# 🔴 Canonical L25 deep-level corruption (price↔size swapped on odd levels)
**2026-06-16. Found during the Phase-2 delta smoke. Verified in BOTH the live source table (`orderbook_snapshots_v2`, VPS3) AND the canonical parquet (`orderbook_l25/{asset}.parquet`).**

## The bug
In the L25 book snapshots, **odd-indexed price columns contain SIZES** (and the matching size columns contain prices). Level 0 and all even levels are correct.

Evidence — canonical `load_orderbook_l25_streaming('btc', …)`, one snapshot:
```
ask prices[0][:6] = [0.78, 22.76, 0.79, 40.80, 0.80, 87.61]   # idx 1,3,5 are SIZES, not prices
ask sizes [0][:6] = [137.3,  0.9, 144.6,  0.9, 128.8,  0.9]   # idx 1,3,5 are PRICES (~0.9)
```
22.76 / 40.80 / 87.61 are impossible as prices (prices ∈ (0,1]). Even indices (0.78, 0.79, 0.80) form a valid monotonic ladder. Same in the live `orderbook_snapshots_v2` (raw row: `bid_price_1 = 230.9`, `bid_size_1 = 0.49`). So per level: **levels 1,3,5,… have the (price,size) pair swapped.**

## Impact (bounded)
- **SAFE: level-0 logic** — best bid/ask, cross-token spread, small-clip ($5–25) book-walk fills that fill at level 0. These read level 0 (correct), so **deployed strategies (scalp/sniper/V2) are unaffected.**
- **CORRUPTED: deep-book reads** — full-ladder VWAP, large clips that walk past level 0, depth analysis, the b945 25-level depth-realism sims, the maker-opportunity sizing, and the "is price visible in the 25-level book" checks (T1 feed-loss / inside-spread) — these read odd levels and got sizes-as-prices (which silently don't match real prices → inflate "invisible" / break VWAP). **Re-run these with de-corruption.**
- **Data is RECOVERABLE** — not lost, just stored swapped.

## De-corruption rule (validated: makes the book 100% valid)
Per level, if the **price-column value > 1**, swap it with the size-column (equivalently: swap odd-indexed levels). After this, the smoke's reconstructed book was 100% `0<bid<ask<1`, spread +0.010.
```python
swap = price_col > 1.0
price = np.where(swap, size_col, price_col); size = np.where(swap, price_col, size_col)
```
(Caveat: value-rule mis-handles a genuine fractional size <1 at a corrupted level — rare. The position-rule "swap odd levels" is more robust; storedata should confirm the exact pattern. The real fix is at the source so no de-corruption is needed.)

## Two fixes
1. **STOREDATA (root cause):** the collector writes `orderbook_snapshots_v2` corrupted. Likely a mismatch between `emit_book_snapshot_row`'s interleaved 109-tuple `(bid_price_0, bid_size_0, bid_price_1, …)` and the table column order (migration `008_orderbook_snapshots_v2.sql`) used by `copy_records_to_table` (positional). Diff the emit order vs the schema column order; fix so odd levels align. Check the extent (all history vs since a date). **Note: the new `orderbook_deltas_v2` is CLEAN — different write path (one row per change) — so the maker/queue thread is unaffected.**
2. **CANONICAL loader (stopgap so existing parquet is usable now):** add the de-corruption swap in `load_orderbook_l25_streaming` (after reading cols_ap/as/bp/bs, swap per-level where price>1) so every existing deep-book backtest reads correct levels without a re-pull.

## Provenance
Found by `strategy_lab/directional/_phase2_smoke.py` (de-corrupted keyframe + clean deltas → 100% valid book) + the column probes. The clean delta table validated separately (prices 0.001–0.999, 143/s).
