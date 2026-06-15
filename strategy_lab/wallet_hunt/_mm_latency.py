"""
_mm_latency.py — Requote-latency sensitivity on the VALIDATED inventory config.

MODEL: b945's flow-capture edge = he re-posts to the FRONT of each new best-bid level fast.
Parameterize requote latency L: when best bid moves at t (L25 best-bid change), we cancel and
re-post at the new level at t+L. queue_ahead at the new level = competition that accumulated
during [t, t+L]:
    qa(L) = max(
        trade_volume printed at price >= new_level during [t, t+L]   (μs-resolved tape),
        L25 displayed depth at price >= new_level at time t+L         (100ms-floored book)
    )
At L=0: qa=0 (front of a fresh level) -> high flow capture.
At L=inf (passive): the order never chases; it sits at the original placement level and only
    fills when the wandering market returns -> the current ~9% passive capture.

RESOLUTION FLOOR (stated honestly): L25 is 10Hz (median inter-event 186ms, p25=42ms, only 8%
<10ms). The trade tape IS μs-resolved (14% of inter-arrivals <1ms, 15% <10ms). So the
COMPETITION-AHEAD term (taker prints filling the level before us) is resolved sub-100ms; the
DISPLAYED-DEPTH term is floored at ~100ms. For L < 100ms we rely on the tape's μs arrivals and
take the L25 depth snapshot nearest t+L (so sub-100ms L's depth term is approximate, but the
tape term — which is what actually fills ahead of us — is exact). This is stated per-cell.

Config: VALIDATED inventory cell = GLT Q=20, AS skew gamma=0.05, budget $350/side, -3600s.
Sweep L in {0, 50ms, 100ms, 200ms, 500ms, 1s, 2s, passive}. FIFO lower bound.

DECISION RULE (pre-registered): largest (slowest) L with OOS net CI95 lower bound > 0.
  L >= 100ms  -> GO (Ireland <2ms RTT + 100ms poll can hit it).
  L < 10ms    -> MARGINAL (needs co-loc + pre-signed sub-tick requote).
  no L works  -> NO-GO offline confirmed.
"""
import sys, time
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab" / "wallet_hunt"))
from _mm_inv_engine import (load_resolutions, load_books, load_trades, slug_pnl, boot,
                            _qa_at, _bid_at, WINDOW_S, CLIP_USD)

CACHE_DIR = ROOT / "strategy_lab" / "wallet_hunt" / "cache"
IS_CUT = int(pd.Timestamp("2026-05-21", tz="UTC").timestamp() * 1e6)

# Validated config
BUDGET = 350.0
Q_CAP  = 20.0
GAMMA  = 0.05
OFFSET = -3600
SIGMA  = 0.5


def _trade_vol_ahead(tr, t0_us, L_us, level_price):
    """Taker volume printed at price >= level_price during [t0, t0+L]. μs-resolved."""
    if tr is None or L_us <= 0:
        return 0.0
    tts = tr["ts"]; tpx = tr["px"]; tsz = tr["sz"]
    lo = int(np.searchsorted(tts, t0_us, "left"))
    hi = int(np.searchsorted(tts, t0_us + L_us, "right"))
    if hi <= lo:
        return 0.0
    seg_px = tpx[lo:hi]; seg_sz = tsz[lo:hi]
    m = seg_px >= level_price - 1e-6
    return float(seg_sz[m].sum())


def sim_slug_latency(bk_up, tr_up, bk_dn, tr_dn, slot_s, offset_s, L_us, use_upper=False,
                     improve_ticks=0):
    """Joint two-sided sim with latency-aware requote queue_ahead.

    On a best-bid move at t to new_level, we re-post at t+L; queue_ahead at the new level =
    max(trade-vol-ahead during [t,t+L], L25 displayed depth at t+L). L_us = inf -> passive
    (never chase: order stays at its current level; book moves leave us behind, qa from L25).

    improve_ticks: post improve_ticks*TICK ABOVE the best bid (price-improvement / queue jump).
    DIAGNOSIS (2026-06-13): 56% of b945 fills are ABOVE the prior best bid -> his real mechanic
    is price-improvement, not pure requote-latency. With improve_ticks=0 (join best bid) the
    latency lever is a no-op because 48% of sell flow prints above a passive joiner and is missed.
    """
    TICK = 0.01
    t_place = (slot_s + offset_s) * 1_000_000
    t_end   = (slot_s + WINDOW_S) * 1_000_000
    passive = not np.isfinite(L_us)

    def improved(bid):
        # post improve_ticks above best bid, capped just under the ask region (<=0.99)
        return min(round(bid + improve_ticks * TICK, 4), 0.99)

    sides = {}
    for tag, bk in (("up", bk_up), ("dn", bk_dn)):
        if bk is None:
            sides[tag] = None; continue
        ib = _bid_at(bk, t_place)
        if not np.isfinite(ib) or ib <= 0:
            sides[tag] = None; continue
        op0 = improved(ib)
        sides[tag] = dict(bk=bk, order_price=op0, order_qa=_qa_at(bk, t_place, op0),
                          remaining=min(CLIP_USD, BUDGET) / op0, budget_left=BUDGET,
                          cur_bid=ib, sh=0., cost=0., n_fills=0, active=True)

    events = []
    trmap = {"up": tr_up, "dn": tr_dn}
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

    def net_res(tag):
        other = "dn" if tag == "up" else "up"
        st = sides[tag]["sh"] if sides[tag] else 0.0
        so = sides[other]["sh"] if sides[other] else 0.0
        return st - so

    def apply_glt(tag):
        if sides[tag] is None:
            return
        sides[tag]["active"] = (net_res(tag) <= Q_CAP)

    def skew(tag, base_bid, ev_ts):
        # base_bid is the current best bid; we improve by improve_ticks then skew for inventory
        base = improved(base_bid)
        if GAMMA <= 0:
            return min(base, 0.99)
        q = net_res(tag); tl = max(0., (t_end - ev_ts) / (WINDOW_S * 1_000_000))
        return min(max(base - (q / 100.0) * GAMMA * (SIGMA ** 2) * tl, 0.01), 0.99)

    for ev_ts, kind, tag, payload in events:
        s = sides[tag]
        if s is None:
            continue
        if kind == 0:
            nb = payload
            if np.isfinite(nb) and nb > 0 and abs(nb - s["cur_bid"]) > 1e-6:
                if not passive:
                    # chase: re-post at new level at t+L; qa = competition accumulated in [t, t+L]
                    nl = skew(tag, nb, ev_ts)
                    if abs(nl - s["order_price"]) > 1e-6 and s["remaining"] > 1e-6:
                        carry = s["remaining"] * s["order_price"]
                        s["order_price"] = nl
                        s["remaining"] = carry / nl
                        # latency-aware queue_ahead at the NEW level
                        qa_tape = _trade_vol_ahead(trmap[tag], ev_ts, L_us, nl)
                        qa_book = _qa_at(s["bk"], ev_ts + L_us, nl)
                        s["order_qa"] = max(qa_tape, qa_book)
                # passive: do NOT chase — order_price stays; just track cur_bid
                s["cur_bid"] = nb
            apply_glt(tag)
        else:
            tp, ts2 = payload
            apply_glt(tag)
            if not s["active"] or s["remaining"] <= 1e-6 or s["budget_left"] <= 1e-6:
                continue
            fa = 0.0; op = s["order_price"]
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
                        fa = min(s["remaining"], ts2 - s["order_qa"]); s["order_qa"] = 0.0
            if fa > 1e-9:
                s["sh"] += fa; s["cost"] += fa * op; s["remaining"] -= fa
                s["budget_left"] -= fa * op; s["n_fills"] += 1
                if s["remaining"] <= 1e-6 and s["budget_left"] > 1e-6:
                    nl = skew(tag, s["cur_bid"] if not passive else op, ev_ts)
                    s["order_price"] = nl
                    s["remaining"] = min(CLIP_USD, s["budget_left"]) / nl
                    # re-entry after a fill: at our own level, front of fresh queue (qa=0)
                    s["order_qa"] = 0.0
                apply_glt(tag)
                other = "dn" if tag == "up" else "up"
                if sides[other]:
                    apply_glt(other)

    out = {}
    for tag in ("up", "dn"):
        s = sides[tag]
        tr = trmap[tag]
        # total intra-window taker-sell flow for capture %
        flow = 0.0
        if tr is not None:
            su = slot_s * 1_000_000; eu = t_end
            mm = (tr["ts"] >= su) & (tr["ts"] < eu)
            flow = float(tr["sz"][mm].sum())
        if s is None:
            out[f"sh_{tag}"] = 0.; out[f"cost_{tag}"] = 0.; out[f"vwap_{tag}"] = np.nan
            out[f"n_fills_{tag}"] = 0; out[f"flow_{tag}"] = flow
        else:
            out[f"sh_{tag}"] = s["sh"]; out[f"cost_{tag}"] = s["cost"]
            out[f"vwap_{tag}"] = s["cost"] / s["sh"] if s["sh"] > 0 else np.nan
            out[f"n_fills_{tag}"] = s["n_fills"]; out[f"flow_{tag}"] = flow
    return out


def run_latency_sweep(res, tob, trades, use_upper=False, improve_ticks=0):
    slot_map = dict(zip(res.slug, res.slot_start_s))
    oc_map   = dict(zip(res.slug, res.outcome))
    slot_us  = dict(zip(res.slug, res.slot_start_us))
    all_slugs = sorted(res.slug.tolist())

    L_grid = [("0ms", 0), ("50ms", 50_000), ("100ms", 100_000), ("200ms", 200_000),
              ("500ms", 500_000), ("1s", 1_000_000), ("2s", 2_000_000),
              ("passive", float("inf"))]

    print(f"\n{'='*100}")
    print(f"REQUOTE-LATENCY SWEEP  (config Q=20 g=0.05 bud=$350 off=-3600s, "
          f"improve={improve_ticks}tick, {'UPPER' if use_upper else 'FIFO'})")
    print(f"Floor: tape=us-resolved (competition-ahead exact); L25 depth=~100ms (displayed-depth approx <100ms)")
    print(f"{'='*100}")
    hdr = (f"{'L':>8} | {'split':>3} | {'n':>4} | {'cap%':>5} | {'pvs':>5} | "
           f"{'pair_sh':>7} | {'resid$':>7} | {'r/psh':>7} | {'net':>7} | {'CI95':>16} | {'ex2':>6}")
    print(hdr); print("-" * len(hdr))

    rows = []
    t0 = time.time()
    for L_lbl, L_us in L_grid:
        recs = []
        for slug in all_slugs:
            ss = slot_map.get(slug)
            if ss is None:
                continue
            won = str(oc_map.get(slug, "")).lower() == "up"
            isw = slot_us.get(slug, 0) < IS_CUT
            o = sim_slug_latency(tob.get((slug, "Up")), trades.get((slug, "Up")),
                                 tob.get((slug, "Down")), trades.get((slug, "Down")),
                                 ss, OFFSET, L_us, use_upper=use_upper, improve_ticks=improve_ticks)
            p = slug_pnl(o, won)
            p["is_window"] = isw
            p["L"] = L_lbl
            p["improve_ticks"] = improve_ticks
            p["nf"] = (o["n_fills_up"] + o["n_fills_dn"]) / 2
            p["flow"] = (o["flow_up"] + o["flow_dn"])
            p["filled_total"] = o["sh_up"] + o["sh_dn"]
            recs.append(p)
        R = pd.DataFrame(recs)
        rows.append(R)

        for split, m in [("IS", R.is_window), ("OOS", ~R.is_window)]:
            sub = R[m]; fi = sub[(sub.sh_up > 0) | (sub.sh_dn > 0)]
            if len(fi) == 0:
                continue
            tot = fi.sh_up.sum() + fi.sh_dn.sum()
            pf = 2 * fi.paired.sum() / tot if tot > 0 else 0
            cap = fi.filled_total.sum() / fi.flow.sum() if fi.flow.sum() > 0 else 0
            paired_sh = fi.paired.median()
            resid = fi.residual_pnl.mean()
            r_per_psh = fi.residual_pnl.sum() / fi.paired.sum() if fi.paired.sum() > 0 else 0
            net = fi.net_pnl.to_numpy(); ci = boot(net, nb=2000)
            ex2 = net[np.argsort(np.abs(net))[:-2]].mean() if len(net) > 2 else np.nan
            print(f"{L_lbl:>8} | {split:>3} | {len(fi):>4} | {100*cap:4.1f} | {fi.pvs.median():.3f} | "
                  f"{paired_sh:7.0f} | {resid:+7.2f} | {r_per_psh:+.4f} | {net.mean():+7.2f} | "
                  f"[{ci[0]:+.2f},{ci[1]:+.2f}] | {ex2:+6.2f}", flush=True)
    print(f"\ngrid time={time.time()-t0:.0f}s")
    return pd.concat(rows, ignore_index=True)


def main():
    t0 = time.time()
    res = load_resolutions(); slug_set = set(res.slug)
    print("loading books/trades...", flush=True)
    tob = load_books(slug_set); trades = load_trades(slug_set)
    print(f"  loaded  t={time.time()-t0:.0f}s", flush=True)

    # improve=0: join best bid (latency is a no-op — diagnoses the missed-flow problem)
    # improve=1: price-improve 1 tick above best bid (b945's real mechanic: 56% of his fills
    #            are above the prior best bid). NOW latency matters: faster = front of the
    #            vacant improved level before others pile in.
    all_R = []
    for improve in [0, 1]:
        R = run_latency_sweep(res, tob, trades, use_upper=False, improve_ticks=improve)
        all_R.append(R)
    R_all = pd.concat(all_R, ignore_index=True)
    R_all.to_parquet(CACHE_DIR / "_mm_latency_sweep.parquet", index=False)
    print(f"\nSaved _mm_latency_sweep.parquet  ({len(R_all)} rows)")
    print(f"total t={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
