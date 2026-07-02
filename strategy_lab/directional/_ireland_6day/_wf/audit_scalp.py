import json
import pandas as pd
import numpy as np

path = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\directional\_ireland_6day\vps3_scalp_exits_clean.tsv"

rows = []
skipped = 0
with open(path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            skipped += 1
            continue
        at, js = parts
        if js.strip() == "SET":
            skipped += 1
            continue
        try:
            d = json.loads(js)
        except Exception as e:
            skipped += 1
            continue
        rows.append((at, d))

print(f"parsed={len(rows)} skipped={skipped}")

# Only keep the actual scalp_exit events (event_type == 'sleeve_scalp_exit')
exits = []
other_event_types = {}
for at, d in rows:
    et = d.get("event_type")
    other_event_types[et] = other_event_types.get(et, 0) + 1
    if et == "sleeve_scalp_exit" and "scalp_exit" in d:
        se = d["scalp_exit"]
        rec = {
            "at": at,
            "slug": d.get("slug"),
            "direction": d.get("direction"),
            "asset": d.get("asset"),
            "tf": d.get("tf"),
            "sleeve_id": d.get("sleeve_id"),
            "fire_us": d.get("fire_us"),
            "book_source": d.get("book_source"),
            "fill_method": d.get("fill_method"),
            "entry_vwap": se.get("entry_vwap"),
            "exit_vwap": se.get("exit_vwap"),
            "shares": se.get("shares"),
            "scalp_pnl_usd": se.get("scalp_pnl_usd"),
            "exit_trigger": se.get("exit_trigger"),
            "delta_bps": se.get("delta_bps"),
            "best_bid_at_exit": se.get("best_bid_at_exit"),
            "exit_book_depth": se.get("exit_book_depth"),
            "sell_leg_fee_charged": se.get("sell_leg_fee_charged"),
            "tp_bid": se.get("tp_bid"),
            "stop_bid": se.get("stop_bid"),
            "side": se.get("side"),
        }
        exits.append(rec)

print("event_type counts:", other_event_types)
print(f"n_exits(sleeve_scalp_exit)={len(exits)}")

df = pd.DataFrame(exits)
df.to_csv(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\directional\_ireland_6day\_wf\exits_parsed.csv", index=False)

# (a) pnl formula check
computed = (df["exit_vwap"] - df["entry_vwap"]) * df["shares"]
diff = (computed - df["scalp_pnl_usd"]).abs()
maxdiff = diff.max()
violators = df[diff > 1e-9]
print(f"\n(a) pnl formula maxdiff={maxdiff:.12f}  n_violators(>1e-9)={len(violators)}")
if len(violators):
    print(violators[["slug","direction","entry_vwap","exit_vwap","shares","scalp_pnl_usd"]])

# (b) stake distribution
stake = df["shares"] * df["entry_vwap"]
print("\n(b) stake (shares*entry_vwap) stats:")
print(stake.describe())
print("median:", stake.median(), "min:", stake.min(), "max:", stake.max())

# (c) sell_leg_fee_charged total
fee_total = df["sell_leg_fee_charged"].sum()
print(f"\n(c) sell_leg_fee_charged total = {fee_total}")
print(df["sell_leg_fee_charged"].describe())

# (d) exit_trigger distribution
print("\n(d) exit_trigger distribution:")
print(df["exit_trigger"].value_counts(dropna=False))

# (e) entry_vwap < 0.55 always?
bad_entry = df[df["entry_vwap"] >= 0.55]
print(f"\n(e) entry_vwap>=0.55 violations: {len(bad_entry)}")
print("entry_vwap max:", df["entry_vwap"].max(), "min:", df["entry_vwap"].min())
if len(bad_entry):
    print(bad_entry[["slug","direction","entry_vwap"]])

# (f) delta_bps >= 3 always?
bad_delta = df[df["delta_bps"] < 3]
print(f"\n(f) delta_bps<3 violations: {len(bad_delta)}")
print("delta_bps min:", df["delta_bps"].min(), "max:", df["delta_bps"].max())
print(df["delta_bps"].describe())
if len(bad_delta):
    print(bad_delta[["slug","direction","delta_bps"]])

# (g) exit_book_depth vs shares needed
depth_short = df[df["exit_book_depth"] < df["shares"]]
print(f"\n(g) exit_book_depth < shares violations: {len(depth_short)}")
print("exit_book_depth stats:")
print(df["exit_book_depth"].describe())
print("shares stats:")
print(df["shares"].describe())
if len(depth_short):
    print(depth_short[["slug","direction","exit_book_depth","shares"]])

# (h) best_bid_at_exit == exit_vwap always, or walk deeper?
diff_bid_vwap = (df["best_bid_at_exit"] - df["exit_vwap"]).abs()
n_equal = (diff_bid_vwap < 1e-9).sum()
n_walk_deeper = (df["exit_vwap"] < df["best_bid_at_exit"] - 1e-9).sum()  # sold below best bid = walked deeper (worse)
n_better = (df["exit_vwap"] > df["best_bid_at_exit"] + 1e-9).sum()
print(f"\n(h) best_bid_at_exit == exit_vwap: {n_equal}/{len(df)}")
print(f"    exit_vwap < best_bid_at_exit (walked deeper/worse): {n_walk_deeper}")
print(f"    exit_vwap > best_bid_at_exit (better than best bid?!): {n_better}")
print(df[["best_bid_at_exit","exit_vwap"]].describe())

# 3. Duplicates check on (slug, direction)
dupes = df[df.duplicated(subset=["slug","direction"], keep=False)]
print(f"\n(3) duplicate (slug,direction) rows: {len(dupes)}")
if len(dupes):
    print(dupes[["at","slug","direction","scalp_pnl_usd"]].sort_values("slug"))

# 4. PnL distribution + cumulative max drawdown in time order
df["at_dt"] = pd.to_datetime(df["at"], utc=True, format="mixed")
df_sorted = df.sort_values("at_dt").reset_index(drop=True)
pnl = df_sorted["scalp_pnl_usd"]
print("\n(4) PnL distribution:")
print(f"mean={pnl.mean():.4f} median={pnl.median():.4f} p10={pnl.quantile(0.10):.4f} p90={pnl.quantile(0.90):.4f} worst={pnl.min():.4f} best={pnl.max():.4f}")

cum = pnl.cumsum()
running_max = cum.cummax()
drawdown = cum - running_max
max_dd = drawdown.min()
print(f"cumulative PnL final = {cum.iloc[-1]:.4f}")
print(f"max drawdown (cum curve) = {max_dd:.4f}")
dd_idx = drawdown.idxmin()
print(f"max DD occurs at row {dd_idx}, at={df_sorted.loc[dd_idx,'at']}, cum={cum.loc[dd_idx]:.4f}, running_max={running_max.loc[dd_idx]:.4f}")

df_sorted[["at","slug","direction","scalp_pnl_usd"]].assign(cum=cum, running_max=running_max, drawdown=drawdown).to_csv(
    r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\directional\_ireland_6day\_wf\pnl_timeseries.csv", index=False
)

print("\nDONE")
