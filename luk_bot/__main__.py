"""Command line.

  python -m luk_bot scan     [--universe tickers.txt]          Step 1 shortlist
  python -m luk_bot signals  [--universe tickers.txt]          Steps 1-3: signals + sized plans
  python -m luk_bot chart    NVDA [--out nvda.png]             Step 2 chart markup
  python -m luk_bot backtest [--universe tickers.txt] [--capital 100000]
  python -m luk_bot run      [--universe ...] [--state paper_state.pkl]   daily paper run (after the close)
  python -m luk_bot run --live [--port 7497]                   route plans to IBKR (TWS/Gateway)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .backtest import run_backtest
from .broker import IBKRBroker, PaperBroker
from .chart import plot_setup
from .config import BotConfig
from .data import fetch_yf, load_csv_dir, load_universe
from .engine import Engine
from .indicators import ema
from .risk import size_position
from .screener import screen
from .signals import check_signal


def _data(args):
    if args.csv_dir:
        return load_csv_dir(args.csv_dir)
    syms = load_universe(args.universe)
    print(f"downloading {len(syms)} symbols...")
    return fetch_yf(syms, period=args.period)


def cmd_scan(args, cfg):
    data = _data(args)
    short = screen(data, cfg.screen, verbose=True)
    cols = ["close", "ret_1M", "ret_3M", "ret_6M", "avg_dollar_volume", "base_depth", "atr_contraction", "score"]
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(short[cols].head(args.top))
    return data, short


def cmd_signals(args, cfg):
    data, short = cmd_scan(args, cfg)
    equity = args.capital
    for sym in short.index[: args.top]:
        sig = check_signal(sym, data[sym], cfg.signal)
        if not sig:
            continue
        plan = size_position(sym, sig.trigger, {"breakout_bar_low": sig.breakout_bar_low,
                                                "prev_bar_low": sig.prev_bar_low}, equity, cfg.risk)
        print("\n" + sig.describe())
        print("  " + (plan.describe() if plan else "no valid stop within limits -> skip"))
        if plan and args.charts:
            print("  chart:", plot_setup(sym, data[sym], f"{sym}_setup.png", plan))


def cmd_chart(args, cfg):
    data = fetch_yf([args.symbol], period=args.period) if not args.csv_dir else load_csv_dir(args.csv_dir)
    df = data[args.symbol.upper()]
    print(plot_setup(args.symbol.upper(), df, args.out or f"{args.symbol.upper()}_chart.png"))


def cmd_backtest(args, cfg):
    data = _data(args)
    res = run_backtest(data, args.capital, cfg, start=args.start, verbose=not args.quiet)
    print(json.dumps(res["stats"], indent=2, default=str))
    res["trades"].to_csv("backtest_trades.csv", index=False)
    res["fills"].to_csv("backtest_fills.csv", index=False)
    res["equity"].to_csv("backtest_equity.csv")
    print("wrote backtest_trades.csv, backtest_fills.csv, backtest_equity.csv")

    eq = res["equity"]
    if args.benchmark and len(eq) and not args.csv_dir:
        b = fetch_yf([args.benchmark], period=args.period).get(args.benchmark)
        if b is not None:
            bc = b["close"].reindex(eq.index).ffill().dropna()
            bench = args.capital * bc / bc.iloc[0]
            bdd = float((bench / bench.cummax() - 1).min())
            yrs = (eq.index[-1] - eq.index[0]).days / 365.25
            cagr = lambda s: (float(s.iloc[-1]) / args.capital) ** (1 / yrs) - 1
            print(f"\n{'':12}{'bot':>12}{args.benchmark + ' hold':>12}")
            print(f"{'return':12}{eq.iloc[-1] / args.capital - 1:>12.1%}{bench.iloc[-1] / args.capital - 1:>12.1%}")
            print(f"{'CAGR':12}{cagr(eq):>12.1%}{cagr(bench):>12.1%}")
            print(f"{'max DD':12}{res['stats']['max_drawdown']:>12.1%}{bdd:>12.1%}")
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(11, 5))
            ax.plot(eq.index, eq.to_numpy(), label="luk_bot")
            ax.plot(bench.index, bench.to_numpy(), label=f"{args.benchmark} buy & hold")
            ax.set_title(f"Equity, ${args.capital:,.0f} start"); ax.legend(); ax.grid(alpha=0.3)
            fig.tight_layout(); fig.savefig("backtest_equity.png", dpi=110)
            print("wrote backtest_equity.png")


def cmd_run(args, cfg):
    data = _data(args)
    last = max(df.index[-1] for df in data.values())
    if not args.live:
        broker = PaperBroker(args.state, args.capital)
        st = broker.load()
        plans = Engine(cfg).step(st, last, data)
        broker.save(st)
        for f in st.fills[-20:]:
            print("fill:", f)
        for sig, plan in plans:
            print("NEW  ", sig.describe(), "\n     ", plan.describe())
        print(f"paper equity {st.equity_curve[-1][1]:,.2f}  open: {list(st.positions)}  queued: {list(st.pending)}")
        return

    # ---- live via IBKR ----
    cfg.live = True
    ib = IBKRBroker(cfg, port=args.port)
    journal_path = Path(args.journal)
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {}
    held = {p.contract.symbol: p.position for p in ib.ib.positions() if p.position > 0}

    # Step 4 management for positions the bot opened
    for sym, info in list(journal.items()):
        if sym not in held:
            if info.get("filled"):
                journal.pop(sym)            # fully exited
            continue
        info["filled"] = True
        df = data.get(sym)
        if df is None:
            continue
        r = info["entry"] - info["stop"]
        hi_since = df.loc[pd.Timestamp(info["date"]):, "high"].max()
        first_r = cfg.exits.scale_outs[0][0]
        if hi_since >= info["entry"] + first_r * r:
            if cfg.exits.breakeven_after_first:
                ib.move_stops(sym, info["entry"])
            if df["close"].iloc[-1] < ema(df["close"], cfg.exits.trail_ema).iloc[-1]:
                print(f"{sym}: close below EMA{cfg.exits.trail_ema} -> sell remainder at the open")
                ib.exit_at_open(sym)

    # Steps 1-3 for new entries
    equity = ib.equity()
    slots = cfg.risk.max_open_positions - len(held)
    short = screen(data, cfg.screen, verbose=True)
    for sym in short.index[:30]:
        if slots <= 0:
            break
        if sym in held or sym in journal:
            continue
        sig = check_signal(sym, data[sym], cfg.signal)
        if not sig:
            continue
        plan = size_position(sym, sig.trigger, {"breakout_bar_low": sig.breakout_bar_low,
                                                "prev_bar_low": sig.prev_bar_low}, equity, cfg.risk)
        if not plan:
            continue
        print("LIVE ", plan.describe())
        ib.place_plan(plan)
        journal[sym] = {"date": str(sig.date.date()), "entry": plan.entry, "stop": plan.stop, "shares": plan.shares}
        slots -= 1
    journal_path.write_text(json.dumps(journal, indent=2))


def main():
    p = argparse.ArgumentParser(prog="luk_bot")
    p.add_argument("command", choices=["scan", "signals", "chart", "backtest", "run"])
    p.add_argument("symbol", nargs="?")
    p.add_argument("--universe", help="text file of tickers (default: all US-listed stocks)")
    p.add_argument("--csv-dir", help="use local CSVs instead of downloading")
    p.add_argument("--period", default="2y")
    p.add_argument("--capital", type=float, default=100_000)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--charts", action="store_true")
    p.add_argument("--out")
    p.add_argument("--start")
    p.add_argument("--benchmark", default="QQQ", help="buy-and-hold comparison ticker ('' to skip)")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--state", default="paper_state.pkl")
    p.add_argument("--live", action="store_true")
    p.add_argument("--port", type=int, default=7497, help="7497 = TWS paper, 7496 = TWS live")
    p.add_argument("--journal", default="live_journal.json")
    args = p.parse_args()
    cfg = BotConfig()
    {"scan": cmd_scan, "signals": cmd_signals, "chart": cmd_chart,
     "backtest": cmd_backtest, "run": cmd_run}[args.command](args, cfg)


if __name__ == "__main__":
    main()
