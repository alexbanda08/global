"""Compare last 12h post-WS-patch production performance vs backtest prediction.

Backtest prediction (full-universe 17d window):
  HOLD           +$13.54/trade
  HEDGE_5bp      +$10.44/trade
  SELL_5bp       +$10.42/trade
  HEDGE fire%    14%
  SELL fire%     14%

Production should now (post-patch) match these numbers if the WS book mirror
is properly serving HEDGE/SELL paths and the strategy alpha translates to live.
"""
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
LIVE = ROOT / "data/v4/shadow_trades_2026_05_09/momo_post_patch_12h.csv"

df = pd.read_csv(LIVE)
df["hedged"] = df.hedged.astype(str).str.lower() == "true"
df["partial_bid_exit"] = df.partial_bid_exit.astype(str).str.lower() == "true"
df["actual_exit"] = "hold"
df.loc[df.hedged, "actual_exit"] = "hedge"
df.loc[df.partial_bid_exit, "actual_exit"] = "sell"

# parse sleeve into version + policy
import re
SLEEVE_RE = re.compile(r"^poly_updown_(btc|eth|sol)_(5m|15m)_momo(_v2)?_(HOLD|HEDGE|SELL)$")
df["asset_p"] = df.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(1).upper() if SLEEVE_RE.match(s) else None)
df["tf_p"] = df.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(2) if SLEEVE_RE.match(s) else None)
df["is_v2"] = df.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(3) == "_v2" if SLEEVE_RE.match(s) else False)
df["policy_tag"] = df.sleeve_id.apply(lambda s: SLEEVE_RE.match(s).group(4) if SLEEVE_RE.match(s) else None)

print(f"=== Post-WS-patch shadow data: last 12h ({len(df)} resolutions) ===")
print(f"window: {df['at'].min()} -> {df['at'].max()}\n")

# Per-policy summary across all cells
print("=== Production performance by sleeve policy (last 12h) ===")
agg = df.groupby(["is_v2", "policy_tag"]).agg(
    n=("pnl_usd", "size"),
    pnl_total=("pnl_usd", "sum"),
    pnl_mean=("pnl_usd", "mean"),
    n_hedged=("hedged", "sum"),
    n_sell=("partial_bid_exit", "sum"),
    hedge_fire_pct=("hedged", lambda s: round(100*s.sum()/max(len(s),1), 1)),
    sell_fire_pct=("partial_bid_exit", lambda s: round(100*s.sum()/max(len(s),1), 1)),
).round(2)
print(agg.to_string())
print()

# Production exit-policy effective PnL (per actual exit)
print("=== Production PnL by ACTUAL exit reason (last 12h) ===")
agg2 = df.groupby(["is_v2", "policy_tag", "actual_exit"]).agg(
    n=("pnl_usd", "size"),
    pnl_total=("pnl_usd", "sum"),
    pnl_mean=("pnl_usd", "mean"),
).round(2)
print(agg2.to_string())
print()

# Per-cell view
print("=== Per-cell PnL summary ===")
agg3 = df.groupby(["is_v2", "asset_p", "tf_p", "policy_tag"]).agg(
    n=("pnl_usd", "size"),
    pnl_total=("pnl_usd", "sum"),
    pnl_mean=("pnl_usd", "mean"),
    hedge_fire=("hedged", lambda s: int(s.sum())),
    sell_fire=("partial_bid_exit", lambda s: int(s.sum())),
).round(2)
print(agg3.to_string())
print()

# Comparison table
print("=== Production vs Backtest comparison ===\n")
print(f"{'cell':<25} {'n':>5} {'prod_pnl/trd':>13} {'bt_pnl/trd':>11} {'gap':>8}")
print("-" * 65)
# Backtest predictions per cell+policy from full_universe per_trade.csv
bt_path = ROOT / "data/v4/refresh_2026_05_09/full_universe/per_trade.csv"
bt = pd.read_csv(bt_path)
# Map prod policy_tag → backtest variant
policy_to_variant = {"HOLD": "HOLD_baseline", "HEDGE": "HEDGE_5bp", "SELL": "SELL_5bp"}
for is_v2 in (False, True):
    for tag in ("HOLD", "HEDGE", "SELL"):
        sub_prod = df[(df.is_v2 == is_v2) & (df.policy_tag == tag)]
        if len(sub_prod) == 0:
            continue
        prod_mean = sub_prod.pnl_usd.mean()
        # Find matching backtest cell-mean
        variant = policy_to_variant[tag]
        # Aggregate backtest at all cells for this variant since prod is mixed across cells
        bt_sub = bt[bt.variant == variant]
        bt_mean = bt_sub.pnl.mean()
        ver = "v2" if is_v2 else "v1"
        gap = prod_mean - bt_mean
        print(f"{ver}_{tag}                 {len(sub_prod):>5}  ${prod_mean:>+11.2f}  ${bt_mean:>+9.2f}  ${gap:>+6.2f}")
