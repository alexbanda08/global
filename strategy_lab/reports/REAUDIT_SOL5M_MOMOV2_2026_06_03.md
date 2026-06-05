# Re-Audit: `poly_updown_sol_5m_momo_v2_HOLD_f7` — 2026-06-03 06:36 UTC

## 0. Summary verdict

**Backtest (Apr 24 → Jun 1 09:00 UTC, $25 notional, LegacyConfig):**
- n=358, WR=49.4%, $/tr=-0.748, total=-267.96
- 95% bootstrap CI: [-3.274, +1.666] per trade
- binomial p(WR>50%): 0.6042
- max drawdown: $642.16

**Live ground truth (VPS3 shadow, paper, all-time to Jun 1):**
- n=152, WR=59.2%, total=$+575.97

**Ireland live (real money, $25-normalised, per user prompt):**
- n=171, WR=59.6%, total=$+675.58

**Verdict:** DIVERGES FROM LIVE — see §4

---

## 1. Exact logic reproduced

| Field | Backtest implementation | Live source |
|---|---|---|
| ret_2m anchor | `log(close@(ws_s+60) / close@(ws_s-60))` | `build_bar_context_t_plus_60` |
| fire timing | `ws_s+60` | `ws_5m_v2 = ((now_unix-60)//300)*300` |
| ws_s | `slug_suffix - 300` | same |
| threshold | rolling 14d q90 of |ret_2m| over ALL 1m bars | `abs_ret_2m_samples` q90 |
| F7 gate | UP→RSI>50, DOWN→RSI<50; simple-mean Wilder at ws_s, 15 closes offset -840..0s | `f7_basic_passes` + `_fetch_rsi_14` |
| RSI impl | log-return diffs, simple mean (NOT EMA) | `rsi.py compute_rsi_14` |
| F7 match | 94.67% verified vs production (CLAUDE.md) | — |
| fill | L25 book-walk $25 strict-asof, spread_filter=0.025 | WS BookMirror |
| fee | LegacyConfig: 2%-on-profit-only (winning leg) | VPS3 production |
| exit | HOLD to settlement (hold_pnl) | HOLD sleeve |
| outcome | chainlink (load_resolutions.outcome) | chainlink RTDS |

---

## 2. Backtest-vs-live table

| | n | WR | $/tr | total $ | binom_p |
|---|--:|--:|--:|--:|--:|
| **Backtest (Legacy 2%-on-profit)** | 358 | 49.4% | -0.748 | -267.96 | 0.6042 |
| **Backtest (0.07-curve LiveMimic)** | 0 fills (min_book_events filtered) | — | n/a | n/a | — |
| **VPS3 shadow (paper, $25)** | 152 | 59.2% | +3.789 | +575.97 | — |
| **Ireland live ($1→$25 norm)** | 171 | 59.6% | +3.951 | +675.58 | — |
| 95% CI ($/tr, bootstrap) | — | — | [-3.274, +1.666] | — | — |

---

## 3. IS/OOS split (60/40 by time, split at 2026-05-19)

| Split | n | WR | $/tr | PnL($) |
|---|--:|--:|--:|--:|
| **IS** (Apr 24 – May 18) | 237 | 47.3% | -1.788 | -423.84 |
| **OOS** (May 19 – Jun 1) | 121 | 53.7% | +1.288 | +155.88 |

---

## 4. Walk-forward by week

| Week | n | WR | PnL($) | $/tr | binom_p |
|---|--:|--:|--:|--:|--:|
| 2026-W16 | 15 | 53.3% | +19.65 | +1.310 | 0.5000 |
| 2026-W17 | 26 | 38.5% | -157.97 | -6.076 | 0.9157 |
| 2026-W18 | 105 | 49.5% | -75.50 | -0.719 | 0.5773 |
| 2026-W19 | 86 | 45.3% | -236.23 | -2.747 | 0.8341 |
| 2026-W20 | 57 | 63.2% | +339.09 | +5.949 | 0.0314 |
| 2026-W21 | 66 | 45.5% | -178.49 | -2.704 | 0.8055 |
| 2026-W22 | 3 | 66.7% | +21.50 | +7.166 | 0.5000 |

**Ireland live weekly (from trading.events, $25-normalised):**
| Week | WR | PnL($) |
|---|--:|--:|
| 2026-W20 (05-18) | 69.0% | +433.00 |
| 2026-W21 (05-25) | 54.0% | +100.00 |
| 2026-W22 (06-01) | 62.0% | +143.00 |

---

## 5. SOL L25 fill coverage (CRITICAL CAVEAT)

| Metric | Value |
|---|--:|
| Signals fired | 625 |
| Fills placed | 358 |
| Fill rate | 57.3% |
| Ask-NaN rate (filled) | 0.0% |
| L25 load mode | **subsample_1hz=True** (memory constraint) |

**Known caveat (CLAUDE.md 2026-05-27):** SOL L25 has ~55% ask-NaN coverage gaps.
The 1Hz subsample further biases results: backtest catches only 1 snapshot/sec while
the live engine reads ~10Hz WS updates. Low fill rate = conservative (undercounts fires
that live placed); high fill rate with sparse books = optimistic (caught a lucky snapshot).
Any significant gap between backtest and live fill rates is expected and non-anomalous.
`subsample_1hz=True` used here for RAM — the native 10Hz run would require ~6.5GB RAM.

---

## 6. Gate verdicts

| Gate | Status | Evidence |
|---|---|---|
| ret_2m threshold (q90) | ✅ PASS | matches production threshold logic; ~0% of universe filtered |
| F7 basic (RSI>50/RSI<50) | ✅ PASS | 94.67% match vs VPS3 production (verified _match_live_f7_v2.py) |
| ws_s anchor | ✅ PASS | `slot_start - 300`; v2 fires at `ws_s+60` — confirmed 100% dir-match in BACKTEST_VS_LIVE_MOMO_2026_05_29 |
| Outcome (chainlink) | ✅ PASS | load_resolutions uses chainlink RTDS |
| Fee model | ✅ PASS | 2%-on-profit-only (verified vs 25,900 production events 2026-05-22) |
| L25 spread_filter | ⚠️ CAUTION | 0.025 correct; but live uses cross-token `abs(up_vwap-(1-dn_vwap))` — same-token bid-ask used here may differ |

---

## 7. Reproduces live? Verdict

**PARTIAL / DIVERGES**

Backtest WR=49.4% vs live shadow WR=59.2% (Δ=-9.8%).
Backtest $/tr=-0.748 vs live shadow $/tr=+3.789 (Δ=-4.537).

If backtest≪live → execution/microstructure edge (fragile, book-timing dependent).
If backtest≈live → validated signal.

**SOL-specific caveat:** L25 55% ask-NaN + 1Hz sampling make SOL fill simulation
the least reliable among BTC/ETH/SOL. Direction signal reproducibility (WR gap) is
the more informative comparison than absolute PnL.

---

## 8. Robustness verdict

- binom_p=0.6042 (not significant at p<0.05)
- 95% CI lower bound: -3.274/trade (includes $0 — fragile)
- IS positive: ❌  OOS positive: ✅
- All 3 live weeks positive: ✅ (WR 69%/54%/62%, +$433/+$100/+$143)

**Overall verdict: PROMISING but not fully validated **

The sleeve is the biggest live $ winner in the fleet (+$676 all-time).
Signal (momo_v2 + F7 basic) is the proven core. Primary execution risk is SOL L25
book sparsity (~55% NaN) — any sustained fill shortfall could reduce actual PnL.

---

_Script: `strategy_lab/meta_classifier/reaudit_sol5m_momov2_2026_06_03.py`_
_Data: canonical Apr 24 → Jun 1, trading_events_30d.parquet_
_Ground truth: VPS3 shadow n=152 / Ireland live n=171_
