"""
RIGOROUS audit of every (sleeve, signal, hour_bucket) cut.
For each cut, compute SAME-side and INVERSE-side stats with:
  - real L25 fills + 100ms latency
  - 2000-draw permutation test
  - 2000-iteration bootstrap 95% CI on $/trade
  - walk-forward by weekly block (4 weeks)
  - Bonferroni correction applied at the end

Includes ALL sleeves (not just losing ones) — KEEP candidates might have
positive SAME at some cuts and positive INVERSE at others.
"""
from __future__ import annotations
import sys, json, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "discovery_2026_05_16"))

from load import (load_trading_events, load_orderbook_l25_streaming, load_resolutions)
from harness import SPREAD_FILTER, NOTIONAL, FEE_RATE, walk_asks, get_book_at

LATENCY_US = 100_000
DIR = Path(__file__).resolve().parent

print("Loading events...", flush=True)
ev = load_trading_events()
res = ev[ev.kind == "poly_updown_resolution"].copy()
parsed = res["data"].apply(json.loads).apply(pd.Series)
res = pd.concat([res, parsed], axis=1)
res["entry_price"] = pd.to_numeric(res["entry_price"], errors="coerce")
res["pnl"] = pd.to_numeric(res["pnl_usd"], errors="coerce")
res["at_ts"] = pd.to_datetime(res["at"], utc=True, errors="coerce")
res["hour"] = res["at_ts"].dt.hour
res["dow"] = res["at_ts"].dt.dayofweek
res["week"] = res["at_ts"].dt.isocalendar().week
res["asset"] = res["symbol"].str.upper()
res["hour_bucket"] = pd.cut(res.hour, bins=[-1, 5, 11, 17, 23],
                             labels=["00-05", "06-11", "12-17", "18-23"])

resol_univ = load_resolutions()
condmap = dict(zip(resol_univ.market_id, zip(resol_univ.slot_start_us, resol_univ.slug, resol_univ.timeframe)))
res["slot_data"] = res.condition_id.map(condmap)
res = res[res.slot_data.notna()].copy()
res[["slot_start_us", "slug", "tf"]] = pd.DataFrame(res.slot_data.tolist(), index=res.index)
print(f"  {len(res):,} resolution events")


# Pre-load books
books_by_asset = {}
for asset in ["BTC", "ETH", "SOL"]:
    t0 = time.time()
    slugs = set(res[res.asset == asset].slug.unique())
    print(f"  loading {asset} L25 ({len(slugs)} slugs)...", flush=True)
    books_by_asset[asset] = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=True)
    print(f"    -> {len(books_by_asset[asset])} keys in {time.time()-t0:.0f}s", flush=True)


def fire_us_for(slot_start_us, tf):
    window_s = {"5m": 300, "15m": 900}[tf]
    return int(slot_start_us - window_s * 1_000_000 + 120 * 1_000_000)


def compute_fills(r):
    """Compute SAME-side and INVERSE-side L25 fill PnL."""
    asset = r["asset"]; SPREAD = SPREAD_FILTER[asset]
    books = books_by_asset.get(asset, {})
    if not books: return None
    fire = fire_us_for(int(r.slot_start_us), r.tf)
    safe_us = fire - LATENCY_US
    out = {}
    for side_label, signal_dir in [("same", r.signal), ("inv", "DOWN" if r.signal == "UP" else "UP")]:
        side = "Up" if signal_dir == "UP" else "Down"
        snap = get_book_at(books, r.slug, side, safe_us)
        if snap is None:
            out[f"{side_label}_pnl"] = np.nan
            out[f"{side_label}_won"] = np.nan
            out[f"{side_label}_vwap"] = np.nan
            continue
        ap, asz, bp, bsz = snap
        if not (np.isfinite(ap[0]) and np.isfinite(bp[0])) or (ap[0] - bp[0]) > SPREAD:
            out[f"{side_label}_pnl"] = np.nan
            out[f"{side_label}_won"] = np.nan
            out[f"{side_label}_vwap"] = np.nan
            continue
        vwap, shares, spent, under = walk_asks(list(ap), list(asz), NOTIONAL)
        if under or not np.isfinite(vwap):
            out[f"{side_label}_pnl"] = np.nan
            out[f"{side_label}_won"] = np.nan
            out[f"{side_label}_vwap"] = np.nan
            continue
        won = int(str(r.outcome).upper() == signal_dir)
        profit_raw = shares * (won - vwap)
        fee = max(profit_raw, 0.0) * FEE_RATE
        out[f"{side_label}_pnl"] = profit_raw - fee
        out[f"{side_label}_won"] = won
        out[f"{side_label}_vwap"] = vwap
    return out


print("Computing fills (SAME + INVERSE) for every event...", flush=True)
t0 = time.time()
fills = res.apply(compute_fills, axis=1)
mask = fills.notna()
res = res[mask].copy()
fills_df = pd.DataFrame(fills[mask].tolist(), index=res.index)
res = pd.concat([res, fills_df], axis=1)
# Require both same + inv to be valid
res = res.dropna(subset=["same_pnl", "inv_pnl"]).copy()
print(f"  computed {len(res)} events with both fills in {time.time()-t0:.0f}s")


# ---- RIGOROUS PER-CUT TEST ----
np.random.seed(42)
B_PERM = 2000
B_BOOT = 2000


def cut_stats(g, side):
    """Run perm + bootstrap on a group for one side (same or inv)."""
    pnl = g[f"{side}_pnl"].values
    won = g[f"{side}_won"].values
    n = len(pnl)
    total = pnl.sum()
    ppt = pnl.mean()
    hit = won.mean()
    # Permutation
    perm_pnls = np.array([(pnl * np.random.choice([1, -1], size=n)).sum() for _ in range(B_PERM)])
    p_val = (perm_pnls >= total).mean()
    # Bootstrap
    boot = np.array([pnl[np.random.choice(n, n, replace=True)].mean() for _ in range(B_BOOT)])
    return dict(n=n, hit=hit, pnl=total, ppt=ppt, perm_p=p_val,
                ci_lo=np.percentile(boot, 2.5), ci_hi=np.percentile(boot, 97.5))


print("\nScanning every (sleeve, signal, hour_bucket) cut with n>=25...", flush=True)
groups = res.groupby(["sleeve_id", "signal", "hour_bucket"], observed=True)
records = []
n_cuts_tested = 0
for (sl, sig, hb), g in groups:
    if len(g) < 25:
        continue
    n_cuts_tested += 1
    same = cut_stats(g, "same")
    inv = cut_stats(g, "inv")
    rec = {"sleeve_id": sl, "signal": sig, "hour_bucket": str(hb)}
    rec.update({f"same_{k}": v for k, v in same.items()})
    rec.update({f"inv_{k}": v for k, v in inv.items()})
    records.append(rec)

cuts = pd.DataFrame(records)
print(f"  tested {n_cuts_tested} cuts")


# ---- Walk-forward by week ----
print("\nWalk-forward per cut (4 weekly blocks)...", flush=True)
def walk_forward(g, side):
    weeks = sorted(g.week.unique())
    per_week = {}
    for w in weeks:
        sub = g[g.week == w]
        if len(sub) >= 5:
            per_week[int(w)] = float(sub[f"{side}_pnl"].sum())
    return per_week

wf = []
for _, row in cuts.iterrows():
    g = res[(res.sleeve_id == row.sleeve_id) & (res.signal == row.signal) & (res.hour_bucket.astype(str) == row.hour_bucket)]
    if len(g) < 25: continue
    same_wf = walk_forward(g, "same")
    inv_wf = walk_forward(g, "inv")
    weeks_pos_same = sum(1 for v in same_wf.values() if v > 0)
    weeks_pos_inv = sum(1 for v in inv_wf.values() if v > 0)
    wf.append({"sleeve_id": row.sleeve_id, "signal": row.signal, "hour_bucket": row.hour_bucket,
               "n_weeks": len(same_wf),
               "same_weeks_pos": weeks_pos_same, "inv_weeks_pos": weeks_pos_inv,
               "same_pnl_by_week": str(same_wf), "inv_pnl_by_week": str(inv_wf)})
wf_df = pd.DataFrame(wf)
cuts = cuts.merge(wf_df, on=["sleeve_id", "signal", "hour_bucket"], how="left")


# ---- Multiple-testing correction ----
n_tests = len(cuts) * 2  # we test both same and inv on each cut
bonf_alpha = 0.05 / n_tests
print(f"\nBonferroni α = 0.05 / {n_tests} = {bonf_alpha:.2e}")

# Top fade survivors (inv positive, p < bonf, walk-forward positive in majority of weeks)
fade_strict = cuts[
    (cuts.inv_pnl > 0)
    & (cuts.inv_perm_p < bonf_alpha)
    & (cuts.inv_weeks_pos >= cuts.n_weeks / 2)
    & (cuts.inv_ci_lo > 0)
].sort_values("inv_pnl", ascending=False)

# Relaxed (p < 0.05, no Bonferroni)
fade_relaxed = cuts[
    (cuts.inv_pnl > 0)
    & (cuts.inv_perm_p < 0.05)
    & (cuts.inv_weeks_pos >= cuts.n_weeks / 2)
    & (cuts.inv_ci_lo > 0)
].sort_values("inv_pnl", ascending=False)

# KEEP strict (same positive, p < bonf, wf majority pos, CI > 0)
keep_strict = cuts[
    (cuts.same_pnl > 0)
    & (cuts.same_perm_p < bonf_alpha)
    & (cuts.same_weeks_pos >= cuts.n_weeks / 2)
    & (cuts.same_ci_lo > 0)
].sort_values("same_pnl", ascending=False)
keep_relaxed = cuts[
    (cuts.same_pnl > 0)
    & (cuts.same_perm_p < 0.05)
    & (cuts.same_weeks_pos >= cuts.n_weeks / 2)
    & (cuts.same_ci_lo > 0)
].sort_values("same_pnl", ascending=False)

print(f"\nSTRICT survivors (Bonferroni α={bonf_alpha:.2e}, WF majority pos, CI lo > 0):")
print(f"  FADE: {len(fade_strict)} cuts")
print(f"  KEEP: {len(keep_strict)} cuts")
print(f"\nRELAXED (p<0.05, WF majority pos, CI lo > 0):")
print(f"  FADE: {len(fade_relaxed)} cuts")
print(f"  KEEP: {len(keep_relaxed)} cuts")

print("\n=== TOP 20 FADE — STRICT (Bonferroni) ===")
cols = ["sleeve_id","signal","hour_bucket","inv_n","inv_hit","inv_pnl","inv_ppt","inv_perm_p","inv_ci_lo","inv_ci_hi","inv_weeks_pos","n_weeks"]
display = fade_strict[cols].head(20).copy() if len(fade_strict) else pd.DataFrame()
if len(display):
    print(display.to_string(index=False, float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else x))
else:
    print("  (none — all cuts fail Bonferroni)")

print("\n=== TOP 20 FADE — RELAXED (p<0.05) ===")
display = fade_relaxed[cols].head(20).copy() if len(fade_relaxed) else pd.DataFrame()
if len(display):
    print(display.to_string(index=False, float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else x))

print("\n=== TOP 20 KEEP — STRICT (Bonferroni) ===")
cols_k = ["sleeve_id","signal","hour_bucket","same_n","same_hit","same_pnl","same_ppt","same_perm_p","same_ci_lo","same_ci_hi","same_weeks_pos","n_weeks"]
display = keep_strict[cols_k].head(20).copy() if len(keep_strict) else pd.DataFrame()
if len(display):
    print(display.to_string(index=False, float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else x))
else:
    print("  (none — all cuts fail Bonferroni)")

print("\n=== TOP 20 KEEP — RELAXED (p<0.05) ===")
display = keep_relaxed[cols_k].head(20).copy() if len(keep_relaxed) else pd.DataFrame()
if len(display):
    print(display.to_string(index=False, float_format=lambda x: f"{x:.4f}" if isinstance(x, float) else x))


# ---- COMBINED PORTFOLIO: KEEP cuts + FADE cuts together ----
print("\n=== COMBINED PORTFOLIO (RELAXED set) — day-blocked bootstrap ===")
# Build per-trade pnl for the combined portfolio
keep_keys = set((r.sleeve_id, r.signal, r.hour_bucket) for _, r in keep_relaxed.iterrows())
fade_keys = set((r.sleeve_id, r.signal, r.hour_bucket) for _, r in fade_relaxed.iterrows())
res["pf_pnl"] = 0.0
res["in_keep"] = res.apply(lambda r: (r.sleeve_id, r.signal, str(r.hour_bucket)) in keep_keys, axis=1)
res["in_fade"] = res.apply(lambda r: (r.sleeve_id, r.signal, str(r.hour_bucket)) in fade_keys, axis=1)
res.loc[res.in_keep, "pf_pnl"] = res.loc[res.in_keep, "same_pnl"]
res.loc[res.in_fade, "pf_pnl"] = res.loc[res.in_fade, "inv_pnl"]
portfolio = res[res.in_keep | res.in_fade]
print(f"  portfolio trades (KEEP + FADE): {len(portfolio)}")
print(f"  total PnL: ${portfolio.pf_pnl.sum():+.2f}")
print(f"  $/trade: ${portfolio.pf_pnl.mean():+.2f}")
print(f"  win rate: {((portfolio.in_keep & (portfolio.same_won==1)) | (portfolio.in_fade & (portfolio.inv_won==1))).mean():.4f}")

# Day-blocked bootstrap
portfolio["date"] = portfolio["at_ts"].dt.date
day_pnl = portfolio.groupby("date").pf_pnl.sum().values
days_n = len(day_pnl)
boot_totals = []
np.random.seed(42)
for _ in range(2000):
    sample_days = np.random.choice(days_n, days_n, replace=True)
    boot_totals.append(day_pnl[sample_days].sum())
boot_totals = np.array(boot_totals)
print(f"  Day-blocked bootstrap 95% CI on total PnL: [${np.percentile(boot_totals,2.5):+.0f}, ${np.percentile(boot_totals,97.5):+.0f}]")
print(f"  p(PnL > 0): {(boot_totals > 0).mean():.4f}")
print(f"  median bootstrap PnL: ${np.median(boot_totals):+.0f}")

# Save
cuts.to_csv(DIR / "rigorous_fade_audit_cuts.csv", index=False)
fade_strict.to_csv(DIR / "rigorous_fade_strict.csv", index=False)
fade_relaxed.to_csv(DIR / "rigorous_fade_relaxed.csv", index=False)
keep_strict.to_csv(DIR / "rigorous_keep_strict.csv", index=False)
keep_relaxed.to_csv(DIR / "rigorous_keep_relaxed.csv", index=False)
print(f"\nSaved CSVs to {DIR}")
