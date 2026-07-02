"""
fetch_reference.py

Pulls reference/classification data that doesn't change daily:
- AMFI large/mid/small cap classification (official SEBI-mandated list,
  updated every January and July)
- NSE equity master list (symbol, name, ISIN, face value)

These are cheap, small files - refetching every daily run is fine and
avoids needing separate scheduling logic to know when AMFI last updated.

Confirmed (mid-2026) real structure of the AMFI file: columns are
Sr. No., Company Name, ISIN, BSE Symbol, BSE 6 month Avg Total Market
Cap in (Rs. Crs.), NSE Symbol, NSE 6 month Avg Total Market Cap in
(Rs. Crs.) - no explicit "Large/Mid/Small" text column, so category is
derived from rank (Sr. No.) using SEBI's fixed methodology instead:
top 100 = Large, 101-250 = Mid, 251+ = Small.

>>> VERIFY IF THIS EVER BREAKS <<<
- AMFI's page lists Jan-June before Jul-Dec within each year, so
  "grab the first .xlsx link" would pick the WRONG (older) file half
  the time. fetch_amfi_cap_classification() instead extracts a date
  from every .xlsx filename found and picks the maximum - if AMFI
  changes their filename pattern, this date-extraction regex is the
  thing to fix.
- Column names inside the xlsx: find_col() below matches case/spacing
  variations defensively, but if AMFI renames a column entirely,
  classify_cap_from_amfi() will raise with the actual columns listed,
  rather than silently producing wrong data.
"""

import io
import re
from datetime import datetime

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


def _extract_date_from_filename(url: str):
    """Pulls a date like '31Dec2025' or '30_Jun2024' out of an AMFI
    filename. Returns None if the filename doesn't match (older files
    use inconsistent word-based naming that isn't worth parsing)."""
    m = re.search(r"(\d{1,2})[_\-\s%20]*([A-Za-z]{3})[a-z]*[_\-\s%20]*(\d{4})", url)
    if not m:
        return None
    day, mon, year = m.groups()
    try:
        return datetime.strptime(f"{day}{mon}{year}", "%d%b%Y")
    except ValueError:
        return None


def fetch_amfi_cap_classification() -> pd.DataFrame:
    """Finds AMFI's TRUE latest classification .xlsx (by parsing dates out
    of every xlsx filename on the page and taking the max - NOT just the
    first link found, since the page lists Jan-June before Jul-Dec within
    each year) and downloads it."""
    page = requests.get(AMFI_CATEGORISATION_PAGE, headers=HEADERS, timeout=15).text
    xlsx_links = re.findall(r'href="([^"]+\.xlsx)"', page, re.IGNORECASE)
    if not xlsx_links:
        raise RuntimeError(
            "No .xlsx links found on AMFI's categorisation page - "
            f"page structure likely changed. Check manually: {AMFI_CATEGORISATION_PAGE}"
        )

    dated = [(_extract_date_from_filename(u), u) for u in xlsx_links]
    dated = [(d, u) for d, u in dated if d is not None]
    latest_url = max(dated, key=lambda x: x[0])[1] if dated else xlsx_links[0]

    if latest_url.startswith("/"):
        latest_url = "https://www.amfiindia.com" + latest_url

    resp = requests.get(latest_url, headers=HEADERS, timeout=20)
    df = pd.read_excel(io.BytesIO(resp.content))
    df.columns = [str(c).strip() for c in df.columns]
    return df


def classify_cap_from_amfi(amfi_df: pd.DataFrame, micro_cap_cutoff_cr: float = 5000) -> pd.DataFrame:
    """Derives Large/Mid/Small/Micro cap category from AMFI's raw file.

    Uses rank (Sr. No.) rather than any text category column, since
    AMFI's ranking methodology is fixed by SEBI circular (top 100=Large,
    101-250=Mid, 251+=Small) while exact column wording shifts release
    to release. Micro is our own addition on top (AMFI doesn't define
    it) - any Small-cap stock below micro_cap_cutoff_cr (₹ Cr) gets
    reclassified Micro. Returns ISIN, CAP_CATEGORY, MARKET_CAP_CR."""
    cols = {c.lower().strip().rstrip("."): c for c in amfi_df.columns}

    def find_col(*candidates):
        for cand in candidates:
            key = cand.lower().strip().rstrip(".")
            if key in cols:
                return cols[key]
        return None

    isin_col = find_col("ISIN")
    srno_col = find_col("Sr No", "Sr. No", "Sr.No", "S.No", "Serial No")
    mcap_cols = [c for c in amfi_df.columns if "market cap" in c.lower()]

    if isin_col is None or srno_col is None:
        raise RuntimeError(
            "Could not find expected ISIN / Sr.No columns in AMFI file. "
            f"Actual columns: {list(amfi_df.columns)} - update find_col() "
            "candidates above to match."
        )

    out = pd.DataFrame({
        "ISIN": amfi_df[isin_col],
        "RANK": pd.to_numeric(amfi_df[srno_col], errors="coerce"),
    })

    if mcap_cols:
        # Some releases have separate BSE/NSE market-cap columns - average
        # whichever are populated per row rather than assuming a single
        # combined column always exists.
        out["MARKET_CAP_CR"] = amfi_df[mcap_cols].apply(pd.to_numeric, errors="coerce").mean(axis=1, skipna=True)
    else:
        out["MARKET_CAP_CR"] = pd.NA

    out = out.dropna(subset=["ISIN", "RANK"])

    def rank_to_category(rank):
        if rank <= 100:
            return "Large"
        elif rank <= 250:
            return "Mid"
        return "Small"

    out["CAP_CATEGORY"] = out["RANK"].apply(rank_to_category)

    micro_mask = (out["CAP_CATEGORY"] == "Small") & (out["MARKET_CAP_CR"] < micro_cap_cutoff_cr)
    out.loc[micro_mask, "CAP_CATEGORY"] = "Micro"

    return out[["ISIN", "CAP_CATEGORY", "MARKET_CAP_CR"]]


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


if __name__ == "__main__":
    # Quick manual test: python fetch_reference.py
    print("Fetching AMFI classification...")
    amfi = fetch_amfi_cap_classification()
    print(f"Columns found: {list(amfi.columns)}")
    print(amfi.head())
    print()

    print("Classifying...")
    classified = classify_cap_from_amfi(amfi)
    print(classified.head(10))
    print(f"\nCategory counts:\n{classified['CAP_CATEGORY'].value_counts()}")
