"""
build_enriched_physics.py — add L25 entry price + real-fee PnL + d_speed to the
physics fires, so we can test the EDGE (physics-WR vs token-implied prob = the gap),
not just WR. Heavy step (L25); run once, then cheap experiments read the output.

Output: strategy_lab/physics/_results/physics_fires_enriched.parquet
Run: C:/Python314/python.exe strategy_lab/physics/build_enriched_physics.py
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "physics"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT))
from load import load_chainlink_asof, load_orderbook_l25_streaming  # noqa
from physics_signal import physics_at  # noqa
from strategy_lab.engine_v2 import LiveMimicConfig, LegacyConfig, fill_at_book, hold_pnl  # noqa

OUT = ROOT / "strategy_lab" / "physics" / "_results"
WIN = {"5m": 300, "15m": 900}
HAVE_S = 60
BATCH = 1500


def main():
    print("loading physics_fires_btc.parquet ...", flush=True)
    df = pd.read_parquet(OUT / "physics_fires_btc.parquet")
    print(f"  {len(df)} fires loaded", flush=True)
    df["slot_end_us"] = df.apply(lambda r: int(r.slot_start_us) + WIN[r.tf] * 1_000_000, axis=1)
    df["fire_us"] = df["slot_end_us"] - HAVE_S * 1_000_000

    # d_speed: speed(now) - speed(30s earlier). 'speed' col already = speed over [fire-60,fire].
    cl_ts, cl_px = load_chainlink_asof("BTC")
    cl_ts = np.asarray(cl_ts, np.int64); cl_px = np.asarray(cl_px, float)
    dsp = []
    for r in df.itertuples(index=False):
        f30 = physics_at(cl_ts, cl_px, 0.0, int(r.fire_us) - 30_000_000, int(r.slot_end_us), 60)
        dsp.append((r.speed - f30["speed"]) if f30 else np.nan)
    df["d_speed"] = dsp   # >0 accelerating, <0 inertia fading
    print("d_speed computed; starting L25 entry overlay ...", flush=True)

    live = LiveMimicConfig(); leg = LegacyConfig()
    entry_vwap = np.full(len(df), np.nan); ask0 = entry_vwap.copy(); bid0 = entry_vwap.copy()
    pnl_curve = entry_vwap.copy(); pnl_legacy = entry_vwap.copy(); valid = np.zeros(len(df), bool)

    import gc
    idx_by_slug = {s: df.index[df.slug == s].tolist() for s in df.slug.unique()}
    # ONE loader call per timeframe (the full-file rescan is the memory hog; minimize calls).
    for tf in ["5m", "15m"]:
        sub = df[df.tf == tf]
        slugs = set(sub.slug)
        tlo = int(sub.fire_us.min()) - 5_000_000
        thi = int(sub.fire_us.max()) + 2_000_000
        print(f"  [{tf}] loading L25 for {len(slugs)} slugs ...", flush=True)
        books = load_orderbook_l25_streaming("btc", slugs=slugs, subsample_1hz=True,
                                             min_ts_us=tlo, max_ts_us=thi)
        for s in slugs:
            for ridx in idx_by_slug[s]:
                r = df.loc[ridx]
                fill = fill_at_book(books, s, r.bet, int(r.fire_us), cfg=live,
                                    spread_filter=None, notional_usd=25.0)
                if fill is None:
                    continue
                won = bool(r.won)
                entry_vwap[ridx] = fill["vwap"]; ask0[ridx] = fill["ask0"]; bid0[ridx] = fill["bid0"]
                pnl_curve[ridx] = hold_pnl(fill, won=won, cfg=live)
                pnl_legacy[ridx] = hold_pnl(fill, won=won, cfg=leg)
                valid[ridx] = True
        print(f"  [{tf}] done; cum_valid={valid.sum()}", flush=True)
        del books; gc.collect()

    df["entry_vwap"] = entry_vwap; df["ask0"] = ask0; df["bid0"] = bid0
    df["spread"] = ask0 - bid0
    df["pnl_curve"] = pnl_curve; df["pnl_legacy"] = pnl_legacy; df["valid"] = valid
    df["implied"] = entry_vwap          # token price ~ market-implied P(bet wins)
    df.to_parquet(OUT / "physics_fires_enriched.parquet", index=False)

    v = df[df.valid].copy()
    print(f"\n=== ENRICHED: {len(df)} fires, {len(v)} valid L25 fills ({100*len(v)/len(df):.0f}%) ===")
    print(f"  realized WR={100*v.won.mean():.1f}%  mean implied(entry_vwap)={v.implied.mean():.3f}  "
          f"GAP(WR-implied)={100*(v.won.mean()-v.implied.mean()):+.1f}pp")
    print(f"  net PnL/fire  curve={v.pnl_curve.mean():+.4f}  legacy={v.pnl_legacy.mean():+.4f}  (n={len(v)})")
    # WEAK_COMBO kept set (dist<30 & speed_away<10 => SKIP)
    kept = v[~((v.dist_abs < 30) & (v.speed_away < 10))]
    print(f"  WEAK_COMBO kept (n={len(kept)}, {100*len(kept)/len(v):.0f}%): WR={100*kept.won.mean():.1f}%  "
          f"implied={kept.implied.mean():.3f}  gap={100*(kept.won.mean()-kept.implied.mean()):+.1f}pp  "
          f"net curve={kept.pnl_curve.mean():+.4f}  legacy={kept.pnl_legacy.mean():+.4f}")
    print(f"\nwrote {OUT/'physics_fires_enriched.parquet'}")


if __name__ == "__main__":
    main()
