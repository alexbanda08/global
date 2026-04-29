# V2 Signals Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 3 calibrated probability signals (`prob_a`, `prob_b`, `prob_c`) and a logistic-regression stack (`prob_stack`) to the existing `features_v3.csv` pipeline, then run them through the existing strategy_lab engines to identify which (if any) survives the same forward-walk + live-reconciliation gates as `sig_ret5m`.

**Architecture:** Approach 2 from the design doc. Three new builder scripts under `strategy_lab/v2_signals/` add columns to `features_v3.csv`. A 4th script fits a logistic-regression meta-model on the train slice and adds `prob_stack`. Existing engines (`signal_grid_v2.py`, `forward_walk_v2.py`) gain 4 entries to their signal list and consume the new columns automatically. Backtests output to `results/polymarket/v2_signals_*.csv` and `reports/POLYMARKET_V2_SIGNALS_FINDINGS.md`.

**Tech Stack:** Python 3.12, pandas, numpy, scipy.stats, scikit-learn (LogisticRegression + CalibratedClassifierCV), psql via ssh to VPS2 for trades_v2 extract. No new dependencies beyond sklearn (likely already installed; pin in requirements if not).

**Reference:** `docs/plans/2026-04-29-v2-signals-design.md`

---

## Pre-flight

Confirm the existing pipeline is healthy on freshly-refreshed data before adding anything.

### Task 0: Verify pre-state

**Files (read-only):**
- `strategy_lab/data/polymarket/btc_features_v3.csv`
- `strategy_lab/data/polymarket/btc_markets_v3.csv`
- `strategy_lab/results/polymarket/signal_grid_v2.csv`

**Step 1: Inspect inputs.**

```bash
cd "C:/Users/alexandre bandarra/Desktop/global/strategy_lab"
python -c "
import pandas as pd
for a in ['btc','eth','sol']:
    f = pd.read_csv(f'data/polymarket/{a}_features_v3.csv')
    m = pd.read_csv(f'data/polymarket/{a}_markets_v3.csv')
    print(f'{a}: features {f.shape} markets {m.shape}')
    print('  features cols:', list(f.columns))
"
```

Expected: 3 assets, ~2,700 rows each, columns include `asset, slug, timeframe, window_start_unix, outcome_up, ret_5m, ret_15m, ret_1h, btc_close_at_ws, strike_price, settlement_price, entry_yes_ask, entry_no_ask`.

**Step 2: No commit — verification only. Move on if shapes match design assumptions.**

---

## Task 1: Bootstrap v2_signals package

**Files:**
- Create: `strategy_lab/v2_signals/__init__.py`
- Create: `strategy_lab/v2_signals/common.py`
- Create: `strategy_lab/v2_signals/test_common.py`

**Step 1: Write the failing test.**

`strategy_lab/v2_signals/test_common.py`:
```python
import pandas as pd
import pytest
from strategy_lab.v2_signals.common import load_features, save_features, ASSETS

def test_load_features_returns_dataframe(tmp_path, monkeypatch):
    # Arrange: write a fake features CSV
    p = tmp_path / "data" / "polymarket"
    p.mkdir(parents=True)
    df = pd.DataFrame({"asset": ["btc"], "slug": ["s"], "outcome_up": [1]})
    df.to_csv(p / "btc_features_v3.csv", index=False)
    monkeypatch.setattr("strategy_lab.v2_signals.common.DATA_DIR", p.parent)

    out = load_features("btc")
    assert isinstance(out, pd.DataFrame)
    assert "asset" in out.columns

def test_assets_constant():
    assert ASSETS == ("btc", "eth", "sol")
```

**Step 2: Run to confirm failure.**

```bash
pytest strategy_lab/v2_signals/test_common.py -v
```

Expected: ImportError on `strategy_lab.v2_signals.common`.

**Step 3: Implement minimal `common.py`.**

`strategy_lab/v2_signals/common.py`:
```python
"""Shared utilities for v2_signals builders."""
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
DATA_DIR = HERE / "data"
ASSETS = ("btc", "eth", "sol")
TIMEFRAMES = ("5m", "15m")


def load_features(asset: str) -> pd.DataFrame:
    p = DATA_DIR / "polymarket" / f"{asset}_features_v3.csv"
    return pd.read_csv(p)


def save_features(asset: str, df: pd.DataFrame) -> None:
    p = DATA_DIR / "polymarket" / f"{asset}_features_v3.csv"
    df.to_csv(p, index=False)
```

`strategy_lab/v2_signals/__init__.py`: empty file.

**Step 4: Run tests to confirm pass.**

```bash
pytest strategy_lab/v2_signals/test_common.py -v
```

Expected: 2 passed.

**Step 5: Commit.**

```bash
git add strategy_lab/v2_signals/__init__.py strategy_lab/v2_signals/common.py strategy_lab/v2_signals/test_common.py
git commit -m "feat(v2_signals): bootstrap package with common loader"
```

---

## Task 2: Signal A — multi-horizon momentum agreement

**Files:**
- Create: `strategy_lab/v2_signals/build_signal_a.py`
- Create: `strategy_lab/v2_signals/test_build_signal_a.py`

**Step 1: Write the failing test.**

`strategy_lab/v2_signals/test_build_signal_a.py`:
```python
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.build_signal_a import compute_votes_up, calibrate_prob_a

def test_compute_votes_up_all_positive():
    df = pd.DataFrame({"ret_5m":[0.01], "ret_15m":[0.02], "ret_1h":[0.005]})
    assert compute_votes_up(df).iloc[0] == 3

def test_compute_votes_up_mixed():
    df = pd.DataFrame({"ret_5m":[0.01], "ret_15m":[-0.02], "ret_1h":[0.005]})
    assert compute_votes_up(df).iloc[0] == 2

def test_compute_votes_up_handles_zero_as_negative():
    # zero is treated as not > 0 (i.e. a "down" vote)
    df = pd.DataFrame({"ret_5m":[0.0], "ret_15m":[0.0], "ret_1h":[0.0]})
    assert compute_votes_up(df).iloc[0] == 0

def test_calibrate_prob_a_uses_train_buckets():
    # Build a 100-row train where votes=3 → 80% up, votes=0 → 20% up
    n = 100
    train = pd.DataFrame({
        "asset": ["btc"]*n,
        "timeframe": ["5m"]*n,
        "votes_up": [3]*50 + [0]*50,
        "outcome_up": [1]*40 + [0]*10 + [1]*10 + [0]*40,
    })
    full = train.copy()
    out = calibrate_prob_a(full, train)
    assert out.loc[0, "prob_a"] == 0.8
    assert out.loc[60, "prob_a"] == 0.2

def test_calibrate_prob_a_falls_back_when_thin_bucket():
    train = pd.DataFrame({
        "asset": ["btc"]*5,  # only 5 train rows in bucket
        "timeframe": ["5m"]*5,
        "votes_up": [3]*5,
        "outcome_up": [1]*5,
    })
    full = train.copy()
    out = calibrate_prob_a(full, train, min_samples=20)
    # Bucket too thin → fall back to 0.5
    assert out.loc[0, "prob_a"] == 0.5
```

**Step 2: Run to confirm fail.**

```bash
pytest strategy_lab/v2_signals/test_build_signal_a.py -v
```

Expected: ImportError on `build_signal_a`.

**Step 3: Implement `build_signal_a.py`.**

```python
"""Signal A — multi-horizon momentum agreement.

prob_a = empirical P(outcome_up=1 | votes_up bucket, asset, tf) on train slice.
"""
from __future__ import annotations
import argparse
import os
import pandas as pd
import numpy as np
from strategy_lab.v2_signals.common import load_features, save_features, ASSETS, TIMEFRAMES

TRAIN_FRAC = 0.8


def compute_votes_up(df: pd.DataFrame) -> pd.Series:
    return ((df.ret_5m > 0).astype(int)
            + (df.ret_15m > 0).astype(int)
            + (df.ret_1h > 0).astype(int))


def calibrate_prob_a(full: pd.DataFrame, train: pd.DataFrame, min_samples: int = 20) -> pd.DataFrame:
    """Return full with a 'prob_a' column, fitted on train."""
    keys = ["asset", "timeframe", "votes_up"]
    bucket_stats = (train.groupby(keys)["outcome_up"]
                         .agg(["mean", "count"])
                         .reset_index()
                         .rename(columns={"mean": "p_up_bucket", "count": "n_bucket"}))
    out = full.merge(bucket_stats, on=keys, how="left")
    fallback = (out["n_bucket"].isna()) | (out["n_bucket"] < min_samples)
    out["prob_a"] = np.where(fallback, 0.5, out["p_up_bucket"])
    return out.drop(columns=["p_up_bucket", "n_bucket"])


def chronological_split(df: pd.DataFrame, train_frac: float = TRAIN_FRAC) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("window_start_unix").reset_index(drop=True)
    cut = int(len(df) * train_frac)
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def build_one_asset(asset: str) -> None:
    df = load_features(asset)
    df["votes_up"] = compute_votes_up(df)
    train, _ = chronological_split(df)
    df = calibrate_prob_a(df, train)
    save_features(asset, df)
    print(f"{asset}: prob_a written, mean={df['prob_a'].mean():.3f}, "
          f"std={df['prob_a'].std():.3f}, "
          f"buckets={df.groupby('votes_up')['prob_a'].mean().to_dict()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default=os.getenv("ASSET", "all"))
    args = ap.parse_args()
    assets = ASSETS if args.asset == "all" else (args.asset,)
    for a in assets:
        build_one_asset(a)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to confirm pass.**

```bash
pytest strategy_lab/v2_signals/test_build_signal_a.py -v
```

Expected: 5 passed.

**Step 5: Run on real data.**

```bash
cd "C:/Users/alexandre bandarra/Desktop/global"
python -m strategy_lab.v2_signals.build_signal_a
```

Expected printout: 3 lines, one per asset, mean prob_a near 0.5, buckets showing monotone progression (votes=0 → ~0.4, votes=3 → ~0.6 ish).

**Step 6: Verify column exists in features_v3.**

```bash
python -c "
import pandas as pd
df = pd.read_csv('strategy_lab/data/polymarket/btc_features_v3.csv')
assert 'prob_a' in df.columns
print('prob_a coverage:', df.prob_a.notna().mean())
print('prob_a distribution:')
print(df.prob_a.describe())
"
```

Expected: coverage ≥ 99%, prob_a distribution centered ~0.5.

**Step 7: Commit.**

```bash
git add strategy_lab/v2_signals/build_signal_a.py strategy_lab/v2_signals/test_build_signal_a.py
git add strategy_lab/data/polymarket/btc_features_v3.csv strategy_lab/data/polymarket/eth_features_v3.csv strategy_lab/data/polymarket/sol_features_v3.csv
git commit -m "feat(v2_signals): add prob_a (multi-horizon momentum agreement)"
```

---

## Task 3: Signal B — vol-arb / digital fair value

**Files:**
- Create: `strategy_lab/v2_signals/build_signal_b.py`
- Create: `strategy_lab/v2_signals/test_build_signal_b.py`

**Step 1: Write failing tests.**

`strategy_lab/v2_signals/test_build_signal_b.py`:
```python
import math
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.build_signal_b import (
    realized_vol_daily, digital_fair_yes, isotonic_calibrate
)

def test_realized_vol_daily_simple():
    # 1440 minutes of constant-return process → vol ≈ 0
    closes = pd.Series([100.0] * 1440)
    sig = realized_vol_daily(closes)
    assert sig < 1e-9

def test_realized_vol_daily_known():
    # 1m return 0.001 every minute → daily vol = 0.001 * sqrt(1440)
    closes = pd.Series([100.0 * (1.001 ** i) for i in range(1440)])
    sig = realized_vol_daily(closes)
    expected = 0.001 * math.sqrt(1440)
    assert abs(sig - expected) < 1e-3

def test_digital_fair_yes_at_strike_returns_half():
    # S = S0 → P(S_T > S0) = 0.5 (no drift)
    out = digital_fair_yes(s=100.0, s0=100.0, sigma_daily=0.02, t_seconds=300)
    assert abs(out - 0.5) < 1e-6

def test_digital_fair_yes_above_strike_returns_above_half():
    out = digital_fair_yes(s=101.0, s0=100.0, sigma_daily=0.02, t_seconds=300)
    assert out > 0.5

def test_digital_fair_yes_clipped():
    # huge S vs S0 → ~1.0 but never exactly
    out = digital_fair_yes(s=200.0, s0=100.0, sigma_daily=0.02, t_seconds=300)
    assert 0.99 < out < 1.0

def test_isotonic_calibrate_monotone():
    # raw probs 0..1 with noisy outcomes — calibration preserves order
    raw = np.linspace(0.1, 0.9, 50)
    y = (raw + np.random.RandomState(0).normal(0, 0.05, 50) > 0.5).astype(int)
    cal = isotonic_calibrate(raw, y, raw_to_calibrate=raw)
    # Calibrated values should be monotonic in raw input
    diffs = np.diff(cal)
    assert (diffs >= -1e-9).all()
```

**Step 2: Run to confirm fail.**

```bash
pytest strategy_lab/v2_signals/test_build_signal_b.py -v
```

**Step 3: Implement `build_signal_b.py`.**

```python
"""Signal B — vol-arb / digital fair value.

prob_b = norm.cdf(d) where d = (ln(S/S0) + 0.5*σ²T) / (σ*√T),
S = current binance close at window_start, S0 = strike_price,
σ = realized daily vol from the last 1440 minutes of 1m closes.
Then isotonic-calibrate against actual outcomes on the train slice.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.isotonic import IsotonicRegression
from strategy_lab.v2_signals.common import load_features, save_features, ASSETS, DATA_DIR
from strategy_lab.v2_signals.build_signal_a import chronological_split

TIMEFRAME_SECONDS = {"5m": 300, "15m": 900}


def realized_vol_daily(closes_1m: pd.Series) -> float:
    """Daily realized vol from 1m closes via log-return std × sqrt(1440)."""
    rets = np.log(closes_1m.astype(float)).diff().dropna()
    return float(rets.std() * np.sqrt(1440))


def digital_fair_yes(s: float, s0: float, sigma_daily: float, t_seconds: float) -> float:
    """Black-style digital cash-or-nothing call price (no drift, no rate)."""
    if sigma_daily <= 0 or t_seconds <= 0:
        return 1.0 if s > s0 else (0.0 if s < s0 else 0.5)
    sigma_t = sigma_daily * np.sqrt(t_seconds / 86400)
    d = (np.log(s / s0) + 0.5 * sigma_t**2) / sigma_t
    p = float(norm.cdf(d))
    return min(max(p, 1e-4), 1.0 - 1e-4)


def isotonic_calibrate(raw_train, y_train, raw_to_calibrate) -> np.ndarray:
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(raw_train, y_train)
    return iso.transform(raw_to_calibrate)


def load_klines_1m(asset: str) -> pd.DataFrame:
    p = DATA_DIR / "binance" / f"{asset}_klines_window.csv"
    k = pd.read_csv(p)
    k = k[k.period_id == "1MIN"].copy()
    k["ts_s"] = (k.time_period_start_us // 1_000_000).astype(int)
    return k.sort_values("ts_s").reset_index(drop=True)[["ts_s", "price_close"]]


def compute_raw_prob_b(features: pd.DataFrame, klines: pd.DataFrame) -> pd.Series:
    """For each market, compute fair-yes at window_start_unix using last-1440-min vol."""
    closes = klines.set_index("ts_s")["price_close"].astype(float)
    raw = np.full(len(features), np.nan, dtype=float)
    closes_idx = closes.index.values
    closes_vals = closes.values

    for i, row in features.reset_index(drop=True).iterrows():
        ws = int(row["window_start_unix"])
        # σ from window_start - 24h .. window_start
        lo = ws - 86400
        # use searchsorted on numpy for speed
        l = np.searchsorted(closes_idx, lo)
        r = np.searchsorted(closes_idx, ws)
        if r - l < 60:  # need at least 60 minutes
            continue
        sigma = float(np.std(np.diff(np.log(closes_vals[l:r])))) * np.sqrt(1440)
        # spot S = the close AT window_start (last bar at or before ws)
        s = float(closes_vals[r - 1])
        s0 = float(row["strike_price"])
        if not (np.isfinite(s) and np.isfinite(s0) and s0 > 0 and sigma > 0):
            continue
        t_sec = TIMEFRAME_SECONDS.get(row["timeframe"], 300)
        raw[i] = digital_fair_yes(s, s0, sigma, t_sec)

    return pd.Series(raw, name="prob_b_raw")


def build_one_asset(asset: str) -> None:
    df = load_features(asset)
    klines = load_klines_1m(asset)
    df["prob_b_raw"] = compute_raw_prob_b(df, klines).values
    train, _ = chronological_split(df.dropna(subset=["prob_b_raw"]))
    df["prob_b"] = 0.5  # default
    mask = df["prob_b_raw"].notna()
    df.loc[mask, "prob_b"] = isotonic_calibrate(
        train["prob_b_raw"].values, train["outcome_up"].values,
        df.loc[mask, "prob_b_raw"].values
    )
    df = df.drop(columns=["prob_b_raw"])
    save_features(asset, df)
    print(f"{asset}: prob_b written, n_valid={mask.sum()}/{len(df)}, "
          f"mean={df.loc[mask,'prob_b'].mean():.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default=os.getenv("ASSET", "all"))
    args = ap.parse_args()
    assets = ASSETS if args.asset == "all" else (args.asset,)
    for a in assets:
        build_one_asset(a)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to pass.**

```bash
pytest strategy_lab/v2_signals/test_build_signal_b.py -v
```

Expected: 6 passed.

**Step 5: Run on real data.**

```bash
python -m strategy_lab.v2_signals.build_signal_b
```

Expected: 3 lines, n_valid ≥ 95%, mean prob_b near 0.5.

**Step 6: Verify in CSV.**

```bash
python -c "
import pandas as pd
df = pd.read_csv('strategy_lab/data/polymarket/btc_features_v3.csv')
print('prob_b stats:', df.prob_b.describe())
print('correlation prob_a/prob_b:', df[['prob_a','prob_b']].corr().iloc[0,1])
"
```

Expected: prob_b std > 0.05 (i.e. it's not collapsed to 0.5). Corr(prob_a, prob_b) probably moderate (0.3-0.6) — the signals share information.

**Step 7: Commit.**

```bash
git add strategy_lab/v2_signals/build_signal_b.py strategy_lab/v2_signals/test_build_signal_b.py strategy_lab/data/polymarket/*.csv
git commit -m "feat(v2_signals): add prob_b (vol-arb digital fair value)"
```

---

## Task 4: Extract Polymarket trade-flow per market

**Background:** Signal C needs the 60s pre-resolution trade tape per market. We don't have it locally yet — need to extract from VPS2's `trades_v2` (8M rows). Must be window-aware: only trades in `[slot_start_us - 60_000_000, slot_start_us]` per market.

**Files:**
- Create: `strategy_lab/polymarket_extract_flow.sql`
- Modify: VPS2 (run extractor)
- Create: `strategy_lab/data/polymarket/{btc,eth,sol}_flow_v3.csv` (download)

**Step 1: Write the SQL extractor.**

`strategy_lab/polymarket_extract_flow.sql`:
```sql
-- Per-market 60s pre-window trade aggregates from trades_v2.
-- Asset-template: replace 'btc-updown-%' with eth/sol via psql -v ASSET_PREFIX=
-- Emits: slug, asset_id (yes/no), buy_volume, sell_volume, n_trades

\set ASSET_PREFIX 'btc-updown-%'

DROP TABLE IF EXISTS tmp_flow;
CREATE TEMP TABLE tmp_flow AS
WITH resolved AS (
  SELECT slug, slot_start_us
  FROM market_resolutions_v2
  WHERE slug LIKE :'ASSET_PREFIX'
    AND outcome IS NOT NULL
)
SELECT
  r.slug,
  t.asset_id,
  t.taker_side,
  COUNT(*)              AS n_trades,
  SUM(t.size)           AS total_size
FROM resolved r
JOIN trades_v2 t
  ON t.market_id IN (SELECT market_id FROM markets WHERE slug = r.slug)
 AND t.timestamp_us BETWEEN r.slot_start_us - 60000000 AND r.slot_start_us
GROUP BY 1, 2, 3;

\copy tmp_flow TO '/tmp/extract/flow_v3.csv' WITH CSV HEADER;
\echo Exported flow_v3.
```

(Adjust `t.asset_id`/`t.taker_side` column names if different — verify schema first.)

**Step 2: Run on VPS2 for all 3 assets.**

```bash
ssh -i ~/.ssh/vps2_ed25519 root@'[2605:a140:2323:6975::1]' 'bash -s' <<'REMOTE'
mkdir -p /tmp/extract && chmod 777 /tmp/extract
sudo -u postgres psql -d storedata -c "\d trades_v2" | head -25
REMOTE
```

Inspect schema first. Expected columns include `market_id, timestamp_us, asset_id, side, price, size`.

If schema matches, run extractor per asset (sed-template like markets_v3 was done). Push extractor:

```bash
scp -i ~/.ssh/vps2_ed25519 strategy_lab/polymarket_extract_flow.sql root@'[2605:a140:2323:6975::1]':/tmp/

ssh -i ~/.ssh/vps2_ed25519 root@'[2605:a140:2323:6975::1]' 'bash -s' <<'REMOTE'
mkdir -p /tmp/extract && chmod 777 /tmp/extract
for asset in btc eth sol; do
  cp /tmp/polymarket_extract_flow.sql /tmp/extract/flow_${asset}.sql
  sed -i "s/btc-updown/${asset}-updown/g; s|/tmp/extract/flow_v3.csv|/tmp/extract/${asset}_flow_v3.csv|g" /tmp/extract/flow_${asset}.sql
  sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -q -f /tmp/extract/flow_${asset}.sql 2>&1 | tail -3
done
ls -lh /tmp/extract/*flow_v3.csv
REMOTE
```

**Step 3: Pull to local.**

```bash
for a in btc eth sol; do
  scp -i ~/.ssh/vps2_ed25519 \
    "root@[2605:a140:2323:6975::1]:/tmp/extract/${a}_flow_v3.csv" \
    "strategy_lab/data/polymarket/${a}_flow_v3.csv"
done
wc -l strategy_lab/data/polymarket/*_flow_v3.csv
```

Expected: ≥1 row per market on average (8,200 markets total).

**Step 4: Commit data + sql.**

```bash
git add strategy_lab/polymarket_extract_flow.sql strategy_lab/data/polymarket/*_flow_v3.csv
git commit -m "data(v2_signals): extract per-market 60s pre-window trade flow"
```

---

## Task 5: Signal C — Polymarket microstructure flow

**Files:**
- Create: `strategy_lab/v2_signals/build_signal_c.py`
- Create: `strategy_lab/v2_signals/test_build_signal_c.py`

**Step 1: Write failing tests.**

`strategy_lab/v2_signals/test_build_signal_c.py`:
```python
import pandas as pd
import numpy as np
from strategy_lab.v2_signals.build_signal_c import (
    flow_signal_per_market, book_imbalance_top5, combine_to_prob_c
)

def test_flow_signal_pure_yes_buy():
    # YES side has 100 buy, 0 sell. NO side empty. flow ≈ +1.
    df = pd.DataFrame({
        "slug": ["s","s"],
        "outcome": ["Up","Up"],
        "taker_side": ["buy","sell"],
        "total_size": [100, 0],
    })
    f = flow_signal_per_market(df)
    assert abs(f.loc["s"] - 1.0) < 1e-6

def test_flow_signal_balanced():
    df = pd.DataFrame({
        "slug": ["s"]*4,
        "outcome": ["Up","Up","Down","Down"],
        "taker_side": ["buy","sell","buy","sell"],
        "total_size": [50, 50, 50, 50],
    })
    assert abs(flow_signal_per_market(df).loc["s"]) < 1e-6

def test_book_imbalance_yes_thicker():
    # NO side has 1000 ask, YES has 100 → imbalance = (1000-100)/1100 ≈ +0.82 (positive = bullish UP)
    bd = pd.DataFrame({
        "slug":["s"]*2,
        "outcome":["Up","Down"],
        "ask_size_0":[100, 1000],
        "ask_size_1":[0,0],"ask_size_2":[0,0],"ask_size_3":[0,0],"ask_size_4":[0,0],
    })
    out = book_imbalance_top5(bd)
    assert abs(out.loc["s"] - (900/1100)) < 1e-3

def test_combine_squashes_to_band():
    raw_c = 0.6 * pd.Series([1.0, -1.0, 0.0]) + 0.4 * pd.Series([1.0, -1.0, 0.0])
    p = combine_to_prob_c(raw_c)
    assert abs(p.iloc[0] - 0.9) < 1e-6
    assert abs(p.iloc[1] - 0.1) < 1e-6
    assert abs(p.iloc[2] - 0.5) < 1e-6
```

**Step 2: Run to fail.**

```bash
pytest strategy_lab/v2_signals/test_build_signal_c.py -v
```

**Step 3: Implement.**

```python
"""Signal C — Polymarket microstructure flow.

Combines (a) 60s pre-window trade-tape pressure and (b) top-5 book ask-size
imbalance, squashed to a probability in [0.1, 0.9], then isotonic-calibrated
on the train slice.
"""
from __future__ import annotations
import argparse, os
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from strategy_lab.v2_signals.common import load_features, save_features, ASSETS, DATA_DIR
from strategy_lab.v2_signals.build_signal_a import chronological_split


def flow_signal_per_market(flow_df: pd.DataFrame) -> pd.Series:
    """Per slug: ((yes_buy - yes_sell) - (no_buy - no_sell)) / total_volume."""
    pivoted = (flow_df.assign(signed=lambda d: np.where(d.taker_side=='buy',
                                                        d.total_size, -d.total_size))
                       .groupby(["slug", "outcome"])["signed"].sum().unstack(fill_value=0))
    yes = pivoted.get("Up", 0)
    no  = pivoted.get("Down", 0)
    total_vol = (flow_df.groupby("slug")["total_size"].sum()).replace(0, np.nan)
    return ((yes - no) / total_vol).fillna(0)


def book_imbalance_top5(book: pd.DataFrame) -> pd.Series:
    cols = [f"ask_size_{i}" for i in range(5)]
    pivoted = (book.assign(ask5=book[cols].sum(axis=1))
                   .groupby(["slug","outcome"])["ask5"].mean()
                   .unstack(fill_value=0))
    yes = pivoted.get("Up", 0)
    no  = pivoted.get("Down", 0)
    denom = (yes + no).replace(0, np.nan)
    return ((no - yes) / denom).fillna(0)


def combine_to_prob_c(raw_c: pd.Series) -> pd.Series:
    return 0.5 + 0.4 * raw_c.clip(-1, 1)


def isotonic_calibrate(raw_train, y_train, raw_to_cal):
    iso = IsotonicRegression(out_of_bounds="clip")
    iso.fit(raw_train, y_train)
    return iso.transform(raw_to_cal)


def load_flow(asset: str) -> pd.DataFrame:
    p = DATA_DIR / "polymarket" / f"{asset}_flow_v3.csv"
    return pd.read_csv(p)


def load_book_depth(asset: str) -> pd.DataFrame:
    p = DATA_DIR / "polymarket" / f"{asset}_book_depth_v3.csv"
    bd = pd.read_csv(p)
    # Use only the snapshot at bucket_10s == 0 (window-start) to avoid leakage
    return bd[bd.bucket_10s == 0]


def build_one_asset(asset: str) -> None:
    feats = load_features(asset)
    flow = load_flow(asset)
    book = load_book_depth(asset)

    flow_signal = flow_signal_per_market(flow).rename("flow")
    imbalance   = book_imbalance_top5(book).rename("imb")
    feats = feats.merge(flow_signal, left_on="slug", right_index=True, how="left")
    feats = feats.merge(imbalance, left_on="slug", right_index=True, how="left")
    feats[["flow", "imb"]] = feats[["flow", "imb"]].fillna(0)
    raw_c = 0.6 * feats["flow"] + 0.4 * feats["imb"]
    feats["prob_c_raw"] = combine_to_prob_c(raw_c)

    train, _ = chronological_split(feats)
    feats["prob_c"] = isotonic_calibrate(
        train["prob_c_raw"].values, train["outcome_up"].values, feats["prob_c_raw"].values
    )
    feats = feats.drop(columns=["flow", "imb", "prob_c_raw"])
    save_features(asset, feats)
    print(f"{asset}: prob_c written, mean={feats['prob_c'].mean():.3f}, "
          f"std={feats['prob_c'].std():.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default=os.getenv("ASSET", "all"))
    args = ap.parse_args()
    assets = ASSETS if args.asset == "all" else (args.asset,)
    for a in assets:
        build_one_asset(a)


if __name__ == "__main__":
    main()
```

**Step 4: Tests pass.**

```bash
pytest strategy_lab/v2_signals/test_build_signal_c.py -v
```

**Step 5: Run on real data.**

```bash
python -m strategy_lab.v2_signals.build_signal_c
```

**Step 6: Verify all 3 prob columns exist + sanity-check IC.**

```bash
python -c "
import pandas as pd
df = pd.read_csv('strategy_lab/data/polymarket/btc_features_v3.csv')
for col in ['prob_a','prob_b','prob_c']:
    ic = df[[col,'outcome_up']].corr().iloc[0,1]
    print(f'{col}: IC={ic:+.4f}, mean={df[col].mean():.3f}')
print('correlation matrix prob_a/b/c:')
print(df[['prob_a','prob_b','prob_c']].corr())
"
```

Expected: each IC > 0 (positive — higher prob → higher actual outcome). Pairwise correlations 0.2–0.6.

**Step 7: Commit.**

```bash
git add strategy_lab/v2_signals/build_signal_c.py strategy_lab/v2_signals/test_build_signal_c.py strategy_lab/data/polymarket/*.csv
git commit -m "feat(v2_signals): add prob_c (Polymarket microstructure flow)"
```

---

## Task 6: Stack meta-model

**Files:**
- Create: `strategy_lab/v2_signals/build_stack.py`
- Create: `strategy_lab/v2_signals/test_build_stack.py`

**Step 1: Write failing tests.**

```python
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.build_stack import fit_stack, apply_stack

def test_fit_stack_returns_calibrated_classifier():
    n = 1000
    rng = np.random.RandomState(0)
    X = pd.DataFrame({
        "prob_a": rng.uniform(0,1,n),
        "prob_b": rng.uniform(0,1,n),
        "prob_c": rng.uniform(0,1,n),
    })
    # outcome correlated with X.prob_a
    y = (X.prob_a + 0.1 * rng.randn(n) > 0.5).astype(int)
    clf = fit_stack(X, y)
    assert hasattr(clf, "predict_proba")

def test_apply_stack_outputs_in_unit_interval():
    n = 500; rng = np.random.RandomState(1)
    X = pd.DataFrame({c: rng.uniform(0,1,n) for c in ["prob_a","prob_b","prob_c"]})
    y = rng.randint(0,2,n)
    clf = fit_stack(X, y)
    p = apply_stack(clf, X)
    assert ((p >= 0) & (p <= 1)).all()
```

**Step 2: Run to fail.**

```bash
pytest strategy_lab/v2_signals/test_build_stack.py -v
```

**Step 3: Implement.**

```python
"""Stack meta-model — logistic regression + isotonic calibration on (prob_a, prob_b, prob_c)."""
from __future__ import annotations
import argparse, os
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from strategy_lab.v2_signals.common import load_features, save_features, ASSETS
from strategy_lab.v2_signals.build_signal_a import chronological_split


def fit_stack(X: pd.DataFrame, y: pd.Series):
    base = LogisticRegression(C=1.0, fit_intercept=True, max_iter=1000)
    clf = CalibratedClassifierCV(base, cv=3, method="isotonic")
    clf.fit(X.values, y.values if hasattr(y, "values") else y)
    return clf


def apply_stack(clf, X: pd.DataFrame) -> np.ndarray:
    return clf.predict_proba(X.values)[:, 1]


def build_one_asset(asset: str) -> None:
    df = load_features(asset)
    cols = ["prob_a", "prob_b", "prob_c"]
    if not all(c in df.columns for c in cols):
        raise RuntimeError(f"{asset} missing one of {cols} — run build_signal_{{a,b,c}} first")
    train, _ = chronological_split(df)
    clf = fit_stack(train[cols], train["outcome_up"])
    df["prob_stack"] = apply_stack(clf, df[cols])
    save_features(asset, df)
    # Inspect base estimator coefficients (averaged across CV folds)
    base = clf.calibrated_classifiers_[0].estimator
    coefs = base.coef_[0]
    print(f"{asset}: stack written, mean={df['prob_stack'].mean():.3f}, "
          f"coefs(a,b,c)={coefs.round(3).tolist()}, intercept={base.intercept_[0]:.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default=os.getenv("ASSET", "all"))
    args = ap.parse_args()
    assets = ASSETS if args.asset == "all" else (args.asset,)
    for a in assets:
        build_one_asset(a)


if __name__ == "__main__":
    main()
```

**Step 4: Tests pass.**

```bash
pytest strategy_lab/v2_signals/test_build_stack.py -v
```

**Step 5: Run.**

```bash
python -m strategy_lab.v2_signals.build_stack
```

Expected: 3 lines, coefs printed. Read coefs — that's the meta-model interpretation.

**Step 6: Verify.**

```bash
python -c "
import pandas as pd
df = pd.read_csv('strategy_lab/data/polymarket/btc_features_v3.csv')
for col in ['prob_a','prob_b','prob_c','prob_stack']:
    ic = df[[col,'outcome_up']].corr().iloc[0,1]
    print(f'{col}: IC={ic:+.4f}')
"
```

Expected: prob_stack IC ≥ max(individual ICs).

**Step 7: Commit.**

```bash
git add strategy_lab/v2_signals/build_stack.py strategy_lab/v2_signals/test_build_stack.py strategy_lab/data/polymarket/*.csv
git commit -m "feat(v2_signals): add prob_stack (LogReg meta-model)"
```

---

## Task 7: Wire signals into existing engines

**Files:**
- Modify: `strategy_lab/polymarket_signal_grid_v2.py`
- Modify: `strategy_lab/polymarket_forward_walk_v2.py`

**Step 1: Find the signal-list location.**

```bash
grep -n "q10\|q20\|signal\s*=\|SIGNALS\b" strategy_lab/polymarket_signal_grid_v2.py | head -20
```

Identify the loop that defines signals (likely a list of `(name, predicate_func)` tuples or column names).

**Step 2: Add 4 entries.** For each new signal, add to the list:

```python
("prob_a",     "prob_a",     0.55, 0.45),  # threshold UP, threshold DOWN
("prob_b",     "prob_b",     0.55, 0.45),
("prob_c",     "prob_c",     0.55, 0.45),
("prob_stack", "prob_stack", 0.55, 0.45),
```

If the engine internally maps `q10`/`q20` to functions, add a helper:

```python
def prob_signal(df, col, thr_up=0.55, thr_dn=0.45):
    df = df.copy()
    df["sig_dir"] = np.where(df[col] >= thr_up, +1,
                     np.where(df[col] <= thr_dn, -1, 0))
    return df
```

**Step 3: Same for `forward_walk_v2.py`.** Add the 4 signals to its iteration list.

**Step 4: Smoke-test.**

```bash
cd strategy_lab && python polymarket_signal_grid_v2.py 2>&1 | tail -10
```

Expected: new rows in output for `prob_a/b/c/stack`, alongside existing `q10/q20/full`.

**Step 5: Inspect results.**

```bash
python -c "
import pandas as pd
df = pd.read_csv('strategy_lab/results/polymarket/signal_grid_v2.csv')
print(df[df.signal.isin(['prob_a','prob_b','prob_c','prob_stack'])].sort_values('roi_pct', ascending=False).head(20).to_string())
"
```

**Step 6: Commit.**

```bash
git add strategy_lab/polymarket_signal_grid_v2.py strategy_lab/polymarket_forward_walk_v2.py strategy_lab/results/polymarket/signal_grid_v2.csv
git commit -m "feat(v2_signals): wire prob_a/b/c/stack into signal_grid_v2 + forward_walk_v2"
```

---

## Task 8: Forward-walk holdout for the 4 new signals

**Files:**
- Run: `strategy_lab/polymarket_forward_walk_v2.py`

**Step 1: Run.**

```bash
cd strategy_lab && python polymarket_forward_walk_v2.py 2>&1 | tail -40
```

**Step 2: Capture pass/fail per signal.**

```bash
python -c "
import pandas as pd
df = pd.read_csv('strategy_lab/results/polymarket/forward_walk_v2.csv')
for sig in ['prob_a','prob_b','prob_c','prob_stack']:
    sub = df[df.signal == sig]
    print(f'=== {sig} ===')
    print(sub[['timeframe','asset','train_hit','holdout_hit','holdout_roi_pct']].to_string(index=False))
"
```

Apply gates from design §7:
- Holdout hit ≥ 60%
- Holdout ROI ≥ +10%
- Train→holdout drop ≤ 8 pp

**Step 3: Commit results CSV.**

```bash
git add strategy_lab/results/polymarket/forward_walk_v2.csv
git commit -m "test(v2_signals): forward-walk holdout for 4 new signals"
```

---

## Task 9: Live reconciliation

**Files:**
- Create: `strategy_lab/v2_signals/reconcile_live.py`

**Step 1: Implement the reconciler.**

For every resolved market in `vps2_v1_shadow.csv` and `vps3_v2_shadow.csv`, compute what each of the 4 new signals would have done and compare predicted hit rate vs actual.

```python
"""Live reconciliation for prob_a/b/c/stack against VPS2 V1 + VPS3 V2 shadow tapes."""
from __future__ import annotations
import json
import pandas as pd
from pathlib import Path
from strategy_lab.v2_signals.common import load_features, ASSETS, DATA_DIR


def parse_shadow_tape(path: Path) -> pd.DataFrame:
    rows = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        next(f)  # header
        for line in f:
            parts = line.rstrip().split(",", 3)
            if len(parts) < 4:
                continue
            at, sleeve, kind, data = parts
            if data.startswith('"') and data.endswith('"'):
                data = data[1:-1].replace('""', '"')
            try:
                d = json.loads(data) if data.startswith('{') else {}
            except Exception:
                continue
            if kind == "poly_updown_resolution":
                rows.append({"at": at, "sleeve": sleeve, **d})
    return pd.DataFrame(rows)


def reconcile(box_name: str, shadow_path: Path):
    tape = parse_shadow_tape(shadow_path)
    if tape.empty:
        print(f"{box_name}: no resolutions"); return
    # Need to join with features by slug or condition_id
    all_feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    # Map sleeve_id (e.g. poly_updown_btc_5m) → asset, tf
    tape["asset"] = tape.sleeve.str.extract(r"poly_updown_([a-z]+)_")
    tape["tf"]    = tape.sleeve.str.extract(r"poly_updown_[a-z]+_(\d+m)")
    if "condition_id" in tape.columns and "condition_id" in all_feats.columns:
        joined = tape.merge(all_feats, on="condition_id", how="inner", suffixes=("_l", ""))
    else:
        # Fallback: join by slug if available
        joined = tape.merge(all_feats, on="slug", how="inner", suffixes=("_l", ""))

    print(f"\n=== {box_name}: {len(joined)}/{len(tape)} resolutions matched to features ===")
    for col in ["prob_a", "prob_b", "prob_c", "prob_stack"]:
        if col not in joined.columns:
            continue
        # Predicted direction based on threshold
        pred_up = joined[col] >= 0.55
        pred_dn = joined[col] <= 0.45
        actual_up = (joined["outcome"] == "Up") if "outcome" in joined.columns else (joined["won"].astype(bool))
        # Hit when prediction matches actual
        hits = ((pred_up & actual_up) | (pred_dn & ~actual_up))
        n_acted = pred_up.sum() + pred_dn.sum()
        if n_acted == 0:
            print(f"  {col}: no signals fired"); continue
        hit_rate = (hits & (pred_up | pred_dn)).sum() / n_acted
        print(f"  {col}: live hit={hit_rate:.1%} on n={n_acted} (pred_up={pred_up.sum()}, pred_dn={pred_dn.sum()})")


def main():
    base = DATA_DIR / "polymarket"
    reconcile("VPS2 V1", base / "vps2_v1_shadow.csv")
    reconcile("VPS3 V2", base / "vps3_v2_shadow.csv")


if __name__ == "__main__":
    main()
```

**Step 2: Run.**

```bash
python -m strategy_lab.v2_signals.reconcile_live
```

**Step 3: Commit.**

```bash
git add strategy_lab/v2_signals/reconcile_live.py
git commit -m "test(v2_signals): live reconciliation against VPS2/VPS3 shadow tapes"
```

---

## Task 10: Findings synthesis report

**Files:**
- Create: `strategy_lab/reports/POLYMARKET_V2_SIGNALS_FINDINGS.md`
- Create: `strategy_lab/v2_signals/build_findings.py`

**Step 1: Implement the report builder.**

```python
"""Aggregate Tier 1, forward-walk, and live recon results into a findings doc."""
from __future__ import annotations
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent.parent
RESULTS = HERE / "results" / "polymarket"
REPORTS = HERE / "reports"


def main():
    grid = pd.read_csv(RESULTS / "signal_grid_v2.csv")
    fw   = pd.read_csv(RESULTS / "forward_walk_v2.csv")

    new_signals = ["prob_a", "prob_b", "prob_c", "prob_stack"]

    out = ["# V2 Signals — Findings\n"]
    out.append(f"**Date:** {pd.Timestamp.utcnow().strftime('%Y-%m-%d')}\n")

    out.append("## Tier 1 — Baseline grid (top 10 by ROI)")
    top = grid[grid.signal.isin(new_signals)].nlargest(10, "roi_pct")
    out.append(top[["signal","timeframe","asset","rule","n","hit","roi_pct","sharpe","max_dd"]].to_markdown(index=False))

    out.append("\n## Forward-walk holdout (gate: hit ≥60%, ROI ≥+10%, drift ≤8pp)")
    for sig in new_signals:
        sub = fw[fw.signal == sig]
        out.append(f"\n### {sig}")
        out.append(sub[["timeframe","asset","train_hit","holdout_hit","holdout_roi_pct"]].to_markdown(index=False))
        passed = sub[(sub.holdout_hit >= 0.60) & (sub.holdout_roi_pct >= 10.0)
                     & ((sub.train_hit - sub.holdout_hit) <= 0.08)]
        out.append(f"\n**Cells passing all gates:** {len(passed)}/{len(sub)}")

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "POLYMARKET_V2_SIGNALS_FINDINGS.md").write_text("\n\n".join(out))
    print("Wrote", REPORTS / "POLYMARKET_V2_SIGNALS_FINDINGS.md")


if __name__ == "__main__":
    main()
```

**Step 2: Run.**

```bash
python -m strategy_lab.v2_signals.build_findings
```

**Step 3: Commit.**

```bash
git add strategy_lab/v2_signals/build_findings.py strategy_lab/reports/POLYMARKET_V2_SIGNALS_FINDINGS.md
git commit -m "docs(v2_signals): findings synthesis report"
```

---

## Task 11: Decision

Open `POLYMARKET_V2_SIGNALS_FINDINGS.md`. Apply the decision tree from design §7:

- Stack passes, components fail → ship stack alone.
- Components pass, stack adds <2 pp lift → ship best component alone.
- Multiple components pass independently → ship as parallel sleeves with stack as 4th.
- Nothing passes → abandon the V2 stack project; revert to sig_ret5m sniper q10.

Write decision to `docs/V2_SIGNALS_DECISION.md` (single paragraph). Hand off to TV agent for VPS3 deployment per `VPS3_FIX_PLAN.md` (the new prob signals just become additional sleeves alongside sniper q10).

---

## Risk register (from design §10)

Each addressed in tasks above:
- **Look-ahead bias in B**: Task 3 enforces `closes[ts ≤ window_start_unix]` only.
- **Train-set isotonic leakage**: Tasks 3, 5 fit isotonic ON THE TRAIN SLICE ONLY (`chronological_split` before fit).
- **Sklearn calibration on small n**: Task 6 uses 3-fold CV (`cv=3`) and 7d × ~6,500 train samples is plenty for 3 features.
- **Signal redundancy with ret_5m**: Task 5 step 6 prints corr matrix; if any pair > 0.85, surface for design review before Task 6.
- **C requires expensive trades_v2 join**: Task 4 pre-aggregates at SQL level on VPS2.

---

**Plan complete and saved to `docs/plans/2026-04-29-v2-signals-implementation.md`. Two execution options:**

**1. Subagent-Driven (this session)** — I dispatch fresh subagent per task, review between tasks, fast iteration.

**2. Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints.

**Which approach?**
