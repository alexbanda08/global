"""Maker-order simulator for gated-sleeve fires.

Hypothesis: instead of taking the book at fire_us (current production), place
a MAKER buy limit at a passive price (best_bid, bid+1 tick, mid, ask-1 tick)
and let it sit from fire_us+latency until slot_end_us.

Fill model: scan L25 snapshots in (fire_us+latency, slot_end_us]. First
snapshot where best_ask <= limit_price → filled at limit_price (all-or-
nothing; size limit = our notional). Otherwise → no fill, no trade, no PnL.

Fee model:
  - maker fill: $0 entry fee  (CLAUDE.md verified: feeRate=0 on the BTC/ETH/
    SOL up-down markets — neither 2%-on-profit nor maker rebate accrues).
  - taker baseline (production today): 2% on winning leg only, no fee on loss.

Outputs:
  strategy_lab/markov_filter/_results/maker_per_fire.csv
  strategy_lab/markov_filter/_results/maker_per_sleeve.csv
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
from engine_v2 import LegacyConfig, find_book_strict
from load import load_orderbook_l25_streaming


NOTIONALS_USD = [25, 100, 500, 1_000]
TICK = 0.01
LATENCY_MS = 85          # match LiveMimicConfig
MAX_BOOK_STALENESS_US = 60_000_000


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
QTY_MIN_PRICE, QTY_MAX_PRICE = 0.05, 0.95


# ---------------------------------------------------------------------
# MTF2 derivation (same as other runners)
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
        mask = fills["asset"] == asset
        sub  = fills[mask]
        fire = sub["fire_us"].to_numpy()
        i_n  = np.searchsorted(end_us, fire,                  side="right") - 1
        i_15 = np.searchsorted(end_us, fire -   900_000_000,  side="right") - 1
        i_1h = np.searchsorted(end_us, fire - 3_600_000_000,  side="right") - 1
        good = (i_n >= 0) & (i_15 >= 0) & (i_1h >= 0)
        p_n  = np.where(good, prices[np.clip(i_n , 0, None)], np.nan)
        p_15 = np.where(good, prices[np.clip(i_15, 0, None)], np.nan)
        p_1h = np.where(good, prices[np.clip(i_1h, 0, None)], np.nan)
        ret15 = np.log(p_n / p_15)
        ret1h = np.log(p_n / p_1h)
        sig = sub["signal"].to_numpy()
        ok = (np.isfinite(ret15) & np.isfinite(ret1h)) & (
            ((sig == "UP")   & (ret15 > 0) & (ret1h > 0)) |
            ((sig == "DOWN") & (ret15 < 0) & (ret1h < 0))
        )
        fills.loc[mask, "mtf2_pass"] = ok
    return fills


def apply_gate(fills, strategy, cell, gate):
    df = fills[(fills["strategy"] == strategy) & (fills["cell_key"] == cell)].copy()
    if df.empty: return df
    df = df[df["hour"].isin(set(HOD_TOP8[(strategy, cell)]))]
    if "MTF2" in gate: df = df[df["mtf2_pass"]]
    if "M5va" in gate: df = df[df["markov_pass_w20_5m_voladaptive"]]
    return df


# ---------------------------------------------------------------------
# Maker fill simulator
# ---------------------------------------------------------------------
def simulate_maker(books_idx, slug, outcome_side, fire_us, slot_end_us,
                    limit_price, latency_us=LATENCY_MS * 1_000):
    """Return (filled, fill_ts_us, dt_us) for a single maker buy limit.

    Fill condition: any L25 snapshot strictly after `fire_us+latency_us`
    and before/at `slot_end_us` has best_ask <= limit_price.
    """
    series = books_idx.get((slug, outcome_side))
    if series is None:
        return False, None, None
    ts_us, ap, *_ = series
    lookup_after = int(fire_us) + int(latency_us)
    # find first index strictly after lookup_after
    j = int(np.searchsorted(ts_us, lookup_after, side="right"))
    while j < len(ts_us) and ts_us[j] <= slot_end_us:
        a0 = float(ap[j, 0])
        if np.isfinite(a0) and a0 <= limit_price + 1e-9:
            return True, int(ts_us[j]), int(ts_us[j] - fire_us)
        j += 1
    return False, None, None


def pnl_maker(shares: float, limit_price: float, won: bool) -> float:
    """Maker pnl: $0 entry fee. Winner: 1 - limit. Loser: -limit."""
    return shares * (1.0 - limit_price) if won else shares * (-limit_price)


def pnl_taker_2pct(shares: float, usd: float, won: bool) -> float:
    if won:
        gross = shares * 1.0
        profit = gross - usd
        return profit * 0.98 if profit > 0 else (gross - usd)
    return -usd


def sweep_one_asset(asset: str, fires: pd.DataFrame) -> list[dict]:
    slugs = set(fires["slug"].unique())
    print(f"[{asset}] loading L25 for {len(slugs):,} slugs...")
    books = load_orderbook_l25_streaming(
        asset, slugs=slugs, subsample_1hz=True,
        min_ts_us=int(fires["fire_us"].min()) - 60 * 1_000_000,
        max_ts_us=int(fires["fire_us"].max()) + 3600 * 1_000_000,
    )
    print(f"[{asset}] {len(books):,} (slug, outcome) series")

    out = []
    n_done = 0; n_no_entry_book = 0; n_qty_skip = 0
    for r in fires.itertuples(index=False):
        outcome_side = "Up" if r.signal == "UP" else "Down"
        fire_us = int(r.fire_us)
        slot_end_us = (int(r.ws_s) + 2 * int(r.window_s)) * 1_000_000
        # entry book — to get best_bid + best_ask at fire_us
        book = find_book_strict(
            books, r.slug, outcome_side,
            fire_us + LATENCY_MS * 1_000,
            max_staleness_us=MAX_BOOK_STALENESS_US,
        )
        if book is None:
            n_no_entry_book += 1; continue
        ap  = [float(x) for x in book["ap"]]
        asz = [float(x) for x in book["asz"]]
        bp  = [float(x) for x in book["bp"]]
        best_ask = ap[0] if ap and np.isfinite(ap[0]) else float("nan")
        best_bid = bp[0] if bp and np.isfinite(bp[0]) else float("nan")
        if not (np.isfinite(best_ask) and np.isfinite(best_bid)
                and best_ask > best_bid + 1e-9):
            n_qty_skip += 1; continue
        if best_ask < QTY_MIN_PRICE or best_ask > QTY_MAX_PRICE:
            n_qty_skip += 1; continue
        if (best_ask - best_bid) > 0.02:
            n_qty_skip += 1; continue
        won = bool(r.won)
        mid = round((best_bid + best_ask) / 2.0, 2)
        # candidate placements (only those strictly inside the spread)
        candidates = {
            "P_bid":       best_bid,
            "P_bid+1":     round(best_bid + TICK, 2),
            "P_mid":       mid,
            "P_ask-1":     round(best_ask - TICK, 2),
        }
        # finite ladder for taker baseline
        ladder_p, ladder_s = [], []
        for p, s in zip(ap, asz):
            if not (np.isfinite(p) and np.isfinite(s) and 0 < p < 1 and s > 0):
                break
            ladder_p.append(p); ladder_s.append(s)
        if not ladder_p:
            n_qty_skip += 1; continue

        for nU in NOTIONALS_USD:
            # taker baseline
            vwap_t, sh_t, usd_t, lev_t, under_t = book_walk_fill(
                ladder_p, ladder_s, float(nU), side="buy",
            )
            pnl_t = pnl_taker_2pct(sh_t, usd_t, won) if sh_t > 0 else 0.0

            for name, P in candidates.items():
                # require limit strictly below best_ask (otherwise it crosses
                # = becomes a taker)
                if P >= best_ask - 1e-9:
                    continue
                filled, fill_ts, dt_us = simulate_maker(
                    books, r.slug, outcome_side, fire_us, slot_end_us, P,
                )
                if filled:
                    shares_m = nU / P
                    pnl_m = pnl_maker(shares_m, P, won)
                else:
                    shares_m = 0.0
                    pnl_m = 0.0
                out.append({
                    "sleeve": r.sleeve, "strategy": r.strategy, "cell": r.cell,
                    "asset": asset, "slug": r.slug, "fire_us": fire_us,
                    "signal": r.signal, "won": won,
                    "best_ask": best_ask, "best_bid": best_bid, "mid": mid,
                    "notional": nU,
                    "placement": name, "limit_price": P,
                    "filled": filled,
                    "fill_dt_s": (dt_us / 1e6) if dt_us is not None else None,
                    "shares_maker": shares_m, "pnl_maker": pnl_m,
                    # baseline (constant across placements at the same notional)
                    "vwap_taker": float(vwap_t), "shares_taker": float(sh_t),
                    "usd_taker_filled": float(usd_t), "pnl_taker": float(pnl_t),
                })
        n_done += 1
    print(f"[{asset}] done={n_done}, no_entry_book={n_no_entry_book}, "
          f"qty_skip={n_qty_skip}")
    del books; gc.collect()
    return out


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
        gated = apply_gate(fills, strategy, cell, gate)
        if gated.empty: continue
        gated = gated.copy()
        gated["gate"]   = gate
        gated["sleeve"] = f"{strategy}_{cell}_{gate}"
        rows.append(gated)
    gated_all = pd.concat(rows, ignore_index=True)
    print(f"[gate] {len(gated_all):,} fires across 11 sleeves")

    per_fire = []
    for asset, sub in gated_all.groupby("asset"):
        per_fire.extend(sweep_one_asset(asset, sub))

    out_dir = Path("strategy_lab/markov_filter/_results")
    df = pd.DataFrame(per_fire)
    df.to_csv(out_dir / "maker_per_fire.csv", index=False)
    print(f"\n[write] {len(df):,} per-fire rows → {out_dir / 'maker_per_fire.csv'}")

    # Per (sleeve, placement, notional)
    agg = (df.groupby(["sleeve","placement","notional"], as_index=False)
        .agg(
            n_fires        = ("pnl_maker",    "size"),
            fill_rate_pct  = ("filled",       lambda x: 100*float(x.mean())),
            sum_pnl_maker  = ("pnl_maker",    "sum"),
            sum_pnl_taker  = ("pnl_taker",    "sum"),
            wr_pct         = ("won",          lambda x: 100*float(x.mean())),
            wr_when_filled = ("won",          lambda x: 100*float(x[df.loc[x.index,"filled"]].mean()) if df.loc[x.index,"filled"].any() else np.nan),
            mean_fill_dt_s = ("fill_dt_s",    "mean"),
            mean_limit_px  = ("limit_price",  "mean"),
            mean_taker_vwap= ("vwap_taker",   "mean"),
        )
    )
    agg["maker_lift_$"]   = (agg["sum_pnl_maker"] - agg["sum_pnl_taker"]).round(2)
    agg["maker_lift_pct"] = (100 * (agg["sum_pnl_maker"] - agg["sum_pnl_taker"]) /
                              agg["sum_pnl_taker"].replace(0, np.nan)).round(1)
    for c in ["sum_pnl_maker","sum_pnl_taker","wr_pct","wr_when_filled",
              "fill_rate_pct","mean_fill_dt_s","mean_limit_px","mean_taker_vwap"]:
        agg[c] = agg[c].round(2)
    agg = agg.sort_values(["sleeve","notional","placement"]).reset_index(drop=True)
    agg.to_csv(out_dir / "maker_per_sleeve.csv", index=False)
    print(f"[write] {len(agg):,} sleeve×placement×notional rows → "
          f"{out_dir / 'maker_per_sleeve.csv'}")

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 240)
    print("\nTop rows (by maker_lift):")
    print(agg.sort_values("maker_lift_$", ascending=False).head(30).to_string(index=False))


if __name__ == "__main__":
    main()
