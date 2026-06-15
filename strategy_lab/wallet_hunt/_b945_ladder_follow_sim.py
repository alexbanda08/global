"""
_b945_ladder_follow_sim.py — PRE-REGISTERED two-sided price-following proportional-ladder maker sim.

PURPOSE
-------
Faithful simulation of the b945-decoded strategy:
  - At t+60s, place resting bids on BOTH tokens simultaneously.
  - Clip size proportional to price (~0.27×price×$100-scale) with a per-side $100 budget cap.
  - Requote by following the best bid every 1s book tick (price-following, not static).
  - Hold all fills to resolution; NO taker exits.
  - Accounting CHAIN-TRUE: winner leg redeems full $1, no fee (verified vs b945's 2,010 REDEEMs);
    maker fills pay $0 + rebate_income = +0.0015/sh.
  - Score at SLUG level on paired cost sum (pvs = vwap_up + vwap_dn on the paired qty).

WHY DIFFERENT FROM PRIOR ARMS A/B/C/D
--------------------------------------
- Arms A/B (_maker_queue_bt.py): $1 fixed clip, per-fill markout → wrong objective.
- Arms C/D (_maker_ladder_bt.py): static offsets, one-sided → wrong execution model.
- This sim: clip∝price two-sided, price-following requote, slug-level paired scoring.

PRE-REGISTRATION (written before any results are computed)
----------------------------------------------------------
Universe : ALL 4,729 btc-updown-15m windows Apr 22 → Jun 11 (50 days).
Cells    : 2 fill models × 2 ladder variants = 4 cells
           Fill models : FIFO (strict lower bound) | PROP (proportional upper bound)
           Ladder variants : L1 = join-bid only (1 level, best bid)
                             L3 = 3-level ladder (best bid, bid−1¢, bid−2¢)
           Budget per side: min(0.27 × price × 100, 100) USD — matches b945's clip∝price pattern.
Metrics  : % windows with both-side fills, pair fraction (pairs/total shares),
           pvs median + %<1.00 + %<0.98, paired $/win, residual $/win, net $/win,
           bootstrap CI95, ex-top2.
GO/NO-GO GATE (pre-registered from the decode):
  PASS requires ALL of: achieved pvs ≲ 0.98 AND pair fraction ≳ 44% AND net CI95 > 0
  in at least one cell under FIFO (lower bound).
  Basis: b945 achieves pvs~0.97, 44% pair fraction, net +$4.2/slug + $2.3/slug rebates.
  If FIFO can't hit pvs < 0.98 at ≳44% pairs, edge = his infra moat (sub-second requote
  queue position we cannot simulate as reachable), not a replicable signal.

SANITY CHECK: prints 3 windows by hand before full run.

Usage: py -3 strategy_lab/wallet_hunt/_b945_ladder_follow_sim.py [n_slugs=4729]
Output: cache/_b945_ladder_sim.parquet
"""
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
from scalp_fill_lib_2026_06_10 import resolve_size, boot  # noqa: E402

L25 = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / "btc.parquet"
TR  = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / "btc.parquet"
RNG = np.random.default_rng(42)

N_SLUGS  = int(sys.argv[1]) if len(sys.argv) > 1 else 4729
JOIN_T   = 60          # seconds after slot_start to begin quoting
STOP_T   = 870         # seconds after slot_start to cancel unfilled (14.5 min)
FEE      = 0.07        # winner-only Polymarket taker fee (we're makers → $0; used on final redeem)
REBATE   = 0.0015      # maker rebate income per share
BUDGET   = 100.0       # max USD per side per slug
CLIP_K   = 0.27        # clip = CLIP_K × price × 100 (b945 scale)
NLV_BOOK = 5           # load 5 bid levels from L25 (need only best bid + 2 below)

# Ladder level offsets (from best bid at join/requote time)
LADDER_L1 = [0.0]                   # join-bid only
LADDER_L3 = [0.0, -0.01, -0.02]    # 3-level: join, −1¢, −2¢

SANITY_N = 3  # print this many windows by hand

# ──────────────────────────────────────────
# Load resolutions
# ──────────────────────────────────────────
t0 = time.time()
res = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "resolutions.parquet",
                      columns=["slug", "outcome", "slot_start_us"])
res = res[res.slug.str.contains("btc-updown-15m", na=False, regex=False)]
res = res[res.slot_start_us >= int(pd.Timestamp("2026-04-22", tz="UTC").timestamp() * 1e6)]
res = res.drop_duplicates("slug")
win_up = {r.slug: (str(r.outcome).lower() == "up") for r in res.itertuples()}
slugs  = sorted(win_up)
if N_SLUGS < len(slugs):
    slugs = sorted(RNG.choice(slugs, size=N_SLUGS, replace=False))
sset = set(slugs)
print(f"[load] universe: {len(slugs)} slugs (of {len(win_up)})  t={time.time()-t0:.0f}s", flush=True)

# ──────────────────────────────────────────
# Load trade tape (sell prints only)
# ──────────────────────────────────────────
f = pq.ParquetFile(TR)
parts = []
for i in range(f.num_row_groups):
    df = f.read_row_group(i, columns=["timestamp_us","slug","outcome","price","size","side"]).to_pandas()
    df = df[df.slug.isin(sset) & (df.side.str.lower() == "sell")]
    if len(df):
        parts.append(df)
T = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
trades = {}
for k, g in T.groupby(["slug","outcome"], sort=False, observed=True):
    trades[k] = (g.timestamp_us.to_numpy(np.int64),
                 g.price.to_numpy(np.float64),
                 g["size"].to_numpy(np.float64))
print(f"[load] sell prints: {len(T)}  t={time.time()-t0:.0f}s", flush=True)
del T

# ──────────────────────────────────────────
# Load L25 book (top NLV_BOOK bid levels)
# ──────────────────────────────────────────
cols = (["timestamp_us","slug","outcome"]
        + [f"bid_price_{i}" for i in range(NLV_BOOK)]
        + [f"bid_size_{i}"  for i in range(NLV_BOOK)])
f2 = pq.ParquetFile(L25)
parts = []
for i in range(f2.num_row_groups):
    df = f2.read_row_group(i, columns=cols).to_pandas()
    df = df[df.slug.isin(sset)]
    if len(df):
        parts.append(df)
B = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
tob = {}
for k, g in B.groupby(["slug","outcome"], sort=False, observed=True):
    tob[k] = (g.timestamp_us.to_numpy(np.int64),
              g[[f"bid_price_{i}" for i in range(NLV_BOOK)]].to_numpy(np.float64),
              g[[f"bid_size_{i}"  for i in range(NLV_BOOK)]].to_numpy(np.float64))
print(f"[load] book series: {len(tob)}  t={time.time()-t0:.0f}s", flush=True)
del B


# ──────────────────────────────────────────
# Core sim: one token, one ladder variant, one fill model
# Returns dict with fill stats
# ──────────────────────────────────────────
def sim_follow(slug, outcome, ss, ladder_offsets, fill_model, verbose=False):
    """
    Simulate price-following proportional-ladder bids on one token.

    Args:
        slug           : market slug
        outcome        : "Up" or "Down"
        ss             : slot_start (seconds)
        ladder_offsets : list of price offsets from best bid (e.g. [0, -0.01, -0.02])
        fill_model     : "fifo" or "prop"
        verbose        : if True, print sanity trace

    Returns dict: filled_sh, cost, n_requotes, pair-relevant stats
    """
    bk = tob.get((slug, outcome))
    tr = trades.get((slug, outcome))
    if bk is None:
        return {"filled_sh": 0.0, "cost": 0.0, "n_requotes": 0}

    bts, bpm, bsm = bk  # timestamps, bid price matrix (NxNLV), bid size matrix

    t_join = (ss + JOIN_T) * 1_000_000
    t_stop = (ss + STOP_T) * 1_000_000

    j0 = int(np.searchsorted(bts, t_join, "right")) - 1
    if j0 < 0 or not np.isfinite(bpm[j0, 0]):
        return {"filled_sh": 0.0, "cost": 0.0, "n_requotes": 0}

    best_bid0 = bpm[j0, 0]
    budget = min(CLIP_K * best_bid0 * 100.0, BUDGET)

    hi = int(np.searchsorted(bts, t_stop, "right"))
    seg_ts  = bts[j0:hi]
    seg_bpm = bpm[j0:hi]
    seg_bsm = bsm[j0:hi]

    # trade tape within window
    if tr is not None:
        tts_all, tpx_all, tsz_all = tr
        ta = int(np.searchsorted(tts_all, t_join, "left"))
        tb = int(np.searchsorted(tts_all, t_stop, "left"))
        tts = tts_all[ta:tb]
        tpx = tpx_all[ta:tb]
        tsz = tsz_all[ta:tb]
    else:
        tts = np.array([], np.int64)
        tpx = np.array([])
        tsz = np.array([])

    n_levels = len(ladder_offsets)

    # State per level: level price, queue ahead, filled shares, cost, target shares
    levels     = np.full(n_levels, np.nan)
    q_ahead    = np.zeros(n_levels)
    filled_sh  = np.zeros(n_levels)
    cost_sh    = np.zeros(n_levels)
    targets    = np.zeros(n_levels)

    # Initialize levels at join
    best_bid = bpm[j0, 0]
    for li, off in enumerate(ladder_offsets):
        lev = round(best_bid + off, 4)
        if lev <= 0.01:
            continue
        levels[li] = lev
        # queue ahead: scan displayed bid levels for this price
        qa = 0.0
        for bi in range(NLV_BOOK):
            p = bpm[j0, bi]
            if not np.isfinite(p):
                break
            if abs(p - lev) < 0.005:
                qa, _ = resolve_size(seg_ts, seg_bsm[:, bi], 0)
                break
        q_ahead[li]  = qa if np.isfinite(qa) else (1e9 if fill_model == "fifo" else 500.0)
        targets[li]  = (budget / n_levels) / max(lev, 0.01)

    n_requotes = 0
    ki = 0  # book cursor

    if verbose:
        print(f"  [{slug} {outcome}] join t={ss+JOIN_T}  best_bid={best_bid:.4f}  budget={budget:.2f}")
        for li in range(n_levels):
            print(f"    level[{li}] = {levels[li]:.4f}  q_ahead={q_ahead[li]:.1f}  target={targets[li]:.2f}sh")

    for m in range(len(tts)):
        # advance book cursor to trade time; check for requote
        while ki + 1 < len(seg_ts) and seg_ts[ki+1] <= tts[m]:
            ki += 1
            new_best = seg_bpm[ki, 0]
            if not np.isfinite(new_best):
                continue
            # requote each level: shift by same offsets from new best bid
            for li, off in enumerate(ladder_offsets):
                new_lev = round(new_best + off, 4)
                if new_lev <= 0.01:
                    levels[li] = np.nan
                    continue
                old_lev = levels[li]
                if np.isfinite(old_lev) and abs(new_lev - old_lev) < 1e-9:
                    continue  # no change
                # price changed → requote: reset queue at new level
                levels[li]  = new_lev
                # compute remaining budget as target
                cost_so_far = cost_sh[li]
                targets[li] = (budget / n_levels - cost_so_far) / max(new_lev, 0.01)
                if targets[li] <= 0:
                    levels[li] = np.nan
                    continue
                # queue at new level
                qa = 0.0
                for bi in range(NLV_BOOK):
                    p = seg_bpm[ki, bi]
                    if not np.isfinite(p):
                        break
                    if abs(p - new_lev) < 0.005:
                        idx_g = ki
                        qa, _ = resolve_size(seg_ts, seg_bsm[:, bi], idx_g)
                        break
                q_ahead[li] = qa if np.isfinite(qa) else (1e9 if fill_model == "fifo" else 500.0)
                n_requotes += 1

        # process trade print against each level
        for li in range(n_levels):
            lev = levels[li]
            if not np.isfinite(lev):
                continue
            if filled_sh[li] >= targets[li] - 1e-9:
                continue
            if tpx[m] > lev + 1e-9:
                continue

            to_fill = targets[li] - filled_sh[li]
            if fill_model == "fifo":
                take = tsz[m]
                eat  = min(q_ahead[li], take)
                q_ahead[li] -= eat
                rem = take - eat
                if rem > 0:
                    fsh = min(rem, to_fill)
                    filled_sh[li] += fsh
                    cost_sh[li]   += fsh * lev
            else:  # prop
                denom = max(q_ahead[li], 1.0) + to_fill
                share = to_fill / denom
                fsh   = min(tsz[m] * share, to_fill)
                filled_sh[li] += fsh
                cost_sh[li]   += fsh * lev

    total_filled = filled_sh.sum()
    total_cost   = cost_sh.sum()

    if verbose and total_filled > 0:
        for li in range(n_levels):
            print(f"    level[{li}] filled={filled_sh[li]:.2f}sh cost={cost_sh[li]:.4f}  level={levels[li]:.4f}")
        print(f"    TOTAL: filled={total_filled:.2f}sh cost={total_cost:.4f}  n_req={n_requotes}")

    return {"filled_sh": total_filled, "cost": total_cost, "n_requotes": n_requotes}


# ──────────────────────────────────────────
# SANITY CHECK: 3 windows by hand
# ──────────────────────────────────────────
print("\n=== SANITY CHECK (3 windows) ===", flush=True)
sanity_count = 0
for slug in slugs:
    if sanity_count >= SANITY_N:
        break
    ss = int(slug.rsplit("-", 1)[1])
    wu = win_up[slug]
    has_data = (tob.get((slug, "Up")) is not None and tob.get((slug, "Down")) is not None)
    if not has_data:
        continue
    print(f"\nSlug: {slug}  outcome={'UP' if wu else 'DOWN'}")
    for side in ("Up", "Down"):
        r_l3_fifo = sim_follow(slug, side, ss, LADDER_L3, "fifo", verbose=True)
    sanity_count += 1


# ──────────────────────────────────────────
# Full simulation — all 4 cells
# ──────────────────────────────────────────
print(f"\n[sim] running {len(slugs)} slugs × 4 cells ...", flush=True)

rows = []
for n, slug in enumerate(slugs):
    ss = int(slug.rsplit("-", 1)[1])
    wu = win_up[slug]
    rec = dict(slug=slug, ss=ss, won_up=wu)

    for lname, loffs in (("L1", LADDER_L1), ("L3", LADDER_L3)):
        for fmodel in ("fifo", "prop"):
            tag = f"{lname}_{fmodel}"
            r_up = sim_follow(slug, "Up",   ss, loffs, fmodel)
            r_dn = sim_follow(slug, "Down", ss, loffs, fmodel)

            q_up, q_dn = r_up["filled_sh"], r_dn["filled_sh"]
            c_up, c_dn = r_up["cost"],       r_dn["cost"]
            vwap_up = c_up / q_up if q_up > 1e-9 else np.nan
            vwap_dn = c_dn / q_dn if q_dn > 1e-9 else np.nan

            pairs  = min(q_up, q_dn) if (q_up > 1e-9 and q_dn > 1e-9) else 0.0
            pvs    = (vwap_up + vwap_dn) if (q_up > 1e-9 and q_dn > 1e-9) else np.nan
            res_up = q_up - pairs
            res_dn = q_dn - pairs

            # Paired PnL: pairs × (1 − pvs) — redeems at $1 both legs, no fee on maker redemption
            paired_pnl = pairs * (1.0 - pvs) if np.isfinite(pvs) else 0.0

            # Residual PnL — winner-only 0.07 fee on redemption (CHAIN-TRUE per REDEEM validation)
            # Up residual
            up_won = wu  # Up token wins iff outcome is Up
            if res_up > 1e-9 and np.isfinite(vwap_up):
                ev_up = vwap_up
                if up_won:
                    res_up_pnl = res_up * (1.0 - ev_up) * (1.0 - FEE * ev_up)
                else:
                    res_up_pnl = -res_up * ev_up
            else:
                res_up_pnl = 0.0
            # Down residual
            dn_won = not wu
            if res_dn > 1e-9 and np.isfinite(vwap_dn):
                ev_dn = vwap_dn
                if dn_won:
                    res_dn_pnl = res_dn * (1.0 - ev_dn) * (1.0 - FEE * ev_dn)
                else:
                    res_dn_pnl = -res_dn * ev_dn
            else:
                res_dn_pnl = 0.0

            residual_pnl = res_up_pnl + res_dn_pnl
            rebate_pnl   = (q_up + q_dn) * REBATE
            net_pnl      = paired_pnl + residual_pnl + rebate_pnl

            rec[f"{tag}_q_up"]         = q_up
            rec[f"{tag}_q_dn"]         = q_dn
            rec[f"{tag}_cost_up"]      = c_up
            rec[f"{tag}_cost_dn"]      = c_dn
            rec[f"{tag}_pvs"]          = pvs
            rec[f"{tag}_pairs"]        = pairs
            rec[f"{tag}_paired_pnl"]   = paired_pnl
            rec[f"{tag}_residual_pnl"] = residual_pnl
            rec[f"{tag}_rebate_pnl"]   = rebate_pnl
            rec[f"{tag}_net_pnl"]      = net_pnl
            rec[f"{tag}_nreq_up"]      = r_up["n_requotes"]
            rec[f"{tag}_nreq_dn"]      = r_dn["n_requotes"]

    rows.append(rec)
    if n % 500 == 0:
        print(f"  {n}/{len(slugs)} t={time.time()-t0:.0f}s", flush=True)

R = pd.DataFrame(rows)
out_path = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_b945_ladder_sim.parquet"
R.to_parquet(out_path, index=False)
days = (R.ss.max() - R.ss.min()) / 86400
print(f"\n[done] {len(R)} windows over {days:.0f}d  saved to {out_path}  t={time.time()-t0:.0f}s")


# ──────────────────────────────────────────
# RESULTS TABLE
# ──────────────────────────────────────────
print("\n=== RESULTS TABLE ===")
print(f"{'Cell':<14} {'%both':>6} {'pf%':>5} {'pvs_med':>8} {'%<1':>6} {'%<.98':>6} "
      f"{'pair$/w':>8} {'res$/w':>8} {'net$/w':>8} {'CI95':>18} {'ex-top2':>8}")
print("-"*100)

for lname in ("L1","L3"):
    for fmodel in ("fifo","prop"):
        tag  = f"{lname}_{fmodel}"
        both = (R[f"{tag}_q_up"] > 1e-9) & (R[f"{tag}_q_dn"] > 1e-9)
        any_ = (R[f"{tag}_q_up"] > 1e-9) | (R[f"{tag}_q_dn"] > 1e-9)

        # pair fraction = total paired shares / total filled shares
        total_pairs  = R[f"{tag}_pairs"].sum()
        total_filled = (R[f"{tag}_q_up"] + R[f"{tag}_q_dn"]).sum()
        pf = total_pairs / total_filled if total_filled > 0 else 0.0

        pvs_vals = R.loc[both, f"{tag}_pvs"].dropna()
        pvs_med  = pvs_vals.median() if len(pvs_vals) > 0 else np.nan
        pct_lt1  = (pvs_vals < 1.0).mean() if len(pvs_vals) > 0 else np.nan
        pct_lt98 = (pvs_vals < 0.98).mean() if len(pvs_vals) > 0 else np.nan

        # per-slug PnL (only windows where at least one side fired)
        net_pnl = R.loc[any_, f"{tag}_net_pnl"]
        pnl_pair = R.loc[both, f"{tag}_paired_pnl"]
        pnl_res  = R.loc[both, f"{tag}_residual_pnl"]

        lo, hi  = boot(net_pnl.values) if len(net_pnl) > 5 else (np.nan, np.nan)

        # ex-top2
        if len(net_pnl) > 2:
            pnl_sorted = net_pnl.values.copy()
            pnl_sorted.sort()
            ex2 = pnl_sorted[:-2].mean()
        else:
            ex2 = np.nan

        print(f"{tag:<14} {both.mean():>6.1%} {pf:>5.1%} {pvs_med:>8.4f} {pct_lt1:>6.1%} {pct_lt98:>6.1%} "
              f"{pnl_pair.mean():>8.4f} {pnl_res.mean():>8.4f} {net_pnl.mean():>8.4f} "
              f"[{lo:>+.4f},{hi:>+.4f}] {ex2:>8.4f}")

# b945 ground truth for comparison
print("\n--- b945 ground truth (from r2 decode, 1,562 slugs) ---")
print(f"{'GT':14} {'67-86%':>6} {'44%':>5} {'0.970':>8} {'70-86%':>6} {'47%':>6} "
      f"{'22.71':>8} {'-18.78':>8} {'4.23':>8} {'n/a':>18} {'n/a':>8}")

# GO/NO-GO GATE verdict
print("\n=== GO/NO-GO GATE (pre-registered) ===")
print("Gate: achieved pvs ≲ 0.98 AND pair fraction ≳ 44% AND net CI95 > 0 (FIFO cells only)")
gate_pass = False
for lname in ("L1","L3"):
    tag = f"{lname}_fifo"
    both = (R[f"{tag}_q_up"] > 1e-9) & (R[f"{tag}_q_dn"] > 1e-9)
    any_ = (R[f"{tag}_q_up"] > 1e-9) | (R[f"{tag}_q_dn"] > 1e-9)
    pvs_vals = R.loc[both, f"{tag}_pvs"].dropna()
    pvs_med  = pvs_vals.median() if len(pvs_vals) > 0 else np.nan
    total_pairs  = R[f"{tag}_pairs"].sum()
    total_filled = (R[f"{tag}_q_up"] + R[f"{tag}_q_dn"]).sum()
    pf = total_pairs / total_filled if total_filled > 0 else 0.0
    net_pnl = R.loc[any_, f"{tag}_net_pnl"]
    lo, hi  = boot(net_pnl.values) if len(net_pnl) > 5 else (np.nan, np.nan)
    g_pvs  = np.isfinite(pvs_med) and pvs_med <= 0.98
    g_pf   = pf >= 0.44
    g_ci   = np.isfinite(lo) and lo > 0
    verdict = "PASS" if (g_pvs and g_pf and g_ci) else "FAIL"
    print(f"  {tag}: pvs_med={pvs_med:.4f}({'ok' if g_pvs else 'FAIL'})  "
          f"pf={pf:.1%}({'ok' if g_pf else 'FAIL'})  "
          f"CI=[{lo:+.4f},{hi:+.4f}]({'ok' if g_ci else 'FAIL'})  → {verdict}")
    if g_pvs and g_pf and g_ci:
        gate_pass = True

if gate_pass:
    print("\nGATE: GO — at least one FIFO cell passes all three criteria.")
else:
    print("\nGATE: NO-GO — no FIFO cell passes all three criteria.")
    print("Interpretation: the edge is b945's infra+rebate moat (sub-second requote queue position),")
    print("  not a replicable signal accessible from our queue position. Do NOT deploy.")
