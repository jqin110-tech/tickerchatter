"""Find which tickers a headline mentions.

This replaces the first version's rule ("any all-caps word up to 5
letters"), which counted words like AI, CEO and U.S. as tickers. Now a
word only counts if it matches a known company, and punctuation like
"(MU)" or "$MU," no longer hides the symbol.

The same file runs in two places: GitHub Actions (every hour) and the
visitor's browser (through Pyodide) when someone runs a search on the site.
"""
from __future__ import annotations

import re

from .tickers import WATCHLIST


def headline_key(title: str) -> str:
    """Same story from two feeds -> same key, so it's only counted once."""
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def pattern_for(t: dict) -> re.Pattern:
    """One regex that matches every way a headline might name this company."""
    parts = []
    symbol = t.get("symbol", "")
    if symbol:
        sym = re.escape(symbol)
        parts += [
            rf"\${sym}\b",                         # cashtag: $NVDA
            rf"\((?:[A-Z]+:\s*)?{sym}\)",          # brackets: (NVDA) or (NASDAQ: NVDA)
        ]
        if not t.get("strict"):
            parts.append(rf"(?<![A-Za-z$]){sym}(?![A-Za-z])")  # bare symbol: NVDA
    for alias in t.get("aliases", []):
        # Names are case sensitive, so lowercase "apple" never counts as Apple.
        # ("Apple pie" at the start of a headline still would: a known limit.)
        parts.append(rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])")
    return re.compile("|".join(parts) or r"(?!)")


_PATTERNS = [(t["symbol"], pattern_for(t)) for t in WATCHLIST]


def find_tickers(headline: str) -> list[str]:
    """Return the watchlist symbols mentioned in a headline, in watchlist order."""
    return [symbol for symbol, pattern in _PATTERNS if pattern.search(headline)]
