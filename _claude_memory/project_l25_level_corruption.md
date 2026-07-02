---
name: project_l25_level_corruption
description: canonical L25 (+ source orderbook_snapshots_v2) has price↔size SWAPPED on odd-indexed book levels; level 0 + even levels correct; deep-book reads corrupted but recoverable (swap if price>1)
metadata: 
  node_type: memory
  type: project
  originSessionId: 05cced9b-6087-4f55-b19f-1a29add92555
---

Found 2026-06-16 (Phase-2 delta smoke, `strategy_lab/directional/_phase2_smoke.py`; full writeup `L25_LEVEL_CORRUPTION_2026_06_16.md`).

**The bug:** in the L25 book snapshots, **odd-indexed price columns hold SIZES** (and the matching size cols hold prices) — i.e. levels 1,3,5,… have the (price,size) pair SWAPPED. Level 0 and even levels are correct. Verified in BOTH the live source `orderbook_snapshots_v2` (VPS3) AND the canonical parquet `orderbook_l25/{asset}.parquet`. Evidence: `load_orderbook_l25_streaming` returns ask prices `[0.78, 22.76, 0.79, 40.80, 0.80, 87.61]` — 22.76/40.8/87.61 are sizes, impossible as prices.

**Impact (bounded):** SAFE = level-0 logic (best bid/ask, cross-token spread, small-clip $5-25 fills that fill at L0) → deployed strategies (scalp/sniper/V2) unaffected. CORRUPTED = deep-book reads (full-ladder VWAP, large clips walking past L0, depth analysis, b945 25-level depth-realism, maker-opportunity sizing, the T1/inside-spread "visible in 25-level book" checks) → re-run with de-corruption. Data is RECOVERABLE (stored swapped, not lost).

**De-corruption (validated → 100% valid book):** per level, if price-col >1 swap with size-col (or position-rule: swap odd levels). `price=np.where(P>1,S,P); size=np.where(P>1,P,S)`.

**✅ FIXED IN LOADER 2026-06-16** — `load_orderbook_l25_streaming` now de-corrupts on read: per level swap price↔size where price>1, THEN re-sort each row (asks asc, bids desc) — the corruption was BOTH a price/size swap AND a level-ORDER interleave. SELF-CORRECTING (no-op once source is clean+sorted), non-destructive (no re-pull). Verified: prices all ≤1, ladders monotonic, **0.00% non-monotonic**, 96.9% clean + 0.7% crossed + 2.4% one-sided (both real microstructure). Every backtest via the loader now gets correct books. **Still TODO: STOREDATA root-cause fix** — collector writes corrupted; likely `emit_book_snapshot_row` interleaved 109-tuple order ≠ migration 008 column order in positional `copy_records_to_table`; diff + fix + check extent (writeup `L25_LEVEL_CORRUPTION_2026_06_16.md`). **The new `orderbook_deltas_v2` is CLEAN (different write path).**

**How to apply:** any backtest using L25 levels beyond 0 is suspect until de-corrupted — re-run. Level-0-only logic is fine. Links [[project_offline_feed_blind_to_edge]].
