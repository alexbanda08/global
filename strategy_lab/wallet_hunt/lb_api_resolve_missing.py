"""
For the wallets where trades_chain.parquet didn't expose a wallet-like column,
fall back to: (a) alchemy_transfers.parquet (b) reading a couple of rows of any
parquet looking for the matching prefix.
"""
from __future__ import annotations
import json
from pathlib import Path

import pandas as pd

CACHE = Path(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cache")

MISSING = [
    "0x0fe40e88", "0x3e6bfd2f", "0x7cde1da9", "0x7f599984",
    "0x9dae874a", "0xa0a50783", "0xeefe46de", "0xf247584e",
    "0xf3cfb6a6", "0xf7f0b0b1",
]


def scan_for_full(short: str, d: Path) -> str | None:
    short_lower = short.lower()
    # Try all parquets, all string columns, look for any value matching prefix
    for p in d.rglob("*.parquet"):
        try:
            df = pd.read_parquet(p, columns=None)
        except Exception:
            try:
                df = pd.read_parquet(p)
            except Exception:
                continue
        for c in df.columns:
            try:
                s = df[c].astype(str).str.lower()
            except Exception:
                continue
            mask = s.str.startswith(short_lower) & (s.str.len() == 42)
            if mask.any():
                return s[mask].value_counts().index[0]
    return None


def main():
    out = {}
    for short in MISSING:
        d = CACHE / short
        if not d.exists():
            print(f"  {short}  DIR MISSING")
            continue
        full = scan_for_full(short, d)
        out[short] = full
        print(f"  {short}  -> {full}")

    p = CACHE / "_missing_resolved.json"
    p.write_text(json.dumps(out, indent=2))
    print(f"Dumped: {p}")


if __name__ == "__main__":
    main()
