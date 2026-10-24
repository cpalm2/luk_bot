"""Order routing.

PaperBroker  - default. Keeps engine state on disk and simulates fills from
               daily bars with exactly the backtest logic.
IBKRBroker   - optional. Sends the plan to TWS / IB Gateway via ib_async.
               Requires `pip install ib_async`, TWS or Gateway running with
               API enabled, and BotConfig.live = True. Test on an IBKR paper
               account (port 7497) before pointing at a live one.

How a plan becomes IBKR orders (risk first, then the order):
  The position is split into tranches so a partial fill never over-sells:
    tranche 1 (1/3): BUY STP-LMT @ trigger -> OCA[ SELL LMT @3R , SELL STP @stop ]
    tranche 2 (1/3): BUY STP-LMT @ trigger -> OCA[ SELL LMT @5R , SELL STP @stop ]
    tranche 3 (rest): BUY STP-LMT @ trigger -> SELL STP @stop  (trailed by the bot)
  The daily `manage` run moves stops to breakeven after the first target and
  sends a market-on-open sell when the close is below the 9 EMA.
"""
from __future__ import annotations

import math
import pickle
from pathlib import Path

from .config import BotConfig
from .engine import EngineState
from .risk import TradePlan


class PaperBroker:
    def __init__(self, state_path: str = "paper_state.pkl", capital: float = 100_000):
        self.path = Path(state_path)
        self.capital = capital

    def load(self) -> EngineState:
        if self.path.exists():
            with self.path.open("rb") as f:
                return pickle.load(f)
        return EngineState(cash=self.capital)

    def save(self, state: EngineState) -> None:
        with self.path.open("wb") as f:
            pickle.dump(state, f)


class IBKRBroker:
    def __init__(self, cfg: BotConfig, host: str = "127.0.0.1", port: int = 7497, client_id: int = 17):
        if not cfg.live:
            raise RuntimeError("Live routing is off. Set BotConfig.live = True (and use --live) to enable.")
        from ib_async import IB  # pip install ib_async

        self.cfg = cfg
        self.ib = IB()
        self.ib.connect(host, port, clientId=client_id)

    def equity(self) -> float:
        for v in self.ib.accountSummary():
            if v.tag == "NetLiquidation" and v.currency == "USD":
                return float(v.value)
        raise RuntimeError("NetLiquidation not available")

    def place_plan(self, plan: TradePlan, limit_slip_pct: float = 0.005) -> list:
        from ib_async import LimitOrder, Order, Stock, StopOrder

        contract = Stock(plan.symbol, "SMART", "USD")
        self.ib.qualifyContracts(contract)
        fracs = [f for _, f in self.cfg.exits.scale_outs]
        qtys = [max(1, math.floor(plan.shares * f)) for f in fracs]
        qtys.append(plan.shares - sum(qtys))
        targets = [plan.r_price(r) for r, _ in self.cfg.exits.scale_outs] + [None]
        trades = []
        for i, (q, tgt) in enumerate(zip(qtys, targets)):
            if q <= 0:
                continue
            parent = Order(action="BUY", orderType="STP LMT", totalQuantity=q,
                           auxPrice=plan.entry, lmtPrice=round(plan.entry * (1 + limit_slip_pct), 2),
                           tif="DAY", transmit=False, orderRef=f"luk:{plan.symbol}:t{i+1}")
            parent.orderId = self.ib.client.getReqId()
            oca = f"luk-{plan.symbol}-{parent.orderId}"
            stop = StopOrder("SELL", q, plan.stop, tif="GTC", parentId=parent.orderId,
                             ocaGroup=oca, ocaType=1, transmit=tgt is None,
                             orderRef=f"luk:{plan.symbol}:stop{i+1}")
            orders = [parent, stop]
            if tgt is not None:
                tp = LimitOrder("SELL", q, tgt, tif="GTC", parentId=parent.orderId,
                                ocaGroup=oca, ocaType=1, transmit=True,
                                orderRef=f"luk:{plan.symbol}:tp{i+1}")
                orders.append(tp)
            for o in orders:
                trades.append(self.ib.placeOrder(contract, o))
        return trades

    def move_stops(self, symbol: str, new_stop: float) -> None:
        for t in self.ib.openTrades():
            o = t.order
            if t.contract.symbol == symbol and o.orderType == "STP" and o.action == "SELL" \
                    and str(o.orderRef).startswith("luk:") and o.auxPrice < new_stop:
                o.auxPrice = new_stop
                self.ib.placeOrder(t.contract, o)

    def exit_at_open(self, symbol: str) -> None:
        from ib_async import MarketOrder, Stock

        pos = [p for p in self.ib.positions() if p.contract.symbol == symbol and p.position > 0]
        if not pos:
            return
        for t in self.ib.openTrades():   # cancel resting luk orders first
            if t.contract.symbol == symbol and str(t.order.orderRef).startswith("luk:"):
                self.ib.cancelOrder(t.order)
        c = Stock(symbol, "SMART", "USD")
        self.ib.qualifyContracts(c)
        self.ib.placeOrder(c, MarketOrder("SELL", pos[0].position, tif="OPG", orderRef=f"luk:{symbol}:trail"))
