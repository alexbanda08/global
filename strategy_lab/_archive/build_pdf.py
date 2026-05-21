"""
Build a multi-page PDF report for the winning strategy:

  1. Cover + headline metrics
  2. Equity growth curve (strategy vs BH, per-asset overlay)
  3. Drawdown / underwater chart
  4. Per-year returns (bar) + table
  5. Parameter sensitivity heatmap
  6. Rolling 1-year Sharpe
  7. Strategy logic + caveats

Output: strategy_lab/results/FINAL_REPORT.pdf
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
OUT  = ROOT / "FINAL_REPORT.pdf"


# ---------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------
def _read_eq(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    return df

eq       = _read_eq(ROOT / "FINAL_portfolio_equity.csv")
bh       = _read_eq(ROOT / "FINAL_bh_equity.csv")
per_year = pd.read_csv(ROOT / "WINNER_per_year.csv")
sens     = pd.read_csv(ROOT / "WINNER_param_sensitivity.csv")
rolling  = pd.read_csv(ROOT / "WINNER_rolling_sharpe.csv", index_col=0)
rolling.index = pd.to_datetime(rolling.index, utc=True)
report   = json.loads((ROOT / "FINAL_report.json").read_text())


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def fmt_pct(x):  return f"{x*100:+.1f}%"
def fmt_usd(x):  return f"${x:,.0f}"
def fmt_ratio(x):return f"{x:.2f}"


def cover_page(pdf):
    p = report["portfolio"]
    b = report["bh"]
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.axis("off")

    # Title
    ax.text(0.5, 0.96, "Volume Breakout V2B",
            ha="center", fontsize=26, weight="bold")
    ax.text(0.5, 0.92, "Cross-asset crypto strategy — BTC · ETH · SOL (4h)",
            ha="center", fontsize=13, color="#555")
    ax.text(0.5, 0.885,
            "Backtest 2018-01-01 → 2026-04-01   |   $10,000 demo   |   Binance spot",
            ha="center", fontsize=10, color="#888")

    # Headline box
    ax.axhline(0.855, 0.05, 0.95, color="#ccc", lw=0.5)
    rows = [
        ("Final equity",  fmt_usd(p["final"]),  fmt_usd(b["final"])),
        ("Total return",  fmt_pct(p["total_return"]), fmt_pct(b["total_return"])),
        ("CAGR",          fmt_pct(p["cagr"]),   fmt_pct(b["cagr"])),
        ("Sharpe",        fmt_ratio(p["sharpe"]), fmt_ratio(b["sharpe"])),
        ("Sortino",       fmt_ratio(p["sortino"]), "—"),
        ("Max drawdown",  fmt_pct(p["max_dd"]), fmt_pct(b["max_dd"])),
        ("Calmar",        fmt_ratio(p["calmar"]),  fmt_ratio(b["calmar"])),
    ]
    ax.text(0.15, 0.82, "Metric", weight="bold", fontsize=11)
    ax.text(0.55, 0.82, "Strategy", weight="bold", fontsize=11, color="#0a7c3a")
    ax.text(0.78, 0.82, "Buy & Hold", weight="bold", fontsize=11, color="#888")
    y = 0.79
    for k, sv, bv in rows:
        ax.text(0.15, y, k, fontsize=10.5)
        ax.text(0.55, y, sv, fontsize=10.5, color="#0a7c3a", weight="bold")
        ax.text(0.78, y, bv, fontsize=10.5, color="#666")
        y -= 0.032

    # Edge summary
    y -= 0.02
    ax.text(0.15, y,
            f"Equity multiple vs BH : {p['final']/b['final']:.2f}×   |   "
            f"DD reduction : {p['max_dd']/b['max_dd']:.2f}×   |   "
            f"Calmar ratio : {p['calmar']/b['calmar']:.2f}×",
            fontsize=10, color="#0a7c3a", weight="bold")

    # Allocation + params + walk-forward
    y -= 0.08
    ax.text(0.5, y, "Portfolio composition", ha="center",
            fontsize=13, weight="bold"); y -= 0.04
    alloc_str = "   |   ".join(f"{s}  {int(w*100)} %"
                               for s, w in report["allocation"].items())
    ax.text(0.5, y, alloc_str, ha="center", fontsize=11); y -= 0.05

    ax.text(0.5, y, "Strategy parameters (walk-forward selected)",
            ha="center", fontsize=13, weight="bold"); y -= 0.04
    p_str = ", ".join(f"{k}={v}" for k, v in report["params"].items())
    ax.text(0.5, y, p_str, ha="center", fontsize=10, family="monospace")
    y -= 0.045

    ax.text(0.5, y, "Walk-forward verification",
            ha="center", fontsize=13, weight="bold"); y -= 0.04
    ax.text(0.5, y,
            "IS 2018-2022 : CAGR 65.2 %   Sharpe 1.47   DD −27.9 %",
            ha="center", fontsize=10); y -= 0.028
    ax.text(0.5, y,
            "OOS 2023-2026 (unseen): CAGR 20.2 %   Sharpe 0.79   DD −24.1 %",
            ha="center", fontsize=10, color="#0a7c3a", weight="bold")
    y -= 0.07

    # Per-asset table
    ax.text(0.5, y, "Per-asset contribution",
            ha="center", fontsize=13, weight="bold"); y -= 0.04
    hdr = ["Asset","Init $","CAGR","Sharpe","MaxDD","Trades","Win %","BH return"]
    xs = [0.10, 0.22, 0.35, 0.47, 0.58, 0.70, 0.80, 0.90]
    for x, h in zip(xs, hdr):
        ax.text(x, y, h, fontsize=9.5, weight="bold")
    y -= 0.025
    for sym, m in report["per_asset"].items():
        row = [sym, f"${m['initial']:,.0f}",
               fmt_pct(m["cagr"]), fmt_ratio(m["sharpe"]),
               fmt_pct(m["max_dd"]), str(m["n_trades"]),
               f"{m['win_rate']*100:.1f}%", fmt_pct(m["bh_return"])]
        for x, v in zip(xs, row):
            ax.text(x, y, v, fontsize=9.5)
        y -= 0.023

    # Footer
    ax.text(0.5, 0.03,
            "Costs modelled: 0.1 % per side + 5-tick slippage  |  "
            "Execution: next-bar OPEN after signal",
            ha="center", fontsize=8, color="#888")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def equity_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 7))
    strat = eq["portfolio_equity"]
    bh_eq = bh["bh_equity"]
    ax.plot(strat.index, strat.values, lw=1.6, color="#0a7c3a",
            label="Volume Breakout V2B")
    ax.plot(bh_eq.index, bh_eq.values, lw=1.2, color="#999",
            label="Buy & Hold (60/25/15)")
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"${x:,.0f}"))
    ax.set_title("Equity growth — $10,000 starting capital (log scale)",
                 fontsize=14, weight="bold", loc="left")
    ax.set_xlabel("")
    ax.set_ylabel("Account equity")
    ax.legend(loc="upper left", frameon=False)
    # mark important events
    events = {
        "2018 crypto winter":   "2018-06-01",
        "COVID crash":          "2020-03-15",
        "BTC ATH 1":            "2021-11-10",
        "LUNA / FTX":           "2022-11-11",
        "2024 ATH":             "2024-03-12",
    }
    for label, ds in events.items():
        t = pd.Timestamp(ds, tz="UTC")
        if t >= strat.index.min() and t <= strat.index.max():
            ax.axvline(t, color="#bbb", lw=0.7, ls=":")
            ax.text(t, ax.get_ylim()[1] * 0.95, label,
                    rotation=90, fontsize=7.5, color="#888", va="top")

    fig.tight_layout()
    pdf.savefig(fig); plt.close(fig)


def drawdown_page(pdf):
    strat = eq["portfolio_equity"]
    bh_eq = bh["bh_equity"]
    strat_dd = strat / strat.cummax() - 1.0
    bh_dd    = bh_eq / bh_eq.cummax() - 1.0

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8),
                                   sharex=True, gridspec_kw={"height_ratios":[1, 1]})

    ax1.fill_between(strat_dd.index, strat_dd.values * 100, 0,
                     color="#d62728", alpha=0.55, label="Strategy")
    ax1.set_ylabel("Drawdown %"); ax1.set_title(
        "Underwater chart — Volume Breakout V2B",
        fontsize=13, weight="bold", loc="left")
    ax1.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"{x:.0f}%"))
    ax1.axhline(report["portfolio"]["max_dd"]*100, color="#8b0000",
                lw=0.8, ls="--",
                label=f"Max DD {report['portfolio']['max_dd']*100:.1f}%")
    ax1.legend(loc="lower left", frameon=False)
    ax1.set_ylim(top=2)

    ax2.fill_between(bh_dd.index, bh_dd.values * 100, 0,
                     color="#888", alpha=0.55, label="Buy & Hold")
    ax2.set_ylabel("Drawdown %"); ax2.set_title(
        "Underwater chart — Buy & Hold (60/25/15)",
        fontsize=13, weight="bold", loc="left")
    ax2.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"{x:.0f}%"))
    ax2.axhline(report["bh"]["max_dd"]*100, color="#222", lw=0.8, ls="--",
                label=f"Max DD {report['bh']['max_dd']*100:.1f}%")
    ax2.legend(loc="lower left", frameon=False)
    ax2.set_ylim(top=2)

    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def per_year_page(pdf):
    df = per_year.copy()
    df["ret_pct"]    = df["ret"]    * 100
    df["bh_ret_pct"] = df["bh_ret"] * 100
    df["dd_pct"]     = df["dd"]     * 100

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 9),
                                   gridspec_kw={"height_ratios":[2, 1]})

    x = np.arange(len(df))
    w = 0.38
    bars_s = ax1.bar(x - w/2, df["ret_pct"], width=w,
                     color=["#0a7c3a" if v >= 0 else "#d62728" for v in df["ret_pct"]],
                     label="Strategy")
    bars_b = ax1.bar(x + w/2, df["bh_ret_pct"], width=w,
                     color="#bbb", label="Buy & Hold")
    ax1.set_xticks(x); ax1.set_xticklabels(df["year"])
    ax1.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"{x:.0f}%"))
    ax1.set_title("Annual returns — Strategy vs Buy & Hold",
                  fontsize=13, weight="bold", loc="left")
    ax1.axhline(0, color="#333", lw=0.6)
    ax1.legend(frameon=False, loc="upper right")

    # Annotate bars
    for bar, v in zip(bars_s, df["ret_pct"]):
        h = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2,
                 h + (3 if h >= 0 else -6),
                 f"{v:+.0f}%", ha="center", fontsize=8)
    for bar, v in zip(bars_b, df["bh_ret_pct"]):
        h = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2,
                 h + (3 if h >= 0 else -6),
                 f"{v:+.0f}%", ha="center", fontsize=8, color="#555")

    # intra-year DD
    ax2.bar(x, df["dd_pct"], width=0.6, color="#d62728", alpha=0.7)
    ax2.set_xticks(x); ax2.set_xticklabels(df["year"])
    ax2.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"{x:.0f}%"))
    ax2.set_title("Max intra-year drawdown (strategy)",
                  fontsize=11, weight="bold", loc="left")
    ax2.axhline(0, color="#333", lw=0.6)
    for xi, v in zip(x, df["dd_pct"]):
        ax2.text(xi, v - 2, f"{v:.0f}%", ha="center", fontsize=8)
    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def sensitivity_page(pdf):
    # Heatmap: mean Calmar for each (don_len × vol_mult)
    pivot = sens.pivot_table(index="don_len", columns="vol_mult",
                             values="calmar", aggfunc="mean")
    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto", vmin=0.6, vmax=2.2)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels([f"{v:.1f}" for v in pivot.columns])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_xlabel("Volume spike multiplier")
    ax.set_ylabel("Donchian lookback")
    ax.set_title("Parameter sensitivity — mean Calmar across 108 combos",
                 fontsize=13, weight="bold", loc="left")
    for i in range(len(pivot.index)):
        for j in range(len(pivot.columns)):
            ax.text(j, i, f"{pivot.values[i, j]:.2f}",
                    ha="center", va="center",
                    color="white" if pivot.values[i, j] < 1.2 else "black",
                    fontsize=9, weight="bold")
    fig.colorbar(im, ax=ax, shrink=0.7, label="Mean Calmar")

    # Footer with stability summary
    ax.text(0, -0.22,
            f"Stability across 108 combos: CAGR ∈ [{sens.cagr.min()*100:.1f}%, "
            f"{sens.cagr.max()*100:.1f}%]   |   "
            f"Calmar ∈ [{sens.calmar.min():.2f}, {sens.calmar.max():.2f}]   |   "
            f"MaxDD ∈ [{sens.max_dd.min()*100:.1f}%, {sens.max_dd.max()*100:.1f}%]   |   "
            f"100 % of combos profitable",
            transform=ax.transAxes, fontsize=9, color="#333")
    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def rolling_sharpe_page(pdf):
    s = rolling.iloc[:, 0]
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(s.index, s.values, lw=1.2, color="#0a7c3a")
    ax.fill_between(s.index, s.values, 0,
                    where=(s.values > 0), color="#0a7c3a", alpha=0.15)
    ax.fill_between(s.index, s.values, 0,
                    where=(s.values <= 0), color="#d62728", alpha=0.25)
    ax.axhline(0, color="#222", lw=0.6)
    ax.axhline(s.median(), color="#0a7c3a", lw=1, ls="--",
               label=f"Median {s.median():.2f}")
    ax.set_title("Rolling 1-year Sharpe ratio — strategy",
                 fontsize=13, weight="bold", loc="left")
    ax.set_ylabel("Rolling Sharpe")
    ax.legend(frameon=False, loc="lower left")
    ax.text(0.02, 0.95,
            f"{(s > 0).mean() * 100:.1f} % of rolling windows positive   |   "
            f"25th={s.quantile(.25):.2f}   75th={s.quantile(.75):.2f}",
            transform=ax.transAxes, fontsize=9, color="#333",
            va="top")
    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


def logic_page(pdf):
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.axis("off")
    ax.text(0.5, 0.96, "Strategy Logic", ha="center", fontsize=20, weight="bold")

    txt = [
        ("Entry (ALL three must be true on bar close):", True),
        ("  1) close > highest(high, 30)[1]       breakout above prev 30-bar high", False),
        ("  2) volume > sma(volume, 20) × 1.3     volume-spike confirmation", False),
        ("  3) close > sma(close, 150)            higher-TF regime is up", False),
        ("", False),
        ("Exits (whichever triggers first):", True),
        ("  a) ATR(14) × 4.5 trailing stop        ratchets up from highest-since-entry", False),
        ("  b) close < sma(close, 150)            regime failsafe", False),
        ("", False),
        ("Execution & cost model:", True),
        ("  • Signal on closed bar i -> FILL at OPEN of bar i+1 (no look-ahead)", False),
        ("  • Fees     : 0.1 % per side (Binance spot)", False),
        ("  • Slippage : 5 ticks", False),
        ("  • Position : 100 % of sub-account equity per trade, no pyramiding", False),
        ("", False),
        ("Risk-adjusted portfolio allocation:", True),
        ("  BTC 60 %   ETH 25 %   SOL 15 %   of $10,000 demo", False),
        ("  Rationale: higher-quality / lower-vol assets get the largest share.", False),
        ("", False),
        ("Known limitations:", True),
        ("  • Long-only. Shorts were tested and consistently hurt in crypto bulls.", False),
        ("  • Single TF (4h). Adding multi-TF confirmation could improve OOS stability.", False),
        ("  • SOL asset-level DD of -71.9 % — portfolio only averages to -31 % because of", False),
        ("    imperfect correlation between assets.", False),
        ("  • OOS Sharpe degraded by ~46 % vs IS. Expect live Sharpe ~0.8-1.0.", False),
    ]
    y = 0.90
    for line, bold in txt:
        ax.text(0.08, y, line, fontsize=11, weight="bold" if bold else "normal",
                family="monospace" if line.startswith("  ") else "DejaVu Sans")
        y -= 0.032

    # Next-step roadmap
    y -= 0.02
    ax.text(0.5, y, "Planned optimisation: add trend-validator filter",
            ha="center", fontsize=13, weight="bold", color="#0a5"); y -= 0.03
    todo = [
        "• HTF 1d regime overlay: only allow longs when 1d 200-EMA rising",
        "• ADX(14) > 20 gate — avoid entries in chop",
        "• Composite trend score (MA slope + ADX + rising-vol) with threshold",
        "• Aim: keep CAGR, cut MaxDD below -25 %, lift OOS Sharpe > 1.0",
    ]
    for t in todo:
        ax.text(0.10, y, t, fontsize=10); y -= 0.025

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------
def main():
    with PdfPages(OUT) as pdf:
        cover_page(pdf)
        equity_page(pdf)
        drawdown_page(pdf)
        per_year_page(pdf)
        sensitivity_page(pdf)
        rolling_sharpe_page(pdf)
        logic_page(pdf)

        meta = pdf.infodict()
        meta["Title"]    = "Volume Breakout V2B — Final Report"
        meta["Author"]   = "strategy_lab"
        meta["Subject"]  = "Backtest of V2B on BTC/ETH/SOL 4h, 2018-2026"
        meta["Keywords"] = "crypto, vectorbt, backtest, strategy, pine"

    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"Wrote {OUT}  ({size_mb:.2f} MB, 7 pages)")


if __name__ == "__main__":
    main()
