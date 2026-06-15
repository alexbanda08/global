"""
SCALP GATE-SOFTENING SWEEP — BNB / XRP / DOGE (2026-06-11).

Question: on the 3 new coins, if we loosen the spread filter (and/or the delta gate),
does the open exit-scalp edge SURVIVE (CI>0) or DIE?

Mirrors scalp_oos_bbo_fixed_2026_06_10.py conventions:
  - corrected fill lib scalp_fill_lib_2026_06_10 (entry_fill/exit_fill artifact-aware)
  - chunked BBO loading, +5s fire, $25 stake, +85ms latency, corrected +60s SELL exit
  - cheap gate ev<0.55 applied at ANALYSIS time
DIFFERENCES vs the OOS script:
  - COINS = BNB,XRP,DOGE only; windows = their 1s+BBO coverage.
  - CANDIDATES floor delta_bps>=2.0 (so delta in {2,3,5} is testable post-hoc).
  - FILL with spread=0.12 (loose) so all spreads<=0.12 fill; spread thresholds POST-HOC.
  - Record per fire: delta_bps, RAW spread at fire (ask-bid pre-filter), ev, won, pnl60, frac_held.
  - ANALYSIS: matrix spread_max in {0.05,0.06,0.07,0.08,0.10,0.12} x delta_min in {2,3,5},
    each cell n/$tr/t/bootstrap CI, ALL and CLEAN(frac_held==0). Plus the INCREMENTAL band
    row spread in (0.05, X] — the decisive marginal-fire cell. Plus delta in [2,3) incremental.
  - Live-volume estimate from the stated skip histograms.

Checkpoint parquet: _results/scalp_gate_soften_2026_06_11.parquet
"""
import sys, os, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_bbo
from scalp_fill_lib_2026_06_10 import entry_fill, exit_fill, boot, cell
CANON = ROOT / "data/v4/canonical"
RES = ROOT / "strategy_lab/directional/_results"
RES.mkdir(parents=True, exist_ok=True)
LOOSE_SPREAD = 0.12; STAKE = 25.0; LAT_US = 85_000
DELTA_FLOOR = 2.0

COINS = ["BNB", "XRP", "DOGE"]
WIN = {"BNB": ("2026-04-06", "2026-04-21"), "DOGE": ("2026-04-06", "2026-04-21"),
       "XRP": ("2026-04-07", "2026-04-21")}
CKPT = RES / "scalp_gate_soften_2026_06_11.parquet"
SPREAD_GRID = [0.05, 0.06, 0.07, 0.08, 0.10, 0.12]
DELTA_GRID = [2, 3, 5]

# Live skip histograms (last 30h, stated by operator). Spread medians/deciles for new coins:
#   BNB p50~0.14 (spread 0.06-0.25+), DOGE p50~0.11, XRP p50~0.08, XRP p10=0.05.
# spread-skip counts (joint never passes spread<=0.05 & d>=3):
LIVE = {"BNB": dict(spread_skips=234, lag_skips=33, p50=0.14, p10=None),
        "DOGE": dict(spread_skips=192, lag_skips=70, p50=0.11, p10=None),
        "XRP": dict(spread_skips=52, lag_skips=203, sparse=13, p50=0.08, p10=0.05)}
HOURS = 30.0


def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    # CAUSAL FIX 2026-06-13: index on bar END (start+1s). A 1s bar realizes its close at end;
    # asof must return the bar whose END<=t. Bar-START indexing = ~1s lookahead (see
    # scalp_causal_asof_oneshot_2026_06_12: inflated pooled gated $/tr +1.71->+1.01).
    starts = df.time_period_start_us.values.astype("int64")
    return starts + 1_000_000, df.price_close.values.astype(float)


def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)


def raw_spread_at(ts, ask, bid, fire_us):
    """ask-bid at the entry-quote row (asof fire+LAT), pre-filter. nan if no usable quote."""
    je = np.searchsorted(ts, fire_us + LAT_US, "right") - 1
    if je < 0 or je >= len(ts):
        return np.nan
    a0, b0 = ask[je], bid[je]
    if not (np.isfinite(a0) and np.isfinite(b0)):
        return np.nan
    return float(round(float(a0 - b0), 4))


res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"]) & res.timeframe.isin(["5m", "15m"])].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]

ALL_FIRES = []
for coin in COINS:
    lo = pd.Timestamp(WIN[coin][0], tz="UTC").value // 1000
    hi = pd.Timestamp(WIN[coin][1], tz="UTC").value // 1000
    d = res[(res.ticker == coin) & (res.slot_start_us >= lo) & (res.slot_start_us <= hi)].copy()
    if not len(d):
        print(f"\n=== {coin}: no slugs in window ==="); continue
    be, bc = unified_1s(coin)
    ss = d.slot_start_us.values
    ret = asof(be, bc, ss + 5_000_000) / asof(be, bc, ss) - 1.0
    d = d.assign(fire_us=ss + 5_000_000, slot_end=d.slot_end_us.values, ret=ret,
                 delta_bps=np.abs(ret) * 1e4, lead=np.where(ret > 0, "Up", "Down"))
    d = d[np.isfinite(d.ret) & (d.delta_bps >= DELTA_FLOOR)].reset_index(drop=True)
    print(f"\n=== {coin} {WIN[coin][0]}..{WIN[coin][1]}: candidate fires (delta>={DELTA_FLOOR}) "
          f"= {len(d)} (tfs 15m+5m) ===", flush=True)
    recs = []; slugs = d.slug.tolist(); B = 120
    for i in range(0, len(slugs), B):
        chunk = d.iloc[i:i + B]
        cmin = int(chunk.fire_us.min()) - 2_000_000; cmax = int(chunk.slot_end.max()) + 2_000_000
        bbo = load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
        bk = {}
        for (sl, oc), g in bbo.groupby(["slug", "outcome"]):
            g = g.sort_values("timestamp_us")
            bk[(sl, oc)] = (g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                            g.best_bid.values.astype(float), g.best_ask_size.values.astype(float),
                            g.best_bid_size.values.astype(float))
        for _, r in chunk.iterrows():
            key = (r.slug, r.lead)
            if key not in bk: continue
            ts, ask, bid, asz, bsz = bk[key]
            won = (r.ret > 0) == (r.outcome == "Up")
            raw_sp = raw_spread_at(ts, ask, bid, int(r.fire_us))
            ent = entry_fill(ts, ask, asz, int(r.fire_us) + LAT_US, STAKE, LOOSE_SPREAD, bid)
            if ent is None: continue
            ev = ent["ev"]; shares = ent["shares"]; eidx = ent["entry_idx"]
            ext = min(int(r.fire_us) + 60_000_000, int(r.slot_end))
            ef = exit_fill(ts, bid, bsz, eidx, ext, shares, ev, won)
            hour = (int(r.fire_us) // 1_000_000 % 86_400) // 3600
            recs.append(dict(coin=coin, tf=r.timeframe, fire_us=int(r.fire_us), hour=hour,
                             ev=ev, won=won, pnl60=ef["pnl"], frac_held=ef["frac_held"],
                             held_full=ef["held_full"], delta_bps=float(r.delta_bps),
                             raw_spread=raw_sp,
                             entry_size_carried=ent["entry_size_carried"],
                             exit_size_carried=ef["exit_size_carried"]))
        del bbo, bk
    F = pd.DataFrame(recs)
    ALL_FIRES.extend(recs)
    print(f"  filled fires: {len(F)} (of {len(d)} candidates)")
    if len(F):
        print(f"  raw_spread: p10={F.raw_spread.quantile(.1):.3f} p50={F.raw_spread.median():.3f} "
              f"p90={F.raw_spread.quantile(.9):.3f}  frac<=0.05={ (F.raw_spread<=0.05).mean():.3f} "
              f"frac<=0.08={(F.raw_spread<=0.08).mean():.3f}")
        print(f"  frac_held mean={F.frac_held.mean():.3f}  clean(frac==0)={(F.frac_held==0).mean():.3f}")

A = pd.DataFrame(ALL_FIRES)
A.to_parquet(CKPT)
print(f"\n[checkpoint] {len(A)} fires -> {CKPT}")


# ============================ ANALYSIS ============================
def cellrow(sub):
    """one matrix cell -> (n, $tr, t, lo, hi) ALL."""
    v = sub.pnl60.values
    v = v[np.isfinite(v)]
    if len(v) < 5:
        return (len(v), np.nan, np.nan, np.nan, np.nan)
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan
    lo, hi = boot(v)
    return (len(v), v.mean(), t, lo, hi)


def fmt(tup):
    n, m, t, lo, hi = tup
    if not np.isfinite(m):
        return f"n={n:4d} (few)"
    return f"n={n:4d} $tr={m:+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]"


def verdict_safe(inc_tup, cum_clean_tup):
    """SAFE iff incremental band $/tr>=0 (CI not sig-neg) AND cumulative CLEAN CI>0."""
    _, inc_m, _, inc_lo, inc_hi = inc_tup
    _, _, _, cum_lo, _ = cum_clean_tup
    inc_ok = np.isfinite(inc_m) and (inc_m >= 0) and not (np.isfinite(inc_hi) and inc_hi < 0)
    cum_ok = np.isfinite(cum_lo) and cum_lo > 0
    return inc_ok and cum_ok


MD = ["# GATE-SOFTENING SWEEP — BNB / XRP / DOGE (2026-06-11)\n",
      "Open exit-scalp (fire slot_start+5s on binance-moved side, $25 @ best_ask +85ms, "
      "corrected +60s SELL exit). Cheap gate ev<0.55 applied. BBO window = Apr 2026 regime.\n",
      "**Question:** loosening the spread filter (and/or delta gate) — does the edge survive (CI>0) or die?\n",
      "\n**Pre-registered verdict rule:** soften to spread_max=X is SAFE for a coin iff the "
      "INCREMENTAL band (0.05,X] cell has $/tr >= 0 (CI not sig-negative) AND the cumulative cell "
      "at X keeps CI>0 (CLEAN). Delta floor stays 3 unless delta in [2,3) incremental is CI>0.\n"]

per_coin_summary = {}
for coin in COINS:
    G0 = A[(A.coin == coin) & (A.ev < 0.55)].copy()
    print(f"\n{'='*70}\n{coin}  gated ev<0.55  n={len(G0)}\n{'='*70}")
    MD.append(f"\n## {coin}  (gated ev<0.55, n={len(G0)})\n")
    if len(G0) < 5:
        print("  too few fires"); MD.append("Too few fires — coin untradeable on this data.\n")
        per_coin_summary[coin] = ("untradeable", np.nan, "n/a"); continue

    # ---- matrix spread_max x delta_min : ALL then CLEAN ----
    for clean_lab, dfc in [("ALL", G0), ("CLEAN (frac_held==0)", G0[G0.frac_held == 0])]:
        print(f"\n  --- {coin} matrix [{clean_lab}] ---")
        MD.append(f"\n### {coin} matrix — {clean_lab}\n")
        MD.append("| spread<= \\ delta>= | " + " | ".join(f"d{d}" for d in DELTA_GRID) + " |")
        MD.append("|---|" + "---|" * len(DELTA_GRID))
        for sm in SPREAD_GRID:
            cells = []
            for dm in DELTA_GRID:
                sub = dfc[(dfc.raw_spread <= sm) & (dfc.delta_bps >= dm)]
                t = cellrow(sub)
                cells.append(fmt(t))
            print(f"    spread<={sm:.2f}: " + "  ||  ".join(cells))
            MD.append(f"| spread<={sm:.2f} | " + " | ".join(cells) + " |")

    # ---- incremental band rows (delta>=3 baseline) ----
    print(f"\n  --- {coin} INCREMENTAL spread bands (delta>=3) ---")
    MD.append(f"\n### {coin} INCREMENTAL spread bands (delta>=3) — the decisive marginal-fire cell\n")
    MD.append("| band | ALL | CLEAN |")
    MD.append("|---|---|---|")
    d3 = G0[G0.delta_bps >= 3]
    d3c = d3[d3.frac_held == 0]
    inc_band_tups = {}
    for blo, bhi in [(0.00, 0.05), (0.05, 0.06), (0.05, 0.07), (0.05, 0.08), (0.05, 0.10), (0.05, 0.12)]:
        sub_all = d3[(d3.raw_spread > blo) & (d3.raw_spread <= bhi)] if blo > 0 \
            else d3[d3.raw_spread <= bhi]
        sub_cln = d3c[(d3c.raw_spread > blo) & (d3c.raw_spread <= bhi)] if blo > 0 \
            else d3c[d3c.raw_spread <= bhi]
        ta, tc = cellrow(sub_all), cellrow(sub_cln)
        if blo > 0:
            inc_band_tups[bhi] = (ta, tc)
        lbl = f"(<= {bhi:.2f}] baseline" if blo == 0 else f"({blo:.2f}, {bhi:.2f}]"
        print(f"    {lbl:18s} ALL {fmt(ta)}   CLEAN {fmt(tc)}")
        MD.append(f"| {lbl} | {fmt(ta)} | {fmt(tc)} |")

    # ---- delta in [2,3) incremental (does loosening delta help?) ----
    print(f"\n  --- {coin} DELTA [2,3) incremental (spread<=0.05) ---")
    d23 = G0[(G0.delta_bps >= 2) & (G0.delta_bps < 3) & (G0.raw_spread <= 0.05)]
    d23c = d23[d23.frac_held == 0]
    t23a, t23c = cellrow(d23), cellrow(d23c)
    print(f"    delta[2,3) spread<=0.05  ALL {fmt(t23a)}   CLEAN {fmt(t23c)}")
    MD.append(f"\n### {coin} delta [2,3) incremental (spread<=0.05)\n")
    MD.append(f"- ALL: {fmt(t23a)}\n- CLEAN: {fmt(t23c)}\n")
    delta23_helps = np.isfinite(t23a[3]) and t23a[3] > 0  # lo CI > 0

    # ---- per-coin recommendation ----
    cum_clean = {sm: cellrow(d3c[d3c.raw_spread <= sm]) for sm in SPREAD_GRID}
    rec_x = None
    for X in [0.06, 0.07, 0.08, 0.10, 0.12]:
        if X in inc_band_tups and verdict_safe(inc_band_tups[X][0], cum_clean[X]):
            rec_x = X  # keep widening as long as safe
    base_clean = cum_clean[0.05]
    base_ok = np.isfinite(base_clean[3]) and base_clean[3] > 0
    if rec_x is not None:
        rec = f"soften to spread_max={rec_x:.2f}"
        inc_dtr = inc_band_tups[rec_x][0][1]
    elif base_ok:
        rec = "keep 0.05 (no safe softening)"
        inc_dtr = inc_band_tups.get(0.06, ((0, np.nan, 0, 0, 0),))[0][1]
    else:
        rec = "coin UNTRADEABLE (even 0.05 CLEAN CI not >0)"
        inc_dtr = np.nan
    print(f"\n  >>> {coin} RECOMMENDATION: {rec}  (incremental band $/tr={inc_dtr:+.3f}) "
          f"delta[2,3) helps={delta23_helps}")
    MD.append(f"\n**{coin} recommendation: {rec}** — incremental band $/tr={inc_dtr:+.3f}; "
              f"delta in [2,3) helps = {delta23_helps}.\n")
    per_coin_summary[coin] = (rec, inc_dtr, delta23_helps)

    # ---- live-volume estimate ----
    lv = LIVE[coin]; ss = lv["spread_skips"]; p50 = lv["p50"]
    # approx fraction of spread-skips with spread<=X, crudely from a logistic around p50
    # (we only have median + a decile; linear-interp between known points, clamp [0,1]).
    pts = {0.05: 0.0, p50: 0.5}
    if lv.get("p10") is not None:
        pts[lv["p10"]] = 0.10
    print(f"\n  --- {coin} live-volume estimate (spread-skips={ss} in {HOURS}h, p50={p50}) ---")
    MD.append(f"\n### {coin} live-volume estimate (approx)\n")
    MD.append(f"spread-skips={ss} over {HOURS}h (~{ss/HOURS*24:.0f}/day). "
              f"Median skip spread p50={p50}"
              + (f", p10={lv['p10']}" if lv.get("p10") else "") + ".\n")
    MD.append("| spread_max | approx frac of skips <=X | extra evals/day |")
    MD.append("|---|---|---|")
    xs = sorted(set(pts.keys()))
    for X in SPREAD_GRID:
        if X <= 0.05:
            frac = 0.0
        elif X >= p50:
            frac = min(1.0, 0.5 + (X - p50) / (0.25 - p50) * 0.4) if X < 0.25 else 0.9
        else:
            # interp between nearest known points below/above X
            below = max([p for p in xs if p <= X], default=0.05)
            above = min([p for p in xs if p >= X], default=p50)
            fl, fh = pts.get(below, 0.0), pts.get(above, 0.5)
            frac = fl if above == below else fl + (fh - fl) * (X - below) / (above - below)
        frac = float(np.clip(frac, 0, 1))
        extra = ss / HOURS * 24 * frac
        MD.append(f"| {X:.2f} | {frac:.2f} | {extra:.0f} |")
    MD.append("(approximate — linear interp from stated median/decile; books today are WIDER "
              "than the Apr BBO window so live fill rate may be lower.)\n")

# ---- overall summary + caveats ----
MD.append("\n## Per-coin verdict summary\n")
MD.append("| coin | recommendation | incremental-band $/tr | delta[2,3) helps |")
MD.append("|---|---|---|---|")
for coin in COINS:
    rec, inc_dtr, d23h = per_coin_summary.get(coin, ("n/a", np.nan, "n/a"))
    inc_s = f"{inc_dtr:+.3f}" if isinstance(inc_dtr, float) and np.isfinite(inc_dtr) else "n/a"
    MD.append(f"| {coin} | {rec} | {inc_s} | {d23h} |")

MD.append("\n## Caveats\n"
          "- BBO window = Apr 6-21 2026 regime; **books today are WIDER** (live median +5s spreads "
          "BNB~0.14 / DOGE~0.11 / XRP~0.08), so the historical fill rate OVERSTATES live volume.\n"
          "- **Burned-window note:** Mar30-Apr21 OOS is partially burned per RETRO_MASTER_AUDIT_2026_06_10; "
          "treat magnitudes as hypotheses, not deploy-grade.\n"
          "- **Thin-book exit risk at wide spreads:** wide ask-spread fires tend to have thin bid depth "
          "at +60s -> higher frac_held / settlement-valued remainder; CLEAN(frac_held==0) is the honest bound.\n"
          "- BBO top-of-book fill (no L25 depth walk) -> entry slightly optimistic.\n"
          "- Incremental-band n can be small per coin -> CI wide; verdict conservative (requires CI not sig-neg).\n")

out = ROOT / "strategy_lab/reports/GATE_SOFTEN_BNB_XRP_DOGE_2026_06_11.md"
out.write_text("\n".join(MD), encoding="utf-8")
print(f"\n[report] {out}")
print("\n===== PER-COIN VERDICT =====")
for coin in COINS:
    rec, inc_dtr, d23h = per_coin_summary.get(coin, ("n/a", np.nan, "n/a"))
    inc_s = f"{inc_dtr:+.3f}" if isinstance(inc_dtr, float) and np.isfinite(inc_dtr) else "n/a"
    print(f"  {coin}: {rec}  (incremental-band $/tr={inc_s})  delta[2,3) helps={d23h}")
