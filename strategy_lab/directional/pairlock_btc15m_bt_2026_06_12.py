"""
pairlock_btc15m_bt_2026_06_12.py — backtest of the b945-decoded PAIR-LOCK mechanic
on OUR validated lag entry (spec: SPEC_B945_EVLAYER_PAIRLOCK_2026_06_11.md,
TV_AGENT_SPEC_PAIRLOCK_BTC15M_SHADOW_2026_06_12.md).

Logic per market (btc-updown-15m):
  A1  enter signal side at fire (+5s lag entry from lag_taker_fires_oos universe), $5 stake.
  A2  from fire to slot_start+870s: whenever the OPPOSITE token's ask completes the pair at
      blended cost <= PAIR_TARGET, taker-buy the matching shares (multi-clip, size-capped via
      resolve_size; fill price re-checked asof +85ms latency). No sells. Hold both to resolution.
  PnL matched pairs: q*[(1-p_w)(1-0.07 p_w) - p_l]   (winner-only 0.07 on the winning leg)
      residual:       held_value(rem, ev, won)         (corrected-lib settlement valuation)
  CONTROL: identical A1 fires, deployed scalp exit (+60s time sell via exit_fill).

Arms (pre-registered trial count = 2 arms x 5 targets = 10 cells):
  ARM A (primary): delta>=3 AND entry_vwap<0.55  (production scalp entry config)
  ARM B          : delta>=3 any vwap             (does pair-lock widen the safe entry set?)
  PAIR_TARGET sweep: 0.99 / 0.97 / 0.95 / 0.93 / 0.90

Bankroll sim: $300 start, chronological, capital locked fire -> slot_end+60s,
per-market outlay cap $30, skip fire if free capital < $10.

Usage: py -3 strategy_lab/directional/pairlock_btc15m_bt_2026_06_12.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
from load import load_orderbook_l25_streaming                      # noqa: E402
from scalp_fill_lib_2026_06_10 import resolve_size, held_value, exit_fill, boot  # noqa: E402

FIRES = ROOT / "strategy_lab" / "lag_taker_fires_oos_2026_06_01.parquet"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
LAT_US = 85_000          # 85 ms
STAKE = 5.0
WIN_S = 900
HEDGE_STOP_S = 870
MKT_CAP = 30.0
BANKROLL0 = 300.0
TARGETS = [0.99, 0.97, 0.95, 0.93, 0.90]
FEE = 0.07


def pair_locked_pnl(q, p_w, p_l):
    """matched-pair settlement: winning leg pays winner-only fee, losing leg costs its price."""
    return q * ((1 - p_w) * (1 - FEE * p_w) - p_l)


def simulate_market(rec_opp, fire_us, slot_start, ev, shares, won, target, budget):
    """A2 hedge loop on the OPPOSITE token. Returns dict with hedge fills + settlement pnl."""
    p_star = target - ev
    stop_us = (slot_start + HEDGE_STOP_S) * 1_000_000
    q_opp, c_opp = 0.0, 0.0
    if rec_opp is not None and p_star > 0.005:
        ts, ap, asz, bp, bsz = rec_opp
        a0 = ap[:, 0]; s0 = asz[:, 0]
        i = int(np.searchsorted(ts, fire_us, "left"))
        n = len(ts)
        while i < n and ts[i] <= stop_us and q_opp < shares - 1e-9:
            px = a0[i]
            if np.isfinite(px) and 0.0 < px <= p_star:
                # react with +85ms latency: fill at the asof book then, only if still <= p*
                j = int(np.searchsorted(ts, ts[i] + LAT_US, "right")) - 1
                j = max(j, i)
                pxj = a0[j]
                if np.isfinite(pxj) and 0.0 < pxj <= p_star:
                    depth, _car = resolve_size(ts, s0, j)
                    need = shares - q_opp
                    afford = max(budget - c_opp, 0.0) / pxj
                    fill = min(need, depth, afford)
                    if fill > 1e-9:
                        q_opp += fill
                        c_opp += fill * pxj
                    i = j
            i += 1
    matched = min(shares, q_opp)
    rem = shares - matched
    p_opp = (c_opp / q_opp) if q_opp > 0 else np.nan
    # settlement: our side won -> winning leg price = ev, losing = p_opp; else swapped
    if matched > 0:
        p_w, p_l = (ev, p_opp) if won else (p_opp, ev)
        locked = pair_locked_pnl(matched, p_w, p_l)
    else:
        locked = 0.0
    residual = held_value(rem, ev, won)
    # any over-hedge (q_opp>shares) impossible by construction
    return dict(q_opp=q_opp, c_opp=c_opp, matched=matched, p_opp=p_opp,
                pair_cost=(ev + p_opp) if q_opp > 0 else np.nan,
                locked=locked, residual=residual, pnl=locked + residual,
                completed=bool(matched >= shares - 1e-9))


def control_pnl(rec_own, fire_us, slot_start, ev, shares, won):
    """deployed scalp exit: +60s time sell on OUR token (corrected exit_fill)."""
    if rec_own is None:
        return held_value(shares, ev, won)
    ts, ap, asz, bp, bsz = rec_own
    je = int(np.searchsorted(ts, fire_us + LAT_US, "right")) - 1
    if je < 0:
        return held_value(shares, ev, won)
    ext = min(fire_us + 60_000_000, slot_start * 1_000_000 + WIN_S * 1_000_000)
    r = exit_fill(ts, bp[:, 0], bsz[:, 0], je, ext, shares, ev, won)
    return r["pnl"]


def main():
    t0 = time.time()
    F = pd.read_parquet(FIRES)
    F = F[(F.asset == "BTC") & (F.tf == "15m") & (F.delta_bps >= 3)].copy()
    F = F.sort_values("fire_us").reset_index(drop=True)
    print(f"universe: {len(F)} BTC-15m fires delta>=3 "
          f"(armA vwap<0.55: {(F.entry_vwap < 0.55).sum()})", flush=True)

    slugs = set(F.slug)
    books = load_orderbook_l25_streaming("btc", slugs=slugs, subsample_1hz=False)
    print(f"L25 loaded: {len(books)} (slug,outcome) series  t={time.time()-t0:.0f}s", flush=True)

    rows = []
    for _, r in F.iterrows():
        ev = float(r.entry_vwap)
        shares = STAKE / ev
        opp = "Down" if r.direction == "Up" else "Up"
        rec_opp = books.get((r.slug, opp))
        rec_own = books.get((r.slug, r.direction))
        won = bool(r.won)
        fire_us = int(r.fire_us); ss = int(r.slot_start)
        base = dict(slug=r.slug, fire_us=fire_us, slot_start=ss, ev=ev, shares=shares,
                    won=won, armA=bool(ev < 0.55),
                    ctrl=control_pnl(rec_own, fire_us, ss, ev, shares, won),
                    hold=held_value(shares, ev, won))
        for tgt in TARGETS:
            s = simulate_market(rec_opp, fire_us, ss, ev, shares, won, tgt,
                                budget=MKT_CAP - STAKE)
            base[f"pnl_{tgt}"] = s["pnl"]
            base[f"locked_{tgt}"] = s["locked"]
            base[f"resid_{tgt}"] = s["residual"]
            base[f"cost_{tgt}"] = STAKE * min(1.0, shares * ev / STAKE) + s["c_opp"]
            base[f"paircost_{tgt}"] = s["pair_cost"]
            base[f"comp_{tgt}"] = s["completed"]
        rows.append(base)
    R = pd.DataFrame(rows)
    R.to_parquet(OUT / "pairlock_btc15m_bt_2026_06_12.parquet", index=False)
    print(f"simulated {len(R)} markets  t={time.time()-t0:.0f}s", flush=True)

    def show(df, label):
        print(f"\n===== {label} (n={len(df)}) =====")
        m, t_, n = df.ctrl.mean(), np.nan, len(df)
        lo, hi = boot(df.ctrl.values)
        print(f"  CONTROL +60s sell : $/mkt {m:+.3f}  CI[{lo:+.3f},{hi:+.3f}]")
        lo, hi = boot(df.hold.values)
        print(f"  PURE HOLD         : $/mkt {df.hold.mean():+.3f}  CI[{lo:+.3f},{hi:+.3f}]")
        for tgt in TARGETS:
            p = df[f"pnl_{tgt}"]
            lo, hi = boot(p.values)
            comp = df[f"comp_{tgt}"].mean()
            pc = df[f"paircost_{tgt}"].dropna()
            d = p - df.ctrl
            dlo, dhi = boot(d.values)
            print(f"  PAIRLOCK tgt={tgt:.2f}: $/mkt {p.mean():+.3f}  CI[{lo:+.3f},{hi:+.3f}]"
                  f"  comp {comp:4.0%}  paircost_med {pc.median() if len(pc) else float('nan'):.3f}"
                  f"  locked {df[f'locked_{tgt}'].mean():+.3f}  resid {df[f'resid_{tgt}'].mean():+.3f}"
                  f"  | vs ctrl paired {d.mean():+.3f} CI[{dlo:+.3f},{dhi:+.3f}]")

    show(R[R.armA], "ARM A — delta>=3 & vwap<0.55 (production entry)")
    show(R, "ARM B — delta>=3 any vwap")

    # bankroll sim on ARM A, primary target 0.97 + best-by-armA (report both, trial-counted)
    def bankroll(df, tgt):
        cash, locked_until = BANKROLL0, []   # (release_us, amount)
        eq_pts, skipped = [], 0
        peak, mdd = BANKROLL0, 0.0
        equity = BANKROLL0
        for _, r in df.sort_values("fire_us").iterrows():
            now = r.fire_us
            locked_until = [(t, a) for (t, a) in locked_until if t > now] or []
            released = sum(a for (t, a) in locked_until if t <= now)
            free = cash - sum(a for (t, a) in locked_until)
            outlay = r[f"cost_{tgt}"]
            if free < 10.0:
                skipped += 1
                continue
            outlay = min(outlay, free)
            pnl = r[f"pnl_{tgt}"]
            cash += pnl
            locked_until.append(((r.slot_start + WIN_S + 60) * 1_000_000, outlay))
            equity = cash
            peak = max(peak, equity); mdd = min(mdd, equity - peak)
            eq_pts.append(equity)
        return equity, mdd, skipped, len(eq_pts)

    for tgt in [0.97, 0.93, 0.90]:
        eqA, mddA, skA, nA = bankroll(R[R.armA], tgt)
        eqB, mddB, skB, nB = bankroll(R, tgt)
        print(f"\nBANKROLL $300 tgt={tgt:.2f}:  ARM A final ${eqA:.2f} (MDD {mddA:+.2f},"
              f" {nA} mkts, {skA} skipped)   ARM B final ${eqB:.2f} (MDD {mddB:+.2f}, {nB} mkts)")
    print(f"\ntrials this script: 10 cells (2 arms x 5 targets) — count toward DSR")
    print(f"done t={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
