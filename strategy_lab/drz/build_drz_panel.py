"""Build DRZ (Delta Reaction Zones) feature panel — port of BOSWaves Pine v6.

Indicator logic (port of `Delta Reaction Zones [BOSWaves]` for TradingView):
  1. raw_delta[i]  = sign(close - open) * volume
  2. smoothed_delta = EMA(raw_delta, delta_smooth=3)
  3. CVD          = cumulative sum of smoothed_delta
  4. pivots on CVD with lookback `pivot_lookback=12` (left+right)
  5. when an upper pivot prints (at bar i, CVD has local max in window [i-12, i+12]):
       - RESISTANCE zone created at high[i-12] (NOT bar 0 — pivot center is 12 bars back)
       - half_width = ATR(14) at pivot bar * zone_atr_mult (default 0.35)
  6. when a lower pivot prints:
       - SUPPORT zone created at low[i-12], same half-width formula.
  7. Each zone gets an `impulse window` of the last `impulse_window=100` raw_delta values
     surrounding pivot — track pos_pct, neg_pct, net_impulse.
  8. A zone is "breached" once close exits the box (above resistance / below support).
  9. **Signals**:
       - Support reclaim (RC):    close crosses up through midline AFTER being below.
       - Resistance re-enter (RE): close crosses down through midline AFTER being above.

For each fire timestamp `fire_us`, look up DRZ state on the LAST CLOSED bar of that
timeframe BEFORE fire_us - 1s (causal). Outputs at offset `fire_us - 1s` per fire.

Outputs:
  data/v4/canonical/_results/drz_panel_5m.parquet   (per fire row with drz_* columns)
  data/v4/canonical/_results/drz_panel_15m.parquet
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_klines  # type: ignore

RES = ROOT / "data" / "v4" / "canonical" / "_results"
ASSETS = ("BTC", "ETH", "SOL")

# Default Pine inputs
DELTA_SMOOTH = 3
PIVOT_LOOKBACK = 12
ATR_LENGTH = 14
ZONE_ATR_MULT = 0.35
IMPULSE_WINDOW = 100
RECLAIM_WINDOW_BARS = 5  # how many bars back to check for RC/RE signal


def ema(x: np.ndarray, length: int) -> np.ndarray:
    """Pine EMA — alpha = 2/(length+1). Seed = x[0]. NaN-pass-through."""
    n = len(x)
    out = np.full(n, np.nan, dtype="float64")
    if n == 0:
        return out
    alpha = 2.0 / (length + 1.0)
    # seed at first finite value
    seed = None
    for i in range(n):
        if np.isfinite(x[i]):
            seed = float(x[i])
            out[i] = seed
            start = i + 1
            break
    if seed is None:
        return out
    cur = seed
    for i in range(start, n):
        v = x[i]
        if np.isfinite(v):
            cur = alpha * float(v) + (1 - alpha) * cur
            out[i] = cur
        else:
            out[i] = cur
    return out


def atr_wilder(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int = 14) -> np.ndarray:
    """Wilder ATR (RMA on True Range). Matches Pine `ta.atr(length)`."""
    n = len(close)
    out = np.full(n, np.nan, dtype="float64")
    if n == 0:
        return out
    tr = np.zeros(n, dtype="float64")
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        h = high[i]; l = low[i]; pc = close[i-1]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    # Wilder: alpha = 1/length, seed = SMA of first `length` TRs
    if n < length:
        return out
    seed = float(np.mean(tr[:length]))
    out[length - 1] = seed
    cur = seed
    alpha = 1.0 / length
    for i in range(length, n):
        cur = alpha * tr[i] + (1 - alpha) * cur
        out[i] = cur
    return out


def find_pivots(x: np.ndarray, left: int, right: int) -> tuple[np.ndarray, np.ndarray]:
    """Pine `ta.pivothigh(x, left, right)` / `ta.pivotlow(x, left, right)`.

    Pivot PRINTS at bar `i + right` (right bars later) for a pivot CENTERED at bar i.
    Returns (pivot_high_index_at_print, pivot_low_index_at_print) arrays — same len as x.
    Value is the CENTER index of the pivot when one prints, else -1.
    """
    n = len(x)
    pivhi = np.full(n, -1, dtype="int64")
    pivlo = np.full(n, -1, dtype="int64")
    for i in range(left, n - right):
        win = x[i - left: i + right + 1]
        center = x[i]
        if not np.isfinite(center):
            continue
        if np.isfinite(win).sum() < (left + right + 1):
            continue
        # strict max (Pine ta.pivothigh uses >= for ties — emulate with > for stability)
        if center > np.max(np.concatenate([x[i-left:i], x[i+1:i+right+1]])):
            # PRINTS at bar i + right
            pivhi[i + right] = i
        if center < np.min(np.concatenate([x[i-left:i], x[i+1:i+right+1]])):
            pivlo[i + right] = i
    return pivhi, pivlo


def build_drz_bars(df_k: pd.DataFrame) -> pd.DataFrame:
    """Compute DRZ-related per-bar state for one asset/timeframe OHLCV frame.

    Input columns expected: time_period_start_us, time_period_end_us,
        price_open, price_high, price_low, price_close, volume_traded.

    Output adds (per bar):
      raw_delta, sm_delta, cvd, atr14,
      sup_zone_low, sup_zone_hi, sup_mid, sup_active,  (latest active support zone)
      res_zone_low, res_zone_hi, res_mid, res_active,
      sup_pivot_bar_idx, res_pivot_bar_idx,  (the BAR INDEX where pivot center sits)
      sup_zone_pos_pct, sup_zone_net_impulse,
      res_zone_pos_pct, res_zone_net_impulse,
      n_active_sup, n_active_res,
      sig_rc_bar  (1 if support reclaim printed on this bar),
      sig_re_bar  (1 if resistance re-enter printed on this bar).
    """
    o = df_k["price_open"].astype("float64").values
    h = df_k["price_high"].astype("float64").values
    l = df_k["price_low"].astype("float64").values
    c = df_k["price_close"].astype("float64").values
    v = df_k["volume_traded"].astype("float64").values
    n = len(c)

    # Step 1+2+3: raw_delta, sm_delta, CVD
    sign_oc = np.where(c > o, 1.0, np.where(c < o, -1.0, 0.0))
    raw_delta = sign_oc * v
    sm_delta = ema(raw_delta, DELTA_SMOOTH)
    cvd = np.cumsum(np.where(np.isfinite(sm_delta), sm_delta, 0.0))

    # Step 4: ATR(14)
    atr14 = atr_wilder(h, l, c, ATR_LENGTH)

    # Step 5+6: pivots on CVD
    pivhi, pivlo = find_pivots(cvd, PIVOT_LOOKBACK, PIVOT_LOOKBACK)

    # Maintain ACTIVE zones — Pine convention: a fresh pivot SUPERSEDES the prior zone
    # (zones get drawn as boxes that extend forward until broken; we simulate by only
    # tracking the most recent un-breached zone of each kind).
    sup_low = np.full(n, np.nan); sup_hi = np.full(n, np.nan); sup_mid = np.full(n, np.nan)
    sup_active = np.zeros(n, dtype="int8")
    sup_piv_idx = np.full(n, -1, dtype="int64")
    sup_pos_pct = np.full(n, np.nan); sup_net = np.full(n, np.nan)
    res_low = np.full(n, np.nan); res_hi = np.full(n, np.nan); res_mid = np.full(n, np.nan)
    res_active = np.zeros(n, dtype="int8")
    res_piv_idx = np.full(n, -1, dtype="int64")
    res_pos_pct = np.full(n, np.nan); res_net = np.full(n, np.nan)
    n_sup = np.zeros(n, dtype="int32"); n_res = np.zeros(n, dtype="int32")

    sig_rc = np.zeros(n, dtype="int8")
    sig_re = np.zeros(n, dtype="int8")

    # State: dicts holding active sup / res zone parameters
    cur_sup = None   # {center_bar, mid, lo, hi, breached: bool, last_side: 'below'|'above'|'in'}
    cur_res = None

    for i in range(n):
        # --- Step 7: zone IMPULSE stats for any pivot that just printed on bar i ---
        if pivhi[i] >= 0:
            center = pivhi[i]
            if np.isfinite(atr14[center]) and atr14[center] > 0:
                half = atr14[center] * ZONE_ATR_MULT
                mid = h[center]
                lo = mid - half
                hi = mid + half
                # impulse window: last IMPULSE_WINDOW raw_delta entries up to center
                lo_w = max(0, center - IMPULSE_WINDOW + 1)
                window = raw_delta[lo_w:center + 1]
                pos = float((window > 0).sum())
                neg = float((window < 0).sum())
                tot = float(len(window))
                pos_pct = pos / tot * 100.0 if tot > 0 else np.nan
                net = float(window.sum())
                cur_res = {
                    "center": center, "mid": mid, "lo": lo, "hi": hi,
                    "breached": False, "last_side": None,
                    "pos_pct": pos_pct, "net": net,
                }
        if pivlo[i] >= 0:
            center = pivlo[i]
            if np.isfinite(atr14[center]) and atr14[center] > 0:
                half = atr14[center] * ZONE_ATR_MULT
                mid = l[center]
                lo = mid - half
                hi = mid + half
                lo_w = max(0, center - IMPULSE_WINDOW + 1)
                window = raw_delta[lo_w:center + 1]
                pos = float((window > 0).sum())
                neg = float((window < 0).sum())
                tot = float(len(window))
                pos_pct = pos / tot * 100.0 if tot > 0 else np.nan
                net = float(window.sum())
                cur_sup = {
                    "center": center, "mid": mid, "lo": lo, "hi": hi,
                    "breached": False, "last_side": None,
                    "pos_pct": pos_pct, "net": net,
                }

        # --- Step 8/9: detect signals + breaches using CURRENT close ---
        close_i = c[i]
        # support
        if cur_sup is not None and np.isfinite(close_i):
            side_now = "above" if close_i > cur_sup["mid"] else ("below" if close_i < cur_sup["mid"] else "in")
            if not cur_sup["breached"]:
                # mark breach when close exits below the BOX bottom
                if close_i < cur_sup["lo"]:
                    cur_sup["breached"] = True
                # RC: crossing UP through midline
                elif cur_sup["last_side"] == "below" and side_now == "above":
                    sig_rc[i] = 1
            cur_sup["last_side"] = side_now
        # resistance
        if cur_res is not None and np.isfinite(close_i):
            side_now = "above" if close_i > cur_res["mid"] else ("below" if close_i < cur_res["mid"] else "in")
            if not cur_res["breached"]:
                if close_i > cur_res["hi"]:
                    cur_res["breached"] = True
                elif cur_res["last_side"] == "above" and side_now == "below":
                    sig_re[i] = 1
            cur_res["last_side"] = side_now

        # --- record state for bar i ---
        if cur_sup is not None and not cur_sup["breached"]:
            sup_low[i] = cur_sup["lo"]; sup_hi[i] = cur_sup["hi"]; sup_mid[i] = cur_sup["mid"]
            sup_active[i] = 1
            sup_piv_idx[i] = cur_sup["center"]
            sup_pos_pct[i] = cur_sup["pos_pct"]; sup_net[i] = cur_sup["net"]
            n_sup[i] = 1
        if cur_res is not None and not cur_res["breached"]:
            res_low[i] = cur_res["lo"]; res_hi[i] = cur_res["hi"]; res_mid[i] = cur_res["mid"]
            res_active[i] = 1
            res_piv_idx[i] = cur_res["center"]
            res_pos_pct[i] = cur_res["pos_pct"]; res_net[i] = cur_res["net"]
            n_res[i] = 1

    out = df_k[["time_period_start_us", "time_period_end_us", "price_close"]].copy()
    out["raw_delta"] = raw_delta
    out["sm_delta"] = sm_delta
    out["cvd"] = cvd
    out["atr14"] = atr14
    out["sup_low"] = sup_low; out["sup_hi"] = sup_hi; out["sup_mid"] = sup_mid
    out["sup_active"] = sup_active
    out["sup_piv_idx"] = sup_piv_idx
    out["sup_pos_pct"] = sup_pos_pct
    out["sup_net"] = sup_net
    out["res_low"] = res_low; out["res_hi"] = res_hi; out["res_mid"] = res_mid
    out["res_active"] = res_active
    out["res_piv_idx"] = res_piv_idx
    out["res_pos_pct"] = res_pos_pct
    out["res_net"] = res_net
    out["n_active_sup"] = n_sup
    out["n_active_res"] = n_res
    out["sig_rc"] = sig_rc
    out["sig_re"] = sig_re
    # bar index for indexing later
    out["_bar"] = np.arange(n, dtype="int64")
    return out


def lookup_drz_state(drz: pd.DataFrame, fire_us: int) -> dict:
    """Lookup the LAST FULLY-CLOSED bar's DRZ state for a fire timestamp.

    Causal: drz row r is valid if r.time_period_end_us <= fire_us. Use right-edge
    searchsorted.
    """
    end_us = drz["time_period_end_us"].values
    target = int(fire_us) - 1_000_000  # 1 second margin
    pos = int(np.searchsorted(end_us, target, side="right")) - 1
    if pos < 0:
        return {}
    r = drz.iloc[pos]
    close = float(r["price_close"])
    atr = float(r["atr14"]) if np.isfinite(r["atr14"]) else np.nan

    out = {
        "drz_close": close,
        "drz_atr14": atr,
        "drz_active_zone_count": int(r["n_active_sup"]) + int(r["n_active_res"]),
        "drz_n_sup": int(r["n_active_sup"]),
        "drz_n_res": int(r["n_active_res"]),
        "drz_in_support_zone": False,
        "drz_in_resistance_zone": False,
        "drz_dist_to_nearest_support_bps": np.nan,
        "drz_dist_to_nearest_resistance_bps": np.nan,
        "drz_bars_since_support_pivot": -1,
        "drz_bars_since_resistance_pivot": -1,
        "drz_recent_RC": False,
        "drz_recent_RE": False,
        "drz_zone_sup_pos_pct": np.nan,
        "drz_zone_sup_net": np.nan,
        "drz_zone_res_pos_pct": np.nan,
        "drz_zone_res_net": np.nan,
    }
    bar = int(r["_bar"])

    if int(r["n_active_sup"]) > 0 and np.isfinite(r["sup_mid"]) and close > 0:
        sl, sh, sm = float(r["sup_low"]), float(r["sup_hi"]), float(r["sup_mid"])
        out["drz_in_support_zone"] = (close >= sl and close <= sh)
        out["drz_dist_to_nearest_support_bps"] = (close - sm) / close * 10_000.0
        if int(r["sup_piv_idx"]) >= 0:
            out["drz_bars_since_support_pivot"] = bar - int(r["sup_piv_idx"])
        out["drz_zone_sup_pos_pct"] = float(r["sup_pos_pct"]) if np.isfinite(r["sup_pos_pct"]) else np.nan
        out["drz_zone_sup_net"] = float(r["sup_net"]) if np.isfinite(r["sup_net"]) else np.nan
    if int(r["n_active_res"]) > 0 and np.isfinite(r["res_mid"]) and close > 0:
        rl, rh, rm = float(r["res_low"]), float(r["res_hi"]), float(r["res_mid"])
        out["drz_in_resistance_zone"] = (close >= rl and close <= rh)
        out["drz_dist_to_nearest_resistance_bps"] = (close - rm) / close * 10_000.0
        if int(r["res_piv_idx"]) >= 0:
            out["drz_bars_since_resistance_pivot"] = bar - int(r["res_piv_idx"])
        out["drz_zone_res_pos_pct"] = float(r["res_pos_pct"]) if np.isfinite(r["res_pos_pct"]) else np.nan
        out["drz_zone_res_net"] = float(r["res_net"]) if np.isfinite(r["res_net"]) else np.nan

    # Recent signals — look in the last RECLAIM_WINDOW_BARS bars (inclusive of current)
    lo = max(0, pos - RECLAIM_WINDOW_BARS + 1)
    win = drz.iloc[lo:pos + 1]
    out["drz_recent_RC"] = bool(win["sig_rc"].sum() > 0)
    out["drz_recent_RE"] = bool(win["sig_re"].sum() > 0)

    return out


def build_for_tf(tf_period: str, fire_universe_path: Path) -> pd.DataFrame:
    """Compute DRZ panel per (asset) at fire timestamps.

    tf_period: '5MIN' or '15MIN' (chart-tf for DRZ).
    fire_universe_path: parquet with at least (asset, slug, fire_us).
    """
    fires = pd.read_parquet(fire_universe_path)
    print(f"  fires: {len(fires):,} rows from {fire_universe_path.name}")

    parts = []
    for asset in ASSETS:
        print(f"  [{asset} {tf_period}] loading klines...")
        k = load_klines(asset, source="binance-spot-ws", period_id=tf_period)
        if len(k) == 0:
            print(f"   no klines for {asset} — skip")
            continue
        print(f"   {len(k)} bars; computing DRZ panel...")
        drz = build_drz_bars(k)

        sub = fires[fires["asset"] == asset].copy()
        # dedupe fires by (slug, fire_us) — fire universe has multiple offsets per slug
        # but DRZ lookup depends only on (asset, fire_us) so we can compute per row.
        if len(sub) == 0:
            continue
        print(f"   {len(sub):,} fire rows to enrich")
        feats = sub["fire_us"].astype("int64").map(lambda fu: lookup_drz_state(drz, int(fu)))
        feats_df = pd.json_normalize(feats).reset_index(drop=True)
        sub = sub.reset_index(drop=True)
        joined = pd.concat([sub, feats_df], axis=1)
        parts.append(joined)
        del drz, k

    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    return out


def main():
    t0 = time.time()
    print("=" * 72)
    print("DRZ PANEL BUILD")
    print("=" * 72)

    # 5m: drz on 5MIN chart-tf, fired on 5m fire universe
    print("\n--- 5m chart-tf -> 5m fire universe ---")
    fu5 = RES / "hybrid_fire_universe_5m.parquet"
    p5 = build_for_tf("5MIN", fu5)
    out5 = RES / "drz_panel_5m.parquet"
    p5.to_parquet(out5, index=False, compression="zstd")
    print(f"  wrote {out5} ({len(p5):,} rows, {os.path.getsize(out5)/1024/1024:.1f} MB)")

    # 15m: drz on 15MIN chart-tf, fired on 15m fire universe
    print("\n--- 15m chart-tf -> 15m fire universe ---")
    fu15 = RES / "hybrid_fire_universe_15m.parquet"
    p15 = build_for_tf("15MIN", fu15)
    out15 = RES / "drz_panel_15m.parquet"
    p15.to_parquet(out15, index=False, compression="zstd")
    print(f"  wrote {out15} ({len(p15):,} rows, {os.path.getsize(out15)/1024/1024:.1f} MB)")

    print(f"\nDONE in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
