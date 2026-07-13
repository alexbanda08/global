# Shadow deep-dive + b945 alignment check — 2026-07-13
**Data through Jul 13 21:31 (11.5 days of v3). Raws: `_ireland_6day/{ladder_all_refresh5.tsv, b945_*_2026_07_13.csv, B945_REDECODE_2026_07_13.md}`.**

## 1. Fleet status (traded-only, FULL period)
| sleeve | n | mean/win | CI95 | ex-top2 | $/day | trend |
|---|---|---|---|---|---|---|
| **btc_5m_v3** | 2,497 | **+1.093** | [+0.88,+1.31] | +1.011 | **$229** | NEW +1.157/$281 — **12/12 positive days** |
| btc_15m_v4_coc | 306 | +1.108 | [+0.61,+1.61] | +0.866 | $29 | holds; NEW 71.7% pos |
| eth_5m_v3 | 1,025 | +0.342 | [+0.18,+0.51] | +0.315 | $29 | NEW +0.543 — improving |
| btc_15m_v3 | 496 | +0.338 ns | [−0.04,+0.71] | +0.242 | $14 | NEW slice went CI>0 (+0.763, n=72 small) |
| sumpair btc | 900 | +0.843 | — | — | ~$65 | NEW +0.36 (thin, fine) |
Fleet total ≈ **$300+/day paper at ~$5–13 clips.** Go-live candidate unchanged and unweakened.

## 2. Improvement levers found (ranked, with sizes)
1. **🥇 Residual "coinflip" gate (btc-5m):** residual legs entered at vwap **0.3–0.6 lose money** (−0.279 and −0.220/win, n=1,113 windows) while both tails are positive (+0.198 cheap / +0.184 expensive). Recoverable ≈ **+$25/day (~11% uplift)**. Mechanism = our own cloud_vwap coinflip-filter pattern: mid-band residual = pure coin-flip inventory with no mispricing to harvest. **Implementation: flatten immediately (not at T−45s) when residual entry ∈ (0.30, 0.60).** ETH shows the same shape but narrower (only 0.3–0.45 negative).
2. **🥈 Quote-depth bracket test:** we run d2 only. b945 has moved his maker depth **from −3 ticks to −1** (shallower, closer to touch) while accelerating to his best-ever P&L — evidence the current regime rewards more aggressive quoting. The d4 variant is already built (flag off). **Enable d4 AND add a d1 paper variant → 3-point depth curve.**
3. **🥉 Size-up/multi-clip:** corr(fill $, net) = +0.41, flow capture only 0.22% of visible sell flow (8,767 sh/window market flow vs our ~18 sh) — the big scale lever, consistent with ce25 (12 clips) and b945 (clips now $12.80). Paper variant with 2× clips first. (Caveat: the correlation is partly crash-window driven — the sizing test must watch tail exposure.)
4. pvs gate 0.99→0.995: binds 19.7% of windows (~411 sh/day suppressed) but marginal pairs are near-zero EV by construction — weak lever, sensitivity-test only.
5. Hour-23 soft-avoid: mean +0.014 vs fleet ~+1.1 — real but small; skip for now.
**Discipline note: ship all of these as PARALLEL PAPER VARIANTS. `poly_ladder_btc_5m_v3` stays FROZEN as the go-live baseline — no config churn on the candidate mid-gate.**

## 3. b945 alignment check (fresh pull Jul 9–13, 4.33d, 3,500-row cap)
**Reliable numbers:**
- Lifetime +$34,409 — **+$6,123 in 11.7 days = $524/day, his best stretch ever, accelerating** (was $96–310/day).
- Still BTC-only, 5m+15m ~50/50, 0% sells, pvs 0.973, clip median $12.80 (up from $11).
- Classification (74.7% coverage): **maker share UP 42.8%→57.8%$**, and **maker depth SHALLOWER: −1 tick median (was −3)**.

**NOT reliable (do not act on):** the per-slug PnL (gross +$62/day, "5m flipped negative for him") — the data-api row cap truncated ~32% of his fills this pull, so per-slug legs are incomplete → cost/win arithmetic garbage (this wallet's documented accounting trap). Same caveat may inflate the "pair_frac collapsed to 0.15" reading (missing legs mimic lopsidedness). His true per-market split needs an Alchemy chain pull if we ever want it. Our OWN 5m tape (2,497 windows, CI>0) massively outweighs his truncated 4-day sample on the "is 5m good" question.

**Alignment verdict: we are strategically in line and converging on scale.** Same machine (two-sided BTC maker, deep quotes, pair capture, hold+redeem), and our paper fleet ($300/day) is now the same order as his real $524/day. The one directional divergence: **he has moved toward the touch (−1) and bigger clips while we sit at −2 with $5 clips** — exactly what improvement levers #2 and #3 test. The market's most successful practitioner of our strategy is currently voting for *more aggression*, not less.

## 4. Actions
1. TV agent (AFTER the live-session items — don't preempt the go-live queue): v3.1 paper variants — residual coinflip gate (0.30–0.60 early-flatten), d1 + d4 depth variants, 2× clip variant. All parallel paper, candidate frozen.
2. Bank: b945 accelerating + shallower + bigger = regime rewards aggression; recheck his depth in 2 weeks.
3. If his per-market split ever matters: Alchemy full-chain pull, not data-api (row cap = broken ledgers).
