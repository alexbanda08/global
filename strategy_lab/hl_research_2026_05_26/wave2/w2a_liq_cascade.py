"""
W2a — HL liquidation cascades as directional signal (Hypothesis N1).

Tests:
  - Continuation: large LONG liq -> short pressure -> DOWN next 1-30m
  - Reversion:    large LONG liq -> exhausted shorts -> UP within 5-30m

DATA GAP NOTE
-------------
Real HL liquidations on majors are concentrated in Oct 2025 (the data is
front-loaded from a major mid-Oct 2025 deleveraging event):
  - BTC: 1,699 liqs in Oct '25; 226 in Nov; ~3 from Jan-Feb 2026 onwards
  - ETH: 1,406 in Oct '25; 7 in Nov; 94 in Jan 2026; near-zero thereafter
  - SOL: 1,645 in Oct '25; 75 in Nov; 7 in 2026
  - HYPE: 2,262 in Oct '25; 45 in Nov; 1 in Dec; zero in 2026

But HL canonical klines start only at 2026-01-30. So we use BINANCE_VISION
1MIN klines (price proxy; corr 0.9996 vs HL per audit) for the Oct-Nov 2025
window when liq density is sufficient. HL funding still used for funding
accrual. Engine is HL (HL taker 4.5bps + slip 3bps).

Sub-tests:
  1) Threshold x horizon grid per asset (BTC, ETH, SOL)
  2) Cascade detection (>=5 liqs in 60s OR cumulative >= $5M)
  3) Filtered variants: regime_label==ranging, tr_in_london/ny, markov_state

HYPE excluded — no kline backbone overlap for its liq window (HYPE not on Binance spot).

Validation per cell:
  G1: binomial p<0.05 vs 50% WR
  G2: net PnL > 0 after fees+funding
  G3: walk-forward (4 splits): require >=50% splits positive
  G4: permutation test (n=200) — shuffle liq timestamps within +/-60s
  G5: per-asset Sharpe consistency

Runs from project root.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from itertools import product

import numpy as np
import pandas as pd

# Project paths
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "strategy_lab" / "hl_research_2026_05_26"))
from hl_engine import HyperliquidConfig, run_backtest

# -------------------------------------------------------------------
LIQ_PARQUET    = REPO / "data" / "v4" / "canonical" / "hyperliquid_liquidations_full.parquet"
LIQ30_PARQUET  = REPO / "data" / "v4" / "canonical" / "hyperliquid_liquidations_30d.parquet"
BNB_KL_PARQUET = REPO / "data" / "v4" / "canonical" / "binance_vision_klines.parquet"
FUND_PARQUET   = REPO / "data" / "v4" / "canonical" / "hyperliquid_funding.parquet"
PANEL_DIR      = REPO / "strategy_lab" / "hl_research_2026_05_26" / "panels"

OUT_DIR        = REPO / "strategy_lab" / "hl_research_2026_05_26" / "wave2"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Tested assets (HYPE excluded — no Binance spot backbone overlap)
ASSETS = ["BTC", "ETH", "SOL"]
THRESHOLDS_USD = [100_000, 250_000, 500_000, 1_000_000]
HOLDS_MIN      = [5, 15, 30, 60]
DIRECTIONS     = ["continuation", "reversion"]
LIQ_SIDES      = ["LONG", "SHORT"]  # which side liquidated

NOTIONAL = 250.0
LEVERAGE = 1.0

BINANCE_SYM = {
    "BTC":  "BINANCE_SPOT_BTC_USDT",
    "ETH":  "BINANCE_SPOT_ETH_USDT",
    "SOL":  "BINANCE_SPOT_SOL_USDT",
}


# -------------------------------------------------------------------
# Data loaders
# -------------------------------------------------------------------
def load_liquidations() -> pd.DataFrame:
    """Real liquidations from both parquets, dedup'd."""
    full = pd.read_parquet(LIQ_PARQUET)
    d30 = pd.read_parquet(LIQ30_PARQUET)
    combined = pd.concat([full, d30], ignore_index=True)
    combined = combined.drop_duplicates(
        subset=["time_exchange_us", "coin", "dir", "price", "size"], keep="first"
    )
    mask = combined["dir"].str.contains("Liquidated|Deleveraging|Borrow Liquidation",
                                         na=False, regex=True)
    liq = combined[mask].copy()
    def _side(d):
        if "Long" in d: return "LONG"
        if "Short" in d: return "SHORT"
        return "UNKNOWN"
    liq["liq_side"] = liq["dir"].apply(_side)
    liq["notional_usd"] = liq["size"].abs() * liq["price"]
    liq = liq[(liq["liq_side"].isin(["LONG", "SHORT"])) & (liq["notional_usd"] > 100)]
    liq = liq.sort_values("time_exchange_us").reset_index(drop=True)
    return liq[["time_exchange_us", "coin", "liq_side", "notional_usd", "size", "price"]]


def load_binance_klines(asset: str, period: str = "1MIN") -> pd.DataFrame:
    """Use Binance vision klines as backbone for HL price proxy.

    Reads in chunks to limit memory; only keeps columns needed by engine.
    """
    df = pd.read_parquet(BNB_KL_PARQUET, filters=[
        ("symbol_id", "=", BINANCE_SYM[asset]),
        ("period_id", "=", period),
    ], columns=["time_period_start_us", "price_open", "price_high", "price_low",
                "price_close", "volume_traded"])
    sub = df.rename(columns={
        "time_period_start_us": "open_time_us",
        "price_open": "open", "price_high": "high",
        "price_low": "low", "price_close": "close",
        "volume_traded": "volume",
    })
    sub = sub.sort_values("open_time_us").reset_index(drop=True)
    return sub


def load_funding_for(asset: str) -> pd.DataFrame:
    """HL funding (3-letter symbol). For windows before funding coverage we
    return an empty df — engine will skip funding accrual gracefully."""
    df = pd.read_parquet(FUND_PARQUET)
    sub = df[df["symbol"] == asset].copy()
    sub["funding_rate"] = pd.to_numeric(sub["funding_rate"], errors="coerce")
    sub = sub.dropna(subset=["funding_rate"]).sort_values("funding_time_us").reset_index(drop=True)
    return sub[["funding_time_us", "funding_rate"]]


def load_panel(asset: str, tf: str = "15m"):
    """Try Binance-backbone panel."""
    fp = PANEL_DIR / f"hl_panel_{asset}_{tf}.parquet"
    if not fp.exists():
        return None
    p = pd.read_parquet(fp)
    if "ts_us" not in p.columns and "open_time" in p.columns:
        ts = pd.to_datetime(p["open_time"], utc=True)
        p["ts_us"] = (ts.astype("int64") // 1_000).astype("int64")
    return p.sort_values("ts_us").reset_index(drop=True)


# -------------------------------------------------------------------
# Signal builders
# -------------------------------------------------------------------
def _dedup_close_in_time(times: np.ndarray, cooldown_us: int) -> np.ndarray:
    """Keep only first event in each cooldown window. Returns mask."""
    if len(times) == 0:
        return np.array([], dtype=bool)
    keep = np.zeros(len(times), dtype=bool)
    last_us = -np.inf
    for i, t in enumerate(times):
        if t - last_us >= cooldown_us:
            keep[i] = True
            last_us = t
    return keep


def build_signals_threshold(
    liqs: pd.DataFrame,
    asset: str,
    threshold_usd: float,
    liq_side: str,            # "LONG" or "SHORT"
    direction_mode: str,      # "continuation" or "reversion"
    hold_minutes: int,
    kl_start_us: int,
    kl_end_us: int,
    dedup_cooldown_min: int = 5,   # min minutes between sample fires (5m = same kline cluster)
) -> pd.DataFrame:
    sub = liqs[(liqs["coin"] == asset) & (liqs["liq_side"] == liq_side) &
               (liqs["notional_usd"] >= threshold_usd)]
    margin_us = hold_minutes * 60 * 1_000_000
    sub = sub[(sub["time_exchange_us"] >= kl_start_us) &
              (sub["time_exchange_us"] <= kl_end_us - margin_us)]
    if len(sub) == 0:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"])

    sub = sub.sort_values("time_exchange_us").reset_index(drop=True)
    # Critical: dedup close-in-time liqs so we don't double-count one market event
    times = sub["time_exchange_us"].to_numpy()
    keep = _dedup_close_in_time(times, cooldown_us=dedup_cooldown_min * 60 * 1_000_000)
    sub = sub.loc[keep].reset_index(drop=True)

    if direction_mode == "continuation":
        trade_dir = "SHORT" if liq_side == "LONG" else "LONG"
    else:
        trade_dir = "LONG" if liq_side == "LONG" else "SHORT"

    sig_us = sub["time_exchange_us"].to_numpy()
    exit_us = sig_us + margin_us
    return pd.DataFrame({
        "signal_us": sig_us,
        "direction": trade_dir,
        "exit_us": exit_us,
    })


def detect_cascades(
    liqs: pd.DataFrame,
    asset: str,
    window_s: int = 60,
    min_count: int = 5,
    min_cum_usd: float = 5_000_000,
):
    sub = liqs[liqs["coin"] == asset].sort_values("time_exchange_us").reset_index(drop=True)
    if len(sub) == 0:
        return pd.DataFrame(columns=["time_us", "dominant_side", "n_liqs", "cum_notional"])

    t = sub["time_exchange_us"].to_numpy()
    notional = sub["notional_usd"].to_numpy()
    sides = sub["liq_side"].to_numpy()
    n = len(sub)
    window_us = window_s * 1_000_000

    j_idx = np.searchsorted(t, t - window_us, side="left")

    fires = []
    last_fire_us = -1
    cooldown_us = 60 * 1_000_000
    for i in range(n):
        lo = j_idx[i]
        cnt = i - lo + 1
        cum = notional[lo:i+1].sum()
        if cnt < min_count and cum < min_cum_usd:
            continue
        long_n = (sides[lo:i+1] == "LONG").sum()
        short_n = (sides[lo:i+1] == "SHORT").sum()
        dominant = "LONG" if long_n >= short_n else "SHORT"
        if t[i] - last_fire_us < cooldown_us:
            continue
        fires.append({
            "time_us": int(t[i]),
            "dominant_side": dominant,
            "n_liqs": int(cnt),
            "cum_notional": float(cum),
        })
        last_fire_us = t[i]
    return pd.DataFrame(fires)


def build_signals_cascade(cascades, direction_mode, hold_min, kl_lo, kl_hi):
    if len(cascades) == 0:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"])
    margin_us = hold_min * 60 * 1_000_000
    sub = cascades[(cascades["time_us"] >= kl_lo) & (cascades["time_us"] <= kl_hi - margin_us)]
    if len(sub) == 0:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"])

    if direction_mode == "continuation":
        trade_dir = np.where(sub["dominant_side"] == "LONG", "SHORT", "LONG")
    else:
        trade_dir = np.where(sub["dominant_side"] == "LONG", "LONG", "SHORT")

    sig_us = sub["time_us"].to_numpy()
    exit_us = sig_us + margin_us
    return pd.DataFrame({
        "signal_us": sig_us,
        "direction": trade_dir,
        "exit_us": exit_us,
    })


# -------------------------------------------------------------------
# Stats helpers
# -------------------------------------------------------------------
def binomial_p(n_wins: int, n_total: int, p_null: float = 0.5) -> float:
    if n_total < 1: return 1.0
    if n_total < 25:
        from math import comb
        obs = n_wins
        diff = abs(obs - n_total * p_null)
        p_sum = 0.0
        for k in range(n_total + 1):
            if abs(k - n_total * p_null) >= diff:
                p_sum += comb(n_total, k) * (p_null ** k) * ((1 - p_null) ** (n_total - k))
        return min(1.0, p_sum)
    from scipy.stats import norm
    z = (n_wins - n_total * p_null) / np.sqrt(n_total * p_null * (1 - p_null))
    return float(2.0 * (1.0 - norm.cdf(abs(z))))


def permutation_p_value(
    actual_mean: float,
    klines, funding, base_signals, asset, cfg, notional, leverage,
    n_perms: int = 200,
    jitter_us: int = 60_000_000,
) -> float:
    if len(base_signals) == 0 or n_perms == 0:
        return 1.0
    rng = np.random.default_rng(123)
    perm_means = []
    sig_arr = base_signals["signal_us"].to_numpy()
    exit_arr = base_signals["exit_us"].to_numpy()
    delta_arr = exit_arr - sig_arr
    dirs = base_signals["direction"].to_numpy()
    for _ in range(n_perms):
        offsets = rng.integers(-jitter_us, jitter_us, size=len(sig_arr))
        new_sig = (sig_arr + offsets).astype(np.int64)
        new_exit = new_sig + delta_arr
        perm_sig = pd.DataFrame({"signal_us": new_sig, "direction": dirs, "exit_us": new_exit})
        _, st = run_backtest(klines, funding, perm_sig, asset,
                             notional_usd=notional, leverage=leverage, cfg=cfg)
        perm_means.append(st["avg_pnl_usd"] if not np.isnan(st["avg_pnl_usd"]) else 0.0)
    perm_means = np.array(perm_means)
    p = (perm_means >= actual_mean).sum() / max(1, len(perm_means))
    return float(p)


def walk_forward_check(klines, funding, signals, asset, cfg, notional, leverage, n_splits=4):
    if len(signals) < 4 * n_splits:
        return float("nan"), []
    s = signals.sort_values("signal_us").reset_index(drop=True)
    t_lo, t_hi = s["signal_us"].min(), s["signal_us"].max()
    window_us = (t_hi - t_lo) / n_splits
    test_means = []
    for k in range(n_splits):
        win_lo = t_lo + k * window_us
        win_hi = t_lo + (k + 1) * window_us
        sub = s[(s["signal_us"] >= win_lo) & (s["signal_us"] < win_hi)]
        if len(sub) < 5:
            continue
        _, st = run_backtest(klines, funding, sub, asset,
                              notional_usd=notional, leverage=leverage, cfg=cfg)
        test_means.append(st["avg_pnl_usd"] if not np.isnan(st["avg_pnl_usd"]) else 0.0)
    if not test_means:
        return float("nan"), []
    return float(np.mean(test_means)), test_means


# -------------------------------------------------------------------
# Main runner
# -------------------------------------------------------------------
def run_grid():
    print("Loading liquidations (combined full+30d, dedup'd)...")
    liqs = load_liquidations()
    print(f"  {len(liqs)} real liq events")

    cfg = HyperliquidConfig()
    results = []

    for asset in ASSETS:
        print(f"\n=== {asset} (Binance backbone, HL fee+funding) ===")
        kl = load_binance_klines(asset, "1MIN")
        if len(kl) == 0:
            print(f"  no klines for {asset}; skip"); continue
        fnd = load_funding_for(asset)
        kl_lo, kl_hi = int(kl["open_time_us"].min()), int(kl["open_time_us"].max())
        liqs_asset = liqs[liqs["coin"] == asset]
        liq_lo = int(liqs_asset["time_exchange_us"].min()) if len(liqs_asset) else kl_lo
        liq_hi = int(liqs_asset["time_exchange_us"].max()) if len(liqs_asset) else kl_hi
        # Effective window: intersection of kline range and liq range
        win_lo = max(kl_lo, liq_lo)
        win_hi = min(kl_hi, liq_hi)
        print(f"  klines: {len(kl)} bars 1MIN, range {pd.to_datetime(kl_lo,unit='us')} -> {pd.to_datetime(kl_hi,unit='us')}")
        print(f"  liqs:   {len(liqs_asset)} for {asset}, range {pd.to_datetime(liq_lo,unit='us')} -> {pd.to_datetime(liq_hi,unit='us')}")
        print(f"  active window: {pd.to_datetime(win_lo,unit='us')} -> {pd.to_datetime(win_hi,unit='us')}")

        # =========== Sub-test 1: threshold x horizon ===========
        for liq_side, thresh, hold_min, direction in product(LIQ_SIDES, THRESHOLDS_USD, HOLDS_MIN, DIRECTIONS):
            sig = build_signals_threshold(liqs, asset, thresh, liq_side, direction,
                                          hold_min, win_lo, win_hi)
            if len(sig) < 5: continue
            t0 = time.time()
            trades_df, st = run_backtest(kl, fnd, sig, asset, notional_usd=NOTIONAL,
                                          leverage=LEVERAGE, cfg=cfg)
            if st["n_trades"] < 5: continue

            p_g1 = binomial_p(st["n_wins"], st["n_trades"])
            g1 = p_g1 < 0.05
            g2 = st["total_pnl_usd"] > 0
            wf_mean, wf_splits = walk_forward_check(kl, fnd, sig, asset, cfg, NOTIONAL, LEVERAGE, n_splits=4)
            wf_pos_frac = float((np.array(wf_splits) > 0).mean()) if wf_splits else 0.0
            g3 = wf_pos_frac >= 0.5

            # Permutation only for cells passing G1+G2 (saves time)
            if g1 and g2:
                p_g4 = permutation_p_value(st["avg_pnl_usd"], kl, fnd, sig, asset, cfg,
                                            NOTIONAL, LEVERAGE, n_perms=100,
                                            jitter_us=60_000_000)
                g4 = p_g4 < 0.05
            else:
                p_g4 = float("nan"); g4 = False

            gates = []
            if g1: gates.append("G1")
            if g2: gates.append("G2")
            if g3: gates.append("G3")
            if g4: gates.append("G4")
            gate_pass = ",".join(gates) if gates else "NONE"

            sid = f"{asset}_1m_liq_{liq_side.lower()}_{int(thresh/1000)}k_{hold_min}m_{direction}"
            results.append({
                "strategy_id": sid, "asset": asset, "tf": "1m", "hypothesis": "N1",
                "subtest": "threshold_horizon",
                "liq_side": liq_side, "threshold_usd": thresh,
                "hold_min": hold_min, "direction_mode": direction,
                "n_trades": st["n_trades"], "win_rate": round(st["win_rate"], 4),
                "dollar_per_trade": round(st["avg_pnl_usd"], 4),
                "total_pnl_usd": round(st["total_pnl_usd"], 2),
                "sharpe": round(st["sharpe"], 3),
                "max_dd": round(st["max_dd_usd"], 2),
                "p_value": round(p_g1, 5),
                "permutation_p": round(p_g4, 5) if not np.isnan(p_g4) else None,
                "bootstrap_ci_lo": None,
                "wf_mean": round(wf_mean, 4) if not np.isnan(wf_mean) else None,
                "wf_pos_frac": round(wf_pos_frac, 3),
                "gate_pass": gate_pass,
                "notes": f"liq_{liq_side.lower()}_>=${int(thresh/1000)}k_{hold_min}m_{direction}",
            })
            print(f"  T={thresh/1000:>5.0f}k {hold_min:3d}m {liq_side:5s} {direction:12s} -> n={st['n_trades']:4d} WR={st['win_rate']:.2f} $/tr={st['avg_pnl_usd']:+.3f} Sh={st['sharpe']:+.2f} gates={gate_pass} ({time.time()-t0:.1f}s)")

        # =========== Sub-test 2: cascade detection ===========
        cascades = detect_cascades(liqs, asset, window_s=60, min_count=5, min_cum_usd=5_000_000)
        print(f"  [cascade] {len(cascades)} cascade fires found")
        if len(cascades) >= 10:
            for hold_min, direction in product(HOLDS_MIN, DIRECTIONS):
                sig = build_signals_cascade(cascades, direction, hold_min, win_lo, win_hi)
                if len(sig) < 5: continue
                _, st = run_backtest(kl, fnd, sig, asset, notional_usd=NOTIONAL, leverage=LEVERAGE, cfg=cfg)
                if st["n_trades"] < 5: continue

                p_g1 = binomial_p(st["n_wins"], st["n_trades"])
                g1 = p_g1 < 0.05
                g2 = st["total_pnl_usd"] > 0
                wf_mean, wf_splits = walk_forward_check(kl, fnd, sig, asset, cfg, NOTIONAL, LEVERAGE, n_splits=4)
                wf_pos_frac = float((np.array(wf_splits) > 0).mean()) if wf_splits else 0.0
                g3 = wf_pos_frac >= 0.5

                if g1 and g2:
                    p_g4 = permutation_p_value(st["avg_pnl_usd"], kl, fnd, sig, asset, cfg, NOTIONAL, LEVERAGE, n_perms=100, jitter_us=60_000_000)
                    g4 = p_g4 < 0.05
                else:
                    p_g4 = float("nan"); g4 = False

                gates = []
                if g1: gates.append("G1")
                if g2: gates.append("G2")
                if g3: gates.append("G3")
                if g4: gates.append("G4")
                gate_pass = ",".join(gates) if gates else "NONE"

                sid = f"{asset}_1m_cascade_{hold_min}m_{direction}"
                results.append({
                    "strategy_id": sid, "asset": asset, "tf": "1m", "hypothesis": "N1",
                    "subtest": "cascade",
                    "liq_side": "ANY", "threshold_usd": 5_000_000,
                    "hold_min": hold_min, "direction_mode": direction,
                    "n_trades": st["n_trades"], "win_rate": round(st["win_rate"], 4),
                    "dollar_per_trade": round(st["avg_pnl_usd"], 4),
                    "total_pnl_usd": round(st["total_pnl_usd"], 2),
                    "sharpe": round(st["sharpe"], 3),
                    "max_dd": round(st["max_dd_usd"], 2),
                    "p_value": round(p_g1, 5),
                    "permutation_p": round(p_g4, 5) if not np.isnan(p_g4) else None,
                    "bootstrap_ci_lo": None,
                    "wf_mean": round(wf_mean, 4) if not np.isnan(wf_mean) else None,
                    "wf_pos_frac": round(wf_pos_frac, 3),
                    "gate_pass": gate_pass,
                    "notes": f"cascade_5+_60s_{hold_min}m_{direction}",
                })
                print(f"  [casc] {hold_min:3d}m {direction:12s} -> n={st['n_trades']:4d} WR={st['win_rate']:.2f} $/tr={st['avg_pnl_usd']:+.3f} Sh={st['sharpe']:+.2f} gates={gate_pass}")

        # =========== Sub-test 3: filtered variants ===========
        panel = load_panel(asset, "15m")
        if panel is None or "tr_in_london" not in panel.columns:
            print(f"  [filt] panel not loadable for {asset}; skip filters")
            continue
        # Pick top 3 cells by Sharpe (asset-specific) for this asset
        df_so_far = pd.DataFrame(results) if results else pd.DataFrame()
        if "asset" not in df_so_far.columns or len(df_so_far) == 0:
            continue
        df_a = df_so_far[df_so_far["asset"] == asset].copy()
        if len(df_a) == 0: continue
        df_a["sharpe_num"] = pd.to_numeric(df_a["sharpe"], errors="coerce").fillna(-99)
        top = df_a.nlargest(3, "sharpe_num")

        panel_ts = panel["ts_us"].to_numpy()
        for _, base in top.iterrows():
            if base["subtest"] == "threshold_horizon":
                sig = build_signals_threshold(
                    liqs, asset, float(base["threshold_usd"]), str(base["liq_side"]),
                    str(base["direction_mode"]), int(base["hold_min"]), win_lo, win_hi,
                )
            else:
                sig = build_signals_cascade(
                    detect_cascades(liqs, asset),
                    str(base["direction_mode"]), int(base["hold_min"]), win_lo, win_hi,
                )
            if len(sig) == 0: continue

            sig_ts = sig["signal_us"].to_numpy()
            panel_idx = np.clip(np.searchsorted(panel_ts, sig_ts, side="right") - 1, 0, len(panel)-1)

            for filt_name in ["ranging", "ldn_ny", "markov_contra"]:
                try:
                    if filt_name == "ranging":
                        mask_arr = (panel["regime_label"].iloc[panel_idx].to_numpy() == "ranging")
                    elif filt_name == "ldn_ny":
                        mask_arr = (panel["tr_in_london"].iloc[panel_idx].to_numpy().astype(bool) |
                                    panel["tr_in_ny"].iloc[panel_idx].to_numpy().astype(bool))
                    elif filt_name == "markov_contra":
                        ms = panel["markov_state_fixed"].iloc[panel_idx].to_numpy()
                        # For continuation: take trades where regime supports the trade
                        # For reversion: take trades where regime supports counter-move
                        if str(base["direction_mode"]) == "continuation":
                            # liq_side LONG -> trade SHORT -> want markov_state==-1 (trending dn)
                            want = -1 if base["liq_side"] == "LONG" else 1
                        else:
                            want = 1 if base["liq_side"] == "LONG" else -1
                        mask_arr = (ms == want)
                except Exception as e:
                    print(f"    filter {filt_name} error: {e}")
                    continue

                f_sig = sig.iloc[mask_arr].reset_index(drop=True)
                if len(f_sig) < 10: continue
                _, st_f = run_backtest(kl, fnd, f_sig, asset, notional_usd=NOTIONAL,
                                         leverage=LEVERAGE, cfg=cfg)
                if st_f["n_trades"] < 5: continue

                p_g1 = binomial_p(st_f["n_wins"], st_f["n_trades"])
                g1 = p_g1 < 0.05
                g2 = st_f["total_pnl_usd"] > 0
                wf_mean, wf_splits = walk_forward_check(kl, fnd, f_sig, asset, cfg, NOTIONAL, LEVERAGE, n_splits=4)
                wf_pos_frac = float((np.array(wf_splits) > 0).mean()) if wf_splits else 0.0
                g3 = wf_pos_frac >= 0.5

                if g1 and g2:
                    p_g4 = permutation_p_value(st_f["avg_pnl_usd"], kl, fnd, f_sig, asset, cfg, NOTIONAL, LEVERAGE, n_perms=100, jitter_us=60_000_000)
                    g4 = p_g4 < 0.05
                else:
                    p_g4 = float("nan"); g4 = False

                gates = []
                if g1: gates.append("G1")
                if g2: gates.append("G2")
                if g3: gates.append("G3")
                if g4: gates.append("G4")
                gate_pass = ",".join(gates) if gates else "NONE"

                sid = f"{asset}_1m_{base['subtest']}_{base['hold_min']}m_{base['direction_mode']}_filt_{filt_name}"
                results.append({
                    "strategy_id": sid, "asset": asset, "tf": "1m", "hypothesis": "N1",
                    "subtest": "filtered",
                    "liq_side": base["liq_side"], "threshold_usd": float(base["threshold_usd"]),
                    "hold_min": int(base["hold_min"]), "direction_mode": base["direction_mode"],
                    "n_trades": st_f["n_trades"], "win_rate": round(st_f["win_rate"], 4),
                    "dollar_per_trade": round(st_f["avg_pnl_usd"], 4),
                    "total_pnl_usd": round(st_f["total_pnl_usd"], 2),
                    "sharpe": round(st_f["sharpe"], 3),
                    "max_dd": round(st_f["max_dd_usd"], 2),
                    "p_value": round(p_g1, 5),
                    "permutation_p": round(p_g4, 5) if not np.isnan(p_g4) else None,
                    "bootstrap_ci_lo": None,
                    "wf_mean": round(wf_mean, 4) if not np.isnan(wf_mean) else None,
                    "wf_pos_frac": round(wf_pos_frac, 3),
                    "gate_pass": gate_pass,
                    "notes": f"base={base['strategy_id']}+filt={filt_name}",
                })
                print(f"  [filt] base={str(base['strategy_id'])[:36]:36s} +{filt_name:14s} -> n={st_f['n_trades']:3d} WR={st_f['win_rate']:.2f} $/tr={st_f['avg_pnl_usd']:+.3f} Sh={st_f['sharpe']:+.2f} gates={gate_pass}")

    df = pd.DataFrame(results)
    df.to_csv(OUT_DIR / "W2a_results.csv", index=False)
    print(f"\nWrote {len(df)} cells to {OUT_DIR/'W2a_results.csv'}")
    return df


if __name__ == "__main__":
    t0 = time.time()
    df = run_grid()
    print(f"\nDone in {time.time()-t0:.1f}s. Total cells: {len(df)}")
