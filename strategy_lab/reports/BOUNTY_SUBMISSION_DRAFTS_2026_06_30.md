# Bounty submission drafts — 3 skill options (copy-paste ready)
**2026-06-30. One full draft per candidate skill. Pick one, paste into the form. Fields match the submission modal exactly.**

> ⚠️ **Two things only you can supply:**
> 1. **Link to Your Submission** = a PUBLIC repo you create (a GitHub repo holding `SKILL.md` + code). I cannot invent it. Each draft names what to put there.
> 2. **Alpha safety:** the form is public ("accessible by everyone"). Do NOT paste live strategy params, wallet addresses, or the actual edges. These drafts prove *capability + method*, not the money-making specifics. Keep the repo you link a **methodology/tooling** repo, not your live `global`/`TVRUST` trees.
>
> **Proof-link honesty:** your strongest proof is your own track record, which is private. The realistic play = publish ONE redacted artifact (a gist or repo with the *method* and an anonymized result), then cite the public papers/tools below for credibility. I did not fabricate any "you are the winner" link — those don't exist; credibility is built from the repo + citations.

---

## OPTION A — `pm-quant-edge` (Prediction-market quant-edge toolkit) ★ strongest founder-fit

**Link to Your Submission** *(you create)*
`https://github.com/<you>/pm-quant-edge` — a public repo with `SKILL.md` + the (redacted) canonical fill/fee model, the DSR/PBO validation layer, and a wallet-decode example on public chain data.

**Tweet Link** *(optional)* — your announce tweet, or leave blank.

**Did you contribute towards existing repos or is it a new idea?**
> New skill, but not a weekend idea — it packages a battle-tested private research stack I've run live for months against Polymarket + Hyperliquid: a canonical data pipeline (multi-year Binance klines, 10Hz L25 CLOB books, Chainlink oracle resolutions), a live-mimic fill engine (real maker/taker fee curve `0.07·p·(1−p)`, winner-only, book-walk fills), a deflated-Sharpe / PBO overfitting layer, and an on-chain wallet-strategy decoder. The skill is the new, shareable front-end to that stack.

**What is your closest "competing" skill?**
> Generic backtesting skills (vectorbt/`backtest`/`optimize`) and quant libraries (mlfinlab, hftbacktest). None are prediction-market-native: they model OHLC candles, not a binary CLOB with L25 depth, oracle-settled Up/Down resolution, maker-rebate income, and overround. The closest is a vectorbt backtest skill — but it can't price a Polymarket fill, resolve via Chainlink, or decode a trader's wallet. This skill is the missing PM-microstructure layer.

**Founder-market-fit (links/proofs)**
> I operate this live, not in theory: a multi-VPS stack (data collector + execution engine + a Rust A/B box) with a ground-truth-verification discipline (every "edge" is checked against real executed trades before it's believed). Track record includes reverse-engineering profitable Polymarket wallets from raw chain data and validating an intra-window execution edge through deflated Sharpe. Proof stack:
> - **Primary:** `https://github.com/<you>/pm-quant-edge` (the skill + redacted method) + a gist with one anonymized validated result.
> - **Method credibility (public):** López de Prado, *Advances in Financial Machine Learning* (Wiley 2018); Bailey & López de Prado, *The Deflated Sharpe Ratio* (SSRN); Bailey/Borwein/López de Prado/Zhu, *The Probability of Backtest Overfitting* (SSRN).
> - **Domain credibility (public):** my decode of the @0xSurferX and @l5zn1bwom8etsk ("6 edges") trader threads; Polymarket CLOB docs; Hyperliquid docs.

**Anything Else?**
> The skill's real value is discipline, not hype: it turns "my backtest shows +X%" into a fee-realistic, multiple-testing-corrected, live-shadow-gated verdict — the exact workflow that stops PM traders from deploying overfit noise. Happy to demo the wallet-decoder live on any public address.

---

## OPTION B — `quant-rigor` (Anti-overfit backtest validator) — broadest appeal

**Link to Your Submission** *(you create)*
`https://github.com/<you>/quant-rigor` — public repo, `SKILL.md` + a thin wrapper over deflated-Sharpe / PBO / CPCV / fill-haircut checks with a worked before/after example.

**Tweet Link** *(optional)* — announce tweet or blank.

**Did you contribute towards existing repos or is it a new idea?**
> New idea. It wraps established academic methods (Deflated Sharpe, Probability of Backtest Overfitting, Combinatorial Purged CV, fill haircuts) into a single Claude workflow, plus a "ground-truth verification" step of my own (reconcile every backtest number against real fills/settlements before trusting it). Builds on mlfinlab/ml4t, which I already use in production.

**What is your closest "competing" skill?**
> The existing `backtest` / `optimize` (vectorbt) skills. Critically, they *run and optimize* backtests — producing parameter heatmaps that actively *encourage* overfitting — but they never *deflate* the result: no multiple-testing correction, no PBO, no realistic-fill haircut. mlfinlab has the functions but no Claude-skill packaging. This skill is the guardrail those optimizers lack.

**Founder-market-fit (links/proofs)**
> I've caught real overfits in my own operation using exactly this method: a strategy whose "out-of-sample" was contaminated (tail-split, not disjoint), a signal that failed Bonferroni, a ~1-second look-ahead that inflated a backtest ~41%, and a paper sleeve booking a placeholder fill that faked its entire PnL. Living proof I apply the rigor rather than sell it. Proof stack:
> - **Primary:** `https://github.com/<you>/quant-rigor` + a gist showing one "backtest said +X, deflated truth = flat" case (anonymized).
> - **Public method anchors:** Bailey & López de Prado, *Deflated Sharpe Ratio* (SSRN); *The Probability of Backtest Overfitting* (SSRN); López de Prado, *Advances in Financial Machine Learning*; hftbacktest; vectorbt.

**Anything Else?**
> One-line pitch: this skill turns "my backtest is profitable" into "here's the number after selection bias, multiple testing, and realistic fills — and whether it survives." It's the check every retail quant skips and every serious desk runs.

---

## OPTION C — `hft-feed-race` (Maker-infra / feed-race moat) — the 0xSurferX-thread angle

**Link to Your Submission** *(you create)*
`https://github.com/<you>/hft-feed-race` — public repo, `SKILL.md` + a reference N-connection WS racer (first-wins dedup), a per-hop latency tape, and a two-sided maker-ladder skeleton (venue-agnostic; no live keys).

**Tweet Link** *(optional)* — announce tweet or blank.

**Did you contribute towards existing repos or is it a new idea?**
> New idea, extracted from a Rust execution engine I built. It packages the "infrastructure moat" the 0xSurferX thread describes — multi-connection feed racing, pre-signed orders, queue-priority maker quoting, microsecond latency instrumentation — as a reusable skill/skeleton. The live engine stays private; the skill ships the pattern.

**What is your closest "competing" skill?**
> There's no Claude skill for this. The closest analogs are hftbacktest (a simulator, not live infra) and generic ccxt/websocket boilerplate (a single connection, no racing, no queue model, no latency tape). None package the multi-connection race + first-wins dedup + queue-priority + per-hop latency measurement that actually wins fills in production.

**Founder-market-fit (links/proofs)**
> I didn't read about this — I built and measured it. My Rust engine runs a 4-connection feed racer with a ~20–60µs receive-to-apply hot path and 13 days of live paper evidence that early placement + racing beats the offline model (a passive maker book paired 80% of its fills live vs a 29% offline ceiling — the exact live-only edge the thread claims). Proof stack:
> - **Primary:** `https://github.com/<you>/hft-feed-race` (racer + latency tape reference).
> - **Evidence (publish a redacted one-pager):** the latency distribution + the live-vs-offline pair-fraction result, numbers only, no venue params.
> - **Context (public):** the @0xSurferX thread this responds to; Polymarket CLOB WS docs; hftbacktest.

**Anything Else?**
> The moat is a data-freshness race + queue priority, and I have live latency + fill telemetry proving it — not a claim, a measurement. The skill hands anyone the racing + instrumentation scaffold so they can measure their own edge instead of guessing.

---

## Fields that are the SAME across all three
- **Tweet Link:** optional — only if you announce it on X.
- **KYC checkbox:** tick it (standard; only matters if you win).
- **"Link to Your Submission":** must be public + clickable. If you have nothing public yet, the fastest path is a new GitHub repo with just the `SKILL.md` + a minimal working example — reviewers need to click *something*.

## My recommendation
**Option A** if the bounty rewards depth + a real operator (strongest founder-fit, hardest to fake). **Option B** if it rewards broad usefulness (every quant needs it, lowest barrier to a public repo). **Option C** if the bounty is specifically about the 0xSurferX/HFT-infra theme. If unsure which the sponsor wants, A is the safest high-ceiling bet.
