"""Export S&P 500 KPIs + price history to JSON for the iOS app.

Run:  uv run python export_data.py
Then commit & push — the iOS app reads both JSON files straight from GitHub.
"""

import json
from pathlib import Path

import pandas as pd
import yfinance as yf

HERE = Path(__file__).parent
KPI_CACHE = HERE / "sp500_kpis.csv"
OUT_KPIS = HERE / "data" / "sp500.json"
OUT_HISTORY = HERE / "data" / "history.json"

if not KPI_CACHE.exists():
    raise SystemExit("sp500_kpis.csv not found — run the Streamlit app once first.")

# ---------------------------------------------------------------- KPIs
kpis = pd.read_csv(KPI_CACHE)

constituents = pd.read_html(
    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    storage_options={"User-Agent": "Mozilla/5.0"},
)[0][["Symbol", "Security", "GICS Sector"]]
constituents.columns = ["ticker", "name", "sector"]
constituents["ticker"] = constituents["ticker"].str.replace(".", "-", regex=False)

data = constituents.merge(kpis, on="ticker", how="left")

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

OUT_KPIS.parent.mkdir(exist_ok=True)
data[cols].to_json(OUT_KPIS, orient="records", indent=2)
print(f"Wrote {len(data)} companies to {OUT_KPIS}")

# ---------------------------------------------------------------- price history
# 5 years of weekly closes for every ticker, one bulk download (takes ~1 min).
tickers = data["ticker"].dropna().tolist()
print("Downloading 5y weekly price history for all tickers…")
closes = yf.download(tickers, period="5y", interval="1wk",
                     auto_adjust=True, progress=True)["Close"]

history = {}
for ticker in tickers:
    if ticker not in closes.columns:
        continue
    series = closes[ticker].dropna().round(2)
    if series.empty:
        continue
    history[ticker] = {
        "dates": [d.strftime("%Y-%m-%d") for d in series.index],
        "closes": series.tolist(),
    }

with open(OUT_HISTORY, "w") as f:
    json.dump(history, f, separators=(",", ":"))

size_mb = OUT_HISTORY.stat().st_size / 1e6
print(f"Wrote history for {len(history)} tickers to {OUT_HISTORY} ({size_mb:.1f} MB)")
