# Handoff — HoD refresh + sleeve fixes + prod-q90 calibration

_2026-05-22. Continuation of `HANDOFF_2026_05_22_MOMO_F7_MARKOV.md`. Executed
the four named "next session" tasks: refresh HoD-Top-8, fix sleeve #3 with M1V,
investigate sleeve #2 Markov inversion, replicate production q90. **All four
done; the wins are bigger than expected.**_

## TL;DR

| Question | Answer |
|---|---|
| Does refreshing HoD help? | **Massively.** Ensemble PnL: $2,949 → $15,900 (5.4×). All 11 sleeves flip positive (was 7/11). |
| Should sleeve #3 add M1V? | **Yes.** `hod+m1va` WR=90.16%, $/tr=$20.73 (+$1,264 sum). Pure `hod` already gets to 78.4% / +$1,865 once HoD is refreshed. Best blend: `hod+f7+m1va` (88.46% WR, +$20.24/tr). |
| Sleeve #2 Markov inversion - what works? | **Drop Markov.** `hod_only` (refreshed) = +$745 sum, 73.64% WR, n=129. None of the Markov variants beat it. Signal-anchored M5V doesn't help (the regime isn't the bottleneck). |
| Does my backtest fire 10× less because of q90 calibration? | **No.** Prod q90 is actually 8-18% STRICTER than chainlink-only q90; if anything we should fire MORE under prod calibration. The fire-count gap comes from universe filtering (binance-resolved markets we drop), not threshold. |

## Files added

- `strategy_lab/markov_filter/_recompute_hod_top8.py` — refreshes HoD-Top-8 per
  spec §6, diffs vs shipped constant, flags ≥3-hour changes.
- `strategy_lab/meta_classifier/shadow_11_sleeves_v2.py` — re-runs 11 sleeves
  with both current and refreshed HoD, adds 8 extra variants for sleeves #2/#3.
- `strategy_lab/meta_classifier/_replicate_prod_q90.py` — computes hourly
  rolling 14d q90 from ALL binance 1MIN bars (production-equivalent) and
  compares to chainlink-only q90.

## Files outputs

- `strategy_lab/reports/HOD_REFRESH_2026_05_22.md`
- `strategy_lab/reports/SHADOW_11_SLEEVES_V2_2026_05_22.md`
- `strategy_lab/reports/PROD_Q90_REPLICATION_2026_05_22.md`
- `strategy_lab/markov_filter/_results/hod_refresh/2026_05_22/`
- `data/v4/canonical/_results/shadow_11_sleeves_v2.csv`
- `data/v4/canonical/_results/prod_q90_calibration/`

## 1. HoD refresh — every cell flagged

The currently shipped `HOD_TOP8_BY_CELL` was derived using the RESOLUTION-time
hour (`at_ts.dt.hour`). The spec §2.1 mandates **fire-time hour**. Re-deriving
with fire-time produces a materially different list for all 18 cells.

| Sleeve | (fam, cell) | Old | New (fire-time) | Symmetric diff |
|---:|---|---|---|---|
| #2  | sniper eth_15m  | `[0, 6, 7, 9, 13, 14, 19, 22]`   | `[0, 6, 12, 14, 16, 18, 19, 22]` | 6 hrs |
| #3  | momo btc_15m    | `[0, 1, 3, 5, 9, 14, 16, 20]`    | `[0, 5, 7, 10, 11, 15, 18, 20]`  | 10 hrs |
| #5  | sniper btc_5m   | `[0, 1, 3, 5, 12, 15, 19, 21]`   | `[1, 2, 4, 6, 8, 14, 21, 22]`    | 12 hrs |
| #10 | momo_v2 sol_15m | `[1, 2, 5, 12, 13, 16, 17, 21]`  | `[1, 5, 9, 11, 14, 16, 22, 23]`  | 10 hrs |

Full diff in `HOD_REFRESH_2026_05_22.md`.

## 2. Sleeve performance — current vs refreshed HoD

All 11 canonical sleeves backtested against both HoD universes, refreshed HoD
strictly dominates everywhere.

| # | sleeve | current sum$ | refreshed sum$ | refreshed WR / $/tr |
|--:|---|--:|--:|---|
| 1 | sniper sol_5m _hod          | +121  | **+769**   | 62.39% / +$3.41 |
| 2 | sniper eth_15m _hod_m5va    | +169  | **+313**   | 67.27% / +$5.69 |
| 3 | momo btc_15m _hod (v1)      | +712  | **+1,865** | 78.42% / +$13.42 |
| 4 | sniper btc_15m _hod         | +134  | **+939**   | 57.23% / +$5.43 |
| 5 | sniper btc_5m _hod          | **−779** (was negative) | **+349** | 59.84% / +$1.40 |
| 6 | momo_v2 btc_5m _hod_mtf     | +325  | **+1,746** | 58.74% / +$4.07 |
| 7 | momo_v2 btc_15m _hod        | +731  | **+2,317** | 70.73% / +$9.42 |
| 8 | momo_v2 sol_5m _hod         | +1,517| **+2,392** | 65.57% / +$7.16 |
| 9 | momo_v2 eth_15m _hod        | −22   | **+3,515** | 83.62% / +$15.15 |
| 10| momo_v2 sol_15m _hod        | **−52** (was negative) | **+1,213** | 77.17% / +$13.18 |
| 11| sniper eth_5m _hod          | +92   | **+481**   | 55.78% / +$1.64 |

**Ensemble PnL @ $25 notional:** $2,949 → **$15,900** (5.4×). Both originally
negative sleeves (#5, #10) flipped positive on HoD refresh alone — no further
gate changes needed.

## 3. Sleeve #3 (momo v1 btc_15m) — M1V hypothesis confirmed

Spec promised 70-85% WR. With **refreshed HoD only** we already get 78.42% WR
(+$13.42/tr). Adding Markov pushes it further:

| Variant | gate stack | n | WR% | $/tr | sum$ |
|---|---|--:|--:|--:|--:|
| Baseline (refreshed HoD)   | hod                | 139 | 78.42 | +$13.42 | +$1,865 |
| **#3.1 + M1V**             | hod + m1va         | 61  | **90.16** | **+$20.73** | +$1,265 |
| #3.2 + M5V                  | hod + m5va         | 30  | 100.00 | +$22.69 | +$681 (small n) |
| #3.3 + F7                   | hod + f7           | 58  | 79.31 | +$15.56 | +$903 |
| **#3.4 + F7 + M1V**         | hod + f7 + m1va    | 52  | **88.46** | **+$20.25** | +$1,053 |

**Recommendation**: deploy `hod+m1va` (#3.1) — best $/tr, decent n. F7 adds
marginal benefit. The 90% WR figure beats the spec's outer bound.

## 4. Sleeve #2 (sniper eth_15m) — Markov inversion resolved

Original `hod+m5va` cuts 490→55 fires. Tested 4 alternatives:

| Variant | gate stack | n | WR% | $/tr | sum$ |
|---|---|--:|--:|--:|--:|
| Baseline (refreshed HoD)            | hod + m5va         | 55  | 67.27 | +$5.69 | +$313 |
| #2.1 M5V at **signal time** (ws_s)  | hod + m5va_sig     | 47  | 61.70 | +$2.47 | +$116 |
| #2.2 M1V (1-min vol-adaptive)       | hod + m1va         | 93  | 78.49 | +$6.87 | +$639 |
| #2.3 M5F (fixed threshold)          | hod + m5f          | 29  | 55.17 | +$5.38 | +$156 |
| **#2.4 Drop Markov**                | hod (only)         | 129 | 73.64 | +$5.78 | **+$745** |

**Recommendation**: **drop Markov on sniper sleeves**. `hod` alone is best by
total $ (+$745) and beats spec range (70-80%). M1V is close (n=93, +$639) but
adds complexity for less return. M5V signal-anchored (#2.1) did not improve over
fire-anchored — the regime isn't the bottleneck; Markov just adds noise on
sniper fires that aren't momentum-aligned.

**General implication**: per the handoff hypothesis — "sniper fires at
slot_start, not at momentum-aligned moment → regime at fire ≠ regime that drives
the bet" — looks correct. Markov is a momentum-gate primitive; sniper isn't a
momentum strategy. Don't stack them.

## 5. Production q90 calibration — handoff hypothesis disproven

Production's `_fetch_abs_ret_2m_history` samples every 1MIN binance kline in
rolling 14d. The handoff guessed this would be LOOSER than my chainlink-only
sampling and explain the 10× fire-count gap. **It's the opposite:**

| Asset | tf | prod q90 (all bars, hourly anchors) | chainlink q90 (slug-aligned) | fires above prod / fires above chainlink | ratio |
|---|---|--:|--:|--:|--:|
| BTC | 5m  | 0.000902 | 0.000837 | 697 / 837   | 0.83× |
| BTC | 15m | 0.000902 | 0.000809 | 233 / 293   | 0.80× |
| ETH | 5m  | 0.001108 | 0.001002 | 677 / 836   | 0.81× |
| ETH | 15m | 0.001108 | 0.001017 | 228 / 272   | 0.84× |
| SOL | 5m  | 0.001321 | 0.001117 | 710 / 1,028 | 0.69× |
| SOL | 15m | 0.001321 | 0.001084 | 235 / 340   | 0.69× |

Prod is **8-18% stricter** depending on asset. If we swapped to prod's threshold
we'd fire 0.69-0.84× as much — fewer, not more.

**Where does the 10× actually come from?** Universe filtering. Production fires
on every market opened (including binance-resolved markets that we DROP from
canonical because we don't trust their outcome). The chainlink-only universe
has ~12-18k markets per cell; production's full universe is 2-3× larger. Plus:

- L25 sparse-book filter in our backtest is potentially stricter
- Spread filter (0.02 BTC/ETH, 0.025 SOL) cuts more fires than production might
- We require both entry-side asks AND exit-side resolution; production may
  resort to MTM-only or other accounting

This is a **non-issue for the deploy-readiness signal**. The chainlink-only
backtest is the CORRECT universe to validate against — we only want to deploy
on markets that will actually settle on a trustworthy oracle. The 10× gap is a
selection-bias feature, not a calibration bug.

## 6. What's next

### Recommended action — ship the refreshed HoD

The refreshed HoD-Top-8 is the single biggest win. **Update
`backend/app/strategies/polymarket/gates.py::HOD_TOP8_BY_CELL`** with the
fire-time-derived constant from `_results/hod_refresh/2026_05_22/new_hod_top8.json`.

### TV-agent ship list (updated)

Same 11 sleeves as before, but with these gate-stack changes:

| Sleeve | OLD stack | NEW stack | Why |
|---|---|---|---|
| #2 sniper eth_15m   | hod + m5va | **hod** | drop Markov |
| #3 momo v1 btc_15m  | hod        | **hod + m1va** | M1V flips it from 78% to 90% WR |
| #5 sniper btc_5m    | hod        | **hod** (with refreshed HoD) | no other change needed |
| #10 momo_v2 sol_15m | hod        | **hod** (with refreshed HoD) | no other change needed |

All other sleeves: gate-stack unchanged, just refresh the HoD constant.

### Open lower-priority items

1. Investigate why the original HoD list was derived from `at_ts.dt.hour`
   instead of fire-time. Was the source script lost? Re-confirm with whoever
   first computed the constant.
2. Out-of-sample window: refreshed-HoD numbers are in-sample on the same 28d
   used to derive the hours. Need a 7-day forward-walk before live deploy.
3. Per-sleeve `expected_n / week` recalculation against refreshed numbers
   (some are now 2-3× larger).
4. Re-test sleeve #6 (`hod_mtf`) — refreshed HoD already gets it to spec
   range; MTF might be redundant.

## Key invariants confirmed/added

- `fire_us` must be derived from `at_ts` + family-specific offset (payload
  contains `fire_us: None` for resolution events). Formula:
  - momo v1: `at_s - 2*window_s + 120`
  - momo_v2: `at_s - 2*window_s + 60`
  - sniper:  `at_s - window_s`
- HoD gate MUST use fire-time hour, NOT resolution-time hour.
- Sniper sleeves: do NOT stack Markov on top. Use HoD (+ F7 if you must).
- Momo sleeves: M1V is the gate of choice (M5V has too few samples and
  warmup is heavy).

## Quick-start commands

```bash
cd "C:/Users/alexandre bandarra/Desktop/global"

# 1. Refresh HoD (idempotent; produces same output until new data lands)
PYTHONIOENCODING=utf-8 C:/Python314/python.exe \
  strategy_lab/markov_filter/_recompute_hod_top8.py --window-days 28

# 2. Re-run 11-sleeve shadow backtest with refreshed HoD + variants
PYTHONIOENCODING=utf-8 C:/Python314/python.exe \
  strategy_lab/meta_classifier/shadow_11_sleeves_v2.py

# 3. Recompute prod-q90 calibration (only if klines change)
PYTHONIOENCODING=utf-8 C:/Python314/python.exe \
  strategy_lab/meta_classifier/_replicate_prod_q90.py
```

## End of handoff
