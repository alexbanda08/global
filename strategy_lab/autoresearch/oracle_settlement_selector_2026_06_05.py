"""
EXPERIMENT 1 — Oracle-determinism settlement selector (slug selection).

Thesis: ~12-20% of slugs are DECIDED by Chainlink (|oracle dist from strike| >= 15bp) 30-60s before settle,
with ~99.9% accuracy. If the poly price of the oracle-implied winner LAGS the oracle there (price < realized
win rate), buying it and holding to settle is a structural edge. 3 gates (all must pass):
  STEP 1 FIDELITY: does our RTDS-chainlink reproduce the actual settle outcome? (settlement_price vs strike)
  STEP 2 POLY-LAG: on decided slugs, is poly price of the oracle-winner < acc? realized print-space EV>0?
  STEP 3 FILL:     does it survive a real L25 ask-walk ($25, 0.07 winner-only fee) + slug-block CI? (print!=fill)
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical")); sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_resolutions, load_chainlink_asof, load_orderbook_l25_streaming
from engine_v2 import LiveMimicConfig, fill_at_book, hold_pnl
np.random.seed(0)
CANON = ROOT / "data/v4/canonical"
ASSETS = ["BTC", "ETH", "SOL"]; TFS = ["5m", "15m"]
X = 60                 # seconds before slot_end (anchor); acc ~99.9% at |dist|>=15bp
DIST_BP = 15.0         # oracle-decided threshold
cfg = LiveMimicConfig()

def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)

cl = {a: load_chainlink_asof(a) for a in ASSETS}
res = load_resolutions(assets=ASSETS, timeframes=TFS)
res = res[res.outcome.isin(["Up", "Down"])].dropna(subset=["strike_price", "settlement_price"]).copy()

# ---------- STEP 1: fidelity (does chainlink settle reproduce the resolution?) ----------
strike = res.strike_price.values.astype(float); settle = res.settlement_price.values.astype(float)
res["oracle_outcome"] = np.where(settle > strike, "Up", "Down")
fid = (res.oracle_outcome == res.outcome).mean()
print(f"STEP 1 FIDELITY: sign(settlement-strike)==resolution outcome on {len(res)} slugs = {fid:.4f}")

# decided set at T-X using the RTDS chainlink feed (the live-observable signal)
asset_of = res.ticker.values if "ticker" in res.columns else res.slug.str.split("-").str[0].str.upper().values
res["asset_"] = asset_of
end_us = res.slot_end_us.values.astype("int64")
px_tx = np.empty(len(res));
for a in ASSETS:
    m = res.asset_.values == a
    if m.sum(): px_tx[m] = asof(cl[a][0], cl[a][1], end_us[m] - X * 1_000_000)
res["dist_bp"] = (px_tx - strike) / strike * 1e4
res["rtds_winner"] = np.where(res.dist_bp > 0, "Up", "Down")
dec = res[np.isfinite(res.dist_bp) & (res.dist_bp.abs() >= DIST_BP)].copy()
acc = (dec.rtds_winner == dec.outcome).mean()
print(f"DECIDED set (|dist|>={DIST_BP}bp at T-{X}s): n={len(dec)} ({len(dec)/len(res):.1%} of slugs) "
      f"RTDS-winner accuracy={acc:.4f}")

# ---------- STEP 2: poly-lag (price of the oracle-winner at T-X via trade tape) ----------
print("\nSTEP 2 POLY-LAG (price of oracle-winner at T-X; edge if price < acc):")
rows = []
for a in ASSETS:
    da = dec[dec.asset_ == a]
    if not len(da): continue
    flt = [("slug", "in", set(da.slug))]
    t = pd.read_parquet(CANON / "trades_polymarket" / f"{a.lower()}.parquet",
                        columns=["slug", "outcome", "timestamp_us", "price"], filters=flt)
    t = t.sort_values("timestamp_us")
    grp = {k: (g.timestamp_us.values, g.price.values) for k, g in t.groupby(["slug", "outcome"])}
    for _, r in da.iterrows():
        anchor = int(r.slot_end_us) - X * 1_000_000
        key = (r.slug, r.rtds_winner)
        if key not in grp: continue
        ts, px = grp[key]
        j = np.searchsorted(ts, anchor, "right") - 1
        if j < 0: continue
        p = float(px[j])
        won = (r.rtds_winner == r.outcome)
        pnl = (1 - p) * (1 - 0.07 * p) if won else -p          # hold-to-settle, 0.07 winner-only, per share
        rows.append(dict(asset=a, slug=r.slug, p=p, won=won, pnl=pnl, dist_bp=abs(r.dist_bp)))
S = pd.DataFrame(rows)
print(f"  decided slugs with a poly print for the winner before T-{X}s: {len(S)}")
def boot(v, nb=4000):
    v = np.asarray(v);
    if len(v) < 5: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))
for lab, d in [("ALL", S)] + [(a, S[S.asset == a]) for a in ASSETS]:
    if len(d) < 10: continue
    lo, hi = boot(d.pnl.values)
    print(f"  [{lab}] n={len(d):4d} win_rate={d.won.mean():.4f} mean_price={d.p.mean():.4f} "
          f"print_EV/sh={d.pnl.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}]  (lag={d.won.mean()-d.p.mean():+.4f})")
# price-bucketed (where is poly cheapest vs decided?)
S["pb"] = pd.cut(S.p, [0, .8, .9, .95, .98, 1.01])
print("\n  by poly price bucket (oracle-winner):")
g = S.groupby("pb", observed=True).agg(n=("won", "size"), wr=("won", "mean"), price=("p", "mean"), ev=("pnl", "mean"))
print(g.round(4).to_string())

# ---------- STEP 3: fill test (L25 ask-walk on the oracle-winner at T-X) ----------
print(f"\nSTEP 3 FILL (L25 $25 ask-walk on oracle-winner at T-{X}s, hold to settle):")
samp = dec.groupby("asset_", group_keys=False).apply(lambda d: d.sample(min(len(d), 250), random_state=0))
fr = []
for a in ASSETS:
    da = samp[samp.asset_ == a]
    if not len(da): continue
    slugs = list(da.slug); B = 250
    for i in range(0, len(slugs), B):
        chunk = set(slugs[i:i+B])
        books = load_orderbook_l25_streaming(a.lower(), slugs=chunk, subsample_1hz=False)
        for _, r in da[da.slug.isin(chunk)].iterrows():
            anchor = int(r.slot_end_us) - X * 1_000_000
            f = fill_at_book(books, r.slug, r.rtds_winner, anchor, cfg=cfg, side="buy",
                             spread_filter=0.05, notional_usd=25.0)
            if f is None:
                fr.append(dict(asset=a, filled=0, pnl=np.nan, p=np.nan, won=None)); continue
            won = (r.rtds_winner == r.outcome)
            fr.append(dict(asset=a, filled=1, p=f["vwap"], won=won, pnl=hold_pnl(f, won=won, cfg=cfg)))
        del books
FR = pd.DataFrame(fr)
ff = FR[FR.filled == 1]
print(f"  sampled {len(FR)}  fill_rate={FR.filled.mean():.2f}  filled n={len(ff)} mean_vwap={ff.p.mean():.4f}")
if len(ff) >= 10:
    lo, hi = boot(ff.pnl.values)
    print(f"  FILLED hold-to-settle: $/tr={ff.pnl.mean():+.4f} (per $25 stake) won={ff.won.mean():.4f} CI=[{lo:+.3f},{hi:+.3f}]")
print("\nREAD: edge real only if STEP2 print_EV>0 with CI>0 AND STEP3 filled $/tr>0 with CI>0 (print!=fill).")
