"""
R2 — LONG-HISTORY VALIDATION of the 9 V52 sleeves on Binance 4h.
================================================================

Motivation
----------
R1 showed the only untouched HL window is POST (2026-04-25 -> today) = 76 trades,
of which the pre-registered live slice (>=2026-06-11) is 46 trades and NEGATIVE.
n=46 cannot settle anything, and the HL API cannot serve history before 2024-03
(probed: EMPTY), so HL alone will never give power.

Binance native 4h klines DO go back years and are clean (0 zero-volume bars):
  BTC/ETH 2017-08, LINK 2019-01, SOL 2020-08, AVAX 2020-09  ->  2026-03/05.

Everything before 2024-03-01 is a window the V52 selection never saw (the audit
used HL 2024-01-12 -> 2026-04-25, and HL data only starts 2024-03 anyway). So:

  LONG_OOS  coin start -> 2024-03-01   fully untouched, thousands of bars
  HL_ERA    2024-03-01 -> data end     same calendar span as the HL selection window

This is a cross-venue robustness test, not a live-fill claim: Binance spot 4h
OHLCV stands in for HL perp price. Funding is REAL Binance perp funding (8h) for
BTC/ETH/SOL; AVAX/LINK have no local perp funding so they run funding=0 and the
FUND_Z gate is skipped for them (recorded in the `gate_applied` column).

If a sleeve's edge is real it should be positive in LONG_OOS. If it is only
positive in HL_ERA it was fitted to that regime.

Outputs: r2_trades.csv, r2_by_window.csv, r2_gate_passrates.csv
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


def _load_mod(rel, name):
    spec = importlib.util.spec_from_file_location(name, str(REPO / rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

_v30 = _load_mod("strategy_lab/run_v30_creative.py", "v30c")
_v29 = _load_mod("strategy_lab/run_v29_regime.py", "v29r")

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
SPLIT = pd.Timestamp("2024-03-01", tz="UTC")

BINANCE_SYM = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT",
               "AVAX": "AVAXUSDT", "LINK": "LINKUSDT"}
PERP_FUNDING = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}  # rest -> 0

SLEEVES = [
    ("STF_BTC",    "BTC",  _v30.sig_supertrend_flip,  dict(st_n=10, st_mult=3.0, ema_reg=200),                       "V45",      "FUND_Z"),
    ("CCI_ETH",    "ETH",  _v30.sig_cci_extreme,      dict(cci_n=20, cci_lo=-150, cci_hi=150, adx_max=22, adx_n=14), "V41",      "FUND_Z"),
    ("STF_SOL",    "SOL",  _v30.sig_supertrend_flip,  dict(st_n=10, st_mult=3.0, ema_reg=200),                       "baseline", "FUND_Z"),
    ("STF_AVAX",   "AVAX", _v30.sig_supertrend_flip,  dict(st_n=10, st_mult=3.0, ema_reg=200),                       "V45",      "FUND_Z"),
    ("LATBB_AVAX", "AVAX", _v29.sig_lateral_bb_fade,  dict(bb_n=20, bb_k=2.0, adx_max=18, adx_n=14),                 "baseline", "FUND_Z"),
    ("MFI_SOL",    "SOL",  sig_mfi_extreme,           dict(lower=25, upper=75),                                      "V41",      "ATR_NOTOPVOL"),
    ("VP_LINK",    "LINK", sig_volume_profile_rot,    dict(win=60, n_bins=15),                                       "baseline", "ATR_NOTOPVOL"),
    ("SVD_AVAX",   "AVAX", sig_signed_vol_div,        dict(lookback=20, cvd_win=50),                                 "baseline", "ATR_NOTOPVOL"),
    ("MFI_ETH",    "ETH",  sig_mfi_extreme,           dict(lower=25, upper=75),                                      "baseline", "ATR_NOTOPVOL"),
]


# ------------------------------------------------------------------ data
def load_binance_4h(coin: str) -> pd.DataFrame:
    sym = BINANCE_SYM[coin]
    fs = sorted(glob.glob(str(REPO / f"data/binance/parquet/{sym}/4h/year=*/part.parquet")))
    d = pd.concat([pd.read_parquet(f) for f in fs]).sort_values("open_time")
    d["timestamp"] = pd.to_datetime(d["open_time"], utc=True)
    d = d.drop_duplicates("timestamp").set_index("timestamp")
    out = d[["open", "high", "low", "close", "volume"]].astype(float)
    return out[~out.index.duplicated()]


def load_perp_funding_4h(coin: str, index: pd.DatetimeIndex) -> pd.Series:
    """Binance perp funding (8h settlements) -> summed into each 4h bar."""
    if coin not in PERP_FUNDING:
        return pd.Series(0.0, index=index)
    p = REPO / f"strategy_lab/autoresearch/_data/binance_vision_deriv/{PERP_FUNDING[coin]}_funding_full.parquet"
    if not p.exists():
        return pd.Series(0.0, index=index)
    f = pd.read_parquet(p)
    ts = pd.to_datetime(f["0"].astype("int64"), unit="ms", utc=True)
    rate = f["2"].astype(float)
    s = pd.Series(rate.values, index=ts).sort_index()
    return s.groupby(s.index.floor("4h")).sum().reindex(index).fillna(0.0)


# ------------------------------------------------------------------ gates
def gate_fund_z(fund_4h: pd.Series, z_thr=2.0) -> pd.Series:
    mu = fund_4h.rolling(500, min_periods=100).mean()
    sd = fund_4h.rolling(500, min_periods=100).std()
    z = (fund_4h - mu) / sd.replace(0, np.nan)
    return (z.abs() < z_thr).fillna(True)


def gate_atr_notopvol(df, atr_n=14, high_q=0.80) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_n).mean()
    return (atr.rolling(500, min_periods=100).rank(pct=True) < high_q).fillna(True)


def metrics(sub: pd.DataFrame) -> dict:
    if len(sub) == 0:
        return dict(n=0, mean_ret=np.nan, wr=np.nan, tot=0.0, t=np.nan, ex_top2=0.0)
    r = sub["ret_pct"].to_numpy(float); p = sub["realized"].to_numpy(float)
    o = np.sort(p)[::-1]
    t = (r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 and r.std(ddof=1) > 0 else np.nan
    return dict(n=len(sub), mean_ret=r.mean(), wr=100.0 * (r > 0).mean(),
                tot=p.sum(), t=t, ex_top2=p.sum() - o[:2].sum())


def main():
    data = {}
    for coin in BINANCE_SYM:
        df = load_binance_4h(coin)
        data[coin] = (df, load_perp_funding_4h(coin, df.index))
        fnd = "perp" if coin in PERP_FUNDING else "ZERO"
        print(f"[r2] {coin:5s} bars={len(df):6d} {df.index.min():%Y-%m-%d} -> {df.index.max():%Y-%m-%d} funding={fnd}")

    rows, gates = [], []
    for name, coin, sig_fn, params, variant, gate in SLEEVES:
        df, fund = data[coin]
        out = sig_fn(df, **params)
        le, se = out if isinstance(out, tuple) else (out, None)
        le = le.reindex(df.index).fillna(False)
        se = se.reindex(df.index).fillna(False) if se is not None else pd.Series(False, index=df.index)
        if variant == "V45":
            active = df["volume"] > 1.1 * df["volume"].rolling(20, min_periods=10).mean()
            le, se = le & active, se & active

        raw_fires = int(le.sum() + se.sum())
        if gate == "FUND_Z" and coin in PERP_FUNDING:
            m = gate_fund_z(fund); applied = "FUND_Z"
        elif gate == "ATR_NOTOPVOL":
            m = gate_atr_notopvol(df); applied = "ATR_NOTOPVOL"
        else:
            m = pd.Series(True, index=df.index); applied = "NONE(no perp funding)"
        le, se = (le & m).fillna(False), (se & m).fillna(False)
        gated_fires = int(le.sum() + se.sum())
        gates.append(dict(sleeve=name, gate_spec=gate, gate_applied=applied,
                          bar_pass_rate=round(100.0 * m.mean(), 2),
                          fires_raw=raw_fires, fires_gated=gated_fires,
                          fires_killed_pct=round(100.0 * (1 - gated_fires / max(raw_fires, 1)), 2)))

        if variant in ("V41", "V45"):
            _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
            trades, _ = simulate_with_funding(df, le, se, fund,
                                              regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
        else:
            trades, _ = simulate_with_funding(df, le, se, fund, **EXIT_4H)

        for t in trades:
            ets = df.index[t["entry_idx"]]
            rows.append(dict(sleeve=name, coin=coin, variant=variant, gate_applied=applied,
                             entry_ts=ets, window="LONG_OOS" if ets < SPLIT else "HL_ERA",
                             side="LONG" if t["side"] > 0 else "SHORT",
                             ret_pct=100.0 * t["ret"], realized=t["realized"],
                             reason=t["reason"], bars=t["bars"]))
        print(f"  {name:11s} {coin:5s} {variant:8s} gate={applied:22s} fires {raw_fires}->{gated_fires} trades={len(trades)}")

    tr = pd.DataFrame(rows)
    tr.to_csv(HERE / "r2_trades.csv", index=False)
    gp = pd.DataFrame(gates); gp.to_csv(HERE / "r2_gate_passrates.csv", index=False)

    print(f"\n{'='*100}\nGATE REALITY CHECK — how much does each gate actually filter?\n{'='*100}")
    print(gp.to_string(index=False))

    out = []
    for name in [s[0] for s in SLEEVES]:
        for w in ("LONG_OOS", "HL_ERA"):
            out.append(dict(sleeve=name, window=w, **metrics(tr[(tr.sleeve == name) & (tr.window == w)])))
    bw = pd.DataFrame(out); bw.to_csv(HERE / "r2_by_window.csv", index=False)

    print(f"\n{'='*112}\nPER SLEEVE — LONG_OOS (untouched, pre-2024-03) vs HL_ERA (the selection era)\n{'='*112}")
    print(f"{'sleeve':12s} | {'n':>5s} {'mean%':>8s} {'WR%':>6s} {'t':>6s} {'tot$':>10s} {'ex-top2$':>10s} | "
          f"{'n':>5s} {'mean%':>8s} {'WR%':>6s} {'t':>6s} {'tot$':>10s} | verdict")
    print("-" * 112)
    tally = {}
    for name in [s[0] for s in SLEEVES]:
        a = bw[(bw.sleeve == name) & (bw.window == "LONG_OOS")].iloc[0]
        b = bw[(bw.sleeve == name) & (bw.window == "HL_ERA")].iloc[0]
        if a["n"] < 20:
            v = "THIN"
        elif a["mean_ret"] > 0 and a["t"] > 1.0:
            v = "HOLDS long-OOS"
        elif a["mean_ret"] > 0:
            v = "weak-positive"
        else:
            v = "FAILS long-OOS"
        tally[name] = v
        print(f"{name:12s} | {a['n']:5.0f} {a['mean_ret']:+8.3f} {a['wr']:6.1f} {a['t']:+6.2f} "
              f"{a['tot']:+10.1f} {a['ex_top2']:+10.1f} | "
              f"{b['n']:5.0f} {b['mean_ret']:+8.3f} {b['wr']:6.1f} {b['t']:+6.2f} {b['tot']:+10.1f} | {v}")

    print(f"\ntally: " + ", ".join(f"{v}={sum(1 for x in tally.values() if x == v)}" for v in sorted(set(tally.values()))))

    print(f"\n{'='*100}\nPOOLED\n{'='*100}")
    for w in ("LONG_OOS", "HL_ERA"):
        m = metrics(tr[tr.window == w])
        print(f"  {w:9s} n={m['n']:5d} mean={m['mean_ret']:+7.3f}% WR={m['wr']:5.1f}% "
              f"t={m['t']:+5.2f} tot=${m['tot']:+11.1f} ex-top2=${m['ex_top2']:+11.1f}")

    print(f"\n{'='*100}\nEXIT REASON MIX\n{'='*100}")
    for w in ("LONG_OOS", "HL_ERA"):
        s = tr[tr.window == w]
        g = s.groupby("reason").agg(n=("ret_pct", "size"), mean=("ret_pct", "mean"), tot=("realized", "sum"))
        print(f"  {w:9s} " + " | ".join(f"{k}: n={int(v['n'])} mean={v['mean']:+.2f}% ${v['tot']:+.0f}"
                                        for k, v in g.iterrows()))
    print("\n[r2] wrote r2_trades.csv, r2_by_window.csv, r2_gate_passrates.csv")


if __name__ == "__main__":
    main()
