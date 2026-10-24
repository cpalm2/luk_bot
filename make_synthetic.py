"""Synthetic OHLCV universe for offline testing (not real market data)."""
import os
import sys

import numpy as np
import pandas as pd

out = sys.argv[1] if len(sys.argv) > 1 else "synthetic_data"
os.makedirs(out, exist_ok=True)
rng = np.random.default_rng(7)
dates = pd.bdate_range("2024-06-03", periods=500)

for k in range(150):
    drift = rng.normal(0.0003, 0.0008)
    vol = rng.uniform(0.015, 0.035)
    rets = rng.normal(drift, vol, len(dates))
    # some names get momentum legs followed by tight bases
    if k % 3 == 0:
        for _ in range(3):
            s = rng.integers(130, 440)
            rets[s : s + 25] += rng.uniform(0.006, 0.012)    # advance
            rets[s + 25 : s + 55] *= 0.45                    # tightening base
            rets[s + 25 : s + 55] += 0.0008
    close = 30 * np.exp(np.cumsum(rets))
    opn = close * np.exp(rng.normal(0, vol * 0.3, len(dates)))
    opn[1:] = np.where(rng.random(len(dates) - 1) < 0.03, opn[1:] * (1 + rng.normal(0.03, 0.02, len(dates) - 1)), opn[1:])
    hi = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, vol * 0.5, len(dates))))
    lo = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, vol * 0.5, len(dates))))
    v = rng.lognormal(np.log(1.5e6), 0.4, len(dates)) * (0.1 if k % 10 == 9 else 1)  # some illiquid names
    pd.DataFrame({"open": opn, "high": hi, "low": lo, "close": close, "volume": v.astype(int)},
                 index=dates).rename_axis("date").to_csv(f"{out}/SYN{k:03d}.csv")
print(f"wrote 150 symbols to {out}/")
