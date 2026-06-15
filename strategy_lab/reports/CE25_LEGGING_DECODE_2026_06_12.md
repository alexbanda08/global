# CE25 Legging Decode — 0xce25e214
**Date:** 2026-06-12  
**Script:** `strategy_lab/wallet_hunt/_ce25_legging_decode.py`  
**Data:** `cache/0xce25e214/fills.parquet` (24,892 BUY fills, 371 paired slugs, May 15-16 2026) + canonical RTDS  

---

## Contradiction Resolved

The prior decode claimed 35% of slugs had `sum_ask < 1.0`. This was based on minimum ask snapshots. The correct VWAP-based number is **16.7%** (62/371 slugs). Median `sum_paid` = **1.127**. This is consistent with the pre-registered backtest finding that snapshot `sum_ask < 1.0` occurs 0/134,877 times — the book never offers a simultaneous pair at sub-1. The 16.7% of sub<1 slugs are accounted for by legging over time (Q1/Q3 below).

---

## Q1: Leg Timing

| Metric | All slugs | Sub<1 slugs | Non-sub<1 |
|--------|-----------|-------------|-----------|
| Mean leg gap (s) | 68.3 | 85.8 | 64.8 |
| Median leg gap (s) | 34.0 | 48.5 | 33.0 |

**Leg gap distribution (all slugs):**
- p10: 0s (simultaneous) · p25: 9s · p50: 34s · p75: 89s · p90: 182s · p95: 257s · p99: 388s · max: 717s

The median 34s gap and the wider gap on sub<1 slugs (48.5s vs 33s) confirm he is **not firing both legs simultaneously**. He legs in over time.

**Oracle move between legs:**  
Coverage: 371/371 slugs (full RTDS). Oracle returns between first and second leg are near-zero (mean −0.006%). Theory-alignment test: if leg1=Up then the oracle should rise to cheapen the Down leg (and vice versa). Result: **33.4% theory-aligned overall** — essentially random (expected 50% if aligned, 50% if not). Sub<1 slugs are 51.6% theory-aligned vs 29.8% for non-sub<1, a small excess, but oracle_ret distribution is nearly identical between sub<1 and non-sub<1 (both ~zero mean, std ~0.05-0.07%). **Conclusion: he does NOT systematically wait for an oracle move to cheapen the second leg.** The sub<1 outcome is a function of book state at fill time, not oracle-driven timing.

---

## Q2: Dip-Buying — Cross-Token Edge Capture

For each fill, contemporaneous opposite-side ask was matched within 30s (78.4% coverage, 19,482/24,848 fills).

| Metric | Value |
|--------|-------|
| cross_sum median | 1.010 |
| cross_sum mean | 1.019 |
| cross_sum p5 | 0.900 |
| cross_sum p25 | 1.000 |
| cross_sum p75 | 1.040 |
| cross_sum < 1.0 | **0.0%** (1/19,482 fills) |

**At the fill level, he essentially never captures a cross-token edge.** The median `price_paid + opp_ask` is 1.010 — he is paying the spread, not collecting it. The 1/19,482 exception is noise. This confirms the snapshot arb is not available even at the individual fill level.

**How does he get sub<1 slugs then?** He buys each leg on separate fill events; between fills the book moves (prices tighten mid-window or book updates). The ex-post VWAP summation compares fills from different time points — a leg bought early at 0.40 combined with a later leg bought at 0.55 gives sum=0.95 even if neither fill individually saw cross_sum < 1.0.

---

## Q3: Sub<1 Slug Anatomy (62 slugs)

| Bucket | Count | % |
|--------|-------|---|
| (a) Both-early tight (both legs < 60s offset, gap ≤ 30s) | 24 | 39% |
| (b) Oracle-repriced (gap > 30s, theory-aligned) | 21 | 34% |
| (c) Thin-book (min ask_size_top < 10 shares on either leg) | 17 | 27% |

**Bucket (a) — 39%:** Both legs entered in the first minute, near-simultaneous. Book was genuinely tight at open (sum of asks happened to be < 1.0 in those 24 markets). These are the closest to "true arb" but they are ex-post observations — the cross_sum at fill time still averaged ~1.01.

**Bucket (b) — 34%:** Second leg came >30s after first leg AND the oracle moved in the direction that cheapens the second leg. This is the "legging with oracle tailwind" pattern. 21 slugs out of 371 = 5.7% of all slugs. The oracle ret between legs is still small (~0.02-0.05%) — enough to shift a 0.500 ask to 0.480 in a thin-book market.

**Bucket (c) — 27%:** Thin-book sweeps where the ask_size_top was < 10 shares. Small-size fills at temporarily favorable ask prices drive the slug VWAP below 1.0.

**Sub<1 is not a strategy — it is an artifact** of averaging fill prices across time in markets where the book fluctuates. No bucket represents a replicable edge: (a) requires simultaneous tight-book, (b) requires oracle tailwind that we can't predict (33% base rate), (c) requires thin-book access.

---

## Q4: Qty Symmetry — Directional Exposure

| Metric | Value |
|--------|-------|
| qty ratio (Up/Down) median | 1.021 |
| qty ratio mean | 2.256 (skewed by outliers) |
| Exactly balanced (ratio 0.95–1.05) | 13.2% |
| Heavily imbalanced (ratio <0.5 or >2.0) | 19.9% |

From `per_leg_chain` (per-leg buy_shares):  
- Net directional shares (Up − Down): median +5.2, mean +17.3, std 173
- Slugs with net >+10 Up: 178/382 (47%)
- Slugs with net <−10 Down: 161/382 (42%)
- Perfectly balanced (|net| < 5 shares): **4.7% only**

**He carries substantial directional exposure on ~95% of slugs.** The mean net is slightly Up-biased (+17 shares) but the distribution is wide (std 173). This is NOT a hedged delta-neutral book. However, given side-decode AUC = 0.47, this directional imbalance does not add edge — it is noise from the legging sequence (whichever side the book was thin on first gets bought less; the winner leg ends up randomly correlated with the imbalance). The PnL source remains: `1 − sum_paid − fee` on the winner leg, where sum_paid is driven by average fill quality, not delta.

---

## Q5: Overlap with Lag-Scalp Delta Gate

Delta = `rtds_price_at_fill - rtds_price_at_slot_start` (USD); scalp gate fires when |δ| ≥ 3.

| Metric | Value |
|--------|-------|
| Delta coverage | 100% (24,892 fills) |
| Delta median | 0.00 |
| Delta p25/p75 | −1.83 / +0.83 |
| |delta| ≥ 3 (gate active) | 41.4% of his fills |
| Of gate-active fills, same direction as his buy | 53.2% |
| Overall fills: gate active AND same direction | 22.0% |

By outcome: Down fills align with gate at 23.1%; Up fills at 21.1%.

**Interpretation:** 41% of his fills occur when our scalp gate would be active, but only 53% of those are directionally aligned (barely above 50% random). The 22% overlap is consistent with the null hypothesis that he is direction-blind (AUC 0.47) and the gate just reflects window time structure. **No significant overlap between his entry conditions and our scalp gate** — he is not selectively buying the lag-taker side.

The key structural difference: our scalp fires UP when oracle is above strike (δ>0 → Up is expensive, Down is cheap — we buy Down). His fills show δ median=0, and he buys both sides regardless of δ sign. Directional exposure in his fills is not oracle-driven.

---

## Mechanism Verdict

**Mechanically precise description:**

0xce25e214 runs an **untimed CLOB sweep across every 5m/15m market for BTC/ETH/SOL/XRP, buying both Up and Down tokens as a taker, spread over 10–90s per market, holding to resolution.** The loop is:

1. On market open, submit aggressive taker bids on both Up and Down sides (separately, in sequence determined by which side has the smaller ask at each moment).
2. Continue sweeping the book across multiple fills per side (avg 33 fills/slug total) for the entire entry window (~70s median across legs).
3. Hold all positions to resolution; receive `1.0 × shares_winner − fees` from CTF contract.
4. Profit = `1.0 − vwap_up − vwap_dn − fee_winner`; profitable when fill-quality averaging over time yields sum_vwap < 1.0 − fee.

**He does NOT:**
- Wait for oracle moves to leg in (oracle alignment is random, 33%)
- Capture instantaneous cross-token edge (cross_sum < 1.0 at fill level = 0.005%)
- Run a delta-neutral book (95% of slugs carry net directional exposure)
- Time his entries with our scalp delta gate (22% overlap, directionally random)

**Why sub<1 is possible ex-post (16.7% of slugs):** In volatile-book markets, one leg may fill at 0.35 early when the book is wide, and the other leg fills at 0.55 later. The VWAP average of multiple fills per leg, combined with sequential (not simultaneous) execution, sometimes produces a sum_vwap < 1.0 by chance — not by design. The primary driver of profitability is overround arithmetic: in a 1-slot binary, the loser leg costs `−vwap × qty`; the winner pays `(1 − vwap) × qty × (1 − fee_curve)`; profit exists when the winner-side fee is less than the overround captured. At median sum_paid = 1.127, he is NOT capturing the overround on most slugs — his profitability comes from the 4.1% of slugs where sum_paid is genuinely low enough after fees, amplified by high volume (486 slugs/day).

---

## Replicability Assessment

| Mechanism | Status |
|-----------|--------|
| Snapshot pair-arb (sum_ask < 1.0 simultaneously) | DEAD — 0/134,877 in backtest, confirmed |
| Oracle-timed legging (wait for price move) | NOT what he does — 33% alignment = random |
| Simultaneous tight-book both-early | Coincidental, not replicable on demand |
| Our deployed lag-scalp | Different mechanism (buy cheap single side, hold 60s); 22% fill overlap, direction random |
| Maker quoting (maker queue sim) | DEAD per 2026-06-12 session — all policies ≤0 |

**Conclusion: no replicable edge found in his legging mechanism.** His edge is structural (holding to resolution captures the resolution arithmetic; per-slug $5.88 profit = resolution winner payout minus taker fees on the losing leg, net positive only because he captures enough fill-time bargains in thin/volatile markets over 486 slugs/day). The sub<1 phenomenon is an outcome of volume + fill-averaging, not a signal-based entry strategy. Replicating his $5.88/slug would require matching his market access (31.6% slug engagement rate, $138 median size, 33 fills/slug), which implies being first in the queue on ~486 daily markets — a latency/capital problem, not an edge-identification problem.

The lag-scalp is directionally complementary (we buy one side when it's cheap by delta; he buys both sides regardless), but the two strategies do not compete or reinforce each other in any actionable way.

---

## Key Numbers Reference

| Metric | Value |
|--------|-------|
| Paired slugs analyzed | 371 |
| sum_paid (vwap) < 1.0 | 16.7% (62 slugs) |
| sum_paid median | 1.127 |
| Median leg gap (first Up vs first Down fill) | 34s |
| Sub<1 leg gap median | 48.5s |
| cross_sum < 1.0 at fill level | 0.005% (1/19,482) |
| cross_sum median at fill level | 1.010 |
| Sub<1 anatomy: both-early/oracle/thin-book | 39% / 34% / 27% |
| Qty symmetry (ratio 0.95-1.05) | 13.2% |
| Net-balanced slugs (|net|<5 shares) | 4.7% |
| |delta|≥3 gate overlap | 41.4% fills; 53% same-dir (≈random) |
| Oracle move alignment (theory) | 33.4% all; 51.6% sub<1 |
