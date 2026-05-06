"""Re-run momo strategy on the 2026-05-06 data refresh with 25-level entry books.

Phase 1: HOLD-only baseline (no exit-policy intervention).

Inputs (all from data/v4/refresh_2026_05_06):
  markets_full.csv               -- 9934 markets (BTC/ETH/SOL × 5m/15m, status=active)
  market_resolutions_full.csv    -- 16030 resolutions (Up/Down)
  klines_full.csv                -- 73K rows of 1MIN BTC/ETH/SOL × Binance/OKX
  tier1_entries/{asset}_entries_at_t120.parquet  -- microsecond 25-level entry books

Outputs:
  strategy_lab/results/meta_classifier/momo_rerun_l25_hold.csv
  strategy_lab/reports/MOMO_RERUN_L25_HOLD_2026_05_06.md

Strategy logic (mirrors production momo controller):
  At t+120s:
    asset_ret_2m = log(close@(ws+120)/close@(ws))
    threshold    = rolling 14d q90 |ret_2m| per (asset, tf)
    if |ret_2m| < threshold or not finite: SKIP
    if (ask_0 - bid_0) > spread_filter[asset]: SKIP
    signal = UP if ret_2m>0 else DOWN
    walk top-25 ASKs for $25 notional → (vwap, shares, usd_spent)
    if shares==0 or underfilled and usd_spent < $12.5: SKIP
    won = (signal==UP and outcome=='Up') or (signal==DOWN and outcome=='Down')
    HOLD pnl:
      won  → shares*1.0 - usd_spent - 2%*max(profit,0)
      lost → -usd_spent
"""
from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))

from book_walk import book_walk_fill  # noqa: E402

REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_06"
TIER1 = REFRESH / "tier1_entries"
OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_rerun_l25_hold.csv"
REPORT = ROOT / "strategy_lab" / "reports" / "MOMO_RERUN_L25_HOLD_2026_05_06.md"

LEVELS = 25
NOTIONAL_USD = 25.0
FEE_RATE = 0.02
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
GATE_QUANTILE = 0.90
LOOKBACK_DAYS = 14

ASSET_BIN = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
ASSET_OKX = {"BTC": "OKX_SPOT_BTC_USDT", "ETH": "OKX_SPOT_ETH_USDT", "SOL": "OKX_SPOT_SOL_USDT"}


def load_klines() -> dict[str, pd.DataFrame]:
    df = pd.read_csv(REFRESH / "klines_full.csv")
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for a in ("BTC", "ETH", "SOL"):
        bs = ASSET_BIN[a]; os_ = ASSET_OKX[a]
        b = df[df.symbol_id == bs][["ts_s", "price_close"]].copy(); b["src"] = "binance"
        o = df[df.symbol_id == os_][["ts_s", "price_close"]].copy(); o["src"] = "okx"
        comb = pd.concat([b, o], ignore_index=True).sort_values(["ts_s", "src"])
        comb = comb.drop_duplicates("ts_s", keep="first").sort_values("ts_s").reset_index(drop=True)
        out[a] = comb[["ts_s", "price_close"]].reset_index(drop=True)
    return out


def asof(k: pd.DataFrame, ts: int) -> float:
    """End-time-indexed asof (1MIN bars). Returns price_close of the most
    recent bar whose CLOSE TIME has already happened by ``ts``. Avoids the
    bar-open-indexed lookahead bug fixed in extended_backtest_with_robustness
    on 2026-05-06."""
    end_us = (k.ts_s.astype("int64") + 60).values * 1_000_000
    target_us = int(ts) * 1_000_000
    idx = int(np.searchsorted(end_us, target_us, side="right")) - 1
    if idx < 0:
        return float("nan")
    return float(k.price_close.iloc[idx])


def load_universe() -> pd.DataFrame:
    m = pd.read_csv(REFRESH / "markets_full.csv")
    r = pd.read_csv(REFRESH / "market_resolutions_full.csv")[["slug", "outcome"]]
    df = m.merge(r, on="slug", how="left", suffixes=("_m", ""))
    df["outcome"] = df["outcome"].fillna(df["outcome_m"])
    df = df.dropna(subset=["outcome"])
    df = df[df.ticker.isin(["BTC", "ETH", "SOL"]) & df.timeframe.isin(["5m", "15m"])].copy()
    df["ws"] = df.slug.str.extract(r"-(\d+)$")[0].astype("int64")
    df["asset"] = df.ticker
    df["tf"] = df.timeframe
    df["outcome_up"] = (df.outcome == "Up").astype(int)
    return df[["slug", "asset", "tf", "ws", "outcome", "outcome_up"]].reset_index(drop=True)


def load_entry_books() -> dict[tuple, tuple]:
    """Returns {(asset_upper, slug, outcome): (asks_p[25], asks_s[25], bids_p[25], bids_s[25], dt_abs_us)}"""
    cols_ap = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_as = [f"ask_size_{i}"  for i in range(LEVELS)]
    cols_bp = [f"bid_price_{i}" for i in range(LEVELS)]
    cols_bs = [f"bid_size_{i}"  for i in range(LEVELS)]
    out: dict = {}
    for a in ("btc", "eth", "sol"):
        df = pd.read_parquet(TIER1 / f"{a}_entries_at_t120.parquet")
        ap = df[cols_ap].to_numpy(dtype=float); as_ = df[cols_as].to_numpy(dtype=float)
        bp = df[cols_bp].to_numpy(dtype=float); bs = df[cols_bs].to_numpy(dtype=float)
        for i in range(len(df)):
            out[(a.upper(), df.slug.iat[i], df.outcome.iat[i])] = (ap[i], as_[i], bp[i], bs[i], int(df.dt_abs.iat[i]))
    return out


def compute_thresholds(uni: pd.DataFrame) -> dict:
    """Per (asset, tf): for each market's day-bucket, q90 of |ret_2m| from prior 14d (excluding current day).

    Returns {(asset, tf, day_str): threshold}
    """
    out: dict = {}
    uni = uni.copy()
    uni["day"] = pd.to_datetime(uni.ws, unit="s").dt.floor("D")
    for (asset, tf), g in uni.groupby(["asset", "tf"]):
        g = g.sort_values("ws").reset_index(drop=True)
        for day, _ in g.groupby("day"):
            cutoff_lo = day - pd.Timedelta(days=LOOKBACK_DAYS)
            train = g[(g.day >= cutoff_lo) & (g.day < day)]
            samples = train["abs_ret_2m"].dropna().values
            if len(samples) < 50:
                out[(asset, tf, str(day.date()))] = float("nan")
            else:
                out[(asset, tf, str(day.date()))] = float(np.quantile(samples, GATE_QUANTILE))
    return out


def main():
    print("[1] klines…")
    klines = load_klines()
    for a, k in klines.items():
        print(f"    {a}: {len(k)} bars  {pd.to_datetime(k.ts_s.min(), unit='s')} -> {pd.to_datetime(k.ts_s.max(), unit='s')}")

    print("[2] universe…")
    uni = load_universe()
    print(f"    {len(uni)} markets total")

    # Compute ret_2m per market.
    # CORRECTED ANCHOR (sanity-tested 2026-05-06): Polymarket UpDown strike is
    # at slug_ws - 60s, resolution at slug_ws + window - 60s. The 2-min return
    # window that maximally predicts outcome at the q90 tail is (ws-60, ws+60).
    # See _sanity_outcome.py and _sanity_gate.py — top decile hit rate flips
    # from 16% (wrong anchor ws→ws+120) to 89% (right anchor ws-60→ws+60).
    print("[3] ret_2m per market (anchor: ws-60 → ws+60)…")
    ret_vals = []
    for asset, ws in zip(uni.asset.values, uni.ws.values):
        c0 = asof(klines[asset], int(ws) - 60)
        c2 = asof(klines[asset], int(ws) + 60)
        if math.isfinite(c0) and math.isfinite(c2) and c0 > 0 and c2 > 0:
            r = math.log(c2 / c0)
        else:
            r = float("nan")
        ret_vals.append(r)
    uni["ret_2m"] = ret_vals
    uni["abs_ret_2m"] = uni.ret_2m.abs()
    n_finite = uni.ret_2m.notna().sum()
    print(f"    {n_finite}/{len(uni)} have finite ret_2m")

    print("[4] daily q90 thresholds (14d trailing)…")
    thresholds = compute_thresholds(uni)
    n_with_thresh = sum(1 for v in thresholds.values() if math.isfinite(v))
    print(f"    {n_with_thresh}/{len(thresholds)} (asset,tf,day) cells have thresholds (≥50 samples)")

    print("[5] entry books…")
    books = load_entry_books()
    print(f"    {len(books)} (asset, slug, outcome) entry books loaded")

    print("[6] simulate HOLD…")
    rows = []
    sk_no_book = sk_no_thresh = sk_below_thresh = sk_spread = sk_thin = sk_no_ret = 0
    uni["day"] = pd.to_datetime(uni.ws, unit="s").dt.floor("D")
    for r in uni.itertuples(index=False):
        if not math.isfinite(r.ret_2m):
            sk_no_ret += 1; continue
        thresh = thresholds.get((r.asset, r.tf, str(r.day.date())))
        if thresh is None or not math.isfinite(thresh):
            sk_no_thresh += 1; continue
        if r.abs_ret_2m < thresh:
            sk_below_thresh += 1; continue
        signal = "UP" if r.ret_2m > 0 else "DOWN"
        held_outcome = "Up" if signal == "UP" else "Down"
        key = (r.asset, r.slug, held_outcome)
        if key not in books:
            sk_no_book += 1; continue
        ap, as_, bp, bs, dt_abs = books[key]
        ask0 = ap[0] if len(ap) and math.isfinite(ap[0]) else float("nan")
        bid0 = bp[0] if len(bp) and math.isfinite(bp[0]) else float("nan")
        if math.isfinite(ask0) and math.isfinite(bid0) and (ask0 - bid0) > SPREAD_FILTER[r.asset]:
            sk_spread += 1; continue
        vwap, shares, usd, hits, under = book_walk_fill(ap, as_, NOTIONAL_USD)
        if shares <= 0:
            sk_thin += 1; continue
        if under and usd < NOTIONAL_USD * 0.5:
            sk_thin += 1; continue
        won = (signal == "UP" and r.outcome == "Up") or (signal == "DOWN" and r.outcome == "Down")
        if won:
            profit = shares * 1.0 - usd
            fee = profit * FEE_RATE if profit > 0 else 0.0
            pnl = profit - fee
        else:
            pnl = -usd
        rows.append(dict(
            slug=r.slug, asset=r.asset, tf=r.tf, ws=int(r.ws), day=str(r.day.date()),
            ret_2m=r.ret_2m, abs_ret_2m=r.abs_ret_2m, threshold=thresh,
            signal=signal, outcome=r.outcome, won=int(won),
            ask0=ask0, bid0=bid0, vwap_e=vwap, shares=shares, usd_spent=usd,
            hits=hits, underfilled=int(under), dt_entry_us=dt_abs, pnl=pnl,
        ))

    print(f"    fired:    {len(rows)}")
    print(f"    skipped — no_ret_2m: {sk_no_ret}, no_thresh: {sk_no_thresh}, below_thresh: {sk_below_thresh},")
    print(f"              no_book:   {sk_no_book}, spread:    {sk_spread}, thin:        {sk_thin}")

    if not rows:
        print("[FAIL] no fires"); return
    df = pd.DataFrame(rows)
    df.to_csv(ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_rerun_l25_hold_per_trade.csv", index=False)

    # Aggregate per cell
    agg = df.groupby(["asset", "tf"]).agg(
        n=("pnl", "size"),
        wins=("won", "sum"),
        hit=("won", "mean"),
        pnl_total=("pnl", "sum"),
        pnl_mean=("pnl", "mean"),
        pnl_std=("pnl", "std"),
        pnl_min=("pnl", "min"),
        pnl_max=("pnl", "max"),
        avg_vwap=("vwap_e", "mean"),
        avg_dt_entry_us=("dt_entry_us", "mean"),
    ).reset_index()
    agg["sharpe"] = agg.pnl_mean / agg.pnl_std.replace(0, float("nan"))
    agg["pnl_per_$1"] = agg.pnl_mean / NOTIONAL_USD
    print("\n=== Per-cell HOLD aggregation ===")
    print(agg.to_string(index=False))
    agg.to_csv(OUT_CSV, index=False)
    print(f"\nCSV: {OUT_CSV}")

    # Build markdown report
    md = []
    md.append("# Momo Re-run on 2026-05-06 dataset — HOLD baseline (25-level entry books)\n")
    md.append(f"**Generated:** {pd.Timestamp.utcnow():%Y-%m-%d %H:%M UTC}  ")
    md.append("**Source:** `data/v4/refresh_2026_05_06/`  ")
    md.append(f"**Strategy:** momo gate (q{int(GATE_QUANTILE*100)} |ret_2m|, {LOOKBACK_DAYS}d trailing) → top-25 ASK walk → ${NOTIONAL_USD:.0f} notional → HOLD to chainlink.  ")
    md.append(f"**Fee model:** {FEE_RATE*100:.0f}% on profit only.\n")
    md.append("## Pipeline counts\n")
    md.append(f"- universe (resolved markets): **{len(uni)}**")
    md.append(f"- with finite ret_2m: **{n_finite}**")
    md.append(f"- below q90 gate: **{sk_below_thresh}**")
    md.append(f"- skipped (no entry book): **{sk_no_book}**, (spread): **{sk_spread}**, (thin): **{sk_thin}**, (no thresh): **{sk_no_thresh}**")
    md.append(f"- **fires: {len(rows)}**\n")
    md.append("## Per-cell HOLD\n")
    md.append("| cell | n | wins | hit% | pnl_total | pnl_mean | pnl_std | sharpe | pnl_per_$1 | avg_vwap | dt_entry_us p̄ |")
    md.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in agg.iterrows():
        md.append(
            f"| {r.asset}_{r.tf} | {int(r.n)} | {int(r.wins)} | {r.hit*100:.1f} | "
            f"${r.pnl_total:+.2f} | ${r.pnl_mean:+.4f} | {r.pnl_std:.2f} | "
            f"{r.sharpe:.2f} | ${r['pnl_per_$1']:+.4f} | "
            f"{r.avg_vwap:.4f} | {int(r.avg_dt_entry_us):,} |"
        )
    md.append("")
    md.append("## Comparison vs prior `extended_backtest.csv` (HOLD column)\n")
    md.append("Prior run (May 6 morning): 1,151 trades total, +$13,481 across 6 cells.")
    md.append(f"This run: **{len(rows)}** trades total, **${df.pnl.sum():+.2f}**.")
    md.append("Differences attributable to:")
    md.append("- updated resolution data (post-shadow-deploy markets included)")
    md.append("- 25-level entry books (was already 25-level — should be ~identical)")
    md.append("- threshold recompute on fresh 14d windows\n")
    md.append("## Next phases (HEDGE / SELL with 25-level exits)\n")
    md.append("HOLD-only here. HEDGE/SELL paths require book snapshots during the holding window")
    md.append("(buckets 13-29 for 5m, 13-89 for 15m). The raw L25 gzipped CSVs in `refresh_2026_05_06/`")
    md.append("contain microsecond snapshots — Phase 2 will stream-aggregate these into")
    md.append("per-(slug, bucket, outcome) 25-level snapshots, then HEDGE/SELL/anchor-sweep tests")
    md.append("can run on the precision exit data.\n")
    REPORT.write_text("\n".join(md), encoding="utf-8")
    print(f"Report: {REPORT}")


if __name__ == "__main__":
    main()
