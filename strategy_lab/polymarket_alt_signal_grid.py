"""
polymarket_alt_signal_grid.py — Alternative signals × cross-asset × hedge-hold rev_bp=5

The locked baseline is sig_ret5m_q20 + hedge-hold rev_bp=5 (75.8% hit, +20.39% ROI at q20×15m×ALL).
This script tests 8 ALTERNATIVE signal definitions under the SAME exit rule to see if any beats it.

Signals tested:
  S1  sig_ret5m_q20         — locked baseline (control)
  S2  sig_ret5m_q10         — tighter top/bot 10%
  S3  sig_ret5m_q5          — tighter top/bot 5%
  S4  sig_ret5m_thr25bps    — only when |ret_5m| > 25bps
  S5  sig_ret15m_q20        — 15-min return as primary
  S6  sig_ret1h_q20         — 1-hour return as primary
  S7  sig_smartretail_q20   — smart_minus_retail (long-short signal)
  S8  sig_combo_q20         — ret_5m_q20 AND smart_minus_retail agrees
  S9  sig_ret5m_q20_smartretailfilter — ret_5m direction, only when smart_minus_retail not opposing

Outputs:
  results/polymarket/alt_signal_grid.csv
  reports/POLYMARKET_ALT_SIGNAL_GRID.md
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(42)
FEE_RATE = 0.02
ASSETS = ["btc", "eth", "sol"]
REV_BP = 5


def load_features(asset):
    df = pd.read_csv(HERE/"data"/"polymarket"/f"{asset}_features_v3.csv")
    df["asset"] = asset
    return df


def load_trajectories(asset):
    t = pd.read_csv(HERE/"data"/"polymarket"/f"{asset}_trajectories_v3.csv")
    up = t[t.outcome == "Up"].rename(columns={
        "bid_first":"up_bid_first","bid_last":"up_bid_last","bid_min":"up_bid_min","bid_max":"up_bid_max",
        "ask_first":"up_ask_first","ask_last":"up_ask_last","ask_min":"up_ask_min","ask_max":"up_ask_max",
    })[["slug","bucket_10s","window_start_unix",
        "up_bid_first","up_bid_last","up_bid_min","up_bid_max",
        "up_ask_first","up_ask_last","up_ask_min","up_ask_max"]]
    dn = t[t.outcome == "Down"].rename(columns={
        "bid_first":"dn_bid_first","bid_last":"dn_bid_last","bid_min":"dn_bid_min","bid_max":"dn_bid_max",
        "ask_first":"dn_ask_first","ask_last":"dn_ask_last","ask_min":"dn_ask_min","ask_max":"dn_ask_max",
    })[["slug","bucket_10s",
        "dn_bid_first","dn_bid_last","dn_bid_min","dn_bid_max",
        "dn_ask_first","dn_ask_last","dn_ask_min","dn_ask_max"]]
    merged = up.merge(dn, on=["slug","bucket_10s"], how="outer").sort_values(["slug","bucket_10s"])
    return {slug:g.reset_index(drop=True) for slug,g in merged.groupby("slug")}


def load_klines_1m(asset):
    k = pd.read_csv(HERE/"data"/"binance"/f"{asset}_klines_window.csv")
    k1m = k[k.period_id == "1MIN"].copy()
    k1m["ts_s"] = (k1m.time_period_start_us // 1_000_000).astype(int)
    return k1m.sort_values("ts_s").reset_index(drop=True)[["ts_s","price_close"]]


def asof_close(k1m, ts):
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    return float("nan") if idx < 0 else float(k1m.price_close.iloc[idx])


def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Add 9 candidate signals. -1 = no signal."""
    df = df.copy()
    cols = ["sig_ret5m_q20","sig_ret5m_q10","sig_ret5m_q5","sig_ret5m_thr25bps",
            "sig_ret15m_q20","sig_ret1h_q20","sig_smartretail_q20","sig_combo_q20",
            "sig_ret5m_q20_srfilter"]
    for c in cols:
        df[c] = -1

    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            m = (df.asset == asset) & (df.timeframe == tf)
            sub = df[m]
            if len(sub) == 0:
                continue
            ret5 = df.loc[m, "ret_5m"]; ret5_abs = ret5.abs()
            q20_5 = ret5_abs.quantile(0.80)
            q10_5 = ret5_abs.quantile(0.90)
            q5_5  = ret5_abs.quantile(0.95)
            df.loc[m & (ret5_abs >= q20_5) & ret5.notna(), "sig_ret5m_q20"] = (ret5 > 0).astype(int)
            df.loc[m & (ret5_abs >= q10_5) & ret5.notna(), "sig_ret5m_q10"] = (ret5 > 0).astype(int)
            df.loc[m & (ret5_abs >= q5_5)  & ret5.notna(), "sig_ret5m_q5"]  = (ret5 > 0).astype(int)
            df.loc[m & (ret5_abs >= 0.0025) & ret5.notna(), "sig_ret5m_thr25bps"] = (ret5 > 0).astype(int)

            ret15 = df.loc[m, "ret_15m"]; ret15_abs = ret15.abs()
            q20_15 = ret15_abs.quantile(0.80)
            df.loc[m & (ret15_abs >= q20_15) & ret15.notna(), "sig_ret15m_q20"] = (ret15 > 0).astype(int)

            ret1h = df.loc[m, "ret_1h"]; ret1h_abs = ret1h.abs()
            q20_1h = ret1h_abs.quantile(0.80)
            df.loc[m & (ret1h_abs >= q20_1h) & ret1h.notna(), "sig_ret1h_q20"] = (ret1h > 0).astype(int)

            sr = df.loc[m, "smart_minus_retail"]
            sr_hi = sr.quantile(0.90); sr_lo = sr.quantile(0.10)
            sr_extreme = m & ((df.smart_minus_retail >= sr_hi) | (df.smart_minus_retail <= sr_lo))
            df.loc[sr_extreme, "sig_smartretail_q20"] = (df.loc[sr_extreme, "smart_minus_retail"] > 0).astype(int)

            sr_med = df.loc[m, "smart_minus_retail"].median()
            agree_up = (df.sig_ret5m_q20 == 1) & (df.smart_minus_retail > sr_med) & m
            agree_dn = (df.sig_ret5m_q20 == 0) & (df.smart_minus_retail < sr_med) & m
            df.loc[agree_up | agree_dn, "sig_combo_q20"] = df.loc[agree_up | agree_dn, "sig_ret5m_q20"]

            # SR filter: take ret5m_q20 unless smart_minus_retail strongly opposes
            sr_oppose_up = (df.sig_ret5m_q20 == 1) & (df.smart_minus_retail <= sr_lo) & m
            sr_oppose_dn = (df.sig_ret5m_q20 == 0) & (df.smart_minus_retail >= sr_hi) & m
            keep = m & (df.sig_ret5m_q20 != -1) & ~(sr_oppose_up | sr_oppose_dn)
            df.loc[keep, "sig_ret5m_q20_srfilter"] = df.loc[keep, "sig_ret5m_q20"]

    return df


def simulate_market(row, traj_g, k1m, sig_value, rev_bp):
    """Hedge-hold simulator (per-share, matches v2 baseline)."""
    sig = int(sig_value)
    entry = float(row.entry_yes_ask) if sig == 1 else float(row.entry_no_ask)
    if not (np.isfinite(entry) and 0 < entry < 1):
        return None
    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws)
    hedge_other_entry = None
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
                other_ask = b[col]
                if pd.notna(other_ask) and 0 < other_ask < 1:
                    hedge_other_entry = float(other_ask)
                    break
    outcome_up = int(row.outcome_up)
    sig_won = (sig == outcome_up)
    if hedge_other_entry is None:
        if sig_won:
            payout = 1.0 - (1.0 - entry) * FEE_RATE
            return payout - entry
        return -entry
    if sig_won:
        payout = 1.0 - (1.0 - entry) * FEE_RATE
    else:
        payout = 1.0 - (1.0 - hedge_other_entry) * FEE_RATE
    return payout - entry - hedge_other_entry


def run_signal(df: pd.DataFrame, traj: dict, k1m: dict, sig_col: str, rev_bp: int) -> dict:
    sub = df[df[sig_col] != -1]
    pnls = []
    for _, row in sub.iterrows():
        traj_g = traj[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        p = simulate_market(row, traj_g, k1m[row.asset], row[sig_col], rev_bp)
        if p is not None:
            pnls.append(p)
    pnls = np.array(pnls)
    n = len(pnls)
    if n == 0:
        return {"n": 0, "pnl_total": 0.0, "pnl_mean": 0.0, "roi_pct": 0.0,
                "ci_lo": 0.0, "ci_hi": 0.0, "hit": float("nan")}
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    return {
        "n": n,
        "pnl_total": float(pnls.sum()),
        "pnl_mean": float(pnls.mean()),
        "roi_pct": float(pnls.mean() * 100),  # per-share v2-metric
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "hit": float((pnls > 0).mean()),
    }


def main():
    print("Loading data...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}
    print(f"  features: {len(feats)}")
    feats = add_signals(feats)

    signals = ["sig_ret5m_q20", "sig_ret5m_q10", "sig_ret5m_q5", "sig_ret5m_thr25bps",
               "sig_ret15m_q20", "sig_ret1h_q20", "sig_smartretail_q20",
               "sig_combo_q20", "sig_ret5m_q20_srfilter"]

    rows = []
    for asset_filter in [None] + list(ASSETS):
        asset_lbl = "ALL" if asset_filter is None else asset_filter
        sub_a = feats if asset_filter is None else feats[feats.asset == asset_filter]
        for tf in ["5m", "15m", "ALL"]:
            sub_tf = sub_a if tf == "ALL" else sub_a[sub_a.timeframe == tf]
            if len(sub_tf) == 0:
                continue
            for sig in signals:
                r = run_signal(sub_tf, traj, k1m, sig, REV_BP)
                r.update({"asset": asset_lbl, "timeframe": tf, "signal": sig})
                rows.append(r)
                marker = " ★" if sig == "sig_ret5m_q20" else ""
                print(f"asset={asset_lbl:3s} tf={tf:3s} {sig:30s} → "
                      f"n={r['n']:>4d} hit={r['hit']*100 if not np.isnan(r['hit']) else 0:5.1f}% "
                      f"pnl_mean=${r['pnl_mean']:+.4f} ROI={r['roi_pct']:+5.2f}%{marker}")

    df = pd.DataFrame(rows)
    out_csv = HERE/"results"/"polymarket"/"alt_signal_grid.csv"
    out_md = HERE/"reports"/"POLYMARKET_ALT_SIGNAL_GRID.md"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    # Markdown report
    md = ["# Alt-Signal Grid — Cross-Asset × Hedge-Hold rev_bp=5\n",
          f"Universe: BTC + ETH + SOL Up/Down markets (5,742 total). Exit: hedge-hold rev_bp={REV_BP}. "
          "Bootstrap n=2000. ROI = mean PnL per (1 share entry + 1 share hedge) × 100.\n\n"
          "**Locked baseline:** `sig_ret5m_q20` (★) at q20×15m×ALL → n=289, hit 75.8%, ROI +20.39%.\n"]

    # Best signal per (asset, tf) cell
    md.append("\n## Best signal per (asset, tf) cell\n")
    md.append("| Asset | TF | Best signal | n | Hit | ROI | vs baseline |")
    md.append("|---|---|---|---|---|---|---|")
    for asset in ["ALL", "btc", "eth", "sol"]:
        for tf in ["ALL", "15m", "5m"]:
            cell = df[(df.asset == asset) & (df.timeframe == tf)].copy()
            if cell.empty:
                continue
            cell = cell.sort_values("roi_pct", ascending=False)
            best = cell.iloc[0]
            base = cell[cell.signal == "sig_ret5m_q20"]
            base_roi = base.iloc[0]["roi_pct"] if len(base) else 0
            delta = best["roi_pct"] - base_roi
            star = " ★" if best["signal"] == "sig_ret5m_q20" else ""
            md.append(f"| {asset} | {tf} | `{best['signal']}`{star} | {int(best['n'])} | "
                      f"{best['hit']*100:.1f}% | {best['roi_pct']:+.2f}% | "
                      f"{'baseline' if star else f'{delta:+.2f}pp vs baseline'} |")

    # Full grid per signal
    md.append("\n\n## Full grid (all asset × tf × signal)\n")
    md.append("| Asset | TF | Signal | n | Hit | PnL/trade | ROI |")
    md.append("|---|---|---|---|---|---|---|")
    for asset in ["ALL", "btc", "eth", "sol"]:
        for tf in ["ALL", "15m", "5m"]:
            cell = df[(df.asset == asset) & (df.timeframe == tf)].sort_values("roi_pct", ascending=False)
            for _, r in cell.iterrows():
                star = " ★" if r["signal"] == "sig_ret5m_q20" else ""
                md.append(f"| {asset} | {tf} | `{r['signal']}`{star} | {int(r['n'])} | "
                          f"{r['hit']*100:.1f}% | ${r['pnl_mean']:+.4f} | {r['roi_pct']:+.2f}% |")

    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {out_csv} and {out_md}")


if __name__ == "__main__":
    main()
