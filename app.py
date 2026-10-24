"""
Root Flask application for firfly.us

This app serves:
- / → Landing page
- /newsagg/* → NewsAgg news aggregator (via Blueprint)
- /url/* → URL Shortener admin (via Blueprint)
- /<code> → Short URL redirects
"""

import os
import secrets
import subprocess
from pathlib import Path

from flask import Flask, abort, redirect, render_template

from newsagg_bp import newsagg_bp
from reddagg_bp import reddagg_bp
from urlshort_bp import urlshort_bp, get_url_by_code, increment_clicks

BASE_DIR = Path(__file__).parent

app = Flask(__name__)

# Signs the admin session cookie. Without NEWSAGG_SECRET_KEY a random key is
# used, which logs admins out whenever the app restarts.
app.secret_key = os.environ.get("NEWSAGG_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Set NEWSAGG_SECURE_COOKIES=1 when served over HTTPS
    SESSION_COOKIE_SECURE=os.environ.get("NEWSAGG_SECURE_COOKIES") == "1",
)

# Register blueprints
app.register_blueprint(newsagg_bp, url_prefix="/newsagg")
app.register_blueprint(reddagg_bp, url_prefix="/reddagg")
app.register_blueprint(urlshort_bp, url_prefix="/url")


# ─────────────────────────────────────────────
#  Version helper
# ─────────────────────────────────────────────


def get_version() -> str:
    """Return the short git commit hash, or 'dev' if not available."""
    # Railway sets RAILWAY_GIT_COMMIT_SHA; other deployments can set GIT_SHA
    env_sha = os.environ.get("GIT_SHA") or os.environ.get("RAILWAY_GIT_COMMIT_SHA")
    if env_sha:
        return env_sha[:7]  # Short hash (first 7 chars)

    # Fall back to git command for local development
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "dev"


# Cache the version at startup (it won't change while running)
APP_VERSION = get_version()


@app.context_processor
def inject_version():
    """Make version available in all templates."""
    return {"app_version": APP_VERSION}


# ─────────────────────────────────────────────
#  Root routes
# ─────────────────────────────────────────────


@app.route("/")
def landing():
    """Simple landing page for firfly.us"""
    return render_template("landing.html")


# ─────────────────────────────────────────────
#  Short URL redirect (catch-all, must be last)
# ─────────────────────────────────────────────


@app.route("/<code>")
@app.route("/<code>/<path:subpath>")
def short_redirect(code: str, subpath: str = ""):
    """Redirect short URLs to their targets, with optional path passthrough."""
    url_data = get_url_by_code(code)
    if url_data:
        increment_clicks(code)
        target = url_data["url"]
        # Append subpath if passthrough is enabled and subpath exists
        if subpath and url_data.get("passthrough"):
            # Ensure target ends with / before appending
            if not target.endswith("/"):
                target += "/"
            target += subpath
        return redirect(target)
    abort(404)


if __name__ == "__main__":
    # Run locally in debug mode
    # Just load the venv and then run `python app.py`
    app.run(debug=True, port=5000)
