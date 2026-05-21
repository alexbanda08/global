"""Find the INITIAL funding put into each cached wallet.

Uses the same exchange-counterparty classification as cash_pnl.py:
  capital flow = USDC transfers to/from non-exchange (EOA) addresses
  trading flow = USDC transfers to/from known Polymarket contracts

Per wallet, reports:
  - First capital_in (timestamp, amount, source address)
  - First trading activity timestamp
  - Cumulative capital_in deposited BEFORE first trade (= seed/initial funding)
  - Total capital_in (lifetime deposits)
  - Total capital_out (lifetime withdrawals)
  - Net capital (deposits - withdrawals)

Run:  py -3 -X utf8 strategy_lab/wallet_hunt/_initial_funding.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

CACHE = Path(__file__).resolve().parent / "cache"

# From cash_pnl.py — Polymarket on Polygon
EXCHANGE_ADDRS = {
    "0xe111180000d2663c0091e4f400237545b87b996b",  # NegRisk matcher
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",  # CTFExchange (old)
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",  # NegRiskCtfExchange
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",  # CTF / Conditional Tokens
    "0x0000000000000000000000000000000000000000",  # mint/burn → trading flow
}

USDC_ASSETS = {"pUSD", "USDCE", "USDC", "USDT", "USDC.e"}


def per_wallet(short: str) -> dict:
    p = CACHE / short / "alchemy_transfers.parquet"
    if not p.exists():
        return {"short": short, "error": "no transfers"}
    df = pd.read_parquet(p)
    if df.empty or "asset" not in df.columns:
        return {"short": short, "error": "empty transfers file"}

    u = df[df.asset.isin(USDC_ASSETS)].copy()
    if u.empty:
        # fall back: any erc20 row (some wallets may have asset=NaN or other label)
        u = df[df.category == "erc20"].copy()
        if u.empty:
            return {"short": short, "error": "no USDC/erc20"}
    u["ts_dt"] = pd.to_datetime(u.ts, errors="coerce", utc=True)
    u["counterparty"] = u.apply(
        lambda r: r["to"] if r.direction == "from" else r["from"], axis=1
    ).str.lower()
    u["is_exchange"] = u.counterparty.isin(EXCHANGE_ADDRS)

    capital = u[~u.is_exchange].copy()
    trading = u[u.is_exchange].copy()

    cap_in = capital[capital.direction == "to"].sort_values("ts_dt")
    cap_out = capital[capital.direction == "from"].sort_values("ts_dt")

    first_trade_ts = trading.ts_dt.min() if not trading.empty else None

    # Cumulative capital_in BEFORE first trade
    if first_trade_ts is not None and not cap_in.empty:
        seed_rows = cap_in[cap_in.ts_dt < first_trade_ts]
        seed_total = float(seed_rows.value.sum())
        n_seed = len(seed_rows)
        seed_first_ts = seed_rows.ts_dt.min() if not seed_rows.empty else None
        seed_first_value = float(seed_rows.iloc[0].value) if not seed_rows.empty else None
        seed_first_from = seed_rows.iloc[0]["from"] if not seed_rows.empty else None
    else:
        seed_total = float(cap_in.value.sum()) if not cap_in.empty else 0.0
        n_seed = len(cap_in)
        seed_first_ts = cap_in.ts_dt.min() if not cap_in.empty else None
        seed_first_value = float(cap_in.iloc[0].value) if not cap_in.empty else None
        seed_first_from = cap_in.iloc[0]["from"] if not cap_in.empty else None

    # Earliest observed activity at all = our scan-window floor
    earliest_seen = u.ts_dt.min()
    # If first trade timestamp is within 5 minutes of earliest_seen → seed
    # likely happened BEFORE our scan window (we missed it)
    seed_likely_pre_scan = (
        first_trade_ts is not None
        and (first_trade_ts - earliest_seen).total_seconds() < 300
        and n_seed == 0
    )

    return {
        "short": short,
        "scan_first_ts": earliest_seen,
        "first_capital_in_ts": seed_first_ts,
        "first_capital_in_usd": seed_first_value,
        "first_capital_in_from": seed_first_from,
        "first_trade_ts": first_trade_ts,
        "n_seed_deposits": n_seed,
        "seed_total_usd": round(seed_total, 2),
        "seed_likely_pre_scan": seed_likely_pre_scan,
        "lifetime_capital_in": round(float(cap_in.value.sum()), 2) if not cap_in.empty else 0.0,
        "lifetime_capital_out": round(float(cap_out.value.sum()), 2) if not cap_out.empty else 0.0,
        "net_capital": round(
            float(cap_in.value.sum()) - float(cap_out.value.sum()), 2
        ) if not cap_in.empty else 0.0,
        "n_cap_in_total": len(cap_in),
        "n_cap_out_total": len(cap_out),
        "n_usdc_transfers": len(u),
    }


def main():
    shorts = sorted(
        d.name for d in CACHE.glob("0x*")
        if d.is_dir() and (d / "alchemy_transfers.parquet").exists()
    )
    rows = [per_wallet(s) for s in shorts]
    df = pd.DataFrame(rows)

    # Order columns
    col_order = [
        "short", "seed_total_usd", "n_seed_deposits", "seed_likely_pre_scan",
        "first_capital_in_usd", "first_capital_in_ts", "first_capital_in_from",
        "scan_first_ts", "first_trade_ts",
        "lifetime_capital_in", "lifetime_capital_out", "net_capital",
        "n_cap_in_total", "n_cap_out_total", "n_usdc_transfers",
    ]
    col_order = [c for c in col_order if c in df.columns]
    df = df[col_order]

    print()
    print("=" * 130)
    print("INITIAL FUNDING per wallet (Polymarket cached caches)")
    print("=" * 130)
    print(df.to_string(index=False))
    print()
    df.to_csv(CACHE / "_initial_funding.csv", index=False)
    print(f"saved -> {CACHE / '_initial_funding.csv'}")


if __name__ == "__main__":
    main()
