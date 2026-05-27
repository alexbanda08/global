"""Per-offset baseline + single-gate lift table for ETH 5m."""
import pandas as pd, numpy as np
df = pd.read_parquet("data/v4/canonical/_results/_sniper_eth5m_v3_universe.parquet")

print("offset_s baseline:")
g = df.groupby("fire_offset_s").agg(n=("won","count"), wr=("won","mean"), dpt=("pnl_legacy_usd","mean"), sum_pnl=("pnl_legacy_usd","sum")).round(4)
print(g.to_string())

print("\noffset_bin baseline:")
g = df.groupby("offset_bin").agg(n=("won","count"), wr=("won","mean"), dpt=("pnl_legacy_usd","mean"), sum_pnl=("pnl_legacy_usd","sum")).round(4)
print(g.to_string())

print("\n== Single-gate lift (full universe) ==")
g_cols = [c for c in df.columns if c.startswith("g_")]
rows = []
for g in g_cols:
    col = df[g].astype("float").fillna(0).values
    m = (col >= 1.0)
    sub = df[m]
    if len(sub) < 100:
        continue
    rows.append(dict(
        gate=g,
        coverage=m.mean(),
        n=len(sub),
        wr=sub["won"].mean(),
        dpt=sub["pnl_legacy_usd"].mean(),
        sum_pnl=sub["pnl_legacy_usd"].sum(),
    ))
res = pd.DataFrame(rows).sort_values("wr", ascending=False)
print(res.round(4).to_string())

# also per offset_bin × gate
print("\n== Per offset_bin × gate (offset_bin 0-60 only, top 20 gates by WR) ==")
sub06 = df[df["offset_bin"] == "0-60"]
rows = []
for g in g_cols:
    col = sub06[g].astype("float").fillna(0).values
    m = (col >= 1.0)
    s = sub06[m]
    if len(s) < 50:
        continue
    rows.append(dict(gate=g, n=len(s), wr=s["won"].mean(), dpt=s["pnl_legacy_usd"].mean()))
print(pd.DataFrame(rows).sort_values("wr", ascending=False).head(20).round(4).to_string())
