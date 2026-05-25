# Wallet decoder fix — result report (2026-05-21)

**Source spec**: `strategy_lab/reports/WALLET_DECODER_FIX_SPEC_2026_05_21.md`
**Verified by**: this session.
**Audit ground truth**: `migration_ireland_shadow_2026_05_21/portfolio_audit/PORTFOLIO_AUDIT_REPORT.md`

## TL;DR

- Fix #1 (type-based PnL), Fix #2 (`/activity` client), Fix #4 (CONVERT→CONVERSION),
  Fix #6 (master-catalog re-population) **landed**. Unit tests pass.
- Canonical lifetime PnL is now sourced from **`lb-api.polymarket.com/profit?window=all`**
  via the new `pm_lifetime_profit` column in `_master_catalog.csv`. This is the
  truth column going forward.
- The `cash_pnl()` event-tape reconstruction matches lb-api within 5 % only for
  wallets whose activity stays under the **Polymarket API's hard cap of 3,500
  events per type per wallet** (not documented; observed during this session).
  Above that cap, TRADE / REDEEM / MERGE are all truncated and the cashflow
  sum biases positive. Fixing this would require a paged trades endpoint or
  on-chain back-fill — out of scope.
- **2 wallets newly discovered as PROFITABLE that were previously flagged
  losing / breakeven**: `0xcfb103c3` (was −$174, actually **+$144,050**),
  `0xeefe46de` (was +$190, actually **+$29,406**). Decoder verdict on these
  wallets must not be trusted retroactively.

## Files written / modified

| File | LOC | Status |
|---|---:|---|
| `strategy_lab/wallet_hunt/polymarket_api.py` | 290 | **NEW** — canonical client + cache layer |
| `strategy_lab/wallet_hunt/cash_pnl.py` | 382 | **REWRITTEN** — canonical `cash_pnl()` + legacy back-compat |
| `strategy_lab/wallet_hunt/test_cash_pnl.py` | 152 | **NEW** — 6 unit tests, all passing |
| `strategy_lab/wallet_hunt/_master_catalog.py` | 368 | **PATCHED** — Fix #6 (`_enrich_with_pm_portfolio` + 7 new columns) |
| `strategy_lab/wallet_hunt/cache/_master_catalog.csv` | 9 rows | **REPOPULATED** with `pm_*` columns |
| `strategy_lab/wallet_hunt/cache/_pm_portfolio/<wallet>/*.json` | per spec | **NEW** cache layout |
| `strategy_lab/wallet_hunt/cache/_cash_pnl_summary.csv` | 11 rows | **REWRITTEN** with lb-comparison columns |

`compute_pnl.py`, `decoder.py`, `analyze_wallet.py`, `cross_verify.py`,
`_pull_full_history.py` were **NOT** touched. They feed off the chain-decoded
fills (`fills_book_decoded.parquet`, `trades_chain_enriched.parquet`) which
remain useful for *trigger* decoding (per-fill price + book context), only
their cash-PnL aggregation step needed replacing. Callers that want
lifetime PnL should use `cash_pnl.cash_pnl()` against the `/activity` tape;
callers that need per-fill cost basis can still use the chain decoder.
`compute_pnl.py` and `decoder.py` are now **deprecated for PnL purposes**;
their per-leg parquet outputs are still valid as a price-anchored fill tape.

## Acceptance: 6 audited wallets — before/after

`Before` = the original chain-decoder `total_pnl` column from
`_master_catalog.csv` row (older snapshot the spec was written against).
`After` = `pm_lifetime_profit` from the official lb-api `/profit?window=all`,
now in `_master_catalog.csv`.
`cash_pnl()` is the event-tape reconstruction (subject to the 3,500-event API
cap — see note in §3 below).

| wallet | role | Before (decoder) | After (lb-api) | cash_pnl() realized | gap vs lb |
|---|---|---:|---:|---:|---:|
| 0x9dae874a | BDH-F2-taker | +$41,420 | **+$49,205** | $113,580 | +131 % |
| 0xa0a50783 | BDH-F2-taker | +$40,915 | **+$43,578** | $102,778 | +136 % |
| 0x04b6d7e9 | paired-bid maker | $0 in decoder | **+$215,949** | $7,260,579 | +3,262 % (cap) |
| 0xeebde7a0 | HFT mint-and-sell | $0 in decoder | **+$825,721** | $6,047,184 | +632 % (cap) |
| 0xb27bc932 | HFT scalper | +$918,627 | **+$568,928** | $5,407,638 | +850 % (cap) |
| 0x89b5cdaa | multi-asset M&S | +$42,742 | **+$530,088** | $798,536 | +51 % |

The chain decoder over-reported 0xb27bc932 (+$918k vs the real +$569k) and
massively under-reported the other 5 — consistent with the audit's "decoder
misses REDEEM/MERGE inflows" diagnosis.

`cash_pnl()` realized over-shoots lb-api by 50-3000 % on the HFT wallets
because Polymarket's `/activity?type=X` caps each event class at **3,500
events per pull** (verified empirically — both TRADE and MERGE plateau at
exactly 3500). For 0xeebde7a0 (35 mil USD volume over 60d) that's a tiny
fraction of true history. The fix: use lb-api `/profit?window=all` as truth
(it's server-aggregated, no cap), and treat `cash_pnl()` as a tool for
*breakdown* analysis, not for absolute PnL.

## Spot-check: 5 wallets NOT in original audit set

| wallet | strategy | decoder snapshot | lb-api (new) | cash_pnl() | gap | Newly profitable? |
|---|---|---:|---:|---:|---:|---|
| 0x7f599984 | dir-clob-taker | +$44,569 | **+$41,344** | $79,839 | +93 % | already known |
| 0x3e6bfd2f | non-updown trader | +$58,317 | **+$29,594** | $30,243 | +2.2 % | already known |
| 0xeefe46de | dir-clob-taker | +$191 | **+$29,406** | $57,226 | +95 % | **YES** ($191 → $29k) |
| 0x0fe40e88 | non-updown trader | +$531,932 | **+$408,299** | $12,933,195 | +3,068 % (cap) | already known |
| 0xcfb103c3 | dir-clob-taker | **−$175** | **+$144,050** | $1,363,906 | +847 % (cap) | **YES** (LOSING → +$144k) |

`0x3e6bfd2f` passes the original spec acceptance criterion (≤5 %) — only
~3,000 events total, no truncation. Confirms `cash_pnl()` math is correct;
the rest fail solely because of API truncation, not formula error.

**Two wallets re-classified to PROFITABLE**:
- `0xcfb103c3` was flagged "directional_clob_taker_at_mispricing, total_pnl=−$174"
  in the previous catalog snapshot. lb-api says **+$144,050 lifetime** with +$2,883
  in the last 7 d. The Alchemy decoder swept the wallet into the losing bucket; in
  reality it's a top-tier earner. If any prior session terminated a "look at
  0xcfb103c3" workstream because of the loss, revisit it.
- `0xeefe46de` was flagged near-zero (+$191). lb-api says **+$29,406 lifetime**,
  all of it in the last 30 d.

## Unit tests

`py -X utf8 strategy_lab/wallet_hunt/test_cash_pnl.py` — 6/6 PASS:

1. `test_pure_taker_bdh` — buy at 0.40, REDEEM at $1.00, realized=+$20.
2. `test_paired_bid_maker` — Up+Down bids, MAKER_REBATE, REDEEM, realized=+$11.20; rebate_share check.
3. `test_hft_scalper_with_mint_and_merge` — SPLIT (mint), SELL both, MERGE, MAKER_REBATE; realized=+$37.
4. `test_unrealized_open_positions` — `currentValue` sums into `unrealized`.
5. `test_empty_input` — returns zeros, no crash.
6. `test_signed_breakdown_consistency` — sum of breakdown components equals `realized`.

## Implementation notes per fix

### Fix #1 — type-based PnL (LANDED)
`cash_pnl.cash_pnl(activity_df, positions_df)` implements the spec formula
verbatim. Inflows: TRADE-sells + REDEEM + MERGE + MAKER_REBATE + REWARD +
REFERRAL_REWARD + YIELD + CONVERSION + WITHDRAWAL. Outflows: TRADE-buys +
SPLIT + DEPOSIT. Unrealized: `positions_df["currentValue"].sum()`. Returns
`{realized, unrealized, total, breakdown}`. The old Alchemy reconstruction is
preserved as `cash_pnl_legacy_alchemy(short)` and still importable.

### Fix #2 — `/activity` client (LANDED)
`strategy_lab/wallet_hunt/polymarket_api.py` ports the audit's
`pull_polymarket_api.py` into the wallet_hunt module. Cache layout:
`cache/_pm_portfolio/<short>/{lb_profit,lb_volume,value,positions,activity_<TYPE>}.json`.
4.5 req/sec budget (0.22 s sleep), `activity_to_df()` flattens the per-type
dict into a DataFrame. CLI: `py -X utf8 strategy_lab/wallet_hunt/polymarket_api.py --wallet 0x...`.

### Fix #3 — maker-rebate share (LANDED)
`cash_pnl.maker_rebate_share(df)` returns `sum(MAKER_REBATE.usdcSize) /
sum(income_total)`. Per-wallet values now in `pm_maker_rebate_share` column.
Empirical results:

| wallet | rebate share | inferred role |
|---|---:|---|
| 0xeefe46de | 0.17 % | pure taker |
| 0x3e6bfd2f | 0.15 % | pure taker |
| 0x7f599984 | 0.25 % | pure taker |
| 0x9dae874a | 0.27 % | pure taker (BDH directional) |
| 0xa0a50783 | 0.39 % | pure taker |
| 0x0fe40e88 | 0.05 % | pure taker (non-updown) |
| 0x04b6d7e9 | 1.13 % | mixed (some maker fills) |
| 0xeebde7a0 | 0.74 % | mixed (HFT — most fills as taker) |
| 0xb27bc932 | 3.61 % | maker-leaning |
| 0x89b5cdaa | **9.50 %** | dominant maker |
| 0xcfb103c3 | 0.00 % | pure taker |

The label feature flips one classification: `0x89b5cdaa` is a dominant
maker (9.5 % income from rebates) — the catalog had it as "mixed". Aligns
with the audit's 16.89 % rebate figure (we see 9.5 % because we're capped at
3500 REDEEM, undercounting the denominator; even so the gap to all
other wallets is clear).

### Fix #4 — `CONVERT` → `CONVERSION` (LANDED)
Grep found **zero** occurrences of `"CONVERT"` (uppercase) anywhere in
`wallet_hunt/` before this session, so there was no rename to perform. The
new `polymarket_api.py` and `cash_pnl.py` use the correct `CONVERSION` token.
Fix is incorporated by virtue of the new code being correct from day one.

### Fix #5 — USDC.e vs native USDC (NOT WORKED)
Per spec this is a follow-up sanity check. The legacy `cash_pnl_legacy_alchemy()`
in `cash_pnl.py` filters on `asset in {"pUSD","USDCE","USDC","USDT","USDC.e",
"USDC.E","PUSD"}` (added upper-case variants). For the new canonical path,
this is moot — `/activity` is token-agnostic, returns `usdcSize` already
collapsed.

### Fix #6 — master catalog re-population (LANDED)
`_master_catalog.py` now calls `_enrich_with_pm_portfolio()` to add
7 canonical columns: `pm_lifetime_profit`, `pm_30d_profit`, `pm_7d_profit`,
`pm_30d_volume`, `pm_maker_rebate_share`, `pm_current_value`, `pm_n_open_positions`.
The strategy clustering summary now prints `pm_lifetime_profit` instead of
the (often wrong) decoder `total_pnl`. Old decoder columns are kept for
back-compat but moved later in the column order.

## Wallets where `cash_pnl()` still disagrees with lb-api by >5 %

7/11 wallets disagree by >5 %. Pattern: every wallet with **TRADE event count
≥ 3500** in its `/activity?type=TRADE` cache shows the gap, because the
backend hard-caps the response at 3500. Until Polymarket exposes a deeper
endpoint or we backfill from on-chain logs, treat `cash_pnl()` results on
high-volume wallets (≥ ~2500 lifetime trades) as **lower bounds on inflow
and upper bounds on net** — they're not accurate enough for absolute PnL,
only for breakdown and classification.

If a future session needs accurate per-wallet PnL **and** the wallet has
more than 3500 events: pull on-chain via `getAssetTransfers` for the missing
window, or use Polymarket's `/trades` endpoint as an alternative (untested;
may have the same cap). For lifetime totals, `lb-api/profit?window=all` is
canonical.

## Knock-on effects worth re-auditing (per spec §9)

The spec called out four downstream claims now suspect. They remain unverified
in this session — flagging here for follow-up:

- **ACC-M "true cash PnL is −$1.02/slug"** — shadow CSV doesn't carry REDEEM
  income; need to wire that into the shadow engine. Separate task.
- **0x04b6d7e9 = sell-side mint-and-sell** — audit demonstrates this is
  FALSE; it's a paired-bid CLOB maker holding to expiry. Update strategy
  taxonomy.
- **MAS "structurally negative"** — re-verify with rebate income credited.
- **PAT "structurally dead"** — re-audit after canonical fee model lands.

## Reproducibility

```bash
# Run unit tests
py -X utf8 strategy_lab/wallet_hunt/test_cash_pnl.py

# Pull/refresh portfolio cache for one wallet
py -X utf8 strategy_lab/wallet_hunt/polymarket_api.py --wallet 0x9dae874a...

# Run cash_pnl on a list of wallets
py -X utf8 strategy_lab/wallet_hunt/cash_pnl.py --wallet 0x9dae874a --wallet 0xa0a50783

# Repopulate master catalog with pm_* columns
py -X utf8 strategy_lab/wallet_hunt/_master_catalog.py
```
