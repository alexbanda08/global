# Feedback — canonical data refresh source & workflow

Corrected by user 2026-05-28.

## Architecture
- **Ireland VPS** (`ssh vps_ireland`, code `/opt/tradingvenue/`) = **live trades +
  maker-arb shadow execution ONLY. NO data collector.** Its only data output is
  the maker shadow CSVs (`/var/log/tv/maker/*.csv`) and live trade logs.
- **Canonical market data is refreshed from the VPS3 storedata collector**
  (`ssh vps3`, postgres db `storedata`): chainlink RTDS (`oracle_prices_v2`),
  resolutions (`market_resolutions_v2`), binance klines (`binance_klines_v2`),
  polymarket trades (`trades_v2`), `trading.events`, L25 (`orderbook_snapshots_v2`), HL.
- **Never propose pulling canonical market data from Ireland.** To settle/resolve
  anything against truth, refresh canonical from VPS3, not by re-pulling Ireland CSVs.

## Refresh workflow (single-source invariant)
1. Clone `migration_<prev>/` non-L25 scripts → `migration_<TAG>/`, bump `TAG` + `T_START_US`.
2. Pull on VPS3 → convert → merge into `canonical/` (append+dedup; resolutions
   full-replace; rebuild `resolutions_from_rtds`).
3. **DELETE the downloaded `data/v4/refresh_<TAG>/` dir** (and VPS3 `/tmp/v3_delta_<TAG>`)
   after merge — never leave the delta tables around to avoid duplicated data.
   The `migration_<TAG>/` scripts stay as the persistent record.
- Playbook lives in `data/v4/canonical/README.md`. Read it before refreshing.
- `python` is not on PATH locally — use `py -X utf8`.
