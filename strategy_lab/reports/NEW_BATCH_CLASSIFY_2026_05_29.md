# New Wallet Batch — Classification & Routing (2026-05-29)

13 user-supplied wallets classified via data-api activity archetype + lb-api profit.
Source: `strategy_lab/wallet_hunt/classify_batch_2026_05_29.py` →
`cache/_classify_batch_2026_05_29.csv`.

## Routing by archetype

### A) Directional takers — harness-decodable (single-outcome buys, 5m/15m updown)
| wallet | pseudo | updown% | n_slugs | entry px_med | lifetime | 30d | 7d | note |
|---|---|---|---|---|---|---|---|---|
| **0xee65685d** | 0x50f7 | 100% | 490 | **0.04** | **$142.8k** | $44.1k | −$5.9k | multi-asset (btc/eth/xrp/sol/doge/bnb), buys CHEAP longshots, 5m. ⭐ |
| **0xa70f7d26** | 67djk | 100% | 471 | 0.76 | $7.0k | $2.2k | −$4.6k | "promising"; buys FAVORITES, btc/eth/sol 5m+15m+long |

→ Decode with `trigger_decode_harness.py`. WR-per-segment from `segment_winrate.py` (running).
0xee65685d's **0.04 median entry** is unusual — a cheap-longshot directional taker, opposite of
the favorite-buyers; worth understanding what makes a 4¢ bet win.

### B) Maker / pair-arb — execution-edge family (the real alpha per our efficient-market finding)
| wallet | pseudo | archetype | paired% | lifetime | 30d | 7d | note |
|---|---|---|---|---|---|---|---|
| **0x74a2b82f** | PBot-3 | PURE_PAIR_ARB_MAKER | 94% | $50.6k | **+$28.3k** | **+$7.4k** | btc 5m/15m, consistently +ve ⭐ |
| 0x7399fe3e | pandagon | MIXED_PAIR_ARB | 54% | $11.6k | $3.4k | $0.8k | btc 5m |
| 0x47f606ca | 123azxc | MIXED_MAKER | 93% | $2.0k | $2.0k | $2.0k | btc 5m, both-sides |
| 0x07e87aec | — | MIXED_MAKER | 49% | $3.4k | $3.4k | $0.0k | btc 5m, both-sides |
| 0x8320b90d | vedaresearch.btc | MIXED_MAKER | 41% | $40.2k | $29.5k | $3.1k | btc, mixed 4h/long/5m, notional ~$20 |

→ These are mint-and-sell / pair-arb makers. Per `EFFICIENT_MARKET_FINDING_2026_05_28.md`,
reproducible edge lives in maker execution, not directional prediction. Route to the maker-arb
workstream (`CLAUDE.md §Mint-and-sell maker V2`, `poly_maker_*`). PBot-3 is the cleanest btc pair-arb.

### C) Long-dated pair-arb whales — huge profit, NOT the 5m/15m directional game
| wallet | pseudo | updown% | timeframe | lifetime | 30d | portfolio | note |
|---|---|---|---|---|---|---|---|
| **0x6e1d5040** | — | 7.6% | long | **$935k** | $321k | $1.22M | pair-arb maker, 166 merges, long-dated |
| **0x0fe40e88** | gobblewobble | 67.8% | long | $490k | $98k | $429k | known catalog wallet; long pair-arb |
| 0x4ee29e4e | IH2P | 0.7% | long | $236k | $3.0k | $46.8k | non-updown |
| 0xeee92f1c | ComTruise | 11.3% | long | $161k | −$6.1k | $39.3k | long both-sides maker |
| 0xa42f127d | 5f5a | 2.2% | long | $140k | $16.2k | $15.5k | long both-sides maker |
| 0xfdc072df | — | 100% | long | $38.4k | $8.0k | $10.0k | UNCLEAR: long updown, up-biased (70%), 71 rebates |

→ These earn on LONG-dated markets via pair-arb / merge (buy both legs sub-$1, collect $1 at
resolution; mint+merge). Strategy archetype is clear (pair-arb/merge) but deep-decode needs the
CHAIN decoder (`decoder.py` + `fetch_chain.py`, reads SPLIT/MERGE events), not the directional
5m/15m harness. Biggest $ but outside current directional infra.

## Decode results (harness, btc-5m)

**0xa70f7d26 (promising)** — MOMENTUM follower. Direction d: px_vs_strike +1.21,
cl_basis −0.99, ret_1m +0.75, ret_3m +0.64, px_vs_ema21 +0.63. Buys the favorite on
positive Binance momentum. Win/loss weakly separable by momentum quality (macd_hist
d=0.33, ema9_slope 0.30). Net +$983, WR 76.8% @ 0.744 → **edge only +2.4pp over
breakeven = priced-out momentum** (same family as 0x07480f20/0xe3867b68). Slug
selection weak. Verdict: real but thin, not novel.

**0x7399fe3e (pandagon)** — ⭐ CONTRARIAN / MEAN-REVERSION (the one different profile).
Win-vs-loss is INVERTED: wins have NEGATIVE ret_5m/ema9_slope/macd_hist (d≈−0.26),
losses positive → it WINS WHEN IT FADES the recent move. Enters cheap (0.607),
profits on reversion. Direction also cl_basis-driven (d=−0.81). +7.6pp edge, n=432,
+$582. Slug selection indiscriminate. This is the one signal in the batch that is
NOT momentum-follow — a short-horizon mean-reversion of the up-down price after an overshoot.

**0xee65685d** = longshot/lottery (buys 4¢–17¢ tails; lifetime +$142k via rare ~25× hits,
net −$4.5k in our 33d window). High-variance, not a clean reproducible directional signal.

**0x8320b90d** = late-near-resolved carry (94% WR @ 0.90 entry, big size) — no predictive edge.

## Next steps
1. **Blind gate-test the pandagon mean-reversion hypothesis** (fade ret_5m / buy the dipped
   cheap side) across the 6-market 33d scan with the full gate battery — the one profile that
   might survive where momentum/favorite/underdog/cheap_mom/flow all failed. NOTE: our
   capstone (multivariate OOS model can't beat price) predicts it likely won't, but it's the
   best remaining directional shot.
2. PBot-3 (0x74a2b82f) → maker-arb deep-dive (+$28.3k/30d, +$7.4k/7d consistent btc pair-arb) —
   the execution-edge family where reproducible profit actually lives.
3. Optional: chain-decode the long-dated whales (0x6e1d5040 **$935k**, 0x0fe40e88 $490k) via
   decoder.py + fetch_chain.py (reads SPLIT/MERGE) — biggest $, pair-arb, outside the 5m/15m harness.
