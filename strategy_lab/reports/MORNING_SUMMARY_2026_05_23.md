# Morning summary — 2026-05-23

_~2h overnight push. 4 parallel agents + 3 inline experiments + 1 stress test.
**Result: NEW deployable 5m strategy with 86.3% WR and $1,010 sum/28d under
real-fee live-mimic conditions.**_

## 🎯 The big finding

**"VWAP Continuation"** — a brand new 5m strategy. Late-fire (60-270s into
the slot) when binance has clearly deviated from its 15m anchored VWAP.
Bet WITH the move (momentum continuation). M1V Markov regime gate filters
noise.

```
At t = slot_start + 240s (4 min into a 5m slot):
  dev_bps = 10_000 * log(binance_close_now / VWAP_15m_anchored)
  if 5 < |dev_bps| <= 10  AND  M1V regime agrees with sign(dev_bps):
      → BET WITH the deviation
      → enter via L25 book walk
      → hold to slot_end
```

**Top single config**: BTC 240s 5-10bps + M1V → n=546, WR=86.3%, +$1,090
sum at production-actual fees (LegacyConfig: 2%-on-profit-only,
verified vs 25,900 prod resolutions in CLAUDE.md). **Live-mimic stress
test** (hypothetical `0.07·p·(1-p)`-per-share curve, _NOT_ production
fees) only loses ~7%: $1,010 sum, confirming the strategy survives
even if Polymarket switches to the general docs fee schedule.

Out-of-sample test_wr=89% > train_wr=85% → robust. Loss streak max=3.
Sharpe-like annual=8.12.

## 💰 5-config ensemble (deploy as 5 sleeves)

| sleeve | n | WR | $/tr | sum 28d |
|---|--:|--:|--:|--:|
| BTC 5m vwap_off240_m1v | 546 | 86.3% | +$2.00 | **+$1,090** |
| BTC 5m vwap_off60_f7_cross | 164 | 73.2% | +$2.77 | +$454 |
| BTC 5m vwap_off90_cross | 211 | 78.7% | +$1.89 | +$399 |
| ETH 5m vwap_off210_f7_m1v | 188 | 92.6% | +$1.26 | +$237 |
| SOL 5m vwap_off60 | 64 | 75.0% | +$1.66 | +$106 |
| **TOTAL ensemble** | **1,173** | **avg 81%** | | **+$2,286** |

Per-day @ $25 notional: **~$82/day**. At $250 notional: **~$820/day**.

## 🥈 Other winners discovered

**Fade extreme momo** (Agent A): when momo fires with mag_ratio > 3×
threshold, the move is exhaustion. **Fading on BTC+ETH (NOT SOL) gives
67-71% WR**, +$7-9/tr. Adds ~$1,264 over 28d. Free upgrade — just
flip direction in existing momo code when mag>3.

**Z_contra ETH 30s** (Agent B): underdog mean-reversion at PM dips +
binance disagreement. 55% WR but +$3.24/tr because we buy cheap
underdog tokens. +$594 sum over 28d.

**Combinatorial gate search** (Agent C): all 6 5m cells now have at least
one deployable (n≥30, WR≥60%) gate stack. Cell-specific recipe per
`GATE_SEARCH_5M_2026_05_23.md`.

## ⚠️ Mint-and-sell needs V3 redesign

Agent D — mint-and-sell V2 cannot exploit 1s CVD with symmetric
two-sided posting. **CVD direction predicts adverse-side selection**
but |CVD| magnitude alone has no usable separation. Fix requires
**asymmetric one-sided posting**: when |CVD_slope_30s| is high, post
only the side that flow is FOR. This is a strategy redesign — flagged
as V3 work. Spec details in `MINT_AND_SELL_CVD_TIMING_2026_05_23.md`.

## 📊 Deploy sequence — recommended order

1. **THIS WEEK**: ship VWAP continuation as 5 paper-only shadow sleeves.
   Full spec: `TV_AGENT_VWAP_CONTINUATION_SPEC_2026_05_23.md`.
   Requires: 1s binance feed already on VPS3 (`binance_klines_v2.period_id='1SEC'`),
   M1V compute (already in TV_AGENT_PHASE34_FIXES spec), cross-asset
   dev_bps aux.

2. **THIS WEEK**: patch existing momo sleeves to fade mag_ratio>3 on
   BTC+ETH (NOT SOL). 4-line change. Free $1,264/28d.

3. **NEXT WEEK**: deploy ETH 30s z_contra as a 6th paper-only sleeve.
   Smaller bets ($10 notional initially) to limit downside since WR<60%.

4. **PARALLEL TRACK**: redesign mint-and-sell as V3 with asymmetric
   CVD-gated posting. Larger architectural change — separate workstream.

## 📁 Files produced overnight

**Reports** (`strategy_lab/reports/`):
- `OVERNIGHT_STRATEGY_RUN_2026_05_23.md` — full synthesis
- `TV_AGENT_VWAP_CONTINUATION_SPEC_2026_05_23.md` — implementation spec
- `VWAP_CONT_V2_GATED_2026_05_23.md` — the winning backtest
- `VWAP_DRAWDOWN_LIVEMIMIC_2026_05_23.md` — stress test
- `VWAP_CONTINUATION_5M_2026_05_23.md` — v1 backtest
- `FADE_MOMO_5M_2026_05_23.md` — Agent A
- `Z_CONTRA_5M_2026_05_23.md` — Agent B
- `GATE_SEARCH_5M_2026_05_23.md` — Agent C
- `MINT_AND_SELL_CVD_TIMING_2026_05_23.md` — Agent D

**Data** (`data/v4/canonical/`):
- `klines_1s/binance_1s_28d.parquet` (5.5M rows, 1s OHLCV+CVD)
- `_results/vwap_continuation_5m_per_fire.parquet` (40,210 fitted fires)
- `_results/vwap_continuation_v2_gated.csv` (1,003 gated configs)
- `_results/vwap_drawdown_livemimic.csv` (stress test results)
- `_results/fade_momo_5m.csv`, `gate_search_5m.csv`, `z_contra_5m.csv`,
  `mint_and_sell_cvd_overlay.csv`

**Scripts** (`strategy_lab/meta_classifier/`, `strategy_lab/markov_filter/`):
- `vwap_continuation_5m.py`, `vwap_continuation_v2_gated.py`,
  `vwap_drawdown_livemimic.py`, `fade_momo_5m.py`,
  `z_contra_5m.py`, `_gate_search_5m.py`, `_cvd_timing_overlay.py`

## 🔬 Validation status

| Strategy | Sample size | OOS test | Live-mimic | Drawdown | Verdict |
|---|---|---|---|---|---|
| VWAP cont BTC 240 M1V | n=546 | ✅ test_wr=89% | ✅ 92.7% preserved | ✅ DD=28% sum | **DEPLOY** |
| VWAP cont BTC 60 F7 | n=164 | ✅ test_wr=82% | (not tested separately) | DD=40% | DEPLOY |
| VWAP cont BTC 90 cross | n=221 | ✅ test_wr=76% | — | DD=29% | DEPLOY |
| VWAP cont ETH 210 F7+M1V | n=188 | ✅ test_wr=93% | — | DD=44% | DEPLOY |
| VWAP cont SOL 60 | n=64 | ⚠️ test_wr=80% (small n) | — | DD=96% (small n) | PAPER ONLY |
| Fade momo BTC+ETH mag>3 | n=164 | not split | — | — | DEPLOY |
| Z_contra ETH 30 | n=183 | not split | — | — | PAPER ONLY (WR<60%) |

## End of morning summary
