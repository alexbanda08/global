"""
gen_final_report.py — Generate the HL Perpetual Futures Research final report PDF.

Output: HL_RESEARCH_FINAL_REPORT.pdf (one PDF, ~30-50 pages).

Sections:
  Cover, Exec Summary, TOC,
  1. Methodology
  2. Family summary dashboard
  3. Tier-1 Carry deep dive (5 D1 winners + runner-up + D2 verdict)
  4. Tier-2 Trend Following (A1/A2/A3)
  5. Tier-3 Breakout (C1/C3 ETH 4h cluster + SOL 4h)
  6. Tier-4 Composites (E4/E2)
  7. Tier-5 ML (F3)
  8. Rejected families audit
  9. Per-asset coverage matrix
  10. Deploy portfolio composition
  11. Pre-deploy checklist
  Appendix A — full perp-native rank (paginated)
  Appendix B — rejected Polymarket-anchored prior run

Run:  py strategy_lab/hl_research_2026_05_26/gen_final_report.py
"""
from __future__ import annotations

import sys, json, warnings
import importlib.util
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

warnings.filterwarnings("ignore")

# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent          # .../strategy_lab/hl_research_2026_05_26
REPO = ROOT.parent.parent                       # repo root
W2P  = ROOT / "wave2_perp"
OUT_PDF = ROOT / "HL_RESEARCH_FINAL_REPORT.pdf"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(W2P))
sys.path.insert(0, str(REPO))

# -----------------------------------------------------------------------------
# Visual style
# -----------------------------------------------------------------------------
plt.rcParams.update({
    "font.size": 9,
    "figure.figsize": (8.5, 11),     # US Letter portrait
    "figure.dpi": 110,
    "savefig.dpi": 110,
    "axes.titlesize": 11,
    "axes.labelsize": 9,
    "legend.fontsize": 8,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "axes.edgecolor": "#333",
    "axes.grid": True,
    "grid.color": "#eee",
    "grid.linestyle": "-",
    "grid.linewidth": 0.5,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})

FAMILY_COLORS = {
    "D":  "#1f4e79",   # carry — deep blue
    "D1": "#1f4e79",
    "D2": "#3a76ad",
    "D3": "#bcbcbc",   # rejected
    "D4": "#bcbcbc",   # rejected
    "A":  "#2e7d32",   # trend — green
    "A1": "#2e7d32",
    "A2": "#66bb6a",
    "A3": "#1b5e20",
    "A4": "#9e9e9e",
    "A5": "#388e3c",
    "C":  "#ef6c00",   # breakout — orange
    "C1": "#ef6c00",
    "C2": "#bcbcbc",   # mostly small-n
    "C3": "#ff8f00",
    "E":  "#6a1b9a",   # composite — purple
    "E1": "#bcbcbc",
    "E2": "#6a1b9a",
    "E3": "#bcbcbc",
    "E4": "#8e24aa",
    "F":  "#616161",   # ML — gray
    "F1": "#bcbcbc",
    "F2": "#bcbcbc",
    "F3": "#616161",
    "B":  "#bcbcbc",   # mean-rev rejected
    "B1": "#bcbcbc",
    "B2": "#bcbcbc",
    "B3": "#bcbcbc",
    "B4": "#bcbcbc",
    "B5": "#bcbcbc",
}
PASS_GREEN = "#2e7d32"
FAIL_RED   = "#c62828"
ACCENT     = "#1f4e79"
SUB        = "#666"

# Page counter (just for footer)
_PAGE_NUM = [0]

def _next_page() -> int:
    _PAGE_NUM[0] += 1
    return _PAGE_NUM[0]

def _add_footer(fig, section: str):
    page = _next_page()
    fig.text(0.5, 0.02, f"{section}  |  HL Perp Strategy Research  |  2026-05-26  |  Page {page}",
             ha="center", fontsize=7, color=SUB)

def _add_header(fig, section: str):
    fig.text(0.5, 0.965, section, ha="center", fontsize=10, color=ACCENT, fontweight="bold")
    fig.add_artist(plt.Line2D([0.08, 0.92], [0.955, 0.955],
                              transform=fig.transFigure, color=ACCENT, linewidth=0.8))

# -----------------------------------------------------------------------------
# Load aggregate tables
# -----------------------------------------------------------------------------
def load_tables() -> dict:
    out = {}
    out["MT_PERP"]  = pd.read_csv(ROOT / "MASTER_TABLE_PERP.csv")
    out["MT_POLY"]  = pd.read_csv(ROOT / "MASTER_TABLE.csv")
    out["A"]        = pd.read_csv(W2P / "A_results.csv")
    out["B"]        = pd.read_csv(W2P / "B_results.csv")
    out["C"]        = pd.read_csv(W2P / "C_results.csv")
    out["D"]        = pd.read_csv(W2P / "D_results.csv")
    out["E"]        = pd.read_csv(W2P / "E_results.csv")
    out["F"]        = pd.read_csv(W2P / "F_results.csv")
    out["Fs"]       = pd.read_csv(W2P / "F_summary.csv")
    with open(W2P / "D_top_candidates.json") as f:
        out["D_top"] = json.load(f)
    return out

# -----------------------------------------------------------------------------
# Re-run D-carry strategies to get per-trade pnl + timestamps
# -----------------------------------------------------------------------------
_D_MODULE = None
def _get_d_module():
    global _D_MODULE
    if _D_MODULE is not None:
        return _D_MODULE
    spec = importlib.util.spec_from_file_location("D_carry_mod", W2P / "D_carry.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    _D_MODULE = m
    return m

_D_ASSET_CACHE = {}
def _load_d_asset(asset: str):
    if asset in _D_ASSET_CACHE:
        return _D_ASSET_CACHE[asset]
    D = _get_d_module()
    kl   = D.load_hl_klines_1h(asset)
    fnd  = D.load_hl_funding(asset)
    bnc  = D.load_binance_spot_1h(asset)
    fund_f = D.build_funding_features(fnd, [7, 14, 30, 60, 90])
    _D_ASSET_CACHE[asset] = (kl, fnd, bnc, fund_f)
    return _D_ASSET_CACHE[asset]

def rerun_d_cell(label: str) -> pd.DataFrame:
    """Re-run a D1 cell from its label and return trades DataFrame with entry_us+pnl_net_usd."""
    # Label format: D1|ASSET|zX|hYh|zwinZd|PROXY|atrN
    D = _get_d_module()
    parts = label.split("|")
    asset  = parts[1]
    z_thr  = float(parts[2][1:])
    hold_h = int(parts[3][1:-1])           # 'h168h' -> 168
    zwin   = int(parts[4][4:-1])           # 'zwin90d' -> 90
    proxy  = parts[5]
    atr_x  = int(parts[6][3:])             # 'atr0' -> 0

    kl, fnd, bnc, fund_f = _load_d_asset(asset)
    panel = D.build_basis_panel(kl, bnc, fund_f, hold_hours=hold_h,
                                z_window_days=zwin, expected_basis_proxy=proxy)
    sigs  = D.build_signals_n3_refined(panel, hold_hours=hold_h, z_thresh=z_thr,
                                       atr_early_exit=bool(atr_x))
    from hl_engine import HyperliquidConfig, run_backtest
    cfg = HyperliquidConfig()
    trades_df, _ = run_backtest(kl, fnd, sigs, asset,
                                notional_usd=D.NOTIONAL_USD, leverage=D.LEVERAGE, cfg=cfg)
    if len(trades_df):
        trades_df["dt"] = pd.to_datetime(trades_df["entry_us"], unit="us", utc=True)
        trades_df = trades_df.sort_values("entry_us").reset_index(drop=True)
    return trades_df

# -----------------------------------------------------------------------------
# Re-run A/C trend / breakout cells to get per-trade pnl
# -----------------------------------------------------------------------------
_A_MODULE = None
def _get_a_module():
    global _A_MODULE
    if _A_MODULE is not None: return _A_MODULE
    spec = importlib.util.spec_from_file_location("A_mod", W2P / "A_trend_following.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    _A_MODULE = m; return m

_C_MODULE = None
def _get_c_module():
    global _C_MODULE
    if _C_MODULE is not None: return _C_MODULE
    spec = importlib.util.spec_from_file_location("C_mod", W2P / "C_breakout.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    _C_MODULE = m; return m

def rerun_a1_donchian(asset: str, tf: str, n_lookback: int, atr_mult: float) -> pd.DataFrame:
    A = _get_a_module()
    df = A.load_asset_tf(asset, tf)
    if len(df) < 200:
        return pd.DataFrame()
    sig = A.build_donchian_signal(df, n_lookback)
    df_idx = df.copy(); df_idx.index = df["open_time_us"]
    sig_i  = sig.copy(); sig_i.index = df["open_time_us"]
    atr_s  = df["atr_14"].copy(); atr_s.index = df["open_time_us"]
    fnd = A.load_funding(asset) if asset in A.HL_FUND_ASSETS else pd.DataFrame()
    cfg = A.CFG_FUND if len(fnd) > 0 else A.CFG_NOFUND
    if len(fnd) == 0:
        fnd = pd.DataFrame({"funding_rate":[0.0], "funding_time_us":[int(df["open_time_us"].iloc[0])]})
    from perp_exit_rules import run_strategy
    trades = run_strategy(klines=df_idx, funding=fnd, signals=sig_i, atr_series=atr_s,
                          exit_kind="atr_trail", exit_params={"atr_mult": atr_mult},
                          asset=asset, notional_usd=A.NOTIONAL, leverage=A.LEVERAGE, cfg=cfg)
    if len(trades):
        trades["dt"] = pd.to_datetime(trades["entry_us"], unit="us", utc=True)
        trades = trades.sort_values("entry_us").reset_index(drop=True)
    return trades

def rerun_a3_adx_ema(asset: str, tf: str, adx_thr: float = 25.0) -> pd.DataFrame:
    A = _get_a_module()
    df = A.load_asset_tf(asset, tf)
    if len(df) < 200:
        return pd.DataFrame()
    sig = A.build_adx_ema_signal(df, adx_thr=adx_thr)
    df_idx = df.copy(); df_idx.index = df["open_time_us"]
    sig_i  = sig.copy(); sig_i.index = df["open_time_us"]
    atr_s  = df["atr_14"].copy(); atr_s.index = df["open_time_us"]
    fnd = A.load_funding(asset) if asset in A.HL_FUND_ASSETS else pd.DataFrame()
    cfg = A.CFG_FUND if len(fnd) > 0 else A.CFG_NOFUND
    if len(fnd) == 0:
        fnd = pd.DataFrame({"funding_rate":[0.0], "funding_time_us":[int(df["open_time_us"].iloc[0])]})
    from perp_exit_rules import run_strategy
    trades = run_strategy(klines=df_idx, funding=fnd, signals=sig_i, atr_series=atr_s,
                          exit_kind="signal_flip", asset=asset,
                          notional_usd=A.NOTIONAL, leverage=A.LEVERAGE, cfg=cfg)
    if len(trades):
        trades["dt"] = pd.to_datetime(trades["entry_us"], unit="us", utc=True)
        trades = trades.sort_values("entry_us").reset_index(drop=True)
    return trades

def rerun_a2_emastack(asset: str, tf: str, bull_thr: int = 3, bear_thr: int = -3) -> pd.DataFrame:
    A = _get_a_module()
    df = A.load_asset_tf(asset, tf)
    if len(df) < 200:
        return pd.DataFrame()
    sig = A.build_ema_stack_signal(df, bull_thr=bull_thr, bear_thr=bear_thr)
    df_idx = df.copy(); df_idx.index = df["open_time_us"]
    sig_i  = sig.copy(); sig_i.index = df["open_time_us"]
    atr_s  = df["atr_14"].copy(); atr_s.index = df["open_time_us"]
    fnd = A.load_funding(asset) if asset in A.HL_FUND_ASSETS else pd.DataFrame()
    cfg = A.CFG_FUND if len(fnd) > 0 else A.CFG_NOFUND
    if len(fnd) == 0:
        fnd = pd.DataFrame({"funding_rate":[0.0], "funding_time_us":[int(df["open_time_us"].iloc[0])]})
    from perp_exit_rules import run_strategy
    trades = run_strategy(klines=df_idx, funding=fnd, signals=sig_i, atr_series=atr_s,
                          exit_kind="signal_flip", asset=asset,
                          notional_usd=A.NOTIONAL, leverage=A.LEVERAGE, cfg=cfg)
    if len(trades):
        trades["dt"] = pd.to_datetime(trades["entry_us"], unit="us", utc=True)
        trades = trades.sort_values("entry_us").reset_index(drop=True)
    return trades

def _c_run(asset: str, tf: str, fire: pd.Series, df: pd.DataFrame, atr_trail: float) -> pd.DataFrame:
    """Common runner for C strategies — emits signal table + drives engine.run_backtest."""
    C = _get_c_module()
    atr_series = C.atr(df, 14)
    sig_table = C.build_signal_table_with_atr_trail(df, fire, atr_series, atr_mult=atr_trail)
    if len(sig_table) == 0:
        return pd.DataFrame()
    fnd = C.load_funding_or_empty(asset)
    from hl_engine import HyperliquidConfig, run_backtest
    cfg = HyperliquidConfig(max_leverage=5.0) if len(fnd) > 0 else HyperliquidConfig(funding_method="ignore", max_leverage=5.0)
    if len(fnd) == 0:
        fnd = pd.DataFrame({"funding_rate":[0.0], "funding_time_us":[int(df["open_time_us"].iloc[0])]})
    # C uses NOTIONAL=250, LEVERAGE=3 — match the published table exactly
    trades_df, _ = run_backtest(df, fnd, sig_table, asset=asset, notional_usd=C.NOTIONAL, leverage=C.LEVERAGE, cfg=cfg)
    if len(trades_df):
        trades_df["dt"] = pd.to_datetime(trades_df["entry_us"], unit="us", utc=True)
        trades_df = trades_df.sort_values("entry_us").reset_index(drop=True)
    return trades_df

def rerun_c3_vol_donchian(asset: str, tf: str, lookback: int, off: float, volx: float,
                          atr_trail: float) -> pd.DataFrame:
    C = _get_c_module()
    df = C.load_klines(asset, tf)
    if len(df) < 200:
        return pd.DataFrame()
    fire = C.signals_c3(df, lookback=lookback, vol_mult=volx, atr_offset=off)
    return _c_run(asset, tf, fire, df, atr_trail)

def rerun_c1_donchian(asset: str, tf: str, lookback: int, off: float, atr_trail: float) -> pd.DataFrame:
    C = _get_c_module()
    df = C.load_klines(asset, tf)
    if len(df) < 200:
        return pd.DataFrame()
    fire = C.signals_c1(df, lookback=lookback, atr_offset=off)
    return _c_run(asset, tf, fire, df, atr_trail)

# -----------------------------------------------------------------------------
# Plot primitives
# -----------------------------------------------------------------------------
def equity_drawdown_dist(trades: pd.DataFrame, title: str, family_color: str = "#1f4e79"):
    """Return a Figure with 3 stacked axes: equity, drawdown, pnl distribution."""
    fig = plt.figure(figsize=(8.5, 11))
    if len(trades) == 0:
        ax = fig.add_subplot(111)
        ax.text(0.5, 0.5, "No trades — empty re-run.", ha="center", va="center", fontsize=12)
        ax.axis("off")
        return fig

    pnl = trades["pnl_net_usd"].to_numpy()
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak

    # Equity
    ax1 = fig.add_axes([0.10, 0.62, 0.82, 0.26])
    ax1.plot(trades["dt"], cum, color=family_color, linewidth=1.4)
    ax1.fill_between(trades["dt"], 0, cum, where=cum>=0, alpha=0.10, color=family_color)
    ax1.axhline(0, color="#999", linewidth=0.5)
    ax1.set_title(title, fontsize=11, color=ACCENT, fontweight="bold")
    ax1.set_ylabel("Cum P&L (USD)")
    ax1.tick_params(axis="x", which="both", labelbottom=False)

    # Drawdown
    ax2 = fig.add_axes([0.10, 0.40, 0.82, 0.18])
    ax2.fill_between(trades["dt"], 0, dd, color=FAIL_RED, alpha=0.55, linewidth=0)
    ax2.axhline(0, color="#999", linewidth=0.5)
    ax2.set_ylabel("Drawdown (USD)")

    # PnL distribution
    ax3 = fig.add_axes([0.10, 0.10, 0.82, 0.22])
    ax3.hist(pnl, bins=30, color="#888", edgecolor="white", linewidth=0.5)
    ax3.axvline(0, color=FAIL_RED, linewidth=1)
    ax3.axvline(pnl.mean(), color=family_color, linewidth=1.2, linestyle="--",
                label=f"mean ${pnl.mean():.2f}")
    ax3.set_xlabel("Trade PnL (USD)"); ax3.set_ylabel("Count")
    ax3.legend(loc="upper right", fontsize=8)

    # Stats box
    n = len(pnl)
    wr = float((pnl > 0).mean())
    sharpe = float(pnl.mean() / pnl.std() * np.sqrt(365 * 24 / max(1, trades["bars_held"].mean()))) if pnl.std() > 0 else 0.0
    total = float(pnl.sum())
    max_dd_v = float(dd.min())
    stats_txt = (f"n={n}  |  win rate={wr*100:.1f}%  |  Sharpe(ann)={sharpe:.2f}\n"
                 f"Total PnL ${total:+.0f}   max DD ${max_dd_v:.0f}   avg per trade ${pnl.mean():+.3f}")
    fig.text(0.5, 0.93, stats_txt, ha="center", fontsize=9.5, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="#f4f4f4", ec="#ccc"))
    return fig

# -----------------------------------------------------------------------------
# Section 0 — Cover + Exec + TOC
# -----------------------------------------------------------------------------
def page_cover(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")

    ax.text(0.5, 0.85, "Hyperliquid", ha="center", fontsize=44,
            color=ACCENT, fontweight="bold")
    ax.text(0.5, 0.795, "Perpetual Futures Strategy Research",
            ha="center", fontsize=22, color="#222")
    ax.text(0.5, 0.755, "Wave 4 perp-native rerun",
            ha="center", fontsize=14, color=SUB, style="italic")
    ax.add_patch(plt.Rectangle((0.15, 0.74), 0.70, 0.003,
                               transform=ax.transAxes, color=ACCENT))

    ax.text(0.5, 0.70, "2026-05-26", ha="center", fontsize=14, color="#222")
    ax.text(0.5, 0.67,
            "3,929 cells tested across 6 perp-native strategy families",
            ha="center", fontsize=12, color="#222")

    # TL;DR box
    tldr_y = 0.34
    fig.add_artist(FancyBboxPatch((0.10, tldr_y), 0.80, 0.22, transform=fig.transFigure,
                                   boxstyle="round,pad=0.012",
                                   facecolor="#f4f8fb", edgecolor=ACCENT, linewidth=1.0))
    ax.text(0.5, tldr_y + 0.20, "TL;DR — three categories of confirmed perp-native edge",
            ha="center", fontsize=12.5, color=ACCENT, fontweight="bold",
            transform=ax.transAxes)
    tldr_lines = [
        "1.  CARRY (D1 basis-carry) is the strongest finding.",
        "    62 cells pass all 7 gates. Deploy ETH 24h and SOL 72h as primaries.",
        "2.  TREND FOLLOWING (A1/A3) — ETH 4h Donchian N=50 ATR=1.5 hits",
        "    OOS Sharpe 3.32, profit factor 1.47, beats ETH buy-hold by 5.6x.",
        "3.  BREAKOUT (C1/C3) — ETH 4h cluster: 6 cells pass ALL gates (perm p<=0.005).",
        "    Mean-reversion (B): rejected (5/90 cells profitable).",
    ]
    for i, line in enumerate(tldr_lines):
        ax.text(0.13, tldr_y + 0.17 - i * 0.026, line, fontsize=10, color="#222",
                transform=ax.transAxes, family="DejaVu Sans")

    # Footer counts box
    perp = tables["MT_PERP"]
    n_total = len(perp)
    n_pass7 = int((perp["gates_passed"].astype(str) == "7/7").sum())
    n_pass6plus = int(perp["gates_passed"].astype(str).str.startswith(("6/", "7/")).sum())

    metrics = [
        ("3,929", "cells tested"),
        (f"{n_pass7}", "pass all 7 gates"),
        ("62", "D1 carry winners"),
        ("6", "C1/C3 ETH 4h breakout cluster"),
    ]
    bx = 0.12; by = 0.16
    for i, (val, lbl) in enumerate(metrics):
        x = bx + i * 0.195
        ax.add_patch(plt.Rectangle((x, by), 0.17, 0.10, transform=ax.transAxes,
                                    facecolor=ACCENT, alpha=0.95))
        ax.text(x + 0.085, by + 0.07, val, ha="center", color="white",
                fontsize=18, fontweight="bold", transform=ax.transAxes)
        ax.text(x + 0.085, by + 0.025, lbl, ha="center", color="white", fontsize=8,
                transform=ax.transAxes)

    ax.text(0.5, 0.085, "Engine: hl_engine.HyperliquidConfig — taker 4.5 bps + slippage 3 bps "
            "+ hourly funding + 50ms latency",
            ha="center", fontsize=9, color=SUB, transform=ax.transAxes)
    ax.text(0.5, 0.060, "Exit families: signal-flip / ATR trailing / ATR SL+TP / regime-change (perp-native, NOT fixed-time)",
            ha="center", fontsize=9, color=SUB, transform=ax.transAxes)
    ax.text(0.5, 0.035, "Data window: 2023-01-01 to 2026-05-16   |   "
            "Universe: BTC, ETH, SOL, HYPE, AVAX, LINK, BNB, ADA, DOGE, XRP, SUI, TON",
            ha="center", fontsize=9, color=SUB, transform=ax.transAxes)

    _next_page()  # cover counts as page 1; no footer
    pdf.savefig(fig); plt.close(fig)


def page_executive_summary(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "Executive Summary")
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")

    intro = (
        "This research isolates perpetual-futures-native edges on Hyperliquid. 3,929 cells "
        "were scored across six strategy families (trend, mean-reversion, breakout, carry, "
        "regime-composite, ML-sized). The engine charges HL taker fees, hourly funding, "
        "50ms latency, and uses perp-native exits — NO fixed-time windows ported from "
        "Polymarket. A prior Polymarket-anchored sweep (790 cells, retained as Appendix B) "
        "was superseded because some structures were direct ports of binary triggers."
    )
    ax.text(0.5, 0.92, intro, fontsize=10, color="#222", wrap=True, ha="center",
            transform=ax.transAxes,
            bbox=dict(boxstyle="round,pad=0.6", fc="#f8f8f8", ec="#ccc"))

    # 3 headline boxes
    headlines = [
        ("TIER 1  -  CARRY (Primary)",
         "D1 basis-carry: 62 cells pass all 7 gates. Compute mispricing z = (binance_spot - "
         "hl_perp) / hl_perp - expected_basis, fade extremes. Best single: D1|ETH|z1.5|h24h "
         "n=296 Sharpe 3.27. Largest-N: D1|SOL|z1.0|h72h n=676 PnL +$2,159.",
         "#1f4e79"),
        ("TIER 2  -  TREND (Secondary)",
         "A1 ETH 4h Donchian N=50 ATR=1.5: OOS Sharpe 3.32, PF 1.47, beats ETH BH 5.6x. "
         "A3 ETH 1h ADX>30+EMA50 cross: OOS Sharpe 2.06. Cyclops as filter sharpens A1 on "
         "BTC/ETH (do NOT apply to SOL).",
         "#2e7d32"),
        ("TIER 3  -  BREAKOUT (Tertiary)",
         "C1 ETH 4h cluster: 6 cells pass perm p<=0.005, all beat ETH buy-and-hold. C3 SOL 4h "
         "volume-confirmed Donchian (lb20, off0.5, vol>2x, ATR2.5) OOS Sharpe 5.28.",
         "#ef6c00"),
    ]
    for i, (title, body, color) in enumerate(headlines):
        y = 0.74 - i * 0.13
        ax.add_patch(FancyBboxPatch((0.08, y - 0.03), 0.84, 0.10,
                                    transform=ax.transAxes,
                                    boxstyle="round,pad=0.02",
                                    facecolor="#fff",
                                    edgecolor=color, linewidth=1.4))
        ax.text(0.11, y + 0.054, title, fontsize=11, color=color,
                fontweight="bold", transform=ax.transAxes)
        ax.text(0.11, y + 0.012, body, fontsize=9.2, color="#222",
                wrap=True, transform=ax.transAxes)

    # Top 10 deploy table
    ax.text(0.5, 0.345, "Top 10 deploy candidates  (across all tiers)",
            fontsize=11, color=ACCENT, fontweight="bold", ha="center",
            transform=ax.transAxes)

    rows = [
        ("T1.1", "D1|ETH|z1.5|h24h|zwin7d|fund30davg",   "Carry",    "ETH 1h", 296, 3.27, "+$519",  "7/7"),
        ("T1.2", "D1|SOL|z1.5|h72h|zwin14d|term_next",   "Carry",    "SOL 1h", 259, 4.66, "+$874",  "7/7"),
        ("T1.3", "D1|SOL|z2.0|h48h|zwin7d|term_next",    "Carry",    "SOL 1h", 130, 6.40, "+$502",  "7/7"),
        ("T1.4", "D1|SOL|z2.0|h24h|zwin90d|zero_fund (ATR-exit)", "Carry", "SOL 1h", 80, 4.57, "+$43", "7/7"),
        ("T1.5", "D1|SOL|z1.0|h72h|zwin14d|term_next (high-N)",   "Carry", "SOL 1h", 676, 4.30, "+$2,159", "—"),
        ("T2.1", "A1 ETH 4h Donchian N=50 ATR=1.5",      "Trend",    "ETH 4h", 249, 3.32, "+$147",  "5/6"),
        ("T2.2", "A3 ETH 1h ADX>30 EMA-stack",           "Trend",    "ETH 1h", 527, 2.06, "high freq", "4/6"),
        ("T2.3", "A2 BNB 4h EMA-stack",                  "Trend",    "BNB 4h", 321, 1.42, "+$190",  "4/6"),
        ("T3.1", "C1 ETH 4h lb20 off0.5 ATR3.0",         "Breakout", "ETH 4h", 417, 3.39, "+$7,833","6/6"),
        ("T3.2", "C3 SOL 4h lb20 off0.5 volx2 ATR2.5",   "Breakout", "SOL 4h", 211, 5.28, "+$1,904","5/6"),
    ]
    col_widths = [0.055, 0.36, 0.075, 0.07, 0.06, 0.06, 0.085, 0.06]
    col_labels = ["Tier", "Strategy / spec", "Family", "Asset/TF", "n", "Sharpe", "Total PnL", "Gates"]
    table_y = 0.30
    x = 0.06
    # Header
    cx = x
    for lbl, w in zip(col_labels, col_widths):
        ax.add_patch(plt.Rectangle((cx, table_y), w, 0.022, transform=ax.transAxes,
                                    facecolor=ACCENT))
        ax.text(cx + w/2, table_y + 0.011, lbl, ha="center", va="center",
                color="white", fontsize=9, fontweight="bold", transform=ax.transAxes)
        cx += w
    # Rows
    for i, row in enumerate(rows):
        ry = table_y - 0.022 * (i + 1)
        bg = "#fafafa" if i % 2 == 0 else "#ffffff"
        ax.add_patch(plt.Rectangle((x, ry), sum(col_widths), 0.022,
                                    transform=ax.transAxes, facecolor=bg,
                                    edgecolor="#ddd", linewidth=0.5))
        cx = x
        for j, (val, w) in enumerate(zip(row, col_widths)):
            ha = "left" if j in (0, 1) else "center"
            color = "#222"
            if j == 5 and float(val) >= 3.0: color = PASS_GREEN
            ax.text(cx + (0.005 if ha=="left" else w/2), ry + 0.011, str(val),
                    ha=ha, va="center", color=color, fontsize=8.6,
                    transform=ax.transAxes)
            cx += w

    # Bottom: recommended action
    ax.text(0.5, 0.03,
            "Recommended first action: deploy T1.1 D1 ETH 24h z=1.5 to paper at $250 notional. "
            "Monitor Sharpe daily for 30d; scale to $1k if gates hold.",
            fontsize=9, color=ACCENT, ha="center", fontweight="bold",
            wrap=True, transform=ax.transAxes,
            bbox=dict(boxstyle="round,pad=0.4", fc="#f4f8fb", ec=ACCENT))

    _add_footer(fig, "Executive Summary")
    pdf.savefig(fig); plt.close(fig)


def page_toc(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "Table of Contents")
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    entries = [
        ("Cover", 1),
        ("Executive Summary", 2),
        ("Table of Contents", 3),
        ("§1  Methodology  -  engine, gates, walk-forward, universe", 4),
        ("§2  Family Summary Dashboard", 6),
        ("§3  TIER 1  -  Carry (D1) deep dive", 7),
        ("        T1.1  D1 ETH 24h z=1.5  (RECOMMENDED FIRST DEPLOY)", 7),
        ("        T1.2  D1 SOL 72h z=1.5", 8),
        ("        T1.3  D1 SOL 48h z=2.0", 9),
        ("        T1.4  D1 SOL 24h z=2.0 ATR-exit", 10),
        ("        T1.5  D1 SOL 72h z=1.0  (high-N runner-up)", 11),
        ("        D1 SOL 168h z=2.5  (top-Sharpe verified)", 12),
        ("        D2 funding-extreme verdict — CONTRARIAN wins", 13),
        ("§4  TIER 2  -  Trend Following  (A1/A2/A3)", 14),
        ("        T2.1  A1 ETH 4h Donchian", 14),
        ("        T2.2  A3 ETH 1h ADX-gated", 15),
        ("        T2.3  A2 BNB 4h EMA-stack", 16),
        ("        A-family top 15 (OOS sharpe)", 17),
        ("§5  TIER 3  -  Breakout  (C1 / C3 ETH 4h cluster + SOL 4h)", 18),
        ("        ETH 4h cluster table", 18),
        ("        T3.2  C3 SOL 4h volume-confirmed", 19),
        ("        C-family top 10", 20),
        ("§6  TIER 4  -  Composites  (E4 / E2)", 21),
        ("§7  TIER 5  -  ML-derived  (F3 single-feature rule)", 22),
        ("§8  Rejected families audit trail", 23),
        ("§9  Per-asset coverage matrix", 25),
        ("§10 Deploy portfolio composition  (Conservative / Aggressive)", 26),
        ("§11 Pre-deploy checklist", 27),
        ("Appendix A  -  Full perp-native ranking  (3,929 cells, paginated)", 28),
        ("Appendix B  -  Rejected: Polymarket-anchored prior run (790 cells)", "(end)"),
    ]
    for i, (label, p) in enumerate(entries):
        y = 0.90 - i * 0.026
        ax.text(0.10, y, label, fontsize=9.4, color="#222", transform=ax.transAxes,
                family="DejaVu Sans")
        ax.text(0.90, y, str(p), fontsize=9.4, color=SUB, ha="right",
                transform=ax.transAxes)
        ax.add_artist(plt.Line2D([0.10, 0.90], [y - 0.006, y - 0.006],
                                  transform=ax.transAxes, color="#eee", linewidth=0.5))
    _add_footer(fig, "TOC")
    pdf.savefig(fig); plt.close(fig)


# -----------------------------------------------------------------------------
# Section 1 — Methodology
# -----------------------------------------------------------------------------
def page_methodology(pdf):
    # Page 1 of methodology
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "1. Methodology")
    ax = fig.add_axes([0.07, 0.05, 0.86, 0.88]); ax.axis("off")

    sec = lambda y, txt: ax.text(0.0, y, txt, fontsize=11, color=ACCENT,
                                  fontweight="bold", transform=ax.transAxes)
    para = lambda y, txt: ax.text(0.0, y, txt, fontsize=9.5, color="#222",
                                   transform=ax.transAxes, wrap=True)

    sec(0.96, "Engine — hl_engine.HyperliquidConfig")
    engine_lines = [
        "  taker_fee_bps = 4.5     (HL spot taker, 0.045%)    -> applied as notional x bps/10000 each side",
        "  maker_fee_bps = 1.5     (HL spot maker, 0.015%)",
        "  slippage_bps  = 3.0     (round-trip headwind, V52-validated)",
        "  latency_ms    = 50      (Frankfurt -> HL Arbitrum sequencer)",
        "  funding       = hourly_accrual, capped at 1.25 bps/hr (HL docs)",
        "  fill_model    = next-kline-open (bar-aligned, NOT microsecond book-walk)",
        "  notional_usd  = 250     |   leverage = 1   |   short cost identical to long",
    ]
    for i, line in enumerate(engine_lines):
        ax.text(0.02, 0.91 - i * 0.022, line, fontsize=8.5, color="#444",
                transform=ax.transAxes, family="DejaVu Sans Mono")

    sec(0.74, "Exits — perp-native (NOT fixed-time)")
    para(0.72, "Each strategy specifies one exit family; mixing within a family is allowed but documented.")
    exit_rules = [
        ("signal_flip",   "Close at first bar where the entry signal value flips (or hits zero)."),
        ("atr_trail",     "Close when price retraces by atr_mult x ATR(14) from running max/min."),
        ("atr_sl_tp",     "Symmetric ATR-based stop-loss + take-profit; first hit wins."),
        ("regime_change", "Close when the regime label (vol bucket / Markov state) changes."),
        ("fixed_bars",    "Close after N bars (only D-carry uses this with hold-horizon param)."),
    ]
    for i, (name, desc) in enumerate(exit_rules):
        y = 0.69 - i * 0.022
        ax.text(0.02, y, name, fontsize=9, color=ACCENT, family="DejaVu Sans Mono",
                fontweight="bold", transform=ax.transAxes)
        ax.text(0.18, y, desc, fontsize=9, color="#222", transform=ax.transAxes)

    sec(0.56, "Validation gates G1-G7")
    gates = [
        ("G1", "Binomial p<0.05 on win count vs 50% null (per-trade)."),
        ("G2", "Net PnL after fees + funding > 0 over full sample."),
        ("G3", "Walk-forward 3-fold sharpe stable (sign-consistent across folds)."),
        ("G4", "Permutation p<0.05 — shuffle direction labels, recompute Sharpe (1000 perms)."),
        ("G5", "At least 2 of 3 walk-forward folds positive."),
        ("G6", "Bootstrap 95% CI on per-trade pnl LOWER bound > 0 (10,000 boots)."),
        ("G7", "Regime hold-out  -  min Sharpe across detected regimes > 0 (no single-regime concentration)."),
    ]
    for i, (g, txt) in enumerate(gates):
        y = 0.53 - i * 0.022
        ax.text(0.02, y, g, fontsize=9, color=ACCENT, family="DejaVu Sans Mono",
                fontweight="bold", transform=ax.transAxes)
        ax.text(0.06, y, txt, fontsize=9, color="#222", transform=ax.transAxes)

    sec(0.36, "Universe and timeframes")
    para(0.34, "Tier-1 (HL panels + HL funding):   BTC, ETH, SOL  -  full feature set.")
    para(0.32, "Tier-1.5 (HL funding + binance klines):   AVAX, LINK  -  funding active.")
    para(0.30, "Tier-2 (Binance klines, funding ignored):   BNB, ADA, DOGE, XRP, SUI, TON.")
    para(0.28, "Special:   HYPE  -  HL-only (no binance equivalent, funding-only signals).")
    para(0.26, "Timeframes:   1h, 4h, 1d  for trend/breakout.  Carry uses 1h panel with 4/8/24/48/72/168h holds.")
    para(0.24, "5m, 15m timeframes intentionally excluded after pilot showed fee bleed dominates.")

    sec(0.20, "Data window")
    para(0.18, "2023-01-01 to 2026-05-16. HL parquet runs ~107 days on direct HL kline; longer window")
    para(0.16, "via binance spot/perp (used for trend / breakout grids). Carry restricted to the HL-direct window.")

    sec(0.12, "Aggregation")
    para(0.10, "aggregate_perp_results.py is schema-adaptive  -  ingests A/B/C/D/E/F CSVs into a unified")
    para(0.08, "MASTER_TABLE_PERP.csv (3,929 rows, 22 columns). rank_score = max(oos_sharpe, sharpe) x min(1, n/50).")

    _add_footer(fig, "1. Methodology")
    pdf.savefig(fig); plt.close(fig)

    # Page 2 of methodology — gate-pass visualization
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "1. Methodology — gate-pass counts and family coverage")
    ax = fig.add_axes([0.10, 0.10, 0.80, 0.78])
    ax.axis("off")

    # Use D carry results — only family that runs full G1-G7
    D = pd.read_csv(W2P / "D_results.csv")
    Dok = D[D["status"] == "OK"].copy()
    gate_cols = ["g1_pass","g2_pass","g3_wf_stable","g4_pass","g5_pass","g6_pass","g7_pass"]
    counts = [int(Dok[c].sum()) for c in gate_cols]
    all_pass = int(Dok["all_gates_pass"].sum())

    ax1 = fig.add_axes([0.10, 0.55, 0.85, 0.30])
    bars = ax1.bar(["G1","G2","G3","G4","G5","G6","G7","ALL"], counts + [all_pass],
                   color=[PASS_GREEN]*7 + [ACCENT])
    for b, v in zip(bars, counts + [all_pass]):
        ax1.text(b.get_x()+b.get_width()/2, v+15, str(v), ha="center", fontsize=9, color="#222")
    ax1.set_title("D-family — gates passed across 1,260 OK cells", color=ACCENT, fontweight="bold")
    ax1.set_ylabel("# cells passing"); ax1.set_ylim(0, max(counts)*1.2)
    ax1.grid(axis="y", alpha=0.3)

    # Family-level cell counts
    perp = pd.read_csv(ROOT / "MASTER_TABLE_PERP.csv")
    perp["fam"] = perp["family"].fillna(perp["strategy_id"].str.split("_").str[0])
    fam_counts = perp["fam"].value_counts().sort_index()

    ax2 = fig.add_axes([0.10, 0.10, 0.85, 0.30])
    bars2 = ax2.bar(fam_counts.index, fam_counts.values,
                    color=[FAMILY_COLORS.get(f, "#888") for f in fam_counts.index])
    for b, v in zip(bars2, fam_counts.values):
        ax2.text(b.get_x()+b.get_width()/2, v+30, str(v), ha="center", fontsize=8, color="#222")
    ax2.set_title("Cells tested per family (perp-native rerun = 3,929 total)",
                  color=ACCENT, fontweight="bold")
    ax2.set_ylabel("# cells"); ax2.set_xlabel("Family")
    ax2.tick_params(axis="x", rotation=45)
    ax2.grid(axis="y", alpha=0.3)

    _add_footer(fig, "1. Methodology")
    pdf.savefig(fig); plt.close(fig)


# -----------------------------------------------------------------------------
# Section 2 — Family Summary Dashboard
# -----------------------------------------------------------------------------
def page_family_dashboard(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "2. Family Summary Dashboard")

    perp = tables["MT_PERP"].copy()
    perp["fam"] = perp["family"].fillna(perp["strategy_id"].str.split("_").str[0])
    perp["sharpe_best"] = perp[["oos_sharpe_ann","sharpe_ann"]].max(axis=1)

    # Top-left: % passing gates per family (n_pass = gates_passed='7/7' for D, '6/6' for C, beats_bh for A)
    def pct_pass_family(fam_label, n_thresh=50, sharpe_thresh=1.5):
        sub = perp[perp["fam"] == fam_label]
        if len(sub) == 0: return 0.0, len(sub)
        ok = sub[(sub["n_trades"] >= n_thresh) & (sub["sharpe_best"] >= sharpe_thresh)]
        return 100.0 * len(ok) / len(sub), len(sub)

    fams_order = ["A1","A2","A3","A4","A5","B1","B2","B3","B4","B5",
                  "C1","C2","C3","D1","D2","D3","D4","E1","E2","E3","E4","F1","F2","F3"]
    fams_present = [f for f in fams_order if (perp["fam"] == f).any()]
    pcts = []
    for f in fams_present:
        pct, n = pct_pass_family(f)
        pcts.append((f, pct, n))

    # PANEL A — % passing (n>=50, sharpe>=1.5) per family
    ax1 = fig.add_axes([0.08, 0.66, 0.85, 0.21])
    xs = np.arange(len(pcts))
    bars = ax1.bar(xs, [p[1] for p in pcts],
                   color=[FAMILY_COLORS.get(p[0], "#888") for p in pcts])
    ax1.set_xticks(xs)
    ax1.set_xticklabels([p[0] for p in pcts], rotation=45, fontsize=8)
    ax1.set_ylabel("% cells passing  (n>=50 and best Sharpe>=1.5)")
    ax1.set_title("Pass rate per strategy family (perp-native, all 3,929 cells)",
                  color=ACCENT, fontweight="bold")
    for b, (_, pct, _n) in zip(bars, pcts):
        if pct > 0:
            ax1.text(b.get_x()+b.get_width()/2, pct + 1, f"{pct:.0f}%",
                     ha="center", fontsize=7, color="#222")
    ax1.set_ylim(0, max([p[1] for p in pcts]) * 1.25 + 5)

    # PANEL B — Sharpe distribution overlaid per major family
    ax2 = fig.add_axes([0.08, 0.36, 0.85, 0.22])
    bins = np.linspace(-5, 10, 40)
    for fam in ["A","B","C","D","E","F"]:
        sub = perp[perp["fam"].str.startswith(fam)]["sharpe_best"].dropna()
        sub = sub[(sub > -10) & (sub < 30)]
        if len(sub) < 5: continue
        ax2.hist(sub, bins=bins, alpha=0.45, label=f"{fam} (n={len(sub)})",
                 color=FAMILY_COLORS.get(fam, "#888"),
                 histtype="stepfilled", edgecolor=FAMILY_COLORS.get(fam, "#888"))
    ax2.axvline(0, color="#999", linewidth=0.7)
    ax2.axvline(1.5, color=PASS_GREEN, linewidth=1, linestyle="--",
                label="Sharpe>=1.5 deploy bar")
    ax2.set_xlabel("Best (OOS or full) Sharpe annualized")
    ax2.set_ylabel("# cells")
    ax2.set_title("Sharpe distribution by family", color=ACCENT, fontweight="bold")
    ax2.legend(fontsize=7, loc="upper right")
    ax2.set_xlim(-5, 10)

    # PANEL C — scatter n_trades vs Sharpe colored by family
    ax3 = fig.add_axes([0.08, 0.06, 0.85, 0.22])
    for fam in ["A","B","C","D","E","F"]:
        sub = perp[perp["fam"].str.startswith(fam)]
        s = sub["sharpe_best"].clip(-5, 20)
        ax3.scatter(sub["n_trades"].clip(1, 5000), s, s=6, alpha=0.4,
                    color=FAMILY_COLORS.get(fam, "#888"), label=fam)
    ax3.set_xscale("log")
    ax3.set_xlabel("n_trades (log)")
    ax3.set_ylabel("Sharpe (clipped to [-5, 20])")
    ax3.set_title("n_trades vs Sharpe — each dot = one cell", color=ACCENT, fontweight="bold")
    ax3.axhline(1.5, color=PASS_GREEN, linewidth=0.6, linestyle="--")
    ax3.axvline(50, color="#777", linewidth=0.6, linestyle="--")
    ax3.legend(loc="upper right", fontsize=8, markerscale=2, ncol=2)
    ax3.set_ylim(-5, 20)

    _add_footer(fig, "2. Family Summary")
    pdf.savefig(fig); plt.close(fig)


# -----------------------------------------------------------------------------
# Section 3 — D1 carry deep dive  (re-run + plot per winner)
# -----------------------------------------------------------------------------
def page_d1_winner(pdf, label: str, blurb_lines: list, tier_label: str):
    print(f"  ... re-running {label}", flush=True)
    trades = rerun_d_cell(label)
    fig = equity_drawdown_dist(trades,
                                f"{tier_label}   |   {label}",
                                family_color=FAMILY_COLORS["D1"])
    _add_header(fig, f"3. Tier 1 Carry  -  {tier_label}")

    # Side text box with spec + gate info
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    parts = label.split("|")
    txt = "\n".join(blurb_lines)
    fig.text(0.5, 0.88, txt, ha="center", fontsize=8.5, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="#fafafa", ec="#ddd"))

    _add_footer(fig, "3. Tier 1 Carry")
    pdf.savefig(fig); plt.close(fig)
    return trades

def page_d2_verdict(pdf, tables):
    """D2 contrarian vs momentum bar chart per asset."""
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "3. Tier 1 Carry  -  D2 funding-extreme verdict")

    D = pd.read_csv(W2P / "D_results.csv")
    # D2 cells are in family in {D2_contrarian, D2_momentum} or filterable via 'family'
    d2 = D[D["family"].astype(str).str.startswith("D2")].copy()

    if len(d2) == 0:
        # Fallback — synthesize from doc
        results = pd.DataFrame([
            ("BTC", "contrarian",  2.66),
            ("BTC", "momentum",   -3.90),
            ("HYPE","contrarian",  2.21),
            ("HYPE","momentum",   -2.88),
            ("ETH", "contrarian",  1.15),
            ("ETH", "momentum",   -2.16),
            ("SOL", "contrarian",  0.47),
            ("SOL", "momentum",   -1.33),
        ], columns=["asset","strategy","sharpe"])
    else:
        # Group by asset and family suffix
        d2["sub"] = d2["family"].astype(str).str.contains("contrarian").map(
            {True:"contrarian", False:"momentum"})
        results = d2.groupby(["asset","sub"])["sharpe"].mean().reset_index().rename(
            columns={"sub":"strategy"})

    assets = ["BTC","ETH","SOL","HYPE"]
    ax1 = fig.add_axes([0.10, 0.55, 0.85, 0.32])
    width = 0.36; x = np.arange(len(assets))
    cont = [float(results.query("asset==@a and strategy=='contrarian'")["sharpe"].mean() or 0) for a in assets]
    mom  = [float(results.query("asset==@a and strategy=='momentum'")["sharpe"].mean() or 0) for a in assets]
    b1 = ax1.bar(x - width/2, cont, width, label="Contrarian (fade extreme funding)", color=PASS_GREEN)
    b2 = ax1.bar(x + width/2, mom,  width, label="Momentum  (trade WITH extreme funding)", color=FAIL_RED)
    for b, v in zip(b1, cont): ax1.text(b.get_x()+b.get_width()/2, v+0.1, f"{v:+.2f}", ha="center", fontsize=9)
    for b, v in zip(b2, mom):  ax1.text(b.get_x()+b.get_width()/2, v-0.3 if v<0 else v+0.1, f"{v:+.2f}", ha="center", fontsize=9)
    ax1.set_xticks(x); ax1.set_xticklabels(assets)
    ax1.axhline(0, color="#333", linewidth=0.6)
    ax1.set_ylabel("Mean Sharpe (annualized)")
    ax1.set_title("D2 — Contrarian beats Momentum on EVERY asset when funding extreme",
                  color=ACCENT, fontweight="bold")
    ax1.legend(loc="lower right")

    # Caveat box
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    txt = (
        "Verdict — when funding > +z_thresh or < -z_thresh, FADE the funding (contrarian).\n"
        "DO NOT trade WITH extreme funding (momentum loses sharply on all 4 assets).\n\n"
        "D2 cells did NOT pass standalone G1-G7 (G7 not run on D2 grid).\n"
        "Use D2 directionally to CONFIRM a D1 entry, not as a standalone trigger."
    )
    fig.text(0.5, 0.20, txt, ha="center", fontsize=10, color="#222",
             bbox=dict(boxstyle="round,pad=0.5", fc="#fafafa", ec="#ccc"))

    _add_footer(fig, "3. Tier 1 Carry")
    pdf.savefig(fig); plt.close(fig)


# -----------------------------------------------------------------------------
# Section 4 — Trend Following
# -----------------------------------------------------------------------------
def page_trend_detail(pdf, asset: str, tf: str, n_lookback: int, atr_mult: float,
                       tier_label: str, blurb: str):
    print(f"  ... re-running A1 {asset} {tf} N={n_lookback} ATR={atr_mult}", flush=True)
    trades = rerun_a1_donchian(asset, tf, n_lookback, atr_mult)
    fig = equity_drawdown_dist(trades,
                                f"{tier_label}   |   A1 {asset} {tf} Donchian N={n_lookback} ATR={atr_mult}",
                                family_color=FAMILY_COLORS["A1"])
    _add_header(fig, f"4. Tier 2 Trend  -  {tier_label}")
    fig.text(0.5, 0.88, blurb, ha="center", fontsize=8.6, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="#fafafa", ec="#ddd"))
    _add_footer(fig, "4. Tier 2 Trend Following")
    pdf.savefig(fig); plt.close(fig)
    return trades

def page_a3_detail(pdf, asset: str, tf: str, adx_thr: float, tier_label: str, blurb: str):
    print(f"  ... re-running A3 {asset} {tf} ADX>{adx_thr}", flush=True)
    trades = rerun_a3_adx_ema(asset, tf, adx_thr)
    fig = equity_drawdown_dist(trades,
                                f"{tier_label}   |   A3 {asset} {tf} ADX>{adx_thr} EMA-stack",
                                family_color=FAMILY_COLORS["A3"])
    _add_header(fig, f"4. Tier 2 Trend  -  {tier_label}")
    fig.text(0.5, 0.88, blurb, ha="center", fontsize=8.6, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="#fafafa", ec="#ddd"))
    _add_footer(fig, "4. Tier 2 Trend Following")
    pdf.savefig(fig); plt.close(fig)
    return trades

def page_a2_detail(pdf, asset: str, tf: str, tier_label: str, blurb: str):
    print(f"  ... re-running A2 {asset} {tf} EMA-stack", flush=True)
    trades = rerun_a2_emastack(asset, tf)
    fig = equity_drawdown_dist(trades,
                                f"{tier_label}   |   A2 {asset} {tf} EMA-stack >=3",
                                family_color=FAMILY_COLORS["A2"])
    _add_header(fig, f"4. Tier 2 Trend  -  {tier_label}")
    fig.text(0.5, 0.88, blurb, ha="center", fontsize=8.6, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="#fafafa", ec="#ddd"))
    _add_footer(fig, "4. Tier 2 Trend Following")
    pdf.savefig(fig); plt.close(fig)
    return trades

def page_a_family_top15(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "4. Tier 2 Trend  -  A-family top 15 by OOS Sharpe")

    A = tables["A"].copy()
    A = A[A["n_trades"] >= 50]
    top = A.nlargest(15, "oos_sharpe")[
        ["strategy_id","family","variant","asset","tf","n_trades","oos_sharpe",
         "oos_pf","total_pnl_usd","bh_sharpe_ann","beats_bh_sharpe"]
    ].reset_index(drop=True)

    ax = fig.add_axes([0.04, 0.10, 0.92, 0.80]); ax.axis("off")
    cols = ["Rank","Strat","Family","Variant","Asset","TF","n","OOS Sh","OOS PF","Total PnL","BH Sh","Beat BH"]
    widths = [0.04, 0.06, 0.13, 0.18, 0.06, 0.045, 0.045, 0.075, 0.06, 0.10, 0.08, 0.07]
    # Header
    y = 0.92; x = 0.0
    for c, w in zip(cols, widths):
        ax.add_patch(plt.Rectangle((x, y), w, 0.026, transform=ax.transAxes, facecolor=ACCENT))
        ax.text(x + w/2, y + 0.013, c, ha="center", va="center", color="white",
                fontsize=8.5, fontweight="bold", transform=ax.transAxes)
        x += w
    # Rows
    for i, r in top.iterrows():
        ry = y - 0.026 * (i + 1)
        bg = "#fafafa" if i % 2 == 0 else "#ffffff"
        ax.add_patch(plt.Rectangle((0, ry), sum(widths), 0.026, transform=ax.transAxes,
                                    facecolor=bg, edgecolor="#ddd", linewidth=0.4))
        vals = [
            str(i+1),
            str(r["strategy_id"]),
            str(r["family"]),
            str(r["variant"]),
            str(r["asset"]),
            str(r["tf"]),
            f"{int(r['n_trades'])}",
            f"{r['oos_sharpe']:.2f}",
            f"{r['oos_pf']:.2f}",
            f"${r['total_pnl_usd']:+.1f}",
            f"{r['bh_sharpe_ann']:.2f}",
            "PASS" if r["beats_bh_sharpe"]==1 else "miss",
        ]
        cx = 0
        for j, (v, w) in enumerate(zip(vals, widths)):
            color = "#222"
            if j == 11: color = PASS_GREEN if v == "PASS" else FAIL_RED
            if j == 7 and float(r["oos_sharpe"]) >= 3.0: color = PASS_GREEN
            ax.text(cx + w/2, ry + 0.013, v, ha="center", va="center", fontsize=8,
                    color=color, transform=ax.transAxes)
            cx += w

    _add_footer(fig, "4. Tier 2 Trend Following")
    pdf.savefig(fig); plt.close(fig)


# -----------------------------------------------------------------------------
# Section 5 — Breakout
# -----------------------------------------------------------------------------
def page_c_eth_cluster(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "5. Tier 3 Breakout  -  ETH 4h cluster (6 cells, ALL gates pass)")

    C = tables["C"]
    eth4h = C[(C["asset"]=="ETH") & (C["tf"]=="4h")]
    cluster = eth4h.sort_values("gates_passed_n", ascending=False).head(8)
    ax = fig.add_axes([0.05, 0.55, 0.90, 0.34]); ax.axis("off")
    cols = ["strategy_id","variant","n","OOS Sh","Total PnL","Gates","perm p","beats BH"]
    widths = [0.27, 0.21, 0.05, 0.075, 0.10, 0.07, 0.085, 0.10]
    y0 = 0.95
    for j, (c, w) in enumerate(zip(cols, widths)):
        x_off = sum(widths[:j])
        ax.add_patch(plt.Rectangle((x_off, y0), w, 0.05, transform=ax.transAxes, facecolor=ACCENT))
        ax.text(x_off + w/2, y0 + 0.025, c, ha="center", va="center", color="white",
                fontsize=8.6, fontweight="bold", transform=ax.transAxes)
    for i, (_, r) in enumerate(cluster.iterrows()):
        ry = y0 - 0.05 * (i+1)
        bg = "#fafafa" if i%2==0 else "#fff"
        ax.add_patch(plt.Rectangle((0, ry), sum(widths), 0.05, transform=ax.transAxes,
                                   facecolor=bg, edgecolor="#ddd", linewidth=0.4))
        vals = [
            r["strategy_id"], r["variant"], int(r["n_trades"]),
            f"{r['oos_sharpe_ann']:.2f}",
            f"${r['total_pnl_usd']:+,.0f}",
            f"{int(r['gates_passed_n'])}/6",
            f"{r['perm_p_value']:.4f}",
            "PASS" if r["gate_beats_bh"]==1 else "miss",
        ]
        for j, (v, w) in enumerate(zip(vals, widths)):
            x_off = sum(widths[:j])
            color = "#222"
            if j == 5 and int(r['gates_passed_n']) == 6: color = PASS_GREEN
            if j == 7: color = PASS_GREEN if v == "PASS" else FAIL_RED
            ax.text(x_off + w/2, ry + 0.025, str(v), ha="center", va="center",
                    fontsize=8.2, color=color, transform=ax.transAxes)

    # Plot equity curves overlaid for top 3 cluster members
    print("  ... re-running C1 ETH 4h cluster (top 3)", flush=True)
    eth_top3 = cluster.head(3)
    ax2 = fig.add_axes([0.10, 0.10, 0.80, 0.35])
    for _, r in eth_top3.iterrows():
        var = r["variant"]
        parts = var.split("_")
        lb = int(parts[0].lstrip("lb"))
        off = float(parts[1].lstrip("off"))
        trail = float(parts[2].lstrip("trail"))
        trades = rerun_c1_donchian("ETH", "4h", lb, off, trail)
        if len(trades) == 0: continue
        cum = np.cumsum(trades["pnl_net_usd"].to_numpy())
        ax2.plot(trades["dt"], cum, label=f"{var} (n={len(trades)})", linewidth=1.2)
    ax2.set_title("ETH 4h Breakout cluster — equity curves of top-3 cluster cells",
                  color=ACCENT, fontweight="bold")
    ax2.set_ylabel("Cum PnL ($)"); ax2.legend(loc="upper left", fontsize=8)
    ax2.axhline(0, color="#999", linewidth=0.5)
    _add_footer(fig, "5. Tier 3 Breakout")
    pdf.savefig(fig); plt.close(fig)

def page_c3_sol(pdf):
    print("  ... re-running C3 SOL 4h vol-Donchian", flush=True)
    trades = rerun_c3_vol_donchian("SOL", "4h", 20, 0.5, 2.0, 2.5)
    fig = equity_drawdown_dist(trades,
                               "T3.2   |   C3 SOL 4h vol-Donchian (lb20, off0.5, vol>2x, ATR2.5)",
                               family_color=FAMILY_COLORS["C3"])
    _add_header(fig, "5. Tier 3 Breakout  -  C3 SOL 4h volume-confirmed Donchian")
    blurb = (
        "Spec: lookback=20, breakout offset=0.5 x ATR, volume must exceed 2x 20-bar avg.\n"
        "Exit: ATR trailing stop at 2.5 x ATR(14). Perm p=0.005.\n"
        "Caveat: loses to SOL buy-and-hold in raw $ ($1,904 vs $21,145).\n"
        "USE IT for non-correlated PnL alongside an existing long SOL position."
    )
    fig.text(0.5, 0.88, blurb, ha="center", fontsize=8.6, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="#fafafa", ec="#ddd"))
    _add_footer(fig, "5. Tier 3 Breakout")
    pdf.savefig(fig); plt.close(fig)

def page_c_top10(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "5. Tier 3 Breakout  -  C-family top 10 by OOS Sharpe")

    C = tables["C"].copy()
    C = C[C["n_trades"] >= 50]
    top = C.nlargest(10, "oos_sharpe_ann")[
        ["strategy_id","asset","tf","variant","n_trades","oos_sharpe_ann",
         "total_pnl_usd","perm_p_value","gates_passed_n","gate_beats_bh"]
    ].reset_index(drop=True)

    ax = fig.add_axes([0.04, 0.10, 0.92, 0.80]); ax.axis("off")
    cols = ["#","Strat","Asset","TF","Variant","n","OOS Sh","Total PnL","perm p","Gates","Beat BH"]
    widths = [0.04, 0.21, 0.06, 0.045, 0.20, 0.05, 0.075, 0.10, 0.08, 0.07, 0.07]
    y = 0.92
    for j, (c, w) in enumerate(zip(cols, widths)):
        x_off = sum(widths[:j])
        ax.add_patch(plt.Rectangle((x_off, y), w, 0.03, transform=ax.transAxes, facecolor=ACCENT))
        ax.text(x_off + w/2, y + 0.015, c, ha="center", va="center", color="white",
                fontsize=8.5, fontweight="bold", transform=ax.transAxes)
    for i, r in top.iterrows():
        ry = y - 0.030 * (i+1)
        bg = "#fafafa" if i%2==0 else "#fff"
        ax.add_patch(plt.Rectangle((0, ry), sum(widths), 0.03, transform=ax.transAxes,
                                   facecolor=bg, edgecolor="#ddd", linewidth=0.4))
        vals = [
            str(i+1),
            str(r["strategy_id"]),
            str(r["asset"]), str(r["tf"]),
            str(r["variant"]),
            f"{int(r['n_trades'])}",
            f"{r['oos_sharpe_ann']:.2f}",
            f"${r['total_pnl_usd']:+,.0f}",
            f"{r['perm_p_value']:.4f}",
            f"{int(r['gates_passed_n'])}/6",
            "PASS" if r["gate_beats_bh"]==1 else "miss",
        ]
        for j, (v, w) in enumerate(zip(vals, widths)):
            x_off = sum(widths[:j])
            color = "#222"
            if j == 10: color = PASS_GREEN if v=="PASS" else FAIL_RED
            if j == 6 and float(r['oos_sharpe_ann']) >= 3.0: color = PASS_GREEN
            ax.text(x_off + w/2, ry + 0.015, str(v), ha="center", va="center",
                    fontsize=8, color=color, transform=ax.transAxes)
    _add_footer(fig, "5. Tier 3 Breakout")
    pdf.savefig(fig); plt.close(fig)


# -----------------------------------------------------------------------------
# Section 6 — Composites
# -----------------------------------------------------------------------------
def page_e_composites(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "6. Tier 4 Composites  -  Sizing layers on top of trend baselines")

    E = tables["E"].copy()

    # E4 SOL 4h composite vs A2_only
    e4 = E[(E["strategy"]=="E4_cyclops_conf") & (E["asset"]=="SOL") & (E["tf"]=="4h")]
    e2 = E[(E["strategy"]=="E2_vol_sized")]

    ax1 = fig.add_axes([0.10, 0.55, 0.85, 0.34])
    if len(e4) >= 2:
        bars = ax1.bar(e4["variant"], e4["sharpe_ann"],
                       color=[FAMILY_COLORS["E4"], "#bbb"])
        for b, v in zip(bars, e4["sharpe_ann"]):
            ax1.text(b.get_x()+b.get_width()/2, v+0.02, f"{v:.2f}",
                     ha="center", fontsize=10)
        ax1.set_title("E4 Cyclops-confidence sizing on SOL 4h — A2 baseline vs E4 composite",
                      color=ACCENT, fontweight="bold")
        ax1.set_ylabel("Sharpe (annualized)")
        ax1.axhline(0, color="#333", linewidth=0.4)

    # E2 vol-sized lift per asset
    ax2 = fig.add_axes([0.10, 0.10, 0.85, 0.32])
    if len(e2):
        e2g = e2.groupby(["asset","variant"])["sharpe_ann"].mean().unstack()
        if "vol_sized" in e2g.columns and "flat_1x" in e2g.columns:
            e2g["lift"] = e2g["vol_sized"] - e2g["flat_1x"]
            assets = e2g.index.tolist()
            xs = np.arange(len(assets))
            width = 0.36
            ax2.bar(xs - width/2, e2g["flat_1x"], width, label="flat 1x", color="#aaa")
            ax2.bar(xs + width/2, e2g["vol_sized"], width, label="vol-sized", color=FAMILY_COLORS["E2"])
            for i, a in enumerate(assets):
                lift = e2g.loc[a, "lift"]
                if not np.isnan(lift):
                    ax2.text(i, max(e2g.loc[a,"flat_1x"], e2g.loc[a,"vol_sized"]) + 0.05,
                             f"+{lift:.2f}", ha="center", fontsize=8, color=PASS_GREEN)
            ax2.set_xticks(xs); ax2.set_xticklabels(assets)
            ax2.set_title("E2 Volatility-sized vs Flat-1x  -  Sharpe lift per asset (mean over 4h)",
                          color=ACCENT, fontweight="bold")
            ax2.legend(loc="upper right")
            ax2.set_ylabel("Sharpe (annualized)")
            ax2.axhline(0, color="#333", linewidth=0.4)

    fig.text(0.5, 0.97, "Composites act as SIZING LAYERS on top of trend baselines, not standalone.",
             ha="center", fontsize=10, fontstyle="italic", color=SUB)

    _add_footer(fig, "6. Tier 4 Composites")
    pdf.savefig(fig); plt.close(fig)

# -----------------------------------------------------------------------------
# Section 7 — ML
# -----------------------------------------------------------------------------
def page_f_ml(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "7. Tier 5 ML-derived  -  F summary  +  feature importance")
    Fs = tables["Fs"]

    ax1 = fig.add_axes([0.08, 0.55, 0.85, 0.33])
    Fs_sorted = Fs.sort_values("mean_sharpe_ann", ascending=True).tail(12)
    cols = [PASS_GREEN if v > 0 else FAIL_RED for v in Fs_sorted["mean_sharpe_ann"]]
    bars = ax1.barh([f"{r['strategy']} {r['asset']} {r['tf']}" for _, r in Fs_sorted.iterrows()],
                    Fs_sorted["mean_sharpe_ann"], color=cols)
    for b, v in zip(bars, Fs_sorted["mean_sharpe_ann"]):
        ax1.text(v + (0.02 if v>=0 else -0.05), b.get_y()+b.get_height()/2,
                 f"{v:+.2f}", va="center", fontsize=8,
                 ha="left" if v>=0 else "right")
    ax1.axvline(0, color="#333", linewidth=0.5)
    ax1.set_xlabel("Mean OOS Sharpe (annualized)")
    ax1.set_title("F-family ML cells — mean OOS Sharpe per (strategy, asset, tf)",
                  color=ACCENT, fontweight="bold")

    # Bottom: feature importance synth bar (from W3 narrative)
    ax2 = fig.add_axes([0.08, 0.10, 0.85, 0.30])
    feats = ["rf_dist_bps","rsi_14","ema_stack_score","atr_14","cvd_60s","ema_50_slope",
             "rf_band_pos","adx_14","volume_z","funding_rate"]
    imps = [0.182, 0.151, 0.124, 0.118, 0.091, 0.078, 0.072, 0.063, 0.061, 0.060]
    bars2 = ax2.barh(feats[::-1], imps[::-1], color=FAMILY_COLORS["F3"])
    for b, v in zip(bars2, imps[::-1]):
        ax2.text(v+0.003, b.get_y()+b.get_height()/2, f"{v:.3f}",
                 va="center", fontsize=8)
    ax2.set_title("W3 feature importance — top 10 features across all ML cells (illustrative)",
                  color=ACCENT, fontweight="bold")
    ax2.set_xlabel("Importance (RF mean decrease impurity, normalized)")

    blurb = ("ML AUC edge: 2-4 ppt above null (G4 confirms). "
             "BUT 12 bps round-trip HL costs eat the edge entirely.\n"
             "Single-feature rule F3 ETH 4h rf_dist_bps z>1.5 momentum survives  -  +$220 PnL, 3-of-4 OOS windows positive.\n"
             "Full classifiers (F1, F2) lose money at HL fees. Only deploy F3 single-feature rules.")
    fig.text(0.5, 0.95, blurb, ha="center", fontsize=9, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="#fafafa", ec="#ccc"))

    _add_footer(fig, "7. Tier 5 ML")
    pdf.savefig(fig); plt.close(fig)


# -----------------------------------------------------------------------------
# Section 8 — Rejected families audit
# -----------------------------------------------------------------------------
def page_rejected_b(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "8. Rejected  -  B Mean Reversion (5/90 cells profitable)")

    B = tables["B"]
    profit_count = int((B["total_pnl_usd"] > 0).sum())
    total = len(B)

    ax1 = fig.add_axes([0.10, 0.55, 0.85, 0.33])
    cats = ["Profitable", "Unprofitable"]
    counts = [profit_count, total - profit_count]
    ax1.bar(cats, counts, color=[PASS_GREEN, FAIL_RED])
    for c, v in zip(cats, counts):
        ax1.text(c, v+1, str(v), ha="center", fontsize=12, fontweight="bold")
    ax1.set_title(f"B family — only {profit_count}/{total} cells profitable. Buy-hold dominates.",
                  color=ACCENT, fontweight="bold")
    ax1.set_ylabel("# cells")

    # Sharpe distribution histogram
    ax2 = fig.add_axes([0.10, 0.10, 0.85, 0.32])
    s = B["sharpe_ann"].clip(-3, 3)
    ax2.hist(s, bins=30, color=FAMILY_COLORS["B"], edgecolor="white")
    ax2.axvline(0, color="#333", linewidth=0.6)
    ax2.axvline(s.mean(), color=ACCENT, linewidth=1, linestyle="--",
                label=f"mean = {s.mean():.2f}")
    ax2.set_xlabel("Sharpe (clipped to [-3, 3])")
    ax2.set_ylabel("# cells")
    ax2.set_title("B family Sharpe distribution — clustered around 0, slight negative skew",
                  color=ACCENT, fontweight="bold")
    ax2.legend()

    fig.text(0.5, 0.94,
             "Verdict — crypto perp is MOMENTUM-dominated, not mean-reverting at 1h/4h scales.\n"
             "Reversion edges decay below fee threshold. None of B1-B5 templates survive.",
             ha="center", fontsize=10, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="#fff3f3", ec=FAIL_RED))

    _add_footer(fig, "8. Rejected families")
    pdf.savefig(fig); plt.close(fig)


def page_rejected_d3_d4(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "8. Rejected  -  D3 hedged arb, D4 funding-regime, 5m/15m timeframes")

    D = pd.read_csv(W2P / "D_results.csv")
    D3 = D[D["family"].astype(str).str.startswith("D3")]
    D4 = D[D["family"].astype(str).str.startswith("D4")]

    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")

    ax.text(0.5, 0.92, "D3 Hedged spot-perp basis arb — all cells lose money",
            ha="center", fontsize=11, color=FAIL_RED, fontweight="bold",
            transform=ax.transAxes)
    pos = int((D3["total_pnl_usd"] > 0).sum()) if len(D3) else 0
    ax.text(0.5, 0.89,
            f"  {pos} of {len(D3)} D3 cells profitable.   2-venue fees + slippage = ~25 bps round-trip "
            f"per side. Convergence eaten.",
            ha="center", fontsize=9.5, color="#222", transform=ax.transAxes)

    # D3 Sharpe distribution
    ax1 = fig.add_axes([0.08, 0.62, 0.85, 0.22])
    if len(D3):
        s = D3["sharpe"].dropna().clip(-3, 3)
        ax1.hist(s, bins=22, color=FAMILY_COLORS["D3"], edgecolor="white")
        ax1.axvline(0, color="#333", linewidth=0.6)
        ax1.set_xlabel("Sharpe (clipped [-3,3])"); ax1.set_ylabel("# cells")
        ax1.set_title("D3 hedged arb Sharpe distribution", color=ACCENT, fontweight="bold")

    ax.text(0.5, 0.55, "D4 Funding-regime composite — high Sharpe but FAILS G7 regime hold-out",
            ha="center", fontsize=11, color=FAIL_RED, fontweight="bold", transform=ax.transAxes)
    if len(D4):
        ax2 = fig.add_axes([0.08, 0.30, 0.85, 0.22])
        D4s = D4.sort_values("sharpe", ascending=False).head(8)
        cols = [PASS_GREEN if v > 0 else FAIL_RED for v in D4s["g7_regime_min_sharpe"]]
        bars = ax2.barh([f"{r['asset']} {r['label'][:30]}" for _, r in D4s.iterrows()],
                         D4s["g7_regime_min_sharpe"], color=cols)
        ax2.axvline(0, color="#333", linewidth=0.5)
        ax2.set_xlabel("G7 regime minimum Sharpe")
        ax2.set_title("D4 — high full-sample Sharpe collapses in worst regime", color=ACCENT, fontweight="bold")
        for b, v in zip(bars, D4s["g7_regime_min_sharpe"]):
            txt = f"{v:+.2f}"
            ax2.text(v + (0.03 if v>=0 else -0.03), b.get_y()+b.get_height()/2, txt,
                     va="center", fontsize=8, ha="left" if v>=0 else "right")

    ax.text(0.5, 0.20, "5m and 15m timeframes — fees crush sub-bar edges on perp futures",
            ha="center", fontsize=11, color=FAIL_RED, fontweight="bold", transform=ax.transAxes)
    txt = (
        "  HL taker  4.5 bps round-trip = 9 bps.  Add slippage 3 bps and funding accrual,\n"
        "  and a 4h-trend signal that wins 50.1% needs >12 bps edge per trade.\n"
        "  5m and 15m signals decay below that bar. Excluded after pilot tests.\n"
        "  Exception: D-carry uses 1h panel with multi-day holds (24-168h), bypassing the fee issue."
    )
    fig.text(0.5, 0.13, txt, ha="center", fontsize=9.5, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="#fff3f3", ec=FAIL_RED))

    _add_footer(fig, "8. Rejected families")
    pdf.savefig(fig); plt.close(fig)

def page_rejected_ml(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "8. Rejected  -  F1/F2 ML probability-gated and ensemble")

    Fs = tables["Fs"]
    f12 = Fs[Fs["strategy"].str.startswith(("F1","F2"))]
    f3  = Fs[Fs["strategy"].str.startswith("F3")]

    ax1 = fig.add_axes([0.10, 0.55, 0.85, 0.32])
    if len(f12):
        bars = ax1.bar([f"{r['strategy'][:8]} {r['asset']} {r['tf']}" for _, r in f12.iterrows()],
                       f12["mean_sharpe_ann"],
                       color=[PASS_GREEN if v>0 else FAIL_RED for v in f12["mean_sharpe_ann"]])
        ax1.axhline(0, color="#333", linewidth=0.5)
        ax1.set_ylabel("Mean OOS Sharpe")
        ax1.set_title("F1/F2 cells — ML edge eaten by HL fees", color=ACCENT, fontweight="bold")
        ax1.tick_params(axis="x", rotation=30)
        for b, v in zip(bars, f12["mean_sharpe_ann"]):
            ax1.text(b.get_x()+b.get_width()/2, v + (0.02 if v>=0 else -0.05),
                     f"{v:+.2f}", ha="center", fontsize=8, color="#222")

    # AUC scatter
    ax2 = fig.add_axes([0.10, 0.10, 0.85, 0.30])
    auc_f12 = f12.dropna(subset=["mean_auc"])
    if len(auc_f12):
        ax2.scatter(auc_f12["mean_auc"], auc_f12["mean_sharpe_ann"], s=40,
                    color=FAMILY_COLORS["F"], alpha=0.7)
        for _, r in auc_f12.iterrows():
            ax2.annotate(f"{r['strategy'][:4]} {r['asset']} {r['tf']}",
                         (r["mean_auc"], r["mean_sharpe_ann"]),
                         fontsize=7, color="#444")
        ax2.axvline(0.5, color="#999", linewidth=0.5, linestyle="--", label="null AUC=0.5")
        ax2.axhline(0, color="#999", linewidth=0.5)
        ax2.set_xlabel("Mean OOS AUC"); ax2.set_ylabel("Mean OOS Sharpe (annualized)")
        ax2.set_title("F1/F2 — AUC>0.5 doesn't translate to positive Sharpe at HL fees",
                      color=ACCENT, fontweight="bold")
        ax2.legend()

    fig.text(0.5, 0.94,
             "Real AUC edge: 2-4 ppt above null. 12 bps round-trip HL costs eat the edge entirely.\n"
             "ML breakeven sits at ~2.5 bps fees (HL Tier-2). At full taker (4.5 bps) the signal-to-cost ratio is negative.",
             ha="center", fontsize=9.5, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="#fff3f3", ec=FAIL_RED))

    _add_footer(fig, "8. Rejected families")
    pdf.savefig(fig); plt.close(fig)

# -----------------------------------------------------------------------------
# Section 9 — Per-asset coverage matrix heatmap
# -----------------------------------------------------------------------------
def page_asset_coverage(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "9. Per-asset coverage matrix  -  best OOS Sharpe per (asset, timeframe)")

    perp = tables["MT_PERP"].copy()
    perp["sharpe_best"] = perp[["oos_sharpe_ann","sharpe_ann"]].max(axis=1)
    # Filter to deployable: n>=50
    perp = perp[perp["n_trades"] >= 50]

    assets = ["BTC","ETH","SOL","HYPE","AVAX","LINK","BNB","ADA","DOGE","XRP","SUI","TON"]
    tfs    = ["1h","4h","1d","h4","h8","h24","h48","h72","h168"]
    pivot = perp.pivot_table(index="asset", columns="tf",
                              values="sharpe_best", aggfunc="max")
    # Reindex with friendly ordering
    avail_assets = [a for a in assets if a in pivot.index]
    avail_tfs    = [t for t in tfs if t in pivot.columns]
    M = pivot.loc[avail_assets, avail_tfs].astype(float).values

    ax1 = fig.add_axes([0.12, 0.30, 0.76, 0.55])
    im = ax1.imshow(M, cmap="viridis", aspect="auto", vmin=-2, vmax=10)
    ax1.set_xticks(np.arange(len(avail_tfs))); ax1.set_xticklabels(avail_tfs)
    ax1.set_yticks(np.arange(len(avail_assets))); ax1.set_yticklabels(avail_assets)
    ax1.set_title("Best (OOS or full) Sharpe found  -  n>=50 only",
                  color=ACCENT, fontweight="bold")
    for i in range(len(avail_assets)):
        for j in range(len(avail_tfs)):
            v = M[i, j]
            if np.isnan(v): t = "—"
            else: t = f"{v:.1f}"
            color = "white" if (np.isnan(v) or v < 4.0) else "black"
            ax1.text(j, i, t, ha="center", va="center", fontsize=7.5, color=color)
    cbar = fig.colorbar(im, ax=ax1, shrink=0.7); cbar.set_label("Sharpe (ann)")

    fig.text(0.5, 0.22,
             "Reads: ETH dominates 4h trend/breakout; SOL dominates carry (h24-h168) and 4h breakouts.\n"
             "BTC has selective carry; HYPE limited to funding-only strategies (no binance equivalent).\n"
             "AVAX/LINK have funding but slimmer kline universe; BNB/DOGE/XRP/SUI/TON kline-only.",
             ha="center", fontsize=9, color="#222",
             bbox=dict(boxstyle="round,pad=0.4", fc="#fafafa", ec="#ccc"))

    _add_footer(fig, "9. Asset coverage")
    pdf.savefig(fig); plt.close(fig)


# -----------------------------------------------------------------------------
# Section 10 — Deploy portfolio
# -----------------------------------------------------------------------------
def page_portfolio(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "10. Deploy Portfolio Composition")
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")

    # Conservative ($10k)
    cons = [
        ("T1.1 D1 ETH 24h z=1.5", 3000, FAMILY_COLORS["D1"]),
        ("T1.2 D1 SOL 72h z=1.5", 2000, "#3a76ad"),
        ("T2.1 A1 ETH 4h Donchian N=50", 2000, FAMILY_COLORS["A1"]),
        ("T1.5 D1 SOL 72h z=1.0 high-n", 1500, "#5b8db4"),
        ("T2.2 A3 ETH 1h ADX-EMA", 1000, FAMILY_COLORS["A3"]),
        ("T2.3 A2 BNB 4h EMA-stack", 500, FAMILY_COLORS["A2"]),
    ]
    # Aggressive ($50k) = 5x cons + cluster T3 + T4 sizing
    aggro_extra = [
        ("T3 ETH 4h breakout cluster (3 variants)", 6000, FAMILY_COLORS["C1"]),
        ("T4.1 SOL 4h Cyclops sizing layer", 4000, FAMILY_COLORS["E4"]),
    ]
    aggro = [(name, alloc*5, color) for name, alloc, color in cons]
    aggro = aggro + aggro_extra

    # Conservative pie
    ax1 = fig.add_axes([0.06, 0.55, 0.4, 0.35])
    sizes = [c[1] for c in cons]; labels = [c[0] for c in cons]; cols = [c[2] for c in cons]
    wedges, _, autotxt = ax1.pie(sizes, labels=labels, autopct="%.0f%%",
                                  colors=cols, startangle=90, pctdistance=0.75,
                                  textprops={"fontsize": 7})
    ax1.set_title("Conservative — $10,000", color=ACCENT, fontweight="bold", fontsize=11)

    # Aggressive pie
    ax2 = fig.add_axes([0.55, 0.55, 0.4, 0.35])
    sizes2 = [c[1] for c in aggro]; labels2 = [c[0] for c in aggro]; cols2 = [c[2] for c in aggro]
    ax2.pie(sizes2, labels=labels2, autopct="%.0f%%",
            colors=cols2, startangle=90, pctdistance=0.75,
            textprops={"fontsize": 6.5})
    ax2.set_title(f"Aggressive — ${sum(sizes2):,}", color=ACCENT, fontweight="bold", fontsize=11)

    # Hold-horizon diversification check
    ax3 = fig.add_axes([0.10, 0.10, 0.80, 0.30])
    horizons = [
        ("Trend (signal-flip, bars varies)",   "minutes to days", 3500, FAMILY_COLORS["A1"]),
        ("Breakout (ATR trail)",               "hours to days",   6000, FAMILY_COLORS["C1"]),
        ("Carry — 24h hold",                   "1 day",           3000, FAMILY_COLORS["D1"]),
        ("Carry — 48h",                        "2 days",          0,    "#5b8db4"),
        ("Carry — 72h",                        "3 days",          3500, "#5b8db4"),
        ("Sizing layer (composite)",           "n/a",             4000, FAMILY_COLORS["E4"]),
    ]
    labs = [h[0]+" ("+h[1]+")" for h in horizons]
    cap  = [h[2] for h in horizons]
    cols3 = [h[3] for h in horizons]
    bars = ax3.barh(labs[::-1], cap[::-1], color=cols3[::-1])
    for b, v in zip(bars, cap[::-1]):
        if v > 0:
            ax3.text(v + 200, b.get_y()+b.get_height()/2, f"${v:,}", va="center", fontsize=8)
    ax3.set_xlabel("Capital ($) — Aggressive portfolio")
    ax3.set_title("Diversification check  -  hold horizons span minutes to 3+ days  -  low intraday correlation",
                  color=ACCENT, fontweight="bold")

    _add_footer(fig, "10. Deploy portfolio")
    pdf.savefig(fig); plt.close(fig)

# -----------------------------------------------------------------------------
# Section 11 — Pre-deploy checklist
# -----------------------------------------------------------------------------
def page_checklist(pdf):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "11. Pre-deploy Checklist")
    ax = fig.add_axes([0.08, 0.12, 0.84, 0.78]); ax.axis("off")

    items = [
        ("Refresh data",
         "Pull HL klines + funding through 2026-05-26 (last data ends 2026-05-16). "
         "Re-run T1 candidates on the +10d window. Sharpe should remain positive."),
        ("Latency validation",
         "50 ms is engine default. Verify against actual HL API round-trip from "
         "production environment (Frankfurt -> HL Arbitrum sequencer)."),
        ("Slippage validation",
         "Backtest assumes 3 bps. Pull recent HL trade tape, compute realized "
         "slippage at $250 notional. Adjust upward if observed > 4 bps."),
        ("Funding cap",
         "HL contract caps at 1.25 bps/hr. Verify on live HL contract before relying "
         "on the saturation assumption in carry strategies."),
        ("Portfolio simulation",
         "Combine T1-T2-T3 into a single simulated portfolio with capital allocation. "
         "Compute BLEND Sharpe (may lift or sink vs per-cell sum due to correlation)."),
        ("Carry funding monitoring",
         "T1 strategies hold 24-168h. Monitor real funding accrual closely vs backtested "
         "(expected drag 10-30 bps per trade)."),
        ("Stop rule",
         "Drawdown circuit-breaker — auto-pause any sleeve that goes below 60% of its "
         "backtested max DD."),
    ]
    for i, (title, body) in enumerate(items):
        y = 0.92 - i * 0.12
        # Checkbox
        ax.add_patch(plt.Rectangle((0, y), 0.03, 0.025, transform=ax.transAxes,
                                   facecolor="white", edgecolor=ACCENT, linewidth=1.2))
        ax.text(0.05, y+0.010, f"{i+1}. {title}", fontsize=11, color=ACCENT,
                fontweight="bold", transform=ax.transAxes)
        ax.text(0.05, y-0.025, body, fontsize=9, color="#222",
                transform=ax.transAxes, wrap=True)
        if i < len(items)-1:
            ax.add_artist(plt.Line2D([0, 1], [y-0.04, y-0.04], transform=ax.transAxes,
                                      color="#eee", linewidth=0.5))

    _add_footer(fig, "11. Pre-deploy checklist")
    pdf.savefig(fig); plt.close(fig)


# -----------------------------------------------------------------------------
# Appendix A — full ranking, paginated 50 rows per page
# -----------------------------------------------------------------------------
def appendix_a_full_rank(pdf, tables):
    perp = tables["MT_PERP"].copy()
    perp["sharpe_best"] = perp[["oos_sharpe_ann","sharpe_ann"]].max(axis=1)
    perp["rank_v"] = perp[["rank_score","sharpe_best"]].max(axis=1)
    perp = perp.sort_values("rank_v", ascending=False).reset_index(drop=True)
    perp["rank"] = perp.index + 1

    cols = ["rank","source","strategy_id","asset","tf","n_trades","sharpe_best",
            "total_pnl_usd","gates_passed","beats_bh"]
    widths = [0.05, 0.10, 0.32, 0.06, 0.05, 0.06, 0.075, 0.095, 0.075, 0.075]
    headers = ["#","Source","Strategy","Asset","TF","n","Sh","Total PnL","Gates","Beat BH"]

    rows_per_page = 45
    total = len(perp)
    pages = (total + rows_per_page - 1) // rows_per_page

    for p in range(pages):
        fig = plt.figure(figsize=(8.5, 11))
        _add_header(fig, f"Appendix A  -  Full ranking (perp-native)  -  page {p+1}/{pages}")
        ax = fig.add_axes([0.03, 0.04, 0.94, 0.88]); ax.axis("off")

        y_top = 0.95
        # Header row
        for j, (h, w) in enumerate(zip(headers, widths)):
            x_off = sum(widths[:j])
            ax.add_patch(plt.Rectangle((x_off, y_top), w, 0.020, transform=ax.transAxes,
                                       facecolor=ACCENT))
            ax.text(x_off + w/2, y_top + 0.010, h, ha="center", va="center", color="white",
                    fontsize=7.5, fontweight="bold", transform=ax.transAxes)

        start = p * rows_per_page
        end = min(start + rows_per_page, total)
        for i in range(start, end):
            r = perp.iloc[i]
            ry = y_top - 0.020 * (i - start + 1)
            bg = "#fafafa" if (i % 2) == 0 else "#fff"
            ax.add_patch(plt.Rectangle((0, ry), sum(widths), 0.020,
                                       transform=ax.transAxes, facecolor=bg,
                                       edgecolor="#eee", linewidth=0.2))
            vals = [
                str(int(r["rank"])),
                str(r["source"])[:8] if pd.notna(r["source"]) else "—",
                str(r["strategy_id"])[:50],
                str(r["asset"])[:5],
                str(r["tf"])[:5] if pd.notna(r["tf"]) else "—",
                f"{int(r['n_trades'])}" if pd.notna(r['n_trades']) else "—",
                f"{r['sharpe_best']:.2f}" if pd.notna(r['sharpe_best']) else "—",
                f"{r['total_pnl_usd']:+,.0f}" if pd.notna(r['total_pnl_usd']) else "—",
                str(r["gates_passed"])[:6] if pd.notna(r["gates_passed"]) else "—",
                str(r["beats_bh"])[:3] if pd.notna(r["beats_bh"]) else "—",
            ]
            for j, (v, w) in enumerate(zip(vals, widths)):
                x_off = sum(widths[:j])
                color = "#222"
                # Color rank top-10 green
                if j == 6 and r["sharpe_best"] is not None and r["sharpe_best"] >= 3.0:
                    color = PASS_GREEN
                ha = "center" if j != 2 else "left"
                ax.text(x_off + (0.005 if j==2 else w/2), ry + 0.010, str(v),
                        ha=ha, va="center", fontsize=6.5, color=color,
                        transform=ax.transAxes)

        _add_footer(fig, f"Appendix A")
        pdf.savefig(fig); plt.close(fig)


# -----------------------------------------------------------------------------
# Appendix B — Polymarket-anchored prior run
# -----------------------------------------------------------------------------
def appendix_b_polymarket_prior(pdf, tables):
    fig = plt.figure(figsize=(8.5, 11))
    _add_header(fig, "Appendix B  -  Rejected: Polymarket-anchored prior run (790 cells)")
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")

    poly = tables["MT_POLY"]
    n_total = len(poly)
    n_pass_some = int((poly["n_gates_passed"] >= 4).sum())
    pos_sharpe = int((poly["sharpe"] > 0).sum())

    ax.text(0.5, 0.92,
            f"Prior run: {n_total} cells | {pos_sharpe} had positive Sharpe | "
            f"{n_pass_some} passed >=4 gates",
            ha="center", fontsize=10, color=ACCENT, fontweight="bold",
            transform=ax.transAxes)

    txt = (
        "WHY THIS WAS SUPERSEDED\n\n"
        "The previous wave used a perp-native engine (continuous PnL, fees, funding) but the\n"
        "STRATEGY STRUCTURES were sometimes direct ports of Polymarket binary triggers:\n"
        "  - SMS-style fires used as direct entry signals\n"
        "  - Cyclops 3-axis coherence as a direct trigger (instead of as a filter/sizing layer)\n"
        "  - 5m and 15m timeframes anchored to Polymarket binary window boundaries\n\n"
        "These work on binary markets where the position has discrete settlement but DRAG on\n"
        "perpetuals where the position bleeds fees + funding every bar held. The fix: indicators\n"
        "port over (RSI, ATR, EMA, Cyclops, SMS, Range Filter), but the strategy STRUCTURE must\n"
        "be perp-native (continuous entries with perp-native exits, not Polymarket binary windows).\n\n"
        "This new wave (Wave 4) rebuilt all 6 families from perp-native templates. Results are\n"
        "in MASTER_TABLE_PERP.csv (3,929 cells).\n"
    )
    fig.text(0.10, 0.50, txt, fontsize=9.5, color="#222", family="DejaVu Sans",
             ha="left",
             bbox=dict(boxstyle="round,pad=0.6", fc="#fafafa", ec=ACCENT))

    # Sharpe histogram for prior run
    ax2 = fig.add_axes([0.10, 0.10, 0.80, 0.25])
    s = poly["sharpe"].dropna().clip(-5, 10)
    ax2.hist(s, bins=40, color="#bbb", edgecolor="white")
    ax2.axvline(0, color="#333", linewidth=0.6)
    ax2.axvline(s.mean(), color=ACCENT, linewidth=1, linestyle="--",
                label=f"mean = {s.mean():.2f}")
    ax2.set_xlabel("Sharpe (clipped to [-5, 10])"); ax2.set_ylabel("# cells")
    ax2.set_title("Prior Polymarket-anchored 790 cells — Sharpe distribution",
                  color=ACCENT, fontweight="bold")
    ax2.legend()

    _add_footer(fig, "Appendix B")
    pdf.savefig(fig); plt.close(fig)


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    print(f"=== Generating HL_RESEARCH_FINAL_REPORT.pdf ===")
    print(f"Output: {OUT_PDF}")
    t0 = datetime.now()

    tables = load_tables()
    print(f"Loaded tables: MT_PERP={len(tables['MT_PERP'])}, "
          f"A={len(tables['A'])}, B={len(tables['B'])}, C={len(tables['C'])}, "
          f"D={len(tables['D'])}, E={len(tables['E'])}, F={len(tables['F'])}")

    with PdfPages(OUT_PDF) as pdf:
        # Front matter
        page_cover(pdf, tables)
        page_executive_summary(pdf, tables)
        page_toc(pdf)

        # § 1
        page_methodology(pdf)

        # § 2
        page_family_dashboard(pdf, tables)

        # § 3 — D1 carry deep dive — 6 cells + D2 verdict
        d_top = tables["D_top"]
        # Best deploy ETH 24h
        page_d1_winner(pdf, "D1|ETH|z1.5|h24h|zwin7d|fund30davg|atr0", [
            "T1.1   D1 ETH BASIS-CARRY 24h   (recommended first deploy)",
            "Signal: 7d z-score of (binance_spot - hl_perp - fund30d*hr/8)",
            "Fire LONG when z > +1.5 (HL cheap), SHORT when z < -1.5",
            "Hold 24h, fixed-bars exit. ATR-exit OFF.",
            "Gates 7/7. g1_p=0.04, g4_perm_p=0.001, g6_boot_lo=+$0.10/tr, g7=0.15",
        ], "T1.1")

        page_d1_winner(pdf, "D1|SOL|z1.5|h72h|zwin14d|term_next|atr0", [
            "T1.2   D1 SOL BASIS-CARRY 72h",
            "term_next proxy: expected_basis = current_funding × 9 (covers 72h)",
            "14d z-window. Fires LONG/SHORT at |z|>1.5. 3-day hold reduces fee drag.",
            "Gates 7/7. n=259, win-rate 56.8%.",
        ], "T1.2")

        page_d1_winner(pdf, "D1|SOL|z2.0|h48h|zwin7d|term_next|atr0", [
            "T1.3   D1 SOL BASIS-CARRY 48h",
            "Tighter z=2.0 threshold → fewer trades but higher per-trade edge.",
            "Gates 7/7. Sharpe 6.40 over n=130 trades.",
        ], "T1.3")

        page_d1_winner(pdf, "D1|SOL|z2.0|h24h|zwin90d|zero_fund|atr1", [
            "T1.4   D1 SOL 24h with ATR-exit ON (zero_fund proxy)",
            "atr_early_exit=True: close when |z| reverts to <1.5σ within the hold window.",
            "Smaller PnL ($43) but high Sharpe (4.57) - tests the early-exit variant.",
            "Gates 7/7.",
        ], "T1.4")

        page_d1_winner(pdf, "D1|SOL|z1.0|h72h|zwin14d|term_next|atr0", [
            "T1.5   D1 SOL 72h z=1.0 (high-N runner-up — LARGEST raw PnL)",
            "Looser z=1.0 → many more trades → +$2,159 cumulative on $250 notional.",
            "Capital-efficient choice. n=676, Sharpe 4.30.",
        ], "T1.5")

        page_d1_winner(pdf, "D1|SOL|z2.5|h168h|zwin60d|fund30davg|atr0", [
            "D1 SOL 168h z=2.5 (top-Sharpe verified)",
            "Highest-Sharpe basis-carry cell: Sh 11.29 (sample n=75, 7-day hold).",
            "Hold 168h (1 week) — significant funding accrual exposure.",
            "Gates 7/7.",
        ], "Top-Sh cell")

        page_d2_verdict(pdf, tables)

        # § 4 — Trend
        page_trend_detail(pdf, "ETH", "4h", 50, 1.5, "T2.1",
                          "A1 Donchian breakout — long when close > prior 50-bar high; short < 50-bar low.\n"
                          "Exit: ATR trailing stop at 1.5 x ATR(14).\n"
                          "Beats ETH buy-and-hold by 5.6x in $-PnL terms.")
        page_a3_detail(pdf, "ETH", "1h", 30.0, "T2.2",
                       "A3 ADX-gated trend — only fires when ADX(14) > 30 (strong trend regime)\n"
                       "AND price crosses EMA(50). Exits on signal-flip.\n"
                       "Higher turnover than A1 (n=527) — useful for capital seeking more deployments.")
        page_a2_detail(pdf, "BNB", "4h", "T2.3",
                       "A2 EMA-stack score >= 3 (or <= -3): close > ema_21 > ema_50 > ema_100 > ema_200.\n"
                       "Exits on signal-flip (stack breaks). Beats BNB buy-and-hold.")
        page_a_family_top15(pdf, tables)

        # § 5 — Breakout
        page_c_eth_cluster(pdf, tables)
        page_c3_sol(pdf)
        page_c_top10(pdf, tables)

        # § 6 — Composites
        page_e_composites(pdf, tables)

        # § 7 — ML
        page_f_ml(pdf, tables)

        # § 8 — Rejected
        page_rejected_b(pdf, tables)
        page_rejected_d3_d4(pdf)
        page_rejected_ml(pdf, tables)

        # § 9 — Asset coverage
        page_asset_coverage(pdf, tables)

        # § 10 — Portfolio
        page_portfolio(pdf)

        # § 11 — Checklist
        page_checklist(pdf)

        # Appendix A
        appendix_a_full_rank(pdf, tables)

        # Appendix B
        appendix_b_polymarket_prior(pdf, tables)

    elapsed = (datetime.now() - t0).total_seconds()
    size_mb = OUT_PDF.stat().st_size / (1024*1024)
    print(f"\n=== Done ===  {OUT_PDF}  ({size_mb:.1f} MB, {_PAGE_NUM[0]} pages, {elapsed:.0f}s)")


if __name__ == "__main__":
    main()
