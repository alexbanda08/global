# Round 6 — cut-gate holds, late naked entries are the remaining bleed — 2026-08-21 (00:55–01:55 UTC)

Continues rounds 1–5. Same cash-verified method: winners 11/11, identities exact; one
dust position open (15 sh @ $0.07 — immaterial, noted). 11 windows, all btc-5m,
**biggest deployment rate yet ($375 of buys in one hour).**

## 1. The session

| | round 6 | round 5 (for contrast) |
|---|---|---|
| net cash | **−$18.69** | +$6.12 |
| buys / sells / redeems | $375.01 / $40.45 / $315.86 | $277.09 / $41.24 / $241.96 |
| **sells before T+90s** | **0 of 12** ✅ | 0 of 13 ✅ |
| **sell effect** | **+$35.45** ✅ | +$8.24 |
| gross entry edge | **−6.38¢/sh (−$54.1)** | −0.35¢ |
| pairing ratio | 1.55 | 2.00 |

**Change A (cut gate) is a solved problem** — two consecutive sessions fully
compliant, sell effect +$8.24 then +$35.45 (tonight the late cuts saved $35 by
correctly dumping losers after T+90). The sell-effect series across the campaign:
+13.8 → −19.5 → −32.6 → −28.5 → +8.2 → **+35.5**.

## 2. Where the loss is — Change B is not enforced, and round 5 masked it

Timing decomposition of tonight's entries:

| fill timing | legs | sh | vwap | WR | edge | $ |
|---|---:|---:|---:|---:|---:|---:|
| 0–60s | 10 | 355 | 0.425 | 52.1% | **+9.66¢** | **+$34.3** |
| 60–120s | 6 | 306 | 0.505 | 44.4% | −6.03¢ | −$18.4 |
| **>120s** | **3** | **187** | **0.374** | **0.0%** | **−37.36¢** | **−$70.0** |

Round 5's post-120s fills won (+20.9¢, n=3) and I flagged them as "completion-like —
confirm via telemetry". Round 6 answers it: **187 naked shares filled after T+120 at
0.374 with a 0% win rate.** These are not sum-gated pair completions; they are the
same collapsing-side accumulation documented since round 1. The naked >120s bucket
is now negative in 5 of 6 rounds (−28, −48, −55, +21ᵣ₅, −37 ¢/sh). Counterfactual:
without tonight's >120s naked fills the session is ≈ **+$51**.

First-minute entries stay good: +9.66¢/sh tonight; the 0–60s bucket is positive in
5 of 6 rounds. The engine's profitable core is unchanged.

## 3. The pros on OUR 11 windows (volatile hour for everyone)

| | sh | vwap | WR | edge |
|---|---:|---:|---:|---:|
| **b27** | 31,220 | 0.465 | 51.5% | **+5.09¢ (+$1,588)** |
| PBot-6 | 2,062 | 0.466 | 49.9% | +3.31¢ (+$68) |
| **us** | 848 | 0.442 | 37.8% | −6.38¢ gross / −$18.69 net |
| PBot-5 | 5,414 | 0.659 | 58.5% | −7.45¢ (−$404) |
| b945 | 3,565 | 0.416 | 29.3% | **−12.34¢ (−$440)** |

b27 is now positive on our windows in EVERY round measured (+2.24, −1.33, +0.50,
+2.64, +5.09) — the one consistently green benchmark at 5m. b945 keeps bleeding on
5m (−$440 tonight), reinforcing the tf-split conclusion.

## 4. Action for the TV agent (one item)

**Implement/enforce Change B from
[TV_AGENT_SPEC_LIVE_LADDER_PHASE_RULES_2026_08_20.md](TV_AGENT_SPEC_LIVE_LADDER_PHASE_RULES_2026_08_20.md):**
after `T_open + 60s`, cancel entry bids; a resting buy may only exist if its fill
REDUCES |up−dn| imbalance AND passes `pair_max_sum`. Tonight's three >120s legs
(187 sh, all on the heavy/collapsing side) would have been blocked by the imbalance
test alone. Add the fill tag (`entry` vs `completion`) to the telemetry so the next
audit doesn't have to infer it — that ambiguity is what let round 5 mask this.

Campaign scoreboard after 6 rounds: entries 0–60s solidly positive, cut-gate fixed
and paying, ONE known defect remaining (late naked entries), 15m expansion still
queued behind capital top-up.
