"""Full 14-day analysis of momo_v2 bugs.

Computes the same V1 vs V2 cross-tabs but over 14 days of production data
(May 7 - May 21) instead of just the 23.5h post-F7 window. Confirms whether
the bugs are persistent or window-specific.
"""
import json
import pandas as pd
import numpy as np

ev = pd.read_csv('strategy_lab/markov_filter/_vps3_pull/all_momo_events_14d.csv')
ev["at"] = pd.to_datetime(ev["at"], utc=True, format="mixed")
print(f"Total events: {len(ev):,}")
print(f"Date range: {ev['at'].min()}  →  {ev['at'].max()}")
print(f"Sleeve types: {ev['sleeve_id'].nunique()}")
print()

# Parse resolutions only
res = ev[ev["kind"] == "poly_updown_resolution"].copy()
print(f"Resolutions: {len(res):,}")
rows = []
for _, r in res.iterrows():
    try: d = json.loads(r["data"])
    except: continue
    d["sleeve_id"] = r["sleeve_id"]
    d["at"] = r["at"]
    rows.append(d)
df = pd.DataFrame(rows)
df["pnl_usd"] = pd.to_numeric(df["pnl_usd"], errors="coerce")
df["is_f7"]   = df["sleeve_id"].str.endswith("_f7")
df["version"] = df["sleeve_id"].apply(lambda s: "v2" if "_momo_v2_" in s else "v1")

# Helper to extract (asset, tf)
def asset_tf(sid):
    s = sid.replace("poly_updown_", "")
    parts = s.split("_")
    return parts[0].upper(), parts[1]
df["asset"], df["tf"] = zip(*df["sleeve_id"].map(asset_tf))
df["sleeve_key"] = df["asset"].str.lower() + "_" + df["tf"]

print(f"\n=== Per-day breakdown for each (asset, tf, version) ===")
df["day"] = df["at"].dt.date
daily = df.groupby(["sleeve_key","version","is_f7","day"]).agg(
    n=("won","size"),
    wins=("won","sum"),
    pnl=("pnl_usd","sum"),
).reset_index()
daily["wr"] = (daily["wins"] / daily["n"] * 100).round(2)
print()

# Focus on V2 cells per day
print("=== V2 SLEEVES — daily WR over 14 days ===")
v2 = daily[daily["version"]=="v2"].copy()
v2_pivot = v2.pivot_table(index="day", columns=["sleeve_key","is_f7"], values="wr").round(1)
print(v2_pivot.to_string())
print()

# Aggregate (sleeve, is_f7) over full 14 days
print("=== V2 aggregate over 14 days (per sleeve × F7) ===")
agg = df[df["version"]=="v2"].groupby(["sleeve_key","is_f7"]).agg(
    n=("won","size"),
    wr=("won","mean"),
    avg_pnl=("pnl_usd","mean"),
    sum_pnl=("pnl_usd","sum"),
).round({"wr":4, "avg_pnl":3, "sum_pnl":2})
agg["wr"] = (agg["wr"]*100).round(2)
print(agg.to_string())
print()

# Signal × outcome cross-tabs for V2 sleeves over 14 days
for sleeve_key in sorted(df[df["version"]=="v2"]["sleeve_key"].unique()):
    for is_f7_val in [True, False]:
        sub = df[(df["version"]=="v2") & (df["sleeve_key"]==sleeve_key) & (df["is_f7"]==is_f7_val)]
        if len(sub) < 10: continue
        label = "F7" if is_f7_val else "no_F7"
        print(f"\n--- {sleeve_key}_v2 {label} (n={len(sub)}, WR={sub.won.mean()*100:.2f}%, ${sub.pnl_usd.mean():.2f}/trade, sum=${sub.pnl_usd.sum():.2f}) ---")
        ct = pd.crosstab(sub["signal"], sub["outcome"], margins=True)
        print(ct)
        # Inversion test
        clean = sub[sub["outcome"].isin(["Up","Down"])].copy()
        if len(clean):
            inv_won = (((clean["signal"]=="UP") & (clean["outcome"]=="Down")) |
                       ((clean["signal"]=="DOWN") & (clean["outcome"]=="Up")))
            print(f"   Original WR: {clean['won'].mean()*100:.2f}%   Inverted WR: {inv_won.mean()*100:.2f}%")

# V1 control over same window
print("\n\n=== V1 CONTROL over 14 days (same cells) ===")
v1_agg = df[df["version"]=="v1"].groupby(["sleeve_key","is_f7"]).agg(
    n=("won","size"), wr=("won","mean"),
    avg_pnl=("pnl_usd","mean"), sum_pnl=("pnl_usd","sum"),
).round({"wr":4})
v1_agg["wr"] = (v1_agg["wr"]*100).round(2)
print(v1_agg.to_string())
