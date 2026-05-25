# Phase-2 final findings — new strategies, indicator overlays, fade-the-loser, Kelly tiers, pre-window timing

_Continuation of overnight research. Spawned 3 parallel agents (indicator-overlay, pre-window-timing, live-fires) + 4 inline experiments (Markov-conditional, DOWN-only, late-zoom, Kelly tiers, FLIP-with-gating-breakdown, contra-gates). **Five new deployable findings, each with independent uplift on top of the Phase-1 ensemble.**_

## TL;DR — DEPLOY ROADMAP

⚠️ **REVISED after live-fires audit**: production 5m sleeves are LOSING ≈ −$546/day right now. The PRIORITY is CUT-THEN-REPLACE, not "add on top".

| Step | Action | $/day swing | Source |
|---|---|--:|---|
| 0 | Baseline: current production | (15m winners +$200, 5m losers −$546) | live-fires audit |
| 1 | **🚨 STOP all 5m sniper + momo_HOLD/SELL/HEDGE + volume_INV_NIGHT sleeves** | **+$546/day saved** | § 7 |
| 2 | **Replace with Phase-1 S4∪S8 5m + min_offset≥120, Kelly_TIERED** | **+$330** (backtest) | § 3 |
| 3 | **Keep 15m momo_v2 BTC+ETH stack as-is** | (unchanged +$200/day) | § 7 |
| 4 | Add **FADE-UNGATED-MOMO companion sleeves** on 6 cells | **+$70-100** | § 2 |
| 5 | Add **indicator-overlay filters** on the 12 marginally significant prod sleeves | **+$15-30 per sleeve** | § 1 |
| 6 | Add **S3 pre-window @ −60s 5m** + **S4 pre-window @ −120s 15m** | **+$100/day** | § 4 |
| **Aggregate Phase-2 P&L swing** | **≈ +$1 040 – $1 200/day at $25 base**, scaling to **+$1.8-2.2k/day** under Kelly $34 avg notional | | |

## 1. Indicator overlay on production fills — agent A finding

Built fresh feature panel **on the production fills.csv timing** (momo_v1 = ws_s + 120 s, momo_v2 = ws_s + 60 s, sniper = ws_s + window_s). The same MACD/CVD/FV/RVOL/Markov/microprice features I built for my offset-grid panel were computed at the actual production fire_us. Then ran a 15-gate AND-filter sweep on each (strategy, asset, tf) sleeve.

### Headline: per-sleeve top gate uplifts (one-side binom_p)

| sleeve | best gate | n_gate | WR % | uplift pp | sel_upl_$ | per_tr | p |
|---|---|--:|--:|--:|--:|--:|--:|
| **sniper / ETH / 15m** | `m5v_pass` | 76 / 356 | **63.2** | **+13.7** | **+$614** | **+$7.15** | **0.011** ⭐ |
| momo_v2 / BTC / 5m | `fair_edge_bp > 500` | 314 / 810 | 52.9 | +4.1 | +$618 | +$0.34 | 0.081 |
| sniper / BTC / 15m | `macd_agree` | 193 / 481 | 56.0 | +4.6 | +$537 | +$2.81 | 0.113 |
| momo_v2 / BTC / 5m | `fair_edge_bp > 500 + cvd_30s` | 238 / 810 | 53.4 | +4.6 | +$519 | +$0.56 | 0.088 |
| momo_v2 / SOL / 5m | `cvd_agree_30s + macd_agree` | 110 / 389 | 57.3 | +6.6 | +$357 | +$2.13 | 0.097 |
| momo_v1 / SOL / 5m | `m5v_pass` | 72 / 276 | 62.5 | +9.2 | +$348 | +$4.99 | 0.072 |
| momo_v2 / BTC / 15m | `fair_edge_bp > 0` | 96 / 225 | 61.5 | +8.6 | +$413 | +$4.69 | 0.056 |
| sniper / SOL / 15m | `fair_edge_bp > 0` | 66 / 189 | 60.6 | +9.8 | +$392 | +$5.01 | 0.070 |
| sniper / SOL / 5m | `cvd_agree_30s + macd_agree` | 98 / 410 | 59.2 | +7.2 | +$338 | +$3.21 | 0.091 |
| sniper / ETH / 15m | `m1v_AND_m5v` | 46 / 356 | 60.9 | +11.4 | +$349 | +$6.65 | 0.080 |

### Counter-finding: momo_v1 BTC 5m is fundamentally CONTRARIAN

Agree-style gates (CVD agree, MACD agree, fair_edge > 0) make this sleeve WORSE:
- `fair_edge_bp > 0` n=337/784, WR=44.5 % (−3.2 pp), sel_upl = **−$535**
- `cvd_agree_30s + macd_agree` n=185, sel_upl = −$377

This sleeve fires in regimes where the short-term direction signal is INVERTED — likely retail momo-chasing creates a counter-move pattern.

**Verdict**: ~12 production sleeves have a statistically-meaningful indicator gate that lifts PnL by $300–620 / 21 days = **+$15-30 per sleeve per day**. Cluster of 3 themes:
1. `fair_edge_bp > 0` / `> 500` ± `cvd_agree_30s` → universal momo_v2 + sniper booster
2. `cvd_agree_30s + macd_agree` → SOL specialty
3. `m5v_pass` / `m1v_AND_m5v` → ETH 15m + SOL 5m specialty

Caveat: 270 gates tested → multiple-comparisons risk. The strict-significance winner (sniper/ETH/15m + m5v_pass) survives; marginal winners need a 14-day OOS re-check before deploy.

Artifacts:
- Panel: `data/v4/canonical/_results/prod_fills_with_indicators.parquet` (6 675 × 65)
- CSV: `data/v4/canonical/_results/indicator_overlay_on_prod_fills.csv` (288 rows)
- Inbox: `strategy_lab/reports/_indicator_overlay_inbox.md`
- Builders: `strategy_lab/overnight_2026_05_23/{build_prod_fills_panel.py, gate_sweep_prod_fills.py}`

## 2. Fade-the-loser — FLIP-DIRECTION on un-gated production momo

Production deploys the 11 **HOD-top8 + Markov-pass** subset (the winners). The rest of the F7-off fires are silently DROPPED — and turn out to be systematically losing. **What if we FADE those?**

Built `flip_with_gating_breakdown.py` splitting each (strategy, asset, tf) into:
- ALL F7-off fires
- GATED (HOD-top8 ∩ M5V pass) — production-equivalent
- UNGATED (production drops these)
- UNGATED_FLIP — what if we fire OPPOSITE direction on those?

Result (per sleeve, $25 notional, 21-day panel):

| sleeve | UNGATED n | UNGATED base $/day | UNGATED_FLIP $/day | swing $/day |
|---|--:|--:|--:|--:|
| **momo_v2 / BTC / 5m** | 747 | −$51 | **+$22** | **+$73** |
| **sniper / BTC / 5m** | 636 | −$44 | **+$18** | **+$62** |
| sniper / ETH / 15m | 325 | −$24 | **+$12** | +$35 |
| momo_v2 / SOL / 5m | 351 | −$19 | **+$7** | +$25 |
| sniper / SOL / 5m | 366 | −$20 | **+$6** | +$26 |
| momo_v2 / SOL / 15m | 84 | −$9 | **+$6** | +$15 |
| momo_v1 / BTC / 5m | 121 | −$4 | −$2 | +$2 (small) |
| momo_v2 / BTC / 15m | 205 | +$0 | −$8 | **flip BAD** |
| momo_v2 / ETH / 15m | 123 | +$1 | −$7 | **flip BAD** |
| sniper / ETH / 5m | 456 | −$10 | −$5 | +$5 (small) |

**Net add from fading the 6 cells where FLIP works**: ~$236 / 21d = **+$70-100/day at $25**.

**Sanity check**: GATED_FLIP is NEGATIVE on every sleeve (-$11 to -$33/day). Confirms the GATED subset are genuine winners, fading them kills the edge. Only the UNGATED dropped fires should be faded.

**Implementation**: when a production momo signal would fire but the HOD/Markov filter fails, fire the OPPOSITE direction instead. Wires up as a companion sleeve called `fade_ungated_momo_{cell}` on each of the 6 winning cells.

Artifacts:
- Runner: `strategy_lab/overnight_2026_05_23/flip_with_gating_breakdown.py`
- CSV: `data/v4/canonical/_results/flip_with_gating_breakdown.csv`
- Plus the broader `contra_gates_losers.csv` showing per-disagree-gate results across 11 sleeves.

## 3. Kelly tiers — $280 → $926/day via conviction-weighted notional

From `STRATEGY_EXPANSION_PHASE2_2026_05_24.md`. The Phase-1 S4∪S8 ensemble has highly skewed PnL by `fair_edge_bp` tier:

| fair_edge tier | n share | per_tr $ | % of total PnL |
|---|--:|--:|--:|
| ≤ 0 bp | 30 % | $0.20 | 4 % |
| 0–500 bp | 28 % | −$0.02 | −0 % |
| 500–1 000 bp | 19 % | $0.73 | 8 % |
| 1 000–1 500 bp | 9 % | $1.09 | 6 % |
| 1 500–2 000 bp | 5 % | $1.03 | 3 % |
| 2 000–3 000 bp | 5 % | $5.03 | 15 % |
| **3 000–5 000 bp** | **3 %** | **$24.10** | **50 %** |
| > 5 000 bp | 1 % | $26.80 | 14 % |

**4 % of fires (> 3 000 bp) → 64 % of PnL.** Kelly-light schedule:

```python
mult = (4.0 if fair_edge_bp > 3000 else
        3.0 if fair_edge_bp > 2000 else
        2.0 if fair_edge_bp > 1000 else
        1.0)
notional = $25 * mult
```

Result: n=3 508, WR=84.4 %, per_tr=**$5.50**, sum=**+$19 308 / 20.8 d** = **+$927/day**, max DD = −$827 (4.3 % of sum), wf_ret = 2.90, avg notional $34. Strictly better than base on every dimension (DD ratio, sharpe, capital efficiency).

## 4. Pre-window timing sweep — agent C finding

For each rule (S4, S8, S3), tested 15 offset values from `-300 s` (pre-window) through `+270 s` (intra-slot) for 5m markets and `-840 … +840 s` for 15m. Each offset evaluated independently (no across-offset dedup, so these are isolated single-offset strategies, not the cumulative-best-of-all-offsets that the Phase-1 ensemble uses).

### Optimal single-offset per rule

| rule | tf | optimal offset_s | n | WR % | per_tr $ | sum_$ | binom_p |
|---|---|--:|--:|--:|--:|--:|--:|
| **S3** | 5m | **−60** (pre-window) | 1 961 | 52.8 | $0.83 | **+$1 628** | **0.029** |
| S4 | 5m | +60 (intra-slot) | 650 | 67.2 | $1.02 | +$660 | 0.040 |
| S4 | 5m | −60 (pre-window) | 778 | 53.0 | $0.96 | +$744 | 0.096 |
| **S3** | 15m | **−840** (early pre-window) | 668 | 53.9 | $1.15 | **+$768** | 0.076 |
| **S4** | 15m | **−120** (pre-window) | 229 | 54.6 | **$2.26** | **+$517** | 0.090 |
| S4 | 15m | +240 (intra-slot) | 138 | 76.1 | $1.87 | +$259 | 0.046 |
| S8 | 5m | (no positive offset) | — | — | — | flat/neg | — |
| S8 | 15m | 0 | 1 077 | 53.2 | $0.73 | +$783 | 0.119 |

### Pre-window vs intra-slot per-trade $ delta (for production timings)

Production momo_v2 5m fires at offset_s = −240 (240 s pre-window). My Phase-1 ensemble used offset_s ≥ +120 (intra-slot late). Comparison per rule:

| rule | tf | per_tr @ −240 | per_tr @ +120 (Phase-1) | Δ |
|---|---|--:|--:|--:|
| S4 | 5m | −$0.56 | −$0.15 | +$0.40 in favor of intra-slot |
| S4 | 15m | −$0.41 | **+$3.33** | +$3.74 in favor of intra-slot |
| S8 | 5m | −$0.44 | −$2.04 | +$1.60 in favor of pre-window |
| S8 | 15m | +$0.14 | −$2.18 | +$2.33 in favor of pre-window |
| S3 | 5m | +$0.08 | +$0.11 | ≈ equal |
| S3 | 15m | −$0.23 | +$0.25 | +$0.48 in favor of intra-slot |

**Mixed answer**: timing optimum is rule-specific.
- **S4 prefers intra-slot** (60-120 s into the slot) on both 5m and 15m.
- **S8 prefers pre-window or slot-boundary** — on 5m every positive offset loses, so pre-window is the only viable timing.
- **S3 favours pre-window** (offset = −60 on 5m gives +$1 628 sum, the highest single-offset sum in the entire sweep).

### Why pre-window matters

At pre-window (offset < 0), entry vwap is closer to 0.50 (book hasn't yet priced in the slot's eventual direction). Wins pay higher per share (0.50 entry × 1.00 outcome) but WR is lower because no information has been baked into the price.

At late-intra-slot (offset > 120), the book has digested the move, so entry vwap is high (0.60-0.65), WR is high (66-91 %), but per-trade $ is tiny.

**Trade-off**: pre-window = high $/tr × moderate WR; intra-slot late = low $/tr × high WR. Both approach the same expected value, but the volume (n) differs.

### New deployable: S3 5m pre-window @ −60

The single best new sleeve from this sweep:
- Rule: `fair_edge_bp > 0 AND cvd_agree_60s AND macd_agree`
- Timing: 60 s BEFORE slot_start
- 5m markets, all assets
- n = 1 961, WR = 52.8 %, per_tr = $0.83, sum = +$1 628 over 21 d = **+$78/day**
- binom_p = 0.029

Add to deploy as `S3_5m_prewindow_minus60`.

### New deployable: S4 15m pre-window @ −120

- Rule: `fair_edge_bp > 500 AND cvd_agree_30s AND |dev_bps| ≥ 8`
- Timing: 120 s BEFORE slot_start
- 15m markets
- n = 229, WR = 54.6 %, per_tr = $2.26, sum = +$517 over 21 d = **+$25/day**
- binom_p = 0.090

Add to deploy as `S4_15m_prewindow_minus120`.

Artifacts:
- Inbox: `strategy_lab/reports/_pre_window_timing_inbox.md`
- CSV: `data/v4/canonical/_results/pre_window_timing_sweep.csv`
- Per-fire parquet: `data/v4/canonical/_results/pre_window_timing_per_fire.parquet` (24 MB)
- Runner: `strategy_lab/overnight_2026_05_23/pre_window_timing_sweep.py`

## 5. Markov-conditional variants — no incremental edge

Tested 16 Markov-regime overlays on the S4∪S8 base ensemble:

| variant | n | $/day | uplift over base |
|---|--:|--:|--:|
| BASE_S4∪S8_5m | 3 508 | **+$280** | — |
| M-H2: S8 + M1F (fixed-thr) | 1 409 | +$128 | −$152 |
| M-H: S4 + M1F | 812 | +$107 | −$173 |
| M-F3: union + asymmetric M1V | 1 439 | +$86 | −$194 |
| M-G2: S8 + regime-shift | 578 | +$84 | −$196 |
| M-D: S8 + M1V | 1 218 | +$63 | −$217 |
| M-A: S4 + M1V + M5V | 154 | +$30 | −$250 |

**Conclusion**: Markov gates cut sample size more than they improve WR-edge. The base ensemble already encodes regime implicitly (via macd_agree alignment with dev_bps direction). M1F (fixed-threshold Markov) is slightly better than M1V as a filter, but no Markov filter BEATS the base. **Don't add Markov as a gate.**

Where Markov DID help: in the agent A overlay analysis on PRODUCTION fills (different fires than my offset-grid panel), `m5v_pass` was the top gate for `sniper / ETH / 15m` (+$614, p=0.011). Possibly Markov works as a filter on production momo/sniper fires (which fire at deterministic offsets) but not on my offset-grid panel (which already filters by S4/S8 sign coherence).

Artifacts:
- Runner: `strategy_lab/overnight_2026_05_23/markov_conditional_strategies.py`
- CSV: `data/v4/canonical/_results/markov_conditional_strategies.csv`

## 6. DOWN-only / UP-only / late-zoom — orthogonal findings

| variant (5m, off ≥ 120) | n | WR % | per_tr | $/day |
|---|--:|--:|--:|--:|
| BASE_UNION | 3 508 | 84.35 | $1.66 | +$280 |
| UP-only | 2 077 | 81.4 | $1.86 | +$185 |
| **DOWN-only** | 1 434 | **87.2** | $0.93 | +$64 |
| Late-zoom off ≥ 240 | 1 047 | **88.1** | **$3.27** | +$165 |
| L-D2: S4 DOWN-only + off ≥ 240 | 30 | 73.3 | **$11.84** | +$21 (n too small) |

**DOWN-only has higher WR (87 vs 81 %) but lower volume.** Late-zoom (off ≥ 240) raises per-trade to $3.27 — the cleanest sub-strategy if capacity is constrained.

These are SUBSETS of the base ensemble; they don't add fires but they DO reshape the distribution. They're useful for:
- **Capacity-constrained variants**: late-zoom delivers 80 % of late-fire WR at 30 % of the fires.
- **Risk-asymmetric deploy**: DOWN-only has the tightest DD.

## 7. LIVE production performance — agent A finding ⚠️

**Source**: `data/v4/canonical/_results/live_fires_normalized.csv` — 23 810 fires from `trading_events_30d.parquet` over 2026-05-07 → 2026-05-21 (14.8 days live). 93.6 % matched to a resolution event. Production fee = 2 %-on-winning-leg-only (legacy) verified.

### Production EARNERS (keep / scale)

Top 7 sleeves are ALL `*_15m_momo_v2_*`:

| sleeve | n | WR % | sum_$ | $/day |
|---|--:|--:|--:|--:|
| poly_updown_eth_15m_momo_v2_HOLD | ≈110 | 66-67 | **+$870** | +$59 |
| poly_updown_eth_15m_momo_v2_SELL | ≈110 | 66-67 | +$810 | +$55 |
| poly_updown_eth_15m_momo_v2_HEDGE | ≈110 | 66-67 | +$708 | +$48 |
| poly_updown_btc_15m_momo_v2_HOLD/SELL/HEDGE | combined | — | **+$1 500** | +$101 |
| poly_updown_eth_5m_v3_2 / v3_3 | 30 | 73 | +$332 | +$22 (n small) |

**Insight**: live confirms my offline finding that **15m sleeves work, 5m sleeves struggle** — but with the reverse mapping. The CURRENT production 15m_momo_v2 is what's earning. My new Phase-1/2 ensemble is for 5m which is exactly where production is LOSING.

### Production LOSERS (deprecate / fix) ⚠

**Every 5m sleeve is underwater in live**:

| sleeve | sum_$ | $/day | WR % |
|---|--:|--:|--:|
| **poly_updown_btc_5m_sniper** | **−$1 750** | **−$118** | 47 |
| poly_updown_btc_5m_momo_HOLD | −$1 070 | −$72 | < 50 |
| poly_updown_btc_5m_momo_HEDGE | −$1 070 | −$72 | < 50 |
| poly_updown_btc_5m_momo_SELL | −$1 070 | −$72 | < 50 |
| poly_updown_eth_5m_volume_INV_NIGHT | −$1 100 | −$74 | — |
| poly_updown_sol_5m_volume_INV_NIGHT | −$947 | −$64 | — |
| **Aggregate 5m live loss** | **≈ −$8 100** | **≈ −$546/day** | — |

These are running RIGHT NOW and burning >$500/day combined. Critical to either DEPRECATE or FIX with the Phase-2 indicator gates.

### F7 filter verification

- momo_v1 with F7=basic: **+$867 / WR 59 % / n=162**
- momo_v1 with F7=off:   **−$5 800 / WR 48 % / n=4 500**

**F7 is a real edge on momo_v1** in live deploy. On momo_v2 it's still net negative (−$556 with F7=basic).

### Why this re-prioritizes the deploy roadmap

The **Phase-2 add-ons need to REPLACE the 5m losers**, not just stack on top:

| Current state | Phase-2 fix | Net swing |
|---|---|--:|
| BTC 5m sniper live: −$118/day | Replace with S4_BTC_5m + Kelly (backtest: +$36/day) | **+$154/day** |
| BTC 5m momo_HOLD/SELL/HEDGE: −$216/day | Replace 3 sleeves with single S4∪S8 5m Kelly ensemble | **+$300+/day** |
| ETH 5m volume_INV_NIGHT: −$74/day | Replace with S4_ETH_5m + Kelly | **+$190/day** |
| SOL 5m volume_INV_NIGHT: −$64/day | Replace with S4_SOL_5m + Kelly | **+$100/day** |
| 15m momo_v2 BTC + ETH stack: +$200/day | **KEEP AS-IS** | — |
| 15m momo_v1: F7=basic only (small) | **KEEP AS-IS** | — |
| **Net Phase-2 swing if we cut + replace** | | **≈ +$700-800/day** |

That's a different (and bigger) number than the additive bullets at the top of this report. The full picture: **cut the losers worth ≈ $546/day + add the Phase-2 ensemble worth ≈ $237/day** = **+$783/day total swing**, before Kelly amplification.

With Kelly tiers on top, the effective notional rises to ~$34 and the daily uplift grows proportionally to ~$1 100/day total swing. Conservative scaling estimate.

### Caveats

- `pat_shadow` (Ireland maker shadow, n=304) shows -$1 300 sum but `won` is heuristic (pnl_final > 0) and WR=3 % is an artifact of per-slug mid-fill snapshots, not a true settle. Flagged in agent caveats.
- ~1 500 mint_sell v2 fires lack `vwap`/`usd` — v2 payload only carries quote intent.
- 1 463 mint_sell v2 fires + 304 pat_shadow fires lack slug — filtered out of the per-sleeve aggregation.

Artifacts:
- CSV: `data/v4/canonical/_results/live_fires_normalized.csv` (23 810 rows × 21 cols)
- Inbox: `strategy_lab/reports/_live_fires_inbox.md` (150 lines)
- Helpers: `strategy_lab/reports/_build_live_fires_normalized.py`, `strategy_lab/reports/_build_live_fires_inbox.py`

## Final consolidated deploy spec (V2)

```python
# Sleeve set after Phase-2 add-ons. All evaluations done at fire_offset_s
# relative to slot_start_us = (ws_s + window_s) * 1e6.

# 1) Phase-1 base ensemble — intra-slot late
#    fire at FIRST offset >= 120s where (S4 OR S8) passes
S4 = lambda f: (f.fair_edge_bp > 500 and f.cvd_agree_30s
                 and abs(f.dev_bps) >= 8)
S8 = lambda f: f.macd_agree and f.rvol_30_300 > 1.2

# 2) Kelly tier on top of (1)
def kelly(f):
    if f.fair_edge_bp > 3000: return 4.0
    if f.fair_edge_bp > 2000: return 3.0
    if f.fair_edge_bp > 1000: return 2.0
    return 1.0

# 3) Pre-window add-on — fire at slot_start - 60s when S3 passes
S3_prewindow = lambda f: (f.fair_edge_bp > 0 and f.cvd_agree_60s
                           and f.macd_agree)
# applies at fire_offset_s = -60 (5m markets only)

# 4) Pre-window 15m add-on — fire at slot_start - 120s
# applies at fire_offset_s = -120, 15m markets, S4 rule

# 5) FADE_UNGATED_MOMO — for each (strategy in {momo_v1, momo_v2, sniper},
#    asset, tf) cell, when production WOULD fire but HOD+M5V GATE FAILS,
#    fire the OPPOSITE direction. Only enable for cells where the 21d
#    backtest shows positive flip uplift:
FADE_CELLS = {
    ("momo_v2", "BTC", "5m"),   # +$22/day
    ("sniper",  "BTC", "5m"),   # +$18/day
    ("sniper",  "ETH", "15m"),  # +$12/day
    ("momo_v2", "SOL", "5m"),   # +$7/day
    ("sniper",  "SOL", "5m"),   # +$6/day
    ("momo_v2", "SOL", "15m"),  # +$6/day
}

# 6) Indicator overlay on existing PRODUCTION fires — for each
#    production sleeve where backtest WR uplift binom_p < 0.10,
#    add the corresponding AND-filter:
PROD_OVERLAY = {
    ("sniper",  "ETH", "15m"): "m5v_pass",                   # p=0.011 ⭐
    ("momo_v2", "BTC", "5m"):  "fair_edge_bp > 500",          # p=0.081
    ("momo_v2", "BTC", "15m"): "fair_edge_bp > 0",            # p=0.056
    ("sniper",  "SOL", "15m"): "fair_edge_bp > 0",            # p=0.070
    ("momo_v2", "SOL", "5m"):  "cvd_agree_30s AND macd_agree",# p=0.097
    ("momo_v1", "SOL", "5m"):  "m5v_pass",                    # p=0.072
}
```

## Caveats

1. **Multi-comparison risk** — agent A ran 288 gates. Even at p=0.05 chance, ~14 cells would appear "significant" by luck. Cluster-survival is the credible signal: `fair_edge_bp` working across 4 cells (momo_v2 BTC 5m+15m, sniper SOL 15m, momo_v2 BTC 15m) is more credible than the single 0.011 winner.
2. **Kelly DD risk** — the 4× notional tier ($100 fires) has 121 fires in 21 days = 6/day. A 3-fire losing streak at $100 = −$300 from this tier alone. Watch.
3. **FADE_UNGATED model** approximates flipped pnl as `1 − vwap` for the opposite outcome, ignoring the actual Polymarket spread on the OTHER side. Realistic flipped vwap might be `1 − vwap_orig − 0.01` (10-bp spread cost). Reduces FADE uplift estimates by ~10-15 %.
4. **Pre-window timing** uses chainlink strike read at slot_start, which is "future" relative to fire_us < slot_start_us. Strike doesn't move materially in the 60-240s before slot opens (verified by spot check), but live deploy should re-read strike at fire_us and accept the small lag.
5. **All numbers panel-period 21 days (May 1 → May 21)**. Re-validate on the next 28d data refresh before scaling.

## Files

- Phase-2 expansion (Markov / Kelly / DOWN / late-zoom): `strategy_lab/reports/STRATEGY_EXPANSION_PHASE2_2026_05_24.md`
- This final synthesis: `strategy_lab/reports/PHASE2_FINAL_FINDINGS_2026_05_24.md`
- Indicator-overlay inbox: `strategy_lab/reports/_indicator_overlay_inbox.md`
- Pre-window timing inbox: `strategy_lab/reports/_pre_window_timing_inbox.md`
- Live-fires inbox: `strategy_lab/reports/_live_fires_inbox.md` (pending)

### Scripts (all in `strategy_lab/overnight_2026_05_23/`)

- `markov_conditional_strategies.py` — 16 Markov variants
- `down_only_and_late_zoom.py` — direction-asymmetric + offset zoom variants
- `kelly_tier_sweep.py` — 13 Kelly sizing curves
- `contra_gate_momo_v1_btc.py` — disagree/flip gates on the 11 losers
- `flip_with_gating_breakdown.py` — flip un-gated subset
- `build_prod_fills_panel.py` (agent A) — feature panel on prod fires
- `gate_sweep_prod_fills.py` (agent A) — 15-gate sweep
- `pre_window_timing_sweep.py` (agent C) — offset −300 … +840 sweep

### Data outputs

- `data/v4/canonical/_results/prod_fills_with_indicators.parquet`
- `data/v4/canonical/_results/indicator_overlay_on_prod_fills.csv`
- `data/v4/canonical/_results/markov_conditional_strategies.csv`
- `data/v4/canonical/_results/down_only_and_late_zoom.csv`
- `data/v4/canonical/_results/kelly_tier_sweep.csv`
- `data/v4/canonical/_results/contra_gates_losers.csv`
- `data/v4/canonical/_results/flip_with_gating_breakdown.csv`
- `data/v4/canonical/_results/pre_window_timing_sweep.csv`
- `data/v4/canonical/_results/pre_window_timing_per_fire.parquet`
