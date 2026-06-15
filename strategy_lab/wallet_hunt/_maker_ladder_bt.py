"""
_maker_ladder_bt.py — STATIC-LADDER maker variant (motivated by b945's fill locations:
47% of his fills at-or-below the displayed bid -> his bids sit DEEPER, price dips into them).

Policy: at t=60s place a static $1 GTC bid at (best_bid - OFF) per token; never chase.
Queue = displayed size at that level if present in the L25 bid ladder at placement (else 0 ahead —
we create the level; FIFO front!). Fill when taker-sell prints arrive at price <= our level:
consume queue ahead, then fill us. Cancel unfilled at t=870s. Fills held to redemption.
Arms: C = both tokens; D = favorite token only (bid in [0.55,0.97]). OFF grid: 2c, 4c.
Fees: winner-only 0.07 on winning redeem; rebate +0.0015/sh. No censoring (full resolutions).

Usage: py -3 strategy_lab/wallet_hunt/_maker_ladder_bt.py [n_slugs=4729]
"""
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
from scalp_fill_lib_2026_06_10 import boot   # noqa: E402

L25 = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / "btc.parquet"
TR = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / "btc.parquet"
RNG = np.random.default_rng(13)
N_SLUGS = int(sys.argv[1]) if len(sys.argv) > 1 else 4729
ORDER_USD = 1.0
JOIN_T, STOP_T = 60, 870
FEE = 0.07
REBATE_SH = 0.0015
FAV_LO, FAV_HI = 0.55, 0.97
OFFS = [0.02, 0.04]
NLV = 5

t0 = time.time()
res = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "resolutions.parquet",
                      columns=["slug", "outcome", "slot_start_us"])
res = res[res.slug.str.contains("btc-updown-15m", na=False, regex=False)]
res = res[res.slot_start_us >= int(pd.Timestamp("2026-04-22", tz="UTC").timestamp() * 1e6)]
res = res.drop_duplicates("slug")
win_up = {r.slug: (str(r.outcome).lower() == "up") for r in res.itertuples()}
slugs = sorted(win_up)
if N_SLUGS < len(slugs):
    slugs = sorted(RNG.choice(slugs, size=N_SLUGS, replace=False))
sset = set(slugs)
print(f"universe: {len(slugs)}", flush=True)

f = pq.ParquetFile(TR)
parts = []
for i in range(f.num_row_groups):
    df = f.read_row_group(i, columns=["timestamp_us", "slug", "outcome", "price", "size", "side"]).to_pandas()
    df = df[df.slug.isin(sset) & (df.side.str.lower() == "sell")]
    if len(df):
        parts.append(df)
T = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
trades = {}
for k, g in T.groupby(["slug", "outcome"], sort=False, observed=True):
    trades[k] = (g.timestamp_us.to_numpy(np.int64), g.price.to_numpy(np.float64),
                 g["size"].to_numpy(np.float64))
print(f"sell prints: {len(T)}  t={time.time()-t0:.0f}s", flush=True)

cols = (["timestamp_us", "slug", "outcome"]
        + [f"bid_price_{i}" for i in range(NLV)] + [f"bid_size_{i}" for i in range(NLV)])
f2 = pq.ParquetFile(L25)
parts = []
for i in range(f2.num_row_groups):
    df = f2.read_row_group(i, columns=cols).to_pandas()
    df = df[df.slug.isin(sset)]
    if len(df):
        parts.append(df)
B = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
tob = {}
for k, g in B.groupby(["slug", "outcome"], sort=False, observed=True):
    tob[k] = (g.timestamp_us.to_numpy(np.int64),
              g[[f"bid_price_{i}" for i in range(NLV)]].to_numpy(np.float64),
              g[[f"bid_size_{i}" for i in range(NLV)]].to_numpy(np.float64))
del B, T
print(f"tob series: {len(tob)}  t={time.time()-t0:.0f}s", flush=True)


def sim_ladder(slug, outcome, ss, off, fav_only):
    bk = tob.get((slug, outcome))
    if bk is None:
        return (0.0, 0.0)
    bts, bpm, bsm = bk
    t_join = (ss + JOIN_T) * 1_000_000
    t_stop = (ss + STOP_T) * 1_000_000
    j = int(np.searchsorted(bts, t_join, "right")) - 1
    if j < 0 or not np.isfinite(bpm[j, 0]):
        return (0.0, 0.0)
    bb = bpm[j, 0]
    if fav_only and not (FAV_LO <= bb <= FAV_HI):
        return (0.0, 0.0)
    level = round(bb - off, 2)
    if level <= 0.01:
        return (0.0, 0.0)
    # queue ahead at our level = displayed size at that exact price in the ladder (else 0 — new level)
    row_p, row_s = bpm[j], bsm[j]
    q_ahead = 0.0
    for li in range(NLV):
        if np.isfinite(row_p[li]) and abs(row_p[li] - level) < 0.005:
            q_ahead = row_s[li] if np.isfinite(row_s[li]) else 0.0
            break
    tr = trades.get((slug, outcome))
    if tr is None:
        return (0.0, 0.0)
    tts, tpx, tsz = tr
    a = int(np.searchsorted(tts, t_join, "left"))
    b = int(np.searchsorted(tts, t_stop, "left"))
    target = ORDER_USD / level
    filled = 0.0
    for m in range(a, b):
        if tpx[m] > level + 1e-9:
            continue
        take = tsz[m]
        eat = min(q_ahead, take)
        q_ahead -= eat
        rem = take - eat
        if rem > 0:
            filled += min(rem, target - filled)
            if filled >= target - 1e-9:
                break
    return (filled, filled * level)


rows = []
for n, slug in enumerate(slugs):
    ss = int(slug.rsplit("-", 1)[1])
    wu = win_up[slug]
    rec = dict(slug=slug, ss=ss)
    for off in OFFS:
        for arm, fav in (("C", False), ("D", True)):
            for side in ("Up", "Down"):
                fsh, cost = sim_ladder(slug, side, ss, off, fav)
                won = (side == "Up") == wu
                if fsh > 0:
                    ev = cost / fsh
                    pnl = (fsh * (1 - ev) * (1 - FEE * ev)) if won else -cost
                    pnl += fsh * REBATE_SH
                else:
                    pnl = 0.0
                tag = f"{arm}{int(off*100)}_{side}"
                rec[f"{tag}_cost"] = cost
                rec[f"{tag}_pnl"] = pnl
    rows.append(rec)
    if n % 1000 == 0:
        print(f"  {n}/{len(slugs)} t={time.time()-t0:.0f}s", flush=True)

R = pd.DataFrame(rows)
R.to_parquet(ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_maker_ladder_bt.parquet", index=False)
days = (R.ss.max() - R.ss.min()) / 86400
print(f"\nsimulated {len(R)} windows over {days:.0f} days")
for off in OFFS:
    for arm in ("C", "D"):
        p = R[f"{arm}{int(off*100)}_Up_pnl"] + R[f"{arm}{int(off*100)}_Down_pnl"]
        c = R[f"{arm}{int(off*100)}_Up_cost"] + R[f"{arm}{int(off*100)}_Down_cost"]
        fired = c > 0
        both = (R[f"{arm}{int(off*100)}_Up_cost"] > 0) & (R[f"{arm}{int(off*100)}_Down_cost"] > 0)
        lo, hi = boot(p[fired].values) if fired.sum() > 5 else (np.nan, np.nan)
        print(f"ARM {arm} off={off:.2f}: fill% {fired.mean():.0%}  both {both.mean():.0%}  "
              f"$/fired {p[fired].mean():+.4f} CI[{lo:+.4f},{hi:+.4f}]  "
              f"deployed ${c[fired].mean():.2f}  total ${p.sum():+.2f} (${p.sum()/days:+.2f}/day)")
