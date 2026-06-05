"""
01 — Live stats foundation for the 21 target sleeves.
- Maps dashboard names -> DB sleeve_id (present in local trading_events_30d.parquet).
- Resolution-level live stats: n, WR, sum/mean pnl (0.07-curve PnL as logged), by direction, hedge usage, entry_price dist.
- Extracts each sleeve's signal-fire set (slug, fire_us, direction, all payload features) -> fires/<sleeve>.csv
- Probes signal payload schema (prints union of keys).
Outputs: _results live_stats_21.csv + fires/*.csv ; prints compact summary only.
"""
import pandas as pd, numpy as np, json, os, collections

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
EV = os.path.join(ROOT, r"data\v4\canonical\trading_events_30d.parquet")
OUTD = os.path.join(ROOT, r"strategy_lab\_opt_2026_05_30")
FIRED = os.path.join(OUTD, "fires")
os.makedirs(FIRED, exist_ok=True)

TARGETS = [
 ("sol_5m_rf_tr_partial_mid","sniper"),
 ("eth_5m_tr200_mp_sms_active_off120","sniper"),
 ("btc_5m_ts_mpskew_any_off30","sniper"),
 ("btc_15m_ema50_ema800_off600_down","sniper"),
 ("eth_5m_cloud_ribbon_mp_hurst_v6","sniper"),
 ("eth_5m_v5repl_off120_v6","sniper"),
 ("eth_5m_bb_mp_hurst_band_v6","sniper"),
 ("sol_5m_cci_f7_mfi_partial_vwap_v6","sniper"),
 ("sol_5m_f7_mfi_ema200_vwap_v6","sniper"),
 ("btc_15m_vwapprem_ema50_mpskew_off600_v6","sniper"),
 ("btc_5m_parent15m_notrang_ts_mpskew_v7","sniper"),
 ("eth_5m_cloud_vwap_hurstmp_v7","sniper"),
 ("sol_5m_btcf7_f7overb_ema800_vwap_v7","sniper"),
 ("eth_5m_l_ema50_hurst_grandparent_v8","sniper"),
 ("btc_5m_q_parent15mslope_ts_imb5_v8","sniper"),
 ("btc_5m_l_1hrf_imb5_ribbon_v8","sniper"),
 ("sol_5m_j_2asset_trending_cci_rf_ema200_v8","sniper"),
 ("eth_5m_bb_mp_hurst_band_v6_vL","sniper"),
 ("btc_5m_up_a2_hlcascade50k_v9","sniper"),
 ("ALL_5m_phase1_kelly","shadow"),
 ("ALL_5m_S3_prewindow","shadow"),
]

df = pd.read_parquet(EV, columns=["at","sleeve_id","kind","data"])
distinct = set(df["sleeve_id"].dropna().unique())

def resolve_name(suffix, kind):
    cands = []
    if kind == "sniper":
        cands = ["poly_sniper_v5_"+suffix]
    else:
        cands = ["shadow_poly_updown_"+suffix]
    for c in cands:
        if c in distinct:
            return c, "exact"
    # fallback: any distinct ending with suffix
    hits = [s for s in distinct if s.endswith(suffix)]
    if len(hits) == 1:
        return hits[0], "endswith"
    if len(hits) > 1:
        return hits[0], "ambiguous:"+str(len(hits))
    # contains
    hits = [s for s in distinct if suffix in s]
    if hits:
        return hits[0], "contains:"+str(len(hits))
    return None, "MISSING"

name_map = {}
print("=== NAME MAP ===")
for suf, knd in TARGETS:
    nm, how = resolve_name(suf, knd)
    name_map[suf] = nm
    print(f"{suf:42s} -> {nm}  [{how}]")

target_ids = set(v for v in name_map.values() if v)
sub = df[df["sleeve_id"].isin(target_ids)].copy()

def jget(d, *keys, default=None):
    for k in keys:
        if isinstance(d, dict) and k in d and d[k] is not None:
            return d[k]
    return default

# ---- Resolution stats ----
res = sub[sub["kind"] == "poly_updown_resolution"]
rows = []
for sid, g in res.groupby("sleeve_id"):
    pnl = []; won = []; dirs = []; ep = []; hedged = 0; qty = []
    for d in g["data"]:
        if not isinstance(d, dict):
            try: d = json.loads(d)
            except: continue
        try: pnl.append(float(d.get("pnl_usd")))
        except: pnl.append(np.nan)
        won.append(bool(d.get("won")))
        dirs.append(d.get("signal"))
        try: ep.append(float(d.get("entry_price")))
        except: pass
        try: qty.append(float(d.get("entry_qty")))
        except: pass
        if d.get("hedged"): hedged += 1
    pnl = np.array(pnl, dtype=float)
    n = len(pnl)
    rows.append(dict(
        sleeve_id=sid, n=n, wr=round(100*np.mean(won),1) if n else 0,
        sum_pnl=round(np.nansum(pnl),1), mean_pnl=round(np.nanmean(pnl),3) if n else 0,
        n_up=sum(1 for x in dirs if x=="UP"), n_down=sum(1 for x in dirs if x=="DOWN"),
        wr_up=round(100*np.mean([w for w,x in zip(won,dirs) if x=="UP"]),1) if any(x=="UP" for x in dirs) else None,
        wr_down=round(100*np.mean([w for w,x in zip(won,dirs) if x=="DOWN"]),1) if any(x=="DOWN" for x in dirs) else None,
        ep_med=round(np.median(ep),3) if ep else None,
        ep_p10=round(np.percentile(ep,10),3) if ep else None,
        ep_p90=round(np.percentile(ep,90),3) if ep else None,
        qty_med=round(np.median(qty),1) if qty else None,
        hedged=hedged,
    ))
rstat = pd.DataFrame(rows).sort_values("sum_pnl", ascending=False)
rstat.to_csv(os.path.join(OUTD,"live_stats_21.csv"), index=False)

# ---- Signal-fire schema probe + extraction ----
sig = sub[sub["kind"] == "poly_updown_signal"]
keycount = collections.Counter()
for d in sig["data"].iloc[:5000]:
    if isinstance(d, dict):
        keycount.update(d.keys())
print("\n=== SIGNAL PAYLOAD KEYS (top 40 by freq in 5k sample) ===")
for k,c in keycount.most_common(40):
    print(f"  {k}: {c}")

# fired = reason != no_signal AND has a directional signal
def is_fire(d):
    if not isinstance(d, dict): return False
    sgn = d.get("signal")
    rsn = d.get("reason")
    return (sgn in ("UP","DOWN")) and (rsn != "no_signal")

print("\n=== FIRE EXTRACTION ===")
fire_summary = []
for sid, g in sig.groupby("sleeve_id"):
    recs = []
    for at, d in zip(g["at"], g["data"]):
        if not isinstance(d, dict):
            try: d = json.loads(d)
            except: continue
        if not is_fire(d): continue
        rec = dict(d); rec["_at"] = at
        recs.append(rec)
    if not recs:
        fire_summary.append((sid,0)); continue
    fdf = pd.DataFrame(recs)
    safe = sid.replace("poly_sniper_v5_","").replace("shadow_poly_updown_","")
    fdf.to_csv(os.path.join(FIRED, safe+".csv"), index=False)
    fire_summary.append((sid, len(fdf)))

print("\n=== LIVE RESOLUTION STATS (sorted by sum_pnl) ===")
print(rstat[["sleeve_id","n","wr","sum_pnl","mean_pnl","n_up","n_down","ep_med","hedged"]].to_string(index=False))
print("\n=== FIRE COUNTS (signal events, directional) ===")
for sid,n in sorted(fire_summary, key=lambda x:-x[1]):
    print(f"  {n:5d}  {sid}")
print("\nWROTE:", os.path.join(OUTD,"live_stats_21.csv"))
