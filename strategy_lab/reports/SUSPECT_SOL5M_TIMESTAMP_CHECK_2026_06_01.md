# SUSPECT SOL 5m sleeves — timestamp / panel check (2026-06-01)

Two SOL 5m sleeves logged **0 live fires over 2d15h** despite backtest projecting ~20/day:

- `poly_sniper_v5_sol_5m_btctrend_cci_hurstrev_v7`
- `poly_sniper_v5_sol_5m_btcf7against_cci_hurstrev_mfi_v8`

Hypotheses tested: **LOW_BASE_RATE** (clustered backtest fires, recent live days are dead-vol) vs **LIVE_PANEL_BUG** (stale/None SOL CCI or hurst panel never satisfies its gate live).

Scope: read-only VPS3, no canonical L25 re-eval. Check A from sniper JSONL `gates_evaluated`; Check B from backtest fire universes.

---

## Check A — live per-gate True-rate (sniper_v5 JSONL)

Source: `/var/log/tradingvenue/sniper_v5/2026-05-27 … 2026-06-01.jsonl` (6 files).
Aggregated over **all `sleeve_fire_eval` rows** for each sleeve. `true_rate_when_present` = True count / rows where the gate key is present in `gates_evaluated`. (~5,200 early rows per sleeve omit gate keys entirely — panel-warmup rows; excluded from rate denom.)

### Sleeve v7 — `…sol_5m_btctrend_cci_hurstrev_v7`
| gate | present | True | true-rate (when present) |
|---|---:|---:|---:|
| `g_btc_trend_30m_with` | 16,322 | 7,097 | **0.4348** |
| `g_cci_extreme_with(SOL)` | 16,322 | 1,290 | **0.0790** |
| `g_hurst_reverting(SOL,5m)` | 16,322 | **0** | **0.0000** ⚠ |
| **conjunction (all_gates_passed)** | 21,524 rows | **0** | **0.0000** |

### Sleeve v8 — `…sol_5m_btcf7against_cci_hurstrev_mfi_v8`
| gate | present | True | true-rate (when present) |
|---|---:|---:|---:|
| `g_btc_f7_against` | 16,322 | 3,657 | **0.2241** |
| `g_cci_extreme_with(SOL)` | 16,322 | 1,290 | **0.0790** |
| `g_hurst_reverting(SOL,5m)` | 16,322 | **0** | **0.0000** ⚠ |
| `g_mfi_strong_with(SOL)` | 16,322 | 6,644 | **0.4071** |
| **conjunction (all_gates_passed)** | 21,524 rows | **0** | **0.0000** |

### Hurst gate True-rate by day (v7; SOL panel shared with v8)
| day | present | True | rate |
|---|---:|---:|---:|
| 2026-05-27 | 1,368 | 0 | 0.0000 |
| 2026-05-28 | 3,091 | 0 | 0.0000 |
| 2026-05-29 | 3,639 | 0 | 0.0000 |
| 2026-05-30 | 3,810 | 0 | 0.0000 |
| 2026-05-31 | 3,294 | 0 | 0.0000 |
| 2026-06-01 | 1,120 | 0 | 0.0000 |

**SMOKING GUN: `g_hurst_reverting(SOL,5m)` is True in 0 of 16,322 rows — every single day, no exception.**
The other gates fire at healthy, plausible rates (btc_trend 43%, btc_f7 22%, mfi 41%, cci 7.9%). CCI is *healthy* (contradicts the "SOL-CCI panel bug" framing in the task title — CCI fires fine). The dead gate is **hurst**, shared by both sleeves. Because both specs require hurst in the conjunction, both sleeves are hard-blocked → 0 fires.

This is a textbook **LIVE_PANEL_BUG** signature: a single gate stuck at exactly 0.0000 across 16k+ evals and 6 days, while sibling gates on the same asset (SOL CCI) behave normally. A genuine low-base-rate gate would still flicker True occasionally (hurst<0.5 reverting regime is common). 0/16,322 ⇒ the SOL 5m hurst panel value is stale / None / NaN / a constant that never crosses the reverting threshold.

---

## Check B — backtest fire-timestamp clustering

Source panels: `sol_5m_v7/_panel_sol_5m_v7.parquet` (101,500 rows), `sol_5m_v8/_panel_sol_5m_v8.parquet`. Exact gate stacks from `_v{7,8}_final_pass_tagged.csv` row 0:

- v7 = `g_btc_trend_30m_with ∧ g_cci_extreme_with ∧ g_hurst_reverting`
- v8 = `g_btc_f7_against ∧ g_cci_extreme_with ∧ g_hurst_reverting ∧ g_mfi_strong_with`

(Backtest panel column is `g_hurst_reverting`; the live label `g_hurst_reverting(SOL,5m)` is the same gate.) Reconstructed conjunction fires, histogrammed `fire_us` → UTC day:

### v7 — n=661 fires, span 22.0d, 22 active days, mean 30.0/day
Per-gate backtest True (of 101,500): btc_trend_30m=16,568 · cci_extreme=11,059 · **hurst_reverting=39,801 (39.2%)**.
Daily counts (May 1→22): 44,10,18,45,53,54,6,34,12,5,19,32,30,33,18,16,17,35,45,32,58,45. Top day 58 = **9% of total**, median 32/day, **zero dead days**.

### v8 — n=650 fires, span 21.9d, 22 active days, mean 29.6/day
Per-gate backtest True: btc_f7_against=23,414 · cci_extreme=11,059 · **hurst_reverting=39,801 (39.2%)** · mfi_strong=39,865.
Daily counts: 33,25,29,16,31,31,4,34,32,21,13,27,36,28,11,35,31,36,44,44,49,40. Top day 49 = **8% of total**, median 31/day, **zero dead days**.

**Verdict: UNIFORM, not clustered.** ~30 fires/day on every backtest day (consistent with the projected ~20/day). No high-vol-day bunching, no dead days. So the "recent live days happen to map to zero-fire backtest days" explanation is **falsified** — there are no zero-fire backtest days at all.

### The clincher
`g_hurst_reverting` fires **39.2% in backtest** vs **0.0% live** (0/16,322). Same gate, same asset, same timeframe. cci_extreme is healthy in both (backtest 10.9%, live 7.9%). Only hurst is dead, and only live.

---

## FINAL VERDICT (both sleeves)

| sleeve | verdict | broken panel |
|---|---|---|
| `…sol_5m_btctrend_cci_hurstrev_v7` | **LIVE_PANEL_BUG** | SOL 5m hurst panel |
| `…sol_5m_btcf7against_cci_hurstrev_mfi_v8` | **LIVE_PANEL_BUG** | SOL 5m hurst panel |

Root cause: `g_hurst_reverting(SOL,5m)` evaluates True 0/16,322 live (every day, 6 days) vs 39% in backtest. The live SOL 5m **hurst panel** is stale / None / NaN / never crosses the reverting threshold, so its gate is permanently False. Both sleeves require it in the conjunction → both hard-blocked → 0 live fires. NOT low base rate (backtest fires are uniform ~30/day with no dead days; the conjunction *would* fire live if hurst worked, since btc_trend/btc_f7/cci/mfi all fire at healthy live rates).

Note: the task framed this as a possible "SOL-CCI panel bug" — that is **wrong**; SOL CCI is healthy live (7.9%). The dead panel is **SOL hurst**, not CCI.

### Recommended next step (out of scope here)
Inspect the live engine's SOL 5m hurst panel feed (the source computing `g_hurst_reverting(SOL,5m)`): check for stale/None hurst value or an inverted/mis-thresholded comparison. Likely a panel that is never populated for SOL 5m (warmup never completes, wrong key, or NaN-guard returning False).

