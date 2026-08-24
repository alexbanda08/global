"""
R4 — SIGNAL FAMILY x COIN UNIVERSE on the untouched window.
===========================================================

Why
---
R3 produced the decisive operational fact: the 9-sleeve V52 fleet fires ~12 trades/
month, and with sd=6.7%/trade around a +1.05% mean it needs ~530 trades (~45 months)
to prove itself. The fleet cannot be validated in any useful timeframe. The bottleneck
is BREADTH, not the signal.

So instead of judging 9 hand-picked (signal, coin) pairs — which is exactly the kind
of cherry-pick that produces the IS/OOS gap seen in R1 — this tests each SIGNAL FAMILY
pooled across the whole coin universe. One hypothesis per family (6 tests, Bonferroni
|t| > 2.64 for family-wise 0.05), and the headline robustness stat is BREADTH: the
fraction of coins where the family is positive. A family that only works on the one
coin it was discovered on is an artifact.

Uniform, deliberately unfitted setup:
  - static EXIT_4H for every cell (no per-cell tuning, no regime model)
  - ATR_NOTOPVOL applied uniformly (helped 3/4 sleeves in R3; FUND_Z needs perp
    funding we only hold for BTC/ETH/SOL, so it is excluded here)
  - windows: LONG_OOS (< 2024-03-01, untouched) and HL_ERA (>= 2024-03-01, verify)

Outputs: r4_cells.csv, r4_families.csv, r4_portfolio.csv
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

sys.path.insert(0, str(HERE))
from _r2_long_history import gate_atr_notopvol, EXIT_4H, SPLIT


def _load_mod(rel, name):
    spec = importlib.util.spec_from_file_location(name, str(REPO / rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

_v30 = _load_mod("strategy_lab/run_v30_creative.py", "v30c")
_v29 = _load_mod("strategy_lab/run_v29_regime.py", "v29r")

# 10 coins with real pre-2024-03 history (TON excluded: 0 bars pre-split)
COINS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "ADA", "BNB", "DOGE", "XRP", "SUI"]
SYM = {c: c + "USDT" for c in COINS}

FAMILIES = {
    "STF":   (_v30.sig_supertrend_flip, dict(st_n=10, st_mult=3.0, ema_reg=200)),
    "CCI":   (_v30.sig_cci_extreme,     dict(cci_n=20, cci_lo=-150, cci_hi=150, adx_max=22, adx_n=14)),
    "LATBB": (_v29.sig_lateral_bb_fade, dict(bb_n=20, bb_k=2.0, adx_max=18, adx_n=14)),
    "MFI":   (sig_mfi_extreme,          dict(lower=25, upper=75)),
    "VP":    (sig_volume_profile_rot,   dict(win=60, n_bins=15)),
    "SVD":   (sig_signed_vol_div,       dict(lookback=20, cvd_win=50)),
}
BONF_T = 2.64  # two-sided 0.05 / 6 families


def load_4h(coin: str) -> pd.DataFrame:
    fs = sorted(glob.glob(str(REPO / f"data/binance/parquet/{SYM[coin]}/4h/year=*/part.parquet")))
    d = pd.concat([pd.read_parquet(f) for f in fs]).sort_values("open_time")
    d["timestamp"] = pd.to_datetime(d["open_time"], utc=True)
    d = d.drop_duplicates("timestamp").set_index("timestamp")
    return d[["open", "high", "low", "close", "volume"]].astype(float)


def stats(r: np.ndarray, p: np.ndarray) -> dict:
    if len(r) == 0:
        return dict(n=0, mean=np.nan, wr=np.nan, t=np.nan, tot=0.0, ex_top2=0.0)
    o = np.sort(p)[::-1]
    t = (r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 and r.std(ddof=1) > 0 else np.nan
    return dict(n=len(r), mean=r.mean(), wr=100 * (r > 0).mean(), t=t,
                tot=p.sum(), ex_top2=p.sum() - o[:2].sum())


def main():
    data = {}
    for c in COINS:
        df = load_4h(c)
        data[c] = (df, pd.Series(0.0, index=df.index), gate_atr_notopvol(df))

    rows = []
    for fam, (fn, params) in FAMILIES.items():
        for c in COINS:
            df, fund, gmask = data[c]
            try:
                out = fn(df, **params)
            except Exception as e:
                print(f"  !! {fam}/{c}: {type(e).__name__}: {e}")
                continue
            le, se = out if isinstance(out, tuple) else (out, None)
            le = le.reindex(df.index).fillna(False) & gmask
            se = (se.reindex(df.index).fillna(False) & gmask) if se is not None \
                else pd.Series(False, index=df.index)
            trades, _ = simulate_with_funding(df, le, se, fund, **EXIT_4H)
            for t in trades:
                ets = df.index[t["entry_idx"]]
                rows.append(dict(family=fam, coin=c, entry_ts=ets,
                                 window="LONG_OOS" if ets < SPLIT else "HL_ERA",
                                 ret_pct=100 * t["ret"], realized=t["realized"], reason=t["reason"]))
        n_lo = sum(1 for r in rows if r["family"] == fam and r["window"] == "LONG_OOS")
        print(f"[r4] {fam:6s} long-OOS trades across {len(COINS)} coins: {n_lo}")

    tr = pd.DataFrame(rows)
    tr.to_csv(HERE / "r4_cells.csv", index=False)

    # ---------------- per-family pooled, with breadth
    print(f"\n{'='*112}")
    print("FAMILY VERDICT — pooled across the coin universe, untouched window (Bonferroni |t|>2.64 for 6 families)")
    print(f"{'='*112}")
    print(f"{'family':7s} | {'n':>5s} {'mean%':>8s} {'WR%':>6s} {'t':>6s} {'tot$':>11s} {'ex-top2$':>11s} "
          f"{'breadth':>9s} | {'HL_ERA n':>8s} {'mean%':>8s} {'t':>6s} | verdict")
    print("-" * 112)
    fam_rows = []
    for fam in FAMILIES:
        lo = tr[(tr.family == fam) & (tr.window == "LONG_OOS")]
        he = tr[(tr.family == fam) & (tr.window == "HL_ERA")]
        a = stats(lo.ret_pct.to_numpy(float), lo.realized.to_numpy(float))
        b = stats(he.ret_pct.to_numpy(float), he.realized.to_numpy(float))
        per_coin = lo.groupby("coin").ret_pct.mean()
        breadth = f"{int((per_coin>0).sum())}/{len(per_coin)}"
        pos_frac = (per_coin > 0).mean() if len(per_coin) else 0
        if a["n"] < 50:
            v = "THIN"
        elif a["t"] > BONF_T and pos_frac >= 0.7 and a["ex_top2"] > 0:
            v = "PASSES (Bonf + breadth)"
        elif a["t"] > 1.96 and pos_frac >= 0.6:
            v = "nominal only"
        elif a["mean"] > 0:
            v = "weak"
        else:
            v = "FAILS"
        fam_rows.append(dict(family=fam, breadth=breadth, verdict=v,
                             **{f"lo_{k}": val for k, val in a.items()},
                             **{f"he_{k}": val for k, val in b.items()}))
        print(f"{fam:7s} | {a['n']:5d} {a['mean']:+8.3f} {a['wr']:6.1f} {a['t']:+6.2f} {a['tot']:+11.1f} "
              f"{a['ex_top2']:+11.1f} {breadth:>9s} | {b['n']:8d} {b['mean']:+8.3f} {b['t']:+6.2f} | {v}")
    fdf = pd.DataFrame(fam_rows); fdf.to_csv(HERE / "r4_families.csv", index=False)

    # ---------------- per-coin detail for the passing families
    keep = [r["family"] for r in fam_rows if r["verdict"].startswith("PASSES")]
    if keep:
        print(f"\n{'='*100}\nPER-COIN DETAIL for passing families {keep}\n{'='*100}")
        lo = tr[(tr.family.isin(keep)) & (tr.window == "LONG_OOS")]
        pv = lo.pivot_table(index="coin", columns="family", values="ret_pct", aggfunc="mean").round(3)
        cnt = lo.pivot_table(index="coin", columns="family", values="ret_pct", aggfunc="size")
        print("mean ret% per (coin, family):"); print(pv.to_string())
        print("\nn trades per (coin, family):"); print(cnt.to_string())

    # ---------------- candidate portfolio = every coin x passing family
    print(f"\n{'='*100}\nCANDIDATE BREADTH PORTFOLIO (all coins x passing families, no cherry-picking)\n{'='*100}")
    port = tr[tr.family.isin(keep)] if keep else tr.iloc[0:0]
    prows = []
    for w in ("LONG_OOS", "HL_ERA"):
        s = port[port.window == w]
        if not len(s):
            continue
        st = stats(s.ret_pct.to_numpy(float), s.realized.to_numpy(float))
        days = max((s.entry_ts.max() - s.entry_ts.min()).days, 1)
        rate = len(s) / days * 30.0
        sd = s.ret_pct.std(ddof=1)
        n_req = int(np.ceil((1.96 + 1.64) ** 2 * sd ** 2 / st["mean"] ** 2)) if st["mean"] > 0 else -1
        prows.append(dict(window=w, **st, trades_per_month=round(rate, 1),
                          n_required=n_req, months_to_power=round(n_req / rate, 1) if n_req > 0 else -1))
        print(f"  {w:9s} n={st['n']:5d} mean={st['mean']:+7.3f}% WR={st['wr']:5.1f}% t={st['t']:+5.2f} "
              f"ex-top2=${st['ex_top2']:+10.1f} | rate={rate:5.1f} tr/mo  "
              f"n_req={n_req}  -> {n_req/rate if n_req>0 else -1:.1f} months to 95% power")
    pd.DataFrame(prows).to_csv(HERE / "r4_portfolio.csv", index=False)
    print("\n  (compare: current 9-sleeve V52 fleet = ~11.8 tr/mo, ~45 months to power)")
    print("\n[r4] wrote r4_cells.csv, r4_families.csv, r4_portfolio.csv")


if __name__ == "__main__":
    main()
