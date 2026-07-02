"""CYCLOPS selector — BTC, NATIVE 10Hz L25 + DSR — 2026-06-15
Re-run of cyclops_l25_selector_bt at native 10Hz (subsample_1hz=False, per L25
convention: 1Hz over-fills tight-book moments) to firm up magnitude, + Deflated
Sharpe Ratio (Bailey & Lopez de Prado) on the headline BTC cell.

Selector: fire@120 iff |move120|>=thr (binance 1s) & monotonic-to-120; buy favorite
ask via L25 book-walk at the snapshot NEAREST fire_us (10Hz); HOLD to chainlink.
$1 notional, 0.07 winner-only fee. Window Jun1->Jun15 (fresh). BTC only (ETH dead).
Loads L25 in slug-batches to bound RAM at 10Hz.
Run: C:/Python314/python.exe strategy_lab/directional/cyclops_l25_selector_10hz_dsr_2026_06_15.py
"""
from __future__ import annotations
import sys, io, math
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import numpy as np, pandas as pd
import pyarrow.parquet as pq, pyarrow.compute as pc, pyarrow as pa
from scipy.stats import norm
pd.set_option("display.width", 240); pd.set_option("display.max_columns", 40)
TAG = "CYCLOPS_L25_SELECTOR_10HZ_DSR_2026_06_15"; print(TAG, "OUTPUT START", flush=True)
from load import load_resolutions, load_orderbook_l25_streaming  # noqa

CANON = Path(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
WIN = 300; FIRE_OFF = 120; MONO_TOL = 2.0
WIN_LO = 1780272000; WIN_HI = 1781528400
THRS = [3.0, 5.0, 6.0, 8.0]; CAPS = [0.83, 0.88, 0.90, 1.00]
NOTIONAL = 1.0; FEE_K = 0.07; SNAP_TOL_US = 1_000_000  # 1s
SYMB = "BINANCE_SPOT_BTC_USDT"; BATCH = 350


def pnl_07(won, vw, sh):
    return sh * (1 - vw) * (1 - FEE_K * vw) if won else -sh * vw


def load_kl(sym):
    pf = pq.ParquetFile(CANON / "klines_1s.parquet"); keep = pa.array([sym]); d = {}
    for b in pf.iter_batches(batch_size=200_000, columns=["symbol_id", "time_period_start_us", "price_close"]):
        m = pc.is_in(b.column("symbol_id"), value_set=keep)
        if pc.sum(m).as_py() == 0:
            continue
        bb = b.filter(m).to_pydict()
        for t, c in zip(bb["time_period_start_us"], bb["price_close"]):
            d[t // 1_000_000] = c
    k = np.array(sorted(d), dtype=np.int64)
    return k, np.array([d[x] for x in k], dtype=np.float64)


print("loading klines_1s BTC…", flush=True)
KIDX, KVAL = load_kl(SYMB)
print(f"  btc 1s secs={len(KIDX)} max={pd.to_datetime(KIDX.max(),unit='s')}", flush=True)


def px(sec):
    i = np.searchsorted(KIDX, sec, "right") - 1
    return float(KVAL[i]) if i >= 0 else np.nan


def extreme(ss, upto, side):
    o = px(ss)
    if np.isnan(o):
        return np.nan
    lo = np.searchsorted(KIDX, ss, "left"); hi = np.searchsorted(KIDX, ss + upto, "right")
    seg = KVAL[lo:hi]
    if len(seg) == 0:
        return np.nan
    r = (seg / o - 1) * 1e4
    return r.min() if side == "min" else r.max()


# resolutions BTC 5m
res = load_resolutions(); res.columns = [c.lower() for c in res.columns]
res = res[res["slug"].astype(str).str.contains("btc-updown-5m", na=False)].copy()
res["slot_start"] = pd.to_numeric(res["slug"].astype(str).str.extract(r"-(\d+)\Z")[0], errors="coerce")
res = res.dropna(subset=["slot_start"]); res["slot_start"] = res["slot_start"].astype(int)
res = res[(res.slot_start >= WIN_LO) & (res.slot_start + WIN <= WIN_HI)]
res["truth_up"] = res["outcome"].astype(str).str.lower().map({"up": 1, "down": 0})
res = res.dropna(subset=["truth_up"])
print(f"BTC 5m resolutions in window: {len(res)}", flush=True)


def decode(thr):
    fires = {}
    for _, r in res.iterrows():
        ss = int(r.slot_start); o = px(ss); p = px(ss + FIRE_OFF)
        if np.isnan(o) or np.isnan(p):
            continue
        mv = (p / o - 1) * 1e4
        if abs(mv) < thr:
            continue
        fav = "Up" if mv > 0 else "Down"
        mono = (extreme(ss, FIRE_OFF, "min") > -MONO_TOL) if fav == "Up" else (extreme(ss, FIRE_OFF, "max") < MONO_TOL)
        if mono:
            fires[r.slug] = (ss + FIRE_OFF, fav, int(r.truth_up))
    return fires


def walk(ap, asz, notion):
    spent = sh = 0.0; rem = notion
    for p, s in zip(ap, asz):
        if not (p > 0 and s > 0):
            continue
        c = p * s
        if c >= rem:
            sh += rem / p; spent += rem; rem = 0.0; break
        sh += s; spent += c; rem -= c
    return (spent / sh) if (sh > 0 and rem <= 0) else None


# union of all fired slugs across thresholds (lowest thr = superset), load 10Hz once in batches
fires_by_thr = {thr: decode(thr) for thr in THRS}
all_slugs = sorted(set().union(*[set(f) for f in fires_by_thr.values()]))
print(f"fired slugs (union, thr>={min(THRS):.0f}): {len(all_slugs)} — loading L25 @10Hz in batches of {BATCH}…", flush=True)

# fire snapshot per slug: vwap of favorite ask at row nearest fire_us (10Hz)
snap = {}  # slug -> vwap (favorite side)
fav_of = {s: fires_by_thr[min(THRS)][s][1] for s in all_slugs if s in fires_by_thr[min(THRS)]}
# ensure every slug has a fav (use any thr that contains it)
for s in all_slugs:
    if s not in fav_of:
        for thr in THRS:
            if s in fires_by_thr[thr]:
                fav_of[s] = fires_by_thr[thr][s][1]; break
fire_us = {}
for thr in THRS:
    for s, (fsec, fav, tr) in fires_by_thr[thr].items():
        fire_us[s] = fsec * 1_000_000

for bi in range(0, len(all_slugs), BATCH):
    chunk = set(all_slugs[bi:bi + BATCH])
    books = load_orderbook_l25_streaming("btc", slugs=chunk, subsample_1hz=False,
                                         min_ts_us=WIN_LO * 1_000_000, max_ts_us=WIN_HI * 1_000_000)
    for s in chunk:
        fav = fav_of.get(s);
        if fav is None:
            continue
        key = (s, fav)
        if key not in books:
            continue
        ts, ap, asz, *_ = books[key]
        fu = fire_us[s]
        i = int(np.searchsorted(ts, fu, "right") - 1)
        # nearest row to fu (check i and i+1)
        cand = [j for j in (i, i + 1) if 0 <= j < len(ts)]
        if not cand:
            continue
        j = min(cand, key=lambda x: abs(int(ts[x]) - fu))
        if abs(int(ts[j]) - fu) > SNAP_TOL_US:
            continue
        vw = walk(ap[j], asz[j], NOTIONAL)
        if vw is not None and 0.01 < vw < 0.999:
            snap[s] = vw
    del books
    print(f"  batch {bi//BATCH+1}: cum filled snapshots={len(snap)}", flush=True)


def dsr(pnl, trial_sharpes):
    """Deflated Sharpe Ratio (per-trade, non-annualized). Bailey & Lopez de Prado."""
    x = np.asarray(pnl, float); n = len(x)
    if n < 5 or x.std(ddof=1) == 0:
        return None
    sr = x.mean() / x.std(ddof=1)
    g = (((x - x.mean()) ** 3).mean()) / (x.std() ** 3)        # skew
    k = (((x - x.mean()) ** 4).mean()) / (x.std() ** 4)        # kurtosis (raw)
    ts = np.asarray([t for t in trial_sharpes if np.isfinite(t)], float)
    N = max(len(ts), 2); var_tr = ts.var(ddof=1) if len(ts) > 1 else (sr * 0.5) ** 2
    em = 0.5772156649
    sr0 = math.sqrt(var_tr) * ((1 - em) * norm.ppf(1 - 1.0 / N) + em * norm.ppf(1 - 1.0 / (N * math.e)))
    denom = math.sqrt(max(1e-12, 1 - g * sr + ((k - 1) / 4.0) * sr ** 2))
    z = (sr - sr0) * math.sqrt(n - 1) / denom
    return dict(sr=sr, sr0=sr0, dsr=float(norm.cdf(z)), n=n, skew=g, kurt=k, n_trials=N)


# build per-cell pnl, trial sharpes
cells = {}
for thr in THRS:
    for cap in CAPS:
        pnl = []
        for s, (fsec, fav, tr) in fires_by_thr[thr].items():
            if s not in snap:
                continue
            vw = snap[s]
            if vw > cap:
                continue
            won = (fav == "Up" and tr == 1) or (fav == "Down" and tr == 0)
            pnl.append(pnl_07(won, vw, NOTIONAL / vw))
        if len(pnl) >= 12:
            cells[(thr, cap)] = np.array(pnl)

trial_sh = [c.mean() / c.std(ddof=1) for c in cells.values() if c.std(ddof=1) > 0]
rows = []
for (thr, cap), pnl in cells.items():
    won_rate = (pnl > 0).mean()
    rows.append(dict(thr=thr, cap=cap, n=len(pnl), WR=round(won_rate * 100, 1),
                     dol_tr=round(pnl.mean(), 4),
                     extop2=round(np.sort(pnl)[:-2].mean(), 4),
                     sharpe=round(pnl.mean() / pnl.std(ddof=1), 3) if pnl.std(ddof=1) > 0 else None))
R = pd.DataFrame(rows).sort_values(["thr", "cap"])
print("\n=== BTC selector @10Hz ($1, 0.07 fee, fire@120 monotonic) ===")
print(R.to_string(index=False))

# DSR on headline cells (thr=3 cap=0.88 ; best $/tr)
print("\n=== DSR (n_trials = grid size) ===")
for key in [(3.0, 0.88), (5.0, 1.00), (3.0, 1.00)]:
    if key in cells:
        d = dsr(cells[key], trial_sh)
        if d:
            print(f"thr={key[0]:.0f} cap={key[1]:.2f}: n={d['n']} SR={d['sr']:.4f} SR0={d['sr0']:.4f} "
                  f"DSR={d['dsr']:.3f} skew={d['skew']:.2f} kurt={d['kurt']:.2f} n_trials={d['n_trials']}")
best = R.loc[R.dol_tr.idxmax()]
bk = (best.thr, best.cap)
if bk in cells:
    d = dsr(cells[bk], trial_sh)
    print(f"BEST thr={best.thr:.0f} cap={best.cap:.2f}: $/tr={best.dol_tr:+.4f} ex-top2={best.extop2:+.4f} "
          f"DSR={d['dsr']:.3f} (DSR>0.95 = survives deflation)")

print(f"\nfill rate (filled/union fired): {len(snap)}/{len(all_slugs)} = {len(snap)/max(1,len(all_slugs))*100:.1f}%")
print("vs 1Hz prior: BTC thr3/cap.88 $/tr +0.0179 ex-top2 +0.0139 ; net of ~$0.011 tx ~+0.005-0.007")
print(TAG, "OUTPUT END")
