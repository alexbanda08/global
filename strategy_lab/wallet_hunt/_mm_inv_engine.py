"""
_mm_inv_engine.py — MM backtest engine v2: inventory management + throughput.

Adds the two mechanics omitted from the strawman (_mm_queue_engine.py):
  1. INVENTORY MANAGEMENT (b945's #1 documented mechanic):
     (a) GLT hard cap: when |sh_up - sh_dn| > Q, STOP quoting the heavy side until the
         light side catches up. Grid Q in {20, 50, 100, inf}.
     (b) AS reservation-price skew: skew each side's bid by -q*gamma*sigma^2*(T-t),
         where q = net residual (favor the light side). Grid gamma in {0, 0.05, 0.1}.
  2. THROUGHPUT: budget per side in {100, 350} (b945 median = $332/side), full-band
     quoting (NO 0.85 cap — b945 fills above 0.85 11.8% of the time), $5 clips, re-entry.

The two sides are simulated JOINTLY (not independently) because inventory mgmt couples them:
the cap/skew on Up depends on how much Down has filled at that instant. So we run a single
merged event loop over BOTH tokens' books + trades, tracking sh_up and sh_dn live.

GROUND TRUTH (from per_slug_paired_ledger.parquet, btc-15m, n=1564):
  pvs median 0.9674 | vwap_up 0.466 vwap_dn 0.490 | pair_frac median 0.912 mean 0.872
  fills/side median 44 (total median 88, mean 92) | sh/side median 760
  usd/side median $332 | gt_pnl median +$3.18 mean +$4.08 (sum +$6,378)
  paired_gain median +$17.6, residual drag median -$10.9 -> net +$3.2

VALIDATION GATE (HARD, pre-registered, BEFORE any placement sweep):
  On 200-slug sample at -3600s, does ANY config reach
    pvs >= 0.95 AND fills/side >= 60 AND net >= +$3/slug (b945's own median)?
  (Gate spec asked +$6/slug, which is ABOVE b945's own +$3.18 median — report both.)
  Grid: Q in {20,50,100,inf} x gamma in {0,0.05,0.1} x budget in {100,350} = 24 cells.
"""

import sys
import time
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
L25_PATH  = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / "btc.parquet"
TR_PATH   = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / "btc.parquet"
RES_PATH  = ROOT / "data" / "v4" / "canonical" / "resolutions.parquet"
RTDS_PATH = ROOT / "data" / "v4" / "canonical" / "chainlink_rtds.parquet"
TAPE_PATH = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xb945945d" / "fill_tape_full.parquet"
CACHE_DIR = ROOT / "strategy_lab" / "wallet_hunt" / "cache"
REPORT_PATH = ROOT / "strategy_lab" / "reports" / "MM_ENGINE_QUEUE_REPLAY_2026_06_12.md"

sys.path.insert(0, str(ROOT / "strategy_lab" / "directional"))
try:
    from scalp_fill_lib_2026_06_10 import boot
except ImportError:
    def boot(v, nb=1000):
        rng = np.random.default_rng(42)
        v = np.asarray(v, float)
        means = [v[rng.integers(0, len(v), len(v))].mean() for _ in range(nb)]
        return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))

RNG = np.random.default_rng(42)
WINDOW_S   = 900
REBATE_SH  = 0.0015
CLIP_USD   = 5.0
TICK       = 0.01
IS_CUTOFF_US = int(pd.Timestamp("2026-05-21", tz="UTC").timestamp() * 1e6)

# B945 ground-truth targets (from the ledger)
GT_PVS       = 0.9674
GT_FILLS_SD  = 44.0
GT_NET       = 3.18    # median gt_pnl/slug
GATE_PVS     = 0.95
GATE_FILLS   = 60
GATE_NET     = 3.0     # b945's own median; gate spec asked 6 (above his median)


# ══════════════════════════════════════════════════════════════════════════════
# DATA
# ══════════════════════════════════════════════════════════════════════════════

def load_resolutions():
    r = pd.read_parquet(RES_PATH, columns=["slug", "slot_start_us", "outcome"])
    r = r[r.slug.str.contains("btc-updown-15m", na=False, regex=False)]
    r = r[r.slot_start_us >= int(pd.Timestamp("2026-04-22", tz="UTC").timestamp() * 1e6)]
    r = r.drop_duplicates("slug")
    r["slot_start_s"] = (r["slot_start_us"] // 1_000_000).astype(int)
    return r.reset_index(drop=True)


def load_books(slug_set):
    """Returns dict (slug,outcome)->{ts, bp[5], bs[5]} (top-5 bid levels)."""
    bp_names = [f"bid_price_{i}" for i in range(5)]
    bs_names = [f"bid_size_{i}" for i in range(5)]
    cols = ["timestamp_us", "slug", "outcome"] + bp_names + bs_names
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
        }
    return out


def load_trades(slug_set):
    f = pq.ParquetFile(TR_PATH)
    parts = []
    for i in range(f.num_row_groups):
        df = f.read_row_group(i, columns=["timestamp_us", "slug", "outcome", "price", "size", "side"]).to_pandas()
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
# QUEUE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _qa_at(bk, at_us, level_price):
    """FIFO queue_ahead = sum bid_size at price >= level_price at time at_us."""
    ts = bk["ts"]; bp = bk["bp"]; bs = bk["bs"]
    j = max(0, min(int(np.searchsorted(ts, at_us, "right")) - 1, len(ts) - 1))
    qa = 0.0
    for lvl in range(5):
        p = bp[j, lvl]; s = bs[j, lvl]
        if not np.isfinite(p):
            break
        if p > level_price + 1e-6:
            if np.isfinite(s) and s > 0:
                qa += s
        elif abs(p - level_price) < 1e-6:
            if np.isfinite(s) and s > 0:
                qa += s
            break
        else:
            break
    return qa


def _bid_at(bk, at_us):
    ts = bk["ts"]; bp = bk["bp"]
    j = max(0, min(int(np.searchsorted(ts, at_us, "right")) - 1, len(ts) - 1))
    p = bp[j, 0]
    return float(p) if np.isfinite(p) else float("nan")


# ══════════════════════════════════════════════════════════════════════════════
# JOINT TWO-SIDED SIM WITH INVENTORY MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def sim_slug(bk_up, tr_up, bk_dn, tr_dn, slot_s, offset_s, budget, Q_cap, gamma,
             use_upper=False, sigma=0.5):
    """
    Joint simulation of both tokens with shared inventory state.

    Inventory mgmt:
      (a) GLT cap: if (sh_heavy - sh_light) > Q_cap, pause quoting the heavy side.
      (b) AS skew: bid_skewed = bid - q*gamma*sigma^2*(T-t)/T, where q = signed net
          residual (sh_this - sh_other) normalized. A positive net on THIS side pushes
          our bid DOWN (quote less aggressively on the heavy side). T-t = time to resolution.

    Returns dict with sh_up, sh_dn, cost_up, cost_dn, n_fills_up, n_fills_dn, qa_up, qa_dn.
    """
    t_place = (slot_s + offset_s) * 1_000_000
    t_end   = (slot_s + WINDOW_S) * 1_000_000
    slot_us = slot_s * 1_000_000

    # State per side
    sides = {}
    for tag, bk in (("up", bk_up), ("dn", bk_dn)):
        if bk is None:
            sides[tag] = None
            continue
        init_bid = _bid_at(bk, t_place)
        if not np.isfinite(init_bid) or init_bid <= 0:
            sides[tag] = None
            continue
        op = init_bid  # NO max-price cap: b945 quotes the full band
        sides[tag] = {
            "bk": bk,
            "order_price": op,
            "order_qa": _qa_at(bk, t_place, op),
            "remaining": min(CLIP_USD, budget) / op,
            "budget_left": budget,
            "cur_bid": init_bid,
            "sh": 0.0, "cost": 0.0, "n_fills": 0, "n_req": 0,
            "qa_place": _qa_at(bk, t_place, op),
            "active": True,   # toggled by GLT cap
        }

    # Build merged event stream: (ts, kind, tag, payload)
    # kind 0=book, 1=trade. We iterate by global ts order.
    events = []
    for tag, bk, tr in (("up", bk_up, tr_up), ("dn", bk_dn, tr_dn)):
        if bk is not None:
            ts = bk["ts"]; bp0 = bk["bp"][:, 0]
            lo = int(np.searchsorted(ts, t_place, "left"))
            hi = int(np.searchsorted(ts, t_end, "right"))
            for k in range(lo, hi):
                events.append((int(ts[k]), 0, tag, float(bp0[k])))
        if tr is not None:
            ts = tr["ts"]; px = tr["px"]; sz = tr["sz"]
            lo = int(np.searchsorted(ts, t_place, "left"))
            hi = int(np.searchsorted(ts, t_end, "right"))
            for k in range(lo, hi):
                events.append((int(ts[k]), 1, tag, (float(px[k]), float(sz[k]))))
    events.sort(key=lambda e: (e[0], e[1]))  # ts, then book(0) before trade(1)

    def net_residual(tag):
        """Signed share imbalance on this side (positive = this side heavier)."""
        other = "dn" if tag == "up" else "up"
        s_this = sides[tag]["sh"] if sides[tag] else 0.0
        s_other = sides[other]["sh"] if sides[other] else 0.0
        return s_this - s_other

    def apply_glt(tag):
        """GLT hard cap: pause heavy side if imbalance > Q_cap."""
        if not np.isfinite(Q_cap):
            return
        q = net_residual(tag)
        if sides[tag]:
            # If THIS side is heavier than the other by > Q_cap, pause it.
            sides[tag]["active"] = (q <= Q_cap)

    def skewed_price(tag, base_bid, ev_ts):
        """AS reservation-price skew: lower our bid on the heavy side."""
        if gamma <= 0:
            return min(base_bid, 0.99)
        q = net_residual(tag)  # shares; positive = heavy
        # Normalize q by a reference clip count (~clip shares) to keep skew in ticks
        time_left = max(0.0, (t_end - ev_ts) / (WINDOW_S * 1_000_000))
        # skew in price units: -q_norm * gamma * sigma^2 * time_left
        # scale q by 100 sh reference so a 100-sh imbalance at gamma=0.1, sigma=0.5,
        # full time -> 0.1*0.25*1*1 = 0.025 price units (2.5 ticks)
        q_norm = q / 100.0
        skew = -q_norm * gamma * (sigma ** 2) * time_left
        p = base_bid + skew
        return min(max(p, 0.01), 0.99)

    # Process events
    for ev_ts, kind, tag, payload in events:
        s = sides[tag]
        if s is None:
            continue

        if kind == 0:
            # book update
            new_bid = payload
            if np.isfinite(new_bid) and new_bid > 0 and abs(new_bid - s["cur_bid"]) > 1e-6:
                base = new_bid
                nl = skewed_price(tag, base, ev_ts)
                if abs(nl - s["order_price"]) > 1e-6 and s["remaining"] > 1e-6:
                    carry = s["remaining"] * s["order_price"]
                    s["order_price"] = nl
                    s["remaining"] = carry / nl
                    s["order_qa"] = _qa_at(s["bk"], ev_ts, nl)
                    s["n_req"] += 1
                s["cur_bid"] = new_bid
            # refresh GLT active state on book ticks too
            apply_glt(tag)
        else:
            # trade event
            tp, ts2 = payload
            apply_glt(tag)
            if not s["active"] or s["remaining"] <= 1e-6 or s["budget_left"] <= 1e-6:
                continue
            fa = 0.0
            op = s["order_price"]
            if tp < op - 1e-6:
                fa = min(s["remaining"], ts2)
            elif abs(tp - op) < 1e-6:
                if use_upper:
                    denom = max(s["remaining"] + s["order_qa"], 1e-9)
                    fa = min(s["remaining"], ts2 * s["remaining"] / denom)
                    s["order_qa"] = max(0.0, s["order_qa"] - ts2 * s["order_qa"] / denom)
                else:
                    if s["order_qa"] >= ts2:
                        s["order_qa"] -= ts2
                    else:
                        fa = min(s["remaining"], ts2 - s["order_qa"])
                        s["order_qa"] = 0.0
            if fa > 1e-9:
                s["sh"] += fa
                s["cost"] += fa * op
                s["remaining"] -= fa
                s["budget_left"] -= fa * op
                s["n_fills"] += 1
                # re-enter at current best bid (skewed) after clip depletes
                if s["remaining"] <= 1e-6 and s["budget_left"] > 1e-6:
                    nl = skewed_price(tag, s["cur_bid"], ev_ts)
                    s["order_price"] = nl
                    s["remaining"] = min(CLIP_USD, s["budget_left"]) / nl
                    s["order_qa"] = 0.0  # fresh re-entry at tail
                apply_glt(tag)
                # re-activate the OTHER side if this fill rebalanced it
                other = "dn" if tag == "up" else "up"
                if sides[other]:
                    apply_glt(other)

    out = {}
    for tag in ("up", "dn"):
        s = sides[tag]
        if s is None:
            out[f"sh_{tag}"] = 0.0; out[f"cost_{tag}"] = 0.0
            out[f"vwap_{tag}"] = float("nan"); out[f"n_fills_{tag}"] = 0
            out[f"qa_{tag}"] = float("inf")
        else:
            out[f"sh_{tag}"] = s["sh"]; out[f"cost_{tag}"] = s["cost"]
            out[f"vwap_{tag}"] = s["cost"] / s["sh"] if s["sh"] > 0 else float("nan")
            out[f"n_fills_{tag}"] = s["n_fills"]
            out[f"qa_{tag}"] = s["qa_place"]
    return out


def slug_pnl(o, won_up):
    sh_up = o["sh_up"]; sh_dn = o["sh_dn"]
    vw_up = o["vwap_up"]; vw_dn = o["vwap_dn"]
    if sh_up <= 0 and sh_dn <= 0:
        return dict(sh_up=0., sh_dn=0., vwap_up=np.nan, vwap_dn=np.nan, paired=0.,
                    pvs=np.nan, pair_frac=0., paired_pnl=0., residual_pnl=0.,
                    rebate_pnl=0., net_pnl=0., both_sides=False)
    paired = min(sh_up, sh_dn)
    pvs = (vw_up if np.isfinite(vw_up) else 0.) + (vw_dn if np.isfinite(vw_dn) else 0.)
    tot = sh_up + sh_dn
    pf = 2 * paired / tot if tot > 0 else 0.
    paired_pnl = paired * (1. - pvs) if np.isfinite(pvs) else 0.
    resid_up = sh_up - paired; resid_dn = sh_dn - paired
    vu = vw_up if np.isfinite(vw_up) else 0.
    vd = vw_dn if np.isfinite(vw_dn) else 0.
    if won_up:
        res = resid_up * (1. - vu) - resid_dn * vd
    else:
        res = resid_dn * (1. - vd) - resid_up * vu
    rebate = (sh_up + sh_dn) * REBATE_SH
    net = paired_pnl + res + rebate
    return dict(sh_up=sh_up, sh_dn=sh_dn, vwap_up=vw_up, vwap_dn=vw_dn, paired=paired,
                pvs=pvs, pair_frac=pf, paired_pnl=paired_pnl, residual_pnl=res,
                rebate_pnl=rebate, net_pnl=net, both_sides=(sh_up > 0 and sh_dn > 0))


# ══════════════════════════════════════════════════════════════════════════════
# VALIDATION GRID
# ══════════════════════════════════════════════════════════════════════════════

def run_validation_grid(res_df, tob, trades, sample_n=200, offset_s=-3600):
    """
    Pre-registered grid: Q in {20,50,100,inf} x gamma in {0,0.05,0.1} x budget in {100,350}
    = 24 cells. At offset -3600s on a 200-slug sample. FIFO lower bound.
    Find ANY config reaching pvs>=0.95 AND fills/side>=60 AND net>=+$3/slug.
    """
    print(f"\n{'='*70}\nVALIDATION GRID (pre-registered, 24 cells, FIFO, offset={offset_s}s)\n{'='*70}")
    print(f"B945 ground truth: pvs={GT_PVS:.3f} fills/side={GT_FILLS_SD:.0f} net=+${GT_NET:.2f}/slug")
    print(f"Gate: pvs>={GATE_PVS} AND fills/side>={GATE_FILLS} AND net>=+${GATE_NET:.0f}/slug\n")

    slot_map    = dict(zip(res_df["slug"], res_df["slot_start_s"]))
    outcome_map = dict(zip(res_df["slug"], res_df["outcome"]))
    all_slugs = sorted(res_df["slug"].tolist())
    if len(all_slugs) > sample_n:
        rng = np.random.default_rng(7)
        sample = list(rng.choice(all_slugs, sample_n, replace=False))
    else:
        sample = all_slugs

    Q_grid = [20, 50, 100, float("inf")]
    gamma_grid = [0.0, 0.05, 0.1]
    budget_grid = [100.0, 350.0]

    cells = []
    t0 = time.time()
    for budget in budget_grid:
        for Q in Q_grid:
            for gamma in gamma_grid:
                recs = []
                for slug in sample:
                    slot_s = slot_map.get(slug)
                    if slot_s is None:
                        continue
                    won_up = str(outcome_map.get(slug, "")).lower() == "up"
                    o = sim_slug(tob.get((slug, "Up")), trades.get((slug, "Up")),
                                 tob.get((slug, "Down")), trades.get((slug, "Down")),
                                 slot_s, offset_s, budget, Q, gamma, use_upper=False)
                    p = slug_pnl(o, won_up)
                    p["n_fills_up"] = o["n_fills_up"]; p["n_fills_dn"] = o["n_fills_dn"]
                    recs.append(p)
                R = pd.DataFrame(recs)
                fi = R[(R.sh_up > 0) | (R.sh_dn > 0)]
                if len(fi) == 0:
                    continue
                tot = fi.sh_up.sum() + fi.sh_dn.sum()
                pf = 2 * fi.paired.sum() / tot if tot > 0 else 0
                pvs = fi[fi.pvs.notna()].pvs.median()
                fills_sd = (fi.n_fills_up + fi.n_fills_dn).mean() / 2
                net = fi.net_pnl.to_numpy()
                net_mean = net.mean()
                ci = boot(net, nb=2000)
                ex2 = net[np.argsort(np.abs(net))[:-2]].mean() if len(net) > 2 else np.nan
                Q_lbl = 999999 if not np.isfinite(Q) else int(Q)
                gate_pvs = pvs >= GATE_PVS
                gate_fl  = fills_sd >= GATE_FILLS
                gate_net = net_mean >= GATE_NET
                passed = gate_pvs and gate_fl and gate_net
                cells.append(dict(budget=budget, Q=Q_lbl, gamma=gamma, n=len(fi),
                                  pair_frac=pf, pvs=pvs, fills_sd=fills_sd,
                                  net=net_mean, ci_lo=ci[0], ci_hi=ci[1], ex2=ex2,
                                  pass_pvs=gate_pvs, pass_fills=gate_fl, pass_net=gate_net,
                                  passed=passed))
                flag = "  *** PASS ***" if passed else ""
                Q_disp = "inf" if Q_lbl == 999999 else str(Q_lbl)
                print(f"  bud={budget:.0f} Q={Q_disp:>3} g={gamma:.2f}: "
                      f"pf={100*pf:4.1f}% pvs={pvs:.3f} fills/sd={fills_sd:5.1f} "
                      f"net={net_mean:+6.2f} CI[{ci[0]:+.2f},{ci[1]:+.2f}] ex2={ex2:+6.2f}"
                      f"  [pvs{'Y' if gate_pvs else 'n'} fl{'Y' if gate_fl else 'n'} "
                      f"net{'Y' if gate_net else 'n'}]{flag}", flush=True)
    print(f"\n  grid time={time.time()-t0:.0f}s")
    return pd.DataFrame(cells)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--sweep", action="store_true")
    args = ap.parse_args()

    t0 = time.time()
    print("Loading resolutions...", flush=True)
    res_df = load_resolutions()
    print(f"  {len(res_df)} slugs")
    slug_set = set(res_df["slug"])
    print("Loading books...", flush=True)
    tob = load_books(slug_set)
    print(f"  {len(tob)} book series  t={time.time()-t0:.0f}s")
    print("Loading trades...", flush=True)
    trades = load_trades(slug_set)
    print(f"  {len(trades)} trade series  t={time.time()-t0:.0f}s")

    grid = run_validation_grid(res_df, tob, trades)
    grid.to_parquet(CACHE_DIR / "_mm_inv_validation_grid.parquet", index=False)
    print(f"\nSaved grid to _mm_inv_validation_grid.parquet")

    n_pass = grid["passed"].sum() if len(grid) else 0
    print(f"\n{'='*70}")
    if n_pass > 0:
        print(f"VALIDATION: {n_pass} config(s) PASS. Winners:")
        print(grid[grid["passed"]].to_string(index=False))
    else:
        print("VALIDATION: NO config cleared all 3 gates. Closest by each gate:")
        for g in ["pvs", "fills_sd", "net"]:
            best = grid.loc[grid[g].idxmax()]
            print(f"  max {g}: {best[g]:.3f} at bud={best['budget']:.0f} Q={best['Q']} gamma={best['gamma']}")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
