"""
backfill.py

One-time (or occasional) script to build up enough price history for
EMA-200 / 52-week-high-low / 1Y returns to be meaningful. Run this once
manually before daily automation starts producing reliable long-window
metrics. Daily runs after that only need to append one day at a time.

Usage:
    python scripts/backfill.py --days 300

This will take a while (one NSE + one BSE request per trading day) - NSE
in particular can be slow/rate-limit-sensitive, so this pauses briefly
between requests. Safe to re-run if it gets interrupted partway; it skips
dates already in history.
"""

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).parent))
from fetch_bhavcopy import fetch_both

DATA_DIR = Path(__file__).parent.parent / "data"
HISTORY_FILE = DATA_DIR / "history" / "price_history.csv"


def main(days: int, pause_seconds: float) -> None:
    history = pd.read_csv(HISTORY_FILE) if HISTORY_FILE.exists() else pd.DataFrame()
    existing_dates = set(history["DATE"]) if not history.empty else set()

    today = datetime.today()
    new_rows = []

    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")

        if d.weekday() >= 5:  # skip Sat/Sun - NSE holidays just return empty
            continue
        if date_str in existing_dates:
            continue

        print(f"Backfilling {date_str}...")
        day_data = fetch_both(d)
        if not day_data.empty:
            new_rows.append(day_data)
        time.sleep(pause_seconds)

    if new_rows:
        history = pd.concat([history] + new_rows, ignore_index=True)
        history = history.drop_duplicates(subset=["SYMBOL", "EXCHANGE", "DATE"], keep="last")
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        history.to_csv(HISTORY_FILE, index=False)

    print(f"\nBackfill complete: {len(history)} total rows, "
          f"{history['SYMBOL'].nunique() if not history.empty else 0} symbols.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=300,
                         help="Calendar days to backfill (300 ≈ 200 trading days, enough for 200 EMA)")
    parser.add_argument("--pause", type=float, default=1.0,
                         help="Seconds to pause between requests, be polite to NSE/BSE servers")
    args = parser.parse_args()
    main(args.days, args.pause)
