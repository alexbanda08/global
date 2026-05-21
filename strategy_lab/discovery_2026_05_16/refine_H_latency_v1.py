"""
Re-test V1 (baseline H_refined, vwap [0.3, 0.7], no time/dow filter) with
realistic latency. If V1 also collapses, the entire H_refined discovery is
a microsecond-lookahead artifact.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "discovery_2026_05_16"))

from load import load_resolutions, load_klines_asof, load_orderbook_l25_streaming, asof_strict
from harness import SPREAD_FILTER, NOTIONAL, FEE_RATE, walk_asks, get_book_at

DIR = Path(__file__).resolve().parent
ANCHOR_S = 300
HORIZON_S = 600
THR = 0.08
N_PER_ASSET = 1500


def fair_p_up(ret, sigma_norm):
    if not np.isfinite(ret) or sigma_norm <= 0: return 0.5
    z = ret / sigma_norm
    p = 0.5 + 0.5 * np.tanh(2.0 * z)
    return float(np.clip(p, 0.10, 0.90))


def compute_sigma_30min(end_us_arr, prices_arr, fire_us):
    idx_end = int(np.searchsorted(end_us_arr, fire_us, side="right") - 1)
    if idx_end < 30: return 0.0
    sl = prices_arr[idx_end - 29 : idx_end + 1]
    if len(sl) < 5: return 0.0
    rets = np.diff(np.log(sl))
    rets = rets[np.isfinite(rets)]
    return float(np.std(rets)) if len(rets) >= 5 else 0.0


def run(latency_us, vwap_lo, vwap_hi, apply_time_filter):
    res = load_resolutions(timeframes=["15m"])
    rows = []
    for asset in ["BTC", "ETH"]:
        sub = res[res.ticker == asset].sort_values("slot_start_us").copy()
        if len(sub) > N_PER_ASSET:
            idx = np.linspace(0, len(sub)-1, N_PER_ASSET).astype(int)
            sub = sub.iloc[idx]
        if apply_time_filter:
            sub["ts"] = pd.to_datetime(sub.slot_start_us, unit="us", utc=True)
            sub = sub[(sub.ts.dt.hour >= 6) & (sub.ts.dt.hour < 24) & (sub.ts.dt.dayofweek < 5)]
        end_us, prices = load_klines_asof(asset, "binance-spot-ws", "1MIN")
        SPREAD = SPREAD_FILTER[asset]
        sub["entry_us"] = sub.slot_end_us - ANCHOR_S * 1_000_000

        slugs_list = list(sub.slug.unique())
        books = {}
        for i in range(0, len(slugs_list), 500):
            chunk = set(slugs_list[i:i+500])
            books.update(load_orderbook_l25_streaming(asset.lower(), slugs=chunk, subsample_1hz=True))

        for _, r in sub.iterrows():
            entry_us = int(r["entry_us"])
            slot_start_us = int(r["slot_start_us"])
            entry_us_kline = entry_us - latency_us
            obs_lo_us = max(slot_start_us, entry_us_kline - HORIZON_S * 1_000_000)
            p_now = asof_strict(end_us, prices, entry_us_kline)
            p_then = asof_strict(end_us, prices, obs_lo_us)
            if not (np.isfinite(p_now) and np.isfinite(p_then) and p_then > 0): continue
            ret_obs = p_now / p_then - 1.0
            sigma = compute_sigma_30min(end_us, prices, entry_us_kline)
            fair_p = fair_p_up(ret_obs, sigma)
            snap_up = get_book_at(books, r["slug"], "Up", entry_us)
            if snap_up is None: continue
            ap_up, asz_up, bp_up, bsz_up = snap_up
            ap0_up = float(ap_up[0]) if np.isfinite(ap_up[0]) else np.nan
            bp0_up = float(bp_up[0]) if np.isfinite(bp_up[0]) else np.nan
            if not (np.isfinite(ap0_up) and np.isfinite(bp0_up)): continue
            if (ap0_up - bp0_up) > SPREAD: continue
            p_clob_up = (ap0_up + bp0_up) / 2
            edge = fair_p - p_clob_up
            if abs(edge) < THR: continue
            if edge > 0:
                signal = "UP"; ap, asz = list(ap_up), list(asz_up)
            else:
                signal = "DOWN"
                snap_dn = get_book_at(books, r["slug"], "Down", entry_us)
                if snap_dn is None: continue
                ap_dn, asz_dn, _, _ = snap_dn
                ap, asz = list(ap_dn), list(asz_dn)
            vwap, shares, spent, under = walk_asks(ap, asz, NOTIONAL)
            if under or not np.isfinite(vwap) or shares <= 0: continue
            if not (vwap_lo < vwap < vwap_hi): continue
            won = int(signal == r["outcome"].upper())
            profit_raw = shares * (won - vwap)
            fee = max(profit_raw, 0.0) * FEE_RATE
            pnl = profit_raw - fee
            rows.append(dict(asset=asset, slug=r["slug"], outcome=r["outcome"],
                             signal=signal, vwap=vwap, won=won, pnl=pnl))
    return pd.DataFrame(rows)


def report(df, label):
    if len(df) == 0:
        print(f"{label}: 0 trades"); return
    n = len(df); hit = df.won.mean(); pnl = df.pnl.sum(); ppt = df.pnl.mean()
    pnls = []
    for _ in range(1000):
        flips = np.random.choice([1,-1], size=n)
        pnls.append((df.pnl.values * flips).sum())
    pv = (np.array(pnls) >= pnl).mean()
    boot = []
    for _ in range(2000):
        idx = np.random.choice(n, size=n, replace=True)
        boot.append(df.pnl.values[idx].mean())
    boot = np.array(boot)
    ci_lo, ci_hi = np.percentile(boot, 2.5), np.percentile(boot, 97.5)
    print(f"  {label:<40s}  n={n:>4d}  hit={hit:.4f}  pnl=${pnl:>+7.0f}  ppt=${ppt:>+5.2f}  p={pv:.3f}  CI=[${ci_lo:+.2f}, ${ci_hi:+.2f}]")


def main():
    import time
    np.random.seed(42)

    # Two variants × three latencies
    variants = [
        ("V1 (vwap [0.3,0.7], no time)", 0.30, 0.70, False),
        ("V2 (vwap [0.4,0.6], +active+weekday)", 0.40, 0.60, True),
    ]
    latencies = [0, 100_000, 1_000_000]   # 0, 100ms, 1s

    for vname, vlo, vhi, ft in variants:
        print(f"\n=== {vname} ===")
        for lat in latencies:
            t0 = time.time()
            df = run(lat, vlo, vhi, ft)
            elapsed = time.time() - t0
            label = f"latency={lat/1e6:>6.3f}s"
            report(df, label)


if __name__ == "__main__":
    main()
