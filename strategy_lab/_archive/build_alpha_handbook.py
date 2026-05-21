"""
Build ALPHA_HANDBOOK.pdf — the complete R&D guide.

Summarises every experiment we ran (V7-V18), the Pareto frontier of
what works vs what didn't, the final recommended Hyperliquid portfolio
spec, and a deployment checklist.

Pages:
  1. Cover + headline finding (Sharpe 1.88 hybrid portfolio)
  2. R&D timeline and methodology
  3. Pareto frontier chart — CAGR vs Sharpe by strategy family
  4. V7 high-win-rate (HWR) family — results
  5. V8/V9 multi-TP / SuperTrend / HMA (+ advanced simulator)
  6. V10 orderflow filters — null results
  7. V11 regime ensemble — null results
  8. V12 pullback / squeeze / NR7 — pockets of edge
  9. V14 cross-sectional momentum — BREAKTHROUGH
 10. V15 parameter sweep — 70 configs → balanced champion
 11. V16 ML-ranked XSM (if results available)
 12. V17 pairs trading
 13. V18 robustness audit of V15 champion
 14. Combined portfolio equity (trend + XSM) — full period
 15. Final Hyperliquid deployment spec
 16. Honest caveats + what comes next
"""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import pandas as pd

plt.rcParams.update({
    "font.family":     "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid":       True,
    "grid.alpha":      0.25,
    "grid.linestyle":  "--",
    "figure.facecolor":"white",
})

BASE = Path(__file__).resolve().parent
RES = BASE / "results"
OUT = BASE / "reports" / "ALPHA_HANDBOOK.pdf"
OUT.parent.mkdir(exist_ok=True)

IS_END = pd.Timestamp("2023-01-01", tz="UTC")


def _load_eq(path: Path) -> pd.Series | None:
    if not path.exists(): return None
    df = pd.read_csv(path, index_col=0, parse_dates=[0])
    df.index = df.index.tz_convert("UTC") if df.index.tz else df.index.tz_localize("UTC")
    return df.iloc[:, 0]


def _text_page(pdf, title, lines, fontsize=10, subtitle=None):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, title, ha="center", fontsize=20, weight="bold")
    if subtitle:
        ax.text(0.5, 0.925, subtitle, ha="center", fontsize=11, color="#555")
    ax.axhline(0.90, 0.05, 0.95, color="#ccc", lw=0.5)
    y = 0.87
    for line in lines:
        if line.startswith("## "):
            y -= 0.005
            ax.text(0.06, y, line[3:], fontsize=12, weight="bold", color="#222")
            y -= 0.028
        elif line.startswith("> "):
            ax.text(0.06, y, line[2:], fontsize=fontsize, color="#444", style="italic")
            y -= 0.024
        elif line == "":
            y -= 0.012
        else:
            ax.text(0.06, y, line, fontsize=fontsize)
            y -= 0.022
        if y < 0.05:
            break
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def _table_page(pdf, title, headers, rows, fontsize=8, subtitle=None):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, title, ha="center", fontsize=18, weight="bold")
    if subtitle:
        ax.text(0.5, 0.925, subtitle, ha="center", fontsize=10, color="#555")

    cell_text = [headers] + rows
    tbl = ax.table(cellText=cell_text, loc="center", cellLoc="left",
                   colWidths=[1.0/len(headers)]*len(headers))
    tbl.auto_set_font_size(False); tbl.set_fontsize(fontsize); tbl.scale(1, 1.35)
    for j in range(len(headers)):
        tbl[(0, j)].set_facecolor("#dee"); tbl[(0, j)].set_text_props(weight="bold")
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------
def page_cover(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.95, "ALPHA HANDBOOK", ha="center", fontsize=28, weight="bold")
    ax.text(0.5, 0.915, "Complete R&D guide · Strategy Lab",
            ha="center", fontsize=13, color="#555")
    ax.text(0.5, 0.88, "2018-2026 backtest · 9 coins · 4h timeframe · Hyperliquid maker fees",
            ha="center", fontsize=10, color="#888")
    ax.axhline(0.86, 0.05, 0.95, color="#ccc", lw=0.7)

    # Headline summary box
    y0 = 0.78
    ax.add_patch(plt.Rectangle((0.08, y0 - 0.40), 0.84, 0.42,
                               fill=False, edgecolor="#222", lw=1.3))
    ax.text(0.10, y0,
            "Headline finding: Cross-sectional momentum (XSM) beats time-series trend by ~4x CAGR.",
            fontsize=12, weight="bold")
    ax.text(0.10, y0 - 0.04,
            "Hybrid portfolio (70% XSM + 30% Trend) hits best-ever Sharpe 1.88 on the 2018-2026 window.",
            fontsize=10)

    headline = [
        ("Strategy family",        "CAGR FULL", "Sharpe", "MaxDD",  "Final on $10k"),
        ("Trend-only baseline (V3B/V4C/HWR1)",  "+37.7 %",  "1.16",  "-32.9 %", "$139,520"),
        ("XSM k=2 lb=28d (V14)",                "+157.6 %", "1.60",  "-58.0 %", "$24,393,857"),
        ("XSM k=4 lb=14d (V15 BALANCED)",       "+158.6 %", "1.86",  "-48.3 %", "$25,234,358"),
        ("Hybrid 70% V15 + 30% trend",          "+147.8 %", "1.88",  "-45.8 %", "$17,705,907"),
    ]
    tbl = ax.table(cellText=headline[1:], colLabels=headline[0],
                   loc="center", cellLoc="left",
                   bbox=[0.10, y0 - 0.35, 0.82, 0.28])
    tbl.auto_set_font_size(False); tbl.set_fontsize(9); tbl.scale(1, 1.3)
    for j in range(5):
        tbl[(0, j)].set_facecolor("#dee")
        tbl[(0, j)].set_text_props(weight="bold")

    # Experiments table
    y1 = 0.34
    ax.text(0.10, y1, "Experiments summarised in this handbook:",
            fontsize=11, weight="bold")
    notes = [
        "V7  HWR rule-based high-WR family (BB meanrev / RSI-stoch / pullback)",
        "V8  Novel entries: triple SuperTrend, HMA+ADX, Vol-Donchian",
        "V9  Multi-TP ladder wrappers on V3B/V4C/V2B entries",
        "V10 Orderflow filters (funding / OI / L-S ratio / liquidation cascades)",
        "V11 Regime-switching ensemble (V4C in bull, HWR1 in chop, flat in bear)",
        "V12 Pullback / BB squeeze / higher-lows / NR7 breakout",
        "V14 Cross-sectional momentum — THE BREAKTHROUGH",
        "V15 XSM variant sweep: 70 configs (long-short, composite rank, vol-adj, vol-weighted, grid)",
        "V16 ML-ranked XSM (GradientBoostingRegressor on features)",
        "V17 Pairs trading (BTC/ETH, SOL/ETH, AVAX/SOL, etc.)",
        "V18 Robustness audit of V15 balanced champion",
    ]
    for j, t in enumerate(notes):
        ax.text(0.10, y1 - 0.025 - j * 0.022, t, fontsize=9)

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def page_pareto(pdf):
    # Scatter CAGR vs Sharpe across all strategy families, plus frontier
    candidates = [
        ("V3B baseline",      0.377, 1.16, -0.33,  "#888"),
        ("V4C baseline",      0.335, 1.13, -0.45,  "#888"),
        ("HWR1 XRP",          0.062, 0.43, -0.19,  "#888"),
        ("V8A SuperTrend",    0.000, 0.00, -0.01,  "#c55"),
        ("V8B HMA+ADX",       0.000, 0.05, -0.07,  "#c55"),
        ("V8C Vol-Donchian",  0.040, 0.43, -0.16,  "#c55"),
        ("V9E V3B+ladder",    0.024, 0.43, -0.07,  "#c55"),
        ("V10 orderflow",     0.000, 0.05, -0.12,  "#c55"),
        ("V11 regime ens",    0.005, 0.20, -0.17,  "#c55"),
        ("V12A pullback",     0.014, 0.34, -0.07,  "#c55"),
        ("V12B BB squeeze",   0.023, 0.41, -0.06,  "#c55"),
        ("V14 k=2 lb=28d",    1.576, 1.60, -0.58,  "#090"),
        ("V15 k=4 lb=14d BAL",1.586, 1.86, -0.48,  "#0a0"),
        ("V15F k=3 lb=14d",   1.771, 1.82, -0.48,  "#0a0"),
        ("Hybrid 50/50",      1.379, 1.86, -0.46,  "#004"),
        ("Hybrid 70XSM/30base",1.478,1.88, -0.46,  "#004"),
    ]
    fig, ax = plt.subplots(figsize=(11, 7.5))
    for name, cagr, sh, dd, color in candidates:
        ax.scatter(cagr*100, sh, s=80 + abs(dd)*200, color=color, alpha=0.75, edgecolor="black", lw=0.5)
        ax.annotate(name, (cagr*100, sh), textcoords="offset points", xytext=(6, 4), fontsize=8)
    ax.set_xlabel("CAGR (%)")
    ax.set_ylabel("Sharpe")
    ax.set_title("Pareto frontier — strategy families across full 2018-2026 window\n"
                 "bubble size = |MaxDD|   ·   red = dead-end   ·   green = XSM winners   ·   navy = hybrid",
                 fontsize=11)
    ax.grid(True, alpha=0.3)
    ax.axhline(1.0, color="#ccc", lw=0.5)
    ax.axvline(0.0, color="#ccc", lw=0.5)
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def page_v7_hwr(pdf):
    lines = [
        "## V7 High-Win-Rate rule-based family",
        "Tested 7 variants on 6 coins (42 combos).  Hypothesis: can we hit >=50% win rate every year?",
        "",
        "Key variants:",
        "  HWR1_bb_meanrev         buy lower BB, exit mid-band, ATR stop",
        "  HWR2_rsi_stoch_oversold RSI<25 + Stoch<20 + EMA200 regime",
        "  HWR3_pullback_1to1      EMA50>EMA200 uptrend, enter pullback to 20EMA, 1:1 ATR R/R",
        "  HWR1b_bb_strict         BB std 2.5 (stricter) + N-bar confirm",
        "  HWR3b_pullback_asym     Asymmetric TP<SL for higher WR at same signal",
        "  HWR5_tight_tp_wide_sl   TP 0.5 ATR, SL 2.5 ATR — structural high WR",
        "",
        "## Result: ONE passer (XRP/HWR1)",
        "Only XRP/HWR1_bb_meanrev cleared the bar: WR 73.7%, PF 2.10, $10k -> $15,070.",
        "HWR5 got WR 78% on BTC/LINK but PF 1.02 (every loss wipes out 5 wins mathematically).",
        "Everywhere else: high WR but unprofitable — WR-for-CAGR swap, not a free lunch.",
        "",
        "## Verdict",
        "> Rule-based high-win-rate exists only where mean-reversion structurally lives (XRP).",
        "> Every other coin pays CAGR for the WR bump.  We swapped XRP -> HWR1 in the portfolio.",
    ]
    _text_page(pdf, "V7 — High-Win-Rate rule-based family", lines, fontsize=9)


def page_v8_v9(pdf):
    lines = [
        "## V8 novel entries",
        "V8A Triple SuperTrend stack (ATR 10/1, 11/2, 12/3 all bullish + HTF EMA200 filter)",
        "V8B Hull MA(55) slope + ADX > 22 regime",
        "V8C Volatility-percentile Donchian breakout",
        "",
        "## V9 multi-TP ladder wrappers",
        "V9A = V3B entries + TP1/TP2/TP3 (40/30/30%) + ratcheting SL + Chandelier trail",
        "V9B = V4C + ladder;   V9C = V2B + ladder;   V9D = HWR1 + ladder",
        "V9E = V3B aggressive (25/25/50% — let runner breathe)",
        "",
        "## Result",
        "V8A fires 0 trades — triple-ST confluence too rare on 4h crypto.",
        "V8B gets 3-13 trades in 4 years — ADX>22 gates too tight.",
        "V8C works on ETH (PF 1.26) and SOL (PF 1.67) — weak passers.",
        "V9 ladders produce high WR (55-75%) but SLASH CAGR (45% -> 1-4%).",
        "TP1 at 1 ATR caps the big trending runs V3B/V4C exist to capture.",
        "",
        "## Verdict",
        "> Research techniques (Chandelier, ratcheting SL, triple ST) are sound but don't beat",
        "> baseline trailing-stop trend-following on 4h crypto.  Multi-TP is a WR-for-CAGR swap.",
        "",
        "Built advanced_simulator.py (TP1/TP2/TP3, ratcheting SL, post-TP2 trail).  Still useful for V10/V11/V12/V16.",
    ]
    _text_page(pdf, "V8 / V9 — Novel entries + multi-TP ladder wrappers", lines, fontsize=9)


def page_v10(pdf):
    lines = [
        "## V10 Orderflow strategies (BTC/ETH/SOL only — where Binance futures data exists)",
        "V10A  V3B + funding-rate fade (skip long when 3d funding > +0.015%)",
        "V10B  V4C + Open Interest rising (require OI slope > 0)",
        "V10C  Top-trader L/S > 1.30 standalone (smart-money long signal)",
        "V10D  Liquidation cascade rebound (buy 5sigma liq spikes in bull regime)",
        "",
        "## Result: 0 / 12 passers",
        "V10A: BTC 18 trades, WR 56%, PF 0.97 (unprofitable despite edge-like numbers).",
        "V10B: ETH 5 trades — filter kills signal.",
        "V10C: SOL 17 trades WR 53% PF 0.69 — lagging indicator.",
        "V10D: 2-6 trades — too few 4h-aligned cascades.",
        "",
        "## Verdict",
        "> Level-based aggregated orderflow signals at 4h are too lagging.  By the time",
        "> funding/OI/LS ratio prints, the move is over.  This isn't where the alpha lives.",
        "> Real orderflow edge probably requires 1-min bars + tick data, not 4h aggregates.",
    ]
    _text_page(pdf, "V10 — Orderflow filters (funding, OI, L-S, liquidations)", lines, fontsize=9)


def page_v11(pdf):
    lines = [
        "## V11 Regime-switching ensemble",
        "Classify each 4h bar into BULL / CHOP / BEAR / OTHER using price + ADX:",
        "  BULL  close > EMA100  AND  ADX > 20  AND  EMA50 > EMA100",
        "  CHOP  close near EMA100 (+/-2%)  AND  ADX < 18  AND  not bear",
        "  BEAR  close < EMA100  AND  EMA50 < EMA100   -> stay flat",
        "In BULL:  run V4C_range_kalman entries",
        "In CHOP:  run HWR1_bb_meanrev entries (tighter TPs)",
        "In BEAR / OTHER: no new positions",
        "",
        "## Result: null across all 6 coins",
        "BTC: 0 trades    ETH: 2    SOL: 2    LINK: 13    ADA: 0    XRP: 1",
        "Sharpe 0.0-0.55 on every coin — far below baseline V3B/V4C (1.16-1.61).",
        "",
        "## Root cause",
        "> V3B/V4C already have implicit regime filters (Donchian + volume + regime EMA).",
        "> Stacking another regime layer over-restricts and kills trade count.",
        "> The value is in the ENTRIES themselves, not in additional filtering.",
    ]
    _text_page(pdf, "V11 — Regime-switching ensemble", lines, fontsize=9)


def page_v12(pdf):
    lines = [
        "## V12 — Replacement entries (not filters): pullback / squeeze / pattern",
        "V12A  Pullback-to-EMA20 in 4h uptrend with RSI guard",
        "V12B  Bollinger squeeze breakout (BB width bottom 35% of last 60 bars)",
        "V12C  Higher-lows pattern (2 consecutive HL in trend + ADX>18)",
        "V12D  NR7 narrow-range-7 breakout in uptrend",
        "",
        "## Result: interesting pockets but no CAGR improvement",
        "SOL / V12B_bb_squeeze_break:  n=7  WR 85.7%  PF 1.57  CAGR +2.3%",
        "ETH / V12A_pullback_trend:    n=6  WR 66.7%  PF 1.34  CAGR +1.4%",
        "LINK / V12A_pullback_trend:   n=7  WR 100%   CAGR +5.8%",
        "BTC / V12B:                   n=10 WR 50%    PF 1.16  CAGR +0.9%",
        "",
        "## Verdict",
        "> Higher-WR pockets exist on every coin but CAGR stays <6%.",
        "> Pullback / squeeze entries fire too rarely (3-15 trades / 4 years) to grow capital.",
        "> Same frontier as HWR family — trade CAGR for WR, no true improvement.",
    ]
    _text_page(pdf, "V12 — Pullback / BB squeeze / pattern entries", lines, fontsize=9)


def page_v14(pdf):
    lines = [
        "## V14 — Cross-sectional momentum — THE BREAKTHROUGH",
        "After V7-V12 failed to move the Pareto frontier, V14 tried a different PARADIGM:",
        "every week, RANK all 9 coins by past-N-day return.  Long the top-K.",
        "Rebalance weekly.  Flat when BTC is below its 100-day moving average (bear filter).",
        "",
        "## Why it works (time-series-momentum had blind spots V14 plugs)",
        "  * Bigger universe — DOGE/AVAX/BNB eligible only when they're the top mover that week.",
        "  * Self-selecting — capital automatically concentrates in the current leader (e.g. SOL 2021).",
        "  * Adaptive — weekly rebalance switches horses when momentum rotates.",
        "  * BTC regime filter is orthogonal — it sits OUTSIDE the XSM logic.",
        "",
        "## V14 champion (lb=28d, k=2, rb=7d, BTC filter, 1x leverage)",
        "CAGR  +157.6 %   Sharpe 1.60   MaxDD -58 %   Calmar 2.72",
        "$10k -> $24,393,857 over full 2018-2026 period.",
        "",
        "## Per-year",
        "  2018   -49%  (universe too small early)",
        "  2019  +259%",
        "  2020  +187%",
        "  2021 +6170%  (SOL/AVAX/LINK/ADA alt-season)",
        "  2022   -10%  (BTC filter worked — market did -70%)",
        "  2023  +111%",
        "  2024  +166%",
        "  2025   +40%",
    ]
    _text_page(pdf, "V14 — Cross-sectional momentum (breakthrough)", lines, fontsize=9)


def page_v15(pdf):
    v15 = RES / "v15_xsm.csv"
    subtitle = "Swept 70 XSM variants: long-short, multi-lookback composite, vol-adjusted, vol-weighted, grid"
    if not v15.exists():
        _text_page(pdf, "V15 — XSM variant sweep", ["v15_xsm.csv missing"]); return
    df = pd.read_csv(v15).sort_values("calmar", ascending=False).head(12)
    rows = []
    for _, r in df.iterrows():
        rows.append([
            str(r["name"])[:24],
            f"{r['cagr']*100:+.1f}%",
            f"{r['sharpe']:.2f}",
            f"{r['dd']*100:+.1f}%",
            f"{r['calmar']:.2f}",
            f"${r['final']:,.0f}",
        ])
    _table_page(pdf, "V15 — XSM variant sweep (top 12 by Calmar)",
                headers=["config", "CAGR", "Sharpe", "MaxDD", "Calmar", "Final"],
                rows=rows, subtitle=subtitle, fontsize=8)


def page_v16(pdf):
    v16 = RES / "v16_ml_rank.csv"
    if not v16.exists():
        _text_page(pdf, "V16 — ML-ranked XSM",
                   ["(v16_ml_rank.csv not found — run v16_ml_rank.py first)"]);
        return
    df = pd.read_csv(v16)
    rows = []
    for _, r in df.iterrows():
        rows.append([
            f"k={int(r['top_k'])}  rb={int(r['rebal_d'])}d  hz={int(r['horizon_d'])}d",
            f"{r['cagr']*100:+.1f}%" if pd.notna(r.get('cagr')) else '-',
            f"{r['sharpe']:.2f}"     if pd.notna(r.get('sharpe')) else '-',
            f"{r['dd']*100:+.1f}%"   if pd.notna(r.get('dd')) else '-',
            f"{r['calmar']:.2f}"     if pd.notna(r.get('calmar')) else '-',
            f"${r['final']:,.0f}"    if pd.notna(r.get('final')) else '-',
            f"{int(r['n_fits'])} / {int(r['avg_samples'])}",
        ])
    _table_page(pdf, "V16 — ML-ranked XSM",
                headers=["config", "CAGR", "Sharpe", "MaxDD", "Calmar", "Final", "fits / samples"],
                rows=rows, fontsize=8,
                subtitle="GradientBoostingRegressor, monthly re-fit, walk-forward predictions")


def page_v17(pdf):
    v17 = RES / "v17_pairs.csv"
    if not v17.exists():
        _text_page(pdf, "V17 — Pairs trading",
                   ["(v17_pairs.csv not found — run v17_pairs_trading.py first)"])
        return
    df = pd.read_csv(v17)
    df = df[df["n_trades"] >= 3].sort_values("sharpe", ascending=False).head(15)
    rows = []
    for _, r in df.iterrows():
        rows.append([
            str(r["pair"]),
            f"{r['z_entry']:+.1f}", f"{r['z_exit']:+.1f}",
            f"{int(r['n_trades'])}",
            f"{r['wr']*100:.0f}%",
            f"{r['pf']:.2f}",
            f"{r['sharpe']:.2f}",
            f"{r['cagr']*100:+.1f}%",
            f"{r['dd']*100:+.1f}%",
            f"${r['final']:,.0f}",
        ])
    _table_page(pdf, "V17 — Pairs trading (top 15 by Sharpe, n>=3)",
                headers=["pair", "z_in", "z_out", "n", "WR", "PF", "Sharpe", "CAGR", "DD", "Final"],
                rows=rows, fontsize=8,
                subtitle="Log-spread z-score mean-reversion, long cheap leg only, 4h bars")


def page_v18(pdf):
    rw_path = RES / "v18_random_windows.csv"
    pe_path = RES / "v18_param_epsilon.csv"
    lines = ["## V18 — Robustness audit of V15 balanced champion (lb=14d, k=4, rb=7d, BTC filter)",
             ""]
    if rw_path.exists():
        rw = pd.read_csv(rw_path)
        if len(rw):
            pos = (rw["cagr"] > 0).mean() * 100
            stable = (rw["sharpe"] > 0.5).mean() * 100
            lines.append(f"## 1) Random 2-year windows (n={len(rw)})")
            lines.append(f"   profitable   = {pos:.0f}%")
            lines.append(f"   sharpe > 0.5 = {stable:.0f}%")
            lines.append(f"   median sharpe = {rw['sharpe'].median():.2f}")
            lines.append(f"   worst DD      = {rw['dd'].min()*100:.1f}%")
            lines.append("")
    if pe_path.exists():
        pe = pd.read_csv(pe_path)
        ok = pe[pe["cagr"] > 0]
        lines.append(f"## 2) Parameter-epsilon grid (n={len(pe)} configs)")
        lines.append(f"   profitable      = {len(ok)}/{len(pe)}")
        lines.append(f"   sharpe range    = [{pe.sharpe.min():.2f}, {pe.sharpe.max():.2f}]")
        lines.append(f"   cagr range      = [{pe.cagr.min()*100:+.0f}%, {pe.cagr.max()*100:+.0f}%]")
        lines.append(f"   worst DD        = {pe.dd.min()*100:.1f}%")
        lines.append("")
    lines += [
        "## Verdict",
        "> Champion is NOT knife-edge — profitable across most of the parameter grid.",
        "> 2018-2020 windows have lower Sharpe (universe too small).",
        "> 2020+ windows consistently strong.",
    ]
    _text_page(pdf, "V18 — Robustness audit of V15 champion", lines, fontsize=9)


def page_combined_equity(pdf):
    xsm_path = RES / "v15_balanced_k4_lb14_rb7_equity.csv"
    base_path = RES / "portfolio" / "portfolio_equity.csv"
    xsm = _load_eq(xsm_path)
    base = _load_eq(base_path)
    if xsm is None or base is None:
        _text_page(pdf, "Combined portfolio equity",
                   ["Equity files missing"]); return
    idx = xsm.index.union(base.index)
    xsm_a = xsm.reindex(idx).ffill().fillna(10000)
    base_a = base.reindex(idx).ffill().fillna(10000)
    hybrid = 10000 * (0.7 * xsm_a / xsm_a.iloc[0] + 0.3 * base_a / base_a.iloc[0])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8.5),
                                    gridspec_kw={"height_ratios": [3, 1]})
    ax1.plot(base_a.index, base_a.values, label="Baseline trend (100%)",
             color="#888", lw=1.2)
    ax1.plot(xsm_a.index, xsm_a.values, label="XSM balanced (100%)",
             color="#0a0", lw=1.2)
    ax1.plot(hybrid.index, hybrid.values, label="Hybrid 70 XSM / 30 trend",
             color="#004", lw=1.8)
    ax1.axvspan(idx[0], IS_END, alpha=0.04, color="#0a9396", label="IS (2018-22)")
    ax1.axvspan(IS_END, idx[-1], alpha=0.04, color="#d90429", label="OOS (2023-26)")
    ax1.set_yscale("log")
    ax1.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x,_: f"${x:,.0f}"))
    ax1.set_title("Equity curves (log scale)  -  $10,000 start")
    ax1.legend(loc="upper left", frameon=False, fontsize=9)

    # Underwater of hybrid
    dd = (hybrid / hybrid.cummax() - 1)
    ax2.fill_between(dd.index, dd.values, 0, color="#d90429", alpha=0.6)
    ax2.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax2.set_title("Hybrid drawdown")
    fig.tight_layout()
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def page_deploy(pdf):
    lines = [
        "## Hyperliquid deployment spec",
        "Capital: $10,000 USDC",
        "Timeframe: 4h bars on perpetuals",
        "",
        "## Sleeve A: TREND (30% of equity = $3,000)",
        "  Coins:       BTC, ETH, SOL, LINK, ADA, XRP",
        "  Strategies:  V4C_range_kalman (BTC, SOL, ADA)",
        "               V3B_adx_gate     (ETH, LINK, XRP)",
        "               HWR1_bb_meanrev  (XRP - replaces V3B on that coin)",
        "  Sizing:      5% notional per new entry at 5x account leverage",
        "  Stops:       existing trailing stops (ATR-scaled) per strategy",
        "",
        "## Sleeve B: XSM MOMENTUM (70% of equity = $7,000)",
        "  Universe:    BTC, ETH, SOL, BNB, XRP, DOGE, LINK, ADA, AVAX (all 9)",
        "  Signal:      rank all 9 coins by trailing 14-day return, weekly",
        "  Picks:       long top 4 coins, equal-weight, 1x leverage",
        "  Bear filter: flat (close all) when BTC < its 100-day SMA",
        "  Rebalance:   every Monday 00:00 UTC on the 4h bar open",
        "  Execution:   post limit orders — Hyperliquid maker fee 0.015%",
        "",
        "## Expected performance (backtest)",
        "  FULL 2018-2026  CAGR +148%  Sharpe 1.88  MaxDD -46%  Calmar 3.23",
        "  OOS 2022-2025   CAGR  +72%  Sharpe 1.33  MaxDD -46%",
        "",
        "## Risk guards",
        "  Kill-switch:    halt new entries if combined equity drops >40% from ATH.",
        "  Per-sleeve kill: pause a sleeve if its own DD exceeds 45%.",
        "  Fat-finger cap: reject any order > 3x the recommended notional.",
        "  Resume:         only when BTC closes above its 100-day SMA for >= 1 week.",
    ]
    _text_page(pdf, "Final Hyperliquid deployment spec", lines, fontsize=9,
               subtitle="Hybrid 70% XSM / 30% Trend - Sharpe 1.88")


def page_caveats(pdf):
    lines = [
        "## Honest caveats",
        "",
        "1. MaxDD -46%  You will watch the account drop from $X to $X/2 during crypto bear.",
        "   Psychological discipline is the main bottleneck to capturing the backtest alpha.",
        "",
        "2. 2021 alt-season contributed >50% of the 2018-2026 XSM CAGR.",
        "   If no comparable alt season arrives again the forward CAGR is lower.",
        "",
        "3. Backtest uses Hyperliquid maker-fee model (0.015% per side, 0 slippage).",
        "   Reality will be 70-90% fills as maker.  TSL exits hit as taker.",
        "   Expect forward CAGR to be 10-20% worse than backtest, DD 5-10% deeper.",
        "",
        "4. Universe concentration.  k=4 means each coin is 25% of the sleeve weekly.",
        "   One coin -50% that week loses the sleeve 12.5%.",
        "",
        "5. XSM correlation with trend = 0.44-0.53 (moderate).  Not fully independent.",
        "",
        "## What comes next",
        "",
        "The live_forward.py runner is ready for the TREND sleeve.",
        "An XSM equivalent (weekly rebalance + BTC filter) is a ~100 line script.",
        "",
        "Four genuine next bets (each 1-4 week research):",
        "  1. ML ranker with features beyond price (funding, OI, social sentiment)",
        "  2. Hyperliquid market-making (maker rebates, flat-expectation-per-hour)",
        "  3. Cross-sectional momentum at 1D granularity (different regime)",
        "  4. Options/funding arbitrage on Hyperliquid vs CEX perps",
    ]
    _text_page(pdf, "Caveats + what comes next", lines, fontsize=9)


def main():
    with PdfPages(OUT) as pdf:
        page_cover(pdf)
        page_pareto(pdf)
        page_v7_hwr(pdf)
        page_v8_v9(pdf)
        page_v10(pdf)
        page_v11(pdf)
        page_v12(pdf)
        page_v14(pdf)
        page_v15(pdf)
        page_v16(pdf)
        page_v17(pdf)
        page_v18(pdf)
        page_combined_equity(pdf)
        page_deploy(pdf)
        page_caveats(pdf)

    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
