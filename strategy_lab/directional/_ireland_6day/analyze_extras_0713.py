import sys; sys.stdout.reconfigure(encoding="utf-8")
import json, numpy as np, pandas as pd
D = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/directional/_ireland_6day/"
rng = np.random.default_rng(13)
def ci(x, n=12000):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    if len(x) < 5: return (np.nan, np.nan)
    b = np.array([rng.choice(x, len(x), True).mean() for _ in range(n)])
    return tuple(np.percentile(b, [2.5, 97.5]))

rows = []
for ln in open(D + "ladder_all_refresh5.tsv", encoding="utf-8"):
    ln = ln.rstrip("\n")
    if not ln: continue
    at, sl, js = ln.split("\t", 2)
    d = json.loads(js); d["ts"] = at; d["sleeve"] = sl; rows.append(d)
df = pd.DataFrame(rows); df["ts"] = pd.to_datetime(df["ts"])
for c in ["total_net_usd","filled_up_sh","filled_dn_sh","residual_entry_vwap","residual_pnl_usd",
          "residual_sh","residual_flattened_sh","paired_pnl_locked_usd","rebate_usd"]:
    df[c] = pd.to_numeric(df.get(c), errors="coerce")
df["traded"] = (df.filled_up_sh > 0) | (df.filled_dn_sh > 0)
T = df[df.traded & df.outcome.notna()].copy()

print("="*90)
print("1. V4_COC vs V3-15M — MATCHED-SLUG PAIRED TEST (full sample)")
print("="*90)
a = T[T.sleeve == "poly_ladder_btc_15m_v3"].set_index("slug")
b = T[T.sleeve == "poly_ladder_btc_15m_v4_coc"].set_index("slug")
both = a.index.intersection(b.index)
dif = (b.loc[both, "total_net_usd"] - a.loc[both, "total_net_usd"]).dropna()
lo, hi = ci(dif.values)
print(f"matched slugs n={len(dif)} | v4−v3 diff: mean {dif.mean():+.3f}/win CI[{lo:+.3f},{hi:+.3f}] | median {dif.median():+.3f} | v4 better in {100*(dif>0).mean():.0f}%")
w = np.sort(dif.values); ex2 = w[2:-2] if len(w) > 20 else w
print(f"trimmed (drop 2 each tail): {ex2.mean():+.3f} CI[{ci(ex2)[0]:+.3f},{ci(ex2)[1]:+.3f}]")

print()
print("="*90)
print("2. COINFLIP-GATE (rcg) COUNTERFACTUAL — pre-registered expectation for v31_rcg")
print("="*90)
for sl, LO, HI in [("poly_ladder_btc_5m_v3", .30, .60), ("poly_ladder_eth_5m_v3", .30, .45)]:
    g = T[T.sleeve == sl].copy()
    band = g[(g.residual_entry_vwap > LO) & (g.residual_entry_vwap < HI) & (g.residual_sh > 0)]
    # counterfactual: flatten immediately at entry − k ticks (cost k*0.01*sh), replacing realized residual_pnl
    n_days = (g.ts.max() - g.ts.min()).total_seconds()/86400
    print(f"\n[{sl}] band ({LO},{HI}): {len(band)}/{len(g)} windows gated ({100*len(band)/len(g):.0f}%)")
    print(f"  realized residual_pnl in band: mean {band.residual_pnl_usd.mean():+.3f}, sum {band.residual_pnl_usd.sum():+.1f} over {n_days:.1f}d")
    for k in [0.5, 1.0, 2.0]:  # flatten cost in ticks
        cf_pnl = -k * 0.01 * band.residual_sh          # immediate flatten cost
        uplift = (cf_pnl - band.residual_pnl_usd)      # per gated window
        # uplift over ALL traded windows (non-gated contribute 0)
        full = np.zeros(len(g)); full[:len(uplift)] = 0  # build properly below
        up_all = pd.Series(0.0, index=g.index); up_all.loc[band.index] = uplift
        lo2, hi2 = ci(up_all.values)
        print(f"  flatten cost {k:>3.1f} ticks: uplift {up_all.mean():+.4f}/win CI[{lo2:+.4f},{hi2:+.4f}]  = ${up_all.sum()/n_days:+.2f}/day")

print()
print("="*90)
print("3. LADDER × SUMPAIR OVERLAP (btc-5m) — additive or redundant?")
print("="*90)
srows = []
for ln in open(D + "sumpair_all_refresh5.tsv", encoding="utf-8"):
    ln = ln.rstrip("\n")
    if not ln: continue
    p = ln.split("\t", 2)
    d = json.loads(p[2]); d["ts"] = p[0]; d["sleeve"] = p[1]; srows.append(d)
sp = pd.DataFrame(srows); sp = sp[sp.sleeve == "sumpair_osc_btc_5m"]
sp = sp.sort_values("ts").drop_duplicates(subset=["condition_id"], keep="last")
sp["net"] = pd.to_numeric(sp.net_pnl_level0, errors="coerce")
lad = T[T.sleeve == "poly_ladder_btc_5m_v3"][["condition_id", "total_net_usd"]].dropna()
m = lad.merge(sp[["condition_id", "net"]].dropna(), on="condition_id", how="inner", suffixes=("_lad", "_sp"))
print(f"windows where BOTH traded: {len(m)} (ladder {len(lad)}, sumpair {len(sp[sp.net.notna()])})")
if len(m) > 10:
    r = np.corrcoef(m.total_net_usd, m.net)[0, 1]
    print(f"PnL correlation on shared windows: r = {r:+.3f}")
    both_pos = ((m.total_net_usd > 0) & (m.net > 0)).mean()
    print(f"both positive same window: {100*both_pos:.0f}% | combined mean/win {m.total_net_usd.mean()+m.net.mean():+.2f}")
    # portfolio view: does adding sumpair to ladder improve risk-adjusted?
    port = m.total_net_usd + m.net
    print(f"portfolio (1:1) per-window: mean {port.mean():+.3f} std {port.std():.2f} | ladder alone: {m.total_net_usd.mean():+.3f} std {m.total_net_usd.std():.2f}")
    print(f"sharpe-ish ratio: portfolio {port.mean()/port.std():.3f} vs ladder {m.total_net_usd.mean()/m.total_net_usd.std():.3f}")
