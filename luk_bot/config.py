"""All tunable parameters in one place.

Values marked [article] follow published descriptions of Martin Luk's method.
Values marked [assumption] are sensible defaults you should tune yourself.
"""
from dataclasses import dataclass, field


@dataclass
class ScreenConfig:
    # Step 1: momentum screen
    lookbacks: dict = field(default_factory=lambda: {"1M": 21, "3M": 63, "6M": 126})
    min_gain: float = 0.30            # [article] up >= 30% over 1, 3 or 6 months
    top_percentile: float = 0.25      # keep the top 25% per lookback (user: 20-30%)
    min_avg_volume: float = 500_000   # [assumption] shares/day, 50-day average
    min_avg_dollar_volume: float = 20e6  # [assumption] $/day, 50-day average
    min_price: float = 5.0            # [assumption] skip low-priced names
    volume_window: int = 50
    # "consolidating and gradually gaining strength"
    require_above_ema50: bool = True
    require_ema_stack: bool = True    # 9 > 21 > 50 EMA, 50 EMA rising
    max_base_depth: float = 0.35      # [assumption] base high-to-low drawdown
    base_window: int = 40             # [assumption] ~8 weeks [article: bases of 8+ weeks]
    contraction_ratio: float = 0.85   # [assumption] recent ATR / earlier ATR (tightening)


@dataclass
class SignalConfig:
    # Step 2: support zones and buy signal
    ema_periods: tuple = (9, 21, 50)  # [article]
    pivot_strength: int = 5           # bars each side to qualify as swing high/low
    n_pivots: int = 4                 # recent swing highs/lows to mark
    gap_lookback: int = 120           # bars to search for unfilled gaps
    min_gap_pct: float = 0.01         # ignore gaps smaller than 1%
    zone_tolerance: float = 0.015     # price within 1.5% of a level counts as "at support"
    min_confluence: int = 2           # [article] several support factors converging
    reclaim_close_pos: float = 0.5    # close in upper half of day's range = strong close
    require_volume_expansion: bool = False


@dataclass
class RiskConfig:
    # Step 3: stop first, then size
    account_risk_pct: float = 0.005   # [assumption] risk 0.5% of equity per trade
    max_position_pct: float = 0.25    # [assumption] cap any one position at 25% of equity
    max_stop_pct: float = 0.07        # [article] stops ~1-4%, examples up to 7%; skip wider
    stop_mode: str = "tightest_valid" # "day_low" | "breakout_bar_low" | "prev_bar_low" | "tightest_valid"
    stop_buffer_pct: float = 0.001    # a tick under the low
    max_open_positions: int = 6       # [assumption]
    min_stop_pct: float = 0.005       # avoid noise-sized stops


@dataclass
class ExitConfig:
    # Step 4: take profits in batches, then track the rest
    # (R multiple, fraction of the ORIGINAL position to sell)
    scale_outs: tuple = ((3.0, 1 / 3), (5.0, 1 / 3))   # [user/article] partials around 3R and 5R
    breakeven_after_first: bool = True  # [assumption] move stop to entry after the first partial
    trail_ema: int = 9                  # [article] exit the remainder on a daily close below the 9 EMA
    trail_only_after_first: bool = True # [assumption] trailing starts once the first partial is taken


@dataclass
class BotConfig:
    screen: ScreenConfig = field(default_factory=ScreenConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    exits: ExitConfig = field(default_factory=ExitConfig)
    live: bool = False                # paper by default; live must be switched on explicitly
