# strategy_lab — folder layout

```
strategy_lab/
├── reports/          ← PDFs and written reports (open these to read results)
│   ├── STRATEGY_REPORT.pdf       ← MAIN consolidated report (BTC + ETH + SOL)
│   ├── PER_ASSET_REPORT.pdf      ← earlier per-asset PDF
│   ├── FINAL_REPORT.pdf          ← legacy V2B report
│   ├── FINAL_REPORT_V3E.pdf      ← legacy V3E report
│   ├── FINAL_SUMMARY.md          ← text summary
│   └── ROBUSTNESS_VERDICT.md     ← 5-test overfitting audit
│
├── pine/             ← TradingView Pine Script strategies (paste into Pine Editor)
│   ├── BTC_V4C_RangeKalman.pine         ← winner for BTCUSDT 4h
│   ├── ETH_V3B_ADXGate.pine             ← winner for ETHUSDT 4h
│   ├── SOL_V2B_VolumeBreakout.pine      ← winner for SOLUSDT 4h
│   ├── VolumeBreakout_V2B.pine          ← legacy generic V2B
│   └── VolumeBreakout_V3E.pine          ← legacy V3E (trend-validator)
│
├── results/          ← raw experiment outputs (CSV, JSON) + per-run logs
│   ├── *.csv / *.json                   ← every sweep + robustness run
│   ├── V4_*.csv                         ← per-asset winner equity curves
│   └── logs/                            ← stdout logs from each background run
│
└── [Python package at root]  ← engine, strategies, runners, PDF builders
    ├── engine.py                        ← vectorbt wrapper, look-ahead-safe
    ├── strategies.py, strategies_v2.py … strategies_v5.py
    ├── run_sweep.py / run_sweep_v2.py / run_v3.py / run_per_asset.py
    ├── portfolio.py / test_combos.py
    ├── validate.py / validate_alternatives.py / walk_forward.py / robust_validate.py
    ├── final_report.py / final_report_v3.py / per_asset_report.py / detailed_metrics.py
    └── build_pdf.py / build_pdf_v3.py / build_pdf_per_asset.py / build_consolidated_pdf.py
```

## Quick start

**View the consolidated report**
```
reports/STRATEGY_REPORT.pdf
```
This single PDF contains everything: per-asset pages, combined portfolio,
robustness tests, annual bars, strategy logic and caveats.

**Deploy a strategy on TradingView**
1. Open the relevant `.pine` file from `pine/`
2. Paste into TradingView Pine Editor → Add to chart
3. Make sure chart is the matching symbol and 4h timeframe

**Re-run the pipeline from scratch**
```bash
# (from the repo root, one level above strategy_lab/)
python -m strategy_lab.run_per_asset           # full sweep (≈5 min)
python -m strategy_lab.robust_validate         # 5 overfitting tests
python -m strategy_lab.per_asset_report        # equity CSVs + JSON summary
python -m strategy_lab.build_consolidated_pdf  # builds reports/STRATEGY_REPORT.pdf
```

## Current winners (2018-01-01 → 2026-04-01, $10,000 each)

| Asset | Strategy | Timeframe | Final | CAGR | Sharpe | MaxDD | Calmar |
|-------|----------|-----------|------:|-----:|-------:|------:|------:|
| BTC   | V4C Range Kalman        | 4h | $156,611 | 39.6 %  | 1.32 | −28.8 % | 1.38 |
| ETH   | V3B ADX Gate            | 4h | $395,501 | 56.2 %  | 1.26 | −33.8 % | 1.66 |
| SOL   | V2B Volume Breakout     | 4h | $566,967 | 104.7 % | 1.35 | −51.5 % | 2.03 |

**Combined 3 × $10,000 → $1,119,079**  (CAGR 55.1 %, MaxDD −32.2 %, Sharpe 1.43)

See `reports/STRATEGY_REPORT.pdf` for the full breakdown.
