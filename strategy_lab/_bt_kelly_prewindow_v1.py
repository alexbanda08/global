"""Independent backtest of kelly + prewindow S3/S4 shadow sleeves.

Recomputes signals from canonical 1s klines + L25 book (best-ask entry_vwap),
applies the exact VPS3 shadow9.py + features_1s.py logic, fills via L25 walk,
resolves via chainlink, prices with the CORRECTED 0.07 fee curve.

Universe: every canonical resolved slot in the live window (May 24 17:47 ->
May 29 13:10 UTC), per timeframe. Mirrors the live "ALL" sleeves.

Fee: pnl_won=(1-vwap)*shares*(1-0.07*vwap); loss=-vwap*shares.
Fills: L25 walk for the kelly notional ($25*mult) / $25 (prewindow),
       subsample_1hz=False, anchor fire_us per phase.
v1.
"""
import sys, math, json
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import numpy as np
import pandas as pd

from load import (load_resolutions, load_klines_1s, load_orderbook_l25_streaming,
                  slug_to_ws_s)

SCR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_kp_fade_scratch"

# ---- live window (UTC) ----
WIN_LO_US = int(pd.Timestamp("2026-05-24 17:00:00", tz="UTC").value // 1000)
WIN_HI_US = int(pd.Timestamp("2026-05-29 13:10:00", tz="UTC").value // 1000)

WINDOW_S = {"5m": 300, "15m": 900}

# ============ feature helpers (verbatim from VPS3 features_1s.py) ============
def _ema(values, span):
    if not values or span <= 0: return []
    a = 2.0/(span+1.0); out=[]; prev=values[0]
    for v in values:
        prev = a*v + (1.0-a)*prev; out.append(prev)
    return out

def macd_hist(closes, fast=12, slow=26, signal=9):
    finite=[float(c) for c in closes if c is not None and math.isfinite(float(c))]
    if len(finite) < slow+signal: return None
    ef=_ema(finite,fast); es=_ema(finite,slow)
    ml=[f-s for f,s in zip(ef,es)]
    sl=_ema(ml[-signal*4:] if len(ml)>signal*4 else ml, signal)
    if not sl: return None
    h=ml[-1]-sl[-1]
    return h if math.isfinite(h) else None

def _norm_cdf(z): return 0.5*(1.0+math.erf(z/math.sqrt(2.0)))

def fair_up(s_now, strike, sigma, tau_s):
    if not all(math.isfinite(x) for x in (s_now,strike,sigma,tau_s)): return None
    if s_now<=0 or strike<=0 or sigma<=0 or tau_s<=0: return None
    try: z=math.log(s_now/strike)/(sigma*math.sqrt(tau_s))
    except (ValueError,ArithmeticError): return None
    return _norm_cdf(z)

def cvd_agree(v,d):
    if v is None or not math.isfinite(v): return False
    return v>0 if d=="UP" else (v<0 if d=="DOWN" else False)
def macd_agree(h,d):
    if h is None or not math.isfinite(h): return False
    return h>0 if d=="UP" else (h<0 if d=="DOWN" else False)
def kelly_mult(fe):
    if fe>3000: return 4.0
    if fe>2000: return 3.0
    if fe>1000: return 2.0
    return 1.0

# ============ per-asset 1s arrays ============
print("BT_START")
print("loading 1s klines...")
ASSETS=["BTC","ETH","SOL"]
S1={}  # asset -> (ts_us[N], close, vol(base), tbq(quote), qv(quote))
for a in ASSETS:
    df=load_klines_1s(a)
    # window pad: need 900s sigma lookback + 300s rvol; pad 1200s before lo
    df=df[(df.time_period_start_us>=WIN_LO_US-1300*1_000_000)&(df.time_period_start_us<=WIN_HI_US+200*1_000_000)]
    df=df.drop_duplicates("time_period_start_us").sort_values("time_period_start_us")
    ts=df.time_period_start_us.values.astype("int64")
    close=df.price_close.values.astype("float64")
    vol=df.volume_traded.values.astype("float64")
    tbq=df.taker_buy_quote.values.astype("float64")
    qv=df.quote_volume.values.astype("float64")
    S1[a]=(ts,close,vol,tbq,qv)
    print(f"  {a}: {len(ts)} 1s bars  {pd.to_datetime(ts.min()/1e6,unit='s')} -> {pd.to_datetime(ts.max()/1e6,unit='s')}")

def _slice(a, lo_us, hi_us):
    ts,close,vol,tbq,qv=S1[a]
    i0=np.searchsorted(ts,lo_us,side="left"); i1=np.searchsorted(ts,hi_us,side="right")
    return ts[i0:i1],close[i0:i1],vol[i0:i1],tbq[i0:i1],qv[i0:i1]

def feat_at(a, fire_us, slot_start_us, slot_end_us):
    """Replicate _phase36_feature_dict using canonical 1s bars."""
    ts,close,vol,tbq,qv=_slice(a, fire_us-1300*1_000_000, fire_us+1_000_000)
    if len(ts)==0: return None
    # mask <= fire_us
    m=ts<=fire_us
    ts=ts[m]; close=close[m]; vol=vol[m]; tbq=tbq[m]; qv=qv[m]
    if len(ts)==0: return None
    # CVD windows
    def cvd(w):
        frm=fire_us-w*1_000_000
        sel=(ts>=frm)
        if sel.sum()==0: return None
        return float(np.sum(2.0*tbq[sel]-qv[sel]))
    cvd30=cvd(30); cvd60=cvd(60)
    # rvol 30/300
    s_frm=fire_us-30*1_000_000; l_frm=fire_us-300*1_000_000
    ssel=ts>=s_frm; lsel=ts>=l_frm
    rvol=None
    if lsel.sum()>0 and ssel.sum()>0:
        sv=float(vol[ssel].sum()); lv=float(vol[lsel].sum())
        buckets=max(1.0,300/30); mshort=lv/buckets
        rvol=sv/mshort if mshort>0 else None
    # sigma (last 900s log-rets)
    sg_frm=fire_us-900*1_000_000; sgsel=ts>=sg_frm
    sigma=None
    cl=close[sgsel]
    cl=cl[np.isfinite(cl)&(cl>0)]
    if len(cl)>=31:
        rets=np.diff(np.log(cl)); rets=rets[np.isfinite(rets)]
        if len(rets)>=30:
            var=rets.var(ddof=1)
            if var>0: sigma=math.sqrt(var)
    # MACD on last 120 closes
    mc=close[np.isfinite(close)&(close>0)]
    if len(mc)>120: mc=mc[-120:]
    macd=macd_hist(list(mc))
    # s_now = last close
    s_now=float(close[-1]) if len(close) else None
    # strike = first close at-or-after slot_start
    sk=None
    ts_all,close_all,_,_,_=_slice(a, slot_start_us-2*1_000_000, slot_start_us+5*1_000_000)
    skm=ts_all>=slot_start_us
    if skm.any(): sk=float(close_all[skm][0])
    elif s_now is not None: sk=s_now
    # tau
    tau=(slot_end_us-fire_us)/1_000_000.0
    tau=tau if tau>0 else None
    fu=fair_up(s_now,sk,sigma,tau) if (s_now and sk and sigma and tau) else None
    # vwap_dev (15m UTC-bucket anchored, base volume)
    bk=(fire_us//(900*1_000_000))*(900*1_000_000)
    vsel=(ts>=bk)
    dev=None; vwap=None
    if vsel.sum()>0:
        cv=close[vsel]; vv=vol[vsel]
        cumv=vv.sum()
        if cumv>0:
            vwap=float((cv*vv).sum()/cumv)
            if vwap>0 and s_now>0: dev=10000.0*math.log(s_now/vwap)
    return dict(cvd_30s=cvd30,cvd_60s=cvd60,rvol_30_300=rvol,sigma=sigma,macd=macd,
                s_now=s_now,strike=sk,tau_s=tau,fair_up=fu,vwap_dev_bps=dev)

# ============ resolution universe ============
res=load_resolutions()
res=res[(res.slot_start_us>=WIN_LO_US)&(res.slot_start_us<=WIN_HI_US)].copy()
res=res[res.ticker.isin(ASSETS)]
print(f"\ncanonical slots in window: {len(res)}  by tf:",res.timeframe.value_counts().to_dict())

# Need L25 best-ask (entry_vwap) at fire_us per slug+outcome. Load L25 per asset.
# To bound RAM: gather all slugs in window per asset, load once at native 10Hz.
BOOKS={}
for a in ASSETS:
    slugs=set(res[res.ticker==a].slug)
    print(f"loading L25 {a} for {len(slugs)} slugs (native 10Hz)...")
    BOOKS[a]=load_orderbook_l25_streaming(a.lower(), slugs=slugs, subsample_1hz=False,
                                          min_ts_us=WIN_LO_US-200*1_000_000, max_ts_us=WIN_HI_US+1000*1_000_000)
    print(f"  {a}: {len(BOOKS[a])} (slug,outcome) book series")

def best_ask_at(a, slug, outcome, fire_us):
    rec=BOOKS[a].get((slug,outcome))
    if rec is None: return None
    ts,ap,asz,bp,bsz=rec
    i=np.searchsorted(ts,fire_us,side="right")-1
    if i<0: return None
    px=ap[i,0]
    return float(px) if math.isfinite(px) and px>0 else None

def walk_fill(a, slug, outcome, fire_us, notional):
    """L25 ask walk for `notional` USD. Returns (avg_vwap, shares) or (None,None)."""
    rec=BOOKS[a].get((slug,outcome))
    if rec is None: return None,None
    ts,ap,asz,bp,bsz=rec
    i=np.searchsorted(ts,fire_us,side="right")-1
    if i<0: return None,None
    aprow=ap[i]; aszrow=asz[i]
    spent=0.0; shares=0.0; rem=notional
    for lvl in range(len(aprow)):
        p=aprow[lvl]; sz=aszrow[lvl]
        if not (math.isfinite(p) and p>0 and math.isfinite(sz) and sz>0): continue
        lvl_cost=p*sz
        if lvl_cost>=rem:
            buy=rem/p; shares+=buy; spent+=rem; rem=0.0; break
        else:
            shares+=sz; spent+=lvl_cost; rem-=lvl_cost
    if shares<=0: return None,None
    return spent/shares, shares

# 0.07 fee curve
def pnl_07(vwap, shares, won):
    if won: return (1.0-vwap)*shares*(1.0-0.07*vwap)
    return -vwap*shares
def pnl_legacy(vwap, shares, won):  # 2% on profit (winning leg)
    if won: return (1.0-vwap)*shares*0.98
    return -vwap*shares

# ============ run strategies ============
SPREAD_FILTER=0.02  # cross-token? live shadow uses best-ask top-of-book; keep simple bid-ask
recs=[]
for _,r in res.iterrows():
    a=r.ticker; tf=r.timeframe; slug=r.slug
    ws_s=int(r.slot_start_us//1_000_000)-WINDOW_S[tf]
    slot_start_us=int(r.slot_start_us); slot_end_us=int(r.slot_end_us)
    outcome_true=r.outcome  # 'Up'/'Down'

    # ---- KELLY: t_plus_120 -> fire = ws_s+120 ----
    fire_k=(ws_s+120)*1_000_000
    f=feat_at(a, fire_k, slot_start_us, slot_end_us)
    if f and f["vwap_dev_bps"] is not None:
        dev=f["vwap_dev_bps"]; direction="UP" if dev>0 else "DOWN"
        leg = "Up" if direction=="UP" else "Down"
        ev=best_ask_at(a,slug,leg,fire_k)
        if ev is not None and f["fair_up"] is not None:
            fe=(f["fair_up"]-ev)*10000.0 if direction=="UP" else ((1.0-f["fair_up"])-ev)*10000.0
            s4=(fe>500 and cvd_agree(f["cvd_30s"],direction) and abs(dev)>=8)
            s8=(macd_agree(f["macd"],direction) and f["rvol_30_300"] is not None and f["rvol_30_300"]>1.2)
            if (s4 or s8):
                mult=kelly_mult(fe); notional=25.0*mult
                vwap,shares=walk_fill(a,slug,leg,fire_k,notional)
                if vwap is not None:
                    won=(leg==outcome_true)
                    recs.append(dict(sleeve="kelly",tf=tf,asset=a,slug=slug,direction=direction,
                                     fe=fe,mult=mult,rule=("S4" if s4 else "S8"),vwap=vwap,shares=shares,
                                     won=won,pnl=pnl_07(vwap,shares,won),pnl_legacy=pnl_legacy(vwap,shares,won)))

    # ---- S3 prewindow (5m only): pre_window_60 -> fire = slot_start-60 ----
    if tf=="5m":
        fire_s3=slot_start_us-60*1_000_000
        f=feat_at(a, fire_s3, slot_start_us, slot_end_us)
        if f and f["vwap_dev_bps"] is not None:
            dev=f["vwap_dev_bps"]; direction="UP" if dev>0 else "DOWN"
            leg="Up" if direction=="UP" else "Down"
            ev=best_ask_at(a,slug,leg,fire_s3)
            if ev is not None and f["fair_up"] is not None:
                fe=(f["fair_up"]-ev)*10000.0 if direction=="UP" else ((1.0-f["fair_up"])-ev)*10000.0
                if fe>0 and cvd_agree(f["cvd_60s"],direction) and macd_agree(f["macd"],direction):
                    vwap,shares=walk_fill(a,slug,leg,fire_s3,25.0)
                    if vwap is not None:
                        won=(leg==outcome_true)
                        recs.append(dict(sleeve="S3_prewindow",tf=tf,asset=a,slug=slug,direction=direction,
                                         fe=fe,mult=1.0,rule="S3",vwap=vwap,shares=shares,
                                         won=won,pnl=pnl_07(vwap,shares,won),pnl_legacy=pnl_legacy(vwap,shares,won)))

    # ---- S4 prewindow (15m only): pre_window_120 -> fire = slot_start-120 ----
    if tf=="15m":
        fire_s4=slot_start_us-120*1_000_000
        f=feat_at(a, fire_s4, slot_start_us, slot_end_us)
        if f and f["vwap_dev_bps"] is not None:
            dev=f["vwap_dev_bps"]
            if abs(dev)>=8:
                direction="UP" if dev>0 else "DOWN"
                leg="Up" if direction=="UP" else "Down"
                ev=best_ask_at(a,slug,leg,fire_s4)
                if ev is not None and f["fair_up"] is not None:
                    fe=(f["fair_up"]-ev)*10000.0 if direction=="UP" else ((1.0-f["fair_up"])-ev)*10000.0
                    if fe>500 and cvd_agree(f["cvd_30s"],direction):
                        vwap,shares=walk_fill(a,slug,leg,fire_s4,25.0)
                        if vwap is not None:
                            won=(leg==outcome_true)
                            recs.append(dict(sleeve="S4_prewindow",tf=tf,asset=a,slug=slug,direction=direction,
                                             fe=fe,mult=1.0,rule="S4",vwap=vwap,shares=shares,
                                             won=won,pnl=pnl_07(vwap,shares,won),pnl_legacy=pnl_legacy(vwap,shares,won)))

bt=pd.DataFrame(recs)
bt.to_csv(SCR+r"\bt_kelly_prewindow.csv", index=False)
print(f"\n=== BACKTEST RESULTS (0.07 fee) ===  total fires={len(bt)}")
for sl,sub in bt.groupby("sleeve"):
    n=len(sub); wr=sub.won.mean()*100; pnl=sub.pnl.sum(); pnl_l=sub.pnl_legacy.sum()
    print(f"  {sl:14s}: n={n:4d} WR={wr:5.1f}% PnL_07={pnl:9.2f} $/tr={pnl/n:7.3f}  | PnL_legacy={pnl_l:9.2f} (fee drag={pnl_l-pnl:7.2f})")
# kelly per tier
print("\n=== BT kelly per-tier ===")
kk=bt[bt.sleeve=="kelly"]
for m,sub in kk.groupby("mult"):
    n=len(sub); print(f"  mult={m:.0f}: n={n:4d} WR={sub.won.mean()*100:5.1f}% PnL_07={sub.pnl.sum():8.2f} $/tr={sub.pnl.sum()/n:7.3f} meanFE={sub.fe.mean():8.1f}")
print("flat-$25 kelly counterfactual PnL_07:", round((kk.pnl/kk.mult).sum(),2))
print("BT_END")
