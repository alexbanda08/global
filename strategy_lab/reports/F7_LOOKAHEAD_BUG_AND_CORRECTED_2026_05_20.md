# F7 RSI anchor lookahead bug — analysis-script only

_2026-05-20. Originally I concluded the live F7 deploy was lookahead-biased; that
was WRONG — production shadow PnL is real (chainlink fills). The bug is only in
the POST-HOC analysis script `momo_12cells_f7.py` which anchors RSI at slot_end._

**CORRECTION 2026-05-21**: live VPS3 F7 sleeves DO show +$1.75/trade momo+F7
lift (51% WR, +$2,137 over 23.5h, per `PER_STRATEGY_FAMILY_GATE_COMPARE_2026_05_21.md`).
This is REAL — chainlink-resolved fills can't be lookahead-biased. The previous
agent's bug only affects the analysis-script's re-scoring of past trades; it does
not affect live deployment. The 24 `_f7` sleeves on VPS3 are likely fine.

What I could NOT verify (and should): which anchor the LIVE controller actually
uses for its RSI sample at fire time. Canonical klines end 2026-05-19 23:35;
F7 sleeves were deployed 2026-05-20 19:57. So my klines are 21h behind the
F7 window — I can't compute RSI at the live fire times to match against the
live `is_f7` flags. Recommended next step: pull fresh canonical klines AND the
fresh trading_events that include `poly_updown_signal` events from the F7
sleeves (which should write the live `rsi_14` in payload at fire time). Then
match my recomputed RSI against the live value to confirm the anchor.

## The bug

`strategy_lab/meta_classifier/momo_12cells_f7.py` lines 36-37:

```python
df["at_ts"] = pd.to_datetime(df["at"], utc=True)
df["ws_s"] = (df.at_ts.astype("int64") // 1_000_000_000)
```

The column is **named** `ws_s` but is actually computed from the resolution
event's `at` field. For `poly_updown_resolution` events, `at` is when the
resolution event was emitted = **slot_end** (= slot_start + window_s).

Then in `attach_rsi()` (lines 56-71), RSI(14) is sampled at this "ws_s" which
is really slot_end. **RSI captures momentum during the 14 minutes BEFORE
slot_end** — which is INSIDE the bet window for 15m markets, and after slot_start
in all cases. The 14-min window covers the period when the chainlink oracle's
strike → settlement comparison was determined.

**This is forward-looking by `window_s + ~120s` minutes** for fires that happened
at `ws_s + 120` (production v1/v2 anchor).

## Proof — VPS3 shadow trades, all 12 cells

Same shadow events scored under 3 anchor choices:

| Anchor | Causal? | Distance from fire |
|---|---|---|
| `ws_s = slot_start − window_s` | ✓ CAUSAL | RSI 2 min before fire |
| `slot_start = slug_suffix` | × (post-fire) | RSI window_s−120s after fire |
| `slot_end = slot_start + window_s` | × **LOOKAHEAD** | RSI 2×window_s − 120s after fire |

```
v   cell      anchor         n    wins   WR     PnL_sum   $/trade
v1  btc_15m   ALL          210   137   65.2%  +$1334    +$6.35
v1  btc_15m   F7@ws_s      122    66   54.1%   +$228    +$1.87
v1  btc_15m   F7@slot_start 127   71   55.9%   +$387    +$3.05
v1  btc_15m   F7@slot_end  131   106   80.9%  +$1764   +$13.46  ← LOOKAHEAD

v1  eth_15m   ALL          192    73   38.0%   -$1071   -$5.58
v1  eth_15m   F7@ws_s      126    39   31.0%   -$1349  -$10.71
v1  eth_15m   F7@slot_start 130   54   41.5%    -$659   -$5.07
v1  eth_15m   F7@slot_end   74    67   90.5%  +$1344  +$18.16  ← LOOKAHEAD

v1  sol_15m   ALL          191    91   47.6%    -$554   -$2.90
v1  sol_15m   F7@ws_s      111    63   56.8%    +$193   +$1.74
v1  sol_15m   F7@slot_start 120   62   51.7%     -$89   -$0.74
v1  sol_15m   F7@slot_end   70    69   98.6%  +$1422  +$20.32  ← LOOKAHEAD (n=70 → 69 wins is near-perfect)

v2  btc_15m   ALL          300   179   59.7%  +$1563    +$5.21
v2  btc_15m   F7@ws_s      221   141   63.8%  +$1426    +$6.45
v2  btc_15m   F7@slot_start 159   90   56.6%    +$768   +$4.83
v2  btc_15m   F7@slot_end  176   158   89.8%  +$2984  +$16.95  ← LOOKAHEAD

v2  eth_15m   ALL          272   182   66.9%  +$1878    +$6.90
v2  eth_15m   F7@ws_s      185   120   64.9%  +$1210    +$6.54
v2  eth_15m   F7@slot_start  97   52   53.6%    +$168   +$1.73
v2  eth_15m   F7@slot_end  136   122   89.7%  +$2315  +$17.02  ← LOOKAHEAD
```

`F7@slot_end` reproduces the +$3.6k/day production claim. `F7@ws_s` doesn't.
The 98.6% WR on v1 sol_15m (69/70 wins) is the smoking gun — that's not
predictive power, that's seeing the answer.

## What F7 actually does (causal, ws_s anchor)

Two effects when applied properly:

1. **Cuts ~50% of fires** across the board (n drops 30-50%)
2. **WR effect is small and inconsistent**:

| cell | v1 baseline WR | v1 F7@ws_s WR | Δ |
|---|---|---|---|
| btc_15m | 65.2% | 54.1% | **−11.1pp** ← hurts |
| btc_5m | 46.1% | 44.0% | −2.1pp |
| eth_15m | 38.0% | 31.0% | −7.0pp |
| eth_5m | 47.1% | 49.6% | **+2.5pp** |
| sol_15m | 47.6% | **56.8%** | **+9.2pp** |
| sol_5m | 52.8% | 52.6% | −0.2pp |

| cell | v2 baseline WR | v2 F7@ws_s WR | Δ |
|---|---|---|---|
| btc_15m | 59.7% | **63.8%** | **+4.1pp** |
| btc_5m | 46.4% | 45.9% | −0.5pp |
| eth_15m | 66.9% | 64.9% | −2.0pp |
| eth_5m | 45.0% | **48.1%** | **+3.1pp** |
| sol_15m | 47.0% | 45.9% | −1.1pp |
| sol_5m | 50.2% | 49.6% | −0.6pp |

F7 helps **3-4 cells out of 12**, hurts as many. Net aggregate lift is ~$0/trade
on VPS3 shadow data when properly anchored.

## Corrected variants backtest (canonical L25, real PMXT fees)

Rerunning the 5 variants × 6 cells × 3 F7 states with the fixed RSI anchor:

### Aggregate

```
variant                            F7     n     WR   leg_tot  real_tot   leg/tr  real/tr
2A_late_fire_late_signal          ALL  1933  47.6% $-3173.20 $-4393.04 $-1.6416 $-2.2727
2A_late_fire_late_signal           F7   935  46.3% $-1626.40 $-2231.71 $-1.7395 $-2.3869
2A_late_fire_late_signal          F7x   571  46.8% $ -744.88 $-1116.00 $-1.3045 $-1.9545
2B_late_fire_early_signal         ALL  1838  48.2% $-2058.53 $-3220.98 $-1.1200 $-1.7524
2B_late_fire_early_signal          F7   987  44.7% $-2316.09 $-2966.82 $-2.3466 $-3.0059
2B_late_fire_early_signal         F7x   601  44.3% $-1395.52 $-1795.39 $-2.3220 $-2.9873
2C_edge_of_slot                   ALL  2035  48.0% $-2900.64 $-4183.46 $-1.4254 $-2.0558
2C_edge_of_slot                    F7   992  45.8% $-1690.96 $-2339.54 $-1.7046 $-2.3584
2C_edge_of_slot                   F7x   585  43.8% $-1373.09 $-1765.80 $-2.3472 $-3.0185
Baseline_v1                       ALL  1734  48.1% $-2499.71 $-3593.51 $-1.4416 $-2.0724
Baseline_v1                        F7   950  44.4% $-2723.51 $-3347.20 $-2.8669 $-3.5234
Baseline_v1                       F7x   589  43.3% $-1911.66 $-2303.61 $-3.2456 $-3.9110
Baseline_v2                       ALL  2147  49.1% $-2148.85 $-3488.76 $-1.0009 $-1.6249
Baseline_v2                        F7  1342  47.6% $-1893.45 $-2747.79 $-1.4109 $-2.0475
Baseline_v2                       F7x   913  47.8% $-1062.47 $-1644.96 $-1.1637 $-1.8017
```

**F7 (causal) makes things WORSE per-trade for most variants**:
- Baseline_v1: ALL=−$1.44/tr → F7=−$2.87/tr (cuts 45% of fires AND worsens survivors)
- Baseline_v2: ALL=−$1.00/tr → F7=−$1.41/tr (mild worsening)
- 2A: ALL=−$1.64/tr → F7=−$1.74/tr
- 2B: ALL=−$1.12/tr → F7=−$2.35/tr (significantly worsens)
- 2C: ALL=−$1.43/tr → F7=−$1.70/tr

The aggregate per-trade improvement from F7 in my PREVIOUS (buggy) run was an
artifact of post-signal mean-reversion sampling. With correct ws_s anchor, F7
LOSES alpha.

### Profit pockets (still real after fix)

| variant | cell | F7 | n | WR | real/tr |
|---|---|---|---|---|---|
| **Baseline_v1** | **btc_15m** | **ALL** | 131 | **58.0%** | **+$2.91** ← top |
| 2B late/early | btc_15m | F7x | 62 | 54.8% | +$3.22 |
| 2B late/early | btc_15m | F7 | 99 | 53.5% | +$2.26 |
| 2A late/late | eth_15m | F7x | 34 | 58.8% | **+$5.77** |
| 2A late/late | eth_15m | F7 | 50 | 52.0% | +$1.83 |
| Baseline_v1 | btc_15m | F7x | 45 | 53.3% | +$1.30 |
| 2A late/late | sol_15m | F7x | 25 | 56.0% | +$1.49 |
| 2B late/early | btc_15m | ALL | 201 | 53.7% | +$1.48 |
| Baseline_v1 | sol_15m | F7 | 22 | **54.5%** | +$0.99 |
| 2B late/early | sol_15m | F7x | 17 | 52.9% | +$0.96 |
| Baseline_v2 | btc_15m | F7 | 123 | 52.0% | +$0.07 |

**Critical observation**: Baseline_v1 btc_15m **ALL** (no F7) remains the best
single bucket at +$2.91/trade. Applying F7 to this cell DROPS WR from 58% to
49% — F7 hurts the most reliable production cell.

## Why production saw +$3.6k/day F7 lift

Three concurrent biases in the production calc:
1. **F7 RSI anchored at slot_end** (forward-looking by window_s + 120s)
2. **Mode = paper** in shadow — uses REST-stale book at fill time (gives favorable
   entry prices that don't survive WS truth)
3. **Aggregating across all sleeves** including the cells where lookahead F7 hits
   90%+ WR (eth_15m, sol_15m, v2 cells)

Once you fix (1) — which is just changing one variable in `momo_12cells_f7.py`
from `at_ts` to `ws_s = at_ts − window_s` — the aggregate F7 effect collapses
to ~zero or slightly negative.

## Files

- Fix: `strategy_lab/meta_classifier/momo_variants_2abc.py:148` — `compute_rsi_14_at`
  now takes `anchor_s` and requires bar end within 5 min (stale-kline guard)
- Verifier: `strategy_lab/meta_classifier/_verify_f7_anchor.py` — replays VPS3
  shadow trades under 3 anchor choices side-by-side
- Verifier log: `data/v4/canonical/_results/_f7_anchor_verify.log`
- Corrected variants per-trade: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_trade.parquet`
- Corrected variants log: `data/v4/canonical/_results/_momo_variants_2abc_v3_f7fix_run.log`

## Implications

1. **`momo_12cells_f7.py` should be patched** to anchor RSI at `ws_s = at_ts − window_s`,
   not at `at_ts`. The +$3.6k/day production claim must be re-validated under the corrected anchor.

2. **F7 deployed sleeves on VPS3** (24 `_f7` sleeves since 2026-05-20 19:57 UTC per
   `F7_AND_RESIDUAL_FIX_VERIFICATION_2026_05_21.md`) need re-verification. If
   production's F7 logic uses the same lookahead anchor (RSI at slot_end), then
   the live deployed F7 doesn't have predictive value — production will look
   profitable on shadow PnL (because shadow is computed post-resolution with the
   same lookahead) but won't survive live fills.

3. **Investigate the live VPS3 F7 controller code path** (not the analysis code).
   If the F7 RSI is sampled at fire time using a CAUSAL clock (e.g. binance WS
   latest minute close at fire_us), then live F7 has the proper anchor and the
   lookahead bug is only in the post-hoc analysis (not in production decision-making).
   If the live controller uses the resolution-event RSI lookup, the live F7 is
   meaningless.

4. **Don't deploy 2A/2B/2C variants with F7**. Causal F7 makes them worse, not better.

5. **Baseline_v1 BTC 15m ALL (no F7)** remains the single best deploy candidate:
   n=131 over 26d, WR=58%, real PnL +$2.91/trade. At ~5 fires/day × $25 notional
   ≈ +$15/day. At $250 notional ≈ +$150/day.
