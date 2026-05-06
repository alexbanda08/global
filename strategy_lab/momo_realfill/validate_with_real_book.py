"""validate_with_real_book — re-run the momo HEDGE/SELL backtest against the
RAW L25 orderbook (every snapshot, all 25 levels) to test if those exits would
actually have liquidity in production.

Existing backtest (`extended_backtest_with_robustness.py`):
    - Entry: t+120s, walks tier1 entry book (already L25 from parquet)
    - Exit monitoring: 10s-bucketed L10 book CSV → finds rev_bp triggers,
      walks opposite-asks for HEDGE or own-bids for SELL
    - Per cell: stats for HOLD vs HEDGE vs SELL

This validator:
    - Same entry path (REUSE simulate() logic for entry walk)
    - REPLACES bucket_book lookup with snapshot-precise OrderbookIndex over L25 raw
    - Per fire: records hedge_feasible, sell_feasible, real_pnl, snap_staleness_ms
    - Aggregates per (asset, tf, exit_policy) and writes both per-trade and
      cell-level CSVs + a markdown report.

Outputs:
    strategy_lab/results/meta_classifier/momo_realfill_validation.csv  (cells)
    strategy_lab/results/meta_classifier/momo_realfill_pertrade.csv    (per fire)
    strategy_lab/reports/MOMO_REALFILL_VALIDATION_2026_05_06.md

Usage:
    py -X utf8 -m strategy_lab.momo_realfill.validate_with_real_book
    py -X utf8 -m strategy_lab.momo_realfill.validate_with_real_book --asset sol
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

from book_walk import book_walk_fill                    # noqa: E402
from polymarket_stats import equity_curve_stats         # noqa: E402
from loaders.raw_orderbook_l25 import (                 # noqa: E402
    load_orderbook_l25_raw,
    OrderbookIndex,
    has_liquidity,
)

# Reuse from existing momo backtest (no duplication)
from extended_backtest_with_robustness import (         # noqa: E402
    NOTIONAL_USD, FEE_RATE, SPREAD_FILTER,
    load_klines, asof, load_tier1_entries,
    sell_at_bid,
)

REFRESH_NEW = ROOT / "data" / "v4" / "refresh_2026_05_06"
REFRESH_OLD = ROOT / "data" / "v4" / "refresh_2026_05_02"

OUT_DIR = ROOT / "strategy_lab" / "results" / "meta_classifier"
REPORT  = ROOT / "strategy_lab" / "reports" / "MOMO_REALFILL_VALIDATION_2026_05_06.md"


# ---------------------------------------------------------------------------
# Universe loader (compat with our minimal market_resolutions_full.csv)
# ---------------------------------------------------------------------------

def load_universe_compat() -> pd.DataFrame:
    """Load universe from our minimal pull. Builds the columns the engine needs.

    Our pulled `market_resolutions_full.csv` has just (slug, outcome, recorded_at, source).
    Add: window_start_unix (extracted from slug epoch), outcome_up (Up=1/Down=0),
         timeframe (from slug), asset (from slug).
    """
    path = REFRESH_NEW / "market_resolutions_full.csv"
    df = pd.read_csv(path)

    # asset and timeframe from slug like 'btc-updown-5m-1777824000'
    parts = df["slug"].str.split("-", n=3, expand=True)
    df["asset"] = parts[0]
    df["timeframe"] = parts[2]
    df["window_start_unix"] = pd.to_numeric(parts[3], errors="coerce")

    # outcome_up
    df["outcome_up"] = (df["outcome"].str.lower() == "up").astype(int)

    df = df.dropna(subset=["window_start_unix", "asset", "timeframe"]).copy()
    df = df[df["asset"].isin(("btc", "eth", "sol"))]
    df = df[df["timeframe"].isin(("5m", "15m"))]
    df["window_start_unix"] = df["window_start_unix"].astype("int64")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Replacement simulate(): uses L25 OrderbookIndex for exit monitoring
# ---------------------------------------------------------------------------

# Map outcome string to outcome_id used in raw orderbook
# Polymarket convention: Up=0, Down=1 (consistent across both files)
_OUTCOME_TO_ID = {"Up": 0, "Down": 1, "up": 0, "down": 1}


def _outcome_id(outcome: str) -> int:
    return _OUTCOME_TO_ID[outcome]


def simulate_l25(
    row: pd.Series,
    k1m: pd.DataFrame,
    entry_book: dict,
    ob_idx: OrderbookIndex,
    max_bucket: int,
    policy: str,
    rev_bp: int = 5,
    spread_filter: float | None = None,
) -> dict | None:
    """Mirror of `extended_backtest_with_robustness.simulate()` but exit monitoring
    walks the raw L25 OrderbookIndex at exact ws + bucket*10 timestamps instead of
    looking up a 10s-bucket aggregated CSV.

    Per-snap diagnostics:
        snap_staleness_ms_max — biggest gap (query - snap) ms across the trigger lookup
        hedge_feasible        — opposite-side asks present at trigger ts
        sell_feasible         — own-side bid >= entry vwap - threshold
        n_rev_triggers        — # of buckets where rev_bp threshold crossed
    """
    sig = int(row.signal)
    held = "Up" if sig == 1 else "Down"
    other = "Down" if sig == 1 else "Up"
    held_id = _outcome_id(held)
    other_id = _outcome_id(other)

    # Entry book — same as existing code (uses L25 tier1 parquet)
    if (row.slug, held) not in entry_book:
        return None
    ask_p, ask_s, bid_p, bid_s = entry_book[(row.slug, held)]
    if spread_filter is not None and len(ask_p) and len(bid_p):
        if np.isfinite(ask_p[0]) and np.isfinite(bid_p[0]) and (ask_p[0] - bid_p[0]) > spread_filter:
            return {"skipped_spread": True}
    vwap_e, shares_e, usd_e, _, under_e = book_walk_fill(ask_p, ask_s, NOTIONAL_USD)
    if shares_e <= 0:
        return None
    if under_e and usd_e < NOTIONAL_USD * 0.5:
        return {"skipped_thin": True}

    ws = int(row.window_start_unix)
    asset_at_entry = asof(k1m, ws + 120)

    exit_event = None
    n_rev_triggers = 0
    snap_staleness_max_us = 0
    hedge_feasible_at_first_trigger: bool | None = None
    sell_feasible_at_first_trigger: bool | None = None

    if policy != "HOLD":
        for bucket in range(13, max_bucket + 1):
            ts_in_s = ws + bucket * 10
            ts_in_us = ts_in_s * 1_000_000
            a_now = asof(k1m, ts_in_s)
            if not (np.isfinite(asset_at_entry) and np.isfinite(a_now)):
                continue
            bp_rev = (a_now - asset_at_entry) / asset_at_entry * 10000.0
            trig = (sig == 1 and bp_rev <= -rev_bp) or (sig == 0 and bp_rev >= rev_bp)
            if not trig:
                continue
            n_rev_triggers += 1

            # --- Look up real L25 books at this ts ---
            if policy == "HEDGE":
                # opposite-side ASKS for hedge buy
                h_ask_p, h_ask_s, snap_ts = ob_idx.book_at_with_ts(
                    row.slug, other_id, ts_in_us, side="ask"
                )
                if snap_ts is not None:
                    staleness = ts_in_us - snap_ts
                    if staleness > snap_staleness_max_us:
                        snap_staleness_max_us = staleness
                feasible = (
                    h_ask_p is not None
                    and len(h_ask_p) > 0
                    and h_ask_p[0] is not None
                    and np.isfinite(h_ask_p[0])
                    and 0 < h_ask_p[0] < 1
                )
                if hedge_feasible_at_first_trigger is None:
                    hedge_feasible_at_first_trigger = feasible
                if not feasible:
                    continue
                top = float(h_ask_p[0])
                target_h = shares_e * top
                vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(h_ask_p, h_ask_s, target_h)
                if shares_h > 0:
                    if shares_h < shares_e * 0.95 and not under_h:
                        # second pass: rescale to actual vwap
                        vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(
                            h_ask_p, h_ask_s, shares_e * vwap_h
                        )
                    exit_event = ("hedge", bucket, dict(
                        vwap_h=vwap_h, shares_h=shares_h, usd_h=usd_h,
                        snap_ts=snap_ts,
                    ))
                    break

            elif policy == "SELL":
                # own-side BIDS for sell
                b_p, b_s, snap_ts = ob_idx.book_at_with_ts(
                    row.slug, held_id, ts_in_us, side="bid"
                )
                if snap_ts is not None:
                    staleness = ts_in_us - snap_ts
                    if staleness > snap_staleness_max_us:
                        snap_staleness_max_us = staleness
                feasible = (
                    b_p is not None
                    and len(b_p) > 0
                    and b_p[0] is not None
                    and np.isfinite(b_p[0])
                    and 0 < b_p[0] < 1
                )
                if sell_feasible_at_first_trigger is None:
                    sell_feasible_at_first_trigger = feasible
                if not feasible:
                    continue
                sv, sg = sell_at_bid(np.asarray(b_p), np.asarray(b_s), shares_e)
                if np.isfinite(sv) and sg > 0:
                    exit_event = ("sell", bucket, dict(
                        sell_vwap=sv, sell_gross=sg, snap_ts=snap_ts,
                    ))
                    break

    won = (sig == int(row.outcome_up))

    # PnL resolution
    if exit_event is None:
        if won:
            profit = shares_e * 1.0 - usd_e
            fee = profit * FEE_RATE if profit > 0 else 0.0
            pnl = profit - fee
        else:
            pnl = -usd_e
        return dict(
            pnl=pnl, cost=usd_e, vwap_e=vwap_e, exit_reason="hold", sig_won=won,
            n_rev_triggers=n_rev_triggers,
            hedge_feasible=hedge_feasible_at_first_trigger,
            sell_feasible=sell_feasible_at_first_trigger,
            snap_staleness_ms=snap_staleness_max_us / 1000.0,
        )

    kind, eb, ed = exit_event
    if kind == "hedge":
        cost = usd_e + ed["usd_h"]
        if won:
            gross = shares_e * 1.0
            fee = shares_e * (1.0 - vwap_e) * FEE_RATE
        else:
            gross = ed["shares_h"] * 1.0
            fee = ed["shares_h"] * (1.0 - ed["vwap_h"]) * FEE_RATE
        return dict(
            pnl=gross - cost - fee, cost=cost, vwap_e=vwap_e, exit_reason="hedge",
            sig_won=won, n_rev_triggers=n_rev_triggers,
            hedge_feasible=True, sell_feasible=None,
            snap_staleness_ms=snap_staleness_max_us / 1000.0,
            hedge_bucket=eb, hedge_vwap=ed["vwap_h"],
        )

    profit = ed["sell_gross"] - usd_e
    fee = max(profit, 0) * FEE_RATE
    return dict(
        pnl=profit - fee, cost=usd_e, vwap_e=vwap_e, exit_reason="sell",
        sig_won=won, n_rev_triggers=n_rev_triggers,
        hedge_feasible=None, sell_feasible=True,
        snap_staleness_ms=snap_staleness_max_us / 1000.0,
        sell_bucket=eb, sell_vwap=ed["sell_vwap"],
    )


# ---------------------------------------------------------------------------
# Per-cell runner
# ---------------------------------------------------------------------------

def run_cell_l25(
    df: pd.DataFrame,
    k1m: pd.DataFrame,
    entry_book: dict,
    ob_idx: OrderbookIndex,
    policy: str,
    label: str,
    asset: str,
) -> dict:
    pnls, costs, ws_list, vwaps = [], [], [], []
    sk_thin = sk_no_book = sk_spread = wins = 0
    n_hold = n_hedge = n_sell = 0
    feasible_hedge = feasible_sell = 0
    n_with_trigger = 0
    stalenesses_ms = []
    per_trade = []

    for _, row in df.iterrows():
        max_b = 89 if row.timeframe == "15m" else 29
        r = simulate_l25(
            row, k1m, entry_book, ob_idx, max_b, policy,
            spread_filter=SPREAD_FILTER[asset],
        )
        if r is None:
            sk_no_book += 1
            continue
        if r.get("skipped_spread"):
            sk_spread += 1
            continue
        if r.get("skipped_thin"):
            sk_thin += 1
            continue

        pnls.append(r["pnl"])
        costs.append(r["cost"])
        ws_list.append(int(row.window_start_unix))
        vwaps.append(r["vwap_e"])
        if r["sig_won"]:
            wins += 1
        if r["exit_reason"] == "hold":
            n_hold += 1
        elif r["exit_reason"] == "hedge":
            n_hedge += 1
        elif r["exit_reason"] == "sell":
            n_sell += 1
        if r.get("n_rev_triggers", 0) > 0:
            n_with_trigger += 1
        if r.get("hedge_feasible") is True:
            feasible_hedge += 1
        if r.get("sell_feasible") is True:
            feasible_sell += 1
        stalenesses_ms.append(r.get("snap_staleness_ms", 0.0))

        per_trade.append(dict(
            asset=asset, slug=row.slug, ws_s=int(row.window_start_unix),
            tf=row.timeframe, signal=int(row.signal), outcome_up=int(row.outcome_up),
            policy=policy, exit_reason=r["exit_reason"], pnl=r["pnl"],
            cost=r["cost"], vwap_e=r["vwap_e"],
            n_rev_triggers=r.get("n_rev_triggers", 0),
            hedge_feasible=r.get("hedge_feasible"),
            sell_feasible=r.get("sell_feasible"),
            snap_staleness_ms=r.get("snap_staleness_ms", 0.0),
        ))

    pnls = np.array(pnls)
    n = len(pnls)
    if n == 0:
        return {"label": label, "n": 0, "per_trade": []}

    eq = equity_curve_stats(pnls, trade_timestamps=np.array(ws_list, dtype=float))
    return dict(
        label=label, n=n, wins=wins,
        hit=float((pnls > 0).mean()),
        pnl_total=float(pnls.sum()),
        pnl_mean=float(pnls.mean()),
        pnl_std=float(pnls.std()),
        avg_vwap_e=float(np.mean(vwaps)),
        n_hold=n_hold, n_hedge=n_hedge, n_sell=n_sell,
        sk_thin=sk_thin, sk_no_book=sk_no_book, sk_spread=sk_spread,
        sharpe=eq["sharpe"], sortino=eq["sortino"], max_dd=eq["max_dd"],
        # Realfill-specific telemetry
        n_with_trigger=n_with_trigger,
        feasible_hedge=feasible_hedge,
        feasible_sell=feasible_sell,
        feasible_pct=(
            float(feasible_hedge / n_with_trigger) if policy == "HEDGE" and n_with_trigger > 0
            else float(feasible_sell / n_with_trigger) if policy == "SELL" and n_with_trigger > 0
            else None
        ),
        snap_staleness_ms_p50=float(np.median(stalenesses_ms)) if stalenesses_ms else 0.0,
        snap_staleness_ms_p95=float(np.quantile(stalenesses_ms, 0.95)) if stalenesses_ms else 0.0,
        per_trade=per_trade,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", choices=("all", "btc", "eth", "sol"), default="all",
                    help="Which asset(s) to validate (default all)")
    ap.add_argument("--max-fires", type=int, default=None,
                    help="Cap fires per cell for fast iteration (debug)")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1] universe + klines + tier1 entries…")
    uni = load_universe_compat()
    print(f"    universe: {len(uni)} resolved markets ({uni.asset.value_counts().to_dict()})  "
          f"tfs: {uni.timeframe.value_counts().to_dict()}")
    klines = load_klines()

    # Compute asset_ret_2m
    for a in ("btc", "eth", "sol"):
        m = uni.asset == a
        ws_arr = uni.loc[m, "window_start_unix"].astype("int64").values
        p0 = np.array([asof(klines[a], int(w)) for w in ws_arr])
        p2 = np.array([asof(klines[a], int(w) + 120) for w in ws_arr])
        ret_2m = np.log(p2 / p0)
        uni.loc[m, "asset_ret_2m"] = ret_2m
    active = uni[uni["asset_ret_2m"].notna() & np.isfinite(uni["asset_ret_2m"])].copy()
    print(f"    active: {len(active)}")

    # Top-10% |asset_ret_2m| per (asset, tf) → fired
    fired = []
    for a in ("btc", "eth", "sol"):
        for tf in ("5m", "15m"):
            sub = active[(active.asset == a) & (active.timeframe == tf)].copy()
            if len(sub) < 50:
                continue
            thr = sub["asset_ret_2m"].abs().quantile(0.90)
            f = sub[sub["asset_ret_2m"].abs() >= thr].copy()
            f["signal"] = (f["asset_ret_2m"] > 0).astype(int)
            fired.append(f)
    fired_all = pd.concat(fired, ignore_index=True)
    print(f"    fired (top-10%): {len(fired_all)}")

    # Optional cap for fast debug
    if args.max_fires is not None:
        fired_all = fired_all.groupby(["asset", "timeframe"], group_keys=False).head(args.max_fires)
        print(f"    capped to {len(fired_all)} for debug")

    print("[2] tier1 entry books…")
    entry_books = {a: load_tier1_entries(a) for a in ("btc", "eth", "sol")}
    for a in ("btc", "eth", "sol"):
        print(f"    {a}: {len(entry_books[a])} tier1 entries")

    print("[3+4] running per (asset, tf) — load orderbook → index → run cells → free memory")
    assets_to_run = ("btc", "eth", "sol") if args.asset == "all" else (args.asset,)
    results = []
    per_trade_rows = []
    import gc

    for a in assets_to_run:
        for tf in ("5m", "15m"):
            sub = fired_all[(fired_all.asset == a) & (fired_all.timeframe == tf)]
            if len(sub) == 0:
                continue
            slugs_for_at = set(sub["slug"].unique())
            print(f"  [{a}_{tf}] loading L25 raw filtered to {len(slugs_for_at)} slugs…")
            t0 = time.time()
            ob_df = load_orderbook_l25_raw(a, slugs=slugs_for_at)
            print(f"  [{a}_{tf}] loaded {len(ob_df):,} rows in {time.time()-t0:.1f}s — indexing…")
            t0 = time.time()
            ob_idx = OrderbookIndex(ob_df)
            print(f"  [{a}_{tf}] index ready ({time.time()-t0:.1f}s)")

            for policy in ("HOLD", "HEDGE", "SELL"):
                t0 = time.time()
                r = run_cell_l25(
                    sub, klines[a], entry_books[a], ob_idx,
                    policy, f"{a.upper()}_{tf}_{policy}", a,
                )
                per_trade_rows.extend(r.pop("per_trade", []))
                results.append(r)
                if r["n"] > 0:
                    feas = r.get("feasible_pct")
                    feas_s = f"{feas*100:.1f}%" if feas is not None else "—"
                    print(
                        f"    {r['label']:18s}  n={r['n']:4d}  hit={r['hit']*100:5.1f}%  "
                        f"pnl=${r['pnl_total']:+8.2f}  hedged={r['n_hedge']:3d} sells={r['n_sell']:3d}  "
                        f"trigger_n={r['n_with_trigger']:3d}  feasible={feas_s}  "
                        f"snap_p95={r['snap_staleness_ms_p95']:.0f}ms  "
                        f"({time.time()-t0:.1f}s)"
                    )

            # Free orderbook memory before next tf
            del ob_df, ob_idx
            gc.collect()

    # Write outputs
    df_cells = pd.DataFrame([{k: v for k, v in r.items() if k not in ("per_trade",)}
                              for r in results])
    df_cells.to_csv(OUT_DIR / "momo_realfill_validation.csv", index=False)
    print(f"\n[csv] cells → {OUT_DIR / 'momo_realfill_validation.csv'}")
    df_pt = pd.DataFrame(per_trade_rows)
    df_pt.to_csv(OUT_DIR / "momo_realfill_pertrade.csv", index=False)
    print(f"[csv] per-trade → {OUT_DIR / 'momo_realfill_pertrade.csv'}")

    # Compare to existing extended_backtest.csv
    print("\n[5] comparing to extended_backtest.csv (bucketed L10 baseline)")
    bt_path = OUT_DIR / "extended_backtest.csv"
    if not bt_path.exists():
        print(f"    [!] {bt_path} not found — skipping comparison")
        bt = None
    else:
        bt = pd.read_csv(bt_path)
        merged = df_cells.merge(bt, on="label", suffixes=("_l25", "_bt"))
        for _, m in merged.iterrows():
            print(
                f"    {m['label']:18s}  "
                f"L25 n={m['n_l25']:4d} pnl=${m['pnl_total_l25']:+8.2f} hit={m['hit_l25']*100:5.1f}%  |  "
                f"BT n={m['n_bt']:4d} pnl=${m['pnl_total_bt']:+8.2f} hit={m['hit_bt']*100:5.1f}%  "
                f"Δpnl=${m['pnl_total_l25']-m['pnl_total_bt']:+.2f}"
            )

    # Markdown report
    print("\n[6] writing report…")
    write_report(df_cells, bt)


def write_report(df_cells: pd.DataFrame, bt: pd.DataFrame | None) -> None:
    L: list[str] = []
    L.append("# Momo Realfill Validation — L25 raw vs L10 bucketed exit-monitoring\n")
    L.append("**Generated:** 2026-05-06\n")
    L.append("**Scope:** Re-runs the existing momo backtest's HEDGE and SELL exit policies "
             "but replaces the 10s-bucketed L10 exit-monitoring book with the snapshot-precise "
             "L25 raw book pulled from VPS2 on 2026-05-06.\n")
    L.append("**Question answered:** *would HEDGE / SELL exits actually have liquidity in the "
             "real production orderbook at the rev_bp trigger time?*\n")
    L.append("**Reused infrastructure:**\n")
    L.append("- `book_walk.book_walk_fill` (canonical fill simulator)")
    L.append("- `polymarket_stats.equity_curve_stats` (Sharpe/Sortino/MaxDD)")
    L.append("- `extended_backtest_with_robustness.{load_klines, load_tier1_entries, sell_at_bid}`")
    L.append("- `loaders.raw_orderbook_l25.{load_orderbook_l25_raw, OrderbookIndex}` (NEW)\n")

    L.append("## Cell-level results\n")
    L.append("| Cell | n | hit% | total PnL | mean PnL | hedge | sell | rev_n | feasible% | snap_p50 ms | snap_p95 ms |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in df_cells.iterrows():
        if r["n"] == 0:
            continue
        feas = r.get("feasible_pct")
        feas_s = f"{feas*100:.1f}" if feas is not None and not pd.isna(feas) else "—"
        L.append(
            f"| {r['label']} | {r['n']} | {r['hit']*100:.1f} | "
            f"${r['pnl_total']:+.2f} | ${r['pnl_mean']:+.4f} | "
            f"{r['n_hedge']} | {r['n_sell']} | {r.get('n_with_trigger', 0)} | "
            f"{feas_s} | {r['snap_staleness_ms_p50']:.0f} | {r['snap_staleness_ms_p95']:.0f} |"
        )
    L.append("")

    if bt is not None:
        L.append("## L25 vs L10 backtest comparison\n")
        merged = df_cells.merge(bt, on="label", suffixes=("_l25", "_bt"))
        L.append("| Cell | L25 n | L25 PnL | L25 hit% | L10 n | L10 PnL | L10 hit% | Δ PnL | Δ hit% |")
        L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
        for _, m in merged.iterrows():
            d_pnl = m["pnl_total_l25"] - m["pnl_total_bt"]
            d_hit = (m["hit_l25"] - m["hit_bt"]) * 100
            L.append(
                f"| {m['label']} | {m['n_l25']} | ${m['pnl_total_l25']:+.2f} | "
                f"{m['hit_l25']*100:.1f} | {m['n_bt']} | ${m['pnl_total_bt']:+.2f} | "
                f"{m['hit_bt']*100:.1f} | ${d_pnl:+.2f} | {d_hit:+.1f} |"
            )
        L.append("")

    L.append("## Liquidity feasibility analysis\n")
    L.append("**Definition:** for HEDGE cells, `feasible_pct` = % of fires where, at the FIRST rev_bp trigger, ")
    L.append("the opposite-side ask book had ≥1 valid (price ∈ (0,1)) level. Same for SELL on own-side bids.\n")
    hedge_rows = [r for _, r in df_cells.iterrows() if r["label"].endswith("_HEDGE") and r["n"] > 0]
    sell_rows = [r for _, r in df_cells.iterrows() if r["label"].endswith("_SELL") and r["n"] > 0]
    if hedge_rows:
        avg_hedge_feas = np.mean([r.get("feasible_pct", 0) or 0 for r in hedge_rows]) * 100
        L.append(f"- **HEDGE feasible (avg across cells)**: {avg_hedge_feas:.1f}%")
    if sell_rows:
        avg_sell_feas = np.mean([r.get("feasible_pct", 0) or 0 for r in sell_rows]) * 100
        L.append(f"- **SELL feasible (avg across cells)**: {avg_sell_feas:.1f}%")
    L.append("")

    L.append("## Snap staleness\n")
    L.append("**Definition:** at each rev_bp trigger, we look up the L25 snapshot at-or-before "
             "the trigger second. `snap_staleness_ms` is `trigger_ts − snap_ts` in milliseconds. "
             "P95 of the per-trade max staleness across the cell tells us how stale the production "
             "controller's view of the book would be at decision time.\n")

    L.append("## Files\n")
    L.append("- Per-cell: `strategy_lab/results/meta_classifier/momo_realfill_validation.csv`")
    L.append("- Per-trade: `strategy_lab/results/meta_classifier/momo_realfill_pertrade.csv`")
    L.append("- This report: `strategy_lab/reports/MOMO_REALFILL_VALIDATION_2026_05_06.md`\n")

    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"[md] report → {REPORT}")


if __name__ == "__main__":
    main()
