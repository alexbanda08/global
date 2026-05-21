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

"""Exploratory exit-policy sweep — find a momo variant that beats HOLD on the live window.

Tests on the same 851 live momo v1+v2 trades (7-day window). For each strategy variant,
replays the entry walk + exit logic against L25 WS books and computes total PnL.

Variants tested (each defined by a small set of parameters):
  HOLD_baseline                 — no exit-policy intervention
  HEDGE_<N>bp                   — fire HEDGE when |rev_bp| ≥ N (Binance reversal)
  SELL_<N>bp                    — fire SELL_BID when |rev_bp| ≥ N
  HYBRID_<N>bp                  — HEDGE first, fall back to SELL_BID if hedge fails
  TIME_HEDGE_t<S>               — force HEDGE at t+S of holding window (no rev_bp needed)
  TIME_SELL_t<S>                — force SELL at t+S of holding window
  PROFIT_SELL_<R>x              — SELL when own_bid_top > entry_vwap × R (profit-take)
  STOP_SELL_<F>x                — SELL when own_bid_top < entry_vwap × F (stop-loss)
  STOP_HEDGE_<F>x               — HEDGE when own_bid_top < entry_vwap × F
  COMBO_<...>                   — composite triggers (rev_bp OR profit-take OR stop-loss)

All HEDGE / SELL variants accept ANY positive partial fill (chainlink settles remainder).
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
OUT_CSV = DIR / "momo_exit_policy_explore_per_trade.csv"
SUMMARY_CSV = DIR / "momo_exit_policy_explore_summary.csv"
REPORT = ROOT / "strategy_lab/reports/MOMO_EXIT_POLICY_EXPLORE_2026_05_09.md"

LEVELS = 25
NOTIONAL = 25.0
FEE = 0.02
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
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
    path = DIR / f"vps2_l25_{asset.lower()}.csv"
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_as = [f"ask_size_{i}" for i in range(LEVELS)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS)]
    cols_bs = [f"bid_size_{i}" for i in range(LEVELS)]
    keep = ["timestamp_us", "slug", "market_id", "outcome"] + cols_ap + cols_as + cols_bp + cols_bs
    chunks = [c for c in pd.read_csv(path, usecols=keep, chunksize=100_000, low_memory=False)]
    df = pd.concat(chunks, ignore_index=True)
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


# ---------------------------------------------------------------------------
# Variant configs
# ---------------------------------------------------------------------------

def all_variants():
    """Return list of (variant_name, params dict) tuples."""
    out = [("HOLD_baseline", {"trigger": "none", "exit": "none"})]

    # rev_bp sweep on HEDGE
    for bp in (3, 5, 7, 10, 15):
        out.append((f"HEDGE_{bp}bp", {"trigger": "rev_bp", "rev_bp": bp, "exit": "hedge"}))
    # rev_bp sweep on SELL
    for bp in (3, 5, 7, 10, 15):
        out.append((f"SELL_{bp}bp", {"trigger": "rev_bp", "rev_bp": bp, "exit": "sell"}))
    # HYBRID = HEDGE then SELL fallback
    for bp in (3, 5, 10):
        out.append((f"HYBRID_{bp}bp", {"trigger": "rev_bp", "rev_bp": bp, "exit": "hybrid"}))

    # Time-forced exits (no rev_bp; just t+S)
    for s in (60, 120, 180, 240):
        out.append((f"TIME_HEDGE_t{s}", {"trigger": "time", "time_s": s, "exit": "hedge"}))
        out.append((f"TIME_SELL_t{s}", {"trigger": "time", "time_s": s, "exit": "sell"}))

    # Profit-take SELL: SELL when own bid > entry_vwap * R
    for r in (1.05, 1.10, 1.20, 1.30):
        out.append((f"PROFIT_SELL_{r}x", {"trigger": "profit", "profit_ratio": r, "exit": "sell"}))

    # Stop-loss exits (Polymarket-side reversal)
    for f in (0.30, 0.50, 0.70):
        out.append((f"STOP_SELL_{f}x", {"trigger": "stop", "stop_ratio": f, "exit": "sell"}))
        out.append((f"STOP_HEDGE_{f}x", {"trigger": "stop", "stop_ratio": f, "exit": "hedge"}))

    # Combo: rev_bp 5bp OR profit 1.10x OR stop 0.50x
    out.append(("COMBO_RevOrProfit", {"trigger": "any", "rev_bp": 5, "profit_ratio": 1.10, "exit": "sell"}))
    out.append(("COMBO_AllExits", {"trigger": "any", "rev_bp": 5, "profit_ratio": 1.10, "stop_ratio": 0.50, "exit": "sell"}))
    out.append(("COMBO_HEDGE_RevOrStop", {"trigger": "any", "rev_bp": 5, "stop_ratio": 0.50, "exit": "hedge"}))

    return out


# ---------------------------------------------------------------------------
# Trade simulator
# ---------------------------------------------------------------------------

def simulate(r, klines, books, params):
    """Run one trade through one variant. Returns dict with pnl + diagnostics."""
    asset = r["asset"]
    held = "Up" if r["signal"] == "UP" else "Down"
    other = "Down" if r["signal"] == "UP" else "Up"
    idx = books[asset]
    mid = r["condition_id"]

    # Entry
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
    if shares_e <= 0 or (under and usd_e < NOTIONAL * 0.5):
        return None

    won = (r["signal"] == "UP" and r["outcome"] == "Up") or (r["signal"] == "DOWN" and r["outcome"] == "Down")

    def hold_pnl():
        if won:
            profit = shares_e * 1.0 - usd_e
            return profit - (profit * FEE if profit > 0 else 0.0)
        return -usd_e

    # HOLD baseline
    if params["trigger"] == "none":
        return dict(exit_reason="hold", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                    shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0,
                    pnl=hold_pnl(), fired=False, t_exit_s=None)

    # rev_bp anchor for triggers that need Binance
    asset_at_ws = asof_strict(klines[asset], int(r["ws"]))
    if not math.isfinite(asset_at_ws) or asset_at_ws <= 0:
        return dict(exit_reason="hold_no_anchor", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                    shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0,
                    pnl=hold_pnl(), fired=False, t_exit_s=None)

    fire_us = int(r["fire_us"])
    resolve_us = int(r["resolve_us"])

    # Walk ticks to find first trigger time
    triggered_at_us = None
    triggered_by = None  # 'rev_bp' | 'time' | 'profit' | 'stop'

    t_us = fire_us + TICK_S * 1_000_000
    while t_us <= resolve_us:
        t_dt_s = (t_us - fire_us) / 1_000_000

        # --- Time trigger ---
        if params["trigger"] == "time" and t_dt_s >= params["time_s"]:
            triggered_at_us = t_us; triggered_by = "time"; break

        # --- Get current Polymarket book if needed ---
        own_book = None
        own_bid_top = None
        if params["trigger"] in ("profit", "stop", "any"):
            own_book = find_book_l25(idx, mid, held, t_us)
            if own_book is not None:
                bp_now = own_book[2]
                if math.isfinite(bp_now[0]) and 0 < bp_now[0] < 1:
                    own_bid_top = float(bp_now[0])

        # --- Profit trigger ---
        if params["trigger"] == "profit" and own_bid_top is not None:
            if own_bid_top >= vwap_e * params["profit_ratio"]:
                triggered_at_us = t_us; triggered_by = "profit"; break

        # --- Stop trigger ---
        if params["trigger"] == "stop" and own_bid_top is not None:
            if own_bid_top <= vwap_e * params["stop_ratio"]:
                triggered_at_us = t_us; triggered_by = "stop"; break

        # --- rev_bp / hybrid / any (rev_bp branch) ---
        if params["trigger"] in ("rev_bp", "any"):
            a_now = asof_strict(klines[asset], t_us // 1_000_000)
            if math.isfinite(a_now):
                rev_bp = (a_now - asset_at_ws) / asset_at_ws * 1e4
                rev_bp_thr = params.get("rev_bp", 5)
                if (r["signal"] == "UP" and rev_bp <= -rev_bp_thr) or \
                   (r["signal"] == "DOWN" and rev_bp >= rev_bp_thr):
                    triggered_at_us = t_us; triggered_by = "rev_bp"; break

        # --- 'any' also checks profit/stop ---
        if params["trigger"] == "any":
            if "profit_ratio" in params and own_bid_top is not None and \
               own_bid_top >= vwap_e * params["profit_ratio"]:
                triggered_at_us = t_us; triggered_by = "profit"; break
            if "stop_ratio" in params and own_bid_top is not None and \
               own_bid_top <= vwap_e * params["stop_ratio"]:
                triggered_at_us = t_us; triggered_by = "stop"; break

        t_us += TICK_S * 1_000_000

    if triggered_at_us is None:
        return dict(exit_reason="hold_no_trigger", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                    shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0,
                    pnl=hold_pnl(), fired=False, t_exit_s=None)

    t_dt_s = (triggered_at_us - fire_us) / 1_000_000

    # --- Execute exit ---
    exit_kind = params["exit"]

    def try_hedge():
        opp = find_book_l25(idx, mid, other, triggered_at_us)
        if opp is None:
            return None
        ap_o, as_o, _, _, _ = opp
        top_ask = float(ap_o[0]) if math.isfinite(ap_o[0]) else float("nan")
        if not (math.isfinite(top_ask) and 0 < top_ask < 1):
            return None
        target_h_usd = shares_e * top_ask
        vwap_h, shares_h, usd_h, _, _ = book_walk_fill(
            [float(x) for x in ap_o], [float(x) for x in as_o], target_h_usd
        )
        if shares_h <= 0:
            return None
        return vwap_h, shares_h, usd_h

    def try_sell():
        own = find_book_l25(idx, mid, held, triggered_at_us)
        if own is None:
            return None
        _, _, bp_o, bs_o, _ = own
        vwap_s, shares_s, gross_s = sell_at_bid_partial(bp_o, bs_o, shares_e)
        if shares_s <= 0:
            return None
        return vwap_s, shares_s, gross_s

    if exit_kind == "hedge":
        h = try_hedge()
        if h is None:
            return dict(exit_reason="hold_hedge_failed", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                        shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0,
                        pnl=hold_pnl(), fired=False, t_exit_s=t_dt_s)
        vwap_h, shares_h, usd_h = h
        held_gross = shares_e * 1.0 if won else 0.0
        hedge_gross = shares_h * 1.0 if not won else 0.0
        cost = usd_e + usd_h
        profit = (held_gross + hedge_gross) - cost
        fee = profit * FEE if profit > 0 else 0.0
        return dict(exit_reason=f"hedge_by_{triggered_by}", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                    shares_filled=shares_h, vwap_exit=vwap_h, usd_exit=usd_h,
                    pnl=profit - fee, fired=True, t_exit_s=t_dt_s)

    if exit_kind == "sell":
        s = try_sell()
        if s is None:
            return dict(exit_reason="hold_sell_failed", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                        shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0,
                        pnl=hold_pnl(), fired=False, t_exit_s=t_dt_s)
        vwap_s, shares_s, gross_s = s
        remainder = shares_e - shares_s
        remainder_gross = remainder * 1.0 if won else 0.0
        gross = gross_s + remainder_gross
        profit = gross - usd_e
        fee = profit * FEE if profit > 0 else 0.0
        return dict(exit_reason=f"sell_by_{triggered_by}", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                    shares_filled=shares_s, vwap_exit=vwap_s, usd_exit=gross_s,
                    pnl=profit - fee, fired=True, t_exit_s=t_dt_s)

    if exit_kind == "hybrid":
        h = try_hedge()
        if h is not None:
            vwap_h, shares_h, usd_h = h
            held_gross = shares_e * 1.0 if won else 0.0
            hedge_gross = shares_h * 1.0 if not won else 0.0
            cost = usd_e + usd_h
            profit = (held_gross + hedge_gross) - cost
            fee = profit * FEE if profit > 0 else 0.0
            return dict(exit_reason=f"hedge_by_{triggered_by}", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                        shares_filled=shares_h, vwap_exit=vwap_h, usd_exit=usd_h,
                        pnl=profit - fee, fired=True, t_exit_s=t_dt_s)
        # fall through to SELL
        s = try_sell()
        if s is not None:
            vwap_s, shares_s, gross_s = s
            remainder = shares_e - shares_s
            remainder_gross = remainder * 1.0 if won else 0.0
            gross = gross_s + remainder_gross
            profit = gross - usd_e
            fee = profit * FEE if profit > 0 else 0.0
            return dict(exit_reason=f"sell_by_{triggered_by}", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                        shares_filled=shares_s, vwap_exit=vwap_s, usd_exit=gross_s,
                        pnl=profit - fee, fired=True, t_exit_s=t_dt_s)
        return dict(exit_reason="hold_hybrid_failed", shares_e=shares_e, usd_e=usd_e, vwap_e=vwap_e,
                    shares_filled=0.0, vwap_exit=0.0, usd_exit=0.0,
                    pnl=hold_pnl(), fired=False, t_exit_s=t_dt_s)

    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[1] load klines + L25 books per asset...")
    klines = load_klines()
    books = {}; mid2slug: dict = {}
    for a in ("BTC", "ETH", "SOL"):
        bks, m = load_l25_keyed(a)
        books[a] = bks; mid2slug.update(m)
        print(f"    {a}: {len(bks)} keys, {sum(len(rec[0]) for rec in bks.values()):,} snapshots")

    print("[2] read live trades (one per (slug, sleeve) — dedupe by trade)...")
    live = pd.read_csv(DIR / "momo_v1v2_live.csv")
    live["slug"] = live.condition_id.map(mid2slug)
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

    # DEDUPE: keep only one row per (sleeve_id, ws) — production fires the same
    # trade across HOLD/HEDGE/SELL sleeves (3 rows per fire). For the variant
    # sweep we want each market evaluated once per variant.
    live = live.drop_duplicates(["asset", "tf", "is_v2", "ws"]).reset_index(drop=True)
    print(f"    deduped trades to evaluate per variant: {len(live)}")

    variants = all_variants()
    print(f"[3] running {len(variants)} variants × {len(live)} trades = {len(variants)*len(live)} simulations...")

    rows = []
    for vname, params in variants:
        for r in live.to_dict("records"):
            res = simulate(r, klines, books, params)
            if res is None:
                continue
            rows.append({
                "variant": vname,
                **{k: r[k] for k in ("asset", "tf", "is_v2", "ws", "signal", "outcome",
                                     "policy_tag", "sleeve_id", "pnl_usd")},
                **res,
            })
        sub = [r for r in rows if r["variant"] == vname]
        n_fired = sum(1 for r in sub if r["fired"])
        total = sum(r["pnl"] for r in sub)
        print(f"    {vname:<25} n={len(sub)} fires={n_fired} pnl_total=${total:+.2f}")

    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nwrote {len(df)} rows -> {OUT_CSV.name}")

    # Summary table
    print("\n=== Summary: total PnL across all 6 cells × v1+v2, by variant ===")
    summary = df.groupby("variant").agg(
        n=("pnl", "size"),
        n_fired=("fired", "sum"),
        fire_pct=("fired", lambda s: round(100 * s.sum() / len(s), 1)),
        pnl_total=("pnl", lambda s: round(s.sum(), 2)),
        pnl_mean=("pnl", lambda s: round(s.mean(), 4)),
    ).sort_values("pnl_total", ascending=False)
    summary.to_csv(SUMMARY_CSV)
    print(summary.to_string())

    # Per-cell winner
    print("\n=== Best variant per (asset, tf, is_v2) cell, ranked by pnl_total ===")
    cell = df.groupby(["asset", "tf", "is_v2", "variant"]).pnl.sum().reset_index()
    winners = cell.loc[cell.groupby(["asset", "tf", "is_v2"]).pnl.idxmax()]
    print(winners.sort_values("pnl", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
