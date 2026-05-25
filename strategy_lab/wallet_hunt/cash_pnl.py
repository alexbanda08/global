"""Canonical cash-PnL aggregator for Polymarket wallets.

THIS MODULE NOW EXPOSES TWO IMPLEMENTATIONS:

1. cash_pnl(activity_df, positions_df=None)  ← **CANONICAL, USE THIS**
   Type-based dispatch over Polymarket's /activity tape.
   Sums TRADE / REDEEM / MERGE / MAKER_REBATE / REWARD / REFERRAL_REWARD /
   YIELD / CONVERSION / WITHDRAWAL as cash inflows, SPLIT / DEPOSIT as
   outflows, and TRADE as buys (outflow) + sells (inflow).
   Matches lb-api /profit?window=all within ~1 %.

2. cash_pnl_legacy_alchemy(short, full_wallet=None)
   The OLD Alchemy-asset-transfers reconstruction. Kept for back-compat
   for any caller that still expects {short, n_usdc_transfers, net_cash_pnl, ...}.
   Known under-reports lifetime PnL by 100 %+ for hold-to-expiry strategies
   because Alchemy's USDC stream doesn't surface server-side REDEEM aggregations.

WHY THE FIX MATTERS
===================
The chain-based reconstruction filtered activity events on `side ∈ {BUY,SELL}`
and silently dropped every event with `side=""` (REDEEM, MERGE, MAKER_REBATE,
CONVERSION, REWARD). For hold-to-expiry maker strategies, REDEEM is 80-90 % of
cash income. Dropping it flipped the sign on every profitable wallet.

Reference verification:
    See migration_ireland_shadow_2026_05_21/portfolio_audit/PORTFOLIO_AUDIT_REPORT.md
    6 wallets audited: each reported +$49k to +$825k by lb-api `/profit?window=all`;
    Alchemy decoder reported them as net-negative.

See also: strategy_lab/reports/WALLET_DECODER_FIX_SPEC_2026_05_21.md
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).resolve().parent / "cache"


# ===========================================================================
# CANONICAL PnL (Fix #1)
# ===========================================================================

# Income types: each row's `usdcSize` is added to realized PnL.
INCOME_TYPES = (
    "REDEEM",           # winner-share redemption at $1
    "MERGE",            # pair claim at $1 via NegRiskAdapter
    "MAKER_REBATE",     # liquidity rebate
    "REWARD",           # liquidity / volume reward
    "REFERRAL_REWARD",
    "YIELD",
    "CONVERSION",       # NegRisk yes+no → USDC conversion (note: API uses
                        # CONVERSION, not CONVERT — Fix #4)
    "WITHDRAWAL",       # user pulling USDC out is income from PM's books
)

# Outflow types: subtracted from realized PnL.
OUTFLOW_TYPES = (
    "SPLIT",            # USDC consumed to mint a yes+no pair
    "DEPOSIT",          # user pushing USDC in
)


def cash_pnl(activity_df: pd.DataFrame,
              positions_df: pd.DataFrame | None = None) -> dict:
    """Realized + unrealized PnL from a Polymarket /activity tape.

    Realized cash:
        + TRADE sells
        - TRADE buys
        + REDEEM, MERGE, MAKER_REBATE, REWARD, REFERRAL_REWARD, YIELD, CONVERSION, WITHDRAWAL
        - SPLIT, DEPOSIT
    Unrealized: sum of `currentValue` over open positions (positions_df).

    Args:
        activity_df: flat DataFrame with columns ['type', 'side', 'usdcSize', ...].
            Get this from `polymarket_api.activity_to_df(...)`.
        positions_df: open positions DataFrame; needs `currentValue` column.

    Returns:
        dict {realized, unrealized, total, breakdown} where `breakdown` is
        per-event-type $ sums (signed).
    """
    if activity_df is None or len(activity_df) == 0:
        return {"realized": 0.0, "unrealized": 0.0, "total": 0.0, "breakdown": {}}

    df = activity_df.copy()
    if "usdcSize" not in df.columns:
        # Tolerate missing column — treat as zero
        df["usdcSize"] = 0.0
    df["usdcSize"] = pd.to_numeric(df["usdcSize"], errors="coerce").fillna(0.0)
    if "type" not in df.columns:
        return {"realized": 0.0, "unrealized": 0.0, "total": 0.0,
                "breakdown": {"_err": "no 'type' column"}}
    if "side" not in df.columns:
        df["side"] = ""

    breakdown: dict[str, float] = {}
    realized = 0.0

    # ---- TRADE ----
    trades = df[df["type"] == "TRADE"]
    side_upper = trades["side"].astype(str).str.upper()
    buys = float(trades.loc[side_upper == "BUY", "usdcSize"].sum())
    sells = float(trades.loc[side_upper == "SELL", "usdcSize"].sum())
    realized -= buys
    realized += sells
    breakdown["TRADE_buys"] = round(buys, 4)
    breakdown["TRADE_sells"] = round(sells, 4)
    breakdown["TRADE_net"] = round(sells - buys, 4)

    # ---- INCOME ----
    for t in INCOME_TYPES:
        s = float(df.loc[df["type"] == t, "usdcSize"].sum())
        realized += s
        breakdown[t] = round(s, 4)

    # ---- OUTFLOW ----
    for t in OUTFLOW_TYPES:
        s = float(df.loc[df["type"] == t, "usdcSize"].sum())
        realized -= s
        breakdown[t] = round(-s, 4)  # signed view

    # ---- UNREALIZED ----
    unrealized = 0.0
    if positions_df is not None and len(positions_df):
        if "currentValue" in positions_df.columns:
            unrealized = float(
                pd.to_numeric(positions_df["currentValue"], errors="coerce").sum()
            )

    return {
        "realized": round(realized, 4),
        "unrealized": round(unrealized, 4),
        "total": round(realized + unrealized, 4),
        "breakdown": breakdown,
    }


def maker_rebate_share(activity_df: pd.DataFrame) -> float:
    """Fraction of cash INCOME that comes from MAKER_REBATE events.

    Per spec Fix #3: wallets with maker_rebate_share > 0.05 are confirmed
    makers (post resting orders). Wallets with < 0.001 are likely pure takers.
    """
    if activity_df is None or len(activity_df) == 0 or "type" not in activity_df.columns:
        return 0.0
    df = activity_df.copy()
    df["usdcSize"] = pd.to_numeric(df.get("usdcSize", 0.0), errors="coerce").fillna(0.0)
    income_total = 0.0
    for t in INCOME_TYPES:
        income_total += float(df.loc[df["type"] == t, "usdcSize"].sum())
    rebate = float(df.loc[df["type"] == "MAKER_REBATE", "usdcSize"].sum())
    if income_total <= 0:
        return 0.0
    return float(rebate / income_total)


# ===========================================================================
# LEGACY: Alchemy-asset-transfer reconstruction (under-reports REDEEM)
# ===========================================================================

# Known Polymarket exchange / matcher contracts on Polygon
EXCHANGE_ADDRS = {
    "0xe111180000d2663c0091e4f400237545b87b996b",  # NegRisk matcher
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",  # CTFExchange (old)
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",  # NegRiskCtfExchange
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",  # CTF / ConditionalTokens
    "0xc8c4db15e07d0f30558eaab922bf2631550a266e",  # NegRisk adapter
    "0x0000000000000000000000000000000000000000",  # mint/burn via CTF token
}

WALLETS_LEGACY = [
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


def cash_pnl_legacy_alchemy(short: str, full_wallet: str | None = None) -> dict:
    """LEGACY Alchemy-asset-transfers reconstruction.

    Kept for back-compat. Known to under-report by ~100 % on hold-to-expiry
    strategies because the USDC flow doesn't surface server-side aggregations
    (REDEEM proceeds are credited via the CTF contract; this scanner sees them
    as a USDC transfer but lumps them into 'trading_in' without sign-aware
    treatment of the resolution-vs-trade distinction). Prefer `cash_pnl()`.
    """
    p = CACHE / short / "alchemy_transfers.parquet"
    if not p.exists():
        return {"short": short, "error": "no transfers file"}
    df = pd.read_parquet(p)
    USDC_ASSETS = {"pUSD", "USDCE", "USDC", "USDT", "USDC.e",
                    "USDC.E", "PUSD"}  # add upper-case variants seen in cache
    u = df[df.asset.isin(USDC_ASSETS)].copy()
    if u.empty:
        return {"short": short,
                "error": f"no USDC transfers "
                         f"(assets seen: {df.asset.value_counts().head(3).to_dict()})"}
    u["ts_dt"] = pd.to_datetime(u.ts, errors="coerce", utc=True)
    u["day"] = u.ts_dt.dt.date
    u["counterparty"] = u.apply(
        lambda r: r["to"] if r.direction == "from" else r["from"], axis=1
    )
    u["counterparty"] = u.counterparty.str.lower()
    u["is_exchange"] = u.counterparty.isin(EXCHANGE_ADDRS)

    trading = u[u.is_exchange]
    cap = u[~u.is_exchange]
    trading_in = trading[trading.direction == "to"].value.sum()
    trading_out = trading[trading.direction == "from"].value.sum()
    cap_in = cap[cap.direction == "to"].value.sum()
    cap_out = cap[cap.direction == "from"].value.sum()

    if full_wallet:
        pos = refresh_positions(full_wallet)
    else:
        pp = CACHE / short / "positions.parquet"
        pos = pd.read_parquet(pp) if pp.exists() else pd.DataFrame()
    if not pos.empty and "currentValue" in pos.columns:
        open_value = pd.to_numeric(pos.currentValue, errors="coerce").sum()
        n_open = len(pos)
    else:
        open_value = 0
        n_open = 0

    net_cash = (trading_in - trading_out) + (cap_in - cap_out)
    out = {
        "short": short,
        "n_usdc_transfers": len(u),
        "time_first": str(u.ts_dt.min()),
        "time_last": str(u.ts_dt.max()),
        "span_days": round(
            (u.ts_dt.max() - u.ts_dt.min()).total_seconds() / 86400, 2
        ) if not u.ts_dt.isna().all() else 0,
        "trading_in":  round(trading_in, 2),
        "trading_out": round(trading_out, 2),
        "net_trading_pnl": round(trading_in - trading_out, 2),
        "capital_in":  round(cap_in, 2),
        "capital_out": round(cap_out, 2),
        "net_capital": round(cap_in - cap_out, 2),
        "net_cash_pnl": round(net_cash, 2),
        "n_open_positions": int(n_open),
        "open_position_value": round(float(open_value), 2),
        "total_pnl": round(net_cash + float(open_value), 2),
    }
    if out["span_days"] > 0:
        out["total_pnl_per_day"] = round(out["total_pnl"] / out["span_days"], 2)
    return out


# Back-compat alias for the prior name in this module.
analyze_wallet = cash_pnl_legacy_alchemy


# ===========================================================================
# CLI: re-run the canonical cash_pnl over all wallets with a /pm_portfolio cache
# ===========================================================================

def _resolve_full_address(short: str) -> str | None:
    """Try to resolve a short prefix to a full address from local artifacts."""
    # 1. lb_api_canonical's ADDR_MAP
    try:
        from lb_api_canonical import ADDR_MAP
        if short in ADDR_MAP:
            return ADDR_MAP[short]
    except Exception:
        pass
    # 2. _addr_map.json
    p = CACHE / "_addr_map.json"
    if p.exists():
        try:
            mp = json.loads(p.read_text())
            if short in mp:
                return mp[short]
        except Exception:
            pass
    # 3. trades.parquet in the per-wallet cache (has proxyWallet)
    tp = CACHE / short / "trades.parquet"
    if tp.exists():
        try:
            t = pd.read_parquet(tp)
            if "proxyWallet" in t.columns and len(t):
                return str(t.iloc[0].proxyWallet).lower()
        except Exception:
            pass
    return None


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from polymarket_api import (
        fetch_lb_profit, fetch_activity, fetch_positions,
        activity_to_df, positions_to_df, lb_amount,
    )

    ap = argparse.ArgumentParser()
    ap.add_argument("--wallet", action="append",
                    help="short prefix or full address; repeat for multi-wallet")
    ap.add_argument("--all", action="store_true",
                    help="run on every wallet with a per-wallet cache dir")
    ap.add_argument("--no-cache", action="store_true",
                    help="bypass on-disk cache (re-pull from API)")
    args = ap.parse_args()

    use_cache = not args.no_cache

    if args.all:
        shorts = [d.name for d in CACHE.glob("0x*") if d.is_dir()]
    elif args.wallet:
        shorts = []
        for w in args.wallet:
            shorts.append(w.lower()[:10] if w.startswith("0x") else w)
    else:
        shorts = WALLETS_LEGACY

    rows = []
    for short in shorts:
        full = _resolve_full_address(short)
        if not full:
            print(f"{short}: no full-address mapping; skipping")
            continue
        lb = fetch_lb_profit(full, use_cache=use_cache)
        act = fetch_activity(full, use_cache=use_cache)
        positions_payload = fetch_positions(full, use_cache=use_cache)
        df_act = activity_to_df(act)
        df_pos = positions_to_df(positions_payload)
        result = cash_pnl(df_act, positions_df=df_pos)
        rebate_pct = maker_rebate_share(df_act)

        lb_all = lb_amount(lb, "all")
        gap = (result["realized"] - (lb_all or 0)) if lb_all is not None else None
        gap_pct = (gap / lb_all * 100) if lb_all not in (None, 0) else None

        rows.append({
            "short": short,
            "full": full,
            "lb_profit_all": lb_all,
            "cash_pnl_realized": result["realized"],
            "cash_pnl_unrealized": result["unrealized"],
            "cash_pnl_total": result["total"],
            "gap_vs_lb_all": gap,
            "gap_pct_of_lb_all": round(gap_pct, 2) if gap_pct is not None else None,
            "maker_rebate_share": round(rebate_pct, 4),
        })
        print(f"{short}: lb=${lb_all}  cash_pnl=${result['realized']}  "
              f"gap_pct={'-' if gap_pct is None else round(gap_pct,1)}%  "
              f"rebate_share={rebate_pct:.4f}")

    df = pd.DataFrame(rows)
    out_csv = CACHE / "_cash_pnl_summary.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nsaved -> {out_csv}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
