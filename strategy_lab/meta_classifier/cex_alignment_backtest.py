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

"""CEX alignment backtest harness — Phase 16 §B.

Tests whether multi-venue CEX kline reference beats single-venue (binance-only)
for predicting Polymarket UpDown resolutions, using L25 weighted-avg fills as
the liquidity verdict.

Reuses canonical engine pieces:
  - book_walk_fill        (strategy_lab/book_walk.py) — L25 walk
  - equity_curve_stats    (strategy_lab/polymarket_stats.py) — Sharpe/Sortino/MaxDD

Pipeline:
  1. Load multi-venue klines + universe + tier1 L25 entries + bucket books.
  2. Compute candidate signals via cex_alignment_signals.
  3. For each candidate × policy, run simulator → per-trade CSV + headline stats.
  4. Permutation test 1000× (shuffle outcome_up within asset×timeframe).
  5. Walk-forward 7d-train / 1d-test, 23 folds.
  6. VPS3 trusted-window cross-check (24-48h trading.events restriction).
  7. Write headline / permutation / walkforward CSVs + report.

Production constants (locked):
  LEVELS_T1   = 25  (entry walk depth, matches operator §B.4)
  LEVELS_BKT  = 10  (bucket book depth for HEDGE/SELL_BID exits)
  NOTIONAL    = $25
  REV_BP      = 5
  ENTRY_BUCKET= 12  (t+120s)
  FEE_RATE    = 0.02 (winning leg only)
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

sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))
from cex_alignment_signals import (                # noqa: E402
    load_klines as load_cex_klines,
    load_universe,
    compute_signals,
    coverage_report,
    CANDIDATES,
    col_safe,
)

# Locked production constants
LEVELS_T1 = 25
LEVELS_BKT = 10
NOTIONAL_USD = 25.0
REV_BP = 5
FEE_RATE = 0.02
ENTRY_BUCKET = 12

REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_09"
TIER1_DIR = REFRESH / "tier1_entries"
PREV_REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_02"  # bucket books vintage

OUT_DIR = ROOT / "strategy_lab" / "results" / "cex_alignment"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORT_PATH = ROOT / "strategy_lab" / "reports" / "CEX_ALIGNMENT_BACKTEST_2026_05_09.md"

RNG = np.random.default_rng(42)
N_PERM = 1000
WF_TRAIN_D = 7
WF_TEST_D = 1


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_tier1_entries(asset: str) -> dict:
    """{(slug, outcome): (asks_p[25], asks_s[25], bids_p[25], bids_s[25])}."""
    path = TIER1_DIR / f"{asset}_entries_at_t120.parquet"
    df = pd.read_parquet(path)
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS_T1)]
    cols_as = [f"ask_size_{i}"  for i in range(LEVELS_T1)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS_T1)]
    cols_bs = [f"bid_size_{i}"  for i in range(LEVELS_T1)]
    asks_p = df[cols_ap].to_numpy(dtype=float)
    asks_s = df[cols_as].to_numpy(dtype=float)
    bids_p = df[cols_bp].to_numpy(dtype=float)
    bids_s = df[cols_bs].to_numpy(dtype=float)
    out: dict = {}
    for i in range(len(df)):
        out[(df.slug.iat[i], df.outcome.iat[i])] = (asks_p[i], asks_s[i], bids_p[i], bids_s[i])
    return out


def load_bucket_book(asset: str) -> dict:
    """{slug: {(bucket_10s, outcome): (asks_p[10], asks_s[10], bids_p[10], bids_s[10])}}."""
    path = PREV_REFRESH / f"{asset}_book_depth_v3_full.csv"
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS_BKT)]
    cols_as = [f"ask_size_{i}"  for i in range(LEVELS_BKT)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS_BKT)]
    cols_bs = [f"bid_size_{i}"  for i in range(LEVELS_BKT)]
    keep = ["slug", "bucket_10s", "outcome"] + cols_ap + cols_as + cols_bp + cols_bs
    df = pd.read_csv(path, usecols=keep)
    asks_p = df[cols_ap].to_numpy(dtype=float)
    asks_s = df[cols_as].to_numpy(dtype=float)
    bids_p = df[cols_bp].to_numpy(dtype=float)
    bids_s = df[cols_bs].to_numpy(dtype=float)
    out: dict = {}
    for i in range(len(df)):
        slug = df.slug.iat[i]
        if slug not in out:
            out[slug] = {}
        out[slug][(int(df.bucket_10s.iat[i]), df.outcome.iat[i])] = (
            asks_p[i], asks_s[i], bids_p[i], bids_s[i]
        )
    return out


def load_binance_1m_per_asset() -> dict[str, pd.DataFrame]:
    """Per-asset Binance 1m closes (used for hedge trigger only — asset-truth, candidate-agnostic)."""
    df = pd.read_csv(REFRESH / "binance_klines_vps3.csv",
                     usecols=["symbol_id", "period_id", "source",
                              "time_period_start_us", "price_close"])
    df = df[(df.period_id == "1MIN") & (df.source == "binance-spot-ws")].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for asset, sym in [("btc", "BINANCE_SPOT_BTC_USDT"),
                       ("eth", "BINANCE_SPOT_ETH_USDT"),
                       ("sol", "BINANCE_SPOT_SOL_USDT")]:
        sub = df[df.symbol_id == sym].sort_values("ts_s").reset_index(drop=True)
        out[asset] = sub[["ts_s", "price_close"]]
    return out


def asof_close_1m(k1m: pd.DataFrame, ts_s: int) -> float:
    """End-time-indexed asof for 1MIN bars (matches end-time-indexing fix from 2026-05-06)."""
    if k1m.empty:
        return float("nan")
    end_us = (k1m.ts_s.astype("int64") + 60).values * 1_000_000
    target_us = int(ts_s) * 1_000_000
    idx = int(np.searchsorted(end_us, target_us, side="right")) - 1
    if idx < 0:
        return float("nan")
    return float(k1m.price_close.iloc[idx])


# ---------------------------------------------------------------------------
# Simulator (HOLD policy first; HEDGE/SELL added in v2)
# ---------------------------------------------------------------------------

def simulate_hold(row: pd.Series, entry_book: dict,
                  notional_usd: float = NOTIONAL_USD) -> dict | None:
    """Buy at entry @ t+120s, hold to resolution, settle 1.0 if won else 0."""
    sig = int(row.signal)
    if sig < 0:
        return None
    held = "Up" if sig == 1 else "Down"
    key = (row.slug, held)
    if key not in entry_book:
        return None
    ask_p, ask_s, _bid_p, _bid_s = entry_book[key]
    vwap_e, shares_e, usd_e, lvls_e, under_e = book_walk_fill(ask_p, ask_s, notional_usd)
    if shares_e <= 0:
        return None
    if under_e and usd_e < notional_usd * 0.5:
        return {"skipped_thin": True}

    sig_won = (sig == int(row.outcome_up))
    if sig_won:
        gross = shares_e * 1.0
        profit_pre_fee = gross - usd_e
        fee = profit_pre_fee * FEE_RATE if profit_pre_fee > 0 else 0.0
        pnl = profit_pre_fee - fee
    else:
        pnl = -usd_e
    return dict(
        pnl=pnl, cost=usd_e, vwap_e=vwap_e, shares_e=shares_e,
        lvls_e=int(lvls_e), under_e=bool(under_e), sig_won=sig_won, hedged=False,
        skipped_thin=False,
    )


def simulate_hedge(row: pd.Series, k1m: pd.DataFrame, entry_book: dict,
                   bucket_book: dict, max_bucket: int,
                   notional_usd: float = NOTIONAL_USD,
                   rev_bp: int = REV_BP) -> dict | None:
    """HEDGE_HOLD policy — mirrors phase9_lookahead_realfills_multi.simulate_realfill."""
    sig = int(row.signal)
    if sig < 0:
        return None
    held = "Up" if sig == 1 else "Down"
    other = "Down" if sig == 1 else "Up"
    if (row.slug, held) not in entry_book:
        return None
    ask_p, ask_s, _bp, _bs = entry_book[(row.slug, held)]
    vwap_e, shares_e, usd_e, lvls_e, under_e = book_walk_fill(ask_p, ask_s, notional_usd)
    if shares_e <= 0:
        return None
    if under_e and usd_e < notional_usd * 0.5:
        return {"skipped_thin": True}

    ws = int(row.window_start_unix)
    asset_at_entry = asof_close_1m(k1m, ws + ENTRY_BUCKET * 10)
    hedge = None
    slug_book = bucket_book.get(row.slug, {})
    if rev_bp is not None and np.isfinite(asset_at_entry):
        for bucket in range(ENTRY_BUCKET + 1, max_bucket + 1):
            ts_in = ws + bucket * 10
            a_now = asof_close_1m(k1m, ts_in)
            if not np.isfinite(a_now):
                continue
            bp = (a_now - asset_at_entry) / asset_at_entry * 10000.0
            reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
            if not reverted:
                continue
            hkey = (bucket, other)
            if hkey not in slug_book:
                break
            h_ask_p, h_ask_s, _, _ = slug_book[hkey]
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

    sig_won = (sig == int(row.outcome_up))
    if hedge is None:
        if sig_won:
            gross = shares_e * 1.0
            profit_pre_fee = gross - usd_e
            fee = profit_pre_fee * FEE_RATE if profit_pre_fee > 0 else 0.0
            pnl = profit_pre_fee - fee
        else:
            pnl = -usd_e
        return dict(pnl=pnl, cost=usd_e, vwap_e=vwap_e, shares_e=shares_e,
                    lvls_e=int(lvls_e), under_e=bool(under_e), sig_won=sig_won,
                    hedged=False, skipped_thin=False)

    vwap_h, shares_h, usd_h, lvls_h, under_h = hedge
    cost = usd_e + usd_h
    if sig_won:
        gross = shares_e * 1.0
        fee = shares_e * (1.0 - vwap_e) * FEE_RATE
    else:
        gross = shares_h * 1.0
        fee = shares_h * (1.0 - vwap_h) * FEE_RATE
    pnl = gross - cost - fee
    return dict(pnl=pnl, cost=cost, vwap_e=vwap_e, shares_e=shares_e,
                lvls_e=int(lvls_e), under_e=bool(under_e),
                vwap_h=vwap_h, shares_h=shares_h, lvls_h=int(lvls_h), under_h=bool(under_h),
                sig_won=sig_won, hedged=True, skipped_thin=False)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_candidate(df: pd.DataFrame, candidate: str, policy: str,
                  k1m_per_asset: dict, entry_books: dict, bucket_books: dict
                  ) -> tuple[pd.DataFrame, dict]:
    """Run one (candidate, policy) over the full universe, return (per-trade df, headline dict)."""
    sig_col = f"signal_{col_safe(candidate)}"
    rows = []
    for r in df.itertuples(index=False):
        ws = int(r.window_start_unix)
        sig = int(getattr(r, sig_col))
        # Build a Series-like object for the simulator (avoid full pd.Series allocation per row)
        row_obj = pd.Series({"slug": r.slug, "outcome_up": r.outcome_up,
                              "window_start_unix": ws, "timeframe": r.timeframe,
                              "signal": sig})
        asset = r.asset
        if policy == "HOLD":
            res = simulate_hold(row_obj, entry_books[asset])
        elif policy == "HEDGE":
            max_bucket = 89 if r.timeframe == "15m" else 29
            res = simulate_hedge(row_obj, k1m_per_asset[asset],
                                 entry_books[asset], bucket_books[asset], max_bucket)
        else:
            raise ValueError(f"unknown policy {policy!r}")
        if res is None:
            continue
        if res.get("skipped_thin"):
            continue
        out = {"asset": asset, "slug": r.slug, "timeframe": r.timeframe,
               "ws": ws, "signal": sig, "outcome_up": int(r.outcome_up),
               **{k: res.get(k) for k in ("pnl", "cost", "vwap_e", "shares_e",
                                            "lvls_e", "under_e", "sig_won", "hedged")}}
        rows.append(out)

    per_trade = pd.DataFrame(rows)
    if per_trade.empty:
        return per_trade, {"candidate": candidate, "policy": policy, "n": 0}

    pnls = per_trade["pnl"].to_numpy(dtype=float)
    costs = per_trade["cost"].to_numpy(dtype=float)
    ws_arr = per_trade["ws"].to_numpy(dtype=float)
    eq = equity_curve_stats(pnls, trade_timestamps=ws_arr)
    headline = {
        "candidate": candidate, "policy": policy,
        "n": int(len(per_trade)),
        "hit_rate": float((pnls > 0).mean()),
        "sig_won_rate": float(per_trade["sig_won"].mean()),
        "total_pnl": float(pnls.sum()),
        "mean_pnl": float(pnls.mean()),
        "roi_pct": float((pnls / np.where(costs > 0, costs, 1.0)).mean() * 100),
        "sharpe": float(eq.get("sharpe", float("nan"))),
        "sortino": float(eq.get("sortino", float("nan"))),
        "max_dd": float(eq.get("max_dd", float("nan"))),
        "avg_vwap_e": float(per_trade["vwap_e"].mean()),
        "avg_lvls_e": float(per_trade["lvls_e"].mean()),
        "underfilled_pct": float(100 * per_trade["under_e"].mean()),
        "hedged_pct": float(100 * per_trade["hedged"].mean()),
    }
    return per_trade, headline


def permutation_test(per_trade: pd.DataFrame, n_perm: int = N_PERM) -> dict:
    """Shuffle outcome_up within (asset, timeframe), recompute PnL on shuffled labels.
    Returns null distribution + observed p-value.

    Permutation simulation: assumes HOLD-style PnL where pnl_won = shares*(1-vwap) - fee
    and pnl_lost = -cost. We approximate by re-using observed shares/cost/vwap and only
    flipping sig_won.
    """
    if per_trade.empty:
        return {"observed": 0.0, "p_value": float("nan"), "n_perm": 0}

    observed_pnl = per_trade["pnl"].sum()
    rng = np.random.default_rng(42)
    null_pnls = np.zeros(n_perm, dtype=float)

    # Reconstruct per-trade pnl-if-won and pnl-if-lost (works for HOLD; HEDGE is approx)
    shares = per_trade["shares_e"].to_numpy(dtype=float)
    vwap_e = per_trade["vwap_e"].to_numpy(dtype=float)
    cost = per_trade["cost"].to_numpy(dtype=float)
    pnl_win = shares * (1.0 - vwap_e)
    pnl_win = np.where(pnl_win > 0, pnl_win * (1.0 - FEE_RATE), pnl_win)
    pnl_lose = -cost

    # Shuffle outcome_up within (asset, timeframe) groups
    groups = per_trade.groupby(["asset", "timeframe"]).indices
    for p in range(n_perm):
        sig_won_shuf = np.zeros(len(per_trade), dtype=bool)
        for _, idx in groups.items():
            outcomes = per_trade["outcome_up"].iloc[idx].to_numpy()
            shuffled = rng.permutation(outcomes)
            sigs = per_trade["signal"].iloc[idx].to_numpy()
            sig_won_shuf[idx] = (sigs == shuffled)
        pnl_shuf = np.where(sig_won_shuf, pnl_win, pnl_lose)
        null_pnls[p] = pnl_shuf.sum()

    p_value = float((null_pnls >= observed_pnl).mean())
    return {
        "observed": float(observed_pnl),
        "null_mean": float(null_pnls.mean()),
        "null_std": float(null_pnls.std()),
        "null_q05": float(np.quantile(null_pnls, 0.05)),
        "null_q95": float(np.quantile(null_pnls, 0.95)),
        "p_value": p_value,
        "n_perm": int(n_perm),
    }


def walk_forward(per_trade: pd.DataFrame, train_days: int = WF_TRAIN_D,
                 test_days: int = WF_TEST_D) -> pd.DataFrame:
    """Rolling 7d-train / 1d-test folds. For non-q90 candidates this just measures
    PnL stability across windows (no threshold to refit)."""
    if per_trade.empty:
        return pd.DataFrame()
    df = per_trade.sort_values("ws").copy()
    ws_min = int(df["ws"].min())
    ws_max = int(df["ws"].max())
    fold_secs = test_days * 86400
    train_secs = train_days * 86400

    folds = []
    fold_id = 0
    cur = ws_min + train_secs
    while cur + fold_secs <= ws_max + 1:
        train_lo, train_hi = cur - train_secs, cur
        test_lo, test_hi = cur, cur + fold_secs
        train = df[(df["ws"] >= train_lo) & (df["ws"] < train_hi)]
        test = df[(df["ws"] >= test_lo) & (df["ws"] < test_hi)]
        folds.append({
            "fold": fold_id,
            "train_n": int(len(train)),
            "train_pnl": float(train["pnl"].sum()),
            "train_hit": float((train["pnl"] > 0).mean()) if len(train) else float("nan"),
            "test_n": int(len(test)),
            "test_pnl": float(test["pnl"].sum()),
            "test_hit": float((test["pnl"] > 0).mean()) if len(test) else float("nan"),
        })
        cur += fold_secs
        fold_id += 1
    return pd.DataFrame(folds)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(candidates_subset: list[str] | None = None,
         policies: list[str] = ("HOLD", "HEDGE")):
    print("\n=== CEX Alignment Backtest — Phase 16 §B ===\n")

    print("[1/6] Loading klines (multi-venue)...")
    klines = load_cex_klines()
    print(f"   {len(klines)} (asset,venue,source) series loaded")

    print("[2/6] Loading universe...")
    universe = load_universe()
    print(f"   {len(universe)} markets ({universe['timeframe'].value_counts().to_dict()})")

    print("[3/6] Computing signals for all candidates...")
    cands = list(candidates_subset) if candidates_subset else list(CANDIDATES)
    df = compute_signals(universe, klines, candidates=cands)
    cov = coverage_report(df, candidates=cands)
    print("\nCoverage:")
    print(cov.to_string(index=False))
    cov.to_csv(OUT_DIR / "coverage.csv", index=False)

    print("\n[4/6] Loading L25 entry books + bucket books per asset...")
    entry_books = {a: load_tier1_entries(a) for a in ("btc", "eth", "sol")}
    bucket_books = {a: load_bucket_book(a) for a in ("btc", "eth", "sol")}
    k1m_per_asset = load_binance_1m_per_asset()
    for a in ("btc", "eth", "sol"):
        print(f"   {a}: entry_book={len(entry_books[a])} keys, "
              f"bucket_book={len(bucket_books[a])} slugs, "
              f"k1m={len(k1m_per_asset[a])} bars")

    print("\n[5/6] Running candidates × policies...")
    headline_rows = []
    perm_rows = []
    wf_frames = []
    for cand in cands:
        for policy in policies:
            print(f"   ▶ {cand:>14s} × {policy}")
            per_trade, head = run_candidate(df, cand, policy,
                                              k1m_per_asset, entry_books, bucket_books)
            headline_rows.append(head)
            if not per_trade.empty:
                per_trade.to_csv(OUT_DIR / f"per_trade_{cand}_{policy}.csv", index=False)
                perm = permutation_test(per_trade, n_perm=N_PERM)
                perm["candidate"] = cand
                perm["policy"] = policy
                perm_rows.append(perm)
                wf = walk_forward(per_trade)
                wf["candidate"] = cand
                wf["policy"] = policy
                wf_frames.append(wf)
                print(f"     n={head['n']:5d}  hit={head['hit_rate']*100:5.2f}%  "
                      f"pnl=${head['total_pnl']:+8.2f}  sharpe={head['sharpe']:+.2f}  "
                      f"perm_p={perm['p_value']:.4f}")
            else:
                print(f"     n=0 (skipped — no surviving trades)")

    headline_df = pd.DataFrame(headline_rows).sort_values(
        ["policy", "total_pnl"], ascending=[True, False])
    headline_df.to_csv(OUT_DIR / "headline.csv", index=False)
    perm_df = pd.DataFrame(perm_rows)
    perm_df.to_csv(OUT_DIR / "permutation.csv", index=False)
    wf_df = pd.concat(wf_frames, ignore_index=True) if wf_frames else pd.DataFrame()
    wf_df.to_csv(OUT_DIR / "walkforward.csv", index=False)
    print(f"\n   wrote {OUT_DIR}/{{headline,permutation,walkforward,coverage,per_trade_*}}.csv")

    print("\n[6/6] Writing report...")
    write_report(headline_df, perm_df, wf_df, cov)
    print(f"   wrote {REPORT_PATH}")


def write_report(headline: pd.DataFrame, perm: pd.DataFrame,
                 wf: pd.DataFrame, cov: pd.DataFrame):
    L = [
        "# CEX Alignment Backtest — Phase 16 §B",
        "_Generated: 2026-05-09_",
        "",
        "## Question",
        "Does multi-venue CEX kline reference (binance + coinbase + kraken + ensembles) beat",
        "single-venue (binance-only) for predicting Polymarket UpDown resolutions?",
        "Tested with $25 notional through L25 weighted-avg fill prices.",
        "",
        "## Engine constants (locked, production-faithful)",
        f"- Notional: ${NOTIONAL_USD:.0f}",
        f"- Entry walk: top-{LEVELS_T1} ASK levels at t+{ENTRY_BUCKET*10}s",
        f"- Hedge bucket book: top-{LEVELS_BKT} levels (10s buckets)",
        f"- Hedge trigger: ≥{REV_BP} bps reversion on Binance asset price (asset-truth, candidate-agnostic)",
        f"- Fee: {FEE_RATE*100:.0f}% taker on winning leg's profit only",
        f"- Permutation: {N_PERM}× shuffle outcome_up within (asset, timeframe)",
        f"- Walk-forward: {WF_TRAIN_D}d train / {WF_TEST_D}d test rolling",
        "",
        "## Coverage per candidate (Skip rate measures venue-data availability)",
        "",
        cov.to_markdown(index=False) if not cov.empty else "_no rows_",
        "",
        "## Headline ranking (by policy)",
        "",
    ]
    if not headline.empty:
        for policy, sub in headline.groupby("policy"):
            L += [f"### Policy: {policy}", "",
                  sub.drop(columns=["policy"]).to_markdown(index=False), ""]
    L += ["## Permutation null vs observed",
          "_Spec target: p<0.01 (operator §4)_",
          "",
          perm.to_markdown(index=False) if not perm.empty else "_no rows_",
          ""]
    L += ["## Walk-forward stability (per-fold PnL)",
          "_Edge must hold across MAJORITY of folds, not just averaged._",
          ""]
    if not wf.empty:
        for (cand, policy), sub in wf.groupby(["candidate", "policy"]):
            pos_folds = (sub["test_pnl"] > 0).sum()
            n_folds = len(sub)
            L += [f"### {cand} × {policy}: {pos_folds}/{n_folds} positive test folds  "
                  f"(median test PnL ${sub['test_pnl'].median():+.2f})", ""]
    L += ["",
          "## Verdict (auto-generated from headline)",
          ""]
    if not headline.empty:
        for policy, sub in headline.groupby("policy"):
            top = sub.iloc[0]
            L += [f"**{policy}** — top candidate: `{top['candidate']}` "
                  f"(n={int(top['n'])}, hit={top['hit_rate']*100:.2f}%, "
                  f"PnL=${top['total_pnl']:+.2f}, Sharpe={top['sharpe']:+.2f})", ""]
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--policies", nargs="+", default=["HOLD"],
                   choices=["HOLD", "HEDGE"],
                   help="Policies to run (HEDGE requires refresh_2026_05_02 bucket books, "
                        "covers only first ~14d of universe)")
    p.add_argument("--candidates", nargs="*", default=None,
                   help="Subset of candidates; default = all")
    args = p.parse_args()
    main(candidates_subset=args.candidates, policies=args.policies)
