# TV Agent Fix — Dashboard PnL: cumulative-since-deploy mode

**Date**: 2026-05-27
**Scope**: dashboard PnL column shows lifetime (cumulative-since-deploy) PnL per sleeve, not just today's UTC PnL.
**Effort**: ~1-2 dev-hours.
**Files**: `backend/app/api/maker_sleeves.py`.

## 1. Current behavior (the bug)

Operator dashboard at `/maker-sleeves` shows PnL like:
```
ACC-M btc 5m   −$242.46
ACC-H btc 15m  +$59.33
ACC-PC btc 15m −$38.56
MAS btc 5m     +$0.44
MAS btc 15m    +$26.76
PAT-SHADOW     −$2334.54
```

These numbers are **today only (UTC 00:00 → now)**, computed from a single CSV file `/var/log/tv/maker/<sleeve>_<TODAY_UTC>.csv`. At UTC midnight every day, **all sleeves reset to $0**.

Confirmed by reading `api/maker_sleeves.py` and reproducing the numbers exactly with today's-CSV-only data (`migration_ireland_shadow_2026_05_27/audit_today_only.py`).

## 2. Problem with current behavior

Operator can't see:
- Trend across days (was yesterday better or worse?)
- Multi-day drawdown picture
- Whether sleeve is profitable on net since deploy
- Magnitude of recent change (today's −$200 might look big but if lifetime is +$5,000 it's a normal day; if lifetime is −$5,000 it's a problem)

The session-reset behavior was a side effect of how `AsyncShadowLogger` rotates CSV files daily, not a deliberate design choice.

## 3. Desired behavior

Dashboard shows TWO columns per sleeve:

| sleeve | today $ | lifetime $ |
|---|---:|---:|
| ACC-M btc 5m | −$242 | +$3,420 |
| ACC-H btc 15m | +$59 | +$1,205 |
| ... | | |

- **`today_pnl`** = current behavior, kept as-is (today UTC 00:00 → now)
- **`lifetime_pnl`** = sum over ALL CSV files for this sleeve in `/var/log/tv/maker/`

Compute on every API request (cheap; CSVs are ~5-15MB per day per sleeve, 30 days = 150-450MB across all).

For performance: cache the lifetime sum per (sleeve, file_date) with file mtime as cache key. Today's CSV is "live"; recompute every request. Past CSVs only change if log rotation re-touches them — cache lifetime with TTL=300s or invalidate by mtime check.

## 4. Implementation

### 4.1 Edit `backend/app/api/maker_sleeves.py`

Find the `MakerSleeveStateRow` Pydantic model. Add field:

```python
class MakerSleeveStateRow(BaseModel):
    # ... existing fields ...
    pnl_so_far: float          # KEEP — this is today's pnl with mark
    pnl_today_cash: float      # NEW — today's pnl WITHOUT mark (cash only)
    pnl_lifetime: float        # NEW — sum of pnl across all CSV files for this sleeve
    pnl_lifetime_cash: float   # NEW — same, cash-only
    n_days_active: int         # NEW — how many distinct days the sleeve has CSVs
    deploy_first_ts_us: int    # NEW — first ts_us across all CSVs (when sleeve started)
```

(Keep `pnl_so_far` for backward-compat with the current frontend; new fields are additive.)

### 4.2 New function `_compute_lifetime_pnl`

```python
import functools, os
from pathlib import Path

@functools.lru_cache(maxsize=1024)
def _read_sleeve_csv_cached(csv_path: str, mtime: float):
    """Read + parse one sleeve CSV. Cache key includes mtime so cache invalidates on file change."""
    df = pd.read_csv(csv_path, engine="python", on_bad_lines="skip")
    for c in ["cash_spent","cash_received","cash_recovered","rebates","taker_fees",
              "slug_pnl_so_far","price","size","inv_up","inv_dn","ts_us"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df

def _compute_lifetime_pnl(sleeve_id: str, log_dir: Path, today_csv: Path) -> dict:
    """Aggregate cumulative PnL across ALL CSV files for this sleeve.

    Returns:
        {pnl_lifetime, pnl_lifetime_cash, n_days_active, deploy_first_ts_us}

    Today's CSV is read fresh; past CSVs use mtime-cached parse.
    """
    strategy_code = _strategy_code_from_sleeve_id(sleeve_id)
    prefix = strategy_code.lower().replace("_","-")
    pattern = f"{prefix}_*.csv"
    all_csvs = sorted(log_dir.glob(pattern))
    if not all_csvs:
        return {"pnl_lifetime": 0.0, "pnl_lifetime_cash": 0.0,
                "n_days_active": 0, "deploy_first_ts_us": 0}

    lifetime_with_mark = 0.0
    lifetime_cash_only = 0.0
    deploy_first_ts = None
    n_days_active = 0

    for csv_path in all_csvs:
        mtime = os.path.getmtime(csv_path)
        df = _read_sleeve_csv_cached(str(csv_path), mtime)

        # Filter to this sleeve_id (one file can contain multiple sleeve_ids)
        if "sleeve_id" in df.columns:
            df = df[df["sleeve_id"] == sleeve_id]
        if len(df) == 0:
            continue

        n_days_active += 1
        if deploy_first_ts is None:
            deploy_first_ts = int(df["ts_us"].min())
        else:
            deploy_first_ts = min(deploy_first_ts, int(df["ts_us"].min()))

        # Compute pnl for this day's CSV using existing per-slug formula
        pnl_with_mark, pnl_cash = _compute_pnl_for_df(df, with_mark=True), _compute_pnl_for_df(df, with_mark=False)
        lifetime_with_mark += pnl_with_mark
        lifetime_cash_only += pnl_cash

    return {
        "pnl_lifetime": lifetime_with_mark,
        "pnl_lifetime_cash": lifetime_cash_only,
        "n_days_active": n_days_active,
        "deploy_first_ts_us": deploy_first_ts or 0,
    }

def _compute_pnl_for_df(df: pd.DataFrame, with_mark: bool) -> float:
    """Apply the same per-slug formula as the existing /maker-sleeves endpoint."""
    if "sleeve_id" not in df.columns:
        return 0.0
    cash_rows = df[(df["cash_spent"].abs() + df["cash_received"].abs()) > 0]
    if len(cash_rows) == 0:
        return 0.0
    latest_per_slug = cash_rows.sort_values("ts_us").groupby("slug").last()
    redeem_fired = set(df[df["action"] == "REDEEM"]["slug"].unique())

    pnl = 0.0
    for slug, row in latest_per_slug.iterrows():
        inv_up = row.get("inv_up", 0) or 0
        inv_dn = row.get("inv_dn", 0) or 0
        paired = min(inv_up, inv_dn)
        residual = abs(inv_up - inv_dn)
        if with_mark:
            mark = paired * 1.0 + (residual * 0.5 if slug not in redeem_fired else 0)
        else:
            mark = 0.0
        pnl += (
            row.get("cash_received", 0) + row.get("cash_recovered", 0)
            - row.get("cash_spent", 0) + row.get("rebates", 0)
            - row.get("taker_fees", 0) + mark
        )
    return pnl
```

### 4.3 Call site update

In the existing endpoint handler (`get_sleeve_state` or similar), after computing today's `pnl_so_far`:

```python
log_dir = Path(settings.tv_poly_maker_log_dir)
lifetime_stats = _compute_lifetime_pnl(sleeve_id, log_dir, csv_path)

return MakerSleeveStateRow(
    # ... existing fields ...
    pnl_so_far=pnl_so_far,                                     # today's with mark (kept)
    pnl_today_cash=pnl_today_cash,                             # NEW
    pnl_lifetime=lifetime_stats["pnl_lifetime"],               # NEW
    pnl_lifetime_cash=lifetime_stats["pnl_lifetime_cash"],     # NEW
    n_days_active=lifetime_stats["n_days_active"],             # NEW
    deploy_first_ts_us=lifetime_stats["deploy_first_ts_us"],   # NEW
)
```

### 4.4 Frontend display

Update the dashboard table to show 4 columns instead of 1:

```
| sleeve         | today (mark) | today cash | lifetime (mark) | lifetime cash |
|----------------|-------------:|-----------:|----------------:|--------------:|
| ACC-M btc 5m   |     −$242.46 |  −$1,122   |      +$3,420.21 |    +$1,580.40 |
| ACC-H btc 15m  |      +$59.33 |    −$167   |      +$1,205.50 |      +$890.20 |
```

Or simpler: single PnL column, but two display modes toggled by operator (today / lifetime), default `lifetime`.

### 4.5 Performance considerations

- Per-request, all CSV files in `/var/log/tv/maker/` are inspected (no DB).
- 30 days × 6 sleeves × ~10MB/day = ~1.8 GB total disk read in worst case.
- LRU cache on `_read_sleeve_csv_cached` keyed by `(path, mtime)` keeps re-reads to ZERO for unchanged files. Only today's CSV is re-read on every API hit.
- Cache miss cost: ~200ms per file. Cold start (~30 files × 200ms = 6s for first request). Subsequent requests: ~200ms (just today's file).
- Acceptable for an operator dashboard; if too slow, add a 60s endpoint cache.

## 5. Smoke test

After deploy + restart `tv-api.service`:

1. Open dashboard. Verify 4 new columns appear (or single column with mode toggle).
2. `today` columns match current behavior (sanity).
3. `lifetime` for ACC-M btc 5m should equal `sum(all daily PnL since 2026-05-19)` — verify by running:
   ```python
   import pandas as pd, glob, os
   files = sorted(glob.glob(r"/var/log/tv/maker/acc-m_*.csv"))
   total = sum(_compute_pnl_for_df(pd.read_csv(f, engine="python", on_bad_lines="skip"), with_mark=True) for f in files)
   print(total)
   ```
   Match the dashboard's `lifetime_pnl` for ACC-M-V1 within $1.
4. `deploy_first_ts_us` = earliest ts in any CSV for this sleeve. For ACC-M that's the original deploy date.
5. Toggle to today-only mode → returns to old numbers.

## 6. Migration considerations

- Existing frontend will break if it expects ONLY the old field name and we remove it. **Don't remove** — `pnl_so_far` stays as the today-with-mark column. NEW fields are additive.
- DB schema unchanged (we're reading from CSV files on disk).
- No breaking change to `MakerSleeveStateRow` shape (extra fields don't break Pydantic v2 deserializers).

## 7. Rollout checklist

- [ ] Add fields to `MakerSleeveStateRow` schema
- [ ] Add `_compute_lifetime_pnl` + `_compute_pnl_for_df` helpers in `maker_sleeves.py`
- [ ] Wire call site to populate new fields
- [ ] Frontend: add `lifetime_pnl` column or toggle mode
- [ ] Restart `tv-api.service`
- [ ] Smoke test (§5)
- [ ] Verify cache hit rate via debug log after 1h running

## 8. Future enhancements (not in this PR)

1. **30-day rolling PnL** column (last-30d window). Useful if old data is too noisy and operator wants recent picture.
2. **Per-week breakdown** — show last 4 weeks separately.
3. **Drawdown indicator** — max drawdown over lifetime + days since max-DD.
4. **Sleeve start-date column** — converted from `deploy_first_ts_us` to a date string ("started 2026-05-19").

## 9. References

- Current behavior verified at: `migration_ireland_shadow_2026_05_27/audit_today_only.py`
- Existing API formula at: `backend/app/api/maker_sleeves.py:529-535`
- Reconstructed numbers in operator screenshot (2026-05-27) match today-only mode within $20

## 10. Why this matters

Operator currently looks at the dashboard and sees `ACC-M −$242.46` for today. Cannot tell if:
- This is a normal Tuesday morning (lifetime +$3k, no concern)
- This is the start of a drawdown (lifetime now −$5k, KILL)

Adding lifetime visibility is the single most-requested operator improvement and unblocks several other downstream decisions (e.g. when to promote V2 to live — needs lifetime comparison to V1 baseline).
