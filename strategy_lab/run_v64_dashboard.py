"""
V64 Strategy Dashboard — full statistics for the leveraged champion.

Builds V64 (V52 with risk_per_trade=0.0525, leverage_cap=4.0) capturing
trades AND equity per sleeve, then renders a comprehensive dashboard:
  - Trade frequency (per week, per month, per sleeve)
  - Trade quality (WR, profit factor, expectancy, streaks)
  - Holding period distribution
  - Per-sleeve breakdown
  - Per-coin breakdown
  - Long/short split
  - Yearly + monthly returns
  - Drawdown profile
  - Best/worst trades
  - Recovery times

Output: pretty-printed text dashboard + JSON dump.
"""
from __future__ import annotations
import json, sys, time, warnings, importlib.util
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H
from strategy_lab.regime.hmm_adaptive import fit_regime_model
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)

OUT = REPO / "docs/research/phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6
START = "2024-01-12"
END = "2026-04-25"
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
RISK = 0.0525   # V64 = V52 x 1.75
LEV_CAP = 4.0

# V52 spec
V41_VARIANT_MAP = {
    "CCI_ETH_4h":    "V41",
    "STF_SOL_4h":    "baseline",
    "STF_AVAX_4h":   "V45",
    "LATBB_AVAX_4h": "baseline",
}
SLEEVE_SPECS = {
    "CCI_ETH_4h":    ("run_v30_creative.py",  "sig_cci_extreme",     "ETH"),
    "STF_SOL_4h":    ("run_v30_creative.py",  "sig_supertrend_flip", "SOL"),
    "STF_AVAX_4h":   ("run_v30_creative.py",  "sig_supertrend_flip", "AVAX"),
    "LATBB_AVAX_4h": ("run_v29_regime.py",    "sig_lateral_bb_fade", "AVAX"),
}
DIV_SPECS = [
    ("MFI_SOL",  "SOL",  sig_mfi_extreme,        dict(lower=25, upper=75), "V41"),
    ("VP_LINK",  "LINK", sig_volume_profile_rot, dict(win=60, n_bins=15), "baseline"),
    ("SVD_AVAX", "AVAX", sig_signed_vol_div,     dict(lookback=20, cvd_win=50, min_cvd_threshold=0.5), "baseline"),
    ("MFI_ETH",  "ETH",  sig_mfi_extreme,        dict(lower=25, upper=75), "baseline"),
]
ALL_SLEEVES = list(V41_VARIANT_MAP.keys()) + [s[0] for s in DIV_SPECS]


def import_sig(script, fn):
    path = REPO / "strategy_lab" / script
    spec = importlib.util.spec_from_file_location(script.replace(".", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, fn)


def build_v41_sleeve(sleeve):
    script, fn, sym = SLEEVE_SPECS[sleeve]
    sig = import_sig(script, fn)
    df = load_hl(sym, "4h", start=START, end=END)
    out = sig(df); le, se = out if isinstance(out, tuple) else (out, None)
    fund = funding_per_4h_bar(sym, df.index)
    variant = V41_VARIANT_MAP[sleeve]
    common = dict(risk_per_trade=RISK, leverage_cap=LEV_CAP)
    if variant == "baseline":
        trades, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H, **common)
    elif variant == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        trades, eq = simulate_with_funding(df, le, se, fund,
                                            regime_labels=rdf["label"],
                                            regime_exits=REGIME_EXITS_4H,
                                            **common)
    elif variant == "V45":
        vol = df["volume"]; vmean = vol.rolling(20, min_periods=10).mean()
        active = vol > 1.1 * vmean
        le2 = le & active
        se2 = se & active if se is not None else None
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        trades, eq = simulate_with_funding(df, le2, se2, fund,
                                            regime_labels=rdf["label"],
                                            regime_exits=REGIME_EXITS_4H,
                                            **common)
    return trades, eq, sym, df.index


def build_div(name):
    spec = next(s for s in DIV_SPECS if s[0] == name)
    _, sym, sig_fn, kw, exit_style = spec
    df = load_hl(sym, "4h", start=START, end=END)
    out = sig_fn(df, **kw); le, se = out if isinstance(out, tuple) else (out, None)
    fund = funding_per_4h_bar(sym, df.index)
    common = dict(risk_per_trade=RISK, leverage_cap=LEV_CAP)
    if exit_style == "V41":
        _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
        trades, eq = simulate_with_funding(df, le, se, fund,
                                            regime_labels=rdf["label"],
                                            regime_exits=REGIME_EXITS_4H,
                                            **common)
    else:
        trades, eq = simulate_with_funding(df, le, se, fund, **EXIT_4H, **common)
    return trades, eq, sym, df.index


def annotate_trades(trades, sleeve, sym, idx):
    """Add timestamps and sleeve/coin tags to each trade."""
    out = []
    for t in trades:
        ei = t["entry_idx"]; xi = t["exit_idx"]
        if ei < len(idx) and xi < len(idx):
            t2 = dict(t)
            t2["sleeve"] = sleeve
            t2["coin"]   = sym
            t2["entry_ts"] = idx[ei]
            t2["exit_ts"]  = idx[xi]
            out.append(t2)
    return out


def hist_text(values, bins=10, width=40):
    """ASCII histogram."""
    if not values:
        return "(empty)"
    a = np.array(values)
    counts, edges = np.histogram(a, bins=bins)
    mx = counts.max() if counts.max() > 0 else 1
    lines = []
    for i, c in enumerate(counts):
        bar = "#" * int(c / mx * width)
        lines.append(f"  {edges[i]:>+7.3f} to {edges[i+1]:>+7.3f}  {bar:<{width}} {c}")
    return "\n".join(lines)


def main():
    t0 = time.time()
    print("=" * 78)
    print("V64 STRATEGY DASHBOARD")
    print(f"Window: {START} -> {END} | risk={RISK} | leverage_cap={LEV_CAP}")
    print("=" * 78)

    # ------------------------------------------------------------------ build
    print("\n[1] Building all 8 sleeves with trade capture...")
    sleeve_data = {}
    for s in V41_VARIANT_MAP:
        tr, eq, sym, idx = build_v41_sleeve(s)
        sleeve_data[s] = {"trades": annotate_trades(tr, s, sym, idx),
                           "eq": eq, "sym": sym}
        print(f"   {s:<14} ({sym})  trades={len(tr):>4}  eq_bars={len(eq)}")
    for spec in DIV_SPECS:
        nm = spec[0]
        tr, eq, sym, idx = build_div(nm)
        sleeve_data[nm] = {"trades": annotate_trades(tr, nm, sym, idx),
                            "eq": eq, "sym": sym}
        print(f"   {nm:<14} ({sym})  trades={len(tr):>4}  eq_bars={len(eq)}")

    # Compose V64 portfolio equity (matches build_v52_hl but with V64 sleeves)
    v41_curves = {k: sleeve_data[k]["eq"] for k in V41_VARIANT_MAP}
    p3 = invvol_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h"]}, window=500)
    p5 = eqw_blend({k: v41_curves[k] for k in ["CCI_ETH_4h", "LATBB_AVAX_4h", "STF_SOL_4h"]})
    idx = p3.index.intersection(p5.index)
    v41_r = 0.6 * p3.reindex(idx).pct_change().fillna(0) + 0.4 * p5.reindex(idx).pct_change().fillna(0)
    v41_eq = (1 + v41_r).cumprod() * 10_000.0

    div_curves = {nm: sleeve_data[nm]["eq"] for nm, *_ in DIV_SPECS}
    all_idx = v41_eq.index
    for eq in div_curves.values():
        all_idx = all_idx.intersection(eq.index)
    cr = v41_eq.reindex(all_idx).pct_change().fillna(0)
    drs = {k: eq.reindex(all_idx).pct_change().fillna(0) for k, eq in div_curves.items()}
    combined = (0.60 * cr + 0.10 * drs["MFI_SOL"] + 0.10 * drs["VP_LINK"]
                + 0.10 * drs["SVD_AVAX"] + 0.10 * drs["MFI_ETH"])
    eq_v64 = (1 + combined).cumprod() * 10_000.0
    rets = eq_v64.pct_change().dropna()

    # ------------------------------------------------------------------ headline
    sd = float(rets.std())
    sh = (float(rets.mean()) / sd) * np.sqrt(BPY) if sd > 0 else 0
    pk = eq_v64.cummax(); dd = eq_v64 / pk - 1
    mdd = float(dd.min())
    yrs = (eq_v64.index[-1] - eq_v64.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq_v64.iloc[-1] / eq_v64.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = cagr / abs(mdd) if mdd != 0 else 0

    # ------------------------------------------------------------------ trade pool
    all_trades = []
    for s in ALL_SLEEVES:
        all_trades.extend(sleeve_data[s]["trades"])
    all_trades.sort(key=lambda t: t["entry_ts"])
    n_t = len(all_trades)
    weeks = yrs * 52.18
    months = yrs * 12
    days = yrs * 365.25

    # ------------------------------------------------------------------ section: HEADLINE
    print("\n" + "=" * 78)
    print("HEADLINE PERFORMANCE")
    print("=" * 78)
    print(f"  Period            : {eq_v64.index[0].date()} -> {eq_v64.index[-1].date()}  ({yrs:.2f} years)")
    print(f"  Sharpe            : {sh:.3f}")
    print(f"  CAGR              : {cagr*100:+.2f}%")
    print(f"  MDD               : {mdd*100:+.2f}%")
    print(f"  Calmar            : {cal:.3f}")
    print(f"  Total return      : {(eq_v64.iloc[-1]/eq_v64.iloc[0]-1)*100:+.2f}%")
    print(f"  Final equity (10k): {eq_v64.iloc[-1]:,.0f}")
    print(f"  Volatility (ann)  : {sd * np.sqrt(BPY) * 100:.2f}%")
    print(f"  Skew (4h ret)     : {float(rets.skew()):.3f}")
    print(f"  Kurtosis (4h ret) : {float(rets.kurtosis()):.3f}")
    pos_bars = (rets > 0).sum(); neg_bars = (rets < 0).sum()
    print(f"  Positive bars     : {pos_bars}/{len(rets)} ({pos_bars/len(rets)*100:.1f}%)")
    print(f"  Best 4h bar       : {rets.max()*100:+.2f}%")
    print(f"  Worst 4h bar      : {rets.min()*100:+.2f}%")

    # ------------------------------------------------------------------ section: TRADE FREQUENCY
    print("\n" + "=" * 78)
    print("TRADE FREQUENCY")
    print("=" * 78)
    print(f"  Total trades             : {n_t}")
    print(f"  Trades per year          : {n_t/yrs:.1f}")
    print(f"  Trades per month         : {n_t/months:.2f}")
    print(f"  Trades per week          : {n_t/weeks:.2f}")
    print(f"  Trades per day           : {n_t/days:.3f}")
    print(f"  Avg days between trades  : {days/n_t:.2f}")
    long_n = sum(1 for t in all_trades if t["side"] == 1)
    short_n = sum(1 for t in all_trades if t["side"] == -1)
    print(f"  Long / Short             : {long_n} ({long_n/n_t*100:.1f}%) / {short_n} ({short_n/n_t*100:.1f}%)")

    # ------------------------------------------------------------------ section: PER SLEEVE
    print("\n" + "=" * 78)
    print("PER-SLEEVE TRADE TABLE")
    print("=" * 78)
    print(f"  {'sleeve':<14} {'coin':<5} {'n':>4} {'/yr':>6} {'/wk':>6} "
          f"{'WR%':>6} {'avg_r%':>7} {'avg_bars':>9} {'med_bars':>9}")
    sleeve_summary = []
    for s in ALL_SLEEVES:
        ts = sleeve_data[s]["trades"]
        sym = sleeve_data[s]["sym"]
        n = len(ts)
        if n == 0:
            print(f"  {s:<14} {sym:<5} {n:>4}  (no trades)")
            continue
        wins = sum(1 for t in ts if t["ret"] > 0)
        wr = wins / n
        avg_r = np.mean([t["ret"] for t in ts])
        avg_b = np.mean([t["bars"] for t in ts])
        med_b = np.median([t["bars"] for t in ts])
        print(f"  {s:<14} {sym:<5} {n:>4} {n/yrs:>6.1f} {n/weeks:>6.2f} "
              f"{wr*100:>6.1f} {avg_r*100:>+7.3f} {avg_b:>9.1f} {med_b:>9.1f}")
        sleeve_summary.append({"sleeve": s, "coin": sym, "n": n,
                                "per_yr": n/yrs, "per_wk": n/weeks,
                                "wr": wr, "avg_r": avg_r,
                                "avg_bars": avg_b, "med_bars": med_b})

    # ------------------------------------------------------------------ section: PER COIN
    print("\n" + "=" * 78)
    print("PER-COIN AGGREGATES")
    print("=" * 78)
    coin_buckets = defaultdict(list)
    for t in all_trades:
        coin_buckets[t["coin"]].append(t)
    print(f"  {'coin':<5} {'n':>4} {'%':>6} {'WR%':>6} {'avg_r%':>7} {'sleeves':<25}")
    for coin in sorted(coin_buckets.keys()):
        ts = coin_buckets[coin]
        n = len(ts)
        wins = sum(1 for t in ts if t["ret"] > 0)
        wr = wins / n
        avg_r = np.mean([t["ret"] for t in ts])
        sleeves = sorted(set(t["sleeve"] for t in ts))
        print(f"  {coin:<5} {n:>4} {n/n_t*100:>6.1f} {wr*100:>6.1f} {avg_r*100:>+7.3f} "
              f"{','.join(sleeves)}")

    # ------------------------------------------------------------------ section: TRADE QUALITY
    print("\n" + "=" * 78)
    print("TRADE QUALITY")
    print("=" * 78)
    rets_pct = [t["ret"] for t in all_trades]
    wins = [r for r in rets_pct if r > 0]
    losses = [r for r in rets_pct if r < 0]
    n_w = len(wins); n_l = len(losses); n_be = n_t - n_w - n_l
    wr = n_w / n_t
    avg_w = np.mean(wins) if wins else 0
    avg_l = np.mean(losses) if losses else 0
    pf = (sum(wins) / abs(sum(losses))) if losses else float("inf")
    expectancy_pct = wr * avg_w + (1 - wr) * avg_l
    print(f"  Win rate                 : {wr*100:.2f}%  ({n_w}W / {n_l}L / {n_be}BE)")
    print(f"  Avg win                  : {avg_w*100:+.3f}% (per-equity)")
    print(f"  Avg loss                 : {avg_l*100:+.3f}%")
    print(f"  Win/Loss ratio (avg)     : {abs(avg_w/avg_l):.2f}")
    print(f"  Profit factor            : {pf:.2f}")
    print(f"  Expectancy per trade     : {expectancy_pct*100:+.4f}%")
    print(f"  Median trade ret         : {np.median(rets_pct)*100:+.3f}%")
    print(f"  Best trade               : {max(rets_pct)*100:+.3f}%")
    print(f"  Worst trade              : {min(rets_pct)*100:+.3f}%")
    print(f"  Stdev trade ret          : {np.std(rets_pct)*100:.3f}%")

    # streaks
    sorted_t = sorted(all_trades, key=lambda t: t["entry_ts"])
    cur_w, cur_l, max_w, max_l = 0, 0, 0, 0
    for t in sorted_t:
        if t["ret"] > 0:
            cur_w += 1; cur_l = 0
            max_w = max(max_w, cur_w)
        elif t["ret"] < 0:
            cur_l += 1; cur_w = 0
            max_l = max(max_l, cur_l)
    print(f"  Max winning streak       : {max_w}")
    print(f"  Max losing streak        : {max_l}")

    # ------------------------------------------------------------------ section: HOLDING PERIOD
    print("\n" + "=" * 78)
    print("HOLDING PERIOD DISTRIBUTION (in 4h bars)")
    print("=" * 78)
    bars = [t["bars"] for t in all_trades]
    print(f"  Mean         : {np.mean(bars):.1f} bars  ({np.mean(bars)*4/24:.2f} days)")
    print(f"  Median       : {np.median(bars):.0f} bars  ({np.median(bars)*4/24:.2f} days)")
    print(f"  P10          : {np.percentile(bars, 10):.0f} bars")
    print(f"  P25          : {np.percentile(bars, 25):.0f} bars")
    print(f"  P75          : {np.percentile(bars, 75):.0f} bars")
    print(f"  P90          : {np.percentile(bars, 90):.0f} bars")
    print(f"  Max          : {max(bars)} bars  ({max(bars)*4/24:.1f} days)")

    # exit reason
    reasons = defaultdict(int)
    for t in all_trades:
        reasons[t.get("reason", "?")] += 1
    print(f"\n  Exit reason breakdown:")
    for r, c in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"     {r:<14} : {c:>4}  ({c/n_t*100:.1f}%)")

    # ------------------------------------------------------------------ section: RETURN DIST
    print("\n" + "=" * 78)
    print("PER-TRADE RETURN HISTOGRAM (% per equity)")
    print("=" * 78)
    print(hist_text([r*100 for r in rets_pct], bins=12))

    # ------------------------------------------------------------------ section: YEARLY
    print("\n" + "=" * 78)
    print("YEARLY PERFORMANCE")
    print("=" * 78)
    print(f"  {'year':<6} {'ret%':>8} {'#trades':>9} {'WR%':>6} {'maxDD%':>8}")
    yearly = {}
    for yr in sorted(set(eq_v64.index.year)):
        y_eq = eq_v64[eq_v64.index.year == yr]
        if len(y_eq) < 30:
            continue
        y_ret = (y_eq.iloc[-1] / y_eq.iloc[0] - 1)
        y_pk = y_eq.cummax(); y_dd = float((y_eq / y_pk - 1).min())
        y_trades = [t for t in all_trades if t["entry_ts"].year == yr]
        y_wr = (sum(1 for t in y_trades if t["ret"] > 0) / max(len(y_trades), 1))
        print(f"  {yr:<6} {y_ret*100:>+7.2f}% {len(y_trades):>9} "
              f"{y_wr*100:>6.1f} {y_dd*100:>+7.2f}%")
        yearly[int(yr)] = {"ret_pct": y_ret*100, "n_trades": len(y_trades),
                            "wr": y_wr, "mdd_pct": y_dd*100}

    # ------------------------------------------------------------------ section: MONTHLY
    print("\n" + "=" * 78)
    print("MONTHLY RETURNS HEATMAP")
    print("=" * 78)
    monthly = eq_v64.resample("ME").last().pct_change().dropna() * 100
    months_df = pd.DataFrame({"ret": monthly})
    months_df["year"] = months_df.index.year
    months_df["month"] = months_df.index.month
    pivot = months_df.pivot_table(index="year", columns="month", values="ret")
    months_lbl = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    header = "  year |" + "".join(f"{m:>7}" for m in months_lbl) + "    YTD"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for yr in pivot.index:
        cells = []
        for mo in range(1, 13):
            v = pivot.loc[yr, mo] if mo in pivot.columns and not pd.isna(pivot.loc[yr, mo]) else None
            cells.append(f"{v:>+6.1f}%" if v is not None else "      .")
        ytd = monthly[monthly.index.year == yr].sum()
        print(f"  {yr:<5}|" + "".join(cells) + f"  {ytd:>+6.1f}%")
    pos_m = (monthly > 0).sum(); neg_m = (monthly < 0).sum()
    best_m_ix = monthly.idxmax(); worst_m_ix = monthly.idxmin()
    print(f"\n  Positive months  : {pos_m}/{len(monthly)} ({pos_m/len(monthly)*100:.1f}%)")
    print(f"  Best month       : {monthly.max():+.2f}%  ({best_m_ix.strftime('%Y-%m')})")
    print(f"  Worst month      : {monthly.min():+.2f}%  ({worst_m_ix.strftime('%Y-%m')})")
    print(f"  Avg pos month    : {monthly[monthly > 0].mean():+.2f}%")
    print(f"  Avg neg month    : {monthly[monthly < 0].mean():+.2f}%")

    # ------------------------------------------------------------------ section: DRAWDOWNS
    print("\n" + "=" * 78)
    print("DRAWDOWN PROFILE (top 5 drawdowns)")
    print("=" * 78)
    # find drawdown periods
    dd_arr = dd.values
    in_dd = False
    starts = []; troughs = []; recoveries = []; depths = []
    cur_start = None; cur_trough = -1.0; cur_trough_idx = None
    for i in range(len(dd_arr)):
        if not in_dd and dd_arr[i] < -0.001:
            in_dd = True
            cur_start = i; cur_trough = dd_arr[i]; cur_trough_idx = i
        elif in_dd:
            if dd_arr[i] < cur_trough:
                cur_trough = dd_arr[i]; cur_trough_idx = i
            if dd_arr[i] >= -0.0001:
                in_dd = False
                starts.append(cur_start); troughs.append(cur_trough_idx)
                recoveries.append(i); depths.append(cur_trough)
    if in_dd:
        starts.append(cur_start); troughs.append(cur_trough_idx)
        recoveries.append(len(dd_arr)-1); depths.append(cur_trough)

    drawdowns = []
    for s, tr_ix, r, d in zip(starts, troughs, recoveries, depths):
        drawdowns.append({
            "start": eq_v64.index[s], "trough": eq_v64.index[tr_ix],
            "recovery": eq_v64.index[r] if r < len(eq_v64) else None,
            "depth_pct": d * 100,
            "to_trough_bars": tr_ix - s,
            "recovery_bars": r - tr_ix if r < len(eq_v64) else None,
            "total_bars": r - s,
        })
    drawdowns.sort(key=lambda x: x["depth_pct"])
    print(f"  {'#':>2} {'start':<12} {'trough':<12} {'recov':<12} {'depth%':>7} "
          f"{'to_trough_d':>11} {'recov_d':>7} {'total_d':>7}")
    for i, d in enumerate(drawdowns[:5], 1):
        rec = d["recovery"].date() if d["recovery"] is not None else "ongoing"
        rec_d = (d["recovery_bars"] or 0) * 4 / 24
        tot_d = d["total_bars"] * 4 / 24
        ttr_d = d["to_trough_bars"] * 4 / 24
        print(f"  {i:>2} {str(d['start'].date()):<12} {str(d['trough'].date()):<12} "
              f"{str(rec):<12} {d['depth_pct']:>+7.2f} "
              f"{ttr_d:>10.1f}d {rec_d:>6.1f}d {tot_d:>6.1f}d")

    # ------------------------------------------------------------------ DUMP JSON
    summary = {
        "headline": {
            "sharpe": round(float(sh), 3),
            "cagr_pct": round(float(cagr) * 100, 2),
            "mdd_pct": round(float(mdd) * 100, 2),
            "calmar": round(float(cal), 3),
            "vol_ann_pct": round(float(sd) * np.sqrt(BPY) * 100, 2),
            "skew": round(float(rets.skew()), 3),
            "kurtosis": round(float(rets.kurtosis()), 3),
            "total_ret_pct": round(float(eq_v64.iloc[-1]/eq_v64.iloc[0]-1)*100, 2),
        },
        "trade_frequency": {
            "n_total": int(n_t),
            "per_year": round(n_t / yrs, 1),
            "per_month": round(n_t / months, 2),
            "per_week": round(n_t / weeks, 2),
            "per_day": round(n_t / days, 3),
            "long_n": int(long_n),
            "short_n": int(short_n),
        },
        "trade_quality": {
            "win_rate": round(wr, 4),
            "avg_win_pct": round(float(avg_w) * 100, 4),
            "avg_loss_pct": round(float(avg_l) * 100, 4),
            "profit_factor": round(float(pf), 3),
            "expectancy_pct": round(float(expectancy_pct) * 100, 4),
            "max_win_streak": int(max_w),
            "max_loss_streak": int(max_l),
            "best_trade_pct": round(float(max(rets_pct)) * 100, 3),
            "worst_trade_pct": round(float(min(rets_pct)) * 100, 3),
        },
        "holding_period_bars": {
            "mean": round(float(np.mean(bars)), 1),
            "median": int(np.median(bars)),
            "p10": int(np.percentile(bars, 10)),
            "p90": int(np.percentile(bars, 90)),
            "max": int(max(bars)),
        },
        "exit_reasons": dict(reasons),
        "per_sleeve": sleeve_summary,
        "yearly": yearly,
        "drawdowns_top5": [{
            "start": str(d["start"].date()),
            "trough": str(d["trough"].date()),
            "recovery": str(d["recovery"].date()) if d["recovery"] is not None else "ongoing",
            "depth_pct": round(d["depth_pct"], 2),
            "total_days": round(d["total_bars"] * 4 / 24, 1),
        } for d in drawdowns[:5]],
    }
    out = OUT / "v64_dashboard.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n[done in {time.time()-t0:.1f}s]  Wrote: {out}")


if __name__ == "__main__":
    main()
