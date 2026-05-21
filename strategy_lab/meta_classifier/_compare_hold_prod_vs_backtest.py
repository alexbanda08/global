"""Compare HOLD-only production data (full window since deploy) vs backtest HOLD prediction."""
import re
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra/Desktop/global")
LIVE = ROOT / "data/v4/shadow_trades_2026_05_09/momo_hold_full.csv"
BT = ROOT / "data/v4/refresh_2026_05_09/full_universe/per_trade.csv"

df = pd.read_csv(LIVE)
df["at_dt"] = pd.to_datetime(df["at"], utc=True)
df["won"] = df["won"].astype(str).str.lower().isin(("t", "true"))
df["day"] = df.at_dt.dt.date
SLEEVE_RE = re.compile(r"^poly_updown_(btc|eth|sol)_(5m|15m)_momo(_v2)?_HOLD$")
df["asset"] = df.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(1).upper() if SLEEVE_RE.match(s) else None)
df["tf"] = df.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(2) if SLEEVE_RE.match(s) else None)
df["is_v2"] = df.sleeve_id.apply(lambda s: bool(SLEEVE_RE.match(s).group(3)) if SLEEVE_RE.match(s) else False)

print(f"=== Production HOLD sleeve resolutions: {len(df)} ===")
print(f"window: {df.at_dt.min()} -> {df.at_dt.max()}")
hours = (df.at_dt.max() - df.at_dt.min()).total_seconds() / 3600
print(f"duration: {hours:.1f}h")
print()

# Per-version overall
print("=== Per-version HOLD totals ===")
for is_v2 in (False, True):
    sub = df[df.is_v2 == is_v2]
    if len(sub) == 0: continue
    ver = "v2" if is_v2 else "v1"
    wins = int(sub.won.sum())
    pos_pnl = float(sub.pnl_usd.sum())
    avg = pos_pnl / len(sub)
    hit = wins / len(sub) * 100
    print(f"  {ver} HOLD: n={len(sub):>3}  wins={wins:>3} ({hit:.1f}%)  total_pnl=${pos_pnl:+.2f}  mean_pnl=${avg:+.4f}")
print()

# Per-cell
print("=== Per (version, asset, tf) HOLD cell ===")
agg = df.groupby(["is_v2", "asset", "tf"]).agg(
    n=("pnl_usd", "size"),
    wins=("won", "sum"),
    hit_pct=("won", lambda s: round(100*s.sum()/len(s), 1)),
    pnl_total=("pnl_usd", "sum"),
    pnl_mean=("pnl_usd", "mean"),
).round(2)
print(agg.to_string())
print()

# Backtest HOLD baseline (full 17d universe)
print("=== Backtest HOLD baseline (Apr 23 -> May 9, 17d universe) ===")
bt = pd.read_csv(BT)
bt_hold = bt[bt.variant == "HOLD_baseline"]
bt_agg = bt_hold.groupby(["asset", "tf"]).agg(
    n=("pnl", "size"),
    wins=("pnl", lambda s: int((s > 0).sum())),
    hit_pct=("pnl", lambda s: round(100*(s > 0).sum()/len(s), 1)),
    pnl_total=("pnl", "sum"),
    pnl_mean=("pnl", "mean"),
).round(2)
print(bt_agg.to_string())
print()

# Apples-to-apples: filter backtest to ONLY days production HOLD covered
prod_days = set(df.day.astype(str))
print(f"=== Backtest HOLD subset on overlapping days only ({sorted(prod_days)}) ===")
bt_hold_window = bt_hold[bt_hold.day.isin(prod_days)]
bt_agg_w = bt_hold_window.groupby(["asset", "tf"]).agg(
    n=("pnl", "size"),
    wins=("pnl", lambda s: int((s > 0).sum())),
    hit_pct=("pnl", lambda s: round(100*(s > 0).sum()/len(s), 1)),
    pnl_total=("pnl", "sum"),
    pnl_mean=("pnl", "mean"),
).round(2)
print(bt_agg_w.to_string())
print()

# Side-by-side: prod vs backtest-on-same-days
print("=== Prod HOLD vs Backtest HOLD (overlapping days only) ===\n")
print(f"{'cell':<18} {'prod_n':>6} {'prod_pnl/trd':>14} {'bt_n':>5} {'bt_pnl/trd':>11} {'haircut%':>10}")
print("-" * 72)
for is_v2 in (False, True):
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m"):
            sub_prod = df[(df.is_v2 == is_v2) & (df.asset == asset) & (df.tf == tf)]
            sub_bt = bt_hold_window[(bt_hold_window.asset == asset) & (bt_hold_window.tf == tf)]
            if len(sub_prod) == 0 or len(sub_bt) == 0: continue
            ver = "v2" if is_v2 else "v1"
            pm = float(sub_prod.pnl_usd.mean())
            bm = float(sub_bt.pnl.mean())
            hc = (1 - pm / bm) * 100 if bm != 0 else float("nan")
            print(f"{ver}_{asset}_{tf:<3}        {len(sub_prod):>6} ${pm:>+12.4f} {len(sub_bt):>5} ${bm:>+9.4f} {hc:>9.1f}%")
print()

# Aggregate (all cells combined)
print("=== Aggregate Prod HOLD vs Backtest HOLD (overlapping days) ===")
prod_total = df.pnl_usd.sum(); prod_n = len(df); prod_mean = prod_total / prod_n
bt_total = bt_hold_window.pnl.sum(); bt_n = len(bt_hold_window); bt_mean = bt_total / bt_n
print(f"  Production: n={prod_n}, total=${prod_total:+.2f}, mean=${prod_mean:+.4f}/trade")
print(f"  Backtest  : n={bt_n}, total=${bt_total:+.2f}, mean=${bt_mean:+.4f}/trade")
hc = (1 - prod_mean / bt_mean) * 100 if bt_mean != 0 else float("nan")
print(f"  Haircut    : {hc:.1f}%  (production captures {100-hc:.1f}% of backtest expectation)")
print()

# Production cumulative pnl by day
print("=== Production HOLD cumulative pnl by day (across all cells) ===")
daily = df.groupby("day").pnl_usd.agg(["count", "sum", "mean"]).round(4)
daily.columns = ["n", "pnl_total", "pnl_mean"]
print(daily.to_string())
