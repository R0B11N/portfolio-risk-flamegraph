"""
Fama-French 3-factor pipeline: download factors, fetch prices, run regressions.
"""

import io
import time
import zipfile
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

FF_CACHE_FILE = DATA_DIR / "ff_factors_daily.csv"
FF_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip"


def download_ff_factors() -> pd.DataFrame:
    """Download daily Fama-French 3-factor data from Ken French's library.
    Caches to disk so subsequent runs skip the download."""

    if FF_CACHE_FILE.exists():
        age = datetime.now() - datetime.fromtimestamp(FF_CACHE_FILE.stat().st_mtime)
        if age.days < 7:
            log.info("Using cached FF data (%d days old)", age.days)
            df = pd.read_csv(FF_CACHE_FILE, index_col=0)
            df.index = pd.to_datetime(df.index)
            df.index.name = "Date"
            return df

    log.info("Downloading FF factor data from %s", FF_URL)
    resp = requests.get(FF_URL, timeout=30)
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        csv_name = [n for n in zf.namelist() if n.endswith(".CSV") or n.endswith(".csv")]
        if not csv_name:
            raise ValueError("No CSV found in FF zip archive")

        raw = zf.read(csv_name[0]).decode("utf-8", errors="replace")

    lines = raw.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and stripped[0].isdigit() and len(stripped.split(",")) >= 4:
            date_candidate = stripped.split(",")[0].strip()
            if len(date_candidate) == 8 and date_candidate.isdigit():
                start_idx = i
                break

    if start_idx is None:
        raise ValueError("Could not find data start in Fama-French CSV")

    data_lines = []
    for line in lines[start_idx:]:
        stripped = line.strip()
        if not stripped or not stripped[0].isdigit():
            break
        data_lines.append(stripped)

    csv_text = "Date,Mkt-RF,SMB,HML,RF\n" + "\n".join(data_lines)
    df = pd.read_csv(io.StringIO(csv_text), parse_dates=False)

    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d")
    df = df.set_index("Date").sort_index()

    for col in ["Mkt-RF", "SMB", "HML", "RF"]:
        df[col] = df[col].astype(float) / 100.0

    df.to_csv(FF_CACHE_FILE)
    log.info("Cached %d days of FF data to %s", len(df), FF_CACHE_FILE)
    return df


def _is_tsx_ticker(ticker: str) -> bool:
    """Check if a ticker is listed on Toronto Stock Exchange."""
    return ticker.upper().endswith(".TO") or ticker.upper().endswith(".V")


def _fetch_via_yfinance(ticker: str) -> Optional[pd.Series]:
    """Fetch a single ticker from yfinance with retry logic."""
    try:
        import yfinance as yf
    except ImportError:
        return None

    for attempt in range(3):
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="18mo")
            if hist.empty or "Close" not in hist.columns:
                if attempt < 2:
                    time.sleep(5 * (2 ** attempt))
                    continue
                return None
            series = hist["Close"].copy()
            series.name = ticker
            series.index = series.index.tz_localize(None).normalize()
            return series
        except Exception as e:
            log.warning("yfinance attempt %d for %s: %s", attempt + 1, ticker, e)
            if attempt < 2:
                time.sleep(5 * (2 ** attempt))
    return None


def fetch_prices(tickers: List[str], lookback_months: int = 18) -> pd.DataFrame:
    """Fetch close prices for a list of tickers.
    Uses yfinance as the primary source for all tickers.
    Falls back to Stooq for non-TSX tickers if yfinance fails."""

    end = datetime.now()
    start = end - timedelta(days=lookback_months * 30)
    log.info("Fetching prices for %s from %s to %s", tickers, start.date(), end.date())

    all_series = {}
    stooq_fallback = []

    # Try yfinance first for all tickers (avoids pandas_datareader
    # parse_dates incompatibility with pandas 2.x)
    for i, ticker in enumerate(tickers):
        if i > 0:
            time.sleep(1.0)
        series = _fetch_via_yfinance(ticker)
        if series is not None:
            all_series[ticker] = series
            log.info("✓ %s: %d days (yfinance)", ticker, len(series))
        else:
            if not _is_tsx_ticker(ticker):
                stooq_fallback.append(ticker)
            else:
                log.warning("No data for TSX ticker %s", ticker)

    # Fall back to Stooq for non-TSX tickers that yfinance missed
    if stooq_fallback:
        log.info("Falling back to Stooq for: %s", stooq_fallback)
        for ticker in stooq_fallback:
            try:
                from pandas_datareader import data as pdr
                df = pdr.DataReader(ticker, "stooq", start, end)

                if df.empty or "Close" not in df.columns:
                    log.warning("Stooq: no data for %s either", ticker)
                    continue

                series = df["Close"].sort_index()
                series.name = ticker
                all_series[ticker] = series
                log.info("✓ %s: %d days (stooq)", ticker, len(series))

            except Exception as e:
                log.warning("Stooq also failed for %s: %s", ticker, e)

    if not all_series:
        raise ValueError(f"No price data returned for any ticker: {tickers}")

    failed = [t for t in tickers if t not in all_series]
    if failed:
        log.warning("No data for these tickers (excluded): %s", failed)

    prices = pd.DataFrame(all_series)
    prices = prices.dropna(how="all")
    return prices


def _fetch_cad_usd_rate() -> Optional[pd.Series]:
    """Fetch CAD→USD daily exchange rate. FF factors are in USD,
    so CAD-denominated returns must be converted."""
    try:
        import yfinance as yf
        fx = yf.Ticker("CADUSD=X")
        hist = fx.history(period="2y")
        if not hist.empty and "Close" in hist.columns:
            series = hist["Close"].copy()
            series.index = series.index.tz_localize(None).normalize()
            log.info("✓ CAD/USD rate: %d days", len(series))
            return series
    except Exception as e:
        log.warning("Could not fetch CAD/USD rate: %s", e)
    return None


def _convert_cad_returns_to_usd(
    returns: pd.DataFrame, cad_tickers: List[str]
) -> pd.DataFrame:
    """Convert CAD returns to USD: R_usd ≈ R_cad + R_fx."""
    if not cad_tickers:
        return returns

    fx_rate = _fetch_cad_usd_rate()
    if fx_rate is None:
        log.warning("No FX data — using CAD returns as-is")
        return returns

    fx_returns = fx_rate.pct_change().dropna()
    common = returns.index.intersection(fx_returns.index)

    for ticker in cad_tickers:
        if ticker in returns.columns:
            returns.loc[common, ticker] = (
                returns.loc[common, ticker] + fx_returns.loc[common]
            )
            log.info("✓ %s: converted CAD→USD returns", ticker)

    return returns


def compute_excess_returns(
    prices: pd.DataFrame, ff_df: pd.DataFrame, tickers: Optional[List[str]] = None
) -> pd.DataFrame:
    """Compute daily excess returns (stock return minus risk-free rate).
    Converts CAD returns to USD for TSX-listed stocks."""
    returns = prices.pct_change().dropna()

    if tickers:
        cad_tickers = [t for t in tickers if _is_tsx_ticker(t) and t in returns.columns]
        if cad_tickers:
            returns = _convert_cad_returns_to_usd(returns, cad_tickers)

    common_dates = returns.index.intersection(ff_df.index)
    returns = returns.loc[common_dates]
    rf = ff_df.loc[common_dates, "RF"]
    excess = returns.sub(rf, axis=0)
    return excess


def run_factor_regression(
    ticker: str,
    excess_returns: pd.Series,
    ff_df: pd.DataFrame,
    window: int = 252,
    min_obs: int = 60,
) -> Dict[str, Any]:
    """Run OLS regression of stock excess returns on MKT, SMB, HML factors.
    Uses the most recent `window` trading days."""

    common = excess_returns.dropna().index.intersection(ff_df.index)
    if len(common) == 0:
        return _empty_result(ticker)

    common = common.sort_values()
    if len(common) > window:
        common = common[-window:]

    y = excess_returns.loc[common].values
    X = ff_df.loc[common, ["Mkt-RF", "SMB", "HML"]].values
    n_obs = len(y)

    if n_obs < min_obs:
        return {
            "ticker": ticker,
            "beta_mkt": 0.0,
            "beta_smb": 0.0,
            "beta_hml": 0.0,
            "alpha": 0.0,
            "r_squared": 0.0,
            "residual_variance": float(np.var(y)) if len(y) > 0 else 0.0,
            "n_observations": n_obs,
            "sufficient_data": False,
        }

    X_const = sm.add_constant(X)

    try:
        model = sm.OLS(y, X_const).fit()
    except Exception:
        return _empty_result(ticker)

    return {
        "ticker": ticker,
        "beta_mkt": float(model.params[1]),
        "beta_smb": float(model.params[2]),
        "beta_hml": float(model.params[3]),
        "alpha": float(model.params[0]),
        "r_squared": float(model.rsquared),
        "residual_variance": float(np.var(model.resid, ddof=0)),
        "n_observations": n_obs,
        "sufficient_data": True,
    }


def _empty_result(ticker: str) -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "beta_mkt": 0.0,
        "beta_smb": 0.0,
        "beta_hml": 0.0,
        "alpha": 0.0,
        "r_squared": 0.0,
        "residual_variance": 0.0,
        "n_observations": 0,
        "sufficient_data": False,
    }


def analyze_all(tickers: List[str]):
    """Full pipeline: download factors → fetch prices → excess returns → regressions.
    Returns (results_dict, ff_dataframe, prices_dataframe)."""

    ff_df = download_ff_factors()
    prices = fetch_prices(tickers)
    excess = compute_excess_returns(prices, ff_df, tickers)

    results = {}
    for ticker in tickers:
        if ticker in excess.columns:
            result = run_factor_regression(ticker, excess[ticker], ff_df)
        else:
            result = _empty_result(ticker)
        results[ticker] = result

    return results, ff_df, prices
