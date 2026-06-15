# TV AGENT SPEC — BTC 5m lag + momentum-alignment scalp (SHADOW → LIVE)

**Date:** 2026-06-09  **Owner research:** `SCALP_FROM_SHADOW_SLEEVES_2026_06_09.md`
**Status:** pre-registered single hypothesis, disjoint-OOS positive. SHADOW first; LIVE only after gates below.

A refinement of the deployed `shadow_scalp_exit_btc_5m_d3_v1`: SAME base lag scalp + a NEW
**momentum-alignment** gate, fired at offset 30/60s. Validated below.

---

## 1. Evidence (backtest, engine_v2 LiveMimicConfig, 10Hz L25, 85ms latency, 0.07 fee)

- Window **2026-04-24 → 2026-06-08** (~45 days). **164 fires** (98 IS / 66 OOS).
- Pre-registered OOS (held-out last 40%): **+$4.24/tr CI[1.85,6.52]** (pure +45s); with stop **+$5.21/tr CI[2.81,7.74]**.
- **Exit-policy ground truth** (`momalign_exit_policy_2026_06_09.py`): stop@−0.10 vs pure = **+0.73/tr CI[+0.35,+1.14], SIG in ALL/IS/OOS → KEEP STOP**. TP@0.65 **leaks** ($/tr 3.59→1.01) → **NO TP**. (stop-hit 23%, TP-hit 40%.)
- **Momentum-alignment gate adds the edge:** momalign OOS +4.24 vs no-regime +2.77.
- **ETH does NOT hold** (BTC only; BTC≫ETH).
- **Overlap w/ deployed 5s scalp** (`scalp_overlap_2026_06_09.py`): of 162 momalign slugs, deployed fires on only **9%** (2% same-side, 7% opposite/hedge) → **91% disjoint, additive coverage, negligible double-exposure.** Safe to run both.
- ⚠️ Not deflation-confirmed across the 130-cell search (expected; correlated trials). Meets the project bar only as a pre-registered hypothesis + disjoint-OOS CI>0 → **forward-test before capital**.

---

## 2. Sleeve definition (mirror existing SCALP_EXIT sleeves in `sniper_v5_sleeves.py`)

```python
# BTC 5m lag + momentum-alignment scalp (TV_AGENT_SPEC_SCALP_MOMALIGN_BTC5M_2026_06_09)
SniperV5Sleeve(
    sleeve_id="shadow_scalp_momalign_btc_5m_v1",
    asset="BTC", tf="5m", direction="BOTH",
    offsets=(30, 60),                      # NOTE: 2 offsets (vs deployed +5s)
    spread_filter=_SPREAD_LAGV2,
    notional_usd_override=Decimal("25.0"), # paper $25 (shadow); live override below
    live_notional_usd_override=Decimal("1.0"),
    one_shot_per_slug=True,
    exit_policy="SCALP_EXIT",
    entry_band=(0.0, 0.55),                # cheap leading token only
    # EXIT — ⚠️ use PURE time-sell, NO stop, NO TP. The 06-09 "stop +0.73/tr" used the flagged
    # outcome-fallback harness; the 06-11 corrected-harness FINAL is STOP DEAD (artifact) → pure +Ns
    # time-sell on all scalp sleeves (TP off, stop off). Match the deployed scalp's exit exactly.
    scalp_exit_secs=45,                    # (or 60 to match deployed; pure time-sell)
    scalp_stop_delta=None,                 # NO stop (06-11: artifact). Re-validate w/ scalp_fill_lib_2026_06_10 before adding.
    scalp_take_profit=None,                # NO TP (leaks — confirmed)
    gates=(
        GateRef(g_oracle_lag_with, (("lo_bps","3.0"),("hi_bps","12.0")), "g_oracle_lag_with(3.0,12.0)"),
        GateRef(g_lag_momentum_align, (("asset","BTC"),("mom_win_s","30")), "g_lag_momentum_align(BTC,30)"),
    ),
),
# CONTROL — identical but momalign gate OFF, to measure the gate's live lift (A/B):
SniperV5Sleeve(
    sleeve_id="shadow_scalp_momalign_btc_5m_control_v1",
    ... identical ...,
    gates=( GateRef(g_oracle_lag_with, (("lo_bps","3.0"),("hi_bps","12.0")), "g_oracle_lag_with(3.0,12.0)"), ),
),
```
(Use whatever exit-param names the existing `SCALP_EXIT` config uses — `SCALP_EXIT_CONFIG_BY_TF`. The
**intent is exact**: taker exit at **+45s**, **protective stop at fill−0.10 ON**, **take-profit OFF**.)

---

## 3. NEW gate — `g_lag_momentum_align` (`sniper_v5_gates.py`, mirror `g_oracle_lag_with`)

Pass iff the oracle-lag direction agrees with the 30s binance return AND it's the leading side.

```python
def g_lag_momentum_align(direction, fire_us, *, asset, oracle_lag=None, mom_win_s="30", **_):
    if oracle_lag is None or getattr(oracle_lag, "stale", False):
        return False
    lag = float(oracle_lag.price_delta_bps)              # rolling binance 5s return (same source as g_oracle_lag_with)
    px_now  = _binance_close_at(asset, fire_us)
    px_then = _binance_close_at(asset, fire_us - int(mom_win_s) * 1_000_000)
    if not px_now or not px_then or px_then <= 0:
        return False                                     # fail-closed on missing 1s data
    mom = px_now / px_then - 1.0
    if lag == 0 or mom == 0:
        return False
    if (lag > 0) != (mom > 0):                           # signs must AGREE
        return False
    return direction == ("UP" if lag > 0 else "DOWN")    # leading side only
```
Reuses `_binance_close_at` + the `oracle_lag` snapshot already wired for the scalp. Register in `__all__`.

---

## 4. SHADOW deploy (VPS3 — do first)

- Add both sleeves to `SNIPER_V5_SLEEVES`. They run shadow automatically on VPS3 (full-fleet box).
- Resolution emits `event_type='sleeve_scalp_exit'` (distinct → no double-count).
- Runs alongside the existing `shadow_scalp_exit_btc_5m_*` sleeves (91% disjoint slugs — additive).

## 5. LIVE deploy (Ireland — only after §6 gates)

- Add `shadow_scalp_momalign_btc_5m_v1` to `TV_POLY_SNIPER_V5_LIVE_ALLOWLIST` in `/etc/tv/tradingvenue.env`.
- Live size = `live_notional_usd_override` = **$1** probe (clamped by `SNIPER_V5_LIVE_MAX_NOTIONAL`).
- ✅ **Live firing CONFIRMED working on Ireland** (verified 2026-06-09): `g_oracle_lag` passes all day, the
  existing `shadow_scalp_exit_btc_5m_d3_v1_LIVE` placed 8 live fills / 24h (15m: 4). The momalign sleeve
  uses the same 1s-store gate path → it will fire live the same way. (An earlier 06-08 note claimed a stale
  1s `vwap_store` blocker — that is RETRACTED; the store is live and the scalp trades live.)
- Dedup vs deployed 5s scalp: only ~2% same-side overlap; if both live, skip the second same-side entry per slug.
- Minor: one `live_exec_failed` seen in 24h (placement attempt failed at exec) — monitor, not a blocker.

## 6. Graduation gates (HARD — before ANY real capital)

1. SHADOW on VPS3: **≥200 forward fires**, bootstrap CI on realized scalp $/tr **> 0**.
2. momalign sleeve **beats its `_control_v1`** (paired, live fires) → confirms the gate adds lift live.
3. Exit confirmed: realized fires show stop firing ~20–25%, no TP. Then $1 live probe (after §5 1s-store fix).

## 7. Guardrails
- BTC 5m only (ETH/SOL did not hold). Offsets (30,60). Stop ON, TP OFF, exit +45s — do NOT re-enable TP.
- Shadow $25 paper / live $1. This is a forward-test, NOT a confirmed edge.
