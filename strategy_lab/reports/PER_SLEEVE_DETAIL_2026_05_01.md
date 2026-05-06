# Per-Sleeve Detail — 2026-05-01 15:30 UTC

**Window:** 2026-04-30 06:10 → 2026-05-01 15:20 (1.38 days)
**Total resolutions:** 3,102 (refreshed)
**All trades:** `mode=paper`, `hedged=false`

## VPS2 status — NOT off, actively firing

| Sleeve | n_24h | last fire | mins ago |
|---|---|---|---|
| btc_5m_volume | 287 | 05-01 15:20 | 3m |
| eth_5m_volume | 288 | 05-01 15:20 | 3m |
| sol_5m_volume | 276 | 05-01 15:20 | 3m |
| btc_15m_volume | 96 | 05-01 15:15 | 8m |
| eth_15m_volume | 96 | 05-01 15:15 | 8m |
| sol_15m_volume | 90 | 05-01 15:15 | 8m |

**Strategy is firing every 5/15 minutes as designed.** If your dashboard shows zero, it's filtering by `mode=live` (these are paper) or `hedged=true` (HEDGE_HOLD policy = no perp hedge placed). The dashboard query needs to allow `mode=paper` and ignore `hedged`.

---

## Per-sleeve totals (no aggregation)

### VPS2 — V1 control arm (OKX-WS feed, volume mode only)

| Sleeve | n | wins | hit | PnL | ROI | last_fire |
|---|---|---|---|---|---|---|
| btc_15m_volume | 124 | 60 | 48.4% | -$206.06 | -6.60% | 05-01 15:15 |
| btc_5m_volume | 375 | 186 | 49.6% | -$240.91 | -2.57% | 05-01 15:20 |
| eth_15m_volume | 125 | 64 | 51.2% | -$60.77 | -1.93% | 05-01 15:15 |
| eth_5m_volume | 377 | 171 | 45.4% | **-$1,154.66** | **-12.06%** | 05-01 15:20 |
| **sol_15m_volume** | **116** | **67** | **57.8%** | **+$247.44** | **+8.39%** | 05-01 15:15 |
| sol_5m_volume | 360 | 166 | 46.1% | **-$1,244.04** | **-13.52%** | 05-01 15:20 |

### VPS3 — V2 + V3 (binance-WS feed)

| Sleeve | n | wins | hit | PnL | ROI | last_fire |
|---|---|---|---|---|---|---|
| btc_15m_sniper | 12 | 6 | 50.0% | -$7.07 | -2.33% | 05-01 15:15 |
| btc_15m_volume | 130 | 65 | 50.0% | -$108.62 | -3.32% | 05-01 15:15 |
| **btc_5m_sniper** | **23** | **16** | **69.6%** | **+$221.31** | **+38.32%** | 05-01 15:16 |
| **btc_5m_v3** | **7** | **6** | **85.7%** | **+$114.42** | **+65.38%** | 05-01 14:55 |
| btc_5m_volume | 386 | 200 | 51.8% | +$177.39 | +1.84% | 05-01 15:20 |
| eth_15m_sniper | 9 | 5 | 55.6% | +$11.28 | +4.97% | 05-01 15:15 |
| eth_15m_volume | 130 | 69 | 53.1% | +$40.23 | +1.23% | 05-01 15:15 |
| eth_5m_sniper | 16 | 7 | 43.8% | -$50.34 | -12.42% | 05-01 15:16 |
| eth_5m_volume | 387 | 182 | 47.0% | -$875.31 | -8.91% | 05-01 15:20 |
| sol_15m_sniper | 14 | 8 | 57.1% | +$24.00 | +6.76% | 05-01 15:15 |
| **sol_15m_volume** | **121** | **69** | **57.0%** | **+$224.27** | **+7.30%** | 05-01 15:15 |
| **sol_5m_sniper** | **24** | **6** | **25.0%** | **-$324.47** | **-52.84%** ⚠ | **05-01 09:35** |
| sol_5m_volume | 366 | 172 | 47.0% | -$1,098.18 | -11.75% | 05-01 15:20 |

**SOL 5m sniper hasn't fired since 09:35 today** — possibly hit kill-switch threshold or the sniper gate didn't trigger. Rest of sleeves all fired in last 8 min.

---

## Per-sleeve × direction breakdown (no aggregation)

### VPS2 (V1 / OKX feed)

| Sleeve | UP n / hit / PnL / ROI | DOWN n / hit / PnL / ROI |
|---|---|---|
| btc_15m_volume | 56 / 53.6% / +$51 / +3.66% | 68 / 44.1% / -$258 / -15.05% |
| btc_5m_volume | 185 / 49.7% / -$131 / -2.84% | 190 / 49.5% / -$110 / -2.30% |
| eth_15m_volume | 61 / 50.8% / -$42 / -2.70% | 64 / 51.6% / -$19 / -1.18% |
| eth_5m_volume | 193 / 44.6% / -$650 / -13.29% | 184 / 46.2% / -$505 / -10.78% |
| **sol_15m_volume** | **55 / 63.6% / +$266 / +19.03%** ⭐ | 61 / 52.5% / -$19 / -1.19% |
| sol_5m_volume | 186 / 46.2% / -$648 / -13.71% | 174 / 46.0% / -$596 / -13.32% |

### VPS3 (V2 / binance-WS)

| Sleeve | UP n / hit / PnL / ROI | DOWN n / hit / PnL / ROI |
|---|---|---|
| btc_15m_sniper | 4 / 75.0% / +$48 / +47.21% | 8 / 37.5% / -$55 / -27.29% |
| btc_15m_volume | 60 / 55.0% / +$97 / +6.45% | 70 / 45.7% / -$206 / -11.69% |
| **btc_5m_sniper** | **14 / 64.3% / +$99 / +28.08%** | **9 / 77.8% / +$123 / +54.24%** ⭐ |
| **btc_5m_v3** | **5 / 80.0% / +$69 / +55.33%** | **2 / 100% / +$45 / +90.53%** ⭐ |
| btc_5m_volume | 191 / 52.4% / +$118 / +2.47% | 195 / 51.3% / +$59 / +1.21% |
| eth_15m_sniper | 5 / 40.0% / -$31 / -24.73% | 4 / 75.0% / +$43 / +42.46% |
| eth_15m_volume | 65 / 52.3% / -$5 / -0.33% | 65 / 53.8% / +$46 / +2.78% |
| eth_5m_sniper | 11 / 45.5% / -$24 / -8.51% | 5 / 40.0% / -$27 / -20.91% |
| eth_5m_volume | 191 / 46.6% / -$452 / -9.34% | 196 / 47.4% / -$423 / -8.49% |
| sol_15m_sniper | 7 / 42.9% / -$37 / -20.99% | 7 / 71.4% / +$61 / +34.44% |
| **sol_15m_volume** | **59 / 62.7% / +$263 / +17.58%** ⭐ | 62 / 51.6% / -$39 / -2.48% |
| **sol_5m_sniper** | **13 / 7.7% / -$284 / -85.63%** ⚠⚠ | 11 / 45.5% / -$41 / -14.40% |
| sol_5m_volume | 188 / 45.7% / -$688 / -14.41% | 178 / 48.3% / -$410 / -8.96% |

---

## Per (asset × tf × direction) — across all sleeves and hosts

| Asset | TF | Dir | n | wins | hit | PnL | ROI |
|---|---|---|---|---|---|---|---|
| BTC | 15m | DOWN | 146 | 65 | 44.5% | -$519 | -14.11% |
| BTC | 15m | UP | 120 | 66 | 55.0% | +$197 | +6.52% |
| BTC | 5m | DOWN | 396 | 203 | 51.3% | +$118 | +1.19% |
| BTC | 5m | UP | 395 | 205 | 51.9% | +$154 | +1.56% |
| ETH | 15m | DOWN | 133 | 71 | 53.4% | +$69 | +2.06% |
| ETH | 15m | UP | 131 | 67 | 51.1% | -$78 | -2.37% |
| ETH | 5m | DOWN | 385 | 180 | 46.8% | -$955 | -9.75% |
| ETH | 5m | UP | 395 | 180 | 45.6% | -$1,125 | -11.25% |
| SOL | 15m | DOWN | 130 | 69 | 53.1% | +$4 | +0.11% |
| **SOL** | **15m** | **UP** | **121** | **75** | **62.0%** | **+$492** | **+16.01%** ⭐ |
| SOL | 5m | DOWN | 363 | 171 | 47.1% | -$1,046 | -11.22% |
| **SOL** | **5m** | **UP** | **387** | **173** | **44.7%** | **-$1,621** | **-16.48%** ⚠ |

---

## Standout findings

### Profitable sleeves (sorted by ROI)

| Sleeve | Host | n | hit | PnL | ROI |
|---|---|---|---|---|---|
| btc_5m_v3 | vps3 | 7 | 85.7% | +$114 | +65.4% |
| btc_5m_sniper | vps3 | 23 | 69.6% | +$221 | +38.3% |
| sol_15m_volume | vps2 | 116 | 57.8% | +$247 | +8.4% |
| sol_15m_volume | vps3 | 121 | 57.0% | +$224 | +7.3% |
| sol_15m_sniper | vps3 | 14 | 57.1% | +$24 | +6.8% |
| eth_15m_sniper | vps3 | 9 | 55.6% | +$11 | +5.0% |
| btc_5m_volume | vps3 | 386 | 51.8% | +$177 | +1.8% |
| eth_15m_volume | vps3 | 130 | 53.1% | +$40 | +1.2% |

### Losing sleeves

| Sleeve | Host | n | hit | PnL | ROI |
|---|---|---|---|---|---|
| sol_5m_sniper | vps3 | 24 | 25.0% | -$324 | -52.8% |
| sol_5m_volume | vps2 | 360 | 46.1% | -$1,244 | -13.5% |
| eth_5m_volume | vps2 | 377 | 45.4% | -$1,155 | -12.1% |
| sol_5m_volume | vps3 | 366 | 47.0% | -$1,098 | -11.7% |
| eth_5m_sniper | vps3 | 16 | 43.8% | -$50 | -12.4% |
| eth_5m_volume | vps3 | 387 | 47.0% | -$875 | -8.9% |
| btc_15m_volume | vps2 | 124 | 48.4% | -$206 | -6.6% |
| btc_15m_volume | vps3 | 130 | 50.0% | -$109 | -3.3% |

### Same-strategy host comparison (V1 vs V2_volume)

Same logic, only different feed:

| Sleeve | V1 (vps2) ROI | V2 (vps3) ROI | feed delta |
|---|---|---|---|
| btc_5m_volume | -2.57% | **+1.84%** | +4.41pp ⭐ |
| btc_15m_volume | -6.60% | -3.32% | +3.28pp |
| eth_5m_volume | -12.06% | -8.91% | +3.15pp |
| eth_15m_volume | -1.93% | +1.23% | +3.16pp |
| sol_5m_volume | -13.52% | -11.75% | +1.77pp |
| sol_15m_volume | +8.39% | +7.30% | -1.09pp |

**5 of 6 sleeves: V2 beats V1 by 1.8-4.4pp ROI.** Feed quality matters.

### Top single sleeve+direction combos

**Best ROI per single bucket:**
1. btc_5m_v3 DOWN: 90.5% ROI (n=2, small)
2. sol_5m_sniper UP — **WORST: -85.6% ROI** (n=13)
3. btc_5m_v3 UP: 55.3% ROI (n=5)
4. btc_5m_sniper DOWN: 54.2% ROI (n=9)
5. btc_15m_sniper UP: 47.2% ROI (n=4)

### Universal patterns

- **SOL 5m UP**: across all 3 strategies on SOL 5m UP (sniper + volume on both vps), -$1,621 cumulative (-16.48% ROI). Worst single bucket overall.
- **SOL 15m UP**: opposite — across all sleeves +$492 (+16.01%). Reversal at 15m.
- **BTC 5m**: roughly breakeven across DOWN (+1.19%) and UP (+1.56%).

---

## Files

- `data/v4/shadow_trades_2026_05_01/{vps2,vps3}.csv` — refreshed 15:25 UTC
- `strategy_lab/v4_signals/per_sleeve_detail.py` — re-runnable harness
- This report: `strategy_lab/reports/PER_SLEEVE_DETAIL_2026_05_01.md`
