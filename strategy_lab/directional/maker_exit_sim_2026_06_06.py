"""
MAKER-EXIT with taker-+60 fallback — does a maker sell beat the pure-taker +60 exit on the scalp?
Exit-side selection is FAVORABLE (a resting SELL fills when a BUYER lifts it = when the token repriced UP =
position winning). Maker sell pays $0 taker fee + earns rebate; if unfilled by +60, taker-cross the bid (baseline).

Compare 3 exits on the confirmed gated scalp (BTC/ETH, entry_vwap<0.55):
  (1) PURE TAKER +60  : sell at bid_60, pay taker sell fee  [the validated optimum]
  (2) TAKER TP@target : sell at target when bid first hits it, else bid_60; taker fee  [current live, suspect]
  (3) MAKER TP@target + taker +60 fallback : rest sell at target; fill if a BUY trade >= target in [fire,fire+60]
      -> sell at target, $0 fee, + rebate; else taker bid_60.  [NEW]
Fees: taker sell = 0.07*p*(1-p)/sh ; maker rebate = 0.20*0.07*p*(1-p)/sh. Judge: bootstrap CI + ml4t DSR.
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics
CANON = ROOT / "data/v4/canonical"

c = pd.read_parquet(ROOT / "strategy_lab/directional/_results/scalp_hedge_physics_cache_2026_06_03.parquet")
c = c[(c.asset.isin(["BTC", "ETH"])) & (c.filled == 1) & (c.entry_vwap < 0.55)].copy()
# need direction(lead) per fire: derive from the lag-taker fires parquet (has direction) by slug
lf = pd.read_parquet(ROOT / "strategy_lab/lag_taker_fires_oos_2026_06_01.parquet")[["slug", "direction"]].drop_duplicates("slug")
c = c.merge(lf, on="slug", how="left").dropna(subset=["direction"])
print(f"gated scalp fires (BTC/ETH, vwap<0.55) w/ direction: {len(c)}")

tk = lambda p: 0.07 * p * (1 - p)            # taker fee per share
reb = lambda p: 0.20 * 0.07 * p * (1 - p)    # maker rebate per share

# buy-trade tape per (slug, outcome) for maker-fill detection
recs = []
for a in ["btc", "eth"]:
    ca = c[c.asset == a.upper()]
    t = pd.read_parquet(CANON / "trades_polymarket" / f"{a}.parquet",
                        columns=["slug", "outcome", "timestamp_us", "price", "side"],
                        filters=[("slug", "in", set(ca.slug)), ("side", "in", {"buy", "BUY"})])
    t = t.sort_values("timestamp_us")
    g = {k: (v.timestamp_us.values, v.price.values) for k, v in t.groupby(["slug", "outcome"])}
    for _, r in ca.iterrows():
        ev, sh = r.entry_vwap, r.shares; lead = r.direction
        b60 = pd.to_numeric(pd.Series([r.bid_60]), errors="coerce").iloc[0]
        b60 = float(b60) if np.isfinite(b60) else (1.0 if r.won else 0.0)   # fallback if no book
        fire = int(r.fire_us)
        ts_px = g.get((r.slug, lead))
        rec = dict(asset=a.upper(), slug=r.slug, ev=ev, sh=sh, won=bool(r.won), b60=b60)
        # (1) pure taker +60
        rec["taker60"] = (b60 - ev) * sh - tk(b60) * sh
        for tgt in [0.58, 0.60, 0.62, 0.65]:
            # (3) maker fill: first BUY trade >= tgt in [fire, fire+60]
            mk = np.nan
            if ts_px is not None:
                tt, pp = ts_px; lo = np.searchsorted(tt, fire, "right"); hi = np.searchsorted(tt, fire + 60_000_000, "right")
                seg = pp[lo:hi]; hit = np.where(seg >= tgt - 1e-9)[0]
                if len(hit): mk = tgt
            if np.isfinite(mk):
                rec[f"maker_{round(tgt*100)}"] = (mk - ev) * sh + reb(mk) * sh   # maker fill: no fee + rebate
            else:
                rec[f"maker_{round(tgt*100)}"] = (b60 - ev) * sh - tk(b60) * sh   # fallback = taker60
            # (2) taker TP: if bid hit tgt (use tp_hit_*_dt proxy ~ bid>=tgt) -> sell tgt taker; else bid_60
            # approximate "bid hit tgt" via the cache tp_hit columns (bid path); use bid_60>=tgt OR tp_hit
            hitcol = {0.60:"tp_hit_60_dt",0.65:"tp_hit_65_dt",0.70:"tp_hit_70_dt",0.75:"tp_hit_75_dt"}.get(tgt)
            taker_tp = (b60 - ev) * sh - tk(b60) * sh
            if hitcol and hitcol in r.index and np.isfinite(pd.to_numeric(pd.Series([r[hitcol]]),errors="coerce").iloc[0]):
                taker_tp = (tgt - ev) * sh - tk(tgt) * sh
            rec[f"takerTP_{round(tgt*100)}"] = taker_tp
        recs.append(rec)
D = pd.DataFrame(recs)
D.to_parquet(ROOT / "strategy_lab/directional/_results/maker_exit_sim_2026_06_06.parquet")

def boot(v, nb=5000):
    v=np.asarray(v); i=np.random.randint(0,len(v),(nb,len(v))); return tuple(np.percentile(v[i].mean(1),[2.5,97.5]))
def show(col, label):
    v = D[col].dropna().values
    t = v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std()>0 else np.nan; lo,hi=boot(v)
    print(f"  {label:28s} n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]")
    return v
print(f"\n=== EXIT POLICY COMPARISON (gated scalp, n={len(D)}) ===")
base = show("taker60", "(1) PURE TAKER +60 [optimum]")
print("  --- maker-TP + taker fallback (NEW) ---")
for tgt in [58,60,62,65]: show(f"maker_{tgt}", f"(3) MAKER TP@0.{tgt}+fallback")
print("  --- taker-TP (current live style) ---")
for tgt in [60,65]: show(f"takerTP_{tgt}", f"(2) TAKER TP@0.{tgt}")
# paired: best maker vs pure taker
print("\n=== PAIRED diff: best maker-exit vs pure-taker +60 ===")
for tgt in [58,60,62,65]:
    d = (D[f"maker_{tgt}"] - D["taker60"]).dropna().values
    lo,hi=boot(d); sig = "SIG+" if lo>0 else ("SIG-" if hi<0 else "ns")
    print(f"  maker@0.{tgt} - taker60: mean={d.mean():+.4f} CI=[{lo:+.4f},{hi:+.4f}] {sig}")
print("\nREAD: maker-exit wins only if (3) > (1) with paired CI>0. Caveat: maker fill = first buy-trade>=target")
print("(ignores queue position -> optimistic); fixed-target still caps runners (peg-to-ask/trail is the real impl).")
