# FirstApp — S&P 500 Screener

Filter S&P 500 stocks by KPIs (P/E, market cap, dividend yield, revenue growth, profit margin) and explore price history charts.

## Run

```bash
uv run streamlit run app.py
```

Opens at http://localhost:8501. The first run fetches fundamentals for all 500 companies (~2 min); after that it's cached for 24 hours.

Data from Yahoo Finance via [yfinance](https://github.com/ranaroussi/yfinance). For exploration, not investment advice.
