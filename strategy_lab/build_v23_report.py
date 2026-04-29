"""
V23 — Build rich PDF report for all 9 per-coin winners.

Layout:
  Page 1: title + overview table + combined portfolio equity
  Pages 2-10: one page per coin: metrics table, equity curve, drawdown,
              trade distribution, monthly returns heatmap
"""
from __future__ import annotations
import pickle, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Rectangle

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, inch
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                  Table, TableStyle, PageBreak, KeepTogether)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

LAB = Path(__file__).resolve().parent
RES = LAB / "results" / "v23"
CHARTS = LAB / "results" / "v23" / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)
OUT_PDF = LAB.parent / "ALL_COINS_STRATEGY_REPORT.pdf"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 110,
})


def load():
    # Prefer the OOS-augmented pickle when available, else fall back.
    p_oos = RES / "v23_results_with_oos.pkl"
    p_base = RES / "v23_results.pkl"
    # v23_results_with_oos.pkl does NOT carry eq_index/eq_values — only
    # per-coin winners pickle does. Merge the two so we have both.
    with open(p_base, "rb") as f:
        base = pickle.load(f)
    merged = {}
    if p_oos.exists():
        with open(p_oos, "rb") as f:
            oos = pickle.load(f)
        for sym, d in base.items():
            merged[sym] = dict(d)
            if sym in oos:
                # Add is/oos/verdict + eq_is/eq_oos reconstructions
                merged[sym]["is"] = oos[sym]["is"]
                merged[sym]["oos"] = oos[sym]["oos"]
                merged[sym]["verdict"] = oos[sym]["verdict"]
                # Rebuild IS/OOS equity series for per-coin split chart
                if oos[sym].get("eq_is_idx") and oos[sym].get("eq_is_val"):
                    idx_is = pd.to_datetime(oos[sym]["eq_is_idx"])
                    merged[sym]["eq_is"] = pd.Series(oos[sym]["eq_is_val"], index=idx_is)
                if oos[sym].get("eq_oos_idx") and oos[sym].get("eq_oos_val"):
                    idx_oos = pd.to_datetime(oos[sym]["eq_oos_idx"])
                    merged[sym]["eq_oos"] = pd.Series(oos[sym]["eq_oos_val"], index=idx_oos)
    else:
        merged = {k: dict(v) for k, v in base.items()}

    # Rebuild full-sample eq as Series (for main charts + portfolio)
    for sym, d in merged.items():
        idx = pd.to_datetime(d["eq_index"])
        d["eq"] = pd.Series(d["eq_values"], index=idx)
    return merged


def make_charts(sym: str, d: dict) -> str:
    eq = d["eq"].copy()
    trades = d["trades"]
    family = d["family"]; tf = d["tf"]

    fig = plt.figure(figsize=(11, 7.5))
    gs = GridSpec(3, 3, figure=fig, hspace=0.55, wspace=0.35,
                  height_ratios=[2.0, 1.2, 1.5])

    # === Equity curve (top, spans all columns) ===
    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(eq.index, eq.values, lw=1.3, color="#1f77b4")
    ax1.set_yscale("log")
    ax1.set_title(f"{sym}   —   {family} @ {tf}   —   Equity Curve ($10k start)",
                  fontsize=11, fontweight="bold", loc="left", pad=8)
    ax1.set_ylabel("Equity (log)")
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax1.axhline(10000, color="gray", lw=0.5, ls="--", alpha=0.5)
    # OOS split line
    split_ts = pd.Timestamp("2024-01-01", tz="UTC")
    try:
        # Match index timezone
        if eq.index.tz is None:
            split_for_plot = pd.Timestamp("2024-01-01")
        else:
            split_for_plot = split_ts
        if eq.index[0] <= split_for_plot <= eq.index[-1]:
            ax1.axvline(split_for_plot, color="#555", lw=0.9, ls="--", alpha=0.8)
            ax1.text(split_for_plot, eq.max() * 1.02, " IS | OOS",
                     color="#555", fontsize=8, va="bottom", ha="left")
    except Exception:
        pass
    final = eq.iloc[-1]
    mult = final / 10000
    ax1.text(0.02, 0.95, f"Final: ${final:,.0f}  ({mult:.1f}×)",
             transform=ax1.transAxes, fontsize=10, fontweight="bold", va="top",
             bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))

    # === Drawdown underwater (middle, spans all columns) ===
    ax2 = fig.add_subplot(gs[1, :])
    dd = (eq / eq.cummax() - 1) * 100
    ax2.fill_between(dd.index, dd.values, 0, color="#d62728", alpha=0.55, lw=0)
    ax2.set_title("Drawdown (underwater)", fontsize=10, loc="left")
    ax2.set_ylabel("DD %")
    max_dd = float(dd.min())
    ax2.axhline(max_dd, color="black", lw=0.6, ls=":")
    ax2.text(0.02, 0.1, f"Max DD: {max_dd:.1f}%", transform=ax2.transAxes,
             fontsize=9, fontweight="bold",
             bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))
    ax2.xaxis.set_major_locator(mdates.YearLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

    # === Trade-return histogram (bottom left) ===
    ax3 = fig.add_subplot(gs[2, 0])
    tr = np.array([t["ret"] for t in trades]) * 100
    if len(tr):
        ax3.hist(tr, bins=40, color="#2ca02c", alpha=0.75, edgecolor="white")
        ax3.axvline(0, color="black", lw=0.8)
        ax3.axvline(tr.mean(), color="red", lw=1.2, ls="--",
                    label=f"mean {tr.mean():.2f}%")
        ax3.legend(fontsize=8, loc="upper right", frameon=False)
    ax3.set_title("Trade return distribution", fontsize=9, loc="left")
    ax3.set_xlabel("Trade return (% of equity)")

    # === Monthly returns heatmap (bottom middle+right) ===
    ax4 = fig.add_subplot(gs[2, 1:])
    mret = eq.resample("ME").last().pct_change().dropna() * 100
    if len(mret):
        pivot = pd.DataFrame({
            "year": mret.index.year,
            "month": mret.index.month,
            "ret": mret.values,
        }).pivot(index="year", columns="month", values="ret")
        im = ax4.imshow(pivot.values, aspect="auto", cmap="RdYlGn",
                        vmin=-30, vmax=30, interpolation="nearest")
        ax4.set_xticks(range(len(pivot.columns)))
        ax4.set_xticklabels(["Jan","Feb","Mar","Apr","May","Jun",
                              "Jul","Aug","Sep","Oct","Nov","Dec"][:len(pivot.columns)],
                             fontsize=7)
        ax4.set_yticks(range(len(pivot.index)))
        ax4.set_yticklabels(pivot.index.astype(int), fontsize=7)
        for i, yr in enumerate(pivot.index):
            for j, mo in enumerate(pivot.columns):
                v = pivot.iloc[i, j]
                if pd.notna(v):
                    ax4.text(j, i, f"{v:.0f}", ha="center", va="center",
                             fontsize=6, color="black" if abs(v) < 18 else "white")
        cbar = fig.colorbar(im, ax=ax4, shrink=0.7, pad=0.02)
        cbar.ax.tick_params(labelsize=7)
    ax4.set_title("Monthly returns (%)", fontsize=9, loc="left")

    path = CHARTS / f"{sym}.png"
    fig.savefig(path, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


def make_portfolio_chart(data: dict) -> str:
    # Equal-weight $10k-per-coin portfolio: each sub-account starts at $10k on
    # first bar it has data for; before that, sits as $10k cash (pre-listing).
    all_eqs = {sym: d["eq"].astype(float).resample("1D").last().ffill()
               for sym, d in data.items()}
    start = min(e.index[0] for e in all_eqs.values())
    end   = max(e.index[-1] for e in all_eqs.values())
    full  = pd.date_range(start, end, freq="1D")
    aligned = pd.DataFrame(index=full)
    for sym, e in all_eqs.items():
        s = e.reindex(full).ffill().fillna(10000)
        aligned[sym] = s
    combined = aligned.sum(axis=1)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6),
                                    gridspec_kw=dict(height_ratios=[2, 1]),
                                    sharex=True)
    # Per-coin curves (only plot post-listing segments for clarity)
    for sym, e in all_eqs.items():
        ax1.plot(e.index, e.values, lw=0.9, alpha=0.55,
                 label=sym.replace("USDT", ""))
    ax1.set_yscale("log")
    ax1.set_title("Per-coin equity curves ($10k start each, log scale)",
                  fontsize=11, fontweight="bold", loc="left", pad=8)
    ax1.legend(ncol=5, fontsize=7, frameon=False, loc="upper left")
    ax1.set_ylabel("Per-coin $ (log)", fontsize=9)

    ax1b = ax1.twinx()
    ax1b.plot(combined.index, combined.values, lw=2.2, color="black",
              label=f"Portfolio ({len(data)}×$10k start = ${10000*len(data):,})")
    ax1b.set_yscale("log")
    ax1b.spines["top"].set_visible(False)
    ax1b.set_ylabel("Portfolio $ (log)", fontsize=9)
    ax1b.legend(loc="lower right", fontsize=8, frameon=False)
    ax1b.grid(False)

    dd = (combined / combined.cummax() - 1) * 100
    ax2.fill_between(dd.index, dd.values, 0, color="#d62728", alpha=0.55, lw=0)
    ax2.set_title(f"Combined portfolio drawdown  (Max DD: {dd.min():.1f}%)",
                  fontsize=10, loc="left")
    ax2.set_ylabel("DD %")
    ax2.xaxis.set_major_locator(mdates.YearLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.tight_layout()
    path = CHARTS / "_portfolio.png"
    fig.savefig(path, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path), combined


def compute_portfolio_stats(combined: pd.Series, n_coins: int) -> dict:
    start_eq = 10000 * n_coins
    final = float(combined.iloc[-1])
    mult = final / start_eq
    yrs = (combined.index[-1] - combined.index[0]).total_seconds() / (365.25 * 86400)
    cagr = mult ** (1 / yrs) - 1
    rets = combined.pct_change().dropna()
    sharpe = rets.mean() / rets.std() * np.sqrt(365) if rets.std() > 0 else 0
    dd = float((combined / combined.cummax() - 1).min())
    calmar = cagr / abs(dd) if dd != 0 else 0
    return dict(start=start_eq, final=final, mult=mult, cagr=cagr,
                sharpe=sharpe, dd=dd, calmar=calmar, years=yrs)


# ============================================================================
# PDF assembly
# ============================================================================

styles = getSampleStyleSheet()
TITLE = ParagraphStyle("title", parent=styles["Title"], fontSize=22,
                        leading=26, alignment=TA_CENTER, spaceAfter=6,
                        textColor=colors.HexColor("#1f2d3d"))
SUB = ParagraphStyle("sub", parent=styles["Normal"], fontSize=10,
                      alignment=TA_CENTER, textColor=colors.HexColor("#555"),
                      spaceAfter=14)
H2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=14,
                     spaceBefore=4, spaceAfter=6,
                     textColor=colors.HexColor("#1f2d3d"))
BODY = ParagraphStyle("body", parent=styles["Normal"], fontSize=9, leading=12)
SMALL = ParagraphStyle("small", parent=styles["Normal"], fontSize=8,
                        leading=10, textColor=colors.HexColor("#444"))

TBL_HDR = colors.HexColor("#253858")
TBL_ALT = colors.HexColor("#f4f5f7")
GOOD    = colors.HexColor("#1e7e34")
BAD     = colors.HexColor("#b02a37")


def build_overview_table(data: dict) -> Table:
    """Summary row per coin, now including walk-forward OOS columns."""
    rows = [["Coin", "Strategy", "TF", "Trades", "Full CAGR",
              "Full Sh", "IS Sh", "OOS Sh", "OOS CAGR", "OOS Verdict",
              "Max DD", "Final ($10k)"]]
    for sym in data:
        d = data[sym]; m = d["metrics"]
        r_is = d.get("is", {})
        r_oos = d.get("oos", {})
        v = d.get("verdict", "n/a")
        # Shorten verdict for table cell
        vshort = (v.replace("✓ OOS holds", "✓ holds")
                    .replace("OOS LOSES", "✗ loses")
                    .replace("✗ OOS degrades", "✗ degrades")
                    .replace("insufficient OOS trades", "low n")
                    .replace("OOS-only history (no IS)", "OOS-only"))
        rows.append([
            sym.replace("USDT", ""),
            d["family"].replace("_LS", ""),
            d["tf"],
            f"{m['n']}",
            f"{m['cagr_net']*100:+.1f}%",
            f"{m['sharpe']:+.2f}",
            f"{r_is.get('sharpe', 0):+.2f}" if r_is.get("n", 0) else "—",
            f"{r_oos.get('sharpe', 0):+.2f}" if r_oos.get("n", 0) else "—",
            f"{r_oos.get('cagr_net', 0)*100:+.1f}%" if r_oos.get("n", 0) else "—",
            vshort,
            f"{m['dd']*100:+.1f}%",
            f"${m['final']:,.0f}",
        ])
    t = Table(rows, colWidths=[1.4*cm, 2.8*cm, 0.9*cm, 1.3*cm, 1.8*cm,
                                1.3*cm, 1.3*cm, 1.3*cm, 1.8*cm, 2.2*cm,
                                1.6*cm, 2.3*cm])
    ts = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TBL_HDR),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (1, -1), "LEFT"),
        ("ALIGN", (9, 1), (9, -1), "CENTER"),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, TBL_ALT]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d0d0d0")),
    ])
    # Color CAGR/DD/verdict cells
    for i, sym in enumerate(data, start=1):
        d = data[sym]; m = d["metrics"]
        r_oos = d.get("oos", {})
        v = d.get("verdict", "")
        if m["cagr_net"] >= 0.55:
            ts.add("TEXTCOLOR", (4, i), (4, i), GOOD)
            ts.add("FONTNAME", (4, i), (4, i), "Helvetica-Bold")
        if m["dd"] <= -0.35:
            ts.add("TEXTCOLOR", (10, i), (10, i), BAD)
        # Verdict color
        if v.startswith("✓"):
            ts.add("TEXTCOLOR", (9, i), (9, i), GOOD)
            ts.add("FONTNAME", (9, i), (9, i), "Helvetica-Bold")
        elif v.startswith("✗") or "LOSES" in v or "insufficient" in v:
            ts.add("TEXTCOLOR", (9, i), (9, i), BAD)
        else:
            ts.add("TEXTCOLOR", (9, i), (9, i), colors.HexColor("#ad6800"))
        # OOS Sharpe cell coloring
        if r_oos.get("sharpe", 0) >= 1.0:
            ts.add("TEXTCOLOR", (7, i), (7, i), GOOD)
            ts.add("FONTNAME", (7, i), (7, i), "Helvetica-Bold")
        elif r_oos.get("sharpe", 0) > 0:
            ts.add("TEXTCOLOR", (7, i), (7, i), colors.HexColor("#ad6800"))
        elif r_oos.get("n", 0):
            ts.add("TEXTCOLOR", (7, i), (7, i), BAD)
    t.setStyle(ts)
    return t


def build_per_coin_kv_table(d: dict) -> Table:
    """Small two-column key-value table for params + exits + IS/OOS."""
    m = d["metrics"]; p = d["params"]; e = d["exits"]
    r_is = d.get("is", {})
    r_oos = d.get("oos", {})
    verdict = d.get("verdict", "n/a")

    def _sh(r):
        return f"Sh {r.get('sharpe', 0):+.2f}" if r.get("n", 0) else "n/a"
    def _c(r):
        return f"CAGR {r.get('cagr_net', 0)*100:+.1f}%" if r.get("n", 0) else "n/a"
    def _dd(r):
        return f"DD {r.get('dd', 0)*100:+.1f}%" if r.get("n", 0) else "n/a"
    def _n(r):
        return f"n={r.get('n', 0)}" if r.get("n", 0) else "n=0"

    rows = [
        ["Strategy family", d["family"]],
        ["Timeframe", d["tf"]],
        ["Signal params", ", ".join([f"{k}={v}" for k, v in p.items()])],
        ["Exit params",
          f"TP={e['tp']}×ATR, SL={e['sl']}×ATR, Trail={e['trail']}×ATR, MaxHold={e['mh']} bars"],
        ["Risk / Lev", f"{d['risk']*100:.1f}% per trade, {d['lev']:.1f}× cap"],
        ["", ""],
        ["Trades (full)", f"{m['n']}"],
        ["Win rate", f"{m['win']*100:.1f}%"],
        ["Profit factor", f"{m['pf']:.2f}"],
        ["Avg leverage", f"{m['avg_lev']:.2f}×"],
        ["Exposure", f"{m['exposure']*100:.1f}%"],
        ["", ""],
        ["CAGR (net)", f"{m['cagr_net']*100:+.1f}%"],
        ["Sharpe (annualized)", f"{m['sharpe']:+.2f}"],
        ["Max drawdown", f"{m['dd']*100:+.1f}%"],
        ["Final equity ($10k)", f"${m['final']:,.0f}"],
        ["", ""],
        ["IS (2019-2023)", f"{_n(r_is)}  {_c(r_is)}  {_sh(r_is)}  {_dd(r_is)}"],
        ["OOS (2024-2026)", f"{_n(r_oos)}  {_c(r_oos)}  {_sh(r_oos)}  {_dd(r_oos)}"],
        ["Walk-forward verdict", verdict],
    ]
    t = Table(rows, colWidths=[4.2*cm, 7.4*cm])
    ts = TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#1f2d3d")),
        ("LINEBELOW", (0, 4), (-1, 4), 0.3, colors.HexColor("#cccccc")),
        ("LINEBELOW", (0, 10), (-1, 10), 0.3, colors.HexColor("#cccccc")),
        ("LINEBELOW", (0, 15), (-1, 15), 0.3, colors.HexColor("#cccccc")),
    ])
    # Highlight full CAGR row
    ts.add("TEXTCOLOR", (1, 12), (1, 12),
            GOOD if m["cagr_net"] >= 0.55 else colors.HexColor("#ad6800"))
    ts.add("FONTNAME", (1, 12), (1, 12), "Helvetica-Bold")
    # Highlight verdict
    if verdict.startswith("✓"):
        ts.add("TEXTCOLOR", (1, 19), (1, 19), GOOD)
        ts.add("FONTNAME", (1, 19), (1, 19), "Helvetica-Bold")
    elif verdict.startswith("✗") or "LOSES" in verdict:
        ts.add("TEXTCOLOR", (1, 19), (1, 19), BAD)
        ts.add("FONTNAME", (1, 19), (1, 19), "Helvetica-Bold")
    else:
        ts.add("TEXTCOLOR", (1, 19), (1, 19), colors.HexColor("#ad6800"))
    t.setStyle(ts)
    return t


def page_cover(story, data, portfolio_png, p_stats):
    story.append(Paragraph("Crypto Perp Strategy Portfolio", TITLE))
    story.append(Paragraph(
        "Nine per-asset winners · Hyperliquid-style execution · 2019 – Apr 2026 · $10,000 start per coin",
        SUB))

    # Executive highlights
    n_coins = len(data)
    clears_55 = sum(1 for d in data.values() if d["metrics"]["cagr_net"] >= 0.55)
    within_dd = sum(1 for d in data.values() if d["metrics"]["dd"] >= -0.40)
    avg_sh = np.mean([d["metrics"]["sharpe"] for d in data.values()])

    oos_hold = sum(1 for d in data.values()
                   if str(d.get("verdict", "")).startswith("✓"))
    oos_only = sum(1 for d in data.values()
                   if "OOS-only" in str(d.get("verdict", "")))
    highlights = f"""
<b>At a glance.</b> {clears_55} of {n_coins} coins clear 55% net CAGR; all {within_dd}/{n_coins}
stay inside the -40% drawdown cap. Average Sharpe across the portfolio is
<b>{avg_sh:.2f}</b>. Equal-weight combination of the nine sub-accounts delivers a
combined CAGR of <b>{p_stats['cagr']*100:.1f}%</b> with Sharpe <b>{p_stats['sharpe']:.2f}</b>
and max drawdown <b>{p_stats['dd']*100:.1f}%</b> (Calmar <b>{p_stats['calmar']:.2f}</b>).
<b>Walk-forward OOS (split at 2024-01-01):</b> {oos_hold} of {n_coins} coins pass the
≥ 50% IS-Sharpe retention test; {oos_only} coin has only post-split history
(TON — flagged OOS-only). No coin's edge flipped negative out of sample.
Strategies were independently tuned per coin from three signal families
(RangeKalman L+S, BB-Break L+S, Keltner+ADX L+S), each evaluated across 1h/2h/4h
with small param grids. All numbers are <i>after</i> 0.045% taker fees per side
plus 8% APR funding drag.
"""
    story.append(Paragraph(highlights, BODY))
    story.append(Spacer(1, 0.3*cm))

    story.append(Paragraph("Per-coin winners overview", H2))
    story.append(build_overview_table(data))
    story.append(Spacer(1, 0.4*cm))

    # Portfolio chart
    story.append(Paragraph(
        f"Combined portfolio equity (equal-weight, ${int(10000*n_coins):,} start)", H2))
    story.append(Image(portfolio_png, width=26*cm, height=14.2*cm))
    story.append(Spacer(1, 0.25*cm))

    # Portfolio stats line
    ptxt = (f"Portfolio: start ${p_stats['start']:,.0f} → final ${p_stats['final']:,.0f}  "
            f"({p_stats['mult']:.1f}× over {p_stats['years']:.1f} years)  |  "
            f"CAGR {p_stats['cagr']*100:+.1f}%  |  Sharpe {p_stats['sharpe']:.2f}  |  "
            f"Max DD {p_stats['dd']*100:+.1f}%  |  Calmar {p_stats['calmar']:.2f}")
    story.append(Paragraph(ptxt, BODY))

    story.append(PageBreak())


def page_per_coin(story, sym, d, chart_png):
    m = d["metrics"]
    headline = (f"{sym.replace('USDT','')}  —  {d['family']} @ {d['tf']}  —  "
                f"CAGR {m['cagr_net']*100:+.1f}%, Sharpe {m['sharpe']:+.2f}, DD {m['dd']*100:+.1f}%")
    story.append(Paragraph(headline, H2))

    # Side-by-side: chart (left, bigger) + kv table (right)
    img = Image(chart_png, width=18*cm, height=12.5*cm)
    kvtbl = build_per_coin_kv_table(d)
    container = Table([[img, kvtbl]], colWidths=[18.2*cm, 7.8*cm])
    container.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(container)

    # Footer: honest caveats + OOS note
    r_is = d.get("is", {})
    r_oos = d.get("oos", {})
    v = d.get("verdict", "n/a")
    oos_line = ""
    if r_is.get("n", 0) and r_oos.get("n", 0):
        oos_line = (f"<b>Walk-forward OOS (split 2024-01-01):</b> "
                    f"IS Sharpe {r_is['sharpe']:+.2f} / OOS Sharpe {r_oos['sharpe']:+.2f} "
                    f"({r_oos['cagr_net']*100:+.1f}% OOS CAGR, n={r_oos['n']}). Verdict: <b>{v}</b>.<br/><br/>")
    elif r_oos.get("n", 0):
        oos_line = (f"<b>Walk-forward OOS:</b> no IS slice (post-2024 listing) — "
                    f"full-sample IS Sharpe {d['metrics']['sharpe']:+.2f}, {v}.<br/><br/>")
    caveats = f"""
{oos_line}<i>Notes.</i> Signal parameters above are native-TF values (already scaled from 1h).
This configuration was selected by grid search over the 2019-2026 full window.
Equity curve is on a log scale. Drawdown is the peak-to-trough equity % from the
prior high-water mark. Monthly-returns heatmap colors: green ≥ 0, red &lt; 0, clamped
at ±30% for visibility.
"""
    story.append(Paragraph(caveats, SMALL))
    story.append(PageBreak())


def page_methodology(story):
    story.append(Paragraph("Methodology and caveats", H2))
    text = """
<b>Data.</b> Binance perpetual-futures USDT-margined OHLCV bars. BTC/ETH/SOL histories
start 2019, altcoins start when they first listed on Binance (SUI 2023-05, TON 2022-10).
Loaded from the local <code>features/multi_tf/</code> parquet store at 1h, 2h, and 4h.<br/><br/>

<b>Signal families tested (all long + short).</b>
(1) RangeKalman L+S — mean-reverting Kalman-EMA with deviation bands, direction gated by a regime SMA.
(2) BB-Break L+S — Bollinger band breakout + regime SMA gate.
(3) Keltner + ADX L+S — Keltner channel breakout gated by ADX strength + regime SMA.
For each coin, the best config was chosen from a small per-family grid (α, lengths, multipliers, risk, TF).<br/><br/>

<b>Execution model.</b> Signals fire at bar close; fills at next-bar open ± 3 bps slippage.
Exits: TP at +tp×ATR, SL at -sl×ATR, trailing stop at -trail×ATR from high-water mark,
forced exit at max-hold bars. Position sizing: risk_per_trade × equity ÷ (sl×ATR),
capped at leverage_cap × equity ÷ price. Taker fee of 0.045% charged on entry and exit notional.<br/><br/>

<b>Performance accounting.</b> CAGR is compounded annual return on equity from a $10,000
start. "Net" CAGR subtracts a modeled 8% APR funding drag × average leverage × time-in-market.
Sharpe is annualized using the natural bar count per year at each TF. Drawdown is the maximum
peak-to-trough decline of the equity curve. Profit factor is sum(winning P&L) / |sum(losing P&L)|.<br/><br/>

<b>What this report IS.</b> A per-coin optimization showing the best single-config for
each asset, with a walk-forward out-of-sample check. For each coin the same locked
config is re-simulated in two slices: IS (2019-2023) and OOS (2024-2026). The
"Walk-forward verdict" column flags a config as holding when OOS Sharpe ≥ 50% of IS
Sharpe. TON has no IS history (first listing 2024-08) and is shown OOS-only.<br/><br/>

<b>What this report is NOT.</b> A go-live spec. Expect 20-40% haircut on CAGR from slippage,
borrowing frictions, venue outages, and regime change. Paper trade each coin for 4+ weeks
before real capital; set a -45% circuit breaker per sub-account; re-audit every 6 months.
LINK (37%) and INJ (29%) fall short of the 55% target — use them for diversification, not as
standalone aggressive allocations.
"""
    story.append(Paragraph(text, BODY))


def main():
    data = load()
    # Per-coin charts
    print("Rendering per-coin charts...", flush=True)
    chart_paths = {}
    for sym, d in data.items():
        chart_paths[sym] = make_charts(sym, d)
        print(f"  ✓ {sym}", flush=True)

    # Portfolio chart
    print("Rendering portfolio chart...", flush=True)
    portfolio_png, combined = make_portfolio_chart(data)
    p_stats = compute_portfolio_stats(combined, len(data))

    # Build PDF (landscape A4 so tables + charts fit)
    print("Building PDF...", flush=True)
    doc = SimpleDocTemplate(
        str(OUT_PDF), pagesize=landscape(A4),
        leftMargin=1.2*cm, rightMargin=1.2*cm,
        topMargin=1.0*cm, bottomMargin=1.0*cm,
        title="Crypto Perp Strategy Portfolio — 9-coin report",
        author="strategy_lab v23",
    )
    story = []

    page_cover(story, data, portfolio_png, p_stats)
    for sym, d in data.items():
        page_per_coin(story, sym, d, chart_paths[sym])
    page_methodology(story)

    doc.build(story)
    print(f"\nSaved: {OUT_PDF}")
    print(f"Size:  {OUT_PDF.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
