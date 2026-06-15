"""
_mm_oracle_gate.py — Oracle-gated quoting variant on top of the best inventory config.

Variant 3 from the operator's spec: gate quoting to only when |rtds_ret5s| > threshold
(b945's model-D signature — quote during taker panics where effective spread is wider).
Applied on top of the best inventory cell (bud=350, Q=20, gamma=0.05).

Grid: threshold in {0 (no gate), 5bp, 10bp, 20bp} on |rtds_ret5s|.
Run on 200-slug validation sample at -3600s, FIFO.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd, pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab" / "wallet_hunt"))
from _mm_inv_engine import (load_resolutions, load_books, load_trades, slug_pnl, boot,
                            _qa_at, _bid_at, WINDOW_S, CLIP_USD, REBATE_SH)

RTDS_PATH = ROOT / "data" / "v4" / "canonical" / "chainlink_rtds.parquet"


def load_rtds_btc(t_min_us, t_max_us):
    """Load BTC chainlink RTDS in window, return sorted (ts, price)."""
    f = pq.ParquetFile(RTDS_PATH)
    parts = []
    for i in range(f.num_row_groups):
        df = f.read_row_group(i, columns=["timestamp_us", "symbol_id", "price_value"]).to_pandas()
        df = df[(df.symbol_id == "CHAINLINK_BTC_USD") &
                (df.timestamp_us >= t_min_us) & (df.timestamp_us <= t_max_us)]
        if len(df):
            parts.append(df)
    if not parts:
        return np.array([], np.int64), np.array([], np.float64)
    R = pd.concat(parts, ignore_index=True).drop_duplicates("timestamp_us").sort_values("timestamp_us")
    return R.timestamp_us.to_numpy(np.int64), R.price_value.to_numpy(np.float64)


def rtds_ret5(rtds_ts, rtds_px, at_us):
    """|return| over the prior 5 seconds of the oracle at time at_us."""
    if len(rtds_ts) == 0:
        return 0.0
    j = int(np.searchsorted(rtds_ts, at_us, "right")) - 1
    if j < 1:
        return 0.0
    j0 = int(np.searchsorted(rtds_ts, at_us - 5_000_000, "right")) - 1
    if j0 < 0:
        j0 = 0
    p1 = rtds_px[j]; p0 = rtds_px[j0]
    if p0 <= 0:
        return 0.0
    return abs(p1 / p0 - 1.0)


def sim_slug_gated(bk_up, tr_up, bk_dn, tr_dn, slot_s, offset_s, budget, Q_cap, gamma,
                   rtds_ts, rtds_px, ret_thr):
    """Best inventory config + oracle gate: only fill when |rtds_ret5s| >= ret_thr."""
    t_place = (slot_s + offset_s) * 1_000_000
    t_end   = (slot_s + WINDOW_S) * 1_000_000

    sides = {}
    for tag, bk in (("up", bk_up), ("dn", bk_dn)):
        if bk is None:
            sides[tag] = None; continue
        ib = _bid_at(bk, t_place)
        if not np.isfinite(ib) or ib <= 0:
            sides[tag] = None; continue
        sides[tag] = dict(bk=bk, order_price=ib, order_qa=_qa_at(bk, t_place, ib),
                          remaining=min(CLIP_USD, budget)/ib, budget_left=budget,
                          cur_bid=ib, sh=0., cost=0., n_fills=0, active=True)

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

    def net_res(tag):
        other = "dn" if tag == "up" else "up"
        st = sides[tag]["sh"] if sides[tag] else 0.0
        so = sides[other]["sh"] if sides[other] else 0.0
        return st - so

    def apply_glt(tag):
        if not np.isfinite(Q_cap) or sides[tag] is None:
            return
        sides[tag]["active"] = (net_res(tag) <= Q_cap)

    def skew(tag, base, ev_ts):
        if gamma <= 0:
            return min(base, 0.99)
        q = net_res(tag); tl = max(0., (t_end - ev_ts) / (WINDOW_S * 1_000_000))
        return min(max(base - (q/100.0)*gamma*0.25*tl, 0.01), 0.99)

    for ev_ts, kind, tag, payload in events:
        s = sides[tag]
        if s is None:
            continue
        if kind == 0:
            nb = payload
            if np.isfinite(nb) and nb > 0 and abs(nb - s["cur_bid"]) > 1e-6:
                nl = skew(tag, nb, ev_ts)
                if abs(nl - s["order_price"]) > 1e-6 and s["remaining"] > 1e-6:
                    carry = s["remaining"] * s["order_price"]
                    s["order_price"] = nl; s["remaining"] = carry/nl
                    s["order_qa"] = _qa_at(s["bk"], ev_ts, nl)
                s["cur_bid"] = nb
            apply_glt(tag)
        else:
            tp, ts2 = payload
            apply_glt(tag)
            # ORACLE GATE: skip fill if oracle quiet
            if ret_thr > 0 and rtds_ret5(rtds_ts, rtds_px, ev_ts) < ret_thr:
                continue
            if not s["active"] or s["remaining"] <= 1e-6 or s["budget_left"] <= 1e-6:
                continue
            fa = 0.0; op = s["order_price"]
            if tp < op - 1e-6:
                fa = min(s["remaining"], ts2)
            elif abs(tp - op) < 1e-6:
                if s["order_qa"] >= ts2:
                    s["order_qa"] -= ts2
                else:
                    fa = min(s["remaining"], ts2 - s["order_qa"]); s["order_qa"] = 0.0
            if fa > 1e-9:
                s["sh"] += fa; s["cost"] += fa*op; s["remaining"] -= fa
                s["budget_left"] -= fa*op; s["n_fills"] += 1
                if s["remaining"] <= 1e-6 and s["budget_left"] > 1e-6:
                    nl = skew(tag, s["cur_bid"], ev_ts)
                    s["order_price"] = nl; s["remaining"] = min(CLIP_USD, s["budget_left"])/nl
                    s["order_qa"] = 0.0
                apply_glt(tag)
                other = "dn" if tag == "up" else "up"
                if sides[other]:
                    apply_glt(other)

    out = {}
    for tag in ("up", "dn"):
        s = sides[tag]
        if s is None:
            out[f"sh_{tag}"]=0.; out[f"cost_{tag}"]=0.; out[f"vwap_{tag}"]=np.nan; out[f"n_fills_{tag}"]=0; out[f"qa_{tag}"]=np.inf
        else:
            out[f"sh_{tag}"]=s["sh"]; out[f"cost_{tag}"]=s["cost"]
            out[f"vwap_{tag}"]=s["cost"]/s["sh"] if s["sh"]>0 else np.nan
            out[f"n_fills_{tag}"]=s["n_fills"]; out[f"qa_{tag}"]=0.
    return out


def main():
    import time
    t0 = time.time()
    res = load_resolutions(); slug_set = set(res.slug)
    print("loading books/trades...", flush=True)
    tob = load_books(slug_set); trades = load_trades(slug_set)
    slot_map = dict(zip(res.slug, res.slot_start_s)); oc_map = dict(zip(res.slug, res.outcome))
    rng = np.random.default_rng(7); sample = list(rng.choice(sorted(slug_set), 200, replace=False))

    # Load BTC RTDS across the full sample window
    slot_us_list = [slot_map[s]*1_000_000 for s in sample if s in slot_map]
    t_min = min(slot_us_list) - 7200_000_000; t_max = max(slot_us_list) + 1000_000_000
    print(f"loading RTDS [{t_min}, {t_max}]...", flush=True)
    rtds_ts, rtds_px = load_rtds_btc(t_min, t_max)
    print(f"  rtds rows: {len(rtds_ts)}  t={time.time()-t0:.0f}s", flush=True)

    print(f"\nORACLE-GATE GRID (best cell bud350 Q20 g0.05 + |rtds_ret5| gate), FIFO, -3600s")
    print("Gate: pvs>=0.95 AND fills/side>=60 AND net>=+$3/slug\n")
    for thr in [0.0, 0.0005, 0.001, 0.002]:
        recs = []
        for slug in sample:
            ss = slot_map.get(slug)
            if ss is None: continue
            won = str(oc_map.get(slug,'')).lower()=='up'
            o = sim_slug_gated(tob.get((slug,'Up')),trades.get((slug,'Up')),
                               tob.get((slug,'Down')),trades.get((slug,'Down')),
                               ss,-3600,350,20,0.05,rtds_ts,rtds_px,thr)
            p = slug_pnl(o, won); p['nf']=(o['n_fills_up']+o['n_fills_dn'])/2; recs.append(p)
        R = pd.DataFrame(recs); fi = R[(R.sh_up>0)|(R.sh_dn>0)]
        if len(fi)==0:
            print(f"  thr={thr*1e4:.0f}bp: 0 fills"); continue
        tot=fi.sh_up.sum()+fi.sh_dn.sum(); pf=2*fi.paired.sum()/tot
        net=fi.net_pnl.to_numpy(); ci=boot(net,nb=2000)
        ex2=net[np.argsort(np.abs(net))[:-2]].mean() if len(net)>2 else np.nan
        gp=fi.pvs.median()>=0.95; gf=fi.nf.mean()>=60; gn=net.mean()>=3.0
        flag="  *** PASS ***" if (gp and gf and gn) else ""
        print(f"  thr={thr*1e4:4.0f}bp: n={len(fi)} pf={100*pf:4.1f}% pvs={fi.pvs.median():.3f} "
              f"fills/sd={fi.nf.mean():5.1f} net={net.mean():+6.2f} CI[{ci[0]:+.2f},{ci[1]:+.2f}] "
              f"ex2={ex2:+6.2f} [pvs{'Y' if gp else 'n'} fl{'Y' if gf else 'n'} net{'Y' if gn else 'n'}]{flag}", flush=True)
    print(f"\ntotal t={time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
