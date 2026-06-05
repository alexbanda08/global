"""Test the 'lock-the-lag' hypothesis via time-ordered FIFO complete-set matching.

Hypothesis: wallet buys the leading side cheap (Up@66), waits for the binance->oracle
lag to fill (Up rises to 77, Down falls to 23), then completes the set by buying the
OTHER side cheap (Down@23) -> matched pair cost 89c < $1 = locked ~11c market-neutral.

This is DIFFERENT from averaging buy-price per side. We FIFO-match opposite-side fills
in TIME ORDER and measure each matched pair's (leg1_px + leg2_px), the gap, and which
side was bought first (the leading side should be first if they 'lock when right').
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from collections import deque
import numpy as np, pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, "data/v4/canonical")

def load_buys(short):
    """Return BUY fills DataFrame [conditionId, slug, outcome, price, size, ts]."""
    # intraday wallet eebde7a0 has a direct trades.parquet; others via _pm_portfolio
    p1 = HERE / "cache" / ("0x"+short) / "trades.parquet"
    if p1.exists():
        df = pd.read_parquet(p1)
    else:
        f = HERE / "cache" / "_pm_portfolio" / ("0x"+short) / "activity_TRADE.json"
        df = pd.DataFrame(json.load(open(f, encoding="utf-8")))
    for c in ["price","size","timestamp"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["slug"] = df.get("slug","").fillna("")
    df["outcome"] = df.get("outcome","").fillna("")
    df["conditionId"] = df.get("conditionId","").fillna("")
    return df[df["side"].astype(str).str.upper()=="BUY"].copy()

def fifo_pairs(g):
    """Time-ordered FIFO matching of opposite-outcome buys within one market.
    Returns list of matched pairs: dict(first_side, first_px, first_ts, second_side,
    second_px, second_ts, shares, sum_cost, gap_s)."""
    g = g.sort_values("timestamp")
    outs = list(g["outcome"].unique())
    if len(outs) < 2:
        return [], dict(g[["outcome","size"]].groupby("outcome")["size"].sum())
    # two main outcomes
    top2 = g.groupby("outcome")["size"].sum().sort_values(ascending=False).head(2).index.tolist()
    A, B = top2[0], top2[1]
    qA, qB = deque(), deque()   # each: [price, ts, shares_remaining]
    pairs = []
    for _, r in g.iterrows():
        o, p, n, ts = r["outcome"], float(r["price"]), float(r["size"]), int(r["timestamp"])
        if o == A: my, opp, mes = qA, qB, A
        elif o == B: my, opp, mes = qB, qA, B
        else: continue
        # match against opposite inventory (FIFO)
        while n > 1e-9 and opp:
            op_px, op_ts, op_sh = opp[0]
            m = min(n, op_sh)
            # first leg = the earlier ts; this fill is the completion
            if op_ts <= ts:
                first_side = B if mes==A else A
                first_px, first_ts = op_px, op_ts
                second_side, second_px, second_ts = mes, p, ts
            else:
                first_side, first_px, first_ts = mes, p, ts
                second_side, second_px, second_ts = (B if mes==A else A), op_px, op_ts
            pairs.append(dict(first_side=first_side, first_px=first_px, first_ts=first_ts,
                second_side=second_side, second_px=second_px, second_ts=second_ts,
                shares=m, sum_cost=op_px+p, gap_s=abs(ts-op_ts)))
            n -= m; op_sh -= m
            if op_sh <= 1e-9: opp.popleft()
            else: opp[0][2] = op_sh
        if n > 1e-9:
            my.append([p, ts, n])
    # leftover = directional residual
    resid = {A: sum(x[2] for x in qA), B: sum(x[2] for x in qB)}
    return pairs, resid

def analyze(short, label, use_resolution=True):
    b = load_buys(short)
    res = None
    if use_resolution:
        try:
            from load import load_resolutions
            r = load_resolutions()[["slug","outcome"]].drop_duplicates("slug")
            res = r.set_index("slug")["outcome"]
        except Exception:
            res = None
    allpairs = []
    resid_dir_shares = 0.0; resid_count = 0
    examples = []
    for cond, g in b.groupby("conditionId"):
        if not cond: continue
        pairs, resid = fifo_pairs(g)
        slug = g["slug"].iloc[0]
        for pr in pairs: pr["slug"] = slug
        allpairs.extend(pairs)
        # capture a few clean example slugs (>=2 pairs, intraday)
        if len(pairs) >= 1 and len(examples) < 6 and ("updown-5m" in slug or "updown-15m" in slug or "up-or-down-on" in slug):
            examples.append((slug, g.sort_values("timestamp"), pairs))
    P = pd.DataFrame(allpairs)
    print(f"\n===== {short} ({label}) =====")
    if P.empty:
        print("  no matched pairs"); return
    n = len(P); shrs = P["shares"].sum()
    print(f"  matched pairs n={n}  (share-weighted)")
    # share-weighted distribution of sum_cost
    def wq(q):
        s = P.sort_values("sum_cost"); cum = s["shares"].cumsum(); tot=s["shares"].sum()
        return float(s.loc[cum>=q*tot,"sum_cost"].iloc[0])
    print(f"  MATCHED-PAIR SUM (leg1+leg2), share-weighted: p25={wq(.25):.4f} median={wq(.5):.4f} p75={wq(.75):.4f}")
    lt1 = float(P.loc[P.sum_cost<1.0,"shares"].sum()/shrs)
    lt99 = float(P.loc[P.sum_cost<0.99,"shares"].sum()/shrs)
    lt97 = float(P.loc[P.sum_cost<0.97,"shares"].sum()/shrs)
    print(f"  %% pairs (share-wtd) sum<1.00={100*lt1:.1f}%  sum<0.99={100*lt99:.1f}%  sum<0.97={100*lt97:.1f}%")
    # locked spread on profitable pairs
    prof = P[P.sum_cost<1.0]
    print(f"  locked spread on sum<1 pairs: mean (1-sum)={float((1-prof.sum_cost).mean()):.4f}  "
          f"share-wtd $ locked=${float(((1-prof.sum_cost)*prof.shares).sum()):.0f}")
    loss = P[P.sum_cost>=1.0]
    print(f"  loss-locked on sum>=1 pairs: share-wtd $=${float(((1-loss.sum_cost)*loss.shares).sum()):.0f}")
    print(f"  NET locked $ (all matched pairs, ignoring fees) = ${float(((1-P.sum_cost)*P.shares).sum()):.0f}")
    print(f"  median gap between legs: {float(P['gap_s'].median()):.0f}s  (hypothesis: seconds = wait-for-lag)")
    # did they buy the LEADING side first? leading-first <=> for sum<1 pairs the first leg appreciated
    # we already know sum<1 => first leg side's implied price rose. Report share of pairs where gap>0 (real sequence)
    seq = float(P.loc[P.gap_s>0,"shares"].sum()/shrs)
    print(f"  %% pairs with real time-gap (not same-instant): {100*seq:.1f}%")
    return P, examples

def dump_examples(short, examples, k=3):
    import datetime as dt
    print(f"\n  --- {short} example slug sequences (ordered fills + FIFO pairs) ---")
    for slug, g, pairs in examples[:k]:
        print(f"  SLUG {slug}  ({len(g)} buys, {len(pairs)} matched pairs)")
        for _, r in g.iterrows():
            t = dt.datetime.utcfromtimestamp(int(r['timestamp'])).strftime('%H:%M:%S')
            print(f"     {t} BUY {str(r['outcome']):4s} px={float(r['price']):.3f} sz={float(r['size']):8.1f}")
        for pr in pairs[:5]:
            print(f"      -> PAIR first={pr['first_side']}@{pr['first_px']:.3f} second={pr['second_side']}@{pr['second_px']:.3f} "
                  f"SUM={pr['sum_cost']:.3f} gap={pr['gap_s']}s shares={pr['shares']:.1f} "
                  f"{'LOCK+'+format(1-pr['sum_cost'],'.3f') if pr['sum_cost']<1 else 'LOSS'+format(1-pr['sum_cost'],'.3f')}")

if __name__ == "__main__":
    for short,label in [("eebde7a0","best/intraday"),("0fe40e88","gobblewobble/daily"),
                         ("143732d8","multisafe"),("a42f127d","5f5a"),("4ee29e4e","IH2P")]:
        out = analyze(short, label)
        if out and short in ("eebde7a0","0fe40e88"):
            dump_examples(short, out[1], k=3)
