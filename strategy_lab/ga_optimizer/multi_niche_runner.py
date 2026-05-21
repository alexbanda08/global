"""
Multi-niche orchestrator. Runs GA on all 9 (asset, sleeve_type) combinations
serially or with limited parallelism (joblib).

Outputs:
  strategy_lab/ga_optimizer/runs/multi_niche_<ts>/
    {ASSET}_{sleeve}/                 per-niche run dir with checkpoints
    summary.json                      aggregated top-1 per niche
    portfolio.json                    combined deployable config
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import load_resolutions, load_klines_asof, load_orderbook_l25_streaming
from strategy_lab.ga_optimizer.genome import GENOMES
from strategy_lab.ga_optimizer.seeds import SEEDS
from strategy_lab.ga_optimizer.ga_loop_v2 import GAConfigV2, run_ga_v2

NICHES = [
    ("BTC", "momo_5m"),  ("BTC", "momo_15m"),  ("BTC", "mispricing_15m"),
    ("ETH", "momo_5m"),  ("ETH", "momo_15m"),  ("ETH", "mispricing_15m"),
    ("SOL", "momo_5m"),  ("SOL", "momo_15m"),  ("SOL", "mispricing_15m"),
]


def run_niche(asset: str, sleeve_type: str, pop: int, gens: int,
              cap: int, run_root: Path) -> dict:
    print(f"\n{'='*80}\n=== NICHE: {asset} {sleeve_type}  pop={pop} gens={gens} ===\n{'='*80}")
    t0 = time.time()

    res = load_resolutions()
    tf = "5m" if sleeve_type == "momo_5m" else "15m"
    res = res[(res.ticker == asset) & (res.timeframe == tf)].sort_values("slot_start_us").reset_index(drop=True)
    if len(res) > cap:
        idx = np.linspace(0, len(res) - 1, cap).astype(int)
        res = res.iloc[idx].reset_index(drop=True)
    print(f"  {asset} {tf}: {len(res):,} markets")

    slugs = set(res.slug.unique())
    books = {}
    slugs_list = list(slugs)
    BATCH = 500
    t_books = time.time()
    for i in range(0, len(slugs_list), BATCH):
        chunk = set(slugs_list[i:i+BATCH])
        bks = load_orderbook_l25_streaming(asset.lower(), slugs=chunk, subsample_1hz=True)
        books.update(bks)
    print(f"  L25: {len(books)} keys in {time.time()-t_books:.0f}s")

    end_us, prices = load_klines_asof(asset, "binance-spot-ws", "1MIN")

    config = GAConfigV2(sleeve_type=sleeve_type, asset=asset,
                       population_size=pop, n_generations=gens)
    genome = GENOMES[sleeve_type]
    seeds = SEEDS[sleeve_type]()
    niche_dir = run_root / f"{asset}_{sleeve_type}"
    final = run_ga_v2(config, genome, seeds, res, books, end_us, prices, niche_dir)

    elapsed = time.time() - t0
    print(f"\n  NICHE DONE in {elapsed/60:.1f} min")
    return {"asset": asset, "sleeve_type": sleeve_type, "elapsed_s": elapsed,
            "top1": final[0] if final else None,
            "top5": final}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", type=int, default=60)
    ap.add_argument("--generations", type=int, default=30)
    ap.add_argument("--n-markets-cap", type=int, default=3000)
    ap.add_argument("--niches", nargs="*", default=None,
                     help="e.g. BTC_momo_5m ETH_momo_15m. Default: all 9.")
    args = ap.parse_args()

    if args.niches:
        run_set = []
        for n in args.niches:
            parts = n.split("_", 1)
            run_set.append((parts[0], parts[1]))
    else:
        run_set = NICHES

    print(f"=== MULTI-NICHE GA: {len(run_set)} niches  pop={args.population}  gens={args.generations} ===")
    print(f"  Niches: {run_set}")

    ts = int(time.time())
    run_root = ROOT / "strategy_lab" / "ga_optimizer" / "runs" / f"multi_niche_{ts}"
    run_root.mkdir(parents=True, exist_ok=True)

    all_results = []
    for asset, sleeve in run_set:
        try:
            r = run_niche(asset, sleeve, args.population, args.generations,
                          args.n_markets_cap, run_root)
            all_results.append(r)
            # incremental summary save
            with open(run_root / "summary.json", "w") as f:
                json.dump(all_results, f, indent=2, default=str)
        except Exception as e:
            import traceback
            print(f"  NICHE FAILED ({asset} {sleeve}): {e}")
            traceback.print_exc()
            all_results.append({"asset": asset, "sleeve_type": sleeve, "error": str(e)})

    # Build deployable portfolio
    portfolio = []
    for r in all_results:
        if "top1" in r and r["top1"]:
            top1 = r["top1"]
            held = top1.get("held_out", {})
            if held.get("pnl", 0) > 0 and held.get("n", 0) >= 30:
                portfolio.append({
                    "asset": r["asset"], "sleeve_type": r["sleeve_type"],
                    "individual": top1["individual"],
                    "held_out_pnl": held.get("pnl"),
                    "held_out_n": held.get("n"),
                    "held_out_win_rate": held.get("win_rate"),
                    "held_out_sharpe": held.get("sharpe"),
                })
    with open(run_root / "portfolio.json", "w") as f:
        json.dump({"deployable_sleeves": portfolio,
                   "total_held_out_pnl": sum(p["held_out_pnl"] for p in portfolio),
                   "total_held_out_n": sum(p["held_out_n"] for p in portfolio)},
                  f, indent=2, default=str)

    print(f"\n{'='*80}\n=== ALL NICHES DONE ===")
    print(f"Run dir: {run_root}")
    print(f"Deployable sleeves: {len(portfolio)}")
    if portfolio:
        total = sum(p["held_out_pnl"] for p in portfolio)
        print(f"Combined held-out PnL: ${total:+.2f}")


if __name__ == "__main__":
    main()
