# B945 Fresh Tape Forensics — 2026-06-12

`0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68` (@l5zn1bwom8etsk) — per-trade forensic walk
of the **3,500 freshest fills** (data-api hard cap) from the Polymarket activity feed.

---

## 0. Data Freshness

| Item | Value |
|------|-------|
| Tape window | Jun 10 13:27 UTC → Jun 12 17:44 UTC (~52h) |
| Total trades | 3,500 (API limit; actual volume is far higher) |
| Unique slugs | 49 btc-updown-15m markets |
| Unique condition IDs | 49 |
| Unique tx hashes | 3,370 |
| RTDS coverage (Jun 10-11 fills) | 788 / 3,500 (22.5%) |
| 1m kline coverage (Jun 10-11) | 788 / 3,500 (same cutoff: Jun 11 06:00 UTC) |
| Trades AFTER canonical window | 2,712 (Jun 11 06:00 → Jun 12 17:44) — no RTDS/kline; price analysis only |
| Raw JSON saved | `cache/_pm_portfolio/0xb945945d/activity_TRADE_2026_06_12.json` |

---

## 1. HEADLINE REVISION — He Is NOT Just a Passive Resting-Bid Maker

The ML decode (Jun 11-12) concluded he is a "passive two-sided bid MAKER … resting limit bids on
both tokens all window." The fresh tape **partially overturns** this. He IS a maker (confirmed: all fills
are `BUY`-side only; no `SELL` trades; rebate $3.6k proven). But his quote behavior is ACTIVE and
price-following, not static resting:

**He chases price toward resolution certainty throughout the 15-min window.**

Evidence (all n=3,500 fills):
- Mean fill price declines from **0.535 in first 2 min → 0.392 in last 3 min** (p-val: t-test on
  early vs late sub-samples t=10.4 p<1e-15)
- Fraction of extreme fills (<15¢ or >85¢) rises monotonically: **0% at open → 53% in final 3 min**
- 83.7% of markets (41/49) show a price drift >20 pp from first fill to last fill
- Mean price range first→last fill within a market: **−4 pp median, std 46 pp** (huge spread = market
  moves either way and he follows)
- Average market duration (first fill to last fill): **630 seconds** (only 270s remaining = he's
  active right through expiry)

**Interpretation:** He opens both token sides in the first ~2 min at mid-prices (0.5–0.6¢ range),
then continuously re-quotes lower on the losing side and higher on the winning side as BTC price
moves resolve the market. By window close he is buying the loser at 0.01–0.05 (almost worthless)
and the winner at 0.95–0.99 (near certain). This is an **EV-ladder / sweeper** strategy, not
a static resting-bid maker.

---

## 2. Lens (a): Oracle Burst Timing

**RTDS coverage subset (n=788, Jun 10-11 only).**

Oracle proxy: RTDS |ret5| (5-second Chainlink return). BTC 1m kline |ret5m| used for same subset.

### RTDS |ret5| (Chainlink, n=788):
| Condition | n | mean clip ($) | ratio |
|-----------|---|--------------|-------|
| Burst (|ret5| > p75 = 0.00019) | 195 | 10.25 | 1.20× |
| Calm (|ret5| ≤ p75) | 593 | 8.55 | — |
| t-test | | t=2.37, **p=0.0180** | SIG |

**Finding:** He places **20% larger clips during oracle bursts** (p=0.018, significant at α=5%).
Extreme fill fraction (>85¢ or <15¢): **burst=26.7%, calm=33.2%** — same as ML decode showing
U-shaped intensity. During bursts he targets mid-prices more (fills at 0.457 vs 0.479 on calm).

This supports the residual oracle-gated quoting hypothesis from the handoff: he widens/increases
clip size when the oracle is moving (either direction = takers panic, spreads widen, he gets
filled at a better effective spread).

### Binance 5m kline (n=788):
| Condition | n | mean clip ($) | ratio |
|-----------|---|--------------|-------|
| Burst (|ret5m| > p75 = 0.0025) | 191 | 8.78 | 0.97× |
| Calm (|ret5m| ≤ p75) | 597 | 9.03 | — |
| t-test | | t=−0.35, p=0.73 | NS |

Binance 5m shows no clip-size effect (NS). **RTDS (Chainlink) is the relevant signal, not Binance
5m return.** Consistent with his article's "Chainlink-CVD fusion" — he watches the oracle directly,
not Binance price changes.

### Side alignment with BTC (covered subset n=788):
- UP fills: mean ret5m = +0.000203; DOWN fills: mean ret5m = +0.000101
- t-test UP vs DN ret5m: t=0.63, **p=0.53** — NO statistically significant side alignment
- UP fills when BTC going up: 56% (vs 50% base — noisy)
- This is consistent with the ML decode: side is a coin flip (AUC 0.532)

---

## 3. Lens (b): Size Laddering

**Clear monotonic size taper from cheap tokens → expensive tokens** (Spearman r=0.752, p<1e-200).

| Price bucket | n | median clip ($) | mean clip ($) |
|-------------|---|-----------------|--------------|
| <5¢ | 367 | 0.34 | 0.53 |
| 5–10¢ | 323 | 1.80 | 1.56 |
| 10–20¢ | 443 | 3.04 | 2.91 |
| 20–30¢ | 307 | 5.04 | 4.89 |
| 30–40¢ | 283 | 6.20 | 6.29 |
| 40–50¢ | 256 | 8.57 | 8.19 |
| 50–60¢ | 278 | 9.50 | 9.75 |
| 60–70¢ | 331 | 12.72 | 12.00 |
| 70–80¢ | 283 | 15.00 | 14.11 |
| 80–90¢ | 325 | 19.67 | 17.03 |
| 90–95¢ | 162 | 27.30 | 19.96 |
| >95¢ | 142 | 27.79 | 21.05 |

**Finding:** Dollar clip scales roughly linearly with fill price, from ~$0.34 at 2¢ to ~$27 at 97¢.
This is EXACTLY the EV ladder from his article: at 2¢ entry he needs tiny clips (1 win covers 49
losses); at 90¢ entry he needs big clips (small spread). The math: `clip ≈ 0.27 × price × $100`.

Favorites (≥70¢): mean $17.19, Underdogs (≤30¢): mean $2.42. t-test t=56.44 p<1e-300.

**Total USDC deployed across 49 markets: $29,797** (~$608/market, consistent with $726/market
lifetime average from chain analysis).

---

## 4. Lens (c): Level Selection

**Fill price distribution (n=3,500):**
- Mean: 0.444, Median: 0.410, Std: 0.311
- Percentiles: [5%=0.01, 10%=0.04, 25%=0.14, 50%=0.41, 75%=0.72, 90%=0.89, 95%=0.96]

**NEW FINDING:** The price distribution is BIMODAL — heavy tails at both 0–10¢ (628 fills, 18%)
and 85–99¢ (466 fills, 13%). This is not a resting mid-market maker. It's a sweep of the full
probability curve.

- Extreme fills (<10¢ or >90¢): 26.6% of all fills, 22.9% of total USDC
- Extreme low (<10¢): n=628, mean clip $0.94, mean offset 702s (>11 min into window)
- Extreme high (>90¢): n=304, mean clip $20.47, mean offset 690s

Both extremes appear LATE in the window when resolution is near-certain. He is buying the loser
at pennies (EV positive if outcome not yet resolved) and the winner at 95¢+ (pure risk-free
near-certain payout, capturing residual spread).

**Token breakdown at extremes:**
- Extreme low (<10¢): 53.5% UP, 46.5% DOWN — roughly even (both tokens hit extremes equally)
- Extreme high (>90¢): 44.1% UP, 55.9% DOWN — DOWN token slightly more represented at high prices
  (consistent with BTC being more often DOWN in this 2-day window, Jun 10-12)

---

## 5. Lens (d): Cancel/Replace Cadence

**Key metrics (n=49 markets):**
- Min intra-market fill gap: median 0s (sub-second gaps in EVERY market)
- Markets with sub-1s intra-fill gap: **100%** (49/49)
- Same-second clusters (per market per slug-second):
  - 1 fill: 1,706 seconds
  - 2–5 fills: 669 seconds
  - 6–10 fills: 17 seconds
  - >10 fills: 1 second (max 11 fills in 1 second, 1 market)
- Max levels per second (per market): mean=3.4, std=1.4, max=9
- Markets with >1 level per second on average: 100% (49/49)

**Finding:** He fires multiple fills per second in every market. The max of 9 distinct price levels
in a single second confirms the "EV layering" claim from his article — he simultaneously places
orders at multiple price rungs. This requires a co-located or CPU-pinned execution engine.

Transaction batching is rare (3.8% of txs have >1 fill, max 3 fills per tx), confirming each
fill is an individual CLOB limit order, not a batched sweep.

**Critically: 0% of transactions include BOTH tokens simultaneously.** Every tx is single-token.
This means his system places UP and DOWN orders as separate transactions, not atomic pairs.
The near-simultaneous appearance of both tokens in the same second is from independent orders
landing in the same Polygon block.

---

## 6. Lens (e): EV Layering

**This is the core mechanism — confirmed across all 3,500 fills.**

Simultaneous price levels per market per second: mean 3.4, max 9. 100% of markets show this.

The full price sweep structure is now clear from the example market (btc-updown-15m-1781098200,
124 fills, $1,227 deployed, price range 0.01–0.98):

- **Phase 1 (0–90s):** Opens at 0.69 (UP) / 0.24 (DOWN) — mid-range both sides
- **Phase 2 (90–300s):** Both tokens shift together: UP 0.62–0.76, DOWN 0.22–0.37
- **Phase 3 (300–450s):** Price moves strongly UP; DOWN fills drop to 0.12–0.19, UP climbs to 0.80–0.90
- **Phase 4 (450–600s):** DOWN virtually dead (0.03–0.06), UP at 0.93–0.97, still buying both
- **Phase 5 (600s+):** DOWN at 0.01–0.02 ($0.30 clips), UP at 0.98 ($27+ clips) until expiry

**Each phase uses the EV ladder size scaling:** tiny clips on the dying side, max clips on the
winning side. The strategy is more accurately described as **continuous EV-ladder sweeping of the
resolution curve** than "passive maker."

---

## 7. Lens (f): Anomalies

### Sub-second clustering
- 17 market-seconds with 6–10 fills, 1 with 11 fills
- Consistent with CPU-pinned order firing at maximum CLOB throughput

### Round vs non-round prices
Price analysis: fills appear at round cent boundaries (0.05, 0.10, 0.15…) and also at fractional
levels (e.g., 0.46, 0.63, 0.88). No special clustering at 0.50 (256 fills, 7.3% = normal given
the price curve shape).

### Side symmetry per market
- Mean UP fraction of notional: 0.484 ± 0.260 std
- Only 22.4% of markets near parity (40–60%); 38.8% dominated by UP, 38.8% by DOWN
- This is NOT a delta-neutral strategy per market — he ends up with large net positions
- The symmetry at the POPULATION level (0.484) emerges from aggregation, not per-market hedging

### Late fills at extreme prices
- 63.5% of fills in last 3 minutes are at extremes (>85¢ or <15¢)
- These have the highest concentration of tiny clips (losers at 1–5¢, $0.30 average) and largest
  clips (winners at 95–99¢, ~$25+)
- The tiny loser clips are essentially free lottery tickets near expiry

---

## 8. New Findings vs Prior ML Decode Report

| Item | ML Decode (prior) | Fresh Tape Forensics (now) | Status |
|------|-------------------|---------------------------|--------|
| Passive resting bids, static | Asserted | **REVISED** — he actively chases price toward extremes | NEW |
| Opens in first 2 min | Confirmed (0.932 AUC) | Confirmed: 51% first fill <120s, 100% <15 min | CONFIRMED |
| No side signal | Confirmed (AUC 0.532) | Confirmed: BTC ret5m uncorrelated with side (p=0.53) | CONFIRMED |
| Quote intensity ↑ with oracle | Confirmed | Confirmed with RTDS: burst clips 1.20× bigger (p=0.018) | CONFIRMED + QUANTIFIED |
| EV layering full curve | Asserted from article | **Quantified**: 3.4 price levels/second, full 0.01–0.99 range, clip scales linearly | QUANTIFIED |
| Delta-contrarian fills | Shown via ML | Confirmed: ends up on losing side by construction (follows price) | CONFIRMED |
| Never sells | Assumed | Confirmed: 0 SELL-side fills in 3,500 trades | CONFIRMED |
| Sweeps to near-certainty | Not in prior decode | **NEW**: 53% of late-window fills at extremes, mean price 0.39 in last 3 min | NEW |
| Extreme clips tiny/large | Not quantified | **NEW**: <10¢ = $0.94 avg, >90¢ = $20.47 avg (22:1 ratio) | NEW |
| BTC oracle ≠ Binance signal | Partial (ML AUC) | **CONFIRMED**: RTDS burst SIG (p=0.018), Binance 5m NS (p=0.73) | NEW EVIDENCE |
| Per-market asymmetry | Side counts only | **NEW**: 77.6% of markets are >60% tilted one side notionally | NEW |

---

## 9. Verdict: What Is Replicable?

### His actual strategy (fully decoded):

```
1. Open every btc-updown-15m market in first ~2 min — BOTH tokens at mid-range (0.5–0.65)
   tiny-clip resting bids. No signal, just a presence to get queue position early.
2. All window: continuously re-quote BOTH tokens tracking the market price.
   Quote UP side at the current best bid for UP; quote DN side at the current best bid for DN.
   Fill wherever the market price is → EV ladder clip size = price × 0.27 × $100.
3. When oracle/market clearly resolves one direction (BTC has moved ±0.3%+),
   INCREASE clip size on the winner (approaching $27-30 max), REDUCE on the loser.
4. In final 3 minutes: sweep the loser at pennies (0.01–0.05, $0.30 clips = lottery tickets),
   keep buying winner at 0.95–0.99 capturing last spread.
5. Hold everything to resolution. Winners pay out; losers expire at 0. Rebates earned on ALL fills.
```

### What is replicable for us?

**NOT replicable (reasons confirmed):**
- Queue-aware maker sim already showed −0.05/win SIG-NEG on the faithful-join strategy
- The CLOB depth at mid-window (his Q2-Q4 fills) is thin → fill models show ≤ −0.05/win
- His clip-size scaling requires knowing the true probability (he reads the live book + oracle)

**POTENTIALLY testable (one new opening from this forensic):**
- **Late-window sweeper — buying the near-certain winner at 90–99¢:** This is pure spread capture
  on a near-resolved market. He buys the UP token at 0.97 and earns ~0.03 profit (3% return in
  <3 minutes) if it wins. The risk is: if BTC reverses in the final minute, the 0.97 token crashes.
  This is NOT a maker strategy at extremes — he must be taking the offer. Effective yield if
  correct: 3¢ on $27 = 1.1% for ~120s exposure = 2,880% annualized. But n needs verification.

- **Oracle-gated clip sizing on the maker sim:** RTDS burst → 1.20× bigger clips (p=0.018).
  Already planned as Task 1 from the handoff. The fresh tape confirms the signal is real in his
  actual fills, not just an ML artifact. Pre-register: oracle-gated variant of the queue sim should
  show better $/win vs the flat-clip arm A.

**GROUND-TRUTH RULE note:** The 90–99¢ late sweeper hypothesis needs per-trade verification
against actual resolution outcomes before any capital allocation. The tape has timestamps but not
per-slug outcomes in the fresh window — need to cross-join against `load_resolutions()` for Jun
10-12 slugs to compute his actual win rate and $/fill at extreme prices.

---

## 10. Scripts

| Script | Purpose |
|--------|---------|
| `strategy_lab/wallet_hunt/_b945_forensic_fetch.py` | Fetch + paginate 3,500 trades, save JSON |
| `strategy_lab/wallet_hunt/_b945_forensic_walk.py` | Per-trade forensic across all 6 lenses |

**Artifacts:**
- `cache/_pm_portfolio/0xb945945d/activity_TRADE_2026_06_12.json` — 3,500 raw trade records
- `cache/_pm_portfolio/0xb945945d/fresh_tape_analysis.parquet` — per-trade enriched df
- `cache/_pm_portfolio/0xb945945d/fresh_tape_mkt_stats.parquet` — per-market stats (49 markets)

---

## 11. Next Session Priorities (from this forensic)

1. **Oracle-gated maker sim variant** (planned from handoff, now confirmed by fresh tape):
   run arm A (faithful join-bid) conditioned on RTDS |ret5| > threshold. Pre-register 3 thresholds.

2. ~~**Late-window sweeper P&L verification**~~ — **DONE same session, see §12. RETRACTED:
   sweeper is SIG-NEGATIVE in his own tape.**

3. ~~**His 3,500-trade P&L accounting**~~ — **DONE same session (§12 context row): +$1,344 over
   49 markets, +$0.38/fill, slug-cluster CI [+0.02, +0.79] — consistent with lifetime stats; the
   profit is portfolio-level only.**

---

## 12. Ground-truth verification: >90¢ sweeper (added same session)

**GROUND-TRUTH RULE applied to §9's "potentially testable" claim.** Per-slug outcome cross-join
done: canonical `load_resolutions()` (only 2/49 tape slugs inside the canonical window) + **CLOB
winner fetched by conditionId for all 49 slugs** (2/2 agree with canonical, 0 disagree, **0 slugs
without an outcome**). Script: `strategy_lab/wallet_hunt/_b945_forensic_sweeper_gt.py`; artifacts:
`cache/_pm_portfolio/0xb945945d/fresh_tape_with_outcomes.parquet` (3,500 rows with `won`+`pnl_07`),
`cache/_pm_portfolio/0xb945945d/clob_winners_fresh_2026_06_12.json`.

Fee model: WON → `qty·(1−p)·(1−0.07·p)`; LOST → `−qty·p` (production winner-only 0.07 curve).
Maker rebate estimated at pool-prorated ~0.0015/sh (lifetime MAKER_REBATE / volume) — immaterial
(shifts $/fill by ~+$0.03).

### Realized economics in HIS OWN tape (final 3 min, off_s > 720)

| Cell | n fills | n slugs | mean entry | WR (Jeffreys CI95) | breakeven WR | $/fill | naive bootCI95 | slug-CLUSTER bootCI95 | total $ |
|------|---------|---------|-----------|--------------------|--------------|--------|----------------|----------------------|---------|
| **p ≥ 0.90** | 163 | 29 | 0.953 | 0.865 [0.806, 0.911] | **0.956** | **−1.96** | [−3.26, −0.77] | [−4.84, +0.87] | **−$320** |
| **p ≥ 0.95** | 104 | 23 | 0.972 | 0.904 [0.836, 0.950] | **0.974** | **−1.52** | [−3.02, −0.23] | [−3.97, +0.62] | **−$158** |
| p ≤ 0.10 (loser lottery, context) | 384 | 39 | 0.049 | 0.083 [0.059, 0.114] | 0.049 | +0.68 | [+0.02, +1.46] | [−0.78, +2.52] | +$259 |
| ALL fresh-tape fills (context) | 3,500 | 49 | 0.444 | 0.466 | — | +0.38 | [+0.08, +0.68] | **[+0.02, +0.79]** | **+$1,344** (+$99 rebate est) |

(Breakeven WR at entry p with the 0.07 winner-only fee: `WR_be = p / (p + (1−p)(1−0.07p))`.)

### Loss tail (the killer)

- **p ≥ 0.90:** 22 losses (13.5%) — mean **−$20.12**, worst −$29.10, total −$442.53, vs wins
  averaging only +$0.87. **One average loss wipes 23.2 average wins.** Observed WR 0.865 is
  **9.1 pp BELOW the 0.956 breakeven** — even the WR CI95 upper bound (0.911) doesn't reach it.
- **p ≥ 0.95:** 10 losses (9.6%) — mean −$21.19, worst −$29.10. One loss wipes **37.3** wins.
  WR 0.904 vs breakeven 0.974; CI upper 0.950 < breakeven.
- All ≥0.90 losses come from just 2 late-reversal slugs (`…1781269200`, `…1781198100`) where BTC
  flipped in the final ~2 minutes and his ≥0.90 buys were on the side that died.

### The reversal slugs reveal the real structure

The SAME two slugs that produce his ≥0.90 loss tail produce most of his loser-lottery WINS
(`…1781198100` +$253, `…1781269200` +$151 from penny fills on the opposite token). **The two
extremes are not separable edges — they are the two legs of his always-on two-sided book.** When a
late reversal hits, the expensive leg burns and the penny leg pays; netted across the whole book he
stays positive. Slicing out one leg inherits only that leg's adverse selection.

The loser-lottery leg alone naively looks +EV ($/fill +0.68, naive CI excludes 0), but its wins
concentrate in 4/39 slugs and the slug-level cluster bootstrap flips it inconclusive
([−0.78, +2.52]). Same knife-edge shape, opposite tail — do not chase it either.

His FULL book over the same 49 markets: **+$1,344 (+$0.38/fill, slug-cluster CI [+0.02, +0.79] —
the only cell that stays positive under clustering).** The profit exists only at the portfolio
level (two-sided spread capture + EV-ladder sizing + rebates), not in any price band sliced out.

### VERDICT

**The >90¢ late-window sweeper is NOT +EV — it is SIG-NEGATIVE in his own tape on the naive
bootstrap (−$1.96/fill, CI [−3.26, −0.77]) and at best inconclusive-negative under slug
clustering.** Observed WR fails the breakeven WR with the entire CI below it at both thresholds.
This is exactly the favorite-longshot knife-edge that killed momo HOLD: harvest 1–3¢ wins until a
single late reversal claws back 23–37 of them. **§9's "potentially testable" late-sweeper opening
is RETRACTED. Do not build it.** The only robust number in the fresh tape is his whole-book
+$0.38/fill — already shown unreplicable for us by the queue sim (arm A SIG-NEG without his queue
priority/throughput). The oracle-gated sim variant (§11.1) remains the one live thread.

_End of forensic session 2026-06-12 (ground-truth addendum same day)._
