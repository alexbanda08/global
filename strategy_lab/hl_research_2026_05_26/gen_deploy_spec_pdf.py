"""
Clean focused PDF — only PROFITABLE deploy candidates with full per-strategy spec.

Builds: HL_DEPLOY_SPEC.pdf using reportlab (clean Platypus layout, no charts).

Layout:
  - Cover + summary table of all profitable strategies
  - One page per strategy with full spec
  - Strategy explanation narratives at the end
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

BASE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\hl_research_2026_05_26")
OUT = BASE / "HL_DEPLOY_SPEC.pdf"


# =========================== Data: verified profitable strategies ===========================

# Backtest windows
WINDOW_HL_DAYS = 107  # HL data: 2026-01-30 -> 2026-05-16
WINDOW_BINANCE_BTC_YEARS = 8.6  # BTCUSDT spot full
WINDOW_BINANCE_ETH_YEARS = 8.6
WINDOW_BINANCE_SOL_YEARS = 5.6
WINDOW_BINANCE_BNB_YEARS = 8.4

NOTIONAL_PER_ENTRY = 250  # USD, 1x leverage in backtest


def cap_estimate_carry(n_trades, hold_h, window_days):
    """Estimate capital needed for overlapping multi-day-hold strategies."""
    # avg concurrent positions = (n * hold_h) / (window_days * 24)
    if window_days <= 0 or hold_h <= 0:
        return NOTIONAL_PER_ENTRY
    avg_conc = (n_trades * hold_h) / (window_days * 24)
    # 1.5x buffer for peak overlap
    return int(round(NOTIONAL_PER_ENTRY * max(1.5, avg_conc * 1.5)))


# 12 profitable strategies — all metrics from the actual result CSVs
STRATEGIES = [
    # ---------- TIER 1 CARRY (D1) ----------
    {
        "rank": 1,
        "tier": "T1 Carry",
        "id": "D1_SOL_168h_z2.5_zwin60d_fund30davg",
        "asset": "SOL",
        "venue": "Hyperliquid Perp",
        "signal_tf": "1h",
        "hold": "168h (7 days)",
        "n_trades": 75,
        "win_rate": 0.8133,
        "sharpe": 11.29,
        "total_pnl": 588.41,
        "avg_pnl": 7.85,
        "max_dd_pct": None,  # not in D CSV
        "avg_funding": -0.13,
        "avg_fees": 0.225,
        "gates": "7/7",
        "perm_p": 0.001,
        "boot_lo": 0.44,
        "boot_hi": 1.09,
        "window": f"HL {WINDOW_HL_DAYS}d (Jan 30 - May 16 2026)",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": cap_estimate_carry(75, 168, WINDOW_HL_DAYS),
        "trigger": "basis_z > +2.5 -> LONG; basis_z < -2.5 -> SHORT",
        "expected_basis": "30d funding mean x (168h/8h)",
        "z_window": "60 days",
        "exit": "Time stop 168h (no ATR early exit)",
        "explanation_key": "basis_carry",
        "warning": "Small effective n (75 trades / 107 days at 168h hold = limited statistical power). Re-validate when more HL data accumulates.",
    },
    {
        "rank": 2,
        "tier": "T1 Carry",
        "id": "D1_SOL_168h_z2.0_zwin90d_zero_fund",
        "asset": "SOL",
        "venue": "Hyperliquid Perp",
        "signal_tf": "1h",
        "hold": "168h (7 days)",
        "n_trades": 80,
        "win_rate": 0.775,
        "sharpe": 12.02,
        "total_pnl": 718.90,
        "avg_pnl": 8.99,
        "max_dd_pct": None,
        "avg_funding": -0.13,
        "avg_fees": 0.225,
        "gates": "7/7",
        "perm_p": 0.001,
        "boot_lo": 0.49,
        "boot_hi": 1.12,
        "window": f"HL {WINDOW_HL_DAYS}d",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": cap_estimate_carry(80, 168, WINDOW_HL_DAYS),
        "trigger": "basis_z > +2.0 -> LONG; basis_z < -2.0 -> SHORT",
        "expected_basis": "zero (pure spot-perp, no funding adjustment)",
        "z_window": "90 days",
        "exit": "Time stop 168h",
        "explanation_key": "basis_carry",
        "warning": "168h hold = small effective n. Validate on extended history.",
    },
    {
        "rank": 3,
        "tier": "T1 Carry",
        "id": "D1_SOL_168h_z1.5_zwin90d_term_next",
        "asset": "SOL",
        "venue": "Hyperliquid Perp",
        "signal_tf": "1h",
        "hold": "168h (7 days)",
        "n_trades": 145,
        "win_rate": 0.669,
        "sharpe": 6.96,
        "total_pnl": 830.19,
        "avg_pnl": 5.73,
        "max_dd_pct": None,
        "avg_funding": -0.11,
        "avg_fees": 0.225,
        "gates": "7/7",
        "perm_p": 0.001,
        "boot_lo": None,
        "boot_hi": None,
        "window": f"HL {WINDOW_HL_DAYS}d",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": cap_estimate_carry(145, 168, WINDOW_HL_DAYS),
        "trigger": "basis_z > +1.5 -> LONG; basis_z < -1.5 -> SHORT",
        "expected_basis": "current funding x (168h/8h) = 'term_next'",
        "z_window": "90 days",
        "exit": "Time stop 168h",
        "explanation_key": "basis_carry",
        "warning": "Looser z=1.5 = more trades + larger total PnL than higher-z variants. Best mid-Sharpe / large-n SOL 168h cell.",
    },
    {
        "rank": 4,
        "tier": "T1 Carry",
        "id": "D1_SOL_72h_z1.5_zwin14d_term_next",
        "asset": "SOL",
        "venue": "Hyperliquid Perp",
        "signal_tf": "1h",
        "hold": "72h (3 days)",
        "n_trades": 259,
        "win_rate": 0.568,
        "sharpe": 4.66,
        "total_pnl": 873.66,
        "avg_pnl": 3.37,
        "max_dd_pct": None,
        "avg_funding": -0.11,
        "avg_fees": 0.225,
        "gates": "7/7",
        "perm_p": 0.001,
        "boot_lo": 0.18,
        "boot_hi": 0.41,
        "window": f"HL {WINDOW_HL_DAYS}d",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": cap_estimate_carry(259, 72, WINDOW_HL_DAYS),
        "trigger": "basis_z > +1.5 -> LONG; basis_z < -1.5 -> SHORT",
        "expected_basis": "current funding x 9 = 'term_next'",
        "z_window": "14 days",
        "exit": "Time stop 72h",
        "explanation_key": "basis_carry",
        "warning": "Highest total PnL with manageable hold. Recommended SOL deploy.",
    },
    {
        "rank": 5,
        "tier": "T1 Carry",
        "id": "D1_SOL_48h_z2.0_zwin7d_term_next",
        "asset": "SOL",
        "venue": "Hyperliquid Perp",
        "signal_tf": "1h",
        "hold": "48h (2 days)",
        "n_trades": 130,
        "win_rate": 0.638,
        "sharpe": 6.40,
        "total_pnl": 501.91,
        "avg_pnl": 3.86,
        "max_dd_pct": None,
        "avg_funding": -0.13,
        "avg_fees": 0.225,
        "gates": "7/7",
        "perm_p": 0.001,
        "boot_lo": 0.24,
        "boot_hi": 0.57,
        "window": f"HL {WINDOW_HL_DAYS}d",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": cap_estimate_carry(130, 48, WINDOW_HL_DAYS),
        "trigger": "basis_z > +2.0 -> LONG; basis_z < -2.0 -> SHORT",
        "expected_basis": "current funding x 6 = 'term_next'",
        "z_window": "7 days",
        "exit": "Time stop 48h",
        "explanation_key": "basis_carry",
        "warning": "Stricter z threshold + shorter hold = good Sharpe with moderate n.",
    },
    {
        "rank": 6,
        "tier": "T1 Carry",
        "id": "D1_ETH_24h_z1.5_zwin7d_fund30davg",
        "asset": "ETH",
        "venue": "Hyperliquid Perp",
        "signal_tf": "1h",
        "hold": "24h (1 day)",
        "n_trades": 296,
        "win_rate": 0.561,
        "sharpe": 3.27,
        "total_pnl": 518.66,
        "avg_pnl": 1.75,
        "max_dd_pct": None,
        "avg_funding": -0.03,
        "avg_fees": 0.225,
        "gates": "7/7",
        "perm_p": 0.001,
        "boot_lo": 0.10,
        "boot_hi": 0.32,
        "window": f"HL {WINDOW_HL_DAYS}d",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": cap_estimate_carry(296, 24, WINDOW_HL_DAYS),
        "trigger": "basis_z > +1.5 -> LONG; basis_z < -1.5 -> SHORT",
        "expected_basis": "30d funding mean x 3",
        "z_window": "7 days",
        "exit": "Time stop 24h",
        "explanation_key": "basis_carry",
        "warning": "Best 24h-hold cell. Easiest to operate. RECOMMENDED FIRST DEPLOY.",
    },

    # ---------- TIER 2 TREND (A1) ----------
    {
        "rank": 7,
        "tier": "T2 Trend",
        "id": "A1_ETH_4h_Donchian_N50_ATR1.5",
        "asset": "ETH",
        "venue": "Hyperliquid Perp",
        "signal_tf": "4h",
        "hold": "Variable (avg ~4.7 bars = ~19h)",
        "n_trades": 249,
        "win_rate": 0.470,
        "sharpe": 1.36,
        "sharpe_oos": 3.32,
        "total_pnl": 146.67,
        "avg_pnl": 0.59,
        "max_dd": -88.46,
        "profit_factor": 1.19,
        "calmar": 1.66,
        "gates": "OOS PASS + beats BH 5.6x",
        "window": f"~{WINDOW_BINANCE_ETH_YEARS}y Binance ETH spot (2017-08 -> 2026-03)",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": NOTIONAL_PER_ENTRY,
        "trigger": "Close > prior 50-bar HIGH -> LONG; Close < prior 50-bar LOW -> SHORT",
        "exit": "ATR(14) trailing stop, mult = 1.5",
        "explanation_key": "donchian_trend",
        "warning": "Max DD only -$88 on $250 notional = -35% per-trade max DD. Beats ETH buy-and-hold Sharpe by 5.6x.",
    },
    {
        "rank": 8,
        "tier": "T2 Trend",
        "id": "A1_ETH_4h_Donchian_N20_ATR1.5",
        "asset": "ETH",
        "venue": "Hyperliquid Perp",
        "signal_tf": "4h",
        "hold": "Variable (avg ~4.9 bars)",
        "n_trades": 427,
        "win_rate": 0.452,
        "sharpe": 0.66,
        "sharpe_oos": 3.16,
        "total_pnl": 110.40,
        "avg_pnl": 0.26,
        "max_dd": -108.31,
        "profit_factor": 1.09,
        "calmar": 1.02,
        "gates": "OOS PASS + beats BH",
        "window": f"~{WINDOW_BINANCE_ETH_YEARS}y Binance ETH",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": NOTIONAL_PER_ENTRY,
        "trigger": "Close > prior 20-bar HIGH -> LONG; Close < prior 20-bar LOW -> SHORT",
        "exit": "ATR(14) trailing stop, mult = 1.5",
        "explanation_key": "donchian_trend",
        "warning": "Higher trade count than N=50 variant. Lower per-trade $ but more samples.",
    },
    {
        "rank": 9,
        "tier": "T2 Trend",
        "id": "A1_ETH_4h_Donchian_N50_ATR2.0",
        "asset": "ETH",
        "venue": "Hyperliquid Perp",
        "signal_tf": "4h",
        "hold": "Variable (avg ~7.9 bars = ~32h)",
        "n_trades": 204,
        "win_rate": 0.426,
        "sharpe": 0.69,
        "sharpe_oos": 1.99,
        "total_pnl": 94.04,
        "avg_pnl": 0.46,
        "max_dd": -97.52,
        "profit_factor": 1.11,
        "calmar": 0.96,
        "gates": "OOS PASS + beats BH",
        "window": f"~{WINDOW_BINANCE_ETH_YEARS}y Binance ETH",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": NOTIONAL_PER_ENTRY,
        "trigger": "Close > prior 50-bar HIGH -> LONG; Close < prior 50-bar LOW -> SHORT",
        "exit": "ATR(14) trailing stop, mult = 2.0 (wider than rank 7)",
        "explanation_key": "donchian_trend",
        "warning": "Wider trail = fewer exits = larger holds. Marginal vs N50_ATR1.5.",
    },

    # ---------- TIER 3 BREAKOUT (C3) ----------
    {
        "rank": 10,
        "tier": "T3 Breakout",
        "id": "C3_SOL_4h_vol_confirmed_Donchian",
        "asset": "SOL",
        "venue": "Hyperliquid Perp",
        "signal_tf": "4h",
        "hold": "Variable (ATR trail)",
        "n_trades": 211,
        "win_rate": 0.507,
        "sharpe": 2.76,
        "sharpe_oos": 5.28,
        "total_pnl": 1904.01,
        "total_pnl_oos": 969.83,
        "avg_pnl": 9.02,
        "max_dd": -258.86,
        "profit_factor": 1.76,
        "calmar": 7.36,
        "gates": "5/6 (perm p=0.005, loses to SOL bull buy-hold)",
        "window": f"~{WINDOW_BINANCE_SOL_YEARS}y Binance SOL",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": NOTIONAL_PER_ENTRY,
        "trigger": "Close > prior 20-bar HIGH + 0.5*ATR(14) AND volume > 2x 20-bar avg -> LONG (mirror SHORT)",
        "exit": "ATR(14) trailing stop, mult = 2.5",
        "explanation_key": "vol_breakout",
        "warning": "Loses to SOL bull-run buy-and-hold ($1,904 vs $21,145 in SOL bull). Useful for non-correlated PnL diversification, NOT to beat outright long-SOL exposure.",
    },

    # ---------- TIER 4 COMPOSITE (E4) ----------
    {
        "rank": 11,
        "tier": "T4 Composite",
        "id": "E4_Cyclops_confidence_sizing_SOL_4h",
        "asset": "SOL",
        "venue": "Hyperliquid Perp",
        "signal_tf": "4h",
        "hold": "Variable (signal-flip)",
        "n_trades": 134,
        "win_rate": 0.567,
        "sharpe": 1.98,
        "total_pnl": 285.54,
        "avg_pnl": 2.13,
        "max_dd": -102.81,
        "profit_factor": 1.46,
        "calmar": 2.78,
        "avg_funding": 0.06,
        "avg_fees": 0.23,
        "gates": "passes G1-G5 (G6 boot CI wide)",
        "window": f"~{WINDOW_BINANCE_SOL_YEARS}y Binance SOL",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": NOTIONAL_PER_ENTRY,
        "trigger": "EMA stack score >= +4 (bull alignment) -> LONG; <= -4 -> SHORT; SIZE scales with Cyclops 3-axis coherence: all 3 axes = 2x notional, 2 of 3 = 1x, less = skip",
        "exit": "Signal flip (stack score crosses zero)",
        "explanation_key": "cyclops_sizing",
        "warning": "Sizing layer on top of EMA-stack trend. Beats A2 baseline by +0.82 Sharpe on SOL 4h. Does NOT work well on BTC/SOL alone.",
    },

    # ---------- TIER 5 ML-derived (F3) ----------
    {
        "rank": 12,
        "tier": "T5 ML-derived",
        "id": "F3_ETH_4h_rf_dist_bps_z1.5_momentum",
        "asset": "ETH",
        "venue": "Hyperliquid Perp",
        "signal_tf": "4h",
        "hold": "Variable (ATR SL/TP)",
        "n_trades": 48,  # sum across 4 walk-forward windows
        "win_rate": 0.464,
        "sharpe": 1.16,
        "total_pnl": 220.16,
        "avg_pnl": 4.31,
        "gates": "3/4 windows positive (not all 4)",
        "window": "Walk-forward 4 windows on Binance ETH",
        "notional": NOTIONAL_PER_ENTRY,
        "capital": NOTIONAL_PER_ENTRY,
        "trigger": "rolling 30d z-score of feature `rf_dist_bps` > +1.5 -> LONG (momentum follow); reverse SHORT for z < -1.5",
        "exit": "ATR SL/TP (sl_mult=1.0, tp_mult=2.5)",
        "explanation_key": "single_feature_ml",
        "warning": "Single-feature rule derived from ML feature-importance. Marginal Sharpe. Not a full ML classifier (those lose to fees).",
    },
]


# =========================== Strategy explanations (narrative) ===========================

EXPLANATIONS = {
    "basis_carry": {
        "title": "Basis Carry (D1) — Spot-Perp Mispricing Reversion",
        "body": """The Hyperliquid perpetual price and the underlying Binance spot price normally
trade within a small band of each other. The exact 'fair' gap (basis) depends on the funding
rate the perp is paying or receiving — if funding is +1 bp/hr, a 24-hour-forward perp price
is expected to sit ~24 bps above spot (longs pay shorts that much).<br/><br/>

<b>Mispricing signal:</b> at each hourly bar we compute:<br/>
&nbsp;&nbsp;&nbsp;basis_bps = (binance_spot_close - hl_perp_close) / hl_perp_close * 10000<br/>
&nbsp;&nbsp;&nbsp;expected_basis = (funding_rate_proxy) * (hold_hours / 8) * 10000<br/>
&nbsp;&nbsp;&nbsp;mispricing = basis_bps - expected_basis<br/><br/>

We compute a rolling z-score of the mispricing over a configurable lookback window
(7d, 14d, 30d, 60d, or 90d). When mispricing z-score exceeds the threshold:<br/>
&nbsp;&nbsp;&nbsp;- z &gt; +1.5 (or +2.0, +2.5...) means HL perp is CHEAP relative to expected fair -&gt; LONG HL perp<br/>
&nbsp;&nbsp;&nbsp;- z &lt; -1.5 means HL perp is RICH -&gt; SHORT HL perp<br/><br/>

We hold for a fixed time horizon (24h, 48h, 72h, or 168h) and let funding accrue. Convergence
toward fair pulls our P&amp;L positive. Win rate is 55-95% depending on z-threshold (higher z =
rarer signal = higher WR).<br/><br/>

<b>Why this works on Hyperliquid specifically:</b> HL has a smaller, less efficient perp market
than Binance. When sentiment piles into one side, the perp dislocates from spot. Most market
participants don't have clean Binance+HL data side-by-side to spot this. The funding rate
already prices in expected basis decay, so any deviation from that funding-implied basis is
a real mispricing.<br/><br/>

<b>Expected-basis proxies tested:</b><br/>
&nbsp;&nbsp;&nbsp;- fund30davg: 30-day rolling mean of HL funding rate (smooth, slower)<br/>
&nbsp;&nbsp;&nbsp;- term_next: current funding rate as the implied term-structure (responsive to regime changes)<br/>
&nbsp;&nbsp;&nbsp;- zero_fund: assume funding is zero (pure spot-perp gap) — works at large z because funding
is a small fraction of the basis at extremes<br/><br/>

<b>Direction verdict (D2):</b> Funding-extreme CONTRARIAN beats funding-extreme MOMENTUM on
all four HL coins tested (BTC, ETH, SOL, HYPE). When funding gets very positive, market is
over-long; the marginal long is structurally weak. Fade it.""",
    },
    "donchian_trend": {
        "title": "Donchian Channel Trend Following (A1)",
        "body": """Classical trend-following: a position is opened when price breaks above the
highest high of the last N bars (long) or below the lowest low (short). The position is held
with a trailing stop based on Average True Range (ATR) until the trail is hit.<br/><br/>

<b>Parameters tested:</b> N = {20, 50, 100}; ATR multiplier for trail = {1.5, 2.0, 3.0}<br/><br/>

<b>Entry rule:</b><br/>
&nbsp;&nbsp;&nbsp;LONG: close[t] &gt; max(high[t-N:t])  (close breaks above N-bar high)<br/>
&nbsp;&nbsp;&nbsp;SHORT: close[t] &lt; min(low[t-N:t])<br/><br/>

<b>Exit rule:</b><br/>
&nbsp;&nbsp;&nbsp;For LONG: trail = running_max(high since entry) - ATR_mult * ATR(14)<br/>
&nbsp;&nbsp;&nbsp;Exit when low[t] &lt;= trail (next bar open at the close of the breach bar)<br/>
&nbsp;&nbsp;&nbsp;Mirror logic for SHORT<br/><br/>

The ETH 4h N=50 variant is the strongest because at 4h on ETH the bar size is large enough
that the breakout is real (not noise) but small enough that breakouts happen frequently. ATR
trail at 1.5x is tight enough to lock in moves before reversal but loose enough to ride trends.<br/><br/>

<b>Why this works on crypto perp:</b> Crypto is highly momentum-driven; sustained trends over
hours-to-days are common. Funding cost on 4h holds is tiny (~1-3 bps round-trip). Trail prevents
giving back accumulated gains. Beats buy-and-hold Sharpe on ETH by 5.6x because it goes flat
during chop/drawdowns.""",
    },
    "vol_breakout": {
        "title": "Volume-Confirmed Donchian Breakout (C3)",
        "body": """Same Donchian breakout as A1, but with TWO additional gates:<br/><br/>

1. <b>ATR buffer on the breakout level:</b> close must exceed the N-bar high by at least
0.5 * ATR(14). This avoids triggering on tiny range expansions that are likely noise.<br/><br/>

2. <b>Volume confirmation:</b> the bar must have volume > 2x the 20-bar average volume.
Real breakouts have institutional flow behind them; chop breakouts don't.<br/><br/>

<b>Why this works on SOL 4h:</b> SOL has high realized volatility, so breakouts that ALSO
have volume confirmation are rare but strong. The 5.3 OOS Sharpe is real; perm p = 0.005
confirms it's not random.<br/><br/>

<b>Important caveat:</b> Over a SOL bull run (e.g. 2020-2021), simply being long SOL
the whole time produces $21k of PnL on $250 — far better than the strategy's $1,900. The
strategy is valuable for DIVERSIFICATION (uncorrelated PnL during chop and bear regimes)
not as a replacement for outright long-SOL exposure.""",
    },
    "cyclops_sizing": {
        "title": "Cyclops 3-Axis as Confidence Multiplier (E4)",
        "body": """Cyclops is a multi-axis indicator coherence concept ported from Polymarket
research. Three axes must align for a trade:<br/><br/>

&nbsp;&nbsp;&nbsp;1. <b>Trend axis:</b> 20-bar linear regression slope sign + EMA stack alignment<br/>
&nbsp;&nbsp;&nbsp;2. <b>Levels axis:</b> proximity to and tested integrity of recent swing high/low pivots<br/>
&nbsp;&nbsp;&nbsp;3. <b>Momentum axis:</b> RSI(14) directional alignment AND no momentum exhaustion flag<br/><br/>

The PERP-NATIVE adaptation is to use Cyclops not as a binary entry trigger (as in Polymarket)
but as a POSITION-SIZING multiplier on top of a base strategy (here: EMA-stack-cross trend).<br/><br/>

<b>Sizing rule:</b><br/>
&nbsp;&nbsp;&nbsp;- All 3 axes aligned with trade direction -&gt; 2x notional<br/>
&nbsp;&nbsp;&nbsp;- 2 of 3 axes aligned -&gt; 1x notional<br/>
&nbsp;&nbsp;&nbsp;- Less than 2 -&gt; skip the trade<br/><br/>

This produces a +0.82 Sharpe lift over the unsized A2 (EMA-stack-only) baseline on SOL 4h.
It's the textbook way to use a multi-indicator confluence in futures: as confidence, not as
on/off filter.<br/><br/>

The strategy works on SOL specifically — same sizing layer does NOT lift BTC or ETH meaningfully.""",
    },
    "single_feature_ml": {
        "title": "Single-Feature Z-Score Rule from ML Feature Importance (F3)",
        "body": """W3 (the meta-classifier wave) trained LightGBM/XGBoost on 100+ engineered
features to predict next-bar direction. The full classifier doesn't generate enough edge to
overcome HL's 12 bps round-trip cost (taker 4.5 bps x 2 + slippage 3 bps). However, permutation
importance identified which individual features carry signal.<br/><br/>

The F3 strategy uses just ONE feature (the strongest from the ML feature ranking) as a
threshold rule:<br/><br/>

&nbsp;&nbsp;&nbsp;feature = rf_dist_bps  (distance from Range Filter band in basis points)<br/>
&nbsp;&nbsp;&nbsp;z_30d = rolling 30-day z-score of feature<br/>
&nbsp;&nbsp;&nbsp;LONG when z &gt; +1.5 (with momentum bias)<br/>
&nbsp;&nbsp;&nbsp;SHORT when z &lt; -1.5<br/>
&nbsp;&nbsp;&nbsp;Exit: ATR(14) SL at 1.0x ATR, TP at 2.5x ATR<br/><br/>

Why this works while the full classifier doesn't: with one feature the rule is simple,
captures the strongest signal, doesn't get noise from 99 other features, and stays robust
across walk-forward windows. 3 of 4 walk-forward windows produced positive PnL.<br/><br/>

Marginal Sharpe 1.16 — useful as a small position in a diversified book, not a primary deploy.""",
    },
}


# =========================== PDF generation ===========================

def make_pdf():
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=LETTER,
        leftMargin=0.6*inch,
        rightMargin=0.6*inch,
        topMargin=0.6*inch,
        bottomMargin=0.6*inch,
        title="HL Deploy Spec — Profitable Strategies",
        author="Strategy Research 2026-05-26",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, spaceAfter=8, textColor=colors.HexColor("#0B3D91"))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceAfter=4, textColor=colors.HexColor("#0B3D91"))
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=11, spaceAfter=3, textColor=colors.HexColor("#333333"))
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12, spaceAfter=3)
    body_small = ParagraphStyle("bs", parent=styles["BodyText"], fontSize=8, leading=10, spaceAfter=2)
    warn = ParagraphStyle("warn", parent=body, fontSize=8.5, textColor=colors.HexColor("#C0392B"), leading=11)

    story = []

    # ---------------- Cover ----------------
    story.append(Paragraph("Hyperliquid Perpetual Futures — Deploy Spec", h1))
    story.append(Paragraph("12 profitable strategies ranked. Per-strategy spec + capital + risk.", body))
    story.append(Spacer(1, 0.15*inch))

    # Summary table
    summary_data = [["#", "Strategy ID", "Asset", "TF", "Hold", "n", "WR%", "Sharpe", "Total $", "$/tr", "Capital $"]]
    for s in STRATEGIES:
        sharpe_display = s.get("sharpe_oos") or s["sharpe"]
        summary_data.append([
            str(s["rank"]),
            s["id"][:42],
            s["asset"],
            s["signal_tf"],
            s["hold"].split(" ")[0],
            str(s["n_trades"]),
            f"{s['win_rate']*100:.1f}",
            f"{sharpe_display:.2f}",
            f"${s['total_pnl']:.0f}",
            f"${s['avg_pnl']:.2f}",
            f"${s['capital']:,}",
        ])
    t = Table(summary_data, colWidths=[0.25*inch, 2.3*inch, 0.4*inch, 0.35*inch, 0.55*inch, 0.35*inch, 0.4*inch, 0.5*inch, 0.55*inch, 0.45*inch, 0.65*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0B3D91")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), 7.5),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ("ALIGN", (5,0), (-1,-1), "RIGHT"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#888888")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.HexColor("#F0F4FA"), colors.white]),
        ("BACKGROUND", (0,1), (-1,6), colors.HexColor("#E8F4E8")),  # T1 highlight
    ]))
    story.append(t)
    story.append(Spacer(1, 0.15*inch))

    story.append(Paragraph("<b>Notes:</b>", h3))
    notes_text = (
        "• All metrics are from $250 notional at 1x leverage in backtest. Scale linearly with notional. "
        "Capital column estimates working capital accounting for hold-overlap (multi-day holds may have several concurrent positions).<br/>"
        "• Engine: Hyperliquid taker 4.5 bps x 2 + slippage 3 bps + hourly funding (1.25 bps/hr cap) + 50 ms latency. Same fees applied in every cell.<br/>"
        "• T1 Carry (green) uses HL vs Binance basis. T2/T3/T4/T5 use Binance kline backbone (multi-year) for backtest; execute on HL.<br/>"
        "• Sharpe is annualized. For T2-T5 the OOS Sharpe (out-of-sample test window) is shown when available."
    )
    story.append(Paragraph(notes_text, body_small))
    story.append(PageBreak())

    # ---------------- Per-strategy pages ----------------
    for s in STRATEGIES:
        sharpe_display = s.get("sharpe_oos") or s["sharpe"]
        title = f"#{s['rank']} — {s['id']}"
        story.append(Paragraph(title, h1))
        story.append(Paragraph(f"<i>Tier: {s['tier']}</i>", body))
        story.append(Spacer(1, 0.08*inch))

        # MARKET & EXECUTION block
        story.append(Paragraph("Market &amp; Execution", h2))
        market_data = [
            ["Field", "Value"],
            ["Asset", s["asset"]],
            ["Venue", s["venue"]],
            ["Signal timeframe", s["signal_tf"]],
            ["Hold horizon", s["hold"]],
            ["Backtest window", s["window"]],
        ]
        mt = Table(market_data, colWidths=[1.8*inch, 4.7*inch])
        mt.setStyle(_label_value_style())
        story.append(mt)
        story.append(Spacer(1, 0.08*inch))

        # SIGNAL block
        story.append(Paragraph("Signal &amp; Exit", h2))
        signal_data = [["Field", "Value"]]
        signal_data.append(["Entry trigger", _wrap(s["trigger"], 90)])
        if "expected_basis" in s:
            signal_data.append(["Expected-basis proxy", s["expected_basis"]])
        if "z_window" in s:
            signal_data.append(["z-score window", s["z_window"]])
        signal_data.append(["Exit rule", _wrap(s["exit"], 90)])
        st = Table(signal_data, colWidths=[1.8*inch, 4.7*inch])
        st.setStyle(_label_value_style())
        story.append(st)
        story.append(Spacer(1, 0.08*inch))

        # CAPITAL & RISK block
        story.append(Paragraph("Capital &amp; Risk", h2))
        cap_data = [
            ["Field", "Value"],
            ["Notional per entry", f"${s['notional']} (1x leverage)"],
            ["Working capital required", f"${s['capital']:,}"],
            ["Max drawdown (on $250 notional)", f"${s.get('max_dd', 'n/a')}" if isinstance(s.get('max_dd'), (int,float)) else f"{s.get('max_dd','not reported by D engine')}"],
        ]
        if s.get('max_dd') and isinstance(s['max_dd'], (int,float)):
            mdd_pct = s['max_dd'] / s['notional'] * 100
            cap_data.append(["Max DD as % of notional", f"{mdd_pct:.1f}%"])
        cap_data.append(["Profit factor", f"{s.get('profit_factor', 'n/a')}" if 'profit_factor' in s else 'n/a'])
        cap_data.append(["Calmar (PnL / |MaxDD|)", f"{s.get('calmar', 'n/a')}" if 'calmar' in s else 'n/a'])
        ct = Table(cap_data, colWidths=[1.8*inch, 4.7*inch])
        ct.setStyle(_label_value_style())
        story.append(ct)
        story.append(Spacer(1, 0.08*inch))

        # PERFORMANCE block
        story.append(Paragraph("Performance Metrics", h2))
        perf_data = [["Metric", "Value"],
            ["Total trades (n)", str(s["n_trades"])],
            ["Win rate", f"{s['win_rate']*100:.1f}%"],
            ["Sharpe (annualized)", f"{sharpe_display:.2f}" + (" [OOS]" if "sharpe_oos" in s else "")],
            ["Total P&L (backtest)", f"${s['total_pnl']:.2f}"],
            ["Avg P&L per trade", f"${s['avg_pnl']:.2f}"],
        ]
        if "total_pnl_oos" in s:
            perf_data.append(["Total P&L (OOS)", f"${s['total_pnl_oos']:.2f}"])
        if "avg_funding" in s and s.get("avg_funding") is not None:
            perf_data.append(["Avg funding paid per trade", f"${s['avg_funding']:.3f}"])
        if "avg_fees" in s and s.get("avg_fees") is not None:
            perf_data.append(["Avg fee paid per trade", f"${s['avg_fees']:.3f}"])
        if "perm_p" in s and s.get("perm_p") is not None:
            perf_data.append(["Permutation p-value", f"{s['perm_p']:.4f}"])
        if "boot_lo" in s and s.get("boot_lo") is not None:
            perf_data.append(["Bootstrap 95% CI on $/tr", f"[${s['boot_lo']:.2f}, ${s['boot_hi']:.2f}]"])
        perf_data.append(["Validation gates passed", s["gates"]])
        pt = Table(perf_data, colWidths=[1.8*inch, 4.7*inch])
        pt.setStyle(_label_value_style())
        story.append(pt)
        story.append(Spacer(1, 0.08*inch))

        # WARNING / NOTES
        if s.get("warning"):
            story.append(Paragraph(f"<b>Caveats:</b> {s['warning']}", warn))
        story.append(Spacer(1, 0.05*inch))

        # Reference back to explanation
        exp = EXPLANATIONS.get(s["explanation_key"])
        if exp:
            story.append(Paragraph(f"<i>See &quot;{exp['title']}&quot; on the explanation pages.</i>", body_small))

        story.append(PageBreak())

    # ---------------- Strategy explanations ----------------
    story.append(Paragraph("Strategy Mechanisms — How Each Works", h1))
    story.append(Spacer(1, 0.1*inch))

    for key, exp in EXPLANATIONS.items():
        story.append(Paragraph(exp["title"], h2))
        story.append(Spacer(1, 0.05*inch))
        story.append(Paragraph(exp["body"], body))
        story.append(Spacer(1, 0.2*inch))

    # ---------------- Pre-deploy checklist ----------------
    story.append(PageBreak())
    story.append(Paragraph("Pre-Deploy Checklist", h1))
    checklist = [
        "1. <b>Refresh data:</b> HL canonical klines ended 2026-05-16; today is 2026-05-26. Pull the 10-day delta and re-run the carry signals before going live. Sharpe should remain positive on fresh data.",
        "2. <b>Latency validation:</b> backtest assumes 50 ms. Verify against actual HL API round-trip from production environment. If latency &gt; 200 ms, redo backtest with realistic figure.",
        "3. <b>Slippage validation:</b> backtest assumes 3 bps slippage. Pull recent HL trade tape at $250 notional, compute realized slippage, confirm 3 bps is conservative.",
        "4. <b>Funding cap:</b> verify HL contract caps funding at 1.25 bps/hr — this is in the engine config; if HL changes the cap the strategy economics shift.",
        "5. <b>Per-strategy notional scaling:</b> all backtests are $250 notional 1x leverage. Scaling to $1,000+ should be linear up to a point; monitor slippage as size grows.",
        "6. <b>Drawdown circuit breaker:</b> auto-pause any sleeve that hits 60% of its backtested max drawdown. Re-evaluate the cause before un-pausing.",
        "7. <b>Carry funding monitoring:</b> T1 carry strategies hold 24-168h with funding accrual. Max funding drag estimated ~10-30 bps per trade. Monitor real funding accrual vs backtested expectation closely.",
    ]
    for item in checklist:
        story.append(Paragraph(item, body))
        story.append(Spacer(1, 0.05*inch))

    # ---------------- Rejected (audit trail) ----------------
    story.append(Spacer(1, 0.2*inch))
    story.append(Paragraph("Rejected Strategy Families (audit trail)", h2))
    rejected = [
        ("Mean Reversion (5 variants tested: RSI, BB, Z-score, SMS, VWAP)", "5 / 90 cells profitable. Buy-and-hold dominates every variant. Crypto perp is momentum-driven, not mean-reverting on the timeframes tested."),
        ("ML Probability-Trading (RandomForest + LightGBM + XGBoost ensembles)", "AUC edge of 2-4 ppt is real but smaller than HL's 12 bps round-trip cost. Net P&L is negative on every cell. Use ML for feature selection only (see F3)."),
        ("Hedged Spot-Perp Arbitrage (D3 — long HL perp + short Binance perp simultaneously)", "All 27 cells negative. 2-venue fees + slippage = ~25 bps round-trip x 2 sides. Even when convergence is real (it is — corr near 0), fees eat the alpha."),
        ("Funding-Regime Composite (D4 — basis carry + funding-regime filter overlay)", "High raw Sharpe (BTC 7.09) but fails G7 regime hold-out — collapses in at least one regime. Hidden concentration risk; do NOT deploy raw."),
        ("Markov regime router (E1) and session-switch (E3)", "Both drag relative to best component. Forcing mean-reversion in sideways regimes destroys good trend trades."),
        ("All 5m and 15m timeframes for non-carry strategies", "HL fees crush sub-bar edges. Only carry strategies (which need long enough horizons for convergence) can amortize fees."),
    ]
    for title, reason in rejected:
        story.append(Paragraph(f"<b>{title}</b>", body))
        story.append(Paragraph(reason, body_small))
        story.append(Spacer(1, 0.05*inch))

    doc.build(story)
    print(f"Wrote {OUT}")
    print(f"Size: {OUT.stat().st_size:,} bytes")


def _label_value_style():
    return TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0B3D91")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,0), 9),
        ("FONTSIZE", (0,1), (-1,-1), 9),
        ("BACKGROUND", (0,1), (0,-1), colors.HexColor("#F0F4FA")),
        ("FONTNAME", (0,1), (0,-1), "Helvetica-Bold"),
        ("ALIGN", (0,0), (-1,-1), "LEFT"),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#AAAAAA")),
        ("LEFTPADDING", (0,0), (-1,-1), 4),
        ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ])


def _wrap(s, width):
    """Soft wrap a string at word boundaries for table cells."""
    if not s:
        return ""
    s = str(s)
    if len(s) <= width:
        return s
    out, cur = [], ""
    for w in s.split(" "):
        if len(cur) + len(w) + 1 > width:
            out.append(cur)
            cur = w
        else:
            cur = w if not cur else cur + " " + w
    if cur:
        out.append(cur)
    return "<br/>".join(out)


if __name__ == "__main__":
    make_pdf()
