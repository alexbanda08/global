"""PHASE A4 — V24 multi-filter pass-rate audit + relaxation tests."""
import sys
from pathlib import Path
import pandas as pd
import numpy as np
sys.path.insert(0, "C:/Users/alexandre bandarra/Desktop/global")
import warnings; warnings.filterwarnings("ignore")

from strategy_lab.util.hl_data import load_hl

# V24's universe — original (Binance) had 9 coins, but HL has 5
# Use HL-native: 5 coins + check filter pass-rate for relaxations
COINS = ["BTC", "ETH", "SOL", "AVAX", "LINK"]
BARS_PER_DAY = 6  # 4h bars

dfs = {sym: load_hl(sym, "4h", start="2023-04-01", end="2026-04-25") for sym in COINS}
# Align indices
all_idx = None
for sym in COINS:
    idx = dfs[sym].index
    all_idx = idx if all_idx is None else all_idx.intersection(idx)
close = pd.DataFrame({sym: dfs[sym]["close"].reindex(all_idx) for sym in COINS})

# Compute filters
btc_ma100 = close["BTC"].rolling(100*BARS_PER_DAY).mean()
btc_ma50  = close["BTC"].rolling(50 *BARS_PER_DAY).mean()
btc_above_100 = close["BTC"] > btc_ma100
# rising = 50d MA today > 50d MA 1-day ago
btc_50_rising = btc_ma50 > btc_ma50.shift(BARS_PER_DAY)

per_coin_ma50 = {sym: close[sym].rolling(50*BARS_PER_DAY).mean() for sym in COINS}
breadth = sum((close[sym] > per_coin_ma50[sym]).astype(int) for sym in COINS)
# breadth max is 5 in HL (was 9 in original)

# === Pass-rate of filter combinations ===
print("="*90)
print(f"V24-XSM filter pass-rates on HL universe (5 coins), {all_idx[0]} -> {all_idx[-1]}")
print("="*90)

last_180d_idx = all_idx[all_idx >= (all_idx[-1] - pd.Timedelta(days=180))]
last_90d_idx = all_idx[all_idx >= (all_idx[-1] - pd.Timedelta(days=90))]
last_30d_idx = all_idx[all_idx >= (all_idx[-1] - pd.Timedelta(days=30))]

# Original (HL-adapted) — breadth>=5/5 ≈ breadth>=3/5 scaling (5/9 was 56%, on HL = 3/5)
def pct_active(filt, idx):
    return float(filt.loc[idx].mean()) * 100

filt_configs = [
    ("original_BTC100_BTC50rising_breadth5/5", btc_above_100 & btc_50_rising & (breadth >= 5)),
    ("original_BTC100_BTC50rising_breadth4/5", btc_above_100 & btc_50_rising & (breadth >= 4)),
    ("original_BTC100_BTC50rising_breadth3/5", btc_above_100 & btc_50_rising & (breadth >= 3)),
    ("relaxed_BTC100_breadth3/5",              btc_above_100                & (breadth >= 3)),
    ("relaxed_BTC100_breadth2/5",              btc_above_100                & (breadth >= 2)),
    ("relaxed_BTC100only",                     btc_above_100),
    ("relaxed_BTC50only",                      close["BTC"] > btc_ma50),
    ("very_loose_breadth_only_3/5",            (breadth >= 3)),
    ("very_loose_breadth_only_2/5",            (breadth >= 2)),
]
rows = []
for name, filt in filt_configs:
    full = pct_active(filt, all_idx[~filt.isna()])
    p180 = pct_active(filt, last_180d_idx[last_180d_idx.isin(filt.dropna().index)])
    p90 = pct_active(filt, last_90d_idx[last_90d_idx.isin(filt.dropna().index)])
    p30 = pct_active(filt, last_30d_idx[last_30d_idx.isin(filt.dropna().index)])
    print(f"  {name:48s} | full={full:5.1f}%  180d={p180:5.1f}%  90d={p90:5.1f}%  30d={p30:5.1f}%")
    rows.append(dict(filter=name, full_pct=round(full,2), pct_180d=round(p180,2),
        pct_90d=round(p90,2), pct_30d=round(p30,2)))
dfo = pd.DataFrame(rows)
dfo.to_csv("C:/Users/alexandre bandarra/Desktop/global/strategy_lab/hl_research_2026_05_26/v52_v24_audit/a4_v24_filter_passrate.csv", index=False)

# === Find last date the ORIGINAL filter PASSED ===
orig = btc_above_100 & btc_50_rising & (breadth >= 5)
last_pass_orig = orig[orig].index.max() if orig.any() else None
loose_breadth3 = btc_above_100 & btc_50_rising & (breadth >= 3)
last_pass_b3 = loose_breadth3[loose_breadth3].index.max() if loose_breadth3.any() else None
btconly = close["BTC"] > btc_ma100
last_pass_btconly = btconly[btconly].index.max() if btconly.any() else None

print()
print(f"Last bar ORIGINAL filter PASSED (breadth>=5/5):  {last_pass_orig}")
print(f"Last bar relaxed b>=3/5 PASSED:                  {last_pass_b3}")
print(f"Last bar BTC>100MA only PASSED:                  {last_pass_btconly}")
print(f"Data end:                                        {all_idx[-1]}")

# === 2024/2025/2026 pass-rate per filter ===
print()
print("Per-year pass-rate of ORIGINAL filter:")
for yr in [2024, 2025, 2026]:
    yridx = all_idx[all_idx.year == yr]
    if len(yridx) > 30:
        pct = pct_active(orig, yridx[yridx.isin(orig.dropna().index)])
        print(f"  {yr}: {pct:.1f}%")
