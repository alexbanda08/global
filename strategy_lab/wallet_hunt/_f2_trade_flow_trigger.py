"""F2 trigger discovery using the Polymarket trade tape (24M trades).

The earlier trigger-finder used L25 snapshots (1Hz) + binance momentum.
That missed sub-second event signals.

This script uses the full Polymarket trades parquet to identify what
trades occurred IMMEDIATELY before each F2 fire — looking for the
trade-flow pattern that triggers F2.

For each F2 fire:
  - Slice all trades on the SAME slug in the 30s preceding the fire
  - Compute pre-fire flow features:
      * net_aggressor_$  (buy - sell volume in window)
      * n_trades         (count in window)
      * last_trade_size  (size of the most recent trade)
      * last_trade_side  (Up vs Down side of the most recent trade)
      * mean_price_drift (price change over the window)
      * imbalance_$_5s   (net flow in last 5s)
  - Compare to control moments (non-fire) on same slugs
  - Identify discriminating features
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_trades  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache"

F2_WALLETS = ("0xa0a50783", "0x9dae874a")
WINDOWS = (5, 10, 30)   # seconds before fire to compute flow


def main():
    # 1. Load F2 fires
    print("Loading F2 fires_decoded ...")
    f_dfs = []
    for w in F2_WALLETS:
        p = CACHE / w / "fires_decoded.parquet"
        df = pd.read_parquet(p)
        df["wallet"] = w
        f_dfs.append(df[df.wallet_side == "BUY"])
    f2 = pd.concat(f_dfs, ignore_index=True)
    f2 = f2[f2.slug.str.startswith("btc-updown-")].copy()
    f2 = f2.sort_values("ts_us").reset_index(drop=True)
    print(f"  F2 BUY fires (BTC): {len(f2)}")
    print(f"  unique slugs: {f2.slug.nunique()}")

    # 2. Load Polymarket trade tape (BTC)
    print("Loading Polymarket BTC trade tape (24M trades) ...")
    tr = load_trades("btc")
    # Filter to slugs F2 fired on
    f2_slugs = set(f2.slug.unique())
    tr = tr[tr.slug.isin(f2_slugs)].copy()
    tr = tr.sort_values("timestamp_us").reset_index(drop=True)
    print(f"  trades on F2 slugs: {len(tr):,}")

    # Per-slug indices for quick slicing
    print("Building per-slug trade indices...")
    tr_by_slug = {sl: g for sl, g in tr.groupby("slug", sort=False)}
    print(f"  slugs in trade tape: {len(tr_by_slug)}")

    # 3. For each F2 fire, compute pre-fire flow features
    print("Computing pre-fire flow features for each F2 fire ...")
    rows_fire = []
    for r in f2.itertuples(index=False):
        slug = r.slug
        t_us = int(r.ts_us)
        slug_tr = tr_by_slug.get(slug)
        if slug_tr is None:
            continue
        feats = {"slug": slug, "fire_ts_us": t_us, "f2_outcome": r.outcome,
                 "is_fire": 1, "wallet": r.wallet}
        for win_s in WINDOWS:
            lo = t_us - win_s * 1_000_000
            sub = slug_tr[(slug_tr.timestamp_us > lo)
                          & (slug_tr.timestamp_us < t_us)]
            if sub.empty:
                feats.update({f"n_trades_{win_s}s": 0,
                              f"net_aggressor_{win_s}s": 0.0,
                              f"up_buy_$_{win_s}s": 0.0,
                              f"dn_buy_$_{win_s}s": 0.0,
                              f"mean_price_up_{win_s}s": float("nan"),
                              f"mean_price_dn_{win_s}s": float("nan")})
                continue
            # buy = taker bought (paid ask)
            up = sub[sub.outcome == "Up"]
            dn = sub[sub.outcome == "Down"]
            up_buy_usd = float(
                (up[up.side == "buy"].size * up[up.side == "buy"].price).sum()
            )
            dn_buy_usd = float(
                (dn[dn.side == "buy"].size * dn[dn.side == "buy"].price).sum()
            )
            up_sell_usd = float(
                (up[up.side == "sell"].size * up[up.side == "sell"].price).sum()
            )
            dn_sell_usd = float(
                (dn[dn.side == "sell"].size * dn[dn.side == "sell"].price).sum()
            )
            # Aggressor on UP side (positive = more buying of Up)
            net_up = up_buy_usd - up_sell_usd
            net_dn = dn_buy_usd - dn_sell_usd
            feats.update({
                f"n_trades_{win_s}s": len(sub),
                f"up_buy_$_{win_s}s": up_buy_usd,
                f"dn_buy_$_{win_s}s": dn_buy_usd,
                f"up_sell_$_{win_s}s": up_sell_usd,
                f"dn_sell_$_{win_s}s": dn_sell_usd,
                f"net_up_{win_s}s": net_up,
                f"net_dn_{win_s}s": net_dn,
                f"flow_imbalance_{win_s}s": (
                    (net_up - net_dn) / (abs(net_up) + abs(net_dn) + 1e-9)
                ),
                f"mean_price_up_{win_s}s": float(up.price.mean()) if not up.empty else float("nan"),
                f"mean_price_dn_{win_s}s": float(dn.price.mean()) if not dn.empty else float("nan"),
            })
        rows_fire.append(feats)
    print(f"  F2 fire feature rows: {len(rows_fire)}")

    # 4. Sample control moments on the same slugs
    print("Sampling control moments (5s intervals on F2 slugs)...")
    rows_ctrl = []
    fire_ts_by_slug = f2.groupby("slug")["ts_us"].apply(set).to_dict()
    for slug, slug_tr in tr_by_slug.items():
        if slug_tr.empty:
            continue
        # Sample every 5s across the slug's trade timeline
        t_min = int(slug_tr.timestamp_us.min())
        t_max = int(slug_tr.timestamp_us.max())
        fire_ts = fire_ts_by_slug.get(slug, set())
        for t_us in range(t_min, t_max, 5_000_000):
            # Skip if within 2s of any fire
            close = any(abs(t_us - f) < 2_000_000 for f in fire_ts)
            if close:
                continue
            feats = {"slug": slug, "fire_ts_us": t_us, "f2_outcome": None,
                     "is_fire": 0, "wallet": None}
            for win_s in WINDOWS:
                lo = t_us - win_s * 1_000_000
                sub = slug_tr[(slug_tr.timestamp_us > lo)
                              & (slug_tr.timestamp_us < t_us)]
                if sub.empty:
                    feats.update({f"n_trades_{win_s}s": 0,
                                  f"flow_imbalance_{win_s}s": 0.0,
                                  f"net_up_{win_s}s": 0.0,
                                  f"net_dn_{win_s}s": 0.0})
                    continue
                up = sub[sub.outcome == "Up"]
                dn = sub[sub.outcome == "Down"]
                up_buy = float((up[up.side == "buy"].size * up[up.side == "buy"].price).sum())
                up_sell = float((up[up.side == "sell"].size * up[up.side == "sell"].price).sum())
                dn_buy = float((dn[dn.side == "buy"].size * dn[dn.side == "buy"].price).sum())
                dn_sell = float((dn[dn.side == "sell"].size * dn[dn.side == "sell"].price).sum())
                net_up = up_buy - up_sell
                net_dn = dn_buy - dn_sell
                feats.update({
                    f"n_trades_{win_s}s": len(sub),
                    f"up_buy_$_{win_s}s": up_buy,
                    f"dn_buy_$_{win_s}s": dn_buy,
                    f"net_up_{win_s}s": net_up,
                    f"net_dn_{win_s}s": net_dn,
                    f"flow_imbalance_{win_s}s": (
                        (net_up - net_dn) / (abs(net_up) + abs(net_dn) + 1e-9)
                    ),
                })
            rows_ctrl.append(feats)
    print(f"  control rows: {len(rows_ctrl)}")

    # 5. Build combined dataframe
    all_rows = rows_fire + rows_ctrl
    df = pd.DataFrame(all_rows)
    df.to_parquet(CACHE / "_f2_trade_flow_features.parquet", index=False)
    print(f"  saved -> _f2_trade_flow_features.parquet ({len(df)} rows)")

    # 6. Distribution comparison (fire vs control)
    print()
    print("=" * 90)
    print("Trade-flow features — fire vs control")
    print("=" * 90)
    feat_cols = [c for c in df.columns if c.startswith(("n_trades", "net_",
                                                          "flow_imbalance",
                                                          "up_buy_", "dn_buy_"))]
    fire = df[df.is_fire == 1]
    ctrl = df[df.is_fire == 0]
    summary = []
    for c in feat_cols:
        f = fire[c].dropna()
        cc = ctrl[c].dropna()
        if len(f) < 10 or len(cc) < 10:
            continue
        sf, sc = float(f.std()), float(cc.std())
        z = (float(f.mean()) - float(cc.mean())) / (sc + 1e-9)
        summary.append({
            "feature": c,
            "fire_mean": float(f.mean()),
            "ctrl_mean": float(cc.mean()),
            "fire_median": float(f.median()),
            "ctrl_median": float(cc.median()),
            "z_mean_diff": z,
        })
    sm = pd.DataFrame(summary).sort_values("z_mean_diff", key=abs, ascending=False)
    pd.options.display.float_format = "{:.4f}".format
    print(sm.to_string(index=False))

    # 7. Direction picker based on flow
    print()
    print("=" * 90)
    print("Does F2 pick the side WITH or AGAINST recent trade flow?")
    print("=" * 90)
    fire_only = df[df.is_fire == 1].copy()
    for win_s in WINDOWS:
        col = f"flow_imbalance_{win_s}s"
        sub = fire_only.dropna(subset=[col, "f2_outcome"])
        # flow > 0 means more buying of Up
        sub_pos = sub[sub[col] > 0.3]    # strong Up-bias flow
        sub_neg = sub[sub[col] < -0.3]   # strong Dn-bias flow
        if sub_pos.empty and sub_neg.empty:
            continue
        # F2 picks Up vs Down
        pct_up_when_flow_up = (sub_pos.f2_outcome == "Up").mean() if not sub_pos.empty else float("nan")
        pct_up_when_flow_dn = (sub_neg.f2_outcome == "Up").mean() if not sub_neg.empty else float("nan")
        print(f"  flow_imbalance_{win_s}s:")
        print(f"    flow > +0.3 (recent buyers favored Up): "
              f"n={len(sub_pos)}  F2 picks Up={pct_up_when_flow_up*100:.1f}%")
        print(f"    flow < -0.3 (recent buyers favored Down): "
              f"n={len(sub_neg)}  F2 picks Up={pct_up_when_flow_dn*100:.1f}%")


if __name__ == "__main__":
    main()
