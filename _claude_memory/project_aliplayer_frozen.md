---
name: project_aliplayer_frozen
description: "The HF aliplayer Polymarket BBO dataset is frozen at Apr 21 2026, not auto-updating"
metadata: 
  node_type: memory
  type: project
  originSessionId: d1852a20-0e96-4e2d-bb1c-a27e957eed3d
---

The HuggingFace dataset `aliplayer1/polymarket-crypto-updown` is **FROZEN** — `lastModified
2026-04-26`, data ends **2026-04-21 00:26**. The `HF_BACKFILL_DONE_2026_06_05.md` handoff's
claim that "aliplayer auto-updates every 3h → covers Apr 21 → today" is OUTDATED/false.

Consequences (verified 2026-06-05):
- Existing `D:\global_data\canonical_bbo\` (Mar 30→Apr 21, 7 coins) is already the dataset's
  FULL extent — nothing more to pull. No ongoing BBO for BNB/DOGE/HYPE/XRP after Apr 21 exists anywhere.
- Resolved markets in `markets.parquet` only span Apr 6→21 (older = resolution=-1). These were
  appended to `resolutions_hf.parquet` (now 64,728 rows, all 7 coins incl BNB/DOGE/HYPE).
- Cannot cross-validate vs production: production stack starts Apr 22+ → ZERO overlap with aliplayer (≤Apr 21).

Session writeup: `telonex/HF_BACKFILL_SESSION_2026_06_05b.md`. Related: [[feedback_canonical_refresh]].
