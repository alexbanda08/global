"""
Phase C verification: SUI/TON 4h native load + BTC 2h / DOGE 30m resample.
Run from repo root: python strategy_lab/verify_phase_c.py
"""
import sys
from pathlib import Path

# Ensure strategy_lab is importable when run from any dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "strategy_lab"))
from engine import load


def check(label, df):
    if df is None or len(df) == 0:
        print(f"[FAIL] {label}: empty DataFrame")
        return
    print(f"[OK]   {label}: {len(df)} bars  {df.index[0]}  to  {df.index[-1]}")


print("=" * 68)
print("Phase C verification")
print("=" * 68)

# 1. SUIUSDT 4h native
df_sui = load("SUIUSDT", "4h", "2023-06-01", "2026-04-24")
check("SUIUSDT 4h  (2023-06-01 to 2026-04-24)", df_sui)

# 2. TONUSDT 4h native
df_ton = load("TONUSDT", "4h", "2022-11-01")
check("TONUSDT 4h  (2022-11-01 to today)", df_ton)

# 3. BTCUSDT 2h resample (from 1h)
df_btc_1h = load("BTCUSDT", "1h", "2022-01-01")
df_btc_2h = load("BTCUSDT", "2h", "2022-01-01")
check("BTCUSDT 1h  (2022-01-01 to today, source)", df_btc_1h)
check("BTCUSDT 2h  (2022-01-01 to today, resampled)", df_btc_2h)
ratio_btc = len(df_btc_1h) / max(len(df_btc_2h), 1)
print(f"       1h/2h ratio: {ratio_btc:.3f}  (expect ~2.0)")

# 4. DOGEUSDT 30m resample (from 15m)
df_doge_15 = load("DOGEUSDT", "15m", "2022-01-01")
df_doge_30 = load("DOGEUSDT", "30m", "2022-01-01")
check("DOGEUSDT 15m (2022-01-01 to today, source)", df_doge_15)
check("DOGEUSDT 30m (2022-01-01 to today, resampled)", df_doge_30)
ratio_doge = len(df_doge_15) / max(len(df_doge_30), 1)
print(f"       15m/30m ratio: {ratio_doge:.3f}  (expect ~2.0)")

print("=" * 68)
print("Verification complete.")
