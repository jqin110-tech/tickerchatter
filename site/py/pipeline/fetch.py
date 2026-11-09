"""Download headlines from news feeds.

Two sources per ticker:
  Yahoo Finance's headline feed, the one the first version used.
  Google News search, which goes back further and has more publishers.

Google returns at most 100 results per search, so a busy stock like Nvidia
would only show the last day or two. For the first run (backfill) we
search one day at a time for the last 15 days instead, which gives every
stock a full history straight away.

Every headline comes back as a plain dict so the rest of the pipeline
doesn't care where it came from.
"""
from __future__ import annotations

import calendar
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (TickerChatter news counter; personal project)"}
TIMEOUT = 15
BACKFILL_DAYS = 15


def yahoo_url(symbol: str) -> str:
    return f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"


def google_url(name: str, symbol: str, extra: str) -> str:
    query = quote_plus(f'"{name}" OR "{symbol} stock" {extra}')
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def google_day_urls(name: str, symbol: str, days: int) -> list[str]:
    """One search per day, so the 100-result cap applies to each day separately."""
    today = datetime.now(timezone.utc).date()
    urls = []
    for d in range(days):
        after = today - timedelta(days=d + 1)
        before = today - timedelta(days=d - 1)
        urls.append(google_url(name, symbol, f"after:{after} before:{before}"))
    return urls


def _published(entry) -> datetime | None:
    stamp = entry.get("published_parsed") or entry.get("updated_parsed")
    if not stamp:
        return None
    return datetime.fromtimestamp(calendar.timegm(stamp), tz=timezone.utc)


def _clean_title(title: str, source: str) -> str:
    # Google News adds " - Publisher" to the end of every title.
    if source and title.endswith(f" - {source}"):
        title = title[: -len(source) - 3]
    return re.sub(r"\s+", " ", title).strip()


def fetch_feed(url: str, feed_name: str) -> list[dict]:
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"  skipped a {feed_name} feed: {error}")
        return []

    feed = feedparser.parse(response.content)
    items = []
    for entry in feed.entries:
        published = _published(entry)
        if not published or not entry.get("title"):
            continue
        source = (entry.get("source") or {}).get("title", "") or feed_name
        items.append({
            "title": _clean_title(entry.title, source),
            "link": entry.get("link", ""),
            "source": source,
            "published": published.isoformat(timespec="seconds"),
        })
    return items


def feeds_for(t: dict, backfill: bool) -> list[tuple[str, str]]:
    feeds = [(yahoo_url(t["symbol"]), "Yahoo Finance")]
    if backfill:
        feeds += [(u, "Google News") for u in google_day_urls(t["name"], t["symbol"], BACKFILL_DAYS)]
    else:
        feeds.append((google_url(t["name"], t["symbol"], "when:2d"), "Google News"))
    return feeds


def fetch_all(watchlist: list[dict], backfill: bool = False) -> list[dict]:
    """Fetch every ticker's feeds, 8 at a time so a backfill takes about a minute, not ten."""
    items = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for t in watchlist:
            results = pool.map(lambda f: fetch_feed(*f), feeds_for(t, backfill))
            got = [item for chunk in results for item in chunk]
            print(f"  {t['symbol']:<6} {len(got):>5} headlines")
            items += got
    return items
