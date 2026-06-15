"""
_maker_queue_bt_oraclegate.py — oracle-gated variant of the arm-B maker shadow backtest.

Pre-registration (3 thresholds × 2 fill models = 6 cells):
  E-FIFO-2:  favorite band [0.55,0.97], gate |rtds_ret5| >= $2, FIFO fill model
  E-PROP-2:  same, proportional fill model
  E-FIFO-5:  favorite band, gate |rtds_ret5| >= $5, FIFO
  E-PROP-5:  same, proportional
  E-FIFO-10: favorite band, gate |rtds_ret5| >= $10, FIFO
  E-PROP-10: same, proportional

Hypothesis (model-D signature): b945 supplies liquidity during taker panics when oracle is
moving → wider effective spread → positive selection vs unconditional arm-B (flat).

Gate logic: at quote-join time AND at each requote (level change), check the RTDS 5s return
at that moment. If |rtds_ret5| < threshold → skip (no quote this window).
RTDS ret5 = rtds_price(t) - rtds_price(t-5s), computed from the 1Hz chainlink RTDS series.

Same fee/rebate/universe as arm B: winner-only 0.07 fee, +0.0015/sh rebate,
full 4,729-window universe (btc-updown-15m, Apr 22 – Jun 11).

Results vs arm-B baseline: paired diff per window (gate adds filtering, arm-B has
pnl=0 on filtered windows too since they never quoted → paired diff = E_pnl - B_pnl
where B_pnl=0 for gated-out windows, so pair diff = E_pnl for those rows).

Output:
  strategy_lab/wallet_hunt/cache/_maker_oraclegate_bt.parquet
  Printed summary per cell.

Usage: py -3 strategy_lab/wallet_hunt/_maker_queue_bt_oraclegate.py
"""
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from scalp_fill_lib_2026_06_10 import resolve_size, boot  # noqa: E402
from load import load_chainlink_rtds                       # noqa: E402

L25 = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / "btc.parquet"
TR = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / "btc.parquet"
RNG = np.random.default_rng(13)
ORDER_USD = 1.0
JOIN_T, STOP_T = 60, 870
FEE = 0.07
REBATE_SH = 0.0015
FAV_LO, FAV_HI = 0.55, 0.97
THRESHOLDS = [2.0, 5.0, 10.0]  # |rtds_ret5| in USD

t0 = time.time()

# ── resolutions (full universe, same as arm B) ──────────────────────────────
res = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "resolutions.parquet",
                      columns=["slug", "outcome", "slot_start_us"])
res = res[res.slug.str.contains("btc-updown-15m", na=False, regex=False)]
res = res[res.slot_start_us >= int(pd.Timestamp("2026-04-22", tz="UTC").timestamp() * 1e6)]
res = res.drop_duplicates("slug")
win_up = {r.slug: (str(r.outcome).lower() == "up") for r in res.itertuples()}
slugs = sorted(win_up)
sset = set(slugs)
print(f"universe: {len(slugs)} slugs  t={time.time()-t0:.0f}s", flush=True)

# ── RTDS 1Hz → 5s return lookup ─────────────────────────────────────────────
print("loading RTDS...", flush=True)
rtds = load_chainlink_rtds(asset="BTC")
# keep only timestamp_us and price; sort
rtds = rtds[["timestamp_us", "price_value"]].dropna().sort_values("timestamp_us").reset_index(drop=True)
rtds_ts = rtds["timestamp_us"].to_numpy(np.int64)
rtds_px = rtds["price_value"].to_numpy(np.float64)
print(f"RTDS rows: {len(rtds_ts)}  t={time.time()-t0:.0f}s", flush=True)
del rtds


def rtds_ret5_at(t_us: int) -> float:
    """5-second RTDS price change ending at t_us (microseconds). Returns nan if no data."""
    hi = int(np.searchsorted(rtds_ts, t_us, "right")) - 1
    if hi < 0:
        return np.nan
    t_5s_ago = t_us - 5_000_000
    lo = int(np.searchsorted(rtds_ts, t_5s_ago, "left"))
    if lo > hi:
        return np.nan
    return float(rtds_px[hi] - rtds_px[lo])


# ── trades (sell prints only) ────────────────────────────────────────────────
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

# ── books top-of-book ────────────────────────────────────────────────────────
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


def sim_token_gated(slug, outcome, ss, threshold):
    """Simulate resting $1 bid (favorite band) gated by |rtds_ret5| >= threshold.
    Returns dict(fifo=..., prop=...) each (filled_sh, cost, n_requotes, fill_ts) or None."""
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
    lo = j
    hi = int(np.searchsorted(bts, t_stop, "right"))
    seg_ts, seg_bp = bts[lo:hi], bp[lo:hi]
    if not len(seg_ts) or not np.isfinite(seg_bp[0]):
        return None
    # favorite-band filter at join
    if not (FAV_LO <= seg_bp[0] <= FAV_HI):
        return None
    # oracle gate at join time
    ret5 = rtds_ret5_at(t_join)
    if np.isnan(ret5) or abs(ret5) < threshold:
        return None  # gate OFF at join: no quote this window

    # trades within window
    if tr is not None:
        tts, tpx, tsz = tr
        a = int(np.searchsorted(tts, t_join, "left"))
        b = int(np.searchsorted(tts, t_stop, "left"))
        tts, tpx, tsz = tts[a:b], tpx[a:b], tsz[a:b]
    else:
        tts = np.array([], np.int64); tpx = tsz = np.array([])

    out = {}
    for model in ("fifo", "prop"):
        level = seg_bp[0]
        q_ahead, _ = resolve_size(bts, bsz, lo)
        if not np.isfinite(q_ahead):
            q_ahead = 1e9 if model == "fifo" else 500.0
        our_sh_target = ORDER_USD / max(level, 0.01)
        filled, cost, requotes, fill_ts = 0.0, 0.0, 0, None
        ki = 0
        gate_active = True  # oracle gate checked at join (already passed)
        for m in range(len(tts)):
            # advance book to trade time; requote if level changed
            while ki + 1 < len(seg_ts) and seg_ts[ki + 1] <= tts[m]:
                ki += 1
                if np.isfinite(seg_bp[ki]) and abs(seg_bp[ki] - level) > 1e-9:
                    new_lv = seg_bp[ki]
                    if not (FAV_LO <= new_lv <= FAV_HI):
                        level = np.nan
                        gate_active = False
                        continue
                    # re-check oracle gate at requote time
                    ret5_req = rtds_ret5_at(seg_ts[ki])
                    if np.isnan(ret5_req) or abs(ret5_req) < threshold:
                        level = np.nan
                        gate_active = False
                        continue
                    gate_active = True
                    level = new_lv
                    idx_global = lo + ki
                    q_ahead, _ = resolve_size(bts, bsz, idx_global)
                    if not np.isfinite(q_ahead):
                        q_ahead = 1e9 if model == "fifo" else 500.0
                    our_sh_target = (ORDER_USD - cost) / max(level, 0.01)
                    requotes += 1
            if not gate_active or not np.isfinite(level) or filled >= our_sh_target - 1e-9:
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


# ── load arm-B baseline from prior run ──────────────────────────────────────
bt_path = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_maker_queue_bt.parquet"
B_prior = pd.read_parquet(bt_path, columns=["slug",
    "B_fifo_Up_pnl", "B_fifo_Down_pnl", "B_prop_Up_pnl", "B_prop_Down_pnl",
    "B_fifo_Up_cost", "B_fifo_Down_cost", "B_prop_Up_cost", "B_prop_Down_cost"])
B_prior = B_prior.set_index("slug")
print(f"arm-B prior loaded: {len(B_prior)} rows  t={time.time()-t0:.0f}s", flush=True)

# ── main simulation loop ─────────────────────────────────────────────────────
rows = []
for n, slug in enumerate(slugs):
    ss = int(slug.rsplit("-", 1)[1])
    wu = win_up[slug]
    rec = dict(slug=slug, ss=ss)
    # arm-B baseline for this window
    if slug in B_prior.index:
        b_row = B_prior.loc[slug]
        rec["B_fifo_pnl"] = float(b_row["B_fifo_Up_pnl"] + b_row["B_fifo_Down_pnl"])
        rec["B_prop_pnl"] = float(b_row["B_prop_Up_pnl"] + b_row["B_prop_Down_pnl"])
    else:
        rec["B_fifo_pnl"] = 0.0
        rec["B_prop_pnl"] = 0.0

    for thr in THRESHOLDS:
        key = int(thr)
        # gate checks favorite band AND oracle at join; returns None if gated out
        r_up = sim_token_gated(slug, "Up", ss, thr)
        r_dn = sim_token_gated(slug, "Down", ss, thr)
        for model in ("fifo", "prop"):
            total_pnl = 0.0
            total_cost = 0.0
            total_sh = 0.0
            for side, r in (("Up", r_up), ("Down", r_dn)):
                fsh, cost, rq, fts = (r[model] if r else (0.0, 0.0, 0, None))
                won = (side == "Up") == wu
                if fsh > 0:
                    ev = cost / fsh
                    if won:
                        pnl = fsh * (1 - ev) * (1 - FEE * ev)
                    else:
                        pnl = -cost
                    pnl += fsh * REBATE_SH
                else:
                    pnl = 0.0
                total_pnl += pnl
                total_cost += cost
                total_sh += fsh
            rec[f"E{key}_{model}_pnl"] = total_pnl
            rec[f"E{key}_{model}_cost"] = total_cost
            rec[f"E{key}_{model}_sh"] = total_sh
    rows.append(rec)
    if n % 200 == 0:
        print(f"  {n}/{len(slugs)} t={time.time()-t0:.0f}s", flush=True)

R = pd.DataFrame(rows)
out_path = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_maker_oraclegate_bt.parquet"
R.to_parquet(out_path, index=False)
days = (R.ss.max() - R.ss.min()) / 86400
print(f"\nsimulated {len(R)} windows over {days:.0f} days  t={time.time()-t0:.0f}s")

# ── summary stats ────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("PRE-REGISTERED CELLS (3 thresholds × 2 fill models = 6 cells)")
print("="*70)
print(f"{'Cell':<14} {'fired%':>7} {'wins_w_fill':>11} {'$/fired':>9} {'CI95':>22} "
      f"{'total$':>8} {'vs_armB/win':>12} {'verdict':>10}")
print("-"*70)

results_for_report = []
for thr in THRESHOLDS:
    key = int(thr)
    for model in ("fifo", "prop"):
        cell = f"E{key}_{model}"
        pnl = R[f"{cell}_pnl"]
        cost = R[f"{cell}_cost"]
        fired = cost > 0
        n_fired = fired.sum()
        fill_rate = fired.mean()

        if n_fired > 5:
            lo, hi = boot(pnl[fired].values)
            mean_fired = pnl[fired].mean()
        else:
            lo = hi = mean_fired = np.nan

        total_pnl = pnl.sum()

        # paired diff vs arm B on FIRED windows
        b_col = f"B_{model}_pnl"
        if b_col in R.columns:
            # on fired windows: diff = E_pnl - B_pnl (B may be 0 if gated-out by oracle)
            paired_diff = (pnl[fired] - R.loc[fired, b_col]).mean() if n_fired > 0 else np.nan
        else:
            paired_diff = np.nan

        if np.isnan(mean_fired):
            verdict = "no data"
        elif lo > 0:
            verdict = "POS"
        elif hi < 0:
            verdict = "NEG"
        else:
            verdict = "flat"

        ci_str = f"[{lo:+.4f},{hi:+.4f}]" if not np.isnan(lo) else "[n/a]"
        print(f"{cell:<14} {fill_rate:>7.1%} {n_fired:>11d} {mean_fired:>+9.4f} "
              f"{ci_str:>22} {total_pnl:>+8.2f} {paired_diff:>+12.4f} {verdict:>10}")

        results_for_report.append(dict(cell=cell, threshold=thr, model=model,
            fired_pct=fill_rate, n_fired=int(n_fired),
            mean_pnl_fired=mean_fired, ci_lo=lo, ci_hi=hi,
            total_pnl=total_pnl, paired_vs_B=paired_diff, verdict=verdict))

# ── arm B baseline reminder ──────────────────────────────────────────────────
print("\nArm-B baseline (from prior run):")
for model in ("fifo", "prop"):
    b_col = f"B_{model}_pnl"
    if b_col in R.columns:
        b_pnl = R[b_col]
        b_fired = R[f"B_{model}_pnl"].abs() > 1e-12  # proxy: B had a fill
        # use cost from prior
        b_cost_up = f"B_{model}_Up_cost"
        b_cost_dn = f"B_{model}_Down_cost"
        if b_cost_up in B_prior.columns:
            b_cost = (B_prior[b_cost_up] + B_prior[b_cost_dn]).reindex(R.slug).fillna(0).values
            b_fired_mask = b_cost > 0
            b_pnl_arr = b_pnl.values
            if b_fired_mask.sum() > 5:
                blo, bhi = boot(b_pnl_arr[b_fired_mask])
                print(f"  B [{model}]: fired {b_fired_mask.mean():.0%}  "
                      f"$/fired {b_pnl_arr[b_fired_mask].mean():+.4f} CI[{blo:+.4f},{bhi:+.4f}]"
                      f"  total ${b_pnl.sum():+.2f}")

print(f"\nOutput: {out_path}")
print(f"Total runtime: {time.time()-t0:.0f}s")
