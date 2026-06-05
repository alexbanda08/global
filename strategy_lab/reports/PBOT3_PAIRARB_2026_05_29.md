# PBot-3 (0x74a2b82f) — Pair-Arb Economics Deep-Dive
**Date:** 2026-05-29 | **Analyst:** Claude Sonnet 4.6

---

## 1. Data Coverage

- **Trades file:** 3,500 rows (Polymarket /trades API limit), Dec 31 2025 - Mar 6 2026 (65 days)
- **Unique slugs:** 1,212 — all BTC, all BUY-side
- **Timeframe split:** 15m 720 slugs (59.4%), 5m 492 slugs (40.6%)
- **Resolution source:** CLOB API fetched live for all 1,212 conditionIds (0 errors)
- **Caveat:** 3,500 rows is the API page limit. lb-api reports $50.6k lifetime / $28.3k/30d,
  implying $943/day. Our modeled $1,842 over 65 days = $28/day. The sample is ~3.3% of the
  wallet's actual trading history. Structural patterns are reliable; absolute PnL is not.

---

## 2. Slug-Level Classification

| Category | Slugs | % |
|---|---|---|
| Directional-only (Up OR Down) | 1,022 | 84.3% |
| Paired (both Up AND Down) | 190 | 15.7% |

The "94% paired" figure from lb-api wallet classification is misleading — it measures
trade-level overlap, not slug-level independence. At slug level, 84% are one-sided bets.

---

## 3. Pair-Arb Economics — Core Metrics

For the 190 paired slugs:

| Metric | Value |
|---|---|
| Median sum_px (up_avg + dn_avg) | 1.1418 |
| Mean sum_px | 1.1409 |
| P5 sum_px | 0.816 |
| P10 sum_px | 0.960 |
| P25 sum_px | 1.000 |
| P75 sum_px | 1.304 |
| P90 sum_px | 1.391 |
| Slugs with sum_px < 1.0 (risk-free) | **48 / 190 = 25.3%** |
| Slugs with sum_px >= 1.0 (losing pairs) | 142 / 190 = 74.7% |

**Only 4.0% of all 1,212 slugs are truly risk-free pairs** (48 slugs with sum_px < 1.0).

Risk-free pair metrics (48 slugs):
- Mean arb spread: 0.0975 (mean profit per matched share)
- Median arb spread: 0.0308
- Mean matched qty: 89.3 shares
- Total risk-free arb profit: **$401.05** over 65 days = $6.17/day

This is approximately **0.8% of the wallet's lb-api implied lifetime profit**.

---

## 4. Realized PnL Breakdown (2%-on-profit fee model)

| Segment | Slugs | PnL |
|---|---|---|
| Directional-only | 1,022 | **+$5,259.95** |
| Paired (both sides) | 190 | **-$3,417.88** |
| **Total modeled** | **1,212** | **+$1,842.07** |

The paired slugs LOSE money. The profit is entirely from directional single-sided bets.

**TF breakdown:**

| TF | Slugs | Dir PnL | Paired PnL | Total |
|---|---|---|---|---|
| 15m | 720 | +$9,365 | -$2,383 | **+$6,982** |
| 5m | 492 | -$4,105 | -$1,035 | **-$5,140** |

15m is the profitable timeframe; 5m loses in this sample window.

---

## 5. What Actually Drives the Profit — Directional Edge

PBot-3 is primarily a **directional MAKER**, not a pair-arb operator. It posts limit-order
bids (resting) and gets filled. The profitable mechanism is systematic WR outperformance
relative to entry price on the 15m book.

**Directional calibration (1,022 dir-only slugs):**

| Price bucket | N | WR | Mean entry | Edge (WR - price) |
|---|---|---|---|---|
| 0.00-0.30 | 227 | 14.1% | 0.179 | **-3.8% (adverse selection zone)** |
| 0.30-0.40 | 21 | 47.6% | 0.350 | +12.6% |
| 0.40-0.50 | 150 | 48.0% | 0.472 | +0.8% |
| 0.50-0.60 | 247 | 56.7% | 0.543 | +2.4% |
| 0.60-0.70 | 191 | 70.2% | 0.648 | +5.4% |
| 0.70-0.80 | 143 | 79.0% | 0.750 | +4.0% |
| 0.80-1.00 | 43 | 97.7% | 0.842 | **+13.5%** |

**Overall dir-only: mean_px 0.509, WR 53.1%, edge +2.2%**

15m directional: mean_px 0.513, WR 55.6%, EV/share +$0.038
5m directional: mean_px 0.505, WR 50.1%, EV/share -$0.008 (no edge, near-zero)

The dominant profit driver is **15m buys in the 0.6-1.0 price zone** (high-probability
outcomes trading at resting bid, getting filled by takers dumping). This is NOT pair-arb.

---

## 6. Entry Timing

All trades:
- Mean entry offset from slot_start: +222 seconds (mid-slug)
- Median: +213 seconds
- Range: -891 to +843 seconds (enters before and after slot_start)

Most fills happen 60-600s into the slot (taker activity picks up mid-slot). The
"before slot_start" trades ((-600, 0]) appear to be the previous-period fills landing.

The near-simultaneous Up+Down entries in paired slugs (both at ~315s mean offset)
suggest these are NOT deliberate pair-arb constructions — they are sequential fills
on different sides as the book oscillates mid-slot.

---

## 7. Fee Structure (CLOB API)

| Fee field | Value | Slug count |
|---|---|---|
| maker_base_fee = 1000 tenths-bp | 0.1 bp = 0.00001 | 950 |
| maker_base_fee = 0 (true zero) | 0 | 262 |

**Maker rebate estimate:** 0.1 bp taker fee, 40% rebate share, $100 notional at p=0.5
= $100 * 0.00001 * 0.4 = **$0.0004 per order** — economically negligible.

This confirms CLAUDE.md: on BTC/ETH/SOL updown markets, feeRate is effectively 0 and
**maker rebates are ~$0**. The edge is purely price-based, not rebate-based.

Production fee model applies: 2%-on-profit-only (LegacyConfig) for the winning leg.

---

## 8. Capacity & Scale

In the 65-day sample:
- 57 median slugs/day (range: 3-212/day)
- 3,500 trades / 1,212 slugs = 2.89 trades per slug average
- Mean position size: 70.9 shares @ $0.54 avg price = $38.3 notional/trade
- Total capital deployed: $134,280 over 65 days

Risk-free pair-arb capacity (if we tried to replicate ONLY the arb component):
- 0.74 risk-free slug opportunities/day
- $6/day expected arb profit (entirely insufficient to explain $943/day lb-api rate)

---

## 9. lb-api Reconciliation Gap

| Source | PnL/day |
|---|---|
| lb-api $28.3k/30d | $943/day |
| Our modeled 65-day sample | $28/day |
| Ratio | 33x gap |

The gap is structural: the 3,500-row API limit returns only ~3% of the wallet's
historical trade activity. The wallet has been active much longer and/or at much
larger position sizes in earlier periods.

Structural patterns in our sample (84% directional, 15m profitable, 5m breakeven,
adverse selection at <0.30 bucket) are likely representative of the full history.
The 33x PnL gap implies either: (a) position sizes were 10-30x larger historically,
or (b) the wallet traded 10-30x more slugs/day in its peak period.

---

## 10. Verdict

### Is PBot-3 a risk-free pair-arb?

**NO.**

The wallet was classified as PURE_PAIR_ARB_MAKER based on lb-api metadata (94% of
slugs appear to have both-sides trades). At the slug-level, 84% of positions are
directional-only. Of the 190 "paired" slugs, only 48 (4% of all slugs) have
sum_px < 1.0 (genuinely risk-free). The 142 remaining paired slugs have median
sum_px = 1.24 — these are losing positions, not arb.

**Actual strategy: 15m FAVORITE-BIAS DIRECTIONAL MAKER**
- Posts limit bids on both 5m and 15m BTC markets
- Gets filled by takers; net position is usually single-sided
- 15m shows strong positive edge (+4.3pp WR vs implied probability, EV +$0.038/share)
- 5m is near breakeven (-0.3pp edge in this sample)
- Profit source: WR calibration edge on 15m, particularly in the 0.5-1.0 price range
- The "both sides" appearance = sequential fills from resting bids as market moves,
  not deliberate pair construction

### Is the "pair-arb" component replicable?

The 48 risk-free pair opportunities ($401 total, $6/day) exist but are economically
trivial relative to the wallet's profit rate. Replicating only the arb component
delivers ~$6/day — not the $943/day lb-api implies.

### What IS replicable from PBot-3?

The **15m directional maker edge** (+4.3pp WR outperformance) is the actual alpha.
Mechanism: resting limit bids at market prices on 15m BTC markets, getting filled
by takers who are directionally motivated — the maker earns the spread between
their bid and the implied probability. The 0.6-0.8 price zone shows the strongest
calibrated edge (+4-5.4pp, relatively low adverse-selection risk).

**Adverse selection warning:** the <0.30 price bucket (227 slugs, -3.8% edge,
-$1278 total drag) shows classic maker adverse selection — takers DUMP into resting
bids at very cheap prices specifically when they know the outcome is going the other way.
A replication strategy should avoid resting at p < 0.35.

### Deployability assessment

| Component | Deployable | Notes |
|---|---|---|
| Risk-free pair-arb (sum_px<1) | Low priority | $6/day, not enough volume |
| 15m directional maker | Investigate | Need more trade history; 15m shows +4.3pp edge |
| 5m directional maker | No | Near-zero edge in sample window |
| Avoid p<0.35 resting bids | Required | Adverse selection sink, -$1278 drag |

**Recommended next step:** Pull full transaction history via Alchemy `getAssetTransfers`
(not just the 3500-row /trades endpoint) to get complete PnL picture and confirm whether
the 15m directional maker edge is stable across longer history.
