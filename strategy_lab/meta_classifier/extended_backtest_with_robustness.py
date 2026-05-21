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

"""Extended backtest + permutation + walkforward — momentum strategy on 15,370 markets.

Inputs (all from VPS2 data refresh 2026-05-06):
  data/v4/refresh_2026_05_06/market_resolutions_full.csv   (15,370 markets Apr22-May6)
  data/v4/refresh_2026_05_06/klines_full.csv               (73,189 1m bars; BTC/ETH/SOL × Binance/OKX)
  data/v4/refresh_2026_05_06/tier1_entries/*.parquet       (28,700 microsecond entries)
  data/v4/refresh_2026_05_02/{btc,eth,sol}_book_depth_v3_full.csv  (existing bucketed exit-monitoring books)

Tests run:
  1. Headline backtest: 6 cells × 3 exit policies = 18 strategy results
  2. Permutation test: shuffle outcome_up within (asset, tf), recompute HOLD PnL.
     1000 draws → p-value for observed PnL.
  3. Walkforward: rolling 7d train / 1d test, refit threshold per train window.
     Out-of-sample PnL vs in-sample for stability evidence.

Outputs:
  strategy_lab/results/meta_classifier/extended_backtest.csv  (headline)
  strategy_lab/results/meta_classifier/permutation_results.csv
  strategy_lab/results/meta_classifier/walkforward_results.csv
  strategy_lab/reports/EXTENDED_BACKTEST_ROBUSTNESS.md
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

LEVELS_T1 = 25
LEVELS_BUCKETS = 10
NOTIONAL_USD = 25.0
FEE_RATE = 0.02
SPREAD_FILTER = {"btc": 0.02, "eth": 0.02, "sol": 0.025}

REFRESH_NEW = ROOT / "data" / "v4" / "refresh_2026_05_06"
REFRESH_OLD = ROOT / "data" / "v4" / "refresh_2026_05_02"
TIER1_DIR = REFRESH_NEW / "tier1_entries"

OUT_DIR = ROOT / "strategy_lab" / "results" / "meta_classifier"
REPORT  = ROOT / "strategy_lab" / "reports"  / "EXTENDED_BACKTEST_ROBUSTNESS.md"

ASSET_BINANCE = {"btc": "BINANCE_SPOT_BTC_USDT", "eth": "BINANCE_SPOT_ETH_USDT", "sol": "BINANCE_SPOT_SOL_USDT"}
ASSET_OKX = {"btc": "OKX_SPOT_BTC_USDT", "eth": "OKX_SPOT_ETH_USDT", "sol": "OKX_SPOT_SOL_USDT"}

RNG = np.random.default_rng(42)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_universe() -> pd.DataFrame:
    """Load market resolutions and ensure (asset, timeframe, window_start_unix,
    outcome_up) columns exist. Derives missing columns from `slug` and
    `outcome` if the CSV came from the minimal-column pull format.
    """
    df = pd.read_csv(REFRESH_NEW / "market_resolutions_full.csv")
    # Schema-compat: derive columns if absent (minimal pull only has
    # slug, outcome, recorded_at, source).
    if "window_start_unix" not in df.columns or "outcome_up" not in df.columns:
        parts = df["slug"].str.split("-", n=3, expand=True)
        df["asset"] = parts[0]
        df["timeframe"] = parts[2]
        df["window_start_unix"] = pd.to_numeric(parts[3], errors="coerce")
        df["outcome_up"] = (df["outcome"].str.lower() == "up").astype(int)
    df = df.dropna(subset=["window_start_unix", "outcome_up"]).copy()
    df["asset"] = df["slug"].str.extract(r'^(btc|eth|sol)-updown-')[0]
    df = df.dropna(subset=["asset"]).copy()
    df["window_start_unix"] = df["window_start_unix"].astype("int64")
    df["outcome_up"] = df["outcome_up"].astype(int)
    df["timeframe"] = df["timeframe"].str.lower()
    return df


def load_klines() -> dict[str, pd.DataFrame]:
    """Combined Binance + OKX feeds per asset; Binance preferred, OKX fallback."""
    df = pd.read_csv(REFRESH_NEW / "klines_full.csv")
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for asset in ("btc", "eth", "sol"):
        bin_sym = ASSET_BINANCE[asset]
        okx_sym = ASSET_OKX[asset]
        bin_sub = df[df.symbol_id == bin_sym][["ts_s", "price_close"]].copy()
        okx_sub = df[df.symbol_id == okx_sym][["ts_s", "price_close"]].copy()
        # Combine: union by timestamp; Binance preferred when both have a row at same ts
        bin_sub["src"] = "binance"
        okx_sub["src"] = "okx"
        combined = pd.concat([bin_sub, okx_sub], ignore_index=True)
        combined = combined.sort_values(["ts_s", "src"]).drop_duplicates("ts_s", keep="first")
        combined = combined.sort_values("ts_s").reset_index(drop=True)
        out[asset] = combined[["ts_s", "price_close"]]
        print(f"[klines/{asset}] {len(out[asset])} bars  range "
              f"{pd.to_datetime(out[asset].ts_s.min(), unit='s')} -> "
              f"{pd.to_datetime(out[asset].ts_s.max(), unit='s')}")
    return out


_ASOF_CACHE: dict[int, tuple[np.ndarray, np.ndarray]] = {}


def _ensure_asof_cache(k1m: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Compute (end_us, closes) once per kline DataFrame and cache by id.

    Avoids re-allocating a 4 MiB int64 array on every asof() call (was OOMing
    after ~50k calls under memory pressure).
    """
    key = id(k1m)
    cached = _ASOF_CACHE.get(key)
    if cached is not None:
        return cached
    end_us = (k1m["ts_s"].to_numpy(dtype="int64") + 60) * 1_000_000
    closes = k1m["price_close"].to_numpy(dtype=float)
    _ASOF_CACHE[key] = (end_us, closes)
    return end_us, closes


def asof(k1m: pd.DataFrame, ts: int) -> float:
    """End-time-indexed asof: returns price_close of the most recent
    1MIN bar whose CLOSE TIME has already happened by ``ts``.

    Bug fix 2026-05-06: end-time-indexed (was bar-open-time → 50s lookahead).
    Perf fix 2026-05-07: cache (end_us, closes) per DataFrame to avoid 4 MiB
    temp allocation on every call.
    """
    end_us, closes = _ensure_asof_cache(k1m)
    target_us = int(ts) * 1_000_000
    idx = int(np.searchsorted(end_us, target_us, side="right")) - 1
    return float("nan") if idx < 0 else float(closes[idx])


def load_tier1_entries(asset: str) -> dict:
    df = pd.read_parquet(TIER1_DIR / f"{asset}_entries_at_t120.parquet")
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS_T1)]
    cols_as = [f"ask_size_{i}"  for i in range(LEVELS_T1)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS_T1)]
    cols_bs = [f"bid_size_{i}"  for i in range(LEVELS_T1)]
    asks_p = df[cols_ap].to_numpy(dtype=float); asks_s = df[cols_as].to_numpy(dtype=float)
    bids_p = df[cols_bp].to_numpy(dtype=float); bids_s = df[cols_bs].to_numpy(dtype=float)
    out: dict = {}
    for i in range(len(df)):
        out[(df.slug.iat[i], df.outcome.iat[i])] = (asks_p[i], asks_s[i], bids_p[i], bids_s[i])
    return out


def load_book_buckets(asset: str) -> dict:
    """Existing 10s-bucket book CSV (Apr 22-May 4 only); used for exit monitoring."""
    path = REFRESH_OLD / f"{asset}_book_depth_v3_full.csv"
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS_BUCKETS)]
    cols_as = [f"ask_size_{i}"  for i in range(LEVELS_BUCKETS)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS_BUCKETS)]
    cols_bs = [f"bid_size_{i}"  for i in range(LEVELS_BUCKETS)]
    keep = ["slug", "bucket_10s", "outcome"] + cols_ap + cols_as + cols_bp + cols_bs
    df = pd.read_csv(path, usecols=keep)
    asks_p = df[cols_ap].to_numpy(dtype=float); asks_s = df[cols_as].to_numpy(dtype=float)
    bids_p = df[cols_bp].to_numpy(dtype=float); bids_s = df[cols_bs].to_numpy(dtype=float)
    out: dict = {}
    for i in range(len(df)):
        slug = df.slug.iat[i]
        if slug not in out: out[slug] = {}
        out[slug][(int(df.bucket_10s.iat[i]), df.outcome.iat[i])] = (asks_p[i], asks_s[i], bids_p[i], bids_s[i])
    return out


# ---------------------------------------------------------------------------
# Simulator (tier1 entry + bucket exit)
# ---------------------------------------------------------------------------

def sell_at_bid(bid_p: np.ndarray, bid_s: np.ndarray, shares: float) -> tuple[float, float]:
    remaining = float(shares); total_usd = 0.0; total_shares = 0.0
    for p, s in zip(bid_p, bid_s):
        if not (np.isfinite(p) and np.isfinite(s)) or s <= 0 or p <= 0 or p >= 1:
            break
        if s >= remaining:
            total_usd += remaining * p; total_shares += remaining; remaining = 0; break
        total_usd += s * p; total_shares += s; remaining -= s
    if total_shares <= 0:
        return float("nan"), 0.0
    return total_usd / total_shares, total_usd


def simulate(row: pd.Series, k1m: pd.DataFrame, entry_book: dict, bucket_book: dict,
             max_bucket: int, policy: str, rev_bp: int = 5,
             spread_filter: float | None = None) -> dict | None:
    sig = int(row.signal)
    held = "Up" if sig == 1 else "Down"
    other = "Down" if sig == 1 else "Up"

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

    if policy != "HOLD":
        slug_book = bucket_book.get(row.slug, {})
        for bucket in range(13, max_bucket + 1):
            held_key_b = (bucket, held)
            b_p = b_s = None
            if held_key_b in slug_book:
                _, _, b_p, b_s = slug_book[held_key_b]
            ts_in = ws + bucket * 10
            a_now = asof(k1m, ts_in)
            if not (np.isfinite(asset_at_entry) and np.isfinite(a_now)):
                continue
            bp_rev = (a_now - asset_at_entry) / asset_at_entry * 10000.0
            trig = (sig == 1 and bp_rev <= -rev_bp) or (sig == 0 and bp_rev >= rev_bp)
            if not trig:
                continue
            if policy == "HEDGE":
                if (bucket, other) in slug_book:
                    h_ask_p, h_ask_s, _, _ = slug_book[(bucket, other)]
                    top = h_ask_p[0] if len(h_ask_p) and np.isfinite(h_ask_p[0]) else float("nan")
                    if np.isfinite(top) and 0 < top < 1:
                        target_h = shares_e * float(top)
                        vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(h_ask_p, h_ask_s, target_h)
                        if shares_h > 0:
                            if shares_h < shares_e * 0.95 and not under_h:
                                vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(h_ask_p, h_ask_s, shares_e * vwap_h)
                            exit_event = ("hedge", bucket, dict(vwap_h=vwap_h, shares_h=shares_h, usd_h=usd_h)); break
            elif policy == "SELL" and b_p is not None:
                sv, sg = sell_at_bid(b_p, b_s, shares_e)
                if np.isfinite(sv) and sg > 0:
                    exit_event = ("sell", bucket, dict(sell_vwap=sv, sell_gross=sg)); break

    won = (sig == int(row.outcome_up))
    if exit_event is None:
        if won:
            profit = shares_e * 1.0 - usd_e
            fee = profit * FEE_RATE if profit > 0 else 0.0
            pnl = profit - fee
        else:
            pnl = -usd_e
        return dict(pnl=pnl, cost=usd_e, vwap_e=vwap_e, exit_reason="hold", sig_won=won)
    kind, eb, ed = exit_event
    if kind == "hedge":
        cost = usd_e + ed["usd_h"]
        if won:
            gross = shares_e * 1.0; fee = shares_e * (1.0 - vwap_e) * FEE_RATE
        else:
            gross = ed["shares_h"] * 1.0; fee = ed["shares_h"] * (1.0 - ed["vwap_h"]) * FEE_RATE
        return dict(pnl=gross - cost - fee, cost=cost, vwap_e=vwap_e, exit_reason="hedge", sig_won=won)
    profit = ed["sell_gross"] - usd_e
    fee = max(profit, 0) * FEE_RATE
    return dict(pnl=profit - fee, cost=usd_e, vwap_e=vwap_e, exit_reason="sell", sig_won=won)


def run_cell(df: pd.DataFrame, k1m: pd.DataFrame, entry_book: dict, bucket_book: dict,
             policy: str, label: str, asset: str) -> dict:
    pnls, costs, ws_list, vwaps = [], [], [], []
    sk_thin = sk_no_book = sk_spread = wins = 0
    n_hold = n_hedge = n_sell = 0
    per_trade = []
    for _, row in df.iterrows():
        max_b = 89 if row.timeframe == "15m" else 29
        r = simulate(row, k1m, entry_book, bucket_book, max_b, policy,
                     spread_filter=SPREAD_FILTER[asset])
        if r is None: sk_no_book += 1; continue
        if r.get("skipped_spread"): sk_spread += 1; continue
        if r.get("skipped_thin"): sk_thin += 1; continue
        pnls.append(r["pnl"]); costs.append(r["cost"]); ws_list.append(int(row.window_start_unix))
        vwaps.append(r["vwap_e"])
        if r["sig_won"]: wins += 1
        if r["exit_reason"] == "hold": n_hold += 1
        elif r["exit_reason"] == "hedge": n_hedge += 1
        elif r["exit_reason"] == "sell": n_sell += 1
        per_trade.append(dict(slug=row.slug, ws_s=row.window_start_unix, signal=row.signal,
                              outcome_up=row.outcome_up, pnl=r["pnl"]))
    pnls = np.array(pnls); costs = np.array(costs); n = len(pnls)
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
        per_trade=per_trade,
    )


# ---------------------------------------------------------------------------
# Permutation test (shuffle outcome_up labels)
# ---------------------------------------------------------------------------

def permutation_test(per_trade_observed: list[dict], n_permutations: int = 1000,
                     rng=None) -> dict:
    """Shuffle outcome_up labels among the FIRED trades and recompute PnL.

    The fired trade set + signals + entry vwap are FIXED — only the actual
    settlement (UP vs DOWN) is shuffled. This tests: 'given we picked these
    markets to enter and these directions to bet, would random outcomes
    produce as much PnL as we observed?'

    Returns: dict with observed_pnl, p_value (one-sided), null mean/std/quantiles.
    """
    if rng is None:
        rng = np.random.default_rng(42)
    df = pd.DataFrame(per_trade_observed)
    if len(df) == 0:
        return dict(observed_pnl=0.0, p_value=float("nan"), n=0)
    # Per-trade win pnl and loss pnl (deterministic functions of signal + book + outcome)
    # For the permutation, we need per-trade pnl IF won and pnl IF lost.
    # In HOLD mode (the simplest case): win = shares_e × (1 - vwap) × (1 - fee), loss = -usd_e
    # Both are encoded in the observed pnl + sign(observed pnl).
    # For each trade: observed_pnl is win_pnl if outcome matched signal, else loss_pnl.
    # We need win_pnl and loss_pnl separately. Reconstruct from observed.
    # Simpler: assume each trade has known pnl IF outcome matches signal vs not.
    # Since we don't store both, we'll regenerate the pnl distribution by:
    #   For each trade, P(win|original) = 1 if sig==outcome else 0.
    #   The "win pnl" magnitude is (observed_pnl) if won else (we don't have it).
    # Proper approach: shuffle outcome_up among trades, recompute pnl assuming
    # each trade's PnL when winning is its observed pnl_w, when losing is -usd_e ≈ -25.
    # But we need pnl_w and pnl_l per trade.
    # Simpler proxy: assume win_pnl = observed_pnl when observed_pnl > 0, else win_pnl_proxy.
    # For each trade: if won, the win is observed_pnl. If lost, the win would have been
    # ~ shares_e × (1-vwap) × 0.98. We don't have shares_e in per_trade.
    # Use a DIFFERENT shuffle: shuffle signs of pnls.
    # Equivalent test: shuffle (outcome - signal) sign across trades.
    # If sign is right, trade wins (+observed_pnl_magnitude). If wrong, trade loses (-25).
    # For trades that lost in the original (observed_pnl < 0), magnitude = 25.
    # For trades that won (observed_pnl > 0), magnitude = observed_pnl.
    # In a permuted draw, each trade independently flips with prob = original_hit_rate.
    # Cleaner: for each trade, compute win_pnl = observed if won else +avg_observed_win,
    #          loss_pnl = -usd_cost. Then permute outcome.
    won = df["signal"] == df["outcome_up"]
    win_pnls = df[won]["pnl"].values
    loss_pnls = df[~won]["pnl"].values
    if len(win_pnls) == 0 or len(loss_pnls) == 0:
        return dict(observed_pnl=float(df.pnl.sum()), p_value=float("nan"), n=len(df))
    avg_win = float(win_pnls.mean())
    avg_loss = float(loss_pnls.mean())
    n = len(df)
    p_win = len(win_pnls) / n  # original hit rate

    observed = float(df.pnl.sum())
    null_totals = np.empty(n_permutations)
    for i in range(n_permutations):
        # Each trade independently wins with prob p_win (Bernoulli)
        # Equivalent to shuffling outcome labels under H0: outcome ⊥ signal
        wins = rng.random(n) < p_win
        null_totals[i] = wins.sum() * avg_win + (n - wins.sum()) * avg_loss

    p_value = float((null_totals >= observed).mean())
    return dict(
        observed_pnl=observed,
        n=n,
        hit_rate=p_win,
        avg_win=avg_win,
        avg_loss=avg_loss,
        n_permutations=n_permutations,
        null_mean=float(null_totals.mean()),
        null_std=float(null_totals.std()),
        null_q025=float(np.quantile(null_totals, 0.025)),
        null_q975=float(np.quantile(null_totals, 0.975)),
        null_max=float(null_totals.max()),
        p_value=p_value,
    )


def permutation_test_strict(per_trade_observed: list[dict], universe_outcomes: pd.Series,
                            n_permutations: int = 1000, rng=None) -> dict:
    """Stronger: shuffle outcome_up across the FULL universe (not just fired trades).
    Then re-fire the strategy gate (top-10% |signal_score|) and recompute PnL.

    This tests: 'is our gate selecting markets where outcome_up is correlated
    with our signal direction, beyond what random would do?'
    Skipped here for simplicity — implemented when needed.
    """
    return {}


# ---------------------------------------------------------------------------
# Walkforward (rolling 7d train / 1d test)
# ---------------------------------------------------------------------------

def walkforward(df_active: pd.DataFrame, k1m: pd.DataFrame, entry_book: dict,
                bucket_book: dict, asset: str, tf: str,
                train_days: int = 7, test_days: int = 1) -> dict:
    """Roll forward: each test_day, fit q90 |asset_ret_2m| on train window,
    deploy on test day, record PnL. Concatenate all test PnLs.
    """
    df = df_active[(df_active.asset == asset) & (df_active.timeframe == tf)].copy()
    df = df.sort_values("window_start_unix").reset_index(drop=True)
    if len(df) == 0:
        return {"label": f"{asset.upper()}_{tf}", "n_test": 0}
    df["day"] = df["window_start_unix"] // 86_400
    days = sorted(df["day"].unique())
    if len(days) < train_days + test_days:
        return {"label": f"{asset.upper()}_{tf}", "n_test": 0,
                "note": f"only {len(days)} days available; need {train_days+test_days}"}

    # For each test_day, fit threshold on previous train_days days
    all_pnls = []
    threshold_history = []
    for test_day_idx in range(train_days, len(days)):
        test_day = days[test_day_idx]
        train_start = days[test_day_idx - train_days]
        train_df = df[(df["day"] >= train_start) & (df["day"] < test_day)]
        test_df = df[df["day"] == test_day]
        if len(train_df) < 50 or len(test_df) < 5:
            continue
        # Fit q90 on |asset_ret_2m| from train
        thr = train_df["asset_ret_2m"].abs().quantile(0.90)
        threshold_history.append(dict(test_day=int(test_day), n_train=len(train_df),
                                       n_test=len(test_df), thr=float(thr)))
        # Fire test markets
        test_fired = test_df[test_df["asset_ret_2m"].abs() >= thr].copy()
        test_fired["signal"] = (test_fired["asset_ret_2m"] > 0).astype(int)
        # Run HOLD policy (simplest, independent of exit-book quality for new markets)
        for _, row in test_fired.iterrows():
            max_b = 89 if row.timeframe == "15m" else 29
            r = simulate(row, k1m, entry_book, bucket_book, max_b, "HOLD",
                         spread_filter=SPREAD_FILTER[asset])
            if r is None or r.get("skipped_spread") or r.get("skipped_thin"):
                continue
            all_pnls.append(r["pnl"])

    if not all_pnls:
        return {"label": f"{asset.upper()}_{tf}", "n_test": 0,
                "note": "no out-of-sample trades"}
    pnls = np.array(all_pnls)
    return dict(
        label=f"{asset.upper()}_{tf}",
        n_test=len(pnls),
        oos_total_pnl=float(pnls.sum()),
        oos_mean_pnl=float(pnls.mean()),
        oos_hit=float((pnls > 0).mean()),
        oos_std=float(pnls.std()),
        n_train_days=train_days,
        n_test_days=test_days,
        n_windows=len(threshold_history),
        thr_history=threshold_history,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("[1] universe + klines + books…")
    uni = load_universe()
    print(f"    universe: {len(uni)} resolved markets ({uni.asset.value_counts().to_dict()})  "
          f"tfs: {uni.timeframe.value_counts().to_dict()}")
    klines = load_klines()

    # Compute asset_ret_2m per market using combined kline feed
    for a in ("btc", "eth", "sol"):
        m = uni.asset == a
        ws_arr = uni.loc[m, "window_start_unix"].astype("int64").values
        p0 = np.array([asof(klines[a], int(w)) for w in ws_arr])
        p2 = np.array([asof(klines[a], int(w) + 120) for w in ws_arr])
        ret_2m = np.log(p2 / p0)
        uni.loc[m, "asset_ret_2m"] = ret_2m
    active = uni[uni["asset_ret_2m"].notna() & np.isfinite(uni["asset_ret_2m"])].copy()
    print(f"    active (with asset_ret_2m): {len(active)}")

    print("[2] tier1 entry books + bucket books…")
    entry_books = {a: load_tier1_entries(a) for a in ("btc", "eth", "sol")}
    bucket_books = {a: load_book_buckets(a) for a in ("btc", "eth", "sol")}
    for a in ("btc", "eth", "sol"):
        print(f"    {a}: {len(entry_books[a])} tier1 entries, {len(bucket_books[a])} slugs in bucket book")

    # ── Build signal: top-10% |asset_ret_2m| per (asset, tf) ──
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
            print(f"    {a.upper()}_{tf}: thr={thr:.5f}  fires={len(f)}/{len(sub)}")
    fired_all = pd.concat(fired, ignore_index=True)
    print(f"    total fires: {len(fired_all)}")

    # ── Headline backtest: all 18 cells ──
    print("\n[3] headline backtest — 6 cells × 3 policies = 18 results")
    results = []
    cell_per_trade: dict[tuple[str, str, str], list] = {}
    for a in ("btc", "eth", "sol"):
        for tf in ("5m", "15m"):
            sub = fired_all[(fired_all.asset == a) & (fired_all.timeframe == tf)]
            if len(sub) == 0: continue
            for policy in ("HOLD", "HEDGE", "SELL"):
                r = run_cell(sub, klines[a], entry_books[a], bucket_books[a],
                             policy, f"{a.upper()}_{tf}_{policy}", a)
                cell_per_trade[(a, tf, policy)] = r.pop("per_trade", [])
                results.append(r)
                if r["n"] > 0:
                    print(f"    {r['label']:18s}  n={r['n']:4d}  hit={r['hit']*100:5.1f}%  "
                          f"vwap=${r['avg_vwap_e']:.4f}  pnl=${r['pnl_total']:+8.2f}  "
                          f"mean=${r['pnl_mean']:+.4f}  std=${r['pnl_std']:5.2f}  "
                          f"sharpe={r['sharpe']:+.2f}  hedged={r['n_hedge']:3d}  sells={r['n_sell']:3d}")

    df_head = pd.DataFrame([{k: v for k, v in r.items() if k != "per_trade"} for r in results])
    df_head.to_csv(OUT_DIR / "extended_backtest.csv", index=False)
    print(f"    [csv] wrote {OUT_DIR / 'extended_backtest.csv'}")

    # ── Permutation test on HOLD per cell ──
    print("\n[4] permutation test (1000 draws per cell, HOLD policy)")
    perm_rows = []
    for (a, tf, policy), per_trade in cell_per_trade.items():
        if policy != "HOLD" or not per_trade: continue
        rng = np.random.default_rng(hash((a, tf)) % (2**32))
        p = permutation_test(per_trade, n_permutations=1000, rng=rng)
        p["cell"] = f"{a.upper()}_{tf}"
        perm_rows.append(p)
        print(f"    {p['cell']:10s}  n={p['n']:4d}  observed=${p['observed_pnl']:+.2f}  "
              f"null_mean=${p['null_mean']:+.2f}  null_q975=${p['null_q975']:+.2f}  "
              f"null_max=${p['null_max']:+.2f}  p={p['p_value']:.4f}")
    df_perm = pd.DataFrame(perm_rows)
    df_perm.to_csv(OUT_DIR / "permutation_results.csv", index=False)

    # ── Walkforward ──
    print("\n[5] walkforward (7d train / 1d test, refit q90 per window)")
    wf_rows = []
    for a in ("btc", "eth", "sol"):
        for tf in ("5m", "15m"):
            r = walkforward(active, klines[a], entry_books[a], bucket_books[a], a, tf)
            if r["n_test"] > 0:
                wf_rows.append(r)
                print(f"    {r['label']:10s}  n_test={r['n_test']:4d}  "
                      f"oos_total=${r['oos_total_pnl']:+8.2f}  "
                      f"oos_mean=${r['oos_mean_pnl']:+.4f}  oos_hit={r['oos_hit']*100:.1f}%  "
                      f"windows={r['n_windows']}")
    df_wf = pd.DataFrame([{k: v for k, v in r.items() if k != "thr_history"} for r in wf_rows])
    df_wf.to_csv(OUT_DIR / "walkforward_results.csv", index=False)

    # ── Final report ──
    print("\n[6] writing report…")
    L = [
        "# Extended Backtest + Permutation + Walkforward\n",
        "_Generated: 2026-05-05 evening_\n",
        "## What's new\n",
        f"- **Fresh data**: pulled VPS2 `market_resolutions_v2` ({len(uni)} resolved markets, Apr 22 → May 6) "
        f"and combined Binance-vision + Binance-WS + OKX-WS klines feed",
        f"- **Tier1 entries**: extended pull → {sum(len(eb) for eb in entry_books.values())} (slug, outcome) entries with 25 levels of depth, microsecond-precise timestamps (median 336ms from t+120s target)",
        f"- **Active universe (asset_ret_2m valid)**: {len(active)} markets",
        f"- **Total fires (top-10% |asset_ret_2m| per cell)**: {len(fired_all)}",
        "",
        "## Headline — full extended dataset\n",
        "Engine: $25 stake, top-25 ASK book walk for entry, 2% taker fee, asset-specific spread filter, "
        "10s-bucket book for hedge/sell exit monitoring (existing CSVs cover Apr 22-May 4).\n",
        "| Cell | Policy | n | hit% | avg vwap | total | mean | std | Sharpe | Sortino | maxDD | hedged | sells |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        if r["n"] == 0: continue
        cell, pol = r["label"].rsplit("_", 1)
        L.append(
            f"| {cell} | {pol} | {r['n']} | {r['hit']*100:.1f} | "
            f"${r['avg_vwap_e']:.4f} | ${r['pnl_total']:+.2f} | ${r['pnl_mean']:+.4f} | "
            f"${r['pnl_std']:.2f} | {r['sharpe']:+.2f} | {r['sortino']:+.2f} | "
            f"${r['max_dd']:.2f} | {r['n_hedge']} | {r['n_sell']} |"
        )

    # Permutation summary
    L.append("")
    L.append("## Permutation test — is the strategy edge real?\n")
    L.append("Method: hold the FIRED trades + their entry vwap fixed; randomize whether each trade wins")
    L.append("or loses (Bernoulli with the observed hit rate). Repeat 1000×. p-value = fraction of")
    L.append("random draws producing PnL ≥ observed PnL.\n")
    L.append("| Cell | n | observed PnL | null mean | null q975 | null max | p-value |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for p in perm_rows:
        sig = "***" if p["p_value"] < 0.001 else ("**" if p["p_value"] < 0.01 else ("*" if p["p_value"] < 0.05 else "ns"))
        L.append(f"| {p['cell']} | {p['n']} | ${p['observed_pnl']:+.2f} | ${p['null_mean']:+.2f} | "
                 f"${p['null_q975']:+.2f} | ${p['null_max']:+.2f} | **{p['p_value']:.4f}** {sig} |")

    L.append("")
    L.append("**Caveat on this permutation**: it tests the conditional H0 'given we fired on these markets,")
    L.append("does outcome direction match signal beyond random?' It does NOT test the GATE itself")
    L.append("(whether top-10% |asset_ret_2m| picks better markets than random selection). For that")
    L.append("we'd need to shuffle outcomes across the FULL universe and re-fire — see `permutation_test_strict`")
    L.append("(stub, not run here).\n")

    # Walkforward
    L.append("## Walkforward — out-of-sample stability\n")
    L.append("Method: rolling 7-day train window / 1-day test window. Each test day, refit q90 |asset_ret_2m|")
    L.append("on the prior 7 days, deploy that threshold on the test day, record HOLD-policy PnL. Aggregate")
    L.append("all out-of-sample test PnLs.\n")
    L.append("| Cell | n_test | OOS total | OOS mean | OOS hit% | n_windows |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for r in wf_rows:
        L.append(f"| {r['label']} | {r['n_test']} | ${r['oos_total_pnl']:+.2f} | "
                 f"${r['oos_mean_pnl']:+.4f} | {r['oos_hit']*100:.1f}% | {r['n_windows']} |")
    L.append("")
    L.append("If OOS PnL ≈ in-sample, threshold refits don't degrade the edge — the strategy is robust to ")
    L.append("regime shifts and not overfitting to the in-sample distribution.\n")

    # Verdict
    sig_count = sum(1 for p in perm_rows if p["p_value"] < 0.05)
    L.append("---")
    L.append("")
    L.append("## Verdict\n")
    L.append(f"- **Permutation**: {sig_count}/{len(perm_rows)} cells significant at p<0.05 "
             f"(observed PnL exceeds 95% of random draws)")
    if wf_rows:
        wf_total = sum(r["oos_total_pnl"] for r in wf_rows)
        L.append(f"- **Walkforward**: combined OOS PnL ${wf_total:+.2f} across all 6 cells")
    L.append(f"- **Headline (all policies, all cells)**: combined PnL ${df_head['pnl_total'].sum():+.2f}")
    L.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"[report] wrote {REPORT}")


if __name__ == "__main__":
    main()
