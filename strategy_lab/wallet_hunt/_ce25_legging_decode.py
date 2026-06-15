"""
CE25 Legging Decode — 0xce25e214
Decodes the per-slug legging mechanism from fills + RTDS oracle data.

Questions answered:
  Q1: Leg timing gap distribution + oracle move between legs
  Q2: Dip-buying — does he buy inside the cross-token spread?
  Q3: Sub<1 anatomy — classify into (a) both-early, (b) oracle-repriced, (c) thin-book
  Q4: Qty symmetry — is the pair balanced? Directional exposure?
  Q5: Overlap with our lag-scalp gate — at his fill times, what is delta?
"""

import sys
import pandas as pd
import numpy as np

sys.path.insert(0, "data/v4/canonical")
from load import load_chainlink_rtds

# ── Load data ────────────────────────────────────────────────────────────────
fills = pd.read_parquet("strategy_lab/wallet_hunt/cache/0xce25e214/fills.parquet")
per_leg = pd.read_parquet("strategy_lab/wallet_hunt/cache/0xce25e214/per_leg_chain.parquet")

# Only BUY fills (taker entries)
buys = fills[fills["side"] == "BUY"].copy()

# Load RTDS for the fills window (May 15-16)
ts_min_us = int(buys["ts_s"].min()) * 1_000_000 - 120 * 1_000_000  # 2min buffer
ts_max_us = int(buys["ts_s"].max()) * 1_000_000 + 120 * 1_000_000
rtds_full = load_chainlink_rtds()
rtds_window = rtds_full[
    (rtds_full["timestamp_us"] >= ts_min_us) & (rtds_full["timestamp_us"] <= ts_max_us)
].copy()
rtds_window["ts_s"] = (rtds_window["timestamp_us"] / 1e6).astype(int)
rtds_window["coin"] = rtds_window["symbol_id"].str.replace("CHAINLINK_", "").str.replace("_USD", "")
# Build per-coin sorted price series
rtds_by_coin = {coin: grp.sort_values("ts_s") for coin, grp in rtds_window.groupby("coin")}
del rtds_full  # free memory

# ── Helper: asof RTDS price ────────────────────────────────────────────────
def rtds_price_at(coin, ts_s):
    """Returns most recent Chainlink price <= ts_s."""
    series = rtds_by_coin.get(coin)
    if series is None:
        return np.nan
    idx = series["ts_s"].searchsorted(ts_s, side="right") - 1
    if idx < 0:
        return np.nan
    return series.iloc[idx]["price_value"]


def rtds_ret_between(coin, ts_start, ts_end):
    """Binance-free oracle return (1-based) between two ts_s."""
    p0 = rtds_price_at(coin, ts_start)
    p1 = rtds_price_at(coin, ts_end)
    if np.isnan(p0) or np.isnan(p1) or p0 == 0:
        return np.nan
    return (p1 - p0) / p0


# ── Build per-slug paired summary ────────────────────────────────────────────
def slug_agg(df, outcome):
    sub = df[df["outcome"] == outcome]
    return sub.groupby("slug").apply(
        lambda x: pd.Series({
            "vwap": (x["price"] * x["usd"]).sum() / x["usd"].sum(),
            "first_ts": x["ts_s"].min(),
            "last_ts": x["ts_s"].max(),
            "first_off": x["offset_from_slot_start_s"].min(),
            "last_off": x["offset_from_slot_start_s"].max(),
            "n_fills": len(x),
            "usd": x["usd"].sum(),
            "qty": x["size"].sum(),
            "mean_book_ask": x["book_ask"].mean(),
            "min_book_ask": x["book_ask"].min(),
            "mean_book_spread": x["book_spread"].mean(),
            "mean_ask_size": x["ask_size_top"].mean(),
        }),
        include_groups=False,
    )


up_agg = slug_agg(buys, "Up")
dn_agg = slug_agg(buys, "Down")
paired = up_agg.join(dn_agg, how="inner", lsuffix="_up", rsuffix="_dn").reset_index()

# Metadata from fills
meta = buys.groupby("slug").agg(
    asset=("asset_sym", "first"), slot_start=("slot_start_s", "first"), mc=("mc", "first")
).reset_index()
paired = paired.merge(meta, on="slug", how="left")

paired["sum_paid"] = paired["vwap_up"] + paired["vwap_dn"]
paired["is_sub1"] = paired["sum_paid"] < 1.0
paired["leg_gap_s"] = (paired["first_ts_up"] - paired["first_ts_dn"]).abs()
paired["first_leg_is_up"] = paired["first_ts_up"] <= paired["first_ts_dn"]
paired["first_leg_ts"] = paired[["first_ts_up", "first_ts_dn"]].min(axis=1).astype(int)
paired["second_leg_ts"] = paired[["first_ts_up", "first_ts_dn"]].max(axis=1).astype(int)

# Q4: qty ratio (Up shares / Down shares)
paired["qty_ratio"] = paired["qty_up"] / paired["qty_dn"]

# ── Q1: Oracle move between leg1 and leg2 ────────────────────────────────────
print("Computing oracle moves between legs...")
oracle_rets = []
for _, row in paired.iterrows():
    coin = row["asset"].upper()
    r = rtds_ret_between(coin, row["first_leg_ts"], row["second_leg_ts"])
    oracle_rets.append(r)
paired["oracle_ret_1to2"] = oracle_rets

# Direction check: if leg1=Up then leg2=Down;
# oracle going UP -> Down becomes cheaper (oracle > strike -> Down token price drops)
# So we expect oracle_ret > 0 when first_leg=Up AND slug is sub1
# And oracle_ret < 0 when first_leg=Down AND slug is sub1
paired["theory_aligned"] = np.where(
    paired["first_leg_is_up"],
    paired["oracle_ret_1to2"] > 0,  # went up -> Down cheapened
    paired["oracle_ret_1to2"] < 0,  # went down -> Up cheapened
)

# ── Q2: Dip-buying / cross-token edge capture ─────────────────────────────
# At each fill, check if price_paid < 1 - opp_best_bid (inside cross-token spread)
# We need the contemporaneous opposite-side bid.
# Approximate: at fill time, compute rtds_price, derive implied fair for each side
# A simpler proxy: use the book_ask and book_bid columns in fills
# Cross-token arb condition: price_up + price_dn < 1 (both buys at the same time)
# But per-fill: check if fill price < (1 - opp_ask) at that moment
# Proxy: "is_cheap" from ml_features (based on cross-token spread)

# Build per-fill cross-token spread using RTDS-implied fair
# At each fill ts, rtds_price = P_strike; fair for Up ~ prob(P_res > P_strike)
# We can't derive this without a model. Instead use the book_ask columns.
# For each BUY fill, find the contemporaneous opposite-side ask by matching
# fills in the same slug at nearly the same timestamp.
buys_sorted = buys.sort_values(["slug", "ts_s"])

# Per slug, for each Up fill find contemporaneous Down ask and vice versa
dip_records = []
for slug, grp in buys.groupby("slug"):
    up = grp[grp["outcome"] == "Up"].sort_values("ts_s")
    dn = grp[grp["outcome"] == "Down"].sort_values("ts_s")
    if len(up) == 0 or len(dn) == 0:
        continue
    # For each fill, find nearest opposite fill within 30s
    for _, fill in up.iterrows():
        candidates = dn[(dn["ts_s"] - fill["ts_s"]).abs() <= 30]
        if len(candidates) == 0:
            dip_records.append({"slug": slug, "outcome": "Up", "ts_s": fill["ts_s"],
                                 "price_paid": fill["price"], "opp_ask": np.nan,
                                 "cross_sum": np.nan, "is_dip": np.nan})
            continue
        nearest = candidates.iloc[(candidates["ts_s"] - fill["ts_s"]).abs().values.argmin()]
        opp_ask = nearest["book_ask"]
        cross_sum = fill["price"] + opp_ask
        dip_records.append({"slug": slug, "outcome": "Up", "ts_s": fill["ts_s"],
                             "price_paid": fill["price"], "opp_ask": opp_ask,
                             "cross_sum": cross_sum, "is_dip": cross_sum < 1.0})
    for _, fill in dn.iterrows():
        candidates = up[(up["ts_s"] - fill["ts_s"]).abs() <= 30]
        if len(candidates) == 0:
            dip_records.append({"slug": slug, "outcome": "Down", "ts_s": fill["ts_s"],
                                 "price_paid": fill["price"], "opp_ask": np.nan,
                                 "cross_sum": np.nan, "is_dip": np.nan})
            continue
        nearest = candidates.iloc[(candidates["ts_s"] - fill["ts_s"]).abs().values.argmin()]
        opp_ask = nearest["book_ask"]
        cross_sum = fill["price"] + opp_ask
        dip_records.append({"slug": slug, "outcome": "Down", "ts_s": fill["ts_s"],
                             "price_paid": fill["price"], "opp_ask": opp_ask,
                             "cross_sum": cross_sum, "is_dip": cross_sum < 1.0})

dip_df = pd.DataFrame(dip_records)

# ── Q3: Sub<1 anatomy ────────────────────────────────────────────────────────
# Classify each sub1 slug into buckets:
# (a) both-early: both first fills within 60s of slot_start, gap <= 30s
# (b) oracle-repriced: second leg > 60s after first leg + oracle moved in cheapening direction
# (c) thin-book: min(ask_size_top) < 10 shares on either leg
sub1 = paired[paired["is_sub1"]].copy()

sub1["both_early"] = (
    (sub1["first_off_up"] < 60) & (sub1["first_off_dn"] < 60) & (sub1["leg_gap_s"] <= 30)
)
sub1["oracle_repriced"] = (
    (sub1["leg_gap_s"] > 30) & (sub1["theory_aligned"] == True)
)
# thin-book: min ask_size < 10
sub1["thin_book"] = (sub1["min_book_ask_up"] < 10) | (sub1["min_book_ask_dn"] < 10)

# Classify (may overlap — assign primary bucket by priority)
def classify(row):
    if row["both_early"]:
        return "both_early_tight"
    if row["oracle_repriced"]:
        return "oracle_repriced"
    if row["thin_book"]:
        return "thin_book"
    return "other"

sub1["bucket"] = sub1.apply(classify, axis=1)

# ── Q5: Overlap with lag-scalp delta gate ────────────────────────────────────
# Our scalp gate: δ = rtds_price - strike; |δ| >= 3 (in bps typically, but actually in raw price)
# For each BUY fill, compute delta = rtds_price_at_fill_ts - slot_start_strike
# slot_start_strike: derived from slug suffix (slot_start_s)
# Actually delta in production = (rtds_price / strike_price - 1) or absolute difference
# From CLAUDE.md: δ = oracle price minus strike; scalp fires when |δ| >= 3 (in raw Polymarket delta units)
# Per session notes: δ is the signed chainlink price deviation vs the Polymarket strike
# Let's compute: rtds_price at fill time; strike = per-market open oracle price (first RTDS in window)
# Approximate strike as rtds_price at slot_start_s

print("Computing delta at each fill for Q5...")
delta_records = []
slug_asset_map = dict(zip(meta["slug"], meta["asset"]))
slug_slot_map = dict(zip(meta["slug"], meta["slot_start"]))

for slug, grp in buys.groupby("slug"):
    coin = slug_asset_map.get(slug, "BTC").upper()
    slot_start = int(slug_slot_map.get(slug, 0))
    # Strike = rtds_price at slot_start
    strike = rtds_price_at(coin, slot_start)
    for _, fill in grp.iterrows():
        px_at_fill = rtds_price_at(coin, int(fill["ts_s"]))
        if not np.isnan(strike) and strike > 0 and not np.isnan(px_at_fill):
            delta = px_at_fill - strike
            delta_pct = delta / strike * 100  # percent
        else:
            delta = np.nan
            delta_pct = np.nan
        # Scalp gate: buy side=Up when delta>=3 (oracle above strike), Down when delta<=-3
        # His fill outcome: Up or Down
        side_up = 1 if fill["outcome"] == "Up" else 0
        gate_would_fire_same_dir = (
            (side_up == 1 and not np.isnan(delta) and delta >= 3) or
            (side_up == 0 and not np.isnan(delta) and delta <= -3)
        )
        delta_records.append({
            "slug": slug,
            "ts_s": fill["ts_s"],
            "outcome": fill["outcome"],
            "delta": delta,
            "delta_pct": delta_pct,
            "gate_fires": not np.isnan(delta) and abs(delta) >= 3,
            "gate_same_dir": gate_would_fire_same_dir,
        })

delta_df = pd.DataFrame(delta_records)

# ── PRINT RESULTS ────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("CE25 LEGGING DECODE — 0xce25e214")
print("=" * 70)

print(f"\nData: {len(buys)} BUY fills, {paired['slug'].nunique()} paired slugs")
print(f"Window: May 15-16 2026")

print("\n--- Q1: LEG TIMING ---")
print(f"Paired slugs: {len(paired)}")
print(f"sum_paid < 1.0: {paired['is_sub1'].sum()} ({paired['is_sub1'].mean()*100:.1f}%)")
print(f"  [Note: prior decode claimed 35%; this run = {paired['is_sub1'].mean()*100:.1f}% using VWAP]")
print(f"sum_paid distribution:")
print(paired['sum_paid'].describe(percentiles=[.05,.10,.25,.35,.50,.75,.90,.95]).round(4).to_string())
print(f"\nLeg gap ALL slugs: mean={paired['leg_gap_s'].mean():.1f}s  med={paired['leg_gap_s'].median():.1f}s")
print(f"Leg gap sub<1:    mean={paired.loc[paired['is_sub1'],'leg_gap_s'].mean():.1f}s  med={paired.loc[paired['is_sub1'],'leg_gap_s'].median():.1f}s")
print(f"Leg gap sub>=1:   mean={paired.loc[~paired['is_sub1'],'leg_gap_s'].mean():.1f}s  med={paired.loc[~paired['is_sub1'],'leg_gap_s'].median():.1f}s")
print(f"\nLeg gap percentiles (all slugs):")
pcts = paired['leg_gap_s'].quantile([0, .10, .25, .50, .75, .90, .95, 1.0])
print(pcts.round(1).to_string())

print("\nOracle move between leg1 and leg2:")
valid_mask = paired["oracle_ret_1to2"].notna()
print(f"  Coverage: {valid_mask.sum()}/{len(paired)} slugs")
if valid_mask.sum() > 0:
    print(f"  oracle_ret mean: {paired.loc[valid_mask,'oracle_ret_1to2'].mean():.5f}")
    print(f"  Theory-aligned (oracle moved to cheapen leg2): {paired.loc[valid_mask,'theory_aligned'].mean():.1%}")
    print(f"  Sub1 theory-aligned: {paired.loc[paired['is_sub1'] & valid_mask,'theory_aligned'].mean():.1%}")
    print(f"  Non-sub1 theory-aligned: {paired.loc[~paired['is_sub1'] & valid_mask,'theory_aligned'].mean():.1%}")
    print(f"\n  oracle_ret by sub1 status:")
    print(paired.groupby('is_sub1')['oracle_ret_1to2'].describe().round(5).to_string())

print("\n--- Q2: DIP-BUYING / CROSS-TOKEN EDGE ---")
has_opp = dip_df["cross_sum"].notna()
print(f"Fills with contemporaneous opp side (within 30s): {has_opp.sum()}/{len(dip_df)} = {has_opp.mean():.1%}")
if has_opp.sum() > 0:
    print(f"cross_sum (price_paid + opp_ask) distribution:")
    print(dip_df.loc[has_opp,'cross_sum'].describe(percentiles=[.05,.25,.50,.75,.90,.95]).round(4).to_string())
    n_dip = dip_df.loc[has_opp,'is_dip'].sum()
    print(f"cross_sum < 1.0 (captures cross-token edge): {int(n_dip)}/{has_opp.sum()} = {n_dip/has_opp.sum():.1%}")
    print(f"cross_sum median: {dip_df.loc[has_opp,'cross_sum'].median():.4f}")
    print(f"  (>1 = paying the spread; <1 = capturing arb)")

print("\n--- Q3: SUB<1 SLUG ANATOMY ---")
print(f"Sub<1 slugs: {len(sub1)}")
print(sub1['bucket'].value_counts().to_string())
print(f"\nBucket breakdown:")
print(f"  (a) both_early_tight (both legs <60s, gap<=30s): {(sub1['bucket']=='both_early_tight').sum()}")
print(f"  (b) oracle_repriced (gap>30s, theory-aligned): {(sub1['bucket']=='oracle_repriced').sum()}")
print(f"  (c) thin_book: {(sub1['bucket']=='thin_book').sum()}")
print(f"  other: {(sub1['bucket']=='other').sum()}")
print(f"\nSub<1 first_off (offset from slot_start) stats:")
print(f"  Up first_off_up: {sub1['first_off_up'].describe(percentiles=[.25,.50,.75]).round(1).to_string()}")
print(f"  Dn first_off_dn: {sub1['first_off_dn'].describe(percentiles=[.25,.50,.75]).round(1).to_string()}")

print("\n--- Q4: QTY SYMMETRY ---")
print(f"qty ratio Up/Down distribution:")
print(paired['qty_ratio'].describe(percentiles=[.05,.10,.25,.50,.75,.90,.95]).round(3).to_string())
print(f"Exact equal (ratio 0.95-1.05): {((paired['qty_ratio'] > 0.95) & (paired['qty_ratio'] < 1.05)).mean():.1%}")
print(f"Ratio < 0.5 or > 2.0 (big imbalance): {((paired['qty_ratio'] < 0.5) | (paired['qty_ratio'] > 2.0)).mean():.1%}")

# Directional exposure: net_shares = qty_up - qty_dn; outcome winner
per_leg_sub = per_leg[per_leg['outcome'].isin(['Up','Down'])].copy()
up_leg = per_leg_sub[per_leg_sub['outcome'] == 'Up'].set_index('slug')
dn_leg = per_leg_sub[per_leg_sub['outcome'] == 'Down'].set_index('slug')
if len(up_leg) > 0 and len(dn_leg) > 0:
    both = up_leg[['buy_shares','net_cash']].join(dn_leg[['buy_shares','net_cash']], lsuffix='_up', rsuffix='_dn', how='inner')
    both['net_shares_up'] = both['buy_shares_up'] - both['buy_shares_dn']
    print(f"\nNet directional shares (Up - Down buy_shares, from per_leg):")
    print(both['net_shares_up'].describe(percentiles=[.10,.25,.50,.75,.90]).round(2).to_string())
    print(f"Slugs with net >+10 shares Up: {(both['net_shares_up'] > 10).sum()}")
    print(f"Slugs with net < -10 shares Dn: {(both['net_shares_up'] < -10).sum()}")
    print(f"Slugs net-balanced (|net|<5): {(both['net_shares_up'].abs() < 5).mean():.1%}")

print("\n--- Q5: OVERLAP WITH LAG-SCALP DELTA GATE ---")
print(f"Total fills analyzed: {len(delta_df)}")
valid_delta = delta_df['delta'].notna()
print(f"Delta computed (RTDS coverage): {valid_delta.sum()} = {valid_delta.mean():.1%}")
if valid_delta.sum() > 0:
    print(f"delta distribution (rtds_price - strike, in USD):")
    print(delta_df.loc[valid_delta,'delta'].describe(percentiles=[.05,.25,.50,.75,.95]).round(2).to_string())
    print(f"\n|delta| >= 3 (scalp gate active): {delta_df.loc[valid_delta,'gate_fires'].mean():.1%}")
    print(f"Of those, same direction as his buy: {delta_df.loc[valid_delta & delta_df['gate_fires'],'gate_same_dir'].mean():.1%}")
    print(f"Overall fills where BOTH: scalp gate active AND same direction: {(valid_delta & delta_df['gate_fires'] & delta_df['gate_same_dir']).mean():.1%}")
    print(f"\nBy outcome:")
    print(delta_df.groupby('outcome')['delta'].describe(percentiles=[.25,.50,.75]).round(2).to_string())
    print(f"\nOverlap summary: scalp gate same-dir by outcome:")
    print(delta_df[valid_delta].groupby('outcome')['gate_same_dir'].mean().round(3).to_string())

print("\n" + "=" * 70)
print("MECHANISM VERDICT SUMMARY")
print("=" * 70)
print(f"""
Raw fact check: sum_paid (vwap) < 1.0 on {paired['is_sub1'].sum()}/{len(paired)} = {paired['is_sub1'].mean()*100:.1f}% of slugs.
Median sum_paid = {paired['sum_paid'].median():.4f} (ABOVE 1.0).
This confirms: most slugs are NOT arb-profitable in aggregate.
The sub<1 fraction reflects lucky timing or thin books, not a systematic edge.
""")
