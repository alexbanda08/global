# Round 2 — our NEW live windows (Aug 20) vs the reference wallets — 2026-08-20

Method identical to [OURS_VS_WALLETS_SAME_WINDOW_2026_08_18.md](OURS_VS_WALLETS_SAME_WINDOW_2026_08_18.md)
(round 1, 51 windows through Aug 18 14:27). This round: the 13 NEW windows since —
one overnight session, **Aug 20 ~00:20–02:20 UTC, all btc-5m**. Fresh data-api pulls
for us + all 6 reference wallets (tag `_2026_08_20`).
Scripts: `_refresh_all_2026_08_20.py`, `_ours_vs_wallets_round2_2026_08_20.py`.

## 0. Verification

Cash identity exact (net −$23.76 two ways) · winners 13/13 · sell-effect −$19.46
reproduced by independent decomposition (sold-winners −$83.9 + sold-losers +$68.1 −
rounding ✓) · unredeemed winning shares 0.00 · one window (`…1787228700`, 55/55 sh
both sides) is IN FLIGHT right now — excluded. Caveat: 13 windows / 24 legs / one
session — this round is an out-of-sample CHECK of round-1's findings, not a new
estimate.

## 1. The session

| | value |
|---|---|
| windows | 13 (5m) |
| buys / sells / redeems | $199.29 / $115.54 / $59.99 |
| **net** | **−$23.76** |
| gross entry edge | **−0.79¢/share** (543 sh, vwap 0.367, WR 35.9%) → −$4.30 |
| **sell-policy effect** | **−$19.46** |
| pairing ratio | **0.32** (round 1: 1.0–2.3 — config regressed) |

## 2. Round-1 findings: which survived out-of-sample?

**① The timing split — CONFIRMED, stronger:**

| fill timing | round 1 (51 w) | **round 2 (13 w)** |
|---|---:|---:|
| 0–60s | +4.25¢/sh | **+20.35¢/sh (+$60.0)** |
| 60–120s | +0.37¢ (60–180s) | **−22.95¢ (−$50.0)** |
| 120–180s | " | **−47.79¢ (−$14.3)** |
| >180s | −28.37¢ | (no fills — quotes died earlier) |

Two independent samples now agree: **everything we buy in the first minute makes
money; everything our resting quotes catch after it is adverse selection.** The
negative zone starts at +60s, not +180s.

**② "We pay less and still lose" — CONFIRMED:** same-side same-window we paid
−3.5¢ vs b945, −3.7¢ vs b27, −5.2¢ vs PBot-5, −4.6¢ vs PBot-6 … and every one of
them was positive on OUR windows while we were not:

| wallet on OUR 13 windows | legs | sh | vwap | WR | edge |
|---|---:|---:|---:|---:|---:|
| **PBot-6** | 14 | 5,858 | 0.454 | **69.5%** | **+24.03¢/sh (+$1,408)** |
| PBot-5 | 17 | 1,350 | 0.464 | 50.9% | +4.51¢ |
| b945 | 26 | 3,825 | 0.499 | 54.3% | +4.42¢ |
| b27 | 26 | 30,135 | 0.481 | 50.4% | +2.24¢ |
| **us** | 24 | 543 | 0.367 | 35.9% | **−0.79¢** |

**③ "Keep the sell policy (+$13.82)" — REVERSED this session (−$19.46).** The
decomposition names the mechanism precisely: we sold **135 shares of sides that went
on to WIN, at avg 0.379, median offset +32s** — the 30s age-cut fires into the first
intra-window dip, which mean-reverts — while the cuts that happened at +91s median
(losers, 230 sh @ 0.296) correctly saved money. Combined across rounds the recycle is
now **−$5.64 net over 64 windows**: not reliably additive; its sign depends entirely
on WHEN it fires. Early cuts realize the bottom; later cuts are protective.

## 3. Fleet intelligence (new, material)

- **PBot-2 and PBot-3 went SILENT at Aug 18 03:16–03:31** — zero trades since
  (cursor-verified through Aug 20 12:15). These were the two with the weakest recent
  edges. The fleet prunes.
- **b945 velocity ~4×'d**: 62,282 trades Aug 18–20 (~26k/day vs ~6k before).
  **b27: 60,813 trades in 14 HOURS.** The family is scaling hard into these books.
- PBot-6 unchanged (~7k/day) and printing (+24¢/sh on our windows this round).

## 4. Recommendations (supersedes round-1 §5 where noted)

1. **Quote window shrinks to [open, T+60s]** for entry bids (was: kill at T+120s).
   Both samples say the resting quote's edge dies after the first minute; after +60s
   only pair-completions under a sum gate should touch the book.
2. **The 30s age-cut must become phase-aware** (supersedes "keep selling as is"):
   never cut before T+90s (our own two-round data: cuts ≤60s destroyed $84, cuts
   ~90s+ saved $68). This is exactly `v5_latepair`'s boundary — the live recycle
   should adopt it.
3. **Pairing regression**: this session ran at ratio 0.32 (vs 1.0–2.3 in round 1).
   Whatever config changed for the overnight run, it dropped the one thing that was
   working. Diff the env backups before the next session.
4. **v6_preopen priority unchanged and reinforced** — the pre-open collector printed
   +24¢/share on our own windows while our in-window quotes did −0.79¢.
5. Capital/scale note: b27 did 30,135 sh on our 13 windows; we did 543. At our size,
   session-to-session PnL (−$24, −$20) is dominated by 2–3 windows — keep judging on
   edge-per-share, not dollars.

## 4b. ROUND 3 ADDENDUM (same day, 12:25–12:50 UTC session — 5 windows)

Fresh top-up (`_refresh_topup_2026_08_20b.py`); all settled, winners 5/5, zero open
positions. Cash: buys $181.99, sells $45.40, redeems $127.01, **net −$9.57**.

| | round 3 value | vs previous rounds |
|---|---|---|
| **gross entry edge** | **+5.54¢/sh (+$23.0)** — best session ever | r1 −1.86¢ · r2 −0.79¢ |
| pairing ratio | **2.69** — recovered | r2 was 0.32 |
| **sell-policy effect** | **−$32.57** | r1 +13.82 · r2 −19.46 |
| sold-winners | 78 sh @ 0.391, median offset **+54s** | same mechanism as r2 |
| timing | 0–60s −26.1¢ (n=3, 45sh) · 60–120s **+17.2¢ (330sh)** · >120s −54.8¢ (n=1) | small-n; see below |

Wallets on these 5 windows: b945 **+14.95¢** (2,043 sh), PBot-6 +21.64¢, PBot-5
+6.52¢, **b27 −1.33¢ on 10,673 sh** (even the pros lose sessions).

**What round 3 changes:**
1. **The entries are fixed.** +5.54¢/share gross with pairing at 2.69 — whatever the
   operator changed between the overnight and midday sessions, it worked: our entry
   edge was competitive with PBot-5's on the same windows for the first time.
2. **The sell policy is now the single dominant loss, two sessions running** (−$19.46,
   −$32.57; cumulative across all rounds **−$38.21**). Both times the same mechanism:
   early cuts (median +32s / +54s) selling recovering winners at ~0.38–0.39. Gross
   entries today made +$18.7 combined; the sells turned today into −$33.33.
3. Timing granularity: individual buckets are small-n and noisy per session, but the
   LAST bucket (>120–180s) is negative in **3 of 3 rounds** (−28¢, −48¢, −55¢) — that
   part is settled evidence.

**CORRECTION (operator challenge, upheld):** the "−$52/day" phrasing conflated two
things and two sessions. Realized CASH across rounds 2+3 is **−$33.33** (r2 −$23.76 +
r3 −$9.57), and round 2's windows are Aug-19 EVENING in the operator's local time
(UTC−3), not "today". The −$52.03 is the counterfactual SELL-EFFECT (hold-all would
have returned +$18.71 gross; sells turned it into −$33.33 cash). Operator's own
figures ("~$10 today, ~$33 since the Aug-18 drills") reconcile exactly.

**Immediate action (upgraded from recommendation to defect): suspend the early
residual cut on the live sleeve.** No cut before T+90s under any condition; ideally
disarm the recycle entirely until it is phase-aware. Two consecutive live sessions,
one identified mechanism, a sell-effect of −$52 counterfactual (−$33.33 cash) on
~$380 of buys — with entries now positive, the early cut is the only thing between
the current config and its first green session.

## 5. Confidence

Cash identities exact; every headline number reproduced two ways; winners fully
resolved. The round-2 sample is ONE session (13 windows) — its role is confirmation/
refutation of round-1 hypotheses, and it did both: timing split confirmed (the one
structural finding, now 2-for-2), sell-policy value refuted-as-unstable (n=2 sessions,
opposite signs, mechanism identified). PBot-6's +24¢ this round is a hot small sample
(n=14 legs) — its long-run number remains +5.5¢ pre-open (14,904-window decode).
