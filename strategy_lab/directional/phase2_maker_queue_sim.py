"""PHASE 2 — delta-resolution maker/queue sim. RUNS WHEN DELTAS LAND (orderbook_deltas/{asset}.parquet).
The thing the full-book sims couldn't do: with the price_change delta stream we can model TRUE queue
position (resting size ahead of us at our level, intra-window) + detect being FIRST at a new level.

Policy (v1, simple + comparable): rest a single BUY bid per token at the current best bid, requote every
REQUOTE_S, hold the window. A resting bid fills from taker SELLS at our price once cumulative sells exceed
the queue ahead (FIFO lower bound; cancels don't help us — matches the prior _maker_queue_bt convention).
Run on the DELTA-resolution book vs the 1Hz full-book → the delta-vs-1Hz capture gap = what the new data buys.

This is the harness that answers the maker NO-GO (full-book ceilinged at ~4-7% flow capture vs b945 ~11.5%).
Foundation (reconstruct_book_10hz) is unit-tested (_test_reconstruct_book.py). This policy layer validates
once real deltas exist — until then it exits with a friendly 'not yet' message.
"""
import sys, time
sys.path.insert(0, "data/v4/canonical")
import numpy as np, pandas as pd
import pyarrow.parquet as pq
from load import (load_resolutions, load_orderbook_l25_streaming, load_orderbook_deltas,
                  reconstruct_book_10hz, CANON)

COIN = sys.argv[1].upper() if len(sys.argv) > 1 else "BTC"
TF = "15m"; NSLUG = int(sys.argv[2]) if len(sys.argv) > 2 else 30
REQUOTE_S = 10; CLIP_USD = 5.0
CUTOFF = sys.argv[3] if len(sys.argv) > 3 else "2026-06-16"  # collection start (no deltas before this)

def best_bid_asof(ts, bp, bs, t):
    j = int(np.searchsorted(ts, t, "right")) - 1
    if j < 0: return (np.nan, 0.0)
    r = bp[j]; z = bs[j]
    for i in range(r.shape[0]):
        if np.isfinite(r[i]) and r[i] > 0 and z[i] > 0:
            return (round(float(r[i]), 2), float(z[i]))
    return (np.nan, 0.0)

def sim_token(book, sells, ss, se):
    """book=(ts,ap,asz,bp,bs); sells=DataFrame[timestamp_us,price,size] (taker SELLS only).
    Returns (filled_sh, market_sell_sh, n_first)."""
    ts, ap, asz, bp, bs = book
    if len(ts) == 0: return (0.0, float(sells["size"].sum()), 0)
    spx = np.round(sells["price"].to_numpy(float), 2); sts = sells["timestamp_us"].to_numpy(); ssz = sells["size"].to_numpy(float)
    filled = 0.0; n_first = 0
    for t0 in range(int(ss), int(se), REQUOTE_S * 1_000_000):
        t1 = min(t0 + REQUOTE_S * 1_000_000, int(se))
        price, qahead = best_bid_asof(ts, bp, bs, t0)
        if not np.isfinite(price): continue
        if qahead <= 1e-9: n_first += 1
        our_sh = CLIP_USD / max(price, 0.01)
        m = (sts >= t0) & (sts < t1) & (np.abs(spx - price) < 1e-9)
        consumed = ssz[m].sum()
        f = min(our_sh, max(0.0, consumed - qahead))
        filled += f
    market = float(ssz.sum())
    return (filled, market, n_first)

def main():
    t0 = time.time()
    try:
        # probe: deltas present?
        _ = load_orderbook_deltas(COIN, slugs={"__probe__"})
    except FileNotFoundError as e:
        print(f"[phase2] deltas not collected yet — harness is READY, run when data lands.\n  {e}")
        return
    res = load_resolutions(assets=[COIN], timeframes=[TF]).drop_duplicates("slug").sort_values("slot_start_us")
    cut = int(pd.Timestamp(CUTOFF, tz="UTC").timestamp() * 1e6)
    res = res[res.slot_start_us >= cut]
    if len(res) == 0:
        print(f"[phase2] no {COIN} {TF} slugs after {CUTOFF} — wait for windows to accrue with deltas."); return
    slugs = res.slug.tolist()[:NSLUG]; smap = dict(zip(res.slug, res.slot_start_us))
    print(f"[phase2] {COIN} {TF}: {len(slugs)} slugs after {CUTOFF}", flush=True)

    kbooks = load_orderbook_l25_streaming(COIN.lower(), slugs=set(slugs), subsample_1hz=False)
    dmap = load_orderbook_deltas(COIN, slugs=set(slugs))
    # trades (SELLS, exchange-time join)
    tcols = ["timestamp_us", "slug", "outcome", "price", "size", "side"]; parts = []
    for b in pq.ParquetFile(CANON / "trades_polymarket" / f"{COIN.lower()}.parquet").iter_batches(columns=tcols, batch_size=500_000):
        d = b.to_pandas(); d = d[(d.slug.isin(slugs)) & (d.side == "sell")]
        if len(d): parts.append(d)
    TR = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=tcols)

    agg = {"delta": dict(fill=0., mkt=0., first=0, n=0), "hz": dict(fill=0., mkt=0., first=0, n=0)}
    pair = {"delta": [], "hz": []}
    for sl in slugs:
        ss = int(smap[sl]); se = ss + 900_000_000
        per = {"delta": {}, "hz": {}}
        for oc in ("Up", "Down"):
            kf = kbooks.get((sl, oc));
            if kf is None: continue
            sells = TR[(TR.slug == sl) & (TR.outcome == oc)][["timestamp_us", "price", "size"]]
            dbook = reconstruct_book_10hz(kf, dmap.get((sl, oc)))
            for mode, book in (("delta", dbook), ("hz", kf)):
                f, mkt, nf = sim_token(book, sells, ss, se)
                agg[mode]["fill"] += f; agg[mode]["mkt"] += mkt; agg[mode]["first"] += nf; agg[mode]["n"] += 1
                per[mode][oc] = f
        for mode in ("delta", "hz"):
            u, dn = per[mode].get("Up", 0.), per[mode].get("Down", 0.)
            if max(u, dn) > 0: pair[mode].append(min(u, dn) / max(u, dn))
    print("=" * 60)
    for mode in ("delta", "hz"):
        a = agg[mode]; cap = 100 * a["fill"] / a["mkt"] if a["mkt"] > 0 else 0
        pf = np.mean(pair[mode]) if pair[mode] else 0
        print(f"  {mode:>5}-book: flow_capture={cap:5.2f}%  filled={a['fill']:.0f}sh  pair_frac={pf:.2f}  first-quotes={a['first']}")
    print(f"\n  → delta-vs-1Hz flow-capture gap = what the price_change stream buys. Target: clear the ~4-7% full-book ceiling toward b945's ~11.5%.")
    print(f"t={time.time()-t0:.0f}s")

if __name__ == "__main__":
    main()
