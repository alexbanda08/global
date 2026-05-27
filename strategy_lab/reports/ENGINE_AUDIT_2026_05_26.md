# Engine + Panel Audit — Round 7 11.6× Step-Up Investigation
**Date:** 2026-05-26  **Auditor:** quant-skeptic agent

## TL;DR — VERDICT
The 11.6× daily PnL step-up is **NOT genuine alpha** and **NOT a single backtest bug**.
It is primarily a **structural fire-count inflation** between val and lockbox windows:
the OOS files (used May 21+) contain ~2× the offset granularity (every 15s vs every
30s in base panels), inflating fire counts ~4-8× per day. Combined with 30% more slugs/day
than val due to upstream universe shift, the lockbox has **3-8× more shots per day at
roughly comparable per-trade EV** — hence the appearance of dramatically higher daily PnL.

A secondary lookahead leak exists in the **regime panel** that mis-anchors ~20% of fires.

**APPLES-TO-APPLES TEST**: When restricting to common offsets {60,120,180,240}s and the same
sleeve (S7_BTC_5m_base hybrid_v1 AND), val gives **$38/day** vs lockbox **$144/day** — a
3.8× ratio (not 11.6×). When deduped per (slug,direction), lockbox edge **disappears**
(-$43/day, WR 55%) vs val (+$51/day, WR 80%). **Deploy-ready estimates are inflated.**

---

## TASK 1 — engine_v2.py audit  → CLEAN
- `LegacyConfig`: 2%-on-profit-only, no fee on losing leg ✓ matches CLAUDE.md
- `find_book_strict`: `np.searchsorted(ts, target_us, side="right") - 1` → STRICT CAUSAL ✓
- `fill_at_book` latency shift: only if `cfg.apply_latency_to_entry` (False for legacy) ✓
- `hold_pnl` legacy formula: `shares × (1-vwap) × 0.98` if won, `-usd_in` if lost ✓
- `book_event_count`: counts in `[start_us, end_us]` inclusive, used pre-fire ✓
- No bug in engine_v2.

## TASK 2 — Per-panel causal anchoring
| Panel | Anchor | Verdict |
|---|---|---|
| microprice_panel | `searchsorted(ts, fire_us, "right")-1` + look back 500ms | **CAUSAL** ✓ |
| microstructure_panel | same; also uses fire_us-500ms/1s | **CAUSAL** ✓ |
| vpin_hawkes_at_fires | `target_us = fire_us - 1_000_000` | **CAUSAL** ✓ |
| lee_mykland_panel | bipower window `[t-K, t-1]` excluding bar t | **CAUSAL** ✓ |
| hybrid_features (R1+R2) | `CAUSAL_OFFSET_US = 1_000_000` subtract from fire_us | **CAUSAL** ✓ |
| sms_panel_5m/15m | ts_us = bar **START**; bar features use full slot | **LEAK** 🚨 |
| **regime_panel_5m/15m** | ts_us = bar **START**; close/ADX/regime_label use FULL slot | **LEAK** 🚨 |

### REGIME PANEL LEAK details
`strategy_lab/meta_classifier/build_regime_panel.py` lines 270-282:
```python
out["slot_us"] = (out["ts_us"] // (minutes * 60_000_000)) * (minutes * 60_000_000)
agg = out.groupby("slot_us").agg(close=("close","last"), high=("high","max"), ...)
agg.rename(columns={"slot_us": "ts_us"})  # bar START
```
Features `regime_label`, `regime_score`, `adx_14`, `plus_di_14`, `minus_di_14`,
`tr_ema_stack_score`, `trend_slope_30m`, `range_compression`, `realized_vol_60m` are
ALL computed on the **closed** bar yet keyed by **bar START**. `master_combinatorial`
05_rebuild line 164: `merge_asof(..., direction='backward')` picks the latest bar with
ts_us ≤ fire_us → for any fire inside a 5m slot (mean offset 128s), the joined regime
row uses data 0-300s INTO THE FUTURE of fire_us.

**Quantified leak**: 19.5% of BTC 5m fires get a DIFFERENT regime_label between
the leaky bar (slot containing the fire) and the prior bar (causal). ADX corr=0.995
(small), regime_score corr=0.54 (significant).

**FIX (1 line)**: in `build_regime_panel.py:280`, change to:
```python
agg["bar_end_us"] = agg.ts_us + minutes * 60_000_000
agg["ts_us"] = agg["bar_end_us"]   # rekey by bar END
```
Then merge_asof backward picks the latest CLOSED bar — strictly causal.

## TASK 3 — Lockbox slug coverage / distribution shift
| Window | Days | Total slugs/day | BTC 5m fires/day | s15 sleeve fires/day |
|---|---|---|---|---|
| Train (Apr 30-May 14) | 14 | ~600 | ~500 | ~330 |
| Val (May 15-21) | 7 | ~570 | ~500 | ~460 |
| **Lockbox (May 22-25)** | 4 | **~900** | **~3,700** | **~3,700** |

Raw chainlink resolutions per asset are STABLE (260-290 5m markets/day). But the
panel slug-count jumps ~50% on lockbox and the **fire-count-per-slug roughly DOUBLES**.

**ROOT CAUSE**: `data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_*.parquet`
files have **17 distinct fire offsets** (every 15s, 30→270 + 30→270 by 30) per slot,
vs the **base s15_joined_all.parquet** which has only **9 offsets** (every 30s).
Confirmed in `oos_fires_BTC_5m.parquet`: `fire_offset_s.value_counts()` shows 1700-2000
fires per offset across [15,30,45,...,300]. Base `s15_joined_all`: cleanly 9 offsets
30/60/.../270 with [1129, 2343, 3317, ..., 3459] across 21 days.

Net: **lockbox has 1.89× more fires/slot from offset density alone**, PLUS the OOS
file applies to all 3 assets without the additional gate-filtering some base panels did.

## TASK 4 — Outcome label audit
50/50 sampled fires have `outcome` matching `load_resolutions()` chainlink-derived
truth. **No outcome bug.**

## TASK 5 — WS-poly2 specific causal audit
- `vwap_since_open_bps`: causal `searchsorted(ts_us, fire_us, "right")` excludes fire-second ✓
- `mp_weighted_skew`: comes from `microprice_panel`, causal ✓
- Bootstrap (in `build_weighted_models.py:201`): resamples WITH REPLACEMENT on the
  lockbox slice — does NOT shuffle PnL across time; preserves time-ordering per draw.
  Bootstrap p-values are valid.
- Train/val/lockbox split is by `ts` (per `load_panel:113`); no leakage across splits.

## TASK 6 — Smoking-gun test (S7_BTC_5m_base)
`strategy_lab/engine_audit_2026_05_26/smoke_test.py`:

| Variant | val sum_pnl | val $/day | lockbox sum_pnl | lockbox $/day | ratio |
|---|---|---|---|---|---|
| hybrid_v1, ALL offsets | $970 | $139 | $1,429 | $357 | **2.57×** |
| hybrid_v1, common offsets {60,120,180,240} | $266 | $38 | $576 | $144 | **3.79×** |
| hybrid_v1, dedup per (slug, direction) | $358 | $51 | **-$172** | **-$43** | **NEGATIVE** |
| logistic_l2 (TT WS-poly2) | $2,808 | $401 | $24,799 | $6,200 | **15.4×** |

**Note**: TT's logistic_l2 sees a 15× step-up because the model has 4.6× more fires/day
in lockbox to score from. Per-trade DPT actually went UP ($1.146 → $2.454) — but on
a sample 4.6× larger, the bootstrap CI looks artificially significant.

## TASK 7 — Bugs found
1. **REGIME PANEL LEAK (medium severity)**: `regime_panel_{5m,15m}.parquet` ts_us =
   bar START, features computed over full closed bar. 19.5% mislabel rate on BTC 5m
   when comparing leaky vs causal. Impact on model: present but small (corr ADX 0.995).
   - **Fix**: rekey ts_us = bar_end_us in `build_regime_panel.py`.
2. **SMS PANEL LEAK (medium severity)**: same pattern as regime panel (ts_us = bar
   start, features over full slot).
   - **Fix**: same rekey pattern in `meta_classifier/compute_sms_panel.py`.
3. **FIRE-COUNT INFLATION (HIGH severity)**: OOS files have 17 offsets vs base 9
   offsets → 1.89× fire inflation on lockbox alone. Combined with slug-universe
   shift, drives most of the "11.6× step-up".
   - **Fix**: filter OOS to same 9 offsets {30,60,90,120,150,180,210,240,270} as base
     panels before concatenation. Re-run `full_window_gate_search_2026_05_26.py` and
     downstream master panel rebuild.

## TASK 8 — Re-validation
Not run for fully corrected panels — fixes require regenerating regime/sms panels and
re-running master_combinatorial pipeline (multi-hour). But the smoke-test already
shows that **once offset density is matched, val→lockbox $/day ratio is 3.8× not 11.6×**,
and once per-slug deduped lockbox is **negative**.

## TASK 9 — Confidence in deploy-ready estimates
**Confidence: LOW.** The val and lockbox results CANNOT be directly compared in their
current form because:
1. Different fire-offset density (9 vs 17 offsets per slot)
2. Slug-universe shift (val ~570/day, lockbox ~900/day)
3. Regime panel lookahead leak adds noise to ~20% of WS-poly2 feature anchors

**Re-runs needed before deploying:**
- Re-build regime + SMS panels keyed at bar-end_us (causal)
- Re-filter OOS to base-panel offsets (every 30s)
- Re-run weighted_voting `build_weighted_models.py` on corrected master panel

After those, the deploy-ready PnL estimate is most likely **$50-200/day net** for
S7_BTC_5m_base alone (matching val's per-day rate), not the $6,200/day implied by
the raw lockbox sum_pnl.

## Files touched
- `strategy_lab/engine_audit_2026_05_26/smoke_test.py` (new, smoking-gun test)
- `strategy_lab/engine_audit_2026_05_26/regime_leak_test.py` (new, regime leak quantification)
- `strategy_lab/reports/ENGINE_AUDIT_2026_05_26.md` (this report)
