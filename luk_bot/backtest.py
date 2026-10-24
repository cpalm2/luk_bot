"""Walk the engine forward day by day over historical data."""
from __future__ import annotations

import pandas as pd

from .config import BotConfig
from .engine import Engine, EngineState


def run_backtest(data: dict[str, pd.DataFrame], capital: float = 100_000, cfg: BotConfig | None = None,
                 start: str | None = None, warmup: int = 130, screen_every_days: int = 5,
                 verbose: bool = True) -> dict:
    eng = Engine(cfg, screen_every_days=screen_every_days)
    st = EngineState(cash=capital)
    dates = sorted(set().union(*[df.index for df in data.values()]))
    dates = dates[warmup:]
    if start:
        dates = [d for d in dates if d >= pd.Timestamp(start)]
    for d in dates:
        plans = eng.step(st, d, data)
        if verbose:
            for sig, plan in plans:
                print(f"{d.date()} SIGNAL {sig.describe()}\n            PLAN {plan.describe()}")
    # mark remaining open positions at the last close
    eq = pd.Series(dict(st.equity_curve), name="equity")
    trades = []
    for p in st.closed + list(st.positions.values()):
        risk = p.R * p.original_shares
        trades.append({"symbol": p.symbol, "entry_date": p.entry_date.date(), "entry": p.entry,
                       "stop": p.initial_stop, "shares": p.original_shares,
                       "realized_pnl": round(p.realized, 2),
                       "R": round(p.realized / risk, 2) if risk else 0.0,
                       "partials": ",".join(f"{r:g}R" for r in p.targets_hit),
                       "status": "open" if p.open else "closed"})
    trades = pd.DataFrame(trades)
    return {"equity": eq, "trades": trades, "fills": pd.DataFrame(st.fills), "stats": stats(eq, trades, capital)}


def stats(eq: pd.Series, trades: pd.DataFrame, capital: float) -> dict:
    if eq.empty:
        return {}
    dd = eq / eq.cummax() - 1
    closed = trades[trades["status"] == "closed"] if len(trades) else trades
    out = {
        "start_equity": capital,
        "end_equity": round(float(eq.iloc[-1]), 2),
        "total_return": round(float(eq.iloc[-1] / capital - 1), 4),
        "max_drawdown": round(float(dd.min()), 4),
        "trades": int(len(trades)),
    }
    if len(closed):
        wins = closed[closed["R"] > 0]
        out.update({
            "win_rate": round(len(wins) / len(closed), 3),
            "avg_R": round(float(closed["R"].mean()), 2),
            "avg_win_R": round(float(wins["R"].mean()), 2) if len(wins) else 0.0,
            "avg_loss_R": round(float(closed[closed["R"] <= 0]["R"].mean()), 2) if len(wins) < len(closed) else 0.0,
            "best_R": round(float(closed["R"].max()), 2),
            "hit_3R": int(closed["partials"].str.contains("3R").sum()),
            "hit_5R": int(closed["partials"].str.contains("5R").sum()),
        })
    return out
