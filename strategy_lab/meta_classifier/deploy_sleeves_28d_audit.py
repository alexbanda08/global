"""Per-sleeve + ensemble audit on full 28d canonical for the deploy candidates.

Top 5 deploy sleeves from `MOMO_VARIANTS_F7_MARKOV_STACK_2026_05_22.md`:

  S1: Baseline_v1 + btc_15m + M1V         (Markov only, no F7)
  S2: 2B late/early + btc_15m + M1V       (Markov only)
  S3: 2B late/early + btc_15m + F7+M1V    (F7 + Markov stack)
  S4: 2C edge-of-slot + btc_15m + F7+M5V  (5m-Markov stack)
  S5: Baseline_v2 + eth_5m + F7+M5F       (only 5m positive cell)

For each: 28d full-window stats (WR, PnL, per-trade, daily PnL distribution,
max drawdown, longest win/loss streak).
Plus ensemble: overlap analysis (do sleeves fire on the same slugs?), combined
daily PnL.

Source: per_trade_markov.parquet (already has F7 + Markov columns).
"""
from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
PT = ROOT / "data" / "v4" / "canonical" / "_results" / "momo_variants_2abc_2026_05_20" / "per_trade_markov.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "momo_variants_2abc_2026_05_20" / "deploy_sleeves_28d_audit.csv"

SLEEVES = [
    # (id, variant, cell, filter_fn, label_str)
    ("S1", "Baseline_v1",               "btc_15m", lambda d: d.mpass_w20_1m_voladaptive,                  "M1V"),
    ("S2", "2B_late_fire_early_signal", "btc_15m", lambda d: d.mpass_w20_1m_voladaptive,                  "M1V"),
    ("S3", "2B_late_fire_early_signal", "btc_15m", lambda d: d.f7  & d.mpass_w20_1m_voladaptive,          "F7+M1V"),
    ("S4", "2C_edge_of_slot",            "btc_15m", lambda d: d.f7  & d.mpass_w20_5m_voladaptive,         "F7+M5V"),
    ("S5", "Baseline_v2",               "eth_5m",  lambda d: d.f7  & d.mpass_w20_5m_fixed,               "F7+M5F"),
]


def f7_basic(sig, rsi):
    if not math.isfinite(rsi): return False
    if sig == "UP"   and rsi <= 50: return False
    if sig == "DOWN" and rsi >= 50: return False
    return True


def max_drawdown(pnl_series: np.ndarray) -> float:
    cum = np.cumsum(pnl_series)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return float(dd.min()) if len(dd) else 0.0


def streaks(won: np.ndarray) -> tuple[int, int]:
    """Returns (max_win_streak, max_loss_streak)."""
    if len(won) == 0: return 0, 0
    max_w = max_l = cur_w = cur_l = 0
    for w in won:
        if w:
            cur_w += 1; cur_l = 0
            max_w = max(max_w, cur_w)
        else:
            cur_l += 1; cur_w = 0
            max_l = max(max_l, cur_l)
    return max_w, max_l


def main():
    print(f"[1] loading per_trade_markov ({PT.name})...")
    pt = pd.read_parquet(PT)
    # F7 column is already there from overlay run, but rebuild for safety
    if "f7" not in pt.columns:
        pt["f7"] = [f7_basic(s, r) for s, r in zip(pt.signal, pt.rsi_14)]
    print(f"    {len(pt):,} fires total")

    # Date column for daily aggregation
    pt["fire_ts"] = pd.to_datetime(pt.fire_s, unit="s", utc=True)
    pt["day"] = pt.fire_ts.dt.date

    # === Per-sleeve audit ===
    print()
    print("=" * 110)
    print("PER-SLEEVE 28-day AUDIT (production-matched PnL, ws_s F7 anchor, sub-sec L25)")
    print("=" * 110)
    sleeve_dfs = {}
    rows = []
    for sid, variant, cell, fn, lbl in SLEEVES:
        asset, tf = cell.split("_")
        asset = asset.upper()
        g = pt[(pt.variant == variant) & (pt.asset == asset) & (pt.tf == tf)].copy()
        sub = g[fn(g)].sort_values("fire_s").reset_index(drop=True)
        sleeve_dfs[sid] = sub
        n = len(sub)
        wins = int(sub.won.sum())
        wr = wins / max(n, 1)
        pnl = sub.pnl_legacy_usd.values.astype("float64")
        leg_tot = float(pnl.sum())
        leg_per = float(pnl.mean()) if n else 0.0
        leg_std = float(pnl.std()) if n else 0.0
        # daily aggregation
        daily = sub.groupby("day").pnl_legacy_usd.sum()
        days_traded = len(daily)
        avg_per_day = leg_tot / 28.0
        max_dd = max_drawdown(pnl)
        max_ws, max_ls = streaks(sub.won.values.astype(bool))
        sharpe = (leg_per / leg_std * math.sqrt(n)) if leg_std > 0 else 0.0
        rows.append(dict(
            sleeve=sid, variant=variant, cell=cell, filter=lbl,
            n=n, wins=wins, wr_pct=wr*100, leg_tot=leg_tot, leg_per_tr=leg_per,
            std=leg_std, sharpe=sharpe, max_dd=max_dd,
            avg_per_day_at_25=avg_per_day, days_traded=days_traded,
            max_win_streak=max_ws, max_loss_streak=max_ls,
        ))
        print(f"\n--- {sid}  {variant} / {cell} / {lbl} ---")
        print(f"    n={n}  wins={wins}  WR={wr*100:.2f}%  total_legacy_pnl=${leg_tot:+.2f}  per_trade=${leg_per:+.4f}")
        print(f"    pnl_std=${leg_std:.4f}  sharpe(approx)={sharpe:.2f}  max_dd=${max_dd:.2f}")
        print(f"    days_with_fire={days_traded}/28   max_win_streak={max_ws}   max_loss_streak={max_ls}")
        print(f"    avg_per_day @ $25 notional: ${avg_per_day:+.2f}")
        print(f"    avg_per_day @ $250:         ${avg_per_day*10:+.2f}")
        print(f"    avg_per_day @ $1000:        ${avg_per_day*40:+.2f}")
        if days_traded:
            print(f"    daily PnL: mean=${daily.mean():+.2f}  std=${daily.std():.2f}  "
                  f"best=${daily.max():+.2f}  worst=${daily.min():+.2f}")

    pd.DataFrame(rows).to_csv(OUT, index=False)

    # === Ensemble overlap ===
    print()
    print("=" * 110)
    print("ENSEMBLE OVERLAP — do sleeves fire on the same slugs?")
    print("=" * 110)
    slug_sets = {sid: set(df.slug) for sid, df in sleeve_dfs.items()}
    sids = [sid for sid, *_ in SLEEVES]
    print(f"    {'pair':<10} {'|A∩B|':>6} {'|A∪B|':>6} {'jaccard':>9}  ({'A':<3} ∩ {'B':<3})")
    for i, a in enumerate(sids):
        for b in sids[i+1:]:
            inter = len(slug_sets[a] & slug_sets[b])
            union = len(slug_sets[a] | slug_sets[b])
            jac = inter / max(union, 1)
            print(f"    {a}+{b:<7} {inter:>6} {union:>6} {jac:>9.3f}")

    # === Combined ensemble (dedup by slug — pick highest-conviction fire) ===
    print()
    print("=" * 110)
    print("ENSEMBLE COMBINED DAILY — union of all 5 sleeves (1 fire per slug if multiple)")
    print("=" * 110)
    combined = []
    for sid, df in sleeve_dfs.items():
        d = df.copy()
        d["sleeve"] = sid
        combined.append(d)
    combined = pd.concat(combined, ignore_index=True)
    # Within same slug, KEEP all sleeve fires (independent capital allocations) ←
    # operator decision: 1 sleeve = 1 capital unit, so 2 sleeves firing same slug = 2x notional
    combined_daily = combined.groupby("day").pnl_legacy_usd.sum()
    print(f"    total ensemble fires: {len(combined):,}")
    print(f"    unique slugs fired:   {combined.slug.nunique():,}")
    print(f"    days with ≥1 fire:    {len(combined_daily)} / 28")
    print(f"    total ensemble PnL:   ${combined.pnl_legacy_usd.sum():+.2f}")
    print(f"    daily PnL:  mean=${combined_daily.mean():+.2f}  std=${combined_daily.std():.2f}")
    print(f"                best=${combined_daily.max():+.2f}  worst=${combined_daily.min():+.2f}")
    n_pos_days = (combined_daily > 0).sum()
    n_neg_days = (combined_daily < 0).sum()
    print(f"    positive days: {n_pos_days}/{len(combined_daily)}  negative days: {n_neg_days}/{len(combined_daily)}")

    # Daily PnL trajectory
    print()
    print("Daily ensemble PnL (28 days):")
    sorted_daily = combined_daily.sort_index()
    cum = 0.0
    for day, dpnl in sorted_daily.items():
        cum += dpnl
        bar = "+" * min(int(dpnl), 50) if dpnl > 0 else "-" * min(int(-dpnl), 50)
        print(f"    {day}  ${dpnl:>+7.2f}  cum ${cum:>+8.2f}  {bar}")

    # Annualized projection at $25 notional
    total = float(combined.pnl_legacy_usd.sum())
    days_in_data = (pt.day.max() - pt.day.min()).days + 1 if pt.day.notna().any() else 28
    daily_avg = total / max(days_in_data, 1)
    print()
    print(f"PROJECTION at $25 notional × {len(SLEEVES)} sleeves:")
    print(f"    daily avg: ${daily_avg:+.2f}")
    print(f"    monthly:   ${daily_avg*30:+.2f}")
    print(f"    annual:    ${daily_avg*365:+.2f}")
    print(f"PROJECTION at $250 notional × {len(SLEEVES)} sleeves (10x):")
    print(f"    daily avg: ${daily_avg*10:+.2f}")
    print(f"    monthly:   ${daily_avg*300:+.2f}")
    print(f"    annual:    ${daily_avg*3650:+.2f}")
    print(f"PROJECTION at $1000 notional × {len(SLEEVES)} sleeves (40x):")
    print(f"    daily avg: ${daily_avg*40:+.2f}")
    print(f"    monthly:   ${daily_avg*1200:+.2f}")
    print(f"    annual:    ${daily_avg*14600:+.2f}")


if __name__ == "__main__":
    main()
