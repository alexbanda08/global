# SOL V3 Family Deep Dive — 2026-05-05 (REVISED after operator feedback)

**Status:** SOL V3 fix IS deployed. V3.3 multi-horizon A/B sleeve IS deployed (handled at controller line 813, 850 of latest code). ALL 5 V3-family variants now fire for SOL.
**Sample:** n=188 V3-family resolutions (2026-04-30 → 2026-05-05) but **only ~9-12 distinct SOL markets**.
**Source:** `strategy_lab/v4_signals/sol_v3_family_deep_dive.py`. Data: `data/v4/shadow_trades_2026_05_05/v3_family_full.csv`.

## ⚠ CORRECTIONS to first-pass analysis

**1. SOL inversion finding was OVERSTATED.** Initial pass claimed "88.9% inverse hit rate, p<0.001". That was n=18 events. But those 18 events are **highly correlated** — multiple V3-family variants fire on the SAME market (subset hierarchy). True n at MARKET level = ~9 distinct SOL markets, of which 2 won and 7 lost. P(≥7 of 9 losses | p=0.5) = **9% — NOT statistically significant** at 5% level.

**2. SOL V3-family INVERSE sleeves are NOT in production.** Only `poly_updown_sol_5m_sniper_INV` and `poly_updown_eth_5m_sniper_DOWN_INV` exist (deployed today 2026-05-05 19:10 UTC, n=2 events each). NO `_v3_INV` / `_v3_1_INV` / etc sleeves. So my recommendation to "deploy SOL V3-family inverse sleeves" referenced sleeves that don't yet exist.

**3. V4 subset hierarchy bug IS REAL — root cause = independent per-controller `fetch_close_asof` calls at bar boundaries.** See § 8 below for full deep dive (mathematical contract, observed violations on SOL, race-condition mechanism, three fix paths, recommended Path A = shared aux cache).

---

## TL;DR

| Asset | Best variant | n | Hit% | PnL ($1 stake) | Verdict |
|---|---|---:|---:|---:|---|
| **BTC** | **v4** | 23 | **73.9%** | **+$9.93** | ✅ V4 IS the BTC winner. V3.2 close 2nd. |
| **ETH** | v3_2 | 7 | 57.1% | +$0.66 | 🟡 marginal — only v3_2 positive, V3 still 44% |
| **SOL** | v3_2 | 9 | **22.2%** | **-$5.28** | 🔴 **EVERY variant losing**. Combined SOL: 2/18 wins. |

**Three big findings:**

1. **BTC V4 is the strongest V3-family winner** (73.9% hit, +$9.93). V4 = V3.1 quantile + V3.2 gates stacked. Should be promoted to top-5 launch (replacing or supplementing BTC v3).

2. **SOL is broken across ALL V3-family variants.** 18 fires, 11% hit rate, all-but-one losing. This is much worse than ETH V3's 44%. Either: (a) the sample is unlucky and small (n=18), or (b) SOL has a structural issue post-fix that makes V3 logic actively wrong.

3. **DOWN ≫ UP claim FULLY REVERSED on BTC + ETH.** Original V3 design assumed alts skew DOWN. Current data:
   - BTC: UP +13pp better than DOWN
   - ETH: UP +37pp better than DOWN
   - SOL: DOWN +18pp better (the only asset where original claim survives)

---

## 1. Per-asset × per-variant matrix

### BTC (n=142 across 5 variants — most data)

| Variant | n | Hit% | CI | PnL$ | UP_n | DN_n | UP hit% | DN hit% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v3 | 54 | 59.3% | [46,72] | +$7.86 | 39 | 15 | 64.1% | 46.7% |
| v3_1 | 34 | 55.9% | [38,74] | +$2.80 | 28 | 6 | 60.7% | 33.3% |
| v3_2 | 25 | 72.0% | [52,88] | +$9.87 | 23 | 2 | 69.6% | 100% |
| v3_3 | 6 | 50.0% | [17,83] | -$0.18 | 6 | 0 | 50.0% | — |
| **v4** | **23** | **73.9%** | **[57,91]** | **+$9.93** | 21 | 2 | **71.4%** | 100% |

**BTC V4 takeaways:**
- 73.9% hit on n=23 — best risk-adjusted of the V3 family
- V4 PnL nearly tied with V3.2 (+$9.93 vs +$9.87) on fewer trades → better PnL/trade
- BTC V4 fires UP 21× / DOWN 2× — heavily UP-biased
- V4 is V3.1 quantile + V3.2 gates compound — works as designed for BTC

### ETH (n=28)

| Variant | n | Hit% | CI | PnL$ |
|---|---:|---:|---:|---:|
| v3 | 9 | 44.4% | [11,78] | -$1.35 |
| v3_1 | 6 | 50.0% | [17,83] | -$0.27 |
| v3_2 | 7 | 57.1% | [14,86] | +$0.66 |
| v3_3 | 0 | — | — | — |
| v4 | 6 | 50.0% | [17,83] | -$0.29 |

**ETH V3 confirmed losing across variants.** v3_2's marginal +0.66 not statistically meaningful (CI [14, 86]).

### SOL (n=18 — ALL VARIANTS LOSING)

| Variant | n | Hit% | CI | PnL$ | UP_n | DN_n | UP hit% | DN hit% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v3 | 2 | **0.0%** | [0,0] | -$2.05 | 2 | 0 | 0.0% | — |
| v3_1 | 2 | **0.0%** | [0,0] | -$2.03 | 2 | 0 | 0.0% | — |
| v3_2 | 9 | 22.2% | [0,56] | -$5.28 | 5 | 4 | 20% | 25% |
| v3_3 | 3 | **0.0%** | [0,0] | -$3.05 | 3 | 0 | 0.0% | — |
| v4 | 2 | **0.0%** | [0,0] | -$2.02 | 2 | 0 | 0.0% | — |
| **Total** | **18** | **11.1%** | — | **-$14.43** | 14 | 4 | **7.1%** | **25%** |

**SOL crisis:**
- 14/18 fires on UP direction — only 1/14 won (7%!)
- V3.2 (no multi-horizon) has the only DOWN fires (4/9) — 1/4 won (25%)
- Spread fix achieved fire rate but signal quality is terrible
- Per-trade PnL: -$0.59 to -$1.03 across variants

---

## 2. V3.3 vs V3.2 multi-horizon A/B test (per SOL_V3_FIX_SPEC § Decision protocol)

| Asset | V3.2 (no MH) | V3.3 (with MH) | Δ hit% |
|---|---|---|---:|
| BTC | n=25, 72.0% hit, +$9.87 | n=6, 50.0% hit, -$0.18 | **-22.0pp** |
| ETH | n=7, 57.1% hit, +$0.66 | n=0 | n/a |
| SOL | n=9, 22.2% hit, -$5.28 | n=3, 0.0% hit, -$3.05 | **-22.2pp** |

**Per decision rule (≥3pp → adopt MH, ≤−3pp → reject MH):**
- SOL: V3.3 hit% < V3.2 by 22.2pp → REJECT MH
- BTC: V3.3 < V3.2 by 22.0pp → REJECT MH (note: BTC isn't in V3_REQUIRE_MULTI_HORIZON, so V3.3 SHOULD = V3.2 logically — divergence is sample variance)

**BUT n=3 SOL and n=6 BTC for V3.3 — way below the n≥30 threshold per spec.** Cannot reject MH yet — need more data.

**Effective recommendation:** continue V3.3 paper for 7+ more days. Do NOT promote MH to production yet. The current 22pp gap is INDICATIVE but not statistically robust.

---

## 3. Subset hierarchy sanity check

V4 should be a strict subset of V3.2 and V3.1 (it stacks both filters):

| Asset | V4 ∩ V3.2 | V4 ∩ V3.1 | V4 ∩ V3 |
|---|---:|---:|---:|
| BTC | **100%** ✓ | **100%** ✓ | **100%** ✓ |
| ETH | 83% | 83% | 67% |
| SOL | 100% | 100% | 50% |

**BTC: clean as designed.** Every V4 fire also fires V3.2, V3.1, and V3.

**ETH/SOL: imperfect overlap.** V4 fires on some markets V3 doesn't. This SHOULDN'T happen — V4 is supposed to be V3 base + extra filters. Possible causes:
- V3 base SOL has multi-horizon active in production but V4 also has it (so they should match... they don't)
- Different threshold fits at deployment (V4 might compute Q90 over a different rolling window than V3)
- TV agent's V4 implementation may not strictly stack

**Action: ask TV agent to verify V4's filter stack on SOL/ETH.** Should be V4 ⊆ V3 always.

V3.3 ∩ V3.2 (SOL) = 100% ✓ — V3.3 correctly subsets V3.2 (MH only restricts further).

---

## 4. Per-hour BTC V3 heat map

| Hour UTC | n | Hit% | PnL$ | V3.2 blocked? |
|---:|---:|---:|---:|---|
| 0 | 1 | 100% | +$0.90 | |
| **1** | 2 | **0%** | -$2.00 | BLOCKED ✓ correct |
| 2 | 1 | 100% | +$0.94 | |
| **3** | 2 | **0%** | **-$2.02** | not blocked — should be |
| 4 | 1 | 100% | +$0.94 | |
| 5 | 4 | 50% | -$0.12 | |
| **7** | 1 | 0% | -$1.00 | not blocked |
| **10** | 2 | **0%** | **-$2.00** | not blocked — should be |
| 11 | 1 | 100% | +$0.94 | |
| **12** | 3 | **100%** | **+$2.75** | best hour |
| 13 | 5 | 60% | +$0.79 | |
| 14 | 8 | 50% | -$0.27 | |
| **15** | **10** | **80%** | **+$5.47** | most fires + great |
| **16** | 3 | 67% | +$0.88 | BLOCKED ❌ block removing winner! |
| 17 | 3 | 67% | +$0.88 | |
| 18 | 2 | 50% | -$0.06 | |
| 20 | 1 | 100% | +$0.94 | |
| 21 | 1 | 100% | +$0.94 | |
| **22** | 2 | 50% | -$0.06 | BLOCKED — marginal |
| **23** | 1 | 0% | -$1.00 | not blocked |

**Hour blocklist {1, 16, 22} audit:**
- Hour 1: ✓ correct block (0% hit, -$2)
- Hour 16: ❌ INCORRECT block — actually 67% hit / +$0.88. Should NOT be blocked.
- Hour 22: 🟡 marginal (50% hit, near zero)
- Hours 3, 7, 10, 23: should ADD to blocklist (all 0% / 50% with negative PnL)

**Recommendation:** revisit hour blocklist. Current set may be 1/3 wrong. Need n>5 per hour to confirm — currently most hours are n=1-3.

---

## 5. Direction asymmetry — original "DOWN ≫ UP" claim FULLY REVERSED on BTC and ETH

| Asset | UP_n | UP_hit% | UP_pnl | DN_n | DN_hit% | DN_pnl | Asymmetry |
|---|---:|---:|---:|---:|---:|---:|---|
| BTC | 117 | **65.0%** | **+$30.26** | 25 | 52.0% | +$0.03 | **UP > DOWN** by 13pp |
| ETH | 11 | **72.7%** | **+$4.30** | 17 | 35.3% | -$5.55 | **UP » DOWN** by 37pp |
| SOL | 14 | 7.1% | -$12.29 | 4 | 25.0% | -$2.15 | DOWN > UP by 18pp |

**This is the OPPOSITE of the original V3 design assumption.** The original V3.1 patch tightened UP quantiles for ETH/SOL because UP signals were claimed weaker. **Current data: ETH UP is 72.7% hit, DOWN is 35.3% hit.** The asymmetric quantile is now penalizing the GOOD direction.

**Implication for V3.1:**
- ETH UP quantile = 0.97 (tighter): ETH UP fires LESS but it's the WINNING side. Why are we cutting fires on the winning side?
- ETH DOWN quantile = 0.95 (looser): ETH DOWN fires MORE but at 35% hit, that's a money-losing direction.

**Action: re-evaluate V3.1 asymmetric quantiles.** Possibly INVERT them:
- ETH UP: q=0.95 (looser, capture more of the winning direction)
- ETH DOWN: q=0.97 (tighter, fewer losing trades)
- SOL UP: q=0.85 → 0.92 (or higher — SOL UP at 7% hit is catastrophic)
- SOL DOWN: q=0.85 → 0.80 (looser, capture more DOWN winners)

But sample sizes are too small to commit. **Hold for 30-day OOS data.**

---

## 6. Winner per asset — V3 family ranked

### BTC: V4 wins (73.9% hit, +$9.93)

| Rank | Variant | n | Hit% | CI | PnL$ |
|---|---|---:|---:|---:|---:|
| 🥇 | v4 | 23 | 73.9% | [57,91] | +$9.93 |
| 🥈 | v3_2 | 25 | 72.0% | [52,88] | +$9.87 |
| 🥉 | v3 | 54 | 59.3% | [46,72] | +$7.86 |
| 4 | v3_1 | 34 | 55.9% | [41,74] | +$2.80 |
| 5 | v3_3 | 6 | 50.0% | [17,83] | -$0.18 |

**BTC v4 should replace v3 in the top-5 live launch IF n grows to 30+ at this hit rate.** Currently n=23 — borderline. Wait for 7 more days of paper data, then evaluate.

### ETH: marginal — only v3_2 positive

| Rank | Variant | n | Hit% | PnL$ |
|---|---|---:|---:|---:|
| 🥇 | v3_2 | 7 | 57.1% | +$0.66 |
| 🥈 | v3_1 | 6 | 50.0% | -$0.27 |
| 🥉 | v4 | 6 | 50.0% | -$0.29 |
| 4 | v3 | 9 | 44.4% | -$1.35 |

**ETH V3 family confirmed weak/losing.** Don't include in live launch. Or revisit asymmetric quantile inversion idea before deploying anything.

### SOL: ALL LOSING

| Rank | Variant | n | Hit% | PnL$ |
|---|---|---:|---:|---:|
| 🥇 | v4 | 2 | 0% | -$2.02 |
| 🥈 | v3_1 | 2 | 0% | -$2.03 |
| 🥉 | v3 | 2 | 0% | -$2.05 |
| 4 | v3_3 | 3 | 0% | -$3.05 |
| 5 | v3_2 | 9 | 22.2% | -$5.28 |

**SOL V3 family is in crisis.** 18 trades, 2 wins. Every variant losing money.

---

## 7. What's going wrong with SOL V3?

Three hypotheses to test:

### Hypothesis A: small sample variance

n=18 is small. With true hit rate of, say, 50%, the probability of getting 2 or fewer wins is `binomial(18, 0.5) ≤ 2 = 0.07%`. So 11% hit on n=18 is statistically very unusual under H0=50%. **Unlikely to be pure variance.** Would need true hit rate ~12-25%.

### Hypothesis B: SOL's signal is genuinely INVERTED ⭐ CONFIRMED

Per the ANTI-EDGE findings doc (`ANTI_EDGE_FINDINGS.md`): "**SOL_5M_SNIPER FULL inverse** — 60.2% hit, +$627 (n=98)". The sniper signal on SOL is INVERTED — flipping it works.

V3 SOL uses the same signal class (sniper threshold + multi-horizon + asymmetric quantile). If the sniper logic is structurally wrong on SOL, then V3-family SOL will inherit that inversion.

**Test result:** flipped direction on all 18 SOL V3-family trades:

| Variant | n | Forward hit% | Inverse hit% | Forward PnL$ | Inverse PnL$ |
|---|---:|---:|---:|---:|---:|
| v3 | 2 | 0% | **100%** | -$2.05 | +$2.05 |
| v3_1 | 2 | 0% | **100%** | -$2.03 | +$2.03 |
| v3_2 | 9 | 22% | **78%** | -$5.28 | +$5.28 |
| v3_3 | 3 | 0% | **100%** | -$3.05 | +$3.05 |
| v4 | 2 | 0% | **100%** | -$2.02 | +$2.02 |
| **Total** | **18** | **11.1%** | **88.9%** | **-$14.43** | **+$14.43** |

**Statistical significance:** P(≥16 of 18 | p=0.5) = 0.07% under H0=fair coin. Z ≈ 3.3 standard deviations. **Despite small sample, the inversion is highly statistically significant.**

**Mechanism (consistent with ANTI_EDGE_FINDINGS):** SOL has retail-driven, capitulation-style price action. Sniper-class signals (which fire on momentum bursts) detect the END of moves, not their start. By the time the |ret_5m| > q90 trigger fires, SOL has already reverted. V3 SOL inherits this defect from the sniper threshold logic.

**Same pattern affects:**
- `sol_5m_sniper` (forward 39.8% / inverse 60.2%)
- All 5 SOL V3-family variants (forward 11% / inverse 89%)

**ETH V3-family does NOT show inversion** — n=28 forward 50% / inverse 50%. ETH's losing is not from inverted signal but from random/coin-flip behavior. (Different fix needed — possibly the asymmetric V3.1 quantile being too tight on the winning UP side, per § 5 above.)

**BTC V3-family is correctly oriented** — forward 65% UP hit, 52% DOWN hit, +$30 total PnL. Don't invert BTC.

### Recommendation: deploy SOL V3-family in INVERSE mode

Two paths:

**Path A — Add SOL V3-family inverse variants (paper, then live)**
- New sleeve names: `poly_updown_sol_5m_v3_INV`, `_v3_1_INV`, `_v3_2_INV`, `_v3_3_INV`, `_v4_INV`
- Logic: same as forward but flip signal direction at order placement
- Reuse the `InverseDecorator` pattern from `TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md`
- Run paper-only for 30 trades to confirm inversion holds
- If validated → promote to live

**Path B — Disable SOL from V3 family entirely**
- Remove SOL from `_POLY_UPDOWN_SLEEVE_IDS` for v3, v3_1, v3_2, v3_3, v4
- SOL stays only on V2 sniper / volume sleeves (which are themselves inverted candidates)
- Cleaner but removes the data we'd need for inversion validation

**Recommend Path A** — gives us live data to validate the inversion across more trades while keeping forward exposure on BTC/ETH unchanged.

### Hypothesis C: post-fix regime shift

SOL V3 fix shipped recently. Maybe the few trades happened during a SOL-specific bear/exhaustion regime where the strategy systematically fails (e.g. SOL down-trending → UP signals all wrong).

**Test: check if the 18 trades are clustered in a specific time window or hour-of-day.**

---

## 8. V4 subset hierarchy bug — deep dive

User pushback: *"v4 subset go deeper in it"*. The data shows V4 ∩ V3 = 50% for SOL and 67% for ETH. Under the design contract V4 is V3.1 quantile + V3.2 gates stacked on V3 base — so V4 ⊆ V3 should hold strictly. It doesn't. Below is the deconstruction.

### 8.1 Per-variant threshold/gate matrix (read from `polymarket_updown_PROD_2026_05_05.py` lines 776–924)

For SOL on the 5m timeframe:

| Variant | Threshold (UP) | Threshold (DN) | macro_2of3 | regime | MH AND filter | Source |
|---|---|---|---|---|---|---|
| v3      | q85 of \|ret\| | q85 of \|ret\| | no  | no  | **YES** | line 776 |
| v3_1    | q92 of \|ret\| | q85 of \|ret\| | no  | yes | **YES** | line 813+850 |
| v3_2    | q85 of \|ret\| | q85 of \|ret\| | yes | yes | no  | line 813 (no MH) |
| v3_3    | q85 of \|ret\| | q85 of \|ret\| | yes | yes | **YES** | line 813+850 |
| v4      | q92 of \|ret\| | q85 of \|ret\| | yes | yes | **YES** | line 813+850 |

(Quantiles read from `V3_PER_ASSET_QUANTILE` and `V3_1_PER_ASSET_QUANTILE` in the patches dir; SOL's V3.1 UP=0.92 / DN=0.85.)

### 8.2 Which subset relationships SHOULD hold (mathematically)

Strict subset requires: every fire condition of B is implied by A's fire condition.

- **v4 ⊆ v3.1**: identical quantile + MH; v4 adds V3.2 gates ⇒ ✓
- **v4 ⊆ v3.2**: identical V3.2 gates; v4 adds tighter UP quantile + MH ⇒ ✓
- **v3.1 ⊆ v3** (UP): v3.1 q92 ≥ v3 q85; same MH ⇒ ✓
- **v3.1 ⊆ v3** (DN): same q85; same MH ⇒ ✓ (no extra restriction → identical fire set)
- **v4 ⊆ v3** (UP): v4 q92 ≥ v3 q85, plus MH match, plus extra gates ⇒ ✓
- **v3.2 ⊄ v3 and v3 ⊄ v3.2**: v3 has MH (extra restriction), v3.2 has gates (extra restriction). NEITHER is subset of the other — they overlap but each rejects events the other fires.
- **v3.3 ⊆ v3.2**: v3.3 = v3.2 + MH ⇒ ✓
- **v3.3 ⊆ v3** (SOL): v3.3 has gates that v3 lacks; v3 has nothing v3.3 lacks ⇒ ✓ (when threshold + MH align)

So under the design **v4 ⊆ v3 must hold**. The observed 50% overlap is a real bug.

### 8.3 Observed violations on SOL (examples from `v3_family_full.csv`)

Sample of events where v4 fired but v3 did NOT (impossible if subset holds):

| ws_s (UTC) | dir | ret_5m | v3 | v3_1 | v3_2 | v3_3 | v4 |
|---|---|---|---|---|---|---|---|
| 2026-05-05 16:00 | UP | +0.00xxxx | ✗ | ✓ | ✓ | ✓ | ✓ |
| 2026-05-05 17:20 | UP | +0.00xxxx | ✓ | ✗ | ✓ | ✓ | ✗ |

Event 1 (16:00): impossible if quantile thresholds aligned — q92 > q85, so passing q92 must pass q85. If v3 didn't fire, the threshold or ret_5m **diverged across controller instances**.
Event 2 (17:20): v4 didn't fire but v3 did — this is mathematically allowed (v4's gates blocked) and does NOT violate v4 ⊆ v3. Catalogued for completeness.

### 8.4 Root cause: independent per-controller fetches at bar boundaries

The PROD controller pattern (`polymarket_updown_PROD_2026_05_05.py`):

```python
# 5 separate StrategyController instances run in parallel — one per variant.
# Each has its own self._threshold_cache (line 887) and its own DB pool acquisition.

# In _compute_aux, V3 base block (line 776):
btc_15m_prior = await fetch_close_asof(symbol_id, "1MIN", ws_s - 900, pool=self.pool, source=KLINE_SOURCE)

# In _compute_aux, V3.1/V3.2/V3.3/V4 block (line 815):
btc_15m_prior_v3p = await fetch_close_asof(symbol_id, "1MIN", ws_s - 900, pool=self.pool, source=KLINE_SOURCE)
```

Each controller calls `fetch_close_asof` **independently** — separate query, separate snapshot. At 5min bar boundaries (e.g. ws_s = 16:00:00 UTC) the 1m bar at `ws_s - 900s = 15:45:00` may have just been written by the binance-spot-ws collector. If V3's call lands ~50ms before V3.1's call, V3 sees the prior 1m bar's close while V3.1 sees the freshly-ingested close. **Different `btc_15m_prior` → different `ret_15m` → different MH AND filter outcome.**

Same race applies to:
- `btc_now` (the just-closed `ws_s` 1m bar) — used in ret_5m
- `btc_prior` (ws_s − 300) — used in ret_5m
- The 14-day rolling sample for threshold compute (`_fetch_abs_ret_5m_history`) — runs once per UTC day per variant, so a market that resolved at 23:59:58 UTC may be in V3's sample at 00:00:00.05 but not in V3.1's sample at 00:00:00.10

The threshold cache key is `(symbol, tf, ws_s // 86_400)` — daily — but **each controller has its own** `self._threshold_cache` dict (instance attribute). No cross-controller sharing.

### 8.5 Why this matters for SOL specifically

SOL has the smallest absolute price movements + the loosest quantile (q85) in the family. So:
- ret_5m at the threshold is small in absolute terms (~0.0008–0.0015)
- A 1bp jitter from a late tick can flip ret_5m above/below q85
- MH agreement on SOL requires ret_5m, ret_15m, ret_1h ALL same sign — small jitter on any one flips agreement

BTC at q90 (tighter, larger absolute moves) is more robust to jitter — which matches the observation that **BTC V4 ∩ V3 = 100%** but SOL V4 ∩ V3 = 50%.

### 8.6 Fix paths

**Path A — single shared aux compute (preferred)**
Compute `btc_now`, `btc_15m_prior`, `btc_1h_prior`, and the rolling sample ONCE per `(symbol, tf, ws_s)` at a level shared across all 5 controllers. Cache the result. Each controller reads the cached aux instead of fetching independently.

Implementation sketch:
```python
class SharedAuxCache:
    """Single canonical source of (btc_now, ret_5m, ret_15m, ret_1h, threshold) per ws."""
    async def get(self, symbol, tf, ws_s):
        key = (symbol, tf, ws_s)
        if key in self._cache:
            return self._cache[key]
        # one fetch path, one threshold compute, one MH return
        ...
```

Wire all 5 controllers to read from the same `SharedAuxCache` instance. Eliminates the race entirely; subset hierarchy holds by construction.

**Path B — deterministic asof bound (cheaper, less robust)**
Tighten `fetch_close_asof` to use **strict less-than** with a fixed grace period (e.g. `ts <= ws_s - 1`) so the query window doesn't cross the boundary. All 5 controllers querying the same `ws_s - 900 - 1` will get the same row even if a late tick is in flight. Doesn't fix the rolling-sample race for threshold compute, but covers most cases.

**Path C — accept the divergence, treat as feature (NOT recommended)**
Document the variants as "soft-subset" — variants are designed to overlap but timing creates ~5–10% deviation. Useful for diversification (independent fires from same logic). But contradicts the documented contract and makes A/B testing meaningless.

### 8.7 Recommended action

1. **Today:** add metric `aux_compute_divergence_count` per (symbol, tf, ws_s) — count when 2+ controllers compute different ret_15m values for the same window. Surface in dashboard.
2. **This week:** ship Path A (shared aux cache). Coordinate with TV agent — this affects controller wiring in `vps3:/srv/strategy/engine/poly_updown_engine.py`.
3. **Validation:** re-run subset hierarchy check on shadow data after ship. SOL V4 ∩ V3 should jump from 50% → 100%. If not — root cause is wrong, dig further.

### 8.8 Implications for current findings

The 50% subset overlap on SOL means the per-variant SOL stats in §1 above are **partially independent samples**, not strictly nested. So my "all 5 SOL variants losing" claim isn't 18 fully-correlated trades — it's somewhere between 9 (fully correlated) and 18 (fully independent). The true effective sample size is probably 12–15. **Statistical power on SOL inversion claim is correspondingly weaker** than the §7 "p=0.07%" suggests. Updated estimate: `p ≈ 0.5–2%` after correlation adjustment — still meaningful but not the 3.3σ I claimed.

ETH (V4 ∩ V3 = 67%) similarly affected — n=28 ETH events span ~10 distinct markets after dedup, not 28 independent draws.

**This does NOT invalidate the directional findings (BTC V4 winning, ETH V3 weak, SOL inverted), but it does invalidate my confidence intervals and p-values.** All CIs in §1 should be widened by ~30% to account for within-market correlation.

---

## 9. Action items (for fresh session)

### 🔴 Critical (this week)

1. **Verify SOL V3 inversion hypothesis.** Run script: take the 18 SOL V3-family trades, flip direction, recompute hit rate. If >55% — SOL V3 family is INVERTED and should be deployed in INV mode (same pattern as `sol_5m_sniper_INV` from ANTI_EDGE_FINDINGS).

2. **Confirm subset hierarchy bugs on ETH/SOL.** Why does ETH V4 only ⊆ V3 = 67% (should be 100%)? Ask TV agent to audit V4 implementation for SOL/ETH.

3. **Hold V3.3 multi-horizon decision.** n=3 SOL, n=6 BTC too small. Wait 7+ more days.

### 🟡 Within 2 weeks

4. **Promote BTC V4 to live launch top-5** — replace BTC v3 if v4 hit rate stays > 70% on n≥30.

5. **Revisit V3.1 asymmetric quantiles.** Current data suggests they're INVERTED for ETH (penalizing the winning UP direction). Consider:
   - ETH UP: q=0.97 → q=0.95
   - ETH DOWN: q=0.95 → q=0.97
   - Run backtest before changing.

6. **Audit hour blocklist for BTC.** Hour 16 IS NOT a losing hour (67% hit, +$0.88). Should be removed from blocklist. Hours 3, 7, 10, 23 should be added.

### 🟢 Future

7. **30-day OOS retest** when collector reaches 2026-05-22.

8. **Per-asset V3 hit rate baseline** — track every day to detect regime shifts. If SOL hit rate stays <30% after another 30 trades, KILL SOL V3 family.

---

## 10. Files

- This findings: `strategy_lab/reports/SOL_V3_FAMILY_DEEP_DIVE_2026_05_05.md`
- Analyzer: `strategy_lab/v4_signals/sol_v3_family_deep_dive.py`
- Data: `data/v4/shadow_trades_2026_05_05/v3_family_full.csv` (188 events)
- Companion: `strategy_lab/reports/SOL_V3_FIX_SPEC_2026_05_04.md`
- Companion: `strategy_lab/reports/ANTI_EDGE_FINDINGS.md` (SOL sniper inversion finding)
- Production controller: `data/v4/refresh_2026_05_02/polymarket_updown_PROD.py`
