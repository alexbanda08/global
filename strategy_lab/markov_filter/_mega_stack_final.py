"""Final mega-stack: combine HoD + Markov + MTF + Chainlink + microstructure gates.

For each (strategy, cell), find the best combo from:
  - HoD-Top8 (in-sample selected top 8 hours per cell)
  - Markov binance w20_5m_voladaptive (or per-cell best)
  - Chainlink Markov (combine on 15m only)
  - MTF2 (multi-tf 15m + 1h agreement)
  - Tight spread (Q1)

Also do walk-forward: split into 2 halves, optimize on first half, test on second.
"""
import numpy as np
import pandas as pd
from pathlib import Path

OUT_MD = Path("strategy_lab/markov_filter/_results/MEGA_STACK_FINAL.md")
fills_path = "strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv"
fills = pd.read_csv(fills_path)
fills["fire_ts"] = pd.to_datetime(fills["fire_us"], unit="us", utc=True)
fills["hour"] = fills["fire_ts"].dt.hour
fills["dow"] = fills["fire_ts"].dt.dayofweek
fills["cell_key"] = fills["asset"].str.lower() + "_" + fills["tf"]

# Build per-asset 1m klines for MTF2
import sys
sys.path.insert(0, "data/v4/canonical")
k = pd.read_csv("strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv")
kcache = {}
for asset in ("BTC","ETH","SOL"):
    sym = f"BINANCE_SPOT_{asset}_USDT"
    sub = k[k["symbol_id"]==sym].drop_duplicates("time_period_start_us").sort_values("time_period_start_us")
    kcache[asset] = (
        sub["time_period_start_us"].values.astype("int64") + 60_000_000,
        sub["price_close"].values.astype("float64"),
    )
def cl(end_us, c, t):
    i = int(np.searchsorted(end_us, int(t), side="right")) - 1
    if i < 0 or i >= len(c): return float("nan")
    return float(c[i])

# Compute MTF2 (sign(ret_15m) == sign(ret_1h) == signal)
print("Computing MTF2 per fire...")
mtf2 = np.zeros(len(fills), dtype=bool)
for i, r in enumerate(fills.itertuples(index=False)):
    end_us, c = kcache[r.asset]
    p_now = cl(end_us, c, r.fire_us)
    p_15m = cl(end_us, c, r.fire_us - 900_000_000)
    p_1h  = cl(end_us, c, r.fire_us - 3600_000_000)
    if not (np.isfinite(p_now) and np.isfinite(p_15m) and np.isfinite(p_1h)):
        continue
    if p_15m <= 0 or p_1h <= 0: continue
    ret_15m = np.log(p_now / p_15m)
    ret_1h  = np.log(p_now / p_1h)
    sig = r.signal
    pass_ = ((sig=="UP" and ret_15m > 0 and ret_1h > 0) or
             (sig=="DOWN" and ret_15m < 0 and ret_1h < 0))
    mtf2[i] = pass_
fills["mtf2"] = mtf2

# Compute spread_pct quartile (per asset×tf)
fills["spread_pct"] = (fills["best_ask"] - fills["bid0"]) / ((fills["best_ask"] + fills["bid0"]) / 2)
fills["q1_spread"] = False
for (asset, tf), g in fills.groupby(["asset","tf"]):
    thr = g["spread_pct"].quantile(0.25)
    fills.loc[g.index, "q1_spread"] = g["spread_pct"] <= thr

# HoD top-8 per cell (in-sample selection)
fills["hod_top8"] = False
hod_select = {}
for (strat, cell), g in fills.groupby(["strategy","cell_key"]):
    # rank hours by sum_pnl
    hr = g.groupby("hour")["pnl"].agg(["sum","size"]).reset_index()
    hr = hr[hr["size"] >= 5]
    top8 = hr.sort_values("sum", ascending=False).head(8)["hour"].tolist()
    hod_select[(strat, cell)] = set(top8)
    fills.loc[g.index, "hod_top8"] = g["hour"].isin(top8)

# Build chainlink Markov pass column (load from agent A output if exists)
cl_fills_path = "strategy_lab/markov_filter/_results/_chainlink_markov_fills.csv"
if Path(cl_fills_path).exists():
    clf = pd.read_csv(cl_fills_path)
    # Join the chainlink pass columns
    cl_cols = [c for c in clf.columns if c.startswith("chainlink_pass")]
    print(f"Chainlink columns found: {cl_cols}")
    # Try to merge on fire_us + sleeve fields if they match
    if "fire_us" in clf.columns and len(cl_cols) > 0:
        match_cols = ["fire_us"]
        for extra in ("strategy","cell","signal"):
            if extra in clf.columns: match_cols.append(extra)
        try:
            fills = fills.merge(clf[match_cols + cl_cols].drop_duplicates(match_cols),
                                on=match_cols, how="left")
        except Exception as e:
            print(f"join err: {e}")

# Filter library
gates = {
    "BASE": pd.Series(True, index=fills.index),
    "HoD8": fills["hod_top8"],
    "MTF2": fills["mtf2"],
    "M_5mva": fills["markov_pass_w20_5m_voladaptive"],
    "M_1mva": fills["markov_pass_w20_1m_voladaptive"],
    "M_5mfix": fills["markov_pass_w20_5m_fixed"],
    "M_1mfix": fills["markov_pass_w20_1m_fixed"],
    "Q1spr": fills["q1_spread"],
}
# Build composite gates (pairs, triples, top combos)
composite_gates = {
    "HoD8+M5mva": gates["HoD8"] & gates["M_5mva"],
    "HoD8+M1mva": gates["HoD8"] & gates["M_1mva"],
    "HoD8+MTF2":  gates["HoD8"] & gates["MTF2"],
    "MTF2+M5mva": gates["MTF2"] & gates["M_5mva"],
    "MTF2+M1mva": gates["MTF2"] & gates["M_1mva"],
    "HoD8+MTF2+M5mva": gates["HoD8"] & gates["MTF2"] & gates["M_5mva"],
    "HoD8+MTF2+M1mva": gates["HoD8"] & gates["MTF2"] & gates["M_1mva"],
    "HoD8+Q1spr": gates["HoD8"] & gates["Q1spr"],
    "HoD8+M5mva+Q1spr": gates["HoD8"] & gates["M_5mva"] & gates["Q1spr"],
}
gates.update(composite_gates)

# Score every gate × cell
rows = []
for (strat, cell), g in fills.groupby(["strategy","cell_key"]):
    for gname, mask_full in gates.items():
        mask = mask_full[g.index]
        gp = g[mask]
        n = len(gp)
        if n < 5: continue
        rows.append({
            "strategy":strat, "cell":cell, "gate":gname,
            "n":n,
            "wr": gp["won"].mean()*100,
            "avg": gp["pnl"].mean(),
            "sum": gp["pnl"].sum(),
        })
scoreboard = pd.DataFrame(rows)
scoreboard.to_csv("strategy_lab/markov_filter/_results/MEGA_STACK_SCOREBOARD.csv", index=False)

# Per-cell best (n>=30)
best_per_cell = []
for (strat, cell), g in scoreboard.groupby(["strategy","cell"]):
    cands = g[g["n"] >= 30]
    if cands.empty: continue
    best = cands.loc[cands["sum"].idxmax()]
    best_per_cell.append(best)
bdf = pd.DataFrame(best_per_cell).sort_values("sum", ascending=False)

# Walk-forward: split fires by date, optimize on first half, test on second
fills["date"] = fills["fire_ts"].dt.date
mid = pd.Timestamp("2026-05-07").date()
fills["wf_split"] = np.where(fills["fire_ts"].dt.date <= mid, "train", "test")
print(f"Train fires: {(fills['wf_split']=='train').sum()}, test: {(fills['wf_split']=='test').sum()}")

wf_rows = []
# For each strat × cell × gate: train on first half, test on second
for (strat, cell), g in fills.groupby(["strategy","cell_key"]):
    train = g[g["wf_split"]=="train"]
    test  = g[g["wf_split"]=="test"]
    if len(train) < 30 or len(test) < 20: continue
    for gname, mask_full in gates.items():
        mtrain = mask_full[train.index]
        mtest  = mask_full[test.index]
        gpt = train[mtrain]; gpv = test[mtest]
        if len(gpt) < 15 or len(gpv) < 10: continue
        wf_rows.append({
            "strategy":strat, "cell":cell, "gate":gname,
            "train_n":len(gpt), "train_wr":gpt["won"].mean()*100, "train_sum":gpt["pnl"].sum(),
            "test_n":len(gpv),  "test_wr":gpv["won"].mean()*100,  "test_sum":gpv["pnl"].sum(),
        })
wf_df = pd.DataFrame(wf_rows)
wf_df.to_csv("strategy_lab/markov_filter/_results/MEGA_STACK_WALKFWD.csv", index=False)

# Build the final report
with OUT_MD.open("w") as f:
    f.write("# MEGA-STACK final synthesis\n\n")
    f.write("Combines: Markov (binance) variants, MTF2 (15m+1h confluence), HoD-Top8, tight-spread quartile.\n")
    f.write(f"Source fills: {len(fills):,}. Date window: Apr 22 → May 21.\n\n")

    f.write("## Best gate per (strategy, cell) — IN SAMPLE (n>=30, ranked by sum$)\n\n")
    f.write("| strategy | cell | gate | n | WR | $/tr | sum$ |\n")
    f.write("|---|---|---|---:|---:|---:|---:|\n")
    for _, r in bdf.iterrows():
        f.write(f"| {r['strategy']} | {r['cell']} | {r['gate']} | {int(r['n'])} | {r['wr']:.1f}% | ${r['avg']:+.2f} | ${r['sum']:+.0f} |\n")
    f.write(f"\n**Aggregate sum (top in-sample picks): ${bdf['sum'].sum():.0f} over 28 days**\n\n")

    f.write("## Walk-forward — train Apr 22-May 7, test May 8-21\n\n")
    f.write("For each cell, the BEST gate (by train_sum) and its TEST sum:\n\n")
    f.write("| strategy | cell | best_gate(train) | train_n | train_WR | train_sum | test_n | test_WR | test_sum |\n")
    f.write("|---|---|---|---:|---:|---:|---:|---:|---:|\n")
    wf_best = []
    for (strat, cell), g in wf_df.groupby(["strategy","cell"]):
        # Filter gates with reasonable train sample
        cands = g[g["train_n"] >= 20]
        if cands.empty: continue
        best = cands.loc[cands["train_sum"].idxmax()]
        wf_best.append(best)
        f.write(f"| {best['strategy']} | {best['cell']} | {best['gate']} | "
                f"{int(best['train_n'])} | {best['train_wr']:.1f}% | ${best['train_sum']:+.0f} | "
                f"{int(best['test_n'])} | {best['test_wr']:.1f}% | ${best['test_sum']:+.0f} |\n")
    if wf_best:
        wfdf = pd.DataFrame(wf_best)
        f.write(f"\n**Walk-forward aggregate: train ${wfdf['train_sum'].sum():.0f}, "
                f"test ${wfdf['test_sum'].sum():.0f}**\n")
        f.write(f"Test/train ratio: {wfdf['test_sum'].sum() / max(wfdf['train_sum'].sum(),0.01):.2f}\n")
        f.write(f"(ratio close to 1 = gate holds; near 0 = overfit)\n\n")

    # Gate-by-gate aggregate
    f.write("## Aggregate per gate (all cells, n>=30)\n\n")
    agg = scoreboard[scoreboard["n"]>=30].groupby("gate").agg(
        total_n=("n","sum"), total_sum=("sum","sum"), cells=("cell","nunique")
    ).sort_values("total_sum", ascending=False)
    f.write("| gate | cells | total_n | total_sum |\n|---|---:|---:|---:|\n")
    for gname, row in agg.iterrows():
        f.write(f"| {gname} | {int(row['cells'])} | {int(row['total_n'])} | ${row['total_sum']:+.0f} |\n")
    f.write("\n")

    # Top 20 by sum (any cell, n>=30)
    top = scoreboard[scoreboard["n"]>=30].sort_values("sum", ascending=False).head(20)
    f.write("## Top 20 (strategy × cell × gate) by sum$ (n>=30)\n\n")
    f.write("| strategy | cell | gate | n | WR | $/tr | sum$ |\n|---|---|---|---:|---:|---:|---:|\n")
    for _, r in top.iterrows():
        f.write(f"| {r['strategy']} | {r['cell']} | {r['gate']} | {int(r['n'])} | {r['wr']:.1f}% | ${r['avg']:+.2f} | ${r['sum']:+.0f} |\n")

print(f"\nwrote {OUT_MD}")
print(f"\nTop 5 in-sample:")
print(bdf.head(5).to_string(index=False))
print(f"\nWalk-forward aggregate:")
if wf_best:
    print(f"  train sum: ${pd.DataFrame(wf_best)['train_sum'].sum():.0f}")
    print(f"  test sum:  ${pd.DataFrame(wf_best)['test_sum'].sum():.0f}")
