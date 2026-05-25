"""
Hour-of-day + day-of-week overlay on existing fills.csv.
Writes HOUR_OF_DAY_FILTER.md and _hod_per_cell.csv incrementally.

NO backtest rerun. Pure overlay.
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/markov_filter/_results")
FILLS = ROOT / "backtest_prod_strats" / "fills.csv"
OUT_MD = ROOT / "HOUR_OF_DAY_FILTER.md"
OUT_CSV = ROOT / "_hod_per_cell.csv"

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def fmt_pct(x):
    return f"{x*100:.1f}%" if pd.notna(x) else "—"

def fmt_dollar(x):
    if pd.isna(x):
        return "—"
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):.2f}"

def metrics(g):
    n = len(g)
    if n == 0:
        return {"n": 0, "wr": np.nan, "pnl_per_tr": np.nan, "sum_pnl": 0.0}
    wr = g["won"].mean()
    sum_pnl = g["pnl"].sum()
    pnl_tr = sum_pnl / n
    return {"n": n, "wr": wr, "pnl_per_tr": pnl_tr, "sum_pnl": sum_pnl}

def append_md(text, mode="a"):
    with open(OUT_MD, mode, encoding="utf-8") as f:
        f.write(text + "\n")

# -----------------------------------------------------------------------------
# Load + enrich
# -----------------------------------------------------------------------------
df = pd.read_csv(FILLS)
df["fire_dt"] = pd.to_datetime(df["fire_us"], unit="us", utc=True)
df["hour"] = df["fire_dt"].dt.hour
df["dow"]  = df["fire_dt"].dt.dayofweek    # 0=Mon … 6=Sun
DOW_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
df["dow_name"] = df["dow"].map(dict(enumerate(DOW_NAMES)))

CELLS = sorted(df["cell"].unique())
STRATS = sorted(df["strategy"].unique())

# -----------------------------------------------------------------------------
# Header
# -----------------------------------------------------------------------------
gen_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
data_min = df["fire_dt"].min()
data_max = df["fire_dt"].max()

append_md(f"""# Hour-of-Day & Day-of-Week filter overlay

**Generated:** {gen_time}
**Input:** `strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv`
**Rows:** {len(df):,}
**Window:** {data_min} → {data_max}
**Strategies:** {', '.join(STRATS)}
**Cells:** {', '.join(CELLS)}

> Overlay-only analysis. No backtest rerun. UTC throughout.
> WR = win rate, $/tr = mean PnL per fill, n = # fills, sum$ = total PnL.
> A "fill" already includes Polymarket fees (legacy 2%-on-profit, sleeve-default).

---

""", mode="w")

# -----------------------------------------------------------------------------
# Section 1 — Per (strategy, cell) × hour
# -----------------------------------------------------------------------------
append_md("## 1. Per (strategy × cell) × UTC hour-of-day\n")
append_md("Tables show **win rate** in each hour, with $/trade and n underneath. "
          "Hot hours (WR ≥ 55%, n ≥ 10) are flagged with ★. "
          "Cold hours (WR ≤ 45%, n ≥ 10) are flagged with ✗.\n")

# Build per-cell-hour table → for raw csv export
rows = []
for (strat, cell), grp in df.groupby(["strategy","cell"]):
    for h in range(24):
        sub = grp[grp["hour"] == h]
        m = metrics(sub)
        rows.append({"strategy": strat, "cell": cell, "hour": h, **m})

hod_per_cell = pd.DataFrame(rows)
hod_per_cell.to_csv(OUT_CSV, index=False)

# Render per-(strategy,cell) tables
for strat in STRATS:
    sub_strat = df[df["strategy"] == strat]
    cells_for_strat = sorted(sub_strat["cell"].unique())
    if not cells_for_strat:
        continue
    append_md(f"### Strategy: `{strat}`\n")
    for cell in cells_for_strat:
        sub_cell = sub_strat[sub_strat["cell"] == cell]
        if len(sub_cell) == 0:
            continue
        n_tot = len(sub_cell)
        wr_tot = sub_cell["won"].mean()
        sum_tot = sub_cell["pnl"].sum()
        pnl_tot = sum_tot / n_tot
        append_md(f"#### `{strat} × {cell}` — overall: n={n_tot}, WR={fmt_pct(wr_tot)}, $/tr={fmt_dollar(pnl_tot)}, sum={fmt_dollar(sum_tot)}\n")

        # Build hour table
        lines = ["| h | n | WR | $/tr | sum$ | tag |", "|---|---|---|---|---|---|"]
        hot, cold = [], []
        for h in range(24):
            s = sub_cell[sub_cell["hour"] == h]
            m = metrics(s)
            tag = ""
            if m["n"] >= 10:
                if m["wr"] >= 0.55:
                    tag = "★"; hot.append(h)
                elif m["wr"] <= 0.45:
                    tag = "✗"; cold.append(h)
            wr_s   = fmt_pct(m["wr"]) if m["n"]>0 else "—"
            pnl_s  = fmt_dollar(m["pnl_per_tr"]) if m["n"]>0 else "—"
            sum_s  = fmt_dollar(m["sum_pnl"]) if m["n"]>0 else "—"
            lines.append(f"| {h:02d} | {m['n']} | {wr_s} | {pnl_s} | {sum_s} | {tag} |")
        append_md("\n".join(lines))
        append_md("")
        if hot:  append_md(f"**Hot hours (≥55% WR, n≥10):** {', '.join(f'{h:02d}' for h in hot)}")
        if cold: append_md(f"**Cold hours (≤45% WR, n≥10):** {', '.join(f'{h:02d}' for h in cold)}")
        append_md("")

# -----------------------------------------------------------------------------
# Section 2 — Day-of-Week
# -----------------------------------------------------------------------------
append_md("---\n\n## 2. Day-of-week analysis\n")
append_md("WR per day (Mon–Sun). Hot = WR ≥ 55% & n ≥ 10; cold = WR ≤ 45% & n ≥ 10.\n")

dow_rows = []
for (strat, cell), grp in df.groupby(["strategy","cell"]):
    append_md(f"### `{strat} × {cell}`\n")
    lines = ["| Day | n | WR | $/tr | sum$ | tag |", "|---|---|---|---|---|---|"]
    hot_d, cold_d = [], []
    for d_idx, d_name in enumerate(DOW_NAMES):
        s = grp[grp["dow"] == d_idx]
        m = metrics(s)
        tag = ""
        if m["n"] >= 10:
            if m["wr"] >= 0.55:
                tag = "★"; hot_d.append(d_name)
            elif m["wr"] <= 0.45:
                tag = "✗"; cold_d.append(d_name)
        wr_s   = fmt_pct(m["wr"]) if m["n"]>0 else "—"
        pnl_s  = fmt_dollar(m["pnl_per_tr"]) if m["n"]>0 else "—"
        sum_s  = fmt_dollar(m["sum_pnl"]) if m["n"]>0 else "—"
        lines.append(f"| {d_name} | {m['n']} | {wr_s} | {pnl_s} | {sum_s} | {tag} |")
        dow_rows.append({"strategy":strat,"cell":cell,"dow":d_idx,"dow_name":d_name,**m})
    append_md("\n".join(lines))
    append_md("")
    if hot_d:  append_md(f"**Hot days:** {', '.join(hot_d)}")
    if cold_d: append_md(f"**Cold days:** {', '.join(cold_d)}")
    append_md("")

dow_df = pd.DataFrame(dow_rows)
dow_df.to_csv(ROOT / "_dow_per_cell.csv", index=False)

# -----------------------------------------------------------------------------
# Section 3 — Top-8 hours filter test  (per cell, regardless of strategy)
# -----------------------------------------------------------------------------
append_md("---\n\n## 3. Top-8-hours filter test\n")
append_md("For each (strategy, cell): pick the **top 8 hours by sum$** "
          "(constraint: n ≥ 5). Apply as gate. Compare to NO_FILTER.\n")

filter_rows = []
for strat in STRATS:
    sub_strat = df[df["strategy"] == strat]
    cells_for_strat = sorted(sub_strat["cell"].unique())
    if not cells_for_strat:
        continue
    append_md(f"### Strategy: `{strat}`\n")
    header = ["| cell | NO_FILTER n | NO_FILTER WR | NO_FILTER $/tr | NO_FILTER sum$ | TOP8 hours | TOP8 n | TOP8 WR | TOP8 $/tr | TOP8 sum$ | $/tr lift |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    lines = list(header)
    for cell in cells_for_strat:
        sub_cell = sub_strat[sub_strat["cell"] == cell].copy()
        # Per-hour table for this cell
        per_h = (sub_cell.groupby("hour")
                 .agg(n=("won","size"), wr=("won","mean"),
                      sum_pnl=("pnl","sum"), pnl_tr=("pnl","mean"))
                 .reset_index())
        eligible = per_h[per_h["n"] >= 5].sort_values("sum_pnl", ascending=False)
        top8 = eligible.head(8)["hour"].tolist()
        # baseline
        m_no = metrics(sub_cell)
        # filtered
        sub_filt = sub_cell[sub_cell["hour"].isin(top8)]
        m_yes = metrics(sub_filt)
        lift = (m_yes["pnl_per_tr"] - m_no["pnl_per_tr"]) if m_yes["n"]>0 else np.nan
        top8_str = ",".join(f"{h:02d}" for h in sorted(top8))
        lines.append("| {cell} | {n0} | {wr0} | {p0} | {s0} | {h} | {n1} | {wr1} | {p1} | {s1} | {lift} |".format(
            cell=cell,
            n0=m_no["n"], wr0=fmt_pct(m_no["wr"]), p0=fmt_dollar(m_no["pnl_per_tr"]), s0=fmt_dollar(m_no["sum_pnl"]),
            h=top8_str,
            n1=m_yes["n"], wr1=fmt_pct(m_yes["wr"]), p1=fmt_dollar(m_yes["pnl_per_tr"]), s1=fmt_dollar(m_yes["sum_pnl"]),
            lift=fmt_dollar(lift),
        ))
        filter_rows.append({"strategy":strat,"cell":cell,
                            "no_filter_n":m_no["n"],"no_filter_wr":m_no["wr"],
                            "no_filter_pnl_tr":m_no["pnl_per_tr"],"no_filter_sum":m_no["sum_pnl"],
                            "top8_hours":top8_str,
                            "top8_n":m_yes["n"],"top8_wr":m_yes["wr"],
                            "top8_pnl_tr":m_yes["pnl_per_tr"],"top8_sum":m_yes["sum_pnl"],
                            "lift_pnl_tr":lift})
    append_md("\n".join(lines))
    append_md("")

filter_df = pd.DataFrame(filter_rows)
filter_df.to_csv(ROOT / "_hod_top8_filter.csv", index=False)

# -----------------------------------------------------------------------------
# Section 4 — HoD ∩ Markov  combo
# -----------------------------------------------------------------------------
append_md("---\n\n## 4. HoD-Top8 ∩ Markov(1m voladaptive) combo\n")
append_md("Stack the HoD-Top8 gate with the existing `markov_pass_w20_1m_voladaptive` column. "
          "Compare: NO_FILTER, HoD only, Markov only, HoD ∩ Markov.\n")

combo_rows = []
for strat in STRATS:
    sub_strat = df[df["strategy"] == strat]
    cells_for_strat = sorted(sub_strat["cell"].unique())
    if not cells_for_strat:
        continue
    append_md(f"### Strategy: `{strat}`\n")
    header = ["| cell | gate | n | WR | $/tr | sum$ |",
              "|---|---|---|---|---|---|"]
    lines = list(header)
    for cell in cells_for_strat:
        sub_cell = sub_strat[sub_strat["cell"] == cell].copy()
        # Recompute Top8 for this cell
        per_h = (sub_cell.groupby("hour")
                 .agg(n=("won","size"), wr=("won","mean"), sum_pnl=("pnl","sum"))
                 .reset_index())
        eligible = per_h[per_h["n"] >= 5].sort_values("sum_pnl", ascending=False)
        top8 = set(eligible.head(8)["hour"].tolist())
        in_hod  = sub_cell["hour"].isin(top8)
        in_mark = sub_cell["markov_pass_w20_1m_voladaptive"].astype(bool)

        gates = {
            "NO_FILTER": sub_cell,
            "HoD-Top8":  sub_cell[in_hod],
            "MARKOV-1m-voladaptive": sub_cell[in_mark],
            "HoD ∩ MARKOV": sub_cell[in_hod & in_mark],
        }
        for gname, gdf in gates.items():
            m = metrics(gdf)
            lines.append("| {c} | {g} | {n} | {wr} | {p} | {s} |".format(
                c=cell, g=gname, n=m["n"],
                wr=fmt_pct(m["wr"]) if m["n"]>0 else "—",
                p=fmt_dollar(m["pnl_per_tr"]) if m["n"]>0 else "—",
                s=fmt_dollar(m["sum_pnl"]) if m["n"]>0 else "—",
            ))
            combo_rows.append({"strategy":strat,"cell":cell,"gate":gname,**m})
    append_md("\n".join(lines))
    append_md("")

combo_df = pd.DataFrame(combo_rows)
combo_df.to_csv(ROOT / "_hod_markov_combo.csv", index=False)

# -----------------------------------------------------------------------------
# Section 5 — Verdict
# -----------------------------------------------------------------------------
append_md("---\n\n## 5. Verdict\n")

# Find best (strategy, cell, gate) combos by sum$ where n>=20
best = combo_df[combo_df["n"] >= 20].sort_values("sum_pnl", ascending=False).head(10)

append_md("### Top 10 (strategy × cell × gate) by sum$ (n ≥ 20)\n")
lines = ["| strategy | cell | gate | n | WR | $/tr | sum$ |",
         "|---|---|---|---|---|---|---|"]
for _, r in best.iterrows():
    lines.append("| {s} | {c} | {g} | {n} | {wr} | {p} | {sm} |".format(
        s=r["strategy"], c=r["cell"], g=r["gate"], n=int(r["n"]),
        wr=fmt_pct(r["wr"]), p=fmt_dollar(r["pnl_per_tr"]), sm=fmt_dollar(r["sum_pnl"]),
    ))
append_md("\n".join(lines))
append_md("")

# Per (strategy,cell), find best gate
append_md("### Best gate per (strategy × cell)\n")
best_per = (combo_df[combo_df["n"] >= 20]
            .sort_values("sum_pnl", ascending=False)
            .groupby(["strategy","cell"])
            .head(1)
            .sort_values(["strategy","cell"]))
lines = ["| strategy | cell | best gate | n | WR | $/tr | sum$ |",
         "|---|---|---|---|---|---|---|"]
for _, r in best_per.iterrows():
    lines.append("| {s} | {c} | {g} | {n} | {wr} | {p} | {sm} |".format(
        s=r["strategy"], c=r["cell"], g=r["gate"], n=int(r["n"]),
        wr=fmt_pct(r["wr"]), p=fmt_dollar(r["pnl_per_tr"]), sm=fmt_dollar(r["sum_pnl"]),
    ))
append_md("\n".join(lines))
append_md("")

# Stack vs each alone
append_md("### Does HoD + Markov stack?\n")
stack_lines = ["| strategy | cell | HoD only $/tr | Markov only $/tr | HoD ∩ Markov $/tr | better than each? |",
               "|---|---|---|---|---|---|"]
pivot = combo_df.pivot_table(index=["strategy","cell"], columns="gate", values="pnl_per_tr").reset_index()
n_pivot = combo_df.pivot_table(index=["strategy","cell"], columns="gate", values="n").reset_index()
for _, r in pivot.iterrows():
    h  = r.get("HoD-Top8", np.nan)
    mk = r.get("MARKOV-1m-voladaptive", np.nan)
    hm = r.get("HoD ∩ MARKOV", np.nan)
    n_hm = int(n_pivot[(n_pivot["strategy"]==r["strategy"]) & (n_pivot["cell"]==r["cell"])]["HoD ∩ MARKOV"].iloc[0] or 0)
    if n_hm < 10:
        verdict = "n<10 too small"
    elif pd.notna(hm) and pd.notna(h) and pd.notna(mk):
        better = hm > max(h, mk)
        verdict = "YES (stacks)" if better else "no (worse than at-least-one component)"
    else:
        verdict = "—"
    stack_lines.append("| {s} | {c} | {h} | {m} | {hm} | {v} |".format(
        s=r["strategy"], c=r["cell"],
        h=fmt_dollar(h), m=fmt_dollar(mk), hm=fmt_dollar(hm),
        v=verdict,
    ))
append_md("\n".join(stack_lines))
append_md("")

# Edge-vs-noise summary (count of cells where Top8 beats NO_FILTER $/tr)
no_filt = combo_df[combo_df["gate"]=="NO_FILTER"].set_index(["strategy","cell"])["pnl_per_tr"]
top8    = combo_df[combo_df["gate"]=="HoD-Top8"].set_index(["strategy","cell"])["pnl_per_tr"]
n_top8  = combo_df[combo_df["gate"]=="HoD-Top8"].set_index(["strategy","cell"])["n"]
n_cells = len(no_filt)
beats = int(((top8 > no_filt) & (n_top8 >= 20)).sum())
sig_cells = int((n_top8 >= 20).sum())
append_md("### Edge vs noise\n")
append_md(f"- (strategy × cell) pairs where HoD-Top8 beats NO_FILTER on $/tr (with n≥20): **{beats} / {sig_cells}** "
          f"({beats/max(sig_cells,1)*100:.0f}%).\n")
append_md(f"- Total (strategy × cell) pairs: {n_cells}.")
append_md("")
append_md("> A robust edge should beat NO_FILTER in **most** pairs. If the count is roughly 50/50 it's noise. "
          "An asymmetric split (e.g. 5/6) with material $/tr lift suggests a real intraday cycle.")
append_md("")

# -----------------------------------------------------------------------------
# Footer
# -----------------------------------------------------------------------------
append_md("\n---\n\n### Artefacts\n")
append_md(f"- `{OUT_CSV.name}` — per-(strategy,cell,hour) raw breakdown.")
append_md(f"- `_dow_per_cell.csv` — per-(strategy,cell,dow) breakdown.")
append_md(f"- `_hod_top8_filter.csv` — Top-8 filter results.")
append_md(f"- `_hod_markov_combo.csv` — HoD × Markov combo grid.")

print(f"DONE -> {OUT_MD}")
print(f"     -> {OUT_CSV}")
print(f"rows={len(df)} strategies={STRATS} cells={CELLS}")
