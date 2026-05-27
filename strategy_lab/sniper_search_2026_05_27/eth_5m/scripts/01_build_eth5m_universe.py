"""
Build the ETH 5m candidate universe with features merged for sniper search.

Master universe: master_gate_features_v2.parquet (filtered ETH 5m), 22,741 fires.
Joins microstructure depth (up/dn total ask size & 2% depth) for $250-capable filter.
Computes binary g_book_depth_supports_250 = (1 if chosen-direction total_ask_size > 1500).

Outputs: data/v4/canonical/_results/_sniper_eth5m_universe.parquet
"""
import sys
import pandas as pd
import numpy as np

CANONICAL = "data/v4/canonical/_results"
OUT = "data/v4/canonical/_results/_sniper_eth5m_universe.parquet"

def main():
    print("Loading master_gate_features_v2 ...")
    df = pd.read_parquet(f"{CANONICAL}/master_gate_features_v2.parquet")
    eth5 = df[(df["asset"] == "ETH") & (df["tf"] == "5m")].copy()
    print(f"ETH 5m fires: {len(eth5):,}")
    print(f"  baseline WR: {eth5['won'].mean():.4f}")
    print(f"  baseline $/tr: {eth5['pnl_legacy_usd'].mean():+.4f}")
    print(f"  baseline sum: {eth5['pnl_legacy_usd'].sum():+.2f}")

    print("\nLoading microstructure panel for depth ...")
    ms = pd.read_parquet(f"{CANONICAL}/microstructure_panel.parquet")
    ms_eth5 = ms[(ms["asset"] == "ETH") & (ms["tf"] == "5m")].copy()
    print(f"ms ETH 5m rows: {len(ms_eth5):,}")

    keep_cols = [
        "slug", "fire_offset_s",
        "up_total_ask_size", "dn_total_ask_size",
        "up_depth_2pct", "dn_depth_2pct",
        "up_eff_spread_25", "dn_eff_spread_25",
        "up_spread_bps", "dn_spread_bps",
        "imb5_diff", "depth_diff",
    ]
    keep_cols = [c for c in keep_cols if c in ms_eth5.columns]
    merged = eth5.merge(ms_eth5[keep_cols], on=["slug", "fire_offset_s"], how="left")
    print(f"merged: {merged.shape}")

    # Chosen-direction depth columns
    is_up = (merged["direction"] == "UP")
    merged["chosen_total_size"] = np.where(is_up, merged["up_total_ask_size"], merged["dn_total_ask_size"])
    merged["chosen_depth_2pct"] = np.where(is_up, merged["up_depth_2pct"], merged["dn_depth_2pct"])
    merged["chosen_spread_bps"] = np.where(is_up, merged["up_spread_bps"], merged["dn_spread_bps"])
    merged["chosen_eff_spread_25"] = np.where(is_up, merged["up_eff_spread_25"], merged["dn_eff_spread_25"])

    # Book-depth gate for $250-capable
    # brief: > 6x $250 = $1500 total available on chosen side
    merged["g_book_depth_supports_250"] = (merged["chosen_total_size"].fillna(0) > 1500.0).astype(int)
    # Tighter: > 12x = $3000 (extra-safe)
    merged["g_book_depth_supports_250_tight"] = (merged["chosen_total_size"].fillna(0) > 3000.0).astype(int)

    print()
    print(f"book_depth_supports_250 fire-coverage: {merged['g_book_depth_supports_250'].mean()*100:.1f}%")
    print(f"book_depth_supports_250_tight        : {merged['g_book_depth_supports_250_tight'].mean()*100:.1f}%")

    # Time index
    merged["day"] = pd.to_datetime(merged["fire_us"], unit="us").dt.date
    days_total = merged["day"].nunique()
    print(f"\nDays covered: {days_total}")

    # 3-way chronological split
    # Per brief: 20d train / 7d val / 5d lockbox
    # But we only have 25 days. Adapt: 15/5/5 sliding
    days_sorted = sorted(merged["day"].unique())
    print(f"day list: {days_sorted[0]} ... {days_sorted[-1]}")
    n_lockbox = 5
    n_val = 5
    lockbox_days = set(days_sorted[-n_lockbox:])
    val_days = set(days_sorted[-(n_lockbox + n_val):-n_lockbox])
    train_days = set(days_sorted[:-(n_lockbox + n_val)])

    def label(d):
        if d in lockbox_days: return "lockbox"
        if d in val_days: return "val"
        if d in train_days: return "train"
        return "drop"

    merged["split"] = merged["day"].map(label)
    print(f"\nSplit counts:")
    print(merged["split"].value_counts())

    print(f"\nWrite -> {OUT}")
    merged.to_parquet(OUT)
    print("Done.")

if __name__ == "__main__":
    main()
