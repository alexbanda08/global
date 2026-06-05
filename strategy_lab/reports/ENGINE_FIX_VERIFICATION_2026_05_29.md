# Maker-Arb Shadow Engine — Fix Verification (2026-05-29 01:49 UTC)

> Verified the bug-map fixes that landed on Ireland (files modified 21:40-01:14
> after the 2026-05-28 20:00 audit snapshot). Method: diff current Ireland source
> vs the audited snapshot, read the new code, and re-audit the live post-fix
> shadow data. **Verdict: the displayed PnL is now REAL. The big optimism bug
> (E1) is fixed and confirmed live.**

## Fix status

| Bug | Status | Evidence |
|---|---|---|
| **E1** settlement / loser-mark | ✅ FIXED + live | New `fill_sim.settle_slug()` (idempotent, double-credit-safe) called for **every** resolved slug from `poly_maker_loop` resolution tick. Zeros both inventories, sets `redeem_fired`, emits an `EXPIRE` row. acc-h-v2 today: **14 EXPIRE** + 8 REDEEM rows. |
| **E2** MAS-V2 inert gate | ✅ FIXED + live | `mas.py`: `if self.variant != "v2" and sum_asks < MAS_V3_MIN_SUM_ASKS` (both gate sites). MAS-V2 today: **44 MINT / 42 REDEEM / 21 EXPIRE** (was 0/235 inert). |
| **E3** slug-keyed fill routing | ✅ FIXED | `_lookup_strategy(slug, order_id)` now prefers `_order_strategy[order_id]`, slug cache only as fallback. |
| **E4** fee model | ⚠️ machinery in, **not activated** | `base.py` adds `resolution_fee()` + selectable `model` (curve / curve_winner / legacy_2pct / zero), re-verified vs 6795 events. BUT all call sites `getattr(settings,"tv_poly_maker_fee_model","curve")` and the live env does **not** set it → defaults to `"curve"`. See "remaining" below. |
| **E5** dashboard PnL | ✅ FIXED | `_emit_state_tick` now adds `cash_recovered` (E5a). `maker_sleeves.py` "REAL PnL" recompute = pure cash + corrected mark (settled→0, open→paired×$1, residual→$0), **drops** the rebates/taker_fees columns, and dedups midnight-spanning slugs via one global latest-row-per-slug (E5b/E5c). |
| shadow_log.py | unchanged (correct) | Mark formula untouched; with E1 now setting `redeem_fired`, its `mark = paired×$1` correctly collapses to 0 for settled losers. |

## Proof the displayed PnL is real

Re-audited the post-fix data (2026-05-29, ~2h). Per settled slug compared
**true realized cash** (`cash_received + cash_recovered − cash_spent`, no fee
columns) to the engine's `slug_pnl_so_far`:

| sleeve | n_active | n_settled | n_resid_open | true_mean | engine_col | gap | fee_col |
|---|---:|---:|---:|---:|---:|---:|---:|
| acc_h_v2_btc_15m | 8 | 6 | 1 | +1.703 | +1.694 | −0.010 | −0.010 |
| acc_h_v2_eth_15m | 4 | 4 | 0 | +1.105 | +0.969 | −0.136 | −0.136 |
| acc_pc_v2_btc_15m | 8 | 6 | 1 | +1.703 | +1.694 | −0.010 | −0.010 |
| acc_pc_v2_eth_15m | 5 | 5 | 0 | +1.484 | +1.343 | −0.140 | −0.140 |
| acc_m_v2_btc_5m | 20 | 19 | 1 | −1.602 | −1.671 | −0.069 | −0.069 |
| mas_v2_btc_5m | 23 | 21 | 1 | 0.000 | −0.451 | −0.451 | −0.451 |
| acc_m_btc_5m | 21 | 19 | 1 | −1.640 | −1.716 | −0.076 | −0.076 |

Two facts prove the fix:
1. **`gap == fee_col` to 3 decimals on every sleeve.** The only difference between
   the engine column and true cash is the fee columns — i.e. **the mark is now 0
   on settled slugs.** The "+$0.50 × worthless residual" optimism is gone.
2. **`n_resid_open` collapsed to 0-1** (just the one in-flight slug at the snapshot
   edge). Pre-fix the strong 15m sleeves carried 26-37 censored residual losers
   each. Losers now settle via `EXPIRE` → no survivorship gap.

The dashboard "REAL PnL" equals `true_mean` (it uses pure cash + corrected mark),
so **the operator screen now shows the true realized number.**

## Remaining items (none are PnL-truth bugs)

1. **E4 fee model defaults to `"curve"` (not activated).** No `tv_poly_maker_fee_model`
   in the live env and no config-class default found → per-fill 0.07 curve + maker
   rebates are still booked in the CSV `rebates`/`taker_fees` columns. Net effect:
   `taker_fees > rebates`, so the engine `slug_pnl_so_far` column is **conservative**
   (slightly *below* true cash by `fee_col`, e.g. −$0.07 to −$0.45/slug), **not
   optimistic**. The dashboard ignores these columns, so the displayed PnL is
   unaffected. To get live-parity on the CSV column, set
   `TV_POLY_MAKER_FEE_MODEL=curve_winner` (or `legacy_2pct`) — a parity nicety,
   not a correctness bug. Verify the live fee first (`TV_AGENT_FIX_FEE_MODEL_SPEC.md`).
2. **`settle_slug` partial-REDEEM edge case (low risk).** If a strategy ever emits
   a REDEEM for *less* than the full winner residual, `redeem_fired=True` makes
   `settle_slug` zero the remaining winner shares **without** crediting them →
   understates that slug. Confirm `on_slug_resolved` always redeems the full
   winner inventory (it appears to). Not observed in current data.
3. **E6/E7 not addressed** (convergence-flatten of directional residual;
   per-side cash for the ACC-PC pair-cost gate). These are the *edge* levers, not
   accounting — the strategies remain ~breakeven-to-negative without them.

## ⚠️ The numbers are honest now — but the strategies are NOT yet profitable

Fixing the accounting did **not** make the sleeves win. On this tiny ~2h post-fix
window: acc_m −$1.6/slug (n=19), mas_v2 ≈$0 (mint-and-hold, asks not filling),
and the 15m sleeves show +$1.7 but on only **n=6** — pure noise. This is fully
consistent with the censoring-reversal finding: the true edge is ~breakeven-to-
negative. **Do not read the small positive 15m numbers as a signal.** Collect a
multi-day post-fix window before any profitability call, and address E6/E7 (the
real PnL levers) if a sleeve is to have a chance of turning positive.

## Artifacts
- Current Ireland source snapshot: `migration_ireland_recheck_2026_05_29/source/`
- Post-fix shadow CSVs: `migration_ireland_recheck_2026_05_29/maker_csvs/`
- Bug map: `strategy_lab/reports/ENGINE_BUG_MAP_2026_05_28.md`
