"""
Strategy I -- Binance-only momentum baseline (robustness benchmark).

Hypothesis: with no L25 / no HL / just binance OHLCV -- is there ANY edge?

For each market: signal = sign of binance return over the previous full window,
anchored on the production ws_s (NOT slot_start -- the lookahead footgun).

Two sweeps:
  A. EARLY (production-mimic): observation = [ws_s, ws_s+window]
     -- this is the LAST FULL window BEFORE the prediction window.
  B. LATE-15m: enter at slot_end - 60s; observation = [slot_start, entry_us]
     -- elapsed momentum.

Sweep return-threshold in bp: {0, 5, 10, 20, 50}. Higher = fewer fires.

Anchor: ws_s. Outcome = chainlink. Fee = 2% on profit only.
Notional: $25 flat at fixed entry_price=0.5 (we have NO book here; this is the
robustness baseline, so we use the no-book PnL convention).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "discovery_2026_05_16"))

from load import (  # type: ignore
    load_resolutions, load_klines_asof, load_binance_vision_klines, asof_strict,
    slug_to_ws_s,
)
from harness import hold_pnl_no_book  # type: ignore

OUT = ROOT / "strategy_lab" / "discovery_2026_05_16"
OUT.mkdir(parents=True, exist_ok=True)


def build_kline_arrays_live(asset: str):
    """1MIN live binance-spot-ws end_us + close array via load_klines_asof."""
    end_us, prices = load_klines_asof(asset.upper(), "binance-spot-ws", "1MIN")
    return end_us, prices


def build_kline_arrays_vision(asset: str):
    """1MIN binance-vision end_us + close. Used only as backup when live cache misses."""
    bv = load_binance_vision_klines(asset.upper(), "1MIN")
    end_us = bv.time_period_end_us.values.astype(np.int64) + 1   # asof_strict expects end_us of bar
    prices = bv.price_close.values.astype(float)
    return end_us, prices


def fused_lookup(t_us: int, e_live, p_live, e_vis, p_vis) -> float:
    """Prefer live cache; fall back to vision if outside live range."""
    p = asof_strict(e_live, p_live, t_us) if e_live is not None and len(e_live) else float("nan")
    if np.isfinite(p):
        return p
    return asof_strict(e_vis, p_vis, t_us) if e_vis is not None and len(e_vis) else float("nan")


def compute_returns(res: pd.DataFrame) -> pd.DataFrame:
    """Compute early (ws_s window) and late-15m returns per row."""
    out = res.copy().reset_index(drop=True)
    out["ret_early"] = np.nan
    out["ret_late15"] = np.nan  # only for 15m markets
    out["p_ws"] = np.nan
    out["p_ws_plus_window"] = np.nan
    out["p_slotstart"] = np.nan
    out["p_entry_late"] = np.nan

    for asset in ["BTC", "ETH", "SOL"]:
        e_live, p_live = build_kline_arrays_live(asset)
        try:
            e_vis, p_vis = build_kline_arrays_vision(asset)
        except Exception:
            e_vis, p_vis = np.array([], dtype=np.int64), np.array([], dtype=float)
        mask = out.ticker == asset
        idxs = out.index[mask].tolist()
        for i in idxs:
            slug = out.at[i, "slug"]
            tf = out.at[i, "timeframe"]
            w = 300 if tf == "5m" else 900
            ws_s = slug_to_ws_s(slug, tf)
            # EARLY: [ws_s, ws_s+window]
            p0 = fused_lookup(int(ws_s) * 1_000_000, e_live, p_live, e_vis, p_vis)
            p1 = fused_lookup(int(ws_s + w) * 1_000_000, e_live, p_live, e_vis, p_vis)
            out.at[i, "p_ws"] = p0
            out.at[i, "p_ws_plus_window"] = p1
            if np.isfinite(p0) and p0 > 0 and np.isfinite(p1):
                out.at[i, "ret_early"] = (p1 - p0) / p0
            if tf == "15m":
                slot_start_us = int(out.at[i, "slot_start_us"])
                slot_end_us = int(out.at[i, "slot_end_us"])
                entry_us = slot_end_us - 60 * 1_000_000
                p_ss = fused_lookup(slot_start_us, e_live, p_live, e_vis, p_vis)
                p_le = fused_lookup(entry_us, e_live, p_live, e_vis, p_vis)
                out.at[i, "p_slotstart"] = p_ss
                out.at[i, "p_entry_late"] = p_le
                if np.isfinite(p_ss) and p_ss > 0 and np.isfinite(p_le):
                    out.at[i, "ret_late15"] = (p_le - p_ss) / p_ss
    return out


def signal_from_return(ret: float, thr_bp: float) -> str:
    if not np.isfinite(ret):
        return "SKIP"
    thr = thr_bp / 10_000.0
    if ret > thr:
        return "UP"
    if ret < -thr:
        return "DOWN"
    return "SKIP"


def evaluate(df: pd.DataFrame, ret_col: str, thr_bp: float, label: str,
             entry_price: float = 0.5):
    sub = df.copy()
    sub["sig"] = sub[ret_col].apply(lambda r: signal_from_return(r, thr_bp))
    fired = sub[sub.sig.isin(("UP", "DOWN"))].copy()
    if len(fired) == 0:
        return {"label": label, "thr_bp": thr_bp, "n": 0, "hit_rate": np.nan, "pnl_at_0.5": 0.0}
    fired["won"] = (fired.sig.str.upper() == fired.outcome.str.upper()).astype(int)
    fired["pnl"] = fired.apply(lambda r: hold_pnl_no_book(r.sig, r.outcome, entry_price), axis=1)
    return {
        "label": label,
        "thr_bp": thr_bp,
        "n": int(len(fired)),
        "hit_rate": float(fired.won.mean()),
        "pnl_at_0.5": float(fired.pnl.sum()),
    }


def per_asset_breakdown(df: pd.DataFrame, ret_col: str, thr_bp: float) -> pd.DataFrame:
    sub = df.copy()
    sub["sig"] = sub[ret_col].apply(lambda r: signal_from_return(r, thr_bp))
    fired = sub[sub.sig.isin(("UP", "DOWN"))].copy()
    if len(fired) == 0:
        return pd.DataFrame()
    fired["won"] = (fired.sig.str.upper() == fired.outcome.str.upper()).astype(int)
    fired["pnl"] = fired.apply(lambda r: hold_pnl_no_book(r.sig, r.outcome, 0.5), axis=1)
    return (
        fired.groupby(["ticker", "timeframe"])
        .agg(n=("won", "size"), hit=("won", "mean"), pnl=("pnl", "sum"))
        .round(4)
    )


def main():
    print("[I] Loading resolutions universe...")
    res = load_resolutions()
    print(f"[I] {len(res)} markets total.")

    print("[I] Computing binance returns per row (this loads klines x3 assets)...")
    res = compute_returns(res)
    print(f"[I] ret_early coverage: {res.ret_early.notna().sum()}/{len(res)} "
          f"= {res.ret_early.notna().mean()*100:.1f}%")
    print(f"[I] ret_late15 coverage on 15m: "
          f"{res[res.timeframe == '15m'].ret_late15.notna().sum()}/{(res.timeframe == '15m').sum()}")

    print("\n[I] === SWEEP EARLY (production-anchor ws_s + window) ===")
    rows = []
    for thr in [0, 5, 10, 20, 50]:
        rows.append(evaluate(res, "ret_early", thr, f"EARLY-thr{thr}bp"))
    sweep_early = pd.DataFrame(rows)
    print(sweep_early.to_string())
    sweep_early.to_csv(OUT / "I_sweep_early.csv", index=False)

    print("\n[I] === SWEEP LATE-15m (entry @ slot_end - 60s) ===")
    res15 = res[res.timeframe == "15m"].copy()
    rows_late = []
    for thr in [0, 5, 10, 20, 50]:
        rows_late.append(evaluate(res15, "ret_late15", thr, f"LATE15m-thr{thr}bp"))
    sweep_late = pd.DataFrame(rows_late)
    print(sweep_late.to_string())
    sweep_late.to_csv(OUT / "I_sweep_late15m.csv", index=False)

    # Pick best config: highest hit_rate with n >= 100.
    best_early = max((r for r in rows if r["n"] >= 100), key=lambda r: r["hit_rate"], default=None)
    best_late = max((r for r in rows_late if r["n"] >= 100), key=lambda r: r["hit_rate"], default=None)

    print("\n[I] === PER-ASSET breakdown of best EARLY config ===")
    if best_early:
        print(f"best EARLY: thr={best_early['thr_bp']}bp hit={best_early['hit_rate']:.4f} "
              f"n={best_early['n']}")
        print(per_asset_breakdown(res, "ret_early", best_early["thr_bp"]).to_string())

    print("\n[I] === PER-ASSET breakdown of best LATE-15m config ===")
    if best_late:
        print(f"best LATE: thr={best_late['thr_bp']}bp hit={best_late['hit_rate']:.4f} "
              f"n={best_late['n']}")
        print(per_asset_breakdown(res15, "ret_late15", best_late["thr_bp"]).to_string())

    # No-lookahead sanity check: dump 10 random samples showing ws_s + entry_us < earliest data window
    print("\n[I] === NO-LOOKAHEAD SANITY (10 random EARLY rows) ===")
    smp = res.dropna(subset=["ret_early"]).sample(10, random_state=0)
    for _, r in smp.iterrows():
        w = 300 if r.timeframe == "5m" else 900
        ws_s = slug_to_ws_s(r.slug, r.timeframe)
        print(f"  slug={r.slug} tf={r.timeframe} slot_start_us={r.slot_start_us} "
              f"ws_s_us={ws_s*1_000_000} obs_end_us={(ws_s+w)*1_000_000} "
              f"  -> obs_end < slot_start? {(ws_s+w)*1_000_000 < r.slot_start_us}")

    res[["slug", "ticker", "timeframe", "slot_start_us", "slot_end_us", "outcome",
         "ret_early", "ret_late15"]].to_parquet(OUT / "I_predictions.parquet")

    # Verdict
    verdict = "NULL"
    edge_threshold = 0.52
    if best_early and best_early["hit_rate"] >= edge_threshold and best_early["n"] >= 300:
        verdict = "ALPHA-CANDIDATE-EARLY"
    elif best_late and best_late["hit_rate"] >= edge_threshold and best_late["n"] >= 300:
        verdict = "ALPHA-CANDIDATE-LATE"
    elif (best_early and best_early["hit_rate"] > 0.51) or (best_late and best_late["hit_rate"] > 0.51):
        verdict = "WEAK-POSITIVE"
    print(f"\n[I] verdict: {verdict}")
    return {"best_early": best_early, "best_late": best_late, "verdict": verdict}


if __name__ == "__main__":
    main()
