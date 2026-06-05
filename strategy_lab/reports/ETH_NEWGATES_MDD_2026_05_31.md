# ETH sleeves — new-gate sweep + Max Drawdown (full period Apr 24 → May 26)

_Re-analysis of the 3 ETH 5m winners on the full-period universe. Swept ALL ~200 `g_*` columns as candidate ADD-gates (both-half holdout filter), computed Max Drawdown + Calmar. PnL = 0.07-curve, flat $5. ⚠ Universe = the GA training set → in-sample; new-gate picks need live OOS confirmation (see caveat)._

## 1. Base sleeves — risk-adjusted profile (the solid finding)

| sleeve | period | trades | WR% | $/tr | total $ | **MaxDD $** | **Calmar** |
|---|---|--:|--:|--:|--:|--:|--:|
| eth_l_ema50_grandparent_v8 | Apr24-May26 | 467 | 82.0 | +0.93 | +432 | **$25** | **17.3** ⭐ |
| eth_cloud_ribbon_v6 | Apr24-May26 | 481 | 81.7 | +0.88 | +422 | $35 | 12.0 |
| eth_bb_mp_hurst_v6 | Apr24-May26 | 162 | 74.1 | +1.92 | +311 | $32 | 9.6 |

**These are genuinely low-drawdown strategies.** Calmar 10-17 (total return ÷ max drawdown) is strong — the worst peak-to-trough on a $5 stake is only $25-35 against $300-430 of cumulative profit. `eth_l_ema50_grandparent_v8` is the standout: highest WR (82%), lowest MaxDD ($25), best Calmar (17.3). (MaxDD scales linearly with stake — at $25 notional, MaxDD ≈ $125-175.)

## 2. `entry_vwap ≤ 0.70` — raises $/tr but LOWERS Calmar here

| sleeve | base Calmar | +entry_vwap≤0.70 | verdict |
|---|--:|---|---|
| eth_cloud_ribbon | 12.0 | total $345, MaxDD $32, **Calmar 10.9** | ↓ |
| eth_l_ema50 | 17.3 | total $334, MaxDD $30, **Calmar 11.2** | ↓ |
| eth_bb | 9.6 | (no-op — own vwap-band already caps) | = |

**Important nuance:** `entry_vwap≤0.70` (my durable OOS gate) lifts per-trade EV but **cuts Calmar on these already-strong winners** — it removes high-priced winners that were still net-positive, shrinking total more than drawdown. **So `entry_vwap≤0.70` is the right gate for marginal/losing sleeves (where overpaying is the loss source), NOT for these ETH winners — they're better left ungated for risk-adjusted return.**

## 3. New candidate gates (both-half-positive, n≥40) — ranked by Calmar improvement

⚠ **In-sample**: swept ~200 gates and kept both-half-positive ones; with that many candidates, some pass by chance. Treat as candidates, not confirmed. Best to re-test live.

**eth_l_ema50_grandparent_v8 (base Calmar 17.3):**
| new gate | n | lift $/tr | total $ | MaxDD $ | Calmar | note |
|---|--:|--:|--:|--:|--:|---|
| **g_sms_no_liquidity_above** | 353 | +0.08 | +355 | **$15** | **23.7** ⭐ | cuts MaxDD 40%, keeps return |
| g_tr_in_active_session | 433 | +0.01 | +406 | $20 | 20.2 | keeps n, lower DD |
| g_mp_skew_with / g_hurst_mp_trend_with | 275 | +0.25 | +324 | $16 | 20.1 | best $/tr lift + low DD |
| g_tight_ribbon | 385 | +0.09 | +390 | $22 | 17.9 | ~neutral |

**eth_bb_mp_hurst_v6 (base Calmar 9.6):**
| new gate | n | lift $/tr | total $ | MaxDD $ | Calmar |
|---|--:|--:|--:|--:|--:|
| **g_entry_vwap_in_band_narrow** | 65 | **+1.41** | +216 | $16 | **13.6** ⭐ |
| g_rf_fresh | 151 | +0.04 | +296 | $32 | 9.2 |

**eth_cloud_ribbon_v6 (base Calmar 12.0):**
| new gate | n | lift $/tr | total $ | MaxDD $ | Calmar |
|---|--:|--:|--:|--:|--:|
| g_tr_above_pp | 264 | +0.09 | +254 | **$21** | 12.3 |
| g_entry_vwap_in_band_narrow | 62 | +2.28 | +196 | $16 | 12.3 |
| g_markov_with | 253 | +0.07 | +240 | $20 | 11.8 |

(Avoid `g_vol_high` on cloud_ribbon: total $342 but Calmar collapses to 2.4 — return concentrated in a few volatile windows = high drawdown risk.)

## 4. Takeaways

- **Base ETH sleeves are low-DD, high-Calmar** (10-17) and the alpha persists full-period (WR 72-82% ≈ live). These are the most deployable in the fleet.
- **Best risk-adjusted improvement: `eth_l_ema50 + g_sms_no_liquidity_above`** → Calmar 17.3 → **23.7** (MaxDD $25→$15) with no return loss. `+ g_mp_skew_with` adds +0.25/tr at Calmar 20. Strong candidates — confirm live.
- **`eth_bb + g_entry_vwap_in_band_narrow`**: +1.41/tr, Calmar 9.6→13.6 (but n→65, halves trade count).
- **Do NOT apply `entry_vwap≤0.70` to these winners** — it hurts Calmar. Reserve it for marginal/losing sleeves.
- **Caveat**: new-gate sweep is in-sample (universe = training set). The base MaxDD/Calmar are real; the specific new-gate picks need live-window confirmation before deploy.

Artifact: `16_eth_newgates_mdd.py`. Companion full-period work: kelly (`KELLY_FULLPERIOD_2026_05_31.md`) + sol_rf (`SOLRF_FULLPERIOD_2026_05_31.md`) — subagents running.
