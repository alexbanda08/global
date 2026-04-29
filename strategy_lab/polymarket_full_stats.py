"""
polymarket_full_stats.py — Comprehensive performance stats for the
recommended strategy variants. Computes per-strategy:
  • n trades, win rate, total PnL
  • mean / median / max / min PnL per trade
  • std dev, Sharpe-like ratio (mean / std)
  • drawdown (running min)
  • % of trades that hedged (rev_bp triggered)
  • % of trades that won as direct vs hedged
  • per-asset, per-timeframe breakdowns
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from polymarket_signal_grid_v2 import (
    load_features, load_trajectories, load_klines_1m,
    add_q20_signal, add_full_signal,
    asof_close, FEE_RATE,
)

OUT_MD = HERE / "reports" / "POLYMARKET_FULL_STATS.md"
ASSETS = ["btc", "eth", "sol"]
RNG = np.random.default_rng(42)


def simulate_with_diag(row, traj_g, k1m, rev_bp, hedge_hold=True):
    """Per-market PnL plus diagnostic flags (hedged?, won?, when triggered?)."""
    sig = int(row.signal)
    entry = float(row.entry_yes_ask if sig == 1 else row.entry_no_ask)
    if not np.isfinite(entry) or entry <= 0 or entry >= 1:
        return None

    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws)

    hedge_other_entry = None
    hedge_bucket = None
    for _, b in traj_g.iterrows():
        bucket = int(b.bucket_10s)
        if bucket < 0:
            continue
        if rev_bp is not None and np.isfinite(btc_at_ws):
            ts_in_bucket = ws + bucket * 10
            btc_now = asof_close(k1m, ts_in_bucket)
            if np.isfinite(btc_now):
                bp = (btc_now - btc_at_ws) / btc_at_ws * 10000
                reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
                if reverted and hedge_hold:
                    other_ask_col = "dn_ask_min" if sig == 1 else "up_ask_min"
                    other_ask = b[other_ask_col]
                    if pd.notna(other_ask) and 0 < other_ask < 1:
                        hedge_other_entry = float(other_ask)
                        hedge_bucket = bucket
                        break

    outcome = int(row.outcome_up)
    sig_won = (sig == outcome)
    if hedge_other_entry is not None:
        if sig_won:
            payout = 1.0 - (1.0 - entry) * FEE_RATE
        else:
            payout = 1.0 - (1.0 - hedge_other_entry) * FEE_RATE
        pnl = payout - entry - hedge_other_entry
        return {
            "pnl": pnl, "hedged": True, "hedge_bucket": hedge_bucket,
            "sig_won": sig_won, "entry": entry, "other_entry": hedge_other_entry,
        }

    # No hedge: hold to resolution
    if sig_won:
        gross = 1.0 - entry
        fee = (1.0 - entry) * FEE_RATE
        pnl = gross - fee
    else:
        pnl = -entry
    return {
        "pnl": pnl, "hedged": False, "hedge_bucket": None,
        "sig_won": sig_won, "entry": entry, "other_entry": None,
    }


def stats_block(pnls: np.ndarray, label: str = "") -> dict:
    if len(pnls) == 0:
        return {"label":label,"n":0}
    boot = RNG.choice(pnls, size=(2000, len(pnls)), replace=True).sum(axis=1)
    cum = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cum)
    drawdown = (cum - running_max).min()
    return {
        "label": label,
        "n": len(pnls),
        "win_rate": float((pnls > 0).mean()),
        "total_pnl": float(pnls.sum()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "mean_pnl": float(pnls.mean()),
        "median_pnl": float(np.median(pnls)),
        "max_pnl": float(pnls.max()),
        "min_pnl": float(pnls.min()),
        "std_pnl": float(pnls.std(ddof=1)) if len(pnls) > 1 else 0.0,
        "sharpe_like": float(pnls.mean() / pnls.std(ddof=1)) if len(pnls) > 1 and pnls.std() > 0 else 0.0,
        "max_dd": float(drawdown),
        "roi_pct": float(pnls.sum() / max(len(pnls),1) * 100),
    }


def fmt_stats_row(s: dict) -> str:
    if s["n"] == 0:
        return f"| {s['label']} | 0 | — | — | — | — | — | — | — | — |"
    return (
        f"| {s['label']} | {s['n']} | {s['win_rate']*100:.1f}% | "
        f"${s['total_pnl']:+.2f} | [${s['ci_lo']:+.0f}, ${s['ci_hi']:+.0f}] | "
        f"${s['mean_pnl']:+.4f} | ${s['median_pnl']:+.4f} | "
        f"${s['min_pnl']:+.3f} | ${s['max_dd']:+.2f} | "
        f"{s['sharpe_like']:.3f} | {s['roi_pct']:+.2f}% |"
    )


def main():
    print("Loading...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj_by_asset = {a: load_trajectories(a) for a in ASSETS}
    k1m_by_asset  = {a: load_klines_1m(a)   for a in ASSETS}

    feats_q20  = add_q20_signal(feats)
    feats_full = add_full_signal(feats)

    REV_BP = 5

    md = ["# Polymarket Strategy — Full Win Rate & Performance Report\n",
          f"Universe: 5,742 markets across BTC/ETH/SOL (5m + 15m), Apr 22-27, 2026.\n",
          f"Strategy: `sig_ret5m` (sign of Binance close ratio over prior 5min) "
          f"with hedge-hold exit at `rev_bp={REV_BP}`. Fee 2% on winning leg payout.\n"]

    # Run all 4 main universes + per-asset breakdowns + the chosen sniper config
    universes = []
    for sig_label, sig_df in [("full", feats_full), ("q20", feats_q20)]:
        for tf in ["5m", "15m"]:
            for asset_filter in [None, "btc", "eth", "sol"]:
                sub = sig_df[sig_df.timeframe == tf]
                if asset_filter is not None:
                    sub = sub[sub.asset == asset_filter]
                if len(sub) == 0:
                    continue
                universes.append((sig_label, tf, asset_filter or "ALL", sub))

    all_rows = []  # for hedge-rate aggregation
    for sig_label, tf, asset_lbl, sub in universes:
        # Run simulation collecting diagnostics
        results = []
        for _, row in sub.iterrows():
            traj_g = traj_by_asset[row.asset].get(row.slug)
            if traj_g is None or traj_g.empty:
                continue
            k1m = k1m_by_asset[row.asset]
            r = simulate_with_diag(row, traj_g, k1m, rev_bp=REV_BP, hedge_hold=True)
            if r is None:
                continue
            r["sig_label"] = sig_label
            r["tf"] = tf
            r["asset_lbl"] = asset_lbl
            all_rows.append(r)
            results.append(r)
        if not results:
            continue

        pnls = np.array([r["pnl"] for r in results])
        hedged = np.array([r["hedged"] for r in results])
        sig_won = np.array([r["sig_won"] for r in results])

        s_all = stats_block(pnls, f"{asset_lbl}")
        s_hedged = stats_block(pnls[hedged], f"{asset_lbl} (hedged subset)")
        s_unhedged = stats_block(pnls[~hedged], f"{asset_lbl} (unhedged subset)")

        n_total = len(pnls)
        n_hedge = int(hedged.sum())
        n_sig_correct = int(sig_won.sum())
        n_sig_correct_unhedged = int((sig_won & ~hedged).sum())
        n_sig_correct_hedged = int((sig_won & hedged).sum())

        if (sig_label, tf) == ("q20", "15m") and asset_lbl == "ALL":
            md.append("\n## Headline Strategy: q20 signal × 15m × ALL assets (Sniper Mode)\n")
        elif asset_lbl == "ALL":
            md.append(f"\n## {sig_label} signal × {tf} × ALL assets\n")
        else:
            continue  # keep main report focused on ALL universes; per-asset in dedicated section below

        md.append(f"- **Total trades**: {n_total}")
        md.append(f"- **Signal hit rate (raw, before hedge)**: {n_sig_correct}/{n_total} = "
                 f"**{n_sig_correct/n_total*100:.1f}%** (this is the baseline directional accuracy)")
        md.append(f"- **Hedge-trigger rate**: {n_hedge}/{n_total} = **{n_hedge/n_total*100:.1f}%** "
                 f"(BTC reversed ≥{REV_BP} bps mid-window)")
        md.append(f"- **Win rate (PnL > 0)**: {(pnls > 0).sum()}/{n_total} = "
                 f"**{(pnls > 0).mean()*100:.1f}%**")
        md.append(f"- **Total PnL** (per $1 stake): **${pnls.sum():+.2f}** "
                 f"[95% CI: ${s_all['ci_lo']:+.0f}, ${s_all['ci_hi']:+.0f}]")
        md.append(f"- **ROI per trade**: **{pnls.sum()/n_total*100:+.2f}%** "
                 f"(mean ${pnls.mean():+.4f} / median ${np.median(pnls):+.4f})")
        md.append(f"- **Worst single trade**: ${pnls.min():+.4f}  |  **Best**: ${pnls.max():+.4f}")
        md.append(f"- **Std dev**: ${pnls.std(ddof=1):.4f}  |  **Sharpe-like**: {pnls.mean()/pnls.std(ddof=1):.3f}")
        md.append(f"- **Max drawdown** (running min): ${s_all['max_dd']:+.2f}")

        md.append(f"\n### Subsetted by hedge state\n")
        md.append("| Subset | n | Win% | Total PnL | Mean/trade | Median/trade |")
        md.append("|---|---|---|---|---|---|")
        if s_unhedged["n"] > 0:
            md.append(f"| **Unhedged** (rode to resolution) | {s_unhedged['n']} | "
                     f"{s_unhedged['win_rate']*100:.1f}% | ${s_unhedged['total_pnl']:+.2f} | "
                     f"${s_unhedged['mean_pnl']:+.4f} | ${s_unhedged['median_pnl']:+.4f} |")
        if s_hedged["n"] > 0:
            md.append(f"| **Hedged** (synthetic close) | {s_hedged['n']} | "
                     f"{s_hedged['win_rate']*100:.1f}% | ${s_hedged['total_pnl']:+.2f} | "
                     f"${s_hedged['mean_pnl']:+.4f} | ${s_hedged['median_pnl']:+.4f} |")

    # Per-asset comparison table
    md.append("\n\n## Per-Asset Breakdown\n")
    md.append("Using `q20` signal at 15m (sniper mode), `rev_bp=5`, hedge-hold.\n")
    md.append("| Asset | n | Hit% | Total PnL | 95% CI | Mean/trade | ROI/bet | Worst | Sharpe |")
    md.append("|---|---|---|---|---|---|---|---|---|")
    for asset in ["btc", "eth", "sol", None]:
        sub_rows = [r for r in all_rows
                    if r["sig_label"] == "q20" and r["tf"] == "15m"
                    and (r["asset_lbl"] == (asset or "ALL"))]
        if not sub_rows:
            continue
        pnls = np.array([r["pnl"] for r in sub_rows])
        s = stats_block(pnls, asset.upper() if asset else "ALL")
        md.append(
            f"| {s['label']} | {s['n']} | {s['win_rate']*100:.1f}% | "
            f"${s['total_pnl']:+.2f} | [${s['ci_lo']:+.0f}, ${s['ci_hi']:+.0f}] | "
            f"${s['mean_pnl']:+.4f} | {s['roi_pct']:+.2f}% | "
            f"${s['min_pnl']:+.3f} | {s['sharpe_like']:.3f} |"
        )

    # Sizing tables
    md.append("\n## Scaled PnL projections (assumes performance holds)\n")
    md.append("Per-trade ROI from the headline sniper cell × N trades × stake size:\n")
    headline = [r for r in all_rows
                if r["sig_label"] == "q20" and r["tf"] == "15m" and r["asset_lbl"] == "ALL"]
    pnls_h = np.array([r["pnl"] for r in headline])
    roi_per_trade = pnls_h.mean()  # per $1
    n_per_5d = len(headline)
    n_per_day = n_per_5d / 5
    n_per_month = n_per_day * 30

    md.append("| Stake size | Trades / day | Expected $/day | Trades / month | Expected $/month |")
    md.append("|---|---|---|---|---|")
    for stake in [1, 5, 10, 25, 100]:
        per_day = roi_per_trade * stake * n_per_day
        per_month = roi_per_trade * stake * n_per_month
        md.append(f"| ${stake} | {n_per_day:.0f} | ${per_day:+.2f} | "
                 f"{n_per_month:.0f} | ${per_month:+.2f} |")

    md.append("\n*These are gross projections from in-sample backtest. Subtract gas (~$0.001/trade) "
             "and any slippage haircut (estimate -10% on per-trade ROI for live execution friction).*\n")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Wrote {OUT_MD}")
    print("\n=== HEADLINE NUMBERS ===")
    pnls_q20_15m = np.array([r["pnl"] for r in all_rows if r["sig_label"]=="q20" and r["tf"]=="15m" and r["asset_lbl"]=="ALL"])
    print(f"q20 15m ALL: n={len(pnls_q20_15m)}, win_rate={(pnls_q20_15m>0).mean()*100:.1f}%, "
          f"total=${pnls_q20_15m.sum():+.2f}, mean=${pnls_q20_15m.mean():+.4f}, "
          f"sharpe={pnls_q20_15m.mean()/pnls_q20_15m.std(ddof=1):.3f}")
    pnls_full_5m = np.array([r["pnl"] for r in all_rows if r["sig_label"]=="full" and r["tf"]=="5m" and r["asset_lbl"]=="ALL"])
    print(f"full 5m ALL: n={len(pnls_full_5m)}, win_rate={(pnls_full_5m>0).mean()*100:.1f}%, "
          f"total=${pnls_full_5m.sum():+.2f}, mean=${pnls_full_5m.mean():+.4f}, "
          f"sharpe={pnls_full_5m.mean()/pnls_full_5m.std(ddof=1):.3f}")


if __name__ == "__main__":
    main()
