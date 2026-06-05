# Maker-Arb Full-History Real-PnL Backfill (2026-05-29)

> Question: "can we backfill the old history with the new implementation so we
> can see the real PnL?" — **Yes.** Done here. No engine replay needed: the E1
> bug was only in settlement/marking; recorded fills (and realized cash) were
> always correct. Backfill = reprocess recorded fills through corrected
> settlement (realized cash + chainlink residual settle).

Script: `strategy_lab/maker_arb_audit/backfill_history.py`
Window: V1 sleeves May 25-29 (5d), V2 sleeves May 27-29 (3d). 4,433 counted
slugs (81 uncovered in-flight/gap = 1.8%).

## Real PnL over full history (POST_SIZE=20)

| sleeve | n | win% | **real $/slug** | 95% CI | real total | old dashboard showed |
|---|---:|---:|---:|---|---:|---:|
| mas_btc_15m (v1) | 365 | 11.0% | −0.09 | [−0.43, +0.25] | −$32 | ≈0 |
| mas_v2_btc_5m | 447 | 6.3% | −0.16 | [−0.47, +0.16] | −$70 | ≈0 |
| mas_btc_5m (v1) | 1096 | 10.2% | −0.25 | [−0.45, −0.05] | −$272 | ≈0 |
| acc_h_v2_btc_15m | 131 | 47.3% | **−0.52** | [−1.83, +0.80] | −$67 | **+1.76** |
| acc_h_v2_eth_15m | 76 | 46.1% | −0.79 | [−2.42, +0.84] | −$60 | +0.65 |
| acc_pc_v2_btc_15m | 141 | 40.4% | −1.50 | [−2.78, −0.23] | −$212 | +1.06 |
| acc_m_v2_btc_5m | 435 | 37.7% | −1.78 | [−2.47, −1.09] | −$774 | −0.18 |
| acc_pc_v2_eth_15m | 124 | 44.4% | −1.86 | [−3.22, −0.49] | −$230 | +1.39 |
| acc_h_btc_15m (v1) | 271 | 42.1% | −1.99 | [−2.95, −1.03] | −$539 | +1.59 |
| acc_pc_btc_15m (v1) | 298 | 37.2% | −2.43 | [−3.37, −1.49] | −$725 | +0.72 |
| acc_m_btc_5m (v1) | 1049 | 33.7% | **−3.45** | [−3.94, −2.96] | −$3,618 | −1.06 |

**GRAND TOTAL real PnL across all sleeves over the history: −$6,599.**

## Read

- **Every sleeve is net-negative on real PnL.** The old reporting showed the
  15m sleeves as **+$0.7 to +$1.8/slug profitable**; the truth is **negative**
  for all of them. That gap is the survivorship bias (directional losers never
  settled in the old log) the E1 fix removed.
- **ACC-M 5m is the biggest bleed**: acc_m_btc_5m −$3.45/slug × 1049 slugs =
  **−$3,618** over 5 days. acc_m_v2 (PAT-off) is less bad (−$1.78) but still
  clearly negative. The 5m cadence + adverse-selected directional residual
  dominates.
- **15m V2 sleeves are the "least bad"**: acc_h_v2_btc_15m −$0.52 (CI straddles
  0 on n=131). Not profitable, but closest to breakeven. acc_pc variants are
  clearly negative.
- **MAS is ~breakeven-slightly-negative** (mint-and-hold; asks rarely fill) —
  −$0.09 to −$0.25/slug. Low-magnitude bleed.
- `old dashboard showed` = mean `slug_pnl_so_far` over inv==0 slugs. (Note: over
  this window it mixes pre-fix biased-high settled winners with post-fix
  correctly-settled losers, so it understates the *original* overstatement —
  the pure pre-fix snapshot read acc_h_v2_btc_15m at +$4.44. Either way: the old
  number was positive, the real number is negative.)

## Bottom line

The new implementation, applied to the full recorded history, confirms the
censoring-reversal at scale and with statistical confidence: **the maker-arb
suite has lost ~$6.6k (paper) over 5 days; no sleeve shows a positive edge.**
The fix made the numbers honest — it did not make the strategies profitable.
Do not deploy live. The path to any positive sleeve runs through E6/E7
(eliminate/flatten the adverse-selected directional residual) — until then
every cell bleeds.

## Artifacts
- `strategy_lab/maker_arb_audit/backfill_history.py`
- `strategy_lab/maker_arb_audit/_results/backfill_summary.csv`
- `strategy_lab/maker_arb_audit/_results/backfill_per_slug.csv`
