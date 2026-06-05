"""
EXPERIMENT 1b — fill-test the CHEAP-but-DECIDED subset (the only place the oracle selector has juice).
Slugs where Chainlink is decided (|dist|>=15bp at T-X, acc ~99.6%) AND the poly oracle-winner print is
still cheap (< 0.95 / < 0.90) at T-X -> latency/inattention mispricing. Does it actually FILL on L25?
Also test T-30 (sharper determinism) and stake $5 (thin-book friendly).
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
CANON = ROOT / "data/v4/canonical"; ASSETS = ["BTC", "ETH", "SOL"]; TFS = ["5m", "15m"]
DIST_BP = 15.0

def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)
def boot(v, nb=4000):
    v = np.asarray(v)
    if len(v) < 5: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))

cl = {a: load_chainlink_asof(a) for a in ASSETS}
res = load_resolutions(assets=ASSETS, timeframes=TFS)
res = res[res.outcome.isin(["Up", "Down"])].dropna(subset=["strike_price", "settlement_price"]).copy()
res["asset_"] = res.ticker.values if "ticker" in res.columns else res.slug.str.split("-").str[0].str.upper().values
strike = res.strike_price.values.astype(float)

for X, stake, pmax in [(60, 25.0, 0.95), (60, 5.0, 0.95), (30, 25.0, 0.95), (60, 25.0, 0.90)]:
    end_us = res.slot_end_us.values.astype("int64"); px_tx = np.empty(len(res))
    for a in ASSETS:
        m = res.asset_.values == a
        if m.sum(): px_tx[m] = asof(cl[a][0], cl[a][1], end_us[m] - X * 1_000_000)
    dist = (px_tx - strike) / strike * 1e4
    win = np.where(dist > 0, "Up", "Down")
    R = res.assign(dist=dist, rtds_winner=win)
    dec = R[np.isfinite(R.dist) & (np.abs(R.dist) >= DIST_BP)].copy()
    # cheap poly print of winner at T-X (trade tape, decided slugs only)
    keep = []
    for a in ASSETS:
        da = dec[dec.asset_ == a]
        if not len(da): continue
        t = pd.read_parquet(CANON / "trades_polymarket" / f"{a.lower()}.parquet",
                            columns=["slug", "outcome", "timestamp_us", "price"], filters=[("slug", "in", set(da.slug))])
        t = t.sort_values("timestamp_us")
        grp = {k: (g.timestamp_us.values, g.price.values) for k, g in t.groupby(["slug", "outcome"])}
        for _, r in da.iterrows():
            key = (r.slug, r.rtds_winner); anchor = int(r.slot_end_us) - X * 1_000_000
            if key not in grp: continue
            ts, px = grp[key]; j = np.searchsorted(ts, anchor, "right") - 1
            if j < 0: continue
            p = float(px[j])
            if p < pmax: keep.append((a, r.slug, r.rtds_winner, r.outcome, anchor, p))
    K = pd.DataFrame(keep, columns=["asset", "slug", "winner", "outcome", "anchor", "print_p"])
    # fill test
    cfg = LiveMimicConfig(notional_usd=stake) if hasattr(LiveMimicConfig(), "notional_usd") else LiveMimicConfig()
    fr = []
    for a in ASSETS:
        ka = K[K.asset == a]
        if not len(ka): continue
        slugs = list(ka.slug); B = 250
        for i in range(0, len(slugs), B):
            chunk = set(slugs[i:i+B])
            books = load_orderbook_l25_streaming(a.lower(), slugs=chunk, subsample_1hz=False)
            for _, r in ka[ka.slug.isin(chunk)].iterrows():
                f = fill_at_book(books, r.slug, r.winner, int(r.anchor), cfg=cfg, side="buy",
                                 spread_filter=0.05, notional_usd=stake)
                won = (r.winner == r.outcome)
                if f is None: fr.append(dict(filled=0, pnl=np.nan, vwap=np.nan, won=won, print_p=r.print_p)); continue
                fr.append(dict(filled=1, pnl=hold_pnl(f, won=won, cfg=cfg), vwap=f["vwap"], won=won, print_p=r.print_p))
            del books
    FR = pd.DataFrame(fr); ff = FR[FR.filled == 1]
    print(f"\n=== T-{X}s, stake=${stake}, poly_winner_print<{pmax} ===")
    print(f"  cheap-decided slugs: {len(K)}  (asset mix {K.asset.value_counts().to_dict()})  mean_print_p={K.print_p.mean():.3f}")
    print(f"  fill_rate={FR.filled.mean():.2f}  filled n={len(ff)}  mean_fill_vwap={ff.vwap.mean():.3f}" if len(ff) else f"  fill_rate={FR.filled.mean():.2f} (no fills)")
    if len(ff) >= 8:
        lo, hi = boot(ff.pnl.values)
        per = ff.pnl.mean(); per_sh = per / stake
        print(f"  FILLED hold-to-settle: $/tr={per:+.4f} (${stake} stake, ={per_sh:+.4f}/share) won={ff.won.mean():.3f} CI=[{lo:+.3f},{hi:+.3f}]")
print("\nREAD: real narrow edge needs cheap-decided slugs to FILL (rate non-trivial) AND $/tr>0 with CI>0.")
