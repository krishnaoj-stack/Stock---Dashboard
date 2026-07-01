# Stock Dashboard - Data Pipeline (v1)

Free, automated daily pipeline for all NSE + BSE listed stocks: prices,
VWAP, EMAs, RSI, returns (1D/1W/1M/3M/6M/1Y), 52-week high/low, volume
spikes, delivery %, and cap/SME tagging - built entirely on official free
data sources (NSE bhavcopy, BSE bhavcopy, AMFI classification).

## What's in here

```
scripts/
  fetch_bhavcopy.py    # downloads NSE + BSE daily price data
  fetch_reference.py   # downloads AMFI cap classification + NSE equity master
  compute_metrics.py   # computes EMA/RSI/returns/VWAP/52w-hi-lo from history
  build_dataset.py     # daily orchestrator - runs the full pipeline
  backfill.py           # one-time script to build up price history
data/
  history/              # accumulated daily prices (grows over time)
  output/latest.csv     # final output - this is what your Google Sheet reads
.github/workflows/
  daily-update.yml      # runs build_dataset.py automatically every trading day
```

## Setup (do this once)

1. **Create a new GitHub repo** and push this folder to it.

2. **Backfill price history**, so EMA-200 and 1-year returns aren't blank
   on day one. From the repo root:
   ```
   pip install -r requirements.txt
   python scripts/backfill.py --days 300
   ```
   This takes a while (~200 trading days x 2 exchanges). You can run it on
   your own machine, or trigger it as a one-off GitHub Action run.

3. **Commit and push** the resulting `data/history/price_history.csv`.

4. **Enable the daily Action** - it's already configured to run
   automatically on weekdays at 6:05 PM IST (`daily-update.yml`). No
   secrets or API keys needed, since all sources here are public.

5. **Connect Google Sheets** - in any cell:
   ```
   =IMPORTDATA("https://raw.githubusercontent.com/<your-username>/<your-repo>/main/data/output/latest.csv")
   ```
   Sheets refreshes this automatically on its own schedule (and you can
   force a refresh anytime). Use Data → Filter views to slice by any
   column - sector, cap category, EMA distance, returns, etc.

## Known things to verify on first live run

I couldn't test any of this against the real NSE/BSE sites from here (my
sandbox can't reach nseindia.com or bseindia.com), so these are the spots
most likely to need a small fix once it runs for real - flagged with
`VERIFY ON FIRST LIVE RUN` comments in the code:

- **BSE bhavcopy URL/columns** - medium confidence, BSE has changed formats
  before. If `build_dataset.py` logs BSE fetch failures on a trading day,
  check `bseindia.com/download/BhavCopy/Equity` for the current format.
- **Delivery % source** - script expects `DELIV_PER` inside the NSE file;
  if it logs that column as missing, NSE may have split it into a
  separate report that needs its own fetch function.
- **AMFI column names** - the classification spreadsheet's exact column
  names shift release to release. `build_dataset.py` saves the raw file
  to `data/reference/amfi_cap_raw.csv` so you can check the real columns
  and finish wiring up the merge (marked with a `NOTE:` comment).
- **Sector/sub-sector** - not wired up yet. The NSE equity master gives
  symbol/name/ISIN reliably, but full-universe sector coverage (not just
  index-member stocks) needs a bit more digging - flagged as a next step
  rather than guessed at.

None of these break the core pipeline (price, VWAP, EMA, returns, volume,
52-week hi/lo all work independently of the above) - they just mean cap
category and sector will need one more pass once we see real output.

## Next steps once this is running

- Wire up the AMFI cap-category merge and sector mapping (above)
- Add index data (Nifty, Bank Nifty, Nifty IT, etc.) for market-level context
- Move from Google Sheets to a custom filterable dashboard, if/when you
  outgrow Sheets - same pipeline feeds either one
