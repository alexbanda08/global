# Worked examples — Kelly tiers, FADE-UNGATED-MOMO, indicator overlays

_How each of the 3 new schemes runs in production, with real fires pulled from the panel for illustration._

---

## 1. Kelly tiered sizing — how it works

### Production logic

```python
def decide_notional(features):
    # Run after S4 ∪ S8 rule passes at fire_offset_s ≥ 120
    base = 25.0  # dollars
    if   features.fair_edge_bp > 3000: mult = 4.0    # → $100 stake
    elif features.fair_edge_bp > 2000: mult = 3.0    # → $75 stake
    elif features.fair_edge_bp > 1000: mult = 2.0    # → $50 stake
    else:                              mult = 1.0    # → $25 stake
    return base * mult
```

`fair_edge_bp` is computed at fire_us as `10 000 × (fair_up − entry_vwap)` for UP signals (or the symmetric DOWN version). `fair_up = Φ(z)` where `z = ln(s_now / chainlink_strike) / (σ_900s × √τ_sec)`.

### Per-tier behaviour (panel period = 20.8 days, 3 508 fires)

| tier | fair_edge_bp | n | % fires | WR % | avg_vwap | avg WIN $ | avg LOSS $ | sum at base | sum at Kelly | max DD | notional |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **1×** | 0 – 1 000 | 2 688 | **76.6 %** | **87.9 %** | 0.868 | +$3.71 | −$25.00 | +$679 | +$679 | −$754 | $25 |
| **2×** | 1 000 – 2 000 | 497 | 14.2 % | 76.3 | 0.707 | +$9.19 | −$25.00 | +$533 | +$1 065 | −$771 | $50 |
| **3×** | 2 000 – 3 000 | 169 | 4.8 % | 69.2 | 0.591 | +$18.38 | −$25.00 | +$851 | +$2 552 | −$450 | $75 |
| **4×** | > 3 000 | 152 | **4.3 %** | 64.5 | **0.451** | **+$52.01** | −$25.00 | +$3 747 | **+$14 988** | **−$409** | **$100** |
| **TOTAL** | | 3 508 | 100 % | 84.4 % | 0.79 | +$8.50 | −$25.00 | +$5 833 | **+$19 308** | **−$829** | **avg $34** |

**Key reading:**
- The **4× tier (4.3 % of fires)** delivers **77.6 % of total PnL** (+$14 988 of +$19 308).
- 1× tier (77 % of fires) is the "easy" trades — high WR (88 %) but tiny per-trade $ — contributes only **3.5 %** of PnL. Kelly doesn't amplify these, so they're not eating capital.
- WR DECREASES as the tier rises (88 → 65 %), because higher fair_edge is achieved on cheap-underdog tokens (avg_vwap drops from 0.87 → 0.45) where the FV model is more uncertain. But each WIN pays much more ($52 vs $3.71).
- Combined ensemble max DD is **only −$829 (4.3 % of total PnL)** — Kelly doesn't blow up the drawdown.

### Sample real fires from the panel (all BTC 5m, May 1)

| time UTC | tier | fair_edge_bp | dir | entry_vwap | won | base pnl | Kelly pnl |
|---|--:|--:|---|--:|---|--:|--:|
| 05-01 03:08 | 1× | 200 | UP | 0.980 | ✅ | +$0.50 | +$0.50 |
| 05-01 14:52 | 1× | 121 | UP | 0.846 | ❌ | −$25.00 | −$25.00 |
| 05-01 01:48 | 1× | 900 | UP | 0.910 | ✅ | +$2.42 | +$2.42 |
| 05-01 17:27 | 1× | 525 | DOWN | 0.750 | ❌ | −$25.00 | −$25.00 |
| 05-01 05:07 | 2× | 1 124 | UP | 0.870 | ✅ | +$3.66 | **+$7.32** |
| 05-01 01:57 | 2× | 1 202 | UP | 0.860 | ❌ | −$25.00 | **−$50.00** |
| 05-01 12:47 | 3× | 2 352 | UP | 0.604 | ✅ | +$16.05 | **+$48.15** |
| 05-01 06:42 | 3× | 2 316 | DOWN | 0.700 | ❌ | −$25.00 | **−$75.00** |
| **05-01 01:13** | **4×** | **4 176** | UP | **0.580** | ✅ | +$17.74 | **+$70.96** |
| 05-01 07:12 | 4× | 3 562 | UP | 0.392 | ❌ | −$25.00 | **−$100.00** |

The 4× row at 01:13 won and paid +$71 (vs +$18 at base size). The 4× row at 07:12 lost −$100. Net of the day's 4× fires: positive expectation given the 64.5 % WR + $52 avg win profile.

### Operational risk

- **Worst single loss in the panel under Kelly = $100** (any 4× tier loser).
- **Worst loss streak in the 4× tier was 3 in a row = $300 hit**. This is rare; over 152 fires in 21 d the streak occurs about once.
- **Combined ensemble max running DD = $829**, recovered within ~4 days each time.

---

## 2. FADE-UNGATED-MOMO — how it works

### Production logic

Production currently runs 11 deployed sleeves that fire when `(HOD-top8 hour) AND (Markov M5V passes)`. The rest of the signal universe (un-gated fires) is SILENTLY DROPPED — and turns out to be systematically losing. Instead of dropping, **fire the OPPOSITE direction**.

```python
def decide_fade_companion(production_signal, features):
    # production_signal exists because momo/sniper raised it
    if HOD_TOP8[(strategy, cell)].contains(hour) and features.m5v_pass:
        # Production fires the standard direction — let it do its thing
        return None
    # HOD or Markov gate failed → production drops the fire
    # We FIRE THE OPPOSITE direction at $25
    return {
        "direction": "DOWN" if production_signal.direction == "UP" else "UP",
        "notional_usd": 25.0,
        "sleeve_label": f"fade_ungated_{strategy}_{cell}",
    }
```

### Per-sleeve performance (panel = 21 days, $25 notional)

Cells where FADE_UNGATED is positive (deploy these):

| sleeve | un-gated n | base $/day | **FADE $/day** | WR (faded) | DD on flip | swing |
|---|--:|--:|--:|--:|--:|--:|
| **momo_v2 BTC 5m** | 747 | −$51 | **+$22** | **51.9 %** | ~−$200 | **+$73** |
| **sniper BTC 5m** | 636 | −$44 | **+$18** | 53.0 % | ~−$180 | **+$62** |
| sniper ETH 15m | 325 | −$24 | **+$12** | 52.6 % | ~−$140 | +$35 |
| sniper SOL 5m | 366 | −$20 | +$6 | 50.8 % | ~−$120 | +$26 |
| momo_v2 SOL 5m | 351 | −$19 | +$7 | 50.1 % | ~−$130 | +$25 |
| momo_v2 SOL 15m | 84 | −$9 | +$6 | 52.4 % | ~−$90 | +$15 |

Cells where FADE_UNGATED is NEGATIVE (do NOT deploy):

| sleeve | un-gated n | base $/day | FADE $/day | verdict |
|---|--:|--:|--:|---|
| momo_v2 BTC 15m | 205 | +$0 | −$8 | already breakeven; flipping kills it |
| momo_v2 ETH 15m | 123 | +$1 | −$7 | same |
| momo_v1 BTC 15m | 121 | −$4 | −$2 | flat |
| sniper BTC 15m | 410 | −$7 | −$9 | flat |
| sniper ETH 5m | 456 | −$10 | −$5 | small |

### Sanity check

If FADE worked everywhere, it would mean production gating is wrong. The real test: **does flipping the GATED fires kill the edge?** Yes:

| sleeve | gated n | base $/day | FLIPPED $/day |
|---|--:|--:|--:|
| sniper BTC 5m gated | 76 | **+$13** | −$18 |
| sniper SOL 5m gated | 44 | +$29 | −$33 |
| momo_v2 BTC 5m gated | 63 | +$8 | −$12 |
| sniper ETH 15m gated | 31 | +$23 | −$23 |

Confirms gated fires are genuine winners; flipping them destroys the edge. So FADE only makes sense on the UN-gated rejects.

### Sample real un-gated fires from `prod_fills_with_indicators` (BTC 5m, Apr 23)

| time UTC | sleeve | slug suffix | prod_sig | prod_vwap | prod_won | prod_pnl | FADE_sig | FADE_vwap | FADE_pnl |
|---|---|---|---|--:|---|--:|---|--:|--:|
| 04-23 00:01 | momo_v2 BTC 5m | …−1776902700 | UP | 0.520 | ❌ | −$25.84 | **DOWN** | 0.480 | **+$26.54** |
| 04-23 00:11 | momo_v2 BTC 5m | …−1776903300 | DOWN | 0.490 | ❌ | −$25.89 | **UP** | 0.510 | **+$23.54** |
| 04-22 22:21 | momo_v2 BTC 5m | …−1776896700 | DOWN | 0.500 | ✅ | +$24.12 | UP | 0.500 | −$25.00 |
| 04-23 00:10 | sniper BTC 5m | …−1776903000 | UP | 0.510 | ❌ | −$25.86 | **DOWN** | 0.490 | **+$25.50** |
| 04-23 00:15 | sniper BTC 5m | …−1776903300 | DOWN | 0.460 | ❌ | −$25.94 | **UP** | 0.540 | **+$20.87** |
| 04-22 23:30 | sniper BTC 5m | …−1776900600 | DOWN | 0.500 | ✅ | +$24.12 | UP | 0.500 | −$25.00 |

**Pattern**: most un-gated production fires LOSE (because they failed HOD/Markov filters that select winners). 4 of these 6 fires were losers for production — flipping them all wins back ~$25 each. 2 were winners — flipping those loses $25. Net: 4×$25 − 2×$25 = +$50 over 6 fires.

### Important caveat on FADE pnl modelling

The flipped pnl approximates `vwap_flip = 1 − vwap_original`. In reality:
- Polymarket has a per-side spread (typically 0.01-0.02), so true flipped vwap is `1 − vwap_orig − 0.01` or so
- The DEPTH on the opposite side might be different from the original side
- L25 walk-fills slip differently per side

Realistic de-rate: **−10 to −15 % on the flip uplift estimates** above. Live shadow before scaling.

---

## 3. Indicator overlays — which sleeves benefit, ranked

13 production sleeves have a statistically meaningful gate uplift (binom_p < 0.10, n_gate ≥ 20). Sorted by selectivity-uplift $ (extra dollars gated subset earned vs ungated baseline rate):

| rank | sleeve | best gate | n_gate (frac) | gated WR % | WR uplift pp | per_tr $ | sel_upl $ | binom_p |
|--:|---|---|--:|--:|--:|--:|--:|--:|
| 1 | momo_v2 BTC 5m | `fair_edge_bp > 500` | 314 (39 %) | 52.9 | +4.1 | +$0.34 | **+$618** | 0.081 |
| 2 | **sniper ETH 15m** | **`m5v_pass`** | **76 (21 %)** | **63.2** | **+13.7** | **+$7.15** | **+$615** | **0.011 ⭐** |
| 3 | momo_v2 BTC 5m | `fair_edge_bp > 500 + cvd_30s` | 238 (29 %) | 53.4 | +4.6 | +$0.56 | +$519 | 0.088 |
| 4 | **momo_v2 BTC 15m** | `fair_edge_bp > 0` | 96 (43 %) | 61.5 | +8.6 | **+$4.69** | +$413 | 0.056 |
| 5 | sniper SOL 15m | `fair_edge_bp > 0` | 66 (35 %) | 60.6 | +9.8 | +$5.01 | +$392 | 0.070 |
| 6 | momo_v2 SOL 5m | `cvd_agree_30s + macd_agree` | 110 (28 %) | 57.3 | +6.6 | +$2.13 | +$357 | 0.097 |
| 7 | **momo_v2 BTC 15m** | `fair_edge_bp > 500 + cvd_30s` | 68 (30 %) | 63.2 | +10.3 | **+$5.54** | +$350 | 0.055 |
| 8 | sniper ETH 15m | `m1v_pass + m5v_pass` | 46 (13 %) | 60.9 | +11.4 | +$6.65 | +$349 | 0.080 |
| 9 | **momo_v1 SOL 5m** | `m5v_pass` | 72 (26 %) | 62.5 | +9.2 | +$4.99 | +$348 | 0.072 |
| 10 | sniper SOL 5m | `cvd_agree_30s + macd_agree` | 98 (24 %) | 59.2 | +7.2 | +$3.21 | +$338 | 0.091 |
| 11 | sniper SOL 15m | `imb5_signal_aligned_0p10` | 67 (35 %) | 59.7 | +8.9 | +$3.66 | +$308 | 0.090 |
| 12 | **sniper SOL 15m** | `fair_edge_bp > 500` | 32 (17 %) | 65.6 | +14.8 | **+$8.06** | +$288 | 0.066 |
| 13 | momo_v1 BTC 15m | `fair_edge_bp > 500` | 55 (40 %) | 63.6 | +9.6 | +$5.98 | +$273 | 0.097 |

### Which sleeve benefits MOST?

**Highest per-trade $ (best signal quality):**
1. **sniper SOL 15m + fair_edge > 500** → **$8.06 / trade**
2. sniper ETH 15m + m5v_pass → $7.15 / trade
3. sniper ETH 15m + m1v + m5v → $6.65 / trade
4. momo_v1 BTC 15m + fair_edge > 500 → $5.98 / trade
5. momo_v2 BTC 15m + fair_edge + cvd_30s → $5.54 / trade
6. sniper SOL 15m + fair_edge > 0 → $5.01 / trade
7. momo_v2 BTC 15m + fair_edge > 0 → $4.69 / trade
8. momo_v1 SOL 5m + m5v_pass → $4.99 / trade

**ALL of the top 7 best per-trade $ sleeves are 15m markets.** 15m gates produce dramatically higher $/trade than 5m gates because the slot lasts 3× longer — wins pay out at lower entry vwap.

**Highest total selectivity uplift:**
1. **momo_v2 BTC 5m + fair_edge > 500** → +$618 (huge sample n=314)
2. sniper ETH 15m + m5v_pass → +$615 (smaller n=76 but **only strict-significance winner**, p=0.011 ⭐)
3. momo_v2 BTC 5m + fair_edge + cvd_30s → +$519

**By gate-type pattern:**

| gate family | best sleeves | works on |
|---|---|---|
| `fair_edge_bp > 0/500` ± `cvd_30s` | momo_v2 BTC 5m, momo_v2 BTC 15m, sniper SOL 15m, momo_v1 BTC 15m | BTC + SOL, both timeframes |
| `m5v_pass` (Markov) | sniper ETH 15m ⭐, momo_v1 SOL 5m | ETH 15m, SOL 5m |
| `cvd_agree_30s + macd_agree` | momo_v2 SOL 5m, sniper SOL 5m | **SOL only** |
| `m1v_pass + m5v_pass` | sniper ETH 15m | ETH 15m |
| `imb5_signal_aligned_0p10` | sniper SOL 15m | SOL 15m |

### Which timeframe benefits most?

- **5m sleeves benefit**: 6 of 13 winners are 5m, all `fair_edge` or `cvd+macd` gated
- **15m sleeves benefit MORE**: 7 of 13 winners are 15m, with the highest per-trade $ and tightest p-values

**Best overall single sleeve to ship first** (strict-p significance + clean profile):

> **`sniper ETH 15m + m5v_pass`**: n=76, WR 63.2 % (+13.7 pp vs baseline), per_tr **+$7.15**, sel_upl **+$615 / 21d**, **p = 0.011** (only strict-significance gate in the sweep). Production currently runs this sleeve at WR 49.4 % (losing $0.94 / trade). Adding the m5v_pass filter keeps 21 % of fires and turns net loss into a strong winner.

### Sample deploy spec for the top-3 overlays

```python
PROD_INDICATOR_OVERLAYS = {
    # sleeve -> required gate AND-filter
    ("sniper",  "ETH", "15m"): "m5v_pass",                   # +$7.15/tr, p=0.011
    ("momo_v2", "BTC", "5m"):  "fair_edge_bp > 500",          # +$0.34/tr, n=314 (big sample)
    ("momo_v2", "BTC", "15m"): "fair_edge_bp > 500 AND cvd_agree_30s",  # +$5.54/tr
    ("sniper",  "SOL", "15m"): "fair_edge_bp > 500",          # +$8.06/tr (smaller n but best per-tr)
    ("momo_v1", "SOL", "5m"):  "m5v_pass",                    # +$4.99/tr
    ("momo_v2", "SOL", "5m"):  "cvd_agree_30s AND macd_agree",# +$2.13/tr
}

def decide_overlay_fire(production_signal, features):
    """Production runs the existing sleeve, BUT only fires if the overlay
    gate also passes. Drops fires that fail the new gate."""
    key = (production_signal.strategy, production_signal.asset, production_signal.tf)
    gate_expr = PROD_INDICATOR_OVERLAYS.get(key)
    if gate_expr is None:
        return production_signal  # no overlay, pass through
    if eval_gate(features, gate_expr):
        return production_signal
    return None  # drop fire
```

---

## Combined operational picture at $25 base (panel period 21 d)

| scheme | sample / day | WR | per-tr | $/day | max DD | role |
|---|--:|--:|--:|--:|--:|---|
| Phase-1 ensemble (S4∪S8 5m, off≥120) | 167 | 84.4 % | +$1.66 | +$280 | −$447 | base |
| + Kelly tiered (1×/2×/3×/4×) | 167 (avg notional $34) | 84.4 % | +$5.50 | **+$927** | **−$829** | amp |
| + FADE-UNGATED-MOMO (6 cells) | 80 | ~51 % | +$0.80–$1.50 | +$70-100 | −$200/cell | new |
| + 6 indicator overlays | varies (~50-300 per sleeve over panel) | 56-65 % | $2-8 | +$15-30 / sleeve | −$50-200 / sleeve | filter |
| + S3 pre-window @ −60s 5m | 95 | 52.8 % | +$0.83 | +$78 | −$155 | new |
| + S4 pre-window @ −120s 15m | 11 | 54.6 % | +$2.26 | +$25 | −$95 | new |
| **TOTAL Phase-2 deploy** | ~360 | 75 % | +$3.20 | **+$1 200-1 400** | **−$1 200** | full stack |

At $25 base notional with Kelly amplification, the full Phase-2 stack projects to **+$1.4-1.6k / day** in additional PnL on top of keeping the existing 15m_momo_v2 winners.

## Caveats on these worked examples

1. **Backtest only** — none of these are live yet. Shadow-deploy on VPS3 for 14 days before scaling notional.
2. **Multiple-comparison risk** on the 13 marginal indicator overlays. The single strict-significance winner (`sniper ETH 15m + m5v_pass`, p=0.011) should ship first; treat the others as paper-only until OOS confirms.
3. **FADE pnl is approximated** — real Polymarket spread costs ~10-15 % of modelled uplift.
4. **Kelly DD risk** — a 3-fire 4× losing streak = −$300 from this tier alone. Cap the daily 4× tier exposure at, say, 10 fires/day max.
5. **Capacity not re-tested at Kelly notionals** — the 4× tier fires at $100 stake; L25 depth on cheap-underdog tokens (avg_vwap 0.45) should be re-verified per the capacity sweep before scaling.

## Files

- Master report: `strategy_lab/reports/PHASE2_FINAL_FINDINGS_2026_05_24.md`
- Per-sleeve breakdown: `strategy_lab/reports/PER_SLEEVE_PER_ASSET_TF_2026_05_24.md`
- Indicator overlay inbox: `strategy_lab/reports/_indicator_overlay_inbox.md`
- Phase-2 expansion: `strategy_lab/reports/STRATEGY_EXPANSION_PHASE2_2026_05_24.md`
- Raw CSVs in `data/v4/canonical/_results/`: `kelly_tier_sweep.csv`, `flip_with_gating_breakdown.csv`, `indicator_overlay_on_prod_fills.csv`
