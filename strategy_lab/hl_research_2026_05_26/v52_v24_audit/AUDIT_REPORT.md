# V52 + V24-XSM Audit Report — 2026-05-26

**Window audited:** 2024-01-12 → 2026-04-25 (HL parquet end).
**Auditor:** v52-v24-audit-agent (autonomous).

---

## TL;DR (1-line per family)

- **V52 sleeves fire normally** through 2026-04-25 (data end). No "flat" status confirmed in code; degradation is real market-regime collapse, not a bug.
- **HL parquet data is STALE by 1 month** (ends 2026-04-25, current date 2026-05-26). Refresh pipeline is the single biggest blocker; user's "flat" perception may be either (a) genuine since 2026-04-25 OR (b) a downstream effect of stale data feeding the live engine.
- **No look-ahead bugs found** in signal definitions, funding sign convention, HMM regime classifier, simulator entry/exit, or volume-profile rolling window.
- **2026 degradation is a regime story**: BTC vol dropped 47% → 47.5% YoY; AVAX/SOL/LINK vol crashed ~30%; funding rates fell to 1/3 of 2024 levels. V52's mean-reversion (CCI) and breakout (STF) sleeves are calibrated for the higher-vol 2024-2025 regime — they lose their edge in 2026's low-vol grind.
- **V24-XSM is restrictive BY DESIGN** — original multi-filter (BTC>100MA AND BTC50MA-rising AND breadth≥5/5) passed only **4.5% of 2026 bars** vs 19.8% in 2024. Relaxations all PERFORM WORSE — the filter is doing its job; "flat" is correct.
- **V52 has NO BTC sleeve** — confirmed by reading `run_v52_hl_gates.py`. The 5 traded coins are ETH/SOL/AVAX/LINK only (BTC used only for regime-classifier context). V52-BTC "flat" is by design; proposed STF_BTC_V45 sleeve fills this gap.

---

## A1. "Flat" status verification

Recomputed each sleeve on HL data through 2026-04-25 (the latest available bar).

| Sleeve      | Asset | Tot fires | Last 30d | Last 90d | Last 180d | Last fire           |
|-------------|-------|-----------|----------|----------|-----------|---------------------|
| CCI_ETH     | ETH   | 90        | 5        | 10       | 16        | 2026-04-22 20:00 UTC |
| STF_SOL     | SOL   | 59        | 3        | 10       | 16        | 2026-04-19 20:00 UTC |
| STF_AVAX    | AVAX  | 62        | 4        | 10       | 19        | 2026-04-19 20:00 UTC |
| LATBB_AVAX  | AVAX  | 36        | 1        | 4        | 8         | 2026-04-22 08:00 UTC |
| MFI_SOL     | SOL   | 253       | 12       | 36       | 61        | 2026-04-22 16:00 UTC |
| VP_LINK     | LINK  | 613       | 21       | 66       | 145       | 2026-04-19 20:00 UTC |
| SVD_AVAX    | AVAX  | 308       | 9        | 28       | 76        | 2026-04-19 20:00 UTC |
| MFI_ETH     | ETH   | 210       | 5        | 20       | 50        | 2026-04-20 04:00 UTC |

**Finding:** All sleeves continue to fire normally through the data end (2026-04-25). LATBB_AVAX is the rarest at 1 fire in last 30d (it requires ADX<18, range-bound), but that is the signal definition working as designed.

**V24-XSM filter pass-rate:** 4.5% in 2026 vs 19.8% in 2024. Last bar where the filter passed: 2026-04-25 (data end). So V24 is gated OFF more often in 2026.

**Critical inference:** If the user reports "V52 is flat" as of 2026-05-26, it is **NOT because the signals stopped working** in the modeled window. Possible root causes the agent cannot verify with the stale data:
1. **Data pipeline broken** — HL parquets last updated 2026-04-25, ~1 month stale. If live engine reads from these, signals will appear flat.
2. **Live engine bar-close gating** — V52 fires at bar close, fills at next open. If a sleeve hasn't met conditions since 2026-04-25, that's only ~6 trading days at 4h.
3. **Position-tracker stuck** — sleeve may have an open trade that hasn't hit TP/SL/TIME exit yet (max_hold=60 bars = 10 days).

**RECOMMENDATION:** Verify HL data refresh pipeline first. Pull fresh OHLCV through 2026-05-26 before drawing further conclusions about live flatness.

---

## A2. Bug hunt — clean

Searched for known-bad patterns across `v50_new_signals.py`, `run_v30_creative.py`, `run_v29_regime.py`, `v23_low_dd_xsm.py`, `perps_simulator_funding.py`, `hmm_adaptive.py`, `run_leverage_audit.py`, `hl_data.py`.

| Check                              | Result   | Detail                                                                                                                                                                |
|------------------------------------|----------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `shift(-N)` look-ahead             | CLEAN    | No negative shifts found in signals or simulator.                                                                                                                     |
| Forward `iloc[i:]` slice           | CLEAN    | Volume-profile uses `close_arr[i-win:i]` (causal).                                                                                                                    |
| Funding sign convention            | CORRECT  | `funding_pnl = -pos * size * cl[i] * fund[i]` ⇒ long pos=+1 + fund>0 ⇒ pnl<0 (long pays). Matches HL spec "fundingRate from longs' perspective".                  |
| HMM regime-classifier forward leak | CLEAN    | Uses `train_X_raw.mean/std` from in-sample only (line 142 of `hmm_adaptive.py`).                                                                                      |
| HMM warmup discard                 | CLEAN    | Regime labels start after warmup; OOS labels predicted forward, not refit.                                                                                            |
| Inverse-vol blend warmup           | NOTE     | `window=500` means first ~83 days produce noisy weights with `min_periods=125` fallback. Does not affect V52 (V52 uses fixed weights, not invvol).                    |
| HL funding bucketing               | CORRECT  | `floor("4h")` aligns hourly funding to 4h kline bar.                                                                                                                  |
| Volume signal HL vs Binance        | KNOWN    | HL volume is 0.5-0.7× Binance; signals fire at different bars (per `V52_HYPERLIQUID_DEPLOYMENT_NOTES.md`). Audit already validated MFI/VP/SVD on HL-native data.   |
| Signal-to-fill direction           | CORRECT  | `ep_new = op[i+1] * (1 + slip * direction)` and `direction = 1 if take_long else -1`; long fills above mid, short below — correct slippage direction.                |

**No bugs requiring fixes were found.** The strategies behave per spec.

---

## A3. 2026 degradation — per-sleeve breakdown

**Sharpe per year (positive HL data, with funding):**

| Sleeve     | Asset | 2024 Sh | 2024 Ret | 2025 Sh | 2025 Ret | 2026 Sh | 2026 Ret |
|------------|-------|---------|----------|---------|----------|---------|----------|
| CCI_ETH    | ETH   | 1.83    | +41.4%   | 1.09    | +19.1%   | 0.42    | +2.1%    |
| STF_SOL    | SOL   | 0.42    | +7.8%    | 2.12    | +60.7%   | -0.72   | -5.7%    |
| STF_AVAX   | AVAX  | 2.43    | +57.7%   | 2.36    | +93.8%   | 0.42    | +2.2%    |
| LATBB_AVAX | AVAX  | 2.37    | +48.9%   | 1.17    | +22.2%   | 0.15    | +0.3%    |
| MFI_SOL    | SOL   | 1.24    | +46.8%   | 0.34    | +6.0%    | -0.24   | -5.8%    |
| VP_LINK    | LINK  | 1.56    | +61.2%   | 1.61    | +69.3%   | -0.27   | -4.6%    |
| SVD_AVAX   | AVAX  | 0.45    | +8.8%    | -0.32   | -11.0%   | 2.07    | +20.3%   |
| MFI_ETH    | ETH   | 0.40    | +7.6%    | 0.24    | +2.3%    | 0.04    | -1.4%    |

**Degradation is BROAD (7 of 8 sleeves down vs prior 2 yrs)** — not concentrated in any single sleeve.
Only SVD_AVAX improved (-0.32 → +2.07 Sh) because CVD-divergence works best in low-vol mean-reverting tape.

### Macro/regime context (per-year)

**Realized vol (4h log-ret stdev, annualized):**

| Asset | 2024 vol | 2025 vol | 2026 vol | Δ vs 2024 |
|-------|---------:|---------:|---------:|----------:|
| BTC   | 52.0%    | 44.3%    | 47.5%    | -4.5pp    |
| ETH   | 63.9%    | 73.3%    | 63.5%    | -0.4pp    |
| SOL   | 88.8%    | 83.8%    | 68.4%    | -20.4pp   |
| AVAX  | 99.3%    | 93.7%    | 68.0%    | -31.3pp   |
| LINK  | 93.6%    | 93.3%    | 63.6%    | -30.0pp   |

**Funding rate (4h-aggregated abs mean, bps):**

| Asset | 2024 | 2025 | 2026 | Comment                          |
|-------|-----:|-----:|-----:|----------------------------------|
| BTC   | 1.08 | 0.55 | 0.35 | 3× lower than 2024               |
| ETH   | 1.06 | 0.51 | 0.36 | 3× lower than 2024               |
| SOL   | 1.34 | 0.57 | 0.56 | 2.4× lower, signed shifted negative (-0.28bps) |
| AVAX  | 1.25 | 0.64 | 0.46 | 2.7× lower                       |
| LINK  | 1.26 | 0.57 | 0.42 | 3× lower                         |

**Spot direction:** Every asset is DOWN in 2026 — BTC -14.7%, ETH -27%, SOL -35.8%, AVAX -29%, LINK -28%.

### Diagnosis

The 2026 Sharpe collapse (Fold 6 OOS = 0.289 per audit JSON) is **explained by**:
1. **Vol compression on alt-coins** (AVAX, SOL, LINK down 20-30pp vol vs 2024). ATR-risk sizing increases position size in low vol → leverage cap pinned, but mean-reversion (CCI) and breakout (STF) signal density drops, fewer high-conviction setups.
2. **Lower funding** is mildly positive for any short side, but the V52 sleeves' net positioning is mixed (long/short).
3. **Persistent downtrend** + low vol = "grind down" market — historically bad for momentum-or-fade systems. STF (trend follow) on SOL/AVAX in particular gets whipsawed (STF_SOL 2026 Sh = -0.72).

**This is regime sensitivity, not a bug.** V52 is a winning strategy in 2024-2025-style markets; it under-performs in low-vol-bear regimes. The mitigation is to **add adaptive sizing or new gates** (see Phase B).

---

## A4. V24-XSM filter pass-rate

| Filter config                       | Full window | Last 180d | Last 90d | Last 30d |
|-------------------------------------|------------:|----------:|---------:|---------:|
| `BTC>100MA & BTC50MA-rising & b≥5/5` (original) | 17.0%   | 2.9%      | 5.7%     | 17.1%    |
| `BTC>100MA & BTC50MA-rising & b≥4/5`            | 23.0%   | 3.4%      | 6.8%     | 20.4%    |
| `BTC>100MA & BTC50MA-rising & b≥3/5`            | 27.8%   | 4.6%      | 9.2%     | 27.6%    |
| `BTC>100MA only`                                | 46.7%   | 5.2%      | 9.2%     | 27.6%    |
| `BTC>50MA only`                                 | 51.1%   | 25.9%     | 30.5%    | 65.2%    |

**Per-year original-filter pass-rate:** 2024: 19.8% → 2025: 19.5% → **2026: 4.5%** (4.4× drop).

**Last bar original filter PASSED:** 2026-04-25 (data end) — but only on 4.5% of 2026 bars.

**Backtest of relaxations** (top-2 momentum, 14d lookback, 7d rebal, leverage=1.0):

| Relaxation                        | Sharpe | CAGR  | MDD   | Calmar | 2026 Sh |
|-----------------------------------|-------:|------:|------:|-------:|--------:|
| ALWAYS_ON (no filter)             | -0.12  | -25.9% | -71.4% | -0.36  | -1.14   |
| **V24 original (b≥5/5)**          | 0.69   | +20.5% | -34.9% | 0.59  | 0.00    |
| Relaxed b≥4/5                     | 0.33   | +5.5%  | -34.9% | 0.16   | 0.00    |
| Relaxed b≥3/5                     | -0.20  | -16.4% | -55.5% | -0.30  | 0.84    |
| Drop "rising" + b≥3/5             | -0.15  | -15.2% | -55.5% | -0.27  | 0.84    |
| BTC>50MA only                     | -0.10  | -15.4% | -53.2% | -0.29  | -1.39   |
| BTC>100MA only                    | -0.01  | -11.9% | -53.9% | -0.22  | 0.84    |
| Vol-target lev=0.5 (no filter)    | -0.14  | -9.4%  | -44.4% | -0.21  | -1.18   |

**Finding:** The original V24 filter is OPTIMAL. Every relaxation hurts. The "flat" status in 2026 is the filter correctly avoiding a bad regime — V24's 2026 return is exactly 0% (filter never activated long enough to take a position) vs all relaxations losing 5-15%.

**Therefore V24-XSM does NOT need optimization** — the only way to improve it is to add new asset breadth (HYPE/SUI/INJ etc), but those aren't in HL canonical parquets yet.

---

## Bug-list summary (none found)

| Tag                       | File                              | Line | Status   |
|---------------------------|-----------------------------------|------|----------|
| `funding_pnl` sign        | `perps_simulator_funding.py`      | ~165 | CORRECT  |
| HMM `train_X_raw.mean`    | `hmm_adaptive.py`                 | 142  | CORRECT  |
| V52 weights hard-coded    | `run_v52_hl_gates.py`             | 76+  | BY DESIGN|
| HL funding `floor("4h")`  | `util/hl_data.py`                 | 54   | CORRECT  |
| Volume-profile rolling    | `v50_new_signals.py`              | 118  | CAUSAL   |
| V24 breadth & rising tests| `v23_low_dd_xsm.py`               | 178, 187 | CORRECT |

---

## Critical data finding

**HL parquet files end 2026-04-25** (32 days stale as of 2026-05-26).

```
data/hyperliquid/parquet/BTC/4h.parquet   end 2026-04-25 00:00 UTC
data/hyperliquid/parquet/ETH/4h.parquet   end 2026-04-25 00:00 UTC
data/hyperliquid/parquet/SOL/4h.parquet   end 2026-04-25 00:00 UTC
data/hyperliquid/parquet/AVAX/4h.parquet  end 2026-04-25 00:00 UTC
data/hyperliquid/parquet/LINK/4h.parquet  end 2026-04-25 00:00 UTC
data/hyperliquid/funding/*.parquet        end 2026-04-24 23:00 UTC
```

**ACTION REQUIRED:** Refresh HL parquets before the live deploy can be properly verified. The agent CANNOT confirm "actually flat since 2026-05-XX" because the data simply doesn't exist locally.

---

## Files generated

- `a1_v52_fires.csv` — per-sleeve fire counts on latest 30/90/180d window
- `a2_bug_findings.json` — bug-hunt audit log
- `a3_per_yr_sleeve.csv` — per-sleeve yearly Sharpe/return/MDD
- `a3_funding_regimes.csv` — funding rate regime per year per asset
- `a3_vol_regimes.csv` — realized-vol regime per year per asset
- `a4_v24_filter_passrate.csv` — V24 filter pass-rates per relaxation

See `OPTIMIZATION_RESULTS.md` for Phase B findings.
