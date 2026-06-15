# b945 "infrastructure guide" article — analysis, cross-validation vs our decode, TV/TVRUST gap map

_2026-06-12. Source: second article by @l5zn1bwom8etsk (wallet `0xb945945d`, +$21,742 audited).
Cross-referenced against: `B945_INVENTORY_SUMARB_DECODE_2026_06_12.md` (r3), `B945_FRESH_TAPE_FORENSICS_2026_06_12.md`,
`B945_LADDER_SIM_RESULTS_2026_06_12.md` (NO-GO on pair fraction), `B945_PNL_AUDIT_2026_06_12.md`,
TVRUST `STATUS.md` 2026-06-11 (R0–R9, Ireland A/B `:8444`, live-ready pre-creds)._

---

## 1. Article claims × our ground-truthed decode (what it CONFIRMS)

| Article claim | Our evidence | Verdict |
|---|---|---|
| "Ireland/Montreal closest viable locations" | Poly CLOB on AWS eu-west-2; our Ireland VPS <2ms RTT (verified 2026-05-17) | ✅ we're already optimal |
| "Maker/ladder bots outperform directional" | His engine = paired sum<1 maker ladders +$10.65/slug; our directional fleet audit 155→76 KILL | ✅ matches |
| "EV-layers across the whole 2–95¢ curve, never idle" | Clip∝price Spearman 0.752, $0.34@2¢→$27@97¢, both sides whole window | ✅ exact match to tape |
| "Tens of thousands of trades/month" | 20–27k fills/wk from Apr 21 | ✅ |
| "Test window-open vs 60s-in entries separately" | He enters ~60s in (books formed); both sides within 60s | ✅ |
| "Sim 74% WR → live 52–56%" | Our adjacency test: backtest 82%→shadow 67% WR; momo fake-fill saga | ✅ same lesson, independently learned |
| "70% WR can lose; entry price sets breakeven" | Favorite-longshot knife-edge (momo HOLD, ce25 sweeper retraction: 86.5% WR vs 95.6% breakeven) | ✅ |
| "Bid below ask → adverse selection" | Arms C/D static ladders SIG-NEG (−0.24..−0.41) | ✅ |
| "Split by weekday/UTC hour; regimes differ" | Our TOD gate (exclude {12,17} UTC, 22–02 boost) OOS-confirmed | ✅ |
| "BTC entries >85¢: one late reversal destroys many windows" | Our forensics measured EXACTLY this in his own tape: ≥0.90 fills −$1.96/fill, 2 late-reversal slugs wiped 22 wins | ✅ — and explains why he warns about it |

**Conclusion: the article is genuine** — every checkable claim matches what we independently measured.
That raises confidence in the parts we could NOT check (the WS-racing internals, pre-built orders).

## 2. What the article REVEALS that our decode could not see (the missing mechanism)

Our ladder sim NO-GO had one fatal gap: **pair fraction 28–29% vs his 44%** — we join the FIFO queue
behind 60–560 resting shares. The article explains how he avoids that queue position:

1. **WS connection racing** — 100–300 parallel connections per feed, take the FIRST deduplicated tick,
   kill the slowest 10% every 4s (jitter EMA), staggered startups. → He sees every book change first,
   so his cancel/replace lands FIRST at freshly created price levels = front-of-queue where the queue
   doesn't exist yet. **This is the 44% pair fraction.** Our infra (Python TV AND TVRUST) runs ONE
   WS book mirror with REST fallback.
2. **Pre-built orders** — HMAC sigs/headers/bodies pre-computed before the window; hot path = clone+send.
   His ladder lives on a discrete 1¢ price grid with deterministic clip-per-price → the ENTIRE ladder
   (token × level × size) is pre-signable at window open. Both our stacks build+sign at fire time.
3. **CPU pinning** — signal / submission / WS on separate dedicated cores (no contention spikes).
   TVRUST = default tokio multi-thread, no affinity.
4. **Data-quality gating** — 15s pre-window warmup, ≥3 clean ticks/token, no >5¢ jumps, drop first tick
   (cached snapshot), reject >15¢ deltas, skip the window entirely on a failed gate. We have none of
   this as an explicit layer; the momo fake-fill and stale-data sagas were exactly this class of bug.
5. **Drawdown-map stops + loss-cluster pause** — per-entry-price drawdown profiles from his own recorded
   data ("at 72¢: 63% chance of an ≥11¢ dip pre-resolution"); 2–3 consecutive losses → skip windows;
   daily DD circuit breaker. NOTE: for the two-sided ladder itself his tape shows ~no stop usage
   (sells ≈4% non-CTF) — the stop framework applies to his directional/other bots. Do not bolt stops
   onto the ladder (two-sided = self-hedged); DO take the circuit-breaker + loss-pause + >85¢ filter.
6. **Own tick-level recording with own latency measurements** (1TB/day raw → 75GB/day vectorized).
   Our canonical L25 = 10Hz snapshots from VPS2; we have no per-hop latency tape of our own execution.
7. **Own Polygon node mempool reads (320ms vs 2450ms)** — copy-trading only. NOT our strategy. PARK.

## 3. Re-analysis of the strategy understanding (corrections)

- **Unchanged:** two-sided price-following proportional ladder, no signal, hold to resolution, paired
  sum<1 capture engine, residual drag, rebates ~17%. The article's "EV framework" = the clip∝price rule.
- **Refined:** the moat is not "infra" generically — it's the **data-freshness race**. The ladder logic
  is trivial; being first to KNOW the book changed is the entire business. Our sim modeled queue position
  at existing levels; his fills come disproportionately from being FIRST at new levels (zero queue ahead).
  This also explains why our sim's pvs (0.939) was BETTER than his (0.975) on fewer pairs: we only "filled"
  where queues were short = deeper discounts; he fills everywhere because he's first.
- **Refined:** "skip the window on bad data" + warmup gate likely explains short gaps in his otherwise
  every-window cadence.
- **New risk rule to adopt from his own measured pain:** strict filter on >85¢ entries for BTC ladders
  (cap clip or skip level) — his late-window extreme fills were the −EV part of his own book.

## 4. What we have in TV/TVRUST today (relevant inventory)

| Capability | Python TV (live) | TVRUST (Ireland A/B `:8444`) |
|---|---|---|
| Location | Ireland (optimal) + VPS3 | Ireland, isolated, fail-closed |
| Poly book feed | single WS BookMirror (Tier-1), REST T2 | single dynamic book mirror, watch channel |
| Order path | python clob client, sign at fire | `ClobLiveSubmit` (EIP-712, clob-sdk), sign at fire |
| Strategies | sniper gates/sleeves, scalp, momo... | sniper(119 gates), scalp, v52, kalshi, hl |
| Risk rails | 11 rails | rails 3/4/5/11 live; 2/8/9 deferred |
| Redeemer | python loop | ported (local commit `aedfa5c`), needs deploy |
| Latency instrumentation | none per-hop | none |
| WS racing / dedup / warmup gates | none | none |
| Pre-signed order ladders | none | none |
| CPU pinning | none | none |
| Maker/ladder strategy | none (taker sleeves only) | none |
| Tick recording w/ own latency | VPS2 10Hz L25 collector | none |

## 5. MODIFICATION PLAN (build order = the article's order: infra → data → strategy → deploy)

### Phase A — TVRUST infra (prerequisites, ~the whole edge)
- **A1 `tv-feeds-racer`:** N parallel Poly market-WS connections (start N=8–16, measure; article's 100–300
  needs rate-limit testing), per-tick dedup (token, book-hash/seq), first-wins bus, per-conn jitter EMA +
  cull slowest 10% every 4s, staggered connect, drop-first-tick, >15¢ delta reject, 15s warmup gate with
  ≥3-clean-ticks/no->5¢-jump check → window-skip signal. Replaces the single mirror FOR THE LADDER LOOP
  (sniper keeps the existing mirror until proven).
- **A2 pre-signed ladder grid in `tv-venues`:** at window open pre-build+EIP-712-sign orders for
  (2 tokens × ~12 price levels × clip(price)); hot path = lookup, stamp salt/nonce if required, POST.
  Measure: sign-time saved per requote (target hot path <1ms ex-network).
- **A3 CPU pinning:** `core_affinity` — WS-racer core, ladder-decision core, submit core (Ireland box
  cores permitting; check `nproc` and Python TV contention — the box ALSO runs live Python TV. If
  contention is real, this argues for a second dedicated box later).
- **A4 latency tape:** µs timestamps at every hop (tick-recv → dedup-win → decision → submit → ack →
  fill event), persisted to `tradingvenue_rust` — this is also the "record your own data" layer start.

### Phase B — `tv-strat-ladder` (the strategy)
- Two-sided price-following ladder: on every (deduped) book change, requote 1–3 levels/side, clip∝price
  (b945 curve, $100/side/slug budget cap), no stops, hold to resolution (redeemer already ported).
- Filters: skip-window on warmup-gate fail; >85¢ level cap/skip (BTC); inventory cap/slug.
- Risk: daily DD breaker (rails live), ADD consecutive-loss pause (2–3 losing SLUGS → skip next K windows),
  per-slug telemetry: pvs, pair fraction, paired/residual PnL split (the go/no-go metrics).
- Markets: btc-updown-15m only first (his market; densest books).

### Phase C — deployment pipeline (article phases, mapped to our A/B setup)
- **C1 zero-balance dry run** on the Rust box (creds, $0): real orders → NSF rejections etc. = data.
  Judge ONE number: **live pair fraction + achieved pvs** vs brackets (sim-FIFO 29% = fail, b945 44% = target).
  Cheap intermediate proxy before creds: paper mode + racer telemetry measuring "would-have-been-first-at-level" rate.
- **C2 small capital** ($50–100 inventory cap) only if C1 pair fraction materially beats 29%.
- **C3 scale in steps**, monitor fill rate / pvs / DD vs baseline; alerts (Pushover/Discord env already wired).
- 3% backtest↔dry-run tolerance is unattainable for a queue strategy offline — replace with the
  pre-registered bracket gate above.

### Explicitly NOT doing
- Polygon node / mempool (copy-trading only). The 100–300-connection scale before measuring N=8–16.
- Stops on the ladder (two-sided, self-hedged; his own tape shows none). Drawdown-map stops = only if we
  later run directional bots through this infra.

## 6. Open questions for the operator
1. Ireland box capacity: ladder loop + racer beside live Python TV — pin cores or budget a second box?
2. Poly WS connection limits per IP (needs empirical test in A1 — start low, ramp).
3. Probe wallet: reuse the planned `poly_ab_signer` wallet for the dry-run/probe, or separate?

---

## 7. Claim-by-claim plan impact update (2026-06-12 verification pass)

Cross-reference: `B945_MERGE_LOOP_VERIFY_2026_06_12.md`.

| Claim | Verified verdict | Plan impact |
|-------|-----------------|-------------|
| GTC ladder placed at market creation (~24h early) | CONSISTENT — 82.3% of btc-15m markets trade pre-slot_start (up to −23.9h); b945 first FILL median 38s, placement unobservable | A2 pre-signed ladder CAN be placed at market creation, not just at window open — markets accept orders up to ~24h early. Test pre-open placement in C1 |
| Mid-window MERGE loop / fills = 40% of activity | REFUTED — 1,307 mergePositions txs on-chain but 100% post-resolution (median +43s after slot end, 0% mid-window; activity-API shows 0 because ERC-4337 invisible) | REMOVE any mid-window MERGE tx logic from TVRUST. Post-resolution merge IS needed (add trivial cleanup step). Capital locked per window. |
| SPLIT + sell unwanted side | PARTIAL — 1,360 SPLIT ops confirmed; no mid-window sells | ADD `ensure_pusd_balance()` pre-session (USDC→pUSD SPLIT ~18x/day); no sell logic needed |
| GTC only, rebates = income | PARTIAL — 35–47% maker fills; $3.6k rebate confirmed | Plan unchanged; rebate income is real but small (0.29% of volume) |
| Imbalance gate (stop quoting heavy side) | WEAK CONFIRM — 5–9pp effect, not hard stop | Use soft gate: widen spread on heavy side, not full withdrawal; no specific threshold confirmed |
| 2-second requote cadence | PARTIAL — 14.9% at 2–2.5s; 30.9% sub-1s dominant | SPLIT into two loops: sub-second price-update cancel-replace + 2s post-fill GTC resubmit |
| Article's 3,500 trades / $52k / 6 weeks | REFUTED — API page cap; real = 144,584 / $1.24M | Benchmark TVRUST at 1,928 fills/day / $16.5k volume/day; not the article snapshot |

### New capital-cycle requirement
The SPLIT step is NOT optional. pUSD collateral must be pre-funded via negRisk adapter (0x4d97). TVRUST must verify `pusd_balance ≥ target_inventory` before starting the ladder loop. If depleted mid-session, pause and top up. This is a Phase A prerequisite, not Phase B.

### PnL reality (CORRECTED r2 — earlier −$8.1k figure was a ledger artifact)
The r1 "−$8.1k net" was wrong on two counts: (1) the ledger's `total_pnl` subtracted $17,873 of modeled taker fees the maker wallet never paid, and (2) it dropped 323 unmapped slugs worth +$11,725 net. Reconciled against the closed audit identity: mapped-slug cash net +$6,372 + unmapped-slug net +$11,725 + rebate +$3,645 = **+$21,742** (matches LB API exactly; see `B945_MERGE_LOOP_VERIFY_2026_06_12.md` reconciliation section). **The strategy IS net-positive: ~+$11.5/slug, ~$290/day.** Decomposition on mapped slugs: paired_nofee +$35,470 (sum<1 capture engine) vs residual_nofee −$29,335 (directional drag). The sum_asks gate still matters — the paired capture is the profit engine and median pvs = 0.968 — but the headline "deploy-blocker" framing was wrong. The real deploy question remains the LADDER_SIM pair-fraction NO-GO (28–29% vs his 44%, an infra/queue-position problem, not an economics problem).

## 8. FINAL CONSOLIDATED PICTURE (end of session 2026-06-12) — the definitive strategy spec

**The verified loop (every element ground-truthed against chain/API; article embellishments stripped):**
1. **Pre-fund pUSD** collateral via the negRisk adapter (`ensure_pusd_balance()`; he splits ~18×/day, $1.13M cycled).
2. **Place the GTC ladder EARLY** — btc-15m markets accept orders up to ~24h before the window (82.3% have
   pre-slot prints; cluster −23.5h). Early placement = front of FIFO queue when intra-window flow arrives.
   This is the missing pair-fraction mechanism the offline sim could not model (sim joined at +60s → 29%
   pair fraction vs his 44%). b945 has 0 pre-window FILLS (his levels only become marketable intra-window).
3. **Ladder shape:** both tokens, weighted curve (clip∝price, more size near current price), >85¢ levels
   filtered/capped (his own −EV zone, measured).
4. **Requote, two loops:** sub-second price-following cancel/replace (dominant mode, 30.9% gaps <1s) +
   ~2s post-fill GTC resubmit (14.9% of gaps at 2–2.5s). ~40% of fills end up taker (crossing) — GTC-purity
   is article embellishment.
5. **Inventory:** soft imbalance gate — skew/widen the heavy side (5–9pp fill-prob effect), never hard stop.
   No taker rebalancing. No stops (two-sided, self-hedged).
6. **NO mid-window merge** (1,307 `mergePositions` txs confirmed on-chain, BUT all 100% post-resolution,
   median +43s after slot end, 0% pre/mid-window — `merge_timing.parquet`, n=2,689 legs mapped; the activity-API
   shows 0 events because ERC-4337 UserOps are invisible to it). Hold EVERYTHING to resolution; pUSD-era
   redemption fires automatically ~30–70s post slot-end. Capital locked per window — size for that.
7. **Data-quality + regime guards:** warmup gate / skip-window on bad feed; daily DD breaker; consecutive-loss
   pause (2–3 losing slugs → skip K windows).

**Economics (audited):** +$21,742 lifetime / 75d tape ≈ +$11.5/slug ≈ $290/day on ~$16.5k/day volume.
Engine = paired sum<1 capture (median pvs 0.968, 72.6% slugs <1; paired +$35.5k) financed against
directional residual drag (−$29.3k) + rebates ($3.6k). Edge ≈ 0.8% of volume — infra-margin business.

**Academic context (arXiv 2508.03474):** our gate math is the paper's Market-Rebalancing-Arbitrage long
condition; $39.6M extracted platform-wide with ~99% of election arb UNcaptured; maker-side capture (his
model) is invisible to the paper's taker-only taxonomy = less studied competition. Paper's appendix H:
short-side (sum_bid>1 split+sell-both) "has more profit" — we have NEVER scanned this; cheap L25 scan TODO.

**THE one open technical question before capital:** does early placement + the two requote loops actually
deliver ≥~40% pair fraction live? Offline sims cannot answer (queue position unobservable). Answer comes
from TVRUST C1 zero-balance dry run with the pre-open placement test + pair-fraction telemetry.

**Build order (final):** A1 racer+warmup-gate → A2 pre-signed ladder + EARLY placement via gamma discovery
(markets exist ~24h ahead — discovery loop must subscribe/place at creation, like the Kalshi pre-subscribe
lesson) → A3 pinning → A4 latency tape → B tv-strat-ladder (spec above) → C1 dry run judged on pair
fraction bracket (29% fail / 44% target) + achieved pvs ≤0.98 → C2 $50–100 → C3 scale.
**Parallel cheap win:** short-side sum_bid>1 L25 scan (offline, pre-registered) — if frequent, the same
ladder infra harvests BOTH sides of the overround.
