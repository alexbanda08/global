"""
Multi-strategy comparison using the `investing-algorithm-framework` library.

Ports four of our best strategies into IAF's TradingStrategy interface and
runs them side-by-side on the same BTC/ETH/SOL/DOGE 4h data, then builds
the self-contained HTML comparison report that IAF specialises in.

Strategies ported:
  A. UserSOL_BBBreak_LS  — V34 USER sleeve (SOL BBBreak + regime filter)
  B. UserETH_CCI         — V34 USER sleeve (ETH CCI mean-reversion)
  C. UserDOGE_Donchian   — V34 USER sleeve (DOGE HTF Donchian breakout)
  D. MyBTC_Momentum14d   — V15/V24 XSM condensed to single-coin (BTC 14d mom)

Output:
  strategy_lab/results/iaf/comparison_report.html      (self-contained)
  ~/Desktop/newstrategies/IAF_MULTI_COMPARISON.html    (copy)
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone
import shutil

import numpy as np
import pandas as pd
import talib

from investing_algorithm_framework import (
    TradingStrategy, TimeUnit, DataType, DataSource,
    CSVOHLCVDataProvider, PortfolioConfiguration, BacktestDateRange,
    BacktestReport, create_app,
    PositionSize, StopLossRule, TakeProfitRule,
)

BASE = Path(__file__).resolve().parent
PARQUET = BASE.parent / "data" / "binance" / "parquet"
WORK = BASE / "results" / "iaf"
CSV_DIR = WORK / "csv"
BT_DIR = WORK / "backtests"
for d in (WORK, CSV_DIR, BT_DIR):
    d.mkdir(parents=True, exist_ok=True)

MARKET = "BINANCE"
TS     = "USDT"
COINS_TF = [("BTCUSDT", "4h"), ("ETHUSDT", "4h"),
            ("SOLUSDT", "4h"), ("DOGEUSDT", "4h")]


# ---------------------------------------------------------------------
def prep_csvs(start="2022-06-01", end="2026-03-01"):
    paths = {}
    for sym, tf in COINS_TF:
        folder = PARQUET / sym / tf
        files = sorted(folder.glob("year=*/part.parquet"))
        if not files: continue
        df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        df = df.drop_duplicates("open_time").sort_values("open_time").set_index("open_time")
        s = pd.Timestamp(start, tz="UTC"); e = pd.Timestamp(end, tz="UTC")
        df = df[(df.index >= s) & (df.index < e)]
        out = pd.DataFrame({
            "Datetime": df.index.tz_convert("UTC").tz_localize(None),
            "Open":  df["open"].values, "High": df["high"].values,
            "Low":   df["low"].values,  "Close": df["close"].values,
            "Volume":df["volume"].values,
        })
        p = CSV_DIR / f"{sym}_4h.csv"
        out.to_csv(p, index=False)
        paths[sym] = p
        print(f"  {sym} 4h -> {p.name}  ({len(out):,} bars)")
    return paths


# ---------------------------------------------------------------------
def _get_df(data, identifier: str):
    return data.get(identifier) if isinstance(data, dict) else None


def _bb_break_ls(df, n=20, k=2.0, regime_len=200):
    c = df["Close"]
    mid = c.rolling(n).mean(); std = c.rolling(n).std()
    upper = mid + k*std; lower = mid - k*std
    ema_r = c.ewm(span=regime_len, adjust=False).mean()
    long_  = (c > upper) & (c.shift(1) <= upper.shift(1)) & (c > ema_r)
    short_ = (c < lower) & (c.shift(1) >= lower.shift(1)) & (c < ema_r)
    return long_.fillna(False), short_.fillna(False)


def _htf_donchian(df, donch_n=20, ema_reg=100):
    c = df["Close"]
    hi = df["High"].rolling(donch_n).max().shift(1)
    lo = df["Low"].rolling(donch_n).min().shift(1)
    ema_r = c.ewm(span=ema_reg, adjust=False).mean()
    long_  = (c > hi) & (c > ema_r)
    short_ = (c < lo) & (c < ema_r)
    return long_.fillna(False), short_.fillna(False)


def _cci_rev(df, cci_n=20, cci_thr=200, adx_max=25):
    c = df["Close"].values; h = df["High"].values; l = df["Low"].values
    cci = pd.Series(talib.CCI(h, l, c, cci_n), index=df.index)
    adx = pd.Series(talib.ADX(h, l, c, 14), index=df.index)
    long_  = (cci < -cci_thr) & (adx < adx_max)
    short_ = (cci >  cci_thr) & (adx < adx_max)
    return long_.fillna(False), short_.fillna(False)


def _momentum_14d(df, lookback_bars=84):
    c = df["Close"]
    mom = c.pct_change(lookback_bars)
    ma_bear = c.rolling(lookback_bars*7).mean()
    long_  = (mom > 0) & (c > ma_bear)
    return long_.fillna(False), pd.Series(False, index=df.index)


# ---------------------------------------------------------------------
class _BaseStrategy(TradingStrategy):
    COIN = None
    SIGNAL_ID = None
    TIME_FRAME = "4h"
    time_unit = TimeUnit.HOUR
    interval = 4

    def __init__(self, **kw):
        sym = self.COIN
        ident = f"{sym}_ohlcv"
        super().__init__(
            algorithm_id=self.SIGNAL_ID,
            strategy_id=self.strategy_id,
            symbols=[sym], trading_symbol=TS,
            position_sizes=[PositionSize(symbol=sym, percentage_of_portfolio=95)],
            stop_losses=[StopLossRule(symbol=sym, percentage_threshold=8,
                                       sell_percentage=100, trailing=True)],
            take_profits=[TakeProfitRule(symbol=sym, percentage_threshold=25,
                                          sell_percentage=100, trailing=False)],
            data_sources=[
                DataSource(
                    identifier=ident, symbol=f"{sym}/{TS}",
                    data_type=DataType.OHLCV, time_frame=self.TIME_FRAME,
                    market=MARKET, pandas=True, warmup_window=250,
                    data_provider_identifier=self.SIGNAL_ID + "_provider",
                )
            ],
            **kw,
        )
        self._ident = ident

    def _signal(self, df):
        raise NotImplementedError

    def generate_buy_signals(self, data):
        df = _get_df(data, self._ident)
        if df is None or len(df) < 250:
            return {self.COIN: pd.Series(False,
                    index=df.index if df is not None else [])}
        long_, _ = self._signal(df)
        return {self.COIN: long_}

    def generate_sell_signals(self, data):
        df = _get_df(data, self._ident)
        if df is None or len(df) < 250:
            return {self.COIN: pd.Series(False,
                    index=df.index if df is not None else [])}
        long_, _ = self._signal(df)
        exit_flag = (~long_) & long_.shift(1).fillna(False)
        return {self.COIN: exit_flag.fillna(False)}


class UserSOL_BBBreak_LS(_BaseStrategy):
    COIN = "SOL"
    SIGNAL_ID = "sol_bbbreak_ls"
    strategy_id = "USER_SOL_BBBreak_LS"
    def _signal(self, df): return _bb_break_ls(df)


class UserETH_CCI(_BaseStrategy):
    COIN = "ETH"
    SIGNAL_ID = "eth_cci_rev"
    strategy_id = "USER_ETH_CCI_Extreme_Rev"
    def _signal(self, df): return _cci_rev(df)


class UserDOGE_Donchian(_BaseStrategy):
    COIN = "DOGE"
    SIGNAL_ID = "doge_htf_donch"
    strategy_id = "USER_DOGE_HTF_Donchian"
    def _signal(self, df): return _htf_donchian(df)


class MyBTC_Momentum14d(_BaseStrategy):
    COIN = "BTC"
    SIGNAL_ID = "btc_momentum14"
    strategy_id = "MY_BTC_Momentum14d_XSM"
    def _signal(self, df): return _momentum_14d(df)


# ---------------------------------------------------------------------
def main():
    paths = prep_csvs()

    app = create_app(config={"APP_MODE": "backtest"})

    sym_to_id = {"BTCUSDT":"btc_momentum14", "ETHUSDT":"eth_cci_rev",
                 "SOLUSDT":"sol_bbbreak_ls", "DOGEUSDT":"doge_htf_donch"}
    for sym, tf in COINS_TF:
        p = paths.get(sym)
        if p is None: continue
        coin = sym.replace("USDT", "")
        prov = CSVOHLCVDataProvider(
            storage_path=str(p),
            symbol=f"{coin}/{TS}",
            time_frame=tf,
            market=MARKET,
            pandas=True,
            data_provider_identifier=sym_to_id[sym] + "_provider",
        )
        app.add_data_provider(prov)

    app.add_portfolio_configuration(PortfolioConfiguration(
        market=MARKET, trading_symbol=TS,
        initial_balance=10_000,
        fee_percentage=0.045, slippage_percentage=0.03,
    ))

    strategies = [UserSOL_BBBreak_LS(), UserETH_CCI(),
                  UserDOGE_Donchian(), MyBTC_Momentum14d()]

    date_range = BacktestDateRange(
        start_date=datetime(2023, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 3, 1, tzinfo=timezone.utc),
        name="2023_to_2026",
    )

    backtests = app.run_vector_backtests(
        backtest_date_ranges=[date_range],
        strategies=strategies,
        backtest_storage_directory=str(BT_DIR),
        show_progress=True,
        continue_on_error=True,
    )

    report = BacktestReport.open(backtests=backtests)
    html_path = WORK / "comparison_report.html"
    report.save(str(html_path))
    print(f"\nWrote {html_path}")

    public = Path("C:/Users/alexandre bandarra/Desktop/newstrategies/IAF_MULTI_COMPARISON.html")
    public.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(html_path, public)
    print(f"Copied {public}")

    print("\n=== Strategy summary ===")
    for bt in backtests:
        try:
            m = bt.metrics
            sid = getattr(bt, "strategy_id", None) or getattr(bt, "name", "?")
            total_pct = getattr(m, "total_gain_percentage", None) or getattr(m, "total_return", 0)
            sharpe    = getattr(m, "sharpe_ratio", 0) or getattr(m, "sharpe", 0)
            dd        = getattr(m, "max_drawdown", 0)
            n         = getattr(m, "number_of_trades", 0) or getattr(m, "total_trades", 0)
            print(f"  {sid:<32}  return {float(total_pct)*100:+.1f}%  "
                  f"Sharpe {float(sharpe):+.2f}  MaxDD {float(dd)*100:+.1f}%  "
                  f"Trades {int(n)}")
        except Exception as e:
            print(f"  (summary error: {e})")


if __name__ == "__main__":
    main()
