# 11 idle sleeves diagnosis — VPS3 live (2026-05-27 ~17:00 UTC)

_Dashboard shows PnL/WR/ROI = "—" on these 11 sleeves. SSH'd VPS3, queried `storedata.trading.events` directly. **Two different root causes** — one per sleeve group. Detailed below._

## TL;DR

| group | sleeves | events / sleeve | real fires | root cause |
|---|--:|--:|--:|---|
| **VWAP-cont (5)** | `*_vwap_off*` | 315-319 | **0** | **Working-as-designed** — gates are TOO TIGHT for the panel period. Features are populated correctly. |
| **Overlay filters (6)** | `shadow_*_sniper_m5v/_fairedge500/etc` | 271-817 | **0** | **Bug**. Overlay's wrapped `_base_strategy` returns NONE on every call even though production parent IS firing 78-106 times. Overlay state-isolation issue. |

## Group 1 — 5 VWAP-cont sleeves: **working as designed, gates too tight**

### DB shows: 318 events each, 0 fires, 0 resolutions, all `no_signal`

```
poly_updown_btc_5m_vwap_off240_m1v        318 events / 0 UP-DOWN / 0 res
poly_updown_btc_5m_vwap_off60_f7_cross    319 events / 0 / 0
poly_updown_btc_5m_vwap_off90_cross       316 events / 0 / 0
poly_updown_eth_5m_vwap_off210_f7_m1v     315 events / 0 / 0
poly_updown_sol_5m_vwap_off60             319 events / 0 / 0
```

### Sample payload (proves features ARE populated)

```json
{
    "tf": "5m", "symbol": "BTC", "signal": "NONE", "reason": "no_signal",
    "entry_phase": "t_plus_240", "fire_offset_s": 240,
    "strategy_mode": "vwap_continuation",
    "vwap_dev_bps": -7.43,
    "vwap_15m_anchored": 75088.32,
    "rsi_14_for_signal": 55.42,
    "markov_regime_w20_1m_va": 2,
    "cross_asset_devs": [["ETH", -6.12], ["SOL", -10.38]]
}
```

### Why no fires — sleeve spec analysis

From `backend/app/engine/main.py:135`:

```
("poly_updown_btc_5m_vwap_off240_m1v",     "BTC", "5m", 240,  5.0, 10.0, True,  False, False, False),
                                                       │     │    │     │
                                                       │     │    │     +-- f7_gate
                                                       │     │    +-------- m1v_gate ✓
                                                       │     +------------- dev_tier_max (bps)
                                                       +------------------- dev_tier_min (bps)
```

Gates per sleeve:

| sleeve | offset | dev tier (bps) | m1v | f7 | cross |
|---|--:|---|--:|--:|--:|
| btc_5m_vwap_off240_m1v | 240 | 5-10 | ✓ | × | × |
| btc_5m_vwap_off60_f7_cross | 60 | 10-15 | × | ✓ | ✓ |
| btc_5m_vwap_off90_cross | 90 | 10-15 | × | × | ✓ |
| eth_5m_vwap_off210_f7_m1v | 210 | 10-15 | ✓ | ✓ | × |
| sol_5m_vwap_off60 | 60 | 20-30 | × | × | × |

Sample BTC fires from log: `dev_bps = -7.43` and `+13.08`.
- `-7.43` has `|dev| = 7.43` → inside 5-10 tier, direction = DOWN. But `m1v = 2 (BULL)`. M1V passes only when regime sign agrees with signal direction → BULL+DOWN = mismatch → **no_signal**.
- `+13.08` is OUTSIDE the 5-10 tier (>10) → not in window → **no_signal**.

That's the literal design. The intersection of `(|dev| in [5,10]) AND (M1V regime agrees with dev sign)` is rare. Over 318 evaluations across 3 days, 0 hits.

### Verdict — Group 1

**NOT a bug. Sleeves are running correctly.** Backtest gates were tight enough that 318 evaluations / 3 days → ~0-2 expected fires. Sample size too small to conclude anything yet.

Recommendation: keep running shadow for 14 more days. If still 0 fires, **widen the tier** (e.g. 5-20 bps for `btc_5m_vwap_off240_m1v`) and re-run.

## Group 2 — 6 overlay-filter sleeves: **REAL BUG**

### DB shows: 271-817 events each, 0 fires, 0 resolutions

```
shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30   272 / 0 fires
shadow_poly_updown_btc_5m_momo_v2_fairedge500          817 / 0 fires
shadow_poly_updown_eth_15m_sniper_m5v                  271 / 0 fires
shadow_poly_updown_sol_15m_sniper_fairedge500          271 / 0 fires
shadow_poly_updown_sol_5m_momo_v1_m5v                  816 / 0 fires
shadow_poly_updown_sol_5m_momo_v2_cvd_macd             817 / 0 fires
```

### BUT — production PARENTS are firing fine

```
poly_updown_btc_5m_momo_v2_HOLD_f7   106 fires / 53 resolutions
poly_updown_eth_15m_sniper_hod        78 fires / 17 resolutions
poly_updown_sol_5m_momo_HOLD_f7       92 fires / 46 resolutions
poly_updown_sol_5m_momo_v2_HOLD_f7    88 fires / 44 resolutions
```

### Sample overlay payload (NULL features even after Bug 1 fix)

```json
{
    "tf": "15m", "mode": "paper", "reason": "no_signal", "signal": "NONE",
    "symbol": "ETH", "strategy_mode": "overlay_sniper",
    "predicted_edge_pp": 3.0, "predicted_cost_bps": 400.0
}
```

**No `vwap_dev_bps`, no `fair_edge_bp`, no `markov_regime`, no `cvd_30s`, no `macd_hist`.** Compare to VWAP sleeves above (those DO carry features).

### Bug analysis

`OverlayFilterStrategy.signal()` in `backend/app/strategies/polymarket/shadow9.py:465`:

```python
def signal(self, bars, config, aux):
    base_sig = self._base_strategy.signal(bars, config, aux)
    if base_sig not in ("UP", "DOWN"):
        return "NONE"
    # ... then evaluate gate ...
```

The base_strategy returns NONE every time. The overlay never reaches the gate-check code path, so no features get logged.

**Why does base_strategy return NONE on overlay path but UP/DOWN on production path** for the same slug at the same time?

Two possible causes (need source dive in `bots.py` overlay registration):

1. **Separate base_strategy instance** — overlay was wired with a fresh strategy instance that doesn't share `_bars` deque, RSI buffers, or feature warm-up state with the production parent. Returns NONE because internal state is empty.
2. **Different aux dict** — production parent's aux has `_bar_ctx`, `_controller_ref`, `fair_edge_bp_up/down`, `markov_regime_w20_5m_va`. Overlay's aux is stripped down. Base strategy reads `aux["fair_edge_bp"]` (Phase 36-injected feature it needs to fire) and finds None → returns NONE.

Evidence for cause (2): the controller has an aux-injection block at `controllers/polymarket_updown.py:1457-1474`:

```python
fe_up = getattr(_bar_ctx_pre, "fair_edge_bp", None)
...
aux = {
    "fair_edge_bp": fe_up,
    "fair_edge_bp_down": fe_dn,
    ...
}
```

If the overlay shadow's controller doesn't run this aux-injection block (because it's a different controller instance from production), base_strategy reads `fair_edge_bp=None` → fails its internal check → returns NONE.

### Confirmation needed (read source)

```bash
ssh vps3
grep -B5 -A30 'OverlayFilterStrategy\|register.*overlay\|gate_kind=' \
  /opt/tradingvenue/backend/app/api/bots.py | head -100
```

Look for the registration call — does it instantiate a fresh base_strategy or share the production instance? Does it duplicate the aux-injection block from `controllers/polymarket_updown.py:1457`?

### Quick fix candidates

A. **Mirror the aux-injection block** from `polymarket_updown.py:1457` into the overlay's call path so the wrapped base_strategy sees the same aux dict (with `fair_edge_bp`, `fair_edge_bp_down`, `markov_regime_w20_5m_va`) as the production parent.

B. **Share the production base_strategy instance** instead of constructing a fresh one. The shadow only adds a gate check on top — no need to re-run the base signal logic, just intercept the production fire event and apply the gate.

C. **Make the overlay a post-fire HOOK**: when production parent emits `poly_updown_signal` for `poly_updown_eth_15m_sniper_hod`, mirror it under `shadow_poly_updown_eth_15m_sniper_m5v` IFF the M5V gate passes (read regime from the same BarContext). This is the cleanest design but requires a new hook in the audit-write path.

### Verdict — Group 2

**Real bug. Overlay sleeves are unable to fire by construction**, not by gate selectivity. They emit 271-817 heartbeats per sleeve over 3 days, all `signal: NONE` because the wrapped `_base_strategy` always returns NONE — most likely because the overlay's `aux` dict is missing the Phase 36 features (`fair_edge_bp`, `markov_regime_w20_5m_va`, ...) that the base strategy needs.

## Side note — VWAP heartbeat ratio is suspicious too

The VWAP sleeves emit 315-319 events per 3 days. With 3 assets × (288 5m slots × 3 days) = 864 5m slot-evaluations per asset. At offset 240 there should be ~864 evaluations per sleeve, but we see only 318. **2.7× fewer than expected** — maybe the scheduler dispatches the sleeve only on some slots or the late-fire offset+m1v dispatch skips heartbeats when m1v compute fails. Worth a follow-up but not blocking.

## Action items (tv-agent next session)

| priority | task |
|---|---|
| **P0** | **Bug fix for overlay sleeves** — implement option C (post-fire hook) OR option A (mirror the aux-injection block). Without this, 6 sleeves stay dead. |
| **P0** | Verify the new aux delivers `fair_edge_bp`, `markov_regime_w20_5m_va`, `cvd_agree_30s`, `macd_hist` to the OverlayFilterStrategy via `_from_ctx` reads. |
| **P1** | After fix is deployed, run a 12 h check: overlay fire-rate should be ≈ 21 % of production parent fire-rate (matches the backtest n_gate / n_total ratio). |
| **P2** | VWAP sleeves are correctly gated but yield 0 fires in 3 days. Widen the dev tier on the slowest cells (btc_5m_vwap_off240_m1v: 5-10 → 5-20). |
| **P2** | Investigate why VWAP heartbeat count is 318 vs 864 expected slots — may be a scheduler dispatch gap. |

## Reference data captured

| query | result |
|---|---|
| All shadow events last 3 d | 4 803 events across 15 sleeves |
| 9 of 9 Phase 36 + 6 overlay registered | ✓ |
| Phase 36 Kelly + FADE sleeves firing? | ✓ (post Bug 1 fix from 2026-05-26) |
| 5 VWAP-cont sleeves firing? | ❌ 0 fires (gate-tight, not a bug) |
| 6 overlay sleeves firing? | ❌ 0 fires (real bug — base returns NONE) |
| Production parent sleeves firing? | ✓ 78-106 fires per sleeve / 3 days |

## Files

- This diagnosis: `strategy_lab/reports/IDLE_SLEEVES_DIAGNOSIS_2026_05_27.md`
- Prior audit: `strategy_lab/reports/VPS3_LIVE_SHADOW_AUDIT_V2_2026_05_25.md`
- Phase 36 fix log: `strategy_lab/reports/TV_AGENT_FIX_SPEC_PHASE36_BUGS_2026_05_26.md`
