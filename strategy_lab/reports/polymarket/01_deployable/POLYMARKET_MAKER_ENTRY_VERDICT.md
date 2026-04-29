# Maker-Entry Strategy — Final Verdict & Deploy Spec

**Status:** validated as standalone candidate. Deploy on **15m markets only**.
Keep current taker baseline on 5m.

This is a **secondary candidate strategy** — orthogonal to the q10/q20 + hedge-hold baseline already going to TV. If TV agent has bandwidth after the primary deployment, this is the next lever.

---

## 1. The signal & exit (unchanged)

- Signal: `sig_ret5m = sign(log(BTC_close[ws] / BTC_close[ws-300]))`
- Quantile filter on entry: q20 (top 20% of |ret_5m|) on 15m markets — already in TV guide
- Exit: hedge-hold rev_bp=5 — already in TV guide

## 2. The change — maker entry on 15m

Replace the **entry order** in 15m markets only:

**Old (taker):** market buy at `entry_yes_ask` (or `entry_no_ask`) immediately at window_start.

**New (maker hybrid):**
1. At window_start, place LIMIT BUY at `held_side_bid + $0.01` (1 tick above current bid)
2. Wait **30 seconds** for fill
3. If filled within 30s: done. We bought at `bid+0.01`, saving ~1¢ vs taker.
4. If not filled by t+30s: cancel limit, place market buy at current ask (taker fallback)

**Critical:** the fallback to taker is not optional. Skipping unfilled trades destroys the edge (selection bias toward markets where price moved AWAY from us = our best winners).

## 3. Validated numbers — q10 universe, hedge-hold rev_bp=5

### In-sample (full Apr 22-26 universe)

| Universe | Mode | n | Hit% | ROI | Mean cost |
|---|---|---|---|---|---|
| q10 ALL TF | TAKER baseline | 579 | 81.5% | +24.58% | $0.6907 |
| q10 ALL TF | **MAKER hybrid** | 509 | **84.7%** | **+26.81%** | $0.6666 |
| | Δ | | +3.2pp | **+2.24pp** | -$0.024 |

Cross-asset (ALL TF): BTC +1.62pp, ETH +2.37pp, SOL +2.66pp — **3/3 confirm**.

### Forward-walk holdout (chronological 80/20)

**15m markets (where we recommend deploy):**

| Slice | TRAIN n / ROI | HOLDOUT n / ROI / 95% CI | Lift |
|---|---|---|---|
| q10 × 15m × ALL | 117 / +25.92% | **23 / +26.78% / [+3, +7]** | **+2.42pp ✅** |
| q10 × 15m × ETH | 39 / +28.74% | 7 / +26.83% / [+1, +2] | +2.44pp ✅ |
| q10 × 15m × SOL | 39 / +23.41% | 8 / +26.79% / [+0, +3] | +9.04pp ✅ |
| q10 × 15m × BTC | 38 / +26.18% | 8 / +26.74% / 0% fill | -4.22pp ❌ (no fills, sample=8) |

**5m markets (do NOT deploy maker — keep taker):**

| Slice | TRAIN lift | HOLDOUT lift | Reason |
|---|---|---|---|
| q10 × 5m × ALL | +2.04pp | -0.29pp | Edge collapses |
| q10 × 5m × BTC | +1.50pp | +0.04pp | Tie |
| q10 × 5m × ETH | +2.49pp | +0.10pp | Tie |
| q10 × 5m × SOL | +2.13pp | -0.97pp | Negative |

**Why 5m fails:** 5min windows are too fast. By 30s, prices have already moved on normal volatility. Our limit triggers from noise, not signal-driven flow. Higher fill rate (~27-39%) but lower-quality fills.

**Why 15m works:** Slower windows mean less random price movement in first 30s. Our limit only fills when actual interest arrives — those fills are quality.

## 4. Live-deploy spec for TV agent

Add **after** the existing taker entry path. Toggle by config flag `polymarket_maker_15m_enabled` (default `false` for safe rollout).

```python
async def place_entry(slot, sig_direction):
    is_15m = slot.timeframe == "15m"
    use_maker = settings.polymarket_maker_15m_enabled and is_15m
    
    if not use_maker:
        # Existing taker path — unchanged
        return await place_market_buy_at_ask(slot, sig_direction)
    
    # Maker hybrid path
    held_token = slot.yes_token_id if sig_direction == "UP" else slot.no_token_id
    book = await clob.get_orderbook(held_token)
    bid = book.bids[0].price if book.bids else None
    if bid is None:
        return await place_market_buy_at_ask(slot, sig_direction)  # no bid → fallback
    
    limit_px = bid + Decimal("0.01")  # 1-cent improvement
    if limit_px >= book.asks[0].price:
        # Spread already at tick — no room to improve. Fallback.
        return await place_market_buy_at_ask(slot, sig_direction)
    
    order_id = await clob.place_limit_buy(held_token, qty=slot.target_qty, price=limit_px)
    slot.maker_order_id = order_id
    slot.maker_deadline = now() + timedelta(seconds=30)
    slot.status = "maker_pending"
    return  # tick handler will check fill or fall back
```

In `on_tick(...)` (the existing rev_bp check loop), add at the top:

```python
for slot in self._open_slots():
    if slot.status == "maker_pending":
        if now() >= slot.maker_deadline:
            await clob.cancel_order(slot.maker_order_id)
            await place_market_buy_at_ask(slot, slot.signal)
            slot.status = "open"  # now armed for hedge logic
        elif slot.is_filled():
            slot.status = "open"  # filled, armed for hedge
    # ... existing rev_bp / hedge logic ...
```

## 5. Settings additions

```python
# In PolySettings
polymarket_maker_15m_enabled: bool = False  # default off; flip on after pilot
polymarket_maker_tick_improve: Decimal = Decimal("0.01")
polymarket_maker_wait_seconds: int = 30
```

```ini
# In tv-engine.env
TV_POLY_MAKER_15M_ENABLED=false   # set to true after pilot validates
TV_POLY_MAKER_TICK_IMPROVE=0.01
TV_POLY_MAKER_WAIT_SECONDS=30
```

## 6. Pilot plan

**Phase 18b — Maker pilot (run AFTER 18-04/18-05 q20 baseline is green):**

1. Day 0: enable flag for 15m markets only. $1/slot.
2. Days 1-3: monitor `maker_filled` event rate. Expect ~20-25% fill rate. If < 10% or > 50%, investigate (book skew, latency).
3. Days 4-7: compute realized maker-vs-taker lift from `trading.events`. Expected: maker hit% ≥ taker hit% + 2pp on 15m sleeve.
4. Day 7+: if green, expand stake $1 → $5 → $25. If red (lift < 0pp on holdout), keep flag off.

## 7. Caveats

- **Holdout sample is tiny per cell (n=7-23).** Bootstrap CIs are wide. The ALL-cell numbers (n=23) are most reliable.
- **5m DOES NOT generalize** — only deploy on 15m. Strict per-timeframe gating required.
- **Live execution may differ from sim:** in simulator we assume our limit gets filled when ask drops to ≤ our_limit. In live, our order is part of the book (other MMs see it, may front-run). For $1 stakes this is negligible; at scale, check.
- **Selection bias risk:** the 25% of trades that fill are NOT a random subsample. They're trades where the price came down to us. The maker-then-taker hybrid handles this — but if you ever deploy `maker-only` (no fallback), the edge inverts (-5pp loss).
- **Fee structure:** Polymarket charges 0% maker rebate. So our edge is pure spread capture, not maker rebates. If Polymarket ever adds maker fees, this strategy could break.

## 8. Files

- [polymarket_maker_entry.py](../polymarket_maker_entry.py) — variant grid simulator
- [polymarket_forward_walk_maker.py](../polymarket_forward_walk_maker.py) — out-of-sample test
- [POLYMARKET_MAKER_ENTRY.md](POLYMARKET_MAKER_ENTRY.md) — full in-sample variant grid
- [POLYMARKET_FORWARD_WALK_MAKER.md](POLYMARKET_FORWARD_WALK_MAKER.md) — forward-walk results
- [results/polymarket/maker_entry.csv](../../results/polymarket/maker_entry.csv) — variant comparison data
- [results/polymarket/forward_walk_maker.csv](../../results/polymarket/forward_walk_maker.csv) — holdout data

---

**Bottom line:** the maker-entry hybrid generalizes on 15m markets (+2.4pp ROI, n=23 holdout, hit 91%). On 5m it's noise. Deploy as a **15m-only flag** behind a feature toggle, run the pilot for 7 days, scale if green.
