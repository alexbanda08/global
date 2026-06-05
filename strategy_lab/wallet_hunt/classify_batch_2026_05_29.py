"""Classify a batch of wallets via data-api activity (strategy archetype) + lb-api profit.

Reuses the proven deepdive() signature from lb_api_deepdive_v3.py:
  - pct_updown, asset/timeframe mix
  - pct_slugs_paired_buy / both_sides / single_outcome  -> archetype verdict
    (PURE_PAIR_ARB_MAKER / MINT_AND_SELL / DIRECTIONAL_TAKER_* / ASK_HEAVY_MAKER / ...)
  - merge/split/rebate density, notional, price stats
Adds lb-api lifetime/30d/7d profit + portfolio value.

Output: cache/_classify_batch_2026_05_29.csv

Usage: py -3 strategy_lab/wallet_hunt/classify_batch_2026_05_29.py
"""
from __future__ import annotations
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lb_api_deepdive_v3 import deepdive  # noqa: E402

CACHE = HERE / "cache"
LB = "http://lb-api.polymarket.com"
DATA = "https://data-api.polymarket.com"

WALLETS = [
    "0xee65685de42f8de9a03b4c53ee77d56a20d2cfc9",
    "0x74a2b82f079e12bcc25cd0d479f17979fb62e32f",
    "0xa70f7d263122d7664441c864b0f806c23791dbc6",  # promising
    "0x47f606ca2cfd1fed2a9e0845c2ac4c90e861b482",
    "0x07e87aec5c341c21f874003c7eaf84250b9aed9f",
    "0x7399fe3ecdc1ac708b418448101d0475d1f9ef2e",
    "0x0fe40e887acbd0022f89d996acce26ab428501b7",  # known: non-updown $408k
    "0x8320b90db15e5b777e5a023b5ba3cfa214d4904e",
    "0xfdc072df1e4c7d91334cf622d0520d51aef5e6a1",
    "0x6e1d5040d0ac73709b0621f620d2a60b80d2d0fa",
    "0x4ee29e4e7d4c380babeae5e22e5c02400c2246e1",
    "0xeee92f1cc6d6e0ad0b4ffda20b01cf3678e27ecb",
    "0xa42f127d7e8df9f16881ffcc9ed0bc0326875f5a",
]


def lb_profit(addr: str) -> dict:
    out = {}
    s = requests.Session()
    s.headers["accept"] = "application/json"
    for w in ("all", "30d", "7d", "1d"):
        try:
            r = s.get(f"{LB}/profit", params={"window": w, "address": addr}, timeout=8)
            j = r.json() if r.status_code == 200 else None
            out[f"lb_profit_{w}"] = (j[0].get("amount") if isinstance(j, list) and j else None)
            if w == "all" and isinstance(j, list) and j:
                out["pseudonym"] = j[0].get("pseudonym")
        except Exception:
            out[f"lb_profit_{w}"] = None
    try:
        r = s.get(f"{DATA}/value", params={"user": addr}, timeout=8)
        j = r.json() if r.status_code == 200 else None
        out["portfolio_value"] = (j[0].get("value") if isinstance(j, list) and j else None)
    except Exception:
        out["portfolio_value"] = None
    return out


def main():
    rows = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        dfut = {ex.submit(deepdive, a, a[:10], "NEW"): a for a in WALLETS}
        lfut = {ex.submit(lb_profit, a): a for a in WALLETS}
        dres = {}
        for f in as_completed(dfut):
            a = dfut[f]
            try:
                dres[a] = f.result()
            except Exception as e:
                dres[a] = {"addr": a, "error": str(e)}
        lres = {}
        for f in as_completed(lfut):
            lres[lfut[f]] = f.result()

    for a in WALLETS:
        d = dres.get(a, {})
        flat = {k: v for k, v in d.items() if not isinstance(v, (dict, list))}
        flat["asset_mix"] = json.dumps(d.get("asset_mix", {}))
        flat["timeframe_mix"] = json.dumps(d.get("timeframe_mix", {}))
        flat.update(lres.get(a, {}))
        rows.append(flat)

    df = pd.DataFrame(rows)
    out = CACHE / "_classify_batch_2026_05_29.csv"
    df.to_csv(out, index=False)

    cols = ["addr", "pseudonym", "verdict", "pct_updown", "n_updown_trades", "n_slugs",
            "pct_slugs_paired_buy", "pct_slugs_both_sides", "pct_slugs_single_outcome",
            "pct_buy", "up_pct", "n_merge", "n_split", "n_rebate", "notional_med",
            "price_med", "asset_mix", "timeframe_mix",
            "lb_profit_all", "lb_profit_30d", "lb_profit_7d", "portfolio_value"]
    cols = [c for c in cols if c in df.columns]
    print("=" * 100)
    print("BATCH CLASSIFICATION — 13 wallets")
    print("=" * 100)
    print(df[cols].to_string(index=False))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
