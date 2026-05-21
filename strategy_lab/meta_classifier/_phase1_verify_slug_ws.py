"""Phase 1: verify slug-ws is END time (resolution), NOT bar-close.

Method: for each production audit row, compute (ws_unix - at_unix). Group by tf
and version. Expected pattern under slug-ws-as-END:
  - 5m markets: ws-at ~ 240s (production fires at ws-240 = strike+60)
  - 15m markets: ws-at ~ 840s (production fires at ws-840 = strike+60)

If pattern is consistent (stdev < 5s), slug-ws-as-END confirmed.
"""
import re
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra/Desktop/global")

# Use the 851-row resolution data (has condition_id) + markets to derive ws
res = pd.read_csv(ROOT / "data/v4/shadow_trades_2026_05_08/momo_v1v2_live.csv", dtype={"condition_id": str})
res["at_us"] = (pd.to_datetime(res["at"], utc=True).astype("int64") // 1000)
res["at_unix"] = res.at_us // 1_000_000

m_old = pd.read_csv(ROOT / "data/v4/refresh_2026_05_06/markets_full.csv", dtype={"condition_id": str})[["condition_id", "slug"]]
m_new = pd.read_csv(ROOT / "data/v4/refresh_2026_05_09/markets_full.csv", dtype={"condition_id": str})[["condition_id", "slug"]]
mk = pd.concat([m_old, m_new]).drop_duplicates("condition_id")

df = res.merge(mk, on="condition_id", how="left").dropna(subset=["slug"]).copy()
df["ws"] = df.slug.str.extract(r"-(\d+)$")[0].astype("int64")
df["lag_s"] = df["ws"] - df["at_unix"]

# Parse sleeve into version + asset + tf
SLEEVE_RE = re.compile(r"^poly_updown_(btc|eth|sol)_(5m|15m)_momo(_v2)?_(HOLD|HEDGE|SELL)$")
df["asset"] = df.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(1).upper() if SLEEVE_RE.match(s) else None)
df["tf_p"] = df.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(2) if SLEEVE_RE.match(s) else None)
df["is_v2"] = df.sleeve_id.apply(lambda s: bool(SLEEVE_RE.match(s).group(3)) if SLEEVE_RE.match(s) else False)
df = df.dropna(subset=["asset"])

print(f"=== Phase 1: slug-ws semantics verification (n={len(df)}) ===\n")

# NOTE: `at` here is the RESOLUTION audit time (audited after chainlink settles), NOT fire time.
# So expect: at ≈ ws + small_lag (chainlink settle takes seconds-minutes).
# If audit `at` is BEFORE ws by hundreds of seconds, slug-ws is END time.

print("=== Per (tf, is_v2): lag_s = ws_unix - at_unix ===")
print("(positive = ws is in the future relative to audit; large positive = audit BEFORE ws)\n")
agg = df.groupby(["tf_p", "is_v2"]).lag_s.agg(["count", "mean", "median", "std", "min", "max"])
print(agg.round(1).to_string())

print("\n=== Distribution (10/25/50/75/90th percentile) ===")
for (tf, v2), g in df.groupby(["tf_p", "is_v2"]):
    p = g.lag_s.quantile([0.1, 0.25, 0.5, 0.75, 0.9])
    print(f"  {'v2' if v2 else 'v1'} {tf}: p10={p.iloc[0]:.0f}s  p25={p.iloc[1]:.0f}s  p50={p.iloc[2]:.0f}s  p75={p.iloc[3]:.0f}s  p90={p.iloc[4]:.0f}s  (n={len(g)})")

print("\n=== Interpretation ===")
print("If slug-ws is BAR-CLOSE START (my old assumption):")
print("  expect at >> ws (audit happens AFTER fire which is AFTER ws)")
print("  expect lag_s = (ws - at) < 0, i.e. negative numbers")
print("")
print("If slug-ws is END/RESOLUTION time:")
print("  expect at < ws (audit happens before market end if it's an entry-event audit)")
print("  expect lag_s > 0")
print("  - For RESOLUTION events (kind='poly_updown_resolution'), at = chainlink settle time")
print("    → audit happens AFTER ws (chainlink reports few seconds-minutes after end)")
print("    → lag_s ≈ -30 to -120s (negative, small)")
print("")
print("So for resolution events: lag_s should be slightly NEGATIVE if ws=END.")

# Also: for ENTRY-side signal events (which I already have in momo_orders_for_anchor.csv)
print("\n\n=== Additional check: signal-event audit `at` vs ws ===")
sig = pd.read_csv(ROOT / "data/v4/shadow_trades_2026_05_09/momo_orders_for_anchor.csv", dtype={"condition_id": str})
sig = sig.dropna(subset=["condition_id"])
sig["at_us"] = (pd.to_datetime(sig["at"], utc=True).astype("int64") // 1000)
sig["at_unix"] = sig.at_us // 1_000_000
sig = sig.merge(mk, on="condition_id", how="left").dropna(subset=["slug"])
sig["ws"] = sig.slug.str.extract(r"-(\d+)$")[0].astype("int64")
sig["lag_s"] = sig["ws"] - sig["at_unix"]
sig["is_v2"] = sig.sleeve_id.str.contains("_momo_v2_")
sig["tf_p"] = sig.tf

print(f"signal events (order_placed): n={len(sig)}\n")
print("=== Per (tf, is_v2): ws - at_signal ===")
agg2 = sig.groupby(["tf_p", "is_v2"]).lag_s.agg(["count", "mean", "median", "std", "min", "max"])
print(agg2.round(1).to_string())

print("\n=== Conclusion test ===")
print("If audit `at` for ORDER_PLACED signal events is consistently:")
print("  ~240s BEFORE ws on 5m sleeves AND ~840s BEFORE ws on 15m sleeves")
print("  → slug-ws is END time, production fires at ws-240 (5m) / ws-840 (15m) = strike+60")
print()
print("If audit `at` is consistently:")
print("  ~120s AFTER ws on 5m+15m v1 sleeves (= ws+120 fire), ~60s AFTER ws on v2 sleeves")
print("  → slug-ws is BAR-CLOSE start (my old assumption)")
