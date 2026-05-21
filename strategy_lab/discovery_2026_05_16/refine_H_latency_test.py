"""
Re-evaluate H_refined_v2 with realistic WebSocket latency.

Critical lookahead concern: original backtest uses asof_strict which includes
the 1MIN bar ending EXACTLY at entry_us. In production, that bar's close
arrives ~10-100ms after entry_us via WebSocket. So including it is a
microsecond-to-100ms-level lookahead.

Test: shift entry_us by LATENCY_US when computing asof on the kline (binance)
data. Book snapshots stay at entry_us (their median delta is ~1s already).

Latencies tested:
   0us       (original — has the boundary issue)
   1us       (excludes bar closing AT entry_us)
   50_000us  (50ms — typical WS forwarding latency)
   100_000us (100ms — conservative)
   500_000us (500ms — paranoid)
   60_000_000us (60s — full minute back; excludes the in-progress minute entirely)
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import datetime as _dt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "discovery_2026_05_16"))

from load import load_resolutions, load_klines_asof, load_orderbook_l25_streaming, asof_strict
from harness import SPREAD_FILTER, NOTIONAL, FEE_RATE, walk_asks, get_book_at

DIR = Path(__file__).resolve().parent
np.random.seed(42)

ASSETS = ["BTC", "ETH"]
ANCHOR_S = 300
HORIZON_S = 600
THR = 0.08
VWAP_LO, VWAP_HI = 0.40, 0.60
N_PER_ASSET = 1500

# Latencies to test (microseconds)
LATENCIES_US = [0, 1, 50_000, 100_000, 500_000, 1_000_000, 60_000_000]


def fair_p_up(ret: float, sigma_norm: float) -> float:
    if not np.isfinite(ret) or sigma_norm <= 0:
        return 0.5
    z = ret / sigma_norm
    p = 0.5 + 0.5 * np.tanh(2.0 * z)
    return float(np.clip(p, 0.10, 0.90))


def compute_sigma_30min(end_us_arr, prices_arr, fire_us):
    idx_end = int(np.searchsorted(end_us_arr, fire_us, side="right") - 1)
    if idx_end < 30:
        return 0.0
    sl = prices_arr[idx_end - 29 : idx_end + 1]
    if len(sl) < 5:
        return 0.0
    rets = np.diff(np.log(sl))
    rets = rets[np.isfinite(rets)]
    return float(np.std(rets)) if len(rets) >= 5 else 0.0


def run_with_latency(latency_us: int):
    """Run the full candidate cell with kline asof shifted by latency_us."""
    res = load_resolutions(timeframes=["15m"])
    rows = []
    for asset in ASSETS:
        sub = res[res.ticker == asset].sort_values("slot_start_us").copy()
        if len(sub) > N_PER_ASSET:
            idx = np.linspace(0, len(sub) - 1, N_PER_ASSET).astype(int)
            sub = sub.iloc[idx]

        end_us, prices = load_klines_asof(asset, "binance-spot-ws", "1MIN")
        SPREAD = SPREAD_FILTER[asset]

        # Apply time/dow filter early (compound v2)
        sub["ts"] = pd.to_datetime(sub.slot_start_us, unit="us", utc=True)
        sub = sub[(sub.ts.dt.hour >= 6) & (sub.ts.dt.hour < 24) & (sub.ts.dt.dayofweek < 5)]
        sub["entry_us"] = sub.slot_end_us - ANCHOR_S * 1_000_000

        # Load L25 books in chunks
        slugs_list = list(sub.slug.unique())
        books: dict = {}
        BATCH = 500
        for i in range(0, len(slugs_list), BATCH):
            chunk = set(slugs_list[i:i+BATCH])
            books.update(load_orderbook_l25_streaming(asset.lower(), slugs=chunk, subsample_1hz=True))

        for _, r in sub.iterrows():
            entry_us = int(r["entry_us"])
            slot_start_us = int(r["slot_start_us"])
            # Apply latency shift to kline lookups only
            entry_us_kline = entry_us - latency_us
            obs_lo_us = max(slot_start_us, entry_us_kline - HORIZON_S * 1_000_000)
            p_now = asof_strict(end_us, prices, entry_us_kline)
            p_then = asof_strict(end_us, prices, obs_lo_us)
            if not (np.isfinite(p_now) and np.isfinite(p_then) and p_then > 0):
                continue
            ret_obs = p_now / p_then - 1.0
            sigma = compute_sigma_30min(end_us, prices, entry_us_kline)
            fair_p = fair_p_up(ret_obs, sigma)

            # Book lookup stays at entry_us (book snapshots are sub-second-fresh anyway)
            snap_up = get_book_at(books, r["slug"], "Up", entry_us)
            if snap_up is None:
                continue
            ap_up, asz_up, bp_up, bsz_up = snap_up
            ap0_up = float(ap_up[0]) if np.isfinite(ap_up[0]) else np.nan
            bp0_up = float(bp_up[0]) if np.isfinite(bp_up[0]) else np.nan
            if not (np.isfinite(ap0_up) and np.isfinite(bp0_up)):
                continue
            if (ap0_up - bp0_up) > SPREAD:
                continue
            p_clob_up = (ap0_up + bp0_up) / 2
            edge = fair_p - p_clob_up
            if abs(edge) < THR:
                continue
            if edge > 0:
                signal = "UP"
                ap, asz = list(ap_up), list(asz_up)
            else:
                signal = "DOWN"
                snap_dn = get_book_at(books, r["slug"], "Down", entry_us)
                if snap_dn is None:
                    continue
                ap_dn, asz_dn, _, _ = snap_dn
                ap, asz = list(ap_dn), list(asz_dn)
            vwap, shares, spent, under = walk_asks(ap, asz, NOTIONAL)
            if under or not np.isfinite(vwap) or shares <= 0:
                continue
            if not (VWAP_LO < vwap < VWAP_HI):
                continue
            won = int(signal == r["outcome"].upper())
            profit_raw = shares * (won - vwap)
            fee = max(profit_raw, 0.0) * FEE_RATE
            pnl = profit_raw - fee
            rows.append(dict(
                latency_us=latency_us, asset=asset, slug=r["slug"],
                outcome=r["outcome"], signal=signal, edge=edge, vwap=vwap,
                won=won, pnl=pnl,
            ))
    return pd.DataFrame(rows)


def main():
    import time
    np.random.seed(42)
    all_results = []
    for lat in LATENCIES_US:
        t0 = time.time()
        print(f"[latency={lat:>10d}us = {lat/1e6:>6.3f}s] running...", flush=True)
        df = run_with_latency(lat)
        print(f"   -> {len(df)} fires in {time.time()-t0:.1f}s")
        all_results.append(df)
    full = pd.concat(all_results, ignore_index=True)
    full.to_parquet(DIR / "refine_H_latency_results.parquet", index=False)

    # Summary
    print()
    print("=" * 100)
    print(f"{'latency':<12s} {'n':>6s} {'hit':>8s} {'pnl':>10s} {'ppt':>8s} {'perm_p':>8s} {'CI_lo':>10s} {'CI_hi':>10s}")
    print("-" * 100)
    for lat, df in zip(LATENCIES_US, all_results):
        if len(df) == 0:
            print(f"{lat:>10d}us  -> 0 trades")
            continue
        n = len(df)
        hit = df.won.mean()
        pnl = df.pnl.sum()
        ppt = df.pnl.mean()
        # Perm test
        pnls = []
        for _ in range(1000):
            flips = np.random.choice([1, -1], size=n)
            pnls.append((df.pnl.values * flips).sum())
        p_val = (np.array(pnls) >= pnl).mean()
        # Bootstrap
        boot = []
        for _ in range(2000):
            idx = np.random.choice(n, size=n, replace=True)
            boot.append(df.pnl.values[idx].mean())
        boot = np.array(boot)
        ci_lo, ci_hi = np.percentile(boot, 2.5), np.percentile(boot, 97.5)
        label = f"{lat/1e6:>7.3f}s"
        print(f"{label:<12s} {n:>6d} {hit:>8.4f} ${pnl:>+8.0f} ${ppt:>+6.2f} {p_val:>8.3f} ${ci_lo:>+8.2f} ${ci_hi:>+8.2f}")
    print("=" * 100)
    print()
    print("Interpretation:")
    print("  latency=0us  is the ORIGINAL backtest. Includes bar closing AT entry_us.")
    print("  latency=1us  excludes that bar (paranoia check).")
    print("  latency=50-500ms is realistic WebSocket forwarding lag.")
    print("  latency=60s   uses ONLY bars that closed >=60s ago (most conservative).")
    print()
    print("If PPT halves going from 0us -> 100ms, the original alpha is mostly lookahead.")
    print("If PPT stable going from 0us -> 500ms, the alpha is real.")


if __name__ == "__main__":
    main()
