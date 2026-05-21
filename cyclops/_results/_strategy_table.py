"""Build the cross-strategy comparison table the user asked for.

Loads every per-trade CSV produced this session, rescales PnL from
$25 stake → $1 stake, and prints a wide table with all the key metrics.
Also writes the table to a markdown file for easy reference.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

STAKE_BACKTEST = 25.0
STAKE_RESCALE = 1.0
SCALE = STAKE_RESCALE / STAKE_BACKTEST   # = 0.04


CONFIGS = [
    # (label, file, description)
    ("S1_P2_raw",
     "cyclops/_results/p2_full_21d.csv",
     "raw 3-axis, no filters (degraded momentum from tier1 snapshot)"),
    ("S2_P3_baseline",
     "cyclops/_results/p3_vwap30_momabstain.csv",
     "+ vwap>=0.30 + require_momentum_abstain"),
    ("S3_P3_plus_blowoff",
     "cyclops/_results/p3_plus_blowoff.csv",
     "S2 + blowoff_guard"),
    ("S4_P3_plus_hours",
     "cyclops/_results/p3_plus_hours.csv",
     "S2 + hours_guard (13-21 UTC, weekend off)"),
    ("S5_P3_full_stack",
     "cyclops/_results/p3_full_stack.csv",
     "S2 + hours + blowoff + reentry"),
    ("S6_FD_raw",
     "cyclops/_results/p5_full_depth_raw.csv",
     "raw 3-axis, FULL-DEPTH momentum (streaming L25 + 24M trades)"),
    ("S7_FD_P3",
     "cyclops/_results/p5_full_depth_p3.csv",
     "S2 with full-depth momentum"),
    ("S8_FD_full_stack",
     "cyclops/_results/p5_full_depth_fullstack.csv",
     "S5 with full-depth momentum + ob_manipulation_guard"),
]


def load_gates_json(csv_path: Path) -> dict:
    out = {}
    for tag in ("permutation", "bootstrap", "walkforward"):
        p = csv_path.with_suffix(f".{tag}.json")
        if p.exists():
            out[tag] = json.loads(p.read_text())
    return out


def stats_for(csv_path: Path) -> dict:
    df = pd.read_csv(csv_path)
    fired = df[df.fired == True].copy()
    n_eval = len(df)
    n_fired = len(fired)
    if n_fired == 0:
        return {"n_eval": n_eval, "n_fired": 0}

    # Rescale PnL to $1 stake
    fired["pnl_1usd"] = fired["pnl_usd"] * SCALE
    fired["stake_1usd"] = fired["stake_usd"] * SCALE

    wins = int(fired["won"].sum())
    losses = n_fired - wins
    wr = wins / n_fired
    mean_pnl_1 = float(fired["pnl_1usd"].mean())
    sum_pnl_1 = float(fired["pnl_1usd"].sum())
    sum_pnl_25 = float(fired["pnl_usd"].sum())
    mean_vwap = float(fired["vwap_entry"].mean())
    breakeven_wr = mean_vwap  # for binary markets, breakeven WR ≈ entry price
    edge_pp = (wr - breakeven_wr) * 100

    # Drawdown (assuming sequential trade order by ws_s)
    fired_sorted = fired.sort_values("ws_s").reset_index(drop=True)
    fired_sorted["cum_1"] = fired_sorted["pnl_1usd"].cumsum()
    fired_sorted["peak_1"] = fired_sorted["cum_1"].cummax()
    fired_sorted["dd_1"] = fired_sorted["cum_1"] - fired_sorted["peak_1"]
    max_dd_1 = float(fired_sorted["dd_1"].min())
    max_dd_25 = max_dd_1 / SCALE

    # Period
    ws_min = int(fired["ws_s"].min())
    ws_max = int(fired["ws_s"].max())
    days_span = (ws_max - ws_min) / 86400

    # Win/loss size moments
    win_pnl = fired[fired.won == True]["pnl_1usd"]
    loss_pnl = fired[fired.won == False]["pnl_1usd"]
    mean_win = float(win_pnl.mean()) if len(win_pnl) else 0.0
    mean_loss = float(loss_pnl.mean()) if len(loss_pnl) else 0.0
    profit_factor = (
        -float(win_pnl.sum()) / float(loss_pnl.sum())
        if len(loss_pnl) and loss_pnl.sum() < 0 else float("inf")
    )

    # Per direction
    by_dir = {}
    if "direction" in fired.columns:
        for d in ("Up", "Down"):
            sd = fired[fired.direction == d]
            if len(sd):
                by_dir[d] = {
                    "n": int(len(sd)),
                    "wr": float(sd["won"].mean()),
                    "mean_pnl_1": float(sd["pnl_1usd"].mean()),
                    "sum_pnl_1": float(sd["pnl_1usd"].sum()),
                }

    # Sharpe-ish (per-trade)
    pnl_std_1 = float(fired["pnl_1usd"].std())
    sharpe_per_trade = mean_pnl_1 / pnl_std_1 if pnl_std_1 > 0 else 0.0

    gates = load_gates_json(csv_path)

    return {
        "n_eval": n_eval,
        "n_fired": n_fired,
        "fire_rate_pct": n_fired / n_eval * 100,
        "wins": wins,
        "losses": losses,
        "wr": wr,
        "mean_vwap": mean_vwap,
        "breakeven_wr": breakeven_wr,
        "edge_pp": edge_pp,
        "mean_pnl_1": mean_pnl_1,
        "sum_pnl_1": sum_pnl_1,
        "sum_pnl_25_actual": sum_pnl_25,
        "max_dd_1": max_dd_1,
        "max_dd_25_actual": max_dd_25,
        "mean_win_1": mean_win,
        "mean_loss_1": mean_loss,
        "profit_factor": profit_factor,
        "sharpe_per_trade": sharpe_per_trade,
        "ws_min": ws_min,
        "ws_max": ws_max,
        "days_span": days_span,
        "by_dir": by_dir,
        "gates": gates,
    }


def fmt_period(ws_min: int, ws_max: int) -> str:
    a = pd.Timestamp(ws_min, unit="s", tz="UTC").strftime("%Y-%m-%d %H:%M")
    b = pd.Timestamp(ws_max, unit="s", tz="UTC").strftime("%Y-%m-%d %H:%M")
    return f"{a} → {b}"


def main():
    results = []
    for label, fp, desc in CONFIGS:
        p = Path(fp)
        if not p.exists():
            print(f"  MISSING {fp}")
            continue
        s = stats_for(p)
        s["label"] = label
        s["description"] = desc
        s["file"] = str(p)
        results.append(s)

    # Print human-readable table
    print()
    print("=" * 110)
    print("Strategy comparison — every config, $1 stake per trade")
    print("=" * 110)
    print()
    headers = ["Strategy", "Markets", "Fires", "Wins", "Loss", "WR%",
               "Brk%", "Edge", "$mean", "$total", "$dd_max", "Period (UTC)"]
    widths = [22, 7, 6, 5, 5, 5, 5, 6, 8, 9, 9, 38]

    def row(vals):
        parts = []
        for v, w in zip(vals, widths):
            s = str(v)
            if len(s) > w:
                s = s[: w - 1] + "…"
            parts.append(s.rjust(w))
        return "  ".join(parts)

    print(row(headers))
    print("-" * 110)
    for r in results:
        if r["n_fired"] == 0:
            print(row([r["label"], r["n_eval"], 0, 0, 0, "-", "-", "-", "-",
                      "-", "-", "-"]))
            continue
        print(row([
            r["label"],
            r["n_eval"],
            r["n_fired"],
            r["wins"],
            r["losses"],
            f"{r['wr']*100:.1f}",
            f"{r['breakeven_wr']*100:.1f}",
            f"{r['edge_pp']:+.2f}pp",
            f"${r['mean_pnl_1']:+.4f}",
            f"${r['sum_pnl_1']:+.2f}",
            f"${r['max_dd_1']:.2f}",
            fmt_period(r["ws_min"], r["ws_max"]),
        ]))
    print("-" * 110)
    print(f"All PnL columns are at $1 stake per trade. Multiply by 25 for actual backtest dollars.")
    print(f"WR = wins / fires.  Brk = mean entry vwap (= breakeven WR for binary markets).")
    print(f"Edge = WR - Brk (positive = profitable per-trade).")
    print()

    print("=" * 110)
    print("Detailed per-strategy breakdown")
    print("=" * 110)
    for r in results:
        print(f"\n{r['label']}: {r['description']}")
        if r["n_fired"] == 0:
            print(f"  → no fires")
            continue
        print(f"  Period:     {fmt_period(r['ws_min'], r['ws_max'])}  "
              f"({r['days_span']:.1f}d)")
        print(f"  Universe:   {r['n_eval']} markets evaluated, "
              f"{r['n_fired']} fired ({r['fire_rate_pct']:.2f}%)")
        print(f"  Outcomes:   {r['wins']} wins, {r['losses']} losses")
        print(f"  WR / Brk:   {r['wr']*100:.2f}% / {r['breakeven_wr']*100:.2f}% "
              f"= {r['edge_pp']:+.2f}pp edge")
        print(f"  Per-trade:  mean=${r['mean_pnl_1']:+.4f}  "
              f"win=${r['mean_win_1']:+.4f}  loss=${r['mean_loss_1']:+.4f}  "
              f"profit_factor={r['profit_factor']:.2f}")
        print(f"  Risk:       max DD=${r['max_dd_1']:.2f}  "
              f"sharpe/trade={r['sharpe_per_trade']:.3f}")
        print(f"  Totals:     ${r['sum_pnl_1']:+.2f} @ $1 stake "
              f"(${r['sum_pnl_25_actual']:+.2f} @ $25 stake)")
        if r["by_dir"]:
            for d, ds in r["by_dir"].items():
                print(f"  {d:4s} dir:   n={ds['n']:4d}  WR={ds['wr']*100:.2f}%  "
                      f"mean=${ds['mean_pnl_1']:+.4f}  total=${ds['sum_pnl_1']:+.2f}")
        # Gates
        gates = r.get("gates", {})
        if gates:
            print(f"  Gates:")
            if "permutation" in gates:
                g = gates["permutation"]
                p = g.get("p_value")
                v = g.get("verdict", "?")
                print(f"    G3 perm:  p={p:.4f}  ({v})")
            if "bootstrap" in gates:
                g = gates["bootstrap"]
                lo = g.get("ci_lower", float("nan"))
                hi = g.get("ci_upper", float("nan"))
                v = g.get("verdict", "?")
                # Rescale CI to $1 stake
                print(f"    G4 boot:  CI[95%] @$1 = ${lo*SCALE:+.4f} .. "
                      f"${hi*SCALE:+.4f}  ({v})")
            if "walkforward" in gates:
                g = gates["walkforward"]
                nw = g.get("n_windows", 0)
                npos = g.get("n_positive", 0)
                v = g.get("verdict", "?")
                print(f"    G2 walk:  {npos}/{nw} windows positive  ({v})")

    # Also dump as Markdown table
    print()
    print("=" * 110)
    print("Markdown table (paste-ready)")
    print("=" * 110)
    md_headers = ["#", "Strategy", "Markets", "Fires", "Wins", "Losses",
                  "WR%", "Brk%", "Edge", "Mean PnL ($1)", "Total ($1)",
                  "Max DD ($1)", "Days", "G1", "G3 p", "G4", "G2"]
    print("| " + " | ".join(md_headers) + " |")
    print("|" + "|".join(["---"] * len(md_headers)) + "|")
    for r in results:
        if r["n_fired"] == 0:
            continue
        g = r.get("gates", {})
        g1 = "PASS" if r["mean_pnl_1"] > 0 else "FAIL"
        g3 = g.get("permutation", {}).get("p_value", "—")
        if isinstance(g3, float):
            g3 = f"{g3:.3f}"
        g4 = g.get("bootstrap", {}).get("verdict", "—")
        g2 = g.get("walkforward", {}).get("verdict", "—")
        if g2 not in ("PASS", "FAIL", "—"):
            g2 = "—"
        cells = [
            r["label"].split("_")[0].lstrip("S"),
            r["label"][3:].replace("_", " "),
            str(r["n_eval"]),
            str(r["n_fired"]),
            str(r["wins"]),
            str(r["losses"]),
            f"{r['wr']*100:.1f}",
            f"{r['breakeven_wr']*100:.1f}",
            f"{r['edge_pp']:+.2f}pp",
            f"${r['mean_pnl_1']:+.4f}",
            f"${r['sum_pnl_1']:+.2f}",
            f"${r['max_dd_1']:.2f}",
            f"{r['days_span']:.1f}",
            g1,
            str(g3),
            str(g4),
            str(g2),
        ]
        print("| " + " | ".join(cells) + " |")
    print()


if __name__ == "__main__":
    main()
