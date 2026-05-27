"""
TASK 1+2+3+4: RF param sweep + 5m/15m PVSRA panel + per-fire join + standalone test.

Reads:
  data/v4/canonical/klines_1s/binance_1s_28d.parquet  (5.5M rows, OHLCV)
  data/v4/canonical/_results/{s15,s6}_with_rf.parquet
  data/v4/canonical/_results/v15m_with_ta_markov_rf.parquet

Writes:
  data/v4/canonical/_results/rf_param_sweep.csv
  data/v4/canonical/_results/pvsra_5m.parquet
  data/v4/canonical/_results/pvsra_15m.parquet
  data/v4/canonical/_results/s15_with_pvsra5m.parquet
  data/v4/canonical/_results/s6_with_pvsra5m.parquet
  data/v4/canonical/_results/v15m_with_pvsra15m.parquet

Sanity: window is canonical refresh (Apr 30 → May 22 2026 approx). Fee model = LegacyConfig
(use existing pnl_legacy_usd / won; the per-fire parquets already have those columns).
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


# ============================================================================
# Range Filter core (replicate of compute_range_filter._range_filter_loop)
# ============================================================================

if HAVE_NUMBA:
    @njit(cache=True)
    def _rf_loop(close, n, sn, qty):
        N = close.shape[0]
        rf_close = np.empty(N, dtype=np.float64)
        rf_dir = np.zeros(N, dtype=np.int8)

        alpha_n = 2.0 / (n + 1.0)
        alpha_sn = 2.0 / (sn + 1.0)
        ac = 0.0
        rng_smooth = 0.0
        rfilt = close[0]
        rfilt_prev = close[0]
        dir_prev = 0

        for t in range(N):
            c = close[t]
            d = 0.0 if t == 0 else abs(c - close[t - 1])
            ac = d if t == 0 else ac + alpha_n * (d - ac)
            rng_size = qty * ac
            rng_smooth = rng_size if t == 0 else rng_smooth + alpha_sn * (rng_size - rng_smooth)
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
            rf_dir[t] = d_now
            rfilt_prev = rfilt
            dir_prev = d_now

        return rf_close, rf_dir
else:
    def _rf_loop(close, n, sn, qty):
        raise RuntimeError("numba required for sweep speed")


# ============================================================================
# Paths
# ============================================================================

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
KLINES_1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
RESULTS = ROOT / "data" / "v4" / "canonical" / "_results"

PARAM_SETS = [
    # (label, n, qty, sn)
    ("n7_q1.5_sn14",       7, 1.5,   14),
    ("n14_q2.0_sn27",     14, 2.0,   27),
    ("n14_q2.618_sn27",   14, 2.618, 27),  # current default
    ("n14_q3.5_sn27",     14, 3.5,   27),
    ("n20_q3.5_sn39",     20, 3.5,   39),  # DonovanWall paper
    ("n28_q2.5_sn55",     28, 2.5,   55),
    ("n14_q2.618_sn1",    14, 2.618,  1),  # no smoothing
]

SYM_TO_ASSET = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}


# ============================================================================
# Step A — load 1s panel ONCE (OHLCV)
# ============================================================================

def load_1s_panel() -> pd.DataFrame:
    print(f"[load-1s] reading {KLINES_1S}", flush=True)
    t0 = time.time()
    k = pd.read_parquet(KLINES_1S, columns=[
        "symbol_id", "time_period_start_us",
        "price_open", "price_high", "price_low", "price_close",
        "volume_traded", "taker_buy_base"
    ])
    k = k.rename(columns={"time_period_start_us": "ts_us"})
    k["asset"] = k["symbol_id"].map(SYM_TO_ASSET)
    k = k[k["asset"].notna()].copy()
    k = k.drop(columns=["symbol_id"])
    k = k.sort_values(["asset", "ts_us"]).reset_index(drop=True)
    print(f"[load-1s] {len(k):,} rows in {time.time()-t0:.1f}s; "
          f"assets={k['asset'].value_counts().to_dict()}", flush=True)
    return k


# ============================================================================
# TASK 1 — RF parameter sweep
# ============================================================================

def rf_sweep(panel_1s: pd.DataFrame, fires_specs: list[tuple]) -> pd.DataFrame:
    """Sweep PARAM_SETS over (asset, fire-source) and report agree/wr metrics."""
    print("\n=== TASK 1 — RF parameter sweep ===\n", flush=True)
    rows = []

    # warm numba
    if HAVE_NUMBA:
        _rf_loop(panel_1s["price_close"].iloc[:200].to_numpy(dtype=np.float64), 14, 27, 2.618)

    for label, n, qty, sn in PARAM_SETS:
        print(f"[sweep] computing param={label}  n={n} qty={qty} sn={sn}", flush=True)
        t0 = time.time()
        rf_per_asset = {}
        for asset, grp in panel_1s.groupby("asset", sort=False):
            close = grp["price_close"].to_numpy(dtype=np.float64)
            t1 = time.time()
            rf_close, rf_dir = _rf_loop(close, n, sn, qty)
            rf_per_asset[asset] = pd.DataFrame({
                "ts_us": grp["ts_us"].to_numpy(),
                "rf_close": rf_close,
                "rf_dir": rf_dir.astype(np.int8),
            })
            print(f"[sweep]   {asset} rf computed in {time.time()-t1:.1f}s "
                  f"(dir+1 {(rf_dir==1).mean()*100:.1f}% dir-1 {(rf_dir==-1).mean()*100:.1f}%)",
                  flush=True)

        # join onto each fire-source and compute per-(asset,tf) metrics
        for src_label, fires_path in fires_specs:
            fires = pd.read_parquet(fires_path,
                                     columns=["asset", "fire_us", "direction", "won"])
            for asset, fg in fires.groupby("asset", sort=False):
                rg = rf_per_asset[asset].copy()
                rg["key_us"] = rg["ts_us"] + 1_000_000
                rg = rg[["key_us", "rf_dir"]].sort_values("key_us").reset_index(drop=True)
                fg = fg.sort_values("fire_us").reset_index(drop=True)
                m = pd.merge_asof(
                    fg, rg,
                    left_on="fire_us", right_on="key_us",
                    direction="backward",
                    tolerance=5_000_000,
                )
                m = m.dropna(subset=["rf_dir"]).copy()
                m["bet_int"] = m["direction"].astype(str).str.upper().map({"UP": 1, "DOWN": -1})
                m = m.dropna(subset=["bet_int"])
                if len(m) == 0:
                    continue
                m["agree"] = (m["bet_int"].astype(int) == m["rf_dir"].astype(int)).astype(int)
                agree_pct = m["agree"].mean() * 100
                # WR by agreement
                agr = m[m["agree"] == 1]
                dis = m[m["agree"] == 0]
                wr_agree = agr["won"].mean() * 100 if len(agr) else float("nan")
                wr_disagree = dis["won"].mean() * 100 if len(dis) else float("nan")
                wr_delta = wr_agree - wr_disagree
                rows.append({
                    "param_set": label,
                    "n": n, "qty": qty, "sn": sn,
                    "asset": asset,
                    "tf": src_label,
                    "fires": int(len(m)),
                    "agree_pct": round(agree_pct, 3),
                    "wr_agree": round(wr_agree, 3) if not np.isnan(wr_agree) else None,
                    "wr_disagree": round(wr_disagree, 3) if not np.isnan(wr_disagree) else None,
                    "wr_delta": round(wr_delta, 3) if not np.isnan(wr_delta) else None,
                })
        print(f"[sweep] param={label} done in {time.time()-t0:.1f}s", flush=True)

    df = pd.DataFrame(rows)
    out = RESULTS / "rf_param_sweep.csv"
    df.to_csv(out, index=False)
    print(f"\n[sweep] wrote {out}  rows={len(df)}", flush=True)
    return df


# ============================================================================
# TASK 2 — 5m / 15m PVSRA panel
# ============================================================================

def resample_to_tf(panel_1s: pd.DataFrame, tf_sec: int) -> pd.DataFrame:
    """Resample 1s bars to tf_sec bars per asset.
       Returns: asset, bar_start_us, open, high, low, close, volume, taker_buy_base.
       bar_start_us is the floor of the bar (e.g. 5m bar at 12:00 covers [12:00, 12:05)).
       Use only fully-aligned tf_sec windows."""
    tf_us = tf_sec * 1_000_000
    p = panel_1s.copy()
    p["bar_start_us"] = (p["ts_us"] // tf_us) * tf_us
    g = p.groupby(["asset", "bar_start_us"], sort=True)
    agg = g.agg(
        open=("price_open", "first"),
        high=("price_high", "max"),
        low=("price_low", "min"),
        close=("price_close", "last"),
        volume=("volume_traded", "sum"),
        taker_buy_base=("taker_buy_base", "sum"),
        n_bars=("price_close", "size"),
    ).reset_index()
    # drop partial bars at edges (require full tf_sec coverage)
    agg = agg[agg["n_bars"] == tf_sec].copy()
    return agg.drop(columns=["n_bars"])


def compute_pvsra(df: pd.DataFrame) -> pd.DataFrame:
    """PVSRA on already-resampled bars.
       Convention (per Pine indicator):
        - climax bull (lime, +3): vol >= 2.0 * sma(vol,10) OR sv >= rolling_max(sv,10); bull
        - climax bear (red,  -3): same vol cond; bear
        - rising bull (blue, +2): vol >= 1.5 * sma(vol,10) and NOT climax; bull
        - rising bear (violet,-2): same vol; bear
        - absorption (+1): climax vol AND spread < 0.5 * avg spread (rarely fires in crypto)
        - regular (0): otherwise
       Integer encoding matches the prompt: 3 / -3 / 2 / -2 / 1 / 0
    """
    out_chunks = []
    for asset, grp in df.groupby("asset", sort=False):
        grp = grp.sort_values("bar_start_us").reset_index(drop=True).copy()
        vol = grp["volume"].fillna(0.0).to_numpy()
        high = grp["high"].to_numpy()
        low  = grp["low"].to_numpy()
        opn  = grp["open"].to_numpy()
        cls  = grp["close"].to_numpy()
        spread = high - low

        vol_s = pd.Series(vol)
        sma_vol_10 = vol_s.rolling(10, min_periods=10).mean().to_numpy()
        sv = spread * vol
        sv_max_10 = pd.Series(sv).rolling(10, min_periods=10).max().to_numpy()
        spread_avg_10 = pd.Series(spread).rolling(10, min_periods=10).mean().to_numpy()

        finite = np.isfinite(sma_vol_10) & np.isfinite(sv_max_10)
        # match Pine: climax = vol >= 2*sma OR sv >= rolling_max(sv,10)
        climax = ((vol >= 2.0 * sma_vol_10) | (sv >= sv_max_10)) & finite
        rising = (vol >= 1.5 * sma_vol_10) & (~climax) & np.isfinite(sma_vol_10)
        absorption = climax & np.isfinite(spread_avg_10) & (spread < 0.5 * spread_avg_10)
        # absorption is its own class (+1)

        bull = cls > opn
        bear = cls < opn

        pv = np.zeros(len(grp), dtype=np.int8)
        # priority: climax > absorption-overlay > rising > regular
        pv[climax & bull] = 3
        pv[climax & bear] = -3
        # rising override only where not climax
        pv[rising & bull] = 2
        pv[rising & bear] = -2
        # absorption overrides climax bars when spread is tight
        pv[absorption] = 1

        grp["spread"] = spread
        grp["sv"]     = sv
        grp["sma_vol_10"] = sma_vol_10
        grp["sv_max_10"]  = sv_max_10
        grp["pvsra"]      = pv
        out_chunks.append(grp)
    out = pd.concat(out_chunks, ignore_index=True)
    return out


def build_pvsra_panels(panel_1s: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    print("\n=== TASK 2 — PVSRA 5m / 15m panels ===\n", flush=True)

    print("[pvsra] resampling to 5m ...", flush=True); t = time.time()
    bars5 = resample_to_tf(panel_1s, 300)
    print(f"[pvsra]   5m bars: {len(bars5):,} in {time.time()-t:.1f}s", flush=True)

    print("[pvsra] resampling to 15m ...", flush=True); t = time.time()
    bars15 = resample_to_tf(panel_1s, 900)
    print(f"[pvsra]   15m bars: {len(bars15):,} in {time.time()-t:.1f}s", flush=True)

    print("[pvsra] computing 5m PVSRA ...", flush=True); t = time.time()
    pv5 = compute_pvsra(bars5).rename(columns={"pvsra": "pvsra_5m_int"})
    out5 = RESULTS / "pvsra_5m.parquet"
    pv5.to_parquet(out5, compression="zstd", index=False)
    print(f"[pvsra]   wrote {out5}  rows={len(pv5):,} ({time.time()-t:.1f}s)", flush=True)

    print("[pvsra] computing 15m PVSRA ...", flush=True); t = time.time()
    pv15 = compute_pvsra(bars15).rename(columns={"pvsra": "pvsra_15m_int"})
    out15 = RESULTS / "pvsra_15m.parquet"
    pv15.to_parquet(out15, compression="zstd", index=False)
    print(f"[pvsra]   wrote {out15}  rows={len(pv15):,} ({time.time()-t:.1f}s)", flush=True)

    return pv5, pv15


# ============================================================================
# TASK 3 — Sample PVSRA onto per-fire parquets
# ============================================================================

def _bars_since_flag(arr: np.ndarray) -> np.ndarray:
    """Bars since most recent True. -1 before first True; 0 at True bar; else increment."""
    out = np.empty(len(arr), dtype=np.int32)
    cnt = -1
    for i in range(len(arr)):
        if arr[i]:
            cnt = 0
        elif cnt >= 0:
            cnt += 1
        out[i] = cnt
    return out


def join_pvsra_onto_fires(pv: pd.DataFrame, tf_us: int, tf_label: str,
                           fires_path: Path, out_path: Path) -> None:
    """Causal join: for each fire at fire_us, find last fully-closed tf bar
       (bar_start_us + tf_us <= fire_us)."""
    print(f"\n[join-{tf_label}] {fires_path.name} -> {out_path.name}", flush=True)
    if not fires_path.exists():
        print(f"[join-{tf_label}] SKIP missing {fires_path}", flush=True)
        return

    fires = pd.read_parquet(fires_path)
    pv_col = f"pvsra_{tf_label}_int"  # 5m / 15m

    pieces = []
    for asset, fg in fires.groupby("asset", sort=False):
        rg = pv[pv["asset"] == asset].copy()
        if rg.empty:
            print(f"[join-{tf_label}]   no PVSRA for asset={asset}", flush=True)
            continue
        rg = rg.sort_values("bar_start_us").reset_index(drop=True)
        # bars_since features computed in panel order
        rg[f"bars_since_pvsra_{tf_label}_climax_bull"] = _bars_since_flag(rg[pv_col].to_numpy() == 3)
        rg[f"bars_since_pvsra_{tf_label}_climax_bear"] = _bars_since_flag(rg[pv_col].to_numpy() == -3)
        # key = bar_start + tf_us  (bar closes at this instant; we want first bar whose close <= fire_us)
        rg["key_us"] = rg["bar_start_us"] + tf_us

        keep = ["key_us", "bar_start_us", pv_col,
                f"bars_since_pvsra_{tf_label}_climax_bull",
                f"bars_since_pvsra_{tf_label}_climax_bear",
                "volume", "spread", "sv", "sma_vol_10"]
        rg = rg[keep].sort_values("key_us").reset_index(drop=True)
        rg = rg.rename(columns={
            pv_col: f"pvsra_{tf_label}",
            "bar_start_us": f"pvsra_{tf_label}_bar_start_us",
            "volume": f"pvsra_{tf_label}_bar_volume",
            "spread": f"pvsra_{tf_label}_bar_spread",
            "sv": f"pvsra_{tf_label}_bar_sv",
            "sma_vol_10": f"pvsra_{tf_label}_sma_vol_10",
        })

        fg = fg.sort_values("fire_us").reset_index(drop=True)
        merged = pd.merge_asof(
            fg, rg,
            left_on="fire_us", right_on="key_us",
            direction="backward",
            tolerance=tf_us * 2,  # 2 bars worth
        )
        merged = merged.drop(columns=["key_us"], errors="ignore")
        # derived: bull / climax_bull flags
        pcol = f"pvsra_{tf_label}"
        merged[f"pvsra_{tf_label}_bull"]        = (merged[pcol] > 0).astype("Int8")
        merged[f"pvsra_{tf_label}_climax_bull"] = (merged[pcol] == 3).astype("Int8")
        merged[f"pvsra_{tf_label}_climax_bear"] = (merged[pcol] == -3).astype("Int8")
        pieces.append(merged)

    out = pd.concat(pieces, ignore_index=True)
    cov = out[f"pvsra_{tf_label}"].notna().mean() * 100
    out.to_parquet(out_path, compression="zstd", index=False)
    print(f"[join-{tf_label}]   wrote {out_path.name} rows={len(out):,} "
          f"cov={cov:.1f}%  size={os.path.getsize(out_path)/1e6:.1f}MB", flush=True)


# ============================================================================
# TASK 4 — Standalone PVSRA-5m direction signal test on S1.5
# ============================================================================

def task4_standalone_pvsra_signal(s15_pvsra_path: Path) -> pd.DataFrame:
    print("\n=== TASK 4 — standalone PVSRA-5m direction signal on S1.5 ===\n", flush=True)
    df = pd.read_parquet(s15_pvsra_path)
    # Rule: bet UP if last 5m bar bull (>0); DOWN if bear (<0); skip otherwise.
    df["pvsra_pick"] = np.where(df["pvsra_5m"] > 0, "UP",
                          np.where(df["pvsra_5m"] < 0, "DOWN", None))

    # Per (asset, offset) report
    rows_signal = []
    rows_baseline = []
    for (asset, off), grp in df.groupby(["asset", "fire_offset_s"], sort=True):
        # baseline = default direction picker
        n_base = len(grp)
        wr_base = grp["won"].mean() * 100
        pnl_base_mean = grp["pnl_legacy_usd"].mean() if "pnl_legacy_usd" in grp.columns else float("nan")
        pnl_base_sum  = grp["pnl_legacy_usd"].sum()  if "pnl_legacy_usd" in grp.columns else float("nan")

        # signal: only fires where pvsra_pick is non-null AND matches existing direction (i.e.
        # we'd take the bet if PVSRA agrees). But spec says "bet UP if last 5m bar was climax_bull
        # or rising_bull; DOWN if climax_bear or rising_bear; skip otherwise". So the signal CHOOSES
        # the direction; the *outcome* for that direction is what matters.
        # outcome is fixed by market — if pvsra says UP and actual outcome was UP, that's a win.
        sig = grp.dropna(subset=["pvsra_pick"]).copy()
        if len(sig) == 0:
            continue
        # outcome is 'Up'/'Down' Title Case; pvsra_pick is 'UP'/'DOWN' upper
        sig["pvsra_won"] = (sig["pvsra_pick"].astype(str).str.upper() ==
                              sig["outcome"].astype(str).str.upper())
        # PnL: we need entry_vwap and direction. The per-fire parquet has entry_vwap (price paid
        # for OUTCOME=='direction'). If pvsra picks the same side as the original direction column,
        # we can reuse pnl_legacy_usd. If pvsra picks the OPPOSITE side, we have to invert: a $1 bet
        # on the other side at price (1 - entry_vwap), payout 1 if pvsra_pick was correct.
        # LegacyConfig fee: 2% on profit only (winning leg).
        # Compute synthetic pnl per $1 stake:
        ev = sig["entry_vwap"].to_numpy()
        # If we follow the original direction's price as a proxy: when pvsra_pick == direction,
        # cost_per_share = ev. Else cost_per_share = 1 - ev.
        same_side = (sig["pvsra_pick"].astype(str).str.upper() ==
                       sig["direction"].astype(str).str.upper()).to_numpy()
        cost = np.where(same_side, ev, 1.0 - ev)
        # shares for $1 stake = 1/cost
        shares = 1.0 / np.where(cost > 0, cost, np.nan)
        won = sig["pvsra_won"].to_numpy()
        gross = np.where(won, shares, 0.0)  # payout 1 per share if won
        gross_profit = np.maximum(gross - 1.0, 0.0)
        fee = gross_profit * 0.02
        pnl = (gross - 1.0) - fee
        sig["pnl_pvsra_usd"] = pnl

        rows_signal.append({
            "asset": asset, "offset": int(off),
            "n": int(len(sig)),
            "wr": round(sig["pvsra_won"].mean() * 100, 3),
            "mean_pnl": round(float(sig["pnl_pvsra_usd"].mean()), 5),
            "sum_pnl_28d": round(float(sig["pnl_pvsra_usd"].sum()), 4),
        })
        rows_baseline.append({
            "asset": asset, "offset": int(off),
            "n_base": int(n_base),
            "wr_base": round(wr_base, 3),
            "mean_pnl_base": round(float(pnl_base_mean), 5),
            "sum_pnl_base_28d": round(float(pnl_base_sum), 4),
        })

    out_sig = pd.DataFrame(rows_signal)
    out_base = pd.DataFrame(rows_baseline)
    out = out_sig.merge(out_base, on=["asset", "offset"], how="outer").sort_values(["asset", "offset"])
    out_csv = RESULTS / "pvsra_5m_standalone_signal.csv"
    out.to_csv(out_csv, index=False)
    print(f"[task4] wrote {out_csv}", flush=True)
    print(out.to_string(index=False), flush=True)
    return out


# ============================================================================
# MAIN
# ============================================================================

def main():
    t_global = time.time()

    # === Step A: load 1s panel ===
    panel_1s = load_1s_panel()

    # === TASK 1: RF sweep ===
    fires_specs = [
        ("S1.5", RESULTS / "s15_with_rf.parquet"),
        ("S6",   RESULTS / "s6_with_rf.parquet"),
        ("V15m", RESULTS / "v15m_with_ta_markov_rf.parquet"),
    ]
    sweep_df = rf_sweep(panel_1s, fires_specs)

    # === TASK 2: PVSRA 5m/15m panels ===
    pv5, pv15 = build_pvsra_panels(panel_1s)

    # === TASK 3: join PVSRA onto per-fire ===
    print("\n=== TASK 3 — sample PVSRA onto per-fire parquets ===\n", flush=True)
    join_pvsra_onto_fires(pv5, 300_000_000, "5m",
                            RESULTS / "s15_with_rf.parquet",
                            RESULTS / "s15_with_pvsra5m.parquet")
    join_pvsra_onto_fires(pv5, 300_000_000, "5m",
                            RESULTS / "s6_with_rf.parquet",
                            RESULTS / "s6_with_pvsra5m.parquet")
    join_pvsra_onto_fires(pv15, 900_000_000, "15m",
                            RESULTS / "v15m_with_ta_markov_rf.parquet",
                            RESULTS / "v15m_with_pvsra15m.parquet")

    # === TASK 4: standalone PVSRA-5m direction signal on S1.5 ===
    task4_signal = task4_standalone_pvsra_signal(RESULTS / "s15_with_pvsra5m.parquet")

    print(f"\n[done] total {time.time()-t_global:.1f}s", flush=True)
    return sweep_df, pv5, pv15, task4_signal


if __name__ == "__main__":
    main()
