"""
polymarket_strategy_stacks.py — stack the winners: q10 signal × time-of-day filter × asset × tf

Tests COMBINED filters to see if signal + session stacking is multiplicative.
Strategy core: hedge-hold rev_bp=5 (locked exit).

Stacks tested:
  baseline:           sig_ret5m_q20 — no filter (LOCKED)
  q10:                sig_ret5m_q10
  q5:                 sig_ret5m_q5
  good_hours:         sig_ret5m_q20 × hours[3,5,8,9,10,11,12,13,14,17,19,21]
  q10+good_hours:     sig_ret5m_q10 × good hours
  q5+good_hours:      sig_ret5m_q5 × good hours
  bad_hours_excl:     sig_ret5m_q20 × ~hours[0,2,4,7,16]
  q10+bad_excl:       sig_ret5m_q10 × ~bad hours
  europe_only:        sig_ret5m_q20 × hours[8-13]
  q10+europe:         sig_ret5m_q10 × hours[8-13]

Outputs:
  results/polymarket/strategy_stacks.csv
  reports/POLYMARKET_STRATEGY_STACKS.md
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(42)
FEE_RATE = 0.02
ASSETS = ["btc", "eth", "sol"]
REV_BP = 5

GOOD_HOURS = {3, 5, 8, 9, 10, 11, 12, 13, 14, 17, 19, 21}
BAD_HOURS = {0, 2, 4, 7, 16}
EUROPE_HOURS = set(range(8, 13))


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


def add_q_signals(df):
    df = df.copy()
    for q, name in [(0.80, "q20"), (0.90, "q10"), (0.95, "q5")]:
        col = f"sig_{name}"
        df[col] = -1
        for asset in df.asset.unique():
            for tf in df.timeframe.unique():
                m = (df.asset == asset) & (df.timeframe == tf)
                r = df.loc[m, "ret_5m"]
                rabs = r.abs()
                thr = rabs.quantile(q)
                sel = m & (rabs >= thr) & r.notna()
                df.loc[sel, col] = (r > 0).astype(int)
    df["hour_utc"] = df.window_start_unix.apply(lambda ws: datetime.fromtimestamp(int(ws), tz=timezone.utc).hour)
    return df


def simulate_market(row, traj_g, k1m, sig_value, rev_bp):
    sig = int(sig_value)
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
                oa = b[col]
                if pd.notna(oa) and 0 < oa < 1:
                    hedge_p = float(oa)
                    break
    sig_won = (sig == int(row.outcome_up))
    if hedge_p is None:
        return (1.0 - (1.0 - entry) * FEE_RATE - entry) if sig_won else -entry
    if sig_won:
        payout = 1.0 - (1.0 - entry) * FEE_RATE
    else:
        payout = 1.0 - (1.0 - hedge_p) * FEE_RATE
    return payout - entry - hedge_p


def cell_stats(pnls):
    pnls = np.array(pnls)
    n = len(pnls)
    if n == 0:
        return dict(n=0, pnl_total=0, pnl_mean=0, roi=0, hit=float('nan'), ci_lo=0, ci_hi=0)
    boot = RNG.choice(pnls, size=(2000, n), replace=True).sum(axis=1)
    return dict(
        n=n, pnl_total=float(pnls.sum()), pnl_mean=float(pnls.mean()),
        roi=float(pnls.mean() * 100), hit=float((pnls > 0).mean()),
        ci_lo=float(np.quantile(boot, 0.025)), ci_hi=float(np.quantile(boot, 0.975)),
    )


STACKS = [
    ("baseline_q20",      "sig_q20", None),
    ("q10",               "sig_q10", None),
    ("q5",                "sig_q5",  None),
    ("good_hours_q20",    "sig_q20", lambda h: h in GOOD_HOURS),
    ("good_hours_q10",    "sig_q10", lambda h: h in GOOD_HOURS),
    ("good_hours_q5",     "sig_q5",  lambda h: h in GOOD_HOURS),
    ("bad_excl_q20",      "sig_q20", lambda h: h not in BAD_HOURS),
    ("bad_excl_q10",      "sig_q10", lambda h: h not in BAD_HOURS),
    ("europe_q20",        "sig_q20", lambda h: h in EUROPE_HOURS),
    ("europe_q10",        "sig_q10", lambda h: h in EUROPE_HOURS),
]


def main():
    print("Loading data...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj = {a: load_trajectories(a) for a in ASSETS}
    k1m = {a: load_klines_1m(a) for a in ASSETS}
    feats = add_q_signals(feats)

    rows = []
    for asset_filter in [None] + list(ASSETS):
        asset_lbl = "ALL" if asset_filter is None else asset_filter
        sub_a = feats if asset_filter is None else feats[feats.asset == asset_filter]
        for tf in ["5m", "15m", "ALL"]:
            sub_tf = sub_a if tf == "ALL" else sub_a[sub_a.timeframe == tf]
            for stack_name, sig_col, hour_filter in STACKS:
                sel = sub_tf[sub_tf[sig_col] != -1].copy()
                if hour_filter is not None:
                    sel = sel[sel.hour_utc.apply(hour_filter)]
                pnls = []
                for _, row in sel.iterrows():
                    tg = traj[row.asset].get(row.slug)
                    if tg is None or tg.empty:
                        continue
                    p = simulate_market(row, tg, k1m[row.asset], row[sig_col], REV_BP)
                    if p is not None:
                        pnls.append(p)
                s = cell_stats(pnls)
                s.update({"asset": asset_lbl, "tf": tf, "stack": stack_name})
                rows.append(s)
    df = pd.DataFrame(rows)

    out_csv = HERE/"results"/"polymarket"/"strategy_stacks.csv"
    out_md = HERE/"reports"/"POLYMARKET_STRATEGY_STACKS.md"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    md = ["# Strategy Stacks — q-tightening × time-of-day filter\n",
          "Cross-asset hedge-hold rev_bp=5. Comparing locked baseline (q20, no filter) "
          "to combinations of tighter quintiles + UTC-hour filters.\n"]

    # Best stack per (asset, tf)
    md.append("\n## Best stack per cell\n")
    md.append("| Asset | TF | Best stack | n | Hit% | ROI | vs baseline |")
    md.append("|---|---|---|---|---|---|---|")
    for asset in ["ALL", "btc", "eth", "sol"]:
        for tf in ["ALL", "15m", "5m"]:
            cell = df[(df.asset == asset) & (df.tf == tf)].copy()
            if cell.empty:
                continue
            cell = cell.sort_values("roi", ascending=False)
            best = cell.iloc[0]
            base = cell[cell["stack"].values == "baseline_q20"]
            base_roi = base.iloc[0]["roi"] if len(base) else 0
            base_n = int(base.iloc[0]["n"]) if len(base) else 0
            star = " ★" if best["stack"] == "baseline_q20" else ""
            md.append(f"| {asset} | {tf} | `{best['stack']}`{star} | {int(best['n'])} | "
                      f"{best['hit']*100:.1f}% | {best['roi']:+.2f}% | "
                      f"{'baseline' if star else f'+{best['roi']-base_roi:.2f}pp ({best['n']/max(base_n,1)*100:.0f}% volume)'} |")

    # ALL × ALL detail
    md.append("\n## ALL × ALL — all stacks ranked\n")
    md.append("| Stack | n | Hit% | PnL/trade | ROI | 95% CI |")
    md.append("|---|---|---|---|---|---|")
    aa = df[(df.asset == "ALL") & (df.tf == "ALL")].sort_values("roi", ascending=False)
    for _, r in aa.iterrows():
        marker = " ★ baseline" if r.stack == "baseline_q20" else ""
        md.append(f"| `{r.stack}`{marker} | {int(r.n)} | {r.hit*100:.1f}% | "
                  f"${r.pnl_mean:+.4f} | {r.roi:+.2f}% | [${r.ci_lo:+.0f}, ${r.ci_hi:+.0f}] |")

    md.append("\n## BTC × ALL — all stacks ranked\n")
    md.append("| Stack | n | Hit% | PnL/trade | ROI | 95% CI |")
    md.append("|---|---|---|---|---|---|")
    bb = df[(df.asset == "btc") & (df.tf == "ALL")].sort_values("roi", ascending=False)
    for _, r in bb.iterrows():
        marker = " ★ baseline" if r.stack == "baseline_q20" else ""
        md.append(f"| `{r.stack}`{marker} | {int(r.n)} | {r.hit*100:.1f}% | "
                  f"${r.pnl_mean:+.4f} | {r.roi:+.2f}% | [${r.ci_lo:+.0f}, ${r.ci_hi:+.0f}] |")

    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {out_csv} and {out_md}")

    # Print ALL × ALL ranked
    print("\n=== ALL × ALL stacks ranked by ROI ===")
    for _, r in aa.iterrows():
        m = " ★" if r.stack == "baseline_q20" else ""
        print(f"  {r.stack:25s} n={int(r.n):>4d} hit={r.hit*100:5.1f}% ROI={r.roi:+6.2f}%{m}")


if __name__ == "__main__":
    main()
