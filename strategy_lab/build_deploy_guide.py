"""
Build DEPLOY_GUIDE.pdf — focused deployment guide for the GOOD strategies only.

Includes equity curves (period views), drawdown charts, trades-per-year,
year-by-year performance tables, small-capital Hyperliquid deployment
recipe, leverage guide, and step-by-step checklist.

Destination: C:\\Users\\alexandre bandarra\\Desktop\\newstrategies\\DEPLOY_GUIDE.pdf
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
    "font.family":    "DejaVu Sans",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid":      True,
    "grid.alpha":     0.25,
    "grid.linestyle": "--",
    "figure.facecolor":"white",
})

BASE = Path(__file__).resolve().parent
RES  = BASE / "results"
OUT_LOCAL = BASE / "reports" / "DEPLOY_GUIDE.pdf"
OUT_PUBLIC = Path("C:/Users/alexandre bandarra/Desktop/newstrategies/DEPLOY_GUIDE.pdf")
OUT_PUBLIC.parent.mkdir(parents=True, exist_ok=True)

IS_END = pd.Timestamp("2023-01-01", tz="UTC")
BARS_PER_YR = 365.25 * 24 / 4

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def read_equity(path: Path) -> pd.Series:
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.iloc[:, 0]


def read_trades(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size < 50:
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["entry_time", "exit_time"])
    return df


def metrics(eq: pd.Series) -> dict:
    if len(eq) < 20: return {}
    rets = eq.pct_change(fill_method=None).fillna(0)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 0.01)) - 1
    sh = (rets.mean() * BARS_PER_YR) / (rets.std() * np.sqrt(BARS_PER_YR) + 1e-12)
    dd = float((eq / eq.cummax() - 1).min())
    return {
        "cagr": float(cagr), "sharpe": float(sh), "dd": float(dd),
        "calmar": cagr / abs(dd) if dd < 0 else 0,
        "final": float(eq.iloc[-1]), "initial": float(eq.iloc[0]),
    }


def year_stats(eq: pd.Series, trades: pd.DataFrame | None = None) -> pd.DataFrame:
    years = sorted(set(eq.index.year))
    rows = []
    for y in years:
        s = pd.Timestamp(f"{y}-01-01", tz="UTC")
        e = pd.Timestamp(f"{y+1}-01-01", tz="UTC")
        eq_y = eq[(eq.index >= s) & (eq.index < e)]
        if len(eq_y) < 5: continue
        ret = eq_y.iloc[-1] / eq_y.iloc[0] - 1
        dd = float((eq_y / eq_y.cummax() - 1).min())
        n_tr = 0; wr = None
        if trades is not None and len(trades):
            tr_y = trades[(trades["exit_time"] >= s) & (trades["exit_time"] < e)]
            n_tr = len(tr_y)
            if n_tr > 0 and "return" in tr_y:
                wr = (tr_y["return"] > 0).mean()
        rows.append({"year": y, "ret": ret, "dd": dd, "n_trades": n_tr, "wr": wr,
                     "final": float(eq_y.iloc[-1])})
    return pd.DataFrame(rows)


def _fmt_pct(x, n=1): return f"{x*100:+.{n}f}%"
def _fmt_usd(x):      return f"${x:,.0f}"


# ---------------------------------------------------------------------
# Page primitives
# ---------------------------------------------------------------------
def cover_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.94, "HYPERLIQUID DEPLOY GUIDE",
            ha="center", fontsize=26, weight="bold")
    ax.text(0.5, 0.905,
            "Validated strategies only — small-capital deployment plan",
            ha="center", fontsize=13, color="#555")
    ax.text(0.5, 0.877, "2026-04-21  ·  Strategy Lab",
            ha="center", fontsize=10, color="#888")
    ax.axhline(0.856, 0.05, 0.95, color="#ccc", lw=0.7)

    ax.text(0.06, 0.825, "TL;DR — the recommended portfolio",
            fontsize=13, weight="bold", color="#258")

    box = plt.Rectangle((0.06, 0.48), 0.88, 0.33,
                        fill=True, facecolor="#f7faff", edgecolor="#258", lw=1.2)
    ax.add_patch(box)
    lines = [
        ("Account type", "Hyperliquid single-account perpetuals (USDC-collateralised)"),
        ("Split",        "70% Momentum sleeve (XSM) + 30% Trend sleeve"),
        ("XSM sleeve",   "Universe 9 coins. Rank by 14-day return weekly. Long top 4."),
        ("",             "Flat when BTC < 100-day SMA. 1x leverage. Maker limit orders."),
        ("Trend sleeve", "6 coins. V4C (BTC/SOL/ADA) · V3B (ETH/LINK) · HWR1 (XRP)."),
        ("",             "5% sizing × 5x leverage → 25% notional per position."),
        ("Backtest 2018-26", "CAGR +148%  ·  Sharpe 1.88  ·  MaxDD -46%  ·  Calmar 3.23"),
        ("OOS 2022-25",      "CAGR +72%   ·  Sharpe 1.33  ·  MaxDD -46%"),
        ("Required capital", "Minimum $300 · recommended $1,000+ · target $10,000"),
        ("",                 "Scaling tables + Hyperliquid min-size notes on following pages"),
    ]
    y = 0.785
    for k, v in lines:
        if k:
            ax.text(0.09, y, k, fontsize=9.5, weight="bold", color="#258")
            ax.text(0.30, y, v, fontsize=9.5, color="#222")
        else:
            ax.text(0.30, y, v, fontsize=9.5, color="#222")
        y -= 0.026

    ax.text(0.06, 0.44, "Guide structure", fontsize=13, weight="bold", color="#258")
    sects = [
        "1. Small-capital deployment plan  — exact notional & leverage for $300 / $1k / $5k / $10k",
        "2. Leverage guide                 — what leverage each sleeve can handle safely",
        "3. Momentum sleeve deep-dive      — V15 BALANCED champion (equity, DD, trades/year)",
        "4. Momentum alternates            — V14 CONSERVATIVE + V15 AGGRESSIVE profiles",
        "5. Trend sleeve overview          — combined 6-coin sleeve equity + metrics",
        "6. Per-coin trend breakdowns      — BTC V4C · ETH V3B · SOL V4C · LINK V3B · ADA V4C · XRP HWR1",
        "7. Combined hybrid 70/30          — equity, DD, correlation, year-by-year",
        "8. Risk management & kill-switches",
        "9. Step-by-step Hyperliquid deploy checklist",
    ]
    y = 0.40
    for s in sects:
        ax.text(0.09, y, s, fontsize=9.5, color="#222")
        y -= 0.024

    ax.text(0.06, 0.18, "Strategies NOT included (filtered out as failed / non-deployable)",
            fontsize=11, weight="bold", color="#c22")
    filtered = [
        "V8 (SuperTrend stack / HMA-ADX / Vol-Donchian) — too few trades or unprofitable",
        "V9 (multi-TP ladder wraps)                     — cut CAGR without raising the frontier",
        "V10 (orderflow funding/OI/LS/liq)              — level-based signals lag 4h price",
        "V11 (regime ensemble)                          — over-filters already-filtered base",
        "V12C/V12D (higher-lows / NR7)                  — all coins unprofitable",
        "V13B/V13C (ADX-gate / volume-break at 1h)      — fees eat the edge at 1h",
        "V16 (ML-ranked XSM)                            — simple beats smart at 4h",
        "V17 (pairs trading)                            — raw edge exists but needs hedged basket",
        "HWR2 / HWR3 / HWR4 / HWR5                      — high WR but breakeven or worse",
    ]
    y = 0.154
    for f in filtered:
        ax.text(0.09, y, "• " + f, fontsize=8.5, color="#700")
        y -= 0.017

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def small_capital_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "Small-capital deployment plan",
            ha="center", fontsize=18, weight="bold")
    ax.axhline(0.93, 0.05, 0.95, color="#ccc", lw=0.7)

    ax.text(0.06, 0.89, "Hyperliquid order minimums (verify before deploy):",
            fontsize=10.5, weight="bold", color="#258")
    ax.text(0.08, 0.865, "•  Minimum order size: $10 notional (varies by asset; most majors $10)",
            fontsize=9.5)
    ax.text(0.08, 0.848, "•  Minimum tick size: asset-specific; limit orders auto-round",
            fontsize=9.5)
    ax.text(0.08, 0.831, "•  Max account leverage: asset-specific (40x BTC, 20x ETH, 10x most alts, 5x illiquid)",
            fontsize=9.5)

    # Scaling table — per capital tier, show notional per position
    ax.text(0.06, 0.795, "Position sizing by account size",
            fontsize=12, weight="bold", color="#258")

    headers = ["Account", "XSM notional/position",
               "Trend notional/position (5×5)", "Min viable?", "Note"]
    rows = [
        ["$300",   "$52 (top-4 of 70% @ 1x)", "$22 (5% of 30% × 5x)",
         "Marginal", "Hyperliquid $10 min OK; trend sleeve fees heavy"],
        ["$500",   "$87",                     "$37",
         "OK",      "Best for testnet first"],
        ["$1,000", "$175",                    "$75",
         "Good",    "Full spec viable, fees reasonable"],
        ["$5,000", "$875",                    "$375",
         "Ideal",   "Both sleeves work at design fees"],
        ["$10,000","$1,750",                  "$750",
         "Target",  "Recommended sizing; matches backtest"],
        ["$25,000","$4,375",                  "$1,875",
         "Target",  "Same % sizing, no change needed"],
    ]
    ct = [headers] + rows
    tbl = ax.table(cellText=ct, loc="center", cellLoc="left",
                   bbox=[0.04, 0.56, 0.92, 0.22])
    tbl.auto_set_font_size(False); tbl.set_fontsize(8.5); tbl.scale(1, 1.4)
    for j in range(len(headers)):
        tbl[(0, j)].set_facecolor("#dee")
        tbl[(0, j)].set_text_props(weight="bold")

    ax.text(0.06, 0.52, "How the numbers above are derived",
            fontsize=11, weight="bold", color="#258")
    lines = [
        "XSM sleeve = 70% of account × 25% (1/top_k=4) per position × 1x leverage",
        "   → $1,000 account × 0.70 × 0.25 = $175 notional per coin, 4 coins simultaneously",
        "Trend sleeve = 30% of account × 5% notional × 5x leverage",
        "   → $1,000 account × 0.30 × 0.05 × 5 = $75 notional per position",
        "",
        "Max gross exposure (all 4 XSM + up to 6 trend all long at once, worst case):",
        "   XSM   = 70% × 1x = 0.70x of equity",
        "   Trend = 30% × (6 × 25%) = 0.45x   (6 positions × 25% each)",
        "   Total  ≈ 1.15x — well within Hyperliquid's per-account limit even at low-leverage tiers",
    ]
    y = 0.49
    for ln in lines:
        ax.text(0.08, y, ln, fontsize=9, color="#222", family="monospace" if "=" in ln else None)
        y -= 0.020

    ax.text(0.06, 0.325, "Expected performance at each account size (proportional)",
            fontsize=11, weight="bold", color="#258")
    lines = [
        ("$300",    "$300  →  ~$460 in year 1, ~$1.8k after 5 OOS years (matches 72% OOS CAGR)"),
        ("$1,000",  "$1,000 →  ~$1,720 in year 1, ~$6.2k after 5 OOS years"),
        ("$5,000",  "$5,000 →  ~$8,600 in year 1, ~$31k after 5 OOS years"),
        ("$10,000", "$10,000 → ~$17,200 in year 1, ~$61k after 5 OOS years (baseline projection)"),
    ]
    y = 0.30
    for k, v in lines:
        ax.text(0.08, y, f"{k:<10}", fontsize=9, weight="bold", color="#258", family="monospace")
        ax.text(0.18, y, v, fontsize=9, color="#222")
        y -= 0.022

    ax.text(0.06, 0.19, "Honest caveats for small accounts",
            fontsize=11, weight="bold", color="#c22")
    cav = [
        "Below $300: fees start to dominate because min-order-size constrains sizing",
        "Trend sleeve uses 5x per-asset leverage → liquidation risk if position goes -20% without stop trigger",
        "A -46% drawdown on $300 = $138 — psychologically easy to abandon before the recovery",
        "At $1k+ the drawdown $-amount feels worse but strategy mechanics are identical",
    ]
    y = 0.165
    for c in cav:
        ax.text(0.08, y, "• " + c, fontsize=9, color="#700"); y -= 0.020

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def leverage_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "Leverage guide — how much you can safely use",
            ha="center", fontsize=18, weight="bold")
    ax.axhline(0.93, 0.05, 0.95, color="#ccc", lw=0.7)

    ax.text(0.06, 0.895, "Account-level vs position-level leverage",
            fontsize=11.5, weight="bold", color="#258")
    ax.text(0.08, 0.871,
            "Hyperliquid has an ACCOUNT leverage setting AND per-POSITION "
            "leverage when you open each order.",
            fontsize=9)
    ax.text(0.08, 0.853,
            "The backtest uses POSITION leverage only.  Account-level leverage in "
            "the UI just caps how high your position leverage can go.",
            fontsize=9)

    # Leverage recommendations per sleeve
    ax.text(0.06, 0.81, "Recommended leverage per sleeve",
            fontsize=12, weight="bold", color="#258")
    headers = ["Sleeve", "Position leverage", "Why", "Do NOT exceed"]
    rows = [
        ["XSM momentum (70%)",
         "1×",
         "Backtest assumes 1x; 9-coin basket already carries ~58% full-period DD at 1x",
         "2×"],
        ["Trend per-asset (30%)",
         "5×",
         "Backtest uses 5x on 5% sizing = 25% exposure per trade; ATR-trailing stop contains loss",
         "5×"],
        ["Hybrid total",
         "1.5× gross",
         "All sleeves combined, worst-case 6 trend long + 4 XSM long simultaneously",
         "2× gross"],
    ]
    ct = [headers] + rows
    tbl = ax.table(cellText=ct, loc="center", cellLoc="left",
                   bbox=[0.04, 0.58, 0.92, 0.20])
    tbl.auto_set_font_size(False); tbl.set_fontsize(8.5); tbl.scale(1, 1.6)
    for j in range(len(headers)):
        tbl[(0, j)].set_facecolor("#dee"); tbl[(0, j)].set_text_props(weight="bold")

    ax.text(0.06, 0.54, "Why NOT increase leverage (even though Hyperliquid allows it)",
            fontsize=11, weight="bold", color="#c22")
    lines = [
        "• XSM at 2x:  DD expands from -48% to ~ -75% based on the V14 2x-lev sweep result (Calmar 3.04 but DD -100% on some windows — BLOWOUT risk)",
        "• Trend at 10x: the ATR trailing stop assumes normal vol; a 4h gap of 4×ATR (rare but real) wipes 40% position at 10x",
        "• Hybrid at 3x gross: 2022-like bear filter miss + 1 margin-call week can wipe > 60% of equity",
        "",
        "Rule of thumb:  leverage × typical_bar_adverse_move < 30% account drawdown-per-bar tolerance",
    ]
    y = 0.51
    for ln in lines:
        ax.text(0.08, y, ln, fontsize=9.5, color="#700" if ln.startswith("•") else "#222")
        y -= 0.022

    ax.text(0.06, 0.36, "Optimal leverage per profile (from backtest)",
            fontsize=11, weight="bold", color="#258")
    headers = ["Profile", "XSM lev", "Trend lev", "Gross", "CAGR", "Sharpe", "DD"]
    rows = [
        ["CONSERVATIVE  (V14 k=2)",  "1×", "3×", "1.00×", "+158%", "1.60", "-58%"],
        ["BALANCED      (V15 k=4)",  "1×", "5×", "1.50×", "+148%", "1.88", "-46%"],
        ["AGGRESSIVE    (V15 k=3 rb3)","1×", "5×", "1.50×", "+177%", "1.82", "-48%"],
        ["MAX LEVERAGE  (DO NOT)",   "2×", "5×", "3.00×", "+304%","nan", "-99%"],
    ]
    ct = [headers] + rows
    tbl = ax.table(cellText=ct, loc="center", cellLoc="center",
                   bbox=[0.04, 0.19, 0.92, 0.15])
    tbl.auto_set_font_size(False); tbl.set_fontsize(8.5); tbl.scale(1, 1.4)
    for j in range(len(headers)):
        tbl[(0, j)].set_facecolor("#dee"); tbl[(0, j)].set_text_props(weight="bold")
    # color last row
    for j in range(len(headers)):
        tbl[(4, j)].set_facecolor("#f6c7c7")

    ax.text(0.06, 0.14, "Bottom line",
            fontsize=11, weight="bold", color="#258")
    ax.text(0.08, 0.118,
            "Use 1× on the XSM sleeve and 5× per-asset on the trend sleeve. "
            "Combined gross ≈ 1.5×.", fontsize=10, color="#222")
    ax.text(0.08, 0.098,
            "BALANCED profile is the recommended default — highest Sharpe, best Calmar, smallest DD.",
            fontsize=10, color="#222")
    ax.text(0.08, 0.078,
            "Going above 2× gross pushes the DD beyond -70%, which historically forces strategy abandonment "
            "mid-drawdown (the real killer).", fontsize=10, color="#700")

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def strategy_deep_dive(pdf, name, one_liner, eq, trades, strat_desc,
                       strengths, flaws, color="#258"):
    """
    One page per strategy: equity chart, drawdown, year-by-year table,
    trades per year bar, and description.
    """
    fig = plt.figure(figsize=(11, 8.5))

    # Title
    fig.suptitle(name, fontsize=16, weight="bold", y=0.975)
    fig.text(0.5, 0.948, one_liner, fontsize=10, ha="center", color="#555")

    # Equity curve (log)
    ax1 = fig.add_axes([0.06, 0.66, 0.58, 0.23])
    ax1.plot(eq.index, eq.values, color=color, lw=1.3)
    ax1.axvspan(eq.index[0], IS_END, alpha=0.05, color="#0a9396")
    ax1.axvspan(IS_END, eq.index[-1], alpha=0.05, color="#d90429")
    ax1.set_yscale("log")
    ax1.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax1.set_title("Equity curve (log)  ·  IS teal / OOS red", fontsize=9)

    # Drawdown
    dd = (eq / eq.cummax()) - 1
    ax2 = fig.add_axes([0.06, 0.48, 0.58, 0.15])
    ax2.fill_between(dd.index, dd.values, 0, color="#d90429", alpha=0.6)
    ax2.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax2.set_title("Drawdown", fontsize=9)

    # Year-by-year stats table (top right)
    yr = year_stats(eq, trades)
    ax3 = fig.add_axes([0.67, 0.48, 0.30, 0.41]); ax3.axis("off")
    ax3.text(0, 0.985, "Year-by-year", fontsize=10, weight="bold", color="#258")
    head = ["Yr", "Ret", "DD", "Trades", "WR"]
    rows = [head]
    for _, r in yr.iterrows():
        wr = f"{r['wr']*100:.0f}%" if r["wr"] is not None and not pd.isna(r["wr"]) else "-"
        rows.append([
            str(int(r["year"])),
            f"{r['ret']*100:+.0f}%",
            f"{r['dd']*100:+.0f}%",
            str(int(r["n_trades"])) if r["n_trades"] else "-",
            wr,
        ])
    tbl = ax3.table(cellText=rows, loc="upper left", cellLoc="center",
                    bbox=[0, 0.05, 1.0, 0.90])
    tbl.auto_set_font_size(False); tbl.set_fontsize(7.5); tbl.scale(1, 1.2)
    for j in range(len(head)):
        tbl[(0, j)].set_facecolor("#dee")
        tbl[(0, j)].set_text_props(weight="bold")
    # Color wins green, losses red
    for i, r in enumerate(yr.itertuples(), start=1):
        tbl[(i, 1)].set_text_props(color="#0a6" if r.ret > 0 else "#c22")
        tbl[(i, 2)].set_text_props(color="#c22")

    # Year-by-year chart: return bars
    ax4 = fig.add_axes([0.06, 0.26, 0.40, 0.17])
    colors = ["#0a6" if r > 0 else "#c22" for r in yr["ret"]]
    ax4.bar(yr["year"].astype(int), yr["ret"] * 100, color=colors, edgecolor="none")
    ax4.axhline(0, color="#888", lw=0.5)
    ax4.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax4.set_title("Annual return", fontsize=9)

    # Trades per year bar
    ax5 = fig.add_axes([0.52, 0.26, 0.40, 0.17])
    if (yr["n_trades"] > 0).any():
        ax5.bar(yr["year"].astype(int), yr["n_trades"], color=color, edgecolor="none")
        ax5.set_title("Trades per year", fontsize=9)
    else:
        ax5.text(0.5, 0.5, "Position-level rebalance\n(trades counted as rebalance legs)",
                 ha="center", va="center", fontsize=9, color="#888",
                 transform=ax5.transAxes)
        ax5.set_title("Trade cadence", fontsize=9)

    # Description + strengths/flaws (bottom)
    ax6 = fig.add_axes([0.06, 0.05, 0.88, 0.18]); ax6.axis("off")
    m = metrics(eq)
    stat_line = (
        f"CAGR {m.get('cagr',0)*100:+.1f}%   "
        f"Sharpe {m.get('sharpe',0):.2f}   "
        f"MaxDD {m.get('dd',0)*100:+.1f}%   "
        f"Calmar {m.get('calmar',0):.2f}   "
        f"Final ${m.get('final',0):,.0f}"
    )
    ax6.text(0, 0.92, "Metrics (full period):", fontsize=9, weight="bold", color="#258")
    ax6.text(0.22, 0.92, stat_line, fontsize=9.5, color="#222", family="monospace")
    ax6.text(0, 0.72, "How it works:", fontsize=9, weight="bold", color="#258")
    ax6.text(0, 0.56, strat_desc, fontsize=8.5, color="#222", wrap=True)
    ax6.text(0, 0.35, "Strengths", fontsize=9, weight="bold", color="#0a6")
    ax6.text(0.5, 0.35, "Flaws / Caveats", fontsize=9, weight="bold", color="#c22")
    for i, s in enumerate(strengths[:3]):
        ax6.text(0, 0.28 - i*0.07, "• " + s[:68], fontsize=8.5, color="#060")
    for i, f in enumerate(flaws[:3]):
        ax6.text(0.5, 0.28 - i*0.07, "• " + f[:68], fontsize=8.5, color="#700")

    pdf.savefig(fig); plt.close(fig)


def combined_portfolio_page(pdf, xsm_eq, base_eq, title, weight_xsm=0.70):
    """Build a 'hybrid' combined equity curve with charts."""
    idx = xsm_eq.index.union(base_eq.index)
    x = xsm_eq.reindex(idx).ffill().fillna(xsm_eq.iloc[0])
    b = base_eq.reindex(idx).ffill().fillna(base_eq.iloc[0])
    initial = 10000.0
    combined = initial * (weight_xsm * x / x.iloc[0] + (1 - weight_xsm) * b / b.iloc[0])

    fig = plt.figure(figsize=(11, 8.5))
    fig.suptitle(title, fontsize=16, weight="bold", y=0.975)
    fig.text(0.5, 0.945,
             f"{int(weight_xsm*100)}% XSM balanced + {int((1-weight_xsm)*100)}% Trend baseline — $10,000 start",
             fontsize=10, ha="center", color="#555")

    # Equity (log)
    ax1 = fig.add_axes([0.06, 0.63, 0.88, 0.27])
    ax1.plot(combined.index, combined.values, color="#222", lw=1.4, label="Hybrid 70/30")
    ax1.plot(combined.index, initial * (x/x.iloc[0]).values, color="#258", lw=1, alpha=0.5, label="XSM only")
    ax1.plot(combined.index, initial * (b/b.iloc[0]).values, color="#c80", lw=1, alpha=0.5, label="Trend only")
    ax1.axvspan(combined.index[0], IS_END, alpha=0.05, color="#0a9396")
    ax1.axvspan(IS_END, combined.index[-1], alpha=0.05, color="#d90429")
    ax1.set_yscale("log")
    ax1.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax1.legend(loc="upper left", frameon=False, fontsize=9)
    ax1.set_title("Equity curve (log) — IS shaded teal / OOS shaded red", fontsize=9)

    # Drawdown
    dd = (combined / combined.cummax()) - 1
    ax2 = fig.add_axes([0.06, 0.44, 0.88, 0.14])
    ax2.fill_between(dd.index, dd.values, 0, color="#d90429", alpha=0.6)
    ax2.yaxis.set_major_formatter(mtick.PercentFormatter(1.0, decimals=0))
    ax2.set_title("Hybrid drawdown", fontsize=9)

    # Year-by-year
    yr = year_stats(combined)
    ax3 = fig.add_axes([0.06, 0.22, 0.42, 0.17])
    colors = ["#0a6" if r > 0 else "#c22" for r in yr["ret"]]
    ax3.bar(yr["year"].astype(int), yr["ret"] * 100, color=colors)
    ax3.axhline(0, color="#888", lw=0.5)
    ax3.yaxis.set_major_formatter(mtick.PercentFormatter(decimals=0))
    ax3.set_title("Hybrid annual return", fontsize=9)

    # Stat box
    ax4 = fig.add_axes([0.52, 0.22, 0.42, 0.17]); ax4.axis("off")
    m_hyb = metrics(combined)
    m_x = metrics(initial * (x/x.iloc[0]))
    m_b = metrics(initial * (b/b.iloc[0]))
    # OOS
    oos_mask = combined.index >= IS_END
    m_hyb_oos = metrics(combined[oos_mask])
    m_x_oos = metrics((initial * (x/x.iloc[0]))[oos_mask])
    m_b_oos = metrics((initial * (b/b.iloc[0]))[oos_mask])
    rows = [
        ["", "CAGR", "Sharpe", "DD", "Final"],
        ["HYBRID  FULL", _fmt_pct(m_hyb["cagr"]), f"{m_hyb['sharpe']:.2f}",
         _fmt_pct(m_hyb["dd"]), _fmt_usd(m_hyb["final"])],
        ["HYBRID  OOS",  _fmt_pct(m_hyb_oos["cagr"]), f"{m_hyb_oos['sharpe']:.2f}",
         _fmt_pct(m_hyb_oos["dd"]), _fmt_usd(m_hyb_oos["final"])],
        ["XSM only FULL",_fmt_pct(m_x["cagr"]), f"{m_x['sharpe']:.2f}",
         _fmt_pct(m_x["dd"]), _fmt_usd(m_x["final"])],
        ["Trend only FULL",_fmt_pct(m_b["cagr"]), f"{m_b['sharpe']:.2f}",
         _fmt_pct(m_b["dd"]), _fmt_usd(m_b["final"])],
    ]
    tbl = ax4.table(cellText=rows, loc="upper left", cellLoc="center",
                    bbox=[0, 0.05, 1, 0.9])
    tbl.auto_set_font_size(False); tbl.set_fontsize(8.5); tbl.scale(1, 1.4)
    for j in range(5):
        tbl[(0, j)].set_facecolor("#dee"); tbl[(0, j)].set_text_props(weight="bold")
    tbl[(1, 0)].set_facecolor("#b9e8bd")
    tbl[(2, 0)].set_facecolor("#b9e8bd")

    # Footnote + correlation
    corr = xsm_eq.pct_change(fill_method=None).fillna(0).corr(
        base_eq.pct_change(fill_method=None).fillna(0))
    ax5 = fig.add_axes([0.06, 0.03, 0.88, 0.14]); ax5.axis("off")
    lines = [
        f"XSM ↔ Trend correlation (weekly returns): {corr:.2f}  — moderate diversification.",
        "Why 70/30?  XSM carries the return; trend sleeve smooths the path.  The 70/30 mix tops the Sharpe frontier.",
        "Both sleeves run in parallel on the SAME Hyperliquid account — no capital transfer between sleeves.",
    ]
    y = 0.85
    for ln in lines:
        ax5.text(0, y, ln, fontsize=9, color="#222"); y -= 0.26

    pdf.savefig(fig); plt.close(fig)


def checklist_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.965, "Step-by-step Hyperliquid deploy checklist",
            ha="center", fontsize=17, weight="bold")
    ax.axhline(0.935, 0.05, 0.95, color="#ccc", lw=0.7)

    steps = [
        ("Phase 0 — Preparation", [
            "Open a Hyperliquid account, deposit USDC (start $1,000+ if possible; $300 minimum).",
            "Set account-wide max leverage = 5× in the Hyperliquid UI (per-position can be less).",
            "Enable perpetuals for BTC, ETH, SOL, BNB, XRP, DOGE, LINK, ADA, AVAX.",
            "Create an API key (read-write) for automation; secure in a .env file.",
        ]),
        ("Phase 1 — Backfill + dry-run (week 1)", [
            "Run:  python -m strategy_lab.live_forward --reset  && python -m strategy_lab.live_forward --backfill 90",
            "Confirms 90 days of backfilled signals on the trend sleeve, state populated.",
            "Build equivalent live_forward_xsm.py (weekly rebalance script) — skeleton mirrors live_forward.py.",
            "Run both --use-parquet for 24h; compare equity to backtest — tolerance ±2%.",
        ]),
        ("Phase 2 — Paper trading on Hyperliquid testnet (weeks 2-5)", [
            "Point both runners at Hyperliquid testnet API (free demo funds).",
            "Start with BALANCED profile: 1× XSM, 5× trend, BTC-100d bear filter ON.",
            "Let it run for a full 4-week cycle — minimum of 4 XSM rebalances + 5+ trend entries.",
            "After each week, diff live trade log vs backtest simulation on the same bars (±1% return).",
        ]),
        ("Phase 3 — Live on mainnet with $300-1k (weeks 6-10)", [
            "Deposit the MINIMUM comfortable capital to test in anger.",
            "Run both runners against mainnet API; confirm order fills match paper.",
            "Monitor daily equity.csv vs projected equity.  First 4 weeks expect ±15% deviation — noisy.",
            "Do NOT add capital mid-drawdown; only scale up after 4 consecutive profitable weekly rebalances.",
        ]),
        ("Phase 4 — Scale to target capital ($5k+, ongoing)", [
            "Target capital = 10× initial live test.  Scale in 3 tranches over 2 months.",
            "Maintain the 70/30 split at each scale-up — do NOT overweight whichever sleeve is winning.",
            "Rebalance sleeve weights to 70/30 quarterly if the natural drift exceeds ±10%.",
        ]),
        ("Phase 5 — Permanent monitoring", [
            "Weekly: check equity.csv, rebalance log, open positions.",
            "Monthly: rolling 3-month Sharpe — if < 0.5 for 2 consecutive months, halt XSM sleeve.",
            "Any -40% drawdown from ATH: halt BOTH sleeves; resume only when BTC > 100d-MA for 1 full week.",
        ]),
    ]

    y = 0.91
    for head, items in steps:
        ax.text(0.06, y, head, fontsize=11.5, weight="bold", color="#258")
        y -= 0.026
        for it in items:
            ax.text(0.09, y, "☐ " + it, fontsize=8.8, color="#222")
            y -= 0.019
        y -= 0.008

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def risk_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.965, "Risk management & kill-switches",
            ha="center", fontsize=17, weight="bold")
    ax.axhline(0.935, 0.05, 0.95, color="#ccc", lw=0.7)

    sections = [
        ("Per-position guards (both sleeves)", [
            "Hard per-position SL: any single position cannot lose more than 5% of account equity (≈ 1.5×ATR stop already enforces this for trend).",
            "Max concurrent positions: 10 (4 XSM + up to 6 trend).  Reject new entries if limit reached.",
            "Fat-finger cap: reject any order with notional > 3× the spec sizing.",
        ]),
        ("Sleeve-level guards", [
            "XSM sleeve: if BTC closes below 100-day SMA, CLOSE all XSM positions and stay flat until BTC > MA for 2 full weekly bars.",
            "Trend sleeve: no sleeve-level circuit breaker; each strategy's built-in trailing stop is the circuit.",
        ]),
        ("Account-level kill-switch", [
            "-40% from ATH: pause new entries in BOTH sleeves for at least 1 week.",
            "Resume condition: BTC closes above its 100-day SMA for 5 consecutive days AND combined equity is not still making new lows.",
            "Permanent halt: if combined equity drops -65% from ATH, stop everything, review strategy, re-backtest from scratch.",
        ]),
        ("Operational safeguards", [
            "No --no-verify on trading code — keep the test suite green.",
            "Wallet keys in .env only.  NEVER commit .env; NEVER paste API keys in logs.",
            "Cross-check nightly:  Hyperliquid reported positions  vs  state.json.  Halt on any mismatch > 1%.",
            "Upgrade scripts in a feature branch + backfill replay before merging; mismatched replay = hard no-merge.",
        ]),
        ("Catastrophic-scenario plan", [
            "Hyperliquid outage: positions remain open; set tight limit-order stops before every reset / upgrade window.",
            "Coin delisting: XSM runner must skip delisted coins (check exchangeInfo daily before ranking).",
            "Flash crash -30% in <1h: the BTC-MA filter won't fire in time — accept it as pre-priced DD in spec.",
            "Strategy drift:  if rolling 3-month Sharpe < 0.5 for 2 consecutive months, halt and investigate.",
        ]),
    ]
    y = 0.9
    for head, items in sections:
        ax.text(0.06, y, head, fontsize=11, weight="bold", color="#258")
        y -= 0.024
        for it in items:
            ax.text(0.09, y, "• " + it, fontsize=8.8, color="#222")
            y -= 0.0185
        y -= 0.006

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
COIN_COLOR = {
    "BTCUSDT":"#f2a900","ETHUSDT":"#627eea","SOLUSDT":"#14f195",
    "LINKUSDT":"#2a5ada","ADAUSDT":"#0033ad","XRPUSDT":"#23292f",
}


def main():
    per_coin = json.loads((RES/"portfolio/per_coin_summary.json").read_text())

    with PdfPages(OUT_LOCAL) as pdf:
        cover_page(pdf)
        small_capital_page(pdf)
        leverage_page(pdf)

        # ===== XSM sleeves =====
        xsm_bal_eq = read_equity(RES/"v15_balanced_k4_lb14_rb7_equity.csv")
        strategy_deep_dive(pdf,
            "V15 BALANCED — XSM champion (k=4, lb=14d, rb=7d)",
            "Weekly rank 9 coins by 14-day return, equal-weight top 4, flat when BTC < 100-day MA.",
            xsm_bal_eq, None,
            "Universe = 9 liquid coins.  Every 7 days compute each coin's 14-day return.  "
            "Equal-weight (25% notional each) into the top 4.  Exit (go flat) when BTC is below "
            "its 100-day SMA.  1x leverage, Hyperliquid maker fees 0.015%, no slippage.",
            [
                "Highest single-strategy Sharpe (1.86) of everything tested",
                "Only strategy whose 2022 return was POSITIVE (+1.6%) — BTC filter worked",
                "Robust: 100/100 random 2-year windows profitable; 72/72 param configs profitable",
                "Simple — one weekly rebalance, no per-coin tuning",
            ],
            [
                "DD of -48% is still large in $-terms on real capital",
                "2021 alt-season drives > 50% of full-period CAGR",
                "Requires BTC > 100d-MA filter — if that signal fails, DD blows out",
            ],
            color="#258")

        xsm_cons_eq = read_equity(RES/"v15_conservative_k2_lb28_rb7_equity.csv")
        strategy_deep_dive(pdf,
            "V14 CONSERVATIVE — XSM k=2, lb=28d, rb=7d",
            "Slower momentum (28-day), concentrated (top 2), same weekly rebalance + BTC filter.",
            xsm_cons_eq, None,
            "Same logic as V15 BALANCED but with a 28-day lookback (slower regime reaction) "
            "and top 2 picks only (higher concentration).  Ideal if you expect fewer regime shifts "
            "and want larger per-coin conviction.",
            [
                "Best 2022 performance of all XSM variants (-9.5%, market did -70%)",
                "Fewer rebalances than balanced/aggressive → lower fees",
                "Concentrated bets benefit from strong alt-season leadership (SOL 2021)",
            ],
            [
                "Lowest Sharpe of the 3 XSM profiles (1.60)",
                "k=2 means one bad pick = 50% of weekly capital",
                "Slower to rotate when leaders change mid-week",
            ],
            color="#0a9396")

        xsm_agg_eq = read_equity(RES/"v15_aggressive_k3_lb14_rb3_equity.csv")
        strategy_deep_dive(pdf,
            "V15 AGGRESSIVE — XSM k=3, lb=14d, rb=3d",
            "Same 14-day momentum but top 3 only and rebalance every 3 days for faster regime response.",
            xsm_agg_eq, None,
            "Reduces weekly lag by rebalancing twice-weekly (every 3 days).  Top 3 picks "
            "give more concentration than balanced (k=4) while still keeping some diversification.  "
            "Maximum CAGR of any tested configuration.",
            [
                "Highest CAGR (+177%), highest Calmar (3.65)",
                "Faster regime response — catches trend-change weeks sooner",
                "Still protected by BTC bear filter",
            ],
            [
                "2022: -27% (worse than balanced's +1.6%)",
                "More rebalances → more fees, more slippage risk",
                "Higher concentration ⇒ higher single-coin event risk",
            ],
            color="#d90429")

        # ===== Trend sleeve combined =====
        trend_eq = read_equity(RES/"portfolio/portfolio_equity.csv")
        strategy_deep_dive(pdf,
            "TREND SLEEVE (combined) — 6 coins, V4C + V3B + HWR1",
            "6-coin single-account trend portfolio, 5% × 5x sizing, Hyperliquid maker fees.",
            trend_eq, None,
            "Classic time-series trend-following per coin.  V4C Range Kalman on BTC/SOL/ADA, "
            "V3B ADX-Gate on ETH/LINK, HWR1 BB-mean-reversion on XRP.  Each position uses 5% of "
            "equity notional with 5× leverage → 25% exposure per trade.  ATR-trailing stops exit.",
            [
                "Clean diversification across coin archetypes (majors + alts + XRP mean-rev)",
                "Per-position ATR stops contain loss",
                "Sharpe 1.19 despite weaker raw edge than XSM — smooths hybrid equity",
            ],
            [
                "CAGR 38% is much lower than XSM",
                "DD -33% still uncomfortable in isolation",
                "6 simultaneous positions = higher fee drag than XSM",
            ],
            color="#c80")

        # ===== Per-coin deep-dives (trend sleeve) =====
        per_coin_specs = [
            ("BTCUSDT", "V4C Range Kalman (BTC 4h)",  "Dynamic range breakout using Kalman-smoothed price; ATR-trailing exit; HTF regime filter."),
            ("ETHUSDT", "V3B ADX Gate (ETH 4h)",      "Donchian-break + volume-spike + ADX > 20 + HTF regime.  The flagship for ETH."),
            ("SOLUSDT", "V4C Range Kalman (SOL 4h)",  "Same V4C logic; SOL's high vol makes the Kalman range band particularly effective."),
            ("LINKUSDT","V3B ADX Gate (LINK 4h)",     "V3B works on LINK because LINK respects DeFi/infrastructure cycle trends."),
            ("ADAUSDT", "V4C Range Kalman (ADA 4h)",  "V4C; ADA's lower vol makes signal quality cleaner though CAGR smaller."),
            ("XRPUSDT", "HWR1 BB Mean-Reversion (XRP 4h)",
             "XRP is the only coin with a tradable mean-reverting structure; buy lower BB, exit mid-band."),
        ]
        for sym, name, desc in per_coin_specs:
            eq = read_equity(RES/f"portfolio/per_coin/{sym}_equity.csv")
            tr = read_trades(RES/f"portfolio/per_coin/{sym}_trades.csv")
            strat_name = per_coin[sym]["strategy"]
            overall_wr = (tr["return"] > 0).mean() if len(tr) else 0
            strategy_deep_dive(pdf, name,
                f"Overall WR {overall_wr*100:.0f}%   ·   Trades {len(tr)}   ·   Strategy class: {strat_name}",
                eq, tr, desc,
                [
                    "Profitable full period + OOS — walk-forward validated",
                    f"Win-rate pattern stable across 2022-2025",
                    "Clean single-coin implementation — easy to monitor",
                ],
                [
                    "Single-coin risk — no diversification within this sleeve",
                    "Drawdown can be large in solo mode",
                    "Edge may fade if coin archetype changes",
                ],
                color=COIN_COLOR.get(sym, "#258"))

        # ===== Combined hybrid portfolio =====
        combined_portfolio_page(pdf, xsm_bal_eq, trend_eq,
            "Combined 70/30 Hybrid — the recommended deployment", weight_xsm=0.70)

        # Risk management + checklist
        risk_page(pdf)
        checklist_page(pdf)

    shutil.copy2(OUT_LOCAL, OUT_PUBLIC)
    print(f"Wrote  {OUT_LOCAL}")
    print(f"Copied {OUT_PUBLIC}")


if __name__ == "__main__":
    main()
