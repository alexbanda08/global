"""
Market-level wallet discovery — harvest the FULL participant universe of up-down
markets, not just counterparties of known wallets.

data-api.polymarket.com/trades?market=<slug> returns every trade on a market
(proxyWallet of each participant). We sample N updown markets spread across the
canonical window + assets + timeframes, collect every unique proxyWallet and how
many sampled markets it appears in (= how systematic the trader is), then dedupe
against wallets we've already cataloged.

Frequent participants (high n_markets) = the systematic bots/traders we want to
WR-scan next.

Output: cache/_harvest_wallets.csv  (ranked, new wallets only)

Usage:
  py -3 strategy_lab/wallet_hunt/harvest_market_wallets.py --n-markets 400 --pages 2
"""
from __future__ import annotations
import argparse
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions  # noqa: E402

CACHE = Path(__file__).resolve().parent / "cache"
DATA = "https://data-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}

# Polymarket infra / exchange contracts to exclude from "wallets"
EXCLUDE = {
    "0xe111180000d2663c0091e4f400237545b87b996b",
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",
    "0x84ba896235059fe27727eaa2695a9f99220d9a7e",
    "0xd91e80cf2e7be2e162c6513ced06f1dd0da35296",
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",
}


def known_wallets() -> set[str]:
    s = set()
    for f in ["_directional_wallet_registry.csv", "_lb_counterparties_scored.csv",
              "_master_catalog.csv"]:
        fp = CACHE / f
        if fp.exists():
            df = pd.read_csv(fp)
            for col in ["full", "counterparty", "short"]:
                if col in df.columns:
                    s |= {str(x).lower() for x in df[col].dropna() if str(x).startswith("0x")}
    return s | EXCLUDE


def fetch_market_trades(market_id: str, pages: int, page_size: int = 500) -> list[dict]:
    # NOTE: data-api /trades?market= REQUIRES the conditionId (canonical `market_id`).
    # Passing the SLUG is silently ignored and returns the GLOBAL trade feed (bug fixed
    # 2026-05-29). Always pass the 0x conditionId here.
    out = []
    for p in range(pages):
        url = f"{DATA}/trades?market={market_id}&limit={page_size}&offset={p * page_size}"
        try:
            r = requests.get(url, headers=UA, timeout=12)
            if r.status_code != 200:
                break
            j = r.json()
            if not isinstance(j, list) or not j:
                break
            out.extend(j)
            if len(j) < page_size:
                break
        except Exception:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-markets", type=int, default=400)
    ap.add_argument("--pages", type=int, default=2, help="pages of /trades per market (500 each)")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    res = load_resolutions()
    res = res[res["slug"].astype(str).str.contains("-updown-")].copy()
    res["asset"] = res["slug"].str.extract(r"^([a-z0-9]+)-updown")[0]
    res["tf"] = res["slug"].str.extract(r"-updown-(\d+[mh])-")[0]
    res["slot_start_s"] = res["slug"].str.rsplit("-", n=1).str[-1].astype("int64")

    # stratified sample: spread across asset x tf x day
    res["day"] = res["slot_start_s"] // 86_400
    per_cell = max(1, args.n_markets // (res.groupby(["asset", "tf"]).ngroups))
    sample = (res.groupby(["asset", "tf"], group_keys=False)
              .apply(lambda g: g.sample(min(len(g), per_cell), random_state=11)))
    slugs = sample["slug"].tolist()
    slug_cid = dict(zip(sample["slug"], sample["market_id"]))  # conditionId for /trades (bugfix)
    print(f"Sampling {len(slugs)} markets across {res.groupby(['asset','tf']).ngroups} cells, "
          f"{args.pages} pages each...")

    known = known_wallets()
    print(f"Known/excluded wallets: {len(known)}")

    wallet_markets = defaultdict(set)
    wallet_trades = defaultdict(int)
    wallet_assets = defaultdict(lambda: defaultdict(int))
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_market_trades, slug_cid[s], args.pages): s for s in slugs}
        for fut in as_completed(futs):
            slug = futs[fut]
            asset = slug.split("-")[0]
            try:
                trades = fut.result()
            except Exception:
                trades = []
            for t in trades:
                w = str(t.get("proxyWallet", "")).lower()
                if not w.startswith("0x"):
                    continue
                wallet_markets[w].add(slug)
                wallet_trades[w] += 1
                wallet_assets[w][asset] += 1
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(slugs)} markets, {len(wallet_markets)} unique wallets so far", flush=True)

    rows = []
    for w, mkts in wallet_markets.items():
        rows.append({
            "wallet": w,
            "n_markets_seen": len(mkts),
            "n_trades_seen": wallet_trades[w],
            "asset_mix": dict(wallet_assets[w]),
            "is_new": w not in known,
        })
    df = pd.DataFrame(rows).sort_values("n_markets_seen", ascending=False)
    new = df[df["is_new"]].copy()

    out = CACHE / "_harvest_wallets.csv"
    df.to_csv(out, index=False)
    print(f"\nTotal unique wallets: {len(df)}  |  NEW (not cataloged): {len(new)}")
    print(f"Wallets in >=5 sampled markets (systematic): {(df['n_markets_seen']>=5).sum()}  "
          f"(new: {(new['n_markets_seen']>=5).sum()})")
    print("\nTop 25 NEW systematic wallets:")
    print(new.head(25)[["wallet", "n_markets_seen", "n_trades_seen", "asset_mix"]].to_string(index=False))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
