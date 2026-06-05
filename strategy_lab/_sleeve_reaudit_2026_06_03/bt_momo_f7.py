"""
SLEEVE 2 REAUDIT: poly_updown_btc_15m_momo_HOLD_f7
Fresh backtest Apr24 -> Jun1 09:00 UTC on canonical data.

LOGIC (faithful to VPS3 live, verified in meta_classifier/backtest_vs_live_momo_2026_05_29.py):
  - momo_v1: ws_s = slug_suffix - window_s (= slot_start - 900)
  - ret_2m = log(close@(ws_s+120) / close@ws_s)  [v1 anchor]
  - fire_us = (ws_s + 120) * 1_000_000
  - direction: UP if ret_2m > 0, DOWN if ret_2m < 0
  - Gate: |ret_2m| >= q90 of rolling 14d abs_ret_2m samples
  - F7 gate: RSI(14) simple-mean Wilder at ws_s > 50 for UP, < 50 for DOWN
  - Fill: L25 $25 @ fire_us, hold to settlement
  - Fee: LegacyConfig (2%-on-profit only)
  - spread_filter: 0.02

F7 RSI: 14-period simple-mean Wilder on 1-MIN binance closes, anchor=ws_s.
  closes = 15 bars at offsets [-840,-780,...,-60,0] from ws_s (i.e. ws_s-840s to ws_s)
  verified 94.67% match vs live (from CLAUDE.md).

Window for q90 threshold: rolling 14d lookback from ws_s.
"""
from __future__ import annotations
import sys, math, gc
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions, load_klines_asof, load_orderbook_l25_streaming
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl

NOTIONAL = 25.0
SPREAD_FILTER = 0.02
WINDOW_S = 900  # 15m
CFG = LegacyConfig()
GATE_Q = 0.90
LOOKBACK_DAYS = 14
RSI_PERIOD = 14  # F7 uses 14 bars

# ── 1. Load 1MIN klines ──────────────────────────────────────────────────────
print("[1] Loading 1MIN klines …")
eu_1m, cl_1m = load_klines_asof("BTC", source="binance-spot-ws", period_id="1MIN")
eu_1m = eu_1m.astype("int64")
cl_1m = cl_1m.astype("float64")
print(f"   {len(eu_1m)} bars, {pd.Timestamp(int(eu_1m[0]),unit='us',tz='UTC')} to {pd.Timestamp(int(eu_1m[-1]),unit='us',tz='UTC')}")

def close_at(target_s: int) -> float:
    """Close of 1MIN bar that ended at or before target_s (in seconds)."""
    target_us = int(target_s) * 1_000_000
    i = int(np.searchsorted(eu_1m, target_us, side="right")) - 1
    return float("nan") if i < 0 else float(cl_1m[i])

def wilder_rsi(closes: np.ndarray, period: int = 14) -> float:
    """Simple-mean Wilder RSI (matches production rsi.py — verified 94.67%)."""
    if len(closes) < period + 1:
        return float("nan")
    diffs = np.diff(closes[-period-1:])
    gains = diffs[diffs > 0]
    losses = -diffs[diffs < 0]
    avg_gain = gains.mean() if len(gains) > 0 else 0.0
    avg_loss = losses.mean() if len(losses) > 0 else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))

def rsi_at_ws(ws_s: int) -> float:
    """F7 RSI: 15 closes at ws_s-840, ws_s-780, ..., ws_s (step=60s).
    Uses 14 diffs -> RSI(14). Anchor = ws_s (verified anchor for F7)."""
    offsets = list(range(-840, 1, 60))  # [-840, -780, ..., 0], 15 values
    closes = np.array([close_at(ws_s + o) for o in offsets])
    if np.any(np.isnan(closes)):
        return float("nan")
    return wilder_rsi(closes, period=14)

# ── 2. Load resolutions ──────────────────────────────────────────────────────
print("[2] Loading BTC 15m resolutions …")
res = load_resolutions(assets=["BTC"], timeframes=["15m"])
APR24 = int(pd.Timestamp("2026-04-24 00:00:00", tz="UTC").value // 1000)
JUN1 = int(pd.Timestamp("2026-06-01 09:00:00", tz="UTC").value // 1000)
res = res[(res["slot_start_us"] >= APR24) & (res["slot_start_us"] <= JUN1)].copy()
res = res.sort_values("slot_start_us").reset_index(drop=True)
print(f"   {len(res)} slots")

def slug_to_ws_s(slot_start_s: int) -> int:
    return slot_start_s - WINDOW_S

# ── 3. Build rolling ret_2m series for q90 threshold ────────────────────────
print("[3] Building rolling ret_2m series for threshold …")
# Compute ret_2m for every slot (for rolling q90)
slot_starts_s = (res["slot_start_us"] / 1_000_000).astype(int).values
ret2m_all = []
for sss in slot_starts_s:
    ws_s = sss - WINDOW_S
    c0 = close_at(ws_s)
    c1 = close_at(ws_s + 120)
    if math.isnan(c0) or math.isnan(c1) or c0 <= 0:
        ret2m_all.append(float("nan"))
    else:
        ret2m_all.append(math.log(c1 / c0))
ret2m_arr = np.array(ret2m_all)
print(f"   ret_2m computed for {np.sum(~np.isnan(ret2m_arr))} slots")

# ── 4. Fire loop ─────────────────────────────────────────────────────────────
print("[4] Computing fires …")
fires = []
LOOKBACK_SLOTS = LOOKBACK_DAYS * 24 * 4  # 14d * 96 slots/day for 15m

for idx, row in res.iterrows():
    sss = int(row["slot_start_us"] / 1_000_000)
    ws_s = sss - WINDOW_S
    fire_us = (ws_s + 120) * 1_000_000

    # ret_2m (causal)
    ret2m = ret2m_arr[idx]
    if math.isnan(ret2m) or ret2m == 0:
        continue

    # Rolling q90 threshold (14d lookback, exclude current)
    lo = max(0, idx - LOOKBACK_SLOTS)
    hist = ret2m_arr[lo:idx]
    hist_valid = hist[~np.isnan(hist)]
    if len(hist_valid) < 50:
        continue
    threshold = float(np.quantile(np.abs(hist_valid), GATE_Q))
    if abs(ret2m) < threshold:
        continue

    # Direction
    direction = "UP" if ret2m > 0 else "DOWN"

    # F7 RSI gate
    rsi_val = rsi_at_ws(ws_s)
    if math.isnan(rsi_val):
        continue
    if direction == "UP" and rsi_val <= 50:
        continue
    if direction == "DOWN" and rsi_val >= 50:
        continue

    fires.append({
        "slug": row["slug"],
        "slot_start_us": int(row["slot_start_us"]),
        "ws_s": ws_s,
        "fire_us": fire_us,
        "direction": direction,
        "ret2m": ret2m,
        "threshold": threshold,
        "rsi": rsi_val,
        "outcome": row["outcome"],
        "won": (direction == "UP" and row["outcome"] == "Up") or
               (direction == "DOWN" and row["outcome"] == "Down"),
    })

f = pd.DataFrame(fires)
print(f"   Total fires before fill: {len(f)}")

# ── 5. Load L25 and fill ─────────────────────────────────────────────────────
print("[5] Loading L25 books …")
# Load in batches by slug to bound memory
all_slugs = set(f["slug"].tolist())
# Single load call (BTC only, bounded time window)
books = load_orderbook_l25_streaming(
    "btc",
    slugs=all_slugs,
    subsample_1hz=False,
    min_ts_us=APR24,
    max_ts_us=JUN1 + 900 * 1_000_000,
)
print(f"   Books loaded for {len(all_slugs)} slugs")

print("[6] Filling fires …")
filled = []
for _, row in f.iterrows():
    direction = row["direction"]
    outcome_side = "Up" if direction == "UP" else "Down"
    fill = fill_at_book(books, row["slug"], outcome_side, int(row["fire_us"]),
                        cfg=CFG, spread_filter=SPREAD_FILTER)
    if fill is None:
        continue
    won = bool(row["won"])
    pnl_legacy = hold_pnl(fill, won=won, cfg=CFG)
    shares = NOTIONAL / fill["vwap"]
    if won:
        pnl_07 = shares * (1 - fill["vwap"]) * (1 - 0.07 * fill["vwap"])
    else:
        pnl_07 = -shares * fill["vwap"]
    filled.append({
        "slug": row["slug"],
        "fire_us": row["fire_us"],
        "direction": direction,
        "outcome": row["outcome"],
        "won": won,
        "entry_vwap": fill["vwap"],
        "ret2m": row["ret2m"],
        "rsi": row["rsi"],
        "pnl_legacy": pnl_legacy,
        "pnl_07": pnl_07,
    })

del books; gc.collect()

all_fires = pd.DataFrame(filled)
print(f"   Filled fires: {len(all_fires)}")

# ── 7. Stats ─────────────────────────────────────────────────────────────────
print("\n" + "="*70)
print("SLEEVE 2: poly_updown_btc_15m_momo_HOLD_f7")
print("BACKTEST Apr24 -> Jun1 09:00 UTC")
print("="*70)

n = len(all_fires)
wr = all_fires["won"].mean()
pnl_legacy = all_fires["pnl_legacy"].sum()
pnl_07 = all_fires["pnl_07"].sum()

print(f"\n  n={n}  WR={wr:.4f} ({100*wr:.1f}%)  $/tr(legacy)={all_fires['pnl_legacy'].mean():.3f}  total(legacy)={pnl_legacy:.2f}")
print(f"  $/tr(0.07)={all_fires['pnl_07'].mean():.3f}  total(0.07)={pnl_07:.2f}")

from scipy import stats
binom_p = stats.binomtest(int(all_fires["won"].sum()), n, 0.5, alternative="greater").pvalue
print(f"  binom_p(WR>50%)={binom_p:.6f}")

rng = np.random.default_rng(42)
bt_means = [rng.choice(all_fires["pnl_legacy"].values, size=n, replace=True).mean() for _ in range(5000)]
ci_lo, ci_hi = np.percentile(bt_means, [2.5, 97.5])
print(f"  bootstrap 95% CI $/tr: [{ci_lo:.3f}, {ci_hi:.3f}]")

cum = all_fires["pnl_legacy"].cumsum()
max_dd = (cum - cum.cummax()).min()
print(f"  max_drawdown(legacy)={max_dd:.2f}")

# By week
all_fires["dt"] = pd.to_datetime(all_fires["fire_us"], unit="us", utc=True)
all_fires["yw"] = all_fires["dt"].dt.isocalendar().year.astype(str) + "-W" + \
                  all_fires["dt"].dt.isocalendar().week.astype(str).str.zfill(2)

print("\n  --- By week ---")
wk = all_fires.groupby("yw").agg(
    n=("won", "size"),
    wr=("won", lambda x: round(x.mean(), 4)),
    pnl_legacy=("pnl_legacy", lambda x: round(x.sum(), 2)),
    pnl_07=("pnl_07", lambda x: round(x.sum(), 2)),
).reset_index()
print(wk.to_string(index=False))

# OOS split 60/40
split_idx = int(n * 0.6)
train = all_fires.iloc[:split_idx]
test = all_fires.iloc[split_idx:]
print(f"\n  --- OOS split (60/40) ---")
print(f"  TRAIN n={len(train)} WR={train['won'].mean():.4f} $/tr={train['pnl_legacy'].mean():.3f} total={train['pnl_legacy'].sum():.2f}")
print(f"  TEST  n={len(test)}  WR={test['won'].mean():.4f} $/tr={test['pnl_legacy'].mean():.3f} total={test['pnl_legacy'].sum():.2f}")

# Direction breakdown
print("\n  --- By direction ---")
for d in ["UP", "DOWN"]:
    sub = all_fires[all_fires["direction"] == d]
    print(f"  {d}: n={len(sub)} WR={sub['won'].mean():.4f} $/tr={sub['pnl_legacy'].mean():.3f} total={sub['pnl_legacy'].sum():.2f}")

OUT = ROOT / "strategy_lab/_sleeve_reaudit_2026_06_03"
OUT.mkdir(parents=True, exist_ok=True)
all_fires.to_parquet(OUT / "momo_f7_bt_trades.parquet", index=False)
print(f"\n  Saved: {OUT / 'momo_f7_bt_trades.parquet'}")

print("\nDONE MOMO_F7 backtest.")
