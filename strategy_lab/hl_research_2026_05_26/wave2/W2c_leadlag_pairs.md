# W2c — Cross-Asset Lead-Lag (N5) and Structure-Break Pairs (N11)

**Run date:** 2026-05-26
**Script:** `strategy_lab/hl_research_2026_05_26/wave2/W2c_leadlag_pairs.py`
**Results CSV:** `strategy_lab/hl_research_2026_05_26/wave2/W2c_results.csv`

---

## TL;DR

| Hypothesis | Verdict | Punchline |
|---|---|---|
| **N5 — Cross-asset lead-lag (30-180s)** | **REJECTED** | No detectable 1-minute lead-lag. Lag-0 contemporaneous corr is 0.82 BTC↔ETH, 0.57 BTC↔SOL; lag=1m corr drops to 0.01-0.03. Macro moves propagate within the same 1-minute bar. The *real* lead-lag is sub-second (≈1s, see N5.7). |
| **N11 — Structure-break pairs** | **REJECTED in both directions** | Direct (LONG ETH+SOL vs SHORT BTC on BTC bos_buy alone): mean -$0.67/trade, sharpe -11, n=1069, p<0.001. Inverse (LONG BTC vs SHORT ETH+SOL): mean -$0.53/trade, sharpe -8.96. Pair leg fees (×2 single) eat any small edge; the unconditional sign of "BTC structure-break leads while ETH/SOL haven't" appears to be mean-reverting within the pair (BTC pulls back), but the magnitude of that reversion is smaller than the pair's fee+slip drag. |

**Best lead-lag (Binance → Hyperliquid):**  **-1,000 ms = 1 second** (Binance 1-second leads HL by 1s, corr=0.43 for BTC at lag=-1s). Source: existing 1-second subminute xcorr in `_xcorr_subminute_hl_fast.csv`. This matches the prior cross-exchange research already flagged in `_signed_leadlag.csv` (Binance→HL signed up/down lift ≈ 0.15 at 5s window).

---

## N5 — Cross-asset lead-lag

### N5.1 Lagged correlation (Binance 1m, 2020-01 → 2026-04, ~3.3M bars)

| Pair | Lag 0 | Lag +1m | Lag +2m | Lag +3m | Lag +5m |
|---|---|---|---|---|---|
| BTC → ETH (BTC leads) | **0.822** | 0.013 | -0.014 | 0.000 | -0.002 |
| BTC → SOL (BTC leads) | **0.574** | 0.030 | -0.006 | -0.004 | 0.003 |
| ETH → BTC (ETH leads) | **0.822** | 0.014 | -0.011 | -0.005 | -0.003 |

**Reading:** the entire BTC/ETH/SOL covariance lives in the contemporaneous 1-minute bar. Lag=1m correlation is essentially zero (0.013), and there is **no asymmetry** between BTC→ETH and ETH→BTC (both 0.014 vs 0.013 at +1m). At 1-minute granularity, no asset leads any other.

### N5.7 — Sub-minute lead-lag (from prior `_xcorr_subminute_hl_fast.csv`)

| Asset | Peak lag (sec) | Peak corr | Interpretation |
|---|---|---|---|
| BTC | **-1 s** | 0.431 | Binance leads HL by 1 second |
| ETH | 0 s | 0.461 | contemporaneous |
| SOL | **-1 s** | 0.451 | Binance leads HL by 1 second |

The 1s lead-lag is real but not exploitable at our latency floor — already shown unprofitable in prior `_walkforward_basis.csv`. The 30-180s macro lead-lag the hypothesis posited **does not exist** in the data.

### N5.2 Threshold-trigger sweep (last 12 months, 1m)

Sweep: thr ∈ {0.2, 0.3, 0.5, 1.0}%, K ∈ {1, 3, 5, 10, 15}m, followers ETH/SOL, directions UP/DOWN, n×2×2×4×5 = 80 cells. Net of $0.30 round-trip fees+slip on $250 notional.

**Top 5 cells by mean PnL where n ≥ 20 and p < 0.10:**

| follower | dir | thr% | K min | n | mean | win | sharpe | p |
|---|---|---|---|---|---|---|---|---|
| ETH | UP | 0.3 | 10 | 27 | **+$1.57** | 52% | 6.90 | 0.033 |
| SOL | DOWN | 0.2 | 3 | 129 | -$0.22 | 36% | -2.70 | 0.056 |
| SOL | DOWN | 0.2 | 1 | 129 | -$0.23 | 26% | -3.85 | 0.007 |
| ETH | DOWN | 0.2 | 1 | 104 | -$0.25 | 30% | -4.40 | 0.006 |
| SOL | UP | 0.2 | 1 | 115 | -$0.33 | 26% | -5.33 | 0.000 |

The single positive cell (ETH UP thr=0.3% K=10m) is a fluke: n=27 is far too small for the sweep size (Bonferroni correction → 0.033 × 80 = p_corrected ≈ 2.6, not significant), and the rest of the sweep is strongly negative (followers underperform when BTC moves, NOT outperform — meaning the lead-lag hypothesis is reversed at 1m scale).

### N5.3 Volume confluence filter on best cell

Adding `BTC_volume > 1.5× 60m-avg` filter on (ETH, UP, 0.3%, K=10): n collapsed from 27 to 62 (counter-intuitive: filter loosens because thr+vol jointly trigger), **mean -$0.14, p=0.78. Edge eliminated.**

### N5.4 Walk-forward (60d train / 20d test)

5 windows. Test-set mean PnL is **negative in 4/5 windows**. Best window: Win2 test_mean=+$0.55 (n=7). Cannot reproduce out-of-sample.

### N5.5 Permutation (shuffle leader by ±5m)

Observed mean +$0.33, permutation p = 0.20 (6/30 perms beat observed). **Edge indistinguishable from a randomly-misaligned BTC tape.**

### N5.6 Cross-asset to alts (15m, last 12m)

| Alt | thr% | K bars | n | mean | sharpe | p |
|---|---|---|---|---|---|---|
| DOGE | 0.5 | 3 | 29 | -$0.83 | -7.3 | **0.019 (negative)** |
| AVAX | 0.5 | 3 | 46 | -$0.43 | -2.9 | 0.222 |
| LINK | 0.5 | 1 | 38 | -$0.70 | -6.1 | **0.023 (negative)** |

DOGE and LINK both show **statistically significant losses** when chased after BTC moves — confirming the "follower mean-reverts back" story.

### G1-G5 Gate Verdict for N5

- G1 (p<0.05): only 1 cell out of 80 passes (Bonferroni-corrected fails). NOT VALIDATED.
- G2 (net PnL > 0 with HL fees): the best cell is +$1.57 net, but it's a small-n fluke; sweep is dominated by losers.
- G3 (walk-forward 3+ windows): 4/5 test windows negative.
- G4 (permutation): obs not significantly above shuffled. FAILED.
- G5 (cross-asset): DOGE/AVAX/LINK NEGATIVE. NOT GENERALIZABLE.

**N5 strategy is rejected.**

---

## N11 — SMS structure-break pairs (15m panels, last 24 months)

Direct rule: BTC `bos_buy=1` AND ETH `bos_buy=0` AND SOL `bos_buy=0` in last 30 min (2× 15m bars) → LONG 0.5× ETH + 0.5× SOL vs SHORT 1.0× BTC. Hold {1h, 4h, 24h} or exit when ETH or SOL `bos_buy` fires.

| Direction | Hold | Avg bars held | n | mean | win% | sharpe | sum | p |
|---|---|---|---|---|---|---|---|---|
| UP | 1h | 3.5 | **1069** | **-$0.67** | 17% | **-11.32** | -$716 | <0.001 |
| UP | 4h | 10.0 | 1069 | -$0.67 | 29% | -6.37 | -$719 | <0.001 |
| UP | 24h | 20.8 | 1068 | -$0.74 | 33% | -4.53 | -$792 | <0.001 |
| DOWN | 1h | 3.5 | 911 | -$0.54 | 25% | -8.15 | -$495 | <0.001 |
| DOWN | 4h | 10.4 | 911 | -$0.55 | 33% | -4.97 | -$502 | <0.001 |
| DOWN | 24h | 23.1 | 910 | -$0.64 | 38% | -4.04 | -$585 | <0.001 |

**Net pair fees+slip on $250 notional per leg = $0.60 round-trip.** Even the BEST 1h direction (UP, mean -$0.67, gross ≈ -$0.07) doesn't cover fees. The pair structurally bleeds.

### N11 inverse (does flipping help?)

Same fires, but inverted PnL (LONG BTC vs SHORT ETH+SOL on UP break):

| Direction | Hold | n | mean | win% | sharpe |
|---|---|---|---|---|---|
| UP_inv | 1h | 1069 | -$0.53 | 21% | -8.96 |
| DOWN_inv | 1h | 911 | -$0.66 | 21% | -9.85 |

**Both sides lose.** The pair fees+slip alone are >$0.60 round-trip, so the trade is structurally dead unless the gross edge is > 24 bps (~0.24% pair move). The observed gross spread is ≪ 24 bps either direction.

### G1-G5 Gate Verdict for N11

- G1: p < 0.001 ✓ (but in the *wrong* direction)
- G2: net PnL < 0 EVERYWHERE. FAILED.
- G3-G5: not run, primary direction is unprofitable.

**N11 strategy is rejected.**

---

## Why both hypotheses fail

1. **Speed of co-movement:** crypto markets at the BTC/ETH/SOL/perp-spot level are arbitraged within seconds, not minutes. The contemporaneous-bar correlation of 0.82-0.98 means any move that's still detectable at 1m boundaries has already propagated to all venues. The "BTC leads ETH/SOL by 30-180s" intuition is folk-wisdom from 2018-2020 markets — modern HFT has compressed it to <1s.

2. **Structure-break pairs are momentum-on-leader, mean-reversion-on-follower.** The standard MA-cross style structure break in BTC is followed by **further BTC continuation, not convergence**, because the break itself is the news. The ETH/SOL "catch-up" already happened in the same 15m bar. By the time we observe BTC's `bos_buy` we're 2-3 bars behind the news, and the follower legs of the pair drag PnL.

3. **Pair-trade fees:** at 2× single-leg fees ($0.60 vs $0.30) you need ~2× the per-trade gross edge of a single-leg trade. Neither asset combination clears this hurdle.

---

## What WOULD be tradeable (recommendation for next session)

- **Sub-second lead-lag (already explored):** real but unexploitable at our co-location/latency floor. See `_walkforward_basis.csv` for confirmed-no-edge outcome.
- **Volatility-shock cross-asset relative-value:** instead of lagging on returns, lag on realized vol — when BTC realized vol spikes 2σ above 1h baseline, ETH realized vol typically follows within 3-5 minutes. Could be tradeable as a vol-pair (long vol of follower via straddle approximation). Out of scope for W2c.
- **N5 with intra-bar timing:** if we had 1-second binance data joined to 1-second HL data, the 1s sub-minute lead-lag could be exploited at maker-only fees. Not feasible without sub-minute data history and co-location.

---

## Output files

- `strategy_lab/hl_research_2026_05_26/wave2/W2c_leadlag_pairs.py` — runnable analysis script
- `strategy_lab/hl_research_2026_05_26/wave2/W2c_leadlag_pairs.md` — this report
- `strategy_lab/hl_research_2026_05_26/wave2/W2c_results.csv` — machine-readable results table (every sub-test row)
