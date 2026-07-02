---
name: project_sleeve_pnl_metric
description: "Rank sleeves on the TV dashboard dedup metric, NOT raw trading.events pnl_usd (it double-counts + inflates)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9eb8ff90-baef-4a06-95c1-dd7a28ecaa37
---

When ranking/auditing tradingvenue sleeve profitability on vps3 `storedata.trading.events_*`, do NOT sum raw `data->>'pnl_usd'` — it OVERSTATES badly. Each trade emits TWO `poly_updown_resolution` rows with the same `condition_id` (a real `fill_method='l25_walk'` / `event_type='sleeve_fire_resolved'` row + a legacy on-chain resolver row `fill_method=NULL` ~60s later), and there are `fill_method='synthetic'` placeholder fires that were never fillable on the live book.

Use the TV **dashboard metric** (the ground truth, `GET /sleeves/stats` in `/opt/tradingvenue/backend/app/api/sleeves.py`): dedup to one authoritative row per `(sleeve_id, condition_id)` via `_RESOLUTION_DEDUP_ROW_NUMBER` (~sleeves.py:1330) AND exclude `COALESCE(data->>'fill_method','')='synthetic'`. It trusts the stored `pnl_usd` (already 0.07-curve), so no fee recompute needed — the fix is dedup + synthetic-exclusion.

**Worked proof (2026-06-07):** `poly_fast_taker_lagv2_btc_5m` = raw +$1,681 / 89% WR (looked great) → deduped **−$195, t=−0.48** (the +$1,921 from phantom legacy dup rows was fake; real l25_walk fills −$240). Matches the dashboard's loss. The whole `lagv2` + `mint_sell` (replay-only) families collapse under the corrected metric. 89% WR + net loss = textbook **WR≠edge**. Related: [[feedback_subagent_model]]. GROUND-TRUTH RULE — verify sleeve PnL against the dashboard/live wallet, never the raw paper events.
