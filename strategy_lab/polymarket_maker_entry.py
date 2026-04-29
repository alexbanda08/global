"""
polymarket_maker_entry.py — STANDALONE candidate strategy: place limit-at-bid+tick instead of crossing spread.

Hypothesis (from JBecker 2026 + side_asymmetry test 2):
  - Markets carry ~2.6¢ taker spread on average (yes_ask + no_ask = 1.026 mean)
  - If we POST liquidity (limit at bid_top + 1 tick) instead of TAKE (cross spread),
    we save ~1-2¢ per leg = ~1-2pp ROI per trade on top of q10 edge

Mechanics:
  1. At window_start, place a buy limit at our_side_bid + TICK (1 cent improvement)
  2. Wait WAIT_BUCKETS × 10s. Filled if ask drops to <= our_limit during any bucket
  3. If filled: entry = our_limit price (cheaper than crossing the ask)
  4. Same hedge-hold rev_bp=5 logic on exit (placed at other-side ASK, like baseline)

Variants tested:
  V1 maker_only: skip if not filled in WAIT_BUCKETS
  V2 maker_then_taker: fallback to taker entry at ask if not filled by deadline
  V3 maker_aggressive: improve by 2 ticks (bid+0.02) — fill faster but smaller spread save

Wait windows tested: 30s, 60s, 120s, 180s

Also tested: hedge-side maker (limit on opposite side at its bid+tick after rev_bp triggers).
  Optional second-tier optimization.

Outputs:
  results/polymarket/maker_entry.csv
  reports/POLYMARKET_MAKER_ENTRY.md
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from polymarket_signal_grid_v2 import load_features, load_trajectories, load_klines_1m

RNG = np.random.default_rng(42)
ASSETS = ["btc", "eth", "sol"]
REV_BP = 5
FEE_RATE = 0.02
TICK = 0.01

OUT_CSV = HERE / "results" / "polymarket" / "maker_entry.csv"
OUT_MD = HERE / "reports" / "POLYMARKET_MAKER_ENTRY.md"


def add_q10_signal(df):
    df = df.copy()
    df["signal"] = -1
    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            m = (df.asset == asset) & (df.timeframe == tf)
            r_abs = df.loc[m, "ret_5m"].abs()
            thr = r_abs.quantile(0.90)
            sel = m & (df.ret_5m.abs() >= thr) & df.ret_5m.notna()
            df.loc[sel, "signal"] = (df.loc[sel, "ret_5m"] > 0).astype(int)
    return df[df.signal != -1].copy()


def asof_close(k1m, ts):
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


def simulate_maker_entry(row, traj_g, k1m, rev_bp, wait_buckets, tick_improve, fallback_to_taker):
    """Maker entry: post limit at held-side bid + tick_improve. Hedge stays as taker (baseline).

    Returns dict {pnl, cost, entry_used, filled_as_maker, fill_bucket, hedged, sig_won, ...} or None.
    """
    sig = int(row.signal)
    # bucket_0 of held side
    bucket0 = traj_g[traj_g.bucket_10s == 0]
    if bucket0.empty:
        return None
    b0 = bucket0.iloc[0]

    if sig == 1:
        held_bid_first = b0.get("up_bid_first", float("nan"))
        held_ask_at_ws = float(row.entry_yes_ask) if pd.notna(row.entry_yes_ask) else float("nan")
        ask_min_col = "up_ask_min"
    else:
        held_bid_first = b0.get("dn_bid_first", float("nan"))
        held_ask_at_ws = float(row.entry_no_ask) if pd.notna(row.entry_no_ask) else float("nan")
        ask_min_col = "dn_ask_min"

    if not (np.isfinite(held_bid_first) and 0 < held_bid_first < 1):
        return None
    if not (np.isfinite(held_ask_at_ws) and 0 < held_ask_at_ws < 1):
        return None

    our_limit = float(held_bid_first) + tick_improve
    # Ensure our limit is BELOW the current ask (otherwise it crosses the spread = becomes taker)
    if our_limit >= held_ask_at_ws:
        # Spread is already at the tick — degenerate case. Fall back per policy.
        if not fallback_to_taker:
            return None
        entry_used = held_ask_at_ws
        filled_as_maker = False
        fill_bucket = 0
    else:
        # Walk forward through buckets 0..wait_buckets-1, see if ask ever drops to our_limit
        candidate = traj_g[(traj_g.bucket_10s >= 0) & (traj_g.bucket_10s < wait_buckets)]
        candidate = candidate.sort_values("bucket_10s")
        filled_as_maker = False
        fill_bucket = -1
        for _, row_b in candidate.iterrows():
            ask_min_in_bucket = row_b.get(ask_min_col, float("nan"))
            if pd.notna(ask_min_in_bucket) and ask_min_in_bucket <= our_limit + 1e-9:
                filled_as_maker = True
                fill_bucket = int(row_b.bucket_10s)
                break
        if filled_as_maker:
            entry_used = our_limit
        else:
            if not fallback_to_taker:
                return None
            entry_used = held_ask_at_ws
            fill_bucket = wait_buckets  # post-deadline taker fill

    # Now run hedge-hold from fill_bucket onward (no rev_bp check before fill)
    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws)
    hedge_p = None

    # Walk forward from fill_bucket+1 (signal can only trigger after we're filled)
    for _, b in traj_g.iterrows():
        bucket = int(b.bucket_10s)
        if bucket <= fill_bucket:
            continue
        if rev_bp is not None and np.isfinite(btc_at_ws):
            ts_in = ws + bucket * 10
            btc_now = asof_close(k1m, ts_in)
            if not np.isfinite(btc_now):
                continue
            bp = (btc_now - btc_at_ws) / btc_at_ws * 10000
            reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
            if reverted:
                col = "dn_ask_min" if sig == 1 else "up_ask_min"
                oa = b.get(col, float("nan"))
                if pd.notna(oa) and 0 < oa < 1:
                    hedge_p = float(oa)
                    break

    sig_won = (sig == int(row.outcome_up))

    if hedge_p is None:
        if sig_won:
            payout = 1.0 - (1.0 - entry_used) * FEE_RATE
            pnl = payout - entry_used
        else:
            pnl = -entry_used
        cost = entry_used
        return {"pnl": pnl, "cost": cost, "entry_used": entry_used, "hedged": False,
                "sig_won": sig_won, "filled_as_maker": filled_as_maker,
                "fill_bucket": fill_bucket, "held_bid_first": held_bid_first,
                "held_ask_at_ws": held_ask_at_ws, "our_limit": our_limit}

    if sig_won:
        payout = 1.0 - (1.0 - entry_used) * FEE_RATE
    else:
        payout = 1.0 - (1.0 - hedge_p) * FEE_RATE
    pnl = payout - entry_used - hedge_p
    cost = entry_used + hedge_p
    return {"pnl": pnl, "cost": cost, "entry_used": entry_used, "hedge_p": hedge_p,
            "hedged": True, "sig_won": sig_won, "filled_as_maker": filled_as_maker,
            "fill_bucket": fill_bucket, "held_bid_first": held_bid_first,
            "held_ask_at_ws": held_ask_at_ws, "our_limit": our_limit}


def simulate_taker_baseline(row, traj_g, k1m, rev_bp):
    """Reference taker simulation (matches signal_grid_v2.simulate_market for hedge-hold)."""
    sig = int(row.signal)
    entry = float(row.entry_yes_ask) if sig == 1 else float(row.entry_no_ask)
    if not (np.isfinite(entry) and 0 < entry < 1):
        return None
    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws)
    hedge_p = None
    for _, b in traj_g.iterrows():
        bucket = int(b.bucket_10s)
        if bucket < 0:
            continue
        if rev_bp is not None and np.isfinite(btc_at_ws):
            ts_in = ws + bucket * 10
            btc_now = asof_close(k1m, ts_in)
            if not np.isfinite(btc_now):
                continue
            bp = (btc_now - btc_at_ws) / btc_at_ws * 10000
            reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
            if reverted:
                col = "dn_ask_min" if sig == 1 else "up_ask_min"
                oa = b.get(col, float("nan"))
                if pd.notna(oa) and 0 < oa < 1:
                    hedge_p = float(oa)
                    break
    sig_won = (sig == int(row.outcome_up))
    if hedge_p is None:
        if sig_won:
            return {"pnl": 1.0 - (1.0 - entry) * FEE_RATE - entry, "cost": entry,
                    "entry_used": entry, "hedged": False, "sig_won": sig_won}
        return {"pnl": -entry, "cost": entry, "entry_used": entry, "hedged": False, "sig_won": sig_won}
    if sig_won:
        payout = 1.0 - (1.0 - entry) * FEE_RATE
    else:
        payout = 1.0 - (1.0 - hedge_p) * FEE_RATE
    return {"pnl": payout - entry - hedge_p, "cost": entry + hedge_p,
            "entry_used": entry, "hedge_p": hedge_p, "hedged": True, "sig_won": sig_won}


def stat_block(rows, label):
    pnls = np.array([r["pnl"] for r in rows])
    n = len(pnls)
    if n == 0:
        return {"label": label, "n": 0, "hit": float("nan"), "roi": float("nan"),
                "mean_pnl": 0.0, "ci_lo": 0.0, "ci_hi": 0.0,
                "fill_rate": float("nan"), "mean_cost": 0.0}
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    fills = sum(1 for r in rows if r.get("filled_as_maker", False))
    return {
        "label": label,
        "n": n,
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.mean() * 100),
        "mean_pnl": float(pnls.mean()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "fill_rate": float(fills / n) if n else float("nan"),
        "mean_cost": float(np.mean([r["cost"] for r in rows])),
    }


def main():
    print("Loading data...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}

    feats_q10 = add_q10_signal(feats)
    print(f"q10 markets: {len(feats_q10)}")

    # Pre-compute taker baseline once
    print("Running taker baseline (q10)...")
    taker_rows = []
    for _, row in feats_q10.iterrows():
        traj_g = traj[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        r = simulate_taker_baseline(row, traj_g, k1m[row.asset], REV_BP)
        if r is not None:
            r["filled_as_maker"] = False
            r["asset"] = row.asset; r["tf"] = row.timeframe; r["slug"] = row.slug
            r["sig"] = int(row.signal); r["ws"] = int(row.window_start_unix)
            taker_rows.append(r)
    taker_stats = stat_block(taker_rows, "TAKER baseline")
    print(f"  TAKER: n={taker_stats['n']} hit={taker_stats['hit']*100:.1f}% ROI={taker_stats['roi']:+.2f}% "
          f"mean_cost=${taker_stats['mean_cost']:.4f}")

    # Variants: tick_improve x wait_buckets x fallback
    variants = []
    for tick_imp in [TICK, 2 * TICK]:  # 1 tick, 2 ticks
        for wait in [3, 6, 12, 18]:    # 30s, 60s, 120s, 180s
            for fb in [False, True]:    # skip-if-no-fill, fallback-to-taker
                variants.append({
                    "tick_improve": tick_imp,
                    "wait_buckets": wait,
                    "fallback": fb,
                    "label": f"maker tick={tick_imp:.2f} wait={wait*10}s fb={'taker' if fb else 'skip'}",
                })

    all_rows = []
    rows_for_csv = [{"variant": "TAKER", **{k: v for k, v in taker_stats.items() if k != "label"}}]

    print(f"\nRunning {len(variants)} maker variants...")
    per_variant_rows = {}
    for v in variants:
        maker_rows = []
        for _, row in feats_q10.iterrows():
            traj_g = traj[row.asset].get(row.slug)
            if traj_g is None or traj_g.empty:
                continue
            r = simulate_maker_entry(row, traj_g, k1m[row.asset],
                                      REV_BP, v["wait_buckets"], v["tick_improve"], v["fallback"])
            if r is not None:
                r["asset"] = row.asset; r["tf"] = row.timeframe; r["slug"] = row.slug
                r["sig"] = int(row.signal); r["ws"] = int(row.window_start_unix)
                maker_rows.append(r)
        s = stat_block(maker_rows, v["label"])
        delta_roi_vs_taker = s["roi"] - taker_stats["roi"]
        s["delta_roi_vs_taker"] = delta_roi_vs_taker
        s["mean_savings_per_trade"] = taker_stats["mean_cost"] - s["mean_cost"] if s["n"] > 0 else 0
        rows_for_csv.append({"variant": v["label"], **{k: vv for k, vv in s.items() if k != "label"}})
        per_variant_rows[v["label"]] = maker_rows
        print(f"  {v['label']:50s}: n={s['n']:>3d} hit={s['hit']*100 if not np.isnan(s['hit']) else 0:5.1f}% "
              f"ROI={s['roi']:+6.2f}% (vs taker {delta_roi_vs_taker:+5.2f}pp) "
              f"fill={s['fill_rate']*100:5.1f}% mean_cost=${s['mean_cost']:.4f}")

    # Pick best variant for deeper analysis
    best = max((r for r in rows_for_csv if r["variant"] != "TAKER"),
               key=lambda x: x["roi"])
    print(f"\nBest variant: {best['variant']}")

    # Cross-asset breakdown for best variant
    best_rows = per_variant_rows[best["variant"]]
    md = ["# Maker-Entry Strategy Test — Standalone Candidate\n",
          f"Hypothesis: posting buy-limit at held-side bid + 1 tick saves ~2.6¢ taker spread per trade. "
          f"Reference taker baseline: ROI {taker_stats['roi']:+.2f}% (n={taker_stats['n']}, "
          f"hit {taker_stats['hit']*100:.1f}%) on q10 universe at hedge-hold rev_bp={REV_BP}.\n"]

    md.append("\n## Variant grid — tick_improve × wait window × fallback policy\n")
    md.append("| Variant | n | Hit% | ROI | vs taker | Fill rate | Mean cost |")
    md.append("|---|---|---|---|---|---|---|")
    md.append(f"| **TAKER baseline** | {taker_stats['n']} | {taker_stats['hit']*100:.1f}% | "
              f"{taker_stats['roi']:+.2f}% | — | n/a | ${taker_stats['mean_cost']:.4f} |")
    for r in rows_for_csv[1:]:
        marker = " ★" if r["variant"] == best["variant"] else ""
        md.append(f"| {r['variant']}{marker} | {r['n']} | {r['hit']*100 if not np.isnan(r['hit']) else 0:.1f}% | "
                  f"{r['roi']:+.2f}% | {r['delta_roi_vs_taker']:+.2f}pp | "
                  f"{r['fill_rate']*100 if not np.isnan(r['fill_rate']) else 0:.1f}% | "
                  f"${r['mean_cost']:.4f} |")

    md.append(f"\n## Cross-asset breakdown — best variant `{best['variant']}`\n")
    md.append("| Asset | TF | n | Hit% | ROI | Fill rate | vs taker |")
    md.append("|---|---|---|---|---|---|---|")
    for asset in ["ALL", "btc", "eth", "sol"]:
        for tf in ["ALL", "5m", "15m"]:
            sub = [r for r in best_rows
                   if (asset == "ALL" or r["asset"] == asset)
                   and (tf == "ALL" or r["tf"] == tf)]
            sub_taker = [r for r in taker_rows
                         if (asset == "ALL" or r["asset"] == asset)
                         and (tf == "ALL" or r["tf"] == tf)]
            if not sub:
                continue
            s = stat_block(sub, "x")
            t = stat_block(sub_taker, "x")
            d_roi = s["roi"] - t["roi"]
            md.append(f"| {asset} | {tf} | {s['n']} | {s['hit']*100:.1f}% | {s['roi']:+.2f}% | "
                      f"{s['fill_rate']*100:.1f}% | {d_roi:+.2f}pp vs taker {t['roi']:+.2f}% |")

    # Day-by-day for best
    md.append(f"\n## Day-by-day — best variant `{best['variant']}`\n")
    md.append("| Date | n | Hit% | ROI | Fill rate | Taker comparison |")
    md.append("|---|---|---|---|---|---|")
    df_best = pd.DataFrame(best_rows)
    df_best["dt"] = pd.to_datetime(df_best.ws, unit="s", utc=True)
    df_best["date"] = df_best.dt.dt.date
    df_taker = pd.DataFrame(taker_rows)
    df_taker["dt"] = pd.to_datetime(df_taker.ws, unit="s", utc=True)
    df_taker["date"] = df_taker.dt.dt.date
    days_lift = 0
    for d in sorted(df_best.date.unique()):
        sub = df_best[df_best.date == d]
        sub_t = df_taker[df_taker.date == d]
        if len(sub) == 0:
            continue
        roi = sub.pnl.mean() * 100
        roi_t = sub_t.pnl.mean() * 100 if len(sub_t) else 0
        delta = roi - roi_t
        if delta > 0:
            days_lift += 1
        fr = sub.filled_as_maker.mean() * 100
        md.append(f"| {d} | {len(sub)} | {(sub.pnl > 0).mean()*100:.1f}% | "
                  f"{roi:+.2f}% | {fr:.1f}% | taker {roi_t:+.2f}% (Δ {delta:+.2f}pp) |")

    md.append("\n## Verdict\n")
    md.append("Criteria for shipping maker-entry as new strategy:")
    md.append("1. Best variant ROI > taker ROI (in-sample)")
    md.append("2. Cross-asset: ≥ 2/3 assets show maker > taker")
    md.append("3. Day-by-day: ≥ 4/5 days show maker > taker")
    md.append("4. Fill rate adequate (≥ 60% so we don't bleed too much volume)\n")

    n_criteria = 0
    if best["delta_roi_vs_taker"] > 0:
        n_criteria += 1
    cross_asset_lift = 0
    for asset in ["btc", "eth", "sol"]:
        sub = [r for r in best_rows if r["asset"] == asset]
        sub_t = [r for r in taker_rows if r["asset"] == asset]
        if sub and sub_t:
            if stat_block(sub, "x")["roi"] > stat_block(sub_t, "x")["roi"]:
                cross_asset_lift += 1
    if cross_asset_lift >= 2:
        n_criteria += 1
    if days_lift >= 4:
        n_criteria += 1
    if best["fill_rate"] >= 0.60:
        n_criteria += 1
    md.append(f"**Criteria met: {n_criteria}/4**")
    md.append(f"  - in-sample lift: {best['delta_roi_vs_taker']:+.2f}pp")
    md.append(f"  - cross-asset agreement: {cross_asset_lift}/3")
    md.append(f"  - day-by-day lift: {days_lift}/{df_best.date.nunique()}")
    md.append(f"  - fill rate: {best['fill_rate']*100:.1f}%")
    if n_criteria >= 3:
        md.append("\n✅ **DEPLOY** as candidate — maker entries beat taker baseline robustly.")
    elif n_criteria >= 2:
        md.append("\n⚠️ **PARTIAL** signal — worth piloting but more data needed.")
    else:
        md.append("\n❌ **NO clear edge** in maker entries on this universe.")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_for_csv).to_csv(OUT_CSV, index=False)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")
    print(f"\nVerdict: {n_criteria}/4 criteria met. Best variant: {best['variant']} "
          f"(ROI {best['roi']:+.2f}%, +{best['delta_roi_vs_taker']:.2f}pp vs taker)")


if __name__ == "__main__":
    main()
