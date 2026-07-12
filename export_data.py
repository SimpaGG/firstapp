"""Export S&P 500 KPIs + price history to JSON for the iOS app.

Standalone: fetches everything itself, so it runs both on your Mac
(uv run python export_data.py) and in GitHub Actions on a schedule.
Uses sp500_kpis.csv as a cache if it's less than 24h old.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import yfinance as yf

HERE = Path(__file__).parent
KPI_CACHE = HERE / "sp500_kpis.csv"
OUT_KPIS = HERE / "data" / "sp500.json"
OUT_HISTORY = HERE / "data" / "history.json"


def get_constituents() -> pd.DataFrame:
    df = pd.read_html(
        "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        storage_options={"User-Agent": "Mozilla/5.0"},
    )[0][["Symbol", "Security", "GICS Sector"]]
    df.columns = ["ticker", "name", "sector"]
    df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)
    return df


def fetch_kpis_one(ticker: str) -> dict:
    try:
        info = yf.Ticker(ticker).info
        return {
            "ticker": ticker,
            "price": info.get("currentPrice"),
            "market_cap": info.get("marketCap"),
            "pe": info.get("trailingPE"),
            "dividend_yield": info.get("dividendYield"),
            "profit_margin": info.get("profitMargins"),
            "revenue_growth": info.get("revenueGrowth"),
            "roe": info.get("returnOnEquity"),
            "beta": info.get("beta"),
        }
    except Exception:
        return {"ticker": ticker}


def load_kpis(tickers: list[str]) -> pd.DataFrame:
    if KPI_CACHE.exists() and time.time() - KPI_CACHE.stat().st_mtime < 24 * 3600:
        print("Using cached KPIs (less than 24h old)")
        return pd.read_csv(KPI_CACHE)
    print(f"Fetching fundamentals for {len(tickers)} tickers (a few minutes)…")
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(fetch_kpis_one, tickers))
    df = pd.DataFrame(rows)
    df.to_csv(KPI_CACHE, index=False)
    return df


# ---------------------------------------------------------------- KPIs
constituents = get_constituents()
kpis = load_kpis(constituents["ticker"].tolist())
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
