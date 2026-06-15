"""3rd-sleeve search WITH robustness filter. Base = ETH v8 + cloud_vwap_v7.
Candidates: all ETH-5m + all SOL-5m (SOL = different asset -> 100% new slugs by definition).
Filters: running >=5d, active, n>=40, top2%<=40 (outlier-robust), ex-top2 $/tr>0.
Rank by: ex-top2 $/tr (robust ROI), then new-slug% (diversification)."""
import numpy as np, pandas as pd

ROOT = r"C:\Users\alexandre bandarra\Desktop\global\migration_2026_06_08"
eth = pd.read_csv(ROOT + r"\all_eth5m.csv"); eth["asset"] = "ETH"
sol = pd.read_csv(ROOT + r"\all_sol5m.csv"); sol["asset"] = "SOL"
df = pd.concat([eth, sol], ignore_index=True)

BASE = ["poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8",
        "poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7"]
base_slugs = set(df[df.sid.isin(BASE)]["slug"])
base_lo = df[df.sid.isin(BASE)]["fire_us"].min()
gmax = df["fire_us"].max()

rows = []
for sid, g in df.groupby("sid"):
    if sid in BASE:
        continue
    asset = g["asset"].iloc[0]
    g = g[g.fire_us >= base_lo]
    if len(g) < 40:
        continue
    span = (g.fire_us.max() - g.fire_us.min()) / 86_400_000_000
    if span < 5 or g.fire_us.max() < gmax - 1 * 86_400_000_000:
        continue
    p = np.sort(g["pnl"].to_numpy())[::-1]
    n = len(p); tot = p.sum()
    top2 = p[:2].sum()
    top2pct = top2 / tot * 100 if tot > 0 else 999
    ex2 = p[2:].mean()
    cum = np.cumsum(np.sort(g["pnl"].to_numpy()) if False else g.sort_values("fire_us")["pnl"].to_numpy())
    mdd = float((cum - np.maximum.accumulate(cum)).min())
    slugs = set(g["slug"])
    new = len(slugs) if asset == "SOL" else len(slugs - base_slugs)  # SOL = all new
    rows.append(dict(sid=sid.replace("poly_sniper_v5_", ""), asset=asset, n=n,
                     wr=g["won"].mean() * 100, dpt=tot / n, ex2=ex2, top2pct=top2pct,
                     newpct=new / len(slugs) * 100, mdd=mdd,
                     cal=(tot / abs(mdd) if mdd < 0 else 99)))

r = pd.DataFrame(rows)
ROB = r[(r.top2pct <= 40) & (r.ex2 > 0)].sort_values("ex2", ascending=False)
print(f"base = ETH v8 + cloud_vwap_v7. ROBUST candidates (top2<=40%, ex-top2>0, >5d, n>=40):\n")
print("%-40s %4s %4s %4s %7s %8s %6s %6s %6s %6s" %
      ("sleeve", "ast", "n", "WR", "$/tr", "ex-top2", "top2%", "new%", "MaxDD", "Calmr"))
for _, x in ROB.iterrows():
    print("%-40s %4s %4d %3.0f%% %+7.3f %+8.3f %5.0f%% %5.0f%% %6.1f %6.2f" %
          (x.sid[:40], x.asset, x.n, x.wr, x.dpt, x.ex2, x.top2pct, x.newpct, x.mdd, x.cal))

print("\n--- REJECTED for outlier-contamination (top2 > 40%) ---")
for _, x in r[r.top2pct > 40].sort_values("top2pct", ascending=False).head(10).iterrows():
    print("  %-38s %s n=%d $/tr=%+.3f ex-top2=%+.3f top2=%.0f%%" % (x.sid[:38], x.asset, x.n, x.dpt, x.ex2, x.top2pct))
