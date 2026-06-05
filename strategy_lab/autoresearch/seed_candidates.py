"""Seed the autoresearch history with a batch of candidates -> findings table."""
import sys, json
from pathlib import Path
import pandas as pd
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE=Path(__file__).resolve().parent; sys.path.insert(0,str(HERE))
import fitness
df=pd.read_parquet(HERE/"_data"/"master_features.parquet")
CANDS=[
 {"name":"clob_only_xgb","features":["clob"],"model":"xgb","entry_filter":"vwap055","exit_dt":45},
 {"name":"indicators_only_xgb","features":["indicators"],"model":"xgb","entry_filter":"vwap055","exit_dt":45},
 {"name":"clob+ind_noentry","features":["clob","indicators"],"model":"xgb","entry_filter":"vwap055","exit_dt":45},
 {"name":"all_xgb_e45","features":["indicators","clob","physics","entry"],"model":"xgb","entry_filter":"vwap055","exit_dt":45},
 {"name":"all_xgb_e60","features":["indicators","clob","physics","entry"],"model":"xgb","entry_filter":"vwap055","exit_dt":60},
 {"name":"all_logit","features":["indicators","clob","physics","entry"],"model":"logit","entry_filter":"vwap055","exit_dt":45},
 {"name":"all_rf","features":["indicators","clob","physics","entry"],"model":"rf","entry_filter":"vwap055","exit_dt":45},
 {"name":"all_xgb_broad","features":["indicators","clob","physics","entry"],"model":"xgb","entry_filter":"broad","exit_dt":45},
 {"name":"all_xgb_deployed","features":["indicators","clob","physics","entry"],"model":"xgb","entry_filter":"deployed","exit_dt":45},
 {"name":"clob_only_broad","features":["clob"],"model":"xgb","entry_filter":"broad","exit_dt":45},
]
rows=[]
for c in CANDS:
    r=fitness.score_candidate(c,df=df.copy())
    rows.append(r)
    print(f"{r['candidate']:22} filt={r.get('entry_filter'):9} all={r.get('all_dpt')!s:>7} "
          f"gated={r.get('gated_dpt')!s:>7}(n={r.get('gated_n')}) lift={r.get('lift')!s:>6} "
          f"CI={r.get('gated_ci')} mix={r.get('gated_asset_mix')} fit={r.get('fitness')}",flush=True)
json.dump(rows,open(HERE/"_data"/"seed_results.json","w"),indent=2,default=str)
print("\nwrote seed_results.json",flush=True)
