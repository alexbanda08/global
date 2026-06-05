# HF aliplayer backfill — follow-up session (2026-06-05b)

Continued the `HF_BACKFILL_DONE_2026_06_05.md` task list. **Headline: the aliplayer dataset
is FROZEN — `lastModified 2026-04-26`, data ends 2026-04-21.** The handoff's assumption that
"aliplayer auto-updates every 3h → covers Apr 21 → today" is OUTDATED. This re-scopes Tasks 2 & 3.

## Task 1 — Resolutions for all 7 coins ✅ DONE
- Pulled `aliplayer1/polymarket-crypto-updown` `data/markets.parquet` (104,668 markets, 7 coins).
- Resolved rows: **31,848** (resolution 1=Up / 0=Down / -1=unresolved). Resolved window =
  **Apr 6 → Apr 21 2026** only (older markets carry resolution=-1 in the snapshot).
- Derived canonical slug uniformly from `end_ts - window` (slug col is human-readable for 1h/4h;
  verified for 5m/15m: `end_ts - window == slug-suffix epoch == slot_start`).
- Appended to `canonical/resolutions_hf.parquet`: **32,880 → 64,728 rows**. Zero overlap with
  bmoney (bmoney = Jan 2→Mar 24; aliplayer = Apr 6→21) so no agreement cross-check possible.
- **Newly added coins: BNB 4,295 / DOGE 4,403 / HYPE 4,082** (plus btc/eth/sol/xrp Apr 6-21).
- Final per-coin: btc 17,322 / eth 16,570 / sol 9,063 / xrp 8,993 / doge 4,403 / bnb 4,295 / hype 4,082.
- Script: `telonex/append_resolutions_ali.py`.

## Task 2 — Extend BBO+trades Apr 22 → today ❌ IMPOSSIBLE (hard limit)
- Aliplayer is **frozen at Apr 21** (`lastModified 2026-04-26`). Existing `D:\global_data\canonical_bbo\`
  already covers **Mar 30 → Apr 21 for all 7 coins** = the dataset's full extent. Orderbook WS
  recording began Mar 30 (no earlier data; can't help the Mar 24-30 gap either).
- **Nothing to pull/append.** The Apr 21 → now BBO for the non-VPS3 coins (BNB/DOGE/HYPE/XRP)
  does not exist in this source. BTC/ETH/SOL ongoing top-of-book is covered by production L25 (Apr 22+).

## Task 3 — Cross-validate production vs HF ❌ NO OVERLAP (then salvaged internally)
- Production stack starts **Apr 22+** (resolutions Apr 22 15:45, chainlink Apr 24 01:40,
  trades Apr 26 12:46); aliplayer ends **Apr 21 00:26**. **Zero temporal overlap** → cannot
  compare resolutions/trades/book against production.
- Salvaged as an **internal aliplayer BBO↔resolution consistency check** (validates the HF data
  we keep for the non-collected coins):
  - Slugs join correctly — directional signal is right: Up-outcome markets have higher final
    Up-token mid (avg **0.526**) than Down-outcome (avg **0.475**). If mislabeled, both would be ~0.50.
  - BBO records ~**108s past slot_end** (captures settlement tail).
  - BUT minor-coin books (BNB/HYPE/DOGE) are **thin**: final Up-mid median/q25/q75 all = **0.5**
    (book sits at the 0.5 default); only ~110/2117 markets per coin actually moved to >0.9.
  - **Verdict:** HF data is internally consistent and correctly linked, but BNB/DOGE/HYPE BBO has
    limited microstructure depth — usable for the subset of markets that actually traded.

## Task 4 — Fix 1970-01-01 trades bug ✅ DONE
- `canonical_bbo_trades` epoch-0 rows (aliplayer ticks with `timestamp_ms=0`): btc 183,706 (2.9%),
  eth 286,863 (3.8%), sol 177,987 (4.4%), xrp 2; bnb/doge/hype clean.
- Cleaned all files in place (rewrite, keep `timestamp_us > 2025-01-01`): btc 6.34M→6.15M,
  eth 7.52M→7.23M, sol 4.02M→3.84M, xrp →1,029,214. Script: `telonex/fix_1970_trades.py`.
- Hardened against recurrence:
  - `telonex/aliplayer_convert_duck.py` ticks query now `WHERE timestamp_ms > 1735689600000`.
  - `load.py::load_trades_hf(bbo=True)` filters `timestamp_us > 2025-01-01` on read.

## Net state
- `resolutions_hf.parquet`: 64,728 real outcomes, all 7 coins, Jan 2→Mar 24 (bmoney) + Apr 6→21 (aliplayer).
- `canonical_bbo` / `canonical_bbo_trades`: unchanged window (Mar 30→Apr 21), trades de-1970'd.
- Coverage gaps that NO free source fills: **Mar 24-30** (~6 days), **Apr 21-22 seam**, and any
  ongoing BBO for BNB/DOGE/HYPE/XRP after Apr 21.
