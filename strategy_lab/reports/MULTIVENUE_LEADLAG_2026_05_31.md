# Multi-Venue Lead-Lag vs Chainlink RTDS — BTC Oracle-Lag Edge
**Date:** 2026-05-31 | **Asset:** BTC-5m | **Offset tested:** 60s (validated baseline)

## Executive Summary

Binance spot 1s is the **best available reference venue** for the oracle-lag directional edge. HL perp 1MIN and OKX spot 1MIN both fail to improve on it — the 2-second sub-minute lead that BIN 1s captures against Chainlink RTDS is invisible at 1-minute bar granularity. No venue or consensus variant beats the BIN baseline on WR, mean PnL, or gate battery.

---

## 1. Cross-Correlation: Which Venue Leads Chainlink Most?

**Window:** OKX overlap (Apr 28 → May 16, ~18 days, 1.56M 1s grid points)

### 1A. 1-Second Resolution (captures sub-minute dynamics)

| Venue | Best Lead (s) | Peak Corr | Profile |
|---|---|---|---|
| **BIN-spot 1s** | **+2s** | **0.577** | Sharp spike at lag=+2; corr drops to ~0.07 at lag=±5 |
| HL-perp 1MIN | −56s (artifact) | 0.031 | Flat; no detectable structure |
| OKX-spot 1MIN | −56s (artifact) | 0.031 | Flat; no detectable structure |

**BIN lag profile (s → corr):** `{-5: 0.021, -1: 0.043, 0: 0.070, +1: 0.255, +2: 0.577, +3: 0.214, +4: 0.065, +5: 0.033}`

The Binance 1s bar closes and its close price propagates into Chainlink RTDS ~2 seconds later. This is the oracle update pipeline latency. HL and OKX have 60-second bar granularity — their return series is zero between bar closes, producing a flat xcorr profile. The negative-lag "best" at −56s is an artifact of the 60s autocorrelation pattern in the data.

### 1B. 60-Second Resolution (coarse alignment)

| Venue | Best Lead (min) | Peak Corr at lag=0 |
|---|---|---|
| BIN-spot | 0 min | 0.858 |
| HL-perp | 0 min | 0.878 |
| OKX-spot | 0 min | 0.919 |

All venues peak at lag=0 at 60s resolution — no venue leads Chainlink by a detectable full minute. The slightly higher 60s corr for HL/OKX vs BIN is a measurement artifact (perp/spot are near-identical; OKX 60s bars are slightly smoother) and conveys no sub-minute information advantage.

**Bottom line:** BIN 1s leads CL by 2s. HL 1MIN and OKX 1MIN cannot resolve this lag.

---

## 2. Per-Venue Oracle-Lag Signal Edge (BTC-5m, offset=60s)

Strategy: `clbasis_rel` — (venue_px − CL_px)/CL × 10⁴, deviation from trailing median, fire when |dev| > threshold → buy leading side.

### Gate Battery Results

| Venue | thr | n | WR | mean_pnl (legacy) | mean_pnl (realistic) | G1 | G2 | G3_p | G4_ci_lo | G4 |
|---|---|---|---|---|---|---|---|---|---|---|
| **BIN-spot (baseline)** | **3** | **64** | **0.859** | **+$6.31** | **+$5.95** | **PASS** | **PASS 7/7** | **0.0005** | **+$2.93** | **PASS** |
| BIN-spot | 2 | 184 | 0.766 | +$2.92 | +$2.53 | PASS | PASS 6/7 | 0.0005 | +$0.55 | PASS |
| HL-perp | 3 | 320 | 0.706 | +$1.18 | +$0.77 | PASS | FAIL 8/12 | 0.0005 | −$0.72 | **FAIL** |
| HL-perp | 5 | 163 | 0.712 | +$1.18 | +$0.78 | PASS | PASS 6/7 | 0.0005 | −$1.46 | **FAIL** |
| HL-perp | 10 | 123 | 0.683 | +$0.27 | −$0.13 | PASS | — | 0.0005 | −$2.87 | **FAIL** |
| OKX-spot | 20 | 757 | 0.672 | −$0.48 | −$0.90 | **FAIL** | insufficient | 0.0005 | −$1.77 | **FAIL** |
| OKX-spot | 50 | 436 | 0.686 | +$0.13 | −$0.28 | PASS | insufficient | 0.0005 | −$1.50 | **FAIL** |
| BIN+HL consensus | 3 | 51 | 0.824 | +$4.82 | +$4.46 | PASS | PASS 7/7 | 0.0005 | +$0.55 | PASS |

**Fee model:** legacy = 2%-on-profit (production parity); realistic = poly taker curve + $0.01 tx.

### Why HL fails

- **HL basis std = 8.0 bps** vs **BIN std = 1.24 bps**. The fat tails come from 1-minute bar-close timing: HL's "close" price at a given second is stale by up to 59s, so (HL − CL) fluctuates widely due to bar-boundary timing rather than genuine price discovery.
- HL basis deviation > 3 fires 9.3% of rows vs BIN 3.1%. Most HL fires are timing noise.
- **No HL threshold produces G4 PASS** at adequate n. The thr=50 case (n=11, PASS) is a data artifact — all 11 fires cluster in the Apr 28-May 2 period where BIN 1s is absent; they capture an unrelated regime, not the oracle-lag signal.

### Why OKX fails

- **OKX basis std = 43 bps** — large systematic drift from spot-futures basis and sparse liquidity on the OKX-USDT/CL pair used here.
- Partial window (Apr 28 → May 16, 18 days) limits statistical power.
- All thresholds: G1 marginal or FAIL, G4 FAIL across all tested values.

---

## 3. Consensus Variants

**Key finding:** BIN and HL **never** disagree direction when both fire at thr=3. When BIN fires Up, HL fires Up (or doesn't fire). Zero contradictions in 166 BIN-fires × 332 HL-fires overlap.

| Variant | n | WR | mean_pnl | G4 |
|---|---|---|---|---|
| BIN alone (overlap window) | 64 | 0.859 | +$6.31 | PASS |
| BIN+HL consensus (both thr=3) | 51 | 0.824 | +$4.82 | PASS |

Consensus reduces n by 20%, WR by 3.5pp, and mean_pnl by $1.49 vs BIN alone — pure signal loss. HL adds no directional information that BIN doesn't already contain.

---

## 4. Basis Distribution Summary

| Venue | Basis std (raw) | Dev std (vs trailing med) | % |dev|>3 |
|---|---|---|---|
| BIN-spot | ~1.2 bps | 1.24 bps | 3.1% |
| HL-perp | 9.7 bps | 8.0 bps | 9.3% |
| OKX-spot | ~40 bps | 43.4 bps | >90% |

BIN's tight distribution means threshold=3 is a genuine signal gate. HL and OKX are dominated by granularity/basis noise.

---

## 5. Coverage Notes

- **BIN 1s:** full 39-day window (Apr 22 → May 31). Used for baseline gate tests.
- **HL 1MIN:** 39-day window (Apr 28 → May 31), 42,567 1MIN bars, 90.5% coverage of fires.
- **OKX 1MIN:** Apr 28 → May 16 only (17 days), 26,049 rows, 87.5% coverage. **Weight LOW** — short window, partial overlap, systematic basis drift.
- All xcorr comparisons use the OKX overlap window for fairness.

---

## 6. Verdict

**Binance spot 1s is the optimal oracle-lag reference venue. No tested alternative improves the edge.**

| Hypothesis | Result |
|---|---|
| HL-perp leads CL more than BIN-spot | REJECTED — HL 1MIN has no sub-minute resolution |
| HL-perp produces better G4-passing signal | REJECTED — G4 FAIL across all thresholds |
| OKX-spot provides useful cross-check | REJECTED — partial window, basis noise, G4 FAIL |
| BIN+HL consensus improves WR/edge | REJECTED — fewer fires, lower WR and PnL than BIN alone |
| BIN 1s leads CL RTDS | CONFIRMED — 2s sub-minute lead, corr=0.577 spike at lag=+2 |

**Actionable conclusion:** Keep BIN-spot 1s as the oracle-lag leg (LAGV2). No venue upgrade warranted with currently available data.

**If HL 1s tick data were available** (REST `/info` trades or WS L2 at 1s resolution), it would be worth re-testing — HL perp may genuinely lead spot price discovery at the tick level. This is not available in canonical currently.

---

## Appendix: Xcorr Table (1s resolution, lags −10s to +10s)

| Lag (s) | BIN corr | HL corr | OKX corr |
|---|---|---|---|
| −5 | 0.021 | 0.019 | 0.022 |
| −3 | 0.020 | 0.020 | 0.022 |
| −1 | 0.043 | 0.020 | 0.023 |
| **0** | **0.070** | **0.014** | **0.016** |
| +1 | 0.255 | 0.015 | 0.020 |
| **+2** | **0.577** | **0.013** | **0.019** |
| +3 | 0.214 | 0.019 | 0.023 |
| +5 | 0.033 | 0.008 | 0.008 |
| +10 | 0.015 | −0.004 | −0.005 |

BIN profile is a textbook oracle-lag signature: near-zero at negative lags, sharp peak at +2s, rapid decay. HL and OKX are flat throughout — no exploitable structure.
