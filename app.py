"""FirstApp — S&P 500 stock screener.

Filter S&P 500 companies by KPIs and explore price history.
Run with:  uv run streamlit run app.py
"""

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="S&P 500 Screener", page_icon="📈", layout="wide")

KPI_CACHE = Path(__file__).parent / "sp500_kpis.csv"
CACHE_MAX_AGE = 24 * 3600  # refresh fundamentals once a day


# ---------------------------------------------------------------- data layer
@st.cache_data(ttl=CACHE_MAX_AGE)
def get_constituents() -> pd.DataFrame:
    """Current S&P 500 members from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    df = pd.read_html(url, storage_options={"User-Agent": "Mozilla/5.0"})[0]
    df = df[["Symbol", "Security", "GICS Sector"]]
    df.columns = ["ticker", "name", "sector"]
    df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)  # BRK.B -> BRK-B
    return df


def fetch_kpis_one(ticker: str) -> dict:
    """Fetch key fundamentals for a single ticker."""
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
    """All fundamentals, cached to disk so the slow fetch happens once a day."""
    if KPI_CACHE.exists() and time.time() - KPI_CACHE.stat().st_mtime < CACHE_MAX_AGE:
        return pd.read_csv(KPI_CACHE)

    rows = []
    bar = st.progress(0.0)
    with ThreadPoolExecutor(max_workers=12) as pool:
        for i, row in enumerate(pool.map(fetch_kpis_one, tickers), start=1):
            rows.append(row)
            bar.progress(i / len(tickers), text=f"Fetching fundamentals… {i}/{len(tickers)} (first run only)")
    bar.empty()

    df = pd.DataFrame(rows)
    df.to_csv(KPI_CACHE, index=False)
    return df


@st.cache_data(ttl=3600)
def get_history(ticker: str, period: str) -> pd.DataFrame:
    return yf.Ticker(ticker).history(period=period)


# ---------------------------------------------------------------- load data
st.title("📈 S&P 500 Screener")

constituents = get_constituents()
kpis = load_kpis(constituents["ticker"].tolist())
data = constituents.merge(kpis, on="ticker", how="left")
data["market_cap_b"] = data["market_cap"] / 1e9  # billions
data["profit_margin"] = data["profit_margin"] * 100
data["revenue_growth"] = data["revenue_growth"] * 100
data["roe"] = data["roe"] * 100

# ---------------------------------------------------------------- sidebar filters
st.sidebar.header("Filters")

sectors = st.sidebar.multiselect(
    "Sector", sorted(data["sector"].unique()), placeholder="All sectors"
)
pe_max = st.sidebar.slider("Max P/E ratio", 5, 150, 150)
cap_min = st.sidebar.slider("Min market cap ($B)", 0, 500, 0)
div_min = st.sidebar.slider("Min dividend yield (%)", 0.0, 6.0, 0.0, 0.1)
growth_min = st.sidebar.slider("Min revenue growth (%)", -20, 50, -20)
margin_min = st.sidebar.slider("Min profit margin (%)", -20, 60, -20)

filtered = data.copy()
if sectors:
    filtered = filtered[filtered["sector"].isin(sectors)]
if pe_max < 150:
    filtered = filtered[filtered["pe"] <= pe_max]
if cap_min > 0:
    filtered = filtered[filtered["market_cap_b"] >= cap_min]
if div_min > 0:
    filtered = filtered[filtered["dividend_yield"] >= div_min]
if growth_min > -20:
    filtered = filtered[filtered["revenue_growth"] >= growth_min]
if margin_min > -20:
    filtered = filtered[filtered["profit_margin"] >= margin_min]

st.sidebar.caption(f"{len(filtered)} of {len(data)} companies match")

# ---------------------------------------------------------------- results table
st.subheader(f"Matching companies ({len(filtered)})")

table = filtered[
    ["ticker", "name", "sector", "price", "market_cap_b", "pe",
     "dividend_yield", "revenue_growth", "profit_margin", "roe", "beta"]
].sort_values("market_cap_b", ascending=False)

st.dataframe(
    table,
    hide_index=True,
    use_container_width=True,
    column_config={
        "ticker": "Ticker",
        "name": "Company",
        "sector": "Sector",
        "price": st.column_config.NumberColumn("Price", format="$%.2f"),
        "market_cap_b": st.column_config.NumberColumn("Mkt cap ($B)", format="%.1f"),
        "pe": st.column_config.NumberColumn("P/E", format="%.1f"),
        "dividend_yield": st.column_config.NumberColumn("Div yield %", format="%.2f"),
        "revenue_growth": st.column_config.NumberColumn("Rev growth %", format="%.1f"),
        "profit_margin": st.column_config.NumberColumn("Margin %", format="%.1f"),
        "roe": st.column_config.NumberColumn("ROE %", format="%.1f"),
        "beta": st.column_config.NumberColumn("Beta", format="%.2f"),
    },
)

# ---------------------------------------------------------------- detail view
st.subheader("Price history")

if len(filtered) == 0:
    st.info("No companies match the current filters.")
else:
    col1, col2 = st.columns([3, 1])
    options = (filtered["ticker"] + " — " + filtered["name"]).tolist()
    choice = col1.selectbox("Company", options)
    period = col2.radio("Period", ["6mo", "1y", "5y", "max"], horizontal=True, index=1)

    ticker = choice.split(" — ")[0]
    row = data.loc[data["ticker"] == ticker].iloc[0]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Price", f"${row['price']:.2f}" if pd.notna(row["price"]) else "–")
    m2.metric("Market cap", f"${row['market_cap_b']:.1f}B" if pd.notna(row["market_cap_b"]) else "–")
    m3.metric("P/E", f"{row['pe']:.1f}" if pd.notna(row["pe"]) else "–")
    m4.metric("Div yield", f"{row['dividend_yield']:.2f}%" if pd.notna(row["dividend_yield"]) else "–")

    hist = get_history(ticker, period)
    if hist.empty:
        st.warning("No price history available.")
    else:
        fig = px.area(hist, y="Close", title=f"{row['name']} ({ticker}) — closing price")
        fig.update_layout(xaxis_title=None, yaxis_title="USD", showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

st.caption("Data: Yahoo Finance via yfinance. For exploration, not investment advice.")
