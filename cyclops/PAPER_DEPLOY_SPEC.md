# Cyclops — Paper-Deploy Spec (P8)

**Date:** 2026-05-16
**Status:** Spec only. Implementation handoff to the TV-agent.
**Source:** `cyclops/` package (Python, single-file-per-module).
**Validation gates passed:** G0, G1, G2 (baseline only), G3 (both regimes).

---

## 0. Why paper-deploy with two sleeves

The 21d backtest yielded **two statistically-supported configurations** of the same strategy. Neither passes 5/5 gates on 21d alone (G4 fails purely on sample-size, not signal). Live paper-trading is the cheapest way to extend n past the gate threshold:

| Regime | n on 21d | WR | mean PnL | G3 p-value | What it tests |
|---|---:|---:|---:|---:|---|
| `cyclops_v1_baseline` | 305 | 61.3% | +$1.50/tr | 0.022 | Conflict-filter + vwap guard + momentum-must-abstain |
| `cyclops_v1_hours` | 53 | 67.9% | +$4.34/tr | 0.011 | Same + Cyclops's hours/blowoff guards |

Live extrapolation (assuming 21d rates hold):
- baseline reaches **n=300 in ~21 days** → G4 should clear by mid-June
- hours reaches **n=300 in ~120 days** → G4 should clear by mid-September

Running both in parallel converts the regime choice into a **falsifiable head-to-head**: whichever regime drifts off the 21d distribution loses.

## 1. Two sleeves

### `cyclops_v1_baseline` — the "broad signal" sleeve

```yaml
sleeve_id: poly_updown_btc_5m_cyclops_v1_baseline
strategy: cyclops/backtest/runner.py
runner_args:
  asset: BTC
  timeframe: 5m
  vwap_min: 0.30
  require_momentum_abstain: true
  hours_guard_enabled: false
  blowoff_guard_enabled: false
  reentry_lock_enabled: true   # live-only; no-op in backtest
  risk_enabled: true
  start_balance: 10000.0
  max_drawdown_pct: 5.0
  daily_loss_pct: 2.0
notional_usd: 25.0
expected_fires_per_day: ~14.5
expected_wr: 61%
expected_mean_pnl: +$1.50
```

### `cyclops_v1_hours` — the "high-confidence" sleeve

```yaml
sleeve_id: poly_updown_btc_5m_cyclops_v1_hours
strategy: cyclops/backtest/runner.py
runner_args:
  asset: BTC
  timeframe: 5m
  vwap_min: 0.30
  require_momentum_abstain: true
  hours_guard_enabled: true
  hours_start_utc: 13.0
  hours_stop_utc: 21.0
  weekend_off: true
  blowoff_guard_enabled: true
  reentry_lock_enabled: true
  risk_enabled: true
  start_balance: 10000.0       # SEPARATE bankroll from baseline
  max_drawdown_pct: 5.0
  daily_loss_pct: 2.0
notional_usd: 25.0
expected_fires_per_day: ~2.5
expected_wr: 68%
expected_mean_pnl: +$4.34
```

**Bankrolls are independent.** Each sleeve gets its own $10k. Total live exposure is $50 per shared fire (when hours-window is open and both fire) or $25 per baseline-only fire.

## 2. Env-var contract (TV-agent compatible)

Mirrors the existing `CONFLUENCE_*` / `MOMO_*` naming so the rail framework recognises it. **Prefix per-sleeve.**

### Master enable

```bash
CYCLOPS_ENABLED=true
```

### Per-sleeve enable

```bash
CYCLOPS_BTC_5M_BASELINE_ENABLED=true
CYCLOPS_BTC_5M_HOURS_ENABLED=true

# Asset/TF extensions (stay false until each clears its own validation)
CYCLOPS_BTC_15M_BASELINE_ENABLED=false
CYCLOPS_ETH_5M_BASELINE_ENABLED=false
CYCLOPS_SOL_5M_BASELINE_ENABLED=false
```

### Shared (axis & filter thresholds)

```bash
# Axis thresholds — same across both sleeves
CYCLOPS_TREND_EPS_FRAC=0.005
CYCLOPS_TREND_MIN_ABS=1
CYCLOPS_LEVELS_MIN_CERTAINTY=0.15
CYCLOPS_MOMENTUM_MIN_STRENGTH=0.15

# Conflict filter — both sleeves use require_momentum_abstain
CYCLOPS_REQUIRE_MOM_ABSTAIN=true
CYCLOPS_ABSTAIN_LIMIT=2

# Sizing
CYCLOPS_NOTIONAL_USD=25.0
CYCLOPS_SIZING_MODE=fixed

# Vwap pre-flight (the P2 forensic finding)
CYCLOPS_VWAP_MIN=0.30

# Reentry cooldown
CYCLOPS_REENTRY_COOLDOWN_SEC=30
```

### Sleeve-specific

```bash
# Baseline: no hours/blowoff
CYCLOPS_BASELINE_HOURS_GUARD=false
CYCLOPS_BASELINE_BLOWOFF_GUARD=false

# Hours sleeve: full Cyclops Day-3 stack
CYCLOPS_HOURS_TRADING_START_UTC=13.0
CYCLOPS_HOURS_TRADING_STOP_UTC=21.0
CYCLOPS_HOURS_WEEKEND_OFF=true
CYCLOPS_HOURS_BLOWOFF_GUARD=true
CYCLOPS_HOURS_BLOWOFF_RSI_THRESHOLD=60
CYCLOPS_HOURS_BLOWOFF_MIN_MTF=3
CYCLOPS_HOURS_BLOWOFF_GUARD_UP=true
CYCLOPS_HOURS_BLOWOFF_GUARD_DOWN=false
```

### Risk

```bash
CYCLOPS_BASELINE_START_BALANCE=10000.0
CYCLOPS_HOURS_START_BALANCE=10000.0
CYCLOPS_RISK_PAUSE_MODE=hard
CYCLOPS_MAX_DRAWDOWN_PCT=5.0
CYCLOPS_DAILY_LOSS_LIMIT_PCT=2.0
CYCLOPS_RECOVERY_RESUME_FACTOR=0.5
```

## 3. Event schema (`trading.events`)

Mirrors VPS3 production shape. Five event kinds per sleeve:

### `poly_updown_cyclops_signal`

Every evaluation (fire OR skip). One row per (sleeve_id, slug, ws_s).

```json
{
  "kind": "poly_updown_cyclops_signal",
  "at": "2026-05-16T14:32:07.123Z",
  "data": {
    "sleeve_id": "poly_updown_btc_5m_cyclops_v1_baseline",
    "slug": "btc-updown-5m-1779284100",
    "ws_s": 1779283800,
    "fire_us": 1779283920000000,
    "signal_dir": "Up",
    "v_trend": 1,
    "v_levels": 1,
    "v_momentum": 0,
    "trend_align": 2,
    "p_up_levels": 0.612,
    "score_momentum": 0.04,
    "conflict_reason": "coherent_2of2",
    "guards_passed": ["vwap_guard", "hours_guard"],
    "ask_l0_px": 0.42,
    "vwap_entry": 0.435,
    "stake_usd": 25.0,
    "shares": 57.47,
    "fee_rate": 0.02,
    "mode": "paper"
  }
}
```

### `poly_updown_cyclops_skip`

Every skip, with the layer that caused it.

```json
{
  "kind": "poly_updown_cyclops_skip",
  "data": {
    "sleeve_id": "...",
    "slug": "...",
    "ws_s": 1779283800,
    "skip_reason": "vwap_guard_0.220<0.30",
    "skip_layer": "vwap_guard",   // conflict | hours | vwap | blowoff | reentry | risk
    "v_trend": 1, "v_levels": 1, "v_momentum": 0,
    "mode": "paper"
  }
}
```

### `poly_updown_cyclops_resolution`

Per fired+resolved trade.

```json
{
  "kind": "poly_updown_cyclops_resolution",
  "data": {
    "sleeve_id": "...",
    "slug": "...",
    "ws_s": 1779283800,
    "direction": "Up",
    "outcome_truth": "Up",
    "won": true,
    "entry_vwap": 0.435,
    "shares": 57.47,
    "stake_usd": 25.0,
    "settlement_payout_usd": 57.47,
    "fee_usd": 0.65,
    "pnl_usd": 31.82,
    "mode": "paper"
  }
}
```

### `poly_updown_cyclops_risk_pause`

When DrawdownManager halts.

```json
{
  "kind": "poly_updown_cyclops_risk_pause",
  "data": {
    "sleeve_id": "...",
    "trigger": "max_drawdown",       // or daily_loss
    "value_pct": 5.18,
    "threshold_pct": 5.0,
    "recovery_target_balance": 9750.0,
    "current_balance": 9482.30,
    "mode": "paper"
  }
}
```

### `poly_updown_cyclops_error`

Unhandled exceptions in the strategy hot path. Stack truncated to 500 chars.

## 4. KPI queries

All KPIs are computed live from `trading.events`. **No session-state cache files** (per Cyclops May 7 article fix #4 — caches were the source of his stale-state bug).

```sql
-- 7-day fire rate
SELECT sleeve_id,
       count(*) FILTER (WHERE kind='poly_updown_cyclops_signal') AS fires,
       count(*) FILTER (WHERE kind='poly_updown_cyclops_skip')   AS skips
FROM trading.events
WHERE at > now() - INTERVAL '7 days'
  AND data->>'sleeve_id' LIKE 'poly_updown_btc_5m_cyclops_v1_%'
GROUP BY sleeve_id;

-- 7-day WR
SELECT sleeve_id,
       count(*) AS n_resolved,
       avg((data->>'won')::int)::numeric(5,3) AS wr,
       sum((data->>'pnl_usd')::numeric)::numeric(10,2) AS total_pnl_usd,
       avg((data->>'pnl_usd')::numeric)::numeric(10,4) AS mean_pnl_usd
FROM trading.events
WHERE kind = 'poly_updown_cyclops_resolution'
  AND at > now() - INTERVAL '7 days'
GROUP BY sleeve_id;

-- Per-skip-layer breakdown
SELECT sleeve_id,
       data->>'skip_layer' AS layer,
       count(*) AS skips_in_layer
FROM trading.events
WHERE kind = 'poly_updown_cyclops_skip'
  AND at > now() - INTERVAL '7 days'
GROUP BY sleeve_id, layer
ORDER BY skips_in_layer DESC;
```

## 5. Promotion criteria (paper → live)

For EACH sleeve independently:

| Gate | Threshold |
|---|---|
| n_resolved ≥ 80 | guarantees G3 has real power |
| n_losses ≥ 5 | so G3 isn't trivially significant |
| 21-day rolling WR ≥ entry_vwap + 1pp | safety margin above breakeven |
| G3 perm test on rolling n=300 | p < 0.05 |
| G4 bootstrap CI on rolling n=300 | lower bound > 0 |
| Max drawdown < 5% of bankroll for 14 consecutive days | risk pause-test passed |

Sleeves promote independently. The hours sleeve will likely reach these later than the baseline by ~5×.

## 6. Kill criteria (paper)

For EITHER sleeve at any time:

| Trigger | Action |
|---|---|
| Live WR more than 5pp below 21d backtest WR over rolling n=80 | **Pause that sleeve.** Investigate before resuming. |
| Two consecutive max-drawdown pauses within 7 days | **Pause that sleeve.** Risk-pause is doing its job; the strategy is OOD. |
| G3 perm test on first n=100 live trades returns p > 0.20 | **Kill that sleeve.** No statistical signal. |
| Cross-asset divergence > 30% (e.g. ETH 5m running OK but BTC 5m fails) | Investigate asset-specific regime. |

If both sleeves trip simultaneously and the same kill criterion applies, kill the entire `cyclops_v1_*` family and revert to the backtest-state archive.

## 7. Open work

| Item | Owner | Trigger |
|---|---|---|
| Wire `ob_manipulation` guard (deferred) | code | OB streaming integration when needed |
| Recalibrate `TREND_EPS_FRAC` on rolling 14d | code | After n=500 live trades |
| Per-hour PnL split for non-default hours windows | analysis | After n=200 live trades on hours sleeve |
| Re-run G4 bootstrap at n=600 | analysis | When canonical extends past May 16 |
| Consider sizing on n_coherent (3-axis vs 2-axis) | spec change | NOT before n=1000 — flagged for spec §13 "do not iterate" |

## 8. Handoff checklist

- [ ] TV-agent imports `cyclops.backtest.runner.run_backtest()` via subprocess OR re-implements the per-fire path with the env-var contract
- [ ] Two sleeve config files committed to TV-agent's config dir
- [ ] `trading.events` schema verified to accept the 5 new event kinds
- [ ] Production controller reads `ws_s = slug_suffix - window_s` (CRITICAL — the original bug)
- [ ] L25 fills mock to real (production already does this)
- [ ] Risk-manager pause publishes a Slack/PagerDuty alert
- [ ] KPI dashboard rows added to Grafana
- [ ] 24h shadow-trade test before flipping `CYCLOPS_ENABLED=true`

## 9. References

- `cyclops/README.md` — phase status
- `cyclops/_results/p4_risk_10k.csv` + `.permutation.json` / `.bootstrap.json` / `.walkforward.json`
- `cyclops/_results/p3_full_stack.csv` + matching validation JSONs
- `strategy_lab/reports/CYCLOPS_CLONE_SPEC_2026_05_16.md` — original build spec
- `strategy_lab/reports/CYCLOPS_ARCHITECTURE_DEEP_DIVE_2026_05_16.md` — Cyclops's own architecture
- VPS3 production controller (`poly_updown_loop.py`) — reference for `ws_s` anchor convention

---

*Spec generated 2026-05-16. Implementation owner: next TV-agent session.*
