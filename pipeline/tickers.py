"""The watchlist: every ticker TickerChatter tracks.

Each entry has the symbol, a display name, a sector, and "aliases": the
names headlines actually use. Headlines say "Nvidia", not "NVDA", so
without aliases most mentions would be missed.

`strict=True` means the symbol is also a common word or too short to trust
on its own (like "ARM" or "NOW"), so it only counts when written as a
cashtag ($ARM) or in brackets (ARM). The aliases still count normally.

`analyst_firm=True` marks banks whose research teams rate other companies
all day ("JPMorgan downgrades Nike"). Those headlines are skipped for the
bank, see extract.research_note_pattern.
"""

WATCHLIST = [
    # Semiconductors
    {"symbol": "NVDA", "name": "Nvidia", "sector": "Semiconductors", "aliases": ["Nvidia", "NVIDIA"]},
    {"symbol": "AMD", "name": "AMD", "sector": "Semiconductors", "aliases": ["Advanced Micro Devices"]},
    {"symbol": "MU", "name": "Micron", "sector": "Semiconductors", "aliases": ["Micron"]},
    {"symbol": "INTC", "name": "Intel", "sector": "Semiconductors", "aliases": ["Intel"]},
    {"symbol": "AVGO", "name": "Broadcom", "sector": "Semiconductors", "aliases": ["Broadcom"]},
    {"symbol": "TSM", "name": "TSMC", "sector": "Semiconductors", "aliases": ["TSMC", "Taiwan Semiconductor"]},
    {"symbol": "ARM", "name": "Arm Holdings", "sector": "Semiconductors", "aliases": ["Arm Holdings"], "strict": True},
    {"symbol": "SMCI", "name": "Super Micro", "sector": "Semiconductors", "aliases": ["Super Micro", "Supermicro"]},
    # Big tech
    {"symbol": "AAPL", "name": "Apple", "sector": "Big tech", "aliases": ["Apple"]},
    {"symbol": "MSFT", "name": "Microsoft", "sector": "Big tech", "aliases": ["Microsoft"]},
    {"symbol": "GOOGL", "name": "Alphabet", "sector": "Big tech", "aliases": ["Alphabet", "Google"]},
    {"symbol": "AMZN", "name": "Amazon", "sector": "Big tech", "aliases": ["Amazon"]},
    {"symbol": "META", "name": "Meta", "sector": "Big tech", "aliases": ["Meta Platforms", "Meta"]},
    {"symbol": "TSLA", "name": "Tesla", "sector": "Big tech", "aliases": ["Tesla"]},
    {"symbol": "NFLX", "name": "Netflix", "sector": "Big tech", "aliases": ["Netflix"]},
    # Software
    {"symbol": "ORCL", "name": "Oracle", "sector": "Software", "aliases": ["Oracle"]},
    {"symbol": "CRM", "name": "Salesforce", "sector": "Software", "aliases": ["Salesforce"]},
    {"symbol": "ADBE", "name": "Adobe", "sector": "Software", "aliases": ["Adobe"]},
    {"symbol": "PLTR", "name": "Palantir", "sector": "Software", "aliases": ["Palantir"]},
    {"symbol": "CRWD", "name": "CrowdStrike", "sector": "Software", "aliases": ["CrowdStrike"]},
    {"symbol": "SNOW", "name": "Snowflake", "sector": "Software", "aliases": ["Snowflake"], "strict": True},
    {"symbol": "SHOP", "name": "Shopify", "sector": "Software", "aliases": ["Shopify"], "strict": True},
    {"symbol": "UBER", "name": "Uber", "sector": "Software", "aliases": ["Uber"]},
    # Finance
    {"symbol": "JPM", "name": "JPMorgan", "sector": "Finance", "aliases": ["JPMorgan", "JP Morgan", "J.P. Morgan"], "analyst_firm": True},
    {"symbol": "GS", "name": "Goldman Sachs", "sector": "Finance", "aliases": ["Goldman Sachs", "Goldman"], "strict": True, "analyst_firm": True},
    {"symbol": "BAC", "name": "Bank of America", "sector": "Finance", "aliases": ["Bank of America", "BofA"], "analyst_firm": True},
    {"symbol": "COIN", "name": "Coinbase", "sector": "Finance", "aliases": ["Coinbase"], "strict": True},
    {"symbol": "BRK.B", "name": "Berkshire Hathaway", "sector": "Finance", "aliases": ["Berkshire Hathaway", "Berkshire"]},
    # Consumer
    {"symbol": "WMT", "name": "Walmart", "sector": "Consumer", "aliases": ["Walmart"]},
    {"symbol": "COST", "name": "Costco", "sector": "Consumer", "aliases": ["Costco"], "strict": True},
    {"symbol": "DIS", "name": "Disney", "sector": "Consumer", "aliases": ["Disney"], "strict": True},
    {"symbol": "NKE", "name": "Nike", "sector": "Consumer", "aliases": ["Nike"]},
    {"symbol": "SBUX", "name": "Starbucks", "sector": "Consumer", "aliases": ["Starbucks"]},
    {"symbol": "MCD", "name": "McDonald's", "sector": "Consumer", "aliases": ["McDonald's", "McDonalds"]},
    # Health
    {"symbol": "LLY", "name": "Eli Lilly", "sector": "Health", "aliases": ["Eli Lilly", "Lilly"]},
    {"symbol": "PFE", "name": "Pfizer", "sector": "Health", "aliases": ["Pfizer"]},
    {"symbol": "UNH", "name": "UnitedHealth", "sector": "Health", "aliases": ["UnitedHealth"]},
    # Industrials and energy
    {"symbol": "BA", "name": "Boeing", "sector": "Industrials", "aliases": ["Boeing"], "strict": True},
    {"symbol": "XOM", "name": "Exxon Mobil", "sector": "Industrials", "aliases": ["Exxon Mobil", "ExxonMobil", "Exxon"]},
    {"symbol": "CVX", "name": "Chevron", "sector": "Industrials", "aliases": ["Chevron"]},
]

BY_SYMBOL = {t["symbol"]: t for t in WATCHLIST}
