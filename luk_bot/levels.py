"""Step 2a: mark the support zones on the daily chart.

EMAs 9/21/50, previous swing highs and lows, unfilled gaps and anchored VWAPs,
all computed from bars up to and including the last row (no look-ahead).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import SignalConfig
from .indicators import add_emas, anchored_vwap, avwap_anchors, swing_points, unfilled_gaps


@dataclass
class Level:
    kind: str          # ema9, ema21, ema50, prior_high, prior_low, gap_top, gap_bottom, avwap_*
    price: float
    anchor: object = None  # date the level originates from (pivot, gap, AVWAP anchor)


def mark_levels(df: pd.DataFrame, cfg: SignalConfig | None = None) -> dict:
    """Return everything needed to draw and trade the chart."""
    cfg = cfg or SignalConfig()
    d = add_emas(df, cfg.ema_periods)
    ph, pl = swing_points(d, cfg.pivot_strength)
    gaps = unfilled_gaps(d, cfg.gap_lookback, cfg.min_gap_pct)
    anchors = avwap_anchors(d, ph, pl)
    avwaps = {name: anchored_vwap(d, a) for name, a in anchors.items()}

    last = d.iloc[-1]
    levels: list[Level] = [Level(f"ema{p}", float(last[f"ema{p}"])) for p in cfg.ema_periods]
    levels += [Level("prior_high", p, t) for t, p in ph[-cfg.n_pivots :]]
    levels += [Level("prior_low", p, t) for t, p in pl[-cfg.n_pivots :]]
    for g in gaps:
        if g["type"] == "up":  # unfilled gap-ups act as support
            levels.append(Level("gap_top", g["top"], g["date"]))
            levels.append(Level("gap_bottom", g["bottom"], g["date"]))
    for name, s in avwaps.items():
        levels.append(Level(name, float(s.iloc[-1]), anchors[name]))

    return {"df": d, "levels": levels, "pivot_highs": ph, "pivot_lows": pl,
            "gaps": gaps, "avwaps": avwaps, "anchors": anchors}
