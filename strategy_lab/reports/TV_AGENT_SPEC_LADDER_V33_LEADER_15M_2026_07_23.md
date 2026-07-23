# TV RUST AGENT SPEC — v3.3 "LEADER" 15m LADDER + v3.2 verdicts/kills
**2026-07-23 · TVRUST only · vps_ireland · ALL PAPER $0 · rides the next engine deploy. Live-path punch list (real-order fire-drill + $2 dry-arm) is STILL priority 1 if undelivered.**

## 0. Housekeeping FIRST (same deploy)
1. **KILL `poly_ladder_btc_15m_v32_cheapmid` NOW** — −$1,022/48h, paired t=−23.3 vs base. Root cause is a SPEC flaw (operator's, acknowledged): band B 0.50–0.62 quoted on BOTH tokens pairs at avg sum 1.177 (275/275 windows pvs>1) = guaranteed −18% per paired share. Log in ledger as `spec_defect`, not regime.
2. **KILL `poly_ladder_btc_15m_v4_coc`** — full-n paired verdict Δ−$0.063, t=−1.08 (n=1,626): adds nothing on identical windows (confirms the Jul-13 matched-slug counterfactual).
3. `poly_ladder_btc_15m_v32_cheap`: let it run to its Jul-25 pre-registered verdict, then kill unless t≥2 (currently t=−0.64 = trending negative-result). Do NOT tune its bands.
4. Kill-candidate note: `poly_ladder_eth_5m_v31_rcg` paired Δ≈0 vs eth base — kill to free a slot unless its trigger counters show it simply never fired (report `rcg_flattened_sh` total either way).

## 1. Evidence for v3.3 (operator wallet-tape audit 2026-07-23; fills scored vs our recorded outcomes)
Two independent tracked wallets — `0xb945945d…db68` (maker ladders, 7d, 7,232 btc-15m fills, +$6.17/slug, 6/6 positive days) and `0xce25e214…7fdc` (taker pair-arb "Agile-Spacing", 2d, 2,572 btc-15m fills, +$12.10/slug, taker-fee-adjusted) — show the SAME 15m structure (agree on sign in 8/9 window-third × price-zone cells, ~$100k notional):
- **CHEAP side (0.02–0.45) mid/late window = value trap**: WR 16–27% at prices implying 25–40% (b945 −3.5/−5.6%, ce25 −22/−39%).
- **FAVORITE side (0.55–0.85) early/mid = pays**: b945 +2.2/+6.5% (as MAKER), ce25 +21/+3.6%.
- **DEEP FAVORITE (0.85–1.0) = pays in EVERY third, both wallets**: +3.3..+12.6%, WR 94–100% (b945's biggest single earner: late-window 0.85+, $29k notional +3.3%).
- **5m is the OPPOSITE** (cheap +16..19% every third, favorite −5..−13% mid/late) — 5m mean-reverts, 15m polarizes+consolidates. This is why our symmetric-cheap ladders work on 5m and fail on 15m, why v32_cheap's premise (built on a 2-day tape) didn't replicate, and why the side-blind T−45 backstop amputates the winning leg on 15m.

## 2. GATE: offline counterfactual replay BEFORE any new sleeve
We hold every 15m book tick + ladder decision for 2,000+ windows. Replay `poly_ladder_btc_15m_v3`'s recorded windows with the v3.3 rules applied (same fills where rules coincide, drop trailing-side fills after t≥300s, add leader-band fills only where the recorded book shows our bid would have been touched — conservative: level-0 crossings only):
- Report replayed Δ$/window vs actual v3 with CI. **Deploy the paper sleeve ONLY if replay Δ>0 with CI lower bound >−0.05.** If replay fails, write the negative result and STOP (this gate exists because v32 taught us 2-day tape artifacts are real).

## 3. New paper sleeve — `poly_ladder_btc_15m_v33_leader` (if gate passes)
Same framework/feed/telemetry as 15m v3, quoting rules replaced:
- **Phase 1 (t<300s): unchanged v3 two-sided deep quoting** (pair-capture base).
- **Phase 2 (t≥300s): trailing side — cancel all resting bids, quote NOTHING on it.** Leader = token with higher mid; on leader flip, sides swap (rate-limited: only if mid divergence ≥0.55/0.45 to avoid churn at 50/50; at coin-flip quote NEITHER).
- **Phase 2 leader quoting: maker bids on the LEADING token only, 1–2 ticks below touch, band 0.55–0.90 HARD CAP 0.90** (breakeven headroom; 0.92+ forbidden). Flat clips, window cap unchanged ($12/side total).
- **Asymmetric residual (the key change): residual on LEADING side at price ≥0.55 → HOLD to resolution (disable T−45 backstop + rcg for that side). Residual on TRAILING side → flatten (T−45 backstop + rcg band as today).** Leader-awareness evaluated at flatten time, not entry time.
- Env: `TV_LADDER_V33_PHASE2_T_S=300`, `TV_LADDER_V33_LEADER_BAND=0.55:0.90`, `TV_LADDER_V33_DEPTH_TICKS=1..2`, `TV_LADDER_V33_FLIP_HYST=0.55`.

## 4. Telemetry
Standard `ladder_summary` PLUS: `phase2_leader_fills_sh/vwap`, `leader_flips_n`, `residual_held_leading_sh`, `residual_flattened_trailing_sh`, `backstop_suppressed` (bool). Money floats ≤6 dp (crash rule).

## 5. Pre-registered expectations (frozen — no post-hoc tuning)
1. Replay gate (§2) passes before deploy.
2. Paper: `v33_leader` beats `btc_15m_v3` paired per-window **t≥2 within 7 days** (~670 windows).
3. Decomposition sanity: phase-2 leader fills net-positive; held leading residual WR ≥85%; trailing-flatten cost < held-residual gain.
4. Failure = negative-result report; bands/thresholds stay frozen. Any band change = NEW spec, new pre-registration.

## 6. Reporting
(a) housekeeping confirmations w/ ledger notes, (b) replay-gate result with per-rule attribution (drop-trailing vs add-leader vs hold-residual — which rule carries the delta), (c) if deployed: first-24h snapshot + day-7 paired verdict. Flag deviations BEFORE implementing. Commit/push as you go.
