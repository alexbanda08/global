# Deep-dive: btc_15m_ema50_ema800_off600_down — spec, fidelity, cheap-entry edge, full-period backtest (2026-06-01)

## 1. Spec & fidelity — ✅ faithful

- **Gates (live, verified on 185 fires):** `g_dir_down` + `g_tr_above_ema50(BTC)` + `g_tr_above_ema800(BTC)`. Direction 100% DOWN, offset 600 (fires 10 min into the 15m window), `all_gates_passed=True` on every fire. Matches spec exactly (created via the `sniper_btc15m` GA search → `sniper_btc15m_v8_gated` universe panel).
- **Signal logic:** when BTC's short+long EMA stack is bearish (price below ema50 AND ema800), fire DOWN at offset 600, hold to chainlink resolution. $5 stake.
- **Note:** this strategy is ALSO running live on **Kalshi** (`kalshi_sniper_btc_15m_ema50_ema800_off600_down` + `_H`, 73+47 fires) — not just Polymarket.
- Exit types: 241 `hold_to_resolve` (base) + 19 `hedge_late_cut` (the `_H` variant).

## 2. The "cheap entries" question — live looked like edge, full-period says **mostly luck at the extreme**

DOWN bet → `entry_vwap` = market-implied P(DOWN). "Cheap entry" = low price = market thinks DOWN unlikely → contrarian. `edge = WR − implied`.

**LIVE window (175 fires, ~May 27-Jun 1):**
| entry | n | WR | implied | edge | $/tr | total |
|---|--:|--:|--:|--:|--:|--:|
| 0.00-0.15 | 5 | 40% | 6% | +34pp | +$22.1 | **+$110** |
| 0.15-0.30 | 16 | 37.5% | 23.5% | +14pp | +$4.1 | +$65 |
| 0.50-0.70 | 28 | 75% | 60.8% | +14pp | +$1.2 | +$32 |

**FULL PERIOD (917 fires, Apr 24-May 26) — the truth:**
| entry | n | WR | implied | **edge** | $/tr | total |
|---|--:|--:|--:|--:|--:|--:|
| **0.00-0.15** | 36 | 5.6% | 7.9% | **−2.3pp** | **−$1.47** | **−$53** ❌ |
| 0.15-0.30 | 48 | 29.2% | 22.4% | +6.8pp | +$1.35 | +$65 ✅ |
| 0.30-0.50 | 88 | 42.0% | 41.2% | +0.8pp | +$0.02 | +$2 |
| **0.50-0.70** | 156 | 71.2% | 61.2% | **+10pp** | +$0.71 | **+$110** ⭐ |
| 0.70-0.85 | 183 | 80.3% | 78.0% | +2.3pp | +$0.09 | +$16 |
| 0.85-0.95 | 217 | 94.5% | 90.7% | +3.8pp | +$0.18 | +$40 |
| 0.95-1.01 | 189 | 97.4% | 97.6% | −0.2pp | −$0.02 | −$4 |

**Resolution of the puzzle:**
- **The DEEPEST-cheap bucket (entry < 0.15, the 0.06-type bets) is NOT an edge — it's slightly −EV (−$53 over 36 fires, WR 5.6% ≈ 7.9% implied).** The live window's spectacular +$110 there was **5-trade small-sample luck** (it caught 2 of the bucket's only ~2 winners). The specific 0.06 DOWN fire that lost −$5 is a fairly-priced lottery ticket, not a mispricing.
- **The REAL edge is the moderately-cheap contrarian zone, entry 0.15-0.70** — especially **0.50-0.70 (+10pp edge, +$110, n=156)** and 0.15-0.30 (+6.8pp, +$65). The EMA-down trend genuinely beats the crowd's price there.
- **The expensive favorites (≥0.85) add a little; the 0.95+ bucket and the deepest-lottery <0.15 are dead/negative.**

## 3. Optimization — a TIGHT floor helps, a HIGH floor destroys

**Entry-floor sweep (full period, $5):**
| floor | n | WR | total | vs base |
|---|--:|--:|--:|--:|
| none (≥0.00) | 917 | 76.3% | +$176 | — |
| **≥0.15** | 881 | 79.2% | **+$229** | **+$53 (+30%)** ⭐ |
| ≥0.30 | 833 | 82.1% | +$164 | −$12 |
| ≥0.50 | 750 | 86.7% | +$167 | −$9 |
| ≥0.70 | 589 | 91.0% | +$52 | **−$124 (kills it)** |

**Verdict — your instinct is *half* right:**
- ✅ **Add a tight floor `entry_vwap ≥ 0.15`** — it skips ONLY the deepest-lottery bucket (the 0.06-type fires that are −EV / fairly priced), and it's the single best change: **+30% total** ($176→$229), higher WR (76→79%), and it *would have skipped the −$5 0.06 fire you flagged.*
- ❌ **Do NOT raise the floor higher.** `≥0.70` cuts the 0.15-0.70 contrarian edge and collapses the strategy to +$52. The "cheap-ish" 0.15-0.70 DOWN bets are the alpha — keep them.
- Optional: the **0.70-0.85 bucket is near-zero edge** (+$16, +2.3pp) and the **0.95+ bucket is dead** — minor trims, not worth the complexity vs the 0.15 floor.

## 4. Full-period backtest result (all local data, Apr 24 → May 26)

- **Base (no floor):** n=917, WR 76.3%, **+$176.2 total, +$0.19/tr** (0.07-curve, flat $5). Positive **every week** except a partial wk22 (−$22).
- **With `entry≥0.15` floor (recommended):** n=881, WR 79.2%, **+$229, +$0.26/tr**.
- Cheap (<0.70) contributes +$124 of the profit vs expensive (≥0.70) +$52 → the contrarian zone is the engine, but trim the sub-0.15 tail.
- **Live (May 27-Jun 1)** ran hotter (+$1.6/tr, +$282) — a favorable regime + the cheap-bucket luck; the full-period +$0.19/tr is the durable expectation.

## 5. Recommendations
1. **Deploy `entry_vwap ≥ 0.15` floor** on the base sleeve (and the Kalshi twin) — +30% PnL, removes the −EV deepest-lottery fires including the kind you flagged. This is a V10-style tweak.
2. **Keep the 0.15-0.70 contrarian DOWN fires** — that's the genuine EMA-trend-vs-crowd edge.
3. Don't bother with stop-loss/hedge here (prior work: hold-to-resolve optimal; HEDGE_LATE hurts this winner).
4. The big per-trade swings come from the cheap wins paying ~16× — expect high variance (std ~8 on $5); size for it.

Artifacts: `23_ema_down_deepdive.py` (live), `24_ema_down_fullperiod.py` (full period) → `_results/ema_down_fires.parquet`. Substrate: `sniper_btc15m_v8_gated.parquet` (Apr24-May26).
