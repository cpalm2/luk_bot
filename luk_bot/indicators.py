"""Indicators used by the screener and signal engine.

All functions take a daily OHLCV DataFrame with columns
open, high, low, close, volume and a DatetimeIndex, oldest first.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def add_emas(df: pd.DataFrame, periods=(9, 21, 50)) -> pd.DataFrame:
    out = df.copy()
    for p in periods:
        out[f"ema{p}"] = ema(out["close"], p)
    return out


def swing_points(df: pd.DataFrame, strength: int = 5):
    """Confirmed pivot highs/lows: a bar higher (lower) than `strength` bars on each side.

    Returns two lists of (timestamp, price), oldest first. The last `strength`
    bars cannot be confirmed yet, so they are never pivots (no look-ahead).
    """
    highs, lows = df["high"].to_numpy(), df["low"].to_numpy()
    idx = df.index
    ph, pl = [], []
    for i in range(strength, len(df) - strength):
        win_h = highs[i - strength : i + strength + 1]
        win_l = lows[i - strength : i + strength + 1]
        if highs[i] == win_h.max() and (win_h == highs[i]).sum() == 1:
            ph.append((idx[i], float(highs[i])))
        if lows[i] == win_l.min() and (win_l == lows[i]).sum() == 1:
            pl.append((idx[i], float(lows[i])))
    return ph, pl


def unfilled_gaps(df: pd.DataFrame, lookback: int = 120, min_gap_pct: float = 0.01):
    """Find price gaps that later bars have not fully filled.

    Gap up at bar i: low[i] > high[i-1]  -> support zone [high[i-1], remaining top]
    Gap down at bar i: high[i] < low[i-1] -> resistance zone [remaining bottom, low[i-1]]
    The zone shrinks as later bars partially fill it.
    """
    d = df.iloc[-lookback:] if len(df) > lookback else df
    highs, lows = d["high"].to_numpy(), d["low"].to_numpy()
    gaps = []
    for i in range(1, len(d)):
        # gap up
        if lows[i] > highs[i - 1] and (lows[i] - highs[i - 1]) / highs[i - 1] >= min_gap_pct:
            bottom = highs[i - 1]
            later_min = lows[i + 1 :].min() if i + 1 < len(d) else np.inf
            top = min(lows[i], later_min)
            if top > bottom:
                gaps.append({"date": d.index[i], "type": "up", "bottom": float(bottom), "top": float(top)})
        # gap down
        if highs[i] < lows[i - 1] and (lows[i - 1] - highs[i]) / lows[i - 1] >= min_gap_pct:
            top = lows[i - 1]
            later_max = highs[i + 1 :].max() if i + 1 < len(d) else -np.inf
            bottom = max(highs[i], later_max)
            if top > bottom:
                gaps.append({"date": d.index[i], "type": "down", "bottom": float(bottom), "top": float(top)})
    return gaps


def anchored_vwap(df: pd.DataFrame, anchor) -> pd.Series:
    """VWAP accumulated from `anchor` (a timestamp in df.index) to the last bar."""
    d = df.loc[anchor:]
    typical = (d["high"] + d["low"] + d["close"]) / 3
    vol = d["volume"].replace(0, np.nan)
    return (typical * vol).cumsum() / vol.cumsum()


def avwap_anchors(df: pd.DataFrame, pivot_highs, pivot_lows, n: int = 2):
    """Anchors for AVWAP: the most significant recent swing low and swing high,
    plus the largest-volume gap-up day in the last ~6 months.
    """
    anchors = {}
    window_start = df.index[max(0, len(df) - 126)]
    recent_lows = [p for p in pivot_lows if p[0] >= window_start]
    recent_highs = [p for p in pivot_highs if p[0] >= window_start]
    if recent_lows:
        anchors["avwap_swing_low"] = min(recent_lows, key=lambda p: p[1])[0]
        anchors["avwap_last_low"] = recent_lows[-1][0]
    if recent_highs:
        anchors["avwap_swing_high"] = max(recent_highs, key=lambda p: p[1])[0]
    d = df.loc[window_start:]
    gap_up = d[d["low"] > d["high"].shift(1)]
    if len(gap_up):
        anchors["avwap_gap_day"] = gap_up["volume"].idxmax()
    # de-duplicate identical anchors
    seen, uniq = set(), {}
    for k, v in anchors.items():
        if v not in seen:
            uniq[k] = v
            seen.add(v)
    return uniq
