# TV AGENT SPEC — TVRUST b945 two-sided MAKER ladder + data-feed quality layer
**2026-06-13 · for the TVRUST engine agent · target: PAPER-fire on Ireland `:8444`, observe, then stage to live**

> **⚠️ CORRECTED 2026-06-13 by `B945_SESSION_REAUDIT_2026_06_13.md` — read this box first.** An adversarial
> re-audit overturned 3 premises this spec was originally built on. Apply these corrections throughout:
> 1. **MAKER-ONLY.** REMOVE the taker-completion rule (§1.5) — his taker fills happen at sum_asks ≥1.0
>    (the completion gate never fires; verified 0/27,039 below 1.0). Taker is overhead, not edge. Run
>    passive maker; let taker fills be emergent, measured not engineered.
> 2. **No 24h-early placement.** Place at/near window open. Pre-window activity is ~−176s (not −23.5h);
>    b945 has zero pre-window fills; early placement explains <5% of his edge. Discovery just needs to
>    find the market — do NOT build a 24h-ahead queue-priority path.
> 3. **The moat is dense competitive MAKER pricing + tight inventory control (residual drag is the real
>    constraint), NOT queue priority / speed / early placement / taker tricks.** True flow capture target
>    is **~11.5%** (his level), not 28.5%. Dry-run gate → **≥~12% live capture + positive thin-flow week.**
> 4. **GLT cap Q ≈ 3–5, NOT 20.** Verified 2026-06-13 (`MM_Q_AND_SHORTSIDE_2026_06_13.md`): tight Q is the
>    dominant OOS lever — OOS net is monotone in Q and only Q≤5 clears breakeven in thin flow (Q5 +$0.39,
>    Q20 −$0.69). Default the ladder to **Q≈3–5**. (Caveat: thin/tail-driven edge, median still negative —
>    the dry-run promotion gate must require positive net AND healthy %-positive across MULTIPLE thin weeks.)
> The data-quality feed layer (§3.1) and trade-feed-for-metrics remain valid (clean data + measurement).

This spec is self-contained. It encodes everything decoded + validated this session about Polymarket
maker wallet `0xb945945d` (+$21,742 audited) and turns it into an implementation plan for the Rust
engine. Build it to **paper-fire first** so we can watch the feed, the logs, and the flow-capture
metric, and clear every unknown before any capital. Supporting reports (read only if you need depth):
`MM_HYBRID_REPLICA_2026_06_13.md`, `MM_ENGINE_QUEUE_REPLAY_2026_06_12.md`,
`TVRUST_LADDER_INSERTION_MAP_2026_06_12.md`, `B945_ARTICLE_INFRA_GAP_ANALYSIS_2026_06_12.md`,
`B945_ONCHAIN_TX_TAXONOMY_2026_06_12.md`, `AVELLANEDA_STOIKOV_FOR_LADDER_2026_06_12.md`.

---

## 0. The one thing to internalize before building

We built a realistic queue-aware backtest (replays the real trade tape through a per-order FIFO queue)
and **validated it reproduces b945's audited economics in-sample** (net +$3.56/slug vs his +$1.72 GT).
It then **failed out-of-sample for exactly one reason: flow capture.** Our offline model ceilings at
**~4–7% of market taker flow; b945 captures ~28.5%.** Nothing offline closes that gap.

**Critical, counter-intuitive finding that must shape the build:**
> **SPEED IS NOT THE LEVER.** We swept requote latency 0ms→2s and flow capture + PnL were **FLAT**.
> Even a physically-impossible 0ms requote did not improve OOS. So **do NOT build a sub-millisecond
> arms race.** A 100ms poll loop is sufficient. The article over-emphasizes raw speed; our data says
> the wins are in (a) **data cleanliness**, (b) **early placement for queue priority**, (c) **inventory
> discipline**, (d) **measuring real live flow capture** — NOT in shaving microseconds.

The whole point of the paper build is to **measure our real live flow capture** (the only unknown left)
against the **promotion gate: ≥~20% flow capture + positive net on a thin-flow week**, before capital.

---

## 1. The strategy (exact, validated config)

**Market:** `btc-updown-15m` ONLY for v1 (his market; densest books). Generalize later.

**The loop, per window:**
1. **Early placement** — these serial markets accept orders ~24h before the window (82.3% have pre-slot
   prints, cluster −23.5h). Discover the market at/near creation and place the ladder EARLY → front of
   the FIFO queue when window flow arrives. This is the queue-priority moat (our +60s sims got 29% pair
   fraction; early placement is how he gets ~44%).
2. **Two-sided GTC maker ladder** — rest BUY bids on BOTH Up and Down tokens, multiple price levels
   across the near-mid band, **clip ∝ price** (EV layering): ~$0.34 of size at 2¢ → ~$27 at 97¢, $5
   median clip. **Skip/cap levels > 0.85** (his own measured −EV zone — one late reversal there wipes
   many windows).
3. **Requote** on book change: cancel/replace to keep the ladder in the target band + re-post a fresh
   clip after each fill (≈2s post-fill cadence is fine; **sub-second is unnecessary** per §0).
4. **Inventory discipline** (this is what makes it profitable — the residual is the enemy):
   - **GLT hard cap `Q`**: when `|sh_up − sh_dn| > Q`, STOP quoting the heavy side until the light side
     catches up. **Q = 20 shares** (validated; dominant net lever — Q∞→20 moved net −$9.46→−$0.31).
   - **AS reservation-price skew `γ`**: skew each side's bid by `−q·γ·σ²·(T−t)` where `q` = net residual
     (favor the light side), `σ` from oracle/token vol, `(T−t)` = time to resolution. **γ = 0.05**
     (validated). See `AVELLANEDA_STOIKOV_FOR_LADDER_2026_06_12.md` for the adapted math + a golden
     vector. NOTE: `q` is the **net residual**, NOT gross inventory (the paired part is riskless).
5. **Taker-completion** (his 37% taker = "recalibrate with taker"): when holding unpaired inventory on
   side X (`resid > trigger`) AND the opposite side's live ASK `a_opp` would complete a pair at
   `our_vwap_X + a_opp < gate_G`, **lift the ask** to lock the pair. **gate_G ≈ 0.985, trigger ≈ 20–50
   sh** (validated). This reduces residual drag. Taker fee applies (see §6); only take when it keeps the
   pair net-profitable after fee.
6. **Hold to resolution.** No stops (two-sided book is self-hedged). At resolution the winner leg
   redeems $1.
7. **Collateral recovery** — post-resolution only: `mergePositions` recovers paired collateral,
   `redeemPositions` settles the residual. Handled by the Polymarket relayer + the already-ported
   redeemer loop. **No mid-window merge. No split/mint** (he never splits — verified on-chain).

**Validated parameter block (paper defaults):**
```
market            = btc-updown-15m
placement_offset  = -3600 s  (≈1h early in paper; extend toward -24h once discovery supports it)
budget_per_side   = $332      (his real per-side deploy; scale down for paper-economics realism)
clip_usd          = $5
n_levels          = 10-20 across the near-mid band (DENSE — multi-level is lever (a))
max_price_level   = 0.85      (skip levels above)
glt_cap_Q         = 20 shares
as_skew_gamma     = 0.05
taker_gate_G      = 0.985
taker_trigger     = 20 shares
poll_interval     = 100 ms    (NOT sub-ms — speed is flat)
```

---

## 2. Wallet/venue facts (so you don't re-derive them)

- `0xb945945d` is a **Gnosis Safe 1.3.0 proxy**; it never self-submits — fills via the operator's
  `matchOrders`, merges via ERC-4337 bundler UserOps, redeems via relayer Safe calls. Standard
  Polymarket rails; TVRUST's existing clob-sdk path uses the same.
- **Maker/taker = 63/37** (OrderFilled-log truth). Fees only on the 37% taker fills.
- **Fee model (winner-only):** taker leg pays `0.07·p·(1−p)` per share ONLY if it wins; maker legs pay
  $0 + pool rebate (~0.0015/sh income); **redeem pays full $1, no fee.** Never apply the taker fee to
  maker or redeem legs (this bug produced 4 fake-negative ledgers — do not repeat).
- Edge ≈ 0.8% of volume; ~+$3.18/slug median; it's a **volume × tiny-edge** business — capital turns
  over per window (locked, no intra-window recycle).

---

## 3. Infrastructure changes — mapped to TVRUST code surfaces

From `TVRUST_LADDER_INSERTION_MAP_2026_06_12.md`. Effort: S/M/L. Build order top→bottom.

### 3.1 Data-feed quality layer (`tv-feeds`) — the article's "websocket quality" section
**This is for CLEAN DATA, not speed.** Our momo fake-fill + stale-data sagas were exactly this bug class.

- **C1a — Trade feed (NEW, required for the flow-capture metric):** subscribe to the Polymarket market
  **trades** WS channel for the active window tokens, in addition to the book channel. We MUST know
  total market taker flow per window to compute flow capture (our fills / market flow) — the headline
  paper metric. Today TVRUST only mirrors the book. Add a `trade_tape` consumer alongside `poly_book`.
- **C1b — N-connection racer (M):** N parallel WS connections to the market channel (**start N=4–8,
  measure rate limits; do NOT jump to 100–300 before testing**), dedup first-wins by `(asset_id,
  hash/seq)`, per-conn jitter EMA + cull slowest 10% every 4s, staggered connect across ~1s. All write
  to the same `Arc<Mutex<BookState>>` (idempotent last-writer-wins). Wrap/extend `poly_book::run_dynamic`;
  consumer interface unchanged.
- **C1c — Data-quality gates (S, explicit acceptance criteria):**
  - **drop-first-tick** from every new connection (cached snapshot from before connect).
  - **reject any tick with >15¢ price delta** from last-known-good; log + skip.
  - **15s pre-window warmup**: require ≥3 clean ticks/token with no >5¢ jump in the final 5s; if a token
    fails, **SKIP the window entirely** (a bad-data window traded is worse than a missed one).
  - Per-connection jitter EMA exposed in telemetry.

### 3.2 Ladder strategy loop (`tv-engine/src/loops/poly_ladder.rs`) — NEW (L, ~300–400 lines)
The existing sleeves are single-shot (one gate eval → one fire). The ladder is a **stateful continuous
quoting controller** — a new paradigm. Per active window:
- Poll `BookState` every **100ms** (sufficient; matches L25 cadence).
- Compute the target ladder (both tokens, clip∝price, AS skew, GLT cap, >0.85 filter).
- Diff vs current resting orders → emit place/cancel intents (paper: just record; live: via §3.4).
- Run the taker-completion check each tick.
- Track per-window inventory (sh_up, sh_dn, vwaps), pair fraction, pvs, maker/taker split.
- Emit telemetry (§3.6).
- Maintain `current_slug` state; reset accumulators on slug change.

### 3.3 Pre-signed order grid (`tv-venues`) — M (live only; defer for paper)
At window open, pre-build + EIP-712-sign the ladder (2 tokens × ~12–20 levels × clip(price)) on a 1¢
grid; hot path = lookup + POST. **Per §0 this is good hygiene (don't sign in the loop), NOT a speed
race** — do not over-engineer. Not needed for Stage-0 paper.

### 3.4 Order lifecycle (`LadderOrderTracker` + `LadderLiveSubmit`) — M (live only)
- `LadderOrderTracker`: `HashMap<(token_id, price_level) → order_id>` + `place_gtc/cancel/cancel_all`.
- `LadderLiveSubmit`: wraps `PolyClobClient` (`post_order` GTC + `cancel_order`, both exist); stores
  order_ids. Feature-gated `clob-sdk`, fail-closed like `ClobLiveSubmit`.
- **Paper:** `LadderPaperSubmit` — simulate fills against the live book **using the FIFO queue model
  from our offline engine** (queue_ahead = L25 depth at our level at placement, consumed by real taker
  prints from the trade feed). Do NOT use a naive "ask-touches-bid → fill" check (that overestimates;
  it ignores queue position). The realistic queue sim is what makes the paper flow-capture number
  trustworthy.

### 3.5 Discovery / early placement (`GammaSlotProvider`) — S
`build_slug` currently generates the window containing `now`. Add discovery of the **next/future**
windows (`now + k·900`, k=1..N) and place the ladder at market creation. The far-future guard
(`max_ahead_s=86400`) already permits ~24h-ahead. Publish the Up/Down tokens to the book mirror +
trade feed via the existing `tok_tx` watch channel.

### 3.6 Telemetry / flow-capture tape (`tv-persistence`) — S
Reuse `insert_event(db, kind, sleeve_id, data_json)` — no schema change. New `kind`s:
| kind | cadence | payload |
|---|---|---|
| `ladder_tick` | 10s | `{slug, up_bid_levels, dn_bid_levels, sh_up, sh_dn, pvs, pair_frac, market_flow_sh, our_fills_sh, flow_capture, book_age_ms, jitter_ema}` |
| `ladder_summary` | window end | `{slug, pair_frac, pvs, sh_up, sh_dn, paired_pnl, residual_pnl, rebate, maker_pct, taker_pct, flow_capture, net_pnl, skipped_reason?}` |
| `ladder_quote` | per requote (live) | `{token, old_order_id, new_order_id, old_price, new_price, cancel_latency_us}` |
| `feed_quality` | 10s | `{n_conns, culled, dropped_first, rejected_delta, warmup_pass}` |
**`flow_capture` and `pvs` in `ladder_summary` are THE numbers we watch.**

### 3.7 CPU pinning (`tv-engine`) — DEFER / optional
Per §0 (speed flat), this is **low priority**. The Ireland box also runs live Python TV — only pin if
contention shows up in the latency tape. Do not block the build on it.

### 3.8 Risk controls — S (mostly exist)
- DD circuit breaker (portfolio rails already live).
- Consecutive-loss pause (K=2–3 losing slugs → skip N windows). NOTE: offline this was *inert* (losses
  not removably clustered) — include it as a safety rail, not an edge.
- >0.85 level filter (in the ladder logic).
- **No stops on the ladder** (two-sided self-hedged).

---

## 4. Minimal Stage-0 paper path (smallest set to start observing)
No new crates, no creds, no `clob-sdk`. From the insertion map:
1. **NEW** `crates/tv-engine/src/loops/poly_ladder.rs` (~300 lines) — the loop (§3.2) with
   `LadderPaperSubmit` (§3.4 paper, FIFO queue model).
2. **+ trade-feed consumer** (§3.1a) so flow capture is measurable.
3. `loops/mod.rs` — `pub mod poly_ladder` (1 line).
4. `main.rs` — env flag `TV_POLY_LADDER_ENABLED=true` + spawn block reusing live `book_state`,
   `gamma_client`, `tok_tx`, `sink` (~20 lines).
5. Future-window discovery (§3.5, ~5 lines).
Defer for Stage-0: racer (single conn OK to start), pre-signing, order lifecycle, CPU pinning.
**Add the racer + warmup gates (§3.1b/c) as Stage-0.5** once the loop is producing telemetry — they're
what make the data clean and are observable in `feed_quality`.

---

## 5. Staged rollout — what each stage clears

| Stage | Creds | Capital | What it MEASURES / clears |
|---|---|---|---|
| **0 — paper** | none | $0 | Feed quality (clean ticks, warmup pass-rate), the ladder logic firing, and the **paper flow-capture + pvs + pair-fraction** via the FIFO queue sim. Answers: is our feed clean, is discovery early, does the loop behave. Watch `flow_capture` vs the **~7% offline floor / ~28% b945 target**. |
| **0.5 — racer+warmup** | none | $0 | Does multi-connection dedup + warmup gating raise clean-tick rate / would-be flow capture? `feed_quality` telemetry. |
| **1 — zero-balance real orders** | wallet+API | $0 | Real placement/cancel/reject/latency/ghost-fill flow. Validates the live plumbing (signing, order acceptance, cancel/replace). NOTE: a zero-balance GTC likely **NSF-rejects at placement** → this mostly tests plumbing, not fills. |
| **2 — small capital** | wallet+API | $50–100 inv cap | **FIRST real flow-capture measurement** (real resting orders earn real queue position). THE decision data. |

**Pre-registered promotion gate (Stage-2 → scale):**
> Ladder must demonstrate, with real resting orders, **≥~20% live flow capture AND positive net across
> a thin-flow (OOS-equivalent) week.** Only then add capital in steps (the article's Phase-3).

---

## 6. Decided facts / guardrails (do NOT re-litigate)
- **Speed is flat (0ms→2s)** — 100ms poll is fine; no sub-ms arms race; CPU pinning is optional.
- **No stops** on the ladder; **no split/mint**; **no mid-window merge** (post-resolution only, relayer).
- **Fee = winner-only `0.07·p·(1−p)`**; redeems pay full $1; rebates are income. Never fee maker/redeem.
- **Inventory discipline (GLT Q=20 + AS γ=0.05) is the profit lever**, not speed. The residual is the
  enemy; the taker-completion gate (0.985) is a residual-drag reducer.
- **Early placement = the queue-priority moat.** Discovery must place at market creation, not window open.
- **Flow capture is the unknown** the whole exercise exists to measure. Make it the headline telemetry.
- Bad-data window traded > missed window — **skip on warmup failure.**

---

## 7. Definition of done (per stage)
- **Stage 0 DONE:** `poly_ladder` loop runs on `:8444`, `ladder_tick`/`ladder_summary`/`feed_quality`
  rows land in `tradingvenue_rust.trading.events`, btc-15m markets discovered ≥1h early, paper
  `flow_capture`/`pvs`/`pair_frac` computed via the FIFO queue sim and visible in logs + terminal.
- **Stage 0.5 DONE:** racer + warmup gates live; `feed_quality` shows dedup/cull/warmup working; skipped
  windows logged with reason.
- **Stage 1 DONE:** real GTC place/cancel against CLOB with creds at $0; `ladder_quote` rows with real
  latencies; rejection codes logged + classified (NSF/timeout/ghost).
- **Stage 2 DONE:** small-capital run over a thin-flow week; `flow_capture` + net measured vs the
  promotion gate; go/no-go on scaling is a single pre-registered number.

---

## 8. Open questions for the operator (flag, don't block)
1. Ireland box: ladder loop + trade feed beside live Python TV — capacity OK, or a second box?
2. Poly WS connection ceiling per IP (racer N — start 4–8, ramp empirically).
3. Probe wallet: reuse the planned `poly_ab_signer` for Stage-1/2, or a separate funded wallet for Stage-2?
4. Paper budget: run at his $332/side (realistic economics) or smaller for faster iteration?
