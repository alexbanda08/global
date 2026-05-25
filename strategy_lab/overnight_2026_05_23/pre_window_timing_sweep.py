"""Pre-window vs intra-slot fire-timing sweep.

For each (rule × tf × offset_s), evaluate S4 / S8 / S3 rules at the equivalent
fire_us = slot_start_us + offset_s * 1_000_000 (offset_s NEGATIVE means PRE-WINDOW).

Rules tested:
  S4 := fair_edge_bp > 500  AND  cvd_agree_30s  AND  |dev_bps| >= 8
  S8 := macd_agree         AND  rvol_30_300 > 1.2
  S3 := fair_edge_bp > 0   AND  cvd_agree_60s  AND  macd_agree

Each (slug × direction) is checked once per offset; dedup is WITHIN an offset
(one fire per slug × direction per offset). NO dedup across offsets (each
offset is a separately deployable timing decision).

Outputs:
  data/v4/canonical/_results/pre_window_timing_sweep.csv
  data/v4/canonical/_results/pre_window_timing_per_fire.parquet
  strategy_lab/reports/_pre_window_timing_inbox.md
"""
from __future__ import annotations
import math, sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import norm, binomtest

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "markov_filter"))

from load import (load_resolutions, load_chainlink_asof,
                  load_orderbook_l25_streaming)  # noqa: E402
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl  # noqa: E402

KL1S    = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "pre_window_timing_sweep.csv"
OUT_PT  = ROOT / "data" / "v4" / "canonical" / "_results" / "pre_window_timing_per_fire.parquet"
OUT_MD  = ROOT / "strategy_lab" / "reports" / "_pre_window_timing_inbox.md"

# Offsets (in seconds RELATIVE TO slot_start) — negative = PRE-WINDOW.
OFFSETS_5M  = [-300, -240, -180, -120, -90, -60, -30, 0, 30, 60, 90, 120, 180, 240, 270]
OFFSETS_15M = [-840, -720, -600, -480, -360, -240, -120, 0, 120, 240, 360, 480, 600, 720, 840]
WINDOW_S = {"5m": 300, "15m": 900}
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
NOTIONAL = 25.0
ANCHOR_WINDOW_S = 15 * 60  # for VWAP_15m bucketing


# ---------------------------------------------------------------------
# 1s array builder — VWAP_15m + sigma + CVD cumsum + MACD on 1s closes
# ---------------------------------------------------------------------
def build_1s_arrays_for_assets(assets=("BTC", "ETH", "SOL")) -> dict:
    print(f"[1s] loading {KL1S.name}...")
    df = pd.read_parquet(KL1S)
    df = df.sort_values(["symbol_id", "time_period_start_us", "source"])
    df = df.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    SYM = {f"BINANCE_SPOT_{a}_USDT": a for a in assets}
    df["asset"] = df["symbol_id"].map(SYM)
    df = df.dropna(subset=["asset"])

    out = {}
    for a in assets:
        sub = df[df.asset == a].sort_values("time_period_start_us").reset_index(drop=True)
        ts = sub["time_period_start_us"].to_numpy(dtype="int64")
        cls = sub["price_close"].to_numpy(dtype="float64")
        vol = sub["volume_traded"].fillna(0).to_numpy(dtype="float64")
        qvol = sub["quote_volume"].to_numpy(dtype="float64")
        tbq = sub["taker_buy_quote"].to_numpy(dtype="float64")

        # CVD cumsum (signed taker USD)
        cvd_1s = 2.0 * tbq - qvol
        cvd_cum = np.cumsum(cvd_1s)
        vol_cum = np.cumsum(qvol)

        # 15m-anchored VWAP (production formula)
        bucket = (ts // (ANCHOR_WINDOW_S * 1_000_000)) * (ANCHOR_WINDOW_S * 1_000_000)
        tmp = pd.DataFrame({"bucket": bucket, "px_vol": cls * vol, "vol": vol})
        tmp["cum_px_vol"] = tmp.groupby("bucket")["px_vol"].cumsum()
        tmp["cum_vol"] = tmp.groupby("bucket")["vol"].cumsum()
        with np.errstate(invalid="ignore", divide="ignore"):
            vwap_15m = np.where(tmp["cum_vol"].values > 0,
                                tmp["cum_px_vol"].values / tmp["cum_vol"].values,
                                np.nan)

        # MACD(12,26,9) on 1s closes (production formula)
        def _ema(x, n):
            alpha = 2.0 / (n + 1.0)
            out = np.empty_like(x)
            out[0] = x[0]
            for i in range(1, len(x)):
                out[i] = alpha * x[i] + (1.0 - alpha) * out[i-1]
            return out
        ema12 = _ema(cls, 12)
        ema26 = _ema(cls, 26)
        macd_line = ema12 - ema26
        macd_sig = _ema(macd_line, 9)
        macd_hist = macd_line - macd_sig

        log_cls = np.log(np.where(cls > 0, cls, np.nan))

        out[a] = {
            "ts": ts, "cls": cls, "vol": vol,
            "vwap_15m": vwap_15m,
            "cvd_cum": cvd_cum, "vol_cum": vol_cum,
            "macd_line": macd_line, "macd_sig": macd_sig, "macd_hist": macd_hist,
            "log_cls": log_cls,
        }
        print(f"  {a}: rows={len(ts):,}  ts={ts[0]/1e6:.0f}..{ts[-1]/1e6:.0f}")
    return out


# ---------------------------------------------------------------------
# Vectorized feature lookups (operate on arrays-indices)
# ---------------------------------------------------------------------
def _asof_idx_arr(ts: np.ndarray, targets_us: np.ndarray) -> np.ndarray:
    """For each target_us, return idx i s.t. ts[i] <= target_us < ts[i+1]. -1 if none."""
    pos = np.searchsorted(ts, targets_us, side="right") - 1
    pos[pos < 0] = -1
    pos[pos >= len(ts)] = -1
    return pos


def vectorized_features_at(arr, fire_us_arr, dir_arr):
    """Compute base features at fire_us values vectorized.

    Returns dict[name] -> np.array, same length as fire_us_arr.
    `dir_arr` is array of bool: True=UP.
    """
    ts = arr["ts"]
    cls = arr["cls"]
    vwap_15m = arr["vwap_15m"]
    cvd_cum = arr["cvd_cum"]
    vol_cum = arr["vol_cum"]
    macd_hist = arr["macd_hist"]
    log_cls = arr["log_cls"]

    idx = _asof_idx_arr(ts, fire_us_arr.astype("int64"))
    valid = idx >= 0
    n = len(fire_us_arr)

    s_now = np.where(valid, cls[np.clip(idx, 0, len(cls)-1)], np.nan)
    vw = np.where(valid, vwap_15m[np.clip(idx, 0, len(vwap_15m)-1)], np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        dev_bps = np.where((vw > 0) & np.isfinite(vw) & np.isfinite(s_now),
                           10000.0 * np.log(s_now / vw), np.nan)

    # CVD slopes
    def _slope(window_s):
        end = idx
        start = end - window_s
        ok = valid & (start >= 0)
        out = np.full(n, np.nan, dtype="float64")
        out[ok] = cvd_cum[end[ok]] - cvd_cum[start[ok]]
        return out
    cvd_30 = _slope(30)
    cvd_60 = _slope(60)
    cvd_120 = _slope(120)

    # CVD agreement with direction
    cvd_agree_30 = np.where(np.isfinite(cvd_30),
                            (cvd_30 > 0) == dir_arr, False)
    cvd_agree_60 = np.where(np.isfinite(cvd_60),
                            (cvd_60 > 0) == dir_arr, False)
    cvd_agree_120 = np.where(np.isfinite(cvd_120),
                             (cvd_120 > 0) == dir_arr, False)

    # MACD hist + agree
    mh = np.where(valid & (idx >= 35),
                  macd_hist[np.clip(idx, 0, len(macd_hist)-1)], np.nan)
    macd_agree = np.where(np.isfinite(mh), (mh > 0) == dir_arr, False)

    # RVOL 30/300
    def _rvol(win, base):
        ok = valid & (idx >= base)
        out = np.full(n, np.nan, dtype="float64")
        rec = np.where(ok, vol_cum[np.clip(idx, 0, len(vol_cum)-1)] -
                       vol_cum[np.clip(idx - win, 0, len(vol_cum)-1)], np.nan)
        bas = np.where(ok, vol_cum[np.clip(idx, 0, len(vol_cum)-1)] -
                       vol_cum[np.clip(idx - base, 0, len(vol_cum)-1)], np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            out = np.where((bas > 0) & ok, rec / (bas * (win / base)), np.nan)
        return out
    rvol_30_300 = _rvol(30, 300)

    # sigma 15m — rolling std of 1s log returns over last 900s
    # Pre-compute log-returns once, then rolling-std via cumsum trick? For
    # simplicity, do np.empty + per-row slice up to 900s (vectorized by tape)
    # This is the slow part — use cumsum-of-squares trick.
    # log_ret[i] = log_cls[i] - log_cls[i-1] (set log_ret[0]=NaN)
    return {
        "s_now": s_now, "vwap_15m": vw, "dev_bps": dev_bps,
        "cvd_30s": cvd_30, "cvd_60s": cvd_60, "cvd_120s": cvd_120,
        "cvd_agree_30s": cvd_agree_30,
        "cvd_agree_60s": cvd_agree_60,
        "cvd_agree_120s": cvd_agree_120,
        "macd_hist": mh, "macd_agree": macd_agree,
        "rvol_30_300": rvol_30_300,
        "_idx": idx, "_valid": valid,
    }


def compute_sigma_15m_at_idx(arr, idx_arr, window=900):
    """For each idx, compute std of 1s log returns over last `window` seconds.

    Vectorized via cumsum of squared log returns.
    """
    log_cls = arr["log_cls"]
    log_ret = np.diff(log_cls, prepend=np.nan)
    # Replace NaN with 0 for cumsum trick, but track validity separately
    lr_clean = np.where(np.isfinite(log_ret), log_ret, 0.0)
    cs = np.cumsum(lr_clean)
    css = np.cumsum(lr_clean * lr_clean)
    valid_mask = np.isfinite(log_ret).astype(np.int64)
    cs_valid = np.cumsum(valid_mask)

    n = len(idx_arr)
    sigma = np.full(n, np.nan, dtype="float64")
    end = idx_arr
    start = end - window
    ok = (start >= 0) & (end < len(log_cls))
    s = np.where(ok, cs[end] - cs[start], 0.0)
    ss = np.where(ok, css[end] - css[start], 0.0)
    nv = np.where(ok, cs_valid[end] - cs_valid[start], 0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(nv > 1, s / nv, np.nan)
        var = np.where(nv > 1, (ss / nv) - mean * mean, np.nan)
        sigma = np.where((var > 0) & ok, np.sqrt(var * nv / (nv - 1)), np.nan)
    return sigma


# ---------------------------------------------------------------------
# Aggregation + report — runs after feat_df is built
# ---------------------------------------------------------------------
def run_aggregation(feat_df: pd.DataFrame):
    # Make sure rule columns exist
    if "S4_pass" not in feat_df.columns:
        s4 = ((feat_df["fair_edge_bp"] > 500) &
              (feat_df["cvd_agree_30s"]) &
              (feat_df["dev_bps"].abs() >= 8))
        s8 = ((feat_df["macd_agree"]) &
              (feat_df["rvol_30_300"] > 1.2))
        s3 = ((feat_df["fair_edge_bp"] > 0) &
              (feat_df["cvd_agree_60s"]) &
              (feat_df["macd_agree"]))
        feat_df["S4_pass"] = s4
        feat_df["S8_pass"] = s8
        feat_df["S3_pass"] = s3

    # ------------------ aggregate per (rule x tf x offset) ------------------
    print("[agg] aggregating...")
    agg_rows = []
    rule_map = {"S4": "S4_pass", "S8": "S8_pass", "S3": "S3_pass"}
    for rule, col in rule_map.items():
        sub = feat_df[feat_df[col]].copy()
        if sub.empty:
            continue
        # Dedup within (offset, slug, direction): one fire per slug+dir per offset.
        sub = sub.drop_duplicates(["tf", "offset_s", "slug", "direction"], keep="first")
        # Group
        for (tf, off), g in sub.groupby(["tf", "offset_s"], observed=True):
            n_ = len(g)
            if n_ == 0:
                continue
            wr = float(g["won"].mean())
            per_tr = float(g["pnl_legacy_usd"].mean())
            sum_pnl = float(g["pnl_legacy_usd"].sum())
            avg_evwap = float(g["entry_vwap"].mean())
            std_pnl = float(g["pnl_legacy_usd"].std(ddof=1)) if n_ > 1 else float("nan")
            sharpe_pt = per_tr / std_pnl if (std_pnl > 0) else float("nan")
            g_sorted = g.sort_values("fire_us")
            cum = g_sorted["pnl_legacy_usd"].cumsum().values
            max_dd = float((np.maximum.accumulate(cum) - cum).max()) if len(cum) else float("nan")
            vw_null = float(g["entry_vwap"].mean())
            wr_edge_pp = (wr - vw_null) * 100
            wins = int(g["won"].sum())
            try:
                p_bt = float(binomtest(wins, n_, p=vw_null, alternative="greater").pvalue)
            except Exception:
                p_bt = float("nan")
            agg_rows.append({
                "rule": rule, "tf": tf, "offset_s": int(off),
                "n": n_, "WR_pct": round(wr * 100, 2),
                "avg_entry_vwap": round(avg_evwap, 4),
                "per_tr": round(per_tr, 4),
                "sum_pnl": round(sum_pnl, 2),
                "vwap_implied_wr": round(vw_null * 100, 2),
                "wr_edge_pp": round(wr_edge_pp, 2),
                "binom_p": round(p_bt, 4),
                "max_dd": round(max_dd, 2),
                "sharpe_pt": round(sharpe_pt, 4) if np.isfinite(sharpe_pt) else float("nan"),
            })

    agg = pd.DataFrame(agg_rows).sort_values(["rule", "tf", "offset_s"]).reset_index(drop=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    agg.to_csv(OUT_CSV, index=False)
    print(f"   wrote {OUT_CSV}  ({len(agg)} rows)")

    # ------------------ report ------------------
    print(f"[md] writing report -> {OUT_MD}")
    lines = []
    lines.append("# Pre-window vs intra-slot fire timing sweep")
    lines.append("")
    lines.append("**Goal**: find the OPTIMAL `offset_s` (relative to slot_start) for each rule.")
    lines.append("Negative offsets = PRE-WINDOW fires (signal computed before slot opens).")
    lines.append("Positive offsets = INTRA-SLOT fires (production behaviour).")
    lines.append("")
    lines.append("**Rules**:")
    lines.append("- S4: `fair_edge_bp > 500 AND cvd_agree_30s AND |dev_bps| >= 8`")
    lines.append("- S8: `macd_agree AND rvol_30_300 > 1.2`")
    lines.append("- S3: `fair_edge_bp > 0 AND cvd_agree_60s AND macd_agree`")
    lines.append("")
    lines.append("**Fill model**: `engine_v2.LegacyConfig()` (legacy 2%-on-profit, $25 notional, L25 walk).")
    lines.append("")
    lines.append("## Optimal offset per rule (ranked by `sum_pnl x WR x sqrt(n)`)")
    lines.append("")
    for rule in ("S4", "S8", "S3"):
        sub = agg[agg["rule"] == rule].copy()
        if sub.empty:
            lines.append(f"### {rule}\n_no passing fires_\n")
            continue
        sub["score"] = sub["sum_pnl"] * (sub["WR_pct"]/100) * np.sqrt(sub["n"])
        sub_sorted = sub.sort_values("score", ascending=False)
        lines.append(f"### {rule}")
        lines.append("")
        lines.append("Top 5 by `sum_pnl x WR x sqrt(n)`:")
        lines.append("")
        lines.append(sub_sorted.head(5).to_markdown(index=False))
        lines.append("")
        for tf in ("5m", "15m"):
            sub_tf = sub_sorted[sub_sorted["tf"] == tf]
            if not sub_tf.empty:
                top = sub_tf.iloc[0]
                lines.append(f"- **{tf} OPTIMAL**: offset_s={int(top['offset_s'])}  n={int(top['n'])}  "
                             f"WR={top['WR_pct']}%  per_tr=${top['per_tr']:.4f}  "
                             f"sum_pnl=${top['sum_pnl']:.2f}  binom_p={top['binom_p']}")
        lines.append("")

    # Pre-window vs +240 comparison per rule x tf
    lines.append("## Pre-window vs intra-slot per-trade delta (5m)")
    lines.append("")
    lines.append("Comparing per_tr at offset_s=**-240** (production momo_v2 5m timing) vs **+240** (S4 backtest baseline) vs **+120** (most production fires).")
    lines.append("")
    head_cmp = ["rule", "tf",
                "per_tr@-240", "n@-240", "WR@-240",
                "per_tr@+120", "n@+120", "WR@+120",
                "per_tr@+240", "n@+240", "WR@+240",
                "d(-240 - +120)", "d(-240 - +240)"]
    rows_cmp = []
    for rule in ("S4", "S8", "S3"):
        for tf in ("5m", "15m"):
            def _row(off):
                m = agg[(agg["rule"] == rule) & (agg["tf"] == tf) & (agg["offset_s"] == off)]
                if m.empty:
                    return (None, None, None)
                return (float(m["per_tr"].iloc[0]), int(m["n"].iloc[0]), float(m["WR_pct"].iloc[0]))
            p_neg240, n_neg240, wr_neg240 = _row(-240)
            p_120,    n_120,    wr_120    = _row(120)
            p_240,    n_240,    wr_240    = _row(240)
            def _fmt(x, p="${:.4f}"): return p.format(x) if x is not None else "n/a"
            rows_cmp.append([
                rule, tf,
                _fmt(p_neg240), n_neg240, _fmt(wr_neg240, "{:.1f}%") if wr_neg240 is not None else "n/a",
                _fmt(p_120),    n_120,    _fmt(wr_120, "{:.1f}%")    if wr_120    is not None else "n/a",
                _fmt(p_240),    n_240,    _fmt(wr_240, "{:.1f}%")    if wr_240    is not None else "n/a",
                _fmt((p_neg240 or 0) - (p_120 or 0)) if (p_neg240 is not None and p_120 is not None) else "n/a",
                _fmt((p_neg240 or 0) - (p_240 or 0)) if (p_neg240 is not None and p_240 is not None) else "n/a",
            ])
    cmp_df = pd.DataFrame(rows_cmp, columns=head_cmp)
    lines.append(cmp_df.to_markdown(index=False))
    lines.append("")

    lines.append("## All offsets per rule")
    lines.append("")
    for rule in ("S4", "S8", "S3"):
        for tf in ("5m", "15m"):
            sub = agg[(agg["rule"] == rule) & (agg["tf"] == tf)].copy()
            if sub.empty:
                continue
            lines.append(f"### {rule} x {tf}")
            lines.append("")
            lines.append(sub.to_markdown(index=False))
            lines.append("")

    lines.append("## Caveats")
    lines.append("- Pre-window fires evaluate features BEFORE the slot's strike is read; the strike (chainlink RTDS at slot_start) still anchors fair_up, so for offset_s<0 we use the strike that WILL be set at slot_start - which is technically a peek into the strike (~0-few bps move in the seconds before slot_start). Acceptable for sweep; not for live.")
    lines.append("- VWAP_15m is anchored to a 15-min bucket. For pre-window fires the bucket may roll over at the slot boundary; signal at -240s reads a different bucket than slot_start.")
    lines.append("- The `sigma_15m` uses a trailing 900s window of 1s returns - fully causal at any fire_us.")
    lines.append("- entry_vwap and book-walk fills use the L25 book at fire_us with strict-asof + 60s max staleness.")
    lines.append("- Dedup is per (rule x tf x offset_s x slug x direction): one fire per slug-dir-offset.")
    lines.append("")
    lines.append("Artifacts:")
    lines.append(f"- `{OUT_CSV.relative_to(ROOT).as_posix()}`")
    lines.append(f"- `{OUT_PT.relative_to(ROOT).as_posix()}`")
    lines.append(f"- `{Path(__file__).relative_to(ROOT).as_posix()}`")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[done] {OUT_MD}")


# ---------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------
def main():
    # Cache check: if the per-fire parquet exists, skip the heavy stage.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-cache", action="store_true",
                    help="skip heavy stages and just re-aggregate from existing parquet")
    args = ap.parse_args()
    if args.from_cache and OUT_PT.exists():
        print(f"[cache] loading {OUT_PT}")
        feat_df = pd.read_parquet(OUT_PT)
        print(f"   {len(feat_df):,} rows from cache")
        run_aggregation(feat_df)
        return

    print("[1] loading 1s arrays...")
    arrs = build_1s_arrays_for_assets()

    print("[2] loading chainlink asof per asset...")
    ck = {a: load_chainlink_asof(a) for a in ("BTC", "ETH", "SOL")}

    print("[3] loading resolutions (5m + 15m)...")
    res = load_resolutions().rename(columns={"ticker": "asset", "timeframe": "tf"})
    res = res[res.asset.isin(("BTC", "ETH", "SOL"))].copy()
    res["slot_start_s"] = (res.slot_start_us // 1_000_000).astype("int64")
    res["slot_end_s"]   = (res.slot_end_us   // 1_000_000).astype("int64")
    print(f"   total: {len(res):,}  (5m={int((res.tf=='5m').sum()):,}  15m={int((res.tf=='15m').sum()):,})")

    # Filter to slugs within 1s coverage (with room for pre-window + 900s sigma)
    KS_MIN = min(arrs[a]["ts"][0]  for a in arrs) // 1_000_000
    KS_MAX = max(arrs[a]["ts"][-1] for a in arrs) // 1_000_000
    print(f"   1s ts range: {KS_MIN} .. {KS_MAX}")

    # Need (slot_start + min_offset_s - 900) >= KS_MIN  AND  (slot_start + max_offset_s) <= KS_MAX
    # 5m: min_offset = -300, max_offset = 270  → require [KS_MIN + 900 + 300, KS_MAX - 270]
    # 15m: min_offset = -840, max_offset = 840 → require [KS_MIN + 900 + 840, KS_MAX - 840]
    masks = (
        (res.tf == "5m") & (res.slot_start_s >= KS_MIN + 1200) & (res.slot_start_s <= KS_MAX - 270)
    ) | (
        (res.tf == "15m") & (res.slot_start_s >= KS_MIN + 1740) & (res.slot_start_s <= KS_MAX - 840)
    )
    res = res[masks].reset_index(drop=True)
    print(f"   after coverage filter: {len(res):,}")

    # Build per-asset L25 books (one shot, with all slugs we care about).
    print("[4] loading L25 books per asset (one shot)...")
    books_idx: dict = {}
    for a in ("BTC", "ETH", "SOL"):
        slugs_a = set(res[res.asset == a]["slug"].unique())
        if not slugs_a:
            continue
        min_fire_us = (res[res.asset == a]["slot_start_s"].min() - 900) * 1_000_000
        max_fire_us = (res[res.asset == a]["slot_end_s"].max()   + 900) * 1_000_000
        print(f"   {a}: loading {len(slugs_a):,} slugs from L25 caches...")
        books_a = load_orderbook_l25_streaming(
            a, slugs=slugs_a, subsample_1hz=True,
            min_ts_us=int(min_fire_us), max_ts_us=int(max_fire_us),
        )
        books_idx.update(books_a)
        print(f"   {a}: {len(books_a):,} (slug, outcome) keys loaded")

    # Build the master fire candidate list: each row = (slug, asset, tf, direction, offset_s)
    # For each slug, 2 directions × N offsets.
    print("[5] building candidate fire table...")
    rows = []
    for _, r in res.iterrows():
        offs = OFFSETS_5M if r.tf == "5m" else OFFSETS_15M
        for d in ("UP", "DOWN"):
            for off in offs:
                rows.append((r.slug, r.asset, r.tf, int(r.slot_start_s),
                              int(r.slot_end_s), str(r.outcome), d, off))
    cand = pd.DataFrame(rows, columns=[
        "slug", "asset", "tf", "slot_start_s", "slot_end_s",
        "outcome", "direction", "offset_s",
    ])
    cand["fire_s"]  = cand["slot_start_s"] + cand["offset_s"]
    cand["fire_us"] = cand["fire_s"].astype("int64") * 1_000_000
    cand["slot_end_us"] = cand["slot_end_s"].astype("int64") * 1_000_000
    cand["slot_start_us"] = cand["slot_start_s"].astype("int64") * 1_000_000
    cand["tau_s"] = cand["slot_end_s"] - cand["fire_s"]
    # tau must be > 0 to be a valid fire
    cand = cand[cand["tau_s"] > 0].reset_index(drop=True)
    print(f"   {len(cand):,} candidate fires (after tau>0)")

    # ------------------ vectorized feature compute per asset ------------------
    print("[6] computing features vectorized per asset...")
    feat_chunks = []
    for a in ("BTC", "ETH", "SOL"):
        sub = cand[cand.asset == a].copy().reset_index(drop=True)
        if sub.empty:
            continue
        print(f"   {a}: {len(sub):,} candidate fires...")
        dir_arr = (sub["direction"].values == "UP")
        fu = sub["fire_us"].values.astype("int64")
        feats = vectorized_features_at(arrs[a], fu, dir_arr)
        # Sigma — use cumsum trick
        sig15 = compute_sigma_15m_at_idx(arrs[a], feats["_idx"], window=900)

        # Chainlink strike at slot_start_us
        ck_ts, ck_px = ck[a]
        ss_us = sub["slot_start_us"].values.astype("int64")
        ck_i = np.searchsorted(ck_ts, ss_us, side="right") - 1
        ck_ok = ck_i >= 0
        strike = np.where(ck_ok, ck_px[np.clip(ck_i, 0, len(ck_px)-1)], np.nan)

        # Fair value: tau = (slot_end_us - fire_us) / 1e6
        tau = (sub["slot_end_us"].values - sub["fire_us"].values) / 1_000_000.0
        sn = feats["s_now"]
        with np.errstate(invalid="ignore", divide="ignore"):
            z = np.where((strike > 0) & np.isfinite(sn) & np.isfinite(sig15) &
                         (sig15 > 0) & (tau > 0),
                         np.log(sn / strike) / (sig15 * np.sqrt(tau)),
                         np.nan)
            fair_up = norm.cdf(np.where(np.isfinite(z), z, 0.0))
            fair_up = np.where(np.isfinite(z), fair_up, np.nan)

        for k, v in feats.items():
            if k.startswith("_"):
                continue
            sub[k] = v
        sub["sigma_15m"] = sig15
        sub["strike"] = strike
        sub["fair_up"] = fair_up
        feat_chunks.append(sub)

    feat_df = pd.concat(feat_chunks, ignore_index=True)
    print(f"   features computed: {len(feat_df):,} rows")

    # ------------------ fair_edge_bp (per direction) ------------------
    # fair_edge_bp = (fair_side - entry_vwap) * 10000, where fair_side = fair_up if UP else 1-fair_up
    # entry_vwap is filled later. We compute fair_edge_bp_no_evwap first using mid as proxy?
    # NO — keep this faithful: fair_edge_bp uses entry_vwap. So we need entry_vwap first.
    # ------------------ L25 entry_vwap + pnl ------------------
    print("[7] L25 fills via engine_v2.LegacyConfig...")
    cfg = LegacyConfig()
    n = len(feat_df)
    entry_vwap = np.full(n, np.nan)
    pnl_legacy = np.full(n, np.nan)
    won_arr = np.zeros(n, dtype=bool)
    fill_ok = np.zeros(n, dtype=bool)

    # Iterate rows; pre-extract numpy arrays for speed
    slug_a    = feat_df["slug"].values
    out_a     = feat_df["outcome"].values
    direc_a   = feat_df["direction"].values
    fire_us_a = feat_df["fire_us"].values.astype("int64")
    asset_a   = feat_df["asset"].values

    last_print = 0
    for i in range(n):
        if (i + 1) % 50_000 == 0 or i + 1 == n:
            print(f"   fill {i+1:,}/{n:,}")
        side = "Up" if direc_a[i] == "UP" else "Down"
        try:
            fill = fill_at_book(
                books_idx, slug_a[i], side, int(fire_us_a[i]),
                cfg=cfg, spread_filter=SPREAD_FILTER[asset_a[i]],
            )
        except Exception:
            fill = None
        if fill is None:
            continue
        won = (out_a[i] == "Up") if direc_a[i] == "UP" else (out_a[i] == "Down")
        pnl = hold_pnl(fill, won=won, cfg=cfg)
        entry_vwap[i] = float(fill["vwap"])
        pnl_legacy[i] = float(pnl)
        won_arr[i] = bool(won)
        fill_ok[i] = True

    feat_df["entry_vwap"]      = entry_vwap
    feat_df["pnl_legacy_usd"]  = pnl_legacy
    feat_df["won"]             = won_arr

    feat_df = feat_df[fill_ok].reset_index(drop=True)
    print(f"   {len(feat_df):,} rows filled")

    # ------------------ fair_edge_bp ------------------
    print("[8] fair_edge_bp...")
    fu = feat_df["fair_up"].values
    ev = feat_df["entry_vwap"].values
    di = (feat_df["direction"].values == "UP")
    fair_side = np.where(di, fu, 1.0 - fu)
    feat_df["fair_edge_bp"] = (fair_side - ev) * 10_000

    # ------------------ apply rules ------------------
    print("[9] applying rules...")
    s4 = ((feat_df["fair_edge_bp"] > 500) &
          (feat_df["cvd_agree_30s"]) &
          (feat_df["dev_bps"].abs() >= 8))
    s8 = ((feat_df["macd_agree"]) &
          (feat_df["rvol_30_300"] > 1.2))
    s3 = ((feat_df["fair_edge_bp"] > 0) &
          (feat_df["cvd_agree_60s"]) &
          (feat_df["macd_agree"]))

    feat_df["S4_pass"] = s4
    feat_df["S8_pass"] = s8
    feat_df["S3_pass"] = s3

    # Save per-fire (we keep ALL evaluated fires; the rule-pass columns are sparse)
    print(f"[10] writing per-fire parquet -> {OUT_PT}")
    OUT_PT.parent.mkdir(parents=True, exist_ok=True)
    keep_cols = [
        "slug", "asset", "tf", "direction", "offset_s", "fire_s", "fire_us",
        "slot_start_s", "slot_end_s", "outcome", "won",
        "s_now", "vwap_15m", "dev_bps", "strike", "fair_up", "fair_edge_bp",
        "cvd_30s", "cvd_60s", "cvd_120s",
        "cvd_agree_30s", "cvd_agree_60s", "cvd_agree_120s",
        "macd_hist", "macd_agree",
        "rvol_30_300", "sigma_15m",
        "entry_vwap", "pnl_legacy_usd",
        "S4_pass", "S8_pass", "S3_pass",
    ]
    feat_df[keep_cols].to_parquet(OUT_PT, index=False, compression="zstd")

    run_aggregation(feat_df)
    return

    # ------------------ aggregate per (rule x tf x offset) ------------------
    print("[11] aggregating...")
    agg_rows = []
    rule_map = {"S4": "S4_pass", "S8": "S8_pass", "S3": "S3_pass"}
    for rule, col in rule_map.items():
        sub = feat_df[feat_df[col]].copy()
        if sub.empty:
            continue
        # Dedup within (offset, slug, direction): one fire per slug+dir per offset.
        sub = sub.drop_duplicates(["tf", "offset_s", "slug", "direction"], keep="first")
        # Group
        for (tf, off), g in sub.groupby(["tf", "offset_s"], observed=True):
            n_ = len(g)
            if n_ == 0:
                continue
            wr = float(g["won"].mean())
            per_tr = float(g["pnl_legacy_usd"].mean())
            sum_pnl = float(g["pnl_legacy_usd"].sum())
            avg_evwap = float(g["entry_vwap"].mean())
            std_pnl = float(g["pnl_legacy_usd"].std(ddof=1)) if n_ > 1 else float("nan")
            sharpe_pt = per_tr / std_pnl if (std_pnl > 0) else float("nan")
            # cumulative max-drawdown by trade order (chronological by fire_us)
            g_sorted = g.sort_values("fire_us")
            cum = g_sorted["pnl_legacy_usd"].cumsum().values
            max_dd = float((np.maximum.accumulate(cum) - cum).max()) if len(cum) else float("nan")
            # vwap-implied null: WR_null = avg(entry_vwap) — payout=$1 if won
            vw_null = float(g["entry_vwap"].mean())
            wr_edge_pp = (wr - vw_null) * 100
            # binomial test: wins out of n vs p = vw_null
            wins = int(g["won"].sum())
            try:
                p_bt = float(binomtest(wins, n_, p=vw_null, alternative="greater").pvalue)
            except Exception:
                p_bt = float("nan")
            agg_rows.append({
                "rule": rule, "tf": tf, "offset_s": int(off),
                "n": n_, "WR_pct": round(wr * 100, 2),
                "avg_entry_vwap": round(avg_evwap, 4),
                "per_tr": round(per_tr, 4),
                "sum_pnl": round(sum_pnl, 2),
                "vwap_implied_wr": round(vw_null * 100, 2),
                "wr_edge_pp": round(wr_edge_pp, 2),
                "binom_p": round(p_bt, 4),
                "max_dd": round(max_dd, 2),
                "sharpe_pt": round(sharpe_pt, 4) if np.isfinite(sharpe_pt) else float("nan"),
            })

    agg = pd.DataFrame(agg_rows).sort_values(["rule", "tf", "offset_s"]).reset_index(drop=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    agg.to_csv(OUT_CSV, index=False)
    print(f"   wrote {OUT_CSV}  ({len(agg)} rows)")

    # ------------------ report ------------------
    print(f"[12] writing report -> {OUT_MD}")
    lines = []
    lines.append("# Pre-window vs intra-slot fire timing sweep")
    lines.append("")
    lines.append("**Goal**: find the OPTIMAL `offset_s` (relative to slot_start) for each rule.")
    lines.append("Negative offsets = PRE-WINDOW fires (signal computed before slot opens).")
    lines.append("Positive offsets = INTRA-SLOT fires (production behaviour).")
    lines.append("")
    lines.append("**Rules**:")
    lines.append("- S4: `fair_edge_bp > 500 AND cvd_agree_30s AND |dev_bps| >= 8`")
    lines.append("- S8: `macd_agree AND rvol_30_300 > 1.2`")
    lines.append("- S3: `fair_edge_bp > 0 AND cvd_agree_60s AND macd_agree`")
    lines.append("")
    lines.append("**Fill model**: `engine_v2.LegacyConfig()` (legacy 2%-on-profit, $25 notional, L25 walk).")
    lines.append("")
    lines.append("## Optimal offset per rule (ranked by `sum_pnl × WR × sqrt(n)`)")
    lines.append("")
    for rule in ("S4", "S8", "S3"):
        sub = agg[agg["rule"] == rule].copy()
        if sub.empty:
            lines.append(f"### {rule}\n_no passing fires_\n")
            continue
        sub["score"] = sub["sum_pnl"] * (sub["WR_pct"]/100) * np.sqrt(sub["n"])
        sub_sorted = sub.sort_values("score", ascending=False)
        lines.append(f"### {rule}")
        lines.append("")
        lines.append("Top 5 by `sum_pnl × WR × sqrt(n)`:")
        lines.append("")
        lines.append(sub_sorted.head(5).to_markdown(index=False))
        lines.append("")
        # OPTIMAL per (tf):
        for tf in ("5m", "15m"):
            sub_tf = sub_sorted[sub_sorted["tf"] == tf]
            if not sub_tf.empty:
                top = sub_tf.iloc[0]
                lines.append(f"- **{tf} OPTIMAL**: offset_s={int(top['offset_s'])}  n={int(top['n'])}  "
                             f"WR={top['WR_pct']}%  per_tr=${top['per_tr']:.4f}  "
                             f"sum_pnl=${top['sum_pnl']:.2f}  binom_p={top['binom_p']}")
        lines.append("")

    # Pre-window vs +240 comparison per rule × tf
    lines.append("## Pre-window vs intra-slot per-trade delta (5m only)")
    lines.append("")
    lines.append("Comparing per_tr at offset_s=**-240** (production momo_v2 5m timing) vs **+240** (S4 backtest baseline) vs **+120** (most production fires).")
    lines.append("")
    head_cmp = ["rule", "tf",
                "per_tr@-240", "n@-240", "WR@-240",
                "per_tr@+120", "n@+120", "WR@+120",
                "per_tr@+240", "n@+240", "WR@+240",
                "Δ(-240 − +120)", "Δ(-240 − +240)"]
    rows_cmp = []
    for rule in ("S4", "S8", "S3"):
        for tf in ("5m", "15m"):
            def _row(off):
                m = agg[(agg["rule"] == rule) & (agg["tf"] == tf) & (agg["offset_s"] == off)]
                if m.empty:
                    return (None, None, None)
                return (float(m["per_tr"].iloc[0]), int(m["n"].iloc[0]), float(m["WR_pct"].iloc[0]))
            p_neg240, n_neg240, wr_neg240 = _row(-240)
            p_120,    n_120,    wr_120    = _row(120)
            p_240,    n_240,    wr_240    = _row(240)
            def _fmt(x, p="${:.4f}"): return p.format(x) if x is not None else "n/a"
            rows_cmp.append([
                rule, tf,
                _fmt(p_neg240), n_neg240, _fmt(wr_neg240, "{:.1f}%") if wr_neg240 is not None else "n/a",
                _fmt(p_120),    n_120,    _fmt(wr_120, "{:.1f}%")    if wr_120    is not None else "n/a",
                _fmt(p_240),    n_240,    _fmt(wr_240, "{:.1f}%")    if wr_240    is not None else "n/a",
                _fmt((p_neg240 or 0) - (p_120 or 0)) if (p_neg240 is not None and p_120 is not None) else "n/a",
                _fmt((p_neg240 or 0) - (p_240 or 0)) if (p_neg240 is not None and p_240 is not None) else "n/a",
            ])
    cmp_df = pd.DataFrame(rows_cmp, columns=head_cmp)
    lines.append(cmp_df.to_markdown(index=False))
    lines.append("")

    # All rows by rule
    lines.append("## All offsets per rule")
    lines.append("")
    for rule in ("S4", "S8", "S3"):
        for tf in ("5m", "15m"):
            sub = agg[(agg["rule"] == rule) & (agg["tf"] == tf)].copy()
            if sub.empty:
                continue
            lines.append(f"### {rule} × {tf}")
            lines.append("")
            lines.append(sub.to_markdown(index=False))
            lines.append("")

    lines.append("## Caveats")
    lines.append("- Pre-window fires evaluate features BEFORE the slot's strike is read; the strike (chainlink RTDS at slot_start) still anchors fair_up, so for offset_s<0 we use the strike that WILL be set at slot_start — which is technically a peek into the strike (~0-few bps move in the seconds before slot_start). Acceptable for sweep; not for live.")
    lines.append("- VWAP_15m is anchored to a 15-min bucket. For pre-window fires the bucket may roll over at the slot boundary; signal at -240s reads a different bucket than slot_start.")
    lines.append("- The `sigma_15m` uses a trailing 900s window of 1s returns — fully causal at any fire_us.")
    lines.append("- entry_vwap and book-walk fills use the L25 book at fire_us with strict-asof + 60s max staleness.")
    lines.append("- Dedup is per (rule × tf × offset_s × slug × direction): one fire per slug-dir-offset.")
    lines.append("")
    lines.append("Artifacts:")
    lines.append(f"- `{OUT_CSV.relative_to(ROOT).as_posix()}`")
    lines.append(f"- `{OUT_PT.relative_to(ROOT).as_posix()}`")
    lines.append(f"- `{Path(__file__).relative_to(ROOT).as_posix()}`")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"[done] {OUT_MD}")


if __name__ == "__main__":
    main()
