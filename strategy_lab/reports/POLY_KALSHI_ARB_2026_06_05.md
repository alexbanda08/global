# Poly × Kalshi 15m Cross-Venue Arb — efficiently aligned, no clean edge (2026-06-05)

**Data:** new Kalshi feed pulled to canonical (`kalshi_markets.parquet` 978 mkts, `kalshi_orderbook.parquet`
771k quotes; BTC/ETH/SOL `KX{A}15M` series). Overlap with Poly L25 = **Jun 2 → Jun 4** (~2.6 days).
**Script:** `strategy_lab/directional/poly_kalshi_arb_2026_06_05.py`
**One line (UPDATED w/ full numbers `poly_kalshi_arb_numbers_2026_06_05.py`):** Kalshi `KX{A}15M` == Poly
`{a}-updown-15m` (same contract; 96.0% settlement agreement). Shallow dips are fee-eaten, BUT **depth-selective
entry IS net-profitable and significant**: waiting for the cross-venue complete-set to dip below ~$0.95 yields
**net +2.7¢/set (CI [+1.1,+4.2])**, below $0.90 **net +6.6¢/set (CI [+4.8,+8.4])**, ~200–240 chances/day.
🔴 Gated on UNVERIFIED Kalshi ask depth (deep dips may be tiny size) + 2-venue simultaneous execution.

## QUANTIFIED opportunity (Jun 2–4, 2.6d, 681 windows)
| enter cost< | n | /day | entryCost | GROSS/set | NET/set | NET CI | $0loss | @$100 NET (2.6d) | ~$/day @$500 |
|---|---|---|---|---|---|---|---|---|---|
| 0.99 | 645 | 245 | 0.952 | +1.7¢ | −1.1¢ | [−2.7,+0.4] | 3.4% | −$713 | −$1,353 |
| 0.97 | 644 | 244 | 0.941 | +3.4¢ | +0.6¢ | [−0.9,+2.1] | 3.1% | +$376 | — |
| **0.95** | 636 | 241 | 0.926 | +5.5¢ | **+2.7¢** | [+1.1,+4.2] | 2.8% | +$1,697 | +$3,220 |
| **0.92** | 575 | 218 | 0.899 | +8.0¢ | **+5.1¢** | [+3.4,+6.8] | 3.1% | +$2,958 | — |
| **0.90** | 534 | 203 | 0.879 | +9.5¢ | **+6.6¢** | [+4.8,+8.4] | 3.6% | +$3,547 | +$6,729 |
| 0.85 | 413 | 157 | 0.829 | +13¢ | **+10.2¢** | [+7.9,+12.3] | 4.8% | +$4,201 | — |
Per asset @<0.95 net/set: SOL +3.7¢ (CI>0), ETH +3.1¢ (CI>0), BTC +1.3¢ (CI incl 0).

**Verdict: a real deep-dip cross-venue arb exists** (net-positive, CI>0 from cost<0.95 down). The earlier
"no edge" call was at the wrong threshold (0.98) + a too-harsh flat 5¢ fee; with proper per-leg fees
(Poly winner-only 0.07p(1−p) + Kalshi entry 0.07p(1−p) round-up) + depth selectivity it is profitable.

## Match + settlement-basis risk
- Matched 681 finalized 15m windows (227 each BTC/ETH/SOL) by asset + slot_start==Kalshi open_time, Jun 2–4.
- **Outcome agreement Poly(Chainlink) vs Kalshi(index): 96.04%** (BTC 94.7%, ETH 98.2%, SOL 95.2%) → 3.96%
  disagreement = the basis risk for a cross-venue complete set (disagreement is symmetric: pays $2 or $0, ~0 bias,
  adds variance/tail risk).

## Price scan (645 windows w/ both books)
- **Median complete-set cost = $0.990** (time-averaged per window). Persistent arb would need median ≪1; it's ~1.0.
- Cost <$1.00 68% of in-window time; <$0.98 44%. (min-over-window $0.81 = transient blip artifact, ignored.)
- **Realized, enter at first dip <$0.98:** gross **+4.1¢/set** → net **−0.9¢** at a conservative 5¢ fee
  (CI [−2.4¢, +0.6¢], includes 0). With realistic per-leg fees (~2.6¢: Poly winner-only 0.07·p(1−p) + Kalshi
  entry 0.07·p(1−p)) it's ~breakeven to +1.5¢ — marginal, CI straddles 0.

## Why no edge
- The two venues price the same event consistently (~$0.99 set) — efficient cross-venue.
- The ~1¢ gross discount is eaten by: both venues' fees (~2–3.5¢), the 3.96% settlement disagreement (variance),
  and execution (the <$0.98 dips are transient one-sided quotes; you'd need simultaneous fills on two venues with
  inter-venue latency; Kalshi ask SIZE wasn't even captured in the export → can't confirm fillable size).
- This mirrors the intra-Poly results: binary up/down books are efficiently priced; the only edge is execution
  (the lag-taker scalp), not positioning/arb.

## Caveats / what could change the verdict
- Short window (Jun 2–4, 645 windows). As Kalshi data accrues (collector running), re-run on more data.
- Kalshi **ask sizes not exported** (only bid sizes + jsonb book) — re-export `yes_bids/no_bids` jsonb to size the
  dips and confirm whether any are large/persistent enough to fill. If a subset of dips is deep+sized, a
  latency-arb bot could still capture them — but that needs co-located execution, out of scope here.
- A DIRECTIONAL cross-venue signal (when Poly and Kalshi prices diverge, which is right?) = prediction → expected
  efficient per the whole project; not tested (low priority).

## Artifacts
- Canonical: `data/v4/canonical/kalshi_markets.parquet`, `kalshi_orderbook.parquet` (BTC/ETH/SOL 15m, Jun 2–5).
- `poly_kalshi_arb_2026_06_05.py` · `_results/poly_kalshi_arb_2026_06_05.parquet` (per-window costs/outcomes).
- Cross-timeframe arb (same session) = NULL: `CROSS_TIMEFRAME_ARB_2026_06_05.md`.
