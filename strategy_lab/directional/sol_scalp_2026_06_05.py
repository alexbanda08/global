"""
SOL exit-scalp — replicate the confirmed BTC/ETH lag-taker scalp on SOL.

Lag = |SOL binance-1s 5s return| at slot_start; fire @ slot_start+5s; lead = sign(ret).
Entry = $25 taker ask-walk (engine_v2 fill_at_book, 85ms, spread<=0.05, min_book_events>=25).
Exit  = SELL the lead token on the book at +45s and +60s (sell_pnl_partial). Gate: entry_vwap<0.55.
Question: (a) can a $25 SOL scalp even FILL (SOL books are thin), and (b) does the gated edge hold like BTC/ETH?
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical")); sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_resolutions, load_orderbook_l25_streaming
from engine_v2 import LiveMimicConfig, fill_at_book, sell_pnl_partial
np.random.seed(0)
CANON = ROOT / "data/v4/canonical"
cfg = LiveMimicConfig()
SPREAD = 0.05; NOTIONAL = 25.0; TFS = ["5m", "15m"]

def unified_binance_1s(asset):
    sym = f"BINANCE_SPOT_{asset.upper()}_USDT"
    df = pd.read_parquet(
        CANON / "klines_1s.parquet",
        columns=["symbol_id", "period_id", "source", "time_period_start_us", "price_close"],
        filters=[("symbol_id", "==", sym), ("period_id", "==", "1SEC")],
    )
    df = df[df.source.isin(["binance-vision", "binance-spot-ws"])]
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)

def asof(ts, v, t):
    i = np.searchsorted(ts, t, side="right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)

be, bc = unified_binance_1s("SOL")
print(f"SOL 1s: {pd.Timestamp(int(be.min()),unit='us',tz='UTC')} -> {pd.Timestamp(int(be.max()),unit='us',tz='UTC')} n={len(be)}")
res = load_resolutions(assets=["SOL"], timeframes=TFS)
res = res[res.outcome.isin(["Up", "Down"])].copy()
print(f"SOL resolved slugs: {len(res)}")

# candidate fires (delta>=3)
ss = res.slot_start_us.values // 1_000_000
fire = (ss + 5) * 1_000_000
px_open = asof(be, bc, ss * 1_000_000); px_fire = asof(be, bc, fire)
ret = px_fire / px_open - 1.0
res = res.assign(ss=ss, fire_us=fire, ret=ret, delta_bps=np.abs(ret) * 1e4,
                 lead=np.where(ret > 0, "Up", "Down"))
res = res[np.isfinite(res.ret) & (res.delta_bps >= 3.0)].reset_index(drop=True)
print(f"SOL candidate fires (delta>=3, valid 1s): {len(res)}")

recs = []
slugs_all = res.slug.tolist()
B = 250
for i in range(0, len(slugs_all), B):
    chunk = set(slugs_all[i:i + B])
    books = load_orderbook_l25_streaming("sol", slugs=chunk, subsample_1hz=False)
    sub = res[res.slug.isin(chunk)]
    for _, r in sub.iterrows():
        won = (r.ret > 0) == (r.outcome == "Up")
        fill = fill_at_book(books, r.slug, r.lead, int(r.fire_us), cfg=cfg, side="buy",
                            spread_filter=SPREAD, notional_usd=NOTIONAL)
        if fill is None:
            recs.append(dict(slug=r.slug, tf=r.timeframe, fire_us=int(r.fire_us), lead=r.lead,
                             delta_bps=r.delta_bps, filled=0,
                             entry_vwap=np.nan, won=won, pnl45=np.nan, pnl60=np.nan)); continue
        ev = fill["vwap"]
        p45 = sell_pnl_partial(fill, books, r.slug, r.lead, int(r.fire_us) + 45_000_000, cfg=cfg)
        p60 = sell_pnl_partial(fill, books, r.slug, r.lead, int(r.fire_us) + 60_000_000, cfg=cfg)
        recs.append(dict(slug=r.slug, tf=r.timeframe, fire_us=int(r.fire_us), lead=r.lead,
                         delta_bps=r.delta_bps, filled=1,
                         entry_vwap=ev, won=won, pnl45=p45, pnl60=p60))
    del books
F = pd.DataFrame(recs)
F.to_parquet(ROOT / "strategy_lab/directional/_results/sol_scalp_fires_2026_06_05.parquet")
nf = int(F.filled.sum())
print(f"\nfill rate: {nf}/{len(F)} = {nf/len(F):.1%}  (SOL book liquidity gate)")
Ff = F[(F.filled == 1) & F.pnl60.notna()].copy()
print(f"filled w/ exit: {len(Ff)}  entry_vwap mean={Ff.entry_vwap.mean():.3f}")

def boot(v, nb=5000):
    if len(v) < 5: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))
def summ(d, name, col):
    v = d[col].dropna().values
    if len(v) < 5: print(f"  {name:30s} n={len(v):4d} (few)"); return
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan
    lo, hi = boot(v)
    print(f"  {name:30s} n={len(v):4d} $/tr={v.mean():+.4f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] won={d.won.mean():.3f}")

for col in ["pnl45", "pnl60"]:
    print(f"\n=== exit {col} ===")
    summ(Ff, "ALL filled (control)", col)
    summ(Ff[Ff.entry_vwap < 0.55], "GATED vwap<0.55", col)
    summ(Ff[(Ff.entry_vwap < 0.55) & (Ff.delta_bps >= 5)], "GATED vwap<0.55 & d>=5", col)
print("\nREAD: SOL scalp viable only if (a) fill rate non-trivial AND (b) gated $/tr>0 with CI>0 like BTC/ETH.")
