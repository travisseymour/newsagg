"""
ReddAgg Blueprint — displays top posts from Reddit's front page with images.

This is registered under /reddagg in the main app.
"""

import re
from datetime import datetime, timezone
from html import unescape

import feedparser
from flask import Blueprint, render_template

# Create the blueprint
reddagg_bp = Blueprint(
    "reddagg",
    __name__,
    template_folder="templates",
)

# Reddit RSS feed (limit parameter requests more items, max ~100)
REDDIT_RSS_URL = "https://www.reddit.com/.rss?limit={limit}"
USER_AGENT = "ReddAgg/1.0 (newsagg aggregator)"


def extract_thumbnail(content: str) -> str | None:
    """Extract thumbnail URL from RSS entry content HTML."""
    if not content:
        return None
    # Look for image tags in the content
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', content)
    if match:
        url = unescape(match.group(1))
        # Skip Reddit's tracking pixel and small icons
        if "pixel" not in url and "icon" not in url:
            return url
    # Look for thumbnail links
    match = re.search(
        r'href=["\']([^"\']+\.(?:jpg|jpeg|png|gif|webp))["\']', content, re.I
    )
    if match:
        return unescape(match.group(1))
    return None


def extract_subreddit(link: str) -> str:
    """Extract subreddit from Reddit link."""
    match = re.search(r"reddit\.com/r/([^/]+)", link)
    if match:
        return f"r/{match.group(1)}"
    return ""


def age_label(dt: datetime | None) -> str:
    """Convert datetime to human-readable age."""
    if not dt:
        return ""
    try:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "now"
        if seconds < 3600:
            return f"{seconds // 60}m"
        if seconds < 86400:
            return f"{seconds // 3600}h"
        return f"{seconds // 86400}d"
    except Exception:
        return ""


def fetch_reddit_posts(limit: int = 50) -> tuple[list[dict], str | None]:
    """Fetch top posts from Reddit's front page via RSS."""
    try:
        url = REDDIT_RSS_URL.format(limit=limit)
        feed = feedparser.parse(url, agent=USER_AGENT)

        # Check for errors
        status = getattr(feed, "status", None)
        if status and status >= 400:
            return [], f"HTTP {status} - Reddit may be blocking requests"

        if feed.bozo and not feed.entries:
            return [], f"Feed error: {feed.bozo_exception}"

        posts = []
        for entry in feed.entries[:limit]:
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "").strip()

            if not title or not link:
                continue

            # Get content for thumbnail extraction
            content = ""
            if hasattr(entry, "content") and entry.content:
                content = entry.content[0].get("value", "")
            elif hasattr(entry, "summary"):
                content = entry.summary

            # Parse published date
            pub_date = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    pub_date = datetime(
                        *entry.published_parsed[:6], tzinfo=timezone.utc
                    )
                except Exception:
                    pass

            posts.append(
                {
                    "title": title,
                    "url": link,
                    "permalink": link,
                    "subreddit": extract_subreddit(link),
                    "thumbnail": extract_thumbnail(content),
                    "author": getattr(entry, "author", "").replace("/u/", ""),
                    "age": age_label(pub_date),
                    "domain": "reddit.com",
                }
            )

        return posts, None

    except Exception as e:
        return [], str(e)


@reddagg_bp.route("/")
def index():
    """Display Reddit front page posts with thumbnails."""
    posts, error = fetch_reddit_posts()

    return render_template(
        "reddagg.html",
        posts=posts,
        error=error,
    )
