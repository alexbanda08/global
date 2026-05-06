"""Exit-policy comparison v2 — uses TIER 1 microsecond-precise entry books.

Differences from exit_policy_multi_asset.py:
  - Entry book: from tier1 parquet (closest snapshot to t+120s, 25 levels of
    depth, microsecond timestamp). Median 338ms from target.
  - Exit/hedge monitoring: still uses the existing 10s-bucket CSVs (good
    enough for revert detection on a 30-bucket / 90-bucket horizon).

This isolates the IMPACT of better entry data on PnL, while keeping the
exit logic identical for apples-to-apples comparison.

Outputs:
  strategy_lab/results/meta_classifier/exit_policy_tier1.csv
  strategy_lab/reports/EXIT_POLICY_TIER1.md
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

LEVELS_T1 = 25  # tier1 has 25 levels
LEVELS_BUCKETS = 10  # bucket CSVs have 10 levels (used for exit monitoring)
NOTIONAL_USD = 25.0
FEE_RATE = 0.02
SPREAD_FILTER = {"btc": 0.02, "eth": 0.02, "sol": 0.025}

REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_02"
TIER1 = ROOT / "data" / "v4" / "tier1_entries"
KLINES = REFRESH / "binance_spot_1min_full.csv"

OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "exit_policy_tier1.csv"
REPORT  = ROOT / "strategy_lab" / "reports"  / "EXIT_POLICY_TIER1.md"

ASSET_SYMBOL = {
    "btc": "BINANCE_SPOT_BTC_USDT",
    "eth": "BINANCE_SPOT_ETH_USDT",
    "sol": "BINANCE_SPOT_SOL_USDT",
}


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_tier1(asset: str) -> dict:
    """Returns {(slug, outcome): (asks_p[25], asks_s[25], bids_p[25], bids_s[25])}."""
    df = pd.read_parquet(TIER1 / f"{asset}_entries_at_t120.parquet")
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
    """Returns {slug: {(bucket, outcome): (asks_p[10], asks_s[10], bids_p[10], bids_s[10])}}."""
    path = REFRESH / f"{asset}_book_depth_v3_full.csv"
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


def load_klines() -> dict[str, pd.DataFrame]:
    df = pd.read_csv(KLINES)
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for asset, sym in ASSET_SYMBOL.items():
        sub = df[df.symbol_id == sym].sort_values("ts_s").reset_index(drop=True)
        out[asset] = sub[["ts_s", "price_close"]]
    return out


def asof(k1m: pd.DataFrame, ts: int) -> float:
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


def load_universe(asset: str, k1m: pd.DataFrame) -> pd.DataFrame:
    df = pd.read_csv(REFRESH / f"{asset}_markets_minimal.csv").dropna(subset=["window_start_unix", "outcome_up"])
    df["outcome_up"] = df["outcome_up"].astype(int)
    df["asset"] = asset
    df["asset_ret_2m"] = df["window_start_unix"].astype("int64").apply(
        lambda w: np.log(asof(k1m, int(w) + 120) / asof(k1m, int(w))))
    return df


# ---------------------------------------------------------------------------
# Simulator with tier1 entry + bucket exit
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


def simulate(row: pd.Series, k1m: pd.DataFrame,
             entry_book: dict, bucket_book: dict, max_bucket: int,
             policy: str, rev_bp: int = 5,
             floor: float | None = None, trail_pct: float | None = None,
             spread_filter: float | None = None) -> dict | None:
    sig = int(row.signal)
    held = "Up" if sig == 1 else "Down"
    other = "Down" if sig == 1 else "Up"

    # ENTRY: from tier1 parquet (microsecond-precise, 25 levels)
    entry_key = (row.slug, held)
    if entry_key not in entry_book:
        return None
    ask_p, ask_s, bid_p, bid_s = entry_book[entry_key]
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
    peak_bid = bid_p[0] if len(bid_p) and np.isfinite(bid_p[0]) else 0.0
    exit_event = None

    # EXIT/HEDGE monitoring uses bucket CSV (existing 10s data)
    if policy != "HOLD":
        slug_book = bucket_book.get(row.slug, {})
        for bucket in range(13, max_bucket + 1):  # buckets 13-29 (5m) or 13-89 (15m)
            held_key_b = (bucket, held)
            cur_bid = 0.0; b_p = None; b_s = None
            if held_key_b in slug_book:
                _, _, b_p, b_s = slug_book[held_key_b]
                cur_bid = b_p[0] if len(b_p) and np.isfinite(b_p[0]) else 0.0
                peak_bid = max(peak_bid, cur_bid)

            bp_rev = None
            if policy in ("HEDGE_REVERT", "SELL_REVERT_BID", "SELL_REVERT_8BP"):
                ts_in = ws + bucket * 10
                a_now = asof(k1m, ts_in)
                if np.isfinite(asset_at_entry) and np.isfinite(a_now):
                    bp_rev = (a_now - asset_at_entry) / asset_at_entry * 10000.0
            policy_rev = rev_bp if policy != "SELL_REVERT_8BP" else 8

            if policy == "HEDGE_REVERT" and bp_rev is not None:
                trig = (sig == 1 and bp_rev <= -policy_rev) or (sig == 0 and bp_rev >= policy_rev)
                if trig and (bucket, other) in slug_book:
                    h_ask_p, h_ask_s, _, _ = slug_book[(bucket, other)]
                    top = h_ask_p[0] if len(h_ask_p) and np.isfinite(h_ask_p[0]) else float("nan")
                    if np.isfinite(top) and 0 < top < 1:
                        target_h = shares_e * float(top)
                        vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(h_ask_p, h_ask_s, target_h)
                        if shares_h > 0:
                            if shares_h < shares_e * 0.95 and not under_h:
                                vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(h_ask_p, h_ask_s, shares_e * vwap_h)
                            exit_event = ("hedge", bucket, dict(vwap_h=vwap_h, shares_h=shares_h, usd_h=usd_h))
                            break
            elif policy in ("SELL_REVERT_BID", "SELL_REVERT_8BP") and bp_rev is not None:
                trig = (sig == 1 and bp_rev <= -policy_rev) or (sig == 0 and bp_rev >= policy_rev)
                if trig and b_p is not None:
                    sv, sg = sell_at_bid(b_p, b_s, shares_e)
                    if np.isfinite(sv) and sg > 0:
                        exit_event = ("sell_revert", bucket, dict(sell_vwap=sv, sell_gross=sg)); break
            elif policy.startswith("SELL_FLOOR_") and floor is not None and cur_bid > 0 and cur_bid <= floor:
                if b_p is not None:
                    sv, sg = sell_at_bid(b_p, b_s, shares_e)
                    if np.isfinite(sv) and sg > 0:
                        exit_event = ("sell_floor", bucket, dict(sell_vwap=sv, sell_gross=sg)); break
            elif policy.startswith("SELL_TRAIL_") and trail_pct is not None and peak_bid > 0 and cur_bid > 0:
                if (peak_bid - cur_bid) / peak_bid >= trail_pct:
                    if b_p is not None:
                        sv, sg = sell_at_bid(b_p, b_s, shares_e)
                        if np.isfinite(sv) and sg > 0:
                            exit_event = ("sell_trail", bucket, dict(sell_vwap=sv, sell_gross=sg)); break

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
    return dict(pnl=profit - fee, cost=usd_e, vwap_e=vwap_e, exit_reason=kind, sig_won=won)


def run(df: pd.DataFrame, k1m: pd.DataFrame, entry_book: dict, bucket_book: dict,
        policy: str, label: str, **kwargs) -> dict:
    pnls, costs, ws_list, vwaps = [], [], [], []
    sk_thin = sk_no_book = sk_spread = wins = 0
    exit_kinds = {"hold": 0, "hedge": 0, "sell_revert": 0, "sell_floor": 0, "sell_trail": 0}
    for _, row in df.iterrows():
        max_b = 89 if row.timeframe == "15m" else 29
        r = simulate(row, k1m, entry_book, bucket_book, max_b, policy, **kwargs)
        if r is None: sk_no_book += 1; continue
        if r.get("skipped_spread"): sk_spread += 1; continue
        if r.get("skipped_thin"): sk_thin += 1; continue
        pnls.append(r["pnl"]); costs.append(r["cost"]); ws_list.append(int(row.window_start_unix))
        vwaps.append(r["vwap_e"])
        if r["sig_won"]: wins += 1
        exit_kinds[r["exit_reason"]] = exit_kinds.get(r["exit_reason"], 0) + 1
    pnls = np.array(pnls); costs = np.array(costs); n = len(pnls)
    if n == 0:
        return {"label": label, "n": 0}
    eq = equity_curve_stats(pnls, trade_timestamps=np.array(ws_list, dtype=float))
    return dict(
        label=label, n=n, wins=wins,
        hit=float((pnls > 0).mean()),
        pnl_total=float(pnls.sum()),
        pnl_mean=float(pnls.mean()),
        pnl_std=float(pnls.std()),
        pnl_min=float(pnls.min()),
        pnl_max=float(pnls.max()),
        avg_vwap_e=float(np.mean(vwaps)),
        n_hold=exit_kinds.get("hold", 0),
        n_hedge=exit_kinds.get("hedge", 0),
        n_sell=exit_kinds.get("sell_revert", 0) + exit_kinds.get("sell_floor", 0) + exit_kinds.get("sell_trail", 0),
        sk_thin=sk_thin, sk_no_book=sk_no_book, sk_spread=sk_spread,
        sharpe=eq["sharpe"], sortino=eq["sortino"], max_dd=eq["max_dd"],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("[1] klines + universes…")
    klines = load_klines()
    universes = {a: load_universe(a, klines[a]) for a in ["btc", "eth", "sol"]}

    print("[2] tier1 entry books (microsecond, 25 levels)…")
    entry_books = {a: load_tier1(a) for a in ["btc", "eth", "sol"]}
    for a in ["btc", "eth", "sol"]:
        print(f"    {a}: {len(entry_books[a])} (slug,outcome) pairs")

    print("[3] bucket books (for exit monitoring)…")
    bucket_books = {a: load_book_buckets(a) for a in ["btc", "eth", "sol"]}

    POLICIES = [
        ("HOLD",            dict(policy="HOLD")),
        ("HEDGE_REVERT_5",  dict(policy="HEDGE_REVERT", rev_bp=5)),
        ("SELL_REVERT_5",   dict(policy="SELL_REVERT_BID", rev_bp=5)),
    ]

    results = []
    print("\n[4] running…")
    for asset in ["btc", "eth", "sol"]:
        df = universes[asset]
        active = df[df["asset_ret_2m"].notna()].copy()
        for tf in ["5m", "15m"]:
            sub_tf = active[active.timeframe == tf].copy()
            thr = sub_tf["asset_ret_2m"].abs().quantile(0.90)
            fired = sub_tf[sub_tf["asset_ret_2m"].abs() >= thr].copy()
            fired["signal"] = (fired["asset_ret_2m"] > 0).astype(int)
            for pol_name, pol_kwargs in POLICIES:
                r = run(fired, klines[asset], entry_books[asset], bucket_books[asset],
                        label=f"{asset.upper()}_{tf} | {pol_name}",
                        spread_filter=SPREAD_FILTER[asset], **pol_kwargs)
                results.append(r)
                if r["n"] > 0:
                    print(f"  {r['label']:30s}  n={r['n']:4d}  hit={r['hit']*100:5.1f}%  "
                          f"vwap=${r['avg_vwap_e']:.4f}  pnl=${r['pnl_total']:+9.2f}  "
                          f"mean=${r['pnl_mean']:+.4f}  std=${r['pnl_std']:5.2f}  "
                          f"min=${r['pnl_min']:+.2f}  max=${r['pnl_max']:+.2f}  "
                          f"sharpe={r['sharpe']:+.2f}")

    df_res = pd.DataFrame(results)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(OUT_CSV, index=False)

    L = [
        "# Exit Policy — TIER 1 Microsecond-Precise Entries\n",
        "_Generated: 2026-05-05_\n",
        "## What changed vs `EXIT_POLICY_MULTI_ASSET.md`\n",
        f"- Entry book: now uses **tier1 parquet** = single snapshot per (slug, outcome) within ±5s of t+120s (median 338ms from target), with **25 levels of depth**.",
        f"- Exit monitoring: still uses 10s-bucket CSVs (good enough for revert detection on 30/90 bucket horizons).",
        f"- Engine, fees, sizing, gates: unchanged.",
        "",
        "## Coverage (universe → tier1 match rate)\n",
        f"- BTC: {len(entry_books['btc'])} (slug,outcome) pairs / {2*4673} expected = {len(entry_books['btc'])/(2*4673)*100:.1f}%",
        f"- ETH: {len(entry_books['eth'])} / {2*4673} = {len(entry_books['eth'])/(2*4673)*100:.1f}%",
        f"- SOL: {len(entry_books['sol'])} / {2*4673} = {len(entry_books['sol'])/(2*4673)*100:.1f}%",
        "",
        "## Results — 3 exit policies × 3 assets × 2 tfs\n",
        "| Cell | Policy | n | hit% | avg vwap_e | total | mean | std | min | max | Sharpe | hedged | sells |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        if r["n"] == 0:
            L.append(f"| {r['label'].split(' | ')[0]} | {r['label'].split(' | ')[1]} | 0 | — | — | — | — | — | — | — | — | — | — |")
            continue
        cell, pol = r["label"].split(" | ")
        L.append(
            f"| {cell} | {pol} | {r['n']} | {r['hit']*100:.1f} | "
            f"${r['avg_vwap_e']:.4f} | ${r['pnl_total']:+.2f} | ${r['pnl_mean']:+.4f} | "
            f"${r['pnl_std']:.2f} | ${r['pnl_min']:+.2f} | ${r['pnl_max']:+.2f} | "
            f"{r['sharpe']:+.2f} | {r['n_hedge']} | {r['n_sell']} |"
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[report] wrote {REPORT}")
    print(f"[csv]    wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
