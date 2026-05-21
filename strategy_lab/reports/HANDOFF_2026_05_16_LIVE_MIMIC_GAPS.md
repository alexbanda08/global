# Handoff — live-mimic engine fidelity gaps + next steps
_Generated: 2026-05-16. Target reader: next-session backtest/engine agent._
_Supersedes my prior open-items list in `EXTERNAL_REPO_COMPARISON_evan_kolberg_pmxt_2026_05_12.md` after reading work done in subsequent sessions._

---

## TL;DR

1. **Step 2 from the May-10 handoff IS done.** A subsequent session built `strategy_lab/meta_classifier/momo_full_universe_canonical.py` — uses production-correct `ws_s = slug_suffix − window_s`, runs 15 variants × 23,553 chainlink-resolved markets × 18 days, written up in `MOMO_FULL_UNIVERSE_2026_05_16.md`. **Every variant lost over the full window. Permutation: not significant for any variant.** The +PnL we used to see was a window effect, not edge.

2. **Bigger finding from commit `0211074` (May 6) that reframes everything**: production momo's "live paper PnL" was a **REST-staleness artifact**. Production fires at `slug_ws + 120s` right after a high-vol Binance print; Polymarket's REST `/book` lags VPS2 WS L25 ground truth by **$0.19–0.32**. Production was filling at stale (favorable) prices that wouldn't actually be available. Our canonical L25 backtest uses WS truth — that's why backtest shows no edge while production looked profitable. See `MOMO_REST_LAG_VS_MICROSTRUCTURE.md`. **Backtest is more faithful to live-WS than production-REST ever was.**

3. **The PMXT steals (`fees.py`, `latency.py`, `clob_resolutions.py`, `book_filters.py`, `pair_arbitrage/scan_canonical.py`) all EXIST but are NOT WIRED INTO ANY BACKTEST.** `grep poly_taker_fee strategy_lab/` returns 0 hits outside `fees.py` itself. `load.py` has no CLOB integration. `momo_full_universe_canonical.py` still uses "2% on profit only" and zero latency.

4. **The "live mimic" job is now precisely defined**: take the backtest engine that already gets the anchors right + uses WS L25 truth, and add the 3-4 production-realism gates we haven't wired (real fees, latency, sparse-market filter, exit-side WS lookup). That gives us a backtest that predicts what the LIVE-WS production will look like once TV agent migrates off REST.

5. **Highest-value undone items** (priority order):
   - **#1**: Wire `latency.py + fees.py + book_filters.py` into `momo_full_universe_canonical.py` → re-run, compare to current numbers. **<2h.** Tells us whether the apparent ~$0/trade is actually breakeven or negative once fees are correctly priced.
   - **#2**: Add `with_clob_winner=True` to `load_resolutions()` and run full 18k CLOB crosscheck (checkpointed). Validates our outcomes match what Polymarket actually paid. **<1h once checkpoint added.**
   - **#3**: Build the "live-mimic" config flag everywhere — `LIVE_MIMIC_MODE=1` → applies fee_curve + latency + min_book_events + ws-only book. Default off so old reports remain reproducible. **<3h.**

---

## What was done after my last handoff (chronological)

### From the May-10 ws_s handoff (now resolved)

| Item | Status | Where |
|---|---|---|
| Step 2: Rewrite buggy backtests | ✅ DONE | `momo_full_universe_canonical.py` (15 variants × 23,553 markets) |
| Anchor-correct universe | ✅ DONE | `gated_universe.csv` 5,703 rows, `per_trade.csv` 43,635 rows |
| Walkforward permutation test | ✅ DONE | report section "Permutation test" |
| Step 3: `_xref_live.py` re-run | ⚠️ PARTIAL | Phase 3+4 already matches May 7 prod within $0.07/tr, but no formal re-xref against the new full-universe results |
| Step 4: addendum on old reports | ❌ NOT DONE | 6 reports still claim inflated numbers; readers will be misled |
| Step 5: tighter-gate sweep | ❌ NOT DONE | Per-cell winners report exists but no q95/q99 sweep |

### From this canonical/PMXT-steal session (artifacts exist, integrations don't)

| Path | Status | Wired into any backtest? |
|---|---|---|
| `strategy_lab/fees.py` | ✅ exists | ❌ no — grep shows 0 imports outside file itself |
| `strategy_lab/latency.py` | ✅ exists | ❌ no |
| `strategy_lab/book_filters.py` | ✅ exists | ❌ no |
| `data/v4/canonical/clob_resolutions.py` | ✅ exists | ❌ no — `load.py` has no `with_clob_winner` |
| `data/v4/canonical/clob_resolutions_cache.parquet` | 150 markets | not used downstream |
| `strategy_lab/pair_arbitrage/scan_canonical.py` | ✅ runs end-to-end | ❌ never run beyond 20-slug smoke test |
| `data/v4/canonical/load.py` ws_s helpers (`slug_to_ws_s`, `add_ws_s`, `ret_2m_at_ws`) | ✅ exists | ✅ used by `momo_full_universe_canonical` |

### Major new finding: REST-lag (commit `0211074`, May 6)

**Production momo's paper PnL was fictitious.** From `MOMO_REST_LAG_VS_MICROSTRUCTURE.md`:

> Momo fires at `slug_ws+120s` (immediately after a high-vol Binance print), where Polymarket REST `/book` is $0.19–0.32 stale vs VPS2 WS L25 ground truth. Sniper/V3/V4/inverse/volume fire at bar-close and show <$0.04 REST-vs-WS divergence — paper PnL there is real and live-tradeable.

Implications:
- Killed live momo deploy (production was about to lose ~30¢/trade once REST gap closed).
- Non-momo sleeves (sniper, v3, v4, inverse, volume) unblocked for live transition.
- TV agent has the spec: `TV_AGENT_LIVE_TRANSITION_SPEC.md` for migrating production from REST to WS book.
- Our backtest engine is the SOURCE OF TRUTH — production is the one that needs to migrate to match the backtest.

---

## Live-mimic engine fidelity — gap analysis

### What our current backtest engine already does right

| Aspect | Backtest | Matches production? |
|---|---|---|
| Anchor | `ws_s = slug_suffix − window_s` | ✅ matches prod `build_bar_context_t_plus_120` |
| Signal source | Binance spot WS 1MIN bars | ✅ matches prod momo controller |
| Outcome truth | Chainlink RTDS (locally derived) | ✅ matches prod, also matches CLOB on 150-sample crosscheck |
| Fill book | VPS2 WS L25 strict-asof at `fire_us` | ✅ MORE faithful than prod-REST today; matches prod once TV migrates |
| Fill notional | $25 walk | ✅ matches prod sleeve config |
| Spread filter | BTC/ETH 0.02, SOL 0.025 | ✅ matches prod momo |
| Resolutions filter | chainlink-only (drops binance-resolved rows) | ✅ no signal/outcome leakage |
| Kline asof | end-time-indexed (no lookahead) | ✅ fixed in commit `5a72e48` (24 engines) |
| `find_book` lookahead fix | strict asof, no future leak | ✅ fixed in Phase 3+4 |

### What's missing for true live-WS mimic (priority)

| # | Gap | Current state | What to do | Effort |
|---|---|---|---|---|
| **G1** | **Fee model wrong** | "2% on profit only, winning leg" | Replace with `poly_taker_fee_per_share(p) = 0.07 × p × (1−p)` on EVERY fill, both legs. See `strategy_lab/fees.py`. PnL at vwap 0.69 changes meaningfully. | 1h wire + re-run |
| **G2** | **Latency = 0** | Backtest fills at exactly `fire_us` | Shift book lookup to `fire_us + 85_000` (75 ms base + 10 ms insert per PMXT default). Use `strategy_lab/latency.py:apply_latency(fire_us, 'fill')`. Production has measured ~75-120ms decision-to-fill. | 1h wire + re-run |
| **G3** | **Sparse-book markets** | All gated markets pass through | Filter `min_book_events ≥ 25` over `[ws_s, slot_end_us]` window. Use `strategy_lab/book_filters.py`. Drops markets where snapshot density too low to produce realistic fills. | 30m |
| **G4** | **Exit-side book lookup** | HOLD sleeves go to outcome; hedge/sell sleeves need EXIT book lookup at exit time | For SELL_*bp / STOPLOSS / hedge sleeves: lookup L25 BID at exit time + apply latency + apply fee curve on the exit fill. Currently approximated. | 2-3h |
| **G5** | **CLOB winner crosscheck at scale** | 150/150 sample agrees with chainlink | Run full 18k CLOB fetch with checkpointed cache; produce `clob_winner` column on every canonical row; flag disagreements. Validates chainlink truth and discovers any UMA-disputed markets. | 2h cold (10rps × 18k) |
| **G6** | **REST-vs-WS lag modeled** | Backtest assumes WS truth | If we ever want to predict CURRENT (pre-migration) production PnL, simulate REST lag by sampling the WS book at `fire_us − rest_lag_us` where `rest_lag_us ~ Exp(mean=300ms)`. Off the critical path once TV migrates to WS. | 4h (optional) |
| **G7** | **Partial-fill realism** | $25 walks but no per-level latency | If walk hits level N>0, model that levels 1..N−1 may have been swept by other traders during the 75ms latency. Currently `book_walk_fill` assumes the snapshot is the post-latency book. | 4h (advanced) |
| **G8** | **Maker rebate path** | All fills treated as taker | If we test the limit-order branch (post inside, get rebate), credit `−0.07 × p × (1−p) × 0.20` per share on fills. `poly_maker_rebate_per_share` already exists. | 2h once limit strategy exists |

### Engine layout to converge on

Single canonical `run_backtest(...)` shape that's used by every script:

```python
from data.v4.canonical.load import (
    load_resolutions,           # add with_clob_winner=True kwarg (G5)
    load_orderbook_l25_streaming, load_klines_asof,
    slug_to_ws_s, add_ws_s, ret_2m_at_ws, asof_strict,
)
from strategy_lab.fees       import poly_taker_fee_per_share          # G1
from strategy_lab.latency    import apply_latency, DEFAULT_LATENCY    # G2
from strategy_lab.book_filters import filter_by_min_book_events       # G3
from strategy_lab.book_walk  import book_walk_fill

def fill_at_book(books, slug, outcome, fire_us, notional_usd=25.0,
                 latency_cfg=DEFAULT_LATENCY, fee_rate=0.07):
    """Live-mimic taker fill: latency + WS L25 walk + real Polymarket fee."""
    lookup_us = apply_latency(fire_us, kind="fill", latency=latency_cfg)
    rec = find_book(books, slug, outcome, lookup_us)
    if rec is None: return None
    ap, asz = rec["ap"], rec["asz"]
    vwap, shares, usd, levels, under = book_walk_fill(ap, asz, notional_usd, side="buy")
    if under or shares <= 0: return None
    fee = shares * poly_taker_fee_per_share(vwap, fee_rate)
    return {"vwap": vwap, "shares": shares, "usd": usd, "fee_in": fee, "levels": levels}
```

Every existing momo backtest can switch over by one import + one function call swap.

---

## Recommended next session — concrete priority

### Step 1 — Wire the realism gates (2-3h) — **DO THIS FIRST**

```bash
# 1. Create the shared engine module
edit strategy_lab/engine_v2.py  # encapsulates fill_at_book + helpers above

# 2. Add `--live-mimic` flag to momo_full_universe_canonical.py:
#    - default OFF: 2%-on-profit + 0ms latency (reproduces 2026-05-16 report)
#    - ON: poly_taker_fee_per_share + 85ms latency + min_book_events=25
# 3. Re-run both modes
py -3 strategy_lab/meta_classifier/momo_full_universe_canonical.py
py -3 strategy_lab/meta_classifier/momo_full_universe_canonical.py --live-mimic

# 4. Diff the two summary.csv files → quantifies fee+latency impact on PnL
```

Deliverable: addendum to `MOMO_FULL_UNIVERSE_2026_05_16.md` with paired numbers (legacy vs live-mimic). The relevant question: does the strategy go from "≈$0/trade" to "−$1/trade" once we charge real fees on losing legs?

### Step 2 — CLOB winner integration (1-2h)

```python
# data/v4/canonical/load.py
def load_resolutions(..., with_clob_winner: bool = False) -> pd.DataFrame:
    df = ...                                # existing chainlink-filtered
    if with_clob_winner:
        from clob_resolutions import load_resolutions_clob
        clob = load_resolutions_clob(condition_ids=df.market_id.tolist(),
                                       checkpoint_every=500)  # add this param!
        df = df.merge(clob[["condition_id","winner","is_50_50","min_tick_size"]],
                      left_on="market_id", right_on="condition_id", how="left")
        df["poly_truth"] = df["winner"].fillna(df["outcome"])
        df["clob_disagrees_chainlink"] = (df["winner"].notna()
                                          & (df["winner"] != df["outcome"]))
    return df
```

Add checkpointed bulk fetch to `clob_resolutions.py:load_resolutions_clob` (flush parquet every N markets so SIGINT doesn't lose progress). Then run the full 18k fetch overnight; expect ~30 minutes at 10 rps.

Deliverable: `data/v4/canonical/clob_resolutions_cache.parquet` with all 23,553 markets. Brief addendum to `OUTCOME_RESOLUTION_CLOB_DISCOVERY_2026_05_12.md` with full-universe agreement rate.

### Step 3 — Step 5 from May-10 handoff (tighter-gate + 15m + May 8)

With realism gates wired (Step 1), re-run the gate sweep:
- q90 (current) → q95 → q99
- 15m timeframe separately (lower-N but apparently better hit rate)
- May 8 production PnL permutation test on the corrected universe

Deliverable: `GATE_SWEEP_LIVE_MIMIC_2026_05_17.md` answering "does any gate level + asset/tf cell survive once fees are correct?"

### Step 4 — Live transition crosscheck

Once TV agent migrates production to WS book, our backtest engine should match production live PnL to within $0.05/trade. Until then, our backtest predicts the **post-migration** live world, and production REST PnL is irrelevant for forward planning.

The `_xref_live_vs_parquet.py` script needs to be extended to:
1. Pull live trades from `vps3_trading_events_14d.csv`
2. For each, recompute backtest fill via `fill_at_book(books, slug, outcome, fire_us)`
3. Decompose delta into: (a) REST-lag (will go to 0 post-migration), (b) fee model, (c) latency, (d) other
4. Output `LIVE_VS_BACKTEST_DECOMP.csv`

### Step 5 — Addendum on old reports

Six reports still claim inflated numbers from before the ws_s fix:
- `MOMO_V1V2_CANONICAL_2026_05_10.md`
- `MOMO_FEED_LAG_INVESTIGATION_2026_05_10.md`
- `MOMO_CHAINLINK_ONLY_2026_05_09.md`
- `MOMO_COINBASE_LEAD_2026_05_09.md`
- `MOMO_COINBASE_ADDALPHA_2026_05_09.md`
- `EXTENDED_BACKTEST_ROBUSTNESS.md`

Each needs a single section at the top:

```markdown
> **⚠️ RETROACTIVE CORRECTION (2026-05-16)**
>
> Numbers in this report use the pre-fix `ws_s = slug_suffix` anchor →
> inflated hit rate by ~30 pp. Superseded by `MOMO_FULL_UNIVERSE_2026_05_16.md`.
> The strategy variant covered here was [VARIANT-NAME] which corresponds to
> rows where `version=v1`/`v2`, `variant=HOLD_baseline`/etc in the new
> `full_universe_2026_05_16/per_trade.csv`. Recompute from that source.
```

---

## Tier-2/3 PMXT items still on the back burner (not blocking)

| Item | Status | When to revisit |
|---|---|---|
| Maker-rebate posting variant strategy | Not built | After Step 3 confirms or kills momo |
| Microprice imbalance gate on top of momo | Not built | After Step 3 (one of the "harder-gate" candidates) |
| Late-favorite-taker-hold baseline on canonical | Not built | After Step 1 (baseline for comparison) |
| Final-period momentum (PMXT 30-min final TP/SL) | Not built | After Step 1 |
| Staged parallel L25 loading (90s → 15s on BTC) | Not built | After we're iterating fast enough that 90s hurts |
| Port one momo variant to NautilusTrader | Not built | After Step 4 — for production-realism crosscheck |
| Pair-arbitrage full scan (currently 20-slug smoke) | Not built | Independent — could run in background overnight |

---

## File reference — what exists vs what's needed

### Already on disk (need wiring, not rewriting)

```
strategy_lab/fees.py                          ← poly_taker_fee_per_share + breakeven
strategy_lab/latency.py                       ← StaticLatencyConfig + apply_latency
strategy_lab/book_filters.py                  ← filter_by_min_book_events
strategy_lab/pair_arbitrage/scan_canonical.py ← YES+NO < $1 scanner

data/v4/canonical/clob_resolutions.py         ← CLOB resolution loader + crosscheck
data/v4/canonical/clob_resolutions_cache.parquet (150 rows; needs full 18k)

data/v4/canonical/load.py                     ← ws_s helpers ✓; needs with_clob_winner
strategy_lab/meta_classifier/momo_full_universe_canonical.py ← needs --live-mimic flag

strategy_lab/reports/EXTERNAL_REPO_COMPARISON_evan_kolberg_pmxt_2026_05_12.md
strategy_lab/reports/OUTCOME_RESOLUTION_CLOB_DISCOVERY_2026_05_12.md
strategy_lab/reports/DATA_INVENTORY_2026_05_15.md     ← canonical state, read first
strategy_lab/reports/MOMO_FULL_UNIVERSE_2026_05_16.md ← latest backtest verdict
strategy_lab/reports/MOMO_REST_LAG_VS_MICROSTRUCTURE.md ← reframes prod paper PnL
```

### To build next session

```
strategy_lab/engine_v2.py                     ← shared fill_at_book() + helpers
strategy_lab/reports/LIVE_MIMIC_DIFF_2026_05_17.md  ← Step 1 deliverable
strategy_lab/reports/GATE_SWEEP_LIVE_MIMIC_2026_05_17.md  ← Step 3 deliverable
strategy_lab/reports/LIVE_VS_BACKTEST_DECOMP_2026_05_17.md  ← Step 4
strategy_lab/meta_classifier/_xref_live_decomp.py  ← Step 4 script
```

---

## End of handoff
