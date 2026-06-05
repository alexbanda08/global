# Full-Period Re-Analysis — 5 strategies: WR, $/tr, MaxDD, Calmar, new gates, persistence (2026-05-31)

_Re-ran the 3 ETH winners + kelly + sol_rf over all available canonical history, swept new gates, computed Max Drawdown + Calmar, and tested whether each edge + my live-window gates persist out-of-sample. Stake basis differs: ETH/sol_rf = flat $5; kelly = Kelly-sized (up to 4×$25)._

## MASTER TABLE

| strategy | period | trades | WR% | $/tr | total $ | MaxDD $ | Calmar | persistence verdict |
|---|---|--:|--:|--:|--:|--:|--:|---|
| **eth_l_ema50_grandparent_v8** | Apr24–May26 | 467 | 82.0 | +0.93 | +432 | **−25** | **17.3** | ✅ **persists, lowest DD** ⭐ |
| **eth_cloud_ribbon_v6** | Apr24–May26 | 481 | 81.7 | +0.88 | +422 | −35 | 12.0 | ✅ persists |
| **eth_bb_mp_hurst_v6** | Apr24–May26 | 162 | 74.1 | +1.92 | +311 | −32 | 9.6 | ✅ persists |
| **kelly** (full 4×, base) | May1–21 | 3508 | 84.4 | +5.38 | +18,879 | −844 | 391.6 | ⚠ real but concentrated |
| kelly + fe>1000, ½-Kelly | May1–21 | 818 | ~84 | +11.25 | ~+9,200 | ~−260 | ~528 | ✅ recommended config |
| kelly + keep_EU (full 4×) | May1–21 | 1104 | 84.2 | +3.52 | +3,883 | −626 | 108.6 | ❌ WORSE than base |
| **sol_rf** (rf+tr, base) | Apr24–May27 | 4663 | 59.8 | −0.23 | **−1,068** | −1,345 | −0.79 | ❌ base loses |
| sol_rf + drop_US+ma_300+tr≥2 | Apr24–May27 | 1511 | 73.7 | ~0 | −2.6 | −195 | ~0 | ⚠ only breakeven |

## Per-strategy detail

### ETH 5m winners — ✅ deployable, low drawdown
- Alpha persists full-period (in-sample WR 72-82% ≈ live 71-73%). Calmar 10-17 — worst peak-to-trough only $25-35 on a $5 stake vs $300-430 profit.
- **`eth_l_ema50_grandparent_v8` is the fleet's best risk-adjusted sleeve** (82% WR, MaxDD −$25, Calmar 17.3).
- **New gates that improve it (in-sample, confirm live before deploy):**
  - `+ g_sms_no_liquidity_above` → Calmar 17.3 → **23.7** (MaxDD −$25 → −$15, no return loss) ⭐
  - `+ g_mp_skew_with` → +0.25/tr, Calmar 20.1
  - eth_bb `+ g_entry_vwap_in_band_narrow` → +1.41/tr, Calmar 9.6 → 13.6 (n→65)
- **Do NOT add `entry_vwap≤0.70` to these winners** — it lifts $/tr but lowers Calmar (cuts net-positive high-priced winners). Reserve it for marginal/losing sleeves.

### kelly — ⚠ edge is real but fragile & sizing-driven
- Base WR 84.4% over May 1-21, but **at 1× stake earns only +$0.18/tr** — the +$18,879 is the **4× Kelly sizing of the high-`fair_edge_bp` tail**, not the base direction. 80% of PnL from the 4× tier (n=152), **73% of total from week 21 alone** → concentrated/fragile.
- **`keep_EU` does NOT persist** — fails both-half holdout (H1 −$0.08/tr, H2 +$6.94/tr); the live +$2,272 was the week-21 spike, not a robust time-of-day effect. **Drop keep_EU.**
- **The one robust gate: `fair_edge_bp > 1000`** (conviction tier) — passes both halves (H1 +$10.83, H2 +$34.17), retains 23% of fires / 97% of PnL, Calmar 528.
- **½-Kelly** halves return AND drawdown (same Calmar) — the right risk posture given the concentration.
- **Recommended: `fair_edge_bp>1000` + ½-Kelly ($12.5×mult), no keep_EU.** Watch for fair_edge decay.
- MaxDD note: −$844 is at full 4×Kelly ($100 max/trade); ½-Kelly ≈ −$422.

### sol_rf — ❌ NOT deploy-ready (the big correction)
- **Base loses full-period: 59.8% WR, −$1,068, MaxDD −$1,345.** The live +$93 / 69.5% / +$0.25/tr was a **favorable 3-day window**, not the true edge.
- **`drop_US` confirmed overfit** — WR unchanged (59.8→59.9%), zero independent alpha OOS.
- **`ma_300` (binance 300s momentum) is the ONE real signal** — +10pp WR (60→70%), stable both halves. The external gate was the edge, not the base sleeve.
- Even fully gated (`drop_US+ma_300+tr≥2`): WR 73.7% (≈ live 69.5%) but **only breakeven** — entry-vwap levels eat the edge. Needs a vwap filter to clear positive.

## Cross-cutting lesson (the headline)

**Every time-of-day / session gate I found in the short live window FAILED the full-period OOS test:**
- kelly `keep_EU` → fails (week-21 artifact)
- sol_rf `drop_US` → fails (no independent alpha)
- (earlier) ETH `drop_US`, `vsum` → fail

**The signals that DO persist OOS are conviction/momentum/price, not timing:**
- `fair_edge_bp > 1000` (kelly conviction tier) ✅
- `ma_300` binance momentum (sol_rf) ✅
- `entry_vwap ≤ 0.70` (don't overpay, marginal sleeves) ✅
- The ETH base directional signals (cloud/bb/hurst/ema-stack) ✅

**Deploy ranking after full-period:** ETH 5m winners (low-DD, persistent) > kelly with `fe>1000`+½-Kelly (real but concentrated) >> sol_rf (not ready — needs ma_300 + vwap filter just to breakeven).

## Caveats
- ETH/kelly universe panels are the GA **training set** (in-sample upper bound); the live window is the true OOS — that decay is quantified per row.
- sol_rf reconstruction is approximate (rf/tr gates rebuilt from 1s panels, legacy fee on the sol_rf run) — direction is clear (base loses, ma_300 is the signal) even if exact $ differ.
- kelly panel covers May 1-21 only (not Apr 24); week-21 concentration is a real fragility flag.

Sources: `ETH_NEWGATES_MDD_2026_05_31.md`, `KELLY_FULLPERIOD_2026_05_31.md`, `SOLRF_FULLPERIOD_2026_05_31.md` + CSVs in `_opt_2026_05_30/_results/`.
