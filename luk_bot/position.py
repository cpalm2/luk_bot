"""Step 4: take profits in batches after the rise, then track the remainder.

Default plan (configurable in ExitConfig):
  * sell 1/3 of the original position at +3R
  * sell another 1/3 at +5R
  * after the first partial, move the stop to breakeven
  * exit the rest on a daily close below the 9 EMA
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from .config import ExitConfig


@dataclass
class Position:
    symbol: str
    entry_date: pd.Timestamp
    entry: float
    initial_stop: float
    shares: int
    stop: float = 0.0
    original_shares: int = 0
    targets_hit: list = field(default_factory=list)
    trail_armed: bool = False
    exit_next_open: bool = False
    realized: float = 0.0
    fills: list = field(default_factory=list)

    def __post_init__(self):
        self.stop = self.stop or self.initial_stop
        self.original_shares = self.original_shares or self.shares

    @property
    def R(self) -> float:
        return self.entry - self.initial_stop

    @property
    def open(self) -> bool:
        return self.shares > 0

    def _sell(self, date, qty, price, why):
        qty = min(qty, self.shares)
        if qty <= 0:
            return
        self.shares -= qty
        self.realized += qty * (price - self.entry)
        self.fills.append({"date": date, "symbol": self.symbol, "side": "SELL", "qty": qty,
                           "price": round(price, 2), "reason": why,
                           "r": round((price - self.entry) / self.R, 2)})

    def target_orders(self, cfg: ExitConfig) -> list[tuple[float, int]]:
        """Resting limit sells still to be worked: [(price, qty)]."""
        out = []
        for r, frac in cfg.scale_outs:
            if r not in self.targets_hit:
                out.append((round(self.entry + r * self.R, 2), max(1, math.floor(self.original_shares * frac))))
        return out

    def on_bar(self, date, bar: pd.Series, ema_trail: float, cfg: ExitConfig) -> None:
        """Process one completed daily bar (open/high/low/close)."""
        if not self.open:
            return
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]

        # 1) exit flagged at yesterday's close below the trailing EMA
        if self.exit_next_open:
            self._sell(date, self.shares, o, f"close<EMA{cfg.trail_ema}")
            return

        # 2) protective stop (checked before targets: conservative on wide bars)
        if l <= self.stop:
            fill = min(o, self.stop)  # gap through the stop fills at the open
            why = "breakeven stop" if self.stop >= self.entry else "stop"
            self._sell(date, self.shares, fill, why)
            return

        # 3) scale-out targets
        for r, frac in cfg.scale_outs:
            if r in self.targets_hit:
                continue
            px = self.entry + r * self.R
            if h >= px:
                qty = max(1, math.floor(self.original_shares * frac))
                self._sell(date, qty, max(o, px), f"take profit {r:g}R")
                self.targets_hit.append(r)
                if cfg.breakeven_after_first and self.stop < self.entry:
                    self.stop = round(self.entry, 2)
                self.trail_armed = True
        if not self.open:
            return

        # 4) trail the remainder on the daily close
        if (self.trail_armed or not cfg.trail_only_after_first) and c < ema_trail:
            self.exit_next_open = True
