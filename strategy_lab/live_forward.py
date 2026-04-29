"""
Live forward-test runner for the 6-coin Hyperliquid portfolio.

What it does:
  1. At every 4h bar-close, fetches fresh OHLCV from Binance public REST
     for each portfolio coin.
  2. Generates signals with the same strategy functions used in the backtest
     (strategies_v2 / v3 / v4).
  3. Maintains a simulated $10k account with the recommended spec
     (5 % sizing × 5x leverage = 25 % exposure per position) and updates
     positions, equity, and drawdown.
  4. Appends every signal and trade to CSV logs — ready to be compared
     against the backtest to detect drift.

Usage:
    # single pass — process any new closed bars and exit
    python -m strategy_lab.live_forward --once

    # forever — polls every 60 s, acts only on fresh bar close
    python -m strategy_lab.live_forward --daemon

    # bootstrap: replay the last N days from Binance parquet so state is
    # populated before going live (no network calls)
    python -m strategy_lab.live_forward --backfill 90

Files under strategy_lab/results/live/:
    state.json       — current positions, equity, last-processed ts
    signals.csv      — every bar-close evaluation (one row per coin)
    trades.csv       — opens + closes
    equity.csv       — equity sampled at every processed bar-close
"""
from __future__ import annotations
import argparse, json, sys, time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from strategy_lab.strategies_v2 import STRATEGIES_V2
from strategy_lab.strategies_v3 import STRATEGIES_V3
from strategy_lab.strategies_v4 import STRATEGIES_V4

ALL_STRATS = {**STRATEGIES_V2, **STRATEGIES_V3, **STRATEGIES_V4}

# ---------------------------------------------------------------------
# Portfolio spec — matches reports/HYPERLIQUID_PORTFOLIO_REPORT.pdf
# ---------------------------------------------------------------------
PORTFOLIO = {
    "BTCUSDT":  "V4C_range_kalman",
    "ETHUSDT":  "V3B_adx_gate",
    "SOLUSDT":  "V4C_range_kalman",
    "LINKUSDT": "V3B_adx_gate",
    "ADAUSDT":  "V4C_range_kalman",
    "XRPUSDT":  "V3B_adx_gate",
}
TF        = "4h"
INIT_USD  = 10_000.0
SIZING    = 0.05     # 5 % of equity notional per entry
LEVERAGE  = 5        # 5x → 25 % exposure per position
FEE_TAKER = 0.00045  # Hyperliquid taker fee 0.045 %
FEE_MAKER = 0.00015  # Hyperliquid maker fee 0.015 %
# Limit-order model (both sides): earn maker fee, no slippage.
# Assumes 100 % fill — real execution will be slightly worse when a bar
# gaps past the limit; see README for the taker-fallback logic.
FEE  = FEE_MAKER
SLIP = 0.0

BARS_NEEDED = 1000   # history depth for strategies (regime_len up to ~200 on 4h)

BASE = Path(__file__).resolve().parent
LIVE = BASE / "results" / "live"
LIVE.mkdir(parents=True, exist_ok=True)
PARQ = BASE.parent / "data" / "binance" / "parquet"


# ---------------------------------------------------------------------
# State — persisted between runs
# ---------------------------------------------------------------------
@dataclass
class Position:
    entry_ts: str          # ISO
    entry_px: float
    size: float            # shares
    peak: float            # for trailing stop
    tsl_frac: float        # trailing stop distance (fraction of price)
    sl_px: float = 0.0     # absolute static SL price (0 = none)


@dataclass
class State:
    base_cash: float = INIT_USD      # cumulative realized cash (no leverage)
    positions: dict = field(default_factory=dict)
    last_ts:   dict = field(default_factory=dict)    # sym -> last processed bar iso
    history_equity: list = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "base_cash": self.base_cash,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "last_ts":   self.last_ts,
            "history_equity": self.history_equity[-500:],
        }

    @classmethod
    def from_json(cls, d: dict) -> "State":
        s = cls(base_cash=d.get("base_cash", INIT_USD))
        s.positions = {k: Position(**v) for k, v in d.get("positions", {}).items()}
        s.last_ts   = d.get("last_ts", {})
        s.history_equity = d.get("history_equity", [])
        return s


def load_state() -> State:
    p = LIVE / "state.json"
    if not p.exists():
        return State()
    return State.from_json(json.loads(p.read_text()))


def save_state(s: State):
    (LIVE / "state.json").write_text(json.dumps(s.to_json(), indent=2, default=str))


# ---------------------------------------------------------------------
# Data fetch — Binance public REST
# ---------------------------------------------------------------------
BINANCE_KLINES = "https://api.binance.com/api/v3/klines"


def fetch_klines(symbol: str, interval: str = TF, limit: int = BARS_NEEDED) -> pd.DataFrame:
    r = requests.get(BINANCE_KLINES,
                     params={"symbol": symbol, "interval": interval, "limit": limit},
                     timeout=30)
    r.raise_for_status()
    rows = r.json()
    cols = ["open_time","open","high","low","close","volume","close_time",
            "quote_volume","trades","taker_buy_base","taker_buy_quote","_ignore"]
    df = pd.DataFrame(rows, columns=cols)
    df["open_time"] = pd.to_datetime(df["open_time"].astype("int64"), unit="ms", utc=True)
    df = df.set_index("open_time")
    for c in ("open","high","low","close","volume"):
        df[c] = pd.to_numeric(df[c])
    # Drop the still-forming bar (last row open_time + 4h > now).
    # Binance returns an incomplete bar as the last entry.
    now = pd.Timestamp.utcnow().tz_localize("UTC") if pd.Timestamp.utcnow().tzinfo is None \
          else pd.Timestamp.utcnow().tz_convert("UTC")
    bar_dur = pd.Timedelta(hours=4)
    df = df[df.index + bar_dur <= now]
    return df[["open","high","low","close","volume"]].astype("float64")


def load_parquet_tail(symbol: str, limit: int = BARS_NEEDED) -> pd.DataFrame:
    folder = PARQ / symbol / TF
    files = sorted(folder.glob("year=*/part.parquet"))
    frames = [pd.read_parquet(f) for f in files]
    df = (pd.concat(frames, ignore_index=True)
            .drop_duplicates("open_time").sort_values("open_time")
            .set_index("open_time"))
    return df[["open","high","low","close","volume"]].astype("float64").tail(limit)


# ---------------------------------------------------------------------
# Signal generation — on latest CLOSED bar
# ---------------------------------------------------------------------
def latest_signal(df: pd.DataFrame, strat_name: str) -> dict:
    """Return last bar's entry/exit flags + TSL fraction (if any)."""
    sig = ALL_STRATS[strat_name](df)
    e_now = bool(sig["entries"].iloc[-1]) if "entries" in sig else False
    x_now = bool(sig["exits"].iloc[-1])   if "exits"   in sig else False
    tsl = sig.get("tsl_stop")
    if tsl is not None and not isinstance(tsl, (int, float)):
        tsl_now = float(tsl.iloc[-1]) if not np.isnan(tsl.iloc[-1]) else 0.0
    elif isinstance(tsl, (int, float)):
        tsl_now = float(tsl)
    else:
        tsl_now = 0.0
    return {"entry": e_now, "exit": x_now, "tsl": tsl_now}


# ---------------------------------------------------------------------
# Equity tracking / position management
# ---------------------------------------------------------------------
def mark_to_market(state: State, prices_now: dict) -> float:
    # pos.size already represents the leveraged share count (exposure/entry_px),
    # so PnL = size * (px - entry_px) is already in USD equity terms.
    eq = state.base_cash
    for sym, pos in state.positions.items():
        px = prices_now.get(sym, pos.entry_px)
        eq += pos.size * (px - pos.entry_px)
    return eq


def open_position(state: State, sym: str, ts: pd.Timestamp, px: float, tsl_frac: float,
                  equity_now: float) -> dict:
    # notional (margin-equivalent) = equity * sizing
    # exposure (position notional)  = notional * leverage   = equity * sizing * L
    # shares                        = exposure / entry_price
    notional   = equity_now * SIZING
    exposure   = notional * LEVERAGE
    exec_px    = px * (1 + SLIP)
    size       = exposure / exec_px
    fee_usd    = exposure * FEE           # fee charged on exposure (notional of the perp)
    state.base_cash -= fee_usd
    state.positions[sym] = Position(
        entry_ts=ts.isoformat(), entry_px=exec_px, size=size,
        peak=exec_px, tsl_frac=tsl_frac,
    )
    return {"action": "ENTER", "sym": sym, "ts": ts, "px": exec_px,
            "size": size, "notional": exposure, "fee": fee_usd}


def close_position(state: State, sym: str, ts: pd.Timestamp, px: float, reason: str) -> dict:
    pos = state.positions.pop(sym)
    exec_px = px * (1 - SLIP)
    pnl     = pos.size * (exec_px - pos.entry_px)     # size is already leveraged
    fee_usd = pos.size * exec_px * FEE                # fee on exit exposure
    state.base_cash += pnl - fee_usd
    return {"action": "EXIT", "sym": sym, "ts": ts,
            "exit_px": exec_px, "entry_px": pos.entry_px,
            "size": pos.size, "pnl": pnl, "fee": fee_usd, "reason": reason,
            "return_on_equity_pct": pnl / (state.base_cash + pnl) if state.base_cash + pnl > 0 else 0,
            "trade_return_pct": (exec_px / pos.entry_px - 1)}


# ---------------------------------------------------------------------
# CSV append helpers
# ---------------------------------------------------------------------
def _append_csv(path: Path, row: dict):
    header = not path.exists()
    pd.DataFrame([row]).to_csv(path, mode="a", header=header, index=False)


def log_signal(ts, sym, strat, px, sig, pos_open, action, equity):
    _append_csv(LIVE / "signals.csv", {
        "ts": ts, "symbol": sym, "strategy": strat, "close": px,
        "entry_sig": sig["entry"], "exit_sig": sig["exit"],
        "tsl_frac": round(sig["tsl"], 5),
        "position_open": pos_open, "action": action, "equity_usd": round(equity, 2),
    })


def log_trade(row: dict):
    _append_csv(LIVE / "trades.csv", row)


def log_equity(ts, equity, positions, prices):
    _append_csv(LIVE / "equity.csv", {
        "ts": ts, "equity_usd": round(equity, 2),
        "open_positions": len(positions),
        "open_symbols": ",".join(sorted(positions.keys())),
    })


# ---------------------------------------------------------------------
# Core processing — handle any newly-closed bars
# ---------------------------------------------------------------------
def process_symbol(state: State, sym: str, strat: str,
                   df_for_fetch) -> list[dict]:
    """
    Process all bars after state.last_ts[sym] (excluded) up to the last
    closed bar in `df_for_fetch`. Returns list of actions taken.
    """
    actions = []
    last_iso = state.last_ts.get(sym)
    if last_iso:
        after = pd.Timestamp(last_iso)
        new_bars = df_for_fetch[df_for_fetch.index > after]
    else:
        # Initialize: treat every bar except the most recent 2 as already seen
        new_bars = df_for_fetch.tail(2)

    if len(new_bars) == 0:
        return actions

    # Prep strategy once on the full window; signals are causal, we just pick rows.
    sig_dict = ALL_STRATS[strat](df_for_fetch)
    entries = sig_dict["entries"].reindex(df_for_fetch.index).fillna(False)
    exits   = sig_dict.get("exits",   pd.Series(False, index=df_for_fetch.index))\
                     .reindex(df_for_fetch.index).fillna(False)
    tsl     = sig_dict.get("tsl_stop", None)
    if isinstance(tsl, (int, float)):
        tsl_series = pd.Series(tsl, index=df_for_fetch.index)
    elif tsl is None:
        tsl_series = pd.Series(0.0, index=df_for_fetch.index)
    else:
        tsl_series = tsl.reindex(df_for_fetch.index).fillna(0.0)

    for ts, row in new_bars.iterrows():
        close_px = float(row["close"])
        hi_px    = float(row["high"])
        lo_px    = float(row["low"])
        action = "HOLD"
        pos = state.positions.get(sym)

        # Check trailing-stop hit within this bar (uses high for trail update, low for stop)
        if pos:
            pos.peak = max(pos.peak, hi_px)
            stop_px = pos.peak * (1 - pos.tsl_frac)
            if pos.tsl_frac > 0 and lo_px <= stop_px:
                equity_now = mark_to_market(state, {sym: stop_px})
                trade = close_position(state, sym, ts, stop_px, reason="TSL")
                log_trade(trade); actions.append(trade); action = "EXIT_TSL"

        # Re-read state for exit-signal and entry logic
        if state.positions.get(sym) and exits.loc[ts] and action == "HOLD":
            equity_now = mark_to_market(state, {sym: close_px})
            trade = close_position(state, sym, ts, close_px, reason="SIG")
            log_trade(trade); actions.append(trade); action = "EXIT_SIG"

        if sym not in state.positions and entries.loc[ts]:
            equity_now = mark_to_market(state, {sym: close_px})
            tsl_val = float(tsl_series.loc[ts])
            trade = open_position(state, sym, ts, close_px, tsl_val, equity_now)
            log_trade(trade); actions.append(trade); action = "ENTER"

        # Log per-bar signal
        prices_for_eq = {s: (row["close"] if s == sym else None) for s in PORTFOLIO}
        # Use last-known prices for other open positions from df_for_fetch
        equity_now = mark_to_market(state, {sym: close_px})
        log_signal(ts, sym, strat, close_px,
                   {"entry": bool(entries.loc[ts]),
                    "exit": bool(exits.loc[ts]),
                    "tsl": float(tsl_series.loc[ts])},
                   pos_open=(sym in state.positions),
                   action=action, equity=equity_now)

        state.last_ts[sym] = ts.isoformat()

    return actions


def run_once(use_parquet: bool = False) -> dict:
    state = load_state()
    all_actions = []
    latest_prices = {}
    for sym, strat in PORTFOLIO.items():
        try:
            df = load_parquet_tail(sym) if use_parquet else fetch_klines(sym)
        except Exception as e:
            print(f"  {sym}: fetch failed — {e}", flush=True)
            continue
        if len(df) < 300:
            print(f"  {sym}: not enough bars ({len(df)}), skipping", flush=True)
            continue
        latest_prices[sym] = float(df["close"].iloc[-1])
        acts = process_symbol(state, sym, strat, df)
        for a in acts:
            px = a.get('exit_px') or a.get('px') or 0
            pnl_str = f"  pnl={a.get('pnl',0):+.2f}" if a['action'] == 'EXIT' else ''
            print(f"  {sym}  {a['action']}  @ {px:.4f}{pnl_str}", flush=True)
        all_actions.extend(acts)

    # Final equity snapshot + write history
    eq = mark_to_market(state, latest_prices)
    now_ts = pd.Timestamp.utcnow().tz_localize("UTC") if pd.Timestamp.utcnow().tzinfo is None \
             else pd.Timestamp.utcnow().tz_convert("UTC")
    state.history_equity.append({"ts": now_ts.isoformat(),
                                 "equity": round(eq, 2),
                                 "open": len(state.positions)})
    log_equity(now_ts, eq, state.positions, latest_prices)
    save_state(state)

    print(f"\nEquity: ${eq:,.2f}   positions open: {len(state.positions)} "
          f"({', '.join(state.positions) or '-'})", flush=True)
    return {"equity": eq, "actions": all_actions, "open": list(state.positions)}


def daemon(interval_s: int = 60):
    print(f"[daemon] polling every {interval_s}s. Acts only on fresh bar close. "
          f"Ctrl+C to stop.", flush=True)
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            print("\n[daemon] stopped.", flush=True); return
        except Exception as e:
            print(f"[daemon] error: {e}", flush=True)
        time.sleep(interval_s)


def backfill(days: int = 90):
    """Replay the last N days from parquet to pre-populate state."""
    print(f"[backfill] replaying last {days} days from parquet …", flush=True)
    state = State()
    save_state(state)  # fresh start
    for sym, strat in PORTFOLIO.items():
        try:
            df = load_parquet_tail(sym, BARS_NEEDED)
        except Exception as e:
            print(f"  {sym}: parquet load failed: {e}"); continue
        # Only replay the tail-window; strategies need full history for indicators
        # so pass full df but process_symbol will only handle bars after last_ts.
        replay_from = df.index[-1] - pd.Timedelta(days=days)
        # Seed last_ts to replay_from so all bars after are processed.
        state.last_ts[sym] = replay_from.isoformat()
        save_state(state)
        acts = process_symbol(state, sym, strat, df)
        print(f"  {sym}: {len(acts)} actions over {days}d")
    eq = mark_to_market(state, {s: load_parquet_tail(s, 1)["close"].iloc[-1]
                                 for s in PORTFOLIO})
    now = pd.Timestamp.utcnow().tz_localize("UTC") if pd.Timestamp.utcnow().tzinfo is None \
           else pd.Timestamp.utcnow().tz_convert("UTC")
    log_equity(now, eq, state.positions, {})
    save_state(state)
    print(f"[backfill] done. Equity: ${eq:,.2f}, open positions: {len(state.positions)}")


def status():
    state = load_state()
    print(f"Base cash: ${state.base_cash:,.2f}")
    print(f"Open positions: {len(state.positions)}")
    for sym, p in state.positions.items():
        print(f"  {sym}  entered {p.entry_ts}  px ${p.entry_px:,.4f}  "
              f"size {p.size:.6f}  peak ${p.peak:,.4f}  "
              f"tsl {p.tsl_frac*100:.2f}%")
    print(f"Last processed bars:")
    for sym, ts in state.last_ts.items():
        print(f"  {sym}: {ts}")
    if state.history_equity:
        last = state.history_equity[-1]
        print(f"Last recorded equity: ${last['equity']:,.2f} @ {last['ts']}")


# ---------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once",     action="store_true")
    p.add_argument("--daemon",   action="store_true")
    p.add_argument("--backfill", type=int, metavar="DAYS",
                   help="Replay last N days from parquet and exit")
    p.add_argument("--status",   action="store_true")
    p.add_argument("--reset",    action="store_true",
                   help="Wipe state + logs (use with caution)")
    p.add_argument("--use-parquet", action="store_true",
                   help="Use local parquet instead of Binance REST (for dry runs)")
    p.add_argument("--interval", type=int, default=60,
                   help="Daemon poll interval (seconds)")
    a = p.parse_args()

    if a.reset:
        for f in ("state.json", "signals.csv", "trades.csv", "equity.csv"):
            (LIVE / f).unlink(missing_ok=True)
        print("Reset done."); return

    if a.status:
        status(); return

    if a.backfill is not None:
        backfill(a.backfill); return

    if a.daemon:
        daemon(a.interval); return

    # default: --once
    run_once(use_parquet=a.use_parquet)


if __name__ == "__main__":
    sys.exit(main() or 0)
