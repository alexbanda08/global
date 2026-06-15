"""
_mm_q5_filltiming.py — Instrument the Q=5 maker-only sim to capture per-fill OFFSET timing.

Goal: answer whether OUR sim captures late-window (final 200s, off>=700) fills or tapers,
and at what paired-sum (pvs). Mirrors _mm_inv_engine.sim_slug EXACTLY (Q=5, gamma=0.05,
budget=350, offset=-3600, FIFO) but logs each fill's (offset_s, side, price, shares).

Runs on a sample of slugs (default 400) for memory safety, then aggregates fill timing
by offset bucket and computes a completion-time FIFO paired pvs by window (same method as
the b945 ground-truth analysis), so his vs ours is apples-to-apples.

Output: D:/tmp_edge/_mm_q5_filltiming.parquet  (per-fill rows: slug, off, side, price, sh)
        + prints the by-window paired-edge table.
"""
import sys, os, time
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
L25_PATH  = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / "btc.parquet"
TR_PATH   = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / "btc.parquet"
RES_PATH  = ROOT / "data" / "v4" / "canonical" / "resolutions.parquet"

WINDOW_S = 900
CLIP_USD = 5.0
REBATE_SH = 0.0015
Q_CAP = 5.0
GAMMA = 0.05
BUDGET = 350.0
OFFSET = -3600
SIGMA = 0.5
OUT = Path(r"D:\tmp_edge\_mm_q5_filltiming.parquet")
OUT.parent.mkdir(parents=True, exist_ok=True)


def load_resolutions():
    r = pd.read_parquet(RES_PATH, columns=["slug", "slot_start_us", "outcome"])
    r = r[r.slug.str.contains("btc-updown-15m", na=False, regex=False)]
    r = r[r.slot_start_us >= int(pd.Timestamp("2026-04-22", tz="UTC").timestamp() * 1e6)]
    r = r.drop_duplicates("slug")
    r["slot_start_s"] = (r["slot_start_us"] // 1_000_000).astype(int)
    return r.reset_index(drop=True)


def load_books(slug_set):
    bp_names = [f"bid_price_{i}" for i in range(5)]
    bs_names = [f"bid_size_{i}" for i in range(5)]
    cols = ["timestamp_us", "slug", "outcome"] + bp_names + bs_names
    f = pq.ParquetFile(L25_PATH)
    parts = []
    for i in range(f.num_row_groups):
        df = f.read_row_group(i, columns=cols).to_pandas()
        df = df[df.slug.isin(slug_set)]
        if len(df):
            parts.append(df)
    if not parts:
        return {}
    B = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
    out = {}
    for (sl, oc), g in B.groupby(["slug", "outcome"], observed=True, sort=False):
        g = g.sort_values("timestamp_us")
        out[(sl, oc)] = {"ts": g["timestamp_us"].to_numpy(np.int64),
                         "bp": g[bp_names].to_numpy(np.float64),
                         "bs": g[bs_names].to_numpy(np.float64)}
    return out


def load_trades(slug_set):
    f = pq.ParquetFile(TR_PATH)
    parts = []
    for i in range(f.num_row_groups):
        df = f.read_row_group(i, columns=["timestamp_us", "slug", "outcome", "price", "size", "side"]).to_pandas()
        df = df[df.slug.isin(slug_set) & (df["side"].str.lower() == "sell")]
        if len(df):
            parts.append(df)
    if not parts:
        return {}
    T = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
    out = {}
    for (sl, oc), g in T.groupby(["slug", "outcome"], observed=True, sort=False):
        g = g.sort_values("timestamp_us")
        out[(sl, oc)] = {"ts": g["timestamp_us"].to_numpy(np.int64),
                         "px": g["price"].to_numpy(np.float64),
                         "sz": g["size"].to_numpy(np.float64)}
    return out


def _qa_at(bk, at_us, level_price):
    ts = bk["ts"]; bp = bk["bp"]; bs = bk["bs"]
    j = max(0, min(int(np.searchsorted(ts, at_us, "right")) - 1, len(ts) - 1))
    qa = 0.0
    for lvl in range(5):
        p = bp[j, lvl]; s = bs[j, lvl]
        if not np.isfinite(p):
            break
        if p > level_price + 1e-6:
            if np.isfinite(s) and s > 0:
                qa += s
        elif abs(p - level_price) < 1e-6:
            if np.isfinite(s) and s > 0:
                qa += s
            break
        else:
            break
    return qa


def _bid_at(bk, at_us):
    ts = bk["ts"]; bp = bk["bp"]
    j = max(0, min(int(np.searchsorted(ts, at_us, "right")) - 1, len(ts) - 1))
    p = bp[j, 0]
    return float(p) if np.isfinite(p) else float("nan")


def sim_slug_timed(bk_up, tr_up, bk_dn, tr_dn, slot_s, offset_s, budget, Q_cap, gamma,
                   use_upper=False, sigma=0.5):
    """EXACT copy of _mm_inv_engine.sim_slug + per-fill (offset_s, side, price, sh) log."""
    t_place = (slot_s + offset_s) * 1_000_000
    t_end   = (slot_s + WINDOW_S) * 1_000_000
    slot_us = slot_s * 1_000_000
    fills_log = []  # (off_s, tag, price, sh)

    sides = {}
    for tag, bk in (("up", bk_up), ("dn", bk_dn)):
        if bk is None:
            sides[tag] = None; continue
        init_bid = _bid_at(bk, t_place)
        if not np.isfinite(init_bid) or init_bid <= 0:
            sides[tag] = None; continue
        op = init_bid
        sides[tag] = {"bk": bk, "order_price": op, "order_qa": _qa_at(bk, t_place, op),
                      "remaining": min(CLIP_USD, budget) / op, "budget_left": budget,
                      "cur_bid": init_bid, "sh": 0.0, "cost": 0.0, "n_fills": 0, "n_req": 0,
                      "qa_place": _qa_at(bk, t_place, op), "active": True}

    events = []
    for tag, bk, tr in (("up", bk_up, tr_up), ("dn", bk_dn, tr_dn)):
        if bk is not None:
            ts = bk["ts"]; bp0 = bk["bp"][:, 0]
            lo = int(np.searchsorted(ts, t_place, "left")); hi = int(np.searchsorted(ts, t_end, "right"))
            for k in range(lo, hi):
                events.append((int(ts[k]), 0, tag, float(bp0[k])))
        if tr is not None:
            ts = tr["ts"]; px = tr["px"]; sz = tr["sz"]
            lo = int(np.searchsorted(ts, t_place, "left")); hi = int(np.searchsorted(ts, t_end, "right"))
            for k in range(lo, hi):
                events.append((int(ts[k]), 1, tag, (float(px[k]), float(sz[k]))))
    events.sort(key=lambda e: (e[0], e[1]))

    def net_residual(tag):
        other = "dn" if tag == "up" else "up"
        s_this = sides[tag]["sh"] if sides[tag] else 0.0
        s_other = sides[other]["sh"] if sides[other] else 0.0
        return s_this - s_other

    def apply_glt(tag):
        if not np.isfinite(Q_cap):
            return
        q = net_residual(tag)
        if sides[tag]:
            sides[tag]["active"] = (q <= Q_cap)

    def skewed_price(tag, base_bid, ev_ts):
        if gamma <= 0:
            return min(base_bid, 0.99)
        q = net_residual(tag)
        time_left = max(0.0, (t_end - ev_ts) / (WINDOW_S * 1_000_000))
        q_norm = q / 100.0
        skew = -q_norm * gamma * (sigma ** 2) * time_left
        p = base_bid + skew
        return min(max(p, 0.01), 0.99)

    for ev_ts, kind, tag, payload in events:
        s = sides[tag]
        if s is None:
            continue
        if kind == 0:
            new_bid = payload
            if np.isfinite(new_bid) and new_bid > 0 and abs(new_bid - s["cur_bid"]) > 1e-6:
                nl = skewed_price(tag, new_bid, ev_ts)
                if abs(nl - s["order_price"]) > 1e-6 and s["remaining"] > 1e-6:
                    carry = s["remaining"] * s["order_price"]
                    s["order_price"] = nl
                    s["remaining"] = carry / nl
                    s["order_qa"] = _qa_at(s["bk"], ev_ts, nl)
                    s["n_req"] += 1
                s["cur_bid"] = new_bid
            apply_glt(tag)
        else:
            tp, ts2 = payload
            apply_glt(tag)
            if not s["active"] or s["remaining"] <= 1e-6 or s["budget_left"] <= 1e-6:
                continue
            fa = 0.0
            op = s["order_price"]
            if tp < op - 1e-6:
                fa = min(s["remaining"], ts2)
            elif abs(tp - op) < 1e-6:
                if use_upper:
                    denom = max(s["remaining"] + s["order_qa"], 1e-9)
                    fa = min(s["remaining"], ts2 * s["remaining"] / denom)
                    s["order_qa"] = max(0.0, s["order_qa"] - ts2 * s["order_qa"] / denom)
                else:
                    if s["order_qa"] >= ts2:
                        s["order_qa"] -= ts2
                    else:
                        fa = min(s["remaining"], ts2 - s["order_qa"])
                        s["order_qa"] = 0.0
            if fa > 1e-9:
                s["sh"] += fa
                s["cost"] += fa * op
                s["remaining"] -= fa
                s["budget_left"] -= fa * op
                s["n_fills"] += 1
                off_s = (ev_ts - slot_us) / 1_000_000.0  # offset relative to slot start
                fills_log.append((off_s, tag, op, fa))
                if s["remaining"] <= 1e-6 and s["budget_left"] > 1e-6:
                    nl = skewed_price(tag, s["cur_bid"], ev_ts)
                    s["order_price"] = nl
                    s["remaining"] = min(CLIP_USD, s["budget_left"]) / nl
                    s["order_qa"] = 0.0
                apply_glt(tag)
                other = "dn" if tag == "up" else "up"
                if sides[other]:
                    apply_glt(other)
    return fills_log


def main():
    t0 = time.time()
    n_sample = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    res = load_resolutions()
    all_slugs = sorted(res.slug.tolist())
    rng = np.random.default_rng(11)
    if len(all_slugs) > n_sample:
        sample = sorted(rng.choice(all_slugs, n_sample, replace=False).tolist())
    else:
        sample = all_slugs
    print(f"sample slugs: {len(sample)} of {len(all_slugs)}", flush=True)
    slug_set = set(sample)
    tob = load_books(slug_set); print(f"books {len(tob)} t={time.time()-t0:.0f}s", flush=True)
    trades = load_trades(slug_set); print(f"trades {len(trades)} t={time.time()-t0:.0f}s", flush=True)
    slot_map = dict(zip(res.slug, res.slot_start_s))

    rows = []
    for slug in sample:
        slot_s = slot_map.get(slug)
        if slot_s is None:
            continue
        fl = sim_slug_timed(tob.get((slug, "Up")), trades.get((slug, "Up")),
                            tob.get((slug, "Down")), trades.get((slug, "Down")),
                            slot_s, OFFSET, BUDGET, Q_CAP, GAMMA, use_upper=False)
        for off_s, tag, px, sh in fl:
            rows.append((slug, off_s, tag, px, sh))
    df = pd.DataFrame(rows, columns=["slug", "off", "side", "price", "shares"])
    df.to_parquet(OUT, index=False)
    print(f"saved {OUT}: {len(df)} fills, {df.slug.nunique()} slugs  t={time.time()-t0:.0f}s")

    # Only intra-window fills carry an offset 0-900; pre-window fills have off<0.
    print(f"\noff range: {df.off.min():.0f} .. {df.off.max():.0f}")
    print(f"pre-window fills (off<0): {(df.off<0).sum()} ({(df.off<0).mean()*100:.1f}%)")
    intra = df[(df.off >= 0) & (df.off <= 900)].copy()
    print(f"intra-window fills: {len(intra)}")
    print("\n=== OUR SIM fill distribution by window (intra) ===")
    for lo, hi, lab in [(0,300,'0-300'),(300,500,'300-500'),(500,700,'500-700'),(700,900,'700-900 FINAL200'),(850,901,'  850-900 final50')]:
        m = (intra.off >= lo) & (intra.off < hi) if hi < 901 else (intra.off >= lo) & (intra.off <= 900)
        sub = intra[m]
        print(f"{lab:18s} n={len(sub):6d} ({len(sub)/len(intra)*100:5.1f}%) sh={sub.shares.sum():8.0f} ({sub.shares.sum()/intra.shares.sum()*100:5.1f}%) avgpx={sub.price.mean():.3f}")


if __name__ == "__main__":
    main()
