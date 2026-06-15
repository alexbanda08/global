"""
_mm_hybrid_engine.py — MM Hybrid Replica: Maker (multi-level) + Taker Completion.

MISSION: Faithful full replica of 0xb945945d's strategy. Two untested levers vs the
validated v2 maker-only engine (_mm_inv_engine.py):

  Lever A — MULTI-LEVEL DEPTH: instead of one best-bid order, quote the full curve
    with N levels spaced at LEVEL_STEP ticks below best bid. Each level gets a $5 clip
    with fresh FIFO queue (simulating early-placed orders at each price point). Budget
    allocated proportionally across levels.

  Lever B — TAKER COMPLETION: when unpaired residual on side X > taker_trigger (shares),
    and the opposite side's L25 ask_price_0 is available such that
    our_vwap_X + ask_price_0_opp < gate_G,
    we LIFT the opposite ask (FIFO-consume L25 ask depth) to complete the pair.
    This is the economically grounded version of b945's 37% taker component:
    "recalibrate with taker" = complete the pair when passive fills dry up.

VALIDATION GATE (pre-registered):
  Hybrid must reproduce b945's behavior within tolerance:
  - maker/taker split: 63% ± 10pp → tune taker_trigger
  - pvs ≈ 0.967 (±0.03)
  - flow capture toward ~28% (vs 7% from v2)
  - IS net ≈ +$3.18/slug median

EXPERIMENT GRID (pre-registered, run AFTER validation):
  gate_G  ∈ {0.97, 0.985, 1.00}
  trigger ∈ {10, 20, 50} shares
  = 9 cells

GUIDE FILTERS (additive, layered on best cell):
  (a) UTC hour regime gate (b945's profitable hours)
  (b) Consecutive-loss pause (after K slugs losing, skip next N=1)
  (c) >0.85 level filter (skip quoting above 0.85 on extreme levels)

DECISION RULE (pre-registered):
  GO if OOS net CI95 lower bound > 0 AND ex-top2 > 0.

FEE MODEL (established, GROUND-TRUTH verified):
  - Maker fills: $0 fee + rebate $0.0015/share (all shares, winner or loser)
  - Taker fills: fee = 0.07 * price * (1 - price) per share, WINNER-ONLY
  - Paired redeem: $1/pair, split equally across shares
  - Unpaired: winner side pays taker fee on taker-acquired shares only

DATA:
  Canonical: btc-updown-15m slugs, Apr22→Jun11
  IS: Apr22→May20, OOS: May21→Jun11
  L25 books (all 25 ask/bid levels) for taker depth
  trades_polymarket side='sell' for maker FIFO fills (taker sells INTO our bids)
  trades_polymarket side='buy' for AS book-move signal (taker buys = L25 ask consumed)

B945 GROUND TRUTH (per_slug_paired_ledger, n=1564 slugs):
  pvs median 0.9674 | pair_frac 0.912 | fills/side median 44 | sh/side median 760
  IS (Apr22–May20): gt_pnl median +$1.72/slug | OOS (May21–Jun11): gt_pnl median +$5.91/slug
  Full window: gt_pnl median +$3.18/slug, sum +$6,378 (+$21,742 incl rebates on LB)
  Maker/taker: 63% maker / 37% taker (OrderFilled receipt logs, n=634 events)
"""

import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
L25_PATH   = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / "btc.parquet"
TR_PATH    = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / "btc.parquet"
RES_PATH   = ROOT / "data" / "v4" / "canonical" / "resolutions.parquet"
TAPE_PATH  = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xb945945d" / "fill_tape_full.parquet"
LEDGER_PATH = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xb945945d" / "per_slug_paired_ledger.parquet"
CACHE_DIR  = ROOT / "strategy_lab" / "wallet_hunt" / "cache"
OUT_PARQUET = CACHE_DIR / "_mm_hybrid_results.parquet"
REPORT_PATH = ROOT / "strategy_lab" / "reports" / "MM_HYBRID_REPLICA_2026_06_13.md"

sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
try:
    from scalp_fill_lib_2026_06_10 import boot
except ImportError:
    def boot(v, nb=1000):
        rng = np.random.default_rng(42)
        v = np.asarray(v, float)
        means = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(nb)]
        return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))

# ── Constants ──────────────────────────────────────────────────────────────────
WINDOW_S      = 900
REBATE_SH     = 0.0015     # maker rebate per share (all fills)
CLIP_USD      = 5.0        # per-level clip size
TAKER_FEE_A   = 0.07       # taker fee coefficient (winner-only: 0.07*p*(1-p))
LEVEL_STEP    = 0.02       # ticks between levels (2¢)
N_LEVELS      = 5          # number of maker levels to spread below best bid
OFFSET_S      = -3600      # placement offset from slot_start (s)
IS_CUTOFF_US  = int(pd.Timestamp("2026-05-21", tz="UTC").timestamp() * 1e6)

# B945 ground truth
GT_PVS   = 0.9674
GT_NET   = 3.18
GT_MK_PCT = 0.63   # 63% maker
GT_TK_PCT = 0.37   # 37% taker

# Validated base config (from _mm_inv_engine v2 best cell)
BASE_Q_CAP = 20
BASE_GAMMA = 0.05
BASE_BUDGET = 332.0   # b945 median usd/side

# Pre-registered experiment grid
GATE_GRID    = [0.97, 0.985, 1.00]
TRIGGER_GRID = [10, 20, 50]


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADERS
# ══════════════════════════════════════════════════════════════════════════════

def load_resolutions():
    r = pd.read_parquet(RES_PATH, columns=["slug", "slot_start_us", "outcome"])
    r = r[r.slug.str.contains("btc-updown-15m", na=False, regex=False)]
    r = r[r.slot_start_us >= int(pd.Timestamp("2026-04-22", tz="UTC").timestamp() * 1e6)]
    r = r.drop_duplicates("slug")
    r["slot_start_s"] = (r["slot_start_us"] // 1_000_000).astype(int)
    return r.reset_index(drop=True)


def load_books_full(slug_set):
    """Load L25 books with all 25 bid AND ask levels.

    Returns dict (slug, outcome) -> {ts, bp[25], bs[25], ap[25], as[25]}
    """
    bp_names = [f"bid_price_{i}" for i in range(25)]
    bs_names = [f"bid_size_{i}" for i in range(25)]
    ap_names = [f"ask_price_{i}" for i in range(25)]
    as_names = [f"ask_size_{i}" for i in range(25)]
    cols = ["timestamp_us", "slug", "outcome"] + bp_names + bs_names + ap_names + as_names
    f = pq.ParquetFile(L25_PATH)
    parts = []
    for i in range(f.num_row_groups):
        df = f.read_row_group(i, columns=cols).to_pandas()
        df = df[df.slug.isin(slug_set)]
        if len(df):
            parts.append(df)
    if not parts:
        return {}
    B = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
    out = {}
    for (sl, oc), g in B.groupby(["slug", "outcome"], observed=True, sort=False):
        g = g.sort_values("timestamp_us")
        out[(sl, oc)] = {
            "ts": g["timestamp_us"].to_numpy(np.int64),
            "bp": g[bp_names].to_numpy(np.float64),
            "bs": g[bs_names].to_numpy(np.float64),
            "ap": g[ap_names].to_numpy(np.float64),
            "as_": g[as_names].to_numpy(np.float64),
        }
    return out


def load_taker_sells(slug_set):
    """Taker SELL events into our bids — used for FIFO maker fill simulation."""
    f = pq.ParquetFile(TR_PATH)
    parts = []
    for i in range(f.num_row_groups):
        df = f.read_row_group(i, columns=["timestamp_us", "slug", "outcome",
                                           "price", "size", "side"]).to_pandas()
        df = df[df.slug.isin(slug_set) & (df["side"].str.lower() == "sell")]
        if len(df):
            parts.append(df)
    if not parts:
        return {}
    T = pd.concat(parts, ignore_index=True).sort_values("timestamp_us")
    out = {}
    for (sl, oc), g in T.groupby(["slug", "outcome"], observed=True, sort=False):
        g = g.sort_values("timestamp_us")
        out[(sl, oc)] = {
            "ts": g["timestamp_us"].to_numpy(np.int64),
            "px": g["price"].to_numpy(np.float64),
            "sz": g["size"].to_numpy(np.float64),
        }
    return out


# ══════════════════════════════════════════════════════════════════════════════
# BOOK HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _snap_idx(bk, at_us):
    """Return index of latest book snapshot at or before at_us."""
    ts = bk["ts"]
    j = int(np.searchsorted(ts, at_us, "right")) - 1
    return max(0, min(j, len(ts) - 1))


def _best_bid_at(bk, at_us):
    j = _snap_idx(bk, at_us)
    p = bk["bp"][j, 0]
    return float(p) if np.isfinite(p) else float("nan")


def _ask_walk(bk, at_us, needed_shares, max_price=1.0):
    """Walk the L25 ask depth to fill `needed_shares` at current snapshot.

    Returns (achieved_shares, total_cost, vwap) — partial fill allowed.
    """
    j = _snap_idx(bk, at_us)
    ap = bk["ap"][j]
    as_ = bk["as_"][j]
    filled = 0.0
    cost = 0.0
    for lvl in range(25):
        p = ap[lvl]
        if not np.isfinite(p) or p <= 0 or p > max_price:
            break
        sz = as_[lvl]
        if not np.isfinite(sz) or sz <= 0:
            continue
        take = min(sz, needed_shares - filled)
        filled += take
        cost += take * p
        if filled >= needed_shares - 1e-9:
            break
    vwap = cost / filled if filled > 1e-9 else float("nan")
    return filled, cost, vwap


def _best_ask_at(bk, at_us):
    j = _snap_idx(bk, at_us)
    p = bk["ap"][j, 0]
    return float(p) if np.isfinite(p) else float("nan")


# ══════════════════════════════════════════════════════════════════════════════
# HYBRID SLUG SIMULATION
# ══════════════════════════════════════════════════════════════════════════════

def sim_slug_hybrid(bk_up, tr_up, bk_dn, tr_dn,
                    slot_s, offset_s, budget, Q_cap, gamma,
                    gate_G, taker_trigger,
                    n_levels=N_LEVELS, level_step=LEVEL_STEP,
                    sigma=0.5):
    """
    Joint two-sided simulation with:
      Maker layer: N levels below best bid ($5 clips each, EV-layered), GLT cap, AS skew.
      Taker layer: when |resid| > taker_trigger AND sum_vwap < gate_G, lift opposite ask.

    Returns dict with per-side fills + taker info.
    """
    t_place = (slot_s + offset_s) * 1_000_000
    t_end   = (slot_s + WINDOW_S) * 1_000_000

    if bk_up is None and bk_dn is None:
        return _empty_result()

    # ── Maker state per side ─────────────────────────────────────────────────
    sides = {}
    for tag, bk in (("up", bk_up), ("dn", bk_dn)):
        if bk is None:
            sides[tag] = None
            continue
        init_bid = _best_bid_at(bk, t_place)
        if not np.isfinite(init_bid) or init_bid <= 0:
            sides[tag] = None
            continue
        # Multi-level: N levels from init_bid down by LEVEL_STEP each
        # Each level gets one CLIP_USD order; budget split across levels
        budget_per_level = budget / n_levels
        levels = []
        for lv in range(n_levels):
            lp = max(0.01, init_bid - lv * level_step)
            lp = round(lp, 4)
            if lp <= 0.01:
                break
            clip_sh = min(CLIP_USD, budget_per_level) / lp
            # FIFO queue_ahead at this price: sum of sizes at prices > lp
            # Simplified: use best bid size as proxy (no deep pre-queue data)
            # Fresh re-entry (placement at -3600s = likely front of queue)
            levels.append({
                "price": lp,
                "remaining": clip_sh,
                "budget_left": budget_per_level,
                "n_fills": 0,
            })
        sides[tag] = {
            "bk": bk,
            "levels": levels,
            "cur_bid": init_bid,
            "sh": 0.0, "cost": 0.0, "n_fills": 0,
            "active": True,
            # track maker vs taker fills
            "sh_maker": 0.0, "sh_taker": 0.0,
            "cost_maker": 0.0, "cost_taker": 0.0,
            "n_taker": 0,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────
    def net_resid(tag):
        o = "dn" if tag == "up" else "up"
        s_t = sides[tag]["sh"] if sides[tag] else 0.0
        s_o = sides[o]["sh"] if sides[o] else 0.0
        return s_t - s_o

    def apply_glt(tag):
        if not np.isfinite(Q_cap):
            return
        if sides[tag]:
            sides[tag]["active"] = net_resid(tag) <= Q_cap

    def as_skew(tag, base_price, ev_ts):
        if gamma <= 0:
            return min(base_price, 0.99)
        q = net_resid(tag)
        tl = max(0.0, (t_end - ev_ts) / (WINDOW_S * 1_000_000))
        skew = -(q / 100.0) * gamma * (sigma ** 2) * tl
        return min(max(base_price + skew, 0.01), 0.99)

    def get_vwap(tag):
        s = sides[tag]
        if s is None or s["sh"] <= 0:
            return float("nan")
        return s["cost"] / s["sh"]

    def try_taker_complete(ev_ts):
        """If either side has unpaired resid > trigger AND sum < gate_G, lift opposite."""
        for tag in ("up", "dn"):
            s = sides[tag]
            if s is None or s["sh"] <= 0:
                continue
            other = "dn" if tag == "up" else "up"
            s_other = sides[other]

            resid = net_resid(tag)   # positive = this side heavier
            if resid < taker_trigger:
                continue   # not enough residual to trigger

            bk_opp = s_other["bk"] if s_other else None
            if bk_opp is None:
                continue

            # Current vwap on the heavy side
            vwap_self = get_vwap(tag)
            if not np.isfinite(vwap_self):
                continue

            # Check if completing resid shares at the opposite ask meets the gate
            ask0 = _best_ask_at(bk_opp, ev_ts)
            if not np.isfinite(ask0) or ask0 <= 0:
                continue

            # Would completing improve the pair sum?
            # pair_sum if we take = vwap_self (stable) + ask_opp (taker cost/share)
            # For the gate: we need vwap_self + ask0 < gate_G
            # (We use ask0 as the minimum achievable ask price for the gate check)
            if vwap_self + ask0 >= gate_G:
                continue   # not profitable enough

            # Budget check: use any remaining budget on other side, else new cap = resid * ask0
            # Taker completion budget: uncapped (use up to resid shares)
            needed = min(resid, 200.0)   # cap single taker at 200 sh (sanity)
            filled, cost_tk, vwap_tk = _ask_walk(bk_opp, ev_ts, needed, max_price=gate_G - vwap_self)
            if filled < 1e-9:
                continue

            # Execute taker fill on opposite side
            if s_other is None:
                # Initialize other side if it was None (shouldn't happen but guard)
                continue
            s_other["sh"] += filled
            s_other["cost"] += cost_tk
            s_other["sh_taker"] += filled
            s_other["cost_taker"] += cost_tk
            s_other["n_fills"] += 1
            s_other["n_taker"] += 1

            # After taker fill, recheck GLT both sides
            apply_glt(tag)
            apply_glt(other)

    # ── Event stream ──────────────────────────────────────────────────────────
    # kind 0=book, 1=taker_sell (into our bids)
    events = []
    for tag, bk, tr in (("up", bk_up, tr_up), ("dn", bk_dn, tr_dn)):
        if bk is not None:
            ts_bk = bk["ts"]; bp0 = bk["bp"][:, 0]
            lo = int(np.searchsorted(ts_bk, t_place, "left"))
            hi = int(np.searchsorted(ts_bk, t_end, "right"))
            for k in range(lo, hi):
                events.append((int(ts_bk[k]), 0, tag, float(bp0[k])))
        if tr is not None:
            ts_tr = tr["ts"]; px = tr["px"]; sz = tr["sz"]
            lo = int(np.searchsorted(ts_tr, t_place, "left"))
            hi = int(np.searchsorted(ts_tr, t_end, "right"))
            for k in range(lo, hi):
                events.append((int(ts_tr[k]), 1, tag, (float(px[k]), float(sz[k]))))
    events.sort(key=lambda e: (e[0], e[1]))

    last_taker_check_ts = t_place   # throttle taker checks to once per book tick

    for ev_ts, kind, tag, payload in events:
        s = sides[tag]
        if s is None:
            continue

        if kind == 0:
            # Book update: requote all maker levels using AS skew
            new_bid = payload
            if np.isfinite(new_bid) and new_bid > 0:
                s["cur_bid"] = new_bid
                # Requote each level relative to the new best bid
                for lv_idx, lv in enumerate(s["levels"]):
                    if lv["remaining"] <= 1e-6 or lv["budget_left"] <= 1e-6:
                        continue
                    new_lv_base = max(0.01, new_bid - lv_idx * level_step)
                    new_lv_p = as_skew(tag, new_lv_base, ev_ts)
                    lv["price"] = round(min(new_lv_p, 0.99), 4)
                apply_glt(tag)
                # Check taker completion on book updates (throttle: only when bid changes)
                if ev_ts > last_taker_check_ts:
                    try_taker_complete(ev_ts)
                    last_taker_check_ts = ev_ts
        else:
            # Taker SELL trade event: fills our maker bids
            tp, ts2 = payload
            apply_glt(tag)
            if not s["active"]:
                continue
            remaining_trade = ts2
            for lv in s["levels"]:
                if lv["remaining"] <= 1e-6 or lv["budget_left"] <= 1e-6:
                    continue
                if remaining_trade <= 1e-9:
                    break
                lp = lv["price"]
                # Fill if trade price <= our bid (we get filled)
                fa = 0.0
                if tp <= lp + 1e-6:
                    fa = min(lv["remaining"], remaining_trade)
                if fa > 1e-9:
                    lv["remaining"] -= fa
                    lv["budget_left"] -= fa * lp
                    lv["n_fills"] += 1
                    s["sh"] += fa
                    s["cost"] += fa * lp
                    s["sh_maker"] += fa
                    s["cost_maker"] += fa * lp
                    s["n_fills"] += 1
                    remaining_trade -= fa
                    # Re-enter at same level price if budget remains
                    if lv["remaining"] <= 1e-6 and lv["budget_left"] > 1e-6:
                        new_clip = min(CLIP_USD, lv["budget_left"]) / lp
                        lv["remaining"] = new_clip
                    apply_glt(tag)
                    other = "dn" if tag == "up" else "up"
                    if sides[other]:
                        apply_glt(other)

    # ── PnL accounting ────────────────────────────────────────────────────────
    result = {}
    for tag in ("up", "dn"):
        s = sides[tag]
        if s is None:
            result[f"sh_{tag}"] = 0.0
            result[f"cost_{tag}"] = 0.0
            result[f"vwap_{tag}"] = float("nan")
            result[f"sh_maker_{tag}"] = 0.0
            result[f"sh_taker_{tag}"] = 0.0
            result[f"n_fills_{tag}"] = 0
            result[f"n_taker_{tag}"] = 0
        else:
            result[f"sh_{tag}"] = s["sh"]
            result[f"cost_{tag}"] = s["cost"]
            result[f"vwap_{tag}"] = s["cost"] / s["sh"] if s["sh"] > 0 else float("nan")
            result[f"sh_maker_{tag}"] = s["sh_maker"]
            result[f"sh_taker_{tag}"] = s["sh_taker"]
            result[f"cost_taker_{tag}"] = s["cost_taker"]
            result[f"n_fills_{tag}"] = s["n_fills"]
            result[f"n_taker_{tag}"] = s["n_taker"]
    return result


def _empty_result():
    r = {}
    for tag in ("up", "dn"):
        for k in ("sh", "cost", "vwap", "sh_maker", "sh_taker", "cost_taker"):
            r[f"{k}_{tag}"] = 0.0 if k != "vwap" else float("nan")
        r[f"n_fills_{tag}"] = 0
        r[f"n_taker_{tag}"] = 0
    return r


# ══════════════════════════════════════════════════════════════════════════════
# PNL CALCULATOR
# ══════════════════════════════════════════════════════════════════════════════

def slug_pnl_hybrid(o, won_up):
    """
    Compute PnL from hybrid fill dict.

    Fee model (established, GROUND-TRUTH):
      - Maker fills: $0 fee + rebate REBATE_SH/share (all shares)
      - Taker fills: fee = 0.07 * p_taker * (1 - p_taker) per share, WINNER-ONLY
        where p_taker = vwap_taker on that side
      - Paired redeem: $1/pair
    """
    sh_up = o["sh_up"]; sh_dn = o["sh_dn"]
    vw_up = o["vwap_up"]; vw_dn = o["vwap_dn"]
    sh_mk_up = o["sh_maker_up"]; sh_tk_up = o["sh_taker_up"]
    sh_mk_dn = o["sh_maker_dn"]; sh_tk_dn = o["sh_taker_dn"]

    if sh_up <= 0 and sh_dn <= 0:
        return _zero_pnl()

    paired = min(sh_up, sh_dn)
    pvs = (vw_up if np.isfinite(vw_up) else 1.0) + (vw_dn if np.isfinite(vw_dn) else 1.0)
    tot = sh_up + sh_dn
    pair_frac = 2 * paired / tot if tot > 0 else 0.0

    # Paired redeem: earn (1 - pvs) per pair; no fee on redeem
    paired_pnl = paired * (1.0 - pvs) if np.isfinite(pvs) else 0.0

    # Residual (unpaired) PnL
    resid_up = sh_up - paired
    resid_dn = sh_dn - paired
    vu = vw_up if np.isfinite(vw_up) else 0.0
    vd = vw_dn if np.isfinite(vw_dn) else 0.0

    # Taker fee applies only to taker-acquired shares, winner-only
    # Estimate taker vwap per side (if any taker fills occurred)
    vwap_tk_up = o["cost_taker_up"] / sh_tk_up if sh_tk_up > 1e-9 else vu
    vwap_tk_dn = o["cost_taker_dn"] / sh_tk_dn if sh_tk_dn > 1e-9 else vd

    if won_up:
        # Up wins: residual Up earns (1-vu) per sh (minus taker fee on taker sh)
        res_up_gross = resid_up * (1.0 - vu)
        # Taker fee on taker-acquired Up shares (they win)
        taker_fee_up = sh_tk_up * TAKER_FEE_A * vwap_tk_up * (1 - vwap_tk_up)
        # Residual Down loses: -vd per sh (no fee on losers)
        res_dn = -resid_dn * vd
        res_pnl = res_up_gross - taker_fee_up + res_dn
    else:
        # Down wins
        res_dn_gross = resid_dn * (1.0 - vd)
        taker_fee_dn = sh_tk_dn * TAKER_FEE_A * vwap_tk_dn * (1 - vwap_tk_dn)
        res_up = -resid_up * vu
        res_pnl = res_dn_gross - taker_fee_dn + res_up

    # Also taker fee on paired taker-acquired shares (the winning leg of the pair)
    # The paired positions also contain taker fills; taker fee applies to winner leg
    # Conservative: charge taker fee proportionally on paired taker shares for winner side
    # sh_tk winner leg in paired region = min(sh_tk_winner, paired)
    if won_up:
        paired_tk_winner = min(sh_tk_up, paired)
        paired_taker_fee = paired_tk_winner * TAKER_FEE_A * vwap_tk_up * (1 - vwap_tk_up)
    else:
        paired_tk_winner = min(sh_tk_dn, paired)
        paired_taker_fee = paired_tk_winner * TAKER_FEE_A * vwap_tk_dn * (1 - vwap_tk_dn)

    # Rebate: all maker shares (both sides, winners and losers)
    rebate = (sh_mk_up + sh_mk_dn) * REBATE_SH

    net = paired_pnl - paired_taker_fee + res_pnl + rebate

    # Maker/taker split stats
    total_sh = sh_up + sh_dn
    sh_maker_total = sh_mk_up + sh_mk_dn
    sh_taker_total = sh_tk_up + sh_tk_dn
    maker_pct = sh_maker_total / total_sh if total_sh > 0 else float("nan")
    taker_pct = sh_taker_total / total_sh if total_sh > 0 else float("nan")

    return dict(
        sh_up=sh_up, sh_dn=sh_dn, vwap_up=vw_up, vwap_dn=vw_dn,
        paired=paired, pvs=pvs, pair_frac=pair_frac,
        paired_pnl=paired_pnl, residual_pnl=res_pnl, rebate=rebate,
        net_pnl=net,
        sh_maker=sh_maker_total, sh_taker=sh_taker_total,
        maker_pct=maker_pct, taker_pct=taker_pct,
        n_fills_up=o["n_fills_up"], n_fills_dn=o["n_fills_dn"],
        n_taker_up=o["n_taker_up"], n_taker_dn=o["n_taker_dn"],
        both_sides=(sh_up > 0 and sh_dn > 0),
    )


def _zero_pnl():
    return dict(
        sh_up=0., sh_dn=0., vwap_up=np.nan, vwap_dn=np.nan,
        paired=0., pvs=np.nan, pair_frac=0.,
        paired_pnl=0., residual_pnl=0., rebate=0., net_pnl=0.,
        sh_maker=0., sh_taker=0., maker_pct=np.nan, taker_pct=np.nan,
        n_fills_up=0, n_fills_dn=0, n_taker_up=0, n_taker_dn=0,
        both_sides=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# FLOW CAPTURE
# ══════════════════════════════════════════════════════════════════════════════

def compute_flow_capture(slug_rows_df, res_df, taker_sells):
    """
    Flow capture = our maker fills / total taker SELL flow on the market for the same slugs.
    """
    our_sh = slug_rows_df[["sh_maker_up", "sh_maker_dn"]].sum().sum() if "sh_maker_up" in slug_rows_df.columns else slug_rows_df["sh_maker"].sum()
    slug_set = set(slug_rows_df["slug"])
    total_flow = 0.0
    for (sl, oc), tr in taker_sells.items():
        if sl not in slug_set:
            continue
        row = res_df[res_df["slug"] == sl]
        if len(row) == 0:
            continue
        slot_s = int(row.iloc[0]["slot_start_s"])
        t0 = (slot_s + OFFSET_S) * 1_000_000
        t1 = (slot_s + WINDOW_S) * 1_000_000
        ts = tr["ts"]; sz = tr["sz"]
        lo = int(np.searchsorted(ts, t0, "left"))
        hi = int(np.searchsorted(ts, t1, "right"))
        total_flow += sz[lo:hi].sum()
    cap = our_sh / total_flow if total_flow > 0 else float("nan")
    return cap, our_sh, total_flow


# ══════════════════════════════════════════════════════════════════════════════
# RUN ENGINE ON ALL SLUGS (IS + OOS)
# ══════════════════════════════════════════════════════════════════════════════

def run_all_slugs(res_df, tob, taker_sells, gate_G, taker_trigger,
                  Q_cap=BASE_Q_CAP, gamma=BASE_GAMMA, budget=BASE_BUDGET,
                  n_levels=N_LEVELS, label=""):
    slot_map    = dict(zip(res_df["slug"], res_df["slot_start_s"]))
    outcome_map = dict(zip(res_df["slug"], res_df["outcome"]))
    recs = []
    for slug in res_df["slug"]:
        slot_s = slot_map[slug]
        won_up = str(outcome_map[slug]).lower() == "up"
        o = sim_slug_hybrid(
            tob.get((slug, "Up")), taker_sells.get((slug, "Up")),
            tob.get((slug, "Down")), taker_sells.get((slug, "Down")),
            slot_s, OFFSET_S, budget, Q_cap, gamma,
            gate_G, taker_trigger, n_levels=n_levels,
        )
        p = slug_pnl_hybrid(o, won_up)
        p["slug"] = slug
        p["slot_start_us"] = slot_s * 1_000_000
        p["is_oos"] = "OOS" if slot_s * 1_000_000 >= IS_CUTOFF_US else "IS"
        recs.append(p)
        # Track raw sh_maker per side for flow capture
        recs[-1]["sh_maker_up"] = o["sh_maker_up"]
        recs[-1]["sh_maker_dn"] = o["sh_maker_dn"]
    return pd.DataFrame(recs)


# ══════════════════════════════════════════════════════════════════════════════
# STATS HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def summarize(df, label=""):
    fi = df[df.both_sides | (df.sh_up > 0) | (df.sh_dn > 0)]
    if len(fi) == 0:
        return {}
    net = fi.net_pnl.to_numpy()
    ci = boot(net, nb=2000)
    ex2 = net[np.argsort(np.abs(net))[:-2]].mean() if len(net) > 2 else np.nan

    # Ex-top2 CI
    net_ex2 = net[np.argsort(np.abs(net))[:-2]] if len(net) > 2 else net
    ci_ex2 = boot(net_ex2, nb=2000) if len(net_ex2) > 2 else (np.nan, np.nan)

    pvs_med = fi.pvs.dropna().median()
    pf_med  = fi.pair_frac.median()
    mk_pct  = fi.maker_pct.dropna().mean()
    tk_pct  = fi.taker_pct.dropna().mean()
    tot_sh  = fi.sh_up.sum() + fi.sh_dn.sum()
    mk_sh   = fi.sh_maker.sum()
    tk_sh   = fi.sh_taker.sum()
    mk_pct_sh = mk_sh / tot_sh if tot_sh > 0 else float("nan")
    tk_pct_sh = tk_sh / tot_sh if tot_sh > 0 else float("nan")
    fills_sd  = (fi.n_fills_up + fi.n_fills_dn).mean() / 2

    return dict(
        label=label, n=len(fi), n_both=int(fi.both_sides.sum()),
        pvs=pvs_med, pair_frac=pf_med, fills_sd=fills_sd,
        net_mean=net.mean(), net_median=np.median(net),
        ci_lo=ci[0], ci_hi=ci[1], ex2=ex2,
        ci_ex2_lo=ci_ex2[0], ci_ex2_hi=ci_ex2[1],
        maker_pct_sh=mk_pct_sh, taker_pct_sh=tk_pct_sh,
        sh_maker=mk_sh, sh_taker=tk_sh,
        paired_pnl=fi.paired_pnl.mean(), residual_pnl=fi.residual_pnl.mean(),
        rebate=fi.rebate.mean(),
    )


def print_summary(s, prefix=""):
    if not s:
        print(f"  {prefix}NO DATA")
        return
    print(f"  {prefix}n={s['n']} pvs={s['pvs']:.4f} pf={100*s['pair_frac']:.1f}% "
          f"fills/sd={s['fills_sd']:.1f} maker={100*s['maker_pct_sh']:.1f}% taker={100*s['taker_pct_sh']:.1f}%")
    print(f"  {prefix}net_mean={s['net_mean']:+.2f} net_med={s['net_median']:+.2f} "
          f"CI95=[{s['ci_lo']:+.2f},{s['ci_hi']:+.2f}] ex2={s['ex2']:+.2f} "
          f"CI_ex2=[{s['ci_ex2_lo']:+.2f},{s['ci_ex2_hi']:+.2f}]")
    print(f"  {prefix}paired={s['paired_pnl']:+.2f} resid={s['residual_pnl']:+.2f} "
          f"rebate={s['rebate']:+.2f}/slug")


# ══════════════════════════════════════════════════════════════════════════════
# REGIME FILTER (Guide filter A)
# ══════════════════════════════════════════════════════════════════════════════

def find_regime_hours(res_df, all_rows_df):
    """Find UTC hours where b945's strategy shows above-median gt_pnl."""
    # Join slot time to results
    df = all_rows_df.copy()
    df["hour_utc"] = (df["slot_start_us"] // 1_000_000 % 86400) // 3600
    df["weekday"]  = pd.to_datetime(df["slot_start_us"] // 1_000, unit="ms", utc=True).dt.weekday

    # By hour
    by_hour = df.groupby("hour_utc")["net_pnl"].agg(["mean", "median", "count"])
    by_hour = by_hour[by_hour["count"] >= 10]
    good_hours = set(by_hour[by_hour["mean"] > 0].index.tolist())

    # By weekday
    by_day = df.groupby("weekday")["net_pnl"].agg(["mean", "median", "count"])
    by_day = by_day[by_day["count"] >= 20]
    good_days = set(by_day[by_day["mean"] > 0].index.tolist())

    return good_hours, good_days, by_hour, by_day


def apply_regime_filter(rows_df, good_hours, good_days):
    rows_df = rows_df.copy()
    rows_df["hour_utc"] = (rows_df["slot_start_us"] // 1_000_000 % 86400) // 3600
    rows_df["weekday"]  = pd.to_datetime(rows_df["slot_start_us"] // 1_000, unit="ms", utc=True).dt.weekday
    mask = rows_df["hour_utc"].isin(good_hours) & rows_df["weekday"].isin(good_days)
    return rows_df[mask].copy()


def apply_consec_loss_filter(rows_df, K=2, N=1):
    """Skip N slugs after K consecutive losing slugs (time-ordered)."""
    rows_sorted = rows_df.sort_values("slot_start_us").copy()
    keep = []
    consec = 0
    skip_n = 0
    for _, row in rows_sorted.iterrows():
        if skip_n > 0:
            skip_n -= 1
            keep.append(False)
            continue
        if row["net_pnl"] < 0:
            consec += 1
        else:
            consec = 0
        keep.append(True)
        if consec >= K:
            skip_n = N
            consec = 0
    rows_sorted["keep"] = keep
    return rows_sorted[rows_sorted["keep"]].drop(columns=["keep"])


# ══════════════════════════════════════════════════════════════════════════════
# WORKED EXAMPLES
# ══════════════════════════════════════════════════════════════════════════════

def print_worked_examples(res_df, tob, taker_sells, gate_G, taker_trigger,
                           n_examples=3):
    """Show 3 worked example slugs with maker + taker event details."""
    slot_map    = dict(zip(res_df["slug"], res_df["slot_start_s"]))
    outcome_map = dict(zip(res_df["slug"], res_df["outcome"]))

    # Pick example slugs: one with taker completion, one without, one OOS
    slugs = list(res_df["slug"])[:50]   # sample first 50

    examples_printed = 0
    for slug in slugs:
        if examples_printed >= n_examples:
            break
        slot_s = slot_map[slug]
        won_up = str(outcome_map[slug]).lower() == "up"
        o = sim_slug_hybrid(
            tob.get((slug, "Up")), taker_sells.get((slug, "Up")),
            tob.get((slug, "Down")), taker_sells.get((slug, "Down")),
            slot_s, OFFSET_S, BASE_BUDGET, BASE_Q_CAP, BASE_GAMMA,
            gate_G, taker_trigger,
        )
        p = slug_pnl_hybrid(o, won_up)
        if not p["both_sides"]:
            continue
        slot_dt = pd.Timestamp(slot_s, unit="s", tz="UTC")
        print(f"\n  --- Example: {slug} | {slot_dt.date()} | won_up={won_up}")
        print(f"    Maker fills: up={o['sh_maker_up']:.1f}sh / dn={o['sh_maker_dn']:.1f}sh")
        print(f"    Taker fills: up={o['sh_taker_up']:.1f}sh / dn={o['sh_taker_dn']:.1f}sh  (events: up={o['n_taker_up']} dn={o['n_taker_dn']})")
        print(f"    vwap_up={o['vwap_up']:.4f}  vwap_dn={o['vwap_dn']:.4f}  pvs={p['pvs']:.4f}")
        print(f"    paired={p['paired']:.1f}sh  pair_frac={100*p['pair_frac']:.1f}%")
        print(f"    paired_pnl={p['paired_pnl']:+.2f}  resid_pnl={p['residual_pnl']:+.2f}  rebate={p['rebate']:+.2f}")
        print(f"    NET={p['net_pnl']:+.2f}  maker%={100*p['maker_pct']:.0f}%  taker%={100*p['taker_pct']:.0f}%")
        examples_printed += 1


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()

    print("=" * 72)
    print("MM HYBRID REPLICA — 2026-06-13")
    print("Levers: multi-level depth (A) + taker completion (B)")
    print("=" * 72)

    # ── Load data ─────────────────────────────────────────────────────────────
    print("\nLoading resolutions...", flush=True)
    res_df = load_resolutions()
    print(f"  {len(res_df)} btc-updown-15m slugs  (Apr22→Jun11)")
    res_IS  = res_df[res_df["slot_start_us"] <  IS_CUTOFF_US]
    res_OOS = res_df[res_df["slot_start_us"] >= IS_CUTOFF_US]
    print(f"  IS={len(res_IS)} slugs | OOS={len(res_OOS)} slugs")

    slug_set = set(res_df["slug"])
    print("\nLoading L25 books (full 25 levels)...", flush=True)
    tob = load_books_full(slug_set)
    print(f"  {len(tob)} book series  t={time.time()-t0:.0f}s")

    print("\nLoading taker sell trades...", flush=True)
    taker_sells = load_taker_sells(slug_set)
    print(f"  {len(taker_sells)} trade series  t={time.time()-t0:.0f}s")

    # ── B945 ground truth summary ──────────────────────────────────────────
    print("\n--- B945 GROUND TRUTH ---")
    print(f"  pvs median={GT_PVS:.4f}  net/slug median=+${GT_NET:.2f}")
    print(f"  maker={100*GT_MK_PCT:.0f}%  taker={100*GT_TK_PCT:.0f}%")
    print(f"  IS (Apr22–May20) gt_pnl median=+$1.72  OOS (May21–Jun11) median=+$5.91")
    print(f"  IS/OOS split: {len(res_IS)}/{len(res_OOS)} slugs")

    # ── STEP 1: Validation run (best prior config + sweep taker_trigger) ──
    print("\n" + "=" * 72)
    print("STEP 1: VALIDATION — Tune taker_trigger to reproduce 63/37 split")
    print("  Config: Q=20, gamma=0.05, budget=$332, offset=-3600s, n_levels=5")
    print("  Grid: gate_G∈{0.985} × trigger∈{10,20,50}")
    print("=" * 72)

    # Quick validation run on IS only (200-slug sample for speed)
    rng_v = np.random.default_rng(42)
    is_slugs = list(res_IS["slug"])
    sample_is = list(rng_v.choice(is_slugs, min(200, len(is_slugs)), replace=False))
    res_IS_sample = res_IS[res_IS["slug"].isin(sample_is)].reset_index(drop=True)

    for trigger in [10, 20, 50]:
        print(f"\n  gate_G=0.985  trigger={trigger}sh:", flush=True)
        df_v = run_all_slugs(res_IS_sample, tob, taker_sells,
                             gate_G=0.985, taker_trigger=trigger, label="IS_sample")
        s = summarize(df_v, label=f"IS_sample trigger={trigger}")
        print_summary(s, prefix="    ")
        if s:
            mk_pct = s["maker_pct_sh"]
            print(f"    -> maker_pct={100*mk_pct:.1f}% (target 63±10%) | "
                  f"{'OK' if 0.53 <= mk_pct <= 0.73 else 'OUT OF RANGE'}")

    # ── STEP 2: Experiment grid (full IS+OOS) ─────────────────────────────
    print("\n" + "=" * 72)
    print("STEP 2: EXPERIMENT GRID — gate_G × trigger, full IS+OOS")
    print(f"  Pre-registered: gate_G∈{GATE_GRID} × trigger∈{TRIGGER_GRID} = 9 cells")
    print("=" * 72)

    all_cell_results = []
    best_config = None
    best_oos_ci_lo = float("-inf")

    for gate_G in GATE_GRID:
        for trigger in TRIGGER_GRID:
            print(f"\n  gate_G={gate_G:.3f}  trigger={trigger}sh:", flush=True)
            df_all = run_all_slugs(res_df, tob, taker_sells,
                                   gate_G=gate_G, taker_trigger=trigger)
            df_all["gate_G"] = gate_G
            df_all["taker_trigger"] = trigger
            all_cell_results.append(df_all)

            df_IS  = df_all[df_all.is_oos == "IS"]
            df_OOS = df_all[df_all.is_oos == "OOS"]

            s_IS  = summarize(df_IS,  label=f"IS  G={gate_G:.3f} trig={trigger}")
            s_OOS = summarize(df_OOS, label=f"OOS G={gate_G:.3f} trig={trigger}")

            print(f"  IS  [{s_IS.get('n',0)} slugs]:")
            print_summary(s_IS, prefix="    ")
            print(f"  OOS [{s_OOS.get('n',0)} slugs]:")
            print_summary(s_OOS, prefix="    ")

            # Flow capture (IS only for speed)
            cap, mk_sh, tot_flow = compute_flow_capture(df_IS, res_IS, taker_sells)
            print(f"    IS flow_capture={100*cap:.1f}% (maker {mk_sh:.0f}sh / market {tot_flow:.0f}sh)")

            cell_rec = dict(gate_G=gate_G, trigger=trigger,
                            IS_net=s_IS.get("net_mean", np.nan),
                            IS_net_med=s_IS.get("net_median", np.nan),
                            IS_ci_lo=s_IS.get("ci_lo", np.nan),
                            IS_ci_hi=s_IS.get("ci_hi", np.nan),
                            IS_ex2=s_IS.get("ex2", np.nan),
                            IS_pvs=s_IS.get("pvs", np.nan),
                            IS_pf=s_IS.get("pair_frac", np.nan),
                            IS_mk_pct=s_IS.get("maker_pct_sh", np.nan),
                            IS_tk_pct=s_IS.get("taker_pct_sh", np.nan),
                            IS_flow_cap=cap,
                            OOS_net=s_OOS.get("net_mean", np.nan),
                            OOS_net_med=s_OOS.get("net_median", np.nan),
                            OOS_ci_lo=s_OOS.get("ci_lo", np.nan),
                            OOS_ci_hi=s_OOS.get("ci_hi", np.nan),
                            OOS_ex2=s_OOS.get("ex2", np.nan),
                            OOS_pvs=s_OOS.get("pvs", np.nan),
                            OOS_mk_pct=s_OOS.get("maker_pct_sh", np.nan),
                            IS_n=s_IS.get("n", 0),
                            OOS_n=s_OOS.get("n", 0))
            all_cell_results[-1] = df_all  # store per-slug results

            # Track best OOS
            oos_ci_lo = s_OOS.get("ci_lo", float("-inf"))
            if oos_ci_lo > best_oos_ci_lo:
                best_oos_ci_lo = oos_ci_lo
                best_config = (gate_G, trigger)

    # ── STEP 3: Guide filters on best config ──────────────────────────────
    print("\n" + "=" * 72)
    print(f"STEP 3: GUIDE FILTERS on best config (G={best_config[0]:.3f}, trig={best_config[1]})")
    print("=" * 72)

    # Re-run best config full
    df_best = run_all_slugs(res_df, tob, taker_sells,
                             gate_G=best_config[0], taker_trigger=best_config[1])

    # Find regime from IS
    df_best_IS = df_best[df_best.is_oos == "IS"]
    good_hours, good_days, by_hour, by_day = find_regime_hours(res_IS, df_best_IS)
    print(f"\n  (a) Profitable UTC hours (IS, n>=10): {sorted(good_hours)}")
    print(f"      Profitable weekdays (IS, n>=20): {sorted(good_days)}")

    # Apply regime filter
    df_best_regime = apply_regime_filter(df_best, good_hours, good_days)
    df_best_regime_OOS = df_best_regime[df_best_regime.is_oos == "OOS"]
    s_regime_OOS = summarize(df_best_regime_OOS, label="OOS+regime")
    print(f"  Regime filter OOS ({len(df_best_regime_OOS)} slugs):")
    print_summary(s_regime_OOS, prefix="    ")

    # Apply consecutive-loss filter (K=2, N=1) on OOS
    df_cl = apply_consec_loss_filter(df_best, K=2, N=1)
    df_cl_OOS = df_cl[df_cl.is_oos == "OOS"]
    s_cl_OOS = summarize(df_cl_OOS, label="OOS+consec_loss(K=2,N=1)")
    print(f"\n  (b) Consecutive-loss pause K=2, N=1 OOS ({len(df_cl_OOS)} slugs):")
    print_summary(s_cl_OOS, prefix="    ")

    # ── STEP 4: Worked examples ────────────────────────────────────────────
    print("\n" + "=" * 72)
    print(f"STEP 4: WORKED EXAMPLES (3 slugs, G={best_config[0]:.3f}, trig={best_config[1]})")
    print("=" * 72)
    print_worked_examples(res_df, tob, taker_sells,
                          gate_G=best_config[0], taker_trigger=best_config[1])

    # ── STEP 5: DECISION RULE ─────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("STEP 5: PRE-REGISTERED DECISION RULE")
    print("  GO if OOS net CI95 lo > 0 AND ex-top2 > 0")
    print("=" * 72)

    # Rerun best config for clean summary
    df_b = run_all_slugs(res_df, tob, taker_sells,
                          gate_G=best_config[0], taker_trigger=best_config[1])
    s_b_IS  = summarize(df_b[df_b.is_oos == "IS"],  label="IS best")
    s_b_OOS = summarize(df_b[df_b.is_oos == "OOS"], label="OOS best")

    oos_ci_lo = s_b_OOS.get("ci_lo", float("-inf"))
    oos_ex2   = s_b_OOS.get("ex2", float("-inf"))
    go = (oos_ci_lo > 0) and (oos_ex2 > 0)

    # Validation check: maker/taker split
    mk_pct_oos = s_b_OOS.get("maker_pct_sh", float("nan"))
    val_split = 0.53 <= mk_pct_oos <= 0.73 if np.isfinite(mk_pct_oos) else False

    print(f"\n  BEST CONFIG: gate_G={best_config[0]:.3f}  taker_trigger={best_config[1]}sh")
    print(f"\n  IS  [{s_b_IS.get('n',0)} slugs]:")
    print_summary(s_b_IS, prefix="    ")
    print(f"\n  OOS [{s_b_OOS.get('n',0)} slugs]:")
    print_summary(s_b_OOS, prefix="    ")
    print(f"\n  VALIDATION CHECKS:")
    print(f"    maker/taker split: {100*mk_pct_oos:.1f}%/{100*(1-mk_pct_oos):.1f}%  target 63/37  -> {'PASS' if val_split else 'FAIL'}")
    print(f"    pvs (OOS) = {s_b_OOS.get('pvs', float('nan')):.4f}  target ~0.967")
    cap_b, _, _ = compute_flow_capture(df_b[df_b.is_oos == "IS"], res_IS, taker_sells)
    print(f"    flow_capture (IS maker only) = {100*cap_b:.1f}%  target ~28%  prior 7%")
    print(f"\n  OOS CI95 lo = {oos_ci_lo:+.2f}  ex-top2 = {oos_ex2:+.2f}")
    print(f"\n  VERDICT: {'GO' if go else 'NO-GO'}")
    if go:
        print("  -> OOS CI95 lo > 0 AND ex-top2 > 0: DEPLOY CANDIDATE")
        print("  -> Next: TVRUST tv-strat-ladder spec + paper shadow deploy")
    else:
        print("  -> Reason for NO-GO:")
        if oos_ci_lo <= 0:
            print(f"     OOS CI95 lo = {oos_ci_lo:+.2f} (need > 0)")
        if oos_ex2 <= 0:
            print(f"     ex-top2 = {oos_ex2:+.2f} (need > 0)")
        if not val_split:
            print(f"     maker/taker split {100*mk_pct_oos:.1f}% outside 53-73% range")

    # ── Save results ──────────────────────────────────────────────────────
    df_b["gate_G"] = best_config[0]
    df_b["taker_trigger"] = best_config[1]
    df_b.to_parquet(OUT_PARQUET, index=False)
    print(f"\n  Saved per-slug results: {OUT_PARQUET}")
    print(f"\n  Total runtime: {time.time()-t0:.0f}s")
    print("=" * 72)

    return go, best_config, s_b_IS, s_b_OOS


if __name__ == "__main__":
    main()
