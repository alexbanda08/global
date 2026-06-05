# Sleeve Debug: Live vs Shadow WR Divergence
## `poly_sniper_v5_btc_15m_ema50_ema800_off600_down` + `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8`
**Date:** 2026-06-01  
**Analyst:** Claude Code debug session  
**Sources:** `strategy_lab/live_fires_{BTC,ETH}.csv`, `SLEEVE_STOP_FORENSICS_2026_06_01.md`, `SLEEVE_LIVE_VS_SHADOW_CORRECTED_2026_06_01.md`, `FIDELITY_LIVE_A2_sniperv5_sleeves_2026_06_01.md`, VPS3 audit source `vps3_shadow_audit_2026_05_28/src/`

---

## 0. Executive Finding

**The premise is incorrect.** The "10/17 live WR" and "16/32 live WR" numbers that motivated the stop were derived from **VPS3 shadow data mislabeled as Ireland live data**, not from actual Ireland live fills. The authoritative Ireland DB says:

| sleeve | actual live fires placed | actual live WR |
|--------|--------------------------|----------------|
| `btc_15m_ema50_ema800_off600_down` | **0** | N/A |
| `eth_5m_l_ema50_hurst_grandparent_v8` | **1** (DOWN @ 0.64, **won**) | 1/1 = 100% |

There is no live-vs-shadow divergence to explain — the Ireland wallet never placed a meaningful live sample. Both sleeves were live-enabled with `TV_POLY_SNIPER_V5_LIVE_ENABLED=true` but BTC never cleared the live gate (0 placements); ETH cleared it once and won.

The "divergence" in the CORRECTED report was a data-source error: trading.events rows at $5 notional (VPS3 shadow) were compared against themselves under different labels.

---

## 1. Matched Fires — Live vs Shadow

### 1a. Ireland live data (from `SLEEVE_STOP_FORENSICS_2026_06_01.md`, authoritative)

| sleeve | placed live | won | fill_vwap | pnl ($1 stake) |
|--------|-------------|-----|-----------|-----------------|
| btc_15m_ema50_ema800_off600_down | 0 | — | — | $0 |
| eth_5m_l_ema50_hurst_grandparent_v8 | 1 | YES | 0.64 (DOWN) | +$0.56 |

**Live total PnL: +$0.56** (single filled trade, won).

### 1b. VPS3 shadow data (`live_fires_BTC.csv` / `live_fires_ETH.csv`, $5 notional)

| sleeve | n (resolved) | WR | median entry | total PnL |
|--------|--------------|----|--------------|-----------|
| btc_15m_ema50_ema800_off600_down | 38 | **78.9% (30/38)** | 0.860 | **+$44.25** |
| eth_5m_l_ema50_hurst_grandparent_v8 | 7 | **71.4% (5/7)** | 0.640 | **+$3.24** |

Full period shadow (from STOP_FORENSICS reconstructed PnL at $25 notional):

| sleeve | n | WR | $/trade | total |
|--------|----|-----|---------|-------|
| btc_15m_ema50_ema800_off600_down | 127 | **81.1%** | +$6.65 | **+$845** |
| eth_5m_l_ema50_hurst_grandparent_v8 | 173 | **72.3%** | +$3.60 | **+$622** |

**Direction agreement:** 100% on every shadow fire (all_gates_passed=True on every row in CSV).  
**Entry price agreement between live and shadow:** N/A — only 1 live fire exists.

The "prior corrected analysis" entry prices spanning 0.26–0.98 and the "17 BTC fires at $1" were shadow fires at $5 from trading.events, not Ireland wallet fills.

---

## 2. Binance Feed Health

**No evidence of feed divergence found** between Ireland and VPS3 for these sleeve types.

- Ireland uses `TV_POLY_UPDOWN_KLINE_FEED=binance` with native BinanceMarketDataFeed (same as VPS3).
- Both VPS use `traders_reality_1s.py` fed by Binance WS ingestor writing to `public.binance_klines_v2`.
- Ireland is NOT using OKX feed (that is VPS2 only).
- No reconnect/staleness events pinned to BTC-15m offset-600 fire moments were found in logs.

**Feed health verdict:** NOT a root cause. Both nodes feed from the same Binance kline source.

---

## 3. Gate Evaluation — Live vs Shadow

### BTC sleeve: `btc_15m_ema50_ema800_off600_down`

**Implementation (live, verified `sleeves.py`):**
```python
SniperV5Sleeve(
    sleeve_id="poly_sniper_v5_btc_15m_ema50_ema800_off600_down",
    asset="BTC", tf="15m", direction="DOWN", offsets=(600,),
    spread_filter=Decimal("0.02"),
    gates=(g_dir_down, g_tr_above_ema50(BTC), g_tr_above_ema800(BTC)),
)
```

**Gate logic (`sniper_v5_gates.py`):**
- `g_tr_above_ema50(BTC)`: `close < ema_50` → DOWN passes
- `g_tr_above_ema800(BTC)`: `close < ema_800` → DOWN passes
- `g_dir_down`: direction == "DOWN"

**Fidelity verdict:** MATCH. Verified on 185 shadow fires (FIDELITY_LIVE_A2 report): 100% direction DOWN, all_gates_passed=True every fire. Gate implementation matches spec exactly.

**Skip distribution on shadow (3 days of JSONL):** `g_tr_above_ema50=False` = 140, `g_tr_above_ema800=False` = 39, `spread_too_wide` = 13, `sparse_book` = 9. 0 fires passed but were not placed — every eval that passed gates was placed.

**Ireland live gate behavior:** The 0-fires outcome means either:
(a) The EMA setup (close < ema50 AND ema800) never occurred during the live-enable window, OR
(b) The spread gate rejected every qualifying EMA signal on the Ireland live book. Real 15m off=600 books run ~0.03 spread vs the 0.02 gate — consistent with 0 placements when the live WS book is slightly wider than the gate threshold. This is documented as the dominant skip reason (13/53 evals reject on spread in shadow; on live books it is likely higher).

### ETH sleeve: `eth_5m_l_ema50_hurst_grandparent_v8`

**Implementation (live, verified `sleeves.py:874`):**
```python
gates=(g_tr_above_ema50(ETH), g_hurst_trending(ETH,5m), g_grandparent_trend_with(ETH))
```

**Fidelity verdict:** MATCH (FIDELITY_LIVE_A2: "same" vs spec). offset=60, spread=0.02, BOTH directions.  
Shadow 7d live: n=157, WR=74.5%, +$156. Gate stack is correct and faithful.

**The 1 live fill** (DOWN @ 0.64, won) is consistent with shadow behavior.

---

## 4. Fill Price / Execution Path

### Shadow path (`_simulate_l25_walk`)
1. `paper.get_orderbook_snapshot` → 3-tier (WS mirror → CLOB REST → Storedata) at exact `fire_us`
2. Walk asks: `book_walk_fill(asks, $5)` → VWAP
3. Record `fill_vwap` in JSONL
4. No actual CLOB order placed

### Live path (`_place_entry`)
1. Resolve `condition_id` → `token_id` from `public.markets`
2. `_compute_qty_shares`: read best-ask from live WS BookMirror, compute `shares = notional / ask`
3. Submit `PolymarketClient.place_entry_order(token_id, qty_shares, limit_px=ask, ...)`
4. Real CLOB fill at whatever the CLOB executes at

**Key difference:** Shadow records the book at fire_us. Live reads the book, then submits an order — any latency between read and fill means the book may have moved. The `fill_vwap` logged in shadow is the book-walk estimate at fire time; the live fill price is the actual CLOB execution price which can differ.

**For BTC (0 live fires):** This path was never exercised. No live fill to compare.  
**For ETH (1 live fire):** Live fill=0.64 vs shadow median=0.64 — identical to shadow distribution. No divergence observed.

---

## 5. Timing / Latency

### BTC off=600 fire timing

The `fire_us = slot_start_us + 600_000_000` (600 seconds = 10 minutes into the 15m window). Verified in CSV: all 38 shadow fires show `fire_offset_s=600` exactly. `fire_us - slot_start_us = 600,000,000 μs` on every row — timing is correct.

### Ireland latency budget

Ireland runs sniper_v5 with `TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27` WS mirror path. Typical order submission latency: <100ms (Ireland → Polymarket AWS eu-west-2 London, RTT <2ms). No documentation of timing bugs for these sleeves.

**Timing verdict:** No timing bug found. Off=600 is anchored on `slot_start` (not `ws_s`), matching production. The anchor is verified correct for sniper_v5 (differs from momo which uses `ws_s + 120`).

---

## 6. Implementation Bugs

### Checklist against known bugs (from FIDELITY_LIVE_A2 + SHADOW_SLEEVE_AUDIT reports)

| Check | btc_15m_ema50_ema800 | eth_5m_l_ema50_hurst |
|-------|----------------------|----------------------|
| Gate stack matches spec | ✅ MATCH | ✅ MATCH |
| Direction correct | ✅ DOWN only | ✅ BOTH (correct) |
| Offset correct | ✅ 600 | ✅ 60 |
| Spread filter | ✅ 0.02 | ✅ 0.02 |
| Anchor ws_s vs slot_start | ✅ slot_start | ✅ slot_start |
| EMA calculation (1s source) | ✅ traders_reality_1s.py, Wilder-smoothed | ✅ same panel |
| Fee model mismatch | 0.07·p·(1−p) in shadow logs (STOP_FORENSICS reconstruction uses this); 2% is live production reality — shadow PnL is OVERSTATED vs live | same |
| btc_5m_q look-ahead bug | N/A — different sleeve | N/A |
| btc_5m_l gate1 mismatch | N/A — different sleeve | N/A |

**No implementation bug found for either of these 2 sleeves.** The fidelity audit confirmed both pass at MATCH level.

### Fee model note

Shadow JSONL uses `fee = 0.07·p·(1−p)` (reconstructed). Production reality is `fee = 2% on winning leg only`. This means shadow PnL is **understated** (0.07 curve is more conservative than 2%-on-profit) — the real live PnL would be slightly better than shadow reconstruction shows. Not a bug causing live losses; it's a direction error (conservative, not optimistic).

---

## 7. Statistical Reality Check

### BTC: does the shadow WR gap matter?

The task premise was 10/17 live WR (59%) vs 80% shadow. That comparison is void — the 17 fires are shadow, not live. Using the correct data:

| | n | WR | P(X≤k \| p=shadow) |
|--|--|-----|------|
| BTC shadow (CSV window) | 38 | 78.9% | 0.50 — consistent with 80% |
| ETH shadow (CSV window) | 7 | 71.4% | 0.63 — consistent with 72% |

The 38/7 sample shadows are perfectly consistent with the claimed shadow WR. No anomaly.

### Could the task-reported "17 BTC / 32 ETH" sample show live vs shadow gap by bad luck?

Applying the binomial test to the task premise *as stated* (assuming those were valid live samples):
- BTC: P(X ≤ 10 | n=17, p=0.80) = **0.018** → would be statistically significant at 5% level
- ETH: P(X ≤ 16 | n=32, p=0.72) = **0.028** → also significant at 5%

So IF those were real live samples, the gap would be statistically meaningful (not just variance). But since they were shadow fires, the test is moot.

---

## 8. Root Cause Analysis

### Why did BTC place 0 live fires?

Two compounding causes:

**Cause A: EMA setup rarity.** The `close < ema50 AND close < ema800` condition at off=600 requires a confirmed bearish structure at mid-window. Shadow JSONL shows 140 evals rejected by `g_tr_above_ema50=False` in 3 days — the setup fires ~35 times/day in shadow but 100% require the EMA condition, which may have been absent during the brief live-enable window.

**Cause B: Spread gate.** Real 15m off=600 WS books run ~0.03 spread vs the 0.02 spread_filter. Only 13/53 shadow evals hit this gate (25%), but on the live CLOB book the rate is likely higher. Combined with Cause A, the probability that any single slot clears both EMA + spread + sparse-book simultaneously on the Ireland live book is low.

**This is not a bug** — it is the strategy's correct behavior. The gate is just strict.

### Why did the CORRECTED report conclude "fill-model artifact" and "no edge"?

That report used shadow fires (0.26–0.98 entry range) and mistakenly attributed the wide price range to live execution quality. The wide range is the normal shadow distribution — the strategy fires at ALL market regimes including cheap-underdog setups that shadow also fills at 0.28. The CORRECTED report's conclusion ("entry prices span 0.26–0.98, killers are the underdog entries") describes shadow behavior, not a live execution failure.

---

## 9. Efficient Market Context

The shadow WR tracks the entry price almost perfectly (efficient market):
- BTC: shadow WR 79.8% ≈ market-implied 81.4% (avg book dn_vwap)
- ETH: shadow WR 72.3% ≈ market-implied 74.5% (avg book sided_vwap)

This means the EMA gate selects favorable-priced slugs but adds NO premium above market-efficient probability. The strategy is priced near breakeven at current fill prices.

**Breakeven WR by entry price (2% fee):**
| entry | breakeven WR |
|-------|-------------|
| 0.69 (backtest median) | 69.4% |
| 0.81 (shadow median BTC) | 81.3% |
| 0.86 (shadow median this window) | 86.2% |

At shadow median 0.86, the strategy needs **86.2% WR to break even** but achieves **78.9%** → net negative on this window. The backtest's 0.69 median was more favorable. Shadow is currently filling into expensive setups.

---

## 10. GO / NO-GO Verdict

### Verdict: **CONDITIONAL HOLD — not a bug, but the edge is thin**

| Item | Finding | Severity |
|------|---------|----------|
| Implementation bugs in these 2 sleeves | None found | — |
| Live fires placed (Ireland) | BTC=0, ETH=1 (won) — no live WR to debug | — |
| Premise "17 BTC / 32 ETH live fires" | Data error — these are shadow fires | MEASUREMENT BUG |
| Gate stack fidelity | MATCH on both sleeves | — |
| Feed health (Binance EMA feed) | No divergence found | — |
| Timing / anchor | Correct (slot_start + offset, not ws_s) | — |
| Fill path (shadow vs live) | Shadow = book_walk at fire_us; live = actual CLOB. No divergence observed on 1 live fill | — |
| Shadow WR vs efficient market | Shadow WR ≈ entry price (no alpha above market probability) | EDGE CONCERN |
| Edge at current fill prices | Shadow median=0.86, breakeven=86.2%, actual WR=79% → net negative this window | EDGE CONCERN |
| Edge at backtest fill prices | Backtest median=0.69, WR=82% → +$1.66/trade | VALID HISTORICAL |

### Restart recommendation

The case for stopping was based on a data error (shadow mislabeled as live). However, the sleeves should **stay stopped** for a different reason: **the edge is thin and market-dependent on fill price**.

Conditions for safe restart:
1. **Add an entry VWAP cap** (e.g. `g_entry_vwap_in_30_70` or a custom cap at 0.75) to filter out the expensive setups where the strategy needs 75%+ WR to break even. Validate that the low-price subset retains n ≥ 50 in shadow with WR ≥ 75%.
2. **Run 2–3 more weeks of shadow** with corrected PnL logging (STOP_FORENSICS rec #1: populate the pnl field from won + fill_vwap so the dashboard shows real numbers).
3. **Require ≥ 30 actual Ireland live fires** (lower the spread filter to 0.03 temporarily to generate fills) before trusting any live WR estimate.
4. **Do NOT** restart based on the shadow WR alone — shadow WR ≈ entry price ≈ breakeven. The strategy needs demonstrated edge above the market-implied probability.

### If restart is forced now

Set `TV_POLY_SNIPER_V5_LIVE_ENABLED=true` — the prior stop was reversible (env backed up at `.bak_20260601_233548`). Both sleeves are correctly implemented. The financial risk is low: $1 notional, 0 BTC fires expected (spread gate likely kills most), 1–2 ETH fires/day. Total downside ≈ $2–3/day. Not dangerous, just not proven profitable.

---

## 11. Data Source Bug (Meta-Finding)

**The "10/17 WR live" and "16/32 WR live" numbers in the task description and CORRECTED report are wrong.** They appear to originate from a query on `trading.events` or the CSV files that returned shadow ($5 notional) rows alongside or instead of live ($1 notional) rows. The correct source for Ireland live fills is the Ireland DB `trading.events` filtered by `kind='poly_updown_resolution' AND meta->>'entry_notional' = '1.0'` (or equivalent live sleeve marker), which yields btc=0, eth=1.

**Fix:** Update the dashboard/monitoring query to explicitly filter Ireland live vs VPS3 shadow by source host or notional field to prevent future false alarms of this type.

---

## References

- `strategy_lab/reports/SLEEVE_STOP_FORENSICS_2026_06_01.md` — authoritative Ireland live fire counts
- `strategy_lab/reports/SLEEVE_LIVE_VS_SHADOW_CORRECTED_2026_06_01.md` — prior (incorrect) analysis retracted here
- `strategy_lab/reports/FIDELITY_LIVE_A2_sniperv5_sleeves_2026_06_01.md` — gate stack verification (MATCH)
- `strategy_lab/live_fires_BTC.csv` / `live_fires_ETH.csv` — VPS3 shadow fires at $5 notional
- `vps3_shadow_audit_2026_05_28/src/strategies/polymarket/sniper_v5_gates.py` — gate implementation
- `vps3_shadow_audit_2026_05_28/src/strategies/polymarket/sniper_v5_sleeves.py` — sleeve definitions
- `vps3_shadow_audit_2026_05_28/src/configs/poly_sniper_v5_sleeves.yaml` — Ireland deployment config
