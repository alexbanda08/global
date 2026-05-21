"""
CLI runner for single-niche GA. Usage:

    py -3 -X utf8 -m strategy_lab.ga_optimizer.runner \
        --sleeve momo_5m --asset BTC \
        --population 50 --generations 30
"""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from load import load_resolutions, load_klines_asof, load_orderbook_l25_streaming
from strategy_lab.ga_optimizer.genome import GENOMES
from strategy_lab.ga_optimizer.seeds import SEEDS
from strategy_lab.ga_optimizer.ga_loop import GAConfig, run_ga


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sleeve", required=True, choices=["momo_5m","momo_15m","mispricing_15m"])
    ap.add_argument("--asset", required=True, choices=["BTC","ETH","SOL"])
    ap.add_argument("--population", type=int, default=50)
    ap.add_argument("--generations", type=int, default=30)
    ap.add_argument("--n-markets-cap", type=int, default=3000,
                     help="Cap universe per asset/tf for faster iteration")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    print(f"=== GA: sleeve={args.sleeve} asset={args.asset} pop={args.population} gens={args.generations} ===")

    # Load data
    print("[loading] resolutions...")
    res = load_resolutions()
    tf = "5m" if args.sleeve == "momo_5m" else "15m"
    res = res[(res.ticker == args.asset) & (res.timeframe == tf)].sort_values("slot_start_us").reset_index(drop=True)
    print(f"  {args.asset} {tf}: {len(res):,} markets")
    if len(res) > args.n_markets_cap:
        # Sample uniformly across time
        import numpy as np
        idx = np.linspace(0, len(res)-1, args.n_markets_cap).astype(int)
        res = res.iloc[idx].reset_index(drop=True)
        print(f"  sampled to {len(res):,}")

    print(f"[loading] L25 books for {args.asset}...")
    slugs = set(res.slug.unique())
    t0 = time.time()
    books = {}
    slugs_list = list(slugs)
    BATCH = 500
    for i in range(0, len(slugs_list), BATCH):
        chunk = set(slugs_list[i:i+BATCH])
        bks = load_orderbook_l25_streaming(args.asset.lower(), slugs=chunk, subsample_1hz=True)
        books.update(bks)
    print(f"  loaded {len(books)} (slug,side) keys in {time.time()-t0:.0f}s")

    print(f"[loading] binance klines for {args.asset}...")
    end_us, prices = load_klines_asof(args.asset, "binance-spot-ws", "1MIN")
    print(f"  {len(end_us):,} 1MIN bars")

    config = GAConfig(
        sleeve_type=args.sleeve, asset=args.asset,
        population_size=args.population, n_generations=args.generations,
        seed=args.seed,
    )
    genome = GENOMES[args.sleeve]
    seeds = SEEDS[args.sleeve]()

    run_dir = ROOT / "strategy_lab" / "ga_optimizer" / "runs" / f"{args.asset}_{args.sleeve}_{int(time.time())}"
    results = run_ga(config, genome, seeds, res, books, end_us, prices, run_dir)


if __name__ == "__main__":
    main()
