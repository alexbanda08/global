"""match_shadow — true same-trade comparison: re-simulate L25 realfill on EXACTLY
the same markets that shadow live fired on (May 6 deploy window).

Uses the L25 parquet cache (which has data through May 6 from the latest pull).
For each shadow fire:
    1. Derive ws_s from at_unix (5m → at-300, 15m → at-900) and slug.
    2. Look up L25 ask book at ws_s + 120 → walk for $25 entry.
    3. Scan klines from ws+120 to end for rev_bp ≥ 5 reversal trigger.
    4. At first trigger: look up real L25 book on appropriate side, simulate exit.
    5. Resolve PnL given actual outcome from shadow.
    6. Diff vs shadow's reported pnl_usd.

This uses the SAME period the production controller traded in — true apples-to-apples.

Output:
    strategy_lab/results/meta_classifier/momo_shadow_match.csv  (per shadow fire)
    strategy_lab/reports/MOMO_SHADOW_MATCH_2026_05_06.md
"""
from __future__ import annotations

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
)
from extended_backtest_with_robustness import (         # noqa: E402
    NOTIONAL_USD, FEE_RATE, SPREAD_FILTER,
    load_klines, asof, sell_at_bid,
)

SHADOW_CSV = ROOT / "data" / "v4" / "shadow_trades_2026_05_06" / "momo_resolutions_fresh.csv"
OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_shadow_match.csv"
OUT_MD  = ROOT / "strategy_lab" / "reports" / "MOMO_SHADOW_MATCH_2026_05_06.md"

REV_BP = 5
LEVELS = 25


def parse_sleeve(sid: str):
    import re
    m = re.match(r"poly_updown_(btc|eth|sol)_(5m|15m)_momo_(HOLD|HEDGE|SELL)$", sid)
    if not m:
        return None, None, None
    return m.group(1).upper(), m.group(2), m.group(3)


def load_shadow() -> pd.DataFrame:
    df = pd.read_csv(SHADOW_CSV)
    for col in ("won", "hedged", "partial_bid_exit"):
        if col in df.columns and df[col].dtype == object:
            df[col] = df[col].map({"t": True, "f": False}).astype(bool)
    for col in ("pnl_usd", "entry_price", "entry_qty", "hedge_price"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    parsed = df["sleeve_id"].apply(parse_sleeve)
    df["asset"] = [p[0] for p in parsed]
    df["timeframe"] = [p[1] for p in parsed]
    df["exit"] = [p[2] for p in parsed]
    df = df.dropna(subset=["asset", "timeframe", "exit"]).copy()
    df["at_unix"] = pd.to_datetime(df["at"], format="mixed", utc=True).astype("int64") // 1_000_000_000
    # Polymarket UpDown markets resolve at exact tf boundaries (multiples of 300/900).
    # Shadow `at` timestamp is recorded a few seconds AFTER actual resolution.
    # Derive ws_unix by rounding at_unix DOWN to nearest tf boundary, then subtract tf.
    tf_secs = df["timeframe"].map({"5m": 300, "15m": 900}).astype("int64")
    df["ws_unix"] = (df["at_unix"] // tf_secs) * tf_secs - tf_secs
    df["slug"] = (df["asset"].str.lower() + "-updown-" + df["timeframe"]
                  + "-" + df["ws_unix"].astype(str))
    return df


# Outcome ID convention: Up=0, Down=1
_OID = {"Up": 0, "Down": 1}


def simulate_one(
    row: pd.Series,
    klines: dict,
    indices: dict,
) -> dict:
    """Re-simulate one shadow fire against L25 raw book."""
    asset = row["asset"]
    tf = row["timeframe"]
    policy = row["exit"]
    sig_str = row["signal"]  # "UP" or "DOWN"
    held = "Up" if sig_str == "UP" else "Down"
    other = "Down" if sig_str == "UP" else "Up"
    held_id = _OID[held]
    other_id = _OID[other]

    ob_idx: OrderbookIndex = indices[asset.lower()]
    k1m = klines[asset.lower()]
    ws_s = int(row["ws_unix"])
    ws_us = ws_s * 1_000_000

    # Entry: ws + 120s, walk own ASKS for $25
    entry_ts_us = (ws_s + 120) * 1_000_000
    asks_p, asks_s = ob_idx.book_at(row["slug"], held_id, entry_ts_us, side="ask")
    if asks_p is None:
        return {"matched": False, "reason": "no_book_at_entry"}

    spread_thr = SPREAD_FILTER[asset.lower()]
    bids_p, _ = ob_idx.book_at(row["slug"], held_id, entry_ts_us, side="bid")
    if (asks_p[0] is not None and bids_p is not None and bids_p[0] is not None
            and np.isfinite(asks_p[0]) and np.isfinite(bids_p[0])
            and (asks_p[0] - bids_p[0]) > spread_thr):
        return {"matched": False, "reason": "spread_filter_skip"}

    vwap_e, shares_e, usd_e, _, under_e = book_walk_fill(asks_p, asks_s, NOTIONAL_USD)
    if shares_e <= 0:
        return {"matched": False, "reason": "thin_book_at_entry"}
    if under_e and usd_e < NOTIONAL_USD * 0.5:
        return {"matched": False, "reason": "thin_book_skip"}

    asset_at_entry = asof(k1m, ws_s + 120)
    if not (asset_at_entry and np.isfinite(asset_at_entry)):
        return {"matched": False, "reason": "no_kline_at_entry"}

    sig = 1 if sig_str == "UP" else 0
    max_b = 89 if tf == "15m" else 29

    exit_event = None
    if policy != "HOLD":
        for bucket in range(13, max_b + 1):
            ts_in_s = ws_s + bucket * 10
            ts_in_us = ts_in_s * 1_000_000
            a_now = asof(k1m, ts_in_s)
            if not np.isfinite(a_now):
                continue
            bp_rev = (a_now - asset_at_entry) / asset_at_entry * 10000.0
            trig = (sig == 1 and bp_rev <= -REV_BP) or (sig == 0 and bp_rev >= REV_BP)
            if not trig:
                continue
            if policy == "HEDGE":
                h_ask_p, h_ask_s = ob_idx.book_at(row["slug"], other_id, ts_in_us, side="ask")
                if (h_ask_p is None or len(h_ask_p) == 0
                        or h_ask_p[0] is None or not np.isfinite(h_ask_p[0])):
                    continue
                top = float(h_ask_p[0])
                if not (0 < top < 1):
                    continue
                target = shares_e * top
                vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(h_ask_p, h_ask_s, target)
                if shares_h > 0:
                    if shares_h < shares_e * 0.95 and not under_h:
                        vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(
                            h_ask_p, h_ask_s, shares_e * vwap_h
                        )
                    exit_event = ("hedge", bucket, dict(vwap_h=vwap_h, shares_h=shares_h, usd_h=usd_h))
                    break
            elif policy == "SELL":
                b_p, b_s = ob_idx.book_at(row["slug"], held_id, ts_in_us, side="bid")
                if b_p is None:
                    continue
                sv, sg = sell_at_bid(np.asarray(b_p), np.asarray(b_s), shares_e)
                if np.isfinite(sv) and sg > 0:
                    exit_event = ("sell", bucket, dict(sell_vwap=sv, sell_gross=sg))
                    break

    won = bool(row["won"])
    if exit_event is None:
        if won:
            profit = shares_e * 1.0 - usd_e
            fee = profit * FEE_RATE if profit > 0 else 0.0
            pnl_rf = profit - fee
        else:
            pnl_rf = -usd_e
        exit_reason = "hold"
    else:
        kind, _, ed = exit_event
        if kind == "hedge":
            cost = usd_e + ed["usd_h"]
            if won:
                gross = shares_e * 1.0
                fee = shares_e * (1.0 - vwap_e) * FEE_RATE
            else:
                gross = ed["shares_h"] * 1.0
                fee = ed["shares_h"] * (1.0 - ed["vwap_h"]) * FEE_RATE
            pnl_rf = gross - cost - fee
            exit_reason = "hedge"
        else:
            profit = ed["sell_gross"] - usd_e
            fee = max(profit, 0) * FEE_RATE
            pnl_rf = profit - fee
            exit_reason = "sell"

    return {
        "matched": True,
        "rf_vwap_e": vwap_e, "rf_shares_e": shares_e, "rf_usd_e": usd_e,
        "rf_pnl": pnl_rf, "rf_exit": exit_reason,
        "rf_won_alignment": won,  # always True since we use shadow's outcome
    }


def main():
    print("[1] loading shadow…")
    shadow = load_shadow()
    print(f"    shadow: {len(shadow)} fires; window: "
          f"{pd.to_datetime(shadow.at_unix.min(), unit='s', utc=True)} → "
          f"{pd.to_datetime(shadow.at_unix.max(), unit='s', utc=True)}")
    print(f"    unique slugs: {shadow['slug'].nunique()}")

    print("[2] loading klines + L25 parquet (per asset, slug-filtered)…")
    klines = load_klines()
    indices: dict = {}
    for asset in ("btc", "eth", "sol"):
        slugs = set(shadow[shadow.asset == asset.upper()]["slug"].unique())
        if not slugs:
            continue
        t0 = time.time()
        ob_df = load_orderbook_l25_raw(asset, slugs=slugs)
        idx = OrderbookIndex(ob_df)
        indices[asset] = idx
        print(f"    [{asset}] {len(slugs)} slugs → {len(ob_df):,} L25 rows; "
              f"index built in {time.time()-t0:.1f}s")

    print("[3] re-simulating each shadow fire against L25…")
    results = []
    n_matched = n_skip = 0
    for _, row in shadow.iterrows():
        if row["asset"].lower() not in indices:
            results.append({**row.to_dict(), "matched": False, "reason": "no_asset"})
            n_skip += 1
            continue
        sim = simulate_one(row, klines, indices)
        merged = {**row.to_dict(), **sim}
        results.append(merged)
        if sim.get("matched"):
            n_matched += 1
        else:
            n_skip += 1
    print(f"    matched: {n_matched}, skipped: {n_skip}")

    df = pd.DataFrame(results)
    df.to_csv(OUT_CSV, index=False)
    print(f"    [csv] → {OUT_CSV}")

    # Aggregate per cell
    print("\n[4] same-trade per-cell summary:\n")
    matched_df = df[df["matched"] == True].copy()
    if len(matched_df) == 0:
        print("    no matches — aborting report")
        return

    matched_df["pnl_diff"] = matched_df["rf_pnl"] - matched_df["pnl_usd"]
    grp = matched_df.groupby(["asset", "timeframe", "exit"])
    rows = []
    for (a, tf, ex), g in grp:
        n = len(g)
        rows.append({
            "cell": f"{a}_{tf}_{ex}",
            "n_matched": n,
            "shadow_pnl_total": float(g["pnl_usd"].sum()),
            "shadow_pnl_mean": float(g["pnl_usd"].mean()),
            "shadow_hit": float(g["won"].mean()),
            "rf_pnl_total": float(g["rf_pnl"].sum()),
            "rf_pnl_mean": float(g["rf_pnl"].mean()),
            "delta_total": float(g["pnl_diff"].sum()),
            "delta_mean": float(g["pnl_diff"].mean()),
            "n_hedge_rf": int((g["rf_exit"] == "hedge").sum()),
            "n_sell_rf": int((g["rf_exit"] == "sell").sum()),
            "n_hold_rf": int((g["rf_exit"] == "hold").sum()),
        })
    summary = pd.DataFrame(rows)
    print(summary.to_string(index=False))
    summary.to_csv(OUT_CSV.with_name("momo_shadow_match_summary.csv"), index=False)

    # Headline
    sh_total = matched_df["pnl_usd"].sum()
    rf_total = matched_df["rf_pnl"].sum()
    print(f"\nHEADLINE:")
    print(f"  Shadow total (matched): ${sh_total:+.2f}")
    print(f"  Realfill total (same trades): ${rf_total:+.2f}")
    print(f"  Δ (rf − shadow): ${rf_total - sh_total:+.2f}")
    print(f"  Mean Δ per trade: ${(rf_total - sh_total) / len(matched_df):+.3f}")

    write_report(summary, sh_total, rf_total, len(matched_df), len(df))


def write_report(summary: pd.DataFrame, sh_total: float, rf_total: float,
                 n_matched: int, n_total: int) -> None:
    L: list[str] = []
    L.append("# Momo Shadow Match — TRUE Same-Trade Comparison\n")
    L.append("**Generated:** 2026-05-06\n")
    L.append("**Method:** for each shadow live fire on May 6 (~16h post-deploy), re-simulate the "
             "EXACT SAME (slug, outcome, ts) against the L25 raw orderbook captured by VPS2. "
             "Same market, same direction, same outcome — only the EXIT POLICY simulation differs. "
             "Compares the production controller's actual fill/hedge/sell vs what the realfill engine "
             "would have done with the canonical book_walk_fill simulator.\n")
    L.append(f"**Matched:** {n_matched} / {n_total} shadow fires re-simulated successfully")
    L.append(f"**Skipped:** {n_total - n_matched} (no L25 book at entry, spread filter, thin book)\n")

    L.append("## Headline\n")
    L.append(f"- Shadow live total (matched fires only): **${sh_total:+.2f}**")
    L.append(f"- L25 realfill SAME trades: **${rf_total:+.2f}**")
    L.append(f"- Δ (realfill − shadow): **${rf_total - sh_total:+.2f}** "
             f"({(rf_total - sh_total) / n_matched:+.3f} / trade)")
    L.append("")

    L.append("## Per-cell — same-trade comparison\n")
    L.append("| Cell | n | sh_pnl | rf_pnl | Δ | sh_$/trade | rf_$/trade | Δ_$/trade | rf_hold | rf_hedge | rf_sell |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in summary.iterrows():
        L.append(
            f"| {r['cell']} | {int(r['n_matched'])} | "
            f"${r['shadow_pnl_total']:+.2f} | ${r['rf_pnl_total']:+.2f} | "
            f"${r['delta_total']:+.2f} | "
            f"${r['shadow_pnl_mean']:+.3f} | ${r['rf_pnl_mean']:+.3f} | "
            f"${r['delta_mean']:+.3f} | "
            f"{int(r['n_hold_rf'])} | {int(r['n_hedge_rf'])} | {int(r['n_sell_rf'])} |"
        )
    L.append("")

    L.append("## Interpretation\n")
    L.append("- **Δ ≈ 0**: production controller is matching realfill simulation. Strategy healthy.")
    L.append("- **Δ > 0**: realfill BEATS production — production has friction (slippage, missed exits, "
             "stale book at decision). Quantifies the friction.")
    L.append("- **Δ < 0**: production BEATS realfill — production luck OR realfill is too pessimistic.")
    L.append("")
    L.append("## Files\n")
    L.append(f"- Per-trade matched: `{OUT_CSV.relative_to(ROOT)}`")
    L.append(f"- Summary: `strategy_lab/results/meta_classifier/momo_shadow_match_summary.csv`")
    L.append(f"- Shadow source: `data/v4/shadow_trades_2026_05_06/momo_resolutions_fresh.csv`")

    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[md] → {OUT_MD}")


if __name__ == "__main__":
    main()
