"""
V24-XSM SHADOW  (paper, no real orders)
=======================================

Cross-sectional momentum basket — the validated V24 "multi_filter" champion.

Strategy (exactly as validated in strategy_lab/v23_low_dd_xsm.py, mode="multi_filter"):
  Universe : BTC ETH SOL LINK ADA XRP BNB DOGE AVAX  (USDT), 9 coins
  Bars     : 4h  (BARS_PER_DAY = 6)
  Rebalance: every 7 days
  Filter (ALL must pass to deploy, else FLAT):
    1. BTC close > BTC 100d-MA
    2. BTC 50d-MA rising  (btc_ma_fast[i] >= btc_ma_fast[i-24 bars])   <-- exact code, not the comment
    3. Market breadth >= 5 of 9 coins above their own 50d-MA
  Allocation when deployed: long the top-4 coins by 14d momentum, equal weight, leverage 1.0.

Data (fresh):
  BTC/ETH/SOL/AVAX/LINK 4h close -> Hyperliquid (data/hyperliquid/parquet, fresh)
  ADA/XRP/BNB/DOGE      4h close -> Binance Vision parquet (data/binance/parquet)
  (HL vs Binance close corr 0.9997 — close prices are interchangeable for MA/momentum.)

Output (written to shadow_v52/):
  xsm_status.csv      one-row current decision (filter state + target basket)
  XSM_STATUS.md       human-readable
Returns a dict for the tick to fold into the combined status.

This is PAPER ONLY. It records the basket the live XSM bot WOULD hold.
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from strategy_lab.util.hl_data import load_hl

OUT_DIR = REPO / "shadow_v52"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- exact V24 champion params ----
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "AVAXUSDT"]
HL_COINS = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "SOLUSDT": "SOL", "AVAXUSDT": "AVAX", "LINKUSDT": "LINK"}
BARS_PER_DAY = 6
LOOKBACK_DAYS = 14
TOP_K = 4
REBAL_DAYS = 7
BTC_MA_DAYS = 100
MF_BTC_MA_FAST = 50
MF_BREADTH_MIN = 5
LEVERAGE = 1.0

BINANCE_PARQ = REPO / "data" / "binance" / "parquet"


def _load_binance_4h_close(sym: str) -> pd.Series:
    base = BINANCE_PARQ / sym / "4h"
    if not base.exists():
        return pd.Series(dtype=float)
    parts = []
    for yr_dir in sorted(base.glob("year=*")):
        p = yr_dir / "part.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            if "open_time" in df.columns:
                df = df.set_index("open_time")
            parts.append(df["close"])
    if not parts:
        return pd.Series(dtype=float)
    s = pd.concat(parts).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if s.index.tz is None:
        s.index = s.index.tz_localize("UTC")
    return s


def _load_close_panel() -> tuple[pd.DataFrame, dict]:
    """Build a 9-coin 4h close panel from fresh HL + Binance sources."""
    series = {}
    src = {}
    for sym in COINS:
        if sym in HL_COINS:
            try:
                df = load_hl(HL_COINS[sym], "4h")
                series[sym] = df["close"]
                src[sym] = f"HL ({df.index.max():%Y-%m-%d %H:%M})"
                continue
            except Exception:
                pass
        # fallback / non-HL coin -> Binance
        s = _load_binance_4h_close(sym)
        if len(s):
            series[sym] = s
            src[sym] = f"Binance ({s.index.max():%Y-%m-%d %H:%M})"
        else:
            src[sym] = "MISSING"
    idx = None
    for s in series.values():
        idx = s.index if idx is None else idx.union(s.index)
    close = pd.DataFrame({k: v.reindex(idx).ffill() for k, v in series.items()})
    return close, src


def evaluate(now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp.now(tz="UTC")
    close, src = _load_close_panel()
    if "BTCUSDT" not in close or close["BTCUSDT"].dropna().empty:
        return {"status": "NO_DATA", "src": src}

    i = len(close) - 1  # latest bar
    btc = close["BTCUSDT"]
    btc_ma = btc.rolling(BTC_MA_DAYS * BARS_PER_DAY).mean()
    btc_ma_fast = btc.rolling(MF_BTC_MA_FAST * BARS_PER_DAY).mean()
    per_coin_ma50 = {s: close[s].rolling(50 * BARS_PER_DAY).mean() for s in close}

    # ---- filter checks (exact replica) ----
    btc_above_100 = bool(btc.iloc[i] >= btc_ma.iloc[i]) if not np.isnan(btc_ma.iloc[i]) else False
    btc_bear = not btc_above_100

    btc_fast_rising = True
    if not np.isnan(btc_ma_fast.iloc[i]):
        if i >= MF_BTC_MA_FAST * BARS_PER_DAY + 24:
            btc_fast_rising = bool(btc_ma_fast.iloc[i] >= btc_ma_fast.iloc[i - 24])
            if not btc_fast_rising:
                btc_bear = True

    breadth = 0
    breadth_detail = {}
    for s in close:
        ma = per_coin_ma50[s].iloc[i]
        above = bool(not np.isnan(ma) and close[s].iloc[i] > ma)
        breadth_detail[s] = above
        if above:
            breadth += 1
    if breadth < MF_BREADTH_MIN:
        btc_bear = True

    filter_active = not btc_bear

    # ---- momentum ranking + target basket (if active) ----
    lookback_bars = LOOKBACK_DAYS * BARS_PER_DAY
    target = []
    if filter_active and i >= lookback_bars:
        scores = {}
        for s in close:
            p_now = close[s].iloc[i]; p0 = close[s].iloc[i - lookback_bars]
            if not (np.isnan(p_now) or np.isnan(p0) or p0 <= 0):
                scores[s] = (p_now / p0) - 1.0
        ranked = sorted(scores, key=lambda x: scores[x], reverse=True)
        longs = ranked[:TOP_K]
        w = LEVERAGE / TOP_K
        for s in longs:
            target.append({
                "coin": s, "weight": round(w, 4),
                "momentum_14d_pct": round(scores[s] * 100, 2),
                "hl_tradeable": s in HL_COINS,
            })

    # next rebalance estimate (weekly cadence from the latest bar)
    last_bar_ts = close.index[i]
    return {
        "status": "ACTIVE" if filter_active else "FLAT",
        "eval_bar_ts": last_bar_ts.isoformat(),
        "btc_above_100dma": btc_above_100,
        "btc_50dma_rising": btc_fast_rising,
        "breadth": f"{breadth}/9",
        "breadth_pass": breadth >= MF_BREADTH_MIN,
        "breadth_detail": breadth_detail,
        "target_basket": target,
        "src": src,
    }


def write_outputs(res: dict, now: pd.Timestamp | None = None):
    now = now or pd.Timestamp.now(tz="UTC")
    # CSV one-row
    row = {
        "run_ts": now.isoformat(),
        "status": res.get("status"),
        "eval_bar_ts": res.get("eval_bar_ts"),
        "btc_above_100dma": res.get("btc_above_100dma"),
        "btc_50dma_rising": res.get("btc_50dma_rising"),
        "breadth": res.get("breadth"),
        "target_basket": ";".join(f"{t['coin']}:{t['weight']}" for t in res.get("target_basket", [])) or "FLAT",
    }
    csv_path = OUT_DIR / "xsm_status.csv"
    df = pd.DataFrame([row])
    if csv_path.exists():
        df = pd.concat([pd.read_csv(csv_path), df], ignore_index=True).tail(500)
    df.to_csv(csv_path, index=False)

    # MD
    lines = ["# V24-XSM Shadow Status", "",
             f"**Run:** {now.isoformat()}",
             f"**Mode:** PAPER (no real orders). Validated 9-coin cross-sectional momentum.",
             f"**Eval bar:** {res.get('eval_bar_ts')}",
             "",
             f"## Filter: **{res.get('status')}**", ""]
    if res.get("status") == "NO_DATA":
        lines.append("> NO DATA — check sources.")
    else:
        lines += [
            f"- BTC > 100d-MA: **{res.get('btc_above_100dma')}**",
            f"- BTC 50d-MA rising: **{res.get('btc_50dma_rising')}**",
            f"- Breadth (>=5/9 needed): **{res.get('breadth')}** ({'PASS' if res.get('breadth_pass') else 'FAIL'})",
            "",
        ]
        if res.get("status") == "ACTIVE":
            lines += ["## Target basket (long, equal-weight)", "",
                      "| Coin | Weight | 14d momentum % | HL-tradeable |",
                      "|---|---:|---:|:---:|"]
            for t in res["target_basket"]:
                lines.append(f"| {t['coin']} | {t['weight']} | {t['momentum_14d_pct']} | {'yes' if t['hl_tradeable'] else 'NO (Binance only)'} |")
        else:
            lines.append("_Filter gated OFF → XSM holds **CASH** (flat). This is correct defensive behavior; "
                         "in 2026 the filter passes only ~4-5% of bars._")
        lines += ["", "## Data sources (freshness)", ""]
        for s, v in res.get("src", {}).items():
            lines.append(f"- {s}: {v}")
    (OUT_DIR / "XSM_STATUS.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    now = pd.Timestamp.now(tz="UTC")
    res = evaluate(now)
    write_outputs(res, now)
    print(f"[{now.isoformat()}] XSM shadow: {res.get('status')} | "
          f"breadth {res.get('breadth')} | btc>100dMA {res.get('btc_above_100dma')} | "
          f"50dMA_rising {res.get('btc_50dma_rising')}")
    if res.get("target_basket"):
        print("  target longs:", ", ".join(f"{t['coin']}({t['momentum_14d_pct']}%)" for t in res["target_basket"]))
    return res


if __name__ == "__main__":
    main()
