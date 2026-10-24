"""Draw the daily chart with the Step 2 markup (and the Step 3/4 plan if given)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .config import SignalConfig
from .levels import mark_levels


def plot_setup(symbol: str, df: pd.DataFrame, path: str, plan=None, bars: int = 160,
               cfg: SignalConfig | None = None) -> str:
    m = mark_levels(df, cfg or SignalConfig())
    d = m["df"].iloc[-bars:]
    x = range(len(d))
    pos = {t: i for i, t in enumerate(d.index)}

    fig, (ax, axv) = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                                  gridspec_kw={"height_ratios": [4, 1]})
    # candles
    for i, (_, r) in enumerate(d.iterrows()):
        up = r["close"] >= r["open"]
        col = "#2e7d32" if up else "#c62828"
        ax.vlines(i, r["low"], r["high"], color=col, lw=0.8)
        ax.add_patch(plt.Rectangle((i - 0.3, min(r["open"], r["close"])), 0.6,
                                   max(abs(r["close"] - r["open"]), 1e-6), color=col))
        axv.bar(i, r["volume"], color=col, width=0.7, alpha=0.6)

    for p, colr in zip((9, 21, 50), ("#1565c0", "#ef6c00", "#6a1b9a")):
        ax.plot(x, d[f"ema{p}"].to_numpy(), lw=1.3, color=colr, label=f"EMA {p}")

    for name, s in m["avwaps"].items():
        s = s.reindex(d.index)
        ax.plot(x, s.to_numpy(), lw=1.2, ls="--", label=name.replace("_", " ").upper())

    for t, p in m["pivot_highs"][-4:]:
        if t in pos:
            ax.hlines(p, pos[t], len(d) - 1, color="grey", lw=0.8, ls=":")
            ax.annotate(f"prior high {p:.2f}", (pos[t], p), fontsize=7, va="bottom", color="grey")
    for t, p in m["pivot_lows"][-4:]:
        if t in pos:
            ax.hlines(p, pos[t], len(d) - 1, color="grey", lw=0.8, ls=":")
            ax.annotate(f"prior low {p:.2f}", (pos[t], p), fontsize=7, va="top", color="grey")

    for g in m["gaps"]:
        start = pos.get(g["date"], 0)
        color = "#43a047" if g["type"] == "up" else "#e53935"
        ax.axhspan(g["bottom"], g["top"], xmin=start / len(d), color=color, alpha=0.12)
        ax.annotate(f"unfilled gap {g['type']}", (start, g["top"]), fontsize=7, color=color)

    if plan is not None:
        ax.axhline(plan.entry, color="black", lw=1, label=f"entry {plan.entry:.2f}")
        ax.axhline(plan.stop, color="red", lw=1, label=f"stop {plan.stop:.2f}")
        for r in (3, 5):
            ax.axhline(plan.r_price(r), color="green", lw=0.8, ls="-.", label=f"{r}R {plan.r_price(r):.2f}")

    ax.set_title(f"{symbol} — daily | EMAs 9/21/50, prior highs/lows, unfilled gaps, AVWAP")
    ax.legend(loc="upper left", fontsize=7, ncol=3)
    ax.grid(alpha=0.2)
    ticks = list(range(0, len(d), max(1, len(d) // 10)))
    axv.set_xticks(ticks, [d.index[i].strftime("%Y-%m-%d") for i in ticks], rotation=30, fontsize=7)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
