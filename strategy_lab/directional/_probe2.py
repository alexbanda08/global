import sys, re
sys.path.insert(0, "data/v4/canonical")
import pandas as pd, numpy as np
from load import reconstruct_book_10hz
s = pd.read_csv("data/v4/refresh_2026_06_16/smoke/snaps.csv.gz")
d = pd.read_csv("data/v4/refresh_2026_06_16/smoke/deltas.csv.gz")
idx = lambda c: int(c.split("_")[-1])
acol = sorted([c for c in s.columns if re.match(r"ask_price_\d+$", c)], key=idx)
ascol= sorted([c for c in s.columns if re.match(r"ask_size_\d+$", c)], key=idx)
bcol = sorted([c for c in s.columns if re.match(r"bid_price_\d+$", c)], key=idx)
bscol= sorted([c for c in s.columns if re.match(r"bid_size_\d+$", c)], key=idx)
print("acol[:3]", acol[:3], "| bcol[:3]", bcol[:3])
sl, oc = "btc-updown-15m-1781631000", "Down"
g = s[(s.slug==sl)&(s.outcome==oc)].sort_values("timestamp_us")
kbp = g[bcol].to_numpy(float)
print("keyframe bid prices row0[:5]:", kbp[0][:5], "(expect ~0.6 desc)")
kf = (g.timestamp_us.to_numpy(np.int64), g[acol].to_numpy(float), g[ascol].to_numpy(float), kbp, g[bscol].to_numpy(float))
dd = d[(d.slug==sl)&(d.outcome==oc)].sort_values("timestamp_us")[["timestamp_us","side","price","size"]]
print("delta bid sample:", dd[dd.side=="bid"].head(3).to_numpy())
db = reconstruct_book_10hz(kf, dd)
print("recon ask prices last[:5]:", np.round(db[1][-1][:5],3))
print("recon bid prices last[:5]:", np.round(db[3][-1][:5],3), "(expect ~0.6 desc, NOT sizes)")
print("recon bid sizes  last[:5]:", np.round(db[4][-1][:5],1))
