# B945 Inventory Sum-Arb Decode — 2026-06-12 (RECONCILED r3)

**Wallet:** `0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68` (@l5zn1bwom8etsk, `Noisy-Colonisation`)  
**Operator Hypothesis:** temporal sum-arb = accumulate both sides inside a slug at combined cost < 1.00/share-pair, via resting maker + taker recalibration  
**Scripts:** `strategy_lab/wallet_hunt/_b945_inventory_decode.py` (fill-level decode) + `_b945_reconcile.py` (full-window ledger, REDEEM ground-truth, weekly attribution)  
**Artifacts:** `cache/0xb945945d/per_slug_paired_ledger.parquet` (1,564 slugs, full window) + `fill_tape_full.parquet` (144,584 fills)

---

## §0 RECONCILIATION (r3 — supersedes r2 PnL numbers; see `B945_PNL_AUDIT_2026_06_12.md`)

### r3 verdict (2026-06-12 PnL audit)

**TRUE lifetime PnL = +$21,742 (LB canonical, fresh Jun-12 API).** This supersedes r2's +$10k estimate.

r2 computed `redeem − spent + rebates` from `fill_tape_full.parquet` and got ~+$10k. The discrepancy:
- **fill_tape_full covers only 88.4% of true fill costs** (token→slug mapping fails for 11.6% of fills). The unmapped P2P fills (direct counterparty fills bypassing e111, $30,731 from 6,998 ERC20 rows paired with ERC1155-IN) were missing from fill_tape entirely — appearing as cost=$0 in the per-slug ledger (top-10 profit slugs all show cost=0, an artifact).
- The **fresh API has 2,041 REDEEM events** (+31 new vs stored 2,010) and **$3,645 REBATE** (+$23 / 1 new event).
- LB = `REDEEM($1,352,604) + REBATE($3,645) − all_fills($1,334,507) = $21,742`. Chain-verified: our classified fills (e111=$1,077,464 + CLOB=$208,737 + P2P=$30,731 + Jun11-12 gap=$7,979 not yet in tape) = $1,324,911 → remainder ~$9,596 in USDCE-era fills beyond tape = total $1,334,507 ✓.

**Attribution direction unchanged:** paired sum-arb capture is still the profit engine. The per-slug magnitudes scale proportionally: at $21,742 true net on 2,041 slugs = **+$10.65/slug** (vs r2's +$6.4/slug). The weekly table amounts in §0 below are understated by ~2.2× (r2 undercounted fills, not income). Mechanism decode (§2–§6) is unaffected — it depends on pvs distributions and WR, not dollar totals.

**r2 formula was correct conceptually** (`REDEEM + REBATE − costs`) but applied to an incomplete cost basis. Do not use `_b945_reconcile.py` per-slug totals for dollar attribution; use LB directly.

---

## §0 RECONCILIATION (r2 — superseded by r3 above; structural findings still valid)

The r1 report concluded net −$10.28/slug, contradicting the wallet's positive chain-true PnL. Three artifacts found and fixed:

1. **Stale fill tape.** The saved `fill_tape.parquet` was the EARLY 44%-coverage build (67,859 fills, Mar 28→May 15, 827 slugs). The `_tape_build.log` shows the final tape was 144,589 fills Mar 28→Jun 10 (1,564 slugs) at 88.4% coverage — it was never persisted to disk. Rebuilt in `_b945_reconcile.py` from `alchemy_transfers` + the full 3-source token lookup (base `_token_lookup` + ext + clob cache) + pUSD/USDCE outflows → `fill_tape_full.parquet` (144,584 fills, 1,564 slugs, 1,562 resolved: 1,415 canonical/HF, 147 REDEEM-inferred).

2. **Fee double-count.** r1 applied the `0.07·p·(1−p)` winner-fee to redeem income. Chain ground truth (activity_REDEEM, 2,010 events Mar 19→Jun 11): **redeems pay the full $1.00/share** — our winner-side share count matches redeem USDC **exactly** (ratio median 1.000; 99.8% of 1,412 testable slugs within 5%). Any fee he pays is already embedded in the fill `usd` outflow. Applying the 0.07 model on top double-charged ~$18k and manufactured the fake −$10.28/slug.

3. **Chain-true anchor corrected.** Raw chain cash flow (erc20 in − pUSD deposits − erc20 out) = **+$9,749**. Per-slug GT (redeem − spent) = +$6,378 + rebates $3,623 = **+$10,001**. The two agree (gap = open positions/timing). The handoff's "+$15.7k chain-true" is overstated ~1.6×, the leaderboard's $20.6k ~2×. **True lifetime profit ≈ +$10k on ~$1.24M volume (~0.8%).**

### Weekly attribution (GT fee-free basis; rebates by actual event timestamp)

| ISO week | n slugs | paired $ | residual $ | GT trade $ | rebate $ | net $ | cum $ | pvs med | %pvs<1 |
|---|---|---|---|---|---|---|---|---|---|
| W13 (Mar 28) | 10 | +13 | +25 | +3 | 0 | +3 | +3 | 0.974 | 30% |
| W17 (Apr 21+) | 140 | +3,197 | −1,560 | +1,638 | +476 | +2,114 | +2,117 | 0.964 | 72% |
| W18 | 313 | +9,418 | −7,471 | +1,947 | +878 | +2,825 | +4,942 | 0.966 | 70% |
| W19 | 231 | +976 | −3,392 | **−2,417** | +620 | **−1,796** | +3,145 | **0.991** | **58%** |
| W20 | 184 | +2,759 | −1,661 | +1,099 | +313 | +1,412 | +4,557 | 0.974 | 71% |
| W21 | 211 | +4,709 | −3,351 | +1,185 | +355 | +1,541 | +6,098 | 0.973 | 74% |
| W22 | 182 | +6,069 | −4,807 | +1,282 | +278 | +1,561 | +7,659 | 0.954 | 86% |
| W23 | 201 | +5,913 | −3,929 | +2,003 | +473 | +2,477 | +10,135 | 0.965 | 79% |
| W24 (→Jun 10, partial) | 90 | +2,416 | −3,189 | −362 | +227 | −135 | +10,001 | 0.959 | 74% |

Cumulative tracks chain equity: ~+$10k by Jun 10, growth starting W17 (he effectively launched Apr 21; W13 was a 10-slug trial). **7 of 9 weeks net-positive — no losing→winning flip; he was profitable from launch.** The r1 net-negative picture was entirely the fee double-count + truncated tape.

### What a losing week looks like (operator Q2)

The one material loss week (W19, −$1.8k net) is a **paired-capture compression, not a residual blow-up**: pvs median jumped to 0.991 (vs 0.954–0.974 in winning weeks), %slugs pvs<1 fell to 58% (vs 70–86%), paired profit collapsed to +$976 (vs +$2.7–9.4k) while the residual drag stayed normal (−$3.4k vs −$1.6 to −4.8k). Win-vs-loss-week per-slug: paired +$25.8 vs +$10.6; residual −$18.3 vs −$20.5 (flat). **His PnL is one-factor: the achieved discount vs 1.00. When the market quotes tight, he bleeds.**

---

## §1 Per-Slug Paired-Cost Ledger (FULL window, r2)

**Universe:** 1,564 slugs Mar 28→Jun 10, 1,562 resolved. Pairing: pairs = min(qty_up, qty_dn); pvs = vwap_up + vwap_dn.

### PVS distribution

Median pvs 0.954–0.991 by week (typical ~0.97); ~70–86% of slugs land pvs < 1.00 in winning weeks (58% in the loss week). (r1 sub-window numbers: 67% < 1.00, 47% < 0.97, 33% < 0.95, 11% < 0.90 — distribution shape carries over.)

### PnL attribution (GT fee-free basis, 1,562 settled slugs)

| Component | Total | Per slug |
|---|---|---|
| **paired (sum<1 capture)** | **+$35,470** | **+$22.71** |
| **residual (directional excess)** | **−$29,335** | **−$18.78** |
| trade PnL | +$6,135 (≈ GT +$6,378) | +$4.24 |
| maker rebates | +$3,623 | +$2.32 |
| **net** | **≈ +$10,001** | **≈ +$6.4** |

**The paired sum-arb capture is the ENTIRE profit engine (+$35.5k gross).** The residual is a large persistent drag: the excess (unpaired) side wins only **37.3%** — systematically below 50%, because the clip∝price ladder accumulates MORE shares on whichever side gets cheap, and the cheap side loses more often (favorite-longshot arithmetic). Rebates add ~$40/day (36% of net).

### Sanity checks (operator Q3)

- **(a) Residual pricing:** residual legs priced at the side's full-slug vwap (same vwap as paired). Validated against REDEEM ground truth: our winner-side shares == actual redeem USDC for 99.8% of 1,412 testable slugs (median ratio 1.000, only 3 slugs off ≥5%). The fee-free totals reconcile with raw chain cash flow within $250.
- **(b) Coverage bias:** NONE. Winner-side shares match redeems exactly; corr(coverage ratio, residual_pnl) = 0.045. The ~7–11% unmapped fills belong to slugs absent from the ledger entirely (both legs missing), not one-legged contamination. The residual drag is real, not a missing-hedge-leg artifact.

---

## §2 Side-Decision Rule at Fill Level (r1, 67k-fill ml_features sample — unchanged)

| Predictor of which side he buys | Hit rate |
|---|---|
| Inventory (hedge=buy short side 47% / rebal=add to long side 47%) | legs ~50/50 |
| Relative price (buys cheaper side) | 55% |
| Oracle direction bret5 | 50.5% (coin flip) |
| Oracle direction rtds_ret5 | 53.8% |

**No side-selection signal.** `hedge` fills buy the less-held side, `rebal` adds to the more-held side — both are consequences of a passive two-sided ladder being hit, not decisions.

---

## §3 Maker vs Taker Split (r1 — unchanged)

~50/50 at-ask vs at-bid on EVERY leg (overall 48.3% / 47.5%). Taker rate FLAT-to-LOWER at high inventory imbalance (q1 49.4% → q4 47.0%) — **opposite of a taker-recalibration trigger.** Fill discount vs ask ~0.007 uniformly across legs.

---

## §4 Timing of Second Side (r1 — unchanged)

Both sides open near-simultaneously: median lag 34s, 72% within 60s, 92% within 120s; first fills ~62–64s into the 900s window; no side priority (Up first 52%). No "accumulate one side then hedge" phase.

---

## §5 Decoded Decision Rule

> At slug open (~60s in), place limit-buy ladders on BOTH Up and Down simultaneously, clip∝price (big clips cheap, small clips dear). Requote sub-second, following price. Accumulate whatever fills; never sell; hold everything to resolution. No oracle signal, no taker-rebalance trigger, no visible inventory cap. Economics: fills average ~0.7¢ below ask; the two-sided vwap sum lands < 1.00 in ~3 of 4 slugs (median ~0.97), so paired inventory locks ~3¢/pair gross (+$22.7/slug). The unavoidable byproduct — excess inventory concentrated on the cheap side — wins only 37% and gives back ~80% of the paired profit (−$18.8/slug). Net ≈ +$4.2/slug + $2.3/slug rebates.

---

## §6 VERDICT (r2): **CONFIRMED on the economics, REFUTED on the mechanism**

- **CONFIRMED — "combined cost per share-pair < 1.00" IS his edge:** paired capture +$35.5k gross is the only profit source; the losing week is exactly the week the discount compressed (W19 pvs 0.991). His true +$10k = paired (+$35.5k) − residual drag (−$29.3k) + rebates (+$3.6k).
- **REFUTED — "rest maker one side, taker-recalibrate on imbalance":** taker rate flat vs imbalance; both sides open simultaneously; ~50/50 maker/taker everywhere; no recalibration trigger exists. He is a symmetric passive two-sided price-following ladder, hold-to-resolution.
- **Where the profit comes from (operator Q4):** steady +$1.2–2.8k/week from the Apr 21 launch; one-factor = achieved discount vs 1.00. NOT residual luck (residual is a consistent cost), NOT a specific lucky era, rebates ~17% of net. **Lifetime = +$21,742 (LB canonical, r3 CORRECTED).** r2's +$10k was based on incomplete fill_tape (88.4% coverage); the +$15.7k "chain-true" in the original handoff was wrong formula; the $20.6k LB was stale (now $21,742).

### Is the two-sided proportional-ladder maker sim still warranted?

**YES — reconciliation strengthens the case** (paired capture is real, persistent, survives a 37%-win residual drag), but it must differ from the dead static ladders (arms C/D, `MAKER_QUEUE_SHADOW_RESULTS_2026_06_12.md`, −0.24..−0.41/win SIG-NEG) in four ways:

1. **Two-sided simultaneous quoting** (C/D were one-sided) and **slug-level paired scoring**: the PnL unit is pairs × (1 − pvs) + residual at resolution. Per-fill markout scoring — which killed C/D — is the wrong objective for this strategy.
2. **Price-FOLLOWING requotes** (C/D static): ladder tracks the book sub-second.
3. **Clip∝price sizing**: this creates the cheap-side excess; the sim must reproduce the real residual drag (−$18.8/slug at 37% residual win rate), not assume balanced fills.
4. **Chain-true accounting**: redeems pay full $1/share; charge fees only on our own taker fills (live 0.07 curve); maker $0 + rebate.

**Go/no-go gate:** the sim must achieve pvs ≲ 0.98 at ~44% pair fraction with realistic queue position. If our queue fills can't reach pvs < 0.98 (he requotes sub-second with infra we don't have), the edge is his execution+rebate moat, not a replicable signal — consistent with the prior session's conclusion.

**Sizing caveat:** even HIS realized edge is ~0.8% of volume (+$10k on $1.24M), of which 36% is rebates we may not match. This is an infra-margin business, not an alpha business.

---

## Key Numbers (r2)

| Metric | Value |
|---|---|
| Full tape | 144,584 fills, 1,564 slugs, Mar 28→Jun 10 |
| Chain-true lifetime net | **≈ +$10.0k** (GT +$6.4k trade + $3.6k rebates; naive chain flow +$9.7k). Handoff $15.7k / LB $20.6k overstated |
| pvs median | ~0.97 (weekly 0.954–0.991); %pvs<1 = 70–86% winning weeks, 58% loss week |
| Paired capture | +$35,470 (+$22.71/slug) — all of the profit |
| Residual drag | −$29,335 (−$18.78/slug); residual side wins only 37.3% |
| Rebates | +$3,623 (~$40/day, 36% of net) |
| REDEEM validation | winner shares == redeem USDC, ratio 1.000, 99.8% within 5% (n=1,412) |
| Coverage bias | none (corr 0.045) |
| Maker/taker | ~50/50, flat vs imbalance — no recalibration trigger |
| Second-side lag | median 34s (simultaneous two-sided) |
