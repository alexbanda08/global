"""
VARIANT 2 — OSCILLATION-HARVEST (signal-gated predictive legging, 2026-06-13).

THE OPERATOR'S CORE HYPOTHESIS (never tested — see PART 2 of the campaign enumeration):
  Within ONE BTC/ETH/SOL 5m+15m window, independently lag-gate EACH side on its OWN
  causal Binance-LEAD dip. Over the full window, at each causal decision second:
    - if Binance just moved UP by >= THR bps (bar-END asof) AND the Poly UP ask is still
      cheap (book lagging) -> taker-buy a clip of UP (+85ms latency).
    - if Binance just moved DOWN by >= THR bps AND the Poly DOWN ask is still cheap
      -> taker-buy a clip of DOWN (+85ms).
  Accumulate both sides across the window. Down fills cheap on down-legs, Up fills cheap
  on up-legs IF Binance oscillates within the window. At resolution the matched
  pair = min(sh_up, sh_dn) is locked; the residual is held winner-only.

  THE QUESTION: does intra-window Binance oscillation deliver a PAIRED SUM < 1 on the
  self-assembled pair, and does that net beat the deployed +60s-sell scalp on the same
  fires? Three independent priors say no (V1 overround never <1, V2 sub-100ms revert kills
  the taker, V5 hold dominated by +60s sell) BUT every prior test acquired the 2nd leg
  PASSIVELY; this is the first to lag-gate BOTH legs independently.

=========================  PRE-REGISTRATION (written before any PnL)  =========================

SIGNAL (causal, NON-NEGOTIABLE — reused verbatim from scalp_causal_asof_oneshot_2026_06_12):
  unified_1s(coin) -> (starts, starts+1e6, close).  asof_on(ends, close, t) = bar-END asof
  (close known at decision time = LIVE). NEVER bar-START. At decision tick t:
    ret_C(t) = asof_END(t)/asof_END(t - DELTA_LOOKBACK) - 1   (DELTA_LOOKBACK = 5s, == scalp)
    dir_C    = 'Up' if ret_C>0 else 'Down';   d_bps = |ret_C| * 1e4
  Side eligible iff (dir_C==side) AND (d_bps >= THR). Each (slug,side) may fire MULTIPLE
  clips across the window (oscillation harvest), one per decision second it's eligible.

DECISION GRID (causal rolling): every 5s from slot_start+5s to slot_end-65s inclusive
  (>= +65s before end leaves room nothing; clips are HELD to resolution so the only reason
  to stop at -65s is to avoid the dead tail; documented choice). Decision time t is the tick
  itself (live rolling decision; NO ws_s offset for mid-window ticks — stated per spec PART 3 #3).

FILL: entry_fill(ts, ask0, asksz0, t + 85_000us, CLIP_STAKE, SPREAD=0.05, bid0) from
  scalp_fill_lib_2026_06_10. Top-of-book size-capped, resolve_size for artifact sizes,
  round(spread,4)>0.05 reject. CLIP_STAKE = $5 per clip. L25 native 10Hz (subsample_1hz=False),
  streamed per-slug chunk (~120 slugs), intermediates to D:/tmp_sgl. Production vwap gate
  ev<0.55 applied per clip (the cheap-leg condition; Arm PRIMARY). NO double-fire dedup within
  the same second (grid is already 5s-spaced).

SETTLE: load_resolutions (CHAINLINK) outcome for ALL gated slugs. won_side = (side=='Up')==(outcome=='Up').
  Never engine-redeem.

PnL: per (slug,side) accumulate shares & cost. matched = min(sh_up, sh_dn).
  paired pnl  = pair_locked_pnl(matched, p_w, p_l)  [winner leg vwap=p_w, loser=p_l]
  residual    = held_value(rem_up, ev_up, won_up) + held_value(rem_dn, ev_dn, won_dn)
  fee = winner-only 0.07 on the winning leg (built into pair_locked_pnl / held_value).
  paircost (the b945 pvs analog) = vwap_up + vwap_dn on slugs where BOTH sides filled.

GRID (pre-registered trial count):
  THR (cheapness/lag threshold, bps) in {2, 3, 5}   -> 3 cells
  x  3 coins x 2 tf reported separately, pooled overall, IS/OOS split.
  CLIP_STAKE fixed $5 (NOT swept). vwap gate fixed <0.55 (NOT swept). DELTA_LOOKBACK fixed 5s.
  Trial count for DSR bookkeeping: 3 (the THR sweep).

CONTROL (the V5 dominator, MUST beat it): the DEPLOYED +60s-sell scalp on the SAME fires.
  For an apples comparison, the control takes the FIRST eligible clip per side (the production
  single-fire scalp entry: first delta>=THR, ev<0.55, +5s.. anchored fire) and SELLS at +60s
  via exit_fill. We compare ARM A (oscillation-harvest, hold pair) net/slug to:
    (C1) deployed scalp = sum over fired sides of [+60s sell the FIRST clip only].
  i.e. "does PAIRING the accumulated clips and HOLDING add or SUBTRACT vs just selling
  the validated lag entries at +60s." (V5's lesson.)

FEASIBILITY COUNTER (pre-registered, reported BEFORE PnL): per coin x tf count slugs where
  (a) only Up filled, (b) only Down filled, (c) BOTH filled (the actual pair-assembly case),
  (d) neither. If (c) << 10% the variant is FEASIBILITY-DEAD (same-window up-AND-down
  oscillation that leaves both books lagging-cheap doesn't happen) -> report and stop.

SPLIT: IS Apr 22-May 20 | OOS May 21-Jun 11 (same as V2/V7). Production window from load_resolutions.

================================  DECISION RULE (pre-registered)  ================================
  EDGE-FOUND only if ALL hold on ARM A:
    (1) FEASIBILITY: % both-filled >= 10% of fired slugs, AND median achieved paircost < 1.0,
    (2) net/slug OOS CI95_lo > 0,
    (3) ex-top2 net/slug still > 0 (outlier robustness),
    (4) BEATS the deployed +60s-sell control (C1) with paired-diff CI95 excluding 0.
  Otherwise PARK and file the door CLOSED (joins V5 dominance + V2 overround + this test = 3 confirms).

  VERDICT field semantics: 'edge-found' iff (1)-(4) all pass; 'breakeven' if net CI straddles 0
  but feasibility ok; 'dead' if feasibility fails OR net SIG-NEG OR loses to control SIG.

Usage: py -3 strategy_lab/directional/_sumpair_signal_oscillation_harvest.py
"""
from __future__ import annotations
import os, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
from load import load_orderbook_l25_streaming, load_resolutions          # noqa: E402
from scalp_fill_lib_2026_06_10 import (entry_fill, exit_fill, resolve_size,  # noqa: E402
                                       held_value, boot, cell)

CANON = ROOT / "data" / "v4" / "canonical"
RES = ROOT / "strategy_lab" / "directional" / "_results"
TMP = Path(r"D:\tmp_sgl")
_TAG = "_".join(c.upper() for c in os.environ.get("OSC_COINS", "BTC,ETH,SOL").split(","))
OUTPARQ = (Path(r"D:\tmp_sgl") / f"osc_{_TAG}.parquet") if os.environ.get("OSC_COINS") \
    else (RES / "sumpair_oscillation_harvest_2026_06_13.parquet")

SPREAD = 0.05
CLIP_STAKE = 5.0
LAT_US = 85_000
DELTA_LOOKBACK_US = 5_000_000     # 5s momentum window (== scalp)
VWAP_GATE = 0.55                  # cheap-leg gate (production scalp config)
THRS = [2.0, 3.0, 5.0]           # cheapness/lag threshold in bps  (pre-registered grid)
GRID_STEP_US = 5_000_000          # decision tick every 5s
TAIL_PAD_US = 65_000_000          # stop decisions 65s before slot_end
FEE = 0.07
CHUNK = 600
COINS = os.environ.get("OSC_COINS", "BTC,ETH,SOL").split(",")
TFS = ["5m", "15m"]
IS_HI = pd.Timestamp("2026-05-21", tz="UTC").value // 1000   # us; < this = IS ; >= this = OOS


# ---- signal (verbatim reuse) -------------------------------------------------
def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    starts = df.time_period_start_us.values.astype("int64")
    return starts, starts + 1_000_000, df.price_close.values.astype(float)  # (start, end, close)


def asof_on(ts, v, t):
    """bar-END asof: value of the bar whose END <= t (causal, == live)."""
    i = np.searchsorted(ts, t, "right") - 1
    if i < 0:
        return np.nan
    return v[i]


def pair_locked_pnl(q, p_w, p_l):
    """matched-pair settlement: winning leg winner-only fee, losing leg costs its price."""
    return q * ((1 - p_w) * (1 - FEE * p_w) - p_l)


# ---- per-slug harvest --------------------------------------------------------
def harvest_slug(ends, close, rec_up, rec_dn, slot_start_us, slot_end_us, outcome, thr):
    """Run the oscillation harvest on one slug for one THR.

    rec_up/rec_dn: L25 tuples (ts, ap[N,25], asz[N,25], bp[N,25], bsz[N,25]) for the Up/Down
                   token, or None if no book. ends/close: bar-END asof arrays for the coin.
    Returns dict with per-side accumulated shares/cost + per-side FIRST-clip control fields.
    """
    won = {"Up": (outcome == "Up"), "Down": (outcome == "Down")}
    recs = {"Up": rec_up, "Down": rec_dn}
    # accumulators
    sh = {"Up": 0.0, "Down": 0.0}
    cost = {"Up": 0.0, "Down": 0.0}
    nclip = {"Up": 0, "Down": 0}
    first = {"Up": None, "Down": None}   # (fire_us, ev, shares) of the FIRST clip per side (control)

    t = slot_start_us + 5_000_000
    t_stop = slot_end_us - TAIL_PAD_US
    while t <= t_stop:
        p_now = asof_on(ends, close, t)
        p_prev = asof_on(ends, close, t - DELTA_LOOKBACK_US)
        if np.isfinite(p_now) and np.isfinite(p_prev) and p_prev > 0:
            ret = p_now / p_prev - 1.0
            d_bps = abs(ret) * 1e4
            if d_bps >= thr:
                side = "Up" if ret > 0 else "Down"
                rec = recs[side]
                if rec is not None:
                    ts, ap, asz, bp, bsz = rec
                    a0 = ap[:, 0]; s0 = asz[:, 0]; b0 = bp[:, 0]
                    ent = entry_fill(ts, a0, s0, t + LAT_US, CLIP_STAKE, SPREAD, b0)
                    if ent is not None and ent["ev"] < VWAP_GATE:
                        sh[side] += ent["shares"]
                        cost[side] += ent["shares"] * ent["ev"]
                        nclip[side] += 1
                        if first[side] is None:
                            first[side] = (t, ent["ev"], ent["shares"])
        t += GRID_STEP_US

    # vwap per side
    ev = {s: (cost[s] / sh[s]) if sh[s] > 0 else np.nan for s in ("Up", "Down")}
    matched = min(sh["Up"], sh["Down"])
    # paired settlement on matched portion
    if matched > 0:
        if won["Up"]:
            p_w, p_l = ev["Up"], ev["Down"]
        else:
            p_w, p_l = ev["Down"], ev["Up"]
        locked = pair_locked_pnl(matched, p_w, p_l)
        paircost = ev["Up"] + ev["Down"]
    else:
        locked = 0.0
        paircost = np.nan
    rem_up = sh["Up"] - matched
    rem_dn = sh["Down"] - matched
    residual = held_value(rem_up, ev["Up"], won["Up"]) + held_value(rem_dn, ev["Down"], won["Down"])
    arm_a_pnl = locked + residual
    cost_total = cost["Up"] + cost["Down"]

    # ---- CONTROL C1: deployed +60s sell on the FIRST clip of each fired side ----
    ctrl = 0.0
    ctrl_fired = 0
    for side in ("Up", "Down"):
        if first[side] is None:
            continue
        ctrl_fired += 1
        f_us, f_ev, f_sh = first[side]
        rec = recs[side]
        ts, ap, asz, bp, bsz = rec
        je = int(np.searchsorted(ts, f_us + LAT_US, "right")) - 1
        ext = min(f_us + 60_000_000, slot_end_us)
        r = exit_fill(ts, bp[:, 0], bsz[:, 0], je, ext, f_sh, f_ev, won[side])
        ctrl += r["pnl"]

    return dict(
        sh_up=sh["Up"], sh_dn=sh["Down"], nclip_up=nclip["Up"], nclip_dn=nclip["Down"],
        ev_up=ev["Up"], ev_dn=ev["Down"], matched=matched, paircost=paircost,
        locked=locked, residual=residual, arm_a_pnl=arm_a_pnl, cost_total=cost_total,
        both=(sh["Up"] > 0 and sh["Down"] > 0), only_up=(sh["Up"] > 0 and sh["Down"] == 0),
        only_dn=(sh["Down"] > 0 and sh["Up"] == 0), neither=(sh["Up"] == 0 and sh["Down"] == 0),
        ctrl=ctrl, ctrl_fired=ctrl_fired,
    )


def main():
    t0 = time.time()
    res = load_resolutions()
    res = res[res.ticker.isin([c.upper() for c in COINS]) & res.timeframe.isin(TFS)].drop_duplicates("slug")
    print(f"resolutions universe: {len(res)} slugs  "
          f"({pd.to_datetime(res.slot_start_us.min(), unit='us', utc=True).date()} .. "
          f"{pd.to_datetime(res.slot_start_us.max(), unit='us', utc=True).date()})", flush=True)

    all_rows = []
    for coin in COINS:
        c = coin.upper()
        ends, close = (lambda x: (x[1], x[2]))(unified_1s(c))
        for tf in TFS:
            d = res[(res.ticker == c) & (res.timeframe == tf)].copy()
            if not len(d):
                continue
            d = d.sort_values("slot_start_us").reset_index(drop=True)
            slugs = d.slug.tolist()
            print(f"\n=== {c} {tf}: {len(slugs)} slugs ===", flush=True)
            for i in range(0, len(slugs), CHUNK):
                chunk = d.iloc[i:i + CHUNK]
                cmin = int(chunk.slot_start_us.min()) - 2_000_000
                cmax = int(chunk.slot_end_us.max()) + 2_000_000
                books = load_orderbook_l25_streaming(
                    c.lower(), slugs=set(chunk.slug), subsample_1hz=False,
                    min_ts_us=cmin, max_ts_us=cmax)
                for _, r in chunk.iterrows():
                    rec_up = books.get((r.slug, "Up"))
                    rec_dn = books.get((r.slug, "Down"))
                    if rec_up is None and rec_dn is None:
                        continue
                    for thr in THRS:
                        h = harvest_slug(ends, close, rec_up, rec_dn,
                                         int(r.slot_start_us), int(r.slot_end_us),
                                         r.outcome, thr)
                        h.update(coin=c, tf=tf, slug=r.slug, thr=thr,
                                 outcome=r.outcome, slot_start_us=int(r.slot_start_us),
                                 oos=(int(r.slot_start_us) >= IS_HI))
                        all_rows.append(h)
                del books
                if (i // CHUNK) % 10 == 0:
                    print(f"    {c} {tf} {i+len(chunk)}/{len(slugs)}  t={time.time()-t0:.0f}s", flush=True)

    R = pd.DataFrame(all_rows)
    R.to_parquet(OUTPARQ, index=False)
    print(f"\nsaved {len(R)} rows -> {OUTPARQ}   t={time.time()-t0:.0f}s", flush=True)
    report(R)


def report(R):
    print("\n" + "=" * 90)
    print("FEASIBILITY (per THR; counts over slugs where ANY side fired):")
    for thr in THRS:
        g = R[R.thr == thr]
        fired = g[~g.neither]
        both = g.both.sum(); ou = g.only_up.sum(); od = g.only_dn.sum(); nf = g.neither.sum()
        nfired = len(fired)
        pc = g.paircost.dropna()
        print(f"  THR={thr:.0f}bp: slugs={len(g)} fired={nfired} "
              f"both={both} ({both/max(nfired,1):.1%} of fired) only_up={ou} only_dn={od} neither={nf}")
        if len(pc):
            print(f"            paircost: median={pc.median():.4f} mean={pc.mean():.4f} "
                  f"%<1.0={(pc < 1.0).mean():.1%}  (n_both={len(pc)})")

    print("\n" + "=" * 90)
    print("PnL — ARM A (oscillation-harvest, hold pair) net/slug over FIRED slugs:")
    for thr in THRS:
        g = R[(R.thr == thr) & (~R.neither)]
        for scope, gg in (("ALL", g), ("IS", g[~g.oos]), ("OOS", g[g.oos])):
            v = gg.arm_a_pnl.values
            print(f"  THR={thr:.0f}bp {scope:3s}: {cell(v)}", flush=True)
        # vs deployed control on the SAME fired slugs (paired)
        d = (g.arm_a_pnl - g.ctrl).values
        lo, hi = boot(d)
        print(f"           ARM_A vs CTRL(+60s sell) paired: n={len(d)} "
              f"mean={d.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}]")
        # ex-top2 robustness on OOS
        oos = g[g.oos].arm_a_pnl.values
        if len(oos) > 3:
            ex = np.sort(oos)[:-2]
            print(f"           OOS ex-top2: mean={ex.mean():+.4f} (n={len(ex)})")
        # control absolute
        print(f"           CTRL(+60s) net/slug: {cell(g.ctrl.values)}")

    # paired vwap sum sub-1 fraction over completed (both) pairs
    print("\n" + "=" * 90)
    print("PER-COIN x TF (THR=3, fired slugs) net/slug:")
    g3 = R[(R.thr == 3.0) & (~R.neither)]
    for (c, tf), gg in g3.groupby(["coin", "tf"]):
        print(f"  {c} {tf}: {cell(gg.arm_a_pnl.values)}  both%={gg.both.mean():.1%}")


if __name__ == "__main__":
    main()
