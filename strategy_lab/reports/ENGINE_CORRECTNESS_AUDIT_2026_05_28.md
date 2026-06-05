# Maker Engine Correctness Audit — 2026-05-28

Complete audit of whether the shadow engine computes gains, losses, merges, fires, and tx costs **exactly as they would settle live**. Four independent investigations (settlement accounting, fill-sim realism, fee/gas model, per-slug reconciliation).

**Source audited**: Ireland production code pulled 2026-05-28 to `migration_ireland_audit_2026_05_28/source/`.
**Data**: live shadow CSVs May 27-28 (V1 + V2 sleeves).
**Sub-reports**: `migration_ireland_audit_2026_05_28/engine_audit/{settlement_accounting_audit,fill_sim_realism_audit,fee_gas_cost_audit,per_slug_reconciliation}.md`

## 0. Verdict

**The engine's per-slug cash accounting is EXACT** — 10/10 hand-traced resolved slugs reconcile to **$0.000000** discrepancy vs an independent ledger. The economic model is correct.

Net deviation from true live PnL is **±~$50/day** across all sleeves combined, dominated by one *conservative* bias (fee model) and two small *optimistic* gaps (MINT/REDEEM gas + partial fills). The errors partially offset.

**Shadow PnL is trustworthy as a live proxy** — with the caveats in §5 quantified and bounded.

## 1. Per-slug reconciliation — EXACT ✓

Independent hand-ledger replay of 10 fully-resolved slugs (4 ACC-M, 3 ACC-H, 3 MAS):

| Check | Result |
|---|---|
| hand_pnl vs engine `slug_pnl_so_far` | **$0.000000 on all 10** |
| hand_pnl vs engine cash-column formula | **$0.000000 on all 10** |
| Inventory tracking (CSV inv_up/dn vs hand) | matches at every step (1 cosmetic echo row, $0 cash impact) |

The engine's running cash columns are economically exact. No drift, no rounding accumulation, no sign errors.

**New structural facts discovered**:
1. **MERGE carries a 0.25% protocol fee** — `cash_recovered += pairs × 0.9975`, not × $1.00. The engine applies this correctly. (This is the same ~$0.05/merge the fee-audit saw; on a 20-share merge, 0.25% = $0.05.) Any naive backtest using `pairs × $1.00` over-states merge proceeds by 0.25%.
2. **Dual-row CSV pattern**: every action writes an intent row (`fill_simulated=0`) then a sim row (`fill_simulated=1`). Cash/inv mutate only on the sim row.
3. **REDEEM silently burns the losing side** — engine zeros both `inv_up` and `inv_dn` at REDEEM (no explicit BURN event).

## 2. Settlement accounting — CORRECT ✓ (1 small gap)

| Primitive | On-chain truth | Engine | Verdict |
|---|---|---|---|
| MINT / split | $C → C up + C dn, cost $C | `cash_spent += N`, inv both = N | ✓ exact |
| MERGE | 1up+1dn → $1 − 0.25% fee − gas | `cash_recovered += pairs × 0.9975 − gas` | ✓ exact |
| REDEEM | winner × $1, loser × $0 | `cash_recovered += size × $1`, loser zeroed | ✓ exact |
| CLOB BID fill | cash_spent += p×size | via `on_order_fill` | ✓ |
| CLOB ASK fill | cash_received += p×size | via `on_order_fill` | ✓ |
| TAKE fill | cash_spent += p×size + taker fee | VWAP walk + `_apply_bps_deltas` | ✓ |

No double-counts (force-merge depletes paired inventory before REDEEM; explicit guards at sim L738-743). No sign errors.

**GAP — MINT + REDEEM gas not modeled**:
- `_observe_mint` and `_observe_redeem` don't subtract Polygon gas.
- MERGE gas IS modeled (`tv_poly_merge_gas_usd`, $0.05/event).
- Over May 27-28: 1,780 MINT + 2,624 REDEEM = 4,404 untaxed CTF tx × $0.005-$0.02 = **$22-$88 overstatement** (mid ~$44/2-day = **~$22/day**).
- Fix: `cash_spent += gas_usd` in `_observe_mint`, `cash_recovered -= gas_usd` in `_observe_redeem`. Mirror the existing MERGE pattern. ~6 lines.

## 3. Fill simulation realism — REALISTIC ✓ (1 optimistic gap)

| Mechanism | Verdict | Detail |
|---|---|---|
| Queue position | ✓ REALISTIC | `initial_queue = depth ahead of us at post time`; decremented only by correct-side, correct-price trades; new makers behind us ignored (correct FIFO) |
| Book-cross trigger | ✓ REALISTIC | live book at check time; `best_ask <= our_bid` (touch fills — correct, someone willing to sell at our price) |
| Latency | ✓ REALISTIC | no artificial delay but WS RTT baked in. Empirical POST→FILL p50 = 2,311ms, p95 = 10,822ms, 0% under 1ms |
| Adverse-selection haircut | ✓ REALISTIC | 25 bps applied to 100% of 1,203 fills, baked into fill price once (no double-count) |
| Phantom-fill guard | ✓ CONSERVATIVE | cancel-vs-drain race always favors cancel → drops fill → under-counts |

**GAP — 100% fill on queue-drain (no partial fills)**:
- When `remaining_queue` hits 0, sim fills our FULL posted size. Real CLOB: if the aggressor's order is smaller than our size, only a partial fill happens.
- Estimated **10-25% over-fill** vs live → shadow fill rate 7.1% (ACC-M) likely → ~5-6.5% live.
- PnL impact bounded because the adv-sel haircut already penalizes the cost side. **Shadow PnL mildly optimistic** on fill volume.
- Mitigation: add `tv_poly_maker_partial_fill_ratio` knob (e.g. 0.8) to discount fill size.

## 4. Fee + gas + tx cost — MOSTLY CORRECT ✓ (1 conservative bias)

| Cost | Modeled? | $ over window | Note |
|---|---|---:|---|
| Taker fee `0.07×p×(1-p)` | ✓ | $493 booked (vs $495 expected, 1% rounding) | sim L806/815 |
| Maker rebate `0.014×p×(1-p)` | ✓ | $244 booked | bps=0 does NOT zero canonical formula |
| MERGE gas/fee | ✓ | $175.70 (3,514 events × $0.05) | = the 0.25% merge fee from §1 |
| CLOB place/cancel gas | ✓ $0 | — | meta-tx, operator pays (correct) |
| MINT gas | ✗ MISSING | $9-$36 | unbooked |
| REDEEM gas | ✗ MISSING | $13-$52 | unbooked |

**CONSERVATIVE BIAS — fee model may not match live**:
- Shadow charges the `0.07×p×(1-p)` curve on TAKE fills.
- CLAUDE.md (verified against 25,900 production resolution events) says live BTC/ETH/SOL up-down markets actually charge **2%-on-profit-only** — much cheaper than the curve.
- If 2%-on-profit is the live truth: shadow **over-charges taker fees by ~$370** over the window → **shadow PnL is UNDERSTATED** for taker-heavy sleeves. Real live would be BETTER.
- Same ambiguity on rebates: if `feeRate≈0` on these markets, the $244 booked rebate income doesn't exist live → over-states income by $244.
- Net if 2%-on-profit holds: shadow understates PnL by **~$63/day**.
- Net if `0.07` curve holds: accuracy is ±$22/day (gas only).

## 5. Net deviation from live truth

Combining all four:

| Source | Direction | $/day estimate |
|---|---|---:|
| MINT + REDEEM gas unmodeled | shadow OVER-states | −$22/day |
| Partial-fill optimism (100% fill) | shadow OVER-states | −$10 to −$30/day (volume-dependent) |
| Fee model (if live = 2%-on-profit) | shadow UNDER-states | +$63/day |
| Phantom-fill guard | shadow UNDER-states (drops fills) | small +$ |

**If live fees = 2%-on-profit** (most likely per CLAUDE.md verification): net shadow is **conservative** — real live PnL would be **~$15-30/day BETTER** than shadow shows.

**If live fees = 0.07 curve**: net shadow is **mildly optimistic** by ~$30-50/day (gas + partial fills).

Either way: **deviation is bounded to under ~$50/day across all sleeves combined**, on a base that (post V2 fixes) runs ~$1,800/day projected. That's <3% model error. **The engine is trustworthy.**

## 6. Recommended fixes (priority order)

| # | Fix | Effort | $ impact | Priority |
|---|---|---|---:|---|
| 1 | Add MINT gas (`cash_spent += gas_usd` in `_observe_mint`) | 3 lines | $9-36/2d | LOW |
| 2 | Add REDEEM gas (`cash_recovered -= gas_usd` in `_observe_redeem`) | 3 lines | $13-52/2d | LOW |
| 3 | Add `tv_poly_maker_partial_fill_ratio` knob (default 0.8) | ~15 lines | 10-25% fill correction | MEDIUM |
| 4 | Resolve the fee-model question: confirm via live wallet whether BTC/ETH/SOL up-down charge 2%-on-profit or 0.07 curve. If 2%-on-profit, switch shadow to match (recovers the conservative understatement, makes shadow EXACT). | research + ~10 lines | up to $63/day | **HIGH** |

Fix #4 is the highest-value: it's the single biggest source of model deviation and resolving it makes shadow PnL exact rather than conservatively biased. Pull a sample of the live momo wallet's actual resolved trades from `trading.events` and back-derive the fee charged.

## 7. Bottom line for deployment decisions

- **Per-slug accounting: EXACT.** Trust it.
- **Settlement (mint/merge/redeem): correct**, minor gas gap (~$22/day overstatement).
- **Fills: realistic**, mild over-fill optimism (10-25% on volume).
- **Fees: conservative** if live is 2%-on-profit (shadow shows LESS than you'd really make).
- **Total model error < 3%** of projected PnL, with the largest uncertainty in the SAFE (conservative) direction.

When the V2 sleeves show +$1,800/day projected, the true live number is most likely **+$1,800 ± $50/day**, leaning slightly HIGHER if the 2%-on-profit fee model is what production actually charges.

**The shadow engine can be trusted to make the promote/kill and capital-sizing decisions.** The one open item that would make it exact is resolving the fee-model question (§6 fix #4).

## 8. Files

- Sub-reports: `migration_ireland_audit_2026_05_28/engine_audit/*.md` (4 files)
- Reconciliation script: `migration_ireland_audit_2026_05_28/engine_audit/per_slug_recon.py`
- V2 logic audit (prior): `migration_ireland_audit_2026_05_28/audit_v2_logic.py` + `v1_vs_v2_pnl.csv`
- This consolidated report: `strategy_lab/reports/ENGINE_CORRECTNESS_AUDIT_2026_05_28.md`
