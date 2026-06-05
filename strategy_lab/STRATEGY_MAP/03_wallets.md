# Wallet Decodes — Strategy Map

_Last updated: 2026-06-03. Source reports: `strategy_lab/reports/`._

---

## Wallet Table

| Wallet (short) | Strategy class | Profitable? ($/day or lifetime) | Trigger reproducible? | Copyable / Deployable? | Why | Report ref |
|---|---|---|---|---|---|---|
| **0xb27bc932** | Maker pair-arb (HFT CLOB scalper — 99.98% maker, both-sided per slug, relay-exit via 0xf3cf) | YES — +$918k lifetime / **$254k/day** | Mechanics decoded; relay-exit path identified | **NO** — not currently deployable | Requires sub-second queue priority + relay-wallet settlement infra; pair-arb itself proved net-negative in our own shadow (censoring reversal); copy attempt 0xcfb103c3 lost money | `WALLET_STRATEGIES_DECODED_2026_05_17.md`, `NEW_WALLETS_ALPHA_DECODE_2026_05_18.md`, `WALLET_B27_DECODE_2026_05_20.md` |
| **0xeebde7a0** | Mint-and-sell maker (limit bids both sides + taker WHEN book stale; inventory exits via 0xf3cf relay) | YES — +$344k (prior session PnL) | Partially — entry condition (`sum_asks>$1`, taker/maker split) decoded; exact trigger ambiguous at sub-second | **NO** | Maker-arb censoring reversal: all sleeves net-negative post right-censored-residual correction | `TAKER_TRIGGER_DECODE_0xeebde7a0_2026_05_18.md`, `EEBDE7A0_TAKER_TRIGGER_V2/V3_2026_05_18.md`, `WALLET_HUNT_eebde7a0_2026_05_16.md` |
| **0xf3cfb6a6** | Relay / CTF Exchange merge-and-settle hub (receives ERC1155 from multiple maker wallets, merges pairs, redeems $1) | N/A (infrastructure wallet) | YES — role confirmed | **NO** — infrastructure only; not a standalone strategy | Aggregates inventory from B27 + eebde7a0 + others; ~50k transfers/73min; cannot replicate without being the merge agent | `RELAY_WALLET_DECODE_0xf3cfb6a6_2026_05_18.md` |
| **0x0fe40e88** (F1 cluster) | Non-up-down event trader (sports/elections/news Polymarket markets) | YES — +$531k lifetime / **$19k/day** (27.6d) | NO — decoder not built for non-up-down | **NO** | No signal decoder for sports/event markets; $230k withdrawn vs $3k deposited = consistent edge elsewhere | `WALLET_CATALOG_2026_05_17.md`, `WALLET_STRATEGIES_DECODED_2026_05_17.md` |
| **0x3e6bfd2f** | Non-up-down event trader (brand-new wallet, $29.9k bridge-in) | YES — +$58k / **$166k/day** (extrapolated from 0.35d) | NO | **NO** | Same non-up-down limitation; sample too small to validate rate | `WALLET_CATALOG_2026_05_17.md` |
| **0x7f599984** | Directional CLOB taker at mispricing (buy cheap side at `sum_asks>$1`, own_ask ~$0.36) | YES — +$44.6k / **$6.3k/day** (7d) | PARTIAL — entry condition reproducible; slug selector not | **NO** | Broad trigger loses −$14k on full universe; slug-selector not decoded from canonical data | `WALLET_CATALOG_2026_05_17.md`, `WALLET_STRATEGIES_DECODED_2026_05_17.md` |
| **0x89b5cdaa** (F1 cluster) | Binance-mirror directional + partial inventory flip (61% buy / 39% sell) | YES — +$42.7k / **$9.5k/day** (4.5d) | PARTIAL — binance momentum match ~56%; flip logic unclear | **NO** | Mixed strategy; not fully decoded; assumed execution+base-rate, not pure directional | `WALLET_CATALOG_2026_05_17.md`, `WALLET_STRATEGIES_DECODED_2026_05_17.md` |
| **0x9dae874a** (F2 cluster) | Directional CLOB taker — contrarian to 5s flow_imbalance, cheap-side buy (~$0.40), HOLD | YES — +$41.4k / **$5.9k/day** (7d) | PARTIAL — direction formula decoded; slug-selector NOT reproducible | **NO** | Trigger on broad universe: −$14k; slug-selector ~4% of slugs, signal not in canonical data | `F2_FINAL_VERDICT_2026_05_18.md`, `F2_TRIGGER_DECODE_2026_05_17.md`, `WALLET_STRATEGIES_DECODED_2026_05_17.md` |
| **0xa0a50783** (F2 cluster) | Same as 0x9dae874a (F2 directional) | YES — +$40.9k / **$5.8k/day** (7d) | PARTIAL — same as above | **NO** | Same F2 slug-selection problem | `F2_FINAL_VERDICT_2026_05_18.md` |
| **0xeefe46de** | Directional CLOB taker (96% buy, contrarian large-size, own_ask ~$0.42) | BARELY — +$191 / **$94/day** (2d) | PARTIAL | **NO** | Losing on partials; marginal edge evaporates at real fees | `WALLET_CATALOG_2026_05_17.md`, `WALLET_STRATEGIES_DECODED_2026_05_17.md` |
| **0xcfb103c3** | Attempted HFT CLOB scalper (copy of B27 — lower density, no relay-wallet exit) | NO — **−$40/day** (4.4d) | YES (mechanics decoded as counter-example) | **NO** — counter-example | 8 fires/slug vs B27's 53; no relay-wallet exit; larger fills → slippage; confirms execution speed is the moat | `WALLET_STRATEGIES_DECODED_2026_05_17.md` |
| **0xa6896d11** | Maker pair-arb (81.7% of slugs) + directional overlay (18.3%) — BTC 5m | YES — ~$12k/day velocity, $72.9k lifetime | PARTIAL — pair_sum 0.997, arb mechanics confirmed | **NO** | Pair-arb line CLOSED (censoring reversal + no-chase test failed); directional residual not decoded | `DECODE_bigbtc5m_2026_05_29.md`, `WALLET_HUNT_SYNTHESIS_2026_05_29.md` |
| **0x951bd740** | Maker pair-arb + directional overlay — BTC 5m (F2 cluster) | YES — $42.6k lifetime | PARTIAL — paired component decoded | **NO** | Same as above | `DECODE_bigbtc5m_2026_05_29.md` |
| **0x606345ea** | HF maker pair-arb — ETH 15m (1,528 MERGE events, +$1,191/day risk-free on paired leg) | YES — +$1,191/day on paired leg | YES — pair_sum 0.910, slot-open maker pattern confirmed | **NO** | Own pair-arb attempt: net-negative; wallet's edge is queue priority + fill velocity we cannot match | `DECODE_highfreq_makers_2026_05_29.md`, `WALLET_HUNT_SYNTHESIS_2026_05_29.md` |
| **0xc387c2a4** | Maker pair-arb — BTC 5m (pair_sum 0.814, +$4.8k/3.76d) | YES — ~$1.3k/day on paired leg | YES — pair_sum extreme, confirmed genuine maker arb | **NO** | Same pair-arb closure; queue/latency moat | `DECODE_3c58_d9dea_twins_2026_05_29.md`, `WALLET_HUNT_SYNTHESIS_2026_05_29.md` |
| **0xfcdc071d** | Maker pair-arb — BTC 15m (2,313 MERGE, $7.8k maker rebate) | YES | YES — arb mechanics confirmed | **NO** | Pair-arb line closed | `DECODE_multicell_trio_2026_05_29.md` |
| **0x251c1a28** (F1 cluster) | Maker pair-arb — BTC 5m (TWAP $20 ladder, 95.6% paired) | YES | YES | **NO** | Pair-arb closed | `DECODE_251c_c387_btc5m_2026_05_29.md` |
| **0x0de4458d** | Directional taker — cl_basis magnitude slug selector (Family B) | YES (high WR in window) | YES — slug selector is `|cl_basis_bps|` extremity, CONFIRMED reproducible | **NO (THIN)** | cl_basis gate-passer = ~2 fires/day, user passed on; efficient-market OOS test killed broader cl_basis deploy | `DECODE_0x0de4458d_2026_05_28.md`, `DECODE_SYNTHESIS_2026_05_28.md` |
| **0x22b0 / 0x46a8** (cheap contrarian class) | Momentum directional taker — buy cheap side (~$0.47) in direction of ret_30m/MACD | YES (78.9% / 77.4% momentum agreement, WR ~55-56%) | YES — momentum signal reproducible; entry_px filter decoded | **MARGINAL** — was a basis for Cyclops-clone work; WR marginal at real fees | Entry_px < 0.50 is poison-pill; deploy only in [0.55, 0.92] window | `DECODE_cheap_contrarian_class_2026_05_28.md`, `DECODE_SYNTHESIS_2026_05_28.md` |
| **0x6e1d5040** (Whale) | NegRisk low-probability market making — sells long-shot outcomes on composite multi-outcome markets; binary taker on the side | YES — +$592k/30d NegRisk leg alone | NO — NegRisk composite fill format not fully decoded; no infra | **NO** | Requires NegRisk maker infra, different product type (not up-down); not our pipeline | `WHALE_6e1d5040_DECODE_2026_05_29.md` |
| **0xf69af0b9** (Cyclops wallet) | Directional taker — follows Cyclops Telegram channel signals, BTC 5m only, ~1s latency | YES (channel WR ~64%) but wallet net **−$217 lifetime** | YES — signal source identified; latency confirmed | **NO** | 64% Chainlink WR does NOT overcome entry pricing + fees at low stakes; Cyclops strategy is marginal-to-negative | `CYCLOPS_WALLET_HUNT_2026_06_01.md`, `WALLET_FIND_F69AF0B9_2026_06_03.md` |
| **0x6011655c** (@HighTempTation) | Weather nowcast scalp — buy near-certain bucket (~$0.95), sell out after ~12min, 97% WR, +$2.7k/7d | YES — **+$7.8k lifetime**, scaling | YES — buy condition decoded (entry ~0.95, nowcast-driven) | **NO (MARGINAL)** | Edge is private fast weather forecast; by copy-time entry is often 0.97+; thin 3-5¢ margin + illiquid weather book; self-competing | `WALLET_6011655C_HIGHTEMPTATION_2026_06_03.md` |
| **0x331bf91c** | Weather hold-to-resolution — forecast edge, FADING (May flat) | YES historically — +$65k lifetime, but **declining** (May flat) | YES — strategy mechanics decoded | **NO** | Edge decaying; market efficiency catching up; forecast-driven so can't copy without same signal source | `WALLET_331BF91C_WEATHER_2026_06_03.md` |
| **0x8 decode-batch wallets** (0x0079c319, 0x07480f20, 0x10188828, 0x927f7694, 0x9f5ffe76, 0xc547326c, 0xe3867b68, 0x1day_class) | Various directional takers — EMA/return momentum (Family A) or cl_basis divergence (Family B); entry_px 0.55–0.92 | YES in-sample (WR 78–91% in [0.55,0.85] bucket) | YES — trigger class decoded (Family A = momentum, Family B = cl_basis); but OOS multivariate model fails to beat market price | **NO** | Efficient-market capstone: Polymarket price is near-optimal outcome estimator; no signal beats it OOS; profitable wallets' edge = execution quality + base-rate, not prediction | `DECODE_0x*_2026_05_28.md`, `DECODE_SYNTHESIS_2026_05_28.md` |
| **0x45fb42d0** | Late-slot taker + stale-ask sweep illusion ($5.5k of $8.1k from 7 stale-price trades on May 26) | Apparent YES but illusion | NO — $5.5k from 7 anomalous fills at stale 0.01 price; NOT reproducible | **NO** | Edge = data anomaly / market-stale exploit (specific May 26 event); not systematic | `DECODE_highfreq_makers_2026_05_29.md`, `WALLET_HUNT_SYNTHESIS_2026_05_29.md` |
| **0x2f32a09d** | Late-slot directional taker | NO — net **−$77** | Partially decoded | **NO** | Net-negative; no edge | `DECODE_highfreq_makers_2026_05_29.md` |

---

## Net

**Wallets decoded (distinct wallets/clusters):** ~30 across all reports (9 original operator wallets + 20+ additional from batch hunts May 28–Jun 3).

**Profitable wallets (positive lifetime PnL):** ~22 of the ~30 decoded are net-positive.

**Wallets with REPRODUCIBLE trigger edge (we could implement the signal):** ~8 have partially reproducible signals (momentum / cl_basis / pair_sum), but **zero** have a fully reproducible edge that survived backtest on the full OOS universe.

**Remaining unexploited decoded edges:**
- 0x0de4458d's `|cl_basis_bps|` slug selector is the only confirmed reproducible slug filter; yields ~2 fires/day — too thin, user passed.
- Cheap-momentum class (0x22b0/0x46a8) entry logic is reproducible and contributed to Cyclops S7 design; partially exploited via Cyclops composite.
- Weather nowcast scalp (0x6011655c) pattern is understood but requires proprietary weather feed.

**Where profitable wallets' edge actually comes from:**

1. **Execution (primary):** Sub-second maker queue priority → captures guaranteed spread on both-sided fills at slot-open (B27/0x606345ea/0xa6896d11). This is the dominant source of durable alpha — NOT prediction. We cannot replicate without matching fill latency + relay-wallet settlement infrastructure.

2. **Private slug-selection (secondary):** F2 cluster selects ~4% of slugs where contrarian fade pays; that filter is not visible in canonical L25 + binance data. We cannot reverse-engineer it without Polymarket CLOB WS event tape + cross-exchange basis.

3. **Product expertise (tertiary):** NegRisk whale (0x6e1d5040) and weather scalpers (0x331/0x6011) exploit product-specific mispricing in markets outside our decoder scope.

**Biggest lesson:** The Polymarket up-down price is a near-optimal outcome estimator (proven OOS, n=2038). All apparent directional edges from wallet mimicry are either execution advantages (speed/queue), base-rate biases in entry_px, or survivorship/censoring artifacts. The only reproducible prediction signal (cl_basis extreme) is too thin (~2/day) to deploy viably.

---

## Report References (key files)

- `strategy_lab/reports/WALLET_CATALOG_2026_05_17.md`
- `strategy_lab/reports/WALLET_STRATEGIES_DECODED_2026_05_17.md`
- `strategy_lab/reports/F2_FINAL_VERDICT_2026_05_18.md`
- `strategy_lab/reports/DECODE_SYNTHESIS_2026_05_28.md`
- `strategy_lab/reports/WALLET_HUNT_SYNTHESIS_2026_05_29.md`
- `strategy_lab/reports/DECODE_highfreq_makers_2026_05_29.md`
- `strategy_lab/reports/DECODE_bigbtc5m_2026_05_29.md`
- `strategy_lab/reports/CYCLOPS_WALLET_HUNT_2026_06_01.md`
- `strategy_lab/reports/WALLET_6011655C_HIGHTEMPTATION_2026_06_03.md`
- `strategy_lab/reports/WALLET_331BF91C_WEATHER_2026_06_03.md`
- `strategy_lab/reports/WHALE_6e1d5040_DECODE_2026_05_29.md`
- `strategy_lab/wallet_hunt/cache/_master_catalog.csv`
- `strategy_lab/wallet_hunt/cache/_directional_wallet_registry.csv`
