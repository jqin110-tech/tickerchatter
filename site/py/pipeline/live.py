"""The on-demand version of the pipeline, for one company at a time.

When someone types a ticker on the website, a small server (worker/)
downloads ~15 days of headlines for it. This file then runs in their
browser through Pyodide and does steps 2 to 4 of the pipeline on them:

  dedupe -> find mentions -> count per 24h window -> z-score

It reuses extract.py and stats.py, so the browser and the hourly job
always agree.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .extract import headline_key, pattern_for
from .stats import score
from .tickers import BY_SYMBOL, WATCHLIST


def resolve(query: str) -> dict:
    """Turn what the visitor typed into a company to look for."""
    q = query.strip()
    for t in WATCHLIST:
        names = [t["symbol"], t["name"], *t["aliases"]]
        if any(q.lower() == n.lower() for n in names):
            return t
    looks_like_symbol = q.isupper() and q.replace(".", "").isalpha() and len(q) <= 5
    if looks_like_symbol:
        return {"symbol": q, "name": q, "sector": "Other", "aliases": []}
    return {"symbol": "", "name": q.title() if q.islower() else q, "sector": "Other", "aliases": [q.title() if q.islower() else q]}


def analyze(items_json: str, company_json: str, now_iso: str, days_fetched: int) -> str:
    items = json.loads(items_json)
    company = json.loads(company_json)
    now = datetime.fromisoformat(now_iso)
    pattern = pattern_for(company)

    # Step 1 already happened on the server. Step 2: drop duplicates.
    seen, unique = set(), []
    for item in items:
        key = headline_key(item["title"])
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    # Step 3: keep the headlines that actually name the company.
    matched = [i for i in unique if pattern.search(i["title"])]
    times = [datetime.fromisoformat(i["published"]) for i in matched]

    # Step 4: count by 24h window and score against the usual level.
    first_seen = now - timedelta(days=days_fetched)
    stats = score(times, first_seen, now)
    recent = sorted(matched, key=lambda i: i["published"], reverse=True)

    return json.dumps({
        "symbol": company.get("symbol") or company["name"],
        "name": company["name"],
        "sector": company.get("sector", "Other"),
        "fetched": len(items),
        "unique": len(unique),
        "matched": len(matched),
        **stats,
        "headlines": recent[:12],
        "rejected_example": next((i["title"] for i in unique if not pattern.search(i["title"])), None),
    })


def resolve_json(query: str) -> str:
    return json.dumps(resolve(query))


__all__ = ["analyze", "resolve_json", "BY_SYMBOL"]
