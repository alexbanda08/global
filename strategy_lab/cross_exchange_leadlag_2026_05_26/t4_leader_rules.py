"""TASK 4 — Backtest leader-direction rules as fire signals.

Rules (always bet $25 notional at the fire_us, legacy fees):
  LL-A: bet UP when ALL of {coinbase, kraken, okx} moved up in last 15s before fire
  LL-B: bet UP when fastest leader (TBD) moved up in last 5s
  LL-C: bet AGAINST binance when leader DISAGREES with binance recent direction
  LL-D: bet WITH hyperliquid perp recent direction

All leader prices are looked up STRICT-asof at (fire_us - look_s) and (fire_us).
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

import pandas as pd
import numpy as np
from load import load_klines_1s, load_hyperliquid_trades, load_klines, load_okx_klines

OUT_DIR = ROOT / "strategy_lab" / "cross_exchange_leadlag_2026_05_26"

FIRE_PATH = ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_fire_universe_5m.parquet"

WIN_START_US = int(pd.Timestamp("2026-04-30", tz="UTC").value // 1000)
WIN_END_US   = int(pd.Timestamp("2026-05-22", tz="UTC").value // 1000)

def fires(asset: str | None = None) -> pd.DataFrame:
    df = pd.read_parquet(FIRE_PATH)
    df = df[(df.fire_us >= WIN_START_US) & (df.fire_us <= WIN_END_US)].copy()
    if asset:
        df = df[df.asset == asset]
    return df

def asof_searchsorted(target_us: np.ndarray, ref_us: np.ndarray, ref_vals: np.ndarray) -> np.ndarray:
    """For each t in target_us, return ref_vals at last ref_us <= t (or NaN)."""
    pos = np.searchsorted(ref_us, target_us, side="right") - 1
    out = np.full(len(target_us), np.nan)
    valid = pos >= 0
    out[valid] = ref_vals[pos[valid]]
    return out

# ---------------------------------------------------------------------------
# Build per-asset leader series
# ---------------------------------------------------------------------------

def binance_1s_arr(asset: str) -> tuple[np.ndarray, np.ndarray]:
    df = load_klines_1s(asset=asset)
    df = df[(df.time_period_start_us >= WIN_START_US - 60_000_000) &
            (df.time_period_start_us <= WIN_END_US + 60_000_000)]
    df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
    end_us = df.time_period_start_us.values + 1_000_000  # 1-second bars
    return end_us.astype("int64"), df.price_close.astype("float64").values

def hl_trades_per_sec(asset: str) -> tuple[np.ndarray, np.ndarray]:
    df = load_hyperliquid_trades(asset=asset)
    df = df[(df.time_exchange_us >= WIN_START_US - 60_000_000) &
            (df.time_exchange_us <= WIN_END_US + 60_000_000)]
    cols = df.columns.tolist()
    pcol = "px" if "px" in cols else "price"
    qcol = "sz" if "sz" in cols else "size"
    ts_s = (df.time_exchange_us.values // 1_000_000).astype("int64")
    px = df[pcol].astype("float64").values
    sz = df[qcol].astype("float64").values
    g = pd.DataFrame({"ts_s": ts_s, "pq": px*sz, "q": sz}).groupby("ts_s").agg({"pq":"sum","q":"sum"})
    g = g[g.q > 0]
    g["vwap"] = g.pq / g.q
    end_us = (g.index.values * 1_000_000 + 1_000_000).astype("int64")
    return end_us, g["vwap"].astype("float64").values

def kline_1min_arr(asset: str, venue: str) -> tuple[np.ndarray, np.ndarray]:
    if venue == "coinbase":
        df = load_klines(asset, source="coinbase-spot-ws", period_id="1MIN")
    elif venue == "kraken":
        df = load_klines(asset, source="kraken-spot-ws", period_id="1MIN")
    elif venue == "okx":
        df = load_okx_klines(asset=asset, period_id="1MIN")
    elif venue == "binance":
        df = load_klines(asset, source="binance-spot-ws", period_id="1MIN")
    df = df[(df.time_period_start_us >= WIN_START_US - 600_000_000) &
            (df.time_period_start_us <= WIN_END_US + 600_000_000)].copy()
    df = df.drop_duplicates("time_period_start_us", keep="last").sort_values("time_period_start_us")
    end_us = df.time_period_start_us.values + 60_000_000  # 1-minute bars
    return end_us.astype("int64"), df.price_close.astype("float64").values

def get_leader_direction(fire_us: np.ndarray, ref_end_us: np.ndarray, ref_close: np.ndarray, lookback_s: int) -> np.ndarray:
    """Returns signed log-return = log(close_at_fire / close_lookback_before).
    Strict causal: closes are STRICTLY before fire_us.
    """
    target_now = fire_us - 1  # one-microsecond strict-before
    target_back = fire_us - lookback_s * 1_000_000
    p_now = asof_searchsorted(target_now, ref_end_us, ref_close)
    p_old = asof_searchsorted(target_back, ref_end_us, ref_close)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.log(p_now / p_old)

# ---------------------------------------------------------------------------
# Score and run
# ---------------------------------------------------------------------------

def legacy_pnl(side: str, row: pd.Series) -> float:
    """Legacy fee: -usd if lost, 0.98 × shares × (1-vwap) if won."""
    if side == "UP":
        if not row.up_fill_ok or not (row.up_usd > 0): return np.nan
        won = (row.outcome == "Up")
        usd = row.up_usd; shares = row.up_shares; vwap = row.up_vwap
    else:
        if not row.dn_fill_ok or not (row.dn_usd > 0): return np.nan
        won = (row.outcome == "Down")
        usd = row.dn_usd; shares = row.dn_shares; vwap = row.dn_vwap
    if won:
        profit = shares * (1.0 - vwap)
        return 0.98 * profit
    else:
        return -usd

def run():
    out_rows = []
    summary_rows = []

    fires_df = fires()
    fires_df["ts"] = pd.to_datetime(fires_df.fire_us, unit="us", utc=True)
    print(f"Total fires in window: {len(fires_df):,}", flush=True)

    for asset in ["BTC", "ETH", "SOL"]:
        print(f"\n=== {asset} ===", flush=True)
        a_fires = fires_df[fires_df.asset == asset].copy().reset_index(drop=True)
        if len(a_fires) == 0: continue
        fire_us = a_fires.fire_us.values.astype("int64")

        # Leader series
        bn_end, bn_px = binance_1s_arr(asset)
        hl_end, hl_px = hl_trades_per_sec(asset)
        cb_end, cb_px = kline_1min_arr(asset, "coinbase")
        kr_end, kr_px = kline_1min_arr(asset, "kraken")
        ok_end, ok_px = kline_1min_arr(asset, "okx")

        # Compute leader directions at multiple lookbacks
        ret_bn_5  = get_leader_direction(fire_us, bn_end, bn_px, 5)
        ret_bn_15 = get_leader_direction(fire_us, bn_end, bn_px, 15)
        ret_bn_60 = get_leader_direction(fire_us, bn_end, bn_px, 60)

        ret_hl_5  = get_leader_direction(fire_us, hl_end, hl_px, 5)
        ret_hl_15 = get_leader_direction(fire_us, hl_end, hl_px, 15)
        ret_hl_60 = get_leader_direction(fire_us, hl_end, hl_px, 60)

        ret_cb_60  = get_leader_direction(fire_us, cb_end, cb_px, 60)
        ret_cb_120 = get_leader_direction(fire_us, cb_end, cb_px, 120)
        ret_kr_60  = get_leader_direction(fire_us, kr_end, kr_px, 60)
        ret_kr_120 = get_leader_direction(fire_us, kr_end, kr_px, 120)
        ret_ok_60  = get_leader_direction(fire_us, ok_end, ok_px, 60)
        ret_ok_120 = get_leader_direction(fire_us, ok_end, ok_px, 120)

        # Store directions for re-use
        a_fires["ret_bn_5"] = ret_bn_5
        a_fires["ret_bn_15"] = ret_bn_15
        a_fires["ret_bn_60"] = ret_bn_60
        a_fires["ret_hl_5"] = ret_hl_5
        a_fires["ret_hl_15"] = ret_hl_15
        a_fires["ret_hl_60"] = ret_hl_60
        a_fires["ret_cb_60"] = ret_cb_60
        a_fires["ret_cb_120"] = ret_cb_120
        a_fires["ret_kr_60"] = ret_kr_60
        a_fires["ret_kr_120"] = ret_kr_120
        a_fires["ret_ok_60"] = ret_ok_60
        a_fires["ret_ok_120"] = ret_ok_120

        # ------------------------------------------------------------------
        # RULES — each yields a SET of fires where to act, plus a side
        # ------------------------------------------------------------------

        rules = {}

        # Rule LL-A: bet UP when ALL of {coinbase, kraken, okx} up in last 60s
        # Note: with 1MIN venues we use 60s. 15s impossible.
        for lb in [60, 120]:
            cb = a_fires[f"ret_cb_{lb}"].values
            kr = a_fires[f"ret_kr_{lb}"].values
            ok = a_fires[f"ret_ok_{lb}"].values
            up_mask = (cb > 0) & (kr > 0) & (ok > 0)
            dn_mask = (cb < 0) & (kr < 0) & (ok < 0)
            rules[f"LL-A-up_{lb}s"] = (up_mask, "UP")
            rules[f"LL-A-dn_{lb}s"] = (dn_mask, "DN")
            rules[f"LL-A-both_{lb}s"] = (up_mask | dn_mask, "leader")

        # Rule LL-B: bet WITH fastest leader (binance 5s) — should be control
        # And: bet WITH HL recent direction (since HL has predictive power per Task 3)
        for lb in [5, 15, 60]:
            hl = a_fires[f"ret_hl_{lb}"].values
            up_mask = hl > 0
            dn_mask = hl < 0
            rules[f"LL-B-hl-up_{lb}s"] = (up_mask, "UP")
            rules[f"LL-B-hl-dn_{lb}s"] = (dn_mask, "DN")
            rules[f"LL-B-hl-both_{lb}s"] = (np.ones_like(up_mask, dtype=bool), "hl_dir")

            bn = a_fires[f"ret_bn_{lb}"].values
            rules[f"LL-B-bn-up_{lb}s"] = (bn > 0, "UP")
            rules[f"LL-B-bn-dn_{lb}s"] = (bn < 0, "DN")
            rules[f"LL-B-bn-both_{lb}s"] = (np.ones_like(bn, dtype=bool), "bn_dir")

        # Rule LL-C: bet AGAINST binance when HL disagrees with binance
        # i.e., HL is up but binance is down → bet UP (because HL leads correction?)
        for lb in [5, 15]:
            hl = a_fires[f"ret_hl_{lb}"].values
            bn = a_fires[f"ret_bn_{lb}"].values
            # divergence cases
            up_mask = (hl > 0) & (bn < 0)
            dn_mask = (hl < 0) & (bn > 0)
            rules[f"LL-C-div-up_{lb}s"] = (up_mask, "UP")
            rules[f"LL-C-div-dn_{lb}s"] = (dn_mask, "DN")

        # Rule LL-D already in LL-B-hl-*. Skip duplicates.

        # Apply rules
        for rname, (mask, side_or_kind) in rules.items():
            sub = a_fires.loc[mask].copy()
            n = len(sub)
            if n < 50: continue
            pnls = []
            wins = 0
            for idx, r in sub.iterrows():
                if side_or_kind == "UP":
                    p = legacy_pnl("UP", r); ok = "Up" == r.outcome
                elif side_or_kind == "DN":
                    p = legacy_pnl("DN", r); ok = "Down" == r.outcome
                elif side_or_kind == "leader":
                    # Use composite direction
                    cb = r.get(f"ret_cb_60", 0); kr = r.get(f"ret_kr_60", 0); ok_ = r.get(f"ret_ok_60", 0)
                    s = "UP" if (cb>0 and kr>0 and ok_>0) else "DN"
                    p = legacy_pnl(s, r); ok = (s=="UP" and r.outcome=="Up") or (s=="DN" and r.outcome=="Down")
                elif side_or_kind == "hl_dir":
                    s = "UP" if r[f"ret_hl_5"]>0 else "DN"
                    p = legacy_pnl(s, r); ok = (s=="UP" and r.outcome=="Up") or (s=="DN" and r.outcome=="Down")
                elif side_or_kind == "bn_dir":
                    s = "UP" if r[f"ret_bn_5"]>0 else "DN"
                    p = legacy_pnl(s, r); ok = (s=="UP" and r.outcome=="Up") or (s=="DN" and r.outcome=="Down")
                if not np.isfinite(p): continue
                pnls.append(p)
                if ok: wins += 1
            if not pnls: continue
            n_ok = len(pnls)
            pnls = np.array(pnls)
            summary_rows.append({
                "asset": asset, "rule": rname, "n_fires": n_ok,
                "wr": wins / n_ok, "mean_pnl": pnls.mean(),
                "sum_pnl": pnls.sum(), "median_pnl": np.median(pnls),
                "p_value_proxy": 2*(1 - 0.5*(1 + np.tanh(pnls.sum() / (pnls.std() * np.sqrt(len(pnls)) + 1e-9)))),
            })
        print(f"  rules tested: {len(rules)}, summary rows so far: {len(summary_rows)}", flush=True)

    res = pd.DataFrame(summary_rows)
    res = res.sort_values("sum_pnl", ascending=False)
    res.to_csv(OUT_DIR / "_leader_rule_results.csv", index=False)
    print("\n=== TOP 20 RULES BY SUM PnL ===")
    print(res.head(20).to_string(index=False))
    print("\n=== ALL POSITIVE ===")
    print(res[res.sum_pnl > 0].head(40).to_string(index=False))
    print(f"\nWrote {OUT_DIR / '_leader_rule_results.csv'}")

run()
