"""Check condition_id <-> canonical market_id/slug mapping. v1."""
import sys, json
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import pandas as pd
from load import load_resolutions
SCR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\_kp_fade_scratch"

print("CIDMAP_START")
rdf = pd.read_csv(SCR+r"\live_resolutions.csv")
cids = set(rdf.condition_id.dropna().unique())
print("unique live condition_ids:", len(cids))
print("sample:", list(cids)[:3])

res = load_resolutions()
print("canonical resolutions cols:", list(res.columns))
print("canonical market_id sample:", res.market_id.head(3).tolist())
# Does market_id match condition_id?
canon_mids = set(res.market_id.astype(str))
overlap = len(cids & canon_mids)
print(f"condition_id INT canonical market_id: {overlap}/{len(cids)}")
# slug format
print("canonical slug sample:", res.slug.head(5).tolist())
print("CIDMAP_END")
