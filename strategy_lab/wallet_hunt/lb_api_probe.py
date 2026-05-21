"""
LB-API discovery + validation probe.

Endpoints user supplied:
  GET http://lb-api.polymarket.com/profit?window=all&address={addr}
  GET http://lb-api.polymarket.com/profit?window=1d&address={addr}

Goals:
  1. Verify endpoint contract (response shape, fields, units)
  2. Cross-check vs our chain-decoded PnL on known wallets
  3. Probe for adjacent endpoints (leaderboard, volume, positions)
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

BASE = "http://lb-api.polymarket.com"
HERE = Path(__file__).parent
CATALOG = HERE / "cache" / "_master_catalog.csv"

# Anchors with our own chain-decoded $/day from the pickup
KNOWN = {
    "0x04b6d7e9": ("PURE PAIR ARB MAKER", 212_000),
    "0xb27bc932": ("PURE PAIR ARB MAKER scale", 254_000),
    "0xeebde7a0": ("HYBRID maker+taker", 344_000),
    "0xf7f0b0b1": ("mint-and-sell variant", 30_000),
    "0x89b5cdaa": ("DIRECTIONAL maker (undecoded)", 10_000),
    "0xa0a50783": ("F2 cluster TAKER", 6_000),
    "0x9dae874a": ("F2 cluster TAKER", 5_900),
    "0xcfb103c3": ("LOSER", -39),
}


def resolve_full_addr(short: str) -> str | None:
    """Resolve 0x04b6d7e9 → full 42-char address from catalog."""
    if not CATALOG.exists():
        return None
    cat = pd.read_csv(CATALOG)
    addr_col = None
    for c in cat.columns:
        if "addr" in c.lower() or "wallet" in c.lower():
            addr_col = c
            break
    if addr_col is None:
        print(f"WARN: no address column in catalog. Cols: {list(cat.columns)}")
        return None
    short_lower = short.lower()
    for a in cat[addr_col].astype(str):
        if a.lower().startswith(short_lower):
            return a
    return None


def get_profit(addr: str, window: str = "all") -> dict | None:
    url = f"{BASE}/profit"
    params = {"window": window, "address": addr}
    t0 = time.time()
    try:
        r = requests.get(url, params=params, timeout=10)
        dt = time.time() - t0
        print(f"  [{r.status_code}] {window} {addr[:10]}... {dt*1000:.0f}ms  len={len(r.content)}")
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return {"_raw": r.text[:500]}
        else:
            return {"_status": r.status_code, "_text": r.text[:300]}
    except Exception as e:
        print(f"  [ERR] {e}")
        return None


def probe_endpoints(addr: str) -> dict:
    """Try a wide menu of likely endpoints on lb-api."""
    candidates = [
        ("/profit?window=all&address=", addr),
        ("/profit?window=1d&address=", addr),
        ("/profit?window=7d&address=", addr),
        ("/profit?window=30d&address=", addr),
        ("/profit?window=1h&address=", addr),
        ("/volume?window=all&address=", addr),
        ("/volume?window=1d&address=", addr),
        ("/positions?address=", addr),
        ("/leaderboard?window=1d&type=profit", ""),
        ("/leaderboard?window=1d", ""),
        ("/leaderboard?window=all&type=profit", ""),
        ("/leaderboard", ""),
        ("/top?window=1d&type=profit", ""),
        ("/top-traders?window=1d", ""),
        ("/", ""),
    ]
    out = {}
    for path, suffix in candidates:
        url = f"{BASE}{path}{suffix}"
        try:
            r = requests.get(url, timeout=8)
            print(f"  [{r.status_code}] {path}{(' '+suffix[:12]+'...') if suffix else ''}  len={len(r.content)}")
            if r.status_code == 200:
                try:
                    j = r.json()
                    out[path] = j
                except Exception:
                    out[path] = {"_text": r.text[:300]}
            elif r.status_code in (301, 302, 307, 308):
                out[path] = {"_redirect": r.headers.get("Location")}
        except Exception as e:
            print(f"  [ERR] {path}: {e}")
    return out


if __name__ == "__main__":
    print("=" * 70)
    print("STEP 1: validate /profit on known wallets")
    print("=" * 70)
    results = {}
    for short, (label, expected) in KNOWN.items():
        full = resolve_full_addr(short)
        if not full:
            print(f"  {short} {label}: NO FULL ADDR IN CATALOG")
            continue
        print(f"\n{short} ({label})  expected ~${expected:,}/day chain-decoded")
        print(f"  full: {full}")
        for w in ("all", "1d"):
            j = get_profit(full, w)
            if j:
                results[(short, w)] = j
                if isinstance(j, dict) and len(str(j)) < 800:
                    print(f"  {w}: {j}")
                elif isinstance(j, dict):
                    print(f"  {w}: keys={list(j.keys())[:8]}")
                elif isinstance(j, list):
                    print(f"  {w}: list[{len(j)}]; first={j[0] if j else None}")

    # Save full responses to disk
    out_path = HERE / "cache" / "lb_api_probe_results.json"
    serializable = {f"{k[0]}|{k[1]}": v for k, v in results.items()}
    out_path.write_text(json.dumps(serializable, default=str, indent=2))
    print(f"\nResponses dumped: {out_path}")

    print("\n" + "=" * 70)
    print("STEP 2: probe other endpoints on one wallet")
    print("=" * 70)
    sample_addr = resolve_full_addr("0x04b6d7e9") or "0x04b6d7e9d568a1adfb0d3c3ed421c4b3e0a87b1f"
    other = probe_endpoints(sample_addr)
    (HERE / "cache" / "lb_api_endpoint_probe.json").write_text(
        json.dumps(other, default=str, indent=2)
    )
    print("\nEndpoint probe results dumped.")
