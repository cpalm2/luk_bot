"""Step 1: screen for strong stocks that are consolidating and gaining strength.

1. Rank the universe separately by 1M, 3M and 6M gain.
2. Keep names up >= 30% that also sit in the top 20-30% of a ranking.
3. Drop thinly traded names.
4. Keep names in a constructive base: above a rising 50 EMA, EMAs stacked,
   base not too deep, volatility contracting.
"""
from __future__ import annotations

import pandas as pd

from .config import ScreenConfig
from .indicators import atr, ema


def _momentum_table(data: dict[str, pd.DataFrame], cfg: ScreenConfig) -> pd.DataFrame:
    rows = []
    need = max(cfg.lookbacks.values()) + 1
    for sym, df in data.items():
        if len(df) < need:
            continue
        c = df["close"]
        row = {"symbol": sym, "close": float(c.iloc[-1])}
        for name, n in cfg.lookbacks.items():
            row[f"ret_{name}"] = float(c.iloc[-1] / c.iloc[-1 - n] - 1)
        v = df["volume"].iloc[-cfg.volume_window :]
        row["avg_volume"] = float(v.mean())
        row["avg_dollar_volume"] = float((v * c.iloc[-cfg.volume_window :]).mean())
        rows.append(row)
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    # separate ranking per lookback (percentile 1.0 = strongest)
    for name in cfg.lookbacks:
        t[f"pct_{name}"] = t[f"ret_{name}"].rank(pct=True)
    return t.set_index("symbol")


def _base_quality(df: pd.DataFrame, cfg: ScreenConfig) -> dict:
    c = df["close"]
    e9, e21, e50 = ema(c, 9), ema(c, 21), ema(c, 50)
    base = df.iloc[-cfg.base_window :]
    depth = 1 - base["low"].min() / base["high"].max()
    a = atr(df, 10)
    half = cfg.base_window // 2
    recent_atr = a.iloc[-half:].mean()
    earlier_atr = a.iloc[-cfg.base_window : -half].mean()
    contraction = recent_atr / earlier_atr if earlier_atr > 0 else 1.0
    return {
        "above_ema50": bool(c.iloc[-1] > e50.iloc[-1]),
        "ema_stack": bool(e9.iloc[-1] > e21.iloc[-1] > e50.iloc[-1]),
        "ema50_rising": bool(e50.iloc[-1] > e50.iloc[-10]),
        "base_depth": float(depth),
        "atr_contraction": float(contraction),
        "dist_from_high": float(1 - c.iloc[-1] / base["high"].max()),
    }


def screen(data: dict[str, pd.DataFrame], cfg: ScreenConfig | None = None, verbose: bool = False) -> pd.DataFrame:
    """Return the shortlist, best first. `data` maps symbol -> daily OHLCV."""
    cfg = cfg or ScreenConfig()
    t = _momentum_table(data, cfg)
    if t.empty:
        return t

    cut = 1 - cfg.top_percentile
    hit = pd.Series(False, index=t.index)
    for name in cfg.lookbacks:
        hit |= (t[f"ret_{name}"] >= cfg.min_gain) & (t[f"pct_{name}"] >= cut)
    t["momentum_hit"] = hit
    t["liquid"] = (
        (t["avg_volume"] >= cfg.min_avg_volume)
        & (t["avg_dollar_volume"] >= cfg.min_avg_dollar_volume)
        & (t["close"] >= cfg.min_price)
    )
    if verbose:
        print(f"universe={len(t)}  momentum={int(hit.sum())}  liquid&momentum={int((hit & t['liquid']).sum())}")

    short = t[t["momentum_hit"] & t["liquid"]].copy()
    if short.empty:
        return short

    q = pd.DataFrame({s: _base_quality(data[s], cfg) for s in short.index}).T
    short = short.join(q)
    keep = short["base_depth"] <= cfg.max_base_depth
    if cfg.require_above_ema50:
        keep &= short["above_ema50"].astype(bool)
    if cfg.require_ema_stack:
        keep &= short["ema_stack"].astype(bool) & short["ema50_rising"].astype(bool)
    short = short[keep].copy()

    # score: momentum rank + tightening + closeness to base highs
    pct_cols = [f"pct_{n}" for n in cfg.lookbacks]
    short["score"] = (
        short[pct_cols].mean(axis=1)
        + (short["atr_contraction"] <= cfg.contraction_ratio).astype(float) * 0.25
        - short["dist_from_high"].astype(float)
    )
    return short.sort_values("score", ascending=False)
