"""
Fill-selection check for the one Phase-A survivor: DISAGR-HAWKES SOL 5m @210 DN.

Question: the signal fires 264 times but only ~48% fill at $25 within 2c spread.
Is that 48% a BIASED subset? If the UNFILLED fires are disproportionately WINNERS,
then live (which only gets the fillable ones) understates losses -> edge is a mirage.

For every DN fire we know `won` regardless of fill. We classify each fire's fill
outcome + reason and compare won-rate filled vs unfilled, and break down WHY unfilled.
"""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from engine_v2 import LiveMimicConfig, find_book_strict, book_event_count  # noqa
from book_walk import book_walk_fill  # noqa
from load import load_orderbook_l25_streaming  # noqa

cfg = LiveMimicConfig(); SPREAD = 0.02; NOTIONAL = 25.0
m = pd.read_parquet(ROOT / "strategy_lab" / "cross_feature_2026_05_26" / "master.parquet")
d = m[(m.asset == "SOL") & (m.tf == "5m") & (m.fire_offset_s == 210)].reset_index(drop=True)
dn = (d.mp_skew < 0) & (d.imb5_diff > 0) & (d.hawkes_lambda_imbalance < -0.2)
fires = d[dn].copy()
fires["won"] = fires["outcome"] == "Down"   # DN bet
print(f"DISAGR-HAWKES SOL5m DN fires={len(fires)}  raw WR(all fires)={100*fires.won.mean():.1f}%", flush=True)

slugs = set(fires.slug.unique())
tmin = int(fires.fire_us.min()) - 130_000_000
tmax = int(fires.fire_us.max()) + 1_000_000
books = load_orderbook_l25_streaming("sol", slugs=slugs, subsample_1hz=False,
                                     min_ts_us=tmin, max_ts_us=tmax)

def classify(slug, fire_us):
    lookup = int(fire_us) + int(cfg.latency_ms * 1000)
    ws = lookup - 120_000_000
    nev = book_event_count(books, slug, "Down", ws, lookup)
    if nev < cfg.min_book_events:
        return "few_book_events", nev, math.nan, math.nan
    bk = find_book_strict(books, slug, "Down", lookup, max_staleness_us=cfg.max_book_staleness_us)
    if bk is None:
        return "stale_or_nopre", nev, math.nan, math.nan
    ap, asz, bp = bk["ap"], bk["asz"], bk["bp"]
    a0 = float(ap[0]) if (len(ap) and math.isfinite(ap[0])) else math.nan
    b0 = float(bp[0]) if (len(bp) and math.isfinite(bp[0])) else math.nan
    spr = (a0 - b0) if (math.isfinite(a0) and math.isfinite(b0)) else math.nan
    if math.isfinite(spr) and spr > SPREAD:
        return "wide_spread", nev, spr, a0
    vwap, sh, usd, lv, under = book_walk_fill([float(x) for x in ap], [float(x) for x in asz],
                                              NOTIONAL, side="buy")
    if sh <= 0 or (under and usd < NOTIONAL * 0.5):
        return "underfill", nev, spr, a0
    return "FILLED", nev, spr, vwap

rows = []
for r in fires.itertuples():
    reason, nev, spr, px = classify(r.slug, int(r.fire_us))
    rows.append((reason, r.won, nev, spr, px))
res = pd.DataFrame(rows, columns=["reason", "won", "n_events", "spread", "px"])

print("\n=== fill outcome breakdown ===", flush=True)
g = res.groupby("reason").agg(n=("won", "size"), wr=("won", lambda s: round(100*s.mean(), 1)),
                              med_spread=("spread", lambda s: round(np.nanmedian(s), 4)),
                              med_events=("n_events", lambda s: int(np.nanmedian(s)))).sort_values("n", ascending=False)
print(g.to_string(), flush=True)

filled = res.reason == "FILLED"
print(f"\nFILLED  n={filled.sum():3}  WR={100*res.loc[filled,'won'].mean():.1f}%", flush=True)
print(f"UNFILL  n={(~filled).sum():3}  WR={100*res.loc[~filled,'won'].mean():.1f}%", flush=True)
print(f"ALL     n={len(res):3}  WR={100*res.won.mean():.1f}%", flush=True)
# selection-bias test: chi-square-ish — diff in won-rate filled vs unfilled
from scipy import stats
wf, wu = res.loc[filled, "won"], res.loc[~filled, "won"]
if len(wf) > 1 and len(wu) > 1:
    z, p = stats.ttest_ind(wf.astype(float), wu.astype(float), equal_var=False)
    print(f"\nfilled-vs-unfilled won-rate diff: t={z:.2f} p={p:.3f}", flush=True)
    print("INTERPRETATION:", flush=True)
    if p < 0.05 and wu.mean() > wf.mean():
        print("  *** UNFILLED fires WIN MORE -> live edge OVERSTATED (we miss winners). RED FLAG.", flush=True)
    elif p < 0.05 and wu.mean() < wf.mean():
        print("  unfilled fires LOSE more -> the spread/book filter AVOIDS losers -> edge intact/better.", flush=True)
    else:
        print("  no significant won-rate difference -> fill rate just reduces n, edge not selection-biased.", flush=True)
res.to_csv(ROOT / "strategy_lab" / "cross_feature_2026_05_26" / "fill_selection_disagr_2026_06_03.csv", index=False)
