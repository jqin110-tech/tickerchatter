"""Tests for how run.py decides what to search and what to keep."""
from datetime import datetime, timedelta, timezone

from pipeline import stats
from pipeline.run import days_to_search, needs_narrow, record_day, score_ticker
from pipeline.stats import pacific_today

PST = timezone(timedelta(hours=-8))
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=PST).astimezone(timezone.utc)
TODAY = pacific_today(NOW)


def item(title: str, when: datetime) -> dict:
    return {"title": title, "published": when.isoformat()}


def full_store() -> dict:
    """Every day already searched, an hour ago."""
    store = {"headlines": {}, "days": {}}
    for day in days_to_search(store, "NVDA", NOW):
        record_day(store, "NVDA", day, [], NOW - timedelta(hours=1))
    return store


def test_first_run_searches_every_day():
    assert len(days_to_search({"days": {}}, "NVDA", NOW)) == stats.CHART_DAYS


def test_later_runs_only_search_today():
    assert days_to_search(full_store(), "NVDA", NOW) == [TODAY]


def test_yesterday_is_searched_once_more_after_midnight():
    store = full_store()
    tomorrow_morning = NOW + timedelta(hours=13)  # 01:00 the next day
    assert days_to_search(store, "NVDA", tomorrow_morning) == [TODAY + timedelta(days=1), TODAY]


def test_new_search_replaces_old_instead_of_adding():
    # Adding would let today (searched every hour) pile up more than past days.
    store = {"days": {}}
    morning = datetime(2026, 11, 4, 9, 0, tzinfo=PST)
    record_day(store, "NVDA", TODAY, [item("Nvidia a", morning), item("Nvidia b", morning)], NOW)
    record_day(store, "NVDA", TODAY, [item("Nvidia c", morning)], NOW)
    assert len(store["days"]["NVDA"][TODAY.isoformat()]["times"]) == 1


def test_failed_search_keeps_what_we_had():
    store = {"days": {}}
    record_day(store, "NVDA", TODAY, [item("Nvidia a", datetime(2026, 11, 4, 9, 0, tzinfo=PST))], NOW)
    record_day(store, "NVDA", TODAY, None, NOW)
    assert len(store["days"]["NVDA"][TODAY.isoformat()]["times"]) == 1


def test_only_headlines_from_the_searched_day_and_company_count():
    store = {"days": {}}
    record_day(store, "NVDA", TODAY, [
        item("Nvidia today", datetime(2026, 11, 4, 9, 0, tzinfo=PST)),
        item("Nvidia yesterday", datetime(2026, 11, 3, 23, 0, tzinfo=PST)),  # Google's loose date filter
        item("Apple today", datetime(2026, 11, 4, 9, 0, tzinfo=PST)),        # doesn't name Nvidia
    ], NOW)
    assert len(store["days"]["NVDA"][TODAY.isoformat()]["times"]) == 1


def test_capped_stock_moves_to_narrow_query_and_redoes_every_day():
    store = full_store()
    store["tier"] = {}
    store["days"]["NVDA"][TODAY.isoformat()]["capped"] = True
    assert needs_narrow(store, "NVDA")
    store["tier"]["NVDA"] = "narrow"
    assert len(days_to_search(store, "NVDA", NOW)) == stats.CHART_DAYS  # nothing mixes the two queries


def test_days_counted_under_an_older_rule_are_searched_again():
    # When extract.py's counting rule changes, an old day's count can't be
    # compared with a new today. It's treated as missing until searched again.
    store = full_store()
    for snap in store["days"]["NVDA"].values():
        del snap["rules"]   # saved before COUNT_RULES existed
    assert len(days_to_search(store, "NVDA", NOW)) == stats.CHART_DAYS
    assert score_ticker(store, "NVDA", NOW)["baseline_days"] == 0
