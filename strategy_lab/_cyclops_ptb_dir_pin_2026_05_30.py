"""Pin PTB buckets + direction rule using chainlink RTDS (covers full window)."""
import sys, io
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import numpy as np, pandas as pd
from load import load_chainlink_rtds

print("PTB_DIR_PIN_2026_05_30 OUTPUT START")
F = pd.read_parquet(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cyclops_features_2026_05_30.parquet")
F["bot_up"]=(F["bot_dir"]=="Up").astype(int)
F["ptb_signed"]=F["ptb_grn"].fillna(0)-F["ptb_red"].fillna(0)
F["bms"]=F["btc_price"]-F["strike"]

# --- PTB bucket pin: |ptb| vs |bms| ---
print("\n--- PTB bucket boundaries (|BTC-strike| by |ptb|) ---")
F["aptb"]=F["ptb_signed"].abs(); F["abms"]=F["bms"].abs()
print(F.groupby("aptb")["abms"].agg(["min","mean","max","count"]))
# infer: ptb = floor(|bms|/STEP) capped 5? test steps
for step in [8,10,12,15]:
    pred = np.minimum(np.floor(F["abms"]/step),5)*np.sign(F["bms"])
    exact=(pred==F["ptb_signed"]).mean()*100
    print(f"  ptb=sign(bms)*min(floor(|bms|/{step}),5): exact match {exact:.1f}%")
# test ceil and round
for step in [10,12,15,20]:
    pred = np.minimum(np.round(F["abms"]/step),5)*np.sign(F["bms"])
    print(f"  ptb=sign(bms)*min(round(|bms|/{step}),5): exact {(pred==F['ptb_signed']).mean()*100:.1f}%")

# --- DIRECTION via chainlink RTDS momentum (full-window feed) ---
cl = load_chainlink_rtds("BTC")
cts = cl["timestamp_us"].values.astype("int64")//1_000_000  # seconds
cpx = cl["price_value"].values.astype("float64")
order=np.argsort(cts); cts=cts[order]; cpx=cpx[order]
print("\nchainlink BTC range:", pd.to_datetime(cts.min(),unit='s',utc=True),"->",pd.to_datetime(cts.max(),unit='s',utc=True), "n=",len(cts))
def cl_at(ts_s):
    i=np.searchsorted(cts, int(ts_s), side="right")-1
    return cpx[i] if i>=0 else np.nan
def cret(slot_s, sec):
    a=cl_at(slot_s-sec); b=cl_at(slot_s)
    return (b-a)/a if a and not np.isnan(a) and not np.isnan(b) and a>0 else np.nan

for sec,lbl in [(30,"r30s"),(60,"r1m"),(120,"r2m"),(180,"r3m"),(300,"r5m")]:
    F[lbl]=F["slot_s"].map(lambda s,sec=sec: cret(s,sec))

def acc(pred,mask=None):
    sub=F if mask is None else F[mask]
    p = pred if mask is None else pred[mask]
    ok=(p==sub["bot_up"]); return ok.mean()*100, ok.sum(), len(ok)

print("\n--- DIRECTION RULE SEARCH (chainlink momentum) ---")
for lbl in ["r30s","r1m","r2m","r3m","r5m"]:
    v=F.dropna(subset=[lbl]); pred=(v[lbl]>0).astype(int)
    ok=(pred==v["bot_up"]); print(f"  UP iff {lbl}>0: {ok.mean()*100:5.1f}% ({ok.sum()}/{len(ok)})")
# bms
pred=(F["bms"]>0).astype(int); ok=(pred==F["bot_up"]); print(f"  UP iff BTC>strike: {ok.mean()*100:5.1f}% ({ok.sum()}/{len(ok)})")

# CONTRARIAN subset (bot bets against bms): what predicts them?
contra=F[((F["bms"]>0)&(F["bot_dir"]=="Down"))|((F["bms"]<0)&(F["bot_dir"]=="Up"))].copy()
print(f"\nCONTRARIAN subset n={len(contra)} (bot vs strike-sign):")
for lbl in ["r30s","r1m","r2m","r3m","r5m"]:
    v=contra.dropna(subset=[lbl]);
    if len(v)<5: continue
    pred=(v[lbl]>0).astype(int); ok=(pred==v["bot_up"])
    print(f"  among contrarian, UP iff {lbl}>0: {ok.mean()*100:5.1f}% ({ok.sum()}/{len(ok)})")

# Combined model: direction = sign(r_Nm) momentum continuation? full set
print("\n--- combined: does momentum continuation beat strike? ---")
# bot UP iff (recent chainlink return positive) -- pick best window
best=None
for lbl in ["r30s","r1m","r2m","r3m","r5m"]:
    v=F.dropna(subset=[lbl]); pred=(v[lbl]>0).astype(int); a=(pred==v["bot_up"]).mean()*100
    if best is None or a>best[1]: best=(lbl,a)
print("  best single momentum rule:", best)

# logistic-style: bot_up ~ bms + r2m  (manual: combine signs)
def combo(row):
    # primary momentum r2m, fallback bms
    if not np.isnan(row.get("r2m",np.nan)):
        if row["r2m"]>0: return 1
        if row["r2m"]<0: return 0
    return 1 if row["bms"]>0 else 0
pred=F.apply(combo,axis=1); ok=(pred==F["bot_up"]); print(f"  [r2m sign, fallback strike]: {ok.mean()*100:.1f}% ({ok.sum()}/{len(ok)})")

# maybe direction = sign of move that ALREADY happened from strike to btc combined w/ accel
# check: is bot mean-reverting? UP iff bms<0 (price dipped below strike)
pred=(F["bms"]<0).astype(int); ok=(pred==F["bot_up"]); print(f"  UP iff BTC<strike (mean-revert): {ok.mean()*100:.1f}%")

# time-of-day of fires (UTC hour)
F["utc_hr"]=(pd.to_datetime(F["slot_s"],unit="s",utc=True)).dt.hour
print("\nfire UTC-hour dist:", F["utc_hr"].value_counts().sort_index().to_dict())
print("PTB_DIR_PIN_2026_05_30 OUTPUT END")
