"""Build extended microprice (Stoikov 2018) feature panel at every fire_us.

Builds:
  - mp_up_simple, mp_dn_simple (L1)
  - mp_up_dev_bps, mp_dn_dev_bps (signed dev from mid)
  - mp_up_weighted, mp_dn_weighted (L25 exp-decay weighted, w_i=exp(-i/5))
  - mp_up_weighted_dev_bps, mp_dn_weighted_dev_bps
  - mp_skew = mp_up_dev_bps - mp_dn_dev_bps
  - mp_imbalance = (mp_up_dev_bps - mp_dn_dev_bps) / (|mp_up| + |mp_dn|)
  - mp_up_dev_change_500ms, mp_dn_dev_change_500ms
  - mp_skew_change_500ms

For each (asset) we stream L25 once for both UP and DN tokens at fire_us, fire_us-500ms.

The full fire universe = hybrid_fire_universe_{5m,15m} (Apr 30 -> May 23) +
oos_fires_{asset}_{tf}.parquet (May 22 -> May 25) = full 32d Apr 24 -> May 25.

Per-asset output: micro_price_panel_{asset}.parquet
Combined output: data/v4/canonical/_results/microprice_panel.parquet
"""
from __future__ import annotations
import sys, time, gc, os
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_orderbook_l25_streaming  # noqa: E402

OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
PANEL = OUT_DIR / "microprice_panel.parquet"
WORK = ROOT / "strategy_lab" / "microprice_2026_05_26"
WORK.mkdir(exist_ok=True)

LEVELS = 25
# Exp-decay weights for L25 (top of book weighted most)
_WEIGHTS = np.exp(-np.arange(LEVELS) / 5.0)  # w_0=1.0, w_5=0.367, w_24=0.0079


def microprice_features_at_idx(ap, asz, bp, bs, idx):
    """Compute simple + weighted microprice for ONE book snapshot.

    ap, asz, bp, bs are 2D arrays (T, 25). idx selects one row.
    Returns dict {mp_simple, mp_weighted, mid, mp_dev_bps, mp_weighted_dev_bps}.
    """
    a_p = ap[idx]
    a_s = asz[idx]
    b_p = bp[idx]
    b_s = bs[idx]

    a_s_clean = np.nan_to_num(a_s, nan=0.0)
    b_s_clean = np.nan_to_num(b_s, nan=0.0)
    a_p_valid = np.isfinite(a_p) & (a_p > 0) & (a_p < 1)
    b_p_valid = np.isfinite(b_p) & (b_p > 0) & (b_p < 1)
    a_sv = a_s_clean * a_p_valid.astype(float)
    b_sv = b_s_clean * b_p_valid.astype(float)

    ask0 = a_p[0] if a_p_valid[0] else np.nan
    bid0 = b_p[0] if b_p_valid[0] else np.nan
    asz0 = a_sv[0]
    bsz0 = b_sv[0]
    mid = (ask0 + bid0) / 2.0 if (np.isfinite(ask0) and np.isfinite(bid0)) else np.nan

    # Simple microprice (Stoikov L1)
    s_top1 = bsz0 + asz0
    if s_top1 > 0 and np.isfinite(ask0) and np.isfinite(bid0):
        mp_simple = (bsz0 * ask0 + asz0 * bid0) / s_top1
    else:
        mp_simple = np.nan
    mp_dev_bps = ((mp_simple - mid) / mid * 1e4) if (np.isfinite(mp_simple) and mid > 0) else np.nan

    # Weighted microprice across L25 — sum of per-level micropricse with exp-decay weights
    # mp_i = (b_size_i * ask_price_i + ask_size_i * bid_price_i) / (b_size_i + ask_size_i)
    # Only valid where both sides have finite price at that level AND total size > 0
    s_per = a_sv + b_sv  # (25,) total size at level i (b_i + a_i)
    both_valid = a_p_valid & b_p_valid & (s_per > 0)
    # Per-level microprice (where both_valid)
    with np.errstate(divide="ignore", invalid="ignore"):
        per_level_mp = np.where(
            both_valid,
            (b_sv * np.nan_to_num(a_p, nan=0.0) + a_sv * np.nan_to_num(b_p, nan=0.0)) / np.where(s_per > 0, s_per, 1.0),
            np.nan,
        )
    w = _WEIGHTS * both_valid.astype(float)
    wsum = w.sum()
    if wsum > 0:
        mp_weighted = np.nansum(per_level_mp * w) / wsum
    else:
        mp_weighted = np.nan
    mp_weighted_dev_bps = ((mp_weighted - mid) / mid * 1e4) if (np.isfinite(mp_weighted) and mid > 0) else np.nan

    return {
        "mp_simple": mp_simple,
        "mp_weighted": mp_weighted,
        "mid": mid,
        "mp_dev_bps": mp_dev_bps,
        "mp_weighted_dev_bps": mp_weighted_dev_bps,
    }


def compute_for_slug_outcome(books_idx, slug, outcome, fire_us_arr):
    """For one (slug, outcome), compute microprice features at each fire_us.

    Returns list of dicts (one per fire), with keys for the asof book + 500ms-prior book.
    """
    rec = books_idx.get((slug, outcome))
    if rec is None:
        return None
    ts, ap, asz, bp, bs = rec
    if len(ts) == 0:
        return None
    n = len(fire_us_arr)
    out = [None] * n
    for fi, fire_us in enumerate(fire_us_arr):
        pos = int(np.searchsorted(ts, int(fire_us), side="right"))
        if pos == 0:
            continue
        idx = pos - 1
        dt_us = int(fire_us) - int(ts[idx])
        if dt_us > 60_000_000:
            continue
        f = microprice_features_at_idx(ap, asz, bp, bs, idx)
        f["book_dt_us"] = dt_us
        # lookback at fire_us - 500ms
        pos500 = int(np.searchsorted(ts, int(fire_us) - 500_000, side="right"))
        if pos500 > 0:
            f500 = microprice_features_at_idx(ap, asz, bp, bs, pos500 - 1)
            f["mp_dev_500ms"] = f500["mp_dev_bps"]
            f["mp_weighted_dev_500ms"] = f500["mp_weighted_dev_bps"]
        else:
            f["mp_dev_500ms"] = np.nan
            f["mp_weighted_dev_500ms"] = np.nan
        f["fire_idx"] = fi
        out[fi] = f
    return out


def process_asset(asset, fires_df):
    """Stream L25 for asset, compute UP and DN microprice features for each fire."""
    print(f"\n=== {asset} === ({len(fires_df)} fires)", flush=True)
    slugs = set(fires_df.slug.unique())
    print(f"  unique slugs: {len(slugs)}", flush=True)

    min_ts = int(fires_df.fire_us.min()) - 10_000_000
    max_ts = int(fires_df.fire_us.max()) + 10_000_000
    print(f"  window: {pd.to_datetime(min_ts/1e6, unit='s')} -> {pd.to_datetime(max_ts/1e6, unit='s')}", flush=True)

    t0 = time.time()
    books_idx = load_orderbook_l25_streaming(
        asset, slugs=slugs, subsample_1hz=True,
        min_ts_us=min_ts, max_ts_us=max_ts,
    )
    print(f"  loaded books: {len(books_idx)} keys, elapsed={time.time()-t0:.1f}s", flush=True)

    rows = []
    g = fires_df.groupby("slug")
    n_slugs = len(g)
    t1 = time.time()
    for si, (slug, sub) in enumerate(g):
        if si % 1000 == 0 and si > 0:
            print(f"  ...{si}/{n_slugs} slugs, elapsed={time.time()-t1:.1f}s", flush=True)
        fire_us_arr = sub.fire_us.values.astype("int64")
        up_feats = compute_for_slug_outcome(books_idx, slug, "Up", fire_us_arr)
        dn_feats = compute_for_slug_outcome(books_idx, slug, "Down", fire_us_arr)
        for fi, (_, row) in enumerate(sub.iterrows()):
            r = {
                "asset": row["asset"], "slug": slug, "tf": row["tf"],
                "fire_us": int(row["fire_us"]), "fire_offset_s": int(row["fire_offset_s"]),
                "outcome": row["outcome"], "ws_s": int(row["ws_s"]),
            }
            uf = up_feats[fi] if up_feats else None
            df_f = dn_feats[fi] if dn_feats else None
            if uf is None or df_f is None:
                continue
            r["mp_up_simple"] = uf["mp_simple"]
            r["mp_dn_simple"] = df_f["mp_simple"]
            r["mp_up_weighted"] = uf["mp_weighted"]
            r["mp_dn_weighted"] = df_f["mp_weighted"]
            r["mp_up_dev_bps"] = uf["mp_dev_bps"]
            r["mp_dn_dev_bps"] = df_f["mp_dev_bps"]
            r["mp_up_weighted_dev_bps"] = uf["mp_weighted_dev_bps"]
            r["mp_dn_weighted_dev_bps"] = df_f["mp_weighted_dev_bps"]
            r["up_mid_for_mp"] = uf["mid"]
            r["dn_mid_for_mp"] = df_f["mid"]
            r["up_book_dt_us"] = uf["book_dt_us"]
            r["dn_book_dt_us"] = df_f["book_dt_us"]
            # 500ms-prior values
            r["mp_up_dev_500ms"] = uf["mp_dev_500ms"]
            r["mp_dn_dev_500ms"] = df_f["mp_dev_500ms"]
            r["mp_up_weighted_dev_500ms"] = uf["mp_weighted_dev_500ms"]
            r["mp_dn_weighted_dev_500ms"] = df_f["mp_weighted_dev_500ms"]
            rows.append(r)

    del books_idx
    gc.collect()

    df = pd.DataFrame(rows)
    if len(df):
        # Cross-token derived features
        df["mp_skew"] = df["mp_up_dev_bps"] - df["mp_dn_dev_bps"]
        # Normalized imbalance
        denom = df["mp_up_dev_bps"].abs() + df["mp_dn_dev_bps"].abs()
        df["mp_imbalance"] = np.where(denom > 1e-9,
                                      (df["mp_up_dev_bps"] - df["mp_dn_dev_bps"]) / denom,
                                      0.0)
        # Weighted variants
        df["mp_weighted_skew"] = df["mp_up_weighted_dev_bps"] - df["mp_dn_weighted_dev_bps"]
        denom_w = df["mp_up_weighted_dev_bps"].abs() + df["mp_dn_weighted_dev_bps"].abs()
        df["mp_weighted_imbalance"] = np.where(denom_w > 1e-9,
                                                (df["mp_up_weighted_dev_bps"] - df["mp_dn_weighted_dev_bps"]) / denom_w,
                                                0.0)
        # Momentum: change in dev over last 500ms
        df["mp_up_dev_change_500ms"] = df["mp_up_dev_bps"] - df["mp_up_dev_500ms"]
        df["mp_dn_dev_change_500ms"] = df["mp_dn_dev_bps"] - df["mp_dn_dev_500ms"]
        df["mp_skew_500ms"] = df["mp_up_dev_500ms"] - df["mp_dn_dev_500ms"]
        df["mp_skew_change_500ms"] = df["mp_skew"] - df["mp_skew_500ms"]
    print(f"  produced {len(df)} feature rows in {time.time()-t1:.1f}s (total {time.time()-t0:.1f}s)", flush=True)
    return df


def main():
    import builtins
    _print = builtins.print
    def flushed_print(*a, **k):
        k.setdefault('flush', True)
        _print(*a, **k)
    builtins.print = flushed_print

    # Choose asset via CLI
    asset = None
    for a in sys.argv[1:]:
        if a.upper() in ("BTC", "ETH", "SOL"):
            asset = a.upper()
    if asset is None:
        print("USAGE: build_microprice_panel.py {BTC|ETH|SOL}")
        sys.exit(1)

    fr5 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_5m.parquet")
    fr15 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_15m.parquet")

    # Prefix fires (Apr 24 -> May 1) — same schema as OOS
    prefix_parts = []
    pref = OUT_DIR / "_full_window_2026_05_26" / "prefix_fires.parquet"
    if pref.exists():
        d = pd.read_parquet(pref)
        d = d[d.asset == asset]
        # Need: asset, slug, tf, fire_us, fire_offset_s, outcome, ws_s
        keep = ["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome", "ws_s"]
        prefix_parts.append(d[keep])

    # Also pull in OOS fires (May 22-25)
    oos_parts = []
    for tf in ("5m", "15m"):
        p = OUT_DIR / "_full_window_2026_05_26" / f"oos_fires_{asset}_{tf}.parquet"
        if p.exists():
            d = pd.read_parquet(p)
            cols = ["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome", "ws_s"]
            if "tf" not in d.columns:
                d["tf"] = tf
            if "ws_s" not in d.columns and "slot_start_us" in d.columns:
                d["ws_s"] = (d.slot_start_us // 1_000_000) - (300 if tf == "5m" else 900)
            oos_parts.append(d[cols])

    fires = pd.concat([fr5, fr15], ignore_index=True)
    fires = fires[fires.asset == asset].copy()
    print(f"hybrid fires for {asset}: {len(fires)}")
    fires_keep = ["asset","slug","tf","fire_us","fire_offset_s","outcome","ws_s"]
    fires = fires[fires_keep]
    prev_keys = set(zip(fires.slug, fires.fire_us, fires.outcome))

    if prefix_parts:
        pre = pd.concat(prefix_parts, ignore_index=True)
        new_mask = ~pre.apply(lambda r: (r.slug, int(r.fire_us), r.outcome) in prev_keys, axis=1)
        pre_new = pre[new_mask]
        print(f"PREFIX new fires for {asset}: {len(pre_new)}")
        prev_keys |= set(zip(pre_new.slug, pre_new.fire_us, pre_new.outcome))
        fires = pd.concat([fires, pre_new], ignore_index=True)

    if oos_parts:
        oos = pd.concat(oos_parts, ignore_index=True)
        new_mask = ~oos.apply(lambda r: (r.slug, int(r.fire_us), r.outcome) in prev_keys, axis=1)
        oos_new = oos[new_mask]
        print(f"OOS new fires for {asset}: {len(oos_new)}")
        fires = pd.concat([fires, oos_new], ignore_index=True)
    print(f"Total fires for {asset}: {len(fires)}", flush=True)

    df = process_asset(asset, fires)
    out_p = WORK / f"micro_price_panel_{asset.lower()}.parquet"
    df.to_parquet(out_p)
    print(f"\nSaved {out_p} ({len(df)} rows)", flush=True)


if __name__ == "__main__":
    main()
