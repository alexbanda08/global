"""V5 HYPOTHESES — decode the un-explained 67% of taker fires.

Already-decoded rule (DISCOUNT-CAPTURE): own_best_ask < 0.50 AND drop_60s > 0.03
captures 33% with 1.48x lift.

Test H1-H8 on the REMAINING 67% un-explained taker fires.
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

# =====================================================================
# 1. Load enriched fire + control sets (already have book context)
# =====================================================================
log("loading enriched fire + control parquets...")
fe = pd.read_parquet(OUT_DIR / "fire_enriched_for_control.parquet")
ce = pd.read_parquet(OUT_DIR / "control_enriched.parquet")
log(f"  fire n={len(fe)} ctrl n={len(ce)}")

# Apply the already-decoded discount-capture rule
def discount_rule(df):
    return (df["own_best_ask"] < 0.50) & (df["ask_drop_from_60s"] > 0.03)

fe["disc_capture"] = discount_rule(fe)
ce["disc_capture"] = discount_rule(ce)
log(f"  fire disc-rule covers: {fe.disc_capture.sum()} ({100*fe.disc_capture.mean():.1f}%)")
log(f"  ctrl disc-rule covers: {ce.disc_capture.sum()} ({100*ce.disc_capture.mean():.1f}%)")

# UN-EXPLAINED subsets
fe_un = fe[~fe.disc_capture].copy().reset_index(drop=True)
ce_un = ce[~ce.disc_capture].copy().reset_index(drop=True)
log(f"  UN-EXPLAINED fires: n={len(fe_un)}  controls: n={len(ce_un)}")

# =====================================================================
# 2. Load trades_polymarket for H1 (signed volume) and H6 (mid momentum)
# =====================================================================
log("loading trades_polymarket/btc.parquet (signed volume context)...")
fire_slugs = set(fe_un.slug.unique()) | set(ce_un.slug.unique())
log(f"  unique slugs to filter: {len(fire_slugs)}")

# Min t window we need: 5 min before earliest fire/ctrl, 5 min after
t_min_us = (min(int(fe_un.t_sec.min()), int(ce_un.t_sec.min())) - 300) * 1_000_000
t_max_us = (max(int(fe_un.t_sec.max()), int(ce_un.t_sec.max())) + 300) * 1_000_000

tp = pd.read_parquet(
    "data/v4/canonical/trades_polymarket/btc.parquet",
    columns=["timestamp_us","slug","outcome","price","size","side"]
)
tp = tp[(tp.timestamp_us >= t_min_us) & (tp.timestamp_us <= t_max_us)]
tp = tp[tp.slug.isin(fire_slugs)].copy()
tp = tp.sort_values("timestamp_us").reset_index(drop=True)
log(f"  trades_polymarket filtered: {len(tp)} rows ({len(tp.slug.unique())} slugs)")

# Group by (slug, outcome) — index by timestamp_us
trades_idx = {}
for (sl, oc), g in tp.groupby(["slug","outcome"]):
    ts = g.timestamp_us.values.astype(np.int64)
    sz = g["size"].values.astype(np.float64)
    pr = g.price.values.astype(np.float64)
    sd = g.side.values  # 'buy' or 'sell'
    is_buy = (sd == "buy").astype(np.float64)
    is_sell = (sd == "sell").astype(np.float64)
    trades_idx[(sl, oc)] = dict(ts=ts, sz=sz, pr=pr, is_buy=is_buy, is_sell=is_sell)
log(f"  trades_idx keys: {len(trades_idx)}")

def signed_vol_window(slug, outcome, ts_us, window_s):
    """Return (buy_vol, sell_vol, n_trades) in last window_s seconds, in shares."""
    rec = trades_idx.get((slug, outcome))
    if rec is None:
        return 0.0, 0.0, 0
    ts = rec["ts"]; sz = rec["sz"]; isb = rec["is_buy"]; iss = rec["is_sell"]
    t_lo = ts_us - window_s * 1_000_000
    lo_i = np.searchsorted(ts, t_lo, side="left")
    hi_i = np.searchsorted(ts, ts_us, side="left")  # strict: before the fire
    if hi_i <= lo_i:
        return 0.0, 0.0, 0
    bv = float((sz[lo_i:hi_i] * isb[lo_i:hi_i]).sum())
    sv = float((sz[lo_i:hi_i] * iss[lo_i:hi_i]).sum())
    n  = int(hi_i - lo_i)
    return bv, sv, n

def mid_history(slug, outcome, ts_us, window_s):
    """Return prices array of trades in last window_s seconds."""
    rec = trades_idx.get((slug, outcome))
    if rec is None: return np.array([])
    ts = rec["ts"]; pr = rec["pr"]
    t_lo = ts_us - window_s * 1_000_000
    lo_i = np.searchsorted(ts, t_lo, side="left")
    hi_i = np.searchsorted(ts, ts_us, side="left")
    if hi_i <= lo_i: return np.array([])
    return pr[lo_i:hi_i]

# =====================================================================
# 3. Compute H1 (signed volume) for fires + controls
# =====================================================================
log("H1: computing signed volume features (5s, 15s, 60s)...")
def add_volume_features(df):
    rows = []
    for r in df.itertuples(index=False):
        ts_us = int(r.t_sec) * 1_000_000
        b5, s5, n5 = signed_vol_window(r.slug, r.outcome, ts_us, 5)
        b15, s15, n15 = signed_vol_window(r.slug, r.outcome, ts_us, 15)
        b60, s60, n60 = signed_vol_window(r.slug, r.outcome, ts_us, 60)
        rows.append((b5, s5, n5, b15, s15, n15, b60, s60, n60))
    arr = np.array(rows)
    df = df.copy()
    df["buy_vol_5s"] = arr[:,0]; df["sell_vol_5s"] = arr[:,1]; df["n_tr_5s"] = arr[:,2]
    df["buy_vol_15s"] = arr[:,3]; df["sell_vol_15s"] = arr[:,4]; df["n_tr_15s"] = arr[:,5]
    df["buy_vol_60s"] = arr[:,6]; df["sell_vol_60s"] = arr[:,7]; df["n_tr_60s"] = arr[:,8]
    for w in [5, 15, 60]:
        bv = df[f"buy_vol_{w}s"]; sv = df[f"sell_vol_{w}s"]
        tot = bv + sv
        df[f"flow_imb_{w}s"] = np.where(tot > 0, (bv - sv) / tot, 0.0)
        df[f"net_sell_{w}s"] = sv - bv
    return df

fe_un = add_volume_features(fe_un)
ce_un = add_volume_features(ce_un)
log(f"  done: fire mean sell_vol_60s={fe_un.sell_vol_60s.mean():.2f}, ctrl={ce_un.sell_vol_60s.mean():.2f}")

# =====================================================================
# 4. H2: BOOK IMBALANCE
# We already have own_best_ask, own_best_bid (computed at fire time).
# But we need full book L25 size data → reload.
# To save time: use a proxy = pair_ask_sum / pair_bid_sum already in the parquet
# AND fetch sum_asks / sum_bids via book_at() for the bought side.
# =====================================================================
log("H2: loading L25 books for bid/ask size imbalance...")
from load import load_orderbook_l25_streaming

# Only need slugs in fe_un ∪ ce_un to bound memory
need_slugs = set(fe_un.slug.unique()) | set(ce_un.slug.unique())
log(f"  streaming L25 for {len(need_slugs)} slugs ...")
books = load_orderbook_l25_streaming("btc", slugs=need_slugs, subsample_1hz=False)
log(f"  loaded {len(books)} (slug,outcome) series")

def book_sizes(slug, outcome, ts_us):
    """Return (sum_bid_sz, sum_ask_sz, best_bid_sz, best_ask_sz)."""
    rec = books.get((slug, outcome))
    if rec is None: return None
    ts_sorted, ap, asz, bp, bsz = rec
    idx = np.searchsorted(ts_sorted, ts_us, side="right") - 1
    if idx < 0: return None
    ap_row, asz_row = ap[idx], asz[idx]
    bp_row, bsz_row = bp[idx], bsz[idx]
    nz_a, nz_b = ap_row > 0, bp_row > 0
    if not nz_a.any() or not nz_b.any(): return None
    sum_ask = float(asz_row[nz_a].sum())
    sum_bid = float(bsz_row[nz_b].sum())
    # best_ask = lowest ask price
    best_ask_i = np.argmin(np.where(nz_a, ap_row, np.inf))
    best_bid_i = np.argmax(np.where(nz_b, bp_row, -np.inf))
    bbs = float(bsz_row[best_bid_i])
    bas = float(asz_row[best_ask_i])
    return sum_bid, sum_ask, bbs, bas

log("H2: computing book imbalance ...")
def add_book_imb(df):
    rows = []
    for r in df.itertuples(index=False):
        ts_us = int(r.t_sec) * 1_000_000
        sizes = book_sizes(r.slug, r.outcome, ts_us)
        if sizes is None:
            rows.append((np.nan,)*5)
            continue
        sb, sa, bbs, bas = sizes
        imb_total = (sb - sa) / (sb + sa) if (sb + sa) > 0 else np.nan
        best_imb  = (bbs - bas) / (bbs + bas) if (bbs + bas) > 0 else np.nan
        rows.append((sb, sa, bbs, bas, imb_total))
    arr = np.array(rows)
    df = df.copy()
    df["sum_bid_sz"] = arr[:,0]; df["sum_ask_sz"] = arr[:,1]
    df["best_bid_sz"] = arr[:,2]; df["best_ask_sz"] = arr[:,3]
    df["book_imb_total"] = arr[:,4]
    df["best_imb"] = np.where(
        (df["best_bid_sz"] + df["best_ask_sz"]) > 0,
        (df["best_bid_sz"] - df["best_ask_sz"]) / (df["best_bid_sz"] + df["best_ask_sz"]),
        np.nan
    )
    df["ask_depth_ratio"] = np.where(df["sum_ask_sz"] > 0, df["sum_bid_sz"] / df["sum_ask_sz"], np.nan)
    return df

fe_un = add_book_imb(fe_un)
ce_un = add_book_imb(ce_un)
log(f"  done: fire mean book_imb_total={fe_un.book_imb_total.mean():.3f}, ctrl={ce_un.book_imb_total.mean():.3f}")

# =====================================================================
# 5. H3: CROSS-EXCHANGE LEAD (binance kline ret in fire-side direction)
# Use klines_1m.parquet — has BINANCE_SPOT_BTC_USDT through May 16 03:47
# =====================================================================
log("H3: loading binance 1m klines ...")
kl = pd.read_parquet("data/v4/canonical/klines_1m.parquet",
                     columns=["time_period_end_us","symbol_id","price_close","price_open","price_high","price_low"])
kl = kl[kl.symbol_id == "BINANCE_SPOT_BTC_USDT"].sort_values("time_period_end_us").reset_index(drop=True)
log(f"  binance 1m: {len(kl)} rows; range={pd.to_datetime(kl.time_period_end_us.min(),unit='us')} -> {pd.to_datetime(kl.time_period_end_us.max(),unit='us')}")
kl_ts = kl.time_period_end_us.values.astype(np.int64)
kl_close = kl.price_close.values.astype(np.float64)
kl_open = kl.price_open.values.astype(np.float64)

def binance_ret_window(ts_us, lookback_s):
    """Return close-now / close-(lookback)s - 1, or nan if data unavailable."""
    # bar that ENDED at-or-before ts_us
    i_now = np.searchsorted(kl_ts, ts_us, side="right") - 1
    if i_now < 0: return np.nan
    # bar lookback_s earlier
    t_lb = ts_us - lookback_s * 1_000_000
    i_lb = np.searchsorted(kl_ts, t_lb, side="right") - 1
    if i_lb < 0 or i_now <= i_lb: return np.nan
    return float(kl_close[i_now] / kl_close[i_lb] - 1)

log("H3: computing binance returns (5s ~ N/A bc 1m granularity, 60s, 120s, 300s) ...")
def add_binance_features(df):
    rows = []
    for r in df.itertuples(index=False):
        ts_us = int(r.t_sec) * 1_000_000
        ret60  = binance_ret_window(ts_us, 60)
        ret120 = binance_ret_window(ts_us, 120)
        ret300 = binance_ret_window(ts_us, 300)
        # Direction-aligned: positive if bought Up & ret > 0, or bought Down & ret < 0
        sgn = 1.0 if r.outcome == "Up" else -1.0
        rows.append((ret60, ret120, ret300, sgn*ret60, sgn*ret120, sgn*ret300))
    arr = np.array(rows)
    df = df.copy()
    df["bin_ret_60s"] = arr[:,0]; df["bin_ret_120s"] = arr[:,1]; df["bin_ret_300s"] = arr[:,2]
    df["bin_sret_60s"] = arr[:,3]; df["bin_sret_120s"] = arr[:,4]; df["bin_sret_300s"] = arr[:,5]
    return df

fe_un = add_binance_features(fe_un)
ce_un = add_binance_features(ce_un)

# =====================================================================
# 6. H4: TIME-OF-SLUG patterns
# =====================================================================
log("H4: computing slot offsets ...")
def add_slot_offset(df):
    df = df.copy()
    df["slot_start"] = df["slug"].str.rsplit("-", n=1).str[-1].astype(np.int64)
    df["offset_s"]   = df["t_sec"].astype(np.int64) - df["slot_start"]
    return df
fe_un = add_slot_offset(fe_un)
ce_un = add_slot_offset(ce_un)

# =====================================================================
# 7. H5: ABSOLUTE PRICE LEVELS — already have own_best_ask in df
# (We'll bucket histograms in the report stage.)
# =====================================================================

# =====================================================================
# 8. H6: POLYMARKET MID-MOMENTUM (price drop over recent trades)
# Use the same trades_idx — return price array, compute drop.
# =====================================================================
log("H6: computing polymarket recent price drop (own side) ...")
def add_pm_mom(df):
    rows = []
    for r in df.itertuples(index=False):
        ts_us = int(r.t_sec) * 1_000_000
        # last 30s of trade prices on (slug, outcome)
        pr_30 = mid_history(r.slug, r.outcome, ts_us, 30)
        pr_5  = mid_history(r.slug, r.outcome, ts_us, 5)
        if len(pr_30) >= 2:
            drop_30 = float(pr_30[0] - pr_30[-1])  # earliest - latest = drop
            ret_30 = float(pr_30[-1] / pr_30[0] - 1) if pr_30[0] > 0 else np.nan
        else:
            drop_30, ret_30 = np.nan, np.nan
        if len(pr_5) >= 2:
            drop_5 = float(pr_5[0] - pr_5[-1])
        else:
            drop_5 = np.nan
        rows.append((drop_30, drop_5, ret_30, len(pr_30), len(pr_5)))
    arr = np.array(rows)
    df = df.copy()
    df["pm_drop_30s"] = arr[:,0]; df["pm_drop_5s"] = arr[:,1]
    df["pm_ret_30s"] = arr[:,2]
    df["pm_n_30s"] = arr[:,3]; df["pm_n_5s"] = arr[:,4]
    return df

fe_un = add_pm_mom(fe_un)
ce_un = add_pm_mom(ce_un)

# =====================================================================
# 9. H7: TIME SINCE LAST MAKER FILL (own wallet maker fills)
# Load full trades_chain to know all maker fills timestamps per (slug, outcome)
# =====================================================================
log("H7: loading trades_chain to get wallet maker fill timestamps ...")
tc = pd.read_parquet(CACHE / "trades_chain.parquet")
look = pd.read_parquet(ROOT / "strategy_lab" / "wallet_hunt" / "cache" / "_token_lookup.parquet")[
    ["asset_id","slug","outcome","market_class","mkt_asset"]
]
tc["asset_id"] = tc["asset"].astype(str)
look["asset_id"] = look["asset_id"].astype(str)
tcm = tc.merge(look, on="asset_id", how="left")
tcm = tcm[(tcm.mkt_asset=="BTC") & (tcm.market_class=="updown_5m")].copy()
tcm = tcm[(tcm.price > 0) & (tcm.price < 1.0001) & (tcm["size"] > 0)].copy()
maker_fills = tcm[tcm.wallet_is_maker == True][["slug","outcome","timestamp"]].copy()
maker_fills = maker_fills.sort_values(["slug","outcome","timestamp"]).reset_index(drop=True)
log(f"  maker fills in BTC 5m: {len(maker_fills)}")

# Index: (slug, outcome) -> ts array
mf_idx = {}
for (sl, oc), g in maker_fills.groupby(["slug","outcome"]):
    mf_idx[(sl, oc)] = g.timestamp.values.astype(np.int64)

def time_since_last_maker_fill(slug, outcome, t_sec):
    arr = mf_idx.get((slug, outcome))
    if arr is None: return np.nan
    i = np.searchsorted(arr, t_sec, side="right") - 1
    if i < 0: return np.nan
    return float(t_sec - arr[i])

def add_h7(df):
    df = df.copy()
    df["sec_since_last_maker"] = [
        time_since_last_maker_fill(s, o, t) for s, o, t in zip(df.slug, df.outcome, df.t_sec)
    ]
    return df
fe_un = add_h7(fe_un)
ce_un = add_h7(ce_un)
log(f"  done: fire median sec_since_last_maker={fe_un.sec_since_last_maker.median():.1f}, ctrl={ce_un.sec_since_last_maker.median():.1f}")

# Save enriched
fe_un.to_parquet(OUT_DIR / "fire_v5_hypotheses.parquet")
ce_un.to_parquet(OUT_DIR / "control_v5_hypotheses.parquet")

# =====================================================================
# 10. STATISTICAL ANALYSIS
# =====================================================================
print("\n" + "=" * 78)
print("V5 HYPOTHESIS TEST: un-explained taker fires vs matched controls")
print(f"  fire (un-explained) n = {len(fe_un)}")
print(f"  ctrl (un-explained) n = {len(ce_un)}")
print("=" * 78)

def wilson_z(p1, n1, p2, n2):
    # Two-prop z stat
    if min(n1, n2) == 0: return 0.0
    p = (p1*n1 + p2*n2) / (n1 + n2)
    if p == 0 or p == 1: return 0.0
    se = (p * (1-p) * (1/n1 + 1/n2)) ** 0.5
    return (p1 - p2) / se if se > 0 else 0.0

def threshold_test(name, fmask, cmask):
    fv = fmask.dropna()
    cv = cmask.dropna()
    f_n = len(fv); c_n = len(cv)
    f_rate = float(fv.mean()); c_rate = float(cv.mean())
    lift = f_rate / c_rate if c_rate > 0 else float('inf')
    z = wilson_z(f_rate, f_n, c_rate, c_n)
    return name, f_rate, c_rate, lift, z, f_n, c_n

print("\n--- DISTRIBUTION SUMMARY ---\n")
features = [
    ("flow_imb_5s",   "sell-side flow imbalance 5s  (neg=sell pressure)"),
    ("flow_imb_15s",  "sell-side flow imbalance 15s"),
    ("flow_imb_60s",  "sell-side flow imbalance 60s"),
    ("sell_vol_5s",   "sell volume 5s (shares)"),
    ("sell_vol_15s",  "sell volume 15s"),
    ("sell_vol_60s",  "sell volume 60s"),
    ("net_sell_60s",  "net sell minus buy 60s"),
    ("n_tr_60s",      "# trades 60s"),
    ("book_imb_total","total bid - ask size / total"),
    ("best_imb",      "best bid - best ask size / sum"),
    ("ask_depth_ratio","sum_bid_sz / sum_ask_sz"),
    ("sum_ask_sz",    "total ask depth (shares)"),
    ("best_ask_sz",   "size at best ask"),
    ("bin_sret_60s",  "binance signed ret 60s"),
    ("bin_sret_120s", "binance signed ret 120s"),
    ("bin_sret_300s", "binance signed ret 300s"),
    ("offset_s",      "seconds after slot_start"),
    ("own_best_ask",  "own best ask at fire (price)"),
    ("pm_drop_30s",   "polymarket trade-price drop last 30s"),
    ("pm_ret_30s",    "polymarket trade-price ret last 30s"),
    ("sec_since_last_maker", "seconds since last own-wallet maker fill"),
]
hdr = f"{'feature':<22} {'fire med':>10} {'ctrl med':>10} {'fire mean':>10} {'ctrl mean':>10} {'fire p75':>10} {'ctrl p75':>10}"
print(hdr); print("-"*len(hdr))
for f, lbl in features:
    if f not in fe_un.columns: continue
    fv = fe_un[f].dropna(); cv = ce_un[f].dropna()
    if len(fv)==0 or len(cv)==0:
        print(f"{f:<22}  (no data)"); continue
    print(f"{f:<22} {fv.median():>10.4f} {cv.median():>10.4f} {fv.mean():>10.4f} {cv.mean():>10.4f} {fv.quantile(.75):>10.4f} {cv.quantile(.75):>10.4f}")

# =====================================================================
# 11. THRESHOLD LIFT TESTS PER HYPOTHESIS
# =====================================================================
print("\n\n--- HYPOTHESIS THRESHOLD TESTS (FIRE vs CTRL, lift = f_rate/c_rate) ---\n")
tests = [
    # H1: signed volume
    ("H1: sell_vol_60s > 5",          fe_un.sell_vol_60s > 5,  ce_un.sell_vol_60s > 5),
    ("H1: sell_vol_60s > 20",         fe_un.sell_vol_60s > 20, ce_un.sell_vol_60s > 20),
    ("H1: sell_vol_60s > 50",         fe_un.sell_vol_60s > 50, ce_un.sell_vol_60s > 50),
    ("H1: sell_vol_15s > 5",          fe_un.sell_vol_15s > 5,  ce_un.sell_vol_15s > 5),
    ("H1: sell_vol_15s > 20",         fe_un.sell_vol_15s > 20, ce_un.sell_vol_15s > 20),
    ("H1: sell_vol_5s > 5",           fe_un.sell_vol_5s  > 5,  ce_un.sell_vol_5s  > 5),
    ("H1: net_sell_60s > 0",          fe_un.net_sell_60s > 0,  ce_un.net_sell_60s > 0),
    ("H1: net_sell_60s > 10",         fe_un.net_sell_60s > 10, ce_un.net_sell_60s > 10),
    ("H1: net_sell_60s > 30",         fe_un.net_sell_60s > 30, ce_un.net_sell_60s > 30),
    ("H1: flow_imb_60s < -0.2",       fe_un.flow_imb_60s < -0.2, ce_un.flow_imb_60s < -0.2),
    ("H1: flow_imb_60s < -0.5",       fe_un.flow_imb_60s < -0.5, ce_un.flow_imb_60s < -0.5),
    ("H1: flow_imb_15s < -0.5",       fe_un.flow_imb_15s < -0.5, ce_un.flow_imb_15s < -0.5),
    # H2: book imbalance
    ("H2: book_imb_total > 0.0",      fe_un.book_imb_total > 0,  ce_un.book_imb_total > 0),
    ("H2: book_imb_total > 0.1",      fe_un.book_imb_total > 0.1, ce_un.book_imb_total > 0.1),
    ("H2: book_imb_total > 0.3",      fe_un.book_imb_total > 0.3, ce_un.book_imb_total > 0.3),
    ("H2: best_imb > 0.2",            fe_un.best_imb > 0.2,       ce_un.best_imb > 0.2),
    ("H2: best_imb > 0.5",            fe_un.best_imb > 0.5,       ce_un.best_imb > 0.5),
    ("H2: ask_depth_ratio > 1.5",     fe_un.ask_depth_ratio > 1.5,ce_un.ask_depth_ratio > 1.5),
    ("H2: ask_depth_ratio > 2.0",     fe_un.ask_depth_ratio > 2.0,ce_un.ask_depth_ratio > 2.0),
    # H3: binance
    ("H3: bin_sret_60s > 0",          fe_un.bin_sret_60s > 0,    ce_un.bin_sret_60s > 0),
    ("H3: bin_sret_60s > 0.0005",     fe_un.bin_sret_60s > 0.0005, ce_un.bin_sret_60s > 0.0005),
    ("H3: bin_sret_120s > 0",         fe_un.bin_sret_120s > 0,   ce_un.bin_sret_120s > 0),
    ("H3: bin_sret_120s > 0.001",     fe_un.bin_sret_120s > 0.001, ce_un.bin_sret_120s > 0.001),
    ("H3: bin_sret_300s > 0",         fe_un.bin_sret_300s > 0,   ce_un.bin_sret_300s > 0),
    # H4: time-of-slug
    ("H4: offset_s in [0,60]",        (fe_un.offset_s>=0)&(fe_un.offset_s<=60),   (ce_un.offset_s>=0)&(ce_un.offset_s<=60)),
    ("H4: offset_s in [60,180]",      (fe_un.offset_s>=60)&(fe_un.offset_s<=180), (ce_un.offset_s>=60)&(ce_un.offset_s<=180)),
    ("H4: offset_s in [180,280]",     (fe_un.offset_s>=180)&(fe_un.offset_s<=280),(ce_un.offset_s>=180)&(ce_un.offset_s<=280)),
    ("H4: offset_s in [240,300]",     (fe_un.offset_s>=240)&(fe_un.offset_s<=300),(ce_un.offset_s>=240)&(ce_un.offset_s<=300)),
    ("H4: offset_s > 280",            fe_un.offset_s > 280,        ce_un.offset_s > 280),
    # H5: absolute price
    ("H5: own_best_ask < 0.50",       fe_un.own_best_ask < 0.50, ce_un.own_best_ask < 0.50),
    ("H5: own_best_ask < 0.40",       fe_un.own_best_ask < 0.40, ce_un.own_best_ask < 0.40),
    ("H5: own_best_ask < 0.30",       fe_un.own_best_ask < 0.30, ce_un.own_best_ask < 0.30),
    ("H5: own_best_ask < 0.20",       fe_un.own_best_ask < 0.20, ce_un.own_best_ask < 0.20),
    ("H5: own_best_ask < 0.10",       fe_un.own_best_ask < 0.10, ce_un.own_best_ask < 0.10),
    ("H5: 0.10<=ask<0.30",            (fe_un.own_best_ask>=0.10)&(fe_un.own_best_ask<0.30),
                                       (ce_un.own_best_ask>=0.10)&(ce_un.own_best_ask<0.30)),
    # H6: polymarket mid drop
    ("H6: pm_drop_30s > 0.02",        fe_un.pm_drop_30s > 0.02,  ce_un.pm_drop_30s > 0.02),
    ("H6: pm_drop_30s > 0.05",        fe_un.pm_drop_30s > 0.05,  ce_un.pm_drop_30s > 0.05),
    ("H6: pm_drop_5s > 0.02",         fe_un.pm_drop_5s > 0.02,   ce_un.pm_drop_5s > 0.02),
    ("H6: pm_ret_30s < -0.05",        fe_un.pm_ret_30s < -0.05,  ce_un.pm_ret_30s < -0.05),
    ("H6: pm_ret_30s < -0.10",        fe_un.pm_ret_30s < -0.10,  ce_un.pm_ret_30s < -0.10),
    # H7: time since last maker
    ("H7: sec_since_last_maker > 10", fe_un.sec_since_last_maker > 10, ce_un.sec_since_last_maker > 10),
    ("H7: sec_since_last_maker > 30", fe_un.sec_since_last_maker > 30, ce_un.sec_since_last_maker > 30),
    ("H7: sec_since_last_maker > 60", fe_un.sec_since_last_maker > 60, ce_un.sec_since_last_maker > 60),
    ("H7: sec_since_last_maker > 120",fe_un.sec_since_last_maker > 120, ce_un.sec_since_last_maker > 120),
    ("H7: sec_since_last_maker is NaN (never maker'd on this side)",
                                       fe_un.sec_since_last_maker.isna(), ce_un.sec_since_last_maker.isna()),
]

hdr = f"{'test':<55} {'fire%':>8} {'ctrl%':>8} {'lift':>7} {'z':>7} {'verdict':>10}"
print(hdr); print("-"*len(hdr))
results = []
for name, fm, cm in tests:
    r = threshold_test(name, fm, cm)
    nm, fr, cr, lift, z, fn, cn = r
    verdict = "CONFIRM" if (lift >= 1.5 and abs(z) > 2.6) else ("WEAK" if (lift >= 1.2 and abs(z) > 2.0) else "REJECT")
    print(f"{nm:<55} {fr*100:>7.1f}% {cr*100:>7.1f}% {lift:>6.2f}x {z:>+6.2f} {verdict:>10}")
    results.append(dict(name=nm, fire_rate=fr, ctrl_rate=cr, lift=lift, z=z, verdict=verdict, fire_n=fn, ctrl_n=cn))

# =====================================================================
# 12. COMPOSITE RULE — try combining strongest signals
# =====================================================================
print("\n\n--- COMPOSITE RULE TESTING ---\n")

# Always apply discount-capture base first
# Then OR with new rules — measure on FULL fe and FULL ce
# Composite candidate: OR (disc-capture, rule_b, rule_c)
# Pick rules from highest-lift CONFIRMED above

# Helper: full lift on the entire fire/ctrl pool
def composite_lift(name, rule_fn, fdf, cdf):
    fm = rule_fn(fdf).fillna(False)
    cm = rule_fn(cdf).fillna(False)
    f_rate = fm.mean(); c_rate = cm.mean()
    lift = f_rate / c_rate if c_rate > 0 else float('inf')
    z = wilson_z(f_rate, len(fm), c_rate, len(cm))
    return name, f_rate, c_rate, lift, z

# Rebuild features on FULL fe + ce so the composite uses everything
log("\nrebuilding features on FULL fire+ctrl sets for composite ...")
def enrich_full(df):
    df = df.copy()
    # H1, H6, H7 need re-compute; H2, H3 need re-compute
    rows_vol = []
    rows_book = []
    rows_pm = []
    rows_mfill = []
    rows_bin = []
    for r in df.itertuples(index=False):
        ts_us = int(r.t_sec) * 1_000_000
        b5, s5, n5 = signed_vol_window(r.slug, r.outcome, ts_us, 5)
        b15, s15, n15 = signed_vol_window(r.slug, r.outcome, ts_us, 15)
        b60, s60, n60 = signed_vol_window(r.slug, r.outcome, ts_us, 60)
        rows_vol.append((b5,s5,b15,s15,b60,s60))
        sizes = book_sizes(r.slug, r.outcome, ts_us)
        if sizes:
            sb, sa, bbs, bas = sizes
            rows_book.append((sb,sa,bbs,bas))
        else:
            rows_book.append((np.nan,)*4)
        pr_30 = mid_history(r.slug, r.outcome, ts_us, 30)
        pr_5  = mid_history(r.slug, r.outcome, ts_us, 5)
        drop_30 = float(pr_30[0]-pr_30[-1]) if len(pr_30)>=2 else np.nan
        drop_5  = float(pr_5[0]-pr_5[-1]) if len(pr_5)>=2 else np.nan
        rows_pm.append((drop_30, drop_5))
        sec = time_since_last_maker_fill(r.slug, r.outcome, int(r.t_sec))
        rows_mfill.append((sec,))
        r60 = binance_ret_window(ts_us, 60)
        sgn = 1.0 if r.outcome=="Up" else -1.0
        rows_bin.append((r60, sgn*r60))
    A = np.array(rows_vol); B = np.array(rows_book); C = np.array(rows_pm); D = np.array(rows_mfill); E = np.array(rows_bin)
    df["sell_vol_5s"] = A[:,1]; df["sell_vol_15s"] = A[:,3]; df["sell_vol_60s"] = A[:,5]
    df["buy_vol_60s"] = A[:,4]
    df["net_sell_60s"] = A[:,5] - A[:,4]
    tot_60 = A[:,4] + A[:,5]
    df["flow_imb_60s"] = np.where(tot_60>0, (A[:,4]-A[:,5])/tot_60, 0.0)
    df["sum_bid_sz"]=B[:,0]; df["sum_ask_sz"]=B[:,1]; df["best_bid_sz"]=B[:,2]; df["best_ask_sz"]=B[:,3]
    df["book_imb_total"] = np.where((B[:,0]+B[:,1])>0, (B[:,0]-B[:,1])/(B[:,0]+B[:,1]), np.nan)
    df["best_imb"] = np.where((B[:,2]+B[:,3])>0, (B[:,2]-B[:,3])/(B[:,2]+B[:,3]), np.nan)
    df["ask_depth_ratio"] = np.where(B[:,1]>0, B[:,0]/B[:,1], np.nan)
    df["pm_drop_30s"]=C[:,0]
    df["pm_drop_5s"]=C[:,1]
    df["sec_since_last_maker"]=D[:,0]
    df["bin_ret_60s"]=E[:,0]; df["bin_sret_60s"]=E[:,1]
    return df

fe_full = enrich_full(fe)
ce_full = enrich_full(ce)
log(f"  fe_full n={len(fe_full)}  ce_full n={len(ce_full)}")

# Rules
def rule_disc(df):
    return (df.own_best_ask < 0.50) & (df.ask_drop_from_60s > 0.03)

# Get the top-lift new rules from the un-explained analysis
# (Will be filled in after we see results above — but let's parametrize for several candidates)
def rule_b1(df):  # sell pressure
    return (df.sell_vol_60s > 20) & (df.own_best_ask < 0.60)
def rule_b2(df):  # sell pressure stricter
    return (df.sell_vol_60s > 50)
def rule_b3(df):  # book imbalance
    return (df.book_imb_total > 0.3) & (df.own_best_ask < 0.50)
def rule_b4(df):  # cheap absolute price
    return (df.own_best_ask < 0.30)
def rule_b5(df):  # pm drop
    return (df.pm_drop_30s > 0.05)
def rule_b6(df):  # binance signed ret
    return (df.bin_sret_60s > 0.0005)
def rule_b7(df):  # very late offset (>280 after slot start)
    so = df["slug"].str.rsplit('-',n=1).str[-1].astype(np.int64)
    return (df["t_sec"].astype(np.int64) - so > 280)
def rule_b8(df):  # sec_since_last_maker NaN (no maker fill yet)
    return df["sec_since_last_maker"].isna()
def rule_b9(df):  # H4: early offset 0..60
    so = df["slug"].str.rsplit('-',n=1).str[-1].astype(np.int64)
    return ((df["t_sec"].astype(np.int64) - so) <= 60) & ((df["t_sec"].astype(np.int64) - so) >= 0)
def rule_b10(df):  # H6: pm_drop_5s — need to compute on full set
    return df["pm_drop_5s"] > 0.02 if "pm_drop_5s" in df.columns else pd.Series(False, index=df.index)
def rule_b11(df):  # combo: early OR no-prior-maker (both new CONFIRM)
    return rule_b9(df) | rule_b8(df)

candidate_rules = [
    ("disc_capture (baseline)", rule_disc),
    ("R_B1: sell_vol_60s>20 AND ask<0.60", rule_b1),
    ("R_B2: sell_vol_60s>50", rule_b2),
    ("R_B3: book_imb_total>0.3 AND ask<0.50", rule_b3),
    ("R_B4: own_best_ask<0.30", rule_b4),
    ("R_B5: pm_drop_30s>0.05", rule_b5),
    ("R_B6: bin_sret_60s>0.0005", rule_b6),
    ("R_B7: offset_s > 280", rule_b7),
    ("R_B8: sec_since_last_maker IS NaN", rule_b8),
    ("R_B9: offset_s in [0,60] (early)", rule_b9),
    ("R_B11: R_B9 OR R_B8 (early or first-take)", rule_b11),
]

print(f"{'rule':<55} {'fire%':>8} {'ctrl%':>8} {'lift':>7} {'z':>8}")
print("-"*88)
for name, fn in candidate_rules:
    nm, fr, cr, lift, z = composite_lift(name, fn, fe_full, ce_full)
    print(f"{nm:<55} {fr*100:>7.1f}% {cr*100:>7.1f}% {lift:>6.2f}x {z:>+7.2f}")

# Composite: disc OR (top new rule)
print("\n--- COMPOSITE (OR-combined) — applied to FULL fire+ctrl pool ---\n")
def rule_b10v(df):  # pm_drop_5s (the H6 confirmed signal)
    return (df["pm_drop_5s"] > 0.02)
composites = [
    ("disc OR R_B9 (early)", lambda d: rule_disc(d) | rule_b9(d)),
    ("disc OR R_B8 (first-take)", lambda d: rule_disc(d) | rule_b8(d)),
    ("disc OR R_B10 (pm_drop_5s>0.02)", lambda d: rule_disc(d) | rule_b10v(d)),
    ("disc OR R_B7 (late offset>280)", lambda d: rule_disc(d) | rule_b7(d)),
    ("disc OR R_B11 (early OR first-take)", lambda d: rule_disc(d) | rule_b11(d)),
    ("disc OR R_B10 OR R_B9", lambda d: rule_disc(d) | rule_b10v(d) | rule_b9(d)),
    ("disc OR R_B10 OR R_B9 OR R_B8", lambda d: rule_disc(d) | rule_b10v(d) | rule_b9(d) | rule_b8(d)),
    ("disc OR R_B10 OR R_B9 OR R_B8 OR R_B7", lambda d: rule_disc(d) | rule_b10v(d) | rule_b9(d) | rule_b8(d) | rule_b7(d)),
]
print(f"{'composite':<50} {'fire%':>8} {'ctrl%':>8} {'lift':>7} {'z':>8}")
print("-"*83)
composite_results = []
for name, fn in composites:
    nm, fr, cr, lift, z = composite_lift(name, fn, fe_full, ce_full)
    print(f"{nm:<50} {fr*100:>7.1f}% {cr*100:>7.1f}% {lift:>6.2f}x {z:>+7.2f}")
    composite_results.append(dict(name=nm, fire_rate=fr, ctrl_rate=cr, lift=lift, z=z))

# Incremental coverage on un-explained subset (fe_un)
print("\n--- INCREMENTAL COVERAGE ON UN-EXPLAINED 67% (n=807 fires) ---\n")
unexp_rules = [
    ("R_B9 (offset 0-60)", rule_b9),
    ("R_B8 (sec_since_last_maker NaN)", rule_b8),
    ("R_B7 (offset > 280)", rule_b7),
    ("R_B10 (pm_drop_5s>0.02)", rule_b10v),
    ("R_B9 OR R_B8", lambda d: rule_b9(d) | rule_b8(d)),
    ("R_B9 OR R_B10", lambda d: rule_b9(d) | rule_b10v(d)),
    ("R_B9 OR R_B8 OR R_B10", lambda d: rule_b9(d) | rule_b8(d) | rule_b10v(d)),
    ("R_B9 OR R_B8 OR R_B10 OR R_B7", lambda d: rule_b9(d) | rule_b8(d) | rule_b10v(d) | rule_b7(d)),
]
# Note: fe_un was built BEFORE add_book_imb / pm_drop_5s; need to re-add pm_drop_5s
# It's actually there (pm_drop_5s). Let me check by re-running add_pm_mom — yes already there.
print(f"{'rule on un-explained':<45} {'fire%':>8} {'ctrl%':>8} {'lift':>7}")
print("-"*72)
incremental = []
for name, fn in unexp_rules:
    fm = fn(fe_un).fillna(False); cm = fn(ce_un).fillna(False)
    fr = fm.mean(); cr = cm.mean(); lift = fr/cr if cr>0 else float('inf')
    print(f"{name:<45} {fr*100:>7.1f}% {cr*100:>7.1f}% {lift:>6.2f}x")
    incremental.append(dict(name=name, fire_rate=float(fr), ctrl_rate=float(cr), lift=float(lift)))

# Save summary
summary = dict(
    fire_n_full=int(len(fe)), ctrl_n_full=int(len(ce)),
    fire_n_unexplained=int(len(fe_un)), ctrl_n_unexplained=int(len(ce_un)),
    hypothesis_tests=results,
    composite_results=composite_results,
    incremental_unexplained=incremental,
)
with open(OUT_DIR / "summary_v5.json", "w") as f:
    json.dump(summary, f, indent=2, default=float)
log(f"\nsaved {OUT_DIR / 'summary_v5.json'}")
log(f"DONE in {time.time()-t0:.1f}s")
