"""Lightweight finisher for the hybrid MM engine — best cell + guide filters, ONE heavy pass,
checkpointed so a crash can't lose it. Reuses functions from _mm_hybrid_engine.py.
Best cell from the partial grid = gate_G=0.97, taker_trigger=50 (OOS −0.32, the least-negative).
"""
import sys, time, os
sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, os.path.dirname(__file__))
import importlib.util
import numpy as np, pandas as pd

spec = importlib.util.spec_from_file_location("mmh", os.path.join(os.path.dirname(__file__), "_mm_hybrid_engine.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

OUT = os.path.join(os.path.dirname(__file__), "cache", "_mm_hybrid_best_full.parquet")
GATE_G, TRIG = 0.97, 50

t0 = time.time()
print("=== HYBRID FINISH: best cell + guide filters ===", flush=True)
res_df = m.load_resolutions()
res_IS = res_df[res_df["slot_start_us"] < m.IS_CUTOFF_US]
res_OOS = res_df[res_df["slot_start_us"] >= m.IS_CUTOFF_US]
slug_set = set(res_df["slug"])
print(f"slugs {len(res_df)} IS={len(res_IS)} OOS={len(res_OOS)}", flush=True)
tob = m.load_books_full(slug_set); print(f"books {len(tob)} t={time.time()-t0:.0f}s", flush=True)
ts = m.load_taker_sells(slug_set); print(f"trades {len(ts)} t={time.time()-t0:.0f}s", flush=True)

# ── ONE heavy pass, checkpoint immediately ────────────────────────────────
if os.path.exists(OUT):
    print("loading cached per-slug results", flush=True)
    df = pd.read_parquet(OUT)
else:
    print(f"running best cell gate={GATE_G} trig={TRIG} full universe...", flush=True)
    df = m.run_all_slugs(res_df, tob, taker_sells=ts, gate_G=GATE_G, taker_trigger=TRIG)
    df["gate_G"] = GATE_G; df["taker_trigger"] = TRIG
    df.to_parquet(OUT, index=False)
    print(f"SAVED {OUT}  t={time.time()-t0:.0f}s", flush=True)

dIS = df[df.is_oos == "IS"]; dOOS = df[df.is_oos == "OOS"]
print("\n--- BEST CELL (gate 0.97 / trig 50) ---")
print("IS :", m.summarize(dIS, label="IS"))
print("OOS:", m.summarize(dOOS, label="OOS"))

# ── Guide filter 1: regime (select good hours on IS, test on OOS) ──────────
print("\n--- REGIME FILTER (IS-select, OOS-test) ---", flush=True)
good_hours, good_days, by_hour, by_day = m.find_regime_hours(res_IS, dIS)
print("good UTC hours (IS, n>=10):", sorted(good_hours))
print("good weekdays (IS, n>=20):", sorted(good_days))
dR = m.apply_regime_filter(df, good_hours, good_days)
dR_OOS = dR[dR.is_oos == "OOS"]
print(f"regime OOS [{len(dR_OOS)} slugs]:", m.summarize(dR_OOS, label="OOS+regime"))

# ── Guide filter 2: consecutive-loss pause ────────────────────────────────
print("\n--- CONSEC-LOSS PAUSE K=2 N=1 ---", flush=True)
dC = m.apply_consec_loss_filter(df, K=2, N=1)
dC_OOS = dC[dC.is_oos == "OOS"]
print(f"consec-loss OOS [{len(dC_OOS)} slugs]:", m.summarize(dC_OOS, label="OOS+consec"))

# ── regime + consec combined ──────────────────────────────────────────────
dRC = m.apply_consec_loss_filter(dR, K=2, N=1)
dRC_OOS = dRC[dRC.is_oos == "OOS"]
print(f"\nregime+consec OOS [{len(dRC_OOS)} slugs]:", m.summarize(dRC_OOS, label="OOS+regime+consec"))

# ── Verdict ───────────────────────────────────────────────────────────────
def verdict(s, name):
    lo = s.get("ci_lo", float("-inf")); ex2 = s.get("ex2", float("-inf"))
    go = (lo is not None and lo > 0) and (ex2 is not None and ex2 > 0)
    print(f"  [{name}] OOS ci_lo={lo}  ex2={ex2}  -> {'GO' if go else 'NO-GO'}")
print("\n=== VERDICT (OOS ci_lo>0 AND ex2>0) ===")
verdict(m.summarize(dOOS), "best cell raw")
verdict(m.summarize(dR_OOS), "regime")
verdict(m.summarize(dC_OOS), "consec")
verdict(m.summarize(dRC_OOS), "regime+consec")
print(f"\ntotal t={time.time()-t0:.0f}s")
