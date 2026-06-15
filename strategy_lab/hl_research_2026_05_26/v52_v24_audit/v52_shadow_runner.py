"""
V52-OPTIMIZED SHADOW RUNNER  (paper-trade, no real orders)
==========================================================

Deterministic recompute-from-history shadow engine for the optimized V52 fleet.

Sleeves (9):
  V41-family (gate = FUND_Z<2):
    - STF_BTC   (NEW, fills the missing BTC sleeve)  V45 variant
    - CCI_ETH                                         V41 variant
    - STF_SOL                                         baseline variant
    - STF_AVAX                                        V45 variant
    - LATBB_AVAX                                      baseline variant
  Volume diversifiers (gate = ATR_NOTOPVOL):
    - MFI_SOL    V41 variant
    - VP_LINK    baseline
    - SVD_AVAX   baseline
    - MFI_ETH    baseline

Each run (designed to run once per closed 4h bar):
  1. Load FRESH HL 4h OHLCV + funding for each sleeve's coin.
  2. Compute the sleeve's entry signal, apply its gate mask + (V45) volume filter.
  3. Run the funding-aware simulator → closed-trade history.
  4. Detect:
       - recent closed trades (entry in last LOOKBACK_DAYS) = realised shadow fills
       - the currently-OPEN paper position (dangling entry after last close), if any
       - a PENDING fire: gated signal True on the just-closed bar while flat
                          → the action the live bot would take at next bar open
  5. Write:
       shadow_v52/positions_latest.csv   (snapshot, overwritten each run)
       shadow_v52/fires_ledger.csv       (append-only, de-duplicated by sleeve+entry_ts)
       shadow_v52/STATUS.md              (human-readable)
       shadow_v52/run_log.csv            (one row per run: ts, n_open, n_pending, n_new_fires)

This is PAPER ONLY. It never submits an order. It records what the live V52 bot
WOULD do, so you can validate fire cadence + PnL before risking capital.

Usage:
    py strategy_lab/hl_research_2026_05_26/v52_v24_audit/v52_shadow_runner.py
    py strategy_lab/hl_research_2026_05_26/v52_v24_audit/v52_shadow_runner.py --backfill-days 120

Schedule (every 4h, 1 min after the bar close at 00/04/08/12/16/20 UTC):
    Windows Task Scheduler / cron:  1 0,4,8,12,16,20 * * *  py <thispath>
"""
from __future__ import annotations
import sys, json, argparse, importlib.util
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H
from strategy_lab.regime.hmm_adaptive import fit_regime_model

OUT_DIR = REPO / "shadow_v52"
OUT_DIR.mkdir(parents=True, exist_ok=True)

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
BARS_PER_DAY = 6  # 4h bars
NOTIONAL_PER_SLEEVE = 250.0  # paper notional per fire (display only)


def _load_mod(rel, name):
    spec = importlib.util.spec_from_file_location(name, str(REPO / rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

_v30 = _load_mod("strategy_lab/run_v30_creative.py", "v30c")
_v29 = _load_mod("strategy_lab/run_v29_regime.py", "v29r")


# ---------------------------------------------------------------------------
# Sleeve registry — exact specs from the audit (_b2_b3_b4.py) + new STF_BTC
# ---------------------------------------------------------------------------
SLEEVES = [
    # name,        coin,  sig_fn,                      params,                                                              variant,   gate
    ("STF_BTC",    "BTC",  _v30.sig_supertrend_flip,   dict(st_n=10, st_mult=3.0, ema_reg=200),                             "V45",      "FUND_Z"),     # NEW
    ("CCI_ETH",    "ETH",  _v30.sig_cci_extreme,       dict(cci_n=20, cci_lo=-150, cci_hi=150, adx_max=22, adx_n=14),       "V41",      "FUND_Z"),
    ("STF_SOL",    "SOL",  _v30.sig_supertrend_flip,   dict(st_n=10, st_mult=3.0, ema_reg=200),                             "baseline", "FUND_Z"),
    ("STF_AVAX",   "AVAX", _v30.sig_supertrend_flip,   dict(st_n=10, st_mult=3.0, ema_reg=200),                             "V45",      "FUND_Z"),
    ("LATBB_AVAX", "AVAX", _v29.sig_lateral_bb_fade,   dict(bb_n=20, bb_k=2.0, adx_max=18, adx_n=14),                       "baseline", "FUND_Z"),
    ("MFI_SOL",    "SOL",  sig_mfi_extreme,            dict(lower=25, upper=75),                                            "V41",      "ATR_NOTOPVOL"),
    ("VP_LINK",    "LINK", sig_volume_profile_rot,     dict(win=60, n_bins=15),                                            "baseline", "ATR_NOTOPVOL"),
    ("SVD_AVAX",   "AVAX", sig_signed_vol_div,         dict(lookback=20, cvd_win=50),                                      "baseline", "ATR_NOTOPVOL"),
    ("MFI_ETH",    "ETH",  sig_mfi_extreme,            dict(lower=25, upper=75),                                            "baseline", "ATR_NOTOPVOL"),
]

# Sleeve weights inside V52 (proposed: 5 V41 @ 12% + 4 div @ 10%)
WEIGHTS = {
    "STF_BTC": 0.12, "CCI_ETH": 0.12, "STF_SOL": 0.12, "STF_AVAX": 0.12, "LATBB_AVAX": 0.12,
    "MFI_SOL": 0.10, "VP_LINK": 0.10, "SVD_AVAX": 0.10, "MFI_ETH": 0.10,
}


# ---------------------------------------------------------------------------
# Gate masks (exact replicas of audit _b2_b3_b4.py)
# ---------------------------------------------------------------------------
def gate_fund_z(coin, df, z_thr=2.0):
    fund_4h = funding_per_4h_bar(coin, df.index)
    mu = fund_4h.rolling(500, min_periods=100).mean()
    sd = fund_4h.rolling(500, min_periods=100).std()
    z = (fund_4h - mu) / sd.replace(0, np.nan)
    return (z.abs() < z_thr).fillna(True)


def gate_atr_notopvol(df, atr_n=14, high_q=0.80):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_n).mean()
    pct = atr.rolling(500, min_periods=100).rank(pct=True)
    return (pct < high_q).fillna(True)


def build_signal(sleeve, df, fund):
    """Return (le_gated, se_gated) boolean Series after gate + V45 volume filter."""
    name, coin, sig_fn, params, variant, gate = sleeve
    out = sig_fn(df, **params)
    le, se = out if isinstance(out, tuple) else (out, None)
    le = le.reindex(df.index).fillna(False)
    se = se.reindex(df.index).fillna(False) if se is not None else pd.Series(False, index=df.index)

    # V45 variant: volume-active filter (vol > 1.1 * 20-bar mean)
    if variant == "V45":
        vmean = df["volume"].rolling(20, min_periods=10).mean()
        active = df["volume"] > 1.1 * vmean
        le = le & active
        se = se & active

    # Gate
    if gate == "FUND_Z":
        m = gate_fund_z(coin, df)
    elif gate == "ATR_NOTOPVOL":
        m = gate_atr_notopvol(df)
    else:
        m = pd.Series(True, index=df.index)
    le = le & m
    se = se & m
    return le.fillna(False), se.fillna(False)


def run_sleeve(sleeve, df, fund):
    """Run simulator → closed trades; return (trades, le, se, regime_df_or_None)."""
    name, coin, sig_fn, params, variant, gate = sleeve
    le, se = build_signal(sleeve, df, fund)
    if variant in ("V41", "V45"):
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        trades, eq = simulate_with_funding(df, le, se, fund,
            regime_labels=rdf["label"], regime_exits=REGIME_EXITS_4H)
    else:
        trades, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H)
    return trades, le, se, eq


def detect_open_position(trades, le, se, df):
    """A position is OPEN if a gated fire occurred after the last closed-trade exit
    (respecting the 2-bar cooldown) and has not yet exited."""
    N = len(df)
    fires = np.where((le.to_numpy() | se.to_numpy()))[0]
    last_exit = max((t["exit_idx"] for t in trades), default=-10)
    # entries already captured by closed trades:
    entered_idx = {t["entry_idx"] for t in trades}
    for i in fires:
        if i <= last_exit + 2:       # cooldown / already inside a closed trade window
            continue
        if i + 1 >= N:               # signal on last bar → PENDING, not yet open
            continue
        entry_idx = i + 1
        if entry_idx in entered_idx: # this fire opened a trade that already closed
            continue
        # This is an open position (entered, never closed in the trades list)
        direction = 1 if le.iloc[i] else -1
        entry_price = float(df["open"].iloc[entry_idx])
        entry_ts = df.index[entry_idx]
        last_close = float(df["close"].iloc[-1])
        unreal = (last_close - entry_price) * direction / entry_price
        bars_held = N - 1 - entry_idx
        return dict(direction=direction, entry_price=entry_price, entry_ts=entry_ts,
                    bars_held=int(bars_held), unrealized_pct=float(unreal))
    return None


def detect_pending_fire(le, se, df):
    """A fire on the most-recently-CLOSED bar (index N-1). The live bot would
    enter at the next bar's open. This is the actionable shadow fire."""
    i = len(df) - 1
    if bool(le.iloc[i]):
        return dict(direction=1, signal_bar_ts=df.index[i], signal_close=float(df["close"].iloc[i]))
    if bool(se.iloc[i]):
        return dict(direction=-1, signal_bar_ts=df.index[i], signal_close=float(df["close"].iloc[i]))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-days", type=int, default=45,
                    help="window for 'recent fires' ledger seeding")
    ap.add_argument("--now", type=str, default=None,
                    help="override 'now' ISO ts for deterministic testing")
    args = ap.parse_args()

    run_ts = pd.Timestamp(args.now, tz="UTC") if args.now else pd.Timestamp.now(tz="UTC")
    lookback_bars = args.backfill_days * BARS_PER_DAY

    positions_rows = []
    new_fires = []
    pending_rows = []
    data_end_dates = {}

    for sleeve in SLEEVES:
        name, coin, sig_fn, params, variant, gate = sleeve
        try:
            df = load_hl(coin, "4h")
        except FileNotFoundError:
            positions_rows.append(dict(sleeve=name, coin=coin, state="NO_DATA"))
            continue
        fund = funding_per_4h_bar(coin, df.index)
        data_end_dates[name] = df.index.max()

        trades, le, se, eq = run_sleeve(sleeve, df, fund)

        # Recent closed trades (entry within lookback window)
        cutoff = df.index[-1] - pd.Timedelta(days=args.backfill_days)
        for t in trades:
            ets = df.index[t["entry_idx"]]
            if ets >= cutoff:
                new_fires.append(dict(
                    sleeve=name, coin=coin,
                    entry_ts=ets.isoformat(),
                    exit_ts=df.index[t["exit_idx"]].isoformat(),
                    direction="LONG" if t["side"] == 1 else "SHORT",
                    entry_price=round(t["entry"], 4), exit_price=round(t["exit"], 4),
                    bars_held=t["bars"], reason=t["reason"],
                    ret_pct=round(t["ret"] * 100, 3),
                    paper_pnl_usd=round(t["ret"] * NOTIONAL_PER_SLEEVE, 2),
                    status="CLOSED",
                ))

        # Currently-open paper position
        op = detect_open_position(trades, le, se, df)
        if op:
            positions_rows.append(dict(
                sleeve=name, coin=coin, state="OPEN",
                direction="LONG" if op["direction"] == 1 else "SHORT",
                entry_ts=op["entry_ts"].isoformat(),
                entry_price=round(op["entry_price"], 4),
                bars_held=op["bars_held"],
                unrealized_pct=round(op["unrealized_pct"] * 100, 3),
                unrealized_usd=round(op["unrealized_pct"] * NOTIONAL_PER_SLEEVE, 2),
                weight=WEIGHTS[name],
                data_end=df.index.max().isoformat(),
            ))
        else:
            positions_rows.append(dict(
                sleeve=name, coin=coin, state="FLAT",
                weight=WEIGHTS[name], data_end=df.index.max().isoformat(),
            ))

        # Pending fire on the just-closed bar
        pf = detect_pending_fire(le, se, df)
        if pf:
            pending_rows.append(dict(
                sleeve=name, coin=coin,
                direction="LONG" if pf["direction"] == 1 else "SHORT",
                signal_bar_ts=pf["signal_bar_ts"].isoformat(),
                signal_close=round(pf["signal_close"], 4),
                action="ENTER_NEXT_OPEN",
            ))

    # --- Write positions snapshot ---
    pos_df = pd.DataFrame(positions_rows)
    pos_df.to_csv(OUT_DIR / "positions_latest.csv", index=False)

    # --- Append to fires ledger (dedup by sleeve+entry_ts) ---
    ledger_path = OUT_DIR / "fires_ledger.csv"
    fires_df = pd.DataFrame(new_fires)
    if ledger_path.exists() and len(fires_df):
        old = pd.read_csv(ledger_path)
        combo = pd.concat([old, fires_df], ignore_index=True)
        combo = combo.drop_duplicates(subset=["sleeve", "entry_ts"], keep="last")
        combo.to_csv(ledger_path, index=False)
    elif len(fires_df):
        fires_df.to_csv(ledger_path, index=False)
    n_ledger = len(pd.read_csv(ledger_path)) if ledger_path.exists() else 0

    # --- Pending fires ---
    pend_df = pd.DataFrame(pending_rows)
    pend_df.to_csv(OUT_DIR / "pending_fires_latest.csv", index=False)

    # --- Run log ---
    n_open = int((pos_df["state"] == "OPEN").sum()) if "state" in pos_df else 0
    log_row = dict(run_ts=run_ts.isoformat(), n_open=n_open,
                   n_pending=len(pending_rows), n_recent_closed=len(new_fires),
                   ledger_total=n_ledger)
    log_path = OUT_DIR / "run_log.csv"
    log_df = pd.DataFrame([log_row])
    if log_path.exists():
        log_df = pd.concat([pd.read_csv(log_path), log_df], ignore_index=True)
    log_df.to_csv(log_path, index=False)

    # --- STATUS.md ---
    lines = [f"# V52-Optimized Shadow Status", "",
             f"**Run:** {run_ts.isoformat()}",
             f"**Mode:** PAPER (no real orders). Notional/sleeve = ${NOTIONAL_PER_SLEEVE:.0f} (display).",
             f"**Data end (max across sleeves):** {max(data_end_dates.values()).isoformat() if data_end_dates else 'NO DATA'}",
             ""]
    # staleness warning
    if data_end_dates:
        newest = max(data_end_dates.values())
        stale_h = (run_ts - newest).total_seconds() / 3600
        if stale_h > 8:
            lines.append(f"> **WARNING: data is {stale_h:.0f}h stale** (last bar {newest.isoformat()}). "
                         f"Refresh HL data before trusting fires.")
            lines.append("")

    lines.append("## Open paper positions")
    lines.append("")
    open_rows = [r for r in positions_rows if r.get("state") == "OPEN"]
    if open_rows:
        lines.append("| Sleeve | Coin | Dir | Entry ts | Entry px | Bars | Unreal % | Unreal $ |")
        lines.append("|---|---|---|---|---:|---:|---:|---:|")
        for r in open_rows:
            lines.append(f"| {r['sleeve']} | {r['coin']} | {r['direction']} | {r['entry_ts']} | "
                         f"{r['entry_price']} | {r['bars_held']} | {r['unrealized_pct']} | {r['unrealized_usd']} |")
    else:
        lines.append("_None open._")
    lines.append("")

    lines.append("## Pending fires (act at next bar open)")
    lines.append("")
    if pending_rows:
        lines.append("| Sleeve | Coin | Dir | Signal bar | Close |")
        lines.append("|---|---|---|---|---:|")
        for r in pending_rows:
            lines.append(f"| {r['sleeve']} | {r['coin']} | {r['direction']} | {r['signal_bar_ts']} | {r['signal_close']} |")
    else:
        lines.append("_No fresh fire on the just-closed bar._")
    lines.append("")

    lines.append(f"## Recent closed paper trades (last {args.backfill_days}d): {len(new_fires)}")
    lines.append("")
    if new_fires:
        recent_sorted = sorted(new_fires, key=lambda x: x["entry_ts"], reverse=True)[:20]
        lines.append("| Sleeve | Dir | Entry ts | Exit ts | Bars | Reason | Ret % | Paper $ |")
        lines.append("|---|---|---|---|---:|---|---:|---:|")
        for r in recent_sorted:
            lines.append(f"| {r['sleeve']} | {r['direction']} | {r['entry_ts']} | {r['exit_ts']} | "
                         f"{r['bars_held']} | {r['reason']} | {r['ret_pct']} | {r['paper_pnl_usd']} |")
    else:
        lines.append("_No closed trades in window._")
    lines.append("")
    lines.append(f"**Fleet ledger total fires:** {n_ledger}")

    (OUT_DIR / "STATUS.md").write_text("\n".join(lines), encoding="utf-8")

    # Console summary
    print(f"[{run_ts.isoformat()}] V52 shadow run complete")
    print(f"  open positions : {n_open}")
    print(f"  pending fires  : {len(pending_rows)}")
    print(f"  recent closed  : {len(new_fires)}")
    print(f"  ledger total   : {n_ledger}")
    if data_end_dates:
        print(f"  data end       : {max(data_end_dates.values()).isoformat()}")
    print(f"  outputs        : {OUT_DIR}")


if __name__ == "__main__":
    main()
