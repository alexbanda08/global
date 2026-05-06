"""Strict permutation tests — corrects the degenerate test in extended_backtest.

The earlier permutation test held the per-trade win/loss MAGNITUDES fixed and
shuffled WHICH trades won. By construction E[null] = observed → p≈0.5 (degenerate).

This script runs two CORRECT permutations:

A) DIRECTION_PERM — keep gate firings, randomize signal sign per trade.
   Tests H0: the sign of asset_ret_2m is uninformative; we'd do equally
   well betting random direction.

B) GATE_PERM — shuffle WHICH markets fire (random 10% of universe per
   asset/tf), keep the sign logic on whatever asset_ret_2m those markets
   have. Tests H0: the top-10% gate doesn't select markets with above-
   random hit rate.

For both, we use the production-faithful tier1 entry book and HOLD policy
(no exits — simplest baseline).

Outputs:
  strategy_lab/results/meta_classifier/permutation_strict_results.csv
  appended to strategy_lab/reports/EXTENDED_BACKTEST_ROBUSTNESS.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))

from book_walk import book_walk_fill              # noqa: E402

LEVELS_T1 = 25
NOTIONAL_USD = 25.0
FEE_RATE = 0.02
SPREAD_FILTER = {"btc": 0.02, "eth": 0.02, "sol": 0.025}

REFRESH_NEW = ROOT / "data" / "v4" / "refresh_2026_05_06"
TIER1_DIR = REFRESH_NEW / "tier1_entries"

OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "permutation_strict_results.csv"
REPORT  = ROOT / "strategy_lab" / "reports"  / "EXTENDED_BACKTEST_ROBUSTNESS.md"

ASSET_BINANCE = {"btc": "BINANCE_SPOT_BTC_USDT", "eth": "BINANCE_SPOT_ETH_USDT", "sol": "BINANCE_SPOT_SOL_USDT"}
ASSET_OKX = {"btc": "OKX_SPOT_BTC_USDT", "eth": "OKX_SPOT_ETH_USDT", "sol": "OKX_SPOT_SOL_USDT"}


def load_universe() -> pd.DataFrame:
    df = pd.read_csv(REFRESH_NEW / "market_resolutions_full.csv")
    df = df.dropna(subset=["window_start_unix", "outcome_up"]).copy()
    df["asset"] = df["slug"].str.extract(r'^(btc|eth|sol)-updown-')[0]
    df = df.dropna(subset=["asset"]).copy()
    df["window_start_unix"] = df["window_start_unix"].astype("int64")
    df["outcome_up"] = df["outcome_up"].astype(int)
    df["timeframe"] = df["timeframe"].str.lower()
    return df


def load_klines() -> dict[str, pd.DataFrame]:
    df = pd.read_csv(REFRESH_NEW / "klines_full.csv")
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for asset in ("btc", "eth", "sol"):
        bin_sub = df[df.symbol_id == ASSET_BINANCE[asset]][["ts_s", "price_close"]].copy()
        okx_sub = df[df.symbol_id == ASSET_OKX[asset]][["ts_s", "price_close"]].copy()
        bin_sub["src"] = "binance"; okx_sub["src"] = "okx"
        combined = pd.concat([bin_sub, okx_sub], ignore_index=True)
        combined = combined.sort_values(["ts_s", "src"]).drop_duplicates("ts_s", keep="first")
        out[asset] = combined.sort_values("ts_s").reset_index(drop=True)[["ts_s", "price_close"]]
    return out


def asof(k1m: pd.DataFrame, ts: int) -> float:
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


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


def simulate_hold_pnl(slug: str, sig: int, outcome_up: int,
                     entry_book: dict, spread_filter: float | None = None) -> float | None:
    """HOLD-policy single-trade PnL using tier1 entry book. None if can't fill."""
    held = "Up" if sig == 1 else "Down"
    if (slug, held) not in entry_book:
        return None
    ask_p, ask_s, bid_p, bid_s = entry_book[(slug, held)]
    if spread_filter is not None and len(ask_p) and len(bid_p):
        if np.isfinite(ask_p[0]) and np.isfinite(bid_p[0]) and (ask_p[0] - bid_p[0]) > spread_filter:
            return None
    vwap_e, shares_e, usd_e, _, under_e = book_walk_fill(ask_p, ask_s, NOTIONAL_USD)
    if shares_e <= 0:
        return None
    if under_e and usd_e < NOTIONAL_USD * 0.5:
        return None
    won = (sig == int(outcome_up))
    if won:
        profit = shares_e * 1.0 - usd_e
        fee = profit * FEE_RATE if profit > 0 else 0.0
        return profit - fee
    return -usd_e


def main():
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    print("[1] loading universe + klines + tier1 books…")
    uni = load_universe()
    klines = load_klines()
    entry_books = {a: load_tier1_entries(a) for a in ("btc", "eth", "sol")}

    # asset_ret_2m
    for a in ("btc", "eth", "sol"):
        m = uni.asset == a
        ws_arr = uni.loc[m, "window_start_unix"].astype("int64").values
        p0 = np.array([asof(klines[a], int(w)) for w in ws_arr])
        p2 = np.array([asof(klines[a], int(w) + 120) for w in ws_arr])
        uni.loc[m, "asset_ret_2m"] = np.log(p2 / p0)
    active = uni[uni["asset_ret_2m"].notna() & np.isfinite(uni["asset_ret_2m"])].copy()

    rows = []
    n_perm = 1000
    rng_master = np.random.default_rng(42)

    print(f"\n[2] running permutations (n={n_perm} per cell)…")
    for a in ("btc", "eth", "sol"):
        for tf in ("5m", "15m"):
            sub = active[(active.asset == a) & (active.timeframe == tf)].copy()
            if len(sub) < 50:
                continue

            # OBSERVED: top-10% gate, sign(asset_ret_2m) direction
            thr = sub["asset_ret_2m"].abs().quantile(0.90)
            fired = sub[sub["asset_ret_2m"].abs() >= thr].copy()
            obs_pnls = []
            for _, r in fired.iterrows():
                sig = 1 if r.asset_ret_2m > 0 else 0
                pnl = simulate_hold_pnl(r.slug, sig, int(r.outcome_up),
                                        entry_books[a], SPREAD_FILTER[a])
                if pnl is not None:
                    obs_pnls.append(pnl)
            obs_total = float(np.sum(obs_pnls))
            obs_n = len(obs_pnls)

            # ============================================================
            # A) DIRECTION_PERM — keep fires, randomize sig per trade
            # ============================================================
            # Pre-cache pnl_for_each_signal_choice to avoid re-fetching books
            # For each fired market, both UP and DOWN bets have known pnl.
            up_pnls, dn_pnls = [], []
            for _, r in fired.iterrows():
                pnl_up = simulate_hold_pnl(r.slug, 1, int(r.outcome_up),
                                           entry_books[a], SPREAD_FILTER[a])
                pnl_dn = simulate_hold_pnl(r.slug, 0, int(r.outcome_up),
                                           entry_books[a], SPREAD_FILTER[a])
                if pnl_up is not None and pnl_dn is not None:
                    up_pnls.append(pnl_up); dn_pnls.append(pnl_dn)
            up_pnls = np.array(up_pnls); dn_pnls = np.array(dn_pnls)
            n_dir = len(up_pnls)
            null_dir = np.empty(n_perm)
            seed_dir = int.from_bytes(rng_master.bytes(4), "big")
            rng_dir = np.random.default_rng(seed_dir)
            for i in range(n_perm):
                signs = rng_dir.integers(0, 2, n_dir)  # 0 = DOWN, 1 = UP
                null_dir[i] = (signs * up_pnls + (1 - signs) * dn_pnls).sum()
            p_dir = float((null_dir >= obs_total).mean())

            # ============================================================
            # B) GATE_PERM — shuffle which markets fire
            # ============================================================
            # Sample random 10% of the asset/tf universe; for each, use
            # sign(asset_ret_2m) as direction. Compare PnL distribution.
            n_fire_target = len(fired)
            null_gate = np.empty(n_perm)
            seed_gate = int.from_bytes(rng_master.bytes(4), "big")
            rng_gate = np.random.default_rng(seed_gate)
            sub_idx = sub.index.values
            for i in range(n_perm):
                pick = rng_gate.choice(sub_idx, size=n_fire_target, replace=False)
                rs = sub.loc[pick]
                pnls_i = []
                for _, r in rs.iterrows():
                    if not np.isfinite(r.asset_ret_2m) or r.asset_ret_2m == 0:
                        continue
                    sig = 1 if r.asset_ret_2m > 0 else 0
                    pnl = simulate_hold_pnl(r.slug, sig, int(r.outcome_up),
                                            entry_books[a], SPREAD_FILTER[a])
                    if pnl is not None:
                        pnls_i.append(pnl)
                null_gate[i] = float(np.sum(pnls_i))
            p_gate = float((null_gate >= obs_total).mean())

            row = dict(
                cell=f"{a.upper()}_{tf}",
                n_observed=obs_n,
                observed_pnl=obs_total,
                # Direction perm
                dir_perm_n=n_dir,
                dir_perm_null_mean=float(null_dir.mean()),
                dir_perm_null_std=float(null_dir.std()),
                dir_perm_null_q025=float(np.quantile(null_dir, 0.025)),
                dir_perm_null_q975=float(np.quantile(null_dir, 0.975)),
                dir_perm_null_max=float(null_dir.max()),
                dir_perm_p=p_dir,
                # Gate perm
                gate_perm_null_mean=float(null_gate.mean()),
                gate_perm_null_std=float(null_gate.std()),
                gate_perm_null_q025=float(np.quantile(null_gate, 0.025)),
                gate_perm_null_q975=float(np.quantile(null_gate, 0.975)),
                gate_perm_null_max=float(null_gate.max()),
                gate_perm_p=p_gate,
            )
            rows.append(row)
            print(f"  {row['cell']:10s}  n={obs_n:4d}  obs=${obs_total:+.2f}  "
                  f"DIR p={p_dir:.4f} (null_mean=${row['dir_perm_null_mean']:+.2f})  "
                  f"GATE p={p_gate:.4f} (null_mean=${row['gate_perm_null_mean']:+.2f})")

    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False)
    print(f"\n[csv] wrote {OUT_CSV}")

    # Append to existing report
    L = ["\n", "---", "",
         "## Strict Permutation Tests — DIRECTION + GATE\n",
         "_(Added after the degenerate Bernoulli permutation test in the original report.)_\n",
         "**A) DIRECTION_PERM**: keep the FIRED trade set fixed (the same 1542 markets at top-10% \\|asset_ret_2m\\|). For each, randomize whether we bet UP or DOWN. Repeat 1000×. PnL distribution under random direction is the null. p-value = P(null ≥ observed).\n",
         "Tests H0: sign(asset_ret_2m) is uninformative — we'd do equally well betting random direction.\n",
         "**B) GATE_PERM**: shuffle which markets get fired — pick a random 10% of the asset/tf universe per draw, use sign(asset_ret_2m) as direction. PnL distribution under random gate is the null.\n",
         "Tests H0: the top-10% \\|asset_ret_2m\\| gate doesn't select better markets than random selection.\n",
         "| Cell | n | observed PnL | DIR null_mean | DIR null_q975 | DIR p | GATE null_mean | GATE null_q975 | GATE p |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    for r in rows:
        sig_d = "***" if r["dir_perm_p"] < 0.001 else ("**" if r["dir_perm_p"] < 0.01 else ("*" if r["dir_perm_p"] < 0.05 else "ns"))
        sig_g = "***" if r["gate_perm_p"] < 0.001 else ("**" if r["gate_perm_p"] < 0.01 else ("*" if r["gate_perm_p"] < 0.05 else "ns"))
        L.append(f"| {r['cell']} | {r['n_observed']} | ${r['observed_pnl']:+.2f} | "
                 f"${r['dir_perm_null_mean']:+.2f} | ${r['dir_perm_null_q975']:+.2f} | **{r['dir_perm_p']:.4f}** {sig_d} | "
                 f"${r['gate_perm_null_mean']:+.2f} | ${r['gate_perm_null_q975']:+.2f} | **{r['gate_perm_p']:.4f}** {sig_g} |")

    L.append("")
    sig_dir = sum(1 for r in rows if r["dir_perm_p"] < 0.05)
    sig_gate = sum(1 for r in rows if r["gate_perm_p"] < 0.05)
    L.append(f"**Summary**: {sig_dir}/{len(rows)} cells significant for DIRECTION (sign matters); "
             f"{sig_gate}/{len(rows)} cells significant for GATE (top-10% selects better markets).")
    L.append("")

    with open(REPORT, "a", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"[report] appended to {REPORT}")


if __name__ == "__main__":
    main()
