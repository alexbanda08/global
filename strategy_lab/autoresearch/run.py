"""
autoresearch DRIVER. Scores the current candidate.py, prints the result, appends to history.jsonl,
and reports whether it beat the best-so-far. This is the loop an agent runs after editing candidate.py.

Usage:  python run.py
"""
import sys, json, time, importlib
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fitness
import candidate as cand_mod
HIST = HERE/"history.jsonl"

def main():
    importlib.reload(cand_mod)
    cand = cand_mod.CANDIDATE
    res = fitness.score_candidate(cand)
    res["ts"] = int(time.time())
    res["candidate_spec"] = cand
    # best so far
    best = None
    if HIST.exists():
        for line in HIST.read_text().splitlines():
            try:
                r = json.loads(line)
                if isinstance(r.get("fitness"), (int, float)):
                    if best is None or r["fitness"] > best["fitness"]: best = r
            except Exception: pass
    with open(HIST, "a") as fh: fh.write(json.dumps(res, default=str)+"\n")
    print(json.dumps({k: res.get(k) for k in
          ["candidate","entry_filter","exit_dt","n","n_lock","features_used","threshold",
           "all_dpt","all_ci","gated_n","gated_dpt","gated_ci","lift","gated_asset_mix","fitness","note"]},
          indent=2, default=str))
    bf = best["fitness"] if best else None
    verdict = "NEW BEST" if (best is None or (isinstance(res.get("fitness"),(int,float)) and res["fitness"]>bf)) else "kept best"
    print(f"\n>>> fitness={res.get('fitness')}  best_so_far={bf}  -> {verdict}")
    print(f">>> KEEP if: gated_ci excludes 0 AND lift>0 AND gated_asset_mix not all-one-asset.")

if __name__ == "__main__":
    main()
