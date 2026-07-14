"""Export S&P 500 KPIs + price/KPI history to JSON for the iOS app.

Standalone: fetches everything itself, so it runs both on your Mac
(uv run python export_data.py) and in GitHub Actions on a schedule.
Uses sp500_kpis.csv as a cache if it's less than 24h old, and
fundamentals_cache.pkl (annual statements + dividends, which only
change quarterly) as a cache if it's less than 7 days old.
"""

import json
import pickle
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import yfinance as yf

HERE = Path(__file__).parent
KPI_CACHE = HERE / "sp500_kpis.csv"
FUNDAMENTALS_CACHE = HERE / "fundamentals_cache.pkl"
OUT_KPIS = HERE / "data" / "sp500.json"
OUT_HISTORY = HERE / "data" / "history.json"
OUT_KPI_HISTORY = HERE / "data" / "kpi_history.json"


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


def _annual_row(df: pd.DataFrame, *row_names: str) -> dict:
    """First matching row from an annual statement, as {date_str: value}, NaNs dropped."""
    for row in row_names:
        if row in df.index:
            return {d.strftime("%Y-%m-%d"): float(v) for d, v in df.loc[row].dropna().items()}
    return {}


def fetch_fundamentals_one(ticker: str) -> dict:
    """Annual income statement / balance sheet rows + full dividend history for one ticker."""
    empty = {"ticker": ticker, "revenue": {}, "net_income": {}, "eps": {},
              "equity": {}, "shares": {}, "dividends": {}}
    try:
        t = yf.Ticker(ticker)
        inc = t.income_stmt
        bs = t.balance_sheet
        div = t.dividends
        return {
            "ticker": ticker,
            "revenue": _annual_row(inc, "Total Revenue"),
            "net_income": _annual_row(inc, "Net Income"),
            "eps": _annual_row(inc, "Diluted EPS", "Basic EPS"),
            "equity": _annual_row(bs, "Stockholders Equity"),
            "shares": _annual_row(bs, "Ordinary Shares Number", "Share Issued"),
            "dividends": {d.strftime("%Y-%m-%d"): float(v) for d, v in div.items()} if not div.empty else {},
        }
    except Exception:
        return empty


def load_fundamentals(tickers: list[str]) -> dict[str, dict]:
    if FUNDAMENTALS_CACHE.exists() and time.time() - FUNDAMENTALS_CACHE.stat().st_mtime < 7 * 24 * 3600:
        print("Using cached fundamentals history (less than 7d old)")
        with open(FUNDAMENTALS_CACHE, "rb") as f:
            return pickle.load(f)
    print(f"Fetching fundamentals history for {len(tickers)} tickers (a few minutes)…")
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(fetch_fundamentals_one, tickers))
    result = {row["ticker"]: row for row in rows}
    with open(FUNDAMENTALS_CACHE, "wb") as f:
        pickle.dump(result, f)
    return result


def _sorted_items(d: dict) -> list[tuple[pd.Timestamp, float]]:
    return sorted((pd.Timestamp(k), v) for k, v in d.items())


def _step_lookup(items: list[tuple[pd.Timestamp, float]], as_of: pd.Timestamp) -> float | None:
    """Most recent value with date <= as_of (items must be sorted ascending)."""
    val = None
    for d, v in items:
        if d <= as_of:
            val = v
        else:
            break
    return val


def build_kpi_history(dates: list[str], prices: list[float], fund: dict) -> dict:
    """Real (not approximated) weekly P/E, market cap, dividend yield — built from
    the weekly price series combined with the most-recently-known annual EPS/shares
    or trailing-12mo dividends as of each date — plus sparse annual revenue growth,
    profit margin, and ROE (only ~4 fiscal years are available for free).
    """
    eps_items = _sorted_items(fund.get("eps", {}))
    shares_items = _sorted_items(fund.get("shares", {}))
    revenue_items = _sorted_items(fund.get("revenue", {}))
    net_income_items = _sorted_items(fund.get("net_income", {}))
    equity_items = _sorted_items(fund.get("equity", {}))
    div_items = _sorted_items(fund.get("dividends", {}))

    pe_series, cap_series, yield_series = [], [], []
    for date_str, price in zip(dates, prices):
        as_of = pd.Timestamp(date_str)

        eps = _step_lookup(eps_items, as_of)
        pe_series.append(round(price / eps, 1) if eps and eps > 0 else None)

        shares = _step_lookup(shares_items, as_of)
        cap_series.append(round(price * shares / 1e9, 1) if shares else None)

        window_start = as_of - pd.Timedelta(days=365)
        div_sum = sum(v for d, v in div_items if window_start < d <= as_of)
        yield_series.append(round(div_sum / price * 100, 2) if price else None)

    revenue_growth = {"dates": [], "values": []}
    for i in range(1, len(revenue_items)):
        prev_d, prev_v = revenue_items[i - 1]
        cur_d, cur_v = revenue_items[i]
        if prev_v:
            revenue_growth["dates"].append(cur_d.strftime("%Y-%m-%d"))
            revenue_growth["values"].append(round((cur_v - prev_v) / prev_v * 100, 1))

    net_income_by_date = dict(net_income_items)
    profit_margin = {"dates": [], "values": []}
    for d, rev in revenue_items:
        ni = net_income_by_date.get(d)
        if ni is not None and rev:
            profit_margin["dates"].append(d.strftime("%Y-%m-%d"))
            profit_margin["values"].append(round(ni / rev * 100, 1))

    equity_by_date = dict(equity_items)
    roe = {"dates": [], "values": []}
    for d, ni in net_income_items:
        eq = equity_by_date.get(d)
        if eq:
            roe["dates"].append(d.strftime("%Y-%m-%d"))
            roe["values"].append(round(ni / eq * 100, 1))

    return {
        "pe": pe_series,
        "market_cap_b": cap_series,
        "dividend_yield": yield_series,
        "revenue_growth": revenue_growth,
        "profit_margin": profit_margin,
        "roe": roe,
    }


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

# ---------------------------------------------------------------- KPI history
fundamentals = load_fundamentals(list(history.keys()))

kpi_history = {}
for ticker, series in history.items():
    kpi_history[ticker] = build_kpi_history(
        series["dates"], series["closes"], fundamentals.get(ticker, {}))

with open(OUT_KPI_HISTORY, "w") as f:
    json.dump(kpi_history, f, separators=(",", ":"))

size_mb = OUT_KPI_HISTORY.stat().st_size / 1e6
print(f"Wrote KPI history for {len(kpi_history)} tickers to {OUT_KPI_HISTORY} ({size_mb:.1f} MB)")
