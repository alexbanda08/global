"""
Build the Hyperliquid-deploy-ready PDF report from portfolio_audit.py outputs.

Pages:
  1. Cover + recommended spec (conservative / balanced / aggressive)
  2. Combined portfolio equity curve (IS / OOS shaded)
  3. Drawdown underwater
  4. Leverage x sizing heatmap (OOS Calmar)
  5. Per-coin page: equity, DD, FULL/IS/OOS table, headline trade stats
     (one page per coin in the OOS-validated universe)
  6. Hyperliquid deployment checklist

Output: strategy_lab/reports/HYPERLIQUID_PORTFOLIO_REPORT.pdf
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
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

BASE = Path(__file__).resolve().parent
OUT  = BASE / "results" / "portfolio"
PER  = OUT / "per_coin"
PDF_OUT = BASE / "reports" / "HYPERLIQUID_PORTFOLIO_REPORT.pdf"
PDF_OUT.parent.mkdir(exist_ok=True)

COIN_COLOR = {
    "BTCUSDT":  "#f2a900",
    "ETHUSDT":  "#627eea",
    "SOLUSDT":  "#14f195",
    "LINKUSDT": "#2a5ada",
    "ADAUSDT":  "#0033ad",
    "XRPUSDT":  "#23292f",
    "AVAXUSDT": "#e84142",
    "DOGEUSDT": "#c2a633",
    "BNBUSDT":  "#f3ba2f",
}

IS_END = pd.Timestamp("2023-01-01", tz="UTC")


def _read_equity(path: Path) -> pd.Series:
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    return df.iloc[:, 0]


def _read_trades(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size < 50:
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["entry_time", "exit_time"])
    return df


def _fmt_pct(x, n=1): return f"{x*100:+.{n}f}%"
def _fmt_usd(x):       return f"${x:,.0f}"


# ---------------------------------------------------------------------
def page_cover(pdf: PdfPages, rec: dict):
    r   = rec["recommended"]
    m   = rec["metrics"]
    pr  = rec["profiles"]

    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.axis("off")
    ax.text(0.5, 0.96, "Hyperliquid Portfolio Spec",
            ha="center", fontsize=24, weight="bold")
    ax.text(0.5, 0.925,
            "Single $10 k account · 6-coin trend-following · 4h timeframe",
            ha="center", fontsize=13, color="#555")
    ax.text(0.5, 0.90,
            "Walk-forward validated: IS 2018-2022 → OOS 2023-2026",
            ha="center", fontsize=10, color="#888")
    ax.axhline(0.88, 0.05, 0.95, color="#ccc", lw=0.5)

    # Coin/strategy table
    coins = r["coins_and_strategies"]
    y = 0.82
    ax.text(0.08, y, "Asset", fontsize=11, weight="bold")
    ax.text(0.30, y, "Strategy", fontsize=11, weight="bold")
    ax.text(0.65, y, "FULL Sharpe", fontsize=11, weight="bold")
    ax.text(0.82, y, "OOS Sharpe", fontsize=11, weight="bold")
    per_coin = json.loads((OUT / "per_coin_summary.json").read_text())
    for i, (sym, strat) in enumerate(coins.items()):
        yy = 0.78 - i * 0.027
        full = per_coin[sym]["FULL"]; oos = per_coin[sym]["OOS"]
        c = COIN_COLOR.get(sym, "#333")
        ax.add_patch(plt.Rectangle((0.075, yy - 0.005), 0.01, 0.02, color=c))
        ax.text(0.093, yy, sym, fontsize=10)
        ax.text(0.30, yy, strat, fontsize=10)
        ax.text(0.68, yy, f"{full.get('sharpe',0):.2f}", fontsize=10)
        ax.text(0.85, yy, f"{oos.get('sharpe',0):.2f}", fontsize=10)

    # Recommended spec box (balanced default) + profiles
    y0 = 0.56
    ax.add_patch(plt.Rectangle((0.06, y0 - 0.30), 0.88, 0.32,
                               fill=False, edgecolor="#222", lw=1.3))
    ax.text(0.08, y0, "Recommended spec (BALANCED — default)",
            fontsize=12, weight="bold", color="#222")

    ax.text(0.08, y0 - 0.04,
            f"Sizing per trade        : {r['sizing_fraction_per_trade']*100:.1f}% of equity notional",
            fontsize=10)
    ax.text(0.08, y0 - 0.065,
            f"Leverage                : {r['leverage']}x",
            fontsize=10)
    ax.text(0.08, y0 - 0.09,
            f"Max gross exposure (all 6 long at once) : {r['max_gross_exposure_if_all_6_active']}x",
            fontsize=10)
    ax.text(0.08, y0 - 0.115,
            f"Initial capital         : ${r['initial_capital_usd']:,.0f}   |   Timeframe: {r['timeframe']}",
            fontsize=10)

    # Metrics trio
    for i, lbl in enumerate(("FULL", "IS", "OOS")):
        mm = m[lbl]
        x0 = 0.08 + i * 0.30
        y1 = y0 - 0.16
        ax.text(x0, y1, lbl, fontsize=11, weight="bold", color="#444")
        ax.text(x0, y1 - 0.025,
                f"CAGR    {_fmt_pct(mm.get('cagr', 0))}", fontsize=9)
        ax.text(x0, y1 - 0.045,
                f"Sharpe  {mm.get('sharpe', 0):.2f}", fontsize=9)
        ax.text(x0, y1 - 0.065,
                f"MaxDD   {_fmt_pct(mm.get('max_dd', 0))}", fontsize=9)
        ax.text(x0, y1 - 0.085,
                f"Calmar  {mm.get('calmar', 0):.2f}", fontsize=9)
        ax.text(x0, y1 - 0.105,
                f"Final   {_fmt_usd(mm.get('final', 0))}", fontsize=9)

    # Three profiles comparison
    y2 = 0.18
    ax.text(0.08, y2, "Risk profiles (pick one — all use the same coin/strategy set)",
            fontsize=11, weight="bold")
    ax.text(0.08, y2 - 0.03, "Profile", fontsize=10, weight="bold")
    ax.text(0.22, y2 - 0.03, "Size%", fontsize=10, weight="bold")
    ax.text(0.30, y2 - 0.03, "Lev",   fontsize=10, weight="bold")
    ax.text(0.38, y2 - 0.03, "Gross", fontsize=10, weight="bold")
    ax.text(0.48, y2 - 0.03, "OOS CAGR", fontsize=10, weight="bold")
    ax.text(0.62, y2 - 0.03, "OOS Sharpe", fontsize=10, weight="bold")
    ax.text(0.77, y2 - 0.03, "OOS MaxDD", fontsize=10, weight="bold")
    ax.text(0.90, y2 - 0.03, "Final", fontsize=10, weight="bold")
    for i, k in enumerate(("conservative", "balanced", "aggressive")):
        p = pr[k]
        yy = y2 - 0.055 - i * 0.025
        color = "#d90429" if k == "aggressive" else ("#0a9396" if k == "conservative" else "#222")
        ax.text(0.08, yy, k,                           fontsize=9, color=color,
                weight=("bold" if k == "balanced" else "normal"))
        ax.text(0.22, yy, f"{p['sizing_fraction_per_trade']*100:.1f}%", fontsize=9)
        ax.text(0.30, yy, f"{p['leverage']}x", fontsize=9)
        ax.text(0.38, yy, f"{p['max_gross_exposure']}x", fontsize=9)
        o = p["OOS"]
        ax.text(0.48, yy, _fmt_pct(o.get("cagr",0)), fontsize=9)
        ax.text(0.62, yy, f"{o.get('sharpe',0):.2f}", fontsize=9)
        ax.text(0.77, yy, _fmt_pct(o.get('max_dd',0)), fontsize=9)
        ax.text(0.90, yy, _fmt_usd(o.get("final",0)), fontsize=9)

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------
def page_combined_equity(pdf: PdfPages):
    eq_path = OUT / "portfolio_equity.csv"
    if not eq_path.exists():
        return
    eq = _read_equity(eq_path)
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(eq.index, eq.values, color="#222", lw=1.5, label="Portfolio equity")
    ax.axvspan(eq.index[0], IS_END, alpha=0.05, color="#0a9396", label="IS (2018-2022)")
    ax.axvspan(IS_END, eq.index[-1], alpha=0.05, color="#d90429", label="OOS (2023-2026)")
    ax.set_yscale("log")
    ax.set_title("$10k Portfolio — Combined Equity (log scale)")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.legend(loc="upper left", frameon=False)
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)

    # Underwater
    dd = (eq / eq.cummax()) - 1
    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.fill_between(dd.index, dd.values, 0, color="#d90429", alpha=0.7)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax.set_title("Drawdown (underwater)")
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------
def page_grid_heatmap(pdf: PdfPages):
    grid = pd.read_csv(OUT / "grid.csv")
    grid = grid[grid["valid"]]
    pivot = grid.pivot_table(index="sizing_frac", columns="leverage",
                             values="oos_calmar", aggfunc="mean")
    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.imshow(pivot.values, aspect="auto", origin="lower",
                   cmap="RdYlGn", vmin=-0.5, vmax=1.0)
    ax.set_xticks(range(len(pivot.columns))); ax.set_xticklabels([f"{c}x" for c in pivot.columns])
    ax.set_yticks(range(len(pivot.index)));   ax.set_yticklabels([f"{r*100:.0f}%" for r in pivot.index])
    ax.set_xlabel("Leverage"); ax.set_ylabel("Sizing fraction per trade")
    ax.set_title("OOS Calmar heatmap — (sizing fraction × leverage)")
    for i in range(pivot.shape[0]):
        for j in range(pivot.shape[1]):
            v = pivot.values[i, j]
            if np.isfinite(v):
                ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                        color=("black" if -0.2 <= v <= 0.9 else "white"))
    plt.colorbar(im, ax=ax, label="OOS Calmar")
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------
def page_per_coin(pdf: PdfPages, sym: str, summary_entry: dict):
    eq_path = PER / f"{sym}_equity.csv"
    tr_path = PER / f"{sym}_trades.csv"
    if not eq_path.exists():
        return
    eq = _read_equity(eq_path)
    tr = _read_trades(tr_path)

    fig = plt.figure(figsize=(11, 8.5))
    # Title
    strat = summary_entry["strategy"]
    fig.suptitle(f"{sym}  —  {strat}   (solo $10 k)", fontsize=15,
                 color=COIN_COLOR.get(sym, "#222"), weight="bold", y=0.97)

    # Equity (log)
    ax1 = fig.add_axes([0.08, 0.55, 0.88, 0.35])
    ax1.plot(eq.index, eq.values, color=COIN_COLOR.get(sym, "#222"), lw=1.4)
    ax1.axvspan(eq.index[0], IS_END, alpha=0.05, color="#0a9396")
    ax1.axvspan(IS_END, eq.index[-1], alpha=0.05, color="#d90429")
    ax1.set_yscale("log")
    ax1.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax1.set_title("Equity (log)  — IS shaded teal, OOS shaded red")

    # Drawdown
    dd = (eq / eq.cummax()) - 1
    ax2 = fig.add_axes([0.08, 0.38, 0.88, 0.13])
    ax2.fill_between(dd.index, dd.values, 0, color="#d90429", alpha=0.6)
    ax2.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax2.set_title("Drawdown")

    # Metrics table
    ax3 = fig.add_axes([0.08, 0.06, 0.50, 0.28]); ax3.axis("off")
    rows = [["Metric", "FULL", "IS (2018-22)", "OOS (2023-26)"]]
    for k in ("n_trades", "win_rate", "pf", "avg_bars_held",
              "cagr", "sharpe", "calmar", "max_dd", "final"):
        row = [k]
        for lbl in ("FULL", "IS", "OOS"):
            v = summary_entry[lbl].get(k)
            if v is None:
                row.append("—")
            elif k in ("cagr", "max_dd", "win_rate"):
                row.append(_fmt_pct(v) if v is not None else "—")
            elif k == "final":
                row.append(_fmt_usd(v))
            else:
                row.append(f"{v}")
        rows.append(row)
    table = ax3.table(cellText=rows, loc="center", cellLoc="left",
                      colWidths=[0.25, 0.25, 0.25, 0.25])
    table.auto_set_font_size(False); table.set_fontsize(8); table.scale(1, 1.4)
    for j in range(4):
        table[(0, j)].set_facecolor("#eaeaea"); table[(0, j)].set_text_props(weight="bold")

    # Trade stats
    ax4 = fig.add_axes([0.62, 0.06, 0.34, 0.28]); ax4.axis("off")
    if len(tr):
        wins = (tr["return"] > 0).sum(); losses = (tr["return"] <= 0).sum()
        stats = [
            ("Trades total",     f"{len(tr)}"),
            ("Wins / Losses",    f"{wins} / {losses}"),
            ("Win rate",         _fmt_pct(wins / len(tr))),
            ("Avg win (trade)",  _fmt_pct(tr[tr['return']>0]['return'].mean() or 0)),
            ("Avg loss (trade)", _fmt_pct(tr[tr['return']<=0]['return'].mean() or 0)),
            ("Largest win",      _fmt_pct(tr['return'].max())),
            ("Largest loss",     _fmt_pct(tr['return'].min())),
            ("Avg bars held",    f"{tr['bars_held'].mean():.1f}"),
            ("Longest hold",     f"{tr['bars_held'].max()} bars"),
            ("SL/TSL exits",     f"{(tr['reason']=='SL/TSL').sum()}"),
            ("Signal exits",     f"{(tr['reason']=='SIG').sum()}"),
        ]
        y = 0.98
        ax4.text(0, y, "Trade statistics (full period)", fontsize=10, weight="bold")
        for i, (k, v) in enumerate(stats):
            yy = 0.92 - i * 0.075
            ax4.text(0.0, yy, k, fontsize=9)
            ax4.text(0.75, yy, v, fontsize=9, ha="right")

    pdf.savefig(fig); plt.close(fig)


# ---------------------------------------------------------------------
def page_checklist(pdf: PdfPages, rec: dict):
    r = rec["recommended"]
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "Hyperliquid Deployment Checklist",
            ha="center", fontsize=20, weight="bold")

    lines = [
        ("Account setup", [
            "Fund a Hyperliquid account with $10,000 USDC (USD-equivalent).",
            f"Set account-wide leverage to {r['leverage']}x in Hyperliquid UI.",
            "Enable spot-margin (perp) for the 6 coins below.",
        ]),
        ("Coin / strategy map", [
            f"{sym:<9}  →  {strat}" for sym, strat in r["coins_and_strategies"].items()
        ]),
        ("Position sizing", [
            f"On every new entry: notional = {r['sizing_fraction_per_trade']*100:.1f}% × current equity.",
            f"With {r['leverage']}x leverage: margin used per position = {r['sizing_fraction_per_trade']/r['leverage']*100:.2f}% of equity.",
            f"Max gross exposure if all 6 coins long simultaneously: {r['max_gross_exposure_if_all_6_active']}x equity.",
            "Size is recomputed at entry time using CURRENT equity, not initial capital.",
        ]),
        ("Execution rules — LIMIT ORDERS BOTH SIDES (backtest model)", [
            "Timeframe: 4h bars. Signal generated on BAR CLOSE.",
            "On entry signal: post LIMIT BUY at the signal-bar close price; if the",
            "   next bar's low <= that price it fills; otherwise cancel and re-post.",
            "On exit signal (regime flip): post LIMIT SELL at close; falls back to",
            "   a market SL if not filled within 2 bars (taker fee applies there).",
            "Trailing stop (TSL) fires as a MARKET order when hit — accept the",
            "   taker fee for those exits; they are in the minority.",
            "Fee assumption in backtest: 0.015% maker per side (Hyperliquid spot-",
            "   equivalent perp maker).  Slippage 0 bps on limit fills.",
        ]),
        ("Risk guards", [
            "Kill-switch: if portfolio equity drops > 35% from ATH, halt all new entries.",
            "Per-coin kill-switch: if one coin loses > 50% of its allocated max loss, pause it.",
            "Fat-finger guard: reject any order notional > 3x recommended sizing.",
            "Rebalance frequency: none — strategies are independent, position-level.",
        ]),
        ("Forward-test before going live", [
            "Run on Hyperliquid testnet (or the paper-mode adapter) for ≥ 2 weeks.",
            "Compare live trade log vs equivalent backtest bar-by-bar (tolerance ±1%).",
            "If OOS Sharpe drifts below 0.5 over a rolling 3-month window, halt.",
        ]),
    ]
    y = 0.90
    for heading, items in lines:
        ax.text(0.06, y, heading, fontsize=12, weight="bold", color="#222")
        y -= 0.025
        for item in items:
            ax.text(0.09, y, "•  " + item, fontsize=9)
            y -= 0.022
        y -= 0.01

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------
def main():
    rec = json.loads((OUT / "recommended.json").read_text())
    summary = json.loads((OUT / "per_coin_summary.json").read_text())

    with PdfPages(PDF_OUT) as pdf:
        page_cover(pdf, rec)
        page_combined_equity(pdf)
        page_grid_heatmap(pdf)
        for sym in rec["recommended"]["coins_and_strategies"]:
            if sym in summary:
                page_per_coin(pdf, sym, summary[sym])
        page_checklist(pdf, rec)

    print(f"Wrote {PDF_OUT}")
    print(f"  pages: {2 + 1 + len(rec['recommended']['coins_and_strategies']) + 1}")


if __name__ == "__main__":
    main()
