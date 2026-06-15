"""ETH 5m l_ema50_hurst_grandparent v8 vs v10 — RERUN on current canonical + correct fee + DSR.

Sleeve (v8, prod): ETH 5m BOTH, offset 60, gates =
  g_tr_above_ema50      : close vs ema_50, direction-aligned
  g_hurst_trending      : hurst_60 (R/S on 60s 1s-logret) > 0.50  (direction-independent)
  g_grandparent_trend_with : 15m trend_slope_30m 4-bar mean (1h) sign == direction
V10 = v8 + g_sms_no_liquidity_above : NOT near 20-bar liquidity in trade direction.

Fires/fill/outcome: dirscan_eth_5m (offset_s==60) — real L25 walk (u_vwap/d_vwap) + outcome_truth.
Window: dirscan coverage (~Apr24 -> Jun1).  Fee: 0.07 winner-only curve, flat $5 stake.
Fidelity anchor: study reported v8 WR~82%, MaxDD -$25, Calmar 17.3; v10 Calmar 23.7 (legacy fee, in-sample).

Run: C:/Python314/python.exe strategy_lab/directional/eth5m_v8_v10_rerun_2026_06_08.py
"""
from __future__ import annotations
import os, sys, datetime as dt
import numpy as np
import pandas as pd

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
sys.path.insert(0, os.path.join(ROOT, "data", "v4", "canonical"))
RES = os.path.join(ROOT, r"data\v4\canonical\_results")
KL1S = os.path.join(ROOT, r"data\v4\canonical\klines_1s.parquet")

HURST_THR = 0.50
HURST_WIN = 60          # 60 one-second log-returns
EMA50_TF = "5m"         # ema_50 on 5m closes (documented assumption)
LIQ_LB = 20             # 20-bar rolling high/low (5m grid)
LIQ_TOL = 0.001         # within 0.1% of the 20-bar extreme = liquidity present
STAKE = 5.0
FEE = 0.07


def hurst_rs(x, min_chunk=8):
    n = len(x)
    if n < min_chunk * 2:
        return np.nan
    y = x - x.mean(); Z = np.cumsum(y); R = Z.max() - Z.min(); S = x.std(ddof=0)
    if S == 0:
        return np.nan
    rs_full = R / S
    mid = n // 2

    def _rs(z):
        m = z.mean(); yy = np.cumsum(z - m); s = z.std(ddof=0)
        return (yy.max() - yy.min()) / s if s > 0 else np.nan
    rs_half = np.nanmean([_rs(x[:mid]), _rs(x[mid:])])
    if not np.isfinite(rs_half) or rs_half <= 0:
        return np.nan
    return float(np.log(rs_full / rs_half) / np.log(2.0))


def pnl_07(won, vwap):
    sh = STAKE / vwap
    return sh * (1 - vwap) * (1 - FEE * vwap) if won else -sh * vwap


def metrics(df):
    if len(df) == 0:
        return dict(n=0)
    d = df.sort_values("fire_us")
    pnl = d["pnl"].to_numpy()
    cum = np.cumsum(pnl); peak = np.maximum.accumulate(cum); mdd = float((cum - peak).min())
    day = (d["fire_us"].to_numpy() // 86_400_000_000)
    ud, idx = np.unique(day, return_inverse=True)
    byday = np.bincount(idx, weights=pnl)
    sharpe = (byday.mean() / byday.std() * np.sqrt(365)) if (len(byday) > 1 and byday.std() > 0) else 0.0
    return dict(n=len(d), wr=float(d["won"].mean()), dpt=float(pnl.mean()),
                total=float(pnl.sum()), mdd=mdd,
                calmar=float(pnl.sum() / abs(mdd)) if mdd < 0 else float("inf"),
                sharpe=sharpe, days=len(ud), byday=byday)


def dsr(byday, n_trials):
    """Deflated Sharpe via ml4t (daily returns)."""
    try:
        from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio
        return float(deflated_sharpe_ratio(pd.Series(byday), sr_benchmark=0.0, n_trials=max(1, n_trials)))
    except Exception as e:
        return f"ml4t_err:{str(e)[:40]}"


# ---------- 1. fires + fill + outcome from dirscan ----------
ds = pd.read_parquet(os.path.join(RES, "dirscan_eth_5m.parquet"))
ds = ds[ds["offset_s"] == 60].copy()
print("dirscan offset60 rows:", len(ds), "outcome_truth sample:", ds["outcome_truth"].dropna().unique()[:5])
print("cols:", [c for c in ds.columns])
ds = ds.dropna(subset=["fire_us", "outcome_truth"])
lo, hi = int(ds["fire_us"].min()), int(ds["fire_us"].max())
print("window:", dt.datetime.utcfromtimestamp(lo/1e6), "->", dt.datetime.utcfromtimestamp(hi/1e6))

# ---------- 2. ETH 1s klines for the window ----------
import pyarrow.parquet as pq
import pyarrow.dataset as pads
WLO = lo - 4 * 3600 * 1_000_000   # 4h warmup
flt = (
    (pads.field("symbol_id") == "BINANCE_SPOT_ETH_USDT")
    & (pads.field("period_id") == "1SEC")
    & (pads.field("time_period_start_us") >= WLO)
    & (pads.field("time_period_start_us") <= hi)
)
k = pads.dataset(KL1S).to_table(
    columns=["time_period_start_us", "price_high", "price_low", "price_close"], filter=flt
).to_pandas()
if len(k) == 0:  # symbol naming fallback
    syms = pads.dataset(KL1S).to_table(columns=["symbol_id"]).to_pandas()["symbol_id"].unique()
    eth = [s for s in syms if "ETH" in str(s)][:3]
    print("ETH symbol candidates:", eth)
    flt = ((pads.field("symbol_id").isin(eth)) & (pads.field("period_id") == "1SEC")
           & (pads.field("time_period_start_us") >= WLO) & (pads.field("time_period_start_us") <= hi))
    k = pads.dataset(KL1S).to_table(
        columns=["time_period_start_us", "price_high", "price_low", "price_close"], filter=flt).to_pandas()
k = k.rename(columns={"time_period_start_us": "ts", "price_high": "high",
                      "price_low": "low", "price_close": "close"}).sort_values("ts").reset_index(drop=True)
print(f"ETH 1s rows: {len(k)}  {dt.datetime.utcfromtimestamp(k['ts'].min()/1e6)} -> {dt.datetime.utcfromtimestamp(k['ts'].max()/1e6)}")
k["dt"] = pd.to_datetime(k["ts"], unit="us", utc=True)
ks = k.set_index("dt")

# ---------- 3. bar features ----------
def bars(freq):
    o = ks["close"].resample(freq, label="left", closed="left").last()
    h = ks["high"].resample(freq, label="left", closed="left").max()
    lo_ = ks["low"].resample(freq, label="left", closed="left").min()
    b = pd.concat([o, h, lo_], axis=1); b.columns = ["close", "high", "low"]
    b = b.dropna(subset=["close"]).reset_index()
    b["start_us"] = (b["dt"].astype("int64") // 1000)
    return b

b5 = bars("5min")
b5["ema50"] = b5["close"].ewm(span=50, adjust=False).mean()
b5["rh20"] = b5["high"].rolling(LIQ_LB, min_periods=LIQ_LB).max()
b5["rl20"] = b5["low"].rolling(LIQ_LB, min_periods=LIQ_LB).min()
b5["liquidity_up"] = ((b5["high"] - b5["rh20"]).abs() / b5["rh20"] < LIQ_TOL)
b5["liquidity_dn"] = ((b5["low"] - b5["rl20"]).abs() / b5["rl20"] < LIQ_TOL)
b5["end_us"] = b5["start_us"] + 300 * 1_000_000   # bar end (causal join key)

# grandparent: 1m close -> rolling 30min linreg slope -> sample at 15m -> 4-bar(15m) mean sign
b1 = bars("1min")
import numpy as _np
xidx = _np.arange(30, dtype=float)
def _slope(arr):
    if _np.isnan(arr).any():
        return _np.nan
    return _np.polyfit(xidx, arr, 1)[0]
b1["slope30"] = b1["close"].rolling(30, min_periods=30).apply(_slope, raw=True)
b15 = bars("15min")
b15["end_us"] = b15["start_us"] + 900 * 1_000_000
# asof 1m slope at each 15m bar end
b15 = pd.merge_asof(b15.sort_values("end_us"),
                    b1[["start_us", "slope30"]].rename(columns={"start_us": "k"}).sort_values("k"),
                    left_on="end_us", right_on="k", direction="backward")
b15["gp_slope"] = b15["slope30"].rolling(4, min_periods=4).mean()  # 1h smoothing

# ---------- 4. per-fire features (causal asof) ----------
f = ds[["slug", "fire_us", "outcome_truth", "u_vwap", "u_ok", "d_vwap", "d_ok"]].copy().sort_values("fire_us").reset_index(drop=True)
f = pd.merge_asof(f, b5[["end_us", "close", "ema50", "liquidity_up", "liquidity_dn"]].sort_values("end_us"),
                  left_on="fire_us", right_on="end_us", direction="backward")
f = pd.merge_asof(f, b15[["end_us", "gp_slope"]].rename(columns={"end_us": "e15"}).sort_values("e15"),
                  left_on="fire_us", right_on="e15", direction="backward")

# hurst_60 from 1s logret, last 60s before fire
kc = k["close"].to_numpy(); kt = k["ts"].to_numpy()
logret = _np.diff(_np.log(kc), prepend=_np.log(kc[0]))
import bisect
hur = _np.full(len(f), _np.nan)
for i, fu in enumerate(f["fire_us"].to_numpy()):
    hi_i = bisect.bisect_right(kt, fu)            # exclusive of fire
    lo_i = bisect.bisect_left(kt, fu - HURST_WIN * 1_000_000)
    seg = logret[lo_i:hi_i]
    if len(seg) >= 30:
        hur[i] = hurst_rs(seg[-HURST_WIN:])
f["hurst60"] = hur

# ---------- 5. gates + direction + fill + pnl ----------
f = f.dropna(subset=["close", "ema50", "gp_slope", "hurst60"]).reset_index(drop=True)
f["dir"] = _np.where(f["close"] > f["ema50"], "Up", "Down")    # ema50 gate defines fireable dir
gp_sign = _np.sign(f["gp_slope"])
f["g_ema50"] = True                                            # dir is defined to satisfy it
f["g_hurst"] = f["hurst60"] > HURST_THR
f["g_grand"] = ((f["dir"] == "Up") & (gp_sign > 0)) | ((f["dir"] == "Down") & (gp_sign < 0))
f["g_sms"] = _np.where(f["dir"] == "Up", ~f["liquidity_up"].astype(bool), ~f["liquidity_dn"].astype(bool))
# fill in the chosen dir
f["vwap"] = _np.where(f["dir"] == "Up", f["u_vwap"], f["d_vwap"])
f["ok"] = _np.where(f["dir"] == "Up", f["u_ok"], f["d_ok"]).astype(bool)
f["won"] = (f["dir"] == f["outcome_truth"])
f = f[f["ok"] & f["vwap"].notna() & (f["vwap"] > 0.001) & (f["vwap"] < 0.999)].reset_index(drop=True)
f["pnl"] = [pnl_07(w, v) for w, v in zip(f["won"], f["vwap"])]

v8 = f[f["g_hurst"] & f["g_grand"]].copy()
v10 = v8[v8["g_sms"]].copy()


def show(name, d, n_trials):
    m = metrics(d)
    if m["n"] == 0:
        print(f"{name}: 0 fires"); return
    ds_ = dsr(m["byday"], n_trials)
    print(f"{name:6s} n={m['n']:5d} WR={m['wr']*100:5.1f}% $/tr={m['dpt']:+6.3f} "
          f"total=${m['total']:+8.1f} MaxDD=${m['mdd']:7.1f} Calmar={m['calmar']:6.2f} "
          f"Sharpe={m['sharpe']:5.2f} days={m['days']} DSR={ds_}")


print("\n==== ETH 5m l_ema50_hurst_grandparent — RERUN (0.07 fee, $5, dirscan fills) ====")
print(f"window {dt.datetime.utcfromtimestamp(lo/1e6):%Y-%m-%d} -> {dt.datetime.utcfromtimestamp(hi/1e6):%Y-%m-%d}, fillable fires={len(f)}")
show("v8", v8, n_trials=300)     # ~ the v8 GA search breadth
show("v10", v10, n_trials=200)   # v8 + sms
print(f"\nv10 vs v8 delta: n {len(v8)}->{len(v10)} ({len(v10)/max(1,len(v8))*100:.0f}% kept)")
mv8, mv10 = metrics(v8), metrics(v10)
if mv8["n"] and mv10["n"]:
    print(f"  $/tr {mv8['dpt']:+.3f} -> {mv10['dpt']:+.3f}   total ${mv8['total']:+.1f} -> ${mv10['total']:+.1f}   "
          f"MaxDD ${mv8['mdd']:.1f} -> ${mv10['mdd']:.1f}   Calmar {mv8['calmar']:.2f} -> {mv10['calmar']:.2f}")

# fidelity check on the original GA window Apr24->May26
orig_hi = int(dt.datetime(2026, 5, 26, tzinfo=dt.timezone.utc).timestamp() * 1e6)
v8o = v8[v8["fire_us"] <= orig_hi]
print(f"\n[fidelity vs study Apr24->May26] v8: ", metrics(v8o).get("wr"), "WR  (study reported ~0.82)")
out = os.path.join(RES, "_eth5m_v8_v10_rerun_2026_06_08.parquet")
f.to_parquet(out)
print("saved per-fire ->", out)

