# B945 Tick Timeline Analysis — 2026-06-13

**Wallet:** `0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68` (pseudonym: Noisy-Colonisation, +$21,742 LB canonical)

**Hypothesis tested:** Does he buy the *momentarily dipping* side — buy Up when Up price just fell, buy Dn when Up price just rose — accumulating both sides as price oscillates, targeting sum<1?

**Prior conclusion:** "No signal; buys both sides ~uniformly; delta-contrarian at slug level."

**Session findings:** The tick view reveals a **completely different mechanism** from either the operator's dip-buying hypothesis or the prior uniform-accumulation conclusion. He runs an **inventory-rebalancing engine** over the window: open one side, then continuously hedge the lagging side as prices diverge, rebalancing both until resolution. Details below.

---

## A. Data Sources

- `ml_features.parquet`: 90,922 book snapshots (67,198 fill rows) across 817 btc-15m slugs. Has up_ask/bid/dn_ask/bid + oracle/binance returns at each snapshot.
- `fill_tape_full.parquet`: 144,584 chain-confirmed fills with tx_hash + price + outcome
- `orderfilled_sample.parquet`: 634 OrderFilled on-chain events with MAKER/TAKER classification → 628 mapped to btc-15m slugs
- `trades_polymarket/btc.parquet`: 9,525,267 collector taker prints, 4,163 slugs (Apr 26 → Jun 11)
- `per_slug_paired_ledger.parquet`: 1,564 slug-level PnL summaries with vwap_up/dn, share counts, winner
- L25 orderbook (10Hz native): loaded for 10 chosen slugs

---

## B. Critical Discovery: Fill Leg Taxonomy

The `ml_features.parquet` `leg` column reveals **four fill types**, not two:

| leg | n fills | price_mean | price_median | meaning |
|-----|---------|-----------|--------------|---------|
| `open` | 817 | 0.503 | 0.500 | First fill in the slug — opening position |
| `add` | 3,053 | 0.506 | 0.497 | Adding to same side early (q_opp=0) |
| `rebal` | 31,868 | 0.459 | 0.440 | Buys the **LEADING** side (q_own > q_opp, 99.87% of cases) |
| `hedge` | 31,460 | 0.485 | 0.477 | Buys the **LAGGING** side (q_own < q_opp, 100% of cases) |

**The rebal/hedge distinction is inventory-driven, not price-signal-driven:**
- `q_own > q_opp` (holding more of this side) → `rebal` fill = buys MORE of the LEADING side
- `q_own < q_opp` (holding less of this side) → `hedge` fill = buys the LAGGING side

This is NOT a simple "buy both sides." It is a **continuous rebalancing loop** triggered by inventory imbalance.

---

## C. Slug Selection (seed=20260613)

Pool: 746 btc-15m slugs with ≥30 fills, 624 also with collector coverage. Stratified by UTC hour × winner side.

| slug suffix | dt_utc | hr | winner | pvs | n_fills | open_side | t_open | t_hedge | Δ | P_alt | PnL |
|-------------|--------|-----|--------|-----|---------|-----------|--------|---------|---|-------|-----|
| `1777964400` | 2026-05-05 07:00 | 07 | Up | 0.883 | 128 | UP | +350s | +382s | +32s | 28% | +$188 |
| `1778744700` | 2026-05-14 07:45 | 07 | Down | 0.983 | 46 | DN | +56s | +61s | +5s | 36% | +$5 |
| `1778490000` | 2026-05-11 09:00 | 09 | Up | 0.946 | 72 | DN | +59s | +108s | +49s | 28% | -$29 |
| `1778232600` | 2026-05-08 09:30 | 09 | Down | 1.034 | 53 | UP | +180s | +372s | +192s | 23% | -$56 |
| `1778861700` | 2026-05-15 16:15 | 16 | Up | 0.958 | 102 | UP | +68s | +90s | +22s | 35% | +$48 |
| `1778506200` | 2026-05-11 13:30 | 13 | Down | 1.012 | 174 | DN | +125s | +178s | +53s | 32% | +$12 |
| `1777579200` | 2026-04-30 20:00 | 20 | Up | 1.086 | 67 | UP | +46s | +68s | +22s | 24% | +$103 |
| `1778529600` | 2026-05-11 20:00 | 20 | Down | 1.006 | 148 | UP | +65s | +112s | +47s | 31% | +$45 |
| `1778439600` | 2026-05-10 19:00 | 19 | Up | 1.144 | 34 | UP | +446s | +510s | +64s | 27% | -$76 |
| `1777975200` | 2026-05-05 10:00 | 10 | Up | 1.197 | 40 | DN | +58s | +144s | +86s | 33% | -$153 |

**Columns:** `pvs` = vwap_up+vwap_dn (overround); `t_open/t_hedge` = seconds from slot_start; `P_alt` = side-switch rate between consecutive fills (50% = random).

---

## D. Tick-by-Tick Timeline — Primary Slug

### Slug btc-updown-15m-1778506200
Window: **2026-05-11 13:30 UTC** → +15 min | Winner: **Down** | pvs=1.012 | 174 fills | PnL=+$11.55

**Phase 1 (t=125-178s):** Open Dn side at 0.66, add 8 more Dn fills up to 0.753, q_own grows to 145, q_opp=0.

**Phase 2 (t=178s):** SIMULTANEOUS hedge+rebal within the SAME SECOND:

| t(+s) | leg | Side | Price | q_own | q_opp | up_bid | up_ask | dn_bid | dn_ask | sum_ask |
|-------|-----|------|-------|-------|-------|--------|--------|--------|--------|---------|
| +125 | open | DN | 0.660 | 0 | 0 | 0.35 | 0.36 | 0.64 | 0.65 | 1.01 |
| +178 | add | DN | 0.600 | 145 | 0 | 0.39 | 0.40 | 0.60 | 0.62 | 1.02 |
| +**178** | **hedge** | **UP** | **0.370** | 0 | 153 | 0.35 | 0.40 | 0.60 | 0.62 | 1.02 |
| +**178** | **rebal** | **DN** | **0.600** | 153 | 0 | 0.39 | 0.40 | 0.60 | 0.62 | 1.02 |
| +179 | hedge | UP | 0.380 | 0 | 165 | 0.37 | 0.38 | 0.62 | 0.63 | 1.01 |
| +304 | hedge | UP | 0.100 | 101 | 295 | 0.09 | 0.11 | 0.89 | 0.91 | 1.02 |
| +311 | hedge | UP | 0.080 | 141 | 295 | 0.07 | 0.09 | 0.93 | — | — |
| +321 | rebal | DN | 0.910 | 295 | 161 | 0.09 | 0.10 | 0.90 | 0.91 | 1.01 |
| +391 | hedge | UP | 0.053 | 234 | 375 | 0.04 | 0.05 | 0.96 | — | — |
| +417 | hedge | UP | 0.040 | 254 | 375 | 0.03 | 0.04 | 0.97 | — | — |
| +424 | hedge | UP | 0.030 | 259 | 375 | 0.02 | 0.03 | 0.98 | — | — |
| +459 | hedge | UP | 0.010 | 302 | 375 | 0.01 | 0.02 | 0.99 | — | — |
| +521 | rebal | DN | 0.980 | 375 | 333 | 0.01 | 0.02 | 0.98 | 0.99 | 1.01 |
| +745 | rebal | DN | 0.800 | 537 | 333 | — | — | — | — | — |
| +752 | hedge | UP | 0.640 | 340 | 557 | 0.62 | 0.65 | 0.35 | 0.37 | 1.02 |
| +752 | rebal | DN | 0.540 | 557 | 354 | — | — | — | — | — |
| +753 | hedge | UP | 0.770 | 354 | 612 | — | — | — | — | — |
| +879 | rebal | DN | 0.935 | 1402 | 1322 | 0.03 | 0.04 | 0.93 | 0.96 | 1.00 |
| +886 | rebal | DN | 0.960 | 1453 | 1322 | 0.03 | 0.04 | 0.93 | 0.96 | 1.00 |

**Key observations:**
- At t=321s: buys Dn at 0.910 (rebal, Dn is winning) — pays 91¢ for a token that pays 1.00 = 9¢ edge
- At t=391-459s: buys Up at 0.010-0.053 (hedge, Up is losing) — pays 1-5¢ for a token paying 0
- Contemporaneous pairs: hedge UP@0.370 + rebal DN@0.600 = sum 0.970; hedge UP@0.010 + rebal DN@0.980 = sum 0.990
- The pairing window is NOT just at open — pairs form throughout
- Side sequence (first 20): `DN DN DN DN DN DN DN DN DN UP DN UP UP UP UP UP UP UP UP UP`
- Switch rate: **32%** — significantly below 50% (RUNS not alternation)

---

## E. Quantified Tests (all 817 btc-15m slugs, 67,198 fills)

### E1. Dip-Buying: P(buys the locally-cheaper/dipping side)

Definition: "dip buy" = Up fill after up_mid fell (Δup_mid < 0), OR Dn fill after up_mid rose (Δup_mid > 0 = Dn fell).

| lag | N fills | N dip-buys | P(dip) | 95% CI | p(>50%) | p(≠50%) | Verdict |
|-----|---------|------------|--------|--------|---------|---------|---------|
| 5s | 36,302 | 12,917 | **0.3557** | [0.351, 0.361] | 1.000 | <0.0001 | **ANTI-DIP** — buys the RISING side |
| 10s | 51,769 | 22,416 | **0.4330** | [0.429, 0.437] | 1.000 | <0.0001 | **ANTI-DIP** |
| 30s | 64,214 | 33,741 | **0.5255** | [0.522, 0.529] | <0.0001 | <0.0001 | Slight dip (sig) |

**P_dip = 0.356 at 5s = STRONGLY ANTI-DIP.** He buys the RISING side 64% of the time on a 5s window. This is the **opposite of dip-buying**.

**Mechanistic explanation:** The 5s anti-dip is because `rebal` fills (the majority, n=31,868) BUY the WINNING/RISING side. When Dn is winning, up_mid falls → Dn price rises → rebal buys Dn (the rising side = anti-dip). The inventory rule doesn't care about short-term price moves; it cares about which side has more shares. The 30s slight dip signal (0.526) reflects that over longer horizons, both sides trade near mid and mean-revert slightly.

### E2. Alternation / Oscillation

- Total transitions: **66,369** across 816 slugs
- Alternations: **19,353 (29.2%)**
- Median per-slug P_alt: **30.4%**
- Binomial test vs 50%: **p < 1e-10**

**SIGNIFICANT RUNS (p < 1e-10), NOT alternation.** P_alt = 29.2% << 50% means he fires **same-side bursts** (multiple `hedge Up` fills in a row, then multiple `rebal Dn`, etc.). This is the direct signature of the inventory-rebalancing engine: it runs ladder bursts on one side before switching.

**This definitively disproves the oscillation-harvesting hypothesis.**

### E3. Price Drift Within Legs

| leg | mean corr (price vs fill order) | n slugs | t | p |
|-----|--------------------------------|---------|---|---|
| Up fills | +0.008 | 805 | 0.29 | 0.771 |
| Dn fills | **-0.075** | 800 | -2.84 | **0.005** |

Dn fills show SIG negative corr: he accumulates Dn at progressively lower prices on average. This is consistent with early Dn fills at ~0.60 (open/add) then late Dn fills at very high prices (0.90-0.97) when Dn is winning (rebal), creating a bimodal distribution that correlates negatively with order number in losing-Dn slugs.

### E4. Price Level Structure

HHI (1¢ bins): Up=0.01063, Dn=0.01080, uniform=0.01000 — **essentially uniform, no discrete level clustering.** Fills happen wherever the book offers at the time of the rebalancing trigger. No "GTC ladder at fixed prices" structure.

### E5. Maker vs Taker

- 628 btc-15m fills in orderfilled_sample
- **MAKER: 394 (62.7%)** | TAKER: 234 (37.3%)

63% maker = primarily passive limit orders at the current book bid. He places limits at or near the top-of-book and waits for takers to come to him.

### E6. Contemporaneous Hedge+Rebal Pair Quality

Across 2,748 hedge+rebal pairs occurring within 30s of each other (sample of 100 slugs):
- Mean sum_cost: **0.9552**
- Median sum_cost: **0.9800**
- % pairs with sum_cost < 1.00: **58.7%**
- % pairs with sum_cost < 0.95: **34.6%**

Over half of his within-window pairs capture a sub-1.00 sum — the arb is spread throughout the window, not just at open.

---

## F. Synthesis — The Rebalancing Engine

**Complete mechanism from tick sequence:**

1. **Pre-window (hours before):** Places GTC limit orders on BOTH sides, establishing queue priority (confirmed from prior session's article analysis)

2. **Phase 1 — Open (0-200s):** First fill `open` at ~50¢ on one side. Then `add` to build position. Other side q_opp=0.

3. **Phase 2 — Hedge initiation:** Once q_own is established, triggers the FIRST `hedge` fill on the other side (Δt = 5-192s after first open). This is the first "paired" fill.

4. **Phase 3 — Rebalancing loop (continuous):**
   - `q_own > q_opp` → `rebal`: buy more of the LEADING side at its current price (high if winning, low if losing)
   - `q_own < q_opp` → `hedge`: buy the LAGGING side at its current price
   - Both can trigger simultaneously within the same second
   - Pairs formed throughout create the arb capture (58.7% sum < 1.00)

5. **Phase 4 — Late window (700-900s):** Aggressive rebalancing as resolution approaches. Prices diverge to extremes (0.01/0.99). He buys BOTH extremes — paying 99¢ for the winner and 1¢ for the loser.

6. **Resolution:** Redeems matched pairs (paired_gross). Residual position in winner/loser depends on final inventory balance (only 36.9% of slugs have net winner excess — the profit is primarily from the pair arb, not directional).

**Why this explains ALL the prior findings:**
- "No entry signal (AUC=0.53)": confirmed — the open side is not chosen by prediction
- "Delta-contrarian": the hedge leg IS contrarian to the current delta (buys the losing side)
- "78% fire in first 60s": only the OPEN fill; the 90% of fills happen after t=120s
- "No ML signal": the trigger is inventory-driven, not price-predictive

---

## G. Verdict on Operator Hypothesis

**Operator's hypothesis: "He buys one side at ~0.40, waits, when the price dips (that side falls to ~0.35) he buys the OTHER side, and keeps harvesting the oscillation."**

| Component | Status | Evidence |
|-----------|--------|----------|
| Buys both sides | Confirmed | 99.5% slugs paired |
| Targets cheap prices | Confirmed for hedge leg | hedge Up at 0.01-0.37 when Up is losing |
| Waits before buying 2nd side | Confirmed | Δt = 5-192s |
| Reacts to price DIP | **Rejected** | P_dip=0.356 at 5s — buys RISING side |
| Oscillation harvesting | **Rejected** | P_alt=29% << 50% — runs not alternation |
| "Harvesting" the oscillation | **Rejected** | He rebalances until resolution; no exit |

**Correct restatement:** He opens one side, then mechanically hedges via inventory rule (not price signal). The "cheap price" he pays for the hedge is a consequence of the other side winning (prices diverge), not a signal he detected. The "waiting" is just the time it takes for inventory imbalance to accumulate to trigger the hedge. There is NO oscillation — he fills in same-side bursts (runs).

---

## H. Impact on TVRUST Entry Logic

**Prior spec:** GTC ladders at fixed levels ~24h pre-window.

**Additions from tick analysis:**

1. **No dip-timing logic needed.** Do NOT wait for a price drop on the second side. Start hedging as soon as the first side is established. The inventory rule (q_own vs q_opp) drives the trigger.

2. **The paired arb window is throughout the 15m window.** Pairs can be formed at sum<1 anywhere from t=0 to t=900s. No need to rush everything into the opening seconds.

3. **Rebalancing is active and aggressive in the final 200s.** TVRUST needs to fire fills at extreme prices (0.01-0.10 for losing side, 0.90-0.99 for winning side) in the last 3 minutes. This requires the engine to be RUNNING during that phase, not just at open.

4. **62.7% MAKER** — place near-mid limit orders and let takers fill you. No market-order dip-chasing.

5. **Both sides get rebalanced continuously — position is NOT held static.** TVRUST must track q_own/q_opp and keep issuing limit orders on the imbalanced side. A static "place orders once and wait" spec misses the ~64 fills/slug activity.

---

*Generated by `strategy_lab/wallet_hunt/_b945_tick_timeline.py` — 2026-06-13*
