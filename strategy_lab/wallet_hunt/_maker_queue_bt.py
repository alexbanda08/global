"""
_maker_queue_bt.py — queue-aware MAKER shadow backtest of the b945 strategy (offline).

Replicates the live probe spec (TV_AGENT_SPEC_MAKER_PROBE_BTC15M_2026_06_12.md) on canonical data:
  ARM A: join best bid on BOTH tokens with $1, track the bid (requote on level change), hold fills
         to redemption. ARM B: same but only the favorite token (bid in [0.55,0.97]).
Fill models (bracket truth):
  FIFO : strict queue position — join tail (queue_ahead = displayed bid size, artifact-resolved);
         sell prints at-or-below our level consume queue first, then fill us. Requote resets queue.
         LOWER BOUND (real queues also shrink via cancels ahead).
  PROP : engine's proportional share our_sh/(our_sh+queue) per print (shadow_engine/runner.py model).
         UPPER-ish bound.
Settlement: winner-only 0.07 fee on winning leg redeem; loser leg = -cost. Rebate income
  +0.0015/sh on maker fills (POLYMARKET_REBATE_FACTS pool-prorated estimate).
NO CENSORING: every simulated window joins canonical resolutions (the 05-28 maker-arb trap).

Usage: py -3 strategy_lab/wallet_hunt/_maker_queue_bt.py [n_slugs=1000]
"""
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
from scalp_fill_lib_2026_06_10 import resolve_size, boot   # noqa: E402

L25 = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / "btc.parquet"
TR = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / "btc.parquet"
RNG = np.random.default_rng(13)
N_SLUGS = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
ORDER_USD = 1.0
JOIN_T, STOP_T = 60, 870
FEE = 0.07
REBATE_SH = 0.0015
FAV_LO, FAV_HI = 0.55, 0.97

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
print(f"universe: {len(slugs)} slugs (of {len(win_up)})", flush=True)

# trades (sell prints only)
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

# books top-of-book
f2 = pq.ParquetFile(L25)
parts = []
cols = ["timestamp_us", "slug", "outcome", "bid_price_0", "bid_size_0", "ask_price_0"]
for i in range(f2.num_row_groups):
    df = f2.read_row_group(i, columns=cols).to_pandas()
    df = df[df.slug.isin(sset)]
    if len(df):
        parts.append(df)
B = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
tob = {}
for k, g in B.groupby(["slug", "outcome"], sort=False, observed=True):
    tob[k] = (g.timestamp_us.to_numpy(np.int64), g.bid_price_0.to_numpy(np.float64),
              g.bid_size_0.to_numpy(np.float64), g.ask_price_0.to_numpy(np.float64))
del B, T
print(f"tob series: {len(tob)}  t={time.time()-t0:.0f}s", flush=True)


def sim_token(slug, outcome, ss, fav_only):
    """Simulate one resting $1 bid tracking best bid on (slug,outcome).
    Returns dict(fifo=..., prop=...) each (filled_sh, cost, n_requotes, fill_ts) or zeros."""
    bk = tob.get((slug, outcome))
    tr = trades.get((slug, outcome))
    if bk is None:
        return None
    bts, bp, bsz, bap = bk
    t_join = (ss + JOIN_T) * 1_000_000
    t_stop = (ss + STOP_T) * 1_000_000
    j = int(np.searchsorted(bts, t_join, "right")) - 1
    if j < 0:
        return None
    out = {}
    # build the level path: best bid at each book row from join to stop
    lo = j
    hi = int(np.searchsorted(bts, t_stop, "right"))
    seg_ts, seg_bp = bts[lo:hi], bp[lo:hi]
    if not len(seg_ts) or not np.isfinite(seg_bp[0]):
        return None
    if fav_only and not (FAV_LO <= seg_bp[0] <= FAV_HI):
        return None
    # trades within window
    if tr is not None:
        tts, tpx, tsz = tr
        a = int(np.searchsorted(tts, t_join, "left"))
        b = int(np.searchsorted(tts, t_stop, "left"))
        tts, tpx, tsz = tts[a:b], tpx[a:b], tsz[a:b]
    else:
        tts = np.array([], np.int64); tpx = tsz = np.array([])

    for model in ("fifo", "prop"):
        level = seg_bp[0]
        q_ahead, _ = resolve_size(bts, bsz, lo)
        if not np.isfinite(q_ahead):
            q_ahead = 1e9 if model == "fifo" else 500.0   # unknown queue: harsh for fifo
        our_sh_target = ORDER_USD / max(level, 0.01)
        filled, cost, requotes, fill_ts = 0.0, 0.0, 0, None
        ki = 0  # book row cursor
        for m in range(len(tts)):
            # advance book to trade time; requote if level changed
            while ki + 1 < len(seg_ts) and seg_ts[ki + 1] <= tts[m]:
                ki += 1
                if np.isfinite(seg_bp[ki]) and abs(seg_bp[ki] - level) > 1e-9:
                    if fav_only and not (FAV_LO <= seg_bp[ki] <= FAV_HI):
                        level = np.nan
                        continue
                    level = seg_bp[ki]
                    idx_global = lo + ki
                    q_ahead, _ = resolve_size(bts, bsz, idx_global)
                    if not np.isfinite(q_ahead):
                        q_ahead = 1e9 if model == "fifo" else 500.0
                    our_sh_target = (ORDER_USD - cost) / max(level, 0.01)
                    requotes += 1
            if not np.isfinite(level) or filled >= our_sh_target - 1e-9:
                if filled >= our_sh_target - 1e-9:
                    break
                continue
            if tpx[m] > level + 1e-9:
                continue
            if model == "fifo":
                take = tsz[m]
                eat = min(q_ahead, take)
                q_ahead -= eat
                rem = take - eat
                if rem > 0:
                    fsh = min(rem, our_sh_target - filled)
                    filled += fsh; cost += fsh * level
                    fill_ts = fill_ts or tts[m]
            else:
                share = our_sh_target / (our_sh_target + max(q_ahead, 1.0))
                fsh = min(tsz[m] * share, our_sh_target - filled)
                filled += fsh; cost += fsh * level
                fill_ts = fill_ts or tts[m]
        out[model] = (filled, cost, requotes, fill_ts)
    return out


rows = []
for n, slug in enumerate(slugs):
    ss = int(slug.rsplit("-", 1)[1])
    wu = win_up[slug]
    rec = dict(slug=slug, ss=ss)
    for arm, fav in (("A", False), ("B", True)):
        for side in ("Up", "Down"):
            if fav:
                # favorite = token with bid in band at join; sim_token self-filters
                pass
            r = sim_token(slug, side, ss, fav)
            for model in ("fifo", "prop"):
                fsh, cost, rq, fts = (r[model] if r else (0.0, 0.0, 0, None))
                won = (side == "Up") == wu
                if fsh > 0:
                    ev = cost / fsh
                    pnl = fsh * (1 - ev) * (1 - FEE * ev) - 0 if won else -cost
                    if won:
                        pnl = fsh * (1 - ev) * (1 - FEE * ev)
                    pnl += fsh * REBATE_SH
                else:
                    pnl = 0.0
                rec[f"{arm}_{model}_{side}_sh"] = fsh
                rec[f"{arm}_{model}_{side}_cost"] = cost
                rec[f"{arm}_{model}_{side}_pnl"] = pnl
    rows.append(rec)
    if n % 200 == 0:
        print(f"  {n}/{len(slugs)} t={time.time()-t0:.0f}s", flush=True)

R = pd.DataFrame(rows)
R.to_parquet(ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_maker_queue_bt.parquet", index=False)
days = (R.ss.max() - R.ss.min()) / 86400
print(f"\nsimulated {len(R)} windows over {days:.0f} days  t={time.time()-t0:.0f}s")

for arm in ("A", "B"):
    for model in ("fifo", "prop"):
        pnl = R[f"{arm}_{model}_Up_pnl"] + R[f"{arm}_{model}_Down_pnl"]
        cost = R[f"{arm}_{model}_Up_cost"] + R[f"{arm}_{model}_Down_cost"]
        fills = ((R[f"{arm}_{model}_Up_sh"] > 0).astype(int) + (R[f"{arm}_{model}_Down_sh"] > 0))
        both = ((R[f"{arm}_{model}_Up_sh"] > 0) & (R[f"{arm}_{model}_Down_sh"] > 0))
        fired = cost > 0
        lo, hi = boot(pnl[fired].values) if fired.sum() > 5 else (np.nan, np.nan)
        print(f"\nARM {arm} [{model}]: windows w/ fill {fired.mean():.0%}  both-sides {both.mean():.0%}"
              f"  $/window(fired) {pnl[fired].mean():+.4f} CI[{lo:+.4f},{hi:+.4f}]"
              f"  deployed/window ${cost[fired].mean():.2f}  total ${pnl.sum():+.2f} (${pnl.sum()/days:+.2f}/day)")
