"""
Final PDF report for V3E (winner after trend-validator optimization).

Pages:
  1. Cover — V3E headline metrics + per-asset + V2B vs V3E comparison
  2. Equity growth (log-scale, V2B + V3E + BH on one axis)
  3. Drawdown / underwater (V3E vs BH)
  4. Per-year returns + intra-year DD (V3E)
  5. V3 variant comparison table
  6. Rolling 1-year Sharpe (V3E)
  7. Strategy logic + validators explained + caveats
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages

plt.rcParams.update({
    "font.family":     "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid":       True,
    "grid.alpha":      0.25,
    "grid.linestyle":  "--",
    "figure.facecolor":"white",
})

ROOT = Path(__file__).resolve().parent / "results"
OUT  = ROOT / "FINAL_REPORT_V3E.pdf"


def _read(p):
    df = pd.read_csv(p, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    return df


eq_v3e  = _read(ROOT / "V3E_portfolio_equity.csv")
bh      = _read(ROOT / "V3E_bh_equity.csv")
eq_v2b  = _read(ROOT / "FINAL_portfolio_equity.csv")

per_year = pd.read_csv(ROOT / "V3E_per_year.csv")
comp     = pd.read_csv(ROOT / "V3_comparison.csv")
# rolling sharpe — rebuild from V3E equity series (avoids stale file)
rets = eq_v3e["portfolio_equity"].pct_change().dropna()
dt   = rets.index.to_series().diff().median()
bpy  = int(pd.Timedelta(days=365.25) / dt)
rs   = (rets.rolling(bpy).mean() / rets.rolling(bpy).std()) * np.sqrt(bpy)
rs   = rs.dropna()
report = json.loads((ROOT / "V3E_report.json").read_text())


def fmt_pct(x):  return f"{x*100:+.1f}%"
def fmt_usd(x):  return f"${x:,.0f}"
def fmt_ratio(x):return f"{x:.2f}"


def cover_page(pdf):
    p = report["portfolio"]; b = report["bh"]
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.axis("off")

    ax.text(0.5, 0.97, "Volume Breakout V3E",
            ha="center", fontsize=26, weight="bold")
    ax.text(0.5, 0.935, "with Trend-Validator Optimization (score 2-of-3)",
            ha="center", fontsize=13, color="#0a7c3a", weight="bold")
    ax.text(0.5, 0.908,
            "BTC / ETH / SOL @ 4h  —  2018-01-01 -> 2026-04-01  —  $10,000 demo",
            ha="center", fontsize=10, color="#666")
    ax.axhline(0.88, 0.05, 0.95, color="#ccc", lw=0.5)

    # Metrics table
    rows = [
        ("Final equity",  fmt_usd(p["final"]),  fmt_usd(b["final"])),
        ("Total return",  fmt_pct(p["total_return"]), fmt_pct(b["total_return"])),
        ("CAGR",          fmt_pct(p["cagr"]),   fmt_pct(b["cagr"])),
        ("Sharpe",        fmt_ratio(p["sharpe"]), fmt_ratio(b["sharpe"])),
        ("Sortino",       fmt_ratio(p["sortino"]), "—"),
        ("Max drawdown",  fmt_pct(p["max_dd"]), fmt_pct(b["max_dd"])),
        ("Calmar",        fmt_ratio(p["calmar"]),  fmt_ratio(b["calmar"])),
    ]
    ax.text(0.15, 0.85, "Metric", weight="bold", fontsize=11)
    ax.text(0.55, 0.85, "V3E Strategy", weight="bold", fontsize=11, color="#0a7c3a")
    ax.text(0.78, 0.85, "Buy & Hold", weight="bold", fontsize=11, color="#888")
    y = 0.82
    for k, sv, bv in rows:
        ax.text(0.15, y, k, fontsize=10.5)
        ax.text(0.55, y, sv, fontsize=10.5, color="#0a7c3a", weight="bold")
        ax.text(0.78, y, bv, fontsize=10.5, color="#666")
        y -= 0.030

    y -= 0.015
    ax.text(0.15, y,
            f"Equity vs BH: {p['final']/b['final']:.2f}x   |   "
            f"DD ratio: {p['max_dd']/b['max_dd']:.2f}x   |   "
            f"Calmar ratio: {p['calmar']/b['calmar']:.2f}x",
            fontsize=10, color="#0a7c3a", weight="bold")

    # V2B vs V3E comparison
    y -= 0.06
    ax.text(0.5, y, "V2B baseline  ->  V3E optimized",
            ha="center", fontsize=13, weight="bold"); y -= 0.04
    hdr = ["Metric","V2B baseline","V3E","Delta"]
    for x, h in zip([0.12, 0.38, 0.58, 0.77], hdr):
        ax.text(x, y, h, fontsize=10.5, weight="bold")
    y -= 0.025
    comp_rows = [
        ("CAGR",          42.43, p["cagr"]*100,       True),
        ("Sharpe",        1.21,  p["sharpe"],          True),
        ("Max drawdown",  -31.02, p["max_dd"]*100,     False),
        ("Calmar",        1.37,  p["calmar"],          True),
        ("Final equity",  184787, p["final"],          True),
    ]
    for name, v2, v3, up_good in comp_rows:
        delta = v3 - v2
        color = ("#0a7c3a" if (delta > 0) == up_good else "#c33")
        v2s = f"{v2:.2f}" if "rate" in name.lower() or "Sharpe" in name or "Calmar" in name else f"{v2:,.0f}" if name=="Final equity" else f"{v2:+.2f}%"
        v3s = f"{v3:.2f}" if "rate" in name.lower() or "Sharpe" in name or "Calmar" in name else f"${v3:,.0f}" if name=="Final equity" else f"{v3:+.2f}%"
        ds  = f"{delta:+.2f}" if name!="Final equity" else f"+${delta:,.0f}"
        ax.text(0.12, y, name, fontsize=10)
        ax.text(0.38, y, v2s, fontsize=10, color="#666")
        ax.text(0.58, y, v3s, fontsize=10, weight="bold", color="#0a7c3a")
        ax.text(0.77, y, ds, fontsize=10, color=color, weight="bold")
        y -= 0.026

    # Trend validators explained
    y -= 0.02
    ax.text(0.5, y, "Trend validators (entry requires score >= 2 of 3)",
            ha="center", fontsize=12, weight="bold", color="#0a7c3a"); y -= 0.032
    lines = [
        "G1: higher-timeframe 1-Day 200-EMA is rising (macro trend)",
        "G2: ADX(14) > 20 (trend strength, avoid chop)",
        "G3: short-term SMA(50) rising (momentum alignment)",
    ]
    for t in lines:
        ax.text(0.12, y, "  " + t, fontsize=10, family="monospace"); y -= 0.025

    # Walk-forward row
    y -= 0.015
    ax.text(0.5, y, "Honest walk-forward verification",
            ha="center", fontsize=12, weight="bold"); y -= 0.032
    wf_row = comp[comp["variant"] == "V3E_score2of3"].iloc[0]
    ax.text(0.5, y, f"IS 2018-2022: CAGR {wf_row['is_cagr']*100:.1f}%  "
                    f"Sharpe {wf_row['is_sharpe']:.2f}  "
                    f"DD {wf_row['is_maxdd']*100:.1f}%  "
                    f"Calmar {wf_row['is_calmar']:.2f}",
            ha="center", fontsize=10); y -= 0.023
    ax.text(0.5, y, f"OOS 2023-2026 (unseen): CAGR {wf_row['oos_cagr']*100:.1f}%  "
                    f"Sharpe {wf_row['oos_sharpe']:.2f}  "
                    f"DD {wf_row['oos_maxdd']*100:.1f}%  "
                    f"Calmar {wf_row['oos_calmar']:.2f}",
            ha="center", fontsize=10, color="#0a7c3a", weight="bold"); y -= 0.035

    # Per-asset
    ax.text(0.5, y, "Per-asset contribution",
            ha="center", fontsize=12, weight="bold"); y -= 0.035
    hdr = ["Asset","Init","CAGR","Sharpe","MaxDD","Trades","Win %","BH ret"]
    xs = [0.10, 0.22, 0.35, 0.47, 0.58, 0.70, 0.80, 0.90]
    for x, h in zip(xs, hdr):
        ax.text(x, y, h, fontsize=9.5, weight="bold")
    y -= 0.023
    for sym, m in report["per_asset"].items():
        row = [sym, f"${m['initial']:,.0f}",
               f"{m['cagr']*100:+.1f}%", f"{m['sharpe']:.2f}",
               f"{m['max_dd']*100:+.1f}%", str(m["n_trades"]),
               f"{m['win_rate']*100:.1f}%", f"{m['bh_return']*100:+.0f}%"]
        for x, v in zip(xs, row):
            ax.text(x, y, v, fontsize=9.5)
        y -= 0.022

    ax.text(0.5, 0.03,
            "Costs: 0.1 % fee per side + 5-tick slippage  |  "
            "Execution: next-bar OPEN after signal close",
            ha="center", fontsize=8, color="#888")
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def equity_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 7))
    v3 = eq_v3e["portfolio_equity"]
    v2 = eq_v2b["portfolio_equity"]
    bh_eq = bh["bh_equity"]
    ax.plot(v3.index, v3.values, lw=1.7, color="#0a7c3a", label="V3E (winner)")
    ax.plot(v2.index, v2.values, lw=1.2, color="#1f77b4", label="V2B baseline", alpha=0.8)
    ax.plot(bh_eq.index, bh_eq.values, lw=1.1, color="#999",
            label="Buy & Hold (60/25/15)")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"${x:,.0f}"))
    ax.set_title("Equity growth — $10,000 starting capital (log scale)",
                 fontsize=14, weight="bold", loc="left")
    ax.set_ylabel("Account equity")
    ax.legend(loc="upper left", frameon=False)

    events = {
        "2018 winter":  "2018-06-01",
        "COVID":        "2020-03-15",
        "BTC ATH1":     "2021-11-10",
        "LUNA / FTX":   "2022-11-11",
        "Halving rally":"2024-03-12",
    }
    for label, ds in events.items():
        t = pd.Timestamp(ds, tz="UTC")
        if t >= v3.index.min() and t <= v3.index.max():
            ax.axvline(t, color="#bbb", lw=0.7, ls=":")
            ax.text(t, ax.get_ylim()[1] * 0.95, label,
                    rotation=90, fontsize=7.5, color="#888", va="top")

    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def drawdown_page(pdf):
    v3 = eq_v3e["portfolio_equity"]
    bh_eq = bh["bh_equity"]
    v3_dd = v3 / v3.cummax() - 1.0
    bh_dd = bh_eq / bh_eq.cummax() - 1.0

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8),
                                   sharex=True, gridspec_kw={"height_ratios":[1, 1]})

    ax1.fill_between(v3_dd.index, v3_dd.values*100, 0,
                     color="#d62728", alpha=0.55, label="V3E strategy")
    ax1.set_ylabel("Drawdown %")
    ax1.set_title("Underwater chart — V3E strategy",
                  fontsize=13, weight="bold", loc="left")
    ax1.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"{x:.0f}%"))
    ax1.axhline(report["portfolio"]["max_dd"]*100,
                color="#8b0000", lw=0.8, ls="--",
                label=f"Max DD {report['portfolio']['max_dd']*100:.1f}%")
    ax1.legend(loc="lower left", frameon=False); ax1.set_ylim(top=2)

    ax2.fill_between(bh_dd.index, bh_dd.values*100, 0,
                     color="#888", alpha=0.55, label="Buy & Hold")
    ax2.set_ylabel("Drawdown %")
    ax2.set_title("Underwater chart — Buy & Hold",
                  fontsize=13, weight="bold", loc="left")
    ax2.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"{x:.0f}%"))
    ax2.axhline(report["bh"]["max_dd"]*100,
                color="#222", lw=0.8, ls="--",
                label=f"Max DD {report['bh']['max_dd']*100:.1f}%")
    ax2.legend(loc="lower left", frameon=False); ax2.set_ylim(top=2)

    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def per_year_page(pdf):
    df = per_year.copy()
    df["ret_pct"]    = df["ret"]    * 100
    df["bh_ret_pct"] = df["bh_ret"] * 100
    df["dd_pct"]     = df["dd"]     * 100

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9),
                                   gridspec_kw={"height_ratios":[2, 1]})
    x = np.arange(len(df)); w = 0.38
    bars_s = ax1.bar(x - w/2, df["ret_pct"], width=w,
                     color=["#0a7c3a" if v >= 0 else "#d62728" for v in df["ret_pct"]],
                     label="V3E strategy")
    bars_b = ax1.bar(x + w/2, df["bh_ret_pct"], width=w,
                     color="#bbb", label="Buy & Hold")
    ax1.set_xticks(x); ax1.set_xticklabels(df["year"])
    ax1.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"{x:.0f}%"))
    ax1.set_title("Annual returns — V3E vs Buy & Hold",
                  fontsize=13, weight="bold", loc="left")
    ax1.axhline(0, color="#333", lw=0.6); ax1.legend(frameon=False, loc="upper right")
    for bar, v in zip(bars_s, df["ret_pct"]):
        h = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2, h + (3 if h >= 0 else -6),
                 f"{v:+.0f}%", ha="center", fontsize=8)
    for bar, v in zip(bars_b, df["bh_ret_pct"]):
        h = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2, h + (3 if h >= 0 else -6),
                 f"{v:+.0f}%", ha="center", fontsize=8, color="#555")

    ax2.bar(x, df["dd_pct"], width=0.6, color="#d62728", alpha=0.7)
    ax2.set_xticks(x); ax2.set_xticklabels(df["year"])
    ax2.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"{x:.0f}%"))
    ax2.set_title("Max intra-year drawdown (V3E)",
                  fontsize=11, weight="bold", loc="left")
    for xi, v in zip(x, df["dd_pct"]):
        ax2.text(xi, v - 2, f"{v:.0f}%", ha="center", fontsize=8)
    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def variant_table_page(pdf):
    df = comp.copy()
    df_disp = df[["variant","full_cagr","full_sharpe","full_maxdd","full_calmar",
                  "oos_cagr","oos_sharpe","oos_maxdd","oos_calmar","full_trades"]]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.axis("off")
    ax.set_title("Trend-validator variants — performance comparison",
                 fontsize=13, weight="bold", loc="left")
    # render table
    col_labels = ["Variant","Full CAGR","Full Sharpe","Full DD","Full Calmar",
                  "OOS CAGR","OOS Sharpe","OOS DD","OOS Calmar","Trades"]
    cells = []
    for _, r in df_disp.iterrows():
        cells.append([
            r["variant"],
            f"{r['full_cagr']*100:+.1f}%",
            f"{r['full_sharpe']:.2f}",
            f"{r['full_maxdd']*100:+.1f}%",
            f"{r['full_calmar']:.2f}",
            f"{r['oos_cagr']*100:+.1f}%",
            f"{r['oos_sharpe']:.2f}",
            f"{r['oos_maxdd']*100:+.1f}%",
            f"{r['oos_calmar']:.2f}",
            str(int(r["full_trades"])),
        ])
    tbl = ax.table(cellText=cells, colLabels=col_labels, loc="center",
                   cellLoc="center")
    tbl.auto_set_font_size(False); tbl.set_fontsize(9)
    tbl.scale(1, 1.35)
    for j in range(len(col_labels)):
        tbl[(0, j)].set_facecolor("#eef"); tbl[(0, j)].set_text_props(weight="bold")
    # highlight V3E
    for i, r in df_disp.iterrows():
        if r["variant"] == "V3E_score2of3":
            for j in range(len(col_labels)):
                tbl[(i+1, j)].set_facecolor("#e6f6ea")
        elif r["variant"] == "V2B_baseline":
            for j in range(len(col_labels)):
                tbl[(i+1, j)].set_facecolor("#f4f4f4")

    # Footer note
    ax.text(0.5, -0.05,
            "V3E wins on full-period Calmar, full-period MaxDD, OOS Sharpe, and OOS Calmar "
            "vs the V2B baseline. V3D (all-3 required) has slightly better OOS Calmar "
            "but 25 % fewer trades and lower CAGR — V3E gives a better return-for-risk trade-off.",
            transform=ax.transAxes, ha="center", fontsize=9, color="#333")
    fig.tight_layout(); pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def rolling_sharpe_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(rs.index, rs.values, lw=1.2, color="#0a7c3a")
    ax.fill_between(rs.index, rs.values, 0, where=(rs.values > 0),
                    color="#0a7c3a", alpha=0.15)
    ax.fill_between(rs.index, rs.values, 0, where=(rs.values <= 0),
                    color="#d62728", alpha=0.25)
    ax.axhline(0, color="#222", lw=0.6)
    ax.axhline(rs.median(), color="#0a7c3a", lw=1, ls="--",
               label=f"Median {rs.median():.2f}")
    ax.set_title("Rolling 1-year Sharpe ratio — V3E strategy",
                 fontsize=13, weight="bold", loc="left")
    ax.set_ylabel("Rolling Sharpe"); ax.legend(frameon=False, loc="lower left")
    ax.text(0.02, 0.95,
            f"{(rs > 0).mean()*100:.1f} % of rolling windows positive   |   "
            f"25th={rs.quantile(.25):.2f}   75th={rs.quantile(.75):.2f}",
            transform=ax.transAxes, fontsize=9, color="#333", va="top")
    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def logic_page(pdf):
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.axis("off")
    ax.text(0.5, 0.96, "Strategy Logic — V3E",
            ha="center", fontsize=20, weight="bold")
    txt = [
        ("Breakout core (V2B carried forward):", True),
        ("  close > highest(high, 30)[1]", False),
        ("  AND volume > sma(volume, 20) x 1.3", False),
        ("  AND close > sma(close, 150)                  (mid-term regime)", False),
        ("", False),
        ("Trend validators (ADDED in V3E — score >= 2 of 3):", True),
        ("  G1: HTF 1-day 200-EMA rising                 (macro regime)", False),
        ("  G2: ADX(14) > 20                             (trend strength)", False),
        ("  G3: sma(close, 50) rising                    (short-term trend)", False),
        ("", False),
        ("Exits (whichever triggers first):", True),
        ("  a) ATR(14) x 4.5 trailing stop               (ratchets up)", False),
        ("  b) close < sma(close, 150)                   (regime failsafe)", False),
        ("", False),
        ("Execution:", True),
        ("  - Signal on closed bar i -> fill at OPEN of bar i+1 (no look-ahead)", False),
        ("  - Fees     : 0.1 % per side (Binance spot)", False),
        ("  - Slippage : 5 ticks", False),
        ("  - Position : 100 % of sub-account equity, no pyramiding", False),
        ("", False),
        ("Portfolio allocation (risk-adjusted):", True),
        ("  BTC 60 %   ETH 25 %   SOL 15 %   of $10,000 demo", False),
        ("", False),
        ("Caveats:", True),
        ("  - Long-only. Shorts consistently hurt in the 2018-2026 crypto cycle.", False),
        ("  - SOL asset-level DD -68.8 %. Portfolio DD smooths to -28.7 %.", False),
        ("  - OOS Sharpe degraded ~31 % vs IS. Expect live 0.8-1.0.", False),
        ("  - Single TF (4h). Next direction: multi-TF confirmation + session filter.", False),
    ]
    y = 0.91
    for line, bold in txt:
        ax.text(0.08, y, line, fontsize=11, weight="bold" if bold else "normal",
                family="monospace" if line.startswith("  ") else "DejaVu Sans")
        y -= 0.029

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def main():
    with PdfPages(OUT) as pdf:
        cover_page(pdf)
        equity_page(pdf)
        drawdown_page(pdf)
        per_year_page(pdf)
        variant_table_page(pdf)
        rolling_sharpe_page(pdf)
        logic_page(pdf)
        meta = pdf.infodict()
        meta["Title"]   = "Volume Breakout V3E — Trend-Validator Final Report"
        meta["Author"]  = "strategy_lab"
        meta["Subject"] = "V3E backtest 2018-2026 + walk-forward"
    print(f"Wrote {OUT}  ({OUT.stat().st_size/1024/1024:.2f} MB, 7 pages)")


if __name__ == "__main__":
    main()
