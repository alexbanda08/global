"""V4 CONTROL — compare fire moments vs random non-fire moments.

For each sampled slug, take K random non-fire timestamps in the same window.
Compute the same features. If the trigger is real, fire-distributions should DIFFER from control.
"""
from __future__ import annotations
import os, sys, time, json
import numpy as np
import pandas as pd
from pathlib import Path

t0 = time.time()
def log(msg): print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
os.chdir(ROOT); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

CACHE  = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xeebde7a0"
OUT_DIR = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "0xeebde7a0_taker_decode"

# load data
log("loading ...")
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

# Inventory state per slug (same as v2)
def cumstate(df):
    df = df.sort_values(["t_sec","log_index"]).reset_index(drop=True).copy()
    sgn = np.where(df["side"].values == "BUY", 1.0, -1.0)
    is_up = (df["outcome"].values == "Up").astype(np.float64)
    is_dn = (df["outcome"].values == "Down").astype(np.float64)
    dshares = sgn * df["shares"].values
    dnotional = sgn * df["usdc_notional"].values
    cs_up = np.cumsum(dshares * is_up); cs_dn = np.cumsum(dshares * is_dn)
    cd_up = np.cumsum(dnotional * is_up); cd_dn = np.cumsum(dnotional * is_dn)
    df["inv_up_before"]  = np.concatenate([[0.0], cs_up[:-1]])
    df["inv_dn_before"]  = np.concatenate([[0.0], cs_dn[:-1]])
    df["cash_up_before"] = np.concatenate([[0.0], cd_up[:-1]])
    df["cash_dn_before"] = np.concatenate([[0.0], cd_dn[:-1]])
    df["inv_up_after"]   = cs_up
    df["inv_dn_after"]   = cs_dn
    df["cash_up_after"]  = cd_up
    df["cash_dn_after"]  = cd_dn
    return df

# Top-density slugs
taker_per_slug = m5[~m5.wallet_is_maker].groupby("slug").size().sort_values(ascending=False)
sampled_slugs = list(taker_per_slug.head(600).index)
m5s = m5[m5["slug"].isin(sampled_slugs)].copy()
m5s = m5s.groupby("slug", group_keys=False, sort=False).apply(cumstate, include_groups=True).reset_index(drop=True)
log(f"  rows={len(m5s)}  slugs={len(sampled_slugs)}")

# Load books
from load import load_orderbook_l25_streaming
log("streaming L25 ...")
books = load_orderbook_l25_streaming("btc", slugs=set(sampled_slugs), subsample_1hz=False)
log(f"  loaded {len(books)} series")

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
    t_lo = ts_us - 60_000_000
    lo_i = np.searchsorted(ts_sorted, t_lo, side="left")
    hi_i = idx + 1
    if hi_i - lo_i > 1:
        ap_win = ap[lo_i:hi_i]
        ap_masked = np.where(ap_win > 0, ap_win, np.inf)
        per_snap = ap_masked.min(axis=1)
        per_snap = per_snap[per_snap < np.inf]
        med = float(np.median(per_snap)) if len(per_snap) >= 3 else best_ask
    else:
        med = best_ask
    return dict(best_ask=best_ask, best_bid=best_bid, recent_med_ask_60s=med)

# Helper: inventory state at arbitrary timestamp in slug (linear scan)
def inv_state_at(slug_trades, ts_sec):
    """Return inv_up, inv_dn, cash_up, cash_dn as of this timestamp."""
    sub = slug_trades[slug_trades.t_sec <= ts_sec]
    if len(sub) == 0:
        return 0.0, 0.0, 0.0, 0.0
    last = sub.iloc[-1]
    return float(last.inv_up_after), float(last.inv_dn_after), float(last.cash_up_after), float(last.cash_dn_after)

# ---------- Build fire sample (TAKER fires) ----------
log("preparing fire + control samples ...")
tk = m5s[~m5s.wallet_is_maker].copy()
NS = 1500
if len(tk) > NS:
    tk = tk.sample(NS, random_state=42).sort_values("t_sec").reset_index(drop=True)
log(f"  fire sample N={len(tk)}")

# ---------- Control sample: same slugs, random offsets in [30, 280] ----------
np.random.seed(123)
# For each fire, pick a random non-fire timestamp within the same slug
ctrl_rows = []
trades_by_slug = {s: g.sort_values("t_sec") for s, g in m5s.groupby("slug")}
fires_by_slug = {s: set(g.t_sec.values) for s, g in tk.groupby("slug")}

for r in tk.itertuples(index=False):
    # Random offset 30..280
    for _ in range(3):  # try up to 3 times to avoid clashes
        rand_off = int(np.random.randint(30, 281))
        rand_t   = int(r.slot_start) + rand_off
        if rand_t in fires_by_slug.get(r.slug, set()): continue
        # Compute inventory state at this control timestamp
        if r.slug not in trades_by_slug: continue
        iu, id_, cu, cd = inv_state_at(trades_by_slug[r.slug], rand_t)
        # Sample a random outcome to "test" (50/50)
        outcome = "Up" if np.random.rand() < 0.5 else "Down"
        ctrl_rows.append(dict(
            slug=r.slug, outcome=outcome, t_sec=rand_t, slot_start=r.slot_start,
            inv_up_before=iu, inv_dn_before=id_, cash_up_before=cu, cash_dn_before=cd,
        ))
        break

ctrl_df = pd.DataFrame(ctrl_rows)
log(f"  control sample N={len(ctrl_df)}")

# Enrich both with book context
def enrich(df, is_fire=False):
    rows = []
    for r in df.itertuples(index=False):
        ts_us = int(r.t_sec) * 1_000_000
        own = book_at(r.slug, r.outcome, ts_us)
        other_oc = "Down" if r.outcome=="Up" else "Up"
        oth = book_at(r.slug, other_oc, ts_us)
        if own is None or oth is None: continue
        inv_own = r.inv_up_before if r.outcome=="Up" else r.inv_dn_before
        inv_oth = r.inv_dn_before if r.outcome=="Up" else r.inv_up_before
        cash_own= r.cash_up_before if r.outcome=="Up" else r.cash_dn_before
        cash_oth= r.cash_dn_before if r.outcome=="Up" else r.cash_up_before
        cb_other = (cash_oth / inv_oth) if inv_oth > 0.001 else np.nan
        rec = dict(
            slug=r.slug, outcome=r.outcome, t_sec=r.t_sec,
            own_best_ask=own["best_ask"], own_best_bid=own["best_bid"],
            recent_med_ask_60s=own["recent_med_ask_60s"],
            pair_ask_sum=own["best_ask"]+oth["best_ask"],
            pair_bid_sum=own["best_bid"]+oth["best_bid"],
            ask_drop_from_60s=own["recent_med_ask_60s"] - own["best_ask"],
            inv_own_before=float(inv_own), inv_other_before=float(inv_oth),
            cb_other=cb_other,
            pair_eff_at_ask=own["best_ask"] + (cb_other if not np.isnan(cb_other) else np.nan),
        )
        if is_fire:
            rec["take_price"] = r.price
            rec["take_size"] = r.shares
        rows.append(rec)
    return pd.DataFrame(rows)

log("enriching FIRE ...")
fire_en = enrich(tk, is_fire=True)
log(f"  n={len(fire_en)}")
log("enriching CONTROL ...")
ctrl_en = enrich(ctrl_df, is_fire=False)
log(f"  n={len(ctrl_en)}")

# Save
fire_en.to_parquet(OUT_DIR / "fire_enriched_for_control.parquet")
ctrl_en.to_parquet(OUT_DIR / "control_enriched.parquet")

# ---------- Statistical comparison ----------
print("\n" + "=" * 70)
print("CONTROL TEST: fire moments vs random non-fire moments in same slugs")
print("=" * 70)

features = [
    ("own_best_ask", "best ask of bought side"),
    ("ask_drop_from_60s", "ask drop vs 60s med"),
    ("pair_ask_sum", "pair ask sum"),
    ("inv_own_before", "inv on bought side"),
    ("inv_other_before", "inv on other side"),
    ("cb_other", "cost basis other side"),
    ("pair_eff_at_ask", "ask + cb_other"),
]
for f, lbl in features:
    fv = fire_en[f].dropna()
    cv = ctrl_en[f].dropna()
    if len(fv)==0 or len(cv)==0: continue
    print(f"\n  {f} ({lbl}):")
    print(f"    fire    n={len(fv):4d}  mean={fv.mean():8.3f}  median={fv.median():8.3f}  p25={fv.quantile(.25):8.3f}  p75={fv.quantile(.75):8.3f}")
    print(f"    control n={len(cv):4d}  mean={cv.mean():8.3f}  median={cv.median():8.3f}  p25={cv.quantile(.25):8.3f}  p75={cv.quantile(.75):8.3f}")

# Specific trigger threshold tests
print("\n\n--- TRIGGER THRESHOLD RATES (fire vs control) ---")
for name, fmask, cmask in [
    ("ask_drop_60s > 3c",  fire_en.ask_drop_from_60s>0.03, ctrl_en.ask_drop_from_60s>0.03),
    ("ask_drop_60s > 5c",  fire_en.ask_drop_from_60s>0.05, ctrl_en.ask_drop_from_60s>0.05),
    ("own_best_ask < 0.50", fire_en.own_best_ask<0.50, ctrl_en.own_best_ask<0.50),
    ("own_best_ask < 0.40", fire_en.own_best_ask<0.40, ctrl_en.own_best_ask<0.40),
    ("own_best_ask < 0.30", fire_en.own_best_ask<0.30, ctrl_en.own_best_ask<0.30),
    ("pair_eff_at_ask < $1", fire_en.pair_eff_at_ask<1.0, ctrl_en.pair_eff_at_ask<1.0),
    ("pair_eff_at_ask < $0.95", fire_en.pair_eff_at_ask<0.95, ctrl_en.pair_eff_at_ask<0.95),
    ("pair_eff_at_ask < $0.90", fire_en.pair_eff_at_ask<0.90, ctrl_en.pair_eff_at_ask<0.90),
    ("inv_other_before > 0.5", fire_en.inv_other_before>0.5, ctrl_en.inv_other_before>0.5),
    ("inv_own_before < 0 (short)", fire_en.inv_own_before<-0.5, ctrl_en.inv_own_before<-0.5),
]:
    f_rate = fmask.mean()*100
    c_rate = cmask.mean()*100
    lift = f_rate / max(c_rate, 0.01)
    print(f"  {name:30s}  fire={f_rate:5.1f}%  ctrl={c_rate:5.1f}%  lift={lift:5.2f}x")

# Best 2-feature trigger
print("\n--- BEST 2-FEATURE TRIGGERS (high fire-rate, low control-rate) ---")
candidates = [
    ("own_best_ask<0.40 AND inv_other>0.5",
        (fire_en.own_best_ask<0.40)&(fire_en.inv_other_before>0.5),
        (ctrl_en.own_best_ask<0.40)&(ctrl_en.inv_other_before>0.5)),
    ("own_best_ask<0.50 AND ask_drop>3c",
        (fire_en.own_best_ask<0.50)&(fire_en.ask_drop_from_60s>0.03),
        (ctrl_en.own_best_ask<0.50)&(ctrl_en.ask_drop_from_60s>0.03)),
    ("pair_eff<0.95 AND inv_other>0.5",
        (fire_en.pair_eff_at_ask<0.95)&(fire_en.inv_other_before>0.5),
        (ctrl_en.pair_eff_at_ask<0.95)&(ctrl_en.inv_other_before>0.5)),
    ("ask_drop>3c AND inv_other>inv_own",
        (fire_en.ask_drop_from_60s>0.03)&(fire_en.inv_other_before>fire_en.inv_own_before),
        (ctrl_en.ask_drop_from_60s>0.03)&(ctrl_en.inv_other_before>ctrl_en.inv_own_before)),
    ("ask_drop>5c AND own_best_ask<0.50",
        (fire_en.ask_drop_from_60s>0.05)&(fire_en.own_best_ask<0.50),
        (ctrl_en.ask_drop_from_60s>0.05)&(ctrl_en.own_best_ask<0.50)),
]
for name, fm, cm in candidates:
    f_rate = fm.mean()*100; c_rate = cm.mean()*100
    lift = f_rate/max(c_rate, 0.01)
    print(f"  {name:50s}  fire={f_rate:5.1f}%  ctrl={c_rate:5.1f}%  lift={lift:5.2f}x")

log("DONE")
