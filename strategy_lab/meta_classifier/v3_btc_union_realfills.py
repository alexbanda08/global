"""V3 ∪ BTC_only (∪ P7) union — production-faithful realfills test.

Premise: phase9_lookahead_realfills_multi.py proved that BTC_only (top-10%
|btc_ret_2m|, sign = direction, entry @ t+120s) generates +$4,931 / +42.65%
ROI / 85.5% hit on real BTC book fills — vastly dominating Phase 9 (P9_orig
= +$515 / +8.12% ROI).

Question: does BTC_only add INCREMENTAL PnL beyond V3 (which already has many
BTC features in its prob_stack)?

Gates tested through canonical engine (`simulate_realfill`, $25 stake,
hedge-hold rev_bp=5, 2% fee, top-10 book walk):
  V3_alone      : prob_stack confidence ≥ 0.65, sign(prob_stack-0.5)
  BTC_only      : top-10% |asset_ret_2m|, sign = direction
  P7_alone      : top-5% |imb_slope_2m|, CONTRARIAN sign
  V3_BTC        : V3 ∪ BTC_only           (priority V3 > BTC_only on overlap)
  V3_BTC_P7     : V3 ∪ BTC_only ∪ P7      (V3 > BTC_only > P7)

Outputs:
  strategy_lab/results/meta_classifier/v3_btc_union_realfills.csv
  strategy_lab/reports/V3_BTC_UNION_REALFILLS.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))

from book_walk import book_walk_fill              # noqa: E402
from polymarket_stats import equity_curve_stats   # noqa: E402

# Production engine constants
LEVELS = 10
NOTIONAL_USD = 25.0
REV_BP = 5
FEE_RATE = 0.02
ENTRY_BUCKET = 12

# Gate thresholds (matches combined_gate_v2.py)
V3_CONF_THR = 0.65    # |prob_stack - 0.5| + 0.5 ≥ 0.65
P7_PCT = 0.95         # top 5%
BTC_PCT = 0.90        # top 10%

REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_02"
UNIV  = REFRESH / "btc_markets_minimal.csv"
BOOK  = REFRESH / "btc_book_depth_v3_full.csv"
BTC_KLINES = REFRESH / "binance_spot_1min_full.csv"
V3_CSV = ROOT / "strategy_lab" / "data" / "polymarket" / "btc_features_v3.csv"
P7    = ROOT / "strategy_lab" / "data" / "meta_classifier" / "btc_clob_momentum_v1.parquet"

OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "v3_btc_union_realfills.csv"
REPORT  = ROOT / "strategy_lab" / "reports"  / "V3_BTC_UNION_REALFILLS.md"

RNG = np.random.default_rng(42)


# ---------------------------------------------------------------------------
# Data + simulator (reuse same logic as multi-asset script)
# ---------------------------------------------------------------------------

def load_book(path: Path) -> dict:
    print(f"[book] reading {path.name}…")
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
    print(f"[book] {len(out)} unique slugs, {len(df)} rows")
    return out


def load_btc_1m() -> pd.DataFrame:
    df = pd.read_csv(BTC_KLINES)
    df = df[df.symbol_id == "BINANCE_SPOT_BTC_USDT"].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    return df.sort_values("ts_s").reset_index(drop=True)[["ts_s", "price_close"]]


def asof_close(k1m: pd.DataFrame, ts: int) -> float:
    """End-time-indexed asof (1MIN bars). Avoids the bar-open-indexed
    lookahead bug fixed in extended_backtest_with_robustness 2026-05-06."""
    end_us = (k1m.ts_s.astype("int64") + 60).values * 1_000_000
    target_us = int(ts) * 1_000_000
    idx = int(np.searchsorted(end_us, target_us, side="right")) - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


def attach_btc_ret_2m(df: pd.DataFrame, k1m: pd.DataFrame) -> np.ndarray:
    p0, p2 = [], []
    for ws in df["window_start_unix"].astype("int64").values:
        p0.append(asof_close(k1m, int(ws)))
        p2.append(asof_close(k1m, int(ws) + 120))
    return np.log(np.array(p2) / np.array(p0))


def simulate_realfill(row: pd.Series, k1m: pd.DataFrame, book: dict, max_bucket: int,
                      hedge_enabled: bool = True, spread_filter: float | None = None,
                      entry_bucket: int = ENTRY_BUCKET) -> dict | None:
    sig = int(row.signal)
    held_outcome = "Up" if sig == 1 else "Down"
    other_outcome = "Down" if sig == 1 else "Up"

    slug = row.slug
    if slug not in book:
        return None
    slug_book = book[slug]

    entry_key = (entry_bucket, held_outcome)
    if entry_key not in slug_book:
        return None
    ask_p, ask_s, bid_p, bid_s = slug_book[entry_key]
    # Production V3 spread filter: skip if ask_0 - bid_0 > spread_filter
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
    btc_at_entry = asof_close(k1m, ws + entry_bucket * 10)

    hedge = None
    if hedge_enabled and REV_BP is not None and np.isfinite(btc_at_entry):
        for bucket in range(entry_bucket + 1, max_bucket + 1):
            ts_in_bucket = ws + bucket * 10
            btc_now = asof_close(k1m, ts_in_bucket)
            if not np.isfinite(btc_now):
                continue
            bp = (btc_now - btc_at_entry) / btc_at_entry * 10000.0
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
        return dict(pnl=pnl, cost=usd_e, vwap_e=vwap_e, hedged=False, sig_won=sig_won, skipped_thin=False)

    vwap_h, shares_h, usd_h, lvls_h, under_h = hedge
    cost = usd_e + usd_h
    if sig_won:
        gross = shares_e * 1.0
        fee = shares_e * (1.0 - vwap_e) * FEE_RATE
    else:
        gross = shares_h * 1.0
        fee = shares_h * (1.0 - vwap_h) * FEE_RATE
    pnl = gross - cost - fee

    return dict(pnl=pnl, cost=cost, vwap_e=vwap_e, hedged=True, sig_won=sig_won, skipped_thin=False)


def run_universe(df: pd.DataFrame, k1m: pd.DataFrame, book: dict, label: str) -> dict:
    pnls, costs, ws_list = [], [], []
    skipped_thin = skipped_no_book = hedged = wins = 0
    for _, row in df.iterrows():
        max_bucket = 89 if row.timeframe == "15m" else 29
        r = simulate_realfill(row, k1m, book, max_bucket)
        if r is None:
            skipped_no_book += 1
            continue
        if r.get("skipped_thin"):
            skipped_thin += 1
            continue
        pnls.append(r["pnl"])
        costs.append(r["cost"])
        ws_list.append(int(row.window_start_unix))
        if r["sig_won"]:
            wins += 1
        if r["hedged"]:
            hedged += 1
    pnls = np.array(pnls); costs = np.array(costs)
    n = len(pnls)
    if n == 0:
        return {"label": label, "n": 0}
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    roi_per_trade = pnls / np.where(costs > 0, costs, 1.0) * 100.0
    eq = equity_curve_stats(pnls, trade_timestamps=np.array(ws_list, dtype=float))
    return dict(
        label=label, n=n, wins=wins,
        hit=float((pnls > 0).mean()),
        sig_won_rate=float(wins / n),
        pnl_total=float(pnls.sum()),
        pnl_mean=float(pnls.mean()),
        roi_pct=float(roi_per_trade.mean()),
        ci_lo=float(np.quantile(boot, 0.025)),
        ci_hi=float(np.quantile(boot, 0.975)),
        hedged=hedged,
        skipped_thin=skipped_thin,
        skipped_no_book=skipped_no_book,
        sharpe=eq["sharpe"],
        sortino=eq["sortino"],
        max_dd=eq["max_dd"],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[1] universe + features…")
    uni = pd.read_csv(UNIV).dropna(subset=["window_start_unix", "outcome_up"])
    uni["outcome_up"] = uni["outcome_up"].astype(int)
    print(f"    universe: {len(uni)}")

    v3 = pd.read_csv(V3_CSV)[["slug", "prob_stack"]].drop_duplicates("slug")
    p7 = pd.read_parquet(P7)[["slug", "imb_slope_2m"]]

    df = uni.merge(v3, on="slug", how="left").merge(p7, on="slug", how="left")
    print(f"    with V3:    {df['prob_stack'].notna().sum()}")
    print(f"    with P7:    {df['imb_slope_2m'].notna().sum()}")

    print("[2] BTC 1m + asset_ret_2m…")
    k1m = load_btc_1m()
    df["asset_ret_2m"] = attach_btc_ret_2m(df, k1m)
    print(f"    asset_ret_2m valid: {df['asset_ret_2m'].notna().sum()}")

    print("[3] book…")
    book = load_book(BOOK)

    # ───────────────────────────────────────────────────────────────────────
    # Define gates (matches combined_gate_v2.py + new BTC_only)
    # ───────────────────────────────────────────────────────────────────────
    df["v3_conf"]      = (df["prob_stack"] - 0.5).abs() + 0.5
    df["v3_fired"]     = df["v3_conf"] >= V3_CONF_THR
    df["v3_dir"]       = (df["prob_stack"] > 0.5).astype("Int8")

    p7_thr = df["imb_slope_2m"].abs().quantile(P7_PCT)
    df["p7_fired"]     = df["imb_slope_2m"].abs() >= p7_thr
    df["p7_dir"]       = (df["imb_slope_2m"] < 0).astype("Int8")  # CONTRARIAN

    btc_thr = df["asset_ret_2m"].abs().quantile(BTC_PCT)
    df["btc_fired"]    = df["asset_ret_2m"].abs() >= btc_thr
    df["btc_dir"]      = (df["asset_ret_2m"] > 0).astype("Int8")

    print(f"    V3 fires:       {df['v3_fired'].fillna(False).sum()}")
    print(f"    P7 fires:       {df['p7_fired'].fillna(False).sum()}")
    print(f"    BTC_only fires: {df['btc_fired'].fillna(False).sum()}")

    # Build unions with priority direction resolution
    def add_union(df: pd.DataFrame, gates: list[tuple[str, str]], col_prefix: str) -> pd.DataFrame:
        """Each item in gates: (fired_col, dir_col). Priority left → right."""
        df = df.copy()
        fire_cols = [g[0] for g in gates]
        df[col_prefix + "_fired"] = df[fire_cols].fillna(False).any(axis=1)
        df[col_prefix + "_dir"] = pd.NA
        for fcol, dcol in gates:
            m = df[col_prefix + "_fired"] & df[fcol].fillna(False) & df[col_prefix + "_dir"].isna()
            df.loc[m, col_prefix + "_dir"] = df.loc[m, dcol]
        return df

    df = add_union(df, [("v3_fired", "v3_dir"), ("btc_fired", "btc_dir")], "v3_btc")
    df = add_union(df, [("v3_fired", "v3_dir"), ("btc_fired", "btc_dir"), ("p7_fired", "p7_dir")], "v3_btc_p7")

    # ───────────────────────────────────────────────────────────────────────
    # Build per-gate trade-frames
    # ───────────────────────────────────────────────────────────────────────
    def to_signal(df: pd.DataFrame, fired_col: str, dir_col: str) -> pd.DataFrame:
        s = df[df[fired_col].fillna(False) & df[dir_col].notna()].copy()
        s["signal"] = s[dir_col].astype(int)
        return s

    tradesets = {
        "V3_alone":     to_signal(df, "v3_fired", "v3_dir"),
        "BTC_only":     to_signal(df, "btc_fired", "btc_dir"),
        "P7_alone":     to_signal(df, "p7_fired", "p7_dir"),
        "V3_BTC":       to_signal(df, "v3_btc_fired", "v3_btc_dir"),
        "V3_BTC_P7":    to_signal(df, "v3_btc_p7_fired", "v3_btc_p7_dir"),
    }
    for k, v in tradesets.items():
        print(f"    {k}: {len(v)} potential trades")

    # ───────────────────────────────────────────────────────────────────────
    # Pairwise overlap diagnostic
    # ───────────────────────────────────────────────────────────────────────
    def overlap(a, b):
        only_a = (df[a].fillna(False) & ~df[b].fillna(False)).sum()
        only_b = (~df[a].fillna(False) & df[b].fillna(False)).sum()
        both   = (df[a].fillna(False) & df[b].fillna(False)).sum()
        jacc = both / (only_a + only_b + both) if (only_a + only_b + both) > 0 else 0
        return only_a, only_b, both, jacc

    overlaps = {
        "V3 vs BTC":  overlap("v3_fired", "btc_fired"),
        "V3 vs P7":   overlap("v3_fired", "p7_fired"),
        "BTC vs P7":  overlap("btc_fired", "p7_fired"),
    }

    # Direction-agreement on V3 ∩ BTC: when both fire, do they agree?
    both_v3_btc = df[df["v3_fired"].fillna(False) & df["btc_fired"].fillna(False)].copy()
    if len(both_v3_btc) > 0:
        agree_pct = (both_v3_btc["v3_dir"] == both_v3_btc["btc_dir"]).mean()
    else:
        agree_pct = float("nan")

    # ───────────────────────────────────────────────────────────────────────
    # Run engine on each gate
    # ───────────────────────────────────────────────────────────────────────
    print("\n[4] running canonical simulator on each gate…")
    results = []
    for label, sub in tradesets.items():
        for tf_label, tf_sub in [("ALL", sub),
                                  ("5m",  sub[sub.timeframe == "5m"]),
                                  ("15m", sub[sub.timeframe == "15m"])]:
            r = run_universe(tf_sub, k1m, book, f"{label} — {tf_label}")
            results.append(r)
            if r["n"] > 0:
                print(f"  {r['label']:30s}  n={r['n']:4d}  hit={r['hit']*100:5.1f}%  "
                      f"pnl=${r['pnl_total']:+.2f}  roi={r['roi_pct']:+.2f}%  "
                      f"hedged={r['hedged']:3d}  sharpe={r['sharpe']:+.2f}")

    # Persist
    df_res = pd.DataFrame(results)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(OUT_CSV, index=False)

    # ───────────────────────────────────────────────────────────────────────
    # Report
    # ───────────────────────────────────────────────────────────────────────
    L = [
        "# V3 ∪ BTC_only Union — Production-Faithful Realfills\n",
        "_Generated: 2026-05-05_\n",
        "## Setup\n",
        f"Same canonical engine as `phase9_lookahead_realfills_multi.py`. ${NOTIONAL_USD:.0f} stake, "
        f"hedge-hold rev_bp={REV_BP}, {FEE_RATE*100:.0f}% fee, top-{LEVELS} book walk, "
        f"entry @ bucket {ENTRY_BUCKET} (= t+120s).\n",
        "## Gates\n",
        f"- **V3**:       prob_stack confidence ≥ {V3_CONF_THR}, sign(prob_stack-0.5) — covers Apr 22 → Apr 29 only",
        f"- **P7**:       top-{(1-P7_PCT)*100:.0f}% \\|imb_slope_2m\\|, **CONTRARIAN** — full Apr 22 → May 4",
        f"- **BTC_only**: top-{(1-BTC_PCT)*100:.0f}% \\|asset_ret_2m\\|, sign(asset_ret_2m) — full Apr 22 → May 4",
        "",
        "## Universe coverage\n",
        f"- Total markets: {len(df)}",
        f"- With V3 features:    {df['prob_stack'].notna().sum()} (V3 only computed Apr 22 → Apr 29)",
        f"- With P7 features:    {df['imb_slope_2m'].notna().sum()}",
        f"- With BTC ret_2m:     {df['asset_ret_2m'].notna().sum()}",
        "",
        "## Pairwise gate overlap\n",
        "| Pair | only A | only B | both | Jaccard |",
        "|---|---:|---:|---:|---:|",
    ]
    for k, (oa, ob, both, j) in overlaps.items():
        L.append(f"| {k} | {oa} | {ob} | {both} | {j:.3f} |")

    L += [
        "",
        f"On V3 ∩ BTC_only fires (n={len(both_v3_btc)}), V3 and BTC_only directions **agree** on {agree_pct*100:.1f}% of markets.",
        "",
        "## Engine results — entry @ t+120s, real fills, hedge-hold\n",
        "| Gate | n | hit% | total PnL | mean PnL | ROI/trade | Sharpe | hedged | thin | no_book |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        if r["n"] == 0:
            L.append(f"| {r['label']} | 0 | — | — | — | — | — | — | — | — |")
            continue
        L.append(
            f"| {r['label']} | {r['n']} | {r['hit']*100:.1f} | "
            f"${r['pnl_total']:+.2f} | ${r['pnl_mean']:+.4f} | "
            f"{r['roi_pct']:+.2f}% | {r['sharpe']:+.2f} | "
            f"{r['hedged']} | {r['skipped_thin']} | {r['skipped_no_book']} |"
        )

    # Verdict block
    v3a   = next(r for r in results if r["label"] == "V3_alone — ALL")
    btc   = next(r for r in results if r["label"] == "BTC_only — ALL")
    p7a   = next(r for r in results if r["label"] == "P7_alone — ALL")
    vb    = next(r for r in results if r["label"] == "V3_BTC — ALL")
    vbp   = next(r for r in results if r["label"] == "V3_BTC_P7 — ALL")

    incremental_btc = vb["pnl_total"] - v3a["pnl_total"]
    incremental_p7  = vbp["pnl_total"] - vb["pnl_total"]

    L += [
        "",
        "---",
        "",
        "## VERDICT\n",
        f"- **V3 alone**:  n={v3a['n']:>4d}  hit={v3a['hit']*100:.1f}%  total ${v3a['pnl_total']:+.2f}  ROI {v3a['roi_pct']:+.2f}%/trade",
        f"- **BTC_only**:  n={btc['n']:>4d}  hit={btc['hit']*100:.1f}%  total ${btc['pnl_total']:+.2f}  ROI {btc['roi_pct']:+.2f}%/trade",
        f"- **P7 alone**:  n={p7a['n']:>4d}  hit={p7a['hit']*100:.1f}%  total ${p7a['pnl_total']:+.2f}  ROI {p7a['roi_pct']:+.2f}%/trade",
        f"- **V3 ∪ BTC**:        n={vb['n']:>4d}  hit={vb['hit']*100:.1f}%  total ${vb['pnl_total']:+.2f}  ROI {vb['roi_pct']:+.2f}%/trade",
        f"- **V3 ∪ BTC ∪ P7**:   n={vbp['n']:>4d}  hit={vbp['hit']*100:.1f}%  total ${vbp['pnl_total']:+.2f}  ROI {vbp['roi_pct']:+.2f}%/trade",
        "",
        f"**Incremental PnL of adding BTC_only to V3**: ${incremental_btc:+.2f}",
        f"**Incremental PnL of adding P7 to (V3 ∪ BTC)**: ${incremental_p7:+.2f}",
        "",
    ]
    if incremental_btc > 100:
        L.append(f"→ **BTC_only adds significant alpha to V3** (+${incremental_btc:.0f}). Worth deploying.")
    elif incremental_btc > 0:
        L.append(f"→ BTC_only adds marginal alpha (+${incremental_btc:.0f}); deploy if cheap to run.")
    else:
        L.append(f"→ **BTC_only is fully captured by V3** (incremental = ${incremental_btc:+.0f}). V3 already harvests this signal.")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[report] wrote {REPORT}")
    print(f"[csv] wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
