"""
build_eth_physics_14d.py — ETH physics enrichment, last 14 days only.
Mirrors build_enriched_physics.py but for ETH 5m+15m, restricted window.
Output: strategy_lab/physics/_results/physics_fires_eth_14d.parquet
Run: C:/Python314/python.exe strategy_lab/physics/build_eth_physics_14d.py
"""
from __future__ import annotations
import sys
import gc
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "physics"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT))

from load import load_resolutions, load_chainlink_asof, load_orderbook_l25_streaming  # noqa
from physics_signal import physics_at  # noqa
from engine_v2 import LiveMimicConfig, LegacyConfig, fill_at_book, hold_pnl  # noqa

OUT = ROOT / "strategy_lab" / "physics" / "_results"
WIN = {"5m": 300, "15m": 900}
HAVE_S = 60  # fire = slot_end - 60s
ASSET = "ETH"
ASSET_LOWER = "eth"
N_DAYS = 14

# ── 1. Load resolutions ──────────────────────────────────────────────────────
print("Loading ETH resolutions ...", flush=True)
res = load_resolutions(assets=[ASSET], timeframes=["5m", "15m"])
print(f"  total rows: {len(res)}", flush=True)

# Filter to last 14 days
now_us = int(pd.Timestamp.utcnow().timestamp() * 1_000_000)
cutoff_us = now_us - N_DAYS * 86_400 * 1_000_000
res = res[res["slot_start_us"] >= cutoff_us].copy()
print(f"  after 14d filter: {len(res)} rows", flush=True)
print(f"  date range: {pd.to_datetime(res.slot_start_us.min(), unit='us').strftime('%Y-%m-%d')} "
      f"to {pd.to_datetime(res.slot_start_us.max(), unit='us').strftime('%Y-%m-%d')}", flush=True)

# slot_end_us is already present in the resolutions schema
# fire_us = slot_end - 60s
res["fire_us"] = res["slot_end_us"] - HAVE_S * 1_000_000

# ── 2. Load Chainlink ETH prices ─────────────────────────────────────────────
print("Loading Chainlink ETH prices ...", flush=True)
cl_ts, cl_px = load_chainlink_asof(ASSET)
cl_ts = np.asarray(cl_ts, np.int64)
cl_px = np.asarray(cl_px, float)
print(f"  chainlink rows: {len(cl_ts)}", flush=True)

# ── 3. Compute physics features for each fire ────────────────────────────────
print("Computing physics features ...", flush=True)
rows = []
for r in res.itertuples(index=False):
    strike = float(r.strike_price)
    feat = physics_at(cl_ts, cl_px, strike, int(r.fire_us), int(r.slot_end_us), speed_win_s=60)
    if feat is None:
        continue

    # d_speed: speed(now) - speed(30s earlier)
    f30 = physics_at(cl_ts, cl_px, strike, int(r.fire_us) - 30_000_000, int(r.slot_end_us), speed_win_s=60)
    d_speed = (feat["speed"] - f30["speed"]) if f30 is not None else np.nan

    bet = feat["bet"]
    outcome = str(r.outcome)  # 'Up' or 'Down'
    won = 1 if outcome == bet else 0

    rows.append(dict(
        slug=r.slug,
        tf=r.timeframe,
        slot_start_us=int(r.slot_start_us),
        slot_end_us=int(r.slot_end_us),
        fire_us=int(r.fire_us),
        outcome=outcome,
        bet=bet,
        won=won,
        strike=strike,
        dist=feat["dist"],
        dist_abs=feat["dist_abs"],
        side=feat["side"],
        speed=feat["speed"],
        speed_abs=feat["speed_abs"],
        speed_away=feat["speed_away"],
        cross=feat["cross"],
        have_m=feat["have_m"],
        margin=feat["margin"],
        d_speed=d_speed,
    ))

df = pd.DataFrame(rows)
print(f"  physics computed: {len(df)} fires", flush=True)
print(f"  base WR (no fill filter): {100*df.won.mean():.1f}%", flush=True)

# ── 4. L25 entry overlay ─────────────────────────────────────────────────────
live = LiveMimicConfig()
leg = LegacyConfig()
entry_vwap = np.full(len(df), np.nan)
ask0 = entry_vwap.copy()
bid0 = entry_vwap.copy()
pnl_curve = entry_vwap.copy()
pnl_legacy = entry_vwap.copy()
valid = np.zeros(len(df), bool)

# Build slug->row index map
df = df.reset_index(drop=True)
idx_by_slug = {}
for i, row in df.iterrows():
    idx_by_slug.setdefault(row["slug"], []).append(i)

for tf in ["5m", "15m"]:
    sub = df[df["tf"] == tf]
    if len(sub) == 0:
        continue
    slugs = set(sub.slug)
    tlo = int(sub.fire_us.min()) - 5_000_000
    thi = int(sub.fire_us.max()) + 2_000_000
    print(f"  [{tf}] loading ETH L25 for {len(slugs)} slugs, "
          f"{pd.to_datetime(tlo, unit='us').strftime('%m-%d')} to "
          f"{pd.to_datetime(thi, unit='us').strftime('%m-%d')} ...", flush=True)
    books = load_orderbook_l25_streaming(
        ASSET_LOWER, slugs=slugs, subsample_1hz=True,
        min_ts_us=tlo, max_ts_us=thi
    )
    filled = 0
    for s in slugs:
        if s not in idx_by_slug:
            continue
        for ridx in idx_by_slug[s]:
            r = df.loc[ridx]
            fill = fill_at_book(
                books, s, r.bet, int(r.fire_us),
                cfg=live, spread_filter=None, notional_usd=25.0
            )
            if fill is None:
                continue
            won = bool(r.won)
            entry_vwap[ridx] = fill["vwap"]
            ask0[ridx] = fill["ask0"]
            bid0[ridx] = fill["bid0"]
            pnl_curve[ridx] = hold_pnl(fill, won=won, cfg=live)
            pnl_legacy[ridx] = hold_pnl(fill, won=won, cfg=leg)
            valid[ridx] = True
            filled += 1
    print(f"  [{tf}] done; filled={filled}", flush=True)
    del books
    gc.collect()

df["entry_vwap"] = entry_vwap
df["ask0"] = ask0
df["bid0"] = bid0
df["spread"] = ask0 - bid0
df["pnl_curve"] = pnl_curve
df["pnl_legacy"] = pnl_legacy
df["valid"] = valid
df["implied"] = entry_vwap

df.to_parquet(OUT / "physics_fires_eth_14d.parquet", index=False)
print(f"\nWrote {len(df)} rows to {OUT / 'physics_fires_eth_14d.parquet'}", flush=True)

# ── 5. Summary stats ─────────────────────────────────────────────────────────
v = df[df.valid].copy()
print(f"\n=== ETH PHYSICS ENRICHED (last 14d) ===")
print(f"  total fires={len(df)}  valid L25 fills={len(v)} ({100*len(v)/len(df):.0f}%)")
print(f"  WR={100*v.won.mean():.1f}%  implied={v.implied.mean():.3f}  "
      f"GAP={100*(v.won.mean()-v.implied.mean()):+.1f}pp  n={len(v)}")
print(f"  net PnL/fire: curve={v.pnl_curve.mean():+.4f}  legacy={v.pnl_legacy.mean():+.4f}")

# dist_abs >= 40
d40 = v[v.dist_abs >= 40]
if len(d40) > 0:
    print(f"  dist_abs>=40: WR={100*d40.won.mean():.1f}%  implied={d40.implied.mean():.3f}  "
          f"gap={100*(d40.won.mean()-d40.implied.mean()):+.1f}pp  "
          f"curve={d40.pnl_curve.mean():+.4f}  legacy={d40.pnl_legacy.mean():+.4f}  n={len(d40)}")

# WEAK_COMBO kept (dist_abs>=30 OR speed_away>=10)
kept = v[~((v.dist_abs < 30) & (v.speed_away < 10))]
if len(kept) > 0:
    print(f"  WEAK_COMBO kept: WR={100*kept.won.mean():.1f}%  implied={kept.implied.mean():.3f}  "
          f"gap={100*(kept.won.mean()-kept.implied.mean()):+.1f}pp  "
          f"curve={kept.pnl_curve.mean():+.4f}  legacy={kept.pnl_legacy.mean():+.4f}  n={len(kept)}")

# WEAK_COMBO kept + d_speed >= 0
kd = kept[kept.d_speed >= 0]
if len(kd) > 0:
    print(f"  + d_speed>=0: WR={100*kd.won.mean():.1f}%  implied={kd.implied.mean():.3f}  "
          f"gap={100*(kd.won.mean()-kd.implied.mean()):+.1f}pp  "
          f"curve={kd.pnl_curve.mean():+.4f}  legacy={kd.pnl_legacy.mean():+.4f}  n={len(kd)}")

# WEAK_COMBO kept + d_speed>=0 + entry_vwap<=0.85
ke = kd[kd.entry_vwap <= 0.85]
if len(ke) > 0:
    print(f"  + entry_vwap<=0.85: WR={100*ke.won.mean():.1f}%  implied={ke.implied.mean():.3f}  "
          f"gap={100*(ke.won.mean()-ke.implied.mean()):+.1f}pp  "
          f"curve={ke.pnl_curve.mean():+.4f}  legacy={ke.pnl_legacy.mean():+.4f}  n={len(ke)}")

print("\nDone.", flush=True)
