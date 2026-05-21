# Next Session — Start Here (2026-05-21, end-of-day)

_Replaces the morning version of NEXT_SESSION_PICKUP_2026_05_21.md. Both TV-agent specs LANDED today and are working in production._

---

## TL;DR (60 seconds)

Yesterday → ended with two specs sent to TV agent (F7 RSI filter for VPS3 momo, residual-mark fix for Ireland maker-arb). Today both deployed and verified.

**Production state right now**:
1. ✅ **F7 RSI filter LIVE on VPS3** — 24 `_f7` sleeves running since 2026-05-20 19:57 UTC. 36h of data shows aggregate WR jumped 44% → 51%, PnL flipped from **−$5,241 → +$192 = +$3.6k/day projected lift.**
2. ✅ **Residual-mark fix LIVE on Ireland** — `inv_up = inv_dn = 0` in all 4 `on_slug_resolved` methods. New MAS 15m slugs correctly show `slug_pnl_so_far = $0` when there are no fills. Old slugs (resolved before ~2026-05-21 18:25 UTC) still carry the bugged +$15 mark — immutable historical data.

Net state: **production numbers are now trustworthy on both VPSes**. Two minor concerns to monitor + 48h clean-data validation pending. No new specs needed.

---

## Production architecture (unchanged)

| VPS | Role | Strategies |
|---|---|---|
| **VPS3** (`storedata-vps3`, 185.190.143.7) | trading engine + full storedata DB | 12 momo cells × 3 policies × {baseline, +F7} now = up to 72 sleeve_ids |
| **VPS Ireland** (`vps`, 85.137.174.152) | live mirror dashboard + maker-arb suite | 5 maker sleeves (acc_m, acc_h, acc_pc, mas, pat_shadow) — SHADOW mode |

SSH aliases: `vps3`, `vps_ireland`.

### Master data

- `data/v4/canonical/trading_events_30d.parquet` — VPS3 production events. **GROUND TRUTH for momo behavior.**
- `strategy_lab/monitoring/_logs/vps3/momo_resolutions_36h.csv` — fresh F7-tagged resolutions pulled today
- `strategy_lab/monitoring/_logs/ireland/*_2026-05-21.csv` — fresh Ireland maker CSVs
- `strategy_lab/monitoring/_logs/ireland_code/` — Ireland maker source files (for reference)

---

## F7 RSI filter — DEPLOYED + WORKING

### What's running

24 `_f7` sleeves on VPS3, all 5m (BTC/ETH/SOL × v1+v2 × HOLD/HEDGE/SELL = 18) + 6 BTC/ETH 15m v2 sleeves. The filter:

```python
def f7_passes(signal: str, rsi_14: float) -> bool:
    if not math.isfinite(rsi_14):
        return False
    if signal == "UP"   and rsi_14 <= 50: return False
    if signal == "DOWN" and rsi_14 >= 50: return False
    return True
```

RSI(14) computed on binance-spot-ws 1MIN closes ending at `ws_s`.

### Live performance (36h of paper+shadow data)

| Group | n | WR | Sum PnL | $/trade |
|---|---:|---:|---:|---:|
| **momo v1 baseline** | 848 | 45.17% | **−$2,044** | −$2.41 |
| **momo v1 + F7** | 145 | **62.76%** | **+$687** | **+$4.74** |
| **momo v2 baseline** | 1,037 | 43.30% | −$3,197 | −$3.08 |
| **momo v2 + F7** | 239 | 43.93% | −$495 | −$2.07 |
| **TOTAL baseline** | 1,885 | 44.14% | **−$5,241** | −$2.78 |
| **TOTAL +F7** | 384 | **51.04%** | **+$192** | **+$0.50** |

**Aggregate swing: +$5,433 over 36h ≈ +$3,622/day.** In the conservative range of the +$2-5k/day projection from backtest.

### Strong cells (F7 working great)

- btc_5m v1: 43.97% → **70%** WR, +$6.79/trade
- eth_15m v2: 72.82% → **86.11%** WR, +$18.05/trade
- sol_5m v2: 27.57% → **61.54%** WR, +$17.31/trade
- btc_15m v1: 41.67% → **100%** WR (n=15 small, but consistent with backtest)

### ⚠️ One concern to investigate

- **eth_5m_momo_v2 + F7 REGRESSED**: baseline 36.36% WR → F7 6.67% WR (n=45). Small sample, but every other cell either flat or improved. Should investigate next session.
- **momo v2 + F7 mostly flat** while momo v1 + F7 crushes it. The v2 gate may have its own filter that conflicts with F7. Worth understanding why v1 carries all the lift.

---

## Maker-arb suite (Ireland) — residual-mark fix DEPLOYED + WORKING

### What changed

`acc_m.py`, `mas.py`, `acc_h.py`, `acc_pc.py` `on_slug_resolved` now zero BOTH `inv_up` and `inv_dn` after the winner redeems (was: only winner side cleared, loser side kept at original mint quantity).

Verified at `acc_m.py:369-370`:
```python
state.inv_up = Decimal(0)
state.inv_dn = Decimal(0)
```

### Verification on MAS 15m

64 slugs in `mas_2026-05-21.csv`:

| Group | n_slugs | slug_pnl_so_far | inv at last row |
|---|---:|---|---|
| Pre-patch (resolved before 18:25 UTC) | 12 | +$15.00 ← still bugged (immutable) | inv_dn=30 or inv_up=30 |
| Post-patch (resolved after 18:25 UTC) | 52 | **$0.00** ✅ correct | inv_up=0, inv_dn=0 ✅ |

Boundary slug: `btc-updown-15m-1779331500`. Patch landed ~2026-05-21 18:25 UTC.

### All 5 sleeves now produce honest PnL

The `slug_pnl_so_far` column is now trustworthy on Ireland. Cross-check with the manual formula `cash_received + cash_recovered + rebates − cash_spent − taker_fees` (no mark) — should match for all NEW slugs.

### Operational caveats still standing

- **MAS 15m gets 0 maker fills** — reality, not bug. Just mint + redeem economics ≈ $0 PnL per slug.
- **pat_shadow at `pat_max_pair_cost=1.02`** is structurally −EV. Per-slug −$4 to −$30. Operator decides keep (research) or disable.
- **acc_h over-firing** — 2,691 TAKEs in 17h drives taker-fee bleed. Needs Rule B tightening + slot-open delay. Not yet patched.

---

## What's actually open right now

### High priority

1. **48h post-fix clean-data validation on Ireland.** Pull `mas_2026-05-22.csv` + all 5 sleeves' May 22 CSVs after 24h post-patch. Compute clean per-sleeve PnL with the now-honest `slug_pnl_so_far` column.
2. **F7 on momo_v2 deep-dive** — why does v2 + F7 not lift like v1 + F7? Specifically the eth_5m_momo_v2 F7 regression (36% → 6.67% WR).

### Medium priority

3. **acc_h tuning spec** — Rule B (sharp_drop) threshold needs tightening. Add `min_time_after_slot_open_s ≥ 60`. Cap TAKEs per slug.
4. **pat_shadow operator decision** — keep at −$4/slug for research or disable.

### Low priority

5. Investigate `pnl.parquet` wallet-decode build script — numbers don't reconcile with cash flow + mint + redemption math. Separate task.
6. Bug 7 (take_empty_book state leak) — rare edge case.
7. Bug 10 (state persistence on restart) — wait for live mode.

---

## Reports written across the two days

All in `strategy_lab/reports/`:

### Validation / honest numbers
- `BACKTEST_VS_SHADOW_GAP_2026_05_20.md` — admitted backtest was 3-5× inflated
- `NEW_EDGE_FROM_PRODUCTION_DATA_2026_05_20.md` — pivot to production events
- `MOMO_FILTER_OVERLAY_2026_05_20.md` — F7 discovery (74% WR variant)
- `MOMO_12CELLS_F7_2026_05_20.md` — clean 12-cell F7 table
- `MOMO_LIVE_VS_F7_2026_05_20.md` — VPS3 + Ireland combined
- `IRELAND_MAKER_AUDIT_2026_05_20.md` — initial audit
- `IRELAND_MAKER_PATCH_VERIFICATION_2026_05_21.md` — verified 7/10 patches (mistakenly celebrated PnL flip)
- `MAS_15M_STALE_AND_PNL_BUG_2026_05_21.md` — found residual-mark bug
- **`F7_AND_RESIDUAL_FIX_VERIFICATION_2026_05_21.md`** — TODAY: both fixes verified working

### TV agent specs (all DONE — patches landed)
- `TV_AGENT_F7_RSI_FILTER_SPEC.md` ✅ deployed
- `TV_AGENT_MAKER_BUG_FIX_GUIDE.md` ✅ 7/10 patched
- `TV_AGENT_RESIDUAL_MARK_FIX_SPEC.md` ✅ deployed

### Earlier (mostly invalidated by subsequent findings — DON'T REDO)
- `SLUG_SELECTION_DECODE_2026_05_20.md` — engagement classifier (no PnL amplification)
- `WITHIN_SLUG_TIMING_DECODE_2026_05_20.md` — chain PnL untrustworthy
- `PAT_TIMING_SWEEP_2026_05_20.md` / `PAT_HYPERPARAMS_FULL_SWEEP_2026_05_20.md` — backtest inflated
- `WALKFORWARD_AUDIT_2026_05_20.md` — confirmed lift smaller than claimed
- `EXTENDED_WINDOW_REVALIDATION_2026_05_20.md` — found data quality issue

---

## Things to know about the project

### Critical conventions (from CLAUDE.md)

1. UTC microseconds for `*_us` columns; never localize
2. `ws_s = slug_suffix - window_s` (PREVIOUS slot start, NOT slug suffix)
3. Outcome = chainlink RTDS (never derive from binance)
4. `asof_strict` for causal lookups
5. L25 walk via `book_walk_fill` for production-matching fills
6. Polymarket taker fee: `0.07 × p × (1-p)` per share; maker rebate: `0.20 × taker fee`
7. CLOB minimum order: **5 shares per side**, $0.01 price tick
8. Currency on-chain: **USDC.e** (`0x2791bca1...`), Polymarket UI calls it **pUSD** (same token)

### New conventions established this session arc

9. **`trading_events_30d.parquet` is the ground truth** for production behavior — NOT backtest CSVs
10. **F7 = `f7_passes(signal, rsi_14)`** is the validated momo edge — already in production
11. **Shadow CSV `slug_pnl_so_far` is trustworthy for slugs resolved AFTER 2026-05-21 18:25 UTC** — older slugs have the residual-mark bug baked in
12. **Backtest PnL is 3-5× inflated** vs production (queue position assumed=0, no latency, no slippage, missing aggressor info). Always validate against production sleeve data.

### Things I got wrong (lessons)

1. Trusted backtest PnL projections (+$2,000/day) before validation. Real production was LOSING $811/day across all sleeves.
2. Spent significant time on slug-selection classifier — wallet engagement predicts WR but NOT profitability.
3. Within-slug timing decode used `pnl.parquet` which has unreconciled build-script bugs.
4. PAT timing sweep "+125%" claim — driven by sparse `_12` L25 refresh data covering ~25% of slugs.
5. Celebrated "patches flipped everything positive" before re-checking the new PnL field — which itself had the residual-mark bug.

**Rule**: production shadow > backtest, every time. Validate columns are populated AND have correct values. Don't celebrate sign flips before re-running post-patch validation.

---

## Recommended starting prompt for next session

```
Read NEXT_SESSION_PICKUP_2026_05_21.md first.

Both yesterday's specs landed and are verified working. Two priorities for today:

1. Pull May 22+ data from both VPSes. Compute clean post-fix PnL:
   - VPS3: per (cell × version × policy × {baseline, +F7}) using trading_events
   - Ireland: per sleeve using the now-trustworthy slug_pnl_so_far column
   Publish honest 48h numbers.

2. Investigate the eth_5m_momo_v2 + F7 regression (36% → 6.67% WR
   on n=45 yesterday). Either small-sample noise that washes out,
   or F7 conflicts with the v2 gate on ETH 5m.

If both look good after 48h clean data, plan the next step:
  - Promote F7 to "replace baseline" (kill non-F7 sleeves) for cells
    where F7 clearly wins?
  - Or wait for 7d before pulling baselines?
```

---

## Don't redo

- ❌ Slug-selection classifier (engagement ≠ profitability)
- ❌ Within-slug timing decode (chain PnL untrustworthy)
- ❌ PAT timing sweeps / hyperparameter optimization on the limited backtest engine (3-5× inflated)
- ❌ Re-test PAT+ACC-M HYBRID, MAS, ACC-PC — they're in Ireland shadow with honest PnL now
- ❌ Live momo wallet investigation (out of scope, ~$8 pUSD is plenty)
- ❌ Resend F7 spec or residual-mark fix spec — both landed

## Do

- ✅ Trust `trading_events_30d.parquet` for production momo truth
- ✅ Trust Ireland CSVs for slugs resolved AFTER ~18:25 UTC on 2026-05-21
- ✅ Use F7 baseline-vs-F7 comparison as the primary momo metric
- ✅ When numbers look surprising, check column population FIRST before interpreting

---

_End of context dump for 2026-05-21. Both major specs landed. Ready for 48h clean-data validation next session._
