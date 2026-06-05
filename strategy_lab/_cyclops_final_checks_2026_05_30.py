"""Final checks: direction vs displayed arrow, watch gate, win/loss mislabel detail, entry self-consistency."""
import sys, io, re
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import numpy as np, pandas as pd
from load import load_resolutions

print("FINAL_CHECKS_2026_05_30 OUTPUT START")
P = pd.read_parquet(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cyclops_clean_2026_05_30.parquet")
F = pd.read_parquet(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cyclops_features_2026_05_30.parquet")
F["bms"]=F["btc_price"]-F["strike"]
F["ptb_signed"]=F["ptb_grn"].fillna(0)-F["ptb_red"].fillna(0)

# Need ptb_arrow -> reparse from raw since features lost it; reload csv
csv=pd.read_csv(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cyclops_signals.csv")
arrows={}
for _,r in csv[csv["type"]=="SIGNAL"].iterrows():
    m=re.search(r"BTC\s*([▲▼≈])\s*PTB",str(r["raw"]))
    arrows[r["msg_id"]]=m.group(1) if m else None
F["ptb_arrow"]=F["msg_id"].map(arrows)

# Direction vs displayed arrow
print("\nbot_dir vs ptb_arrow:")
print(pd.crosstab(F["bot_dir"],F["ptb_arrow"]))
# arrow ▲->Up ▼->Down ; for ≈ (neutral) what does bot pick?
neutral=F[F["ptb_arrow"]=="≈"]
print(f"\nneutral-arrow signals n={len(neutral)}: dir dist={neutral['bot_dir'].value_counts().to_dict()}")
print("  among neutral, UP iff bms>0:", ((neutral['bot_dir']=='Up')==(neutral['bms']>0)).mean()*100,"%")
print("  among neutral, bms dist sign:", np.sign(neutral['bms']).value_counts().to_dict())

# Best direction rule = follow arrow; arrow itself = sign(bms). Confirm bot_dir==arrow
F["arrow_up"]=F["ptb_arrow"].map({"▲":1,"▼":0,"≈":np.nan})
av=F.dropna(subset=["arrow_up"])
print("\nbot_dir == arrow direction (non-neutral):",
      ((av["bot_dir"]=="Up")==(av["arrow_up"]==1)).mean()*100,"%  n=",len(av))

# So full direction model: dir = arrow = sign(BTC-strike); on neutral, tiebreak
def model(row):
    if row["bms"]>0: return "Up"
    if row["bms"]<0: return "Down"
    return row["bot_dir"]  # neutral undetermined
F["pred"]=F.apply(model,axis=1)
print("MODEL [dir=sign(BTC-strike), neutral=?] reproduces:",
      (F["pred"]==F["bot_dir"]).mean()*100,"%")
nonzero=F[F["bms"]!=0]
print("  on |BTC-strike|>0 only:", ((nonzero["bms"]>0)==(nonzero["bot_dir"]=="Up")).mean()*100,"%  n=",len(nonzero))

# WATCHING gate: parse watch UP/DN cents and BTC; what's different from SIGNAL?
wat=csv[csv["type"]=="WATCHING"].copy()
def wparse(raw):
    bm=re.search(r"BTC\s+\$([\d,]+)",raw);
    up=re.search(r"UP\s+(\d+)¢",raw); dn=re.search(r"DN\s+(\d+)¢",raw)
    mk=re.search(r"Market\s+(\w+)",raw)
    return (float(bm.group(1).replace(",",""))if bm else np.nan,
            int(up.group(1))if up else np.nan,
            int(dn.group(1))if dn else np.nan,
            mk.group(1) if mk else None)
wat[["btc","up_c","dn_c","market"]]=wat["raw"].apply(lambda r: pd.Series(wparse(str(r))))
print("\nWATCHING market-state dist:", wat["market"].value_counts().to_dict())
print("WATCHING UP/DN cents: up median", wat["up_c"].median(), "dn median", wat["dn_c"].median(),
      " both=50:", ((wat["up_c"]==50)&(wat["dn_c"]==50)).mean()*100,"%")
# SIGNAL entry cents dist (fired) vs watch (50/50)
print("SIGNAL entry_cents dist:", F["entry_cents"].describe()[["min","25%","50%","75%","max"]].to_dict())
print(" -> watch when book ~50/50 (no edge); fire when entry deviates from 50 (mispriced side)")
print(" SIGNAL entry !=50:", (F["entry_cents"]!=50).mean()*100,"%  entry in [44,56]:", F["entry_cents"].between(44,56).mean()*100,"%")

# mult/entry vig
F["vig"]=F["mult"]*F["entry_cents"]/100
print("\nmult*entry (payout consistency, should ~1.0):", F["vig"].describe()[["mean","50%","min","max"]].to_dict())

# WIN/LOSS mislabel detail vs chainlink
res=load_resolutions(assets=["BTC"],timeframes=["5m"]).copy()
res["slot_s"]=res["slot_start_us"]//1_000_000
rmap=res.set_index("slot_s")["outcome"].to_dict()
wl=P[P["type"].isin(["WIN","LOSS"])].copy()
wl["clo"]=wl["slot_start_utc"].map(lambda s: rmap.get(int(s)) if pd.notna(s) else None)
wl["bot_dir2"]=wl["direction"].str.title()
wlm=wl.dropna(subset=["clo"]).copy()
wlm["cl_win"]=(wlm["bot_dir2"]==wlm["clo"])
wlm["bot_win"]=(wlm["type"]=="WIN")
mis=wlm[wlm["cl_win"]!=wlm["bot_win"]]
print(f"\nWIN/LOSS mislabels vs chainlink: {len(mis)}/{len(wlm)} = {len(mis)/len(wlm)*100:.1f}%")
print("  mv_delta of mislabeled (near-zero moves?):", mis["mv_delta"].abs().describe()[["mean","50%","max"]].to_dict())
print("  mv_delta all:", wlm["mv_delta"].abs().median(), "median")
# bot uses its own settle px (binance close) vs chainlink -> tie-ish slots mislabel
print("FINAL_CHECKS_2026_05_30 OUTPUT END")
