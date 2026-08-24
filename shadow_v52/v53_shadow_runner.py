"""
V53 BREADTH SHADOW RUNNER  (paper-trade, no real orders)
========================================================

What this is
------------
The V52 fleet is 9 hand-picked (signal, coin) pairs. The 2026-07-27 re-test
(strategy_lab/hl_research_2026_05_26/retest_2026_07_27/) found two problems with it:

  1. Only 4 of its 9 sleeves sit on a signal family that survives an untouched
     window. Pooled across a 10-coin universe on pre-2024-03 data, STF passes
     Bonferroni with 9/10 coins positive (n=877, +1.054%/tr, t=+5.01) and VP passes
     with 10/10 (n=1914, +0.501%/tr, t=+3.93). CCI and SVD are nominal-only; MFI and
     LATBB are weak (t=1.65 / 1.07) — yet CCI_ETH, MFI_SOL, MFI_ETH, SVD_AVAX and
     LATBB_AVAX are five of the nine deployed sleeves.

  2. V52 fires ~12 trades/month. With sd=6.7%/trade around a +1.05% mean it needs
     ~530 trades — about 45 months — to confirm itself live. That is the real
     blocker: not the signal, the sample rate.

V53 fixes both by trading the two VALIDATED families across the whole 10-coin
universe with no per-coin cherry-picking: 2 families x 10 coins = 20 streams,
~35-50 fires/month. Deliberately including the cells that look bad in isolation
(e.g. STF on LINK was -0.078%/tr) because excluding them is the selection bias
that produced problem 1.

Config — all of it inherited, none of it re-fitted here:
  entry  : STF = supertrend_flip(st_n=10, st_mult=3.0, ema_reg=200)
           VP  = volume_profile_rot(win=60, n_bins=15)
  gate   : ATR_NOTOPVOL (ATR(14) 500-bar pct-rank < 0.80) — uniform
  exits  : EXIT_4H tp 10 ATR / sl 2 ATR / trail 6 ATR / max_hold 60, static.
           A 62-variant grid could not beat this in both windows; the marginals
           say tighter stops are better, so the ~70% stop-out rate is the intended
           positive-skew design, not a defect.

PAPER ONLY. Never submits an order. Mirrors v52_shadow_runner's outputs so the two
fleets can be compared trade-for-trade.

Usage:
    py shadow_v52/v53_shadow_runner.py
    py shadow_v52/v53_shadow_runner.py --backfill-days 120
"""
from __future__ import annotations
import sys, argparse, importlib.util
from pathlib import Path
from datetime import timezone
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.strategies.v50_new_signals import sig_volume_profile_rot
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding

OUT_DIR = REPO / "shadow_v52"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _load_mod(rel, name):
    spec = importlib.util.spec_from_file_location(name, str(REPO / rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

_v30 = _load_mod("strategy_lab/run_v30_creative.py", "v30c")

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
BARS_PER_DAY = 6
NOTIONAL_PER_SLEEVE = 250.0

COINS = ["BTC", "ETH", "SOL", "AVAX", "LINK", "ADA", "BNB", "DOGE", "XRP", "SUI"]

# Family arms. DEPLOY = eligible for capital after the shadow gate; OBSERVE = kept
# recording at $0 but never sized, because it failed a forward test.
#
# STF   DEPLOY  — positive in every sequential window and never negative:
#                 2017-22 +1.549 (t=5.28) | 2022-24 +0.443 (t=1.49) |
#                 2024-25 +0.765 (t=1.51) | 2025-26 +1.933 (t=4.47) |
#                 2026-04->now +1.144 (t=1.62).  Breadth 9/10 long-OOS, 6/10 recent.
# VP    OBSERVE — monotonic decay then a significant flip negative:
#                 +0.759 -> +0.186 -> +0.375 -> +0.342 -> -1.091 (t=-3.38, n=161),
#                 breadth collapsed to 2/10 coins. It passed the untouched pre-2024
#                 window (t=+3.93) but has stopped working; keep it logged so a
#                 recovery is visible, do NOT give it size.
ARMS = {"STF": "DEPLOY", "VP": "OBSERVE"}
FAMILIES = {
    "STF": (_v30.sig_supertrend_flip, dict(st_n=10, st_mult=3.0, ema_reg=200)),
    "VP":  (sig_volume_profile_rot,   dict(win=60, n_bins=15)),
}
DEPLOY_FAMILIES = [f for f, a in ARMS.items() if a == "DEPLOY"]
# equal weight across the DEPLOY streams only — no per-cell sizing, matching validation
WEIGHT_PER_STREAM = 1.0 / (len(COINS) * max(len(DEPLOY_FAMILIES), 1))


def gate_atr_notopvol(df, atr_n=14, high_q=0.80) -> pd.Series:
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_n).mean()
    return (atr.rolling(500, min_periods=100).rank(pct=True) < high_q).fillna(True)


def build_signal(fam: str, df: pd.DataFrame):
    fn, params = FAMILIES[fam]
    out = fn(df, **params)
    le, se = out if isinstance(out, tuple) else (out, None)
    le = le.reindex(df.index).fillna(False)
    se = se.reindex(df.index).fillna(False) if se is not None else pd.Series(False, index=df.index)
    g = gate_atr_notopvol(df)
    return (le & g).fillna(False), (se & g).fillna(False)


def detect_open_position(trades, le, se, df):
    """Open if a gated fire happened after the last closed exit (2-bar cooldown)
    and has not exited yet. Same rule as the V52 runner."""
    N = len(df)
    fires = np.where(le.to_numpy() | se.to_numpy())[0]
    last_exit = max((t["exit_idx"] for t in trades), default=-10)
    entered = {t["entry_idx"] for t in trades}
    for i in fires:
        if i <= last_exit + 2 or i + 1 >= N:
            continue
        entry_idx = i + 1
        if entry_idx in entered:
            continue
        direction = 1 if le.iloc[i] else -1
        entry_price = float(df["open"].iloc[entry_idx])
        last_close = float(df["close"].iloc[-1])
        return dict(direction=direction, entry_price=entry_price,
                    entry_ts=df.index[entry_idx], bars_held=int(N - 1 - entry_idx),
                    unrealized_pct=float((last_close - entry_price) * direction / entry_price))
    return None


def detect_pending_fire(le, se, df):
    i = len(df) - 1
    if bool(le.iloc[i]):
        return dict(direction=1, signal_bar_ts=df.index[i], signal_close=float(df["close"].iloc[i]))
    if bool(se.iloc[i]):
        return dict(direction=-1, signal_bar_ts=df.index[i], signal_close=float(df["close"].iloc[i]))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-days", type=int, default=45)
    ap.add_argument("--now", type=str, default=None)
    args = ap.parse_args()
    run_ts = pd.Timestamp(args.now, tz="UTC") if args.now else pd.Timestamp.now(tz="UTC")
    cutoff = run_ts - pd.Timedelta(days=args.backfill_days)

    positions, pendings, fires = [], [], []
    data_end = {}
    skipped = []

    for coin in COINS:
        try:
            df = load_hl(coin, "4h")
            fund = funding_per_4h_bar(coin, df.index)
        except FileNotFoundError as e:
            skipped.append(f"{coin}: {e}")
            continue
        data_end[coin] = df.index.max()
        for fam in FAMILIES:
            name = f"{fam}_{coin}"
            le, se = build_signal(fam, df)
            trades, _ = simulate_with_funding(df, le, se, fund, **EXIT_4H)

            for t in trades:
                ets = df.index[t["entry_idx"]]
                if ets < cutoff:
                    continue
                fires.append(dict(
                    sleeve=name, family=fam, arm=ARMS[fam], coin=coin,
                    entry_ts=ets.isoformat(), exit_ts=df.index[t["exit_idx"]].isoformat(),
                    direction="LONG" if t["side"] > 0 else "SHORT",
                    entry_price=round(t["entry"], 6), exit_price=round(t["exit"], 6),
                    bars_held=t["bars"], reason=t["reason"],
                    ret_pct=round(100 * t["ret"], 3),
                    paper_pnl_usd=round(NOTIONAL_PER_SLEEVE * t["ret"], 2),
                    status="CLOSED"))

            op = detect_open_position(trades, le, se, df)
            if op:
                positions.append(dict(
                    sleeve=name, family=fam, arm=ARMS[fam], coin=coin,
                    direction="LONG" if op["direction"] > 0 else "SHORT",
                    entry_ts=op["entry_ts"].isoformat(), entry_price=round(op["entry_price"], 6),
                    bars_held=op["bars_held"], unreal_pct=round(100 * op["unrealized_pct"], 3),
                    unreal_usd=round(NOTIONAL_PER_SLEEVE * op["unrealized_pct"], 2)))

            pf = detect_pending_fire(le, se, df)
            if pf and not op:
                pendings.append(dict(
                    sleeve=name, family=fam, arm=ARMS[fam], coin=coin,
                    direction="LONG" if pf["direction"] > 0 else "SHORT",
                    signal_bar_ts=pf["signal_bar_ts"].isoformat(),
                    signal_close=round(pf["signal_close"], 6),
                    act_at="next 4h bar open"))

    # ---------------- write outputs (always write a header, even when empty:
    # an empty file with no header crashes pd.read_csv downstream)
    pos_cols = ["sleeve", "family", "arm", "coin", "direction", "entry_ts", "entry_price",
                "bars_held", "unreal_pct", "unreal_usd"]
    pend_cols = ["sleeve", "family", "arm", "coin", "direction", "signal_bar_ts",
                 "signal_close", "act_at"]
    fire_cols = ["sleeve", "family", "arm", "coin", "entry_ts", "exit_ts", "direction",
                 "entry_price", "exit_price", "bars_held", "reason", "ret_pct",
                 "paper_pnl_usd", "status"]

    pd.DataFrame(positions, columns=pos_cols).to_csv(OUT_DIR / "v53_positions_latest.csv", index=False)
    pd.DataFrame(pendings, columns=pend_cols).to_csv(OUT_DIR / "v53_pending_fires_latest.csv", index=False)

    ledger_p = OUT_DIR / "v53_fires_ledger.csv"
    new = pd.DataFrame(fires, columns=fire_cols)
    if ledger_p.exists() and ledger_p.stat().st_size > 0:
        old = pd.read_csv(ledger_p)
        led = pd.concat([old, new], ignore_index=True)
    else:
        led = new
    led = led.drop_duplicates(subset=["sleeve", "entry_ts"], keep="last") \
             .sort_values(["entry_ts", "sleeve"])
    led.to_csv(ledger_p, index=False)

    # ---------------- status
    closed = led[led.status == "CLOSED"] if len(led) else led
    lines = [
        "# V53 Breadth Shadow Status",
        "",
        f"**Run:** {run_ts.isoformat()}",
        f"**Mode:** PAPER (no real orders). Notional/stream = ${NOTIONAL_PER_SLEEVE:.0f} (display).",
        f"**Streams:** {len(FAMILIES)} validated families x {len(data_end)} coins = "
        f"{len(FAMILIES)*len(data_end)}",
        f"**Data end (max):** {max(data_end.values()).isoformat() if data_end else 'n/a'}",
        "",
        f"**Arms:** DEPLOY={DEPLOY_FAMILIES} (eligible for capital after the shadow gate) | "
        f"OBSERVE={[f for f, a in ARMS.items() if a == 'OBSERVE']} (logged at $0, never sized).",
        "",
        "STF validated on an untouched window (pre-2024-03, Binance 4h, n=877, +1.054%/tr, "
        "t=+5.01, 9/10 coins positive) AND positive in every sequential window since. "
        "VP passed the same untouched window (n=1914, t=+3.93, 10/10) but has since decayed "
        "monotonically to -1.091%/tr (t=-3.38, n=161, 2/10 coins) — hence OBSERVE, not DEPLOY. "
        "See strategy_lab/hl_research_2026_05_26/retest_2026_07_27/.",
        "",
        "## Open paper positions",
        "",
    ]
    if positions:
        lines += ["| Sleeve | Dir | Entry ts | Entry px | Bars | Unreal % | Unreal $ |",
                  "|---|---|---|---:|---:|---:|---:|"]
        for p in sorted(positions, key=lambda x: x["sleeve"]):
            lines.append(f"| {p['sleeve']} | {p['direction']} | {p['entry_ts']} | "
                         f"{p['entry_price']} | {p['bars_held']} | {p['unreal_pct']} | {p['unreal_usd']} |")
    else:
        lines.append("_none_")

    lines += ["", "## Pending fires (act at next bar open)", ""]
    if pendings:
        lines += ["| Sleeve | Dir | Signal bar | Close |", "|---|---|---|---:|"]
        for p in pendings:
            lines.append(f"| {p['sleeve']} | {p['direction']} | {p['signal_bar_ts']} | {p['signal_close']} |")
    else:
        lines.append("_No fresh fire on the just-closed bar._")

    if len(closed):
        c = closed.copy()
        lines += ["", f"## Closed paper trades in ledger: {len(c)}", ""]
        # Report the arms separately — pooling them would let the OBSERVE arm's
        # known negative drag hide the DEPLOY arm's result and vice versa.
        lines += ["| Arm | Family | n | mean ret % | WR % | paper $ |", "|---|---|---:|---:|---:|---:|"]
        for fam in FAMILIES:
            s = c[c.family == fam] if "family" in c.columns else c.iloc[0:0]
            if not len(s):
                continue
            lines.append(f"| {ARMS[fam]} | {fam} | {len(s)} | {s.ret_pct.mean():+.3f} | "
                         f"{100.0*(s.ret_pct>0).mean():.1f} | {s.paper_pnl_usd.sum():,.2f} |")
        dep = c[c.arm == "DEPLOY"] if "arm" in c.columns else c
        if len(dep):
            lines += ["", f"**DEPLOY arm only** — n={len(dep)}, "
                      f"mean {dep.ret_pct.mean():+.3f}%/tr, "
                      f"WR {100.0*(dep.ret_pct>0).mean():.1f}%, "
                      f"paper ${dep.paper_pnl_usd.sum():,.2f}", ""]
        by = c.groupby(["arm", "sleeve"]).agg(n=("ret_pct", "size"), mean_ret=("ret_pct", "mean"),
                                             usd=("paper_pnl_usd", "sum")).round(2).sort_values("usd")
        lines += ["| Arm | Sleeve | n | mean ret % | paper $ |", "|---|---|---:|---:|---:|"]
        for (arm, s), r in by.iterrows():
            lines.append(f"| {arm} | {s} | {int(r['n'])} | {r['mean_ret']} | {r['usd']} |")

    if skipped:
        lines += ["", "## Skipped (no data)", ""] + [f"- {s}" for s in skipped]

    (OUT_DIR / "V53_STATUS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    log_p = OUT_DIR / "v53_run_log.csv"
    row = pd.DataFrame([dict(run_ts=run_ts.isoformat(), n_streams=len(FAMILIES) * len(data_end),
                             n_open=len(positions), n_pending=len(pendings),
                             n_recent_closed=len(fires), ledger_total=len(led))])
    row.to_csv(log_p, mode="a", header=not log_p.exists(), index=False)

    print(f"[{run_ts.isoformat()}] V53 breadth shadow complete")
    print(f"  streams        : {len(FAMILIES) * len(data_end)} ({len(data_end)} coins x {len(FAMILIES)} families; "
          f"DEPLOY={DEPLOY_FAMILIES}, OBSERVE={[f for f,a in ARMS.items() if a=='OBSERVE']})")
    print(f"  open positions : {len(positions)}")
    print(f"  pending fires  : {len(pendings)}")
    print(f"  recent closed  : {len(fires)}")
    print(f"  ledger total   : {len(led)}")
    if skipped:
        print(f"  skipped        : {skipped}")
    print(f"  outputs        : {OUT_DIR}")


if __name__ == "__main__":
    main()
