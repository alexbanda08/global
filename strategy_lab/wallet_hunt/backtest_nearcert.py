"""Backtest the 0xee65685d near-certain scalp: BUY the up/down token when its ask
>= theta (near-certain favorite), hold to resolution. Naked (no stop/hedge, matching
the wallet). Real costs: winner-only fee 0.07*p*(1-p)/share + flat $0.01 tx/trade.

For each up-down market: load both token books, find FIRST time either token's best
ask >= theta (and < 0.999, leave win room), book-walk a $NOTIONAL fill at the asks,
hold to resolution (outcome from canonical chainlink), compute pnl.

Run: py -3 strategy_lab/wallet_hunt/backtest_nearcert.py --asset btc --tf 15m --days 6
"""
import sys, argparse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "data" / "v4" / "canonical"))
import numpy as np, pandas as pd
from load import load_resolutions, load_orderbook_l25_streaming

NOTIONAL = 50.0   # target $ per trade
TX = 0.01         # flat tx fee per trade

def walk_fill(ask_px_row, ask_sz_row, theta, notional):
    """Buy up to $notional walking asks (ascending price), only levels in [theta, 0.999]."""
    spent = 0.0; qty = 0.0
    order = np.argsort(ask_px_row)
    for j in order:
        p = ask_px_row[j]; sz = ask_sz_row[j]
        if p < theta or p >= 0.999 or sz <= 0: continue
        take_usd = min(notional - spent, p * sz)
        if take_usd <= 0: break
        q = take_usd / p
        qty += q; spent += take_usd
        if spent >= notional - 1e-9: break
    if qty <= 0: return None
    return spent / qty, qty   # vwap, shares

def pnl(won, vwap, qty):
    win = qty * (1 - vwap) * (1 - 0.07 * vwap)   # winner-only 0.07 curve
    return (win if won else -qty * vwap) - TX

def run(asset, tf, days, thetas):
    res = load_resolutions()
    res = res[res["slug"].astype(str).str.contains(f"{asset}-updown-{tf}-")].dropna(
        subset=["outcome","slot_start_us","slot_end_us"]).sort_values("slot_start_us")
    max_us = int(res["slot_end_us"].max()); min_us = max_us - days*86400*1_000_000
    res = res[res["slot_start_us"] >= min_us]
    slugs = set(res["slug"])
    out_map = dict(zip(res["slug"], res["outcome"].astype(str).str.capitalize()))
    print(f"[{asset} {tf}] {len(res)} markets / {days}d — loading L25 (native 10Hz)...")
    books = load_orderbook_l25_streaming(asset, slugs=slugs, subsample_1hz=False,
                                         min_ts_us=min_us-5_000_000, max_ts_us=max_us+5_000_000)
    slot_end = dict(zip(res["slug"], res["slot_end_us"].astype("int64")))
    for theta in thetas:
      for maxtleft in (600,180,90,45,20):
        trades=[]
        for slug in slugs:
            won_out = out_map.get(slug)
            if won_out not in ("Up","Down"): continue
            se=slot_end[slug]
            cands=[]
            for tok in ("Up","Down"):
                key=(slug,tok)
                if key not in books: continue
                ts, ask_px, ask_sz, bid_px, bid_sz = books[key]
                best=ask_px[:,0]; tleft=(se-ts)/1e6
                idx=np.where((best>=theta)&(best<0.999)&(tleft<=maxtleft)&(tleft>=3))[0]
                if len(idx)==0: continue
                i=idx[-1]   # LATEST qualifying snapshot (buy as late as possible while near-cert)
                fill=walk_fill(ask_px[i], ask_sz[i], theta, NOTIONAL)
                if fill: cands.append((ts[i], tok, fill[0], fill[1]))
            if not cands: continue
            cands.sort(key=lambda c:-c[0])   # latest
            t, tok, vwap, qty = cands[0]
            won = (tok == won_out)
            trades.append({"vwap":vwap,"qty":qty,"won":won,"tleft":(se-t)/1e6,
                           "pnl":pnl(won,vwap,qty),"notional":vwap*qty})
        d=pd.DataFrame(trades)
        if len(d)<20: continue
        be = d.vwap.mean()/(d.vwap.mean()+(1-d.vwap.mean())*(1-0.07*d.vwap.mean()))
        print(f"  th>={theta} tleft<={maxtleft:>3}s: n={len(d):4d} WR={d.won.mean()*100:5.1f}% (BE~{be*100:.1f}%) "
              f"entry={d.vwap.mean():.3f} fill=${d.notional.mean():4.0f} tleft={d.tleft.mean():3.0f}s "
              f"| $/tr={d.pnl.mean():+.4f} tot=${d.pnl.sum():+.1f}")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--asset",default="btc"); ap.add_argument("--tf",default="15m"); ap.add_argument("--days",type=int,default=6)
    a=ap.parse_args(); run(a.asset,a.tf,a.days,(0.95,0.97,0.98,0.99))

if __name__=="__main__": main()
