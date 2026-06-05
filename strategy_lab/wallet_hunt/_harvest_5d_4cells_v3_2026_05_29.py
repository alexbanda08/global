"""Wider harvest — last N days of btc-5m/btc-15m/sol-15m/eth-15m, conditionId-correct.

Extends _harvest_today_4cells_v2 to a multi-day window (more markets = more participants),
dedupes vs catalog + the today-harvest candidates, scores systematic NEW wallets by lb profit.

Usage: py -3 strategy_lab/wallet_hunt/_harvest_5d_4cells_v3_2026_05_29.py --days 5 --score 150
Output: cache/_harvest_5d_4cells_v3_2026_05_29.csv
"""
from __future__ import annotations
import argparse, sys, datetime as dt
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd, requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / "data" / "v4" / "canonical"))
from load import load_resolutions               # noqa
from harvest_market_wallets import known_wallets # noqa
from polymarket_api import fetch_lb_profit, lb_amount  # noqa

CACHE = HERE / "cache"
DATA = "https://data-api.polymarket.com"
UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}
CELLS = {"btc-updown-5m", "btc-updown-15m", "sol-updown-15m", "eth-updown-15m"}


def window_markets(days: int):
    r = load_resolutions(); s = r["slug"].astype(str)
    r = r[s.str.contains("-updown-")].copy()
    r["ss"] = r["slug"].str.rsplit("-", n=1).str[-1].astype("int64")
    r["cell"] = r["slug"].str.extract(r"^([a-z0-9]+-updown-\d+[mh])-")[0]
    hi = int(r["ss"].max()) + 1
    lo = hi - days * 86_400
    r = r[(r["cell"].isin(CELLS)) & (r["ss"] >= lo) & (r["ss"] < hi)]
    return r.drop_duplicates("slug")[["slug", "cell", "market_id"]]


def fetch_by_cid(cid: str, pages: int = 2, ps: int = 500):
    out = []
    for p in range(pages):
        try:
            r = requests.get(f"{DATA}/trades?market={cid}&limit={ps}&offset={p*ps}", headers=UA, timeout=12)
            if r.status_code != 200: break
            j = r.json()
            if not isinstance(j, list) or not j: break
            out.extend(j)
            if len(j) < ps: break
        except Exception:
            break
    return out


def prior_candidates() -> set:
    """Exclude wallets already surfaced by the today-harvest so we find NEW ones."""
    s = set()
    fp = CACHE / "_harvest_today_4cells_v2_2026_05_29.csv"
    if fp.exists():
        s |= {str(x).lower() for x in pd.read_csv(fp)["wallet"].dropna()}
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--score", type=int, default=150)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    mk = window_markets(args.days)
    print(f"{args.days}d 4-cell markets: {len(mk)}"); print(mk["cell"].value_counts().to_string())
    known = known_wallets() | prior_candidates()
    print(f"Known/excluded (catalog + today-harvest): {len(known)}")
    cid_cell = dict(zip(mk["market_id"], mk["cell"]))
    wm = defaultdict(set); wt = defaultdict(int); wc = defaultdict(lambda: defaultdict(int))
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_by_cid, c): c for c in mk["market_id"]}
        for fut in as_completed(futs):
            c = futs[fut]; cell = cid_cell[c]
            try: trades = fut.result()
            except Exception: trades = []
            for t in trades:
                w = str(t.get("proxyWallet", "")).lower()
                if not w.startswith("0x"): continue
                wm[w].add(c); wt[w] += 1; wc[w][cell] += 1
            done += 1
            if done % 100 == 0: print(f"  {done}/{len(mk)} markets, {len(wm)} wallets", flush=True)

    rows = [dict(wallet=w, n_markets=len(m), n_trades=wt[w], cell_mix=dict(wc[w]), is_new=w not in known)
            for w, m in wm.items()]
    df = pd.DataFrame(rows).sort_values("n_markets", ascending=False)
    new = df[df["is_new"]].copy()
    print(f"\nunique wallets={len(df)}  NEW(not catalog/today)={len(new)}  systematic NEW(>=5 mkts)={(new.n_markets>=5).sum()}")

    cand = new[new["n_markets"] >= 4].head(args.score).copy()
    print(f"Scoring {len(cand)} NEW wallets (>=4 markets) by lb profit...")
    recs = []
    for w in cand["wallet"]:
        lb = fetch_lb_profit(w, use_cache=True)
        recs.append(dict(wallet=w, lb_all=lb_amount(lb, "all"), lb_30d=lb_amount(lb, "30d"),
                         lb_7d=lb_amount(lb, "7d"), lb_1d=lb_amount(lb, "1d")))
    out = cand.merge(pd.DataFrame(recs), on="wallet", how="left")
    for c in ["lb_all", "lb_30d", "lb_7d", "lb_1d"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.sort_values(["lb_7d", "lb_all"], ascending=False, na_position="last")
    fp = CACHE / "_harvest_5d_4cells_v3_2026_05_29.csv"; out.to_csv(fp, index=False)
    show = ["wallet", "n_markets", "n_trades", "cell_mix", "lb_all", "lb_30d", "lb_7d", "lb_1d"]
    print("\n=== TOP NEW candidates by lb_7d (5d, systematic in OUR 4 cells, not previously found) ===")
    print(out[show].head(30).to_string(index=False))
    print(f"\nsaved -> {fp}")


if __name__ == "__main__":
    main()
