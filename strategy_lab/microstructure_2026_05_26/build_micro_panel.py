"""Build microstructure feature panel at every fire_us.

For each fire in hybrid_fire_universe_{5m,15m}, sample L25 book at fire_us
(causal — books before fire_us only) for BOTH UP and DN tokens. Compute
~40 microstructure features and save as panel for TASK 2/3 scoring.

Strategy:
  - Stream L25 by asset (BTC -> ETH -> SOL)
  - For each (slug, outcome), keep timestamps + L25 arrays in memory
  - For each fire, do causal asof at fire_us using searchsorted
  - Also look up at fire_us-500ms and fire_us-1s for change features
  - Write per-asset panel parquets, then concat
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
PANEL = OUT_DIR / "microstructure_panel.parquet"
WORK = ROOT / "strategy_lab" / "microstructure_2026_05_26"
WORK.mkdir(exist_ok=True)

LEVELS = 25


def _safe_div(a, b):
    return np.where(np.abs(b) > 1e-12, a / b, 0.0)


def feats_at_idx(ap, asz, bp, bs, idx):
    """Vectorized feature compute given a single book snapshot (1D 25-vec each).

    Returns dict of features for THIS token side.
    """
    # Filter L25 — pad with zeros if needed (only count finite valid prices)
    # ap, asz, bp, bs are 1D arrays size 25
    a_p = ap[idx]
    a_s = asz[idx]
    b_p = bp[idx]
    b_s = bs[idx]

    # Replace NaN with 0 for sizes; for prices keep as-is but skip in sums
    a_s_clean = np.nan_to_num(a_s, nan=0.0)
    b_s_clean = np.nan_to_num(b_s, nan=0.0)
    # valid mask
    a_p_valid = np.isfinite(a_p) & (a_p > 0) & (a_p < 1)
    b_p_valid = np.isfinite(b_p) & (b_p > 0) & (b_p < 1)
    a_s_v = a_s_clean * a_p_valid.astype(float)
    b_s_v = b_s_clean * b_p_valid.astype(float)

    ask0 = a_p[0] if a_p_valid[0] else np.nan
    bid0 = b_p[0] if b_p_valid[0] else np.nan
    asz0 = a_s_v[0]
    bsz0 = b_s_v[0]
    mid = (ask0 + bid0) / 2.0 if (np.isfinite(ask0) and np.isfinite(bid0)) else np.nan
    spread = ask0 - bid0 if (np.isfinite(ask0) and np.isfinite(bid0)) else np.nan
    spread_bps = (spread / mid * 1e4) if (np.isfinite(spread) and mid > 0) else np.nan

    # Imbalances
    s_top1 = bsz0 + asz0
    imb1 = (bsz0 - asz0) / s_top1 if s_top1 > 0 else 0.0
    s_top5 = a_s_v[:5].sum() + b_s_v[:5].sum()
    imb5 = (b_s_v[:5].sum() - a_s_v[:5].sum()) / s_top5 if s_top5 > 0 else 0.0
    s_top25 = a_s_v.sum() + b_s_v.sum()
    imb25 = (b_s_v.sum() - a_s_v.sum()) / s_top25 if s_top25 > 0 else 0.0

    # Microprice (book-weighted mid): asz/bsz weight inverted (more bid size => closer to bid)
    # Standard: microprice = (bid_size * ask + ask_size * bid) / (bid_size + ask_size)
    micro = (bsz0 * ask0 + asz0 * bid0) / s_top1 if (s_top1 > 0 and np.isfinite(ask0) and np.isfinite(bid0)) else np.nan
    micro_dev_bps = ((micro - mid) / mid * 1e4) if (np.isfinite(micro) and mid > 0) else np.nan

    # L25 effective spread: distance between L25 top and L25 bottom levels
    # Take max valid ask price and min valid bid price (best vs worst at L25 depth)
    if a_p_valid.any():
        ask_l25 = a_p[a_p_valid][-1]  # furthest (highest) ask price among valid
    else:
        ask_l25 = np.nan
    if b_p_valid.any():
        bid_l25 = b_p[b_p_valid][-1]  # furthest (lowest) bid among valid
    else:
        bid_l25 = np.nan
    eff_spread_25 = (ask_l25 - bid_l25) if (np.isfinite(ask_l25) and np.isfinite(bid_l25)) else np.nan

    # Book slope (Kyle's lambda proxy)
    # Bid: regress bid_price on cumulative bid_size (more negative slope = steeper, more liquid)
    # For Kyle's lambda: price impact per unit size
    cum_bs = np.cumsum(b_s_v)
    cum_as = np.cumsum(a_s_v)
    # slope = corr(price, cum_size) * std_price/std_cum_size (using only valid rows)
    bid_slope = np.nan
    if b_p_valid.sum() >= 3:
        y = b_p[b_p_valid].astype(float)
        x = cum_bs[b_p_valid].astype(float)
        if x.std() > 1e-9:
            bid_slope = np.cov(x, y, ddof=0)[0, 1] / np.var(x)  # dprice/dsize, negative for bids
    ask_slope = np.nan
    if a_p_valid.sum() >= 3:
        y = a_p[a_p_valid].astype(float)
        x = cum_as[a_p_valid].astype(float)
        if x.std() > 1e-9:
            ask_slope = np.cov(x, y, ddof=0)[0, 1] / np.var(x)

    # Queue position economics
    total_bs = b_s_v.sum()
    queue_top_bid = bsz0 / total_bs if total_bs > 0 else 0.0

    # Book depth within 2% of mid
    depth_2pct = 0.0
    if np.isfinite(mid) and mid > 0:
        thr = 0.02 * mid
        near_b = b_p_valid & (np.abs(b_p - mid) <= thr)
        near_a = a_p_valid & (np.abs(a_p - mid) <= thr)
        depth_2pct = (b_s_v[near_b].sum() + a_s_v[near_a].sum())

    return {
        "ask0": ask0, "bid0": bid0, "mid": mid, "spread_bps": spread_bps,
        "imb1": imb1, "imb5": imb5, "imb25": imb25,
        "microprice": micro, "micro_dev_bps": micro_dev_bps,
        "eff_spread_25": eff_spread_25,
        "bid_slope": bid_slope, "ask_slope": ask_slope,
        "queue_top_bid": queue_top_bid,
        "depth_2pct": depth_2pct,
        "total_bid_size": total_bs, "total_ask_size": a_s_v.sum(),
    }


# Batched version: takes arrays for ALL fires of one (slug, outcome), returns DataFrame
def compute_features_for_slug(books_idx, slug, outcome, fire_us_list):
    """
    books_idx: dict from load_orderbook_l25_streaming
    slug, outcome: keys
    fire_us_list: 1d array of fire_us values for this slug
    Returns: list of dicts (one per fire_us), or None if no book data
    """
    rec = books_idx.get((slug, outcome))
    if rec is None:
        return None
    ts, ap, asz, bp, bs = rec
    if len(ts) == 0:
        return None
    n_fires = len(fire_us_list)
    results = [None] * n_fires
    for fi, fire_us in enumerate(fire_us_list):
        # Causal: book ts <= fire_us
        pos = int(np.searchsorted(ts, int(fire_us), side="right"))
        if pos == 0:
            continue
        idx = pos - 1
        dt_us = int(fire_us) - int(ts[idx])
        if dt_us > 60_000_000:  # >60s stale
            continue
        f = feats_at_idx(ap, asz, bp, bs, idx)
        f["book_dt_us"] = dt_us
        # Lookback features: book change over last 500ms and 1s
        # Find snapshot at fire_us - 500_000 us and fire_us - 1_000_000 us
        pos_500 = int(np.searchsorted(ts, int(fire_us) - 500_000, side="right"))
        pos_1s = int(np.searchsorted(ts, int(fire_us) - 1_000_000, side="right"))
        if pos_500 > 0:
            f500 = feats_at_idx(ap, asz, bp, bs, pos_500 - 1)
            f["imb5_change_500ms"] = f["imb5"] - f500["imb5"]
            f["mid_change_500ms_bps"] = ((f["mid"] - f500["mid"]) / f500["mid"] * 1e4) if (f500["mid"] > 0) else np.nan
        else:
            f["imb5_change_500ms"] = np.nan
            f["mid_change_500ms_bps"] = np.nan
        if pos_1s > 0:
            f1s = feats_at_idx(ap, asz, bp, bs, pos_1s - 1)
            f["depth_change_1s"] = f["depth_2pct"] - f1s["depth_2pct"]
        else:
            f["depth_change_1s"] = np.nan

        # Quote intensity: number of snapshots in last 1s (note 1Hz subsampling cap)
        # With 1Hz subsampling, this is capped at ~2. Use last 5s for richer signal
        cnt_5s = int(((ts >= int(fire_us) - 5_000_000) & (ts <= int(fire_us))).sum())
        f["quote_intensity_5s"] = cnt_5s

        f["fire_idx"] = fi
        results[fi] = f
    return results


def process_asset(asset, fires_df):
    """
    Stream L25 for asset, compute features for each fire's UP and DN token.
    """
    print(f"\n=== {asset} === ({len(fires_df)} fires)", flush=True)
    slugs = set(fires_df.slug.unique())
    print(f"  unique slugs: {len(slugs)}")

    # Time window from fires
    min_ts = int(fires_df.fire_us.min()) - 10_000_000
    max_ts = int(fires_df.fire_us.max()) + 10_000_000
    print(f"  window: {min_ts/1e6:.0f} -> {max_ts/1e6:.0f}")

    t0 = time.time()
    books_idx = load_orderbook_l25_streaming(
        asset, slugs=slugs, subsample_1hz=True,
        min_ts_us=min_ts, max_ts_us=max_ts,
    )
    print(f"  loaded books: {len(books_idx)} (slug,outcome) keys, elapsed={time.time()-t0:.1f}s")

    # Group fires by slug
    rows = []
    g = fires_df.groupby("slug")
    n_slugs = len(g)
    t1 = time.time()
    for si, (slug, sub) in enumerate(g):
        if si % 1000 == 0 and si > 0:
            print(f"  ...{si}/{n_slugs} slugs, elapsed={time.time()-t1:.1f}s")
        fire_us_arr = sub.fire_us.values.astype("int64")
        # For each fire, compute UP-side and DN-side features
        up_feats = compute_features_for_slug(books_idx, slug, "Up", fire_us_arr)
        dn_feats = compute_features_for_slug(books_idx, slug, "Down", fire_us_arr)
        # iterate fires
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
            for k, v in uf.items():
                if k == "fire_idx":
                    continue
                r[f"up_{k}"] = v
            for k, v in df_f.items():
                if k == "fire_idx":
                    continue
                r[f"dn_{k}"] = v
            # Cross-token features
            r["imb5_diff"] = uf["imb5"] - df_f["imb5"]
            r["imb1_diff"] = uf["imb1"] - df_f["imb1"]
            r["imb25_diff"] = uf["imb25"] - df_f["imb25"]
            r["micro_dev_diff"] = (uf["micro_dev_bps"] - df_f["micro_dev_bps"])
            r["spread_diff"] = uf["spread_bps"] - df_f["spread_bps"]
            r["depth_diff"] = uf["depth_2pct"] - df_f["depth_2pct"]
            rows.append(r)

    del books_idx
    gc.collect()
    df = pd.DataFrame(rows)
    print(f"  produced {len(df)} feature rows in {time.time()-t1:.1f}s (total {time.time()-t0:.1f}s)")
    return df


def main():
    import builtins
    _print = builtins.print
    def flushed_print(*a, **k):
        k.setdefault('flush', True)
        _print(*a, **k)
    builtins.print = flushed_print
    fr5 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_5m.parquet")
    fr15 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_15m.parquet")
    fires = pd.concat([fr5, fr15], ignore_index=True)
    print(f"Total fires: {len(fires)}")

    # Process per asset
    all_dfs = []
    for asset in ["BTC", "ETH", "SOL"]:
        sub = fires[fires.asset == asset].copy()
        df = process_asset(asset, sub)
        out_p = WORK / f"micro_panel_{asset.lower()}.parquet"
        df.to_parquet(out_p)
        print(f"  saved {out_p} ({len(df)} rows)")
        all_dfs.append(df)
        gc.collect()

    final = pd.concat(all_dfs, ignore_index=True)
    final.to_parquet(PANEL)
    print(f"\nFINAL: saved {PANEL} ({len(final)} rows)")


if __name__ == "__main__":
    main()
