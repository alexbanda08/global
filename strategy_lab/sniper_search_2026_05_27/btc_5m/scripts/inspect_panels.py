"""Inspect feature panel schemas for BTC 5m sniper search."""
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")

panels = {
    "master_gate_features_v2": ROOT / "data/v4/canonical/_results/master_gate_features_v2.parquet",
    "regime_panel_5m_v2_fixed": ROOT / "data/v4/canonical/_results/regime_panel_5m_v2_fixed.parquet",
    "microprice_panel": ROOT / "data/v4/canonical/_results/microprice_panel.parquet",
    "microstructure_panel": ROOT / "data/v4/canonical/_results/microstructure_panel.parquet",
    "vol_hurst_at_fire_5m": ROOT / "data/v4/canonical/_results/vol_hurst_at_fire_5m.parquet",
    "sms_panel_5m_v2_fixed": ROOT / "data/v4/canonical/_results/sms_panel_5m_v2_fixed.parquet",
    "hawkes_panel": ROOT / "data/v4/canonical/_results/hawkes_panel.parquet",
    "vpin_panel": ROOT / "data/v4/canonical/_results/vpin_panel.parquet",
    "lee_mykland_panel": ROOT / "data/v4/canonical/_results/lee_mykland_panel.parquet",
}

for name, p in panels.items():
    if not p.exists():
        print(f"!! MISSING: {name} -> {p}")
        continue
    df = pd.read_parquet(p, columns=None)
    print("=" * 70)
    print(f"{name}: rows={len(df):,}, cols={len(df.columns)}")
    # detect ts col
    ts_cands = [c for c in df.columns if "_us" in c.lower() or c in ("at_ts", "fire_us", "ws_s", "ts", "bar_ts_us")]
    print(f"  ts candidates: {ts_cands}")
    # asset filter
    if "asset" in df.columns:
        print(f"  assets: {df['asset'].value_counts().to_dict()}")
    if "tf" in df.columns:
        print(f"  tfs: {df['tf'].value_counts().to_dict()}")
    # cols
    cols = list(df.columns)
    print(f"  cols: {cols[:30]}{'...' if len(cols)>30 else ''}")
    if len(cols) > 30:
        print(f"  cols (rest): {cols[30:]}")
    # time range
    for tc in ts_cands:
        try:
            mn = df[tc].min(); mx = df[tc].max()
            if mn > 1e15:
                dt_mn = pd.to_datetime(mn, unit="us", utc=True)
                dt_mx = pd.to_datetime(mx, unit="us", utc=True)
                print(f"  {tc} range: {dt_mn} -> {dt_mx} ({(dt_mx-dt_mn).total_seconds()/86400:.1f}d)")
        except Exception as e:
            print(f"  {tc}: err {e}")
    print()
