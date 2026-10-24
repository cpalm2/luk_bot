"""Market data: daily OHLCV from Yahoo Finance (yfinance) or local CSVs.

Swap in your own provider (IBKR, Polygon, Norgate, gs-quant/Marquee...) by
returning the same shape: dict[symbol] -> DataFrame[open, high, low, close, volume].
"""
from __future__ import annotations

import os

import pandas as pd

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


def load_universe(path: str | None = None) -> list[str]:
    """Tickers from a text file (one per line), or all US-listed common stocks."""
    if path:
        with open(path) as f:
            return [ln.strip().upper() for ln in f if ln.strip() and not ln.startswith("#")]
    a = pd.read_csv(NASDAQ_LISTED, sep="|")
    b = pd.read_csv(OTHER_LISTED, sep="|")
    a = a[(a["Test Issue"] == "N") & (a["ETF"] == "N")]["Symbol"]
    b = b[(b["Test Issue"] == "N") & (b["ETF"] == "N")]["ACT Symbol"]
    syms = pd.concat([a, b]).dropna().astype(str)
    return sorted(s for s in syms if s.isalpha())  # drops warrants, units, preferreds


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
    df = df.dropna()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df.sort_index()


def fetch_yf(symbols: list[str], period: str = "2y", chunk: int = 200) -> dict[str, pd.DataFrame]:
    import yfinance as yf  # pip install yfinance

    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), chunk):
        batch = symbols[i : i + chunk]
        raw = yf.download(batch, period=period, interval="1d", auto_adjust=True,
                          group_by="ticker", progress=False, threads=True)
        for s in batch:
            try:
                df = raw[s] if len(batch) > 1 else raw
                df = _clean(df)
                if len(df) > 60:
                    out[s] = df
            except (KeyError, ValueError):
                continue
    return out


def load_csv_dir(path: str) -> dict[str, pd.DataFrame]:
    """One CSV per symbol named SYMBOL.csv with a date column + OHLCV."""
    out = {}
    for fn in os.listdir(path):
        if fn.lower().endswith(".csv"):
            df = pd.read_csv(os.path.join(path, fn), index_col=0, parse_dates=True)
            out[fn[:-4].upper()] = _clean(df)
    return out
