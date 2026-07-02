"""
build_dataset.py

Daily orchestrator - this is what the GitHub Action runs every trading day.

1. Fetches today's NSE + BSE bhavcopy
2. Appends it to the local history store (data/history/price_history.csv)
3. Recomputes metrics (EMA, returns, VWAP, RSI, etc.) for every symbol
4. Joins cap category + SME tagging
5. Writes the final combined table to data/output/latest.csv
   (this is the file your Google Sheet reads via IMPORTDATA)
"""

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).parent))
from fetch_bhavcopy import fetch_both
from fetch_reference import (
    fetch_amfi_cap_classification,
    fetch_nse_equity_master,
    classify_cap_from_amfi,
    tag_sme,
)
from compute_metrics import compute_all

DATA_DIR = Path(__file__).parent.parent / "data"
HISTORY_FILE = DATA_DIR / "history" / "price_history.csv"
OUTPUT_FILE = DATA_DIR / "output" / "latest.csv"


def load_history() -> pd.DataFrame:
    if HISTORY_FILE.exists():
        return pd.read_csv(HISTORY_FILE)
    return pd.DataFrame()


def save_history(df: pd.DataFrame) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(HISTORY_FILE, index=False)


def main(run_date: datetime = None) -> None:
    run_date = run_date or datetime.today()
    print(f"=== Daily update for {run_date.date()} ===")

    print("Fetching today's bhavcopy...")
    today_data = fetch_both(run_date)
    if today_data.empty:
        print("No data returned (holiday, weekend, or fetch failure) - nothing to update.")
        return
    print(f"Got {len(today_data)} rows.")

    history = load_history()
    history = pd.concat([history, today_data], ignore_index=True)
    history = history.drop_duplicates(subset=["SYMBOL", "EXCHANGE", "DATE"], keep="last")
    save_history(history)
    print(f"History: {len(history)} rows, {history['SYMBOL'].nunique()} symbols.")

    print("Computing metrics for every symbol...")
    metrics = compute_all(history)

    print("Tagging SME stocks...")
    if "SERIES" in metrics.columns:
        metrics["IS_SME"] = metrics["SERIES"].apply(tag_sme)

    print("Fetching cap classification (AMFI)...")
    try:
        amfi_raw = fetch_amfi_cap_classification()
        (DATA_DIR / "reference").mkdir(parents=True, exist_ok=True)
        amfi_raw.to_csv(DATA_DIR / "reference" / "amfi_cap_raw.csv", index=False)

        cap_classified = classify_cap_from_amfi(amfi_raw)
        metrics = metrics.merge(cap_classified[["ISIN", "CAP_CATEGORY"]], on="ISIN", how="left")
        # Not in AMFI's tracked universe at all => smaller than the
        # smallest tracked Small-cap stock, by construction.
        metrics["CAP_CATEGORY"] = metrics["CAP_CATEGORY"].fillna("Micro")
        print(f"Cap classification counts:\n{metrics['CAP_CATEGORY'].value_counts()}")
    except Exception as e:
        print(f"AMFI classification failed (non-fatal, dashboard still updates without cap tags): {e}")

    print("Fetching NSE equity master (for company names / ISIN cross-check)...")
    try:
        master = fetch_nse_equity_master()
        (DATA_DIR / "reference").mkdir(parents=True, exist_ok=True)
        master.to_csv(DATA_DIR / "reference" / "nse_equity_master.csv", index=False)
    except Exception as e:
        print(f"NSE equity master fetch failed (non-fatal): {e}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(OUTPUT_FILE, index=False)
    print(f"Done. Wrote {len(metrics)} rows to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
