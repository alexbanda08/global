# Cyclops X1 — Shadow-Mode Deployment Spec

**Sleeve ID:** `poly_updown_btc_5m_cyclops_v1_x1`
**Target venue:** Polymarket BTC up-down 5m binary markets
**Mode:** Paper / shadow only until promotion criteria met
**Spec date:** 2026-05-17
**Source backtest:** `cyclops/_results/p5_full_depth_p3.csv` filtered by sleeve-active set; validated under real Polymarket fees in `cyclops/_results/_real_fees_rerun.py`.

---

## 0. One-paragraph summary

X1 fires on a Polymarket BTC 5m binary market only when:
(1) the Cyclops 3-axis "S7" filter says Up or Down with **trend+levels coherent AND momentum abstaining**,
(2) the level-0 ask of the chosen direction is ≥ $0.30, and
(3) **at least one VPS3-tracked BTC 5m sleeve already fired on the same slug** (direction agreement NOT required — sleeve presence is a market-coherence filter, not a directional vote).
Stake is fixed $25 walked through L25 ask. Settlement uses chainlink-derived outcome and the real Polymarket fee curve. On 21 days of canonical data this configuration produced **n=36 fires, WR 80.56%, +13.97pp edge over real breakeven, +$8.79 PnL @ $1 stake (+$219.74 @ $25 stake), G3 p=0.002, G4 95% CI lower bound +$0.0042/$1**.

---

## 1. Trigger logic (exact decision pipeline)

A fire requires ALL nine checks below pass in this order. Skip any earlier check → no fire, log skip event.

### 1.1 Market-eligibility gate
```
asset == "BTC"
timeframe == "5m"
market resolved (or will be resolved) via Chainlink (chainlink RTDS oracle)
slug format: btc-updown-5m-<slot_start_unix_seconds>
```

### 1.2 Risk-manager gate (P4 layer)
```
DrawdownManager.update(balance, ws_s)
not DrawdownManager.is_halted(balance)
```
Drawdown manager state — see §6.

### 1.3 Anchor computation
```
ws_s    = slug_suffix - 300            # PREVIOUS slot's start, NOT slot_start
fire_us = (ws_s + 120) × 1_000_000     # production fire moment (microseconds)
```
**CRITICAL:** anchoring on `slot_start` instead of `ws_s` inflates backtest hit rate by 25–40pp — see `SESSION_HANDOFF_2026_05_10_WS_S_CONVENTION.md`.

### 1.4 Trend axis (Q1) — multi-timeframe alignment

For each timeframe in (1h, 15m, 5m):
```
1. Slice last K bars whose end_us ≤ fire_us
   K_1h  = 25     (25h of context)
   K_15m = 100    (25h of context)
   K_5m  = 288    (24h of context)
2. Closed-form OLS slope on (bar_index, close) → slope
3. Normalize: frac = slope × K / mean(close)
4. eps_frac = 0.005 (50 bps over the window)
   vote_tf = +1 if frac >  eps_frac
   vote_tf = -1 if frac < -eps_frac
   vote_tf =  0 otherwise
alignment_int = vote_1h + vote_15m + vote_5m         ∈ [-3, +3]
v_trend       = +1 if alignment_int ≥ 1, -1 if ≤ -1, else 0
```
Bars must be **causal** (end_us ≤ fire_us). Use `np.searchsorted(end_us, fire_us, side='right')`.

Bars come from binance 1MIN klines (source = `binance-spot-ws`), resampled client-side. Drop any partial bucket at the leading edge (no look-ahead from the active bar).

### 1.5 Levels axis (Q2) — 15m swing-pivot S/R

```
1. Slice 15m closes whose end_us in [fire_us - 5 days, fire_us]
   (need ≥ 11 bars for K_CONFIRM=5)
2. Find swing-high pivots: high[i] strictly > high[i-K..i-1] AND > high[i+1..i+K]
3. Find swing-low pivots:  low[i] strictly < low[i-K..i-1] AND < low[i+1..i+K]
4. current_px = asof_strict(end_us_1m, close_1m, fire_us)
   nearest_resistance = min(pivot_high for pivot_high > current_px), else NaN
   nearest_support    = max(pivot_low  for pivot_low  < current_px), else NaN
   if any side missing → p_up = 0.50 (abstain)
   else:
     dist_above = nearest_resistance - current_px
     dist_below = current_px - nearest_support
     p_up = 0.50 + 0.40 × (dist_above - dist_below) / (dist_above + dist_below)
5. v_levels = +1 if p_up > 0.65; -1 if p_up < 0.35; else 0
```
LEVELS_MIN_CERTAINTY = 0.15. LEVELS_SCALE = 0.40. LEVELS_LOOKBACK_DAYS = 5. K_CONFIRM = 5.

### 1.6 Momentum axis (Q3) — full-depth OB + trades

```
1. Slice Polymarket L25 OB snapshots for (slug, outcome="Up") in
   [fire_us - 60s, fire_us]
   (subsample to 1Hz if raw stream is dense)
2. imb_l5 = (sum bid_size[0..4] − sum ask_size[0..4]) /
            (sum bid_size[0..4] + sum ask_size[0..4])
            at the LATEST snapshot ≤ fire_us, clipped to [-1, +1]
3. Slice Polymarket trades for (slug, outcome="Up") in
   [fire_us - 60s, fire_us]:
     side_sign = +1 for "buy", -1 for "sell"
     cvd_usd  = Σ (size_usd × side_sign)
     cvd_norm = clip(cvd_usd / 25_000, -1, +1)
4. Slice trades for (slug, "Up") in [fire_us - 30s, fire_us]:
     buy_30   = Σ size_usd where side=="buy"
     sell_30  = Σ size_usd where side=="sell"
     aggressor = clip((buy_30 − sell_30) / (buy_30 + sell_30), -1, +1)
                 or 0 if total volume == 0
5. score = 0.40 × imb_l5 + 0.30 × cvd_norm + 0.30 × aggressor
          clipped to [-1, +1]
6. v_momentum = +1 if score ≥ 0.15; -1 if ≤ -0.15; else 0
```
MOMENTUM_MIN_STRENGTH = 0.15. MOMENTUM_WINDOW_S = 60. MOMENTUM_AGGRESSOR_WINDOW_S = 30. MOMENTUM_CVD_CAP_USD = 25_000.

### 1.7 Conflict filter — `require_momentum_abstain=True` mode

```
if v_momentum != 0:
    skip  reason="momentum_engaged"
elif v_trend > 0 and v_levels > 0:
    direction = "Up"     reason="coherent_2of2"
elif v_trend < 0 and v_levels < 0:
    direction = "Down"   reason="coherent_2of2"
elif v_trend == 0 or v_levels == 0:
    skip  reason="abstention_X_of_2"
else:
    skip  reason="conflict_pos1_neg1"
```
The momentum axis is computed but used **only as a veto** — it must abstain. This is the structural finding from P2/P3 forensics: when momentum agrees with trend+levels, the trade resolves AGAINST the consensus (3-of-3 coherent is 41% WR; 2-of-2 with momentum silent is 53% WR on degraded momentum, 62% on full-depth).

### 1.8 Vwap pre-flight gate (X1 part 1)

```
key = (slug, direction)
t1_row = tier1_entries.lookup(key)
ask_price_l0 = t1_row.ask_price_0
if ask_price_l0 < 0.30:
    skip  reason=f"vwap_guard_{ask_price_l0:.3f}<0.30"
```
This removes the doom-zone where consensus has already shifted hard against `direction` — see P2 forensics (vwap < 0.30 bucket: 320 trades, 11.6% WR, −$8.90/trade).

### 1.9 Sleeve-active filter (the X1 piece — NEW for shadow deploy)

```
# Maintain a 30-day rolling cache of slugs where any BTC 5m VPS3 sleeve
# resolved a trade (via subscription to `trading.events`).
sleeve_active_slugs = set of slug values from rows where
    kind == "poly_updown_resolution"
    AND sleeve_id matches "poly_updown_btc_5m_*"
    AND at >= now - 30 days

if slug not in sleeve_active_slugs:
    skip  reason="no_sleeve_activity"
```
Direction-of-other-sleeves is irrelevant. The forensic finding (cyclops/_results/_sleeve_presence_audit.py): on Cyclops S7 slugs that ALSO had ≥1 BTC 5m sleeve fire, WR jumps 58.9% → 80.6% with +15.56pp real-fee edge. **Mechanism hypothesis:** sleeve activity is a proxy for "market structure clear enough for multiple independent strategies to fire" — that coherent regime is where Cyclops's filter has its real edge.

### 1.10 Fire — L25 walk + record

```
ask_p = [t1_row.ask_price_0 .. ask_price_24]
ask_s = [t1_row.ask_size_0  .. ask_size_24]
stake_usd = 25.00                           # fixed
vwap_e, shares_e, usd_e, hit_levels, underfilled
    = book_walk_fill(ask_p, ask_s, stake_usd, side="buy")
if underfilled or usd_e ≤ 0:
    skip  reason="no_fill"
reentry_lock.lock(slug, fire_us)             # immediate; before any retry
publish poly_updown_cyclops_signal event
```

### 1.11 Settlement (when chainlink resolution arrives)

```
fee_per_share = 0.07 × vwap_e × (1.0 − vwap_e)
fee_total_usd = shares_e × fee_per_share
won = (direction == outcome_from_chainlink)
if won:
    payout_usd = shares_e × 1.00
    pnl_usd    = payout_usd − usd_e − fee_total_usd
else:
    pnl_usd    = -usd_e − fee_total_usd
publish poly_updown_cyclops_resolution event
update DrawdownManager(balance + pnl_usd)
```
**Real Polymarket fee model** — NOT the legacy 2%-on-profit shortcut. Fee charged on BOTH legs (win and loss). See `strategy_lab/fees.py` for the reference implementation (`poly_taker_fee_per_share`, `long_payoff_after_fees`).

---

## 2. Hard constants (config)

| Constant | Value | Source |
|---|---:|---|
| `CYCLOPS_TREND_EPS_FRAC` | **0.005** | window-fraction threshold |
| `CYCLOPS_TREND_MIN_ABS` | **1** | |alignment| ≥ 1 to vote |
| `CYCLOPS_TREND_K_1H` | 25 | |
| `CYCLOPS_TREND_K_15M` | 100 | |
| `CYCLOPS_TREND_K_5M` | 288 | |
| `CYCLOPS_LEVELS_MIN_CERTAINTY` | **0.15** | |p_up - 0.5| ≥ 0.15 |
| `CYCLOPS_LEVELS_LOOKBACK_DAYS` | 5 | 15m pivot scan window |
| `CYCLOPS_LEVELS_K_CONFIRM` | 5 | swing-bar confirmation |
| `CYCLOPS_LEVELS_SCALE` | 0.40 | p_up scaling factor |
| `CYCLOPS_MOMENTUM_MIN_STRENGTH` | **0.15** | |score| ≥ 0.15 |
| `CYCLOPS_MOMENTUM_W_IMBALANCE_L5` | 0.40 | weight |
| `CYCLOPS_MOMENTUM_W_CVD_1M` | 0.30 | weight |
| `CYCLOPS_MOMENTUM_W_AGGRESSOR_30S` | 0.30 | weight |
| `CYCLOPS_MOMENTUM_WINDOW_S` | 60 | CVD lookback |
| `CYCLOPS_MOMENTUM_AGGRESSOR_WINDOW_S` | 30 | aggressor lookback |
| `CYCLOPS_MOMENTUM_CVD_CAP_USD` | 25_000.0 | normaliser |
| `CYCLOPS_ABSTAIN_LIMIT` | 2 | (not used in 2of2 mode) |
| `CYCLOPS_REQUIRE_MOM_ABSTAIN` | **true** | the X1 mode flag |
| `CYCLOPS_VWAP_MIN` | **0.30** | level-0 ask floor |
| `CYCLOPS_SLEEVE_ACTIVE_REQUIRED` | **true** | the X1 mode flag |
| `CYCLOPS_SLEEVE_LOOKBACK_DAYS` | 30 | trading_events rolling window |
| `CYCLOPS_NOTIONAL_USD` | 25.00 | |
| `CYCLOPS_FEE_MODEL` | "pmxt_real" | NOT "legacy_2pct" |
| `CYCLOPS_FEE_RATE` | 0.07 | crypto markets, 700 bps |
| `CYCLOPS_MAX_DRAWDOWN_PCT` | 5.0 | |
| `CYCLOPS_DAILY_LOSS_LIMIT_PCT` | 2.0 | |
| `CYCLOPS_RECOVERY_RESUME_FACTOR` | 0.5 | |
| `CYCLOPS_REENTRY_COOLDOWN_SEC` | 30 | |
| `CYCLOPS_START_BALANCE` | 10_000.00 | recommended bankroll |

The bold rows are the X1-specific tunables and must NOT be relaxed without re-running the validation battery.

---

## 3. Data dependencies (subscriptions)

| Feed | Source | Refresh rate | Used in |
|---|---|---|---|
| `klines_1m` (BTC, binance-spot-ws) | VPS3 binance collector | 1MIN | trend, levels (resampled to 5m/15m/1h), current_px lookup |
| `orderbook_l25` (BTC Polymarket) | VPS2 polymarket collector | sub-second (1Hz subsample OK) | momentum imb_l5, ob_manipulation (if wired) |
| `trades_polymarket` (BTC) | VPS2 polymarket collector | event-stream | momentum cvd_norm + aggressor |
| `tier1_entries_at_t120` (BTC) | derived from L25 stream | per market | fill price + L25 ask walk |
| `chainlink_rtds` (BTC) | VPS3 chainlink oracle | 1Hz | outcome ground truth |
| `trading.events` (production) | VPS3 | per fire | **sleeve_active filter** + DrawdownManager events |

All timestamps in **UTC microseconds**. Outcomes must come from Chainlink, never derived from binance close (see CLAUDE.md).

### Latency budget

The fire happens at `ws_s + 120s`. Compute budget from kline-1MIN arrival to L25 walk submission:
- 1MIN kline arrives ~1s after its bar closes → roughly `ws_s + 60s` for the last input bar
- Momentum needs OB + trades up to `fire_us` (must observe through `ws_s + 119s`)
- Total compute window: ~1 second
- All inputs already in memory if the controller is steadily running

---

## 4. Module layout (mapping to existing cyclops package)

The Python implementation is already in `cyclops/`. The shadow-mode controller wraps these calls.

```
cyclops/
├── conventions.py                          # all thresholds above
├── data_io.py                              # canonical loaders + resample + signal_streams
├── axes/
│   ├── trend.py        compute_trend_axis() + trend_vote()
│   ├── levels.py       compute_levels_p_up() + levels_vote() + find_pivots()
│   └── momentum.py     compute_momentum_score() + momentum_vote()
├── filters/
│   ├── conflict.py     apply_conflict_filter(require_momentum_abstain=True)
│   ├── vwap_guard.py   is_vwap_too_low(ask_l0, 0.30)
│   ├── reentry_lock.py ReentryLock(cooldown_sec=30)
│   ├── hours_guard.py  NOT USED in X1 (kept disabled in v1)
│   ├── blowoff_guard.py NOT USED in X1
│   └── ob_manipulation.py  NOT USED in X1 (stub; defer)
├── sizing/fixed.py     fixed_size() → $25.00
├── risk/drawdown_manager.py  DrawdownManager
└── backtest/
    ├── runner.py       reference implementation — re-use the per-fire path
    └── settlement.py   settle_legacy() — REPLACE with PMXT real-fee at deploy time
```

The `_momentum_from_streams_up_side()` helper inside `runner.py` and the `load_signal_streams()` helper in `data_io.py` are the exact paths the shadow-mode controller must use. The legacy `_momentum_from_tier1_up_side()` MUST NOT be used (it's the degraded proxy that produced anti-predictive results).

**Replace `settle_legacy()` with this PMXT real-fee function before live:**
```python
def settle_pmxt(won: bool, shares: float, usd: float, vwap: float,
                fee_rate: float = 0.07) -> float:
    fee = shares * fee_rate * vwap * (1.0 - vwap)
    if not won:
        return -usd - fee
    payout = shares * 1.0
    return payout - usd - fee
```

---

## 5. Env-var contract (TV-agent compatible)

```bash
# Master enable
CYCLOPS_ENABLED=true
CYCLOPS_X1_BTC_5M_ENABLED=true
CYCLOPS_X1_MODE=paper                   # paper | live (paper-only until promotion)

# Strategy mode flags
CYCLOPS_X1_REQUIRE_MOM_ABSTAIN=true
CYCLOPS_X1_SLEEVE_ACTIVE_REQUIRED=true
CYCLOPS_X1_SLEEVE_LOOKBACK_DAYS=30
CYCLOPS_X1_HOURS_GUARD=false            # explicitly off
CYCLOPS_X1_BLOWOFF_GUARD=false          # explicitly off
CYCLOPS_X1_OB_MANIPULATION_GUARD=false  # explicitly off (stub)

# Thresholds — DO NOT EDIT without re-running validation battery
CYCLOPS_X1_TREND_EPS_FRAC=0.005
CYCLOPS_X1_TREND_MIN_ABS=1
CYCLOPS_X1_LEVELS_MIN_CERTAINTY=0.15
CYCLOPS_X1_MOMENTUM_MIN_STRENGTH=0.15
CYCLOPS_X1_VWAP_MIN=0.30

# Sizing
CYCLOPS_X1_NOTIONAL_USD=25.00
CYCLOPS_X1_SIZING_MODE=fixed

# Fee model — MUST be pmxt_real
CYCLOPS_X1_FEE_MODEL=pmxt_real
CYCLOPS_X1_FEE_RATE=0.07

# Risk
CYCLOPS_X1_START_BALANCE=10000.00
CYCLOPS_X1_MAX_DRAWDOWN_PCT=5.0
CYCLOPS_X1_DAILY_LOSS_LIMIT_PCT=2.0
CYCLOPS_X1_RECOVERY_RESUME_FACTOR=0.5
CYCLOPS_X1_REENTRY_COOLDOWN_SEC=30
```

---

## 6. Risk manager (P4 — DrawdownManager)

In shadow mode `START_BALANCE = $10,000`. The manager produces a halt flag that must be checked **before** every evaluation. Three rules:

1. **Peak DD halt** — if `(peak - balance) / peak * 100 ≥ 5.0`, halt. Resume only when `balance ≥ peak * (1 - 0.5 × 5/100) = peak × 0.975`.
2. **Daily loss halt** — if `(day_start_balance - balance) / day_start_balance * 100 ≥ 2.0`, halt for the rest of the UTC day.
3. **UTC midnight roll** — `day_start_balance` resnaps when `int(now_ts) // 86400` changes.

Reference: `cyclops/risk/drawdown_manager.py`. On 21d backtest at $10k bankroll the manager never tripped (max DD was 2.2% of bankroll). At smaller bankrolls it WILL trip — use $10k as the calibrated minimum.

---

## 7. Telemetry event schema (mirrors VPS3 `trading.events`)

Five event kinds. One row per `(sleeve_id, slug, ws_s)` evaluation.

### 7.1 `poly_updown_cyclops_signal`
Published on every evaluation that reaches §1.10 (i.e., the fire branch).

```json
{
  "kind": "poly_updown_cyclops_signal",
  "at": "2026-05-17T14:32:07.123Z",
  "sleeve_id": "poly_updown_btc_5m_cyclops_v1_x1",
  "data": {
    "mode": "paper",
    "slug": "btc-updown-5m-1779284100",
    "condition_id": "0x...",
    "ws_s": 1779283800,
    "fire_us": 1779283920000000,
    "signal_dir": "Up",
    "trend_align": 2,
    "v_trend": 1,
    "v_levels": 1,
    "v_momentum": 0,
    "p_up_levels": 0.612,
    "score_momentum": 0.04,
    "mom_imb_l5": 0.18,
    "mom_cvd_norm": 0.02,
    "mom_aggressor": -0.04,
    "conflict_reason": "coherent_2of2",
    "ask_l0_px": 0.42,
    "vwap_entry": 0.435,
    "shares": 57.47,
    "stake_usd": 25.00,
    "fee_estimate_usd": 0.687,
    "fee_model": "pmxt_real",
    "fee_rate": 0.07,
    "sleeve_active_evidence": ["poly_updown_btc_5m_sniper", "poly_updown_btc_5m_momo_v2_HOLD"]
  }
}
```

### 7.2 `poly_updown_cyclops_skip`
Every skip. `skip_layer` identifies which gate killed the fire.

```json
{
  "kind": "poly_updown_cyclops_skip",
  "at": "...",
  "sleeve_id": "poly_updown_btc_5m_cyclops_v1_x1",
  "data": {
    "mode": "paper",
    "slug": "...",
    "ws_s": 1779283800,
    "skip_reason": "no_sleeve_activity",
    "skip_layer": "sleeve_active",   // risk | hours | reentry | trend | levels | momentum | conflict | vwap | sleeve_active | fill
    "v_trend": 1,
    "v_levels": 1,
    "v_momentum": 0
  }
}
```

### 7.3 `poly_updown_cyclops_resolution`
Per resolved trade.

```json
{
  "kind": "poly_updown_cyclops_resolution",
  "at": "...",
  "sleeve_id": "poly_updown_btc_5m_cyclops_v1_x1",
  "data": {
    "mode": "paper",
    "slug": "...",
    "ws_s": 1779283800,
    "direction": "Up",
    "outcome_truth": "Up",
    "won": true,
    "entry_vwap": 0.435,
    "shares": 57.47,
    "stake_usd": 25.00,
    "settlement_payout_usd": 57.47,
    "fee_usd": 0.687,
    "pnl_usd": 31.78,
    "strike_price": 67234.21,
    "settlement_price": 67318.55,
    "price_source": "chainlink"
  }
}
```

### 7.4 `poly_updown_cyclops_risk_pause`
When DrawdownManager halts.

```json
{
  "kind": "poly_updown_cyclops_risk_pause",
  "data": {
    "sleeve_id": "poly_updown_btc_5m_cyclops_v1_x1",
    "trigger": "max_drawdown",     // or "daily_loss"
    "value_pct": 5.18,
    "threshold_pct": 5.0,
    "recovery_target_balance": 9750.00,
    "current_balance": 9482.30,
    "peak_balance": 10000.00,
    "mode": "paper"
  }
}
```

### 7.5 `poly_updown_cyclops_error`
Unhandled exception in hot path. Truncate stack trace to 500 chars.

---

## 8. KPI queries

All KPIs read from `trading.events`. Do **not** maintain a session-state cache file (Cyclops May-7 lesson; stale-cache bug source).

```sql
-- Fire-rate over rolling 7 days
SELECT
  count(*) FILTER (WHERE kind='poly_updown_cyclops_signal')             AS fires,
  count(*) FILTER (WHERE kind='poly_updown_cyclops_skip')                AS skips,
  count(*) FILTER (WHERE kind='poly_updown_cyclops_signal')::numeric
    / NULLIF(count(*) FILTER (WHERE kind IN ('poly_updown_cyclops_signal','poly_updown_cyclops_skip')), 0) AS fire_rate
FROM trading.events
WHERE sleeve_id = 'poly_updown_btc_5m_cyclops_v1_x1'
  AND at > now() - INTERVAL '7 days';

-- Hit rate & PnL over rolling 7 days
SELECT
  count(*) AS n_resolved,
  avg((data->>'won')::int)::numeric(5,3) AS wr,
  avg((data->>'pnl_usd')::numeric)::numeric(10,4) AS mean_pnl,
  sum((data->>'pnl_usd')::numeric)::numeric(10,2) AS total_pnl
FROM trading.events
WHERE kind = 'poly_updown_cyclops_resolution'
  AND sleeve_id = 'poly_updown_btc_5m_cyclops_v1_x1'
  AND at > now() - INTERVAL '7 days';

-- Per-skip-layer distribution (which gate is filtering the most?)
SELECT
  data->>'skip_layer' AS layer,
  count(*) AS n
FROM trading.events
WHERE kind = 'poly_updown_cyclops_skip'
  AND sleeve_id = 'poly_updown_btc_5m_cyclops_v1_x1'
  AND at > now() - INTERVAL '7 days'
GROUP BY layer
ORDER BY n DESC;

-- Sleeve-active evidence (which other sleeves are co-firing on X1 slugs?)
SELECT
  unnest(string_to_array(data->>'sleeve_active_evidence', ',')) AS co_sleeve,
  count(*) AS n
FROM trading.events
WHERE kind = 'poly_updown_cyclops_signal'
  AND sleeve_id = 'poly_updown_btc_5m_cyclops_v1_x1'
  AND at > now() - INTERVAL '7 days'
GROUP BY co_sleeve
ORDER BY n DESC;
```

---

## 9. Promotion criteria (paper → live)

ALL of:
- `n_resolved ≥ 80`
- `n_losses ≥ 8` (so G3 perm test has real power)
- Rolling 21-day WR within ±5pp of backtest target (62-86%)
- G3 perm test on rolling n=300 (or all-available if less): **p < 0.05**
- G4 bootstrap CI on rolling n=300: **lower bound > 0** on $1 stake
- Max drawdown < 5% of bankroll for 14 consecutive days (i.e., no risk_pause events)
- Fire rate stays in 0.3-1.0% range (backtest was 0.59%)
- At least 60% of fires have ≥2 distinct co-firing sleeves in `sleeve_active_evidence`

Expected time to promotion at backtest fire rate (~14.5 fires/day on BTC 5m):
- n=80: ~5-6 days
- n=300: ~21 days

---

## 10. Kill criteria (live or paper)

Any one of:

| Trigger | Action |
|---|---|
| Live WR > 5pp BELOW backtest WR over rolling n=80 | **Pause the sleeve.** Investigate before resuming. |
| Two consecutive max_drawdown pauses within 7 days | **Pause.** Strategy is out-of-distribution. |
| G3 perm test on first n=100 live trades returns p > 0.20 | **Kill.** No statistical signal. |
| Fire rate drops below 0.2% for 7 days | **Kill OR investigate data feeds.** |
| Three consecutive `no_sleeve_activity` skip-rate days where it's > 95% of all skips | **Investigate.** VPS3 sleeve coverage likely degraded. |

Killing creates a sleeve-archive snapshot; do not delete config.

---

## 11. Backtest evidence (the numbers this spec is built on)

From `cyclops/_results/_real_fees_rerun.py` (real PMXT fees):

| Metric | BTC 5m X1 |
|---|---:|
| Period | 2026-04-24 03:00 → 2026-05-15 02:45 UTC (21.0 days) |
| Markets evaluated | 6,110 |
| Fires (S7 baseline) | 238 (3.90% fire rate) |
| Fires (X1 = S7 + sleeve_active) | 36 (0.59% fire rate) |
| Wins / Losses | 29 / 7 |
| Win rate | **80.56%** |
| Mean entry vwap | $0.650 |
| Breakeven WR under real PMXT fees | 66.59% |
| **Real-fee edge** | **+13.97pp** |
| Mean PnL @ $1 stake | +$0.244 |
| Total PnL @ $1 stake | +$8.79 |
| Total PnL @ $25 stake | **+$219.74** |
| Max drawdown @ $1 stake | -$2.06 |
| **G1** (mean PnL > 0) | **PASS** |
| **G3** permutation p-value | **0.002** (PASS) |
| **G4** bootstrap CI [95%] @$1 | [+$0.0042 .. +$0.4843] — **PASS** |
| G2 walkforward | INSUFFICIENT_WINDOWS — n=36 clusters in 2 of 8 windows |

Per direction:
- **Up:** n=21, WR 85.71%, mean +$0.328/$1, total +$6.88
- **Down:** n=15, WR 73.33%, mean +$0.127/$1, total +$1.91

Per co-firing sleeve overlap (descending impact):
- `momo_v2_*` family (any of HOLD/SELL/HEDGE): n=10, WR 90.00%, mean +$0.271/$1
- `volume_INV_NIGHT`: n=24, WR 75.00%, mean +$0.230/$1
- `sniper`: n=5, WR 80.00%, mean +$0.033/$1
- `v3_*` family: n=4, WR 75.00%, mean −$0.070/$1 (the only negative individual correlate)

---

## 12. Validity boundary (what this spec does NOT cover)

X1 is a **BTC 5m-only** strategy. The 6-cell asset×tf grid (`cyclops/_results/_6cell_grid.py`) shows:

| Cell | X1 verdict | Why |
|---|---|---|
| BTC 5m | **DEPLOY** | G1+G3+G4 all PASS |
| BTC 15m | DO NOT DEPLOY | WR 33%, anti-predictive (G3 p=0.986) |
| ETH 5m | DO NOT DEPLOY | Real-fee edge −0.71pp |
| ETH 15m | MAYBE — monitor | Real-fee edge +0.99pp but G3 p=0.32 |
| SOL 5m | DO NOT DEPLOY | Real-fee edge −0.99pp |
| SOL 15m | DO NOT DEPLOY | Real-fee edge −11.18pp (catastrophic) |

This spec is a single-sleeve spec. Extending to additional (asset, tf) cells requires re-tuning `TREND_K_BARS`, `TREND_EPS_FRAC`, and `LEVELS_LOOKBACK_DAYS` per cell, plus re-running the full validation battery on the new cell's universe.

---

## 13. Implementation handoff checklist

- [ ] Add `poly_updown_btc_5m_cyclops_v1_x1` to TV-agent sleeve registry
- [ ] Wire `cyclops.backtest.runner.run_backtest` per-fire path into the production controller
- [ ] Replace `settle_legacy` with `settle_pmxt` (real fee curve)
- [ ] Confirm production controller anchors on `ws_s = slug_suffix - 300`, NOT slot_start (regression-test against `SESSION_HANDOFF_2026_05_10_WS_S_CONVENTION.md`)
- [ ] Set up 30-day rolling cache of BTC 5m sleeve-active slugs from `trading.events`
- [ ] Wire the 5 telemetry event kinds with the schemas in §7
- [ ] Confirm `trading.events` writes accept the new `sleeve_id` value
- [ ] Add Grafana panels for KPI queries in §8
- [ ] Set up Slack/PagerDuty alert on `poly_updown_cyclops_risk_pause`
- [ ] Pre-flight: 24h shadow-trade test before flipping `CYCLOPS_X1_BTC_5M_ENABLED=true`
- [ ] Add an offline regression test: re-run the runner on 21d canonical and confirm total PnL matches `cyclops/_results/p5_full_depth_p3.csv` + sleeve_active filter → +$8.79 @ $1 within $0.10 tolerance

---

## 14. References

- This project: `cyclops/` package (Python, single-file-per-module)
- Original Cyclops architecture: `strategy_lab/reports/CYCLOPS_ARCHITECTURE_DEEP_DIVE_2026_05_16.md` §§19-22
- Original clone spec: `strategy_lab/reports/CYCLOPS_CLONE_SPEC_2026_05_16.md`
- Real fee model reference: `strategy_lab/fees.py`
- Polymarket fee docs: https://docs.polymarket.com/#fees
- ws_s convention pitfall: `strategy_lab/reports/SESSION_HANDOFF_2026_05_10_WS_S_CONVENTION.md`
- Six-cell grid data: `cyclops/_results/_6cell_grid.py` + `SIX_CELL_GRID.txt`
- Master strategy table: `cyclops/_results/_real_fees_rerun.py` + `MASTER_TABLE_REAL_FEES.txt`
- Sleeve-presence audit (mechanism): `cyclops/_results/_sleeve_presence_audit.py`
- Per-trade evidence CSV: `cyclops/_results/p5_full_depth_p3.csv`
- Validation scripts: `cyclops/validate/{permutation,bootstrap,walkforward}.py`

---

*End of spec. Implementation owner: next TV-agent session.*
