# luk_bot
Bot repository for a local server and dev environment

A swing-trading bot after Martin Luk's pullback method.

Four steps, one module each:

| Step | What the bot does | Module |
|---|---|---|
| 1. Screen | Ranks the universe separately by 1M / 3M / 6M gain; keeps names up ≥30% **and** in the top 25% of a ranking; drops thin volume (<500k sh/day or <$20M/day, price <$5); keeps names above a rising 50 EMA with 9>21>50, base ≤35% deep, volatility contracting | `screener.py` |
| 2. Support + signal | Marks EMA 9/21/50, prior swing highs/lows, unfilled gaps, AVWAPs (from the major swing low, latest swing low, swing high, biggest gap-up day). Signal = the day dipped into ≥2 converging support factors and reclaimed them with a close in the upper half of the range. Entry = buy-stop just above that bar's high next session | `levels.py`, `signals.py` |
| 3. Stop and size first | Stop from day low / breakout-bar low / previous-bar low (default: tightest valid). Skip if stop is >7% or <0.5% away. Shares = 0.5% of equity ÷ (entry − stop), capped at 25% of equity. Re-sized on the actual fill so a gap never raises dollar risk | `risk.py` |
| 4. Scale out, track the rest | Sell 1/3 at +3R, 1/3 at +5R, move stop to breakeven after the first sale, exit the remainder on a daily close below the 9 EMA | `position.py` |

All parameters are in `luk_bot/config.py`, tagged `[article]` (from published descriptions of Luk's method) or `[assumption]` (my defaults — tune them).

## Install

```bash
pip install pandas numpy matplotlib yfinance
pip install ib_async          # only for routing to Interactive Brokers
```

## Use

```bash
python -m luk_bot scan                               # Step 1 shortlist (all US stocks; slow first run)
python -m luk_bot scan --universe my_tickers.txt     # your own list, one ticker per line
python -m luk_bot signals --universe my_tickers.txt --charts   # Steps 1-3: today's sized plans + charts
python -m luk_bot chart NVDA                         # Step 2 chart markup for one name
python -m luk_bot backtest --universe my_tickers.txt # full 4-step backtest -> CSVs
python -m luk_bot run --universe my_tickers.txt      # daily paper run after the close (state in paper_state.pkl)
python -m luk_bot run --universe my_tickers.txt --live --port 7497   # route to IBKR (7497 = paper TWS)
```

Run `run` once a day after the US close (e.g. a cron job at 22:30 London time).

## Live routing (IBKR)

Off unless you pass `--live`. Each plan is split into three tranches so a target fill can never over-sell:
tranche 1 = buy-stop → OCA(limit @3R, stop); tranche 2 = buy-stop → OCA(limit @5R, stop); tranche 3 = buy-stop → stop.
The daily run raises stops to breakeven after 3R and sends a market-on-open sell when price closes below the 9 EMA.
**The IBKR adapter has not been run against a real TWS/Gateway yet — test it on an IBKR paper account first.**

## Known limits

- Daily bars only: the entry-day stop is judged conservatively (if the entry bar also trades through the stop, it counts as a loss), and `day_low` stops are only available live.
- Yahoo data is end-of-day and survivorship-biased for backtests; use a point-in-time source for serious testing.
- No market-regime filter (e.g. index above its 50 EMA) — worth adding.
- Not investment advice; the backtest on synthetic data only proves the plumbing works.
