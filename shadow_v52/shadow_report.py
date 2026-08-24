"""
SHADOW REPORT — full per-sleeve state for both HL paper fleets.

One command to see everything the shadow knows: per-sleeve trade counts, windows,
win rate, per-trade return, paper PnL, exit-reason mix, outlier dependence, open
positions and pending fires — for the V52 fleet (9 hand-picked sleeves), the V53
breadth fleet (20 streams, DEPLOY/OBSERVE arms) and the XSM basket.

Read-only. Reads the ledgers the hourly tick maintains; never fetches or fires.

    py shadow_v52/shadow_report.py
    py shadow_v52/shadow_report.py --since 2026-06-11   # restrict to a window
"""
from __future__ import annotations
import argparse
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
SHADOW_START = "2026-06-11"   # date the live paper shadow went up
MIN_N_FOR_T = 10              # below this a t-stat is small-sample noise, not evidence


def _load(name: str) -> pd.DataFrame:
    p = OUT / name
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def agg(s: pd.DataFrame) -> dict:
    """Per-trade stats. ret_pct is % return on deployed cash."""
    if not len(s):
        return dict(n=0, wr=np.nan, mean=np.nan, med=np.nan, best=np.nan, worst=np.nan,
                    usd=0.0, t=np.nan, ex_top2=0.0, avg_bars=np.nan)
    r = s.ret_pct.to_numpy(float)
    p = s.paper_pnl_usd.to_numpy(float)
    o = np.sort(p)[::-1]
    # t is not reported below MIN_N_FOR_T: with 3-4 trades that all stopped out at the
    # same ~-3.1% the variance collapses and t explodes (STF_ADA read t=-189 on n=4),
    # which looks like overwhelming evidence and is pure small-sample artifact.
    t = np.nan
    if len(r) >= MIN_N_FOR_T and r.std(ddof=1) > 0:
        t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))
    return dict(n=len(r), wr=100 * (r > 0).mean(), mean=r.mean(), med=float(np.median(r)),
                best=r.max(), worst=r.min(), usd=p.sum(), t=t,
                ex_top2=p.sum() - o[:2].sum(), avg_bars=float(s.bars_held.mean()))


def hdr(title: str, ch: str = "=") -> None:
    print(f"\n{ch * 118}\n{title}\n{ch * 118}")


def sleeve_table(led: pd.DataFrame, group: str, extra_cols: list[str] | None = None) -> None:
    print(f"{group:12s} | {'n':>4s} {'WR%':>6s} {'mean%':>8s} {'med%':>8s} {'best%':>7s} "
          f"{'worst%':>7s} {'avg':>5s} | {'paper$':>9s} {'ex-top2$':>9s} {'t':>6s} | first fire -> last exit")
    print("-" * 130)
    for key, s in led.groupby(group):
        a = agg(s)
        f = pd.to_datetime(s.entry_ts).min()
        l = pd.to_datetime(s.exit_ts).max()
        print(f"{str(key):12s} | {a['n']:4d} {a['wr']:6.1f} {a['mean']:+8.3f} {a['med']:+8.3f} "
              f"{a['best']:+7.2f} {a['worst']:+7.2f} {a['avg_bars']:5.1f} | "
              f"{a['usd']:+9.2f} {a['ex_top2']:+9.2f} {a['t']:+6.2f} | {f:%Y-%m-%d} -> {l:%Y-%m-%d}")


def reason_mix(led: pd.DataFrame, label: str) -> None:
    g = led.groupby("reason").agg(n=("ret_pct", "size"), mean=("ret_pct", "mean"),
                                  usd=("paper_pnl_usd", "sum"))
    tot = len(led)
    print(f"  {label}: " + "  |  ".join(
        f"{k} n={int(v['n'])} ({100*v['n']/tot:.0f}%) mean={v['mean']:+.2f}% ${v['usd']:+.0f}"
        for k, v in g.iterrows()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="only count fires entered on/after this date")
    args = ap.parse_args()
    now = datetime.now(timezone.utc)

    v52 = _load("fires_ledger.csv")
    v53 = _load("v53_fires_ledger.csv")
    # V52 writes a row per sleeve with state FLAT/OPEN; V53 writes only open rows.
    p52_all = _load("positions_latest.csv")
    p52 = p52_all[p52_all.state == "OPEN"] if "state" in p52_all.columns else p52_all
    pend52 = _load("pending_fires_latest.csv")
    p53, pend53 = _load("v53_positions_latest.csv"), _load("v53_pending_fires_latest.csv")
    n_flat52 = int((p52_all.state == "FLAT").sum()) if "state" in p52_all.columns else 0
    xsm = _load("xsm_status.csv")
    rl52, rl53 = _load("run_log.csv"), _load("v53_run_log.csv")

    for d in (v52, v53):
        if len(d):
            d["entry_ts"] = pd.to_datetime(d["entry_ts"])
            d["exit_ts"] = pd.to_datetime(d["exit_ts"])
    if args.since:
        cut = pd.Timestamp(args.since, tz="UTC")
        v52, v53 = v52[v52.entry_ts >= cut], v53[v53.entry_ts >= cut]

    hdr(f"HL PAPER SHADOW REPORT — generated {now:%Y-%m-%d %H:%M:%S} UTC"
        + (f"  (filtered: entries >= {args.since})" if args.since else ""))
    print("  Mode: PAPER — no real orders, $0 at risk. Notional/sleeve = $250 (display only).")
    print(f"  Scheduler: Windows task 'V52Shadow', hourly.")
    if len(rl52):
        print(f"  V52 ticks logged: {len(rl52)}   last: {rl52.iloc[-1]['run_ts']}")
    if len(rl53):
        print(f"  V53 ticks logged: {len(rl53)}   last: {rl53.iloc[-1]['run_ts']}")

    # ------------------------------------------------------------------ V52
    hdr("FLEET 1 — V52  (9 hand-picked sleeves; the incumbent)", "=")
    if len(v52):
        c = v52[v52.status == "CLOSED"]
        a = agg(c)
        print(f"  closed trades {a['n']}  |  window {pd.to_datetime(c.entry_ts).min():%Y-%m-%d} -> "
              f"{pd.to_datetime(c.exit_ts).max():%Y-%m-%d}  |  OPEN now {len(p52)}  FLAT {n_flat52}  "
              f"pending {len(pend52)}")
        print(f"  pooled: mean {a['mean']:+.3f}%/tr   WR {a['wr']:.1f}%   t {a['t']:+.2f}   "
              f"paper ${a['usd']:+,.2f}   ex-top2 ${a['ex_top2']:+,.2f}")
        print()
        sleeve_table(c, "sleeve")
        print()
        reason_mix(c, "exit mix")
        # pre-registered live slice
        fwd = c[c.entry_ts >= pd.Timestamp(SHADOW_START, tz="UTC")]
        if len(fwd):
            b = agg(fwd)
            print(f"\n  PRE-REGISTERED LIVE SLICE (entries >= {SHADOW_START}): n={b['n']} "
                  f"mean={b['mean']:+.3f}% WR={b['wr']:.1f}% t={b['t']:+.2f} "
                  f"paper=${b['usd']:+,.2f} ex-top2=${b['ex_top2']:+,.2f}")
    else:
        print("  no ledger rows")

    if len(p52):
        print("\n  OPEN NOW:")
        for _, r in p52.iterrows():
            print(f"    {str(r['sleeve']):12s} {str(r['direction']):5s} entry {r['entry_ts']} "
                  f"@ {r['entry_price']:>10}  bars {int(r['bars_held']):>3}  "
                  f"unreal {float(r['unrealized_pct']):+.2f}% (${float(r['unrealized_usd']):+.2f})")

    # ------------------------------------------------------------------ V53
    hdr("FLEET 2 — V53 BREADTH  (2 validated families x 10 coins = 20 streams)", "=")
    if len(v53):
        c = v53[v53.status == "CLOSED"]
        a = agg(c)
        print(f"  closed trades {a['n']}  |  window {pd.to_datetime(c.entry_ts).min():%Y-%m-%d} -> "
              f"{pd.to_datetime(c.exit_ts).max():%Y-%m-%d}  |  open now {len(p53)}  pending {len(pend53)}")
        span = max((pd.to_datetime(c.entry_ts).max() - pd.to_datetime(c.entry_ts).min()).days, 1)
        print(f"  fire rate: {len(c)/span*30:.1f} closed trades / 30d")
        print()
        print("  --- BY ARM (reported separately on purpose: pooling lets one arm hide the other) ---")
        sleeve_table(c, "arm")
        print()
        print("  --- BY FAMILY ---")
        sleeve_table(c, "family")
        print()
        for arm in sorted(c.arm.unique()):
            sub = c[c.arm == arm]
            print(f"  --- {arm} arm, per stream ---")
            sleeve_table(sub, "sleeve")
            reason_mix(sub, f"{arm} exit mix")
            print()
    else:
        print("  no ledger rows")

    if len(p53):
        print("  OPEN NOW:")
        for _, r in p53.sort_values(["arm", "sleeve"]).iterrows():
            print(f"    [{r['arm']:7s}] {r['sleeve']:10s} {r['direction']:5s} entry {r['entry_ts']} "
                  f"@ {r['entry_price']}  bars {r['bars_held']:>3}  unreal {r['unreal_pct']:+.2f}% "
                  f"(${r['unreal_usd']:+.2f})")

    # ------------------------------------------------------------------ XSM
    hdr("FLEET 3 — V24-XSM  (cross-sectional momentum basket)", "=")
    if len(xsm):
        r = xsm.iloc[-1]
        print("  " + "  ".join(f"{k}={r[k]}" for k in xsm.columns))
        print("\n  FLAT is the designed behaviour when the multi_filter fails — it is a defensive")
        print("  filter (needs BTC>100dMA AND 50dMA rising AND breadth>=5/9), not a bug.")
    else:
        print("  no status rows")

    # ------------------------------------------------------------------ combined
    hdr("COMBINED PAPER PnL (both fleets, all-time in ledger)", "=")
    rows = []
    if len(v52):
        rows.append(("V52 (9 sleeves)", agg(v52[v52.status == "CLOSED"])))
    if len(v53):
        cc = v53[v53.status == "CLOSED"]
        rows.append(("V53 DEPLOY (STF)", agg(cc[cc.arm == "DEPLOY"])))
        rows.append(("V53 OBSERVE (VP)", agg(cc[cc.arm == "OBSERVE"])))
    print(f"{'fleet':20s} {'n':>5s} {'WR%':>6s} {'mean%':>8s} {'t':>6s} {'paper$':>10s} {'ex-top2$':>10s}  capital-eligible?")
    print("-" * 110)
    elig = {"V52 (9 sleeves)": "NO - 5/9 sleeves on non-validated families",
            "V53 DEPLOY (STF)": "YES - after the shadow gate",
            "V53 OBSERVE (VP)": "NO - t=-3.38 forward, logged only"}
    for name, a in rows:
        print(f"{name:20s} {a['n']:5d} {a['wr']:6.1f} {a['mean']:+8.3f} {a['t']:+6.2f} "
              f"{a['usd']:+10.2f} {a['ex_top2']:+10.2f}  {elig.get(name,'')}")
    print("\n  Reminder: paper PnL at $250/sleeve is a SIGNAL of behaviour, not an earnings")
    print("  forecast. Judge on mean%/trade, t, and ex-top2 (outlier dependence) — not $.")


if __name__ == "__main__":
    main()
