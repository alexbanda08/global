"""
S4 ALL_15m_S4_prewindow + Kalshi variant backtest.
Window: Apr 24 00:00 → Jun 1 09:00 UTC. Assets: BTC/ETH/SOL. TF: 15m only.

Three fill variants per fire:
  A: poly_prewindow  = L25 walk at slot-120  (validated form, poly 0.07 fee)
  B: kalshi_inwin60  = L25 walk at slot+60   (Kalshi proxy, Kalshi 0.07 fee)
  C: kalshi_open     = L25 walk at slot+1    (earliest-open fallback, Kalshi 0.07 fee)

NOTE: Kalshi book not in canonical → proxy with Polymarket L25 at corresponding ts.
      State clearly as limitation. Both venues price the same binary off the same strike.

Regression battery: coverage, baseline repro (21d May 8–May 29), full period, per-asset,
per-direction, by-week walk-forward, causal-strike robustness.

Memory: load L25 ONE call per asset (subsample_1hz=True, bounded window), gc between assets.
1Hz OK for single-point entry. 15m slugs only keeps it tractable.

Usage:
  C:/Python314/python.exe strategy_lab/s4_backtest_2026_06_03/backtest.py
"""

import sys, math, gc
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
import numpy as np
import pandas as pd
from scipy import stats

from load import (load_resolutions, load_klines_1s, load_orderbook_l25_streaming)

# ── window ───────────────────────────────────────────────────────────────────
WIN_LO_US = int(pd.Timestamp("2026-04-24 00:00:00", tz="UTC").value // 1000)
WIN_HI_US = int(pd.Timestamp("2026-06-01 09:00:00", tz="UTC").value // 1000)

# 21-day "baseline" sub-window matching the validated n=229 / WR=54.6% / $2.26 reference
# The reference script used May 24-29; extend to the 21d panel described in spec (~May 8–May 29)
BASE_LO_US = int(pd.Timestamp("2026-05-08 00:00:00", tz="UTC").value // 1000)
BASE_HI_US = int(pd.Timestamp("2026-05-29 00:00:00", tz="UTC").value // 1000)

ASSETS = ["BTC", "ETH", "SOL"]
WINDOW_S = 900  # 15m
NOTIONAL = 25.0
OUT_DIR = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\s4_backtest_2026_06_03"

# ── feature helpers (verbatim from reference _bt_kelly_prewindow_v1.py) ──────
def _ema(values, span):
    if not values or span <= 0: return []
    a = 2.0 / (span + 1.0); out = []; prev = values[0]
    for v in values:
        prev = a * v + (1.0 - a) * prev; out.append(prev)
    return out

def _norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))

def fair_up_bsm(s_now, strike, sigma, tau_s):
    if not all(math.isfinite(x) for x in (s_now, strike, sigma, tau_s)):
        return None
    if s_now <= 0 or strike <= 0 or sigma <= 0 or tau_s <= 0:
        return None
    try:
        z = math.log(s_now / strike) / (sigma * math.sqrt(tau_s))
    except (ValueError, ArithmeticError):
        return None
    return _norm_cdf(z)

def cvd_agree(v, d):
    if v is None or not math.isfinite(v): return False
    return v > 0 if d == "UP" else (v < 0 if d == "DOWN" else False)

# ── 1s kline arrays ──────────────────────────────────────────────────────────
print("Loading 1s klines ...")
S1 = {}
for a in ASSETS:
    df = load_klines_1s(a)
    # pad 1300s before window for sigma lookback
    lo = WIN_LO_US - 1400 * 1_000_000
    hi = WIN_HI_US + 300 * 1_000_000
    df = df[(df.time_period_start_us >= lo) & (df.time_period_start_us <= hi)]
    df = df.drop_duplicates("time_period_start_us").sort_values("time_period_start_us")
    ts   = df.time_period_start_us.values.astype("int64")
    cls  = df.price_close.values.astype("float64")
    vol  = df.volume_traded.values.astype("float64")
    tbq  = df.taker_buy_quote.values.astype("float64")
    qv   = df.quote_volume.values.astype("float64")
    S1[a] = (ts, cls, vol, tbq, qv)
    print(f"  {a}: {len(ts)} bars  "
          f"{pd.to_datetime(ts.min()/1e6, unit='s', utc=True)} to "
          f"{pd.to_datetime(ts.max()/1e6, unit='s', utc=True)}")

def _slice(a, lo_us, hi_us):
    ts, cls, vol, tbq, qv = S1[a]
    i0 = np.searchsorted(ts, lo_us, side="left")
    i1 = np.searchsorted(ts, hi_us, side="right")
    return ts[i0:i1], cls[i0:i1], vol[i0:i1], tbq[i0:i1], qv[i0:i1]

def feat_at(a, fire_us, slot_start_us, slot_end_us, causal_strike=False):
    """
    Replicate S4 feature dict from canonical 1s bars.

    causal_strike=True → strike = binance close at fire_us (no lookahead).
    causal_strike=False → strike = first 1s close at-or-after slot_start_us
                           (matches reference script, but requires future price).
    """
    ts, cls, vol, tbq, qv = _slice(a, fire_us - 1400 * 1_000_000, fire_us + 2_000_000)
    if len(ts) == 0:
        return None
    m = ts <= fire_us
    ts_f = ts[m]; cls_f = cls[m]; vol_f = vol[m]; tbq_f = tbq[m]; qv_f = qv[m]
    if len(ts_f) == 0:
        return None

    # CVD 30s
    frm30 = fire_us - 30 * 1_000_000
    sel30 = ts_f >= frm30
    cvd_30s = float(np.sum(2.0 * tbq_f[sel30] - qv_f[sel30])) if sel30.sum() > 0 else None

    # sigma last 900s log-rets
    sg_frm = fire_us - 900 * 1_000_000
    sg_sel = ts_f >= sg_frm
    sigma = None
    cl_sg = cls_f[sg_sel]
    cl_sg = cl_sg[np.isfinite(cl_sg) & (cl_sg > 0)]
    if len(cl_sg) >= 31:
        rets = np.diff(np.log(cl_sg))
        rets = rets[np.isfinite(rets)]
        if len(rets) >= 30:
            var = rets.var(ddof=1)
            if var > 0:
                sigma = math.sqrt(var)

    # s_now = last close at-or-before fire_us
    s_now = float(cls_f[-1]) if len(cls_f) else None

    # strike
    if causal_strike:
        sk = s_now  # causal: use the same s_now we'd have at fire time
    else:
        # lookahead: first 1s close at-or-after slot_start_us
        ts_fwd, cls_fwd, _, _, _ = _slice(a, slot_start_us - 2 * 1_000_000, slot_start_us + 5 * 1_000_000)
        skm = ts_fwd >= slot_start_us
        if skm.any():
            sk = float(cls_fwd[skm][0])
        elif s_now is not None:
            sk = s_now
        else:
            sk = None

    # tau
    tau_s = (slot_end_us - fire_us) / 1_000_000.0
    if tau_s <= 0:
        tau_s = None

    # fair_up
    fu = fair_up_bsm(s_now, sk, sigma, tau_s) if (s_now and sk and sigma and tau_s) else None

    # VWAP-dev: 15m UTC bucket anchored, base-volume-weighted
    bk = (fire_us // (900 * 1_000_000)) * (900 * 1_000_000)
    v_sel = ts_f >= bk
    dev = None; vwap_val = None
    if v_sel.sum() > 0:
        cv = cls_f[v_sel]; vv = vol_f[v_sel]
        cumv = vv.sum()
        if cumv > 0:
            vwap_val = float((cv * vv).sum() / cumv)
            if vwap_val > 0 and s_now and s_now > 0:
                dev = 10000.0 * math.log(s_now / vwap_val)

    return dict(
        cvd_30s=cvd_30s, sigma=sigma, s_now=s_now, strike=sk,
        tau_s=tau_s, fair_up=fu, vwap_dev_bps=dev
    )

# ── L25 fill helpers (verbatim from reference) ───────────────────────────────
def walk_fill(books, slug, outcome, fire_us, notional):
    """L25 ask walk. Returns (avg_vwap, shares) or (None, None)."""
    rec = books.get((slug, outcome))
    if rec is None:
        return None, None
    ts, ap, asz, bp, bsz = rec
    i = np.searchsorted(ts, fire_us, side="right") - 1
    if i < 0:
        return None, None
    aprow = ap[i]; aszrow = asz[i]
    spent = 0.0; shares = 0.0; rem = notional
    for lvl in range(len(aprow)):
        p = aprow[lvl]; sz = aszrow[lvl]
        if not (math.isfinite(p) and p > 0 and math.isfinite(sz) and sz > 0):
            continue
        lvl_cost = p * sz
        if lvl_cost >= rem:
            buy = rem / p; shares += buy; spent += rem; rem = 0.0; break
        else:
            shares += sz; spent += lvl_cost; rem -= lvl_cost
    if shares <= 0:
        return None, None
    return spent / shares, shares

def best_ask_at(books, slug, outcome, fire_us):
    """Top-of-book ask at fire_us (for coverage check)."""
    rec = books.get((slug, outcome))
    if rec is None:
        return None
    ts, ap, asz, bp, bsz = rec
    i = np.searchsorted(ts, fire_us, side="right") - 1
    if i < 0:
        return None
    px = ap[i, 0]
    return float(px) if math.isfinite(px) and px > 0 else None

def has_book_at(books, slug, outcome, ts_us):
    """True if there's a book snapshot at or before ts_us."""
    rec = books.get((slug, outcome))
    if rec is None:
        return False
    ts_arr = rec[0]
    i = np.searchsorted(ts_arr, ts_us, side="right") - 1
    return i >= 0

# ── fee models ───────────────────────────────────────────────────────────────
def pnl_poly_07(vwap, shares, won):
    """Polymarket 0.07*p*(1-p) fee on taker entry."""
    if won:
        return (1.0 - vwap) * shares * (1.0 - 0.07 * vwap)
    return -vwap * shares

def pnl_legacy(vwap, shares, won):
    """Legacy 2%-on-profit-only (matches production shadow PnL)."""
    if won:
        return (1.0 - vwap) * shares * 0.98
    return -vwap * shares

def pnl_kalshi(vwap, shares, won):
    """Kalshi fee = 0.07*p*(1-p) per contract on entry (taker)."""
    fee_per_contract = 0.07 * vwap * (1.0 - vwap)
    if won:
        # net = shares * (1 - vwap) - shares * fee_per_contract
        return shares * ((1.0 - vwap) - fee_per_contract)
    # loss = -shares * vwap - shares * fee_per_contract
    return -shares * (vwap + fee_per_contract)

# ── load resolutions ─────────────────────────────────────────────────────────
print("\nLoading resolutions ...")
res = load_resolutions(assets=ASSETS, timeframes=["15m"])
res = res[(res.slot_start_us >= WIN_LO_US) & (res.slot_start_us <= WIN_HI_US)].copy()
print(f"  15m slots in window: {len(res)}")

# ── main loop (per asset to bound RAM) ───────────────────────────────────────
all_recs = []   # fires (gate pass)
all_eligible = []  # every slot where we computed S4 gate (used for coverage)

print("\nRunning S4 backtest per asset ...")
for a in ASSETS:
    res_a = res[res.ticker == a].copy()
    print(f"\n  {a}: {len(res_a)} 15m slots")

    # gather all slugs for this asset/window
    slugs = set(res_a.slug)

    # L25: load with subsample_1hz=True for memory efficiency
    # Single-point entry is fine at 1Hz resolution
    print(f"  Loading L25 {a} ({len(slugs)} slugs, 1Hz) ...")
    books = load_orderbook_l25_streaming(
        a.lower(), slugs=slugs,
        subsample_1hz=True,
        min_ts_us=WIN_LO_US - 200 * 1_000_000,
        max_ts_us=WIN_HI_US + 1100 * 1_000_000,  # +slot end (~900s) + 200s buffer
    )
    print(f"  L25 loaded: {len(books)} (slug, outcome) series")

    for _, r in res_a.iterrows():
        slug = r.slug
        slot_start_us = int(r.slot_start_us)
        slot_end_us   = int(r.slot_end_us)
        outcome_true  = r.outcome  # 'Up' / 'Down'

        fire_a = slot_start_us - 120 * 1_000_000   # pre-window fire (slot-120)
        fire_b = slot_start_us + 60 * 1_000_000    # Kalshi in-window (slot+60)
        fire_c = slot_start_us + 1 * 1_000_000     # Kalshi earliest-open (slot+1)

        # ── S4 gate (computed at fire_a, standard lookahead strike) ──────────
        f = feat_at(a, fire_a, slot_start_us, slot_end_us, causal_strike=False)
        if f is None or f["vwap_dev_bps"] is None:
            continue

        dev = f["vwap_dev_bps"]
        if abs(dev) < 8:
            continue

        direction = "UP" if dev > 0 else "DOWN"
        leg = "Up" if direction == "UP" else "Down"
        fu = f["fair_up"]

        # need pre-window entry_vwap for fair_edge gate
        ev = best_ask_at(books, slug, leg, fire_a)

        # Track coverage for every gate-eligible slug
        cov_rec = dict(
            asset=a, slug=slug, direction=direction,
            slot_start_us=slot_start_us,
            iso_week=pd.to_datetime(slot_start_us / 1e6, unit="s", utc=True).isocalendar().week,
            iso_year=pd.to_datetime(slot_start_us / 1e6, unit="s", utc=True).isocalendar().year,
            has_book_prewindow=has_book_at(books, slug, leg, fire_a),
            has_book_inwin60=has_book_at(books, slug, leg, fire_b),
            has_book_inwin1=has_book_at(books, slug, leg, fire_c),
            dev_bps=dev,
        )

        # fair_edge gate
        if ev is None or fu is None:
            cov_rec["gate_pass"] = False
            all_eligible.append(cov_rec)
            continue

        fe = (fu - ev) * 10000.0 if direction == "UP" else ((1.0 - fu) - ev) * 10000.0
        cvd_ok = cvd_agree(f["cvd_30s"], direction)

        gate_pass = (fe > 500) and cvd_ok
        cov_rec["gate_pass"] = gate_pass
        cov_rec["fair_edge_bp"] = fe
        all_eligible.append(cov_rec)

        if not gate_pass:
            continue

        # ── fills ─────────────────────────────────────────────────────────────
        vwap_a, sh_a = walk_fill(books, slug, leg, fire_a, NOTIONAL)
        vwap_b, sh_b = walk_fill(books, slug, leg, fire_b, NOTIONAL)
        vwap_c, sh_c = walk_fill(books, slug, leg, fire_c, NOTIONAL)

        won = (leg == outcome_true)
        in_baseline = (BASE_LO_US <= slot_start_us <= BASE_HI_US)
        iso_info = pd.to_datetime(slot_start_us / 1e6, unit="s", utc=True).isocalendar()

        base_rec = dict(
            asset=a, slug=slug, direction=direction, leg=leg,
            slot_start_us=slot_start_us, slot_end_us=slot_end_us,
            fire_us=fire_a,
            dev_bps=dev, fair_edge_bp=fe, fair_up=fu,
            cvd_30s=f["cvd_30s"], sigma=f["sigma"], s_now=f["s_now"],
            strike=f["strike"], tau_s=f["tau_s"],
            won=won, in_baseline=in_baseline,
            iso_week=int(iso_info.week), iso_year=int(iso_info.year),
        )

        # ── Variant A: poly prewindow ─────────────────────────────────────────
        if vwap_a is not None:
            rec = dict(base_rec)
            rec.update(
                variant="A_poly_prewindow",
                fill_ts_us=fire_a,
                entry_vwap=vwap_a, shares=sh_a,
                pnl_07=pnl_poly_07(vwap_a, sh_a, won),
                pnl_legacy=pnl_legacy(vwap_a, sh_a, won),
            )
            all_recs.append(rec)

        # ── Variant B: Kalshi in-window slot+60 ───────────────────────────────
        if vwap_b is not None:
            rec = dict(base_rec)
            rec.update(
                variant="B_kalshi_inwin60",
                fill_ts_us=fire_b,
                entry_vwap=vwap_b, shares=sh_b,
                pnl_07=pnl_kalshi(vwap_b, sh_b, won),
                pnl_legacy=pnl_legacy(vwap_b, sh_b, won),
            )
            all_recs.append(rec)

        # ── Variant C: Kalshi earliest-open slot+1 ────────────────────────────
        if vwap_c is not None:
            rec = dict(base_rec)
            rec.update(
                variant="C_kalshi_open",
                fill_ts_us=fire_c,
                entry_vwap=vwap_c, shares=sh_c,
                pnl_07=pnl_kalshi(vwap_c, sh_c, won),
                pnl_legacy=pnl_legacy(vwap_c, sh_c, won),
            )
            all_recs.append(rec)

    # free book memory before next asset
    del books
    gc.collect()
    print(f"  {a}: {sum(1 for r in all_recs if r['asset'] == a and r['variant'] == 'A_poly_prewindow')} S4 fires (variant A)")

# ── also run causal-strike variant on variant-A fires ────────────────────────
print("\nRunning causal-strike robustness pass (standard-gate fires only) ...")
# Reload per asset (need books again)
causal_recs = []
for a in ASSETS:
    res_a = res[res.ticker == a].copy()
    slugs = set(res_a.slug)
    books = load_orderbook_l25_streaming(
        a.lower(), slugs=slugs,
        subsample_1hz=True,
        min_ts_us=WIN_LO_US - 200 * 1_000_000,
        max_ts_us=WIN_HI_US + 1100 * 1_000_000,
    )
    for _, r in res_a.iterrows():
        slug = r.slug
        slot_start_us = int(r.slot_start_us)
        slot_end_us   = int(r.slot_end_us)
        outcome_true  = r.outcome
        fire_a = slot_start_us - 120 * 1_000_000

        f_c = feat_at(a, fire_a, slot_start_us, slot_end_us, causal_strike=True)
        if f_c is None or f_c["vwap_dev_bps"] is None:
            continue

        dev = f_c["vwap_dev_bps"]
        if abs(dev) < 8:
            continue

        direction = "UP" if dev > 0 else "DOWN"
        leg = "Up" if direction == "UP" else "Down"
        fu = f_c["fair_up"]
        ev = best_ask_at(books, slug, leg, fire_a)
        if ev is None or fu is None:
            continue

        fe = (fu - ev) * 10000.0 if direction == "UP" else ((1.0 - fu) - ev) * 10000.0
        cvd_ok = cvd_agree(f_c["cvd_30s"], direction)

        if not (fe > 500 and cvd_ok):
            continue

        vwap_a, sh_a = walk_fill(books, slug, leg, fire_a, NOTIONAL)
        if vwap_a is None:
            continue

        won = (leg == outcome_true)
        causal_recs.append(dict(
            asset=a, slug=slug, direction=direction, leg=leg,
            slot_start_us=slot_start_us, won=won,
            entry_vwap=vwap_a, shares=sh_a,
            pnl_07=pnl_poly_07(vwap_a, sh_a, won),
            pnl_legacy=pnl_legacy(vwap_a, sh_a, won),
            dev_bps=dev, fair_edge_bp=fe,
            iso_week=int(pd.to_datetime(slot_start_us / 1e6, unit="s", utc=True).isocalendar().week),
            iso_year=int(pd.to_datetime(slot_start_us / 1e6, unit="s", utc=True).isocalendar().year),
        ))
    del books
    gc.collect()
    print(f"  {a}: {sum(1 for r in causal_recs if r['asset'] == a)} causal-strike fires")

# ── build DataFrames ──────────────────────────────────────────────────────────
bt = pd.DataFrame(all_recs)
cov = pd.DataFrame(all_eligible)
causal = pd.DataFrame(causal_recs)

# Save fires CSV
fires_out = bt.copy()
fires_out.to_csv(OUT_DIR + r"\s4_fires.csv", index=False)
print(f"\nSaved {len(fires_out)} fire-variant rows to s4_fires.csv")

# ── stats helpers ─────────────────────────────────────────────────────────────
def bootstrap_ci(arr, n=2000, q_lo=0.025, q_hi=0.975):
    if len(arr) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(42)
    means = [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n)]
    return float(np.quantile(means, q_lo)), float(np.quantile(means, q_hi))

def binom_p(wins, n):
    if n == 0:
        return float("nan")
    return stats.binomtest(wins, n, 0.5, alternative="greater").pvalue

def max_drawdown(pnls):
    if len(pnls) == 0:
        return 0.0
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = peak - cum
    return float(dd.max())

def payoff_ratio(pnls, wons):
    wins = pnls[wons]
    losses = -pnls[~wons]
    avg_w = wins.mean() if len(wins) > 0 else float("nan")
    avg_l = losses.mean() if len(losses) > 0 else float("nan")
    return avg_w / avg_l if (avg_l and avg_l > 0) else float("nan")

def summarise(df_sub, pnl_col="pnl_07", label=""):
    if len(df_sub) == 0:
        return dict(label=label, n=0, wr=float("nan"), per_trade=float("nan"),
                    total=float("nan"), binom_p=float("nan"),
                    ci_lo=float("nan"), ci_hi=float("nan"),
                    max_dd=float("nan"), payoff=float("nan"))
    pnl_arr = df_sub[pnl_col].values.astype(float)
    won_arr = df_sub["won"].values.astype(bool)
    n = len(df_sub)
    wins = int(won_arr.sum())
    wr = wins / n
    per_trade = pnl_arr.mean()
    total = pnl_arr.sum()
    bp = binom_p(wins, n)
    ci_lo, ci_hi = bootstrap_ci(pnl_arr)
    mdd = max_drawdown(pnl_arr)
    pr = payoff_ratio(pnl_arr, won_arr)
    return dict(label=label, n=n, wr=wr, per_trade=per_trade, total=total,
                binom_p=bp, ci_lo=ci_lo, ci_hi=ci_hi, max_dd=mdd, payoff=pr)

# ── coverage analysis ─────────────────────────────────────────────────────────
print("\n=== COVERAGE ANALYSIS ===")
if len(cov) > 0:
    gp = cov[cov["gate_pass"] == True] if "gate_pass" in cov.columns else cov
    total_elig = len(cov)
    gate_pass_n = cov.get("gate_pass", pd.Series(dtype=bool)).sum() if "gate_pass" in cov.columns else len(cov)

    has_pre  = cov["has_book_prewindow"].sum() if "has_book_prewindow" in cov.columns else 0
    has_i60  = cov["has_book_inwin60"].sum() if "has_book_inwin60" in cov.columns else 0
    has_i1   = cov["has_book_inwin1"].sum() if "has_book_inwin1" in cov.columns else 0

    pct_pre = 100 * has_pre / total_elig if total_elig else 0
    pct_i60 = 100 * has_i60 / total_elig if total_elig else 0
    pct_i1  = 100 * has_i1  / total_elig if total_elig else 0

    print(f"  Dev-eligible slugs (|dev|>=8): {total_elig}")
    print(f"  Gate pass (fe>500 & cvd): {gate_pass_n}")
    print(f"  Book coverage at slot-120  (pre-window) : {has_pre}/{total_elig} = {pct_pre:.1f}%")
    print(f"  Book coverage at slot+60   (in-win-60)  : {has_i60}/{total_elig} = {pct_i60:.1f}%")
    print(f"  Book coverage at slot+1    (open-fallbk) : {has_i1}/{total_elig} = {pct_i1:.1f}%")

# ── baseline reproduction ─────────────────────────────────────────────────────
print("\n=== BASELINE REPRODUCTION (21d ~May 8 to May 29, legacy 2%-fee) ===")
if len(bt) > 0:
    base_a = bt[(bt.variant == "A_poly_prewindow") & (bt.in_baseline == True)]
    s = summarise(base_a, pnl_col="pnl_legacy", label="A baseline (legacy fee)")
    print(f"  n={s['n']}  WR={s['wr']*100:.1f}%  per-trade=${s['per_trade']:.2f}"
          f"  total=${s['total']:.2f}  binom_p={s['binom_p']:.4f}")
    print(f"  Reference: n=229  WR=54.6%  per-trade=$2.26  binom_p=0.090")
    div = abs(s['n'] - 229)
    print(f"  Delta n={s['n']-229:+d}  (window difference: baseline window may differ)")

# ── full-period results per variant ──────────────────────────────────────────
print("\n=== FULL PERIOD (Apr24-Jun1) PER VARIANT ===")
VAR_FEE = {
    "A_poly_prewindow": "pnl_07",
    "B_kalshi_inwin60": "pnl_07",
    "C_kalshi_open":    "pnl_07",
}
summaries = []
for var in ["A_poly_prewindow", "B_kalshi_inwin60", "C_kalshi_open"]:
    sub = bt[bt.variant == var]
    pnl_col = VAR_FEE[var]
    s = summarise(sub, pnl_col=pnl_col, label=var)
    summaries.append(s)
    print(f"  {var}: n={s['n']}  WR={s['wr']*100:.1f}%  $/tr={s['per_trade']:.2f}"
          f"  total=${s['total']:.2f}  p={s['binom_p']:.4f}"
          f"  CI=[{s['ci_lo']:.2f},{s['ci_hi']:.2f}]"
          f"  MaxDD=${s['max_dd']:.2f}  payoff={s['payoff']:.2f}x")

# Also legacy-fee view for A
if len(bt) > 0:
    sub_a = bt[bt.variant == "A_poly_prewindow"]
    s_leg = summarise(sub_a, pnl_col="pnl_legacy", label="A_poly_prewindow (legacy)")
    print(f"\n  A_poly_prewindow (legacy 2%): n={s_leg['n']}  WR={s_leg['wr']*100:.1f}%  $/tr={s_leg['per_trade']:.2f}"
          f"  total=${s_leg['total']:.2f}  p={s_leg['binom_p']:.4f}")

# ── per-asset breakdown ───────────────────────────────────────────────────────
print("\n=== PER-ASSET BREAKDOWN (variant A, 0.07 fee) ===")
asset_rows = []
if len(bt) > 0:
    sub_a = bt[bt.variant == "A_poly_prewindow"]
    for asset in ASSETS:
        sa = sub_a[sub_a.asset == asset]
        s = summarise(sa, pnl_col="pnl_07", label=f"A {asset}")
        asset_rows.append(s)
        print(f"  {asset}: n={s['n']}  WR={s['wr']*100:.1f}%  $/tr={s['per_trade']:.2f}  total=${s['total']:.2f}")

# ── per-direction breakdown ───────────────────────────────────────────────────
print("\n=== PER-DIRECTION BREAKDOWN (variant A, 0.07 fee) ===")
dir_rows = []
if len(bt) > 0:
    sub_a = bt[bt.variant == "A_poly_prewindow"]
    for d in ["UP", "DOWN"]:
        sd = sub_a[sub_a.direction == d]
        s = summarise(sd, pnl_col="pnl_07", label=f"A {d}")
        dir_rows.append(s)
        print(f"  {d}: n={s['n']}  WR={s['wr']*100:.1f}%  $/tr={s['per_trade']:.2f}")

# ── by-week walk-forward (variant A) ─────────────────────────────────────────
print("\n=== BY-WEEK WALK-FORWARD (variant A, 0.07 fee) ===")
week_rows = []
if len(bt) > 0:
    sub_a = bt[bt.variant == "A_poly_prewindow"].copy()
    sub_a["week_key"] = sub_a.apply(lambda r: f"{r.iso_year}-W{r.iso_week:02d}", axis=1)
    for wk, wdf in sorted(sub_a.groupby("week_key")):
        s = summarise(wdf, pnl_col="pnl_07", label=wk)
        s["week_key"] = wk
        week_rows.append(s)
        print(f"  {wk}: n={s['n']}  WR={s['wr']*100:.1f}%  $/tr={s['per_trade']:.2f}  total=${s['total']:.2f}")

# ── causal-strike robustness ──────────────────────────────────────────────────
print("\n=== CAUSAL-STRIKE ROBUSTNESS ===")
if len(causal) > 0:
    s_c = summarise(causal, pnl_col="pnl_07", label="causal-strike")
    print(f"  Causal: n={s_c['n']}  WR={s_c['wr']*100:.1f}%  $/tr={s_c['per_trade']:.2f}"
          f"  total=${s_c['total']:.2f}  p={s_c['binom_p']:.4f}"
          f"  CI=[{s_c['ci_lo']:.2f},{s_c['ci_hi']:.2f}]")
    # Compare to lookahead variant A
    if len(bt) > 0:
        sub_a = bt[bt.variant == "A_poly_prewindow"]
        s_la = summarise(sub_a, pnl_col="pnl_07", label="lookahead-strike")
        print(f"  Lookahead: n={s_la['n']}  WR={s_la['wr']*100:.1f}%  $/tr={s_la['per_trade']:.2f}"
              f"  total=${s_la['total']:.2f}  p={s_la['binom_p']:.4f}")
        delta_n = s_c["n"] - s_la["n"]
        delta_ppt = (s_c["per_trade"] - s_la["per_trade"])
        print(f"  Delta: n={delta_n:+d}  $/tr={delta_ppt:+.2f}")
        if abs(s_c["per_trade"]) < 0.50 or s_c["binom_p"] > 0.15:
            print("  !! CAUSAL-STRIKE EDGE WEAK OR GONE — lookahead in strike is likely driving the edge !!")
        else:
            print("  Causal-strike edge holds. Strike lookahead is NOT the sole driver.")
else:
    print("  No causal fires found.")

# ── variant comparison table ───────────────────────────────────────────────────
print("\n=== VARIANT COMPARISON TABLE ===")
for s in summaries:
    print(f"  {s['label']:25s}  n={s['n']:4d}  WR={s['wr']*100:5.1f}%  "
          f"$/tr={s['per_trade']:6.2f}  total={s['total']:8.2f}  "
          f"p={s['binom_p']:.4f}  CI=[{s['ci_lo']:.2f},{s['ci_hi']:.2f}]  "
          f"DD={s['max_dd']:.2f}  pay={s['payoff']:.2f}x")

print("\nDONE")
