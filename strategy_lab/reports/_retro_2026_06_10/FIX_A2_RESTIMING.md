# FIX-A2 — `resolutions_hf` slot-timing re-investigation (2026-06-10)

**Verdict: the resolutions_hf slot timing is ALREADY CORRECT. There is no offset to apply.**
The prior spec's hypothesis (bmoney rows are shifted +74–150s) is **REFUTED by data**. The real,
unfixable-by-relabel issue is that the **trentmkelly L25 backfill books start ~75s late** inside an
otherwise-correctly-labelled window (diagnosis **B**, not A or C). The fixed file is a faithful
passthrough tagged `timing_offset_applied_s=0`.

---

## 1. slot_start vs slug-suffix — EQUAL (no offset)

`int(slug.rsplit('-',1)[1]) * 1e6 == slot_start_us` for **all 64,728 rows** (offset distribution: single
value `0.0`, std 0). Window lengths exact: 5m→300s, 15m→900s, 1h→3600s, 4h→14400s. So the slug→epoch
mapping in `resolutions_hf` is internally consistent and `slot_start_us` is exactly the slug's declared
slot-open second. **Task-1 diagnosis (A) "label/clock offset in resolutions_hf" is ruled out at the
suffix level.**

## 2. Outcome-agreement sweep — argmax = +0s for EVERY group

For BTC/ETH/SOL, 5m+15m, I computed the binance-implied outcome `sign(close@(slot_end+off) −
close@(slot_start+off))` from `klines_1s.parquet` and measured % agreement with the stored `outcome`,
across offsets `{-150…+150}s`. **Agreement peaks sharply at offset 0 and decays monotonically both
directions** — the signature of a *correct* mapping (the residual 4–11% disagreement is the known
chainlink-vs-binance split on near-flat windows, which grows as you move off the true window).

| source            | tf  | argmax offset | agree@argmax | agree@0s | agree@+74s | agree@−74s |
|-------------------|-----|---------------|--------------|----------|------------|------------|
| bmoney1321-real   | 5m  | **+0s**       | **95.0%**    | 95.0%    | 74.1%      | 75.0%      |
| bmoney1321-real   | 15m | **+0s**       | **89.1%**    | 89.1%    | 79.7%      | 81.4%      |
| aliplayer1-real   | 5m  | **+0s**       | **94.4%**    | 94.4%    | 72.8%      | 75.6%      |
| aliplayer1-real   | 15m | **+0s**       | **96.5%**    | 96.5%    | 83.5%      | 88.0%      |

Sanity check PASSED: aliplayer (Apr6–21, used successfully for the scalp OOS) peaks at 0 — and so does
**bmoney**. If the bmoney rows carried a +74–150s label offset, bmoney's argmax would sit at that
offset; instead it is dead-on 0 with 95% agreement. **The bmoney outcomes are settled against exactly
`[slot_start, slot_end]` as stored. (A) is fully refuted; nothing to recompute.**

Full sweep table: `_sweep_offset_result.csv` (15 offsets × 4 groups).

## 3. Book-coverage check — books start ~75s into a correct window (diagnosis B)

200-slug BTC + 200-slug ETH bmoney sample, scanning `orderbook_l25_backfill/{btc,eth}.parquet` for the
seconds each slug's book is present, **anchored on the (unchanged, correct) `slot_start_us`**:

| metric                                   | BTC (n=200) | ETH (n=200) |
|------------------------------------------|-------------|-------------|
| slugs with any book                      | 90%         | 100%        |
| book_start − slot_start (median)         | **+75s**    | **+77s**    |
| book_start − slot_start (p10 / p90)      | +47 / +108s | +49 / +108s |
| **coverage at slot_start + 5s**          | **0.0%**    | **0.0%**    |
| coverage at slot_start + 30s             | 0.0%        | 0.0%        |
| coverage at slot_start + 60s             | 26.0%       | 26.0%       |
| coverage at book_start + 5s (re-anchored)| 88.0%       | 98.5%       |

The book and trades agree with each other (per the spec) and sit ~75s into the window because the
trentmkelly backfill only captured MM quoting once it ramped — **a genuine late-quoting / late-capture
property of that backfill, NOT a label error.** The window itself is correct (offset-0 outcome proof).

## 4. What was "fixed"

`data/v4/canonical/resolutions_hf_timingfix_2026_06_10.parquet` — original schema + `slot_start_us` /
`slot_end_us` **unchanged**, plus `timing_offset_applied_s = 0` for all rows. No group had an unambiguous
nonzero offset (every group's argmax is 0), so per the "only fix unambiguous groups" rule, **all rows
pass through untouched**. The original `resolutions_hf.parquet` is not overwritten.

## 5. Book-coverage verdict — CAN the open-scalp be tested on Feb21–Mar24 at +5s?

**No.** Coverage at `slot_start+5s` is **0%** and at `+30s` is **0%**; the backfill books do not exist
until ~+47–108s (median +75s). The open-anchored +5s scalp is **untestable on this Feb21–Mar24 backfill**
— a data-availability ceiling, not a relabel problem.

- Re-anchoring to `book_start+5s` gives **88% (BTC) / 98.5% (ETH)** fill, BUT that is exactly the
  **confounded** path the spec warns about (§ "What this breaks"): the outcome is defined on
  `[slot_start, slot_end]` while you'd be firing the 5s-lag at a shifted t0 ~75s later → lag↔outcome
  alignment is broken, result unusable. Do **not** use book-relative anchoring for an OOS edge claim.
- Earliest the open-scalp *could* fire on this data is **slot_start+60s (26% coverage)** — too sparse and
  too late to represent the production +5s edge.

**Conclusion:** Feb21–Mar24 trentmkelly L25 cannot serve as the open-scalp's disjoint-window OOS. The
already-validated OOS stands on the aliplayer Mar30–Apr21 BBO (`load_orderbook_bbo`, offset-0 confirmed
here, books present at +5s). For a *different* disjoint window, a backfill whose books exist at
strike+5s is required (e.g. a 6-month API pull with books+trades+klines, per the Jun-04 handoff), not a
re-timing of resolutions_hf.

## 6. How to load the fixed file

```python
import sys; sys.path.insert(0, "data/v4/canonical")
import pyarrow.parquet as pq
res = pq.read_table("data/v4/canonical/resolutions_hf_timingfix_2026_06_10.parquet").to_pandas()
# identical to resolutions_hf.parquet + a `timing_offset_applied_s` column (all 0).
# slot_start_us IS the true strike; slot_end_us IS the true settle. Use as-is.
```

Reproduction scripts (repo root): `_diag_restiming.py` (suffix check), `_sweep_offset.py`
(agreement sweep → `_sweep_offset_result.csv`), `_book_cov.py` (coverage scan), `_write_fix.py`.
