import json, numpy as np, pandas as pd
pd.set_option("display.width", 200)
D = r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/directional/_ireland_6day/"
rng = np.random.default_rng(11)

def ci(x, n=12000):
    if len(x) < 3: return (np.nan, np.nan)
    b = np.array([rng.choice(x, len(x), True).mean() for _ in range(n)])
    return tuple(np.percentile(b, [2.5, 97.5]))

# ---------- VPS3 shadow (paper $5, live WS books) ----------
rows = []
for ln in open(D + "vps3_scalp_exits_clean.tsv", encoding="utf-8"):
    ln = ln.rstrip("\n")
    if not ln or ln == "SET": continue
    at, js = ln.split("\t", 1)
    d = json.loads(js); s = d.get("scalp_exit") or {}
    rows.append(dict(ts=at, slug=d["slug"], dir=d["direction"],
        entry=s.get("entry_vwap"), exit=s.get("exit_vwap"), sh=s.get("shares"),
        pnl=s.get("scalp_pnl_usd"), trig=s.get("exit_trigger"),
        bid_at_exit=s.get("best_bid_at_exit"), depth=s.get("exit_book_depth"),
        dbps=s.get("delta_bps"), fee=s.get("sell_leg_fee_charged")))
v = pd.DataFrame(rows)
v["ts"] = pd.to_datetime(v.ts)
v = v.drop_duplicates(subset=["slug", "dir"])
print("========== VPS3 PYTHON SHADOW (the real strategy, $5 paper on live WS books) ==========")
print(f"n={len(v)}  {v.ts.min():%b %d} -> {v.ts.max():%b %d}   ({(v.ts.max()-v.ts.min()).days}d, {len(v)/max((v.ts.max()-v.ts.min()).days,1):.1f}/day)")
lo, hi = ci(v.pnl.values)
print(f"PnL: sum ${v.pnl.sum():+.2f}   mean ${v.pnl.mean():+.4f}/tr  CI95[{lo:+.3f},{hi:+.3f}]   WR {100*(v.pnl>0).mean():.0f}%")
print(f"entry: med {v.entry.median():.3f} p90 {v.entry.quantile(.9):.3f}  (band<0.55 holds: {100*(v.entry<0.55).mean():.0f}%)")
print(f"exit trigger: {v.trig.value_counts().to_dict()}   sell fee charged: {v.fee.sum():.2f}")
print(f"exit move: med {(v.exit-v.entry).median():+.3f}  depth@exit med {v.depth.median():.0f} sh")
v["wk"] = v.ts.dt.tz_localize(None).dt.to_period("W")
print(v.groupby("wk").pnl.agg(["count", "sum", "mean"]).round(3).to_string())

# ---------- Ireland LIVE $1 ----------
ex, res = [], []
for ln in open(D + "ireland_py_scalp.tsv", encoding="utf-8"):
    ln = ln.rstrip("\n")
    if not ln: continue
    at, sleeve, kind, js = ln.split("\t", 3)
    d = json.loads(js)
    if kind == "poly_updown_scalp_exit":
        s = d.get("scalp_exit") or {}
        ex.append(dict(ts=at, sleeve=sleeve, slug=d.get("slug"), dir=d.get("direction"),
            entry=s.get("entry_vwap"), exit=s.get("exit_vwap"), sh=s.get("shares"),
            pnl=s.get("scalp_pnl_usd"), trig=s.get("exit_trigger"), mode=d.get("mode")))
    else:
        res.append(dict(ts=at, sleeve=sleeve, slug=d.get("slug"), cid=d.get("condition_id"),
            pnl=float(d["pnl_usd"]) if d.get("pnl_usd") else np.nan,
            won=d.get("won"), entry=float(d["entry_price"]) if d.get("entry_price") else np.nan,
            qty=float(d["entry_qty"]) if d.get("entry_qty") else np.nan, mode=d.get("mode")))
e = pd.DataFrame(ex); r = pd.DataFrame(res)
e["ts"] = pd.to_datetime(e.ts); r["ts"] = pd.to_datetime(r.ts)
print("\n========== IRELAND (Python engine) ==========")
print("sleeves in exit tape:", e.sleeve.value_counts().to_dict())
print("sleeves in resolution tape:", r.sleeve.value_counts().to_dict())
for sl, g in e.groupby("sleeve"):
    g = g.drop_duplicates(subset=["slug", "dir"])
    lo, hi = ci(g.pnl.dropna().values)
    print(f"\n[{sl}] EXITS n={len(g)}  modes={g['mode'].value_counts().to_dict()}")
    print(f"  pnl sum ${g.pnl.sum():+.3f}  mean ${g.pnl.mean():+.4f}/tr CI[{lo:+.3f},{hi:+.3f}]  WR {100*(g.pnl>0).mean():.0f}%  entry med {g.entry.median():.3f}")
for sl, g in r.groupby("sleeve"):
    g = g.sort_values("ts").drop_duplicates(subset=["cid"])  # dedup phantom double-resolution
    print(f"[{sl}] RESOLUTIONS(deduped) n={len(g)} pnl sum ${g.pnl.sum():+.3f} mean ${g.pnl.mean():+.4f} WR {100*(g.won==True).mean():.0f}% qty med {g.qty.median()}")
# overlap: do resolutions duplicate exits?
if len(e) and len(r):
    both = set(e.slug) & set(r.slug)
    print(f"\nslugs in BOTH exit+resolution tapes: {len(both)} (checking double-count)")
