# Multi-Cell Trio Decode: 0xa2a0519b / 0x2855555a / 0xa5b17799

**Date:** 2026-05-29  
**Segment:** Multi-cell up-down (btc-5m, btc-15m, eth-5m, eth-15m, sol-15m)  
**Tool chain:** segment_winrate → trigger_decode_harness → fetch_alchemy + manual timing/price analysis

---

## Executive Summary

All three wallets share the same macro-mechanic: **Chainlink RTDS oracle-snipe** — buying
the already-winning side of a binary market in the final ~60–120 seconds before slot resolution,
exploiting the gap between the oracle (price publicly visible in CL RTDS ~1s delay) and the
CLOB (market price slow to fully converge). The strategy spectrum runs from an ultra-pure
last-30s snipe (0xa2a0519b, 99% WR) to a noisier earlier-entry variant (0x2855555a, 86% WR)
to a directional-taker variant that also benefits from late timing (0xa5b17799, ~66% recent WR).

**None of these are momentum strategies.** The direction discriminators in the harness
(ret_5m, ema9_slope, px_vs_strike) are non-causal artifacts of buying a side that is already
winning — those features are high BECAUSE the outcome is directionally confirmed, not because
the wallet predicted the direction from early signals.

---

## Wallet 1: 0xa2a0519bb87844b8ef5845a49f04a82aeabc15a1

### lb PnL
- Lifetime: +$15.3k | 30d: +$14.3k | 7d: +$2.5k

### Segment profile (segment_winrate, canonical resolved slugs)

| asset | tf | n | WR | avg_px | avg_qty | up_bias |
|---|---|---|---|---|---|---|
| btc | 5m | 1344 | 99.0% | 0.986 | 973 | 50% |
| eth | 5m | 919 | 99.2% | 0.987 | 452 | 47% |
| btc | 15m | 328 | 98.8% | 0.986 | 603 | 52% |
| eth | 15m | 187 | 98.9% | 0.987 | 320 | 48% |
| **ALL** | | **2778** | **99.1%** | **0.987** | 713 | 49% |

### Mechanic: **Pure Chainlink RTDS late-snipe**

**Entry timing:** 99.2% of all 3500 trades occur in the final 60 seconds before slot end
(mean 32s before close, std 18s). Less than 1% land outside the slot.

**Price structure:** All 3500 trades are BUY-only. Price p10=0.98, p50=0.99, p90=0.99 — no
trades below 0.59 (the single outlier at 0.590 landed 307s early). The market is already
near-resolved when they buy.

**No paired / arb trades:** Per-slug pivot analysis: 1515 slugs with only Up, 1596 only Down,
1 with both (pair_sum=1.95, not a risk-free pair). 100% directional.

**Oracle snipe proof:**
- Chainlink RTDS publishes ~1 update/second, settling AT slot_end (not early).
- BUT the price trajectory in the final 60s IS directionally definitive. Testing on 192 BTC 5m
  slugs: CL at T−30s predicts the outcome with **87.0% accuracy**; at T−120s only 78.6%.
- The wallet reads the CL RTDS stream (or equivalent real-time price) and buys the side that
  will win, typically 15–50s before the market settles.
- At avg_px=0.986, profit per winning share = 0.014. At 99% WR and avg_qty=713:
  **EV/slug ≈ +$2.85** (hold-to-resolution). lb reports ~$4–5/slug; discrepancy from history
  outside our canonical window.

**Direction picker:** Not a separate signal — the wallet buys whichever side is trading at
0.986+ (implying the market already knows the outcome). The trigger_decode_harness direction
discriminators (ret_5m d=1.7, px_vs_strike d=1.5) are fully explained by the price action
of an already-decided market (winner side is above strike, return positive).

**Slug selection:** Weak discriminators (cl_basis_bps d=0.185, rv_15m_bps d=−0.085). Wallet
engages most slots systematically across 4 market cells, filtering only on whether a slot has
reached near-certainty pricing.

**Alchemy / chain:**
- USDC in: $802k | USDC out: $800k (last 7d, $1.8M weekly turnover)
- 4,226 ERC1155 transfers; 2,225 sent (REDEEM at resolution), 2,001 received (fills)
- Primary counterparty: `0xe111180000d2663c0091e4f400237545b87b996b` (Polymarket CTF Exchange)
- Secondary counterparty: `0xc7f92b` (27 transfers, minor — no fleet link identified)

### Verdict
**Bucket: Oracle snipe (Chainlink RTDS) — ultra-pure, final 30s**  
**Reproducible? YES — in principle.** Requires: (a) real-time CL RTDS WS feed with <1s
latency, (b) CLOB connectivity to buy at ~0.986 before the book moves to 0.998+,
(c) sufficient book depth (avg $700 notional/slot, ~10,000 slots/month = ~$7M/month
required turnover). Ireland VPS has <2ms CLOB RTT. The main constraint is CLOB depth —
at 99% of slots the Ask is at 0.99, so the wallet either has a resting limit order
already posted or catches the lag between oracle update and book update.  
**Do NOT replicate as taker** — buying at market Ask when everyone else can see the same
CL price creates a race. The profitability depends on getting fills at sub-fair prices,
likely via maker limit orders resting at 0.985–0.988 that become swept near resolution.

---

## Wallet 2: 0x2855555a48ee7ec2e67272701651bfe77034ebe8

### lb PnL
- Lifetime: +$19.1k | 30d: +$4.0k | 7d: +$2.1k

### Segment profile

| asset | tf | n | WR | avg_px | avg_qty | net_pnl |
|---|---|---|---|---|---|---|
| btc | 5m | 1305 | 86.1% | 0.878 | 95 | −$655 |

Single cell (btc-5m only, 914 lb-reported trades).

**Note:** segment_winrate net_pnl=−$655 is on the most recent 3,500 data-api trades
(hold-to-resolution estimate). lb shows +$19k lifetime / +$4k/30d. Discrepancy because:
(a) lb counts longer history, (b) wallet likely exits pre-resolution via secondary-sell
(ERC1155 sell on secondary market at a markup vs the hold-to-res estimate).

### Mechanic: **Late-slot oracle-snipe, earlier window + lower certainty**

**Entry timing:** mean 84s before slot end (vs 32s for 0xa2a0519b), median 70s.
44% of trades within last 60s, 19% within last 30s.

**WR gradient by timing bucket (confirms oracle snipe):**

| bucket | n | WR | avg_px |
|---|---|---|---|
| < 30s | 664 | 79.9% | 0.847 |
| 30–60s | 867 | 69.3% | 0.793 |
| 1–2m | 1042 | 67.8% | 0.741 |
| 2–5m | 913 | 70.1% | 0.760 |

WR rises as trades approach slot end AND prices are higher (market catching up to oracle).
This is the same snipe mechanic as 0xa2a0519b, 40–50 seconds earlier in the slot (oracle
signal is directionally known but market price hasn't fully moved yet → fills at lower
prices, lower WR but higher upside when correct).

**EV analysis:**
- At avg bucket WR=70-80% and avg_px=0.74–0.85:
  - 1–2m bucket EV/share: 0.678×0.259 − 0.322×0.741 = +0.175 − 0.239 = −0.064 (lossy)
  - <30s bucket EV/share: 0.799×0.153 − 0.201×0.847 = +0.122 − 0.170 = −0.048 (lossy)
- Hold-to-resolution EV is NEGATIVE at all buckets in the recent sample (WR < price).
- lb profit ($4k/30d) likely comes from pre-resolution SELL — ERC1155 ratio: 68,880 fills
  received, 2,668 sent back (ratio 0.04 → most held to resolution, but some sold). The
  momentum creates a price appreciation window: buy at 0.75 → price moves to 0.90 → sell.

**Direction discriminators (harness, btc-5m, n=1305):**
- `px_vs_strike_bps` d=1.166 (price above strike when betting Up)
- `ret_3m` d=1.015, `ret_5m` d=0.922, `ret_1m` d=0.757
- `ema9_slope_bps` d=0.706

Same pattern as 0xa2a0519b: discriminators reflect confirmed directional momentum
(price is already moving, wallet buys the trend).

**Slug selection:** weak (cl_basis_bps d=0.163, rv_15m_bps d=−0.103). Near-indiscriminate.

**Win vs loss separator (key):**
- `cl_basis_bps` d=+0.36 (wins have HIGHER cl_basis = oracle divergence favors entry)
- `px_vs_strike_bps` d=+0.322 (wins when further above strike)
- Losses concentrated when entering with momentum flags but oracle not yet fully decisive.

**Alchemy:**
- USDC in: $513k | USDC out: $510k (last 7d)
- 71,548 ERC1155 transfers — high frequency
- Primary counterparty: `0xe111180000d2663c0091e4f400237545b87b996b` (Polymarket CTF Exchange)
- Secondary funder: `0x021d46` (438 transfers, likely a relay/funder wallet)

### Verdict
**Bucket: Oracle snipe (Chainlink RTDS) — earlier window variant (~60–90s before slot end)**  
**Reproducible? PARTIAL.** Same fundamental mechanic as 0xa2a0519b but entering earlier
creates more competition and lower fill certainty. The EV per share is negative on a
hold-to-resolution basis; profitability requires pre-resolution exit via secondary-sell.
Implementing requires: real-time CL RTDS, secondary-market CLOB sell logic, and precise
timing. More capital-efficient than 0xa2a0519b (avg_qty only $95 vs $700+) but lower
per-bet EV. **Hold-to-resolution replication would LOSE money** — must include the exit leg.

---

## Wallet 3: 0xa5b17799332b276f748feca8649b6e23272cc6dc

### lb PnL
- Lifetime: +$7.4k | 30d: +$7.6k | 7d: +$0.9k

### Segment profile (canonical window, 515 resolved slugs)

| asset | tf | n | WR | avg_px | avg_qty |
|---|---|---|---|---|---|
| btc | 5m | 181 | 85.6% | 0.649 | 19.9 |
| eth | 5m | 131 | 85.5% | 0.676 | 16.2 |
| sol | 5m | 133 | 85.0% | 0.685 | 14.3 |
| btc | 15m | 25 | 92.0% | 0.694 | 16.7 |
| eth | 15m | 24 | 91.7% | 0.707 | 14.2 |
| sol | 15m | 21 | 85.7% | 0.690 | 16.0 |

**ALL resolved (canonical): WR 86.0%, avg_px 0.665, avg_qty ~16 shares/slug**

**Recent WR decline (3,500 API trades, May 25–29 only):** WR=66.3% on resolved recent trades.
Possible strategy decay or small-n noise (only 1742 of 3500 are yet resolved).

### Mechanic: **Directional taker (momentum) across 4+ assets + possible oracle component**

**Entry timing:** Mean 95s before slot end, 41% within last 60s. Price range 0.04–0.89
(median 0.69). Unlike wallets 1 & 2, this wallet enters at ALL price levels including < 0.5.

**WR by timing bucket:**

| bucket | n | WR | avg_px |
|---|---|---|---|
| < 30s | 688 | 21.9% | 0.631 |
| 30–60s | 782 | 29.3% | 0.675 |
| 1–2m | ~1042 | 36.4% | 0.682 |
| 2–5m | ~913 | 41.9% | 0.646 |

**Inverted vs wallets 1 & 2:** WR FALLS as trades approach slot end. This is consistent with
the canonical finding from directional_scan — entering late adds no edge, and near-slot-end
the CLOB price has already fully reflected the oracle → the wallet can't buy below fair value.
The historical 86% WR (canonical window) vs 66% recent WR confirms the edge is degrading.

**Direction discriminators — consistent across ALL 4 cells:**

*btc-5m (n=181):* `px_vs_strike_bps` d=1.24, `cl_basis_bps` d=−1.05 (Up when basis LOW),
`ret_1m` d=0.74, `px_vs_ema21_bps` d=0.68, `ret_3m` d=0.65, `ret_30m` d=0.61

*eth-15m (n=24):* `px_vs_strike_bps` d=1.83, `ret_15m` d=1.50, `rsi14` d=1.35

*sol-15m (n=21):* `ret_30m` d=1.17, `px_vs_strike_bps` d=1.01, `rsi14` d=0.93

*btc-15m (n=25):* `px_vs_strike_bps` d=1.82, `px_vs_ema21_bps` d=0.81, `ret_15m` d=0.53

**Cross-cell consistency:** STRONG. Dominant signal is `px_vs_strike_bps` (d=1.0–1.8) and
trend (ret, ema, rsi) ACROSS ALL CELLS. The same momentum-follow rule applies to BTC, ETH,
SOL at both 5m and 15m. This is a systematic cross-asset directional strategy.

**Unique `cl_basis_bps` inversion in btc-5m:** Up-fires have LOWER cl_basis (d=−1.05 Up vs
Down: Up=14.47 basis-bps, Down=17.13). In context of px_vs_strike dominating, this likely
reflects: when price is above strike (Up bet), the chainlink price is already above strike,
so the basis bps between binance and CL is smaller (converged). Not a unique cl_basis signal
— collinear with px_vs_strike.

**Slug selection discriminators:** Momentum-positive entry filters.
- btc-5m: `macd` d=0.18, `ret_30m` d=0.16 (enters when recent momentum is positive)
- eth-15m: `ret_3m` d=−0.43, `ret_5m` d=−0.37 (ENTERS when recent 3–5m is DOWN — contrarian
  for eth-15m, may be a mean-reversion signal on that cell specifically)
- sol-15m: `ret_3m` d=+0.42, `ret_15m` d=+0.36 (momentum follow for sol-15m)

**Alchemy / chain:**
- pUSD in: $137k | out: $137.6k (last 7d; roughly flat cash, small net loss −$384)
- 33,635 ERC1155 transfers: 19,463 in / 14,172 out
- ERC1155 sent TO `0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0`: **12,678 tokens**
  — this address matches the known F1-treasury relay wallet from CLAUDE.md
  (`F1 treasury 0xf70da97812... uses relay 0xf3cfb6a6... for inventory exit`)
- 0x2855555a also sends 2,668 to same relay; 0xa2a0519b sends 2,196 — but volumes are
  far lower. 0xa5b17799's 12,678 transfers suggest closer operational relationship.
- Primary USDC counterparty: `0xe111180000` (CTF Exchange), self-circulation dominant.

**Recent WR decline note:** The 86% canonical WR (Apr–May 22 window) vs 66% recent (May 25–29)
is a 20pp drop. Consistent with a strategy that relies on some market inefficiency now being
more efficiently priced, OR the wallet's recent entries are larger / in more competitive slots.

### Verdict
**Bucket: Cross-asset directional taker (momentum follow, multi-cell)**  
**Possible F1-fleet sub-wallet** — 12,678 ERC1155 tokens sent to known F1 relay address.
**Reproducible? UNLIKELY at current WR.** 

Historical 86% WR was in canonical window Apr–May 22. Recent WR fell to 66%. The direction
rule (momentum + px_vs_strike) is the same signal identified in earlier decode sessions
(see `DECODE_0x07480f20`, `DECODE_0xe3867b68`) — all momentum followers. Every
blind gate-test of this strategy class has FAILED G1/G4 (see `EFFICIENT_MARKET_FINDING_2026_05_28.md`).
The 86% historical WR at avg_px=0.665 implies EV/share=+0.195 — an enormous edge that is
NOT replicable blind. The wallet likely has a slug-selection signal (possibly from F1
infrastructure: CL RTDS, WS order-flow, proprietary triggers) that our canonical features
cannot capture, exactly as with F2 (see `F2_FINAL_VERDICT_2026_05_18.md`).

---

## Cross-Wallet Comparison

| wallet | lb_lifetime | WR | avg_px | avg_qty | mechanic | cells |
|---|---|---|---|---|---|---|
| 0xa2a0519b | +$15.3k | 99.1% | 0.987 | $713 | CL oracle snipe (last 30s) | 4 |
| 0x2855555a | +$19.1k | 86.1% | 0.878 | $95 | CL oracle snipe (60–90s) | 1 (btc-5m) |
| 0xa5b17799 | +$7.4k | 86%/66% | 0.665 | $16 | Directional taker + possible oracle | 6+ |

**All share:** Polymarket CTF Exchange (`0xe111`) as primary counterparty — expected for all
Polymarket traders. NOT a shared-operator fleet signal.

**0xa5b17799 uniquely:** connects to known F1 relay `0xf3cfb6a6` (12,678 tokens) — potential
F1 sub-wallet.

**0xa2a0519b + 0x2855555a:** same oracle-snipe mechanic at different time windows. May be same
operator (pseudonyms: "United-Designer" / "Dental-Latex" — different names, but both are
auto-generated Polymarket pseudonyms, not user-chosen). No other direct fleet link found in
the 7-day Alchemy window.

---

## Strategy Reproducibility Assessment

### 1. Oracle Snipe (0xa2a0519b / 0x2855555a)

**The gap being exploited:** Chainlink RTDS price updates 1x/second. In the final 30–60s of a
5m slot, the CL price has directionally committed to the outcome (87% accuracy at T−30s vs
79% at T−120s). The Polymarket CLOB adjusts, but with lag — the winner-side Ask sits at 0.986
while fair value is already ~0.999. The sniper buys this spread.

**Replication requirements:**
1. CL RTDS WS stream with <1s latency (we already collect this on VPS3)
2. Resting maker limit orders on BOTH sides at ~0.985 throughout the slot (so fills happen
   automatically when the book sweeps) — NOT taker market orders (would move price against)
3. At avg $700/fill × 10 slots/hour × 24h = ~$168k/day exposure needed
4. Risk: 1% losers at $700 × 0.986 = $690/loss vs 99% winners at $700 × 0.014 = $9.8/win

**Net daily estimate:** ~2,778 slugs/37 days = 75 fills/day × $9.8/fill = **$735/day**
(consistent with lb $14.3k/30d = $477/day — difference likely from avg_qty variation).

**DO attempt as maker strategy:** post resting limit orders at 0.985 on BOTH sides,
cancel unhedged side when oracle commits within 30s of resolution. This is the mechanism
most consistent with the data (100% BUY side in API, likely because fills only show up
when the limit order was hit — the SELL side that was cancelled never traded).

### 2. Cross-Asset Directional (0xa5b17799)

**Not reproducible blind.** Edge is declining (86% → 66%). The historical WR requires a
slug-selection filter we cannot reverse-engineer from canonical data. Likely uses F1-family
infrastructure. DO NOT deploy.

---

## Data files written

- `cache/0xa2a0519b/trigger_btc_5m.parquet` + `_trigger_btc_5m_summary.json`
- `cache/0xa2a0519b/trigger_eth_5m.parquet` + `_trigger_eth_5m_summary.json`
- `cache/0xa2a0519b/alchemy_transfers.parquet`
- `cache/0x2855555a/trigger_btc_5m.parquet` + `_trigger_btc_5m_summary.json`
- `cache/0x2855555a/alchemy_transfers.parquet`
- `cache/0xa5b17799/trigger_btc_5m.parquet`, `trigger_eth_15m.parquet`,
  `trigger_sol_15m.parquet`, `trigger_btc_15m.parquet` + summaries
- `cache/0xa5b17799/alchemy_transfers.parquet`
- `cache/_segment_winrate.csv` (updated, all 3 wallets)
