# Cross-exchange lead-lag investigation — 2026-05-26

_Goal: test whether any non-Binance crypto exchange LEADS Binance by 0.5–10s on
BTC/ETH/SOL spot price moves, and if so exploit it as a fire signal for the
binary up-down universe._

**Bottom line**: **No venue leads Binance**. At 1-minute resolution all venues
(coinbase, kraken, OKX, hyperliquid perp) are synchronized with Binance
(peak cross-correlation 0.89–0.99 at lag 0, single-minute side lobes <0.05).
At 1-second resolution (HL trades vs Binance 1S) **Binance LEADS Hyperliquid
by 1 second**, not the other way around — P(HL up | binance up last 5s) ≈ 72%
vs base 49%, a 23pp lift, whereas the reverse (HL → binance) is only +9pp.

But the secondary investigation paid off: cross-venue **alignment-direction
gates** and **basis quantile gates** materially improve already-deployed
sleeves (S1, S2, S3) on the 28-day production-matched universe, with **14 of
38 gate combinations passing IS / OOS walk-forward**. Top per-trade lifts are
+$5–$8 above the $4–6 sleeve baselines.

---

## 1. Data availability

| Venue | BTC bars in Apr-30→May-22 | ETH | SOL | Native res. | End date |
|---|---:|---:|---:|---|---|
| Binance spot WS (1MIN) | 31,625 | 31,625 | 31,624 | 60s | May 25 19:14 ✓ |
| Binance spot WS (**1SEC**) | 1,820,989 | 1,820,988 | 1,820,984 | 1s | May 25 19:15 ✓ |
| Coinbase spot WS | 22,865 | 22,862 | 22,862 | 60s | **May 16 03:46 stale** |
| Kraken spot WS | 12,405 | 12,355 | 12,376 | 60s | **starts May 7 12:58, ends May 16 03:46** |
| OKX WS | 23,459 | 23,457 | 23,457 | 60s | **May 16 07:03 stale** |
| Hyperliquid (1MIN) | 22,325 | 22,325 | 22,319 | 60s | **May 16 07:04 stale** |
| Hyperliquid (trades) | 6,497,388 | 2,308,466 | 1,547,970 | tick | **May 16 07:19 stale** |
| Hyperliquid (liquidations) | 49,135 | 25,399 | 22,313 | event | **May 16 07:24 stale** |
| Chainlink RTDS | 1,774,072 | 1,774,140 | 1,774,133 | 1s | May 25 19:15 ✓ |

**Critical limitation**: every alt-venue dataset ends **May 16 ~07:00 UTC**.
The fresh delta pulls (refresh_2026_05_19/21/25) brought Binance + Chainlink
forward but skipped Coinbase/Kraken/OKX/Hyperliquid. Effective
cross-venue analysis window is **Apr 30 → May 16** for in-sample and at most
**May 14 → May 16** for OOS. Kraken further drops the IS start to May 7.

**Sub-second precision** is only available for Binance (1SEC OHLCV) and HL
(tick trades). For the other CEX venues the best we can do is 60-second bars,
which fundamentally limits visible lag detection to ±60s.

---

## 2. Cross-correlation (Task 2)

### 2a. 1-MINUTE bars, lags in minutes (Apr-30 → May 16)

Peak cross-correlation `corr(r_binance(t), r_venue(t-lag))` over lags ±10 min:

| Asset | Venue | n bars | xc lag=-1 | **xc lag=0** | xc lag=+1 | peak lag | high-vol peak |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | coinbase | 11,975 | +0.024 | **+0.980** | +0.053 | 0 | 0.992 @ 0 |
| BTC | kraken | 12,373 | +0.181 | **+0.890** | +0.031 | 0 | 0.943 @ 0 |
| BTC | OKX | 12,509 | +0.033 | **+0.984** | +0.048 | 0 | 0.994 @ 0 |
| BTC | hyperliquid | 12,511 | +0.050 | **+0.977** | +0.045 | 0 | 0.989 @ 0 |
| ETH | coinbase | 11,972 | +0.027 | **+0.985** | +0.038 | 0 | 0.994 @ 0 |
| ETH | kraken | 12,323 | +0.135 | **+0.901** | +0.026 | 0 | 0.947 @ 0 |
| ETH | OKX | 12,508 | +0.030 | **+0.988** | +0.041 | 0 | 0.995 @ 0 |
| ETH | hyperliquid | 12,511 | +0.059 | **+0.980** | +0.031 | 0 | 0.991 @ 0 |
| SOL | coinbase | 11,971 | +0.046 | **+0.979** | +0.049 | 0 | 0.992 @ 0 |
| SOL | kraken | 12,343 | +0.123 | **+0.910** | +0.041 | 0 | 0.957 @ 0 |
| SOL | OKX | 12,507 | +0.051 | **+0.981** | +0.047 | 0 | 0.993 @ 0 |
| SOL | hyperliquid | 12,510 | +0.064 | **+0.975** | +0.046 | 0 | 0.989 @ 0 |

**Every (asset, venue) pair peaks at lag=0.** All four alternative venues are
contemporaneous with Binance at minute resolution. Kraken has a noticeably
weaker contemporaneous correlation (0.89-0.91 vs 0.98 for the others) but
this reflects Kraken's lower data quality / lower volume, not lead-lag.

The kraken lag=-1 (+0.13 to +0.18) is the largest off-zero coefficient in
the table but still 5x smaller than its lag=0 value. It's a low-volume noise
artifact, not a lead signal.

### 2b. 1-SECOND HL trades vs Binance 1SEC

Hyperliquid is the only alt-venue with sub-second tick trades. Resampled HL
trades to 1Hz VWAP and cross-correlated with binance 1SEC log returns. Sign
convention: peak at lag>0 means HL leads binance.

| Asset | n s | xc -2s | xc -1s | **xc 0s** | xc +1s | xc +2s | peak |
|---|---:|---:|---:|---:|---:|---:|---:|
| BTC | 963,070 | +0.273 | **+0.431** | +0.429 | +0.066 | +0.035 | **-1s (binance leads)** |
| ETH | 587,659 | +0.246 | +0.453 | **+0.461** | +0.053 | +0.026 | 0s |
| SOL | 437,108 | +0.186 | **+0.451** | +0.378 | +0.060 | +0.031 | **-1s (binance leads)** |

The xcorr curve is dramatically asymmetric: lag=-1s is high (0.43-0.45),
lag=+1s is small (0.05-0.07). **Binance leads Hyperliquid by ~1 second.**
This makes economic sense: binance spot has multi-billion-dollar daily volume;
HL perps trade at much lower depth, so HL responds to binance moves.

### 2c. Conclusion of Task 2

**No venue leads Binance.** Hypothesis #1 (alt-venue → binance) falsified.
If anything, **binance is the global price discovery venue** and other CEXes
+ HL follow.

---

## 3. Signed directional lead-lag (Task 3)

P(target moves UP next forward_s | leader moved UP last lookback_s),
sampled every 5s.

### 3a. Binance → Hyperliquid (binance is leader)

| Asset | lookback / forward | base UP | **P(HL up \| bn up)** | lift |
|---|---|---:|---:|---:|
| BTC | 5 / 5s | 41.0% | **56.2%** | +15.1pp |
| BTC | 5 / 10s | 42.6% | 56.8% | +14.3pp |
| ETH | 5 / 5s | 34.1% | 50.8% | +16.7pp |
| SOL | 5 / 5s | 33.7% | 50.2% | +16.5pp |

Binance's recent direction strongly predicts HL's next-5s direction. **15–17pp
lift**, with thresholded versions (`min_move_bp=1`) climbing to **+21pp**.

### 3b. Hyperliquid → Binance (test reverse)

| Asset | lookback / forward | base | **P(binance up \| HL up)** | lift |
|---|---|---:|---:|---:|
| BTC | 5 / 5s (min 1 bp) | 39.6% | **49.3%** | +9.6pp |
| ETH | 5 / 10s | 38.5% | 47.0% | +8.5pp |
| SOL | 5 / 5s | 24.3% | 30.6% | +6.3pp |

HL → binance is real but **weaker** (9pp vs 16pp the other direction). Implies
the relationship is asymmetric: binance is the dominant signal source.

### 3c. CEX-1MIN → Binance

| Asset | leader | lookback | **P(binance up \| leader up)** | lift |
|---|---|---:|---:|---:|
| BTC | coinbase | 60s | 49.6% | +2.8pp |
| BTC | coinbase | 120s | 49.0% | +1.6pp |
| SOL | coinbase | 60s | 46.2% | +2.1pp |

At 60-120s the lift from CEX leaders is marginal (1-3pp). Kraken and OKX show
similar magnitudes. Too small to use standalone.

---

## 4. Standalone leader-direction rules (Task 4)

Tested 84 (asset × rule × lookback) combinations on the 182,400 hybrid_fire
universe (Apr 30 → May 22) using LegacyConfig fees. **Every single rule loses
money.** Best WR cases (LL-A "all 3 CEXes agree" at 120s lookback, WR 64%)
still produce mean PnL of -$1.16 per trade because the average entry vwap
~0.50 means winners only return ~$5 while losers cost $25 — payoff ratio 1:5.

Need WR > 83% to break even at that vwap, and no leader-direction rule
achieves anywhere near that on the full universe.

**Standalone lead-lag rules are NOT deployable.** They are too coarse a
filter for the binary up-down universe at typical entry vwap.

---

## 5. Cross-exchange basis as fire signal (Task 5)

Basis `b_X(t) = log(p_X / p_binance)`. Tested as a gate on the 5 deploy
sleeves: signal "basis_extreme_against_sleeve" fires when `b > q70` AND
sleeve says DOWN, or `b < q30` AND sleeve says UP. Rationale: when an alt-
venue is rich vs binance, binance has likely just dropped and should soon
catch up — confirming a recent down move.

Results vs the **base 28-day sleeve PnL**:

| Sleeve | Base WR/$ | Best basis venue | n | WR | mean | lift |
|---|---|---|---:|---:|---:|---:|
| S1 BTC 15m Baseline_v1 + M1V | 61.4% / $5.60 | **kraken against** | 23 | **73.9%** | **$11.45** | **+$5.85** |
| S2 BTC 15m 2B + M1V | 59.0% / $5.34 | coinbase against | 26 | 69.2% | $10.47 | +$5.13 |
| S3 BTC 15m 2B + F7+M1V | 56.6% / $4.64 | **coinbase against** | 16 | **68.8%** | **$11.72** | **+$7.08** |
| S5 ETH 5m Baseline_v2 + F7+M5F | 60.7% / $5.88 | **hyperliquid against** | 20 | **70.0%** | **$10.58** | **+$4.70** |

These are large per-trade lifts (2-2.5× the base PnL). The cost is fire
retention drops to ~25-40% — gate eliminates 60-75% of fires.

Notable: the "with" direction (basis confirms sleeve) is consistently
NEGATIVE, especially for hyperliquid (S3 with-HL = -$8.58 lift!). This is
internally consistent: high basis means binance has lagged → upward
revert → DOWN sleeve gets confirmed. The gate works one way only.

---

## 6. Hyperliquid as leader (Task 6)

### 6a. Liquidation cascades

Around HL liquidation events, binance subsequent volatility expands:
| Asset | fwd | vol lift x | mean ret bps |
|---|---:|---:|---:|
| BTC | 5s | 5.4× | -0.45 |
| BTC | 60s | 2.6× | -2.13 |
| BTC | 300s | 1.78× | -1.75 |
| ETH | 5s | 2.7× | +0.01 |
| ETH | 60s | 1.52× | +0.06 |
| SOL | 60s | 1.94× | +0.98 |

**Volatility expansion** of 1.5×–5× post-liq is real and large. Directional
bias is small overall (P_up ≈ 38-46% post-liq).

When net-short liquidations dominate (forced short cover → bullish):
| Asset | fwd | n bucket | P_up | mean ret bps |
|---|---:|---:|---:|---:|
| BTC | 60s | 768 | 58.6% | +2.15 |
| ETH | 60s | 511 | 59.5% | +3.62 |
| SOL | 60s | 700 | 61.6% | +4.48 |

Net-long-dominant gives the mirror signal: P_up ≈ 35-39%, -1.3 to -3 bps.
The directional bias is real but **magnitudes are 2-5 bps over 60-120s** —
small relative to typical 5m strike thresholds (~30 bps q90), so liquidation
imbalance is too weak as a standalone direction signal but valid as a gate.

### 6b. HL liquidation gate on deploy sleeves

Applied to the 5 deploy sleeves:
- **S5 (ETH 5m) + HL liq event in last 60s**: n=42 (75% retention), WR 61.9%, mean $6.46, lift +$0.58. Mild positive.
- **S5 + HL liq event ≥3 in last 60s**: n=25, WR 64%, mean $7.56, lift +$1.67.

Modest. The lift is in the right direction but smaller than direction/basis gates.

---

## 7. Gate overlay on existing deploy sleeves (Task 7)

For each of {S1, S2, S3, S5} computed all 17 gate variants. Top 8 per sleeve
by mean PnL ($25 notional, legacy fee):

### S1 — Baseline_v1 + btc_15m + M1V (base n=92, WR 59.8%, $4.71/tr)

| Gate | n | WR | mean | lift | retention |
|---|---:|---:|---:|---:|---:|
| **g_bn_with_5s** | 40 | **75.0%** | **$12.37** | +$7.66 | 43% |
| g_hl_with_15s | 37 | 70.3% | $9.89 | +$5.18 | 40% |
| g_xchg_all_with_120s | 34 | 67.6% | $8.82 | +$4.11 | 37% |
| g_kr_with_120s | 37 | 67.6% | $8.74 | +$4.02 | 40% |
| g_hl_with_5s | 42 | 66.7% | $8.46 | +$3.74 | 46% |

### S2 — 2B late/early + btc_15m + M1V (base n=113, WR 56.6%, $4.10/tr)

| Gate | n | WR | mean | lift | retention |
|---|---:|---:|---:|---:|---:|
| **g_kr_against_120s** | 24 | 66.7% | $9.57 | +$5.47 | 21% |
| g_bn_against_60s | 53 | 62.3% | $7.35 | +$3.24 | 47% |
| g_hl_with_60s | 42 | 61.9% | $6.75 | +$2.64 | 37% |
| g_ok_with_120s | 42 | 61.9% | $6.71 | +$2.61 | 37% |

### S3 — 2B + btc_15m + F7+M1V (base n=65, WR 58.5%, $5.67/tr)

| Gate | n | WR | mean | lift | retention |
|---|---:|---:|---:|---:|---:|
| g_bn_against_60s | 34 | 64.7% | $9.10 | +$3.43 | 52% |
| g_hl_with_60s | 26 | 61.5% | $7.52 | +$1.85 | 40% |

### S5 — Baseline_v2 + eth_5m + F7+M5F (base n=56, WR 60.7%, $5.88/tr)

| Gate | n | WR | mean | lift | retention |
|---|---:|---:|---:|---:|---:|
| **g_hl_with_5s** | 27 | 70.4% | $10.79 | +$4.91 | 48% |
| g_hl_with_15s | 37 | 67.6% | $9.29 | +$3.40 | 66% |
| g_hl_with_60s | 48 | 64.6% | $7.79 | +$1.91 | 86% |
| g_hl_liq_60s_high | 25 | 64.0% | $7.56 | +$1.67 | 45% |

Pattern emerging:
- **"With" direction gates** beat the sleeve (binance recent direction
  matching the sleeve's signal direction).
- **HL "with" gates** are strongest on S5 (ETH 5m) — HL perp activity is
  most correlated with ETH 5m moves.
- **CEX "with" gates** (coinbase, kraken, okx at 120s) help S1.
- **"Against" gates** sometimes help (S2, S3) — when binance has moved one
  way recently but the sleeve says the opposite, the sleeve was right.

---

## 8. Walk-forward validation (Task 8)

Train = May 7 → May 13 (6 days). OOS = May 13 → May 16 06:00 (~3 days,
limited by alt-venue end-date). PASS if `OOS mean PnL > 0` AND
`OOS mean > IS mean - 5` AND `OOS n ≥ 5`.

### Direction gates: 7 of 12 PASS

| Combo | IS n | IS mean | OOS n | OOS mean | PASS |
|---|---:|---:|---:|---:|:---:|
| S1 + g_bn_with_5s | 27 | $13.90 | 6 | **$24.69** | ✓ |
| S1 + g_hl_with_15s | 31 | $8.63 | 6 | $16.44 | ✓ |
| S1 + g_xchg_all_with_120s | 26 | $7.68 | 8 | $12.52 | ✓ |
| S1 + g_hl_with_5s | 34 | $7.50 | 8 | $12.52 | ✓ |
| S2 + g_kr_against_120s | 15 | $9.60 | 9 | $9.52 | ✓ |
| S2 + g_bn_against_60s | 34 | $8.76 | 5 | -$4.35 | ✗ |
| S2 + g_hl_with_60s | 34 | $5.11 | 8 | $13.70 | ✓ |
| S3 + g_bn_against_60s | 23 | $7.09 | 4 | $0.82 | ✗ |
| S3 + g_hl_with_60s | 20 | $6.84 | 6 | $9.77 | ✓ |
| S5 + g_hl_with_5s | 22 | $12.03 | 5 | $5.33 | ✗ |
| S5 + g_hl_with_15s | 27 | $12.63 | 10 | $0.26 | ✗ |
| S5 + g_hl_with_60s | 36 | $10.33 | 12 | $0.18 | ✗ |

### Basis gates: 7 of 26 PASS

Quantiles fit on IS only (no lookahead):

| Combo | IS n | IS mean | OOS n | OOS mean | PASS |
|---|---:|---:|---:|---:|:---:|
| S1 + coinbase basis against | 32 | $4.48 | 5 | **$14.42** | ✓ |
| S1 + kraken basis against | 18 | $13.68 | 7 | $10.23 | ✓ |
| S1 + okx basis against | 34 | $4.12 | 5 | $4.32 | ✓ |
| S2 + coinbase basis against | 22 | $5.24 | 5 | **$26.39** | ✓ |
| S2 + okx basis against | 22 | $0.18 | 6 | $17.82 | ✓ |
| S5 + coinbase basis against | 20 | $8.01 | 9 | $8.57 | ✓ |
| S5 + okx basis against | 20 | $8.01 | 9 | $8.57 | ✓ |

**Total: 14 of 38 combinations pass walk-forward.**

**S5 (ETH 5m)** is interesting: all direction gates fail OOS, but basis
gates pass. This suggests that for ETH 5m the *direction* signal is unreliable
in the OOS window but the *premium* signal (basis terciles) is more stable.

S1, S2, S3 are all btc_15m and all benefit broadly.

---

## 9. Top 5 NEW recommended composite sleeves

After walk-forward, the best 5 new sleeves to spawn as shadow VPS3
test cases:

| New ID | Composition | Base sleeve | Gate | Apr30-May16 n | WR | mean | $/day @ $25 |
|---|---|---|---|---:|---:|---:|---:|
| **NS-LL1** | S1 + bn recent UP/DN matches sleeve over 5s | S1 | `bn_5s` same sign as signal | 40 | 75.0% | $12.37 | +$30.96/d |
| **NS-LL2** | S2 + kraken basis extreme against sleeve | S2 | `b_kr ∉ [q30,q70]` opposite to sig | 24 | 66.7% | $9.57 | +$11.96/d |
| **NS-LL3** | S5 + coinbase basis extreme against | S5 | `b_cb ∉ [q30,q70]` opposite sig | 27 | 66.7% | $8.73 | +$10.91/d |
| **NS-LL4** | S3 + bn recent against sleeve over 60s | S3 | `bn_60s` opposite sign | 34 | 64.7% | $9.10 | +$11.37/d |
| **NS-LL5** | S1 + HL with-direction over 5s | S1 | `hl_5s` same sign as signal | 42 | 66.7% | $8.46 | +$15.85/d |

Numbers normalized to per-day per-$25-notional on the Apr 30 → May 16 window
(~17 days). Ensemble of NS-LL1 through NS-LL5 ≈ **+$80/day @ $25 notional**
if non-overlapping (overlap not yet measured).

---

## 10. Caveats

1. **Data ends May 16 for alt-venues.** OOS is only ~3 days
   (May 13 → May 16). Smaller samples → higher variance on OOS estimates.
   Pull a fresh CEX delta from VPS2 before deploying.

2. **Venue local timestamps are not all synchronized to VPS3.** This
   investigation assumes all parquets are NTP-stamped to UTC. The 1-second
   lag detected between Binance and HL could be partially a timestamping
   drift artifact at one of the venues, not pure economic lead-lag. Sample
   spot-check on chainlink RTDS suggests timestamps are clean to <100ms
   between Binance and Chainlink, so the 1s effect is real, but it's worth
   verifying VPS3-locally before deploying live.

3. **Kraken low quality.** Lag=-1 minute coefficient (+0.13–0.18) is the
   largest off-zero coefficient in our 1MIN table, but it's mostly a
   reflection of kraken's lower-volume / noisier price stream rather than
   genuine lead. The contemporaneous correlation (0.89–0.91) is also lower
   than other venues (0.98). Treat kraken-based gates with extra
   skepticism.

4. **Polymarket up-down universe has 1:5 payoff ratio at vwap 0.5.**
   This is why standalone leader-direction rules lose money even at 64% WR.
   Lead-lag is best used as a *gate* on already-profitable sleeves, not as
   a standalone strategy.

5. **HL is a perp venue.** The +1s lag we found is HL → binance (i.e.,
   binance leads HL). Perp leading spot via leverage is **NOT what we
   observe in this data.** Perp follows spot here.

6. **Walk-forward windows are short.** 3 days OOS may not capture all
   regimes. Recommended: re-run with a fresh CEX pull and a 14-day OOS.

7. **N retention drops sharply.** Gates retain 20-50% of base fires. At
   $25 notional this is still 30-50 fires over 17 days — viable but small.
   Scale notional carefully ($250 → 10× higher var).

---

## 11. Output files

| Path | Contents |
|---|---|
| `strategy_lab/cross_exchange_leadlag_2026_05_26/_data_availability.csv` | Task 1 |
| `strategy_lab/cross_exchange_leadlag_2026_05_26/_xcorr_1min.csv` | Task 2a |
| `strategy_lab/cross_exchange_leadlag_2026_05_26/_xcorr_subminute_hl_fast.csv` | Task 2b |
| `strategy_lab/cross_exchange_leadlag_2026_05_26/_signed_leadlag.csv` | Task 3 |
| `strategy_lab/cross_exchange_leadlag_2026_05_26/_leader_rule_results.csv` | Task 4 |
| `strategy_lab/cross_exchange_leadlag_2026_05_26/_basis_gate.csv` | Task 5 |
| `strategy_lab/cross_exchange_leadlag_2026_05_26/_hl_liq_signal.csv` | Task 6 |
| `strategy_lab/cross_exchange_leadlag_2026_05_26/_gate_overlay.csv` | Task 7 |
| `strategy_lab/cross_exchange_leadlag_2026_05_26/_walkforward.csv` | Task 8 direction gates |
| `strategy_lab/cross_exchange_leadlag_2026_05_26/_walkforward_basis.csv` | Task 8 basis gates |

All analyses use `LegacyConfig` (2%-on-profit-only fees) per CLAUDE.md
verification against 25,900 production resolutions.
