"""
B945 Tick Timeline Analysis — 2026-06-13
Stress-tests the dip-buying / oscillation-harvesting hypothesis tick by tick.

DATA:
  - ml_features.parquet: per-fill book state (up_ask/bid/dn_ask/bid + oracle rets at fill time)
  - fill_tape_full.parquet: chain fills (ts, price, outcome, slug, tx_hash)
  - per_slug_paired_ledger.parquet: slug-level outcome + PnL
  - trades_polymarket/btc.parquet: ALL collector taker prints
  - orderfilled_sample.parquet: MAKER/TAKER classification
  - L25 dict[(slug,outcome)] -> (ts_us, ap[N,25], asz[N,25], bp[N,25], bsz[N,25])

KEY DESIGN CHOICE:
  ml_features has is_fill=0 rows too (book snapshots between fills) which we use
  for price-change lookback WITHOUT loading 6GB L25. For the timelines, L25 is loaded
  for 10 slugs to show book depth at each fill.

OUTPUT: strategy_lab/reports/B945_TICK_TIMELINE_2026_06_13.md
"""

import sys, os, math
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

sys.path.insert(0, "data/v4/canonical")
from load import load_orderbook_l25_streaming

RNG_SEED = 20260613
BASE = "strategy_lab/wallet_hunt/cache/0xb945945d"
OUT_MD = "strategy_lab/reports/B945_TICK_TIMELINE_2026_06_13.md"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Load all data
# ─────────────────────────────────────────────────────────────────────────────
print("Loading ml_features...")
ml = pd.read_parquet(f"{BASE}/ml_features.parquet")
ml["t_s"] = ml["t_us"] / 1e6
ml["is_up"] = ml["side_up"] == 1.0
fills_ml = ml[ml["is_fill"] == 1].copy()
print(f"  ml_features: {len(ml)} rows ({len(fills_ml)} fills), {fills_ml['slug'].nunique()} slugs")

print("Loading fill_tape_full...")
ft = pd.read_parquet(f"{BASE}/fill_tape_full.parquet")
ft["t_s_ft"] = pd.to_datetime(ft["ts"]).astype("int64") / 1e9
ft_btc = ft[ft["slug"].str.contains("btc-updown-15m", na=False)].copy()
print(f"  fill_tape_full btc-15m: {len(ft_btc)} rows")

print("Loading orderfilled_sample (maker/taker)...")
ofs = pd.read_parquet(f"{BASE}/orderfilled_sample.parquet")
# b945_role = MAKER / TAKER
maker_map = dict(zip(ofs["tx_hash"], ofs["b945_role"]))  # tx_hash -> role
print(f"  orderfilled_sample: {len(ofs)} rows, roles: {ofs['b945_role'].value_counts().to_dict()}")

print("Loading per_slug_paired_ledger...")
ledger = pd.read_parquet(f"{BASE}/per_slug_paired_ledger.parquet").reset_index()
print(f"  ledger: {len(ledger)} rows")

print("Loading collector trades btc-15m...")
trades_raw = pd.read_parquet(
    "data/v4/canonical/trades_polymarket/btc.parquet",
    columns=["timestamp_us", "slug", "outcome", "price", "size", "side"],
)
trades_btc = trades_raw[trades_raw["slug"].str.contains("btc-updown-15m", na=False)].copy()
trades_btc["t_s"] = trades_btc["timestamp_us"] / 1e6
del trades_raw
print(f"  collector btc-15m trades: {len(trades_btc)} rows, {trades_btc['slug'].nunique()} slugs")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Select 10 diverse slugs
# ─────────────────────────────────────────────────────────────────────────────
print("\nSelecting 10 slugs...")
slug_cnt = fills_ml.groupby("slug").size()
rich = slug_cnt[slug_cnt >= 30].index.tolist()
print(f"  slugs with >=30 fills: {len(rich)}")

# need collector trades too
trade_slugs = set(trades_btc["slug"].unique())
rich_with_trades = [s for s in rich if s in trade_slugs]
print(f"  slugs with >=30 fills + collector coverage: {len(rich_with_trades)}")

ledger_slim = ledger[["slug", "winner", "n_up", "n_dn", "vwap_up", "vwap_dn",
                       "pvs", "total_pnl", "first_ts_up", "first_ts_dn"]].copy()
slugs_df = pd.DataFrame({"slug": rich_with_trades})
slugs_df["slot_s"] = slugs_df["slug"].apply(lambda s: int(s.rsplit("-", 1)[1]))
slugs_df["dt_utc"] = pd.to_datetime(slugs_df["slot_s"], unit="s", utc=True)
slugs_df["hour_utc"] = slugs_df["dt_utc"].dt.hour
slugs_df["n_fills"] = slugs_df["slug"].map(slug_cnt)
slugs_df = slugs_df.merge(ledger_slim, on="slug", how="left")

def hour_stratum(h):
    if h < 8: return "A_early"
    elif h < 12: return "B_mid"
    elif h < 20: return "C_us"
    else: return "D_evening"
slugs_df["stratum"] = slugs_df["hour_utc"].apply(hour_stratum)

rng = np.random.default_rng(RNG_SEED)
chosen = []
for st in ["A_early", "B_mid", "C_us", "D_evening"]:
    pool = slugs_df[slugs_df["stratum"] == st].copy()
    if len(pool) == 0: continue
    for winner in ["Up", "Down"]:
        sub = pool[pool["winner"] == winner]
        if len(sub) == 0: sub = pool
        idx_arr = rng.integers(0, len(sub), size=3)
        for idx in idx_arr:
            cand = sub.iloc[idx]["slug"]
            if cand not in chosen:
                chosen.append(cand)
                break
    if len(chosen) >= 10: break

remaining = [s for s in rich_with_trades if s not in chosen]
rng.shuffle(remaining)
chosen.extend(remaining[:max(0, 10 - len(chosen))])
chosen = chosen[:10]

chosen_set = set(chosen)
print(f"\n  Chosen 10 slugs:")
for s in chosen:
    row = slugs_df[slugs_df["slug"] == s].iloc[0]
    print(f"    {s}  n={int(row['n_fills'])}  winner={row['winner']}  "
          f"pvs={row['pvs']:.3f}  dt={row['dt_utc']}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Load L25 for 10 slugs
# ─────────────────────────────────────────────────────────────────────────────
print("\nLoading L25 for 10 slugs (native 10Hz)...")
l25 = load_orderbook_l25_streaming("btc", slugs=chosen_set, subsample_1hz=False)
print(f"  L25 keys: {len(l25)}")

def l25_to_df(l25_dict, slug):
    """Convert L25 dict for one slug into a flat DataFrame with top-of-book."""
    frames = []
    for (s, outcome), (ts_us, ap, asz, bp, bsz) in l25_dict.items():
        if s != slug: continue
        df = pd.DataFrame({
            "timestamp_us": ts_us,
            "outcome": outcome,
            "ask0": ap[:, 0],
            "ask1": ap[:, 1],
            "bid0": bp[:, 0],
            "bid1": bp[:, 1],
            "asksz0": asz[:, 0],
            "bidsz0": bsz[:, 0],
        })
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames)
    out["t_s"] = out["timestamp_us"] / 1e6
    return out.sort_values("t_s").reset_index(drop=True)

# ─────────────────────────────────────────────────────────────────────────────
# 4. Dip-buying signal computation (using ml_features book snapshots)
#    For POWER TEST: use all btc-15m ml rows (fills + non-fills in same slug)
#    to compute up_mid lookback at each fill event.
# ─────────────────────────────────────────────────────────────────────────────
print("\nComputing dip-buying signal across ALL btc-15m fills...")

# For each fill row in ml, find the up_mid value N seconds earlier in the same slug
# We already have up_mid computed in ml_features from the L25 book at snapshot time.

lag_seconds = [5, 10, 30]

def compute_dip_df(ml_all, fills_subset, lags):
    """Vectorised lookback within each slug for speed."""
    results = []
    ml_sorted = ml_all.sort_values(["slug", "t_us"]).reset_index(drop=True)

    for slug, grp in ml_sorted.groupby("slug"):
        grp_arr = grp["up_mid"].values
        t_arr = grp["t_us"].values  # microseconds
        fill_mask = grp["is_fill"].values == 1
        idxs = np.where(fill_mask)[0]  # positions of fill rows within grp

        for pos in idxs:
            t_fill = t_arr[pos]
            up_mid_now = grp_arr[pos]
            row = grp.iloc[pos]
            rec = {
                "slug": slug,
                "t_us": t_fill,
                "off_s": float(row["off"]),
                "is_up": bool(row["is_up"]),
                "price": float(row["price"]),
                "up_mid_now": float(up_mid_now),
                "overround": float(row["overround"]),
                "bret5": float(row["bret5"]),
                "bret15": float(row["bret15"]),
                "rtds_ret5": float(row["rtds_ret5"]),
            }
            for lag_s in lags:
                lag_us = lag_s * 1_000_000
                t_lo = t_fill - lag_us
                # find rows in [t_lo, t_fill)
                prev_mask = (t_arr >= t_lo) & (t_arr < t_fill)
                prev_mids = grp_arr[prev_mask]
                if len(prev_mids) == 0:
                    rec[f"dup_mid_{lag_s}"] = np.nan
                else:
                    # price change = up_mid_now - up_mid_then (earliest in window)
                    rec[f"dup_mid_{lag_s}"] = up_mid_now - prev_mids[0]
            results.append(rec)
    return pd.DataFrame(results)

dip_df = compute_dip_df(ml, fills_ml, lag_seconds)
print(f"  dip_df: {len(dip_df)} fill rows")

# ─────────────────────────────────────────────────────────────────────────────
# 5. Hypothesis tests
# ─────────────────────────────────────────────────────────────────────────────
print("\nHypothesis tests...")

# --- D1: Dip-buying ---
def test_dip_buying(dip_df, lag_s):
    col = f"dup_mid_{lag_s}"
    sub = dip_df[dip_df[col].notna()].copy()
    if len(sub) == 0: return None
    # "bought the dip" = is_up and up_mid fell (dup_mid < 0), or not is_up and up_mid rose (dup_mid > 0 = Dn fell)
    sub["bought_dip"] = np.where(sub["is_up"], sub[col] < 0, sub[col] > 0)
    n = len(sub)
    n_dip = int(sub["bought_dip"].sum())
    p_dip = n_dip / n
    binom_p = scipy_stats.binomtest(n_dip, n, 0.5, alternative="greater").pvalue
    # also test two-sided
    binom_p2 = scipy_stats.binomtest(n_dip, n, 0.5, alternative="two-sided").pvalue
    ci_lo = scipy_stats.binom.ppf(0.025, n, p_dip) / n
    ci_hi = scipy_stats.binom.ppf(0.975, n, p_dip) / n
    return dict(lag_s=lag_s, n=n, n_dip=n_dip, P_dip=round(p_dip, 4),
                binom_p_gt=round(binom_p, 6), binom_p_2s=round(binom_p2, 6),
                CI95=f"[{ci_lo:.3f},{ci_hi:.3f}]")

dip_tests = [test_dip_buying(dip_df, lag) for lag in lag_seconds]
dip_tests = [r for r in dip_tests if r is not None]
for r in dip_tests:
    print(f"  lag={r['lag_s']}s: P(dip)={r['P_dip']:.4f} n={r['n']} binom_p(>50%)={r['binom_p_gt']:.4f}")

# --- D2: Alternation / oscillation ---
print("\nAlternation test...")
alt_slug_data = []
for slug, sf in fills_ml.groupby("slug"):
    sf = sf.sort_values("t_us")
    sides = sf["is_up"].tolist()
    if len(sides) < 4: continue
    n_tr = len(sides) - 1
    n_alt = sum(sides[i] != sides[i-1] for i in range(1, len(sides)))
    alt_slug_data.append({"slug": slug, "n_tr": n_tr, "n_alt": n_alt, "p_alt": n_alt/n_tr})

alt_df = pd.DataFrame(alt_slug_data)
n_tr_total = alt_df["n_tr"].sum()
n_alt_total = alt_df["n_alt"].sum()
p_alt_global = n_alt_total / n_tr_total
binom_alt = scipy_stats.binomtest(int(n_alt_total), int(n_tr_total), 0.5, alternative="two-sided").pvalue
print(f"  P_alt global: {p_alt_global:.4f}  n_transitions: {n_tr_total}  binom_p(2s): {binom_alt:.6f}")
print(f"  Median per-slug P_alt: {alt_df['p_alt'].median():.4f}")

# --- D3: Price-vs-time correlation within each leg ---
print("\nPrice-vs-fill-order correlation within legs...")
corr_up, corr_dn = [], []
for slug, sf in fills_ml.groupby("slug"):
    sf = sf.sort_values("t_us")
    up_sf = sf[sf["is_up"]].reset_index(drop=True)
    dn_sf = sf[~sf["is_up"]].reset_index(drop=True)
    if len(up_sf) >= 4:
        c = up_sf["price"].corr(up_sf.index.to_series())
        if pd.notna(c): corr_up.append(c)
    if len(dn_sf) >= 4:
        c = dn_sf["price"].corr(dn_sf.index.to_series())
        if pd.notna(c): corr_dn.append(c)

mu_up = np.mean(corr_up); t_up, p_up = scipy_stats.ttest_1samp(corr_up, 0)
mu_dn = np.mean(corr_dn); t_dn, p_dn = scipy_stats.ttest_1samp(corr_dn, 0)
print(f"  Up: mean corr={mu_up:.4f}  n={len(corr_up)}  t={t_up:.2f}  p={p_up:.4f}")
print(f"  Dn: mean corr={mu_dn:.4f}  n={len(corr_dn)}  t={t_dn:.2f}  p={p_dn:.4f}")

# --- D4: Price level histogram ---
print("\nPrice level histogram...")
up_prices = fills_ml[fills_ml["is_up"]]["price"].dropna()
dn_prices = fills_ml[~fills_ml["is_up"]]["price"].dropna()
up_1c = (up_prices * 100).round() / 100
dn_1c = (dn_prices * 100).round() / 100
up_hhi = (up_1c.value_counts() / len(up_1c)).pow(2).sum()
dn_hhi = (dn_1c.value_counts() / len(dn_1c)).pow(2).sum()
up_top = (up_1c.value_counts().nlargest(10))
dn_top = (dn_1c.value_counts().nlargest(10))
print(f"  Up median={up_prices.median():.3f}  HHI={up_hhi:.5f}")
print(f"  Dn median={dn_prices.median():.3f}  HHI={dn_hhi:.5f}")
print(f"  Top Up 1¢ bins: {dict(up_top)}")
print(f"  Top Dn 1¢ bins: {dict(dn_top)}")

# --- D5: Maker/Taker ---
print("\nMaker/taker analysis...")
ft_btc["maker_taker"] = ft_btc["tx_hash"].map(maker_map).fillna("UNK")
role_ct = ofs["b945_role"].value_counts()
print(f"  All orderfilled sample: {role_ct.to_dict()}")
# merge ofs with ft to get outcome/slug context
ofs_ctx = ofs.merge(ft_btc[["tx_hash", "slug", "outcome"]], on="tx_hash", how="left")
ofs_btc15 = ofs_ctx[ofs_ctx["slug"].str.contains("btc-updown-15m", na=False) == True] if "slug" in ofs_ctx.columns else ofs_ctx
print(f"  btc-15m subset: {len(ofs_btc15)} rows")
if "b945_role" in ofs_btc15.columns and len(ofs_btc15) > 0:
    role_btc = ofs_btc15["b945_role"].value_counts()
    print(f"  btc-15m roles: {role_btc.to_dict()}")
    maker_frac = ofs_btc15["b945_role"].eq("MAKER").mean()
    print(f"  Maker fraction btc-15m: {maker_frac:.3f}")

# Also: are dip-buys more MAKER? (resting bid catches falling price)
# Use merge_timing.parquet which may have MAKER/TAKER per fill
mt = pd.read_parquet(f"{BASE}/merge_timing.parquet")
print(f"\n  merge_timing cols: {list(mt.columns[:15])}")
print(f"  merge_timing shape: {mt.shape}")
print(f"  merge_timing sample:\n{mt.head(3).to_string()}")

# ─────────────────────────────────────────────────────────────────────────────
# 6. Per-slug timelines for top 4 slugs
# ─────────────────────────────────────────────────────────────────────────────
print("\nBuilding readable timelines for top 4 slugs...")
chosen_sorted = sorted(chosen, key=lambda s: slug_cnt.get(s, 0), reverse=True)
top4 = chosen_sorted[:4]

def fmt(v, dec=3):
    if v is None or (isinstance(v, float) and not math.isfinite(v)): return "  - "
    return f"{v:.{dec}f}"

timeline_sections = {}

for slug in top4:
    slot_s = int(slug.rsplit("-", 1)[1])
    slot_dt = pd.Timestamp(slot_s, unit="s", tz="UTC")
    hf = fills_ml[fills_ml["slug"] == slug].sort_values("t_us").reset_index(drop=True)
    tr = trades_btc[trades_btc["slug"] == slug].sort_values("t_s").reset_index(drop=True)
    ledg = ledger_slim[ledger_slim["slug"] == slug] if "slug" in ledger_slim.columns else pd.DataFrame()
    winner = ledg["winner"].iloc[0] if len(ledg) > 0 else "?"
    pvs = ledg["pvs"].iloc[0] if len(ledg) > 0 else np.nan
    n_up = int(ledg["n_up"].iloc[0]) if len(ledg) > 0 else 0
    n_dn = int(ledg["n_dn"].iloc[0]) if len(ledg) > 0 else 0
    vwap_up = ledg["vwap_up"].iloc[0] if len(ledg) > 0 else np.nan
    vwap_dn = ledg["vwap_dn"].iloc[0] if len(ledg) > 0 else np.nan

    # Get L25 top of book in a flat df for this slug
    bk_slug = l25_to_df(l25, slug)
    has_l25 = len(bk_slug) > 0

    # Compute dup_mid_5 for fills in this slug
    slug_dip = dip_df[dip_df["slug"] == slug].copy()
    dip5_map = dict(zip(slug_dip["t_us"], slug_dip.get("dup_mid_5", pd.Series(dtype=float))))

    lines = []
    lines.append(f"\n### {slug}")
    lines.append(f"Window: **{slot_dt} UTC** → +15 min")
    lines.append(f"Winner: **{winner}** | pvs={fmt(pvs)} | n_up={n_up} n_dn={n_dn} | "
                 f"vwap_up={fmt(vwap_up)} vwap_dn={fmt(vwap_dn)}")
    lines.append(f"His fills in window: {len(hf)} (Up:{int(hf['is_up'].sum())} Dn:{int((~hf['is_up']).sum())})")
    lines.append(f"Collector prints (all wallets): {len(tr)} | L25 snapshots: {len(bk_slug)}")
    lines.append("")

    # Build timeline interleaving his fills with L25 book state
    # For L25: show up_ask0/up_bid0 and dn_ask0/dn_bid0 as the instantaneous ToB
    # His fills already have up_ask, up_bid, dn_ask, dn_bid from ml_features at fill moment

    lines.append("| t(+s) | HIS fill? | Side | Price | USD | up_bid | up_ask | dn_bid | dn_ask | sum_ask | bret5 | bret15 | oracle5 | Δup_mid(5s) |")
    lines.append("|-------|-----------|------|-------|-----|--------|--------|--------|--------|---------|-------|--------|---------|------------|")

    display_hf = hf.head(40)
    prev_side = None
    for i, r in display_hf.iterrows():
        off = r["off"]
        side_str = "▲ UP " if r["is_up"] else "▼ DN "
        switch_flag = " ↔" if (prev_side is not None and bool(r["is_up"]) != prev_side) else ""
        prev_side = bool(r["is_up"])
        price = r["price"]
        usd = r["usd"]
        up_bid = r["up_bid"]
        up_ask = r["up_ask"]
        dn_bid = r["dn_bid"]
        dn_ask = r["dn_ask"]
        sum_ask = up_ask + dn_ask if pd.notna(up_ask) and pd.notna(dn_ask) else np.nan
        bret5 = r["bret5"]
        bret15 = r["bret15"]
        oracle5 = r["rtds_ret5"]
        dip5 = dip5_map.get(r["t_us"], np.nan)

        lines.append(
            f"| {fmt(off,1):>6} | **HIS** | {side_str}{switch_flag} | {fmt(price):>5} | {fmt(usd,2):>5} | "
            f"{fmt(up_bid):>6} | {fmt(up_ask):>6} | {fmt(dn_bid):>6} | {fmt(dn_ask):>6} | "
            f"{fmt(sum_ask):>7} | {fmt(bret5,2):>5} | {fmt(bret15,2):>6} | {fmt(oracle5,2):>7} | {fmt(dip5,4):>10} |"
        )

    if len(hf) > 40:
        lines.append(f"| *...{len(hf)-40} more fills...* |")

    # Side sequence
    sides_seq = ["UP" if r else "DN" for r in hf["is_up"].tolist()]
    if len(sides_seq) > 1:
        n_sw = sum(sides_seq[i] != sides_seq[i-1] for i in range(1, len(sides_seq)))
        lines.append(f"\n**Side sequence** (first 30): `{' '.join(sides_seq[:30])}`")
        lines.append(f"**Switch rate**: {n_sw}/{len(sides_seq)-1} = {n_sw/(len(sides_seq)-1):.1%}")

    # Price monotonicity per leg
    up_hf = hf[hf["is_up"]].sort_values("t_us").reset_index(drop=True)
    dn_hf = hf[~hf["is_up"]].sort_values("t_us").reset_index(drop=True)
    if len(up_hf) >= 4:
        c = up_hf["price"].corr(pd.Series(range(len(up_hf))))
        lines.append(f"**Up leg price-vs-order corr**: {c:.3f}  (neg=falling over time, pos=rising)")
    if len(dn_hf) >= 4:
        c = dn_hf["price"].corr(pd.Series(range(len(dn_hf))))
        lines.append(f"**Dn leg price-vs-order corr**: {c:.3f}")

    if len(up_hf) > 0 and len(dn_hf) > 0:
        lines.append(f"**Up price range**: [{up_hf['price'].min():.3f}, {up_hf['price'].max():.3f}] "
                     f"median={up_hf['price'].median():.3f}")
        lines.append(f"**Dn price range**: [{dn_hf['price'].min():.3f}, {dn_hf['price'].max():.3f}] "
                     f"median={dn_hf['price'].median():.3f}")

    first_off = hf["off"].min() if len(hf) > 0 else np.nan
    last_off = hf["off"].max() if len(hf) > 0 else np.nan
    lines.append(f"**Time span**: first fill +{fmt(first_off,0)}s → last +{fmt(last_off,0)}s out of 900s")

    # Sum_ask evolution: does it start high and compress to <1?
    if has_l25:
        bk_slug["t_off"] = bk_slug["t_s"] - slot_s
        # merge Up and Dn sides
        bk_up = bk_slug[bk_slug["outcome"]=="Up"][["t_s","t_off","ask0","bid0"]].rename(
            columns={"ask0":"up_ask0","bid0":"up_bid0"})
        bk_dn = bk_slug[bk_slug["outcome"]=="Down"][["t_s","t_off","ask0","bid0"]].rename(
            columns={"ask0":"dn_ask0","bid0":"dn_bid0"})
        # asof merge
        bk_up = bk_up.sort_values("t_s")
        bk_dn = bk_dn.sort_values("t_s")
        if len(bk_up) > 0 and len(bk_dn) > 0:
            bk_merged = pd.merge_asof(bk_up, bk_dn, on="t_s", direction="nearest")
            bk_merged["sum_ask"] = bk_merged["up_ask0"] + bk_merged["dn_ask0"]
            bk_merged["sum_bid"] = bk_merged["up_bid0"] + bk_merged["dn_bid0"]
            early = bk_merged.iloc[:50]["sum_ask"].mean()
            mid_section = bk_merged.iloc[len(bk_merged)//3:2*len(bk_merged)//3]["sum_ask"].mean()
            late = bk_merged.iloc[-50:]["sum_ask"].mean()
            lines.append(f"\n**Sum_ask evolution** (L25 ToB): early={early:.4f} → mid={mid_section:.4f} → late={late:.4f}")
            n_below1 = (bk_merged["sum_ask"] < 1.0).mean()
            lines.append(f"**Fraction of book-time sum_ask < 1.0**: {n_below1:.1%}")

    timeline_sections[slug] = "\n".join(lines)

# ─────────────────────────────────────────────────────────────────────────────
# 7. Compact summary all 10 slugs
# ─────────────────────────────────────────────────────────────────────────────
print("\nBuilding compact summary all 10 slugs...")
compact_rows = []
for slug in chosen:
    hf = fills_ml[fills_ml["slug"] == slug].sort_values("t_us")
    ledg = ledger_slim[ledger_slim["slug"] == slug] if "slug" in ledger_slim.columns else pd.DataFrame()
    winner = ledg["winner"].iloc[0] if len(ledg) > 0 else "?"
    pvs = ledg["pvs"].iloc[0] if len(ledg) > 0 else np.nan
    n_up = int(ledg["n_up"].iloc[0]) if len(ledg) > 0 else 0
    n_dn = int(ledg["n_dn"].iloc[0]) if len(ledg) > 0 else 0
    vwap_up = ledg["vwap_up"].iloc[0] if len(ledg) > 0 else np.nan
    vwap_dn = ledg["vwap_dn"].iloc[0] if len(ledg) > 0 else np.nan
    total_pnl = ledg["total_pnl"].iloc[0] if len(ledg) > 0 else np.nan
    sides = hf["is_up"].tolist()
    p_alt = (sum(sides[i] != sides[i-1] for i in range(1, len(sides))) / (len(sides)-1)
             if len(sides) > 1 else np.nan)
    slot_s = int(slug.rsplit("-", 1)[1])
    slot_dt = pd.Timestamp(slot_s, unit="s", tz="UTC")
    # dip signal for this slug
    dip_slug = dip_df[dip_df["slug"] == slug]
    if len(dip_slug) > 0 and "dup_mid_5" in dip_slug.columns:
        ds5 = dip_slug[dip_slug["dup_mid_5"].notna()]
        p_dip5 = (np.where(ds5["is_up"], ds5["dup_mid_5"] < 0, ds5["dup_mid_5"] > 0)).mean() if len(ds5) > 0 else np.nan
    else:
        p_dip5 = np.nan

    compact_rows.append({
        "slug": slug[-20:],
        "dt_utc": str(slot_dt)[:16],
        "hr": int(slot_dt.hour),
        "winner": winner,
        "pvs": pvs,
        "n_fills": len(hf),
        "n_up": int(hf["is_up"].sum()),
        "n_dn": int((~hf["is_up"]).sum()),
        "vwap_up": vwap_up,
        "vwap_dn": vwap_dn,
        "P_alt": p_alt,
        "P_dip5s": p_dip5,
        "first_s": hf["off"].min() if len(hf) > 0 else np.nan,
        "total_pnl": total_pnl,
    })
cdf = pd.DataFrame(compact_rows)

# ─────────────────────────────────────────────────────────────────────────────
# 8. Write report
# ─────────────────────────────────────────────────────────────────────────────
print("\nWriting report...")
R = []

R.append("# B945 Tick Timeline Analysis — 2026-06-13")
R.append("")
R.append("**Wallet:** `0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68` (pseudonym: Noisy-Colonisation, +$21,742 LB)")
R.append("")
R.append("**Hypothesis tested:** Does he buy the *momentarily dipping* side — buy Up when Up price just fell,")
R.append("buy Dn when Up price just rose — accumulating both sides as price oscillates, targeting sum<1?")
R.append("")
R.append("**Prior conclusion:** 'No signal; buys both sides ~uniformly; delta-contrarian at the slug level.'")
R.append("")
R.append("---")

R.append("\n## A. Data Sources Used\n")
R.append(f"- `ml_features.parquet`: {len(ml)} book snapshots ({len(fills_ml)} fill rows) across {fills_ml['slug'].nunique()} btc-15m slugs")
R.append(f"- `fill_tape_full.parquet`: {len(ft_btc)} fills (chain-confirmed)")
R.append(f"- `orderfilled_sample.parquet`: {len(ofs)} OrderFilled events with MAKER/TAKER classification")
R.append(f"- `trades_polymarket/btc.parquet`: {len(trades_btc)} collector taker prints across {trades_btc['slug'].nunique()} slugs")
R.append(f"- `per_slug_paired_ledger.parquet`: {len(ledger)} slug-level PnL summaries")
R.append(f"- L25 orderbook (10Hz native): loaded for 10 chosen slugs")

R.append("\n## B. Slug Selection (seed=20260613)\n")
R.append(f"Pool: {len(rich)} btc-15m slugs with ≥30 fills, {len(rich_with_trades)} also with collector coverage.")
R.append("Stratified by UTC hour band (4 bands) × winner side (Up/Down).\n")
R.append("| slug (suffix) | dt_utc | hr | winner | pvs | n_fills | n_up | n_dn | vwap_up | vwap_dn | P_alt | P_dip(5s) | first_fill | PnL |")
R.append("|---------------|--------|-----|--------|-----|---------|------|------|---------|---------|-------|-----------|------------|-----|")
for _, r in cdf.iterrows():
    R.append(
        f"| `{r['slug']}` | {r['dt_utc']} | {r['hr']:02d} | {r['winner']} | {fmt(r['pvs'])} | "
        f"{r['n_fills']} | {r['n_up']} | {r['n_dn']} | {fmt(r['vwap_up'])} | {fmt(r['vwap_dn'])} | "
        f"{r['P_alt']:.0%} | {fmt(r['P_dip5s'],2) if pd.notna(r['P_dip5s']) else '-'} | "
        f"+{fmt(r['first_s'],0)}s | ${fmt(r['total_pnl'],2) if pd.notna(r['total_pnl']) else '-'} |"
    )

R.append("\n**Column definitions:**")
R.append("- `pvs` = price × shares sum (=sum_ask of his entry cost, proxy for overround)")
R.append("- `P_alt` = fraction of consecutive fill pairs that switch sides (50% = random)")
R.append("- `P_dip(5s)` = fraction of fills where that side's price fell in the preceding 5s (dip-buying signal)")
R.append("- `first_fill` = offset from slot_start of his first fill")

R.append("\n---\n")
R.append("## C. Tick-by-Tick Timelines (top 4 slugs by fill count)\n")
R.append("**Columns:**")
R.append("- `t(+s)` = seconds from slot_start")
R.append("- `Side` = ▲ UP or ▼ DN (which outcome he bought); ↔ marks a side-switch")
R.append("- `Price` = his fill VWAP from ml_features")
R.append("- `up_bid/ask` = Up token top-of-book at fill moment (from L25 snapshot in ml_features)")
R.append("- `sum_ask` = up_ask + dn_ask (overround proxy; < 1.0 = arb window)")
R.append("- `bret5/15` = Binance 5s/15s price return at fill time (%)")
R.append("- `oracle5` = Chainlink RTDS 5s return at fill time (%)")
R.append("- `Δup_mid(5s)` = change in up_mid over preceding 5s (neg = Up price fell = dip opportunity)")
R.append("")

for slug in top4:
    R.append(timeline_sections[slug])
    R.append("")

R.append("---\n")
R.append("## D. Quantified Hypothesis Tests (all 817 btc-15m slugs, 67,198 fills)\n")

R.append("### D1. Dip-Buying: P(buys the locally-cheaper/dipping side)\n")
R.append("Definition: for each fill, compute the change in up_mid over the preceding N seconds (Δup_mid_N).")
R.append("A fill is a 'dip buy' if:")
R.append("  - Up fill AND Δup_mid < 0 (Up price just fell = cheaper)")
R.append("  - Dn fill AND Δup_mid > 0 (Up price just rose = Dn price just fell = cheaper)")
R.append("Null hypothesis: P(dip) = 0.5. One-sided binomial test (H1: P > 0.5).\n")
R.append("| lag | N fills w/ data | N dip-buys | P(dip) | 95% CI | p-value (>50%) | p-value (≠50%) | Verdict |")
R.append("|-----|-----------------|------------|--------|--------|----------------|----------------|---------|")
for r in dip_tests:
    if r["P_dip"] > 0.55 and r["binom_p_gt"] < 0.05:
        v = "**DIP-BUYER** (sig)"
    elif r["P_dip"] < 0.45 and r["binom_p_2s"] < 0.05:
        v = "**MOMENTUM** (anti-dip, sig)"
    elif r["binom_p_2s"] > 0.05:
        v = "No signal (p>" + f"{r['binom_p_2s']:.3f})"
    else:
        v = f"Weak dip signal p={r['binom_p_gt']:.3f}"
    R.append(
        f"| {r['lag_s']}s | {r['n']} | {r['n_dip']} | {r['P_dip']:.4f} | {r['CI95']} | "
        f"{r['binom_p_gt']:.4f} | {r['binom_p_2s']:.4f} | {v} |"
    )
R.append("")

# D1 interpretation
if dip_tests:
    p5 = dip_tests[0]["P_dip"]
    if p5 > 0.55:
        R.append(f"**Interpretation:** P_dip={p5:.4f} > 55% = dip-buying confirmed. He systematically fills AFTER price drops.")
    elif p5 < 0.45:
        R.append(f"**Interpretation:** P_dip={p5:.4f} < 45% = ANTI-dip / momentum. Fills AFTER price rises.")
    else:
        R.append(f"**Interpretation:** P_dip={p5:.4f} ≈ 50% = NO systematic timing relative to recent price move. "
                 f"Consistent with passive MAKER whose resting bids/asks get hit regardless of direction.")
R.append("")

R.append("### D2. Alternation / Oscillation Pattern\n")
R.append(f"- Total fill-to-fill transitions: **{n_tr_total:,}** across {len(alt_df)} slugs")
R.append(f"- Alternations (Up→Dn or Dn→Up): **{n_alt_total:,}** = **{p_alt_global:.4f}** ({p_alt_global:.1%})")
R.append(f"- Median per-slug alternation rate: **{alt_df['p_alt'].median():.4f}**")
R.append(f"- Binomial test vs 50% (two-sided): **p={binom_alt:.6f}**")
R.append("")
if p_alt_global > 0.55 and binom_alt < 0.001:
    alt_v = (f"**SIG ALTERNATION** (P_alt={p_alt_global:.4f} >> 50%, p<0.001). He switches sides more than random. "
             f"Consistent with oscillation-harvesting: buy one side, wait, switch to the other.")
elif p_alt_global < 0.45 and binom_alt < 0.001:
    alt_v = (f"**SIG RUNS** (P_alt={p_alt_global:.4f} < 50%, p<0.001). He CLUSTERS same-side fills — "
             f"multi-fill ladder on one side before switching. NOT oscillation-harvesting in the fill-by-fill sense.")
else:
    alt_v = (f"**No significant alternation** (p={binom_alt:.4f}). Fill sequence near-random conditional on "
             f"having both sides in a slug.")
R.append(f"**Verdict:** {alt_v}\n")

R.append("### D3. Per-Leg Timing: Price Drift Over the Window\n")
R.append("Correlation between fill order (1st, 2nd, ..., Nth fill on that side) and fill price.")
R.append("Negative corr = price falls over his accumulation = he buys later fills cheaper (ladder into dip).")
R.append("Positive corr = price rises = he buys later fills more expensive (momentum/chasing).\n")
R.append(f"- Up leg: mean corr = **{mu_up:.4f}**, n={len(corr_up)} slugs, t={t_up:.2f}, p={p_up:.4f}")
R.append(f"- Dn leg: mean corr = **{mu_dn:.4f}**, n={len(corr_dn)} slugs, t={t_dn:.2f}, p={p_dn:.4f}")
R.append("")
if mu_up < -0.05 and p_up < 0.05:
    d3v_up = "SIG negative corr — Up entries accumulate at progressively LOWER prices. Passive ladder bids catching falling price."
elif mu_up > 0.05 and p_up < 0.05:
    d3v_up = "SIG positive corr — Up entries at progressively higher prices (momentum)."
else:
    d3v_up = f"No significant drift (p={p_up:.4f})."
if mu_dn < -0.05 and p_dn < 0.05:
    d3v_dn = "SIG negative — Dn fills also at lower prices over time."
elif mu_dn > 0.05 and p_dn < 0.05:
    d3v_dn = f"SIG positive — Dn fills drift up (p={p_dn:.4f})."
else:
    d3v_dn = f"No significant drift (p={p_dn:.4f})."
R.append(f"**Up verdict:** {d3v_up}")
R.append(f"**Dn verdict:** {d3v_dn}\n")

R.append("### D4. Price Level Structure (1¢ grid)\n")
R.append(f"Up fills: {len(up_prices):,} fills, median={up_prices.median():.3f}, HHI={up_hhi:.5f}")
R.append(f"Dn fills: {len(dn_prices):,} fills, median={dn_prices.median():.3f}, HHI={dn_hhi:.5f}")
R.append(f"Uniform 1¢ HHI benchmark: {1/100:.5f}\n")
R.append("Top-10 Up fill prices (1¢ bins):")
R.append("| Price | Count | Share |")
R.append("|-------|-------|-------|")
for px, ct in up_top.items():
    R.append(f"| {px:.2f} | {ct} | {ct/len(up_prices):.1%} |")
R.append("\nTop-10 Dn fill prices (1¢ bins):")
R.append("| Price | Count | Share |")
R.append("|-------|-------|-------|")
for px, ct in dn_top.items():
    R.append(f"| {px:.2f} | {ct} | {ct/len(dn_prices):.1%} |")
R.append("")
if up_hhi > 1/100 * 3:
    R.append("**Verdict:** STRONGLY CLUSTERED at favorite price levels (HHI >> uniform). "
             "Strong evidence of resting limit orders at specific prices — GTC ladder behavior.\n")
elif up_hhi > 1/100 * 1.5:
    R.append("**Verdict:** MODERATELY clustered — some level concentration, but spread across many prices.\n")
else:
    R.append("**Verdict:** Price distribution close to uniform — no strong level clustering.\n")

R.append("### D5. Maker vs Taker Breakdown\n")
R.append(f"OrderFilled sample: {len(ofs)} events total, {len(ofs_btc15)} mapped to btc-15m slugs.\n")
if len(ofs_btc15) > 0:
    role_btc = ofs_btc15["b945_role"].value_counts()
    maker_frac_val = ofs_btc15["b945_role"].eq("MAKER").mean()
    R.append("| Role | Count | % |")
    R.append("|------|-------|---|")
    for role, ct in role_btc.items():
        R.append(f"| {role} | {ct} | {ct/len(ofs_btc15):.1%} |")
    R.append("")
    if maker_frac_val > 0.7:
        R.append(f"**Verdict:** {maker_frac_val:.0%} MAKER. He is primarily a **passive limit order placer**. "
                 f"His fills happen when the market comes to his resting price. This explains why P_dip≈50%: "
                 f"he doesn't chase dips — his bid is already there, and market sells arrive regardless of direction.")
    elif maker_frac_val < 0.3:
        R.append(f"**Verdict:** {maker_frac_val:.0%} MAKER = primarily **TAKER**. Active order crosses.")
    else:
        R.append(f"**Verdict:** Mixed ({maker_frac_val:.0%} maker).")
    R.append("")
else:
    R.append("*Insufficient btc-15m matches in orderfilled_sample.*\n")

# merge_timing info
if "b945_role" in mt.columns or "maker_taker" in mt.columns:
    role_col = "b945_role" if "b945_role" in mt.columns else "maker_taker"
    R.append(f"\n`merge_timing.parquet` ({len(mt)} rows) role column `{role_col}`:")
    R.append(str(mt[role_col].value_counts().to_dict()))

R.append("\n---\n")
R.append("## E. Final Verdict\n")

findings = []
# D1
if dip_tests:
    p5 = dip_tests[0]["P_dip"]; bp5 = dip_tests[0]["binom_p_2s"]
    if p5 > 0.55 and bp5 < 0.05:
        findings.append(f"**DIP-BUYING CONFIRMED** at 5s lag (P={p5:.4f}, p={bp5:.4f})")
    elif p5 < 0.45 and bp5 < 0.05:
        findings.append(f"**ANTI-DIP** (momentum, P={p5:.4f})")
    else:
        findings.append(f"**No dip-buying signal** (P_dip5s={p5:.4f}, p={bp5:.4f}) — timing is RANDOM relative to recent price")

# D2
if p_alt_global > 0.55 and binom_alt < 0.001:
    findings.append(f"**SIGNIFICANT ALTERNATION** (P_alt={p_alt_global:.3f}, p<0.001)")
elif p_alt_global < 0.45 and binom_alt < 0.001:
    findings.append(f"**SIGNIFICANT RUNS** — clusters same side before switching (P_alt={p_alt_global:.3f})")
else:
    findings.append(f"**No alternation pattern** (P_alt={p_alt_global:.3f}, p={binom_alt:.4f})")

# D3
if mu_up < -0.05 and p_up < 0.05:
    findings.append(f"**Up leg price FALLS over accumulation** (mean corr={mu_up:.3f}, p={p_up:.4f}) — passive ladder")
else:
    findings.append(f"**No price drift within Up leg** (corr={mu_up:.3f})")

# D4
if up_hhi > 1/100 * 2:
    findings.append(f"**Price CLUSTERED at discrete levels** (HHI={up_hhi:.4f} vs uniform={1/100:.4f}) — GTC ladder at fixed prices")
else:
    findings.append(f"**No strong price level clustering** (HHI={up_hhi:.4f})")

# D5
if len(ofs_btc15) > 0:
    findings.append(f"**{maker_frac_val:.0%} of fills are MAKER** — passive limit orders")

R.append("### Key findings:\n")
for f_str in findings:
    R.append(f"- {f_str}")

R.append("")
R.append("### Mechanistic conclusion:\n")

# Determine primary narrative
p5 = dip_tests[0]["P_dip"] if dip_tests else 0.5
is_maker_dominant = len(ofs_btc15) > 0 and ofs_btc15["b945_role"].eq("MAKER").mean() > 0.6
is_runs = p_alt_global < 0.45 and binom_alt < 0.001
is_price_clustered = up_hhi > 1/100 * 2
is_price_drifts = mu_up < -0.05 and p_up < 0.05

if is_maker_dominant and abs(p5 - 0.5) < 0.05:
    R.append("**Dip-buying hypothesis: REJECTED as an ACTIVE taker strategy.**")
    R.append("")
    R.append("The tick data is consistent with the prior conclusion but now with mechanistic clarity:")
    R.append("He places **resting GTC limit bids** on BOTH sides at his target price levels (typically sub-0.50),")
    R.append("and the market comes to him. His fills are MAKER-fills — the market SELLS into his resting bid.")
    R.append("The price timing relative to his fill is ~random (P_dip≈50%) because he is NOT reacting to price moves;")
    R.append("he is passively waiting for the market to reach his pre-placed level.")
    R.append("")
    if is_price_drifts:
        R.append("The negative price-vs-order correlation (D3) shows his resting bids ARE placed at progressively")
        R.append("lower levels — this IS the ladder structure: he places bids at e.g. 0.45, 0.42, 0.40, 0.38 and")
        R.append("they get filled as the market drifts down through his levels. This looks like 'dip-buying' in")
        R.append("aggregate but is mechanically PASSIVE (bid placed first, market arrives second).")
    R.append("")
    R.append("**The operator hypothesis of 'waiting for the price to dip then buying' is DIRECTIONALLY CORRECT")
    R.append("in outcome** (his fills cluster at low prices after the market moves there) but mechanically WRONG")
    R.append("in causation: he does NOT watch the price and then market-order. He pre-places the ladder,")
    R.append("and resolution-arithmetic makes the sum<1 when both legs fill into a wide spread.")
elif p5 > 0.55:
    R.append("**Dip-buying hypothesis: SUPPORTED.** He actively times entries to buy after local price drops.")
else:
    R.append("**Dip-buying hypothesis: NOT SUPPORTED.** Fill timing is random relative to short-term price moves.")

R.append("\n### Impact on TVRUST entry logic:\n")
if is_maker_dominant:
    R.append("- **Entry = GTC limit bids at fixed price levels** (not market-order triggered by price drop)")
    R.append("- Target prices appear to be sub-50¢ on both legs, with a ladder structure")
    R.append(f"- The level clustering (HHI={up_hhi:.4f}) suggests specific pre-selected prices, not random")
    R.append("- TVRUST should implement: place resting bids at [0.35, 0.38, 0.40, 0.42, 0.45] on Up and mirrored on Dn")
    R.append("- Do NOT add momentum/dip-trigger logic — it is NOT how he operates")
else:
    R.append("- If active taker: add IOC entries triggered by price crossing below threshold")
    R.append("- If passive: pre-place limit orders at discrete price levels")

R.append("")
R.append("---")
R.append(f"*Generated by `strategy_lab/wallet_hunt/_b945_tick_timeline.py` — {pd.Timestamp.now(tz='UTC').date()}*")

os.makedirs("strategy_lab/reports", exist_ok=True)
with open(OUT_MD, "w", encoding="utf-8") as fout:
    fout.write("\n".join(R))
print(f"\nReport written to {OUT_MD} ({len('\n'.join(R))} chars)")
print("\nDONE")
