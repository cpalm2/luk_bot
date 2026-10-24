"""Daily engine shared by the backtest and the paper/live runner.

After each close:
  1. fill or cancel yesterday's buy-stop entries          (Step 3 orders)
  2. manage open positions: stops, 3R/5R partials, trail  (Step 4)
  3. refresh the watchlist with the screener              (Step 1)
  4. look for buy signals at support on the watchlist     (Step 2)
  5. size new trades from the stop, queue buy-stops       (Step 3)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import BotConfig
from .indicators import ema
from .position import Position
from .risk import TradePlan, size_position
from .screener import screen
from .signals import check_signal


@dataclass
class PendingEntry:
    plan: TradePlan
    trigger: float
    candidates: dict
    signal_date: pd.Timestamp
    note: str = ""


@dataclass
class EngineState:
    cash: float
    positions: dict = field(default_factory=dict)      # symbol -> Position
    pending: dict = field(default_factory=dict)        # symbol -> PendingEntry
    watchlist: list = field(default_factory=list)
    closed: list = field(default_factory=list)         # closed Position objects
    fills: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    last_screen: pd.Timestamp | None = None


class Engine:
    def __init__(self, cfg: BotConfig | None = None, max_chase_pct: float = 0.02,
                 screen_every_days: int = 1, watchlist_size: int = 30):
        self.cfg = cfg or BotConfig()
        self.max_chase_pct = max_chase_pct          # skip entries that gap > 2% above trigger
        self.screen_every_days = screen_every_days
        self.watchlist_size = watchlist_size

    # ---------- helpers ----------
    @staticmethod
    def equity(state: EngineState, closes: dict[str, float]) -> float:
        return state.cash + sum(p.shares * closes.get(s, p.entry) for s, p in state.positions.items())

    # ---------- 1. entries ----------
    def _fill_entries(self, state, date, bars):
        for sym, pe in list(state.pending.items()):
            del state.pending[sym]
            bar = bars.get(sym)
            if bar is None or sym in state.positions:
                continue
            o, h, l = bar["open"], bar["high"], bar["low"]
            if h < pe.trigger:
                continue                                   # never triggered: order expires
            if o > pe.trigger * (1 + self.max_chase_pct):
                continue                                   # gapped too far above: don't chase
            entry = max(o, pe.trigger)
            # re-size from the actual fill so dollar risk never exceeds plan
            stop = pe.plan.stop
            rps = entry - stop
            if rps <= 0:
                continue
            shares = min(pe.plan.shares, int(pe.plan.risk_dollars // rps))
            if shares < 1 or shares * entry > state.cash:
                shares = min(shares, int(state.cash // entry))
            if shares < 1:
                continue
            state.cash -= shares * entry
            pos = Position(sym, date, round(entry, 2), stop, shares)
            pos.fills.append({"date": date, "symbol": sym, "side": "BUY", "qty": shares,
                              "price": round(entry, 2), "reason": f"buy-stop ({pe.plan.stop_source})", "r": 0.0})
            state.positions[sym] = pos
            # conservative: if the entry day also traded through the stop, assume stopped
            if l <= stop:
                pos._sell(date, pos.shares, stop, "stop (entry day)")

    # ---------- 2. manage ----------
    def _manage(self, state, date, bars, ema_trail):
        for sym, pos in list(state.positions.items()):
            bar = bars.get(sym)
            if bar is not None and not (pos.entry_date == date):
                pos.on_bar(date, bar, ema_trail[sym], self.cfg.exits)
            # settle cash for new fills
            for f in pos.fills:
                if f.get("_settled"):
                    continue
                f["_settled"] = True
                if f["side"] == "SELL":
                    state.cash += f["qty"] * f["price"]
                state.fills.append({k: v for k, v in f.items() if k != "_settled"})
            if not pos.open:
                state.closed.append(pos)
                del state.positions[sym]

    # ---------- 3-5. scan, signal, plan ----------
    def _scan_and_plan(self, state, date, hist, closes):
        if (state.last_screen is None or (date - state.last_screen).days >= self.screen_every_days):
            short = screen(hist, self.cfg.screen)
            state.watchlist = list(short.index[: self.watchlist_size])
            state.last_screen = date

        eq = self.equity(state, closes)
        slots = self.cfg.risk.max_open_positions - len(state.positions)
        plans = []
        for sym in state.watchlist:
            if slots <= 0:
                break
            if sym in state.positions or sym in state.pending or sym not in hist:
                continue
            sig = check_signal(sym, hist[sym], self.cfg.signal)
            if sig is None:
                continue
            cands = {"breakout_bar_low": sig.breakout_bar_low, "prev_bar_low": sig.prev_bar_low}
            plan = size_position(sym, sig.trigger, cands, eq, self.cfg.risk)
            if plan is None:
                continue
            state.pending[sym] = PendingEntry(plan, sig.trigger, cands, date, sig.describe())
            plans.append((sig, plan))
            slots -= 1
        return plans

    # ---------- one day ----------
    def step(self, state: EngineState, date: pd.Timestamp, data: dict[str, pd.DataFrame]):
        """`data` holds full history; only bars up to `date` are used."""
        hist = {s: df.loc[:date] for s, df in data.items()}
        hist = {s: df for s, df in hist.items() if len(df) and df.index[-1] == date}
        bars = {s: df.iloc[-1] for s, df in hist.items()}
        closes = {s: float(b["close"]) for s, b in bars.items()}
        trail = {s: float(ema(hist[s]["close"], self.cfg.exits.trail_ema).iloc[-1])
                 for s in state.positions if s in hist}

        self._fill_entries(state, date, bars)
        for s in state.positions:
            if s not in trail and s in hist:
                trail[s] = float(ema(hist[s]["close"], self.cfg.exits.trail_ema).iloc[-1])
        self._manage(state, date, bars, trail)
        plans = self._scan_and_plan(state, date, hist, closes)
        state.equity_curve.append((date, self.equity(state, closes)))
        return plans
