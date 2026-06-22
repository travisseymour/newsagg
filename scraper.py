"""
GEMSedit: Environment Editor for GEMS (Graphical Environment Management System)
Copyright (C) 2021-2026 Travis L. Seymour, PhD

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import feedparser
import yaml

"""
scraper.py — fetch all enabled RSS feeds and write results to cache/.

Run this directly:
    python scraper.py

On Railway, the app auto-triggers this when the cache is empty or stale (>1 hour).
Manual refresh is available via the UI button or POST /api/scrape.
"""

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / "cache"
SOURCES_FILE = BASE_DIR / "sources.yaml"
ARTICLES_PER_SOURCE = 15

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


def parse_date(entry) -> str:
    """Return an ISO-8601 string from whatever date fields feedparser gives us."""
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    # Fall back to raw string
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                return parsedate_to_datetime(raw).isoformat()
            except Exception:
                return raw
    return ""


def age_label(iso_str: str) -> str:
    """Convert an ISO timestamp to a human-readable age like '3h' or '2d'."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{seconds // 60}m"
        if seconds < 86400:
            return f"{seconds // 3600}h"
        days = seconds // 86400
        if days < 30:
            return f"{days}d"
        months = days // 30
        return f"{months}mo"
    except Exception:
        return ""


def fetch_source(source: dict) -> dict:
    name = source["name"]
    url = source["url"]
    log.info("Fetching %s ...", name)
    try:
        feed = feedparser.parse(url, agent="NewsAgg/1.0 (self-hosted aggregator)")

        # Log feed status for debugging
        status = getattr(feed, "status", "unknown")
        log.info("  HTTP status: %s", status)
        log.info("  Total entries: %d", len(feed.entries))

        if feed.bozo and not feed.entries:
            log.warning("  ⚠  bozo feed for %s: %s", name, feed.bozo_exception)
        elif feed.bozo:
            log.warning("  ⚠  bozo flag set but has entries: %s", feed.bozo_exception)

        articles = []
        skipped = 0
        for entry in feed.entries[:ARTICLES_PER_SOURCE]:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()
            if not title or not link:
                skipped += 1
                continue
            pub = parse_date(entry)
            articles.append(
                {
                    "title": title,
                    "url": link,
                    "published": pub,
                    "age": age_label(pub),
                }
            )

        if skipped > 0:
            log.info("  Skipped %d entries (missing title or link)", skipped)

        # Sort articles by published date (newest first)
        articles.sort(key=lambda a: a["published"] or "", reverse=True)

        # Detect potential issues
        error_msg = None
        if len(feed.entries) == 0 and status == 200:
            error_msg = "Feed returned 0 entries (possible rate limit or access restriction)"
            log.warning("  ⚠  %s", error_msg)
        elif len(articles) == 0 and len(feed.entries) > 0:
            error_msg = f"All {len(feed.entries)} entries skipped (missing title or link)"
            log.warning("  ⚠  %s", error_msg)

        result = {
            "name": name,
            "url": url,
            "category": source.get("category", "tech"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "articles": articles,
            "error": error_msg,
        }
        log.info("  ✓ %d articles", len(articles))
        return result

    except Exception as exc:
        log.error("  ✗ failed: %s", exc)
        return {
            "name": name,
            "url": url,
            "category": source.get("category", "tech"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "articles": [],
            "error": str(exc),
        }


def safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c == "-" else "_" for c in name).strip("_")


def fetch_all():
    CACHE_DIR.mkdir(exist_ok=True)
    sources = yaml.safe_load(SOURCES_FILE.read_text())["sources"]

    enabled = [s for s in sources if s.get("enabled", True)]
    log.info("Fetching %d enabled sources...", len(enabled))

    for source in enabled:
        data = fetch_source(source)
        fname = CACHE_DIR / f"{safe_filename(source['name'])}.json"
        fname.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        time.sleep(0.5)  # be polite

    # Write a manifest so the Flask app knows what's available
    manifest = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sources": [safe_filename(s["name"]) for s in enabled],
    }
    (CACHE_DIR / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    log.info("Done. Manifest written.")


if __name__ == "__main__":
    fetch_all()
