# Maker-Arb Deploy Decisions — 2026-05-27

Synthesis of 3 parallel investigations: convergence-cancel replay, ACC-M+MAS loss decomposition, cross-cell backtest.

## TL;DR

5 of 6 sleeves have a path to profitability. PAT-SHADOW kills. ACC-M's PAT overlay kills. Add a convergence-cancel filter everywhere. Extend ACC-H + ACC-PC to eth_15m.

| Action | Effort | Expected $/day delta |
|---|---|---:|
| Disable PAT overlay on ACC-M btc 5m | 1 env var | **+$1,195** |
| Land F-convergence-cancel (T-60s 5m, T-120s 15m) on all ACC + MAS | 2-3 dev-hours | +$580 (ACC-M) + $81 (ACC-H) + $155 (ACC-PC) = **+$816** |
| MAS min_ask_price=0.52 + block UTC 4 + sum_asks gates | 1 dev-hour | **+$90** |
| Deploy ACC-H + ACC-PC on eth_15m (shadow first) | new cells, 1 day | **~+$300 estimated** |
| Disable PAT-SHADOW standalone sleeve | 1 env var | +$0 (was bleeding) |
| **Combined potential** | | **~+$2,400/day** |

vs current shadow (post-F1): **-$430/day** (sum of all sleeves)
→ swing: ~$2,800/day improvement

Capital required: **~$400-500 USDC** across 5-7 sleeves.

## Per-sleeve actions

### 1. ACC-M btc 5m — DEPLOY (after PAT disable + convergence fix)

Root cause of loss: PAT overlay fires 553 of 599 slugs at `pair_cost ∈ [0.97, 1.00]`. After fees + variance, those slugs lose −$1.91/slug. Maker-only slugs earn **+$2.63/slug**.

**Fix order**:
1. `tv_poly_maker_acc_m_enable_pat=false` (disable PAT entirely on ACC-M btc 5m) → +$1,195/day
2. Or tighter: `tv_poly_maker_pat_max_pair_cost=0.93` → +$700/day (keeps PAT but only the genuinely cheap pairs)
3. Land convergence-cancel (T-60s) → +$580/day
4. Optional: block UTC hours 22,23,0,12,13,14 → +$291/day

Final estimate: **+$1,329/day cash truth** at current POST_SIZE=20.

Wallet capital: $84.

### 2. ACC-H btc 15m — DEPLOY (with convergence fix)

Already profitable (+$224/day post-F1). Add convergence-cancel (T-120s) for +$81/day.

Final: **+$300/day**. Wallet: $84.

### 3. ACC-PC btc 15m — DEPLOY (with convergence fix)

Already marginal positive (+$73/day post-F1). Convergence fix adds +$155/day.

Final: **+$228/day**. Wallet: $104.

### 4. MAS btc 5m + 15m — DEPLOY (with min_ask + UTC filter)

5m loses because 110/230 fills land at price < $0.50 (below mint cost basis).

**Fixes**:
- `tv_poly_maker_mas_min_ask_price=0.52` → +$50/day
- `tv_poly_maker_mas_block_hours=4` → +$30/day
- `tv_poly_maker_mas_min_sum_asks=1.005, max_sum_asks=1.015` → +$10-20/day

Final: **+$60-100/day**. Wallet: $78 (mint cost is $30 fixed × 2 concurrent + safety).

### 5. ACC-H + ACC-PC on eth_15m — NEW DEPLOY (shadow first)

Per Agent C backtest, eth_15m has the strongest WR profile in the broad universe:
- ACC-H eth 15m: 61.6% WR
- ACC-PC eth 15m: 50.6% WR
- Beats btc_15m baseline WR in the same simulation

But: backtest is conservative on absolute PnL (sim fill_rate 30% vs live ~70%). Real numbers should be 2-5× larger.

**Action**: deploy ACC-H eth_15m + ACC-PC eth_15m in **shadow mode** first. 14-day collection. If WR holds ≥55% on live data, promote to paper at $25 stake.

Estimated $/day at current shadow rate, scaled by cell volume: **+$150-200/day per strategy** = ~$300-400/day combined.

Wallet: another $190 ($84+$104).

### 6. eth_5m for ACC-H + ACC-PC — CONDITIONAL

Backtest WR: 53.5% / 38.5% — under the 55% threshold. 2-week shadow before deciding.

### 7. btc_5m for ACC-H + ACC-PC — DO NOT DEPLOY

Backtest WR: 27.4% / 18.4%. Short slot window kills maker fill time. Don't bother.

### 8. PAT-SHADOW — KILL

−$2,983/day standalone. Structural bleed. The inherited PAT inside ACC-M was the real bug (now disabled per §1).

Set `TV_POLY_MAKER_KILL=PAT-SHADOW:btc_5m` immediately.

## Combined deploy plan

### Phase 0 — TV agent fixes (this week)

| Fix | Spec | Effort |
|---|---|---|
| F-convergence-cancel | `TV_AGENT_FIX_CONVERGENCE_CANCEL_SPEC.md` | 2-3 dev-hr |
| ACC-M disable PAT (config only) | env var | 5 min |
| MAS V3 gates (min_ask + UTC + sum_asks) | `TV_AGENT_FIX_MAS_V3_SPEC.md` (existing) + min_ask additional | 1-2 dev-hr |
| Kill PAT-SHADOW (config only) | env var | 5 min |

Total dev: ~5-7 hours.

### Phase 1 — Shadow verification (24-48h after Phase 0)

Run the re-audit runbook (`SHADOW_PNL_REAUDIT_RUNBOOK_2026_05_21.md`). Expected post-fix honest cash $/day:

| Sleeve | Pre-fix | Post-fix |
|---|---:|---:|
| ACC-M btc 5m | −$446 | **+$1,329** |
| ACC-H btc 15m | +$143 | **+$224** |
| ACC-PC btc 15m | +$73 | **+$228** |
| MAS btc 5m | −$34 | **+$60** |
| MAS btc 15m | +$0.20 | **~+$5** |
| PAT-SHADOW | −$2,983 | $0 (killed) |
| **Sum** | **−$3,246** | **+$1,846** |

Hard gate: must see ≥80% of expected delta materialize. If post-fix sum < +$1,000/day, investigate before paper.

### Phase 2 — Add eth_15m shadow sleeves (week 2)

Add ACC-H + ACC-PC on eth_15m, shadow mode 14 days. Same fixes (convergence-cancel) applied. Promote if WR ≥55% and $/slug ≥ +$1.00.

### Phase 3 — Paper deploy (week 3-4)

Pick top 3-4 sleeves by post-fix $/day rate. Deploy at $50 stake each. 7-day verification. Wallet ~$400-500.

### Phase 4 — Live deploy with scaling (week 5+)

If Phase 3 holds, scale POST_SIZE 20 → 50 over week 5-6. Wallet ~$1,000.

Full deploy at POST_SIZE=100: wallet ~$2,500, projected ~+$2,400/day net.

## What this changes vs prior deploy report

| Question | Yesterday's answer | Today's answer |
|---|---|---|
| Is ACC-M btc 5m viable? | No — cash truth −$1.32/slug | **Yes** — disable PAT, +$1,329/day |
| Does convergence-cancel matter? | Estimated +10-15% | **Confirmed +24-35%** on all ACC sleeves |
| MAS fixable cheaply? | Maybe (UTC + sum_asks) | **Yes** — min_ask_price=$0.52 is the key, +$90/day |
| New cells worth deploying? | Unknown | **eth_15m yes, eth_5m maybe, btc_5m no** |
| Kill PAT-SHADOW? | Yes | Yes, confirmed (also kills 100% loss) |

## Risk caveats

1. **Sample size**: 2.1 days of live shadow is short. Effects may regress to mean over a full month. Run Phase 1 for 7 days before drawing strong conclusions.
2. **Adverse selection at scale**: at POST_SIZE=20, our fills face competition. At POST_SIZE=100+, other makers see our orders and adverse-select harder. Sub-linear scaling (literature: exponent ~0.5).
3. **Convergence-cancel side effects**: cancelling all open orders at T-60s/T-120s may leave residual inventory unmerged. Verify the strategy still triggers force-merge at slug-active-resolve.
4. **PAT-disable trade-off on ACC-M**: PAT did generate $1,000+/day in volume (just at unprofitable margin). Disabling kills the volume but recovers $1,195/day in margin. Net is clearly positive but reduces wallet "activity" — important for maker-rebate-tier eligibility on Polymarket. Verify rebate-tier impact before disable.

## Files produced today

- `migration_ireland_shadow_2026_05_27/convergence_backtest/CONVERGENCE_REPLAY_REPORT.md` + `convergence_summary.csv`
- `migration_ireland_shadow_2026_05_27/loss_decomp/acc_m_btc_5m_optimization.md`
- `migration_ireland_shadow_2026_05_27/loss_decomp/mas_btc_5m_optimization.md`
- `migration_ireland_shadow_2026_05_27/cross_cell_backtest/CROSS_CELL_BACKTEST_REPORT.md` + `cross_cell_summary.csv`
- `strategy_lab/reports/TV_AGENT_FIX_CONVERGENCE_CANCEL_SPEC.md`
- this file: `strategy_lab/reports/MAKER_ARB_DEPLOY_DECISIONS_2026_05_27.md`

## Open questions for next session

1. Does the PAT overlay on ACC-M btc 5m have any positive contribution we're missing? Re-run Agent B with `pat_max_pair_cost ∈ {0.93, 0.95, 0.97}` sweep to find the optimal threshold (not just on/off).
2. Cross-cell exclusivity guard — if we deploy ACC-H + ACC-PC on same eth_15m cell, do we need to pick ONE per cell? Or does the engine handle separate wallets correctly?
3. Maker rebate tier impact: does Polymarket bucket us into a lower rebate tier if we suddenly drop PAT volume? Check the tier formula.
4. Convergence-cancel + force-merge interaction: do we leave residual paired inventory if cancel happens before all expected fills materialized?
