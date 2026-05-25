"""Queue-aware maker fill model + hybrid maker→taker fallback.

Builds on `maker_vs_taker_gated_sleeves.py` (which assumed zero queue + all-or-
nothing fills).  This version uses Polymarket trades parquet to count actual
aggressor SELL volume at our chosen limit price level, and clears our queue
FIFO.

Per fire, per placement, per notional we compute three policies:

  PURE_TAKER       — book walk at fire_us with 2%-on-profit fee (production today)
  PURE_MAKER_Q     — maker at limit P, partial-fill from trades aggregating in
                     [fire_us+85ms, slot_end_us].  No fee.
  HYBRID_MAKER60_T — maker for first 60s; remainder crossed with taker at
                     fire_us+60s with 2%-on-profit fee.

Queue position model:
  queue_ahead = bsz at the price level we sit on at entry book.
    P == best_bid       → queue_ahead = bsz[0]
    P matches bp[k]>0   → queue_ahead = bsz[k]
    P between levels    → queue_ahead = 0 (we create a new level)

Fill model:
  cum_sell_vol_at_P  = sum(trade.size for trade in window if trade.outcome==our_side
                            AND trade.side=='sell' AND abs(trade.price - P) < 0.005)
  filled_shares = clamp(cum_sell_vol_at_P - queue_ahead, 0, target_shares)

Outputs:
  strategy_lab/markov_filter/_results/queue_aware_per_fire.csv
  strategy_lab/markov_filter/_results/queue_aware_per_sleeve.csv
"""
from __future__ import annotations
import gc
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "strategy_lab")
sys.path.insert(0, "data/v4/canonical")

from book_walk import book_walk_fill
from engine_v2 import find_book_strict
from load import load_orderbook_l25_streaming, load_trades


NOTIONALS_USD = [25, 100, 500, 1_000]
TICK = 0.01
LATENCY_MS = 85
HYBRID_WINDOW_S = 60
MAX_BOOK_STALENESS_US = 60_000_000
PRICE_BUCKET = 0.005          # match trade.price to limit within ½ tick

HOD_TOP8 = {
    ("sniper",  "sol_5m"):  [0, 1, 2, 4, 8, 15, 19, 23],
    ("sniper",  "eth_15m"): [0, 6, 7, 9, 13, 14, 19, 22],
    ("momo_v1", "btc_15m"): [0, 1, 3, 5, 9, 14, 16, 20],
    ("sniper",  "btc_15m"): [0, 3, 10, 11, 12, 13, 14, 15],
    ("sniper",  "btc_5m"):  [0, 1, 3, 5, 12, 15, 19, 21],
    ("momo_v2", "btc_5m"):  [0, 2, 5, 6, 10, 12, 21, 23],
    ("momo_v2", "btc_15m"): [1, 11, 12, 16, 18, 20, 21, 22],
    ("momo_v2", "sol_5m"):  [4, 5, 6, 8, 10, 12, 14, 17],
    ("momo_v2", "eth_15m"): [0, 5, 8, 12, 16, 17, 20, 22],
    ("momo_v2", "sol_15m"): [1, 2, 5, 12, 13, 16, 17, 21],
    ("sniper",  "eth_5m"):  [0, 2, 11, 13, 14, 17, 20, 21],
}
SLEEVES = [
    ("sniper",  "sol_5m",  "HOD"),
    ("sniper",  "eth_15m", "HOD+M5va"),
    ("momo_v1", "btc_15m", "HOD"),
    ("sniper",  "btc_15m", "HOD"),
    ("sniper",  "btc_5m",  "HOD"),
    ("momo_v2", "btc_5m",  "HOD+MTF2"),
    ("momo_v2", "btc_15m", "HOD"),
    ("momo_v2", "sol_5m",  "HOD"),
    ("momo_v2", "eth_15m", "HOD"),
    ("momo_v2", "sol_15m", "HOD"),
    ("sniper",  "eth_5m",  "HOD"),
]


# ---------------------------------------------------------------------
# MTF2 (binance 1m → ret_15m AND ret_1h same-sign as signal)
# ---------------------------------------------------------------------
def add_mtf2(fills: pd.DataFrame) -> pd.DataFrame:
    kl = pd.read_csv("strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv")
    kl["asset"] = kl["symbol_id"].str.extract(r"BINANCE_SPOT_([A-Z]+)_USDT")
    fills = fills.copy()
    fills["mtf2_pass"] = False
    for asset, kg in kl.groupby("asset"):
        kg = kg.sort_values("time_period_start_us").reset_index(drop=True)
        end_us = kg["time_period_start_us"].to_numpy() + 60_000_000
        prices = kg["price_close"].to_numpy()
        m = fills["asset"] == asset
        s = fills[m]; fire = s["fire_us"].to_numpy()
        i_n  = np.searchsorted(end_us, fire,                  side="right") - 1
        i_15 = np.searchsorted(end_us, fire -   900_000_000,  side="right") - 1
        i_1h = np.searchsorted(end_us, fire - 3_600_000_000,  side="right") - 1
        good = (i_n >= 0) & (i_15 >= 0) & (i_1h >= 0)
        p_n  = np.where(good, prices[np.clip(i_n,  0, None)], np.nan)
        p_15 = np.where(good, prices[np.clip(i_15, 0, None)], np.nan)
        p_1h = np.where(good, prices[np.clip(i_1h, 0, None)], np.nan)
        ret15 = np.log(p_n / p_15); ret1h = np.log(p_n / p_1h)
        sig = s["signal"].to_numpy()
        ok = (np.isfinite(ret15) & np.isfinite(ret1h)) & (
            ((sig == "UP")   & (ret15 > 0) & (ret1h > 0)) |
            ((sig == "DOWN") & (ret15 < 0) & (ret1h < 0))
        )
        fills.loc[m, "mtf2_pass"] = ok
    return fills


def apply_gate(fills, strategy, cell, gate):
    df = fills[(fills["strategy"] == strategy) & (fills["cell_key"] == cell)].copy()
    if df.empty: return df
    df = df[df["hour"].isin(set(HOD_TOP8[(strategy, cell)]))]
    if "MTF2" in gate: df = df[df["mtf2_pass"]]
    if "M5va" in gate: df = df[df["markov_pass_w20_5m_voladaptive"]]
    return df


# ---------------------------------------------------------------------
# Queue helpers
# ---------------------------------------------------------------------
def queue_ahead_at_price(bp, bsz, P):
    """Existing resting bid volume at level P (within ½ tick)."""
    for px, sz in zip(bp, bsz):
        if not (np.isfinite(px) and np.isfinite(sz)):
            continue
        if abs(px - P) < PRICE_BUCKET:
            return float(sz)
    return 0.0


def maker_fill_in_window(slug_trades_arr, fire_us, end_us, P, queue_ahead,
                         target_shares):
    """Walk pre-sliced trades array forward; return (filled_shares, fill_ts).

    `slug_trades_arr` columns: ts_us, price, size, is_aggressor_sell (uint8).
    """
    if slug_trades_arr is None or len(slug_trades_arr) == 0:
        return 0.0, None
    ts, px, sz, is_sell = slug_trades_arr
    start = int(np.searchsorted(ts, fire_us, side="right"))
    if start >= len(ts):
        return 0.0, None
    cum = 0.0
    fill_ts = None
    filled = 0.0
    for k in range(start, len(ts)):
        if ts[k] > end_us: break
        if not is_sell[k]: continue
        if abs(px[k] - P) >= PRICE_BUCKET: continue
        cum += sz[k]
        avail = cum - queue_ahead
        if avail > 0 and filled == 0.0:
            fill_ts = int(ts[k])
        new_filled = min(target_shares, max(0.0, avail))
        if new_filled > filled:
            filled = new_filled
        if filled >= target_shares - 1e-9:
            break
    return filled, fill_ts


def pnl_maker(shares, P, won):
    return shares * (1.0 - P) if won else shares * (-P)


def pnl_taker_2pct(shares, usd, won):
    if shares <= 0 or usd <= 0: return 0.0
    if won:
        gross = shares * 1.0
        profit = gross - usd
        return profit * 0.98 if profit > 0 else (gross - usd)
    return -usd


# ---------------------------------------------------------------------
# Per-asset sweep
# ---------------------------------------------------------------------
def sweep_one_asset(asset: str, fires: pd.DataFrame) -> list[dict]:
    slugs = set(fires["slug"].unique())
    print(f"[{asset}] loading L25 ({len(slugs):,} slugs)...")
    books = load_orderbook_l25_streaming(
        asset, slugs=slugs, subsample_1hz=True,
        min_ts_us=int(fires["fire_us"].min()) - 60_000_000,
        max_ts_us=int(fires["fire_us"].max()) + 3600_000_000,
    )
    print(f"[{asset}] loading TRADES...")
    trades_full = load_trades(asset)
    trades = trades_full[trades_full["slug"].isin(slugs)].copy()
    del trades_full; gc.collect()
    print(f"[{asset}] {len(trades):,} trades in {trades['slug'].nunique():,} slugs")

    # Pre-group trades by (slug, outcome) as numpy arrays for fast scan
    print(f"[{asset}] indexing trades by (slug, outcome)...")
    trades_by_key = {}
    trades = trades.sort_values(["slug", "outcome", "timestamp_us"]).reset_index(drop=True)
    for (slug, outcome), grp in trades.groupby(["slug", "outcome"], sort=False):
        trades_by_key[(slug, outcome)] = (
            grp["timestamp_us"].to_numpy(),
            grp["price"].to_numpy(),
            grp["size"].to_numpy(),
            (grp["side"].to_numpy() == "sell").astype(np.uint8),
        )
    del trades; gc.collect()
    print(f"[{asset}] indexed {len(trades_by_key):,} (slug, outcome) keys")

    out = []
    n_done = 0; n_skip = 0; n_no_trades = 0
    for r in fires.itertuples(index=False):
        outcome_side = "Up" if r.signal == "UP" else "Down"
        fire_us = int(r.fire_us)
        slot_end_us = (int(r.ws_s) + 2 * int(r.window_s)) * 1_000_000
        hybrid_end_us = fire_us + HYBRID_WINDOW_S * 1_000_000

        # entry book at fire_us+latency
        entry = find_book_strict(
            books, r.slug, outcome_side, fire_us + LATENCY_MS * 1_000,
            max_staleness_us=MAX_BOOK_STALENESS_US,
        )
        if entry is None:
            n_skip += 1; continue
        ap = [float(x) for x in entry["ap"]]
        asz= [float(x) for x in entry["asz"]]
        bp = [float(x) for x in entry["bp"]]
        bsz= [float(x) for x in entry["bsz"]]
        if not ap or not bp or not np.isfinite(ap[0]) or not np.isfinite(bp[0]):
            n_skip += 1; continue
        best_ask = ap[0]; best_bid = bp[0]
        if best_ask <= best_bid or best_ask < 0.05 or best_ask > 0.95:
            n_skip += 1; continue
        if (best_ask - best_bid) > 0.02:
            n_skip += 1; continue
        won = bool(r.won)
        mid = round((best_bid + best_ask) / 2.0, 2)

        # 60s book for hybrid fallback
        book_60s = find_book_strict(
            books, r.slug, outcome_side, hybrid_end_us,
            max_staleness_us=MAX_BOOK_STALENESS_US,
        )
        if book_60s is not None:
            ap60  = [float(x) for x in book_60s["ap"]]
            asz60 = [float(x) for x in book_60s["asz"]]
            ladder60_p = []; ladder60_s = []
            for p, s in zip(ap60, asz60):
                if not (np.isfinite(p) and np.isfinite(s) and 0 < p < 1 and s > 0):
                    break
                ladder60_p.append(p); ladder60_s.append(s)
        else:
            ladder60_p = []; ladder60_s = []

        # taker ladder at fire_us for pure-taker baseline
        ladder_p = []; ladder_s = []
        for p, s in zip(ap, asz):
            if not (np.isfinite(p) and np.isfinite(s) and 0 < p < 1 and s > 0):
                break
            ladder_p.append(p); ladder_s.append(s)
        if not ladder_p:
            n_skip += 1; continue

        # trades array for this (slug, outcome)
        trades_arr = trades_by_key.get((r.slug, outcome_side))
        if trades_arr is None:
            n_no_trades += 1
        # don't skip — partial-fill model just produces zero fills

        candidates = {
            "P_bid":   best_bid,
            "P_bid+1": round(best_bid + TICK, 2),
            "P_mid":   mid,
            "P_ask-1": round(best_ask - TICK, 2),
        }

        for nU in NOTIONALS_USD:
            # ---- PURE_TAKER baseline at fire_us ----
            vwap_t, sh_t, usd_t, _, _ = book_walk_fill(
                ladder_p, ladder_s, float(nU), side="buy"
            )
            pnl_taker = pnl_taker_2pct(sh_t, usd_t, won)

            # ---- PURE_TAKER at fire_us+60s (for hybrid fallback context) ----
            # done lazily inside hybrid below

            for name, P in candidates.items():
                if P >= best_ask - 1e-9 or P <= 0:
                    continue
                # queue at P
                if abs(P - best_bid) < PRICE_BUCKET:
                    q_ahead = bsz[0] if len(bsz) > 0 and np.isfinite(bsz[0]) else 0.0
                else:
                    q_ahead = queue_ahead_at_price(bp, bsz, P)
                target_sh = nU / P

                # PURE_MAKER_Q — window = [fire_us+latency, slot_end_us]
                start_us = fire_us + LATENCY_MS * 1_000
                fill_pm, ft_pm = maker_fill_in_window(
                    trades_arr, start_us, slot_end_us, P, q_ahead, target_sh
                )
                pnl_pm = pnl_maker(fill_pm, P, won)

                # HYBRID_MAKER60_T — first 60s maker, rest taker at fire+60s
                fill_60, ft_60 = maker_fill_in_window(
                    trades_arr, start_us, hybrid_end_us, P, q_ahead, target_sh
                )
                pnl_maker_part = pnl_maker(fill_60, P, won)
                # taker on remainder
                rem_shares = max(0.0, target_sh - fill_60)
                if rem_shares > 0 and ladder60_p:
                    # equivalent $ to walk for the remaining shares
                    # use the ladder at +60s; book_walk_fill is $-driven, so
                    # supply an upper-bound $ that comfortably exhausts to
                    # `rem_shares` shares (cap at largest level vwap)
                    rem_usd_guess = rem_shares * ladder60_p[-1]
                    vwap_h, sh_h, usd_h, _, _ = book_walk_fill(
                        ladder60_p, ladder60_s, float(rem_usd_guess), side="buy"
                    )
                    sh_h = min(sh_h, rem_shares)
                    usd_h = sh_h * (vwap_h if vwap_h > 0 else 0.0)
                    pnl_taker_part = pnl_taker_2pct(sh_h, usd_h, won)
                else:
                    sh_h = 0.0; usd_h = 0.0; pnl_taker_part = 0.0
                pnl_hyb = pnl_maker_part + pnl_taker_part
                hyb_filled = fill_60 + sh_h
                hyb_avg_px = (fill_60 * P + sh_h * (usd_h / sh_h if sh_h > 0 else 0.0)) / max(hyb_filled, 1e-9)

                out.append({
                    "sleeve": r.sleeve, "strategy": r.strategy, "cell": r.cell,
                    "asset": asset, "slug": r.slug, "fire_us": fire_us,
                    "signal": r.signal, "won": won,
                    "best_ask": best_ask, "best_bid": best_bid, "mid": mid,
                    "notional": nU,
                    "placement": name, "limit_price": P,
                    "queue_ahead_shares": round(q_ahead, 2),
                    "target_shares":      round(target_sh, 2),
                    # PURE_MAKER_Q
                    "maker_q_fill_shares": round(fill_pm, 3),
                    "maker_q_fill_frac":   round(fill_pm / target_sh, 3),
                    "maker_q_pnl":         round(pnl_pm, 3),
                    # HYBRID
                    "hyb_maker_shares":    round(fill_60, 3),
                    "hyb_taker_shares":    round(sh_h, 3),
                    "hyb_taker_vwap_60s":  round(usd_h / sh_h if sh_h > 0 else 0.0, 3),
                    "hyb_total_filled":    round(hyb_filled, 3),
                    "hyb_avg_px":          round(hyb_avg_px, 3),
                    "hyb_pnl":             round(pnl_hyb, 3),
                    # PURE_TAKER
                    "taker_vwap":          round(vwap_t, 3),
                    "taker_shares":        round(sh_t, 3),
                    "taker_pnl":           round(pnl_taker, 3),
                })
        n_done += 1
    print(f"[{asset}] done={n_done}, skipped={n_skip}, no_trades_key={n_no_trades}")
    del books, trades_by_key; gc.collect()
    return out


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main():
    fills = pd.read_csv("strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv")
    fills["fire_ts"]  = pd.to_datetime(fills["fire_us"], unit="us", utc=True)
    fills["hour"]     = fills["fire_ts"].dt.hour
    fills["cell_key"] = fills["asset"].str.lower() + "_" + fills["tf"]
    fills = fills[fills["f7_mode"] == "off"].copy()
    fills = add_mtf2(fills)
    fills["window_s"] = np.where(fills["tf"] == "5m", 300, 900)

    rows = []
    for strategy, cell, gate in SLEEVES:
        g = apply_gate(fills, strategy, cell, gate)
        if g.empty: continue
        g = g.copy()
        g["gate"]   = gate
        g["sleeve"] = f"{strategy}_{cell}_{gate}"
        rows.append(g)
    gated_all = pd.concat(rows, ignore_index=True)
    print(f"[gate] {len(gated_all):,} fires across {len(rows)} sleeves")

    per_fire = []
    for asset, sub in gated_all.groupby("asset"):
        per_fire.extend(sweep_one_asset(asset, sub))

    out_dir = Path("strategy_lab/markov_filter/_results")
    df = pd.DataFrame(per_fire)
    df.to_csv(out_dir / "queue_aware_per_fire.csv", index=False)
    print(f"\n[write] {len(df):,} rows → queue_aware_per_fire.csv")

    # Aggregate per (sleeve, placement, notional)
    g = df.groupby(["sleeve","placement","notional"], as_index=False)
    agg = g.agg(
        n_fires           = ("taker_pnl",          "size"),
        wr_pct            = ("won",                lambda x: 100*float(x.mean())),
        # PURE_TAKER
        taker_sum         = ("taker_pnl",          "sum"),
        # PURE_MAKER_Q
        maker_q_sum       = ("maker_q_pnl",        "sum"),
        maker_q_fill_frac = ("maker_q_fill_frac",  "mean"),
        maker_q_zero_pct  = ("maker_q_fill_shares",lambda x: 100*float((x==0).mean())),
        # HYBRID
        hyb_sum           = ("hyb_pnl",            "sum"),
        hyb_maker_part_pct= ("hyb_maker_shares",   lambda x: 100*float((x>0).mean())),
        # context
        mean_queue_ahead  = ("queue_ahead_shares", "mean"),
        mean_target_sh    = ("target_shares",      "mean"),
        mean_limit_px     = ("limit_price",        "mean"),
        mean_taker_vwap   = ("taker_vwap",         "mean"),
    )
    agg["maker_q_lift_$"] = (agg["maker_q_sum"] - agg["taker_sum"]).round(2)
    agg["hyb_lift_$"]     = (agg["hyb_sum"]     - agg["taker_sum"]).round(2)
    for c in ["wr_pct","taker_sum","maker_q_sum","maker_q_fill_frac",
              "maker_q_zero_pct","hyb_sum","hyb_maker_part_pct",
              "mean_queue_ahead","mean_target_sh","mean_limit_px",
              "mean_taker_vwap"]:
        agg[c] = agg[c].round(2)
    agg = agg.sort_values(["sleeve","notional","placement"]).reset_index(drop=True)
    agg.to_csv(out_dir / "queue_aware_per_sleeve.csv", index=False)
    print(f"[write] {len(agg):,} rows → queue_aware_per_sleeve.csv")

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 260)
    print("\nTop-30 by hybrid lift ($):")
    print(agg.sort_values("hyb_lift_$", ascending=False).head(30).to_string(index=False))


if __name__ == "__main__":
    main()
