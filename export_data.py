"""Export S&P 500 KPIs to JSON for the iOS app.

Copy this file into ~/Projects/firstapp, then run:
    uv run python export_data.py
Then commit & push — the iOS app reads the JSON straight from GitHub.
"""

from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
KPI_CACHE = HERE / "sp500_kpis.csv"
OUT = HERE / "data" / "sp500.json"

if not KPI_CACHE.exists():
    raise SystemExit("sp500_kpis.csv not found — run the Streamlit app once first.")

kpis = pd.read_csv(KPI_CACHE)

constituents = pd.read_html(
    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    storage_options={"User-Agent": "Mozilla/5.0"},
)[0][["Symbol", "Security", "GICS Sector"]]
constituents.columns = ["ticker", "name", "sector"]
constituents["ticker"] = constituents["ticker"].str.replace(".", "-", regex=False)

data = constituents.merge(kpis, on="ticker", how="left")

# Same display transforms as app.py
data["market_cap_b"] = (data["market_cap"] / 1e9).round(1)
data["profit_margin"] = (data["profit_margin"] * 100).round(1)
data["revenue_growth"] = (data["revenue_growth"] * 100).round(1)
data["roe"] = (data["roe"] * 100).round(1)
data["price"] = data["price"].round(2)
data["pe"] = data["pe"].round(1)
data["dividend_yield"] = data["dividend_yield"].round(2)
data["beta"] = data["beta"].round(2)

cols = ["ticker", "name", "sector", "price", "market_cap_b", "pe",
        "dividend_yield", "profit_margin", "revenue_growth", "roe", "beta"]

OUT.parent.mkdir(exist_ok=True)
data[cols].to_json(OUT, orient="records", indent=2)
print(f"Wrote {len(data)} companies to {OUT}")
