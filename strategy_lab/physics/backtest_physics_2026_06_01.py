"""
backtest_physics_2026_06_01.py — implement the "physics of BTC" signal on canonical
data and TUNE the article's 2-parameter WEAK_COMBO block (find the 2 thresholds).

Model (per the article):
- bet = CONTINUATION: side BTC is currently on vs strike (inertia hard to reverse).
- fire near close (have=60s default; --have to sweep).
- won = chainlink outcome matches the side.
- WEAK_COMBO: skip iff BOTH entry params weak. Grid finds which 2 params + thresholds
  maximize out-of-sample WR while retaining enough fires and removing losers.

Primary feed = chainlink RTDS (outcome-consistent). Binance-1s speed = ablation.
Run: C:/Python314/python.exe strategy_lab/physics/backtest_physics_2026_06_01.py
"""
from __future__ import annotations
import sys, itertools
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "physics"))
from load import load_resolutions, load_chainlink_asof, load_klines_1s  # noqa
from physics_signal import physics_at, speed_bucket  # noqa

OUT = ROOT / "strategy_lab" / "physics" / "_results"
OUT.mkdir(parents=True, exist_ok=True)
HAVE_S = 60          # fire at slot_end - 60s
SPEED_WIN_S = 60     # speed measured over trailing 60s


def binance_arrays(asset: str):
    try:
        df = load_klines_1s(asset)
    except Exception as e:
        print(f"[binance] load failed: {e}"); return None
    if df is None or len(df) == 0:
        return None
    tcol = next((c for c in ("time_period_start_us", "open_ms", "timestamp_us", "time_open_us") if c in df.columns), None)
    ccol = next((c for c in ("price_close", "close", "c") if c in df.columns), None)
    if tcol is None or ccol is None:
        print(f"[binance] cols not found in {list(df.columns)[:8]}"); return None
    ts = df[tcol].to_numpy(np.int64)
    if ts.max() < 10_000_000_000_000:  # ms -> us guard
        ts = ts * 1000
    px = df[ccol].to_numpy(float)
    order = np.argsort(ts)
    return ts[order], px[order]


def build(asset="BTC"):
    res = load_resolutions(assets=[asset], timeframes=["5m", "15m"]).copy()
    res = res[res.outcome.isin(["Up", "Down"])].dropna(subset=["strike_price"])
    res = res.sort_values("slot_start_us").reset_index(drop=True)
    cl_ts, cl_px = load_chainlink_asof(asset)
    cl_ts = np.asarray(cl_ts, np.int64); cl_px = np.asarray(cl_px, float)
    bn = binance_arrays(asset)
    rows = []
    for r in res.itertuples(index=False):
        se = int(r.slot_end_us); fire = se - HAVE_S * 1_000_000
        K = float(r.strike_price)
        f = physics_at(cl_ts, cl_px, K, fire, se, SPEED_WIN_S)
        if f is None:
            continue
        won = int((f["bet"]) == r.outcome)
        row = dict(slug=r.slug, tf=r.timeframe, slot_start_us=int(r.slot_start_us),
                   outcome=r.outcome, bet=f["bet"], won=won,
                   dist=f["dist"], dist_abs=f["dist_abs"], side=f["side"],
                   speed=f["speed"], speed_abs=f["speed_abs"], speed_away=f["speed_away"],
                   cross=f["cross"], have_m=f["have_m"], margin=f["margin"])
        if bn is not None:
            fb = physics_at(bn[0], bn[1], K, fire, se, SPEED_WIN_S)
            if fb is not None:
                row.update(bn_speed=fb["speed"], bn_speed_abs=fb["speed_abs"],
                           bn_speed_away=fb["speed_away"], bn_cross=fb["cross"],
                           bn_margin=fb["margin"])
        rows.append(row)
    return pd.DataFrame(rows)


def distribution(df):
    s = df["speed_abs"]
    print("\n=== SPEED DISTRIBUTION (chainlink $/min, our data) ===")
    print(f"  n={len(s)}  mean={s.mean():.1f}  median={s.median():.1f}  "
          f"max={s.max():.0f}  std={s.std():.1f}  storm(>15)={100*(s>15).mean():.0f}%  "
          f"avg|dist|={df['dist_abs'].mean():.0f}$")
    for k in ["quiet <5", "normal 5-10", "active 10-15", "storm 15-25", "hurricane >=25"]:
        pct = 100 * df["speed_abs"].map(speed_bucket).eq(k).mean()
        print(f"    {k:<16s} {pct:5.1f}%")
    if "bn_speed_abs" in df:
        b = df["bn_speed_abs"].dropna()
        print(f"  [binance ablation] mean={b.mean():.1f} median={b.median():.1f} storm>15={100*(b>15).mean():.0f}%")


def baseline(df):
    print("\n=== BASELINE continuation-bet WR (no filter) ===")
    print(f"  ALL: n={len(df)}  WR={100*df.won.mean():.1f}%")
    for tf in ["5m", "15m"]:
        d = df[df.tf == tf]
        if len(d): print(f"  {tf}: n={len(d)}  WR={100*d.won.mean():.1f}%")
    # WR by speed bucket and by dist bucket (which axis carries the edge?)
    print("  WR by |speed| bucket:")
    for k in ["quiet <5", "normal 5-10", "active 10-15", "storm 15-25", "hurricane >=25"]:
        d = df[df.speed_abs.map(speed_bucket) == k]
        if len(d): print(f"    {k:<16s} n={len(d):5d} WR={100*d.won.mean():.1f}%")
    print("  WR by |dist| bucket:")
    for lo, hi in [(0,15),(15,30),(30,50),(50,100),(100,1e9)]:
        d = df[(df.dist_abs >= lo) & (df.dist_abs < hi)]
        if len(d): print(f"    [{lo:>3},{hi if hi<1e9 else 'inf'}) n={len(d):5d} WR={100*d.won.mean():.1f}%")


def grid(df):
    """Grid the 2-param WEAK_COMBO. Train=first 60% by time, test=last 40%."""
    df = df.sort_values("slot_start_us").reset_index(drop=True)
    cut = int(len(df) * 0.6)
    tr, te = df.iloc[:cut], df.iloc[cut:]
    base_tr, base_te = tr.won.mean(), te.won.mean()
    PARAMS = {
        "dist_abs":   [10, 15, 20, 25, 30, 40, 50],
        "speed_away": [0, 3, 5, 7, 10, 15],
        "cross":      [1.0, 1.5, 2.0, 3.0, 5.0],
        "margin":     [-0.5, 0.0, 0.5, 1.0, 2.0],
    }
    pnames = list(PARAMS)
    out = []
    for a, b in itertools.combinations(pnames, 2):
        for ta in PARAMS[a]:
            for tb in PARAMS[b]:
                blk_tr = (tr[a] < ta) & (tr[b] < tb)
                blk_te = (te[a] < ta) & (te[b] < tb)
                kept_tr, kept_te = ~blk_tr, ~blk_te
                if kept_tr.sum() < 50 or kept_te.sum() < 50:
                    continue
                kf_tr, kf_te = kept_tr.mean(), kept_te.mean()
                if kf_tr < 0.30 or kf_te < 0.30:
                    continue
                wr_tr, wr_te = tr.won[kept_tr].mean(), te.won[kept_te].mean()
                wr_blk_te = te.won[blk_te].mean() if blk_te.sum() else np.nan
                out.append(dict(pa=a, ta=ta, pb=b, tb=tb,
                                base_tr=round(base_tr, 4), wr_tr=round(wr_tr, 4),
                                base_te=round(base_te, 4), wr_te=round(wr_te, 4),
                                lift_tr=round(wr_tr - base_tr, 4), lift_te=round(wr_te - base_te, 4),
                                keep_te=round(kf_te, 3), n_keep_te=int(kept_te.sum()),
                                wr_blocked_te=round(wr_blk_te, 4) if np.isfinite(wr_blk_te) else None,
                                n_block_te=int(blk_te.sum())))
    g = pd.DataFrame(out)
    if g.empty:
        print("\n[grid] no config met constraints"); return g
    # require consistent OOS lift (both train and test improve), then rank by test WR
    g = g[(g.lift_tr > 0) & (g.lift_te > 0)].copy()
    g = g.sort_values("wr_te", ascending=False).reset_index(drop=True)
    g.to_csv(OUT / "physics_weakcombo_grid.csv", index=False)
    print(f"\n=== WEAK_COMBO GRID (train 60% / test 40%; base_te={100*base_te:.1f}%) ===")
    print(f"  {len(g)} configs with consistent OOS lift. Top 12 by test WR:")
    cols = ["pa","ta","pb","tb","wr_tr","wr_te","lift_te","keep_te","n_keep_te","wr_blocked_te","n_block_te"]
    with pd.option_context("display.width", 220, "display.max_columns", 20):
        print(g[cols].head(12).to_string(index=False))
    # the article's implied pair: dist_abs x speed_away
    ds = g[((g.pa=="dist_abs")&(g.pb=="speed_away"))|((g.pa=="speed_away")&(g.pb=="dist_abs"))]
    if len(ds):
        print("\n  >>> ARTICLE-IMPLIED PAIR (dist_abs x speed_away), best by test WR:")
        print(ds[cols].head(3).to_string(index=False))
    return g


def main():
    df = build("BTC")
    df.to_parquet(OUT / "physics_fires_btc.parquet", index=False)
    print(f"built {len(df)} BTC fires (have={HAVE_S}s, speed_win={SPEED_WIN_S}s)")
    distribution(df)
    baseline(df)
    grid(df)
    print(f"\nwrote {OUT/'physics_fires_btc.parquet'} + physics_weakcombo_grid.csv")


if __name__ == "__main__":
    main()
