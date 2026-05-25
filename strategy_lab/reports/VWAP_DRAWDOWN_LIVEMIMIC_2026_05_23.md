# VWAP continuation — drawdown + live-mimic (2026-05-23 03:26 UTC)

Stress test of the top 5 deployable VWAP continuation configs on 28d data.

## Summary table

| config                   |   n |    wr |   avg_pnl_legacy |   sum_pnl_legacy |   max_dd |   max_loss_streak |   daily_pnl_mean |   daily_pnl_std |   sharpe_like_annual |   train_wr |   test_wr |   train_avg_pnl |   test_avg_pnl |   n_days |   live_mimic_n |   live_mimic_wr |   live_mimic_avg_pnl |   live_mimic_sum_pnl |
|:-------------------------|----:|------:|-----------------:|-----------------:|---------:|------------------:|-----------------:|----------------:|---------------------:|-----------:|----------:|----------------:|---------------:|---------:|---------------:|----------------:|---------------------:|---------------------:|
| BTC_240_5-10bps_m1v      | 546 | 0.863 |            1.996 |         1089.56  | -307.778 |                 3 |           51.884 |         122.093 |                8.119 |      0.851 |     0.89  |           2.656 |          0.457 |       21 |            528 |           0.864 |                1.912 |              1009.59 |
| BTC_60_10-15bps_f7_cross | 164 | 0.732 |            2.769 |          454.123 | -180.179 |                 6 |           23.901 |          60.179 |                7.588 |      0.693 |     0.82  |           1.904 |          4.741 |       19 |            nan |         nan     |              nan     |               nan    |
| BTC_90_10-15bps_none     | 221 | 0.778 |            1.766 |          390.386 | -113.2   |                 3 |           20.547 |          73.246 |                5.359 |      0.786 |     0.761 |           2.431 |          0.239 |       19 |            nan |         nan     |              nan     |               nan    |
| ETH_210_10-15bps_f7_m1v  | 188 | 0.926 |            1.26  |          236.836 | -103.766 |                 1 |           11.278 |          32.494 |                6.631 |      0.924 |     0.93  |           0.466 |          3.084 |       21 |            nan |         nan     |              nan     |               nan    |
| SOL_60_20-30bps_none     |  64 | 0.75  |            1.657 |          106.048 | -102.296 |                 2 |            5.892 |          28.454 |                3.956 |      0.727 |     0.8   |          -0.299 |          5.96  |       18 |            nan |         nan     |              nan     |               nan    |

## Interpretation

- **max_dd** is the worst peak-to-trough drawdown on the cumulative PnL curve, in $ at $25 notional.
- **max_loss_streak** is the longest consecutive losing trade run.
- **sharpe_like_annual** = (mean daily PnL / std daily PnL) × √365. Treats trades as IID — directional but useful.
- **train_wr / test_wr** is a 70/30 walk-forward split (NOT random shuffle — chronological).
- **live_mimic_***: LiveMimicConfig refills the top config with a HYPOTHETICAL fee curve `0.07·p·(1−p)` per share (from Polymarket general docs) + 85ms latency + min_book_events=25 filter. **This is NOT the production fee** — per CLAUDE.md, production-actual fees on BTC/ETH/SOL crypto up-down markets are **2%-on-profit-only** (the LegacyConfig column above, verified vs 25,900 prod resolutions). Live-mimic here is a stress test for "what if Polymarket flips to general docs fees", not current reality.

## Deployability verdict

Production-actual: use `sum_pnl_legacy` column — that's the 2%-on-profit-only number that matches live shadow accounting. Strategy is deploy-ready if `sum_pnl_legacy > 0` AND `test_wr >= 60%` AND `max_dd / sum_pnl_legacy > -0.3` (DD < 30% of total profit). live_mimic_* is the worst-case stress test only.

_data: `data\v4\canonical\_results\vwap_drawdown_livemimic.csv`_  
_script: `strategy_lab/meta_classifier/vwap_drawdown_livemimic.py`_