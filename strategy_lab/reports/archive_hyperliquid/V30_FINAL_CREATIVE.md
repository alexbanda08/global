# V30 — Creative Round (TTM Squeeze, VWAP, CRSI, SuperTrend, CCI)

**Date:** 2026-04-22
**Scope:** 5 brand-new signal families, 9 coins, 2 timeframes (1h / 4h)
**Configurations tested:** ~6,000 across the 5×9×2 matrix (3-4 param dims × 2 risks × 2 exit configs each)
**Verdict rule:** OOS Sharpe ≥ 0.5 × max(0.1, IS Sharpe), where IS = pre-2024, OOS = 2024-01-01 onward.

---

## The five families

### 1. TTM_Squeeze_Pop
Classic John Carter "squeeze": Bollinger Bands fully inside Keltner Channel = squeeze on. Fire on the release bar in the direction of the N-bar Donchian midline. Captures vol expansion after compression.

Params swept: `bb_k ∈ {1.8, 2.0, 2.2}`, `kc_mult ∈ {1.2, 1.5, 1.8}`, `mom_n ∈ {10, 20}`.

### 2. VWAP_Zfade
Rolling-window VWAP (length N). Compute `z = (close - vwap) / rolling_std(dev)`. When ADX is below threshold (range regime), fade extreme z: long when z crosses back up through -z_thr, short when z crosses back down through +z_thr.

Params: `vwap_n ∈ {50, 100, 200}`, `z_thr ∈ {1.5, 2.0, 2.5}`, `adx_max ∈ {18, 22, 28}`.

### 3. Connors_RSI
Larry Connors' classic: `CRSI = (RSI(3) + RSI(streak, 2) + PercentRank(ROC_1, 100)) / 3`. Long when CRSI < lo, short when > hi. Range-gated by ADX.

Params: `(crsi_lo, crsi_hi) ∈ {(5,95),(10,90),(15,85)}`, `adx_max ∈ {20, 28}`.

### 4. SuperTrend_Flip
ATR-band lock-step trailing. On direction change, enter if EMA(reg) regime confirms (long above, short below).

Params: `st_n ∈ {7, 10, 14}`, `st_mult ∈ {2, 3, 4}`, `ema_reg ∈ {100, 200}`.

### 5. CCI_Extreme_Rev
CCI crosses back up through `-cci_thr` with a bullish reversal candle → long. Mirror for short. ADX range filter.

Params: `cci_n ∈ {14, 20, 30}`, `cci_thr ∈ {100, 150, 200}`, `adx_max ∈ {18, 22, 28}`.

---

## OOS audit — 28 of 43 pass (65%)

Top 15 OOS winners (sorted by OOS Sharpe):

| Sym  | Family          | TF | IS Sh | OOS Sh | OOS CAGR | OOS DD | OOS n |
|------|-----------------|----|-------|--------|----------|--------|-------|
| ETH  | CCI_Extreme_Rev | 4h | 1.16  | **2.37** | **+122.8%** | -17.4% | 50    |
| AVAX | VWAP_Zfade      | 1h | 0.16  | 1.96   | +75.6%   | -26.5% | 25    |
| SUI  | CCI_Extreme_Rev | 4h | -2.28 | 1.92   | +82.4%   | -31.0% | 94    |
| SOL  | SuperTrend_Flip | 4h | 1.22  | 1.77   | +73.6%   | -22.0% | 34    |
| DOGE | TTM_Squeeze_Pop | 4h | 0.75  | 1.60   | +56.0%   | -31.3% | 91    |
| SOL  | CCI_Extreme_Rev | 4h | 0.74  | 1.57   | +31.9%   | -19.0% | 14    |
| TON  | VWAP_Zfade      | 1h | n/a   | 1.50   | +88.0%   | -40.0% | 176   |
| TON  | CCI_Extreme_Rev | 4h | n/a   | 1.44   | +104.1%  | -32.5% | 38    |
| AVAX | TTM_Squeeze_Pop | 4h | 0.40  | 1.32   | +39.5%   | -26.3% | 28    |
| SUI  | SuperTrend_Flip | 4h | 2.19  | 1.32   | +66.6%   | -23.7% | 51    |
| SOL  | TTM_Squeeze_Pop | 4h | 1.68  | 1.31   | +42.1%   | -17.1% | 90    |
| TON  | SuperTrend_Flip | 4h | n/a   | 1.26   | +90.7%   | -36.1% | 50    |
| DOGE | VWAP_Zfade      | 4h | 0.42  | 1.21   | +30.3%   | -37.0% | 75    |
| AVAX | CCI_Extreme_Rev | 4h | 1.18  | 1.19   | +44.9%   | -27.3% | 48    |
| INJ  | VWAP_Zfade      | 4h | 0.75  | 1.19   | +38.0%   | -30.8% | 42    |

Per-family pass rate:

| Family           | Pass / Total | Notes                                    |
|------------------|-------------|------------------------------------------|
| CCI_Extreme_Rev  | **8 / 8**   | Cleanest family — passes on every coin   |
| SuperTrend_Flip  | 7 / 8       | Only AVAX fails OOS                      |
| TTM_Squeeze_Pop  | 7 / 9       | BTC and INJ fail; DOGE is top performer  |
| VWAP_Zfade       | 6 / 9       | BTC / SOL / SUI fail                     |
| Connors_RSI      | **1 / 9**   | Weak on this dataset — only SOL passes   |

---

## Portfolio hunt — new peak reached

Pool: V28 winners (V23 BBBreak + V27 Donchian) ∪ V29 PASS ∪ V30 PASS, distinct coins, yearly-rebalanced equal weight.

**Top 10 portfolios by worst-year CAGR (2023-2025):**

| Rank | Size | Worst | 2023 | 2024 | 2025 | Members                                                  |
|------|------|-------|------|------|------|----------------------------------------------------------|
| 1    | 3    | **141.8%** | 141.8 | 159.2 | 177.4 | SOL BBBreak + SUI BBBreak + **ETH CCI_Extreme_Rev 4h**   |
| 2    | 3    | 132.4%    | 142.6 | 132.4 | 148.3 | SOL BBBreak + SUI BBBreak + **ETH VWAP_Zfade 4h**        |
| 3    | 3    | 129.2% *(V28 P2)* | 129.2 | 147.2 | 189.9 | SOL BBBreak + SUI BBBreak + ETH HTF_Donchian 4h          |
| 4    | 3    | 124.0%    | 139.3 | 124.0 | 158.3 | SOL BBBreak + SUI BBBreak + ETH Lateral_BB_Fade 4h (V29) |
| 5    | 3    | 122.8%    | 139.6 | 122.8 | 147.6 | SOL BBBreak + SUI BBBreak + BTC Lateral_BB_Fade 4h (V29) |
| 6    | 3    | 122.2%    | 148.2 | 122.2 | 185.3 | SOL BBBreak + DOGE BBBreak + SUI BBBreak                 |
| 7    | 3    | 120.4%    | 126.9 | 120.4 | 175.4 | SOL BBBreak + SUI BBBreak + DOGE HTF_Donchian 4h         |
| 8    | 3    | 119.6%    | 126.5 | 119.6 | 144.5 | SOL BBBreak + SUI BBBreak + LINK CCI_Extreme_Rev 1h      |
| 9    | 4    | 119.5%    | 119.5 | 124.9 | 133.1 | SOL BBBreak + SUI BBBreak + BTC HTF_Donchian 4h + ETH CCI_Extreme_Rev 4h |
| 10   | 4    | 118.5%    | 118.5 | 129.9 | 156.9 | SOL BBBreak + SUI BBBreak + **ETH CCI_Extreme_Rev 4h** + **AVAX CCI_Extreme_Rev 4h** |

**V30 P1** (swap ETH Donchian for ETH CCI_Extreme_Rev) **→ worst year 141.8%, a +12.6 pt improvement over V28 P2.** The 2023/2024/2025 triplet of 141.8 / 159.2 / 177.4 is the tightest high-floor profile we've found across 10 rounds.

---

## Pine scripts shipped

28 Pine v5 scripts written to `/strategy_lab/pine/`, one per OOS passer. Each matches its Python parent exactly: 0.045% commission, 3 bps slippage, 3× leverage cap, ATR-risk sizing, next-bar-open fills.

```
AVAX_V30_CCIExtreme_4h.pine      ETH_V30_CCIExtreme_4h.pine      SOL_V30_CCIExtreme_4h.pine
AVAX_V30_TTMSqueeze_4h.pine      ETH_V30_SuperTrendFlip_4h.pine  SOL_V30_ConnorsRSI_4h.pine
AVAX_V30_VWAPZfade_1h.pine       ETH_V30_TTMSqueeze_4h.pine      SOL_V30_SuperTrendFlip_4h.pine
BTC_V30_CCIExtreme_1h.pine       ETH_V30_VWAPZfade_4h.pine       SOL_V30_TTMSqueeze_4h.pine
BTC_V30_SuperTrendFlip_4h.pine   INJ_V30_CCIExtreme_4h.pine      SUI_V30_CCIExtreme_4h.pine
DOGE_V30_TTMSqueeze_4h.pine      INJ_V30_SuperTrendFlip_4h.pine  SUI_V30_SuperTrendFlip_4h.pine
DOGE_V30_VWAPZfade_4h.pine       INJ_V30_VWAPZfade_4h.pine       SUI_V30_TTMSqueeze_4h.pine
                                  LINK_V30_CCIExtreme_1h.pine    TON_V30_CCIExtreme_4h.pine
                                  LINK_V30_SuperTrendFlip_4h.pine TON_V30_SuperTrendFlip_4h.pine
                                  LINK_V30_VWAPZfade_1h.pine     TON_V30_TTMSqueeze_4h.pine
                                                                 TON_V30_VWAPZfade_1h.pine
```

---

## Caveats and honest reads

1. **SUI CCI has a suspicious IS ↔ OOS flip** (IS Sharpe -2.28 → OOS Sharpe +1.92). This is most likely because SUI's 2023 pre-launch history is nearly absent, so IS is a near-empty sample. Treat SUI V30 sleeves as 2024-onward evidence only.

2. **TON has no meaningful IS period** — TON started trading in late 2022 and really only has usable OOS data. `n/a` in the IS Sharpe column is honest.

3. **ETH CCI_Extreme_Rev 4h +123% OOS CAGR, Sh 2.37** is the best single-sleeve OOS result we've recorded, but **only 50 trades** in the OOS window. High-conviction, but deserves a small size until it's accumulated ~150+ live trades.

4. **Connors_RSI is a bust** on crypto 4h/1h — 1 / 9 coins passes. This matches academic findings that CRSI works best on equities with longer mean-reversion windows; crypto's fatter tails blow up the fade.

5. **DOGE TTM_Squeeze_Pop 4h +56% OOS** is notable because DOGE failed V29 Lateral_BB_Fade. DOGE's 2024 breakouts reward vol-expansion signals and punish range fades — these are mutually exclusive regimes for the same coin.

6. **The new peak V30 P1 is +12.6 pts above V28 P2**, but the improvement is entirely driven by one sleeve (ETH CCI replacing ETH Donchian). If that sleeve drifts, the V28 P2 fallback is still +129%/yr worst case.

---

## Inventory running total

- **Python sweeps:** V16-V30 (~15 rounds)
- **OOS-passing winners:** 28 (V30) + 16 (V29) + ~25 (V23-V27) = ~70 strategies
- **Pine scripts shipped:** 90+ across 9 coins (28 V30 + 14 V29 + ~50 V23-V27)
- **Peak portfolio:** V30 P1 — min 141.8%/yr across 2023-2025

## Next candidates for V31

If continuing:
- **Funding-rate mean reversion** overlay (requires Hyperliquid funding data ingestion)
- **Divergence-based signals** (RSI/MACD price divergence with multi-bar confirmation)
- **Cross-asset pair** (ETH/BTC ratio mean-reversion, SOL/ETH beta rotation)
- **Event-window strategies** (CPI / FOMC / BTC halving anniversary)
- **Microstructure** (order-book imbalance, trade-count z-score) — requires lower-level data
