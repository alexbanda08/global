"""Render the per-sleeve metrics CSV into the comprehensive table + rollups."""
import os; os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd

df = pd.read_csv("data/v4/shadow_trades_2026_05_09/momo_sleeve_stats.csv")
for c in ["pnl_total_usd","pnl_per_trade_usd","avg_entry_price","avg_entry_qty",
          "hours_running","fire_rate_pct","win_rate_pct","hedge_fire_rate_pct","sell_fire_rate_pct"]:
    df[c] = pd.to_numeric(df[c], errors="coerce")

df["sleeve"] = df["version"] + " " + df["asset"].str.upper() + " " + df["tf"] + " " + df["policy"]
order_v = {"v1":0,"v2":1}; order_t = {"5m":0,"15m":1}; order_p = {"HOLD":0,"HEDGE":1,"SELL":2}
df["_v"] = df.version.map(order_v); df["_t"] = df.tf.map(order_t); df["_p"] = df.policy.map(order_p)
df = df.sort_values(["_v","asset","_t","_p"]).drop(columns=["_v","_t","_p"]).reset_index(drop=True)

print("=== PER-SLEEVE METRICS (last 14d, paper/shadow mode) ===\n")
core = df[["sleeve","hours_running","signals_fired","fire_rate_pct","resolved","wins","losses","win_rate_pct",
           "pnl_total_usd","pnl_per_trade_usd","avg_entry_price","avg_entry_qty",
           "hedge_fired","sell_fired","hedge_skip_total"]].copy()
core.columns = ["sleeve","hrs","fires","fire%","resolved","wins","losses","WR%",
                "pnl$","pnl/tr$","avg_entry","avg_qty","hedge_n","sell_n","hedge_skip"]
print(core.to_string(index=False))

print("\n\n=== ROLLUP BY VERSION x POLICY ===\n")
roll = df.groupby(["version","policy"]).agg(
    n_sleeves=("sleeve_id","count"),
    fires=("signals_fired","sum"),
    resolved=("resolved","sum"),
    wins=("wins","sum"),
    pnl_total=("pnl_total_usd","sum"),
    hedge_n=("hedge_fired","sum"),
    sell_n=("sell_fired","sum"),
    skip_n=("hedge_skip_total","sum"),
).reset_index()
roll["WR%"]   = (roll.wins / roll.resolved * 100).round(2)
roll["pnl/tr$"] = (roll.pnl_total / roll.resolved).round(4)
print(roll.to_string(index=False))

print("\n\n=== HOLD ONLY (cleanest baseline comparison) ===\n")
hold = df[df.policy=="HOLD"].copy()
hold_view = hold[["version","asset","tf","hours_running","signals_fired","resolved","wins","win_rate_pct","pnl_total_usd","pnl_per_trade_usd","avg_entry_price"]].copy()
hold_view.columns = ["version","asset","tf","hrs","fires","resolved","wins","WR%","pnl$","pnl/tr$","entry"]
print(hold_view.to_string(index=False))

print("\n\n=== TOP / BOTTOM SLEEVES BY pnl/trade ===\n")
ranked = df[["sleeve","resolved","win_rate_pct","pnl_per_trade_usd","pnl_total_usd","hedge_fired","sell_fired"]].sort_values("pnl_per_trade_usd", ascending=False)
print("TOP 8:")
print(ranked.head(8).to_string(index=False))
print("\nBOTTOM 8:")
print(ranked.tail(8).to_string(index=False))

print(f"\n\n=== TOTALS (last 14d) ===")
print(f"  sleeves:           {len(df)} ({(df.version=='v1').sum()} v1 + {(df.version=='v2').sum()} v2)")
print(f"  hours running:     ~{df.hours_running.median():.1f}h (median)  range {df.hours_running.min():.1f}-{df.hours_running.max():.1f}")
print(f"  total fires:       {df.signals_fired.sum():,}")
print(f"  total resolved:    {df.resolved.sum():,}")
print(f"  total wins:        {df.wins.sum():,}")
print(f"  overall WR:        {df.wins.sum()/df.resolved.sum()*100:.2f}%")
print(f"  total pnl_usd:     ${df.pnl_total_usd.sum():,.2f}")
print(f"  pnl per trade:     ${df.pnl_total_usd.sum()/df.resolved.sum():.4f}")
print(f"  hedge fires:       {df.hedge_fired.sum()}")
print(f"  sell fires:        {df.sell_fired.sum()}")
print(f"  hedge skips:       {df.hedge_skip_total.sum()}")
