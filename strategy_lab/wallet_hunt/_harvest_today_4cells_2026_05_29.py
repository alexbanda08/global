"""Harvest profitable NEW wallets from TODAY's btc-5m / btc-15m / sol-15m / eth-15m markets.

1. canonical resolutions -> today's slugs for the 4 requested cells
2. data-api /trades per market -> unique proxyWallets (reuse harvest_market_wallets)
3. dedupe vs already-cataloged wallets
4. score top-N systematic NEW wallets by lb-api profit (all/30d/7d/1d)
5. write ranked candidate CSV + print profitable new wallets to decode

Usage: py -X utf8 strategy_lab/wallet_hunt/_harvest_today_4cells_2026_05_29.py
"""
from __future__ import annotations
import sys, datetime as dt
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "data" / "v4" / "canonical"))
from load import load_resolutions                       # noqa
from harvest_market_wallets import fetch_market_trades, known_wallets  # noqa
from polymarket_api import fetch_lb_profit, lb_amount    # noqa

CACHE = HERE / "cache"
CELLS = {"btc-updown-5m", "btc-updown-15m", "sol-updown-15m", "eth-updown-15m"}
TODAY = dt.datetime(2026, 5, 29, tzinfo=dt.timezone.utc)
DAY_LO = int(TODAY.timestamp())
DAY_HI = DAY_LO + 86_400

def today_slugs():
    res = load_resolutions()
    s = res["slug"].astype(str)
    res = res[s.str.contains("-updown-")].copy()
    res["slot_start_s"] = res["slug"].str.rsplit("-", n=1).str[-1].astype("int64")
    res["cell"] = res["slug"].str.extract(r"^([a-z0-9]+-updown-\d+[mh])-")[0]
    sub = res[(res["cell"].isin(CELLS)) & (res["slot_start_s"] >= DAY_LO) & (res["slot_start_s"] < DAY_HI)]
    return sub.drop_duplicates("slug")[["slug", "cell"]]

def main():
    mk = today_slugs()
    print(f"Today ({TODAY:%Y-%m-%d}) markets in 4 cells: {len(mk)}")
    print(mk["cell"].value_counts().to_string())
    known = known_wallets()
    print(f"Known/excluded wallets: {len(known)}")

    wallet_markets = defaultdict(set); wallet_trades = defaultdict(int)
    wallet_cells = defaultdict(lambda: defaultdict(int))
    slugs = mk.set_index("slug")["cell"].to_dict()
    done = 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(fetch_market_trades, s, 2): s for s in slugs}
        for fut in as_completed(futs):
            s = futs[fut]; cell = slugs[s]
            try: trades = fut.result()
            except Exception: trades = []
            for t in trades:
                w = str(t.get("proxyWallet", "")).lower()
                if not w.startswith("0x"): continue
                wallet_markets[w].add(s); wallet_trades[w] += 1; wallet_cells[w][cell] += 1
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(slugs)} markets, {len(wallet_markets)} wallets", flush=True)

    rows = [dict(wallet=w, n_markets=len(m), n_trades=wallet_trades[w],
                 cell_mix=dict(wallet_cells[w]), is_new=w not in known)
            for w, m in wallet_markets.items()]
    df = pd.DataFrame(rows).sort_values("n_markets", ascending=False)
    new = df[df["is_new"]].copy()
    print(f"\nunique wallets={len(df)}  NEW={len(new)}  systematic NEW (>=4 mkts)={(new.n_markets>=4).sum()}")

    # score top systematic NEW wallets by lb profit
    cand = new[new["n_markets"] >= 4].head(60).copy()
    print(f"\nScoring {len(cand)} systematic NEW wallets by lb-api profit...")
    recs = []
    for w in cand["wallet"]:
        lb = fetch_lb_profit(w, use_cache=True)
        recs.append(dict(wallet=w,
            lb_all=lb_amount(lb, "all"), lb_30d=lb_amount(lb, "30d"),
            lb_7d=lb_amount(lb, "7d"), lb_1d=lb_amount(lb, "1d")))
    sc = pd.DataFrame(recs)
    out = cand.merge(sc, on="wallet", how="left")
    for c in ["lb_all", "lb_30d", "lb_7d", "lb_1d"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.sort_values("lb_all", ascending=False, na_position="last")
    fp = CACHE / "_harvest_today_4cells_2026_05_29.csv"
    out.to_csv(fp, index=False)

    prof = out[(out["lb_all"] > 20000) & (out["lb_7d"].fillna(0) > 0)]
    print(f"\n=== PROFITABLE NEW candidates (lb_all>$20k AND lb_7d>0): {len(prof)} ===")
    show = ["wallet", "n_markets", "n_trades", "lb_all", "lb_30d", "lb_7d", "lb_1d", "cell_mix"]
    print(prof[show].head(25).to_string(index=False))
    print(f"\nAll scored -> {fp}")

if __name__ == "__main__":
    main()
