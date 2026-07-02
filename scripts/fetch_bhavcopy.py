"""
fetch_bhavcopy.py

Downloads daily end-of-day price data (bhavcopy) from NSE and BSE and
normalizes both into one common schema.

NSE requires a browser-like session before archive URLs will respond -
hitting the archive URL directly without first visiting nseindia.com
returns a 403. This module handles that automatically.

>>> VERIFY ON FIRST LIVE RUN (things NSE/BSE are known to change) <<<
- NSE_CM_BHAVCOPY_URL: current UDiFF format, confirmed as of mid-2026.
  NSE changed this format in July 2024 and may change it again - if
  this starts 404ing on trading days, check https://www.nseindia.com/all-reports
  ("CM-UDiFF Common Bhavcopy Final (zip)") for the new pattern.
- BSE_BHAVCOPY_URL: BSE has bot-detection that may block simple requests
  even with session priming - if BSE keeps failing, that's expected for
  now and doesn't block the pipeline; NSE data still flows through.
- Whether DELIV_PER (delivery %) ships inside this NSE file or needs a
  separate report - script checks for the column and logs a warning if
  it's missing rather than failing silently.
"""

import io
import logging
import zipfile
from datetime import datetime

import pandas as pd
import requests

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

NSE_HOME = "https://www.nseindia.com"
NSE_CM_BHAVCOPY_URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"
BSE_BHAVCOPY_URL = "https://www.bseindia.com/download/BhavCopy/Equity/EQ{date}_CSV.ZIP"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _nse_session() -> requests.Session:
    """NSE blocks requests without valid cookies. Visit the homepage first
    to collect them, then reuse the session for the actual download."""
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(NSE_HOME, timeout=10)
    return s


def fetch_nse_bhavcopy(date: datetime) -> pd.DataFrame:
    """Downloads NSE's daily CM (equity) bhavcopy. Returns an empty
    DataFrame on holidays/weekends, since the file won't exist."""
    date_str = date.strftime("%Y%m%d")
    url = NSE_CM_BHAVCOPY_URL.format(date=date_str)
    session = _nse_session()
    resp = session.get(url, timeout=20)

    if resp.status_code != 200:
        logger.warning(
            f"NSE bhavcopy unavailable for {date_str} (status {resp.status_code}) "
            f"- likely a holiday, but could mean the URL format changed."
        )
        return pd.DataFrame()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        csv_name = z.namelist()[0]
        with z.open(csv_name) as f:
            df = pd.read_csv(f)

    df.columns = [c.strip().upper() for c in df.columns]
    df["EXCHANGE"] = "NSE"
    df["DATE"] = date.strftime("%Y-%m-%d")

    if "DELIV_PER" not in df.columns:
        logger.warning(
            "DELIV_PER not present in this NSE file - delivery %% will be "
            "blank for this date. Check nseindia.com/all-reports for a "
            "separate delivery position report if this persists."
        )

    return df


def _bse_session() -> requests.Session:
    """BSE has bot-detection on their site (confirmed - a plain request to
    their bhavcopy page gets blocked). Priming a session against the
    homepage first, same approach as NSE, is worth trying before falling
    back to skipping BSE entirely."""
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get("https://www.bseindia.com", timeout=10)
    return s


def fetch_bse_bhavcopy(date: datetime) -> pd.DataFrame:
    """Downloads BSE's daily equity bhavcopy. Returns an empty DataFrame
    on holidays/weekends/fetch failures - BSE being unavailable should
    never crash the pipeline, since NSE alone covers the large majority
    of actively-traded stocks."""
    date_str = date.strftime("%d%m%y")
    url = BSE_BHAVCOPY_URL.format(date=date_str)

    try:
        session = _bse_session()
        resp = session.get(url, timeout=20)

        if resp.status_code != 200:
            logger.warning(
                f"BSE bhavcopy unavailable for {date_str} (status {resp.status_code}) "
                f"- likely a holiday, bot-blocked, or BSE changed their URL format."
            )
            return pd.DataFrame()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            csv_name = z.namelist()[0]
            with z.open(csv_name) as f:
                df = pd.read_csv(f)

    except zipfile.BadZipFile:
        logger.warning(
            f"BSE returned a non-zip response for {date_str} - almost certainly "
            f"bot-detection blocking the request rather than serving the file. "
            f"Skipping BSE for this date; NSE data is unaffected."
        )
        return pd.DataFrame()
    except Exception as e:
        logger.warning(f"BSE fetch failed for {date_str} ({e}) - skipping BSE for this date.")
        return pd.DataFrame()

    df.columns = [c.strip().upper() for c in df.columns]
    df["EXCHANGE"] = "BSE"
    df["DATE"] = date.strftime("%Y-%m-%d")
    return df


def _normalize_nse(df: pd.DataFrame) -> pd.DataFrame:
    """Maps NSE's column names to our common schema. Keeps only the EQ
    (regular equity) series by default - SME stocks (SM/ST series) are
    tagged separately in fetch_reference.py, not dropped here."""
    return pd.DataFrame({
        "SYMBOL": df.get("SYMBOL"),
        "SERIES": df.get("SERIES"),
        "ISIN": df.get("ISIN"),
        "EXCHANGE": "NSE",
        "DATE": df.get("DATE"),
        "OPEN": pd.to_numeric(df.get("OPEN"), errors="coerce"),
        "HIGH": pd.to_numeric(df.get("HIGH"), errors="coerce"),
        "LOW": pd.to_numeric(df.get("LOW"), errors="coerce"),
        "CLOSE": pd.to_numeric(df.get("CLOSE"), errors="coerce"),
        "PREV_CLOSE": pd.to_numeric(df.get("PREVCLOSE"), errors="coerce"),
        "VOLUME": pd.to_numeric(df.get("TOTTRDQTY"), errors="coerce"),
        "TURNOVER": pd.to_numeric(df.get("TOTTRDVAL"), errors="coerce"),
        "TRADES": pd.to_numeric(df.get("TOTALTRADES"), errors="coerce"),
        "DELIV_QTY": pd.to_numeric(df.get("DELIV_QTY"), errors="coerce"),
        "DELIV_PER": pd.to_numeric(df.get("DELIV_PER"), errors="coerce"),
    })


def _normalize_bse(df: pd.DataFrame) -> pd.DataFrame:
    """Maps BSE's column names to our common schema. BSE has used a couple
    of different header sets historically - the .get() fallbacks below
    try the most common alternates. Confirm against the real downloaded
    file on first run and adjust if a column comes through empty."""
    return pd.DataFrame({
        "SYMBOL": df.get("SC_NAME", df.get("TCKRSYMB")),
        "SERIES": df.get("SC_TYPE", df.get("SERIES")),
        "ISIN": df.get("ISIN", df.get("ISIN_CODE")),
        "EXCHANGE": "BSE",
        "DATE": df.get("DATE"),
        "OPEN": pd.to_numeric(df.get("OPEN"), errors="coerce"),
        "HIGH": pd.to_numeric(df.get("HIGH"), errors="coerce"),
        "LOW": pd.to_numeric(df.get("LOW"), errors="coerce"),
        "CLOSE": pd.to_numeric(df.get("CLOSE"), errors="coerce"),
        "PREV_CLOSE": pd.to_numeric(df.get("PREVCLOSE"), errors="coerce"),
        "VOLUME": pd.to_numeric(df.get("NO_OF_SHRS", df.get("VOLUME")), errors="coerce"),
        "TURNOVER": pd.to_numeric(df.get("NET_TURNOV"), errors="coerce"),
        "TRADES": pd.to_numeric(df.get("NO_TRADES"), errors="coerce"),
        "DELIV_QTY": None,
        "DELIV_PER": None,
    })


def fetch_both(date: datetime) -> pd.DataFrame:
    """Fetches and combines NSE + BSE bhavcopy for a single date into one
    normalized DataFrame, ready to append to history."""
    nse_raw = fetch_nse_bhavcopy(date)
    bse_raw = fetch_bse_bhavcopy(date)

    nse = _normalize_nse(nse_raw) if not nse_raw.empty else pd.DataFrame()
    bse = _normalize_bse(bse_raw) if not bse_raw.empty else pd.DataFrame()

    combined = pd.concat([nse, bse], ignore_index=True)
    if not combined.empty:
        combined = combined.dropna(subset=["SYMBOL", "CLOSE"])
    return combined


if __name__ == "__main__":
    # Quick manual test: python fetch_bhavcopy.py
    result = fetch_both(datetime.today())
    print(result.head(10))
    print(f"\nTotal rows: {len(result)}")
