"""Momo + Coinbase overlay — Phase 16 §B real test.

Question: does adding coinbase-derived features to the production-canonical momo
gate (which is already profitable at +$8500/836 trades baseline) provide LIFT?

Strategy:
  Baseline (B0) = the canonical momo simulator (momo_ws_three_policies_sweep.py):
    - Universe: btc/eth/sol updown 5m/15m
    - Gate: |bin_ret_2m| ≥ rolling 14d q90, sign(bin_ret_2m) = direction
    - Entry: L25 ASK walk at fire_offset=60s, $25 notional, spread filter per asset
    - Policies: HOLD / HEDGE_HOLD / SELL_BID_V1 / SELL_BID_V2

  Coinbase variants (8) — each modifies the gate or signal:
    F1: gate + filter sign(premium_ws) == sign(signal)
    F2: gate + filter |premium_ws| > 5bp
    F3: gate + filter |z(premium, 7d)| > 1.5
    F4: gate + filter (premium@ws+60 - premium@ws-60) × signal > 0
    F5: gate + filter sign(bin_ret_2m) == sign(coin_ret_2m)
    E1: gate input replaced with 0.5*bin_ret + 0.5*coin_ret (ensemble)
    E2: gate input replaced with coin_ret_2m only (negative control)
    E3: gate by |premium_ws| instead of |ret_2m|, direction = sign(premium)

SELL v1 vs v2:
  SELL_BID_V1 — rev_bp anchor = close@ws (production v1 convention)
  SELL_BID_V2 — rev_bp anchor = close@fire (close at entry time; tighter "stop")

Universe restriction: ≤ 2026-05-06 (05_06 cache covers this exactly).
fire_offset locked at 60s (matches recent production semantics).

Outputs:
  strategy_lab/results/cex_alignment/coinbase_overlay_per_trade.csv
  strategy_lab/results/cex_alignment/coinbase_overlay_aggregated.csv
  strategy_lab/results/cex_alignment/coinbase_overlay_lift.csv
  strategy_lab/reports/MOMO_COINBASE_OVERLAY_2026_05_09.md
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

from book_walk import book_walk_fill                    # noqa: E402
from momo_ws_three_policies_sweep import (              # noqa: E402
    load_klines as load_binance_okx_klines,
    asof_strict, load_universe, compute_ret_2m,
    compute_thresholds, find_book, sell_at_bid,
    NOTIONAL, FEE, SPREAD_FILTER, GATE_Q, LOOKBACK,
    REV_BP_THRESHOLD, TICK_S, LEVELS,
)
import pyarrow.parquet as pq

CACHE = ROOT / "data" / "v4" / "refresh_2026_05_06" / "cache"


def load_books_for_slugs_streaming(asset: str, slugs: set) -> dict:
    """Memory-safe loader: filter via pyarrow Table.filter, then convert chunks.

    Strategy: chunk slugs into ~100-slug groups, read each group as a single
    filtered pyarrow Table, materialize numpy ladders directly.
    """
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.dataset as ds
    import gc

    parquet_path = CACHE / f"{asset.lower()}_orderbook_L25.parquet"
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_as = [f"ask_size_{i}"  for i in range(LEVELS)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS)]
    cols_bs = [f"bid_size_{i}"  for i in range(LEVELS)]
    cols_keep = ["timestamp_us", "slug", "outcome"] + cols_ap + cols_as + cols_bp + cols_bs

    dataset = ds.dataset(str(parquet_path), format="parquet")
    slug_list = sorted(slugs)
    out: dict = {}
    # Process slugs in chunks of 20 — BTC has microsecond-granularity quotes,
    # ~5500 rows per slug × 100 cols × 4 bytes ≈ 2.2 MB per slug, so 20 ≈ 44 MB.
    CHUNK = 20
    for ci in range(0, len(slug_list), CHUNK):
        chunk_slugs = slug_list[ci:ci + CHUNK]
        tbl = dataset.to_table(
            columns=cols_keep,
            filter=pc.field("slug").isin(pa.array(chunk_slugs)),
        )
        n = tbl.num_rows
        if n == 0:
            continue
        ts = tbl.column("timestamp_us").to_numpy(zero_copy_only=False).astype("int64")
        slug_arr = tbl.column("slug").to_pylist()
        outc_arr = tbl.column("outcome").to_pylist()
        # Build 2D ladders
        ap_2d = np.empty((n, LEVELS), dtype=np.float32)
        as_2d = np.empty((n, LEVELS), dtype=np.float32)
        bp_2d = np.empty((n, LEVELS), dtype=np.float32)
        bs_2d = np.empty((n, LEVELS), dtype=np.float32)
        for j in range(LEVELS):
            ap_2d[:, j] = tbl.column(cols_ap[j]).to_numpy(zero_copy_only=False)
            as_2d[:, j] = tbl.column(cols_as[j]).to_numpy(zero_copy_only=False)
            bp_2d[:, j] = tbl.column(cols_bp[j]).to_numpy(zero_copy_only=False)
            bs_2d[:, j] = tbl.column(cols_bs[j]).to_numpy(zero_copy_only=False)
        del tbl
        # Group rows by (slug, outcome)
        groups: dict[tuple[str, str], list[int]] = {}
        for i in range(n):
            key = (slug_arr[i], outc_arr[i])
            groups.setdefault(key, []).append(i)
        for key, idxs in groups.items():
            idx_arr = np.asarray(idxs, dtype="int64")
            ts_g = ts[idx_arr]
            order = np.argsort(ts_g, kind="mergesort")
            ts_sorted = ts_g[order]
            # Subsample to 1Hz: keep first snapshot per second. find_book uses
            # max_dt_us=10_000_000 so 1Hz is sufficient resolution.
            sec = ts_sorted // 1_000_000
            _, uniq_idx = np.unique(sec, return_index=True)
            uniq_idx = np.sort(uniq_idx)
            sub_idx = idx_arr[order][uniq_idx]
            out[key] = (
                ts_sorted[uniq_idx].copy(),
                ap_2d[sub_idx].astype(np.float64, copy=True),
                as_2d[sub_idx].astype(np.float64, copy=True),
                bp_2d[sub_idx].astype(np.float64, copy=True),
                bs_2d[sub_idx].astype(np.float64, copy=True),
            )
        del ts, slug_arr, outc_arr, ap_2d, as_2d, bp_2d, bs_2d, groups
        gc.collect()
    return out


load_books_for_slugs = load_books_for_slugs_streaming

REFRESH_OLD = ROOT / "data" / "v4" / "refresh_2026_05_06"   # baseline klines + L25 cache
REFRESH_NEW = ROOT / "data" / "v4" / "refresh_2026_05_09"   # coinbase klines

OUT = ROOT / "strategy_lab" / "results" / "cex_alignment"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = ROOT / "strategy_lab" / "reports" / "MOMO_COINBASE_OVERLAY_2026_05_09.md"

ASSET_COIN = {"BTC": "COINBASE_SPOT_BTC_USD",
              "ETH": "COINBASE_SPOT_ETH_USD",
              "SOL": "COINBASE_SPOT_SOL_USD"}

FIRE_OFFSET_S = 60          # locked
PREMIUM_5BP = 0.0005        # 5 basis points
Z_THRESHOLD = 1.5
Z_WINDOW_DAYS = 7

POLICIES = ["HOLD", "HEDGE_HOLD", "SELL_BID_V1", "SELL_BID_V2"]
VARIANTS = ["B0", "F1", "F2", "F3", "F4", "F5", "E1", "E2", "E3"]


# ---------------------------------------------------------------------------
# Coinbase loader
# ---------------------------------------------------------------------------

def load_coinbase_klines() -> dict[str, pd.DataFrame]:
    """1MIN coinbase closes per asset, from refresh_2026_05_09 cex_klines_vps2.csv."""
    df = pd.read_csv(REFRESH_NEW / "cex_klines_vps2.csv",
                     usecols=["symbol_id", "period_id", "source",
                              "time_period_start_us", "price_close"])
    df = df[(df.period_id == "1MIN") & (df.source == "coinbase-spot-ws")].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for a in ("BTC", "ETH", "SOL"):
        sub = df[df.symbol_id == ASSET_COIN[a]].sort_values("ts_s").reset_index(drop=True)
        out[a] = sub[["ts_s", "price_close"]].copy()
        print(f"    coinbase/{a}: {len(out[a])} 1m bars  "
              f"({pd.to_datetime(out[a].ts_s.min(), unit='s', utc=True)} -> "
              f"{pd.to_datetime(out[a].ts_s.max(), unit='s', utc=True)})")
    return out


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def attach_coinbase_features(uni: pd.DataFrame,
                             bin_klines: dict, coin_klines: dict
                             ) -> pd.DataFrame:
    """Adds coin_ret_2m, premium_ws, premium_d2m, premium_z_7d to universe."""
    n = len(uni)
    coin_ret = np.full(n, np.nan)
    premium_ws = np.full(n, np.nan)
    premium_d2m = np.full(n, np.nan)
    bin_close_at_ws = np.full(n, np.nan)
    coin_close_at_ws = np.full(n, np.nan)

    for i, (asset, ws) in enumerate(zip(uni.asset.values, uni.ws.values)):
        ws = int(ws)
        b_pre = asof_strict(bin_klines[asset], ws - 60)
        b_post = asof_strict(bin_klines[asset], ws + 60)
        b_at = asof_strict(bin_klines[asset], ws)
        c_pre = asof_strict(coin_klines[asset], ws - 60)
        c_post = asof_strict(coin_klines[asset], ws + 60)
        c_at = asof_strict(coin_klines[asset], ws)
        if math.isfinite(c_pre) and math.isfinite(c_post) and c_pre > 0 and c_post > 0:
            coin_ret[i] = math.log(c_post / c_pre)
        if math.isfinite(b_at) and math.isfinite(c_at) and b_at > 0 and c_at > 0:
            premium_ws[i] = math.log(c_at / b_at)
            bin_close_at_ws[i] = b_at
            coin_close_at_ws[i] = c_at
        # premium velocity (ws-60 vs ws+60)
        if (math.isfinite(b_pre) and math.isfinite(c_pre) and b_pre > 0 and c_pre > 0
                and math.isfinite(b_post) and math.isfinite(c_post) and b_post > 0 and c_post > 0):
            p_pre = math.log(c_pre / b_pre)
            p_post = math.log(c_post / b_post)
            premium_d2m[i] = p_post - p_pre

    uni = uni.copy()
    uni["coin_ret_2m"] = coin_ret
    uni["premium_ws"] = premium_ws
    uni["premium_d2m"] = premium_d2m
    uni["bin_close_at_ws"] = bin_close_at_ws
    uni["coin_close_at_ws"] = coin_close_at_ws
    return uni


def attach_premium_zscore(uni: pd.DataFrame, window_days: int = Z_WINDOW_DAYS) -> pd.DataFrame:
    """Trailing z-score of premium per asset using a rolling N-day window."""
    uni = uni.sort_values("ws").reset_index(drop=True).copy()
    uni["premium_z_7d"] = np.nan
    win_s = window_days * 86400
    for asset, sub in uni.groupby("asset"):
        idx = sub.index.values
        ws = sub.ws.values.astype("int64")
        prem = sub.premium_ws.values
        z = np.full(len(sub), np.nan)
        for i in range(len(sub)):
            ws_i = ws[i]
            mask = (ws < ws_i) & (ws >= ws_i - win_s) & np.isfinite(prem)
            prior = prem[mask]
            if len(prior) >= 100:
                mu = float(prior.mean()); sd = float(prior.std())
                if sd > 0:
                    z[i] = (prem[i] - mu) / sd
        uni.loc[idx, "premium_z_7d"] = z
    return uni


# ---------------------------------------------------------------------------
# Variant gating
# ---------------------------------------------------------------------------

def apply_gate(uni: pd.DataFrame, variant: str, thresholds: dict) -> pd.DataFrame:
    """Return gated subset (rows that fire) for this variant.
    All variants reuse the same per-day q90 thresholds dict (computed on
    bin |ret_2m| for B0/F* and on the variant's own gate input for E*)."""
    df = uni.copy()
    if variant == "B0":
        thr = df.apply(lambda r: thresholds["bin"].get((r.asset, r.tf, str(r.day.date())),
                                                          float("nan")), axis=1)
        gate = df.bin_ret_2m.abs() >= thr
        gated = df[gate].copy()
        gated["signal"] = gated.bin_ret_2m.apply(lambda x: "UP" if x > 0 else "DOWN")
        return gated

    if variant in ("F1", "F2", "F3", "F4", "F5"):
        thr = df.apply(lambda r: thresholds["bin"].get((r.asset, r.tf, str(r.day.date())),
                                                          float("nan")), axis=1)
        gate = df.bin_ret_2m.abs() >= thr
        gated = df[gate].copy()
        gated["signal"] = gated.bin_ret_2m.apply(lambda x: "UP" if x > 0 else "DOWN")
        sig_int = gated.signal.map({"UP": 1, "DOWN": -1})
        if variant == "F1":   # premium aligned with signal
            keep = (np.sign(gated.premium_ws) == sig_int) & gated.premium_ws.notna()
        elif variant == "F2": # premium magnitude
            keep = gated.premium_ws.abs() > PREMIUM_5BP
        elif variant == "F3": # premium z-score
            keep = gated.premium_z_7d.abs() > Z_THRESHOLD
        elif variant == "F4": # premium velocity in signal direction
            keep = (gated.premium_d2m * sig_int) > 0
        elif variant == "F5": # cross-venue agreement
            keep = (np.sign(gated.bin_ret_2m) == np.sign(gated.coin_ret_2m)) & gated.coin_ret_2m.notna()
        return gated[keep.fillna(False)].copy()

    if variant == "E1":  # ensemble ret_2m
        df["ens_ret_2m"] = 0.5 * df.bin_ret_2m + 0.5 * df.coin_ret_2m
        df_e = df.copy(); df_e["abs_ret_2m"] = df_e.ens_ret_2m.abs()
        thr_ens = compute_thresholds(df_e)
        thr = df.apply(lambda r: thr_ens.get((r.asset, r.tf, str(r.day.date())), float("nan")), axis=1)
        gate = df.ens_ret_2m.abs() >= thr
        gated = df[gate & df.ens_ret_2m.notna()].copy()
        gated["signal"] = gated.ens_ret_2m.apply(lambda x: "UP" if x > 0 else "DOWN")
        return gated

    if variant == "E2":  # coinbase-only ret_2m
        df_e = df.copy(); df_e["abs_ret_2m"] = df_e.coin_ret_2m.abs()
        thr_coin = compute_thresholds(df_e)
        thr = df.apply(lambda r: thr_coin.get((r.asset, r.tf, str(r.day.date())), float("nan")), axis=1)
        gate = df.coin_ret_2m.abs() >= thr
        gated = df[gate & df.coin_ret_2m.notna()].copy()
        gated["signal"] = gated.coin_ret_2m.apply(lambda x: "UP" if x > 0 else "DOWN")
        return gated

    if variant == "E3":  # premium AS signal
        df_e = df.copy(); df_e["abs_ret_2m"] = df_e.premium_ws.abs()
        thr_prem = compute_thresholds(df_e)
        thr = df.apply(lambda r: thr_prem.get((r.asset, r.tf, str(r.day.date())), float("nan")), axis=1)
        gate = df.premium_ws.abs() >= thr
        gated = df[gate & df.premium_ws.notna()].copy()
        gated["signal"] = gated.premium_ws.apply(lambda x: "UP" if x > 0 else "DOWN")
        return gated

    raise ValueError(f"unknown variant {variant!r}")


# ---------------------------------------------------------------------------
# Simulator with policy v1/v2 split
# ---------------------------------------------------------------------------

def simulate_one(row, bin_klines, books_idx, policy: str, fire_offset_s: int = FIRE_OFFSET_S):
    """One trade simulation. Reuses simulate_trade structure but supports SELL v1 vs v2."""
    fire_us = int(row.ws + fire_offset_s) * 1_000_000
    held = "Up" if row.signal == "UP" else "Down"
    other = "Down" if row.signal == "UP" else "Up"
    asset_idx = books_idx[row.asset]

    # ENTRY
    b = find_book(asset_idx, row.slug, held, fire_us)
    if b is None:
        return None
    ap, as_, bp, bs, dt_entry = b
    ask0 = ap[0] if math.isfinite(ap[0]) else float("nan")
    bid0 = bp[0] if math.isfinite(bp[0]) else float("nan")
    if math.isfinite(ask0) and math.isfinite(bid0) and (ask0 - bid0) > SPREAD_FILTER[row.asset]:
        return None
    vwap_e, shares_e, usd_e, _, under = book_walk_fill(ap, as_, NOTIONAL)
    if shares_e <= 0 or (under and usd_e < NOTIONAL * 0.5):
        return None

    won = (row.signal == "UP" and row.outcome == "Up") or \
          (row.signal == "DOWN" and row.outcome == "Down")

    def _hold_pnl():
        if won:
            profit = shares_e * 1.0 - usd_e
            fee = profit * FEE if profit > 0 else 0.0
            return profit - fee
        return -usd_e

    if policy == "HOLD":
        return dict(slug=row.slug, asset=row.asset, tf=row.tf, ws=int(row.ws), policy=policy,
                    signal=row.signal, outcome=row.outcome, won=int(won), exit_reason="hold",
                    vwap_e=vwap_e, shares=shares_e, usd_spent=usd_e, exit_at_t=None, pnl=_hold_pnl())

    # Anchor for rev_bp
    if policy in ("HEDGE_HOLD", "SELL_BID_V1"):
        anchor = asof_strict(bin_klines[row.asset], int(row.ws))      # close@ws
        anchor_kind = "ws"
    elif policy == "SELL_BID_V2":
        anchor = asof_strict(bin_klines[row.asset], int(row.ws + fire_offset_s))  # close@fire
        anchor_kind = "fire"
    else:
        raise ValueError(f"unknown policy {policy!r}")
    if not math.isfinite(anchor) or anchor <= 0:
        return dict(slug=row.slug, asset=row.asset, tf=row.tf, ws=int(row.ws), policy=policy,
                    signal=row.signal, outcome=row.outcome, won=int(won), exit_reason="hold_no_anchor",
                    vwap_e=vwap_e, shares=shares_e, usd_spent=usd_e, exit_at_t=None, pnl=_hold_pnl())

    resolve_us = int(row.ws + row.window_s - 60) * 1_000_000
    exit_event = None
    t_us = fire_us + TICK_S * 1_000_000
    while t_us <= resolve_us:
        a_now = asof_strict(bin_klines[row.asset], t_us // 1_000_000)
        if not math.isfinite(a_now):
            t_us += TICK_S * 1_000_000; continue
        rev_bp = (a_now - anchor) / anchor * 1e4
        triggered = (row.signal == "UP" and rev_bp <= -REV_BP_THRESHOLD) or \
                    (row.signal == "DOWN" and rev_bp >= REV_BP_THRESHOLD)
        if triggered:
            if policy == "HEDGE_HOLD":
                opp = find_book(asset_idx, row.slug, other, t_us)
                if opp is not None:
                    h_ap, h_as, _, _, _ = opp
                    h_top = h_ap[0] if math.isfinite(h_ap[0]) else float("nan")
                    if math.isfinite(h_top) and 0 < h_top < 1:
                        target_h_usd = shares_e * float(h_top)
                        vwap_h, shares_h, usd_h, _, _ = book_walk_fill(h_ap, h_as, target_h_usd)
                        if shares_h > 0:
                            exit_event = ("hedge", t_us, vwap_h, shares_h, usd_h)
                            break
            else:  # SELL_BID_V1 / V2 — both use BID-walk; anchor differs
                own = find_book(asset_idx, row.slug, held, t_us)
                if own is not None:
                    _, _, sb_p, sb_s, _ = own
                    vwap_s, shares_s, gross_s = sell_at_bid(sb_p, sb_s, shares_e)
                    if shares_s > 0:
                        exit_event = ("sell", t_us, vwap_s, shares_s, gross_s)
                        break
        t_us += TICK_S * 1_000_000

    if exit_event is None:
        return dict(slug=row.slug, asset=row.asset, tf=row.tf, ws=int(row.ws), policy=policy,
                    signal=row.signal, outcome=row.outcome, won=int(won), exit_reason="hold",
                    vwap_e=vwap_e, shares=shares_e, usd_spent=usd_e, exit_at_t=None, pnl=_hold_pnl())

    kind, t_exit, vwap_x, shares_x, val_x = exit_event
    if kind == "hedge":
        cost_total = usd_e + val_x
        gross = shares_e * 1.0 if won else shares_x * 1.0
        profit = gross - cost_total
        fee = profit * FEE if profit > 0 else 0.0
        pnl = profit - fee
    else:  # sell
        profit = val_x - usd_e
        fee = profit * FEE if profit > 0 else 0.0
        pnl = profit - fee
    return dict(slug=row.slug, asset=row.asset, tf=row.tf, ws=int(row.ws), policy=policy,
                signal=row.signal, outcome=row.outcome, won=int(won), exit_reason=kind,
                vwap_e=vwap_e, shares=shares_e, usd_spent=usd_e,
                exit_at_t=int(t_exit), exit_vwap=vwap_x, pnl=pnl)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Momo + Coinbase Overlay (Phase 16 §B) ===\n")
    print("[1] Loading binance/okx klines from refresh_2026_05_06...")
    bin_klines = load_binance_okx_klines()
    print(f"    bin_klines: {len(bin_klines)} assets")

    print("[2] Loading coinbase klines from refresh_2026_05_09...")
    coin_klines = load_coinbase_klines()

    print("[3] Loading universe from refresh_2026_05_06 (≤ 2026-05-06 cutoff)...")
    uni = load_universe()
    uni["ret_2m"] = compute_ret_2m(uni, bin_klines)
    uni["abs_ret_2m"] = uni.ret_2m.abs()
    uni = uni.rename(columns={"ret_2m": "bin_ret_2m"})
    uni["abs_bin_ret_2m"] = uni.bin_ret_2m.abs()
    print(f"    universe: {len(uni)} markets, finite bin_ret_2m={uni.bin_ret_2m.notna().sum()}")

    print("[4] Attaching coinbase features (ret_2m, premium_ws, premium_d2m, z_7d)...")
    uni = attach_coinbase_features(uni, bin_klines, coin_klines)
    print(f"    coin_ret_2m  finite: {uni.coin_ret_2m.notna().sum()}")
    print(f"    premium_ws   finite: {uni.premium_ws.notna().sum()}")
    print(f"    premium_d2m  finite: {uni.premium_d2m.notna().sum()}")
    uni = attach_premium_zscore(uni)
    print(f"    premium_z_7d finite: {uni.premium_z_7d.notna().sum()}")

    print("[5] Computing thresholds (rolling 14d q90 |bin_ret_2m|)...")
    uni["day"] = pd.to_datetime(uni.ws, unit="s").dt.floor("D")
    uni["abs_ret_2m"] = uni.abs_bin_ret_2m  # alias for compute_thresholds
    thr_bin = compute_thresholds(uni)
    thresholds = {"bin": thr_bin}

    print("[6] Running variants × policies...")
    # gating universe for each variant
    gated_per_variant = {}
    for v in VARIANTS:
        g = apply_gate(uni, v, thresholds)
        gated_per_variant[v] = g
        print(f"    {v}: gated={len(g)} (signal_up={int((g.signal=='UP').sum())}, "
              f"signal_down={int((g.signal=='DOWN').sum())})")

    # union of slugs across all variants → load books once
    print("[7] Loading L25 books for union of all gated slugs...")
    books_idx = {}
    for a in ("BTC", "ETH", "SOL"):
        slugs = set()
        for v in VARIANTS:
            slugs.update(gated_per_variant[v][gated_per_variant[v].asset == a].slug.unique())
        print(f"    {a}: {len(slugs)} unique slugs to stream...")
        books_idx[a] = load_books_for_slugs(a, slugs)
        n_keys = len(books_idx[a])
        n_total = sum(len(rec[0]) for rec in books_idx[a].values())
        print(f"      {n_keys} (slug,outcome) keys, {n_total:,} snapshots")

    print("[8] Simulating each variant × policy...")
    rows = []
    for v in VARIANTS:
        gated = gated_per_variant[v]
        for policy in POLICIES:
            n_sim = 0
            for r in gated.itertuples(index=False):
                res = simulate_one(r, bin_klines, books_idx, policy)
                if res is not None:
                    res["variant"] = v
                    rows.append(res); n_sim += 1
            print(f"    {v:<3} × {policy:<13} fires={n_sim}")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "coinbase_overlay_per_trade.csv", index=False)

    print("[9] Aggregating + computing lift over baseline...")
    agg = df.groupby(["variant", "policy"]).agg(
        n=("pnl", "size"),
        wins=("won", "sum"),
        hit_rate=("won", "mean"),
        pnl_total=("pnl", "sum"),
        pnl_mean=("pnl", "mean"),
        pnl_std=("pnl", "std"),
        avg_vwap=("vwap_e", "mean"),
    ).reset_index()
    agg["sharpe"] = agg.pnl_mean / agg.pnl_std.replace(0, np.nan)
    agg.to_csv(OUT / "coinbase_overlay_aggregated.csv", index=False)

    # Lift table: each variant × policy vs B0 × policy
    base = agg[agg.variant == "B0"].set_index("policy")
    lift_rows = []
    for v in VARIANTS:
        if v == "B0":
            continue
        sub = agg[agg.variant == v]
        for _, r in sub.iterrows():
            policy = r.policy
            b = base.loc[policy] if policy in base.index else None
            if b is None or b.n == 0:
                continue
            lift_rows.append({
                "variant": v, "policy": policy,
                "n": r.n, "n_base": b.n,
                "n_pct_of_base": round(100 * r.n / max(b.n, 1), 1),
                "hit": r.hit_rate, "hit_base": b.hit_rate,
                "hit_lift_pp": round((r.hit_rate - b.hit_rate) * 100, 2),
                "pnl_total": r.pnl_total, "pnl_total_base": b.pnl_total,
                "pnl_total_lift": round(r.pnl_total - b.pnl_total, 2),
                "pnl_mean": r.pnl_mean, "pnl_mean_base": b.pnl_mean,
                "pnl_mean_lift": round(r.pnl_mean - b.pnl_mean, 4),
            })
    lift = pd.DataFrame(lift_rows)
    lift.to_csv(OUT / "coinbase_overlay_lift.csv", index=False)

    print("\n=== Per-cell summary ===")
    print(agg.to_string(index=False))

    print("\n[10] Writing report...")
    write_report(agg, lift, gated_per_variant)
    print(f"   wrote {REPORT}")


def write_report(agg: pd.DataFrame, lift: pd.DataFrame, gated_per_variant: dict):
    L = [
        "# Momo + Coinbase Overlay — does coinbase add alpha?",
        "_Generated: 2026-05-09_",
        "",
        "## Question",
        "Does adding coinbase-derived features to the production-canonical momo gate ",
        "(which already delivers +$8500/836 trades baseline) lift PnL or hit rate?",
        "",
        "## Setup",
        f"- Universe: refresh_2026_05_06 (≤ 2026-05-06 cutoff for apples-to-apples L25 cache coverage)",
        f"- Klines: binance/okx from refresh_2026_05_06, coinbase from refresh_2026_05_09",
        f"- Entry: $25 L25 ASK walk at fire_offset={FIRE_OFFSET_S}s",
        f"- Gate: rolling 14d q90 |gate_input| per (asset, tf, day)",
        f"- Policies: HOLD / HEDGE_HOLD / SELL_BID_V1 (anchor=close@ws) / SELL_BID_V2 (anchor=close@fire)",
        f"- REV_BP: {int(REV_BP_THRESHOLD)} | FEE: {int(FEE*100)}% on profit | TICK: {TICK_S}s",
        "",
        "## Variants",
        "- **B0** baseline: |bin_ret_2m| gate, sign(bin_ret_2m) direction",
        "- **F1** baseline + filter: sign(premium@ws) == sign(signal)",
        f"- **F2** baseline + filter: |premium@ws| > {PREMIUM_5BP*1e4:.0f} bp",
        f"- **F3** baseline + filter: |z(premium, {Z_WINDOW_DAYS}d)| > {Z_THRESHOLD}",
        "- **F4** baseline + filter: (premium@ws+60 - premium@ws-60) × signal > 0",
        "- **F5** baseline + filter: sign(bin_ret_2m) == sign(coin_ret_2m)",
        "- **E1** ensemble gate: 0.5×bin_ret_2m + 0.5×coin_ret_2m",
        "- **E2** coinbase-only gate: coin_ret_2m (negative control)",
        "- **E3** premium-as-signal: |premium@ws| gate, sign(premium) direction",
        "",
        "## Gating coverage",
        "",
        "| Variant | n_gated |",
        "|---|---:|",
    ]
    for v in VARIANTS:
        L.append(f"| {v} | {len(gated_per_variant[v])} |")

    L += ["", "## Headline (variant × policy)", "",
          agg.to_markdown(index=False, floatfmt=".4f"),
          "", "## Lift over B0 (baseline)", ""]
    if not lift.empty:
        L.append(lift.to_markdown(index=False, floatfmt=".4f"))
    L += ["", "## Verdict (auto-generated)", ""]
    if not lift.empty:
        # Per policy: which variant has highest pnl_total_lift?
        for policy, sub in lift.groupby("policy"):
            top = sub.sort_values("pnl_total_lift", ascending=False).iloc[0]
            sign = "+" if top.pnl_total_lift >= 0 else ""
            L.append(f"- **{policy}**: top variant `{top.variant}` "
                     f"(Δpnl={sign}${top.pnl_total_lift:+.2f}, n={int(top.n)} vs base {int(top.n_base)}, "
                     f"hit Δ{top.hit_lift_pp:+.2f}pp)")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
