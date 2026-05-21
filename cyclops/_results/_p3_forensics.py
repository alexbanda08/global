"""Sanity-check forensics on p3_vwap30_momabstain.csv."""
import pandas as pd
import numpy as np

df = pd.read_csv("cyclops/_results/p3_vwap30_momabstain.csv")
fired = df[df.fired == True].copy()

print(f"eval={len(df)}  fired={len(fired)}  fire_rate={len(fired)/len(df):.2%}")
print(f"WR={fired.won.mean():.3f}  mean_pnl=${fired.pnl_usd.mean():+.4f}  total=${fired.pnl_usd.sum():+.2f}")
print(f"mean vwap=${fired.vwap_entry.mean():.4f}  breakeven WR at mean vwap = {fired.vwap_entry.mean():.3f}")
print()

print("=== Per-direction split ===")
print(fired.groupby("direction").agg(n=("pnl_usd", "size"), wr=("won", "mean"),
                                     mean_pnl=("pnl_usd", "mean"),
                                     mean_vwap=("vwap_entry", "mean"),
                                     total=("pnl_usd", "sum")))
print()

print("=== Daily PnL ===")
fired["dt_utc"] = pd.to_datetime(fired.ws_s, unit="s", utc=True)
fired["date"] = fired.dt_utc.dt.date
daily = fired.groupby("date").agg(n=("pnl_usd", "size"), wr=("won", "mean"),
                                   day_pnl=("pnl_usd", "sum"))
print(daily)
print()

print("=== Vwap bucket split (sanity: should NOT have any sub-0.30 anymore) ===")
bins = [0.0, 0.30, 0.40, 0.50, 0.60, 0.70, 1.01]
fired["vwap_bin"] = pd.cut(fired.vwap_entry, bins=bins)
print(fired.groupby("vwap_bin", observed=True).agg(
    n=("pnl_usd", "size"), wr=("won", "mean"),
    mean_vwap=("vwap_entry", "mean"),
    mean_pnl=("pnl_usd", "mean"),
    total=("pnl_usd", "sum"),
))
print()

print("=== Tuple distribution (should be only (+1,+1,0) and (-1,-1,0)) ===")
print(fired.groupby(["v_trend", "v_levels", "v_momentum"]).agg(
    n=("pnl_usd", "size"), wr=("won", "mean"),
    mean_vwap=("vwap_entry", "mean"),
    mean_pnl=("pnl_usd", "mean"),
))
print()

print("=== Quick equity curve milestones ===")
fired_sorted = fired.sort_values("ws_s").reset_index(drop=True)
fired_sorted["cum_pnl"] = fired_sorted.pnl_usd.cumsum()
for q in (0.25, 0.50, 0.75, 1.0):
    idx = int(len(fired_sorted) * q) - 1
    if idx >= 0:
        row = fired_sorted.iloc[idx]
        print(f"  after {q*100:.0f}% of trades (n={idx+1:4d}): cum_pnl=${row.cum_pnl:+.2f}")
print()

print("=== Drawdown ===")
fired_sorted["peak"] = fired_sorted.cum_pnl.cummax()
fired_sorted["dd"] = fired_sorted.cum_pnl - fired_sorted.peak
print(f"  max drawdown: ${fired_sorted.dd.min():.2f}")
print(f"  current eq (final cum_pnl): ${fired_sorted.cum_pnl.iloc[-1]:+.2f}")
