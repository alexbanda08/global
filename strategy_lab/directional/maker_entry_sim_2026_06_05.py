"""
Maker-ENTRY simulation for the exit-scalp — rebate + spread capture vs adverse selection.

Current scalp TAKES the ask at fire (entry_vwap). Maker variant: rest a BUY limit at the best BID at fire
(join the bid → capture the spread + earn the 0.20*0.07*p(1-p) rebate). Risk = ADVERSE SELECTION: a resting
buy fills only when someone SELLS into it (price moving AGAINST our 'token reprices up' thesis) → we may fill
preferentially on LOSERS and miss the winners (the whole edge).

Fill model (trade-tape, the honest test): a resting BUY at price L on the lead token fills iff a SELL trade
on that (slug, outcome) occurs at price <= L within (fire_us, fire_us+WAIT]. (Optimistic: ignores queue
position → upper bound on maker fill rate.) On non-fill: (a) SKIP, or (b) TAKER fallback at deadline.

Compare per-fire net (maker entry @bid + rebate, exit +60 book-sell) vs taker baseline (entry @ask, exit +60).
Adverse selection = fill rate / $/tr split by eventual won vs lost.
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical")); sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_orderbook_l25_streaming
from engine_v2 import LiveMimicConfig, fill_at_book, sell_pnl_partial
from fees import poly_maker_rebate_per_share
np.random.seed(0)
cfg = LiveMimicConfig()
WAIT_US = 60_000_000          # rest the maker order for up to 60s
FEE_RATE = 0.07; REBATE_SHARE = 0.20
NOTIONAL = 25.0

def load_fires():
    parts = []
    p = ROOT / "strategy_lab/lag_taker_fires_oos_2026_06_01.parquet"
    f = pd.read_parquet(p)
    f = f[f.asset.isin(["BTC", "ETH"])][["slug", "asset", "tf", "fire_us", "direction", "entry_vwap", "won", "delta_bps"]]
    parts.append(f.rename(columns={"direction": "lead"}))
    sp = ROOT / "strategy_lab/directional/_results/sol_scalp_fires_2026_06_05.parquet"
    if sp.exists():
        s = pd.read_parquet(sp)
        s = s[s.filled == 1]
        # sol parquet lacks lead/fire_us in same shape -> skip if columns missing
        if {"slug", "entry_vwap", "won"}.issubset(s.columns) and "fire_us" in s.columns:
            parts.append(s.assign(asset="SOL")[["slug", "asset", "tf", "fire_us", "entry_vwap", "won", "delta_bps"]].assign(lead=None))
    return pd.concat(parts, ignore_index=True)

CANON = ROOT / "data/v4/canonical"
def sell_trades_index(asset, fire_slugs):
    """Memory-safe: pushdown to SELL trades on the fire slugs only."""
    flt = [("side", "in", {"sell", "SELL"}), ("slug", "in", set(fire_slugs))]
    t = pd.read_parquet(CANON / "trades_polymarket" / f"{asset.lower()}.parquet",
                        columns=["slug", "outcome", "timestamp_us", "price", "side"], filters=flt)
    t = t.sort_values("timestamp_us")
    return {k: (g.timestamp_us.values, g.price.values) for k, g in t.groupby(["slug", "outcome"])}

def maker_fills_for(fire_us, L, ts, px):
    """First SELL at price<=L in (fire_us, fire_us+WAIT]. Returns fill_ts or None."""
    lo = np.searchsorted(ts, fire_us, "right"); hi = np.searchsorted(ts, fire_us + WAIT_US, "right")
    if hi <= lo: return None
    seg = px[lo:hi]
    m = np.where(seg <= L + 1e-9)[0]
    return int(ts[lo + m[0]]) if len(m) else None

F = load_fires()
print(f"fire universe: {len(F)}  {F.asset.value_counts().to_dict()}")
recs = []
for asset in ["BTC", "ETH", "SOL"]:
    fa = F[F.asset == asset]
    if not len(fa): continue
    print(f"\n[{asset}] {len(fa)} fires — indexing SELL trades + L25 ...", flush=True)
    sidx = sell_trades_index(asset, set(fa.slug))
    slugs_all = fa.slug.tolist()
    B = 250
    for i in range(0, len(slugs_all), B):
        chunk = set(slugs_all[i:i + B])
        books = load_orderbook_l25_streaming(asset.lower(), slugs=chunk, subsample_1hz=False)
        for _, r in fa[fa.slug.isin(chunk)].iterrows():
            lead = r.lead
            tk = fill_at_book(books, r.slug, lead, int(r.fire_us), cfg=cfg, side="buy",
                              spread_filter=0.05, notional_usd=NOTIONAL) if lead else None
            if tk is None: continue
            bid0, ask0 = tk["bid0"], tk["ask0"]
            taker_vwap = tk["vwap"]
            L = bid0                                   # passive: join best bid
            ts_px = sidx.get((r.slug, lead))
            fill_ts = maker_fills_for(int(r.fire_us), L, *ts_px) if ts_px else None
            # taker baseline exit +60
            tk_exit = sell_pnl_partial(tk, books, r.slug, lead, int(r.fire_us) + 60_000_000, cfg=cfg)
            # maker net (if filled): entry @L, exit +60 book-sell, + rebate
            maker_net = np.nan
            if fill_ts is not None:
                sh = NOTIONAL / L if L > 0 else 0
                mk_fill = {"vwap": L, "shares": sh, "usd": NOTIONAL, "fee_in": 0.0,
                           "ts_us": fill_ts, "ask0": ask0, "bid0": bid0}
                ex = sell_pnl_partial(mk_fill, books, r.slug, lead, fill_ts + 60_000_000, cfg=cfg)
                if ex is not None:
                    reb = poly_maker_rebate_per_share(L, FEE_RATE, REBATE_SHARE) * sh
                    maker_net = ex + reb
            recs.append(dict(asset=asset, slug=r.slug, won=bool(r.won), entry_vwap=taker_vwap,
                             bid0=bid0, ask0=ask0, spread=ask0 - bid0, filled=int(fill_ts is not None),
                             taker_exit60=tk_exit, maker_net=maker_net))
        del books
R = pd.DataFrame(recs)
R.to_parquet(ROOT / "strategy_lab/directional/_results/maker_entry_sim_2026_06_05.parquet")
print(f"\nevaluated {len(R)} fires; mean cross-token... spread mean={R.spread.mean():.3f}")

def boot(v, nb=5000):
    if len(v) < 5: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))

print("\n================ MAKER-ENTRY vs TAKER ================")
for asset in ["ALL", "BTC", "ETH", "SOL"]:
    d = R if asset == "ALL" else R[R.asset == asset]
    if len(d) < 10: continue
    fr = d.filled.mean()
    # adverse selection: fill rate by outcome
    fr_won = d[d.won].filled.mean(); fr_lost = d[~d.won].filled.mean()
    tk = d.taker_exit60.dropna()
    mk = d[d.filled == 1].maker_net.dropna()
    print(f"\n[{asset}] n={len(d)} maker fill_rate={fr:.2f} (won {fr_won:.2f} / lost {fr_lost:.2f})")
    print(f"  TAKER  exit+60: n={len(tk):4d} $/tr={tk.mean():+.4f} CI={tuple(round(x,3) for x in boot(tk.values))}")
    if len(mk) >= 5:
        print(f"  MAKER  (filled): n={len(mk):4d} $/tr={mk.mean():+.4f} CI={tuple(round(x,3) for x in boot(mk.values))}")
        # like-for-like: taker on the SAME fires that maker filled
        tk_same = d[(d.filled == 1)].taker_exit60.dropna()
        print(f"  TAKER  (same fills): n={len(tk_same):4d} $/tr={tk_same.mean():+.4f}")
        # maker w/ taker fallback on non-fills
        fb = d.copy()
        fb["net"] = np.where(fb.filled == 1, fb.maker_net, fb.taker_exit60)
        v = fb.net.dropna().values
        print(f"  MAKER+taker-fallback: n={len(v):4d} $/tr={v.mean():+.4f} CI={tuple(round(x,3) for x in boot(v))}")
print("\nREAD: maker wins only if MAKER(filled) $/tr >= TAKER(same fills) (spread+rebate beat adverse selection)")
print("      AND fill_rate is usable AND not heavily skewed to losers (fr_lost >> fr_won = adverse).")
