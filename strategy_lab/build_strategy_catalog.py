"""
Build STRATEGY_CATALOG.pdf — a comprehensive description of every strategy
tested in this session: entry, exit, stops, params, tests, strengths,
flaws, win rate, best result, and verdict.

Output path: C:\\Users\\alexandre bandarra\\Desktop\\newstrategies\\STRATEGY_CATALOG.pdf
"""
from __future__ import annotations
import json
import shutil
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
OUT_LOCAL = BASE / "reports" / "STRATEGY_CATALOG.pdf"
OUT_PUBLIC = Path("C:/Users/alexandre bandarra/Desktop/newstrategies/STRATEGY_CATALOG.pdf")
OUT_PUBLIC.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# Helper: pull a metric from a V-specific CSV
# ---------------------------------------------------------------------
def best_row(df: pd.DataFrame, name_col: str, name_val: str,
             metric: str = "sharpe"):
    if df is None or len(df) == 0: return None
    sub = df[df[name_col].astype(str).str.contains(name_val, na=False, case=False)]
    if len(sub) == 0: return None
    sub = sub.sort_values(metric, ascending=False)
    return sub.iloc[0].to_dict()


# ---------------------------------------------------------------------
# All strategies — structured metadata
# ---------------------------------------------------------------------
STRATEGIES = [
    # ================= BASELINE TREND-FOLLOWING =================
    {
        "id": "V2B",
        "name": "V2B — Volume Breakout",
        "family": "Baseline trend-following",
        "status": "DEPLOYED (BNB sleeve)",
        "one_liner": "Donchian high-break + volume-spike confirmation + HTF trend filter.",
        "entry": (
            "LONG when all three are true:\n"
            "   1. close > prior 30-bar high (Donchian break, shift-1 to avoid lookahead)\n"
            "   2. volume > 1.3 × 20-bar average volume (volume spike)\n"
            "   3. close > 150-period EMA (HTF regime up)"),
        "exit":   "close < 150-period EMA (regime break) OR 4.5 × ATR(14) trailing stop.",
        "stops":  "ATR-scaled trailing stop: tsl = ATR(14) × 4.5 / close.",
        "params": "don_len=30, vol_avg=20, vol_mult=1.3, regime_len=150, tsl_atr=4.5, atr_len=14",
        "tests":  "Full 2018-2026 on BTC/ETH/SOL + 6 new coins. 5-test robustness audit (passed 5/5 for SOL). Cross-coin edge hunt at 4h.",
        "strengths": [
            "Simple, transparent logic",
            "Generalizes across coins (passes on 9/9 at 4h)",
            "Captures big trending moves — SOL 2021 especially",
        ],
        "flaws": [
            "45% typical win rate (trend-follower baseline)",
            "Drawdowns to -51% (SOL 2018-22)",
            "Whipsaw losses in range-bound periods",
        ],
        "lookup_csv": "edge_hunt.csv",
        "lookup_match": ("V2B_volume_breakout", "4h"),
    },
    {
        "id": "V3B",
        "name": "V3B — ADX-Gated Volume Breakout",
        "family": "Baseline trend-following",
        "status": "DEPLOYED (ETH/LINK sleeve)",
        "one_liner": "V2B's breakout + volume + regime, with an ADX > 20 strength filter.",
        "entry": (
            "LONG when all four are true:\n"
            "   1. close > prior 120-bar Donchian high (shift-1)\n"
            "   2. volume > 1.3 × 80-bar avg volume\n"
            "   3. close > 600-period regime EMA (HTF trend)\n"
            "   4. ADX(14) > 20 (true trend, not chop)"),
        "exit":   "Regime break (close < EMA) OR ATR-trailing.",
        "stops":  "ATR-scaled trailing stop.",
        "params": "don_len=120, vol_len=80, vol_mult=1.3, regime_len=600, adx_min=20",
        "tests":  "Full 2018-2026. 5-test robustness on ETH (passed 5/5). Cross-coin edge hunt.",
        "strengths": [
            "Best single-coin performer for ETH at 4h (56% CAGR, Sharpe 1.26)",
            "ADX filter eliminates ~60% of whipsaws vs V2B",
            "Profitable on AVAX/DOGE/LINK/XRP full-period",
        ],
        "flaws": [
            "Fails OOS on AVAX/DOGE/BNB (2022-2025 curve inverts)",
            "42% win rate still low",
            "ADX > 20 gates out early-trend entries → misses starts",
        ],
        "lookup_csv": "edge_hunt.csv",
        "lookup_match": ("V3B_adx_gate", "4h"),
    },
    {
        "id": "V4C",
        "name": "V4C — Range Kalman",
        "family": "Baseline trend-following",
        "status": "DEPLOYED (BTC/SOL/ADA sleeve)",
        "one_liner": "Kalman-smoothed price + dynamic range band breakout + regime filter.",
        "entry": (
            "LONG when close crosses above the upper Kalman range band:\n"
            "   1. kal_t = kal_{t-1} + α(close_t − kal_{t-1})   (simple Kalman EMA)\n"
            "   2. range = rolling(|close − kal|, N) × mult\n"
            "   3. close crosses above kal + range AND close > regime EMA"),
        "exit":   "Regime-EMA break OR trailing stop.",
        "stops":  "ATR-scaled trailing stop (3.5 × ATR by default).",
        "params": "alpha=0.05, rng_len=400, rng_mult=2.5, regime_len=800, trail_atr=3.5 (for 1h), 100/2.5/100 for 4h.",
        "tests":  "Full 2018-2026. 5-test robustness on BTC (5/5). V13A 1h port (4.5/5). Edge hunt.",
        "strengths": [
            "Best single-coin performer for BTC at 4h (40% CAGR, Sharpe 1.32)",
            "Adaptive band sizing (ATR-scaled) handles vol regime shifts",
            "Wins on BTC, SOL, ADA",
        ],
        "flaws": [
            "Slow to react (400-bar range lookback)",
            "Range collapses in sudden vol spikes",
            "45% win rate",
        ],
        "lookup_csv": "edge_hunt.csv",
        "lookup_match": ("V4C_range_kalman", "4h"),
    },
    # ================= 1H PORTS =================
    {
        "id": "V13A",
        "name": "V13A — Range Kalman 1h",
        "family": "1h trend ports",
        "status": "DEPLOYED (ETH 1h sleeve only)",
        "one_liner": "V4C ported to 1h timeframe with 4× longer lookbacks.",
        "entry": "Same as V4C but on 1h bars (α=0.05, rng_len=400 = ~17 days).",
        "exit":  "TP 5×ATR, SL 2×ATR, trail 3.5×ATR, max hold 72 bars.",
        "stops": "ATR-based; uses the custom simulate() loop (not vbt engine).",
        "params": "alpha=0.05, rng_len=400, rng_mult=2.5, regime_len=800, TP=5×ATR, SL=2×ATR",
        "tests":  "Full 2019-2026 ETH 1h. 5-test robustness: 4.5/5 passed (cross-asset is partial).",
        "strengths": [
            "Only 1h strategy that works (ETH has unique 1h edge)",
            "OOS Sharpe 1.13 > IS Sharpe 0.93 — edge getting stronger",
            "271 trades over 7 years — healthy sample",
        ],
        "flaws": [
            "ETH-only — BTC/SOL fail at 1h",
            "19% CAGR modest vs 4h winners",
            "Does not generalize cross-asset",
        ],
        "lookup_csv": "edge_hunt.csv",
        "lookup_match": ("V13A_range_kalman", "1h"),
    },
    {
        "id": "V13B",
        "name": "V13B — ADX Gate 1h",
        "family": "1h trend ports",
        "status": "TESTED (not deployed)",
        "one_liner": "V3B at 1h, lookbacks scaled up.",
        "entry": "Donchian 120 + vol 80 + ADX > 20 + regime 600 at 1h.",
        "exit":  "TP/SL/trail as V13A.",
        "stops": "ATR-based.",
        "params": "don_len=120, vol_len=80, vol_mult=1.3, regime_len=600, adx_min=20",
        "tests":  "Full 2019-2026 on BTC/ETH/SOL 1h.",
        "strengths": ["ADX filter reduces whipsaws"],
        "flaws": [
            "Fails on all coins at 1h (Sharpe 0.23-0.30)",
            "Too many trades, fees eat edge",
        ],
        "lookup_csv": "edge_hunt.csv",
        "lookup_match": ("V13B_adx_gate", "1h"),
    },
    {
        "id": "V13C",
        "name": "V13C — Volume Breakout 1h",
        "family": "1h trend ports",
        "status": "TESTED (not deployed)",
        "one_liner": "V2B at 1h with 4× longer lookbacks.",
        "entry": "Donchian 120 + vol 80 spike + regime 600 at 1h (no ADX).",
        "exit":  "TP/SL/trail as V13A.",
        "stops": "ATR-based.",
        "params": "don_len=120, vol_len=80, vol_mult=1.3, regime_len=600",
        "tests":  "Full 2019-2026 on BTC/ETH/SOL 1h.",
        "strengths": ["Works on ETH 1h (Sharpe 0.71)"],
        "flaws": ["Fails on BTC and SOL 1h"],
        "lookup_csv": "edge_hunt.csv",
        "lookup_match": ("V13C_volume_breakout", "1h"),
    },
    # ================= V7 HIGH-WIN-RATE FAMILY =================
    {
        "id": "HWR1",
        "name": "HWR1 — Bollinger Mean-Reversion",
        "family": "V7 high-win-rate",
        "status": "DEPLOYED (XRP sleeve only)",
        "one_liner": "Buy lower Bollinger Band touch in a non-bear regime.",
        "entry": (
            "LONG when close ≤ lower BB(20, 2σ) AND close > 0.9 × EMA200 "
            "(bull-to-neutral regime) AND close > prior close (bullish reversal)."),
        "exit":   "close ≥ mid-BB (mean reverted) OR ATR 2× stop.",
        "stops":  "ATR-scaled static stop (2 × ATR(14) / close).",
        "params": "bb_len=20, bb_std=2.0, ema_len=200, atr_sl_mult=2.0",
        "tests":  "6 coins × 2022-2025 per-year WR audit. 7-variant HWR hunt (42 combos).",
        "strengths": [
            "Only high-WR strategy that's PROFITABLE on XRP (73.7% WR, PF 2.10)",
            "74% win rate on XRP — every year ≥ 57%",
            "Low drawdown (-19%)",
        ],
        "flaws": [
            "Fails on all other 5 coins (WR 44-57%, PF < 1)",
            "XRP-specific mean-reverting character required",
            "Lower CAGR (6-9%/yr) than trend-following",
        ],
        "lookup_csv": "hwr_summary.csv",
        "lookup_match": ("HWR1_bb_meanrev", None),
    },
    {
        "id": "HWR2",
        "name": "HWR2 — RSI + Stoch Oversold",
        "family": "V7 high-win-rate",
        "status": "FAILED",
        "one_liner": "Buy RSI < 25 + Stoch < 20 + price above 0.9×EMA200.",
        "entry":  "RSI(14) < 25 AND Stoch(14) < 20 AND close > EMA(200)*0.9.",
        "exit":   "RSI > 55 OR 3% fixed stop.",
        "stops":  "3% fixed percentage stop.",
        "params": "rsi_len=14, rsi_buy=25, rsi_exit=55, stoch_ob=20, sl_pct=0.03",
        "tests":  "6 coins × 2022-2025 per-year.",
        "strengths": ["None — did not pass the bar on any coin"],
        "flaws": [
            "9-40 trades over 4 years (too strict)",
            "WR 8-35% (far below target)",
            "PF < 1 on most coins",
        ],
        "lookup_csv": "hwr_summary.csv",
        "lookup_match": ("HWR2_rsi_stoch", None),
    },
    {
        "id": "HWR3",
        "name": "HWR3 — Pullback 1:1 R/R",
        "family": "V7 high-win-rate",
        "status": "FAILED (profitable only on LINK)",
        "one_liner": "Pullback to 20-EMA in trend with symmetric 1 ATR TP / 1 ATR SL.",
        "entry": (
            "EMA50 > EMA200 (trend up) AND low touched within 0.5% of 20-EMA "
            "in last 3 bars AND close > prior close."),
        "exit":   "TP = entry + 1×ATR, SL = entry − 1×ATR, signal exit on EMA50 < EMA200.",
        "stops":  "Symmetric ATR-based TP and SL.",
        "params": "ema_fast=20, ema_slow=50, ema_trend=200, atr_tp_mult=1.0, atr_sl_mult=1.0",
        "tests":  "6 coins × 2022-2025.",
        "strengths": ["LINK-only: 51.5% WR, PF 1.05, profitable"],
        "flaws": [
            "300+ trades/coin — fees erode edge despite maker",
            "1:1 R/R means even 55% WR barely beats fees",
            "47-48% WR on other coins — unprofitable",
        ],
        "lookup_csv": "hwr_summary.csv",
        "lookup_match": ("HWR3_pullback", None),
    },
    {
        "id": "HWR1b",
        "name": "HWR1b — BB Strict",
        "family": "V7 high-win-rate (refinement)",
        "status": "TESTED (not deployed)",
        "one_liner": "HWR1 with wider BB (2.5σ) and N-bar confirmation.",
        "entry":   "Price closed below 2.5σ lower band at least 1× in last 3 bars + bullish reversal bar.",
        "exit":    "close ≥ mid-BB.",
        "stops":   "4% fixed stop.",
        "params":  "bb_std=2.5, confirm_bars=1, sl_pct=0.04",
        "tests":   "6 coins × 2022-2025.",
        "strengths": ["Higher quality entries than HWR1 (fewer but more reliable)"],
        "flaws": [
            "Still fails on 5/6 coins",
            "Only 54-92 trades in 4 years — small sample",
        ],
        "lookup_csv": "hwr_summary.csv",
        "lookup_match": ("HWR1b_bb_strict", None),
    },
    {
        "id": "HWR3b",
        "name": "HWR3b — Pullback Asymmetric",
        "family": "V7 high-win-rate (refinement)",
        "status": "TESTED (LINK-profitable)",
        "one_liner": "Pullback with asymmetric 0.7 ATR TP / 1.8 ATR SL for structural high-WR.",
        "entry":   "3-tier EMA stack (20>50>200 rising) + pullback + RSI > 40.",
        "exit":    "TP = 0.7×ATR, SL = 1.8×ATR, signal exit on EMA50 < EMA200.",
        "stops":   "Asymmetric ATR-based.",
        "params":  "atr_tp=0.7, atr_sl=1.8, rsi_min=40",
        "tests":   "6 coins × 2022-2025.",
        "strengths": [
            "Win rate 66-73% on every coin (structural)",
            "LINK: 71% WR, PF 1.01, profitable",
        ],
        "flaws": [
            "PF < 1 on 5/6 coins despite high WR (1 loss = 2.5 wins)",
            "Asymmetric math requires ≥ 72% WR for positive EV",
        ],
        "lookup_csv": "hwr_summary.csv",
        "lookup_match": ("HWR3b_pullback_asym", None),
    },
    {
        "id": "HWR4",
        "name": "HWR4 — Keltner Channel Bounce",
        "family": "V7 high-win-rate",
        "status": "FAILED",
        "one_liner": "Buy lower Keltner Channel in uptrend, exit at mid-line.",
        "entry":   "close ≤ EMA(50) − 2.0×ATR AND close > 0.95×EMA(200).",
        "exit":    "close ≥ EMA(50) (mid-line).",
        "stops":   "2.5 × ATR static stop.",
        "params":  "ema_len=50, kc_mult=2.0, trend_ema=200",
        "tests":   "6 coins × 2022-2025.",
        "strengths": ["ATR-adaptive (not stdev like BB)"],
        "flaws": ["Too few trades on all coins (22-64). All unprofitable."],
        "lookup_csv": "hwr_summary.csv",
        "lookup_match": ("HWR4_keltner", None),
    },
    {
        "id": "HWR5",
        "name": "HWR5 — Tight TP / Wide SL",
        "family": "V7 high-win-rate",
        "status": "BORDERLINE (high WR, near-breakeven)",
        "one_liner": "TP = 0.5 ATR, SL = 2.5 ATR — structural 70%+ WR via tight target.",
        "entry":   "Uptrend (close > EMA20 > EMA100 rising) + RSI cross 50 from below.",
        "exit":    "TP=0.5×ATR, SL=2.5×ATR, signal exit on close < EMA100.",
        "stops":   "Ultra-asymmetric ATR.",
        "params":  "atr_tp=0.5, atr_sl=2.5, rsi_min=45",
        "tests":   "6 coins × 2022-2025.",
        "strengths": [
            "BTC 79% WR, LINK 77% WR, ETH 80% WR",
            "Structural high-WR design holds",
        ],
        "flaws": [
            "PF 0.67-1.03 — math requires ≥ 83% WR for real profit",
            "Even with high WR, every loss wipes out 5 wins",
            "Breakeven is the ceiling on 4h",
        ],
        "lookup_csv": "hwr_summary.csv",
        "lookup_match": ("HWR5_tight_tp", None),
    },
    # ================= V8 NOVEL ENTRIES =================
    {
        "id": "V8A",
        "name": "V8A — Triple SuperTrend Stack",
        "family": "V8 novel entries",
        "status": "FAILED (0 trades)",
        "one_liner": "Entry requires all 3 SuperTrend lines (fast/med/slow) to flip bullish + HTF EMA200 up.",
        "entry":   "SuperTrend(10,1) bull AND ST(11,2) bull AND ST(12,3) bull AND close > EMA200.",
        "exit":    "ST(12,3) flips bearish.",
        "stops":   "Chandelier exit (22-bar high − 3×ATR). Multi-TP 1/2/3.5 × ATR.",
        "params":  "p1=10/m1=1, p2=11/m2=2, p3=12/m3=3, htf_ema=200",
        "tests":   "6 coins × 2022-2025 via advanced simulator.",
        "strengths": ["Well-documented 2026 research design"],
        "flaws": [
            "Triple confluence never fires on 4h crypto",
            "0 trades on every coin in 4 years",
            "Over-filtered",
        ],
        "lookup_csv": "v8_hunt.csv",
        "lookup_match": ("V8A_supertrend_stack", None),
    },
    {
        "id": "V8B",
        "name": "V8B — HMA + ADX Regime",
        "family": "V8 novel entries",
        "status": "WEAK (XRP-only)",
        "one_liner": "Hull MA(55) + ADX > 22 regime filter with multi-TP ladder.",
        "entry":   "close > HMA(55) AND HMA slope > 0 AND ADX > 22.",
        "exit":    "HMA slope < 0 AND close < HMA.",
        "stops":   "1.5 × ATR initial SL; TP1/2/3 at 1.5/2.5/4 R; post-TP2 trail.",
        "params":  "hma_len=55, adx_min=22, sl_atr=1.5",
        "tests":   "6 coins × 2022-2025.",
        "strengths": ["XRP-only: WR 67%, PF 1.85, CAGR +4.3%"],
        "flaws": [
            "ADX > 22 on 4h is rare — 3-13 trades in 4 years per coin",
            "5/6 coins fail",
        ],
        "lookup_csv": "v8_hunt.csv",
        "lookup_match": ("V8B_hma_adx", None),
    },
    {
        "id": "V8C",
        "name": "V8C — Vol-Regime Donchian",
        "family": "V8 novel entries",
        "status": "BORDERLINE (ETH-only)",
        "one_liner": "Donchian breakout with volatility-percentile regime and regime-adaptive TP ladder.",
        "entry":   "close > 20-bar Donchian high AND vol-percentile > 25% AND close > EMA100 rising.",
        "exit":    "close < EMA100.",
        "stops":   "2 × ATR SL; TP 1.0/2.0/4.0 R in high-vol, 1.5/2.5/4.0 in normal-vol.",
        "params":  "don_len=20, ema_trend=100, vol_lookback=200, vol_threshold=0.25",
        "tests":   "6 coins × 2022-2025.",
        "strengths": [
            "ETH: WR 56%, PF 1.26, CAGR +4.0% (only pass)",
            "SOL: PF 1.67 (but only 4 trades in 4 years)",
        ],
        "flaws": ["Fails on BTC/LINK/ADA/XRP", "Low trade count"],
        "lookup_csv": "v8_hunt.csv",
        "lookup_match": ("V8C_vol_donchian", None),
    },
    # ================= V9 MULTI-TP LADDER WRAPPERS =================
    {
        "id": "V9A",
        "name": "V9A — V3B + Multi-TP Ladder",
        "family": "V9 multi-TP wrappers",
        "status": "TESTED — lower CAGR than V3B baseline",
        "one_liner": "V3B entries with TP1/TP2/TP3 = 1/2/3.5 ATR (40/30/30% scale-out) and ratcheting SL.",
        "entry":   "Same as V3B.",
        "exit":    "Multi-TP ladder OR V3B signal exit.",
        "stops":   "Initial 1.5×ATR SL → breakeven at TP1 → TP1 at TP2 → post-TP2 trail (2.5×ATR).",
        "params":  "sl_r=1.5, tp1_r=1.0, tp1_frac=0.40, tp2_r=2.0, tp2_frac=0.30, tp3_r=3.5, tp3_frac=0.30",
        "tests":   "6 coins × 2022-2025.",
        "strengths": [
            "Win rate up 40% → 55-65%",
            "Drawdowns cut in half (ratcheting SL)",
        ],
        "flaws": [
            "CAGR drops 45% → 0-2% — TP1 caps trending runs",
            "Clear WR-for-CAGR swap, no frontier shift",
        ],
        "lookup_csv": "v8_hunt.csv",
        "lookup_match": ("V9A_v3b_ladder", None),
    },
    {
        "id": "V9E",
        "name": "V9E — V3B Aggressive Runner",
        "family": "V9 multi-TP wrappers",
        "status": "BEST V9 — ETH/ADA profitable",
        "one_liner": "V3B with tiny TP1/TP2 (25%/25%) to preserve a BIG (50%) runner.",
        "entry":   "Same as V3B.",
        "exit":    "TP1=0.8 ATR, TP2=1.8 ATR, TP3=4.0 ATR, trail 3.0×ATR.",
        "stops":   "Ratcheting as V9A but with 50% runner weight.",
        "params":  "tp1_r=0.8, tp1_frac=0.25, tp2_r=1.8, tp2_frac=0.25, tp3_r=4.0, tp3_frac=0.50, trail_r=3.0",
        "tests":   "6 coins × 2022-2025.",
        "strengths": [
            "ETH: 75% WR, PF 2.27, CAGR +2.2%",
            "ADA: 71% WR, PF 1.87, CAGR +2.4%",
            "XRP: 64% WR, PF 1.08",
        ],
        "flaws": ["Still well below baseline V3B CAGR (~45%) on ETH"],
        "lookup_csv": "v8_hunt.csv",
        "lookup_match": ("V9E_v3b_aggressive", None),
    },
    # ================= V10 ORDERFLOW =================
    {
        "id": "V10A",
        "name": "V10A — Funding-Fade V3B",
        "family": "V10 orderflow",
        "status": "FAILED",
        "one_liner": "V3B entries gated by 3-day funding rate (skip when longs crowded).",
        "entry":   "V3B entry AND 3d mean funding NOT > +0.015%.",
        "exit":    "V3B signal exit.",
        "stops":   "Multi-TP ladder.",
        "params":  "funding_skip_above=0.00015, funding_boost_below=-0.00005",
        "tests":   "BTC/ETH/SOL × 2022-2025.",
        "strengths": ["BTC: 18 trades, 56% WR (slight up vs V3B)"],
        "flaws": [
            "PF 0.97 on BTC — filter kills winners too",
            "ETH/SOL: too few trades",
            "Level-based funding lags 4h price",
        ],
        "lookup_csv": "v10_hunt.csv",
        "lookup_match": ("V10A_funding_fade_v3b", None),
    },
    {
        "id": "V10B",
        "name": "V10B — OI-Confirmed V4C",
        "family": "V10 orderflow",
        "status": "FAILED",
        "one_liner": "V4C entry + require rising Open Interest (24h slope > 0).",
        "entry":   "V4C entry AND OI 24h slope > 0%.",
        "exit":    "V4C signal exit.",
        "stops":   "Multi-TP ladder.",
        "params":  "min_oi_slope_24h=0.00",
        "tests":   "BTC/ETH/SOL × 2022-2025.",
        "strengths": ["None"],
        "flaws": [
            "0-20 trades per coin over 4 years",
            "Filter eliminates genuine V4C winners",
        ],
        "lookup_csv": "v10_hunt.csv",
        "lookup_match": ("V10B_oi_confirm_v4c", None),
    },
    {
        "id": "V10C",
        "name": "V10C — L/S Ratio Long",
        "family": "V10 orderflow",
        "status": "FAILED",
        "one_liner": "Top-trader long/short ratio > 1.30 = smart-money long, enter.",
        "entry":   "top_trader_LS > 1.30 AND close > EMA(50).",
        "exit":    "LS < 1.10 OR close < EMA(50).",
        "stops":   "Multi-TP ladder (tight: tp1=0.8, tp2=1.8).",
        "params":  "ls_enter=1.30, ls_exit=1.10, ema_len=50",
        "tests":   "BTC/ETH/SOL × 2022-2025.",
        "strengths": ["SOL: 53% WR"],
        "flaws": [
            "All coins PF < 1",
            "Lagging ratio — signal fires after move is done",
        ],
        "lookup_csv": "v10_hunt.csv",
        "lookup_match": ("V10C_ls_extreme", None),
    },
    {
        "id": "V10D",
        "name": "V10D — Liquidation Cascade Rebound",
        "family": "V10 orderflow",
        "status": "FAILED",
        "one_liner": "Buy the dip after a 5× liquidation-volume spike in a bull regime.",
        "entry":   "liq_spike > 5× 6-day avg AND close > EMA(200).",
        "exit":    "close < EMA(200).",
        "stops":   "Tight: tp1=1.0, tp2=2.0, tp3=3.0 ATR, trail 1.5 ATR.",
        "params":  "spike_mult=5.0, ema_trend=200",
        "tests":   "BTC/ETH/SOL × 2022-2025 (liq data 2023+).",
        "strengths": ["SOL: 50% WR (but 2 trades)"],
        "flaws": [
            "Only 2-6 trades per coin in 4 years",
            "Cascade events rare at 4h — better at 1min",
        ],
        "lookup_csv": "v10_hunt.csv",
        "lookup_match": ("V10D_liq_cascade", None),
    },
    # ================= V11 REGIME ENSEMBLE =================
    {
        "id": "V11",
        "name": "V11 — Regime-Switching Ensemble",
        "family": "V11 regime ensemble",
        "status": "FAILED",
        "one_liner": "Classify bar as BULL/CHOP/BEAR/OTHER; run V4C in bull, HWR1 in chop, flat else.",
        "entry":   (
            "BULL: close > EMA100 AND ADX > 20 AND EMA50 > EMA100 → V4C entries\n"
            "CHOP: close near EMA100 ±2% AND ADX < 18 → HWR1 entries\n"
            "BEAR/OTHER: flat"),
        "exit":    "Strategy-specific (V4C trail or HWR1 mid-band).",
        "stops":   "Regime-blended: wider in bull, tight in chop.",
        "params":  "ema_trend=100, ema_fast=50, adx_bull=20, adx_chop=18, chop_band=2%",
        "tests":   "6 coins × 2022-2025.",
        "strengths": ["Clean regime taxonomy"],
        "flaws": [
            "0-13 trades per coin over 4 years",
            "V3B/V4C already have implicit regime filters",
            "Over-filtering kills signal count",
        ],
        "lookup_csv": "v11_hunt.csv",
        "lookup_match": ("V11_regime_ensemble", None),
    },
    # ================= V12 REPLACEMENT ENTRIES =================
    {
        "id": "V12A",
        "name": "V12A — Pullback-to-EMA20 Trend",
        "family": "V12 replacement entries",
        "status": "TESTED — LINK/ETH-profitable",
        "one_liner": "Pullback to 20 EMA in a rising 200 EMA trend with RSI 42-62 guard.",
        "entry":   "EMA200 rising + low touched within 0.8 × ATR of EMA20 in last 3 bars + bullish + RSI 42-62.",
        "exit":    "close < EMA50 OR trend turns down.",
        "stops":   "1.5 × ATR SL, multi-TP ladder.",
        "params":  "ema_trend=200, ema_fast=20, pullback_depth_atr=0.8, rsi_min=42, rsi_max=62",
        "tests":   "6 coins × 2022-2025.",
        "strengths": [
            "LINK: 100% WR (n=7), Sharpe 0.91, CAGR +5.8%",
            "ETH: 67% WR, PF 1.34, CAGR +1.4%",
        ],
        "flaws": ["4-14 trades per coin — small sample", "CAGR stays < 6%/yr"],
        "lookup_csv": "v12_hunt.csv",
        "lookup_match": ("V12A_pullback_trend", None),
    },
    {
        "id": "V12B",
        "name": "V12B — Bollinger Squeeze Break",
        "family": "V12 replacement entries",
        "status": "TESTED — SOL/BTC-profitable",
        "one_liner": "After a volatility squeeze, break of upper BB in uptrend.",
        "entry":   "BB width in bottom 35% of last 60 bars (squeeze) + close > upper BB + close > EMA100.",
        "exit":    "close < mid-BB.",
        "stops":   "1.2 × ATR SL, multi-TP ladder.",
        "params":  "bb_len=20, bb_std=2.0, squeeze_pctile=0.35, squeeze_lookback=60",
        "tests":   "6 coins × 2022-2025.",
        "strengths": [
            "SOL: 86% WR (n=7), PF 1.57, CAGR +2.3% (BEST V12 pocket)",
            "BTC: 50% WR, PF 1.16",
            "ADA: 67% WR, PF 1.01",
        ],
        "flaws": ["Fails on LINK/XRP/ETH OOS", "Low CAGR vs trend baseline"],
        "lookup_csv": "v12_hunt.csv",
        "lookup_match": ("V12B_bb_squeeze_break", None),
    },
    {
        "id": "V12C",
        "name": "V12C — Higher-Lows Pattern",
        "family": "V12 replacement entries",
        "status": "FAILED",
        "one_liner": "Two consecutive higher-lows in a trend with ADX > 18.",
        "entry":   "low[t-1]>low[t-2]>low[t-3] AND close > EMA100 AND ADX > 18 AND bullish bar.",
        "exit":    "close < EMA50.",
        "stops":   "1.2 × ATR SL, multi-TP ladder.",
        "params":  "ema_trend=100, adx_min=18",
        "tests":   "6 coins × 2022-2025.",
        "strengths": ["Classic pattern"],
        "flaws": ["Too many false positives — all coins PF < 1"],
        "lookup_csv": "v12_hunt.csv",
        "lookup_match": ("V12C_higher_lows", None),
    },
    {
        "id": "V12D",
        "name": "V12D — NR7 Breakout",
        "family": "V12 replacement entries",
        "status": "FAILED",
        "one_liner": "Narrow-range-7 bar break in uptrend.",
        "entry":   "NR7 bar (smallest range of last 7) in last 3 bars + close > NR7 high + close > EMA100.",
        "exit":    "close < EMA50.",
        "stops":   "1.2 × ATR SL, multi-TP ladder.",
        "params":  "nr_lookback=7, ema_trend=100",
        "tests":   "6 coins × 2022-2025.",
        "strengths": ["Low trade frequency = low fee drag"],
        "flaws": [
            "2-22 trades per coin over 4 years",
            "All coins PF < 1",
        ],
        "lookup_csv": "v12_hunt.csv",
        "lookup_match": ("V12D_nr7_break", None),
    },
    # ================= V14/V15 CROSS-SECTIONAL MOMENTUM =================
    {
        "id": "V14",
        "name": "V14 — Cross-Sectional Momentum (k=2, lb=28d)",
        "family": "V14/V15 cross-sectional momentum",
        "status": "BREAKTHROUGH — first deploy candidate",
        "one_liner": "Weekly rank 9 coins by 28-day return, long top 2, flat when BTC < 100d MA.",
        "entry":   (
            "Every Monday 00:00 UTC 4h bar:\n"
            "   1. Rank 9 coins by (close_t / close_{t-28d}) − 1\n"
            "   2. Take top 2 ranked coins, equal weight (50% each)\n"
            "   3. If BTC < its 100-day MA: FLAT entire portfolio"),
        "exit":    "Weekly rebalance replaces losers; bear filter closes all.",
        "stops":   "No per-trade stops — weekly re-rank is the stop.",
        "params":  "lookback_days=28, top_k=2, rebal_days=7, btc_ma_days=100, leverage=1.0",
        "tests":   "Full 2018-2026 + 11-config variant sweep.",
        "strengths": [
            "CAGR +157.6%, Sharpe 1.60, DD -58%, $10k → $24.4M",
            "2022 bear: −9.5% (market did −70%) — BTC filter worked",
            "Different paradigm from time-series momentum — adds diversification",
        ],
        "flaws": [
            "DD −58% uncomfortable",
            "2021 alt season drives > 50% of full-period CAGR",
            "k=2 means one bad pick = 50% of weekly capital",
        ],
        "lookup_csv": "v15_xsm.csv",
        "lookup_match": (None, None),
    },
    {
        "id": "V15_BALANCED",
        "name": "V15 BALANCED — XSM k=4 lb=14d (CHAMPION)",
        "family": "V14/V15 cross-sectional momentum",
        "status": "DEPLOYED (recommended XSM sleeve)",
        "one_liner": "XSM with 14-day lookback, top 4 coins, weekly rebalance, BTC bear filter.",
        "entry":   (
            "Every Monday:\n"
            "   1. Rank 9 coins by (close_t / close_{t-14d}) − 1\n"
            "   2. Equal-weight long top 4 (25% each)\n"
            "   3. Flat when BTC < 100d MA"),
        "exit":    "Weekly re-rank.",
        "stops":   "Bear filter is the structural stop.",
        "params":  "lookback_days=14, top_k=4, rebal_days=7, btc_ma_days=100",
        "tests":   "Full 2018-2026 + V18 robustness audit (100/100 windows profitable, 72/72 param configs profitable, median Sharpe 1.96).",
        "strengths": [
            "CAGR +158.6%, Sharpe 1.86 (highest single-strategy)",
            "2022: +1.6% (positive in crypto bear)",
            "DD −48% (10pp lower than k=2)",
            "Robust across random windows and parameter variations",
            "Simple — no per-coin tuning needed",
        ],
        "flaws": [
            "Still needs BTC bear filter — if BTC filter fails, DD blows out",
            "Equal weight means winning-coin sizing gains foregone",
            "2018-2020 universe was too small (only 3-6 coins)",
        ],
        "lookup_csv": "v15_xsm.csv",
        "lookup_match": ("V15F_lb14_k4_rb7", None),
    },
    {
        "id": "V15_AGGRESSIVE",
        "name": "V15 AGGRESSIVE — k=3 lb=14d rb=3d",
        "family": "V14/V15 cross-sectional momentum",
        "status": "ALTERNATE (aggressive profile)",
        "one_liner": "Same XSM but top-3 only, rebalance every 3 days for faster regime response.",
        "entry":   "14d lookback, long top 3, rebal 3d.",
        "exit":    "Every 3d rebalance.",
        "stops":   "Bear filter.",
        "params":  "lookback_days=14, top_k=3, rebal_days=3",
        "tests":   "V15 variant sweep.",
        "strengths": [
            "CAGR +177%, Calmar 3.65 (best Calmar overall)",
            "Higher concentration picks up fast movers",
        ],
        "flaws": [
            "2022: −27% (worse than balanced)",
            "More trading → more fees, more slippage risk",
            "Higher concentration risk",
        ],
        "lookup_csv": "v15_xsm.csv",
        "lookup_match": ("V15F_lb14_k3_rb3", None),
    },
    # ================= V16 ML =================
    {
        "id": "V16",
        "name": "V16 — ML-Ranked XSM (GradientBoostingRegressor)",
        "family": "V16 machine learning",
        "status": "FAILED — simple beats smart",
        "one_liner": "Same as V15 but rank by ML-predicted next-7d return instead of past-14d return.",
        "entry":   (
            "At each weekly rebalance:\n"
            "   1. Build features per coin: 7/14/28/56d returns, 28d vol, ADX, RSI, accel, skew\n"
            "   2. Train GradientBoostingRegressor on last 4000 bars of (features → next-7d return)\n"
            "   3. Predict each coin's next-7d return\n"
            "   4. Long top-K predictions"),
        "exit":    "Weekly re-rank.",
        "stops":   "BTC bear filter.",
        "params":  "train_bars=4000, n_estimators=80, max_depth=3, learning_rate=0.05, refit monthly",
        "tests":   "5 configs (k=2/3/4 × rb=3/7 × hz=7/14).",
        "strengths": ["Honest walk-forward — no lookahead"],
        "flaws": [
            "Best ML Sharpe 1.37 vs V15 plain Sharpe 1.86",
            "CAGR 61-80% vs V15 plain 159%",
            "Crypto features are too noisy for tree ensemble at 4h",
            "Monthly refit can't keep pace with regime shifts",
        ],
        "lookup_csv": "v16_ml_rank.csv",
        "lookup_match": (None, None),
    },
    # ================= V17 PAIRS =================
    {
        "id": "V17",
        "name": "V17 — Pairs Trading (Z-Score Mean-Reversion)",
        "family": "V17 statistical arbitrage",
        "status": "RAW EDGE — needs hedged basket to deploy",
        "one_liner": "Long coin A when its log-spread vs coin B drops N sigmas below 28d mean.",
        "entry":   (
            "For each pair (A,B) at each 4h bar:\n"
            "   1. Fit rolling OLS β on log(A) vs log(B) over 56d\n"
            "   2. spread = log(A) − β·log(B)\n"
            "   3. z = (spread − 28d_mean) / 28d_std\n"
            "   4. LONG A when z < −1.5 (A is cheap vs B)"),
        "exit":    "z > 0 (reverted) OR z < −3.5 (stop).",
        "stops":   "z-score stop at −3.5 (spread blew out).",
        "params":  "z_entry=-1.5 to -2.5, z_exit=0.0 or -0.5, z_stop=-3.5, beta_window=336, z_window=168",
        "tests":   "8 pairs × 5 z-thresholds = 40 configs.",
        "strengths": [
            "DOGE/BTC z_in=−1.5: PF 7.85, CAGR +42%, 95 trades",
            "ADA/ETH z_in=−1.5: PF 1.83, CAGR +31%, 292 trades",
            "Raw trade structure has real edge",
        ],
        "flaws": [
            "Drawdowns −85 to −94% on every pair — catastrophic",
            "Structural regime shifts (alt breakouts) break cointegration",
            "Not shippable as long-only; needs hedged basket",
        ],
        "lookup_csv": "v17_pairs.csv",
        "lookup_match": (None, None),
    },
]


# ---------------------------------------------------------------------
def _text_page(pdf, strat: dict, lookup: pd.DataFrame | None):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")

    status_color = {
        "DEPLOYED": "#0a6",
        "CHAMPION": "#0a6",
        "BREAKTHROUGH": "#0a6",
        "BORDERLINE": "#c80",
        "TESTED": "#888",
        "ALTERNATE": "#258",
        "WEAK": "#c80",
        "FAILED": "#c22",
        "RAW": "#c80",
    }
    sc = "#444"
    for k, v in status_color.items():
        if k in strat["status"]:
            sc = v; break

    # Header
    ax.text(0.06, 0.965, strat["name"], fontsize=17, weight="bold", color="#222")
    ax.text(0.06, 0.938, f"Family: {strat['family']}",
            fontsize=10, color="#666")
    ax.text(0.94, 0.94, strat["status"], fontsize=9, ha="right",
            color="white",
            bbox=dict(boxstyle="round,pad=0.35", facecolor=sc, edgecolor="none"))
    ax.axhline(0.918, 0.05, 0.95, color="#ccc", lw=0.7)

    y = 0.895
    def put(key, text, font=9, indent=0.06, bold=False, color="#222", gap=0.018):
        nonlocal y
        if isinstance(text, list):
            for t in text:
                ax.text(indent + 0.02, y, "• " + t, fontsize=font, color=color)
                y -= 0.02
            return
        # Multi-line text block
        lines = text.split("\n") if isinstance(text, str) else [str(text)]
        for i, ln in enumerate(lines):
            weight = "bold" if (bold and i == 0) else "normal"
            ax.text(indent, y, ln, fontsize=font, color=color, weight=weight)
            y -= gap

    ax.text(0.06, y, "One-liner", fontsize=10, weight="bold", color="#258")
    y -= 0.022
    put(None, strat["one_liner"], font=10, color="#222")
    y -= 0.012

    ax.text(0.06, y, "Entry", fontsize=10, weight="bold", color="#258"); y -= 0.022
    put(None, strat["entry"], font=8.5, gap=0.016)
    y -= 0.008

    ax.text(0.06, y, "Exit", fontsize=10, weight="bold", color="#258"); y -= 0.022
    put(None, strat["exit"], font=8.5, gap=0.016)
    y -= 0.008

    ax.text(0.06, y, "Stops / Risk", fontsize=10, weight="bold", color="#258"); y -= 0.022
    put(None, strat["stops"], font=8.5, gap=0.016)
    y -= 0.006

    ax.text(0.06, y, "Parameters", fontsize=10, weight="bold", color="#258"); y -= 0.022
    put(None, strat["params"], font=8.5, gap=0.016)
    y -= 0.006

    ax.text(0.06, y, "Tests performed", fontsize=10, weight="bold", color="#258"); y -= 0.022
    put(None, strat["tests"], font=8.5, gap=0.016)
    y -= 0.006

    # Best result box — pull from lookup CSV
    best = None
    if lookup is not None and strat.get("lookup_match") and strat["lookup_match"][0]:
        match_name, match_tf = strat["lookup_match"]
        cand = lookup.copy()
        for col in ("strategy", "name", "coin"):
            pass
        # name-col guess
        name_col = None
        for c in ("strategy","name"):
            if c in cand.columns: name_col = c; break
        if name_col:
            cand = cand[cand[name_col].astype(str).str.contains(match_name, na=False, case=False)]
        if match_tf and "tf" in cand.columns:
            cand = cand[cand["tf"] == match_tf]
        if "sharpe" in cand.columns:
            cand = cand.sort_values("sharpe", ascending=False)
        if len(cand) > 0:
            best = cand.iloc[0].to_dict()

    # For V14/V15/V16, lookup is direct
    if strat["id"] == "V14" and lookup is not None:
        sub = lookup.copy()
        for q in ["lb= 28d k=2", "lb=28", "28"]:
            if "name" in sub.columns:
                match = sub[sub["name"].astype(str).str.contains("lb= 28d k=2 rb= 7d MOM lev=1.0x \\+BTC_TF", regex=True, na=False)]
                if len(match) > 0: best = match.iloc[0].to_dict(); break
    if strat["id"] == "V15_BALANCED" and lookup is not None:
        for needle in ["V15F_lb14_k4_rb7", "lb14_k4_rb7"]:
            match = lookup[lookup.iloc[:, 0].astype(str).str.contains(needle, na=False)]
            if len(match) > 0: best = match.iloc[0].to_dict(); break
    if strat["id"] == "V15_AGGRESSIVE" and lookup is not None:
        match = lookup[lookup.iloc[:, 0].astype(str).str.contains("V15F_lb14_k3_rb3", na=False)]
        if len(match) > 0: best = match.iloc[0].to_dict()
    if strat["id"] == "V16" and lookup is not None and len(lookup) > 0:
        best = lookup.sort_values("sharpe", ascending=False).iloc[0].to_dict()
    if strat["id"] == "V17" and lookup is not None:
        good = lookup[(lookup["n_trades"] >= 20) & (lookup["final"] > 10000)]
        if len(good) > 0:
            best = good.sort_values("sharpe", ascending=False).iloc[0].to_dict()

    ax.text(0.06, y, "Best result", fontsize=10, weight="bold", color="#258"); y -= 0.022
    if best:
        bits = []
        def g(k, fmt=None, scale=1.0, suffix=""):
            if k not in best or pd.isna(best.get(k)): return None
            v = best[k] * scale
            if fmt: return fmt.format(v) + suffix
            return f"{v:.3f}{suffix}"
        if "coin" in best: bits.append(f"coin {best['coin']}")
        if "pair" in best: bits.append(f"pair {best['pair']}")
        if "name" in best: bits.append(f"cfg {best['name']}")
        wr_val = best.get("wr_overall") if "wr_overall" in best else best.get("wr")
        if wr_val is not None and not pd.isna(wr_val):
            bits.append(f"WR {float(wr_val)*100:.0f}%")
        if "pf" in best and not pd.isna(best.get("pf")): bits.append(f"PF {float(best['pf']):.2f}")
        if "sharpe" in best: bits.append(f"Sharpe {float(best['sharpe']):.2f}")
        if "cagr" in best and not pd.isna(best.get("cagr")): bits.append(f"CAGR {float(best['cagr'])*100:+.1f}%")
        if "dd" in best and not pd.isna(best.get("dd")): bits.append(f"DD {float(best['dd'])*100:+.1f}%")
        if "final" in best and not pd.isna(best.get("final")): bits.append(f"Final ${float(best['final']):,.0f}")
        put(None, "  ·  ".join(bits), font=8.5, indent=0.08)
    else:
        put(None, "(see strategy's dedicated report)", font=8.5, indent=0.08)
    y -= 0.01

    # Split strengths / flaws columns
    half = (0.06, 0.52)
    ax.text(half[0], y, "Strengths", fontsize=10, weight="bold", color="#0a6")
    ax.text(half[1], y, "Flaws", fontsize=10, weight="bold", color="#c22")
    y -= 0.022
    ystart = y
    for s in strat["strengths"][:6]:
        ax.text(half[0] + 0.02, y, "• " + s[:70], fontsize=8.5, color="#060")
        y -= 0.02
    y = ystart
    for f in strat["flaws"][:6]:
        ax.text(half[1] + 0.02, y, "• " + f[:70], fontsize=8.5, color="#700")
        y -= 0.02

    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------
def cover_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.93, "STRATEGY CATALOG", ha="center", fontsize=28, weight="bold")
    ax.text(0.5, 0.89, "Complete description of every strategy tested",
            ha="center", fontsize=12, color="#555")
    ax.text(0.5, 0.86, "2026-04-21  ·  Strategy Lab R&D",
            ha="center", fontsize=10, color="#888")
    ax.axhline(0.84, 0.05, 0.95, color="#ccc", lw=0.7)

    notes = [
        "",
        "Each strategy has its own page with:",
        "",
        "  • One-liner description",
        "  • Entry logic (the exact trigger)",
        "  • Exit logic (signal + stop rules)",
        "  • Stops & risk management",
        "  • Parameters used in the backtest",
        "  • Tests performed (windows, coins, robustness)",
        "  • Best result (coin, win rate, PF, Sharpe, CAGR, DD, final $)",
        "  • Strengths (left column) · Flaws (right column)",
        "",
        "Status legend:",
        "  DEPLOYED / CHAMPION / BREAKTHROUGH   — shipped or imminent",
        "  BORDERLINE / ALTERNATE / WEAK        — partial edge",
        "  TESTED                                — baseline, no shipping decision yet",
        "  FAILED                                — no edge on any coin",
        "  RAW EDGE                              — works but not deployable as-is",
        "",
        "Universe: BTC · ETH · SOL · BNB · XRP · DOGE · LINK · ADA · AVAX (9 coins)",
        "Timeframe: 4h (plus 1h for V13 family)",
        "Fee model: Hyperliquid maker 0.015 %, 0 bps slippage (limit-order optimistic)",
        "Period: 2018-01-01 → 2026-04-01 (8.25 years)",
        "",
        "Sections:",
        "  1. Baseline trend-following (V2B · V3B · V4C · V13A-C)",
        "  2. V7 high-win-rate rule-based family (HWR1-5, 1b, 3b)",
        "  3. V8 novel entries (SuperTrend · HMA · Vol-Donchian)",
        "  4. V9 multi-TP ladder wrappers",
        "  5. V10 orderflow strategies (funding · OI · L/S · liquidations)",
        "  6. V11 regime-switching ensemble",
        "  7. V12 pullback / BB-squeeze / pattern entries",
        "  8. V14/V15 cross-sectional momentum — THE BREAKTHROUGH",
        "  9. V16 ML-ranked XSM (negative finding)",
        " 10. V17 pairs trading (raw edge, needs hedge)",
        "",
        "Final recommended portfolio: 70 % XSM balanced + 30 % Trend baseline",
        "    Sharpe 1.88 · CAGR +148 % · MaxDD −46 % · Final $17.7 M on $10k over 2018-2026.",
    ]
    y = 0.80
    for ln in notes:
        if ln.startswith("Sections:") or ln.startswith("Status legend:") \
           or ln.startswith("Universe") or ln.startswith("Final recommended"):
            ax.text(0.08, y, ln, fontsize=10, weight="bold", color="#258")
        elif ln == "":
            pass
        else:
            ax.text(0.08, y, ln, fontsize=9)
        y -= 0.018
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def summary_table_page(pdf):
    # Master table: every strategy, short status + key metric
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "Summary — all strategies at a glance",
            ha="center", fontsize=17, weight="bold")
    headers = ["ID", "Family", "Status", "Best coin / cfg", "Sharpe", "CAGR", "DD", "WR"]

    # We build rows hand-picked from the STRATEGIES list + known best results
    rows = [
        ["V2B",    "baseline trend",   "DEPLOYED",     "SOL 4h",        "1.35", "+105%", "-52%", "46%"],
        ["V3B",    "baseline trend",   "DEPLOYED",     "ETH 4h",        "1.26", "+56%",  "-34%", "42%"],
        ["V4C",    "baseline trend",   "DEPLOYED",     "BTC 4h",        "1.32", "+40%",  "-29%", "44%"],
        ["V13A",   "1h trend port",    "DEPLOYED",     "ETH 1h",        "0.93", "+19%",  "-23%", "41%"],
        ["V13B",   "1h trend port",    "TESTED",       "-",             "0.30", "+2%",   "-30%", "38%"],
        ["V13C",   "1h trend port",    "TESTED",       "ETH 1h",        "0.71", "+15%",  "-26%", "38%"],
        ["HWR1",   "V7 high-WR",       "DEPLOYED XRP", "XRP 4h",        "0.43", "+6%",   "-19%", "74%"],
        ["HWR2",   "V7 high-WR",       "FAILED",       "-",             "-",    "-",     "-",    "-"],
        ["HWR3",   "V7 high-WR",       "FAILED",       "LINK only",     "0.38", "+3%",   "-15%", "51%"],
        ["HWR1b",  "V7 high-WR",       "TESTED",       "-",             "0.35", "+1%",   "-14%", "55%"],
        ["HWR3b",  "V7 high-WR",       "TESTED",       "LINK",          "0.42", "+2%",   "-12%", "71%"],
        ["HWR4",   "V7 high-WR",       "FAILED",       "-",             "-",    "-",     "-",    "-"],
        ["HWR5",   "V7 high-WR",       "BORDERLINE",   "BTC 4h",        "0.41", "+1%",   "-14%", "79%"],
        ["V8A",    "V8 novel",         "FAILED",       "(0 trades)",    "-",    "-",     "-",    "-"],
        ["V8B",    "V8 novel",         "WEAK",         "XRP",           "0.47", "+4%",   "-11%", "67%"],
        ["V8C",    "V8 novel",         "BORDERLINE",   "ETH",           "0.43", "+4%",   "-16%", "56%"],
        ["V9A",    "V9 multi-TP",      "TESTED",       "BTC",           "0.12", "+0.5%", "-14%", "56%"],
        ["V9E",    "V9 multi-TP",      "TESTED",       "ETH",           "0.60", "+2%",   "-6%",  "75%"],
        ["V10A",   "V10 orderflow",    "FAILED",       "BTC",           "0.12", "+0.5%", "-14%", "56%"],
        ["V10B",   "V10 orderflow",    "FAILED",       "-",             "-",    "-",     "-",    "-"],
        ["V10C",   "V10 orderflow",    "FAILED",       "SOL",           "-0.08","-0.6%", "-11%", "53%"],
        ["V10D",   "V10 orderflow",    "FAILED",       "SOL",           "0.20", "+1%",   "-7%",  "50%"],
        ["V11",    "V11 regime ens",   "FAILED",       "ADA",           "0.55", "+1%",   "-1%",  "0%"],
        ["V12A",   "V12 pullback",     "TESTED",       "LINK",          "0.91", "+6%",   "-6%",  "100%"],
        ["V12B",   "V12 BB squeeze",   "TESTED",       "SOL",           "0.41", "+2%",   "-6%",  "86%"],
        ["V12C",   "V12 higher-lows",  "FAILED",       "-",             "-",    "-",     "-",    "-"],
        ["V12D",   "V12 NR7",          "FAILED",       "-",             "-",    "-",     "-",    "-"],
        ["V14",    "XSM k=2 lb=28d",   "BREAKTHROUGH", "9-coin basket", "1.60", "+158%", "-58%", "-"],
        ["V15 BAL","XSM k=4 lb=14d",   "CHAMPION",     "9-coin basket", "1.86", "+159%", "-48%", "-"],
        ["V15 AGG","XSM k=3 lb=14d rb=3","ALTERNATE",  "9-coin basket", "1.82", "+177%", "-48%", "-"],
        ["V16",    "ML-rank XSM",      "FAILED",       "k=4 rb=3d",     "1.37", "+80%",  "-62%", "-"],
        ["V17",    "pairs trading",    "RAW EDGE",     "DOGE/BTC",      "0.78", "+42%",  "-94%", "47%"],
    ]
    cell_text = [headers] + rows
    tbl = ax.table(cellText=cell_text, loc="center", cellLoc="left",
                   bbox=[0.04, 0.06, 0.92, 0.86])
    tbl.auto_set_font_size(False); tbl.set_fontsize(7.5); tbl.scale(1, 1.15)
    for j in range(len(headers)):
        tbl[(0, j)].set_facecolor("#dee")
        tbl[(0, j)].set_text_props(weight="bold")
    # Color code status column
    status_colors = {
        "DEPLOYED": "#d3f0d5", "CHAMPION": "#b9e8bd", "BREAKTHROUGH": "#b9e8bd",
        "BORDERLINE": "#fff2c2", "ALTERNATE": "#d2e4ff", "WEAK": "#fff2c2",
        "TESTED": "#eeeeee", "FAILED": "#f6c7c7", "RAW EDGE": "#ffd9a8",
    }
    for i, row in enumerate(rows, start=1):
        for key, col in status_colors.items():
            if key in row[2]:
                tbl[(i, 2)].set_facecolor(col); break
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


def verdict_page(pdf):
    fig, ax = plt.subplots(figsize=(11, 8.5)); ax.axis("off")
    ax.text(0.5, 0.96, "Final recommended deployment",
            ha="center", fontsize=18, weight="bold")
    ax.axhline(0.92, 0.05, 0.95, color="#ccc", lw=0.7)
    lines = [
        "Hybrid 70 % XSM (V15 balanced) + 30 % Trend baseline on a single $10,000 Hyperliquid account.",
        "",
        "Sleeve B — XSM MOMENTUM (70 % / $7,000)",
        "    Universe: BTC  ETH  SOL  BNB  XRP  DOGE  LINK  ADA  AVAX  (9 coins)",
        "    Signal:    rank by past-14-day return, weekly (Monday 00:00 UTC)",
        "    Position:  equal-weight long top-4 coins, 1 × leverage",
        "    Bear:      flat (close all) when BTC < its 100-day simple moving average",
        "    Exec:      limit orders on rebalance — maker fee 0.015 %",
        "",
        "Sleeve A — TREND (30 % / $3,000)",
        "    Coins:       BTC · ETH · SOL · LINK · ADA · XRP",
        "    Strategies:  V4C (BTC / SOL / ADA)   V3B (ETH / LINK)   HWR1 (XRP)",
        "    Sizing:      5 % notional per entry × 5 × account leverage",
        "    Stops:       existing ATR-scaled trailing stops per strategy",
        "",
        "Backtest expectation (2018-2026 full period):",
        "    CAGR    +148 %        Sharpe  1.88        MaxDD  -46 %",
        "    Calmar   3.23         Final   $17.7 M (on $10 k start)",
        "",
        "OOS 2022-2025 expectation (re-indexed to $10k start):",
        "    CAGR    +72 %         Sharpe  1.33        MaxDD  -46 %",
        "",
        "Risk guards:",
        "    Kill-switch (both sleeves): pause new entries if combined equity drops > 40 % from ATH.",
        "    Resume: only after BTC closes above its 100-day SMA for >= 1 full week.",
        "    Fat-finger cap: reject any order with notional > 3 × the recommended sizing.",
        "",
        "Validation status:",
        "    V18 robustness audit of V15 balanced champion:",
        "        100 / 100 random 2-year windows were profitable",
        "        98 % of those windows had Sharpe > 0.5,  median Sharpe 1.96",
        "        72 / 72 parameter-epsilon configs were profitable  (Sharpe 1.16 - 1.96)",
        "",
        "Next tactical step: build live_forward_xsm.py (weekly rebalance + BTC filter)",
        "and run alongside the existing live_forward.py for the trend sleeve.",
        "Begin Hyperliquid testnet paper trading once both runners match backtest equity to within 2 %.",
    ]
    y = 0.88
    for ln in lines:
        if ln.startswith("Sleeve") or ln.startswith("Backtest") \
           or ln.startswith("OOS") or ln.startswith("Risk") \
           or ln.startswith("Validation") or ln.startswith("Next") \
           or ln.startswith("Hybrid"):
            ax.text(0.06, y, ln, fontsize=10, weight="bold", color="#258")
        elif ln == "":
            pass
        else:
            ax.text(0.06, y, ln, fontsize=9)
        y -= 0.022
    pdf.savefig(fig, bbox_inches="tight"); plt.close(fig)


# ---------------------------------------------------------------------
def main():
    # Pre-load lookup CSVs
    lookups = {}
    for fname in ["edge_hunt.csv", "hwr_summary.csv", "v8_hunt.csv", "v10_hunt.csv",
                  "v11_hunt.csv", "v12_hunt.csv", "v15_xsm.csv", "v16_ml_rank.csv",
                  "v17_pairs.csv"]:
        p = RES / fname
        lookups[fname] = pd.read_csv(p) if p.exists() else None

    with PdfPages(OUT_LOCAL) as pdf:
        cover_page(pdf)
        summary_table_page(pdf)
        for s in STRATEGIES:
            lookup = lookups.get(s.get("lookup_csv"))
            _text_page(pdf, s, lookup)
        verdict_page(pdf)

    shutil.copy2(OUT_LOCAL, OUT_PUBLIC)
    print(f"Wrote  {OUT_LOCAL}")
    print(f"Copied {OUT_PUBLIC}")


if __name__ == "__main__":
    main()
