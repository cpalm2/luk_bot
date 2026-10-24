"""Step 3: set the stop and position size first, then place the order.

Stop candidates:
  day_low          - today's low (live: intraday low at the time of entry)
  breakout_bar_low - low of the breakout / signal K-line
  prev_bar_low     - low of the K-line before it
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import RiskConfig


@dataclass
class TradePlan:
    symbol: str
    entry: float
    stop: float
    shares: int
    stop_source: str
    risk_per_share: float
    risk_dollars: float
    position_value: float
    reason: str = ""

    @property
    def stop_pct(self) -> float:
        return self.risk_per_share / self.entry

    def r_price(self, r: float) -> float:
        return round(self.entry + r * self.risk_per_share, 2)

    def describe(self) -> str:
        return (f"{self.symbol}: BUY {self.shares} @ {self.entry:.2f}  STOP {self.stop:.2f} "
                f"({self.stop_pct:.1%}, {self.stop_source})  risk ${self.risk_dollars:,.0f}  "
                f"size ${self.position_value:,.0f}  3R {self.r_price(3):.2f}  5R {self.r_price(5):.2f}")


def choose_stop(entry: float, candidates: dict[str, float], cfg: RiskConfig) -> tuple[float, str] | None:
    """Pick the stop per cfg.stop_mode. Returns (stop_price, source) or None if no valid stop."""
    buf = 1 - cfg.stop_buffer_pct
    valid = {}
    for name, low in candidates.items():
        if low is None or math.isnan(low):
            continue
        stop = round(low * buf - 0.01, 2)
        pct = (entry - stop) / entry
        if stop < entry and cfg.min_stop_pct <= pct <= cfg.max_stop_pct:
            valid[name] = stop
    if not valid:
        return None
    if cfg.stop_mode == "tightest_valid":
        name = max(valid, key=valid.get)  # highest stop = least risk per share
        return valid[name], name
    if cfg.stop_mode in valid:
        return valid[cfg.stop_mode], cfg.stop_mode
    return None


def size_position(symbol: str, entry: float, candidates: dict[str, float], equity: float,
                  cfg: RiskConfig | None = None) -> TradePlan | None:
    cfg = cfg or RiskConfig()
    chosen = choose_stop(entry, candidates, cfg)
    if chosen is None:
        return None
    stop, source = chosen
    rps = entry - stop
    by_risk = math.floor(equity * cfg.account_risk_pct / rps)
    by_cap = math.floor(equity * cfg.max_position_pct / entry)
    shares = min(by_risk, by_cap)
    if shares < 1:
        return None
    return TradePlan(
        symbol=symbol, entry=round(entry, 2), stop=stop, shares=shares, stop_source=source,
        risk_per_share=round(rps, 4), risk_dollars=round(shares * rps, 2),
        position_value=round(shares * entry, 2),
        reason="capped by max_position_pct" if by_cap < by_risk else "",
    )
