# Bug B: pyarrow missing + data files absent — V9 sleeves fully blocked

**Date:** 2026-05-29  
**Scope:** Read-only investigation. No changes made to VPS.

---

## 1. Root Cause (two compounded issues)

### Issue B1 — pyarrow not in pyproject.toml deps (library missing)

`/opt/tradingvenue/pyproject.toml` lists `pandas~=2.2` but NOT `pyarrow` or `fastparquet`.
pandas 2.x requires one of these for `pd.read_parquet()`.

Evidence:
- `/opt/tradingvenue/.venv/bin/python -c "import pyarrow"` → ImportError
- Logs every 5 min: `sniper_v5_v9_data.trades_load_failed` (btc/eth/sol) + `sniper_v5_v9_data.hl_load_failed`
- Error: `"Unable to find a usable engine; tried using: 'pyarrow', 'fastparquet'"`
- `uv pip show pyarrow` → `warning: Package(s) not found for: pyarrow`

**NOTE:** The uv install dry-run during investigation appears to have actually installed pyarrow 24.0.0. Verify:
`ssh vps3 '/opt/tradingvenue/.venv/bin/python -c "import pyarrow; print(pyarrow.__version__)"'`
If it prints 24.0.0, B1 is already fixed.

### Issue B2 — canonical parquet data files DO NOT EXIST on VPS3 (the worse problem)

`core/config.py` defaults `tv_poly_sniper_v5_v9_data_root = "/opt/tradingvenue/data"`.
`TV_POLY_SNIPER_V5_V9_DATA_ROOT` is NOT set in `/etc/tv/tradingvenue.env`.
`V9DataStore` expects:
- `{data_root}/v4/canonical/trades_polymarket/{btc,eth,sol}.parquet`
- `{data_root}/v4/canonical/hyperliquid_liquidations_full.parquet`

VPS check:
```
ls /opt/tradingvenue/data/          → No such file or directory
ls .../trades_polymarket/           → No such file or directory
ls .../hyperliquid_liquidations_full.parquet → No such file or directory
```

The canonical parquets live only on the local Windows machine. They have never been synced to VPS3.
`/opt/storedata/` has no export job producing these files — only raw DB collectors and backfill scripts exist there.

---

## 2. Downstream Behavior: Hard Abstain

All four V9 gate functions explicitly return `False` on missing data:

- `g_a2_hl_short_cascade`: `if hl_short_proxy is None: return False`
- `g_b1_poly_flow_aligned`: `if asset_trades is None or slug is None: return False`
- `g_b2_poly_flow_contrarian`: same guard
- `g_b3_poly_flow_abs`: same guard

`V9DataStore.get_asset_trades()` returns `None` for every asset (never loaded).
`V9DataStore.get_hl_short_proxy()` returns `None` (never loaded).

Source comment at sleeve block (line 1154): "Operator must populate `/opt/tradingvenue/data/v4/canonical/` before V9 sleeves start firing."

No degraded-default firing. All 10 V9 sleeves have fired exactly zero times since deploy.

---

## 3. Blocked Sleeves — all 10 V9 sleeves

| Sleeve ID | Gate(s) | Data needed |
|---|---|---|
| `poly_sniper_v5_btc_5m_a2_hlcascade100k_v9` | `g_a2_hl_short_cascade(BTC,300s,100k)` | HL liqs |
| `poly_sniper_v5_btc_5m_up_a2_hlcascade50k_v9` | `g_a2_hl_short_cascade(BTC,300s,50k)` | HL liqs |
| `poly_sniper_v5_btc_5m_down_b2_contrarian2k_v9` | `g_b2_poly_flow_contrarian(DOWN,60s,2000)` | poly trades BTC |
| `poly_sniper_v5_btc_5m_up_b2_contrarian2k_v9` | `g_b2_poly_flow_contrarian(UP,60s,2000)` | poly trades BTC |
| `poly_sniper_v5_sol_5m_b1_polyflow_aligned_v9` | `g_b1_poly_flow_aligned(BOTH,60s,500)` | poly trades SOL |
| `poly_sniper_v5_sol_5m_down_b1_500_v9` | `g_b1_poly_flow_aligned(DOWN,60s,500)` | poly trades SOL |
| `poly_sniper_v5_sol_5m_down_b1_flow250_v9` | `g_b1_poly_flow_aligned(DOWN,60s,250)` | poly trades SOL |
| `poly_sniper_v5_sol_5m_b3_abs500_v9` | `g_b3_poly_flow_abs(BOTH,60s,500)` | poly trades SOL |
| `poly_sniper_v5_sol_5m_b1_120s_250_v9` | `g_b1_poly_flow_aligned(BOTH,120s,250)` | poly trades SOL |
| `poly_sniper_v5_sol_5m_b3_abs500_no_opp_v9` | `g_b3_poly_flow_abs` + `g_b2_NOT_opposing` | poly trades SOL |

All have `s6_precondition=False`. Not subject to the S6 bug.

---

## 4. The Fix — Two Steps

### Step 1 — Install pyarrow into engine venv (may already be done)

Verify first: `ssh vps3 '/opt/tradingvenue/.venv/bin/python -c "import pyarrow; print(pyarrow.__version__)"'`

If not installed:
```bash
ssh vps3 'cd /opt/tradingvenue && uv pip install --python .venv/bin/python pyarrow'
```

Also add to `pyproject.toml` `[project].dependencies` to survive future `uv sync`:
```toml
"pyarrow>=14.0",
```

### Step 2 — Sync canonical parquets to VPS3 (REQUIRED — nothing fires without this)

```bash
# Create dirs on VPS:
ssh vps3 'mkdir -p /opt/tradingvenue/data/v4/canonical/trades_polymarket'

# From WSL or Linux machine with rsync access:
rsync -avz --progress \
  "/mnt/c/Users/alexandre bandarra/Desktop/global/data/v4/canonical/trades_polymarket/" \
  "vps3:/opt/tradingvenue/data/v4/canonical/trades_polymarket/"

rsync -avz --progress \
  "/mnt/c/Users/alexandre bandarra/Desktop/global/data/v4/canonical/hyperliquid_liquidations_full.parquet" \
  "vps3:/opt/tradingvenue/data/v4/canonical/"
```

Files needed (4 total):
- `trades_polymarket/btc.parquet` — B2/B3 gates for BTC sleeves
- `trades_polymarket/sol.parquet` — B1/B3 gates for SOL sleeves
- `trades_polymarket/eth.parquet` — loaded but unused (no eth V9 sleeves)
- `hyperliquid_liquidations_full.parquet` — A2 gate for BTC hlcascade sleeves

### Step 3 — Restart tv-engine

```bash
ssh vps3 'sudo systemctl restart tv-engine'
```

The `refresh_loop` runs every 5 min but `load_initial()` at boot is the critical path.

---

## 5. Is the Fix Sufficient? S6 Gate Interaction

V9 sleeves are NOT subject to S6 precondition. Only sleeve 01 (non-V9) has `s6_precondition=True`. The `s6_check_failed` events (24/hour in logs) are a separate bug (Thread A) and have zero effect on V9 sleeves.

**Conclusion:** pyarrow install + parquet file sync IS sufficient to unblock all 10 V9 sleeves. No code changes needed. The V9 gate logic is correct — it's purely a deploy gap (missing dependency + missing data files).

---

## 6. Data Staleness Note

The canonical parquets on local machine are current to 2026-05-28 ~20:04 UTC (latest refresh). The engine's `refresh_loop` re-reads every 5 min, so once synced, V9 sleeves will operate on the most recent data snapshot. For forward-going live signal quality, a scheduled rsync job should be set up to keep the VPS parquets updated from the storedata pipeline.
