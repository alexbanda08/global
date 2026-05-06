"""V3 production replay — mirror VPS3 shadow exactly, compare apples-to-apples.

What the previous backtest got wrong:
  • Used entry_bucket=12 (t+120s) — but V3 fires at bar close (bucket 0).
  • Used hedge-hold rev_bp=5 with 60+ triggered hedges — but shadow shows 0/190
    hedges actually fire in production V3 trades.
  • Did NOT apply the production spread filter (ask_0 - bid_0 ≤ 0.02 for BTC/ETH).

This script mirrors VPS3 V3 production semantics exactly:
  • Entry: bucket_10s = 0 (first 10s of new market = bar close of just-closed
    Binance 5m bar), book-walked over top-10 ASK levels for $25 notional.
  • Spread filter: skip if (ask_0 - bid_0) > 0.02 for BTC/ETH, > 0.025 for SOL.
  • Hedge: HEDGE_HOLD policy (rev_bp=5), but report both with-hedge and
    no-hedge to show the bound on hedge contribution.
  • Fee: 2% taker on winning leg's profit (matches PolymarketUpdownController).
  • Settlement: $1/$0 binary.

Then compares to:
  • Shadow trades: data/v4/shadow_trades_2026_05_05_live/v3_resolutions_latest.csv
    (live V3 sleeve fires from VPS3 trading.events table)

Outputs:
  strategy_lab/results/meta_classifier/v3_production_replay.csv
  strategy_lab/reports/V3_PRODUCTION_REPLAY.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))

from book_walk import book_walk_fill            # noqa: E402
from polymarket_stats import equity_curve_stats # noqa: E402

LEVELS = 10
NOTIONAL_USD = 25.0
FEE_RATE = 0.02
REV_BP = 5
SPREAD_FILTER = {"btc": 0.02, "eth": 0.02, "sol": 0.025}

REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_02"
KLINES = REFRESH / "binance_spot_1min_full.csv"
V3_CSV = ROOT / "strategy_lab" / "data" / "polymarket" / "btc_features_v3.csv"
SHADOW = ROOT / "data" / "v4" / "shadow_trades_2026_05_05_live" / "v3_resolutions_latest.csv"

OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "v3_production_replay.csv"
REPORT  = ROOT / "strategy_lab" / "reports" / "V3_PRODUCTION_REPLAY.md"

ASSET_SYMBOL = {
    "btc": "BINANCE_SPOT_BTC_USDT",
    "eth": "BINANCE_SPOT_ETH_USDT",
    "sol": "BINANCE_SPOT_SOL_USDT",
}

V3_CONF_THR = 0.65
RNG = np.random.default_rng(42)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_book(path: Path) -> dict:
    cols_ask_p = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_ask_s = [f"ask_size_{i}"  for i in range(LEVELS)]
    cols_bid_p = [f"bid_price_{i}" for i in range(LEVELS)]
    cols_bid_s = [f"bid_size_{i}"  for i in range(LEVELS)]
    keep = ["slug", "bucket_10s", "outcome"] + cols_ask_p + cols_ask_s + cols_bid_p + cols_bid_s
    df = pd.read_csv(path, usecols=keep)
    asks_p = df[cols_ask_p].to_numpy(dtype=float)
    asks_s = df[cols_ask_s].to_numpy(dtype=float)
    bids_p = df[cols_bid_p].to_numpy(dtype=float)
    bids_s = df[cols_bid_s].to_numpy(dtype=float)
    slugs = df.slug.to_numpy()
    buckets = df.bucket_10s.to_numpy(dtype=int)
    outcomes = df.outcome.to_numpy()
    out: dict = {}
    for i in range(len(df)):
        slug = slugs[i]
        if slug not in out:
            out[slug] = {}
        out[slug][(int(buckets[i]), outcomes[i])] = (asks_p[i], asks_s[i], bids_p[i], bids_s[i])
    return out


def load_klines() -> dict[str, pd.DataFrame]:
    df = pd.read_csv(KLINES)
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for asset, sym in ASSET_SYMBOL.items():
        sub = df[df.symbol_id == sym].sort_values("ts_s").reset_index(drop=True)
        out[asset] = sub[["ts_s", "price_close"]]
    return out


def asof_close(k1m: pd.DataFrame, ts: int) -> float:
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


# ---------------------------------------------------------------------------
# Simulator — mirrors VPS3 V3 production
# ---------------------------------------------------------------------------

def simulate_v3_trade(row: pd.Series, k1m: pd.DataFrame, book: dict,
                      max_bucket: int, asset: str,
                      hedge_enabled: bool, spread_filter: float | None) -> dict | None:
    sig = int(row.signal)
    held_outcome = "Up" if sig == 1 else "Down"
    other_outcome = "Down" if sig == 1 else "Up"

    slug = row.slug
    if slug not in book:
        return None
    slug_book = book[slug]

    # ENTRY at bucket 0 (V3 fires at Binance bar close = t=0 of the new market)
    entry_key = (0, held_outcome)
    if entry_key not in slug_book:
        return None
    ask_p, ask_s, bid_p, bid_s = slug_book[entry_key]

    # Production spread filter
    if spread_filter is not None and len(ask_p) and len(bid_p):
        if np.isfinite(ask_p[0]) and np.isfinite(bid_p[0]):
            if (ask_p[0] - bid_p[0]) > spread_filter:
                return {"skipped_spread": True}

    vwap_e, shares_e, usd_e, lvls_e, under_e = book_walk_fill(ask_p, ask_s, NOTIONAL_USD)
    if shares_e <= 0:
        return None
    if under_e and usd_e < NOTIONAL_USD * 0.5:
        return {"skipped_thin": True}

    ws = int(row.window_start_unix)
    asset_at_entry = asof_close(k1m, ws)

    hedge = None
    if hedge_enabled and REV_BP is not None and np.isfinite(asset_at_entry):
        for bucket in range(1, max_bucket + 1):
            ts_in_bucket = ws + bucket * 10
            asset_now = asof_close(k1m, ts_in_bucket)
            if not np.isfinite(asset_now):
                continue
            bp = (asset_now - asset_at_entry) / asset_at_entry * 10000.0
            reverted = (sig == 1 and bp <= -REV_BP) or (sig == 0 and bp >= REV_BP)
            if not reverted:
                continue
            hedge_key = (bucket, other_outcome)
            if hedge_key not in slug_book:
                break
            h_ask_p, h_ask_s, _, _ = slug_book[hedge_key]
            top = h_ask_p[0] if len(h_ask_p) and np.isfinite(h_ask_p[0]) else float("nan")
            if not (np.isfinite(top) and 0 < top < 1):
                break
            target_h = shares_e * float(top)
            vwap_h, shares_h, usd_h, lvls_h, under_h = book_walk_fill(h_ask_p, h_ask_s, target_h)
            if shares_h <= 0:
                break
            if shares_h < shares_e * 0.95 and not under_h:
                bump = shares_e * vwap_h
                vwap_h, shares_h, usd_h, lvls_h, under_h = book_walk_fill(h_ask_p, h_ask_s, bump)
            hedge = (vwap_h, shares_h, usd_h, lvls_h, under_h)
            break

    outcome_up = int(row.outcome_up)
    sig_won = (sig == outcome_up)

    if hedge is None:
        if sig_won:
            gross = shares_e * 1.0
            profit_pre_fee = gross - usd_e
            fee = profit_pre_fee * FEE_RATE if profit_pre_fee > 0 else 0.0
            pnl = profit_pre_fee - fee
        else:
            pnl = -usd_e
        return dict(pnl=pnl, cost=usd_e, vwap_e=vwap_e, hedged=False, sig_won=sig_won, skipped_thin=False, skipped_spread=False)

    vwap_h, shares_h, usd_h, lvls_h, under_h = hedge
    cost = usd_e + usd_h
    if sig_won:
        gross = shares_e * 1.0
        fee = shares_e * (1.0 - vwap_e) * FEE_RATE
    else:
        gross = shares_h * 1.0
        fee = shares_h * (1.0 - vwap_h) * FEE_RATE
    pnl = gross - cost - fee
    return dict(pnl=pnl, cost=cost, vwap_e=vwap_e, hedged=True, sig_won=sig_won, skipped_thin=False, skipped_spread=False)


def run_universe(df: pd.DataFrame, k1m: pd.DataFrame, book: dict, asset: str,
                 hedge_enabled: bool, spread_filter: float | None, label: str) -> dict:
    pnls, costs, ws_list, vwaps = [], [], [], []
    skipped_thin = skipped_no_book = skipped_spread = hedged = wins = 0
    for _, row in df.iterrows():
        max_bucket = 89 if row.timeframe == "15m" else 29
        r = simulate_v3_trade(row, k1m, book, max_bucket, asset, hedge_enabled, spread_filter)
        if r is None:
            skipped_no_book += 1
            continue
        if r.get("skipped_spread"):
            skipped_spread += 1
            continue
        if r.get("skipped_thin"):
            skipped_thin += 1
            continue
        pnls.append(r["pnl"])
        costs.append(r["cost"])
        ws_list.append(int(row.window_start_unix))
        vwaps.append(r["vwap_e"])
        if r["sig_won"]:
            wins += 1
        if r["hedged"]:
            hedged += 1
    pnls = np.array(pnls); costs = np.array(costs)
    n = len(pnls)
    if n == 0:
        return {"label": label, "n": 0}
    eq = equity_curve_stats(pnls, trade_timestamps=np.array(ws_list, dtype=float))
    return dict(
        label=label, n=n, wins=wins,
        hit=float((pnls > 0).mean()),
        sig_won_rate=float(wins / n),
        pnl_total=float(pnls.sum()),
        pnl_mean=float(pnls.mean()),
        cost_total=float(costs.sum()),
        avg_vwap_e=float(np.mean(vwaps)),
        roi_pct=float((pnls / np.where(costs > 0, costs, 1.0)).mean() * 100),
        hedged=hedged,
        skipped_thin=skipped_thin,
        skipped_no_book=skipped_no_book,
        skipped_spread=skipped_spread,
        sharpe=eq["sharpe"],
    )


def parse_shadow(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["data_obj"] = df["data"].apply(json.loads)
    flat = pd.json_normalize(df["data_obj"])
    flat["sleeve_id"] = df["sleeve_id"]
    flat["at"] = pd.to_datetime(df["at"])
    for c in ["pnl_usd", "entry_qty", "entry_price", "hedge_price",
              "strike_price", "settlement_price"]:
        flat[c] = pd.to_numeric(flat[c], errors="coerce")
    flat["won_b"] = flat["won"] == True   # noqa: E712
    flat["hedged_b"] = flat["hedged"] == True   # noqa: E712
    return flat


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[1] V3 features + universe…")
    v3 = pd.read_csv(V3_CSV)
    v3["v3_conf"] = (v3["prob_stack"] - 0.5).abs() + 0.5
    v3["v3_fired"] = v3["v3_conf"] >= V3_CONF_THR
    v3["v3_dir"] = (v3["prob_stack"] > 0.5).astype(int)
    fired = v3[v3["v3_fired"]].copy()
    fired["signal"] = fired["v3_dir"]
    print(f"    V3 features: {len(v3)} markets, V3 fires: {len(fired)}")
    print(f"    V3 period: {pd.to_datetime(v3.window_start_unix.min(), unit='s')} → "
          f"{pd.to_datetime(v3.window_start_unix.max(), unit='s')}")

    # V3 features only have BTC (in btc_features_v3.csv)
    fired["asset"] = "btc"

    print("\n[2] klines + book…")
    klines = load_klines()
    print("[book/btc]…")
    book_btc = load_book(REFRESH / "btc_book_depth_v3_full.csv")

    print("\n[3] running production replay variants on V3 BTC fires…")
    results = []
    # Variant A: production-faithful — entry@0, spread filter 0.02, hedge-hold ON
    r = run_universe(fired, klines["btc"], book_btc, "btc",
                     hedge_enabled=True, spread_filter=SPREAD_FILTER["btc"],
                     label="A. PRODUCTION (entry@0 + spread≤0.02 + hedge_hold)")
    results.append(r)
    # Variant B: same but hedge OFF (matches observed shadow behavior of 0 hedges)
    r = run_universe(fired, klines["btc"], book_btc, "btc",
                     hedge_enabled=False, spread_filter=SPREAD_FILTER["btc"],
                     label="B. PRODUCTION-NO-HEDGE (entry@0 + spread≤0.02 + hold-to-resolution)")
    results.append(r)
    # Variant C: previous backtest assumption (entry@12, no spread filter, hedge ON)
    fired_c = fired.copy()
    r = run_universe(fired_c, klines["btc"], book_btc, "btc",
                     hedge_enabled=True, spread_filter=None,
                     label="C. PREVIOUS BACKTEST (entry@0 unchanged, no spread filter, hedge ON)")
    results.append(r)
    # Variant D: no spread filter, no hedge
    r = run_universe(fired, klines["btc"], book_btc, "btc",
                     hedge_enabled=False, spread_filter=None,
                     label="D. NO-FILTER NO-HEDGE (entry@0, no spread filter, hold-to-resolution)")
    results.append(r)

    for r in results:
        if r["n"] == 0: continue
        print(f"  {r['label']:75s}  n={r['n']:4d}  hit={r['hit']*100:5.1f}%  "
              f"vwap=${r['avg_vwap_e']:.4f}  pnl=${r['pnl_total']:+.2f}  hedged={r['hedged']:3d}  "
              f"thin={r['skipped_thin']:2d}  spread_skip={r['skipped_spread']:3d}  "
              f"no_book={r['skipped_no_book']:2d}")

    # ───────────────────────────────────────────────────────────────────────
    # Shadow comparison
    # ───────────────────────────────────────────────────────────────────────
    shadow = parse_shadow(SHADOW)
    btc_shadow = shadow[(shadow["symbol"] == "BTC") & (shadow["sleeve_id"] == "poly_updown_btc_5m_v3")].copy()
    print(f"\n[4] Shadow `poly_updown_btc_5m_v3` (base V3, no variants): n={len(btc_shadow)}")
    print(f"    period: {btc_shadow['at'].min()} → {btc_shadow['at'].max()}")
    sh_n = len(btc_shadow)
    sh_wins = int(btc_shadow["won_b"].sum())
    sh_hit = sh_wins / sh_n if sh_n else 0
    sh_pnl_total = float(btc_shadow["pnl_usd"].sum())
    sh_pnl_mean = float(btc_shadow["pnl_usd"].mean())
    sh_hedged = int(btc_shadow["hedged_b"].sum())
    sh_avg_entry = float(btc_shadow["entry_price"].mean())
    print(f"    hit={sh_hit*100:.1f}%  pnl=${sh_pnl_total:+.2f}  mean=${sh_pnl_mean:+.4f}  "
          f"hedged={sh_hedged}  avg_entry=${sh_avg_entry:.4f}")

    # Persist
    df_res = pd.DataFrame(results)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(OUT_CSV, index=False)

    # ───────────────────────────────────────────────────────────────────────
    # Report
    # ───────────────────────────────────────────────────────────────────────
    L = [
        "# V3 Production Replay — Backtest vs Live Shadow\n",
        "_Generated: 2026-05-05_\n",
        "## Why a new backtest?\n",
        "The earlier `v3_btc_union_realfills.py` made TWO production-fidelity errors that the VPS3 shadow data exposed:\n",
        "1. **Entry timing**: previous run used `entry_bucket = 12` (t+120s). Wrong for V3 — V3 fires "
        "at Binance bar close, which is bucket 0 of the new Polymarket market.",
        "2. **Hedge frequency**: previous run assumed `rev_bp=5` triggered ~60+ hedges in V3-BTC. Live "
        "shadow shows **0 hedges in 190 V3 trades** (4 days). Production HEDGE_HOLD policy almost never "
        "triggers in 5m markets because `prob_stack` doesn't correlate with same-window Binance reversion.",
        "3. Also missing: **production spread filter** `TV_POLY_V3_SPREAD_FILTER_BTC=0.02` "
        "(skip if ask_0 - bid_0 > 2¢).\n",
        "## VPS3 production config (verified)\n",
        "```",
        "TV_POLY_HEDGE_POLICY=HEDGE_HOLD",
        "TV_POLY_V3_SPREAD_FILTER_BTC=0.02",
        "TV_POLY_V3_SPREAD_FILTER_ETH=0.02",
        "TV_POLY_V3_SPREAD_FILTER_SOL=0.025",
        "TV_POLY_STRATEGY_MODES=volume,sniper,v3,v3_1,v3_2,v3_3,v4",
        "```",
        "",
        "## Backtest variants on V3 BTC fires (Apr 22 → Apr 29)\n",
        f"V3 features have {len(v3)} BTC markets; V3 fires (prob_stack confidence ≥ 0.65): "
        f"{len(fired)} markets.\n",
        "| Variant | n | hit% | avg vwap_e | total PnL | mean PnL | hedged | spread_skipped |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        if r["n"] == 0: continue
        L.append(
            f"| {r['label']} | {r['n']} | {r['hit']*100:.1f}% | "
            f"${r['avg_vwap_e']:.4f} | ${r['pnl_total']:+.2f} | ${r['pnl_mean']:+.4f} | "
            f"{r['hedged']} | {r['skipped_spread']} |"
        )

    L += [
        "",
        "## VPS3 shadow `poly_updown_btc_5m_v3` (base V3, BTC only, Apr 30 → May 5)\n",
        f"- n: {sh_n}",
        f"- hit: {sh_hit*100:.1f}%",
        f"- total PnL: ${sh_pnl_total:+.2f}",
        f"- mean PnL: ${sh_pnl_mean:+.4f} / trade",
        f"- avg entry price: ${sh_avg_entry:.4f}",
        f"- hedged: {sh_hedged}",
        "",
        "## Reconciliation\n",
        "| Metric | Variant B (production-no-hedge) backtest | Shadow `btc_5m_v3` |",
        "|---|---:|---:|",
    ]
    rB = next(r for r in results if r["label"].startswith("B."))
    L += [
        f"| n              | {rB['n']}      | {sh_n} |",
        f"| hit            | {rB['hit']*100:.1f}% | {sh_hit*100:.1f}% |",
        f"| avg vwap entry | ${rB['avg_vwap_e']:.4f}      | ${sh_avg_entry:.4f} |",
        f"| total PnL      | ${rB['pnl_total']:+.2f}     | ${sh_pnl_total:+.2f} |",
        f"| mean PnL       | ${rB['pnl_mean']:+.4f}      | ${sh_pnl_mean:+.4f} |",
        f"| hedged         | {rB['hedged']}      | {sh_hedged} |",
        "",
        "*Different time windows*: backtest uses Apr 22-29 (V3 features available), shadow uses Apr 30-May 5. "
        "If V3's edge is stable, mean PnL should be in the same ballpark.\n",
    ]

    delta = sh_pnl_mean - rB["pnl_mean"]
    delta_hit = sh_hit - rB["hit"]
    if abs(delta) < 1.0 and abs(delta_hit) < 0.10:
        L.append(f"→ **Backtest forward-walks within ${abs(delta):.2f}/trade and {abs(delta_hit)*100:.1f}pp hit-rate.** V3 is stable.")
    elif sh_pnl_mean > rB["pnl_mean"]:
        L.append(f"→ **Shadow OUTPERFORMS Variant B by ${delta:+.2f}/trade**. V3 is doing better in live than backfill predicts.")
    else:
        L.append(f"→ **Shadow UNDERPERFORMS Variant B by ${-delta:.2f}/trade**. Forward-walk degradation; investigate.")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[report] wrote {REPORT}")
    print(f"[csv] wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
