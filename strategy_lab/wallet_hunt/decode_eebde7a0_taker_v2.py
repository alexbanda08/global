"""Decode taker trigger v2 — focus on cost-basis pair-arb + book staleness.

Key new tests:
  1. cost_basis_other_side = VWAP of all maker/taker BUYS of opposite outcome in this slug so far
     - if take_price + cost_basis_other < $1, then pair has POSITIVE expected payout
     - this is the REAL trigger: complete a sub-$1 pair regardless of book
  2. own_ask_at_take_actual = compare take_price to recent OWN ask snapshots (find the closest moment
     where book showed ask <= take_price)
  3. Binance momentum via binance-spot-ws (correct source)
"""
from __future__ import annotations
import os, sys, time, json, gc
import numpy as np
import pandas as pd
from pathlib import Path

t0 = time.time()
def log(msg):
    print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

CACHE  = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xeebde7a0"
OUT_DIR = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xeebde7a0_taker_decode"
OUT_DIR.mkdir(exist_ok=True)

# ---------- Step 1: load ----------
log("loading trades ...")
tr = pd.read_parquet(CACHE / "trades_chain.parquet")
look = pd.read_parquet(ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_token_lookup.parquet")[
    ["asset_id","slug","outcome","market_class","mkt_asset"]
]
tr["asset_id"] = tr["asset"].astype(str)
look["asset_id"] = look["asset_id"].astype(str)
m = tr.merge(look, on="asset_id", how="left").rename(columns={"size":"shares"})
m5 = m[(m["mkt_asset"]=="BTC") & (m["market_class"]=="updown_5m")].copy()
m5 = m5[(m5["price"] > 0) & (m5["price"] < 1.0001) & (m5["shares"] > 0)].copy()
m5["slot_start"] = m5["slug"].str.rsplit("-", n=1).str[-1].astype(np.int64)
m5["t_sec"] = m5["timestamp"].astype(np.int64)
m5["offset_s"] = m5["t_sec"] - m5["slot_start"]
m5 = m5.sort_values("t_sec").reset_index(drop=True)
m5 = m5[(m5["offset_s"] >= -120) & (m5["offset_s"] <= 360)].copy()

# Sample top-density slugs
taker_per_slug = m5[~m5.wallet_is_maker].groupby("slug").size().sort_values(ascending=False)
sampled_slugs = list(taker_per_slug.head(600).index)
m5s = m5[m5["slug"].isin(sampled_slugs)].copy()
log(f"  in-window BTC 5m: {len(m5):,}, sampled {len(sampled_slugs)} slugs -> {len(m5s):,} rows")

# ---------- Step 2: compute per-slug, per-outcome cumulative position + VWAP cost basis ----------
def cumstate(df_slug: pd.DataFrame) -> pd.DataFrame:
    df = df_slug.sort_values(["t_sec","log_index"]).reset_index(drop=True).copy()
    # signed shares delta and signed cash flow PER ROW
    sgn = np.where(df["side"].values == "BUY", 1.0, -1.0)
    is_up = (df["outcome"].values == "Up").astype(np.float64)
    is_dn = (df["outcome"].values == "Down").astype(np.float64)
    dshares = sgn * df["shares"].values
    dnotional = sgn * df["usdc_notional"].values
    # cumulative shares & cumulative dollars on each side
    cs_up = np.cumsum(dshares * is_up)
    cs_dn = np.cumsum(dshares * is_dn)
    cd_up = np.cumsum(dnotional * is_up)
    cd_dn = np.cumsum(dnotional * is_dn)
    # state BEFORE current row (shift by 1)
    df["inv_up_before"]   = np.concatenate([[0.0], cs_up[:-1]])
    df["inv_dn_before"]   = np.concatenate([[0.0], cs_dn[:-1]])
    df["cash_up_before"]  = np.concatenate([[0.0], cd_up[:-1]])
    df["cash_dn_before"]  = np.concatenate([[0.0], cd_dn[:-1]])
    return df

log("computing per-slug cumulative state ...")
m5s = m5s.groupby("slug", group_keys=False, sort=False).apply(cumstate, include_groups=True).reset_index(drop=True)

# Helper: VWAP cost basis of long-position side
def vwap(cash, shares):
    return np.where(shares > 0.001, cash / np.maximum(shares, 1e-9), np.nan)

# ---------- Step 3: load L25 books ----------
from load import load_orderbook_l25_streaming, load_klines_asof

log(f"streaming L25 books for {len(sampled_slugs)} slugs ...")
books = load_orderbook_l25_streaming("btc", slugs=set(sampled_slugs), subsample_1hz=False)
# subsample_1hz=False -> full microsecond resolution (might be heavy but more accurate)
log(f"  loaded {len(books):,} (slug, outcome) book series")

def book_at(slug, outcome, ts_us):
    rec = books.get((slug, outcome))
    if rec is None: return None
    ts_sorted, ap, asz, bp, bsz = rec
    idx = np.searchsorted(ts_sorted, ts_us, side="right") - 1
    if idx < 0: return None
    ap_row, asz_row = ap[idx], asz[idx]
    bp_row, bsz_row = bp[idx], bsz[idx]
    nz_a, nz_b = ap_row > 0, bp_row > 0
    if not nz_a.any() or not nz_b.any(): return None
    best_ask = float(ap_row[nz_a].min())
    best_bid = float(bp_row[nz_b].max())
    # window for med ask 60s back
    t_lo = ts_us - 60_000_000
    lo_i = np.searchsorted(ts_sorted, t_lo, side="left")
    hi_i = idx + 1
    if hi_i - lo_i > 1:
        ap_win = ap[lo_i:hi_i]
        ap_masked = np.where(ap_win > 0, ap_win, np.inf)
        best_ask_per_snap = ap_masked.min(axis=1)
        best_ask_per_snap = best_ask_per_snap[best_ask_per_snap < np.inf]
        med = float(np.median(best_ask_per_snap)) if len(best_ask_per_snap) >= 3 else best_ask
    else:
        med = best_ask
    # 5-second min ask (lowest ask seen in [ts-5s, ts])
    t_lo5 = ts_us - 5_000_000
    lo5 = np.searchsorted(ts_sorted, t_lo5, side="left")
    if hi_i - lo5 > 0:
        ap_win5 = ap[lo5:hi_i]
        ap5_masked = np.where(ap_win5 > 0, ap_win5, np.inf)
        per_snap5 = ap5_masked.min(axis=1)
        per_snap5 = per_snap5[per_snap5 < np.inf]
        min_ask_5s = float(per_snap5.min()) if len(per_snap5) else best_ask
    else:
        min_ask_5s = best_ask
    return dict(best_ask=best_ask, best_bid=best_bid,
                recent_med_ask_60s=med, min_ask_5s=min_ask_5s)

# ---------- Step 4: enrich taker fires ----------
log("enriching TAKER fires ...")
tk = m5s[~m5s.wallet_is_maker].copy()
N_FIRES = 2000
if len(tk) > N_FIRES:
    tk = tk.sample(N_FIRES, random_state=42).sort_values("t_sec").reset_index(drop=True)
log(f"  sampled {len(tk):,}")

rows = []
miss = 0
for i, r in enumerate(tk.itertuples(index=False)):
    if i % 400 == 0:
        log(f"  enrich {i}/{len(tk)} miss={miss}")
    ts_us = int(r.t_sec) * 1_000_000
    own = book_at(r.slug, r.outcome, ts_us)
    other_oc = "Down" if r.outcome == "Up" else "Up"
    oth = book_at(r.slug, other_oc, ts_us)
    if own is None or oth is None:
        miss += 1; rows.append(None); continue
    # cost basis on each side BEFORE this fire
    inv_other = float(r.inv_up_before if r.outcome=="Down" else r.inv_dn_before)
    cash_other= float(r.cash_up_before if r.outcome=="Down" else r.cash_dn_before)
    cb_other = (cash_other / inv_other) if inv_other > 0.001 else np.nan
    inv_own  = float(r.inv_up_before if r.outcome=="Up" else r.inv_dn_before)
    cash_own = float(r.cash_up_before if r.outcome=="Up" else r.cash_dn_before)
    cb_own  = (cash_own / inv_own) if inv_own > 0.001 else np.nan
    # pair effective cost = take_price + cost_basis_other (if other side already long)
    pair_eff_cost = (r.price + cb_other) if not np.isnan(cb_other) else np.nan
    rows.append(dict(
        slug=r.slug, outcome=r.outcome, t_sec=r.t_sec, slot_start=r.slot_start,
        offset_s=r.offset_s, take_price=r.price, take_size=r.shares, take_notional=r.usdc_notional,
        own_best_ask=own["best_ask"], own_best_bid=own["best_bid"],
        oth_best_ask=oth["best_ask"], oth_best_bid=oth["best_bid"],
        pair_ask_sum=own["best_ask"]+oth["best_ask"],
        pair_bid_sum=own["best_bid"]+oth["best_bid"],
        recent_med_ask_60s=own["recent_med_ask_60s"],
        min_ask_5s=own["min_ask_5s"],
        ask_drop_from_60s=own["recent_med_ask_60s"] - own["best_ask"],
        own_ask_vs_take=own["best_ask"] - r.price,   # >0 = book ask is HIGHER than take_price (timing artifact)
        inv_own_before=inv_own, inv_other_before=inv_other,
        cb_own=cb_own, cb_other=cb_other,
        pair_eff_cost=pair_eff_cost,
    ))

en = pd.DataFrame([x for x in rows if x is not None])
log(f"enriched {len(en):,} (miss {miss})")

# ---------- Step 5: binance momentum (via binance-spot-ws) ----------
log("loading binance-spot-ws klines ...")
try:
    end_us, close = load_klines_asof("BTC", "binance-spot-ws", "1MIN")
    def ret_60s(ts_us):
        idx = np.searchsorted(end_us, ts_us, side="right") - 1
        idx_prev = np.searchsorted(end_us, ts_us - 60_000_000, side="right") - 1
        if idx < 0 or idx_prev < 0: return np.nan
        return float(close[idx] / close[idx_prev] - 1.0)
    en["binance_ret_60s"] = en["t_sec"].astype(np.int64).mul(1_000_000).map(ret_60s)
    log(f"  binance enriched (non-NaN: {en.binance_ret_60s.notna().sum()})")
except Exception as e:
    log(f"  binance fail: {e}")
    en["binance_ret_60s"] = np.nan

# Save
en.to_parquet(OUT_DIR / "enriched_taker_fires_v2.parquet")

# ---------- Step 6: hypothesis tests ----------
print("\n" + "=" * 60)
print("V2 HYPOTHESIS TESTS")
print("=" * 60)

print(f"\nn taker fires: {len(en):,}")
print(f"outcome split: Up={int((en.outcome=='Up').sum())}  Down={int((en.outcome=='Down').sum())}")

# 0. book staleness check
print("\n--- 0. BOOK STALENESS ---")
print(f"own_ask_vs_take (book_ask - take_price) cents:")
print(((en.own_best_ask - en.take_price)*100).describe(percentiles=[.1,.25,.5,.75,.9]).to_string())
print(f"% where take_price >= book_ask (consistent w/ ask hit): {(en.take_price >= en.own_best_ask - 0.001).mean()*100:.1f}%")
print(f"% where take_price < book_ask by >2c (book stale OR price level walked): {(en.take_price < en.own_best_ask - 0.02).mean()*100:.1f}%")

# A. REBALANCE (refined)
imbal = en.inv_own_before - en.inv_other_before
print("\n--- A. REBALANCE ---")
print(f"% bought-side underweight (imbalance<0):       {(imbal<0).mean()*100:.1f}%")
print(f"% bought-side strongly underweight (<-1):      {(imbal<-1).mean()*100:.1f}%")
print(f"% other-side already long (inv_other>0):       {(en.inv_other_before>0.001).mean()*100:.1f}%")
print(f"% bought-side ZERO position (fresh leg buy):   {(en.inv_own_before<0.001).mean()*100:.1f}%")
print(f"% other-side long AND bought-side underweight: {((en.inv_other_before>0.001) & (imbal<0)).mean()*100:.1f}%")

# B. PAIR EFFECTIVE COST
print("\n--- B1. PAIR EFFECTIVE COST (take_price + cost_basis_other_side) ---")
mask_pair = en.cb_other.notna()
print(f"n with cb_other present: {mask_pair.sum():,}  ({mask_pair.mean()*100:.1f}%)")
if mask_pair.sum() > 0:
    pec = en.loc[mask_pair, "pair_eff_cost"]
    print(f"pair_eff_cost dist:")
    print(pec.describe(percentiles=[.05,.1,.25,.5,.75,.9,.95]).to_string())
    print(f"% pair_eff_cost < $1.00 (locks in +EV):  {(pec<1.0).mean()*100:.1f}%")
    print(f"% pair_eff_cost < $0.98:                 {(pec<0.98).mean()*100:.1f}%")
    print(f"% pair_eff_cost < $0.95:                 {(pec<0.95).mean()*100:.1f}%")
    print(f"% pair_eff_cost < $0.90:                 {(pec<0.90).mean()*100:.1f}%")

# B2. DISCOUNT (take below recent median)
print("\n--- B2. DISCOUNT FROM 60s MEDIAN ASK ---")
print(f"ask_drop_from_60s_median dist (cents):")
print((en.ask_drop_from_60s*100).describe(percentiles=[.1,.25,.5,.75,.9,.95]).to_string())
print(f"% drop > 0: {(en.ask_drop_from_60s>0).mean()*100:.1f}%")
print(f"% drop > 3c: {(en.ask_drop_from_60s>0.03).mean()*100:.1f}%")
print(f"% drop > 5c: {(en.ask_drop_from_60s>0.05).mean()*100:.1f}%")

# C. MOMENTUM
print("\n--- C. MOMENTUM ---")
if en.binance_ret_60s.notna().any():
    en2 = en.dropna(subset=["binance_ret_60s"]).copy()
    en2["dir"] = np.where(en2.binance_ret_60s>0, "Up", "Down")
    print(f"n with binance: {len(en2)}  match rate (all): {(en2['dir']==en2.outcome).mean()*100:.1f}%")
    for thr in [0.0001, 0.0005, 0.001, 0.002]:
        sub = en2[en2.binance_ret_60s.abs() >= thr]
        if len(sub)==0: continue
        print(f"  |ret|>={thr*100:.2f}%: n={len(sub)}  match={(sub['dir']==sub.outcome).mean()*100:.1f}%")
else:
    print("no binance loaded")

# D. take_size vs notional behavior
print("\n--- D. TAKE SIZE & NOTIONAL ---")
print(f"take_notional dist:")
print(en.take_notional.describe(percentiles=[.25,.5,.75,.9,.95,.99]).to_string())
print(f"take_size (shares) dist:")
print(en.take_size.describe(percentiles=[.25,.5,.75,.9,.95,.99]).to_string())

# Summary stats for decision tree
summary = dict(
    n=len(en),
    pct_pair_eff_lt_1=float((en.pair_eff_cost<1.0).mean()) if mask_pair.sum() else None,
    pct_pair_eff_lt_098=float((en.pair_eff_cost<0.98).mean()) if mask_pair.sum() else None,
    pct_pair_eff_lt_095=float((en.pair_eff_cost<0.95).mean()) if mask_pair.sum() else None,
    pct_other_long=float((en.inv_other_before>0.001).mean()),
    pct_bought_zero=float((en.inv_own_before<0.001).mean()),
    pct_ask_drop_gt_3c=float((en.ask_drop_from_60s>0.03).mean()),
    pct_ask_drop_gt_5c=float((en.ask_drop_from_60s>0.05).mean()),
    median_take_notional=float(en.take_notional.median()),
    p95_take_notional=float(en.take_notional.quantile(0.95)),
)
(OUT_DIR / "summary_v2.json").write_text(json.dumps(summary, indent=2))
log(f"summary saved")
log(f"DONE in {time.time()-t0:.1f}s")
