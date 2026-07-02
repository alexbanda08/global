import json, numpy as np, pandas as pd
pd.set_option("display.width", 200)
D = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/directional/_ireland_6day/"

rows = []
for ln in open(D + "ladder_summary_v2.tsv", encoding="utf-8"):
    ln = ln.rstrip("\n")
    if not ln: continue
    at, js = ln.split("\t", 1)
    d = json.loads(js); d["ts"] = at; rows.append(d)
df = pd.DataFrame(rows)
df["ts"] = pd.to_datetime(df["ts"])
num = ["pvs","pair_frac","paired_sh","rebate_usd","residual_sh","filled_dn_sh","filled_up_sh",
       "filled_up_vwap","filled_dn_vwap","residual_entry_vwap","residual_pnl_usd","total_net_usd",
       "pair_gate_bound_sh","flow_capture","paired_pnl_locked_usd","net_paired_estimate_usd",
       "market_sell_total_sh","maker_pct","taker_completions"]
for c in num: df[c] = pd.to_numeric(df[c], errors="coerce")
span_h = (df.ts.max() - df.ts.min()).total_seconds() / 3600
print(f"WINDOWS: {len(df)}  span {df.ts.min()} -> {df.ts.max()}  ({span_h:.1f}h)")
print("skipped_reason:", df.skipped_reason.value_counts(dropna=False).to_dict())

df["traded"] = (df.filled_up_sh > 0) | (df.filled_dn_sh > 0)
t = df[df.traded].copy(); n = len(t)
print(f"TRADED: {n}/{len(df)} = {100*df.traded.mean():.0f}%")

# ---- integrity: decomposition + gate ----
recon = t.paired_pnl_locked_usd + t.rebate_usd + t.residual_pnl_usd
print("\n== INTEGRITY ==")
print(f"total_net == paired+rebate+residual: maxdiff = {(t.total_net_usd - recon).abs().max():.6f}")
m = t.dropna(subset=["pvs"])
print(f"paired_pnl == paired_sh*(1-pvs): maxdiff = {(m.paired_pnl_locked_usd - m.paired_sh*(1-m.pvs)).abs().max():.6f}")
# residual formula check
v = t.residual_entry_vwap; won = (t.residual_side == t.outcome)
pred = np.where(t.residual_side == "none", 0.0,
        np.where(won, t.residual_sh*(1-v)*(1-0.07*v), -t.residual_sh*v))
print(f"residual_pnl formula: maxdiff = {np.nanmax(np.abs(t.residual_pnl_usd - pred)):.6f}")
print(f"G3 GATE: windows pvs>=0.99: {(m.pvs>=0.99).sum()}/{len(m)}  max pvs={m.pvs.max():.4f}")
print(f"pair_gate_bound_sh: >0 in {(t.pair_gate_bound_sh>0).sum()} wins, mean={t.pair_gate_bound_sh.mean():.2f}, max={t.pair_gate_bound_sh.max():.2f}, sum={t.pair_gate_bound_sh.sum():.1f}")

# ---- headline ----
print("\n== HEADLINE (traded) ==")
for c in ["paired_pnl_locked_usd","rebate_usd","residual_pnl_usd","total_net_usd"]:
    s = t[c]
    print(f"{c:24s} sum=${s.sum():+9.2f}  mean=${s.mean():+7.4f}/win  med=${s.median():+7.4f}")
days = span_h/24
print(f"per-day: total_net ${t.total_net_usd.sum()/days:+.2f}/d   paired ${t.paired_pnl_locked_usd.sum()/days:+.2f}/d")

# residual outcomes
rr = t[t.residual_side != "none"]
print(f"\nresidual: wins {(rr.residual_side==rr.outcome).sum()}/{len(rr)} = {100*(rr.residual_side==rr.outcome).mean():.1f}%")
print(f"residual entry_vwap: mean {rr.residual_entry_vwap.mean():.3f} med {rr.residual_entry_vwap.median():.3f}")
print(f"residual_sh: mean {t.residual_sh.mean():.2f} (v1 was 9.34)")

# ---- key stats vs v1 ----
print("\n== v2 vs v1 (v1 13.4d baselines) ==")
v1 = {"pair_frac":0.7993,"pvs":0.9557,"flow_capture":0.0170,"net_paired_mean":1.4159,"pvs_gt1_pct":33.2,"resid_sh":9.34}
print(f"pair_frac    v2 {t.pair_frac.mean():.3f}  v1 {v1['pair_frac']:.3f}")
print(f"pvs          v2 {m.pvs.mean():.3f}  v1 {v1['pvs']:.3f}")
print(f"pvs>1 wins   v2 {(m.pvs>1).sum()} ({100*(m.pvs>1).mean():.0f}%)  v1 {v1['pvs_gt1_pct']:.0f}%")
print(f"flow_capture v2 {t.flow_capture.mean():.4f}  v1 {v1['flow_capture']:.4f}")
print(f"net_paired   v2 {t.net_paired_estimate_usd.mean():+.3f}/win  v1 {v1['net_paired_mean']:+.3f}/win")
print(f"residual_sh  v2 {t.residual_sh.mean():.2f}  v1 {v1['resid_sh']:.2f}")

# ---- bootstrap CI on total_net mean ----
rng = np.random.default_rng(7)
x = t.total_net_usd.values
boots = np.array([rng.choice(x, len(x), replace=True).mean() for _ in range(20000)])
lo, hi = np.percentile(boots, [2.5, 97.5])
print(f"\n== BOOTSTRAP total_net_usd mean: {x.mean():+.3f}/win  CI95 [{lo:+.3f}, {hi:+.3f}]  P(mean>0)={100*(boots>0).mean():.1f}%")
xp = t.net_paired_estimate_usd.values
bp = np.array([rng.choice(xp, len(xp), replace=True).mean() for _ in range(20000)])
lop, hip = np.percentile(bp, [2.5, 97.5])
print(f"   net_paired only:            {xp.mean():+.3f}/win  CI95 [{lop:+.3f}, {hip:+.3f}]")

# pre/post restart (engine restarted Jun30 17:45)
cut = pd.Timestamp("2026-06-30 17:45", tz="UTC")
for lbl, seg in [("pre-restart", t[t.ts < cut]), ("post-restart", t[t.ts >= cut])]:
    if len(seg):
        print(f"{lbl:13s} n={len(seg):3d}  pvs_max={seg.pvs.max():.3f}  gate_bound_mean={seg.pair_gate_bound_sh.mean():.2f}  total_net=${seg.total_net_usd.sum():+.2f}")

# worst/best windows
print("\n== tails ==")
cols = ["ts","pvs","paired_sh","residual_sh","residual_side","outcome","residual_pnl_usd","total_net_usd"]
print(t.nsmallest(3, "total_net_usd")[cols].to_string(index=False))
print(t.nlargest(3, "total_net_usd")[cols].to_string(index=False))
