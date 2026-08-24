"""
R3 — (a) is the negative live shadow consistent with the long-OOS edge?
     (b) do the FUND_Z / ATR_NOTOPVOL gates actually add value?

(a) POWER / CONSISTENCY
    R2 pooled LONG_OOS: n=927, mean +1.048%/tr, WR 32.9%, t=+4.76.
    The live HL paper shadow since 2026-06-11: n=46, mean -0.215%/tr.
    A 33%-WR / +18%-TP / -2.5%-SL payoff is violently skewed, so short blocks are
    noisy. Bootstrap the LONG_OOS trade distribution in blocks of 46 and ask how
    often a block that negative appears. If it is common, the shadow result is
    uninformative and the correct action is to keep collecting, not to kill.
    Reported both iid-bootstrap and a CONTIGUOUS-block bootstrap (preserves regime
    clustering, the honest version).

(b) GATE VALUE — paired A/B on identical entry signals, gate ON vs OFF, on the
    untouched LONG_OOS window. A gate that does not improve the untouched window
    is decoration that was fitted to the selection era.

Outputs: r3_bootstrap.csv, r3_gate_ab.csv
"""
from __future__ import annotations
import sys, glob, importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H
from strategy_lab.regime.hmm_adaptive import fit_regime_model

sys.path.insert(0, str(HERE))
from _r2_long_history import (  # reuse loaders / gates / registry
    load_binance_4h, load_perp_funding_4h, gate_fund_z, gate_atr_notopvol,
    SLEEVES, EXIT_4H, SPLIT, PERP_FUNDING, metrics,
)

RNG = np.random.default_rng(7)
SHADOW_N = 46
SHADOW_MEAN = -0.215


# ------------------------------------------------------------------ (a) power
def bootstrap_block(rets: np.ndarray, block_n: int, n_iter: int = 20000) -> dict:
    """iid bootstrap: mean of `block_n` trades drawn with replacement."""
    idx = RNG.integers(0, len(rets), size=(n_iter, block_n))
    means = rets[idx].mean(axis=1)
    return dict(kind="iid", p_negative=float((means < 0).mean()),
                p_le_shadow=float((means <= SHADOW_MEAN).mean()),
                q05=float(np.quantile(means, 0.05)), q50=float(np.quantile(means, 0.50)),
                q95=float(np.quantile(means, 0.95)))


def bootstrap_contig(rets_ordered: np.ndarray, block_n: int) -> dict:
    """Every contiguous block of `block_n` consecutive trades (regime-preserving)."""
    n = len(rets_ordered)
    if n < block_n:
        return dict(kind="contiguous", p_negative=np.nan, p_le_shadow=np.nan,
                    q05=np.nan, q50=np.nan, q95=np.nan)
    means = np.array([rets_ordered[i:i + block_n].mean() for i in range(n - block_n + 1)])
    return dict(kind="contiguous", p_negative=float((means < 0).mean()),
                p_le_shadow=float((means <= SHADOW_MEAN).mean()),
                q05=float(np.quantile(means, 0.05)), q50=float(np.quantile(means, 0.50)),
                q95=float(np.quantile(means, 0.95)))


def main():
    tr = pd.read_csv(HERE / "r2_trades.csv", parse_dates=["entry_ts"])
    lo = tr[tr.window == "LONG_OOS"].sort_values("entry_ts")
    r = lo["ret_pct"].to_numpy(float)

    print("=" * 96)
    print("(a) IS THE NEGATIVE LIVE SHADOW CONSISTENT WITH THE LONG-OOS EDGE?")
    print("=" * 96)
    print(f"  long-OOS pool : n={len(r)} mean={r.mean():+.3f}% WR={(r>0).mean()*100:.1f}%")
    print(f"  live shadow   : n={SHADOW_N} mean={SHADOW_MEAN:+.3f}%")
    rows = []
    for f in (bootstrap_block, lambda x, n: bootstrap_contig(x, n)):
        d = f(r, SHADOW_N)
        rows.append(d)
        print(f"  [{d['kind']:11s}] blocks of {SHADOW_N}: P(mean<0)={d['p_negative']*100:5.1f}%  "
              f"P(mean<={SHADOW_MEAN})={d['p_le_shadow']*100:5.1f}%  "
              f"5/50/95pct = {d['q05']:+.2f} / {d['q50']:+.2f} / {d['q95']:+.2f} %")
    pd.DataFrame(rows).to_csv(HERE / "r3_bootstrap.csv", index=False)
    p = max(rows[0]["p_le_shadow"], rows[1]["p_le_shadow"])
    print(f"\n  -> a block as bad as the live shadow happens {p*100:.0f}% of the time under the "
          f"long-OOS edge.\n     {'CONSISTENT with a real edge - keep collecting, do not kill.' if p > 0.10 else 'UNUSUAL - the live window is genuinely worse than history.'}")
    print(f"\n  How many trades to resolve a {r.mean():+.2f}%/tr edge at 95% power?")
    sd = r.std(ddof=1)
    n_req = int(np.ceil((1.96 + 1.64) ** 2 * sd ** 2 / r.mean() ** 2))
    print(f"     sd={sd:.2f}% -> n ~= {n_req} trades  (fleet fires ~{len(lo)/ (lo.entry_ts.max()-lo.entry_ts.min()).days*30:.1f}/month "
          f"=> ~{n_req/max(len(lo)/(lo.entry_ts.max()-lo.entry_ts.min()).days*30,0.01):.0f} months)")

    # ------------------------------------------------------------- (b) gate A/B
    print(f"\n{'='*96}\n(b) GATE A/B — paired, identical entries, untouched LONG_OOS window\n{'='*96}")
    data = {c: None for c in {s[1] for s in SLEEVES}}
    for c in data:
        df = load_binance_4h(c)
        data[c] = (df, load_perp_funding_4h(c, df.index))

    ab = []
    for name, coin, sig_fn, params, variant, gate in SLEEVES:
        if gate == "FUND_Z" and coin not in PERP_FUNDING:
            continue  # no funding -> gate cannot be evaluated
        df, fund = data[coin]
        out = sig_fn(df, **params)
        le0, se0 = out if isinstance(out, tuple) else (out, None)
        le0 = le0.reindex(df.index).fillna(False)
        se0 = se0.reindex(df.index).fillna(False) if se0 is not None else pd.Series(False, index=df.index)
        if variant == "V45":
            active = df["volume"] > 1.1 * df["volume"].rolling(20, min_periods=10).mean()
            le0, se0 = le0 & active, se0 & active
        mask = gate_fund_z(fund) if gate == "FUND_Z" else gate_atr_notopvol(df)

        rdf = None
        if variant in ("V41", "V45"):
            _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)

        res = {}
        for arm, (le, se) in {"OFF": (le0, se0), "ON": (le0 & mask, se0 & mask)}.items():
            if rdf is not None:
                trades, _ = simulate_with_funding(df, le, se, fund,
                                                  regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
            else:
                trades, _ = simulate_with_funding(df, le, se, fund, **EXIT_4H)
            sub = pd.DataFrame([dict(entry_ts=df.index[t["entry_idx"]], ret_pct=100 * t["ret"],
                                     realized=t["realized"]) for t in trades])
            sub = sub[sub.entry_ts < SPLIT] if len(sub) else sub
            res[arm] = metrics(sub) if len(sub) else metrics(pd.DataFrame())
        d = dict(sleeve=name, gate=gate,
                 n_off=res["OFF"]["n"], mean_off=res["OFF"]["mean_ret"], tot_off=res["OFF"]["tot"],
                 n_on=res["ON"]["n"], mean_on=res["ON"]["mean_ret"], tot_on=res["ON"]["tot"],
                 delta_mean=res["ON"]["mean_ret"] - res["OFF"]["mean_ret"])
        ab.append(d)
        verdict = "gate HELPS" if d["delta_mean"] > 0.05 else ("gate HURTS" if d["delta_mean"] < -0.05 else "gate ~neutral")
        print(f"  {name:11s} {gate:13s} OFF n={d['n_off']:4.0f} {d['mean_off']:+7.3f}%  ->  "
              f"ON n={d['n_on']:4.0f} {d['mean_on']:+7.3f}%   delta={d['delta_mean']:+7.3f}pp  {verdict}")

    abdf = pd.DataFrame(ab); abdf.to_csv(HERE / "r3_gate_ab.csv", index=False)
    helps = int((abdf.delta_mean > 0.05).sum()); hurts = int((abdf.delta_mean < -0.05).sum())
    print(f"\n  gates evaluated={len(abdf)}  helps={helps}  hurts={hurts}  "
          f"neutral={len(abdf)-helps-hurts}   mean delta={abdf.delta_mean.mean():+.3f}pp")
    print("\n[r3] wrote r3_bootstrap.csv, r3_gate_ab.csv")


if __name__ == "__main__":
    main()
