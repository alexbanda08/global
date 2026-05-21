# 9 Wallets — Strategy-by-Strategy Decode

_2026-05-17. Per-wallet behavioural decode after canonical resolutions +
chainlink RTDS fallback + fires_decoded enrichment. Source data:
`cache/<short>/fires_decoded.parquet` joined to chainlink ground truth._

**Notation throughout**: `HOLD PnL` = realized PnL if every BUY were held
to chainlink settlement, with real Polymarket fees (`0.07 × p × (1−p)`
per share). Comparing `HOLD PnL` to actual cash PnL reveals whether the
wallet runs a buy-and-hold strategy or scalp-and-flip.

---

## 0. Headline ranking

| # | Wallet | Reported PnL | $/day | HOLD PnL/$ | Implied strategy |
|---|---|---:|---:|---:|---|
| 1 | **0xb27bc932** | **+$918,627** | **$254,467** | **-$0.36** | **2-sided CLOB scalper w/ relay-wallet exit** |
| 2 | 0x0fe40e88 | +$531,932 | $19,266 | n/a | Non-up-down (sports / events) |
| 3 | 0x3e6bfd2f | +$58,317 | $166,620 | n/a | Non-up-down (brand new, 9h) |
| 4 | 0x7f599984 | +$44,569 | $6,349 | -$0.22 | Mixed taker — flips inventory |
| 5 | 0x89b5cdaa | +$42,742 | $9,498 | +$0.02 | Binance-mirror directional + partial flip |
| 6 | 0x9dae874a | +$41,420 | $5,900 | +$0.26 | Pure binance-directional HOLD (F2 cluster) |
| 7 | 0xa0a50783 | +$40,915 | $5,828 | +$0.60 | Pure binance-directional HOLD (F2 cluster) |
| 8 | 0xeefe46de | +$191 | $94 | -$0.02 | Contrarian large-size taker (basically flat) |
| 9 | **0xcfb103c3** | **-$175** | -$40 | **-$0.07** | **Failed scalper — copy of 0xb27bc932 that doesn't work** |

The wallets cluster into **4 distinct strategy types**, not just one.

---

## 1. 🥇 0xb27bc932 — High-frequency two-sided CLOB scalper

**Reported PnL: +$918,627 over 3.6 days. $254,467/day.** Largest scale of any wallet decoded.

### Mechanics (extracted from chain data)

- **Total ERC1155 transfers in 30-day window: 199,830.**
  - 199,250 inbound (BUYs from CLOB takers/sellers)
  - 580 outbound — **ALL 580 sent to one single address `0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0`** (a paired relay/treasury wallet)
- **Zero on-chain mints** (`splitPosition`)
- **Zero on-chain burns** (`mergePositions`)
- BUYs are tiny (~16 shares avg, ~$10/fire); SELLs are huge (median 2,977 shares, max 5,109)

### Fire density (sample of 600 most-recent)

| Slug | Fires | Duration | BUY:SELL | Up shares | Down shares | Final net pos |
|---|---:|---|---|---:|---:|---|
| `btc-updown-5m-1778820000` | 520 | 329s | 518:2 | 10,218 | 5,952 | **Up=0, Down=0** |
| `btc-updown-5m-1778820300` | 55 | 322s | 53:2 | 530 | 1,002 | Up=0, Down≈0 |
| `btc-updown-5m-1778819700` | 25 | 107s | 23:2 | 3,278 | 3,449 | Up=-2,678, Down=-2,507 |

→ **520 fires in 329 seconds on ONE market** = 1.6 fires/second.

### Strategy explanation

1. **Pick a slug** with active mint-and-sell makers (sum_asks > $1).
2. **Buy aggressively on BOTH sides** from those makers (tiny fills, ~16 shares each).
3. **Hundreds of fills per minute** — they outrun other takers to the maker quote.
4. At the end of the slug, **dump all accumulated inventory in 2-3 SELL transactions** to a relay wallet (`0xf3cfb6a6...`), which presumably handles merge/redeem off the radar of this wallet's accounting.
5. The relay wallet is what merges/redeems and ultimately captures $1 per pair.

### Why it makes money

The HOLD-to-settlement PnL of -$0.36/$ implies they would LOSE if they held positions. The +$0.34/$ they actually capture comes from:
- **Sub-cent price improvement** per fill (taking maker at $0.42, immediately reselling at $0.43)
- **Massive turnover** (520 fires/slug × ~100 slugs/day × $10/fire = $520k traded/day)
- **Pair inventory mergeable at $1** (when sum_buy_costs < $1, every pair built is risk-free profit)

### Verifiable signature for future identification

- ERC1155 transfers from a single relay address (`0xf3cfb6a6...`)
- BUY:SELL ratio ~344:1 by count, ~14:1 by share volume (SELLs batch)
- Per-slug fire density >100 with sub-second cadence
- 100% of slugs traded both Up AND Down

### Risks

- Critically dependent on speed (sub-second to outrun other takers)
- The relay wallet `0xf3cfb6a6...` is the actual P&L bookkeeper — worth decoding separately
- High API call volume means high cancellation rate / failed fills

---

## 2. 🥈 0x0fe40e88 — Non-up-down Polymarket operator

**Reported PnL: +$531,932 over 27.6 days. $19,266/day. Long-running.**

### Mechanics

- 12,946 erc1155 transfers, **NONE** in the up-down crypto market lookup
- Trading sports / elections / news / event markets
- Big USDC outflows to NegRisk matcher ($230k withdrawn in window)
- Genesis funded by `0xf70da978...` (F1 treasury) with $9.99 on 2025-12-10 — **6 months old**

### Strategy explanation

Cannot fully decode — our up-down decoder doesn't apply. But the cash-flow signature is **classic prediction-market resolver harvester**:
- Buy outcomes that look mispriced
- Hold to resolution (sports / event outcomes settle naturally)
- $19k/day sustained for nearly a month → consistent edge in event markets

### Next step

Need a `decode_triggers_eventmarkets.py` that handles non-`(btc|eth|sol)-updown-(5m|15m)` slugs. Could lookup `gamma_markets` data for category (sports / politics / news / culture) and decode triggers per category.

---

## 3. 🥉 0x3e6bfd2f — Non-up-down brand-new operator

**Reported PnL: +$58,317 in 0.35 days. Extrapolates to $166,620/day.**

### Mechanics

- 3,556 erc1155 transfers, NONE in up-down
- Genesis: $29,901.45 PUSD bridged at 2026-05-16 20:52 — **first activity 9h before our scan**
- $58k profit in 9h ≈ $156k/day burst

### Strategy explanation

Brand new wallet, large bridge-in, immediate aggressive trading. Cash flow shape suggests **event-market scalper or sports book**. The $29.9k seed × multiple turns/day pattern is consistent with high-frequency event-market trading.

Cannot deeply decode without an event-market decoder. Worth tracking — if it sustains $150k/day for 3-7 days, it's a new entity to study.

---

## 4. 0x7f599984 — Mixed taker that flips inventory

**Reported PnL: +$44,569 over 7d. $6,349/day. HOLD PnL/$ = -$0.22.**

### Mechanics (1500-fire sample)

- 1,319 BUYs / 181 SELLs (88% BUY)
- 42 unique slugs, median 17 fires/slug, p90 95 fires/slug
- 0% of slugs traded both Up AND Down (always one-sided)
- Mean entry: $0.368 (cheap side)
- WR on HOLD: 30% (would lose money if held)

### Strategy explanation

Buys the cheap side at $0.30-$0.40 in moderate density. **HOLD PnL is negative**: they would lose if they sat on positions. But they're +$44k cash → they must be **flipping inventory back** at higher prices before resolution.

Effective strategy:
1. See sum_asks > $1 (mispricing)
2. Buy cheap side at $0.35
3. Wait for binance to drift in the direction of their side
4. Sell back at $0.40 to $0.50 to other takers/makers
5. Capture $0.05-$0.15 per share × N shares

### Signature

- Buys exclusively cheap-side (own_ask < $0.40)
- One side per slug (no pair-building)
- 17 fires/slug = moderate density (not scalper-class, not single-shot)
- Sell-side activity (12% of trades) for the flips back

---

## 5. 0x89b5cdaa — F1 cluster, binance-mirror directional + partial flip

**Reported PnL: +$42,742 over 4.5d. $9,498/day. HOLD PnL/$ = +$0.02.**

### Mechanics

- 600-fire sample: 365 BUYs / 235 SELLs (61% BUY — only wallet with significant sell side)
- 6 on-chain mints + 1,705 on-chain burns (tiny minting, lots of merges)
- 22 unique slugs, 7 fires/slug median
- 41% of slugs have both sides
- Multi-asset: BTC 538, ETH 33, SOL 29 (the only multi-asset wallet here)
- **WR(match binance)=100%, WR(contrary)=0%** — perfect directional alignment

### Strategy explanation

Hybrid strategy:
1. Watch binance momentum
2. When binance moves: BUY the matching side as a CLOB taker
3. Hold and merge pairs at slot_end to recover $1/pair (the 1,705 burns)
4. Occasionally market-sell to exit risk early

Per the genesis: funded by `0xf70da978...` with $999 in February 2026 — **the wallet has been running 3+ months** and gradually built capital to $54k.

This is the only wallet that does **on-chain merges** (1,705 burns) — closest to the traditional mint-and-sell maker shape, but with predominantly buys.

### Signature

- Multi-asset (BTC + ETH + SOL)
- Binance-directional with merges
- Active over months
- Funded by F1 treasury

---

## 6 & 7. 0x9dae874a + 0xa0a50783 — F2 cluster pure binance HOLDers

**Reported PnL: ~$41k each over 7d. ~$5,900/day. HOLD PnL/$ = +$0.26 and +$0.60.**

### Both wallets share

- **Funded by F2 treasury (`0x3a9418b2...`) on 2026-05-11** — same day, same dollar amount ($4,998.88 PUSD bridge), same first activity hour
- **7 shared slugs** out of 8 / 19 — they pick from the same universe
- BUT few same-second fires (1-3 per shared slug) — independent execution

### Per-wallet:

#### 0xa0a50783 (HOLD PnL/$ = +$0.60)

- 432 BUYs, 8 slugs in sample, 42 fires/slug median
- **170 Up at $0.45 (WR=0%) + 262 Down at $0.49 (WR=100%)** in resolved sample
- WR(match binance) = **100%**, WR(contrary) = 0%
- Binance match_pct = 60.7%

#### 0x9dae874a (HOLD PnL/$ = +$0.26)

- 533 BUYs, 19 slugs, 20 fires/slug median
- 234 Up at $0.41 (WR=34%) + 299 Down at $0.41 (WR=93%) in resolved sample
- WR(match binance) = 87%, WR(contrary) = 50%
- Binance match_pct = 45.2%

### Strategy explanation

These are the **cleanest binance-directional HOLDers** in the dataset. Pure recipe:
1. Watch binance BTC price live (must be sub-second to be useful in 5m slugs)
2. When binance drops, BUY Down tokens at whatever ask is available
3. When binance rises, BUY Up tokens
4. **Hold to chainlink settlement** (no exit before resolution)
5. Profit = (1 - entry_price) per winning share, minus fees

The 100% WR-when-matching-binance is striking — it suggests they have a faster signal than the CLOB ask price reflects. Within the 5min window, binance's recent direction is a strong predictor of where chainlink settles (which is essentially binance with a small basis).

### Operator pattern

Same treasury fanned out two parallel wallets at identical seed sizes. Reasons:
- **Risk distribution**: limit per-wallet exposure
- **Rate-limit avoidance**: split orders across wallets to stay under per-account CLOB limits
- **A/B testing**: try slight parameter variations between wallets

The two wallets fire on the same slugs but at different moments → same alpha source, separate execution decisions.

### Signature

- Funded by F2 treasury `0x3a9418b2651c8164db5ebc56f12008137865e0f7`
- PUSD-bridged $4,998.88 specifically (not USDC.e from external)
- Multi-fire-per-slug (~20-42 fires)
- WR(match binance) >> WR(contrary)
- No on-chain mints/merges — pure CLOB

---

## 8. 0xeefe46de — Contrarian large-size taker (basically flat)

**Reported PnL: +$191 over 2 days. $94/day. HOLD PnL/$ = -$0.02 (flat).**

### Mechanics

- 576 BUYs in sample, **mean_shares 241.5** (10× the average) — large-size taker
- WR(match binance) = 14%, **WR(contrary) = 23%** — slightly contrarian
- 7 fires/slug median
- 13.6% slugs both-sided

### Strategy explanation

This wallet trades large size (10× peer average) but with no clear directional edge. WR-when-contrary > WR-when-match → mildly contrarian to binance momentum (fading the move). The very small net PnL ($94/day) suggests they're at the noise floor — neither systematically winning nor losing.

Possibly a **liquidity provider for other wallets** — large size accommodates fills, doesn't try to profit from direction. Or a **failing experimental strategy**.

### Signature

- mean_shares ~240 (10× peer average)
- Slight contrarian binance correlation
- Near-zero PnL/day
- Capital_in vs capital_out: $350 in, $45,586 out → **net withdrawer ($45,235)**, despite small per-trade PnL

---

## 9. 0xcfb103c3 — Failed CLOB scalper (counter-example)

**Reported PnL: -$175 over 4.4d. -$40/day. HOLD PnL/$ = -$0.07. LOSING.**

### Mechanics

- 430 BUYs in sample, 58 slugs, **98.3% slugs both-sided** (just like 0xb27bc932!)
- Mean_shares 207.7 (large-size, similar to 0xeefe46de)
- WR(match binance) = 75%, contrary = 28% — directional signal exists
- **HOLD PnL/$ = -$0.07** (would lose even if held)

### Strategy explanation

Mechanically nearly identical to **0xb27bc932** (98% both-sided per slug = scalper class), but **losing money**. Comparison:

| Aspect | 0xb27bc932 (+$918k) | 0xcfb103c3 (-$175) |
|---|---|---|
| Both-sides slugs | 100% | 98.3% |
| Fires/slug median | 53 | 8 |
| Mean shares/fire | 16.2 | 207.7 |
| Total slugs in sample | 3 | 58 |
| Relay-wallet exit | YES (`0xf3cfb6a6...`) | NO visible |
| Binance correlation | 56.7% match | 46.7% match |

→ **0xcfb103c3 trades larger size, less density, more slugs, no relay-wallet exit**. They look like a wallet trying to copy 0xb27bc932 but:
- Not fast enough (8 fires/slug vs 53)
- Larger fills mean worse execution (more slippage on the maker books)
- No off-chain settlement path

### Lesson

The 0xb27bc932 strategy requires:
1. Sub-second order execution (impossible for human; requires colo + custom engine)
2. Small-size fills (~16 shares = ~$8) to skim the inside spread
3. A relay wallet to handle merge/redeem off the trading wallet

Without all 3, it doesn't work. 0xcfb103c3 has none of those properly and bleeds.

### Signature for AVOIDING this trap

If you see a wallet running the scalper signature (high both-sides, high fires/slug) but losing money, they're attempting an HFT strategy without the infrastructure. Don't copy.

---

## 10. Cross-wallet patterns

### Funder cluster F1 (`0xf70da97812cb96acdf810712aa562db8dfa3dbef`)

Seeded: 0xb27bc932 ($918k), 0x0fe40e88 ($531k), 0x89b5cdaa ($42k), 0xeebde7a0 ($344k from prior session). Strategy mix:
- 0xb27bc932: CLOB scalper
- 0x0fe40e88: non-up-down event trader
- 0x89b5cdaa: binance-directional + small merges
- 0xeebde7a0: mint-and-sell maker

→ **F1 is a diversified multi-strategy treasury.** It hedges by running 4 different strategy types. No single algo failure breaks the whole operation.

### Funder cluster F2 (`0x3a9418b2651c8164db5ebc56f12008137865e0f7`)

Seeded: 0xa0a50783 + 0x9dae874a (same day, same $4,998.88 bridge each). Strategy: pure binance-directional HOLD on both.

→ **F2 is a single-strategy operator running 2 parallel wallets** for risk distribution. Both wallets do the same thing.

### Operator categories observed

| Category | Wallets | Total daily $ |
|---|---|---:|
| HFT CLOB scalper (with relay) | 0xb27bc932 | $254,467/day |
| Event-market traders | 0x0fe40e88, 0x3e6bfd2f | $185,886/day |
| Binance-directional HOLDers | 0xa0a50783, 0x9dae874a, 0x89b5cdaa | $21,226/day |
| Cheap-side flipper | 0x7f599984 | $6,349/day |
| Failed copycat scalper | 0xcfb103c3 | -$40/day |
| Liquidity provider / experimental | 0xeefe46de | $94/day |

---

## 11. Strategy reproduction feasibility

| Strategy | Reproducible by us? | Why / why not |
|---|---|---|
| **0xb27bc932 HFT scalper** | ❌ NO without colo | Needs sub-second order execution; our existing Ireland VPS may not be fast enough; needs custom CLOB engine plus relay wallet plumbing |
| **0xa0a50783 / 0x9dae874a directional HOLD** | ✅ YES | Binance WS + CLOB taker logic; modest infra; we already have binance feeds |
| **0x7f599984 cheap-side flipper** | ⚠️ Partial | Needs flip-back execution which is similar to mint-and-sell exit logic |
| **0x89b5cdaa multi-asset directional+merge** | ✅ YES (already specced as mint-and-sell) | Already covered by `MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md` |
| **0x0fe40e88 event-market trader** | ❌ NO yet | Need event-market decoder + universe |
| **0xb27bc932 with relay wallet** | ❌ extra plumbing | Need second wallet to absorb tokens + handle merge/redeem |

### Best near-term candidate: **F2 directional HOLD strategy**

The F2 cluster is the most reproducible:
- Binance signal is publicly available
- HOLD execution is simple (taker BUY + wait for resolution)
- WR-when-match-binance is 87-100% → robust signal
- Doesn't need colo or HFT infrastructure
- HOLD PnL/$ = +$0.26 to +$0.60 → strong unit economics

Combine this finding with our **Cyclops S7 + sleeve_active filter (BTC 5m)** result — both strategies converge on "use binance momentum as a directional filter on up-down crypto markets." The wallets validate the alpha source.

---

## 12. Files

- [strategy_lab/wallet_hunt/_strategy_deepdive.py](../wallet_hunt/_strategy_deepdive.py) — reusable per-wallet deepdive
- [strategy_lab/wallet_hunt/cache/_strategy_deepdive_all.json](../wallet_hunt/cache/_strategy_deepdive_all.json) — full JSON output per wallet
- [strategy_lab/wallet_hunt/cache/<short>/strategy_deepdive.json](../wallet_hunt/cache/) — individual JSON per wallet
- [strategy_lab/wallet_hunt/cache/_master_catalog.csv](../wallet_hunt/cache/_master_catalog.csv) — flat summary table
- [strategy_lab/reports/WALLET_CATALOG_2026_05_17.md](WALLET_CATALOG_2026_05_17.md) — earlier general catalog

## 13. Next investigation threads

1. **Decode `0xf3cfb6a6...` — 0xb27bc932's relay wallet**. Pull its alchemy_transfers, see what it does with the ~580 SELL chunks it receives. Likely the actual settlement/merge engine.
2. **F1 treasury fan-out**: walk `0xf70da978...` outbound transfers — how many other operator wallets has it funded that we haven't analyzed yet? (`_funder_graph.py` was scoped for this.)
3. **Event-market decoder** for 0x0fe40e88 / 0x3e6bfd2f. Major P&L gap in our coverage.
4. **HOLD strategy paper-trade**: build a backtest of the F2 strategy on canonical data (BTC 5m, binance ret_2m at fire+30 → buy Down if negative). Compare to Cyclops S7 result.
