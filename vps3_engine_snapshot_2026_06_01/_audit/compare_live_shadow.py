import csv, collections, datetime as dt

SNAP = ".."
def load(p):
    return [r for r in csv.DictReader(open(p, encoding="utf-8")) if r.get("sleeve_id")]

ire = load(f"{SNAP}/ireland_fires_7d.csv")
v3  = load(f"{SNAP}/vps3_shadow_fires_compare_7d.csv")

def f(x):
    try: return float(x)
    except: return None
def i(x):
    try: return int(float(x))
    except: return None
def won(r):
    return str(r.get("won")).lower()=="true"
def parse_at(s):
    # '2026-06-02 18:55:39.423622+00'
    try:
        s=s.split(".")[0].replace("+00","").strip()
        return dt.datetime.strptime(s,"%Y-%m-%d %H:%M:%S")
    except: return None

def agg(rows):
    n=len(rows)
    if n==0: return None
    w=sum(won(r) for r in rows)/n
    ups=sum(1 for r in rows if str(r.get("direction","")).upper()=="UP")
    vws=[f(r.get("fill_vwap")) for r in rows if f(r.get("fill_vwap")) is not None]
    pnl=sum(f(r.get("pnl_usd")) or 0 for r in rows)
    return dict(n=n, wr=round(w,3), up=ups, dn=n-ups, up_pct=round(ups/n,3),
               avg_vwap=round(sum(vws)/len(vws),3) if vws else None, pnl=round(pnl,2),
               pnl_per=round(pnl/n,3))

# index by sleeve
ire_by = collections.defaultdict(list)
for r in ire: ire_by[r["sleeve_id"]].append(r)
v3_by = collections.defaultdict(list)
for r in v3: v3_by[r["sleeve_id"]].append(r)

print("="*78)
print("IRELAND LIVE per-sleeve (resolved 7d):")
print("="*78)
for sid in sorted(ire_by, key=lambda s:-len(ire_by[s])):
    a=agg(ire_by[sid]); rows=ire_by[sid]
    venue=rows[0].get("venue") or "poly"; mode=rows[0].get("mode") or "?"; fm=rows[0].get("fill_method") or "?"
    real = "REAL$" if (fm in ("live","l25_walk")) else ("PAPER" if "paper" in (fm or mode or "") else mode)
    print(f"  {sid[:54]:54s} v={venue[:6]:6s} {real:6s} n={a['n']:3d} wr={a['wr']:.3f} up={a['up']:3d}/dn={a['dn']:3d} vwap={a['avg_vwap']} pnl={a['pnl']:8.2f}")

# ---- Comparison pairs: (label, ireland_sleeve, shadow_sleeve) ----
PAIRS = [
 ("ema_down POLY-LIVE", "poly_sniper_v5_btc_15m_ema50_ema800_off600_down_LIVE", "poly_sniper_v5_btc_15m_ema50_ema800_off600_down"),
 ("ema_down KALSHI-LIVE","kalshi_sniper_btc_15m_ema50_ema800_off600_down", "poly_sniper_v5_btc_15m_ema50_ema800_off600_down"),
 ("eth l_ema50 POLY-LIVE","poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8_LIVE","poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8"),
 ("q_parent15m (May31 l25test)","poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8","poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8"),
 ("parent15m_notrang (l25test)","poly_sniper_v5_btc_5m_parent15m_notrang_ts_mpskew_v7","poly_sniper_v5_btc_5m_parent15m_notrang_ts_mpskew_v7"),
 ("up_b2_contrarian (l25test)","poly_sniper_v5_btc_5m_up_b2_contrarian2k_v9","poly_sniper_v5_btc_5m_up_b2_contrarian2k_v9"),
 ("sol_momo_v2_HOLD","poly_updown_sol_5m_momo_v2_HOLD_f7","poly_updown_sol_5m_momo_v2_HOLD_f7"),
]

print("\n"+"="*78)
print("LIVE vs SHADOW aggregate (same strategy):")
print("="*78)
for label, isid, ssid in PAIRS:
    la=agg(ire_by.get(isid,[])); sa=agg(v3_by.get(ssid,[]))
    if not la: print(f"  {label:30s}: no Ireland fires"); continue
    if not sa: print(f"  {label:30s}: LIVE n={la['n']} wr={la['wr']} | NO shadow rows"); continue
    print(f"  {label:30s}: LIVE n={la['n']:3d} wr={la['wr']:.3f} up%={la['up_pct']:.2f} vwap={la['avg_vwap']} pnl/f={la['pnl_per']:+.3f}")
    print(f"  {'':30s}  SHAD n={sa['n']:3d} wr={sa['wr']:.3f} up%={sa['up_pct']:.2f} vwap={sa['avg_vwap']} pnl/f={sa['pnl_per']:+.3f}")

# ---- Slot-level join: ema_down POLY-LIVE vs SHADOW on ws_s ----
def by_ws(rows):
    d={}
    for r in rows:
        k=i(r.get("ws_s"))
        if k is not None: d[k]=r
    return d

print("\n"+"="*78); print("SLOT-LEVEL JOIN — ema_down Poly-LIVE vs Shadow (key=ws_s):"); print("="*78)
L=by_ws(ire_by.get("poly_sniper_v5_btc_15m_ema50_ema800_off600_down_LIVE",[]))
S=by_ws(v3_by.get("poly_sniper_v5_btc_15m_ema50_ema800_off600_down",[]))
common=set(L)&set(S)
print(f"  live slots={len(L)} shadow slots={len(S)} common={len(common)} live-only={len(set(L)-set(S))} shadow-only={len(set(S)-set(L))}")
if common:
    same_dir=sum(1 for k in common if L[k].get("direction")==S[k].get("direction"))
    same_out=sum(1 for k in common if L[k].get("outcome")==S[k].get("outcome"))
    same_win=sum(1 for k in common if won(L[k])==won(S[k]))
    print(f"  on common slots: same_direction={same_dir}/{len(common)}  same_outcome={same_out}/{len(common)}  same_win={same_win}/{len(common)}")
    dvw=[abs((f(L[k].get('fill_vwap')) or 0)-(f(S[k].get('fill_vwap')) or 0)) for k in common if f(L[k].get('fill_vwap')) and f(S[k].get('fill_vwap'))]
    if dvw: print(f"  mean |fill_vwap_live - fill_vwap_shadow| on common = {sum(dvw)/len(dvw):.3f}")

# ---- Kalshi vs Poly-LIVE ema_down: match by resolution time (same 15m slot) ----
print("\n"+"="*78); print("CROSS-VENUE — Kalshi-LIVE vs Poly-LIVE ema_down (match by at within 120s):"); print("="*78)
K=ire_by.get("kalshi_sniper_btc_15m_ema50_ema800_off600_down",[])
P=ire_by.get("poly_sniper_v5_btc_15m_ema50_ema800_off600_down_LIVE",[])
Pat=[(parse_at(r["at"]), r) for r in P if parse_at(r["at"])]
matched=0; same_dir=0; same_out=0
for kr in K:
    kt=parse_at(kr["at"])
    if not kt: continue
    best=None
    for pt,pr in Pat:
        if abs((kt-pt).total_seconds())<=120:
            best=pr; break
    if best:
        matched+=1
        if kr.get("direction")==best.get("direction"): same_dir+=1
        if kr.get("outcome")==best.get("outcome"): same_out+=1
print(f"  kalshi fires={len(K)} poly-live fires={len(P)} matched-by-time={matched}")
if matched:
    print(f"  matched: same_direction={same_dir}/{matched}  same_outcome={same_out}/{matched}")
ka=agg(K); pa=agg(P)
if ka and pa:
    print(f"  KALSHI: wr={ka['wr']} up%={ka['up_pct']} vwap={ka['avg_vwap']} pnl={ka['pnl']} (PAPER fill)")
    print(f"  POLY  : wr={pa['wr']} up%={pa['up_pct']} vwap={pa['avg_vwap']} pnl={pa['pnl']} (REAL fill)")
