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

"""Diagnose why HEDGE/SELL exits don't fire in production momo v1+v2.

For each live fill in the last 7 days, replay the exit-policy logic against
strict-asof Binance klines + L25 WS books, then compare to actual production
outcome. Decompose any gap into:
  - rev_bp gate never opened (Binance asset didn't revert)
  - rev_bp gate opened but opposite-side ask book empty (HEDGE)
  - rev_bp gate opened but own-bid book empty (SELL)
  - both fired in backtest, but at different times → different exit reason

Inputs (all in data/v4/shadow_trades_2026_05_08/):
  momo_v1v2_live.csv         -- 851 production resolutions
  vps2_l25_{btc,eth,sol}.csv -- L25 books for those markets
  vps2_klines_1m.csv         -- 1m Binance + OKX (Binance preferred)

Output:
  data/v4/shadow_trades_2026_05_08/momo_live_vs_backtest_per_trade.csv
  strategy_lab/reports/MOMO_LIVE_VS_BACKTEST_2026_05_08.md
"""
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
from book_walk import book_walk_fill  # noqa: E402

DIR = ROOT / "data/v4/shadow_trades_2026_05_08"
OUT_CSV = DIR / "momo_live_vs_backtest_per_trade.csv"
REPORT = ROOT / "strategy_lab/reports/MOMO_LIVE_VS_BACKTEST_2026_05_08.md"

LEVELS = 25
NOTIONAL = 25.0
FEE = 0.02
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
REV_BP = 5.0
TICK_S = 10
ASSET_BIN = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
ASSET_OKX = {"BTC": "OKX_SPOT_BTC_USDT", "ETH": "OKX_SPOT_ETH_USDT", "SOL": "OKX_SPOT_SOL_USDT"}


def asof_strict(k: pd.DataFrame, ts_s: int) -> float:
    """end-time-indexed asof for 1MIN bars."""
    end_us = (k.ts_s.values + 60) * 1_000_000
    target = int(ts_s) * 1_000_000
    idx = int(np.searchsorted(end_us, target, side="right")) - 1
    if idx < 0:
        return float("nan")
    return float(k.price_close.iloc[idx])


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


def load_l25(asset: str) -> dict:
    """Returns {(market_id, outcome): (ts_us[N], ask_p0[N], ask_s0[N], bid_p0[N], bid_s0[N])}.
    Diagnostic only loads L1 (level 0) — diagnoses gate + book availability, not full
    walk depth. Saves ~10x memory vs L25.
    """
    path = DIR / f"vps2_l25_{asset.lower()}.csv"
    keep = ["timestamp_us", "slug", "market_id", "outcome",
            "ask_price_0", "ask_size_0", "bid_price_0", "bid_size_0"]
    # Read in chunks to avoid OOM on BTC's 640k-row file
    chunks = []
    for chunk in pd.read_csv(path, usecols=keep, chunksize=200_000, low_memory=False):
        chunks.append(chunk)
    df = pd.concat(chunks, ignore_index=True)
    out: dict = {}
    mid2slug: dict = {}
    df = df.sort_values(["market_id", "outcome", "timestamp_us"]).reset_index(drop=True)
    for (mid, oc), sub in df.groupby(["market_id", "outcome"], sort=False):
        ts = sub.timestamp_us.values.astype("int64")
        ap0 = sub.ask_price_0.values.astype(float)
        as0 = sub.ask_size_0.values.astype(float)
        bp0 = sub.bid_price_0.values.astype(float)
        bs0 = sub.bid_size_0.values.astype(float)
        out[(mid, oc)] = (ts, ap0, as0, bp0, bs0)
        mid2slug.setdefault(mid, sub.slug.iloc[0])
    return out, mid2slug


def find_book(idx, mid, outcome, target_us, max_dt_us=10_000_000):
    """Returns (ask_p0, ask_s0, bid_p0, bid_s0, dt_us) or None."""
    rec = idx.get((mid, outcome))
    if rec is None:
        return None
    ts, ap0, as0, bp0, bs0 = rec
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
    return float(ap0[best_i]), float(as0[best_i]), float(bp0[best_i]), float(bs0[best_i]), best_dt


def sell_at_bid(bid_p, bid_s, shares):
    remaining = float(shares); total_usd = 0.0; total_shares = 0.0
    for p, s in zip(bid_p, bid_s):
        if not (math.isfinite(p) and math.isfinite(s)) or s <= 0 or p <= 0 or p >= 1:
            break
        if s >= remaining:
            total_usd += remaining * p; total_shares += remaining; remaining = 0; break
        total_usd += s * p; total_shares += s; remaining -= s
    if total_shares <= 0:
        return float("nan"), 0.0, 0.0
    return total_usd / total_shares, total_shares, total_usd


SLEEVE_RE = re.compile(r"^poly_updown_(btc|eth|sol)_(5m|15m)_momo(_v2)?_(HOLD|HEDGE|SELL)$")


def parse_sleeve(sleeve_id: str):
    m = SLEEVE_RE.match(sleeve_id)
    if not m:
        return None
    asset = m.group(1).upper()
    tf = m.group(2)
    is_v2 = m.group(3) == "_v2"
    policy_tag = m.group(4)
    return asset, tf, is_v2, policy_tag


def main():
    print("[1] load klines + L25 books…")
    klines = load_klines()
    books = {}
    mid2slug: dict = {}
    for a in ("BTC", "ETH", "SOL"):
        b, m = load_l25(a)
        books[a] = b
        mid2slug.update(m)
        print(f"    {a}: {len(b)} (mid,outcome) keys, {sum(len(rec[0]) for rec in b.values()):,} snapshots")

    print("[2] read live trades…")
    live = pd.read_csv(DIR / "momo_v1v2_live.csv")
    print(f"    {len(live)} live resolutions")

    # Add ws from slug
    live["slug"] = live.condition_id.map(mid2slug)
    live = live.dropna(subset=["slug"]).copy()
    live["ws"] = live.slug.str.extract(r"-(\d+)$")[0].astype("int64")
    parsed = live.sleeve_id.apply(parse_sleeve)
    live["asset_p"] = parsed.apply(lambda x: x[0] if x else None)
    live["tf_p"] = parsed.apply(lambda x: x[1] if x else None)
    live["is_v2"] = parsed.apply(lambda x: x[2] if x else None)
    live["policy_tag"] = parsed.apply(lambda x: x[3] if x else None)
    live = live.dropna(subset=["asset_p"])
    live["window_s"] = live.tf_p.map({"5m": 300, "15m": 900})
    live["fire_offset_s"] = live.is_v2.map({True: 60, False: 120})
    live["fire_us"] = (live.ws.astype("int64") + live.fire_offset_s.astype("int64")) * 1_000_000
    live["resolve_us"] = (live.ws.astype("int64") + live.window_s.astype("int64") - 60) * 1_000_000
    print(f"    parseable: {len(live)} (after slug + sleeve parse)")

    print("[3] simulate per-trade exit prediction…")
    rows = []
    for r in live.itertuples(index=False):
        asset = r.asset_p
        held = "Up" if r.signal == "UP" else "Down"
        other = "Down" if r.signal == "UP" else "Up"
        idx = books[asset]

        # Production actual exit
        prod_hedged = (str(r.hedged).lower() == "true")
        prod_partial_bid = (str(r.partial_bid_exit).lower() == "true")
        prod_actual_exit = "hedge" if prod_hedged else ("sell" if prod_partial_bid else "hold")

        # rev_bp anchor = BTC@ws (production convention, both v1 and v2)
        asset_at_ws = asof_strict(klines[asset], int(r.ws))
        if not math.isfinite(asset_at_ws) or asset_at_ws <= 0:
            rows.append(dict(sleeve_id=r.sleeve_id, slug=r.slug, ws=int(r.ws), asset=asset, tf=r.tf_p,
                             signal=r.signal, outcome=r.outcome, policy_tag=r.policy_tag, is_v2=r.is_v2,
                             prod_pnl=r.pnl_usd, prod_actual_exit=prod_actual_exit,
                             diag_gate_ever_opened=None, diag_max_rev_bp=None,
                             diag_first_gate_open_dt_s=None, diag_n_ticks_after_gate=None,
                             diag_hedge_book_available=None, diag_sell_book_available=None,
                             diag_predicted_exit=None, diag_skip_reason="no_anchor"))
            continue

        # Walk ticks from fire_us+TICK to resolve_us
        first_gate_us = None
        max_rev_bp = 0.0
        gate_opened = False
        hedge_feasible_first = None
        sell_feasible_first = None
        predicted_exit = "hold"
        predicted_at_us = None

        t_us = int(r.fire_us) + TICK_S * 1_000_000
        while t_us <= int(r.resolve_us):
            a_now = asof_strict(klines[asset], t_us // 1_000_000)
            if not math.isfinite(a_now):
                t_us += TICK_S * 1_000_000; continue
            rev_bp = (a_now - asset_at_ws) / asset_at_ws * 1e4
            # track magnitude in the "against signal" direction
            against = -rev_bp if r.signal == "UP" else rev_bp
            if against > max_rev_bp:
                max_rev_bp = against
            triggered = (r.signal == "UP" and rev_bp <= -REV_BP) or \
                        (r.signal == "DOWN" and rev_bp >= REV_BP)
            if triggered:
                gate_opened = True
                if first_gate_us is None:
                    first_gate_us = t_us
                    # check both books at this moment
                    opp_book = find_book(idx, r.condition_id, other, t_us)
                    own_book = find_book(idx, r.condition_id, held, t_us)
                    # opp_book: ask_p0, ask_s0, bid_p0, bid_s0, dt → HEDGE walks opposite-side ASK
                    hedge_feasible_first = bool(
                        opp_book is not None
                        and math.isfinite(opp_book[0]) and 0 < opp_book[0] < 1
                        and math.isfinite(opp_book[1]) and opp_book[1] > 0
                    )
                    # own_book: SELL walks own-side BID
                    sell_feasible_first = bool(
                        own_book is not None
                        and math.isfinite(own_book[2]) and 0 < own_book[2] < 1
                        and math.isfinite(own_book[3]) and own_book[3] > 0
                    )
                # predict per policy: SELL fires iff own bid book has shares; HEDGE iff opposite ASK book has shares
                if r.policy_tag == "HEDGE" and predicted_exit == "hold":
                    if hedge_feasible_first:
                        predicted_exit = "hedge"; predicted_at_us = t_us
                elif r.policy_tag == "SELL" and predicted_exit == "hold":
                    if sell_feasible_first:
                        predicted_exit = "sell"; predicted_at_us = t_us
                if predicted_exit != "hold":
                    break
            t_us += TICK_S * 1_000_000

        rows.append(dict(
            sleeve_id=r.sleeve_id, slug=r.slug, ws=int(r.ws), asset=asset, tf=r.tf_p,
            signal=r.signal, outcome=r.outcome, policy_tag=r.policy_tag, is_v2=r.is_v2,
            prod_pnl=r.pnl_usd, prod_actual_exit=prod_actual_exit,
            diag_gate_ever_opened=gate_opened,
            diag_max_rev_bp=round(max_rev_bp, 2),
            diag_first_gate_open_dt_s=int((first_gate_us - r.fire_us) / 1_000_000) if first_gate_us else None,
            diag_n_ticks_after_gate=None,  # could compute but not critical
            diag_hedge_book_available=hedge_feasible_first,
            diag_sell_book_available=sell_feasible_first,
            diag_predicted_exit=predicted_exit,
            diag_skip_reason=("rev_bp_never_opened" if not gate_opened else
                             "book_missing" if (r.policy_tag == "HEDGE" and not hedge_feasible_first) or
                                                (r.policy_tag == "SELL" and not sell_feasible_first)
                                             else "ok"),
        ))

    out = pd.DataFrame(rows)
    out.to_csv(OUT_CSV, index=False)
    print(f"    wrote {len(out)} rows -> {OUT_CSV.name}")

    # Aggregate per (is_v2, policy_tag)
    print("\n=== Per-policy exit fire rates: PROD vs BACKTEST PREDICTED ===")
    g = out.groupby(["is_v2", "policy_tag"])
    summary = g.agg(
        n=("prod_pnl", "size"),
        prod_hold=("prod_actual_exit", lambda s: (s == "hold").sum()),
        prod_hedge=("prod_actual_exit", lambda s: (s == "hedge").sum()),
        prod_sell=("prod_actual_exit", lambda s: (s == "sell").sum()),
        bt_hold=("diag_predicted_exit", lambda s: (s == "hold").sum()),
        bt_hedge=("diag_predicted_exit", lambda s: (s == "hedge").sum()),
        bt_sell=("diag_predicted_exit", lambda s: (s == "sell").sum()),
        gate_open_rate=("diag_gate_ever_opened", "mean"),
    ).reset_index()
    print(summary.to_string(index=False))

    # Per-cell view
    print("\n=== Per-cell PROD exit rate ===")
    g2 = out.groupby(["is_v2", "asset", "tf", "policy_tag"])
    summary2 = g2.agg(
        n=("prod_pnl", "size"),
        prod_hold_pct=("prod_actual_exit", lambda s: 100 * (s == "hold").sum() / max(len(s), 1)),
        prod_hedge_pct=("prod_actual_exit", lambda s: 100 * (s == "hedge").sum() / max(len(s), 1)),
        prod_sell_pct=("prod_actual_exit", lambda s: 100 * (s == "sell").sum() / max(len(s), 1)),
        bt_hedge_pct=("diag_predicted_exit", lambda s: 100 * (s == "hedge").sum() / max(len(s), 1)),
        bt_sell_pct=("diag_predicted_exit", lambda s: 100 * (s == "sell").sum() / max(len(s), 1)),
    ).round(1).reset_index()
    print(summary2.to_string(index=False))

    # Diagnose: of the "predicted SELL but actual HOLD" cases, what's the reason?
    print("\n=== HEDGE/SELL gap diagnosis ===")
    sub = out[(out.policy_tag.isin(("HEDGE","SELL"))) & (out.prod_actual_exit == "hold")]
    skip_breakdown = sub.diag_skip_reason.value_counts()
    print(skip_breakdown)

    print(f"\n=== Trades where backtest says exit but production held ===")
    diff = out[(out.diag_predicted_exit != "hold") & (out.prod_actual_exit == "hold")]
    print(f"  total: {len(diff)}")
    if len(diff):
        print(diff.groupby(["is_v2","policy_tag","diag_predicted_exit"]).size())


if __name__ == "__main__":
    main()
