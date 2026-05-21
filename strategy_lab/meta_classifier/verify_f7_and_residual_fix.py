"""Verify F7 deployment on VPS3 + residual-mark fix on Ireland.

Two checks:
  1. VPS3 momo: compare _f7 sleeves to baseline (non-_f7) — WR + PnL
  2. Ireland maker: MAS 15m REDEEM rows should show slug_pnl_so_far ≈ 0
     (residual-mark fix landed → loser inv zeroed → no $0.50 over-credit)
"""
from __future__ import annotations
import json
import re
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
VPS3 = ROOT / "strategy_lab" / "monitoring" / "_logs" / "vps3" / "momo_resolutions_36h.csv"
IRE = ROOT / "strategy_lab" / "monitoring" / "_logs" / "ireland"

# ==========================================================================
# 1. VPS3 momo: F7 vs baseline
# ==========================================================================
print("=" * 100)
print("1. VPS3 momo — F7 vs baseline (last 36h, paper+shadow modes)")
print("=" * 100)

df = pd.read_csv(VPS3)
df.columns = ["sleeve_id", "at", "data"]
df["parsed"] = df.data.apply(lambda s: json.loads(s) if isinstance(s, str) else {})
df["won"] = df.parsed.apply(lambda d: d.get("won"))
df["pnl_usd"] = df.parsed.apply(lambda d: float(d.get("pnl_usd") or 0))
df["mode"] = df.parsed.apply(lambda d: d.get("mode"))
df["tf"] = df.parsed.apply(lambda d: d.get("tf"))
df["symbol"] = df.parsed.apply(lambda d: d.get("symbol"))

# Derive "is f7" + base "stem" sleeve_id for pairing
df["is_f7"] = df.sleeve_id.str.endswith("_f7")
df["base_sleeve"] = df.sleeve_id.str.replace("_f7$", "", regex=True)
df["policy"] = df.sleeve_id.str.extract(r"_(HOLD|HEDGE|SELL)(?:_f7)?$")[0]
df["version"] = df.sleeve_id.apply(lambda s: "v2" if "_momo_v2_" in s else "v1")
df["cell"] = df.symbol.str.lower() + "_" + df.tf

print(f"Total resolutions: {len(df):,}")
print(f"  F7 sleeves: {df.is_f7.sum():,}")
print(f"  baseline  : {(~df.is_f7).sum():,}")
print()

# Aggregate WR + PnL per cell × version × is_f7
agg = df.groupby(["cell", "version", "is_f7"]).agg(
    n=("won", "size"),
    wins=("won", lambda s: (s == True).sum()),
    pnl=("pnl_usd", "sum"),
).reset_index()
agg["wr_pct"] = agg.wins / agg.n.clip(lower=1) * 100
agg["per_trade"] = agg.pnl / agg.n.clip(lower=1)

# Pivot for side-by-side
pivot = agg.pivot_table(
    index=["cell", "version"], columns="is_f7",
    values=["n", "wr_pct", "pnl", "per_trade"],
    aggfunc="sum",
)
print("Per cell × version (False = baseline, True = F7):")
print(pivot.round(2).to_string())
print()

# Aggregate by version
print("\nAggregate (across ALL cells × HOLD/HEDGE/SELL policies):")
print(f"{'group':<18} {'n':>7} {'WR%':>7} {'sum_PnL':>11} {'$/trade':>9}")
print("-" * 60)
for v in ("v1", "v2"):
    for is_f7 in (False, True):
        sub = df[(df.version == v) & (df.is_f7 == is_f7)]
        n = len(sub)
        w = (sub.won == True).sum()
        wr = w / max(n, 1) * 100
        pnl = sub.pnl_usd.sum()
        per = pnl / max(n, 1)
        label = f"momo {v} {'+F7' if is_f7 else 'baseline'}"
        print(f"{label:<18} {n:>7d} {wr:>6.2f}% {pnl:>+11.2f} {per:>+9.4f}")
print()
# Total
print(f"{'TOTAL baseline':<18} {(~df.is_f7).sum():>7d} "
      f"{(df[~df.is_f7].won==True).sum()/max((~df.is_f7).sum(),1)*100:>6.2f}% "
      f"{df[~df.is_f7].pnl_usd.sum():>+11.2f}")
print(f"{'TOTAL +F7':<18} {df.is_f7.sum():>7d} "
      f"{(df[df.is_f7].won==True).sum()/max(df.is_f7.sum(),1)*100:>6.2f}% "
      f"{df[df.is_f7].pnl_usd.sum():>+11.2f}")

# ==========================================================================
# 2. Ireland MAS 15m residual-fix verification
# ==========================================================================
print()
print("=" * 100)
print("2. Ireland MAS 15m residual-fix verification")
print("=" * 100)

mas = pd.read_csv(IRE / "mas_2026-05-21.csv")
mas15 = mas[mas.tf == "15m"]
print(f"MAS 15m rows: {len(mas15)} ({mas15.slug.nunique()} unique slugs)")
print(f"Actions: {mas15.action.value_counts().to_dict()}")
print()
# Per-slug last-row PnL
last = mas15.sort_values("ts_us").drop_duplicates("slug", keep="last")
last["slug_pnl_so_far"] = pd.to_numeric(last.slug_pnl_so_far, errors="coerce")
last["inv_up"] = pd.to_numeric(last.inv_up, errors="coerce")
last["inv_dn"] = pd.to_numeric(last.inv_dn, errors="coerce")
print(f"Last-row per slug PnL distribution:")
print(last.slug_pnl_so_far.describe().round(4).to_string())
print()
print(f"inv_up + inv_dn at last row per slug:")
print(f"  inv_up sum:  {last.inv_up.sum()}")
print(f"  inv_dn sum:  {last.inv_dn.sum()}")
print(f"  expected:    0 (both should be zeroed after on_slug_resolved)")
print()
print(f"Per-slug PnL traces (REDEEM rows only):")
red = mas15[mas15.action == "REDEEM"]
for slug, g in red.groupby("slug"):
    g = g.sort_values("ts_us")
    final = g.iloc[-1]
    print(f"  {slug}: inv_up={final.inv_up} inv_dn={final.inv_dn} "
          f"slug_pnl_so_far={final.slug_pnl_so_far} cash_spent={final.cash_spent} "
          f"cash_recovered={final.cash_recovered}")

# ==========================================================================
# 3. ALL Ireland sleeves PnL with fixed residual
# ==========================================================================
print()
print("=" * 100)
print("3. All Ireland sleeves PnL (post residual-mark fix)")
print("=" * 100)

for f in sorted(IRE.glob("*_2026-05-21.csv")):
    df = pd.read_csv(f)
    last = df.sort_values("ts_us").drop_duplicates("slug", keep="last")
    last["slug_pnl_so_far"] = pd.to_numeric(last.slug_pnl_so_far, errors="coerce")
    last["inv_up"] = pd.to_numeric(last.inv_up, errors="coerce")
    last["inv_dn"] = pd.to_numeric(last.inv_dn, errors="coerce")
    n = len(last)
    pnl = last.slug_pnl_so_far.sum()
    pnl_mean = last.slug_pnl_so_far.mean()
    n_open = ((last.inv_up != 0) | (last.inv_dn != 0)).sum()
    print(f"  {f.stem}: n_slugs={n}  PnL_total=${pnl:+.2f}  mean=${pnl_mean:+.2f}  "
          f"slugs_with_open_inv={n_open}")
