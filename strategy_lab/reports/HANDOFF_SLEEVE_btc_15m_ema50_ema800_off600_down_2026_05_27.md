# Sleeve Handoff — `poly_sniper_v5_btc_15m_ema50_ema800_off600_down`

**Date:** 2026-05-27
**Sleeve:** V5 #12 — `BTC_15M_EMA50_EMA800_OFF600_DOWN_V5`
**Status:** Deployed in shadow (VPS3), $5 ramp-start

---

## 1. Definition

```
sleeve_id     = poly_sniper_v5_btc_15m_ema50_ema800_off600_down
asset         = BTC
tf            = 15m
direction     = DOWN
offsets       = (600,)        # single fire at 600s into the 900s window
window_s      = 900
spread_filter = 0.020         # same-token bid-ask (post-fix)
gates (all must pass):
  g_dir_down(direction)
  g_tr_above_ema50(direction="DOWN", asset="BTC")
  g_tr_above_ema800(direction="DOWN", asset="BTC")
```

Source: `SHADOW_DEPLOY_SPEC_2026_05_27.md` §Sleeve 12. Gate stack = `g_tr_above_ema50 | g_tr_above_ema800` (+ dir_down).

**Logic**: DOWN bet on BTC 15m, fired late (600s into window), when price is above both EMA50 and EMA800 — a stretched-trend exhaustion fade. Single offset, single direction = max 1 fire per slot.

---

## 2. Backtest metrics — all tests

### 2a. Original lockbox (held-out test set, $25 stake)
| Metric | Value |
|---|---|
| n | 64 |
| WR | 76.6% |
| $/tr | **+$6.26** |
| Max DD | $50 |
| Max losing streak | 2 |
| Bootstrap p-value | 0.004 (significant) |

Source: `SHADOW_DEPLOY_SPEC_2026_05_27.md:574`. This is the selective held-out sub-population that justified deployment.

### 2b. Full-universe overlap audit (33 days, all fires)
| Metric | Value |
|---|---|
| n | 917 |
| WR | 76.34% |
| $/tr (dpt) | +$1.069 |
| Sum PnL | +$980.68 |
| 28d projection | +$832.09 |
| Days active | 33 |

Source: `sniper_search_2026_05_27/_overlap_audit_v5_v6_v7/sleeve_summary.csv:2`.

⚠ **Note the gap**: lockbox $/tr +$6.26 (n=64, cherry sub-population) vs full-universe +$1.07 (n=917). WR is consistent (~76%) across both — the per-trade gap is the broad universe including lower-edge fires. Honest live expectation: closer to **+$1.07/tr** than +$6.26.

### 2c. Exit-policy research (n=199 sample)
| Policy | WR% | Mean $/tr | Total $ | Δ vs HOLD |
|---|---:|---:|---:|---:|
| **HOLD** (baseline) | 77.9% | +$2.315 | +$460.63 | — |
| **HEDGE_LATE** | 76.9% | +$2.709 | +$539.16 | **+$0.395** ★ |
| HEDGE_REVERSAL | 52.8% | −$0.451 | −$89.82 | −$2.766 |
| SELL_TP_0_85 | 40.7% | +$1.159 | +$230.59 | −$1.156 |
| SELL_SL_0_30 | 64.3% | −$0.229 | −$45.65 | −$1.388 |

Source: `EXIT_POLICY_RESEARCH_2026_05_27.md` Sleeve 3 + `exit_policy_results_2026_05_27.csv:4`.

★ **UNIQUE FINDING**: this is the **ONLY sleeve in the entire 56-sleeve fleet where HEDGE_LATE beats HOLD** (+$0.395/tr). Hypothesis: 15m slots (900s) have a long adversarial-drift tail that HEDGE_LATE cuts; 5m slots don't. All other sleeves prefer HOLD.

---

## 3. Live shadow status (VPS3, 2026-05-27)

| Metric | Value |
|---|---|
| Events today (local snapshot) | 19 |
| Placed | 0 |
| Spread-rejected (cross-token, pre-fix) | 17 |
| Gate-rejected (ema50/ema800 False) | 2 |

The local jsonl snapshot predates the spread-definition fix — all rejections are old cross-token format (`spread_too_wide__>_`). Post-fix (bid-ask spread, deployed) this sleeve should start placing. Morning VPS3 audit showed 11 evals / 0 placed for the same reason.

**Action**: re-pull VPS3 jsonl after a few hours of post-fix runtime to confirm it places.

---

## 4. Spread-loosen test verdict

From `SPREAD_LOOSEN_SIM_BTC_5M_2026_05_27.md` (BTC 5m) — BTC 15m was not separately loosen-tested, but BTC borderline band (0.020→0.025) showed **WR 46.8% / $/tr −$0.39** on marginal fires. **Verdict: KEEP at 0.020.** No VL variant created for this sleeve.

---

## 5. Deploy recommendations

1. **Keep spread_filter at 0.020** — loosening hurts BTC.
2. **Consider HEDGE_LATE override** — this is the single best HEDGE_LATE candidate in the fleet (+$0.395/tr). If TV adds a per-sleeve exit-policy flag, this sleeve is the prime test case. Not a default; opt-in for 15m.
3. **Honest $/tr expectation ≈ +$1.07** (full universe), not the +$6.26 lockbox figure.
4. **WR is robust ~76-78%** across all three test methods — high confidence in directional edge.
5. **Low volume** — single offset / DOWN-only → ~1 fire per qualifying slot. n=917 over 33 days ≈ 28 fires/day max universe; far fewer after gates.

---

## 6. Source files
- `strategy_lab/reports/SHADOW_DEPLOY_SPEC_2026_05_27.md` (§Sleeve 12, definition + lockbox)
- `strategy_lab/sniper_search_2026_05_27/_overlap_audit_v5_v6_v7/sleeve_summary.csv` (full-universe)
- `strategy_lab/reports/EXIT_POLICY_RESEARCH_2026_05_27.md` (exit policies)
- `strategy_lab/reports/exit_policy_results_2026_05_27.csv` (raw exit numbers)
- `strategy_lab/v5_live_2026_05_27.jsonl` (live shadow, pre-fix snapshot)

## END
