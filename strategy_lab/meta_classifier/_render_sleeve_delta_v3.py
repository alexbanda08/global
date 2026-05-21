"""Render per-sleeve table — all-time + delta since the previous snapshot.

Compares NEW2 (fresh pull) vs NEW (prior pull).
"""
import os; os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pandas as pd

OLD = pd.read_csv("data/v4/shadow_trades_2026_05_09/all_sleeve_stats_NEW.csv")
NEW = pd.read_csv("data/v4/shadow_trades_2026_05_09/all_sleeve_stats_NEW2.csv")
for df in (OLD, NEW):
    for c in ["pnl_total_usd","pnl_per_trade_usd","avg_entry_price","avg_entry_qty",
              "hours_running","fire_rate_pct","win_rate_pct","resolved","wins","losses",
              "signals_fired","hedge_fired","sell_fired","partial_sell_fired","hedge_skip_total"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

m = NEW.merge(OLD[["sleeve_id","resolved","wins","losses","pnl_total_usd",
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
m["d_pnl_per_tr"] = (m.d_pnl.astype(float) / denom).round(3)

m["d_hours"] = (pd.to_datetime(m.last_signal_at, utc=True) -
                pd.to_datetime(m.last_signal_at_OLD, utc=True)).dt.total_seconds() / 3600
median_dhrs = m.d_hours.median()

m["sleeve"] = m["sleeve_id"].str.replace("poly_updown_","",regex=False)
m = m[m.family != "volume"].copy()

# Sort by all-time pnl_total_usd descending (most profitable first)
m = m.sort_values("pnl_total_usd", ascending=False).reset_index(drop=True)

# Full table
t = m[["sleeve","family","hours_running","resolved","wins","losses","win_rate_pct",
       "pnl_total_usd","pnl_per_trade_usd",
       "d_resolved","d_wins","d_losses","d_pnl","d_pnl_per_tr","d_fires","d_hedge","d_sell",
       "avg_entry_price"]].copy()
t.columns = ["sleeve","family","hrs","resolved","wins","losses","WR%",
             "pnl_total$","pnl/tr$",
             "Δresolved","Δwins","Δlosses","Δpnl$","Δpnl/tr","Δfires","Δhedge","Δsell","entry"]
print(f"=== Delta window: median ~{median_dhrs:.2f}h since snapshot 2 (2026-05-11 19:37 local) ===\n")
print(t.to_string(index=False))

# Total summary
new_trades = int(m.d_resolved.sum())
new_pnl = float(m.d_pnl.sum())
print(f"\n=== TOTALS over delta window ===")
print(f"  ALL-TIME pnl:      ${m.pnl_total_usd.sum():,.2f}")
print(f"  Δpnl (this window): ${new_pnl:,.2f}")
print(f"  Δresolved:          {new_trades} new trades")
print(f"  Δwins:              {m.d_wins.sum()}  (WR {m.d_wins.sum()/max(new_trades,1)*100:.1f}%)")
print(f"  Δpnl/tr:            ${new_pnl/max(new_trades,1):.4f}")
print(f"  Δhedge fires:       {m.d_hedge.sum()}")
print(f"  Δsell fires:        {m.d_sell.sum()}")

# Movers
print("\n=== TOP 8 by Δpnl$ (this window) ===")
print(m.nlargest(8, "d_pnl")[["sleeve","family","d_resolved","d_wins","d_pnl","d_pnl_per_tr"]].to_string(index=False))
print("\n=== BOTTOM 8 by Δpnl$ (this window) ===")
print(m.nsmallest(8, "d_pnl")[["sleeve","family","d_resolved","d_wins","d_pnl","d_pnl_per_tr"]].to_string(index=False))

# Specific: btc_15m_momo gap (what got filled during the 20h "gap" we saw last time)
print("\n=== btc_15m_momo (the 'gap' we investigated) ===")
btc15 = m[m.sleeve.str.startswith("btc_15m_momo_") & ~m.sleeve.str.contains("v2")]
print(btc15[["sleeve","resolved","wins","WR%","pnl_total$","pnl/tr$","Δresolved","Δwins","Δpnl$","Δfires"]].to_string(index=False))

# Profitable sleeves all-time
print("\n=== PROFITABLE sleeves all-time (pnl_total > 0) ===")
prof = m[m.pnl_total_usd > 0].copy()
prof["pnl_pre"] = (prof.pnl_total_usd - prof.d_pnl).round(2)
tp = prof[["sleeve","family","resolved","WR%","pnl_total$","pnl/tr$","pnl_pre","d_resolved","d_pnl","d_pnl_per_tr"]].copy()
tp.columns = ["sleeve","family","resolved","WR%","pnl_total$","pnl/tr$","pnl_pre_Δ$","Δresolved","Δpnl$","Δpnl/tr"]
print(tp.to_string(index=False))
print(f"\n  profitable sleeves: {len(prof)}  total: ${prof.pnl_total_usd.sum():,.2f}  delta-window: ${prof.d_pnl.sum():,.2f}")
