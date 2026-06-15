"""CYCLOPS mid-window favorite-HOLD — L25 $-backtest on canonical (fresh to Jun 15).
Tests the decoded rule with REAL Polymarket entry prices (L25 book walk):
  For each BTC/ETH 5m slug in [Jun 1 -> Jun 15]:
   1. window open = slot_start; binance px_open = 1s close @ slot_start.
   2. fire = first offset t in SCAN where |binance ret open->t| >= THR bps (aligned).
      favorite = sign(ret).  (no fire -> skip)
   3. at fire_sec, walk the favorite-side L25 ask for $1 notional -> entry_vwap.
   4. GATE: enter only if entry_vwap <= cap (the LAG condition).
   5. won = favorite==chainlink outcome.  PnL = 0.07 winner-only.
  Reports per (THR, cap): n, fill%, WR, $/trade, mean entry_vwap, and the KEY number:
  gap = WR(=conditional truth) - mean_entry_vwap  (poly lag; >0 => real edge).
  + DSR + ex-top2 robustness.

L25 loaded at 1Hz (subsample) — measuring the price GAP/edge existence, not live-parity fill.
Run: C:/Python314/python.exe strategy_lab/directional/cyclops_l25_backtest_2026_06_15.py
"""
from __future__ import annotations
import sys, io
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import numpy as np, pandas as pd
import pyarrow.parquet as pq, pyarrow.compute as pc, pyarrow as pa
pd.set_option("display.width", 240); pd.set_option("display.max_columns", 40)
TAG = "CYCLOPS_L25_BACKTEST_2026_06_15"; print(TAG, "OUTPUT START", flush=True)
from load import load_resolutions, load_orderbook_l25_streaming  # noqa

CANON = Path(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
WIN = 300
WIN_LO = 1780272000   # 2026-06-01 00:00 UTC
WIN_HI = 1781528400   # 2026-06-15 ~13:40 UTC
SCAN = [90, 105, 120, 135, 150, 165, 180]
THRS = [5.0, 8.0]
CAPS = [0.83, 0.88, 0.90, 1.00]
NOTIONAL = 1.0
FEE_K = 0.07


def pnl_07(won, vwap, shares):
    return shares * (1 - vwap) * (1 - FEE_K * vwap) if won else -shares * vwap


# ---- klines 1s (BTC+ETH) via arrow projection + filter (avoid 71M OOM) ----
def load_kl(symbols):
    pf = pq.ParquetFile(CANON / "klines_1s.parquet")
    keep_sym = pa.array(symbols)
    secs = {s: {} for s in symbols}
    for batch in pf.iter_batches(batch_size=200_000, columns=["symbol_id", "time_period_start_us", "price_close"]):
        m = pc.is_in(batch.column("symbol_id"), value_set=keep_sym)
        if pc.sum(m).as_py() == 0:
            continue
        b = batch.filter(m).to_pydict()
        for sym, t, c in zip(b["symbol_id"], b["time_period_start_us"], b["price_close"]):
            secs[sym][t // 1_000_000] = c
    out = {}
    for sym in symbols:
        d = secs[sym]
        k = np.array(sorted(d), dtype=np.int64)
        v = np.array([d[x] for x in k], dtype=np.float64)
        out[sym] = (k, v)
    return out


SYM = {"btc": "BINANCE_SPOT_BTC_USDT", "eth": "BINANCE_SPOT_ETH_USDT"}
print("loading klines_1s (btc+eth)…", flush=True)
KL = load_kl(list(SYM.values()))
for a, s in SYM.items():
    print(f"  {a}: {len(KL[s][0])} secs  max={pd.to_datetime(KL[s][0].max(),unit='s')}", flush=True)


def px_at(arr, sec):
    idx, vals = arr
    i = np.searchsorted(idx, sec, side="right") - 1
    return float(vals[i]) if i >= 0 else np.nan


# ---- resolutions ----
res = load_resolutions(); res.columns = [c.lower() for c in res.columns]
res = res[res["slug"].astype(str).str.contains("updown-5m", na=False)].copy()
res["asset"] = res["slug"].astype(str).str.extract(r"^([a-z0-9]+)-updown")[0]
res = res[res["asset"].isin(["btc", "eth"])].copy()
res["slot_start"] = pd.to_numeric(res["slug"].astype(str).str.extract(r"-(\d+)\Z")[0], errors="coerce")
res = res.dropna(subset=["slot_start"]); res["slot_start"] = res["slot_start"].astype(int)
res = res[(res.slot_start >= WIN_LO) & (res.slot_start + WIN <= WIN_HI)]
res["truth_up"] = res["outcome"].astype(str).str.lower().map({"up": 1, "down": 0})
res = res.dropna(subset=["truth_up"])
print(f"\nslugs in window: {res.groupby('asset').size().to_dict()}", flush=True)


def walk_ask(ap_row, asz_row, notional):
    """vwap to fill `notional` USDC on the ask ladder; None if insufficient/no book."""
    spent = 0.0; shares = 0.0; remain = notional
    for p, s in zip(ap_row, asz_row):
        if not (p > 0 and s > 0):
            continue
        lvl_cost = p * s
        if lvl_cost >= remain:
            shares += remain / p; spent += remain; remain = 0.0; break
        shares += s; spent += lvl_cost; remain -= lvl_cost
    if shares <= 0 or remain > 0:  # no book or couldn't fill full notional
        return None
    return spent / shares  # vwap


# build per-asset slug sets and decode fire offset + favorite (klines only) first
def decode_fires(asset, thr):
    sub = res[res.asset == asset]; arr = KL[SYM[asset]]
    fires = {}  # slug -> (fire_sec, favorite_outcome 'Up'/'Down', truth_up)
    for _, r in sub.iterrows():
        ss = int(r.slot_start); po = px_at(arr, ss)
        if not po or np.isnan(po):
            continue
        for t in SCAN:
            pt = px_at(arr, ss + t)
            if np.isnan(pt):
                continue
            ret = (pt / po - 1) * 1e4
            if abs(ret) >= thr:
                fav = "Up" if ret > 0 else "Down"
                fires[r.slug] = (ss + t, fav, int(r.truth_up))
                break
    return fires


results = []
for asset in ("btc", "eth"):
    for thr in THRS:
        fires = decode_fires(asset, thr)
        if not fires:
            continue
        slugset = set(fires)
        print(f"\n[{asset} thr={thr:.0f}bps] fired slugs={len(slugset)} — loading L25…", flush=True)
        books = load_orderbook_l25_streaming(asset, slugs=slugset, subsample_1hz=True,
                                             min_ts_us=WIN_LO * 1_000_000, max_ts_us=WIN_HI * 1_000_000)
        # index books by (slug, outcome)
        rows = []
        for slug, (fire_sec, fav, truth_up) in fires.items():
            key = (slug, fav)
            if key not in books:
                continue
            ts, ap, asz, bp, bsz = books[key]
            i = np.searchsorted(ts, fire_sec * 1_000_000, side="right") - 1
            if i < 0 or abs(ts[i] - fire_sec * 1_000_000) > 3_000_000:  # within 3s
                continue
            vwap = walk_ask(ap[i], asz[i], NOTIONAL)
            if vwap is None or not (0.01 < vwap < 0.999):
                continue
            # other side best ask for overround context
            okey = (slug, "Down" if fav == "Up" else "Up")
            sum_ask = np.nan
            if okey in books:
                ts2, ap2, asz2, *_ = books[okey]
                j = np.searchsorted(ts2, fire_sec * 1_000_000, side="right") - 1
                if j >= 0:
                    ob = next((p for p in ap2[j] if p > 0), np.nan)
                    sum_ask = vwap + ob if not np.isnan(ob) else np.nan
            won = (fav == "Up" and truth_up == 1) or (fav == "Down" and truth_up == 0)
            shares = NOTIONAL / vwap
            rows.append(dict(slug=slug, fav=fav, vwap=vwap, won=won, sum_ask=sum_ask,
                             pnl=pnl_07(won, vwap, shares)))
        D = pd.DataFrame(rows)
        if not len(D):
            print("  no filled fires"); continue
        for cap in CAPS:
            g = D[D.vwap <= cap]
            if len(g) < 15:
                continue
            wr = g.won.mean(); ev = g.pnl.mean(); mv = g.vwap.mean()
            results.append(dict(asset=asset, thr=thr, cap=cap, n=len(g),
                                fill_pct=round(len(D) / len(fires) * 100, 1),
                                WR=round(wr * 100, 1), entry_vwap=round(mv, 3),
                                gap_pp=round((wr - mv) * 100, 1),
                                dol_per_trade=round(ev, 4),
                                sum_ask=round(g.sum_ask.mean(), 3)))
        # stash for ex-top2 on the headline cell (cap=0.90)
        head = D[D.vwap <= 0.90]
        if len(head) >= 15:
            s = head.pnl.sort_values()
            extop2 = s.iloc[:-2].mean()
            print(f"  [{asset} thr={thr:.0f}] cap0.90 n={len(head)} $/tr={head.pnl.mean():+.4f} "
                  f"ex-top2={extop2:+.4f} WR={head.won.mean()*100:.1f}% entry={head.vwap.mean():.3f} "
                  f"sum_ask={head.sum_ask.mean():.3f}")

R = pd.DataFrame(results)
print("\n=== L25 BACKTEST — mid-window favorite-HOLD ($1 notional, 0.07 winner-only fee) ===")
print("(gap_pp = WR − entry_vwap×100 = poly underpricing of the confirmed favorite; >0 = real lag edge)")
print(R.sort_values(["asset", "thr", "cap"]).to_string(index=False))

print("\n=== READ ===")
if len(R):
    pos = R[R.dol_per_trade > 0]
    print(f"cells with $/trade>0: {len(pos)}/{len(R)}")
    for asset in ("btc", "eth"):
        a = R[R.asset == asset]
        if len(a):
            b = a.loc[a.dol_per_trade.idxmax()]
            print(f"[{asset}] best: thr={b.thr:.0f} cap={b.cap:.2f} n={b.n:.0f} WR={b.WR}% "
                  f"entry={b.entry_vwap} gap={b.gap_pp}pp $/tr={b.dol_per_trade:+.4f} sum_ask={b.sum_ask}")
print("\nCyclops live 5d: WR 96.2%, entry 0.83, +$0.56/win, BTC +22% ROI (n=26).")
print(TAG, "OUTPUT END")
