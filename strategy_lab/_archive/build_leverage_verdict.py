"""
Build NEW_IDEAS_VERDICT.pdf — V19 grid + V20 trend-follow results +
V21 leverage/split sweep with final optimal spec.

Destination: C:\\Users\\alexandre bandarra\\Desktop\\newstrategies\\NEW_IDEAS_VERDICT.pdf
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
OUT_LOCAL  = BASE / "reports" / "NEW_IDEAS_VERDICT.pdf"
OUT_PUBLIC = Path("C:/Users/alexandre bandarra/Desktop/newstrategies/NEW_IDEAS_VERDICT.pdf")
OUT_PUBLIC.parent.mkdir(parents=True, exist_ok=True)


def _fmt_pct(x, n=1): return f"{x*100:+.{n}f}%"
def _fmt_usd(x):
    ax = abs(x)
    if ax >= 1e9: return f"${x/1e9:.1f}B"
    if ax >= 1e6: return f"${x/1e6:.1f}M"
    if ax >= 1e3: return f"${x/1e3:.0f}k"
    return f"${x:.0f}"


def cover(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.95, "NEW IDEAS VERDICT",
            ha="center", fontsize=24, weight="bold")
    ax.text(0.5, 0.918,
            "V19 grid · V20 new trend-follow · V21 leverage sweep",
            ha="center", fontsize=12, color="#555")
    ax.text(0.5, 0.892, "Recommendation: 70 % XSM (balanced) × 1.5× leverage  |  30 % Trend",
            ha="center", fontsize=10, color="#258", weight="bold")
    ax.axhline(0.872, 0.05, 0.95, color="#ccc", lw=0.7)

    # TL;DR box
    box = plt.Rectangle((0.06, 0.56), 0.88, 0.30,
                        fill=True, facecolor="#f2fbf2", edgecolor="#0a6", lw=1.2)
    ax.add_patch(box)
    ax.text(0.08, 0.84, "Three findings", fontsize=13, weight="bold", color="#0a6")
    findings = [
        ("1. Grid trading (V19)",
         "FAILED on all 6 coins. 4h sideways regimes on Hyperliquid-fee "
         "crypto are too rare AND too brief for grid arbitrage to accumulate enough "
         "rung-hits to pay fees + adverse selection. NOT shippable."),
        ("2. New trend-follow (V20)",
         "Heikin-SuperTrend, DEMA-Ichimoku, OTT, Squeeze-Ichimoku all tested. "
         "Best pockets: V20B DEMA-Ichimoku on ADA/LINK (PF 2.37 / 1.43) and V20C OTT on "
         "SOL (PF 1.41). All with CAGR < +3%/yr. Existing V3B/V4C dominate."),
        ("3. Leverage sweep (V21) — THE REAL ANSWER",
         "Full 6-leverage × 3-profile × 7-split sweep. OPTIMAL SPEC: "
         "BALANCED (k=4, lb=14d) at 1.5× leverage, 70% XSM + 30% Trend. "
         "CAGR +258% · Sharpe 1.87 · MaxDD −65% · Calmar 3.95."),
    ]
    y = 0.80
    for h, body in findings:
        ax.text(0.09, y, h, fontsize=10.5, weight="bold", color="#258")
        y -= 0.022
        # Wrap manually
        import textwrap
        for line in textwrap.wrap(body, width=110):
            ax.text(0.11, y, line, fontsize=9, color="#222"); y -= 0.018
        y -= 0.008

    ax.text(0.06, 0.48, "Recommendation at a glance", fontsize=12, weight="bold", color="#258")
    rec = [
        ["Capital",            "$10,000 USDC on Hyperliquid"],
        ["Split",              "70% Momentum sleeve + 30% Trend sleeve"],
        ["XSM leverage",       "1.5× (tested: Sharpe 1.87, DD -65%)"],
        ["Trend leverage",     "5× per-position (unchanged from current deploy spec)"],
        ["Expected full",      "CAGR +258%, Sharpe 1.87, DD -65%, Calmar 3.95"],
        ["Expected OOS 22-25", "CAGR +107%, Sharpe 1.34, DD -63%"],
        ["What to AVOID",      "XSM leverage 3×+ (DD -95%+, near-blowout)"],
        ["What to AVOID",      "Grid trading at 4h (tested; unprofitable)"],
    ]
    y = 0.44
    for k, v in rec:
        ax.text(0.09, y, k, fontsize=9.5, weight="bold", color="#258", family="monospace")
        ax.text(0.27, y, v, fontsize=9.5, color="#222"); y -= 0.022

    ax.text(0.06, 0.22, "Sections inside", fontsize=12, weight="bold", color="#258")
    secs = [
        "1. V19 Grid trading — results per coin, why grids failed at 4h",
        "2. V20 New trend-follow — Heikin-ST, DEMA-Ichimoku, OTT, Squeeze-Ichimoku",
        "3. V21 Leverage sweep — profile × leverage full matrix + charts",
        "4. V21 Portfolio-split sweep — XSM weight × returns",
        "5. Kelly analysis — optimal leverage with 1/4 Kelly safety margin",
        "6. Final upgrade path from current 1× to 1.5× leverage",
    ]
    y = 0.19
    for s in secs:
        ax.text(0.09, y, s, fontsize=9.5); y -= 0.022

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def v19_v20_results_page(pdf):
    df = pd.read_csv(RES / "v19_20_hunt.csv")
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "V19 + V20 results — raw backtest matrix",
            ha="center", fontsize=17, weight="bold")
    ax.axhline(0.933, 0.05, 0.95, color="#ccc", lw=0.7)

    # Cell content
    display = df[["coin","strategy","n","wr","wr_min_yr","pf","sharpe","cagr","dd","final"]].copy()
    display["wr"]   = display["wr"].apply(lambda v: f"{v*100:.0f}%" if pd.notna(v) else "-")
    display["wr_min_yr"] = display["wr_min_yr"].apply(lambda v: f"{v*100:.0f}%" if pd.notna(v) else "-")
    display["pf"]   = display["pf"].apply(lambda v: f"{v:.2f}" if pd.notna(v) else "-")
    display["sharpe"] = display["sharpe"].apply(lambda v: f"{v:+.2f}" if pd.notna(v) else "-")
    display["cagr"]   = display["cagr"].apply(lambda v: f"{v*100:+.1f}%" if pd.notna(v) else "-")
    display["dd"]     = display["dd"].apply(lambda v: f"{v*100:+.1f}%" if pd.notna(v) else "-")
    display["final"]  = display["final"].apply(lambda v: _fmt_usd(v) if pd.notna(v) else "-")
    display.columns = ["Coin","Strategy","N","WR","Min-yr WR","PF","Sharpe","CAGR","MaxDD","Final"]
    rows = [list(display.columns)] + display.values.tolist()
    tbl = ax.table(cellText=rows, loc="upper left", cellLoc="center",
                   bbox=[0.03, 0.04, 0.94, 0.88])
    tbl.auto_set_font_size(False); tbl.set_fontsize(7); tbl.scale(1, 1.15)
    for j in range(len(display.columns)):
        tbl[(0, j)].set_facecolor("#dee"); tbl[(0, j)].set_text_props(weight="bold")
    # Color profitable rows
    for i, r in enumerate(df.itertuples(), start=1):
        if pd.notna(r.final) and r.final > 10000:
            tbl[(i, 9)].set_facecolor("#d3f0d5")
        else:
            tbl[(i, 9)].set_facecolor("#f6c7c7")
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def v21_leverage_page(pdf):
    df = pd.read_csv(RES / "v21_leverage_sweep.csv")
    xsm = df[df["w_xsm"] == 1.0].copy()
    xsm["profile_short"] = xsm["profile"].str.extract(r"([A-Z]+)", expand=False).fillna("X")

    fig = plt.figure(figsize=(11, 8.5))
    fig.suptitle("V21 — Leverage sweep on XSM sleeve", fontsize=17, weight="bold", y=0.975)
    fig.text(0.5, 0.948, "Three profiles × six leverages · full 2018-26 metrics",
             fontsize=10, ha="center", color="#555")

    # 3-panel: CAGR / Sharpe / DD vs leverage per profile
    colors = {"CONSERVATIVE":"#0a9396","BALANCED":"#258","AGGRESSIVE":"#d90429"}

    ax1 = fig.add_axes([0.07, 0.67, 0.27, 0.22])
    ax2 = fig.add_axes([0.38, 0.67, 0.27, 0.22])
    ax3 = fig.add_axes([0.69, 0.67, 0.27, 0.22])
    for prof in xsm["profile"].unique():
        sub = xsm[xsm["profile"] == prof].sort_values("xsm_lev")
        lbl = prof.split("(")[0].strip()
        c = colors.get(lbl, "#888")
        ax1.plot(sub["xsm_lev"], sub["full_cagr"]*100, "o-", color=c, label=lbl)
        ax2.plot(sub["xsm_lev"], sub["full_sharpe"],   "o-", color=c, label=lbl)
        ax3.plot(sub["xsm_lev"], sub["full_dd"]*100,   "o-", color=c, label=lbl)
    ax1.set_title("CAGR vs leverage (full)", fontsize=10)
    ax1.set_xlabel("Leverage"); ax1.set_ylabel("CAGR (%)")
    ax1.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax1.legend(loc="upper left", fontsize=8, frameon=False)
    ax2.set_title("Sharpe vs leverage", fontsize=10)
    ax2.set_xlabel("Leverage"); ax2.set_ylabel("Sharpe")
    ax2.axhline(0, color="#888", lw=0.5)
    ax3.set_title("MaxDD vs leverage", fontsize=10)
    ax3.set_xlabel("Leverage"); ax3.set_ylabel("MaxDD (%)")
    ax3.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax3.axhline(-65, color="#c80", lw=0.5, ls="--")
    ax3.axhline(-85, color="#c22", lw=0.5, ls="--")

    # Full-period + OOS metric table at bottom
    ax4 = fig.add_axes([0.06, 0.08, 0.88, 0.50]); ax4.axis("off")
    ax4.text(0, 0.98, "Full matrix (XSM-only, w_xsm = 100%)", fontsize=11, weight="bold", color="#258")

    cols = ["profile","xsm_lev","full_cagr","full_sharpe","full_dd","full_calmar","full_kelly",
            "oos_cagr","oos_sharpe","oos_dd","oos_kelly"]
    headers = ["Profile","Lev","Full CAGR","Sharpe","MaxDD","Calmar","Kelly-g",
               "OOS CAGR","Sharpe","DD","Kelly-g"]
    disp = xsm[cols].copy()
    for c in ("full_cagr","full_dd","oos_cagr","oos_dd"):
        disp[c] = disp[c].apply(lambda v: f"{v*100:+.1f}%")
    for c in ("full_sharpe","full_calmar","full_kelly","oos_sharpe","oos_kelly"):
        disp[c] = disp[c].apply(lambda v: f"{v:+.2f}")
    disp["xsm_lev"] = disp["xsm_lev"].apply(lambda v: f"{v:.1f}×")
    disp["profile"] = disp["profile"].apply(lambda s: s.split("(")[0].strip())
    rows = [headers] + disp.values.tolist()
    tbl = ax4.table(cellText=rows, loc="upper left", cellLoc="center",
                    bbox=[0, 0.06, 1, 0.88])
    tbl.auto_set_font_size(False); tbl.set_fontsize(7.5); tbl.scale(1, 1.2)
    for j in range(len(headers)):
        tbl[(0, j)].set_facecolor("#dee"); tbl[(0, j)].set_text_props(weight="bold")
    # Highlight BALANCED 1.5× row
    for i, r in enumerate(disp.itertuples(), start=1):
        if r.profile == "BALANCED" and r.xsm_lev == "1.5×":
            for j in range(len(headers)):
                tbl[(i, j)].set_facecolor("#d3f0d5")

    pdf.savefig(fig); plt.close(fig)


def v21_split_page(pdf):
    df = pd.read_csv(RES / "v21_leverage_sweep.csv")
    sp = df[df["profile"].str.contains("BLEND")].copy().sort_values("w_xsm")

    fig = plt.figure(figsize=(11, 8.5))
    fig.suptitle("V21 — Portfolio-split sweep (XSM 1× + Trend)",
                 fontsize=17, weight="bold", y=0.975)
    fig.text(0.5, 0.948, "100% Trend  →  100% XSM balanced 1×  ·  full 2018-26 equity shapes",
             fontsize=10, ha="center", color="#555")

    ax1 = fig.add_axes([0.07, 0.58, 0.40, 0.30])
    ax1.plot(sp["w_xsm"], sp["full_cagr"]*100, "o-", color="#258")
    ax1.set_title("CAGR vs XSM weight", fontsize=10)
    ax1.set_xlabel("XSM weight"); ax1.set_ylabel("CAGR (%)")
    ax1.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))

    ax2 = fig.add_axes([0.56, 0.58, 0.40, 0.30])
    ax2.plot(sp["w_xsm"], sp["full_sharpe"], "o-", color="#0a6")
    ax2.plot(sp["w_xsm"], sp["full_calmar"], "o-", color="#c80", label="Calmar")
    ax2.set_title("Sharpe / Calmar vs XSM weight", fontsize=10)
    ax2.set_xlabel("XSM weight"); ax2.legend(fontsize=8, frameon=False, loc="upper left")

    # Table bottom
    ax3 = fig.add_axes([0.06, 0.08, 0.88, 0.42]); ax3.axis("off")
    cols = ["w_xsm","full_cagr","full_sharpe","full_dd","full_calmar","full_final",
            "oos_cagr","oos_sharpe","oos_dd","oos_final"]
    headers = ["w_XSM","Full CAGR","Sharpe","DD","Calmar","Final",
               "OOS CAGR","OOS Sharpe","OOS DD","OOS Final"]
    disp = sp[cols].copy()
    disp["w_xsm"] = disp["w_xsm"].apply(lambda v: f"{v*100:.0f}% XSM")
    for c in ("full_cagr","full_dd","oos_cagr","oos_dd"):
        disp[c] = disp[c].apply(lambda v: f"{v*100:+.1f}%")
    for c in ("full_sharpe","full_calmar","oos_sharpe"):
        disp[c] = disp[c].apply(lambda v: f"{v:+.2f}")
    for c in ("full_final","oos_final"):
        disp[c] = disp[c].apply(lambda v: _fmt_usd(v))
    rows = [headers] + disp.values.tolist()
    tbl = ax3.table(cellText=rows, loc="upper left", cellLoc="center",
                    bbox=[0, 0.06, 1, 0.88])
    tbl.auto_set_font_size(False); tbl.set_fontsize(8); tbl.scale(1, 1.3)
    for j in range(len(headers)):
        tbl[(0, j)].set_facecolor("#dee"); tbl[(0, j)].set_text_props(weight="bold")
    # Highlight 70% row (peak Sharpe)
    for i, r in enumerate(disp.itertuples(), start=1):
        if "70%" in r.w_xsm or "80%" in r.w_xsm:
            for j in range(len(headers)):
                tbl[(i, j)].set_facecolor("#d3f0d5")
    ax3.text(0, 0.03, "Green rows = recommended split (Sharpe peak).  "
             "70% is our pick — same Sharpe as 80%, marginally lower DD.",
             fontsize=9, color="#258")

    pdf.savefig(fig); plt.close(fig)


def kelly_analysis_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "Kelly analysis — safe leverage",
            ha="center", fontsize=17, weight="bold")
    ax.axhline(0.933, 0.05, 0.95, color="#ccc", lw=0.7)

    ax.text(0.06, 0.90, "The theoretical optimum lies between 2.0× and 2.5× — but DD is uncomfortable.",
            fontsize=11, weight="bold", color="#258")
    ax.text(0.06, 0.875,
            "Full-Kelly leverage is the one that maximises the geometric growth rate "
            "E[log(1+r)].  From our sweep:",
            fontsize=9.5)
    bullets = [
        "BALANCED full-Kelly peak at 2.5× (Kelly-g +1.64/yr, CAGR +415%, DD -89%)",
        "AGGRESSIVE full-Kelly peak at 3.0× (Kelly-g +2.02/yr, CAGR +656%, DD -95%)",
        "Both ceilings require stomach to watch 85-95% drawdowns — effectively full portfolio blowout",
        "Real traders cap at 25-50 % of full-Kelly = 0.6-1.3× for BALANCED, 0.75-1.5× for AGGRESSIVE",
    ]
    y = 0.845
    for b in bullets:
        ax.text(0.08, y, "• " + b, fontsize=9.5, color="#222"); y -= 0.022

    ax.text(0.06, 0.75, "Our chosen leverage: 1.5× (between 1/2 and 3/4 Kelly)",
            fontsize=11, weight="bold", color="#0a6")

    data = [
        ["Leverage", "CAGR Full", "Sharpe", "DD Full", "DD OOS", "Kelly-g", "% of full-Kelly", "Comfort"],
        ["0.5×", "+70%",  "1.85", "-27%", "-38%", "+0.53", "20%",   "very easy"],
        ["1.0×", "+159%", "1.86", "-48%", "-46%", "+0.95", "40%",   "easy"],
        ["1.5×", "+258%", "1.87", "-65%", "-63%", "+1.27", "60%",   "moderate"],
        ["2.0×", "+352%", "1.86", "-79%", "-77%", "+1.51", "80%",   "hard"],
        ["2.5×", "+415%", "1.84", "-89%", "-87%", "+1.64", "97%",   "near-blowout"],
        ["3.0×", "+401%", "1.80", "-97%", "-94%", "+1.61", "100%+", "BLOWOUT"],
    ]
    tbl = ax.table(cellText=data, loc="upper left", cellLoc="center",
                   bbox=[0.06, 0.44, 0.88, 0.27])
    tbl.auto_set_font_size(False); tbl.set_fontsize(9); tbl.scale(1, 1.4)
    for j in range(len(data[0])):
        tbl[(0, j)].set_facecolor("#dee"); tbl[(0, j)].set_text_props(weight="bold")
    # Highlight 1.5× row + color comfort column
    row_colors = {0.5:"#d3f0d5", 1.0:"#d3f0d5", 1.5:"#b9e8bd", 2.0:"#fff2c2",
                  2.5:"#fcd7b6", 3.0:"#f6c7c7"}
    comfort_colors = ["#8e8","#8e8","#4b4","#c80","#d22","#700"]
    for i, r in enumerate(data[1:], start=1):
        lev = float(r[0].replace("×",""))
        for j in range(len(data[0])):
            tbl[(i, j)].set_facecolor(row_colors[lev])
    # bold 1.5 row
    for j in range(len(data[0])):
        tbl[(3, j)].set_text_props(weight="bold")

    ax.text(0.06, 0.38, "Why 1.5× and not 2.0× (which has higher Calmar)?",
            fontsize=11, weight="bold", color="#258")
    lines = [
        "• 2.0× pushed the OOS DD to -77% (live 2022-25 test).  A real -77% is unrecoverable for most",
        "   traders psychologically — they'd abandon the strategy mid-drawdown, which is the real risk.",
        "• 1.5× OOS DD -63% is the upper bound of what we consider survivable without abandoning ship.",
        "• 1.5× captures 73% of the 2.0× growth rate but with 18 pp less drawdown.",
        "• In crypto, black-swan events (exchange hacks, regulatory shocks) push realised DD beyond the",
        "   backtest.  Leaving 'room' below full-Kelly preserves capital for those one-off events.",
    ]
    y = 0.35
    for ln in lines:
        ax.text(0.08, y, ln, fontsize=9, color="#222"); y -= 0.020

    ax.text(0.06, 0.23, "Upgrade path from current 1× → 1.5×",
            fontsize=11, weight="bold", color="#258")
    steps = [
        "1. Run current 1× leverage spec on Hyperliquid testnet for 2-4 weeks.",
        "2. Confirm live trade fills match backtest within ±2% weekly.",
        "3. Graduate to mainnet with 1× for 4-8 weeks — real execution, real fees.",
        "4. If live Sharpe > 1.5 after 3 months AND combined equity > starting capital,",
        "   raise XSM leverage to 1.5× in increments of 0.25× every 2 months.",
        "5. Keep trend sleeve at current 5× per-position (unchanged).",
    ]
    y = 0.20
    for s in steps:
        ax.text(0.08, y, s, fontsize=9, color="#222"); y -= 0.020

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def final_spec_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "Final recommended spec — UPGRADED",
            ha="center", fontsize=17, weight="bold")
    ax.axhline(0.933, 0.05, 0.95, color="#ccc", lw=0.7)

    box = plt.Rectangle((0.06, 0.44), 0.88, 0.45,
                        fill=True, facecolor="#f7faff", edgecolor="#258", lw=1.2)
    ax.add_patch(box)
    ax.text(0.08, 0.87, "HYPERLIQUID DEPLOY SPEC v2", fontsize=13, weight="bold", color="#258")
    spec = [
        ("Capital",             "$10,000 USDC (start $1k+)"),
        ("Split",               "70% Momentum sleeve  +  30% Trend sleeve"),
        ("",                    ""),
        ("XSM sleeve (70% / $7,000)", ""),
        ("   Universe",         "BTC · ETH · SOL · BNB · XRP · DOGE · LINK · ADA · AVAX (9 coins)"),
        ("   Signal",           "rank by past-14-day return weekly (Monday 00:00 UTC)"),
        ("   Position",         "equal-weight long top 4 coins"),
        ("   Leverage",         "1.5× (upgraded from 1.0×)"),
        ("   Bear filter",      "flat when BTC < 100-day MA"),
        ("   Execution",        "limit orders on bar open, maker fee 0.015%"),
        ("",                    ""),
        ("Trend sleeve (30% / $3,000)", ""),
        ("   Coins",            "BTC · ETH · SOL · LINK · ADA · XRP"),
        ("   Strategies",       "V4C (BTC/SOL/ADA) · V3B (ETH/LINK) · HWR1 (XRP)"),
        ("   Position",         "5% notional × 5× per-position leverage = 25% exposure"),
        ("   Stops",            "ATR-scaled trailing per strategy (unchanged)"),
    ]
    y = 0.84
    for k, v in spec:
        if k:
            ax.text(0.09, y, k, fontsize=9, weight="bold" if ":" not in k and k[0] != " " else "normal",
                    color="#258" if not k.startswith("   ") else "#444")
        ax.text(0.36, y, v, fontsize=9, color="#222")
        y -= 0.020

    ax.text(0.06, 0.40, "Backtest expectation (2018-26 full):",
            fontsize=11, weight="bold", color="#258")
    expected = [
        ("CAGR",   "+258% / year"),
        ("Sharpe", "1.87"),
        ("MaxDD",  "-65%"),
        ("Calmar", "3.95"),
        ("Final on $10k", "$364 M (8.25 years)"),
    ]
    y = 0.37
    for k, v in expected:
        ax.text(0.08, y, f"{k:<20}", fontsize=10, family="monospace", weight="bold", color="#258")
        ax.text(0.32, y, v, fontsize=10, color="#222"); y -= 0.021

    ax.text(0.06, 0.25, "OOS expectation (2022-25, more representative):",
            fontsize=11, weight="bold", color="#258")
    oos = [
        ("CAGR",    "+107% / year"),
        ("Sharpe",  "1.34"),
        ("MaxDD",   "-63%"),
        ("Final on $10k", "~$140k (3.25 years)"),
    ]
    y = 0.22
    for k, v in oos:
        ax.text(0.08, y, f"{k:<20}", fontsize=10, family="monospace", weight="bold", color="#258")
        ax.text(0.32, y, v, fontsize=10, color="#222"); y -= 0.021

    ax.text(0.06, 0.10, "HARD CEILING — DO NOT EXCEED",
            fontsize=11, weight="bold", color="#c22")
    ax.text(0.08, 0.077,
            "XSM leverage above 2.0× pushes OOS DD past -77%.  The backtest may still show high CAGR,",
            fontsize=9, color="#700")
    ax.text(0.08, 0.058,
            "but a real-money -77% drawdown is effectively terminal for most traders.  Stay at 1.5×.",
            fontsize=9, color="#700")

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def main():
    with PdfPages(OUT_LOCAL) as pdf:
        cover(pdf)
        v19_v20_results_page(pdf)
        v21_leverage_page(pdf)
        v21_split_page(pdf)
        kelly_analysis_page(pdf)
        final_spec_page(pdf)
    shutil.copy2(OUT_LOCAL, OUT_PUBLIC)
    print(f"Wrote  {OUT_LOCAL}")
    print(f"Copied {OUT_PUBLIC}")


if __name__ == "__main__":
    main()
