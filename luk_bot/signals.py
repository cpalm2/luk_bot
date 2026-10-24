"""Step 2b: wait for the buy signal at support.

Signal bar (today, after the close):
  * trend intact: close above the 50 EMA, 21 EMA above the 50 EMA
  * the bar dipped into a support zone where several levels converge
    (e.g. 9 EMA + AVWAP + prior high) ...
  * ... and reclaimed it: close back above those levels, closing in the
    upper part of the day's range (strong close / positive reversal)

Entry plan for the next session: buy-stop a hair above the signal bar's high.
The signal bar is the "breakout K-line"; the bar before it is the "previous K-line".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import SignalConfig
from .levels import Level, mark_levels


@dataclass
class Signal:
    symbol: str
    date: pd.Timestamp
    trigger: float                 # buy-stop price for the next session
    breakout_bar_low: float        # low of the signal bar
    prev_bar_low: float            # low of the bar before it
    confluence: list = field(default_factory=list)  # levels that were tested and reclaimed
    close: float = 0.0

    def describe(self) -> str:
        lv = ", ".join(f"{l.kind}@{l.price:.2f}" for l in self.confluence)
        return f"{self.symbol} {self.date.date()} buy-stop {self.trigger:.2f} | support: {lv}"


def check_signal(symbol: str, df: pd.DataFrame, cfg: SignalConfig | None = None, marked: dict | None = None):
    """Return a Signal if the last bar of `df` is a buy signal, else None."""
    cfg = cfg or SignalConfig()
    if len(df) < 60:
        return None
    m = marked or mark_levels(df, cfg)
    d = m["df"]
    bar, prev = d.iloc[-1], d.iloc[-2]

    if not (bar["close"] > bar["ema50"] and bar["ema21"] > bar["ema50"]):
        return None

    rng = bar["high"] - bar["low"]
    if rng <= 0 or (bar["close"] - bar["low"]) / rng < cfg.reclaim_close_pos:
        return None

    tol = cfg.zone_tolerance
    tested: list[Level] = []
    for lv in m["levels"]:
        # dipped to (or slightly under) the level, closed back above it
        if bar["low"] <= lv.price * (1 + tol) and bar["close"] > lv.price and bar["low"] >= lv.price * (1 - 3 * tol):
            tested.append(lv)
    # confluence = number of distinct support factors converging in the zone
    if len({l.kind for l in tested}) < cfg.min_confluence:
        return None

    if cfg.require_volume_expansion:
        if bar["volume"] < d["volume"].iloc[-21:-1].mean():
            return None

    return Signal(
        symbol=symbol,
        date=d.index[-1],
        trigger=round(float(bar["high"]) * 1.001 + 0.01, 2),
        breakout_bar_low=float(bar["low"]),
        prev_bar_low=float(prev["low"]),
        confluence=tested,
        close=float(bar["close"]),
    )

