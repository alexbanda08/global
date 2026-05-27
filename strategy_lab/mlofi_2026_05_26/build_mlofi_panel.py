"""Build MLOFI (Multi-Level Order Flow Imbalance) panel per Cont/Xu/Gould.

Per Agent N's research: MLOFI extends standard L1-OFI to multiple book levels.
On large-tick instruments (Polymarket binary tokens) MLOFI provides 68-74% RMSE
reduction over single-level OFI.

Formula (Cont, Kukanov, Stoikov 2014 §3 / Xu, Cont, Gould 2019):
    For each PAIR of consecutive book snapshots (prev, curr), at each level i:
      BID side (e_b_i):
        if curr_bid_i > prev_bid_i  (or curr_valid & prev_not_valid): e_b_i = +curr_bid_size_i
        if curr_bid_i == prev_bid_i: e_b_i = curr_bid_size_i - prev_bid_size_i
        if curr_bid_i < prev_bid_i  (or prev_valid & curr_not_valid): e_b_i = -prev_bid_size_i
      ASK side (e_a_i): symmetric with opposite sign
        if curr_ask_i < prev_ask_i (ask improved): e_a_i = +curr_ask_size_i
        if curr_ask_i == prev_ask_i: e_a_i = curr_ask_size_i - prev_ask_size_i
        if curr_ask_i > prev_ask_i: e_a_i = -prev_ask_size_i
      ofi_i = e_b_i - e_a_i  (positive = buy pressure)

    MLOFI(L,T) = sum over events in T-window: sum_{i=1..L} w_i * ofi_i

Window sizes: 30s, 60s; weights w_i = 1/i; also flat-weight cross-check.

VECTORIZED: process ALL events for a (slug, outcome) at once into per-level
ofi arrays, then cumulative sum allows O(log N) window queries per fire.
"""
from __future__ import annotations
import sys, time, gc, os, math
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_orderbook_l25_streaming  # noqa: E402

OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results"
WORK = ROOT / "strategy_lab" / "mlofi_2026_05_26"
WORK.mkdir(exist_ok=True)

LEVELS = 25
WINDOW_SLACK_US = 70_000_000  # 70s safety: max window is 60s + slack


def compute_event_ofi_vectorized(ap_prev, asz_prev, bp_prev, bs_prev,
                                   ap_curr, asz_curr, bp_curr, bs_curr,
                                   levels=25):
    """Compute per-level OFI between two book snapshots (one event).

    Returns: 1D array of size `levels` where ofi_i = e_b_i - e_a_i.

    Kept for unit-tests; production code uses compute_ofi_pairwise (batched).
    """
    asz_p = np.nan_to_num(asz_prev[:levels], nan=0.0)
    bs_p = np.nan_to_num(bs_prev[:levels], nan=0.0)
    asz_c = np.nan_to_num(asz_curr[:levels], nan=0.0)
    bs_c = np.nan_to_num(bs_curr[:levels], nan=0.0)

    ap_p = ap_prev[:levels]
    ap_c = ap_curr[:levels]
    bp_p = bp_prev[:levels]
    bp_c = bp_curr[:levels]

    ap_p_valid = np.isfinite(ap_p) & (ap_p > 0) & (ap_p < 1)
    ap_c_valid = np.isfinite(ap_c) & (ap_c > 0) & (ap_c < 1)
    bp_p_valid = np.isfinite(bp_p) & (bp_p > 0) & (bp_p < 1)
    bp_c_valid = np.isfinite(bp_c) & (bp_c > 0) & (bp_c < 1)

    bs_p = bs_p * bp_p_valid
    bs_c = bs_c * bp_c_valid
    asz_p = asz_p * ap_p_valid
    asz_c = asz_c * ap_c_valid

    # BID side
    up_b = (bp_p_valid & bp_c_valid & (bp_c > bp_p)) | ((~bp_p_valid) & bp_c_valid)
    same_b = (bp_p_valid & bp_c_valid & (bp_p == bp_c)) | ((~bp_p_valid) & (~bp_c_valid))
    same_b = same_b & ~up_b
    down_b = (bp_p_valid & ~bp_c_valid) | (bp_p_valid & bp_c_valid & (bp_c < bp_p))

    e_b = np.zeros(levels, dtype=np.float64)
    e_b[up_b] = bs_c[up_b]
    e_b[same_b] = bs_c[same_b] - bs_p[same_b]
    e_b[down_b] = -bs_p[down_b]

    # ASK side
    up_a = (ap_p_valid & ap_c_valid & (ap_c < ap_p)) | ((~ap_p_valid) & ap_c_valid)
    same_a = (ap_p_valid & ap_c_valid & (ap_p == ap_c)) | ((~ap_p_valid) & (~ap_c_valid))
    same_a = same_a & ~up_a
    down_a = (ap_p_valid & ~ap_c_valid) | (ap_p_valid & ap_c_valid & (ap_c > ap_p))

    e_a = np.zeros(levels, dtype=np.float64)
    e_a[up_a] = asz_c[up_a]
    e_a[same_a] = asz_c[same_a] - asz_p[same_a]
    e_a[down_a] = -asz_p[down_a]

    return e_b - e_a


def compute_ofi_pairwise(ap, asz, bp, bs, levels=25):
    """Vectorized: compute per-level OFI for ALL consecutive pairs in this stream.

    Inputs are (N, 25) arrays. Returns ofi of shape (N-1, levels).

    For event j (using prev=j-1, curr=j):
      ofi[j-1, i] = e_b_i - e_a_i

    Mathematically equivalent to looping compute_event_ofi_vectorized but ~100x faster.
    """
    N = ap.shape[0]
    if N < 2:
        return np.zeros((0, levels), dtype=np.float64)
    # Slice [0:N-1] vs [1:N]
    ap_p = ap[:-1, :levels]
    ap_c = ap[1:, :levels]
    bp_p = bp[:-1, :levels]
    bp_c = bp[1:, :levels]
    asz_p_raw = asz[:-1, :levels]
    asz_c_raw = asz[1:, :levels]
    bs_p_raw = bs[:-1, :levels]
    bs_c_raw = bs[1:, :levels]

    # Replace size NaN with 0
    asz_p = np.where(np.isnan(asz_p_raw), 0.0, asz_p_raw)
    asz_c = np.where(np.isnan(asz_c_raw), 0.0, asz_c_raw)
    bs_p = np.where(np.isnan(bs_p_raw), 0.0, bs_p_raw)
    bs_c = np.where(np.isnan(bs_c_raw), 0.0, bs_c_raw)

    ap_p_valid = np.isfinite(ap_p) & (ap_p > 0) & (ap_p < 1)
    ap_c_valid = np.isfinite(ap_c) & (ap_c > 0) & (ap_c < 1)
    bp_p_valid = np.isfinite(bp_p) & (bp_p > 0) & (bp_p < 1)
    bp_c_valid = np.isfinite(bp_c) & (bp_c > 0) & (bp_c < 1)

    bs_p = bs_p * bp_p_valid
    bs_c = bs_c * bp_c_valid
    asz_p = asz_p * ap_p_valid
    asz_c = asz_c * ap_c_valid

    # Use safe equality on possibly-NaN ap/bp by gating with validity first
    bp_eq = bp_p_valid & bp_c_valid & (bp_p == bp_c)
    bp_curr_higher = bp_p_valid & bp_c_valid & (bp_c > bp_p)
    bp_curr_lower = bp_p_valid & bp_c_valid & (bp_c < bp_p)

    up_b = bp_curr_higher | ((~bp_p_valid) & bp_c_valid)
    same_b = bp_eq | ((~bp_p_valid) & (~bp_c_valid))
    same_b = same_b & ~up_b
    down_b = (bp_p_valid & ~bp_c_valid) | bp_curr_lower

    e_b = np.where(up_b, bs_c,
            np.where(same_b, bs_c - bs_p,
              np.where(down_b, -bs_p, 0.0)))

    ap_eq = ap_p_valid & ap_c_valid & (ap_p == ap_c)
    ap_curr_lower = ap_p_valid & ap_c_valid & (ap_c < ap_p)
    ap_curr_higher = ap_p_valid & ap_c_valid & (ap_c > ap_p)

    up_a = ap_curr_lower | ((~ap_p_valid) & ap_c_valid)
    same_a = ap_eq | ((~ap_p_valid) & (~ap_c_valid))
    same_a = same_a & ~up_a
    down_a = (ap_p_valid & ~ap_c_valid) | ap_curr_higher

    e_a = np.where(up_a, asz_c,
            np.where(same_a, asz_c - asz_p,
              np.where(down_a, -asz_p, 0.0)))

    return e_b - e_a   # shape (N-1, levels)


def compute_features_for_slug(books_idx, slug, outcome, fire_us_list,
                               weights_5, weights_25):
    """For all fires of this (slug, outcome), compute MLOFI 30s+60s windows."""
    rec = books_idx.get((slug, outcome))
    if rec is None:
        return [None] * len(fire_us_list)
    ts, ap, asz, bp, bs = rec
    if len(ts) < 2:
        return [None] * len(fire_us_list)
    # Pre-compute pairwise OFI for ALL events at once
    ofi = compute_ofi_pairwise(ap, asz, bp, bs, levels=LEVELS)
    # ofi[j-1] corresponds to event j (j in 1..N-1). Time index for event j is ts[j].
    # cumulative sums for fast window queries
    # We sum ofi rows [a, b] inclusive where ts[a..b] in [lo_us, fire_us]
    # Per-level cumsum (prepend zero row)
    ofi_cum = np.vstack([np.zeros(LEVELS), np.cumsum(ofi, axis=0)])  # shape (N, LEVELS)
    # ofi_cum[k] = sum of ofi[0..k-1] = sum of events 1..k
    # Sum of events whose ts in [lo, hi]: find indices j_lo..j_hi where ts[j] in [lo, hi]
    # Each event j (j>=1) is associated with ts[j].
    # Use searchsorted on ts.

    n_fires = len(fire_us_list)
    out = [None] * n_fires
    for fi, fire_us in enumerate(fire_us_list):
        fire_us = int(fire_us)
        # Window 30s
        lo30 = fire_us - 30_000_000
        lo60 = fire_us - 60_000_000
        # Strictly events with ts in (lo, fire_us] but each event j has ts[j].
        # Each ofi[j-1] corresponds to transition from snap j-1 to snap j.
        # We want events j with ts[j] in [lo, fire_us]. j ranges 1..N-1.
        j_hi = int(np.searchsorted(ts, fire_us, side="right")) - 1  # last j with ts[j]<=fire_us
        # OFI row index = j-1; so we want rows [j_lo_low, j_hi-1] (= range of valid offsets)
        # For 30s
        j_lo_30 = int(np.searchsorted(ts, lo30, side="left"))   # first j with ts[j]>=lo30
        j_lo_60 = int(np.searchsorted(ts, lo60, side="left"))

        # Sum of ofi rows over [j_lo-1 .. j_hi-1] (inclusive) corresponds to events [j_lo..j_hi]
        # Use cumulative sums:
        #   sum(ofi[a..b-1]) = ofi_cum[b] - ofi_cum[a]
        # We want sum(ofi[j_lo-1 .. j_hi-1]) = ofi_cum[j_hi] - ofi_cum[j_lo-1]
        # If j_lo>=1 we use j_lo-1; if j_lo==0 we use 0.
        if j_hi < 1:  # no events
            out[fi] = {
                "ofi_l1_30s": np.nan, "ofi_l1_60s": np.nan,
                "mlofi_l5_30s": np.nan, "mlofi_l5_60s": np.nan,
                "mlofi_l25_30s": np.nan, "mlofi_l25_60s": np.nan,
                "mlofi_l5_flat_30s": np.nan,
                "n_events_30s": 0, "n_events_60s": 0,
            }
            continue

        # 30s window: events [max(1, j_lo_30) .. j_hi]
        j_start_30 = max(1, j_lo_30)
        j_start_60 = max(1, j_lo_60)
        # Number of events in window
        n30 = j_hi - j_start_30 + 1
        n60 = j_hi - j_start_60 + 1
        # Sum per-level OFI
        # cum index: ofi_cum[k] = sum of first k rows (rows 0..k-1)
        # Sum of rows [j_start-1 .. j_hi-1] inclusive
        #   = ofi_cum[j_hi] - ofi_cum[j_start-1]
        idx_lo_30 = j_start_30 - 1
        idx_lo_60 = j_start_60 - 1
        if n30 < 1:
            f30 = None
        else:
            per_level_30 = ofi_cum[j_hi] - ofi_cum[idx_lo_30]
            f30 = {
                "ofi_l1": float(per_level_30[0]),
                "mlofi_l5": float((per_level_30[:5] * weights_5).sum()),
                "mlofi_l25": float((per_level_30 * weights_25).sum()),
                "mlofi_l5_flat": float(per_level_30[:5].sum()),
                "n_events": int(n30),
            }
        if n60 < 1:
            f60 = None
        else:
            per_level_60 = ofi_cum[j_hi] - ofi_cum[idx_lo_60]
            f60 = {
                "ofi_l1": float(per_level_60[0]),
                "mlofi_l5": float((per_level_60[:5] * weights_5).sum()),
                "mlofi_l25": float((per_level_60 * weights_25).sum()),
                "mlofi_l5_flat": float(per_level_60[:5].sum()),
                "n_events": int(n60),
            }
        out[fi] = {
            "ofi_l1_30s": f30["ofi_l1"] if f30 else np.nan,
            "ofi_l1_60s": f60["ofi_l1"] if f60 else np.nan,
            "mlofi_l5_30s": f30["mlofi_l5"] if f30 else np.nan,
            "mlofi_l5_60s": f60["mlofi_l5"] if f60 else np.nan,
            "mlofi_l25_30s": f30["mlofi_l25"] if f30 else np.nan,
            "mlofi_l25_60s": f60["mlofi_l25"] if f60 else np.nan,
            "mlofi_l5_flat_30s": f30["mlofi_l5_flat"] if f30 else np.nan,
            "n_events_30s": f30["n_events"] if f30 else 0,
            "n_events_60s": f60["n_events"] if f60 else 0,
        }
    return out


def _process_slug_batch(books_idx, fires_df, weights_5, weights_25):
    """Compute MLOFI features for all (slug, fires) in `fires_df` given pre-loaded books."""
    rows = []
    g = fires_df.groupby("slug")
    for slug, sub in g:
        fire_us_arr = sub.fire_us.values.astype("int64")
        up_feats = compute_features_for_slug(books_idx, slug, "Up", fire_us_arr,
                                              weights_5, weights_25)
        dn_feats = compute_features_for_slug(books_idx, slug, "Down", fire_us_arr,
                                              weights_5, weights_25)
        for fi, (_, row) in enumerate(sub.iterrows()):
            uf = up_feats[fi] if up_feats else None
            df_f = dn_feats[fi] if dn_feats else None
            if uf is None or df_f is None:
                continue
            r = {
                "asset": row["asset"], "slug": slug, "tf": row["tf"],
                "fire_us": int(row["fire_us"]),
                "fire_offset_s": int(row["fire_offset_s"]),
                "outcome": row["outcome"], "ws_s": int(row["ws_s"]),
            }
            for k, v in uf.items():
                r[f"up_{k}"] = v
            for k, v in df_f.items():
                r[f"dn_{k}"] = v
            def _sd(a, b):
                return (a - b) if (np.isfinite(a) and np.isfinite(b)) else np.nan
            r["mlofi_skew_l5_30s"] = _sd(uf["mlofi_l5_30s"], df_f["mlofi_l5_30s"])
            r["mlofi_skew_l5_60s"] = _sd(uf["mlofi_l5_60s"], df_f["mlofi_l5_60s"])
            r["mlofi_skew_l25_30s"] = _sd(uf["mlofi_l25_30s"], df_f["mlofi_l25_30s"])
            r["ofi_skew_l1_30s"] = _sd(uf["ofi_l1_30s"], df_f["ofi_l1_30s"])
            if uf["n_events_30s"] > 0 and np.isfinite(uf["mlofi_l5_30s"]):
                r["up_mlofi_l5_per_event_30s"] = uf["mlofi_l5_30s"] / uf["n_events_30s"]
            else:
                r["up_mlofi_l5_per_event_30s"] = np.nan
            if df_f["n_events_30s"] > 0 and np.isfinite(df_f["mlofi_l5_30s"]):
                r["dn_mlofi_l5_per_event_30s"] = df_f["mlofi_l5_30s"] / df_f["n_events_30s"]
            else:
                r["dn_mlofi_l5_per_event_30s"] = np.nan
            rows.append(r)
    return rows


def process_asset(asset, fires_df, batch_size=1000):
    """Stream L25 raw event books in slug-batches; compute MLOFI per fire."""
    print(f"\n=== {asset} === ({len(fires_df)} fires)", flush=True)
    slugs_all = sorted(fires_df.slug.unique())
    print(f"  unique slugs: {len(slugs_all)}", flush=True)

    weights_5 = np.array([1.0 / (i + 1) for i in range(5)], dtype=np.float64)
    weights_25 = np.array([1.0 / (i + 1) for i in range(LEVELS)], dtype=np.float64)

    all_rows = []
    t_overall = time.time()
    n_batches = (len(slugs_all) + batch_size - 1) // batch_size
    for bi in range(n_batches):
        slug_batch = set(slugs_all[bi*batch_size : (bi+1)*batch_size])
        sub_fires = fires_df[fires_df.slug.isin(slug_batch)]
        min_ts = int(sub_fires.fire_us.min()) - WINDOW_SLACK_US
        max_ts = int(sub_fires.fire_us.max()) + 5_000_000
        t0 = time.time()
        books_idx = load_orderbook_l25_streaming(
            asset, slugs=slug_batch, subsample_1hz=False,
            min_ts_us=min_ts, max_ts_us=max_ts,
        )
        t_load = time.time() - t0
        n_events = sum(len(v[0]) for v in books_idx.values())
        t1 = time.time()
        batch_rows = _process_slug_batch(books_idx, sub_fires, weights_5, weights_25)
        t_compute = time.time() - t1
        all_rows.extend(batch_rows)
        elapsed_total = time.time() - t_overall
        slugs_done = (bi+1) * batch_size
        eta = (elapsed_total / slugs_done) * (len(slugs_all) - slugs_done) if slugs_done > 0 else 0
        print(f"  batch {bi+1}/{n_batches} ({len(slug_batch)} slugs, {n_events:,} events): "
              f"load={t_load:.1f}s, compute={t_compute:.1f}s, "
              f"total_elapsed={elapsed_total:.0f}s, eta_remaining={eta:.0f}s, rows={len(all_rows)}",
              flush=True)
        del books_idx
        gc.collect()
    df = pd.DataFrame(all_rows)
    print(f"  produced {len(df)} feature rows in {time.time()-t_overall:.1f}s total", flush=True)
    return df


def main():
    import builtins
    _print = builtins.print
    def fp(*a, **k):
        k.setdefault('flush', True); _print(*a, **k)
    builtins.print = fp

    fr5 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_5m.parquet")
    fr15 = pd.read_parquet(OUT_DIR / "hybrid_fire_universe_15m.parquet")
    fires = pd.concat([fr5, fr15], ignore_index=True)
    print(f"Total fires: {len(fires)}")

    target = os.environ.get("MLOFI_ASSET", "ALL").upper()
    if target != "ALL":
        assets = [target]
    else:
        assets = ["BTC", "ETH", "SOL"]

    for asset in assets:
        out_p = WORK / f"mlofi_panel_{asset.lower()}.parquet"
        if out_p.exists():
            print(f"SKIP {asset}: {out_p} exists ({out_p.stat().st_size/1e6:.1f}MB)")
            continue
        sub = fires[fires.asset == asset].copy()
        df = process_asset(asset, sub)
        df.to_parquet(out_p)
        print(f"  saved {out_p} ({len(df)} rows, {out_p.stat().st_size/1e6:.1f}MB)")
        gc.collect()

    parts = []
    for a in ["BTC", "ETH", "SOL"]:
        p = WORK / f"mlofi_panel_{a.lower()}.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p))
    if len(parts) == 3:
        final = pd.concat(parts, ignore_index=True)
        out_p = OUT_DIR / "mlofi_panel.parquet"
        final.to_parquet(out_p)
        print(f"\nFINAL: saved {out_p} ({len(final)} rows)")


if __name__ == "__main__":
    main()
