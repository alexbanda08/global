import sys; sys.stdout.reconfigure(encoding='utf-8')
import json, numpy as np, pandas as pd
pd.set_option("display.width", 220)
D = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/directional/_ireland_6day/"
rng = np.random.default_rng(9)
def ci(x, n=12000):
    if len(x) < 5: return (np.nan, np.nan)
    b = np.array([rng.choice(x, len(x), True).mean() for _ in range(n)])
    return tuple(np.percentile(b, [2.5, 97.5]))

rows = []
for ln in open(D + "ladder_v3v4.tsv", encoding="utf-8"):
    ln = ln.rstrip("\n")
    if not ln: continue
    at, sl, js = ln.split("\t", 2)
    d = json.loads(js); d["ts"] = at; d["sleeve"] = sl; rows.append(d)
df = pd.DataFrame(rows); df["ts"] = pd.to_datetime(df["ts"])
num = ["pvs","pair_frac","paired_sh","rebate_usd","residual_sh","filled_dn_sh","filled_up_sh",
       "filled_up_vwap","filled_dn_vwap","residual_entry_vwap","residual_pnl_usd","total_net_usd",
       "pair_gate_bound_sh","flow_capture","paired_pnl_locked_usd","market_sell_total_sh",
       "residual_flattened_sh","residual_backstop_cost_usd","fill_below_touch_ticks_up",
       "fill_below_touch_ticks_dn","quote_depth_ticks","coc_triggers","coc_completions","coc_cuts",
       "coc_cut_cost_usd","coc_completion_cost_usd","coc_pnl_delta_vs_hold_usd","coc_taker_fee_usd",
       "outcome_none_held_sh","maker_pct","taker_completions","settle_attempts"]
for c in num:
    if c in df.columns: df[c] = pd.to_numeric(df[c], errors="coerce")
df["traded"] = (df.filled_up_sh > 0) | (df.filled_dn_sh > 0)

print("="*100)
print("A. PER-SLEEVE PERFORMANCE (settled traded windows)")
print("="*100)
for sl, g in df.groupby("sleeve"):
    t = g[g.traded & g.outcome.notna()]
    days = (g.ts.max() - g.ts.min()).total_seconds()/86400
    if not len(t):
        print(f"{sl}: no settled traded windows"); continue
    x = t.total_net_usd.dropna().values
    lo, hi = ci(x)
    fb = pd.concat([t.fill_below_touch_ticks_up.dropna(), t.fill_below_touch_ticks_dn.dropna()])
    print(f"\n[{sl}]  span {days:.1f}d  windows {len(g)}  traded {g.traded.sum()} ({100*g.traded.mean():.0f}%)  settled-traded {len(t)}")
    print(f"  TOTAL NET  {x.mean():+.3f}/win  CI[{lo:+.3f},{hi:+.3f}]  sum {x.sum():+.1f}  (${x.sum()/days:+.1f}/day)")
    print(f"  decomp: paired {t.paired_pnl_locked_usd.mean():+.3f}  rebate {t.rebate_usd.mean():+.4f}  residual {t.residual_pnl_usd.mean():+.3f}")
    print(f"  pair_frac {t.pair_frac.mean():.3f}  pvs mean {t.pvs.mean():.3f} max {t.pvs.max():.3f}  pvs>=0.99: {(t.pvs>=0.99).sum()}")
    print(f"  fills up/dn {t.filled_up_sh.mean():.1f}/{t.filled_dn_sh.mean():.1f} sh  flow_cap {100*t.flow_capture.mean():.2f}%  maker {100*t.maker_pct.mean():.0f}%")
    print(f"  fill_below_touch: mean {fb.mean():.2f} ticks  min {fb.min():.2f}  <1 tick: {(fb<1).sum()}/{len(fb)}")
    print(f"  backstop: flattened_sh mean {t.residual_flattened_sh.mean():.1f} (>0 in {(t.residual_flattened_sh>0).sum()} wins)  cost mean {t.residual_backstop_cost_usd.mean():+.3f}")
    print(f"  pair_gate_bound_sh>0: {(t.pair_gate_bound_sh>0).sum()} wins (mean {t.pair_gate_bound_sh.mean():.2f})")
    if "coc_triggers" in t and t.coc_triggers.notna().any() and t.coc_triggers.sum() > 0:
        print(f"  COC: triggers {t.coc_triggers.sum():.0f}  completions {t.coc_completions.sum():.0f}  cuts {t.coc_cuts.sum():.0f}  delta_vs_hold sum {t.coc_pnl_delta_vs_hold_usd.sum():+.2f}  fees {t.coc_taker_fee_usd.sum():.2f}")

print()
print("="*100)
print("B. TRUST AUDIT (all sleeves, settled traded)")
print("="*100)
t = df[df.traded & df.outcome.notna()].copy()
recon = t.paired_pnl_locked_usd.fillna(0) + t.rebate_usd.fillna(0) + t.residual_pnl_usd.fillna(0)
dd = (t.total_net_usd - recon).abs()
print(f"total_net == paired+rebate+residual: maxdiff {dd.max():.6f}  rows>1e-6: {(dd>1e-6).sum()}")
if (dd > 1e-6).any():
    bad = t[dd > 1e-6]
    print("  DIVERGING sample:"); print(bad[["sleeve","ts","total_net_usd","paired_pnl_locked_usd","rebate_usd","residual_pnl_usd","coc_pnl_delta_vs_hold_usd","coc_taker_fee_usd","coc_cut_cost_usd"]].head(4).to_string(index=False))
    # try v4 identity incl coc terms
    recon2 = recon + t.coc_pnl_delta_vs_hold_usd.fillna(0)
    print(f"  with +coc_delta: maxdiff {(t.total_net_usd-recon2).abs().max():.6f}")
m = t.dropna(subset=["pvs"])
print(f"paired_pnl == paired_sh*(1-pvs): maxdiff {(m.paired_pnl_locked_usd - m.paired_sh*(1-m.pvs)).abs().max():.6f}")
print(f"outcome cross-check: outcome_binance present {t.outcome_binance.notna().sum()}  MISMATCH vs outcome: {(t.outcome_binance.notna() & (t.outcome!=t.outcome_binance)).sum()}")
print(f"outcome_source dist: {t.outcome_source.value_counts(dropna=False).to_dict()}")
print(f"settle_attempts: max {t.settle_attempts.max():.0f}  >1: {(t.settle_attempts>1).sum()}")
print(f"unsettled traded windows (outcome null, excl last hour): ", end="")
un = df[df.traded & df.outcome.isna() & (df.ts < df.ts.max() - pd.Timedelta('1h'))]
print(f"{len(un)}  ({un.sleeve.value_counts().to_dict() if len(un) else ''})")
print(f"rebate model: rate_assumed uniq {df.rebate_rate_assumed.dropna().unique()[:3] if 'rebate_rate_assumed' in df.columns else 'n/a'}")
print(f"taker_completions total: {t.taker_completions.sum():.0f}  outcome_none_held_sh total: {t.outcome_none_held_sh.sum():.1f}")

print()
print("="*100)
print("C. V3-15M vs V2 BASELINE (the fix working?)")
print("="*100)
v3 = t[t.sleeve == "poly_ladder_btc_15m_v3"]
rr = v3[v3.residual_side.isin(["up","dn"])]
held = rr[rr.residual_flattened_sh < rr.residual_sh]  # any held remainder
print(f"v2 baseline: net −0.91/win, residual −2.46/win (win-rate 14.1% at 0.396)")
print(f"v3 15m: net {v3.total_net_usd.mean():+.3f}/win, residual {v3.residual_pnl_usd.mean():+.3f}/win")
print(f"v3 residual entries: med {rr.residual_entry_vwap.median():.3f} | flattened fully {100*(rr.residual_flattened_sh>=rr.residual_sh-1e-9).mean():.0f}% of windows")
print(f"v3 residual heavy-side win-rate (info): {100*(rr.residual_side==rr.outcome).mean():.1f}% (n={len(rr)})")

# per-day table all sleeves
print()
print("per-day net by sleeve:")
df["day"] = df.ts.dt.date
pt = df[df.traded & df.outcome.notna()].pivot_table(index="day", columns="sleeve", values="total_net_usd", aggfunc="sum").round(1)
print(pt.to_string())
df.to_pickle(D + "_v3v4.pkl")
