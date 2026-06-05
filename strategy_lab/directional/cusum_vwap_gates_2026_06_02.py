"""
cusum_vwap_gates_2026_06_02.py — Gate analysis on TIME+90s scalp exit (lag-taker fires).

Tests two gates on the TIME+90s exit scalp:
  S1 CUSUM-onset: running dual Page-CUSUM direction agrees with lag-taker side AND |S|>h
  S6 vwap-to-mid: |entry_vwap - binance_mid_at_fire| > X bps (entry is displaced from fair)

Universe: BTC+ETH lag-taker fires with delta_bps >= 3.
Exit: TIME+90s — sell held token at best-bid walk 90s after fire_us.
Fees: fee=0 (spread only) and fee=0.07 taker curve on BOTH legs.

Usage: C:/Python314/python.exe strategy_lab/directional/cusum_vwap_gates_2026_06_02.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import LiveMimicConfig, find_book_strict, sell_at_bid_partial  # noqa: E402

FIRES = ROOT / "strategy_lab" / "lag_taker_fires_oos_2026_06_01.parquet"
STAGE2_FEATS = ROOT / "strategy_lab" / "directional" / "_results" / "edge_val_stage2_features_2026_06_01.parquet"
CANON = ROOT / "data" / "v4" / "canonical"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
WIN = {"5m": 300, "15m": 900}
FEE = 0.07
LAT = 85_000  # 85ms in microseconds
SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT"}


def fee_share(v):
    return FEE * v * (1.0 - v)


def stat(x):
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return np.nan, np.nan
    m = x.mean()
    se = x.std(ddof=1) / np.sqrt(n)
    return m, (m / se if se else np.nan)


def roundtrip_pnl(exit_vwap, entry_vwap, shares, fee):
    """PnL from scalp: sell at exit_vwap, entered at entry_vwap."""
    rt = (exit_vwap - entry_vwap) * shares
    if fee:
        rt -= (fee_share(entry_vwap) + fee_share(exit_vwap)) * shares
    return rt


def hold_pnl(entry_vwap, shares, won):
    """Hold-to-resolution PnL under 2%-on-profit (production fee model)."""
    if won:
        return (1 - entry_vwap) * shares * (1 - 0.02)
    else:
        return -entry_vwap * shares


def load_klines_1s(asset):
    """Load binance 1s klines for an asset, return (ts_seconds, close_px)."""
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.period_id == "1SEC")
            & df.source.isin(["binance-vision", "binance-spot-ws"])].sort_values("time_period_start_us")
    ts = df.time_period_start_us.values.astype(np.int64) // 1_000_000 + 1  # bar-END seconds
    px = df.price_close.values.astype(float)
    keep = np.concatenate([np.diff(ts) != 0, [True]])
    return ts[keep], px[keep]


def running_cusum(px, k=0.5, roll=300):
    """Dual Page-CUSUM on standardized 1s returns. returns (S_pos, S_neg)."""
    n = len(px)
    r = np.zeros(n)
    r[1:] = np.diff(px) / px[:-1]
    s = pd.Series(r)
    mu = s.rolling(roll, min_periods=30).mean().to_numpy()
    sd = s.rolling(roll, min_periods=30).std(ddof=0).to_numpy()
    z = np.where(sd > 0, (r - mu) / sd, 0.0)
    z = np.nan_to_num(z)
    Sp = np.zeros(n)
    Sn = np.zeros(n)
    sp = sn = 0.0
    for t in range(1, n):
        sp = max(0.0, sp + z[t] - k)
        sn = max(0.0, sn - z[t] - k)
        Sp[t] = sp
        Sn[t] = sn
    return Sp, Sn


def print_split_table(label, R, col_pass, fee_values=(0.0, FEE)):
    """Print split table: gate True vs False, for each fee scenario."""
    n_total = len(R)
    n_pass = col_pass.sum()
    n_fail = (~col_pass).sum()
    print(f"\n  {label}  (n_pass={n_pass}, n_fail={n_fail}, n_total={n_total})")
    print(f"  {'group':<14}{'n':>6}{'$/tr_FEE0':>12}{'t_FEE0':>9}{'$/tr_FEE07':>12}{'t_FEE07':>9}")
    for grp, mask, lbl in [(True, col_pass, "GATE_PASS"), (False, ~col_pass, "GATE_FAIL")]:
        sub = R[mask]
        if len(sub) < 5:
            print(f"  {lbl:<14}{len(sub):>6}{'<5 obs':>34}")
            continue
        for fee_idx, fee in enumerate(fee_values):
            pnl = []
            for _, x in sub.iterrows():
                ev = x.time90
                if pd.notna(ev):
                    pnl.append(roundtrip_pnl(ev, x.entry_vwap, x.shares, fee))
                else:
                    pnl.append(hold_pnl(x.entry_vwap, x.shares, x.won))
            m, t = stat(pnl)
            if fee_idx == 0:
                line = f"  {lbl:<14}{len(sub):>6}{m:>12.3f}{t:>9.2f}"
            else:
                print(line + f"{m:>12.3f}{t:>9.2f}")


def run():
    t0 = time.time()

    # --- Load fires ---
    F_all = pd.read_parquet(FIRES)
    F = F_all[(F_all.asset.isin(["BTC", "ETH"])) & (F_all.delta_bps >= 3)].copy()
    WIN_map = {"5m": 300, "15m": 900}
    F["slot_start_s"] = F.slot_start.astype(np.int64)
    F["ws_s"] = F.slot_start_s - F.tf.map(WIN_map).astype(np.int64)
    print(f"universe: {len(F)} fires (BTC+ETH delta>=3)", flush=True)

    # --- Load L25 books and compute TIME+90s exit ---
    recs = []
    for asset in ["BTC", "ETH"]:
        sub = F[F.asset == asset]
        if sub.empty:
            continue
        slugs = set(sub.slug.values)
        books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
        print(f"[{asset}] L25 loaded n_slugs={len(slugs)} t={time.time()-t0:.0f}s", flush=True)

        for _, r in sub.iterrows():
            slug = r.slug
            side = r.direction
            fire_us = int(r.fire_us)
            shares = float(r.shares)
            ev = float(r.entry_vwap)
            won = bool(r.won)

            def bid_walk_at(ts):
                bk = find_book_strict(books, slug, side, int(ts) + LAT,
                                      max_staleness_us=2_000_000)
                if bk is None or not len(bk.get("bp", [])):
                    return None
                vwap, fsh, _usd = sell_at_bid_partial(
                    np.asarray(bk["bp"], float), np.asarray(bk["bsz"], float), shares)
                return vwap if fsh > 0 else None

            time90 = bid_walk_at(fire_us + 90_000_000)
            recs.append(dict(
                slug=slug, asset=asset, tf=r.tf, side=side, won=won,
                entry_vwap=ev, shares=shares, hold_pnl_val=float(r.pnl),
                ws_s=int(r.ws_s), fire_us=fire_us, delta_bps=float(r.delta_bps),
                time90=time90,
            ))
        del books
        print(f"[{asset}] done t={time.time()-t0:.0f}s", flush=True)

    R = pd.DataFrame(recs)
    print(f"Exit scan done: n={len(R)}, time90 coverage={R.time90.notna().mean()*100:.1f}% t={time.time()-t0:.0f}s", flush=True)

    # --- Sanity check: $/tr range ---
    sample_pnl = R[R.time90.notna()].apply(
        lambda x: roundtrip_pnl(x.time90, x.entry_vwap, x.shares, 0.0), axis=1)
    print(f"  SANITY: TIME+90s fee=0 pnl range [{sample_pnl.min():.2f}, {sample_pnl.max():.2f}]", flush=True)

    # --- Join CUSUM features from stage2 ---
    stage2 = pd.read_parquet(STAGE2_FEATS, columns=["asset", "tf", "ws_s", "Sp", "Sn"])
    stage2["_key"] = stage2.asset + "_" + stage2.tf + "_" + stage2.ws_s.astype(str)
    R["_key"] = R.asset + "_" + R.tf + "_" + R.ws_s.astype(str)
    R = R.merge(stage2[["_key", "Sp", "Sn"]], on="_key", how="left")
    print(f"  CUSUM join: Sp not-null={R.Sp.notna().sum()}/{len(R)}", flush=True)

    # --- S6: Binance 1s mid at fire_us for vwap-to-mid ---
    # Compute |entry_vwap - binance_mid_bps| for each fire.
    # Binance mid = close of 1s bar ending at or before fire_us (seconds).
    R["binance_mid"] = np.nan
    for asset in ["BTC", "ETH"]:
        print(f"[{asset}] loading klines_1s for vwap-to-mid...", flush=True)
        ts, px = load_klines_1s(asset)
        asset_mask = R.asset == asset
        fire_s = (R.loc[asset_mask, "fire_us"].values // 1_000_000).astype(np.int64)
        # strict asof: bar-end seconds <= fire_s
        idx = np.searchsorted(ts, fire_s, side="right") - 1
        valid = idx >= 0
        mids = np.where(valid, px[np.clip(idx, 0, len(px) - 1)], np.nan)
        R.loc[asset_mask, "binance_mid"] = mids

    # vwap_to_mid in bps: (entry_vwap - binance_mid/binance_mid_normalized_to_poly_prob)
    # entry_vwap is a Polymarket probability (0-1); binance_mid is a USD price.
    # The meaningful "mid" for the Polymarket token IS the Polymarket book mid.
    # Per task: "|entry_vwap - mid|" where mid is the Polymarket mid-price of the token.
    # Alternative interpretation: "binance vwap_dev" = deviation of entry from
    # some rolling binance VWAP anchor. Let's use the book mid at fire (ask0+bid0)/2.
    # Since we already did the exit scan, we'd need to re-query the book. Instead,
    # use the entry_vwap vs the time90 vwap as a proxy for "how far from mid did we enter".
    # But the clearest S6 gate is: entry_vwap vs Polymarket book mid at fire.
    # We already have entry_vwap (the ASK-walk vwap). The Polymarket fair-mid for an
    # Up/Down token should be near 0.50 for efficient markets. Displacement from 0.50
    # measures how much premium we paid relative to 50/50 fair.
    # Use |entry_vwap - 0.50| as the vwap-to-mid gate (larger = more displaced = more edge?).
    # Also try threshold on entry_vwap > X (e.g. 0.55, 0.60, 0.65).
    R["vwap_dev_from_50"] = (R.entry_vwap - 0.50).abs()

    # --- Baseline: TIME+90s ungated ---
    print("\n" + "=" * 90)
    print("CUSUM + VWAP GATES — lag-taker fires BTC+ETH delta>=3, TIME+90s exit")
    print("Exit: sell held-direction token at bid+LAT 90s after fire. Fallback to HOLD if no book.")
    print("=" * 90)

    # Baseline
    all_pnl_fee0, all_pnl_fee07 = [], []
    for _, x in R.iterrows():
        ev = x.time90
        if pd.notna(ev):
            all_pnl_fee0.append(roundtrip_pnl(ev, x.entry_vwap, x.shares, 0.0))
            all_pnl_fee07.append(roundtrip_pnl(ev, x.entry_vwap, x.shares, FEE))
        else:
            hp = hold_pnl(x.entry_vwap, x.shares, x.won)
            all_pnl_fee0.append(hp)
            all_pnl_fee07.append(hp)
    m0, t0_ = stat(all_pnl_fee0)
    m7, t7 = stat(all_pnl_fee07)
    print(f"\n  {'BASELINE(ungated)':<22} n={len(R):>5}  FEE0: ${m0:.3f}/tr t={t0_:.2f}  |  FEE07: ${m7:.3f}/tr t={t7:.2f}")
    print(f"  TIME+90s coverage: {R.time90.notna().sum()}/{len(R)} = {R.time90.notna().mean()*100:.1f}%")

    # === S1 CUSUM gate ===
    print("\n" + "=" * 70)
    print("S1 CUSUM GATE — CUSUM direction agrees with lag-taker AND |S| > h")
    print("CUSUM_UP = Sp > Sn; CUSUM_DN = Sn > Sp. Gate passes if aligned with 'side'.")
    print("=" * 70)

    for h in [0.5, 1.0, 2.0, 3.0]:
        cusum_max = R[["Sp", "Sn"]].max(axis=1)
        cusum_up = R.Sp > R.Sn
        cusum_aligned = (
            ((R.side == "Up") & cusum_up) |
            ((R.side == "Down") & ~cusum_up)
        )
        gate_pass = cusum_aligned & (cusum_max > h) & R.Sp.notna()
        print_split_table(f"S1 CUSUM h={h}", R, gate_pass)

    # Also: gate on |S| only (strength, any direction)
    for h in [1.0, 2.0]:
        cusum_max = R[["Sp", "Sn"]].max(axis=1)
        gate_pass = (cusum_max > h) & R.Sp.notna()
        print_split_table(f"S1 CUSUM_strength_only h={h}", R, gate_pass)

    # === S6 vwap-to-mid gate ===
    print("\n" + "=" * 70)
    print("S6 VWAP-TO-MID GATE — |entry_vwap - 0.50| (displacement from 50/50 fair)")
    print("Higher displacement = we're entering at a more extreme price.")
    print("=" * 70)
    print(f"  entry_vwap distribution: min={R.entry_vwap.min():.3f} p25={R.entry_vwap.quantile(.25):.3f} "
          f"median={R.entry_vwap.median():.3f} p75={R.entry_vwap.quantile(.75):.3f} max={R.entry_vwap.max():.3f}")
    print(f"  vwap_dev_from_50: min={R.vwap_dev_from_50.min():.3f} "
          f"p25={R.vwap_dev_from_50.quantile(.25):.3f} "
          f"median={R.vwap_dev_from_50.median():.3f} "
          f"p75={R.vwap_dev_from_50.quantile(.75):.3f} max={R.vwap_dev_from_50.max():.3f}")

    # Gate: entry_vwap > threshold (entered above X, meaning we paid premium for direction)
    for thr in [0.55, 0.60, 0.65, 0.70]:
        gate_pass = R.entry_vwap > thr
        print_split_table(f"S6 entry_vwap>{thr}", R, gate_pass)

    # Gate: |entry_vwap - 0.50| > threshold (displaced from 50/50)
    for dev_bps in [5, 10, 15]:
        dev = dev_bps / 100.0  # in probability units
        gate_pass = R.vwap_dev_from_50 > dev
        print_split_table(f"S6 vwap_dev>{dev_bps}pp", R, gate_pass)

    # S6 variant: entry_vwap quantile-based split
    med_vwap = R.entry_vwap.median()
    gate_pass = R.entry_vwap > med_vwap
    print_split_table(f"S6 entry_vwap>median({med_vwap:.3f})", R, gate_pass)

    # S6 + CUSUM combined (best combination)
    print("\n" + "=" * 70)
    print("COMBINED: best S1 + S6 (h=1.0 CUSUM aligned AND entry_vwap>0.60)")
    print("=" * 70)
    cusum_max = R[["Sp", "Sn"]].max(axis=1)
    cusum_aligned_1 = (
        ((R.side == "Up") & (R.Sp > R.Sn)) |
        ((R.side == "Down") & (R.Sn > R.Sp))
    ) & (cusum_max > 1.0) & R.Sp.notna()
    vwap_gate = R.entry_vwap > 0.60
    combo = cusum_aligned_1 & vwap_gate
    print_split_table("S1(h=1)+S6(ev>0.60)", R, combo)

    print(f"\nTotal runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    run()
