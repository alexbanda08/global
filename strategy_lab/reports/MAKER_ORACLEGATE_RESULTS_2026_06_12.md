# MAKER ORACLE-GATED QUOTING — b945 final variant — 2026-06-12

_Last variant of the b945 maker thread before parking. Pre-registered, shadow-only._

Runner: `strategy_lab/wallet_hunt/_maker_queue_bt_oraclegate.py`
Output: `strategy_lab/wallet_hunt/cache/_maker_oraclegate_bt.parquet`
Universe: **4,729 btc-updown-15m windows** Apr 22 → Jun 11 (50 days), $1 orders, hold-to-redeem.
Fee/rebate: winner-only 0.07 curve, +0.0015/sh rebate (same as arms A/B/C/D).

---

## Pre-registration (before numbers)

**6 cells = 3 thresholds × 2 fill models**

| Cell | Description |
|---|---|
| E2_fifo | Favorite band [0.55,0.97] + `|rtds_ret5| ≥ $2`, FIFO fill |
| E2_prop | Same gate, proportional fill |
| E5_fifo | Favorite band + `|rtds_ret5| ≥ $5`, FIFO fill |
| E5_prop | Same gate, proportional fill |
| E10_fifo | Favorite band + `|rtds_ret5| ≥ $10`, FIFO fill |
| E10_prop | Same gate, proportional fill |

Gate logic: at quote-join time (t_join = ss+60s), check |rtds_ret5| = |price(t) − price(t−5s)|
from the Chainlink 1Hz RTDS BTC series. If gate OFF → no quote; no cost, no fill, no PnL.
Gate re-checked at each requote (book level change); if gate turns off mid-window, cancel.

Hypothesis (model-D signature): b945 quotes selectively into oracle moves → his fills are
positively selected vs unconditional quoting → positive $/window.

---

## Results

### Per-cell table

| Cell | fired% | n_fired | $/fired window | CI95 | total $ | paired vs arm-B | verdict |
|---|---|---|---|---|---|---|---|
| E2_fifo | 1.4% | 64 | +0.0671 | [−0.0941, +0.2267] | +4.30 | +0.000 | **flat** |
| E2_prop | 8.4% | 397 | +0.0015 | [−0.0317, +0.0333] | +0.58 | −0.002 | **flat** |
| E5_fifo | 0.7% | 33 | +0.1486 | [−0.0611, +0.3477] | +4.90 | +0.000 | **flat** |
| E5_prop | 4.4% | 206 | +0.0141 | [−0.0290, +0.0559] | +2.90 | +0.005 | **flat** |
| E10_fifo | 0.4% | 17 | +0.0623 | [−0.2415, +0.3345] | +1.06 | +0.000 | **flat** |
| E10_prop | 2.0% | 93 | +0.0182 | [−0.0458, +0.0799] | +1.69 | −0.026 | **flat** |

_fired% = fraction of all 4,729 windows where gate was ON AND the book was in the fav band._
_$/fired window = mean PnL conditional on having quoted (gate active)._
_CI95 = 1,000-rep bootstrap on fired-window PnL._
_paired vs arm-B = mean(E_pnl − B_pnl) on fired windows (B_pnl≈0 for most since arm-B fires 19-36% and oracle gate selects a largely non-overlapping subset)._

### Arm-B baseline (ungated, from prior run)

| Fill model | fired% | $/fired window | CI95 | total $ |
|---|---|---|---|---|
| FIFO | 19% | −0.0016 | [−0.0404, +0.0376] | −1.42 |
| prop | 36% | +0.0030 | [−0.0167, +0.0234] | +5.08 |

---

## Paired diff vs arm-B

All paired diffs ≈ 0 (range −0.026 to +0.005). The oracle gate selects a tiny subset
(0.4%–8.4% of windows) that is neither better nor worse than the ungated arm-B on a
per-window basis. The positive $/fired point estimates at higher thresholds (E5_fifo
+0.1486, E2_fifo +0.0671) look encouraging but have CI lower bounds that include 0
(n=33 and n=64 respectively) — insufficient power to conclude positive.

---

## Verdict

**ALL 6 CELLS: FLAT.** No cell has a CI lower bound above 0.

- The oracle gate does filter out adverse windows to some degree (FIFO cells show
  positive point estimates vs arm-B's −0.0016 baseline), but the effect is statistically
  indistinguishable from noise at these sample sizes.
- Higher thresholds (E5, E10) reduce fired% to 0.4–0.7% (17–33 windows) — underpowered;
  CI spans ±0.3. Could only be resolved with ~5,000+ fired windows = years of data.
- The model-D "selective quoting" hypothesis is not REFUTED but also not SUPPORTED:
  the mechanism may exist at his sub-second requote speed and order-of-magnitude larger
  volume, but is undetectable at $1/window scale with 50-day universe and RTDS 1Hz
  resolution (oracle signal is already 1–2s stale by definition of the 1Hz series).

---

## PARK / CONTINUE recommendation

**THREAD PARKED.**

All pre-registered variants have been tested:
- Arm A (faithful join-bid, both sides): SIG-NEG
- Arm B (favorite band, ungated): flat
- Arm C/D (static ladders): SIG-NEG
- Arms E2/E5/E10 (oracle-gated favorite band): flat, underpowered

No variant shows a positive CI lower bound. The mechanic carries no detectable alpha
for us at $1/window scale. b945's edge remains ops + selectivity at 2.4M-share volume —
not accessible offline or at paper-trade stakes.

The maker shadow infrastructure (`_maker_queue_bt.py`, FIFO + proportional bracket) is
a **reusable asset** for future maker ideas; the oracle-gated wrapper pattern is also
banked for re-use.

---

## Artifacts

- `strategy_lab/wallet_hunt/_maker_queue_bt_oraclegate.py` — oracle-gated sim script
- `strategy_lab/wallet_hunt/cache/_maker_oraclegate_bt.parquet` — per-window results (4,729 rows)
- Prior chain: `WALLET_B945945D_ML_DECODE_2026_06_12.md` → `PAIRLOCK_BT_RESULTS_2026_06_12.md` →
  `MAKER_QUEUE_SHADOW_RESULTS_2026_06_12.md` → this
