"""
SLEEVE 1 REAUDIT: poly_sniper_v5_btc_15m_ema50_ema800_off600_down
Fresh backtest Apr24 -> Jun1 09:00 UTC on canonical data.

Gate logic (faithful to VPS3 live):
  - direction = DOWN
  - fire_us = slot_start_us + 600s  (offset_s=600)
  - g_tr_above_ema50: binance-1s close < ema_50 at (fire_us - 1s) for DOWN
    -> available in sniper_btc15m_v8_gated.parquet as g_tr_above_ema50
  - g_tr_above_ema800: same for ema_800 -> g_tr_above_ema800

CRITICAL: sniper_v8_gated only covers Apr24-May26. For May26-Jun1 we must
rebuild from resolutions only (no L25 there — canonical L25 max Jun1 09:07).
Strategy: use sniper_v8_gated for Apr24-May26 (has fills + gates pre-computed),
then for May26-Jun1 slots: load resolutions + ema gates from klines_asof
(approximate: use tr_above_ema50/800 from EMA computed on 1MIN bars at fire_us).

HONEST SCOPE: sniper_v8_gated covers Apr24 01:45 to May26 16:55.
Canonical resolutions cover Apr24 01:45 to Jun1 08:45.
Delta = May26 16:55 -> Jun1 08:45 = ~5 days.

For the delta, we need L25 fills. L25 canonical max = Jun1 09:07.
So full coverage is possible.

Fee model: LegacyConfig (2%-on-profit), also report 0.07-curve.
Fill: engine_v2.fill_at_book, L25 subsample_1hz=False, spread_filter=0.02.
"""
from __future__ import annotations
import sys, math, json, gc
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import (
    load_resolutions, load_klines_asof, load_orderbook_l25_streaming,
    load_klines_1s,
)
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl

NOTIONAL = 5.0
SPREAD_FILTER = 0.02
CFG = LegacyConfig()

# ── 1. Load gated substrate (Apr24-May26) ────────────────────────────────────
print("[1] Loading sniper_btc15m_v8_gated …")
v8 = pd.read_parquet(ROOT / "data/v4/canonical/_results/sniper_btc15m_v8_gated.parquet")

# Apply gate filter for this sleeve
mask = (
    (v8["direction"] == "DOWN") &
    v8["g_tr_above_ema50"].fillna(False).astype(bool) &
    v8["g_tr_above_ema800"].fillna(False).astype(bool) &
    (v8["fire_offset_s"] == 600)
)
f_v8 = v8[mask].copy()
print(f"   v8 gated fires: {len(f_v8)} (Apr24-May26)")

# ── 2. Load resolutions for extension window (May26-Jun1) ────────────────────
print("[2] Loading resolutions …")
res = load_resolutions(assets=["BTC"], timeframes=["15m"])
# Extension: slots after v8 max date
V8_MAX_SLOT_US = int(v8["slot_start_us"].max())
JUN1_MAX_US = int(pd.Timestamp("2026-06-01 09:00:00", tz="UTC").value // 1000)

res_ext = res[
    (res["slot_start_us"] > V8_MAX_SLOT_US) &
    (res["slot_start_us"] <= JUN1_MAX_US)
].copy()
EXT_MIN_US = V8_MAX_SLOT_US
print(f"   Extension slots: {len(res_ext)} (May26-Jun1)")

# ── 3. Load klines for EMA gate computation (extension window) ───────────────
print("[3] Loading 1MIN klines for EMA gate reconstruction …")
eu_1m, cl_1m = load_klines_asof("BTC", source="binance-spot-ws", period_id="1MIN")
eu_1m = eu_1m.astype("int64")
cl_1m = cl_1m.astype("float64")

def asof_close_1m(target_us: int) -> float:
    i = int(np.searchsorted(eu_1m, target_us, side="right")) - 1
    return float("nan") if i < 0 else float(cl_1m[i])

def compute_ema(closes: np.ndarray, span: int) -> float:
    """Simple EMA (Wilder-style for EMA not RSI, standard pandas-compatible)."""
    if len(closes) < span:
        return float("nan")
    alpha = 2.0 / (span + 1)
    ema = float(closes[0])
    for c in closes[1:]:
        ema = alpha * c + (1 - alpha) * ema
    return ema

def get_ema_gate(fire_us: int, span: int, direction: str) -> bool:
    """Compute EMA(span) on 1MIN bars ending just before fire_us.
    Returns True if gate passes (close < EMA for DOWN)."""
    # Need ~span+50 bars for warmup
    lookback = (span + 100) * 60 * 1_000_000
    start_us = fire_us - lookback
    # find bars in window
    i0 = int(np.searchsorted(eu_1m, start_us, side="left"))
    i1 = int(np.searchsorted(eu_1m, fire_us - 1_000_000, side="right"))
    if i1 <= i0 or (i1 - i0) < span:
        return False
    closes = cl_1m[i0:i1]
    ema_val = compute_ema(closes, span)
    close_now = float(closes[-1])
    if math.isnan(ema_val) or math.isnan(close_now):
        return False
    if direction == "DOWN":
        return close_now < ema_val
    else:
        return close_now > ema_val

# Apply EMA gates to extension slots
print("[4] Computing EMA gates for extension slots …")
ext_rows = []
for _, row in res_ext.iterrows():
    fire_us = int(row["slot_start_us"]) + 600 * 1_000_000
    g50 = get_ema_gate(fire_us, 50, "DOWN")
    g800 = get_ema_gate(fire_us, 800, "DOWN")
    if g50 and g800:
        ext_rows.append({
            "slug": row["slug"],
            "slot_start_us": int(row["slot_start_us"]),
            "fire_us": fire_us,
            "direction": "DOWN",
            "outcome": row["outcome"],
            "won": (row["outcome"] == "Down"),
            "entry_vwap": None,  # will be filled by book
            "source": "extension",
        })

f_ext_pre = pd.DataFrame(ext_rows)
print(f"   Extension fires after gates: {len(f_ext_pre)}")

# ── 5. Load L25 for extension window fills ───────────────────────────────────
print("[5] Loading L25 books for extension window …")
ext_slugs = set(f_ext_pre["slug"].tolist()) if len(f_ext_pre) > 0 else set()

if ext_slugs:
    books_ext = load_orderbook_l25_streaming(
        "btc",
        slugs=ext_slugs,
        subsample_1hz=False,
        min_ts_us=EXT_MIN_US,
        max_ts_us=JUN1_MAX_US + 900 * 1_000_000,
    )
    print(f"   L25 books loaded for {len(ext_slugs)} ext slugs")
else:
    books_ext = {}
    print("   No ext slugs")

# ── 6. Fill extension fires ──────────────────────────────────────────────────
print("[6] Filling extension fires …")
ext_filled = []
for _, row in f_ext_pre.iterrows():
    fill = fill_at_book(books_ext, row["slug"], "Down", int(row["fire_us"]),
                        cfg=CFG, spread_filter=SPREAD_FILTER)
    if fill is None:
        continue
    won = row["won"]
    pnl_legacy = hold_pnl(fill, won=won, cfg=CFG)
    # Also compute 0.07 curve
    shares = NOTIONAL / fill["vwap"]
    if won:
        pnl_07 = shares * (1 - fill["vwap"]) * (1 - 0.07 * fill["vwap"])
    else:
        pnl_07 = -shares * fill["vwap"]
    ext_filled.append({
        "slug": row["slug"],
        "fire_us": row["fire_us"],
        "direction": "DOWN",
        "outcome": row["outcome"],
        "won": won,
        "entry_vwap": fill["vwap"],
        "pnl_legacy": pnl_legacy,
        "pnl_07": pnl_07,
        "source": "extension",
    })
del books_ext; gc.collect()
print(f"   Extension filled: {len(ext_filled)}")

# ── 7. Process v8 fires (already have fills from substrate) ─────────────────
print("[7] Building v8 fire records …")
v8_rows = []
for _, row in f_v8.iterrows():
    won = bool(row["won"])
    entry = float(row["entry_vwap"])
    if math.isnan(entry) or entry <= 0:
        continue
    shares = NOTIONAL / entry
    pnl_legacy = float(row["pnl_legacy_usd"])
    if won:
        pnl_07 = shares * (1 - entry) * (1 - 0.07 * entry)
    else:
        pnl_07 = -shares * entry
    v8_rows.append({
        "slug": row["slug"],
        "fire_us": int(row["fire_us"]),
        "direction": "DOWN",
        "outcome": row["outcome"],
        "won": won,
        "entry_vwap": entry,
        "pnl_legacy": pnl_legacy,
        "pnl_07": pnl_07,
        "source": "v8_gated",
    })

f_v8_df = pd.DataFrame(v8_rows)
f_ext_df = pd.DataFrame(ext_filled) if ext_filled else pd.DataFrame(columns=f_v8_df.columns)

# ── 8. Combine and analyze ───────────────────────────────────────────────────
all_fires = pd.concat([f_v8_df, f_ext_df], ignore_index=True)
all_fires["dt"] = pd.to_datetime(all_fires["fire_us"], unit="us", utc=True)
all_fires["week"] = all_fires["dt"].dt.isocalendar().week.astype(int)
all_fires["year"] = all_fires["dt"].dt.isocalendar().year.astype(int)
all_fires["yw"] = all_fires["year"].astype(str) + "-W" + all_fires["week"].astype(str).str.zfill(2)

print("\n" + "="*70)
print("SLEEVE 1: poly_sniper_v5_btc_15m_ema50_ema800_off600_down")
print("BACKTEST Apr24 -> Jun1 09:00 UTC")
print("="*70)

n = len(all_fires)
wr = all_fires["won"].mean()
pnl_legacy = all_fires["pnl_legacy"].sum()
pnl_07 = all_fires["pnl_07"].sum()
pnl_legacy_mean = all_fires["pnl_legacy"].mean()
pnl_07_mean = all_fires["pnl_07"].mean()

print(f"\n  n={n}  WR={wr:.4f} ({100*wr:.1f}%)  $/tr(legacy)={pnl_legacy_mean:.3f}  total(legacy)={pnl_legacy:.2f}")
print(f"  $/tr(0.07)={pnl_07_mean:.3f}  total(0.07)={pnl_07:.2f}")

# Binom test
from scipy import stats
binom_p = stats.binomtest(int(all_fires["won"].sum()), n, 0.5, alternative="greater").pvalue if n > 0 else 1.0
print(f"  binom_p(WR>50%)={binom_p:.6f}")

# Bootstrap 95% CI on $/tr
rng = np.random.default_rng(42)
bt_means = [rng.choice(all_fires["pnl_legacy"].values, size=n, replace=True).mean() for _ in range(5000)]
ci_lo, ci_hi = np.percentile(bt_means, [2.5, 97.5])
print(f"  bootstrap 95% CI $/tr: [{ci_lo:.3f}, {ci_hi:.3f}]")

# Max drawdown
cum = all_fires["pnl_legacy"].cumsum()
running_max = cum.cummax()
dd = (cum - running_max)
max_dd = dd.min()
print(f"  max_drawdown(legacy)={max_dd:.2f}")

# By week
print("\n  --- By week ---")
wk = all_fires.groupby("yw").agg(
    n=("won", "size"),
    wr=("won", lambda x: round(x.mean(), 4)),
    pnl_legacy=("pnl_legacy", lambda x: round(x.sum(), 2)),
    pnl_07=("pnl_07", lambda x: round(x.sum(), 2)),
).reset_index()
print(wk.to_string(index=False))

# OOS split (train first 60%, test last 40%)
split_idx = int(n * 0.6)
train = all_fires.iloc[:split_idx]
test = all_fires.iloc[split_idx:]
print(f"\n  --- OOS split (60/40) ---")
print(f"  TRAIN n={len(train)} WR={train['won'].mean():.4f} $/tr={train['pnl_legacy'].mean():.3f} total={train['pnl_legacy'].sum():.2f}")
print(f"  TEST  n={len(test)}  WR={test['won'].mean():.4f} $/tr={test['pnl_legacy'].mean():.3f} total={test['pnl_legacy'].sum():.2f}")

# Entry-vwap band [0.15, 0.93] analysis
banded = all_fires[(all_fires["entry_vwap"] >= 0.15) & (all_fires["entry_vwap"] < 0.93)]
unbanded = all_fires
print(f"\n  --- Entry-vwap band [0.15, 0.93] vs unbanded ---")
print(f"  UNBANDED: n={len(unbanded)} WR={unbanded['won'].mean():.4f} $/tr={unbanded['pnl_legacy'].mean():.3f} total={unbanded['pnl_legacy'].sum():.2f}")
print(f"  BANDED:   n={len(banded)}  WR={banded['won'].mean():.4f} $/tr={banded['pnl_legacy'].mean():.3f} total={banded['pnl_legacy'].sum():.2f}")

# Entry distribution
print(f"\n  entry_vwap dist: {all_fires['entry_vwap'].describe(percentiles=[.1,.25,.5,.75,.9]).round(3).to_dict()}")

# Save per-trade
OUT = ROOT / "strategy_lab/_sleeve_reaudit_2026_06_03"
OUT.mkdir(parents=True, exist_ok=True)
all_fires.to_parquet(OUT / "ema_down_bt_trades.parquet", index=False)
print(f"\n  Saved: {OUT / 'ema_down_bt_trades.parquet'}")

print("\nDONE EMA_DOWN backtest.")
