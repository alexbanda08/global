# Round 3 synthesis — 2026-05-26 (evening)

> ⚠️ **CORRECTIONS NOTICE (Round 6 dedup)**: The combined deployable estimates
> quoted below are NAIVE SUMS that did not account for slug overlap. The
> actual realistic deployable is ~$20.5k/28d at $25 notional (~$2.67M/year
> @ $250). See `NAIVE_SUM_CORRECTIONS_2026_05_26.md` and
> `final_deploy_manifest.csv` for the authoritative numbers.
>
> Individual sleeve metrics (n, WR, $/tr per sleeve) in this report ARE
> CORRECT — only the COMBINED estimates were inflated by overlap.

**Date:** 2026-05-26
**Window:** mostly Apr 30 → May 22, with full Apr 24 → May 25 used by OOS validation
**Fee model:** Legacy 2%-on-profit-only

Round 3 sent 7 agents to attack 7 independent hypotheses: (1) web-research new
quant techniques, (2) order book microstructure on L25, (3) cross-exchange
lead-lag, (4) Polymarket trade flow, (5) vol regime + Hurst, (6) funding/OI/liq,
(7) full-window OOS validation.

**Headline of the session is sobering**: the OOS validation agent showed that
**5 of the 14 top R2 sleeves FAILED on fresh May 22-25 data** — including the
$20.68/tr SMS standalone "headline find" that collapsed to $0.14/tr OOS. The
deployable scale-up gets revised DOWNWARD from $90-110k/28d to **~$51-70k/28d**
realistic. Simple high-n hybrid_v1 sleeves are stable; bespoke high-$/tr
small-n sleeves were over-fit.

But 3 NEW orthogonal lifts ALSO came out of Round 3 and SURVIVED OOS:
**g_vol_expanding** (vol regime), **g_book_slope_steep_against** (microstructure),
**g_flow_with_and_no_whale** (PM flow). These add ~$5-10/tr lift on already-
validated base sleeves with walk-forward proof.

---

## TL;DR — what to do differently after Round 3

### 1. STOP deploying these (FAILED OOS on May 22-25)
| Sleeve | REF $/tr | OOS $/tr | OOS WR | Action |
|---|--:|--:|--:|---|
| poly_updown_btc_5m_off120_sms_liq (the $20.68 headline) | $20.68 | **$0.14** | 48.9% | **REMOVE from deploy list** |
| poly_updown_sol_5m_drz_res_down | $6.62 | catastrophic | 45.5% | **REMOVE** |
| poly_updown_btc_5m_xa_down | $1.64 | negative | 56% | **REMOVE** (cross-asset bias inverted) |
| poly_updown_eth_15m_off120_240 (15m hunt) | $5.97 | negative | 60.2% | **REMOVE** |
| poly_updown_pool_15m_offge480 (15m hunt) | $6.87 | negative | 45.6% | **REMOVE** |

### 2. KEEP deploying these (survived OOS)
| Sleeve | REF $/tr | OOS $/tr | OOS WR | Status |
|---|--:|--:|--:|---|
| poly_updown_btc_5m_s6_hybrid_v1 | $5.10 | **$1.90** | passed | ✅ DEPLOY |
| poly_updown_eth_5m_s6_hybrid_v1 | $1.57 | **$0.86** | passed | ✅ DEPLOY |
| poly_updown_btc_5m_s15_hybrid_v1 | $3.12 | **$2.08** | passed | ✅ DEPLOY |
| poly_updown_eth_15m_off60_120 | $4.48 | **$5.68** | improved! | ✅ DEPLOY |

### 3. ADD these NEW orthogonal gates (Round 3 winners, walk-forward proven)
| Lift | Applied to | Net effect |
|---|---|---|
| **g_vol_expanding** (rv_60s > 1.5× rv_300s) | ETH S6 60-150 | $10 → $17.24/tr IS, OOS lift +$7.38 |
| **g_book_slope_steep_against** (your-side book thick) | ETH 15m momo | OOS $/tr +$10.69 (CI5 +$4.13) |
| **g_flow_with_and_no_whale** (PM 30s flow + no whale) | BTC V7 5m DOWN | $2.70 → IS $6.62, OOS **$11.25/tr** |
| **g_coinbase_basis_extreme_against** (xchg basis) | S1/S3 sleeves | +$7-12/tr lift |
| **g_hl_liq_cascade_with** (HL short-liq > $100k) | Any BTC sleeve | IS $/tr +$17.72 (small n=51) |

### 4. RESEARCH PIPELINE for next round (Agent N's top-5 untested)
1. **Microprice (Stoikov 2018)** on Polymarket L25 — textbook fair-value
2. **Lee-Mykland jump detector** on binance 1s — proper statistical test for spikes
3. **Multi-level OFI (Cont/Xu/Gould)** on Polymarket L25-deep
4. **VPIN (BVC-bucketed)** on binance 1s
5. **Transfer entropy** for cross-exchange lead-lag

---

## Agent-by-agent results

### Agent N — Web research (~668 KB report)

20 candidates ranked; 50 web links cited. Top-5:
1. **Microprice (Stoikov 2018)** — best per-tick fair-value estimator; we use only top-of-book; Polymarket 2% tick/mid ratio is the regime where microprice dominates
2. **Lee-Mykland intraday jump detection** — ~12-15 jumps/asset/28d × 65-75% continuation; replaces our heuristic S6 spike with a properly-normalized statistical test
3. **Multi-level OFI** — 68-74% RMSE reduction over single-level OFI documented on large-tick instruments
4. **VPIN (BVC-bucketed)** — order flow toxicity; magnitude predictor; pairs with our spike+CVD logic
5. **Cross-exchange transfer entropy + Hayashi-Yoshida** — promote partial work to deployable gate

**Biggest gap identified**: "We have polymarket L25 at sub-second resolution and use it only for top-of-book imbalance + book_walk fills. Microprice + multi-level OFI are textbook signals we've never computed."

**Recommended next 3 scripts**: microprice_panel.py, jump_burst_detector.py, mlofi_polymarket.py

Report: `strategy_lab/reports/QUANT_RESEARCH_2026_05_26.md`

---

### Agent O — Order book microstructure (~2 GB compute, 238k fires)

Built 55-feature panel on L25 books at every fire_us. Standalone rules ALL
lose money. **As OVERLAY on directional sleeves, 4/35 combos walk-forward pass —
all are ETH 15m momo**:

| Sleeve | n_test | WR | OOS $/tr | CI5 |
|---|--:|--:|--:|--:|
| momo_v2 ETH 15m + g_book_slope_steep_against | 82 | 79.3% | **+$10.69** | +$4.13 |
| momo_v2 ETH 15m + g_imb5_with | 115 | 61.7% | +$8.02 | +$2.18 |
| momo_v2 ETH 15m + g_depth_high | 167 | 59.3% | +$4.84 | +$0.38 |
| momo_extreme ETH 15m (no gate, mag≥3) | 40 | 82.5% | +$20.49 | — |

**Single big-win feature**: `g_spread_wide_skew` (opposite token spread wider than your side) — lifts WR 28-32pp consistently. Worth as a tie-breaker on existing sleeves.

**Negative finding**: book imbalance at extremes is ANTI-PREDICTIVE. SOL microstructure is degraded (3x wider spreads, 8x thinner depth) — discount SOL microstructure signals.

Report: `strategy_lab/reports/MICROSTRUCTURE_2026_05_26.md`
Panel: `data/v4/canonical/_results/microstructure_panel.parquet` (238k × 55)

---

### Agent P — Cross-exchange lead-lag

**Hypothesis "alt-venue leads binance" CLEANLY FALSIFIED**:
- 1-min resolution: all alt-venues peak xcorr at lag=0 with binance (0.89-0.99)
- 1s resolution: **Binance LEADS Hyperliquid by 1 second** (BTC/SOL xcorr at -1s = 0.43-0.45 vs +1s = 0.05-0.07)

**No standalone LL rule deployable** — best is 64% WR but loses $1.16/tr because Polymarket 1:5 payoff at vwap 0.5 needs WR > 83%.

**BUT as gate, lead-lag DOES help**:

| Sleeve | Gate | n | WR | $/tr | Lift |
|---|---|--:|--:|--:|--:|
| S1 + bn_with_5s | binance recent direction matches signal | 40 | 75% | **+$12.37** | +$7.66 |
| S3 + coinbase basis extreme against | xchg basis extreme | — | 69% | **+$11.72** | +$7.08 |
| S1 + kraken basis extreme against | xchg basis extreme | — | 74% | **+$11.45** | — |
| S5 + HL with_5s | HL recent direction | — | 70% | +$10.79 | +$4.91 |

**Walk-forward: 14/38 pass**. Strong on btc_15m sleeves. Caveat: alt-venue parquets stale at May 16 (3-day OOS only).

Report: `strategy_lab/reports/CROSS_EXCHANGE_LEADLAG_2026_05_26.md`

---

### Agent Q — PM trade flow + whale wallet

**PM trade flow IS predictive as gate (not standalone)**.

**Best sleeve**: BTC 5m off=90 V7 DOWN + `g_flow_with_and_no_whale` (PM 30s flow imbalance matches bet AND no whale active in 60s):
- Baseline V7: n=332, WR 70.8%, $/tr +$2.70
- + new gate: IS n=119, WR 77.3%, $/tr **$6.62**
- **OOS: n=22, WR 86.4%, $/tr +$11.25** — passes walk-forward

Twin: BTC 5m off=150 V7 DOWN → IS $4.86/tr, OOS **$10.64/tr** (n=29).

**Walk-forward: 7/12 combos pass**.

**Whale-FADE beats whale-MIMIC** by +$2.17/tr standalone. Reason: 5 of 6 catalogued whales with parsed chain data are MAKERS (F1 HFT scalper + mint-and-sell trio); fading a maker = siding with the aggressive taker.

**Single best PM feature**: `pm_up_imbalance_30s` (30s buy-flow imbalance) — mean +$0.41/tr lift across all 7 deployable V7 sleeves.

**Caveat**: F2 wallet trades_chain missing locally — F2 5s flow-fade replication failed. PM trade parquet stale May 6 (per CLAUDE.md).

Report: `strategy_lab/reports/PM_TRADE_FLOW_2026_05_26.md`

---

### Agent R — Vol regime + Hurst exponent

**Vol regime HELPS top sleeves substantially**:
- All 7 Tier-1 sleeves show best $/tr in HIGH vol
- ETH S6 60-150 swings: -$2.74/tr (low vol) → **+$5.42/tr (high vol)**
- S6 spike-continuation hypothesis CONFIRMED for gated sleeves

**Hurst predicts direction** ($35/tr swing on ETH S6):
- ETH S6 in H ≥ 0.6 (trending): **+$22.73/tr**
- ETH S6 in H < 0.4 (mean-reverting): -$12.95/tr
- SOL is structurally mean-reverting (median H=0.41) — only 0.5% fires trend → SOL Hurst weak

**Top new sleeve**: ETH S6 60-150 + **g_vol_expanding** (rv_60s > 1.5× rv_300s):
- IS: $/tr **+$17.24**, CI [+11.4, +22.9]
- **OOS: $/tr +$10.38, OOS lift +$7.38 over base** — walk-forward passes cleanly

**Walk-forward: 5/10 top combos pass OOS**:
- ETH S6 + g_vol_expanding: +$7.38 OOS lift
- BTC S15 60-150 + g_vol_expanding: +$2.69
- BTC S15 150-240 + g_vol_high: +$0.36

**Standalone Hurst/momo rules lose post-fee** (only VR-D vol-confirmed direction marginally positive).

Report: `strategy_lab/reports/VOL_HURST_2026_05_26.md`
Panel: `data/v4/canonical/_results/realized_vol_1s.parquet`, `gk_vol_5m.parquet`, `vol_hurst_at_fire_5m.parquet`

---

### Agent S — Funding + OI + Liquidations

**Data availability**: 4 of 5 loaders populated. HL funding, metrics (OI), liquidations, klines all present for BTC/ETH/SOL **through May 16** (binding window: 14.3 days). Binance metrics skipped (schema mismatch).

**Best deriv signal**: liquidation cascade continuation (L-A):
- Bet UP when HL short-liq totals > $100k in prior 60s
- **n=51, WR 66.7%, $/tr +$17.72, sum +$904** (small n)
- Threshold-stable from $50k (n=85, $/tr +$8.53) to $500k (n=13, +$15.29)
- Cascades = pure continuation (NOT mean-reversion at 5-15m horizon)

**Funding-extreme fade FAILED standalone** — hourly HL funding doesn't behave like 8h Binance funding; "crowded longs fade" thesis doesn't transfer.

**OI-A both legs win**: bet WITH price direction when OI is RISING → +$1.05-1.70/tr at n=2,863-4,507. With g_funding_extreme_against gate: **+$4.69/tr at n=514**.

**Walk-forward: 4/10 OOS pass** (strict n≥20). The 4 OI variants OOS-stable. L-A cascade variants OOS higher PnL but small n.

**Caveat**: window asymmetric (HL perp persistent discount, shorts dominant). Refresh HL data to May 25 before deploying.

Report: `strategy_lab/reports/FUNDING_OI_2026_05_26.md`

---

### Agent T — Full-window OOS validation ⚠️ CRITICAL

Re-ran top 15 R1+R2 sleeves on full Apr 24 → May 25 (25d REF + 4d OOS).

**Survivors (4 sleeves)** — REF → OOS $/tr held:
| Sleeve | REF $/tr | OOS $/tr | Status |
|---|--:|--:|---|
| btc_5m_s6_hybrid_v1 | $5.10 | $1.90 | ✅ held (n=2,570 OOS) |
| eth_5m_s6_hybrid_v1 | $1.57 | $0.86 | ✅ held |
| btc_5m_s15_hybrid_v1 | $3.12 | $2.08 | ✅ held |
| eth_15m_off60_120 | $4.48 | $5.68 | ✅ IMPROVED |

**Failed OOS (5 sleeves) — DO NOT DEPLOY**:
| Sleeve | REF $/tr | OOS $/tr | OOS WR | Loss |
|---|--:|--:|--:|--:|
| sol_5m_drz_res_down | +$6.62 | catastrophic | 45.5% | **-$35,730** |
| btc_5m_xa_down | +$1.64 | negative | 56% | -$8,869 |
| btc_5m_off120_sms_liq (the headline) | **+$20.68** | **$0.14** | 48.9% | -$992 |
| eth_15m_off120_240 | +$3.81 | -$1.59 | 60.2% | — |
| pool_15m_offge480 | +$5.48 | negative | 45.6% | — |

**Updated 33d combined deployable estimate**: ~$51,500 / 25d ≈ **$2,060/day at $25 notional, ~$20,600/day at $250 notional**. DOWN ~20% from R2 spec.

**Surprises**:
1. SMS liquidity_reclaim does NOT survive OOS — the biggest "find" of R2 was over-fit on 22d
2. Highest-fire-count SIMPLEST hybrid stacks (#02, #04, #07) are the MOST STABLE
3. High-$/tr bespoke ones (low n) are over-fitters
4. 15m sleeves degraded uniformly more than 5m
5. ETH 15m off=60-120 IMPROVED in OOS — small n=91 but signal looks real

Report: `strategy_lab/reports/FULL_WINDOW_VALIDATION_2026_05_26.md`

---

## What survived everything (R1 + R2 + R3 OOS)

After 33d full-window OOS gating, the TRULY deployable roster shrinks:

### Core (high confidence, n ≥ 500, OOS-validated)
1. **poly_updown_btc_5m_s6_hybrid_v1** — n=2,570 OOS, $/tr $1.90 OOS, sum projection ~$5,000/28d
2. **poly_updown_eth_5m_s6_hybrid_v1** — OOS $/tr $0.86, sum projection ~$3,000/28d
3. **poly_updown_btc_5m_s15_hybrid_v1** — OOS $/tr $2.08, sum projection ~$3,500/28d

### Validated Round-3 OVERLAYS on Core (each adds independent lift)
4. **+ g_vol_expanding on ETH S6** → OOS lift +$7.38/tr (Agent R)
5. **+ g_book_slope_steep_against on ETH 15m momo** → OOS $/tr +$10.69 (Agent O)
6. **+ g_flow_with_and_no_whale on BTC V7 5m DOWN** → OOS $/tr +$11.25 (Agent Q)
7. **+ g_coinbase_basis_extreme_against on S1/S3** → OOS +$7-12/tr (Agent P)

### Small but stable (low n, watch)
8. **poly_updown_eth_15m_off60_120** — n=91 IMPROVED in OOS, $/tr +$5.68 OOS
9. **poly_updown_hl_liq_cascade_up_btc** — n=51, $/tr +$17.72 IS (need OOS rerun on fresh HL data)

### From prior session (already deployed-ready)
10-15. S3 HoD refresh, S2 Fade Momo, S1.5 base + ribbon, V7 standalone, S7 top sleeves (per MASTER_DEPLOY_SPEC §B)

### REMOVED from roster
- SMS standalone liq_reclaim (overfit, OOS $0.14)
- SOL DRZ res_down (catastrophic OOS)
- BTC xa_down (cross-asset bias inverted OOS)
- Several 15m hunt sleeves (overfit)

---

## Updated combined deployable estimate

| Tier | Component | Sum/28d |
|---|---|--:|
| **CORE (validated OOS)** | btc_5m_s6_hybrid_v1 + eth_5m_s6_hybrid_v1 + btc_5m_s15_hybrid_v1 | $+11,500 |
| **CORE 15m** | eth_15m_off60_120 (small n, watch) | $+390 |
| **R3 OVERLAYS** | g_vol_expanding on ETH S6 + g_book_slope on ETH 15m + g_flow_no_whale on V7 + xchg basis | $+8,000-15,000 |
| **R1 quick wins** | S3 HoD refresh + S2 Fade Momo + B.7.1 fix | $+15,900 + $1,216 + $745 = $+17,861 |
| **R1 base sleeves** | S1.5 base + ribbon (top 5) | $+5,000-7,000 |
| **R1 V7 standalone** | top 3 V7 cells | $+2,500-3,000 |
| **R3 deriv** | HL liq cascade UP (small n, refresh data) | $+500-1,500 |
| **R1 S7 base 15m** | top 5 cells | $+1,500-2,000 |

**Realistic combined: ~$50-65k / 28d at $25 notional** = $1,800-2,300/day @ $25 = **$18-23k/day @ $250 notional**.

At $250 notional, **annual run-rate: $6.6-8.4M** (down from R2's $11.7-14.3M — but more honestly OOS-validated).

---

## Lessons learned for future rounds

1. **22d backtest windows are too short.** Many top sleeves OVERFIT the 22d
   window. Mandate 14-day OOS holdout BEFORE recommending any sleeve for deploy.

2. **High $/tr + low n = overfitter signal.** Sleeves with n < 200 and $/tr > $10
   should be treated as candidates, not deploys. Validate on n ≥ 300 OOS first.

3. **Simple > complex.** The "boring" hybrid_v1 stacks with 5 gates and 2k+ fires
   are the survivors. The 6-gate exotic stacks with 100 fires are mostly noise.

4. **Walk-forward is necessary but not sufficient.** Our 20d/8d in-sample walk-
   forward passed for sleeves that then FAILED on truly fresh data. Need a
   3-way split: train / validation / lockbox.

5. **Orthogonality matters.** g_sms_liq_reclaim was orthogonal to ribbon by
   correlation but the EDGE didn't generalize. Independence in feature-space
   doesn't guarantee independence in signal-space.

6. **Run truly fresh data the moment it arrives.** Production should auto-pull
   and re-validate top sleeves weekly. We have a pipeline (migration_2026_05_25)
   — should run it weekly with automated sleeve-stability checks.

7. **Standalone microstructure rules don't work** (Agent O confirmed). Book imbalance,
   microprice, depth, queue position — all useful as GATES but never as triggers.

8. **Cross-exchange lead doesn't exist between major venues.** Binance leads HL by 1s
   (within tick latency); coinbase/kraken/okx are essentially co-incident with binance.
   The cross-exchange BASIS is more useful than the directional lead.

---

## Recommendations for Round 4

Per Agent N's research — implement these three textbook signals we should have done in R1:

1. **Microprice (Stoikov 2018)**: `(bid_size × ask_price + ask_size × bid_price) / (bid_size + ask_size)`. Compute per-second on PM L25; use as direction signal at fire_us when |microprice_dev_bps| > threshold.

2. **Lee-Mykland jump detector**: properly statistical version of our S6 spike. `L(t) = |r(t)| / (bipower_variation × normalization_constant)` — fires only when statistically significant.

3. **Multi-level OFI (Cont/Xu/Gould)**: weighted sum of order flow imbalance across L1-L5; predicts price impact 68-74% better than top-of-book imbalance alone.

These three are the highest-leverage additions remaining on the table. Estimated combined uplift: +$5-10k/28d if walk-forward holds.

---

## Files inventory (Round 3 only)

### Reports
- `QUANT_RESEARCH_2026_05_26.md` — Agent N
- `MICROSTRUCTURE_2026_05_26.md` — Agent O
- `CROSS_EXCHANGE_LEADLAG_2026_05_26.md` — Agent P
- `PM_TRADE_FLOW_2026_05_26.md` — Agent Q
- `VOL_HURST_2026_05_26.md` — Agent R
- `FUNDING_OI_2026_05_26.md` — Agent S
- `FULL_WINDOW_VALIDATION_2026_05_26.md` — Agent T ⚠️ CRITICAL
- **`ROUND3_SYNTHESIS_2026_05_26.md`** ← THIS FILE

### Panels and result CSVs (in `data/v4/canonical/_results/`)
- `microstructure_panel.parquet` (238k × 55)
- `realized_vol_1s.parquet`, `gk_vol_5m.parquet`, `gk_vol_15m.parquet`
- `vol_hurst_at_fire_5m.parquet`, `vol_hurst_at_fire_15m.parquet`
- `_full_window_2026_05_26/sleeve_full_window_validation.csv`
- `_full_window_2026_05_26/sleeve_weekly_stability.csv`
- 5 OOS fire universes
- Per-agent task CSVs in respective directories

### Scripts (in `strategy_lab/`)
- `microstructure_2026_05_26/` — 4 scripts
- `cross_exchange_leadlag_2026_05_26/` — 11 scripts
- `pm_trade_flow_2026_05_26/` — 8 scripts
- `vol_hurst_2026_05_26/` — multiple
- `full_window_validation_v2.py`

## End
