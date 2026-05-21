"""
Full LB-API sweep across 17 known wallets, plus discovery of Polymarket
leaderboard endpoints across all known API hosts.

Outputs:
  cache/_lb_api_full_results.json
  cache/_lb_api_discrepancy_table.csv
  cache/_leaderboard_endpoint_probe.json
"""
from __future__ import annotations
import json
import time
from pathlib import Path

import pandas as pd
import requests

CACHE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache")
LB_BASE = "http://lb-api.polymarket.com"

EXPECTED_CHAIN_PER_DAY = {
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
    "0xf3cfb6a6": None,
    "0xf7f0b0b1": 30_000,
}


def load_address_map() -> dict[str, str]:
    """Combine prior resolution + new missing-resolution dump."""
    out: dict[str, str] = {}
    p1 = CACHE / "_address_resolution.json"
    if p1.exists():
        for k, v in json.loads(p1.read_text()).items():
            if v:
                out[k] = v
    p2 = CACHE / "_missing_resolved.json"
    if p2.exists():
        for k, v in json.loads(p2.read_text()).items():
            if v:
                out[k] = v
    return out


def first_or_empty(j):
    if isinstance(j, list) and j:
        return j[0]
    return {}


def fetch(addr: str, endpoint: str, window: str) -> dict:
    url = f"{LB_BASE}/{endpoint}"
    try:
        r = requests.get(url, params={"window": window, "address": addr}, timeout=8)
        if r.status_code != 200:
            return {"_status": r.status_code}
        return first_or_empty(r.json())
    except Exception as e:
        return {"_err": str(e)}


def sweep():
    amap = load_address_map()
    rows = []
    raw = {}
    for short, full in sorted(amap.items()):
        prof_all = fetch(full, "profit", "all")
        prof_1d  = fetch(full, "profit", "1d")
        prof_7d  = fetch(full, "profit", "7d")
        prof_30d = fetch(full, "profit", "30d")
        vol_all  = fetch(full, "volume", "all")
        vol_1d   = fetch(full, "volume", "1d")
        vol_7d   = fetch(full, "volume", "7d")
        vol_30d  = fetch(full, "volume", "30d")

        raw[short] = {
            "full": full,
            "profit": {"all": prof_all, "1d": prof_1d, "7d": prof_7d, "30d": prof_30d},
            "volume": {"all": vol_all, "1d": vol_1d, "7d": vol_7d, "30d": vol_30d},
        }
        pseudonym = (prof_all.get("pseudonym") or prof_all.get("name") or "")[:32]
        rows.append({
            "short": short,
            "full": full,
            "pseudonym": pseudonym,
            "lb_profit_all":  prof_all.get("amount"),
            "lb_profit_1d":   prof_1d.get("amount"),
            "lb_profit_7d":   prof_7d.get("amount"),
            "lb_profit_30d":  prof_30d.get("amount"),
            "lb_volume_all":  vol_all.get("amount"),
            "lb_volume_1d":   vol_1d.get("amount"),
            "lb_volume_7d":   vol_7d.get("amount"),
            "lb_volume_30d":  vol_30d.get("amount"),
            "chain_per_day_expected": EXPECTED_CHAIN_PER_DAY.get(short),
        })

    df = pd.DataFrame(rows)
    df["lb_per_day_30d"] = df["lb_profit_30d"].astype(float) / 30 if df["lb_profit_30d"].notna().any() else None
    df["lb_per_day_7d"]  = df["lb_profit_7d"].astype(float) / 7 if df["lb_profit_7d"].notna().any() else None
    df["chain_vs_lb30_ratio"] = (
        df["chain_per_day_expected"] / df["lb_per_day_30d"].replace(0, pd.NA)
    )

    out_csv = CACHE / "_lb_api_discrepancy_table.csv"
    df.to_csv(out_csv, index=False)
    (CACHE / "_lb_api_full_results.json").write_text(json.dumps(raw, default=str, indent=2))

    # Print top-level
    cols = [
        "short", "pseudonym", "lb_profit_all", "lb_profit_30d", "lb_profit_7d",
        "lb_profit_1d", "lb_volume_30d", "chain_per_day_expected", "lb_per_day_30d",
    ]
    for c in cols:
        if c in df:
            df[c] = df[c]
    print(df[cols].to_string(index=False))
    print(f"\nSaved: {out_csv}")


def probe_leaderboards():
    """Try every host pattern Polymarket uses publicly."""
    candidates = [
        # lb-api
        f"{LB_BASE}/profit?window=1d",
        f"{LB_BASE}/profit?window=1d&limit=50",
        f"{LB_BASE}/profit/leaderboard?window=1d",
        f"{LB_BASE}/profit/top?window=1d",
        f"{LB_BASE}/profit?window=1d&top=50",
        f"{LB_BASE}/volume?window=1d",
        # data-api
        "https://data-api.polymarket.com/leaderboard?window=1d&type=profit",
        "https://data-api.polymarket.com/leaderboard?window=1d",
        "https://data-api.polymarket.com/leaderboard/profit?window=1d",
        "https://data-api.polymarket.com/top-traders?window=1d",
        # gamma-api
        "https://gamma-api.polymarket.com/leaderboard?window=1d",
        "https://gamma-api.polymarket.com/leaderboard",
        # polymarket.com/api
        "https://polymarket.com/api/leaderboard?window=1d",
        "https://polymarket.com/api/profile/leaderboard?window=1d",
        # clob.polymarket.com leaderboard?
        "https://clob.polymarket.com/leaderboard?window=1d",
    ]
    out = {}
    for url in candidates:
        try:
            r = requests.get(url, timeout=8)
            try:
                j = r.json()
                preview = (
                    {"len": len(j), "first": j[0] if j else None}
                    if isinstance(j, list)
                    else {"keys": list(j.keys())[:8] if isinstance(j, dict) else None}
                )
            except Exception:
                preview = {"_text": r.text[:200]}
            out[url] = {"status": r.status_code, "preview": preview}
            print(f"  [{r.status_code}] {url}")
            if r.status_code == 200 and isinstance(preview, dict):
                print(f"       preview={preview}")
        except Exception as e:
            out[url] = {"_err": str(e)}
            print(f"  [ERR] {url}: {e}")

    (CACHE / "_leaderboard_endpoint_probe.json").write_text(
        json.dumps(out, default=str, indent=2)
    )


if __name__ == "__main__":
    print("=" * 70)
    print("FULL SWEEP — LB-API on all known wallets")
    print("=" * 70)
    sweep()
    print()
    print("=" * 70)
    print("LEADERBOARD ENDPOINT DISCOVERY")
    print("=" * 70)
    probe_leaderboards()
