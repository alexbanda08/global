"""Phase B — Sub-second L25 walk fills + real PnL.

Builds on Phase A's 11,585 clean fires. For each fire:
  - Look up L25 book at fire_us + 85ms (LiveMimicConfig)
  - Walk asks for $25 notional → vwap, shares, fee_in
  - hold_pnl with won/lost from chainlink outcome
  - apply spread filter (0.02), sparse-book filter (≥25 events)

Memory budget: load one asset at a time, filter to fires' slugs.
"""
from __future__ import annotations
import sys
from pathlib import Path
import gc
import numpy as np
import pandas as pd

sys.path.insert(0, "data/v4/canonical")
sys.path.insert(0, "strategy_lab")
from load import load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import (  # noqa: E402
    LiveMimicConfig, fill_at_book, hold_pnl, book_event_count,
)

IN_DIR  = Path("strategy_lab/markov_filter/_results/clean_backtest_phase_a")
OUT_DIR = Path("strategy_lab/markov_filter/_results/clean_backtest_phase_b")
OUT_DIR.mkdir(parents=True, exist_ok=True)

ASSETS = ("BTC", "ETH", "SOL")
NOTIONAL = 25.0


def signal_to_outcome(sig: str) -> str:
    """UP signal → buy 'Up' side. DOWN signal → buy 'Down' side."""
    return "Up" if sig == "UP" else "Down"


def main():
    cfg = LiveMimicConfig()
    print(f"Engine config: {cfg.name}, fee={cfg.fee_model}, latency={cfg.latency_ms}ms")
    print(f"Notional ${cfg.notional_usd}, sparse-book min={cfg.min_book_events}")

    fires = pd.read_csv(IN_DIR / "all_fires_with_gates.csv")
    print(f"\n[1] {len(fires):,} fires loaded")
    # We need slug — Phase A didn't save it. Reload from resolutions.
    sys.path.insert(0, "data/v4/canonical")
    from load import load_resolutions
    r = load_resolutions()
    r["slot_start_s"] = (r["slot_start_us"] // 1_000_000).astype("int64")
    r["asset"] = r["ticker"].str.upper()
    slug_lookup = r.set_index(["asset", "slot_start_s"])["slug"].to_dict()
    fires["slug"] = fires.apply(
        lambda x: slug_lookup.get((x["asset"], x["slot_start_s"])), axis=1
    )
    n_have = fires["slug"].notna().sum()
    print(f"   {n_have:,}/{len(fires):,} fires have slug")

    # Compute outcome side (Up/Down) per fire signal
    fires["outcome_side"] = fires["signal"].map(signal_to_outcome)
    fires["slot_end_us"] = (fires["slot_start_s"] + fires["window_s"]
                            if "window_s" in fires.columns
                            else fires["slot_start_s"] + np.where(fires["tf"] == "5m", 300, 900)
                            ) * 1_000_000
    if "window_s" not in fires.columns:
        fires["window_s"] = np.where(fires["tf"] == "5m", 300, 900)
        fires["slot_end_us"] = (fires["slot_start_s"] + fires["window_s"]) * 1_000_000

    results = []
    for asset in ASSETS:
        sub = fires[(fires["asset"] == asset) & fires["slug"].notna()].copy()
        if sub.empty:
            print(f"\n[2:{asset}] no fires"); continue
        slugs = set(sub["slug"].unique())
        print(f"\n[2:{asset}] loading L25 books for {len(slugs):,} unique slugs...")
        books = load_orderbook_l25_streaming(
            asset, slugs=slugs, subsample_1hz=True,
            min_ts_us=int(sub["slot_start_s"].min() - 1800) * 1_000_000,
            max_ts_us=int(sub["slot_end_us"].max() + 1_000_000),
        )
        print(f"   {len(books):,} (slug, outcome) book series loaded")

        # Per-fire fill
        print(f"   filling fires for {asset}...")
        n_filled = 0
        for r in sub.itertuples(index=False):
            slug = r.slug
            side = r.outcome_side
            fire_us = int(r.fire_us)
            # sparse-book filter — count events in [slot_start, slot_end]
            n_events = book_event_count(books, slug, side,
                                         int(r.slot_start_s) * 1_000_000,
                                         int(r.slot_end_us))
            if n_events < cfg.min_book_events:
                continue
            fill = fill_at_book(books, slug, side, fire_us, cfg=cfg,
                                spread_filter=0.02)
            if fill is None:
                continue
            won = bool(r.won)
            pnl = hold_pnl(fill, won=won, cfg=cfg)
            results.append({
                "asset": asset, "tf": r.tf,
                "strategy": r.strategy, "cell": r.cell,
                "slug": slug, "ws_s": int(r.ws_s),
                "signal": r.signal, "outcome": r.outcome, "won": won,
                "fire_us": fire_us,
                "vwap": fill["vwap"], "shares": fill["shares"],
                "usd": fill["usd"], "fee_in": fill["fee_in"],
                "ask0": fill["ask0"], "bid0": fill["bid0"],
                "pnl": pnl,
                "f7_pass": bool(r.f7_pass),
                "rsi_14": r.rsi_14,
                "markov_pass_w20_1m_voladaptive": bool(getattr(r, "markov_pass_w20_1m_voladaptive", False)),
                "markov_pass_w20_5m_voladaptive": bool(getattr(r, "markov_pass_w20_5m_voladaptive", False)),
                "markov_pass_w20_1m_fixed": bool(getattr(r, "markov_pass_w20_1m_fixed", False)),
                "markov_pass_w20_5m_fixed": bool(getattr(r, "markov_pass_w20_5m_fixed", False)),
            })
            n_filled += 1
        print(f"   {asset}: {n_filled:,} fills produced (of {len(sub):,} attempted)")
        del books
        gc.collect()

    print(f"\n[3] {len(results):,} total fills with PnL")
    if not results:
        print("NO RESULTS — aborting"); return
    df = pd.DataFrame(results)
    df.to_csv(OUT_DIR / "fills_with_pnl.csv", index=False)
    print(f"   wrote {OUT_DIR / 'fills_with_pnl.csv'}")

    # Scorecard
    print("\n=== PER-CELL × STRATEGY × GATE SCORECARD ===")
    rows = []
    for (strat, cell), g in df.groupby(["strategy", "cell"]):
        for label, mask in [
            ("BASE", pd.Series([True] * len(g), index=g.index)),
            ("F7",  g["f7_pass"]),
            ("M:1m_va",  g["markov_pass_w20_1m_voladaptive"]),
            ("M:1m_fix", g["markov_pass_w20_1m_fixed"]),
            ("M:5m_va",  g["markov_pass_w20_5m_voladaptive"]),
            ("M:5m_fix", g["markov_pass_w20_5m_fixed"]),
            ("F7+M:1m_va",  g["f7_pass"] & g["markov_pass_w20_1m_voladaptive"]),
            ("F7+M:1m_fix", g["f7_pass"] & g["markov_pass_w20_1m_fixed"]),
            ("F7+M:5m_va",  g["f7_pass"] & g["markov_pass_w20_5m_voladaptive"]),
            ("F7+M:5m_fix", g["f7_pass"] & g["markov_pass_w20_5m_fixed"]),
        ]:
            sub = g[mask]
            n = len(sub)
            rows.append({
                "strategy": strat, "cell": cell, "filter": label,
                "n": n,
                "wr": round(sub["won"].mean() * 100, 2) if n else 0.0,
                "avg_pnl": round(sub["pnl"].mean(), 3) if n else 0.0,
                "sum_pnl": round(sub["pnl"].sum(), 2),
                "avg_vwap": round(sub["vwap"].mean(), 4) if n else 0.0,
            })
    sc = pd.DataFrame(rows)
    sc.to_csv(OUT_DIR / "scorecard.csv", index=False)
    # Quick view
    for strat in ("momo_v1", "momo_v2", "sniper"):
        ss = sc[sc["strategy"] == strat]
        print(f"\n--- {strat} ---")
        pivot = ss.pivot(index="cell", columns="filter",
                         values=["n", "wr", "avg_pnl", "sum_pnl"])
        # Just show BASE / F7 / F7+M:1m_fix for compactness
        for cell in ss["cell"].unique():
            r0 = ss[(ss["cell"] == cell) & (ss["filter"] == "BASE")].iloc[0]
            r1 = ss[(ss["cell"] == cell) & (ss["filter"] == "F7")].iloc[0]
            rm = ss[(ss["cell"] == cell) & (ss["filter"] == "M:1m_fix")].iloc[0]
            rfm = ss[(ss["cell"] == cell) & (ss["filter"] == "F7+M:1m_fix")].iloc[0]
            print(f"   {cell:8s} BASE n={r0['n']:4d} WR={r0['wr']:5.1f}% ${r0['avg_pnl']:+7.3f}/tr sum=${r0['sum_pnl']:+9.2f}  "
                  f"F7 n={r1['n']:4d} WR={r1['wr']:5.1f}% ${r1['avg_pnl']:+7.3f}/tr  "
                  f"M1f n={rm['n']:4d} WR={rm['wr']:5.1f}% ${rm['avg_pnl']:+7.3f}/tr  "
                  f"F7+M1f n={rfm['n']:4d} WR={rfm['wr']:5.1f}% ${rfm['avg_pnl']:+7.3f}/tr")


if __name__ == "__main__":
    main()
