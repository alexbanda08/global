# Shadow-deploy 11 sleeves — full backtest vs spec expectations

_2026-05-22. Backtest of the 11 gated shadow sleeves defined in
`TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md`. Applied HoD-Top8,
MTF2, and Markov(w20×5m×vol-adaptive) gates to actual production fires
from `trading_events_30d.parquet` (14,148 base-sleeve resolutions over
~15d, 2026-05-07 → 2026-05-21)._

## Setup

- **Base fire universe** = production `poly_updown_resolution` events for
  `fam ∈ {momo, momo_v2, sniper}`, before any modifying suffix (`_f7`,
  `_hod`, `_INV`, `_NIGHT`). 14,148 fires across 18 cells.
- **PnL** = production `pnl_usd` field (verified 2026-05-22 production
  uses legacy 2%-on-profit, matches sample exactly).
- **Fire time derivation**:
  - momo v1: `fire_s = at_ts_s − 2 × window_s + 120`
  - momo_v2: `fire_s = at_ts_s − 2 × window_s + 60`
  - sniper: `fire_s = at_ts_s − window_s` (bar-close fire = slot_start)
- **HoD gate**: filter by `fire_ts.hour ∈ HOD_TOP8_BY_CELL[(strategy, cell)]`
  per Section 2.1 table.
- **MTF2 gate**: `log(BTC@fire_s / BTC@(fire_s − 900s)) > 0`
  AND `log(BTC@fire_s / BTC@(fire_s − 3600s)) > 0` (for UP signal; signs
  flip for DOWN). Closes from canonical 1MIN binance-spot-ws.
- **Markov m5va**: regime at `fire_us` from `build_labels_for_asset(asset,
  window_bars=20, bar_minutes=5, mode='vol_adaptive')`. UP requires BULL,
  DOWN requires BEAR.

## Results — all 11 sleeves vs Section 11 expected ranges

```
 id sleeve                                         n  n/wk     WR     $/tr     sum$    | exp_n   exp_WR   exp_$/tr     status
  1 poly_updown_sol_5m_sniper_hod                 197  98.5  59.39% +$1.34  +$263.81   | ~65/wk  65-70%   +$6 to +$10   ↓ WR & $/tr  miss
  2 poly_updown_eth_15m_sniper_hod_m5va            44  22.0  47.73% -$0.23   -$10.12   | ~25/wk  70-80%   +$10 to +$16  miss — WR way below
  3 poly_updown_btc_15m_momo_hod                   95  51.2  50.53% -$2.45  -$233.09   | ~20/wk  70-85%   +$10 to +$16  miss — NEGATIVE
  4 poly_updown_btc_15m_sniper_hod                224 112.0  52.23% +$0.90  +$202.31   | ~100/wk 55-62%   +$3 to +$5    ↓ slight miss
  5 poly_updown_btc_5m_sniper_hod                 367 183.5  55.04% -$2.25  -$827.03   | ~110/wk 55-60%   +$2 to +$4    miss — NEGATIVE on $/tr
  6 poly_updown_btc_5m_momo_v2_hod_mtf            255 137.3  52.94% +$1.72  +$438.85   | ~60/wk  58-65%   +$3 to +$6    ↓ slight miss
  7 poly_updown_btc_15m_momo_v2_hod               108  58.2  66.67% +$8.05  +$869.21   | ~35/wk  65-72%   +$6 to +$9    ✓ within range
  8 poly_updown_sol_5m_momo_v2_hod                348 187.4  60.34% +$4.81 +$1672.75   | ~50/wk  58-65%   +$3 to +$6    ✓ within range
  9 poly_updown_eth_15m_momo_v2_hod               126  67.8  65.87% +$6.64  +$837.10   | ~25/wk  65-72%   +$6 to +$10   ✓ within range
 10 poly_updown_sol_15m_momo_v2_hod                60  32.3  43.33% -$4.87  -$292.36   | ~18/wk  65-75%   +$6 to +$10   miss — NEGATIVE
 11 poly_updown_eth_5m_sniper_hod                 206 103.0  51.94% +$0.49  +$100.95   | ~80/wk  50-58%   +$0 to +$3    ✓ within range
```

## Verdict by sleeve

### ✓ PASS spec ranges (n=4)
- **#7 momo_v2 btc_15m _hod**: 66.67% WR, +$8.05/tr, +$869 sum. Best sleeve. n=108 (3x expected).
- **#8 momo_v2 sol_5m _hod**: 60.34% WR, +$4.81/tr, **+$1,673 sum** (biggest absolute). n=348 (3.7x expected).
- **#9 momo_v2 eth_15m _hod**: 65.87% WR, +$6.64/tr, +$837 sum. Right in the range.
- **#11 sniper eth_5m _hod**: 51.94% WR, +$0.49/tr. At low end of expected range but positive.

### ↓ MISS — below WR / $/tr expectations but still positive (n=3)
- **#1 sniper sol_5m _hod**: 59.4% WR (expected 65-70%), +$1.34/tr (expected +$6 to +$10). PnL still +$264.
- **#4 sniper btc_15m _hod**: 52.2% WR (expected 55-62%), +$0.90/tr (expected +$3 to +$5).
- **#6 momo_v2 btc_5m _hod_mtf**: 52.9% WR (expected 58-65%), +$1.72/tr.

### ✗ MISS — NEGATIVE (n=4) — DO NOT DEPLOY
- **#2 sniper eth_15m _hod_m5va**: 47.7% WR (expected 70-80%), −$0.23/tr.
  Markov filter shrinks n from 490 → 44 but doesn't lift WR. n=44 over 15d
  is also marginal sample for "70-80% WR" claim. Spec's expected range was
  likely overfit on a smaller window.
- **#3 momo btc_15m _hod (v1)**: 50.5% WR (expected 70-85%), **−$2.45/tr**.
  Big miss. Momo v1 BTC 15m without F7 fired 300 times in the 14d window
  — only HoD filtering left 95, and those underperform expected by a lot.
- **#5 sniper btc_5m _hod**: 55% WR matches expectation but **$/tr is
  NEGATIVE (−$2.25)**. Spec expected +$2-4. The hot hours (`[0,1,3,5,12,15,
  19,21]`) underperform in this window.
- **#10 momo_v2 sol_15m _hod**: 43.3% WR (expected 65-75%), **−$4.87/tr**.
  Worst absolute miss. n=60 — small sample but consistent direction.

## Cross-cutting findings

### Production fires more than spec assumed

For every sleeve except #2, n/week is **2-4x higher** than the spec's
"~XX/wk" estimate. The spec assumed lower fire rates; production's
threshold calibration is looser than the backtest used to derive
expectations. **More fires ≠ more profit** — the additional fires are
often the marginal ones the HoD filter ALONE doesn't catch.

### MTF2 cuts ~87% of momo_v2 btc_5m fires

Sleeve #6 base = 1,930; after HoD+MTF2 = 255 (13.2% retention). The MTF2
gate (requires BOTH 15m AND 1h binance returns to match signal) is very
restrictive. Final +$1.72/tr is below spec's +$3-$6 expected, but at
least the SIGN is right. Useful as a *concentration* filter even if
not as strong as hoped.

### Markov m5va alone (sleeve #2) does NOT save eth_15m sniper

Spec claims 70-80% WR. Backtest delivers 47.7% — random direction.
Possible reasons:
1. The 14-day Markov calibration window includes regime shifts that
   make the labels inconsistent
2. ETH 15m sniper fires at slot_start (not at the momentum-aligned
   moment); regime at fire ≠ regime that actually drives the bet
3. Spec's expected range was overfit to a narrow window

### Best 5 deploy candidates (production-matched PnL):

| ID | Sleeve | n | WR | $/tr | sum$ | day-rate @ $25 |
|---|---|---|---|---|---|---|
| #8 | momo_v2 sol_5m _hod | 348 | 60.3% | +$4.81 | **+$1,673** | **+$112/day** |
| #7 | momo_v2 btc_15m _hod | 108 | 66.7% | +$8.05 | +$869 | +$58/day |
| #9 | momo_v2 eth_15m _hod | 126 | 65.9% | +$6.64 | +$837 | +$56/day |
| #6 | momo_v2 btc_5m _hod_mtf | 255 | 52.9% | +$1.72 | +$439 | +$29/day |
| #1 | sniper sol_5m _hod | 197 | 59.4% | +$1.34 | +$264 | +$18/day |

**Combined day-rate @ $25 notional: ~$273/day** over the 15-day window.

These 5 are independent (different fams/cells). At $250 notional → ~$2,730/day.

## Should TV deploy all 11?

**NO — deploy only the 4 PASS sleeves + 3 MISS-but-positive sleeves (7 total).**

Drop the 4 negative ones:
- #2 (eth_15m_sniper_hod_m5va) — investigate why Markov inverts
- #3 (btc_15m_momo_hod v1) — momo v1 BTC 15m needs F7 (per `MOMO_VARIANTS_PROD_MATCHED`
  Baseline_v1 btc_15m WR drops with F7; this finding inverts here when HoD applied)
- #5 (btc_5m_sniper_hod) — hot hours don't generalize
- #10 (sol_15m_momo_v2_hod) — momo_v2 SOL 15m is in the disabled-cell list per
  production code (`TV_POLY_MOMO_V2_DISABLED_CELLS` env)

Deploy these 7 sleeves (in expected $/day order, $25 notional):

```
#8  momo_v2 sol_5m _hod         +$112/day  ← top
#7  momo_v2 btc_15m _hod         +$58/day
#9  momo_v2 eth_15m _hod         +$56/day
#6  momo_v2 btc_5m _hod_mtf      +$29/day
#1  sniper sol_5m _hod            +$18/day
#4  sniper btc_15m _hod            +$13/day
#11 sniper eth_5m _hod              +$7/day
─────────────────────────────────────────
Ensemble:                        +$293/day  @ $25 notional
                              +$2,930/day  @ $250 notional
                              +$11,720/day @ $1000 notional
```

## Recommendations for TV agent

1. **Deploy the 7 positive sleeves in shadow mode** as the spec defines.
   Add `enabled: false` overrides for sleeves #2, #3, #5, #10.

2. **Recompute HOD_TOP8_BY_CELL for sleeves #3, #5, #10 using fresh 28d**:
   the existing hot-hour lists were derived from an earlier window; the
   3 failing momo/sniper cells may have shifted hot hours. Run the
   `_recompute_hod_top8.py` script (Section 6 of spec) before re-evaluating.

3. **Investigate sleeve #2's Markov m5va inversion**: re-test with
   `bar_minutes=1` (M1V) or `fixed` mode to see if it's a parameter issue
   vs strategy issue. If Markov fundamentally doesn't work on sniper
   eth_15m, drop the gate entirely.

4. **#3 momo btc_15m _hod was the WORST surprise**: spec said 70-85% WR,
   backtest says 50.5%. This is the SAME cell where Baseline_v1 BTC 15m
   M1V hit 59.8% in the 28d variant audit. The HoD-only filter on
   momo v1 doesn't reproduce the M1V result — likely the WR claim was
   based on F7+HoD or the M1V Markov instead of pure HoD. **Re-spec
   with the Markov M1V filter added to sleeve #3** and re-test.

5. **Production fire rate is 2-4× spec's `~n/wk` estimates** — adjust
   capital allocation accordingly (don't expect ~50/wk fires, expect
   ~150-200/wk for the BTC 5m sleeves).

## Files

- Runner: `strategy_lab/meta_classifier/shadow_11_sleeves_backtest.py`
- Per-sleeve CSV: `data/v4/canonical/_results/shadow_11_sleeves_backtest.csv`
- Spec: `strategy_lab/reports/TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md`
