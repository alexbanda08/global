# TV Agent Spec — Exit-Scalp δ≥3 VARIANT (shadow, $5/fire) — 2026-06-02

**Addendum to `TV_AGENT_SPEC_SCALP_EXIT_SHADOW_2026_06_02.md`.** Adds a higher-volume variant of the
already-deployed exit-scalp sleeves: identical mechanics, but a looser entry threshold (`delta_bps≥3`
instead of ≥5) → ~3.4× the fire rate, to reach the forward-OOS graduation gate (n≥200) much faster.
**SHADOW / PAPER only.** Stake **$5/fire** (per operator request).

---

## 1. What changes vs the deployed sleeves
Clone of `shadow_scalp_exit_*_v1` / `_control_v1`, with TWO changes only:
1. Entry gate threshold: **`g_oracle_lag_with(3.0, 12.0)`** (was `5.0, 12.0`).
2. Stake: **`notional_usd_override = Decimal("5.0")`** (was 25.0).
Everything else identical: entry +5s, corrected lag signal (50/50), `entry_band=(0.0,0.55)` on gated /
`None` on control, `exit_policy="SCALP_EXIT"` (+60s / TP@0.65 / stop fill−0.10, poll 5s), `one_shot_per_slug`,
`direction="BOTH"`, `event_type='sleeve_scalp_exit'`. BTC+ETH × 5m+15m.

## 2. Sleeve IDs (8 sleeves: 4 gated + 4 control)
```
shadow_scalp_exit_btc_5m_d3_v1      shadow_scalp_exit_btc_5m_d3_control_v1
shadow_scalp_exit_btc_15m_d3_v1     shadow_scalp_exit_btc_15m_d3_control_v1
shadow_scalp_exit_eth_5m_d3_v1      shadow_scalp_exit_eth_5m_d3_control_v1
shadow_scalp_exit_eth_15m_d3_v1     shadow_scalp_exit_eth_15m_d3_control_v1
```
Implementation = extend the existing generator loop in `strategies/polymarket/sniper_v5_sleeves.py`
(the `shadow_scalp_exit_*` block, ~L1690) with a parallel loop: `lo_bps="3.0"`, `notional=Decimal("5.0")`,
sleeve_id suffix `_d3{_ctl}`. ~6 lines.

## 3. Validation (backtest)
- **Period tested:** 2026-04-24 → 2026-06-01 (~38 days).
- **Backtest stake:** $25/fire. **Deploy stake:** $5/fire → **divide every $/tr below by 5** (WR, t-stat,
  CI-excludes-0 are stake-invariant; only the dollar magnitude scales).
- **WR = % of round-trips that close positive** (mark-to-market exit, NOT chainlink resolution).

| cut | fires | WR% | entry vwap | $/tr @$25 (fee0 / fee.07) | $/tr @$5 (fee0 / fee.07) | t(.015) | 95% CI fee.07 @$25 |
|---|--:|--:|--:|--:|--:|--:|--:|
| **δ≥3 ALL (BTC+ETH)** | **398** | **68.6%** | 0.488 | +4.21 / **+2.56** | +0.84 / **+0.51** | **8.36** | [+1.63,+3.46] ✅ |
| δ≥3 BTC | 238 | 73.9% | 0.491 | +5.07 / +3.43 | +1.01 / +0.69 | 8.16 | [+2.31,+4.58] ✅ |
| δ≥3 ETH | 160 | 60.6% | 0.485 | +2.93 / +1.25 | +0.59 / +0.25 | 3.43 | [−0.20,+2.71] ⚠️ |
| δ≥3 5m | 260 | 66.9% | 0.494 | +4.70 / +3.10 | +0.94 / +0.62 | 6.81 | [+1.82,+4.35] ✅ |
| δ≥3 15m | 138 | 71.7% | 0.479 | +3.29 / +1.53 | +0.66 / +0.31 | 5.21 | [+0.42,+2.64] ✅ |
| _(deployed δ≥5 ALL, ref)_ | 118 | 75.4% | 0.480 | +5.92 / +4.24 | +1.18 / +0.85 | 6.51 | [+2.58,+5.93] ✅ |

**OOS by segment (δ≥3):** bwd_oos n=164 +$2.79 fee.07 CI[+1.32,+4.28] ✅ · fit_OOS n=117 +$2.85 CI[+1.20,+4.50] ✅
· **fwd_oos n=14 −$0.19 fee.07 CI[−3.14,+2.96] ⚠️ (the open gate — still too few forward fires).**

## 4. Honest read / caveats
- δ≥3 vs deployed δ≥5: **3.4× volume** (398 vs 118 fires), slightly lower WR (68.6% vs 75.4%) and edge
  (+$2.56 vs +$4.24/tr @$25 worst-fee) but **still robust** (worst-fee CI excludes 0). The point is *volume*,
  to accelerate forward validation — not a higher edge than δ≥5.
- **BTC ≫ ETH.** ETH δ≥3 worst-fee CI **includes 0** (marginal) — monitor; ETH may not earn its slot.
- ⚠️ **Forward window still unconfirmed** (n=14, flat-negative). The variant does NOT resolve this; it makes
  the live forward data accumulate faster. Same graduation gates as the parent spec §7 apply.

## 5. Graduation gates (unchanged from parent spec — do NOT route real capital until ALL pass)
1. ✅ LAGV2 signal fix (done — 50/50). 2. live taker-sell fee on real scalp fills. **3. forward-OOS ≥200 live
fires, bootstrap CI>0 (THE open blocker — this variant exists to hit it faster).** 4. ✅ walk-forward done.
5. ✅ direction-permutation done. 6. ✅ gate=`vwap<0.55` (CUSUM dropped). 7. exit-fill realism on live books.

## Artifacts
- `strategy_lab/directional/scalp_variant_table_2026_06_02.py` (this table)
- `strategy_lab/directional/scalp_variants_2026_06_02.py` (full variant sweep)
- `strategy_lab/reports/TV_AGENT_SPEC_SCALP_EXIT_SHADOW_2026_06_02.md` (parent spec)
## END
