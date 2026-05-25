# VWAP continuation — 15m markets (2026-05-23 14:04 UTC)

Same strategy as `vwap_continuation_5m.py`, applied to 15m markets. Fire offsets 60-840s into 900s slot.

## Deployable (n>=30, WR>=60%, $/tr > 0)

| asset   |   fire_offset_s | dev_tier   |   n |    wr |   avg_pnl |   sum_pnl |   avg_entry |
|:--------|----------------:|:-----------|----:|------:|----------:|----------:|------------:|
| SOL     |             840 | 20-30bps   |  40 | 0.775 |    17.343 |   693.713 |       0.775 |
| ETH     |             480 | 5-10bps    | 449 | 0.768 |     0.611 |   274.493 |       0.746 |
| SOL     |             240 | 10-15bps   | 116 | 0.828 |     1.792 |   207.819 |       0.791 |
| ETH     |             120 | 10-15bps   |  40 | 0.825 |     4.205 |   168.212 |       0.739 |
| ETH     |             720 | 15-20bps   |  45 | 0.778 |     3.475 |   156.357 |       0.791 |
| ETH     |             240 | 10-15bps   |  68 | 0.868 |     1.98  |   134.626 |       0.785 |
| SOL     |             360 | 10-15bps   | 165 | 0.824 |     0.678 |   111.902 |       0.819 |
| ETH     |             480 | 15-20bps   |  58 | 0.897 |     1.234 |    71.552 |       0.878 |
| BTC     |             360 | 10-15bps   |  75 | 0.867 |     0.685 |    51.35  |       0.831 |
| BTC     |             480 | 10-15bps   |  98 | 0.898 |     0.331 |    32.407 |       0.866 |
| SOL     |             600 | 10-15bps   | 179 | 0.888 |     0.082 |    14.653 |       0.855 |
| ETH     |             600 | 5-10bps    | 485 | 0.775 |     0.019 |     9.024 |       0.758 |
| SOL     |             120 | 10-15bps   |  56 | 0.75  |     0.143 |     8.031 |       0.751 |
| BTC     |             240 | 10-15bps   |  52 | 0.808 |     0.004 |     0.199 |       0.792 |

## Ultra-strict (n>=100, WR>=70%, $/tr>=$1)

| asset   |   fire_offset_s | dev_tier   |   n |    wr |   avg_pnl |   sum_pnl |   avg_entry |
|:--------|----------------:|:-----------|----:|------:|----------:|----------:|------------:|
| SOL     |             240 | 10-15bps   | 116 | 0.828 |     1.792 |   207.819 |       0.791 |

_data: `data\v4\canonical\_results\vwap_continuation_15m.csv`_  
_per-fire: `data\v4\canonical\_results\vwap_continuation_15m_per_fire.parquet`_