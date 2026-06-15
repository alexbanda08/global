"""
SUM-PAIR VARIANT 3 — PREDICTIVE-WINNER LEAN + OPTIONAL HEDGE (Luoye sequential-legging, CAUSAL).
Pre-registered 2026-06-13.  (strategy_lab/directional/_sumpair_signal_predictive_lean_hedge.py)

THE IDEA UNDER TEST (operator's, the genuinely-untested gap):
  Use the *validated* Binance->Polymarket LAG signal (|ret_C|*1e4 >= 3, CAUSAL bar-END asof on
  klines_1s) to buy the side Binance favors to WIN, cheap, BEFORE the Poly book reprices.  Then:
    - HOLD that lead-gated leg to chainlink resolution; AND
    - WITHIN K seconds, if the OPPOSITE side becomes lockable (blended pair sum <= target),
      taker-complete the pair (hedge) and hold both to resolution;
    - else carry the single leg (held to resolution = the deployed-scalp-minus-the-+60s-sell case).
  Question: does the LAG (an entry-PRICE edge, NOT direction prediction — side-pick AUC ~0.5)
  give a price advantage that SURVIVES to resolution, and does the optional hedge ADD value over
  just running the deployed +60s scalp on the same fires?

WHY THIS IS NEW (vs the 12 dead pairing variants):
  - V4 standalone pair-completion: leg-1 was an UN-GATED PRICE dip (adverse selection / buys the
    loser). HERE leg-1 is the BINANCE-LEAD signal-gated leg (the repo's one validated edge).
  - V5 pairlock: leg-1 came from a precomputed SINGLE-DIRECTION fire file; HERE we recompute the
    lead-gated leg causally per window across all 3 coins x 2 tfs (BTC/ETH/SOL, not BTC-15m only).
  - The hedge here is CONDITIONAL on sum<target (a real lockable pair), not unconditional.

CAUSALITY (NON-NEGOTIABLE — repo #1 bug class; reuse scalp_causal_asof_oneshot_2026_06_12.py defs):
  1. Signal = CAUSAL bar-END asof on klines_1s ONLY. ret_C(t)=close_end(t)/close_end(t-DELTA)-1,
     where end-asof picks the 1s bar whose END (start+1e6) <= t. NEVER bar-START (look-ahead).
  2. Lead = dir of ret_C; eligible iff |ret_C|*1e4 >= DELTA_BPS(=3). Fire at the FIRST eligible
     decision tick on a causal grid inside the window (every 5s). Signal uses data <= decision time.
  3. FILL at decision + 85ms latency (measured live latency). entry_fill from scalp_fill_lib.
  4. HEDGE leg: scan opposite L25 ask AFTER lead fill; only fill at a snapshot >= detect+85ms and
     only if blended pair sum (ev_lead + ask_opp) <= target.  (same +85ms latency discipline.)
  5. SETTLE from CHAINLINK (load_resolutions outcome) for ALL gated slugs. Never engine-redeem.
  6. FEE = winner-only 0.07*p*(1-p) on the winning leg, $0 loser, fee-free redeem (held_value /
     pair_locked_pnl from scalp_fill_lib_2026_06_10).

CONTROL (the V5 dominator we MUST beat): same lead-gated fires, deployed scalp exit = +60s pure
  time-sell of the lead leg via exit_fill (TP off, stop off per project_scalp_exit_config).

============================ PRE-REGISTERED GRID + DECISION (declared BEFORE compute) ============
UNIVERSE: BTC/ETH/SOL x {5m,15m}, production window via load_resolutions (Apr 24 -> Jun 11).
  IS  = slot_start < 2026-05-21 00:00 UTC   |   OOS = slot_start >= 2026-05-21 00:00 UTC.
  15m: FULL universe (4366/coin). 5m: deterministic stride sample (every 3rd chronological slug,
       ~4200/coin) to bound L25 runtime while preserving IS+OOS chronological coverage.

DECISION GRID inside each window: t in [ss+5s, slot_end-65s] step 5s (causal rolling decision).
  First eligible tick per window fires the lead leg.  (offset choice stated in run header.)

ARMS (pre-declared trial count = these cells; counts toward DSR):
  Lead entry sub-gate: (i) delta>=3 only ; (ii) delta>=3 AND entry_vwap<0.55 (production scalp cfg).
  For each sub-gate, report:
    A_HOLD       : lead leg held to resolution, NO hedge                     [pure single-leg lean]
    A_HEDGE(tgt) : lead leg + conditional hedge, target in {0.99,0.97,0.95}  [lean + pair-hedge]
    CONTROL      : lead leg, deployed +60s time-sell (the V5 dominator)      [must be beaten]
  => 2 sub-gates x (1 hold + 3 hedge-targets + 1 control) = 10 reported cells. K(hedge window)=120s.

PRE-REGISTERED DECISION RULE (write before computing PnL):
  EDGE-FOUND only if, on OOS, the BEST lean/hedge cell satisfies ALL of:
    (1) net $/slug bootstrap CI95_lo > 0,
    (2) it BEATS CONTROL (+60s scalp) with paired-diff CI95 excluding 0  (V5's lesson: hold/hedge
        must beat sell, not merely be positive),
    (3) paired sum<1 is REAL among completed hedges (median achieved pair cost < 1.0),
    (4) lookahead controlled (signal bar-END asof + 85ms fill confirmed; we ALSO run a leaky
        bar-START arm to quantify the bias — if causal collapses vs leaky, that is the proof).
  ELSE -> PARK, door CLOSED (V5 dominance + V2 overround + this = independent confirmations).

OUTPUT: strategy_lab/directional/_results/sumpair_predictive_lean_hedge_2026_06_13.parquet
        (per-slug fire records: arm, ev, hedge state, pnls, paircost, IS/OOS, causal vs leaky).
"""
from __future__ import annotations
import os, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
np.random.seed(0)

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
from load import load_resolutions, load_orderbook_l25_streaming   # noqa: E402
from scalp_fill_lib_2026_06_10 import (                            # noqa: E402
    entry_fill, exit_fill, resolve_size, held_value, boot, cell)

CANON = ROOT / "data" / "v4" / "canonical"
RES = ROOT / "strategy_lab" / "directional" / "_results"
OUT_PARQUET = RES / "sumpair_predictive_lean_hedge_2026_06_13.parquet"

# ---- locked constants ----
LAT_US = 85_000               # measured live latency
STAKE = 25.0
SPREAD = 0.05                 # entry spread reject (round-4 guarded in entry_fill)
DELTA_BPS = 3.0              # validated lag gate |ret|*1e4 >= 3
GRID_STEP_US = 5_000_000      # 5s causal decision grid
HEDGE_WINDOW_US = 120_000_000  # K = 120s to complete the hedge after lead fill
HEDGE_TARGETS = [0.99, 0.97, 0.95]
FEE = 0.07
WIN_S = {"5m": 300, "15m": 900}
SIG_DELTA_S = 5              # ret window = 5s (matches the deployed +5s scalp signal horizon)

IS_OOS_CUT_US = pd.Timestamp("2026-05-21", tz="UTC").value // 1000  # slot_start_us threshold
COINS = os.environ.get("V3_COINS", "BTC,ETH,SOL").split(",")
TFS = ["5m", "15m"]
STRIDE_5M = int(os.environ.get("V3_STRIDE_5M", "3"))   # 5m sub-sample stride
L25_CHUNK = int(os.environ.get("V3_CHUNK", "400"))     # slugs per L25 stream call


# ---------------------------------------------------------------- signal (causal bar-END) -------
def unified_1s(coin: str):
    """Return (starts, ends, close) for klines_1s; end = start+1e6 (bar CLOSE knowable time)."""
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    starts = df.time_period_start_us.values.astype("int64")
    return starts, starts + 1_000_000, df.price_close.values.astype(float)


def asof_on(ts: np.ndarray, v: np.ndarray, t: int):
    """Scalar asof: value of the series whose key <= t."""
    i = int(np.searchsorted(ts, t, "right")) - 1
    if i < 0:
        return np.nan
    return v[i]


def first_lead_fire(ends, starts, close, ss_us, end_grid_us, delta_us, leaky=False):
    """Walk the causal 5s grid; return (t_decision_us, ret, lead) at the FIRST eligible tick
    (|ret|*1e4 >= DELTA_BPS), else (None, nan, None).

    causal: ret_C = close_end(t)/close_end(t-delta) - 1   (bar-END asof == live)
    leaky : ret_L = close_start(t)/close_start(t-delta) - 1 (bar-START asof == prior drivers; LOOK-AHEAD)
    """
    keys = ends if not leaky else starts
    t = ss_us + 5_000_000
    while t <= end_grid_us:
        a = asof_on(keys, close, t)
        b = asof_on(keys, close, t - delta_us)
        if np.isfinite(a) and np.isfinite(b) and b != 0.0:
            ret = a / b - 1.0
            if abs(ret) * 1e4 >= DELTA_BPS:
                return t, ret, ("Up" if ret > 0 else "Down")
        t += GRID_STEP_US
    return None, np.nan, None


# ---------------------------------------------------------------- hedge leg --------------------
def hedge_fill(rec_opp, t_start_us, stop_us, ev_lead, shares_lead, target):
    """Scan opposite L25 top-of-book ask from t_start_us..stop_us; complete the pair when blended
    sum (ev_lead + ask_opp) <= target. React with +85ms latency; re-check at the latency snapshot.
    Multi-clip until shares_lead matched or window/stake exhausted. Returns dict.

    rec_opp = (ts, ap[N,25], asz[N,25], bp[N,25], bsz[N,25]) for the OPPOSITE token.
    """
    if rec_opp is None:
        return dict(q=0.0, cost=0.0, paircost=np.nan, completed=False)
    ts, ap, asz, bp, bsz = rec_opp
    a0 = ap[:, 0]
    sz0 = asz[:, 0]
    p_star = target - ev_lead          # max acceptable opposite ask
    if p_star <= 0.005:
        return dict(q=0.0, cost=0.0, paircost=np.nan, completed=False)
    i = int(np.searchsorted(ts, t_start_us, "left"))
    n = len(ts)
    q = 0.0
    cost = 0.0
    budget = STAKE                       # cap hedge outlay at one leg's stake (symmetric to lead)
    while i < n and ts[i] <= stop_us and q < shares_lead - 1e-9:
        px = a0[i]
        if np.isfinite(px) and 0.0 < px <= p_star:
            # +85ms latency: fill at the asof snapshot then, only if STILL <= p_star
            j = int(np.searchsorted(ts, ts[i] + LAT_US, "right")) - 1
            j = max(j, i)
            pxj = a0[j]
            if np.isfinite(pxj) and 0.0 < pxj <= p_star:
                depth, _c = resolve_size(ts, sz0, j)
                need = shares_lead - q
                afford = max(budget - cost, 0.0) / pxj
                fill = min(need, depth, afford)
                if fill > 1e-9:
                    q += fill
                    cost += fill * pxj
                i = j
        i += 1
    paircost = (ev_lead + cost / q) if q > 0 else np.nan
    return dict(q=q, cost=cost, paircost=paircost, completed=bool(q >= shares_lead - 1e-9))


def pair_locked_pnl(q, p_w, p_l):
    """matched-pair settlement: winning leg winner-only fee, losing leg costs its price."""
    return q * ((1 - p_w) * (1 - FEE * p_w) - p_l)


# ---------------------------------------------------------------- universe ---------------------
def build_universe():
    r = load_resolutions(assets=COINS, timeframes=TFS, source="rtds").drop_duplicates("slug")
    r = r[r.outcome.isin(["Up", "Down"])].copy()
    frames = []
    for (coin, tf), g in r.groupby(["ticker", "timeframe"]):
        g = g.sort_values("slot_start_us").reset_index(drop=True)
        if tf == "5m" and STRIDE_5M > 1:
            g = g.iloc[::STRIDE_5M].reset_index(drop=True)
        frames.append(g)
    u = pd.concat(frames, ignore_index=True)
    u["seg"] = np.where(u.slot_start_us < IS_OOS_CUT_US, "IS", "OOS")
    return u


# ---------------------------------------------------------------- main -------------------------
def main():
    t0 = time.time()
    print("=" * 100)
    print("VARIANT 3 — PREDICTIVE-WINNER LEAN + HEDGE (causal). PRE-REGISTERED.")
    print(f"  coins={COINS} tfs={TFS} delta_bps={DELTA_BPS} grid_step=5s K_hedge=120s")
    print(f"  lead OFFSET: first eligible tick on [ss+5s, slot_end-65s] step 5s "
          f"(rolling live decision; decision time IS the tick, no ws_s offset on mid-window ticks)")
    print(f"  fill = decision+85ms ; settle=chainlink ; fee=winner-only 0.07 ; control=+60s sell")
    print(f"  5m stride={STRIDE_5M} (sub-sample) ; 15m FULL ; L25 chunk={L25_CHUNK} slugs ; 10Hz")
    print("=" * 100, flush=True)

    U = build_universe()
    print(f"universe rows: {len(U)}  "
          f"({U.groupby(['ticker','timeframe','seg']).size().to_dict()})", flush=True)

    recs = []
    for coin in COINS:
        starts, ends, close = unified_1s(coin)
        print(f"\n--- {coin}: klines_1s loaded ({len(close)} bars)  t={time.time()-t0:.0f}s ---",
              flush=True)
        for tf in TFS:
            sub = U[(U.ticker == coin) & (U.timeframe == tf)].sort_values("slot_start_us")
            sub = sub.reset_index(drop=True)
            win_us = WIN_S[tf] * 1_000_000
            delta_us = SIG_DELTA_S * 1_000_000
            # precompute lead fire (causal + leaky) per slug from klines (cheap, no L25)
            fires = []
            for _, row in sub.iterrows():
                ss = int(row.slot_start_us)
                end_grid = ss + win_us - 65_000_000   # last decision tick (need >=65s to settle)
                tC, retC, leadC = first_lead_fire(ends, starts, close, ss, end_grid, delta_us,
                                                  leaky=False)
                tL, retL, leadL = first_lead_fire(ends, starts, close, ss, end_grid, delta_us,
                                                  leaky=True)
                if tC is None and tL is None:
                    continue
                fires.append(dict(slug=row.slug, ss=ss, slot_end=int(row.slot_end_us),
                                  outcome=row.outcome, seg=row.seg,
                                  tC=tC, retC=retC, leadC=leadC,
                                  tL=tL, retL=retL, leadL=leadL))
            fdf = pd.DataFrame(fires)
            n_any = len(fdf)
            n_C = int(fdf.tC.notna().sum()) if n_any else 0
            print(f"  {coin} {tf}: {len(sub)} slugs scanned -> {n_any} have a lead fire "
                  f"(causal={n_C})  t={time.time()-t0:.0f}s", flush=True)
            if n_any == 0:
                continue

            # stream L25 in chronological chunks, time-bounded
            fdf = fdf.sort_values("ss").reset_index(drop=True)
            slugs_order = fdf.slug.tolist()
            for ci in range(0, len(slugs_order), L25_CHUNK):
                chunk_slugs = slugs_order[ci:ci + L25_CHUNK]
                cset = set(chunk_slugs)
                csub = fdf[fdf.slug.isin(cset)]
                lo = int(csub.ss.min()) - 3 * 3600 * 1_000_000   # books begin ~hrs before slot
                hi = int(csub.slot_end.max()) + 130 * 1_000_000
                books = load_orderbook_l25_streaming(coin.lower(), slugs=cset,
                                                     subsample_1hz=False,
                                                     min_ts_us=lo, max_ts_us=hi)
                for _, f in csub.iterrows():
                    _process_fire(f, books, coin, tf, recs)
                del books
            print(f"  {coin} {tf}: processed  t={time.time()-t0:.0f}s", flush=True)

    A = pd.DataFrame(recs)
    A.to_parquet(OUT_PARQUET, index=False)
    print(f"\nwrote {len(A)} fire records -> {OUT_PARQUET}  t={time.time()-t0:.0f}s", flush=True)
    _report(A)
    print(f"\ndone t={time.time()-t0:.0f}s")


def _process_fire(f, books, coin, tf, recs):
    """Compute lead-leg fill + control + hedge cells for ONE window, for both causal & leaky arms."""
    slot_end = int(f.slot_end)
    for arm_kind in ("causal", "leaky"):
        if arm_kind == "causal":
            t_dec, ret, lead = f.tC, f.retC, f.leadC
        else:
            t_dec, ret, lead = f.tL, f.retL, f.leadL
        if t_dec is None or not np.isfinite(ret):
            continue
        rec_lead = books.get((f.slug, lead))
        opp = "Down" if lead == "Up" else "Up"
        rec_opp = books.get((f.slug, opp))
        if rec_lead is None:
            continue
        ts_l, ap_l, asz_l, bp_l, bsz_l = rec_lead
        won = (lead == "Up") == (f.outcome == "Up")   # does the lead leg win? (chainlink truth)
        fire_us = int(t_dec)
        ent = entry_fill(ts_l, ap_l[:, 0], asz_l[:, 0], fire_us + LAT_US, STAKE, SPREAD, bp_l[:, 0])
        if ent is None:
            # signal-eligible but no fillable book at fire -> record as no-fill (counts feasibility)
            recs.append(dict(coin=coin, tf=tf, slug=f.slug, seg=f.seg, arm=arm_kind,
                             lead=lead, won=won, ev=np.nan, shares=0.0, filled=False,
                             delta_bps=abs(ret) * 1e4, fire_us=fire_us))
            continue
        ev = ent["ev"]
        shares = ent["shares"]
        entry_idx = ent["entry_idx"]

        # CONTROL: deployed +60s time-sell of the lead leg
        ext = min(fire_us + 60_000_000, slot_end)
        ctrl = exit_fill(ts_l, bp_l[:, 0], bsz_l[:, 0], entry_idx, ext, shares, ev, won)

        # A_HOLD: lead leg held to resolution
        hold_pnl = held_value(shares, ev, won)

        rec = dict(coin=coin, tf=tf, slug=f.slug, seg=f.seg, arm=arm_kind,
                   lead=lead, won=won, ev=ev, shares=shares, filled=True,
                   delta_bps=abs(ret) * 1e4, fire_us=fire_us,
                   ctrl_pnl=ctrl["pnl"], hold_pnl=hold_pnl)

        # A_HEDGE(target): conditional pair completion within K seconds
        hedge_start = fire_us + LAT_US
        stop_us = min(fire_us + HEDGE_WINDOW_US, slot_end)
        for tgt in HEDGE_TARGETS:
            h = hedge_fill(rec_opp, hedge_start, stop_us, ev, shares, tgt)
            q = h["q"]
            matched = min(shares, q)
            rem = shares - matched
            if matched > 0:
                p_opp = h["cost"] / q
                # winner-only settlement: which leg won?
                p_w, p_l = (ev, p_opp) if won else (p_opp, ev)
                locked = pair_locked_pnl(matched, p_w, p_l)
            else:
                locked = 0.0
            residual = held_value(rem, ev, won)
            rec[f"hedge_pnl_{tgt}"] = locked + residual
            rec[f"hedge_locked_{tgt}"] = locked
            rec[f"hedge_resid_{tgt}"] = residual
            rec[f"hedge_completed_{tgt}"] = h["completed"]
            rec[f"paircost_{tgt}"] = h["paircost"]
            rec[f"hedge_q_{tgt}"] = q
        recs.append(rec)


def _seg_cell(df, col):
    v = df[col].dropna().values
    return cell(v)


def _report(A):
    print("\n" + "=" * 100)
    print("RESULTS — net $/slug per cell (winner-only fee, chainlink settle, +85ms, bar-END causal)")
    print("=" * 100)
    F = A[A.filled].copy()
    print(f"filled fires: {len(F)}  (no-fill signal-eligible: {(~A.filled).sum()})")

    for arm_kind in ("causal", "leaky"):
        AK = F[F.arm == arm_kind]
        if not len(AK):
            continue
        print(f"\n########## ARM = {arm_kind.upper()} "
              f"({'bar-END asof == live' if arm_kind=='causal' else 'bar-START == LOOK-AHEAD'}) "
              f"##########")
        for sub_label, sub_mask in (("delta>=3 (all vwap)", AK.ev.notna()),
                                    ("delta>=3 & vwap<0.55", AK.ev < 0.55)):
            G = AK[sub_mask]
            if not len(G):
                continue
            print(f"\n--- sub-gate: {sub_label}  (n_fills={len(G)}) ---")
            for seg in ("IS", "OOS"):
                S = G[G.seg == seg]
                if len(S) < 5:
                    print(f"  [{seg}] n={len(S)} (few)")
                    continue
                print(f"  [{seg}] n={len(S)}")
                print(f"    CONTROL +60s sell : {_seg_cell(S,'ctrl_pnl')}")
                print(f"    A_HOLD (lead hold): {_seg_cell(S,'hold_pnl')}")
                for tgt in HEDGE_TARGETS:
                    col = f"hedge_pnl_{tgt}"
                    comp = S[f"hedge_completed_{tgt}"].mean()
                    pc = S[f"paircost_{tgt}"].dropna()
                    pcmed = pc.median() if len(pc) else float("nan")
                    sub1 = (pc < 1.0).mean() if len(pc) else float("nan")
                    # paired diff vs control
                    d = (S[col] - S["ctrl_pnl"]).dropna().values
                    dlo, dhi = boot(d)
                    print(f"    A_HEDGE tgt={tgt:.2f}: {_seg_cell(S,col)}  "
                          f"comp={comp:4.0%} paircost_med={pcmed:.3f} %pairs<1={100*sub1:4.0f}%  "
                          f"| vs CTRL paired d={d.mean():+.3f} CI[{dlo:+.3f},{dhi:+.3f}]")
                # ex-top2 robustness on the best hedge cell (by mean) + hold
                _ex_top2(S, [f"hedge_pnl_{t}" for t in HEDGE_TARGETS] + ["hold_pnl", "ctrl_pnl"], seg)

    # paired causal-vs-leaky on shared filled slugs (lookahead bias quantification)
    print("\n" + "=" * 100)
    print("LOOKAHEAD-BIAS CHECK — causal vs leaky on shared filled fires (per cell, A_HOLD)")
    piv = F.pivot_table(index=["coin", "slug"], columns="arm", values="hold_pnl")
    piv = piv.dropna()
    if len(piv) >= 5:
        d = (piv["leaky"] - piv["causal"]).values
        lo, hi = boot(d)
        print(f"  A_HOLD leaky-causal: n={len(piv)} mean={d.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}]"
              f"  (positive => bar-START inflates / look-ahead present)")


def _ex_top2(S, cols, seg):
    """report ex-top2-outlier mean for robustness on each cell."""
    parts = []
    for c in cols:
        v = S[c].dropna().values
        if len(v) < 5:
            continue
        srt = np.sort(v)[::-1]
        ex = srt[2:] if len(srt) > 2 else srt
        parts.append(f"{c.replace('hedge_pnl_','h').replace('hold_pnl','HOLD').replace('ctrl_pnl','CTRL')}"
                     f"={ex.mean():+.3f}")
    if parts:
        print(f"    [ex-top2 {seg}] " + "  ".join(parts))


if __name__ == "__main__":
    main()
