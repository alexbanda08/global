"""V3 backtest — improvements over v1/v2:

  1. Hyperliquid fee model: 4.5bp taker per side + 1.5bp slippage estimate = ~12bp RT
  2. Regime filter: only enter when price > 200-day MA (risk-on)
  3. Composite signal: z_lsr<-1.5 AND brigalS<-1.0 (both edges from diagnose.py)
  4. Stop-loss: -8% intraday hard stop (caps left tail)
  5. Per-asset tuned z-threshold (BTC: -2.0, ETH: -1.5, SOL: -1.5)
  6. Vol-targeted sizing: notional = 1.0 × (target_vol / realized_vol_30d), capped 0.5–1.5×

Tests multiple variants in one sweep so we can see which improvement matters.

Hyperliquid fee schedule (retail base tier, USDC perps):
  - Taker:  0.045% per side = 4.5 bps
  - Maker:  0.015% per side = 1.5 bps
  - Slippage estimate on liquid BTC/ETH/SOL: 1–2 bps
  Round-trip taker total: ~10-12 bps. We use 12 bps as the default cost.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))

PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"
SPOT = ROOT / "data" / "v4" / "derivatives_zscore" / "spot"
REPORTS = ROOT / "strategy_lab" / "reports" / "derivatives_zscore"
REPORTS.mkdir(parents=True, exist_ok=True)

HYPERLIQUID_TAKER_BPS = 4.5      # per side
HYPERLIQUID_SLIPPAGE_BPS = 1.5   # per side estimate on liquid majors
DEFAULT_FEE_BPS = HYPERLIQUID_TAKER_BPS + HYPERLIQUID_SLIPPAGE_BPS  # 6.0 per side, 12 RT


def load_h(symbol: str) -> pd.DataFrame:
    p = pd.read_parquet(PANELS / f"{symbol}_zscore.parquet").resample("1h").last()
    tag = symbol.replace("USDT", "")
    spot = pd.read_parquet(SPOT / f"BINANCE-{tag}-1h.parquet").set_index("time")["close"].astype(float)
    p["price"] = spot.reindex(p.index, method="ffill")
    # Add 200-day MA filter (4800h) and 30d realized vol (720h) for sizing
    p["ma_200d"] = p["price"].rolling(200 * 24, min_periods=200 * 24).mean()
    p["ret_1h"] = p["price"].pct_change()
    p["realized_vol_30d"] = p["ret_1h"].rolling(30 * 24, min_periods=30 * 24).std() * np.sqrt(24 * 365)
    return p.dropna(subset=["price", "z_lsr", "score_bull_scaled"])


# ────────────────────────────────────────────────────────────
#  Variant definitions
# ────────────────────────────────────────────────────────────

def make_entry_fn(variant: str, z_thr: float):
    """Returns a function row_dict -> bool for entry logic."""
    if variant == "V1_baseline":
        return lambda r: r["z_lsr"] < z_thr
    if variant == "V2_ma_filter":
        return lambda r: (r["z_lsr"] < z_thr) and (r["price"] > r.get("ma_200d", 0) if not pd.isna(r.get("ma_200d", float("nan"))) else False)
    if variant == "V3_composite":
        return lambda r: (r["z_lsr"] < z_thr) and (r["brigalS"] < -1.0)
    if variant == "V4_composite_ma":
        return lambda r: (r["z_lsr"] < z_thr) and (r["brigalS"] < -1.0) \
            and (r["price"] > r.get("ma_200d", 0) if not pd.isna(r.get("ma_200d", float("nan"))) else False)
    if variant == "V5_composite_ma_sl":
        return lambda r: (r["z_lsr"] < z_thr) and (r["brigalS"] < -1.0) \
            and (r["price"] > r.get("ma_200d", 0) if not pd.isna(r.get("ma_200d", float("nan"))) else False)
    if variant == "V6_zlsr_zfund":
        # Independent composite: extreme bearish LSR + negative funding (shorts paying)
        return lambda r: (r["z_lsr"] < z_thr) and (r["z_fund"] < -0.5)
    if variant == "V7_zlsr_zfund_sl":
        return lambda r: (r["z_lsr"] < z_thr) and (r["z_fund"] < -0.5)
    if variant == "V8_zlsr_oisilent":
        # z_lsr (positioning) + z_oi_silent (smart-money accumulation) — both independent
        return lambda r: (r["z_lsr"] < z_thr) and (r["z_oi_silent"] > 1.0)
    raise ValueError(variant)


def vol_scale_size(realized_vol: float, target_vol: float = 0.50) -> float:
    """Scale position size inversely to realized vol. Capped 0.5–1.5×."""
    if realized_vol is None or np.isnan(realized_vol) or realized_vol <= 0:
        return 1.0
    s = target_vol / realized_vol
    return float(np.clip(s, 0.5, 1.5))


def run_variant(df: pd.DataFrame, variant: str, z_thr: float = -1.5,
                hold_h: int = 24, fee_bps_per_side: float = DEFAULT_FEE_BPS / 2,
                stop_loss_pct: float = -0.08, use_vol_sizing: bool = False):
    """Run one variant. Returns (equity, trades, hourly_rets)."""
    fee = fee_bps_per_side / 1e4
    use_sl = "_sl" in variant
    entry_fn = make_entry_fn(variant, z_thr)

    pos = 0
    entry_px = None
    entry_t = None
    entry_idx = None
    pos_size = 1.0  # multiplier on equity exposure
    cash = 1.0
    eq_log = np.empty(len(df), dtype=float)
    rows = list(df.itertuples(index=True))
    trades = []

    for i, r in enumerate(rows):
        ts, px = r.Index, r.price
        # mark-to-market
        if pos == 1:
            mkt_ret = (px / entry_px - 1) * pos_size
            mkt_eq = cash * (1 + mkt_ret)
            eq_log[i] = mkt_eq
        else:
            mkt_ret = 0.0
            mkt_eq = cash
            eq_log[i] = cash

        # exit conditions (priority order: stop-loss, then time-based)
        exit_now = False
        exit_reason = None
        if pos == 1:
            if use_sl and mkt_ret <= stop_loss_pct:
                exit_now = True
                exit_reason = "stop_loss"
            elif (i - entry_idx) >= hold_h:
                exit_now = True
                exit_reason = "time"
        if exit_now:
            net_ret = (px / entry_px - 1) * pos_size - 2 * fee
            cash *= (1 + net_ret)
            trades.append(dict(entry_t=entry_t, exit_t=ts, side="long",
                               entry_px=float(entry_px), exit_px=float(px),
                               ret=float(net_ret), pos_size=float(pos_size),
                               hours=float((ts - entry_t).total_seconds() / 3600),
                               reason=exit_reason))
            pos = 0
            entry_px = None
            pos_size = 1.0

        # entry
        if pos == 0:
            row_dict = {"z_lsr": r.z_lsr, "brigalS": r.brigalS, "z_fund": r.z_fund,
                        "z_oi_silent": r.z_oi_silent, "price": r.price,
                        "ma_200d": r.ma_200d, "score_bull_scaled": r.score_bull_scaled}
            if entry_fn(row_dict):
                pos = 1
                entry_px = px
                entry_t = ts
                entry_idx = i
                if use_vol_sizing:
                    pos_size = vol_scale_size(r.realized_vol_30d)

    eq = pd.Series(eq_log, index=df.index, name="equity")
    rets = eq.pct_change().fillna(0)
    return eq, trades, rets


def summarize(name: str, sym: str, df: pd.DataFrame, eq: pd.Series, trades: list, rets: pd.Series) -> dict:
    bh = float(df["price"].iloc[-1] / df["price"].iloc[0])
    if not trades:
        return {"variant": name, "symbol": sym, "n_trades": 0, "buy_hold_x": bh,
                "final_eq_x": 1.0, "outperform": 1.0 / bh}
    tr_rets = np.array([t["ret"] for t in trades])
    wins = tr_rets > 0
    daily = eq.resample("1D").last().dropna()
    drets = daily.pct_change().dropna()
    sharpe = drets.mean() / drets.std() * np.sqrt(365) if drets.std() > 0 else 0.0
    peak = eq.cummax()
    dd = (eq - peak) / peak
    n_sl = sum(1 for t in trades if t.get("reason") == "stop_loss")
    pf = float(tr_rets[wins].sum() / -tr_rets[~wins].sum()) if (~wins).any() else float("inf")
    return {
        "variant": name,
        "symbol": sym,
        "n_trades": len(trades),
        "n_stopped": n_sl,
        "win_rate": float(wins.mean()),
        "expectancy_pct": float(tr_rets.mean() * 100),
        "profit_factor": pf,
        "sharpe": float(sharpe),
        "max_dd_pct": float(dd.min() * 100),
        "final_eq_x": float(eq.iloc[-1]),
        "buy_hold_x": bh,
        "outperform": float(eq.iloc[-1] / bh),
        "median_hold_h": float(np.median([t["hours"] for t in trades])),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--fee-bps-rt", type=float, default=DEFAULT_FEE_BPS * 2,
                    help="round-trip fee in bps; default 12 (Hyperliquid taker + slippage)")
    args = ap.parse_args()

    fee_per_side = args.fee_bps_rt / 2

    # Per-asset z-threshold tuning (BTC needs more extreme, SOL/ETH ok at -1.5)
    z_per_sym = {"BTCUSDT": -2.0, "ETHUSDT": -1.5, "SOLUSDT": -1.5}

    rows = []
    for sym in args.symbols:
        df = load_h(sym)
        z_thr = z_per_sym.get(sym, -1.5)
        bh = df["price"].iloc[-1] / df["price"].iloc[0]
        print(f"\n══════ {sym}  z_thr={z_thr}  bars={len(df):,}  buy-hold={bh:.2f}× ══════")
        print(f"  fee model: {args.fee_bps_rt:.1f}bp RT (Hyperliquid taker {HYPERLIQUID_TAKER_BPS}bp + slip {HYPERLIQUID_SLIPPAGE_BPS}bp per side)")
        print(f"  {'variant':<22} {'n':>4} {'sl':>3} {'wr':>6} {'exp%':>7} {'pf':>5} {'sharpe':>7} {'mdd%':>7} {'eq×':>7} {'vs B&H':>7}")
        for variant in ["V1_baseline", "V2_ma_filter", "V5_composite_ma_sl",
                        "V6_zlsr_zfund", "V7_zlsr_zfund_sl", "V8_zlsr_oisilent"]:
            for use_vol in ([False, True] if variant in ("V5_composite_ma_sl", "V7_zlsr_zfund_sl") else [False]):
                eq, trades, rets = run_variant(df, variant, z_thr=z_thr,
                                               hold_h=24,
                                               fee_bps_per_side=fee_per_side,
                                               use_vol_sizing=use_vol)
                tag = f"{variant}{'_volsz' if use_vol else ''}"
                s = summarize(tag, sym, df, eq, trades, rets)
                rows.append(s)
                print(f"  {tag:<22} {s.get('n_trades',0):>4} {s.get('n_stopped',0):>3} "
                      f"{s.get('win_rate',0)*100:>6.1f} "
                      f"{s.get('expectancy_pct',0):>+7.3f} "
                      f"{s.get('profit_factor',0):>5.2f} "
                      f"{s.get('sharpe',0):>+7.2f} "
                      f"{s.get('max_dd_pct',0):>+7.1f} "
                      f"{s.get('final_eq_x',1):>7.3f} "
                      f"{s.get('outperform',0):>7.3f}")

    out = pd.DataFrame(rows)
    out.to_csv(REPORTS / "v3_variants_summary.csv", index=False)
    print(f"\nWrote {len(out)} rows to {REPORTS/'v3_variants_summary.csv'}")


if __name__ == "__main__":
    main()
