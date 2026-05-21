"""
Resolve full addresses from per-wallet trades_chain.parquet, then hit LB-API
/profit on each. Cross-check vs chain-decoded PnL.

trades_chain.parquet has columns including maker/taker addresses + the wallet
they were filtered for. We just need ONE full address per cache dir.
"""
from __future__ import annotations
import json
import time
from pathlib import Path

import pandas as pd
import requests

BASE = "http://lb-api.polymarket.com"
CACHE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache")

# Expected from pickup ($/day during chain decode windows)
EXPECTED = {
    "0x04b6d7e9": 212_000,
    "0x0fe40e88": 19_000,
    "0x3e6bfd2f": 166_000,
    "0x7dfc8aa2": -7_900,
    "0x7f599984": 6_300,
    "0x89b5cdaa": 10_000,
    "0x9dae874a": 5_900,
    "0xa0a50783": 6_000,
    "0xb27bc932": 254_000,
    "0xce25e214": -295_000,
    "0xcfb103c3": -39,
    "0xeebde7a0": 344_000,
    "0xeefe46de": 94,
    "0xf247584e": None,
    "0xf3cfb6a6": None,  # relay/router
    "0xf7f0b0b1": 30_000,
}


def resolve_full(short_dir: Path) -> str | None:
    """Try pnl.parquet then trades_chain.parquet for a 'wallet' or 'address' column."""
    for fname in ("pnl.parquet", "trades_chain.parquet", "trades.parquet"):
        p = short_dir / fname
        if not p.exists():
            continue
        try:
            df = pd.read_parquet(p)
        except Exception:
            continue
        for c in df.columns:
            cl = c.lower()
            if cl in ("wallet", "address", "trader", "owner") or cl.endswith("_address"):
                vals = df[c].dropna().astype(str).str.lower()
                vals = vals[vals.str.startswith("0x") & (vals.str.len() == 42)]
                if len(vals) == 0:
                    continue
                # the wallet is the one that appears most often
                top = vals.value_counts().index[0]
                if top.startswith(short_dir.name.lower()):
                    return top
        # also scan maker/taker columns and pick the one matching short
        for c in df.columns:
            cl = c.lower()
            if "maker" in cl or "taker" in cl:
                vals = df[c].dropna().astype(str).str.lower()
                vals = vals[vals.str.startswith(short_dir.name.lower()) & (vals.str.len() == 42)]
                if len(vals) > 0:
                    return vals.iloc[0]
    return None


def hit_lb_api(addr: str, window: str) -> tuple[int, dict | None, float]:
    t0 = time.time()
    try:
        r = requests.get(f"{BASE}/profit", params={"window": window, "address": addr}, timeout=8)
        dt = time.time() - t0
        try:
            j = r.json()
        except Exception:
            j = {"_text": r.text[:200]}
        return r.status_code, j, dt
    except Exception as e:
        return -1, {"_err": str(e)}, time.time() - t0


def hit_volume(addr: str, window: str) -> tuple[int, dict | None]:
    try:
        r = requests.get(f"{BASE}/volume", params={"window": window, "address": addr}, timeout=8)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"_text": r.text[:200]}
    except Exception as e:
        return -1, {"_err": str(e)}


def main():
    wallets = sorted([p for p in CACHE.iterdir() if p.is_dir() and p.name.startswith("0x")])
    print(f"Cache wallets: {len(wallets)}")

    rows = []
    full_map = {}
    for w in wallets:
        full = resolve_full(w)
        full_map[w.name] = full
        if not full:
            print(f"  {w.name}  NO FULL ADDR")
            continue

        s_all, j_all, dt = hit_lb_api(full, "all")
        s_1d,  j_1d,  _  = hit_lb_api(full, "1d")
        s_7d,  j_7d,  _  = hit_lb_api(full, "7d")
        s_30,  j_30,  _  = hit_lb_api(full, "30d")
        vs_all, jv_all = hit_volume(full, "all")
        vs_1d,  jv_1d  = hit_volume(full, "1d")

        row = {
            "short": w.name,
            "full": full,
            "expected_per_day_chain": EXPECTED.get(w.name),
            "profit_all": j_all,
            "profit_1d": j_1d,
            "profit_7d": j_7d,
            "profit_30d": j_30,
            "volume_all": jv_all,
            "volume_1d": jv_1d,
        }
        rows.append(row)
        print(
            f"  {w.name}  profit_all={j_all}  profit_1d={j_1d}  "
            f"profit_7d={j_7d}  vol_all={jv_all}"
        )

    out = CACHE / "lb_api_known_wallets.json"
    out.write_text(json.dumps(rows, default=str, indent=2))
    print(f"\nDumped: {out}")

    fm_out = CACHE / "_address_resolution.json"
    fm_out.write_text(json.dumps(full_map, indent=2))
    print(f"Address resolution map: {fm_out}")


if __name__ == "__main__":
    main()
