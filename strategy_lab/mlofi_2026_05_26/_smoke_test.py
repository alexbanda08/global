"""Smoke test MLOFI implementation on a 10-slug subset."""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "mlofi_2026_05_26"))

from build_mlofi_panel import (
    compute_event_ofi_vectorized,
    compute_ofi_pairwise,
    compute_features_for_slug,
    process_asset,
    LEVELS,
)

def test_event_ofi_basic():
    """Verify per-level OFI formula on a tiny canonical example."""
    # Two snapshots, 5 levels:
    # prev:  bids=[(0.50,100),(0.49,200)],  asks=[(0.51,150),(0.52,100)]
    # curr:  bids=[(0.50,150),(0.49,200)],  asks=[(0.51,100),(0.52,100)]
    # Expected: bid L0: same price, +50 size  -> e_b=+50
    #           bid L1: same price, same size -> e_b=0
    #           ask L0: same price, -50 size -> e_a=-50
    #           ask L1: same           -> e_a=0
    # ofi[0] = e_b - e_a = 50 - (-50) = 100  (strong buy pressure)
    ap_p = np.array([0.51, 0.52, np.nan, np.nan, np.nan])
    asz_p = np.array([150, 100, 0, 0, 0], dtype=float)
    bp_p = np.array([0.50, 0.49, np.nan, np.nan, np.nan])
    bs_p = np.array([100, 200, 0, 0, 0], dtype=float)
    ap_c = np.array([0.51, 0.52, np.nan, np.nan, np.nan])
    asz_c = np.array([100, 100, 0, 0, 0], dtype=float)
    bp_c = np.array([0.50, 0.49, np.nan, np.nan, np.nan])
    bs_c = np.array([150, 200, 0, 0, 0], dtype=float)
    ofi = compute_event_ofi_vectorized(ap_p, asz_p, bp_p, bs_p,
                                         ap_c, asz_c, bp_c, bs_c, levels=5)
    print(f"test_basic: ofi = {ofi}")
    assert abs(ofi[0] - 100) < 1e-9, f"expected 100 at L0, got {ofi[0]}"
    assert abs(ofi[1] - 0) < 1e-9, f"expected 0 at L1, got {ofi[1]}"
    print("  PASS")


def test_event_ofi_improved_bid():
    """Per Cont 2014/Xu 2019, MLOFI is per-LEVEL-INDEX (rank), not per-price.
    When best bid improves, the old top displaces to L2 — this counts as +flow at both."""
    # prev:  bid=[(0.50,100)]
    # curr:  bid=[(0.51,80),(0.50,100)]   <- new top bid at 0.51
    # L1: prev_price=0.50, curr_price=0.51 -> up_b -> e_b = +80 (new improved level)
    # L2: prev=invalid, curr=(0.50,100) -> up_b (curr valid, prev not) -> e_b = +100
    #     This is correct per Cont: the L2 SLOT went from empty to filled, counted as flow.
    ap_p = np.array([0.55, np.nan, np.nan, np.nan, np.nan])
    asz_p = np.array([50, 0, 0, 0, 0], dtype=float)
    bp_p = np.array([0.50, np.nan, np.nan, np.nan, np.nan])
    bs_p = np.array([100, 0, 0, 0, 0], dtype=float)
    ap_c = np.array([0.55, np.nan, np.nan, np.nan, np.nan])
    asz_c = np.array([50, 0, 0, 0, 0], dtype=float)
    bp_c = np.array([0.51, 0.50, np.nan, np.nan, np.nan])
    bs_c = np.array([80, 100, 0, 0, 0], dtype=float)
    ofi = compute_event_ofi_vectorized(ap_p, asz_p, bp_p, bs_p,
                                         ap_c, asz_c, bp_c, bs_c, levels=5)
    print(f"test_improved_bid: ofi = {ofi}")
    assert abs(ofi[0] - 80) < 1e-9, f"expected +80 at L1 (new top), got {ofi[0]}"
    assert abs(ofi[1] - 100) < 1e-9, f"expected +100 at L2 (displaced old top), got {ofi[1]}"
    print("  PASS")


def test_event_ofi_bid_drop():
    """When best bid disappears entirely."""
    # prev: bid=[(0.50,100)]
    # curr: bid=[(0.49,80)]
    # L0: curr_price (0.49) < prev_price (0.50) -> down_b -> e_b = -100 (level vanished)
    # L1: prev invalid, curr invalid -> no change -> 0
    ap_p = np.array([0.55, np.nan, np.nan, np.nan, np.nan])
    asz_p = np.array([50, 0, 0, 0, 0], dtype=float)
    bp_p = np.array([0.50, np.nan, np.nan, np.nan, np.nan])
    bs_p = np.array([100, 0, 0, 0, 0], dtype=float)
    ap_c = np.array([0.55, np.nan, np.nan, np.nan, np.nan])
    asz_c = np.array([50, 0, 0, 0, 0], dtype=float)
    bp_c = np.array([0.49, np.nan, np.nan, np.nan, np.nan])
    bs_c = np.array([80, 0, 0, 0, 0], dtype=float)
    ofi = compute_event_ofi_vectorized(ap_p, asz_p, bp_p, bs_p,
                                         ap_c, asz_c, bp_c, bs_c, levels=5)
    print(f"test_bid_drop: ofi = {ofi}")
    assert abs(ofi[0] - (-100)) < 1e-9, f"expected -100 at L0 (bid vanished), got {ofi[0]}"
    print("  PASS")


def test_ask_improvement():
    """Ask price drops (better ask, more sell pressure)."""
    # prev: ask=[(0.55,100)]
    # curr: ask=[(0.54,80),(0.55,100)]
    # L0: curr_a (0.54) < prev_a (0.55) -> up_a -> e_a = +80
    # ofi[0] = e_b - e_a = 0 - 80 = -80 (sell pressure)
    ap_p = np.array([0.55, np.nan, np.nan, np.nan, np.nan])
    asz_p = np.array([100, 0, 0, 0, 0], dtype=float)
    bp_p = np.array([0.50, np.nan, np.nan, np.nan, np.nan])
    bs_p = np.array([50, 0, 0, 0, 0], dtype=float)
    ap_c = np.array([0.54, 0.55, np.nan, np.nan, np.nan])
    asz_c = np.array([80, 100, 0, 0, 0], dtype=float)
    bp_c = np.array([0.50, np.nan, np.nan, np.nan, np.nan])
    bs_c = np.array([50, 0, 0, 0, 0], dtype=float)
    ofi = compute_event_ofi_vectorized(ap_p, asz_p, bp_p, bs_p,
                                         ap_c, asz_c, bp_c, bs_c, levels=5)
    print(f"test_ask_improvement: ofi = {ofi}")
    assert abs(ofi[0] - (-80)) < 1e-9, f"expected -80 at L0, got {ofi[0]}"
    print("  PASS")


def test_mlofi_window_aggregation():
    """3 events; window covers all; verify accumulation via compute_features_for_slug."""
    ts = np.array([1000_000_000, 1010_000_000, 1020_000_000], dtype=np.int64)
    ap = np.full((3, 25), np.nan); asz = np.zeros((3, 25))
    bp = np.full((3, 25), np.nan); bs = np.zeros((3, 25))
    ap[:, 0] = 0.55; asz[:, 0] = 50
    bp[:, 0] = 0.50
    bs[0, 0] = 100; bs[1, 0] = 150; bs[2, 0] = 200
    w5 = np.array([1.0 / (i + 1) for i in range(5)], dtype=np.float64)
    w25 = np.array([1.0 / (i + 1) for i in range(25)], dtype=np.float64)
    fire_us = 1020_500_000  # 500ms after last event
    books_idx = {("SLUG", "Up"): (ts, ap, asz, bp, bs)}
    feats_list = compute_features_for_slug(books_idx, "SLUG", "Up", [fire_us], w5, w25)
    f = feats_list[0]
    # Expected: ofi[0] sum over 2 transitions = +50 + +50 = +100; mlofi_l5 = 100*1.0 = 100
    assert abs(f["ofi_l1_30s"] - 100) < 1e-9, f"expected 100 ofi_l1_30s, got {f['ofi_l1_30s']}"
    assert abs(f["mlofi_l5_30s"] - 100) < 1e-9, f"expected 100 mlofi_l5_30s, got {f['mlofi_l5_30s']}"
    print(f"test_mlofi_window: {f}")
    print("  PASS")


def test_pairwise_matches_loop():
    """Verify vectorized pairwise gives same result as per-event loop."""
    np.random.seed(0)
    N = 50
    ap = np.full((N, 25), np.nan)
    asz = np.zeros((N, 25))
    bp = np.full((N, 25), np.nan)
    bs = np.zeros((N, 25))
    # Random walk on prices and sizes
    for j in range(N):
        nlev = np.random.randint(3, 25)
        ap[j, :nlev] = np.sort(0.5 + np.random.uniform(0.01, 0.2, nlev))[::-1]
        ap[j, :nlev] = np.sort(ap[j, :nlev])  # ascending
        asz[j, :nlev] = np.random.uniform(50, 500, nlev)
        bp[j, :nlev] = np.sort(0.5 - np.random.uniform(0.01, 0.2, nlev))[::-1]  # descending
        bs[j, :nlev] = np.random.uniform(50, 500, nlev)
    ofi_vec = compute_ofi_pairwise(ap, asz, bp, bs, levels=25)
    # Loop version
    ofi_loop = np.zeros((N-1, 25))
    for j in range(N-1):
        ofi_loop[j] = compute_event_ofi_vectorized(
            ap[j], asz[j], bp[j], bs[j],
            ap[j+1], asz[j+1], bp[j+1], bs[j+1], levels=25,
        )
    assert np.allclose(ofi_vec, ofi_loop, atol=1e-9), (
        f"vectorized vs loop differ; max diff = {np.abs(ofi_vec - ofi_loop).max()}"
    )
    print(f"test_pairwise_matches: max diff = {np.abs(ofi_vec - ofi_loop).max():.2e}")
    print("  PASS")


def test_on_real_slug():
    """Smoke: 5 BTC slugs, full pipeline."""
    fr5 = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_fire_universe_5m.parquet")
    btc = fr5[fr5.asset == "BTC"].head(50)
    btc = btc[btc.slug.isin(btc.slug.unique()[:5])]
    print(f"  testing on {len(btc)} fires across {btc.slug.nunique()} slugs")
    t0 = time.time()
    df = process_asset("BTC", btc)
    print(f"  elapsed: {time.time()-t0:.1f}s, rows: {len(df)}")
    print(df.head())
    print()
    print("  feature distribution:")
    for c in ["up_mlofi_l5_30s", "up_mlofi_l25_30s", "up_ofi_l1_30s", "mlofi_skew_l5_30s"]:
        print(f"    {c}: mean={df[c].mean():.2f}, std={df[c].std():.2f}, "
              f"n_finite={df[c].notna().sum()}/{len(df)}")
    print("  PASS")


if __name__ == "__main__":
    print("=== SMOKE TESTS ===")
    test_event_ofi_basic()
    test_event_ofi_improved_bid()
    test_event_ofi_bid_drop()
    test_ask_improvement()
    test_mlofi_window_aggregation()
    test_pairwise_matches_loop()
    print()
    print("=== REAL DATA SMOKE ===")
    test_on_real_slug()
