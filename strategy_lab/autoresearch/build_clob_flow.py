"""
CLOB-tape flow features per fire (slug), windowed vs ws_s and fire_us. Uses duckdb to filter+join
the 42M-row trades_polymarket parquet efficiently, then aggregates in pandas. Writes
strategy_lab/autoresearch/_data/clob_flow.parquet (one row per slug).
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd, duckdb
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
TR = ROOT/"data"/"v4"/"canonical"/"trades_polymarket"
OUTD = ROOT/"strategy_lab"/"autoresearch"/"_data"; OUTD.mkdir(parents=True, exist_ok=True)
WIN={"5m":300,"15m":900}

fires = pd.read_parquet(ROOT/"strategy_lab"/"lag_taker_fires_oos_2026_06_01.parquet")
fires["ws_us"]=((fires.slot_start.astype("int64")-fires.tf.map(WIN))*1_000_000).astype("int64")
fires["fire_us"]=fires.fire_us.astype("int64")
F=fires[["slug","asset","ws_us","fire_us"]].drop_duplicates("slug")
print(f"fires={len(F)}",flush=True)

con=duckdb.connect()
con.register("fires",F)
out=[]
for asset in ["BTC","ETH","SOL"]:
    p=str(TR/f"{asset.lower()}.parquet")
    fa=F[F.asset==asset]
    if not len(fa): continue
    # filter+join in duckdb -> small joined trade set (only in-window trades for fire slugs)
    q=f"""
    SELECT t.slug, t.outcome, t.side, t.timestamp_us AS ts, t.price, t.size,
           f.ws_us, f.fire_us
    FROM read_parquet('{p}') t JOIN fires f ON t.slug=f.slug
    WHERE f.asset='{asset}' AND t.timestamp_us BETWEEN f.ws_us - 300000000 AND f.fire_us
    """
    tj=con.execute(q).df().rename(columns={"size":"sz"})
    print(f"[{asset}] joined trades={len(tj)} over {fa.slug.nunique()} slugs",flush=True)
    if not len(tj): continue
    tj["sign"]=np.where(tj.side=="buy",1.0,-1.0)
    tj["pre"]=tj.ts < tj.ws_us
    tj["early"]=(tj.ts>=tj.ws_us)&(tj.ts<=tj.fire_us)
    tj["notional"]=tj.price*tj.sz
    def aggwin(g,m):
        s=g[m]
        if not s.any(): return {}
        gg=g[s]
        netbuy=(gg.sz*gg.sign).sum(); vol=gg.sz.sum()
        up=gg[gg.outcome=="Up"]; dn=gg[gg.outcome=="Down"]
        up_nb=(up.sz*up.sign).sum(); dn_nb=(dn.sz*dn.sign).sum()
        pref=("pre_" if m=="pre" else "early_")
        return {pref+"ntr":len(gg), pref+"vol":vol, pref+"buyimb":(netbuy/vol if vol else 0),
                pref+"aggr":(gg.side=="buy").mean(), pref+"maxsz":gg.sz.max(),
                pref+"meansz":gg.sz.mean(), pref+"vwap":(gg.notional.sum()/vol if vol else np.nan),
                pref+"up_netbuy":up_nb, pref+"dn_netbuy":dn_nb, pref+"xtok":up_nb-dn_nb,
                pref+"impact":(gg.sort_values("ts").price.iloc[-1]-gg.sort_values("ts").price.iloc[0])}
    rows=[]
    for slug,g in tj.groupby("slug"):
        r={"slug":slug}; r.update(aggwin(g,"pre")); r.update(aggwin(g,"early")); rows.append(r)
    out.append(pd.DataFrame(rows))
res=pd.concat(out,ignore_index=True) if out else pd.DataFrame()
# fill: slugs with no trades in window get 0 activity
allslugs=F[["slug"]].drop_duplicates()
res=allslugs.merge(res,on="slug",how="left")
numcols=[c for c in res.columns if c!="slug"]
res[numcols]=res[numcols].fillna(0)
res.to_parquet(OUTD/"clob_flow.parquet",index=False)
print(f"wrote clob_flow.parquet n={len(res)} feats={len(numcols)}",flush=True)
print("nonzero pre_ntr:",int((res.pre_ntr>0).sum()),"early_ntr:",int((res.early_ntr>0).sum()),flush=True)
