# Residual anatomy of the professional wallets vs ours.
# Per wallet, per window: paired vs residual shares, which SIDE the residual
# lands on (winner or loser), residual win rate, and the PnL split
# paired-vs-residual. Pros never sell (verified) -> residual rides to settle.
# Sources: full wallet pulls (all Aug cache tags, deduped), Chainlink winners.
import json, csv, glob, os
from collections import defaultdict

DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(DIR, "..", "wallet_hunt", "cache", "_pm_portfolio")
WALLETS = [("ours", "0x51a5f36d"), ("b27", "0xb27bc932"), ("b945", "0xb945945d"),
           ("pbot6", "0x21d0a97a"), ("pbot5", "0x1b58d3de"), ("pbot3", "0x74a2b82f"),
           ("pbot2", "0x095fd7cc")]
T0 = 1785801600  # Aug 4

RES = {}
for f, dur in (("btc5m_resolutions_2wk.csv", 300), ("btc15m_resolutions_2wk.csv", 900)):
    with open(os.path.join(DIR, f), newline="") as fh:
        for row in csv.DictReader(fh):
            RES[row["slug"]] = (int(row["slot_start_us"]) // 1_000_000, dur, row["outcome"])
with open(os.path.join(DIR, "r15_recent.csv"), newline="") as fh:
    for row in csv.DictReader(fh):
        if row["slug"] not in RES:
            RES[row["slug"]] = (int(row["slug"].rsplit("-", 1)[1]), 900, row["outcome"])

def load(short):
    seen = set(); out = []
    for path in sorted(glob.glob(os.path.join(CACHE, short, "activity_TRADE_2026_08_*.json"))):
        try:
            recs = json.load(open(path))
        except Exception:
            continue
        for r in recs:
            slug = r.get("slug", "")
            if not slug.startswith("btc-updown-"):
                continue
            if r["timestamp"] < T0 or r["side"] != "BUY":
                continue
            k = (r.get("transactionHash"), r.get("asset"), r.get("side"),
                 int(float(r.get("size") or 0) * 100), r["timestamp"])
            if k in seen:
                continue
            seen.add(k)
            out.append((slug, r["outcome"] == "Up", float(r["price"]), float(r["size"])))
    return out

print(f"{'wallet':6s} {'tf':>3s} {'wins':>5s} {'sh/w':>7s} {'pair%':>6s} {'res%':>5s} "
      f"{'res sh/w':>8s} {'resWR%':>6s} {'res vwap':>8s} {'resEV c/sh':>10s} {'pairPnl':>8s} {'resPnl':>8s} {'res>20%w':>8s}")
for name, short in WALLETS:
    fills = load(short)
    book = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    for (slug, isup, prc, sh) in fills:
        if slug not in RES:
            continue
        b = book[slug]
        if isup: b[0] += sh; b[2] += sh * prc
        else:    b[1] += sh; b[3] += sh * prc
    for tf in (300, 900):
        stats = dict(n=0, sh=0.0, pair=0.0, res=0.0, res_win=0.0, res_cost=0.0,
                     pair_pnl=0.0, res_pnl=0.0, big=0)
        for slug, (u, d, uc, dc) in book.items():
            start, dur, outc = RES[slug]
            if dur != tf or u + d < 1:
                continue
            win_up = outc == "Up"
            paired = min(u, d); resid = abs(u - d)
            s = stats
            s["n"] += 1; s["sh"] += u + d; s["pair"] += 2 * paired; s["res"] += resid
            if resid > 0.01:
                heavy_up = u > d
                rw = heavy_up == win_up
                rv = (uc / u) if heavy_up else (dc / d)
                s["res_win"] += resid if rw else 0
                s["res_cost"] += resid * rv
                s["res_pnl"] += resid * ((1 if rw else 0) - rv)
                if resid / (u + d) > 0.2:
                    s["big"] += 1
            if paired > 0:
                pvs = uc / u + dc / d
                s["pair_pnl"] += paired * (1 - pvs)
        if stats["n"] < 3:
            continue
        res = stats["res"]
        rwr = 100 * stats["res_win"] / res if res else 0
        rvw = stats["res_cost"] / res if res else 0
        rev = 100 * (stats["res_win"] / res - rvw) if res else 0
        print(f"{name:6s} {tf//60:2d}m {stats['n']:5d} {stats['sh']/stats['n']:7.0f} "
              f"{100*stats['pair']/stats['sh']:5.1f}% {100*res/stats['sh']:4.1f}% "
              f"{res/stats['n']:8.1f} {rwr:6.1f} {rvw:8.3f} {rev:+10.1f} "
              f"{stats['pair_pnl']:+8.0f} {stats['res_pnl']:+8.0f} {100*stats['big']/stats['n']:7.1f}%")
