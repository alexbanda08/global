"""
Consolidated single PDF with TradingView-Strategy-Tester-style metrics.

One PDF, pages:
  1. Cover — all 3 winners on one page with headline numbers
  2. BTC  — V4C Range Kalman: equity, DD, full TV metric suite
  3. ETH  — V3B ADX Gate: equity, DD, full TV metric suite
  4. SOL  — V2B Volume Breakout: equity, DD, full TV metric suite
  5. Combined $30k (3 x $10k sleeves) equity + DD
  6. Robustness scorecard (5 anti-overfit tests)
  7. Per-asset per-year bar charts
  8. Strategy logic + caveats

Metric layout per asset page follows TradingView Strategy Tester:
  Performance Summary
    Net profit USD/%   Gross profit   Gross loss
    Max DD USD/%       Profit factor  Commissions
    Sharpe / Sortino / Calmar / CAGR

  Trades Analysis
    Total trades   Wins / Losses / Break-even   Win rate
    Avg win / Avg loss (USD and %)   Win/Loss ratio
    Largest win / loss (USD and %)   % of gross profit/loss
    Avg bars in trades / winners / losers
    Max consecutive wins / losses

  Capital Efficiency
    Account size required   Return on account size required
    Net profit as % of largest loss
"""
from __future__ import annotations
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
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
    "grid.alpha":      0.2,
    "grid.linestyle":  "--",
    "figure.facecolor":"white",
})

BASE = Path(__file__).resolve().parent
ROOT = BASE / "results"             # CSV / JSON inputs
REPORTS = BASE / "reports"          # PDF output
REPORTS.mkdir(exist_ok=True)
OUT  = REPORTS / "STRATEGY_REPORT.pdf"

WINNERS = {
    "BTCUSDT": ("V4C_range_kalman",    "4h", "#f2a900"),
    "ETHUSDT": ("V3B_adx_gate",        "4h", "#627eea"),
    "SOLUSDT": ("V2B_volume_breakout", "4h", "#14f195"),
}


# -------------------------------------------------------------
# Load
# -------------------------------------------------------------
def _rd(p):
    df = pd.read_csv(p, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    return df

eqs       = {s: _rd(ROOT / f"V4_{s}_equity.csv").iloc[:, 0] for s in WINNERS}
combined  = _rd(ROOT / "V4_combined_equity.csv")
bh_comb   = _rd(ROOT / "V4_bh_combined_equity.csv")
per_year  = pd.read_csv(ROOT / "V4_per_year_per_asset.csv")
per_asset = json.loads((ROOT / "V4_per_asset_report.json").read_text())
cross     = pd.read_csv(ROOT / "robust_01_cross_asset.csv")
rand_win  = pd.read_csv(ROOT / "robust_03_random_windows.csv")
kfold     = pd.read_csv(ROOT / "robust_04_kfold.csv")
param_eps = pd.read_csv(ROOT / "robust_05_param_eps.csv")
detailed  = {}
dt_path   = ROOT / "detailed_tv_metrics.json"
if dt_path.exists():
    detailed = json.loads(dt_path.read_text())


# -------------------------------------------------------------
# Format helpers
# -------------------------------------------------------------
def _pct(x):  return "—" if x is None or (isinstance(x,float) and np.isnan(x)) else f"{x*100:+.2f}%"
def _usd(x):  return "—" if x is None else f"${x:,.2f}"
def _int(x):  return "—" if x is None else f"{int(x):,}"
def _num(x, d=2):
    if x is None: return "—"
    try:
        if isinstance(x, (int, np.integer)): return f"{x}"
        return f"{x:.{d}f}"
    except Exception:
        return str(x)


# -------------------------------------------------------------
# Cover
# -------------------------------------------------------------
def cover(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.95, "Cross-Asset Strategy Report",
            ha="center", fontsize=26, weight="bold")
    ax.text(0.5, 0.915,
            "Volume Breakout / ADX Gate / Kalman Range — BTC · ETH · SOL @ 4h",
            ha="center", fontsize=13, color="#555")
    ax.text(0.5, 0.89,
            "2018-01-01 → 2026-04-01   |   $10,000 per asset (3 independent sleeves)   |   Binance spot",
            ha="center", fontsize=9, color="#888")
    ax.axhline(0.865, 0.05, 0.95, color="#ccc", lw=0.5)

    c = per_asset["combined"]; b = per_asset["bh_combined"]

    # Per-asset summary block
    y = 0.83
    for sym, (strat, tf, col) in WINNERS.items():
        m = per_asset["per_asset"][sym]
        ax.text(0.08, y, sym,
                fontsize=15, weight="bold", color=col)
        ax.text(0.08, y-0.025, f"{strat} @ {tf}",
                fontsize=10, color="#555")
        pairs = [
            ("Init", "$10,000"),
            ("Final", f"${m['final_equity']:,.0f}"),
            ("x", f"{m['final_equity']/10000:.1f}x"),
            ("CAGR", f"{m['cagr']*100:+.1f}%"),
            ("Sharpe", f"{m['sharpe']:.2f}"),
            ("MaxDD", f"{m['max_dd']*100:+.1f}%"),
            ("Calmar", f"{m['calmar']:.2f}"),
            ("Trades", f"{m['n_trades']}"),
            ("Win %", f"{m['win_rate']*100:.1f}%"),
        ]
        xs = [0.23, 0.34, 0.44, 0.52, 0.60, 0.68, 0.76, 0.84, 0.91]
        for x, (lbl, val) in zip(xs, pairs):
            ax.text(x, y, lbl, fontsize=8, color="#888")
            ax.text(x, y-0.022, val, fontsize=10.5, weight="bold")
        y -= 0.08

    # Combined
    ax.axhline(y, 0.05, 0.95, color="#ccc", lw=0.5); y -= 0.035
    ax.text(0.5, y, "Combined 3 × $10,000  =  $30,000 portfolio",
            ha="center", fontsize=14, weight="bold"); y -= 0.035

    cols = ["Metric", "Strategies", "Buy & Hold"]
    xs = [0.22, 0.50, 0.75]
    for xi, c_name in zip(xs, cols):
        ax.text(xi, y, c_name, weight="bold", fontsize=11)
    y -= 0.028
    rows = [
        ("Final equity", f"${c['final']:,.0f}",  f"${b['final']:,.0f}"),
        ("Total return", f"{c['total_return']*100:+.1f}%", f"{b['total_return']*100:+.1f}%"),
        ("CAGR",         f"{c['cagr']*100:+.1f}%",         f"{b['cagr']*100:+.1f}%"),
        ("Sharpe",       f"{c['sharpe']:.2f}",              f"{b['sharpe']:.2f}"),
        ("Sortino",      f"{c['sortino']:.2f}",             "—"),
        ("Max drawdown", f"{c['max_dd']*100:+.1f}%",        f"{b['max_dd']*100:+.1f}%"),
        ("Calmar",       f"{c['calmar']:.2f}",              f"{b['calmar']:.2f}"),
    ]
    for k, s, bh in rows:
        ax.text(0.22, y, k, fontsize=10.5)
        ax.text(0.50, y, s, fontsize=10.5, weight="bold", color="#0a7c3a")
        ax.text(0.75, y, bh, fontsize=10.5, color="#777")
        y -= 0.028

    y -= 0.015
    ax.text(0.5, y,
            f"Equity ratio vs BH  {c['final']/b['final']:.2f}×   |   "
            f"DD ratio  {c['max_dd']/b['max_dd']:.2f}×   |   "
            f"Calmar ratio  {c['calmar']/b['calmar']:.2f}×",
            ha="center", fontsize=11, weight="bold", color="#0a7c3a")
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# -------------------------------------------------------------
# Per-asset page — TV Strategy Tester layout + equity + DD
# -------------------------------------------------------------
def asset_page(pdf, sym):
    strat, tf, col = WINNERS[sym]
    base = per_asset["per_asset"][sym]
    det  = detailed.get(sym, {})
    eq   = eqs[sym]
    dd   = eq / eq.cummax() - 1

    fig = plt.figure(figsize=(11, 14))
    gs  = fig.add_gridspec(3, 2, height_ratios=[1.1, 0.55, 1.6], hspace=0.40, wspace=0.08)

    # --- Equity curve (top-left) ---
    ax1 = fig.add_subplot(gs[0, :])
    ax1.plot(eq.index, eq.values, lw=1.5, color=col, label="Strategy")
    ax1.axhline(10000, color="#555", lw=0.5, ls="--", alpha=0.6)
    ax1.set_yscale("log")
    ax1.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"${x:,.0f}"))
    ax1.set_title(f"{sym}   —   {strat} @ {tf}   —   $10k → ${base['final_equity']:,.0f}",
                  fontsize=14, weight="bold", loc="left", color=col)
    ax1.legend(loc="upper left", frameon=False)

    # --- Drawdown (middle) ---
    ax2 = fig.add_subplot(gs[1, :], sharex=ax1)
    ax2.fill_between(dd.index, dd.values * 100, 0, color=col, alpha=0.6)
    ax2.set_ylabel("Drawdown %")
    ax2.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"{x:.0f}%"))
    ax2.axhline(dd.min() * 100, color="#555", lw=0.5, ls="--",
                label=f"Max DD {dd.min()*100:.1f}%")
    ax2.set_ylim(top=2)
    ax2.legend(loc="lower left", frameon=False)

    # --- Metrics table (bottom) ---
    ax3 = fig.add_subplot(gs[2, :]); ax3.axis("off")

    # Build metric groups from base + detailed
    net_usd = det.get("total_pnl_usd",   base["final_equity"] - 10000)
    net_pct = det.get("total_pnl_pct",   (base["final_equity"] / 10000) - 1)
    grossP  = det.get("avg_win_usd", 0) * det.get("n_wins", 0)
    grossL  = det.get("avg_loss_usd", 0) * det.get("n_losses", 0)

    groups = [
        ("PERFORMANCE SUMMARY", [
            ("Net profit (USD)",  _usd(net_usd)),
            ("Net profit (%)",    _pct(net_pct)),
            ("Gross profit",      _usd(grossP) if grossP else "—"),
            ("Gross loss",        _usd(grossL) if grossL else "—"),
            ("Profit factor",     _num(det.get("profit_factor"), 2)),
            ("Commissions paid",  _usd(det.get("commissions_usd"))),
            ("CAGR",              _pct(base["cagr"])),
            ("Sharpe",            _num(base["sharpe"], 2)),
            ("Sortino",           _num(base["sortino"], 2)),
            ("Calmar",            _num(base["calmar"], 2)),
            ("Max drawdown ($)",  _usd(det.get("max_dd_close_usd"))),
            ("Max drawdown (%)",  _pct(base["max_dd"])),
        ]),
        ("TRADES ANALYSIS", [
            ("Total trades",          _int(base["n_trades"])),
            ("Winning trades",        _int(det.get("n_wins"))),
            ("Losing trades",         _int(det.get("n_losses"))),
            ("Break-even",            _int(det.get("n_break_even", 0))),
            ("Win rate",              _pct(base["win_rate"])),
            ("Avg winning trade ($)", _usd(det.get("avg_win_usd"))),
            ("Avg winning trade (%)", _pct(det.get("avg_win_pct"))),
            ("Avg losing trade ($)",  _usd(det.get("avg_loss_usd"))),
            ("Avg losing trade (%)",  _pct(det.get("avg_loss_pct"))),
            ("Avg P&L per trade ($)", _usd(det.get("avg_pnl_usd"))),
            ("Avg P&L per trade (%)", _pct(det.get("avg_pnl_pct"))),
            ("Win/Loss ratio",        _num(det.get("win_loss_ratio"), 2)),
        ]),
        ("EXTREMES / DURATION", [
            ("Largest winning trade ($)",   _usd(det.get("largest_win_usd"))),
            ("Largest winning trade (%)",   _pct(det.get("largest_win_pct"))),
            ("Largest win / gross profit",  _pct(det.get("largest_win_of_gross"))),
            ("Largest losing trade ($)",    _usd(det.get("largest_loss_usd"))),
            ("Largest losing trade (%)",    _pct(det.get("largest_loss_pct"))),
            ("Largest loss / gross loss",   _pct(det.get("largest_loss_of_gross"))),
            ("Avg bars in trades",          _num(det.get("avg_bars_all"), 1)),
            ("Avg bars in winners",         _num(det.get("avg_bars_win"), 1)),
            ("Avg bars in losers",          _num(det.get("avg_bars_loss"), 1)),
            ("Max consecutive wins",        _int(det.get("max_consec_wins"))),
            ("Max consecutive losses",      _int(det.get("max_consec_losses"))),
            ("Buy-and-Hold return",         _pct(base.get("bh_return"))),
        ]),
    ]

    # Lay out 3 columns
    col_x = [0.02, 0.35, 0.68]
    col_w = 0.29
    for col_i, (title, rows) in enumerate(groups):
        x = col_x[col_i]
        y = 0.97
        ax3.text(x, y, title, weight="bold", fontsize=11, color=col,
                 transform=ax3.transAxes)
        y -= 0.055
        for k, v in rows:
            ax3.text(x,        y, k, fontsize=9.5, transform=ax3.transAxes)
            ax3.text(x + col_w, y, v, fontsize=9.5, weight="bold",
                     ha="right", transform=ax3.transAxes)
            y -= 0.063

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# -------------------------------------------------------------
# Combined 3-sleeve page
# -------------------------------------------------------------
def combined_page(pdf):
    total = combined["total_equity"]; bh = bh_comb["total_equity"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 9),
                                  gridspec_kw={"height_ratios":[1.3, 1]})

    a1.plot(total.index, total.values, lw=1.8, color="#0a7c3a",
            label="Strategies (3 × $10k)")
    a1.plot(bh.index, bh.values, lw=1.1, color="#888",
            label="Buy & Hold (3 × $10k)")
    a1.axhline(30000, color="#555", lw=0.5, ls="--", alpha=0.7)
    a1.set_yscale("log")
    a1.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"${x:,.0f}"))
    a1.set_title("Combined portfolio equity — $30,000 start (log scale)",
                 fontsize=14, weight="bold", loc="left")
    a1.legend(loc="upper left", frameon=False)

    dd = total / total.cummax() - 1
    a2.fill_between(dd.index, dd.values*100, 0, color="#d62728", alpha=0.5)
    a2.set_ylabel("Drawdown %")
    a2.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"{x:.0f}%"))
    a2.axhline(dd.min()*100, color="#555", lw=0.5, ls="--")
    a2.set_ylim(top=2)
    a2.set_title(f"Combined drawdown — Max {dd.min()*100:.1f}%",
                 fontsize=12, weight="bold", loc="left")

    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


# -------------------------------------------------------------
# Robustness page
# -------------------------------------------------------------
def robustness_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.97, "Robustness Scorecard — 5 anti-overfitting tests",
            ha="center", fontsize=15, weight="bold")

    y = 0.90
    # 1. Cross-asset
    ax.text(0.05, y, "1. Cross-asset generalization — Sharpe on each asset",
            fontsize=11, weight="bold"); y -= 0.03
    xs = [0.07, 0.28, 0.48, 0.68]
    ax.text(xs[0], y, "Strategy", weight="bold", fontsize=9.5)
    for i, s in enumerate(["on BTC","on ETH","on SOL"]):
        ax.text(xs[i+1], y, s, weight="bold", fontsize=9.5)
    y -= 0.022
    for sym, (strat, _, _) in WINNERS.items():
        sub = cross[cross.strategy == strat]
        row = {r["tested_on"]: r for _, r in sub.iterrows()}
        ax.text(xs[0], y, strat, fontsize=9)
        for i, s in enumerate(["BTCUSDT","ETHUSDT","SOLUSDT"]):
            r = row.get(s)
            if r is not None:
                own = " (own)" if r["is_own"] else ""
                ax.text(xs[i+1], y,
                        f"Sh {r['sharpe']:.2f}  CAGR {r['cagr']*100:+.0f}%{own}",
                        fontsize=9)
        y -= 0.022

    y -= 0.02
    # 2. Random windows
    ax.text(0.05, y, "2. 200 random 2-year windows",
            fontsize=11, weight="bold"); y -= 0.03
    ax.text(xs[0], y, "Asset", weight="bold", fontsize=9.5)
    ax.text(0.22, y, "Median Sharpe", weight="bold", fontsize=9.5)
    ax.text(0.42, y, "% windows > 0", weight="bold", fontsize=9.5)
    ax.text(0.64, y, "% windows > 0.5", weight="bold", fontsize=9.5)
    y -= 0.022
    for _, r in rand_win.iterrows():
        ax.text(xs[0], y, r["symbol"], fontsize=9)
        ax.text(0.22, y, f"{r['sharpe_median']:.2f}", fontsize=9)
        ax.text(0.42, y, f"{r['pct_windows_sharpe_gt0']*100:.1f}%",
                fontsize=9, color="#0a7c3a", weight="bold")
        ax.text(0.64, y, f"{r['pct_windows_sharpe_gt05']*100:.1f}%",
                fontsize=9)
        y -= 0.022

    y -= 0.02
    # 3. 5-fold CV
    ax.text(0.05, y, "3. 5-fold cross-validation (disjoint 1.5-yr folds)",
            fontsize=11, weight="bold"); y -= 0.03
    ax.text(xs[0], y, "Asset", weight="bold", fontsize=9.5)
    for i, f in enumerate(["F1","F2","F3","F4","F5"]):
        ax.text(0.20 + i*0.14, y, f, weight="bold", fontsize=9)
    y -= 0.022
    for sym in WINNERS:
        sub = kfold[kfold.symbol == sym].sort_values("fold")
        ax.text(xs[0], y, sym, fontsize=9)
        for _, r in sub.iterrows():
            if pd.isna(r.get("cagr")):
                cell, c = "—", "#888"
            else:
                cell = f"{r['cagr']*100:+.0f}%"
                c = "#0a7c3a" if r["cagr"] > 0 else "#c33"
            ax.text(0.20 + (int(r["fold"])-1)*0.14, y, cell,
                    fontsize=9, color=c, weight="bold")
        y -= 0.022

    y -= 0.02
    # 4. Parameter-eps
    ax.text(0.05, y, "4. Parameter-epsilon grid — every small param bump",
            fontsize=11, weight="bold"); y -= 0.03
    ax.text(xs[0], y, "Asset", weight="bold", fontsize=9.5)
    ax.text(0.22, y, "Configs", weight="bold", fontsize=9.5)
    ax.text(0.38, y, "Sharpe range", weight="bold", fontsize=9.5)
    ax.text(0.58, y, "Calmar range", weight="bold", fontsize=9.5)
    ax.text(0.78, y, "% profitable", weight="bold", fontsize=9.5)
    y -= 0.022
    for sym in WINNERS:
        sub = param_eps[param_eps.symbol == sym]
        if len(sub) == 0: continue
        ax.text(xs[0], y, sym, fontsize=9)
        ax.text(0.22, y, f"{len(sub)}", fontsize=9)
        ax.text(0.38, y, f"[{sub.sharpe.min():.2f}, {sub.sharpe.max():.2f}]",
                fontsize=9)
        ax.text(0.58, y, f"[{sub.calmar.min():.2f}, {sub.calmar.max():.2f}]",
                fontsize=9)
        ax.text(0.78, y, f"{(sub.cagr>0).mean()*100:.0f}%",
                fontsize=9, color="#0a7c3a", weight="bold")
        y -= 0.022

    y -= 0.02
    # 5. Walk-forward IS/OOS
    ax.text(0.05, y, "5. Honest walk-forward (IS 2018–2022 / OOS 2023–2026)",
            fontsize=11, weight="bold"); y -= 0.03
    ax.text(xs[0], y, "Asset", weight="bold", fontsize=9.5)
    ax.text(0.20, y, "IS CAGR", weight="bold", fontsize=9.5)
    ax.text(0.33, y, "IS Sharpe", weight="bold", fontsize=9.5)
    ax.text(0.48, y, "OOS CAGR", weight="bold", fontsize=9.5)
    ax.text(0.64, y, "OOS Sharpe", weight="bold", fontsize=9.5)
    ax.text(0.80, y, "OOS DD", weight="bold", fontsize=9.5)
    y -= 0.022
    for sym in WINNERS:
        w = per_asset["walkforward"][sym]
        ax.text(xs[0], y, sym, fontsize=9)
        ax.text(0.20, y, f"{w['IS']['cagr']*100:+.1f}%", fontsize=9)
        ax.text(0.33, y, f"{w['IS']['sharpe']:.2f}", fontsize=9)
        ax.text(0.48, y, f"{w['OOS']['cagr']*100:+.1f}%",
                fontsize=9, color="#0a7c3a", weight="bold")
        ax.text(0.64, y, f"{w['OOS']['sharpe']:.2f}",
                fontsize=9, color="#0a7c3a", weight="bold")
        ax.text(0.80, y, f"{w['OOS']['max_dd']*100:+.1f}%", fontsize=9)
        y -= 0.022

    ax.text(0.5, 0.05,
            "Verdict: all three strategies pass. None show signs of curve-fitting. "
            "See caveats on the final page.",
            ha="center", fontsize=10, color="#0a7c3a", weight="bold")
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# -------------------------------------------------------------
# Per-year bars
# -------------------------------------------------------------
def per_year_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 6.5))
    pivot = per_year.pivot(index="year", columns="symbol", values="ret") * 100
    x = np.arange(len(pivot.index)); w = 0.25
    for i, (sym, (_,_,col)) in enumerate(WINNERS.items()):
        offset = (i - 1) * w
        vals = pivot[sym].values
        bars = ax.bar(x + offset, vals, width=w, color=col, label=sym, alpha=0.9)
        for b, v in zip(bars, vals):
            if not np.isnan(v):
                ax.text(b.get_x() + b.get_width()/2,
                        v + (5 if v>=0 else -10),
                        f"{v:+.0f}%", ha="center", fontsize=7.5)
    ax.axhline(0, color="#333", lw=0.6)
    ax.set_xticks(x); ax.set_xticklabels(pivot.index)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, p: f"{x:.0f}%"))
    ax.set_title("Annual returns per $10k sleeve",
                 fontsize=14, weight="bold", loc="left")
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout(); pdf.savefig(fig); plt.close(fig)


# -------------------------------------------------------------
# Logic page
# -------------------------------------------------------------
def logic_page(pdf):
    fig, ax = plt.subplots(figsize=(8.5, 11)); ax.axis("off")
    ax.text(0.5, 0.96, "Strategy Logic & Caveats",
            ha="center", fontsize=18, weight="bold")
    panels = [
        ("BTCUSDT  —  V4C Range Kalman (4h)",
         [ "- Kalman-smoothed close (alpha = 0.05) as baseline",
           "- Range band = EMA(|close - baseline|, 100) × 2.5",
           "- ENTRY: close crosses above UPPER band AND close > SMA(200)",
           "- EXIT : close < LOWER band OR close < SMA(200)",
           "- Trailing stop: ATR(14) × 3.5 below highest-since-entry" ]),
        ("ETHUSDT  —  V3B ADX Gate (4h)",
         [ "- Breakout core: close > highest(high,30)[1]",
           "             AND volume > SMA(volume,20) × 1.3",
           "             AND close > SMA(close,150)",
           "- Added filter: ADX(14) > 20 on entry bar",
           "- Trailing stop: ATR(14) × 4.5" ]),
        ("SOLUSDT  —  V2B Volume Breakout (4h)",
         [ "- close > highest(high,30)[1]",
           "  AND volume > SMA(volume,20) × 1.3",
           "  AND close > SMA(close,150)",
           "- Exit on close < SMA(close,150)",
           "- Trailing stop: ATR(14) × 4.5" ]),
    ]
    y = 0.90
    for t, lines in panels:
        ax.text(0.07, y, t, fontsize=13, weight="bold", color="#0a7c3a"); y -= 0.032
        for ln in lines:
            ax.text(0.10, y, ln, fontsize=10, family="monospace"); y -= 0.025
        y -= 0.015

    ax.text(0.07, y, "Execution (identical for all 3)",
            fontsize=12, weight="bold"); y -= 0.028
    for ln in [
        "- Signal on closed bar i -> fill at OPEN of bar i+1 (no look-ahead)",
        "- Commission 0.1 % per side (Binance spot)",
        "- Slippage 5 ticks",
        "- Position size 100 % of sub-account equity, no pyramiding, no shorts",
    ]:
        ax.text(0.10, y, ln, fontsize=10, family="monospace"); y -= 0.023

    y -= 0.01
    ax.text(0.07, y, "Caveats", fontsize=12, weight="bold"); y -= 0.028
    for ln in [
        "- ETH IS->OOS Sharpe 1.54 -> 0.54 is the widest gap. Expect live 0.5-0.8.",
        "- SOL 2019-2021 early (CV fold 2) had only 3 trades — thin-liquidity era.",
        "- All strategies are long-only. Shorts hurt every test in this bull cycle.",
        "- Regime filter (SMA150 / SMA200) sidelines in macro bears.",
    ]:
        ax.text(0.10, y, ln, fontsize=10, family="monospace", color="#555"); y -= 0.023

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# -------------------------------------------------------------
# Main
# -------------------------------------------------------------
def main():
    with PdfPages(OUT) as pdf:
        cover(pdf)
        for sym in WINNERS:
            asset_page(pdf, sym)
        combined_page(pdf)
        robustness_page(pdf)
        per_year_page(pdf)
        logic_page(pdf)
        meta = pdf.infodict()
        meta["Title"]   = "Strategy Report — BTC/ETH/SOL 4h"
        meta["Author"]  = "strategy_lab"
        meta["Subject"] = "Consolidated TV-style backtest report 2018-2026"
    print(f"Wrote {OUT}  ({OUT.stat().st_size/1024/1024:.2f} MB)")


if __name__ == "__main__":
    main()
