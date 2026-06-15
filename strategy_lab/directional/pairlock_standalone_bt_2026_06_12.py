"""
pairlock_standalone_bt_2026_06_12.py — STANDALONE replication of wallet 0xb945945d's
temporal pair-arb on btc-updown-15m. NO directional signal, NO fire universe — every window.

Mechanic (decoded from his tape):
  LEG1: t in [60, 600)s — buy the first leg when EITHER token's ask dips <= L1 threshold
        (his entries cluster mid-curve; dip = cheap leg of the moment). $5 clip.
  LEG2: t in [leg1, 870)s — buy the OTHER token when its ask completes the pair at
        blended cost <= TARGET. $5-equivalent shares (match leg1 shares).
  Hold both to resolution, redeem winner (winner-only 0.07 fee). No sells.
  Residual (uncompleted leg1) settles directionally.

Grid (trial-counted): L1 in {0.40, 0.45, 0.50} x TARGET in {0.93, 0.95, 0.97} = 9 cells.
Benchmark sanity arm: instant-pair at open (buy both asks at t=60s) — must be ~ -overround.

Fills: top-of-book asof, +85ms latency re-check, size via resolve_size (corrected lib).
Universe: ALL btc-updown-15m slugs with L25 books + canonical resolution, Apr 22 -> Jun 11.
Bankroll sim: $300, chronological, capital locked to settlement+60s.

Usage: py -3 strategy_lab/directional/pairlock_standalone_bt_2026_06_12.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
from load import load_resolutions                                   # noqa: E402
from scalp_fill_lib_2026_06_10 import resolve_size, boot            # noqa: E402

L25 = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / "btc.parquet"
OUT = ROOT / "strategy_lab" / "directional" / "_results"
LAT_US = 85_000
STAKE = 5.0
WIN_S = 900
FEE = 0.07
L1_GRID = [0.40, 0.45, 0.50]
TGT_GRID = [0.93, 0.95, 0.97]
LEG1_START, LEG1_STOP, HEDGE_STOP = 60, 600, 870
BANKROLL0 = 300.0


def load_tob_15m():
    """Stream only top-of-book cols for 15m slugs -> dict[(slug,outcome)] = (ts, a0, s0)."""
    cols = ["timestamp_us", "slug", "outcome", "ask_price_0", "ask_size_0"]
    f = pq.ParquetFile(L25)
    parts = []
    for i in range(f.num_row_groups):
        t = f.read_row_group(i, columns=cols)
        df = t.to_pandas()
        df = df[df.slug.str.contains("updown-15m", regex=False)]
        if len(df):
            parts.append(df)
    big = pd.concat(parts, ignore_index=True)
    del parts
    big = big.sort_values("timestamp_us")
    out = {}
    for k, g in big.groupby(["slug", "outcome"], sort=False, observed=True):
        out[k] = (g.timestamp_us.to_numpy(np.int64),
                  g.ask_price_0.to_numpy(np.float64),
                  g.ask_size_0.to_numpy(np.float64))
    return out


def fill_at(rec, i, p_max):
    """latency re-check then size-capped fill at row i; returns (px, depth_sh) or None."""
    ts, a0, s0 = rec
    j = int(np.searchsorted(ts, ts[i] + LAT_US, "right")) - 1
    j = max(j, i)
    px = a0[j]
    if not (np.isfinite(px) and 0.0 < px <= p_max):
        return None
    depth, _ = resolve_size(ts, s0, j)
    return float(px), float(depth), j


def sim_market(rec_up, rec_dn, ss, won_up, l1, tgt, instant=False):
    """one window. won_up: True if Up resolved winner. Returns dict or None (no books)."""
    if rec_up is None or rec_dn is None:
        return None
    t0 = (ss + LEG1_START) * 1_000_000
    t1 = (ss + LEG1_STOP) * 1_000_000
    t2 = (ss + HEDGE_STOP) * 1_000_000

    legs = {"Up": rec_up, "Down": rec_dn}
    if instant:
        # sanity arm: buy both at first valid quote after t0
        q = c = {}
        out = {}
        for side, rec in legs.items():
            ts, a0, s0 = rec
            i = int(np.searchsorted(ts, t0, "left"))
            while i < len(ts) and not (np.isfinite(a0[i]) and a0[i] > 0):
                i += 1
            if i >= len(ts) or ts[i] > t1:
                return None
            r = fill_at(rec, i, 1.0)
            if r is None:
                return None
            out[side] = r[0]
        sh = STAKE / out["Up"]
        p_w, p_l = (out["Up"], out["Down"]) if won_up else (out["Down"], out["Up"])
        pnl = sh * ((1 - p_w) * (1 - FEE * p_w) - p_l)
        return dict(pnl=pnl, completed=True, paircost=out["Up"] + out["Down"],
                    cost=sh * (out["Up"] + out["Down"]), resid=0.0, locked=pnl, fired=True)

    # LEG1: first token whose ask dips <= l1 inside [t0, t1)
    cand = []
    for side, rec in legs.items():
        ts, a0, s0 = rec
        lo = int(np.searchsorted(ts, t0, "left"))
        hi = int(np.searchsorted(ts, t1, "left"))
        seg = a0[lo:hi]
        ok = np.where(np.isfinite(seg) & (seg > 0.02) & (seg <= l1))[0]
        if len(ok):
            cand.append((ts[lo + ok[0]], lo + ok[0], side))
    if not cand:
        return dict(pnl=0.0, completed=False, paircost=np.nan, cost=0.0,
                    resid=0.0, locked=0.0, fired=False)
    cand.sort()
    _, i1, side1 = cand[0]
    rec1 = legs[side1]
    r1 = fill_at(rec1, i1, l1)
    if r1 is None:
        return dict(pnl=0.0, completed=False, paircost=np.nan, cost=0.0,
                    resid=0.0, locked=0.0, fired=False)
    p1, depth1, j1 = r1
    sh = min(STAKE / p1, depth1)
    if sh * p1 < STAKE * 0.5:
        return dict(pnl=0.0, completed=False, paircost=np.nan, cost=0.0,
                    resid=0.0, locked=0.0, fired=False)

    # LEG2: other token ask <= tgt - p1, from leg1 fill to t2
    side2 = "Down" if side1 == "Up" else "Up"
    rec2 = legs[side2]
    ts2, a2, s2 = rec2
    p_star = tgt - p1
    p2 = None
    if p_star > 0.005:
        lo = int(np.searchsorted(ts2, rec1[0][j1], "left"))
        hi = int(np.searchsorted(ts2, t2, "left"))
        seg = a2[lo:hi]
        ok = np.where(np.isfinite(seg) & (seg > 0.0) & (seg <= p_star))[0]
        for k in ok:
            r2 = fill_at(rec2, lo + int(k), p_star)
            if r2 is not None:
                p2, depth2, _ = r2
                break
    won1 = (side1 == "Up") == won_up
    if p2 is not None:
        sh2 = min(sh, depth2)
        matched, rem = sh2, sh - sh2
        p_w, p_l = (p1, p2) if won1 else (p2, p1)
        locked = matched * ((1 - p_w) * (1 - FEE * p_w) - p_l)
        resid = rem * ((1 - p1) * (1 - FEE * p1)) if won1 else -rem * p1
        return dict(pnl=locked + resid, completed=bool(rem < 1e-9), paircost=p1 + p2,
                    cost=sh * p1 + matched * p2, resid=resid, locked=locked, fired=True)
    resid = sh * ((1 - p1) * (1 - FEE * p1)) if won1 else -sh * p1
    return dict(pnl=resid, completed=False, paircost=np.nan, cost=sh * p1,
                resid=resid, locked=0.0, fired=True)


def main():
    t0 = time.time()
    res = load_resolutions()
    res = res[res.slug.str.contains("btc-updown-15m", regex=False)]
    win_up = {}
    oc = "outcome" if "outcome" in res.columns else None
    for _, r in res.iterrows():
        win_up[r.slug] = (str(r[oc]).lower() in ("up", "true", "1"))
    print(f"resolutions: {len(win_up)} btc-15m slugs", flush=True)

    books = load_tob_15m()
    slugs = sorted({s for (s, _o) in books} & set(win_up),
                   key=lambda s: int(s.rsplit("-", 1)[1]))
    print(f"L25 top-of-book: {len(books)} series, {len(slugs)} usable slugs "
          f"t={time.time()-t0:.0f}s", flush=True)

    rows = []
    for slug in slugs:
        ss = int(slug.rsplit("-", 1)[1])
        ru, rd = books.get((slug, "Up")), books.get((slug, "Down"))
        wu = win_up[slug]
        base = dict(slug=slug, ss=ss)
        sane = sim_market(ru, rd, ss, wu, 0, 0, instant=True)
        base["instant_pnl"] = sane["pnl"] if sane else np.nan
        base["instant_paircost"] = sane["paircost"] if sane else np.nan
        for l1 in L1_GRID:
            for tgt in TGT_GRID:
                s = sim_market(ru, rd, ss, wu, l1, tgt)
                if s is None:
                    continue
                tag = f"{l1:.2f}_{tgt:.2f}"
                base[f"pnl_{tag}"] = s["pnl"]; base[f"fired_{tag}"] = s["fired"]
                base[f"comp_{tag}"] = s["completed"]; base[f"pc_{tag}"] = s["paircost"]
                base[f"cost_{tag}"] = s["cost"]; base[f"lock_{tag}"] = s["locked"]
                base[f"res_{tag}"] = s["resid"]
        rows.append(base)
    R = pd.DataFrame(rows)
    R.to_parquet(OUT / "pairlock_standalone_bt_2026_06_12.parquet", index=False)
    print(f"simulated {len(R)} windows t={time.time()-t0:.0f}s", flush=True)

    ip = R.instant_pnl.dropna()
    print(f"\nSANITY instant-pair: $/mkt {ip.mean():+.4f} (n={len(ip)}, "
          f"paircost_med {R.instant_paircost.median():.3f}) — expect ~ -overround", flush=True)

    print(f"\n{'cell':>12} {'fired':>6} {'fire%':>6} {'comp%':>6} {'pc_med':>7} "
          f"{'$/fired':>9} {'CI95':>20} {'lock':>7} {'resid':>7} {'$/day':>7}")
    days = (R.ss.max() - R.ss.min()) / 86400
    best = None
    for l1 in L1_GRID:
        for tgt in TGT_GRID:
            tag = f"{l1:.2f}_{tgt:.2f}"
            if f"pnl_{tag}" not in R.columns:
                continue
            fired = R[R[f"fired_{tag}"] == True]          # noqa: E712
            p = fired[f"pnl_{tag}"].dropna()
            if not len(p):
                continue
            lo, hi = boot(p.values)
            comp = fired[f"comp_{tag}"].mean()
            pc = fired[f"pc_{tag}"].dropna().median()
            perday = p.sum() / days
            print(f"{tag:>12} {len(fired):>6} {len(fired)/len(R):>6.0%} {comp:>6.0%} "
                  f"{pc:>7.3f} {p.mean():>+9.4f} [{lo:+.4f},{hi:+.4f}] "
                  f"{fired[f'lock_{tag}'].mean():>+7.3f} {fired[f'res_{tag}'].mean():>+7.3f} "
                  f"{perday:>+7.2f}")
            if best is None or p.mean() > best[1]:
                best = (tag, p.mean())

    # bankroll on best cell + primary 0.45_0.95
    def bankroll(tag):
        cash = BANKROLL0; lockedq = []; peak = BANKROLL0; mdd = 0.0; nsk = 0; n = 0
        for _, r in R.sort_values("ss").iterrows():
            if f"fired_{tag}" not in R.columns or r.get(f"fired_{tag}") != True:  # noqa: E712
                continue
            now = r.ss * 1_000_000
            lockedq = [(t, a) for (t, a) in lockedq if t > now]
            free = cash - sum(a for (t, a) in lockedq)
            cost = r[f"cost_{tag}"]
            if free < cost:
                nsk += 1
                continue
            cash += r[f"pnl_{tag}"]
            lockedq.append(((r.ss + WIN_S + 60) * 1_000_000, cost))
            peak = max(peak, cash); mdd = min(mdd, cash - peak); n += 1
        return cash, mdd, n, nsk

    for tag in {best[0], "0.45_0.95"}:
        eq, mdd, n, nsk = bankroll(tag)
        print(f"\nBANKROLL $300 cell {tag}: final ${eq:.2f} (MDD {mdd:+.2f}, {n} mkts, "
              f"{nsk} skipped) over {days:.0f} days")
    print(f"\ntrials: 9 cells + sanity — count toward DSR. done t={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
