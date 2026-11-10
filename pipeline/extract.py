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
from typing import Callable

from .tickers import WATCHLIST

# Verbs a bank's research team is the subject of: "Goldman Sachs downgrades
# Nike", "JPMorgan sees oil at $105", "Bank of America's Hartnett says".
_ANALYST_VERBS = (
    r"analysts?|strategists?|economists?|upgrades?|downgrades?|reiterates?|maintains?|"
    r"initiates?|raises?|lowers?|cuts?|sets|sees|says|warns|predicts|forecasts?|expects|"
    r"names|issues|remains|sticks|adjusts|reaffirms|flags|finds|delivers|calls|adds|drops|removes|pulls|just dropped|has (?:raised|lowered|cut)"
)
# Words that only show up in ratings: "Price Target Cut from JPMorgan".
_RATING_WORDS = (
    r"price target|target price|rating|buy|hold|sell|overweight|underweight|"
    r"outperform|underperform|neutral|coverage|upgrade|downgrade"
)


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


def research_note_pattern(t: dict) -> re.Pattern | None:
    """For banks that publish research: matches the bank talking about someone else.

    JPMorgan, Goldman Sachs and Bank of America are named in hundreds of
    headlines a week that are their analysts rating other companies
    ("JPMorgan downgrades DraftKings"). Those say nothing about the bank's own
    stock, and on 2026-11-09 they made BAC look like a spike. Rules:
      1. the bank is the subject of an analyst verb ("Goldman Sachs sees ..."), or
      2. it is the source of a rating ("Buy rating from Bank of America").
    """
    if not t.get("analyst_firm"):
        return None
    names = "|".join(re.escape(a) for a in t["aliases"])
    firm = rf"(?<![A-Za-z])(?:{names})(?:['’]s?)?"
    # Up to three capitalised words between, for "JPMorgan Chase & Co. issues"
    # and "Bank of America Securities remains". Never "Stock" or "Shares":
    # "Bank of America Stock Drops 3%" is news about the bank.
    between = r"(?:\s+(?:(?!Stock\b|Shares\b)[A-Z][\w.]*|&)){0,3}?"
    as_subject = rf"{firm}{between}\s+(?i:{_ANALYST_VERBS})\b"
    quoted = rf"(?i:\b(?:says|according to))\s+{firm}"
    # "from/by/at Goldman" alone is too loose ("layoffs at Goldman"), so it
    # only counts when the headline also has rating words somewhere.
    has_rating = rf"(?=.*(?i:\b(?:{_RATING_WORDS})\b))"
    as_source = rf"{has_rating}.*(?i:\b(?:from|by|at|on))\s+{firm}"
    return re.compile(rf"{as_subject}|{quoted}|^{as_source}")


def own_symbol_pattern(t: dict) -> re.Pattern | None:
    """"Bank of America (NYSE:BAC)" or "$BAC": the headline is about the bank itself."""
    if not t.get("symbol"):
        return None
    sym = re.escape(t["symbol"])
    # Not "(GS.US)": Futu writes that after every company it names.
    return re.compile(rf"\${sym}\b|\((?:[A-Z]+:\s*)?{sym}\)")


def matcher_for(t: dict) -> Callable[[str], bool]:
    """Does a headline count as news about company t?

    It has to name the company. For research banks it also must not be
    one of their analysts talking about another company, unless the bank's
    own symbol is written out, which means the story is about the bank.
    """
    names, note, own = pattern_for(t), research_note_pattern(t), own_symbol_pattern(t)

    def matches(headline: str) -> bool:
        if not names.search(headline):
            return False
        if note and note.search(headline):
            return bool(own and own.search(headline))
        return True

    return matches


_MATCHERS = [(t["symbol"], matcher_for(t)) for t in WATCHLIST]
_BY_SYMBOL = dict(_MATCHERS)


def find_tickers(headline: str) -> list[str]:
    """Return the watchlist symbols mentioned in a headline, in watchlist order."""
    return [symbol for symbol, matches in _MATCHERS if matches(headline)]


def mentions(headline: str, symbol: str) -> bool:
    """One company only: 40x faster than find_tickers when that's all we need."""
    return _BY_SYMBOL[symbol](headline)
