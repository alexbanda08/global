"""Diagnose eth_5m_v2 momo collapse to 2.75% WR / -$20/trade.

109 F7 fires in 23.5h window, only 3 wins. Check:
  - signal direction distribution
  - strike vs entry vs settlement prices
  - whether outcomes consistently OPPOSE the signal (sign inversion bug?)
  - vwap entry distribution
  - fee burn analysis
"""
import json
import sys
import pandas as pd
import numpy as np

ev = pd.read_csv('strategy_lab/markov_filter/_vps3_pull/post_f7_events.csv')
ev["at"] = pd.to_datetime(ev["at"], utc=True, format="mixed")

# Get all eth_5m_v2 momo fires (F7 and non-F7)
res = ev[(ev["kind"] == "poly_updown_resolution") &
         ev["sleeve_id"].str.contains("eth_5m_momo_v2", na=False)].copy()
print(f"Total eth_5m_momo_v2 resolutions: {len(res)}")

rrows = []
for _, r in res.iterrows():
    try: d = json.loads(r["data"])
    except: continue
    d["sleeve_id"] = r["sleeve_id"]
    d["at"] = r["at"]
    rrows.append(d)
df = pd.DataFrame(rrows)
df["pnl_usd"] = pd.to_numeric(df["pnl_usd"], errors="coerce")
df["entry_price"] = pd.to_numeric(df["entry_price"], errors="coerce")
df["strike_price"] = pd.to_numeric(df["strike_price"], errors="coerce")
df["settlement_price"] = pd.to_numeric(df["settlement_price"], errors="coerce")
df["entry_qty"] = pd.to_numeric(df["entry_qty"], errors="coerce")
df["is_f7"] = df["sleeve_id"].str.endswith("_f7")

print(f'\n=== Overall WR + PnL ===')
print(f'  F7 fires:    n={df.is_f7.sum()}, wr={df[df.is_f7].won.mean()*100:.2f}%, sum_pnl=${df[df.is_f7].pnl_usd.sum():.2f}')
print(f'  no-F7 fires: n={(~df.is_f7).sum()}, wr={df[~df.is_f7].won.mean()*100:.2f}%, sum_pnl=${df[~df.is_f7].pnl_usd.sum():.2f}')

print(f'\n=== Signal direction distribution ===')
print(df.groupby(["is_f7","signal"]).agg(n=("won","size"), wr=("won","mean"), avg_pnl=("pnl_usd","mean")).round(3))

print(f'\n=== Outcome direction distribution (Up/Down counts) ===')
print(df.groupby(["is_f7","outcome"]).size())

print(f'\n=== Signal vs outcome cross-tab (F7 fires only) ===')
print(pd.crosstab(df[df.is_f7]["signal"], df[df.is_f7]["outcome"], margins=True))

# Compute move from strike to settlement
df["move_abs"] = df.settlement_price - df.strike_price
df["move_pct"] = df.move_abs / df.strike_price * 100
print(f'\n=== Settlement move stats (settlement - strike) ===')
for sig in ["UP","DOWN"]:
    sub = df[df.is_f7 & (df.signal == sig)]
    if len(sub):
        print(f'  signal={sig}, n={len(sub)}: move_pct mean={sub.move_pct.mean():+.4f}%, median={sub.move_pct.median():+.4f}%')

print(f'\n=== Signed move IN FAVOR of signal ===')
df["signed_move_pct"] = df.apply(lambda r: r.move_pct if r.signal=="UP" else -r.move_pct, axis=1)
for is_f7 in [True, False]:
    sub = df[df.is_f7 == is_f7]
    label = "F7" if is_f7 else "noF7"
    if len(sub):
        print(f'  {label} (n={len(sub)}): mean signed_move={sub.signed_move_pct.mean():+.4f}%, median={sub.signed_move_pct.median():+.4f}%')
        print(f'      win rows: mean signed_move = {sub[sub.won].signed_move_pct.mean() if sub.won.any() else float("nan"):+.4f}%')
        print(f'      lose rows: mean signed_move = {sub[~sub.won].signed_move_pct.mean():+.4f}%')

print(f'\n=== Entry price distribution (vwap) ===')
print(f'  F7 fires:    min={df[df.is_f7].entry_price.min():.4f}, median={df[df.is_f7].entry_price.median():.4f}, max={df[df.is_f7].entry_price.max():.4f}')
print(f'  no-F7 fires: min={df[~df.is_f7].entry_price.min():.4f}, median={df[~df.is_f7].entry_price.median():.4f}, max={df[~df.is_f7].entry_price.max():.4f}')

print(f'\n=== Time pattern (F7 fires by hour UTC) ===')
df["hour"] = df["at"].dt.hour
hour_summary = df[df.is_f7].groupby("hour").agg(
    n=("won","size"), wr=("won","mean"), sum=("pnl_usd","sum")
).round(3)
print(hour_summary)

print(f'\n=== Sample of LOSING F7 fires ===')
losers = df[df.is_f7 & ~df.won].sort_values("at")
print(losers[["at","signal","entry_price","strike_price","settlement_price","move_pct","outcome","pnl_usd"]].head(15).to_string(index=False))

print(f'\n=== Sample of WINNING F7 fires ===')
winners = df[df.is_f7 & df.won].sort_values("at")
print(winners[["at","signal","entry_price","strike_price","settlement_price","move_pct","outcome","pnl_usd"]].to_string(index=False))
