"""Smoke test for Phase 3 anchor rewrite — load klines + universe + gate, no L25.

Verifies (a) VPS3 klines load, (b) per-cell anchors compute finite ret_2m,
(c) q90 gate produces reasonable counts, (d) gated hit rate is in 50-55% range
(matching production's 52% HOLD hit rate — anything wildly off means anchor bug).
"""
import sys, os
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\meta_classifier")
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab")
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import importlib.util
spec = importlib.util.spec_from_file_location("mfuv", "strategy_lab/meta_classifier/momo_full_universe_validation.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

import pandas as pd

print(">>> klines")
kl = m.load_klines()

print("\n>>> base universe")
uni = m.load_universe()
print(f"base universe: {len(uni)} markets, range {uni.day.min().date()} → {uni.day.max().date()}")

frames = []
for (v, tf), (off0, off1) in m.SLEEVE_ANCHORS.items():
    sub = uni[uni.tf == tf].copy()
    sub["version"] = v
    sub["anchor_off0_s"] = off0
    sub["anchor_off1_s"] = off1
    sub["fire_offset_s"] = m.SLEEVE_FIRE[(v, tf)]
    sub["ret_2m"] = m.compute_ret_2m(sub, kl, off0, off1)
    sub["abs_ret_2m"] = sub.ret_2m.abs()
    print(f"  {v} {tf}: n={len(sub)} finite={sub.ret_2m.notna().sum()} "
          f"abs_ret_2m mean={sub.abs_ret_2m.mean():.6f} q90={sub.abs_ret_2m.quantile(0.9):.6f}")
    frames.append(sub)
all_ = pd.concat(frames, ignore_index=True)

thr = m.compute_thresholds(all_)
all_["threshold"] = all_.apply(
    lambda r: thr.get((r.version, r.asset, r.tf, str(r.day.date())), float("nan")), axis=1)
gated = all_[all_.abs_ret_2m.notna() & all_.threshold.notna() & (all_.abs_ret_2m >= all_.threshold)].copy()
gated["signal"] = gated.ret_2m.apply(lambda x: "UP" if x > 0 else "DOWN")
print(f"\ngated total: {len(gated)}")
print(gated.groupby(["version", "asset", "tf"]).size().to_string())

hit = ((gated.signal == "UP") & (gated.outcome == "Up")) | ((gated.signal == "DOWN") & (gated.outcome == "Down"))
print(f"\noverall hit% on gated: {hit.mean()*100:.2f}  (production HOLD target = 52%)")
print("hit% by version:")
print(gated.groupby("version").apply(
    lambda g: (((g.signal == "UP") & (g.outcome == "Up")) |
               ((g.signal == "DOWN") & (g.outcome == "Down"))).mean() * 100).to_string())
print("hit% by version × tf:")
print(gated.groupby(["version", "tf"]).apply(
    lambda g: (((g.signal == "UP") & (g.outcome == "Up")) |
               ((g.signal == "DOWN") & (g.outcome == "Down"))).mean() * 100).to_string())
