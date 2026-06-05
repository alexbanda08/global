"""
Favorite-longshot edge — FILL-REALISTIC revalidation (the make-or-break gate).

Trade-print calibration said: buy strong favorites (p>=0.75) @ ttl 15-120s, hold to resolution = +EV.
But prints != achievable fills. Here we re-test on L25 (native 10Hz) with engine_v2 LiveMimicConfig
(85ms latency + 0.07 winner-only fee + min_book_events) and the LIVE cross-token spread filter
|up_vwap - (1 - dn_vwap)| on $25-walked vwaps (CLAUDE.md: live cross-token spreads ~31% killed V5).

Anchor: ttl = 60s before settlement (middle of the +EV band). Favorite = token whose $25 ask-vwap >= 0.75.
PnL = hold to resolution. Sampled (~480 slugs/asset) + batched to bound memory.
"""
import sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, r"data\v4\canonical"); sys.path.insert(0, "strategy_lab")
from load import load_orderbook_l25_streaming, load_resolutions
from engine_v2 import LiveMimicConfig, fill_at_book, hold_pnl
np.random.seed(0)

cfg = LiveMimicConfig()
ANCHOR_TTL_US = 60_000_000
N_PER_ASSET = 480
BATCH = 120

def slug_boot(pnls, slugs, nb=3000):
    df = pd.DataFrame({"s": slugs, "p": pnls})
    g = df.groupby("s").p.agg(["sum", "count"])
    ss, sc = g["sum"].values, g["count"].values; nS = len(ss)
    m = np.array([ss[i].sum() / sc[i].sum() for i in [np.random.randint(0, nS, nS) for _ in range(nb)]])
    return df.p.mean(), np.percentile(m, 2.5), np.percentile(m, 97.5)

rows = []
for asset in ["btc", "eth", "sol"]:
    r = load_resolutions(assets=[asset.upper()])
    r = r[r.outcome.isin(["Up", "Down"])].dropna(subset=["slot_end_us"])
    r = r.sort_values("slot_start_us")
    samp = r.iloc[np.linspace(0, len(r) - 1, min(N_PER_ASSET, len(r))).astype(int)]
    win = dict(zip(samp.slug, samp.outcome)); end = dict(zip(samp.slug, samp.slot_end_us))
    slugs = list(samp.slug)
    print(f"\n===== {asset.upper()} sampling {len(slugs)} slugs across {len(r)} =====", flush=True)
    res = []
    for b0 in range(0, len(slugs), BATCH):
        chunk = set(slugs[b0:b0 + BATCH])
        books = load_orderbook_l25_streaming(asset, slugs=chunk, subsample_1hz=False)
        for s in chunk:
            anchor = int(end[s]) - ANCHOR_TTL_US
            up = fill_at_book(books, s, "Up", anchor, cfg=cfg, side="buy", notional_usd=25.0)
            dn = fill_at_book(books, s, "Down", anchor, cfg=cfg, side="buy", notional_usd=25.0)
            if up is None or dn is None:
                res.append((s, None, None, None, None)); continue
            uv, dv = up["vwap"], dn["vwap"]
            xspread = abs(uv - (1 - dv))                       # live cross-token spread def
            fav_out = "Up" if uv >= dv else "Down"            # favorite = higher-priced token
            fav = up if fav_out == "Up" else dn
            won = (fav_out == win[s])
            pnl = hold_pnl(fav, won=won, cfg=cfg)
            res.append((s, fav["vwap"], xspread, pnl, won))
        del books
    d = pd.DataFrame(res, columns=["slug", "fav_vwap", "xspread", "pnl", "won"])
    placed = d.dropna(subset=["fav_vwap"])
    print(f"book-available: {len(placed)}/{len(d)}  fav_vwap median={placed.fav_vwap.median():.3f}", flush=True)
    print(f"cross-token spread: median={placed.xspread.median():.3f} p25={placed.xspread.quantile(.25):.3f} "
          f"p75={placed.xspread.quantile(.75):.3f}", flush=True)
    rows.append((asset, placed))

ALL = pd.concat([p.assign(asset=a) for a, p in rows], ignore_index=True)
print("\n================ FILL-REALISTIC RESULT (favorite p>=0.75 @ ttl=60s, hold) ================")
for name, cond in [
    ("strong fav (vwap>=0.75), NO spread filter", ALL.fav_vwap >= 0.75),
    ("strong fav + xspread<=0.05", (ALL.fav_vwap >= 0.75) & (ALL.xspread <= 0.05)),
    ("strong fav + xspread<=0.02 (live-ish)", (ALL.fav_vwap >= 0.75) & (ALL.xspread <= 0.02)),
    ("any fav (vwap>=0.60) + xspread<=0.05", (ALL.fav_vwap >= 0.60) & (ALL.xspread <= 0.05)),
]:
    d = ALL[cond]
    if len(d) < 20: print(f"{name:44s} n={len(d)} (few)"); continue
    mean, lo, hi = slug_boot(d.pnl.values, d.slug.values)
    print(f"{name:44s} n={len(d):4d} won={d.won.mean():.3f} fav_vwap={d.fav_vwap.mean():.3f} "
          f"$/tr={mean:+.4f} slugCI=[{lo:+.4f},{hi:+.4f}]")
print("\nREAD: edge survives ONLY if $/tr>0 with slug-CI>0 AFTER the live cross-token spread filter.")
print("      If the spread filter removes most fills or flips $/tr negative -> not deployable (V5 trap).")
