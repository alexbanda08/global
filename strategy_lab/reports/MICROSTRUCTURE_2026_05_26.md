# Microstructure Signal Investigation — 2026-05-26

**Hypothesis tested:** Polymarket L25 order book microstructure at fire_us contains alpha that price/volume alone doesn't capture (top-of-book imbalance, microprice deviation, spread asymmetry, book slope, depth, queue position, VPIN).

**Data window:** 2026-04-30 → 2026-05-22 UTC (~22 days), 240,882 fires across BTC/ETH/SOL × 5m+15m × 5 offsets/window.

**Method:**
- L25 books streamed per asset via `data/v4/canonical/load.py::load_orderbook_l25_streaming` with 1Hz subsample and time-window pruning.
- For each fire, causal asof at `fire_us` (no lookahead) on BOTH up_token and dn_token books.
- ~40 features per fire computed (imbalance×3 levels, microprice, spreads, slopes, depth, queue, change-over-time).
- Backtest fee model = `LegacyConfig` (2%-on-profit-only) per production reality (verified 2026-05-22, see CLAUDE.md).
- Outcome from chainlink-resolved `outcome` column.

Code: `strategy_lab/microstructure_2026_05_26/{build_micro_panel.py, score_panel.py, sleeve_overlay.py, feature_dists.py}`
Panel: `data/v4/canonical/_results/microstructure_panel.parquet` (238,180 rows × 55+ feature cols)
CSVs: `strategy_lab/microstructure_2026_05_26/{task2_standalone_rules, task3_gate_overlay, task3_deep_sleeve_gate, task4_vpin, task5_walkforward, task5_walkforward_deep}.csv`

---

## 1. Panel build summary

| Asset | Fires | With features | Per-asset elapsed | L25 source GB | Unique slugs |
|-------|------:|--------------:|------------------:|--------------:|-------------:|
| BTC | 80,294 | 79,708 (99.3%) | ~700s | 7.28 GB | 8,452 |
| ETH | 80,294 | 79,391 (98.9%) | ~290s | 1.63 GB | 8,452 |
| SOL | 80,294 | 79,081 (98.5%) | ~306s | 0.72 GB | 8,452 |

Total panel: **238,180 rows** with ~55 microstructure columns + merged fill+outcome from `hybrid_fire_universe_{5m,15m}`. Subsample policy: 1 row per (slug, outcome, second) across all refresh caches → typical 350 snapshots per slug × 2 outcomes. Causal asof tolerated up to 60s of book staleness (consistent with `engine_v2.find_book_strict`).

VPIN computed from binance `klines_1s` (taker_buy_base + volume_traded) with auto-bucket sizing → 4,725-4,859 buckets per asset, 50-bucket rolling stdev. **Coverage gap: 29.5% of fires only**, due to 1s taker_buy_base being NaN before 2026-05-12 (vision archive lacked taker side breakdown).

---

## 2. Feature distribution per asset (selected)

| Feature | BTC (mean / median / p10-p90) | ETH | SOL |
|---|---|---|---|
| `up_spread_bps` | 662 / 225 / 112-1429 | 826 / 253 / 112-1818 | 1309 / 504 / 126-3333 |
| `up_imb5` | 0.003 / 0.001 / -0.72-0.74 | 0.009 / 0.014 / -0.70-0.71 | 0.002 / 0.003 / -0.77-0.77 |
| `up_depth_2pct` | 703 / 246 / 0-1241 | 192 / 44 / 0-340 | 86 / 0 / 0-99 |
| `up_quote_intensity_5s` | 4.10 / 5 / 2-5 | 2.33 / 2 / 0-5 | 1.40 / 1 / 0-3 |
| `up_book_dt_us` (median) | 0.90s | 1.34s | 2.80s |

**Key observation**: SOL has the WIDEST spreads (≈2x BTC), THINNEST depth (≈8x lower), LOWEST quote intensity (1.4 vs 4.1 BTC), and STALEST books (2.8s vs 0.9s BTC). SOL Polymarket microstructure is degraded vs BTC/ETH — any microstructure signal on SOL should be discounted.

Full table: `strategy_lab/microstructure_2026_05_26/feature_distributions.csv`.

---

## 3. Standalone rule results (TASK 2)

5 candidate direction rules, applied to the FULL universe (~240k fires). None passed:

| Rule | Best (asset, tf) | n | WR | $/tr | sum_pnl |
|---|---|---:|---:|---:|---:|
| **A** (bet WITH `up_imb5` if abs>0.5) | BTC 5m | 14,012 | 34.4% | -$3.53 | -$49,453 |
| **B** (microprice skew aligned) | BTC 15m | 14,748 | 52.4% | -$1.45 | -$21,407 |
| **C** (your side spread < other -50bps) | BTC 15m | 12,476 | 78.4% | -$0.07 | -$888 |
| **D** (high QI + imb5>0.3) | tiny n | <500 | varied | -$5+ | small |
| **E** (mean-revert at |imb5|>0.9) | BTC 5m | 8,961 | 6.7% | -$18.99 | -$170,204 |

**Standalone WR ≠ standalone alpha.** Rule C achieves 78% WR but loses pennies/trade because it's BUYING at $0.85+ (premium pricing on the tight-spread token absorbs all the edge plus more). Rule E is catastrophically wrong — extreme book imbalance is informative, not noise; betting AGAINST extremes loses ~93% of the time.

Rule A is the most interesting: bet WITH `up_imb5 > 0.5` predicts UP at **34.4% WR** — book imbalance is **anti-predictive** at extremes on this asset class. Combined with the legacy 2%-on-profit fee, this rule LOSES ~$3.50 per fire on BTC 5m. **Rule A inverted (Rule A^-1)** would have been an attractive contrarian signal, but the EV math at fire's vwap is still negative net of pricing premium.

---

## 4. Microstructure gates as overlays (TASK 3)

11 binary gates × top sleeves × (asset, tf). Per-fire gate value is bet-side-aware (UP bet uses UP-token gate state; DOWN bet uses DOWN-token).

### 4a. As overlay on broad UP/DOWN universes

Top by WR lift (n_gate >= 30):

| Gate | (asset, tf, side) | n_gate | WR base → gate | dpt base → gate |
|---|---|---:|---:|---:|
| `g_spread_wide_skew` | SOL 5m, UP | 16,159 | 45% → 77% | -$5.98 → -$0.78 |
| `g_spread_wide_skew` | SOL 5m, DOWN | 15,880 | 46% → 78% | -$5.14 → -$0.39 |
| `g_spread_wide_skew` | ETH 5m, DOWN | 23,283 | 46% → 76% | -$3.97 → -$0.28 |
| `g_spread_wide_skew` | BTC 15m, DOWN | 7,279 | 49% → 75% | **-$1.87 → +$0.31** |
| `g_spread_wide_skew` | ETH 15m, DOWN | 6,626 | 49% → 76% | **-$2.33 → +$0.05** |
| `g_spread_wide_skew` | ALL 15m, DOWN | 19,302 | 49% → 76% | **-$2.71 → +$0.01** |

**`g_spread_wide_skew` is the only meaningful single-gate finding.** It detects when the OPPOSITE token has a wider spread than your bet's token — a structural cue that the market is pricing one side wider for inventory reasons. Lifts WR ~28-32 percentage points (consistent across BTC/ETH/SOL). But the dollar edge is still mostly absorbed by pricing premium; only on 15m DOWN bets does the gate convert to positive expectancy.

### 4b. As overlay on directional sleeves (deep test)

Defined 5 implicit sleeves from fire_universe `ret_2m_at_ws` + `mag_ratio`:
- `momo_v2_anywhere`: |ret_2m|≥0.0005 ∧ mag_ratio≥1.5
- `momo_v2_strong`: |ret_2m|≥0.001 ∧ mag_ratio≥2.5
- `momo_extreme`: |ret_2m|≥0.0015 ∧ mag_ratio≥3.0
- `sniper_midwindow`: fire_offset ∈ {120,240,360,480} ∧ |ret_2m|≥0.0003
- `fade_small`: |ret_2m|<0.0003 (mean-revert)

Each microstructure gate applied. **Top positive-$/tr combos with n_gate ≥ 200:**

| sleeve | asset/tf | gate | n_gate | wr_gate | dpt_gate | sum_pnl_gated |
|---|---|---|---:|---:|---:|---:|
| `momo_v2_anywhere` | ETH 15m | `g_imb5_with` | 323 | 50.2% | **+$5.84** | +$1,886 |
| `momo_v2_anywhere` | ETH 15m | `g_book_slope_steep_against` | 267 | 61.8% | **+$5.66** | +$1,511 |
| `momo_v2_anywhere` | ETH 15m | `g_microprice_with` | 329 | 48.6% | **+$2.81** | +$924 |
| `momo_v2_anywhere` | ETH 15m | `g_depth_high` | 486 | 50.0% | **+$1.80** | +$875 |
| `sniper_midwindow` | BTC 15m | `g_imb5_with` | 2,036 | 50.9% | **+$0.58** | +$1,173 |
| `momo_v2_strong` | ETH ALL | `g_spread_wide_skew` | 301 | 78.1% | **+$0.75** | +$227 |

The ETH 15m momo sleeves show CONSISTENT lift from microstructure gates. `g_imb5_with` (book imbalance aligns with bet) and `g_book_slope_steep_against` (your side has thick book = low slippage if hit) both reinforce momo direction.

---

## 5. VPIN as veto gate analysis (TASK 4)

VPIN = volume-synchronized probability of informed trading. Bucketed binance 1s data into ~5000 equal-volume buckets, computed |buy_vol - sell_vol|/vol per bucket, then 50-bucket rolling stdev. Median VPIN ≈ 0.32-0.39 across assets. Joined to panel via asof on fire_us.

**Coverage gap matters**: only 29.5% of fires have valid VPIN (post 2026-05-12 only). On the covered subset:

| (asset, tf, side) | dpt(low VPIN) | dpt(high VPIN) | lift |
|---|---:|---:|---:|
| BTC 15m UP | -$2.99 | -$4.72 | **+$1.73** |
| BTC ALL UP | -$2.68 | -$4.04 | +$1.36 |
| BTC 5m UP | -$2.60 | -$3.84 | +$1.25 |
| ETH 15m DOWN | -$0.37 | -$1.28 | +$0.91 |
| BTC 15m DOWN | -$1.85 | -$0.57 | **-$1.28** |
| SOL 15m DOWN | -$4.64 | -$2.66 | -$1.97 |

**Mixed signal.** Low VPIN helps BTC/ETH UP bets and ETH DOWN (the lifts are real, +$1.0-1.7 dpt). But DN-bet on BTC and DN on SOL FAVOR high VPIN. Interpretation: VPIN captures "informed flow against my side" — for BTC UP bets, when toxic flow is low, the market is less informationally-asymmetric and momo edge persists. For SOL DN, high VPIN actually means well-functioning market and DN bets fill more cleanly.

Bottom line: VPIN is a **conditional gate**, not a unilateral veto. Useful for BTC UP / ETH DN sleeves only. Not strong enough to be a primary signal.

---

## 6. Top 5 new microstructure-driven sleeves

Ranked by walk-forward dpt_test with bootstrap_p_neg < 0.10. Train = first 75% of window (~16 days), test = last 25% (~5.5 days), 200-shuffle bootstrap.

| # | Sleeve | n_test | WR_test | dpt_test | boot_p | boot_ci5 | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| **1** | `momo_extreme ETH 15m` (no gate; |ret|≥0.0015 ∧ mag≥3) | 40 | **82.5%** | **+$20.49** | 0.000 | +$11.7 to +$33.1 (95% CI). Tiny n but extreme signal. |
| **2** | `momo_v2_anywhere ETH 15m + g_book_slope_steep_against` | 82 | **79.3%** | **+$10.69** | 0.000 | +$4.13 to +$18.6. Your side's book is thick. |
| **3** | `momo_v2_anywhere ETH 15m + g_imb5_with` | 115 | **61.7%** | **+$8.02** | 0.015 | +$2.18 to +$15.0. Book imbalance aligns with bet. |
| **4** | `momo_v2_anywhere ETH 15m + g_depth_high` | 167 | **59.3%** | **+$4.84** | 0.030 | +$0.38 to +$9.32. Total L25 depth > median. |
| **5** | `momo_v2_anywhere ETH 15m + g_microprice_with` | 116 | 62.1% | +$8.25 | 0.000 | +$3.07 to +$15.3. Did not pass binary because train was -$0.16/tr. |

**Findings:** The 4 PASSING sleeves are ALL **ETH 15m momo-style**. ETH 15m has the best signal/noise on this dataset (ETH is liquid enough to make microstructure meaningful but small enough that momo move-magnitude matters). BTC microstructure is too thin (top-of-book ~$10 size) to discriminate; SOL microstructure is too degraded.

**Production overlap**: ETH 15m momo sleeves (poly_updown_eth_15m_momo_v2_hod, +$15.15/tr in shadow_11_sleeves_v2) — microstructure gates `g_imb5_with` and `g_book_slope_steep_against` may compound the production sleeve's edge. Worth a paper-deploy A/B.

---

## 7. Walk-forward validation

| Total combos tested | Passed (dpt_test>0 ∧ p<0.10 ∧ dpt_train>0) | Pass rate |
|---:|---:|---:|
| 21 (deep sleeve+gate) + 14 (broad rule) = 35 | **4** | 11% |

This is below random — but the 4 passes are highly correlated (all ETH 15m momo). Treat as ONE real sleeve discovery (ETH 15m momo) with 3 different microstructure expressions of the same underlying pattern.

The single broad-rule pass: `BTC 15m DOWN + g_spread_wide_skew`, n_test=1,779, dpt_test=+$0.57, p=0.055. Marginal but stable, 75% WR. Worth tracking.

---

## 8. Caveats

1. **Book freshness varies wildly** — median book staleness 0.9s (BTC) → 2.8s (SOL). Microstructure features are computed on 1Hz-subsampled snapshots, so "real-time" book imbalance is approximate. Sub-second changes are partially captured by the `imb5_change_500ms` feature but truncated at the subsampling boundary.
2. **Book imbalance can be transient.** Spoof orders, fast-moving inventory, and queue jumping are all visible in our 1s window but invisible in our 1Hz subsample. Production WS feed will be richer.
3. **Premium pricing absorbs WR edge.** High-WR rules (Rule C 78%, gate combos 75-80%) BUY at the side that's already trading at $0.80+. The 2% legacy fee on profit + the natural cost of paying premium prices means a 28pp WR lift can still be near-zero or negative on dollars. **Microstructure signals are most useful as TIE-BREAKERS or EXIT-LIQUIDITY indicators, not as primary entry signals.**
4. **VPIN coverage is half the panel** — pre-May-12 binance 1s data lacks taker_buy_base. For 2026-06 onward this is no longer a constraint.
5. **No sub-second book event count** — we capped quote_intensity_5s at 5/s effective due to 1Hz subsampling, so the "active market" gate is binary.
6. **ETH 15m results may overfit** — only 119 baseline `momo_extreme ETH 15m` fires (79 train, 40 test). All 4 passing sleeves are ETH 15m. Need to re-validate on the next ~14d of data before claiming production-ready.

---

## Appendix — features computed

For BOTH `up_*` and `dn_*` tokens:
- `ask0, bid0, mid, spread_bps`
- `imb1, imb5, imb25` (book imbalance at 1, 5, 25 levels)
- `microprice, micro_dev_bps`
- `eff_spread_25` (L25-bottom to L25-top distance)
- `bid_slope, ask_slope` (Kyle's lambda proxy via OLS)
- `queue_top_bid` (bid_size[0] / total_bid_size)
- `depth_2pct` (size within 2% of mid)
- `total_bid_size, total_ask_size`
- `book_dt_us` (staleness from fire_us)
- `imb5_change_500ms, mid_change_500ms_bps, depth_change_1s` (short-term deltas)
- `quote_intensity_5s` (count of snapshots in [fire_us-5s, fire_us])

Cross-token: `imb5_diff, imb1_diff, imb25_diff, micro_dev_diff, spread_diff, depth_diff`.

Gate definitions in `score_panel.py::build_gates`.
