# Multi-Cell Wallet Decode: 0x5e2b9261 + 0xfcdc071d (2026-05-29)

Two profitable Polymarket up-down wallets that cover all 4 target cells
(btc-5m, btc-15m, eth-15m, sol-15m). Analysis based on `polymarket_api.py`
`/activity` tape (3500/type page cap = today's fills) + Alchemy on-chain
transfers + lb-api lifetime PnL.

---

## 1. Wallet Profiles

| Metric | 0x5e2b9261 | 0xfcdc071d |
|---|---|---|
| lb_profit_all | **$92,109** | **$18,576** |
| lb_profit_30d | $47,216 | $8,988 |
| lb_profit_7d | $11,093 | $4,662 |
| lb_volume_all | $4.26M | $4.69M |
| open_value | $225 (14 positions) | $827 (100 positions) |
| activity types | TRADE + SPLIT + REDEEM | TRADE + REDEEM + MERGE + MAKER_REBATE |
| started | early (SPLITs from Apr 18) | **May 23** (6 days old) |
| n_markets | 217 | 79 |
| lb trade count | 1,408 | 1,585 |
| cell mix | btc-5m 245, btc-15m 335, eth-15m 576, sol-15m 252 | btc-15m 985, eth-15m 396, sol-15m 195, btc-5m 9 |

---

## 2. 0x5e2b9261 — Verdict: DIRECTIONAL TAKER + MINT bootstrap

### Bucket
**Directional taker (favorite-buyer) with momentum stop-loss.** Uses SPLIT
(minting) to bootstrap positions in bulk, then trades BOTH BUY and SELL
directionally. NOT a pair-arb player (no MERGE events).

### Activity breakdown (today's 3500-event sample)
| Type | Count | USDC | Notes |
|---|---|---|---|
| SPLIT | 3,500 | -$271,340 spent | Minting $100 slugs (75% at $100 flat) |
| REDEEM | 3,500 | +$94,035 received | Settling resolved winners (May 27-29) |
| TRADE BUY | 2,265 | -$14,741 | Taker buys at avg **0.657** |
| TRADE SELL | 1,235 | +$3,640 | Early exits at avg **0.481** |

Note: SPLIT events are from Apr 18–20 (oldest page = oldest minting batch);
TRADE events are from today (May 29 15:40–22:48 UTC, all unresolved);
REDEEM events are May 27–29.

### Entry price profile
- **BUY med = 0.690, avg = 0.657** → buying outcomes already favored by the market
- **SELL med = 0.450, avg = 0.481** → selling at a loss relative to buy price
- BUY > SELL avg by **0.137**: this is directional with a stop-loss discipline
- 31% of sells are at price < 0.30 (dump positions that have moved heavily against)
- 28% of sells are at price > 0.70 (early profit-taking on strong winners)

### SELL pattern: cutting losers
- 291 slugs have both BUY and SELL on the same conditionId (same outcome)
- Of those: 204/291 (70%) have avg SELL < avg BUY → stop-loss exits
- 87/291 (30%) have avg SELL > avg BUY → early profit exits
- Average loss on stop-loss exit: **−0.284** (cut at 0.35 after buying at 0.63)
- Average gain on early profit exit: **+0.207**

### Cross-cell consistency (4 target cells)
| Cell | BUY n | BUY med | Up% | SELL n | SELL med |
|---|---|---|---|---|---|
| btc-5m | 634 | 0.690 | 42% | 269 | 0.500 |
| btc-15m | 162 | 0.660 | 48% | 170 | 0.450 |
| eth-15m | 185 | 0.682 | 44% | 166 | 0.460 |
| sol-15m | 122 | 0.620 | 44% | 78 | 0.565 |

**Consistent pattern across all 4 cells**: BUY med 0.62–0.69, SELL med 0.45–0.57.
Up% 42–48% (slightly Down-biased; Down outcome priced higher avg 0.667 vs Up 0.645,
consistent with market being bullish and Down = short = favored on downward moves).

### REDEEM distribution (resolved PnL)
| Cell | USDC sum | Count | Avg/redeem |
|---|---|---|---|
| btc-5m | $33,395 | 666 | $50.1 |
| eth-5m | $15,679 | 665 | $23.6 |
| xrp-5m | $13,478 | 652 | $20.7 |
| sol-5m | $12,240 | 627 | $19.5 |
| btc-15m | $5,405 | 222 | $24.3 |
| eth-15m | $5,086 | 224 | $22.7 |

btc-5m dominates REDEEM ($33k, avg $50/settlement) — highest notional per slug.

### Fills per slug
10–11 fills/slug across all 4 target cells → moderate activity, typical taker
volume (compared to 28/slug for fcdc's market-making).

### Funder
Alchemy fetch still running at analysis time; SPLIT events go back to Apr 18 →
wallet has been active ~6 weeks. $271k in SPLITs (3500 page cap, oldest batch)
implies substantial capital deployed. No direct USDC source identified yet.

### Directional signal hypothesis
- Buying favorites (avg 0.657) across ALL cells → could be pure price-follow
  ("buy whatever is already the favorite at slug open")
- Up% 42–48% consistent with DOWN being favored more often on current regime
  (BTC/ETH in declining or volatile phase)
- The slug-selection signal (WHY this particular slug?) cannot be decoded from
  today's sample alone — trigger_decode_harness fails because today's trades
  are all unresolved (canonical resolutions max ts = 13:17, trades start at 15:40)
- The WR on held-to-resolution positions is **not directly computable** from
  page-capped data. The $92k lifetime profit / $4.26M volume ≈ **2.2% return on
  volume** — consistent with a ~65% WR on favorite-buy strategy at p≈0.65 entry
  (expected: (0.65 × 0.35) − (0.35 × 0.65) × 2% fee ≈ +2%)

### Classification
- **Bucket**: Directional taker — favorite-buyer with stop-loss
- **Cross-cell consistency**: YES — identical BUY>SELL pattern, same price range
  (0.62–0.69 BUY, 0.45–0.57 SELL) across btc-5m, btc-15m, eth-15m, sol-15m
- **One signal or per-cell?**: Cannot determine from today's data. The uniform
  behavior across all 4 cells suggests ONE cross-asset rule (e.g., "buy the
  favored side at slug open"). The slight Down-bias is consistent across cells.
- **Reproducible?**: PARTIALLY. Buying favorites (highest-priced outcome) is a
  known pattern that earns ~65% WR baseline. Under G1-G4 gate testing, a naive
  "buy favorite" rule fails G4 (net-negative after taker fees). 5e2b's edge likely
  comes from (a) slug selection we cannot decode, (b) timing (entering earlier/later
  than our canonical decision point), or (c) leverage/position sizing with stop-loss
  management. **NOT directly replicable** from available signals.

---

## 3. 0xfcdc071d — Verdict: MAKER LIMIT-ORDER PAIR-ARB

### Bucket
**Maker limit-order pair-arb with full order book posting.** Posts resting limit
bids on BOTH Up AND Down outcomes at sub-fair-value prices. When both sides fill,
MERGEs the pair back to $1 USDC (capturing the spread). When only one side fills,
the position REDEEMs at resolution (introducing directional P/L). MAKER_REBATE
events confirm limit-order execution.

### Activity breakdown (3500/type page cap)
| Type | Count | USDC | Notes |
|---|---|---|---|
| TRADE BUY | 3,500 | -$16,553 | ALL BUY, no SELL; avg **0.474** |
| MERGE | 2,313 | +$998,435 | Pair redemption (Up+Down → $1/share) |
| REDEEM | 3,500 | +$514,311 | Single-side settlements |
| MAKER_REBATE | 19 | +$7,794 | Limit-order rebates (daily aggregated) |
| **NET** | | **+$1,503,988** | (partial sample; large historical MERGE/REDEEM) |

### MERGE economics
| Cell | USDC sum | Count | Avg/merge | Median/merge |
|---|---|---|---|---|
| btc-5m | $807,887 | 1,773 | $456 | $510 |
| btc-15m | $96,246 | 338 | $285 | $273 |
| eth-5m | $80,297 | 151 | $532 | $533 |
| sol-15m | $5,456 | 20 | $273 | $267 |

**btc-5m is the primary pair-arb cell**: 1,773 merges / $808k = 77% of all MERGE
activity. Each MERGE event = returning the position notional at $1/share (e.g.
500 Up shares + 500 Down shares → $500 USDC).

### Maker evidence
- ALL 3,500 TRADE events are BUY — zero SELL → never exits via market sell
- MAKER_REBATE: $7,794 over 19 events (daily-aggregated), ts Apr 2 – May 22
  = **~$156/day** rebate income from limit-order fills
- 19 rebate events / ~50 active days = consistent daily maker activity
- Average rebate per daily event = $410 (reflects large notional being filled)

### Entry price profile
- **BUY avg = 0.474, med = 0.450** → posting limit bids sub-50c
- btc-15m fill distribution is near-uniform across 0.10–0.90 → multi-level
  order book posting (bids at 0.10, 0.20, ... 0.90 on each side)
- 28 fills/slug on btc-15m (vs 10–11 for 5e2b) → confirms multi-level book
- Up% ≈ 51%, Down% ≈ 49% across all cells → symmetric, both sides posted

### Implied pair-arb edge
- If avg fill price = 0.474 per side, and pairs are matched Up+Down:
  `edge = (1 − 0.474 − 0.474) × qty = 5.2%/pair`
- At $500/merge avg notional: **$26/merge × 2313 merges = ~$60k pair-arb PnL**
  (from this sample alone — wallet has full MERGE history from Apr 2 onward)
- REDEEM $514k: single-sided fills that run to resolution — provides additional
  directional P/L. This is risk (unhedged exposure) but also profit when correct.

### Cross-cell consistency
| Cell | TRADE n | Med price | Up% | MERGE n | MERGE sum |
|---|---|---|---|---|---|
| btc-5m | 43 | 0.598 | 60% | 1,773 | $808k |
| btc-15m | 532 | 0.460 | 51% | 338 | $96k |
| eth-15m | 355 | 0.500 | 52% | 2 | $510 |
| sol-15m | 867 | 0.440 | 51% | 20 | $5k |

btc-5m fill price is higher (0.598 med, 60% Up) → current trades are TODAY's
positions which may be more directional; the historical btc-5m MERGE dominance
shows this was the primary pair-arb cell.

sol-15m dominates today's BUY count (867) but has almost no completed MERGEs →
these are all open unmatched positions (one-sided fills waiting for the other side).

### Funder chain
- Alchemy time range: **May 23–29 only** (wallet is 6 days old)
- All USDC IN comes from `0x4d97dcd97ec945f40cf65f87097ace5ea0476045`
  (257 transfers, $73,340 total) — this is the **Polymarket CTF Exchange contract**
- USDC self-funds via MERGE/REDEEM proceeds cycling back: $199k in / $199k out
- Net USDC from external sources: +$272 (essentially self-funded from operations)
- No external funder → this wallet bootstrapped from an initial USDC deposit, then
  all working capital comes from completing pair-arb cycles

### Classification
- **Bucket**: Maker limit-order pair-arb
- **Cross-cell consistency**: YES — symmetric BUY-both-sides pattern with
  sub-50c fill prices across all cells; uniform order book posting confirmed
  by fill distribution on btc-15m
- **Edge mechanic**: Capture spread by posting bids below fair value on both
  outcomes; MERGE when both fill. Residual directional P/L from unmatched fills.
- **Reproducible?**: YES mechanically — the pair-arb mechanic is well-understood.
  **BUT** prior PBot-3 analysis (BATCH_3WAY_SYNTHESIS) showed median `sum_px = 1.14`
  for naive implementations. fcdc achieves avg fill 0.474/side → sum 0.948 < 1.0
  by getting filled at genuinely sub-fair-value prices. This requires:
  1. Posting resting limit bids AND waiting for favorable fills (not taker)
  2. Capital to hold unmatched single-side inventory at risk
  3. Throughput: 2313 merges across ~50 days = 46 pairs/day → high fill rate
  The critical question is whether their fill prices are reproducible or if
  they're first-mover / privileged limit order placement. Given MAKER_REBATE
  (which only exists if feeRate > 0, but CLAUDE.md says feeRate ≈ 0 on crypto
  up-down markets), this wallet may be trading different contract params or in
  a period when fees were active. **Needs verification before deployment.**

---

## 4. Cross-Wallet Comparison

| Dimension | 0x5e2b9261 | 0xfcdc071d |
|---|---|---|
| Bucket | Directional taker (favorite-buy + stop-loss) | Maker pair-arb (limit bids both sides) |
| Mechanic | Buy favorite, hold to resolution, cut losers | Post limit bids sub-50c on both sides, merge pairs |
| Activity types | TRADE (BUY+SELL) + SPLIT + REDEEM | TRADE (BUY only) + MERGE + REDEEM + MAKER_REBATE |
| Entry price | avg 0.657 (favorites) | avg 0.474 (sub-fair-value) |
| Exit mechanism | SELL early (stop-loss or profit-take) + REDEEM | MERGE when paired + REDEEM when single-sided |
| Fills/slug | 10–11 | 28 (multi-level book) |
| Cross-cell signal | Uniform (same rule all cells, slightly Down-biased) | Uniform (symmetric both-sides, btc-5m heaviest) |
| Age | Active since Apr 18 (6+ weeks) | May 23 (6 days) |
| Lifetime profit | $92,109 | $18,576 |
| Capital efficiency | High (small USDC, leverage via minted shares) | Medium (working capital at risk from unmatched fills) |
| Reproducible? | Unlikely (slug selection not decoded) | Yes mechanically (verify MAKER_REBATE/fee conditions) |
| Edge source | Unknown slug-selector + stop-loss discipline | Spread capture (5.2% implied) + maker rebate |

**Neither wallet uses a canonical CEX-momentum signal (no ema9_slope, RSI, ret_2m
cross-cell trigger).** Both operate via execution edge:
- 5e2b: superior slug selection (picks winners more often) and position management
- fcdc: superior order-placement (limit bids below fair value, pair-arb completion)

This is consistent with the EFFICIENT_MARKET_FINDING_2026_05_28 conclusion: the
Polymarket price is an efficient estimator of outcomes. The profitable wallets are
NOT predicting better — they are executing differently.

---

## 5. Is Either a "Cross-Cell Signal" Like 0xe3867b68?

Prior decode of 0xe3867b68 revealed a unified `ema9_slope` rule applied cross-asset.

- **5e2b**: uniform behavior across all cells (same BUY/SELL price range, same Up%),
  consistent with ONE rule applied everywhere. The rule appears to be **"buy the
  currently-favored outcome"** (high entry price = market's current favorite).
  Whether this is purely price-following or involves a timing signal cannot be
  determined from today's unresolved sample. The Up% is 42–48% (Down-biased)
  uniformly, suggesting the same directional filter is active across cells.

- **fcdc**: symmetric both-sides posting across all cells confirms ONE strategy
  applied uniformly (pair-arb). The btc-5m MERGE dominance reflects historical
  pair-arb success on that cell specifically — likely higher fill rates or tighter
  spreads on btc-5m.

**Neither has a complex multi-signal cross-cell trigger.** 5e2b is a simple
favorite-buyer with stop-loss. fcdc is a mechanical pair-arb.

---

## 6. Reproducibility Verdict

### 5e2b — PRICED OUT / UNDECODABLE FROM AVAILABLE DATA
- The naive "buy favorite" rule fails all G1–G4 gates (EFFICIENT_MARKET_FINDING)
- Stop-loss management (cutting at 0.28 when bought at 0.64) reduces drawdowns
  but does NOT recover the negative EV of taker-buying favorites
- The wallet is profitable → there MUST be slug selection (picking only the subset
  where the favorite truly wins more often). The trigger_decode_harness cannot
  expose this without resolved historical trade data (page cap blocks us)
- **NOT replicable** without full Alchemy history + resolved trade matching

### fcdc — MECHANICALLY REPLICABLE (with caveats)
- Core mechanic is known: post limit bids sub-50c on both Up and Down
- When sum_fill_prices < 1.0, MERGE is profitable
- But: prior PBot-3 audit showed naive pair-arb sum_px = 1.14 (ABOVE $1, negative)
  fcdc achieves 0.948 — they are getting fills genuinely below fair value
- Critical gap: HOW they get sub-50c fills at scale on a liquid market
  - Possibility 1: they are among the earliest limit orders on each slug (queue priority)
  - Possibility 2: they use the Polymarket CLOB API with custom fill parameters
  - Possibility 3: the btc-5m market was less liquid historically (stale bids filled)
- MAKER_REBATE exists → verify if this wallet's markets have feeRate > 0 (contradicts
  CLAUDE.md convention of feeRate ≈ 0). If rebates are real, this is an additional
  ~$156/day income stream
- **Capital requirement**: unmatched single-side fills = directional risk
  (REDEEM $514k vs MERGE $998k → ~33% of fills are unmatched and directional)
- **Deploy-readiness**: Deploy NOT recommended without (a) verifying MAKER_REBATE
  conditions are still active, (b) confirming sub-50c fill availability in current
  market depth, (c) testing with small capital to measure actual fill prices achieved

---

## 7. Data Limitations

1. **3500/type page cap**: Only today's (May 29 15:40–22:48) activity is visible.
   All trades are UNRESOLVED → cannot compute WR or directional accuracy.
   Full decode requires either Alchemy ERC1155 history (gets fills but not direction)
   or a Polymarket API with unlimited pagination.

2. **trigger_decode_harness fails**: Returns "no directional resolved fires" because
   canonical resolutions max ts = 13:17 and these wallets' current fills start at 15:40.

3. **5e2b funder**: Alchemy fetch was still running at analysis time. SPLIT history
   from Apr 18 confirms $271k+ minting; external USDC source not identified.

4. **fcdc age**: Only 6 days old — full lifetime analysis covers May 23–29 only.
   $18.6k profit in 6 days = $3.1k/day. The large MERGE volumes in the activity sample
   ($998k) include historical MERGEs from Apr 2 onward (MERGE ts goes back further
   than the wallet's first day — this may be a REDEPLOYED wallet with shared history,
   or the MERGE events belong to a prior version of the same account).

---

## 8. Key Takeaways

1. **0x5e2b9261**: $92k/37-day favorite-buyer with stop-loss discipline. Multi-cell
   (all 4 targets). Same buy-high/sell-low-losers pattern uniformly. Slug selection
   is the unexplained edge — likely an undecoded timing or market-state filter.
   NOT replicable without resolving the slug selector.

2. **0xfcdc071d**: $18.6k/6-day maker pair-arb. btc-5m is the primary cell (77% of
   MERGE volume). $410/event rebates confirm maker fills. Mechanically reproducible
   but requires (a) genuine sub-50c fill access, (b) capital for unmatched inventory
   risk, (c) verification that MAKER_REBATE conditions are still active for these markets.

3. **Neither wallet relies on a CEX momentum signal.** Both confirm the efficient-market
   finding: directional prediction adds no edge; execution and structure are the moat.

4. **The pair-arb mechanic (fcdc) is the more tractable path** if MAKER_REBATE and
   sub-50c fills are still achievable. The mint-and-sell specification
   (`MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md`) is the closest existing spec.
   fcdc extends this by ALSO posting on the Down side, not just selling the cheap
   minted side.

5. **Contrast with PBot-3 (0x74a2b82f)**: PBot-3 achieved sum_px = 1.14 (above $1,
   lossy). fcdc achieves 0.948 (profitable). The difference is fill quality —
   fcdc posts TRUE limit orders (MAKER_REBATE confirmed); PBot-3 may have been
   crossing the spread.
