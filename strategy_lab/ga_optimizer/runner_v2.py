"""CLI runner for v2 GA (walk-forward CV)."""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import load_resolutions, load_klines_asof, load_orderbook_l25_streaming
from strategy_lab.ga_optimizer.genome import GENOMES
from strategy_lab.ga_optimizer.seeds import SEEDS
from strategy_lab.ga_optimizer.ga_loop_v2 import GAConfigV2, run_ga_v2

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleeve", required=True, choices=["momo_5m","momo_15m","mispricing_15m"])
    ap.add_argument("--asset", required=True, choices=["BTC","ETH","SOL"])
    ap.add_argument("--population", type=int, default=60)
    ap.add_argument("--generations", type=int, default=30)
    ap.add_argument("--n-markets-cap", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n-parallel", type=int, default=1)
    args = ap.parse_args()

    print(f"=== GA v2: sleeve={args.sleeve} asset={args.asset} pop={args.population} gens={args.generations} ===")

    import numpy as np
    res = load_resolutions()
    tf = "5m" if args.sleeve == "momo_5m" else "15m"
    res = res[(res.ticker == args.asset) & (res.timeframe == tf)].sort_values("slot_start_us").reset_index(drop=True)
    print(f"  {args.asset} {tf}: {len(res):,} markets")
    if len(res) > args.n_markets_cap:
        idx = np.linspace(0, len(res)-1, args.n_markets_cap).astype(int)
        res = res.iloc[idx].reset_index(drop=True)
        print(f"  capped to {len(res):,}")

    print(f"[loading] L25 books for {args.asset}...")
    slugs = set(res.slug.unique())
    t0 = time.time()
    books = {}
    slugs_list = list(slugs)
    for i in range(0, len(slugs_list), 500):
        chunk = set(slugs_list[i:i+500])
        bks = load_orderbook_l25_streaming(args.asset.lower(), slugs=chunk, subsample_1hz=True)
        books.update(bks)
    print(f"  loaded {len(books)} (slug,side) keys in {time.time()-t0:.0f}s")

    end_us, prices = load_klines_asof(args.asset, "binance-spot-ws", "1MIN")

    config = GAConfigV2(
        sleeve_type=args.sleeve, asset=args.asset,
        population_size=args.population, n_generations=args.generations,
        seed=args.seed, n_parallel_workers=args.n_parallel,
    )
    genome = GENOMES[args.sleeve]
    seeds = SEEDS[args.sleeve]()

    run_dir = ROOT / "strategy_lab" / "ga_optimizer" / "runs" / f"v2_{args.asset}_{args.sleeve}_{int(time.time())}"
    run_ga_v2(config, genome, seeds, res, books, end_us, prices, run_dir)


if __name__ == "__main__":
    main()
