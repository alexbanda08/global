"""Build feature panel on PRODUCTION fills (fills.csv) at the actual production
fire_us timestamps. Mirrors build_master_5m_panel.py / build_master_15m_panel.py
but iterates over fills.csv fires (filtered to f7_mode='off') so we can test
indicator overlays as gates on top of the deployed sleeves (momo_v1, momo_v2,
sniper) across both 5m and 15m timeframes.

Inputs:
  strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv (~10968 rows)
  data/v4/canonical/klines_1s/binance_1s_28d.parquet
  data/v4/canonical/chainlink_rtds.parquet (via load_chainlink_asof)
  data/v4/canonical/klines_*  (via load_klines_asof)
  L25 books via load_orderbook_l25_streaming

Output:
  data/v4/canonical/_results/prod_fills_with_indicators.parquet

Run: py strategy_lab/overnight_2026_05_23/build_prod_fills_panel.py [--limit N]
"""
from __future__ import annotations
import argparse, math, sys
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

FILLS_CSV = ROOT / "strategy_lab" / "markov_filter" / "_results" / "backtest_prod_strats" / "fills.csv"
KL1S      = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT       = ROOT / "data" / "v4" / "canonical" / "_results" / "prod_fills_with_indicators.parquet"

TF_TO_WIN_S = {"5m": 300, "15m": 900}


# ---------------------------------------------------------------------
# 1s feature builders (per asset)
# ---------------------------------------------------------------------
def build_1s_arrays(asset: str) -> dict:
    df = pd.read_parquet(KL1S)
    sym = f"BINANCE_SPOT_{asset.upper()}_USDT"
    df = df[df.symbol_id == sym].copy()
    df = df.sort_values(["time_period_start_us", "source"])
    df = df.drop_duplicates("time_period_start_us", keep="last").reset_index(drop=True)
    ts   = df["time_period_start_us"].to_numpy()
    cls  = df["price_close"].to_numpy()
    qvol = df["quote_volume"].to_numpy()
    tbq  = df["taker_buy_quote"].to_numpy()
    cvd_1s = 2.0 * tbq - qvol
    cvd_cum = np.cumsum(cvd_1s); vol_cum = np.cumsum(qvol)
    def _ema(x, n):
        a = 2.0/(n+1.0); out = np.empty_like(x); out[0] = x[0]
        for i in range(1, len(x)): out[i] = a*x[i] + (1.0-a)*out[i-1]
        return out
    ema12 = _ema(cls, 12); ema26 = _ema(cls, 26)
    macd_line = ema12 - ema26; macd_sig = _ema(macd_line, 9); macd_hist = macd_line - macd_sig
    return {"ts": ts, "cls": cls, "qvol": qvol,
            "cvd_cum": cvd_cum, "vol_cum": vol_cum,
            "macd_line": macd_line, "macd_sig": macd_sig, "macd_hist": macd_hist,
            "log_cls": np.log(np.where(cls>0, cls, np.nan))}


def cvd_slope(arrs, t_us, w):
    ts = arrs["ts"]; cc = arrs["cvd_cum"]
    i = int(np.searchsorted(ts, t_us, side="right")) - 1
    if i < w: return float("nan")
    return float(cc[i] - cc[i-w])


def rvol(arrs, t_us, win=30, base=300):
    ts = arrs["ts"]; vc = arrs["vol_cum"]
    i = int(np.searchsorted(ts, t_us, side="right")) - 1
    if i < base: return float("nan")
    rec = vc[i] - vc[i-win]; bas = vc[i] - vc[i-base]
    if bas <= 0: return float("nan")
    exp = bas * (win/base)
    if exp <= 0: return float("nan")
    return float(rec/exp)


def macd_at(arrs, t_us):
    ts = arrs["ts"]
    i = int(np.searchsorted(ts, t_us, side="right")) - 1
    if i < 35: return (float("nan"),)*3
    return (float(arrs["macd_line"][i]), float(arrs["macd_sig"][i]), float(arrs["macd_hist"][i]))


def sigma(arrs, t_us, win=900):
    ts = arrs["ts"]; lc = arrs["log_cls"]
    i = int(np.searchsorted(ts, t_us, side="right")) - 1
    if i < win+1: return float("nan")
    c = lc[i-win:i+1]
    if not np.isfinite(c).all(): return float("nan")
    r = np.diff(c)
    return float(np.std(r, ddof=1)) if len(r) > 1 else float("nan")


def s_now(arrs, t_us):
    ts = arrs["ts"]; cls = arrs["cls"]
    i = int(np.searchsorted(ts, t_us, side="right")) - 1
    if i < 0 or i >= len(cls): return float("nan")
    return float(cls[i])


def rsi_14(eu, cl, anchor_us):
    closes = []
    for off_s in range(-840, 1, 60):
        idx = int(np.searchsorted(eu, anchor_us + off_s*1_000_000, side="right")) - 1
        if idx < 0 or idx >= len(cl): return float("nan")
        c = float(cl[idx])
        if not math.isfinite(c) or c <= 0: return float("nan")
        closes.append(c)
    if len(closes) < 15: return float("nan")
    arr = np.asarray(closes, dtype=np.float64); r = np.log(arr[1:]/arr[:-1])
    g = np.where(r>0, r, 0.0).mean(); l = np.where(r<0, -r, 0.0).mean()
    if l == 0: return 100.0 if g > 0 else 50.0
    if g == 0: return 0.0
    rs = g/l; return 100.0 - 100.0/(1.0+rs)


def micro_at(books, slug, side, fire_us, lat=85_000, stale=60_000_000):
    series = books.get((slug, side))
    if series is None: return None
    ts, ap, asz, bp, bsz = series
    target = fire_us + lat
    j = int(np.searchsorted(ts, target, side="right")) - 1
    if j < 0 or j >= len(ts): return None
    if (target - ts[j]) > stale: return None
    ap0 = float(ap[j, 0]); bp0 = float(bp[j, 0])
    az0 = float(asz[j, 0]); bz0 = float(bsz[j, 0])
    if not (np.isfinite(ap0) and np.isfinite(bp0) and ap0 > bp0 + 1e-9): return None
    if not (np.isfinite(az0) and np.isfinite(bz0) and az0+bz0 > 0): return None
    mid = (ap0+bp0)/2.0
    micro = (bz0*ap0 + az0*bp0)/(bz0+az0)
    spread_bp = (ap0-bp0)/mid * 10_000
    bid5 = float(np.nansum(np.where(np.isfinite(bsz[j,:5]), bsz[j,:5], 0)))
    ask5 = float(np.nansum(np.where(np.isfinite(asz[j,:5]), asz[j,:5], 0)))
    imb5 = (bid5-ask5)/(bid5+ask5) if (bid5+ask5) > 0 else float("nan")
    return {"mid": mid, "micro": micro,
            "micro_minus_mid_bp": (micro-mid)/mid*10_000,
            "spread_bp": spread_bp, "imb5": imb5,
            "best_bid": bp0, "best_ask": ap0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    print(f"[1] loading {FILLS_CSV.name}...")
    fires = pd.read_csv(FILLS_CSV)
    print(f"    {len(fires):,} total fires")
    fires = fires[fires.f7_mode == "off"].copy()
    print(f"    {len(fires):,} after f7_mode=='off' filter")

    # Derive ts. slot_start_us = (ws_s + window_s) * 1e6   (NOT ws_s * 1e6 — see CLAUDE.md)
    # production fire_us = ws_s + fire_offset_s (where offset = 120 momo_v1, 60 momo_v2,
    # window_s sniper). slot_start = ws_s + window_s.
    fires["window_s"] = fires["tf"].map(TF_TO_WIN_S).astype("int64")
    fires["ws_us"] = (fires["ws_s"].astype("int64")) * 1_000_000
    fires["slot_start_us"] = fires["ws_us"] + fires["window_s"] * 1_000_000
    fires["slot_end_us"] = fires["slot_start_us"] + fires["window_s"] * 1_000_000
    fires["fire_offset_s"] = (fires["fire_us"] - fires["ws_us"]) // 1_000_000
    fires["direction"] = fires["signal"]    # UP / DOWN
    fires["fire_s"] = fires["fire_us"] // 1_000_000

    if args.limit:
        rng = np.random.default_rng(42)
        fires = fires.iloc[rng.permutation(len(fires))[:args.limit]].copy()
        print(f"    subsampled to {len(fires):,}")

    print(f"[2] per-asset 1s arrays + chainlink + 1m klines + Markov labels...")
    one_s = {}; ck_eu = {}; ck_px = {}; km_eu = {}; km_cl = {}
    m1v_eu = {}; m1v_lab = {}; m5v_eu = {}; m5v_lab = {}
    m1f_eu = {}; m1f_lab = {}; m5f_eu = {}; m5f_lab = {}
    for a in ("BTC", "ETH", "SOL"):
        print(f"   [{a}] 1s arrays...")
        one_s[a] = build_1s_arrays(a)
        print(f"   [{a}] chainlink...")
        ck_eu[a], ck_px[a] = load_chainlink_asof(a)
        print(f"   [{a}] 1m klines...")
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

    print(f"[3] L25 books — per asset, batched by slug...")
    books_by_asset = {}
    for a, sub in fires.groupby("asset"):
        slugs = set(sub["slug"].unique())
        books_by_asset[a] = load_orderbook_l25_streaming(
            a, slugs=slugs, subsample_1hz=True,
            min_ts_us=int(sub["fire_us"].min()) - 60_000_000,
            max_ts_us=int(sub["slot_end_us"].max()) + 60_000_000,
        )
        print(f"   [{a}] L25 keys: {len(books_by_asset[a]):,}")

    print(f"[4] per-fire loop ({len(fires):,} rows)...")
    rows = []
    for idx, r in enumerate(fires.itertuples(index=False)):
        if idx % 1000 == 0: print(f"   row {idx:,}/{len(fires):,}")
        a = r.asset
        oa_set = [x for x in ("BTC", "ETH", "SOL") if x != a]
        fire_us = int(r.fire_us)
        slot_start_us = int(r.slot_start_us)
        slot_end_us = int(r.slot_end_us)
        tau_s = (slot_end_us - fire_us) / 1e6

        # ---- A. FV ----
        i_ck = int(np.searchsorted(ck_eu[a], slot_start_us, side="right")) - 1
        strike = float(ck_px[a][i_ck]) if i_ck >= 0 else float("nan")
        sn = s_now(one_s[a], fire_us)
        sg = sigma(one_s[a], fire_us, 900)
        sg5 = sigma(one_s[a], fire_us, 300)
        if (np.isfinite(strike) and np.isfinite(sn) and np.isfinite(sg)
                and sg > 0 and tau_s > 0):
            z = math.log(sn/strike)/(sg*math.sqrt(tau_s))
            fair_up = float(norm.cdf(z))
        else:
            fair_up = float("nan")

        ev = float(r.vwap) if np.isfinite(r.vwap) else float("nan")
        if r.direction == "UP":
            fair_edge_bp = (fair_up - ev)*10_000 if (np.isfinite(fair_up) and np.isfinite(ev)) else float("nan")
        else:
            fair_edge_bp = ((1 - fair_up) - ev)*10_000 if (np.isfinite(fair_up) and np.isfinite(ev)) else float("nan")

        # ---- B. CVD slopes ----
        c30 = cvd_slope(one_s[a], fire_us, 30)
        c60 = cvd_slope(one_s[a], fire_us, 60)
        c120 = cvd_slope(one_s[a], fire_us, 120)
        ca30 = (c30 > 0) == (r.direction == "UP") if np.isfinite(c30) else False
        ca60 = (c60 > 0) == (r.direction == "UP") if np.isfinite(c60) else False
        ca120 = (c120 > 0) == (r.direction == "UP") if np.isfinite(c120) else False

        # ---- C. MACD ----
        ml, ms, mh = macd_at(one_s[a], fire_us)
        macd_agree = (mh > 0) == (r.direction == "UP") if np.isfinite(mh) else False

        # ---- E. RVOL ----
        rv1 = rvol(one_s[a], fire_us, 30, 300)
        rv2 = rvol(one_s[a], fire_us, 60, 900)

        # ---- F. Microstructure ----
        side = "Up" if r.direction == "UP" else "Down"
        mp = micro_at(books_by_asset[a], r.slug, side, fire_us)
        if mp is None:
            micro = mid = micro_dev_bp = spread_bp = imb5 = best_bid = best_ask = float("nan")
        else:
            micro = mp["micro"]; mid = mp["mid"]; micro_dev_bp = mp["micro_minus_mid_bp"]
            spread_bp = mp["spread_bp"]; imb5 = mp["imb5"]
            best_bid = mp["best_bid"]; best_ask = mp["best_ask"]

        # ---- G. Markov ----
        m1v = regime_at_us(m1v_eu[a], m1v_lab[a], fire_us)
        m5v = regime_at_us(m5v_eu[a], m5v_lab[a], fire_us)
        m1f = regime_at_us(m1f_eu[a], m1f_lab[a], fire_us)
        m5f = regime_at_us(m5f_eu[a], m5f_lab[a], fire_us)
        def _p(rg):
            if rg < 0: return False
            return (rg == 1 and r.direction == "UP") or (rg == 0 and r.direction == "DOWN")
        m1v_pass = _p(m1v); m5v_pass = _p(m5v)
        m1f_pass = _p(m1f); m5f_pass = _p(m5f)

        # ---- H. F7 RSI ----
        rsi = rsi_14(km_eu[a], km_cl[a], fire_us)
        if np.isfinite(rsi):
            f7_pass = (rsi > 50 and r.direction == "UP") or (rsi < 50 and r.direction == "DOWN")
        else:
            f7_pass = False

        # ---- I. Cross-asset dev_bps ----
        def _dev(oa):
            sn_o = s_now(one_s[oa], fire_us)
            ts_o = one_s[oa]["ts"]; cls_o = one_s[oa]["cls"]; qvol_o = one_s[oa]["qvol"]
            i_end = int(np.searchsorted(ts_o, fire_us, side="right")) - 1
            if i_end < 900 or not np.isfinite(sn_o): return float("nan")
            pv = cls_o[i_end-900:i_end+1] * qvol_o[i_end-900:i_end+1]
            tv = qvol_o[i_end-900:i_end+1].sum()
            if tv <= 0: return float("nan")
            vw = float(pv.sum()/tv)
            if not (np.isfinite(vw) and vw > 0): return float("nan")
            return float(math.log(sn_o/vw)*10_000)
        oa = _dev(oa_set[0]); ob = _dev(oa_set[1])
        ss = lambda x: (x > 0) == (r.direction == "UP") if np.isfinite(x) else False
        ca = ss(oa); cb = ss(ob); cp = ca or cb; cf = ca and cb

        # ---- own asset dev_bps (vs 15m anchored vwap) ----
        ts_a = one_s[a]["ts"]; cls_a = one_s[a]["cls"]; qvol_a = one_s[a]["qvol"]
        i_end_a = int(np.searchsorted(ts_a, fire_us, side="right")) - 1
        if i_end_a >= 900 and np.isfinite(sn):
            pv = cls_a[i_end_a-900:i_end_a+1] * qvol_a[i_end_a-900:i_end_a+1]
            tv = qvol_a[i_end_a-900:i_end_a+1].sum()
            if tv > 0:
                vw_a = float(pv.sum()/tv)
                dev_bps_self = float(math.log(sn/vw_a)*10_000) if vw_a > 0 else float("nan")
                vwap_15m = vw_a
            else:
                dev_bps_self = float("nan"); vwap_15m = float("nan")
        else:
            dev_bps_self = float("nan"); vwap_15m = float("nan")

        rows.append({
            # base identifiers — carry through production metadata
            "slug": r.slug, "asset": a, "tf": r.tf, "strategy": r.strategy,
            "f7_mode": r.f7_mode, "cell": r.cell,
            "ws_s": int(r.ws_s), "fire_us": fire_us, "fire_s": int(r.fire_s),
            "fire_offset_s": int(r.fire_offset_s),
            "slot_start_us": slot_start_us, "slot_end_us": slot_end_us,
            "window_s": int(r.window_s), "tau_sec": int(tau_s),
            "direction": r.direction, "outcome": r.outcome, "won": bool(r.won),
            "entry_vwap": ev, "pnl_legacy_usd": float(r.pnl),
            "shares": float(r.shares),
            # production markov flags (carry through for cross-check)
            "prod_markov_w20_1m_voladaptive": bool(r.markov_pass_w20_1m_voladaptive),
            "prod_markov_w20_1m_fixed": bool(r.markov_pass_w20_1m_fixed),
            "prod_markov_w20_5m_voladaptive": bool(r.markov_pass_w20_5m_voladaptive),
            "prod_markov_w20_5m_fixed": bool(r.markov_pass_w20_5m_fixed),
            # base feature: own dev_bps + sigmas
            "s_now": sn, "vwap_15m": vwap_15m, "dev_bps": dev_bps_self,
            "sigma_per_sqrt_sec_15m": sg, "sigma_per_sqrt_sec_5m": sg5,
            # A. FV
            "strike": strike, "fair_up": fair_up, "fair_edge_bp": fair_edge_bp,
            # B. CVD
            "cvd_30s": c30, "cvd_60s": c60, "cvd_120s": c120,
            "cvd_agree_30s": ca30, "cvd_agree_60s": ca60, "cvd_agree_120s": ca120,
            # C. MACD
            "macd_line": ml, "macd_sig": ms, "macd_hist": mh, "macd_agree": macd_agree,
            # E. RVOL
            "rvol_30_300": rv1, "rvol_60_900": rv2,
            # F. Micro
            "mid": mid, "micro": micro, "micro_minus_mid_bp": micro_dev_bp,
            "spread_bp": spread_bp, "imb5": imb5,
            "best_bid": best_bid, "best_ask": best_ask,
            # G. Markov (fresh @ fire_us)
            "m1v_pass": m1v_pass, "m5v_pass": m5v_pass,
            "m1f_pass": m1f_pass, "m5f_pass": m5f_pass,
            "m1v_regime": int(m1v), "m5v_regime": int(m5v),
            # H. F7
            "rsi_14": rsi, "f7_pass": f7_pass,
            # I. Cross-asset
            "cross_a_dev_bp": oa, "cross_b_dev_bp": ob,
            "cross_partial_agree": cp, "cross_full_agree": cf,
        })

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(OUT, index=False)
    print(f"\n[done] {len(out):,} rows -> {OUT}")
    print(f"\nfeature coverage (% non-NaN, or True% for bool):")
    for c in out.columns:
        if out[c].dtype == bool:
            cov = 100 * out[c].mean()
            print(f"  {c:35s}  {cov:5.1f}% True")
        else:
            cov = 100 * out[c].notna().mean()
            print(f"  {c:35s}  {cov:5.1f}% non-NaN")


if __name__ == "__main__":
    main()
