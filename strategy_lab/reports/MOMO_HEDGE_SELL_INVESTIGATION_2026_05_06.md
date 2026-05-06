# Momo HEDGE-skip and SELL-fire Investigation

**Date:** 2026-05-06
**Triggered by:** user question — "why did `eth_5m_momo_HEDGE`, `btc_5m_momo_HEDGE`, `btc_15m_momo_HEDGE` skip more hedges than fills? And why did SELL barely fire?"

---

## TL;DR

1. **Hedge skips > fills is NOT a 1-skip-per-attempt counter.** Each `poly_updown_hedge_skip` event is **one on_tick retry**, fired every ~10s while the position is open and the rev_bp gate is open AND the opposite-outcome book is empty. One stuck fill can produce 6-42 skip events over its lifetime. The 6 skips on `btc_15m_HEDGE` (1 fill) = 6 retry ticks on the same position — the engine kept retrying every 10s because the YES-side opposite book was unavailable (`book_ts=0`).
2. **SELL barely fired (1/24+) because the rev_bp gate uses the bar-close anchor, not the entry anchor.** Entry happens at `t+120s` after the asset has already moved `ret_2m ≈ +N bp` in the signal direction. For SELL_BID to fire, the asset must reverse all the way back through zero to `-REV_BP_THRESHOLD` (5bp) on the OPPOSITE side. Effective reversal needed = `5bp + |ret_2m|` ≈ 12-30bp in the remaining 3-13 min window. Rare. Trade #28 (SOL UP, ret_2m=+14.6bp, settled Down) is the only one that crossed it.

Both are **expected behavior given the controller code**, not bugs. But the rev_bp anchor choice is debatable — see §4 "Action items".

---

## 1 · Question A — How can HEDGE have more skips than fills?

### Data (current snapshot, 2026-05-06)

```
sleeve                           hedge_fills  fills_w_skips  total_skips
poly_updown_btc_15m_momo_HEDGE        1              1             6
poly_updown_btc_5m_momo_HEDGE         4              1             6
poly_updown_eth_15m_momo_HEDGE        3              1            42
poly_updown_eth_5m_momo_HEDGE         7              2             8
poly_updown_sol_15m_momo_HEDGE        2              0             0
poly_updown_sol_5m_momo_HEDGE        19              2            25
```

87 total skips, all `reason='no_asks'`, all `hedge_policy_branch=NULL` (default HEDGE_HOLD path, never the SELL_BID path).

### Root cause

`_maybe_hedge` (controller line ~2437) runs on every on_tick (~10s) for every open slot:

```
1. Fetch Binance close. If stale → audit skip + return.
2. Compute bps = (btc_now - btc_close_at_ws) / btc_close_at_ws * 1e4.
3. If not reverted by REV_BP_THRESHOLD → return silently.
4. Fetch opposite-outcome CLOB book.
5. If book empty / no asks → audit_hedge_skip(reason='no_asks'),
                            slot.status = 'held_no_hedge', return.
6. Otherwise → walk asks, place hedge order, slot.status = 'hedged'.
```

**The bug-shaped behavior:** when step 5 fires, `slot.status='held_no_hedge'` does NOT remove the slot from `_open_slots()`. The next tick fires again, refetches the (still-empty) opposite book, writes another skip event. Repeats every 10s until either (a) the book recovers, (b) the position resolves, or (c) the prune in `_prune_resolved_slots` removes it.

### Why opposite books are empty (`book_ts=0`)

`book_ts=0` means the executor returned an empty book object — either:
- REST CLOB call failed/timed out → empty book returned
- Token_id resolution for the opposite outcome failed
- The opposite-outcome asks book genuinely has zero offers (illiquid market near settlement)

The combination of the "every 10s retry" loop + REST instability + occasional truly-empty opposite books = bursts of 6-42 skip events per stuck fill.

### Verifying the count math

`btc_15m_momo_HEDGE`:
- 1 fill at 2026-05-06 15:02:04 (single BTC 15m DOWN entry)
- 6 skip events spaced ~10s apart from 15:04:06 → 15:04:57
- Same `condition_id` and `slot_id` on all 6 skips
- All `book_ts=0`
- Conclusion: 1 position × 6 retry ticks = 6 skip events. **Not 6 separate hedge attempts on different fills.**

The user's intuition was right: it's nonsensical to have more hedge attempts than fills, *if* you assume one skip = one fill. The schema is actually one skip = one tick-retry-on-same-fill.

### Worst case (ETH_15m_momo_HEDGE: 1 fill → 42 skips)

15m markets resolve at `ws + 900s`. After entry at `ws + 120s`, slot is open for ~13 minutes. If the opposite book is unavailable for the entire duration: 13 min × 6 ticks/min = ~78 ticks max. The 42 we observed = the rev_bp gate was open for ~7 min of the 13-min window. Engineering-wise this is wasteful but pnl-wise harmless (HOLD policy wouldn't have hedged either).

---

## 2 · Question B — Why did SELL fire only once across 24+ fills?

### Data

| metric | count |
|---|---:|
| SELL fills (across 6 cells × ~4 fills/cell) | 24-30 (varies by snapshot) |
| Resolutions with `partial_bid_exit=true` | **1** (trade #28: SOL_5m_SELL on 2026-05-06 09:05) |
| `hedge_policy_branch='sell_bid'` skip events | **0** |

Zero `sell_bid` branch skip events means SELL_BID's rev_bp gate **never opened** on any other fill except #28. If it had opened and the own-bid book had been empty, we'd see skip events tagged with `branch=sell_bid`. We don't.

### Root cause (the rev_bp anchor problem)

`_maybe_sell_at_bid` (controller line 2281+):

```python
bps = (btc_now - slot.btc_close_at_ws) / slot.btc_close_at_ws * 10_000

reverted = (slot.signal == "UP"   and bps <= -REV_BP_THRESHOLD) or \
           (slot.signal == "DOWN" and bps >= +REV_BP_THRESHOLD)

if not reverted:
    return  # silent — no event written

await self._try_bid_exit(slot, bps, prior_branch="sell_bid_policy")
```

Critical detail: `slot.btc_close_at_ws` is the **bar-close anchor** = the asset price at market open. Entry happened at `t+120s`, AFTER the asset already moved `ret_2m ≈ +12bp to +30bp` in the signal direction (that's what passed the q90 momo gate in the first place).

For SELL to fire on a bought-UP slot:
- Required: `bps <= -5` (asset price ≤ -5bp from bar-close)
- Effective reversal from entry: `(ret_2m at entry) + 5bp` = roughly **12-35bp opposite move** in the remaining `300-120 = 180s` (5m) or `900-120 = 780s` (15m) window.

Most losing trades reverse only partially — the asset reverses from `+12bp` to `0bp` or `-2bp`, which doesn't cross the 5bp threshold. The losing trade stays held to chainlink resolution.

### Why trade #28 is the exception

Trade #28: SOL_5m_SELL, signal=UP, ret_2m=+14.6bp, market resolved Down.
- For SELL to fire, SOL needed to drop from +14.6bp to ≤-5bp from bar-close = ~20bp reversal.
- SOL clearly did this (market settled Down at 88.71 vs strike 89.50).
- `_maybe_sell_at_bid` rev_bp gate opened, `_try_bid_exit` succeeded:
  - `partial_exit_qty` was bid-exited at `partial_exit_price`
  - `realized_via_bid_pnl = -2.82` (loss on the partial slice — better than the -25 chainlink path)
  - Remaining qty went to chainlink → `chainlink_pnl_on_held = -20.19`
  - **Total: −$23.01 vs HOLD/HEDGE on same trade −$25.02 = SELL saved $2.01 on this loss.**

### Empirically — what the asset moved (bps from bar-close at resolution)

For the 23 SELL fills that DIDN'T fire, the asset never crossed -5bp (UP signals) or +5bp (DOWN signals) from bar-close during the holding window. We can't directly observe asset path from resolutions, but `won` rate informs the prior:

| signal direction | n | won | implied final-asset direction |
|---|---:|---:|---|
| UP signals (bought YES) | ~12 | 8 | mostly stayed UP (won) |
| DOWN signals (bought NO) | ~12 | 5 | half reverted (most lost) |

Even on losers, the asset typically reverted only enough to flip the binary outcome (from +14bp to -1bp), not enough to cross the explicit -5bp gate. **The rev_bp gate is calibrated tightly enough that small reversals don't trigger it, even when they're enough to lose the bet.**

---

## 3 · Implications for shadow vs backtest

The +12h shadow showed `partial_bid_exit` fired 1× out of 24+ SELL fills. The backtest in `EXIT_POLICY_TIER1.md` had SELL beat HOLD by ~$0.03/trade because backtest simulated SELL firing on more reversals (different price-path simulation assumptions or different rev_bp threshold).

**The backtest may be over-modeling SELL-fire frequency.** Either:
- Backtest used a different anchor (e.g., entry-price not bar-close)
- Backtest used a smaller rev_bp threshold
- Backtest had perfect book availability (no `no_asks` failures)

This means **the shadow-vs-backtest haircut on SELL is partly attributable to SELL not firing in production**, not to model mis-specification of the alpha. The trades were equivalent to HOLD/HEDGE; the fact that backtest showed `+$22 SELL_$140` for SOL_5m vs +$13 HOLD doesn't translate when SELL never fires.

---

## 4 · Action items

### Priority 1 — clarify the rev_bp anchor in the live transition spec

Before going live with $1, decide whether SELL anchor should be:
- (a) `btc_close_at_ws` (current — measures full-cycle reversal) — keep this, accept low fire rate
- (b) `btc_at_t_plus_120` (the entry anchor) — would fire ~3× more often, but on smaller reversals
- (c) Both — fire on `min(reversal_from_open, reversal_from_entry) ≥ 5bp`

Backtest the three variants on the existing parquet entries before flipping any sleeve live.

### Priority 2 — fix the spurious-skip-loop on HEDGE

When `_maybe_hedge` falls into the `slot.status='held_no_hedge'` branch, the next tick should NOT re-attempt. Either:
- Add `held_no_hedge` to the `_open_slots()` exclusion filter (the comment at line 1962 hints this was attempted), OR
- Mark the slot with a "tried-and-failed" flag, retry only every Nth tick (1× per minute instead of 1× per 10s).

42 skip events per stuck ETH_15m position is wasteful PG writes. Cosmetic, not pnl-impacting, but pollutes the audit table.

### Priority 3 — emit a `sell_bid_check_passed_no_event` heartbeat

Currently when SELL's rev_bp gate is closed (`if not reverted: return`), nothing is written. Hard to diagnose. Add a debug-level event (or postgres counter increment) so we can later verify: "of all the SELL on_ticks, what fraction had rev_bp open vs closed".

### Priority 4 — re-check at +24h with full SELL fire stats

The +24h reading should specifically include:
- Count of SELL fills
- Count of `partial_bid_exit=true` resolutions
- Count of `hedge_policy_branch=sell_bid` skip events
- If sell_bid skips = 0 still, that confirms the rev_bp gate is the bottleneck, not book unavailability.

---

## 5 · Conclusion

Both anomalies are explained by the controller code paths:
- **HEDGE skips > fills**: 1 fill × N retry ticks = N skip events, all attributable to a single stuck position with an empty opposite book. The user's intuition that "skips > fills makes no sense" is correct under the assumption "1 skip = 1 attempt to hedge a different fill"; the code uses "1 skip = 1 retry tick on the same fill".
- **SELL barely fired**: rev_bp gate uses bar-close anchor → effective threshold for SELL_BID = `5bp + |ret_2m|` ≈ 12-30bp opposite reversal, which 23 of 24 fills didn't cross.

Neither is a code bug. The HEDGE retry loop is wasteful (priority 2) but harmless. The SELL anchor design is a **policy choice** worth revisiting before live (priority 1).
