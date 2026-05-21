"""Decode taker (market-buy) trigger for wallet 0xeebde7a0...

Pipeline:
  1. Load trades_chain, filter to BTC 5m, classify maker/taker
  2. Sample N slugs to bound L25 RAM (~2k slugs out of 1341)
  3. Load L25 books for sampled slugs + binance 1s klines
  4. For each TAKER fire: enrich with best_bid/ask, sum_asks, recent_median_ask_60s,
     binance_ret_60s, AND wallet inventory before fire
  5. Test hypotheses A/B/C
  6. Distill decision rule
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

WALLET = "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30"
CACHE  = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xeebde7a0"
OUT_DIR = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xeebde7a0_taker_decode"
OUT_DIR.mkdir(exist_ok=True)

# ---------- Step 1: load + filter ----------
log("loading trades_chain + token lookup ...")
tr = pd.read_parquet(CACHE / "trades_chain.parquet")
look = pd.read_parquet(ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_token_lookup.parquet")[
    ["asset_id","slug","outcome","market_class","mkt_asset"]
]
tr["asset_id"] = tr["asset"].astype(str)
look["asset_id"] = look["asset_id"].astype(str)
m = tr.merge(look, on="asset_id", how="left").rename(columns={"size":"shares"})
m5 = m[(m["mkt_asset"]=="BTC") & (m["market_class"]=="updown_5m")].copy()
# sane prices only
m5 = m5[(m5["price"] > 0) & (m5["price"] < 1.0001) & (m5["shares"] > 0)].copy()
m5["slot_start"] = m5["slug"].str.rsplit("-", n=1).str[-1].astype(np.int64)
m5["t_sec"] = m5["timestamp"].astype(np.int64)
m5["offset_s"] = m5["t_sec"] - m5["slot_start"]
m5 = m5.sort_values("t_sec").reset_index(drop=True)
log(f"  BTC 5m trades: {len(m5):,}  maker={int(m5.wallet_is_maker.sum()):,}  "
    f"taker={int((~m5.wallet_is_maker).sum()):,}  slugs={m5.slug.nunique():,}")

# Keep only trades within slot window (-60s before to +300s after slot_start)
# This focuses on actual game-time fires not weird stragglers
m5 = m5[(m5["offset_s"] >= -120) & (m5["offset_s"] <= 360)].copy()
log(f"  in-window: {len(m5):,}")

# ---------- Step 2: sample slugs ----------
all_slugs = sorted(m5["slug"].unique())
# Bias to high-taker-activity slugs (these are the ones we can learn from)
taker_per_slug = m5[~m5.wallet_is_maker].groupby("slug").size().sort_values(ascending=False)
# Take top 600 slugs by taker fires
SAMPLE_N = 600
sampled_slugs = list(taker_per_slug.head(SAMPLE_N).index)
log(f"  sampled {len(sampled_slugs)} slugs (top taker-density), "
    f"covering {m5[m5.slug.isin(sampled_slugs)].pipe(lambda d: (~d.wallet_is_maker).sum())} taker fires")

m5s = m5[m5["slug"].isin(sampled_slugs)].copy()

# ---------- Step 3: load L25 books for sampled slugs ----------
from load import load_orderbook_l25_streaming, load_klines_asof, asof_strict

log(f"streaming L25 books for {len(sampled_slugs)} slugs ...")
books = load_orderbook_l25_streaming("btc", slugs=set(sampled_slugs), subsample_1hz=True)
log(f"  loaded {len(books):,} (slug, outcome) book series")

# ---------- Step 4: compute wallet inventory + book context per taker fire ----------
log("computing wallet inventory state per slug ...")

# Per slug, compute cumulative shares position by outcome before each fire
def inv_before(df_slug: pd.DataFrame) -> pd.DataFrame:
    """For each row, add inv_up_before / inv_dn_before (wallet's holdings just before this fire).
    Wallet POV:
        side == 'BUY'  -> shares ADDED to outcome inventory
        side == 'SELL' -> shares REMOVED from outcome inventory
    """
    df_slug = df_slug.sort_values(["t_sec","log_index"]).reset_index(drop=True)
    delta = np.where(df_slug["side"].values == "BUY", df_slug["shares"].values, -df_slug["shares"].values)
    is_up = (df_slug["outcome"].values == "Up").astype(np.float64)
    is_dn = (df_slug["outcome"].values == "Down").astype(np.float64)
    cum_up = np.cumsum(delta * is_up)
    cum_dn = np.cumsum(delta * is_dn)
    # "before" = state just prior to this row, so shift right by 1
    inv_up_before = np.concatenate([[0.0], cum_up[:-1]])
    inv_dn_before = np.concatenate([[0.0], cum_dn[:-1]])
    df_slug["inv_up_before"] = inv_up_before
    df_slug["inv_dn_before"] = inv_dn_before
    return df_slug

m5s = m5s.groupby("slug", group_keys=False).apply(inv_before).reset_index(drop=True)
log(f"  inventory computed")

# ---------- book lookup helper ----------
def book_at(slug: str, outcome: str, ts_us: int):
    """Return (best_ask, best_bid, sum_asks_at_1.005, depth_at_ask, recent_median_ask_60s)
    or None if no data."""
    rec = books.get((slug, outcome))
    if rec is None:
        return None
    ts_sorted, ap, asz, bp, bsz = rec
    # asof - find largest ts <= ts_us
    idx = np.searchsorted(ts_sorted, ts_us, side="right") - 1
    if idx < 0 or idx >= len(ts_sorted):
        return None
    ap_row = ap[idx]; asz_row = asz[idx]; bp_row = bp[idx]; bsz_row = bsz[idx]
    # best ask = lowest non-zero ask price; best bid = highest non-zero bid price
    nz_a = ap_row > 0
    nz_b = bp_row > 0
    if not nz_a.any() or not nz_b.any():
        return None
    best_ask = float(ap_row[nz_a].min())
    best_bid = float(bp_row[nz_b].max())
    # sum of ask sizes at first level
    best_ask_size = float(asz_row[ap_row == best_ask].sum())
    best_bid_size = float(bsz_row[bp_row == best_bid].sum())
    # recent_median_ask_60s: walk back 60s
    t_lo = ts_us - 60_000_000
    lo_i = np.searchsorted(ts_sorted, t_lo, side="left")
    hi_i = idx + 1
    if hi_i - lo_i > 1:
        # for each snapshot in window, take best_ask
        ap_win = ap[lo_i:hi_i]
        # mask 0s: replace with inf, then min across levels
        ap_masked = np.where(ap_win > 0, ap_win, np.inf)
        best_ask_per_snap = ap_masked.min(axis=1)
        best_ask_per_snap = best_ask_per_snap[best_ask_per_snap < np.inf]
        if len(best_ask_per_snap) >= 3:
            med = float(np.median(best_ask_per_snap))
        else:
            med = best_ask
    else:
        med = best_ask
    return dict(best_ask=best_ask, best_bid=best_bid,
                best_ask_size=best_ask_size, best_bid_size=best_bid_size,
                recent_median_ask_60s=med, n_snaps=hi_i - lo_i)

# ---------- enrich taker fires ----------
log("enriching TAKER fires with book context ...")
tk = m5s[~m5s.wallet_is_maker].copy()
log(f"  taker rows in sampled slugs: {len(tk):,}")

# Sample 2000 taker fires uniformly
N_FIRES = 2000
if len(tk) > N_FIRES:
    tk = tk.sample(N_FIRES, random_state=42).sort_values("t_sec").reset_index(drop=True)
log(f"  sampled {len(tk):,} taker fires")

rows = []
miss = 0
for i, r in enumerate(tk.itertuples(index=False)):
    if i % 200 == 0:
        log(f"  enrich {i}/{len(tk)}  miss={miss}")
    ts_us = int(r.t_sec) * 1_000_000
    # Book at side bought (their outcome)
    own = book_at(r.slug, r.outcome, ts_us)
    other_oc = "Down" if r.outcome == "Up" else "Up"
    oth = book_at(r.slug, other_oc, ts_us)
    if own is None or oth is None:
        miss += 1
        rows.append(None); continue
    pair_ask_sum = own["best_ask"] + oth["best_ask"]
    pair_bid_sum = own["best_bid"] + oth["best_bid"]
    # ask drop from rolling median (positive = cheaper than usual)
    ask_drop = own["recent_median_ask_60s"] - own["best_ask"]
    # ask drop from $0.50 baseline ('fair' for 5m updown is roughly 0.5)
    drop_from_50 = 0.50 - own["best_ask"]
    rows.append(dict(
        slug=r.slug, outcome=r.outcome, t_sec=r.t_sec, slot_start=r.slot_start,
        offset_s=r.offset_s, take_price=r.price, take_size=r.shares,
        own_best_ask=own["best_ask"], own_best_bid=own["best_bid"],
        own_ask_sz=own["best_ask_size"], own_bid_sz=own["best_bid_size"],
        oth_best_ask=oth["best_ask"], oth_best_bid=oth["best_bid"],
        oth_ask_sz=oth["best_ask_size"], oth_bid_sz=oth["best_bid_size"],
        pair_ask_sum=pair_ask_sum, pair_bid_sum=pair_bid_sum,
        recent_med_ask_60s=own["recent_median_ask_60s"],
        ask_drop_from_60s=ask_drop, drop_from_50=drop_from_50,
        inv_up_before=r.inv_up_before, inv_dn_before=r.inv_dn_before,
    ))

en = pd.DataFrame([x for x in rows if x is not None])
log(f"enriched {len(en):,} taker fires (missed {miss} due to no book)")

# ---------- Step 4b: binance momentum context (BTC 1s klines, t-60s..t window) ----------
log("loading binance 1m klines for momentum ...")
try:
    klines = load_klines_asof("btc", "1m")
    # klines is dict with keys 'end_us', 'open','high','low','close'
    if isinstance(klines, dict):
        end_us = klines["end_us"]
        close = klines["close"]
    else:
        # If DataFrame
        end_us = klines["end_us"].values
        close = klines["close"].values
    def ret_60s(ts_us):
        # close of bar that ended at-or-before ts_us, vs close 60s earlier
        idx = np.searchsorted(end_us, ts_us, side="right") - 1
        idx_prev = np.searchsorted(end_us, ts_us - 60_000_000, side="right") - 1
        if idx < 0 or idx_prev < 0: return np.nan
        return float(close[idx] / close[idx_prev] - 1.0)
    en["binance_ret_60s"] = en["t_sec"].astype(np.int64).mul(1_000_000).map(ret_60s)
    log(f"  binance enriched (non-NaN: {en.binance_ret_60s.notna().sum():,})")
except Exception as e:
    log(f"  binance failed: {e}")
    en["binance_ret_60s"] = np.nan

# Save
en.to_parquet(OUT_DIR / "enriched_taker_fires.parquet")
log(f"saved {OUT_DIR/'enriched_taker_fires.parquet'}")

# ---------- Step 5: hypotheses ----------
log("=" * 60)
log("HYPOTHESIS TESTS")
log("=" * 60)

# Sanity prints
print("\n--- SAMPLE SUMMARY ---")
print(f"n taker fires (with book context): {len(en):,}")
print(f"outcome split: Up={int((en.outcome=='Up').sum())}  Down={int((en.outcome=='Down').sum())}")
print(f"offset_s dist:\n{en.offset_s.describe(percentiles=[.1,.5,.9])}")
print(f"take_price dist:\n{en.take_price.describe(percentiles=[.1,.5,.9])}")
print(f"own_best_ask dist:\n{en.own_best_ask.describe(percentiles=[.1,.5,.9])}")
print(f"pair_ask_sum dist (cheap-pair-arb indicator):\n{en.pair_ask_sum.describe(percentiles=[.05,.25,.5,.75,.95])}")

# A. REBALANCE
# imbalance = inv_bought - inv_other (positive means already over-weight bought side)
inv_bought = np.where(en.outcome=="Up", en.inv_up_before, en.inv_dn_before)
inv_other  = np.where(en.outcome=="Up", en.inv_dn_before, en.inv_up_before)
imbal = inv_bought - inv_other
print("\n--- A. REBALANCE TEST ---")
print(f"imbalance = inv_bought_side - inv_other_side (before fire)")
print(f"% with imbalance < 0 (justifies rebalance buy of bought side): {(imbal<0).mean()*100:.1f}%")
print(f"% with imbalance < -1 share: {(imbal<-1).mean()*100:.1f}%")
print(f"% with imbalance ≈ 0 (|<0.5|): {(np.abs(imbal)<0.5).mean()*100:.1f}%")
print(f"imbalance dist:\n{pd.Series(imbal).describe(percentiles=[.1,.25,.5,.75,.9])}")
print(f"% with inv_bought_side == 0 (fresh entry on bought side): {(inv_bought<0.001).mean()*100:.1f}%")
print(f"% with inv_other_side > 0 (already long the OTHER side): {(inv_other>0.001).mean()*100:.1f}%")

# B. DISCOUNT
print("\n--- B. DISCOUNT CAPTURE TEST ---")
print(f"ask_drop_from_60s_median dist (cents):")
print((en.ask_drop_from_60s*100).describe(percentiles=[.1,.25,.5,.75,.9,.95]))
print(f"% with ask_drop > 1c: {(en.ask_drop_from_60s>0.01).mean()*100:.1f}%")
print(f"% with ask_drop > 3c: {(en.ask_drop_from_60s>0.03).mean()*100:.1f}%")
print(f"% with ask_drop > 5c: {(en.ask_drop_from_60s>0.05).mean()*100:.1f}%")
print(f"\npair_ask_sum (sum of both sides' best asks; <$1 = pair-arb opp):")
print(en.pair_ask_sum.describe(percentiles=[.05,.25,.5,.75,.95]))
print(f"% pair_ask_sum < $1.00 (free arb): {(en.pair_ask_sum<1.00).mean()*100:.1f}%")
print(f"% pair_ask_sum < $0.98 (clear arb >2c): {(en.pair_ask_sum<0.98).mean()*100:.1f}%")
print(f"% pair_ask_sum < $0.95 (deep arb >5c): {(en.pair_ask_sum<0.95).mean()*100:.1f}%")
print(f"% pair_ask_sum >= $1.05 (no arb): {(en.pair_ask_sum>=1.05).mean()*100:.1f}%")

# C. MOMENTUM
print("\n--- C. MOMENTUM TEST ---")
if en.binance_ret_60s.notna().any():
    en2 = en.dropna(subset=["binance_ret_60s"]).copy()
    en2["binance_dir"] = np.where(en2.binance_ret_60s > 0, "Up", "Down")
    en2["match"] = (en2.binance_dir == en2.outcome).astype(int)
    print(f"n with binance: {len(en2):,}")
    print(f"binance dir matches taker outcome: {en2.match.mean()*100:.1f}%")
    print(f"by buy side: Up={en2[en2.outcome=='Up'].match.mean()*100:.1f}%  "
          f"Down={en2[en2.outcome=='Down'].match.mean()*100:.1f}%")
    print(f"|binance_ret_60s| > 0.05%:  match={en2[en2.binance_ret_60s.abs()>0.0005].match.mean()*100:.1f}% (n={(en2.binance_ret_60s.abs()>0.0005).sum()})")
    print(f"|binance_ret_60s| > 0.1%:   match={en2[en2.binance_ret_60s.abs()>0.001].match.mean()*100:.1f}% (n={(en2.binance_ret_60s.abs()>0.001).sum()})")
else:
    print("no binance data")

# ---------- Step 5b: COMPOSITE TESTS ----------
print("\n--- COMPOSITE: discount AND rebalance ---")
discount_3c = en.ask_drop_from_60s > 0.03
rebal = imbal < 0
print(f"% in discount_3c only: {discount_3c.mean()*100:.1f}%")
print(f"% in rebal only:       {rebal.mean()*100:.1f}%")
print(f"% in BOTH:             {(discount_3c & rebal).mean()*100:.1f}%")
print(f"% in EITHER:           {(discount_3c | rebal).mean()*100:.1f}%")

print("\n--- COMPOSITE: pair_ask_sum<$1.00 OR (rebalance AND own_ask<recent_med) ---")
arb_open = en.pair_ask_sum < 1.00
condA = arb_open
condB = rebal & (en.ask_drop_from_60s > 0)
print(f"% arb_open (pair_ask_sum<$1): {arb_open.mean()*100:.1f}%")
print(f"% rebal & ask_drop>0:         {condB.mean()*100:.1f}%")
print(f"% arb_open OR (rebal & drop): {(condA | condB).mean()*100:.1f}%")

# By outcome (different thresholds per side?)
print("\n--- BY OUTCOME ---")
for oc in ["Up","Down"]:
    sub = en[en.outcome==oc]
    if not len(sub): continue
    print(f"  {oc}: n={len(sub)}  med_take_price={sub.take_price.median():.3f}  "
          f"med_own_ask={sub.own_best_ask.median():.3f}  "
          f"med_pair_ask_sum={sub.pair_ask_sum.median():.3f}  "
          f"med_ask_drop60s={sub.ask_drop_from_60s.median()*100:+.2f}c")

# ---------- Save summary ----------
summary = dict(
    n_taker_in_sample=int(len(en)),
    n_taker_total_btc5m=int((~m5.wallet_is_maker).sum()),
    n_slugs_sampled=len(sampled_slugs),
    pct_rebal=float((imbal<0).mean()),
    pct_rebal_strong=float((imbal<-1).mean()),
    pct_inv_bought_zero=float((inv_bought<0.001).mean()),
    pct_other_long=float((inv_other>0.001).mean()),
    ask_drop_60s_median_cents=float(en.ask_drop_from_60s.median()*100),
    pct_ask_drop_gt_1c=float((en.ask_drop_from_60s>0.01).mean()),
    pct_ask_drop_gt_3c=float((en.ask_drop_from_60s>0.03).mean()),
    pct_ask_drop_gt_5c=float((en.ask_drop_from_60s>0.05).mean()),
    pair_ask_sum_median=float(en.pair_ask_sum.median()),
    pct_pair_arb_open=float((en.pair_ask_sum<1.00).mean()),
    pct_pair_arb_2c=float((en.pair_ask_sum<0.98).mean()),
    pct_pair_arb_5c=float((en.pair_ask_sum<0.95).mean()),
    pct_pair_no_arb=float((en.pair_ask_sum>=1.05).mean()),
)
(OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
log(f"summary -> {OUT_DIR/'summary.json'}")
log(f"DONE in {time.time()-t0:.1f}s")
