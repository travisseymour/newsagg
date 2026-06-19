"""
URL Shortener Blueprint — simple short URL service.

Admin routes are registered under /url in the main app.
Redirects happen at /<code> (root level, handled in app.py).
"""

import os
import random
import sqlite3
import string
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "urlshort.db"

# Create the blueprint
urlshort_bp = Blueprint(
    "urlshort",
    __name__,
    template_folder="templates",
)

# Reuse the same admin password as newsagg
ADMIN_PASSWORD = os.environ.get("NEWSAGG_ADMIN_PASSWORD", "changeme")

# Characters used for generating short codes (no ambiguous chars like 0/O, 1/l)
CODE_CHARS = string.ascii_lowercase + string.digits
CODE_CHARS = CODE_CHARS.replace("0", "").replace("o", "").replace("l", "").replace("1", "")


# ─────────────────────────────────────────────
#  Database helpers
# ─────────────────────────────────────────────


def get_db() -> sqlite3.Connection:
    """Get a database connection, creating the table if needed."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("""
        CREATE TABLE IF NOT EXISTS urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            url TEXT NOT NULL,
            created_at TEXT NOT NULL,
            clicks INTEGER DEFAULT 0,
            passthrough INTEGER DEFAULT 0
        )
    """)
    # Migration: add passthrough column if it doesn't exist (for existing DBs)
    try:
        db.execute("ALTER TABLE urls ADD COLUMN passthrough INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists
    db.commit()
    return db


def generate_code(length: int = 6) -> str:
    """Generate a random short code."""
    return "".join(random.choices(CODE_CHARS, k=length))


def code_exists(code: str) -> bool:
    """Check if a code already exists in the database."""
    db = get_db()
    row = db.execute("SELECT 1 FROM urls WHERE code = ?", (code,)).fetchone()
    db.close()
    return row is not None


def create_short_url(url: str, custom_code: str | None = None, passthrough: bool = False) -> dict:
    """
    Create a new short URL.
    Returns {"code": ..., "url": ..., "passthrough": ...} on success.
    Returns {"error": ...} on failure.
    """
    # Generate or validate code
    if custom_code:
        code = custom_code.strip().lower()
        # Validate custom code
        if len(code) < 2 or len(code) > 32:
            return {"error": "Custom code must be 2-32 characters"}
        if not all(c in (string.ascii_lowercase + string.digits + "-_") for c in code):
            return {"error": "Custom code can only contain letters, numbers, hyphens, and underscores"}
        if code_exists(code):
            return {"error": f"Code '{code}' is already taken"}
    else:
        # Generate unique code
        code = generate_code()
        attempts = 0
        while code_exists(code) and attempts < 10:
            code = generate_code()
            attempts += 1
        if code_exists(code):
            return {"error": "Could not generate unique code, try again"}

    # Validate URL
    url = url.strip()
    if not url:
        return {"error": "URL is required"}
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Insert into database
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    try:
        db.execute(
            "INSERT INTO urls (code, url, created_at, clicks, passthrough) VALUES (?, ?, ?, 0, ?)",
            (code, url, now, 1 if passthrough else 0),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.close()
        return {"error": f"Code '{code}' is already taken"}
    db.close()

    return {"code": code, "url": url, "passthrough": passthrough}


def get_url_by_code(code: str) -> dict | None:
    """Get URL info by short code."""
    db = get_db()
    row = db.execute("SELECT * FROM urls WHERE code = ?", (code,)).fetchone()
    db.close()
    if row:
        return dict(row)
    return None


def increment_clicks(code: str):
    """Increment the click count for a short URL."""
    db = get_db()
    db.execute("UPDATE urls SET clicks = clicks + 1 WHERE code = ?", (code,))
    db.commit()
    db.close()


def get_all_urls() -> list[dict]:
    """Get all short URLs, newest first."""
    db = get_db()
    rows = db.execute("SELECT * FROM urls ORDER BY id DESC").fetchall()
    db.close()
    return [dict(r) for r in rows]


def delete_url(code: str) -> bool:
    """Delete a short URL by code. Returns True if deleted."""
    db = get_db()
    cursor = db.execute("DELETE FROM urls WHERE code = ?", (code,))
    db.commit()
    deleted = cursor.rowcount > 0
    db.close()
    return deleted


# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────


@urlshort_bp.route("/")
def admin():
    """Admin panel to manage short URLs."""
    error = None
    success = None
    authed = request.cookies.get("urlshort_authed") == ADMIN_PASSWORD

    return render_template(
        "urlshort_admin.html",
        urls=get_all_urls() if authed else [],
        authed=authed,
        error=error,
        success=success,
    )


@urlshort_bp.route("/", methods=["POST"])
def admin_post():
    """Handle admin form submissions."""
    error = None
    success = None
    authed = request.cookies.get("urlshort_authed") == ADMIN_PASSWORD

    action = request.form.get("action")

    # Login
    if action == "login":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            resp = redirect(url_for("urlshort.admin"))
            resp.set_cookie("urlshort_authed", ADMIN_PASSWORD, httponly=True, samesite="Lax")
            return resp
        else:
            error = "Wrong password."

    elif not authed:
        error = "Not authenticated."

    # Create new short URL
    elif action == "create":
        target_url = request.form.get("url", "").strip()
        custom_code = request.form.get("custom_code", "").strip() or None
        passthrough = "passthrough" in request.form
        result = create_short_url(target_url, custom_code, passthrough)
        if "error" in result:
            error = result["error"]
        else:
            pt_note = " (with path passthrough)" if result.get("passthrough") else ""
            success = f"Created: /{result['code']} → {result['url']}{pt_note}"

    # Delete short URL
    elif action == "delete":
        code = request.form.get("code", "")
        if delete_url(code):
            success = f"Deleted /{code}"
        else:
            error = f"Could not find /{code}"

    return render_template(
        "urlshort_admin.html",
        urls=get_all_urls() if authed else [],
        authed=authed,
        error=error,
        success=success,
    )


@urlshort_bp.route("/logout")
def logout():
    """Clear admin session."""
    resp = redirect(url_for("urlshort.admin"))
    resp.delete_cookie("urlshort_authed")
    return resp


@urlshort_bp.route("/api/shorten", methods=["POST"])
def api_shorten():
    """JSON API to create a short URL."""
    authed = request.cookies.get("urlshort_authed") == ADMIN_PASSWORD
    if not authed:
        return jsonify({"error": "Not authenticated"}), 401

    data = request.get_json() or {}
    url = data.get("url", "")
    custom_code = data.get("code")
    passthrough = data.get("passthrough", False)

    result = create_short_url(url, custom_code, passthrough)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@urlshort_bp.route("/api/urls")
def api_urls():
    """JSON API to list all short URLs."""
    authed = request.cookies.get("urlshort_authed") == ADMIN_PASSWORD
    if not authed:
        return jsonify({"error": "Not authenticated"}), 401
    return jsonify({"urls": get_all_urls()})
