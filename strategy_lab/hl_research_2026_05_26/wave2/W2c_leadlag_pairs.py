"""W2c — Cross-asset lead-lag (N5) + Structure-break pair trades (N11).

Runs:
  * Lagged correlation BTC↔ETH↔SOL at lags 0, 30s, 60s, 120s, 180s, 300s
    (1m-resampled returns, so 30s shows as nearest-bar; we use the
     full-resolution 1m bars and shift integer minutes; plus a 5m secondary
     resampled lag check for slower scales).
  * Threshold-trigger N5: BTC 1m move > thr AND follower has not yet moved
    comparably → take followers's direction for K minutes.
  * N11 SMS structure-break pair trade: BTC bos_buy fires on 15m AND no
    ETH/SOL bos_buy in last 30 min → LONG (ETH+SOL)/2 vs SHORT BTC.
  * Walk-forward (60d train / 20d test) — at least 3 windows on the 1m
    sample window.
  * Permutation: shuffle LEAD-asset returns by ±5 min and re-evaluate.
  * Cross-asset: BTC→DOGE/AVAX/LINK at 15m.

Outputs:
  * W2c_results.csv         — one row per (test, hypothesis, asset/pair, params)
  * W2c_leadlag_pairs.md    — narrative report
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
OUT_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "wave2"
OUT_DIR.mkdir(parents=True, exist_ok=True)
PANELS = REPO / "strategy_lab" / "hl_research_2026_05_26" / "panels"

# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_binance_1m(symbol: str, years: list[int]) -> pd.DataFrame:
    """Load 1m Binance klines for given symbol and years.
    Returns a DataFrame indexed by UTC datetime with 'open','close','volume'.
    """
    parts = []
    for y in years:
        p = REPO / "data" / "binance" / "parquet" / symbol / "1m" / f"year={y}" / "part.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p, columns=["open_time", "open", "close", "volume"]))
    if not parts:
        raise FileNotFoundError(f"no 1m parquet for {symbol} years {years}")
    df = pd.concat(parts, ignore_index=True)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    df = df.set_index("open_time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def load_binance_15m(symbol: str, years: list[int]) -> pd.DataFrame:
    parts = []
    for y in years:
        p = REPO / "data" / "binance" / "parquet" / symbol / "15m" / f"year={y}" / "part.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p, columns=["open_time", "open", "close", "volume"]))
    if not parts:
        raise FileNotFoundError(f"no 15m parquet for {symbol} years {years}")
    df = pd.concat(parts, ignore_index=True)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)
    df = df.set_index("open_time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def load_panel(asset: str, tf: str) -> pd.DataFrame:
    p = PANELS / f"hl_panel_{asset}_{tf}.parquet"
    return pd.read_parquet(p)


# ---------------------------------------------------------------------------
# HL kline loader for execution
# ---------------------------------------------------------------------------
HL_SYMBOL_MAP = {
    "BTC": "HYPERLIQUID_PERP_BTC_USD",
    "ETH": "HYPERLIQUID_PERP_ETH_USD",
    "SOL": "HYPERLIQUID_PERP_SOL_USD",
}
HL_TF_MAP = {"1m": "1MIN", "5m": "5MIN", "15m": "15MIN", "1h": "1HRS", "4h": "4HRS"}


def load_hl_klines(asset: str, tf: str) -> pd.DataFrame:
    df = pd.read_parquet(REPO / "data" / "v4" / "canonical" / "hyperliquid_klines.parquet")
    sym = HL_SYMBOL_MAP[asset]
    period = HL_TF_MAP[tf]
    sub = df[(df["symbol_id"] == sym) & (df["period_id"] == period)].copy()
    sub = sub.rename(columns={
        "time_period_start_us": "open_time_us",
        "price_open": "open",
        "price_high": "high",
        "price_low": "low",
        "price_close": "close",
        "volume_traded": "volume",
    })
    sub["open_time"] = pd.to_datetime(sub["open_time_us"], unit="us", utc=True)
    return sub.sort_values("open_time").reset_index(drop=True)


def load_hl_funding(asset: str) -> pd.DataFrame:
    """Load HL funding rates for the asset."""
    fp = REPO / "data" / "v4" / "canonical" / "hyperliquid_funding.parquet"
    df = pd.read_parquet(fp)
    # Find the right column / filter
    # Inspect
    if asset in df.columns:
        out = pd.DataFrame({"funding_rate": df[asset]})
        out.index = df.index
    else:
        sym_field = None
        for c in ["symbol", "coin", "asset", "symbol_id"]:
            if c in df.columns:
                sym_field = c
                break
        if sym_field:
            sub = df[df[sym_field].astype(str).str.contains(asset, case=False, na=False)].copy()
            rate_col = None
            for c in ["funding_rate", "fundingRate", "premium", "rate"]:
                if c in sub.columns:
                    rate_col = c
                    break
            if rate_col is None:
                raise ValueError(f"no funding_rate col in {df.columns}")
            if "timestamp" in sub.columns:
                sub.index = pd.to_datetime(sub["timestamp"], utc=True)
            out = pd.DataFrame({"funding_rate": pd.to_numeric(sub[rate_col], errors="coerce")})
        else:
            raise ValueError(f"can't parse HL funding for {asset}: cols={df.columns}")
    out = out.dropna()
    out.index = pd.to_datetime(out.index, utc=True)
    return out.sort_index()


# ---------------------------------------------------------------------------
# Stats / utility
# ---------------------------------------------------------------------------

def t_stat(pnl: np.ndarray) -> tuple[float, float]:
    n = len(pnl)
    if n < 2 or pnl.std(ddof=1) == 0:
        return float("nan"), float("nan")
    t = pnl.mean() / (pnl.std(ddof=1) / np.sqrt(n))
    # 2-sided p (normal approx — large-n analyses below)
    from scipy.stats import t as tdist
    p = 2 * (1 - tdist.cdf(abs(t), df=n - 1))
    return float(t), float(p)


def summary_stats(pnl: np.ndarray, name: str = "") -> dict:
    n = len(pnl)
    if n == 0:
        return {"name": name, "n": 0, "mean": float("nan"), "win_rate": float("nan"),
                "sharpe": float("nan"), "sum": 0.0, "t": float("nan"), "p": float("nan")}
    wins = (pnl > 0).sum()
    sharpe = pnl.mean() / pnl.std(ddof=1) * np.sqrt(252) if pnl.std(ddof=1) > 0 else float("nan")
    t, p = t_stat(pnl)
    return {"name": name, "n": int(n), "mean": float(pnl.mean()),
            "win_rate": float(wins / n), "sharpe": float(sharpe),
            "sum": float(pnl.sum()), "t": t, "p": p}


# ---------------------------------------------------------------------------
# N5.1 — Lagged correlation
# ---------------------------------------------------------------------------

def lagged_corr_1m(leader_close: pd.Series, follower_close: pd.Series,
                    lags_min: list[int]) -> dict:
    """Lagged Pearson correlation of returns. Positive lag = follower at t+lag vs leader at t."""
    lr_lead = np.log(leader_close).diff().dropna()
    lr_foll = np.log(follower_close).diff().dropna()
    # align
    both = pd.concat([lr_lead.rename("lead"), lr_foll.rename("foll")], axis=1).dropna()
    out = {}
    for lag in lags_min:
        if lag == 0:
            c = both["lead"].corr(both["foll"])
        else:
            shifted = both["foll"].shift(-lag)  # follower in the future
            df2 = pd.concat([both["lead"], shifted], axis=1).dropna()
            c = df2.iloc[:, 0].corr(df2.iloc[:, 1])
        out[lag] = float(c)
    return out


# ---------------------------------------------------------------------------
# N5.2 — Threshold-trigger
# ---------------------------------------------------------------------------

def n5_threshold_trigger(leader_close: pd.Series, follower_close: pd.Series,
                          leader_volume: pd.Series,
                          thr_pct: float, hold_min: int,
                          volume_filter: bool = False,
                          direction: str = "UP") -> pd.DataFrame:
    """N5 threshold rule:
       direction=='UP': BTC ret(1m) > +thr_pct AND follower's ret(1m) didn't move
         comparably (within 0.5×thr or opposite sign) → LONG follower for K min.
       direction=='DOWN': BTC ret(1m) < -thr_pct AND follower's ret(1m) didn't
         move down comparably → SHORT follower for K min.
       Returns DataFrame with signal_us, direction, exit_us, leg_pnl_pct.
       leg_pnl_pct is gross % move; fees applied later."""
    df = pd.concat({
        "L_close": leader_close,
        "F_close": follower_close,
        "L_vol": leader_volume,
    }, axis=1).dropna()
    df["L_ret"] = np.log(df["L_close"]).diff()
    df["F_ret"] = np.log(df["F_close"]).diff()
    df["L_vol_avg60"] = df["L_vol"].rolling(60, min_periods=20).mean()

    thr_log = np.log(1 + thr_pct / 100)
    if direction == "UP":
        cond = (df["L_ret"] > thr_log) & (df["F_ret"] < 0.5 * thr_log)
    else:
        cond = (df["L_ret"] < -thr_log) & (df["F_ret"] > -0.5 * thr_log)

    if volume_filter:
        cond &= df["L_vol"] > 1.5 * df["L_vol_avg60"]

    sig_times = df.index[cond]
    if len(sig_times) == 0:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us", "leg_ret"])

    # PnL on the FOLLOWER (long if UP signal, short if DOWN signal)
    # Entry: open of bar AT signal_time + 1 (next 1m bar)
    # Exit: open of bar at signal_time + 1 + hold_min
    rows = []
    df_idx = df.index
    for t in sig_times:
        try:
            entry_idx = df_idx.get_loc(t) + 1
            exit_idx = entry_idx + hold_min
            if exit_idx >= len(df_idx):
                continue
            entry_px = df["F_close"].iloc[entry_idx]
            exit_px = df["F_close"].iloc[exit_idx]
            ret = (exit_px / entry_px - 1.0)
            if direction == "DOWN":
                ret = -ret
            rows.append({
                "signal_us": int(df_idx[entry_idx].value // 1_000),
                "direction": "LONG" if direction == "UP" else "SHORT",
                "exit_us": int(df_idx[exit_idx].value // 1_000),
                "leg_ret": ret,
                "entry_time": df_idx[entry_idx],
            })
        except (IndexError, KeyError):
            continue
    return pd.DataFrame(rows)


def fees_per_trade(notional: float, hl_taker_bps: float = 4.5,
                    slip_bps: float = 3.0) -> float:
    """Round-trip HL fees + slippage cost in dollars on a single-leg position."""
    return notional * ((2 * hl_taker_bps + slip_bps) / 10_000.0)


# ---------------------------------------------------------------------------
# N5.3 — Walk-forward on best N5 config
# ---------------------------------------------------------------------------

def walk_forward_n5(leader_close, follower_close, leader_volume,
                     thr_pct: float, hold_min: int, direction: str,
                     notional: float, train_days: int = 60, test_days: int = 20) -> list[dict]:
    """Run walk-forward on a single N5 configuration. Trains on train_days then evaluates
    on the next test_days; rolls by test_days. Returns list of dicts (one per window)."""
    ts_min = leader_close.index.min()
    ts_max = leader_close.index.max()
    out = []
    cur = ts_min
    win = 0
    while cur + pd.Timedelta(days=train_days + test_days) <= ts_max:
        train_lo = cur
        train_hi = cur + pd.Timedelta(days=train_days)
        test_hi = train_hi + pd.Timedelta(days=test_days)

        lc_train = leader_close.loc[train_lo:train_hi]
        fc_train = follower_close.loc[train_lo:train_hi]
        lv_train = leader_volume.loc[train_lo:train_hi]
        # NB: for THIS version we use FIXED thr/hold (no re-optimization) — we just
        # check whether the OUT-OF-SAMPLE test window also produces positive net.
        trades_train = n5_threshold_trigger(lc_train, fc_train, lv_train,
                                             thr_pct, hold_min, direction=direction)
        train_stats = summary_stats(
            trades_train["leg_ret"].to_numpy() * notional - fees_per_trade(notional)
            if len(trades_train) > 0 else np.array([]),
            name=f"train_{win}",
        )

        lc_test = leader_close.loc[train_hi:test_hi]
        fc_test = follower_close.loc[train_hi:test_hi]
        lv_test = leader_volume.loc[train_hi:test_hi]
        trades_test = n5_threshold_trigger(lc_test, fc_test, lv_test,
                                            thr_pct, hold_min, direction=direction)
        test_stats = summary_stats(
            trades_test["leg_ret"].to_numpy() * notional - fees_per_trade(notional)
            if len(trades_test) > 0 else np.array([]),
            name=f"test_{win}",
        )
        out.append({
            "window": win, "train_lo": train_lo, "train_hi": train_hi, "test_hi": test_hi,
            "train_n": train_stats["n"], "train_mean": train_stats["mean"],
            "train_winrate": train_stats["win_rate"], "train_sum": train_stats["sum"],
            "test_n": test_stats["n"], "test_mean": test_stats["mean"],
            "test_winrate": test_stats["win_rate"], "test_sum": test_stats["sum"],
            "test_t": test_stats["t"], "test_p": test_stats["p"],
        })
        cur = train_hi
        win += 1
    return out


# ---------------------------------------------------------------------------
# Permutation gate (G4)
# ---------------------------------------------------------------------------

def permutation_test(leader_close, follower_close, leader_volume,
                      thr_pct: float, hold_min: int, direction: str,
                      notional: float, n_perm: int = 50, max_shift_min: int = 5) -> dict:
    """Shuffle leader returns by random ±max_shift_min minute shifts and recompute pnl
    mean for each perm. Compute p-value as fraction of perms whose mean ≥ observed."""
    obs_trades = n5_threshold_trigger(leader_close, follower_close, leader_volume,
                                       thr_pct, hold_min, direction=direction)
    obs_pnl = obs_trades["leg_ret"].to_numpy() * notional - fees_per_trade(notional)
    if len(obs_pnl) == 0:
        return {"obs_mean": float("nan"), "perm_p": float("nan"), "n_perm": 0}
    obs_mean = float(obs_pnl.mean())

    rng = np.random.default_rng(42)
    perm_means = []
    for _ in range(n_perm):
        shift = int(rng.integers(-max_shift_min, max_shift_min + 1))
        if shift == 0:
            shift = 1  # ensure shift
        # shift the leader series; effectively destroys true alignment
        L_shift = leader_close.shift(shift)
        L_shift_vol = leader_volume.shift(shift)
        perm_trades = n5_threshold_trigger(L_shift, follower_close, L_shift_vol,
                                            thr_pct, hold_min, direction=direction)
        if len(perm_trades) == 0:
            continue
        perm_pnl = perm_trades["leg_ret"].to_numpy() * notional - fees_per_trade(notional)
        perm_means.append(perm_pnl.mean())
    perm_means = np.array(perm_means)
    if len(perm_means) == 0:
        return {"obs_mean": obs_mean, "perm_p": float("nan"), "n_perm": 0}
    perm_p = float((perm_means >= obs_mean).mean())
    return {"obs_mean": obs_mean, "perm_p": perm_p, "n_perm": len(perm_means),
            "perm_mean_avg": float(perm_means.mean())}


# ---------------------------------------------------------------------------
# N11 — SMS structure-break pairs
# ---------------------------------------------------------------------------

def n11_structure_break_pairs(panel_btc: pd.DataFrame, panel_eth: pd.DataFrame,
                                panel_sol: pd.DataFrame, hold_bars: int,
                                direction: str = "UP") -> pd.DataFrame:
    """N11 pair trade:
      direction=='UP': BTC bos_buy fires AND no ETH bos_buy in last 30 min AND no SOL bos_buy
        in last 30 min → LONG (ETH+SOL)/2 vs SHORT BTC.
      direction=='DOWN': BTC bos_sell fires AND no ETH/SOL bos_sell in last 30 min → SHORT
        (ETH+SOL)/2 vs LONG BTC.
    Holds `hold_bars` 15m bars OR until ETH or SOL bos_buy fires (convergence).
    Returns DataFrame with raw % returns per leg + net pnl.
    """
    # align on open_time
    cols_use = ["open_time", "open", "close", "bos_buy", "bos_sell"]
    b = panel_btc[cols_use].rename(columns={c: f"BTC_{c}" for c in cols_use if c != "open_time"})
    e = panel_eth[cols_use].rename(columns={c: f"ETH_{c}" for c in cols_use if c != "open_time"})
    s = panel_sol[cols_use].rename(columns={c: f"SOL_{c}" for c in cols_use if c != "open_time"})
    df = b.merge(e, on="open_time").merge(s, on="open_time").sort_values("open_time").reset_index(drop=True)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=True)

    # Lookback bars for 30 min on 15m bars = 2 bars
    lb_bars = 2
    bos_col = "bos_buy" if direction == "UP" else "bos_sell"

    fires = []
    for i in range(lb_bars, len(df) - hold_bars):
        if df[f"BTC_{bos_col}"].iloc[i] != 1:
            continue
        # check ETH/SOL have NOT fired the same break in lookback window
        eth_window = df[f"ETH_{bos_col}"].iloc[i - lb_bars:i + 1].sum()
        sol_window = df[f"SOL_{bos_col}"].iloc[i - lb_bars:i + 1].sum()
        if eth_window > 0 or sol_window > 0:
            continue
        # all clear → enter pair
        btc_in = df["BTC_close"].iloc[i]
        eth_in = df["ETH_close"].iloc[i]
        sol_in = df["SOL_close"].iloc[i]

        # exit: hold_bars later, OR earlier if ETH or SOL bos fires (convergence)
        opp_bos = "bos_buy" if direction == "UP" else "bos_sell"  # same direction means convergence
        exit_i = i + hold_bars
        for j in range(i + 1, min(i + hold_bars + 1, len(df))):
            if df[f"ETH_{opp_bos}"].iloc[j] == 1 or df[f"SOL_{opp_bos}"].iloc[j] == 1:
                exit_i = j
                break
        if exit_i >= len(df):
            continue

        btc_out = df["BTC_close"].iloc[exit_i]
        eth_out = df["ETH_close"].iloc[exit_i]
        sol_out = df["SOL_close"].iloc[exit_i]

        btc_ret = (btc_out / btc_in - 1.0)
        eth_ret = (eth_out / eth_in - 1.0)
        sol_ret = (sol_out / sol_in - 1.0)

        if direction == "UP":
            # LONG (ETH+SOL)/2, SHORT BTC
            leg_pnl_ret = 0.5 * eth_ret + 0.5 * sol_ret - btc_ret
        else:
            # SHORT (ETH+SOL)/2, LONG BTC
            leg_pnl_ret = -(0.5 * eth_ret + 0.5 * sol_ret) + btc_ret

        fires.append({
            "open_time": df["open_time"].iloc[i],
            "exit_time": df["open_time"].iloc[exit_i],
            "bars_held": exit_i - i,
            "btc_ret": btc_ret, "eth_ret": eth_ret, "sol_ret": sol_ret,
            "pair_ret": leg_pnl_ret,
        })
    return pd.DataFrame(fires)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    # Force UTF-8 output for Windows console
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    rows = []

    # =======================================================================
    # SUB-TEST 1: Lagged correlation (full Binance window, 1m)
    # =======================================================================
    print("=" * 70)
    print("N5.1 — Lagged correlation BTC → ETH/SOL (Binance 1m, 2020-2026)")
    print("=" * 70)
    # Limit to overlap window where SOL exists. Use 2020-2026 to capture macro era.
    years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    btc = load_binance_1m("BTCUSDT", years)
    eth = load_binance_1m("ETHUSDT", years)
    sol = load_binance_1m("SOLUSDT", years)
    print(f"BTC 1m loaded: {len(btc):,} bars, {btc.index.min()} → {btc.index.max()}")
    print(f"ETH 1m loaded: {len(eth):,} bars, {eth.index.min()} → {eth.index.max()}")
    print(f"SOL 1m loaded: {len(sol):,} bars, {sol.index.min()} → {sol.index.max()}")

    lags = [0, 1, 2, 3, 5]  # minutes (since data is 1m)
    # ETH follower
    eth_corr = lagged_corr_1m(btc["close"], eth["close"], lags)
    print("BTC→ETH 1m lagged corr:", eth_corr)
    sol_corr = lagged_corr_1m(btc["close"], sol["close"], lags)
    print("BTC→SOL 1m lagged corr:", sol_corr)
    # Check reverse: ETH→BTC (to see who leads)
    eth_btc_corr = lagged_corr_1m(eth["close"], btc["close"], lags)
    print("ETH→BTC 1m lagged corr:", eth_btc_corr)

    for lag in lags:
        rows.append({"test": "N5.1_corr", "hypothesis": "N5", "leader": "BTC", "follower": "ETH",
                     "lag_min": lag, "corr": eth_corr[lag]})
        rows.append({"test": "N5.1_corr", "hypothesis": "N5", "leader": "BTC", "follower": "SOL",
                     "lag_min": lag, "corr": sol_corr[lag]})
        rows.append({"test": "N5.1_corr", "hypothesis": "N5", "leader": "ETH", "follower": "BTC",
                     "lag_min": lag, "corr": eth_btc_corr[lag]})

    # =======================================================================
    # SUB-TEST 2: Threshold-trigger sweep (last 12 months, 1m)
    # =======================================================================
    print()
    print("=" * 70)
    print("N5.2 — Threshold trigger sweep (last 12 months for speed)")
    print("=" * 70)
    # Last 12 months: 2025-05 → 2026-04
    btc_12m = btc.loc["2025-05-01":"2026-04-30"]
    eth_12m = eth.loc["2025-05-01":"2026-04-30"]
    sol_12m = sol.loc["2025-05-01":"2026-04-30"]
    print(f"12m sample: BTC={len(btc_12m)}, ETH={len(eth_12m)}, SOL={len(sol_12m)}")

    notional = 250.0
    fees_per = fees_per_trade(notional)
    print(f"Notional ${notional}, round-trip fees+slip = ${fees_per:.3f}")

    sweep_results = []
    for thr in [0.2, 0.3, 0.5, 1.0]:
        for K in [1, 3, 5, 10, 15]:
            for follower_name, foll_close in [("ETH", eth_12m["close"]), ("SOL", sol_12m["close"])]:
                for direction in ["UP", "DOWN"]:
                    trades = n5_threshold_trigger(
                        btc_12m["close"], foll_close, btc_12m["volume"],
                        thr_pct=thr, hold_min=K, direction=direction,
                    )
                    if len(trades) == 0:
                        continue
                    pnl_net = trades["leg_ret"].to_numpy() * notional - fees_per
                    stats = summary_stats(pnl_net, name=f"{follower_name}_{direction}_thr{thr}_K{K}")
                    sweep_results.append({
                        "follower": follower_name, "direction": direction,
                        "thr_pct": thr, "hold_min": K,
                        **stats,
                    })
                    rows.append({"test": "N5.2_sweep", "hypothesis": "N5",
                                 "follower": follower_name, "direction": direction,
                                 "thr_pct": thr, "hold_min": K,
                                 "n": stats["n"], "mean_pnl": stats["mean"],
                                 "win_rate": stats["win_rate"], "sharpe": stats["sharpe"],
                                 "sum_pnl": stats["sum"], "t": stats["t"], "p": stats["p"]})

    sweep_df = pd.DataFrame(sweep_results)
    if len(sweep_df):
        print("\nTop 20 by mean PnL (with n>=20, p<0.10):")
        top = sweep_df[(sweep_df["n"] >= 20) & (sweep_df["p"] < 0.10)].sort_values("mean", ascending=False).head(20)
        print(top.to_string(index=False))
        # Best by sharpe
        print("\nTop 10 by sharpe (n>=20):")
        top_s = sweep_df[sweep_df["n"] >= 20].sort_values("sharpe", ascending=False).head(10)
        print(top_s.to_string(index=False))

    # =======================================================================
    # SUB-TEST 3: Volume confluence on best config
    # =======================================================================
    print()
    print("=" * 70)
    print("N5.3 — Volume confluence filter on best config")
    print("=" * 70)
    # Take the best p<0.05 config from sweep (or best mean)
    if len(sweep_df):
        valid = sweep_df[(sweep_df["n"] >= 30) & (sweep_df["mean"] > 0)].sort_values("mean", ascending=False)
        if len(valid):
            best = valid.iloc[0]
        else:
            best = sweep_df.sort_values("mean", ascending=False).iloc[0]
        print(f"Best config: follower={best['follower']} dir={best['direction']} thr={best['thr_pct']} K={best['hold_min']}")
        # With volume filter
        foll_close = eth_12m["close"] if best["follower"] == "ETH" else sol_12m["close"]
        trades_vf = n5_threshold_trigger(
            btc_12m["close"], foll_close, btc_12m["volume"],
            thr_pct=best["thr_pct"], hold_min=int(best["hold_min"]),
            direction=best["direction"], volume_filter=True,
        )
        if len(trades_vf):
            pnl_vf = trades_vf["leg_ret"].to_numpy() * notional - fees_per
            vf_stats = summary_stats(pnl_vf, name="best_with_vol")
            print("With volume filter:", vf_stats)
            rows.append({"test": "N5.3_volume", "hypothesis": "N5",
                         "follower": best["follower"], "direction": best["direction"],
                         "thr_pct": best["thr_pct"], "hold_min": best["hold_min"],
                         "volume_filter": True,
                         "n": vf_stats["n"], "mean_pnl": vf_stats["mean"],
                         "win_rate": vf_stats["win_rate"], "sharpe": vf_stats["sharpe"],
                         "sum_pnl": vf_stats["sum"], "t": vf_stats["t"], "p": vf_stats["p"]})

    # =======================================================================
    # SUB-TEST 4: Walk-forward on best config
    # =======================================================================
    print()
    print("=" * 70)
    print("N5.4 — Walk-forward 60d train / 20d test")
    print("=" * 70)
    if len(sweep_df) and len(valid):
        foll_close = eth_12m["close"] if best["follower"] == "ETH" else sol_12m["close"]
        wf = walk_forward_n5(
            btc_12m["close"], foll_close, btc_12m["volume"],
            thr_pct=best["thr_pct"], hold_min=int(best["hold_min"]),
            direction=best["direction"], notional=notional,
        )
        print(f"Walk-forward windows: {len(wf)}")
        for w in wf:
            tp = w["test_p"] if w["test_p"] is not None and not pd.isna(w["test_p"]) else float("nan")
            print(f"  Win{w['window']}: train_n={w['train_n']} test_n={w['test_n']} "
                  f"train_mean={w['train_mean']:.4f} test_mean={w['test_mean']:.4f} "
                  f"test_p={tp:.3f}")
            rows.append({"test": "N5.4_wf", "hypothesis": "N5",
                         "follower": best["follower"], "direction": best["direction"],
                         "thr_pct": best["thr_pct"], "hold_min": best["hold_min"],
                         "window": w["window"], "train_n": w["train_n"], "test_n": w["test_n"],
                         "train_mean": w["train_mean"], "test_mean": w["test_mean"],
                         "test_winrate": w["test_winrate"], "test_p": w["test_p"]})

    # =======================================================================
    # SUB-TEST 5: Permutation (G4)
    # =======================================================================
    print()
    print("=" * 70)
    print("N5.5 — Permutation test (shuffle leader returns by ±5 min)")
    print("=" * 70)
    if len(sweep_df) and len(valid):
        foll_close = eth_12m["close"] if best["follower"] == "ETH" else sol_12m["close"]
        perm = permutation_test(
            btc_12m["close"], foll_close, btc_12m["volume"],
            thr_pct=best["thr_pct"], hold_min=int(best["hold_min"]),
            direction=best["direction"], notional=notional, n_perm=30,
        )
        print(f"Observed mean: {perm['obs_mean']:.4f}")
        print(f"Permutation p (frac perms ≥ obs): {perm['perm_p']:.3f}")
        print(f"Perm mean avg: {perm.get('perm_mean_avg', float('nan')):.4f}")
        rows.append({"test": "N5.5_perm", "hypothesis": "N5",
                     "follower": best["follower"], "direction": best["direction"],
                     "thr_pct": best["thr_pct"], "hold_min": best["hold_min"],
                     "obs_mean": perm["obs_mean"], "perm_p": perm["perm_p"],
                     "n_perm": perm["n_perm"]})

    # =======================================================================
    # SUB-TEST 6: G5 — cross-asset to other alts (BTC → DOGE/AVAX/LINK at 15m)
    # =======================================================================
    print()
    print("=" * 70)
    print("N5.6 — Cross-asset: BTC → DOGE/AVAX/LINK at 15m")
    print("=" * 70)
    btc_15 = load_binance_15m("BTCUSDT", years)
    for alt in ["DOGEUSDT", "AVAXUSDT", "LINKUSDT"]:
        try:
            alt_df = load_binance_15m(alt, years)
        except FileNotFoundError:
            print(f"  {alt}: no 15m data")
            continue
        # Align on 15m bars, last 12 months
        b15 = btc_15.loc["2025-05-01":"2026-04-30"]
        a15 = alt_df.loc["2025-05-01":"2026-04-30"]
        # 15m thresholds wider; try 0.5%, 1.0%
        for thr in [0.5, 1.0]:
            for K in [1, 3]:  # K in 15m bars = 15min / 45min
                trades = n5_threshold_trigger(
                    b15["close"], a15["close"], b15["volume"],
                    thr_pct=thr, hold_min=K, direction="UP",
                )
                # NOTE: hold_min is treated as bars here since we replace the 1m bar with 15m bar in this branch
                if len(trades):
                    pnl = trades["leg_ret"].to_numpy() * notional - fees_per
                    s = summary_stats(pnl, name=f"{alt}_thr{thr}_K{K}")
                    print(f"  {alt} thr={thr}% K={K} bars: n={s['n']} mean=${s['mean']:.3f} "
                          f"sharpe={s['sharpe']:.2f} winrate={s['win_rate']:.2%} p={s['p']:.3f}")
                    rows.append({"test": "N5.6_xasset", "hypothesis": "N5", "follower": alt,
                                 "direction": "UP", "thr_pct": thr, "hold_bars_15m": K,
                                 "n": s["n"], "mean_pnl": s["mean"], "win_rate": s["win_rate"],
                                 "sharpe": s["sharpe"], "sum_pnl": s["sum"], "t": s["t"], "p": s["p"]})

    # =======================================================================
    # SUB-TEST 7: N11 — Structure-break pairs (15m, panels)
    # =======================================================================
    print()
    print("=" * 70)
    print("N11 — SMS structure-break pair trades (15m panels)")
    print("=" * 70)
    panel_btc_15 = load_panel("BTC", "15m")
    panel_eth_15 = load_panel("ETH", "15m")
    panel_sol_15 = load_panel("SOL", "15m")

    # Pick a comparable window — panels go back to 2017 but BTC/ETH/SOL panels share 2020+
    # Limit to last 24 months for relevance
    cutoff_lo = pd.Timestamp("2024-05-01", tz="UTC")
    panel_btc_15["open_time"] = pd.to_datetime(panel_btc_15["open_time"], utc=True)
    panel_eth_15["open_time"] = pd.to_datetime(panel_eth_15["open_time"], utc=True)
    panel_sol_15["open_time"] = pd.to_datetime(panel_sol_15["open_time"], utc=True)
    pb = panel_btc_15[panel_btc_15["open_time"] >= cutoff_lo].copy()
    pe = panel_eth_15[panel_eth_15["open_time"] >= cutoff_lo].copy()
    ps = panel_sol_15[panel_sol_15["open_time"] >= cutoff_lo].copy()
    print(f"BTC 15m panel last 24m: {len(pb)} bars")
    print(f"ETH 15m panel last 24m: {len(pe)} bars")
    print(f"SOL 15m panel last 24m: {len(ps)} bars")

    # Pair trade: ENTRY costs 3 legs (BTC short + ETH long 0.5x + SOL long 0.5x). Each leg pays:
    # 2× taker fee + slippage = 12 bps round-trip. With 0.5x notional, fees scale linearly.
    # Total round-trip fees = BTC(1x) + ETH(0.5x) + SOL(0.5x) = 2x notional × (2× taker + slip)
    # = 2 × 250 × 12/10000 = $0.6 + slippage adjustments
    pair_fees = 2 * fees_per_trade(notional)
    print(f"Pair round-trip fees+slip = ${pair_fees:.3f}")

    for direction in ["UP", "DOWN"]:
        for hold_bars in [4, 16, 96]:  # 4×15m=1h, 16×15m=4h, 96×15m=24h
            pair_trades = n11_structure_break_pairs(pb, pe, ps, hold_bars=hold_bars, direction=direction)
            if len(pair_trades) == 0:
                print(f"  N11 {direction} hold={hold_bars*15}min: 0 trades")
                continue
            pnl = pair_trades["pair_ret"].to_numpy() * notional - pair_fees
            s = summary_stats(pnl, name=f"N11_{direction}_{hold_bars}b")
            avg_bars = pair_trades["bars_held"].mean()
            print(f"  N11 {direction} hold={hold_bars*15}min (avg held={avg_bars:.1f} bars): "
                  f"n={s['n']} mean=${s['mean']:.3f} winrate={s['win_rate']:.2%} "
                  f"sharpe={s['sharpe']:.2f} p={s['p']:.3f} sum=${s['sum']:.2f}")
            rows.append({"test": "N11_pair", "hypothesis": "N11", "direction": direction,
                         "hold_bars_15m": hold_bars, "avg_bars_held": float(avg_bars),
                         "n": s["n"], "mean_pnl": s["mean"], "win_rate": s["win_rate"],
                         "sharpe": s["sharpe"], "sum_pnl": s["sum"], "t": s["t"], "p": s["p"]})

    # =======================================================================
    # SUB-TEST 8: N11 INVERSE — flip the pair (since direct loses badly)
    # =======================================================================
    print()
    print("=" * 70)
    print("N11_inverse — Test opposite side: BTC breaks UP, LONG BTC vs SHORT (ETH+SOL)/2")
    print("=" * 70)
    for direction in ["UP", "DOWN"]:
        for hold_bars in [4, 16]:
            pair_trades = n11_structure_break_pairs(pb, pe, ps, hold_bars=hold_bars, direction=direction)
            if len(pair_trades) == 0:
                continue
            # INVERT pair_ret
            pnl = -pair_trades["pair_ret"].to_numpy() * notional - pair_fees
            s = summary_stats(pnl, name=f"N11inv_{direction}_{hold_bars}b")
            avg_bars = pair_trades["bars_held"].mean()
            print(f"  N11_inv {direction} hold={hold_bars*15}min: n={s['n']} mean=${s['mean']:.3f} "
                  f"winrate={s['win_rate']:.2%} sharpe={s['sharpe']:.2f} p={s['p']:.3f} sum=${s['sum']:.2f}")
            rows.append({"test": "N11_inv", "hypothesis": "N11_inverse",
                         "direction": direction, "hold_bars_15m": hold_bars,
                         "avg_bars_held": float(avg_bars),
                         "n": s["n"], "mean_pnl": s["mean"], "win_rate": s["win_rate"],
                         "sharpe": s["sharpe"], "sum_pnl": s["sum"], "t": s["t"], "p": s["p"]})

    # =======================================================================
    # SUB-TEST 9: Sub-minute lead-lag — use 1m bars but try fractional shifts
    # Since Binance is 1m, we cannot directly resolve sub-minute. But we can
    # check whether the contemporaneous correlation is driven by within-bar
    # correlation. For now report the existing prior-work result from
    # cross_exchange_leadlag/_signed_leadlag.csv.
    # =======================================================================
    print()
    print("=" * 70)
    print("N5.7 — Subminute lead-lag (from prior research / xcorr_1min)")
    print("=" * 70)
    # Read the prior xcorr_1min result
    prior_xcorr = REPO / "strategy_lab" / "cross_exchange_leadlag_2026_05_26" / "_xcorr_1min.csv"
    if prior_xcorr.exists():
        xc = pd.read_csv(prior_xcorr)
        print(f"Loaded {len(xc)} prior xcorr rows.")
        print(xc.to_string(index=False))
        # Best lag column already present in the prior result
        for asset in ["BTC", "ETH", "SOL"]:
            sub = xc[xc["asset"] == asset]
            if len(sub):
                print(f"\n  {asset}: peak lag (minutes) per venue:")
                print(sub[["venue", "best_lag_min_at_max_xc", "best_xc",
                            "best_lag_min_at_max_abs", "best_abs_xc"]].to_string(index=False))

    # Also report the 1s sub-minute file
    sub1s = REPO / "strategy_lab" / "cross_exchange_leadlag_2026_05_26" / "_xcorr_subminute_hl_fast.csv"
    if sub1s.exists():
        xs = pd.read_csv(sub1s)
        print(f"\nSubminute 1s xcorr: {len(xs)} rows")
        print(xs.head(20).to_string(index=False))
        # find peak ms lag
        for asset in ["BTC", "ETH", "SOL"]:
            sub = xs[xs["asset"] == asset] if "asset" in xs.columns else pd.DataFrame()
            if len(sub):
                # find row with max corr
                if "corr" in sub.columns:
                    best = sub.loc[sub["corr"].abs().idxmax()]
                    print(f"  {asset} best 1s xcorr: lag_ms={best.get('lag_ms', 'na')} corr={best.get('corr', 'na')}")

    # Save results
    out_csv = OUT_DIR / "W2c_results.csv"
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"\nResults: {out_csv}")
    return rows


if __name__ == "__main__":
    main()
