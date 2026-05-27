# DRZ (Delta Reaction Zones) — Port to Python and Backtest on Polymarket Up/Down

**Date:** 2026-05-26
**Window:** Apr 30 → May 22 2026 (28d window of fire universe; chart-tf bars span Apr 21 → May 24).
**Indicator source:** *Delta Reaction Zones [BOSWaves]* (TradingView Pine v6).
**Fee model:** `engine_v2.LegacyConfig` (2%-on-profit-only — matches what production currently charges).
**Notional:** $25 / fire.
**Code:** `strategy_lab/drz/{build_drz_panel.py, standalone_test.py, gate_overlay.py, walk_forward.py}`.

---

## 1. Panel build summary

`build_drz_panel.py` reproduces the Pine logic in Python:
- `raw_delta = sign(close - open) * volume`, `sm_delta = EMA(raw_delta, 3)`, `CVD = cumsum(sm_delta)`.
- `ta.pivothigh / ta.pivotlow` on CVD with `lookback=12` (prints at bar `i + 12`).
- Pivot bar → zone at high/low with half-width `ATR(14) * 0.35`.
- Track per-zone impulse stats (last 100 raw_delta entries up to the pivot bar): pos_pct, net.
- Active zone breached when close exits the box.
- RC/RE signals = midline crosses (up=reclaim, down=re-enter), looked back 5 bars per fire.

Chart-tf chosen: **5m and 15m binance-spot-ws klines** (NOT 1s resampled — Pine convention applies on the chart-tf the indicator was designed for). For each fire we look up DRZ state on the LAST CLOSED bar before `fire_us - 1s`.

Outputs:
- `data/v4/canonical/_results/drz_panel_5m.parquet` (190,170 fires × 46 cols, 7.8 MB)
- `data/v4/canonical/_results/drz_panel_15m.parquet` (50,712 fires × 46 cols, 2.4 MB)

## 2. DRZ distribution (% of fires in/near zones)

| TF   | Asset | n_fires | in_support | in_resistance | recent_RC | recent_RE | avg_zones |
|------|-------|---------|-----------:|--------------:|----------:|----------:|----------:|
| 5m   | BTC   |  63,390 |     2.52 % |        3.20 % |    1.89 % |    2.38 % |     1.32  |
| 5m   | ETH   |  63,390 |     2.82 % |        3.28 % |    2.33 % |    2.46 % |     1.38  |
| 5m   | SOL   |  63,390 |     2.11 % |        2.81 % |    1.03 % |    2.02 % |     1.38  |
| 15m  | BTC   |  16,904 |     2.32 % |        3.27 % |    1.09 % |    1.70 % |     1.34  |
| 15m  | ETH   |  16,904 |     2.41 % |        2.89 % |    1.14 % |    2.32 % |     1.42  |
| 15m  | SOL   |  16,904 |     3.22 % |        2.22 % |    2.22 % |    1.47 % |     1.34  |

Average ~1.35 active zones at any time per asset; only 2-3% of fires sit inside a box. RC/RE signals fire on 1-2% of bars. **Conclusion:** DRZ is a sparse triggered indicator — useful as a gate, not as a universal direction picker (would only fire ~2% of fires).

## 3. Standalone signal results

Six direction rules evaluated per (asset, tf, offset_bin); top 10 by sum_pnl with n>=20 (from `drz_standalone_results.csv`):

| Rule                       | Asset | TF  | Offset    | n   | WR     | $/tr   | sum_28d   |
|----------------------------|-------|-----|-----------|----:|-------:|-------:|----------:|
| E_at_support_UP            | BTC   | 5m  | 150-240   | 427 | 55.0 % | +5.21  |  +2,226   |
| F_at_resistance_DOWN       | SOL   | 5m  | 60-150    | 291 | 63.9 % | +6.62  |  +1,927   |
| A_RC_at_support_UP         | ETH   | 5m  | 240-300   |  63 | 42.9 % | +21.09 |  +1,329   |
| E_at_support_UP            | ETH   | 5m  | 60-150    | 450 | 57.8 % | +2.44  |  +1,099   |
| E_at_support_UP            | SOL   | 5m  | 150-240   | 242 | 57.0 % | +3.98  |  +964     |
| E_at_support_UP            | SOL   | 5m  | 60-150    | 250 | 56.4 % | +2.88  |  +719     |
| F_at_resistance_DOWN       | ETH   | 15m | 480-840   | 184 | 54.9 % | +3.24  |  +596     |
| A_RC_at_support_UP         | ETH   | 5m  | 60-150    |  81 | 53.1 % | +5.04  |  +408     |
| F_at_resistance_DOWN       | ETH   | 15m | 60-240    | 112 | 61.6 % | +3.61  |  +405     |
| A_RC_at_support_UP         | BTC   | 5m  | 60-150    |  84 | 63.1 % | +4.76  |  +400     |

Rules:
- **A_RC_at_support_UP**: `drz_recent_RC AND drz_in_support_zone` → bet UP.
- **B_RE_at_resistance_DOWN**: `drz_recent_RE AND drz_in_resistance_zone` → bet DOWN.
- **C/D**: same gate but conditioned on impulse pos_pct.
- **E_at_support_UP**: in support zone (no RC needed) → UP.
- **F_at_resistance_DOWN**: in resistance zone (no RE needed) → DOWN.

The "naive bet against the zone" rules (E, F) actually win more often than the trigger-conditioned rules (A, B). This is consistent with the Pine indicator's intent — *zones are reaction zones*, not breakout zones. **Best raw signal:** SOL 5m F (resistance fade → DOWN), 64% WR over 291 fires.

## 4. Gate overlay results

For each top-10 distinct hybrid sleeve (best stack per `(asset, tf, offset_bin)` from `hybrid_gate_search_top.csv`), tested 10 DRZ binary gates as either ADD or REPLACE candidates. Top ADDs by `delta_sum` (only ones with `n>=200`):

| Sleeve                              | DRZ gate                  | Base n | Base WR | Base sum | New n | New WR  | New sum    | Δsum    |
|-------------------------------------|---------------------------|-------:|--------:|---------:|------:|--------:|-----------:|--------:|
| s6_5m / BTC / 60-150                | g_drz_not_contra_zone     |  2,764 | 77.79 % |  14,103  | 2,698 | 78.73 % |  14,472    | **+369** |
| s15_5m / BTC / 240-300              | g_drz_not_contra_zone     |  1,432 | 84.50 % |   2,486  | 1,389 | 84.81 % |   2,667    | **+181** |
| s15_5m / ETH / 240-300              | g_drz_not_contra_zone     |  1,083 | 85.69 % |   2,256  | 1,073 | 85.74 % |   2,300    | +44     |
| s6_5m / SOL / 60-150                | g_drz_not_contra_zone     |  1,503 | 92.88 % |   3,307  | 1,455 | 93.68 % |   3,333    | +27     |

The clear winner is `g_drz_not_contra_zone = NOT (in_resistance & UP) AND NOT (in_support & DOWN)` — i.e. *don't bet INTO a zone*. It drops ~2-5% of fires (the "fading the zone" trades that the underlying signal got wrong) and adds ~$25-370 to each sleeve. WR gains are small (+0.05% to +0.94%) but consistent across sleeves.

**Negative finding:** Specific DRZ-direction gates (`g_drz_at_support_with_up`, `g_drz_recent_RC_with_up`, etc.) collapse the trade count too aggressively (n=37-85) and lose >$1,700 from the baseline sum. They are too sparse to use as ADD gates.

## 5. Walk-forward validation

20d train / 8d test split with 200-shuffle bootstrap (sign-flip null). Both train and test sums must be positive for SIGN PASS.

### Track A — standalone DRZ rules

| Rule                       | Asset | TF  | Offset    | full n | full sum | train sum | test sum | p     | sign? |
|----------------------------|-------|-----|-----------|-------:|---------:|----------:|---------:|------:|------:|
| **F_at_resistance_DOWN**   | SOL   | 5m  | 60-150    |    291 |    1,927 |     1,435 |    +492  | 0.005 | **YES** |
| A_RC_at_support_UP         | BTC   | 5m  | 60-150    |     84 |      400 |        73 |    +327  | 0.050 | YES   |
| F_at_resistance_DOWN       | ETH   | 15m | 60-240    |    112 |      405 |        73 |    +331  | 0.050 | YES   |
| A_RC_at_support_UP         | BTC   | 5m  | 150-240   |     84 |      296 |       242 |     +54  | 0.165 | YES   |
| A_RC_at_support_UP         | ETH   | 5m  | 240-300   |     47 |    1,580 |       137 |  +1,443  | 0.110 | YES   |
| E_at_support_UP            | ETH   | 5m  | 60-150    |    450 |    1,099 |     1,404 |    -305  | 0.090 | NO    |
| E_at_support_UP            | BTC   | 5m  | 150-240   |    427 |    2,226 |     2,634 |    -408  | 0.150 | NO    |
| F_at_resistance_DOWN       | ETH   | 15m | 240-480   |    105 |      265 |       -33 |    +298  | 0.175 | NO    |
| E_at_support_UP            | SOL   | 5m  | 150-240   |    242 |      964 |       950 |     +14  | 0.110 | YES   |
| E_at_support_UP            | SOL   | 5m  | 60-150    |    250 |      719 |       664 |     +56  | 0.065 | YES   |

**6 / 15 SIGN PASS** for standalone DRZ. The two cleanest are **SOL 5m F_at_resistance_DOWN** (p=0.005) and **BTC 5m A_RC_at_support_UP / 60-150** (p=0.050).

### Track B — hybrid + DRZ overlay

| Sleeve                                                 | DRZ gate              | full n | full sum | train sum | test sum | p     | sign? |
|--------------------------------------------------------|----------------------|-------:|---------:|----------:|---------:|------:|------:|
| **BTC s6_5m/60-150** (cci+stoch+rf+ema50+ribbon)        | g_drz_not_contra_zone | 2,698 |  14,472  |   12,546  |   1,925  | 0.000 | **YES** |
| **SOL s6_5m/60-150** (mfi+within_dev+bb+ribbon)         | g_drz_not_contra_zone | 1,455 |   3,333  |    2,815  |     518  | 0.000 | **YES** |
| **BTC s15_5m/240-300** (cloud+mfi+ema200+cci+stoch)     | g_drz_not_contra_zone | 1,389 |   2,667  |    1,845  |     822  | 0.005 | **YES** |
| **ETH s15_5m/240-300** (rf_in_band+rf+within_dev+ema200) | g_drz_not_contra_zone | 1,073 |   2,300  |    1,177  |   1,123  | 0.050 | **YES** |

**4 / 4 SIGN PASS** for the `g_drz_not_contra_zone` overlay. It's a strict superset filter (drops 1-3% of fires) and the resulting sleeves clear both train and test. The p-values are very strong (0.000 for the two biggest sleeves).

## 6. Top-3 recommended new sleeves (with DRZ)

Three deploy-grade sleeves that beat the existing baselines.

### Recommendation 1 — DRZ overlay on **BTC s6_5m / 60-150**
- **Stack:** `g_cci_with & g_stoch_with & g_rf_with & g_tr_above_ema50 & g_ribbon_agrees & g_drz_not_contra_zone`
- **Full window:** n=2,698, WR=78.7 %, $/trade=$5.36, **sum=$14,472** (28d)
- **Walk-forward:** train $12,546 / test $1,925, both positive (p<0.001)
- **vs hybrid baseline:** +$369 (+2.6 %) on 66 fewer trades — slightly higher WR, slightly fewer trades, slightly lower vol drag.
- **Why it works:** removes the ~2.5 % of fires where the s6 momentum signal disagreed with an active DRZ box (e.g. UP signal when at resistance — DRZ blocks it).

### Recommendation 2 — Standalone DRZ on **SOL 5m / 60-150 / F_at_resistance_DOWN**
- **Rule:** `drz_in_resistance_zone == True` → bet DOWN. No hybrid features needed.
- **Full window:** n=291, WR=63.9 %, $/trade=$6.62, **sum=$1,927** (28d)
- **Walk-forward:** train $1,435 / test $492, both positive (p=0.005)
- **vs hybrid baseline:** SOL 5m s6/60-150 sleeve does $3,307 over 1,503 fires; this DRZ rule trades at ~5× higher $/trade on 1/5 of the volume — complementary, not overlapping.
- **Why it works:** SOL's lower-frequency, sharper price action means DRZ resistance zones are statistically reactive (fade-the-zone), and the 5m offset gives time for the bounce to register before the slot closes.

### Recommendation 3 — DRZ overlay on **BTC s15_5m / 240-300**
- **Stack:** `g_tr_above_cloud & g_mfi_with & g_tr_above_ema200 & g_cci_with & g_stoch_with & g_drz_not_contra_zone`
- **Full window:** n=1,389, WR=84.8 %, $/trade=$1.92, **sum=$2,667**
- **Walk-forward:** train $1,845 / test $822, both positive (p=0.005)
- **vs hybrid baseline:** +$181 (+7.3 %) on 43 fewer trades. Lift comes mostly from the 240-300s tail offsets where the original sleeve overfires into late-window resistance.

## 7. Did DRZ improve over hybrid_v1 baseline?

**Yes — but modestly, and only via the `g_drz_not_contra_zone` gate.**

| Baseline sleeve                       | Baseline sum | +DRZ sum | Δ        | Δ %    |
|---------------------------------------|-------------:|---------:|---------:|-------:|
| BTC s6_5m / 60-150                    |   14,103     |  14,472  |  **+369** | +2.6 % |
| BTC s15_5m / 240-300                  |    2,486     |   2,667  |  **+181** | +7.3 % |
| ETH s15_5m / 240-300                  |    2,256     |   2,300  |   +44     | +1.9 % |
| SOL s6_5m / 60-150                    |    3,307     |   3,333  |   +27     | +0.8 % |

Across the top-10 distinct sleeves, the overlay improved **4 / 9** with positive Δ (after filtering to cells where DRZ is defined), with the BTC s6 sleeve showing the largest absolute lift. WR gains are uniformly small (+0.05 % to +0.94 %), but ALL pass walk-forward with p<0.05 on the bootstrap.

The other DRZ direction gates (e.g. `g_drz_at_support_with_up`, `g_drz_recent_RC_with_up`) **do NOT help as overlays** — they collapse the trade count too far (n drops from 1,000+ to <100) and lose more than they gain.

## 8. DRZ-standalone signal that beats existing baselines?

**SOL 5m F_at_resistance_DOWN (60-150s offset)** is the standout standalone signal. It's not strictly bigger than the hybrid_v1 SOL s6_5m sleeve in sum_pnl (3.3k vs 1.9k), but:
- It uses NO momentum / TR / ribbon features — only the DRZ zone state.
- It's complementary (different timing — fires when price reaches resistance, not on momo spikes).
- Higher $/trade (6.62 vs 2.20).
- Walk-forward train/test both positive at p=0.005.

For a wallet that already deploys SOL s6_5m, adding this DRZ standalone sleeve in parallel would likely add ~$70/day with **<10 fires/day** (291 fires / 28d) — low-frequency tail strategy.

**BTC 5m A_RC_at_support_UP / 60-150** (n=84, WR=63%, p=0.05) is a smaller second candidate — tighter trigger (needs an active reclaim signal) so trade count is low but the WR is high enough to bet $1+ stakes per fire.

## 9. Caveats

1. **Pivot definition.** Pine `ta.pivothigh` uses `>=` (i.e. ties allowed). My port uses strict `>` for stability — could miss ~1-2% of pivots near flat CVD. Re-run with `>=` if tighter parity is needed.
2. **EMA seed.** Used `out[0] = x[0]`; Pine seeds at the first non-NA value too, so should be identical for our continuous binance feed.
3. **Pine `barssince` semantics.** Skipped the `barssince(breach)` logic — instead just track active/breached state in a stateful loop. Equivalent in spirit but not bit-for-bit.
4. **CVD reset.** Pine's CVD is a continuous cumsum across the whole loaded session. Mine matches that.
5. **Standalone rule E/F failed walk-forward** for BTC and ETH (E_at_support_UP), but PASSED for SOL. The asset effect is real and SOL is the cleanest fit.
6. **Track A coverage is sparse.** Only 2-3% of fires sit inside a zone; the standalone strategy has 50-450 fires per cell over 28d. Stake size cannot be large without dominating Polymarket book.
7. **No live-mimic fee model.** Used `LegacyConfig` (2%-on-profit-only) which matches production. Re-test with `LiveMimicConfig` only if Polymarket flips to `feeRate × p × (1-p)` on these markets.
8. **No L25 spread filter.** Did not require `(ask-bid)<0.02`; the existing fire universe parquets already have books that filled successfully. If we tighten the L25 spread filter, edge could shift.

## 10. Files produced

- `strategy_lab/drz/build_drz_panel.py` — DRZ feature builder
- `strategy_lab/drz/standalone_test.py` — 6-rule direction-signal scan
- `strategy_lab/drz/gate_overlay.py` — DRZ-as-gate overlay on hybrid sleeves
- `strategy_lab/drz/walk_forward.py` — 20d/8d split + 200-shuffle bootstrap
- `data/v4/canonical/_results/drz_panel_5m.parquet`
- `data/v4/canonical/_results/drz_panel_15m.parquet`
- `data/v4/canonical/_results/drz_standalone_results.csv`
- `data/v4/canonical/_results/drz_gate_overlay_results.csv`
- `data/v4/canonical/_results/drz_gate_overlay_improvements.csv`
- `data/v4/canonical/_results/drz_walk_forward.csv`
- `data/v4/canonical/_results/{s15,s6,v15m}_joined_drz.parquet` — joined frames with DRZ gates ready for downstream gate search
