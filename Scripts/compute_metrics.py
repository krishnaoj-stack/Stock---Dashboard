"""
compute_metrics.py

Takes accumulated daily price history (one row per symbol per trading day)
and computes every derived metric: VWAP, EMAs, RSI, 52-week high/low,
average volume, volume spike ratio, and returns over multiple windows.

Accuracy depends on how much history is available:
- 200 EMA needs ~200 trading days to be meaningful
- 52-week high/low and 1Y return need ~252 trading days
- Everything else needs less

Run backfill.py first to build up history before these are fully reliable -
with less history, EMA/RSI still compute (pandas handles short series) but
will be less accurate the newer the history is.
"""

import numpy as np
import pandas as pd

# Trading-day approximations used for return windows
RETURN_WINDOWS = {
    "1D": 1,
    "1W": 5,
    "1M": 21,
    "3M": 63,
    "6M": 126,
    "1Y": 252,
}


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_symbol_metrics(history: pd.DataFrame) -> pd.Series:
    """history: all rows for ONE (symbol, exchange) pair, any date order.
    Returns a single row of computed metrics as of the most recent date."""
    history = history.sort_values("DATE").reset_index(drop=True)
    close = history["CLOSE"].astype(float)
    volume = history["VOLUME"].astype(float)
    latest = history.iloc[-1]

    def pct_return(days_back: int):
        if len(close) <= days_back:
            return np.nan
        past = close.iloc[-(days_back + 1)]
        return round((close.iloc[-1] - past) / past * 100, 2) if past else np.nan

    ema50 = _ema(close, 50).iloc[-1]
    ema200 = _ema(close, 200).iloc[-1]
    rsi14 = _rsi(close, 14).iloc[-1] if len(close) >= 15 else np.nan

    window_252 = close.tail(252)
    high_52w, low_52w = window_252.max(), window_252.min()
    avg_vol_20 = volume.tail(20).mean()

    prev_close = latest["PREV_CLOSE"]
    row = {
        "SYMBOL": latest["SYMBOL"],
        "EXCHANGE": latest["EXCHANGE"],
        "SERIES": latest.get("SERIES"),
        "ISIN": latest.get("ISIN"),
        "DATE": latest["DATE"],
        "CMP": latest["CLOSE"],
        "OPEN": latest["OPEN"],
        "HIGH": latest["HIGH"],
        "LOW": latest["LOW"],
        "PREV_CLOSE": prev_close,
        "CHANGE_PCT": round((latest["CLOSE"] - prev_close) / prev_close * 100, 2) if prev_close else np.nan,
        "VWAP": round(latest["TURNOVER"] / latest["VOLUME"], 2) if latest["VOLUME"] else np.nan,
        "VOLUME": latest["VOLUME"],
        "TURNOVER": latest["TURNOVER"],
        "AVG_VOL_20D": round(avg_vol_20, 0) if pd.notna(avg_vol_20) else np.nan,
        "VOL_SPIKE_RATIO": round(latest["VOLUME"] / avg_vol_20, 2) if avg_vol_20 else np.nan,
        "DELIV_PER": latest.get("DELIV_PER"),
        "EMA_50": round(ema50, 2) if pd.notna(ema50) else np.nan,
        "EMA_200": round(ema200, 2) if pd.notna(ema200) else np.nan,
        "DIST_FROM_EMA50_PCT": round((latest["CLOSE"] - ema50) / ema50 * 100, 2) if pd.notna(ema50) and ema50 else np.nan,
        "DIST_FROM_EMA200_PCT": round((latest["CLOSE"] - ema200) / ema200 * 100, 2) if pd.notna(ema200) and ema200 else np.nan,
        "EMA_GOLDEN_CROSS": bool(pd.notna(ema50) and pd.notna(ema200) and ema50 > ema200),
        "RSI_14": round(rsi14, 2) if pd.notna(rsi14) else np.nan,
        "HIGH_52W": high_52w,
        "LOW_52W": low_52w,
        "DIST_FROM_52W_HIGH_PCT": round((latest["CLOSE"] - high_52w) / high_52w * 100, 2) if high_52w else np.nan,
        "DIST_FROM_52W_LOW_PCT": round((latest["CLOSE"] - low_52w) / low_52w * 100, 2) if low_52w else np.nan,
        "DAYS_OF_HISTORY": len(close),
    }
    for label, days in RETURN_WINDOWS.items():
        row[f"RETURN_{label}_PCT"] = pct_return(days)

    return pd.Series(row)


def compute_all(history: pd.DataFrame) -> pd.DataFrame:
    """Runs compute_symbol_metrics for every (SYMBOL, EXCHANGE) pair present
    in the accumulated history. Skips any symbol that errors rather than
    failing the whole run, and prints what got skipped."""
    results = []
    skipped = []
    for (symbol, exchange), group in history.groupby(["SYMBOL", "EXCHANGE"]):
        try:
            results.append(compute_symbol_metrics(group))
        except Exception as e:
            skipped.append((symbol, exchange, str(e)))

    if skipped:
        print(f"Skipped {len(skipped)} symbols due to errors, e.g.: {skipped[:5]}")

    return pd.DataFrame(results)
