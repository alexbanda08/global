"""Render per-sleeve table + delta since previous snapshot."""
import os; os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd
from pathlib import Path

OLD = Path("data/v4/shadow_trades_2026_05_09/all_sleeve_stats.csv")
NEW = Path("data/v4/shadow_trades_2026_05_09/all_sleeve_stats_NEW.csv")

old = pd.read_csv(OLD)
new = pd.read_csv(NEW)

for df in (old, new):
    for c in ["pnl_total_usd","pnl_per_trade_usd","avg_entry_price","avg_entry_qty",
              "hours_running","fire_rate_pct","win_rate_pct","resolved","wins","losses",
              "signals_fired","hedge_fired","sell_fired","partial_sell_fired","hedge_skip_total"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

# Join on sleeve_id
m = new.merge(old[["sleeve_id","resolved","wins","losses","pnl_total_usd",
                   "signals_fired","hedge_fired","sell_fired","hedge_skip_total","last_signal_at"]],
              on="sleeve_id", how="left", suffixes=("","_OLD"))

m["d_resolved"] = (m.resolved - m.resolved_OLD).fillna(0).astype(int)
m["d_wins"]     = (m.wins - m.wins_OLD).fillna(0).astype(int)
m["d_losses"]   = (m.losses - m.losses_OLD).fillna(0).astype(int)
m["d_pnl"]      = (m.pnl_total_usd - m.pnl_total_usd_OLD).fillna(0).round(2)
m["d_fires"]    = (m.signals_fired - m.signals_fired_OLD).fillna(0).astype(int)
m["d_hedge"]    = (m.hedge_fired - m.hedge_fired_OLD).fillna(0).astype(int)
m["d_sell"]     = (m.sell_fired - m.sell_fired_OLD).fillna(0).astype(int)
denom = m.d_resolved.astype(float).replace(0, float("nan"))
m["d_pnl_per_new_tr"] = (m.d_pnl.astype(float) / denom).round(3)

# Window of delta = NEW.last_signal_at - OLD.last_signal_at
m["d_hours"] = (pd.to_datetime(m.last_signal_at, utc=True) - pd.to_datetime(m.last_signal_at_OLD, utc=True)).dt.total_seconds() / 3600
median_dhrs = m.d_hours.median()

# Sort by WR desc
m["sleeve"] = m["sleeve_id"].str.replace("poly_updown_","",regex=False)
m = m[m.family != "volume"].copy()
m["_wr"] = m.win_rate_pct.fillna(-1)
m = m.sort_values(["_wr","resolved"], ascending=[False, False]).drop(columns="_wr").reset_index(drop=True)

t = m[["sleeve","family","hours_running","resolved","wins","losses","win_rate_pct",
       "pnl_total_usd","pnl_per_trade_usd",
       "d_resolved","d_wins","d_losses","d_pnl","d_pnl_per_new_tr",
       "d_fires","d_hedge","d_sell",
       "avg_entry_price","hedge_fired","sell_fired","hedge_skip_total"]].copy()
t.columns = ["sleeve","family","hrs","resolved","wins","losses","WR%",
             "pnl$","pnl/tr$",
             "Δresolved","Δwins","Δlosses","Δpnl$","Δpnl/tr",
             "Δfires","Δhedge","Δsell",
             "entry","hedge_n","sell_n","skip"]
print(f"delta window: median ~{median_dhrs:.2f}h since prior snapshot\n")
print(t.to_string(index=False))

# Mini-summary
print(f"\n=== TOTALS ===")
print(f"  delta resolved:  {m.d_resolved.sum()} new trades across all sleeves")
print(f"  delta wins:      {m.d_wins.sum()}")
print(f"  delta pnl_total: ${m.d_pnl.sum():.2f}")
print(f"  delta pnl/tr:    ${m.d_pnl.sum() / max(m.d_resolved.sum(),1):.4f}")
print(f"  delta hedge:     {m.d_hedge.sum()}")
print(f"  delta sell:      {m.d_sell.sum()}")

# Movers (biggest delta_pnl up / down)
print("\n=== TOP 5 BY Δpnl$ ===")
print(m.nlargest(5, "d_pnl")[["sleeve","family","d_resolved","d_wins","d_pnl","d_pnl_per_new_tr"]].to_string(index=False))
print("\n=== BOTTOM 5 BY Δpnl$ ===")
print(m.nsmallest(5, "d_pnl")[["sleeve","family","d_resolved","d_wins","d_pnl","d_pnl_per_new_tr"]].to_string(index=False))
