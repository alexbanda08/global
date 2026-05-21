"""V6 — decode the REMAINING ~31% of taker fires for 0xeebde7a0 that V2's 3-rule
composite (disc OR pm_drop_5s>0.02 OR offset_s∈[0,60]) still misses.

Hypotheses tested:
  H8  cross-exchange leads  (coinbase / kraken / okx 1MIN ret)
  H9  L25 book depth        (top-5 vs top-25 ratios, ask shape)
  H10 trade-size burst       (large trade in last 5-15s)
  H11 interactions           (pairwise loose-rule AND combos)
  H12 time-of-day             (UTC hour clusters in un-explained)
  H13 own-side maker fill chase  (sec since OWN maker fill on SAME side)
  H14 sub-second flow         (sell vol in last 1s / 2s)
  H15 sum_asks specific bands  (narrow $0.99-$1.01 etc.)

Outputs:
  strategy_lab/wallet_hunt/cache/0xeebde7a0_taker_decode/v6_features.parquet
  strategy_lab/wallet_hunt/cache/0xeebde7a0_taker_decode/v6_summary.json
"""
from __future__ import annotations
import os, sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

CACHE = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xeebde7a0_taker_decode"
OUT_FEATURES = CACHE / "v6_features.parquet"
OUT_SUMMARY = CACHE / "v6_summary.json"
LOG_PATH = CACHE / "v6_run.log"

_t0 = time.time()
def log(msg, also_print=True):
    line = f"[{time.time()-_t0:6.1f}s] {msg}"
    if also_print:
        print(line, flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

LOG_PATH.write_text("", encoding="utf-8")

# =====================================================================
# 1. Load V5 enriched parquets — these are the V1-unexplained pool
# =====================================================================
log("loading v5 hypothesis parquets ...")
fe_all = pd.read_parquet(CACHE / "fire_v5_hypotheses.parquet")
ce_all = pd.read_parquet(CACHE / "control_v5_hypotheses.parquet")
log(f"  fire_v5 n={len(fe_all)} ctrl_v5 n={len(ce_all)}")

# Identify the V3 un-explained subset (V2 3-rule composite false)
def v2_covered(df):
    return df.disc_capture | (df.pm_drop_5s > 0.02) | ((df.offset_s >= 0) & (df.offset_s <= 60))

fe_un = fe_all[~v2_covered(fe_all)].reset_index(drop=True)
ce_un = ce_all[~v2_covered(ce_all)].reset_index(drop=True)
log(f"  V3 un-explained (after V2 3-rule composite OFF): fire n={len(fe_un)} ctrl n={len(ce_un)}")

# =====================================================================
# 2. Trade-tape data: index by (slug, outcome)
# =====================================================================
log("loading polymarket trades (btc) ...")
from load import load_trades, load_klines_asof
tr = load_trades("BTC")
# need slug + outcome to match fe.outcome (Up/Down strings)
log(f"  trades: rows={len(tr)} cols={list(tr.columns)}")

# need timestamp + price + size + side (Up/Down) + bought_outcome.
# For 'bought side' notion we'll filter to relevant slugs only — bounds memory
needed_slugs = set(fe_all.slug.unique()) | set(ce_all.slug.unique())
log(f"  filtering trades to {len(needed_slugs)} relevant slugs ...")
tr = tr[tr.slug.isin(needed_slugs)].copy()
log(f"  trades sub: rows={len(tr)}")

# normalize outcome — should be 'Up' / 'Down' strings
tr["timestamp_us"] = tr["timestamp_us"].astype("int64")
tr["price"] = tr["price"].astype("float64")
tr["size"] = tr["size"].astype("float64")
# side is buy/sell
# build per (slug, outcome) sorted index
tr = tr.sort_values(["slug", "outcome", "timestamp_us"]).reset_index(drop=True)

tr_idx = {}
for (sl, oc), g in tr.groupby(["slug", "outcome"], sort=False):
    tr_idx[(sl, oc)] = (
        g["timestamp_us"].values.astype("int64"),
        g["price"].values.astype("float64"),
        g["size"].values.astype("float64"),
        g["side"].values.astype("U8"),
    )
log(f"  trade index: {len(tr_idx)} (slug, outcome) groups")

# =====================================================================
# 3. H8 — cross-exchange leads (coinbase / kraken / okx)
# =====================================================================
log("H8: loading cross-exchange 1MIN klines (coinbase / kraken / okx) ...")
sources = {
    "coinbase": "coinbase-spot-ws",
    "kraken":   "kraken-spot-ws",
    "okx":      "okx-ws",
    "binance":  "binance-spot-ws",  # add for control verification
}
kxs = {}
for name, src in sources.items():
    try:
        e, p = load_klines_asof("BTC", src, "1MIN")
        kxs[name] = (e, p)
        log(f"  {name}: n_bars={len(e)} range_us={int(e.min())}..{int(e.max())}")
    except Exception as ex:
        log(f"  {name}: failed -> {ex}")

def ret_window(end_us, price_close, target_us, window_s):
    """Signed simple return between bar that ended at-or-before (target-window_s)
    and the bar that ended at-or-before target."""
    if len(end_us) == 0: return np.nan
    j = np.searchsorted(end_us, int(target_us), side="right") - 1
    i = np.searchsorted(end_us, int(target_us - window_s * 1_000_000), side="right") - 1
    if j < 0 or i < 0 or i >= j: return np.nan
    p_now = price_close[j]; p_then = price_close[i]
    if p_then <= 0: return np.nan
    return float(p_now / p_then - 1.0)

def add_h8(df):
    df = df.copy()
    for name, (e, p) in kxs.items():
        for w in (60, 120, 300):
            col_r = f"{name}_ret_{w}s"
            col_s = f"{name}_sret_{w}s"
            rets = np.array([ret_window(e, p, int(r.t_sec) * 1_000_000, w) for r in df.itertuples(index=False)])
            df[col_r] = rets
            # signed (positive = aligned with bought side)
            sgn = np.where(df.outcome.values == "Up", 1.0, -1.0)
            df[col_s] = sgn * rets
    return df

log(f"  H8 enriching fire_un (n={len(fe_un)}) ...")
fe_un = add_h8(fe_un)
log(f"  H8 enriching ctrl_un (n={len(ce_un)}) ...")
ce_un = add_h8(ce_un)
log(f"  H8 done. sample coinbase_sret_60s fire mean={fe_un.coinbase_sret_60s.mean():.6f}, ctrl mean={ce_un.coinbase_sret_60s.mean():.6f}")

# =====================================================================
# 4. H10 — trade-size burst patterns
# =====================================================================
log("H10: computing trade-size burst features ...")

def burst_features(slug, outcome, t_sec, win_s):
    """Returns dict: count by size bucket + max trade size in window."""
    arr = tr_idx.get((slug, outcome))
    if arr is None:
        return None
    ts, pr, sz, sd = arr
    tus = t_sec * 1_000_000
    lo = tus - win_s * 1_000_000
    hi_i = np.searchsorted(ts, tus, side="left")
    lo_i = np.searchsorted(ts, lo, side="left")
    if hi_i <= lo_i:
        return {
            "n_lt5":0, "n_5_20":0, "n_20_100":0, "n_gt100":0,
            "max_size":0.0, "max_sell_size":0.0, "max_buy_size":0.0,
            "n_trades":0,
        }
    s = sz[lo_i:hi_i]; d = sd[lo_i:hi_i]
    is_sell = d == "sell"
    is_buy  = d == "buy"
    return {
        "n_lt5":     int(((s > 0) & (s < 5)).sum()),
        "n_5_20":    int(((s >= 5) & (s < 20)).sum()),
        "n_20_100":  int(((s >= 20) & (s < 100)).sum()),
        "n_gt100":   int((s >= 100).sum()),
        "max_size":  float(s.max()) if len(s) else 0.0,
        "max_sell_size": float(s[is_sell].max()) if is_sell.any() else 0.0,
        "max_buy_size":  float(s[is_buy].max()) if is_buy.any() else 0.0,
        "n_trades":  int(len(s)),
    }

def add_h10(df):
    df = df.copy()
    for win in (5, 15):
        feats = [burst_features(r.slug, r.outcome, r.t_sec, win) for r in df.itertuples(index=False)]
        for k in ["n_lt5","n_5_20","n_20_100","n_gt100","max_size","max_sell_size","max_buy_size","n_trades"]:
            df[f"h10_{k}_{win}s"] = [f.get(k) if f else np.nan for f in feats]
    return df

fe_un = add_h10(fe_un)
ce_un = add_h10(ce_un)
log(f"  H10 done. fire max_sell_size_15s mean={fe_un.h10_max_sell_size_15s.mean():.2f}, ctrl mean={ce_un.h10_max_sell_size_15s.mean():.2f}")

# =====================================================================
# 5. H9 — L25 book DEPTH features (top-5 vs top-25 ratios)
# =====================================================================
log("H9: loading L25 books for un-explained slugs (this can take a few min) ...")
from load import load_orderbook_l25_streaming
need_slugs = set(fe_un.slug.unique()) | set(ce_un.slug.unique())
log(f"  loading {len(need_slugs)} slugs ...")
ob = load_orderbook_l25_streaming("btc", slugs=need_slugs, subsample_1hz=True)
log(f"  loaded {len(ob)} (slug, outcome) book streams")

def book_at(slug, outcome, t_sec):
    arr = ob.get((slug, outcome))
    if arr is None: return None
    ts_us, ap, asz, bp, bsz = arr
    tus = t_sec * 1_000_000
    i = np.searchsorted(ts_us, tus, side="right") - 1
    if i < 0: return None
    return ap[i], asz[i], bp[i], bsz[i]

def add_h9(df):
    df = df.copy()
    rows = []
    for r in df.itertuples(index=False):
        b = book_at(r.slug, r.outcome, r.t_sec)
        if b is None:
            rows.append([np.nan]*8); continue
        ap, asz, bp, bsz = b
        sum_ask_top5  = float(np.nansum(asz[:5]))
        sum_ask_top25 = float(np.nansum(asz[:25]))
        sum_bid_top5  = float(np.nansum(bsz[:5]))
        sum_bid_top25 = float(np.nansum(bsz[:25]))
        ask_top5_frac  = (sum_ask_top5 / sum_ask_top25) if sum_ask_top25 > 0 else np.nan
        bid_top5_frac  = (sum_bid_top5 / sum_bid_top25) if sum_bid_top25 > 0 else np.nan
        best_ask_frac  = (float(asz[0]) / sum_ask_top25) if sum_ask_top25 > 0 else np.nan
        best_bid_frac  = (float(bsz[0]) / sum_bid_top25) if sum_bid_top25 > 0 else np.nan
        rows.append([
            sum_ask_top5, sum_ask_top25, sum_bid_top5, sum_bid_top25,
            ask_top5_frac, bid_top5_frac, best_ask_frac, best_bid_frac,
        ])
    arr = np.array(rows)
    df["h9_sum_ask_top5"]  = arr[:,0]
    df["h9_sum_ask_top25"] = arr[:,1]
    df["h9_sum_bid_top5"]  = arr[:,2]
    df["h9_sum_bid_top25"] = arr[:,3]
    df["h9_ask_top5_frac"] = arr[:,4]
    df["h9_bid_top5_frac"] = arr[:,5]
    df["h9_best_ask_frac"] = arr[:,6]
    df["h9_best_bid_frac"] = arr[:,7]
    return df

fe_un = add_h9(fe_un)
ce_un = add_h9(ce_un)
log(f"  H9 done. fire ask_top5_frac mean={fe_un.h9_ask_top5_frac.mean():.3f}, ctrl mean={ce_un.h9_ask_top5_frac.mean():.3f}")
log(f"  H9 done. fire best_ask_frac mean={fe_un.h9_best_ask_frac.mean():.3f}, ctrl mean={ce_un.h9_best_ask_frac.mean():.3f}")

# =====================================================================
# 6. H12 — UTC hour patterns
# =====================================================================
log("H12: time-of-day buckets ...")
def add_h12(df):
    df = df.copy()
    df["utc_hour"] = (df.t_sec.astype("int64") // 3600 % 24).astype("int64")
    return df
fe_un = add_h12(fe_un)
ce_un = add_h12(ce_un)
log(f"  H12 done. fire hour distribution:\n{fe_un.utc_hour.value_counts().sort_index().to_string()}")

# =====================================================================
# 7. H13 — recent OWN-side maker fill (within 10s) on SAME side
# =====================================================================
log("H13: time-since-last-own-MAKER-fill on SAME side (sub-bucket) ...")
# We already have sec_since_last_maker — bucket it
def add_h13(df):
    df = df.copy()
    s = df.sec_since_last_maker
    df["h13_maker_lt5"]  = (s < 5).fillna(False)
    df["h13_maker_lt10"] = (s < 10).fillna(False)
    df["h13_maker_lt30"] = (s < 30).fillna(False)
    df["h13_maker_lt60"] = (s < 60).fillna(False)
    df["h13_maker_isnan"]= s.isna()
    return df
fe_un = add_h13(fe_un)
ce_un = add_h13(ce_un)
log(f"  H13 done. fire maker_lt5={fe_un.h13_maker_lt5.mean():.3f} ctrl={ce_un.h13_maker_lt5.mean():.3f}")

# =====================================================================
# 8. H14 — sub-second sell volume (1s, 2s)
# =====================================================================
log("H14: sub-second sell volume ...")
def micro_vol(slug, outcome, t_sec_us, win_us):
    arr = tr_idx.get((slug, outcome))
    if arr is None: return (np.nan, np.nan, np.nan)
    ts, pr, sz, sd = arr
    lo = t_sec_us - win_us
    hi_i = np.searchsorted(ts, t_sec_us, side="left")
    lo_i = np.searchsorted(ts, lo, side="left")
    if hi_i <= lo_i: return (0.0, 0.0, 0.0)
    s = sz[lo_i:hi_i]; d = sd[lo_i:hi_i]
    sell_v = float(s[d == "sell"].sum())
    buy_v  = float(s[d == "buy"].sum())
    tot    = float(s.sum())
    return (sell_v, buy_v, tot)

def add_h14(df):
    df = df.copy()
    for win_s_micro in (1, 2):
        rows = [micro_vol(r.slug, r.outcome, int(r.t_sec) * 1_000_000, win_s_micro * 1_000_000) for r in df.itertuples(index=False)]
        arr = np.array(rows)
        df[f"h14_sell_vol_{win_s_micro}s"] = arr[:,0]
        df[f"h14_buy_vol_{win_s_micro}s"]  = arr[:,1]
        df[f"h14_tot_vol_{win_s_micro}s"]  = arr[:,2]
    return df

fe_un = add_h14(fe_un)
ce_un = add_h14(ce_un)
log(f"  H14 done. fire sell_vol_1s mean={fe_un.h14_sell_vol_1s.mean():.2f}, ctrl mean={ce_un.h14_sell_vol_1s.mean():.2f}")

# =====================================================================
# 9. H15 — sum_asks specific bands (sum_bid_sz + sum_ask_sz already in df)
# =====================================================================
log("H15: pair_ask_sum / sum_ask_sz bands ...")
# pair_ask_sum & own_best_ask (sum of best_ask + complementary_ask sums to ~$1)
# We have pair_ask_sum in original v5 parquet. Use that.
def add_h15(df):
    df = df.copy()
    p = df.pair_ask_sum
    df["h15_pas_lt_098"]    = p < 0.98
    df["h15_pas_098_100"]   = (p >= 0.98) & (p < 1.00)
    df["h15_pas_100_102"]   = (p >= 1.00) & (p < 1.02)
    df["h15_pas_102_105"]   = (p >= 1.02) & (p < 1.05)
    df["h15_pas_gt_105"]    = p >= 1.05
    return df
fe_un = add_h15(fe_un)
ce_un = add_h15(ce_un)
log(f"  H15 done. fire pas band hist: {[(b, fe_un[b].mean()) for b in ['h15_pas_lt_098','h15_pas_098_100','h15_pas_100_102','h15_pas_102_105','h15_pas_gt_105']]}")

# =====================================================================
# 10. Save enriched
# =====================================================================
log("saving enriched v6 features ...")
fe_un["_kind"] = "fire"
ce_un["_kind"] = "ctrl"
all_df = pd.concat([fe_un, ce_un], ignore_index=True)
all_df.to_parquet(OUT_FEATURES, index=False)
log(f"  saved {OUT_FEATURES} rows={len(all_df)}")

# =====================================================================
# 11. STATISTICAL ANALYSIS
# =====================================================================
def wilson_z(p1, n1, p2, n2):
    if min(n1, n2) == 0: return 0.0
    p = (p1*n1 + p2*n2) / (n1 + n2)
    if p == 0 or p == 1: return 0.0
    se = (p * (1-p) * (1/n1 + 1/n2)) ** 0.5
    return (p1 - p2) / se if se > 0 else 0.0

def thresh(name, fmask, cmask):
    fv = pd.Series(fmask).dropna()
    cv = pd.Series(cmask).dropna()
    fn = int(len(fv)); cn = int(len(cv))
    if fn == 0 or cn == 0:
        return {"name": name, "fire_rate": float("nan"), "ctrl_rate": float("nan"), "lift": float("nan"), "z": 0.0, "fire_n": fn, "ctrl_n": cn, "fire_hits": 0}
    fr = float(fv.astype(bool).mean()); cr = float(cv.astype(bool).mean())
    lift = fr / cr if cr > 0 else float("inf")
    z = wilson_z(fr, fn, cr, cn)
    return {"name": name, "fire_rate": fr, "ctrl_rate": cr, "lift": lift, "z": z, "fire_n": fn, "ctrl_n": cn, "fire_hits": int(fv.astype(bool).sum())}

log("\n=== H8-H15 lift tests on V3 un-explained subset ===\n")
tests = []

# H8 — cross-exchange ret thresholds
for src in ["coinbase","kraken","okx","binance"]:
    for w in (60, 120, 300):
        col = f"{src}_sret_{w}s"
        if col in fe_un.columns:
            for thr in (0.0, 0.0002, 0.0005, 0.001):
                t = thresh(f"H8 {col} > {thr:.4f}", fe_un[col] > thr, ce_un[col] > thr)
                tests.append(t)

# H9 — book depth ratios
for thr in (0.40, 0.50, 0.60, 0.70):
    tests.append(thresh(f"H9 best_ask_frac > {thr}", fe_un.h9_best_ask_frac > thr, ce_un.h9_best_ask_frac > thr))
    tests.append(thresh(f"H9 ask_top5_frac > {thr}", fe_un.h9_ask_top5_frac > thr, ce_un.h9_ask_top5_frac > thr))
tests.append(thresh("H9 sum_ask_top25 < 200",  fe_un.h9_sum_ask_top25 < 200, ce_un.h9_sum_ask_top25 < 200))
tests.append(thresh("H9 sum_ask_top25 < 500",  fe_un.h9_sum_ask_top25 < 500, ce_un.h9_sum_ask_top25 < 500))
tests.append(thresh("H9 sum_ask_top25 > 2000", fe_un.h9_sum_ask_top25 > 2000, ce_un.h9_sum_ask_top25 > 2000))

# H10 — trade-size burst
for w in (5, 15):
    tests.append(thresh(f"H10 max_sell_size_{w}s > 50",  fe_un[f"h10_max_sell_size_{w}s"] > 50, ce_un[f"h10_max_sell_size_{w}s"] > 50))
    tests.append(thresh(f"H10 max_sell_size_{w}s > 100", fe_un[f"h10_max_sell_size_{w}s"] > 100, ce_un[f"h10_max_sell_size_{w}s"] > 100))
    tests.append(thresh(f"H10 n_gt100_{w}s > 0",         fe_un[f"h10_n_gt100_{w}s"] > 0,         ce_un[f"h10_n_gt100_{w}s"] > 0))
    tests.append(thresh(f"H10 n_20_100_{w}s > 0",        fe_un[f"h10_n_20_100_{w}s"] > 0,        ce_un[f"h10_n_20_100_{w}s"] > 0))
    tests.append(thresh(f"H10 n_trades_{w}s > 5",        fe_un[f"h10_n_trades_{w}s"] > 5,        ce_un[f"h10_n_trades_{w}s"] > 5))

# H12 — UTC hour
hours_present_fire = fe_un.utc_hour.value_counts()
for h in range(24):
    tests.append(thresh(f"H12 utc_hour == {h:02d}", fe_un.utc_hour == h, ce_un.utc_hour == h))

# H13 — own-side maker fill chase
tests.append(thresh("H13 maker_lt5",  fe_un.h13_maker_lt5,  ce_un.h13_maker_lt5))
tests.append(thresh("H13 maker_lt10", fe_un.h13_maker_lt10, ce_un.h13_maker_lt10))
tests.append(thresh("H13 maker_lt30", fe_un.h13_maker_lt30, ce_un.h13_maker_lt30))
tests.append(thresh("H13 maker_lt60", fe_un.h13_maker_lt60, ce_un.h13_maker_lt60))

# H14 — sub-second sell volume
for w in (1, 2):
    tests.append(thresh(f"H14 sell_vol_{w}s > 0", fe_un[f"h14_sell_vol_{w}s"] > 0, ce_un[f"h14_sell_vol_{w}s"] > 0))
    tests.append(thresh(f"H14 sell_vol_{w}s > 10", fe_un[f"h14_sell_vol_{w}s"] > 10, ce_un[f"h14_sell_vol_{w}s"] > 10))
    tests.append(thresh(f"H14 sell_vol_{w}s > 50", fe_un[f"h14_sell_vol_{w}s"] > 50, ce_un[f"h14_sell_vol_{w}s"] > 50))
    tests.append(thresh(f"H14 tot_vol_{w}s > 0",   fe_un[f"h14_tot_vol_{w}s"] > 0,   ce_un[f"h14_tot_vol_{w}s"] > 0))

# H15 — pair_ask_sum bands
for col in ["h15_pas_lt_098","h15_pas_098_100","h15_pas_100_102","h15_pas_102_105","h15_pas_gt_105"]:
    tests.append(thresh(f"H15 {col}", fe_un[col], ce_un[col]))

# H11 — loose-rule interactions (use V5 features still in df!)
# pm_drop_5s > 0.01 (loose drop) AND own_best_ask < 0.45 (loose disc)
tests.append(thresh("H11 ask<0.45 AND drop_5s>0.01",
                    (fe_un.own_best_ask < 0.45) & (fe_un.pm_drop_5s > 0.01),
                    (ce_un.own_best_ask < 0.45) & (ce_un.pm_drop_5s > 0.01)))
tests.append(thresh("H11 ask<0.50 AND offset<120",
                    (fe_un.own_best_ask < 0.50) & (fe_un.offset_s < 120),
                    (ce_un.own_best_ask < 0.50) & (ce_un.offset_s < 120)))
tests.append(thresh("H11 ask<0.50 AND best_ask_frac<0.40",
                    (fe_un.own_best_ask < 0.50) & (fe_un.h9_best_ask_frac < 0.40),
                    (ce_un.own_best_ask < 0.50) & (ce_un.h9_best_ask_frac < 0.40)))
tests.append(thresh("H11 sec_since_maker isnan AND offset<180",
                    (fe_un.sec_since_last_maker.isna()) & (fe_un.offset_s < 180),
                    (ce_un.sec_since_last_maker.isna()) & (ce_un.offset_s < 180)))
tests.append(thresh("H11 buy_vol_60s>50 AND pm_drop_5s>0",
                    (fe_un.buy_vol_60s > 50) & (fe_un.pm_drop_5s > 0),
                    (ce_un.buy_vol_60s > 50) & (ce_un.pm_drop_5s > 0)))
tests.append(thresh("H11 buy_vol_60s>100 AND pm_drop_5s>0",
                    (fe_un.buy_vol_60s > 100) & (fe_un.pm_drop_5s > 0),
                    (ce_un.buy_vol_60s > 100) & (ce_un.pm_drop_5s > 0)))
tests.append(thresh("H11 H14 sell_vol_2s > 0 AND ask < 0.50",
                    (fe_un.h14_sell_vol_2s > 0) & (fe_un.own_best_ask < 0.50),
                    (ce_un.h14_sell_vol_2s > 0) & (ce_un.own_best_ask < 0.50)))

# Print sorted by lift desc, then print top 30
tests.sort(key=lambda t: (-(t["lift"] if np.isfinite(t["lift"]) else 0), -abs(t["z"])))
print(f"\n{'rule':<55} {'fire':>8} {'ctrl':>8} {'lift':>7} {'z':>7} {'fn':>5}/{'cn':<5} {'hits':>5}")
print("-"*120)
for t in tests:
    if t["fire_n"] < 30 or t["ctrl_n"] < 30: continue
    print(f"{t['name']:<55} {t['fire_rate']:>8.3f} {t['ctrl_rate']:>8.3f} {t['lift']:>7.2f} {t['z']:>+7.2f} {t['fire_n']:>5}/{t['ctrl_n']:<5} {t['fire_hits']:>5}")

# =====================================================================
# 12. FINAL COMPOSITE — pick top non-overlapping new rules, OR them with V2's 3
# =====================================================================
log("\n=== COMPOSITE RULE EVALUATION on FULL pool ===")
# Build same masks on FULL pool (fe_all, ce_all) — but H8/H9/H10/H13/H14/H15 features need to be enriched on full pool too
# For coverage estimation: re-run enrichment on FULL pool (might be slower)
# Strategy: enrich only the additional new rule columns we plan to use
log("re-enriching FULL pool (fe_all, ce_all) for composite test ...")

# We need: best_ask_frac, max_sell_size_15s, sell_vol_2s, utc_hour, h13_maker_lt5, pair_ask_sum bands
def enrich_full_for_composite(df):
    df = df.copy()
    # H9 best_ask_frac, ask_top5_frac, sum_ask_top25
    rows = []
    for r in df.itertuples(index=False):
        b = book_at(r.slug, r.outcome, r.t_sec)
        if b is None:
            rows.append([np.nan]*3); continue
        ap, asz, bp, bsz = b
        sum_ask_top25 = float(np.nansum(asz[:25]))
        sum_ask_top5  = float(np.nansum(asz[:5]))
        ask_top5_frac  = (sum_ask_top5 / sum_ask_top25) if sum_ask_top25 > 0 else np.nan
        best_ask_frac  = (float(asz[0]) / sum_ask_top25) if sum_ask_top25 > 0 else np.nan
        rows.append([sum_ask_top25, ask_top5_frac, best_ask_frac])
    arr = np.array(rows)
    df["h9_sum_ask_top25"] = arr[:,0]
    df["h9_ask_top5_frac"] = arr[:,1]
    df["h9_best_ask_frac"] = arr[:,2]
    # H10 max_sell_size_15s
    s_15 = [burst_features(r.slug, r.outcome, r.t_sec, 15) for r in df.itertuples(index=False)]
    df["h10_max_sell_size_15s"] = [f.get("max_sell_size", np.nan) if f else np.nan for f in s_15]
    df["h10_n_trades_15s"]      = [f.get("n_trades", np.nan) if f else np.nan for f in s_15]
    # H14 sell_vol_2s
    mv = [micro_vol(r.slug, r.outcome, int(r.t_sec)*1_000_000, 2_000_000) for r in df.itertuples(index=False)]
    arr2 = np.array(mv)
    df["h14_sell_vol_2s"] = arr2[:,0]
    df["h14_tot_vol_2s"]  = arr2[:,2]
    # H12
    df["utc_hour"] = (df.t_sec.astype("int64") // 3600 % 24).astype("int64")
    return df

# Reload v5 to get full pool — we may need to also re-load 1.5x richer
log("  enriching fe_all (V1-unexplained pool) ...")
fe_all_e = enrich_full_for_composite(fe_all)
log("  enriching ce_all ...")
ce_all_e = enrich_full_for_composite(ce_all)
log(f"  fe_all_e n={len(fe_all_e)}  ce_all_e n={len(ce_all_e)}")

# Build composite candidates
def base_rules(df):
    """V1 + V2 base composite (Rules A, B, C)."""
    return df.disc_capture | (df.pm_drop_5s > 0.02) | ((df.offset_s >= 0) & (df.offset_s <= 60))

V2_FIRE_CAPTURED = int(base_rules(fe_all).sum())
V2_CTRL_CAPTURED = int(base_rules(ce_all).sum())
TOTAL_FIRE_FULL = 1349  # from V5 summary
TOTAL_CTRL_FULL = 1401
log(f"V2 baseline coverage on V1-unexplained pool: fire {V2_FIRE_CAPTURED}/{len(fe_all)} ({V2_FIRE_CAPTURED/len(fe_all):.3f}), ctrl {V2_CTRL_CAPTURED}/{len(ce_all)}")
log(f"V2 baseline coverage on FULL pool (incl disc-captured upstream): fire {V2_FIRE_CAPTURED}/{TOTAL_FIRE_FULL} ({V2_FIRE_CAPTURED/TOTAL_FIRE_FULL:.3f})")

# 'fe_all' is the V1-unexplained 807 set (disc_capture=False for all).
# Full pool of 1349 = 542 V1-captured + 807 V1-unexplained.
# So coverage on the FULL pool = (542 + V2_FIRE_CAPTURED) / 1349  (since V1 disc_capture is the strongest signal already in V1)
fe_v1_captured = TOTAL_FIRE_FULL - len(fe_all)  # 542
ce_v1_captured = TOTAL_CTRL_FULL - len(ce_all)  # 399
fe_v2_total_captured = fe_v1_captured + V2_FIRE_CAPTURED
ce_v2_total_captured = ce_v1_captured + V2_CTRL_CAPTURED
log(f"V2 TOTAL FULL coverage: fire={fe_v2_total_captured}/{TOTAL_FIRE_FULL} = {fe_v2_total_captured/TOTAL_FIRE_FULL:.3f}, ctrl={ce_v2_total_captured}/{TOTAL_CTRL_FULL} = {ce_v2_total_captured/TOTAL_CTRL_FULL:.3f}")

# Now test V3 composite candidates — V2 OR new rule
def composite_eval(name, new_fire_mask, new_ctrl_mask):
    """new_fire_mask is on fe_all_e (V1-un); we OR with V2 base, then add V1-captured count."""
    new_only_fire = (~base_rules(fe_all_e)) & new_fire_mask
    new_only_ctrl = (~base_rules(ce_all_e)) & new_ctrl_mask
    fire_cap = V2_FIRE_CAPTURED + int(new_only_fire.sum()) + fe_v1_captured
    ctrl_cap = V2_CTRL_CAPTURED + int(new_only_ctrl.sum()) + ce_v1_captured
    fr = fire_cap / TOTAL_FIRE_FULL
    cr = ctrl_cap / TOTAL_CTRL_FULL
    lift = fr / cr if cr > 0 else float("inf")
    # z on FULL pool
    z = wilson_z(fr, TOTAL_FIRE_FULL, cr, TOTAL_CTRL_FULL)
    inc_fire = int(new_only_fire.sum())
    inc_ctrl = int(new_only_ctrl.sum())
    return {
        "name": name,
        "fire_cap": fire_cap, "ctrl_cap": ctrl_cap,
        "fire_pct": fr, "ctrl_pct": cr, "lift": lift, "z": z,
        "inc_fire": inc_fire, "inc_ctrl": inc_ctrl,
    }

composites = []
# baseline (V2)
composites.append({
    "name": "V2 baseline (A OR B OR C)",
    "fire_cap": fe_v2_total_captured, "ctrl_cap": ce_v2_total_captured,
    "fire_pct": fe_v2_total_captured/TOTAL_FIRE_FULL, "ctrl_pct": ce_v2_total_captured/TOTAL_CTRL_FULL,
    "lift": (fe_v2_total_captured/TOTAL_FIRE_FULL) / (ce_v2_total_captured/TOTAL_CTRL_FULL),
    "z": wilson_z(fe_v2_total_captured/TOTAL_FIRE_FULL, TOTAL_FIRE_FULL,
                  ce_v2_total_captured/TOTAL_CTRL_FULL, TOTAL_CTRL_FULL),
    "inc_fire": 0, "inc_ctrl": 0,
})

# Best individual new candidates discovered in tests above (pick top 5 lift)
# Pre-build a small list of promising candidates to bolt on
cand_specs = [
    ("V3a: + h9_best_ask_frac < 0.40",        fe_all_e.h9_best_ask_frac < 0.40,   ce_all_e.h9_best_ask_frac < 0.40),
    ("V3b: + h10_max_sell_size_15s > 50",     fe_all_e.h10_max_sell_size_15s > 50, ce_all_e.h10_max_sell_size_15s > 50),
    ("V3c: + h10_n_trades_15s > 5",           fe_all_e.h10_n_trades_15s > 5,       ce_all_e.h10_n_trades_15s > 5),
    ("V3d: + h14_sell_vol_2s > 0",            fe_all_e.h14_sell_vol_2s > 0,        ce_all_e.h14_sell_vol_2s > 0),
    ("V3e: + h14_tot_vol_2s > 0",             fe_all_e.h14_tot_vol_2s > 0,         ce_all_e.h14_tot_vol_2s > 0),
    ("V3f: + h9_ask_top5_frac > 0.70",        fe_all_e.h9_ask_top5_frac > 0.70,    ce_all_e.h9_ask_top5_frac > 0.70),
    ("V3g: + h9_sum_ask_top25 < 200",         fe_all_e.h9_sum_ask_top25 < 200,     ce_all_e.h9_sum_ask_top25 < 200),
]
for name, fm, cm in cand_specs:
    composites.append(composite_eval(name, fm, cm))

# Top-combined: V2 OR several together
for combo_name, combo_fm, combo_cm in [
    ("V3 BEST: V2 OR (h10_max_sell_size_15s>50 OR h14_sell_vol_2s>0)",
        (fe_all_e.h10_max_sell_size_15s > 50) | (fe_all_e.h14_sell_vol_2s > 0),
        (ce_all_e.h10_max_sell_size_15s > 50) | (ce_all_e.h14_sell_vol_2s > 0)),
    ("V3 ALL: V2 OR (h10_max>50 OR h14_2s>0 OR h9_best_ask_frac<0.40)",
        (fe_all_e.h10_max_sell_size_15s > 50) | (fe_all_e.h14_sell_vol_2s > 0) | (fe_all_e.h9_best_ask_frac < 0.40),
        (ce_all_e.h10_max_sell_size_15s > 50) | (ce_all_e.h14_sell_vol_2s > 0) | (ce_all_e.h9_best_ask_frac < 0.40)),
]:
    composites.append(composite_eval(combo_name, combo_fm, combo_cm))

print("\n=== COMPOSITE RULE COVERAGE (FULL pool) ===")
print(f"{'rule':<70} {'fire%':>8} {'ctrl%':>8} {'lift':>6} {'z':>6} {'+fire':>6}/{'+ctrl':<6}")
print("-"*120)
for c in composites:
    print(f"{c['name']:<70} {c['fire_pct']*100:>7.1f}% {c['ctrl_pct']*100:>7.1f}% {c['lift']:>6.2f} {c['z']:>+6.2f} {c['inc_fire']:>6}/{c['inc_ctrl']:<6}")

# =====================================================================
# 13. LEFTOVER-ON-WINNER analysis: of fires STILL un-explained after V3, do they make money?
# =====================================================================
log("\n=== leftover-on-winner check ===")
# We need to join un-explained fires to outcomes (resolution) — fe parquet has slug+outcome
# Win = bought side matches outcome.
# Bought-side = outcome (which is the SIDE they BOUGHT, not the market winner)
# The market winner is in load_resolutions.
from load import load_resolutions
res = load_resolutions()
log(f"  resolutions: cols={list(res.columns)} rows={len(res)}")
# Build slug -> winning outcome map
res_idx = res.set_index("slug")["outcome"].to_dict()  # outcome col in res is the winning Up/Down

def add_won(df):
    df = df.copy()
    df["winner"] = df.slug.map(res_idx)
    df["won"] = (df.outcome == df.winner)
    return df
fe_un_w = add_won(fe_un)
log(f"  fe_un (V3-unexplained) win rate: {fe_un_w.won.mean():.3f} n={len(fe_un_w)} (NaN={fe_un_w.won.isna().sum()})")
fe_all_w = add_won(fe_all)
log(f"  fe_all (V1-unexplained) win rate: {fe_all_w.won.mean():.3f}")
# compare to a V1-captured subset
# (we don't have the V1-captured fires in this parquet; can only compare V2-captured vs V2-un)
fe_v2_un = fe_all_e[~base_rules(fe_all_e)]
fe_v2_cap = fe_all_e[base_rules(fe_all_e)]
fe_v2_un_w = add_won(fe_v2_un)
fe_v2_cap_w = add_won(fe_v2_cap)
log(f"  V2-captured (in V1-un pool) win rate: {fe_v2_cap_w.won.mean():.3f} n={len(fe_v2_cap_w)}")
log(f"  V2-un (residual) win rate:        {fe_v2_un_w.won.mean():.3f} n={len(fe_v2_un_w)}")

# =====================================================================
# 14. SAVE SUMMARY
# =====================================================================
summary = {
    "fire_n_full":             TOTAL_FIRE_FULL,
    "ctrl_n_full":             TOTAL_CTRL_FULL,
    "fire_n_v1_unexplained":   len(fe_all),
    "ctrl_n_v1_unexplained":   len(ce_all),
    "fire_n_v3_unexplained":   len(fe_un),
    "ctrl_n_v3_unexplained":   len(ce_un),
    "v2_baseline_coverage_full_fires":  fe_v2_total_captured/TOTAL_FIRE_FULL,
    "v2_baseline_coverage_full_ctrls":  ce_v2_total_captured/TOTAL_CTRL_FULL,
    "hypothesis_tests": tests,
    "composite_results": composites,
    "winrate": {
        "v3_unexplained": float(fe_un_w.won.mean()),
        "v1_unexplained": float(fe_all_w.won.mean()),
        "v2_captured":    float(fe_v2_cap_w.won.mean()),
        "v2_unexplained": float(fe_v2_un_w.won.mean()),
    },
}
with open(OUT_SUMMARY, "w", encoding="utf-8") as f:
    json.dump(summary, f, default=float, indent=2)
log(f"saved {OUT_SUMMARY}")
log(f"total runtime {(time.time()-_t0):.1f}s")
