# PM-native trade-flow signals — 2026-05-26

**Author**: PM-flow agent
**Window**: 2026-04-30 → 2026-05-23 (23 days, post-restriction to PM trades availability)
**Data**: hybrid_fire_universe (5m + 15m) ∩ trades_polymarket parquet ∩ wallet_hunt caches
**Fee model**: LegacyConfig (2 % on profit, $25 notional)
**Causal**: all PM-trade reads filtered to `timestamp_us < fire_us`

---

## 1. Data availability

PM trades parquet **IS NOT stale** as CLAUDE.md says — refreshed coverage:

| Asset | Rows | Span |
|-------|------|------|
| BTC   | 35.6 M | 2026-04-26 12:46 .. 2026-05-25 19:16 |
| ETH   | 9.3 M  | 2026-04-26 13:51 .. 2026-05-25 19:20 |
| SOL   | 4.1 M  | 2026-04-26 18:07 .. 2026-05-25 19:20 |

Schema lacks taker/maker wallet — only `side` (buy/sell), `outcome` (Up/Down), `price`, `size`. Whale-detection requires joining `wallet_hunt/cache/{wallet}/trades_chain_enriched.parquet` (May 11–16 window only).

Hybrid fire universe in window: 5m=190,170 fires, 15m=50,712 fires, total **240,882 fires** with full PM flow features computed.

Wallet data CAVEAT — only 6 of 9 catalog wallets have on-chain trades parsed; F2 wallets (0xa0a50783, 0x9dae874a) only have alchemy_transfers, **so true F2 directional signal cannot be replicated from local data**.

## 2. Flow imbalance distribution

| Stat | Value |
|------|-------|
| Fires with ≥1 PM trade in 30s | 233,768 / 240,882 (97 %) |
| Median `pm_up_imbalance_30s` | ~0.00 |
| Pct ` > 0.3` (strong UP flow) | ~37 % |
| Pct ` < −0.3` (strong DN flow) | ~37 % |
| Mean `pm_trade_count_30s` | ~30 |
| Mean `pm_volume_total_30s` | $400 |

## 3. Standalone PM-rule results (LegacyConfig, $25 notional, full 23d window)

| Rule | n | WR | $/tr | sum_pnl |
|------|---:|----|-----:|--------:|
| PM-A follow 30s flow | 233,764 | 50.7 % | −$0.99 | −$231 k |
| PM-A_strong (|imb|>0.3) | 171,894 | 53.4 % | −$1.07 | −$184 k |
| PM-B fade 30s flow | 233,764 | 20.1 % | −$4.56 | −$1.07 M |
| PM-C follow whale majority | 15,952 | 27.2 % | −$3.66 | −$58 k |
| PM-D fade whale majority | 15,952 | 48.9 % | −$1.48 | −$24 k |
| PM-E vol-spike + strong flow | 15,722 | 50.8 % | −$0.87 | −$14 k |
| PM-F book/flow divergence | 90,389 | 15.0 % | −$5.73 | −$518 k |
| PM-G mint-sell footprint | 3,847 | 46.1 % | −$1.67 | −$6 k |

**Naive blanket use of any single PM-flow rule LOSES.** The information IS there but lives in specific (asset, tf, offset) cells. Top-segment performance (n≥50) is much stronger:

| Segment | Rule | n | WR | $/tr | sum_pnl |
|---------|------|---:|----|-----:|--------:|
| BTC 5m off=120 | PM-A_strong | 3,837 | 72.7 % | +$0.36 | +$1,380 |
| BTC 15m off=240 | PM-A | 2,100 | 61.0 % | +$0.56 | +$1,178 |
| ETH 5m off=210 | PM-A_strong | 4,962 | 69.1 % | +$0.23 | +$1,144 |
| ETH 15m off=60 | PM-F | 711 | 40.5 % | +$1.04 | +$741 |
| ETH 5m off=180 | PM-G | 101 | 57.4 % | +$6.33 | +$639 |
| ETH 5m off=180 | PM-A_strong | 4,685 | 67.2 % | +$0.13 | +$612 |
| ETH 5m off=180 | PM-D | 231 | 56.7 % | +$2.38 | +$549 |
| ETH 5m off=150 | PM-G | 101 | 58.4 % | +$5.34 | +$540 |

PM-A_strong dominates the top — **following strong 30s flow imbalance is mildly +EV in BTC/ETH 5m and 15m at specific offsets**.

## 4. Gate overlay results on top 7 hybrid sleeves

The 7 deployable hybrid V5/V6/V7 sleeves all bet DOWN (mostly) on 5m fires. Gates applied to each, n_pass≥30:

| Gate | Sleeve combos | Mean lift / tr | Median lift | Mean pass-rate | Total ∑pnl |
|------|--------------:|--------------:|------------:|---------------:|-----------:|
| **g_flow_with_and_no_whale** | 7 | **+$0.56** | +$0.81 | 41 % | +$2,338 |
| **g_flow_with** | 7 | **+$0.41** | +$0.81 | 45 % | +$2,548 |
| g_pm_no_whale | 7 | −$0.23 | $0.00 | 91 % | +$3,560 |
| g_flow_against | 7 | −$0.40 | −$0.62 | 55 % | +$1,922 |
| g_flow_strong_against | 7 | −$1.01 | −$0.25 | 34 % | +$820 |
| g_flow_strong_with | 7 | −$1.03 | −$0.50 | 28 % | +$930 |

**Counter-intuitive but stable: gating top hybrid sleeves on `g_flow_with` (PM trade flow agrees with the V7/V5/V6 direction) lifts $/tr by +$0.41–0.56 on average.** Best per-combo:

| Combo | Baseline $/tr (WR) | With gate $/tr (WR) | n_pass | Lift |
|-------|-------------------:|-------------------:|-------:|-----:|
| BTC 5m off=90 V7 Down × `g_flow_with_and_no_whale` | $2.70 (70.8 %) | **$6.62 (77.3 %)** | 119 | +$3.92 |
| BTC 5m off=90 V7 Down × `g_flow_strong_with` | $2.70 (70.8 %) | **$5.45 (79.3 %)** | 87 | +$2.76 |
| BTC 5m off=90 V7 Down × `g_flow_with` | $2.70 (70.8 %) | **$5.29 (75.8 %)** | 161 | +$2.60 |
| BTC 5m off=150 V7 Down × `g_flow_with` | $3.04 (66.7 %) | **$5.09 (71.6 %)** | 141 | +$2.05 |
| BTC 5m off=60 V7 Down × `g_flow_against` | $2.19 (68.7 %) | **$3.75 (73.7 %)** | 179 | +$1.56 |

**`g_pm_no_whale` provides effectively zero lift** (whale activity is too rare in 5m fires to matter as a filter). The action is entirely in **PM trade-flow direction alignment**.

## 5. Wallet catalog directional accuracy (sanity check vs prior decode)

| Wallet | Strategy class | n slugs | WR (BUY=bullish bet) | Note |
|--------|----------------|--------:|---------------------:|------|
| 0xb27bc932 (F1 scalper) | HFT maker | 908 | 18.0 % | Maker — “buys” are inventory acquired by selling to retail. Looks anti-correlated by design. |
| 0x04b6d7e9 (M&S) | Mint-and-sell | 98 | 24.5 % | Maker |
| 0xce25e214 (M&S) | Mint-and-sell | 300 | 50.0 % | Maker, neutral by construction |
| 0xeebde7a0 (M&S) | Mint-and-sell | 218 | 33.0 % | Maker |
| 0x89b5cdaa | Mixed taker/seller | 1,403 | 34.9 % | Mixed |
| 0xcfb103c3 | Directional taker | 175 | 28.6 % | Taker |

The low WRs are **expected for maker-side wallets** — the metric we computed (treat BUY of token = bullish bet) is wrong sign for inventory acquisition. The decoded behavior is confirmed: **catalogued whales are mostly contrarian-shaped (maker-side), which is why PM-D (fade whales) beats PM-C (follow whales) by +$2.17/tr in standalone test**.

## 6. F2-style 5s flow-fade replication

5s PM-trade imbalance computed for all fires. F2-style "bet OPPOSITE recent 5s flow" rule:

| Rule | n | WR | $/tr | sum_pnl |
|------|---:|----|-----:|--------:|
| dir_f2_fade (any) | 90,000 + | ~30 % | −$1.5 | −$120 k |
| dir_f2_fade_strong (|imb_5s|>0.5) | 50,000 + | ~32 % | −$1.4 | −$80 k |

**F2-style fade does NOT replicate as a standalone rule on the broader 23d window using PM-trade flow as a proxy.** Best segment was ETH 15m off=120 (+$372 / +$0.23 / tr, n=1,586) but this is marginal. Consistent with the verdict report: F2’s edge is in slug-SELECTION (which 15m markets to engage), not direction-from-flow. We do not have the cross-exchange basis / slug-selector data locally so cannot reproduce the 86 % WR config.

## 7. Top NEW PM-native sleeves (highest IS sum_pnl, all pass IS filtering)

Ranked by IS sum_pnl; all use Legacy fees, $25 notional:

| # | Sleeve | IS_n | IS_$/tr | IS_WR | IS_sum_pnl |
|--|--------|-----:|--------:|------:|-----------:|
| 1 | pmA_strong BTC 5m off=120 | 3,372 | $0.41 | 72.9 % | +$1,389 |
| 2 | pmA_strong ETH 5m off=210 | 4,331 | $0.31 | 69.0 % | +$1,332 |
| 3 | pmA_strong BTC 15m off=480 | 1,374 | $0.59 | 76.1 % | +$805 |
| 4 | pmA_strong ETH 5m off=180 | 4,063 | $0.18 | 66.6 % | +$736 |
| 5 | **BTC 5m off=90 V7 Down × g_flow_strong_with** | 279 | $2.50 | 71.0 % | +$696 |
| 6 | BTC 5m off=60 V7 Down × g_flow_against | 159 | $4.36 | 75.5 % | +$694 |
| 7 | **BTC 5m off=90 V7 Down × g_flow_with_and_no_whale** | 139 | $4.35 | 74.1 % | +$605 |

## 8. Walk-forward IS=20d (Apr 30 → May 20) / OOS=last 3d (May 20 → May 23)

(Note: window was 23d, so the “8d OOS” spec was unattainable — OOS window is ~3d.)

| Combo | IS_$/tr | OOS_$/tr | OOS_n | OOS_WR | OOS_∑pnl |
|-------|--------:|---------:|------:|-------:|---------:|
| **BTC 5m off=90 V7 Down × g_flow_with_and_no_whale** | $4.35 | **$11.25** | 22 | 86.4 % | +$248 |
| **BTC 5m off=150 V7 Down × g_flow_with_and_no_whale** | $3.66 | **$10.64** | 29 | 69.0 % | +$309 |
| BTC 5m off=90 V7 Down × g_flow_with | $4.35 | $11.25 | 22 | 86.4 % | +$248 |
| BTC 5m off=150 V7 Down × g_flow_with | $3.66 | $10.64 | 29 | 69.0 % | +$309 |
| BTC 5m off=90 V7 Down × g_flow_strong_with | $2.50 | $3.76 | 53 | 69.8 % | +$199 |
| pmA_strong BTC 15m off=240 | $0.39 | $1.17 | 164 | 66.5 % | +$191 |
| SOL 5m off=120 V7 Up × g_flow_against | $4.49 | $4.58 | 10 | 60.0 % | +$46 |
| pmA_strong BTC 5m off=120 | $0.41 | −$0.02 | 465 | 71.4 % | −$9 |
| pmA_strong ETH 5m off=180 | $0.18 | −$0.20 | 622 | 71.1 % | −$124 |
| pmA_strong ETH 5m off=210 | $0.31 | −$0.30 | 631 | 69.7 % | −$188 |
| BTC 5m off=60 V7 Down × g_flow_against | $4.36 | −$1.11 | 20 | 60.0 % | −$22 |
| pmA_strong BTC 15m off=480 | $0.59 | −$1.77 | 192 | 71.4 % | −$340 |

**Walk-forward pass rate: 7 / 12 combos have positive OOS sum_pnl.** Standalone PM-A_strong sleeves mostly DIE OOS (4 of 5 negative). The robust survivors are the **gate-overlays on the already-deployable hybrid V7 momo sleeves**.

## 9. Caveats

1. OOS window is only ~3 days (May 20–23), not 8 days. Confidence-intervals are wide. Re-test once 2 more weeks accumulate.
2. PM-trade parquet has no taker wallet — whale detection only on the 6 wallets whose chain trades we parsed (and those span only May 11–16). Whale-coverage of fires is ~5 % at best.
3. The two F2 wallets (a0a / 9da) have NO trades_chain data, only alchemy_transfers, so we cannot replicate F2 directional behavior from our own data.
4. PM-G “mint-and-sell footprint → fade inventory” shows up in single segments at high $/tr but n is tiny (≤101). Treat as noise until reproduced on more windows.
5. Top hybrid V7 sleeves already incorporate Polymarket book features; the lift from PM-flow gate may be partially overlapping signal (haven’t orthogonalised yet).
6. Coinbase, OKX, Kraken klines exist in canonical but we tested binance-only momo here. Could orthogonalise with cross-exchange flow next.

## Final recommendation

Add **`g_flow_with_and_no_whale`** as a tightening filter to the existing top BTC 5m off=90 / off=150 V7 Down sleeves. Expected uplift: $/tr roughly 2.4 × baseline. OOS supports persistence at n=22–29 over 3 days. Other PM-native rules are useful as features inside a composite ML model but not as standalone deployables.

---

**Files:**
- Features: `strategy_lab/pm_trade_flow_2026_05_26/pm_flow_features_5m.parquet`, `pm_flow_features_15m.parquet`, `pm_imbalance_5s.parquet`
- Whale activity: `whale_activity_5m.parquet`, `whale_activity_15m.parquet`
- Rule results: `standalone_rule_overall.csv`, `standalone_rule_by_segment.csv`
- Gate overlays: `gate_overlay_results.csv`, `gate_overlay_aggregate.csv`
- F2 replication: `f2_replication_dir_f2_fade.csv`, `f2_replication_dir_f2_fade_strong.csv`
- Wallet accuracy: `wallet_accuracy.csv`
- Walk-forward: `walkforward_results.csv`
- Master enriched: `fires_with_pm_features.parquet` (240k rows)
- Pipeline: `01_build_pm_flow_features.py`, `01b_build_pm_flow_15m.py`, `02_build_whale_activity.py`, `03_backtest_rules.py`, `04_gate_overlay.py`, `05_wallet_accuracy.py`, `06_f2_replication.py`, `07_walk_forward.py`
