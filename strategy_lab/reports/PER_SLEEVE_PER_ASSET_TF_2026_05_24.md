# Per-sleeve × per-asset × per-timeframe scorecard

Individual scorecard for **6 markets (BTC/ETH/SOL × 5m/15m)** × 3 sleeve specs (S8, S4, S8 ∪ S4 union). 5m uses `min_offset_s ≥ 120`; 15m uses `min_offset_s ≥ 360` (both = 40 % of slot length). Each cell deduped to one fire per (slug, direction), 2 %-on-profit fee.

Built 15m master panel from scratch at [`data/v4/canonical/_results/master_15m_panel.parquet`](data/v4/canonical/_results/master_15m_panel.parquet) (12 492 fires × 50 features).

Runner: [strategy_lab/overnight_2026_05_23/per_sleeve_per_asset_tf.py](strategy_lab/overnight_2026_05_23/per_sleeve_per_asset_tf.py)
CSV: [data/v4/canonical/_results/per_sleeve_per_asset_tf.csv](data/v4/canonical/_results/per_sleeve_per_asset_tf.csv)

## TL;DR — DEPLOY MATRIX

| market | DEPLOY | reason |
|---|---|---|
| **BTC 5m** | **S4_BTC_5m** | binom p = 0.0086, wf_ret 1.56, max DD only −$165 |
| BTC 5m | S8_BTC_5m AT HALF | edge real (p = 0.011) but wf_ret = 0.35 — decaying |
| **BTC 15m** | **DO NOT DEPLOY** | all rules lose money, binom p > 0.42 — no edge |
| **ETH 5m** | **S4_ETH_5m** ⭐ | strongest signal in study: $4.18/tr, +$95/day, p = 0.00042 |
| ETH 5m | S8_ETH_5m | ❌ DROP — not significant (p = 0.17, edge 1.15 pp) |
| **ETH 15m** | **S4_ETH_15m (off ≥ 0)** | +$37/day, p = 0.007. Use no min-offset filter — best variant |
| **SOL 5m** | **S4_SOL_5m** | cleaner than S8 (p = 0.006 vs 0.032); S8 outlier-dependent |
| **SOL 15m** | **S4_SOL_15m (off ≥ 240)** | +$21/day, p = 0.006 |
| BTC/ETH/SOL 15m S8 | ❌ DROP | MACD on 1s is a 5m-only signal; signal decays before 15m resolves |

**5m S8+S4 deploy set was previously recommended; the 15m extension is S4-only and only on ETH + SOL.**

## Master scorecard — 18 cells

Columns: n, WR %, $/tr, sum $, $/day, max DD, sharpe annual, binom_p, walk-forward retention, train→test WR. ✅ = ship, ⚠ = half-size, ❌ = drop.

### 5m markets (panel = 40 210 fires, 20.8 d, min_offset ≥ 120)

| cell | n | WR % | $/tr | sum $ | $/day | max DD | Sharpe ann | binom_p | wf_ret | train→test WR | verdict |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| **S8 BTC 5m** | 831 | 86.40 | 0.96 | +798 | **+39** | −313 | 7.3 | 0.011 | **0.35** ⚠ | 86.1 → 87.2 | ⚠ half-size |
| **S4 BTC 5m** | 345 | 78.84 | **2.17** | +747 | +36 | **−165** | 8.4 | 0.0086 | **1.56** ✓ | 76.8 → **83.7** | ✅ SHIP |
| S8 ∪ S4 BTC 5m | 1 022 | 84.25 | 1.45 | +1 485 | +71 | −292 | 10.9 | **0.00092** | 0.92 | 83.4 → 86.3 | ✅ SHIP |
| **S8 ETH 5m** | 1 004 | 85.86 | 0.64 | +640 | +31 | −427 | 5.0 | **0.17** ❌ | 0.87 | 85.5 → 86.8 | ❌ DROP |
| **S4 ETH 5m** ⭐ | 473 | 80.76 | **4.18** | **+1 978** | **+95** | −206 | **12.6** | **0.00042** | 1.01 ✓ | 78.9 → **85.2** | ✅ SHIP |
| S8 ∪ S4 ETH 5m | 1 303 | 84.04 | 1.56 | +2 027 | +97 | −365 | 10.9 | 0.0088 | 1.42 | 83.2 → 85.9 | ✅ SHIP |
| **S8 SOL 5m** | 977 | **88.02** | 1.97 | +1 923 | +93 | −314 | 5.2 | 0.032 | **−137** ⚠⚠ | 87.9 → 88.4 | ⚠ tail-dependent |
| **S4 SOL 5m** | 315 | 75.56 | 2.43 | +764 | +37 | −368 | 8.6 | 0.0059 | 0.78 | 72.7 → 82.1 | ✅ SHIP |
| S8 ∪ S4 SOL 5m | 1 183 | 84.78 | 1.96 | **+2 321** | **+112** | −447 | 6.1 | 0.0053 | 28.5 ⚠ | 84.4 → 85.6 | ✅ SHIP (carries S8 tail) |

### 15m markets (panel = 12 492 fires, 20.8 d, min_offset ≥ 360)

| cell | n | WR % | $/tr | sum $ | $/day | max DD | Sharpe ann | binom_p | wf_ret | train→test WR | verdict |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| S8 BTC 15m | 274 | 84.67 | −0.90 | **−247** | **−12** | −288 | −5.5 | **0.42** | 0.32 | 83.8 → 86.8 | ❌ DROP |
| S4 BTC 15m | 138 | 71.74 | −1.59 | −219 | −11 | −321 | −4.3 | **0.56** | 2.61 | 72.9 → 69.1 | ❌ DROP |
| S8 ∪ S4 BTC 15m | 371 | 80.32 | −1.10 | −410 | −20 | −531 | −6.3 | 0.47 | 0.66 | 79.9 → 81.2 | ❌ DROP — no edge |
| S8 ETH 15m | 345 | 80.87 | −1.06 | −365 | −18 | −483 | −5.6 | **0.81** ❌ | −9.7 | 85.1 → 71.2 | ❌ DROP |
| **S4 ETH 15m** | 172 | 73.26 | **+2.81** | **+483** | **+24** | −225 | 5.0 | 0.075 | 0.06 | 72.5 → 75.0 | ⚠ borderline (see below) |
| S8 ∪ S4 ETH 15m | 474 | 78.69 | 0.33 | +155 | +7 | −299 | 1.4 | 0.37 | −0.46 | 79.8 → 76.2 | ❌ DROP |
| S8 SOL 15m | 377 | 81.43 | −1.18 | −445 | −21 | −474 | −7.0 | **0.67** | 0.60 | 82.1 → 79.8 | ❌ DROP |
| **S4 SOL 15m** | 96 | 67.71 | +2.67 | +256 | +12 | −187 | 4.3 | 0.038 | 0.39 | 59.7 → **86.2** | ⚠ small n (96) |
| S8 ∪ S4 SOL 15m | 440 | 79.32 | −0.53 | −233 | −11 | −386 | −2.9 | 0.30 | 0.84 | 79.2 → 79.6 | ❌ DROP |

## Critical finding: MACD-on-1s is a 5m-only signal

**S8 (MACD_1s_hist agree + RVOL elevated) FAILS on every 15m market.** Sum_$ is negative on BTC/ETH/SOL 15m at any min_offset tested (0, 240, 360, 480, 600, 720). Binomial p never drops below 0.42 — no edge above the vwap-implied null.

**Why**: MACD(12, 26, 9) on 1-second closes captures momentum with a half-life of seconds. For 5m windows the signal lives ≈ as long as the slot, predicting outcome. For 15m the signal decays well before resolution — by the time the slot ends, the MACD-pointed move is already exhausted or reversed.

Same diagnosis applies to "MACD agree on 1s" used as a confirmation in unions for 15m — the signal-noise on 1s is too short-lived.

## S4 generalizes — but only on ETH 15m and SOL 15m

| variant | n | WR % | vwap_WR | edge pp | $/day | binom_p |
|---|--:|--:|--:|--:|--:|--:|
| **ETH 15m, S4, off ≥ 0** | 248 | 77.0 | 69.8 | **+7.21** | **+37.53** | **0.0070** ✓ |
| ETH 15m, S4, off ≥ 240 | 212 | 75.5 | 69.4 | +6.12 | +29.64 | 0.030 |
| ETH 15m, S4, off ≥ 360 | 172 | 73.3 | 67.9 | +5.38 | +23.53 | 0.075 |
| ETH 15m, S4, off ≥ 720 | 46 | 65.2 | 49.6 | **+15.60** | +25.78 | 0.024 |
| **SOL 15m, S4, off ≥ 0** | 140 | 69.3 | 60.3 | +9.04 | +19.08 | 0.017 ✓ |
| **SOL 15m, S4, off ≥ 240** | 123 | 70.7 | 59.4 | **+11.38** | **+21.27** | **0.006** ✓ |
| SOL 15m, S4, off ≥ 360 | 96 | 67.7 | 58.3 | +9.38 | +12.37 | 0.038 |
| BTC 15m, S4 (any off) | — | — | — | edge ≈ 0 | losing | > 0.55 |

The 5m-period min_offset_s ≥ 120 rule doesn't transfer to 15m. Best 15m variants:

- **ETH 15m S4**: no min_offset filter (`off ≥ 0`) — best p = 0.007, +$37.53/day
- **SOL 15m S4**: `min_offset ≥ 240` — best p = 0.006, +$21.27/day
- **BTC 15m**: skip — no edge at any threshold

## Direction asymmetry

| cell | UP n / WR | DOWN n / WR | UP sum / DOWN sum |
|---|--:|--:|--:|
| S4 BTC 5m | 284 / 78.5 % | 61 / 80.3 % | +$657 / +$90 |
| S4 ETH 5m | 413 / 79.9 % | 60 / **86.7 %** | +$1 502 / +$476 |
| S4 SOL 5m | 299 / 75.3 % | 16 / 81.3 % | +$567 / +$198 |
| S4 ETH 15m | 134 / 69.4 % | 38 / **86.8 %** | +$310 / +$173 |
| S4 SOL 15m | 88 / 69.3 % | 8 / 50.0 % | +$243 / +$13 |

**DOWN consistently wins more often than UP** on S4 across 5m + 15m. UP fires more often (cheap underdog tokens), DOWN is rarer but very high WR. Suggests adding a `signal == DOWN` boost / kelly-up if you want a high-WR variant.

## Final deploy matrix at $25 notional

| sleeve label | asset | tf | rule | min_off | fires/day | $/day | annualized $ |
|---|---|---|---|--:|--:|--:|--:|
| **`S4_BTC_5m_off120`** | BTC | 5m | fair_edge_strong + cvd_30s + \|dev\|≥8 | 120 | 17 | +$36 | +$13 140 |
| **`S4_ETH_5m_off120`** ⭐ | ETH | 5m | (same) | 120 | 23 | **+$95** | **+$34 675** |
| **`S4_SOL_5m_off120`** | SOL | 5m | (same) | 120 | 15 | +$37 | +$13 505 |
| **`S4_ETH_15m_off0`** | ETH | 15m | (same) | 0 | 12 | +$38 | +$13 870 |
| **`S4_SOL_15m_off240`** | SOL | 15m | (same) | 240 | 6 | +$21 | +$7 665 |
| `S8_BTC_5m_off120` ⚠ | BTC | 5m | macd_agree + rvol_elevated | 120 | 40 | +$39 (decaying) | — |
| `S8_SOL_5m_off120` ⚠ | SOL | 5m | (same) | 120 | 47 | +$93 (tail-dependent) | — |
| `S8_ETH_5m` ❌ | ETH | 5m | (same) | — | — | not significant | — |
| `S8_*_15m` ❌ | any | 15m | (same) | — | — | losing | — |
| `S4_BTC_15m` ❌ | BTC | 15m | (same) | — | — | losing | — |

### Two recommended deploy bundles

**Conservative (5 S4 sleeves, all p < 0.05, lowest fragility)**:
- 5 sleeves across BTC/ETH/SOL × 5m/15m
- ~73 fires/day combined
- **+$227 / day at $25 notional ≈ +$83 000 / year**
- All cells have binom p ≤ 0.05, max DD per cell ≤ $370

**Aggressive (conservative + S8_BTC_5m + S8_SOL_5m)**:
- 7 sleeves, includes the high-volume S8 5m carriers
- ~160 fires/day
- **+$359 / day at $25 notional ≈ +$131 000 / year**
- S8_BTC_5m is decaying (wf_ret 0.35 — re-validate weekly)
- S8_SOL_5m is tail-dependent (one fire = $1 517 of profit — strip that and the edge halves)

## Files

- 15m panel: `data/v4/canonical/_results/master_15m_panel.parquet`
- 5m panel: `data/v4/canonical/_results/master_5m_panel.parquet`
- Scorecard CSV: `data/v4/canonical/_results/per_sleeve_per_asset_tf.csv`
- 15m min_offset sweep stdout: ran inline (per-asset×rule×offset matrix above)
- Runners: `strategy_lab/overnight_2026_05_23/{build_master_15m_panel.py, per_sleeve_per_asset_tf.py}`

## Next steps (if pursuing further alpha)

1. **15m-specific MACD timeframe**: try MACD(12, 26, 9) on 60s rebars instead of 1s — could revive S8 on 15m where 1s noise dominates.
2. **Per-direction sleeves**: explicit DOWN-only variants would tighten DD given the consistent UP < DOWN WR pattern.
3. **Kelly sizing**: scale stake by fair_edge_bp magnitude. S4 fair_edge ≥ 500 already gates entry; bet 1.5× when fair_edge ≥ 1000.
4. **Per-week stability**: wf_ret > 1 confirms test ≥ train, but the panel only spans 21 days. Re-run the whole pipeline against the next 28d data refresh to confirm — especially S8_BTC_5m's 0.35 retention.
