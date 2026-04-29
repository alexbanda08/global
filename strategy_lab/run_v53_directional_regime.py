"""
Validation study for the directional regime classifier.

Outputs (printed + JSON):
  1. Regime distribution on BTC 4h (HL data)
  2. Transition matrix
  3. Run-length stats (median run, % bars in <12-bar runs)
  4. Per-regime price metrics (mean ret, vol)
  5. V52 sleeve signals: per-regime trade counts (sanity check that classifier conditions trade behavior)

Run:  python -m strategy_lab.run_v53_directional_regime
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from strategy_lab.util.hl_data import load_hl
from strategy_lab.regime.directional_regime import fit_directional_regime
from strategy_lab.eval.perps_simulator import simulate as sim_canonical, atr as sim_atr
from strategy_lab.run_v30_creative import (
    sig_cci_extreme, sig_supertrend_flip,
)

OUT = REPO / "docs/research/phase5_results"
OUT.mkdir(parents=True, exist_ok=True)


def regime_distribution(regimes: pd.DataFrame) -> dict:
    counts = regimes["label"].value_counts()
    pct = (counts / len(regimes)).to_dict()
    return {k: round(v, 4) for k, v in pct.items()}


def transition_matrix(regimes: pd.DataFrame) -> dict:
    s = regimes["stable_regime"].values
    K = 3
    M = np.zeros((K, K), dtype=int)
    for a, b in zip(s[:-1], s[1:]):
        M[int(a), int(b)] += 1
    rows = M.sum(axis=1, keepdims=True)
    rows[rows == 0] = 1
    P = M / rows
    names = ["Bear", "Sideline", "Bull"]
    return {names[i]: {names[j]: round(float(P[i, j]), 4) for j in range(K)} for i in range(K)}


def run_length_stats(regimes: pd.DataFrame) -> dict:
    s = regimes["stable_regime"].values
    runs = []
    cur = s[0]; n = 1
    for v in s[1:]:
        if v == cur:
            n += 1
        else:
            runs.append((int(cur), n))
            cur = v; n = 1
    runs.append((int(cur), n))
    lens = np.array([r[1] for r in runs])
    short_bars = sum(r[1] for r in runs if r[1] < 12)
    return {
        "n_runs":         int(len(runs)),
        "median_run":     int(np.median(lens)),
        "p25_run":        int(np.percentile(lens, 25)),
        "p75_run":        int(np.percentile(lens, 75)),
        "max_run":        int(lens.max()),
        "pct_bars_in_short_runs": round(short_bars / len(s), 4),
    }


def per_regime_returns(df: pd.DataFrame, regimes: pd.DataFrame) -> dict:
    merged = df.join(regimes[["label"]], how="inner")
    merged["log_r"] = np.log(merged["close"]).diff()
    out = {}
    for lab in ["Bear", "Sideline", "Bull"]:
        m = merged[merged["label"] == lab]
        if len(m) == 0:
            out[lab] = {"n_bars": 0}
            continue
        r = m["log_r"].dropna()
        out[lab] = {
            "n_bars":    int(len(m)),
            "mean_4h_pct":  round(float(r.mean() * 100), 4),
            "vol_4h_pct":   round(float(r.std() * 100), 4),
            "ann_sharpe":   round(float(r.mean() / r.std() * np.sqrt(6 * 365)), 3) if r.std() > 0 else 0.0,
        }
    return out


def per_regime_signal_stats(df: pd.DataFrame, regimes: pd.DataFrame, sig: pd.Series, name: str) -> dict:
    """Count signal firings per regime — first-order check that regimes condition trade frequency."""
    aligned = pd.DataFrame({"sig": sig.astype(bool), "label": regimes["label"]}, index=df.index).dropna()
    out = {"signal": name, "total_fires": int(aligned["sig"].sum())}
    for lab in ["Bear", "Sideline", "Bull"]:
        n_bars = int((aligned["label"] == lab).sum())
        n_fires = int((aligned["sig"] & (aligned["label"] == lab)).sum())
        rate = n_fires / n_bars if n_bars > 0 else 0.0
        out[lab] = {"bars": n_bars, "fires": n_fires, "fires_per_1k_bars": round(rate * 1000, 3)}
    return out


def per_regime_trade_stats(df: pd.DataFrame, regimes: pd.DataFrame,
                            long_sig: pd.Series, name: str,
                            tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60) -> dict:
    """Run canonical sim with this signal, then bucket trades by regime at entry bar."""
    short_sig = pd.Series(False, index=df.index)
    trades, _ = sim_canonical(
        df, long_sig.astype(bool), short_sig,
        tp_atr=tp_atr, sl_atr=sl_atr, trail_atr=trail_atr, max_hold=max_hold,
        risk_per_trade=0.03, leverage_cap=4.0,
    )
    if not trades:
        return {"signal": name, "n_trades": 0}
    # bucket by regime at entry
    per_lab = {"Bear": [], "Sideline": [], "Bull": []}
    for t in trades:
        e = t.get("entry_idx", t.get("entry_bar"))
        if e is None or e >= len(regimes):
            continue
        try:
            lab = regimes["label"].iloc[e]
        except Exception:
            continue
        if lab in per_lab:
            per_lab[lab].append(t.get("ret", t.get("pnl_pct", 0.0)))
    out = {"signal": name, "n_trades": len(trades)}
    for lab, rs in per_lab.items():
        if not rs:
            out[lab] = {"n": 0}
            continue
        a = np.array(rs)
        out[lab] = {
            "n":      int(len(a)),
            "wr":     round(float((a > 0).mean()), 3),
            "avg_r":  round(float(a.mean()), 4),
            "med_r":  round(float(np.median(a)), 4),
        }
    return out


def main():
    print("=" * 70)
    print("V53: Directional Regime Classifier — Validation Study")
    print("=" * 70)

    # 1. Load BTC for global classifier (the regime variable everyone shares)
    print("\n[1] Loading BTC 4h (HL)...")
    btc = load_hl("BTC", "4h")
    print(f"    BTC: {len(btc)} bars  {btc.index[0]} -> {btc.index[-1]}")

    print("\n[2] Fitting directional regime classifier...")
    model, regimes = fit_directional_regime(btc, verbose=True)

    dist = regime_distribution(regimes)
    print(f"\n[3] Regime distribution: {dist}")
    trans = transition_matrix(regimes)
    print(f"\n[4] Transition matrix:")
    for src, row in trans.items():
        print(f"      {src:<9} -> {row}")
    runs = run_length_stats(regimes)
    print(f"\n[5] Run-length stats: {runs}")
    pr_ret = per_regime_returns(btc, regimes)
    print(f"\n[6] Per-regime BTC returns:")
    for lab, m in pr_ret.items():
        print(f"      {lab:<9} : {m}")

    # 7. Per-regime SIGNAL FIRES (cheap first-order check)
    print(f"\n[7] Signal fires by regime (BTC):")
    fires_btc = []
    cci_l, cci_s = sig_cci_extreme(btc)
    fires_btc.append(per_regime_signal_stats(btc, regimes, cci_l, "cci_long_BTC"))
    fires_btc.append(per_regime_signal_stats(btc, regimes, cci_s, "cci_short_BTC"))
    stf_l, stf_s = sig_supertrend_flip(btc)
    fires_btc.append(per_regime_signal_stats(btc, regimes, stf_l, "stf_long_BTC"))
    fires_btc.append(per_regime_signal_stats(btc, regimes, stf_s, "stf_short_BTC"))
    for r in fires_btc:
        print(f"      {r}")

    # 8. Per-regime TRADE STATS on the V52-component coins (using BTC regime as the global label)
    print(f"\n[8] Per-regime trade stats (canonical EXIT_4H sim, BTC regime label):")
    trade_results = []
    for sym in ["ETH", "SOL", "AVAX"]:
        df = load_hl(sym, "4h")
        # align regimes to this symbol's index
        reg_aligned = regimes.reindex(df.index, method="ffill").dropna()
        df = df.loc[reg_aligned.index]
        cl, _ = sig_cci_extreme(df)
        r = per_regime_trade_stats(df, reg_aligned, cl, f"cci_long_{sym}")
        trade_results.append(r)
        print(f"      {r}")
        sl, _ = sig_supertrend_flip(df)
        r = per_regime_trade_stats(df, reg_aligned, sl, f"stf_long_{sym}")
        trade_results.append(r)
        print(f"      {r}")

    # Lightweight gates
    print(f"\n[9] Validation gates:")
    g1 = all(0.10 <= v <= 0.70 for v in dist.values())
    print(f"    Gate A: each regime in [10%,70%] coverage  -> {'PASS' if g1 else 'FAIL'}")
    g2 = runs["pct_bars_in_short_runs"] < 0.05
    print(f"    Gate B: <5% bars in <12-bar runs           -> {'PASS' if g2 else 'FAIL'} ({runs['pct_bars_in_short_runs']*100:.2f}%)")
    # Gate C: at least one signal shows WR delta >10pp across regimes
    deltas = []
    for r in trade_results:
        if r.get("n_trades", 0) < 30:
            continue
        wrs = [r[lab]["wr"] for lab in ["Bear", "Sideline", "Bull"] if r.get(lab, {}).get("n", 0) >= 5]
        if len(wrs) >= 2:
            deltas.append((r["signal"], max(wrs) - min(wrs)))
    g3 = any(d > 0.10 for _, d in deltas)
    print(f"    Gate C: >=1 signal with cross-regime WR delta >10pp -> {'PASS' if g3 else 'FAIL'}")
    for nm, d in deltas:
        print(f"             {nm}: WR delta = {d*100:.1f}pp")

    summary = {
        "btc_first":    str(btc.index[0]),
        "btc_last":     str(btc.index[-1]),
        "btc_bars":     len(btc),
        "distribution": dist,
        "transition":   trans,
        "run_lengths":  runs,
        "per_regime_returns": pr_ret,
        "btc_signal_fires":   fires_btc,
        "trade_stats":  trade_results,
        "gates": {
            "coverage":  g1,
            "persistence": g2,
            "info_content": g3,
        },
    }
    out_path = OUT / "v53_directional_regime_audit.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[10] Wrote: {out_path}")
    print("\nDONE.")


if __name__ == "__main__":
    main()
