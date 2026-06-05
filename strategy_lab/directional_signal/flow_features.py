"""
Order-flow features from the Polymarket trade tape (trades_polymarket, ~39M rows).

The missing microstructure signal: in the seconds before a decision, how hard are
buyers hitting Up vs Down? This is what the high-WR wallets likely select on
(price/momentum alone is priced-out). The F2 cluster fired contrarian to 5s
flow_imbalance per CLAUDE.md.

Per (slug, offset) — matching the dirscan grid — compute, over windows W before
fire_us = slot_start + offset (strictly causal, trades with ts <= fire_us):
  buy_up_vol_W   : sum size of BUY trades on the Up token
  buy_dn_vol_W   : sum size of BUY trades on the Down token
  flow_imb_W     : (buy_up - buy_dn) / (buy_up + buy_dn)   in [-1,1]  (+ = Up pressure)
  net_signed_W   : signed pressure incl. sells (buy adds / sell removes that side)
  n_trades_W     : trade count (intensity)
Windows: 5s, 30s, 60s.

Output: data/v4/canonical/_results/dirflow_<asset>_<tf>.parquet  (join key: slug, offset_s)

Usage:
  py -3 strategy_lab/directional_signal/flow_features.py --asset btc --tf 5m
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
TP = ROOT / "data" / "v4" / "canonical" / "trades_polymarket"
OUT = ROOT / "data" / "v4" / "canonical" / "_results"
OUT.mkdir(parents=True, exist_ok=True)

OFFSETS = {"5m": [30, 60, 120, 180, 240], "15m": [60, 180, 300, 600, 840]}
WINDOWS = [5, 30, 60]  # seconds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", required=True)
    ap.add_argument("--tf", required=True)
    args = ap.parse_args()
    asset, tf = args.asset.lower(), args.tf.lower()
    offsets = OFFSETS[tf]
    pref = f"{asset}-updown-{tf}-"

    print(f"loading trade tape {asset} ...")
    t = pq.read_table(TP / f"{asset}.parquet",
                      columns=["timestamp_us", "slug", "outcome", "size", "side"]).to_pandas()
    t = t[t["slug"].str.startswith(pref)].copy()
    t["slot_start_s"] = t["slug"].str.rsplit("-", n=1).str[-1].astype(np.int64)
    t["is_up"] = t["outcome"].astype(str).str.lower() == "up"
    t["is_buy"] = t["side"].astype(str).str.lower() == "buy"
    t["size"] = pd.to_numeric(t["size"], errors="coerce").fillna(0.0)
    t = t.sort_values("timestamp_us")
    print(f"  {len(t):,} updown {tf} trades, {t['slug'].nunique():,} slugs")

    # buy volumes split by token
    t["buy_up"] = np.where(t["is_buy"] & t["is_up"], t["size"], 0.0)
    t["buy_dn"] = np.where(t["is_buy"] & ~t["is_up"], t["size"], 0.0)
    # signed pressure toward Up: +buy_up, +sell_dn, -buy_dn, -sell_up
    sgn = np.where((t["is_buy"] & t["is_up"]) | (~t["is_buy"] & ~t["is_up"]), 1.0, -1.0)
    t["signed_up"] = t["size"] * sgn

    rows = []
    for slug, g in t.groupby("slug", sort=False):
        ts = g["timestamp_us"].to_numpy()
        bu = g["buy_up"].to_numpy().cumsum()
        bd = g["buy_dn"].to_numpy().cumsum()
        su = g["signed_up"].to_numpy().cumsum()
        cnt = np.arange(1, len(g) + 1)
        ss = int(g["slot_start_s"].iloc[0])

        def cum_at(arr, t_us):
            i = np.searchsorted(ts, t_us, side="right") - 1
            return arr[i] if i >= 0 else 0.0

        for off in offsets:
            fire_us = (ss + off) * 1_000_000
            row = {"slug": slug, "offset_s": off}
            hi_bu = cum_at(bu, fire_us); hi_bd = cum_at(bd, fire_us)
            hi_su = cum_at(su, fire_us); hi_cnt = cum_at(cnt, fire_us)
            for W in WINDOWS:
                lo_us = fire_us - W * 1_000_000
                lbu = cum_at(bu, lo_us); lbd = cum_at(bd, lo_us)
                lsu = cum_at(su, lo_us); lcnt = cum_at(cnt, lo_us)
                up = hi_bu - lbu; dn = hi_bd - lbd
                tot = up + dn
                row[f"flow_imb_{W}s"] = (up - dn) / tot if tot > 0 else np.nan
                row[f"net_signed_{W}s"] = hi_su - lsu
                row[f"n_trades_{W}s"] = int(hi_cnt - lcnt)
                row[f"buy_vol_{W}s"] = tot
            rows.append(row)

    df = pd.DataFrame(rows)
    out = OUT / f"dirflow_{asset}_{tf}.parquet"
    df.to_parquet(out, index=False)
    cov = df["flow_imb_5s"].notna().mean()
    print(f"  {len(df)} (slug,offset) rows, flow_imb_5s coverage {cov*100:.0f}%  -> {out}")


if __name__ == "__main__":
    main()
