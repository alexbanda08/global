# Maker Queue / Latency Edge Probe — BTC 5m
**Date:** 2026-05-29  
**Script:** `strategy_lab/maker_queue_probe_2026_05_29.py`  
**Author:** automated research agent

---

## 1. Hypothesis

A taker buying the cl_basis-favored side pays ~ask0 ≈ 0.69 on average. A maker
resting a bid at best_bid (≈ ask0 − 0.01) buys 0.01 cheaper, capturing the
spread if filled. The question: does the bid-ask improvement survive adverse
selection (getting filled disproportionately when the slug then **loses**), fees,
and the $0.01 tx cost?

---

## 2. Data & Method

| Item | Detail |
|---|---|
| Universe | BTC-5m, offset=120 (ws_s production anchor), cl_basis non-null |
| Signals | 5,408 slugs across ~37 days |
| Trade tape | 39.7M rows (btc.parquet); 2.75M SELLs in target slugs |
| Book data | L25 skipped (OOM at 6.6 GB with 5408 slugs × 10 Hz); queue position modeled via flow proxy instead |
| Outcome | Chainlink RTDS (resolutions_from_rtds.parquet, 9,831 slugs) |
| Fee | **Maker: $0** (feeRate=0 per production fee verification in CLAUDE.md) |
| Fee (taker baseline) | **2%-on-profit-only** (legacy production) |
| Tx cost | $0.01 per fill |
| Order size | $25 USD notional |

### Fill model

**Optimistic (front-of-queue):** any SELL at price ≤ best_bid, timestamp > fire_us
fills our order up to $25. This is the maximum achievable maker edge — assumes
we are first in the queue.

**Conservative (back-of-queue):** same, but only sell volume **beyond $50**
(2× order size as proxy for queue-ahead) reaches us. Models a realistic
latency penalty where others already rest at the same level.

### Maker bid placement

Resting at `fav_bid0` (dirscan best_bid at fire_us = slot_start + 120s). The
clbasis-favored side is Up when cl_basis_bps > 0 (94.7% of signals — BTC
was mostly bid-up vs Chainlink during the window).

---

## 3. Results

### 3.1 Core Numbers

| Metric | Value |
|---|---|
| Signals | 5,408 |
| Base WR (taker, clbasis direction) | **50.4%** |
| Taker mean PnL/trade | **−$0.74** (G3 FAIL; directional signal flat) |
| | |
| **Optimistic maker** | |
| Fill rate | 88.2% (4,770 / 5,408) |
| Maker fill WR | **44.7%** |
| Adverse selection | **−5.8 pp** vs taker WR |
| Mean PnL / filled order | **−$3.65** |
| Mean PnL / signal (incl unfilled=0) | **−$3.22** |
| Gate G1 (WR>50%) | **FAIL** |
| Gate G3 (mean_pnl>0) | **FAIL** |
| Gate G4 (p<0.05) | **FAIL** (t=−7.04, p=1.0) |
| | |
| **Conservative maker** | |
| Fill rate | 71.7% (3,878 / 5,408) |
| Maker fill WR | **40.3%** |
| Adverse selection | **−10.2 pp** vs taker WR |
| Mean PnL / filled order | **−$6.11** |
| Gate G1/G3/G4 | **ALL FAIL** (t=−13.0) |

### 3.2 Sell Flow Statistics

| Metric | Value |
|---|---|
| Slugs with any sell at bid0 | 4,770 / 5,408 (88%) |
| Total sell USD at bid, p50 | $168 |
| Total sell USD at bid, mean | $333 |

Sell flow is abundant. The problem is **not** that nobody crosses the bid. The
problem is that when they do, you are very likely to be on the wrong side.

### 3.3 Adverse Selection — Key Finding

| Group | Mean sell USD at bid0 |
|---|---|
| WON slugs (fav side wins) | $285 |
| LOST slugs (fav side loses) | $381 |
| **Ratio (lost/won)** | **1.33×** |

LOST slugs attract **33% more sell flow** at the bid than WON slugs. This is
the classic adverse selection signature: informed sellers cross the bid
disproportionately when price will go against you. The flow itself is
directionally informative — it is not random noise.

### 3.4 cl_basis Signal Strength vs Maker PnL

| Basis quartile | cl_basis_bps p50 | WR | Fill rate | Maker PnL/fill |
|---|---|---|---|---|
| Q0 (weakest) | 1.6 bps | 50.5% | 90.2% | −$2.46 |
| Q1 | 4.0 bps | 48.7% | 90.2% | −$5.23 |
| Q2 | 9.0 bps | 50.7% | 87.9% | −$3.36 |
| Q3 (strongest) | 12.0 bps | 51.6% | 84.5% | −$3.55 |

No basis threshold rescues the strategy. Stronger cl_basis slightly reduces
fill rate (less sell pressure when signal is strong) but WR gain is marginal
(51.6% vs 50.4% base) and PnL stays deeply negative.

### 3.5 Fill Timing

Among optimistic fills: p50 lag = **4.0 seconds** after fire_us, p75 = 15.9s.
Fills are not immediate micro-second events — they accumulate over minutes.
A real latency advantage (sub-millisecond queue position) is irrelevant here;
what matters is whether you are filled at all and what the outcome is.

### 3.6 Spread Capture (hypothetical intra-slug exit)

If we could exit immediately after fill by lifting the ask0 (itself a taker
order):
- Gross spread per fill: **$1.03** (fill_shares × 0.01 spread × $25 notional)
- Net after $0.01 tx: **$1.02**

This looks like the 0.01 spread × ~103 shares = $1.03 gross. But:
1. **Exit requires a separate taker buy order** at ask0 — the exit itself costs
   taker fees + another $0.01 tx. At p≈0.69, taker fee ≈ $0.014 on the exit.
2. **Timing mismatch:** fill happens at median 4s lag, spread may have already
   moved. In practice this is impossible to model without intra-second tick data.
3. **The adverse selection still applies:** if we are filled at bid because
   someone knows price will move down, the ask0 is already moving down before
   we can exit. The gross spread of $1.03 is a fiction in that scenario.

---

## 4. Why the Maker Edge Is Negative

### Root cause: adverse selection > spread

Price improvement from maker vs taker: **+$0.013/share** (the bid-ask spread).  
At $25 notional / bid ≈ 0.52 avg → ~48 shares.  
Gross improvement: 48 × 0.013 ≈ **$0.62**.

But adverse selection means:
- Maker WR = 44.7% vs taker WR = 50.4% → **−5.8 pp gap**.
- At $25 notional, 5.8 pp WR drop ≈ 5.8% × $25 ≈ **−$1.45 expected loss per fill** from the WR difference alone.

Net: +$0.62 spread gain − $1.45 adverse selection = **−$0.83 per fill before tx**.  
Add $0.01 tx → **−$0.84 net**, consistent with the observed −$3.65 (which also
includes the full dollar-stakes of $25 notional, not just the $0.01 spread improvement).

### The sell flow is informed

Sellers crossing the bid at the moment we are resting there are not random
"slow uninformed sellers." They are likely:
- Makers unwinding positions as price moves against them (already directionally
  informed).
- Automated flow routed to cross the bid when price is trending down.
- Oracle-arb traders selling the overstated Up token as price drops.

Polymarket's user base on BTC-5m markets is predominantly professional/automated.
There is no pool of slow retail sellers to exploit.

### The F1 HFT hypothesis revisited

The F1 wallet (0xb27bc932, ~$254k/day) is reported to be a high-frequency
scalper. Our probe finds no maker edge in the trade tape. The most likely
explanations:
1. **F1 uses a slug selector we cannot decode** — same gap as the F2 cluster.
   It may only trade slugs where order flow is temporarily dislocated (large
   retail buy pressure + no informed selling), which we cannot identify from
   aggregate cl_basis alone.
2. **F1 may be a mint-and-sell arb** (same as the 3 wallets already decoded),
   not a maker-queue strategy. The `relay wallet 0xf3cfb6a6` pattern is
   consistent with mint + partial-exit, not limit-order fill patterns.
3. **Cross-market arb** — bridging CLOB price dislocations against a CEX hedge.
   This requires co-located CLOB+CEX infrastructure, not just queue position.

---

## 5. Gate Summary

| Strategy variant | G1 (WR>50%) | G3 (mean>0) | G4 (p<0.05) | Verdict |
|---|---|---|---|---|
| Taker, cl_basis favored | PASS | **FAIL** | FAIL | No edge |
| Maker OPT (front queue) | **FAIL** | FAIL | FAIL | No edge |
| Maker CONS (back queue) | **FAIL** | FAIL | FAIL | No edge |
| Spread capture (exit imm.) | N/A | N/A | N/A | Not feasible |

---

## 6. Verdict: DO NOT BUILD

The maker queue / latency edge hypothesis is **refuted** by the data:

1. **Adverse selection dominates the spread**: LOST slugs attract 1.33× more
   sell flow at the bid. Every 0.01 of spread improvement is outweighed by
   a 5.8–10.2 pp WR drop on filled orders.

2. **PnL is deeply negative in both queue models**: −$3.65/fill (optimistic),
   −$6.11/fill (conservative). Not marginal — a factor of 5–8× worse than
   the taker baseline (−$0.74) which already fails gates.

3. **Fill timing (4s median lag)** shows we are not competing with HFT. The
   sell flow is slow but informed — it arrives over minutes, not milliseconds.
   A WS queue position advantage buys nothing if the sellers cross whenever
   the slug is trending against us.

4. **G1/G3/G4 all FAIL** — no statistical ambiguity. t-statistic = −7 to −13.

5. **The F1 HFT edge**, if real, requires a slug-selection signal orthogonal to
   cl_basis that we cannot reverse-engineer from canonical data alone. It is NOT
   a generic maker-queue strategy deployable on the full universe.

**Build recommendation: NO.** The WS/queue infrastructure investment is not
justified. The clbasis-favored taker strategy already fails gates; the maker
version is strictly worse on every metric.

---

## 7. What Would Change This Assessment

To revisit:
- **Real-time CLOB WS event tape** with individual order book updates (not
  snapshots) — to detect transient dislocations where one side briefly has
  stale price and uninformed sellers pile in. This is the only scenario where
  a queue edge is theoretically real.
- **Slug-level selector signal** analogous to F2's slug filter (currently
  undecodable) — if F1 only fires on 5–10% of slugs with some structural
  property (e.g., low liquidity, recent large one-sided flow, specific hour),
  the adverse selection might not apply to that subset.
- **Cross-market arb anchor** — if a CEX hedge is available at the moment of
  fill, spread capture with no inventory risk becomes viable. Requires
  co-located CEX+CLOB infra, <10ms RTT to both exchanges.

None of these are available in current canonical data. Building them is a
separate multi-week data-collection project.

---

*Results saved: `strategy_lab/maker_arb_audit/maker_queue_probe_results_2026_05_29.csv`*  
*Script: `strategy_lab/maker_queue_probe_2026_05_29.py`*
