"""Build the FINAL DEPLOY-READY PDF after the post-audit (Bug #1-#4) corrections.

Headline numbers (post audit):
  - $25  : $66,604/28d  ($866k/year)
  - $250 : $122,629/28d ($1.60M/year) - BTC-only sleeves after L25 fill simulation
  - $2500: NEGATIVE     (book depth insufficient)

Usage:
  PYTHONIOENCODING=utf-8 C:/Python314/python.exe strategy_lab/reports/build_post_audit_pdf.py
"""
from __future__ import annotations
import os
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
)

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RESULTS = ROOT / "data" / "v4" / "canonical" / "_results"
OUT_PDF = ROOT / "strategy_lab" / "reports" / "FINAL_DEPLOY_READY_POST_AUDIT_2026_05_26.pdf"
CHART_DIR = ROOT / "strategy_lab" / "reports" / "_pdf_charts_post_audit_2026_05_26"
CHART_DIR.mkdir(parents=True, exist_ok=True)

sns.set_theme(style="whitegrid", context="notebook")


def chart_pre_vs_post(path="01_pre_vs_post_audit.png"):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    cats = ["PP-R6 audited\n($20.5k/28d)", "POST-AUDIT TRUE\n($66.6k/28d)"]
    vals = [20501, 66604]
    colors_ = ["#d62728", "#2ca02c"]
    axes[0].bar(cats, vals, color=colors_, edgecolor="black", linewidth=1.5)
    for i, v in enumerate(vals):
        axes[0].text(i, v + 2000, f"${v:,}", ha="center", fontsize=14, weight="bold")
    axes[0].set_ylabel("sum_pnl / 28d at $25 notional")
    axes[0].set_title("Post-audit correction (PP under-scaled 8.07x)", fontsize=13, pad=12)
    axes[0].set_ylim(0, 80000)
    # Per-notional realistic
    cats2 = ["@ $25\n(7 deploy)", "@ $250\n(BTC-only, 5 deploy)", "@ $2500\n(none viable)"]
    vals2 = [66604, 122629, 0]
    cs = ["#1a73e8", "#34a853", "#999"]
    axes[1].bar(cats2, vals2, color=cs, edgecolor="black", linewidth=1.5)
    for i, v in enumerate(vals2):
        if v > 0:
            axes[1].text(i, v + 5000, f"${v:,}", ha="center", fontsize=13, weight="bold")
        else:
            axes[1].text(i, 5000, "DEPTH\nEXHAUSTION", ha="center", fontsize=11, weight="bold",
                          color="darkred")
    axes[1].set_ylabel("$/28d (post-dedup, post L25 fill simulation)")
    axes[1].set_title("Realistic deployable by notional", fontsize=13, pad=12)
    axes[1].set_ylim(0, 150000)
    plt.suptitle("POST-AUDIT — Bug #1-#4 fixed; L25 fill simulation",
                  fontsize=14, y=1.03, weight="bold")
    plt.tight_layout()
    fig.savefig(CHART_DIR / path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return CHART_DIR / path


def chart_inflation_per_sleeve(path="02_inflation_per_sleeve.png"):
    df = pd.read_csv(RESULTS / "master_sleeve_catalog_v2_clean.csv")
    df = df[(df.n_clean > 50) & (df.sum_28d_clean > 100)].copy()
    df = df.sort_values("sum_28d_clean", ascending=True).tail(15)
    fig, ax = plt.subplots(figsize=(13, 8))
    y = np.arange(len(df))
    ax.barh(y - 0.2, df.sum_28d_orig_correct_scaling.values, height=0.4,
             color="#d62728", alpha=0.85, label="Original (20 offsets, leaky panels)")
    ax.barh(y + 0.2, df.sum_28d_clean.values, height=0.4,
             color="#2ca02c", alpha=0.85, label="CLEAN (9 offsets, bug-fixed)")
    ax.set_yticks(y)
    ax.set_yticklabels([s[:50] for s in df.sleeve_id], fontsize=9)
    for i, (orig, clean) in enumerate(zip(df.sum_28d_orig_correct_scaling.values,
                                             df.sum_28d_clean.values)):
        ratio = orig / max(clean, 1e-9)
        ax.text(max(orig, clean) + 2000, i, f"{ratio:.1f}x infl",
                  va="center", fontsize=9, color="darkred")
    ax.axvline(0, color="black", linewidth=0.5)
    ax.set_xlabel("sum_pnl / 28d @ $25 notional")
    ax.set_title("Fire-count inflation per sleeve — Bug #1 impact",
                  fontsize=13, weight="bold")
    ax.legend(loc="lower right", fontsize=10)
    plt.tight_layout()
    fig.savefig(CHART_DIR / path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return CHART_DIR / path


def chart_notional_scaling(path="03_notional_scaling.png"):
    df = pd.read_csv(RESULTS / "sleeve_notional_scaling_truth.csv")
    df = df[df.n > 50].copy()
    df = df.sort_values("sum_28d_25", ascending=True).tail(15)
    fig, ax = plt.subplots(figsize=(13, 8))
    y = np.arange(len(df))
    ax.barh(y - 0.27, df.sum_28d_25.values, height=0.27,
             color="#34a853", label="$25")
    ax.barh(y, df.sum_28d_250.values, height=0.27,
             color="#1a73e8", label="$250")
    ax.barh(y + 0.27, df.sum_28d_2500.values, height=0.27,
             color="#d62728", label="$2,500")
    ax.set_yticks(y)
    ax.set_yticklabels([s[:50] for s in df.sleeve_id], fontsize=9)
    ax.axvline(0, color="black", linewidth=0.5)
    ax.set_xlabel("sum_pnl / 28d after L25 fill simulation")
    ax.set_title("Notional scaling — L25 sub-second fill simulation",
                  fontsize=13, weight="bold")
    ax.legend(loc="lower right", fontsize=10)
    plt.tight_layout()
    fig.savefig(CHART_DIR / path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return CHART_DIR / path


def chart_slippage_vs_notional(path="04_slippage_vs_notional.png"):
    df = pd.read_csv(RESULTS / "sleeve_notional_scaling_truth.csv")
    df = df[df.n > 100].copy()
    fig, ax = plt.subplots(figsize=(13, 7))
    for asset, color in [("BTC", "#1a73e8"), ("ETH", "#d62728"), ("SOL", "#fbbc04")]:
        sub = df[df.asset == asset]
        if len(sub) == 0:
            continue
        ax.scatter([25] * len(sub), [0] * len(sub),
                    color=color, alpha=0.6, s=80, label=f"{asset} @ $25")
        ax.scatter([250] * len(sub), sub.avg_slip_250.values,
                    color=color, alpha=0.6, s=80, marker="s")
        ax.scatter([2500] * len(sub), sub.avg_slip_2500.values,
                    color=color, alpha=0.6, s=80, marker="^")
    ax.set_xscale("log")
    ax.set_xlabel("Notional ($)")
    ax.set_ylabel("Average slippage (bps vs $25 reference)")
    ax.set_title("Slippage explodes at $2,500 — book depth insufficient",
                  fontsize=13, weight="bold")
    ax.axhline(100, color="green", linestyle="--", alpha=0.5, label="100 bps")
    ax.axhline(500, color="orange", linestyle="--", alpha=0.5, label="500 bps")
    ax.legend(loc="upper left", fontsize=10)
    plt.tight_layout()
    fig.savefig(CHART_DIR / path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return CHART_DIR / path


def chart_deploy_roster(path="05_deploy_roster.png"):
    df = pd.read_csv(RESULTS / "final_deploy_manifest_v2_post_audit.csv")
    deploy = df[df.status == "DEPLOY"].sort_values("sum_28d", ascending=True)
    fig, ax = plt.subplots(figsize=(13, 7))
    y = np.arange(len(deploy))
    ax.barh(y, deploy.sum_28d.values, color="#34a853", edgecolor="black", linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels([s[:50] for s in deploy.sleeve_id], fontsize=10)
    for i, (sl, val) in enumerate(zip(deploy.sleeve_id, deploy.sum_28d)):
        ax.text(val + 500, i, f"${val:,.0f}", va="center", fontsize=10, weight="bold")
    ax.set_xlabel("sum_pnl / 28d @ $25 notional")
    ax.set_title("POST-AUDIT DEPLOY ROSTER (7 sleeves, dedup-validated)",
                  fontsize=13, weight="bold")
    plt.tight_layout()
    fig.savefig(CHART_DIR / path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return CHART_DIR / path


# ---- PDF generation ----

styles = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=20, textColor=colors.HexColor("#1a73e8"),
                     spaceAfter=10, leading=24)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=15, textColor=colors.HexColor("#0d652d"),
                     spaceAfter=8, spaceBefore=14, leading=20)
H3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=12, textColor=colors.HexColor("#5f6368"),
                     spaceAfter=6, spaceBefore=10)
BODY = ParagraphStyle("BODY", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=6)
LEAD = ParagraphStyle("LEAD", parent=styles["BodyText"], fontSize=11, leading=15,
                       textColor=colors.HexColor("#444"), spaceAfter=8)


def main():
    print("Generating charts…")
    p1 = chart_pre_vs_post()
    p2 = chart_inflation_per_sleeve()
    p3 = chart_notional_scaling()
    p4 = chart_slippage_vs_notional()
    p5 = chart_deploy_roster()
    charts = [p1, p2, p3, p4, p5]

    print(f"Building PDF -> {OUT_PDF}")
    doc = SimpleDocTemplate(str(OUT_PDF), pagesize=A4,
                              leftMargin=15*mm, rightMargin=15*mm,
                              topMargin=18*mm, bottomMargin=15*mm)
    story = []

    # Title
    story.append(Paragraph("FINAL DEPLOY-READY POST-AUDIT", H1))
    story.append(Paragraph("Polymarket Up-Down Sleeves — corrected catalog after Round 7 audit",
                            LEAD))
    story.append(Paragraph("Date: 2026-05-26 | Lockbox window: May 21-25 (3.96d) | Fee: 2%-on-profit-only",
                            BODY))
    story.append(Spacer(1, 5*mm))

    # TL;DR
    story.append(Paragraph("Bottom-line deployable estimates", H2))
    tldr = [
        ["Notional", "Per-day", "28-day", "Annual", "Sleeves", "Confidence"],
        ["$25", "$2,378", "$66,604", "$866k", "7 DEPLOY", "HIGH"],
        ["$250", "$4,380", "$122,629", "$1.60M", "5 BTC-only", "MEDIUM"],
        ["$2,500", "NEGATIVE", "NEGATIVE", "NEGATIVE", "0", "DO-NOT"],
    ]
    t = Table(tldr, hAlign="LEFT", colWidths=[24*mm, 22*mm, 28*mm, 24*mm, 30*mm, 26*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a73e8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#e8f5e9")),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#fff8e1")),
        ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#fce4ec")),
    ]))
    story.append(t)
    story.append(Spacer(1, 5*mm))

    # Bug fixes summary
    story.append(Paragraph("Bug fixes applied", H2))
    story.append(Paragraph(
        "<b>Bug #1 (HIGH):</b> OOS panels used 20 fire offsets per slot (every 15s) while base "
        "panels use 9 (every 30s). Fire-count inflation ~2.10x; PnL inflation 2.50x. Fixed by "
        "filtering oos_fires_* to canonical 9-offset 5m grid {30,60,...,270} and 8-offset 15m "
        "grid {60,120,240,360,480,600,720,840}.", BODY))
    story.append(Paragraph(
        "<b>Bug #2 (MEDIUM):</b> regime_panel ts_us = bar START with closed-bar features caused "
        "merge_asof(backward) to pick the slot containing fire_us (0-300s of lookahead). Rekey'd "
        "ts_us to bar END (slot_start + tf_seconds - 1us). Verification: 7.4% of fires got "
        "different regime_label vs causal prior bar in v1; 0.000% in v2.", BODY))
    story.append(Paragraph(
        "<b>Bug #3 (MEDIUM):</b> Same pattern as #2 for sms_panel. Same fix.", BODY))
    story.append(Paragraph(
        "<b>Bug #4 (HIGH, DEFLATING):</b> PP-R6 manifest scaled by (28/32) = 0.875x while actual "
        "oos panel covers 3.96d not 32d. True scaling = (28/3.96) = 7.07x. Net correction = 8.07x "
        "UPWARD. PP's $20,501/28d → actually $66,604/28d.", BODY))
    story.append(Spacer(1, 4*mm))

    # Charts
    story.append(PageBreak())
    story.append(Paragraph("Pre vs post-audit — the magnitude of the corrections", H2))
    story.append(Image(str(charts[0]), width=170*mm, height=72*mm))
    story.append(Paragraph(
        "Left: PP's $20.5k/28d audited number was UNDER-stated. Real /28d at $25 = $66.6k. "
        "Right: at $250 we only get $122k/28d (3.24x linear scale, not 10x) due to L25 book depth. "
        "At $2,500, every sleeve goes deeply negative (depth exhaustion).", BODY))

    story.append(PageBreak())
    story.append(Paragraph("Fire-count inflation per sleeve (Bug #1 impact)", H2))
    story.append(Image(str(charts[1]), width=180*mm, height=110*mm))
    story.append(Paragraph(
        "Each sleeve's CLEAN (9-offset) /28d is 1.7-3.5x lower than the panel-leaked version. "
        "Sleeves marginal in the original panel (R4 POOL 15m, eth_s15) flipped NEGATIVE after the fix.",
        BODY))

    story.append(PageBreak())
    story.append(Paragraph("L25 fill simulation — notional scaling per sleeve", H2))
    story.append(Image(str(charts[2]), width=180*mm, height=110*mm))
    story.append(Paragraph(
        "Walking the L25 book at $250 yields 3-7x scale (not 10x) for BTC; ETH/SOL flip negative. "
        "At $2,500 every sleeve loses money — book depth is exhausted within 5-15 levels.", BODY))

    story.append(PageBreak())
    story.append(Paragraph("Slippage vs notional", H2))
    story.append(Image(str(charts[3]), width=180*mm, height=100*mm))
    story.append(Paragraph(
        "Slippage at $250: BTC 185-275 bps avg, ETH 460-575 bps avg, SOL 550-770 bps. "
        "Above 500 bps slippage destroys per-trade edge.", BODY))

    story.append(PageBreak())
    story.append(Paragraph("Post-audit DEPLOY roster (7 sleeves)", H2))
    story.append(Image(str(charts[4]), width=180*mm, height=110*mm))
    story.append(Paragraph(
        "Greedy slug-overlap dedup on CLEAN fires selects 7 DEPLOY sleeves. R1_btc_s6_lite and "
        "S7_btc_5m_base lead at ~$24.5k/28d each. R1_eth_5m_s6_tight_pos_cloud is the best ETH at "
        "$15k/28d but cannot scale beyond $25 due to ETH book depth.", BODY))

    # Per-market summary table
    story.append(PageBreak())
    story.append(Paragraph("Per-market BEST sleeve (the user's primary ask)", H2))
    per_market = [
        ["Market", "Offset", "Best sleeve", "n", "WR", "$/tr", "$/28d @25", "$/28d @250", "Deploy@250?"],
        ["BTC 5m", "60-150", "R1_btc_5m_s6_lite", "3,373", "68.4%", "$1.04", "$24,771", "$68,907", "YES"],
        ["BTC 5m", "150-240", "R2_btc_5m_s1_5_3bps", "3,542", "68.0%", "$0.90", "$22,569", "$17,335", "marginal"],
        ["BTC 5m", "240-300", "S7_btc_5m_base", "1,940", "76.9%", "$1.78", "$24,476", "$115,117", "YES"],
        ["ETH 5m", "60-150", "R1_eth_5m_s6_tight_pos_cloud", "2,755", "70.1%", "$0.77", "$15,044", "-$58,537", "NO"],
        ["ETH 5m", "150-240", "(no positive)", "—", "—", "—", "—", "—", "—"],
        ["SOL 5m", "60-150", "poly_updown_sol_5m_s6_hybrid_v1", "2,261", "70.1%", "$0.30", "$4,846", "-$202,189", "NO"],
        ["BTC 15m", "480+", "R4_POOL_15m_600_720_ribbon_slope_vwap", "443", "58.7%", "-$0.41", "-$1,272", "NEG", "NO"],
    ]
    t = Table(per_market, hAlign="LEFT", repeatRows=1,
              colWidths=[16*mm, 16*mm, 60*mm, 14*mm, 14*mm, 14*mm, 22*mm, 22*mm, 18*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a73e8")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 1), (-1, 3), colors.HexColor("#e8f5e9")),
        ("BACKGROUND", (0, 4), (-1, 4), colors.HexColor("#fff8e1")),
        ("BACKGROUND", (0, 5), (-1, 5), colors.HexColor("#f5f5f5")),
        ("BACKGROUND", (0, 6), (-1, 6), colors.HexColor("#fff8e1")),
        ("BACKGROUND", (0, 7), (-1, 7), colors.HexColor("#fce4ec")),
    ]))
    story.append(t)
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        "<b>Operational rule:</b> BTC sleeves scale to $250. ETH/SOL stay at $25 until book "
        "depth improves. 15m has no viable sleeve after audit.", BODY))

    # Confidence + caveats
    story.append(PageBreak())
    story.append(Paragraph("Confidence + caveats", H2))
    story.append(Paragraph(
        "<b>Grade A (deploy with confidence at $25):</b> R1_btc_s6_lite, S7_btc_5m_base, "
        "poly_updown_btc_5m_s15_hybrid_v1, R5_hawkes_btc_5m_off120 — all positive at $25 AND $250.",
        BODY))
    story.append(Paragraph(
        "<b>Grade B (deploy $25 only):</b> R1_eth_5m_s6_tight_pos_cloud, "
        "poly_updown_sol_5m_s6_hybrid_v1, R5_eth_s6_v1_plus_mp_change_with.", BODY))
    story.append(Paragraph(
        "<b>Grade C / DO NOT DEPLOY:</b> R4_POOL_15m_600_720_ribbon_slope_vwap (NEG after Bug #1 fix), "
        "poly_updown_eth_5m_s15_hybrid_v1, R5_hawkes_eth_5m_off120, R5_btc_s6_v1_plus_lm_high_stat (n=8).",
        BODY))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        "<b>Open caveats:</b><br/>"
        "(1) Lockbox is only 3.96d. A 2nd lockbox is recommended before live capital allocation.<br/>"
        "(2) L25 book depth is point-in-time. Slippage estimates use the snapshot AT fire_us. "
        "Production should monitor live book depth and skip fires where 25-level depth < 6×notional.<br/>"
        "(3) ETH/SOL book depth has been improving over the past 30d. Re-test at $250 after 2 more weeks.<br/>"
        "(4) Phase 1 deploy at $25 for 7-14d to confirm post-audit estimates before promoting any sleeve to $250.",
        BODY))

    doc.build(story)
    print(f"PDF generated: {OUT_PDF}")


if __name__ == "__main__":
    main()
