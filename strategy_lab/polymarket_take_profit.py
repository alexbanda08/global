"""
polymarket_take_profit.py — STANDALONE: take-profit exit at fixed target return.

Hypothesis (user idea):
  When signal fires and price moves OUR way, lock in T% profit by selling held side
  at entry * (1 + T) instead of holding to natural resolution.
  Reduces tail risk: caps upside but eliminates "won the signal but resolution flipped" losses.

Mechanics:
  1. Entry: buy held side at entry_yes_ask (or entry_no_ask if sig=DOWN)  — taker baseline
  2. TP: place SELL limit at S_target = entry * (1 + T)
     - Filled when our_held_bid_max[bucket] >= S_target (someone bids at our level)
  3. Combined with rev_bp=5 hedge-hold: if Binance reverses before TP fills, hedge as before
  4. Otherwise: hold to natural resolution

Variants tested:
  baseline_revbp      : rev_bp=5 hedge-hold only (current locked baseline)
  tp_T_only           : TP at T% only, no rev_bp stop. Hold to resolution if no TP fire.
  tp_T_plus_revbp     : TP at T% AND rev_bp=5 hedge-hold (whichever fires first)

Targets tested: T ∈ {5%, 10%, 15%, 20%, 25%}

Outputs:
  results/polymarket/take_profit.csv
  reports/POLYMARKET_TAKE_PROFIT.md
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

OUT_CSV = HERE / "results" / "polymarket" / "take_profit.csv"
OUT_MD = HERE / "reports" / "POLYMARKET_TAKE_PROFIT.md"


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


def simulate_with_tp(row, traj_g, k1m, rev_bp, tp_target):
    """
    rev_bp: int or None (None = no rev_bp stop)
    tp_target: float or None — gross return target (e.g. 0.15 = sell at entry*1.15). None = no TP.
    Returns dict with pnl, exit_kind ∈ {tp_fill, revbp_hedge, natural_resolution}, ...
    """
    sig = int(row.signal)
    if sig == 1:
        entry = float(row.entry_yes_ask) if pd.notna(row.entry_yes_ask) else float("nan")
        held_bid_max_col = "up_bid_max"
        other_ask_min_col = "dn_ask_min"
    else:
        entry = float(row.entry_no_ask) if pd.notna(row.entry_no_ask) else float("nan")
        held_bid_max_col = "dn_bid_max"
        other_ask_min_col = "up_ask_min"
    if not (np.isfinite(entry) and 0 < entry < 1):
        return None

    s_target = entry * (1 + tp_target) if tp_target is not None else float("inf")
    # Cap S_target at 0.99 (can't sell above $1)
    s_target = min(s_target, 0.99)

    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws) if rev_bp is not None else float("nan")

    exit_kind = "natural_resolution"
    exit_price = None         # for direct sell (TP)
    hedge_other_entry = None  # for hedge-hold (rev_bp)

    for _, b in traj_g.iterrows():
        bucket = int(b.bucket_10s)
        if bucket < 0:
            continue

        # ---- TP check (best case in bucket) ----
        if tp_target is not None:
            held_bid_max = b.get(held_bid_max_col, float("nan"))
            if pd.notna(held_bid_max) and float(held_bid_max) >= s_target:
                exit_price = s_target  # we sold AT our limit (no slippage above)
                exit_kind = "tp_fill"
                break

        # ---- rev_bp check ----
        if rev_bp is not None and np.isfinite(btc_at_ws):
            ts_in = ws + bucket * 10
            btc_now = asof_close(k1m, ts_in)
            if not np.isfinite(btc_now):
                continue
            bp = (btc_now - btc_at_ws) / btc_at_ws * 10000
            reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
            if reverted:
                oa = b.get(other_ask_min_col, float("nan"))
                if pd.notna(oa) and 0 < oa < 1:
                    hedge_other_entry = float(oa)
                    exit_kind = "revbp_hedge"
                    break

    # ---- Resolve PnL ----
    sig_won = (sig == int(row.outcome_up))

    if exit_kind == "tp_fill":
        # Sold at exit_price
        gross = exit_price - entry
        fee = gross * FEE_RATE if gross > 0 else 0  # 2% on gross profit
        pnl = gross - fee
        cost = entry
        return {"pnl": pnl, "cost": cost, "entry": entry, "exit_price": exit_price,
                "exit_kind": exit_kind, "sig_won": sig_won}

    if exit_kind == "revbp_hedge":
        # Hedge-hold: total cost = entry + hedge, payout = $1 minus fee on winning leg's profit
        if sig_won:
            payout = 1.0 - (1.0 - entry) * FEE_RATE
        else:
            payout = 1.0 - (1.0 - hedge_other_entry) * FEE_RATE
        cost = entry + hedge_other_entry
        pnl = payout - cost
        return {"pnl": pnl, "cost": cost, "entry": entry,
                "hedge_other_entry": hedge_other_entry,
                "exit_kind": exit_kind, "sig_won": sig_won}

    # Natural resolution
    if sig_won:
        payout = 1.0 - (1.0 - entry) * FEE_RATE
        pnl = payout - entry
    else:
        pnl = -entry
    return {"pnl": pnl, "cost": entry, "entry": entry,
            "exit_kind": exit_kind, "sig_won": sig_won}


def stat_block(rows):
    pnls = np.array([r["pnl"] for r in rows])
    n = len(pnls)
    if n == 0:
        return {"n": 0, "hit": float("nan"), "roi": float("nan"),
                "ci_lo": 0, "ci_hi": 0, "tp_rate": 0, "revbp_rate": 0,
                "natural_rate": 0, "mean_cost": 0}
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    tp_count = sum(1 for r in rows if r["exit_kind"] == "tp_fill")
    rb_count = sum(1 for r in rows if r["exit_kind"] == "revbp_hedge")
    nat_count = sum(1 for r in rows if r["exit_kind"] == "natural_resolution")
    return {
        "n": n,
        "hit": float((pnls > 0).mean()),
        "roi": float(pnls.mean() * 100),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "tp_rate": float(tp_count / n),
        "revbp_rate": float(rb_count / n),
        "natural_rate": float(nat_count / n),
        "mean_cost": float(np.mean([r["cost"] for r in rows])),
    }


def main():
    print("Loading...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}
    feats_q10 = add_q10_signal(feats)
    print(f"q10 markets: {len(feats_q10)}")

    targets = [0.05, 0.10, 0.15, 0.20, 0.25, 0.40, 0.60, 0.80, 1.00, 1.50]

    variants = [
        ("baseline_revbp", REV_BP, None),  # current locked baseline
    ]
    for t in targets:
        variants.append((f"tp_{int(t*100)}pct_only", None, t))           # TP-only
        variants.append((f"tp_{int(t*100)}pct_plus_revbp", REV_BP, t))   # TP + rev_bp combined

    rows_csv = []
    per_variant_rows = {}

    for label, rev_bp, tp in variants:
        sim_rows = []
        for _, row in feats_q10.iterrows():
            traj_g = traj[row.asset].get(row.slug)
            if traj_g is None or traj_g.empty:
                continue
            r = simulate_with_tp(row, traj_g, k1m[row.asset], rev_bp, tp)
            if r is not None and np.isfinite(r["pnl"]):
                r["asset"] = row.asset
                r["tf"] = row.timeframe
                r["slug"] = row.slug
                r["sig"] = int(row.signal)
                r["ws"] = int(row.window_start_unix)
                sim_rows.append(r)
        per_variant_rows[label] = sim_rows
        s = stat_block(sim_rows)
        rows_csv.append({"variant": label, **s})
        print(f"  {label:30s}: n={s['n']:>3d} hit={s['hit']*100:5.1f}% "
              f"ROI={s['roi']:+6.2f}% "
              f"TP={s['tp_rate']*100:4.1f}% revbp={s['revbp_rate']*100:4.1f}% nat={s['natural_rate']*100:4.1f}%")

    baseline = next(r for r in rows_csv if r["variant"] == "baseline_revbp")
    others = [r for r in rows_csv if r["variant"] != "baseline_revbp"]
    for r in others:
        r["lift_vs_baseline"] = r["roi"] - baseline["roi"]
    others.sort(key=lambda x: x["roi"], reverse=True)
    best = others[0]

    print(f"\nBaseline (revbp only): ROI={baseline['roi']:+.2f}%")
    print(f"Best: {best['variant']}: ROI={best['roi']:+.2f}% (lift {best['lift_vs_baseline']:+.2f}pp)")

    # Cross-asset for best
    best_rows = per_variant_rows[best["variant"]]
    base_rows = per_variant_rows["baseline_revbp"]

    md = ["# Take-Profit Strategy Test\n",
          f"q10 universe (n={len(feats_q10)}), hedge-hold rev_bp={REV_BP} as baseline.",
          f"TP targets tested: {[int(t*100) for t in targets]}%. ",
          f"TP execution: sell held side at `entry * (1 + T)` when held_bid_max reaches the target in any bucket.",
          f"\n## Variant grid\n",
          "| Variant | n | Hit% | ROI | vs baseline | TP fire | revbp fire | natural | mean cost |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows_csv:
        is_baseline = r["variant"] == "baseline_revbp"
        marker = " (baseline)" if is_baseline else (" ★" if r["variant"] == best["variant"] else "")
        lift = r.get("lift_vs_baseline", 0.0) if not is_baseline else 0
        md.append(f"| {r['variant']}{marker} | {r['n']} | "
                  f"{r['hit']*100:.1f}% | {r['roi']:+.2f}% | "
                  f"{lift:+.2f}pp | "
                  f"{r['tp_rate']*100:.1f}% | "
                  f"{r['revbp_rate']*100:.1f}% | "
                  f"{r['natural_rate']*100:.1f}% | "
                  f"${r['mean_cost']:.4f} |")

    md.append(f"\n## Cross-asset × timeframe — best variant `{best['variant']}` vs baseline\n")
    md.append("| Asset | TF | n | Hit% | best ROI | baseline ROI | Δ |")
    md.append("|---|---|---|---|---|---|---|")
    cross_lifts = {}
    for asset in ["ALL", "btc", "eth", "sol"]:
        for tf in ["ALL", "5m", "15m"]:
            sub = [r for r in best_rows
                   if (asset == "ALL" or r["asset"] == asset)
                   and (tf == "ALL" or r["tf"] == tf)]
            sub_b = [r for r in base_rows
                     if (asset == "ALL" or r["asset"] == asset)
                     and (tf == "ALL" or r["tf"] == tf)]
            if not sub or not sub_b:
                continue
            s = stat_block(sub)
            t = stat_block(sub_b)
            md.append(f"| {asset} | {tf} | {s['n']} | {s['hit']*100:.1f}% | "
                      f"{s['roi']:+.2f}% | {t['roi']:+.2f}% | "
                      f"{s['roi']-t['roi']:+.2f}pp |")
            cross_lifts[(asset, tf)] = s["roi"] - t["roi"]

    # Day-by-day for best
    md.append(f"\n## Day-by-day — best variant `{best['variant']}` vs baseline\n")
    md.append("| Date | n | best ROI | baseline ROI | Δ |")
    md.append("|---|---|---|---|---|")
    df_best = pd.DataFrame(best_rows)
    df_best["dt"] = pd.to_datetime(df_best.ws, unit="s", utc=True)
    df_best["date"] = df_best.dt.dt.date
    df_base = pd.DataFrame(base_rows)
    df_base["dt"] = pd.to_datetime(df_base.ws, unit="s", utc=True)
    df_base["date"] = df_base.dt.dt.date
    days_lift = 0
    for d in sorted(df_best.date.unique()):
        sub = df_best[df_best.date == d]
        sub_b = df_base[df_base.date == d]
        if len(sub) == 0:
            continue
        roi = sub.pnl.mean() * 100
        roi_b = sub_b.pnl.mean() * 100 if len(sub_b) else 0
        d_pp = roi - roi_b
        if d_pp > 0:
            days_lift += 1
        md.append(f"| {d} | {len(sub)} | {roi:+.2f}% | {roi_b:+.2f}% | {d_pp:+.2f}pp |")

    # PnL distribution for best
    md.append(f"\n## PnL distribution — best variant `{best['variant']}`\n")
    md.append(f"Compares pnl distribution between best and baseline. Tail behavior matters.\n")
    pnls_best = np.array([r["pnl"] for r in best_rows])
    pnls_base = np.array([r["pnl"] for r in base_rows])
    md.append(f"| Stat | best | baseline |")
    md.append(f"|---|---|---|")
    md.append(f"| n | {len(pnls_best)} | {len(pnls_base)} |")
    md.append(f"| mean PnL | {pnls_best.mean():+.4f} | {pnls_base.mean():+.4f} |")
    md.append(f"| median PnL | {np.median(pnls_best):+.4f} | {np.median(pnls_base):+.4f} |")
    md.append(f"| stdev | {pnls_best.std():.4f} | {pnls_base.std():.4f} |")
    md.append(f"| min PnL | {pnls_best.min():+.4f} | {pnls_base.min():+.4f} |")
    md.append(f"| max PnL | {pnls_best.max():+.4f} | {pnls_base.max():+.4f} |")
    md.append(f"| % winning trades | {(pnls_best > 0).mean()*100:.1f}% | {(pnls_base > 0).mean()*100:.1f}% |")
    md.append(f"| Sharpe (mean/std) | {pnls_best.mean()/pnls_best.std():.3f} | {pnls_base.mean()/pnls_base.std():.3f} |")

    # Verdict
    md.append("\n## Verdict\n")
    n_criteria = 0
    if best["lift_vs_baseline"] > 0:
        n_criteria += 1
    cross_lift_count = sum(1 for asset in ["btc", "eth", "sol"]
                           if cross_lifts.get((asset, "ALL"), 0) > 0)
    if cross_lift_count >= 2:
        n_criteria += 1
    if days_lift >= 4:
        n_criteria += 1
    sharpe_best = pnls_best.mean() / pnls_best.std()
    sharpe_base = pnls_base.mean() / pnls_base.std()
    if sharpe_best > sharpe_base:
        n_criteria += 1
    md.append(f"**Criteria:**")
    md.append(f"  1. Best variant ROI > baseline: {'✅' if best['lift_vs_baseline'] > 0 else '❌'} "
              f"({best['lift_vs_baseline']:+.2f}pp)")
    md.append(f"  2. Cross-asset agreement (≥2/3): {'✅' if cross_lift_count >= 2 else '❌'} "
              f"({cross_lift_count}/3)")
    md.append(f"  3. Day-by-day stability (≥4/5): {'✅' if days_lift >= 4 else '❌'} "
              f"({days_lift}/{df_best.date.nunique()})")
    md.append(f"  4. Sharpe improved: {'✅' if sharpe_best > sharpe_base else '❌'} "
              f"({sharpe_best:.3f} vs {sharpe_base:.3f})")
    md.append(f"\n**Score: {n_criteria}/4**")
    if n_criteria >= 3:
        md.append("\n✅ **Worth forward-walk validation. Likely deploy candidate.**")
    elif n_criteria >= 2:
        md.append("\n⚠️ **Mixed.** Forward-walk to clarify.")
    else:
        md.append("\n❌ **No clear edge.** TP at this target doesn't beat the rev_bp baseline.")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_csv).to_csv(OUT_CSV, index=False)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
