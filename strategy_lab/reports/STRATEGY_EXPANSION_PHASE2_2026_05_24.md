# Phase-2 strategy expansion — Markov / DOWN-only / Kelly tiers

_Continuation of the overnight 5m strategy research (see `OVERNIGHT_NEW_5M_STRATEGIES_2026_05_23.md`). This run tests Markov regime conditioning, direction-asymmetric sleeves, late-offset zoom, and conviction-weighted Kelly sizing. **Headline: conviction-weighted Kelly turns the +$280/day base ensemble into +$926/day at average notional $34 — a 3.3× capital-efficient lift.**_

## TL;DR — DEPLOY ROADMAP

| Tier | Variant | $/day | avg notional | max DD | wf_ret | binom_p |
|---|---|--:|--:|--:|--:|--:|
| 0 baseline | BASE_UNION_5m_off120 | +$280 | $25 | −$447 | 2.72 | 1e−6 |
| 1 conservative | UNION + fair_edge > 0 + Kelly_TIERED | **+$914** | $38 | **−$725** | **3.10** | 2e−6 |
| 2 ✅ headline | BASE_UNION + Kelly_TIERED(1000/2000/3000) | **+$927** | $34 | −$827 | 2.90 | 1e−6 |
| 3 high-conviction | UNION + fair_edge > 500 + Kelly_TIERED | +$911 | $47 | −$786 | 2.62 | 1e−6 |

**Kelly_TIERED schedule** (applied to the BASE union of S8 + S4 with `min_offset_s ≥ 120` and slug-dedup):

```
notional_multiplier = (
    4.0  if fair_edge_bp > 3000  else
    3.0  if fair_edge_bp > 2000  else
    2.0  if fair_edge_bp > 1000  else
    1.0
)
notional = $25 × multiplier
```

## Fair-edge tier breakdown — where the PnL lives

| fair_edge_bp tier | n | fraction | WR % | per_tr $ | sum $ | % of total PnL |
|---|--:|--:|--:|--:|--:|--:|
| ≤ 0 bp | 1 060 | 30 % | **84.8** | $0.20 | +215 | 3.7 % |
| 0 → 500 | 965 | 28 % | **94.4** ⚠ | −$0.02 | −16 | −0.3 % |
| 500 → 1 000 | 663 | 19 % | 83.6 | $0.73 | +481 | 8.2 % |
| 1 000 → 1 500 | 322 | 9 % | 78.9 | $1.09 | +352 | 6.0 % |
| 1 500 → 2 000 | 175 | 5 % | 71.4 | $1.03 | +181 | 3.1 % |
| 2 000 → 3 000 | 169 | 5 % | 69.2 | **$5.03** | +851 | 14.6 % |
| **3 000 → 5 000** | **121** | **3 %** | 66.1 | **$24.10** | **+2 916** | **50.0 %** |
| > 5 000 | 31 | 1 % | 58.1 | **$26.80** | +831 | 14.2 % |

**Key insight: just 4 % of fires (the > 3 000 bp tier) generate 64 % of total PnL.**

- Higher fair_edge ⇒ lower WR (66 % vs 94 %) BUT higher per-trade $ (a winning underdog token at vwap 0.10 pays 9× more than a winning favorite at vwap 0.90).
- The middle tier (0–500 bp) is a *negative-PnL trap* — high WR but the per-trade $ is below the loss-side risk. Drop these fires for a cleaner deploy.
- The < 0 bp tier (model says "no edge") is essentially flat — keeping it doesn't hurt, but it adds noise.

This profile is what makes Kelly so effective: increase exposure exactly where the per-trade $ is highest.

## Headline Kelly result

`BASE_UNION_5m_off120 + K_TIERED_1000_2000_3000`:

| metric | value |
|---|--:|
| Fires | 3 508 |
| Days | 20.8 |
| WR | **84.35 %** |
| Per-trade $ (weighted) | **$5.50** |
| **Sum_$** | **+$19 308** |
| **$/day** | **+$926.60** |
| Avg kelly multiplier | 1.368 |
| **Avg notional** | **$34.2** |
| Max drawdown | −$827 |
| DD as % of sum | **4.3 %** ✓ |
| Walk-forward retention | **2.90** (test 2.9× train) |
| Capital efficiency | **27.1 ¢ / $ deployed / day** |
| Binom p | 1e−6 |

**Capital efficiency**: $0.271/day/$1 of deployed notional, i.e. **27 % daily ROI on capital at this stake schedule** — though that's the inflated raw number that ignores Kelly's strict-fraction theory. Realistic deploy: start at $25 base + 4× cap, scale base as confidence grows.

## Other variants tested — Markov / DOWN / late-offset

### Markov regime overlays — ALL fail to improve BASE_UNION

| variant (5m, off ≥ 120) | n | WR % | $/day | binom_p |
|---|--:|--:|--:|--:|
| BASE_UNION (S4 ∪ S8, no Markov) | 3 508 | 84.35 | **+280** | 1e−6 |
| BASE_S4 only | 1 133 | 78.73 | +168 | 1e−6 |
| BASE_S8 only | 2 812 | 86.77 | +161 | 0.001 |
| M-H2: S8 + M1F (fixed-thr Markov) | 1 409 | 87.01 | +128 | 0.021 |
| M-H: S4 + M1F | 812 | 80.05 | +107 | 3e−5 |
| M-F3: union + asymmetric M1V (BULL→UP / BEAR→DOWN) | 1 439 | 86.94 | +86 | 7e−4 |
| M-G2: S8 + regime-shift (M1V ≠ M5V) | 578 | 86.68 | +84 | 0.108 |
| M-C: S4 + strict regime (regime ∈ {0,1}) | 373 | 78.02 | +78 | 9e−4 |
| M-D: S8 + M1V (vol-adaptive Markov) | 1 218 | 88.42 | +63 | 0.008 |
| M-E: union + M1V AND M5V both pass | 520 | 86.92 | +38 | 0.032 |
| M-A: S4 + M1V AND M5V | 154 | 83.77 | +30 | 0.014 |

**Verdict**: Markov filters CUT sample size more than they improve WR-edge. M1F (fixed threshold) outperforms M1V (vol-adaptive) as a filter (counter-intuitively). The base ensemble already encodes regime implicitly through MACD + dev_bps; explicit Markov filters are subtractive.

### DOWN-only / UP-only / late-offset zoom

| variant (5m, off ≥ 120) | n | WR % | per_tr $ | $/day | max DD |
|---|--:|--:|--:|--:|--:|
| BASE_UNION (all directions) | 3 508 | 84.35 | 1.66 | +280 | −447 |
| U-A: S4 UP-only | 996 | 78.11 | 2.74 | +131 | −375 |
| U-B: S8 UP-only | 1 446 | 85.96 | 1.58 | +110 | −441 |
| **D-A: S4 DOWN-only** | **137** | **83.21** | **$5.57** | +39 | **−$114** |
| D-B: S8 DOWN-only | 1 366 | 87.63 | 0.79 | +52 | −303 |
| D-C: UNION DOWN-only | 1 434 | 87.17 | 0.93 | +64 | −288 |
| **L-A2: S4 off ≥ 240** | 283 | 77.03 | **$5.67** | +77 | −208 |
| L-B2: S8 off ≥ 240 | 812 | **91.87** | 2.80 | +110 | −185 |
| **L-C2: UNION off ≥ 240** | 1 047 | **88.06** | 3.27 | +165 | −215 |
| L-D2: S4 DOWN-only + off ≥ 240 | 30 | 73.33 | **$11.84** | +21 | −76 |

- **DOWN-only sleeves have HIGHER per-trade** (S4 DOWN: $5.57/tr) but lower volume — UP fires more often.
- **Late offset (≥ 240 s)** further raises WR to 91.9 % (S8) and per-trade to $5.67 (S4) but cuts fires by ~70 %.
- L-D2 (S4 + DOWN + off ≥ 240) achieves **$11.84/tr**, the highest per-trade of any variant — but n = 30 is too small to deploy alone.

These don't beat the Kelly-on-conviction approach in $/day, but they're orthogonal: **stacking Kelly + DOWN bias = K_FAIR_AND_DOWN**, see below.

### Kelly schedules — full sweep

| variant | n | avg kelly | avg notional | per_tr | sum $ | $/day | max DD | dd % of sum | wf_ret |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| BASE (1×) | 3 508 | 1.000 | $25.0 | 1.66 | 5 833 | +280 | −447 | 7.7 % | 2.72 |
| K1.5 at fair_edge > 500 | 3 508 | 1.211 | $30.3 | 2.46 | 8 638 | +415 | −632 | 7.3 % | 2.58 |
| K2 at 1 000 | 3 508 | 1.233 | $30.8 | 3.13 | 10 963 | +526 | −763 | 7.0 % | 2.83 |
| K2 at 1 500 | 3 508 | 1.141 | $28.5 | 3.03 | 10 612 | +509 | −611 | 5.8 % | 2.51 |
| K3 at 1 500 | 3 508 | 1.283 | $32.1 | 4.39 | 15 390 | +739 | −788 | 5.1 % | 2.44 |
| K3 at 2 000 | 3 508 | 1.183 | $29.6 | 4.28 | 15 028 | +721 | **−567** | **3.8 %** | 2.56 |
| K_TIERED 500/1500 (1×/2×/3×) | 3 508 | 1.564 | $39.1 | 4.63 | 16 223 | +779 | −985 | 6.1 % | 2.44 |
| **K_TIERED 1000/2000/3000 (1/2/3/4×)** ⭐ | 3 508 | 1.368 | $34.2 | **5.50** | **19 308** | **+927** | −827 | 4.3 % | **2.90** |
| K_TIERED 1000/2500 (1/2/4×) | 3 508 | 1.359 | $34.0 | 5.44 | 19 070 | +915 | −847 | 4.4 % | 2.77 |
| K_FAIR_AND_DOWN (K2 at fair>1000 × K1.5 at DOWN) | 3 508 | 1.448 | $36.2 | 3.41 | 11 976 | +575 | −768 | 6.4 % | 2.40 |
| K1.5 DOWN | 3 508 | 1.204 | $30.1 | 1.85 | 6 502 | +312 | −481 | 7.4 % | 2.29 |
| K2 DOWN | 3 508 | 1.409 | $35.2 | 2.04 | 7 171 | +344 | −597 | 8.3 % | 2.01 |

**Best: K_TIERED 1000/2000/3000** — combines high-conviction concentration with manageable max DD.

## Filter-then-Kelly comparison

What happens when we add a `fair_edge_bp > X` floor as a FIRE filter (drops zero/negative-edge fires) before applying Kelly:

| variant | n | per_tr | sum $ | $/day | max DD | dd % | wf_ret | avg notional |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| BASE_UNION (no filter) | 3 508 | $1.66 | 5 833 | +280 | −447 | 7.7 | 2.72 | $25 |
| UNION + fair_edge > 0 | 2 498 | $2.21 | 5 529 | +266 | −321 | 5.8 | 2.73 | $25 |
| UNION + fair_edge > 500 | 1 494 | $3.72 | 5 559 | +267 | −381 | 6.9 | 2.06 | $25 |
| BASE + K_TIERED | 3 508 | $5.50 | 19 308 | **+927** | −827 | 4.3 | 2.90 | $34 |
| **UNION+fe>0 + K_TIERED** | 2 498 | $7.62 | 19 023 | +914 | **−725** | **3.8** | **3.10** | $38 |
| UNION+fe>500 + K_TIERED | 1 494 | **$12.67** | 18 928 | +911 | −786 | 4.2 | 2.62 | $47 |

**`UNION + fair_edge > 0 + K_TIERED` is the cleanest deploy**:
- 29 % fewer fires than BASE (drops 1 010 zero/negative-edge fires)
- 99 % of base PnL preserved (−$13 of $927 lost)
- Best DD as % of sum (3.8 %)
- Best walk-forward retention (3.10 — test sum 3.1× train sum)
- $/day virtually identical at $914

If you want to deploy fewer trades (operational simplicity, less capacity risk), use the `fair_edge > 500` floor — 1 494 fires for $911/day at $12.67 per trade.

## Production deploy spec (Tier 2 / headline)

```python
# Fire-decision pseudocode at fire_offset_s = 120 ... 270 into a 5m slot
# (evaluate at each offset, fire the FIRST match per (asset, slug, direction))

def decide_fire(features):
    # Rule S8 — MACD agree + RVOL elevated
    s8 = features.macd_agree and (features.rvol_30_300 > 1.2)

    # Rule S4 — Black-Scholes fair-value strong + 1s CVD agree + dev_bps ≥ 8
    s4 = (
        features.fair_edge_bp > 500
        and features.cvd_agree_30s
        and abs(features.dev_bps) >= 8
    )

    if not (s8 or s4):
        return None

    # OPTIONAL: drop zero / negative-edge fires (cleaner DD)
    # if features.fair_edge_bp <= 0:
    #     return None

    # Conviction-weighted Kelly sizing on top of base $25
    if   features.fair_edge_bp > 3000: mult = 4.0
    elif features.fair_edge_bp > 2000: mult = 3.0
    elif features.fair_edge_bp > 1000: mult = 2.0
    else:                              mult = 1.0
    notional = 25.0 * mult

    return {"asset": features.asset, "slug": features.slug,
             "direction": "UP" if features.dev_bps > 0 else "DOWN",
             "notional_usd": notional,
             "rule": "S4" if s4 else "S8"}
```

Wire-up additions (vs the Phase-1 S8+S4 deploy):
- Already-published features: `macd_hist`, `rvol_30_300`, `cvd_30s`, `dev_bps`, `vwap_15m_anchored`, `chainlink_strike_at_slot_start`, `sigma_per_sqrt_sec_15m`
- New gate output: `fair_edge_bp = 10_000 × (fair_up − entry_vwap)` if UP signal, else `× ((1 − fair_up) − entry_vwap)`
- New sizing output: `notional_usd` per the multiplier table above

## Caveats

1. **The 3 000–5 000 bp tier (50 % of PnL) is 121 fires over 20.8 days = 5.8 fires/day**. Per-trade $24 expected. If a single fire goes wrong at 4× notional ($100), the loss is $100 — within DD tolerance, but a streak of 3 in a row would be $300 against $24×5×5 = $600 baseline. Watch.
2. **Capacity at 4× notional ($100)** has NOT been re-tested vs the L25 capacity sweep. From CAPACITY_SWEEP_GATED_SLEEVES_2026_05_22, the 11-sleeve practical max was $25–$1000 depending on cell. At $100 with low-vwap underdog tokens, slippage is manageable, BUT the L25 ceiling on the 3 000–5 000 bp tier (cheap-token entries) needs verification.
3. **Walk-forward 2.90× is partially driven by recent fold tail**: from the per-week breakdown last night, week 21 contributed ~$4 000 of $6 800 in BASE. Kelly amplifies that. Re-validate in 7 days.
4. **The negative-edge fires (fair_edge ≤ 0)** contribute +3.7 % of PnL despite the model saying "no edge". Either the FV model is mis-calibrated for those fires (most likely small-tau, small-σ noise) or there's a signal mode we don't understand. Worth a deeper look if shadow shows drift.
5. **Markov filters underperform** likely because the production fills.csv already had Markov gates applied (m5v_voladaptive flags) — our base feature is already "Markov-aware" implicitly through S8 + dev_bps signal alignment.

## Files

- Runner (Markov-conditional): [strategy_lab/overnight_2026_05_23/markov_conditional_strategies.py](strategy_lab/overnight_2026_05_23/markov_conditional_strategies.py)
- Runner (DOWN-only + late-zoom + asymmetric Kelly): [strategy_lab/overnight_2026_05_23/down_only_and_late_zoom.py](strategy_lab/overnight_2026_05_23/down_only_and_late_zoom.py)
- Runner (Kelly tier sweep): [strategy_lab/overnight_2026_05_23/kelly_tier_sweep.py](strategy_lab/overnight_2026_05_23/kelly_tier_sweep.py)
- CSV outputs:
  - `data/v4/canonical/_results/markov_conditional_strategies.csv` (32 configs)
  - `data/v4/canonical/_results/down_only_and_late_zoom.csv` (25 configs)
  - `data/v4/canonical/_results/kelly_tier_sweep.csv` (13 sizing curves)

## Pending (3 agents still running)

1. **Live-fires analyst** — pulling shadow + production `trading_events_30d.parquet` (~173k rows) to normalize live fires + report realized per-sleeve PnL.
2. **Indicator-overlay analyst** — building feature panel ON the production `fills.csv` (different fire timings than my offset-grid panel) to test if MACD/CVD/FV gates lift the production momo/sniper sleeves.
3. **Timing-sweep analyst** — pre-window timing sweep at offsets `-300 … +270 s` for 5m, `-840 … +840 s` for 15m, testing whether firing S4/S8 BEFORE the slot opens gives higher per-trade $.

These will inform the next iteration. Will append findings to this report as inboxes land at `strategy_lab/reports/_*_inbox.md`.
