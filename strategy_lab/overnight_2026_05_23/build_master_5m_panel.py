"""Master 5m feature panel — joins every untested signal onto one row per fire.

Inputs:
  data/v4/canonical/_results/vwap_continuation_5m_per_fire.parquet (40 210 fires)
  data/v4/canonical/klines_1s/binance_1s_28d.parquet (5.5M rows)
  data/v4/canonical/chainlink_rtds.parquet
  data/v4/canonical/orderbook L25 streaming
  binance 1m klines (for Markov + RSI)

Output:
  data/v4/canonical/_results/master_5m_panel.parquet  (one row per fire, ~30 features)

Feature blocks:
  A. Fair-value (FV): strike, fair_up, fair_edge_bps  (mlmodelpoly Φ(z))
  B. 1s CVD slope: cvd_slope_30s, _60s, _120s, cvd_agree
  C. 1s MACD(12,26,9) on binance close: macd_line, macd_signal, macd_hist, macd_agree
  D. Sigma realized vol: sigma_5m, sigma_15m (per √sec)
  E. RVOL: vol_30s / vol_5min trailing mean
  F. L25 microprice + spread + depth imbalance (top 5L)
  G. Markov regime: m1v_pass, m5v_pass, m1f_pass, m5f_pass
  H. F7 RSI(14, Wilder simple-mean): rsi_14, f7_pass
  I. Cross-asset dev_bps: other_a_dev_bps, other_b_dev_bps, cross_partial, cross_full
  J. PM dip indicator: best_ask_drop_3s, mid_drop_3s (from L25 1Hz subsample)

Run: py strategy_lab/overnight_2026_05_23/build_master_5m_panel.py [--limit N]
"""
from __future__ import annotations
import argparse, gc, math, sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "markov_filter"))

from load import (load_chainlink_asof, load_klines_asof,
                  load_orderbook_l25_streaming)
from markov_regime_micro import build_labels_for_asset, regime_at_us

PT_IN  = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_continuation_5m_per_fire.parquet"
KL1S   = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT    = ROOT / "data" / "v4" / "canonical" / "_results" / "master_5m_panel.parquet"
WINDOW_S = 300   # 5m slots

# ---------------------------------------------------------------------
# 1s feature builders (per asset, pre-load once)
# ---------------------------------------------------------------------
def build_1s_arrays(asset: str) -> dict:
    """Load 1s parquet for asset, build raw arrays + EMAs + CVD cumsum."""
    df = pd.read_parquet(KL1S)
    sym = f"BINANCE_SPOT_{asset.upper()}_USDT"
    df = df[df.symbol_id == sym].copy()
    df = df.sort_values(["time_period_start_us", "source"])
    df = df.drop_duplicates("time_period_start_us", keep="last").reset_index(drop=True)

    ts   = df["time_period_start_us"].to_numpy()
    cls  = df["price_close"].to_numpy()
    qvol = df["quote_volume"].to_numpy()
    tbq  = df["taker_buy_quote"].to_numpy()
    cvd_1s = 2.0 * tbq - qvol                     # signed taker volume USD
    cvd_cum = np.cumsum(cvd_1s)                   # for fast slope calc
    vol_cum = np.cumsum(qvol)                     # for RVOL

    # MACD(12, 26, 9) on 1s closes (1-second EMA, per the standard MACD spec at this TF)
    # MACD on 1s is noisy — but exactly what was untested per synthesis.
    def _ema(x, n):
        a = 2.0 / (n + 1.0)
        out = np.empty_like(x); out[0] = x[0]
        for i in range(1, len(x)):
            out[i] = a * x[i] + (1.0 - a) * out[i-1]
        return out

    ema12 = _ema(cls, 12)
    ema26 = _ema(cls, 26)
    macd_line = ema12 - ema26
    macd_sig  = _ema(macd_line, 9)
    macd_hist = macd_line - macd_sig

    return {
        "ts": ts, "cls": cls, "qvol": qvol,
        "cvd_1s": cvd_1s, "cvd_cum": cvd_cum, "vol_cum": vol_cum,
        "macd_line": macd_line, "macd_sig": macd_sig, "macd_hist": macd_hist,
        "log_cls": np.log(np.where(cls > 0, cls, np.nan)),
    }


def cvd_slope(arrs, target_us, window_s):
    """Net signed taker volume (USD) over last `window_s` seconds at `target_us`."""
    ts = arrs["ts"]; cvd_cum = arrs["cvd_cum"]
    i_end = int(np.searchsorted(ts, target_us, side="right")) - 1
    if i_end < window_s:
        return float("nan")
    i_start = i_end - window_s
    return float(cvd_cum[i_end] - cvd_cum[i_start])


def rvol(arrs, target_us, window_s=30, base_window_s=300):
    """Volume over `window_s` divided by mean volume over `base_window_s`."""
    ts = arrs["ts"]; vc = arrs["vol_cum"]
    i_end = int(np.searchsorted(ts, target_us, side="right")) - 1
    if i_end < base_window_s:
        return float("nan")
    recent = vc[i_end] - vc[i_end - window_s]
    base   = vc[i_end] - vc[i_end - base_window_s]
    if base <= 0: return float("nan")
    expected = base * (window_s / base_window_s)
    if expected <= 0: return float("nan")
    return float(recent / expected)


def macd_at(arrs, target_us):
    ts = arrs["ts"]
    i = int(np.searchsorted(ts, target_us, side="right")) - 1
    if i < 35:                                    # need ≥ slow EMA + signal
        return (float("nan"),) * 3
    return (float(arrs["macd_line"][i]),
            float(arrs["macd_sig"][i]),
            float(arrs["macd_hist"][i]))


def sigma_per_sqrt_sec(arrs, target_us, window_s=900):
    """Std of 1s log-returns over `window_s` ending at `target_us`."""
    ts = arrs["ts"]; lc = arrs["log_cls"]
    i_end = int(np.searchsorted(ts, target_us, side="right")) - 1
    if i_end < window_s + 1:
        return float("nan")
    closes = lc[i_end - window_s : i_end + 1]
    if not np.isfinite(closes).all(): return float("nan")
    rets = np.diff(closes)
    return float(np.std(rets, ddof=1)) if len(rets) > 1 else float("nan")


def s_now(arrs, target_us):
    ts = arrs["ts"]; cls = arrs["cls"]
    i = int(np.searchsorted(ts, target_us, side="right")) - 1
    if i < 0 or i >= len(cls): return float("nan")
    return float(cls[i])


# ---------------------------------------------------------------------
# F7 RSI(14) — production simple-mean Wilder (per CLAUDE.md)
# ---------------------------------------------------------------------
def rsi_14_wilder(eu_1m: np.ndarray, cl_1m: np.ndarray, anchor_us: int) -> float:
    """15 closes at offsets [-840, -780, ..., -60, 0] from `anchor_us`."""
    closes = []
    for off_s in range(-840, 1, 60):
        idx = int(np.searchsorted(eu_1m, anchor_us + off_s * 1_000_000, side="right")) - 1
        if idx < 0 or idx >= len(cl_1m):
            return float("nan")
        c = float(cl_1m[idx])
        if not math.isfinite(c) or c <= 0: return float("nan")
        closes.append(c)
    if len(closes) < 15: return float("nan")
    arr = np.asarray(closes, dtype=np.float64)
    rets = np.log(arr[1:] / arr[:-1])
    gains  = np.where(rets > 0,  rets, 0.0).mean()
    losses = np.where(rets < 0, -rets, 0.0).mean()
    if losses == 0: return 100.0 if gains > 0 else 50.0
    if gains  == 0: return 0.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


# ---------------------------------------------------------------------
# Microprice from L25 at fire_us
# ---------------------------------------------------------------------
def microprice_at(books_idx, slug, outcome_side, fire_us, latency_us=85_000,
                  max_stale_us=60_000_000):
    series = books_idx.get((slug, outcome_side))
    if series is None: return None
    ts, ap, asz, bp, bsz = series
    target = fire_us + latency_us
    j = int(np.searchsorted(ts, target, side="right")) - 1
    if j < 0 or j >= len(ts): return None
    if (target - ts[j]) > max_stale_us: return None
    ap0 = float(ap[j, 0]); bp0 = float(bp[j, 0])
    az0 = float(asz[j, 0]); bz0 = float(bsz[j, 0])
    if not (np.isfinite(ap0) and np.isfinite(bp0) and ap0 > bp0 + 1e-9): return None
    if not (np.isfinite(az0) and np.isfinite(bz0) and az0 + bz0 > 0): return None
    mid       = (ap0 + bp0) / 2.0
    micro     = (bz0 * ap0 + az0 * bp0) / (bz0 + az0)
    spread_bp = (ap0 - bp0) / mid * 10_000
    # 5L depth imbalance
    bid5 = float(np.nansum(np.where(np.isfinite(bsz[j, :5]), bsz[j, :5], 0)))
    ask5 = float(np.nansum(np.where(np.isfinite(asz[j, :5]), asz[j, :5], 0)))
    imb5 = (bid5 - ask5) / (bid5 + ask5) if (bid5 + ask5) > 0 else float("nan")
    return {
        "mid": mid, "micro": micro, "micro_minus_mid_bp": (micro - mid) / mid * 10_000,
        "spread_bp": spread_bp, "imb5": imb5,
        "best_ask": ap0, "best_bid": bp0,
    }


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                     help="random subsample N fires for fast dev")
    args = ap.parse_args()

    print(f"[1] loading per-fire parquet {PT_IN.name}...")
    fires = pd.read_parquet(PT_IN)
    print(f"    {len(fires):,} fires")
    if args.limit:
        rng = np.random.default_rng(42)
        fires = fires.iloc[rng.permutation(len(fires))[:args.limit]].copy()
        print(f"    subsampled to {len(fires):,}")

    # ws_s + slot timestamps
    fires["ws_s"]         = fires["fire_s"] - fires["fire_offset_s"]
    fires["slot_start_us"]= fires["ws_s"] * 1_000_000      # NOTE: in vwap_cont, fire_s IS slot_start + fire_offset; ws_s = fire_s - offset = slot_start
    fires["slot_end_us"]  = fires["slot_start_us"] + WINDOW_S * 1_000_000

    # ---------------------------------------------------------------------
    print(f"[2] per-asset 1s arrays + chainlink + 1m klines + Markov labels...")
    one_s = {}; ck_eu = {}; ck_px = {}; km_eu = {}; km_cl = {}
    m1v_eu = {}; m1v_lab = {}; m5v_eu = {}; m5v_lab = {}; m1f_eu = {}; m1f_lab = {}; m5f_eu = {}; m5f_lab = {}
    for a in ("BTC", "ETH", "SOL"):
        print(f"   [{a}] 1s arrays...")
        one_s[a] = build_1s_arrays(a)
        print(f"   [{a}] chainlink...")
        ck_eu[a], ck_px[a] = load_chainlink_asof(a)
        print(f"   [{a}] 1m klines + RSI base...")
        eu, cl = load_klines_asof(a, "binance-spot-ws", "1MIN")
        km_eu[a] = eu.astype("int64"); km_cl[a] = cl.astype("float64")
        print(f"   [{a}] Markov labels...")
        e, _, lab = build_labels_for_asset(a, window_bars=20, bar_minutes=1, mode="vol_adaptive")
        m1v_eu[a] = e.astype("int64"); m1v_lab[a] = lab.astype("int8")
        e, _, lab = build_labels_for_asset(a, window_bars=20, bar_minutes=5, mode="vol_adaptive")
        m5v_eu[a] = e.astype("int64"); m5v_lab[a] = lab.astype("int8")
        e, _, lab = build_labels_for_asset(a, window_bars=20, bar_minutes=1, mode="fixed")
        m1f_eu[a] = e.astype("int64"); m1f_lab[a] = lab.astype("int8")
        e, _, lab = build_labels_for_asset(a, window_bars=20, bar_minutes=5, mode="fixed")
        m5f_eu[a] = e.astype("int64"); m5f_lab[a] = lab.astype("int8")

    # ---------------------------------------------------------------------
    print(f"[3] L25 books — per asset, batched by slug...")
    books_by_asset = {}
    for a, sub in fires.groupby("asset"):
        slugs = set(sub["slug"].unique())
        books_by_asset[a] = load_orderbook_l25_streaming(
            a, slugs=slugs, subsample_1hz=True,
            min_ts_us=int(sub["fire_us"].min()) - 60_000_000,
            max_ts_us=int(sub["fire_us"].max()) + 300_000_000,
        )
        print(f"   [{a}] L25 keys: {len(books_by_asset[a]):,}")

    # ---------------------------------------------------------------------
    print(f"[4] per-fire feature loop...")
    rows = []
    for idx, r in enumerate(fires.itertuples(index=False)):
        if idx % 2000 == 0:
            print(f"   row {idx:,}/{len(fires):,}")
        a = r.asset
        oa_set = [x for x in ("BTC", "ETH", "SOL") if x != a]
        fire_us = int(r.fire_us)
        slot_start_us = int(r.slot_start_us)
        slot_end_us   = int(r.slot_end_us)
        tau_s = (slot_end_us - fire_us) / 1e6

        # ---- A. Fair value ----
        i_ck = int(np.searchsorted(ck_eu[a], slot_start_us, side="right")) - 1
        strike = float(ck_px[a][i_ck]) if i_ck >= 0 else float("nan")
        sn = s_now(one_s[a], fire_us)
        sg = sigma_per_sqrt_sec(one_s[a], fire_us, 900)
        sg5 = sigma_per_sqrt_sec(one_s[a], fire_us, 300)
        if (np.isfinite(strike) and np.isfinite(sn) and np.isfinite(sg) and
            sg > 0 and tau_s > 0):
            z = math.log(sn / strike) / (sg * math.sqrt(tau_s))
            fair_up = float(norm.cdf(z))
        else:
            fair_up = float("nan")

        # ---- entry_vwap available, compute edge per direction ----
        ev = float(r.entry_vwap) if r.entry_vwap is not None and np.isfinite(r.entry_vwap) else float("nan")
        if r.direction == "UP":
            fair_edge_bp = (fair_up - ev) * 10_000 if (np.isfinite(fair_up) and np.isfinite(ev)) else float("nan")
        else:
            fair_edge_bp = ((1 - fair_up) - ev) * 10_000 if (np.isfinite(fair_up) and np.isfinite(ev)) else float("nan")

        # ---- B. CVD slopes ----
        cvd_30  = cvd_slope(one_s[a], fire_us, 30)
        cvd_60  = cvd_slope(one_s[a], fire_us, 60)
        cvd_120 = cvd_slope(one_s[a], fire_us, 120)
        cvd_agree_30  = (cvd_30  > 0) == (r.direction == "UP") if np.isfinite(cvd_30)  else False
        cvd_agree_60  = (cvd_60  > 0) == (r.direction == "UP") if np.isfinite(cvd_60)  else False
        cvd_agree_120 = (cvd_120 > 0) == (r.direction == "UP") if np.isfinite(cvd_120) else False

        # ---- C. MACD ----
        macd_line, macd_sig, macd_hist = macd_at(one_s[a], fire_us)
        macd_agree = (macd_hist > 0) == (r.direction == "UP") if np.isfinite(macd_hist) else False

        # ---- E. RVOL ----
        rvol_30_300 = rvol(one_s[a], fire_us, 30, 300)
        rvol_60_900 = rvol(one_s[a], fire_us, 60, 900)

        # ---- F. Microprice ----
        outcome_side = "Up" if r.direction == "UP" else "Down"
        mp = microprice_at(books_by_asset[a], r.slug, outcome_side, fire_us)
        if mp is None:
            micro = mid = micro_dev_bp = spread_bp = imb5 = best_bid = best_ask = float("nan")
        else:
            micro = mp["micro"]; mid = mp["mid"]; micro_dev_bp = mp["micro_minus_mid_bp"]
            spread_bp = mp["spread_bp"]; imb5 = mp["imb5"]
            best_bid = mp["best_bid"]; best_ask = mp["best_ask"]

        # ---- G. Markov ----
        m1v_r = regime_at_us(m1v_eu[a], m1v_lab[a], fire_us)
        m5v_r = regime_at_us(m5v_eu[a], m5v_lab[a], fire_us)
        m1f_r = regime_at_us(m1f_eu[a], m1f_lab[a], fire_us)
        m5f_r = regime_at_us(m5f_eu[a], m5f_lab[a], fire_us)
        def _pass(rg):                 # BULL=1 → UP ok, BEAR=0 → DOWN ok; -1 unknown
            if rg < 0: return False
            return (rg == 1 and r.direction == "UP") or (rg == 0 and r.direction == "DOWN")
        m1v_pass = _pass(m1v_r); m5v_pass = _pass(m5v_r)
        m1f_pass = _pass(m1f_r); m5f_pass = _pass(m5f_r)

        # ---- H. F7 RSI ----
        rsi = rsi_14_wilder(km_eu[a], km_cl[a], fire_us)
        if np.isfinite(rsi):
            f7_pass = (rsi > 50 and r.direction == "UP") or (rsi < 50 and r.direction == "DOWN")
        else:
            f7_pass = False

        # ---- I. Cross-asset dev_bps at fire_us ----
        def _dev_other(other_a):
            sn_o = s_now(one_s[other_a], fire_us)
            # 15m anchored VWAP for the other asset at fire_us — approximate via
            # last 900 closes (≈ 15m of 1s data)
            ts_o = one_s[other_a]["ts"]; cls_o = one_s[other_a]["cls"]
            qvol_o = one_s[other_a]["qvol"]
            i_end = int(np.searchsorted(ts_o, fire_us, side="right")) - 1
            if i_end < 900 or not np.isfinite(sn_o): return float("nan")
            pv = cls_o[i_end-900:i_end+1] * qvol_o[i_end-900:i_end+1]
            tv = qvol_o[i_end-900:i_end+1].sum()
            if tv <= 0: return float("nan")
            vwap_o = float(pv.sum() / tv)
            if not (np.isfinite(vwap_o) and vwap_o > 0): return float("nan")
            return float((math.log(sn_o / vwap_o)) * 10_000)
        oa_dev = _dev_other(oa_set[0]); ob_dev = _dev_other(oa_set[1])
        same_sign = lambda x: (x > 0) == (r.direction == "UP") if np.isfinite(x) else False
        cross_a_agree = same_sign(oa_dev)
        cross_b_agree = same_sign(ob_dev)
        cross_partial = cross_a_agree or cross_b_agree
        cross_full    = cross_a_agree and cross_b_agree

        # ---- assemble row ----
        rows.append({
            "slug": r.slug, "asset": a, "fire_s": int(r.fire_s),
            "fire_us": fire_us, "fire_offset_s": int(r.fire_offset_s),
            "direction": r.direction, "outcome": r.outcome,
            "won": bool(r.won),
            "entry_vwap": ev, "pnl_legacy_usd": float(r.pnl_legacy_usd),
            "tau_sec": int(r.tau_sec),
            # base features (refreshed)
            "s_now": sn, "vwap_15m": float(r.vwap_15m),
            "dev_bps": float(r.dev_bps),
            "sigma_per_sqrt_sec_15m": sg,
            "sigma_per_sqrt_sec_5m":  sg5,
            # FV
            "strike": strike, "fair_up": fair_up, "fair_edge_bp": fair_edge_bp,
            # CVD
            "cvd_30s": cvd_30, "cvd_60s": cvd_60, "cvd_120s": cvd_120,
            "cvd_agree_30s": cvd_agree_30, "cvd_agree_60s": cvd_agree_60,
            "cvd_agree_120s": cvd_agree_120,
            # MACD 1s
            "macd_line": macd_line, "macd_sig": macd_sig, "macd_hist": macd_hist,
            "macd_agree": macd_agree,
            # RVOL
            "rvol_30_300": rvol_30_300, "rvol_60_900": rvol_60_900,
            # Microstructure
            "mid": mid, "micro": micro, "micro_minus_mid_bp": micro_dev_bp,
            "spread_bp": spread_bp, "imb5": imb5,
            "best_bid": best_bid, "best_ask": best_ask,
            # Markov
            "m1v_pass": m1v_pass, "m5v_pass": m5v_pass,
            "m1f_pass": m1f_pass, "m5f_pass": m5f_pass,
            "m1v_regime": int(m1v_r), "m5v_regime": int(m5v_r),
            # F7
            "rsi_14": rsi, "f7_pass": f7_pass,
            # Cross-asset
            "cross_a_dev_bp": oa_dev, "cross_b_dev_bp": ob_dev,
            "cross_partial_agree": cross_partial, "cross_full_agree": cross_full,
        })

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    print(f"\n[done] {len(out):,} rows → {OUT}")
    print(f"\ncolumns: {out.columns.tolist()}")
    print(f"\nfeature coverage (% non-NaN):")
    for c in out.columns:
        cov = 100 * out[c].notna().mean() if out[c].dtype != bool else 100.0
        print(f"  {c:30s}  {cov:5.1f}%")


if __name__ == "__main__":
    main()
