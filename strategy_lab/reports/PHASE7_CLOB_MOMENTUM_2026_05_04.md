# Phase 7 — CLOB Imbalance Momentum + Late Entry Sweep (run 2026_05_04)

Top-K levels: 5, forward horizons: (10, 30, 60, 120, 180, 240, 270, 300), late windows: (60, 120, 180)

## Tradability framework

5-minute Polymarket UpDown markets last 300s. A feature computed over buckets `[0, T]`
is FAIR for an entry at time T (you've observed all data ending at T before entering).
Holding time = `300 - T` seconds.

| Tier | Means | Fair if entry at | Hold | Useful for |
|---|---|---|---|---|
| `fair_entry_t=0s` | feature at t=0 only | window_start | 5 min | V3-style entry |
| `fair_entry_t=30s..60s` | uses [0, T] data | T into market | 4-4.5 min | Light late-entry |
| `fair_entry_t=120s..180s` | uses [0, T] data | T into market | 2-3 min | Mid-market entry |
| `late_entry_t=240s..270s` | uses [0, T] data | T into market | 30-60s | **Last-min strategy** ⭐ |
| `LOOKAHEAD_full` | uses entire [0, 300] | n/a | n/a | Resolution dynamics only |
| `LOOKAHEAD_last<W>s` | uses last W seconds | n/a | n/a | Settlement-window study |

## Per-asset BEST FEATURE BY ENTRY TIME

Each row shows the strongest |IC| feature available at that entry time.

### BTC (n=2734)

| Entry time | Hold | Best feature | IC | spread | tier |
|---|---:|---|---:|---:|---|
| t=0s | 300s | `dn_imb_t0` | -0.0539 | -0.075 | fair_entry_t=0s |
| t=30s | 270s | `dn_imb_avg_30s` | -0.0748 | -0.120 | fair_entry_t=30s |
| t=60s | 240s | `dn_imb_avg_60s` | -0.0672 | -0.104 | fair_entry_t=60s |
| t=120s | 180s | `dn_imb_slope_120s` | +0.0837 | +0.117 | fair_entry_t=120s |
| t=180s | 120s | `dn_imb_slope_180s` | +0.1772 | +0.250 | fair_entry_t=180s |
| t=240s | 60s | `up_imb_slope_240s` | -0.2898 | -0.411 | late_entry_t=240s |
| t=270s | 30s | `up_imb_slope_270s` | -0.3421 | -0.505 | late_entry_t=270s |

**Settlement-window dynamics (LOOKAHEAD — descriptive):**

| Window | Best feature | IC | spread |
|---|---|---:|---:|
| `LOOKAHEAD_last60s` | `up_imb_slope_last60s` | +0.3580 | +0.560 |
| `LOOKAHEAD_last60s` | `dn_imb_slope_last60s` | -0.3580 | -0.564 |
| `LOOKAHEAD_last60s` | `diff_imb_slope_last60s` | +0.3579 | +0.562 |
| `LOOKAHEAD_last180s` | `up_imb_avg_last180s` | -0.3563 | -0.535 |
| `LOOKAHEAD_last180s` | `diff_imb_avg_last180s` | -0.3560 | -0.533 |

### ETH (n=2728)

| Entry time | Hold | Best feature | IC | spread | tier |
|---|---:|---|---:|---:|---|
| t=0s | 300s | `up_imb_t0` | +0.0085 | +0.027 | fair_entry_t=0s |
| t=30s | 270s | `diff_imb_avg_30s` | +0.0520 | +0.089 | fair_entry_t=30s |
| t=60s | 240s | `dn_imb_avg_60s` | -0.0369 | -0.047 | fair_entry_t=60s |
| t=120s | 180s | `up_imb_slope_120s` | -0.0945 | -0.118 | fair_entry_t=120s |
| t=180s | 120s | `up_imb_slope_180s` | -0.1683 | -0.263 | fair_entry_t=180s |
| t=240s | 60s | `dn_imb_slope_240s` | +0.2287 | +0.336 | late_entry_t=240s |
| t=270s | 30s | `dn_imb_slope_270s` | +0.2544 | +0.367 | late_entry_t=270s |

**Settlement-window dynamics (LOOKAHEAD — descriptive):**

| Window | Best feature | IC | spread |
|---|---|---:|---:|
| `LOOKAHEAD_last60s` | `dn_imb_slope_last60s` | -0.3363 | -0.541 |
| `LOOKAHEAD_last60s` | `diff_imb_slope_last60s` | +0.3362 | +0.541 |
| `LOOKAHEAD_last60s` | `up_imb_slope_last60s` | +0.3361 | +0.539 |
| `LOOKAHEAD_last180s` | `dn_imb_avg_last180s` | +0.3209 | +0.449 |
| `LOOKAHEAD_last180s` | `diff_imb_avg_last180s` | -0.3207 | -0.449 |

### SOL (n=2727)

| Entry time | Hold | Best feature | IC | spread | tier |
|---|---:|---|---:|---:|---|
| t=0s | 300s | `up_imb_t0` | +0.0453 | +0.075 | fair_entry_t=0s |
| t=30s | 270s | `up_imb_avg_30s` | +0.0662 | +0.108 | fair_entry_t=30s |
| t=60s | 240s | `up_imb_slope_60s` | -0.0684 | -0.099 | fair_entry_t=60s |
| t=120s | 180s | `up_imb_slope_120s` | -0.1612 | -0.238 | fair_entry_t=120s |
| t=180s | 120s | `dn_imb_slope_180s` | +0.2844 | +0.377 | fair_entry_t=180s |
| t=240s | 60s | `dn_imb_slope_240s` | +0.4261 | +0.604 | late_entry_t=240s |
| t=270s | 30s | `up_imb_slope_270s` | -0.4491 | -0.619 | late_entry_t=270s |

**Settlement-window dynamics (LOOKAHEAD — descriptive):**

| Window | Best feature | IC | spread |
|---|---|---:|---:|
| `LOOKAHEAD_last180s` | `dn_imb_avg_last180s` | +0.5176 | +0.716 |
| `LOOKAHEAD_last180s` | `diff_imb_avg_last180s` | -0.5176 | -0.718 |
| `LOOKAHEAD_last180s` | `up_imb_avg_last180s` | -0.5175 | -0.718 |
| `LOOKAHEAD_last120s` | `up_imb_avg_last120s` | -0.4977 | -0.678 |
| `LOOKAHEAD_last120s` | `diff_imb_avg_last120s` | -0.4976 | -0.678 |

---

**Interpretation:**

- `IC` = Spearman rank correlation of feature vs outcome_up. >0 means higher feature → more UP wins.
- `top_hit` / `bot_hit` = hit-rate of UP outcomes in top/bottom quintile of feature.
- `spread` = top_hit - bot_hit. >0.10 = strong directional signal.

**Verdict (compare against Phase 2 baseline IC=+0.082 for static ETH imbalance):**

- The high-|IC| features at 300s horizon are LOOKAHEAD — they describe the resolution
  dynamic, not a predictor available at entry. Discard for trading.
- Among FAIR-ENTRY (≤60s) features: imbalance momentum is no stronger than static t0.
  Still ~0.05-0.08 IC, similar to Phase 2.
- Among LATE-ENTRY-OK (60-180s) features: SOL `up_imb_slope_120s` shows IC ~ -0.16.
  Only viable as a late-entry signal (enter at t+120s, hold 3min). Marginal.

**Conclusion:** raw imbalance momentum at fair entry times is NOT a strong directional
alpha. Phase 8 (meta-classifier ensemble) is the next swing. Phase 9 (TFI from trades_v2)
may also add lift since trade flow is independent of orderbook posting.
