# 3-Way Parallel Deep-Dive — Synthesis (2026-05-29)

Ran the 3 leads from the new-wallet batch in parallel. All 3 land on the same
meta-conclusion this session keeps reaching, now from three different angles.

## 1. Mean-reversion / fade-momentum (pandagon hypothesis) — **FAILS gates**
Full report: `MEANREV_GATE_TEST_2026_05_29.md`
- Added `fade_mom`, `fade_ret60`, `fade_mom_cheap` to `eval_strategies.py`; gate-tested 6 markets.
- `fade_mom`: 0/6 pass G4; raw accuracy 39–48% (momentum *continuation* slightly beats the fade).
- `fade_ret60 btc_15m`: only near-miss — G1+G2+G3+plateau PASS but **G4 CI-lo −0.159** (fails). 1 lucky cell of 18 = noise.
- `fade_mom_cheap`: catastrophic (WR 31–36%, G3 p=1.0).
- **Why pandagon profits but the rule fails:** pandagon SELECTS specific slugs; a univariate fade on the
  full universe is efficiently priced. The selection signal isn't in our canonical features (same gap as F2).
- **Only gated-pass directional strategy remains `clbasis_rel-btc-5m`** (G1+G2+G3+G4 + plateau 97.8%).

## 2. PBot-3 (0x74a2b82f) — **NOT risk-free pair-arb; a thin 15m directional maker**
Full report: `PBOT3_PAIRARB_2026_05_29.md`
- Median pair cost `sum_px = 1.14` (ABOVE $1). Only ~4% of slugs assemble Up+Down for <$1 → ~$6/day.
  The "paired" slugs are sequential oscillation fills, not deliberate arb (the non-risk-free pairs LOSE).
- Real edge = **15m maker WR calibration +4.3pp above implied** (EV +$0.038/share); 5m is flat/negative.
- Avoid resting bids below p=0.35 (adverse-selection sink, −3.8pp).
- Fees/rebates ≈ 0 (confirms CLAUDE.md crypto-updown feeRate≈0). Modeled $28/day vs lb $943/day —
  our sample is ~3% of history (data-api 3,500-trade page cap); needs Alchemy full history to validate at scale.
- **Verdict:** the arb angle is a mirage; the maker calibration edge is thin and capital/throughput-bound.

## 3. Whale 0x6e1d5040 ($935k) — **capital-intensive NegRisk LEVEL-market maker, not the up-down game**
Full report: `WHALE_6e1d5040_DECODE_2026_05_29.md`
- Decoded on-chain (fetch_chain): NOT a 5m/15m up-down trader. It market-makes BTC **price-LEVEL**
  multi-outcome (NegRisk) markets ("will BTC reach $X / dip to $Y").
- Two legs: (a) accumulate near-certain outcomes at $0.90–0.99 → redeem $1 (1–10% on $100–300k blocks);
  (b) post resting maker SELLS on low-prob extremes at $0.07–0.10, collect spread from retail.
  Maker-sell leg = +$593k/27d across 57k fills @ ~7.5¢. Classic buy-both-legs pair-arb/merge is negligible ($3.7k).
- **Capital: $4.76M bought, $1.22M portfolio; needs $500k–$1.5M working USDC. ~$10.7k/day. Directional
  risk is real (−$183k on wrong-way bets).** NOT replicable at our budget; different market class entirely.

## Session-wide bottom line
Across taker-directional (momentum / cl_basis / flow / favorite / underdog / mean-reversion), maker
pair-arb (PBot-3), and the biggest whale — the reproducible-at-our-scale edge is **thin and
execution/selection-based**, and the only blind-gated directional survivor is `clbasis_rel-btc-5m`
(~2 fires/day). The largest profits ($935k whale, long-dated pair-arb whales) are **capital-intensive
market-making on LEVEL/long-dated markets**, a different game requiring $500k–$1.5M and not the 5m/15m
up-down universe our infra targets. This is consistent with the efficient-market capstone
(`EFFICIENT_MARKET_FINDING_2026_05_28.md`): the up-down PRICE already prices our signals.

### Where the realistic next value is (if continuing)
- **Deploy/forward-test `clbasis_rel-btc-5m`** (the one gated survivor) — low freq, real edge.
- **Quantify the 15m maker calibration edge** (PBot-3 style) properly — needs full chain history (Alchemy)
  to size; it's the most plausible *maker* edge at modest capital.
- The whale's level-market MM is the highest $ but gated by capital, not signal — out of scope unless
  $500k+ is on the table.
