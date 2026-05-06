"""Phase 9 lookahead — production-faithful realfills test.

Uses the canonical Polymarket UpDown simulator (`simulate_realfill` from
`polymarket_signal_grid_realfills.py`) — book-walked entry across top-10
levels, hedge-hold loop on Binance reversion ≥5bps, $25/slot notional,
2% taker fee. The same engine that produced the published v2 numbers.

Adapted to:
  • Use the NEWER data refresh (April 22 → May 4, 2026) so we cover the
    entire Phase 9 universe.
  • Test three competing signal definitions under identical engine
    semantics:
        G1 P9_orig    — top 10% |poly_tfi_2m|,         sign = direction
        G2 BTC_only   — top 10% |btc_ret_2m|,          sign = direction
        G3 P9_resid   — top 10% |poly_tfi_2m residual|, sign = direction
                        (residual = TFI − OLS(TFI ~ btc_ret_2m))

  • Entry timing: bucket 12 (t = +120s), the moment the signal is
    observable in production. The original published Phase 9 numbers used
    bucket 0 entry which is itself a lookahead artifact — we report both.

Outputs:
  strategy_lab/results/meta_classifier/phase9_realfills_results.csv
  strategy_lab/reports/PHASE9_LOOKAHEAD_REALFILLS.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))

from book_walk import book_walk_fill          # noqa: E402
from polymarket_stats import equity_curve_stats  # noqa: E402

# Data sources (newer refresh — full Apr 22 → May 4 coverage)
UNIV = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_markets_minimal.csv"
P9   = ROOT / "strategy_lab" / "data" / "meta_classifier" / "btc_trade_flow_v1.parquet"
BOOK = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_book_depth_v3_full.csv"
BTC  = ROOT / "data" / "v4" / "refresh_2026_05_02" / "binance_spot_1min_full.csv"

OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "phase9_realfills_results.csv"
REPORT  = ROOT / "strategy_lab" / "reports"  / "PHASE9_LOOKAHEAD_REALFILLS.md"

# Production engine constants (from polymarket_signal_grid_realfills.py)
LEVELS = 10
NOTIONAL_USD = 25.0     # production: $25/slot, hard-coded in PolymarketUpdownController
REV_BP = 5              # production: REV_BP_THRESHOLD = 5
FEE_RATE = 0.02         # 2% taker per side
ENTRY_BUCKET = 12       # bucket 12 = t+120s, when poly_tfi_2m is observable

RNG = np.random.default_rng(42)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_book(path: Path) -> dict:
    """Returns {slug: {(bucket, outcome): (asks_p, asks_s, bids_p, bids_s)}}."""
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
        out[slug][(int(buckets[i]), outcomes[i])] = (
            asks_p[i], asks_s[i], bids_p[i], bids_s[i]
        )
    print(f"[book] loaded {len(out)} unique slugs, {len(df)} bucket rows")
    return out


def load_btc_1m() -> pd.DataFrame:
    print(f"[btc1m] reading {BTC.name}…")
    df = pd.read_csv(BTC)
    df = df[df.symbol_id == "BINANCE_SPOT_BTC_USDT"].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    return df.sort_values("ts_s").reset_index(drop=True)[["ts_s", "price_close"]]


def asof_close(k1m: pd.DataFrame, ts: int) -> float:
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    if idx < 0:
        return float("nan")
    return float(k1m.price_close.iloc[idx])


def attach_btc_return_2m(rows: pd.DataFrame, k1m: pd.DataFrame) -> pd.Series:
    """log(close@t+120 / close@t) per market."""
    p0 = []
    p2 = []
    for ws in rows["window_start_unix"].astype("int64").values:
        p0.append(asof_close(k1m, int(ws)))            # close ≈ at t=0 (bar starting at t-60s ends at t)
        p2.append(asof_close(k1m, int(ws) + 120))      # close ≈ at t+120s
    return np.log(np.array(p2) / np.array(p0))


# ---------------------------------------------------------------------------
# Simulator — adapted from polymarket_signal_grid_realfills.simulate_realfill
# ---------------------------------------------------------------------------

def simulate_realfill(row: pd.Series, k1m: pd.DataFrame, book: dict,
                      max_bucket: int, entry_bucket: int = ENTRY_BUCKET,
                      rev_bp: int = REV_BP, notional_usd: float = NOTIONAL_USD) -> dict | None:
    """One trade. Returns dict with pnl + diagnostics, or None on no-book/skip."""
    sig = int(row.signal)
    held_outcome = "Up" if sig == 1 else "Down"
    other_outcome = "Down" if sig == 1 else "Up"

    slug = row.slug
    if slug not in book:
        return None
    slug_book = book[slug]

    # Entry book: bucket=entry_bucket of held side
    entry_key = (entry_bucket, held_outcome)
    if entry_key not in slug_book:
        return None
    ask_p, ask_s, bid_p, bid_s = slug_book[entry_key]
    vwap_e, shares_e, usd_e, lvls_e, under_e = book_walk_fill(ask_p, ask_s, notional_usd)
    if shares_e <= 0:
        return None
    if under_e and usd_e < notional_usd * 0.5:
        return {"skipped_thin": True}

    ws = int(row.window_start_unix)
    btc_at_entry = asof_close(k1m, ws + entry_bucket * 10)

    # Hedge-hold: scan buckets > entry_bucket up to max_bucket
    hedge = None
    if rev_bp is not None and np.isfinite(btc_at_entry):
        for bucket in range(entry_bucket + 1, max_bucket + 1):
            ts_in_bucket = ws + bucket * 10
            btc_now = asof_close(k1m, ts_in_bucket)
            if not np.isfinite(btc_now):
                continue
            bp = (btc_now - btc_at_entry) / btc_at_entry * 10000.0
            reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
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
        return {"pnl": pnl, "cost": usd_e, "shares_e": shares_e, "vwap_e": vwap_e,
                "lvls_e": lvls_e, "under_e": under_e,
                "shares_h": 0.0, "vwap_h": 0.0, "lvls_h": 0, "under_h": False,
                "hedged": False, "sig_won": sig_won, "skipped_thin": False}

    vwap_h, shares_h, usd_h, lvls_h, under_h = hedge
    cost = usd_e + usd_h
    if sig_won:
        gross = shares_e * 1.0
        fee = shares_e * (1.0 - vwap_e) * FEE_RATE
    else:
        gross = shares_h * 1.0
        fee = shares_h * (1.0 - vwap_h) * FEE_RATE
    pnl = gross - cost - fee

    return {"pnl": pnl, "cost": cost, "shares_e": shares_e, "vwap_e": vwap_e,
            "lvls_e": lvls_e, "under_e": under_e,
            "shares_h": shares_h, "vwap_h": vwap_h, "lvls_h": lvls_h, "under_h": under_h,
            "hedged": True, "sig_won": sig_won, "skipped_thin": False}


def run_universe(df: pd.DataFrame, k1m: pd.DataFrame, book: dict, label: str,
                 entry_bucket: int = ENTRY_BUCKET, notional: float = NOTIONAL_USD) -> dict:
    pnls, costs, ws_list = [], [], []
    skipped_thin = skipped_no_book = hedged = under_e_n = wins = 0

    for _, row in df.iterrows():
        max_bucket = 89 if row.timeframe == "15m" else 29
        r = simulate_realfill(row, k1m, book, max_bucket, entry_bucket=entry_bucket,
                              notional_usd=notional)
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
        if r["under_e"]:
            under_e_n += 1
        if r["hedged"]:
            hedged += 1

    pnls = np.array(pnls); costs = np.array(costs)
    n = len(pnls)
    if n == 0:
        return {"label": label, "n": 0}

    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    roi_per_trade = pnls / np.where(costs > 0, costs, 1.0) * 100.0
    eq = equity_curve_stats(pnls, trade_timestamps=np.array(ws_list, dtype=float))
    return {
        "label": label,
        "n": n,
        "wins": wins,
        "hit": float((pnls > 0).mean()),
        "sig_won_rate": float(wins / n),
        "pnl_total": float(pnls.sum()),
        "pnl_mean": float(pnls.mean()),
        "roi_pct": float(roi_per_trade.mean()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "hedged": hedged,
        "underfilled_entry": under_e_n,
        "skipped_thin": skipped_thin,
        "skipped_no_book": skipped_no_book,
        "sharpe": eq["sharpe"],
        "sortino": eq["sortino"],
        "max_dd": eq["max_dd"],
        "longest_dd_run": eq.get("longest_dd_run", 0),
    }


# ---------------------------------------------------------------------------
# Signal builders
# ---------------------------------------------------------------------------

def add_top_pct_signal(df: pd.DataFrame, score_col: str, pct: float) -> pd.DataFrame:
    """Filter to top `(1-pct)` of |score_col|. Direction = sign of score."""
    df = df.copy()
    df["signal"] = -1
    abs_score = df[score_col].abs()
    thr = abs_score.quantile(pct)
    sel = (abs_score >= thr) & df[score_col].notna()
    df.loc[sel, "signal"] = (df.loc[sel, score_col] > 0).astype(int)
    return df[df.signal != -1].copy()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[1] universe…")
    uni = pd.read_csv(UNIV).dropna(subset=["window_start_unix", "outcome_up"])
    uni["outcome_up"] = uni["outcome_up"].astype(int)
    print(f"    {len(uni)} markets ({(uni.timeframe=='5m').sum()} 5m, {(uni.timeframe=='15m').sum()} 15m)")

    print("[2] Phase 9 features…")
    p9 = pd.read_parquet(P9)[["slug", "poly_tfi_2m", "poly_trade_count_2m"]]

    print("[3] BTC 1m bars…")
    k1m = load_btc_1m()
    print(f"    {len(k1m)} 1m bars, range {k1m.ts_s.min()} → {k1m.ts_s.max()}")

    print("[4] book depth (full 10 levels per bucket)…")
    book = load_book(BOOK)

    # Merge & enrich
    df = uni.merge(p9, on="slug", how="left")
    df["btc_ret_2m"] = attach_btc_return_2m(df, k1m)

    # Residual: poly_tfi_2m − OLS(TFI ~ btc_ret_2m)
    fit = df.dropna(subset=["poly_tfi_2m", "btc_ret_2m"])
    cov = np.cov(fit["btc_ret_2m"].values, fit["poly_tfi_2m"].values, ddof=0)
    beta = cov[0, 1] / cov[0, 0]
    intercept = fit["poly_tfi_2m"].mean() - beta * fit["btc_ret_2m"].mean()
    df["poly_tfi_2m_resid"] = df["poly_tfi_2m"] - (intercept + beta * df["btc_ret_2m"])
    print(f"    residual: TFI = {intercept:+.4f} + ({beta:+.2f})·btc_ret_2m + ε")

    # Active universe: must have ≥1 trade in 2m + valid btc_ret
    active = df[(df["poly_trade_count_2m"] >= 1) &
                df["poly_tfi_2m"].notna() &
                df["btc_ret_2m"].notna()].copy()
    print(f"    active: {len(active)} markets")

    # ───────────────────────────────────────────────────────────────────────
    # Define gates (top-10% threshold, matching production combined_gate_v2)
    # ───────────────────────────────────────────────────────────────────────
    P9_PCT = 0.90

    g_p9   = add_top_pct_signal(active, "poly_tfi_2m",       P9_PCT)
    g_btc  = add_top_pct_signal(active, "btc_ret_2m",        P9_PCT)
    g_res  = add_top_pct_signal(active, "poly_tfi_2m_resid", P9_PCT)

    print(f"    G1 P9_orig:   {len(g_p9)} fires")
    print(f"    G2 BTC_only:  {len(g_btc)} fires")
    print(f"    G3 P9_resid:  {len(g_res)} fires")

    # ───────────────────────────────────────────────────────────────────────
    # Run engine on each gate (entry @ bucket 12 — when signal is observable)
    # ───────────────────────────────────────────────────────────────────────
    results: list[dict] = []
    print("\n[run] entry_bucket=12 (production-honest: signal observable at t+120s)…")
    for label, sub in [("G1 P9_orig",  g_p9), ("G2 BTC_only", g_btc), ("G3 P9_resid", g_res)]:
        for tf_label, tf_sub in [("ALL", sub),
                                  ("5m", sub[sub.timeframe == "5m"]),
                                  ("15m", sub[sub.timeframe == "15m"])]:
            r = run_universe(tf_sub, k1m, book, f"{label} — {tf_label}",
                             entry_bucket=ENTRY_BUCKET, notional=NOTIONAL_USD)
            results.append(r)
            if r["n"] > 0:
                print(f"  {r['label']:30s}  n={r['n']:4d}  hit={r['hit']*100:5.1f}%  "
                      f"sig_won={r['sig_won_rate']*100:5.1f}%  "
                      f"pnl_mean=${r['pnl_mean']:+.4f}  pnl_total=${r['pnl_total']:+.2f}  "
                      f"roi={r['roi_pct']:+.2f}%  hedged={r['hedged']:3d}  "
                      f"sharpe={r['sharpe']:+.2f}")

    # Also: bucket 0 entry (apples-to-apples with combined_gate_v2's lookahead-y assumption)
    print("\n[run] entry_bucket=0 (matches combined_gate_v2's $0.50 mid assumption — for reference)…")
    for label, sub in [("G1 P9_orig",  g_p9), ("G2 BTC_only", g_btc), ("G3 P9_resid", g_res)]:
        r = run_universe(sub, k1m, book, f"{label} — ALL — bucket0",
                         entry_bucket=0, notional=NOTIONAL_USD)
        results.append(r)
        if r["n"] > 0:
            print(f"  {r['label']:30s}  n={r['n']:4d}  hit={r['hit']*100:5.1f}%  "
                  f"pnl_total=${r['pnl_total']:+.2f}  roi={r['roi_pct']:+.2f}%")

    # ───────────────────────────────────────────────────────────────────────
    # Build report
    # ───────────────────────────────────────────────────────────────────────
    df_res = pd.DataFrame(results)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(OUT_CSV, index=False)
    print(f"\n[csv] wrote {OUT_CSV}")

    L = [
        "# Phase 9 Lookahead — Production-Faithful Realfills Test\n",
        "_Generated: 2026-05-05_\n",
        "## Engine\n",
        "Reuses `simulate_realfill` from `strategy_lab/polymarket_signal_grid_realfills.py` "
        "(canonical Polymarket UpDown engine that produced the published v2 numbers). "
        "Imports `book_walk_fill` from `strategy_lab/book_walk.py` and `equity_curve_stats` "
        "from `strategy_lab/polymarket_stats.py`.\n",
        "## Engine constants (production-locked)\n",
        f"- Notional per trade: **${NOTIONAL_USD:.0f}** (matches `PolymarketUpdownController` D-04)",
        f"- Entry: book-walked across top-{LEVELS} ASK levels at `bucket_10s = entry_bucket`",
        f"- Hedge-hold: every 10s bucket after entry, if Binance has reverted ≥{REV_BP} bps "
        f"against signal direction → BUY OPPOSITE side at the bucket's ASK (book-walked)",
        f"- Fee: {FEE_RATE*100:.0f}% taker, applied to winning leg's profit only",
        f"- Settlement: held leg pays $1 if correct / $0; hedge leg vice-versa",
        "",
        "## Gates compared\n",
        "- **G1 P9_orig**:  top 10% |poly_tfi_2m|,       direction = sign(TFI)        (original Phase 9)",
        "- **G2 BTC_only**: top 10% |btc_ret_2m|,        direction = sign(btc_ret_2m) (apples-to-apples lookahead baseline)",
        "- **G3 P9_resid**: top 10% |poly_tfi_2m_resid|, direction = sign(resid)      (TFI − OLS(BTC); BTC-purged Phase 9)",
        "",
        f"OLS used to construct residual: `poly_tfi_2m = {intercept:+.4f} + ({beta:+.2f})·btc_ret_2m + ε`",
        "",
        "## Active universe\n",
        f"- {len(active)} markets ({(active.timeframe=='5m').sum()} 5m, "
        f"{(active.timeframe=='15m').sum()} 15m), each with ≥1 trade in 2m + valid BTC return",
        "",
        "---\n",
        "## Results — entry @ bucket 12 (t+120s, production-honest)\n",
        "Signal becomes observable at t+120s; this is when production would actually fire.\n",
        "| Gate | n | hit | sig_won% | total PnL | mean PnL | ROI%/trade | Sharpe | hedged | thin | no_book |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in [x for x in results if "bucket0" not in x["label"]]:
        if r["n"] == 0:
            L.append(f"| {r['label']} | 0 | — | — | — | — | — | — | — | — | — |")
            continue
        L.append(
            f"| {r['label']} | {r['n']} | {r['hit']*100:.1f}% | "
            f"{r['sig_won_rate']*100:.1f}% | ${r['pnl_total']:+.2f} | "
            f"${r['pnl_mean']:+.4f} | {r['roi_pct']:+.2f}% | "
            f"{r['sharpe']:+.2f} | {r['hedged']} | {r['skipped_thin']} | {r['skipped_no_book']} |"
        )

    L += [
        "",
        "## Reference — entry @ bucket 0 (matches combined_gate_v2's lookahead-y mid-fill)\n",
        "| Gate | n | hit | total PnL | ROI%/trade |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in [x for x in results if "bucket0" in x["label"]]:
        if r["n"] == 0:
            continue
        L.append(
            f"| {r['label']} | {r['n']} | {r['hit']*100:.1f}% | "
            f"${r['pnl_total']:+.2f} | {r['roi_pct']:+.2f}% |"
        )

    # Verdict
    g_p9_all  = next(r for r in results if r["label"] == "G1 P9_orig — ALL")
    g_btc_all = next(r for r in results if r["label"] == "G2 BTC_only — ALL")
    g_res_all = next(r for r in results if r["label"] == "G3 P9_resid — ALL")
    L += [
        "",
        "---",
        "",
        "## VERDICT (entry @ bucket 12, ALL active)\n",
        f"- **G1 P9_orig**  → n={g_p9_all['n']:>4d}  hit={g_p9_all['hit']*100:.1f}%  total ${g_p9_all['pnl_total']:+.2f}  ROI {g_p9_all['roi_pct']:+.2f}%/trade",
        f"- **G2 BTC_only** → n={g_btc_all['n']:>4d}  hit={g_btc_all['hit']*100:.1f}%  total ${g_btc_all['pnl_total']:+.2f}  ROI {g_btc_all['roi_pct']:+.2f}%/trade",
        f"- **G3 P9_resid** → n={g_res_all['n']:>4d}  hit={g_res_all['hit']*100:.1f}%  total ${g_res_all['pnl_total']:+.2f}  ROI {g_res_all['roi_pct']:+.2f}%/trade",
        "",
    ]
    if g_btc_all["pnl_total"] >= g_p9_all["pnl_total"]:
        L.append(f"→ **BTC alone (G2) ≥ Phase 9 (G1)** in production engine. The Polymarket trade-flow signal is redundant against same-window BTC return.")
    else:
        L.append(f"→ G1 (P9_orig) generates ${g_p9_all['pnl_total']-g_btc_all['pnl_total']:+.2f} more than G2 (BTC_only) — Phase 9 may add some value.")

    if g_res_all["roi_pct"] < 5.0 or g_res_all["hit"] < 0.55:
        L.append(f"→ **G3 (BTC-purged residual) is weak**: ROI {g_res_all['roi_pct']:+.2f}%/trade. Phase 9's edge is almost entirely BTC momentum.")
    else:
        L.append(f"→ **G3 (BTC-purged residual) holds** at ROI {g_res_all['roi_pct']:+.2f}%/trade. Phase 9 has independent predictive power beyond BTC.")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[report] wrote {REPORT}")


if __name__ == "__main__":
    main()
