"""Tests for pipeline/extract.py: which headlines count for which company."""
from pipeline.extract import find_tickers, is_fund_filing, mentions


def test_symbol_in_brackets_or_cashtag_counts():
    assert find_tickers("Micron (MU) rises") == ["MU"]
    assert find_tickers("$NVDA, $AMD lead chips") == ["NVDA", "AMD"]


def test_bank_research_notes_dont_count_for_the_bank():
    # The bank's analysts talking about other companies, or about markets.
    notes = [
        "JPMorgan downgrades Molson Coors (TAP) to Underweight",
        "Goldman Sachs sees oil averaging $130 a barrel in 2027",
        "Bank of America's Hartnett says tech bonds are diamonds in the rough",
        "Investors turn gloomy on memory chip stocks, Bank of America says",
        "Apple price target lowered to $355 from $360 at JPMorgan",
        "IonQ (IONQ) Gets a Buy from Bank of America Securities",
        "JPMorgan Chase & Co. Has Lowered Expectations for Yelp (NYSE:YELP) Stock Price",
        "Bank of America Drops Nvidia From Top Stock Picks Amid Jensen Huang Investigation",
    ]
    for headline in notes:
        assert not {"JPM", "GS", "BAC"} & set(find_tickers(headline)), headline


def test_the_rated_company_still_counts():
    assert find_tickers("Goldman Sachs downgrades Nike to Neutral") == ["NKE"]
    assert find_tickers("BofA cuts AMD stock price target to $650") == ["AMD"]


def test_news_about_the_bank_itself_still_counts():
    for headline, symbol in [
        ("JPMorgan Stock Falls as Democrats Plan Probe of Epstein Ties", "JPM"),
        ("Goldman Sachs in talks to acquire controlling stake in TMAP Mobility", "GS"),
        ("These Bank of America Branches Are Closing in 2026", "BAC"),
        ("Layoffs at Goldman Sachs hit trading desk", "GS"),            # "at Goldman", but no rating words
        ("Bank of America Stock Drops 3% After Fed Decision", "BAC"),  # here "drops" is about the stock
        # Writing the bank's own symbol means the story is about the bank.
        ("UBS Has Lowered Expectations for Bank of America (NYSE:BAC) Stock Price", "BAC"),
    ]:
        assert mentions(headline, symbol), headline


def test_other_companies_dont_get_the_bank_filter():
    # "Nvidia says" is Nvidia talking about itself, which is news about Nvidia.
    assert mentions("Nvidia says demand for Blackwell chips is sold out", "NVDA")


def test_fund_holding_filings_dont_count():
    # Generated from quarterly filings, weeks after the trades: not news.
    for headline in [
        "Apple Inc. $AAPL Shares Sold by Seamount Financial Group Inc.",
        "WestEnd Advisors LLC Sells 6,035 Shares of JPMorgan Chase & Co. $JPM",
        "Randolph Co Inc Makes New $36.52 Million Investment in Costco Wholesale Corporation $COST",
        "Tesla, Inc. $TSLA Stock: Alps Advisors Inc. Cuts Holdings",
        "Salesforce Inc. $CRM Position Lessened by AIA Group Ltd",
    ]:
        assert is_fund_filing(headline), headline
        assert find_tickers(headline) == [], headline


def test_real_news_with_trading_words_still_counts():
    for headline, symbol in [
        ("Berkshire Hathaway sells stake in Bank of America", "BAC"),   # news, no cashtag
        ("PALANTIR ($PLTR) Releases Q3 2026 Earnings", "PLTR"),         # cashtag, but no holdings verb
        ("Nvidia stock cut to Hold at Morningstar", "NVDA"),            # holdings verb, but no cashtag
    ]:
        assert mentions(headline, symbol), headline
