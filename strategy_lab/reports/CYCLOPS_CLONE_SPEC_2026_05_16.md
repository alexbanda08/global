# Cyclops Clone — Full Build Spec (Greenfield)

**Date:** 2026-05-16
**Status:** Spec only. Zero code written. Next session executes this from scratch.
**Target codebase root:** `strategy_lab/cyclops/` (new package)
**Authoritative source for architecture:** `strategy_lab/reports/CYCLOPS_ARCHITECTURE_DEEP_DIVE_2026_05_16.md` §§19-22 (the Q1/Q2/Q3 + conflict-filter pivot is what we are copying, NOT the older 4-dim vector or Kelly-with-tier-caps that he already deleted)

---

## 0. One-paragraph context

Gustafssonkotte's Cyclops bot trades BTC binary 5m markets on Polymarket. After 5 months of architectural churn he settled on a 3-axis signal decomposition (Trend / Levels / Momentum) gated by a *conflict filter* that skips any setup where the three axes disagree. On May 11 he reported deleting half his code (the voter, the tier table, "fair_probability", "edge"), and his Day-1-after-fix result was 33 trades / 60% WR (n is small; don't overweight). Three daily updates that followed (Day 1/2/3 cheat-code log) reveal concrete env vars + a regime-asymmetric blowoff guard + the explicit drop of multi-exchange heatmap as a 5m signal. This spec is OUR Polymarket-binary copy of that architecture. We are not refining momo. We are not stacking onto confluence. We start clean.

## 1. Mission, scope, non-goals

### Mission

Build a single-file-per-module Python package `strategy_lab/cyclops/` that:

1. Loads our existing canonical Polymarket data (`from data.v4.canonical.load import *`)
2. Computes three independent axis signals (Trend / Levels / Momentum) per market at `ws_s + 120` (production fire moment)
3. Applies a **conflict filter** that hard-skips any market where the axes disagree
4. For surviving markets, sizes the trade simply (fixed notional → graduate to confidence-scaled later)
5. Walks the L25 book at $25 notional (production fill model)
6. Reports per-trade PnL + standard validation gates (perm / walkforward / bootstrap)

### Scope (what we DO build)

- 3-axis brain (`trend.py` / `levels.py` / `momentum.py`)
- Conflict filter (`conflict_filter.py`)
- Time-of-day gate (`hours_guard.py`)
- Re-entry cooldown (`reentry_lock.py`)
- OB manipulation guard (`ob_manipulation.py`)
- Blowoff guard with regime asymmetry (`blowoff_guard.py`)
- Position sizing — start fixed-$25, then add `confidence_scaled.py` if Phase 1 passes
- Risk manager (`risk.py`) — peak DD halt + daily-loss halt + balance-recovery resume
- Backtest driver (`backtest.py`) using canonical loaders + L25 walk
- Validation runner (`validate.py`) — perm/walkforward/bootstrap battery
- Telemetry contract (event schema for paper + live)

### Non-goals (DO NOT BUILD — Cyclops himself dropped these)

| Component | Why dropped |
|---|---|
| ❌ "voter" / weighted-average aggregator | He deleted it May 11 — "average of contradictions" |
| ❌ tier table (GOLD/SILVER/BRONZE/MICRO) | He deleted it May 11 |
| ❌ "fair probability" lookup `{n: prob}` | He deleted it May 11 |
| ❌ Kelly-with-edge sizing (`edge = signal_prob - entry_px`) | He deleted it May 11 |
| ❌ Cross-exchange heatmap module | Day 3: heatmap on 5m is "noise, sometimes contrarian" |
| ❌ Pattern-memory bank (240-segment Cyclops feature from earlier articles) | Out-of-scope; binary 5m markets too short for pattern memory |
| ❌ Existing momo / confluence / V5 derivatives strategies | We are NOT combining. Treat as parallel new sleeve. |

### Reuse policy

We MAY reuse from the existing codebase:
- `data/v4/canonical/load.py` — all data loaders
- `data/v4/canonical/_test_ws_s.py` — ws_s convention self-test (run before any backtest)
- `strategy_lab/book_walk.py` — `book_walk_fill(ask_p, ask_s, $25)` production fill model
- `strategy_lab/polymarket_stats.py` — `equity_curve_stats` for sharpe / max DD
- `strategy_lab/meta_classifier/extended_backtest_with_robustness.py:permutation_test` — perm test 1000+ draws
- The `asof_strict` causal asof from canonical

We MAY NOT reuse:
- Any strategy code (`run_*.py`, `momo_*.py`, `confluence/*`, `v4_signals/*`)
- Any existing tier classifier or weighting scheme
- Any production controller code from VPS3

If a piece of engine code looks useful but doesn't fit the "loader / fill / stats" buckets above, copy the relevant function INTO `cyclops/` rather than importing — the principle is greenfield + clear dependency edges.

---

## 2. Architecture

The bot answers three independent yes/no questions about each market and only fires when they coherently agree. That's it. The flow:

```
       For each fired-eligible market at ws_s + 120s
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
    ┌───────┐           ┌────────┐          ┌──────────┐
    │ Q1    │           │  Q2    │          │  Q3      │
    │ Trend │           │ Levels │          │ Momentum │
    │ (MTF) │           │ (15m)  │          │ (OB/CVD) │
    └───┬───┘           └───┬────┘          └────┬─────┘
        │                   │                    │
        ▼                   ▼                    ▼
    {-1, 0, +1}         {-1, 0, +1}         {-1, 0, +1}
        │                   │                    │
        └───────────────────┴────────────────────┘
                            │
                            ▼
                  ┌────────────────────┐
                  │  Conflict filter   │
                  │  pos > 0 AND       │
                  │  neg > 0  → SKIP   │
                  │  abst >= 2 → SKIP  │
                  │  else  → FIRE      │
                  └─────────┬──────────┘
                            │
                            ▼
               ┌──────────────────────────┐
               │  Pre-flight guards       │
               │  - hours_guard           │
               │  - blowoff_guard         │
               │  - ob_manipulation       │
               │  - reentry_lock          │
               │  - risk_paused?          │
               └─────────┬────────────────┘
                         │
                         ▼
              ┌─────────────────────────┐
              │  Size + walk L25 book   │
              │  - fixed $25 (Phase 1)  │
              │  - confidence-scaled    │
              │    (Phase 2)            │
              └─────────┬───────────────┘
                        │
                        ▼
              ┌─────────────────────────┐
              │  Settle vs chainlink    │
              │  Resolve win/loss       │
              │  2% fee on profit only  │
              └─────────────────────────┘
```

No averaging. No weighted sum. Three votes, one filter, one fire.

---

## 3. Module layout

```
strategy_lab/cyclops/
├── __init__.py
├── README.md                            # quick-start
├── conventions.py                       # constants (NOTIONAL_USD, FEE_RATE, etc.)
├── data_io.py                           # thin wrappers over canonical load.py
├── axes/
│   ├── __init__.py
│   ├── trend.py                         # Q1: MTF alignment metric (1h/15m/5m)
│   ├── levels.py                        # Q2: 15m S/R pivots
│   └── momentum.py                      # Q3: OB pressure + CVD on short TF
├── filters/
│   ├── __init__.py
│   ├── conflict.py                      # THE conflict filter — heart of the bot
│   ├── hours_guard.py                   # weekday-business-hours-only schedule
│   ├── blowoff_guard.py                 # regime-asymmetric BB+RSI+MTF skip
│   ├── ob_manipulation.py               # OB volatility suppression
│   └── reentry_lock.py                  # 30s lock per condition_id
├── sizing/
│   ├── __init__.py
│   ├── fixed.py                         # Phase 1: $25 flat
│   └── confidence_scaled.py             # Phase 2: scale to coherent-vote magnitude
├── risk/
│   ├── __init__.py
│   └── drawdown_manager.py              # peak DD + daily loss + recovery resume
├── backtest/
│   ├── __init__.py
│   ├── runner.py                        # main driver: universe → axes → filter → fill → pnl
│   └── replay.py                        # production-shadow replay harness (later)
├── validate/
│   ├── __init__.py
│   ├── permutation.py                   # sign-flip perm (1000 draws)
│   ├── walkforward.py                   # rolling 5d train / 2d test
│   └── bootstrap.py                     # 10k bootstrap CI on per-trade pnl
├── telemetry/
│   ├── __init__.py
│   └── events.py                        # event schema for paper + future live
└── tests/
    ├── test_conventions.py
    ├── test_axes.py
    ├── test_conflict_filter.py
    ├── test_backtest_smoke.py
    └── test_ws_s_inherited.py           # re-runs canonical/_test_ws_s.py via subprocess
```

Each module is single-purpose. No cross-imports between `axes/` files. No `filters/` file imports another filter. The `backtest/runner.py` is the only place that wires them together.

---

## 4. Per-module spec

### 4.1 `conventions.py` (constants + canonical paths)

```python
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CANONICAL = ROOT / "data" / "v4" / "canonical"
RESULTS_DIR = ROOT / "strategy_lab" / "cyclops" / "_results"

# Fill model
NOTIONAL_USD = 25.0
FEE_RATE = 0.02                          # on profit only, win leg

# Anchor convention
WINDOW_S = {"5m": 300, "15m": 900}

# Axis thresholds (tunable in Phase 2 calibration)
TREND_MIN_ABS = 1                        # |alignment| >= 1 to vote (range -3..+3)
LEVELS_MIN_CERTAINTY = 0.15              # |p_up - 0.5| >= 0.15 to vote
MOMENTUM_MIN_STRENGTH = 0.15             # |flow_score| >= 0.15 to vote

# Conflict filter
ABSTAIN_LIMIT = 2                        # if 2+ axes abstain → skip

# Risk
MAX_DRAWDOWN_PCT = 5.0                   # halt if peak-current >= 5%
DAILY_LOSS_LIMIT_PCT = 2.0               # halt for the day
RECOVERY_RESUME_FACTOR = 0.5             # resume after balance climbs back to peak*(1 - 0.5*MAX_DD)

# Cooldowns
REENTRY_COOLDOWN_SEC = 30

# OB manipulation
OB_VOLATILITY_WINDOW_S = 5
OB_VOLATILITY_THRESHOLD = 0.5

# Blowoff guard (regime-ASYMMETRIC per his Day 3)
BLOWOFF_RSI_THRESHOLD = 60.0
BLOWOFF_MIN_MTF_ABS = 3
BLOWOFF_GUARD_UP = True                  # block UP-blowoff entries
BLOWOFF_GUARD_DOWN = False               # allow DOWN-blowoff entries

# Trading hours (UTC, fractional hours supported)
TRADING_START_UTC = 13.0                 # 13:00 UTC — adjust based on per-universe backtest
TRADING_STOP_UTC = 21.0
PAUSE_WINDOWS_UTC = []                   # e.g. [(8.0, 8.75)]
WEEKEND_OFF = True

# VWAP
VWAP_WINDOW_BARS = 24                    # 2h of 5m bars
```

### 4.2 `data_io.py` (thin wrappers over canonical)

Only purpose: keep `cyclops/` code from caring about the canonical path layout. If the canonical API changes, only this file edits.

```python
import sys
from .conventions import CANONICAL, WINDOW_S

sys.path.insert(0, str(CANONICAL))

from load import (
    load_resolutions,
    load_klines, load_klines_asof,
    load_chainlink_rtds, load_chainlink_asof,
    load_orderbook_l25_streaming,
    load_tier1_entries,
    load_trades,                          # ⚠ stale through May 6
    asof_strict,
    slug_to_ws_s, add_ws_s, ret_2m_at_ws,
)

def load_btc_universe():
    res = load_resolutions(assets=["BTC"], timeframes=["5m"])
    res = add_ws_s(res)
    return res

# ... convenience wrappers per asset / tf as needed
```

### 4.3 `axes/trend.py` — Q1 MTF alignment

```python
def compute_trend_axis(klines_1h, klines_15m, klines_5m, ws_s):
    """Return signed alignment in {-3, -2, -1, 0, +1, +2, +3}.

    For each timeframe in (1h, 15m, 5m):
      slope = rolling regression slope over the prior K bars ending at ws_s
      vote  = +1 if slope > +eps else -1 if slope < -eps else 0
    alignment = sum(votes)

    K per TF (start values; tune in Phase 2):
      1h:  K=25 (25 hours of context)
      15m: K=100 (25 hours)
      5m:  K=288 (24 hours)

    Eps per TF set so ~30% of bars vote 0 (abstain) and 35% each sign.
    """
```

Returns: `int` in [-3, +3].

### 4.4 `axes/levels.py` — Q2 S/R pivots on 15m

```python
def compute_levels_axis(klines_15m, ws_s, current_px):
    """Return p_up in [0, 1].

    1. Extract swing-high / swing-low pivots over the prior 5 days of 15m klines.
       A 'swing high' = local maximum where K bars before AND K bars after are lower.
       Use K=5 for 15m (~75 min of lookback/lookahead confirmation).
    2. Find nearest resistance above current_px and nearest support below.
    3. p_up = 0.5 + scale * (dist_above - dist_below) / (dist_above + dist_below + eps)
       where scale = 0.4 (so p_up ∈ [0.1, 0.9])
    4. If no resistance OR no support within 5d window → return 0.5 (abstain)

    p_up > 0.5 + LEVELS_MIN_CERTAINTY → vote +1 (Up)
    p_up < 0.5 - LEVELS_MIN_CERTAINTY → vote -1 (Down)
    else                              → vote 0 (abstain)
    """
```

Reuse logic from `strategy_lab/confluence/structure/sr_levels.py` (we built this for SILVER) — but copy the function into `cyclops/axes/levels.py`, don't import.

### 4.5 `axes/momentum.py` — Q3 OB + CVD on short TF

```python
def compute_momentum_axis(ob_snapshots, trade_window, ws_s):
    """Return momentum score in [-1, +1].

    Inputs:
      ob_snapshots: L25 snapshots for held side over last 60s, sorted by ts
      trade_window: trade prints over last 60s on held side

    Composite:
      imb_l5  = (sum bid_size 0..4 - sum ask_size 0..4) / total   → [-1, +1]
      cvd_1m  = sum(size * sign(side=='buy'?+1:-1)) / cap
      aggressor_30s = (buy_size_30s - sell_size_30s) / total_30s

    score = 0.4*imb_l5 + 0.3*cvd_1m + 0.3*aggressor_30s

    |score| >= MOMENTUM_MIN_STRENGTH → vote sign(score)
    else                             → vote 0
    """
```

Reuse logic from `strategy_lab/confluence/flow/features.py` — same copy-not-import rule.

### 4.6 `filters/conflict.py` — THE filter

```python
def apply_conflict_filter(trend_vote: int, levels_vote: int, momentum_vote: int):
    """Return (should_fire, signal_dir, reason).

    Cyclops manifesto (verbatim):
      "The new one asks three independent questions and measures how much
       they agree. Trend, Levels, Momentum. If they disagree too much, the
       trade is skipped. That is the entire fix."

    Rules:
      1. Each vote ∈ {-1, 0, +1}
      2. If at least one positive AND at least one negative → conflict, skip
      3. If 2 or more abstentions → not enough info, skip
      4. Otherwise → fire in the direction of the non-zero votes
    """
    pos  = sum(1 for v in (trend_vote, levels_vote, momentum_vote) if v > 0)
    neg  = sum(1 for v in (trend_vote, levels_vote, momentum_vote) if v < 0)
    abst = sum(1 for v in (trend_vote, levels_vote, momentum_vote) if v == 0)

    if pos > 0 and neg > 0:
        return False, None, f"conflict_pos{pos}_neg{neg}"
    if abst >= ABSTAIN_LIMIT:
        return False, None, f"abstention_{abst}"
    direction = "Up" if pos >= 1 else "Down"
    return True, direction, "coherent"
```

Twenty lines of code. The bot lives or dies here.

### 4.7 `filters/hours_guard.py`

```python
def is_trading_hour(ts_utc_seconds: int) -> tuple[bool, str]:
    """Cyclops Day 3: 'Bitcoin moves when institutions move. Weekday hours only.
    Weekends fully off. Bot stays running, only entries blocked.'

    Returns (allowed, reason).
    """
    dt = datetime.fromtimestamp(ts_utc_seconds, tz=timezone.utc)
    if WEEKEND_OFF and dt.weekday() >= 5:
        return False, "weekend"
    hour_frac = dt.hour + dt.minute / 60
    if hour_frac < TRADING_START_UTC:
        return False, "pre_open"
    if hour_frac >= TRADING_STOP_UTC:
        return False, "post_close"
    for lo, hi in PAUSE_WINDOWS_UTC:
        if lo <= hour_frac < hi:
            return False, f"pause_{lo}_{hi}"
    return True, "ok"
```

### 4.8 `filters/blowoff_guard.py` (regime-asymmetric)

```python
def is_blowoff_skip(direction: str, bb_position: str, rsi14: float,
                    mtf_abs: int) -> tuple[bool, str]:
    """Cyclops Day 3 — regime asymmetry, NOT enforced symmetry.

    Pattern: BB touches upper band + RSI >= 60 + |MTF| >= 3
      → strong-trend overbought blowoff
      → on UP entries: vertical exhaustion, hard SKIP
      → on DOWN entries: leave alone (those wins were working)
    """
    blow_conditions = (
        bb_position == "touch_upper" and
        rsi14 >= BLOWOFF_RSI_THRESHOLD and
        mtf_abs >= BLOWOFF_MIN_MTF_ABS
    )
    if not blow_conditions:
        return False, "ok"
    if direction == "Up" and BLOWOFF_GUARD_UP:
        return True, "blowoff_up"
    if direction == "Down" and BLOWOFF_GUARD_DOWN:
        return True, "blowoff_down"
    return False, "ok"
```

### 4.9 `filters/ob_manipulation.py`

```python
def is_ob_manipulated(ob_snapshots_5s: list) -> tuple[bool, str]:
    """Cyclops Day 2: track OB score volatility over a 5s window.
    If score swings too hard → likely a liquidity grab spike, suppress.
    """
    if len(ob_snapshots_5s) < 2:
        return False, "insufficient_data"
    scores = [compute_imbalance_score(s) for s in ob_snapshots_5s]
    span = max(scores) - min(scores)
    if span > OB_VOLATILITY_THRESHOLD:
        return True, f"ob_manipulated_{span:.3f}"
    return False, "ok"
```

### 4.10 `filters/reentry_lock.py`

```python
class ReentryLock:
    """Cyclops Day 1 + Day 2: lock fires RIGHT AFTER ENTRY log,
    BEFORE size/fill checks. Old bug: cooldown set after Kelly,
    Kelly blocked first, 5 entries in 6s into same market.
    """
    def __init__(self):
        self._locks = {}   # condition_id → unlock_ts_us

    def is_locked(self, condition_id, now_us):
        return self._locks.get(condition_id, 0) > now_us

    def lock(self, condition_id, now_us):
        """Call this IMMEDIATELY on entry decision, even if downstream
        rejects the order. The lock protects against pipeline retries."""
        self._locks[condition_id] = now_us + REENTRY_COOLDOWN_SEC * 1_000_000
```

### 4.11 `sizing/fixed.py` (Phase 1)

```python
def fixed_size(balance: float, direction: str, **_) -> float:
    return NOTIONAL_USD
```

### 4.12 `sizing/confidence_scaled.py` (Phase 2)

Wait for Phase 1 results before designing. Tentative: scale linearly with `coherent_vote_count` (1/2/3 axes voting same way). Cap at `MAX_NOTIONAL_USD = 50.0`. Floor at `MIN_NOTIONAL_USD = 10.0`.

**Important — DO NOT add Kelly-with-edge-formula here.** Cyclops deleted that. We're not bringing it back.

### 4.13 `risk/drawdown_manager.py`

```python
class DrawdownManager:
    """Hybrid of his and our pattern:
       - Peak DD halt (per-session peak tracker)
       - Daily loss halt (resets at UTC midnight)
       - Resume on balance recovery, not timer (Cyclops's choice)
    """
    def __init__(self, start_balance: float):
        self.start_balance = start_balance
        self.peak = start_balance
        self.day_start_balance = start_balance
        self.day_start_ts = None
        self._halted_until_recovery_to = None

    def update(self, current_balance: float, now_ts: int):
        self.peak = max(self.peak, current_balance)
        # Roll day at UTC midnight
        day = now_ts // 86400
        if self.day_start_ts is None or day != self.day_start_ts:
            self.day_start_ts = day
            self.day_start_balance = current_balance

    def is_halted(self, current_balance: float) -> tuple[bool, str]:
        if self._halted_until_recovery_to is not None:
            if current_balance >= self._halted_until_recovery_to:
                self._halted_until_recovery_to = None
            else:
                return True, "drawdown_recovery_pending"

        dd_pct = (self.peak - current_balance) / self.peak * 100
        if dd_pct >= MAX_DRAWDOWN_PCT:
            recovery_to = self.peak * (1 - RECOVERY_RESUME_FACTOR * MAX_DRAWDOWN_PCT / 100)
            self._halted_until_recovery_to = recovery_to
            return True, f"max_drawdown_{dd_pct:.2f}"

        day_loss_pct = (self.day_start_balance - current_balance) / self.day_start_balance * 100
        if day_loss_pct >= DAILY_LOSS_LIMIT_PCT:
            return True, f"daily_loss_{day_loss_pct:.2f}"

        return False, "ok"
```

### 4.14 `backtest/runner.py`

The single integration point. Pseudo:

```python
def run_backtest(asset: str, tf: str, period: tuple):
    res = load_btc_universe()
    res = res[(res.asset == asset) & (res.timeframe == tf)]
    res = filter_period(res, period)

    end_us_1h, prices_1h = load_klines_asof(asset.upper(), "binance-spot-ws", "60MIN")
    # Note: we may need to resample 1MIN klines to 1h/15m/5m client-side
    # since canonical only stores 1MIN — see Open Q #3.

    risk = DrawdownManager(start_balance=100.0)
    reentry = ReentryLock()
    balance = 100.0
    trades = []

    for _, row in res.iterrows():
        ws_s = int(row.ws_s)
        now_us = (ws_s + 120) * 1_000_000
        risk.update(balance, ws_s)

        if risk.is_halted(balance)[0]:
            continue
        if not is_trading_hour(ws_s + 120)[0]:
            continue
        if reentry.is_locked(row.condition_id, now_us):
            continue

        # Compute three axes
        trend_vote    = compute_trend_axis(...)
        levels_vote, p_up = compute_levels_axis(...)
        momentum_vote, score = compute_momentum_axis(...)

        should_fire, direction, reason = apply_conflict_filter(
            trend_vote, levels_vote, momentum_vote
        )
        if not should_fire:
            continue

        # Pre-flight guards (compute features needed)
        bb_pos, rsi14 = compute_bb_rsi(row, klines_5m)
        if is_blowoff_skip(direction, bb_pos, rsi14, abs(trend_vote))[0]:
            continue

        ob5s = ob_snapshots_for_window(row.slug, direction, now_us - 5e6, now_us)
        if is_ob_manipulated(ob5s)[0]:
            continue

        # LOCK first, then fill
        reentry.lock(row.condition_id, now_us)

        # Fill at L25
        book = tier1_entries_lookup(row.slug, direction)
        stake = fixed_size(balance, direction)
        vwap_e, shares_e, usd_e, ... = book_walk_fill(book.ask_p, book.ask_s, stake)
        if not_filled(...):
            continue

        # Settle vs chainlink
        outcome = row.outcome   # already chainlink-derived in canonical
        won = (direction == outcome)
        pnl = settle(won, shares_e, usd_e, FEE_RATE)
        balance += pnl

        trades.append({
            "ws_s": ws_s, "slug": row.slug, "direction": direction,
            "trend_vote": trend_vote, "levels_vote": levels_vote, "momentum_vote": momentum_vote,
            "stake": usd_e, "vwap_e": vwap_e, "won": won, "pnl": pnl,
        })

    return pd.DataFrame(trades), balance
```

### 4.15 `validate/permutation.py`, `walkforward.py`, `bootstrap.py`

Three independent files. Each takes the per-trade DataFrame and returns a verdict dict. Reuse logic from `strategy_lab/meta_classifier/extended_backtest_with_robustness.permutation_test` (copy in, don't import).

### 4.16 `telemetry/events.py`

Event schema for paper deploy. Mirrors VPS3 `trading.events` shape so the same audit queries work.

```python
def make_signal_event(*, slug, ws_s, signal_dir, trend_vote, levels_vote, momentum_vote,
                      reason, stake_usd, ...):
    return {
        "kind": "poly_updown_cyclops_signal",
        "at": iso8601(now()),
        "data": {
            "sleeve_id": "cyclops_v1",
            "slug": slug,
            "ws_s": ws_s,
            "signal_dir": signal_dir,
            "trend_vote": trend_vote,
            "levels_vote": levels_vote,
            "momentum_vote": momentum_vote,
            "reason": reason,
            "stake_usd": stake_usd,
            # ... full feature dump
        }
    }
```

---

## 5. Data layer — what canonical provides

| Need | Source | Loader call |
|---|---|---|
| Universe (chainlink-resolved) | `data/v4/canonical/resolutions_from_rtds.parquet` | `load_resolutions(assets=["BTC"], timeframes=["5m"])` |
| Binance 1MIN klines (signal source) | `klines_1m.parquet` | `load_klines_asof("BTC", "binance-spot-ws", "1MIN")` |
| Chainlink oracle (outcome ground truth) | `chainlink_rtds.parquet` | `load_chainlink_asof("BTC")` |
| Entry book L25 at ws+120 | `tier1_entries_at_t120/btc.parquet` | `load_tier1_entries("btc")` |
| Full L25 OB stream (for momentum + OB manipulation) | `orderbook_l25/btc.parquet` | `load_orderbook_l25_streaming("btc", slugs=…)` |
| Trades for CVD/aggressor | `trades_polymarket/btc.parquet` ⚠ stale May 6 | `load_trades("btc", …)` |

Window for backtest: `2026-04-24 → 2026-05-15` (21 days, 5,887 BTC 5m markets in universe).

### Open Q on data resolution

We need 1h and 15m klines for Q1 / Q2. Canonical stores 1MIN only. Two options:
- (a) Resample 1MIN → 15m / 1h client-side in `data_io.py` (clean, slow)
- (b) Cache resampled parquets in `cyclops/_cache/` (fast, dependency)

**Pick (a) for Phase 1.** Performance optimization only if backtest is intolerably slow.

---

## 6. Backtest harness — reuse plan

| Component | Source | How |
|---|---|---|
| Book walk fill | `strategy_lab/book_walk.py:book_walk_fill` | direct import |
| Equity curve stats | `strategy_lab/polymarket_stats.py:equity_curve_stats` | direct import |
| Permutation test | `strategy_lab/meta_classifier/extended_backtest_with_robustness.py:permutation_test` | **copy into** `cyclops/validate/permutation.py` (greenfield rule) |
| Walkforward pattern | same file, `walkforward()` | copy + simplify |
| asof_strict | `data/v4/canonical/load.py:asof_strict` | direct import via `data_io.py` |

Nothing else gets imported from the existing strategy tree.

---

## 7. Validation gates

Each phase ships only after passing this battery on canonical 21d. All gates run on PER-TRADE DataFrames.

| Gate | Test | Pass | If fail |
|---|---|---|---|
| **G0 Smoke** | Backtest runs end-to-end, produces ≥10 trades | n ≥ 10 | engine bug |
| **G1 Edge sign** | Per-trade mean PnL > 0 on full 21d universe | `mean(pnl) > 0` | strategy has no edge, halt |
| **G2 Walk-forward** | Rolling 5d train / 2d test windows | ≥ 6 of 8 windows positive mean | overfit |
| **G3 Permutation** | 1000-draw sign-flip null distribution | p_value < 0.05 | not statistically distinguishable from noise |
| **G4 Bootstrap CI** | 10k bootstrap of mean PnL | 95% CI lower bound > 0 | small-n positive that won't survive |
| **G5 Stress: spread** | Re-run with SPREAD_FILTER tightened by 50% | mean PnL stays positive | over-relies on wide-spread markets |
| **G6 Sanity vs production** | Compare per-slug PnL against any shadow data covering overlap window | max diff < $0.10/trade | engine drift |

**Promotion criteria to live:**
- n ≥ 80 paper trades
- ≥ 5 observed losses (so G3 is informative)
- All gates G1-G5 pass
- Live hit rate ≥ 88% over rolling 20 trades (1pp safety above breakeven at $4 mean win × 0.86 = $25)
- No risk pause triggered in last 7 days

---

## 8. Phased roadmap

Each phase ships independently. No phase depends on a feature from a later phase.

| Phase | Deliverable | Days | Validation |
|---|---|---:|---|
| **P0 Skeleton** | `cyclops/` package skeleton, `conventions.py`, `data_io.py`, `tests/test_conventions.py`, `tests/test_ws_s_inherited.py` | 0.5 | tests pass |
| **P1 Three axes (no filter)** | `axes/{trend,levels,momentum}.py` with vote functions; `tests/test_axes.py` covers basic cases | 2 | unit tests; per-axis distribution stats on 21d universe sane (each axis abstains ~30%, votes ±1 ~35% each) |
| **P2 Conflict filter + backtest** | `filters/conflict.py`; `backtest/runner.py` with HOLD policy + fixed $25; first backtest result | 1.5 | **G0 + G1** on 21d BTC 5m |
| **P3 Pre-flight guards** | `filters/{hours_guard,reentry_lock,ob_manipulation,blowoff_guard}.py` | 2 | per-guard ablation: does enabling each guard improve PnL? |
| **P4 Risk manager** | `risk/drawdown_manager.py`; wire into runner | 1 | runner shows risk-pause events; PnL series respects pause |
| **P5 Validation battery** | `validate/{permutation,walkforward,bootstrap}.py` | 1 | all three return valid JSON reports |
| **P6 Decision: ship or iterate** | Look at G1-G5 outputs | 0.5 | if G1-G5 all pass → start paper-deploy spec for TV agent. If G1 fails → **STOP**, do not iterate features. The strategy has no edge. |
| **P7 (conditional) Confidence sizing** | `sizing/confidence_scaled.py` | 1 | re-run battery |
| **P8 (conditional) Live deploy spec** | TV agent spec mirroring earlier `TV_AGENT_SPEC_CONFLUENCE_SILVER_V1.md` pattern | 1 | spec reviewed + handed off |

**Total to first verdict: 7.5 days.** If verdict negative, STOP — don't try to save it.

The biggest discipline ask: P6 is a real decision gate. The whole point of copying Cyclops is to NOT iterate signal complexity. If the conflict filter on canonical BTC 5m doesn't have edge after P5, that IS the answer.

---

## 9. Critical conventions (inherited; reference only)

All canonical conventions apply. Full text: `NEXT_SESSION_START_HERE.md` §"Critical conventions agents MUST respect". One-line reminders:

1. UTC microseconds for all `*_us` timestamps. Seconds-suffix `*_s` also UTC. Never localize.
2. `ws_s = slug_suffix - window_s` (PREVIOUS slot's start). NOT the slug suffix.
3. Outcome from chainlink RTDS. Never from binance close.
4. Binance is the SIGNAL source (`source='binance-spot-ws'`).
5. `asof_strict` for causal lookups — end-time-indexed.
6. L25 walk via `book_walk_fill(ask_p, ask_s, $25)` is the production fill.
7. Fee = 2% on profit only (winning leg).

Run `py -3 -X utf8 data/v4/canonical/_test_ws_s.py` BEFORE any backtest. Must print `=== ALL CHECKS PASSED ===`.

---

## 10. Env-var contract (TV-agent compatible)

When P8 (live deploy) lands, these env vars control the bot. Same naming pattern as the operator's `CONFLUENCE_*` vars so the rail framework recognizes them.

```bash
# Master enable
CYCLOPS_ENABLED=true

# Per-cell (start BTC 5m only)
CYCLOPS_BTC_5M_ENABLED=true
CYCLOPS_BTC_15M_ENABLED=false
CYCLOPS_ETH_5M_ENABLED=false
# (others stay false until each clears its own validation)

# Axis thresholds
CYCLOPS_TREND_MIN_ABS=1
CYCLOPS_LEVELS_MIN_CERTAINTY=0.15
CYCLOPS_MOMENTUM_MIN_STRENGTH=0.15

# Conflict filter
CYCLOPS_ABSTAIN_LIMIT=2

# Sizing
CYCLOPS_NOTIONAL_USD=25.0
CYCLOPS_SIZING_MODE=fixed      # fixed | confidence_scaled

# Risk
CYCLOPS_RISK_PAUSE_MODE=hard   # hard | soft | off
CYCLOPS_MAX_DRAWDOWN_PCT=5.0
CYCLOPS_DAILY_LOSS_LIMIT_PCT=2.0
CYCLOPS_RECOVERY_RESUME_FACTOR=0.5

# Cooldowns
CYCLOPS_REENTRY_COOLDOWN_SEC=30

# OB manipulation
CYCLOPS_OB_VOLATILITY_THRESHOLD=0.5
CYCLOPS_OB_VOLATILITY_WINDOW_S=5

# Blowoff (regime-asymmetric)
CYCLOPS_BLOWOFF_GUARD_ENABLED=true
CYCLOPS_BLOWOFF_GUARD_UP=true
CYCLOPS_BLOWOFF_GUARD_DOWN=false
CYCLOPS_BLOWOFF_RSI_THRESHOLD=60
CYCLOPS_BLOWOFF_MIN_MTF=3

# Trading hours
CYCLOPS_TRADING_START_UTC=13.0
CYCLOPS_TRADING_STOP_UTC=21.0
CYCLOPS_PAUSE_WINDOWS_UTC=                # comma-list of LO-HI pairs
CYCLOPS_WEEKEND_OFF=true

# VWAP
CYCLOPS_VWAP_WINDOW_BARS=24
```

Naming: prefix `CYCLOPS_` for bot-internal. Sleeve ID: `poly_updown_btc_5m_cyclops_v1`.

---

## 11. Telemetry contract

Event kinds (mirror `trading.events` shape):

| Kind | When | Required `data` fields |
|---|---|---|
| `poly_updown_cyclops_signal` | every evaluation (fire OR skip) | sleeve_id, slug, ws_s, signal_dir (or null), trend_vote, levels_vote, momentum_vote, conflict_reason, guards_fired (list), stake_usd, vwap_e, mode (paper/live) |
| `poly_updown_cyclops_skip` | every skip | sleeve_id, slug, ws_s, skip_reason, skip_layer (conflict / hours / blowoff / ob_manipulation / reentry / risk), votes |
| `poly_updown_cyclops_resolution` | per resolved trade | sleeve_id, slug, pnl_usd, hit (bool), entry_price, exit_price, stake_usd, mode |
| `poly_updown_cyclops_risk_pause` | when DrawdownManager halts | trigger (max_drawdown / daily_loss), value_pct, threshold_pct, recovery_target_balance, mode |
| `poly_updown_cyclops_error` | unexpected exception | error_type, error_msg, slug, stack_trace (truncated 500 chars) |

KPI queries are computed live from `trading.events`. **No session-state cache files** (per Cyclops May 7 article fix #4).

---

## 12. Reproduction recipe

```bash
cd "C:\Users\alexandre bandarra\Desktop\global"

# Step 0 — Verify environment
py -3 -X utf8 data/v4/canonical/_test_ws_s.py
# Must print: === ALL CHECKS PASSED ===

# Step 1 — Bootstrap package
mkdir -p strategy_lab/cyclops/{axes,filters,sizing,risk,backtest,validate,telemetry,tests,_results}

# Step 2 — Drop the P0 files (operator or agent writes per §3)
# ... edit strategy_lab/cyclops/conventions.py
# ... edit strategy_lab/cyclops/data_io.py
# ... etc.

# Step 3 — Run skeleton tests
py -3 -X utf8 -m pytest strategy_lab/cyclops/tests/test_conventions.py
py -3 -X utf8 -m pytest strategy_lab/cyclops/tests/test_ws_s_inherited.py

# Step 4 — Phase-by-phase
py -3 -X utf8 -m pytest strategy_lab/cyclops/tests/test_axes.py
py -3 -X utf8 -m pytest strategy_lab/cyclops/tests/test_conflict_filter.py

# Step 5 — First backtest (after P2)
py -3 -X utf8 -m strategy_lab.cyclops.backtest.runner \
    --asset btc --tf 5m --start 2026-04-24 --end 2026-05-15 \
    --out strategy_lab/cyclops/_results/p2_first_backtest.csv

# Step 6 — Validation battery (after P5)
py -3 -X utf8 -m strategy_lab.cyclops.validate.permutation \
    --trades strategy_lab/cyclops/_results/p2_first_backtest.csv
py -3 -X utf8 -m strategy_lab.cyclops.validate.walkforward ...
py -3 -X utf8 -m strategy_lab.cyclops.validate.bootstrap ...
```

---

## 13. Risks, open questions, kill criteria

### Risks

| Risk | Mitigation |
|---|---|
| Conflict filter cuts so many trades that n < 80 over 21d → can't validate | Loosen LEVELS_MIN_CERTAINTY / MOMENTUM_MIN_STRENGTH on a 14d hold-out, but tune ONLY on training period, never test |
| Q1 trend axis requires 25h of 1h klines but canonical's earliest BTC 5m market is Apr 24 + needs lookback | Use binance-vision archive bars for pre-Apr 24 history. Already in canonical. |
| `trades_polymarket` STALE through May 6 → momentum axis broken for post-May-6 fires | Either (a) limit backtest to Apr 24 - May 6 (n drops to ~1500 instead of 2900) or (b) compute momentum from OB only (drop CVD term) for post-May-6 segment |
| Levels axis underfires (few pivots on 15m in 5d window) | Lower the swing-confirmation K from 5 to 3 |
| Blowoff guard kills good trades on real uptrends | Operator-disable via env: `CYCLOPS_BLOWOFF_GUARD_ENABLED=false`. Validate in P3 ablation. |

### Open questions

1. **Q1 timeframes** — Cyclops uses 5m + 15m + 1h. We could try 1m + 5m + 15m for binary 5m markets (different time horizon than his 15min markets). Start with his, sensitivity-test in P2.
2. **`TRADING_START_UTC=13.0`** is a placeholder. We don't know the actual best hours for Polymarket BTC binary. Run a per-hour PnL split BEFORE setting this var, then back-test the gate.
3. **Resampling 1MIN → 15m / 1h client-side** vs caching resampled parquets — start with (a), measure.
4. **Per-asset axis weights** — Cyclops trains on BTC only. We extend to ETH/SOL later; expect per-asset thresholds. Phase 1: BTC only.

### Kill criteria — when to stop the project

This is the most important section.

| Trigger | Action |
|---|---|
| P2 G1: per-trade mean PnL ≤ 0 on 21d BTC 5m | **STOP.** Conflict-filter idea doesn't replicate on our universe. Don't iterate. |
| P5 G3: permutation p > 0.10 even on positive-edge cells | **STOP.** Not statistically distinguishable. |
| P6 verdict: 1-2 gates fail but 3+ pass | **STOP signal-side work; investigate WHY.** Probably a calibration issue, not a strategy issue. Do not add features. |
| Any phase: fire rate drops below 3% (≤90 trades / 21d) | Tighten thresholds, do not loosen. If fire rate stays below 3% even after relaxing, the strategy doesn't work for this universe. |

The whole point is to NOT iterate complexity. If the simple version fails, stop.

---

## 14. References

### Architectural source

- `strategy_lab/reports/CYCLOPS_ARCHITECTURE_DEEP_DIVE_2026_05_16.md` §§19-22 — definitive Q1/Q2/Q3 + conflict-filter description, including operator-pasted Day 1/2/3 cheat-code log and manifesto quotes.

### Earlier related work (read for context, do NOT port directly)

- `strategy_lab/reports/CYCLOPS_UPDATE_COMPARISON_2026_05_07.md` — his May 7 article (4 infra fixes that took WR 55%→68% on same signal); risk-pause + tier-flow + skip-on-exception + clean-startup mandates. The infra discipline parts apply to OUR ops too.
- `strategy_lab/reports/MOMO_FULL_UNIVERSE_2026_05_16.md` — proof our existing momo strategy is unprofitable on canonical 21d universe. THIS is why we're starting fresh.
- `strategy_lab/reports/SILVER_VALIDATION_FINAL_2026_05_07.md` — what an honest validation looks like (sample-underpowered, mechanically can't fail-stop, 2 of 5 gates pass). Same standard applies here.

### Data

- `data/v4/canonical/load.py` — entry point; ALL data goes through here
- `data/v4/canonical/README.md` — schema + conventions
- `NEXT_SESSION_START_HERE.md` — top-level pointer doc

### Engines we may use

- `strategy_lab/book_walk.py:book_walk_fill` — fill model
- `strategy_lab/polymarket_stats.py:equity_curve_stats` — sharpe / max DD
- `strategy_lab/meta_classifier/extended_backtest_with_robustness.py:permutation_test` — perm test (copy, not import)

### His articles (X / x-thread.org)

- Apr 21: `x.com/Gustafssonkotte/status/2046690018236735644` — Architecture, Brain, Risk Management
- Apr 27: `x.com/Gustafssonkotte/status/2048755838358061116` — Algo Trading Bot
- May 07: `x.com/Gustafssonkotte/status/2052286284937220240` — WR 55% → 68% via infra
- May 11: `x.com/Gustafssonkotte/status/2053758338974838857` — Deleted half my bot's code (THE conflict-filter article)
- Plus Day 1/2/3 daily updates (operator-pasted; preserved in deep-dive §19)

Live signals: `t.me/cyclops_signals`

---

## 15. Recommended starting prompt for next session

```
Read this first: strategy_lab/reports/CYCLOPS_CLONE_SPEC_2026_05_16.md
Then read its source: strategy_lab/reports/CYCLOPS_ARCHITECTURE_DEEP_DIVE_2026_05_16.md
                       §§19-22 specifically.

The goal is to build strategy_lab/cyclops/ as a greenfield Cyclops-clone
following the spec. Start with Phase P0 (skeleton + conventions + ws_s test).

Critical:
- ws_s = slug_suffix - window_s (NOT slug suffix); 25-40pp hit-rate inflation bug
- chainlink for outcomes, binance for signals
- 2% fee on profit only, $25 notional, L25 book walk
- DO NOT add Kelly-with-edge, fair_probability lookup, voter, or tier-table
  (Cyclops deleted those May 11 — if you bring them back you're undoing his fix)
- Each phase has a kill criterion. If P2 G1 fails, STOP.

First action: run py -3 -X utf8 data/v4/canonical/_test_ws_s.py
              and confirm '=== ALL CHECKS PASSED ==='.
              Then create the package skeleton per spec §3.
```

---

## 16. What to expect

Honest forecast based on `MOMO_FULL_UNIVERSE_2026_05_16.md` and `SILVER_VALIDATION_FINAL_2026_05_07.md`:

- **Most likely outcome (60%):** P2 G1 fails. Conflict filter cuts fire rate, but the surviving trades don't have positive expectancy. Polymarket-binary 5m markets are too short for trend+levels alignment to provide useful directional information. Cyclops's "60% WR Day 1" replicates as ~48-52% WR on our larger sample — same regression we saw with `eth_15m_momo_HOLD` (+$6.78/tr at n=20 → negative at n=415).

- **Moderate outcome (30%):** P2 G1 passes weakly (small positive mean PnL), but G3 perm test p > 0.05 — not statistically distinguishable. STOP per kill criterion.

- **Best case (10%):** All gates pass on 21d. Move to P6 paper-deploy. Even then, treat as paper-only until n≥80 live trades.

Either way, the value of this build is the same: **rigorous test of a specific architectural claim ("conflict filter alone gets you to 60%+ WR") on our universe.** If it doesn't replicate, we've quantified another rejected hypothesis and we know exactly why. If it does, we have a new sleeve that's structurally different from what we have.

The cost: ~8 working days for first verdict. Acceptable.

---

*End of spec. Generated 2026-05-16. Next session: execute P0 per §§3, 4.1-4.2, 12.*
