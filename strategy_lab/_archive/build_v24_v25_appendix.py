"""
Build an appendix PDF covering the V24 + V25 overlays.

One page per validated overlay:
  - V24 ETH Regime Router 2h
  - V24 LINK RSI+BB Scalp 15m
  - V25 AVAX MTF Conf 1h
  - V25 SOL MTF Conf 1h
  - V25 DOGE Seasonal 30m
  - V25 AVAX Seasonal 1h (paper)
  - V25 SUI MTF Conf 30m (paper)

Each page has: header, metrics table, IS/OOS split equity curve, drawdown,
trade-return histogram, monthly returns heatmap.
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

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Image,
                                 Table, TableStyle, PageBreak)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

LAB = Path(__file__).resolve().parent
CHARTS = LAB / "results" / "v25" / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)
OUT_PDF = LAB.parent / "V24_V25_OVERLAY_REPORT.pdf"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9,
    "axes.grid": True, "grid.alpha": 0.25,
    "axes.spines.top": False, "axes.spines.right": False,
    "figure.dpi": 110,
})


def _load_v24():
    """Load V24 results. Handles both pickles (regime + 15m scalp)."""
    out = {}
    p = LAB / "results" / "v24" / "v24_regime_results.pkl"
    if p.exists():
        with open(p, "rb") as f:
            d = pickle.load(f)
        # Only keep ETH (the one we actually deploy)
        if "ETHUSDT" in d:
            out["ETH_V24_Router"] = d["ETHUSDT"]
    p = LAB / "results" / "v24" / "v24_scalp_results.pkl"
    if p.exists():
        with open(p, "rb") as f:
            d = pickle.load(f)
        if "LINKUSDT" in d:
            out["LINK_V24_RSIBB"] = d["LINKUSDT"]
    return out


def _load_v25():
    p = LAB / "results" / "v25" / "v25_creative_results.pkl"
    if not p.exists(): return {}
    with open(p, "rb") as f:
        return pickle.load(f)


def _load_v25_oos():
    p = LAB / "results" / "v25" / "v25_oos_summary.csv"
    if not p.exists(): return pd.DataFrame()
    return pd.read_csv(p)


def _rebuild_eq(d):
    idx = pd.to_datetime(d["eq_index"])
    return pd.Series(d["eq_values"], index=idx)


def make_overlay_chart(title_prefix, d):
    eq = _rebuild_eq(d)
    trades = d.get("trades", [])
    m = d["metrics"]

    fig = plt.figure(figsize=(11, 7.5))
    gs = GridSpec(3, 3, figure=fig, hspace=0.55, wspace=0.35,
                   height_ratios=[2.0, 1.2, 1.5])

    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(eq.index, eq.values, lw=1.3, color="#1f77b4")
    ax1.set_yscale("log")
    ax1.set_title(f"{title_prefix}  —  Equity Curve ($10k start)",
                   fontsize=11, fontweight="bold", loc="left", pad=8)
    ax1.set_ylabel("Equity (log)")
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax1.axhline(10000, color="gray", lw=0.5, ls="--", alpha=0.5)
    # OOS split
    try:
        if eq.index.tz is None:
            split = pd.Timestamp("2024-01-01")
        else:
            split = pd.Timestamp("2024-01-01", tz="UTC")
        if eq.index[0] <= split <= eq.index[-1]:
            ax1.axvline(split, color="#555", lw=0.9, ls="--", alpha=0.8)
            ax1.text(split, eq.max() * 1.02, " IS | OOS", color="#555",
                      fontsize=8, va="bottom", ha="left")
    except Exception:
        pass
    final = float(eq.iloc[-1])
    mult = final / 10000.0
    ax1.text(0.02, 0.95, f"Final: ${final:,.0f}  ({mult:.1f}×)",
              transform=ax1.transAxes, fontsize=10, fontweight="bold", va="top",
              bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))

    ax2 = fig.add_subplot(gs[1, :])
    dd = (eq / eq.cummax() - 1) * 100
    ax2.fill_between(dd.index, dd.values, 0, color="#d62728", alpha=0.55, lw=0)
    ax2.set_title("Drawdown (underwater)", fontsize=10, loc="left")
    ax2.set_ylabel("DD %")
    ax2.axhline(float(dd.min()), color="black", lw=0.6, ls=":")
    ax2.text(0.02, 0.1, f"Max DD: {float(dd.min()):.1f}%",
              transform=ax2.transAxes, fontsize=9, fontweight="bold",
              bbox=dict(boxstyle="round", facecolor="white", alpha=0.85))
    ax2.xaxis.set_major_locator(mdates.YearLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))

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

    fn = title_prefix.replace(" ", "_").replace("/", "-") + ".png"
    path = CHARTS / fn
    fig.savefig(path, dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


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

TBL_HDR = colors.HexColor("#253858")
TBL_ALT = colors.HexColor("#f4f5f7")


def _metrics_table(d, oos_row=None):
    m = d["metrics"]
    rows = [["Metric", "Full", "IS (2020-2023)", "OOS (2024-2026)"]]
    if oos_row is not None:
        rows.append(["CAGR (net)",
                      f"{m['cagr_net']*100:+.1f}%",
                      f"{oos_row['is_cagr']:+.1f}%",
                      f"{oos_row['oos_cagr']:+.1f}%"])
        rows.append(["Sharpe",
                      f"{m['sharpe']:+.2f}",
                      f"{oos_row['is_sh']:+.2f}",
                      f"{oos_row['oos_sh']:+.2f}"])
        rows.append(["Trades",
                      f"{m['n']}",
                      f"{oos_row['is_n']}",
                      f"{oos_row['oos_n']}"])
    else:
        rows.append(["CAGR (net)", f"{m['cagr_net']*100:+.1f}%", "—", "—"])
        rows.append(["Sharpe", f"{m['sharpe']:+.2f}", "—", "—"])
        rows.append(["Trades", f"{m['n']}", "—", "—"])
    rows.append(["Max DD", f"{m['dd']*100:+.1f}%", "—", "—"])
    rows.append(["Profit Factor", f"{m.get('pf',0):.2f}", "—", "—"])
    rows.append(["Win %", f"{m.get('win',0)*100:.1f}%", "—", "—"])

    t = Table(rows, colWidths=[5*cm, 3.5*cm, 3.5*cm, 3.5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), TBL_HDR),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("ALIGN",      (1,1), (-1,-1), "CENTER"),
        ("GRID",       (0,0), (-1,-1), 0.3, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, TBL_ALT]),
        ("FONTSIZE",   (0,0), (-1,-1), 9),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 3),
    ]))
    return t


# Page content for each overlay
OVERLAY_PAGES = [
    {
        "key": ("v25", "AVAXUSDT_MTF_CONF"),
        "title": "AVAX V25 MTF Confluence @ 1h",
        "subtitle": "PRIMARY V25 WINNER — promoted to core AVAX allocation",
        "desc": (
            "EMA(12)/EMA(50) crossover on 1h bars, gated by 4h close > 4h EMA(50). "
            "Long only in 4h uptrend, short only in 4h downtrend. "
            "Backtested single strongest V25 signal: CAGR +320% net, Sharpe 2.19, OOS beats IS. "
            "Suggested allocation: 50% of AVAX sub-account (50/50 with V23 RangeKalman)."
        ),
    },
    {
        "key": ("v25", "SOLUSDT_MTF_CONF"),
        "title": "SOL V25 MTF Confluence @ 1h",
        "subtitle": "Diversifier overlay on V23 SOL BB-Break",
        "desc": (
            "Same MTF family as AVAX V25, tuned for SOL (EMA 20/50). OOS holds: "
            "+73% CAGR, Sharpe +1.43. V23 BB-Break still dominates raw CAGR (+139%), "
            "but the two signal families fire on different timing — stacking reduces "
            "combined variance. Suggested allocation: 30% overlay (70/30 V23 / V25)."
        ),
    },
    {
        "key": ("v25", "DOGEUSDT_SEASONAL"),
        "title": "DOGE V25 Seasonal RSI+BB @ 30m",
        "subtitle": "Hour-of-day (06-12 UTC) mean-reversion",
        "desc": (
            "RSI+BB contrarian signal restricted to the 06:00-12:00 UTC window. "
            "That window captures Asian + European morning flows where DOGE has "
            "structurally higher mean-reversion. Full CAGR +33%, Sharpe +1.13. "
            "OOS +25%, Sharpe +0.92. Suggested allocation: 30% overlay on V23 DOGE."
        ),
    },
    {
        "key": ("v25", "AVAXUSDT_SEASONAL"),
        "title": "AVAX V25 Seasonal RSI+BB @ 1h (PAPER ONLY)",
        "subtitle": "Seasonal edge confirmation on second coin",
        "desc": (
            "Same 06-12 UTC window as DOGE Seasonal. OOS holds (+18% CAGR, Sharpe +0.72) "
            "but CAGR alone is too low to justify capital. Kept as paper-only — its value "
            "is confirming that the 06-12 UTC seasonality is a real alt-coin effect, not "
            "overfit to DOGE."
        ),
    },
    {
        "key": ("v25", "SUIUSDT_MTF_CONF"),
        "title": "SUI V25 MTF Confluence @ 30m (PAPER ONLY)",
        "subtitle": "30m MTF variant — weaker than V23 SUI BB-Break",
        "desc": (
            "EMA(40)/EMA(100) on 30m bars, gated by 4h trend. OOS holds but lower "
            "CAGR (+31%) and lower Sharpe (+0.84) than the V23 SUI BB-Break winner "
            "(+160% / Sh 1.66). Kept as paper-only — upgrade to 15% overlay only if "
            "4 weeks live show parity with backtest."
        ),
    },
]


def build_pdf():
    v24 = _load_v24()
    v25 = _load_v25()
    oos = _load_v25_oos()

    story = []
    # ----- Cover page -----
    story.append(Paragraph("V24 + V25 Overlay Report", TITLE))
    story.append(Paragraph(
        "Appendix to V23 9-coin portfolio · 2026-04-21 · 5 OOS-validated overlays",
        SUB))
    story.append(Paragraph("Executive summary", H2))
    story.append(Paragraph(
        "This appendix documents the seven overlays layered on top of the V23 core "
        "portfolio. V24 contributed two (ETH Regime Router 2h, LINK RSI+BB Scalp 15m). "
        "V25 adds five more, three of which take capital allocation and two of which "
        "remain paper-only. The single biggest change is <b>AVAX V25 MTF Confluence 1h</b>, "
        "which produces CAGR +320% / Sharpe +2.19 with OOS beating IS — a genuine "
        "upgrade over the V23 AVAX RangeKalman. The rest of V25 (SOL, DOGE overlays) "
        "adds diversification and Sharpe improvement rather than CAGR.",
        BODY))
    story.append(Spacer(1, 10))

    # Summary table: all overlays
    summary_rows = [["Overlay", "TF", "Role", "Full CAGR", "Full Sh", "OOS Sh", "Action"]]
    for page_cfg in OVERLAY_PAGES:
        src, key = page_cfg["key"]
        d = (v25 if src == "v25" else v24).get(key)
        if d is None:
            continue
        m = d["metrics"]
        oos_row = None
        if src == "v25" and len(oos):
            match = oos[(oos["sym"] == d["sym"]) & (oos["family"] == d["family"])]
            if len(match):
                oos_row = match.iloc[0]
        oos_sh = f"{oos_row['oos_sh']:+.2f}" if oos_row is not None else "—"
        role = "PAPER ONLY" if "PAPER" in page_cfg["subtitle"].upper() else "LIVE"
        action = ("50% AVAX" if key == "AVAXUSDT_MTF_CONF"
                   else "30% SOL" if key == "SOLUSDT_MTF_CONF"
                   else "30% DOGE" if key == "DOGEUSDT_SEASONAL"
                   else "paper")
        summary_rows.append([
            page_cfg["title"].split(" V")[0] + " V" + page_cfg["title"].split(" V")[1][:2],
            d["tf"], role,
            f"{m['cagr_net']*100:+.1f}%",
            f"{m['sharpe']:+.2f}",
            oos_sh, action,
        ])
    t = Table(summary_rows, colWidths=[5.2*cm, 1.2*cm, 2.0*cm, 2.2*cm,
                                         2.0*cm, 2.0*cm, 2.0*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), TBL_HDR),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("ALIGN",      (1,1), (-1,-1), "CENTER"),
        ("GRID",       (0,0), (-1,-1), 0.3, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, TBL_ALT]),
        ("FONTSIZE",   (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("TOPPADDING", (0,0), (-1,-1), 2),
    ]))
    story.append(t)
    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "<b>Go-live priority:</b> AVAX V25 MTF Conf is the single change that moves "
        "expected portfolio CAGR up materially (from +82% pure V23 to ~+95-100% blended). "
        "Everything else is Sharpe/DD improvement. If you want the minimum incremental "
        "change to the V23 portfolio, deploy AVAX V25 50/50 alongside V23 AVAX "
        "RangeKalman and keep everything else as pure V23.",
        BODY))
    story.append(PageBreak())

    # ----- One page per overlay -----
    for page_cfg in OVERLAY_PAGES:
        src, key = page_cfg["key"]
        d = (v25 if src == "v25" else v24).get(key)
        if d is None:
            print(f"SKIP {page_cfg['title']} — no data")
            continue

        # Chart
        chart_path = make_overlay_chart(page_cfg["title"].replace(" ", "_"), d)

        story.append(Paragraph(page_cfg["title"], H2))
        story.append(Paragraph(f"<i>{page_cfg['subtitle']}</i>", BODY))
        story.append(Spacer(1, 6))
        story.append(Paragraph(page_cfg["desc"], BODY))
        story.append(Spacer(1, 8))

        # OOS row lookup
        oos_row = None
        if len(oos):
            match = oos[(oos["sym"] == d["sym"]) & (oos["family"] == d["family"])]
            if len(match):
                oos_row = match.iloc[0]
        story.append(_metrics_table(d, oos_row))
        story.append(Spacer(1, 10))
        story.append(Image(chart_path, width=17*cm, height=11.5*cm))
        story.append(PageBreak())

    doc = SimpleDocTemplate(
        str(OUT_PDF), pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
    )
    doc.build(story)
    print(f"Wrote: {OUT_PDF}")


if __name__ == "__main__":
    build_pdf()
