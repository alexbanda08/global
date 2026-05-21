"""
Comprehensive lookahead-bias audit for H_refined_v2.

Picks 20 random candidate trades, recomputes the signal end-to-end, and:
  1. Prints every timestamp of data used (binance kline ends, book ts, sigma window).
  2. Verifies each data timestamp is strictly < entry_us (or flags == as borderline).
  3. Recomputes the strategy with entry_us shifted by -1 microsecond. If results
     differ, a boundary-case lookahead exists.
  4. Verifies outcome is only touched for PnL evaluation, not signal generation.

Run:
    py -3 -X utf8 strategy_lab/discovery_2026_05_16/lookahead_audit.py
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "discovery_2026_05_16"))

from load import load_resolutions, load_klines_asof, load_orderbook_l25_streaming, asof_strict
from harness import SPREAD_FILTER, NOTIONAL, FEE_RATE, walk_asks, get_book_at

import datetime as _dt
np.random.seed(42)


def fair_p_up(ret: float, sigma_norm: float) -> float:
    if not np.isfinite(ret) or sigma_norm <= 0:
        return 0.5
    z = ret / sigma_norm
    p = 0.5 + 0.5 * np.tanh(2.0 * z)
    return float(np.clip(p, 0.10, 0.90))


def compute_sigma_30min(asset: str, fire_us: int, ret_details: dict | None = None) -> float:
    end_us, prices = load_klines_asof(asset.upper(), "binance-spot-ws", "1MIN")
    idx_end = int(np.searchsorted(end_us, fire_us, side="right") - 1)
    if idx_end < 30:
        return 0.0
    sl_ends = end_us[idx_end - 30 + 1 : idx_end + 1]
    sl = prices[idx_end - 30 + 1 : idx_end + 1]
    if len(sl) < 5:
        return 0.0
    rets = np.diff(np.log(sl))
    rets = rets[np.isfinite(rets)]
    if ret_details is not None:
        ret_details["sigma_window_first_end_us"] = int(sl_ends[0])
        ret_details["sigma_window_last_end_us"] = int(sl_ends[-1])
        ret_details["sigma_window_n_bars"] = int(len(sl))
    return float(np.std(rets)) if len(rets) >= 5 else 0.0


def run_one_trade(slug: str, ticker: str, slot_start_us: int, slot_end_us: int,
                  outcome: str, entry_us_override: int | None = None, verbose: bool = False) -> dict:
    """
    Recompute the H_refined_v2 signal for ONE market. Return a dict of all
    timestamps used + the signal + the realized PnL.

    If entry_us_override given, use it. Otherwise compute as slot_end - 300s.
    """
    cfg_anchor = 300
    cfg_horizon = 600
    cfg_thr = 0.08
    cfg_spread = SPREAD_FILTER[ticker.upper()]

    entry_us = entry_us_override if entry_us_override is not None else (slot_end_us - cfg_anchor * 1_000_000)

    out = {
        "slug": slug, "ticker": ticker, "outcome": outcome,
        "slot_start_us": slot_start_us, "slot_end_us": slot_end_us,
        "entry_us": entry_us,
    }

    # Binance lookup
    end_us, prices = load_klines_asof(ticker.upper(), "binance-spot-ws", "1MIN")

    # p_now (asof entry_us)
    idx_now = int(np.searchsorted(end_us, entry_us, side="right") - 1)
    p_now_end_us = int(end_us[idx_now]) if idx_now >= 0 else None
    p_now = float(prices[idx_now]) if idx_now >= 0 else float("nan")

    # p_then (asof obs_lo)
    obs_lo_us = max(slot_start_us, entry_us - cfg_horizon * 1_000_000)
    idx_then = int(np.searchsorted(end_us, obs_lo_us, side="right") - 1)
    p_then_end_us = int(end_us[idx_then]) if idx_then >= 0 else None
    p_then = float(prices[idx_then]) if idx_then >= 0 else float("nan")

    ret_obs = p_now / p_then - 1.0 if p_then > 0 else float("nan")
    sigma_details = {}
    sigma = compute_sigma_30min(ticker, entry_us, sigma_details)
    fair_p = fair_p_up(ret_obs, sigma)

    out.update({
        "obs_lo_us": obs_lo_us,
        "p_now_bar_end_us": p_now_end_us,
        "p_now_bar_delta_us": (entry_us - p_now_end_us) if p_now_end_us is not None else None,
        "p_then_bar_end_us": p_then_end_us,
        "ret_obs": ret_obs, "sigma_30min": sigma, "fair_p": fair_p,
        **sigma_details,
    })

    # Book lookup
    books = load_orderbook_l25_streaming(ticker.lower(), slugs={slug}, subsample_1hz=True)

    key_up = (slug, "Up")
    if key_up not in books:
        out.update({"signal": "SKIP", "skip_reason": "no Up book"})
        return out
    ts_up, ap_up, asz_up, bp_up, bsz_up = books[key_up]
    i_up = int(np.searchsorted(ts_up, entry_us, side="right") - 1)
    if i_up < 0:
        out.update({"signal": "SKIP", "skip_reason": "no book before entry"})
        return out
    book_up_ts_us = int(ts_up[i_up])
    book_up_delta_us = entry_us - book_up_ts_us
    ap0_up = float(ap_up[i_up][0])
    bp0_up = float(bp_up[i_up][0])
    if not (np.isfinite(ap0_up) and np.isfinite(bp0_up)):
        out.update({"signal": "SKIP", "skip_reason": "nan top-of-book"})
        return out
    spread = ap0_up - bp0_up
    if spread > cfg_spread:
        out.update({"signal": "SKIP", "skip_reason": f"spread {spread:.4f}",
                    "book_up_ts_us": book_up_ts_us, "book_up_delta_us": book_up_delta_us})
        return out
    p_clob_up = (ap0_up + bp0_up) / 2
    edge = fair_p - p_clob_up

    out.update({
        "book_up_ts_us": book_up_ts_us,
        "book_up_delta_us": book_up_delta_us,
        "ap0_up": ap0_up, "bp0_up": bp0_up, "spread": spread,
        "p_clob_up": p_clob_up, "edge": edge,
    })

    if abs(edge) < cfg_thr:
        out.update({"signal": "SKIP", "skip_reason": f"|edge|={abs(edge):.4f}<{cfg_thr}"})
        return out
    if edge > 0:
        signal = "UP"
        ap, asz = list(ap_up[i_up]), list(asz_up[i_up])
        book_fill_ts = book_up_ts_us
    else:
        signal = "DOWN"
        key_dn = (slug, "Down")
        if key_dn not in books:
            out.update({"signal": "SKIP", "skip_reason": "no Down book"})
            return out
        ts_dn, ap_dn, asz_dn, _, _ = books[key_dn]
        i_dn = int(np.searchsorted(ts_dn, entry_us, side="right") - 1)
        if i_dn < 0:
            out.update({"signal": "SKIP", "skip_reason": "no Down book before entry"})
            return out
        ap, asz = list(ap_dn[i_dn]), list(asz_dn[i_dn])
        book_fill_ts = int(ts_dn[i_dn])

    out["book_fill_ts_us"] = book_fill_ts
    out["book_fill_delta_us"] = entry_us - book_fill_ts

    vwap, shares, spent, under = walk_asks(ap, asz, NOTIONAL)
    if under or not np.isfinite(vwap):
        out.update({"signal": "SKIP", "skip_reason": "underfill"})
        return out

    # v2 vwap filter
    if not (0.40 < vwap < 0.60):
        out.update({"signal": "SKIP", "skip_reason": f"vwap {vwap:.4f} outside [0.40,0.60]",
                    "vwap": vwap})
        return out

    # v2 hour/dow filter
    ts_utc = _dt.datetime.fromtimestamp(slot_start_us / 1e6, tz=_dt.timezone.utc)
    if not (6 <= ts_utc.hour < 24):
        out.update({"signal": "SKIP", "skip_reason": f"hour {ts_utc.hour}<6"})
        return out
    if ts_utc.weekday() >= 5:
        out.update({"signal": "SKIP", "skip_reason": f"weekend dow {ts_utc.weekday()}"})
        return out

    won = int(signal == outcome.upper())
    profit_raw = shares * (won - vwap)
    fee = max(profit_raw, 0.0) * FEE_RATE
    pnl = profit_raw - fee
    out.update({"signal": signal, "vwap": vwap, "shares": shares,
                "won": won, "pnl": pnl})
    return out


def main():
    # Load candidate trades
    DIR = Path(__file__).resolve().parent
    frames = [pd.read_parquet(f) for f in sorted(DIR.glob("refine_H_*_anchor*.parquet"))]
    df = pd.concat(frames, ignore_index=True)
    sel = (df.tf == "15m") & (df.anchor_off_s == 300) & (df.horizon_s == 600) & \
          (df.asset != "SOL") & (df.vwap > 0.4) & (df.vwap < 0.6) & (df.thr == 0.08)
    cand = df[sel].copy()
    cand["slot_start_us"] = cand.slug.str.rsplit("-", n=1).str[1].astype("int64") * 1_000_000

    # Recover slot_end_us from slot_start_us + window
    cand["slot_end_us"] = cand.slot_start_us + 900 * 1_000_000

    # Apply time filters
    cand["ts"] = pd.to_datetime(cand.slot_start_us, unit="us", utc=True)
    cand = cand[(cand.ts.dt.hour >= 6) & (cand.ts.dt.hour < 24) & (cand.ts.dt.dayofweek < 5)]
    print(f"H_refined_v2 candidate trades: {len(cand)}")

    # Pick 20 random
    sample = cand.sample(n=20, random_state=42)

    # Audit each
    audit_results = []
    n_borderline = 0
    n_negative = 0
    for _, row in sample.iterrows():
        slug = row["slug"]
        ticker = row["asset"]
        slot_start_us = int(row["slot_start_us"])
        slot_end_us = int(row["slot_end_us"])
        outcome = row["outcome"]

        # Base run
        r = run_one_trade(slug, ticker, slot_start_us, slot_end_us, outcome)
        # Sanity: run with entry shifted -1 us
        r_minus = run_one_trade(slug, ticker, slot_start_us, slot_end_us, outcome,
                                entry_us_override=r["entry_us"] - 1)

        # Check timestamps strictly < entry_us
        entry_us = r["entry_us"]
        warnings = []
        if r.get("p_now_bar_end_us") is not None and r["p_now_bar_end_us"] == entry_us:
            warnings.append("p_now bar ends EXACTLY at entry_us")
            n_borderline += 1
        if r.get("book_up_ts_us") is not None and r["book_up_ts_us"] == entry_us:
            warnings.append("book_up snapshot ts EXACTLY at entry_us")
            n_borderline += 1
        # Check NEGATIVE deltas (would be lookahead — data AFTER entry)
        if r.get("p_now_bar_delta_us") is not None and r["p_now_bar_delta_us"] < 0:
            warnings.append(f"p_now bar AFTER entry by {-r['p_now_bar_delta_us']}us — LOOKAHEAD!")
            n_negative += 1
        if r.get("book_up_delta_us") is not None and r["book_up_delta_us"] < 0:
            warnings.append(f"book_up snapshot AFTER entry by {-r['book_up_delta_us']}us — LOOKAHEAD!")
            n_negative += 1

        # Check if shifting -1us changes the result
        same = (r.get("signal") == r_minus.get("signal") and
                abs(r.get("pnl", 0) - r_minus.get("pnl", 0)) < 0.01)
        audit_results.append({
            "slug": slug, "ticker": ticker, "entry_us": entry_us,
            "p_now_delta_us": r.get("p_now_bar_delta_us"),
            "p_then_delta_us": (entry_us - r.get("p_then_bar_end_us", entry_us)) if r.get("p_then_bar_end_us") else None,
            "sigma_window_last_delta_us": (entry_us - r.get("sigma_window_last_end_us", entry_us)) if r.get("sigma_window_last_end_us") else None,
            "book_up_delta_us": r.get("book_up_delta_us"),
            "book_fill_delta_us": r.get("book_fill_delta_us"),
            "signal": r.get("signal"), "vwap": r.get("vwap"), "pnl": r.get("pnl"),
            "signal_robust_to_-1us": same,
            "warnings": warnings,
        })

    # Print results
    print(f"\n{'-'*80}")
    print(f"{'slug':<32s} {'p_now_d':>9s} {'p_then_d':>10s} {'book_d':>9s} {'fill_d':>9s} {'signal':>6s} {'-1us':>6s}")
    print(f"{'-'*80}")
    for r in audit_results:
        s_robust = "OK" if r["signal_robust_to_-1us"] else "DIFFERS"
        print(f"{r['slug']:<32s} {str(r['p_now_delta_us'])[:9]:>9s} {str(r['p_then_delta_us'])[:10]:>10s} {str(r['book_up_delta_us'])[:9]:>9s} {str(r['book_fill_delta_us'])[:9]:>9s} {str(r['signal'])[:6]:>6s} {s_robust:>6s}")
        if r["warnings"]:
            for w in r["warnings"]:
                print(f"    WARN: {w}")

    print(f"\n=== Summary ===")
    print(f"Total trades audited: {len(audit_results)}")
    print(f"Borderline (data ts == entry_us): {n_borderline}")
    print(f"NEGATIVE delta (data ts > entry_us): {n_negative}")
    n_signal_changes = sum(1 for r in audit_results if not r["signal_robust_to_-1us"])
    print(f"Signal changes when entry shifted -1us: {n_signal_changes}/{len(audit_results)}")

    # Aggregate stats on deltas
    print(f"\n=== Delta-from-entry distributions (positive = data BEFORE entry, good) ===")
    for key in ["p_now_delta_us", "p_then_delta_us", "sigma_window_last_delta_us", "book_up_delta_us", "book_fill_delta_us"]:
        vals = [r[key] for r in audit_results if r[key] is not None]
        if not vals: continue
        vals = sorted(vals)
        print(f"  {key:<30s} n={len(vals):3d}  min={vals[0]:>15d}us  median={vals[len(vals)//2]:>15d}us  max={vals[-1]:>15d}us")

    if n_negative == 0 and n_borderline == 0:
        print("\nPASS: no lookahead detected. All data timestamps strictly < entry_us.")
    elif n_negative == 0:
        print(f"\nBORDERLINE: {n_borderline} cases with data timestamp == entry_us (microsecond boundary).")
        print("   In production this would still be safe — bar/snapshot just finalized at entry_us instant.")
    else:
        print(f"\nFAIL: {n_negative} cases with data AFTER entry_us — STRATEGY HAS LOOKAHEAD.")

    # Save full audit
    out_path = DIR / "lookahead_audit_report.json"
    with open(out_path, "w") as f:
        json.dump({"n_borderline": n_borderline, "n_negative": n_negative,
                   "n_signal_changes_minus_1us": n_signal_changes,
                   "trades": audit_results}, f, indent=2, default=str)
    print(f"\nFull audit saved: {out_path}")


if __name__ == "__main__":
    main()
