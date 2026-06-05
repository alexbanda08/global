"""Refine trigger decode: kline coverage, PTB N-search, direction rule search."""
import sys, io, re
import datetime as dt
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import numpy as np, pandas as pd
from load import load_resolutions, load_klines, load_klines_asof, asof_strict, load_chainlink_rtds

print("TRIGGER_REFINE_2026_05_30 OUTPUT START")
feat = pd.read_parquet(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cyclops_features_2026_05_30.parquet")
print("feat rows:", len(feat), " slot range:",
      pd.to_datetime(feat['slot_s'].min(),unit='s',utc=True), "->",
      pd.to_datetime(feat['slot_s'].max(),unit='s',utc=True))

# kline coverage check (1m binance-spot-ws) over the cyclops window
km = load_klines("BTC","binance-spot-ws","1MIN")
km = km.dropna(subset=["price_close"])
print("1m klines rows (non-nan):", len(km), " range:",
      pd.to_datetime(km['ts_s'].min(),unit='s',utc=True),"->",
      pd.to_datetime(km['ts_s'].max(),unit='s',utc=True))
# coverage in cyclops window
lo, hi = feat['slot_s'].min()-600, feat['slot_s'].max()+600
win = km[(km['ts_s']>=lo)&(km['ts_s']<=hi)]
print("1m bars in cyclops window:", len(win), " expected ~", (hi-lo)//60)

# use 1s klines for finer strike (production strike is window-open chainlink px)
# Build asof from 1m
end_us, px = load_klines_asof("BTC","binance-spot-ws","1MIN")
end_us = end_us[~np.isnan(px)]; px = px[~np.isnan(px)]
order = np.argsort(end_us); end_us=end_us[order]; px=px[order]
def close_at(ts_s):
    return asof_strict(end_us, px, int(ts_s)*1_000_000)

# Direction rule: bot UP/DOWN. Test many features. signal time = slot_start (window open).
# But cyclops posts AT window open w/ "Closes in 4-5 min" => decision uses data BEFORE slot open.
F = feat.copy()
F["bot_up"] = (F["bot_dir"]=="Up").astype(int)
# recompute returns ending at slot open
for n in [1,2,3,5,10]:
    F[f"r{n}"] = F["slot_s"].map(lambda s,n=n: (close_at(s)-close_at(s-60*n))/close_at(s-60*n)
                                  if close_at(s-60*n) and not np.isnan(close_at(s-60*n)) and not np.isnan(close_at(s)) else np.nan)
F["bms"] = F["btc_price"]-F["strike"]
F["ptb_signed"] = F["ptb_grn"].fillna(0)-F["ptb_red"].fillna(0)

def acc(pred):
    ok = (pred==F["bot_up"]); return ok.mean()*100, ok.sum(), len(ok)

print("\n--- DIRECTION RULE SEARCH (reproduce bot UP/DOWN, n=%d) ---"%len(F))
rules = {
 "UP iff BTC>strike": (F["bms"]>0).astype(int),
 "UP iff BTC>=strike": (F["bms"]>=0).astype(int),
 "UP iff PTB green": (F["ptb_signed"]>0).astype(int),
 "UP iff PTB>=0 (green or neutral)": (F["ptb_signed"]>=0).astype(int),
 "UP iff r1>0": (F["r1"]>0).astype(int),
 "UP iff r2>0": (F["r2"]>0).astype(int),
 "UP iff r3>0": (F["r3"]>0).astype(int),
 "UP iff r5>0": (F["r5"]>0).astype(int),
}
for name, pred in rules.items():
    a,s,n = acc(pred); print(f"  {name:40s}: {a:5.1f}%  ({s}/{n})")

# combined: PTB sign primary, btc-strike tiebreak
def combo(row):
    if row["ptb_signed"]>0: return 1
    if row["ptb_signed"]<0: return 0
    return 1 if row["bms"]>0 else 0
a,s,n = acc(F.apply(combo,axis=1)); print(f"  {'PTB sign, tiebreak BTC>strike':40s}: {a:5.1f}%  ({s}/{n})")
# btc-strike primary, ptb tiebreak
def combo2(row):
    if row["bms"]>0: return 1
    if row["bms"]<0: return 0
    return 1 if row["ptb_signed"]>=0 else 0
a,s,n=acc(F.apply(combo2,axis=1)); print(f"  {'BTC-strike sign, tiebreak PTB':40s}: {a:5.1f}%  ({s}/{n})")

# Look at the DISAGREEMENT cases: bot DOWN but BTC>strike
contra = F[((F["bms"]>0)&(F["bot_dir"]=="Down"))|((F["bms"]<0)&(F["bot_dir"]=="Up"))]
print(f"\nCONTRARIAN-to-strike signals (bot bets against BTC-vs-strike): {len(contra)}")
print("  their ptb_signed dist:", contra["ptb_signed"].value_counts().sort_index().to_dict())
print("  do they follow PTB? UP iff ptb>0:", ((contra["bot_dir"]=="Up")==(contra["ptb_signed"]>0)).mean()*100,"%")
print("  do they follow r2? UP iff r2>0:", ((contra["bot_dir"]=="Up")==(contra["r2"]>0)).mean()*100,"%")
print("  do they follow r1? UP iff r1>0:", ((contra["bot_dir"]=="Up")==(contra["r1"]>0)).mean()*100,"%")

# PTB N-search: |ptb| should = some momentum count. Test: count of last-N 1s/1m bars same dir
# Try: number of last N 1m closes monotonic in PTB direction
print("\n--- PTB DECODE: |ptb_signed| vs candidate momentum counts ---")
# candidate A: net up-down of last N 1m bars sign matches; magnitude = ?
for N in [3,4,5,6,8,10]:
    # count of last N 1m bars that are up (close>prev close)
    def upcount(s,N=N):
        c=[close_at(s-60*k) for k in range(N+1)]
        c=c[::-1]
        if any(x is None or np.isnan(x) for x in c): return np.nan
        d=np.diff(c); return int((d>0).sum()-(d<0).sum())  # net
    F[f"net{N}"]=F["slot_s"].map(upcount)
    valid = F.dropna(subset=[f"net{N}"])
    sgn = (np.sign(valid[f"net{N}"])==np.sign(valid["ptb_signed"])).mean()*100
    print(f"  N={N:2d}: sign(net_updown)==sign(ptb): {sgn:5.1f}%  corr={valid[[f'net{N}','ptb_signed']].corr().iloc[0,1]:+.3f}")

# PTB vs (BTC - strike): maybe ptb = how far above/below strike in 'pip' buckets
F["bms_buckets"] = F["bms"]  # raw
g = F.groupby("ptb_signed")["bms"].agg(["mean","count"])
print("\nptb_signed vs mean(BTC-strike):")
print(g)

# confidence label rule: dots vs label
print("\nconf_dots x conf_label crosstab:")
print(pd.crosstab(F["conf_dots"], F["conf_label"]))
# mult vs entry: mult = (1/entry)*payout_factor?
F["impl_mult"]=100/F["entry_cents"]
print("\nmult/impl_mult ratio (payout vig):", (F["mult"]/F["impl_mult"]).describe()[["mean","50%","min","max"]].to_dict())

print("TRIGGER_REFINE_2026_05_30 OUTPUT END")
