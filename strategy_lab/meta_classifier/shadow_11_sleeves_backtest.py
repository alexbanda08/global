"""Backtest the 11 gated shadow sleeves from
`strategy_lab/reports/TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md`.

Approach:
  - Use production fire data from `data/v4/canonical/trading_events_30d.parquet`
    (already production-matched PnL — legacy 2%-on-profit verified 2026-05-22).
  - For each of 11 sleeves: take base-strategy fires, apply the gate stack.
  - Report n / WR / sum_pnl / per-trade vs Section 11 expected ranges.

Gates implemented per spec:
  - HoD-Top8: at_ts UTC hour in HOD_TOP8_BY_CELL[(strategy, cell)]
  - MTF2: ret_15m AND ret_1h match signal direction (log(close@fire / close@(fire-N)))
  - Markov w20 × 5m × vol-adaptive: regime at fire_us == 2 (UP) or 0 (DOWN)
"""
from __future__ import annotations
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "markov_filter"))

from load import load_klines_asof  # noqa: E402
from markov_regime_micro import build_labels_for_asset, regime_at_us, BEAR, BULL  # noqa: E402

EV = ROOT / "data" / "v4" / "canonical" / "trading_events_30d.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "shadow_11_sleeves_backtest.csv"

# Per-spec hot-hour table (Section 2.1)
HOD_TOP8_BY_CELL = {
    ("sniper",  "sol_5m"):  [0, 1, 2, 4, 8, 15, 19, 23],
    ("sniper",  "eth_15m"): [0, 6, 7, 9, 13, 14, 19, 22],
    ("momo",    "btc_15m"): [0, 1, 3, 5, 9, 14, 16, 20],
    ("sniper",  "btc_15m"): [0, 3, 10, 11, 12, 13, 14, 15],
    ("sniper",  "btc_5m"):  [0, 1, 3, 5, 12, 15, 19, 21],
    ("momo_v2", "btc_5m"):  [0, 2, 5, 6, 10, 12, 21, 23],
    ("momo_v2", "btc_15m"): [1, 11, 12, 16, 18, 20, 21, 22],
    ("momo_v2", "sol_5m"):  [4, 5, 6, 8, 10, 12, 14, 17],
    ("momo_v2", "eth_15m"): [0, 5, 8, 12, 16, 17, 20, 22],
    ("momo_v2", "sol_15m"): [1, 2, 5, 12, 13, 16, 17, 21],
    ("sniper",  "eth_5m"):  [0, 2, 11, 13, 14, 17, 20, 21],
}

# Sleeve definitions (id, base_strategy, asset, tf, gate_stack)
SHADOW_SLEEVES = [
    (1,  "poly_updown_sol_5m_sniper_hod",       "sniper",  "SOL", "5m",  ["hod"]),
    (2,  "poly_updown_eth_15m_sniper_hod_m5va", "sniper",  "ETH", "15m", ["hod", "m5va"]),
    (3,  "poly_updown_btc_15m_momo_hod",        "momo",    "BTC", "15m", ["hod"]),
    (4,  "poly_updown_btc_15m_sniper_hod",      "sniper",  "BTC", "15m", ["hod"]),
    (5,  "poly_updown_btc_5m_sniper_hod",       "sniper",  "BTC", "5m",  ["hod"]),
    (6,  "poly_updown_btc_5m_momo_v2_hod_mtf",  "momo_v2", "BTC", "5m",  ["hod", "mtf2"]),
    (7,  "poly_updown_btc_15m_momo_v2_hod",     "momo_v2", "BTC", "15m", ["hod"]),
    (8,  "poly_updown_sol_5m_momo_v2_hod",      "momo_v2", "SOL", "5m",  ["hod"]),
    (9,  "poly_updown_eth_15m_momo_v2_hod",     "momo_v2", "ETH", "15m", ["hod"]),
    (10, "poly_updown_sol_15m_momo_v2_hod",     "momo_v2", "SOL", "15m", ["hod"]),
    (11, "poly_updown_eth_5m_sniper_hod",       "sniper",  "ETH", "5m",  ["hod"]),
]

EXPECTED = {
    1: ("~65/wk", "65-70%", "+$6 to +$10"),
    2: ("~25/wk", "70-80%", "+$10 to +$16"),
    3: ("~20/wk", "70-85%", "+$10 to +$16"),
    4: ("~100/wk", "55-62%", "+$3 to +$5"),
    5: ("~110/wk", "55-60%", "+$2 to +$4"),
    6: ("~60/wk", "58-65%", "+$3 to +$6"),
    7: ("~35/wk", "65-72%", "+$6 to +$9"),
    8: ("~50/wk", "58-65%", "+$3 to +$6"),
    9: ("~25/wk", "65-72%", "+$6 to +$10"),
    10: ("~18/wk", "65-75%", "+$6 to +$10"),
    11: ("~80/wk", "50-58%", "+$0 to +$3"),
}


def classify_family(sleeve_id: str) -> str:
    """Match a sleeve_id from trading_events to one of {momo, momo_v2, sniper}.
    The base sleeve_id has NO _hod / _hod_mtf / _m5va suffix and NO _f7.
    We want the BARE base sleeves: poly_updown_{asset}_{tf}_{family}[_HOLD|_HEDGE|_SELL].
    """
    if not isinstance(sleeve_id, str):
        return "unknown"
    s = sleeve_id.replace("poly_updown_", "")
    # strip policy suffix
    for suf in ("_HOLD", "_HEDGE", "_SELL"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    # Reject sleeves that already have F7 / hod / inverse modifiers
    if any(tok in s for tok in ("_f7", "_hod", "_INV", "_DOWN_INV", "_NIGHT")):
        return "modified"
    if "momo_v2" in s:    return "momo_v2"
    if s.endswith("_momo") or "_momo_" in s: return "momo"
    if s.endswith("_sniper") or "_sniper_" in s: return "sniper"
    return "other"


def parse_payload(s):
    if isinstance(s, dict): return s
    try:
        return json.loads(s)
    except Exception:
        return {}


def hod_passes(at_ts, allowed_hours):
    if not isinstance(at_ts, pd.Timestamp): return False
    return at_ts.hour in set(allowed_hours)


def mtf2_passes(signal, ret_15m, ret_1h):
    if signal not in ("UP", "DOWN"): return True
    if not (math.isfinite(ret_15m) and math.isfinite(ret_1h)): return False
    if signal == "UP":   return ret_15m > 0 and ret_1h > 0
    return ret_15m < 0 and ret_1h < 0


def main():
    print(f"[1] loading trading_events_30d.parquet...")
    df = pd.read_parquet(EV)
    df = df[df.kind == "poly_updown_resolution"].copy()
    df["at_ts"] = pd.to_datetime(df["at"], utc=True, format="mixed", errors="coerce")
    df = df[df.at_ts.notna()].copy()
    df["p"] = df.data.apply(parse_payload)
    df["symbol"]      = df.p.apply(lambda d: d.get("symbol"))
    df["tf"]          = df.p.apply(lambda d: d.get("tf"))
    df["signal"]      = df.p.apply(lambda d: d.get("signal"))
    df["won"]         = df.p.apply(lambda d: bool(d.get("won")))
    df["pnl_usd"]     = pd.to_numeric(df.p.apply(lambda d: d.get("pnl_usd")), errors="coerce")
    df["entry_qty"]   = pd.to_numeric(df.p.apply(lambda d: d.get("entry_qty")), errors="coerce")
    df["entry_price"] = pd.to_numeric(df.p.apply(lambda d: d.get("entry_price")), errors="coerce")
    df["mode"]        = df.p.apply(lambda d: d.get("mode"))
    df["fam"]         = df.sleeve_id.apply(classify_family)
    df = df[df.fam.isin(("momo", "momo_v2", "sniper")) &
            df.symbol.isin(("BTC","ETH","SOL")) & df.tf.isin(("5m","15m"))].copy()
    print(f"    valid base-sleeve fires: {len(df):,}")
    print(f"    date range: {df.at_ts.min()} -> {df.at_ts.max()}")
    print(f"    by (fam, symbol, tf): {df.groupby(['fam','symbol','tf']).size().to_dict()}")

    # ===== Derive fire_us per sleeve family =====
    # at_ts = slot_end_ts. slot_start_ts = at_ts - window_s.
    # momo v1: fire_us = ws_s + 120 = slot_start - window_s + 120 = at_ts - 2*window_s + 120
    # momo_v2:           = ws_s +  60 = at_ts - 2*window_s + 60
    # sniper: bar_close fire at slot_start = at_ts - window_s
    df["window_s"] = df.tf.map({"5m": 300, "15m": 900}).astype("int64")
    at_s = (df.at_ts.astype("int64") // 1_000_000_000).astype("int64")
    df["at_s"] = at_s
    fire_s = np.where(
        df.fam.values == "momo",     at_s - 2 * df.window_s.values + 120,
        np.where(
            df.fam.values == "momo_v2",  at_s - 2 * df.window_s.values + 60,
            at_s - df.window_s.values,      # sniper
        ),
    )
    df["fire_s"] = fire_s
    df["fire_ts"] = pd.to_datetime(df.fire_s, unit="s", utc=True)

    # ===== Load klines once per asset =====
    print(f"[2] loading 1MIN klines + 5MIN klines for BTC/ETH/SOL...")
    klines_1m = {}
    klines_5m = {}
    for a in ("BTC","ETH","SOL"):
        eu, cl = load_klines_asof(a, "binance-spot-ws", "1MIN")
        klines_1m[a] = (eu.astype("int64"), cl.astype("float64"))
        eu5, cl5 = load_klines_asof(a, "binance-spot-ws", "5MIN")
        klines_5m[a] = (eu5.astype("int64"), cl5.astype("float64"))
        print(f"    {a}: 1MIN n={len(eu)}  5MIN n={len(eu5)}")

    # ===== Build Markov labels for Markov m5va gate (per asset) =====
    print(f"[3] building Markov labels (w20, 5m, vol-adaptive) per asset...")
    markov_cache = {}
    for a in ("BTC","ETH","SOL"):
        end_us, _c, labels = build_labels_for_asset(
            a, window_bars=20, bar_minutes=5, mode="vol_adaptive",
        )
        markov_cache[a] = (end_us.astype("int64"), labels.astype("int8"))
        n_lbl = int((labels >= 0).sum())
        print(f"    {a}: {n_lbl:,} labelled bars")

    # ===== Helpers: close-asof + ret_log =====
    def close_at(asset, ts_s):
        eu, cl = klines_1m[asset]
        target_us = int(ts_s) * 1_000_000
        i = int(np.searchsorted(eu, target_us, side="right")) - 1
        if i < 0 or i >= len(cl): return float("nan")
        return float(cl[i])

    def ret_log(asset, t0_s, t1_s):
        c0 = close_at(asset, t0_s); c1 = close_at(asset, t1_s)
        if not (math.isfinite(c0) and math.isfinite(c1)) or c0 <= 0 or c1 <= 0:
            return float("nan")
        return math.log(c1 / c0)

    def markov_regime_at(asset, ts_s):
        end_us, labels = markov_cache[asset]
        return regime_at_us(end_us, labels, int(ts_s) * 1_000_000)

    # ===== Per-sleeve backtest =====
    print(f"\n[4] applying gate stacks per sleeve...")
    rows = []
    for sid, sleeve_id, fam, asset, tf, gates in SHADOW_SLEEVES:
        cell = f"{asset.lower()}_{tf}"
        # Base fire universe = production fires for this fam × cell
        base = df[(df.fam == fam) & (df.symbol == asset) & (df.tf == tf)].copy()
        n_base = len(base)
        if n_base == 0:
            print(f"  #{sid:>2}  {sleeve_id}  no base fires — skip")
            continue
        # Apply gates
        keep = pd.Series(True, index=base.index)
        skip_counts = {g: 0 for g in gates}
        # Gate 1: hod
        if "hod" in gates:
            allowed = HOD_TOP8_BY_CELL.get((fam, cell), [])
            mask = base.at_ts.dt.hour.isin(allowed)
            skip_counts["hod"] = int((keep & ~mask).sum())
            keep &= mask
        # Gate 2: mtf2 (compute ret_15m + ret_1h at fire_us)
        if "mtf2" in gates:
            sub = base[keep]
            mtf_mask_full = pd.Series(False, index=base.index)
            for idx, r in sub.iterrows():
                t1 = int(r.fire_s)
                r15 = ret_log(asset, t1 - 900, t1)
                r1h = ret_log(asset, t1 - 3600, t1)
                if mtf2_passes(r.signal, r15, r1h):
                    mtf_mask_full[idx] = True
            skip_counts["mtf2"] = int((keep & ~mtf_mask_full).sum())
            keep &= mtf_mask_full
        # Gate 3: m5va (Markov 5m vol-adaptive)
        if "m5va" in gates:
            sub = base[keep]
            m_mask_full = pd.Series(False, index=base.index)
            for idx, r in sub.iterrows():
                regime = markov_regime_at(asset, int(r.fire_s))
                if r.signal == "UP"   and regime == BULL: m_mask_full[idx] = True
                if r.signal == "DOWN" and regime == BEAR: m_mask_full[idx] = True
            skip_counts["m5va"] = int((keep & ~m_mask_full).sum())
            keep &= m_mask_full

        kept = base[keep]
        n = len(kept)
        if n == 0:
            wr = 0.0; sum_pnl = 0.0; per_trade = 0.0
        else:
            wr = float(kept.won.mean())
            sum_pnl = float(kept.pnl_usd.sum())
            per_trade = float(kept.pnl_usd.mean())

        # Span normalization — production sniper events start 2026-05-07; momo earlier
        span_days = (base.at_ts.max() - base.at_ts.min()).days or 1
        n_per_week = n / span_days * 7
        exp_n, exp_wr, exp_per = EXPECTED.get(sid, ("?","?","?"))

        rows.append(dict(
            sid=sid, sleeve_id=sleeve_id, fam=fam, asset=asset, tf=tf,
            gates="+".join(gates), n_base=n_base, n_kept=n,
            n_per_week=round(n_per_week, 1),
            wr_pct=round(wr*100, 2), sum_pnl=round(sum_pnl, 2),
            per_trade=round(per_trade, 3),
            skipped_hod=skip_counts.get("hod", 0),
            skipped_mtf2=skip_counts.get("mtf2", 0),
            skipped_m5va=skip_counts.get("m5va", 0),
            expected_n=exp_n, expected_wr=exp_wr, expected_per=exp_per,
        ))
        print(f"  #{sid:>2} {sleeve_id:<42} base={n_base:>4} kept={n:>4} ({n/n_base*100:>5.1f}%)  "
              f"WR={wr*100:>5.2f}%  $/tr={per_trade:>+7.3f}  sum=${sum_pnl:>+8.2f}  "
              f"[exp {exp_wr}, {exp_per}]")

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(f"\nSaved: {OUT}")

    print()
    print("=" * 110)
    print("SUMMARY TABLE — actual vs expected")
    print("=" * 110)
    print(f"{'id':>3} {'sleeve':<42} {'n':>5} {'n/wk':>5} {'WR':>7} {'$/tr':>8} {'sum$':>9}  | {'exp_n':>7} {'exp_WR':<8} {'exp_$/tr':<13}")
    for r in rows:
        print(f"{r['sid']:>3} {r['sleeve_id']:<42} {r['n_kept']:>5} {r['n_per_week']:>5.1f} {r['wr_pct']:>6.2f}% ${r['per_trade']:>+7.3f} ${r['sum_pnl']:>+8.2f}  | "
              f"{r['expected_n']:<7} {r['expected_wr']:<8} {r['expected_per']:<13}")


if __name__ == "__main__":
    main()
