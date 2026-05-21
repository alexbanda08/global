"""
DEPRECATED FEE MODEL — DO NOT QUOTE PnL FROM THIS FILE FORWARD.

This file uses the legacy `FEE_RATE = 0.02` ("2% on profit only, winning leg")
approximation. The real Polymarket fee is:

    fee = C × feeRate × p × (1 − p)

charged on EVERY fill (not just the winner). For crypto markets feeRate = 0.07.
Use `strategy_lab/fees.py` (`poly_fee_usd`, `poly_maker_rebate_usd`) instead.

Kept here for historical reproducibility only. Numbers produced by this file
diverge materially from real Polymarket settlements — re-run via
`engine_v2.fill_at_book` + `fees.poly_fee_usd` before any decision.
"""

"""Partial-fill HEDGE/SELL backtest on the same 851 live momo v1+v2 trades.

Hypothesis: production may require FULL position liquidity at exit time. Partial
fills on HEDGE/SELL would recover real PnL even when liquidity is thin.

This backtest:
  - Allows HEDGE to fill any positive shares_h (not just shares_h >= shares_e * 0.95)
  - Allows SELL to liquidate any positive shares_sold; remainder settles via chainlink
  - Compares to actual production exit_reason (hold/hedge/sell)

Inputs:
  data/v4/shadow_trades_2026_05_08/momo_v1v2_live.csv          -- 851 prod resolutions
  data/v4/shadow_trades_2026_05_08/vps2_l25_{btc,eth,sol}.csv  -- L25 books
  data/v4/shadow_trades_2026_05_08/vps2_klines_1m.csv          -- 1m klines

Output:
  data/v4/shadow_trades_2026_05_08/momo_partial_fill_per_trade.csv
  strategy_lab/reports/MOMO_PARTIAL_FILL_BACKTEST_2026_05_09.md
"""
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
from book_walk import book_walk_fill  # noqa: E402

DIR = ROOT / "data/v4/shadow_trades_2026_05_08"
OUT_CSV = DIR / "momo_partial_fill_per_trade.csv"
REPORT = ROOT / "strategy_lab/reports/MOMO_PARTIAL_FILL_BACKTEST_2026_05_09.md"

LEVELS = 25
NOTIONAL = 25.0
FEE = 0.02
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
REV_BP = 5.0
TICK_S = 10
ASSET_BIN = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
ASSET_OKX = {"BTC": "OKX_SPOT_BTC_USDT", "ETH": "OKX_SPOT_ETH_USDT", "SOL": "OKX_SPOT_SOL_USDT"}


def asof_strict(k: pd.DataFrame, ts_s: int) -> float:
    end_us = (k.ts_s.values + 60) * 1_000_000
    target = int(ts_s) * 1_000_000
    idx = int(np.searchsorted(end_us, target, side="right")) - 1
    return float("nan") if idx < 0 else float(k.price_close.iloc[idx])


def load_klines() -> dict:
    df = pd.read_csv(DIR / "vps2_klines_1m.csv")
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for a in ("BTC", "ETH", "SOL"):
        b = df[df.symbol_id == ASSET_BIN[a]][["ts_s", "price_close"]].copy(); b["src"] = "b"
        o = df[df.symbol_id == ASSET_OKX[a]][["ts_s", "price_close"]].copy(); o["src"] = "o"
        c = pd.concat([b, o]).sort_values(["ts_s", "src"]).drop_duplicates("ts_s", keep="first").sort_values("ts_s").reset_index(drop=True)
        out[a] = c[["ts_s", "price_close"]]
    return out


def load_l25_keyed(asset: str) -> tuple[dict, dict]:
    """Returns (books, mid2slug). books[(mid, outcome)] = (ts_us[N], ap[N,25], as[N,25], bp[N,25], bs[N,25]).

    Loads in chunks per (mid, outcome) to keep memory bounded.
    """
    path = DIR / f"vps2_l25_{asset.lower()}.csv"
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_as = [f"ask_size_{i}" for i in range(LEVELS)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS)]
    cols_bs = [f"bid_size_{i}" for i in range(LEVELS)]
    keep = ["timestamp_us", "slug", "market_id", "outcome"] + cols_ap + cols_as + cols_bp + cols_bs

    chunks = []
    for chunk in pd.read_csv(path, usecols=keep, chunksize=100_000, low_memory=False):
        chunks.append(chunk)
    df = pd.concat(chunks, ignore_index=True)
    print(f"    {asset} loaded {len(df)} rows; building index...")

    out: dict = {}
    mid2slug: dict = {}
    df = df.sort_values(["market_id", "outcome", "timestamp_us"]).reset_index(drop=True)
    for (mid, oc), sub in df.groupby(["market_id", "outcome"], sort=False):
        ts = sub.timestamp_us.values.astype("int64")
        ap = sub[cols_ap].to_numpy(dtype=np.float32)
        as_ = sub[cols_as].to_numpy(dtype=np.float32)
        bp = sub[cols_bp].to_numpy(dtype=np.float32)
        bs = sub[cols_bs].to_numpy(dtype=np.float32)
        out[(mid, oc)] = (ts, ap, as_, bp, bs)
        mid2slug.setdefault(mid, sub.slug.iloc[0])
    del df, chunks
    return out, mid2slug


def find_book_l25(idx, mid, outcome, target_us, max_dt_us=10_000_000):
    """Returns (ap[25], as[25], bp[25], bs[25], dt_us) or None."""
    rec = idx.get((mid, outcome))
    if rec is None:
        return None
    ts, ap, as_, bp, bs = rec
    if len(ts) == 0:
        return None
    pos = int(np.searchsorted(ts, target_us))
    candidates = []
    if pos > 0: candidates.append(pos - 1)
    if pos < len(ts): candidates.append(pos)
    best_i, best_dt = None, float("inf")
    for i in candidates:
        dt = abs(int(ts[i]) - target_us)
        if dt < best_dt:
            best_dt, best_i = dt, i
    if best_i is None or best_dt > max_dt_us:
        return None
    return ap[best_i], as_[best_i], bp[best_i], bs[best_i], best_dt


def sell_at_bid_partial(bid_p, bid_s, shares):
    """Walk bids descending. Return (vwap, shares_sold, usd_received). Always partial-friendly."""
    remaining = float(shares); total_usd = 0.0; total_shares = 0.0
    for p, s in zip(bid_p, bid_s):
        p = float(p); s = float(s)
        if not (math.isfinite(p) and math.isfinite(s)) or s <= 0 or p <= 0 or p >= 1:
            break
        if s >= remaining:
            total_usd += remaining * p; total_shares += remaining; remaining = 0; break
        total_usd += s * p; total_shares += s; remaining -= s
    if total_shares <= 0:
        return 0.0, 0.0, 0.0
    return total_usd / total_shares, total_shares, total_usd


SLEEVE_RE = re.compile(r"^poly_updown_(btc|eth|sol)_(5m|15m)_momo(_v2)?_(HOLD|HEDGE|SELL)$")


def parse_sleeve(sleeve_id: str):
    m = SLEEVE_RE.match(sleeve_id)
    if not m:
        return None
    return m.group(1).upper(), m.group(2), m.group(3) == "_v2", m.group(4)


def simulate_partial(
    r,
    klines,
    books,
    policy: str,
    require_full: bool,
):
    """Simulate a single trade with the given exit policy.

    require_full=True  → mirror current production: HEDGE skips if shares_h < shares_e * 0.95
                                                      SELL skips if shares_s < shares_e * 0.95
    require_full=False → partial-fill: accept any positive fill, settle remainder at chainlink
    """
    asset = r["asset"]
    held = "Up" if r["signal"] == "UP" else "Down"
    other = "Down" if r["signal"] == "UP" else "Up"
    idx = books[asset]
    mid = r["condition_id"]

    # Replay entry walk
    entry_book = find_book_l25(idx, mid, held, int(r["fire_us"]))
    if entry_book is None:
        return None
    ap_e, as_e, bp_e, bs_e, _ = entry_book
    ask0 = float(ap_e[0]) if math.isfinite(ap_e[0]) else float("nan")
    bid0 = float(bp_e[0]) if math.isfinite(bp_e[0]) else float("nan")
    if math.isfinite(ask0) and math.isfinite(bid0) and (ask0 - bid0) > SPREAD_FILTER[asset]:
        return None
    vwap_e, shares_e, usd_e, _, under = book_walk_fill(
        [float(x) for x in ap_e], [float(x) for x in as_e], NOTIONAL
    )
    if shares_e <= 0:
        return None
    if under and usd_e < NOTIONAL * 0.5:
        return None

    won = (r["signal"] == "UP" and r["outcome"] == "Up") or (r["signal"] == "DOWN" and r["outcome"] == "Down")

    # HOLD → settle at resolution
    def hold_pnl():
        if won:
            profit = shares_e * 1.0 - usd_e
            return profit - (profit * FEE if profit > 0 else 0.0)
        return -usd_e

    if policy == "HOLD":
        return dict(exit_reason="hold", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                    shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0, pnl=hold_pnl())

    # rev_bp anchor = BTC@ws
    asset_at_ws = asof_strict(klines[asset], int(r["ws"]))
    if not math.isfinite(asset_at_ws) or asset_at_ws <= 0:
        return dict(exit_reason="hold_no_anchor", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                    shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0, pnl=hold_pnl())

    # Walk ticks for rev_bp gate
    fire_us = int(r["fire_us"])
    resolve_us = int(r["resolve_us"])
    t_us = fire_us + TICK_S * 1_000_000
    triggered_at = None
    while t_us <= resolve_us:
        a_now = asof_strict(klines[asset], t_us // 1_000_000)
        if math.isfinite(a_now):
            rev_bp = (a_now - asset_at_ws) / asset_at_ws * 1e4
            if (r["signal"] == "UP" and rev_bp <= -REV_BP) or \
               (r["signal"] == "DOWN" and rev_bp >= REV_BP):
                triggered_at = t_us
                break
        t_us += TICK_S * 1_000_000

    if triggered_at is None:
        return dict(exit_reason="hold_no_trigger", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                    shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0, pnl=hold_pnl())

    # rev_bp triggered → try the exit policy
    if policy == "HEDGE":
        opp = find_book_l25(idx, mid, other, triggered_at)
        if opp is None:
            return dict(exit_reason="hold_no_opp_book", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                        shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0, pnl=hold_pnl())
        ap_o, as_o, _, _, _ = opp
        top_ask = float(ap_o[0]) if math.isfinite(ap_o[0]) else float("nan")
        if not (math.isfinite(top_ask) and 0 < top_ask < 1):
            return dict(exit_reason="hold_zero_top_ask", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                        shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0, pnl=hold_pnl())
        # target hedge shares = shares_e (so a winning hedge offsets the losing entry exactly)
        target_h_usd = shares_e * top_ask
        vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(
            [float(x) for x in ap_o], [float(x) for x in as_o], target_h_usd
        )
        if shares_h <= 0:
            return dict(exit_reason="hold_no_h_shares", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                        shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0, pnl=hold_pnl())
        if require_full and shares_h < shares_e * 0.95:
            # Production-like: skip if can't fully cover
            return dict(exit_reason="hold_partial_skipped", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                        shares_filled=shares_h, vwap_exit=vwap_h, usd_exit=usd_h, pnl=hold_pnl())
        # Compute hedged PnL (partial-friendly):
        #   - Held side (shares_e): settles at $1 if won, $0 if lost
        #   - Hedged side (shares_h on opposite outcome): settles at $1 if WE LOST, $0 if WE WON
        #   - Cost: usd_e + usd_h
        hedge_won = not won  # opposite side wins iff held lost
        held_gross = shares_e * 1.0 if won else 0.0
        hedge_gross = shares_h * 1.0 if hedge_won else 0.0
        gross = held_gross + hedge_gross
        cost = usd_e + usd_h
        profit = gross - cost
        fee = profit * FEE if profit > 0 else 0.0
        pnl = profit - fee
        return dict(exit_reason="hedge", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                    shares_filled=shares_h, vwap_exit=vwap_h, usd_exit=usd_h, pnl=pnl)

    if policy == "SELL":
        own = find_book_l25(idx, mid, held, triggered_at)
        if own is None:
            return dict(exit_reason="hold_no_own_book", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                        shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0, pnl=hold_pnl())
        _, _, bp_o, bs_o, _ = own
        vwap_s, shares_s, gross_s = sell_at_bid_partial(bp_o, bs_o, shares_e)
        if shares_s <= 0:
            return dict(exit_reason="hold_no_bid_shares", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                        shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0, pnl=hold_pnl())
        if require_full and shares_s < shares_e * 0.95:
            return dict(exit_reason="hold_partial_skipped", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                        shares_filled=shares_s, vwap_exit=vwap_s, usd_exit=gross_s, pnl=hold_pnl())
        # Partial-friendly SELL:
        #   - Sold shares: gross_s USD received NOW
        #   - Remainder (shares_e - shares_s): settles at chainlink ($1 if won, $0 if lost)
        remainder = shares_e - shares_s
        remainder_gross = remainder * 1.0 if won else 0.0
        gross = gross_s + remainder_gross
        cost = usd_e
        profit = gross - cost
        fee = profit * FEE if profit > 0 else 0.0
        pnl = profit - fee
        return dict(exit_reason="sell", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                    shares_filled=shares_s, vwap_exit=vwap_s, usd_exit=gross_s, pnl=pnl)

    return None


def main():
    print("[1] load klines + L25 books (one asset at a time to bound memory)...")
    klines = load_klines()
    print(f"    klines: BTC={len(klines['BTC'])}, ETH={len(klines['ETH'])}, SOL={len(klines['SOL'])}")

    print("[2] read live trades...")
    live = pd.read_csv(DIR / "momo_v1v2_live.csv")

    # Pre-load BTC/ETH/SOL one at a time
    print("[3] loading L25 per asset...")
    books_per_asset = {}
    mid2slug_total: dict = {}
    for a in ("BTC", "ETH", "SOL"):
        bks, mid2slug = load_l25_keyed(a)
        books_per_asset[a] = bks
        mid2slug_total.update(mid2slug)
        n_keys = len(bks)
        n_snaps = sum(len(rec[0]) for rec in bks.values())
        print(f"    {a}: {n_keys} (mid,outcome) keys, {n_snaps:,} L25 snapshots")

    # Build per-trade context
    live["slug"] = live.condition_id.map(mid2slug_total)
    live = live.dropna(subset=["slug"]).copy()
    live["ws"] = live.slug.str.extract(r"-(\d+)$")[0].astype("int64")
    parsed = live.sleeve_id.apply(parse_sleeve)
    live["asset"] = parsed.apply(lambda x: x[0] if x else None)
    live["tf"] = parsed.apply(lambda x: x[1] if x else None)
    live["is_v2"] = parsed.apply(lambda x: x[2] if x else False)
    live["policy_tag"] = parsed.apply(lambda x: x[3] if x else None)
    live = live.dropna(subset=["asset"])
    live["window_s"] = live.tf.map({"5m": 300, "15m": 900})
    live["fire_offset_s"] = live.is_v2.map({True: 60, False: 120})
    live["fire_us"] = (live.ws.astype("int64") + live.fire_offset_s.astype("int64")) * 1_000_000
    live["resolve_us"] = (live.ws.astype("int64") + live.window_s.astype("int64") - 60) * 1_000_000

    print(f"    parseable: {len(live)} rows")

    # Production actual exit
    live["prod_hedged"] = live.hedged.astype(str).str.lower() == "true"
    live["prod_partial_bid"] = live.partial_bid_exit.astype(str).str.lower() == "true"
    live["prod_actual_exit"] = np.where(
        live.prod_hedged, "hedge",
        np.where(live.prod_partial_bid, "sell", "hold")
    )

    print("[4] simulating PARTIAL-FILL backtest for HEDGE/SELL...")
    rows = []
    for r in live.to_dict("records"):
        # Run all three policies for the same trade.
        # Production already chose ONE per sleeve_id (from policy_tag); we run all 3
        # to A/B compare what each would have done at THIS market moment.
        for policy in ("HOLD", "HEDGE", "SELL"):
            for require_full in (True, False):
                if policy == "HOLD" and require_full:
                    continue  # HOLD has no fill requirement
                res = simulate_partial(r, klines, books_per_asset, policy, require_full)
                if res is None:
                    continue
                rows.append({
                    **{k: r[k] for k in ("sleeve_id", "ws", "asset", "tf", "is_v2",
                                         "policy_tag", "signal", "outcome", "pnl_usd",
                                         "prod_actual_exit")},
                    "bt_policy": policy,
                    "bt_require_full": require_full,
                    **res,
                })
        # HOLD only once
    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False)
    print(f"    wrote {len(df)} rows -> {OUT_CSV.name}")

    # Aggregate
    print("\n=== Total PnL across all 851 markets, by policy + require_full ===")
    pivot = df[df.bt_policy != "HOLD"].groupby(["bt_policy", "bt_require_full"]).agg(
        n=("pnl", "size"),
        n_fired=("exit_reason", lambda s: (~s.str.startswith("hold")).sum()),
        pnl_total=("pnl", "sum"),
        pnl_mean=("pnl", "mean"),
    ).round(2)
    print(pivot.to_string())

    # HOLD baseline (single)
    hold = df[df.bt_policy == "HOLD"]
    print(f"\nHOLD baseline (n={len(hold)}): pnl_total=${hold.pnl.sum():.2f}, mean=${hold.pnl.mean():.4f}")

    # Per-cell view: partial-friendly HEDGE vs require-full HEDGE vs production
    print("\n=== Per-cell pnl_total (HEDGE policy) ===")
    sub = df[df.bt_policy == "HEDGE"]
    pcell = sub.groupby(["asset", "tf", "is_v2", "bt_require_full"]).pnl.sum().unstack().round(0)
    pcell.columns = ["partial_friendly" if c is False else "require_full" for c in pcell.columns]
    print(pcell.to_string())

    print("\n=== Per-cell pnl_total (SELL policy) ===")
    sub = df[df.bt_policy == "SELL"]
    pcell = sub.groupby(["asset", "tf", "is_v2", "bt_require_full"]).pnl.sum().unstack().round(0)
    pcell.columns = ["partial_friendly" if c is False else "require_full" for c in pcell.columns]
    print(pcell.to_string())

    # Fire-rate breakdown
    print("\n=== Fire rate (HEDGE/SELL) under partial-friendly vs require-full ===")
    sub = df[df.bt_policy.isin(("HEDGE", "SELL"))]
    fr = sub.groupby(["bt_policy", "bt_require_full"]).agg(
        n=("exit_reason", "size"),
        n_exited=("exit_reason", lambda s: s.isin(("hedge", "sell")).sum()),
    )
    fr["fire_rate_%"] = (fr.n_exited / fr.n * 100).round(1)
    print(fr.to_string())

    # Diagnose: cases where partial fires but require_full doesn't
    print("\n=== Cases where partial-fill fires but require-full skips ===")
    pivot_diff = df[df.bt_policy.isin(("HEDGE", "SELL"))].pivot_table(
        index=["sleeve_id", "ws"], columns="bt_require_full", values="exit_reason", aggfunc="first"
    )
    pivot_diff.columns = ["partial", "require_full"]
    diff = pivot_diff[(pivot_diff.partial.isin(("hedge", "sell"))) &
                      (pivot_diff.require_full.str.startswith("hold"))]
    print(f"  count: {len(diff)}")
    if len(diff):
        print("  Sample (first 10):")
        print(diff.head(10))


if __name__ == "__main__":
    main()
