"""Pre-window hybrid maker→taker, $25 notional.

Rule:
  - For every gated-sleeve fire, attempt MAKER at limit price `P` starting at
    `fire_us + latency`.
  - Hard cutoff = `slot_start_us - 60_000_000` (1 min before the prediction
    window opens).  If maker is not fully filled by that point, the remaining
    shares are taken aggressively at the book that exists at the cutoff.
  - Notional = $25 per fire.

Timing context (why the cutoff is generous for momo):
  - ws_s = slot_start - window_s    (previous slot start)
  - momo_v1 fire_us = ws_s + 120s   → fires `window_s - 120s` before slot_start
                                        (180s pre-window for 5m, 780s for 15m)
  - momo_v2 fire_us = ws_s + 60s    → fires `window_s - 60s`  before slot_start
                                        (240s pre-window for 5m, 840s for 15m)
  - sniper fire_us varies (level-proximity triggered inside ws);
    if (slot_start - fire_us) <= 60s we cannot run the maker phase at all
    and the fire falls back to pure taker at fire_us+latency.

Outputs:
  strategy_lab/markov_filter/_results/prewindow_hybrid_25usd_per_fire.csv
  strategy_lab/markov_filter/_results/prewindow_hybrid_25usd_per_sleeve.csv
"""
from __future__ import annotations
import gc, sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "strategy_lab")
sys.path.insert(0, "data/v4/canonical")

from book_walk import book_walk_fill
from engine_v2 import find_book_strict
from load import load_orderbook_l25_streaming, load_trades


NOTIONAL_USD          = 25.0
TICK                  = 0.01
LATENCY_MS            = 85
PRE_SLOT_BUFFER_US    = 60_000_000      # cutoff = slot_start_us - 60s
MAX_BOOK_STALENESS_US = 60_000_000
PRICE_BUCKET          = 0.005
MIN_MAKER_WINDOW_S    = 30               # need at least 30s for maker phase


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


def add_mtf2(fills):
    kl = pd.read_csv("strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv")
    kl["asset"] = kl["symbol_id"].str.extract(r"BINANCE_SPOT_([A-Z]+)_USDT")
    fills = fills.copy(); fills["mtf2_pass"] = False
    for asset, kg in kl.groupby("asset"):
        kg = kg.sort_values("time_period_start_us").reset_index(drop=True)
        end_us = kg["time_period_start_us"].to_numpy() + 60_000_000
        prices = kg["price_close"].to_numpy()
        m = fills["asset"] == asset; s = fills[m]; fire = s["fire_us"].to_numpy()
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


def queue_ahead_at_price(bp, bsz, P):
    for px, sz in zip(bp, bsz):
        if not (np.isfinite(px) and np.isfinite(sz)): continue
        if abs(px - P) < PRICE_BUCKET: return float(sz)
    return 0.0


def maker_fill_in_window(arr, start_us, end_us, P, queue_ahead, target_shares):
    if arr is None or len(arr[0]) == 0: return 0.0, None
    ts, px, sz, is_sell = arr
    start = int(np.searchsorted(ts, start_us, side="right"))
    if start >= len(ts): return 0.0, None
    cum = 0.0; fill_ts = None; filled = 0.0
    for k in range(start, len(ts)):
        if ts[k] > end_us: break
        if not is_sell[k]: continue
        if abs(px[k] - P) >= PRICE_BUCKET: continue
        cum += sz[k]
        avail = cum - queue_ahead
        if avail > 0 and filled == 0.0: fill_ts = int(ts[k])
        new_filled = min(target_shares, max(0.0, avail))
        if new_filled > filled: filled = new_filled
        if filled >= target_shares - 1e-9: break
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


def ladder_from_book(book):
    if book is None: return [], []
    p, s = [], []
    for px, sz in zip(book["ap"], book["asz"]):
        if not (np.isfinite(px) and np.isfinite(sz) and 0 < px < 1 and sz > 0):
            break
        p.append(float(px)); s.append(float(sz))
    return p, s


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

    print(f"[{asset}] indexing trades by (slug, outcome)...")
    trades_by_key = {}
    trades = trades.sort_values(["slug","outcome","timestamp_us"]).reset_index(drop=True)
    for (slug, outcome), grp in trades.groupby(["slug","outcome"], sort=False):
        trades_by_key[(slug, outcome)] = (
            grp["timestamp_us"].to_numpy(),
            grp["price"].to_numpy(),
            grp["size"].to_numpy(),
            (grp["side"].to_numpy() == "sell").astype(np.uint8),
        )
    del trades; gc.collect()
    print(f"[{asset}] indexed {len(trades_by_key):,} (slug, outcome) keys")

    out = []
    n_done = 0; n_skip_book = 0; n_taker_only = 0
    for r in fires.itertuples(index=False):
        outcome_side = "Up" if r.signal == "UP" else "Down"
        fire_us       = int(r.fire_us)
        slot_start_us = (int(r.ws_s) + int(r.window_s)) * 1_000_000
        slot_end_us   = (int(r.ws_s) + 2 * int(r.window_s)) * 1_000_000
        maker_cutoff_us = slot_start_us - PRE_SLOT_BUFFER_US

        # entry book at fire_us + latency
        entry = find_book_strict(
            books, r.slug, outcome_side, fire_us + LATENCY_MS * 1_000,
            max_staleness_us=MAX_BOOK_STALENESS_US,
        )
        if entry is None:
            n_skip_book += 1; continue
        ap  = [float(x) for x in entry["ap"]]
        asz = [float(x) for x in entry["asz"]]
        bp  = [float(x) for x in entry["bp"]]
        bsz = [float(x) for x in entry["bsz"]]
        if not ap or not bp or not np.isfinite(ap[0]) or not np.isfinite(bp[0]):
            n_skip_book += 1; continue
        best_ask, best_bid = ap[0], bp[0]
        if best_ask <= best_bid or best_ask < 0.05 or best_ask > 0.95:
            n_skip_book += 1; continue
        if (best_ask - best_bid) > 0.02:
            n_skip_book += 1; continue
        won = bool(r.won)
        mid = round((best_bid + best_ask) / 2.0, 2)

        # entry ladder (for pure-taker baseline at fire_us)
        ladder_entry_p, ladder_entry_s = [], []
        for p, s in zip(ap, asz):
            if not (np.isfinite(p) and np.isfinite(s) and 0 < p < 1 and s > 0):
                break
            ladder_entry_p.append(p); ladder_entry_s.append(s)
        if not ladder_entry_p:
            n_skip_book += 1; continue

        pre_window_s = (slot_start_us - fire_us) / 1e6
        maker_window_s = (maker_cutoff_us - fire_us - LATENCY_MS * 1_000) / 1e6

        # Pure-taker baseline
        vwap_t, sh_t, usd_t, _, _ = book_walk_fill(
            ladder_entry_p, ladder_entry_s, NOTIONAL_USD, side="buy"
        )
        pnl_taker_baseline = pnl_taker_2pct(sh_t, usd_t, won)

        # Can the maker phase run at all?
        maker_feasible = maker_window_s >= MIN_MAKER_WINDOW_S
        trades_arr = trades_by_key.get((r.slug, outcome_side))

        # Maker placement candidates
        candidates = {
            "P_bid":   round(best_bid, 2),
            "P_bid+1": round(best_bid + TICK, 2),
            "P_mid":   mid,
            "P_ask-1": round(best_ask - TICK, 2),
        }

        for name, P in candidates.items():
            if P >= best_ask - 1e-9 or P <= 0:
                continue
            q_ahead = (bsz[0] if abs(P - best_bid) < PRICE_BUCKET
                       else queue_ahead_at_price(bp, bsz, P))
            target_sh = NOTIONAL_USD / P

            # ---- Maker phase ----
            if maker_feasible and trades_arr is not None:
                start_us = fire_us + LATENCY_MS * 1_000
                fill_sh, fill_ts = maker_fill_in_window(
                    trades_arr, start_us, maker_cutoff_us,
                    P, q_ahead, target_sh,
                )
            else:
                fill_sh, fill_ts = 0.0, None

            pnl_maker_part = pnl_maker(fill_sh, P, won)

            # ---- Taker fallback at maker_cutoff_us ----
            rem_sh = max(0.0, target_sh - fill_sh)
            if rem_sh > 0:
                if maker_feasible:
                    book_cut = find_book_strict(
                        books, r.slug, outcome_side, maker_cutoff_us,
                        max_staleness_us=MAX_BOOK_STALENESS_US,
                    )
                else:
                    book_cut = entry           # falls back to fire_us book
                lp, ls = ladder_from_book(book_cut)
                if lp:
                    # USD needed to take `rem_sh` shares at best level guess
                    rem_usd = rem_sh * lp[-1]
                    vwap_f, sh_f, usd_f, _, _ = book_walk_fill(
                        lp, ls, float(rem_usd), side="buy"
                    )
                    sh_f = min(sh_f, rem_sh)
                    usd_f = sh_f * (vwap_f if vwap_f > 0 else 0.0)
                    pnl_taker_part = pnl_taker_2pct(sh_f, usd_f, won)
                else:
                    sh_f, usd_f, vwap_f = 0.0, 0.0, 0.0
                    pnl_taker_part = 0.0
            else:
                sh_f, usd_f, vwap_f, pnl_taker_part = 0.0, 0.0, 0.0, 0.0
                book_cut = None

            pnl_hyb = pnl_maker_part + pnl_taker_part
            total_filled = fill_sh + sh_f
            avg_px = ((fill_sh * P + sh_f * vwap_f) / max(total_filled, 1e-9))

            out.append({
                "sleeve": r.sleeve, "strategy": r.strategy, "cell": r.cell,
                "asset": asset, "slug": r.slug, "fire_us": fire_us,
                "signal": r.signal, "won": won,
                "pre_window_s": round(pre_window_s, 1),
                "maker_window_s": round(maker_window_s, 1),
                "maker_feasible": maker_feasible,
                "best_ask": best_ask, "best_bid": best_bid, "mid": mid,
                "placement": name, "limit_price": P,
                "queue_ahead_shares": round(q_ahead, 2),
                "target_shares":      round(target_sh, 2),
                "maker_fill_shares":  round(fill_sh, 3),
                "maker_fill_frac":    round(fill_sh / target_sh, 3),
                "maker_fill_dt_s":    round((fill_ts - fire_us) / 1e6, 1) if fill_ts else None,
                "fallback_shares":    round(sh_f, 3),
                "fallback_vwap":      round(vwap_f, 3),
                "total_filled":       round(total_filled, 3),
                "avg_entry_px":       round(avg_px, 3),
                "pnl_maker_part":     round(pnl_maker_part, 3),
                "pnl_taker_part":     round(pnl_taker_part, 3),
                "pnl_hybrid":         round(pnl_hyb, 3),
                "pnl_pure_taker":     round(pnl_taker_baseline, 3),
                "taker_vwap":         round(vwap_t, 3),
            })
        n_done += 1
        if not maker_feasible: n_taker_only += 1
    print(f"[{asset}] done={n_done}, skipped_book={n_skip_book}, "
          f"taker_only_window={n_taker_only}")
    del books, trades_by_key; gc.collect()
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
    df.to_csv(out_dir / "prewindow_hybrid_25usd_per_fire.csv", index=False)
    print(f"\n[write] {len(df):,} rows → prewindow_hybrid_25usd_per_fire.csv")

    g = df.groupby(["sleeve","placement"], as_index=False)
    agg = g.agg(
        n_fires        = ("pnl_hybrid",         "size"),
        wr_pct         = ("won",                lambda x: 100*float(x.mean())),
        pre_window_s   = ("pre_window_s",       "mean"),
        maker_feas_pct = ("maker_feasible",     lambda x: 100*float(x.mean())),
        queue_ahead    = ("queue_ahead_shares", "mean"),
        target_sh      = ("target_shares",      "mean"),
        limit_px       = ("limit_price",        "mean"),
        taker_vwap     = ("taker_vwap",         "mean"),
        avg_entry_px   = ("avg_entry_px",       "mean"),
        maker_fill_pct = ("maker_fill_frac",    "mean"),
        maker_zero_pct = ("maker_fill_shares",  lambda x: 100*float((x==0).mean())),
        maker_full_pct = ("maker_fill_frac",    lambda x: 100*float((x >= 0.999).mean())),
        pnl_maker_part = ("pnl_maker_part",     "sum"),
        pnl_taker_part = ("pnl_taker_part",     "sum"),
        pnl_hybrid     = ("pnl_hybrid",         "sum"),
        pnl_pure_taker = ("pnl_pure_taker",     "sum"),
    )
    agg["hyb_lift_$"]   = (agg["pnl_hybrid"] - agg["pnl_pure_taker"]).round(2)
    agg["hyb_lift_pct"] = (100 * (agg["pnl_hybrid"] - agg["pnl_pure_taker"])
                            / agg["pnl_pure_taker"].replace(0, np.nan)).round(1)
    for c in ["wr_pct","pre_window_s","maker_feas_pct","queue_ahead","target_sh",
              "limit_px","taker_vwap","avg_entry_px","maker_fill_pct",
              "maker_zero_pct","maker_full_pct","pnl_maker_part","pnl_taker_part",
              "pnl_hybrid","pnl_pure_taker"]:
        agg[c] = agg[c].round(2)
    agg = agg.sort_values(["sleeve","placement"]).reset_index(drop=True)
    agg.to_csv(out_dir / "prewindow_hybrid_25usd_per_sleeve.csv", index=False)
    print(f"[write] {len(agg):,} rows → prewindow_hybrid_25usd_per_sleeve.csv")

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 260)
    print("\nTop 20 (sleeve × placement) by hybrid lift over pure taker:")
    print(agg.sort_values("hyb_lift_$", ascending=False).head(20).to_string(index=False))


if __name__ == "__main__":
    main()
