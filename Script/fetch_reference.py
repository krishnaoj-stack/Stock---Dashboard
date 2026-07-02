"""
fetch_reference.py

Pulls reference/classification data that doesn't change daily:
- AMFI large/mid/small cap classification (official SEBI-mandated list,
  updated every January and July)
- NSE equity master list (symbol, name, ISIN, face value)

These are cheap, small files - refetching every daily run is fine and
avoids needing separate scheduling logic to know when AMFI last updated.

>>> VERIFY ON FIRST LIVE RUN <<<
- AMFI's classification file is an .xlsx whose filename changes every
  release (e.g. "...Jan-June 2026.xlsx"). This scrapes the categorisation
  page to find the current link rather than hardcoding a URL - if AMFI
  changes their page layout, the regex below will need adjusting.
- AMFI's column names inside the xlsx vary release to release (seen as
  "Stock Name" / "Company Name", "Category" / "Classification" in past
  files) - inspect the first successful download and adjust the merge
  keys in build_dataset.py accordingly.
- NSE_EQUITY_MASTER_URL gives Symbol/ISIN/Face Value reliably, but check
  whether it includes an industry/sector column with good coverage. If
  sparse, sector mapping will need a secondary source - e.g. NSE's
  sectoral index constituent files (ind_niftyitlist.csv, etc.), which
  only cover index-member stocks though, not the full universe.
"""

import io
import re

import pandas as pd
import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

AMFI_CATEGORISATION_PAGE = "https://www.amfiindia.com/otherdata/categorisation-of-stocks"
NSE_EQUITY_MASTER_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

# NSE Emerge (SME) and BSE SME stocks trade under distinct series/group
# codes rather than the standard "EQ" - use this to flag them.
SME_SERIES_CODES = {"SM", "ST"}


def fetch_amfi_cap_classification() -> pd.DataFrame:
    """Scrapes the AMFI page for the latest classification .xlsx link,
    downloads it, and returns the raw table (Large/Mid/Small cap by
    company name)."""
    page = requests.get(AMFI_CATEGORISATION_PAGE, headers=HEADERS, timeout=15).text
    match = re.search(r'href="([^"]+\.xlsx)"', page, re.IGNORECASE)
    if not match:
        raise RuntimeError(
            "Could not find an .xlsx link on the AMFI categorisation page - "
            "the page structure likely changed. Check the URL manually: "
            f"{AMFI_CATEGORISATION_PAGE}"
        )

    xlsx_url = match.group(1)
    if xlsx_url.startswith("/"):
        xlsx_url = "https://www.amfiindia.com" + xlsx_url

    resp = requests.get(xlsx_url, headers=HEADERS, timeout=20)
    df = pd.read_excel(io.BytesIO(resp.content))
    df.columns = [str(c).strip() for c in df.columns]
    return df


def fetch_nse_equity_master() -> pd.DataFrame:
    """Full list of NSE-listed equities - symbol, name, ISIN, face value.
    Used to confirm active listings and join company names."""
    resp = requests.get(NSE_EQUITY_MASTER_URL, headers=HEADERS, timeout=15)
    df = pd.read_csv(io.BytesIO(resp.content))
    df.columns = [c.strip() for c in df.columns]
    return df


def tag_sme(series: str) -> bool:
    """True if a stock's series code identifies it as NSE Emerge / BSE SME."""
    return series in SME_SERIES_CODES


def tag_micro_cap(market_cap_cr: float, small_cap_cutoff_cr: float = 5000) -> bool:
    """AMFI's official list only has Large/Mid/Small. 'Micro' isn't an
    official SEBI bucket, so we define it ourselves: any stock AMFI would
    rank as Small cap but below this threshold. Default cutoff (₹5,000 Cr)
    is a starting point - adjust based on where you actually want the line."""
    return market_cap_cr < small_cap_cutoff_cr


if __name__ == "__main__":
    # Quick manual test: python fetch_reference.py
    print("Fetching AMFI classification...")
    amfi = fetch_amfi_cap_classification()
    print(amfi.head())
    print(f"Columns found: {list(amfi.columns)}\n")

    print("Fetching NSE equity master...")
    master = fetch_nse_equity_master()
    print(master.head())
    print(f"Columns found: {list(master.columns)}")
