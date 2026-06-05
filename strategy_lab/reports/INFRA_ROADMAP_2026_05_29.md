# Infra Roadmap — fighting in the Polymarket up-down market (2026-05-29)

Synthesizes three research threads:
- `LAG_TAKER_FINAL_CONFIG_2026_05_29.md` + `TV_AGENT_SPEC_FAST_TAKER_LAGV2_2026_05_29.md` (the edge)
- `F2_DATA_INVENTORY_GAP_2026_05_29.md` (what data we have vs need)
- `INFRA_BUILD_RESEARCH_2026_05_29.md` (concrete feeds, latency, cost)

## 0. The reframe that makes everything coherent
Earlier work concluded "the market is efficient — no signal beats the price OOS"
(`EFFICIENT_MARKET_FINDING_2026_05_28.md`) and "maker-arb is closed"
(`NOCHASE_MERGEARB_VERDICT_2026_05_29.md`). Both stand. The surviving edge does NOT
contradict them because it is an **EXECUTION edge, not a prediction edge**:

> After a Chainlink Data Streams tick moves the implied outcome, the resting Polymarket
> CLOB book takes **~55s on average to reprice**. You don't predict better than the
> eventual price — you **buy the near-certain winner at a stale cheap ask inside that
> window, before the book catches up.** The market is efficient *in equilibrium*; the
> money is in the 5–55s it takes to GET there.

This is why "improve infra to fight" is exactly right: the edge IS latency + the right
signal feed. An open-source bot already runs this at 61.4% WR — so it's real, and it
will crowd. Move now.

## 1. The edge (validated, ready to shadow) — oracle-lag directional taker
From `LAG_TAKER_FINAL_CONFIG`, **R5 gated config**:
- Cells: **BTC + ETH, 5m** (SOL excluded — net drag, thin book; 15m later batch)
- Signal: `oracle_lag.price_delta_bps` (Binance-1s feed vs last Chainlink tick) measured
  over slot_start → slot_start+5s. Fire at **slot_start+5s** (freshest stale ask).
- Trigger: `|delta_bps| ≥ 3`, **hard cap 12bps** (≥12bps reverses: WR 56%, −$4.17/tr).
  Direction = side the price is leading.
- Gates: UTC hour < 18 (skip US-hours noise) + cross-asset confluence (other asset leading
  same way ≥3bps) [+ optional top-depth ≥ median].
- Exit: HOLD to Chainlink resolution + `LAG_REVERSAL_STOP` (bail at market if the move
  reverses through zero).
- Sizing: micro live = $1 base / $2 ≥5bps / $2 ≥8bps, ceiling $5. No Kelly.
- Fill model: `engine_v2.fill_at_book`, $25 walk, 85ms latency, same-token spread
  `ask0−bid0 ≤ 0.05` (NOT the cross-token vwap check — that's a maker problem).
- Fee: `LegacyConfig` (2% on winning profit only). **Fee-robust** (holds on both curves).

**Measured:** R5 = **+$3.42/$25 (+13.7%/fire), WR 68.1%, OOS t=2.78, ~22 fires/day,
maxDD −$227.** R7 (≥5bps, no confluence) = +$4.73/$25, WR 71.8%, OOS t=2.39, ~11.5/day.
Per-cell: BTC 5m +$2.19 (93% fill), ETH 5m +$2.02 (90% fill). OOS = ~21d (May 8–29).

**Deploy status:** the signal is ALREADY plumbed on VPS3 (`compute_oracle_lag`). Deploy =
add 4 gates + 4 sleeves to the existing sniper-v5 controller, run **shadow** until
AC met (≥2 weeks, n≥200 filled fires, WR≥60%, mean pnl/fire>0 after fee, 7d rolling WR
not declining), then micro live. **No new infra strictly required to start.**

## 2. Prioritized infra build

| P | Upgrade | Why | Effort | Verdict |
|---|---|---|---|---|
| **P0** | Ship oracle-lag taker shadow sleeves (BTC/ETH 5m) | The validated edge; already plumbed | ~days (gates+sleeves) | **DO NOW** |
| **P1** | Subscribe Polymarket RTDS WS `crypto_prices_chainlink` | Exact settlement price, **no auth, free**; replaces Binance proxy → ground-truth signal, removes basis-inference lag | low | **BUILD** |
| **P2** | Cross-exchange TRADE-tape collector (Binance/Bybit/OKX/Coinbase via `cryptofeed`) | (a) lead-lag pre-signal fires taker 1–30s earlier; (b) **the data needed to test the F2 slug-selector** (§3). Free public WS, ~1–2 GB/day | ~1 wk | **BUILD** |
| **P3** | Measure RTDS-relay lag vs direct Chainlink Data Streams WS | Only pay for Chainlink enterprise creds if the Polymarket relay adds >100ms | low (measure first) | **INVESTIGATE** |
| P3 | Revive dormant VPS2 collectors (OKX/Coinbase/Kraken klines stale since May 16); fix funding feeds | Hygiene; funding-spike signal for F2 | med | INVESTIGATE |
| — | Move VPS into AWS eu-west-2 (London) colo | Ireland already <5ms; ~4ms gain vs a 55s window is irrelevant. Bottleneck is *detecting the oracle move*, not order submission | high | **SKIP** |
| — | Per-order L3 (ADD/CANCEL/maker-id) real-time feed | **Does not exist** — Polymarket WS is L2-only (see §3) | n/a | **NOT POSSIBLE** |

Execution facts (from INFRA_BUILD_RESEARCH): FOK / marketable-limit order types exist;
EIP-712 signing <1ms (not a latency concern); `POST /order` limit 3,500/10s (ample).
Add `custom_feature_enabled:true` to the CLOB WS for `best_bid_ask` (faster top-of-book).

## 3. F2 — "what more do we need?" (the honest answer)
F2's edge = **slug SELECTION** (they fire on ~4% of slots where a contrarian fade pays).
The TRIGGER (flow-burst + fade) is already decoded & reproducible on F2's slugs; it loses
on the broad universe. The selector is the missing piece. Mapping the owner's belief to reality:

| F2 input | Status | Detail |
|---|---|---|
| "all polymarket trades" | ✅ HAVE (executed matches) | 39M-row tape gives `n_trades_5s`, flow_imbalance — this is how the burst trigger was found. **But:** matches only, **no maker address**, and NOT order-lifecycle events |
| Cross-exchange basis @ ~100ms (Bybit/OKX/Coinbase TRADE tape) | ❌ **DON'T HAVE** | We only have 1-min KLINES (OKX/Coinbase/Kraken), stale since May 16; **zero Bybit**; no per-trade tick for any non-Binance venue. **This is the build (P2).** |
| Liquidations | ✅ HAVE (HL, 5.27M rows, current) | Funding is stale/partial (Binance/Bybit geoblocked) |
| Chainlink settlement signal | ✅ HAVE | `chainlink_rtds` ~1Hz, current |
| Per-order maker-quote events (who posted, when) | ❌ **NOT AVAILABLE from Polymarket WS** | Polymarket exposes **L2 only** (`price_change` aggregated per level + book snapshots) — there is **no L3 ADD/CANCEL/maker-id stream**. Maker identity is only reconstructable **on-chain / via data-api `/trades`** (batch, not sub-second) |

**Corrected verdict (supersedes the F2 verdict's "need the CLOB order-event tape"):** the
real-time per-order maker feed F2 was assumed to use **does not exist** on Polymarket's API.
So either F2 reconstructs maker behavior on-chain (slow) or — more likely — **their
slug-selector keys off cross-exchange basis dislocations**, which is the one input we can
build and the F2 verdict's own Phase-1 hypothesis.

**Concrete F2 path:**
1. Build the P2 cross-exchange trade-tape collector (Binance/Bybit/OKX/Coinbase, `cryptofeed`).
   Run forward; also backfill what's possible. ~1–2 GB/day.
2. Re-join F2's historical 102 fired slugs (we have them) to cross-exchange basis at each
   fire moment. **Test:** does F2 fire only when binance-vs-{bybit,okx} basis is wide?
   If yes → that's the selector; gate the decoded fade trigger on it and re-run the broad
   universe. If basis doesn't separate fires from controls → the selector is on-chain
   maker-targeting we can't reach, and F2 stays parked.
3. (Optional, batch) reconstruct maker addresses on the fired slugs via data-api `/trades`
   + on-chain CTF fills to test the "post-and-walk maker targeting" hypothesis offline.

Note: P2 is **dual-use** — the same cross-exchange tape feeds the oracle-lag taker's
lead-lag pre-signal (A6) AND the F2 selector test. Build it once.

## 4. Recommended sequence
1. **P0 now:** wire + shadow the oracle-lag taker (BTC/ETH 5m). This is the money item.
2. **P1 now (parallel):** add the RTDS `crypto_prices_chainlink` WS subscription; A/B the
   ground-truth signal vs the Binance proxy in shadow.
3. **P2 this week:** stand up the cross-exchange trade-tape collector on Ireland (or VPS2).
   Feeds both the taker pre-signal and the F2 selector test.
4. **Then:** run the F2 basis-selector test (§3.2). Decide F2 go/park on the result.
5. **Skip** AWS colo and direct Chainlink enterprise until a measurement says otherwise.
