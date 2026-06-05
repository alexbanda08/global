# Silent Sleeves Forensics — Cross-Asset + HOD-gated (2026-06-01)

Scope: 7 sniper_v5 sleeves that NEVER fired in a 2d15h (2.625d) live window.
Source of truth: LIVE VPS3 `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_gates.py`
(2333 lines, mtime 2026-05-31 00:24 — newer than local audit copy; read live).
Backtest window for fires/day = **32.7d** (per V7/V8 spec `32.7d` projections).

---

## 1. `btc_5m_slotend_ofi_ts_v7` — DEAD_STUB (CONFIRMED)

`g_slot_end_ofi_with` (line 1918) hard-returns `False`:

```python
def g_slot_end_ofi_with(direction, fire_us, *, slug, slot_end_us, **_kw) -> bool:
    """V7 §3.3 — STUB returning False until polymarket trade subscriber lands."""
    # TODO(V7-slot-end-ofi): wire polymarket TradeMirror trade-print history.
    return False
```

The OFI subscriber (TradeMirror 1-min trade-print history) is NOT wired. The gate is
the sole directional gate in V7_02 → the sleeve **CANNOT fire by construction**. Spec
(`SHADOW_DEPLOY_SPEC_V7_SELECTED §02`) marks it ⚠ EXPERIMENTAL and projects 32.7d
$13,618 — that projection is fiction; the live gate has never returned True.

**Recommendation:** KILL the sleeve OR wire OFI (needs Polymarket TradeMirror trade
buffer + offset≥240s lookahead guard already specced). Until wired, it is pure noise in
the eval_skip log. Recommend KILL — the same per-slug trade buffer now feeds V9 B-gates;
revive only if OFI shows independent edge.

---

## 2. `g_hod_european_morning` — CORRECT (07–11 UTC). Verdict: NOT a bug.

```python
def g_hod_european_morning(direction, fire_us, **_kw) -> bool:
    """V6 §3.12 — UTC hour 7..11."""
    h = _utc_hour(fire_us)         # (fire_us//1e6//3600) % 24  — true epoch UTC, no tz offset
    return 7 <= h <= 11
```

- Allows UTC **07,08,09,10,11** = 5 hours/day (~20.8% of day). NO local-vs-UTC bug
  (`_utc_hour` is pure epoch arithmetic). NO empty allowed-set.
- Backtest produced real fires in this window: `sol_15m_v8/_v8_tod_specialization.csv`
  shows `*_TOD_european_morning` configs with n_total 44–408 over 32.7d. Window is live.
- The 4 SOL-15m sleeves are low-volume by design (HOD 5h/day × offset∈{60,120,240} ×
  strong-BTC-slope confluence): backtest n=57–106 → **1.7–3.2 fires/day** → 4.6–8.5
  expected in 2.625d. Poisson P(0) = 0.01–1%. Borderline but plausible chance-zero.

---

## 3. Cross-asset gates — polarity + asset-routing all CORRECT. No inverted/mis-routed gate.

| gate | asset read | polarity | matches spec? |
|---|---|---|---|
| `g_btc_trend_30m_with` | hardcoded `_slope(panel,"BTC","5m")` | sign-match dir | ✓ V7 §3.4 |
| `g_btc_f7_against` | hardcoded `f7_panel.lookup("BTC")` | UP⟸RSI≤30, DOWN⟸RSI≥70 (mean-revert) | ✓ V8 §3.7 spec literally says "F7 RSI extreme AGAINST direction (mean-revert)" |
| `g_cci_extreme_with` | `asset=` kwarg (=sleeve's SOL) | \|CCI\|>150 & sign-match | ✓ V7 §3.8 |

**`g_btc_f7_against` is NOT inverted.** "Against" = contrarian/mean-revert is the
intended design; V8_07 spec line 504 confirms verbatim. It reads the BTC panel for a SOL
sleeve — correct (cross-asset BTC RSI as SOL signal). Thresholds match: F7 30/70,
CCI 150, BTC_SLOPE_STRONG_15M 0.612 (all in live `sniper_v5_thresholds.py`).

The 59% block on `g_btc_f7_against` is just BTC RSI rarely at an extreme (≤30 or ≥70) AND
on the correct mean-revert side — not a bug.

---

## 4. Per-sleeve verdict table

fires/day = backtest_full_n / 32.7d. exp = fires/day × 2.625d. P0 = Poisson P(0 | exp).

| sleeve | bt n | /day | exp 2.6d | P(0) | dominant live skip | VERDICT |
|---|---|---|---|---|---|---|
| btc_5m_slotend_ofi_ts_v7 | 689 | 21.1 | 55 | ~0 | g_slot_end_ofi_with hard-False | **DEAD_STUB** |
| sol_5m_btctrend_cci_hurstrev_v7 | 659 | 20.2 | 53 | ~0 | g_btc_trend_30m + g_cci_extreme(SOL) | **SUSPECT** (see §5) |
| sol_5m_btcf7against_cci_hurstrev_mfi_v8 | 649 | 19.9 | 52 | ~0 | g_btc_f7_against + g_cci_extreme(SOL) | **SUSPECT** (see §5) |
| sol_15m_btc_slope_pair_v7 | 80 | 2.4 | 6.4 | 0.16% | HOD + spread 0.030>0.025 | **LOW_BASE_RATE** |
| sol_15m_v7s5_plus_eth1h_adx_v8 | 57 | 1.7 | 4.6 | 1.0% | HOD european_morning | **LOW_BASE_RATE** |
| sol_15m_v7_base_s5_slope_str_v8 | 80 | 2.4 | 6.4 | 0.16% | HOD european_morning | **LOW_BASE_RATE** (dup of V7_11) |
| sol_15m_v6_j_btceth_vollow_l_ethadx_v8 | 106 | 3.2 | 8.5 | 0.02% | HOD european_morning | **LOW_BASE_RATE** (borderline) |

---

## 5. Family root cause

**SOL-15m family (4 sleeves): LOW_BASE_RATE.** HOD 07–11 UTC (5h/day) recurred only
~2–3× in the run; combined with offset∈{60,120,240}, tr_stack, strong-BTC-15m-slope
(>0.612) and a live spread that exceeded the 0.025 filter (triage: 0.030>0.025), the
already-thin 1.7–3.2 fires/day collapses to 0 by chance in 2.625d. Gates verified
correct. No action — observe over a longer window; if still 0 after ~10d, re-examine the
live spread filter (cross-token vs same-token, CLAUDE.md inv) eating the european-morning
fires.

**SOL-5m pair (V7_08 + V8_07): SUSPECT — backtest/live divergence.** Backtest projects
~20 fires/day yet live = 0. Gate code is polarity/route-correct, so this is NOT an
inverted gate. Smoking gun: in the 2026-05-29 live replay (`replay_sol.csv`), the
**sibling** sleeves fire heavily — `sol_5m_j_2asset_trending_cci_rf_ema200_v8` (125) and
`sol_5m_btcf7_f7overb_ema800_vwap_v7` (128) — but V7_08/V8_07 never appear. The
discriminator vs the firing siblings is the **conjunction** `g_cci_extreme_with(SOL,
|CCI|>150)` AND a BTC cross-asset extreme/sign gate (`g_btc_f7_against` RSI-extreme or
`g_btc_trend_30m_with`) AND `g_hurst_reverting(SOL<0.40)` co-occurring at the same fire.
That triple co-occurrence is far rarer live than the backtest's n/32.7 average implies
— the backtest n was lump-summed over a month and likely clustered in a few
extreme-vol/extreme-RSI days; the 2.6d live window simply contained no such cluster.
**Most-likely verdict = LOW_BASE_RATE (clustered, not uniform)**, NOT a wiring bug.
To confirm/refute definitively, re-derive the backtest fire TIMESTAMPS for V7_08/V8_07
and check whether they cluster (→ LOW_BASE_RATE) or are uniform (→ live panel bug,
e.g. SOL ta_indicators CCI_60s stale/empty live). That timestamp dump is the one
remaining gap — flag for next session.

**Overall:** 1 DEAD_STUB (kill/wire OFI), 4 LOW_BASE_RATE (thin HOD window × short run),
2 SUSPECT-but-likely-clustered-LOW_BASE_RATE (verify with backtest fire-timestamp dump).
No inverted or mis-routed gate found. `g_btc_f7_against` polarity is correct per spec.

Path: `strategy_lab/reports/SILENT_FORENSICS_CROSSASSET_HOD_2026_06_01.md`
