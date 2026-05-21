"""V6 composite search — given the H8-H15 lift results, identify the best
combination of new rules to add to V2's base composite. Tests carefully
focused composites with H11 (the strongest new signal: lift 1.84) as anchor.

Also computes leftover-on-winner-after-V3 and the residual noise check.
"""
from __future__ import annotations
import os, sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

CACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xeebde7a0_taker_decode"
FEATURES = CACHE / "v6_features.parquet"

t0 = time.time()
def log(m): print(f"[{time.time()-t0:6.1f}s] {m}", flush=True)

# Load the v6 features (V1-un sub of un, with H8-H15 enrichment already computed)
log("loading v6 features ...")
df = pd.read_parquet(FEATURES)
fe = df[df._kind == "fire"].reset_index(drop=True)
ce = df[df._kind == "ctrl"].reset_index(drop=True)
log(f"  fire={len(fe)} ctrl={len(ce)}  (V3-unexplained set)")

# We also need the full V1-unexplained set (807+1002) to re-test composites
fe_all = pd.read_parquet(CACHE / "fire_v5_hypotheses.parquet")
ce_all = pd.read_parquet(CACHE / "control_v5_hypotheses.parquet")
log(f"  V1-un full: fire={len(fe_all)} ctrl={len(ce_all)}")

# v2 base mask
def v2_base(d):
    return d.disc_capture | (d.pm_drop_5s > 0.02) | ((d.offset_s >= 0) & (d.offset_s <= 60))

# A key question — was H11 (buy_vol_60s>50 AND pm_drop_5s>0) computed on the V3-un subset?
# Yes — fe (the v6 features file) is V3-un. Let me apply same rule to FULL V1-un pool to get
# clear coverage extension on the full pool.

# Compute H11 rules on fe_all/ce_all (already have buy_vol_60s, pm_drop_5s)
def h11_mask(d):
    return (d.buy_vol_60s > 50) & (d.pm_drop_5s > 0)

def h11_loose(d):
    return (d.buy_vol_60s > 100) & (d.pm_drop_5s > 0)

# H12 — UTC hour 15
def h12_15(d):
    h = (d.t_sec.astype("int64") // 3600 % 24).astype("int64")
    return h == 15

def h11_or_h12(d):
    return h11_mask(d) | h12_15(d)

# Try a stricter H11 — must coincide with no offset filter conflict (offset NOT in [0,60])
def h11_strict(d):
    """Same as h11_mask but only applies where the V2 base rules are FALSE.
    Note: it's already OR'd, so just OR is fine in composite."""
    return h11_mask(d)

# Need to re-enrich fe_all / ce_all with H8 coinbase / kraken cross-exchange ret
# (only need coinbase_sret_60s, since that was best)
log("re-enriching fe_all / ce_all with H8 cross-exchange ret_60s ...")
from load import load_klines_asof
e_cb, p_cb = load_klines_asof("BTC", "coinbase-spot-ws", "1MIN")
e_ok, p_ok = load_klines_asof("BTC", "okx-ws", "1MIN")

def cs_ret(e, p, t_us, w):
    j = np.searchsorted(e, int(t_us), side="right") - 1
    i = np.searchsorted(e, int(t_us - w*1_000_000), side="right") - 1
    if j < 0 or i < 0 or i >= j: return np.nan
    p_now = p[j]; p_then = p[i]
    if p_then <= 0: return np.nan
    return float(p_now / p_then - 1.0)

def add_h8_cb(d):
    d = d.copy()
    r60 = np.array([cs_ret(e_cb, p_cb, int(r.t_sec)*1_000_000, 60) for r in d.itertuples(index=False)])
    o60 = np.array([cs_ret(e_ok, p_ok, int(r.t_sec)*1_000_000, 60) for r in d.itertuples(index=False)])
    sgn = np.where(d.outcome.values == "Up", 1.0, -1.0)
    d["coinbase_sret_60s"] = sgn * r60
    d["okx_sret_60s"] = sgn * o60
    return d

fe_all = add_h8_cb(fe_all); ce_all = add_h8_cb(ce_all)
log("  done.")

def h8_cb_strong(d):  return d.coinbase_sret_60s > 0.0005
def h8_okx_strong(d): return d.okx_sret_60s > 0.0005

# === Coverage helpers ===
TOTAL_FIRE_FULL = 1349
TOTAL_CTRL_FULL = 1401
fe_v1_captured = TOTAL_FIRE_FULL - len(fe_all)  # 542
ce_v1_captured = TOTAL_CTRL_FULL - len(ce_all)  # 399

def wilson_z(p1, n1, p2, n2):
    if min(n1, n2) == 0: return 0.0
    p = (p1*n1 + p2*n2) / (n1 + n2)
    if p == 0 or p == 1: return 0.0
    se = (p * (1-p) * (1/n1 + 1/n2)) ** 0.5
    return (p1 - p2) / se if se > 0 else 0.0

def eval_composite(name, fe_mask, ce_mask, include_v1=True):
    """fe_mask is OR'd against v2_base. Then we count fires captured on the V1-un pool,
    add fe_v1_captured (i.e., V1-disc-captured fires) and divide by TOTAL_FIRE_FULL."""
    full_fire = v2_base(fe_all) | fe_mask
    full_ctrl = v2_base(ce_all) | ce_mask
    fire_cap = int(full_fire.sum()) + (fe_v1_captured if include_v1 else 0)
    ctrl_cap = int(full_ctrl.sum()) + (ce_v1_captured if include_v1 else 0)
    fr = fire_cap / TOTAL_FIRE_FULL
    cr = ctrl_cap / TOTAL_CTRL_FULL
    lift = fr / cr if cr > 0 else float("inf")
    z = wilson_z(fr, TOTAL_FIRE_FULL, cr, TOTAL_CTRL_FULL)
    # incremental captures (only fires/ctrls NOT already covered by v2_base)
    new_only_fire = (~v2_base(fe_all)) & fe_mask
    new_only_ctrl = (~v2_base(ce_all)) & ce_mask
    return {
        "name": name, "fire_cap": fire_cap, "ctrl_cap": ctrl_cap,
        "fire_pct": fr, "ctrl_pct": cr, "lift": lift, "z": z,
        "inc_fire": int(new_only_fire.sum()), "inc_ctrl": int(new_only_ctrl.sum()),
    }

# === Baseline ===
fe_v2_full = v2_base(fe_all).sum() + fe_v1_captured
ce_v2_full = v2_base(ce_all).sum() + ce_v1_captured

baseline = {
    "name": "V2 baseline (A OR B OR C)",
    "fire_cap": fe_v2_full, "ctrl_cap": ce_v2_full,
    "fire_pct": fe_v2_full/TOTAL_FIRE_FULL, "ctrl_pct": ce_v2_full/TOTAL_CTRL_FULL,
    "lift": (fe_v2_full/TOTAL_FIRE_FULL) / (ce_v2_full/TOTAL_CTRL_FULL),
    "z": wilson_z(fe_v2_full/TOTAL_FIRE_FULL, TOTAL_FIRE_FULL,
                  ce_v2_full/TOTAL_CTRL_FULL, TOTAL_CTRL_FULL),
    "inc_fire": 0, "inc_ctrl": 0,
}

composites = [baseline]

# === Add H11 alone, in various tightness ===
composites.append(eval_composite("V3a: + H11 (buy_vol_60s>50 AND pm_drop_5s>0)",  h11_mask(fe_all), h11_mask(ce_all)))
composites.append(eval_composite("V3b: + H11 stricter (buy_vol_60s>100 AND pm_drop_5s>0.005)",
                                 (fe_all.buy_vol_60s > 100) & (fe_all.pm_drop_5s > 0.005),
                                 (ce_all.buy_vol_60s > 100) & (ce_all.pm_drop_5s > 0.005)))

# === Add H12 utc_hour == 15 ===
composites.append(eval_composite("V3c: + H12 utc_hour == 15",  h12_15(fe_all), h12_15(ce_all)))

# === Add H8 coinbase sret_60s > 0.0005 ===
composites.append(eval_composite("V3d: + H8 coinbase_sret_60s > 0.0005",
                                 h8_cb_strong(fe_all), h8_cb_strong(ce_all)))

# === H11 OR H12 OR H8 combos ===
composites.append(eval_composite("V3e: + H11 OR H8_cb_strong",
                                 h11_mask(fe_all) | h8_cb_strong(fe_all),
                                 h11_mask(ce_all) | h8_cb_strong(ce_all)))
composites.append(eval_composite("V3f: + H11 OR H12_hour15",
                                 h11_mask(fe_all) | h12_15(fe_all),
                                 h11_mask(ce_all) | h12_15(ce_all)))
composites.append(eval_composite("V3g: + H11 OR H12_hour15 OR H8_cb_strong",
                                 h11_mask(fe_all) | h12_15(fe_all) | h8_cb_strong(fe_all),
                                 h11_mask(ce_all) | h12_15(ce_all) | h8_cb_strong(ce_all)))
# Try with OKX too
composites.append(eval_composite("V3h: + H11 OR H8_cb_strong OR H8_okx_strong",
                                 h11_mask(fe_all) | h8_cb_strong(fe_all) | h8_okx_strong(fe_all),
                                 h11_mask(ce_all) | h8_cb_strong(ce_all) | h8_okx_strong(ce_all)))

print("\n=== V3 COMPOSITE COVERAGE (FULL POOL) ===")
print(f"{'rule':<70} {'fire%':>7} {'ctrl%':>7} {'lift':>6} {'z':>6} {'+fire':>6}/{'+ctrl':<5}")
print("-" * 122)
for c in composites:
    print(f"{c['name']:<70} {c['fire_pct']*100:>6.1f}% {c['ctrl_pct']*100:>6.1f}% {c['lift']:>6.2f} {c['z']:>+6.2f} {c['inc_fire']:>6}/{c['inc_ctrl']:<5}")

# === Drill: lift of H11 ALONE on V3-un (the un-explained subset) ===
print("\n=== H11 cross-tab on V3-unexplained set (was already in v6 features) ===")
fe_h11 = h11_mask(fe).fillna(False)
ce_h11 = h11_mask(ce).fillna(False)
print(f"H11 alone fires (V3-un): {fe_h11.sum()}/{len(fe)} = {fe_h11.mean():.3f}")
print(f"H11 alone ctrls (V3-un): {ce_h11.sum()}/{len(ce)} = {ce_h11.mean():.3f}")
print(f"H11 alone lift on V3-un: {fe_h11.mean()/ce_h11.mean():.2f}")

# What does H11 look like in V2-captured? (controls dilution check)
fe_v2_cap = fe_all[v2_base(fe_all)]
ce_v2_cap = ce_all[v2_base(ce_all)]
fe_h11_in_v2 = h11_mask(fe_v2_cap).fillna(False)
ce_h11_in_v2 = h11_mask(ce_v2_cap).fillna(False)
print(f"H11 within V2-captured fires: {fe_h11_in_v2.sum()}/{len(fe_v2_cap)} = {fe_h11_in_v2.mean():.3f}")
print(f"H11 within V2-captured ctrls: {ce_h11_in_v2.sum()}/{len(ce_v2_cap)} = {ce_h11_in_v2.mean():.3f}")

# === LEFTOVER-ON-WINNER for various coverage levels ===
print("\n=== leftover-on-winner check (V3 composite candidates) ===")
from load import load_resolutions
res = load_resolutions()
res_idx = res.set_index("slug")["outcome"].to_dict()
def winrate(d, mask, label):
    d_sub = d[mask].copy()
    d_sub["won"] = (d_sub.outcome.values == d_sub.slug.map(res_idx).values)
    wr = float(d_sub.won.mean())
    return wr, len(d_sub)

# we need to evaluate winrate among DIFFERENT subsets of fe_all (V1-un) — V2-cap, V3-cap-new, V3-leftover
# For each composite, compute residual leftover fires (= V1-un \ (v2 OR new))
for c in composites:
    name = c["name"]
    new_only_fire_mask = None
    # rebuild new_mask: V2 ALREADY captured + this composite's new rule
    if name == "V2 baseline (A OR B OR C)":
        residual_mask = ~v2_base(fe_all)
    elif "V3a" in name:
        residual_mask = ~(v2_base(fe_all) | h11_mask(fe_all))
    elif "V3b" in name:
        residual_mask = ~(v2_base(fe_all) | ((fe_all.buy_vol_60s > 100) & (fe_all.pm_drop_5s > 0.005)))
    elif "V3c" in name:
        residual_mask = ~(v2_base(fe_all) | h12_15(fe_all))
    elif "V3d" in name:
        residual_mask = ~(v2_base(fe_all) | h8_cb_strong(fe_all))
    elif "V3e" in name:
        residual_mask = ~(v2_base(fe_all) | h11_mask(fe_all) | h8_cb_strong(fe_all))
    elif "V3f" in name:
        residual_mask = ~(v2_base(fe_all) | h11_mask(fe_all) | h12_15(fe_all))
    elif "V3g" in name:
        residual_mask = ~(v2_base(fe_all) | h11_mask(fe_all) | h12_15(fe_all) | h8_cb_strong(fe_all))
    elif "V3h" in name:
        residual_mask = ~(v2_base(fe_all) | h11_mask(fe_all) | h8_cb_strong(fe_all) | h8_okx_strong(fe_all))
    else:
        continue
    wr_resid, n_resid = winrate(fe_all, residual_mask, name)
    print(f"  {name[:40]:<40}  residual fires: {n_resid:>3}  winrate: {wr_resid:.3f}")

# === Save composite summary ===
out = {
    "composites": composites,
    "h11_on_v3un": {
        "fire_rate": float(fe_h11.mean()),
        "ctrl_rate": float(ce_h11.mean()),
        "fire_n": int(len(fe)), "ctrl_n": int(len(ce)),
    },
}
with open(CACHE / "v6_composites_summary.json", "w", encoding="utf-8") as f:
    json.dump(out, f, default=float, indent=2)
log(f"saved v6_composites_summary.json")
