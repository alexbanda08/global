"""Drawdown + live-mimic stress test of the top VWAP continuation config.

Top config: BTC 240s offset, 5-10bps dev, M1V Markov gate, 539 fires, 86.6% WR.

Tests:
  1. Time-ordered PnL curve → max DD, longest losing streak, Sharpe-like.
  2. Live-mimic re-fill — HYPOTHETICAL `0.07·p·(1−p)`-per-share fee curve
     + 85ms latency. NOTE: this is NOT production fees (per CLAUDE.md
     production = 2%-on-profit-only via LegacyConfig, verified vs 25,900
     prod resolutions). Live-mimic is a worst-case stress test only.
  3. Out-of-sample split: train on first 70% of days, test on last 30%.
  4. Same analysis for the top 5 deployable configs side-by-side.

Output:
  data/v4/canonical/_results/vwap_drawdown_livemimic.csv (per-config metrics)
  strategy_lab/reports/VWAP_DRAWDOWN_LIVEMIMIC_2026_05_23.md
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra/Desktop/global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import LegacyConfig, LiveMimicConfig, fill_at_book, hold_pnl  # noqa: E402

PT = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_continuation_5m_per_fire.parquet"
# Need the v2 gated table to know which configs hit which fires.
# Easier path: rebuild the top configs filter from raw per-fire data.

OUT_MD = ROOT / "strategy_lab" / "reports" / "VWAP_DRAWDOWN_LIVEMIMIC_2026_05_23.md"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_drawdown_livemimic.csv"


# Top 5 configs to validate. Each is a (cell, fire_offset, dev_tier, gate) filter.
# Re-derive M1V regime per fire if needed using the same logic as v2_gated.

def main() -> int:
    print(f"[1] loading per-fire parquet {PT}...")
    pt = pd.read_parquet(PT)
    print(f"    {len(pt):,} fires")
    # Need m1v_regime + f7 — re-derive from 1s data the same way v2_gated does.
    # Easier: load v2_gated table and pick out the rows matching each config.
    # That table has aggregated stats, not per-fire. Need to recompute per-fire flags.
    # SHORTCUT: recompute m1v + f7 on the fly here matching v2_gated.

    print(f"[2] computing m1v + f7 per fire (matching v2_gated)...")
    from load import load_klines_asof
    sys.path.insert(0, str(ROOT / "strategy_lab" / "markov_filter"))
    from markov_regime_micro import build_labels_for_asset, regime_at_us, BEAR, BULL

    klines_1m = {}
    markov = {}
    for a in ("BTC", "ETH", "SOL"):
        eu, cl = load_klines_asof(a, "binance-spot-ws", "1MIN")
        klines_1m[a] = (eu.astype("int64"), cl.astype("float64"))
        m_eu, _, m_lab = build_labels_for_asset(a, window_bars=20, bar_minutes=1, mode="vol_adaptive")
        markov[a] = (m_eu.astype("int64"), m_lab.astype("int8"))

    def rsi_at_anchor(eu, cl, anchor_us):
        closes = []
        for off_s in range(-840, 1, 60):
            idx = int(np.searchsorted(eu, anchor_us + off_s * 1_000_000, side="right")) - 1
            if idx < 0 or idx >= len(cl):
                closes.append(float("nan"))
                continue
            closes.append(float(cl[idx]))
        if any(not math.isfinite(c) or c <= 0 for c in closes) or len(closes) < 15:
            return float("nan")
        arr = np.asarray(closes, dtype=np.float64)
        log_rets = np.log(arr[1:] / arr[:-1])
        gains = np.where(log_rets > 0, log_rets, 0.0).mean()
        losses = np.where(log_rets < 0, -log_rets, 0.0).mean()
        if losses == 0:
            return 100.0 if gains > 0 else 50.0
        if gains == 0:
            return 0.0
        rs = gains / losses
        return 100.0 - 100.0 / (1.0 + rs)

    pt = pt.reset_index(drop=True)
    pt["m1v_regime"] = -1
    pt["rsi_14"] = np.nan
    for i in range(len(pt)):
        r = pt.iloc[i]
        a = r.asset
        fu = int(r.fire_us)
        pt.at[i, "rsi_14"] = rsi_at_anchor(*klines_1m[a], fu)
        m_eu, m_lab = markov[a]
        pt.at[i, "m1v_regime"] = regime_at_us(m_eu, m_lab, fu)

    pt["f7_pass"] = np.where(pt.direction == "UP", pt.rsi_14 > 50, pt.rsi_14 < 50)
    pt["m1v_pass"] = np.where(pt.direction == "UP", pt.m1v_regime == BULL, pt.m1v_regime == BEAR)
    pt["abs_dev"] = pt.dev_bps.abs()

    # Filter to the TOP config: BTC 240s 5-10bps + M1V
    print(f"\n[3] applying top-5 configs and computing drawdown...")
    configs = [
        ("BTC_240_5-10bps_m1v",
         lambda d: (d.asset == "BTC") & (d.fire_offset_s == 240) & (d.abs_dev > 5) & (d.abs_dev <= 10) & d.m1v_pass),
        ("BTC_60_10-15bps_f7_cross",
         lambda d: (d.asset == "BTC") & (d.fire_offset_s == 60) & (d.abs_dev > 10) & (d.abs_dev <= 15) & d.f7_pass),
        ("BTC_90_10-15bps_none",
         lambda d: (d.asset == "BTC") & (d.fire_offset_s == 90) & (d.abs_dev > 10) & (d.abs_dev <= 15)),
        ("ETH_210_10-15bps_f7_m1v",
         lambda d: (d.asset == "ETH") & (d.fire_offset_s == 210) & (d.abs_dev > 10) & (d.abs_dev <= 15) & d.f7_pass & d.m1v_pass),
        ("SOL_60_20-30bps_none",
         lambda d: (d.asset == "SOL") & (d.fire_offset_s == 60) & (d.abs_dev > 20) & (d.abs_dev <= 30)),
    ]

    rows = []
    per_config_curves = {}
    for cname, filt in configs:
        kept = pt[filt(pt)].copy().sort_values("fire_s").reset_index(drop=True)
        if len(kept) == 0:
            print(f"  {cname}: n=0 — skip")
            continue
        # Time-ordered PnL curve
        kept["cum_pnl"] = kept["pnl_legacy_usd"].cumsum()
        kept["peak"] = kept["cum_pnl"].cummax()
        kept["dd"] = kept["cum_pnl"] - kept["peak"]
        max_dd = float(kept["dd"].min())
        # Longest loss streak
        wins = kept["pnl_legacy_usd"] > 0
        cur_loss = max_loss_streak = 0
        for w in wins.values:
            if not w:
                cur_loss += 1
                max_loss_streak = max(max_loss_streak, cur_loss)
            else:
                cur_loss = 0
        # Daily PnL
        kept["date"] = pd.to_datetime(kept["fire_s"], unit="s", utc=True).dt.date
        daily = kept.groupby("date")["pnl_legacy_usd"].sum()
        daily_mean = float(daily.mean()) if len(daily) else 0.0
        daily_std = float(daily.std()) if len(daily) > 1 else 0.0
        sharpe_like = (daily_mean / daily_std * math.sqrt(365)) if daily_std > 0 else float("nan")
        # OOS split — train 70%, test 30%
        n = len(kept)
        cut = int(n * 0.7)
        train = kept.iloc[:cut]
        test = kept.iloc[cut:]
        train_wr = float(train.won.mean()) if len(train) else float("nan")
        test_wr = float(test.won.mean()) if len(test) else float("nan")
        train_pnl_mean = float(train.pnl_legacy_usd.mean()) if len(train) else float("nan")
        test_pnl_mean = float(test.pnl_legacy_usd.mean()) if len(test) else float("nan")

        rows.append({
            "config": cname,
            "n": len(kept),
            "wr": float(kept.won.mean()),
            "avg_pnl_legacy": float(kept.pnl_legacy_usd.mean()),
            "sum_pnl_legacy": float(kept.pnl_legacy_usd.sum()),
            "max_dd": max_dd,
            "max_loss_streak": int(max_loss_streak),
            "daily_pnl_mean": daily_mean,
            "daily_pnl_std": daily_std,
            "sharpe_like_annual": sharpe_like,
            "train_wr": train_wr, "test_wr": test_wr,
            "train_avg_pnl": train_pnl_mean, "test_avg_pnl": test_pnl_mean,
            "n_days": int(len(daily)),
        })
        per_config_curves[cname] = kept[["fire_s", "cum_pnl", "peak", "dd"]].copy()
        print(f"  {cname}: n={len(kept)}  WR={kept.won.mean()*100:.1f}%  sum=${kept.pnl_legacy_usd.sum():.0f}  "
              f"max_DD=${max_dd:.0f}  loss_streak={max_loss_streak}  Sharpe={sharpe_like:.2f}  "
              f"train_WR={train_wr*100:.1f} test_WR={test_wr*100:.1f}")

    # ---- Live-mimic refill for top config ----
    print(f"\n[4] live-mimic refill of TOP config (BTC 240s 5-10bps M1V)...")
    top_cname = "BTC_240_5-10bps_m1v"
    top_filt = configs[0][1]
    top_rows = pt[top_filt(pt)].copy().sort_values("fire_s").reset_index(drop=True)
    print(f"    n={len(top_rows)} fires to re-fill...")
    # Load BTC L25 books for these slugs
    slugs_top = set(top_rows["slug"].unique())
    print(f"    loading L25 for {len(slugs_top)} slugs...")
    books_idx = load_orderbook_l25_streaming("BTC", slugs=slugs_top, subsample_1hz=True)
    print(f"    loaded {len(books_idx)} (slug, outcome) keys")
    cfg_live = LiveMimicConfig()
    pnl_live = np.full(len(top_rows), np.nan)
    won_live = np.zeros(len(top_rows), dtype=bool)
    entry_live = np.full(len(top_rows), np.nan)
    for i, r in top_rows.iterrows():
        outcome_to_fill = "Up" if r.direction == "UP" else "Down"
        try:
            fill = fill_at_book(books_idx, r.slug, outcome_to_fill, int(r.fire_us),
                                cfg=cfg_live, spread_filter=0.02)
        except Exception:
            fill = None
        if fill is None:
            continue
        won = (r.outcome == "Up") if r.direction == "UP" else (r.outcome == "Down")
        pnl = hold_pnl(fill, won=won, cfg=cfg_live)
        pnl_live[i] = pnl
        won_live[i] = won
        entry_live[i] = float(fill["vwap"])
    top_rows["pnl_live"] = pnl_live
    top_rows["entry_live"] = entry_live
    live_filled = top_rows[top_rows.pnl_live.notna()]
    live_wr = float(live_filled.won.mean())
    live_avg = float(live_filled.pnl_live.mean())
    live_sum = float(live_filled.pnl_live.sum())
    print(f"    LIVE-MIMIC: n={len(live_filled)}  WR={live_wr*100:.1f}%  avg=${live_avg:.3f}  sum=${live_sum:.0f}")
    rows[0]["live_mimic_n"] = len(live_filled)
    rows[0]["live_mimic_wr"] = live_wr
    rows[0]["live_mimic_avg_pnl"] = live_avg
    rows[0]["live_mimic_sum_pnl"] = live_sum

    df_summary = pd.DataFrame(rows)
    df_summary.to_csv(OUT_CSV, index=False)
    print(f"\nSaved: {OUT_CSV}")
    print(df_summary.to_string(index=False))

    # Markdown
    md = []
    md.append(f"# VWAP continuation — drawdown + live-mimic ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")
    md.append("")
    md.append("Stress test of the top 5 deployable VWAP continuation configs on 28d data.")
    md.append("")
    md.append("## Summary table")
    md.append("")
    md.append(df_summary.round(3).to_markdown(index=False))
    md.append("")
    md.append("## Interpretation")
    md.append("")
    md.append("- **max_dd** is the worst peak-to-trough drawdown on the cumulative PnL curve, in $ at $25 notional.")
    md.append("- **max_loss_streak** is the longest consecutive losing trade run.")
    md.append("- **sharpe_like_annual** = (mean daily PnL / std daily PnL) × √365. Treats trades as IID — directional but useful.")
    md.append("- **train_wr / test_wr** is a 70/30 walk-forward split (NOT random shuffle — chronological).")
    md.append("- **live_mimic_***: hypothetical `0.07·p·(1−p)`-per-share fee curve (Polymarket general docs) + 85ms latency. NOT production fees. Per CLAUDE.md, production = 2%-on-profit-only (LegacyConfig column), verified vs 25,900 prod resolutions. Live-mimic is a worst-case stress test only.")
    md.append("")
    md.append("## Deployability verdict")
    md.append("")
    md.append("If `live_mimic_sum_pnl > 0` AND `test_wr >= 60%` AND `max_dd / sum_pnl > -0.3` (DD < 30% of total profit), config is deploy-ready.")
    md.append("")
    md.append(f"_data: `{OUT_CSV.relative_to(ROOT)}`_  ")
    md.append(f"_script: `strategy_lab/meta_classifier/vwap_drawdown_livemimic.py`_")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Report: {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
