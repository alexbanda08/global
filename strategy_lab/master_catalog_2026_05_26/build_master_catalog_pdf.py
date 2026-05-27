"""Build the MASTER_SLEEVE_CATALOG_AUDITED PDF — Round 6+R7 deploy view.

Patches the headline numbers from the prior build_round6_final_pdf.py with
the audited values and adds a 'Post-Audit Updates' section.

Output: strategy_lab/reports/MASTER_SLEEVE_CATALOG_AUDITED_2026_05_26.pdf
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    Image,
)

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
OUT_PDF = ROOT / "strategy_lab" / "reports" / "MASTER_SLEEVE_CATALOG_AUDITED_2026_05_26.pdf"
CHART_DIR = ROOT / "strategy_lab" / "reports" / "_pdf_charts_master_catalog"
CHART_DIR.mkdir(parents=True, exist_ok=True)


def chart_grade_distribution(path="01_grade_distribution.png"):
    df = pd.read_csv(RES / "master_sleeve_catalog_audited.csv")
    grade_order = ["A", "B", "C", "F"]
    counts = df["confidence_grade"].value_counts().reindex(grade_order, fill_value=0)
    colors_ = ["#2ca02c", "#1f77b4", "#ff7f0e", "#d62728"]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    bars = ax.bar(counts.index, counts.values, color=colors_, edgecolor="black", linewidth=1.2)
    for b, v in zip(bars, counts.values):
        ax.text(b.get_x() + b.get_width() / 2, v + 2, f"{v}", ha="center", fontsize=14, weight="bold")
    ax.set_title("Master catalog — confidence grade distribution (448 sleeves)", fontsize=13, pad=12)
    ax.set_ylabel("# sleeves")
    out = CHART_DIR / path
    plt.tight_layout()
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    return out


def chart_deploy_status(path="02_deploy_status.png"):
    df = pd.read_csv(RES / "master_sleeve_catalog_audited.csv")
    order = ["DEPLOY", "PAPER_FIRST", "CANDIDATE", "SKIP_OVERLAP", "SKIP_NEGATIVE_PNL"]
    counts = df["deploy_status"].value_counts().reindex(order, fill_value=0)
    colors_ = ["#2ca02c", "#1f77b4", "#9467bd", "#7f7f7f", "#d62728"]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    bars = ax.barh(counts.index, counts.values, color=colors_, edgecolor="black", linewidth=1.2)
    for b, v in zip(bars, counts.values):
        ax.text(v + 4, b.get_y() + b.get_height() / 2, f"{v}", va="center", fontsize=12)
    ax.set_title("Master catalog — deploy status (post-audit)", fontsize=13, pad=12)
    ax.set_xlabel("# sleeves")
    ax.invert_yaxis()
    out = CHART_DIR / path
    plt.tight_layout()
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    return out


def chart_deployable_by_scenario(path="03_deployable_scenarios.png"):
    fig, ax = plt.subplots(figsize=(12, 6))
    scenarios = [
        "R5 NAIVE\n(WRONG)",
        "R6 PP dedup\n(BASELINE)",
        "+ R7 threshold\nrecal",
        "+ R7 BTC S15\nAsia session",
        "+ WS-poly2\n(if 2nd LB pass)",
        "WS-poly2\n4d extrap MAX",
    ]
    vals = [90000, 20501, 24000, 25500, 70000, 314000]
    colors_ = ["#d62728", "#2ca02c", "#2ca02c", "#2ca02c", "#1f77b4", "#9467bd"]
    bars = ax.bar(scenarios, vals, color=colors_, edgecolor="black", linewidth=1.2)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 5000, f"${v:,}", ha="center", fontsize=11, weight="bold")
    ax.axhline(20501, color="#2ca02c", ls="--", alpha=0.4, label="R6 audited baseline $20,501")
    ax.set_title("Combined deployable / 28d @ $25 notional — scenarios", fontsize=13, pad=12)
    ax.set_ylabel("Sum_PnL / 28d at $25")
    ax.legend(loc="upper left")
    ax.set_ylim(0, 360000)
    out = CHART_DIR / path
    plt.tight_layout()
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    return out


def chart_per_market_best(path="04_per_market_best.png"):
    df = pd.read_csv(RES / "master_sleeve_catalog_audited.csv")
    df = df[(df["confidence_grade"].isin(["A", "B"])) & (df["oos_status"] == "PASS")].copy()
    df["market"] = df["asset"].astype(str) + " " + df["tf"].astype(str)
    best = (
        df.sort_values("sum_pnl_28d", ascending=False)
        .groupby("market", as_index=False)
        .first()[["market", "sum_pnl_28d"]]
    )
    # Filter sensible markets
    best = best[best["market"].isin(
        ["BTC 5m", "ETH 5m", "SOL 5m", "BTC 15m", "ETH 15m", "SOL 15m", "POOL 15m"]
    )]
    best = best.sort_values("sum_pnl_28d", ascending=True)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    bars = ax.barh(best["market"], best["sum_pnl_28d"], color="#1f77b4", edgecolor="black")
    for b, v in zip(bars, best["sum_pnl_28d"]):
        ax.text(v + 200, b.get_y() + b.get_height() / 2, f"${v:,.0f}", va="center", fontsize=11)
    ax.set_title("Best CANDIDATE sleeve per market (grade A/B, OOS PASS, naive single-sleeve sum)", fontsize=12, pad=12)
    ax.set_xlabel("sum_pnl / 28d ($25 notional)")
    out = CHART_DIR / path
    plt.tight_layout()
    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()
    return out


def build():
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("title", parent=styles["Title"], fontSize=22, alignment=TA_CENTER, spaceAfter=8)
    subtitle_style = ParagraphStyle(
        "subtitle",
        parent=styles["Heading2"],
        fontSize=14,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#444444"),
        spaceAfter=18,
    )
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=15, spaceAfter=8, spaceBefore=12)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=12, spaceAfter=6, spaceBefore=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10, leading=14, alignment=TA_LEFT)
    caption = ParagraphStyle(
        "caption",
        parent=styles["BodyText"],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#666666"),
        alignment=TA_CENTER,
    )
    code = ParagraphStyle("code", parent=body, fontName="Courier", fontSize=8.5, leading=11)

    doc = SimpleDocTemplate(str(OUT_PDF), pagesize=A4, topMargin=15 * mm, bottomMargin=15 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm)

    story = []
    story.append(Paragraph("Master Sleeve Catalog — AUDITED", title_style))
    story.append(Paragraph("R1-R7 deploy roster after Round 6 dedup + Round 7 cross-cuts", subtitle_style))
    story.append(Paragraph("<b>Date:</b> 2026-05-26 &nbsp;&nbsp; <b>Window:</b> Apr 24 → May 25 2026 UTC (32d canonical)", body))
    story.append(Paragraph("<b>Fee model:</b> LegacyConfig (2%-on-profit-only) &nbsp;&nbsp; <b>Anchor:</b> ws_s = slot_start − window_s", body))
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>Authoritative deployable:</b> <font color='#2ca02c'><b>$20,501 / 28d @ $25 = $7,322/day @ $250 = $2.67M/year</b></font> (post-Round 6 slug-overlap dedup, OOS-filtered).", body))
    story.append(Paragraph("<b>R7 WS-poly2 upside (PAPER_FIRST):</b> potentially 2.3× lift to <b>~$127k/28d @ $25 = $1.27M/28d @ $250 = $16.5M/year</b>, pending 2nd-lockbox confirmation.", body))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Bottom-line deployable estimate by notional", h2))
    deploy_data = [
        ["Notional", "Daily", "Weekly", "28-day", "Annual", "Confidence"],
        ["$25", "$732", "$5,125", "$20,501", "$267,310", "HIGH (R6 dedup)"],
        ["$250", "$7,322", "$51,253", "$205,010", "$2,673,098", "HIGH (linear scale)"],
        ["$2,500 (op-max)", "$73,217", "$512,525", "$2,050,100", "$26.7M", "MEDIUM (book depth)"],
        ["+ WS-poly2 (B-grade)", "$4,558", "$31,907", "$127,628", "$1.66M", "PENDING 2nd lockbox"],
    ]
    t = Table(deploy_data, hAlign="LEFT", colWidths=[35*mm, 22*mm, 22*mm, 28*mm, 30*mm, 38*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f77b4")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 1), (-1, 3), colors.HexColor("#e8f5e9")),
        ("BACKGROUND", (0, 4), (-1, 4), colors.HexColor("#fff3e0")),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    # Chart 1: grade distribution
    p1 = chart_grade_distribution()
    img = Image(str(p1), width=170*mm, height=85*mm)
    story.append(img)
    story.append(Paragraph("Confidence grade distribution. A = strict 3-way pass + dedup-validated. B = walk-forward pass + positive lockbox. C = single-window or small-n. F = OOS FAIL.", caption))
    story.append(PageBreak())

    story.append(Paragraph("Post-audit changes (from R5 → R6 → R7)", h2))
    bullets = [
        "<b>R6 dedup audit (Agent PP):</b> downgraded deployable estimate from $85-95k/28d (naive sum) to $20.5k/28d (dedup truth). Jaccard slug-overlap between BTC 5m sleeves was 0.4-1.0 — naive sums counted each slug N times.",
        "<b>OOS filtering:</b> 7 R4/R5 sleeves removed from DEPLOY list because they FAILED 4-day lockbox: poly_updown_eth_5m_s15_v1, R5_hawkes_eth, R5_eth_s6+mp_no_extreme, R4 ETH/POOL 15m trend_slope (3 cells), R5_btc_s6+lm_high_stat (n=8).",
        "<b>R7 weighted scoring (Agent TT):</b> Logistic Poly2 with polynomial interactions beats binary AND by 17× on raw lockbox sum, 2.3× after slug-overlap dedup (per Agent WW). Pairwise Jaccard between WS sleeves is &lt; 0.30 vs 0.4-1.0 for binary AND. Key interaction: ribbon_alignment × +DI captures late-trend exhaustion that AND-logic cannot express.",
        "<b>R7 threshold sweeps (Agent RR):</b> default thresholds were systematically too tight. Global recalibration (g_mp_no_extreme 50→100bps, g_hawkes_imb 0.3→0.15, g_hurst_trending 0.55→0.50) adds +$3-5k/28d at zero engineering cost.",
        "<b>R7 anomalies (Agent VV):</b> 2 sleeves in current DEPLOY list have NEGATIVE marginal_28d (R5_eth_s6+mp_change_with: -$102; R5_hawkes_sol_5m_off120: -$207). Should DEMOTE to PAPER_FIRST.",
    ]
    for b in bullets:
        story.append(Paragraph("• " + b, body))
        story.append(Spacer(1, 4))
    story.append(Spacer(1, 8))

    # Chart 2: deploy status
    p2 = chart_deploy_status()
    img = Image(str(p2), width=170*mm, height=85*mm)
    story.append(img)
    story.append(Paragraph("Deploy status breakdown. CANDIDATE = passes OOS but not yet integrated into deploy manifest (R3 walk-forward, R4 trend_slope 15m sweeps, R5 hawkes variants, etc.).", caption))
    story.append(PageBreak())

    # Phase 1 deploy roster
    story.append(Paragraph("Phase 1 DEPLOY roster (12 sleeves, full $25 notional)", h2))
    df_man = pd.read_csv(RES / "final_deploy_manifest.csv")
    deploy_rows = df_man[df_man["status"] == "DEPLOY"].sort_values("expected_sum_28d", ascending=False)
    table_data = [["#", "Sleeve", "Asset/TF", "n", "WR%", "$/tr", "$28d", "Marginal", "Overlap%"]]
    for i, (_, r) in enumerate(deploy_rows.iterrows(), 1):
        table_data.append([
            str(i),
            str(r["sleeve_id"])[:34],
            f"{r['asset']} {r['tf']}",
            f"{int(r['n']):,}",
            f"{r['wr_pct']:.1f}",
            f"${r['per_tr']:.2f}",
            f"${r['expected_sum_28d']:,.0f}",
            f"${r['marginal_28d']:,.0f}",
            f"{r['overlap_with_primary_pct']:.0f}%",
        ])
    t = Table(table_data, hAlign="LEFT", colWidths=[8*mm, 60*mm, 18*mm, 16*mm, 14*mm, 14*mm, 18*mm, 18*mm, 16*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2ca02c")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (1, 1), (1, -1), "Courier"),
    ]))
    story.append(t)
    story.append(Spacer(1, 8))
    story.append(Paragraph("Action: <b>demote rows 10 and 11 (R5_eth_s6+mp_change_with, R5_hawkes_sol_5m_off120) to PAPER_FIRST</b> due to negative marginal_28d.", body))
    story.append(PageBreak())

    # Chart 3: deployable scenarios
    p3 = chart_deployable_by_scenario()
    img = Image(str(p3), width=175*mm, height=85*mm)
    story.append(img)
    story.append(Paragraph("Deployable scenario range. Realistic post-R7 estimate is $20-30k/28d (audited) with WS-poly2 upside contingent on 2nd-lockbox validation.", caption))
    story.append(Spacer(1, 10))

    # Chart 4: per-market best
    p4 = chart_per_market_best()
    img = Image(str(p4), width=170*mm, height=85*mm)
    story.append(img)
    story.append(Paragraph("Best naive single-sleeve sum_28d per (asset, tf). CAUTION: these are individual sleeve values — combining requires dedup. ETH 5m, BTC 5m show strongest CANDIDATE pools. POOL 15m best CANDIDATE is $7.4k but R4 trend_slope still needs 2nd lockbox.", caption))
    story.append(PageBreak())

    # PAPER_FIRST
    story.append(Paragraph("PAPER_FIRST roster — Week 3-4 (0.5× notional until verified)", h2))
    paper_data = [
        ["Sleeve", "Source", "n", "WR%", "$/tr", "$28d (full)", "Notes"],
    ]
    paper_priority = [
        ("R7_WS_S7_BTC_5m_base", "R7 TT WS", "15543", "82.4", "$2.89", "$39,349", "WS-poly2 — needs 2nd lockbox"),
        ("R7_WS_BTC_S15_150_240", "R7 TT WS", "3938", "85.7", "$3.68", "$12,680", "WS-poly2"),
        ("R7_WS_BTC_S6_60_150", "R7 TT WS", "3791", "73.4", "$3.54", "$11,755", "WS-poly2 (S6 calib poor)"),
        ("R7_WS_SOL_S15_60_150", "R7 TT WS", "2502", "87.0", "$3.64", "$7,969", "WS-poly2"),
        ("R7_WS_SOL_S6_60_150", "R7 TT WS", "1945", "81.2", "$4.42", "$7,514", "WS-poly2"),
        ("R7_WS_ETH_S6_60_150", "R7 TT WS", "2601", "75.5", "$3.11", "$7,089", "WS-poly2 (S6 calib poor)"),
        ("R1_btc_5m_s6_lite", "R6 PP", "5903", "69.0", "$1.26", "$6,534", "85% overlap — marg $350"),
        ("R1_btc_5m_s6_top2", "R6 PP", "5026", "69.1", "$1.42", "$6,239", "97% overlap — marg $149"),
        ("R7_WS_ETH_S15_150_240", "R7 TT WS", "4810", "85.7", "$1.37", "$5,756", "WS-poly2 (marg p=0.064)"),
        ("S2_fade_momo_btc_mag2_0", "R1", "299", "59.5", "$3.68", "$1,399", "Contrarian, 0% overlap"),
        ("S2_fade_momo_eth_mag2_0", "R1", "202", "61.4", "$4.12", "$1,059", "Contrarian, 0% overlap"),
        ("R7_UU_BTC_S15_Asia_session", "R7 UU", "654", "—", "$2.95", "—", "+$0.25/tr session overlay"),
        ("R7_SS_S15_60_150_symmetric_3gate", "R7 SS", "3034", "78.4", "$4.92", "$13,069", "Symmetric stack new sleeve"),
        ("R6_XFI_SOL_15m_off240", "R6 OO", "148", "—", "—", "—", "Cross-feature SOL, paper only"),
    ]
    for row in paper_priority:
        paper_data.append(list(row))
    t = Table(paper_data, hAlign="LEFT", colWidths=[55*mm, 18*mm, 14*mm, 12*mm, 14*mm, 20*mm, 50*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f77b4")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("ALIGN", (2, 1), (5, -1), "RIGHT"),
        ("FONTNAME", (0, 1), (0, -1), "Courier"),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Operational priorities", h2))
    ops = [
        "<b>1. Demote 2 manifest rows to PAPER_FIRST</b> (R5_eth_s6+mp_change_with, R5_hawkes_sol_5m_off120) — both have negative marginal_28d.",
        "<b>2. Apply S3 HoD refresh</b> on existing 11 production sleeves → +$15,900/28d. 5-min config edit, zero new code.",
        "<b>3. Apply R7 global threshold recalibration</b> (g_mp_no_extreme 50→100bps, etc.) → +$3-5k/28d.",
        "<b>4. Run 2nd lockbox</b> on WS-poly2 (rotate window 7d forward). 11.6× val→lockbox step-up needs verification.",
        "<b>5. Live shadow deploy</b> Phase 1 (6 sleeves) at $25 notional for 7-14 days.",
        "<b>6. Weekly auto-pull + auto-revalidate</b> using migration_2026_05_25 pattern.",
        "<b>7. S6 calibration:</b> production sleeves are trained on uncalibrated probabilities. Isotonic regression improves calibration error 0.18→0.03 but lowers PnL 3.8%. <b>Keep uncalibrated until live shadow confirms otherwise.</b>",
        "<b>8. book_walk_fill quality at $250 notional:</b> verify L25 mid-quote depth supports projected fill rates before scaling beyond $25.",
    ]
    for o in ops:
        story.append(Paragraph("• " + o, body))
        story.append(Spacer(1, 3))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Files inventory", h2))
    story.append(Paragraph(
        "<b>Authoritative:</b> "
        "<font name='Courier' size='8'>data/v4/canonical/_results/master_sleeve_catalog_audited.csv</font> (this catalog, 448 sleeves) — "
        "<font name='Courier' size='8'>final_deploy_manifest.csv</font> (R6 dedup, 26 rows) — "
        "<font name='Courier' size='8'>ws_poly2_dedup_2026_05_26/final_deploy_manifest_v2.csv</font> (R7 WW combined). "
        "<b>Reports:</b> "
        "<font name='Courier' size='8'>ROUND6_SYNTHESIS</font>, "
        "<font name='Courier' size='8'>ROUND7_SYNTHESIS</font>, "
        "<font name='Courier' size='8'>NAIVE_SUM_CORRECTIONS</font>, "
        "<font name='Courier' size='8'>SLUG_OVERLAP_DEPLOY_MANIFEST</font>, "
        "<font name='Courier' size='8'>WS_POLY2_DEDUP_VALIDATION</font>. "
        "<b>Source MD:</b> <font name='Courier' size='8'>MASTER_SLEEVE_CATALOG_AUDITED_2026_05_26.md</font>",
        body,
    ))

    doc.build(story)
    print(f"Wrote PDF: {OUT_PDF}")


if __name__ == "__main__":
    build()
