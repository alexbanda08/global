"""
SUM-ARB PRE-REGISTERED BACKTEST  —  2026-06-12
===============================================

Strategy: taker pair-arb on Polymarket crypto up/down markets.
- At fire offset (slot_start + {+5,+30,+60}s), walk BOTH Up ask + Down ask for $70/leg.
- If sum_ask < threshold, enter; hold to resolution.
- PnL = shares_winner * (1 - fee) - cost_up - cost_dn
  winner fee = 0.07 * p_win * (1 - p_win), loser = -cost, no fee.

Pre-registered universe: ALL btc/eth/sol 5m+15m slugs Apr22-Jun11 with L25 coverage.
XRP excluded (no canonical L25).

Decision rule (pre-registered):
  PURSUE if any cell has OOS CI95 > 0 AND ex-top2 stays positive AND n_OOS >= 100.
  Otherwise PARK.

IS split: Apr22-May20
OOS split: May21-Jun11

Differences from dead prior test (SCALP_NEW_EDGE_HUNT_2026_06_09.md Trial Z):
  Prior used BBO top-of-book (load_orderbook_bbo), Mar30-Apr21 window, found <0.04%
  of snapshots had sum_ask<1 and ALL at dust/zero executable size.
  THIS test:
    - Uses full L25 25-level book, Apr22-Jun11 window (production data)
    - Walks $70/leg notional (realistic fill, ce25 equivalent)
    - Gates on sum_ask < {1.00, 0.99, 0.98, 0.97, 0.95}
    - Tests 3 entry offsets: +5s, +30s, +60s after slot_start
    - Direct PyArrow streaming (avoids load.py's types_mapper issue)
"""
from __future__ import annotations

import gc
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

warnings.filterwarnings("ignore")

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions  # noqa
from book_walk import book_walk_fill  # noqa

# ── constants ──────────────────────────────────────────────────────────────────
NOTIONAL_PER_LEG = 70.0
OFFSETS = [5, 30, 60]           # seconds after slot_start
THRESHOLDS = [1.00, 0.99, 0.98, 0.97, 0.95]
IS_CUTOFF_US = int(pd.Timestamp("2026-05-21").timestamp() * 1_000_000)
COINS = ["BTC", "ETH", "SOL"]
TFS = ["5m", "15m"]
LEVELS = 25
L25_DIR = ROOT / "data" / "v4" / "canonical" / "orderbook_l25"
OUT_DIR = ROOT / "strategy_lab" / "directional" / "_results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BATCH_SIZE = 50_000
ASK_P_COLS = [f"ask_price_{i}" for i in range(LEVELS)]
ASK_S_COLS = [f"ask_size_{i}"  for i in range(LEVELS)]
COLS_NEEDED = ["timestamp_us", "slug", "outcome"] + ASK_P_COLS + ASK_S_COLS


# ── helpers ────────────────────────────────────────────────────────────────────

def poly_fee(p: float) -> float:
    return 0.07 * p * (1.0 - p)


def asof_idx(ts_arr: np.ndarray, target_us: int) -> int:
    idx = int(np.searchsorted(ts_arr, target_us, side="right")) - 1
    return idx


def walk_book_row(ap: np.ndarray, asz: np.ndarray) -> tuple[float, float, float, bool]:
    """Walk ask book row (LEVELS,) for NOTIONAL_PER_LEG. Returns (vwap, shares, cost, underfilled)."""
    mask = np.isfinite(ap) & np.isfinite(asz) & (asz > 0) & (ap > 0) & (ap < 1)
    p_clean = ap[mask].tolist()
    s_clean = asz[mask].tolist()
    if not p_clean:
        return 0.0, 0.0, 0.0, True
    vwap, shares, cost, _, under = book_walk_fill(p_clean, s_clean, NOTIONAL_PER_LEG)
    return vwap, shares, cost, under


# ── streaming reader ───────────────────────────────────────────────────────────

def stream_coin_to_slug_dict(coin: str, slugs_set: set[str]) -> dict[str, dict[str, tuple]]:
    """
    Stream L25 parquet for coin, return:
      {slug: {'Up': (ts_us_sorted, ap_array[N,25], asz_array[N,25]),
              'Down': ...}}
    Only keeps slugs in slugs_set.
    """
    path = L25_DIR / f"{coin.lower()}.parquet"
    slugs_arr = pa.array(sorted(slugs_set))

    # Accumulate rows per (slug, outcome)
    accum: dict[tuple[str, str], list[pd.DataFrame]] = {}

    pf = pq.ParquetFile(str(path))
    batch_num = 0
    for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=COLS_NEEDED):
        batch_num += 1
        if batch.num_rows == 0:
            continue
        mask = pc.is_in(batch.column("slug"), value_set=slugs_arr)
        if pc.sum(mask).as_py() == 0:
            continue
        batch = batch.filter(mask)
        if batch.num_rows == 0:
            continue
        df = batch.to_pandas()
        del batch
        for (slug, oc), grp in df.groupby(["slug", "outcome"], sort=False):
            key = (slug, oc)
            if key not in accum:
                accum[key] = []
            accum[key].append(grp)
        del df
        if batch_num % 100 == 0:
            print(f"  [{coin}] batch {batch_num}...", flush=True)
        gc.collect()

    print(f"  [{coin}] assembled {len(accum)} (slug,outcome) pairs from {batch_num} batches")

    # Convert to (ts_arr, ap_arr, asz_arr) per (slug, outcome)
    result: dict[str, dict[str, tuple]] = {}
    for (slug, oc), frames in accum.items():
        df_all = pd.concat(frames, ignore_index=True, copy=False)
        df_all = df_all.sort_values("timestamp_us")
        ts_arr = df_all["timestamp_us"].values.astype("int64")
        ap_arr = df_all[ASK_P_COLS].to_numpy(dtype=np.float32)
        asz_arr = df_all[ASK_S_COLS].to_numpy(dtype=np.float32)
        if slug not in result:
            result[slug] = {}
        result[slug][oc] = (ts_arr, ap_arr, asz_arr)
        del df_all
    del accum
    gc.collect()
    return result


# ── per-coin backtest ──────────────────────────────────────────────────────────

def run_coin(coin: str) -> pd.DataFrame:
    print(f"\n{'='*60}")
    print(f"[{coin}] loading resolutions...")
    rez = load_resolutions(assets=[coin], timeframes=TFS)
    apr22_us = int(pd.Timestamp("2026-04-22").timestamp() * 1_000_000)
    rez = rez[rez["slot_start_us"] >= apr22_us].copy()

    # De-dup: one row per slug
    slug_info = rez.drop_duplicates("slug").set_index("slug")
    slug_outcome = slug_info["outcome"].to_dict()
    slug_slot_us = slug_info["slot_start_us"].to_dict()
    slugs_set = set(slug_outcome.keys())
    print(f"[{coin}] {len(slugs_set)} unique slugs")

    print(f"[{coin}] streaming L25 books...")
    slug_books = stream_coin_to_slug_dict(coin, slugs_set)

    print(f"[{coin}] evaluating {len(slug_books)} slugs with L25 coverage...")

    rows = []
    n_skip_no_book = 0
    n_skip_no_side = 0
    n_skip_no_snap_up = 0
    n_skip_no_snap_dn = 0
    n_skip_empty_book = 0

    for slug in slugs_set:
        if slug not in slug_books:
            n_skip_no_book += 1
            continue
        book = slug_books[slug]
        if "Up" not in book or "Down" not in book:
            n_skip_no_side += 1
            continue

        market_outcome = slug_outcome[slug]
        slot_us = slug_slot_us[slug]
        tf = "5m" if "-5m-" in slug else "15m"

        up_ts, up_ap, up_asz = book["Up"]
        dn_ts, dn_ap, dn_asz = book["Down"]

        for offset_s in OFFSETS:
            fire_us = slot_us + offset_s * 1_000_000

            up_i = asof_idx(up_ts, fire_us)
            dn_i = asof_idx(dn_ts, fire_us)

            if up_i < 0:
                n_skip_no_snap_up += 1
                continue
            if dn_i < 0:
                n_skip_no_snap_dn += 1
                continue

            up_vwap, up_shares, up_cost, up_under = walk_book_row(
                up_ap[up_i].astype(np.float64),
                up_asz[up_i].astype(np.float64)
            )
            dn_vwap, dn_shares, dn_cost, dn_under = walk_book_row(
                dn_ap[dn_i].astype(np.float64),
                dn_asz[dn_i].astype(np.float64)
            )

            if up_vwap <= 0 or dn_vwap <= 0:
                n_skip_empty_book += 1
                continue

            sum_ask = up_vwap + dn_vwap

            # PnL: winner leg redeems at $1, loser forfeits cost
            if market_outcome == "Up":
                win_vwap = up_vwap
                win_shares = up_shares
                win_cost = up_cost
                los_cost = dn_cost
            else:
                win_vwap = dn_vwap
                win_shares = dn_shares
                win_cost = dn_cost
                los_cost = up_cost

            fee = poly_fee(win_vwap)
            pnl = win_shares * (1.0 - fee) - win_cost - los_cost

            rows.append({
                "slug": slug,
                "coin": coin,
                "tf": tf,
                "slot_start_us": slot_us,
                "offset_s": offset_s,
                "sum_ask": float(sum_ask),
                "vwap_up": float(up_vwap),
                "vwap_dn": float(dn_vwap),
                "outcome": market_outcome,
                "win_vwap": float(win_vwap),
                "win_shares": float(win_shares),
                "up_underfilled": up_under,
                "dn_underfilled": dn_under,
                "pnl": float(pnl),
            })

    print(f"[{coin}] evaluable rows: {len(rows)}")
    print(f"[{coin}] skips: no_book={n_skip_no_book}, no_side={n_skip_no_side}, "
          f"no_snap_up={n_skip_no_snap_up}, no_snap_dn={n_skip_no_snap_dn}, "
          f"empty_book={n_skip_empty_book}")
    return pd.DataFrame(rows)


# ── analysis helpers ───────────────────────────────────────────────────────────

def bootstrap_ci(vals: np.ndarray, n_boot: int = 2000, ci: float = 0.95) -> tuple[float, float]:
    if len(vals) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(42)
    means = rng.choice(vals, size=(n_boot, len(vals)), replace=True).mean(axis=1)
    alpha = (1 - ci) / 2
    return float(np.quantile(means, alpha)), float(np.quantile(means, 1 - alpha))


def ex_top2(vals: np.ndarray) -> float:
    if len(vals) <= 2:
        return float("nan")
    return float(np.sort(vals)[::-1][2:].mean())


def compute_cell(df_cell: pd.DataFrame) -> dict:
    vals = df_cell["pnl"].values if len(df_cell) > 0 else np.array([])
    lo, hi = bootstrap_ci(vals)
    return {
        "n": len(vals),
        "mean_pnl": float(vals.mean()) if len(vals) else float("nan"),
        "total_pnl": float(vals.sum()) if len(vals) else float("nan"),
        "wr": float((vals > 0).mean()) if len(vals) else float("nan"),
        "ci95_lo": lo,
        "ci95_hi": hi,
        "ex_top2": ex_top2(vals),
        "median_sum_ask": float(df_cell["sum_ask"].median()) if len(vals) else float("nan"),
    }


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    all_dfs = []
    for coin in COINS:
        df = run_coin(coin)
        if not df.empty:
            all_dfs.append(df)
        gc.collect()

    if not all_dfs:
        print("ERROR: no data")
        return None, None

    full = pd.concat(all_dfs, ignore_index=True)
    full["period"] = np.where(full["slot_start_us"] < IS_CUTOFF_US, "IS", "OOS")

    # Save per-slug artifact
    out_parquet = OUT_DIR / "sumarb_prereg.parquet"
    full.to_parquet(out_parquet, index=False)
    print(f"\nSaved per-slug artifact: {out_parquet} ({len(full)} rows)")

    # ── cell computation ───────────────────────────────────────────────────────
    results = []
    for offset_s in OFFSETS:
        df_off = full[full["offset_s"] == offset_s]
        n_univ_is  = df_off[df_off["period"] == "IS"]["slug"].nunique()
        n_univ_oos = df_off[df_off["period"] == "OOS"]["slug"].nunique()
        n_univ_all = df_off["slug"].nunique()

        for thr_label, df_gated in [("ungated", df_off)] + [
            (thr, df_off[df_off["sum_ask"] < thr]) for thr in THRESHOLDS
        ]:
            for period, n_univ in [("IS", n_univ_is), ("OOS", n_univ_oos), ("ALL", n_univ_all)]:
                sub = df_gated if period == "ALL" else df_gated[df_gated["period"] == period]
                cell = compute_cell(sub)
                cell["offset_s"] = offset_s
                cell["threshold"] = thr_label
                cell["period"] = period
                cell["n_universe"] = n_univ
                cell["pct_universe"] = cell["n"] / n_univ if n_univ > 0 else float("nan")
                results.append(cell)

    res_df = pd.DataFrame(results)
    out_csv = OUT_DIR / "sumarb_prereg_cells.csv"
    res_df.to_csv(out_csv, index=False)
    print(f"Saved cell results: {out_csv}")

    # ── print tables ───────────────────────────────────────────────────────────
    print("\n" + "="*90)
    print("SUM-ARB PRE-REGISTERED BACKTEST — OOS RESULTS (May21–Jun11)")
    print("="*90)
    oos_df = res_df[res_df["period"] == "OOS"].copy()
    print(f"\n{'offset':>6} {'threshold':>10} {'n_OOS':>7} {'%univ':>6} "
          f"{'$/slug':>8} {'CI_lo':>7} {'CI_hi':>7} {'ex-top2':>8} {'wr':>5}")
    print("-"*80)
    for _, row in oos_df.iterrows():
        thr_str = f"{row['threshold']:.2f}" if isinstance(row['threshold'], float) else str(row['threshold'])
        n = int(row['n']) if not np.isnan(row['n']) else 0
        pct = f"{row['pct_universe']:.1%}" if not np.isnan(row['pct_universe']) else "nan"
        mean = f"{row['mean_pnl']:+.4f}" if not np.isnan(row['mean_pnl']) else "nan"
        clo = f"{row['ci95_lo']:+.4f}" if not np.isnan(row['ci95_lo']) else "nan"
        chi = f"{row['ci95_hi']:+.4f}" if not np.isnan(row['ci95_hi']) else "nan"
        et2 = f"{row['ex_top2']:+.4f}" if not np.isnan(row['ex_top2']) else "nan"
        wr = f"{row['wr']:.2f}" if not np.isnan(row['wr']) else "nan"
        print(f"{row['offset_s']:>6} {thr_str:>10} {n:>7} {pct:>6} "
              f"{mean:>8} {clo:>7} {chi:>7} {et2:>8} {wr:>5}")

    print("\n" + "="*90)
    print("IS RESULTS (Apr22–May20)")
    print("="*90)
    is_df = res_df[res_df["period"] == "IS"].copy()
    print(f"\n{'offset':>6} {'threshold':>10} {'n_IS':>7} {'%univ':>6} "
          f"{'$/slug':>8} {'CI_lo':>7} {'CI_hi':>7} {'ex-top2':>8} {'wr':>5}")
    print("-"*80)
    for _, row in is_df.iterrows():
        thr_str = f"{row['threshold']:.2f}" if isinstance(row['threshold'], float) else str(row['threshold'])
        n = int(row['n']) if not np.isnan(row['n']) else 0
        pct = f"{row['pct_universe']:.1%}" if not np.isnan(row['pct_universe']) else "nan"
        mean = f"{row['mean_pnl']:+.4f}" if not np.isnan(row['mean_pnl']) else "nan"
        clo = f"{row['ci95_lo']:+.4f}" if not np.isnan(row['ci95_lo']) else "nan"
        chi = f"{row['ci95_hi']:+.4f}" if not np.isnan(row['ci95_hi']) else "nan"
        et2 = f"{row['ex_top2']:+.4f}" if not np.isnan(row['ex_top2']) else "nan"
        wr = f"{row['wr']:.2f}" if not np.isnan(row['wr']) else "nan"
        print(f"{row['offset_s']:>6} {thr_str:>10} {n:>7} {pct:>6} "
              f"{mean:>8} {clo:>7} {chi:>7} {et2:>8} {wr:>5}")

    # ── sum_ask distribution ───────────────────────────────────────────────────
    print("\n" + "="*60)
    print("SUM_ASK DISTRIBUTION (all coins, ungated)")
    for offset_s in OFFSETS:
        df5 = full[full["offset_s"] == offset_s]["sum_ask"]
        print(f"\nOffset +{offset_s}s (n={len(df5):,}):")
        print(f"  mean={df5.mean():.4f} median={df5.median():.4f} "
              f"p10={df5.quantile(.1):.4f} p90={df5.quantile(.9):.4f}")
        for thr in THRESHOLDS:
            cnt = (df5 < thr).sum()
            pct = (df5 < thr).mean()
            print(f"  sum_ask < {thr:.2f}: {cnt:5d} ({pct:.2%})")

    # ── sanity checks ──────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("SANITY CHECK — 10 BTC slugs at offset +5s")
    sample = full[(full["offset_s"] == 5) & (full["coin"] == "BTC")].head(10)
    for _, r in sample.iterrows():
        print(f"  {r['slug']}: up={r['vwap_up']:.4f} dn={r['vwap_dn']:.4f} "
              f"sum={r['sum_ask']:.4f} win={r['outcome']} win_vwap={r['win_vwap']:.4f} "
              f"pnl=${r['pnl']:.4f}")

    # ── underfill rate ─────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("UNDERFILL RATE (book too thin for $70/leg)")
    for offset_s in OFFSETS:
        df5 = full[full["offset_s"] == offset_s]
        print(f"  +{offset_s}s: up_underfilled={df5['up_underfilled'].mean():.2%} "
              f"dn_underfilled={df5['dn_underfilled'].mean():.2%}")

    # ── decision ──────────────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("DECISION (pre-registered rule)")
    print("PURSUE if: OOS CI95_lo > 0 AND ex_top2 > 0 AND n_OOS >= 100")
    pursue_found = False
    for _, row in oos_df.iterrows():
        if row['threshold'] == 'ungated':
            continue
        n = row['n']
        if (not np.isnan(row['ci95_lo']) and row['ci95_lo'] > 0 and
            not np.isnan(row['ex_top2']) and row['ex_top2'] > 0 and
            not np.isnan(n) and n >= 100):
            print(f"  *** PURSUE: offset={row['offset_s']}s threshold={row['threshold']} "
                  f"n_OOS={int(n)} CI=[{row['ci95_lo']:+.4f},{row['ci95_hi']:+.4f}] "
                  f"ex_top2={row['ex_top2']:+.4f}")
            pursue_found = True
    if not pursue_found:
        print("  PARK: no cell passes (CI95>0 AND ex_top2>0 AND n_OOS>=100)")

    return full, res_df


if __name__ == "__main__":
    full, res_df = main()
