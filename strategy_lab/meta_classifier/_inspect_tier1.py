import pandas as pd
ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
TIER1 = rf"{ROOT}\data\v4\refresh_2026_05_06\tier1_entries"
for a in ('btc','eth','sol'):
    df = pd.read_parquet(rf"{TIER1}\{a}_entries_at_t120.parquet")
    print(f"{a}: shape={df.shape}, cols(first10)={list(df.columns[:10])}")
    print(f"   slugs={df.slug.nunique()}, outcomes={df.outcome.unique()}")
    print(f"   target_ts range: {df.target_ts_us.min()} -> {df.target_ts_us.max()}")
    print(f"   dt_abs (us off target) p50/p95/max: {df.dt_abs.quantile([0.5,0.95,1.0]).round().astype(int).tolist()}")
