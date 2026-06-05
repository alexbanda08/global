"""
Convert bmoney1321 -> staging:
  resolutions/all  -> resolutions_hf rows (derive slug from asset+start_time+tf; REAL outcome)
  orderbooks/*     -> L25 wide per asset (parse bid/ask_levels JSON; label token->outcome via resolution+final-mid)
Output: D:/bmoney_hf/staging/{asset}_l25.parquet, resolutions.parquet
"""
from __future__ import annotations
import glob, json, time
from pathlib import Path
import numpy as np, pandas as pd

BASE=Path(r"D:\bmoney_hf"); STAGE=BASE/"staging"; STAGE.mkdir(exist_ok=True)
LEVELS=25
L25_COLS=["timestamp_us","slug","outcome"]+[f"{p}_{i}" for p in ["ask_price","ask_size","bid_price","bid_size"] for i in range(LEVELS)]
def log(m): print(f"[bmoney] {time.strftime('%H:%M:%S')} {m}", flush=True)

def epoch_s(s):   # robust tz-aware datetime -> epoch seconds (numpy path)
    return pd.to_datetime(s, utc=True).values.astype("datetime64[s]").astype("int64")
def to_us(s):     # -> epoch microseconds
    return pd.to_datetime(s, utc=True).values.astype("datetime64[us]").astype("int64")

# ---- resolutions: derive slug + real outcome ----
rs=pd.read_parquet(BASE/"resolutions"/"all.parquet")
rs=rs[rs["outcome"].isin(["Up","Down"])].copy()
es=epoch_s(rs["start_time"]); ee=epoch_s(rs["end_time"])
secs=ee-es
rs["tf"]=np.where(secs<=300,"5m",np.where(secs<=900,"15m","other"))
mask=np.isin(rs["tf"].values,["5m","15m"])
rs=rs[mask].copy(); es=es[mask]; ee=ee[mask]
rs["slot_start_us"]=es*1_000_000; rs["slot_end_us"]=ee*1_000_000
rs["slug"]=rs["asset"].str.lower()+"-updown-"+rs["tf"]+"-"+es.astype(str)
res_out=rs[["slug","asset","tf","slot_start_us","slot_end_us","outcome"]].rename(columns={"asset":"ticker","tf":"timeframe"})
res_out["ticker"]=res_out["ticker"].str.upper()
res_out["source"]="bmoney1321-real"
res_out.to_parquet(STAGE/"resolutions.parquet", index=False)
slug2out=dict(zip(res_out["slug"], res_out["outcome"]))
log(f"resolutions: {len(res_out):,}  by asset: {res_out.ticker.value_counts().to_dict()}")
log(f"  window {pd.to_datetime(res_out.slot_start_us.min(),unit='us',utc=True)} -> {pd.to_datetime(res_out.slot_start_us.max(),unit='us',utc=True)}")

# ---- orderbooks -> L25 ----
def parse_levels(js):
    try: return json.loads(js) if isinstance(js,str) else (js or [])
    except Exception: return []

acc={a:[] for a in ["btc","eth","sol","xrp"]}
obf=sorted(glob.glob(str(BASE/"orderbooks"/"*.parquet")))
log(f"{len(obf)} orderbook day-files")
for fi,f in enumerate(obf):
    df=pd.read_parquet(f)
    df["asset_l"]=df["asset"].str.lower()
    df["timestamp_us"]=to_us(df["timestamp"])
    df["mid"]=pd.to_numeric(df["mid_price"], errors="coerce")
    # per market: 2 tokens -> winner by final mid -> label via resolution
    for slug, g in df.groupby("market_id"):
        a=g["asset_l"].iloc[0]
        if a not in acc: continue
        toks=g["token_id"].unique()
        if len(toks)!=2: continue
        finals={t: g[g.token_id==t].sort_values("timestamp_us")["mid"].dropna().iloc[-1] if g[g.token_id==t]["mid"].notna().any() else np.nan for t in toks}
        out_res=slug2out.get(slug)
        if out_res is None: continue   # need real resolution to label
        # winner token = higher final mid
        win=max(finals, key=lambda t:(finals[t] if np.isfinite(finals[t]) else -1))
        tok_out={win: out_res, [t for t in toks if t!=win][0]: ("Down" if out_res=="Up" else "Up")}
        for t,sub in g.groupby("token_id"):
            oc=tok_out[t]
            for _,r in sub.iterrows():
                bids=parse_levels(r["bid_levels"]); asks=parse_levels(r["ask_levels"])
                row={"timestamp_us":int(r["timestamp_us"]),"slug":slug,"outcome":oc}
                for i in range(LEVELS):
                    if i<len(bids): row[f"bid_price_{i}"]=np.float32(bids[i]["price"]); row[f"bid_size_{i}"]=np.float32(bids[i]["size"])
                    else: row[f"bid_price_{i}"]=np.nan; row[f"bid_size_{i}"]=np.nan
                    if i<len(asks): row[f"ask_price_{i}"]=np.float32(asks[i]["price"]); row[f"ask_size_{i}"]=np.float32(asks[i]["size"])
                    else: row[f"ask_price_{i}"]=np.nan; row[f"ask_size_{i}"]=np.nan
                acc[a].append(row)
    log(f"  {fi+1}/{len(obf)} {Path(f).name}  (acc sizes: {[ (k,len(v)) for k,v in acc.items() ]})")

for a,rows in acc.items():
    if rows:
        pd.DataFrame(rows)[L25_COLS].to_parquet(STAGE/f"{a}_l25.parquet", index=False)
        log(f"  {a}_l25: {len(rows):,} rows")
log("DONE")
