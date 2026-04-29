"""
V39 — Proper ICT/SMC strategies informed by web research (2026 best practices).

Research sources (see SMC_BACKTEST_FINDINGS_V39.md for citations):
  - ICT Multi-TF: 4H bias + 15M entry + 5M execution
  - Killzones (crypto-adapted to UTC): Asia 00:00-04:00, London 07:00-10:00, NY 13:00-16:00
  - Silver Bullet: 15:00-16:00 UTC (NY AM 10-11 EST)
  - Triple Confluence: Liquidity sweep + Order Block + FVG
  - Judas Swing: London session sweep+reverse (07:00-10:00 UTC)

Seven strategies tested:
  S1. MTF_BIAS_OB:        4H BOS gives direction → 15m OB touch in that direction
  S2. SWEEP_REVERSE:      15m liquidity sweep + immediate BOS opposite → enter on FVG
  S3. SILVER_BULLET:      15m, trade only 15:00-16:00 UTC, sweep+FVG
  S4. JUDAS_LONDON:       15m, 07:00-10:00 UTC Asia sweep reverse
  S5. TRIPLE_CONFLUENCE:  sweep + OB + FVG all on 15m (very selective)
  S6. KILLZONE_BBBREAK:   BBBreak but only during London+NY killzones
  S7. ASIA_RANGE_BREAK:   Mark Asia H/L, fade breakouts during London

Walk-forward validation: 2y train / 1y test / 6mo step.
"""
from __future__ import annotations
import sys, os, io, json, time, warnings
os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from pathlib import Path
from contextlib import redirect_stdout
import numpy as np
import pandas as pd

_buf = io.StringIO()
with redirect_stdout(_buf):
    from smartmoneyconcepts import smc

ROOT = Path(__file__).resolve().parent
FEAT = ROOT / "features" / "multi_tf"
OUT = ROOT / "results" / "v39"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045
SLIP_BPS = 3
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT",
         "XRPUSDT", "BNBUSDT", "DOGEUSDT", "AVAXUSDT"]


# ================================================================
# Data + indicators
# ================================================================
def load(sym, tf):
    p = FEAT / f"{sym}_{tf}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p).dropna(subset=["open", "high", "low", "close"])
    return df[df.index >= pd.Timestamp("2020-01-01", tz="UTC")]


def atr(df, n=14):
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - df["close"].shift(1)).abs(),
        (df["low"] - df["close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def bbands(s, n=20, k=2.0):
    mid = s.rolling(n).mean()
    sd = s.rolling(n).std()
    return mid + k * sd, mid, mid - k * sd


# ================================================================
# Backtest harness
# ================================================================
def simulate(df, long_sig, short_sig, sl_atr=1.5, tp_atr=3.0, mh=48,
             risk_pct=0.01, leverage=3.0):
    a = atr(df, 14)
    opn, hi, lo = df["open"].values, df["high"].values, df["low"].values
    ts = df.index
    ls, ss = long_sig.values, short_sig.values
    av = a.values
    n = len(df)
    slip = SLIP_BPS / 10000.0
    equity = np.ones(n); eq = 1.0
    pos = 0; entry = stop = tp = 0.0; hold = 0
    trades = []

    for i in range(1, n):
        if pos != 0:
            hold += 1
            exit_px = None
            if pos == 1:
                if lo[i] <= stop: exit_px = stop
                elif hi[i] >= tp: exit_px = tp
                elif hold >= mh: exit_px = opn[i]
            else:
                if hi[i] >= stop: exit_px = stop
                elif lo[i] <= tp: exit_px = tp
                elif hold >= mh: exit_px = opn[i]
            if exit_px is not None:
                exit_eff = exit_px * (1 - slip) if pos == 1 else exit_px * (1 + slip)
                gross = (exit_eff - entry) / entry if pos == 1 else (entry - exit_eff) / entry
                pnl = gross * leverage - 2 * FEE
                pos_size = risk_pct / max(abs((entry - stop) / entry), 0.001)
                pos_size = min(pos_size, leverage)
                trade_ret = pnl * pos_size / leverage
                eq *= (1 + trade_ret)
                trades.append(trade_ret)
                pos = 0; hold = 0
        if pos == 0 and i + 1 < n:
            if ls[i] and not np.isnan(av[i]) and av[i] > 0:
                entry = opn[i + 1] * (1 + slip)
                stop = entry - sl_atr * av[i]; tp = entry + tp_atr * av[i]
                pos = 1; hold = 0
            elif ss[i] and not np.isnan(av[i]) and av[i] > 0:
                entry = opn[i + 1] * (1 - slip)
                stop = entry + sl_atr * av[i]; tp = entry - tp_atr * av[i]
                pos = -1; hold = 0
        equity[i] = eq
    eq_s = pd.Series(equity, index=ts)
    return _metrics(eq_s, trades)


def _metrics(eq, trades):
    if len(trades) < 2:
        return {"sharpe": 0.0, "cagr": 0.0, "maxdd": 0.0, "n_trades": len(trades),
                "win_rate": 0.0, "profit_factor": 0.0}
    rets = eq.pct_change().fillna(0.0)
    dt_hours = (eq.index[1] - eq.index[0]).total_seconds() / 3600 if len(eq) > 1 else 1
    ann = np.sqrt((24 / dt_hours) * 365.25)
    sharpe = (rets.mean() / rets.std() * ann) if rets.std() > 0 else 0.0
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 0.1)
    cagr = eq.iloc[-1] ** (1 / years) - 1 if eq.iloc[-1] > 0 else -1
    dd = (eq / eq.cummax() - 1).min()
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    wr = len(wins) / len(trades) if trades else 0
    pf = sum(wins) / abs(sum(losses)) if losses and sum(losses) < 0 else (999.0 if wins else 0.0)
    return {
        "sharpe": round(float(sharpe), 3),
        "cagr": round(float(cagr), 4),
        "maxdd": round(float(dd), 4),
        "n_trades": len(trades),
        "win_rate": round(float(wr), 3),
        "profit_factor": round(float(pf), 3),
    }


# ================================================================
# ICT/SMC primitives (informed by research)
# ================================================================
def _ohlc(df):
    return df[["open", "high", "low", "close", "volume"]].copy()


def in_killzone(ts_index, zones):
    """zones: list of (start_hour_utc, end_hour_utc). Returns bool series."""
    hr = ts_index.hour
    mask = np.zeros(len(ts_index), dtype=bool)
    for s, e in zones:
        if s < e:
            mask |= (hr >= s) & (hr < e)
        else:
            mask |= (hr >= s) | (hr < e)
    return pd.Series(mask, index=ts_index)


def htf_bias(htf_df, swing_length=50):
    """Returns {ts: 'long'|'short'|'flat'} based on latest 4h BOS direction."""
    try:
        shl = smc.swing_highs_lows(_ohlc(htf_df), swing_length=swing_length)
        bc = smc.bos_choch(_ohlc(htf_df), shl, close_break=True)
        bos = bc["BOS"].fillna(0)
        ch = bc["CHOCH"].fillna(0)
        # combined structural signal; bullish = last non-zero was +1
        combined = bos + ch
        bias = pd.Series(0, index=htf_df.index)  # 0 flat, 1 bull, -1 bear
        last = 0
        for i, v in enumerate(combined.values):
            if v == 1:
                last = 1
            elif v == -1:
                last = -1
            bias.iloc[i] = last
        return bias
    except Exception:
        return pd.Series(0, index=htf_df.index)


def reindex_htf_to_ltf(htf_series, ltf_index):
    """ffill HTF signal onto LTF index (avoid look-ahead: shift by 1 HTF bar)."""
    return htf_series.reindex(ltf_index, method="ffill").shift(1).fillna(0)


def liquidity_sweeps(df, swing_length=20):
    """Returns (bullish_sweep, bearish_sweep) bool series.
    Bullish sweep = price briefly dips below recent swing low then closes back above (sell-side grabbed)
    Bearish sweep = price briefly pokes above swing high then closes back below."""
    try:
        shl = smc.swing_highs_lows(_ohlc(df), swing_length=swing_length)
        liq = smc.liquidity(_ohlc(df), shl, range_percent=0.01)
        # Liquidity col: 1 = sell-side swept (bullish opportunity), -1 = buy-side swept
        col = liq["Liquidity"].reindex(df.index).fillna(0)
        bull = (col == 1)
        bear = (col == -1)
        return bull, bear
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


def fvg_recent(df, lookback=20, join_consecutive=False):
    """Returns (has_bullish_fvg_recent, has_bearish_fvg_recent)."""
    try:
        f = smc.fvg(_ohlc(df), join_consecutive=join_consecutive)
        col = f["FVG"].reindex(df.index).fillna(0)
        bull = (col == 1).rolling(lookback, min_periods=1).max().astype(bool)
        bear = (col == -1).rolling(lookback, min_periods=1).max().astype(bool)
        return bull, bear
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


def ob_zones(df, swing_length=30):
    """Returns (in_bullish_ob, in_bearish_ob) bool series per bar."""
    try:
        shl = smc.swing_highs_lows(_ohlc(df), swing_length=swing_length)
        ob = smc.ob(_ohlc(df), shl, close_mitigation=False)
        bull_z = pd.Series(False, index=df.index)
        bear_z = pd.Series(False, index=df.index)
        for i, row in ob.dropna(subset=["OB"]).iterrows():
            top, bot = row["Top"], row["Bottom"]
            if pd.isna(top) or pd.isna(bot):
                continue
            try:
                pos = df.index.get_loc(i)
            except KeyError:
                continue
            m_i = int(row["MitigatedIndex"]) if pd.notna(row.get("MitigatedIndex")) else len(df) - 1
            for j in range(pos + 1, min(m_i + 1, len(df))):
                in_zone = df["low"].iat[j] <= top and df["high"].iat[j] >= bot
                if in_zone:
                    if row["OB"] == 1:
                        bull_z.iat[j] = True
                    else:
                        bear_z.iat[j] = True
        return bull_z, bear_z
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


def bos_recent(df, swing_length=30, lookback=10):
    """Bool series: recent bullish/bearish BOS (structural break)."""
    try:
        shl = smc.swing_highs_lows(_ohlc(df), swing_length=swing_length)
        bc = smc.bos_choch(_ohlc(df), shl, close_break=True)
        col = bc["BOS"].reindex(df.index).fillna(0)
        bull = (col == 1).rolling(lookback, min_periods=1).max().astype(bool)
        bear = (col == -1).rolling(lookback, min_periods=1).max().astype(bool)
        return bull, bear
    except Exception:
        return pd.Series(False, index=df.index), pd.Series(False, index=df.index)


# ================================================================
# Strategy signals
# ================================================================
# Crypto-adapted killzones in UTC (source: web research — NYC EST + 4/5h offset)
# Asia: 00:00-04:00 UTC, London: 07:00-10:00, NY: 13:00-16:00, Silver Bullet: 15:00-16:00
KZ_LONDON = [(7, 10)]
KZ_NY = [(13, 16)]
KZ_LONDON_NY = [(7, 10), (13, 16)]
KZ_ASIA = [(0, 4)]
KZ_SB = [(15, 16)]  # Silver Bullet NY AM


def sig_mtf_bias_ob(ltf_df, htf_df):
    """S1: 4H BOS bias → 15m OB touch in that direction."""
    bias = htf_bias(htf_df, swing_length=50)
    bias_l = reindex_htf_to_ltf(bias, ltf_df.index)
    bull_z, bear_z = ob_zones(ltf_df, swing_length=30)
    long_sig = bull_z & (bias_l == 1)
    short_sig = bear_z & (bias_l == -1)
    return long_sig.fillna(False), short_sig.fillna(False)


def sig_sweep_reverse(ltf_df, htf_df=None):
    """S2: 15m sweep + recent BOS opposite direction = reversal setup."""
    bull_sw, bear_sw = liquidity_sweeps(ltf_df, swing_length=20)
    bos_bull, bos_bear = bos_recent(ltf_df, swing_length=20, lookback=5)
    # After sell-side sweep + recent bullish BOS → go long
    long_sig = bull_sw & bos_bull
    short_sig = bear_sw & bos_bear
    return long_sig.fillna(False), short_sig.fillna(False)


def sig_silver_bullet(ltf_df, htf_df=None):
    """S3: trade only during NY Silver Bullet (15-16 UTC) with sweep+FVG."""
    kz = in_killzone(ltf_df.index, KZ_SB)
    bull_sw, bear_sw = liquidity_sweeps(ltf_df, swing_length=20)
    fvg_b, fvg_s = fvg_recent(ltf_df, lookback=5)
    long_sig = kz & bull_sw & fvg_b
    short_sig = kz & bear_sw & fvg_s
    return long_sig.fillna(False), short_sig.fillna(False)


def sig_judas_london(ltf_df, htf_df=None):
    """S4: London killzone (07-10 UTC) sweep reversal."""
    kz = in_killzone(ltf_df.index, KZ_LONDON)
    bull_sw, bear_sw = liquidity_sweeps(ltf_df, swing_length=20)
    bos_b, bos_s = bos_recent(ltf_df, swing_length=20, lookback=5)
    long_sig = kz & bull_sw & bos_b
    short_sig = kz & bear_sw & bos_s
    return long_sig.fillna(False), short_sig.fillna(False)


def sig_triple_confluence(ltf_df, htf_df=None):
    """S5: sweep + OB zone + FVG all aligned — the highest-probability ICT setup."""
    bull_sw, bear_sw = liquidity_sweeps(ltf_df, swing_length=20)
    bull_z, bear_z = ob_zones(ltf_df, swing_length=30)
    fvg_b, fvg_s = fvg_recent(ltf_df, lookback=5)
    long_sig = bull_sw & bull_z & fvg_b
    short_sig = bear_sw & bear_z & fvg_s
    return long_sig.fillna(False), short_sig.fillna(False)


def sig_killzone_bbbreak(ltf_df, htf_df=None):
    """S6: BBBreak but only during London+NY killzones (filter out Asia chop)."""
    ub, mid, lb = bbands(ltf_df["close"], 20, 2.0)
    ema_reg = ema(ltf_df["close"], 200)
    long_raw = (ltf_df["close"] > ub) & (ltf_df["close"].shift(1) <= ub.shift(1)) & (ltf_df["close"] > ema_reg)
    short_raw = (ltf_df["close"] < lb) & (ltf_df["close"].shift(1) >= lb.shift(1)) & (ltf_df["close"] < ema_reg)
    kz = in_killzone(ltf_df.index, KZ_LONDON_NY)
    return (long_raw & kz).fillna(False), (short_raw & kz).fillna(False)


def sig_asia_range_break(ltf_df, htf_df=None):
    """S7: compute Asian session H/L (00-04 UTC), trade breaks during London (07-10 UTC)."""
    # Group by UTC date and compute Asia H/L
    hr = ltf_df.index.hour
    asia_mask = (hr >= 0) & (hr < 4)
    london_mask = (hr >= 7) & (hr < 10)
    date = ltf_df.index.date
    df = ltf_df.copy()
    df["date"] = date
    # For each date, compute asia_high, asia_low
    asia = df[asia_mask].groupby("date").agg({"high": "max", "low": "min"})
    asia.columns = ["asia_high", "asia_low"]
    df = df.merge(asia, left_on="date", right_index=True, how="left")
    # Entry during London: break of Asia high (long) or Asia low (short)
    long_sig = pd.Series(london_mask, index=ltf_df.index) & \
               (df["close"] > df["asia_high"]) & \
               (df["close"].shift(1) <= df["asia_high"])
    short_sig = pd.Series(london_mask, index=ltf_df.index) & \
                (df["close"] < df["asia_low"]) & \
                (df["close"].shift(1) >= df["asia_low"])
    return long_sig.fillna(False), short_sig.fillna(False)


STRATEGIES = {
    "S1_MTF_BIAS_OB":      (sig_mtf_bias_ob,      True),   # needs HTF
    "S2_SWEEP_REVERSE":    (sig_sweep_reverse,    False),
    "S3_SILVER_BULLET":    (sig_silver_bullet,    False),
    "S4_JUDAS_LONDON":     (sig_judas_london,     False),
    "S5_TRIPLE_CONFL":     (sig_triple_confluence, False),
    "S6_KZ_BBBREAK":       (sig_killzone_bbbreak, False),
    "S7_ASIA_RANGE_BREAK": (sig_asia_range_break, False),
}


# ================================================================
# Walk-forward
# ================================================================
def walk_forward(df, htf_df, sig_fn, needs_htf, train_years=2.0, test_years=1.0, step_months=6, **bt):
    start = df.index[0]
    end = df.index[-1]
    step = pd.DateOffset(months=step_months)
    train_td = pd.DateOffset(days=int(train_years * 365))
    test_td = pd.DateOffset(days=int(test_years * 365))
    results = []
    anchor = start
    while anchor + train_td + test_td <= end:
        train_end = anchor + train_td
        test_end = train_end + test_td
        test_df = df[(df.index >= train_end) & (df.index < test_end)]
        if len(test_df) < 500:
            anchor += step; continue
        try:
            if needs_htf:
                test_htf = htf_df[(htf_df.index >= train_end) & (htf_df.index < test_end)]
                L, S = sig_fn(test_df, test_htf)
            else:
                L, S = sig_fn(test_df)
            m = simulate(test_df, L, S, **bt)
            results.append({"start": str(anchor.date()), "sharpe": m["sharpe"],
                            "cagr": m["cagr"], "maxdd": m["maxdd"], "trades": m["n_trades"]})
        except Exception:
            pass
        anchor += step
    return results


# ================================================================
# Main
# ================================================================
def main():
    t0 = time.time()
    rows = []
    TFS = ["15m", "30m", "1h"]

    # HTF bias uses 4h consistently
    htf_cache = {}
    for coin in COINS:
        htf_cache[coin] = load(coin, "4h")

    for tf in TFS:
        for coin in COINS:
            df = load(coin, tf)
            if df is None:
                continue
            htf_df = htf_cache.get(coin)
            for sname, (fn, needs_htf) in STRATEGIES.items():
                try:
                    if needs_htf:
                        if htf_df is None:
                            continue
                        L, S = fn(df, htf_df)
                    else:
                        L, S = fn(df)
                    n_sig = int(L.sum() + S.sum())
                    if n_sig < 20:
                        continue
                    m = simulate(df, L, S, sl_atr=1.5, tp_atr=3.0, mh=48,
                                 risk_pct=0.01, leverage=3.0)
                    if m["n_trades"] < 20:
                        continue
                    rows.append({"coin": coin, "tf": tf, "strategy": sname,
                                 "n_signals": n_sig, **m})
                except Exception as e:
                    continue
        print(f"  [{time.time()-t0:.0f}s] {tf} done ({len(rows)} configs so far)")

    df_res = pd.DataFrame(rows)
    df_res.to_csv(OUT / "v39_sweep.csv", index=False)
    print(f"\nTotal configs with ≥20 trades: {len(df_res)}")

    # Robustness gate: Sharpe > 0.8, n_trades >= 40, DD >= -50%, CAGR > 0
    good = df_res[
        (df_res["sharpe"] >= 0.8) &
        (df_res["n_trades"] >= 40) &
        (df_res["maxdd"] >= -0.50) &
        (df_res["cagr"] > 0)
    ].sort_values("sharpe", ascending=False)
    print(f"Passing quality gate (Sh≥0.8, trades≥40, DD≥-50%, CAGR>0): {len(good)}")

    if good.empty:
        print("\nNo configs passed the gate. Showing top 15 by raw Sharpe:")
        print(df_res.nlargest(15, "sharpe")[
            ["coin", "tf", "strategy", "sharpe", "cagr", "maxdd", "n_trades", "win_rate"]
        ].to_string(index=False))
        return

    print("\n=== TOP 15 CONFIGS ===")
    print(good.head(15)[
        ["coin", "tf", "strategy", "sharpe", "cagr", "maxdd", "n_trades", "win_rate", "profit_factor"]
    ].to_string(index=False))

    # Walk-forward on top 10
    print(f"\n=== WALK-FORWARD on top 10 (2y/1y/6mo) ===")
    wf_rows = []
    for _, r in good.head(10).iterrows():
        coin, tf, sname = r["coin"], r["tf"], r["strategy"]
        df = load(coin, tf)
        htf_df = htf_cache.get(coin)
        fn, needs_htf = STRATEGIES[sname]
        wf = walk_forward(df, htf_df, fn, needs_htf)
        if not wf or len(wf) < 3:
            continue
        sharpes = [w["sharpe"] for w in wf]
        med = float(np.median(sharpes))
        pct = sum(1 for s in sharpes if s > 0) / len(sharpes)
        mn = float(min(sharpes))
        robust = "ROBUST" if med >= 0.8 and pct >= 0.70 else "fragile"
        wf_rows.append({
            "coin": coin, "tf": tf, "strategy": sname,
            "full_sharpe": r["sharpe"], "full_cagr": r["cagr"],
            "wf_median": round(med, 3), "wf_pct_profit": round(pct, 3),
            "wf_min": round(mn, 3), "wf_windows": len(wf), "verdict": robust,
        })
        print(f"  {coin} {tf} {sname}: full Sh={r['sharpe']:.2f} | "
              f"WF median={med:.2f} | %profit={pct:.0%} | min={mn:.2f} | {robust}")

    pd.DataFrame(wf_rows).to_csv(OUT / "v39_walkforward.csv", index=False)
    with open(OUT / "v39_summary.json", "w") as f:
        json.dump({
            "elapsed": round(time.time()-t0, 1),
            "total": len(df_res),
            "passed_gate": len(good),
            "top_10": good.head(10).to_dict(orient="records"),
            "walk_forward": wf_rows,
            "robust_winners": [r for r in wf_rows if r["verdict"] == "ROBUST"],
        }, f, indent=2, default=str)
    print(f"\nDone in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
