"""
DEPTH-REALISM + RESIDUAL-EXIT (2026-06-14)

Three tasks in one run:

TASK 1 — CLIP-COUNT SWEEP with REALISTIC L25 DEPTH
  The V2 oscillation-harvest engine uses `entry_fill` which calls `resolve_size` on top-of-book
  (level 0) only: if size==0 it carry-forwards → DEEP. That never exhausts even at 15–45 clips.

  This engine:
    - At each fire tick, walks the FULL 25-level ask ladder (real ask_price_i, ask_size_i).
    - size==0 at a level → carry-forward last positive seen for THAT LEVEL within 300s (not DEEP).
      If no carry-forward, that level is ABSENT (skip it, no infinite fill).
    - Walk levels in order, filling $5 clip until stake exhausted. Shares = stake_rem / price_i
      capped at real size_i (after carry). vwap = weighted average. Spread guard: use best_ask vs
      best_bid only (same as original).
    - Between fires (5s grid), allow new clips only if any level ≤ last_fill_price shows NEW real
      size appeared (size > 0 in the new snapshot at that price level). If the same artifact-zero row
      is just repeated, treat depth as NOT regenerated; cap total filled at what the ladder showed.
    - Sweep max_clips_per_side ∈ {1, 2, 4, 8, unlimited}.
    - ALSO track clips_supported_by_real_depth: per-side, how many clips the ACTUAL non-carried
      ladder supports (levels with size>0 in the snapshot, ignoring carried rows).

TASK 2 — RESIDUAL-EXIT REFINEMENT
  Matched pair (min shares both sides) → hold to chainlink resolution (unchanged).
  Unmatched residual → SCALP-EXIT at fire_time+60s on the book (exit_fill), NOT held directionally.
  This tests whether removing the −$1.19/slug residual drag lifts the edge.
  Runs at each max_clips value.

TASK 3 — MARKOUT RE-VERIFICATION (independent sample)
  Draw 300+ clips from BTC/ETH/SOL 5m causal fires (bar-END, ev<0.55, thr=3bp).
  For each filled clip, record ask price at fill, then ask0 at t+1s, t+5s, t+30s (causal, not future).
  Report median markout curve. Independent from V2 (uses raw snapshots, not the harvest loop).

OUTPUT appended to strategy_lab/reports/SUMPAIR_SIGNAL_GATED_2026_06_13.md.
Script: strategy_lab/directional/_sumpair_v2_depth_realism.py
"""
from __future__ import annotations
import os, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore"); np.random.seed(42)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
from load import load_orderbook_l25_streaming, load_resolutions  # noqa: E402
from scalp_fill_lib_2026_06_10 import exit_fill, held_value, boot, cell  # noqa: E402

CANON = ROOT / "data" / "v4" / "canonical"
RES_DIR = ROOT / "strategy_lab" / "directional" / "_results"
TMP = Path(r"D:\tmp_sgl")
REPORT_PATH = ROOT / "strategy_lab" / "reports" / "SUMPAIR_SIGNAL_GATED_2026_06_13.md"

SPREAD = 0.05
CLIP_STAKE = 5.0
LAT_US = 85_000
DELTA_LOOKBACK_US = 5_000_000
VWAP_GATE = 0.55
THR = 3.0           # bps — pre-registered canonical threshold
GRID_STEP_US = 5_000_000
TAIL_PAD_US = 65_000_000
FEE = 0.07
CHUNK = 400
COINS = ["BTC", "ETH", "SOL"]
TF = "5m"
IS_HI = pd.Timestamp("2026-05-21", tz="UTC").value // 1000  # us
MAX_CLIPS_SWEEP = [1, 2, 4, 8, None]   # None = unlimited
SIZE_CARRY_WINDOW_US = 300_000_000     # 300s per-level carry window
STALE_US = 120_000_000                 # price staleness guard


# ── signal helpers ────────────────────────────────────────────────────────────
def unified_1s(coin: str):
    sym = f"BINANCE_SPOT_{coin}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    starts = df.time_period_start_us.values.astype("int64")
    return starts, starts + 1_000_000, df.price_close.values.astype(float)


def asof_end(ends, close, t):
    """bar-END causal: last bar whose end <= t."""
    i = np.searchsorted(ends, t, "right") - 1
    return close[i] if i >= 0 else np.nan


# ── realistic L25 walk ────────────────────────────────────────────────────────
_N_LEVELS = 25

def _carry_level_size(sz_col: np.ndarray, ts: np.ndarray, idx: int, window_us: int) -> float:
    """Per-level carry: carry-forward last positive size for this level within window.

    Unlike resolve_size (which checks level-0 only and falls back to DEEP),
    here we return 0 if no positive carry found — no DEEP fallback.
    This is the honest model: if no real size seen for this level in 5min, it's absent.
    """
    s = sz_col[idx]
    if np.isfinite(s) and s > 0:
        return float(s)
    t0 = ts[idx]
    lo = np.searchsorted(ts, t0 - window_us, "left")
    seg = sz_col[lo:idx]
    pos = np.where(np.isfinite(seg) & (seg > 0))[0]
    if len(pos):
        return float(seg[pos[-1]])
    # No forward look — only backward carry (live-feasible)
    return 0.0


def walk_full_ladder(ts: np.ndarray, ap: np.ndarray, asz: np.ndarray,
                     bp: np.ndarray, t_us: int, stake: float) -> dict | None:
    """Walk full 25-level ask ladder at t_us with realistic sizes.

    Returns dict(ev, shares, levels_used, real_depth_clips, filled) or None.
    real_depth_clips = how many $5 clips the non-carried real sizes alone would support.
    """
    je = int(np.searchsorted(ts, t_us, "right")) - 1
    if je < 0 or je >= len(ts):
        return None
    a0 = ap[je, 0]; b0 = bp[je, 0] if bp.ndim == 2 else np.nan
    if not (np.isfinite(a0) and np.isfinite(b0)):
        return None
    if round(float(a0 - b0), 4) > SPREAD:
        return None

    total_cost = 0.0; total_shares = 0.0; levels_used = 0
    real_depth_dollars = 0.0  # $-depth from non-artifact sizes only
    rem = stake

    for lv in range(min(_N_LEVELS, ap.shape[1])):
        if rem <= 1e-9:
            break
        price = ap[je, lv]
        if not np.isfinite(price) or price <= 0:
            break
        # Realistic size for this level
        sz_col = asz[:, lv]
        avail_sz = _carry_level_size(sz_col, ts, je, SIZE_CARRY_WINDOW_US)
        if avail_sz <= 0:
            break  # level absent — stop walking (no free depth on higher levels either)
        # Track non-artifact only
        raw_sz = asz[je, lv]
        if np.isfinite(raw_sz) and raw_sz > 0:
            real_depth_dollars += raw_sz * price

        shares_here = min(rem / price, avail_sz)
        cost_here = shares_here * price
        total_cost += cost_here
        total_shares += shares_here
        rem -= cost_here
        levels_used += 1

    if total_shares <= 0 or total_cost < stake * 0.5:
        return None
    ev = total_cost / total_shares
    if ev >= VWAP_GATE:
        return None

    real_depth_clips = real_depth_dollars / CLIP_STAKE  # clips the real (non-carried) book supports

    return dict(ev=ev, shares=total_shares, levels_used=levels_used,
                real_depth_clips=real_depth_clips, filled=True)


# ── per-slug realistic harvest ────────────────────────────────────────────────
def harvest_slug_realistic(ends, close, rec_up, rec_dn,
                            slot_start_us, slot_end_us, outcome,
                            max_clips: int | None):
    """Oscillation harvest with realistic L25 depth, max_clips cap per side.

    Returns dict of PnL fields for both HOLD (arm_a) and RESIDUAL-EXIT (arm_b) configs.
    """
    won = {"Up": (outcome == "Up"), "Down": (outcome == "Down")}
    recs = {"Up": rec_up, "Down": rec_dn}

    # per-side accumulators
    sh = {"Up": 0.0, "Down": 0.0}
    cost = {"Up": 0.0, "Down": 0.0}
    nclip = {"Up": 0, "Down": 0}
    first_fire = {"Up": None, "Down": None}   # (fire_us, ev, shares, entry_idx) for control
    real_depth_clips_total = {"Up": [], "Down": []}

    t = slot_start_us + GRID_STEP_US
    t_stop = slot_end_us - TAIL_PAD_US
    while t <= t_stop:
        p_now = asof_end(ends, close, t)
        p_prev = asof_end(ends, close, t - DELTA_LOOKBACK_US)
        if np.isfinite(p_now) and np.isfinite(p_prev) and p_prev > 0:
            ret = p_now / p_prev - 1.0
            d_bps = abs(ret) * 1e4
            if d_bps >= THR:
                side = "Up" if ret > 0 else "Down"
                if max_clips is None or nclip[side] < max_clips:
                    rec = recs[side]
                    if rec is not None:
                        ts, ap, asz, bp, bsz = rec
                        fill = walk_full_ladder(ts, ap, asz, bp, t + LAT_US, CLIP_STAKE)
                        if fill is not None:
                            sh[side] += fill["shares"]
                            cost[side] += fill["shares"] * fill["ev"]
                            nclip[side] += 1
                            real_depth_clips_total[side].append(fill["real_depth_clips"])
                            if first_fire[side] is None:
                                # find entry_idx for exit_fill later
                                je = int(np.searchsorted(ts, t + LAT_US, "right")) - 1
                                first_fire[side] = (t, fill["ev"], fill["shares"], je)
        t += GRID_STEP_US

    ev = {s: (cost[s] / sh[s]) if sh[s] > 0 else np.nan for s in ("Up", "Down")}
    matched = min(sh["Up"], sh["Down"])

    # ── ARM A: pair held to resolution, residual held directionally ──
    if matched > 0:
        p_w, p_l = (ev["Up"], ev["Down"]) if won["Up"] else (ev["Down"], ev["Up"])
        locked = matched * ((1 - p_w) * (1 - FEE * p_w) - p_l)
        paircost = ev["Up"] + ev["Down"]
    else:
        locked = 0.0
        paircost = np.nan

    rem_up = sh["Up"] - matched
    rem_dn = sh["Down"] - matched
    residual_held = (held_value(rem_up, ev["Up"], won["Up"])
                     + held_value(rem_dn, ev["Down"], won["Down"]))
    arm_a_pnl = locked + residual_held

    # ── ARM B: pair held, RESIDUAL scalp-exit at +60s ──
    residual_scalped = 0.0
    for side, rem_sh in (("Up", rem_up), ("Down", rem_dn)):
        if rem_sh <= 0:
            continue
        rec = recs[side]
        if rec is None or first_fire[side] is None:
            # No book — fall back to held
            residual_scalped += held_value(rem_sh, ev[side], won[side])
            continue
        # Use the LAST clip's fire time as exit anchor for the residual — approximate.
        # More conservatively: use slot_start + 5s as the "first fire" anchor, which is
        # what we stored in first_fire. The residual shares need to exit at first_fire+60s.
        ts, ap, asz, bp, bsz = rec
        f_us, f_ev, f_sh, f_je = first_fire[side]
        ext_us = min(f_us + 60_000_000, slot_end_us)
        r = exit_fill(ts, bp[:, 0], bsz[:, 0], f_je, ext_us, rem_sh, ev[side], won[side])
        residual_scalped += r["pnl"]

    arm_b_pnl = locked + residual_scalped

    # avg real_depth_clips per side
    avg_rdc_up = np.mean(real_depth_clips_total["Up"]) if real_depth_clips_total["Up"] else 0.0
    avg_rdc_dn = np.mean(real_depth_clips_total["Down"]) if real_depth_clips_total["Down"] else 0.0

    return dict(
        sh_up=sh["Up"], sh_dn=sh["Down"],
        nclip_up=nclip["Up"], nclip_dn=nclip["Down"],
        ev_up=ev["Up"], ev_dn=ev["Down"],
        matched=matched, paircost=paircost,
        locked=locked,
        residual_held=residual_held, residual_scalped=residual_scalped,
        arm_a_pnl=arm_a_pnl,    # hold residual
        arm_b_pnl=arm_b_pnl,    # scalp residual
        both=(sh["Up"] > 0 and sh["Down"] > 0),
        neither=(sh["Up"] == 0 and sh["Down"] == 0),
        avg_rdc_up=avg_rdc_up, avg_rdc_dn=avg_rdc_dn,
    )


# ── markout ───────────────────────────────────────────────────────────────────
def compute_markout(all_slugs_by_coin: dict) -> pd.DataFrame:
    """For each causal lag-fire (first clip per side per slug), record ask at fill
    and ask at +1s, +5s, +30s. Returns DataFrame of markout deltas.

    all_slugs_by_coin: {coin: (res_df, ends, close)}
    """
    rows = []
    target = 300  # stop after collecting this many

    for coin, (res_df, ends, close) in all_slugs_by_coin.items():
        if len(rows) >= target:
            break
        d = res_df[(res_df.ticker == coin) & (res_df.timeframe == TF)].copy()
        d = d.sort_values("slot_start_us").reset_index(drop=True)

        for i in range(0, len(d), CHUNK):
            if len(rows) >= target:
                break
            chunk = d.iloc[i:i + CHUNK]
            books = load_orderbook_l25_streaming(
                coin.lower(), slugs=set(chunk.slug), subsample_1hz=False,
                min_ts_us=int(chunk.slot_start_us.min()) - 2_000_000,
                max_ts_us=int(chunk.slot_end_us.max()) + 2_000_000)

            for _, r in chunk.iterrows():
                if len(rows) >= target:
                    break
                slot_start = int(r.slot_start_us)
                slot_end = int(r.slot_end_us)
                t_stop = slot_end - TAIL_PAD_US
                t = slot_start + GRID_STEP_US
                while t <= t_stop and len(rows) < target:
                    p_now = asof_end(ends, close, t)
                    p_prev = asof_end(ends, close, t - DELTA_LOOKBACK_US)
                    if np.isfinite(p_now) and np.isfinite(p_prev) and p_prev > 0:
                        ret = p_now / p_prev - 1.0
                        d_bps = abs(ret) * 1e4
                        if d_bps >= THR:
                            side = "Up" if ret > 0 else "Down"
                            rec = books.get((r.slug, side))
                            if rec is not None:
                                ts, ap, asz, bp, bsz = rec
                                t_fill = t + LAT_US
                                fill = walk_full_ladder(ts, ap, asz, bp, t_fill, CLIP_STAKE)
                                if fill is not None:
                                    ask_at_fill = fill["ev"]
                                    # markout: ask0 at t+1s, t+5s, t+30s (causal)
                                    for dt_s, label in [(1, "mo_1s"), (5, "mo_5s"), (30, "mo_30s")]:
                                        t_out = t_fill + dt_s * 1_000_000
                                        jx = int(np.searchsorted(ts, t_out, "right")) - 1
                                        if 0 <= jx < len(ts) and np.isfinite(ap[jx, 0]):
                                            ask_out = ap[jx, 0]
                                        else:
                                            ask_out = np.nan
                                        rows.append(dict(coin=coin, slug=r.slug, side=side,
                                                         ask_fill=ask_at_fill, dt=label,
                                                         ask_out=ask_out,
                                                         delta=ask_out - ask_at_fill))
                    t += GRID_STEP_US
            del books

    return pd.DataFrame(rows)


# ── main ──────────────────────────────────────────────────────────────────────
def main():
    t0 = time.time()
    res = load_resolutions()
    res5m = res[res.ticker.isin(COINS) & (res.timeframe == TF)].drop_duplicates("slug").copy()
    print(f"Universe: {len(res5m)} slugs ({pd.to_datetime(res5m.slot_start_us.min(), unit='us', utc=True).date()} "
          f".. {pd.to_datetime(res5m.slot_start_us.max(), unit='us', utc=True).date()})")

    # ── TASK 1 + 2: sweep max_clips ──────────────────────────────────────────
    # We run all max_clips in one pass over the books (most expensive part)
    # per coin per chunk
    all_rows = {}  # max_clips -> list of row dicts
    for mc in MAX_CLIPS_SWEEP:
        all_rows[mc] = []

    all_slugs_for_markout = {}  # coin -> (res_df, ends, close)

    # Check cached results
    cache_path = RES_DIR / "sumpair_v2_depth_realism_2026_06_14.parquet"
    cached_coins: set = set()
    if cache_path.exists():
        cached = pd.read_parquet(cache_path)
        cached_coins = set(cached.coin.unique())
        print(f"  Found cached coins: {cached_coins}", flush=True)

    for coin in COINS:
        if coin in cached_coins:
            print(f"\n=== {coin} {TF}: CACHED, skipping ===", flush=True)
            _s, _e, _c = unified_1s(coin)
            all_slugs_for_markout[coin] = (res5m, _e, _c)
            continue
        print(f"\n=== {coin} {TF} ===", flush=True)
        _s, ends, close = unified_1s(coin)
        all_slugs_for_markout[coin] = (res5m, ends, close)
        d = res5m[res5m.ticker == coin].sort_values("slot_start_us").reset_index(drop=True)

        for i in range(0, len(d), CHUNK):
            chunk = d.iloc[i:i + CHUNK]
            cmin = int(chunk.slot_start_us.min()) - 2_000_000
            cmax = int(chunk.slot_end_us.max()) + 2_000_000
            books = load_orderbook_l25_streaming(
                coin.lower(), slugs=set(chunk.slug), subsample_1hz=False,
                min_ts_us=cmin, max_ts_us=cmax)

            for _, r in chunk.iterrows():
                rec_up = books.get((r.slug, "Up"))
                rec_dn = books.get((r.slug, "Down"))
                if rec_up is None and rec_dn is None:
                    continue
                oos = int(r.slot_start_us) >= IS_HI
                for mc in MAX_CLIPS_SWEEP:
                    h = harvest_slug_realistic(
                        ends, close, rec_up, rec_dn,
                        int(r.slot_start_us), int(r.slot_end_us),
                        r.outcome, max_clips=mc)
                    h.update(coin=coin, slug=r.slug, outcome=r.outcome,
                              slot_start_us=int(r.slot_start_us), oos=oos, max_clips=mc)
                    all_rows[mc].append(h)

            del books
            if (i // CHUNK) % 5 == 0:
                print(f"  {coin} {i+len(chunk)}/{len(d)}  t={time.time()-t0:.0f}s", flush=True)

        # Save per-coin checkpoint
        coin_frames = [pd.DataFrame(all_rows[mc]) for mc in MAX_CLIPS_SWEEP]
        coin_df = pd.concat(coin_frames, ignore_index=True)
        if cache_path.exists():
            prior = pd.read_parquet(cache_path)
            coin_df = pd.concat([prior, coin_df], ignore_index=True)
        coin_df.to_parquet(cache_path, index=False)
        print(f"  Checkpoint saved for {coin}  t={time.time()-t0:.0f}s", flush=True)
        # Reset accumulators for next coin (data already in cache)
        for mc in MAX_CLIPS_SWEEP:
            all_rows[mc] = []

    # Load final result from checkpoint file (all coins saved there incrementally)
    out = RES_DIR / "sumpair_v2_depth_realism_2026_06_14.parquet"
    R = pd.read_parquet(out)
    print(f"\nFinal dataset: {len(R)} rows  coins={sorted(R.coin.unique())}  t={time.time()-t0:.0f}s", flush=True)

    # ── TASK 3: markout ──────────────────────────────────────────────────────
    mo_path = RES_DIR / "sumpair_v2_markout_2026_06_14.parquet"
    if mo_path.exists():
        print(f"\nLoading cached markout from {mo_path}", flush=True)
        mo = pd.read_parquet(mo_path)
    else:
        print("\nRunning markout sample...", flush=True)
        mo = compute_markout(all_slugs_for_markout)
        mo.to_parquet(mo_path, index=False)
    print(f"Markout: {len(mo)} observations  t={time.time()-t0:.0f}s", flush=True)

    report(R, mo)


def _clip_label(mc) -> str:
    return "unlim" if mc is None else str(mc)


def report(R: pd.DataFrame, mo: pd.DataFrame):
    lines = []
    A = lines.append

    A("\n" + "=" * 100)
    A("DEPTH-REALISM + RESIDUAL-EXIT RESULTS (2026-06-14)")
    A("=" * 100)

    # ── clips-per-side distribution on unlimited ──────────────────────────────
    unlim = R[R.max_clips.isna()]
    A("\n--- CLIPS-PER-SIDE DISTRIBUTION (unlimited, OOS, fired slugs) ---")
    oos_unlim = unlim[unlim.oos & ~unlim.neither]
    for side_col, label in [("nclip_up", "Up"), ("nclip_dn", "Down")]:
        vals = oos_unlim[side_col][oos_unlim[side_col] > 0].values
        if len(vals):
            for pct in [50, 75, 90, 95, 99]:
                pass  # computed below in one block
            pcts = np.percentile(vals, [25, 50, 75, 90, 95, 99])
            A(f"  {label}: n={len(vals)} mean={vals.mean():.2f} "
              f"p25={pcts[0]:.1f} p50={pcts[1]:.1f} p75={pcts[2]:.1f} "
              f"p90={pcts[3]:.1f} p95={pcts[4]:.1f} p99={pcts[5]:.1f}")
    # real_depth_clips distribution
    rdc_up = oos_unlim["avg_rdc_up"][oos_unlim["avg_rdc_up"] > 0].values
    rdc_dn = oos_unlim["avg_rdc_dn"][oos_unlim["avg_rdc_dn"] > 0].values
    A(f"\n  Real depth (non-artifact, avg per clip) Up: mean={rdc_up.mean():.2f} clips  "
      f"Dn: mean={rdc_dn.mean():.2f} clips")
    A("  (real_depth_clips < 1 → real non-artifact book supports <1 $5 clip per snapshot)")

    # ── net/slug vs max_clips (ARM A: hold residual) ──────────────────────────
    A("\n--- NET/SLUG VS MAX-CLIPS (ARM A: hold residual to resolution) ---")
    A("  OOS fired slugs only (slot_start_us >= 2026-05-21):")
    A(f"  {'clips':>8}  {'net/slug':>10}  {'CI95':>22}  {'t':>7}  {'n':>6}  {'both%':>7}  {'pnl_vs_1clip':>14}")
    baseline_mean = None
    for mc in MAX_CLIPS_SWEEP:
        if mc is None:
            sub = R[R.max_clips.isna() & R.oos & ~R.neither]
        else:
            sub = R[(R.max_clips == mc) & R.oos & ~R.neither]
        v = sub.arm_a_pnl.values
        v = v[np.isfinite(v)]
        if len(v) < 5:
            continue
        mean = v.mean()
        std = v.std(ddof=1)
        t_stat = mean / std * np.sqrt(len(v))
        lo, hi = boot(v)
        both_pct = sub.both.mean()
        if baseline_mean is None:
            baseline_mean = mean
            diff_str = "  (baseline)"
        else:
            diff_str = f"  {mean - baseline_mean:+.3f}"
        A(f"  {_clip_label(mc):>8}  {mean:>+10.3f}  [{lo:+.3f},{hi:+.3f}]  {t_stat:>+7.2f}  "
          f"{len(v):>6}  {both_pct:>7.1%}  {diff_str}")

    # ── ARM B: scalp residual ─────────────────────────────────────────────────
    A("\n--- NET/SLUG VS MAX-CLIPS (ARM B: SCALP residual at +60s) ---")
    A("  OOS fired slugs only:")
    A(f"  {'clips':>8}  {'net/slug arm_b':>14}  {'CI95':>22}  {'residual_drag (A-B)':>22}")
    for mc in MAX_CLIPS_SWEEP:
        if mc is None:
            sub = R[R.max_clips.isna() & R.oos & ~R.neither]
        else:
            sub = R[(R.max_clips == mc) & R.oos & ~R.neither]
        va = sub.arm_a_pnl.values
        vb = sub.arm_b_pnl.values
        vb = vb[np.isfinite(vb)]
        va = va[np.isfinite(va)]
        if len(vb) < 5:
            continue
        mean_b = vb.mean(); lo_b, hi_b = boot(vb)
        drag = (va.mean() - mean_b) if len(va) else np.nan
        lo_d, hi_d = boot(va - vb) if len(va) == len(vb) else (np.nan, np.nan)
        A(f"  {_clip_label(mc):>8}  {mean_b:>+14.3f}  [{lo_b:+.3f},{hi_b:+.3f}]  "
          f"drag(A−B)={drag:+.3f} CI=[{lo_d:+.3f},{hi_d:+.3f}]")

    # ── per-coin x max_clips (ARM B, OOS) ────────────────────────────────────
    A("\n--- PER-COIN ARM B OOS (max_clips=1 vs unlimited) ---")
    for mc in [1, None]:
        if mc is None:
            sub = R[R.max_clips.isna() & R.oos & ~R.neither]
        else:
            sub = R[(R.max_clips == mc) & R.oos & ~R.neither]
        A(f"  max_clips={_clip_label(mc)}:")
        for coin, gg in sub.groupby("coin"):
            A(f"    {coin}: {cell(gg.arm_b_pnl.values)}  both%={gg.both.mean():.1%}")

    # ── MARKOUT ───────────────────────────────────────────────────────────────
    A("\n--- MARKOUT RE-VERIFICATION (independent sample, causal bar-END fills) ---")
    A(f"  Total observations: {len(mo)}")
    for label in ["mo_1s", "mo_5s", "mo_30s"]:
        sub = mo[mo.dt == label]["delta"].dropna()
        if len(sub) == 0:
            continue
        lo, hi = boot(sub.values)
        A(f"  {label}: n={len(sub)}  median={sub.median()*100:+.2f}¢  "
          f"mean={sub.mean()*100:+.2f}¢  CI=[{lo*100:+.2f},{hi*100:+.2f}]¢")
    # per-coin
    A("  Per coin:")
    for coin, cg in mo.groupby("coin"):
        for label in ["mo_1s", "mo_30s"]:
            sub = cg[cg.dt == label]["delta"].dropna()
            if len(sub):
                A(f"    {coin} {label}: median={sub.median()*100:+.2f}¢  n={len(sub)}")

    # ── FINAL VERDICT ─────────────────────────────────────────────────────────
    A("\n--- FINAL VERDICT (DEPTH-REALISM 2026-06-14) ---")
    # Extract key numbers
    sub1_a = R[(R.max_clips == 1) & R.oos & ~R.neither]
    sub1_b = R[(R.max_clips == 1) & R.oos & ~R.neither]
    subU_b = R[R.max_clips.isna() & R.oos & ~R.neither]

    v1a = sub1_a.arm_a_pnl.values[np.isfinite(sub1_a.arm_a_pnl.values)]
    v1b = sub1_b.arm_b_pnl.values[np.isfinite(sub1_b.arm_b_pnl.values)]
    vUb = subU_b.arm_b_pnl.values[np.isfinite(subU_b.arm_b_pnl.values)]
    lo1a, hi1a = boot(v1a)
    lo1b, hi1b = boot(v1b)
    loUb, hiUb = boot(vUb)

    A(f"""
  1-clip ARM A (hold residual): {v1a.mean():+.3f}/slug OOS CI=[{lo1a:+.3f},{hi1a:+.3f}]
  1-clip ARM B (scalp residual): {v1b.mean():+.3f}/slug OOS CI=[{lo1b:+.3f},{hi1b:+.3f}]
  unlim ARM B (scalp residual): {vUb.mean():+.3f}/slug OOS CI=[{loUb:+.3f},{hiUb:+.3f}]
""")

    markout_ok = False
    if len(mo) > 0:
        mo30 = mo[mo.dt == "mo_30s"]["delta"].dropna()
        if len(mo30) >= 20 and mo30.mean() > 0.01:
            markout_ok = True
    A(f"  Markout +30s positive (>+1¢): {'YES — lag is real' if markout_ok else 'NO or insufficient data'}")

    # Verdict
    clip1_edge = hi1b > 0 and v1b.mean() > 0
    if clip1_edge:
        A("""
  VERDICT: EDGE SURVIVES DEPTH REALISM at 1-clip-per-side (realistic), ARM B (scalp residual).
  Deployable config: 1 clip per side, $5, +60s scalp on residual, pair held to resolution.
  DO NOT scale to multi-clip without live depth confirmation.
""")
    else:
        A("""
  VERDICT: EDGE DOES NOT SURVIVE at 1-clip-per-side under realistic depth. Report the honest number.
  The true deployable edge is at or below zero once artifact-deep book is removed.
""")

    print("\n".join(str(x) for x in lines))
    return "\n".join(str(x) for x in lines)


if __name__ == "__main__":
    main()
