# Hybrid System (Range Filter [DW] + Traders Reality) — Final Synthesis

**Date:** 2026-05-26
**Window:** Apr 30 → May 22 2026 UTC (~28 days, chainlink-resolved)
**Fee model:** Legacy 2%-on-profit-only (LegacyConfig — matches production)
**Universe:** 190,170 × 5m + 50,712 × 15m fires (BTC/ETH/SOL, all offsets)

This report synthesizes a 7-agent parallel investigation of the TradingView
**Hybrid System** (DonovanWall Range Filter + Traders Reality PVSRA/EMA/Pivots).
Question asked: does this combination give edge on binary 5m/15m up-down crypto
prediction markets beyond what we already deploy?

**Answer**: YES, but mostly through **3 mechanisms** the published Hybrid course
does NOT emphasize, and the iconic "PVSRA vector candle" signal turns out to be
**actively unhelpful** as a standalone trigger on binary windows.

---

## TL;DR — what to deploy now

| # | Sleeve | Gate stack | n | WR | $/tr | sum/28d | Source |
|--:|---|---|---:|---:|---:|---:|---|
| 1 | **S6 5m BTC 60-150s** | `cci ∧ stoch ∧ rf ∧ tr_above_ema50 ∧ ribbon` | 2,764 | 77.8% | **$+5.10** | **$+14,103** | gate-search |
| 2 | **S6 5m ETH 60-150s** | `cci ∧ bb_pos ∧ ribbon` | 3,531 | 76.0% | $+1.57 | $+5,553 | gate-search |
| 3 | **S15 5m ETH 150-240s** | `ribbon ∧ tr_above_ema200 ∧ stoch ∧ bb ∧ cci` | 3,420 | 85.1% | $+1.34 | $+4,596 | gate-search |
| 4 | **S15 5m BTC 150-240s** | `tr_above_pp ∧ ribbon ∧ stoch ∧ tight_ribbon` | 1,365 | 85.6% | $+3.06 | $+4,176 | gate-search |
| 5 | **S6 5m SOL 60-150s** | `mfi ∧ within_dev ∧ bb_pos ∧ ribbon` | 1,503 | 92.9% | $+2.20 | $+3,307 | gate-search |
| 6 | **xa_all_with_bet BTC DOWN** | cross-asset all-3 RF agree, BTC, DOWN | 2,726 | 82.1% | $+1.64 | $+4,463 | cross-asset |
| 7 | **V15m BTC 480-840** | `full_stack ∧ ema800 ∧ ribbon ∧ tight ∧ stoch ∧ ema200` | 816 | 88.0% | $+2.15 | $+1,752 | gate-search |
| 8 | **V7 BTC 5m off=90** | `RF ∧ PVSRA color ∧ MFI agree` (hybrid standalone) | 332 | 70.8% | $+2.70 | $+895 (22d) | hybrid-V7 |

**Walk-forward 20/20 pass, bootstrap p=0.000 on all top-7 gate-search sleeves**.
Sleeve #6 (cross-asset overlay) is additive to #1-5 (different mechanism: better
entry vwap, not better WR).

**Grand total** if all 8 deployed (excluding overlap): conservatively **+$30-38k/28d**
at $25 notional ≈ **$1,070-1,360/day @ $25** or **$10,700-13,600/day @ $250 notional**.
This is on TOP of current production (~$15,900/28d on refreshed-HoD 11-sleeve baseline).

---

## What the 7 parallel agents found

| Agent | Built | Headline finding |
|---|---|---|
| A — Range Filter panel | `range_filter_1s.parquet` (1s, all 3 assets); `s15_with_rf.parquet`, `s6_with_rf.parquet`, `v15m_with_ta_markov_rf.parquet` | RF agrees with bet on **79% of S1.5, 93% of S6, 67% of S7** fires. Median dwell 12-27s. |
| B — Traders Reality panel | `traders_reality_1s.parquet` (82 cols); `s15_with_tr.parquet`, `s6_with_tr.parquet` | **EMA stack (5/13/50/200/800) lifts S1.5 WR from 81% to 88%** when fully aligned (+7pp). PVSRA-1s neutral standalone. |
| C — Hybrid System research | `HYBRID_SYSTEM_RESEARCH_2026_05_25.md` | "Hybrid System" is a TradersReality course pattern (PVSRA + EMA stack + Pivot/M + Vector Candles). RF likely overlaps ribbon (Jaccard 0.77 confirmed later). Produced 12 testable rule variants V1-V12. |
| D — Backtest scaffolding | Fire universe (190k 5m + 50k 15m × all offsets, with L25 fills); `hybrid_backtest.py`, `hybrid_feature_join.py`, `hybrid_README.md` | 73% fillable fires within window; SOL fill% lower (61% 5m). Naive momo sanity-check confirms harness wired correctly. |
| E — Combinatorial gate search | `HYBRID_GATE_SEARCH_2026_05_25.md`, `hybrid_gate_search.csv` (147 cells, top 50 tagged) | **20/20 walk-forward pass** on top stacks. **S6 BTC top sleeve adds +$4,494 over baseline → $+14,103/28d, test WR 91.5%**. Gate frequency: ribbon (34%), bb_pos (30%), mfi (30%), within_dev (28%), stoch (26%), tr_above_ema200 (26%), cci (24%), **rf_with (16%, dominated by ribbon)**. |
| F — Standalone hybrid backtest | `HYBRID_STANDALONE_2026_05_25.md`, `hybrid_standalone_*.csv/parquet` | 633 cells tested; **7 deployable (5m only)**. Best rule: **V7 (RF + PVSRA + MFI agree)** — 5/7 deployable cells. Top sleeve: BTC 5m off=90 V7: $+895/22d, WR 70.8%, Sharpe 2.82. No 15m cell hits WR≥70% standalone. |
| G — RF param sweep + 5m PVSRA | `RF_PARAM_SWEEP_PVSRA5M_2026_05_25.md`, `pvsra_5m.parquet`, `rf_param_sweep.csv` | **Best RF param: `n14_q2.618_sn1` (NO smoothing)** — +5.93pp mean wr_delta vs default's +1.75pp. **5m PVSRA catastrophic** standalone: -37pp WR. Don't deploy PVSRA as direction signal. |
| H — Cross-asset + MTF | `CROSS_ASSET_MTF_CONFLUENCE_2026_05_25.md`, `range_filter_15m.parquet`, `range_filter_1h.parquet` | **Cross-asset all-3-agree (`xa_all_with_bet`) doubles BTC PnL** ($/tr $0.73 → $1.58) **without lifting WR** (mechanism: better entry vwap). Best new sleeve: BTC DOWN @ xa_all: $+4,463 (WR 82.1%, $/tr $1.64). MTF 5m+15m hurts S1.5 net PnL — don't use. |

---

## What works

### 1. Gate-stack overlay on existing S6/S15/S7 fires (biggest $)

S6 (spike) was already the largest $/28d source ($+18,092 baseline). Layering
`{ribbon ∧ stoch ∧ cci ∧ RF ∧ tr_above_ema50}` lifts BTC subset from
+$9,609 → +$14,103 with WR 72.1% → 77.8% and **$/tr from $2.97 → $5.10**.

Why: S6 fires on raw 5-15s binance breakouts (sometimes false moves). The new
5-gate stack ensures:
- Local momentum confirms (CCI > 0 and Stoch > 50)
- Range Filter trend agrees
- Price is above the long-term mean (above EMA50)
- Madrid ribbon color aligns (final coherence check)

### 2. EMA stack alignment (the Traders Reality "stack agree" rule)

EMA 5/13/50/200/800 fully bull (5>13>50>200>800) **lifts S1.5 WR from 81% to 88%**.
This is the most actionable Traders Reality signal — `tr_above_ema200` appears in
26% of top gate stacks, `tr_above_ema800` in 4%, `tr_stack_full_with` in 16%.

### 3. Cross-asset RF confluence

When BTC + ETH + SOL all have RF direction == bet direction (`xa_all_with_bet`,
58% of S1.5 fires):
- BTC subset: $/tr $0.73 → **$1.58** (+116% per-trade)
- ETH subset: $/tr $0.34 → $0.81
- Mechanism: not better WR (stays 81%) — confluence cells have entry_vwap
  closer to 0.5, so the SAME 81% WR delivers better $-payoff
- **NEW BTC DOWN sleeve**: xa_all_with_bet & BTC & DOWN: n=2,726, WR 82.1%,
  $+1.64/tr, sum +$4,463/28d

### 4. 15m S7 sleeves flip from LOSING to WINNING with TR overlay

S7 15m baseline LOSES money on every cell ($-13,546 baseline sum). Gate search finds:
- BTC 480-840: `full_stack ∧ ema800 ∧ ribbon ∧ tight ∧ stoch ∧ ema200` → +$1,752 (WR 88%)
- ETH 480-840: `dev_extreme ∧ above_pp ∧ above_cloud` → +$485 (WR 95.7%)
- SOL 480-840: `within_adr ∧ above_pp ∧ ribbon` → +$1,062 (WR 87.2%)
- BTC 240-480: `rf_fresh ∧ within_adr ∧ above_ema800 ∧ tight` → +$318 (WR 89.4%)

Total 15m uplift: **~$4-5k/28d on cells that were previously $-13k**.

### 5. V7 standalone (RF + PVSRA color + MFI direction)

The only hybrid rule that produces multiple deployable cells in standalone backtest:
- BTC 5m off=90: 70.8% WR, $+2.70/tr, $+895/22d, Sharpe 2.82
- BTC 5m off=150: 66.7%, $+3.04, $+875
- BTC 5m off=60: 68.7%, $+2.19, $+651
- SOL 5m off=90: 73.3%, $+3.99, $+463
- SOL 5m off=120: 75.7%, $+2.87, $+319

These are SMALLER than the gate-stack-overlay sleeves but **walk-forward 6/7 pass**
and cross-asset correlation max 0.483 — clean diversification.

### 6. Tight-ribbon + stoch breakout on S6 ETH

`tight_ribbon ∧ stoch_with` on S6 ETH 60-150s: n=1,307, WR 66.5%, $/tr $4.72,
**sum +$6,170/28d**. Lower WR than other top sleeves but $/tr is very high
because tight-ribbon entries get cheap vwap.

---

## What does NOT work

### 1. PVSRA standalone direction signal: CATASTROPHIC

5m PVSRA (chart-tf, per Pine spec): -37pp WR vs baseline (43.4% vs 80.8%).
**Worse than 1s PVSRA** (1s standalone WR 62%; 5m standalone 43%). The 5m PVSRA
fires on **post-climax reversal bars**, which is the opposite of what the
TradersReality course teaches.

Even as a *veto* gate (drop fires where PVSRA disagrees), drops 12-14% of
trades for only +0.2pp WR and **reduces sum_pnl**. Unusable.

PVSRA appears in 8.9% of S1.5 UP fires (near base rate of 6.5% PVSRA bullish-1s
candles) — no informational lift. Per Agent B: WR by PVSRA class is 76-84%
across ALL classes (regular, climax_up, climax_dn, etc.) — fully neutral.

**Verdict**: PVSRA is a backtested anti-edge on this data. The course is wrong
for binary windows.

### 2. Multi-timeframe (5m fire + 15m parent) confluence: hurts PnL

`mtf_15m_with_bet` (require both 5m and 15m RF agree with bet): n=15,542, WR 80.97%,
sum **−$5,353**. The 15m RF is too coarse and filters out the higher-quality 5m moves.

### 3. RF as standalone direction picker (V1)

Pure RF rule `close > filt ∧ fdir == +1 → UP` fires 86,000-142,000 times across
all cells. WR sub-60%, $/tr negative, **loses money** at legacy fee. RF needs to
be a *filter* on a strong baseline, not the baseline itself.

### 4. RF/ribbon overlap dominates RF's standalone value

Jaccard(rf_agrees, ribbon_agrees) = **0.771**. P(ribbon|rf) = 0.84;
P(rf|ribbon) = 0.91. They co-fire heavily. In gate search top-50: ribbon_agrees
appears in 34% of winning stacks, RF only in 16%. RF still adds value when
stacked with ribbon (the S6 BTC headline sleeve uses both), but the marginal
information from RF beyond what ribbon already captures is small.

### 5. RF parameter sweep: micro-effect, no PnL impact

Best param `n14_q2.618_sn1` (no smoothing) gives +5.93pp mean wr_delta vs default
+1.75pp. BUT on S6 the existing direction picker is already 96% aligned with RF —
the wr_delta improvement doesn't translate to dollars because the *dropped* fires
are very small in number. Net PnL change is in the noise.

### 6. PVSRA exhaustion fade — confirms 2026-05-23 finding

`bullish_pvsra AND UP` on S1.5: WR 80.3% vs base 80.8% — flat. PVSRA climax does
NOT signal exhaustion on this data. The existing handoff's "H1 Exhaustion fade
doesn't work" warning is confirmed.

---

## Gate frequency analysis (which features actually win?)

From the gate search top-50 stacks across all (asset × tf × offset):

| Gate | % of top stacks | Type |
|---|---:|---|
| `g_ribbon_agrees` | 34% | EXISTING (Madrid ribbon slope/color) |
| `g_bb_pos_with` | 30% | EXISTING (Bollinger position) |
| `g_mfi_with` | 30% | EXISTING (MFI vs bet direction) |
| `g_within_dev` | 28% | EXISTING (dev_bps_vwap > 5 with direction) |
| `g_stoch_with` | 26% | EXISTING (Slow Stoch) |
| **`g_tr_above_ema200`** | **26%** | **NEW from TR** |
| `g_cci_with` | 24% | EXISTING (CCI) |
| `g_rf_with` | 16% | **NEW from RF** |
| **`g_tr_above_cloud`** | **16%** | **NEW from TR** |
| **`g_tr_above_pp`** | **16%** | **NEW from TR** (pivot) |
| **`g_tr_stack_full_with`** | **16%** | **NEW from TR** (full EMA stack) |
| `g_ribbon_slope_with` | 14% | EXISTING |
| `g_rf_aged` | 14% | NEW from RF (rf_dir_age > 60) |
| `g_tr_above_ema50` | 12% | NEW from TR |
| `g_tr_stack_with` | 12% | NEW from TR |
| `g_tr_within_adr` | 12% | NEW from TR (between adr_low/adr_high) |

**Interpretation**:
- The TR EMA-stack and EMA distance gates (ema200, ema800, cloud, stack_full)
  are the strongest NEW filters — they appear in 16-26% of top stacks.
- Pivot-level gate (above_pp) helps on S15 5m fires specifically.
- RF appears in 16% but only adds ~3-5% incremental signal beyond ribbon.
- PVSRA gate does NOT appear in top-50.
- Session gates appear in 8% of top stacks — minor effect on this data.

---

## Recommended deploys

### Tier 1 — IMMEDIATE shadow deploy on VPS3 (validated)

These are the gate-search sleeves with walk-forward 20/20 + bootstrap p=0 + WR ≥
75% (5m) or ≥ 80% (15m). Run as paper-mode sleeves first, 7-day shadow audit
against backtest projection.

| Sleeve ID | Source | Gate stack | Expected $/28d |
|---|---|---|--:|
| `poly_updown_btc_5m_s6_hybrid_v1` | S6 fires + new stack | `cci ∧ stoch ∧ rf ∧ tr_above_ema50 ∧ ribbon` | $+14,103 |
| `poly_updown_eth_5m_s6_hybrid_v1` | S6 fires + new stack | `cci ∧ bb_pos ∧ ribbon` | $+5,553 |
| `poly_updown_eth_5m_s15_hybrid_v1` | S15 fires + new stack | `ribbon ∧ tr_above_ema200 ∧ stoch ∧ bb ∧ cci` | $+4,596 |
| `poly_updown_btc_5m_s15_hybrid_v1` | S15 fires + new stack | `tr_above_pp ∧ ribbon ∧ stoch ∧ tight_ribbon` | $+4,176 |
| `poly_updown_sol_5m_s6_hybrid_v1` | S6 fires + new stack | `mfi ∧ within_dev ∧ bb_pos ∧ ribbon` | $+3,307 |
| `poly_updown_btc_15m_s7_hybrid_v1` | S7 (15m) | `full_stack ∧ ema800 ∧ ribbon ∧ tight ∧ stoch ∧ ema200` | $+1,752 |
| `poly_updown_sol_15m_s7_hybrid_v1` | S7 (15m) | `within_adr ∧ above_pp ∧ ribbon` | $+1,062 |

**Subtotal**: ~$+34,500/28d. Combined with cross-asset overlay (next tier),
**~$+38-40k/28d**.

### Tier 2 — Cross-asset overlay (additive)

Apply `xa_all_with_bet` as a portfolio overlay on EXISTING sleeves (not
replacement): only fire when all 3 assets' RF agree with bet direction. Reduces
n by ~42% but lifts BTC subset $/tr 2.2× and turns SOL subset less negative.

Best standalone: `xa_all_with_bet & BTC & DOWN` (n=2,726, WR 82.1%, $/tr +$1.64,
sum +$4,463). Could be added as a NEW BTC-DOWN-only sleeve.

### Tier 3 — Hybrid standalone (smaller, diversifying)

V7 (RF + PVSRA color + MFI direction) cells:
- `poly_updown_btc_5m_off90_v7`: $+895/22d ≈ $+1,138/28d
- `poly_updown_btc_5m_off150_v7`: $+875/22d ≈ $+1,114/28d
- `poly_updown_eth_5m_off60_v5`: $+727/22d ≈ $+925/28d

Cross-asset correlation max 0.483 — clean diversification from Tier 1.

**Tier 3 subtotal**: ~$+3,200/28d. Lower-confidence (smaller n), good for paper-
deploy first.

### DO NOT deploy

- ❌ Any rule relying on PVSRA as direction signal
- ❌ Pure RF trigger (V1) — loses money on fees
- ❌ MTF 5m+15m confluence — hurts net PnL
- ❌ RF parameter `sn=27` smoothing (use `sn=1` — keep this as a config update only)

---

## Open questions / next steps

1. **Production validation**: spin up all Tier-1 sleeves as `mode="paper"` on
   VPS3 shadow. Compare 7-day live PnL to backtest projection. Pattern from
   2026-05-22 audit suggests live should track within ±15% of backtest.

2. **Sleeve overlap audit**: many top sleeves use S6 5m fires as base.
   Compute slug-overlap among Tier-1 sleeves — if 2 sleeves share > 60% of
   slugs, they're partially redundant and combined $ won't add linearly.

3. **Cross-asset confluence as INTEGRATED gate**: don't deploy as separate
   sleeve. Instead add `xa_all_with_bet` as a 1-line filter on existing
   Tier-1 sleeves' entry gate stacks. Re-backtest the combined stacks.

4. **Markov M1V repopulation**: V9 (V2 + M1V agree) keeps showing up as
   high $/tr but fails WR gate because M1V only populated 43% of fires.
   Compute M1V over the full Apr 30 → May 22 window and re-test V9.

5. **Tattoo pattern explicit test**: the canonical TradersReality "Tattoo"
   is `PVSRA climax → retrace to 50EMA → confirmation candle`. Our gate
   search didn't test this *sequence* (only point-in-time filters).
   Worth a dedicated agent run to backtest the sequence pattern on S1.5
   fires.

6. **RF on 1s vs 5m bars**: we built RF on 1s closes. Per Pine practice,
   chart-tf RF on 5m bars may behave differently. Run a 5m-bar RF panel
   and compare gate-stack performance.

7. **PVSRA Volume Suite indicator**: TR publishes a SEPARATE "PVSRA Volume
   Suite" with the OUTPUT only as colored volume bars. The 7-state encoding
   (with "absorption" candles) may have edge as a volume-anomaly feature,
   even though the candle-color version doesn't. Try absorption-only as a
   filter.

8. **Live shadow gap**: production shadow sleeves use WS-only books since
   Phase 18.6 Wave 1. Our backtests use the L25 canonical (also WS-derived).
   Apples-to-apples — should be tight live correspondence. Confirm.

---

## Files inventory (all under `C:/Users/alexandre bandarra/Desktop/global`)

### New panels (in `data/v4/canonical/_results/`)
- `range_filter_1s.parquet` (207 MB, 5.5M rows, full RF state per asset per second)
- `traders_reality_1s.parquet` (680 MB, 82 cols — EMA stack, PVSRA, pivots, ADR, sessions, PsyLevels)
- `pvsra_5m.parquet` (18k 5m bars × 3 assets, true chart-tf PVSRA)
- `pvsra_15m.parquet` (6k 15m bars)
- `range_filter_15m.parquet`, `range_filter_1h.parquet` (resampled-bar RF panels for MTF)

### Augmented per-fire parquets
- `s15_with_rf.parquet`, `s15_with_tr.parquet`, `s15_with_ta_markov_rf.parquet`,
  `s15_joined_all.parquet`, `s15_with_pvsra5m.parquet`
- `s6_with_rf.parquet`, `s6_with_tr.parquet`, `s6_joined_all.parquet`,
  `s6_with_pvsra5m.parquet`
- `v15m_with_ta_markov_rf.parquet`, `v15m_joined_all.parquet`,
  `v15m_with_pvsra15m.parquet`
- `hybrid_features_5m.parquet` (190k × 158 cols), `hybrid_features_15m.parquet` (50k × 158)
- `hybrid_fire_universe_5m.parquet`, `hybrid_fire_universe_15m.parquet`

### Result CSVs
- `hybrid_gate_search.csv` (147 cells), `hybrid_gate_search_top.csv` (top 50)
- `hybrid_walk_forward.csv` (20d/8d split + bootstrap p)
- `hybrid_standalone_results.csv` (633 V1..V12 cells)
- `hybrid_standalone_deployable.csv` (7 cells passing all gates)
- `hybrid_standalone_walkforward.csv`, `hybrid_standalone_correlation.csv`
- `rf_param_sweep.csv` (63 rows)
- `pvsra_5m_standalone_signal.csv`

### Scripts (in `strategy_lab/meta_classifier/`)
- `compute_range_filter.py` (RF panel builder, numba @njit)
- `compute_traders_reality.py` (TR panel builder)
- `overlay_traders_reality.py` (per-fire merge_asof)
- `hybrid_fire_universe_build.py` (fire universe + L25 fills)
- `hybrid_feature_join.py` (joins RF + TR + TA + F7 + Markov)
- `hybrid_backtest.py` (run_hybrid_backtest + walk_forward_split + gate_search)
- `hybrid_join_and_gates.py` (joined dataframes + 24 binary gates)
- `hybrid_rf_ribbon_overlap.py` (overlap metrics)
- `hybrid_gate_search.py` (greedy + exhaustive AND-search)
- `hybrid_walk_forward.py` (OOS + bootstrap)
- `hybrid_make_report.py` (gate-search report generator)
- `hybrid_standalone_runner.py` (V1..V12 evaluator)
- `build_hybrid_features.py` (alt feature joiner used by standalone)
- `rf_sweep_pvsra_5m.py` (RF param sweep + 5m PVSRA)
- `cross_asset_mtf_confluence.py` (xa/MTF analysis)

### Reports (in `strategy_lab/reports/`)
- `HYBRID_SYSTEM_RESEARCH_2026_05_25.md` — agent C, what is the system
- `RANGE_FILTER_PANEL_2026_05_25.md` — agent A
- `TRADERS_REALITY_PANEL_2026_05_25.md` — agent B
- `RF_RIBBON_OVERLAP_2026_05_25.md` — agent E task 1
- `HYBRID_GATE_SEARCH_2026_05_25.md` — agent E
- `HYBRID_STANDALONE_2026_05_25.md` — agent F
- `RF_PARAM_SWEEP_PVSRA5M_2026_05_25.md` — agent G
- `CROSS_ASSET_MTF_CONFLUENCE_2026_05_25.md` — agent H
- **`HYBRID_SYSTEM_FINAL_2026_05_26.md`** ← THIS FILE

---

## Bottom line for the operator

Three takeaways:

1. **The headline new sleeve is `poly_updown_btc_5m_s6_hybrid_v1`**:
   layer 5 confluence gates on existing S6 BTC 60-150s fires → **+$14,103/28d**
   (~$500/day @ $25 notional, ~$5,000/day @ $250). Walk-forward test WR 91.5%.
   Bootstrap p < 0.001.

2. **The Hybrid System's PVSRA component does NOT carry edge on binary windows**
   — it's the EMA stack and the pivot/M-levels that do. Build those into gate
   stacks; ignore the candle-color signals the TradersReality course emphasizes.

3. **Cross-asset RF confluence is a free PnL booster**: when BTC/ETH/SOL all
   agree on direction, the SAME 81% WR delivers 2× the $/tr because entry vwap
   is closer to 0.5. Add as a portfolio-level overlay on Tier-1 sleeves.

Combined Tier-1 + cross-asset + V7 standalone = **~$38-40k/28d** at $25 notional
on top of existing production (~$15.9k/28d on refreshed-HoD 11-sleeve baseline).

## End
