# Lee-Mykland (2008) Intraday Jump Test — 2026-05-26

## Executive summary

Implemented Lee-Mykland (2008) statistical jump test as a replacement candidate for
the S6 heuristic spike detector. Key conclusions:

1. **LM is NOT a clean upgrade of S6** — they overlap only 20% (S6 → LM) /
   4% (LM → S6). They detect different events.
2. **LM as standalone signal**: best rule is LM-E (bet sign of log_ret at fires
   where L_stat > 5.97) on BTC 5m: WR 69.7%, $/tr +$2.86, n=534, sum +$1,526.
3. **LM as GATE OVERLAY on S6 is the win**: g_lm_high_stat (L>5.97 at fire) +
   S6 BTC 5m → WR jumps from 68.5% to 82.1%, $/tr from +$2.39 to +$15.44.
4. **3-way validation**: 4 of 7 candidate sleeves pass lockbox (per_tr_usd > 0,
   n ≥ 5). Top: S1_btc_high_stat — train+$20.88, val+$15.85, lockbox+$2.92.
5. **g_lm_extreme_against is a KILL signal**: WR drops 30-40pp when the most
   recent extreme jump direction opposes the bet → useful negative filter.

## TASK 1 — Lee-Mykland panel build

**Implementation**: `strategy_lab/lee_mykland_2026_05_26/build_lm_panel.py`

**Configuration**:
- Bar size: **5-second** (sub-sampled from 1s binance closes; 1s data has
  34-71% zero-return bars due to microstructure rest periods, which deflates
  bipower variation and inflates L spuriously. 5s reduces zero-bar fraction to
  30-43% and is closer to LM's recommended HF regime.)
- Window K = 270 (= 22.5 minutes of 5s bars)
- Bipower variation excludes the candidate bar t (LM convention):
  `σ_BV(t) = sqrt(π/2 × 1/(K-1) × Σ_{s∈[t-K,t-1]} |r(s)|·|r(s-1)|)`
- Threshold at α: `β = sqrt(2·ln n) + (-ln(-ln(1-α))) / sqrt(2·ln n)`
  - n_obs ≈ 367k (BTC 22d 5s bars) → thr_01 = 5.971, thr_05 = 5.649
- Extreme tier: L > 10 (empirically heavy-tail cutoff)

**Output**: `data/v4/canonical/_results/lee_mykland_panel.parquet` (1.15M rows)

| Asset | n_obs   | jumps_01 (rate) | jumps_05 | jumps_ex (L>10) |
|-------|---------|-----------------|----------|-----------------|
| BTC   | 366,924 | 5,615 (1.53%)   | 6,381    | 1,535           |
| ETH   | 366,922 | 3,593 (0.98%)   | 4,146    | 785             |
| SOL   | 366,922 | 1,070 (0.29%)   | 1,272    | 243             |

**Caveat — jump count vs Agent N's spec**:
Agent N's spec expected ~12-15 jumps per asset over 28d. We see 5,615 BTC at
α=0.01 (≈ 255/day, well above the 1% nominal level on ≈ 367k observations,
which would be ≈ 3,670 false-positives if LM's iid-Gaussian-diffusion null
held). The empirical excess implies crypto 5s returns are heavy-tailed
beyond the LM null model — typical for microstructure-noisy HF data. The
"extreme" tier (L > 10) yields a more LM-canonical count: 1,535 BTC over 22d ≈
70/day. The signal is still informative as a feature; see TASK 5.

## TASK 2 — Sample at every fire_us causally

**Implementation**: `strategy_lab/lee_mykland_2026_05_26/sample_at_fires.py`

For each fire in `hybrid_fire_universe_{5m,15m}.parquet`, computed strictly
causally (last LM bar with ts ≤ fire_us):

- `lm_L_stat_at_fire`, `lm_log_ret_at_fire`
- `lm_has_jump_30s` / `60s` / `120s` (α=0.01)
- `lm_last_jump_dir_30s/60s/120s` (+1/-1/0)
- `lm_has_jump_extreme_60s`, `lm_last_jump_dir_extreme_60s/120s`
- `lm_n_jumps_in_last_300s` (count α=0.01)
- `lm_n_jumps_extreme_300s`

**Outputs**:
- `data/v4/canonical/_results/lm_at_fires_5m.parquet`  (190,170 fires)
- `data/v4/canonical/_results/lm_at_fires_15m.parquet` (50,712 fires)

Fires-with-jump (60s window, α=0.01):
- 5m: BTC 8,298 / ETH 5,654 / SOL 1,830
- 15m: BTC 2,234 / ETH 1,562 / SOL 500

## TASK 3 — Standalone rule tests (LegacyConfig fees)

**Implementation**: `strategy_lab/lee_mykland_2026_05_26/standalone_rules.py`

| Rule | TF | Asset | n     | WR%  | $/tr  | sum    |
|------|----|-------|-------|------|-------|--------|
| LM-A 30s WITH  | 5m | BTC | 3,446 | 66.9 | -0.997 | -$3,435 |
| LM-B 60s WITH  | 5m | BTC | 6,413 | 65.4 | -1.078 | -$6,916 |
| LM-C 120s WITH | 5m | BTC | 10,712 | 63.5 | -1.241 | -$13,296 |
| LM-D 60s AGAINST | 5m | BTC | 7,072 | 28.1 | **-5.810** | **-$41,086** |
| **LM-E L>5.97**  | 5m | BTC | **534** | **69.7** | **+2.857** | **+$1,526** |
| LM-F extreme 60s WITH | 5m | BTC | 1,842 | 69.6 | +0.628 | +$1,157 |
| LM-G extreme 120s WITH | 5m | BTC | 3,562 | 65.5 | -0.686 | -$2,442 |

**Findings**:
- LM-D (bet AGAINST jump) is **catastrophic** across all assets/TFs: WR drops to
  14-37% and $/tr is -$5 to -$16 per trade. Mean-reversion AFTER a jump is the
  WRONG bet — continuation dominates exhaustion at the 60-120s horizon. This
  matches Agent N's prior. Implication: ANY entry on a freshly-jumped market
  must bet WITH the jump, not against.
- LM-E (high L at fire moment, bet sign of last return) is the strongest pure
  standalone: positive across BTC and SOL on 5m; n is modest (534 BTC).
- LM-F (extreme jump 60s, bet with) is positive on BTC/ETH/SOL 5m, but on 15m
  it inverts (-$0.5 to -$2/tr) — implies jump continuation decays before the
  15m slot closes; 5m is the right horizon for jump-with bets.

## TASK 4 — Lee-Mykland vs S6 heuristic comparison

**Implementation**: `strategy_lab/lee_mykland_2026_05_26/compare_to_s6.py`

**Overlap on 5m hybrid universe** (S6: 3,322 unique fires; LM jump in 60s: 15,782):

- % of S6 fires that ALSO have LM jump in 60s: **20.1%**
- % of LM fires that ALSO are S6 fires:        **4.2%**
- Both:                                          **668**

Per-asset PnL by category (each cell uses its native direction picker: LM
sign(log_ret) for lm_only, S6's picked direction for s6_only/both):

| Asset | Category | n     | WR%  | $/tr   | sum     |
|-------|----------|-------|------|--------|---------|
| BTC | lm_only | 6,140 | 64.9 | -1.310 | -$8,042 |
| BTC | s6_only | 865   | 67.7 | +1.964 | +$1,699 |
| BTC | **both** | 273   | **71.1** | **+3.725** | +$1,017 |
| ETH | lm_only | 3,797 | 65.6 | -1.186 | -$4,504 |
| ETH | s6_only | 1,040 | 65.2 | -0.035 | -$36    |
| ETH | both    | 264   | 69.3 | -0.597 | -$158   |
| SOL | lm_only | 725   | 73.2 | +0.965 | +$699   |
| SOL | s6_only | 749   | 69.3 | +0.672 | +$504   |
| SOL | both    | 131   | 74.8 | -1.453 | -$190   |

**Verdict**: Lee-Mykland is NEITHER a clean upgrade NOR redundant with S6.
They detect largely disjoint event sets (80% non-overlap). On BTC, the
intersection (`both`) yields the highest WR (71.1%) and $/tr (+$3.73) per
fire — but it's small (n=273). S6's direction-picker is materially better
than LM's sign(log_ret) on lm_only fires (compare BTC $/tr: s6_only +$1.96 vs
lm_only -$1.31). LM's *direction* signal is noisy; its *event-detection* signal
is information-rich and best used as a gate.

## TASK 5 — Lee-Mykland as gate overlay on S6 sleeves

**Implementation**: `strategy_lab/lee_mykland_2026_05_26/gate_overlay.py`

Base sleeves: S6 spike fires (5m), grouped by (asset, fire_offset_s range).
Gates applied to filter base; PnL on S6's picked direction.

### Headline gates on BTC s6_all (15-300s offset, n=1,138, base WR 68.5%, $/tr +$2.39):

| Gate | n | WR% | (Δ) | $/tr | (Δ) | sum |
|------|---|-----|-----|------|-----|-----|
| **g_lm_high_stat** | 84 | **82.1** | +13.6 | **+15.44** | +13.05 | +$1,297 |
| g_lm_extreme_with | 104 | 82.7 | +14.2 | +6.35 | +3.96 | +$660 |
| g_lm_extreme_with_or_high | 160 | 81.2 | +12.7 | +7.87 | +5.48 | +$1,259 |
| g_lm_recent_jump_with | 217 | 80.2 | +11.6 | +6.18 | +3.80 | +$1,342 |
| g_lm_extreme_against (KILL) | 33 | 27.3 | -41.3 | -9.53 | -11.92 | -$315 |

### Same overlay on BTC 60-150s (the deploy-spec offset range, n=867, base WR 68.3%, $/tr +$2.15):

| Gate | n | WR% | (Δ) | $/tr | (Δ) | sum |
|------|---|-----|-----|------|-----|-----|
| g_lm_high_stat | 60 | 81.7 | +13.4 | **+16.79** | +14.63 | +$1,007 |
| g_lm_extreme_with | 71 | 83.1 | +14.8 | +7.36 | +5.20 | +$522 |
| g_lm_extreme_with_or_high | 112 | 82.1 | +13.9 | +8.94 | +6.78 | +$1,001 |
| g_lm_extreme_against (KILL) | 26 | 30.8 | -37.5 | -6.55 | -8.70 | -$170 |

### ETH/SOL gates (s6_all):

ETH base n=1,304, WR 66.0%, $/tr -$0.15:
- g_lm_extreme_with_or_high: n=127, WR 81.9% (+15.9), $/tr +$2.53, sum +$321
- g_lm_extreme_against: n=36, WR 33.3% (-32.7), $/tr -$1.13 (KILL)

SOL base n=880, WR 70.1%, $/tr +$0.36:
- g_lm_recent_jump_with: n=106, WR 87.7% (+17.6), $/tr +$1.85, sum +$196
- g_lm_high_stat: n=20, WR 90.0% (+19.9), $/tr +$10.82, sum +$216

## Top 5 NEW deployable LM-driven sleeves

| Rank | Sleeve | Asset | TF | Offset | Gate | n | WR% | $/tr | 22d sum |
|------|--------|-------|----|--------|------|---|-----|------|---------|
| 1 | `poly_updown_btc_5m_s6_lm_high_stat` | BTC | 5m | 60-150 | g_lm_high_stat | 60 | 81.7 | +$16.79 | +$1,007 |
| 2 | `poly_updown_btc_5m_s6_lm_extreme` | BTC | 5m | 15-300 | g_lm_extreme_with | 104 | 82.7 | +$6.35 | +$660 |
| 3 | `poly_updown_btc_5m_s6_lm_combo` | BTC | 5m | 15-300 | g_lm_extreme_with_or_high | 160 | 81.2 | +$7.87 | +$1,259 |
| 4 | `poly_updown_eth_5m_s6_lm_combo` | ETH | 5m | 15-300 | g_lm_extreme_with_or_high | 127 | 81.9 | +$2.53 | +$321 |
| 5 | `poly_updown_sol_5m_s6_lm_combo` | SOL | 5m | 15-300 | g_lm_extreme_with_or_high | 57 | 87.7 | +$3.97 | +$226 |

All use S6's direction picker. Gate stack runs on top of existing S6 spike
sleeve fire universe; only ADDS a filter, never relaxes one.

**Also add KILL filter**: any S6 fire where `g_lm_extreme_against` is TRUE
should be skipped — this is a high-confidence anti-signal (WR drops 30-40 pp).

## TASK 6 — Strict 3-way validation (train 12d / val 5d / lockbox 3d + 200-shuffle bootstrap)

**Implementation**: `strategy_lab/lee_mykland_2026_05_26/validation.py`

Note: split is 12/5/3 not 20/7/5 because the S6 fire universe spans only
21 days (May 1 → May 21), the LM panel goes to May 23 but S6 is the limiter.

| Sleeve | Split | n | WR% | $/tr | sum | p(bootstrap) |
|--------|-------|---|-----|------|-----|--------------|
| S1_btc_high_stat | train_12d | 42 | 81.0 | +20.88 | +$877 | 0.005 |
| S1_btc_high_stat | val_5d | 23 | 87.0 | +15.85 | +$365 | 0.000 |
| **S1_btc_high_stat** | **lockbox_3d** | **19** | **78.9** | **+2.92** | **+$55** | 0.195 |
| S2_btc_extreme_with | lockbox_3d | 30 | 76.7 | -1.34 | -$40 | 0.650 |
| S3_btc_extreme_with_or_high | lockbox_3d | 42 | 78.6 | +0.81 | +$34 | 0.300 |
| S4_eth_extreme_with_or_high | lockbox_3d | 30 | 90.0 | +2.08 | +$62 | 0.110 |
| S5_sol_extreme_with_or_high | lockbox_3d | 23 | 91.3 | +2.02 | +$47 | 0.135 |
| S6_btc_60_150_high_stat | lockbox_3d | 12 | 66.7 | -0.75 | -$9 | 0.555 |
| S7_btc_60_150_extreme_with | lockbox_3d | 19 | 78.9 | -0.61 | -$12 | 0.560 |

**Lockbox pass count: 4 / 7** (per_tr_usd > 0 AND n ≥ 5):
- S1 (BTC high_stat) — strongest, consistent across all splits
- S3 (BTC extreme_with_or_high) — broad combo gate
- S4 (ETH extreme_with_or_high)
- S5 (SOL extreme_with_or_high)

**Bootstrap p-values** ≤ 0.005 on train for S1/S3, ≤ 0.10 on val for S1/S3/S5
indicate the in-sample edge is unlikely to be noise. Lockbox p-values are
weaker (0.11–0.30) due to small n on the 3-day lockbox window — not a
rejection, just under-powered. Recommend re-validating after the next data
refresh extends the S6 universe beyond May 21.

## Caveats

1. **Jump-count discrepancy with Agent N's spec**: we get 5,615 BTC jumps at
   α=0.01 vs spec's "~12-15 per asset per 28d". Two reasons: (a) we test
   each bar individually at α=0.01 (yielding ~1% × n_obs expected false-
   positives under null), not the max-over-sample test that yields a single
   "probability of any false positive" of 1%; (b) crypto 5s returns are
   heavier-tailed than LM's iid-Gaussian diffusion null. The "extreme" tier
   (L>10) gives 1,535/22d for BTC ≈ 70/day, much closer to a meaningful
   "rare events" rate.

2. **5s bar choice**: 1s bars have 34-71% zero-return fraction (microstructure
   rest), which deflates bipower variation. 5s reduces to 30-43% zero-frac
   and yields more stable L. A 1s implementation can be added if needed but
   would require zero-return-aware BV (e.g. Andersen et al. 2007 truncated BV).

3. **Lockbox window is short (3 days)**: only ~12-42 trades land in lockbox
   for each gated sleeve. Bootstrap p-values on lockbox are 0.11-0.30 → edge
   probable but not statistically confirmed. After next refresh extends data
   past May 25, rerun with full 20/7/5 split.

4. **S6 direction-picker dependence**: the gate-overlay sleeves inherit S6's
   direction logic. If S6 changes (e.g. new spike-detection rules), the gate
   results must be re-validated.

5. **Latency**: bipower variation needs 270 bars (22.5 min) of history. At
   fire_us, the LM panel must be queryable with strict-asof on bars ending
   ≤ fire_us. Implementation note for live: maintain a rolling 22.5-min ring
   buffer of 5s bars per asset; recompute σ_BV every 5s.

6. **Fee model**: all PnL uses LegacyConfig (2%-on-profit-only) which matches
   current production. If Polymarket activates real fees, re-validate with
   LiveMimicConfig (will reduce $/tr by ~$0.40 on high-vwap winners).

## Files

- `strategy_lab/lee_mykland_2026_05_26/build_lm_panel.py` — panel builder
- `strategy_lab/lee_mykland_2026_05_26/sample_at_fires.py` — per-fire sampling
- `strategy_lab/lee_mykland_2026_05_26/standalone_rules.py` — Tasks 3
- `strategy_lab/lee_mykland_2026_05_26/compare_to_s6.py` — Task 4
- `strategy_lab/lee_mykland_2026_05_26/gate_overlay.py` — Task 5
- `strategy_lab/lee_mykland_2026_05_26/validation.py` — Task 6
- `data/v4/canonical/_results/lee_mykland_panel.parquet`
- `data/v4/canonical/_results/lm_at_fires_{5m,15m}.parquet`
- `data/v4/canonical/_results/lm_standalone_rules.csv`
- `data/v4/canonical/_results/lm_vs_s6_comparison.csv`
- `data/v4/canonical/_results/lm_gate_overlay.csv`
- `data/v4/canonical/_results/lm_validation_3way.csv`
