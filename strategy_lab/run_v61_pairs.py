"""
V61: Pairs / spread strategy on HL data.

Tested pairs:
  - ETH/BTC ratio z-score reversion
  - SOL/AVAX ratio z-score reversion
  - SOL/ETH (third pair, same family for cross-validation)

For each pair, sweep (z_win, z_in, z_exit) on a small grid; pick best by
Calmar; report headline + correlation with V52.

Promotion bar (sleeve-level):
  Sharpe >= 0.6 AND |rho_with_V52| < 0.20 AND n_trades >= 30

If 1+ pairs promote, run blend (0.92*V52 + 0.08*invvol(pairs)) and gates.
"""
from __future__ import annotations
import json, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

from strategy_lab.util.hl_data import load_hl
from strategy_lab.strategies.pairs_zscore import simulate_pair
from strategy_lab.run_v52_hl_gates import build_v52_hl
from strategy_lab.run_leverage_audit import invvol_blend, verdict_8gate

OUT = REPO / "docs/research/phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6

PAIRS = [
    ("ETHBTC", "ETH", "BTC"),
    ("SOLAVAX", "SOL", "AVAX"),
    ("SOLETH", "SOL", "ETH"),
]

GRID = [
    # (z_win, z_in, z_exit, z_stop, max_hold)
    (60,  1.5, 0.25, 4.0, 60),
    (60,  2.0, 0.50, 4.0, 60),
    (100, 1.5, 0.25, 4.0, 120),
    (100, 2.0, 0.50, 4.0, 120),
    (100, 2.5, 0.50, 4.0, 120),
    (200, 2.0, 0.50, 4.0, 240),
    (200, 2.5, 0.50, 4.0, 240),
]


def headline(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    sd = float(r.std())
    if sd == 0:
        return {"sharpe": 0, "cagr_pct": 0, "mdd_pct": 0, "calmar": 0}
    sh = (float(r.mean()) / sd) * np.sqrt(BPY)
    pk = eq.cummax(); mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = cagr / abs(mdd) if mdd != 0 else 0
    return {"sharpe": round(sh, 3), "cagr_pct": round(float(cagr) * 100, 2),
            "mdd_pct": round(mdd * 100, 2), "calmar": round(float(cal), 3)}


def main():
    t0 = time.time()
    print("=" * 72)
    print("V61: Pairs / Spread (z-score mean-reversion)")
    print("=" * 72)

    print("\n[1] Loading HL 4h data...")
    dfs = {sym: load_hl(sym, "4h") for sym in ["BTC", "ETH", "SOL", "AVAX"]}
    for sym, df in dfs.items():
        print(f"   {sym}: {len(df)} bars  {df.index[0]} -> {df.index[-1]}")

    print("\n[2] Building V52 reference...")
    v52_eq = build_v52_hl()
    h52 = headline(v52_eq)
    print(f"   V52: {h52}")

    pair_results = []
    for pair_name, sym_a, sym_b in PAIRS:
        print(f"\n[3] Pair: {pair_name} ({sym_a}/{sym_b}) sweep...")
        df_a, df_b = dfs[sym_a], dfs[sym_b]
        best = None
        for params in GRID:
            zw, zi, zx, zs, mh = params
            trades, eq, diag = simulate_pair(df_a, df_b,
                z_win=zw, z_in=zi, z_exit=zx, z_stop=zs, max_hold=mh,
                risk_per_trade=0.03)
            h = headline(eq)
            row = {"pair": pair_name, "params": params, **h, "n_trades": diag["n_trades"],
                   "wr": round(diag["wr"], 3), "avg_held": round(diag["avg_held"], 1)}
            if best is None or h["calmar"] > best["calmar"]:
                best = {**row, "_eq": eq}
            print(f"   z_win={zw} z_in={zi} z_x={zx} mh={mh}  n={diag['n_trades']:>3}  "
                  f"Sh={h['sharpe']:>5.2f}  Cal={h['calmar']:>5.2f}  WR={diag['wr']:.2f}")
        # rho with V52
        common = v52_eq.index.intersection(best["_eq"].index)
        v52_r = v52_eq.reindex(common).pct_change().fillna(0)
        p_r = best["_eq"].reindex(common).pct_change().fillna(0)
        rho = float(p_r.corr(v52_r)) if p_r.std() > 0 else 0.0
        best["rho_v52"] = round(rho, 3)
        print(f"   BEST {pair_name}: params={best['params']}  "
              f"Sh={best['sharpe']:.2f}  Cal={best['calmar']:.2f}  "
              f"MDD={best['mdd_pct']:.2f}%  rho(V52)={rho:+.3f}  n_trades={best['n_trades']}")
        pair_results.append(best)

    # Promotion check
    PROMO_SH = 0.6
    PROMO_RHO = 0.20
    PROMO_N = 30
    promoted = [p for p in pair_results
                if p["sharpe"] >= PROMO_SH
                and abs(p["rho_v52"]) < PROMO_RHO
                and p["n_trades"] >= PROMO_N]
    print(f"\n[4] Promoted pairs (Sh>={PROMO_SH}, |rho|<{PROMO_RHO}, n>={PROMO_N}): {len(promoted)}/{len(pair_results)}")
    for p in promoted:
        print(f"     {p['pair']}: Sh={p['sharpe']:.2f}  Cal={p['calmar']:.2f}  rho={p['rho_v52']:+.3f}")

    blend_summary = None
    if promoted:
        print(f"\n[5] Blending V52 + invvol(promoted pairs)...")
        # Use 92/08 first (matches V58 best)
        sleeves = {p["pair"]: p["_eq"] for p in promoted}
        common_pairs = list(sleeves.values())[0].index
        for eq in sleeves.values():
            common_pairs = common_pairs.intersection(eq.index)
        invvol_pairs = invvol_blend(
            {k: eq.reindex(common_pairs) for k, eq in sleeves.items()}, window=500
        )
        blends = []
        for w_v52, w_p in [(0.95, 0.05), (0.92, 0.08), (0.90, 0.10), (0.85, 0.15)]:
            common = v52_eq.index.intersection(invvol_pairs.index)
            v52_r = v52_eq.reindex(common).pct_change().fillna(0)
            p_r = invvol_pairs.reindex(common).pct_change().fillna(0)
            blend_r = w_v52 * v52_r + w_p * p_r
            blend_eq = (1 + blend_r).cumprod() * 10_000.0
            h = headline(blend_eq)
            gates = verdict_8gate(blend_eq)
            sh_lci = float(gates["gates"]["bootstrap_sharpe_lowerCI_gt_0.5"]["value"])
            cal_lci = float(gates["gates"]["bootstrap_calmar_lowerCI_gt_1.0"]["value"])
            mdd_wci = float(gates["gates"]["bootstrap_mdd_worstCI_gt_neg30pct"]["value"])
            wf_eff = float(gates["gates"]["walk_forward_efficiency_gt_0.5"]["value"])
            row = {"weights": [w_v52, w_p], **h,
                   "sharpe_lowerCI": round(sh_lci, 3),
                   "calmar_lowerCI": round(cal_lci, 3),
                   "mdd_worstCI": round(mdd_wci, 3),
                   "wf_efficiency": round(wf_eff, 3),
                   "gates_passed_1_6": sum(1 for g in gates["gates"].values() if g["pass"] is True)}
            blends.append(row)
            d_sh = h["sharpe"] - h52["sharpe"]
            d_cal = h["calmar"] - h52["calmar"]
            d_mdd = h["mdd_pct"] - h52["mdd_pct"]
            cross = " *** CROSSES ***" if cal_lci > 0.987 else ""
            print(f"   {w_v52:.2f}/{w_p:.2f}:  Sh={h['sharpe']:.3f}(d={d_sh:+.3f})  "
                  f"Cal={h['calmar']:.2f}(d={d_cal:+.2f})  MDD={h['mdd_pct']:.2f}%(d={d_mdd:+.2f})  "
                  f"Sh_lci={sh_lci:.3f}  Cal_lci={cal_lci:.3f}{cross}")
        blend_summary = blends

    summary = {
        "v52_baseline": h52,
        "pair_results": [{k: v for k, v in p.items() if k != "_eq"} for p in pair_results],
        "promoted": [p["pair"] for p in promoted],
        "blends": blend_summary,
    }
    out = OUT / "v61_pairs.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote: {out}")
    print(f"Total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
