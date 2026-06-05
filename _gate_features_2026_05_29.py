"""
_gate_features_2026_05_29.py — compute candidate gate features at fire_us (causal) for the
lag-taker base universe (BTC+ETH, delta_bps>=3). Writes an enriched parquet to feed the
conditional-analysis step. Features strictly use data at/before fire_us (no lookahead).

Gates computed here:
  delta_bps (already in fires)            -> gate1 tiers
  persist3 = last 3 1s bars same sign as direction   -> gate2 persistence
  rv30 = realized vol (std of 1s log-rets) over 30s pre-fire (bps)  -> gate3 vol regime
  rv60 = same over 60s
  topdepth_usd = $ at best ask on entry side (book at/before fire)  -> gate4 depth
  spread = ask0 - bid0 on entry-side token's book                  -> gate4 spread
  rsi14_1s, macd_hist_1s, cci20_1s = ta on 1s closes at fire        -> gate8 micro
  (cross-asset confluence handled in analysis step via slot overlap)
Run: C:/Python314/python.exe _gate_features_2026_05_29.py
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_orderbook_l25_streaming  # noqa: E402

CANON = ROOT / "data" / "v4" / "canonical"
SYM = {"BTC": "BINANCE_SPOT_BTC_USDT", "ETH": "BINANCE_SPOT_ETH_USDT", "SOL": "BINANCE_SPOT_SOL_USDT"}
OUT = ROOT / "strategy_lab" / "lag_taker_fires_enriched_2026_05_29.parquet"

print("FEATURES_V1_MARKER", flush=True)
t0 = time.time()

F = pd.read_parquet(ROOT / "strategy_lab" / "lag_taker_fires_2026_05_29.parquet")
# base universe + keep SOL rows too so cross-asset / extended checks possible, but flag base
F["is_base"] = (F.asset.isin(["BTC", "ETH"])) & (F.delta_bps >= 3.0)
print("total fires:", len(F), "base:", int(F.is_base.sum()), flush=True)


def binance_1s(asset):
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["time_period_start_us", "price_close", "symbol_id", "source", "period_id"])
    df = df[(df.symbol_id == SYM[asset]) & (df.source == "binance-spot-ws")
            & (df.period_id == "1SEC")].sort_values("time_period_start_us")
    # bar that ENDED at-or-before t: end = start+1e6
    return (df.time_period_start_us.values.astype(np.int64) + 1_000_000), df.price_close.values.astype(float)


def rsi_wilder_simple(closes):
    """Production simple-mean Wilder RSI over the supplied closes (len=period+1 -> 1 value)."""
    d = np.diff(closes)
    up = np.clip(d, 0, None).mean()
    dn = -np.clip(d, None, 0).mean()
    if dn == 0:
        return 100.0
    rs = up / dn
    return 100.0 - 100.0 / (1.0 + rs)


def ema(arr, span):
    a = 2.0 / (span + 1.0)
    out = arr[0]
    for x in arr[1:]:
        out = a * x + (1 - a) * out
    return out


# load binance per asset
bz = {a: binance_1s(a) for a in ["BTC", "ETH"]}
print("binance loaded", round(time.time() - t0), "s", flush=True)

# ---- klines-derived features (persistence, realized vol, ta) ----
feat = {k: [] for k in ["persist3", "rv30_bps", "rv60_bps", "rsi14", "macd_hist", "cci20"]}
for asset in ["BTC", "ETH"]:
    be, bc = bz[asset]
    sub = F[F.asset == asset]
    for fire in sub.fire_us.values:
        fire = int(fire)
        # index of last bar ending at/before fire
        i = np.searchsorted(be, fire, side="right") - 1
        if i < 0:
            for k in feat:
                feat[k].append(np.nan)
            continue
        # persistence: signs of last 3 1s returns (bar i-2..i)
        if i >= 3:
            r = np.diff(bc[i - 3:i + 1])  # 3 returns ending at bar i
            persist = float(np.all(r > 0) or np.all(r < 0))
        else:
            persist = np.nan
        # realized vol over 30s/60s pre-fire (std of 1s log returns, in bps)
        def rv(n):
            if i >= n:
                seg = bc[i - n:i + 1]
                lr = np.diff(np.log(seg))
                return float(np.std(lr) * 1e4)
            return np.nan
        rv30 = rv(30); rv60 = rv(60)
        # RSI14: 15 closes ending at bar i
        rsi = rsi_wilder_simple(bc[i - 14:i + 1]) if i >= 14 else np.nan
        # MACD hist on 1s closes (12,26,9) — last 35 closes enough-ish; use 40
        if i >= 40:
            seg = bc[i - 40:i + 1]
            # rolling EMAs
            def ema_series(arr, span):
                a = 2.0 / (span + 1.0); o = [arr[0]]
                for x in arr[1:]:
                    o.append(a * x + (1 - a) * o[-1])
                return np.array(o)
            e12 = ema_series(seg, 12); e26 = ema_series(seg, 26)
            macd_line = e12 - e26
            sig = ema_series(macd_line, 9)
            macd_h = float(macd_line[-1] - sig[-1])
        else:
            macd_h = np.nan
        # CCI20 on 1s closes (typical price = close here)
        if i >= 20:
            seg = bc[i - 19:i + 1]
            tp = seg
            sma = tp.mean()
            md = np.mean(np.abs(tp - sma))
            cci = float((tp[-1] - sma) / (0.015 * md)) if md > 0 else 0.0
        else:
            cci = np.nan
        feat["persist3"].append(persist)
        feat["rv30_bps"].append(rv30)
        feat["rv60_bps"].append(rv60)
        feat["rsi14"].append(rsi)
        feat["macd_hist"].append(macd_h)
        feat["cci20"].append(cci)
    print(f"  klines feats {asset} done {round(time.time()-t0)}s", flush=True)

# assemble in F order (BTC then ETH then SOL). We only filled BTC+ETH; SOL gets nan.
# Build aligned arrays by re-iterating F in same asset order used above.
order_idx = list(F[F.asset == "BTC"].index) + list(F[F.asset == "ETH"].index)
for k in feat:
    s = pd.Series(index=order_idx, data=feat[k], dtype=float)
    F[k] = s.reindex(F.index)

print("klines features attached", round(time.time() - t0), "s", flush=True)

# ---- L25 book features (top-of-book depth + spread on entry side) at/before fire ----
topdepth = pd.Series(index=F.index, dtype=float)
spread_eff = pd.Series(index=F.index, dtype=float)
for asset in ["BTC", "ETH"]:
    sub = F[F.asset == asset]
    slugs = set(sub.slug.values)
    books = load_orderbook_l25_streaming(asset.lower(), slugs=slugs, subsample_1hz=False)
    for idx, row in sub.iterrows():
        key = (row.slug, row.direction)  # outcome token we BUY
        if key not in books:
            continue
        ts, ap, asz, bp, bsz = books[key]
        j = np.searchsorted(ts, int(row.fire_us), side="right") - 1
        if j < 0:
            continue
        a0 = ap[j, 0]; b0 = bp[j, 0]; a0sz = asz[j, 0]
        if np.isfinite(a0) and np.isfinite(a0sz):
            topdepth.loc[idx] = float(a0 * a0sz)  # $ resting at best ask we hit
        if np.isfinite(a0) and np.isfinite(b0):
            spread_eff.loc[idx] = float(a0 - b0)
    print(f"  book feats {asset} done {round(time.time()-t0)}s", flush=True)

F["topdepth_usd"] = topdepth
F["spread_eff"] = spread_eff

F.to_parquet(OUT, index=False)
print("WROTE", OUT, "rows", len(F), flush=True)
b = F[F.is_base]
print("base feat coverage (non-nan frac):", flush=True)
for c in ["persist3", "rv30_bps", "rv60_bps", "rsi14", "macd_hist", "cci20", "topdepth_usd", "spread_eff"]:
    print(f"  {c}: {b[c].notna().mean():.3f}  median={b[c].median():.4g}", flush=True)
print("DONE", round(time.time() - t0), "s", flush=True)
