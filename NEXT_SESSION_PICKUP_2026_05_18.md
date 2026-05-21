# Next Session — Start Here

_2026-05-18. Session pickup document. Read this FIRST before diving in._

---

## Your goal next session

**Deep-dive on the Mint-and-Sell maker V2 strategy to make it deployable.**
V1 is dead (known flaws — see §"Why V1 is dead" below). V2 is the live
candidate. The implementation spec is mostly written; what's missing is
the empirical validation of the per-fire vs slug-level economics under
real Polymarket fees.

---

## Where to start

```bash
cd "C:\Users\alexandre bandarra\Desktop\global"

# 1. Read the V2 replication report (the EMPIRICAL truth)
#    Confirms slug-level aggregation flips positive
cat strategy_lab/reports/MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md

# 2. Read the implementation spec (now 1479 lines after this session)
#    Sections to focus on:
#      §1.3-1.4 Fire sequence + slug lifecycle
#      §4.3 InventoryManager component
#      §5 Paper-trade simulator
#      §8 PnL accounting (§8.5 worked example, §8.6 mid-slug MTM, §8.7 PaperLedger)
cat strategy_lab/reports/MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md

# 3. Run the V2 scanner to confirm reproducibility
py -3 -X utf8 strategy_lab/wallet_hunt/replicate/mint_and_sell_scan_v2.py
```

---

## Strategy summary (what V2 does)

**Trigger**: when `best_ask(Up) + best_ask(Down) > $1.00` (sum_asks > $1).
The two-sided ask is the structural mispricing — together they pay more
than $1 for the pair, but their sum cannot exceed $1 at fair value.

**Action** (per fire, at slug t+120 or later):
1. `CTF.splitPosition($N)` — pay $N USDC, receive N Up tokens + N Down tokens
2. Post limit `SELL N×Up @ ask_up` (maker)
3. Post limit `SELL N×Down @ ask_dn` (maker)
4. Wait up to 60s for fills:
   - BOTH fill → arbitrage captured (sum_asks − $1) × N + 2× maker rebate
   - ONE fills → keep N tokens of the unfilled side as inventory; hold to settlement
   - NEITHER fills → `mergePositions(N)` recovers $N USDC (gas only)

**Fees (verified)**:
- Makers pay **$0** + receive rebate of `0.20 × 0.07 × p × (1−p)` per share
- Takers pay `0.07 × p × (1−p)` per share on every fill
- The "2% on profit only" legacy model is WRONG — V2 uses the correct curve

**Wallet validation** (4 chain-decoded operators):
- `0xeebde7a0` — $344k/day (1.06d sample, largest scale)
- `0x04b6d7e9` — $212k/day (1.82d sample)
- `0x89b5cdaa` — $10k/day (4.5d sample)
- `0xf7f0b0b1` — $281/day (3.54d sample, small scale)

All 4 wallets share the same on-chain signature: `splitPosition` →
limit-sell both sides → optional `mergePositions` if neither fills.

---

## Where to dig deeper

The implementation spec is comprehensive but the V2 backtest has known
ambiguities. Open questions:

### Q1: Per-fire vs slug-level — confirm the regime

V2 report shows:
- Per-fire HOLD PnL: −$0.06 to −$0.15/op (negative)
- Slug-level in BOTH_SIDES_PARTIALS regime: +$0.04 to +$0.41/slug (positive)

The strategy only works when accumulating inventory across many fires
per slug (the 30-170 fires/slug regime). What's the minimum fires-per-slug
threshold that flips the sign?

```bash
# Re-run with different cooldown / max-fires-per-slug to find the
# minimum fire density that makes it work
py -3 strategy_lab/wallet_hunt/replicate/slug_level_aggregation.py \
    --cell btc_15m --min-fires-per-slug 30
```

### Q2: Wallet PnL gap — explain the 200-10,000x

The V2 backtest projects $20-50/day per wallet at $2.5 notional. But
wallets report $10k-344k/day. Three hypotheses:

1. **Higher effective BOTH-fill rate** in production (70-85% vs our
   measured 35-55%). Our `check_fill_window` uses best_bid_opp reaching
   our ask — overly conservative.
2. **Self-selection** to better fire moments — wallets wait for tighter
   books or active periods. Our scanner fires every L25 snapshot with
   sum_asks > $1.005.
3. **Scale effects** beyond what sampling reveals — 5.2M opportunities
   × thin per-op edge requires running at scale we haven't simulated.

Spending time on (1) — better fill simulation — is the highest-leverage
investigation.

### Q3: Partial-fill policy — HOLD vs MARKET_EXIT vs HYBRID

Tested in `MINT_AND_SELL_PARTIAL_FILL_POLICY_2026_05_16.md`. Summary:
- HOLD wins. MARKET_EXIT loses an extra $1-4/op due to thin opposite-side
  bid. HYBRID rarely triggers.
- Don't market-exit. Just hold the unfilled leg.

This is well-decided. Move on.

### Q4: Pre-mint pattern — single mint TX → 1500 sells

`0x89b5cdaa` showed exactly 1 mint TX producing the inventory for 1500
subsequent sell orders. This means the wallet pre-mints at slug start,
not per-fire. Spec §1.4 already encodes this. Worth verifying that the
pre-mint sizing is sufficient under high-fill regime.

### Q5: ETH/SOL extension — does V2 generalize?

V2 report shows all 6 cells (BTC/ETH/SOL × 5m/15m) have BOTH_SIDES_PARTIALS
positive. The eth_5m cell has the **highest** mean PnL/slug at +$0.41.
Worth testing ETH 5m as a primary deploy target alongside BTC 15m.

---

## Files you'll touch next session

| File | Purpose |
|---|---|
| `strategy_lab/reports/MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md` | Empirical truth |
| `strategy_lab/reports/MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md` | Spec (now 1479 lines, drop-in PaperLedger in §8.7) |
| `strategy_lab/reports/MINT_AND_SELL_PARTIAL_FILL_POLICY_2026_05_16.md` | HOLD vs MARKET_EXIT verdict |
| `strategy_lab/wallet_hunt/replicate/mint_and_sell_scan_v2.py` | V2 scanner (corrected fees) |
| `strategy_lab/wallet_hunt/replicate/partial_fill_policy_compare_v2.py` | Policy comparison |
| `strategy_lab/wallet_hunt/replicate/slug_level_aggregation.py` | Slug-level rollup |
| `strategy_lab/wallet_hunt/replicate/replay_at_wallet_conditions.py` | Replay using wallet's actual conditions |
| `strategy_lab/wallet_hunt/replicate/inspect_wallet_sizing.py` | Sizing calibration from chain |
| `strategy_lab/wallet_hunt/replicate/check_premint_pattern.py` | Verifies pre-mint vs per-fire |
| `strategy_lab/wallet_hunt/replicate/analyze_fire_cadence.py` | Fires/slug cadence stats |
| `strategy_lab/fees.py` | Correct Polymarket fee + rebate math |

---

## Why V1 is dead

`MINT_AND_SELL_LIVE_SPEC_2026_05_16.md` is the V1 live spec. It uses:
- Wrong fee model: "80% of taker fee" for maker side (actual: $0 + rebate income)
- Wrong notional: $200 (wallets use $3-6, smaller fires)
- Wrong cooldown: 10-snapshot (wallets fire every snapshot when conditions hold)
- Wrong entry threshold: ~$1.035 effective (wallets at $1.010)

Per the V2 report, fixing these flipped a per-slug −$25k/day projection
into a +$20-50/day projection (still 100-1000x short of wallet performance
but at least directionally correct). The remaining gap is the fill model.

**Do not deploy V1 anywhere.** Use V2 spec + corrected fees.

---

## Quick wins for the deep-dive

1. **Re-run the V2 scanner per-cell with the corrected fee model**, capture
   per-fire stats AND slug-level stats. Confirm the BOTH_SIDES_PARTIALS
   threshold (probably ~30 fires/slug minimum).

2. **Build a paper-trade harness** using the §8.7 PaperLedger reference
   class. Run it on canonical L25 + chainlink for 1 historical slug end-to-end
   as the first integration test.

3. **Investigate the fill model** — replace `check_fill_window` (best_bid
   reaches ask) with the trade-tape fill detector (cross-check actual
   maker fills from the Polymarket trades parquet against our simulated
   fires).

4. **Re-spec the partial-fill exit logic** with a unified ledger that
   covers HOLD + merge_at_slot_end + redeem_winner — the spec already
   has §8.5 worked example for this.

---

## Other stuff (in case you forget)

### Critical conventions (still apply — see CLAUDE.md for full list)

1. UTC microseconds for `*_us` columns; never localize
2. `ws_s = slug_suffix - window_s` (PREVIOUS slot start, not slug suffix)
3. Outcome = chainlink RTDS (never derive from binance)
4. `asof_strict` for causal lookups
5. L25 walk via `book_walk_fill` for fills
6. Real Polymarket fees: `0.07 × p × (1-p)` per share on every fill (taker)
   or maker rebate `0.20 × 0.07 × p × (1-p)` per share (maker)
7. Polymarket CLOB hosted **AWS eu-west-2 (London)** — Ireland VPS optimal

### Run the ws_s self-test BEFORE any backtest

```bash
py -3 -X utf8 data/v4/canonical/_test_ws_s.py
# Must print: === ALL CHECKS PASSED ===
```

### Data status (2026-05-18)

| Dataset | Window | Notes |
|---|---|---|
| `resolutions_from_rtds.parquet` | Apr 24 - May 16 01:00 | Chainlink-derived (canonical) |
| `klines_1m.parquet` | Apr 14 - May 16 03:46 | Binance spot WS, 1MIN |
| `chainlink_rtds.parquet` | Apr 24 01:38 - May 16 03:47 | 1Hz oracle feed |
| `trades_polymarket/btc.parquet` | Apr 26 - May 16 07:04 | 24M trades, 1µs resolution |
| `trades_polymarket/eth.parquet` | Apr 26 - May 16 07:02 | 6M trades |
| `trades_polymarket/sol.parquet` | Apr 26 - May 16 07:02 | 2.7M trades |
| L25 OB streaming (3 files merge) | Apr 14 - May 16 | 5.13 GB BTC, smaller ETH/SOL |
| `tier1_entries_at_t120/btc.parquet` | Apr 24 - May 15 | 15,808 (slug, outcome) snapshots |

---

## Cyclops S7 X1 — deployment state (parallel track)

**Status: PAPER-DEPLOY-READY.** Passes G1+G3+G4 at $1 stake on real fees.

- Spec: `cyclops/PAPER_DEPLOY_SPEC.md` (already written)
- Package: `cyclops/` (full code, 151 tests passing)
- Results: `cyclops/_results/MASTER_TABLE_REAL_FEES.txt` shows X1 is only strategy that passes all 4 gates.

Could deploy this in parallel with V2 development if you want PnL today
while debugging V2.

```bash
# To re-run the X1 backtest end-to-end:
py -3 -X utf8 -m cyclops.backtest.runner \
    --asset BTC --tf 5m \
    --vwap-min 0.30 --require-mom-abstain --full-depth \
    --out cyclops/_results/p5_full_depth_p3.csv

# Then run the master table with real fees + sleeve_active filter:
py -3 -X utf8 cyclops/_results/_real_fees_rerun.py
```

---

## What was done this session (2026-05-17 → 2026-05-18)

For context — these reports were generated this session:

- `strategy_lab/reports/WALLET_CATALOG_2026_05_17.md` — 9 wallet catalog
- `strategy_lab/reports/WALLET_STRATEGIES_DECODED_2026_05_17.md` — per-wallet decode
- `strategy_lab/reports/F2_TRIGGER_DECODE_2026_05_17.md` — F2 partial decode
- `strategy_lab/reports/F2_REPLICATION_VERDICT_2026_05_17.md` — F2 replication attempt
- `strategy_lab/reports/F2_FINAL_VERDICT_2026_05_18.md` — F2 final (not replicable from canonical)
- `strategy_lab/reports/MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md` (extended) — §8.5/8.6/8.7 added
- `cyclops/PAPER_DEPLOY_SPEC.md` — Cyclops X1 paper-deploy spec
- New analysis modules in `strategy_lab/wallet_hunt/` and `strategy_lab/f2_replica/`

This session's TL;DR: tried hard to replicate F2 (one of the high-PnL
wallets) — failed because slug-selection is the alpha and we lack
sub-second CLOB events. Cyclops X1 stays validated. Mint-and-sell V2
remains the next implementation target.
