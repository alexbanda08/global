# TV Fix Spec — `g_vol_high` / `g_vol_contracting` rv_60 SCALE BUG — 2026-05-27

**SEVERITY**: HIGH — one gate is a silent no-op (10 sleeves), one gate is a PERMANENT BLOCK (1 sleeve never fires).

**FOUND BY**: live analysis 2026-05-27. Operator flagged `VOL_HIGH_RV60_THR` appears far below real rv_60 → gate passes ~always.

---

## TL;DR

The threshold `VOL_HIGH_RV60_THR` was calibrated on **NON-annualized** realized vol, but the production panel compares against **ANNUALIZED** `rv_60` (≈187–324× larger). Scale mismatch:

| Gate | Compare | Live behavior | Affected |
|---|---|---|---|
| `g_vol_high` | `rv_60 > thr` | annualized rv_60 (~0.5–1.0) always >> thr (~0.008–0.027) → **ALWAYS TRUE = no-op** | 10 sleeves |
| `g_vol_contracting` | `rv_60 < thr × 0.5` | annualized rv_60 never < (~0.004–0.014) → **ALWAYS FALSE = permanent block** | 1 sleeve |

---

## Evidence

### Production panel — `vol_hurst.py:187`
```python
rv = math.sqrt(sum(r * r for r in log_rets) / RV_LOOKBACK_BARS)   # raw per-bar realized vol
rv_60 = rv * math.sqrt(ANNUAL_FACTOR_BY_TF[tf])                    # ANNUALIZED
```
where `ANNUAL_FACTOR_BY_TF = {"5m": 105_120, "15m": 35_040}`.
- 5m annualization: √105120 = **324.2×**
- 15m annualization: √35040 = **187.2×**

### Threshold — `sniper_v5_thresholds.py:38`
```python
VOL_HIGH_RV60_THR = {
    ("BTC","5m"): 0.0084, ("ETH","5m"): 0.0109, ("SOL","5m"): 0.0142,
    ("BTC","15m"):0.0162, ("ETH","15m"):0.0203, ("SOL","15m"):0.0271,
}
```

### Why these thresholds are NON-annualized (proof)
1. **Magnitude**: real crypto annualized vol p75 ≈ 0.5–0.9 (50–90%). Thresholds are 0.008–0.027 — that's the scale of **raw per-bar** realized vol, not annualized.
2. **TF-scaling signature**: 15m thr / 5m thr = 0.0162/0.0084 = **1.93 ≈ √3**. A 15m bar has ~3× the variance of a 5m bar, so its raw std is √3× larger. This is the fingerprint of NON-annualized per-bar vol. Annualized thresholds would be ~tf-INDEPENDENT (annualization normalizes timeframe).
3. **Spec §9 mislabel**: `SHADOW_DEPLOY_SPEC_2026_05_27.md:255` comments `# rv_60 = 60-bar realized vol (annualized, asset-specific)` and `thr = p75 of rv_60 distribution`. The "annualized" label is WRONG — the p75 of the annualized distribution cannot be 0.0084. The backtest that produced these p75 values computed them on RAW rv.
4. **vol_hurst.py header**: claims `rv_60 ~ 0.01-0.03 ≈ 1-3% annualized vol on crypto`. This is internally inconsistent — 1–3% annualized is impossibly low for crypto (real is 40–80%). The author expected rv_60 ≈ 0.01–0.03 (which matches the thresholds = raw rv), but the code multiplies by √annual_factor making it ~100–300× bigger.

### Numeric sanity (BTC 5m)
- Typical BTC 5m raw rv ≈ 0.0015–0.003
- Annualized rv_60 = 0.002 × 324 ≈ **0.65**
- Threshold = 0.0084
- `g_vol_high`: 0.65 > 0.0084 → **TRUE every time** → no-op
- `g_vol_contracting`: 0.65 < 0.0042 → **FALSE every time** → blocks all fires

---

## Impact per sleeve

### `g_vol_high` no-op — 10 sleeves (filter does nothing; sleeves still fire on OTHER gates)
ETH 15m: trstack_vwap_vol_offearly, _vL, _band_v6, _band_v6_vL, pw_trendslope_trstack_offearly_v6, pi_btc15m_trend_v7, baseline_v7_top_replicate_v8, pj_btc_and_sol_trend_sep_v8
SOL 15m: trstack_vol_ribbon_ema_mid, _vL

**Consequence**: these sleeves fire on a BROADER population than the backtest validated. The backtest applied the vol filter as a meaningful top-25%-vol gate; production applies no filter → ~4× more fires than validated → quality dilution. The OTHER gates in each stack still work, so it's not catastrophic, but the validated edge assumed the vol filter was active.

### `g_vol_contracting` permanent block — 1 sleeve (NEVER fires)
- `poly_sniper_v5_btc_15m_btceth_diverg_stoch_volcontr_v8`

**Consequence**: this sleeve produces ZERO placements in production because `g_vol_contracting` always returns False. Verify against live JSONL — it should have 0 placed fires and skip_reason `g_vol_contracting=False` on every eval. The backtest validated it WITH the low-vol filter active (on raw rv), so backtest had fires; production has none.

---

## The fix

Make the gate comparison scale MATCH the threshold calibration scale (raw, non-annualized rv). Two clean options:

### Option A (recommended) — de-annualize inside the gates
Add `ANNUAL_FACTOR_BY_TF` import to `sniper_v5_gates.py` and compare against raw rv:

```python
import math
from backend.app.features.vol_hurst import ANNUAL_FACTOR_BY_TF

def g_vol_high(direction, fire_us, *, asset, tf, vol_hurst_panel, **_kw) -> bool:
    row = vol_hurst_panel.lookup(asset, tf, fire_us)
    if row is None or row.rv_60 is None:
        return False
    thr = VOL_HIGH_RV60_THR.get((asset, tf))
    if thr is None:
        return False
    raw_rv = row.rv_60 / math.sqrt(ANNUAL_FACTOR_BY_TF[tf])   # de-annualize to match thr scale
    return raw_rv > thr
```

Same de-annualization in `g_vol_contracting`:
```python
    raw_rv = row.rv_60 / math.sqrt(ANNUAL_FACTOR_BY_TF[tf])
    return raw_rv < thr * 0.5
```

### Option B — store raw rv in the panel
Add a `rv_raw` field to `VolHurstRow` (the value before annualization) and have the gates read `row.rv_raw`. Cleaner long-term but touches the panel schema + its lockbox test.

**Recommendation: Option A** — smallest change, no panel schema churn, no lockbox-test edit. Keeps `rv_60` annualized for any consumer that genuinely wants annualized vol; only the two threshold-comparing gates de-annualize.

### Do NOT just annualize the thresholds
Multiplying the thresholds by √annual_factor would only be correct if the backtest SCORING also used annualized rv — but evidence (3) + (4) shows the backtest used raw rv. Annualizing the thresholds would NOT reproduce the backtest fire population. Option A reproduces the validated behavior.

---

## Validation required before deploy

This fix CHANGES which fires pass (real behavior change, not cosmetic). Before deploying:

1. **Confirm backtest scale**: locate the backtest scoring code that computed `VOL_HIGH_RV60_THR` p75 values. Confirm it used `sqrt(sum(log²)/60)` WITHOUT `× sqrt(annual_factor)`. (Strong circumstantial evidence already; confirm to be safe.)
2. **Re-validate the 11 affected sleeves** post-fix on the fire universe — the `g_vol_high` sleeves should drop to ~25% of current fire count (the vol filter becomes active); `g_vol_contracting` sleeve should go from 0 → its backtested fire count.
3. **Unit test**: assert `g_vol_high` returns False when raw_rv < thr (e.g., feed a low-vol window) and True when raw_rv > thr. Currently no such test catches the scale bug because it always returns True.

---

## Related — the OTHER rv path is VERIFIED CLEAN ✅

`_rv_60m` (sniper_v5_gates.py:1410) reads `regime_panel.realized_vol_60m` and compares against medians `0.0042` (BTC 5m) / `0.0055` (ETH 5m) in `g_BTC_vol_low` / `g_ETH_vol_low` / `g_J_btc_eth_vol_both_low` (V7 §3.5, V8 §3.2).

**VERIFIED 2026-05-27 — NO BUG here.** `regime_panel._compute_realized_vol_60m` (regime_panel.py:497) returns `math.sqrt(mean_sq)` with explicit code comment (line 150-151, 481-482):
```python
realized_vol_60m: float | None  # sqrt(mean(log_ret^2)) over last 60m
                                 # (None during warmup, raw not annualized)
```
> "NOT annualized — the V7 spec thresholds (BTC 5m=0.0042, ETH 5m=0.0055)"

The regime_panel author DELIBERATELY kept it raw to match the raw thresholds. Scale is consistent → these gates work correctly.

**This is the proof that vol_hurst is the one with the bug**: two parallel realized-vol implementations exist. `regime_panel` correctly kept raw to match raw thresholds. `vol_hurst` annualized (`× √annual_factor`) but its thresholds (`VOL_HIGH_RV60_THR`) are ALSO raw → mismatch. The fix is to make `vol_hurst`'s gate comparisons raw too (Option A), matching the already-correct `regime_panel` pattern.

---

## Acceptance criteria

1. ✅ `g_vol_high` returns False for below-p75-vol windows (currently always True)
2. ✅ `g_vol_contracting` returns True for low-vol windows (currently always False)
3. ✅ `btc_15m_btceth_diverg_stoch_volcontr_v8` starts placing fires (currently 0)
4. ✅ The 10 `g_vol_high` sleeves drop fire count toward backtest-validated levels
5. ✅ Unit tests cover both high-vol and low-vol cases at the correct scale
6. ✅ `regime_panel.realized_vol_60m` scale audited for the same class of bug

---

## Files
- `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_gates.py` — `g_vol_high` (line 616), `g_vol_contracting` (line 1775), `_rv_60m` (line 1410)
- `/opt/tradingvenue/backend/app/features/vol_hurst.py` — `rv_60` computation (line 187), `ANNUAL_FACTOR_BY_TF` (line 60)
- `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_thresholds.py` — `VOL_HIGH_RV60_THR` (line 38)
- `/opt/tradingvenue/backend/app/features/regime*.py` — `realized_vol_60m` (audit for same bug)

## END
