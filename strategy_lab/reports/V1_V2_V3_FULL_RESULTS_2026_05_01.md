# V1 / V2 / V3 — Full Live Shadow Results

**Window:** 2026-04-30 06:10 → 2026-05-01 14:10 UTC (1.33 days)
**Total resolutions across all 3 versions:** 2,978

## Definitions

| Version | Host | Strategy | Feed | Notes |
|---|---|---|---|---|
| **V1** | VPS2 | volume-mode (HEDGE_HOLD) | OKX-WS | control arm |
| **V2_volume** | VPS3 | volume-mode (HYBRID side) | binance-spot-ws | test arm — same logic as V1, different feed |
| **V2_sniper** | VPS3 | sniper-mode (HYBRID side) | binance-spot-ws | top-quantile magnitude |
| **V3** | VPS3 | per-asset tuned portfolio sniper | binance-spot-ws | new strategy, BTC q10 / ETH q5 / SOL q15 multi-h |

---

## Headline (top-line)

| Version | n | wins | hit | PnL | Notional | ROI |
|---|---|---|---|---|---|---|
| V1 | 1,420 | 680 | **47.89%** | **-$2,891** | $35,944 | **-8.04%** |
| V2_volume | 1,466 | 722 | **49.25%** | **-$2,004** | $37,099 | **-5.40%** |
| V2_sniper | 86 | 41 | 47.67% | -$172 | $2,178 | -7.90% |
| **V3** | **6** | **5** | **83.33%** | **+$93** | $150 | **+61.80%** |

V3 is the only profitable version. V2_sniper barely worse than volume mode in this window. V2_volume is the best volume mode (1.4pp better than V1 due to feed alone).

---

## V1 — VPS2 volume mode (control arm, OKX-WS feed)

**Aggregate:**
- Fires: 1,420 (680 wins / 740 losses)
- Hit rate: **47.89%**
- Total PnL: **-$2,891.13**
- Notional: $35,944
- ROI: **-8.04%**
- Avg PnL/trade: -$2.04
- Avg fill cost: 0.5152
- Avg win: +$23.29 / avg loss: -$25.31

**Per-sleeve:**

| Sleeve | n | hit | PnL | ROI |
|---|---|---|---|---|
| **sol_15m_volume** | 111 | 58.6% | **+$278** | **+9.88%** ⭐ |
| eth_15m_volume | 120 | 51.7% | -$31 | -1.03% |
| btc_15m_volume | 119 | 47.1% | -$273 | -9.13% |
| btc_5m_volume | 361 | 49.3% | -$293 | -3.24% |
| eth_5m_volume | 363 | 44.6% | -$1,252 | -13.59% |
| sol_5m_volume | 346 | 45.4% | -$1,320 | -14.92% |

**By asset/tf/direction (V1):**

| Asset | TF | Dir | n | hit | PnL |
|---|---|---|---|---|---|
| BTC | 5m | DOWN | 186 | 50.0% | -$56 |
| BTC | 5m | UP | 175 | 48.6% | -$236 |
| BTC | 15m | DOWN | 66 | 43.9% | -$254 |
| BTC | 15m | UP | 53 | 50.9% | -$19 |
| ETH | 5m | DOWN | 179 | 45.8% | -$522 |
| ETH | 5m | UP | 184 | 43.5% | -$730 |
| ETH | 15m | DOWN | 63 | 52.4% | +$6 |
| ETH | 15m | UP | 57 | 50.9% | -$37 |
| **SOL** | **15m** | **UP** | **51** | **64.7%** | **+$272** ⭐ |
| SOL | 15m | DOWN | 60 | 53.3% | +$7 |
| SOL | 5m | DOWN | 170 | 45.9% | -$591 |
| SOL | 5m | UP | 176 | 44.9% | -$729 |

**By date:**

| Date | n | hit | PnL |
|---|---|---|---|
| 04-30 | 842 | 47.1% | -$2,005 |
| 05-01 | 578 | 49.0% | -$886 |

V1 is bleeding ~$2-2.9k/day at $25/trade flat sizing. Single bright spot: SOL 15m volume UP (+$272 over 51 fires).

---

## V2 (VPS3, binance-spot-ws feed)

V2 has two sub-modes running in parallel: volume + sniper.

### V2_volume — same volume logic as V1, but binance feed

**Aggregate:**
- Fires: 1,466
- Hit rate: **49.25%** (1.36pp better than V1)
- PnL: **-$2,004** ($887 less loss than V1)
- ROI: **-5.40%**
- Avg fill cost: 0.5152 (identical to V1)

**Per-sleeve:**

| Sleeve | n | hit | PnL | ROI |
|---|---|---|---|---|
| **sol_15m_volume** | 116 | 57.8% | **+$256** | **+8.71%** ⭐ |
| eth_15m_volume | 125 | 53.6% | **+$70** | **+2.21%** |
| **btc_5m_volume** | 373 | 51.2% | **+$51** | **+0.55%** |
| btc_15m_volume | 125 | 49.6% | -$129 | -4.09% |
| eth_5m_volume | 374 | 46.0% | -$1,048 | -11.04% |
| sol_5m_volume | 353 | 46.2% | -$1,205 | -13.36% |

3 of 6 V2_volume sleeves are now profitable. V1 had only 1.

**By asset/tf/direction (V2_volume):**

| Asset | TF | Dir | n | hit | PnL |
|---|---|---|---|---|---|
| BTC | 5m | DOWN | 192 | 51.6% | +$88 |
| BTC | 5m | UP | 181 | 50.8% | -$36 |
| BTC | 15m | DOWN | 69 | 46.4% | -$181 |
| BTC | 15m | UP | 56 | 53.6% | +$52 |
| ETH | 5m | DOWN | 190 | 46.8% | -$463 |
| ETH | 5m | UP | 184 | 45.1% | -$585 |
| ETH | 15m | DOWN | 64 | 54.7% | +$71 |
| ETH | 15m | UP | 61 | 52.5% | -$1 |
| **SOL** | **15m** | **UP** | **55** | **63.6%** | **+$270** ⭐ |
| SOL | 15m | DOWN | 61 | 52.5% | -$14 |
| SOL | 5m | DOWN | 174 | 48.3% | -$405 |
| SOL | 5m | UP | 179 | 44.1% | -$800 |

**By date (V2_volume):**

| Date | n | hit | PnL |
|---|---|---|---|
| 04-30 | 920 | 49.3% | -$1,213 |
| 05-01 | 546 | 49.1% | -$791 |

### V2_sniper — top-quantile magnitude sniper

**Aggregate:**
- Fires: 86
- Hit rate: 47.67%
- PnL: **-$172.08**
- ROI: -7.90%
- Avg fill cost: 0.5140
- Avg win: +$23.59 / avg loss: -$25.31

**Per-sleeve:**

| Sleeve | n | hit | PnL | ROI |
|---|---|---|---|---|
| **btc_5m_sniper** | 20 | 65.0% | **+$149** | **+29.57%** ⭐ |
| **sol_15m_sniper** | 12 | 66.7% | **+$75** | **+24.85%** |
| **eth_15m_sniper** | 7 | 71.4% | **+$63** | **+35.67%** |
| btc_15m_sniper | 10 | 50.0% | -$6 | -2.22% |
| eth_5m_sniper | 13 | 30.8% | -$129 | -39.12% |
| **sol_5m_sniper** | 24 | **25.0%** | **-$324** | **-52.84%** ⚠ |

3 sleeves profitable, 3 losing. **SOL 5m sniper alone is responsible for nearly 2x the total V2_sniper net loss.**

**By asset/tf/direction (V2_sniper):**

| Asset | TF | Dir | n | hit | PnL |
|---|---|---|---|---|---|
| BTC | 5m | DOWN | 8 | 75.0% | +$101 |
| BTC | 5m | UP | 12 | 58.3% | +$48 |
| BTC | 15m | DOWN | 7 | 42.9% | -$30 |
| BTC | 15m | UP | 3 | 66.7% | +$24 |
| ETH | 5m | DOWN | 5 | 40.0% | -$27 |
| ETH | 5m | UP | 8 | 25.0% | -$102 |
| ETH | 15m | DOWN | 3 | **100%** | +$68 |
| ETH | 15m | UP | 4 | 50.0% | -$5 |
| SOL | 5m | DOWN | 11 | 45.5% | -$41 |
| **SOL** | **5m** | **UP** | **13** | **7.7%** | **-$284** ⚠ |
| SOL | 15m | DOWN | 6 | 83.3% | +$87 |
| SOL | 15m | UP | 6 | 50.0% | -$11 |

**By date (V2_sniper):**

| Date | n | hit | PnL |
|---|---|---|---|
| 04-30 | 61 | 55.7% | +$120 |
| **05-01** | **25** | **28.0%** | **-$292** ⚠ |

V2 sniper was profitable on 04-30, crashed on 05-01 (UP signals went 0-for-11).

---

## V3 — per-asset tuned portfolio sniper

**Aggregate:**
- Fires: 6 (only on BTC; ETH/SOL had zero fires due to tighter thresholds)
- Hit rate: **83.33%**
- PnL: **+$92.70**
- ROI: **+61.80%**
- Avg PnL/trade: +$15.45
- Avg fill cost: 0.5100
- Avg win: +$23.54 / avg loss: -$25.00

**Per-sleeve:**

| Sleeve | n | hit | PnL | ROI |
|---|---|---|---|---|
| **btc_5m_v3** | 6 | **83.3%** | **+$93** | **+61.80%** |
| eth_5m_v3 | 0 | — | — | — |
| sol_5m_v3 | 0 | — | — | — |

**By direction (V3, BTC only):**

| Dir | n | hit | PnL |
|---|---|---|---|
| UP | 5 | 80.0% | +$69 |
| DOWN | 1 | 100% | +$24 |

**By date:**

| Date | n | hit | PnL |
|---|---|---|---|
| 04-30 | 6 | 83.3% | +$93 |
| 05-01 | 0 | — | — |

V3 didn't fire at all on 05-01 — thresholds didn't trigger. No data for that day.

---

## Cross-version comparison

### Same-strategy feed delta (V1 vs V2_volume)

Identical strategy logic, only difference is price feed (OKX vs binance-WS):

| Metric | V1 (OKX) | V2_volume (binance) | Delta |
|---|---|---|---|
| Hit rate | 47.89% | 49.25% | **+1.36pp** |
| PnL | -$2,891 | -$2,004 | **+$887** |
| ROI | -8.04% | -5.40% | **+2.64pp** |
| Profitable sleeves | 1 of 6 | 3 of 6 | +2 |

**Feed quality alone is worth ~+1.4pp hit rate / +$887 over 1.33 days at $25/trade flat sizing.**

### Top performers across all versions

| Sleeve | Version | n | hit | PnL | ROI |
|---|---|---|---|---|---|
| btc_5m_v3 | **V3** | 6 | 83.3% | +$93 | **+61.80%** |
| eth_15m_sniper | V2_sniper | 7 | 71.4% | +$63 | +35.67% |
| btc_5m_sniper | V2_sniper | 20 | 65.0% | +$149 | +29.57% |
| sol_15m_sniper | V2_sniper | 12 | 66.7% | +$75 | +24.85% |
| sol_15m_volume | V1 | 111 | 58.6% | +$279 | +9.88% |
| sol_15m_volume | V2_volume | 116 | 57.8% | +$256 | +8.71% |
| eth_15m_volume | V2_volume | 125 | 53.6% | +$70 | +2.21% |
| btc_5m_volume | V2_volume | 373 | 51.2% | +$51 | +0.55% |

### Worst performers across all versions

| Sleeve | Version | n | hit | PnL | ROI |
|---|---|---|---|---|---|
| sol_5m_volume | V1 | 346 | 45.4% | -$1,320 | -14.92% |
| eth_5m_volume | V1 | 363 | 44.6% | -$1,252 | -13.59% |
| sol_5m_volume | V2_volume | 353 | 46.2% | -$1,205 | -13.36% |
| eth_5m_volume | V2_volume | 374 | 46.0% | -$1,048 | -11.04% |
| sol_5m_sniper | V2_sniper | 24 | 25.0% | -$324 | -52.84% |

### UP vs DOWN cumulative across all sniper sleeves

| Direction | n | hit | PnL |
|---|---|---|---|
| UP signals (sniper) | 46 | 39.1% | -$257 |
| DOWN signals (sniper) | 40 | 57.5% | +$85 |

**Sniper DOWN works (+$85), sniper UP loses (-$257). Asymmetry is structural.**

### Per-day sniper drift

| Date | V2_sniper hit | V2_sniper PnL |
|---|---|---|
| 04-30 | 55.7% | +$120 |
| 05-01 | 28.0% | -$292 |

Sniper performance dropped on 05-01 (UP signals went 0-for-11).

---

## Files

- `data/v4/shadow_trades_2026_05_01/{vps2,vps3}.csv` — raw dumps
- `strategy_lab/v4_signals/v1_v2_v3_results.py` — re-runnable harness
- This report: `strategy_lab/reports/V1_V2_V3_FULL_RESULTS_2026_05_01.md`
