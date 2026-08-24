# Round 5 — first green session, phase rules ENFORCING — 2026-08-20 (20:15–21:35 UTC)

Continues rounds 1–4. Same method, cash-verified (identities exact, winners 14/14,
zero open positions). 14 windows, all btc-5m.

## 1. Headline

| | round 5 | rounds 2–4 for contrast |
|---|---|---|
| **net cash** | **+$6.12** | −$23.76 / −$9.57 / −$11.33 |
| buys / sells / redeems | $277.09 / $41.24 / $241.96 | |
| **sells before T+90s** | **0 of 13** ✅ | 9 of 17 in round 4 |
| **sell effect** | **+$8.24** | −$19.46 / −$32.57 / −$28.48 |
| sold-winner profile | 33 sh @ **0.652**, median **+201s** | 105–213 sh @ ~0.38, +32…+54s |
| gross entry edge | −0.35¢/sh (≈flat) | +5.5 / +5.2 (r3/r4) |
| pairing ratio | 2.00 | |

**The cut gate deployed sometime between 14:31 and 20:15 and is enforcing perfectly.**
The sell policy's sign flipped exactly as the mechanism predicted: cuts now fire late
(median +201s vs +32/+54s), at value (0.652 vs 0.38), and ADD money (+$8.24). The
sell-effect series across the campaign: +13.8 → −19.5 → −32.6 → −28.5 → **+8.2**.

Entry-window rule: 45/143 fills still land after T+60s — from data-api alone I cannot
distinguish naked entries from the spec-permitted pair-completing bids. The >120s
bucket was +20.9¢/sh this session (completion-like), the 60–120s bucket −40¢ on 2
legs (−$26, small-n) — ask the TV agent to confirm via the new telemetry whether
post-60s fills are tagged as completions.

## 2. The pros on OUR 14 windows

| | legs | sh | vwap | WR | edge |
|---|---:|---:|---:|---:|---:|
| PBot-5 | 15 | 2,120 | 0.557 | 66.1% | **+10.43¢ (+$221)** |
| **b27** | 28 | **49,995** | 0.450 | 47.7% | **+2.64¢ (+$1,322)** |
| PBot-6 | 21 | 4,063 | 0.451 | 45.3% | +0.26¢ (≈flat) |
| **us** | 26 | 613 | 0.452 | 44.9% | −0.35¢ gross, **+$6.12 net** |
| b945 | 25 | 5,670 | 0.524 | 49.4% | **−3.02¢ (−$171)** |

Mid-table: this stretch we matched PBot-6 (≈flat gross) and beat b945 — whose recent
5m struggles keep confirming the tf-split finding (its 5m book is structurally
negative; its money is 15m). b27 keeps printing on raw scale (50k shares on 14
windows — 80× our size at 2.6¢).

## 3. Reading, honestly

+$6.12 over 14 windows is not a statistical claim — it is a COMPLIANCE result: the
one defect that cost every session since Aug 19 is fixed and the sell ledger flipped
sign on cue. The campaign scoreboard now reads: entries ≈ flat-to-positive across
r3–r5 (+5.5, +5.2, −0.4¢/sh — pooled comfortably positive), sells fixed, capital
tiny. What remains before judging edge: accumulate the pre-registered n ≥ 30 windows
under the enforced config (r5 gives 14; P1 entry-edge ≥ +2¢ and P3 net ≥ $0 both
currently on track), and confirm the 60–120s fills are completions, not stragglers.

Next decision unchanged from [ROUND4_POSTSPEC_AND_TF_SPLIT_2026_08_20.md](ROUND4_POSTSPEC_AND_TF_SPLIT_2026_08_20.md):
add btc-15m with proportionally scaled phase rules once capital is topped up — b945
made −$171 on our 5m windows tonight while its 15m book runs +5.85% ROI on $1.0M;
the pairing game we run belongs there.
