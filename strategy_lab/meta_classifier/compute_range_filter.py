"""
Range Filter [DW] (DonovanWall) — Python port for 1s binance BTC/ETH/SOL.

Faithful reimplementation of the Pine Script v4 study with defaults:
  filter_type      = "Type 1"
  movement_source  = "Close"
  range_qty        = 2.618
  range_scale      = "Average Change"
  range_period n   = 14
  smooth_range     = True
  smooth_period sn = 27
  av_vals          = False

Pine semantics implemented:
  Cond_EMA(x, cond=True, n) = standard EMA, alpha = 2/(n+1)
  AC          = Cond_EMA(abs(x - x[-1]), 1, n)
  rng_size    = qty * AC
  rng_smooth  = Cond_EMA(rng_size, 1, sn)
  r           = rng_smooth

  Type 1 (h = l = close when movement_source=Close):
    rfilt[0] = (h+l)/2 = close[0]
    rfilt[t] = h - r          if h - r > rfilt[t-1]
             = l + r          if l + r < rfilt[t-1]
             = rfilt[t-1]     otherwise

  hi_band  = rfilt + r
  lo_band  = rfilt - r
  fdir     = +1 if rfilt > rfilt[-1]
             -1 if rfilt < rfilt[-1]
             carry otherwise (start 0)

Outputs per (asset, ts_us):
  rf_close, rf_hi, rf_lo, rf_r, rf_dir, rf_dir_age,
  rf_dist_bps = (close - rf_close) / rf_close * 1e4,
  rf_band_pos = (close - rf_lo) / (rf_hi - rf_lo)

CAUSAL fire-time merge: pd.merge_asof(direction='backward', tolerance=5s) so the
fire at fire_us receives the LAST 1s bar with ts_us <= fire_us - 1_000_000
(the last fully CLOSED 1s bar before fire_us). To enforce that "fully closed"
constraint we add 1s to the kline ts_us when merging, so a bar with raw
ts_us = T (covering [T, T+1s)) is keyed at T + 1_000_000 in the merge.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from numba import njit
    HAVE_NUMBA = True
except ImportError:
    HAVE_NUMBA = False


# ----------------------------- Range Filter core -----------------------------

if HAVE_NUMBA:
    @njit(cache=True)
    def _range_filter_loop(close: np.ndarray, n: int, sn: int, qty: float):
        N = close.shape[0]
        rf_close = np.empty(N, dtype=np.float64)
        rf_hi    = np.empty(N, dtype=np.float64)
        rf_lo    = np.empty(N, dtype=np.float64)
        rf_r     = np.empty(N, dtype=np.float64)
        rf_dir   = np.zeros(N, dtype=np.int8)

        alpha_n  = 2.0 / (n + 1.0)
        alpha_sn = 2.0 / (sn + 1.0)

        ac = 0.0
        rng_smooth = 0.0
        rfilt = close[0]
        rfilt_prev = close[0]
        dir_prev = 0

        for t in range(N):
            c = close[t]
            if t == 0:
                d = 0.0
            else:
                d = abs(c - close[t - 1])

            # Cond_EMA(abs(diff), 1, n) — standard EMA seeded on the running value
            # Pine's EMA with cond=true is the same as a recursive EMA from t=0
            # initialized to the input at t=0 (we seed with 0 to match Pine's
            # na->nz behavior where the first iteration outputs the first input).
            if t == 0:
                ac = d
            else:
                ac = ac + alpha_n * (d - ac)

            rng_size = qty * ac

            if t == 0:
                rng_smooth = rng_size
            else:
                rng_smooth = rng_smooth + alpha_sn * (rng_size - rng_smooth)

            r = rng_smooth

            # Type 1 update with h = l = close
            if t == 0:
                rfilt = c
            else:
                if c - r > rfilt_prev:
                    rfilt = c - r
                elif c + r < rfilt_prev:
                    rfilt = c + r
                else:
                    rfilt = rfilt_prev

            if rfilt > rfilt_prev:
                d_now = 1
            elif rfilt < rfilt_prev:
                d_now = -1
            else:
                d_now = dir_prev

            rf_close[t] = rfilt
            rf_r[t]     = r
            rf_hi[t]    = rfilt + r
            rf_lo[t]    = rfilt - r
            rf_dir[t]   = d_now

            rfilt_prev = rfilt
            dir_prev   = d_now

        return rf_close, rf_hi, rf_lo, rf_r, rf_dir

else:
    def _range_filter_loop(close, n, sn, qty):
        N = close.shape[0]
        rf_close = np.empty(N, dtype=np.float64)
        rf_hi    = np.empty(N, dtype=np.float64)
        rf_lo    = np.empty(N, dtype=np.float64)
        rf_r     = np.empty(N, dtype=np.float64)
        rf_dir   = np.zeros(N, dtype=np.int8)

        alpha_n  = 2.0 / (n + 1.0)
        alpha_sn = 2.0 / (sn + 1.0)

        ac = 0.0
        rng_smooth = 0.0
        rfilt = close[0]
        rfilt_prev = close[0]
        dir_prev = 0

        for t in range(N):
            c = close[t]
            d = 0.0 if t == 0 else abs(c - close[t - 1])
            ac = d if t == 0 else (ac + alpha_n * (d - ac))
            rng_size = qty * ac
            rng_smooth = rng_size if t == 0 else (rng_smooth + alpha_sn * (rng_size - rng_smooth))
            r = rng_smooth

            if t == 0:
                rfilt = c
            else:
                if c - r > rfilt_prev:
                    rfilt = c - r
                elif c + r < rfilt_prev:
                    rfilt = c + r
                else:
                    rfilt = rfilt_prev

            if rfilt > rfilt_prev:
                d_now = 1
            elif rfilt < rfilt_prev:
                d_now = -1
            else:
                d_now = dir_prev

            rf_close[t] = rfilt
            rf_r[t]     = r
            rf_hi[t]    = rfilt + r
            rf_lo[t]    = rfilt - r
            rf_dir[t]   = d_now

            rfilt_prev = rfilt
            dir_prev   = d_now

        return rf_close, rf_hi, rf_lo, rf_r, rf_dir


def compute_range_filter_for_asset(df_close_sorted: pd.DataFrame,
                                    n: int = 14, sn: int = 27, qty: float = 2.618) -> pd.DataFrame:
    """df_close_sorted must have ['ts_us','close'] sorted by ts_us ascending."""
    close = df_close_sorted["close"].to_numpy(dtype=np.float64)
    rf_close, rf_hi, rf_lo, rf_r, rf_dir = _range_filter_loop(close, n, sn, qty)

    out = pd.DataFrame({
        "ts_us":    df_close_sorted["ts_us"].to_numpy(),
        "close":    close,
        "rf_close": rf_close,
        "rf_hi":    rf_hi,
        "rf_lo":    rf_lo,
        "rf_r":     rf_r,
        "rf_dir":   rf_dir.astype(np.int8),
    })

    # rf_dir_age = bars since last flip (resets to 0 at flip, increments after)
    flips = (out["rf_dir"].to_numpy() != np.roll(out["rf_dir"].to_numpy(), 1)).astype(np.int64)
    flips[0] = 1
    # ages: cumulative count since last flip
    age = np.empty(len(out), dtype=np.int64)
    a = 0
    flip_arr = flips
    for i in range(len(out)):
        if flip_arr[i] == 1:
            a = 0
        else:
            a += 1
        age[i] = a
    out["rf_dir_age"] = age.astype(np.int32)

    out["rf_dist_bps"] = (out["close"] - out["rf_close"]) / out["rf_close"] * 1e4
    denom = (out["rf_hi"] - out["rf_lo"]).replace(0, np.nan)
    out["rf_band_pos"] = (out["close"] - out["rf_lo"]) / denom

    return out


# --------------------------------- Pipeline ---------------------------------

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
KLINES_PATH = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
RESULTS_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
RF_OUT      = RESULTS_DIR / "range_filter_1s.parquet"


SYMBOL_TO_ASSET = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}


def build_panel() -> pd.DataFrame:
    print(f"[load] reading {KLINES_PATH}", flush=True)
    t0 = time.time()
    k = pd.read_parquet(KLINES_PATH,
                         columns=["symbol_id", "time_period_start_us", "price_close"])
    k = k.rename(columns={"time_period_start_us": "ts_us", "price_close": "close"})
    k["asset"] = k["symbol_id"].map(SYMBOL_TO_ASSET)
    k = k[k["asset"].notna()].copy()
    k = k[["asset", "ts_us", "close"]]
    k = k.sort_values(["asset", "ts_us"]).reset_index(drop=True)
    print(f"[load] {len(k):,} rows in {time.time()-t0:.1f}s; assets={k['asset'].unique().tolist()}",
          flush=True)
    return k


def run_filter(panel: pd.DataFrame) -> pd.DataFrame:
    outs = []
    for asset, grp in panel.groupby("asset", sort=False):
        t0 = time.time()
        grp = grp[["ts_us", "close"]].reset_index(drop=True)
        rf = compute_range_filter_for_asset(grp)
        rf.insert(0, "asset", asset)
        outs.append(rf)
        print(f"[rf]   {asset:>3} rows={len(rf):,} "
              f"dir+1 pct={(rf['rf_dir']==1).mean()*100:.1f}  "
              f"dir-1 pct={(rf['rf_dir']==-1).mean()*100:.1f}  "
              f"dir0 pct={(rf['rf_dir']==0).mean()*100:.1f}  "
              f"({time.time()-t0:.1f}s)", flush=True)
    out = pd.concat(outs, ignore_index=True)
    return out


def merge_onto_fires(rf_panel: pd.DataFrame, fires_path: Path, out_path: Path,
                     fire_col: str = "fire_us") -> dict:
    if not fires_path.exists():
        print(f"[merge] SKIP missing: {fires_path}", flush=True)
        return {}

    print(f"[merge] {fires_path.name}  ->  {out_path.name}", flush=True)
    fires = pd.read_parquet(fires_path)
    if fire_col not in fires.columns:
        print(f"[merge] SKIP no '{fire_col}' col in {fires_path.name}", flush=True)
        return {}

    rf_cols = ["rf_close", "rf_hi", "rf_lo", "rf_r", "rf_dir", "rf_dir_age",
               "rf_dist_bps", "rf_band_pos"]

    # Drop any pre-existing rf_* cols to avoid suffix collisions
    fires = fires.drop(columns=[c for c in rf_cols if c in fires.columns], errors="ignore")

    pieces = []
    for asset, fg in fires.groupby("asset", sort=False):
        rg = rf_panel[rf_panel["asset"] == asset].copy()
        if rg.empty:
            print(f"[merge]   no rf for asset={asset}, skipping {len(fg)} fires", flush=True)
            pieces.append(fg.assign(**{c: np.nan for c in rf_cols}))
            continue

        # Causal "fully closed" merge: a 1s bar covers [ts_us, ts_us+1s) so its
        # close becomes known at ts_us + 1_000_000. Key the kline at that time
        # then merge backward — fires at fire_us get the last bar that closed
        # at or before fire_us.
        rg["key_us"] = rg["ts_us"] + 1_000_000
        rg = rg[["key_us", "ts_us"] + rf_cols].sort_values("key_us").reset_index(drop=True)

        fg = fg.sort_values(fire_col).reset_index(drop=True)
        merged = pd.merge_asof(
            fg, rg,
            left_on=fire_col, right_on="key_us",
            direction="backward",
            tolerance=5_000_000,  # 5 seconds in us
            suffixes=("", "_rf"),
        )
        merged = merged.drop(columns=["key_us"], errors="ignore")
        # rename rf-side ts_us to avoid clobbering fire-side ts_us if present
        if "ts_us_rf" in merged.columns:
            merged = merged.rename(columns={"ts_us_rf": "rf_bar_ts_us"})
        elif "ts_us" in merged.columns and "ts_us" in fg.columns:
            # both sides had ts_us — pandas suffix logic kept the left one as ts_us
            pass
        pieces.append(merged)

    out = pd.concat(pieces, ignore_index=True)
    out.to_parquet(out_path, compression="zstd", index=False)

    cov = out["rf_dir"].notna().mean() * 100 if "rf_dir" in out.columns else 0.0
    print(f"[merge]   wrote {out_path.name} rows={len(out):,} size={os.path.getsize(out_path)/1e6:.1f}MB "
          f"rf_dir cov={cov:.1f}%", flush=True)

    # Fire-direction agreement metric (needs direction col 'UP'/'DOWN' or pick/prediction)
    summary = {
        "rows": int(len(out)),
        "rf_dir_coverage_pct": float(cov),
    }
    dir_col = None
    for cand in ("direction", "pick", "prediction"):
        if cand in out.columns:
            dir_col = cand
            break
    if dir_col is not None and "rf_dir" in out.columns:
        m = out.dropna(subset=["rf_dir"]).copy()
        m["bet_int"] = m[dir_col].astype(str).str.upper().map({"UP": 1, "DOWN": -1})
        m = m.dropna(subset=["bet_int"])
        m["agree"] = (m["bet_int"].astype(int) == m["rf_dir"].astype(int)).astype(int)
        summary["fire_agree_pct"] = float(m["agree"].mean() * 100) if len(m) else float("nan")
        summary["bet_dir_col"] = dir_col
        summary["n_with_dir"]  = int(len(m))
    return summary


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    panel = build_panel()
    rf_panel = run_filter(panel)

    print(f"[save] writing {RF_OUT} ...", flush=True)
    rf_panel.to_parquet(RF_OUT, compression="zstd", index=False)
    print(f"[save]   size={os.path.getsize(RF_OUT)/1e6:.1f}MB rows={len(rf_panel):,}", flush=True)

    fire_specs = [
        (RESULTS_DIR / "s15_with_ta.parquet",            RESULTS_DIR / "s15_with_rf.parquet"),
        (RESULTS_DIR / "s15_with_ta_and_markov.parquet", RESULTS_DIR / "s15_with_ta_markov_rf.parquet"),
        (RESULTS_DIR / "s6_with_ta.parquet",             RESULTS_DIR / "s6_with_rf.parquet"),
        (RESULTS_DIR / "v15m_with_ta_and_markov.parquet",RESULTS_DIR / "v15m_with_ta_markov_rf.parquet"),
    ]

    merge_summaries = {}
    for src, dst in fire_specs:
        s = merge_onto_fires(rf_panel, src, dst)
        if s:
            merge_summaries[dst.name] = s

    # ----------------------------- Report -----------------------------
    print("[report] computing summary stats ...", flush=True)
    rep_lines = []
    rep_lines.append("# Range Filter [DW] 1s panel — 2026-05-25\n")
    rep_lines.append("Defaults: Type 1 / Close / qty=2.618 / Average Change / n=14 / smooth=true / sn=27\n")

    rep_lines.append("## Per-asset summary\n")
    rep_lines.append("| asset | bars | dir+1 % | dir-1 % | dir0 % | mean dwell (s) | median dwell (s) |")
    rep_lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for asset, grp in rf_panel.groupby("asset"):
        d = grp["rf_dir"].to_numpy()
        flips = np.where(d[1:] != d[:-1])[0]
        if len(flips) > 1:
            seg_lens = np.diff(flips)
            mean_dwell = float(seg_lens.mean())
            med_dwell  = float(np.median(seg_lens))
        else:
            mean_dwell = med_dwell = float("nan")
        rep_lines.append(f"| {asset} | {len(grp):,} | "
                          f"{(d==1).mean()*100:.2f} | {(d==-1).mean()*100:.2f} | {(d==0).mean()*100:.2f} | "
                          f"{mean_dwell:.1f} | {med_dwell:.1f} |")

    rep_lines.append("\n## rf_band_pos distribution (per asset)\n")
    rep_lines.append("| asset | p5 | p25 | p50 | p75 | p95 | <0 % | >1 % |")
    rep_lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for asset, grp in rf_panel.groupby("asset"):
        bp = grp["rf_band_pos"].dropna()
        q = bp.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
        rep_lines.append(f"| {asset} | {q.iloc[0]:.2f} | {q.iloc[1]:.2f} | {q.iloc[2]:.2f} | "
                          f"{q.iloc[3]:.2f} | {q.iloc[4]:.2f} | "
                          f"{(bp<0).mean()*100:.2f} | {(bp>1).mean()*100:.2f} |")

    # Hand-verification on first 100 BTC bars
    rep_lines.append("\n## Verification — first 100 BTC bars (recompute)\n")
    btc = panel[panel["asset"] == "BTC"].head(100).reset_index(drop=True)
    rf_btc_full = rf_panel[rf_panel["asset"] == "BTC"].head(100).reset_index(drop=True)

    # Pure-python reference recompute
    closes = btc["close"].to_numpy(dtype=np.float64)
    n, sn, qty = 14, 27, 2.618
    a_n, a_sn = 2.0/(n+1.0), 2.0/(sn+1.0)
    ac = closes[0] * 0.0  # 0
    rs = 0.0
    rf = closes[0]
    rf_prev = closes[0]
    ref_rf = np.empty(100); ref_r = np.empty(100)
    for t, c in enumerate(closes):
        d = 0.0 if t == 0 else abs(c - closes[t-1])
        ac = d if t == 0 else ac + a_n*(d - ac)
        rng_size = qty * ac
        rs = rng_size if t == 0 else rs + a_sn*(rng_size - rs)
        r = rs
        if t == 0:
            rf = c
        else:
            if c - r > rf_prev:
                rf = c - r
            elif c + r < rf_prev:
                rf = c + r
            else:
                rf = rf_prev
        ref_rf[t] = rf; ref_r[t] = r
        rf_prev = rf

    diff_rf = float(np.max(np.abs(ref_rf - rf_btc_full["rf_close"].to_numpy())))
    diff_r  = float(np.max(np.abs(ref_r  - rf_btc_full["rf_r"].to_numpy())))
    rep_lines.append(f"- max |rf_close ref vs prod| on 100 BTC bars = {diff_rf:.6e}")
    rep_lines.append(f"- max |rf_r     ref vs prod| on 100 BTC bars = {diff_r:.6e}")
    rep_lines.append(f"- sample (last bar, idx 99): close={closes[99]:.2f}  rf={ref_rf[99]:.4f}  r={ref_r[99]:.4f}\n")

    # Fire agreement
    rep_lines.append("## Fire-time rf_dir agreement (vs bet direction)\n")
    rep_lines.append("| file | rows | rf cov % | dir col | n w/dir | agree % |")
    rep_lines.append("|---|---:|---:|---|---:|---:|")
    for fname, s in merge_summaries.items():
        rep_lines.append(f"| {fname} | {s.get('rows','-')} | {s.get('rf_dir_coverage_pct',float('nan')):.2f} | "
                          f"{s.get('bet_dir_col','-')} | {s.get('n_with_dir','-')} | "
                          f"{s.get('fire_agree_pct',float('nan')):.2f} |")

    rep_lines.append("")
    rep_path = ROOT / "strategy_lab" / "reports" / "RANGE_FILTER_PANEL_2026_05_25.md"
    rep_path.write_text("\n".join(rep_lines), encoding="utf-8")
    print(f"[report] wrote {rep_path}", flush=True)


if __name__ == "__main__":
    main()
