"""Microstructure gate analysis on fills.csv (no L25 re-load).

Features from existing columns:
  spread_pct = (best_ask - bid0) / mid
  best_ask (price level)
  vwap_slippage = vwap - best_ask
  log_shares = log(shares)

Test per-cell quartile WR; build "best quartile" gates; combine with Markov.
"""
import numpy as np
import pandas as pd
from pathlib import Path

OUT_MD = Path("strategy_lab/markov_filter/_results/BOOK_MICROSTRUCTURE_GATES.md")
fills = pd.read_csv("strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv")
print(f"Loaded {len(fills)} fills")

# Features
fills["spread_pct"] = (fills["best_ask"] - fills["bid0"]) / ((fills["best_ask"] + fills["bid0"]) / 2)
fills["vwap_slip"] = fills["vwap"] - fills["best_ask"]
fills["log_shares"] = np.log(fills["shares"].clip(lower=0.001))
fills["cell_key"] = fills["asset"].str.lower() + "_" + fills["tf"]

with OUT_MD.open("w") as f:
    f.write("# Book microstructure gates — inline analysis\n\n")
    f.write(f"Date: 2026-05-22, fills: {len(fills):,}\n\n")
    f.write("Features:\n- spread_pct = (best_ask - bid0) / mid\n")
    f.write("- best_ask\n- vwap_slip = vwap - best_ask\n- log_shares\n\n")

    # 1. Distribution per asset
    f.write("## Feature distributions per asset\n\n")
    f.write("| asset | feature | p25 | p50 | p75 | p95 |\n")
    f.write("|---|---|---:|---:|---:|---:|\n")
    for asset in ("BTC","ETH","SOL"):
        sub = fills[fills["asset"]==asset]
        for feat in ("spread_pct","best_ask","vwap_slip"):
            q = sub[feat].quantile([0.25,0.5,0.75,0.95])
            f.write(f"| {asset} | {feat} | {q[0.25]:.4f} | {q[0.5]:.4f} | {q[0.75]:.4f} | {q[0.95]:.4f} |\n")
    f.write("\n")

    # 2. Per-feature quartile WR (focus on spread_pct first)
    for feat, label in [("spread_pct","TIGHT-SPREAD-Q1"),("best_ask","LOW-PRICE-Q1"),("vwap_slip","TIGHT-VWAP-Q1")]:
        f.write(f"## Quartile WR for `{feat}` — does Q1 (lowest) outperform other quartiles?\n\n")
        f.write("Per (strategy, cell): WR in each quartile (Q1 = lowest value of feature).\n\n")
        f.write("| strategy | cell | Q1_n | Q1_WR | Q1_avg$ | Q4_n | Q4_WR | Q4_avg$ | spread (Q1-Q4) |\n")
        f.write("|---|---|---:|---:|---:|---:|---:|---:|---:|\n")
        for (strat, cell), g in fills.groupby(["strategy","cell_key"]):
            if len(g) < 40: continue
            q1_thr, q3_thr = g[feat].quantile([0.25, 0.75])
            q1 = g[g[feat] <= q1_thr]; q4 = g[g[feat] >= q3_thr]
            if len(q1) < 5 or len(q4) < 5: continue
            wr_q1 = q1["won"].mean()*100; wr_q4 = q4["won"].mean()*100
            avg_q1 = q1["pnl"].mean(); avg_q4 = q4["pnl"].mean()
            f.write(f"| {strat} | {cell} | {len(q1)} | {wr_q1:.1f}% | ${avg_q1:+.2f} | "
                    f"{len(q4)} | {wr_q4:.1f}% | ${avg_q4:+.2f} | {wr_q1-wr_q4:+.1f}pp |\n")
        f.write("\n")

    # 3. Spread filter test: spread_pct in bottom quartile per (asset, tf)
    f.write("## Filter: tight spread (Q1 per asset×tf) — overlay per (strategy, cell)\n\n")
    fills["q1_spread"] = False
    for (asset, tf), g in fills.groupby(["asset","tf"]):
        thr = g["spread_pct"].quantile(0.25)
        fills.loc[g.index, "q1_spread"] = g["spread_pct"] <= thr
    f.write("| strategy | cell | n_pre | WR_pre | $/tr_pre | sum_pre | n_post | WR_post | $/tr_post | sum_post |\n")
    f.write("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|\n")
    for (strat, cell), g in fills.groupby(["strategy","cell_key"]):
        n_pre = len(g); wr_pre = g["won"].mean()*100; avg_pre = g["pnl"].mean(); sum_pre = g["pnl"].sum()
        gp = g[g["q1_spread"]]
        n_post = len(gp)
        if n_post < 10:
            f.write(f"| {strat} | {cell} | {n_pre} | {wr_pre:.1f}% | ${avg_pre:+.2f} | ${sum_pre:+.0f} | {n_post} | — | — | — |\n")
            continue
        wr_post = gp["won"].mean()*100; avg_post = gp["pnl"].mean(); sum_post = gp["pnl"].sum()
        f.write(f"| {strat} | {cell} | {n_pre} | {wr_pre:.1f}% | ${avg_pre:+.2f} | ${sum_pre:+.0f} | "
                f"{n_post} | {wr_post:.1f}% | ${avg_post:+.2f} | ${sum_post:+.0f} |\n")
    f.write("\n")

    # 4. Combined: tight-spread ∩ Markov
    f.write("## Tight spread ∩ MARKOV:w20_5m_voladaptive\n\n")
    f.write("| strategy | cell | n_combo | WR | $/tr | sum$ |\n")
    f.write("|---|---|---:|---:|---:|---:|\n")
    rows = []
    for (strat, cell), g in fills.groupby(["strategy","cell_key"]):
        gc = g[g["q1_spread"] & g["markov_pass_w20_5m_voladaptive"]]
        if len(gc) < 10:
            continue
        rows.append({"strategy":strat,"cell":cell,"n":len(gc),"wr":gc["won"].mean()*100,
                     "avg":gc["pnl"].mean(),"sum":gc["pnl"].sum()})
    rows_df = pd.DataFrame(rows).sort_values("sum", ascending=False)
    for _, r in rows_df.iterrows():
        f.write(f"| {r['strategy']} | {r['cell']} | {int(r['n'])} | {r['wr']:.1f}% | ${r['avg']:+.2f} | ${r['sum']:+.0f} |\n")
    f.write("\n")

    # 5. Verdict
    f.write("## Verdict\n\n")
    qprint = lambda x: f"${x:+.0f}"
    # Best per-cell using just q1_spread
    tight_per_cell = []
    for (strat, cell), g in fills.groupby(["strategy","cell_key"]):
        gp = g[g["q1_spread"]]
        if len(gp) < 30: continue
        tight_per_cell.append({"strategy":strat,"cell":cell,"n":len(gp),
                               "wr":gp["won"].mean()*100,"sum":gp["pnl"].sum()})
    tdf = pd.DataFrame(tight_per_cell).sort_values("sum",ascending=False).head(10)
    f.write("Top 10 (strategy × cell) under TIGHT-SPREAD-only gate (n>=30):\n\n")
    f.write("| strategy | cell | n | WR | sum |\n|---|---|---:|---:|---:|\n")
    for _, r in tdf.iterrows():
        f.write(f"| {r['strategy']} | {r['cell']} | {int(r['n'])} | {r['wr']:.1f}% | {qprint(r['sum'])} |\n")
    f.write("\n")

    f.write("## Notes\n")
    f.write("- Tight-spread filter is per (asset, tf) — Q1 of own-cell spread distribution.\n")
    f.write("- vwap_slip is essentially 0 because $25 notional rarely walks past best level on liquid books.\n")
    f.write("- best_ask quartile reveals price-level edges (more on cheap-side or expensive-side bets).\n")

print(f"wrote {OUT_MD}")
