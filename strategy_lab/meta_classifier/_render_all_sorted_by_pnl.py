"""Render full 65-sleeve table sorted top-profit → biggest-loss with all-time + delta."""
import os; os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd

OLD = pd.read_csv("data/v4/shadow_trades_2026_05_09/all_sleeve_stats_NEW.csv")
NEW = pd.read_csv("data/v4/shadow_trades_2026_05_09/all_sleeve_stats_NEW2.csv")
for df in (OLD, NEW):
    for c in ["pnl_total_usd","pnl_per_trade_usd","avg_entry_price","avg_entry_qty",
              "hours_running","fire_rate_pct","win_rate_pct","resolved","wins","losses",
              "signals_fired","hedge_fired","sell_fired","partial_sell_fired","hedge_skip_total"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

m = NEW.merge(OLD[["sleeve_id","resolved","wins","pnl_total_usd"]],
              on="sleeve_id", how="left", suffixes=("","_OLD"))
m["d_resolved"] = (m.resolved - m.resolved_OLD).fillna(0).astype(int)
m["d_wins"]     = (m.wins - m.wins_OLD).fillna(0).astype(int)
m["d_pnl"]      = (m.pnl_total_usd - m.pnl_total_usd_OLD).fillna(0).round(2)
denom = m.d_resolved.astype(float).replace(0, float("nan"))
m["d_pnl_per_tr"] = (m.d_pnl.astype(float) / denom).round(3)

m["sleeve"] = m["sleeve_id"].str.replace("poly_updown_","",regex=False)
m = m[m.family != "volume"].copy()
m = m.sort_values("pnl_total_usd", ascending=False).reset_index(drop=True)

t = m[["sleeve","family","hours_running","resolved","wins","losses","win_rate_pct",
       "pnl_total_usd","pnl_per_trade_usd","avg_entry_price","avg_entry_qty",
       "hedge_fired","sell_fired","partial_sell_fired","hedge_skip_total",
       "d_resolved","d_wins","d_pnl","d_pnl_per_tr"]].copy()
t.columns = ["sleeve","family","hrs","resolved","wins","losses","WR%",
             "pnl_total$","pnl/tr$","entry","qty",
             "hedge_n","sell_n","p_sell","skip",
             "Δresolved","Δwins","Δpnl$","Δpnl/tr"]
out = "data/v4/shadow_trades_2026_05_09/sleeves_sorted_by_pnl.txt"
with open(out, "w", encoding="utf-8") as f:
    f.write(t.to_string(index=False))
    f.write(f"\n\n=== TOTALS ===\n")
    f.write(f"  sleeves:           {len(m)}\n")
    f.write(f"  all-time pnl:      ${m.pnl_total_usd.sum():,.2f}\n")
    f.write(f"  delta-window pnl:  ${m.d_pnl.sum():,.2f}\n")
    f.write(f"  profitable:        {(m.pnl_total_usd > 0).sum()} sleeves  total ${m[m.pnl_total_usd > 0].pnl_total_usd.sum():,.2f}\n")
    f.write(f"  losing:            {(m.pnl_total_usd < 0).sum()} sleeves  total ${m[m.pnl_total_usd < 0].pnl_total_usd.sum():,.2f}\n")
print(f"wrote {out}")
print(t.to_string(index=False))

print(f"\n=== TOTALS ===")
print(f"  sleeves:           {len(m)}")
print(f"  all-time pnl:      ${m.pnl_total_usd.sum():,.2f}")
print(f"  delta-window pnl:  ${m.d_pnl.sum():,.2f}")
print(f"  profitable:        {(m.pnl_total_usd > 0).sum()} sleeves  total ${m[m.pnl_total_usd > 0].pnl_total_usd.sum():,.2f}")
print(f"  losing:            {(m.pnl_total_usd < 0).sum()} sleeves  total ${m[m.pnl_total_usd < 0].pnl_total_usd.sum():,.2f}")

print(f"\n=== TOP 10 LOSERS (all-time) ===")
losers = m.nsmallest(10, "pnl_total_usd")
print(losers[["sleeve","family","resolved","win_rate_pct","pnl_total_usd","pnl_per_trade_usd","d_resolved","d_pnl"]].to_string(index=False))
