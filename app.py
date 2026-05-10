"""
app.py — Flask news aggregator.

Local dev:
    pip install -r requirements.txt
    python app.py              # cache auto-populates on first visit

Railway:
    - Push to GitHub, deploy via railway.com
    - Set NEWSAGG_ADMIN_PASSWORD in environment variables
    - Uses railway.toml for config, gunicorn as WSGI server
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml
from flask import Flask, jsonify, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "cache"
SOURCES_FILE = BASE_DIR / "sources.yaml"

app = Flask(__name__)

# Simple admin password — set via environment variable or change the default
ADMIN_PASSWORD = os.environ.get("NEWSAGG_ADMIN_PASSWORD", "changeme")


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def load_sources_config() -> list[dict]:
    return yaml.safe_load(SOURCES_FILE.read_text())["sources"]


def save_sources_config(sources: list[dict]):
    SOURCES_FILE.write_text(yaml.dump({"sources": sources}, allow_unicode=True, sort_keys=False))


def safe_filename(name: str) -> str:
    """Convert a source name to a safe key/filename (no spaces, no special chars)."""
    return "".join(c if c.isalnum() or c == "-" else "_" for c in name).strip("_")


# Expose safe_filename in Jinja templates so checkbox names always match
app.jinja_env.filters["safe_filename"] = safe_filename


def load_cache(source_name: str) -> dict | None:
    fname = CACHE_DIR / f"{safe_filename(source_name)}.json"
    if fname.exists():
        try:
            return json.loads(fname.read_text())
        except Exception:
            return None
    return None


def load_manifest() -> dict:
    mf = CACHE_DIR / "_manifest.json"
    if mf.exists():
        try:
            return json.loads(mf.read_text())
        except Exception:
            pass
    return {}


def cache_age_seconds() -> int | None:
    """Return the age of the cache in seconds, or None if no cache exists."""
    manifest = load_manifest()
    iso = manifest.get("updated_at", "")
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int((datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return None


def cache_is_stale(max_age_seconds: int = 3600) -> bool:
    """Return True if the cache is older than max_age_seconds (default 1 hour)."""
    age = cache_age_seconds()
    return age is None or age > max_age_seconds


def last_updated() -> str:
    age = cache_age_seconds()
    if age is None:
        return "never"
    if age < 60:
        return "just now"
    if age < 3600:
        return f"{age // 60}m ago"
    if age < 86400:
        return f"{age // 3600}h ago"
    return f"{age // 86400}d ago"


# ─────────────────────────────────────────────
#  Routes
# ─────────────────────────────────────────────

@app.route("/")
def index():
    global _scrape_running
    sources_config = load_sources_config()
    enabled = [s for s in sources_config if s.get("enabled", True)]

    feeds = []
    for source in enabled:
        cache = load_cache(source["name"])
        if cache and cache.get("articles"):
            feeds.append(cache)

    # Auto-trigger scrape if cache is empty or stale (>1 hour) and no scrape is running
    auto_refreshing = False
    if (not feeds or cache_is_stale()) and not _scrape_running:
        import threading
        from scraper import fetch_all

        def run():
            global _scrape_running
            _scrape_running = True
            try:
                fetch_all()
            finally:
                _scrape_running = False

        threading.Thread(target=run, daemon=True).start()
        auto_refreshing = True

    return render_template(
        "index.html",
        feeds=feeds,
        last_updated=last_updated(),
        total_sources=len(enabled),
        refreshing=_scrape_running or auto_refreshing,
    )


@app.route("/search")
def search():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return redirect(url_for("index"))

    sources_config = load_sources_config()
    enabled = [s for s in sources_config if s.get("enabled", True)]

    results = []
    for source in enabled:
        cache = load_cache(source["name"])
        if not cache:
            continue
        matches = [
            a for a in cache.get("articles", [])
            if q in a["title"].lower() or q in a["url"].lower()
        ]
        if matches:
            results.append({**cache, "articles": matches})

    total = sum(len(r["articles"]) for r in results)
    return render_template(
        "index.html",
        feeds=results,
        last_updated=last_updated(),
        total_sources=len(enabled),
        query=q,
        total_results=total,
    )


@app.route("/admin", methods=["GET", "POST"])
def admin():
    """Simple admin panel to toggle sources and add new ones."""
    error = None
    success = None
    authed = request.cookies.get("admin_authed") == ADMIN_PASSWORD

    if request.method == "POST":
        action = request.form.get("action")

        # Login
        if action == "login":
            pw = request.form.get("password", "")
            if pw == ADMIN_PASSWORD:
                resp = redirect(url_for("admin"))
                resp.set_cookie("admin_authed", ADMIN_PASSWORD, httponly=True, samesite="Lax")
                return resp
            else:
                error = "Wrong password."

        elif not authed:
            error = "Not authenticated."

        # Toggle sources
        elif action == "save_toggles":
            sources = load_sources_config()
            for s in sources:
                key = f"enabled_{safe_filename(s['name'])}"
                s["enabled"] = key in request.form
            save_sources_config(sources)
            success = "Sources updated. Re-run the scraper to refresh cache."

        # Add new source
        elif action == "add_source":
            name = request.form.get("new_name", "").strip()
            url = request.form.get("new_url", "").strip()
            category = request.form.get("new_category", "tech").strip()
            if name and url:
                sources = load_sources_config()
                sources.append({"name": name, "url": url, "enabled": True, "category": category})
                save_sources_config(sources)
                success = f"Added '{name}'. Re-run the scraper to fetch it."
            else:
                error = "Name and URL are required."

        # Delete source
        elif action == "delete_source":
            name = request.form.get("source_name", "")
            sources = load_sources_config()
            sources = [s for s in sources if s["name"] != name]
            save_sources_config(sources)
            # Remove cache file
            cf = CACHE_DIR / f"{safe_filename(name)}.json"
            if cf.exists():
                cf.unlink()
            success = f"Deleted '{name}'."

    sources_config = load_sources_config()
    return render_template(
        "admin.html",
        sources=sources_config,
        authed=authed,
        error=error,
        success=success,
        last_updated=last_updated(),
    )


@app.route("/admin/logout")
def admin_logout():
    resp = redirect(url_for("admin"))
    resp.delete_cookie("admin_authed")
    return resp


@app.route("/api/feeds")
def api_feeds():
    """JSON API — handy for debugging or building a custom frontend."""
    sources_config = load_sources_config()
    enabled = [s for s in sources_config if s.get("enabled", True)]
    out = []
    for source in enabled:
        cache = load_cache(source["name"])
        if cache:
            out.append(cache)
    return jsonify({"updated_at": load_manifest().get("updated_at"), "feeds": out})


# Tracks whether a scrape is currently running
_scrape_running = False


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """Trigger a scrape in a background thread."""
    global _scrape_running
    if _scrape_running:
        return jsonify({"status": "already_running"})

    import threading
    from scraper import fetch_all

    def run():
        global _scrape_running
        _scrape_running = True
        try:
            fetch_all()
        finally:
            _scrape_running = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/api/scrape/status")
def api_scrape_status():
    return jsonify({
        "running": _scrape_running,
        "updated_at": load_manifest().get("updated_at", ""),
        "last_updated": last_updated(),
    })


if __name__ == "__main__":
    # Run locally in debug mode
    app.run(debug=True, port=5000)
