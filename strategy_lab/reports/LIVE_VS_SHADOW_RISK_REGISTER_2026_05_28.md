# Live-vs-Shadow Risk Register — Maker-Arb Sleeves

**Date**: 2026-05-28
**Question**: what can go wrong LIVE that the shadow simulation does not capture?
**Context**: shadow engine is economically EXACT per `ENGINE_CORRECTNESS_AUDIT_2026_05_28.md`, but "exact accounting of simulated fills" ≠ "what really happens when real orders hit a real venue with real competitors."

Risks ranked by severity × likelihood. Each: what shadow assumes, what live actually does, mitigation.

## TIER 1 — could flip a profitable sleeve to a loser

### R1. Partial fills / queue jumping (HIGH)
- **Shadow**: when our queue position drains to 0, we fill 100% of posted size at our price.
- **Live**: an aggressor order smaller than our size only fills us partially. Other makers can sit AHEAD of us (iceberg/hidden size, or they re-post at a better price and jump the queue). We may fill 0% on a slug we "should" have filled.
- **Impact**: fewer paired fills → fewer merges → more single-side inventory carried to resolution = directional risk we didn't sign up for. Audit estimated 10-25% over-fill in shadow.
- **Mitigation**: `tv_poly_maker_partial_fill_ratio` knob (default 0.8) + monitor live fill rate vs shadow in first 7 days. If live fill rate < 60% of shadow, re-size expectations down.

### R2. Cancel-vs-fill race (adverse selection you actually eat) (HIGH)
- **Shadow**: phantom-fill guard DROPS any fill that happens after the strategy decided to cancel → conservative, we never "eat" the bad fill.
- **Live**: you decide to cancel at T, but the cancel takes ~50-100ms to land. In that gap, an informed aggressor hits your stale order. You DO eat it. This is exactly the toxic flow that maker-arb is exposed to.
- **Impact**: the convergence-cancel fix reduces this but doesn't eliminate it. Live realized adverse selection will be WORSE than shadow's 25bps haircut suggests, especially in the 50-100ms cancel window.
- **Mitigation**: pre-signed cancels + sub-100ms cancel path (already a P-requirement). Widen adv-sel haircut to 35-50bps for live projection. Cancel earlier (bigger convergence offset).

### R3. Informed-flow adverse selection beyond the flat haircut (HIGH)
- **Shadow**: flat 25bps haircut on every fill, regardless of context.
- **Live**: adverse selection is STATE-DEPENDENT. You get filled precisely when someone knows the price is about to move — news prints, large CEX liquidations, oracle updates. Per Bartlett & O'Hara, single-name short-duration markets (our exact universe) are the TOXIC regime where the behavioral-surplus cushion may not apply.
- **Impact**: the 25bps average hides a fat tail. On a news day, your fills could be −200 to −500 bps. A single bad hour can erase a week of edge.
- **Mitigation**: VPIN-style toxicity gate (pull quotes when order-flow imbalance spikes). News-feed kill switch (Yahoo/CEX-liquidation triggers). Hard daily-DD circuit breaker.

### R4. Self-competition across sleeves on the same cell (HIGH for live, invisible in shadow)
- **Shadow**: ACC-H-V2 and ACC-PC-V2 both run btc_15m as INDEPENDENT wallets. Each gets its own fills, own PnL.
- **Live**: they'd be the SAME wallet (or two wallets we control) posting on the same book. They compete with each other — split the available fills, double the capital tied up, and if both fill they double our exposure on one slug. Polymarket sees them as separate accounts ADDING to book depth, increasing our own adverse selection.
- **Impact**: live combined PnL of (ACC-H + ACC-PC on btc_15m) will be LESS than the sum of their shadow PnLs, not equal.
- **Mitigation**: ONE sleeve per cell live. `TV_POLY_MAKER_KILL=<loser>:<cell>` after picking the better of each pair from shadow.

## TIER 2 — bleed / operational failure

### R5. Capital & inventory constraints (MEDIUM)
- **Shadow**: effectively unlimited capital; every signal that passes gates gets posted.
- **Live**: USDC tied up in open paired inventory can't fund new posts. Hit the wallet cap → miss the next slug's posts. Shadow over-counts the opportunity set.
- **Impact**: live captures fewer slugs than shadow at a given wallet size. Real $/day < shadow $/day at the recommended ~$84-104/sleeve wallet.
- **Mitigation**: size wallet for p99 concurrent in-flight, not p95. Monitor "skipped post: insufficient balance" events.

### R6. Gas balance + on-chain tx failure (MEDIUM)
- **Shadow**: MINT/MERGE/REDEEM settle instantly and always succeed.
- **Live**: needs MATIC for gas. If MATIC depletes, every CTF op fails silently — you stop merging/redeeming and inventory piles up unhedged. Polygon congestion can delay txs minutes. A reverted MERGE leaves you holding pairs past resolution.
- **Impact**: a gas-out is a silent kill — looks like the strategy stopped working with no error in PnL.
- **Mitigation**: MATIC balance alert (< 5 MATIC → page). Auto-topup. Retry logic on reverted CTF txs. Nonce manager.

### R7. Redemption timing & locked capital (MEDIUM)
- **Shadow**: credits $1/winner-share at the instant of resolution.
- **Live**: chainlink must finalize, THEN you call redeemPositions, THEN wait for confirmation. Capital is locked from slug-end until redemption confirms — minutes to hours. During congestion, longer.
- **Impact**: effective capital turnover is slower than shadow assumes → lower $/day at fixed wallet, OR need more wallet to maintain cadence.
- **Mitigation**: batch redemptions. Size capital for the redemption lag, not just in-slug peak.

### R8. Order rejection / API rate limits (MEDIUM)
- **Shadow**: every POST/CANCEL is accepted.
- **Live**: ACC-H re-quotes ~130 times/slug. At scale across 4-6 sleeves that's thousands of orders/min — may hit Polymarket operator-tier rate limits → orders rejected → missed fills. CLOB also rejects on min-size, price-band, maintenance windows.
- **Impact**: rejected posts = missed opportunities; rejected cancels = stuck adverse-selection exposure.
- **Mitigation**: confirm operator rate-tier ceiling. Throttle re-quote frequency. Handle rejections gracefully (retry/backoff).

### R9. WS feed disconnect / staleness (MEDIUM)
- **Shadow & live both** use BookMirror/TradeMirror WS. But live has the extra risk: if the WS lags or drops, you post/cancel against a stale book. Fills compute against the wrong prices.
- **Impact**: stale-book fills are systematically adverse (you only get filled when your stale price is now off-market).
- **Mitigation**: WS heartbeat monitor; pause posting if mirror age > 2s (the sparse-book gate partially covers this). Already a Tier-3 fallback exists.

## TIER 3 — model / regime risk

### R10. Fee model flips (MEDIUM, already flagged)
- **Shadow**: currently `0.07 curve`; spec pending switch to `legacy_2pct`.
- **Live**: Polymarket can turn fees ON for crypto up-down at any time (governance/contract change). If they flip to the real 0.07 curve, every sleeve's economics shift overnight — taker-heavy sleeves get much worse.
- **Mitigation**: the `tv_poly_maker_fee_model` selector (per `TV_AGENT_FIX_FEE_MODEL_SPEC.md`) lets us flip in one config change. Monitor actual fees on live fills weekly.

### R11. Edge decay / regime shift (MEDIUM)
- **Shadow**: 2-3 days of data, likely a single vol regime.
- **Live**: maker-arb edge is regime-dependent. A trending or high-vol week increases single-side fills and adverse selection. Other bots copying the same paired-bid template compress the spread over weeks.
- **Impact**: the +$1,800/day projection is a snapshot. Real sustained rate could be half that after competition + regime cycling.
- **Mitigation**: don't extrapolate 3 days to a month. Run 14-30 day shadow before sizing up. Monthly re-validation. Trailing-Sharpe kill switch.

### R12. Resolution / oracle disputes (LOW but tail-fatal)
- **Shadow**: chainlink `outcome` is ground truth, instant, always correct.
- **Live**: Polymarket settlement can lag chainlink, use UMA optimistic oracle for some markets (disputable), or void a market. CLAUDE.md notes 300/300 chainlink-vs-CLOB-winner agreement so far — but not guaranteed forever.
- **Impact**: a disputed/voided market with our capital in it = frozen funds or wrong-side settlement. Rare but unbounded.
- **Mitigation**: cross-check chainlink vs CLOB winner on every resolution; alert on any disagreement. Cap per-slug exposure.

### R13. Market-impact / book signaling at scale (LOW now, HIGH at scale)
- **Shadow**: we're an infinitely small price-taker on liquidity.
- **Live at POST_SIZE 100+**: our orders are a meaningful fraction of book depth. Other makers detect our pattern and adversely adjust. Our own posting moves the mid.
- **Impact**: sub-linear scaling (edge per $ drops as size grows — literature exponent ~0.5). The $2,500-wallet → $2,400/day projection likely won't materialize linearly.
- **Mitigation**: scale POST_SIZE gradually (20 → 50 → 100), measure $/slug at each step, stop scaling when marginal $/slug drops.

## Summary table

| # | Risk | Tier | Shadow captures? | Live direction |
|---|---|---|---|---|
| R1 | Partial fills / queue jump | 1 | No (100% fill) | worse |
| R2 | Cancel-vs-fill race | 1 | No (drops fill) | worse |
| R3 | State-dependent adverse selection | 1 | Partial (flat 25bps) | much worse on tails |
| R4 | Self-competition same cell | 1 | No | worse |
| R5 | Capital/inventory limits | 2 | No (unlimited) | fewer fills |
| R6 | Gas-out / tx failure | 2 | No | silent kill |
| R7 | Redemption lag | 2 | No (instant) | slower turnover |
| R8 | Order rejection / rate limits | 2 | No | missed fills |
| R9 | WS staleness | 2 | Shared + extra live risk | adverse fills |
| R10 | Fee model flip | 3 | Configurable | step-change |
| R11 | Edge decay / regime | 3 | No (3-day snapshot) | lower sustained |
| R12 | Oracle dispute | 3 | No (chainlink=truth) | tail-fatal |
| R13 | Market impact at scale | 3 | No | sub-linear scaling |

## The one-paragraph answer

Shadow gets the **book and the settlement math** right, but it assumes **you always win the race**: orders land instantly, fill fully, cancel before toxic flow hits, capital is unlimited, gas never runs out, and resolution is instant and certain. Live, you're racing sub-150ms bots for fills, eating the fills you tried to cancel, splitting liquidity with your own other sleeves, waiting hours for redemptions to unlock capital, and exposed to a fat tail of news-driven adverse selection that a flat 25bps haircut can't represent. The net: **live $/day will be meaningfully below shadow $/day** — most of the gap from R1-R4 (fills + competition + adverse selection). Expect 40-70% of shadow PnL to survive to live at small size, less as you scale.

## Recommended pre-live gauntlet

1. **Paper at $5-25 stake for 7 days** — measure live fill rate vs shadow (R1), live adverse selection vs 25bps (R3), redemption lag (R7).
2. **One sleeve per cell** — eliminate R4 before measuring anything.
3. **Instrument**: live-vs-shadow fill-rate delta, realized adv-sel bps, MATIC balance, order-rejection rate, redemption confirm latency.
4. **Kill switches live from day 1**: daily DD cap, consecutive-loss pause, MATIC-low alert, WS-stale pause, fill-rate-collapse alert.
5. **Scale only after** live $/slug ≥ 50% of shadow $/slug holds for 7 consecutive days.

## References
- Engine correctness: `strategy_lab/reports/ENGINE_CORRECTNESS_AUDIT_2026_05_28.md`
- Fill-sim realism sub-report: `migration_ireland_audit_2026_05_28/engine_audit/fill_sim_realism_audit.md`
- Adverse-selection literature: Bartlett & O'Hara (Stanford SSRN 6615739)
- Deploy decisions: `strategy_lab/reports/MAKER_ARB_DEPLOY_DECISIONS_2026_05_27.md`
