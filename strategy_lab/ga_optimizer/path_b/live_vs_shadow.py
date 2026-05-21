"""
Compare LIVE (Ireland) vs SHADOW (VPS3) for the same sleeves.

Both VPSes emit `poly_updown_resolution` events. By matching on condition_id +
sleeve_id (stripped of _LIVE suffix), we can compare fill quality directly
on the same markets.

Ireland: live + paper modes (both emitted per fire)
VPS3:    paper only (shadow)
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "v4" / "refresh_2026_05_19" / "raw"
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_trading_events


def parse_events(df):
    parsed = df["data"].apply(json.loads).apply(pd.Series)
    return pd.concat([df, parsed], axis=1)


def main():
    # Ireland (live mirror)
    irl = pd.read_csv(RAW / "ireland_events.csv.gz", compression="gzip")
    irl = parse_events(irl)
    irl["pnl"] = pd.to_numeric(irl["pnl_usd"], errors="coerce")
    irl["entry_price"] = pd.to_numeric(irl["entry_price"], errors="coerce")
    irl["entry_qty"] = pd.to_numeric(irl["entry_qty"], errors="coerce")
    irl["at_ts"] = pd.to_datetime(irl["at"], utc=True, errors="coerce")
    print(f"Ireland events: {len(irl):,}")
    print(f"  modes: {irl['mode'].value_counts().to_dict()}")
    print(f"  sleeves: {irl.sleeve_id.value_counts().head(10).to_dict()}")

    # VPS3 (shadow)
    print("\nLoading VPS3 events...")
    vps3 = load_trading_events()
    vps3 = vps3[vps3.kind == "poly_updown_resolution"].copy()
    vps3 = parse_events(vps3)
    vps3["pnl"] = pd.to_numeric(vps3["pnl_usd"], errors="coerce")
    vps3["entry_price"] = pd.to_numeric(vps3["entry_price"], errors="coerce")
    vps3["entry_qty"] = pd.to_numeric(vps3["entry_qty"], errors="coerce")
    vps3["at_ts"] = pd.to_datetime(vps3["at"], utc=True, errors="coerce")
    print(f"VPS3 events: {len(vps3):,}")

    # Normalize sleeve_id (drop _LIVE suffix for matching)
    irl["sleeve_base"] = irl.sleeve_id.str.replace("_LIVE", "", regex=False)
    vps3["sleeve_base"] = vps3.sleeve_id

    # Match LIVE Ireland trades to PAPER VPS3 on (sleeve_base, condition_id, signal)
    irl_live = irl[irl["mode"] == "live"].copy()
    irl_paper = irl[irl["mode"] == "paper"].copy()

    # Direct match: same condition_id + sleeve_base
    print(f"\nIreland LIVE: {len(irl_live)} events  Ireland PAPER: {len(irl_paper)}")

    # 1. Compare Ireland LIVE vs Ireland PAPER (same VPS, same sleeve, side-by-side)
    print(f"\n=== A) Ireland LIVE vs Ireland PAPER (same VPS, side-by-side) ===")
    matched_irl = irl_live.merge(
        irl_paper, on=["condition_id", "sleeve_base", "signal"],
        suffixes=("_live", "_paper"), how="inner"
    )
    print(f"  matched pairs: {len(matched_irl)}")
    if len(matched_irl):
        matched_irl["pnl_delta"] = matched_irl.pnl_live - matched_irl.pnl_paper
        matched_irl["entry_delta"] = matched_irl.entry_price_live - matched_irl.entry_price_paper
        print(f"  mean live entry_price : {matched_irl.entry_price_live.mean():.4f}")
        print(f"  mean paper entry_price: {matched_irl.entry_price_paper.mean():.4f}")
        print(f"  mean entry delta      : {matched_irl.entry_delta.mean():+.4f}  (live paid {matched_irl.entry_delta.mean()*100:+.2f}c more)")
        print(f"  total LIVE pnl   : ${matched_irl.pnl_live.sum():+.4f}")
        print(f"  total PAPER pnl  : ${matched_irl.pnl_paper.sum():+.4f}")
        print(f"  mean LIVE  pnl/trade: ${matched_irl.pnl_live.mean():+.4f}")
        print(f"  mean PAPER pnl/trade: ${matched_irl.pnl_paper.mean():+.4f}")
        print(f"  delta per trade     : ${matched_irl.pnl_delta.mean():+.4f}  (slippage cost)")
        print()
        print(matched_irl.groupby("sleeve_base").agg(
            n=("pnl_live", "size"),
            live_pnl=("pnl_live", "sum"),
            paper_pnl=("pnl_paper", "sum"),
            entry_delta=("entry_delta", "mean"),
            pnl_delta=("pnl_delta", "sum"),
        ).round(4).to_string())

    # 2. Cross-VPS: Ireland LIVE vs VPS3 PAPER
    print(f"\n=== B) Ireland LIVE vs VPS3 PAPER (cross-VPS) ===")
    matched_cross = irl_live.merge(
        vps3, on=["condition_id", "sleeve_base", "signal"],
        suffixes=("_live", "_v3"), how="inner"
    )
    print(f"  matched pairs (cross-VPS): {len(matched_cross)}")
    if len(matched_cross):
        matched_cross["pnl_delta"] = matched_cross.pnl_live - matched_cross.pnl_v3
        matched_cross["entry_delta"] = matched_cross.entry_price_live - matched_cross.entry_price_v3
        print(f"  total LIVE pnl   : ${matched_cross.pnl_live.sum():+.4f}")
        print(f"  total VPS3 pnl   : ${matched_cross.pnl_v3.sum():+.4f}")
        print(f"  delta per trade : ${matched_cross.pnl_delta.mean():+.4f}")
        print(f"  entry delta     : ${matched_cross.entry_delta.mean():+.4f}")
        print()
        print(matched_cross.groupby("sleeve_base").agg(
            n=("pnl_live", "size"),
            live_pnl=("pnl_live", "sum"),
            v3_pnl=("pnl_v3", "sum"),
            entry_delta=("entry_delta", "mean"),
        ).round(4).to_string())

    # 3. Slippage analysis on LIVE: entry_price gap, fill quality, hit rate
    print(f"\n=== C) Ireland LIVE pure stats ===")
    if len(irl_live):
        print(f"  n: {len(irl_live)}")
        irl_live["won_b"] = irl_live.won.astype(bool)
        print(f"  win rate: {irl_live.won_b.mean():.4f}")
        print(f"  total pnl: ${irl_live.pnl.sum():+.4f}")
        print(f"  per trade: ${irl_live.pnl.mean():+.4f}")
        print(f"  entry price stats: mean={irl_live.entry_price.mean():.4f} std={irl_live.entry_price.std():.4f}")
        print(f"  qty stats: mean={irl_live.entry_qty.mean():.2f} std={irl_live.entry_qty.std():.2f}")
        # Imply notional
        irl_live["notional"] = irl_live.entry_qty * irl_live.entry_price
        print(f"  implied notional: mean=${irl_live.notional.mean():.2f}  median=${irl_live.notional.median():.2f}")

    print(f"\n=== D) Per-sleeve LIVE vs all PAPER versions side-by-side ===")
    overall = pd.DataFrame()
    for slv_b, gl in irl_live.groupby("sleeve_base"):
        gp_irl = irl_paper[irl_paper.sleeve_base == slv_b]
        gp_v3 = vps3[vps3.sleeve_base == slv_b]
        row = {
            "sleeve_base": slv_b,
            "live_n": len(gl), "live_pnl": gl.pnl.sum(), "live_win": gl.won.fillna(False).mean(),
            "live_entry_avg": gl.entry_price.mean(),
            "irl_paper_n": len(gp_irl), "irl_paper_pnl": gp_irl.pnl.sum(),
            "irl_paper_win": gp_irl.won.fillna(False).mean() if len(gp_irl) else None,
            "v3_n": len(gp_v3), "v3_pnl": gp_v3.pnl.sum(),
            "v3_win": gp_v3.won.fillna(False).mean() if len(gp_v3) else None,
            "v3_entry_avg": gp_v3.entry_price.mean() if len(gp_v3) else None,
        }
        overall = pd.concat([overall, pd.DataFrame([row])], ignore_index=True)
    print(overall.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
