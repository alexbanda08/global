"""
Build LOW_DD_VERDICT.pdf — V23-V28 low-drawdown variants + new recommendation.

Destination: C:\\Users\\alexandre bandarra\\Desktop\\newstrategies\\LOW_DD_VERDICT.pdf
"""
from __future__ import annotations
import json, shutil
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd

plt.rcParams.update({
    "font.family":"DejaVu Sans","axes.spines.top":False,"axes.spines.right":False,
    "axes.grid":True,"grid.alpha":0.25,"grid.linestyle":"--","figure.facecolor":"white",
})

BASE = Path(__file__).resolve().parent
RES  = BASE / "results"
OUT_LOCAL  = BASE / "reports" / "LOW_DD_VERDICT.pdf"
OUT_PUBLIC = Path("C:/Users/alexandre bandarra/Desktop/newstrategies/LOW_DD_VERDICT.pdf")
OUT_PUBLIC.parent.mkdir(parents=True, exist_ok=True)


def _fmt_usd(x):
    ax = abs(x)
    if ax >= 1e9: return f"${x/1e9:.1f}B"
    if ax >= 1e6: return f"${x/1e6:.1f}M"
    if ax >= 1e3: return f"${x/1e3:.0f}k"
    return f"${x:.0f}"


def cover(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "LOW-DRAWDOWN FINDINGS",
            ha="center", fontsize=24, weight="bold")
    ax.text(0.5, 0.93, "Cutting OOS DD from -64% to -34% while keeping Sharpe > 1.3",
            ha="center", fontsize=12, color="#555")
    ax.axhline(0.91, 0.05, 0.95, color="#ccc", lw=0.7)

    # TL;DR box
    box = plt.Rectangle((0.06, 0.52), 0.88, 0.35,
                        fill=True, facecolor="#f2fbf2", edgecolor="#0a6", lw=1.2)
    ax.add_patch(box)
    ax.text(0.08, 0.845, "Three upgrade paths (vs baseline 1× XSM DD -46%)",
            fontsize=12, weight="bold", color="#0a6")

    lines = [
        ("1. DEFENSIVE — V24 multi-filter at 1× leverage",
         "Triple bear filter (BTC 100d-MA + BTC 50d-MA rising + ≥5 of 9 coins above own 50d-MA)."),
        ("",
         "Full CAGR +120%, Sharpe 1.80, DD -39%, Calmar 3.07  |  OOS CAGR +60%, Sharpe 1.31, DD -39%"),
        ("2. BALANCED — V24 multi-filter at 1.5× leverage",
         "Same triple filter + 1.5× leverage — highest Calmar of any test."),
        ("",
         "Full CAGR +199%, Sharpe 1.83, DD -53%, Calmar 3.77  |  OOS CAGR +91%, Sharpe 1.32, DD -53%"),
        ("3. OOS-MAX — V27 long-short  L2/S2  at 1× leverage",
         "Long top-2, short bottom-2 — market-neutral direction, catches relative-strength."),
        ("",
         "Full CAGR +96%, Sharpe 1.25, DD -71%  |  OOS CAGR +104%, Sharpe 1.75, DD -34%  (LOWEST OOS DD!)"),
    ]
    y = 0.815
    for h, body in lines:
        if h:
            ax.text(0.09, y, h, fontsize=10, weight="bold", color="#258")
        else:
            ax.text(0.11, y, body, fontsize=9, color="#222", family="monospace")
        y -= 0.022

    ax.text(0.06, 0.48, "What we tested (22 configs)",
            fontsize=12, weight="bold", color="#258")
    mech = [
        ("V23 Vol-targeting",
         "inverse-vol sizing, target 35/50/70% annualised — modest help; same DD at same leverage"),
        ("V24 Multi-filter regime",
         "triple confirmation BTC-100d + BTC-50d-rising + market breadth ≥ 5/9 — BIGGEST WIN"),
        ("V25 DD circuit breaker",
         "flatten at -20/-25/-30% DD from ATH — over-halts; strategy sits flat forever"),
        ("V26 Dynamic leverage",
         "lev = target_vol / realised_vol — DD -37%/Sharpe 1.63 at 1× target 40%; moderate help"),
        ("V27 Long-short",
         "long top-K, short bottom-K — OOS DD -34% (best), but full-period DD -71% (early period noisy)"),
        ("V28 Per-position SL",
         "hard 10/15/20% stop per coin — modest effect, close-to-baseline"),
        ("COMBINED",
         "stack v23+v25+v28 — net negative (halt breaker over-fires)"),
    ]
    y = 0.45
    for k, v in mech:
        ax.text(0.08, y, k, fontsize=9.5, weight="bold", color="#258")
        ax.text(0.28, y, v, fontsize=9, color="#222"); y -= 0.022

    ax.text(0.06, 0.22, "Final recommendation — pick ONE profile based on comfort",
            fontsize=12, weight="bold", color="#258")

    rec = [
        ("If DD > 45% wipes you out", "V24 multi-filter  1×", "DD -39%, Sharpe 1.80 full, 1.31 OOS"),
        ("Best Calmar + acceptable DD","V24 multi-filter  1.5×", "DD -53%, Sharpe 1.83, Calmar 3.77"),
        ("Best OOS-tested metric",    "V27 long-short L2/S2 1×", "OOS Sharpe 1.75, OOS DD -34%"),
    ]
    y = 0.19
    for ctx, spec, perf in rec:
        ax.text(0.08, y, ctx, fontsize=9.5, color="#258", weight="bold")
        ax.text(0.30, y, spec, fontsize=9.5, color="#0a6", weight="bold", family="monospace")
        ax.text(0.55, y, perf, fontsize=9, color="#222"); y -= 0.022

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def results_table_page(pdf):
    df = pd.read_csv(RES / "v23_low_dd.csv")
    # Sort by OOS DD (less negative = better)
    df_sorted = df.sort_values("oos_dd", ascending=False).copy()

    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "All 22 low-DD variants ranked by OOS drawdown",
            ha="center", fontsize=16, weight="bold")
    ax.text(0.5, 0.935, "Smallest OOS |DD| at top.  Green = profitable + Sharpe > 1.5.",
            ha="center", fontsize=9, color="#555")
    ax.axhline(0.92, 0.05, 0.95, color="#ccc", lw=0.7)

    cols = ["label", "full_cagr", "full_sharpe", "full_dd", "full_calmar",
            "oos_cagr", "oos_sharpe", "oos_dd", "legs"]
    headers = ["Variant", "Full CAGR", "Sharpe", "DD", "Calmar",
               "OOS CAGR", "OOS Sharpe", "OOS DD", "Trades"]
    disp = df_sorted[cols].copy()
    # Fix mojibake
    disp["label"] = disp["label"].str.replace("\u00d7", "x").str.replace("\ufffd", "x", regex=False).str.replace("x x", "x")
    disp["label"] = disp["label"].str.replace("Lx", "Lx", regex=False)
    # Format
    for c in ("full_cagr","full_dd","oos_cagr","oos_dd"):
        disp[c] = disp[c].apply(lambda v: f"{v*100:+5.1f}%")
    for c in ("full_sharpe","full_calmar","oos_sharpe"):
        disp[c] = disp[c].apply(lambda v: f"{v:+.2f}")
    disp["legs"] = disp["legs"].apply(lambda v: f"{int(v):,}")
    rows = [headers] + disp.values.tolist()
    tbl = ax.table(cellText=rows, loc="upper center", cellLoc="left",
                   bbox=[0.02, 0.02, 0.96, 0.90])
    tbl.auto_set_font_size(False); tbl.set_fontsize(6.8); tbl.scale(1, 1.20)
    for j in range(len(headers)):
        tbl[(0, j)].set_facecolor("#dee"); tbl[(0, j)].set_text_props(weight="bold")
    # Color code
    for i, r in enumerate(df_sorted.itertuples(), start=1):
        # Green if profitable AND sharpe > 1.5
        if r.full_final > 10000 and r.full_sharpe > 1.5:
            tbl[(i, 0)].set_facecolor("#d3f0d5")
        # DD column colour
        if r.full_dd > -0.45:
            tbl[(i, 3)].set_facecolor("#b9e8bd")
        elif r.full_dd > -0.60:
            tbl[(i, 3)].set_facecolor("#fff2c2")
        else:
            tbl[(i, 3)].set_facecolor("#fcd7b6")
        if r.oos_dd > -0.40:
            tbl[(i, 7)].set_facecolor("#b9e8bd")
        elif r.oos_dd > -0.55:
            tbl[(i, 7)].set_facecolor("#fff2c2")
        else:
            tbl[(i, 7)].set_facecolor("#fcd7b6")

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def frontier_page(pdf):
    df = pd.read_csv(RES / "v23_low_dd.csv")
    fig = plt.figure(figsize=(11, 8.5))
    fig.suptitle("Risk / reward frontier — DD vs CAGR",
                 fontsize=16, weight="bold", y=0.97)
    fig.text(0.5, 0.945, "Up and to the LEFT is better (higher CAGR at smaller DD).",
             fontsize=10, ha="center", color="#555")

    # Full period scatter
    ax1 = fig.add_axes([0.07, 0.52, 0.42, 0.38])
    ax1.scatter(-df["full_dd"] * 100, df["full_cagr"] * 100,
                s=df["full_sharpe"].clip(0.5, 2.0) * 60,
                c=df["full_sharpe"], cmap="RdYlGn", vmin=0.5, vmax=2.0,
                edgecolors="black", linewidths=0.5, alpha=0.85)
    ax1.set_xlabel("MaxDD (%, absolute)"); ax1.set_ylabel("CAGR (%)")
    ax1.set_title("Full period 2018-2026  ·  size = Sharpe", fontsize=10)
    ax1.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    # Annotate top points
    best_full = df.nlargest(3, "full_calmar")
    for _, r in best_full.iterrows():
        ax1.annotate(r["label"].split()[0] + " " + r["label"].split()[-1],
                     xy=(-r["full_dd"]*100, r["full_cagr"]*100),
                     fontsize=7, xytext=(5, 5), textcoords="offset points")

    # OOS scatter
    ax2 = fig.add_axes([0.55, 0.52, 0.42, 0.38])
    ax2.scatter(-df["oos_dd"] * 100, df["oos_cagr"] * 100,
                s=df["oos_sharpe"].clip(0.5, 2.0) * 60,
                c=df["oos_sharpe"], cmap="RdYlGn", vmin=0.5, vmax=2.0,
                edgecolors="black", linewidths=0.5, alpha=0.85)
    ax2.set_xlabel("OOS MaxDD (%, abs)"); ax2.set_ylabel("OOS CAGR (%)")
    ax2.set_title("OOS 2022-2025  ·  size = Sharpe", fontsize=10)
    ax2.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    best_oos = df.nlargest(3, "oos_sharpe")
    for _, r in best_oos.iterrows():
        ax2.annotate(r["label"].split()[0] + " " + r["label"].split()[-1],
                     xy=(-r["oos_dd"]*100, r["oos_cagr"]*100),
                     fontsize=7, xytext=(5, 5), textcoords="offset points")

    # Bottom: Sharpe ranking by Calmar
    ax3 = fig.add_axes([0.07, 0.08, 0.88, 0.36])
    top_by_calmar = df.nlargest(10, "full_calmar").sort_values("full_calmar")
    labels = [l.replace("\u00d7","x").replace("\ufffd","x") for l in top_by_calmar["label"]]
    bars = ax3.barh(labels, top_by_calmar["full_calmar"],
                    color=["#0a6" if v > 3.2 else "#258" for v in top_by_calmar["full_calmar"]])
    ax3.set_xlabel("Full-period Calmar")
    ax3.set_title("Top 10 variants by Calmar (CAGR / MaxDD)", fontsize=10)
    for bar, v in zip(bars, top_by_calmar["full_calmar"]):
        ax3.text(v + 0.05, bar.get_y() + bar.get_height()/2,
                 f"{v:.2f}", va="center", fontsize=8)

    pdf.savefig(fig); plt.close(fig)


def winners_detail_page(pdf):
    df = pd.read_csv(RES / "v23_low_dd.csv")
    # Pick the three winners
    wanted = [
        "V24 multi-filter  breadth=5  L=1",
        "V24 multi-filter  breadth=5  L=1.5",
        "V27 long-short   L2/S2  L=1",
        "BASELINE 1.0",
        "BASELINE 1.5",
    ]
    selected = []
    for w in wanted:
        match = df[df["label"].str.contains(w.replace(" ", " "), regex=False, na=False)]
        if len(match): selected.append(match.iloc[0].to_dict())
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "The three upgrade paths side-by-side",
            ha="center", fontsize=17, weight="bold")
    ax.axhline(0.93, 0.05, 0.95, color="#ccc", lw=0.7)

    headers = ["Metric", "Baseline 1.0×", "Baseline 1.5×",
               "V24 mf 1.0× DEFENSIVE", "V24 mf 1.5× BALANCED NEW", "V27 L/S OOS-MAX"]
    metric_rows = [
        ("Full CAGR",    "full_cagr",    "pct"),
        ("Full Sharpe",  "full_sharpe",  "num"),
        ("Full MaxDD",   "full_dd",      "pct"),
        ("Full Calmar",  "full_calmar",  "num"),
        ("OOS CAGR",     "oos_cagr",     "pct"),
        ("OOS Sharpe",   "oos_sharpe",   "num"),
        ("OOS MaxDD",    "oos_dd",       "pct"),
        ("Trade legs",   "legs",         "int"),
    ]

    def pick(label_sub):
        for s in selected:
            if label_sub.lower() in s["label"].lower():
                return s
        return {}

    profile_cols = [
        pick("baseline 1.0"),
        pick("baseline 1.5"),
        pick("V24 multi-filter  breadth=5  L=1") if "V24 multi-filter  breadth=5  L=1.5" not in pick("V24 multi-filter  breadth=5  L=1").get("label","") else {},
        pick("V24 multi-filter  breadth=5  L=1.5"),
        pick("V27 long-short   L2/S2"),
    ]
    # Re-fetch in explicit order
    def find(q):
        for s in selected:
            lab = s["label"].lower().replace("\u00d7","x").replace("\ufffd","x")
            if q.lower() in lab:
                return s
        return {}
    profile_cols = [
        find("baseline 1.0"),
        find("baseline 1.5"),
        find("v24 multi-filter  breadth=5  lx=1x"),  # fallback patterns
        find("v24 multi-filter  breadth=5  l=1.5"),
        find("v27 long-short   l2/s2"),
    ]
    # easier: lookup by label pattern
    def by(label_part):
        for _, r in df.iterrows():
            ll = str(r["label"]).lower()
            if all(p.lower() in ll for p in label_part):
                return r.to_dict()
        return {}
    profile_cols = [
        by(["baseline", "1.0"]),
        by(["baseline", "1.5"]),
        by(["v24", "breadth=5", "l=1"]) if not by(["v24","breadth=5","l=1.5"]).get("label") == by(["v24","breadth=5","l=1"]).get("label") else by(["v24","breadth=5","l=1"]),
        by(["v24", "breadth=5", "l=1.5"]),
        by(["v27", "l2/s2"]),
    ]
    # simpler: fetch all V24 breadth=5 rows, pick 1x and 1.5x
    v24_rows = df[df["label"].str.contains("multi-filter", case=False)].copy()
    v24_rows["_is_15"] = v24_rows["label"].str.contains("1.5", case=False)
    v24_1x = v24_rows[(~v24_rows["_is_15"]) & v24_rows["label"].str.contains("breadth=5")]
    v24_15 = v24_rows[v24_rows["_is_15"] & v24_rows["label"].str.contains("breadth=5")]
    profile_cols[2] = v24_1x.iloc[0].to_dict() if len(v24_1x) else {}
    profile_cols[3] = v24_15.iloc[0].to_dict() if len(v24_15) else {}

    def cell(prof, key, kind):
        v = prof.get(key)
        if v is None or (isinstance(v, float) and np.isnan(v)): return "-"
        if kind == "pct": return f"{v*100:+.1f}%"
        if kind == "num": return f"{v:+.2f}" if isinstance(v, float) else f"{v}"
        if kind == "int": return f"{int(v):,}"
        return str(v)

    rows_data = [headers]
    for metric_name, key, kind in metric_rows:
        row = [metric_name]
        for p in profile_cols:
            row.append(cell(p, key, kind))
        rows_data.append(row)

    tbl = ax.table(cellText=rows_data, loc="upper center", cellLoc="center",
                   bbox=[0.02, 0.30, 0.96, 0.6])
    tbl.auto_set_font_size(False); tbl.set_fontsize(9); tbl.scale(1, 1.6)
    for j in range(len(headers)):
        tbl[(0, j)].set_facecolor("#dee"); tbl[(0, j)].set_text_props(weight="bold")
    # Highlight winning columns
    for i in range(1, len(rows_data)):
        tbl[(i, 3)].set_facecolor("#eaf6ea")  # V24 1x
        tbl[(i, 4)].set_facecolor("#b9e8bd")  # V24 1.5x (champion)
        tbl[(i, 5)].set_facecolor("#eaf6ea")  # V27 LS

    # Guidance text
    ax.text(0.06, 0.22, "Which to pick?",
            fontsize=12, weight="bold", color="#258")
    guidance = [
        "• New default = V24 multi-filter 1.5×  —  biggest Calmar (3.77), CAGR +199%, DD cut from -64% to -53%.",
        "• Conservative (can't tolerate > -40% DD) = V24 multi-filter 1.0× — DD -39%, CAGR +120%.",
        "• Most-robust-OOS = V27 long-short L2/S2 — best OOS Sharpe 1.75 and best OOS DD -34%.",
        "",
        "Implementation deltas from current spec:",
        "  V24: add two extra conditions to the rebalance filter (BTC 50d-MA rising + market breadth ≥ 5/9).",
        "  V27: same XSM universe but ALSO open short positions on bottom-2 coins at equal weight.",
        "  (V27 requires Hyperliquid perpetual shorts — already supported natively.)",
    ]
    y = 0.19
    for line in guidance:
        ax.text(0.08, y, line, fontsize=9.5, color="#222"); y -= 0.020

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def new_spec_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "UPGRADED SPEC — v3 with V24 multi-filter",
            ha="center", fontsize=17, weight="bold")
    ax.axhline(0.93, 0.05, 0.95, color="#ccc", lw=0.7)

    box = plt.Rectangle((0.06, 0.44), 0.88, 0.46, fill=True,
                        facecolor="#f7faff", edgecolor="#258", lw=1.2)
    ax.add_patch(box)
    ax.text(0.08, 0.88, "HYPERLIQUID DEPLOY SPEC v3", fontsize=13, weight="bold", color="#258")
    spec = [
        ("Account",             "$10,000 USDC on Hyperliquid (min $1k)"),
        ("Split",               "70% Momentum + 30% Trend (unchanged)"),
        ("",                    ""),
        ("XSM sleeve (70%)",    ""),
        ("   Universe",         "BTC · ETH · SOL · BNB · XRP · DOGE · LINK · ADA · AVAX"),
        ("   Signal",           "rank by past-14d return weekly (Monday 00:00 UTC)"),
        ("   Position",         "equal-weight long top 4  —  1.5× leverage"),
        ("   BEAR FILTER (NEW)","flatten entire sleeve when ANY of:"),
        ("                    ","   a) BTC close < BTC 100-day SMA"),
        ("                    ","   b) BTC 50-day SMA falling (1-day slope < 0)"),
        ("                    ","   c) market breadth: < 5 of 9 coins above own 50-day SMA"),
        ("   Execution",        "limit orders on next bar open, Hyperliquid maker 0.015%"),
        ("",                    ""),
        ("Trend sleeve (30%)",  ""),
        ("   Coins",            "BTC · ETH · SOL · LINK · ADA · XRP"),
        ("   Strategies",       "V4C / V3B / HWR1  (unchanged)"),
        ("   Sizing",           "5% × 5× per-position  (unchanged)"),
    ]
    y = 0.85
    for k, v in spec:
        if k:
            ax.text(0.09, y, k, fontsize=9,
                    weight="bold" if (":" not in k and k[0] != " ") else "normal",
                    color="#258" if not k.startswith("   ") else "#444")
        ax.text(0.36, y, v, fontsize=9, color="#222")
        y -= 0.020

    ax.text(0.06, 0.40, "Backtest expectation (2018-26):",
            fontsize=11, weight="bold", color="#258")
    expected = [
        ("Full CAGR",      "+199 %/yr"),
        ("Full Sharpe",    "1.83"),
        ("Full MaxDD",     "-53 %  (−12 pp vs old spec v2)"),
        ("Full Calmar",    "3.77  (vs 3.95 v2 — slightly lower but much safer)"),
        ("Final on $10k",  "~$110 M (8.25 years)"),
    ]
    y = 0.37
    for k, v in expected:
        ax.text(0.08, y, f"{k:<18}", fontsize=10, family="monospace", weight="bold", color="#258")
        ax.text(0.29, y, v, fontsize=10, color="#222"); y -= 0.021

    ax.text(0.06, 0.25, "OOS expectation (2022-25):",
            fontsize=11, weight="bold", color="#258")
    oos = [
        ("OOS CAGR",       "+91 %/yr"),
        ("OOS Sharpe",     "1.32"),
        ("OOS MaxDD",      "-53 %  (−10 pp vs old v2)"),
        ("OOS final on $10k", "~$85 k (3.25 years)"),
    ]
    y = 0.22
    for k, v in oos:
        ax.text(0.08, y, f"{k:<18}", fontsize=10, family="monospace", weight="bold", color="#258")
        ax.text(0.29, y, v, fontsize=10, color="#222"); y -= 0.021

    ax.text(0.06, 0.12, "Changes from spec v2 → v3",
            fontsize=11, weight="bold", color="#c22")
    changes = [
        "• Added BTC 50d-MA rising condition (second bear layer)",
        "• Added market-breadth condition (third bear layer) — ≥ 5 of 9 coins must be above their own 50d-MA",
        "• Everything else identical — same universe, same weights, same rebal cadence, same trend sleeve",
    ]
    y = 0.09
    for line in changes:
        ax.text(0.08, y, line, fontsize=9, color="#700"); y -= 0.019

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def main():
    with PdfPages(OUT_LOCAL) as pdf:
        cover(pdf)
        results_table_page(pdf)
        frontier_page(pdf)
        winners_detail_page(pdf)
        new_spec_page(pdf)
    shutil.copy2(OUT_LOCAL, OUT_PUBLIC)
    print(f"Wrote  {OUT_LOCAL}")
    print(f"Copied {OUT_PUBLIC}")


if __name__ == "__main__":
    main()
