# Engine Fidelity Map — confirmed bugs, primitives, parity findings

_Last updated: 2026-06-03. Sources: ENGINE_AUDIT_{A,B,C,D}_2026_05_29, ENGINE_BUG_MAP_2026_05_28,
ENGINE_CORRECTNESS_AUDIT_2026_05_28, ENGINE_FIX_VERIFICATION_2026_05_29, CAPSTONE_STRATEGY_ARCHITECTURE_2026_05_29,
parity reports (ETH_LIVE_VS_SHADOW, SOL_MOMO_V2_LIVE_VS_SHADOW, ETH_SHADOW_FIRES_LIVE_DOESNT_BOOKSOURCE,
DEBUG_SOL_MOMO_V2_HOLD_LIVE_VS_SHADOW — all 2026-06-02), HANDOFF_2026_06_03, HANDOFF_2026_06_03_SCALP_DEPLOY,
BACKTEST_VS_SHADOW_GAP_2026_05_20, HANDOFF_2026_05_16_LIVE_MIMIC_GAPS, EXACT_BUG_MOMO_V2_QTY_COMPUTE_ASYMMETRY_2026_05_21._

---

## Confirmed bugs (fixed / open)

### Fixed in `engine_v2.py` (as of ENGINE_AUDIT_A_core_2026_05_29 + ENGINE_FIX_VERIFICATION_2026_05_29)

| Bug | Severity | Status | Details |
|-----|----------|--------|---------|
| `min_book_events` never enforced | Medium | **FIXED** | Declared in `EngineConfig`, set to 25 in `LiveMimicConfig`, but `fill_at_book` never called `book_event_count`. Silently admitted sparse-book markets, inflating placement count. Fix: count events in 120s window before `find_book_strict`; return None if < threshold. |
| `sell_pnl_partial` missing | Low-Medium | **FIXED** | Referenced in docstrings and usage examples, never defined. Any `from engine_v2 import sell_pnl_partial` caused `ImportError`. Fix: added convenience wrapper (book lookup + bid-side walk + `sell_pnl` in one call). |
| Kline lookahead — anchor on `slot_start` not `ws_s` | Critical | **FIXED** | Pre-fix commit `5a72e48` fixed 24 backtest engines. Anchoring on `slot_start` observes first 2 min inside prediction window → inflates backtest hit rate ~25–40 pp (~85% vs ~50% live). |
| `find_book` lookahead fix | Medium | **FIXED** | `find_book_strict` now uses strict asof (no future snap ever returned). Fixed in Phase 3+4. |
| `acc_pc.py` E7 — pair-cost uses both-sides average | Medium | **OPEN (not fixed)** | `avg_lead_cost = state.cash_spent / lead_inv` — `cash_spent` is total both-side spend; `lead_inv` is one side → garbled `pair_cost` gate. Correct fix: track `cash_spent_up` / `cash_spent_dn` separately. Reported in ENGINE_BUG_MAP_2026_05_28. Maker-arb is anyway net-negative post-censoring (MAKER_ARB_CENSORING_REVERSAL_2026_05_28). |
| `momo_v2 qty_compute_failed` asymmetry | Low | **NOT a code bug** | Investigated in EXACT_BUG_MOMO_V2_QTY_COMPUTE_ASYMMETRY_2026_05_21. `qty_compute_failed` is a documented strategy gate, not a defect. Bias is real in trending regimes but reflects market structure — deploy decision, not code fix. |
| LAGV2 always-UP direction bug | High | **FIXED (2026-06-01)** | All 4 `poly_fast_taker_lagv2_*` live sleeves fired UP on 100% of 95 resolved fires (never DOWN). Root cause: live gate read the wrong signal. Fix deployed 2026-06-01; confirmed 50/50 post-fix. |
| Kalshi 409 Conflict / FOK-to-IOC | Medium | **FIXED (2026-06-03)** | `ema50_ema800_H` sleeve not firing on Kalshi. Fix: capture 409 body + change entries from FOK to IOC (`TV_FIX_KALSHI_IOC_2026_06_02`). Live after 06-03 09:38 restart. Also added FOK-killed accounting (no phantom positions). |
| `fire_us = slot_end` in RESOLVED events | Cosmetic | **OPEN** | `polymarket_sniper_v5.py` resolution path passes `slot_end_us` as the `fire_us` param → misleads analytics dashboards. (Placed events correctly show off=60/600.) Fix: add separate `resolved_at_us` field. Has fooled analysis twice. |
| Fee model misidentified as 2%-on-profit | Critical (now corrected) | **CORRECTED in CLAUDE.md 2026-06-03** | Earlier reports claimed feeRate=0 (2%-on-profit). VERIFIED 2026-06-03 against live `poly_updown_resolution` events: production charges `0.07 × p × (1−p)` on winners ONLY (losers = $0 fee). Worked example: entry=0.509, qty=50 → pnl +23.675 matches 0.07-curve exactly, NOT 2%-on-profit. Old reports priced at legacy overstate winning-trade PnL ~$0.36–0.43/win at typical vwaps. |
| off900 "double-fire" apparent in metrics | Cosmetic | **NOT A BUG** | `sleeve_fire_placed` + `sleeve_fire_resolved` both stamped `all_gates_passed=true` → metrics double-count only. Actual execution is single fire. (`TV_FIX_SNIPER_DOUBLE_FIRE_NONBUG_2026_06_02.md`). |

---

## Trustworthy primitives & their known limits

### `engine_v2.py` — the canonical backtest primitive
- Use `from strategy_lab.engine_v2 import LiveMimicConfig, fill_at_book, hold_pnl, sell_pnl`
- **`RealisticConfig`** = conservative stress-test (poly_taker_curve on ALL fills including losers + 85ms latency + min_book_events=25 + tx_cost_usd=0.01). NOTE: production charges fee on WINNERS ONLY, so `RealisticConfig` is deliberately harsher than reality. Use for bounding downside, NOT for production parity.
- **`LiveMimicConfig`** = poly_taker_curve + 85ms latency + min_book_events=25 + no tx_cost. Fee model here charges on every fill (both winners and losers) which is slightly too harsh vs live (winner-only). For hold-to-resolution strategies where the fee is effectively 0 on crypto up-down markets, `LegacyConfig` may be closer to production reality.
- **Confirmed correct** (matching production): ws_s anchor, Binance spot signal source, Chainlink RTDS outcomes, L25 strict-asof fill, $25 book walk, BTC/ETH 0.02 / SOL 0.025 spread filter, chainlink-only resolutions filter.
- **Known optimism in fill model:** canonical L25 walk is OPTIMISTIC vs live taker fills on thin/marginal slugs. Backtest fill ≠ live fill; backtest over-estimates placement rate on sparse books.

### `load_orderbook_l25_streaming` — mandatory calling convention
```python
books = load_orderbook_l25_streaming(asset.lower(), slugs=set(...), subsample_1hz=False, ...)
```
- **`subsample_1hz=False` is MANDATORY** for any backtest. Default is `subsample_1hz=True` for memory; OVERRIDE it. Verified 2026-05-27: V5 live deploy had 0 placements because cross-token spreads averaged 31% on live data; backtest with 1Hz subsampling placed thousands — "luck of the sample" bias.
- Native rate is ~10Hz. Production reads WS BookMirror at every update; matching this is essential.

### Spread filter convention — backtest must match live
- Live controller `polymarket_sniper_v5.py:_compute_spread` uses **cross-token** spread: `abs(up_vwap - (1 - dn_vwap))` on $5/$25-walked vwaps.
- `engine_v2.fill_at_book` uses **same-token** bid-ask: `ask0 - bid0` on the buy side only.
- These diverge: live's cross-token check fails 99%+ of V5 fires on real books (UP+DOWN vwaps sum to ~1.30 median). Use the LIVE cross-token filter definition when comparing backtest to live PnL.

### `asof_strict` / `find_book_strict`
- Always use `asof_strict(end_us, prices, target_us)` for kline lookups — returns close of bar that ended at-or-before `target_us`. Causal. Never `searchsorted(side='left')`.
- `find_book_strict` similarly: latest book snapshot with `ts <= target_us`, enforces `max_staleness_us`.

### Outcome truth
- Primary: `outcome` col from `load_resolutions()` — chainlink-derived.
- Opt-in: `load_resolutions(..., with_clob_winner=True)` — Polymarket actual settlement. 300/300 agreement tested. Use when PnL is what Polymarket actually pays out.
- Never derive Up/Down from Binance close.

---

## Live-vs-shadow parity findings

### Root cause (confirmed 2026-06-02)
Shadow and live engines run on DIFFERENT hosts (VPS3 vs Ireland VPS). Both use the same strategy code and threshold — but each computes gate inputs from its own local feed/snapshot. When strategies trigger at decision boundaries (most gates are threshold-based), marginal slots flip fire/no-fire, and can flip direction.

### Sniper sleeves (spread gate divergence)
- Both hosts read `ws_mirror` (WS BookMirror). Two INDEPENDENT WebSocket connections see different spreads on thin books at the exact fire millisecond.
- Prime suspect: shadow path has `TV_POLY_PAPER_BOOK_CACHE_TTL=1` → serves a ≤1s-stale, tighter spread snapshot.
- Example: slug `1780442400` — shadow spread 0.02 → fired DOWN @0.21; live spread 0.05 → rejected.
- Source: `ETH_SHADOW_FIRES_LIVE_DOESNT_BOOKSOURCE_2026_06_02.md`

### momo_v2 sleeves (ret_2m threshold divergence)
- Identical threshold (0.00151) but each host computes `ret_2m_at_signal` from its OWN Binance feed with its own bar timing/freshness.
- Small feed difference flips boundary slot between fire/no_signal AND can flip direction.
- On non-boundary slots with tight books: both hosts agree exactly (eth sniper: 11/11 identical slug/dir/price within 1–2¢).
- Source: `SOL_MOMO_V2_LIVE_VS_SHADOW_2026_06_02.md`, `DEBUG_SOL_MOMO_V2_HOLD_LIVE_VS_SHADOW_2026_06_02.md`

### Implication & fix
- **Judge strategies by LIVE wallet, NOT shadow WR.** Shadow numbers are unreliable for boundary strategies.
- Fix: make shadow gate inputs read from the SAME fresh feed/snapshot as the live host (book spread + `ret_2m`/threshold). OPEN as of 2026-06-03.

### Backtest-vs-live gaps (earlier findings, still relevant)
- PAT/ACC-M: zero latency + zero slippage → overstates PAT PnL ~1.3–1.5×.
- Maker fill model: `open_bid_queue_ahead = bid_size_at_best` — assumes optimal queue position. Real latency collapses queue advantage.
- Data coverage cliff (BACKTEST_VS_SHADOW_GAP_2026_05_20): Apr 22–May 6 L25 base file had ~75% slug coverage; May 7+ delta pulls had ~20–35%. Best backtest configs win mostly on the dense 13-day window. "80% fire rate" estimate for post-May-6 would double projected PnL — do NOT extrapolate.
- BTC momo: backtest UNDER-estimates by ~12pp due to HL-vs-Binance price divergence (backtest uses Binance; production uses Binance; mismatch only from HL perp ≠ Binance spot at 5m). ETH/SOL roughly match.

---

## Backtest gotchas to respect

1. **ws_s anchor is MANDATORY.** `ws_s = slug_suffix - window_s` (NOT slug_suffix). Anchoring on `slot_start` = lookahead → hit rate inflates 25–40 pp. Use `slug_to_ws_s()`, `add_ws_s()`, `ret_2m_at_ws()`.
2. **Fee model.** Production = `0.07 × p × (1−p)`, WINNER ONLY. Losers pay $0. Verified 2026-06-03. `LegacyConfig` (2%-on-profit) is slightly too harsh on losers but directionally acceptable. `RealisticConfig` (0.07-curve on ALL fills) is a conservative stress-test, not production reality.
3. **L25 at native 10Hz.** Always `subsample_1hz=False`. 1Hz subsampling produces backtest placements that vanish live (spread bias).
4. **Spread filter: same-token bid-ask in engine_v2.** Live production uses cross-token arb-consistency spread. When comparing to live fill rates, replicate the live definition.
5. **Chainlink-only outcomes.** Filter out binance-resolved rows. Never derive Up/Down from Binance close.
6. **`min_book_events=25` must be enforced.** Use `LiveMimicConfig` or `RealisticConfig` which set this. `LegacyConfig` (=0) disables the filter — fine for pre-2026-05-16 comparisons, not for new work.
7. **`fire_us = (ws_s + 120) * 1_000_000` for momo v1; `(ws_s + 60) * 1_000_000` for momo v2.** Version-aware.
8. **F7 RSI anchor = ws_s, simple-mean Wilder (NOT exponential).** 94.67% match verified against 1,331 live fires.
9. **`sell_pnl_partial` for intra-window exits.** Now exists in engine_v2. Use it; don't roll your own.
10. **Shadow PnL ≠ live PnL.** Boundary-trigger strategies will show different fire counts and WRs on shadow vs live. Always use LIVE wallet as ground truth once deployed.
11. **`fire_us = slot_end` in RESOLVED events (open bug).** Do NOT use `fire_us` from resolution events for timing analysis — use `fire_us` from placed events only.
12. **Backtest fill model is optimistic on thin/marginal slugs.** Canonical L25 walk assumes available depth; live takers face adverse selection on sparse books. Cross-token spread averages ~31% on real V5 live data vs backtest-passing books.
13. **Data coverage window matters.** Always verify L25 slug coverage density for the backtest period — don't extrapolate PnL from a dense window to a sparser one.
14. **Maker-arb is closed.** Survivorship-bias correction (right-censored slugs) flips edge from +$4.44/slug to −$0.41–−$3.63/slug. acc_pc E7 bug (open) further compromises that pipeline.
