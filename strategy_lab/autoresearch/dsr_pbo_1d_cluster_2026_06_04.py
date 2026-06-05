"""
HANDOFF_2026_06_04 §D-4 — DSR + PBO the mega-sweep 1d-trend MA cluster.

The sweep stored only scalar Sharpes. Here we reconstruct the EXACT survivor positions
(reusing vbt_mega_sweep.gen_single + the same combine semantics), recompute the OOS
per-bar fee-adjusted return series, then judge with:
  - Deflated Sharpe (ml4t) at effective_trials = n_strat searched per series (~400k) -> the honest
    multiple-testing correction. Pooled 4.8M variant also reported.
  - PBO via CSCV (8 blocks, C(8,4)=70 IS/OOS combos) over the reconstructed cluster -> rank stability.

Verdict question: does ANY 1d MA-cluster survivor beat its own multiple-testing null? If yes -> a
standalone Binance/HL daily strategy (then ml4t/backtest). If no -> noise, same as everything else.
"""
import sys, json, itertools, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")

import vbt_mega_sweep as S   # gen_single, sharpe, FEE
from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import (
    deflated_sharpe_ratio, deflated_sharpe_ratio_from_statistics)
from ml4t.diagnostic.evaluation.stats.backtest_overfitting import compute_pbo

FEE = S.FEE
DATA = r"strategy_lab\autoresearch\_data\binance_vision"
RES = json.load(open(r"strategy_lab\autoresearch\_data\vbt_mega_results.json"))
SERIES = {r["label"]: r for r in RES if r["label"].endswith("_1d")}  # BTCUSDT_1d etc.
print("1d series in results:", list(SERIES))

def combine(a, b, mode):
    if mode == "and":  return np.where(a == b, a, 0).astype(np.int8)
    if mode == "gate": return np.where(a != 0, b, 0).astype(np.int8)
    return np.where(a == b, a, np.where(a == 0, b, np.where(b == 0, a, 0))).astype(np.int8)  # or

def reconstruct(label, singles):
    """Rebuild a survivor position array from its label using the sweep's combine rules."""
    if "&" in label:                       # 3-way agree
        parts = label.split("&")
        if len(parts) != 3 or any(p not in singles for p in parts): return None
        a, b, c = (singles[p] for p in parts)
        return np.where((a == b) & (b == c), a, 0).astype(np.int8)
    if "|" in label:                       # a|b|mode
        a, b, mode = label.split("|")
        if a not in singles or b not in singles: return None
        return combine(singles[a], singles[b], mode)
    return singles.get(label)

def oos_series(pos, lr, cut2):
    """Fee-adjusted per-bar return series on the OOS window (matches sweep.sharpe math)."""
    pos = np.nan_to_num(pos, nan=0.0).astype(float)
    r = pos[:-1] * lr - FEE * np.abs(np.diff(pos, prepend=pos[0]))[:-1]
    return r[cut2:]                        # lr has len n-1; OOS slice mirrors lr_oos=lr[cut2:]

def win_sharpe(pos, lr, a, b, ann):
    """Annualized Sharpe on bar window [a,b) — for CSCV/verify (matches S.sharpe)."""
    return S.sharpe(pos[a:b], lr[a:b - 1] if b - 1 <= len(lr) else lr[a:], ann)[0]

ALL = []
for ser, rec in SERIES.items():
    path = f"{DATA}\\{ser.replace('_1d','')}_1d_full.parquet"
    df = pd.read_parquet(path)
    ts = pd.to_datetime(df.open_time, unit="ms")
    d = df.assign(ts=ts).sort_values("ts").drop_duplicates("ts")
    o, h, l, c, v = (pd.to_numeric(d[x], errors="coerce").values.astype(float)
                     for x in ["open", "high", "low", "close", "volume"])
    n = len(c); cut1 = int(n * 0.50); cut2 = int(n * 0.75); lr = np.diff(np.log(c)); ann = 365.0
    singles = {}
    for lbl, pos in S.gen_single(o, h, l, c, v):
        if pos is not None and len(pos) == n:
            singles[lbl] = np.sign(np.nan_to_num(pos, nan=0.0)).astype(np.int8)
    n_strat = int(rec["n_strat"]); null95 = rec["null_p95"]
    print(f"\n===== {ser}  n={n} OOS_bars={n-cut2} n_strat={n_strat:,} null_p95(ann)={null95} =====")
    # reconstruct top survivors
    recon = []
    for row in rec["top"]:
        lbl, IS, ntr, VAL, OSH = row
        pos = reconstruct(lbl, singles)
        if pos is None: continue
        ros = oos_series(pos, lr, cut2)
        if len(ros) < 30 or ros.std() == 0: continue
        sh_ann_chk = ros.mean() / ros.std() * np.sqrt(ann)
        recon.append((lbl, pos, IS, VAL, OSH, ros, sh_ann_chk))
    print(f"reconstructed {len(recon)}/{len(rec['top'])} survivors (OSH_json vs OSH_recon):")
    periodic = [r[5].mean() / r[5].std() for r in recon]   # non-annualized OOS Sharpe
    vt = float(np.var(periodic)) if len(periodic) > 2 else 0.04
    for lbl, pos, IS, VAL, OSH, ros, chk in recon[:8]:
        print(f"  {lbl[:60]:60s} OSH_json={OSH:+.2f} recon={chk:+.2f}")
    # DSR per survivor (effective_trials = per-series n_strat)
    print(f"-- DSR (effective_trials = {n_strat:,}; pooled 4.8M in last col) --")
    surv_pass = 0
    hdr = f"{'strategy':52s} {'annSh':>6} {'DSR_p(series)':>13} {'sig':>4} {'DSR_p(pool4.8M)':>15}"
    print(hdr)
    for lbl, pos, IS, VAL, OSH, ros, chk in recon:
        try:
            psh = ros.mean() / ros.std()   # periodic Sharpe
            d1 = deflated_sharpe_ratio_from_statistics(
                observed_sharpe=psh, n_samples=len(ros), n_trials=n_strat,
                variance_trials=vt, frequency="daily", periods_per_year=365)
            d2 = deflated_sharpe_ratio_from_statistics(
                observed_sharpe=psh, n_samples=len(ros), n_trials=4_802_841,
                variance_trials=vt, frequency="daily", periods_per_year=365)
            sig = d1.is_significant
            surv_pass += int(sig)
            print(f"{lbl[:52]:52s} {chk:+6.2f} {d1.probability:13.3f} {str(sig):>4} {d2.probability:15.3f}")
        except Exception as e:
            print(f"{lbl[:52]:52s}  DSR err {type(e).__name__}: {e}")
    print(f">> {ser}: {surv_pass}/{len(recon)} survive DSR at series multiple-testing.")

    # PBO via CSCV over reconstructed cluster
    if len(recon) >= 2:
        B = 8
        edges = np.linspace(0, len(lr), B + 1).astype(int)
        blocks = [np.arange(edges[i], edges[i + 1]) for i in range(B)]
        posmat = [r[1] for r in recon]
        is_perf, oos_perf = [], []
        for combo in itertools.combinations(range(B), B // 2):
            is_idx = np.concatenate([blocks[i] for i in combo])
            oos_idx = np.concatenate([blocks[i] for i in range(B) if i not in combo])
            ir, orr = [], []
            for pos in posmat:
                posf = np.nan_to_num(pos, nan=0.0).astype(float)
                rr = posf[:-1] * lr - FEE * np.abs(np.diff(posf, prepend=posf[0]))[:-1]
                ii = is_idx[is_idx < len(rr)]; oo = oos_idx[oos_idx < len(rr)]
                ir.append(rr[ii].mean() / rr[ii].std() if rr[ii].std() > 0 else 0.0)
                orr.append(rr[oo].mean() / rr[oo].std() if rr[oo].std() > 0 else 0.0)
            is_perf.append(ir); oos_perf.append(orr)
        pbo = compute_pbo(np.array(is_perf), np.array(oos_perf))
        print(f">> {ser}: PBO (CSCV {len(is_perf)} combos x {len(posmat)} strats) = {pbo.pbo:.3f}")
        ALL.append((ser, surv_pass, len(recon), pbo.pbo))

print("\n================ SUMMARY ================")
for ser, sp, nr, pbo in ALL:
    print(f"{ser:12s} DSR_survivors={sp}/{nr}  PBO={pbo:.3f}")
print("READ: DSR_survivors=0 everywhere => 1d cluster is multiple-testing noise (same as everything else).")
print("      Any DSR_survivors>0 with PBO<0.5 => candidate standalone daily strategy worth ml4t/backtest.")
