"""Capacity sweep — walk L25 at multiple notional sizes per gated-sleeve fire.

For each of the 11 gated sleeves (from TV_AGENT_SHADOW_DEPLOY spec) and each
candidate notional in NOTIONALS, walk the L25 book at fire_us + latency,
compute the entry vwap / shares / usd, then apply hold pnl with 2%-on-profit
fees (production rule, CLAUDE.md). Aggregate per (sleeve, notional) to find
the size where total $ is maximised before slippage erodes the edge.

Outputs:
  strategy_lab/markov_filter/_results/capacity_sweep_per_fire.csv
  strategy_lab/markov_filter/_results/capacity_sweep_per_sleeve.csv
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
from engine_v2 import (
    LiveMimicConfig, LegacyConfig, find_book_strict, book_event_count,
)
from load import load_orderbook_l25_streaming


# Notional sweep — geometric ladder from production stake ($25) up to $10k.
NOTIONALS_USD = [25, 50, 100, 250, 500, 1_000, 2_500, 5_000, 10_000]

# 11 gated sleeves from TV_AGENT_SHADOW_DEPLOY spec.
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


def add_mtf2(fills: pd.DataFrame) -> pd.DataFrame:
    """Same MTF2 derivation as robustness_gated_sleeves.py."""
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


def apply_gate(fills: pd.DataFrame, strategy: str, cell: str, gate: str) -> pd.DataFrame:
    df = fills[(fills["strategy"] == strategy) & (fills["cell_key"] == cell)].copy()
    if df.empty: return df
    df = df[df["hour"].isin(set(HOD_TOP8[(strategy, cell)]))]
    if "MTF2" in gate: df = df[df["mtf2_pass"]]
    if "M5va" in gate: df = df[df["markov_pass_w20_5m_voladaptive"]]
    return df


def pnl_legacy_2pct(shares: float, usd: float, won: bool) -> float:
    """Production fee rule (CLAUDE.md): 2% on profit only, winning leg only."""
    if won:
        gross = shares * 1.0
        profit = gross - usd
        return (profit * 0.98) if profit > 0 else (gross - usd)
    return -usd


def sweep_one_asset(asset: str, fires: pd.DataFrame, cfg) -> list[dict]:
    """Walk L25 at every NOTIONALS_USD for every fire in `fires` for this asset."""
    slugs = set(fires["slug"].unique())
    print(f"[{asset}] loading L25 for {len(slugs):,} unique slugs...")
    books = load_orderbook_l25_streaming(
        asset, slugs=slugs, subsample_1hz=True,
        min_ts_us=int(fires["fire_us"].min()) - 1_800_000_000,
        max_ts_us=int(fires["fire_us"].max()) + 1_800_000_000,
    )
    print(f"[{asset}] {len(books):,} (slug, outcome) book series loaded")

    out = []
    n_skip_book = 0; n_skip_qty = 0; n_skip_sparse = 0; n_done = 0
    for r in fires.itertuples(index=False):
        outcome_side = "Up" if r.signal == "UP" else "Down"
        slot_start_us = (int(r.ws_s) + int(r.window_s)) * 1_000_000  # approx
        slot_end_us   = slot_start_us + int(r.window_s) * 1_000_000
        n_events = book_event_count(books, r.slug, outcome_side,
                                     slot_start_us, slot_end_us)
        if n_events < cfg.min_book_events:
            n_skip_sparse += 1; continue
        book = find_book_strict(books, r.slug, outcome_side,
                                 int(r.fire_us) + int(cfg.latency_ms * 1_000),
                                 max_staleness_us=cfg.max_book_staleness_us)
        if book is None:
            n_skip_book += 1; continue
        ap  = [float(x) for x in book["ap"]]
        asz = [float(x) for x in book["asz"]]
        bp  = [float(x) for x in book["bp"]]
        bid0 = bp[0] if bp and np.isfinite(bp[0]) else float("nan")
        best_ask = ap[0] if ap and np.isfinite(ap[0]) else float("nan")
        if not np.isfinite(best_ask) or best_ask < QTY_MIN_PRICE or best_ask > QTY_MAX_PRICE:
            n_skip_qty += 1; continue
        if np.isfinite(best_ask) and np.isfinite(bid0) and (best_ask - bid0) > 0.02:
            n_skip_qty += 1; continue
        # Pre-extract finite ladder for repeated walks
        ladder_p, ladder_s = [], []
        for p, s in zip(ap, asz):
            if not (np.isfinite(p) and np.isfinite(s) and 0 < p < 1 and s > 0):
                break
            ladder_p.append(p); ladder_s.append(s)
        if not ladder_p: continue
        depth_usd = sum(p*s for p, s in zip(ladder_p, ladder_s))
        won = bool(r.won)
        # Walk at every notional
        for nU in NOTIONALS_USD:
            vwap, shares, usd, levels, under = book_walk_fill(
                ladder_p, ladder_s, float(nU), side="buy",
            )
            if shares <= 0 or usd <= 0:
                continue
            fill_rate = usd / nU
            slippage_bp = (vwap - best_ask) / best_ask * 1e4 if best_ask > 0 else 0.0
            pnl = pnl_legacy_2pct(shares, usd, won)
            out.append({
                "asset": asset, "tf": r.tf, "cell_key": r.cell_key,
                "strategy": r.strategy, "gate": r.gate, "sleeve": r.sleeve,
                "slug": r.slug, "fire_us": int(r.fire_us),
                "signal": r.signal, "outcome": r.outcome, "won": won,
                "best_ask": best_ask, "bid0": bid0, "l25_depth_usd": depth_usd,
                "notional_target": nU,
                "vwap": float(vwap), "shares": float(shares), "usd_filled": float(usd),
                "fill_rate": float(fill_rate), "levels": int(levels),
                "under": bool(under), "slippage_bp": float(slippage_bp),
                "pnl": float(pnl),
            })
        n_done += 1
    print(f"[{asset}] done={n_done}, sparse_skip={n_skip_sparse}, "
          f"book_skip={n_skip_book}, qty_skip={n_skip_qty}")
    del books; gc.collect()
    return out


def main():
    # ---- 1. Reconstruct the gated-sleeve fires from fills.csv ----
    fills = pd.read_csv("strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv")
    fills["fire_ts"]  = pd.to_datetime(fills["fire_us"], unit="us", utc=True)
    fills["hour"]     = fills["fire_ts"].dt.hour
    fills["cell_key"] = fills["asset"].str.lower() + "_" + fills["tf"]
    # F7-off universe (matches robustness runner)
    fills = fills[fills["f7_mode"] == "off"].copy()
    print(f"[load] {len(fills):,} F7-off fires before gating")
    fills = add_mtf2(fills)

    # window_s needed for sparse-book check (slot duration)
    fills["window_s"] = np.where(fills["tf"] == "5m", 300, 900)

    sleeve_rows = []
    for strategy, cell, gate in SLEEVES:
        gated = apply_gate(fills, strategy, cell, gate)
        if gated.empty: continue
        gated = gated.copy()
        gated["gate"]   = gate
        gated["sleeve"] = f"{strategy}_{cell}_{gate}"
        sleeve_rows.append(gated)
    gated_all = pd.concat(sleeve_rows, ignore_index=True)
    print(f"[gate] {len(gated_all):,} gated-sleeve fires across 11 sleeves")
    print(gated_all.groupby("sleeve").size().to_string())

    # ---- 2. Walk L25 per asset ----
    cfg = LegacyConfig()  # 2%-on-profit fee model (production convention)
    print(f"\n[cfg] using {type(cfg).__name__}: latency_ms={cfg.latency_ms}, "
          f"max_book_staleness_us={cfg.max_book_staleness_us}, "
          f"min_book_events={cfg.min_book_events}, fee_model={cfg.fee_model}")

    per_fire_rows = []
    for asset, sub in gated_all.groupby("asset"):
        rows = sweep_one_asset(asset, sub, cfg)
        per_fire_rows.extend(rows)
        del rows

    per_fire = pd.DataFrame(per_fire_rows)
    out_dir = Path("strategy_lab/markov_filter/_results")
    out_dir.mkdir(parents=True, exist_ok=True)
    per_fire.to_csv(out_dir / "capacity_sweep_per_fire.csv", index=False)
    print(f"\n[write] {len(per_fire):,} per-fire rows → "
          f"{out_dir / 'capacity_sweep_per_fire.csv'}")

    # ---- 3. Aggregate per (sleeve, notional) ----
    if per_fire.empty:
        print("NO ROWS — abort"); return
    agg = (per_fire.groupby(["sleeve","notional_target"], as_index=False)
        .agg(
            n_fires           = ("pnl",          "size"),
            sum_pnl_usd       = ("pnl",          "sum"),
            per_trade_pnl     = ("pnl",          "mean"),
            wr_pct            = ("won",          lambda x: 100*float(x.mean())),
            mean_fill_rate    = ("fill_rate",    "mean"),
            mean_slippage_bp  = ("slippage_bp",  "mean"),
            mean_levels       = ("levels",       "mean"),
            median_depth_usd  = ("l25_depth_usd","median"),
            share_underfilled = ("under",        lambda x: 100*float(x.mean())),
            sum_usd_filled    = ("usd_filled",   "sum"),
        )
    )
    agg["roi_on_filled_pct"] = (100 * agg["sum_pnl_usd"] / agg["sum_usd_filled"]).round(2)
    # round
    for c in ["sum_pnl_usd","per_trade_pnl","wr_pct","mean_fill_rate",
              "mean_slippage_bp","mean_levels","median_depth_usd",
              "share_underfilled"]:
        if c in agg.columns:
            agg[c] = agg[c].round(2)
    agg = agg.sort_values(["sleeve","notional_target"]).reset_index(drop=True)
    agg.to_csv(out_dir / "capacity_sweep_per_sleeve.csv", index=False)
    print(f"[write] {len(agg):,} sleeve×notional rows → "
          f"{out_dir / 'capacity_sweep_per_sleeve.csv'}")

    # ---- 4. Pick optimal notional per sleeve ----
    def pick(df_sleeve):
        if df_sleeve.empty: return None
        # primary: maximise sum_pnl_usd; tie-break: largest size still > 80% of max
        max_sum = df_sleeve["sum_pnl_usd"].max()
        cand = df_sleeve[df_sleeve["sum_pnl_usd"] >= 0.80 * max_sum]
        if cand.empty: cand = df_sleeve
        # Among candidates pick the LARGEST notional that still keeps fill_rate ≥ 0.95
        cand = cand[cand["mean_fill_rate"] >= 0.95]
        if cand.empty: cand = df_sleeve
        return cand.sort_values("notional_target", ascending=False).iloc[0]
    opt = (agg.groupby("sleeve", group_keys=False)
              .apply(pick, include_groups=False)
              .reset_index())
    opt.to_csv(out_dir / "capacity_sweep_optimal.csv", index=False)
    print(f"[write] optimal-per-sleeve → "
          f"{out_dir / 'capacity_sweep_optimal.csv'}")
    print("\nOPTIMAL NOTIONAL PER SLEEVE:")
    print(opt.to_string(index=False))

    # ---- 5. Print compact per-sleeve curve table ----
    print("\nCAPACITY CURVE — sum_pnl_usd by notional_target ($):")
    piv = agg.pivot(index="sleeve", columns="notional_target",
                     values="sum_pnl_usd")
    print(piv.to_string())


if __name__ == "__main__":
    main()
