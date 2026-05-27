"""Resume only TASK 3 (PVSRA join) + TASK 4 from saved panels."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RESULTS = ROOT / "data" / "v4" / "canonical" / "_results"

sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))
from rf_sweep_pvsra_5m import join_pvsra_onto_fires, task4_standalone_pvsra_signal

# Load saved panels — these have the renamed column
pv5  = pd.read_parquet(RESULTS / "pvsra_5m.parquet")
pv15 = pd.read_parquet(RESULTS / "pvsra_15m.parquet")
print("[resume] loaded pv5", len(pv5), "pv15", len(pv15), flush=True)

join_pvsra_onto_fires(pv5, 300_000_000, "5m",
                        RESULTS / "s15_with_rf.parquet",
                        RESULTS / "s15_with_pvsra5m.parquet")
join_pvsra_onto_fires(pv5, 300_000_000, "5m",
                        RESULTS / "s6_with_rf.parquet",
                        RESULTS / "s6_with_pvsra5m.parquet")
join_pvsra_onto_fires(pv15, 900_000_000, "15m",
                        RESULTS / "v15m_with_ta_markov_rf.parquet",
                        RESULTS / "v15m_with_pvsra15m.parquet")

task4_standalone_pvsra_signal(RESULTS / "s15_with_pvsra5m.parquet")
print("[resume] done", flush=True)
