"""
Compute per-slug and per-day PnL for wallet 0xce25e214 over the fetched window
(2026-07-01 21:17 UTC -> 2026-07-02 05:48 UTC, 3481 unique BUY fills, 288 slugs).

Outcomes source: Polymarket gamma-api /events?slug=... (100% coverage, 0 errors,
validated 156/156 agreement against vps3 storedata.market_resolutions_v2 -- that
table only covered 156/288 = 54% of slugs, and had ZERO XRP coverage because
storedata's chainlink oracle_prices_v2 only carries BTC/ETH/SOL; XRP resolutions
are Polymarket-native / chainlink-XRP which storedata does not persist. Gamma API
bypassed that gap entirely and is fully current (resolves even the most recent
slug in the window).

PnL convention per project CLAUDE.md:
  - Winner-only taker fee: 0.07 * p * (1-p), charged on the WINNING leg only,
    at that leg's own average entry price p (shares-weighted).
  - LOST shares: pnl = -cost (no fee).
  - WON shares: pnl = shares*(1-avg_price) - fee, where fee = 0.07*avg_price*(1-avg_price)*shares
    i.e. pnl_07 = shares*(1-avg_price)*(1-0.07*avg_price)  [algebraically identical]
  - This wallet is 100% BUY (0 sells in the fetched window) -> hold-to-resolution only,
    no exit-scalp component to model.
"""
import json
import pandas as pd
import numpy as np

CACHE = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache\0xce25e214"

# ---- load fills ----
fills = pd.read_csv(f"{CACHE}\\trades_recent_2026_07_02.csv")
fills = fills.drop_duplicates(subset=["transactionHash", "asset", "size", "price", "timestamp", "side"])
assert (fills["side"] == "BUY").all(), "expected all-BUY wallet in this window"

fills["cost"] = fills["size"] * fills["price"]
fills["dt_utc"] = pd.to_datetime(fills["timestamp"], unit="s", utc=True)
fills["date_utc"] = fills["dt_utc"].dt.date.astype(str)
fills["coin"] = fills["slug"].str.split("-").str[0]
fills["tf"] = fills["slug"].str.split("-").str[2]
fills["slot_start"] = fills["slug"].str.rsplit("-", n=1).str[1].astype(int)

# ---- load gamma outcomes ----
with open(f"{CACHE}\\gamma_outcomes_2026_07_02.json") as f:
    gamma = json.load(f)

winners = {}
for slug, v in gamma.items():
    op = json.loads(v["outcomePrices"])
    oc = json.loads(v["outcomes"])
    op_f = [float(x) for x in op]
    if abs(sum(op_f) - 1.0) > 1e-6 or 1.0 not in op_f:
        continue  # unresolved / malformed -- none observed in this pull
    idx = op_f.index(1.0)
    winners[slug] = oc[idx]

fills["winner_outcome"] = fills["slug"].map(winners)
n_resolved_slugs = fills.loc[fills["winner_outcome"].notna(), "slug"].nunique()
n_total_slugs = fills["slug"].nunique()
n_unresolved_slugs = n_total_slugs - n_resolved_slugs
print(f"slugs: {n_total_slugs} total, {n_resolved_slugs} resolved, {n_unresolved_slugs} unresolved")

fills["is_winning_leg"] = fills["outcome"] == fills["winner_outcome"]

FEE_RATE = 0.07


def leg_pnl_gross(row):
    if pd.isna(row["winner_outcome"]):
        return np.nan
    if row["is_winning_leg"]:
        return row["size"] * (1.0 - row["price"])
    else:
        return -row["size"] * row["price"]


def leg_fee(row):
    if pd.isna(row["winner_outcome"]) or not row["is_winning_leg"]:
        return 0.0
    return FEE_RATE * row["price"] * (1.0 - row["price"]) * row["size"]


fills["pnl_gross"] = fills.apply(leg_pnl_gross, axis=1)
fills["fee"] = fills.apply(leg_fee, axis=1)
fills["pnl_fee_adj"] = fills["pnl_gross"] - fills["fee"]

# =========================================================================
# PER-SLUG aggregation
# =========================================================================
resolved = fills[fills["winner_outcome"].notna()].copy()
unresolved = fills[fills["winner_outcome"].isna()].copy()

per_slug = resolved.groupby("slug").agg(
    coin=("coin", "first"),
    tf=("tf", "first"),
    slot_start=("slot_start", "first"),
    n_fills=("slug", "size"),
    total_cost=("cost", "sum"),
    up_shares=("size", lambda s: s[resolved.loc[s.index, "outcome"] == "Up"].sum()),
    down_shares=("size", lambda s: s[resolved.loc[s.index, "outcome"] == "Down"].sum()),
    winner=("winner_outcome", "first"),
    pnl_gross=("pnl_gross", "sum"),
    fee=("fee", "sum"),
    pnl_fee_adj=("pnl_fee_adj", "sum"),
    date_utc=("date_utc", "first"),
).reset_index()

per_slug["avg_up_price"] = resolved[resolved["outcome"] == "Up"].groupby("slug")["price"].mean()
per_slug = per_slug.set_index("slug")
per_slug["avg_up_price"] = resolved[resolved["outcome"] == "Up"].groupby("slug").apply(
    lambda g: (g["price"] * g["size"]).sum() / g["size"].sum()
)
per_slug["avg_down_price"] = resolved[resolved["outcome"] == "Down"].groupby("slug").apply(
    lambda g: (g["price"] * g["size"]).sum() / g["size"].sum()
)
per_slug = per_slug.reset_index()
per_slug["sum_ask"] = per_slug["avg_up_price"].fillna(0) + per_slug["avg_down_price"].fillna(0)
per_slug["is_paired"] = per_slug["up_shares"].gt(0) & per_slug["down_shares"].gt(0)

per_slug = per_slug.sort_values("slot_start")
per_slug.to_csv(f"{CACHE}\\per_slug_pnl_2026_07_02.csv", index=False)
print(f"saved per-slug csv: {len(per_slug)} rows -> {CACHE}\\per_slug_pnl_2026_07_02.csv")

# =========================================================================
# PER-DAY aggregation
# =========================================================================
per_day = resolved.groupby("date_utc").agg(
    n_fills=("slug", "size"),
    n_slugs=("slug", "nunique"),
    volume=("cost", "sum"),
    pnl_gross=("pnl_gross", "sum"),
    fee=("fee", "sum"),
    pnl_fee_adj=("pnl_fee_adj", "sum"),
).reset_index()
print("\n=== PER-DAY (resolved-only) ===")
print(per_day.to_string(index=False))

# =========================================================================
# Per-slug distribution stats (fee-adjusted)
# =========================================================================
dist = per_slug["pnl_fee_adj"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])
print("\n=== per-slug pnl_fee_adj distribution ===")
print(dist)

win_slugs = per_slug[per_slug["pnl_fee_adj"] > 0]
loss_slugs = per_slug[per_slug["pnl_fee_adj"] <= 0]
print(f"\nwin slugs: {len(win_slugs)} ({len(win_slugs)/len(per_slug)*100:.1f}%), "
      f"mean pnl {win_slugs['pnl_fee_adj'].mean():.3f}, total {win_slugs['pnl_fee_adj'].sum():.2f}")
print(f"loss slugs: {len(loss_slugs)} ({len(loss_slugs)/len(per_slug)*100:.1f}%), "
      f"mean pnl {loss_slugs['pnl_fee_adj'].mean():.3f}, total {loss_slugs['pnl_fee_adj'].sum():.2f}")

# window totals
window_total_gross = per_slug["pnl_gross"].sum()
window_total_fee = per_slug["fee"].sum()
window_total_feeadj = per_slug["pnl_fee_adj"].sum()
n_hours = (fills["dt_utc"].max() - fills["dt_utc"].min()).total_seconds() / 3600
print(f"\n=== WINDOW TOTAL (resolved slugs only, n={len(per_slug)}) ===")
print(f"gross: {window_total_gross:.2f}  fee: {window_total_fee:.2f}  fee_adj: {window_total_feeadj:.2f}")
print(f"window hours: {n_hours:.2f}")
print(f"extrapolated $/day (fee_adj): {window_total_feeadj / n_hours * 24:.2f}")
print(f"extrapolated $/day (gross):   {window_total_gross / n_hours * 24:.2f}")

# =========================================================================
# Unresolved exposure
# =========================================================================
unresolved_slugs = unresolved["slug"].unique()
unresolved_cost = unresolved.groupby("slug")["cost"].sum()
print(f"\n=== UNRESOLVED ===")
print(f"n unresolved slugs: {len(unresolved_slugs)}, total $ at risk (cost basis): {unresolved_cost.sum():.2f}")

# =========================================================================
# Working capital: max intraday cumulative outstanding cost
# Approximate: for each slug, capital is "outstanding" from first fill timestamp
# until slot_start + window_s (resolution time). Build an event timeline of
# +cost at fill time, -cost at resolution time, take running max.
# =========================================================================
window_s_map = {"5m": 300, "15m": 900}
fills["window_s"] = fills["tf"].map(window_s_map)
fills["resolve_ts"] = fills["slot_start"] + fills["window_s"]

events = []
for _, row in fills.iterrows():
    events.append((row["timestamp"], row["cost"]))          # capital deployed
    events.append((row["resolve_ts"], -row["cost"]))          # capital returned at resolution
events.sort(key=lambda x: x[0])

running = 0.0
peak = 0.0
peak_ts = None
for ts, delta in events:
    running += delta
    if running > peak:
        peak = running
        peak_ts = ts

print(f"\n=== WORKING CAPITAL ===")
print(f"peak outstanding cost (approx working capital): ${peak:.2f} at ts={peak_ts}")
print(f"(assumes capital freed exactly at slot_start + window_s; real freed-at redemption may lag)")

# Save a small json summary too
summary = {
    "n_slugs_total": int(n_total_slugs),
    "n_slugs_resolved": int(n_resolved_slugs),
    "n_slugs_unresolved": int(n_unresolved_slugs),
    "unresolved_cost_at_risk": float(unresolved_cost.sum()) if len(unresolved_cost) else 0.0,
    "window_hours": float(n_hours),
    "window_total_gross": float(window_total_gross),
    "window_total_fee": float(window_total_fee),
    "window_total_fee_adj": float(window_total_feeadj),
    "extrapolated_per_day_gross": float(window_total_gross / n_hours * 24),
    "extrapolated_per_day_fee_adj": float(window_total_feeadj / n_hours * 24),
    "per_slug_mean": float(per_slug["pnl_fee_adj"].mean()),
    "per_slug_median": float(per_slug["pnl_fee_adj"].median()),
    "per_slug_p10": float(per_slug["pnl_fee_adj"].quantile(0.1)),
    "per_slug_p90": float(per_slug["pnl_fee_adj"].quantile(0.9)),
    "win_slug_count": int(len(win_slugs)),
    "loss_slug_count": int(len(loss_slugs)),
    "peak_working_capital": float(peak),
}
with open(f"{CACHE}\\pnl_summary_2026_07_02.json", "w") as f:
    json.dump(summary, f, indent=2)
print(f"\nsaved summary json -> {CACHE}\\pnl_summary_2026_07_02.json")
