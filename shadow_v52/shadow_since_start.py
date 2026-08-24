"""
SHADOW-SINCE-START — per-sleeve results counting ONLY live-observed trades.

The ledgers also contain backfill rows (trades recomputed from history when a fleet
was first created). Those are not evidence of anything forward, so this report counts
only fires whose entry bar closed AFTER that fleet's shadow went live:

    V52 fleet : 2026-06-11
    V53 fleet : 2026-07-27 21:16 UTC

Per sleeve: start date, days running, trades, wins/losses, win rate, average win,
average loss, biggest win/loss, paper PnL, exit-reason counts, and whether it is
currently holding an open position.

    py shadow_v52/shadow_since_start.py
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent

FLEETS = {
    "V52": dict(ledger="fires_ledger.csv", positions="positions_latest.csv",
                start="2026-06-11T00:00:00+00:00",
                note="9 hand-picked sleeves (incumbent)"),
    "V53": dict(ledger="v53_fires_ledger.csv", positions="v53_positions_latest.csv",
                start="2026-07-27T21:16:00+00:00",
                note="20 breadth streams (2 families x 10 coins)"),
}


def _load(name: str) -> pd.DataFrame:
    p = OUT / name
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def main() -> None:
    now = datetime.now(timezone.utc)
    print("=" * 122)
    print(f"SHADOW RESULTS SINCE GO-LIVE — {now:%Y-%m-%d %H:%M} UTC")
    print("=" * 122)
    print("Counts LIVE-OBSERVED trades only (entry bar closed after the fleet went live).")
    print("Backfill rows — trades recomputed from history at fleet creation — are excluded")
    print("and reported separately, because they are not forward evidence.\n")

    for fleet, cfg in FLEETS.items():
        led = _load(cfg["ledger"])
        pos = _load(cfg["positions"])
        start = pd.Timestamp(cfg["start"])
        days = (now - start.to_pydatetime()).total_seconds() / 86400

        print("=" * 122)
        print(f"{fleet} — {cfg['note']}")
        print(f"   shadow live since {start:%Y-%m-%d %H:%M} UTC  ({days:.1f} days)")
        print("=" * 122)

        if not len(led):
            print("   no ledger rows\n")
            continue

        led["entry_ts"] = pd.to_datetime(led["entry_ts"])
        led["exit_ts"] = pd.to_datetime(led["exit_ts"])
        live = led[led.entry_ts >= start]
        back = led[led.entry_ts < start]

        # open positions (V52 marks state, V53 lists only open rows)
        if len(pos) and "state" in pos.columns:
            pos = pos[pos.state == "OPEN"]
        open_by = set(pos.sleeve) if len(pos) else set()

        print(f"   live-observed closed trades: {len(live)}     "
              f"(backfill rows in ledger, excluded: {len(back)})")
        print(f"   open positions right now   : {len(open_by)}\n")

        sleeves = sorted(led.sleeve.unique())
        print(f"{'sleeve':12s} | {'first fire':>10s} {'last':>10s} {'days':>5s} | "
              f"{'trades':>6s} {'win':>4s} {'loss':>4s} {'WR%':>6s} | "
              f"{'avg win%':>8s} {'avg loss%':>9s} {'best%':>7s} {'worst%':>7s} | "
              f"{'paper$':>8s} | {'TP':>3s} {'TIME':>4s} {'SL':>3s} | open?")
        print("-" * 140)

        tot_n = tot_w = 0
        for s in sleeves:
            sub = live[live.sleeve == s]
            is_open = "YES" if s in open_by else ""
            if not len(sub):
                # no live trade yet -- dashes, not zeros, so an untraded sleeve is
                # never mistaken for one that traded and broke even
                d = "-"
                print(f"{s:12s} | {d:>11s} {d:>5s} {d:>5s} | {d:>6s} {d:>4s} {d:>4s} {d:>6s} | "
                      f"{d:>8s} {d:>9s} {d:>7s} {d:>7s} | {d:>8s} | {d:>3s} {d:>4s} {d:>3s} | {is_open}")
                continue
            r = sub.ret_pct.to_numpy(float)
            wins, losses = r[r > 0], r[r <= 0]
            span = (sub.entry_ts.max() - sub.entry_ts.min()).days
            rc = sub.reason.value_counts()
            tot_n += len(r); tot_w += len(wins)
            print(f"{s:12s} | {sub.entry_ts.min():%m-%d %H:%M} {sub.exit_ts.max():%m-%d} {span:5d} | "
                  f"{len(r):6d} {len(wins):4d} {len(losses):4d} {100*len(wins)/len(r):6.1f} | "
                  f"{(wins.mean() if len(wins) else np.nan):+8.2f} "
                  f"{(losses.mean() if len(losses) else np.nan):+9.2f} "
                  f"{r.max():+7.2f} {r.min():+7.2f} | "
                  f"{sub.paper_pnl_usd.sum():+8.2f} | "
                  f"{rc.get('TP',0):3d} {rc.get('TIME',0):4d} {rc.get('SL',0):3d} | {is_open}")

        if tot_n:
            r = live.ret_pct.to_numpy(float)
            w, l = r[r > 0], r[r <= 0]
            print("-" * 140)
            print(f"{'TOTAL':12s} | {live.entry_ts.min():%m-%d %H:%M} {live.exit_ts.max():%m-%d} "
                  f"{(live.entry_ts.max()-live.entry_ts.min()).days:5d} | "
                  f"{len(r):6d} {len(w):4d} {len(l):4d} {100*len(w)/len(r):6.1f} | "
                  f"{w.mean():+8.2f} {l.mean():+9.2f} {r.max():+7.2f} {r.min():+7.2f} | "
                  f"{live.paper_pnl_usd.sum():+8.2f} | "
                  f"{int((live.reason=='TP').sum()):3d} {int((live.reason=='TIME').sum()):4d} "
                  f"{int((live.reason=='SL').sum()):3d} |")
            print(f"\n   mean {r.mean():+.3f}%/trade   median {np.median(r):+.3f}%   "
                  f"payoff ratio {abs(w.mean()/l.mean()):.2f}x   "
                  f"breakeven WR needed {100/(1+abs(w.mean()/l.mean())):.1f}% vs actual {100*len(w)/len(r):.1f}%")

            # arm split where present
            if "arm" in live.columns and live.arm.nunique() > 1:
                print()
                for arm, a in live.groupby("arm"):
                    ar = a.ret_pct.to_numpy(float)
                    print(f"   {arm:8s} n={len(ar):3d}  wins={int((ar>0).sum()):3d}  "
                          f"WR={100*(ar>0).mean():5.1f}%  mean={ar.mean():+.3f}%  "
                          f"paper=${a.paper_pnl_usd.sum():+.2f}")
        print()

    print("=" * 122)
    print("HOW TO READ THIS")
    print("=" * 122)
    print("  * These are PAPER trades at $250 notional. $0 is at risk.")
    print("  * The system is deliberately low win-rate / high payoff: it takes many small")
    print("    stop-outs to pay for a few large winners. A WR near 33% is ON design, not a")
    print("    malfunction — compare WR against the 'breakeven WR needed' line above.")
    print("  * At these sample sizes per sleeve, individual sleeve numbers are noise. The")
    print("    fleet-level and arm-level rows are the only ones with any weight yet.")


if __name__ == "__main__":
    main()
