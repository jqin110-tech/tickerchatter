"""Download headlines from news feeds.

Counting uses one Google News search per ticker per Pacific-time day
(Google's date filters work in California time). Every day is searched
the same way, so every day gets the same 100-result cap.

That matters: the first version searched 2-day ranges, and the newest
range was mostly in the future, so it squeezed its 100 results into a
few hours and "today" looked 2-3x busier than any past day.

Yahoo Finance's feed only has the latest ~20 stories, so it's fetched to
show recent headlines on the site but never counted.

Every headline comes back as a plain dict so the rest of the pipeline
doesn't care where it came from.
"""
from __future__ import annotations

import calendar
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (TickerChatter news counter; personal project)"}
TIMEOUT = 15
GOOGLE_CAP = 100   # Google News never returns more than this per search


def yahoo_url(symbol: str) -> str:
    return f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"


# The broad query catches every headline naming the company. For the
# busiest stocks it hits the 100 cap every day, and a capped count can't be
# compared with anything, so those switch to the narrow query: a smaller
# sample of the same news, but taken the same way every day.
QUERIES = {
    "broad": '"{name}" OR "{symbol} stock"',
    "narrow": '"{name} stock"',
}


def google_day_url(t: dict, day: date, tier: str = "broad") -> str:
    """Exactly one Pacific day: after: is inclusive, before: is not."""
    query = QUERIES[tier].format(name=t["name"], symbol=t["symbol"])
    query += f" after:{day} before:{day + timedelta(days=1)}"
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"


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


def fetch_feed(url: str, feed_name: str, feed: str) -> list[dict] | None:
    """Returns None if the request failed, so a broken search is never
    mistaken for a day with no news.

    feed says which kind of search found the item ("yahoo", "google-day").
    "source" is the publisher, which can't tell feeds apart: a Google result
    published by Yahoo Finance is also labelled "Yahoo Finance".
    """
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as error:
        print(f"  skipped a {feed_name} feed: {error}")
        return None

    parsed = feedparser.parse(response.content)
    items = []
    for entry in parsed.entries:
        published = _published(entry)
        if not published or not entry.get("title"):
            continue
        source = (entry.get("source") or {}).get("title", "") or feed_name
        items.append({
            "title": _clean_title(entry.title, source),
            "link": entry.get("link", ""),
            "source": source,
            "published": published.isoformat(timespec="seconds"),
            "feed": feed,
        })
    return items


def fetch_days(searches: list[tuple[dict, date, str]]) -> list[tuple[dict, date, str, list[dict] | None]]:
    """Run one Google search per (ticker, day, query tier), 8 at a time."""
    def one(job):
        t, day, tier = job
        return t, day, tier, fetch_feed(google_day_url(t, day, tier), "Google News", "google-day")
    with ThreadPoolExecutor(max_workers=8) as pool:
        return list(pool.map(one, searches))


def fetch_yahoo(watchlist: list[dict]) -> list[dict]:
    """Latest headlines per ticker, for display only."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = pool.map(lambda t: fetch_feed(yahoo_url(t["symbol"]), "Yahoo Finance", "yahoo") or [], watchlist)
        return [item for chunk in results for item in chunk]
