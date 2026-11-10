"""Tests for pipeline/check.py, with made-up prices and headlines (no network)."""
from datetime import date, timedelta

from pipeline.check import market_signal, merge_checks, story_signal
from pipeline.report import agreement

DAY = date(2026, 11, 9)


def bars(moves: list[float], volumes: list[int]) -> list[dict]:
    """Daily bars ending on DAY, from daily % moves. One bar per calendar day keeps it simple."""
    out, close = [], 100.0
    start = DAY - timedelta(days=len(moves) - 1)
    for k, (move, volume) in enumerate(zip(moves, volumes)):
        close *= 1 + move
        out.append({"day": start + timedelta(days=k), "close": close, "volume": volume})
    return out


WOBBLE = [0.01, -0.01] * 15           # the stock's usual +/-1% days
SPY_FLAT = bars([0.0] * 31, [1] * 31)


def test_big_move_against_the_market_is_evidence():
    stock = bars(WOBBLE + [0.08], [1000] * 31)            # +8% on a flat market day
    m = market_signal(stock, SPY_FLAT, DAY)
    assert m["z"] > 2 and m["evidence"]


def test_moving_with_the_whole_market_is_not_evidence():
    # Everything rose 8% together: nothing company-specific happened.
    stock = bars(WOBBLE + [0.08], [1000] * 31)
    spy = bars(WOBBLE + [0.08], [1] * 31)
    m = market_signal(stock, spy, DAY)
    assert abs(m["excess_return"]) < 0.001 and not m["evidence"]


def test_heavy_volume_alone_is_evidence():
    stock = bars(WOBBLE + [0.0], [1000] * 30 + [2000])     # flat price, twice the usual volume
    m = market_signal(stock, SPY_FLAT, DAY)
    assert m["volume_ratio"] == 2.0 and m["evidence"]


def test_no_market_signal_when_market_closed():
    stock = bars(WOBBLE + [0.08], [1000] * 31)
    assert market_signal(stock, SPY_FLAT, DAY + timedelta(days=1)) is None


def heads(titles_and_sources):
    return [{"title": t, "source": s} for t, s in titles_and_sources]


def test_one_story_across_many_publishers_is_evidence():
    today = heads([(f"Costco declares $30 special dividend ({i})", f"Pub{i}") for i in range(6)]
                  + [(f"Costco deal of the day {i}", "Deals") for i in range(14)])
    earlier = heads([(f"Costco deal of the day {i}", "Deals") for i in range(60)])
    s = story_signal(today, earlier, "COST")
    assert s["evidence"] and {w["word"] for w in s["words"]} >= {"special", "dividend"}
    assert "Costco" not in [w["word"] for w in s["words"]]   # the company's own name isn't a story


def test_one_publisher_repeating_itself_is_not_a_story():
    today = heads([(f"Costco special dividend explained part {i}", "OneBlog") for i in range(10)])
    assert not story_signal(today, [], "COST")["evidence"]


def test_a_word_that_is_always_there_is_not_a_story():
    today = heads([(f"Costco rotisserie chicken {i}", f"Pub{i}") for i in range(10)])
    earlier = heads([(f"Costco rotisserie chicken {i}", f"Pub{i}") for i in range(50)])
    assert not story_signal(today, earlier, "COST")["evidence"]


def test_rechecking_replaces_those_days_and_keeps_older_ones():
    saved = {"spikes": [{"day": "2026-11-01", "symbol": "A", "verdict": "news found"},
                        {"day": "2026-11-09", "symbol": "B", "verdict": "no news found"}]}
    new = [{"day": "2026-11-09", "symbol": "B", "verdict": "news found"}]
    merged = merge_checks(saved, new, [DAY])
    assert [(r["day"], r["verdict"]) for r in merged["spikes"]] == [("2026-11-01", "news found"), ("2026-11-09", "news found")]


def test_agreement_with_hand_checks():
    hand = [{"day": "2026-11-09", "symbol": "NVDA", "verdict": "real"},
            {"day": "2026-11-09", "symbol": "WMT", "verdict": "false"},
            {"day": "2026-11-09", "symbol": "SBUX", "verdict": "minor"},
            {"day": "2026-11-09", "symbol": "BAC", "verdict": "false"}]      # not a spike any more: skipped
    auto = [{"day": "2026-11-09", "symbol": "NVDA", "verdict": "news found"},
            {"day": "2026-11-09", "symbol": "WMT", "verdict": "news found"},
            {"day": "2026-11-09", "symbol": "SBUX", "verdict": "news found"}]
    agree, compared, misses = agreement(hand, auto)
    assert (agree, compared) == (2, 3) and misses == ["2026-11-09 WMT: hand false, auto news found"]
