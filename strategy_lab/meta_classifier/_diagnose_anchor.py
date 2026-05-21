"""Diagnose production's actual ret_2m anchor by recomputing with multiple candidates.

Pulls recent momo + momo_v2 signal audit rows with logged ret_2m_at_signal.
For each, computes ret_2m using strict-asof on several anchor candidates:
  - (ws-60, ws+60)       — momo_v2 spec (lab claim)
  - (ws, ws+120)         — momo_v1 documented production anchor
  - (ws-120, ws)         — full pre-window
  - (ws-60, ws+120)      — 180s window
  - (ws, ws+60)          — short window
  - BUGGY (ws, ws+120) using bar-START-indexed asof (60s lookahead)

Whichever candidate matches the logged value tells us production's actual anchor.
"""
import math
import re
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra/Desktop/global")
LIVE = ROOT / "data/v4/shadow_trades_2026_05_09/momo_orders_for_anchor.csv"
KLINES = ROOT / "data/v4/refresh_2026_05_09/klines_full.csv"

# --- Load production signals ---
sig = pd.read_csv(LIVE, dtype={"condition_id": str})
sig["at_dt"] = pd.to_datetime(sig["at"], utc=True)
sig = sig.dropna(subset=["condition_id", "ret_2m_at_signal"])
SLEEVE_RE = re.compile(r"^poly_updown_(btc|eth|sol)_(5m|15m)_momo(_v2)?_(HOLD|HEDGE|SELL)$")
sig["asset"] = sig.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(1).upper() if SLEEVE_RE.match(s) else None)
sig["is_v2"] = sig.sleeve_id.apply(lambda s: bool(SLEEVE_RE.match(s).group(3)) if SLEEVE_RE.match(s) else False)

# Derive ws from condition_id is hard — use markets table
markets_old = pd.read_csv(ROOT / "data/v4/refresh_2026_05_06/markets_full.csv", dtype={"condition_id": str})[["condition_id", "slug"]]
markets_new = pd.read_csv(ROOT / "data/v4/refresh_2026_05_09/markets_full.csv", dtype={"condition_id": str})[["condition_id", "slug"]]
markets = pd.concat([markets_old, markets_new]).drop_duplicates("condition_id")
sig = sig.merge(markets, on="condition_id", how="left")
sig = sig.dropna(subset=["slug"]).copy()
sig["ws"] = sig.slug.str.extract(r"-(\d+)$")[0].astype("int64")
print(f"sample size: {len(sig)} signal events with ws + ret_2m_at_signal")
print(f"version split: v1={int((~sig.is_v2).sum())} v2={int(sig.is_v2.sum())}")
print(f"signal split: order_placed={int((sig.reason=='order_placed').sum())} no_signal={int((sig.reason=='no_signal').sum())}")
print()

# --- Load klines ---
ASSET_BIN = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
ASSET_OKX = {"BTC": "OKX_SPOT_BTC_USDT", "ETH": "OKX_SPOT_ETH_USDT", "SOL": "OKX_SPOT_SOL_USDT"}
df_k = pd.read_csv(KLINES)
df_k["ts_s"] = (df_k.time_period_start_us // 1_000_000).astype("int64")
klines = {}
for a in ("BTC", "ETH", "SOL"):
    b = df_k[df_k.symbol_id == ASSET_BIN[a]][["ts_s", "price_close"]].copy(); b["src"] = "b"
    o = df_k[df_k.symbol_id == ASSET_OKX[a]][["ts_s", "price_close"]].copy(); o["src"] = "o"
    c = pd.concat([b, o]).sort_values(["ts_s", "src"]).drop_duplicates("ts_s", keep="first").sort_values("ts_s").reset_index(drop=True)
    klines[a] = (
        (c.ts_s.values.astype("int64") + 60) * 1_000_000,  # end_us
        c.ts_s.values.astype("int64") * 1_000_000,          # start_us
        c.price_close.values.astype("float64"),
    )

def asof_strict(asset, ts_s):
    end_us, _, price_close = klines[asset]
    target = int(ts_s) * 1_000_000
    idx = int(np.searchsorted(end_us, target, side="right")) - 1
    return float("nan") if idx < 0 else float(price_close[idx])

def asof_buggy(asset, ts_s):
    """Bar-START-indexed asof — returns price 60s in the FUTURE."""
    _, start_us, price_close = klines[asset]
    target = int(ts_s) * 1_000_000
    idx = int(np.searchsorted(start_us, target, side="right")) - 1
    return float("nan") if idx < 0 else float(price_close[idx])

# --- Compute candidate ret_2m for each row ---
print("computing 6 candidate anchors per row...")
candidates = {
    "spec_v2_strict": ("strict", -60, 60),       # (ws-60, ws+60), strict asof
    "v1_doc_strict": ("strict", 0, 120),          # (ws, ws+120), strict asof
    "long_window": ("strict", -60, 120),          # (ws-60, ws+120), 180s window
    "short_window": ("strict", 0, 60),            # (ws, ws+60), 60s window
    "v1_buggy_asof": ("buggy", 0, 120),           # (ws, ws+120), buggy bar-start asof
    "v2_buggy_asof": ("buggy", -60, 60),          # (ws-60, ws+60), buggy asof
}

rows = []
for r in sig.itertuples(index=False):
    asset = r.asset
    ws = int(r.ws)
    obs = float(r.ret_2m_at_signal)
    row = {"sleeve_id": r.sleeve_id, "is_v2": r.is_v2, "asset": asset, "tf": r.tf,
           "ws": ws, "obs_ret": obs, "phase": r.entry_phase, "reason": r.reason}
    for name, (kind, off0, off1) in candidates.items():
        fn = asof_strict if kind == "strict" else asof_buggy
        c0 = fn(asset, ws + off0)
        c1 = fn(asset, ws + off1)
        if math.isfinite(c0) and math.isfinite(c1) and c0 > 0:
            ret = math.log(c1 / c0)
        else:
            ret = float("nan")
        row[name] = ret
        row[f"{name}_diff"] = abs(ret - obs) if math.isfinite(ret) else float("nan")
    rows.append(row)

df = pd.DataFrame(rows)
df.to_csv(ROOT / "data/v4/shadow_trades_2026_05_09/anchor_diagnosis.csv", index=False)
print(f"  computed {len(df)} rows")
print()

# --- Find which anchor matches best ---
print("=== Mean absolute diff per candidate (smaller = better match to production) ===")
diff_cols = [c for c in df.columns if c.endswith("_diff")]
mean_abs_diff = df[diff_cols].mean().sort_values()
print(mean_abs_diff.to_string())
print()

print("=== Median absolute diff per candidate ===")
median_abs_diff = df[diff_cols].median().sort_values()
print(median_abs_diff.to_string())
print()

# Per-version split
print("=== Per-version mean absolute diff (v1 vs v2) ===")
for is_v2 in (False, True):
    sub = df[df.is_v2 == is_v2]
    if len(sub) == 0: continue
    print(f"\n{'v2' if is_v2 else 'v1'} (n={len(sub)}):")
    print(sub[diff_cols].mean().sort_values().to_string())

# Show 5 sample rows with all candidates
print("\n=== Sample 5 rows comparing all anchors to obs ret_2m_at_signal ===")
sample = df.sample(min(5, len(df)), random_state=42)
cols = ["sleeve_id", "is_v2", "ws", "phase", "obs_ret"] + list(candidates.keys())
print(sample[cols].to_string(index=False))

# Match rate: within 1e-6 of observed
print("\n=== % rows where each candidate matches obs within 1e-6 ===")
for name in candidates.keys():
    diff = df[f"{name}_diff"]
    match_pct = 100 * (diff < 1e-6).sum() / len(diff[diff.notna()])
    print(f"  {name:<22} {match_pct:>5.1f}%")

print("\n=== Per-version match rate ===")
for is_v2 in (False, True):
    sub = df[df.is_v2 == is_v2]
    print(f"\n{'v2' if is_v2 else 'v1'} (n={len(sub)}):")
    for name in candidates.keys():
        diff = sub[f"{name}_diff"]
        valid = diff.notna()
        if valid.sum() == 0: continue
        match_pct = 100 * (diff < 1e-6).sum() / valid.sum()
        print(f"  {name:<22} {match_pct:>5.1f}%")
