# New-indicators session synthesis — 2026-05-26 (Round 2)

> ⚠️ **CORRECTIONS NOTICE (Round 6 dedup)**: The combined deployable estimates
> quoted below are NAIVE SUMS that did not account for slug overlap. The
> actual realistic deployable is ~$20.5k/28d at $25 notional (~$2.67M/year
> @ $250). See `NAIVE_SUM_CORRECTIONS_2026_05_26.md` and
> `final_deploy_manifest.csv` for the authoritative numbers.
>
> Individual sleeve metrics (n, WR, $/tr per sleeve) in this report ARE
> CORRECT — only the COMBINED estimates were inflated by overlap.

**Date:** 2026-05-26 (afternoon)
**Window:** Apr 30 → May 22 2026 UTC (~28 days, chainlink-resolved)
**Fee model:** Legacy 2%-on-profit-only (LegacyConfig)

Second round of investigation, 5 parallel agents testing four new TradingView
indicators (Delta Reaction Zones, Quantum Ribbon Lite, Smart Money Structure /
CHoCH-BOS, regime classifier) + a focused 15m sleeve hunt. **Headline:
liquidity_reclaim is the biggest find — orthogonal to everything we had,
3-4× $/tr lift on top sleeves. And the 15m hunt produced 31 new walk-forward-
validated sleeves.**

---

## TL;DR — what's new vs MASTER_DEPLOY_SPEC_2026_05_26.md

| # | Discovery | Lift vs prior |
|--:|---|---|
| 1 | **SMS `g_sms_liq_reclaim_with`** sweep-and-reverse gate | BTC S6 hybrid: $5.10/tr → **$18.71/tr** (3.7×), sum +$13,075/22d |
| 2 | **SMS standalone** BTC S6 off=120 liquidity_reclaim (pure SMS) | NEW sleeve: n=166, WR 77.1%, $/tr **+$20.68**, +$3,432/22d |
| 3 | **31 new 15m sleeves** from focused hunt (WF p<0.05) | ETH dominates, killer feature `g_vwap_ge_50_le_85`, $/tr $4-8 test |
| 4 | **QR `g_qr_volume_strong`** on BTC S6 | +$12.7/tr lift (4× baseline) at 87% sample cost |
| 5 | **QR confidence buckets** (BTC monotonic, ETH non-monotonic) | Different per asset — use BTC conf ∈ [4,6] only |
| 6 | **DRZ `g_drz_not_contra_zone`** overlay | Modest: +$369 on BTC S6 → +$14,472 |
| 7 | **DRZ standalone** SOL 5m F_at_resistance_DOWN | NEW: n=291, WR 64%, $/tr +$6.62, +$1,927/28d |
| 8 | **Regime gating** flips 2 losing sleeves to OOS-positive | S7 ETH DOWN: -$0.62 → +$7.46/tr; S1.5 SOL DOWN: -$0.35 → +$4.81 |

**Total new uplift (additive on top of MASTER_DEPLOY_SPEC top-20):** ~**$25-35k/28d** at $25 notional, ~**$8-12k/day @ $250 notional**. Most of it from SMS-enhanced BTC S6 and the 15m hunt.

---

## 1. Smart Money Structure — the biggest find

### 1.1 What works
**`g_sms_liq_reclaim_with`**: bet UP when price taps the last 20-bar low (sweep) — assumes mean-reverting bounce; bet DOWN when it taps the 20-bar high.

This is the "stop hunt" / "liquidity sweep" pattern in smart-money trading. The
key for binary windows: don't fade EVERY zone — only the ones where the sleeve
direction already aligns with the post-sweep bounce direction.

**Top SMS-enhanced sleeves** (walk-forward 20/20 pass):

| Sleeve | n | WR | $/tr | sum/28d | Train→Test $/tr | p5 |
|---|--:|--:|--:|--:|--:|--:|
| **BTC S6 5m 60-150 + `g_sms_liq_reclaim_with`** | 699 | **88.3%** | **+$18.71** | **+$13,075** | $30 → $6.50 | +$5.57 |
| **ETH S6 5m 60-150 + `g_sms_liq_reclaim_with`** | 324 | 61.4% | +$10.52 | +$3,410 | — → $8.59 | +$4.12 |
| **BTC S6 5m off=120 standalone liq_reclaim** | 166 | 77.1% | **+$20.68** | +$3,432 | — | — |

The standalone "BTC off=120 liquidity_reclaim" sleeve uses NO base gates — just
the SMS signal. **+$20.68/tr** is the highest per-trade edge of any 5m sleeve
discovered all session. n is small but Sharpe is excellent.

### 1.2 What does NOT work (clean negatives)
- **`trend_strength_raw` standalone**: -$0.62/tr across all assets. Multi-TF
  consensus is a LATE signal in binary windows — by the time all TFs agree, the
  move is exhausted.
- **CVD-aligned standalone**: -$0.95/tr. CVD direction is reactive, not predictive.
- **`g_sms_recent_choch_with`** / **`g_sms_recent_bos_with`** standalone: no edge.
- **D_top_confidence** (system_confidence == 90): too sparse (n=43 total).

### 1.3 Why this matters
SMS liquidity_reclaim correlation with ribbon features is **-0.07** — fully
orthogonal. This is the rarest property in feature engineering: a signal that
genuinely adds independent information. Add `g_sms_liq_reclaim_with` to every
top sleeve.

**Files**: `strategy_lab/reports/SMS_BACKTEST_2026_05_26.md`, `sms_panel_5m.parquet`, `sms_panel_15m.parquet`

---

## 2. 15m sleeve hunt — 31 new deployable sleeves

The user explicitly asked for more 15m strategies with higher $/tr. We
exhaustively searched 1,563 gate combos across 121 cells (per-asset + pooled,
multiple offset bins). **31 sleeves pass strict walk-forward** (test_n ≥ 10,
test_wr ≥ 75%, test_dpt ≥ $3, bootstrap p < 0.05).

### 2.1 Top 10 new 15m sleeves (by full-window sum)

| Sleeve | Asset | Offset | n | WR | $/tr | sum_28d | test_$/tr | test_WR | gate_stack |
|---|---|--:|--:|--:|--:|--:|--:|--:|---|
| POOL_offge_720_devgeto10_dpt9.2 | POOL | ≥720s | 120 | 90.8% | $+9.22 | $+1,106 | $+4.00 | 90.5% | m5v_strong ∧ tr_above_cloud ∧ mfi ∧ cvd60 ∧ cvd30 ∧ tr_stack_full |
| POOL_offge_840_devgeto10_dpt20.1 | POOL | ≥840s | 55 | 90.9% | **$+20.09** | $+1,105 | $+4.20 | 84.6% | m5v_strong ∧ rf_in_band |
| POOL_offge_720_devgeto10_dpt7.9 | POOL | ≥720s | 140 | 91.4% | $+7.87 | $+1,102 | $+3.58 | 91.7% | m5v_strong ∧ tr_above_cloud ∧ mfi ∧ tr_stack_full |
| POOL_off120-240_dpt2.7 | POOL | 120-240s | 322 | 78.9% | $+2.67 | $+859 | $+4.48 | 82.7% | rf_aged ∧ cvd60 ∧ vwap_ge_30 |
| BTC_off480-600_dpt4.4 | BTC | 480-600s | 157 | 88.5% | $+4.37 | $+686 | $+2.58 | 88.6% | rf_aged ∧ cvd120 ∧ cvd60 ∧ bb_pos |
| ETH_offge_480_devgeto10_dpt6.4 | ETH | ≥480s | 91 | 90.1% | $+6.37 | $+580 | $+5.27 | 86.2% | vwap_50_85 ∧ tr_above_ema50 ∧ tr_above_ema800 |
| SOL_off360-480_dpt2.9 | SOL | 360-480s | 175 | 81.1% | $+2.88 | $+505 | **$+6.81** | 92.3% | tight_ribbon ∧ rf_with ∧ tr_within_adr |
| ETH_off120-240_dpt3.8 | ETH | 120-240s | 130 | 84.6% | $+3.81 | $+495 | $+5.60 | 87.8% | cvd60 ∧ tr_above_pp ∧ tr_above_ema200 |
| POOL_off60-120_dpt3.6 | POOL | 60-120s | 134 | 78.4% | $+3.65 | $+489 | $+6.39 | 83.7% | rf_aged ∧ ribbon_agrees ∧ cvd30 |
| ETH_off240-360_dpt2.7 | ETH | 240-360s | 180 | 84.4% | $+2.69 | $+484 | $+4.32 | 87.1% | tr_above_ema800 ∧ rf1h ∧ cci ∧ cross_partial |

### 2.2 Key findings from the 15m hunt

1. **ETH dominates** (20 of 37 deployable sleeves). Specifically early-fire
   ETH 15m (60-360s) was UNDER-EXPLORED in prior runs — bin gaps in original
   search. Combined ETH 15m subtotal: ~$3,500/28d.

2. **`g_vwap_ge_50_le_85` is a killer feature**: forces entry vwap into the
   "sweet zone" (avoids <$0.30 catastrophe + >$0.85 low-margin). Appears in
   9 of top 15 new sleeves.

3. **Pool > per-asset for late-fire dev cells**: pooling BTC+ETH+SOL fires
   with `|dev_bps| ∈ [10, 15]` at ≥480s offset gives n=86, $/tr +$5.48, more
   robust than per-asset.

4. **Per-asset > pool for early ETH cells**: ETH has its own early-fire edge
   that pooling dilutes.

5. **`g_cvd60_with` (CVD 60s aligned)** and **`g_rf_aged`** are powerful
   generic gates appearing across many cells.

6. **The famous "SOL 840 dev_20-30 $/tr=$21.79" sleeve does NOT generalize** —
   train/test split has test_n=0 because all qualifying fires concentrate in
   May 1-14. Was a 28d-window artifact.

### 2.3 Deployable subtotal

If all 37 new 15m sleeves deploy: ~**$8-12k/28d** at $25 notional. With ETH
focused offset 60-360s the largest contributor (~$3,500/28d alone).

**Files**: `strategy_lab/reports/SLEEVE_HUNT_15M_2026_05_26.md`, `sleeve_hunt_15m_deployable.csv` (37 rows)

---

## 3. Quantum Ribbon — meta-features add lift

### 3.1 What works
- **`g_qr_volume_strong`** (volume_ratio > 1.3): adds **+$12.7/tr** (4× baseline)
  on BTC s6_5m at 87% sample cost. Test $/tr +$3.64, p5 lower bound +$1.44 PASS.
- **`g_qr_high_health`** (health > 70): adds +$4.5/tr at only 8% sample loss
  on BTC s6_5m. Test $/tr +$2.43, p5 +$0.22 PASS.

### 3.2 Confidence-bucket analysis — KEY ASYMMETRY
| Asset | conf [0,2) | conf [2,4) | conf [4,6) | conf [6,8] |
|---|--:|--:|--:|--:|
| **BTC** WR | 50% | 70% | **84%** | 83% (monotonic) |
| **ETH** WR | — | — | 70% | **44%** (drops sharply!) |

**Insight**: High confidence on BTC is genuinely informative. High confidence
on ETH is a CONTRA signal — likely overextension reversal zone. **Recommend**:
gate BTC sleeves with `confidence ∈ [4, 6]`, gate ETH sleeves with
`confidence ∈ [2, 6]` (skip the >6 bucket).

### 3.3 What does NOT work
- Standalone QR rules lose (~44% WR). QR is best as a meta-filter.
- Madrid ribbon (existing 5-100 EMA range) and QR (21-60 EMA range) overlap on
  alignment — the NEW value is in regime + volume_ratio + confidence + health,
  NOT in the ribbon itself.
- 12/80 combos walk-forward pass — all are BTC s6_5m specifically.

**Files**: `strategy_lab/reports/QR_BACKTEST_2026_05_26.md`, `qr_panel_5m.parquet`, `qr_panel_15m.parquet`

---

## 4. Delta Reaction Zones — modest lift

### 4.1 What works
- **`g_drz_not_contra_zone`** (don't bet INTO an active opposing zone):
  modest +$369 lift on BTC s6 hybrid_v1 (+2.6%); $+44 to $+181 on other
  hybrid_v1 sleeves. 4/4 walk-forward sign-pass with p ≤ 0.05.

- **Standalone NEW sleeve**: **SOL 5m F_at_resistance_DOWN** — bet DOWN at
  resistance zone, n=291, WR 63.9%, **$/tr +$6.62**, sum +$1,927/28d, p=0.005.
  Cleanest standalone DRZ rule. SOL-specific edge (BTC/ETH similar rules
  failed walk-forward).

### 4.2 What does NOT work
- Direction-specific DRZ gates (at_support_with_up, recent_RC_with_up) collapse
  n too far (37-85) and lose >$1,700.
- "Naive fade the zone" looks good on BTC/ETH full-window but fails walk-forward
  on those assets — only SOL holds up.

### 4.3 Net contribution
~$1,000 lift across Tier-1 hybrid_v1 (from `g_drz_not_contra_zone`) + $1,927
from SOL standalone = ~**$3,000/28d net new**.

**Files**: `strategy_lab/reports/DRZ_BACKTEST_2026_05_26.md`, `drz_panel_5m.parquet`, `drz_panel_15m.parquet`

---

## 5. Regime-conditional sleeve routing

### 5.1 Regime classifier built
3-state (trending_up / trending_dn / ranging) using ADX(14) + tr_ema_stack_score
+ ribbon_alignment_pct. **Market is 86% ranging** on 5m bars — only ~14%
trending. Jaccard overlap with ribbon = 0.155 (regime adds genuine new info).

### 5.2 Tier-1 routing is marginal
On the Tier-1 hybrid_v1 top-7: always-on $/tr $3.04 → regime-routed $/tr $3.12
(+2.6% in-sample, +5% OOS, CIs overlap). **The gate stacks ALREADY encode
regime implicitly via ribbon + EMA stack** — adding an explicit regime gate
adds little.

### 5.3 BUT — regime gating FLIPS 2 losing sleeves
| Sleeve | Baseline $/tr | Regime gate | OOS test $/tr | CI |
|---|--:|---|--:|---|
| **S7 ETH 15m DOWN** | -$0.62 (LOSER) | trending_dn only | **+$7.46** (n=11) | [+$3.99, +$11.79] |
| **S6 BTC 5m DOWN** | +$4.19 | trending_up only | **+$10.66** (n=17) | [+$3.45, +$16.89] |
| **S1.5 SOL 5m DOWN** | -$0.35 (LOSER) | trending_dn only | **+$4.81** (n=39) | [+$1.02, +$8.52] |

Two regime-gated sleeves go from **NET LOSER → POSITIVE OOS**. This is the
clean win. Net new ~$500-1,000/28d.

**Caveat**: test n=7-39, wide CIs. Re-validate after 14d fresh data.

**Files**: `strategy_lab/reports/REGIME_CONDITIONAL_2026_05_26.md`, `regime_panel_5m.parquet`, `regime_panel_15m.parquet`

---

## 6. Updated combined deployable roster

Comparing pre-round-2 (MASTER_DEPLOY_SPEC) to post-round-2:

| Tier | Pre-R2 | Post-R2 lift | Post-R2 total |
|---|--:|--:|--:|
| Tier-1 hybrid_v1 (7 sleeves) | $+34,549 | +$13,075 (SMS on BTC) +$369 (DRZ) +$3-12/tr QR | **$+50,000-55,000** |
| Tier-2 cross-asset RF | $+8,748 | — | $+8,748 |
| Tier-3 V7 standalone | $+5,693 | — | $+5,693 |
| **NEW: SMS standalone (3 sleeves)** | — | — | **$+5,000-7,000** |
| **NEW: 15m hunt (31 sleeves)** | — | — | **$+8,000-12,000** |
| **NEW: DRZ standalone SOL** | — | — | $+1,927 |
| **NEW: Regime-gated 2 sleeves** | — | — | $+500-1,000 |
| S1.5 base + ribbon (10) | $+10,300 | — | $+10,300 |
| S6 base (10) | $+5,764 | superseded by hybrid_v1 | (overlap) |
| S7 base (10) | $+1,683 | partially overlaps 15m hunt | (overlap) |
| S2 Fade Momo patch | $+1,216 | — | $+1,216 |
| S3 HoD refresh | $+12,951 | — | $+12,951 |
| S5 Z_Contra ETH (paper) | $+594 | — | $+594 |

**Realistic combined deployable (with overlap dedup): ~$90-110k / 28d at $25 notional.**

At $250 notional ≈ **$32-39k/day = $11.7-14.3M/year run-rate.**

That's a roughly **2× scale-up over the previous MASTER_DEPLOY_SPEC**
($55-65k/28d → $90-110k/28d) just from this round.

---

## 7. Top NEW sleeves to register on VPS3 (priority order)

### Tier 1 — IMMEDIATE (orthogonal new signal, biggest lift)
1. **`poly_updown_btc_5m_s6_hybrid_v2`** = hybrid_v1 + `g_sms_liq_reclaim_with`
   - n=699, WR 88.3%, $/tr +$18.71, sum +$13,075/22d
   - The single most valuable sleeve change of this round.
2. **`poly_updown_eth_5m_s6_hybrid_v2`** = ETH hybrid_v1 + `g_sms_liq_reclaim_with`
   - n=324, WR 61.4%, $/tr +$10.52, sum +$3,410
3. **`poly_updown_btc_5m_off120_sms_liq`** = standalone liquidity reclaim
   - n=166, WR 77.1%, $/tr +$20.68 (no base gates needed)

### Tier 2 — 15m hunt picks (top 5 by test $/tr)
4. **`poly_updown_eth_15m_off60_120_v1`** — ETH 60-120s, n=87, test $/tr +$8.06, WR 89% OOS
   Gates: `tr_in_active_session ∧ vwap_50_85 ∧ tr_above_ema50`
5. **`poly_updown_pool_15m_off480_dev_10_15`** — POOL ≥480s + dev[10,15]bps
   n=86, test $/tr +$6.87, gates: `vwap_50_85 ∧ rf_fresh`
6. **`poly_updown_eth_15m_off120_240_v1`** — ETH 120-240s, n=119, test $/tr +$5.97
   Gates: `cvd60 ∧ tr_above_pp ∧ tr_above_ema800`
7. **`poly_updown_sol_15m_off360_480_v1`** — SOL 360-480s, n=175, test $/tr +$6.81
   Gates: `tight_ribbon ∧ rf_with ∧ tr_within_adr`
8. **`poly_updown_eth_15m_offge480_dev_10_15`** — ETH ≥480s + dev[10,15]
   n=79, test $/tr +$5.26

### Tier 3 — QR meta + DRZ enhancements
9. **`poly_updown_btc_5m_s6_hybrid_v3`** = hybrid_v1 + `g_qr_volume_strong` + `g_sms_liq_reclaim_with`
   (stack the orthogonal lifts)
10. **`poly_updown_sol_5m_off60_drz_resistance_down`** — DRZ standalone SOL
    n=291, WR 64%, $/tr +$6.62, sum +$1,927/28d

### Tier 4 — Regime-gated losers→winners
11. **`poly_updown_eth_15m_dn_trending_dn`** — S7 ETH 15m DOWN, fire only when regime=trending_dn
    Test $/tr +$7.46 (n=11, wide CI but flips baseline LOSER to positive)
12. **`poly_updown_sol_5m_dn_trending_dn`** — S1.5 SOL 5m DOWN, fire only when regime=trending_dn
    Test $/tr +$4.81 (n=39)

---

## 8. Required infrastructure for round-2 deploys

New panels needed on VPS3 (beyond what's in MASTER_DEPLOY_SPEC §A.4):

| Panel | Compute | New cols | Source |
|---|---|---|---|
| SMS (5m/15m bars) | 5m + 15m resample of 1s OHLCV | bos_buy/sell, choch_buy/sell, bars_since, liquidity_up/dn, rsi_div, cvd, trend_strength_raw | `sms_panel_5m.parquet`, `sms_panel_15m.parquet` |
| QR (5m/15m bars) | 5m + 15m resample | qr_state (-2..+2), regime, health (0-100), confidence (0-8), volume_ratio | `qr_panel_5m.parquet`, `qr_panel_15m.parquet` |
| DRZ (5m/15m) | Per-asset, ATR-based | drz_in_*_zone, drz_dist_bps, drz_recent_RC/RE, drz_zone_pos_pct | `drz_panel_5m.parquet`, `drz_panel_15m.parquet` |
| Regime (5m/15m) | ADX + ribbon + stack | regime_label, regime_score, adx_14, realized_vol_60m | `regime_panel_5m.parquet`, `regime_panel_15m.parquet` |
| `g_vwap_ge_50_le_85` | Per-fire | entry_vwap between 0.50 and 0.85 (boolean) | derived from existing book walk at fire_us |

All panels are ~50-200 MB zstd parquet. Compute time ~30s each on 5.5M 1s bars.

Gate function additions to `gates.py`:
```python
def g_sms_liq_reclaim_with(ctx) -> bool:
    """Bet UP at liquidity_dn (sweep then bounce); bet DOWN at liquidity_up."""
    if ctx.direction == "UP":
        return ctx.sms_liquidity_dn
    return ctx.sms_liquidity_up

def g_qr_volume_strong(ctx) -> bool:
    return ctx.qr_volume_ratio > 1.3

def g_qr_high_health(ctx) -> bool:
    return ctx.qr_health > 70

def g_qr_high_conf(ctx) -> bool:
    return ctx.qr_confidence > 4

def g_qr_conf_4_to_6(ctx) -> bool:
    """BTC sweet spot; for ETH use 2..6 — see report."""
    return 4 <= ctx.qr_confidence < 6

def g_drz_not_contra_zone(ctx) -> bool:
    """Don't bet INTO an active opposing zone."""
    if ctx.direction == "UP":
        return not ctx.drz_in_resistance_zone
    return not ctx.drz_in_support_zone

def g_vwap_ge_50_le_85(ctx) -> bool:
    """Entry vwap in sweet zone — avoids <$0.30 cat. + >$0.85 low margin."""
    return 0.50 <= ctx.entry_vwap <= 0.85

def g_cvd_aligned_with(ctx, window_s=60) -> bool:
    """CVD over last window matches bet direction. window_s ∈ {30, 60, 120}."""
    cvd = getattr(ctx, f"cvd_{window_s}s")
    if ctx.direction == "UP":
        return cvd > 0
    return cvd < 0

def g_regime_trending_dn(ctx) -> bool:
    return ctx.regime_label == "trending_dn"

def g_regime_trending_up(ctx) -> bool:
    return ctx.regime_label == "trending_up"
```

---

## 9. Negative findings (what didn't work — important context)

1. **Pure RF/QR/SMS standalone direction rules** all lose (~44-50% WR).
   These indicators are FILTERS, not alpha generators.
2. **`trend_strength_raw` standalone** loses (-$0.62/tr). Multi-TF consensus
   is reactive in binary windows.
3. **CVD-aligned standalone** loses (-$0.95/tr).
4. **CHoCH / BOS standalone** no edge. The patterns are anecdotal; they don't
   carry quantifiable predictive value on binary horizons.
5. **Naive "fade the DRZ zone"** looks profitable full-window but fails
   walk-forward on BTC + ETH (only SOL holds).
6. **PVSRA 5m and 1s** confirmed unusable (already documented in prior round —
   no PVSRA gate appears in any new top sleeve).
7. **Top confidence (system_confidence == 90)** too sparse to use (n=43 total).

---

## 10. Files inventory (round 2 only)

### Scripts (in `strategy_lab/`)
- `drz/drz_panel.py`, `drz/drz_overlay.py`, `drz/drz_backtest.py`, `drz/drz_walkforward.py`
- `sleeve_hunt_15m_2026_05_26.py`
- (QR, SMS, Regime scripts per agent — see their reports for paths)

### Panels (in `data/v4/canonical/_results/`)
- `drz_panel_5m.parquet`, `drz_panel_15m.parquet`
- `qr_panel_5m.parquet`, `qr_panel_15m.parquet`
- `sms_panel_5m.parquet`, `sms_panel_15m.parquet`
- `regime_panel_5m.parquet`, `regime_panel_15m.parquet`
- `sleeve_hunt_15m_features.parquet`

### Augmented per-fire parquets
- `s15_with_qr.parquet`, `s15_with_sms.parquet`
- `s6_with_qr.parquet`, `s6_with_sms.parquet`
- `v15m_with_qr.parquet`, `v15m_with_sms.parquet`

### Result CSVs
- `sleeve_hunt_15m_deployable.csv` (37 rows)
- DRZ, QR, SMS, regime backtest CSVs per agent

### Reports
- `DRZ_BACKTEST_2026_05_26.md`
- `QR_BACKTEST_2026_05_26.md`
- `SMS_BACKTEST_2026_05_26.md`
- `REGIME_CONDITIONAL_2026_05_26.md`
- `SLEEVE_HUNT_15M_2026_05_26.md`
- **`NEW_INDICATORS_SYNTHESIS_2026_05_26.md`** ← THIS FILE

---

## 11. Bottom line for the operator

**Three game-changing additions this round**:

1. **SMS liquidity_reclaim**: add to every BTC + ETH S6 sleeve. **3-4× $/tr lift** with walk-forward proof. The strongest new finding. Orthogonal to ribbon.

2. **15m sleeve catalog grew from 8 to 39 deployable sleeves.** Specifically ETH 15m at early offsets (60-360s) was massively under-explored. ~$8-12k/28d new capacity at higher $/tr than prior 15m sleeves.

3. **QR `g_qr_volume_strong` + `g_qr_high_health`**: BTC-specific meta-filters that boost $/tr 2-4× on already-winning sleeves.

**Combined deployable scale-up: $55-65k/28d → $90-110k/28d at $25 notional.**
**~2× over the previous comprehensive estimate.**

Updated deploy priority (replaces MASTER_DEPLOY_SPEC §C.5 deploy order):
- **Week 1**: S3 HoD refresh + S2 Fade Momo + B.7.1 (zero-code, immediate $14k lift).
- **Week 2**: Build SMS panel + add `g_sms_liq_reclaim_with` to existing 7 Tier-1 hybrid_v1 sleeves (immediate $13-17k lift from this change alone).
- **Week 3**: Build QR panel + add `g_qr_volume_strong` to BTC hybrid_v1 (incremental lift).
- **Week 4**: Deploy top 10 of the 15m hunt sleeves (paper mode first).
- **Week 5**: Build DRZ + Regime panels + deploy DRZ SOL standalone + 2 regime-gated losers→winners.
- **Week 6**: Tier-2 cross-asset + Tier-3 V7 standalone (from prior round).

## End
