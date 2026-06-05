"""
jump_asym_s4_2026_06_02.py — S4 negative-jump-asymmetry analysis + scalp downside risk.

(a) A = RS+/(RS+ + RS-) over 120s before fire_us.
    Test A<0.35 as DOWN-token predictor on BTC+ETH delta>=3 (n=1342):
      - WR of DOWN when A<0.35
      - TIME+90s scalp PnL on those A<0.35 fires vs the full universe
      - Also test A>0.65 as UP-token predictor for symmetry

(b) Worst-case scalp risk on TIME+90s exit (delta>=5, n=430, from existing scalp parquet):
      - Distribution of per-trade PnL at FEE0 and FEE07
      - Max drawdown (cumsum of trades sorted by time), worst-5% per-trade

Uses precomputed stage2 features for A120 (same formula as edge_val_stage2_klines_2026_06_01.py).
For TIME+90s PnL: recomputes from the existing scalp_exit_validation_2026_06_02.parquet.

Usage: C:/Python314/python.exe strategy_lab/directional/jump_asym_s4_2026_06_02.py
"""
from __future__ import annotations
import sys, math, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_orderbook_l25_streaming
from engine_v2 import LiveMimicConfig, find_book_strict, sell_at_bid_partial

FIRES_PATH = ROOT / "strategy_lab" / "lag_taker_fires_oos_2026_06_01.parquet"
STAGE2_FEAT = ROOT / "strategy_lab" / "directional" / "_results" / "edge_val_stage2_features_2026_06_01.parquet"
SCALP_PARQUET = ROOT / "strategy_lab" / "directional" / "_results" / "scalp_exit_validation_2026_06_02.parquet"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
OUT.mkdir(parents=True, exist_ok=True)

WIN = {"5m": 300, "15m": 900}
FEE = 0.07
LAT = 85_000  # 85ms in us


def fee_share(v):
    return FEE * v * (1.0 - v)


def stat(x):
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return np.nan, np.nan, n
    m = x.mean()
    se = x.std(ddof=1) / np.sqrt(n)
    t = m / se if se > 0 else np.nan
    return m, t, n


def norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def z_prop(k, n, p0=0.5):
    if n == 0:
        return np.nan, np.nan
    ph = k / n
    se = math.sqrt(p0 * (1 - p0) / n)
    if se == 0:
        return ph, np.nan
    z = (ph - p0) / se
    return ph, z


def roundtrip_fee0(exit_vwap, entry_vwap, shares):
    return (exit_vwap - entry_vwap) * shares


def roundtrip_fee07(exit_vwap, entry_vwap, shares):
    rt = (exit_vwap - entry_vwap) * shares
    rt -= (fee_share(entry_vwap) + fee_share(exit_vwap)) * shares
    return rt


def hold_pnl_legacy(row):
    """Hold-to-resolution pnl under legacy 2%-on-profit (what parquet.pnl uses)."""
    return float(row.pnl)


def hold_pnl_fee07(row):
    """Hold-to-resolution under 0.07 winner-only (from CLAUDE.md note)."""
    ev = float(row.entry_vwap)
    sh = float(row.shares)
    if row.won:
        return (1 - ev) * sh * (1 - FEE * ev)
    else:
        return -ev * sh


# ============================================================
# PART A: S4 jump-asymmetry signal on delta>=3 universe
# ============================================================

def part_a():
    print("\n" + "=" * 80)
    print("PART A: S4 semivariance asymmetry A120 as directional signal + scalp")
    print("        BTC+ETH delta>=3; A from precomputed stage2 features")
    print("=" * 80)

    t0 = time.time()
    # Load fires
    fires = pd.read_parquet(FIRES_PATH)
    fires = fires[(fires.asset.isin(["BTC", "ETH"])) & (fires.delta_bps >= 3)].copy()
    fires["ws_s"] = (fires.slot_start - fires.tf.map(WIN)).astype(np.int64)
    print(f"Fires (BTC+ETH delta>=3): n={len(fires)}")

    # Load precomputed A120 from stage2 features
    feat = pd.read_parquet(STAGE2_FEAT, columns=["asset", "tf", "ws_s", "A60", "A120", "A300"])
    fires = fires.merge(feat, on=["asset", "tf", "ws_s"], how="left")
    print(f"After merge: n={len(fires)}, A120 notna={fires.A120.notna().sum()}")

    # Define direction buckets
    # A<0.35 => downside vol dominated => favour DOWN token
    # A>0.65 => upside vol dominated => favour UP token
    fires["A_signal"] = "neutral"
    fires.loc[fires.A120 < 0.35, "A_signal"] = "DOWN_favour"
    fires.loc[fires.A120 > 0.65, "A_signal"] = "UP_favour"

    # For each fire, we know 'direction' (what lag-taker fired) and 'won' (did it win)
    # We want to test: when A120 < 0.35, does DOWN side win more?
    # i.e., does A120 < 0.35 AND direction==DOWN have higher WR than base?

    base_wr = fires.won.mean()
    print(f"\nBase WR (all fires, won means lag-taker direction won): {base_wr:.3f} n={len(fires)}")

    print("\n--- A120 split: WR of the lag-taker's 'won' by A bucket ---")
    print(f"{'bucket':<20} {'n':>6} {'WR':>8} {'z vs 0.5':>10}")
    for lab, mask in [
        ("A<0.35 (DOWN_fav)", fires.A120 < 0.35),
        ("0.35<=A<=0.65", (fires.A120 >= 0.35) & (fires.A120 <= 0.65)),
        ("A>0.65 (UP_fav)", fires.A120 > 0.65),
        ("all", pd.Series([True] * len(fires), index=fires.index)),
    ]:
        g = fires[mask]
        n = len(g)
        k = g.won.sum()
        wr, z = z_prop(k, n, 0.5)
        print(f"{lab:<20} {n:>6} {wr:>8.3f} {z:>10.2f}")

    print("\n--- A<0.35 fires: WR split by direction of the lag-taker fire ---")
    down_mask = fires.A120 < 0.35
    for direction in ["Up", "Down"]:
        g = fires[down_mask & (fires.direction == direction)]
        n = len(g)
        k = g.won.sum()
        wr, z = z_prop(k, n, 0.5)
        print(f"  direction={direction:<5} n={n:>4} WR={wr:.3f} z={z:.2f}")

    print("\n--- A<0.35 DOWN-token fires: does betting on DOWN (A<0.35) give higher WR? ---")
    # When A<0.35 AND direction==Down: does 'won' (Down wins) differ from base?
    # Also compute: if A<0.35 and lag-taker fired Down, what's the WR vs if A>=0.35 and fired Down?
    for athr, lab in [(0.35, "A<0.35"), (0.40, "A<0.40"), (0.45, "A<0.45")]:
        for direction in ["Down", "Up"]:
            g = fires[(fires.A120 < athr) & (fires.direction == direction)]
            base = fires[fires.direction == direction]
            n = len(g); nb = len(base); kb = base.won.sum()
            base_wr_dir = kb / nb if nb > 0 else np.nan
            k = g.won.sum()
            wr, z = z_prop(k, n, base_wr_dir)
            print(f"  {lab}, dir={direction}: n={n:>4} WR={wr:.3f} (base_dir={base_wr_dir:.3f}) z_vs_base={z:.2f}")

    # Now load L25 books for TIME+90s scalp on the A<0.35 subset
    print("\n--- Loading L25 for TIME+90s scalp on A<0.35 fires (BTC+ETH delta>=3) ---")
    down_asym_fires = fires[fires.A120 < 0.35].copy()
    print(f"  A<0.35 fires: n={len(down_asym_fires)}")

    cfg = LiveMimicConfig()
    scalp_recs = []

    for asset in ["BTC", "ETH"]:
        sub = down_asym_fires[down_asym_fires.asset == asset]
        if sub.empty:
            continue
        slugs = set(sub.slug.values)
        print(f"  [{asset}] loading L25 for {len(slugs)} slugs...", flush=True)
        books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
        print(f"  [{asset}] loaded t={time.time()-t0:.0f}s", flush=True)

        for _, r in sub.iterrows():
            slug = r.slug
            side = r.direction
            fire_us = int(r.fire_us)
            shares = float(r.shares)
            ev = float(r.entry_vwap)
            won = bool(r.won)
            ss = int(r.slot_start)
            win = WIN[r.tf]

            # TIME+90s exit
            t90_us = fire_us + 90_000_000
            bk = find_book_strict(books, slug, side, t90_us + LAT,
                                  max_staleness_us=cfg.max_book_staleness_us)
            exit_vwap = None
            if bk is not None and len(bk.get("bp", [])):
                bp = np.asarray(bk["bp"], float)
                bsz = np.asarray(bk["bsz"], float)
                vw, fsh, _usd = sell_at_bid_partial(bp, bsz, shares)
                if fsh > 0:
                    exit_vwap = vw

            scalp_recs.append(dict(
                slug=slug, asset=asset, side=side, won=won,
                entry_vwap=ev, shares=shares, A120=float(r.A120),
                exit_vwap_t90=exit_vwap,
            ))
        del books

    SA = pd.DataFrame(scalp_recs)
    print(f"\n  A<0.35 scalp records: n={len(SA)}, time90 hit={SA.exit_vwap_t90.notna().sum()}")

    # Compute PnL for A<0.35 TIME+90s
    def pnl_time90(row, fee):
        ev = row.entry_vwap
        sh = row.shares
        ex = row.exit_vwap_t90
        if pd.notna(ex):
            rt = (ex - ev) * sh
            if fee:
                rt -= (fee_share(ev) + fee_share(ex)) * sh
            return rt
        else:
            # fallback: hold
            if row.won:
                return (1 - ev) * sh * (1 - FEE * ev)
            else:
                return -ev * sh

    print("\n--- TIME+90s scalp on A<0.35 fires ---")
    print(f"{'subset':<30} {'n':>5} {'$/tr_FEE0':>11} {'t_FEE0':>8} {'$/tr_FEE07':>12} {'t_FEE07':>9}")

    # A<0.35 all directions
    pnl0 = SA.apply(lambda r: pnl_time90(r, False), axis=1).to_numpy()
    pnl7 = SA.apply(lambda r: pnl_time90(r, True), axis=1).to_numpy()
    m0, t0_, n0 = stat(pnl0)
    m7, t7, n7 = stat(pnl7)
    print(f"{'A<0.35 all':30} {n0:>5} {m0:>11.3f} {t0_:>8.2f} {m7:>12.3f} {t7:>9.2f}")

    # A<0.35 direction==Down only
    sub_d = SA[SA.side == "Down"]
    if len(sub_d) >= 5:
        pnl0d = sub_d.apply(lambda r: pnl_time90(r, False), axis=1).to_numpy()
        pnl7d = sub_d.apply(lambda r: pnl_time90(r, True), axis=1).to_numpy()
        m0d, t0d, n0d = stat(pnl0d)
        m7d, t7d, _ = stat(pnl7d)
        print(f"{'A<0.35 dir=Down':30} {n0d:>5} {m0d:>11.3f} {t0d:>8.2f} {m7d:>12.3f} {t7d:>9.2f}")

    # A<0.35 direction==Up
    sub_u = SA[SA.side == "Up"]
    if len(sub_u) >= 5:
        pnl0u = sub_u.apply(lambda r: pnl_time90(r, False), axis=1).to_numpy()
        pnl7u = sub_u.apply(lambda r: pnl_time90(r, True), axis=1).to_numpy()
        m0u, t0u, n0u = stat(pnl0u)
        m7u, t7u, _ = stat(pnl7u)
        print(f"{'A<0.35 dir=Up':30} {n0u:>5} {m0u:>11.3f} {t0u:>8.2f} {m7u:>12.3f} {t7u:>9.2f}")

    # Compare to full delta>=3 universe TIME+90s (load all slugs for both assets)
    print("\n--- TIME+90s scalp on FULL delta>=3 universe (BTC+ETH) for comparison ---")
    full_recs = []
    for asset in ["BTC", "ETH"]:
        sub = fires[fires.asset == asset]
        if sub.empty:
            continue
        slugs = set(sub.slug.values)
        print(f"  [{asset}] loading L25 for full delta>=3 ({len(slugs)} slugs)...", flush=True)
        books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
        print(f"  [{asset}] loaded t={time.time()-t0:.0f}s", flush=True)
        for _, r in sub.iterrows():
            slug = r.slug; side = r.direction; fire_us = int(r.fire_us)
            shares = float(r.shares); ev = float(r.entry_vwap); won = bool(r.won)
            t90_us = fire_us + 90_000_000
            bk = find_book_strict(books, slug, side, t90_us + LAT,
                                  max_staleness_us=cfg.max_book_staleness_us)
            exit_vwap = None
            if bk is not None and len(bk.get("bp", [])):
                bp = np.asarray(bk["bp"], float)
                bsz = np.asarray(bk["bsz"], float)
                vw, fsh, _usd = sell_at_bid_partial(bp, bsz, shares)
                if fsh > 0:
                    exit_vwap = vw
            full_recs.append(dict(
                slug=slug, asset=asset, side=side, won=won,
                entry_vwap=ev, shares=shares, A120=r.A120,
                exit_vwap_t90=exit_vwap,
            ))
        del books

    FA = pd.DataFrame(full_recs)
    pnl0f = FA.apply(lambda r: pnl_time90(r, False), axis=1).to_numpy()
    pnl7f = FA.apply(lambda r: pnl_time90(r, True), axis=1).to_numpy()
    mf0, tf0, nf = stat(pnl0f)
    mf7, tf7, _ = stat(pnl7f)
    print(f"{'FULL delta>=3':30} {nf:>5} {mf0:>11.3f} {tf0:>8.2f} {mf7:>12.3f} {tf7:>9.2f}")

    FA["pnl_fee0"] = pnl0f
    FA["pnl_fee07"] = pnl7f

    # Save enriched full records
    FA.to_parquet(OUT / "jump_asym_full_delta3_2026_06_02.parquet", index=False)
    SA.to_parquet(OUT / "jump_asym_down_asym_delta3_2026_06_02.parquet", index=False)
    return FA


# ============================================================
# PART B: Worst-case scalp risk on TIME+90s (delta>=5, n=430)
# ============================================================

def part_b():
    print("\n" + "=" * 80)
    print("PART B: TIME+90s scalp worst-case risk (BTC+ETH delta>=5, n=430)")
    print("        Using scalp_exit_validation_2026_06_02.parquet")
    print("=" * 80)

    R = pd.read_parquet(SCALP_PARQUET)
    print(f"Loaded scalp parquet: n={len(R)}, time90 notna={R.time90.notna().sum()}")

    def pnl_time90_row(row, fee):
        ev = row.entry_vwap; sh = row.shares; ex = row.time90
        if pd.notna(ex):
            rt = (ex - ev) * sh
            if fee:
                rt -= (fee_share(ev) + fee_share(ex)) * sh
            return rt
        else:
            # fallback: hold (2% on profit only = legacy)
            if row.won:
                return (1 - ev) * sh * 0.98
            else:
                return -ev * sh

    pnl0 = R.apply(lambda r: pnl_time90_row(r, False), axis=1).to_numpy()
    pnl7 = R.apply(lambda r: pnl_time90_row(r, True), axis=1).to_numpy()

    print(f"\n{'Metric':<35} {'FEE0':>12} {'FEE07':>12}")
    print("-" * 60)
    m0, t0, n = stat(pnl0); m7, t7, _ = stat(pnl7)
    print(f"{'mean $/tr':<35} {m0:>12.3f} {m7:>12.3f}")
    print(f"{'t-stat':<35} {t0:>12.2f} {t7:>12.2f}")
    print(f"{'n':<35} {n:>12} {n:>12}")

    # percentiles
    for pct in [1, 5, 10, 25, 50, 75, 90, 95, 99]:
        v0 = np.percentile(pnl0, pct); v7 = np.percentile(pnl7, pct)
        print(f"{'P'+str(pct):<35} {v0:>12.3f} {v7:>12.3f}")

    # worst-5% (P5 and below)
    w5_fee0 = np.percentile(pnl0, 5)
    w5_fee07 = np.percentile(pnl7, 5)
    print(f"\nWorst-5% threshold (P5) FEE0 = {w5_fee0:.3f}, FEE07 = {w5_fee07:.3f}")
    tail0 = pnl0[pnl0 <= w5_fee0]; tail7 = pnl7[pnl7 <= w5_fee07]
    print(f"Mean of worst-5%      FEE0 = {tail0.mean():.3f} (n={len(tail0)}), "
          f"FEE07 = {tail7.mean():.3f} (n={len(tail7)})")

    # Max drawdown (assume random order = worst plausible sequential)
    # Sort by PnL ascending (pessimistic sequential order) -> cumsum drawdown
    sorted0 = np.sort(pnl0)
    sorted7 = np.sort(pnl7)
    cum0 = np.cumsum(sorted0); cum7 = np.cumsum(sorted7)
    mdd0 = float(cum0.min()); mdd7 = float(cum7.min())
    print(f"\nMax cumulative drawdown (all-losses-first order):")
    print(f"  FEE0:  {mdd0:.2f}")
    print(f"  FEE07: {mdd7:.2f}")

    # More realistic: actual time-ordered drawdown (sort by slug/fire_us if available)
    # R doesn't have fire_us but has slug; slug suffix = slot_start_s
    R["slot_s"] = R.slug.str.rsplit("-", n=1).str[-1].astype(np.int64)
    R_sort = R.sort_values("slot_s")
    pnl0s = R_sort.apply(lambda r: pnl_time90_row(r, False), axis=1).to_numpy()
    pnl7s = R_sort.apply(lambda r: pnl_time90_row(r, True), axis=1).to_numpy()
    cum0s = np.cumsum(pnl0s); cum7s = np.cumsum(pnl7s)
    running_max0 = np.maximum.accumulate(cum0s)
    running_max7 = np.maximum.accumulate(cum7s)
    dd0 = cum0s - running_max0; dd7 = cum7s - running_max7
    mdd0_real = float(dd0.min()); mdd7_real = float(dd7.min())
    print(f"\nMax drawdown (time-ordered):")
    print(f"  FEE0:  {mdd0_real:.2f}")
    print(f"  FEE07: {mdd7_real:.2f}")

    # What % of trades are losers under TIME+90s?
    lose0 = (pnl0 < 0).mean(); lose7 = (pnl7 < 0).mean()
    print(f"\n% trades PnL < 0: FEE0={100*lose0:.1f}%, FEE07={100*lose7:.1f}%")

    # Sanity: check that all PnL values are within ±$25
    max_abs = max(abs(pnl0).max(), abs(pnl7).max())
    print(f"\nSANITY: max |PnL| = {max_abs:.2f} (should be << $25 at $25 notional)")


if __name__ == "__main__":
    t_start = time.time()
    fa = part_a()
    part_b()
    print(f"\ntotal elapsed: {time.time()-t_start:.0f}s")
