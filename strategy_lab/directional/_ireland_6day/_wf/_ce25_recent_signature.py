"""
Compute strategy signature for wallet 0xce25e214... from recent trades pull
(2026-07-02, API depth-limited to ~3500 rows / ~8.5h back).
"""
import pandas as pd
import numpy as np
import re
import datetime as dt

CSV = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache\0xce25e214\trades_recent_2026_07_02.csv"
ACT_CSV = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache\0xce25e214\activity_recent_2026_07_02.csv"

df = pd.read_csv(CSV)
df = df.drop_duplicates(subset=["transactionHash", "asset", "side", "price", "size", "timestamp"])
df["dt"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
df["date"] = df["dt"].dt.date
df["usd"] = df["price"] * df["size"]

print("=== BASIC ===")
print("n fills (deduped):", len(df))
print("date range:", df["dt"].min(), "->", df["dt"].max())
print("n distinct slugs:", df["slug"].nunique())
print()

# parse slug: {coin}-updown-{tf}-{slot_start_s}
def parse_slug(slug):
    m = re.match(r"([a-z]+)-updown-(\d+[a-z]+)-(\d+)", str(slug))
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    return None, None, None

parsed = df["slug"].apply(parse_slug)
df["coin"] = parsed.apply(lambda x: x[0])
df["tf"] = parsed.apply(lambda x: x[1])
df["slot_start"] = parsed.apply(lambda x: x[2])
df["sec_from_open"] = df["timestamp"] - df["slot_start"]

print("=== NON-STANDARD SLUGS (parse failures) ===")
bad = df[df["coin"].isna()]
print("n unparsed:", len(bad), bad["slug"].unique()[:10] if len(bad) else [])
print()

print("=== PER-DAY TABLE ===")
daily = df.groupby("date").agg(
    n_fills=("timestamp", "count"),
    n_slugs=("slug", "nunique"),
    usd_volume=("usd", "sum"),
    n_buy=("side", lambda s: (s == "BUY").sum()),
    n_sell=("side", lambda s: (s == "SELL").sum()),
)
print(daily.to_string())
print()

print("=== MARKET MIX (coin x timeframe) ===")
mix = df.groupby(["coin", "tf"]).size().unstack(fill_value=0)
print(mix.to_string())
print()
print("coin totals:\n", df["coin"].value_counts())
print("tf totals:\n", df["tf"].value_counts())
print()

print("=== BUY vs SELL ===")
side_counts = df["side"].value_counts()
print(side_counts)
pct_sell = 100 * side_counts.get("SELL", 0) / len(df)
print(f"% sell fills: {pct_sell:.2f}%")
print()

print("=== PER-SLUG PAIR ANALYSIS (BUY fills only) ===")
buys = df[df["side"] == "BUY"].copy()
grp = buys.groupby(["slug", "outcome"]).agg(cost=("usd", "sum"), shares=("size", "sum")).reset_index()
piv_cost = grp.pivot(index="slug", columns="outcome", values="cost").fillna(0)
piv_sh = grp.pivot(index="slug", columns="outcome", values="shares").fillna(0)
for col in ["Up", "Down"]:
    if col not in piv_cost.columns:
        piv_cost[col] = 0.0
    if col not in piv_sh.columns:
        piv_sh[col] = 0.0

slug_tbl = pd.DataFrame({
    "cost_up": piv_cost["Up"],
    "cost_dn": piv_cost["Down"],
    "sh_up": piv_sh["Up"],
    "sh_dn": piv_sh["Down"],
})
slug_tbl["avg_px_up"] = np.where(slug_tbl["sh_up"] > 0, slug_tbl["cost_up"] / slug_tbl["sh_up"], np.nan)
slug_tbl["avg_px_dn"] = np.where(slug_tbl["sh_dn"] > 0, slug_tbl["cost_dn"] / slug_tbl["sh_dn"], np.nan)
slug_tbl["paired_sh"] = np.minimum(slug_tbl["sh_up"], slug_tbl["sh_dn"])
slug_tbl["max_sh"] = np.maximum(slug_tbl["sh_up"], slug_tbl["sh_dn"])
slug_tbl["pair_fraction"] = np.where(slug_tbl["max_sh"] > 0, slug_tbl["paired_sh"] / slug_tbl["max_sh"], np.nan)
slug_tbl["both_sides"] = (slug_tbl["sh_up"] > 0) & (slug_tbl["sh_dn"] > 0)
slug_tbl["pvs"] = slug_tbl["avg_px_up"] + slug_tbl["avg_px_dn"]  # paired vwap sum

n_slugs_bought = len(slug_tbl)
n_both = slug_tbl["both_sides"].sum()
print(f"n slugs with >=1 BUY: {n_slugs_bought}")
print(f"n slugs with BOTH sides bought: {n_both} ({100*n_both/n_slugs_bought:.1f}%)")
print()
print("pair_fraction stats (all slugs w/ buys):")
print(slug_tbl["pair_fraction"].describe())
print()
both_tbl = slug_tbl[slug_tbl["both_sides"]]
print(f"pvs (paired vwap sum) stats, n={len(both_tbl)}:")
print(both_tbl["pvs"].describe())
print("median pvs:", both_tbl["pvs"].median())
print("% slugs with pvs < 1.0 (arb-priced):", 100 * (both_tbl["pvs"] < 1.0).mean())
print("% slugs with pvs < 0.97:", 100 * (both_tbl["pvs"] < 0.97).mean())
print()

print("=== ENTRY TIMING (BUY fills, seconds from window open) ===")
timing = buys["sec_from_open"]
print(timing.describe())
print("p10/p50/p90:", timing.quantile([0.1, 0.5, 0.9]).to_dict())
print("% within first 60s:", 100 * (timing <= 60).mean())
print("% within first 30s:", 100 * (timing <= 30).mean())
print("% within first 120s:", 100 * (timing <= 120).mean())
print()

print("=== SELL FILLS (pre-resolution exits) ===")
sells = df[df["side"] == "SELL"]
print(f"n sell fills: {len(sells)} ({pct_sell:.2f}% of all fills)")
if len(sells):
    print("sell timing (sec_from_open) stats:")
    print(sells["sec_from_open"].describe())
    print("sell coin/tf mix:\n", sells.groupby(["coin", "tf"]).size())
print()

print("=== CLIP SIZING ===")
print("per-fill usd size distribution (all fills):")
print(df["usd"].describe())
print("per-fill usd size distribution (BUY only):")
print(buys["usd"].describe())
print()
per_slug_side_usd = buys.groupby(["slug", "outcome"])["usd"].sum()
print("per-slug per-side total $ distribution:")
print(per_slug_side_usd.describe())
print()
print("n fills per slug distribution:")
fills_per_slug = df.groupby("slug").size()
print(fills_per_slug.describe())
print()

# ---- Activity / REDEEM ----
print("=== ACTIVITY / REDEEM ===")
try:
    act = pd.read_csv(ACT_CSV)
    act["dt"] = pd.to_datetime(act["timestamp"], unit="s", utc=True)
    print("activity type counts:\n", act["type"].value_counts())
    redeems = act[act["type"] == "REDEEM"]
    print(f"n REDEEM events: {len(redeems)}")
    if len(redeems):
        # usdcSize or size*price fallback
        if "usdcSize" in redeems.columns:
            redeem_usd = redeems["usdcSize"].sum()
        else:
            redeem_usd = (redeems["size"] * redeems.get("price", 1)).sum()
        print(f"total REDEEM $ (within pulled window): {redeem_usd:.2f}")
        print("REDEEM window:", redeems["dt"].min(), "->", redeems["dt"].max())
except Exception as e:
    print("activity load error:", e)

print()
print("=== SUMMARY FOR COMPARISON TO OLD SIGNATURE (2026-06-12 decode) ===")
print(f"OLD: 99.5% slugs paired, 78% entries <60s, ~486 slugs/day")
print(f"NEW: {100*n_both/n_slugs_bought:.1f}% slugs both-sides, "
      f"{100*(timing<=60).mean():.1f}% entries <60s, "
      f"{daily['n_slugs'].mean():.1f} avg slugs/day (partial-day pull, hard API cap ~8.5h)")
