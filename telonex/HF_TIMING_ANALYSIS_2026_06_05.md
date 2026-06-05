# HF data timing analysis — "+137s shift" investigation (2026-06-05)

**Report:** for every HF slug, trades AND book run shifted from `resolutions_hf` `slot_start`
and extend past `slot_end` (e.g. nominal 00:00–00:05 → real activity ~00:02:17–00:06:34).

## Verdict: NOT a timing bug. resolutions_hf slot timing is correct. No data rewrite needed.

The observation is two **expected** phenomena, neither a defect:
1. A real ~+80s **tail past slot_end** (post-settlement trading) — universal, present in production too.
2. A **coverage offset of the trentmkelly recorder only** — it captured a 300s slice per market
   shifted to `[slot_start+~80s, slot_end+~80s]`; it never recorded the pre-slot book.

## Evidence

| Check | Result | Implication |
|---|---|---|
| PROD `slot_start_us` vs chainlink `strike_ts_us` (n=46k) | **+0.0s exact** | slug→slot_start convention correct |
| PROD `slot_end_us` vs `settle_ts_us` | **+0.0s exact** | slot boundaries == real strike/settle window |
| slug suffix epoch vs slot_start | **equal** | `int(slug.split('-')[-1]) == slot_start == strike_ts` |
| HF book end-offset vs PROD book end-offset | both **+80s** | HF timestamps correctly time-aligned (a real +Δ error would show ~+160s) |
| trentmkelly btc 5m book final-mid → bmoney outcome | **97.3%** (Down→0.051, Up→0.948) | slug↔data mapping + timing correct (not off-by-one) |
| aliplayer trades vs slot (bnb/doge) | start −7s, end ±8s | aliplayer trades align tightly to `[slot_start, slot_end]` |
| aliplayer BBO vs slot | start −83,800s, end +108s | aliplayer book = full market lifetime (created ~24h early) + tail |

### Per-source coverage (measured, 5m; offsets in seconds relative to slot)
| Source (layer) | book start_off | book end_off | trade start_off | trade end_off | coverage of slug |
|---|---|---|---|---|---|
| **trentmkelly** `orderbook_l25_backfill`/`trades_polymarket_hf` (btc/eth) | +80 (p10 +51 … p90 +110) | +79 (p90 +109) | +80 | +74 | **partial: `[slot_start+~80, slot_end+~80]`** — misses early slot |
| **aliplayer** `canonical_bbo`/`canonical_bbo_trades` (7 coins) | −83,800 (≈market creation) | +108 | ≈ slot_start | ≈ slot_end | book = full lifetime; trades = the slot |
| **production** `orderbook_l25`/`trades_polymarket` (btc/eth/sol) | hours before | +81 | hours before | +83 | full lifetime + tail |

The "~+137s" in the report is a high-tail trentmkelly slug (start_off p90 = +110s, occasional higher);
the median is +80s. Variance = trentmkelly's per-market subscription latency.

## What this means for usage (the "fix" = guidance, not a rewrite)

1. **Do NOT shift any timestamps.** They are correct; shifting would break the 97.3% alignment.
2. **trentmkelly book/trades have NO data in the first ~80s of a slot.** For entry-time / `ws_s` /
   `fire_us` book lookups that fall in `[slot_start, slot_start+~80s]`, trentmkelly will return empty.
   Use **aliplayer BBO** (full pre-slot coverage) or **production L25** for early-slot book.
   trentmkelly is fine for mid-to-late-slot and the settlement region.
3. **The ~+80–110s tail past slot_end is real** (near-resolved 0/1 trading before market close).
   When extracting the "final pre-resolution" book/price, **clamp the lookup to `slot_end`** — do
   not pick the literal last row (it's post-settlement). For "outcome already known" microstructure
   studies, the tail is usable but should be labeled as post-settlement.
4. **aliplayer trades = the clean slot window**; aliplayer BBO needs a `timestamp_us >= slot_start`
   filter if you only want in-window book (otherwise you get ~24h of pre-slot quotes).

## No action on the data files
All timestamps (UTC µs) and `resolutions_hf` slot boundaries are verified correct. The loaders now
carry these coverage notes in their docstrings (`data/v4/canonical/load.py`).
