# Directional Up/Down WR Scan — 2026-05-28

Goal: find wallets (or specific market segments) trading BTC/ETH/SOL up-down
**directionally** with high win-rate. Profit size irrelevant — WR per
(asset × timeframe) is the target. A wallet 60% overall but 75% on btc-5m =
crack that one segment.

## Method
- Tool: `strategy_lab/wallet_hunt/segment_winrate.py`
- WR truth: data-api `/trades` returns the **exact canonical slug**
  (`btc-updown-5m-<slot_start_s>`) + `outcome`, so joins straight to
  `canonical/load_resolutions()` (37,039 resolved updown markets, Apr 24–May 27).
- Per slug: net_qty per outcome = Σbuy − Σsell. A slug counts as a **directional
  bet** only if net-long exactly ONE side (the other side ≤1 share). Paired /
  mint-and-sell / churn slugs excluded.
- Win = held side == resolution winner. PnL = net_qty·(1−px) if win else −net_qty·px.
- Candidate pool: **100 counterparties** that crossed our known directional
  wallets (`_lb_counterparties_scored.csv`) — guaranteed updown participants.
  (Global leaderboards useless: 1/249 were updown — all sports/political whales.)

## ⚠️ Critical confound: WR is meaningless without entry price
Raw WR ranks reward late/near-certain entry, not edge. Discard these despite high WR:
- `0xf22f6ba8` btc-5m: 100% WR but **avg entry $0.97** → carry/arb, ~$0.03/win. No alpha.
- `0x4b1c18f2` btc-5m: 91.2% WR, entry $0.91, **net −$1,391** → rare losses wipe it. Losing.
- `0xb9c1ed96` btc-5m: 80.3% WR, **net −$5,817** → size blows up on losses.

Real edge = high WR **above breakeven (=avg_px)** at non-expensive entry + positive EV.

## 🎯 Edge-ranked crack targets (WR≥65%, entry≤$0.72, +EV, n≥25)
Ranked by `(WR − avg_px)·√n` = WR margin over implied breakeven, sample-weighted.

| wallet | seg | n | WR | entry | WR−BE | $/bet | net$ | full address |
|---|---|---|---|---|---|---|---|---|
| 0x07480f20 | btc-5m | 816 | 75.6% | 0.674 | +8.2pp | +1.60 | +1303 | 0x07480f204434ad41b1705b9d1de5bbfc451092a1 |
| 0x0079c319 | btc-15m | 610 | 73.9% | 0.662 | +7.8pp | +1.66 | +1010 | 0x0079c31913ed195a00d17c23562e78d46a3154d8 |
| 0x0de4458d | btc-5m | 297 | 69.0% | 0.594 | +9.7pp | +1.74 | +516 | 0x0de4458d107bb01a375879e8061c979269203158 |
| 0x8ef6a1cc | btc-5m | 40 | 80.0% | 0.625 | +17.5pp | +8.58 | +343 | 0x8ef6a1cc3fb81a0e2c3eb405a09ce497a23563ee |
| 0x9f5ffe76 | eth-15m | 27 | 74.1% | 0.556 | +18.5pp | +6.73 | +182 | 0x9f5ffe76a818dce37c70f947998b52b70671a008 |
| 0xe3867b68 | eth-15m | 80 | 75.0% | 0.656 | +9.4pp | +0.73 | +58 | 0xe3867b68af6eb14e3d04e5e86325e53700a94d91 |
| 0xf6d2f340 | sol-5m | 68 | 75.0% | 0.655 | +9.5pp | +0.96 | +66 | 0xf6d2f340298aaa0107d180b73aa93069f80686e7 |
| 0x7e5d2991 | btc-15m | 53 | 75.5% | 0.651 | +10.4pp | +1.95 | +103 | 0x7e5d2991c2647de2348287e2f499329fc6a6c4c3 |
| 0x10188828 | sol-15m | 78 | 67.9% | 0.634 | +4.5pp | +1.49 | +116 | 0x101888282092fb5be3764b1c615200b2f14a23fe |
| 0xe3867b68 | btc-15m | 167 | 66.5% | 0.630 | +3.5pp | +0.75 | +126 | (same as above) |

Notes:
- **0x07480f20 / 0x0079c319** = best size+edge. Huge samples (816/610), consistent
  +EV, mid entry. Most robust — top decode priority.
- **0x8ef6a1cc / 0x9f5ffe76** = highest per-bet edge but small n (40/27). Promising,
  need more history to confirm.
- **0xe3867b68 / 0x10188828** = multi-segment winners (eth+btc / sol+eth) → may run
  one signal across assets. Worth profiling cross-segment.
- up_bias mostly ~0.4–0.5 → genuinely two-sided directional (not just perma-long Up).

## Outputs
- `cache/_segment_winrate_counterparties.csv` — all 42 wallets × 92 segments
- `cache/_segment_winrate.csv` — known-wallet validation run

## Next step — crack the top target
Decode `0x07480f20` (btc-5m, 816 bets @ 75.6%):
```
py -3 strategy_lab/wallet_hunt/fetch_chain.py --wallet 0x07480f204434ad41b1705b9d1de5bbfc451092a1
py -3 strategy_lab/wallet_hunt/decoder.py      --wallet 0x07480f204434ad41b1705b9d1de5bbfc451092a1
# then join each fire to L25 book + binance 1s klines + chainlink RTDS at fire_us
# (anchor ws_s = slot_start − window_s) to reverse the entry trigger.
```
