# TV RUST AGENT SPEC — Ladder v3.1 PAPER VARIANTS (coinflip-residual gate · depth bracket · 2× clips)
**2026-07-13 · TVRUST (Rust) ONLY · Ireland · ALL PAPER · Python frozen · no storedata dependency.**

## 0. Ground rules (read first)
- **`poly_ladder_btc_5m_v3` (and the other v3/v4 sleeves) stay BYTE-FROZEN** — they are the go-live baseline mid-gate. Variants are NEW parallel paper sleeves; the only permitted effect on the baseline is the engine restart that spawns them.
- **Sequencing:** the live-path punch list (parse-fix + honest drill, ladder live branch, dashboard) stays PRIORITY 1. These variants ride along in the **next engine deploy** you were doing anyway for the Phase-A/B engine work — do not do a dedicated restart just for them.
- **All variants MUST share the SAME racer/book state as the base btc-5m sleeve** (same mirror, different quoting sims — paper sleeves don't interfere). A variant on its own connection would confound the A/B with feed quality (the d4 lesson from 2026-07-02).
- Evidence base: `SHADOW_IMPROVE_B945_ALIGNMENT_2026_07_13.md` (the three levers, sized on 2,497 traded windows) + b945 fresh decode (the source wallet moved to −1-tick depth + bigger clips while printing $524/day — the regime rewards aggression).

## 1. VARIANT A — residual coinflip gate (`poly_ladder_btc_5m_v31_rcg`) — the biggest lever (~+$25/day, ~11%)
Finding: residual legs whose entry vwap lands in **(0.30, 0.60) systematically lose** (−0.279 and −0.220/win, n=1,113 windows) while both tails are positive (+0.198 below 0.30, +0.184 above 0.60). Mid-band residual = coin-flip inventory with no mispricing to harvest.
- Behavior: identical to v3 EXCEPT — when a residual exists and `residual_entry_vwap ∈ (RCG_LO, RCG_HI)`, **flatten it IMMEDIATELY** (taker marketable-limit, partial-tolerant, same mechanics as the T−45s backstop — just fired early). Outside the band: unchanged (standard T−45s backstop).
- Trigger evaluation: on each tick where a residual exists (recheck as fills accrue — the residual vwap moves); once flattened, normal re-quoting continues (a NEW residual re-evaluates fresh).
- Env: `TV_LADDER_RCG_ENABLED`, `TV_LADDER_RCG_LO=0.30`, `TV_LADDER_RCG_HI=0.60`.
- Telemetry (added to `ladder_summary`): `rcg_flattened_sh`, `rcg_flatten_cost_usd`, and **`residual_pnl_virtual_hold_usd`** (what the flattened shares would have made under the v3 policy — held to T−45s/backstop/resolution) so we can attribute the gate's value exactly per window.
- **ETH twin (cheap, same code): `poly_ladder_eth_5m_v31_rcg`** with `RCG_LO=0.30, RCG_HI=0.45` (ETH's negative band is narrower — only 0.3–0.45 loses; 0.45–0.6 is ETH's BEST bucket, do not gate it).

## 2. VARIANT B — depth bracket (`poly_ladder_btc_5m_v31_d1` + enable the existing d4)
We only measure depth-2. b945 (the source wallet) has moved his maker depth from −3 to **−1 tick** while accelerating to his best-ever P&L.
- `v31_d1`: identical to v3 with `quote_depth_ticks=1`.
- **Flip `TV_LADDER_D4_ENABLED`** (the depth-4 variant you built 2026-07-02) — per the standing note: it must share the base sleeve's book feed; if your build gave it its own conn, re-wire or confirm `feed_quality.book_age` parity before we trust the comparison.
- Result: a 3-point depth curve (d1/d2/d4) on identical windows. Expected trade-offs: d1 = more fills + more adverse selection; d4 = fewer, purer fills. The matched-window diffs decide.

## 3. VARIANT C — 2× clips (`poly_ladder_btc_5m_v31_c2`)
Findings: corr(fill $, net) = +0.41; we capture only 0.22% of ~8,800 sh/window sell flow; both source wallets run bigger clips (b945 med $12.80, ce25 12 clips/slug).
- Identical to v3 with all rung/clip sizes ×2 (double the per-side budget accordingly; pvs gate and backstop unchanged).
- Watch item (telemetry already exists): tail exposure — crash windows will fill 2× ($160+ per-window paper inventory). Fine on paper; this variant informs LIVE sizing later, it is not itself a live candidate.

## 4. Explicitly NOT in scope
❌ pvs-gate loosening (0.99→0.995) — weak lever, skip. ❌ hour-23 avoid — too small. ❌ Any change to v3/v4 base sleeves. ❌ Any live flag. ❌ 15m variants (5m is the proving ground; 15m follows if a lever validates).

## 5. Telemetry / load notes
- Every variant echoes its config in `ladder_summary` (`quote_depth_ticks`, `rcg_lo/hi`, `clip_multiplier`) — the analysis keys on these.
- 4 new 5m sleeves ≈ +2× `ladder_tick` volume. Acceptable (DB is small), but if you want to economize: emit variant `ladder_tick` at 1/4 cadence — `ladder_summary` (the analysis unit) must stay full-fidelity.

## 6. Acceptance
1. Sleeves emitting: `btc_5m_v31_rcg`, `btc_5m_v31_d1`, `btc_5m_v31_c2`, the d4 sleeve, `eth_5m_v31_rcg` — all with config echoes, all sharing the base book feed (book_age parity vs base within noise).
2. Base v3/v4 sleeves: zero config change (diff of their `ladder_summary` field-set before/after deploy = identical + continuous emission through the restart gap only).
3. rcg rows show `rcg_flattened_sh>0` with `residual_pnl_virtual_hold_usd` populated on gated windows.
4. ~1 week accrual → research side computes **matched-window paired diffs** (variant − base, same slugs) per variant — the decision metric (much more powerful than independent CIs).

## 7. PRE-REGISTERED EXPECTATIONS (counterfactual on the existing 11.5d tape — added 2026-07-13 late)
Computed by simulating the rcg gate on the realized v3 windows (`analyze_extras_0713.py`):
- **btc rcg:** uplift **+0.097/win CI[+0.006,+0.187] ≈ +$21/day** if the early flatten costs ~0.5 ticks; +$17/day at 1 tick; +$10/day at 2 ticks. **Judge the variant against this curve** — if its realized flatten cost exceeds ~2 ticks, the gate is not worth it.
- **eth rcg twin: DOWNGRADED TO OPTIONAL** — counterfactual only +$1.3/day at best, CI spans 0. Ship it only if it's zero marginal effort; don't debug anything for it.
- **v4_coc context:** matched-slug paired test at full n (282 shared slugs): v4−v3 diff **+0.058 CI[−0.39,+0.50], median $0.00** — COC adds nothing on identical windows; its standalone edge is window-mix. **No COC variant for 5m; v4_coc is a kill-candidate at the 2-week mark** (frees box load).

## Provenance
Lever evidence: `SHADOW_IMPROVE_B945_ALIGNMENT_2026_07_13.md`. b945 aggression shift: `B945_REDECODE_2026_07_13.md` (per-slug PnL therein NOT reliable — row-cap truncation; the depth/clip signature IS). Base semantics: `TV_AGENT_SPEC_LADDER_V3_DEEPQUOTES_5M_2026_07_02.md`. Coinflip-gate pattern precedent: `TV_AGENT_SPEC_CLOUDVWAP_V7_COINFLIP_FILTER_2026_06_09.md`.
