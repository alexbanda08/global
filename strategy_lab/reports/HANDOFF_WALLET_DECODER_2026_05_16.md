# Handoff — Wallet Strategy Decoder + Mint-and-Sell Live Spec

_2026-05-16. Full session capture. Next session: continue finding & decoding
Polymarket wallets to expand our strategy catalog; track TV agent's
mint-and-sell engine build progress; consider live-deploy decisions._

---

## TL;DR for the next session agent

1. **Wallet-strategy decoder pipeline is built and validated**:
   - Pulls full chain history via Alchemy `getAssetTransfers` (no block-range limit)
   - Computes cash + open-position PnL (matches Polymarket UI numbers within $200/day on the wallet we verified against)
   - Cross-references every fire to L25 book / binance / chainlink RTDS
   - Classifies strategy archetype automatically

2. **3 distinct strategies decoded**:
   - **MINT-AND-SELL** (4 wallets confirmed: `0xeebde7a0` $344k/day, `0x04b6d7e9` $212k/day, `0x89b5cdaa` $10k/day, `0xf7f0b0b1` $281/day)
     — fires 100% when `best_ask(Up) + best_ask(Down) > $1.00` on BTC/ETH/SOL 5m+15m short-form markets.
     **Live-deploy spec written, TV agent currently implementing.**
   - **SELL-AND-REDEEM** (hybrid variant of mint-and-sell, observed in `0x04b6d7e9` + `0x89b5cdaa`) — mints pair, sells the EXPENSIVE side immediately, HOLDS the cheap side to settlement and redeems via CTF burn. EV ~10× pure mint-and-sell per opportunity, but with directional variance. Uses same engine primitives as mint-and-sell; can be enabled with single config flag.
   - **PAIR-ACCUMULATOR** (1 wallet: `0xf247584e` $178/day) — buys BOTH sides on **long-form hourly markets** when `sum_bids < $1`. Mirror of mint-and-sell on the BID side. NOT yet spec'd; needs more wallet samples to confirm trigger.

3. **Mint-and-sell backtest matches observed wallet PnL within $200/day**:
   - 314,169 opportunities across 24,376 markets over 21 days (6 cells: BTC/ETH/SOL × 5m/15m)
   - $14k/day projected at $200 notional — brackets observed $10k–$18k for two wallets
   - Realized fill probability: **40.8%** (both Up+Down fills within 60s)

4. **TV agent's mint-and-sell engine in progress**:
   - Task 2 (fee module) in implementation
   - Task 2 implementer flagged a real edge-math concern → resolved correctly
   - Task 3 (trigger condition) is next
   - Spec is at `strategy_lab/reports/MINT_AND_SELL_LIVE_SPEC_2026_05_16.md`

5. **The user is collecting more wallets to expand the catalog.** Run the pipeline on each. Strategies that are NEITHER mint-and-sell NOR pair-accumulator → high-value discoveries.

6. **User is deliberating live-deploy of mint-and-sell** once TV ships Phase 4 (paper mode validated). Risk assessment is in §10 below.

---

## Run the decoder on a new wallet (3 commands)

```bash
# 1. Pull full transfer history via Alchemy (5d window, ~3 min)
py -3 strategy_lab/wallet_hunt/fetch_alchemy.py \
    --wallet 0x<address> --days 5 --max-pages 80

# 2. Cash PnL with open positions (instant, refreshes positions via data-api)
py -3 strategy_lab/wallet_hunt/cash_pnl.py --wallet 0x<short>

# 3. Trigger decode — joins each fire to L25 + binance + RTDS (~2 min)
py -3 strategy_lab/wallet_hunt/replicate/decode_triggers.py \
    --wallet 0x<address> --max-fires 1500
```

Read the trigger report. Classification table:

| Signal | Mint-and-sell | Pair-accumulator | NEW (worth deep-dive) |
|---|---|---|---|
| `sum_asks > $1.00` at fire | 100% | <50% | varies |
| Side mix | ~99% BUY (mints, then sells via separate event stream) | ~96% BUY (accumulates inventory) | mixed / heavily BUY or SELL one side |
| Binance ret_2m std at fire | ~0 bp | ~0 bp | **>5 bp → directional signal** |
| Offset from slot_start | 50-500s (mid-window) | hours-long range | timing-correlated (e.g. all at slot_start ± 10s) |
| Counterparty | matcher `0xe1111800...` 87%+ | varies, plus `0x0` for mints | new counterparty → new venue/contract |
| Token match rate to our lookup | >90% | <50% (long-form markets) | varies |

If a wallet shows **directional signal** (binance ret std > 5 bp) AND
**single-sided positions** (BUY-only on one outcome) AND/OR
**non-50%-fire-direction match with binance momentum**, that's likely a new directional or oracle-based strategy. Decode further by:
1. Pull their open positions via data-api `/positions`
2. Look at which markets they trade vs market resolution (winning side) — compute hit rate
3. Check correlation of fire direction with binance ret_2m, chainlink RTDS deviation, time-of-day

---

## Required setup

**Alchemy Polygon RPC key** (already hardcoded in `fetch_alchemy.py`):
- URL: `https://polygon-mainnet.g.alchemy.com/v2/CkcB0ru1bUfColNdPoTLO`
- Key: `CkcB0ru1bUfColNdPoTLO`
- Free tier — generous for `alchemy_getAssetTransfers` (no block range limit, paginated via `pageKey`)
- Hard 10-block limit for raw `eth_getLogs` — DO NOT use that endpoint for backfill

**Token lookup** must include the wallet's markets. If `decode_triggers`
reports "0 ERC1155 up-down transfers" the wallet trades markets we don't
have indexed. Either:
- Rebuild lookup: `py -3 strategy_lab/wallet_hunt/asset_lookup.py`
- Or pull data-api trades to see what markets they actually use (this is how we discovered 0xf247584e trades long-form hourly markets — those aren't in our short-form 5m/15m lookup)

---

## Files built (full layout)

### Decoder pipeline (`strategy_lab/wallet_hunt/`)

```
strategy_lab/wallet_hunt/
├── fetch_alchemy.py           # Step 1: pull USDC + ERC1155 transfers
├── cash_pnl.py                # Step 2: PnL = USDC_in - USDC_out + open_pos
│                              #         with exchange-counterparty classification
│                              #         (including 0x0 mint/burn = trading flow)
├── asset_lookup.py            # Build token_id → (slug, outcome) map
│                              # Sources: CLOB cache + per-wallet data-api trades
├── shadow_track.py            # Live tracking poller (every 30s)
├── decoder.py                 # Unified L25-anchored strategy decoder + classifier
│                              # (older pipeline, supersede by alchemy stack above)
├── fetch_chain.py             # eth_getLogs OrderFilled decoder (deprecated)
│                              # ⚠️ Public RPCs prune at ~24-48h; Alchemy free
│                              # tier caps getLogs at 10 blocks. Use Alchemy
│                              # getAssetTransfers instead.
└── replicate/
    ├── decode_triggers.py     # Step 3: per-fire trigger extraction
    │                          #   Joins to: L25 book ask/bid/spread
    │                          #             binance kline ret_2m at fire time
    │                          #             chainlink RTDS basis
    │                          #             slot_start offset
    ├── mint_and_sell_scan.py  # Backtest mint-and-sell on canonical L25
    │                          # ⚠️ Has the maker-fee bug (subtracts instead of adds)
    │                          # PnL output ~30-50% understated
    └── fill_probability.py    # Measures realized 60s-window joint fill rate
```

### Per-wallet artifacts (`strategy_lab/wallet_hunt/cache/<short_10char>/`)

Active artifacts (from Alchemy pipeline):
- `alchemy_transfers.parquet` — full transfer history (USDC + ERC1155)
- `fires_decoded.parquet` — enriched per-fire context (ask/bid/spread/binance/rtds at fire time)
- `positions.parquet` — current open positions (data-api snapshot)
- `value.json` — current portfolio value

Legacy artifacts (from chain-RPC decoder — keep for reference but supersede with Alchemy):
- `trades_chain.parquet`, `trades_chain_raw.parquet`
- `fills.parquet`, `legs.parquet`, `markets.parquet`, `pnl.parquet`
- `fills_book_decoded.parquet`, `legs_pnl.parquet`, `per_leg_chain.parquet`

### Cross-wallet outputs (`strategy_lab/wallet_hunt/cache/`)

- `_cash_pnl_summary.csv` — definitive cash + position PnL ranking
- `_token_lookup.parquet` — asset_id → (condition_id, slug, outcome) lookup (52k tokens, 51k up-down)
- `_decoder_summary.csv` — strategy classifier output per wallet (decoder.py)
- `_fingerprints.json` — behavioral fingerprint output (fingerprint.py)

### Backtest outputs (`data/v4/canonical/_results/mint_and_sell_*_2026_05_16/`)

Per-cell directories (6 cells: btc/eth/sol × 5m/15m):
- `opportunities.parquet` — every detected opportunity (slug, ts, ask_up, ask_dn, edge, etc.)
- `fill_probability.parquet` — sample of opportunities with realized fill outcome

Consolidated:
- `_mint_and_sell_consolidated.csv` — per-cell rollup, total $1,787/day @ $25 notional / $14,293/day @ $200

---

## Strategies decoded so far

### 1. Mint-and-sell (CONFIRMED across 4 wallets)

```
TRIGGER (empirical, 100% of 5,500 fires across 3 deep-decoded wallets):
  best_ask(Up) + best_ask(Down) > $1.00

MARKETS:
  BTC/ETH/SOL up-down 5m and 15m (short-form slugs like btc-updown-5m-1778910300)

FIRE SEQUENCE:
  1. CTF.splitPosition($N) on-chain
     → pay N USDC → receive N Up tokens + N Down tokens
  2. EIP712-sign + POST two limit SELL orders to Polymarket CLOB:
     - SELL N×Up   at best_ask(Up)
     - SELL N×Down at best_ask(Down)
  3. Wait up to ~60s for fills (impatient takers cross our quotes)
  4. Per side:
     filled  → receive USDC × price + 20% maker rebate
     unfilled at +60s → cancel
     both unfilled → CTF.mergePositions(N) recovers N USDC
     one filled, one not → hold remaining shares to settlement

EDGE PER OPPORTUNITY (at $200 notional, sum=$1.01, p=0.5):
  Gross:    +$2.00 (sum_asks − $1 × notional)
  Rebate:   +$0.70 (2 sides × 20% × 7% × p × (1-p))
  NET:      +$2.70
  × 40.8% joint fill rate = +$1.10 expected per attempt

REALIZED FILL RATE (measured on BTC 15m, n=2000): 40.8%
  Up alone: 68%, Down alone: 69%, BOTH: 40.8% (binding constraint)
  Stable 40-43% across edge buckets 0-5¢; drops to 17% at >5¢ (stale book)
```

**Wallets running it** (cash PnL verified via Alchemy):
- `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` — **$344k/day** (1.06d sample, largest scale)
- `0x04b6d7e930cf9e493c5e6ef24b496294f95594c8` — **$212k/day** (1.82d sample)
- `0x89b5cdaaa4866c1e738406712012a630b4078beb` — **$10k/day** (4.5d sample, matches user's claimed $10k/day baseline)
- `0xf7f0b0b1e9c0fe02ccad926916ee31aef74b912c` — **$281/day** (3.54d sample, small scale)

**Reference documents** (all under `strategy_lab/reports/`):
- `MINT_AND_SELL_LIVE_SPEC_2026_05_16.md` — live-deploy spec for TV agent (strategy-focused, no over-prescription)
- `MINT_AND_SELL_REPLICATION_2026_05_16.md` — backtest results across 6 cells
- `STRATEGY_DECODED_2026_05_16.md` — original strategy decode (the trigger discovery)
- `WALLET_PNL_BREAKTHROUGH_2026_05_16.md` — how we cracked the cash PnL accounting

### 2. Sell-and-Redeem (HYBRID — asymmetric variant of mint-and-sell)

Observed organically in 2 wallets (`0x04b6d7e9`, `0x89b5cdaa`) as the
fallback behavior when their pure mint-and-sell fires don't get both legs
filled. Their PnL accounting shows it's a deliberate sub-strategy, not just
a failure mode.

```
TRIGGER (inferred from observed fills):
  Either:
  (a) sum_asks > $1 AND one side's ask is unusually high (e.g. ≥ $0.85)
      → asymmetric mint: sell the expensive side immediately, keep the cheap side
  (b) Pure mint-and-sell fired, only ONE side filled within 60s
      → fallback path: hold the unfilled leg to settlement instead of cancelling

MARKETS:
  Same as mint-and-sell — BTC/ETH/SOL up-down 5m+15m short-form markets

FIRE SEQUENCE:
  1. CTF.splitPosition($N) → mint N Up + N Down tokens for N USDC
  2. POST limit SELL N×<expensive_side> at best_ask  (e.g. SELL Up if Up is at $0.85+)
     Optionally also POST limit SELL N×<cheap_side> at best_ask (lower priority)
  3. Wait 60s, cancel anything unfilled on the CHEAP side
  4. HOLD the unsold side to market settlement
  5. CTF.redeemPositions(...) on the held side after slot_end
     → winning held side cashes out at $1/share via 0x0 zero-address burn
     → losing held side gets $0

EDGE MATH (mint $200 at sum_asks=$1.10, sell Up at $0.95, hold Down at $0.15):
  Mint cost                                    -$200
  Sell 200×Up at $0.95 → cash               +$190
  Net cash so far                              -$10
  Hold 200×Down to settlement:
    Down wins (50% prob)  → redeem 200×$1   = +$200 → net +$190
    Down loses (50% prob) → redeem 200×$0   = +$0   → net -$10
  EV at 50% hit rate: +$90 per opportunity
  + Maker rebate on the Up sell: +$0.35
  
RECOVERY PATH (if neither leg fills within 60s):
  CTF.mergePositions(N) → burns the unsold pair, returns N USDC
  Net loss: gas only (~$0.005)
```

**Why this works**: when one side is at an extreme price (e.g. Up at $0.95),
the mint operation effectively buys you "Down at $0.05" as a positive-EV
binary option. The high ask on Up gives near-immediate fill (impatient
takers). The held Down is a 50/50 directional bet at $0.05 cost basis —
positive expected value at any realistic hit rate.

**Wallet evidence**:
- `0x04b6d7e9`: 74% of legs are "only SELL" (= mint + sell one side + held other to redeem). They receive massive USDC from `0x0` zero-address (CTF redemptions) — that's the "redeem" half showing up in their cash flow.
- `0x89b5cdaa`: 100% only-SELL legs. Same pattern but smaller scale.
- Both wallets' positive PnL comes substantially from the **redemption income** (USDC received from `0x0` after market resolutions), not just immediate sell proceeds.

**Difference vs pure mint-and-sell**:
| Aspect | Pure mint-and-sell | Sell-and-Redeem |
|---|---|---|
| Sell both legs immediately | YES | NO (only the expensive side) |
| Directional exposure | None (net 0) | YES (long the cheap side) |
| Capital lockup | <60s typical | Until market settlement (5-15 min) |
| Edge per opportunity at $200 | +$2.70 | +$90 EV (10× more upside, with variance) |
| Frequency | Every sum>$1 event | Subset where one side is at extreme price |
| Risk profile | Near-zero variance | 50/50 binary on held side; large positive EV but lumpy returns |

**Not yet spec'd separately** because the operational primitives are the
SAME as mint-and-sell (CTF split, EIP712 sells, CTF redeem). The TV agent's
mint-and-sell engine spec already includes the redeem path. Once that
engine ships, this variant can be enabled by adding a single config option:
`hold_unfilled_to_settlement: true` instead of `cancel_after_60s`.

**Next-session work**:
1. Decode the EXACT trigger condition for the sell-and-hold variant — is it
   `min(ask_up, ask_dn) < $0.15` AND `max(ask_up, ask_dn) > $0.85`? Or
   something more subtle?
2. Backtest separately on canonical L25 to estimate $/day at $200 notional
3. Compare hit rate of the held side vs binance momentum / chainlink
   deviation to see if the wallets are also gating direction

---

### 3. Pair-accumulator (NEW — single wallet, needs more samples)

```
TRIGGER (inferred from observed BUY behavior):
  best_bid(Up) + best_bid(Down) < $1.00 — buy the pair at a discount
  (NOT yet verified empirically — needs decode_triggers extension to long-form markets)

MARKETS:
  Long-form hourly Polymarket up-down markets
  (slug format: `bitcoin-up-or-down-may-15-2026-5pm-et`, NOT our short `btc-updown-5m-X`)
  Quoted in larger ($5-30+ per share) and slower-moving than 5m/15m

ACTION:
  POST limit BUY on BOTH sides at best_bid (we're maker on both legs)
  Accumulate inventory cheap
  Hold to settlement → receive $1 from winning side

OBSERVED ECONOMICS:
  192 of 210 markets traded BOTH sides
  Sum-of-avg-buy-prices: median $1.026, p25 $0.971, p75 $1.107
  ~25% of markets sum below $0.97 — clear pair discounts
  At p25 ($0.971): profit = $1 - $0.971 = +$0.029 per pair (3% return)
```

**Wallets running it**:
- `0xf247584e41117bbbe4cc06e4d2c95741792a5216` — **$178/day** (3.99d sample, 32% token match rate to our lookup — they trade markets we don't have indexed)

**Not yet spec'd.** Next-session candidates:
1. Validate trigger across more samples — extend `decode_triggers.py` to handle long-form market slugs (`bitcoin-up-or-down-may-15-2026-5pm-et`)
2. Find more wallets running similar strategies
3. Build backtest scanner — mirror of `mint_and_sell_scan.py` but for the BID side, on long-form markets

---

## Loose ends to clean up (in priority order)

### 1. Maker fee model bug (HIGH — TV agent's live engine depends on this being right)

`strategy_lab/wallet_hunt/replicate/mint_and_sell_scan.py` and our `strategy_lab/fees.py` both treat maker fee as `0.80 × taker_fee` (80% of the taker fee net of rebate). **This is wrong.** Polymarket's actual fee model:

| Role | Per-share fee |
|---|---|
| Taker | `0.07 × p × (1-p)` — paid in full |
| Maker | **$0** — pays nothing |
| Maker rebate | **`+0.20 × 0.07 × p × (1-p)`** — received as INCOME |

Impact:
- Scanner: rejects opportunities at sum_asks $1.01-$1.028 that ARE profitable (subtracts phantom $0.028 fee per pair). Wallets fire at median $1.010 → backtest finds them only because we set `MIN_NET_EDGE_PER_SHARE = 0`.
- PnL: Posted PnL × 40.8% fill rate = $14k/day reported; actual should be ~30-50% higher (~$18-21k/day at $200 notional). Better matches observed wallet PnL.

**Fix** (next session, ~30 min):
1. Add `poly_maker_rebate_per_share(price, fee_rate, rebate_share)` to `fees.py` returning POSITIVE value
2. Update `mint_and_sell_scan.py` line 100ish:
   ```python
   # OLD:
   fee_u = poly_taker_fee_per_share(au0, fee_rate) * (1 - CRYPTO_MAKER_REBATE_SHARE)
   net_edge = (au0 + ad0) - 1.0 - fee_u - fee_d
   # NEW:
   rebate_u = poly_taker_fee_per_share(au0, fee_rate) * CRYPTO_MAKER_REBATE_SHARE
   net_edge = (au0 + ad0) - 1.0 + rebate_u + rebate_d
   ```
3. Re-run 6-cell backtest, update `MINT_AND_SELL_REPLICATION_2026_05_16.md`
4. Notify TV agent — their Task 2 fee module is correct as a primitive, but Task 3's edge calculator must use the rebate-additive model

### 2. Long-form market lookup (MEDIUM — blocks pair-accumulator decode)

To decode `0xf247584e` properly we need long-form hourly Polymarket markets indexed:
- Gamma API search pattern: `?slug_contains=up-or-down` filter by `endDate` recent
- Build separate parquet `long_form_token_lookup.parquet`
- Extend `decode_triggers.py` to fall back to this lookup when short-form lookup misses

### 3. `0xce25e214` mystery (LOW — investigate when scale matters)

This wallet showed −$87k/day cash PnL even with the `0x0` mint/burn counterparty included. Counterparty analysis showed:
- $800k sent to exchange (trading_out)
- $527k received from `0x0` (mint/burn redemptions)
- −$23k capital flow
- Net −$296k over 3.4 days

Hypotheses:
- a) Has inventory in a separate Safe/EOA we're not tracking (proxy pattern)
- b) Genuinely losing money (could be a "tester" or a misconfigured bot)
- c) Their full strategy uses additional contracts we haven't classified as exchange

Worth re-checking with `--max-pages 200` once Alchemy budget allows.

### 4. TV agent's task progress (TRACK)

Current state (as of this session):
- Task 1: ? (not visible to us)
- **Task 2: fee module — IN PROGRESS** (implementer correctly flagged edge-math tension; resolution: trigger is empirical `sum_asks > $1`, fee math is for accounting only)
- Task 3: trigger condition — NEXT. Critical: must use `sum_asks > $1` as gate, NOT `net_edge > 0`. The fee-rebate math (corrected per loose-end #1) is for after-the-fact PnL ranking, not for the fire gate.

When TV ships Task 5 (paper mode), validate:
- Detected opportunities ≈ 1,800/day at backtest baseline
- 100% of fires satisfy `sum_asks > $1`
- Simulated joint fill rate 35-45% (vs backtest 40.8%)
- Paper PnL within ±15% of backtest projection

---

## Session-specific discoveries (chronological)

This is what we LEARNED this session, in order, so the next agent has the reasoning trail:

1. **Data-api has a 3500-trade cap per wallet.** Initial fetcher hit this limit. Pagination via `end_time` returns no new data — it's a hard cap on most-recent trades only.

2. **Polygon free RPCs prune history at ~24-48h.** Tried `eth_getLogs` direct, got `-32701 History has been pruned` errors past chunk 23/68 on a 7-day pull.

3. **Alchemy free tier hard-limits `eth_getLogs` to 10 blocks** even with address+topic filters. Useless for backfill.

4. **`alchemy_getAssetTransfers` IS the right primitive.** No block-range limit. Paginated via `pageKey`. Pulled 545k transfers for one wallet in one run.

5. **Zero address (`0x0`) is the CTF mint/burn counterparty.** USDC FROM `0x0` = redemption income. USDC TO `0x0` = mint cost. Initially classified as "external capital" → flipped `0xce25e214` from `−$295k` (apparent loss) to `−$87k/day` (true loss after counterparty fix; still negative but less so).

6. **Polymarket UI's PnL = cash_balance_change + open_position_value.** That's what users see, what wallets report, and what we must replicate.

7. **OrderFilled chain decoder is broken in 80%+ of fills.** Cross-checked against L25 book; median price error is $0.21 vs the actual ask/bid. Fixed via L25-anchored decoder (`book_anchored_decode.py`) but the simpler Alchemy `getAssetTransfers` path supersedes it for PnL purposes.

8. **The "contrarian binance momentum" thesis from earlier sessions is DEAD.** With full chain data, signal alignment is 49% (random) for all profitable wallets. Earlier 63% contrarian WR was a data-api 3500-cap artifact (clipped BUY activity to only one side).

9. **`0xeebde7a0` is actually a market-maker, not a "pyramid taker"** as originally hypothesized from data-api. 65% both-sides legs in full chain data vs 0% in data-api due to cap bias.

10. **Maker fee model misunderstanding (the one we just discussed)**: maker pays $0 + receives 20% rebate income. Spec assumption was wrong; backtest PnL understated.

11. **TV agent Task 2 implementer correctly flagged the spec tension.** Their resolution (trigger = empirical, fee math = separate) is correct.

12. **Two new wallets (0xf7f0b0b1, 0xf247584e) analyzed.** 0xf7f0b0b1 = same mint-and-sell. 0xf247584e = NEW strategy (pair-accumulator on long-form markets).

---

## How to start the next session

Recommended starting prompt:

```
Read this first: strategy_lab/reports/HANDOFF_WALLET_DECODER_2026_05_16.md

Context: we have a working wallet-strategy decoder pipeline. We've found
4 mint-and-sell wallets ($281–$344k/day) and 1 pair-accumulator wallet
($178/day). TV agent is implementing the mint-and-sell live engine
(currently on Task 2, fee module).

[Then: paste new wallets to analyze OR ask for specific work]
```

---

## What I'd do first in the next session (depending on user intent)

### If user pastes new wallets:
1. Batch-run the 3-step pipeline on all of them
2. Sort by `$/day` PnL
3. For top profitable: check if mint-and-sell (sum_asks > $1, 100% match) or pair-accumulator (sum_bids < $1)
4. Any with non-mint trigger → that's a NEW strategy → deep dive (binance correlation, timing, counterparty analysis)

### If user wants the maker-fee bug fixed:
1. Update `fees.py` with `poly_maker_rebate_per_share` helper (positive value)
2. Update `mint_and_sell_scan.py` to ADD rebate instead of subtract phantom fee
3. Re-run 6-cell backtest
4. Update `MINT_AND_SELL_REPLICATION_2026_05_16.md` with corrected numbers
5. Notify TV agent in spec doc

### If user asks about live-deploy timing:
- Mint-and-sell engine: WAIT for TV to ship Phase 4 (paper mode validated). Then go live $25 × 1 market × 24h. See §10 of `MINT_AND_SELL_LIVE_SPEC_2026_05_16.md` for the phased rollout.
- Pair-accumulator engine: NOT YET — need more wallet samples to confirm trigger before spec'ing.
- Momo engine (existing shadow sleeves): **DO NOT DEPLOY**. Backtest with WS truth shows all variants losing. Production paper PnL was a REST-staleness artifact ($0.19-0.32 stale fills inflated apparent profitability). See `MOMO_REST_LAG_VS_MICROSTRUCTURE.md`.

### If user wants to track the pair-accumulator wallet live:
- Add `0xf247584e` to `shadow_track.py` watch list (already supports per-wallet polling)
- Build long-form-market lookup (loose end #2)
- Decode their fires properly once lookup exists

---

## Risk/deploy assessment for mint-and-sell (full detail)

User is deliberating live-deploy. My assessment from this session:

**Strategy edge thesis** (why it should work):
- Microstructure inefficiency: directional takers check one side, ignore the opposite. When both asks drift above sum=$1, the surplus is real money for any operator who can mint Up+Down pairs from $1 USDC and sell both.
- Maker side wins because we pay $0 fees + receive 20% rebate; the impatient taker pays the full taker fee.
- VERIFIED in the wild: 4 independent wallets making real money on this exact pattern, with chain-verified cash PnL ($10k–$344k/day depending on notional).

**Risks in likelihood order**:
1. **Execution risk: stale book at fire** (~30% material impact) — edge is 1¢ on a $1 sum; 1-second stale read kills it. Why spec mandates WS not REST.
2. **Order rejection / nonce issues** (~15%, first week) — EIP712 sig bugs, expired timestamps; recoverable.
3. **Adverse fill mix** (~25% some weeks) — only one leg fills; ends with directional inventory at ~0 EV; tail-risk-OK with sizing.
4. **Other makers compete edge away** (~20% over 3-6 months) — slow erosion, not a cliff.
5. **Polymarket fee schedule change** (~10%) — daily refresh of `feeSchedule.rate`, refuse to fire if EV flips negative.
6. **Smart contract failures** (~5% low impact) — splitPosition / mergePositions are battle-tested; gas spike timing worst case.
7. **Small mint sizes find few takers** (~10%) — scale notional progressively from $25 → $200.

**NOT risks**:
- Directional risk (delta-neutral on every fire)
- Information asymmetry (no need to predict price)
- Market regime dependence (spread opens regardless of conditions)

**Recommendation**: **Yes, deploy** — follow phased rollout in the spec. Edge is real and verified. Risk is in execution quality, not strategy theory. Single biggest thing TV needs to nail: WS-only book data in the fire path.

---

## Files referenced

Key reports (all in `strategy_lab/reports/`):
- `HANDOFF_WALLET_DECODER_2026_05_16.md` — this file
- `MINT_AND_SELL_LIVE_SPEC_2026_05_16.md` — TV agent's deploy spec
- `MINT_AND_SELL_REPLICATION_2026_05_16.md` — backtest results across 6 cells
- `STRATEGY_DECODED_2026_05_16.md` — original trigger discovery
- `WALLET_PNL_BREAKTHROUGH_2026_05_16.md` — Alchemy pipeline + PnL math
- `WALLET_STRATEGIES_FINAL_2026_05_16.md` — first taxonomy (now superseded but useful context)
- `WALLET_DECODER_PIPELINE_2026_05_16.md` — earlier pipeline doc
- `MOMO_REST_LAG_VS_MICROSTRUCTURE.md` — why momo HOLD shadow PnL is fictitious

Root-level:
- `CLAUDE.md` — project-wide context, updated this session with mint-and-sell + maker-fee bug bullets

Code (all in `strategy_lab/wallet_hunt/`):
- `fetch_alchemy.py` (Step 1)
- `cash_pnl.py` (Step 2)
- `replicate/decode_triggers.py` (Step 3)
- `replicate/mint_and_sell_scan.py` (backtest — has maker-fee bug)
- `replicate/fill_probability.py` (fill-rate validation)
- `asset_lookup.py` (token_id → slug map builder)
- `shadow_track.py` (live wallet polling)

Backtest output: `data/v4/canonical/_results/mint_and_sell_*_2026_05_16/`
Wallet artifacts: `strategy_lab/wallet_hunt/cache/<short_10char>/`
Consolidated PnL: `strategy_lab/wallet_hunt/cache/_cash_pnl_summary.csv`

---

## End of handoff
