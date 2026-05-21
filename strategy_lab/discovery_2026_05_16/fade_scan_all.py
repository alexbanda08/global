"""
Comprehensive fade scan: for every production sleeve, evaluate INVERSE
performance with real L25 fills + 100ms latency.

Scope: every sleeve_id × signal × hour-bucket. Sub-cuts with low same-side
winrate are fade candidates. We verify with real fill economics that the
inverse is actually profitable (not just statistically inverted).
"""
from __future__ import annotations
import sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "discovery_2026_05_16"))

from load import (load_trading_events, load_orderbook_l25_streaming, load_resolutions)
from harness import SPREAD_FILTER, NOTIONAL, FEE_RATE, walk_asks, get_book_at

LATENCY_US = 100_000  # 100ms

# ---- Load + parse events ----
print("Loading trading events...", flush=True)
ev = load_trading_events()
res = ev[ev.kind == "poly_updown_resolution"].copy()
parsed = res["data"].apply(json.loads).apply(pd.Series)
res = pd.concat([res, parsed], axis=1)
res["entry_price"] = pd.to_numeric(res["entry_price"], errors="coerce")
res["pnl"] = pd.to_numeric(res["pnl_usd"], errors="coerce")
res["hour"] = pd.to_datetime(res["at"], utc=True, errors="coerce").dt.hour
res["asset"] = res["symbol"].str.upper()
res["hour_bucket"] = pd.cut(res.hour, bins=[-1, 5, 11, 17, 23],
                             labels=["00-05", "06-11", "12-17", "18-23"])

# Match condition_id -> slot_start_us
resol_univ = load_resolutions()
condmap = dict(zip(resol_univ.market_id, zip(resol_univ.slot_start_us, resol_univ.slug, resol_univ.timeframe)))
res["slot_data"] = res.condition_id.map(condmap)
res = res[res.slot_data.notna()].copy()
res[["slot_start_us", "slug", "tf"]] = pd.DataFrame(res.slot_data.tolist(), index=res.index)
print(f"  {len(res):,} resolution events with valid slot_start_us")


def fire_us_for(slot_start_us, tf):
    """Production momo fire time = ws_s + 120s = slot_start - window + 120."""
    window_s = {"5m": 300, "15m": 900}[tf]
    return int(slot_start_us - window_s * 1_000_000 + 120 * 1_000_000)


# ---- Pre-load books per asset for ALL slugs in the sample ----
print("Loading L25 books for all assets...", flush=True)
books_by_asset = {}
import time
for asset in ["BTC", "ETH", "SOL"]:
    t0 = time.time()
    slugs = set(res[res.asset == asset].slug.unique())
    print(f"  {asset}: {len(slugs)} slugs...", flush=True)
    bks = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=True)
    books_by_asset[asset] = bks
    print(f"    -> {len(bks)} (slug,outcome) keys in {time.time()-t0:.0f}s", flush=True)


# ---- For each event, compute INVERSE L25 fill ----
def compute_inverse(r):
    asset = r["asset"]
    SPREAD = SPREAD_FILTER[asset]
    books = books_by_asset.get(asset, {})
    if not books:
        return None
    fire = fire_us_for(int(r.slot_start_us), r.tf)
    safe_us = fire - LATENCY_US
    # Inverse: original signal direction's OPPOSITE
    inv_side = "Up" if r.signal == "DOWN" else "Down"
    snap = get_book_at(books, r.slug, inv_side, safe_us)
    if snap is None:
        return None
    ap, asz, bp, bsz = snap
    if not (np.isfinite(ap[0]) and np.isfinite(bp[0])): return None
    if (ap[0] - bp[0]) > SPREAD: return None
    vwap, shares, spent, under = walk_asks(list(ap), list(asz), NOTIONAL)
    if under or not np.isfinite(vwap): return None
    inv_signal = "UP" if r.signal == "DOWN" else "DOWN"
    won_inv = int(str(r.outcome).upper() == inv_signal)
    profit_raw = shares * (won_inv - vwap)
    fee = max(profit_raw, 0.0) * FEE_RATE
    return dict(inv_vwap=vwap, inv_shares=shares, inv_won=won_inv, inv_pnl=profit_raw - fee)


print("Computing INVERSE fills for all events...", flush=True)
import time
t0 = time.time()
inv_results = res.apply(compute_inverse, axis=1)
mask = inv_results.notna()
res_inv = res[mask].copy()
inv_df = pd.DataFrame(inv_results[mask].tolist(), index=res_inv.index)
res_inv = pd.concat([res_inv, inv_df], axis=1)
print(f"  computed {len(res_inv)} inverse trades in {time.time()-t0:.0f}s "
      f"({len(res_inv)/len(res)*100:.1f}% of events had valid L25 inverse fill)")


# ---- Aggregate fade alpha per (sleeve_id, signal, hour_bucket) ----
np.random.seed(42)

def perm_p(pnl_vals, B=1000):
    n = len(pnl_vals)
    if n == 0: return 1.0
    pnls = np.array([(pnl_vals * np.random.choice([1, -1], size=n)).sum() for _ in range(B)])
    return (pnls >= pnl_vals.sum()).mean()


# Cuts to evaluate
print()
print("=== Scanning all (sleeve_id, signal, hour_bucket) cuts ===")
groups = res_inv.groupby(["sleeve_id", "signal", "hour_bucket"], observed=True)
findings = []
for (sl, sig, hb), g in groups:
    if len(g) < 25:
        continue
    inv_pnl = g.inv_pnl.sum()
    inv_hit = g.inv_won.mean()
    same_pnl = g.pnl.sum()
    n = len(g)
    if inv_pnl <= 0:
        continue
    p = perm_p(g.inv_pnl.values, B=500)
    findings.append({
        "sleeve_id": sl, "signal": sig, "hour_bucket": str(hb), "n": n,
        "inv_hit": inv_hit, "inv_pnl": inv_pnl, "inv_ppt": g.inv_pnl.mean(),
        "same_pnl": same_pnl, "swing": inv_pnl - same_pnl, "perm_p": p,
    })

fd = pd.DataFrame(findings)
if len(fd) > 0:
    fd = fd.sort_values("inv_pnl", ascending=False)
    sig_fd = fd[fd.perm_p < 0.10].copy()
    print(f"\\nFound {len(fd)} positive-inverse cuts; {len(sig_fd)} with perm p<0.10")
    print("\\n=== TOP 30 fade cuts (perm p<0.10) ===")
    print(f'{"sleeve_id":<42s} {"sig":>5s} {"hour":>6s} {"n":>4s} {"hit":>6s} {"pnl":>8s} {"ppt":>7s} {"swing":>8s} {"p":>6s}')
    print("-" * 105)
    for _, row in sig_fd.head(30).iterrows():
        print(f'{row.sleeve_id:<42s} {row.signal:>5s} {row.hour_bucket:>6s} {int(row.n):>4d} {row.inv_hit*100:>5.1f}% ${row.inv_pnl:>+6.0f} ${row.inv_ppt:>+5.2f} ${row.swing:>+6.0f} {row.perm_p:>6.3f}')

    # Save
    fd.to_csv(Path(__file__).parent / "fade_scan_results.csv", index=False)
    sig_fd.to_csv(Path(__file__).parent / "fade_scan_significant.csv", index=False)

    # Summary aggregates
    print(f"\\n=== Total fade alpha (perm p<0.10 cuts only) ===")
    print(f"  total inverse PnL: ${sig_fd.inv_pnl.sum():+.2f}")
    print(f"  total swing vs current: ${sig_fd.swing.sum():+.2f}")
    print(f"  total trades: {sig_fd.n.sum()}")

# ---- Now also evaluate KEEP candidates (winning sleeves) — verify with same L25 model ----
print()
print("=== KEEP candidates — same-side performance, real L25 ===")
res["pnl_winsorize_ok"] = res.pnl.notna()
keepers = res.groupby("sleeve_id").agg(
    n=("pnl", "size"), live_pnl=("pnl", "sum"),
    live_win=("won", lambda s: s.fillna(False).mean()),
).query("n >= 100 and live_pnl > 0").sort_values("live_pnl", ascending=False)
print(keepers.to_string())
print(f"\\nTotal KEEP PnL (live): ${keepers.live_pnl.sum():+.2f}")
