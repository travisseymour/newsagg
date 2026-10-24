"""
Shared admin login for the NewsAgg and URL shortener admin pages.

Logged-in state lives in Flask's signed session cookie (never the password
itself), and repeated wrong passwords from one IP are locked out for a while.
"""

import hmac
import os
import threading
import time

from flask import request, session

ADMIN_PASSWORD = os.environ.get("NEWSAGG_ADMIN_PASSWORD", "changeme")

MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60

# ip -> timestamps of recent failed logins (per process; the app runs one worker)
_failures: dict[str, list[float]] = {}
_failures_lock = threading.Lock()


def client_ip() -> str:
    """The visitor's IP. Behind a trusted reverse proxy, read it from X-Real-IP."""
    if os.environ.get("NEWSAGG_TRUST_PROXY") == "1":
        return request.headers.get("X-Real-IP", request.remote_addr or "")
    return request.remote_addr or ""


def is_authed() -> bool:
    return session.get("admin") is True


def _recent_failures(ip: str, now: float) -> list[float]:
    recent = [t for t in _failures.get(ip, []) if now - t < LOCKOUT_SECONDS]
    if recent:
        _failures[ip] = recent
    else:
        _failures.pop(ip, None)
    return recent


def try_login(password: str) -> str | None:
    """Log in if the password is right. Returns an error message, or None on success."""
    ip = client_ip()
    now = time.time()
    with _failures_lock:
        if len(_recent_failures(ip, now)) >= MAX_FAILURES:
            return "Too many failed attempts. Try again in 15 minutes."

    if hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
        session.clear()
        session["admin"] = True
        with _failures_lock:
            _failures.pop(ip, None)
        return None

    with _failures_lock:
        _failures.setdefault(ip, []).append(now)
        # Keep memory bounded if many IPs are guessing
        if len(_failures) > 10_000:
            for other in list(_failures):
                _recent_failures(other, now)
    return "Wrong password."


def logout():
    session.pop("admin", None)
