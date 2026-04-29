"""
V24 — 15-minute scalping suite.

Four signal families, all L+S, targeting intraday edge on 15m bars:

  1. ORB         — Opening Range Breakout. First N bars after 00:00 UTC define
                    the session range; break above/below with volume filter.
  2. VWAP_BAND   — Intraday VWAP ± k·std deviations. Fade extremes in
                    low-vol/range regime, momentum in trend regime.
  3. RSI_BB      — RSI extremes at Bollinger tails. Short top, long bottom,
                    with regime SMA gate.
  4. ST_DUAL     — Dual Supertrend confluence. Two STs (fast + slow) must
                    align for entry; exit on fast flip.

Execution: same simulator as v22/v23 (0.045% fee, 3 bps slippage, 3× cap).
Walk-forward OOS done in a follow-up script.
"""
from __future__ import annotations
import sys, pickle, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd
import talib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics, atr, ema, supertrend

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v24"
OUT.mkdir(parents=True, exist_ok=True)
FEE = 0.00045

# 15m = 4 bars per hour, 96 bars per day
BARS_PER_DAY_15M = 96
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
         "DOGEUSDT", "INJUSDT", "SUIUSDT", "TONUSDT"]


SINCE = pd.Timestamp("2020-01-01", tz="UTC")  # trim early data: fee regimes changed


def _load(sym, tf="15m"):
    p = FEAT / f"{sym}_{tf}.parquet"
    if not p.exists(): return None
    df = pd.read_parquet(p).dropna(subset=["open","high","low","close","volume"])
    return df[df.index >= SINCE]


def dedupe(s): return s & ~s.shift(1).fillna(False)


# ---------- Signal 1: ORB (Opening Range Breakout) ----------
def sig_orb(df: pd.DataFrame, open_bars: int = 4, vol_mult: float = 1.3,
            session_anchor_hour: int = 0):
    """First `open_bars` 15m bars after the session anchor (00:00 UTC default)
    define today's opening range. A breakout above/below that range with
    volume > vol_mult × rolling(20) average is the signal. Active only during
    the session day (next 00:00 resets)."""
    idx = df.index
    day_key = idx.floor("D")  # UTC day
    # Position of each bar within its UTC day (0..95 for 15m)
    bar_in_day = ((idx - day_key).total_seconds() // (15 * 60)).astype(int)

    # For each day, compute the highest high / lowest low of first `open_bars`.
    # groupby day, mark the open-range high/low, then forward-fill to the
    # rest of that day.
    dfw = df.copy()
    dfw["day"] = day_key
    dfw["bar"] = bar_in_day
    open_mask = dfw["bar"] < open_bars
    or_hi = dfw.loc[open_mask].groupby("day")["high"].max()
    or_lo = dfw.loc[open_mask].groupby("day")["low"].min()
    dfw["or_hi"] = dfw["day"].map(or_hi)
    dfw["or_lo"] = dfw["day"].map(or_lo)

    vol_avg = df["volume"].rolling(20).mean()
    vol_ok = df["volume"] > vol_mult * vol_avg

    # After open_bars, break above/below OR with volume
    active = dfw["bar"] >= open_bars
    long_sig = (df["close"] > dfw["or_hi"]) & (df["close"].shift(1) <= dfw["or_hi"]) & active & vol_ok
    short_sig = (df["close"] < dfw["or_lo"]) & (df["close"].shift(1) >= dfw["or_lo"]) & active & vol_ok
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ---------- Signal 2: VWAP band ----------
def sig_vwap_band(df: pd.DataFrame, band_n: int = 20, band_k: float = 2.0,
                   mode: str = "revert"):
    """Rolling VWAP ± k·std. `mode`='revert' fades the bands; 'break' rides
    breakouts."""
    pv = (df["close"] * df["volume"]).rolling(band_n).sum()
    vv = df["volume"].rolling(band_n).sum()
    vwap = pv / vv
    diff = df["close"] - vwap
    dev = diff.rolling(band_n).std()
    upper = vwap + band_k * dev
    lower = vwap - band_k * dev
    if mode == "revert":
        # Fade: short when close crosses above upper; long when below lower
        long_sig = (df["close"] < lower) & (df["close"].shift(1) >= lower.shift(1))
        short_sig = (df["close"] > upper) & (df["close"].shift(1) <= upper.shift(1))
    else:
        long_sig = (df["close"] > upper) & (df["close"].shift(1) <= upper.shift(1))
        short_sig = (df["close"] < lower) & (df["close"].shift(1) >= lower.shift(1))
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ---------- Signal 3: RSI + Bollinger ----------
def sig_rsi_bb(df: pd.DataFrame, rsi_n: int = 14, rsi_lo: float = 25,
                rsi_hi: float = 75, bb_n: int = 40, bb_k: float = 2.0,
                regime_len: int = 400):
    """Contrarian extreme: long when RSI<rsi_lo AND close<BB_lower;
    short when RSI>rsi_hi AND close>BB_upper. Gated by SMA regime."""
    rsi = talib.RSI(df["close"].values, rsi_n)
    m = df["close"].rolling(bb_n).mean()
    s = df["close"].rolling(bb_n).std()
    ub = m + bb_k * s; lb = m - bb_k * s
    reg_sma = df["close"].rolling(regime_len).mean()
    regime_up = df["close"] > reg_sma
    regime_dn = df["close"] < reg_sma
    long_sig = (pd.Series(rsi, index=df.index) < rsi_lo) & (df["close"] < lb) & regime_up
    short_sig = (pd.Series(rsi, index=df.index) > rsi_hi) & (df["close"] > ub) & regime_dn
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ---------- Signal 4: Dual Supertrend ----------
def sig_st_dual(df: pd.DataFrame, n_fast: int = 10, m_fast: float = 2.0,
                 n_slow: int = 20, m_slow: float = 4.0):
    st_fast = supertrend(df, n_fast, m_fast)
    st_slow = supertrend(df, n_slow, m_slow)
    st_f = pd.Series(st_fast, index=df.index)
    st_s = pd.Series(st_slow, index=df.index)
    # Entry when fast flips aligned with slow
    long_sig = (st_f == 1) & (st_f.shift(1) == -1) & (st_s == 1)
    short_sig = (st_f == -1) & (st_f.shift(1) == 1) & (st_s == -1)
    return long_sig.fillna(False).astype(bool), short_sig.fillna(False).astype(bool)


# ---------- Sweep ----------

def run_one(df, lsig, ssig, tp, sl, tr, mh, risk, lev, lbl):
    ls = dedupe(lsig); ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades), trades, eq


def sweep_family(sym: str, family: str):
    """Sweep one family on 15m only. Return best config."""
    df = _load(sym, "15m")
    if df is None or len(df) < 5000: return None
    best = None

    # Exit grids tuned for 15m scalp (tighter + shorter hold)
    exit_grids = [
        (4, 1.5, 2.5, 32),   # 8h max hold
        (6, 2.0, 3.5, 64),   # 16h max hold
    ]
    risks = [0.03, 0.05]

    if family == "ORB":
        for open_bars in [4, 8]:
            for vol_mult in [1.0, 1.4]:
                try:
                    lsig, ssig = sig_orb(df, open_bars, vol_mult)
                except Exception: continue
                for risk in risks:
                    for (tp, sl, tr, mh) in exit_grids:
                        r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                 f"{sym}_15m_ORB")
                        if r["n"] < 30 or r["dd"] < -0.45: continue
                        score = r["cagr_net"] * (r["sharpe"] / 1.5)
                        if best is None or score > best["score"]:
                            best = dict(sym=sym, family="ORB_15m", tf="15m",
                                        params=dict(open_bars=open_bars, vol_mult=vol_mult),
                                        exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                        risk=risk, lev=3.0, metrics=r, trades=trades,
                                        eq=eq, score=score)

    elif family == "VWAP":
        for band_n in [40, 80]:
            for band_k in [1.8, 2.2]:
                for mode in ["revert", "break"]:
                    try:
                        lsig, ssig = sig_vwap_band(df, band_n, band_k, mode)
                    except Exception: continue
                    for risk in risks:
                        for (tp, sl, tr, mh) in exit_grids:
                            r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                     f"{sym}_15m_VWAP")
                            if r["n"] < 30 or r["dd"] < -0.45: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(sym=sym, family=f"VWAP_{mode}_15m", tf="15m",
                                            params=dict(band_n=band_n, band_k=band_k, mode=mode),
                                            exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                            risk=risk, lev=3.0, metrics=r, trades=trades,
                                            eq=eq, score=score)

    elif family == "RSIBB":
        for rsi_n in [14]:
            for (rsi_lo, rsi_hi) in [(25, 75), (30, 70)]:
                for bb_n in [40, 80]:
                    for bb_k in [2.0]:
                        for regime_len in [400, 800]:
                            try:
                                lsig, ssig = sig_rsi_bb(df, rsi_n, rsi_lo, rsi_hi,
                                                         bb_n, bb_k, regime_len)
                            except Exception: continue
                            for risk in risks:
                                for (tp, sl, tr, mh) in exit_grids:
                                    r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                             f"{sym}_15m_RSIBB")
                                    if r["n"] < 30 or r["dd"] < -0.45: continue
                                    score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                    if best is None or score > best["score"]:
                                        best = dict(sym=sym, family="RSIBB_15m", tf="15m",
                                                    params=dict(rsi_n=rsi_n, rsi_lo=rsi_lo,
                                                                 rsi_hi=rsi_hi, bb_n=bb_n,
                                                                 bb_k=bb_k, regime_len=regime_len),
                                                    exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                    risk=risk, lev=3.0, metrics=r, trades=trades,
                                                    eq=eq, score=score)

    elif family == "STDUAL":
        for n_fast in [10, 14]:
            for m_fast in [2.0]:
                for n_slow in [30, 50]:
                    for m_slow in [3.0, 4.0]:
                        try:
                            lsig, ssig = sig_st_dual(df, n_fast, m_fast, n_slow, m_slow)
                        except Exception: continue
                        for risk in risks:
                            for (tp, sl, tr, mh) in exit_grids:
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                         f"{sym}_15m_STDUAL")
                                if r["n"] < 30 or r["dd"] < -0.45: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="STDUAL_15m", tf="15m",
                                                params=dict(n_fast=n_fast, m_fast=m_fast,
                                                             n_slow=n_slow, m_slow=m_slow),
                                                exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                risk=risk, lev=3.0, metrics=r, trades=trades,
                                                eq=eq, score=score)
    return best


def _persist(results, path):
    light = {}
    for sym, w in results.items():
        light[sym] = {
            "sym": sym, "family": w["family"], "tf": w["tf"],
            "params": w["params"], "exits": w["exits"],
            "risk": w["risk"], "lev": w["lev"],
            "metrics": w["metrics"],
            "trades": w["trades"],
            "eq_index": list(w["eq"].index.astype("int64").tolist()),
            "eq_values": w["eq"].values.tolist(),
        }
    with open(path, "wb") as f:
        pickle.dump(light, f)


def main():
    results = {}
    ckpt = OUT / "v24_15m_results.pkl"
    for sym in COINS:
        print(f"\n=== {sym} (15m scalp) ===", flush=True)
        candidates = []
        for fam in ["ORB", "VWAP", "RSIBB", "STDUAL"]:
            try:
                b = sweep_family(sym, fam)
            except Exception as e:
                print(f"  {fam} FAIL: {e}")
                continue
            if b is None:
                print(f"  {fam:6s}  (no viable config)")
                continue
            candidates.append(b)
            m = b["metrics"]
            print(f"  {fam:6s}  CAGR {m['cagr_net']*100:6.1f}%  Sh {m['sharpe']:+.2f}  "
                  f"DD {m['dd']*100:+6.1f}%  n={m['n']:4d}  p={b['params']}", flush=True)
        if not candidates:
            print("  NO VIABLE 15m CONFIG")
            continue
        winner = max(candidates, key=lambda c: c["score"])
        results[sym] = winner
        m = winner["metrics"]
        print(f"  → {winner['family']}  CAGR {m['cagr_net']*100:.1f}%  Sh {m['sharpe']:.2f}", flush=True)
        # Checkpoint after each coin so a timeout still leaves usable data
        _persist(results, ckpt)

    # Final persist
    _persist(results, ckpt)

    flat = [{"sym": s, "family": w["family"], "tf": w["tf"],
             "params": str(w["params"]), "exits": str(w["exits"]),
             "risk": w["risk"],
             **{k: v for k, v in w["metrics"].items() if k != "label"}}
            for s, w in results.items()]
    pd.DataFrame(flat).to_csv(OUT / "v24_15m_summary.csv", index=False)

    print("\n" + "=" * 80)
    print("V24 15m SCALP — per-coin winners")
    print("=" * 80)
    print(pd.DataFrame(flat).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
