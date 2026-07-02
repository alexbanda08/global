"""CYCLOPS selector L25 $-backtest — does the decoded SELECTOR rescue the edge? 2026-06-15
Decoded selector (last-5d regime): fire when, by mid-window (offset 120s), Binance
has moved >= THR bps in one direction AND the path was MONOTONIC (no opposite
excursion > 2bps); buy that favorite at offset 120; HOLD to resolution.
Contrast vs the LOOSE trigger (first |ret|>=THR at any offset) used before.

Real entry via L25 book-walk ($1, 1Hz), 0.07 winner-only fee, chainlink truth.
Window Jun 1 -> Jun 15 (fresh). BTC + ETH 5m.
Run: C:/Python314/python.exe strategy_lab/directional/cyclops_l25_selector_bt_2026_06_15.py
"""
from __future__ import annotations
import sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import numpy as np, pandas as pd
import pyarrow.parquet as pq, pyarrow.compute as pc, pyarrow as pa
pd.set_option("display.width", 240); pd.set_option("display.max_columns", 40)
TAG = "CYCLOPS_L25_SELECTOR_BT_2026_06_15"; print(TAG, "OUTPUT START", flush=True)
from load import load_resolutions, load_orderbook_l25_streaming  # noqa

CANON = Path(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
WIN = 300; FIRE_OFF = 120; MONO_TOL = 2.0
WIN_LO = 1780272000; WIN_HI = 1781528400
THRS = [3.0, 5.0, 6.0, 8.0]
CAPS = [0.83, 0.88, 0.90, 1.00]
NOTIONAL = 1.0; FEE_K = 0.07
SYM = {"btc": "BINANCE_SPOT_BTC_USDT", "eth": "BINANCE_SPOT_ETH_USDT"}


def pnl_07(won, vwap, shares):
    return shares * (1 - vwap) * (1 - FEE_K * vwap) if won else -shares * vwap


def load_kl(symbols):
    pf = pq.ParquetFile(CANON / "klines_1s.parquet"); keep = pa.array(symbols)
    secs = {s: {} for s in symbols}
    for batch in pf.iter_batches(batch_size=200_000, columns=["symbol_id", "time_period_start_us", "price_close"]):
        m = pc.is_in(batch.column("symbol_id"), value_set=keep)
        if pc.sum(m).as_py() == 0:
            continue
        b = batch.filter(m).to_pydict()
        for sym, t, c in zip(b["symbol_id"], b["time_period_start_us"], b["price_close"]):
            secs[sym][t // 1_000_000] = c
    out = {}
    for sym in symbols:
        d = secs[sym]; k = np.array(sorted(d), dtype=np.int64)
        out[sym] = (k, np.array([d[x] for x in k], dtype=np.float64))
    return out


print("loading klines_1s…", flush=True)
KL = load_kl(list(SYM.values()))


def px(arr, sec):
    idx, vals = arr; i = np.searchsorted(idx, sec, side="right") - 1
    return float(vals[i]) if i >= 0 else np.nan


def path_extreme(arr, ss, upto, side):
    """min/max bps excursion from open over [ss, ss+upto] (1s)."""
    idx, vals = arr; o = px(arr, ss)
    if np.isnan(o):
        return np.nan
    lo = np.searchsorted(idx, ss, "left"); hi = np.searchsorted(idx, ss + upto, "right")
    seg = vals[lo:hi]
    if len(seg) == 0:
        return np.nan
    rets = (seg / o - 1) * 1e4
    return rets.min() if side == "min" else rets.max()


res = load_resolutions(); res.columns = [c.lower() for c in res.columns]
res = res[res["slug"].astype(str).str.contains("updown-5m", na=False)].copy()
res["asset"] = res["slug"].astype(str).str.extract(r"^([a-z0-9]+)-updown")[0]
res = res[res["asset"].isin(["btc", "eth"])].copy()
res["slot_start"] = pd.to_numeric(res["slug"].astype(str).str.extract(r"-(\d+)\Z")[0], errors="coerce")
res = res.dropna(subset=["slot_start"]); res["slot_start"] = res["slot_start"].astype(int)
res = res[(res.slot_start >= WIN_LO) & (res.slot_start + WIN <= WIN_HI)]
res["truth_up"] = res["outcome"].astype(str).str.lower().map({"up": 1, "down": 0})
res = res.dropna(subset=["truth_up"])


def walk_ask(ap, asz, notional):
    spent = sh = 0.0; remain = notional
    for p, s in zip(ap, asz):
        if not (p > 0 and s > 0):
            continue
        c = p * s
        if c >= remain:
            sh += remain / p; spent += remain; remain = 0.0; break
        sh += s; spent += c; remain -= c
    return (spent / sh) if (sh > 0 and remain <= 0) else None


def decode_selector(asset, thr):
    """fire at offset 120 iff |move120|>=thr AND monotonic to 120."""
    sub = res[res.asset == asset]; arr = KL[SYM[asset]]; fires = {}
    for _, r in sub.iterrows():
        ss = int(r.slot_start); o = px(arr, ss); p120 = px(arr, ss + FIRE_OFF)
        if np.isnan(o) or np.isnan(p120):
            continue
        mv = (p120 / o - 1) * 1e4
        if abs(mv) < thr:
            continue
        fav = "Up" if mv > 0 else "Down"
        if fav == "Up":
            mono = path_extreme(arr, ss, FIRE_OFF, "min") > -MONO_TOL
        else:
            mono = path_extreme(arr, ss, FIRE_OFF, "max") < MONO_TOL
        if not mono:
            continue
        fires[r.slug] = (ss + FIRE_OFF, fav, int(r.truth_up))
    return fires


rows_out = []
for asset in ("btc", "eth"):
    for thr in THRS:
        fires = decode_selector(asset, thr)
        if len(fires) < 15:
            continue
        books = load_orderbook_l25_streaming(asset, slugs=set(fires), subsample_1hz=True,
                                             min_ts_us=WIN_LO * 1_000_000, max_ts_us=WIN_HI * 1_000_000)
        recs = []
        for slug, (fsec, fav, truth) in fires.items():
            key = (slug, fav)
            if key not in books:
                continue
            ts, ap, asz, *_ = books[key]
            i = np.searchsorted(ts, fsec * 1_000_000, "right") - 1
            if i < 0 or abs(ts[i] - fsec * 1_000_000) > 3_000_000:
                continue
            vw = walk_ask(ap[i], asz[i], NOTIONAL)
            if vw is None or not (0.01 < vw < 0.999):
                continue
            won = (fav == "Up" and truth == 1) or (fav == "Down" and truth == 0)
            recs.append(dict(vwap=vw, won=won, pnl=pnl_07(won, vw, NOTIONAL / vw)))
        D = pd.DataFrame(recs)
        if len(D) < 15:
            continue
        for cap in CAPS:
            g = D[D.vwap <= cap]
            if len(g) < 12:
                continue
            wr = g.won.mean(); ev = g.pnl.mean(); mv = g.vwap.mean()
            s = g.pnl.sort_values(); extop2 = s.iloc[:-2].mean() if len(s) > 4 else ev
            rows_out.append(dict(asset=asset, thr=thr, cap=cap, fired=len(fires), n=len(g),
                                 fill_pct=round(len(D) / len(fires) * 100, 1),
                                 WR=round(wr * 100, 1), entry=round(mv, 3),
                                 gap_pp=round((wr - mv) * 100, 1),
                                 dol_tr=round(ev, 4), extop2=round(extop2, 4)))

R = pd.DataFrame(rows_out)
print("\n=== SELECTOR backtest (fire@120 iff |move120|>=thr & monotonic; HOLD; $1; 0.07 fee) ===")
print("(gap_pp = WR-entry = poly underpricing; dol_tr = $/trade; extop2 = ex-top-2-winners robustness)")
print(R.sort_values(["asset", "thr", "cap"]).to_string(index=False))
print("\n=== READ vs LOOSE trigger (prior bt: BTC best +$0.014 gap+1.5pp, ex-top2 +0.006; ETH neg) ===")
for asset in ("btc", "eth"):
    a = R[R.asset == asset]
    if len(a):
        b = a.loc[a.dol_tr.idxmax()]
        print(f"[{asset}] best: thr={b.thr:.0f} cap={b.cap:.2f} fired={b.fired:.0f} n={b.n:.0f} fill={b.fill_pct}% "
              f"WR={b.WR}% entry={b.entry} gap={b.gap_pp}pp $/tr={b.dol_tr:+.4f} ex-top2={b.extop2:+.4f}")
print("\nCyclops live 5d: WR 96.2%, entry 0.83 (n=26).  Selector fires/day target ~5.")
print(TAG, "OUTPUT END")
