"""
V37 — Claude as Trader (LLM Regime Router).

Claude (or any LLM, via the provider abstraction) sees recent OHLCV +
indicators and emits a structured Decision that picks one of our existing
tested signal families. Execution is `simulate()` from run_v16_1h_hunt.py
(next-bar-open fills, ATR-based TP/SL/trail, Hyperliquid perp cost model).

Design doc:    strategy_lab/reports/V37_CLAUDE_TRADER_DESIGN.md
System prompt: strategy_lab/prompts/claude_trader_system.md
Providers:     strategy_lab/v37_providers.py
                  - ClaudeCLIProvider     (Max / Pro subscription, $0)
                  - AnthropicAPIProvider  (token-billed, Batch API)
                  - OpenRouterProvider    (GLM, Kimi, DeepSeek, Sonnet, ...)

This module owns the schema, snapshot builder, signal dispatch, and decision
cache. The actual LLM call is delegated to a provider (see v37_providers.py).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

# ─── Paths ──────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent
PROMPT_PATH = BASE / "prompts" / "claude_trader_system.md"
RESULTS_DIR = BASE / "results" / "v37"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ─── Tuning knobs ───────────────────────────────────────────────────
LOOKBACK_BARS = 200                 # bars of history shown to the LLM
COMPACT_BARS = 50                   # how many rendered in the text table
# Decision cadence — chosen per provider in the runner.
#   6  bars on 4h = daily
#  42  bars on 4h = weekly  (sane default for Max-subscription mode)
DECISION_CADENCE_BARS = 42


# ─── Decision schema ────────────────────────────────────────────────
class Decision(BaseModel):
    """Validated output of the Claude trader. Matches the system prompt schema."""
    regime: Literal["trend_up", "trend_down", "range", "high_vol", "transition"]
    strategy: Literal["BBBreak_LS", "HTF_Donchian", "CCI_Rev", "Flat"]
    direction: Literal["long", "short", "both", "none"]
    size_mult: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=300)


# ─── Snapshot builder (look-ahead safe) ─────────────────────────────
def _compact_ohlcv(df: pd.DataFrame, n: int = COMPACT_BARS) -> str:
    """
    Render the last `n` bars as a compact text table.
    Close price is additionally rendered as a percentile rank (0-100)
    to mask any memorized patterns the model may have on literal prices.
    """
    d = df.tail(n).copy()
    rank = df["close"].rank(pct=True) * 100.0   # rank across the FULL history shown
    d["close_pct"] = rank.reindex(d.index)
    rows = []
    for ts, r in d.iterrows():
        rows.append(
            f"{ts.strftime('%Y-%m-%d %H:%M')}  "
            f"O={r['open']:.4f} H={r['high']:.4f} L={r['low']:.4f} "
            f"C={r['close']:.4f} V={r.get('volume', float('nan')):.0f} "
            f"cp={r['close_pct']:.0f}"
        )
    return "\n".join(rows)


def _compute_indicators(df: pd.DataFrame) -> dict:
    """
    Indicator snapshot for the latest bar using only past bars.
    No look-ahead — everything here is closed-bar arithmetic.
    Uses lightweight pandas ops to avoid an extra dependency.
    """
    c, h, low = df["close"], df["high"], df["low"]
    rets = c.pct_change()

    # EMAs
    ema50 = c.ewm(span=50, adjust=False).mean()
    ema200 = c.ewm(span=200, adjust=False).mean()
    ema50_slope = (ema50.iloc[-1] / ema50.iloc[-10] - 1.0) * 100.0 if len(df) > 10 else 0.0

    # ATR (Wilder smoothed, period 14) — simple implementation
    tr = pd.concat([(h - low),
                    (h - c.shift(1)).abs(),
                    (low - c.shift(1)).abs()], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    atr_pct = float(atr14 / c.iloc[-1] * 100.0) if c.iloc[-1] else float("nan")

    # ADX — approximate via +DM/-DM smoothed
    up_move = h.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)).astype(float) * up_move.clip(lower=0)
    minus_dm = ((down_move > up_move) & (down_move > 0)).astype(float) * down_move.clip(lower=0)
    atr_s = tr.ewm(alpha=1 / 14, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_s.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / atr_s.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = float(dx.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])

    # RSI 14
    gain = rets.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    lossr = (-rets.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / lossr.replace(0, np.nan)
    rsi = float(100 - 100 / (1 + rs.iloc[-1])) if len(df) > 14 else float("nan")

    # Realized vol (last 30 trading-days proxy on 4h bars)
    vol_window = min(len(rets) - 1, 30 * 6)
    vol30 = float(rets.tail(vol_window).std() * np.sqrt(365 * 6) * 100) if vol_window > 10 else float("nan")

    # Vol percentile vs trailing 180 × 30-day rolling stds (proxy of regime)
    roll_vol = rets.rolling(30 * 6).std()
    vol_pct = float((roll_vol <= roll_vol.iloc[-1]).tail(180).mean() * 100) if len(roll_vol) > 180 else float("nan")

    return {
        "adx14": round(adx, 1),
        "atr_pct": round(atr_pct, 2),
        "rsi14": round(rsi, 1),
        "ema50_above_200": bool(ema50.iloc[-1] > ema200.iloc[-1]),
        "ema50_slope_10bar_pct": round(float(ema50_slope), 2),
        "realized_vol_30d_annpct": round(vol30, 1),
        "vol_regime_pctile_180d": round(vol_pct, 0),
        "bars_in_snapshot": len(df),
    }


def build_snapshot(df_hist: pd.DataFrame, coin: str,
                    last_decisions: list[Decision] | None = None) -> str:
    """
    Compose the user message for a single decision.
    `df_hist` MUST be strictly past data — the caller is responsible for slicing.
    """
    ind = _compute_indicators(df_hist)
    ohlcv = _compact_ohlcv(df_hist)
    hist = "\n".join(
        f"- {d.strategy}/{d.direction} size={d.size_mult:.2f} ({d.regime})"
        for d in (last_decisions or [])[-5:]
    ) or "(none)"
    return (
        f"# Decision request — {coin}\n"
        f"Last seen bar timestamp (close): {df_hist.index[-1]}\n"
        f"Your decision will be executed at the OPEN of the NEXT bar.\n\n"
        f"## Current indicators\n{json.dumps(ind, indent=2)}\n\n"
        f"## Last {COMPACT_BARS} bars (close_pct = percentile rank across snapshot)\n"
        f"{ohlcv}\n\n"
        f"## Your last 5 decisions\n{hist}\n\n"
        f"Return the Decision JSON per the schema. No other text."
    )


def snapshot_hash(snapshot: str) -> str:
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:16]


# ─── System prompt loader ──────────────────────────────────────────
def load_system_prompt() -> str:
    """Frozen bytes — same prompt every call so providers can prefix-cache it."""
    return PROMPT_PATH.read_text(encoding="utf-8")


# ─── Decision → signals dispatch ────────────────────────────────────
#
# V23/V30/V34 signal functions return 2-tuples of entry edges only:
#   sig_bbbreak_ls(df, n, k, regime_len)        → (long_sig, short_sig)
#   sig_htf_donchian_ls(df, donch_n, ema_reg)   → (long_sig, short_sig)
#   sig_cci_extreme(df, cci_n, ...)             → (long_sig, short_sig)
#
# Exits are handled inside `simulate()` from run_v16_1h_hunt.py via
# ATR-based tp_atr / sl_atr / trail_atr / max_hold. So v37 only needs to
# produce the masked long/short entry series — simulate() takes it from there.
def _entries_bbbreak_ls(df, n=20, k=2.0, regime_len=200):
    from strategy_lab.run_v34_expand import sig_bbbreak_ls
    return sig_bbbreak_ls(df, n=n, k=k, regime_len=regime_len)  # (long, short)


def _entries_htf_donchian_ls(df, donch_n=20, ema_reg=100):
    from strategy_lab.run_v34_expand import sig_htf_donchian_ls
    return sig_htf_donchian_ls(df, donch_n=donch_n, ema_reg=ema_reg)  # (long, short)


def _entries_cci_extreme(df, cci_n=20, cci_lo=-200, cci_hi=200, adx_max=22, adx_n=14):
    from strategy_lab.run_v30_creative import sig_cci_extreme
    return sig_cci_extreme(df, cci_n=cci_n, cci_lo=cci_lo, cci_hi=cci_hi,
                           adx_max=adx_max, adx_n=adx_n)  # (long, short)


def build_entries_from_decisions(df: pd.DataFrame,
                                   decisions: dict[int, Decision]
                                   ) -> tuple[pd.Series, pd.Series]:
    """
    Convert per-bar Claude decisions into long/short ENTRY series for simulate().

    A decision forward-fills until the next decision bar. On each bar, the
    active strategy's entry signals are kept if-and-only-if (a) this bar's
    active strategy == that signal's strategy AND (b) direction permits it.

    Exits are NOT produced here — simulate() in run_v16_1h_hunt.py exits
    every trade via ATR TP/SL/trail/max_hold. Strategy switches still close
    the open position because simulate's max_hold + trail will catch it on
    a dry strategy, and we suppress re-entries from the old strategy.
    """
    idx = df.index
    long_e = pd.Series(False, index=idx)
    short_e = pd.Series(False, index=idx)

    l_bb, s_bb = _entries_bbbreak_ls(df)
    l_dn, s_dn = _entries_htf_donchian_ls(df)
    l_cc, s_cc = _entries_cci_extreme(df)

    active: Decision | None = None
    for i in range(len(df)):
        if i in decisions:
            active = decisions[i]
        if active is None or active.strategy == "Flat":
            continue
        want_long = active.direction in ("long", "both")
        want_short = active.direction in ("short", "both")
        if active.strategy == "BBBreak_LS":
            long_e.iloc[i]  = bool(want_long  and l_bb.iloc[i])
            short_e.iloc[i] = bool(want_short and s_bb.iloc[i])
        elif active.strategy == "HTF_Donchian":
            long_e.iloc[i]  = bool(want_long  and l_dn.iloc[i])
            short_e.iloc[i] = bool(want_short and s_dn.iloc[i])
        elif active.strategy == "CCI_Rev":
            long_e.iloc[i]  = bool(want_long  and l_cc.iloc[i])
            short_e.iloc[i] = bool(want_short and s_cc.iloc[i])
    return long_e, short_e


# ─── Decision cache (parquet, keyed by input hash) ──────────────────
def cache_path(coin: str) -> Path:
    return RESULTS_DIR / f"decisions_{coin}.parquet"


def load_cache(coin: str) -> pd.DataFrame:
    p = cache_path(coin)
    if p.exists():
        return pd.read_parquet(p)
    return pd.DataFrame(columns=["bar_ix", "input_hash", "decision_json"])


def save_cache(coin: str, df: pd.DataFrame) -> None:
    df.to_parquet(cache_path(coin), index=False)


def decision_to_row(bar_ix: int, snapshot: str, d: Decision) -> dict:
    return {
        "bar_ix": int(bar_ix),
        "input_hash": snapshot_hash(snapshot),
        "decision_json": d.model_dump_json(),
    }


__all__ = [
    "Decision", "LOOKBACK_BARS", "DECISION_CADENCE_BARS", "COMPACT_BARS",
    "build_snapshot", "snapshot_hash", "load_system_prompt",
    "build_entries_from_decisions",
    "load_cache", "save_cache", "decision_to_row",
    "RESULTS_DIR", "PROMPT_PATH",
]
