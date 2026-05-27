# VPS3 shadow-sleeve verification kit — 2026-05-25

**Why this exists**: I cannot SSH to VPS3 from this machine (key auth fails), and the local `trading_events_30d.parquet` snapshot is 3 days stale (last event = 2026-05-21 20:17 UTC). So I can't directly verify whether the 9 new shadow sleeves I specced on 2026-05-24 (`SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md`) are firing on VPS3.

**This kit** does the verification in 3 stages, runnable by you (or anyone with VPS3 SSH).

## Stage 0 — confirm with me what's expected

The 9 shadow sleeves I specced (all with `sleeve_id` starting `shadow_poly_updown_`):

```
shadow_poly_updown_ALL_5m_phase1_kelly
shadow_poly_updown_btc_5m_fade_momo_v2
shadow_poly_updown_btc_5m_fade_sniper
shadow_poly_updown_eth_15m_fade_sniper
shadow_poly_updown_sol_5m_fade_sniper
shadow_poly_updown_sol_5m_fade_momo_v2
shadow_poly_updown_sol_15m_fade_momo_v2
shadow_poly_updown_ALL_5m_S3_prewindow
shadow_poly_updown_ALL_15m_S4_prewindow
```

In the LOCAL snapshot (4 days old) **none of these sleeves have ever emitted an event**. Possible reasons:

1. The deploy hasn't happened yet on VPS3.
2. The deploy happened but used DIFFERENT sleeve_ids than the spec.
3. The deploy happened AFTER my snapshot was pulled.

Run the kit on VPS3 to disambiguate.

## Stage 1 — `02_grep_source_check.sh` (source-code presence)

Run ON VPS3 in the `tradingvenue` repo:

```bash
cd /opt/tradingvenue/backend
bash 02_grep_source_check.sh
```

Verifies:
- Whether any of the 9 `sleeve_id` strings exist in `app/`.
- Whether new features (`fair_edge_bp`, `cvd_30s`, `macd_hist`, `rvol_30_300`, `imb5`, `kelly_mult`, etc.) are referenced anywhere.
- Where sleeves get registered (`register_poly_updown` / `_SHADOW_GATED_SLEEVES_SPEC`).
- Last 7 d of git log on engine + polymarket dirs.
- Env-var setting `TV_POLY_SHADOW_*`.
- Whether `tv-engine` was restarted recently.

Outputs `✓ FOUND` or `✗ NOT FOUND` per item.

## Stage 2 — `01_check_trading_events.sql` (live event check)

Run on VPS3 with `psql storedata` access:

```bash
psql storedata -h localhost -U <storedata_user> -f 01_check_trading_events.sql > /tmp/trading_events_check.txt 2>&1
```

8 checks in one file:
1. Presence: how many events per shadow sleeve in last 7 days
2. Catch-all: any `sleeve_id LIKE 'shadow_%'` in last 2 days
3. Fire-rate vs backtest expectation (per-sleeve OK/LOW/HIGH/MISSING)
4. Realized PnL per sleeve (matched fires to resolutions)
5. Feature-payload sanity (% of fires carrying each new feature in `data` JSON)
6. Kelly tier distribution on the phase-1 ensemble
7. FADE companion direction sanity (shadow should fire OPPOSITE of prod)
8. Pre-window offset check (S3 should fire at offset `-60s`, S4 at `-120s`)

The exact output structure is at the top of each `\echo` line in the SQL.

## Stage 3 — `03_compare_to_backtest.py` (PnL comparison)

Run LOCALLY after pulling a fresh `trading_events_30d.parquet`:

```bash
# 1. Refresh from VPS3 (script paths vary by tag; pick the latest)
bash migration_2026_05_2x/pull_delta_vps3_<TAG>.sh

# 2. Convert + merge into canonical
python migration_2026_05_2x/convert_and_merge.py
python migration_2026_05_2x/merge_to_canonical.py

# 3. Compare live vs backtest
py strategy_lab/overnight_2026_05_23/vps3_verify_shadow_sleeves/03_compare_to_backtest.py
```

Produces `data/v4/canonical/_results/shadow_sleeves_vs_backtest.csv` with per-sleeve columns:

| col | meaning |
|---|---|
| `days_covered` | how many days the shadow has been running |
| `fires_per_day_obs` / `fires_per_day_exp` | live vs expected fire rate |
| `fires_dev_pct` | % deviation (positive = more fires than expected) |
| `wr_pct_obs` / `wr_pct_exp` | live vs expected win rate |
| `wr_dev_pp` | pp deviation |
| `per_tr_obs` / `per_tr_exp` | live vs expected per-trade $ |
| `sum_per_day_obs` / `sum_per_day_exp` | live vs expected daily PnL |
| **verdict** | `MISSING` / `LOW_FIRES` / `HIGH_FIRES` / `WR_LOW` / `WR_HIGH` / `PNL_LOW` / `OK` |

## What I'm looking for in the output

### Pass criteria (all 9 sleeves)

- `fires_per_day_obs` within 0.5× – 2× of `expected`
- `wr_pct_obs` within ±5 pp of `wr_pct_exp`
- `sum_per_day_obs` ≥ 0.5 × `sum_per_day_exp`
- For sleeve `#1` (phase1_kelly): Kelly tier distribution should be roughly:
  - 1× tier: ~77 % of fires
  - 2× tier: ~14 %
  - 3× tier: ~5 %
  - 4× tier: ~4 %
- For FADE sleeves (#2-7): SQL §7 should show **100 % "OK: OPPOSITE"** rows. Any "SAME DIRECTION" = critical bug.
- For pre-window sleeves (#8-9): SQL §8 should show `fire_offset_s = -60` for S3 5m and `-120` for S4 15m, with negligible noise.

### Fail signals to escalate

| signal | implication |
|---|---|
| All 9 missing in source AND events | deploy never happened — go look at the deploy ticket |
| Source exists, events missing | engine restart didn't pick up the change OR env-var gate is off |
| Events exist but feature columns NaN | feature publisher not wired to the new sleeves |
| Fire-rate < 50 % of expected | filter logic too strict OR feature feed dropping fires |
| WR / per_tr way off backtest | implementation bug (wrong direction, wrong fee, stale book) |
| FADE shadow same direction as prod | the OPPOSITE flip never gets applied |
| Pre-window fires at offset_s ≥ 0 | timing logic broken — sleeve is firing intra-slot |

## Then send me back

After running the kit, paste me:
- `02_grep_source_check.sh` output (tells me what the source has)
- `01_check_trading_events.sql` output sections 1, 3, 4, 7, 8 (live behaviour)
- `03_compare_to_backtest.py` output CSV (variance vs backtest)

I'll cross-reference and tell you exactly which sleeves need attention.

## Local-snapshot caveat

Right now, with the 3-day-stale parquet I have, `03_compare_to_backtest.py` reports **all 9 sleeves as MISSING** — could be either "never deployed" or "deployed after my snapshot". The fresh pull is the only way to disambiguate.

## Files

- `01_check_trading_events.sql` — psql script, 8 sections
- `02_grep_source_check.sh` — VPS3 bash, source-code presence
- `03_compare_to_backtest.py` — local pandas, fires vs backtest
- `README.md` — this file
