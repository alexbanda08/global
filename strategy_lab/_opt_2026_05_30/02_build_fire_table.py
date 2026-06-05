"""
02 — Build unified resolved-fire substrate for the 21 target sleeves (FRESH data, May 30 22:39 UTC).
Handles both schemas:
  - sniper_v5 rich:  fill_vwap, slug, fire_us, fire_offset_s, l25_book_snapshot{}, gates_evaluated{}, direction, won, pnl_usd
  - momo/shadow:     entry_price, entry_qty, signal, won, outcome, pnl_usd  (kelly / prewindow)
Outputs:
  _results/fires_resolved_all.parquet   (one row per resolved trade, flattened)
  prints per-sleeve live stats + available gating features
"""
import pandas as pd, numpy as np, json, os, datetime as dt

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
EV = os.path.join(ROOT, r"data\v4\canonical\trading_events_30d.parquet")
OUTD = os.path.join(ROOT, r"strategy_lab\_opt_2026_05_30")
os.makedirs(os.path.join(OUTD, "_results"), exist_ok=True)

SNIPER = [
 "sol_5m_rf_tr_partial_mid","eth_5m_tr200_mp_sms_active_off120","btc_5m_ts_mpskew_any_off30",
 "btc_15m_ema50_ema800_off600_down","eth_5m_cloud_ribbon_mp_hurst_v6","eth_5m_v5repl_off120_v6",
 "eth_5m_bb_mp_hurst_band_v6","sol_5m_cci_f7_mfi_partial_vwap_v6","sol_5m_f7_mfi_ema200_vwap_v6",
 "btc_15m_vwapprem_ema50_mpskew_off600_v6","btc_5m_parent15m_notrang_ts_mpskew_v7","eth_5m_cloud_vwap_hurstmp_v7",
 "sol_5m_btcf7_f7overb_ema800_vwap_v7","eth_5m_l_ema50_hurst_grandparent_v8","btc_5m_q_parent15mslope_ts_imb5_v8",
 "btc_5m_l_1hrf_imb5_ribbon_v8","sol_5m_j_2asset_trending_cci_rf_ema200_v8","eth_5m_bb_mp_hurst_band_v6_vL",
 "btc_5m_up_a2_hlcascade50k_v9",
]
SHADOW = ["ALL_5m_phase1_kelly","ALL_5m_S3_prewindow"]
ID = {s:"poly_sniper_v5_"+s for s in SNIPER}
ID.update({s:"shadow_poly_updown_"+s for s in SHADOW})
target_ids = set(ID.values())

df = pd.read_parquet(EV, columns=["at","sleeve_id","kind","data"])
df = df[df["sleeve_id"].isin(target_ids) & (df["kind"]=="poly_updown_resolution")].copy()

def J(d):
    if isinstance(d, dict): return d
    try: return json.loads(d)
    except: return {}

def f(x):
    try: return float(x)
    except: return np.nan

rows=[]
for at, sid, data in zip(df["at"], df["sleeve_id"], df["data"]):
    d=J(data)
    bs=d.get("l25_book_snapshot") or {}
    direction = d.get("direction") or d.get("signal")
    entry = d.get("fill_vwap"); entry = d.get("entry_price") if entry is None else entry
    placed = d.get("placed_size_usd")
    if placed is None:
        # momo schema: stake = entry_qty * entry_price
        eq=f(d.get("entry_qty")); ep=f(d.get("entry_price"))
        placed = eq*ep if (eq==eq and ep==ep) else np.nan
    fire_us = d.get("fire_us")
    # hour: prefer fire_us; else event 'at'
    if fire_us:
        hr = dt.datetime.utcfromtimestamp(fire_us/1e6); hour=hr.hour; dow=hr.weekday()
    else:
        ts = pd.Timestamp(at).tz_convert("UTC"); hour=ts.hour; dow=ts.weekday()
    own_vwap = f(bs.get("up_vwap")) if direction=="UP" else (f(bs.get("dn_vwap")) if direction=="DOWN" else np.nan)
    opp_vwap = f(bs.get("dn_vwap")) if direction=="UP" else (f(bs.get("up_vwap")) if direction=="DOWN" else np.nan)
    own_depth = f(bs.get("up_depth_usd")) if direction=="UP" else (f(bs.get("dn_depth_usd")) if direction=="DOWN" else np.nan)
    opp_depth = f(bs.get("dn_depth_usd")) if direction=="UP" else (f(bs.get("up_depth_usd")) if direction=="DOWN" else np.nan)
    vwap_sum = f(bs.get("up_vwap")) + f(bs.get("dn_vwap")) if (bs.get("up_vwap") and bs.get("dn_vwap")) else np.nan
    pnl=f(d.get("pnl_usd"))
    rows.append(dict(
        sleeve=sid.replace("poly_sniper_v5_","").replace("shadow_poly_updown_",""),
        family="sniper" if sid.startswith("poly_sniper") else "shadow",
        asset=(d.get("asset") or d.get("symbol") or "").upper(), tf=d.get("tf"),
        slug=d.get("slug"), direction=direction, outcome=d.get("outcome"),
        won=bool(d.get("won")), pnl_usd=pnl,
        entry_vwap=f(entry), shares=f(d.get("fill_shares") or d.get("entry_qty")),
        placed_usd=f(placed), pnl_per_dollar=(pnl/f(placed)) if (f(placed) and f(placed)==f(placed) and f(placed)!=0) else np.nan,
        fire_us=fire_us, fire_offset_s=f(d.get("fire_offset_s")),
        exit_type=d.get("exit_type"), hedged=bool(d.get("hedged")) or (d.get("hedge_sell_vwap") is not None),
        own_vwap=own_vwap, opp_vwap=opp_vwap, vwap_sum=vwap_sum,
        own_depth=own_depth, opp_depth=opp_depth,
        cross_spread=f(bs.get("cross_spread_old")),
        hour=hour, dow=dow, at=pd.Timestamp(at).tz_convert("UTC"),
    ))
fr=pd.DataFrame(rows)
# normalized pnl to a flat $5 stake for cross-sleeve comparison (sizing-neutral)
fr["pnl_5"]=fr["pnl_per_dollar"]*5.0
fr.to_parquet(os.path.join(OUTD,"_results","fires_resolved_all.parquet"), index=False)

def agg(g):
    return pd.Series(dict(
        n=len(g), wr=round(100*g.won.mean(),1),
        sum_pnl=round(g.pnl_usd.sum(),1), mean_pnl=round(g.pnl_usd.mean(),3),
        mean_pnl5=round(g.pnl_5.mean(),3),
        n_up=(g.direction=="UP").sum(), n_dn=(g.direction=="DOWN").sum(),
        ev_med=round(g.entry_vwap.median(),3),
        off_med=round(g.fire_offset_s.median(),0),
        hedged=g.hedged.sum(),
    ))
summ=fr.groupby("sleeve").apply(agg, include_groups=False).reset_index().sort_values("sum_pnl",ascending=False)
print("=== FRESH LIVE RESOLVED STATS (21 sleeves, "+dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M")+" UTC) ===")
print(summ.to_string(index=False))
print("\nTOTAL resolved rows:", len(fr))
print("zero-n sleeves:", [s for s in ID if s not in set(fr.sleeve.unique())])
print("WROTE _results/fires_resolved_all.parquet")
