"""
polymarket_realfills_validate.py — apples-to-apples validation: v2-baseline (level-0 single price)
vs realistic (book-walked) on the SAME matched universe.

For every (asset, tf, signal=q20, rev_bp=5, notional in {1,25,100,250}) cell:
  - run BASELINE: 1 share entry at entry_yes_ask, 1 share hedge at other_ask_min — matches v2 logic
  - run REALISTIC: book-walk top-10 levels for entry + hedge at notional stake

Per-trade dump includes both PnLs so deltas can be analyzed.

Outputs:
  results/polymarket/realfills_validate_per_trade.json
  results/polymarket/realfills_validate_cells.csv
"""
from __future__ import annotations
from pathlib import Path
import json
import numpy as np
import pandas as pd

from book_walk import book_walk_fill

HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(42)
FEE_RATE = 0.02
ASSETS = ["btc", "eth", "sol"]
LEVELS = 10
NOTIONAL_LADDER = [1.0, 25.0, 100.0, 250.0]
REV_BP = 5


def load_features(asset: str) -> pd.DataFrame:
    df = pd.read_csv(HERE / "data" / "polymarket" / f"{asset}_features_v3.csv")
    df["asset"] = asset
    return df


def load_trajectories(asset: str) -> dict[str, pd.DataFrame]:
    t = pd.read_csv(HERE / "data" / "polymarket" / f"{asset}_trajectories_v3.csv")
    up = t[t.outcome == "Up"].rename(columns={
        "bid_first":"up_bid_first","bid_last":"up_bid_last",
        "bid_min":"up_bid_min","bid_max":"up_bid_max",
        "ask_first":"up_ask_first","ask_last":"up_ask_last",
        "ask_min":"up_ask_min","ask_max":"up_ask_max",
    })[["slug","bucket_10s","window_start_unix",
        "up_bid_first","up_bid_last","up_bid_min","up_bid_max",
        "up_ask_first","up_ask_last","up_ask_min","up_ask_max"]]
    dn = t[t.outcome == "Down"].rename(columns={
        "bid_first":"dn_bid_first","bid_last":"dn_bid_last",
        "bid_min":"dn_bid_min","bid_max":"dn_bid_max",
        "ask_first":"dn_ask_first","ask_last":"dn_ask_last",
        "ask_min":"dn_ask_min","ask_max":"dn_ask_max",
    })[["slug","bucket_10s",
        "dn_bid_first","dn_bid_last","dn_bid_min","dn_bid_max",
        "dn_ask_first","dn_ask_last","dn_ask_min","dn_ask_max"]]
    merged = up.merge(dn, on=["slug","bucket_10s"], how="outer").sort_values(["slug","bucket_10s"])
    return {slug:g.reset_index(drop=True) for slug,g in merged.groupby("slug")}


def load_book_depth(asset: str) -> dict[str, dict]:
    df = pd.read_csv(HERE / "data" / "polymarket" / f"{asset}_book_depth_v3.csv")
    cols_ask_p = [f"ask_price_{i}" for i in range(LEVELS)]
    cols_ask_s = [f"ask_size_{i}"  for i in range(LEVELS)]
    asks_p = df[cols_ask_p].to_numpy(dtype=float)
    asks_s = df[cols_ask_s].to_numpy(dtype=float)
    slugs = df.slug.to_numpy()
    buckets = df.bucket_10s.to_numpy(dtype=int)
    outcomes = df.outcome.to_numpy()
    out: dict[str, dict] = {}
    for i in range(len(df)):
        slug = slugs[i]
        if slug not in out:
            out[slug] = {}
        out[slug][(int(buckets[i]), outcomes[i])] = (asks_p[i], asks_s[i])
    return out


def load_klines_1m(asset: str) -> pd.DataFrame:
    k = pd.read_csv(HERE / "data" / "binance" / f"{asset}_klines_window.csv")
    k1m = k[k.period_id == "1MIN"].copy()
    k1m["ts_s"] = (k1m.time_period_start_us // 1_000_000).astype(int)
    return k1m.sort_values("ts_s").reset_index(drop=True)[["ts_s", "price_close"]]


def asof_close(k1m, ts):
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


def add_q20_signal(df):
    df = df.copy()
    df["signal"] = -1
    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            m = (df.asset == asset) & (df.timeframe == tf)
            ret = df.loc[m, "ret_5m"].abs()
            q20 = ret.quantile(0.80)
            sel = m & (df.ret_5m.abs() >= q20) & df.ret_5m.notna()
            df.loc[sel, "signal"] = (df.loc[sel, "ret_5m"] > 0).astype(int)
    return df[df.signal != -1].copy()


def simulate_baseline_v2(row, traj_g, k1m, rev_bp):
    """Mimic v2's per-$1 stake logic (1 share entry + 1 share hedge at level-0 prices)."""
    sig = int(row.signal)
    entry = float(row.entry_yes_ask) if sig == 1 else float(row.entry_no_ask)
    if not (np.isfinite(entry) and 0 < entry < 1):
        return None

    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws)
    hedge_other_entry = None
    trigger_bucket = None

    for _, b in traj_g.iterrows():
        bucket = int(b.bucket_10s)
        if bucket < 0:
            continue
        if rev_bp is not None and np.isfinite(btc_at_ws):
            ts_in_bucket = ws + bucket * 10
            btc_now = asof_close(k1m, ts_in_bucket)
            if not np.isfinite(btc_now):
                continue
            bp = (btc_now - btc_at_ws) / btc_at_ws * 10000
            reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
            if reverted:
                col = "dn_ask_min" if sig == 1 else "up_ask_min"
                other_ask = b[col]
                if pd.notna(other_ask) and 0 < other_ask < 1:
                    hedge_other_entry = float(other_ask)
                    trigger_bucket = bucket
                    break

    outcome_up = int(row.outcome_up)
    sig_won = (sig == outcome_up)

    if hedge_other_entry is None:
        if sig_won:
            payout = 1.0 - (1.0 - entry) * FEE_RATE
            pnl = payout - entry
        else:
            pnl = -entry
        cost = entry
        return {"pnl": pnl, "cost": cost, "entry_p": entry, "hedge_p": None,
                "shares_e": 1.0, "shares_h": 0.0, "lvls_e": 1, "lvls_h": 0,
                "hedged": False, "sig_won": sig_won, "trigger_bucket": None}

    if sig_won:
        payout = 1.0 - (1.0 - entry) * FEE_RATE
    else:
        payout = 1.0 - (1.0 - hedge_other_entry) * FEE_RATE
    pnl = payout - entry - hedge_other_entry
    cost = entry + hedge_other_entry
    return {"pnl": pnl, "cost": cost, "entry_p": entry, "hedge_p": hedge_other_entry,
            "shares_e": 1.0, "shares_h": 1.0, "lvls_e": 1, "lvls_h": 1,
            "hedged": True, "sig_won": sig_won, "trigger_bucket": trigger_bucket}


def simulate_realistic(row, traj_g, k1m, book, rev_bp, notional_usd):
    """Book-walk version with hedge-share equalization."""
    sig = int(row.signal)
    held = "Up" if sig == 1 else "Down"
    other = "Down" if sig == 1 else "Up"

    entry_book = book.get((0, held))
    if entry_book is None:
        return None
    ask_p, ask_s = entry_book
    vwap_e, shares_e, usd_e, lvls_e, under_e = book_walk_fill(ask_p, ask_s, notional_usd)
    if shares_e <= 0:
        return None
    if under_e and usd_e < notional_usd * 0.5:
        return {"skipped_thin": True}

    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws)
    hedge = None
    trigger_bucket = None

    if rev_bp is not None and np.isfinite(btc_at_ws):
        for _, b in traj_g.iterrows():
            bucket = int(b.bucket_10s)
            if bucket < 0:
                continue
            ts_in_bucket = ws + bucket * 10
            btc_now = asof_close(k1m, ts_in_bucket)
            if not np.isfinite(btc_now):
                continue
            bp = (btc_now - btc_at_ws) / btc_at_ws * 10000
            reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
            if not reverted:
                continue
            hedge_book = book.get((bucket, other))
            if hedge_book is None:
                break
            h_ask_p, h_ask_s = hedge_book
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
            trigger_bucket = bucket
            break

    outcome_up = int(row.outcome_up)
    sig_won = (sig == outcome_up)

    if hedge is None:
        if sig_won:
            gross = shares_e * 1.0
            profit = gross - usd_e
            fee = profit * FEE_RATE if profit > 0 else 0.0
            pnl = profit - fee
        else:
            pnl = -usd_e
        return {"pnl": pnl, "cost": usd_e, "vwap_e": vwap_e, "vwap_h": None,
                "shares_e": shares_e, "shares_h": 0.0, "lvls_e": lvls_e, "lvls_h": 0,
                "under_e": under_e, "under_h": False,
                "hedged": False, "sig_won": sig_won, "trigger_bucket": None,
                "skipped_thin": False}

    vwap_h, shares_h, usd_h, lvls_h, under_h = hedge
    cost = usd_e + usd_h
    if sig_won:
        gross = shares_e * 1.0
        fee = shares_e * (1.0 - vwap_e) * FEE_RATE
    else:
        gross = shares_h * 1.0
        fee = shares_h * (1.0 - vwap_h) * FEE_RATE
    pnl = gross - cost - fee
    return {"pnl": pnl, "cost": cost, "vwap_e": vwap_e, "vwap_h": vwap_h,
            "shares_e": shares_e, "shares_h": shares_h, "lvls_e": lvls_e, "lvls_h": lvls_h,
            "under_e": under_e, "under_h": under_h,
            "hedged": True, "sig_won": sig_won, "trigger_bucket": trigger_bucket,
            "skipped_thin": False}


def cell_stats(pnls, costs, hits):
    pnls = np.array(pnls); costs = np.array(costs)
    n = len(pnls)
    if n == 0:
        return {"n": 0, "pnl_total": 0.0, "pnl_mean": 0.0, "roi_v2": 0.0,
                "roi_capital": 0.0, "ci_lo": 0.0, "ci_hi": 0.0, "hit": float("nan")}
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    return {
        "n": n,
        "pnl_total": float(pnls.sum()),
        "pnl_mean": float(pnls.mean()),
        "roi_v2": float(pnls.mean() * 100),  # v2's metric: per-share or per-$1-stake
        "roi_capital": float((pnls / np.where(costs > 0, costs, 1.0)).mean() * 100),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "hit": float((pnls > 0).mean()),
        "hits": int(np.array(hits).sum()),
        "total_capital": float(costs.sum()),
    }


def main():
    print("Loading data...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    book = {a: load_book_depth(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}
    print(f"  features={len(feats)}  book_depth_slugs={sum(len(b) for b in book.values())}")

    feats_q20 = add_q20_signal(feats)
    print(f"q20 markets: {len(feats_q20)}")

    per_trade = []  # full detail dump
    cells = []      # cell-level summary

    # For each (asset_filter, tf, notional): run both modes
    for asset_filter in [None] + list(ASSETS):
        asset_lbl = "ALL" if asset_filter is None else asset_filter
        sub_a = feats_q20 if asset_filter is None else feats_q20[feats_q20.asset == asset_filter]
        for tf in ["5m", "15m", "ALL"]:
            sub_tf = sub_a if tf == "ALL" else sub_a[sub_a.timeframe == tf]
            if len(sub_tf) == 0:
                continue

            # First: baseline v2 (per-$1 stake equivalent — same for all stakes since 1-share)
            base_pnls, base_costs, base_hits = [], [], []
            base_per_trade = {}
            n_no_book_baseline = 0
            for _, row in sub_tf.iterrows():
                slug = row.slug
                tg = traj[row.asset].get(slug)
                if tg is None or tg.empty:
                    n_no_book_baseline += 1
                    continue
                r = simulate_baseline_v2(row, tg, k1m[row.asset], REV_BP)
                if r is None:
                    n_no_book_baseline += 1
                    continue
                base_pnls.append(r["pnl"])
                base_costs.append(r["cost"])
                base_hits.append(int(r["pnl"] > 0))
                base_per_trade[slug] = {**r, "asset": row.asset, "tf": row.timeframe,
                                         "sig": int(row.signal), "outcome_up": int(row.outcome_up)}

            base_stats = cell_stats(base_pnls, base_costs, base_hits)
            cells.append({"asset": asset_lbl, "tf": tf, "notional": "baseline_v2",
                          "mode": "baseline_v2", **base_stats,
                          "skipped_no_book": n_no_book_baseline})

            # Then: realistic at each stake
            for notional in NOTIONAL_LADDER:
                real_pnls, real_costs, real_hits = [], [], []
                n_no_book = 0
                n_thin = 0
                for _, row in sub_tf.iterrows():
                    slug = row.slug
                    tg = traj[row.asset].get(slug)
                    if tg is None or tg.empty:
                        n_no_book += 1
                        continue
                    bk = book[row.asset].get(slug)
                    if bk is None:
                        n_no_book += 1
                        continue
                    r = simulate_realistic(row, tg, k1m[row.asset], bk, REV_BP, notional)
                    if r is None:
                        n_no_book += 1
                        continue
                    if r.get("skipped_thin"):
                        n_thin += 1
                        continue
                    real_pnls.append(r["pnl"])
                    real_costs.append(r["cost"])
                    real_hits.append(int(r["pnl"] > 0))
                    # Only keep per-trade dump for ALL/ALL cell across stakes (avoid bloat)
                    if asset_lbl == "ALL" and tf == "ALL":
                        if slug not in base_per_trade:
                            continue
                        bp = base_per_trade[slug]
                        per_trade.append({
                            "slug": slug, "asset": row.asset, "tf": row.timeframe,
                            "sig": int(row.signal), "outcome_up": int(row.outcome_up),
                            "stake": notional,
                            "base_pnl": bp["pnl"], "base_cost": bp["cost"],
                            "base_entry_p": bp["entry_p"], "base_hedge_p": bp["hedge_p"],
                            "base_hedged": bp["hedged"],
                            "real_pnl": r["pnl"], "real_cost": r["cost"],
                            "real_vwap_e": r["vwap_e"], "real_vwap_h": r["vwap_h"],
                            "real_shares_e": r["shares_e"], "real_shares_h": r["shares_h"],
                            "real_lvls_e": r["lvls_e"], "real_lvls_h": r["lvls_h"],
                            "real_hedged": r["hedged"],
                            "real_under_e": r["under_e"], "real_under_h": r["under_h"],
                            "trigger_bucket": r["trigger_bucket"],
                            "sig_won": r["sig_won"],
                            "delta_pnl_pct": (r["pnl"] - bp["pnl"]) / max(abs(bp["pnl"]), 0.01) * 100,
                        })

                real_stats = cell_stats(real_pnls, real_costs, real_hits)
                cells.append({"asset": asset_lbl, "tf": tf, "notional": notional,
                              "mode": "realistic", **real_stats,
                              "skipped_no_book": n_no_book, "skipped_thin": n_thin})
                print(f"asset={asset_lbl:3s} tf={tf:3s} ${notional:>5.0f} → "
                      f"n={real_stats['n']:>4d} pnl_mean=${real_stats['pnl_mean']:+.4f} "
                      f"roi_v2={real_stats['roi_v2']:+5.2f}% "
                      f"roi_cap={real_stats['roi_capital']:+5.2f}% "
                      f"hit={real_stats['hit']*100:5.1f}% "
                      f"thin={n_thin:>3d}")

            print(f"          baseline_v2 → "
                  f"n={base_stats['n']:>4d} pnl_mean=${base_stats['pnl_mean']:+.4f} "
                  f"roi_v2={base_stats['roi_v2']:+5.2f}% "
                  f"hit={base_stats['hit']*100:5.1f}%")

    # Write outputs
    out_dir = HERE / "results" / "polymarket"
    out_dir.mkdir(parents=True, exist_ok=True)
    cells_df = pd.DataFrame(cells)
    cells_df.to_csv(out_dir / "realfills_validate_cells.csv", index=False)

    with open(out_dir / "realfills_validate_per_trade.json", "w") as f:
        # Pre-clean NaN/Inf for JSON
        clean = []
        for t in per_trade:
            d = {}
            for k, v in t.items():
                if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
                    d[k] = None
                else:
                    d[k] = v
            clean.append(d)
        json.dump(clean, f)
    print(f"\nWrote {out_dir/'realfills_validate_cells.csv'}")
    print(f"Wrote {out_dir/'realfills_validate_per_trade.json'} ({len(per_trade)} trade rows)")


if __name__ == "__main__":
    main()
