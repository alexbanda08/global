"""Cash-PnL analyzer using Alchemy asset transfers + open-position value.

For each wallet:
  net_trading_pnl = USDC received from exchange contracts -
                    USDC sent to exchange contracts
  net_capital_flow = USDC received from EOAs (deposits) -
                     USDC sent to EOAs (withdrawals)
  open_position_value = sum of currentValue across all open positions
                        (includes UNREDEEMED winning tokens — important!)

Total PnL = net_trading + net_capital + open_position_value

Open positions matter because:
  - Wallets often hold large bags of unresolved tokens (live markets)
  - Wallets also hold WINNING tokens they haven't claimed yet
    (redeemable=True with $1 curPrice)
  - Without these, the cash-flow PnL understates true profit
"""
from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

CACHE = Path(__file__).resolve().parent / "cache"

# Known Polymarket exchange / matcher contracts on Polygon
EXCHANGE_ADDRS = {
    "0xe111180000d2663c0091e4f400237545b87b996b",  # NegRisk matcher
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",  # CTFExchange (old)
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",  # NegRiskCtfExchange
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",  # CTF / ConditionalTokens
    "0xc8c4db15e07d0f30558eaab922bf2631550a266e",  # NegRisk adapter
    # Zero address = mint/burn events on the CTF token. USDC coming FROM 0x0
    # is a CTF redemption (winning pair burned, USDC released). USDC sent TO 0x0
    # is a CTF mint (USDC locked, Up+Down pair issued).
    "0x0000000000000000000000000000000000000000",
}

WALLETS = [
    "0xeebde7a0",
    "0xce25e214",
    "0x89b5cdaa",
    "0x7cde1da9",
    "0xcfb103c3",
    "0x04b6d7e9",
]


def refresh_positions(wallet: str) -> pd.DataFrame:
    """Pull fresh open positions from Polymarket data-api."""
    UA = {"User-Agent": "global-strategy-lab/1.0", "Accept": "application/json"}
    url = f"https://data-api.polymarket.com/positions?user={wallet}"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
        if data:
            return pd.DataFrame(data)
    except Exception as e:
        print(f"  positions refresh failed: {e}")
    return pd.DataFrame()


def analyze_wallet(short: str, full_wallet: str | None = None) -> dict:
    p = CACHE / short / "alchemy_transfers.parquet"
    if not p.exists():
        return {"short": short, "error": "no transfers file"}
    df = pd.read_parquet(p)
    # Polymarket USDC variants: pUSD (wrapped, used by exchange), USDCE (USDC.e on Polygon),
    # USDC (native), USDT (occasionally). All ~$1.
    USDC_ASSETS = {"pUSD", "USDCE", "USDC", "USDT", "USDC.e"}
    u = df[df.asset.isin(USDC_ASSETS)].copy()
    if u.empty:
        return {"short": short, "error": f"no USDC transfers (assets seen: {df.asset.value_counts().head(3).to_dict()})"}

    u["ts_dt"] = pd.to_datetime(u.ts, errors="coerce", utc=True)
    u["day"] = u.ts_dt.dt.date
    u["counterparty"] = u.apply(lambda r: r["to"] if r.direction == "from" else r["from"], axis=1)
    u["counterparty"] = u.counterparty.str.lower()
    u["is_exchange"] = u.counterparty.isin(EXCHANGE_ADDRS)

    # Trading flow
    trading = u[u.is_exchange]
    cap = u[~u.is_exchange]
    trading_in = trading[trading.direction == "to"].value.sum()
    trading_out = trading[trading.direction == "from"].value.sum()
    cap_in = cap[cap.direction == "to"].value.sum()
    cap_out = cap[cap.direction == "from"].value.sum()

    # Add open-position value (refresh from data-api for latest)
    if full_wallet:
        pos = refresh_positions(full_wallet)
    else:
        pp = CACHE / short / "positions.parquet"
        pos = pd.read_parquet(pp) if pp.exists() else pd.DataFrame()
    if not pos.empty and "currentValue" in pos.columns:
        open_value = pd.to_numeric(pos.currentValue, errors="coerce").sum()
        n_open = len(pos)
        # Separate redeemable (winning, unclaimed) vs unresolved
        if "redeemable" in pos.columns and "curPrice" in pos.columns:
            cp = pd.to_numeric(pos.curPrice, errors="coerce")
            winning_unclaimed_val = pd.to_numeric(
                pos.loc[(pos.redeemable.astype(bool)) & (cp >= 0.99), "currentValue"],
                errors="coerce").sum()
            losing_pending_val = pd.to_numeric(
                pos.loc[(pos.redeemable.astype(bool)) & (cp <= 0.01), "currentValue"],
                errors="coerce").sum()
        else:
            winning_unclaimed_val = 0
            losing_pending_val = 0
    else:
        open_value = 0; n_open = 0
        winning_unclaimed_val = losing_pending_val = 0

    net_cash = (trading_in - trading_out) + (cap_in - cap_out)
    out = {
        "short": short,
        "n_usdc_transfers": len(u),
        "time_first": str(u.ts_dt.min()),
        "time_last": str(u.ts_dt.max()),
        "span_days": round((u.ts_dt.max() - u.ts_dt.min()).total_seconds() / 86400, 2)
                     if not u.ts_dt.isna().all() else 0,
        "trading_in":  round(trading_in, 2),
        "trading_out": round(trading_out, 2),
        "net_trading_pnl": round(trading_in - trading_out, 2),
        "capital_in":  round(cap_in, 2),
        "capital_out": round(cap_out, 2),
        "net_capital": round(cap_in - cap_out, 2),
        "net_cash_pnl": round(net_cash, 2),
        "n_open_positions": int(n_open),
        "open_position_value": round(float(open_value), 2),
        "winning_unclaimed_value": round(float(winning_unclaimed_val), 2),
        "total_pnl": round(net_cash + float(open_value), 2),
    }
    if out["span_days"] > 0:
        out["total_pnl_per_day"] = round(out["total_pnl"] / out["span_days"], 2)

    # Daily PnL
    daily = trading.groupby(["day", "direction"]).value.sum().unstack(fill_value=0)
    if "to" in daily.columns and "from" in daily.columns:
        daily["net"] = daily["to"] - daily["from"]
        out["pnl_per_day"] = round(daily.net.mean(), 2)
        out["pnl_best_day"] = round(daily.net.max(), 2)
        out["pnl_worst_day"] = round(daily.net.min(), 2)
        out["n_days_positive"] = int((daily.net > 0).sum())
        out["n_days_negative"] = int((daily.net < 0).sum())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", action="append", help="short prefix like 0x89b5cdaa")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.all:
        shorts = [d.name for d in CACHE.glob("0x*") if d.is_dir()
                   and (d / "alchemy_transfers.parquet").exists()]
    elif args.wallet:
        shorts = [w[:10] for w in args.wallet]
    else:
        shorts = WALLETS

    # Build short → full address map (using existing trades.parquet if present)
    short_to_full = {}
    for short in shorts:
        tp = CACHE / short / "trades.parquet"
        if tp.exists():
            t = pd.read_parquet(tp)
            if "proxyWallet" in t.columns and len(t):
                short_to_full[short] = str(t.iloc[0].proxyWallet).lower()

    rows = []
    for s in shorts:
        try:
            r = analyze_wallet(s, full_wallet=short_to_full.get(s))
        except Exception as e:
            import traceback; traceback.print_exc()
            r = {"short": s, "error": str(e)[:60]}
        rows.append(r)

    df = pd.DataFrame(rows)
    df.to_csv(CACHE / "_cash_pnl_summary.csv", index=False)
    print(f"\n{'='*120}")
    print(df.to_string(index=False))
    print(f"\nsaved -> cache/_cash_pnl_summary.csv")


if __name__ == "__main__":
    main()
