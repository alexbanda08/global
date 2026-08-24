# Round 4 (post-"spec" session) + 5m-vs-15m split of the pro wallets — 2026-08-20

Continues rounds 1–3 ([R1](OURS_VS_WALLETS_SAME_WINDOW_2026_08_18.md), [R2+R3](OURS_VS_WALLETS_ROUND2_2026_08_20.md)).
Round 4 = the 5 windows 14:10–14:30 UTC today. All cash-verified as before
(identities exact, winners 5/5, settle complete).

---

## 1. Round 4: the spec was NOT in effect — and it cost the session, again

| | value |
|---|---|
| windows | 5 (btc-5m, 14:10–14:30 UTC) |
| cash | buys $142.85 · sells $76.51 · redeems $55.01 · **net −$11.33** |
| **gross entry edge** | **+5.20¢/sh (+$17.1)** — second session running above +5¢ |
| pairing ratio | 1.15 |
| **sell effect** | **−$28.48** (105 winning shares sold) |
| **sells before T+90s** | **9 of 17 — at +4s, +10s, +12s, +12s, +13s, +13s, +27s, +28s, +52s** |
| buy fills after T+60s | 28 of 72 (entry-window rule also not in force) |

Box facts: `tv-engine` was rebuilt and restarted at **13:59:54 UTC** — 10 minutes
BEFORE this session — yet the cuts fired at +4s and the spec's env knobs
(`TV_LADDER_CUT_MIN_AGE_S`, `TV_LADDER_ENTRY_WINDOW_S`) do not exist in
`/etc/tv/tvrust.env`. Whatever the 13:59 deploy contained, **the phase rules from
[TV_AGENT_SPEC_LIVE_LADDER_PHASE_RULES_2026_08_20.md](TV_AGENT_SPEC_LIVE_LADDER_PHASE_RULES_2026_08_20.md)
are not enforcing.** That is now the third consecutive session where the early cut
is the whole loss: sell-effect −$19.46 → −$32.57 → −$28.48 (cumulative −$80.51 vs
entries that made +$36 gross over the same three sessions).

## 2. Are we close to the pros? — On these windows we BEAT them (gross)

The 14:10–14:30 stretch was brutal for everyone:

| on OUR round-4 windows | sh | vwap | WR | edge |
|---|---:|---:|---:|---:|
| **us (gross entries)** | 330 | 0.433 | 48.5% | **+5.20¢/sh** |
| b27 | 10,260 | 0.503 | 50.8% | +0.50¢ |
| b945 | 1,747 | 0.538 | 51.4% | −2.36¢ |
| PBot-5 | 705 | 0.497 | 24.4% | −25.32¢ (−$178) |
| PBot-6 | 2,328 | 0.473 | 12.0% | **−35.34¢ (−$823)** |

Two sessions running our entry engine is competitive with the best table in this
market (+5.54¢, +5.20¢). The professionals' collapse here also calibrates
expectations: window-level variance is enormous — PBot-6's long-run +5.5¢ coexists
with −35¢ stretches. Judge everything share-weighted over ≥30 windows.

## 3. The 5m vs 15m split of every wallet (cash method, MERGE proceeds included)

| wallet | tf | windows | %win | buy USD | **%capital** | net | **ROI** | net/window |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **b945** (19.7d) | 5m | 1,811 | 63% | $151,914 | 12.8% | −$1,991 | **−1.31%** | −$1.10 |
| | **15m** | 1,058 | 37% | **$1,039,401** | **87.2%** | **+$60,813** | **+5.85%** | **+$57.48** |
| b27 (2.0d)¹ | 5m | 532 | 100% | $295,191 | 100% | +$85,853 | +29.08%¹ | +$161.38 |
| PBot-2 (19.3d) | 5m | 4,857 | 77% | $407,438 | 77.8% | +$18,978 | +4.66% | +$3.91 |
| | 15m | 1,489 | 23% | $116,322 | 22.2% | +$7,207 | **+6.20%** | +$4.84 |
| PBot-3 (40.5d) | 5m | 9,141 | 78% | $414,719 | 82.6% | +$28,463 | +6.86% | +$3.11 |
| | 15m | 2,615 | 22% | $87,606 | 17.4% | +$5,641 | +6.44% | +$2.16 |
| PBot-5 (73.9d) | 5m | 8,259 | 100% | $354,427 | 100% | +$10,745 | +3.03% | +$1.30 |
| PBot-6 (43.3d) | 5m | 10,458 | 70% | $868,655 | 71.7% | +$115,001 | +13.24% | +$11.00 |
| | 15m | 4,446 | 30% | $343,272 | 28.3% | +$43,282 | +12.61% | +$9.74 |

¹ b27's sample is 2 days at the fetch cap; windows at the old edge may have partial
buys against full proceeds — treat 29% as an upper estimate. Directionally consistent
with its +$690k lifetime and this week's 60k-trades/14h velocity.

**Read of the table:**
- **The biggest allocator puts 87% of its capital in 15m** (b945) — and its 5m book
  is outright NEGATIVE. The in-window PAIRING game (our design) is only demonstrated
  profitable at scale on 15m.
- The wallets that win on 5m do it with mechanics we don't run: pre-open collection
  (PBot-6), velocity + instant merge recycling (b27), late one-sided fading (PBot-5).
- Where a wallet runs both tfs, 15m ROI ≥ 5m in 2 of 3 cases (b945 hugely, PBot-2
  moderately; PBot-3/PBot-6 ≈ equal).
- 15m ALSO fits our constraints better: 96 windows/day (vs 288) at 3× the window
  length = 3× more time to complete pairs (our pairing already works: 1.15–2.69),
  fewer capital rotations against the ~47s redemption float, and our own
  `btc_15m_v3` paper arm has been consistently positive (+0.40–0.47/w).

## 4. What to do (priority order)

1. **Nothing new until the phase rules actually enforce.** Round 4 is a deployment
   failure, not a strategy finding: the +4s cuts are measured violations. The TV
   agent must (a) confirm what the 13:59 build contained, (b) implement Changes A/B
   from the phase-rules spec with their env knobs, (c) prove compliance with the new
   telemetry (`window_elapsed_s` on every cut) before the next armed session. The
   entry engine is fine — two sessions >+5¢/share — every dollar since Aug 19 was
   lost to this one un-deployed rule.
2. **Yes to 15m — as an ADDITION, phase rules scaled proportionally.** Same live
   sleeve machinery on `btc-updown-15m`: entry window `[open, T+180s]` (same 20% of
   window as 5m's 60s), no residual cut before `T+270s` (30%, mirroring 5m's 90s),
   same pair gate, backstop unchanged at T−45s. Caps: it needs the capital top-up
   first (≥$300; b945 runs $982/window — we'd run $10–20/side) because 15m holds
   inventory 3× longer. Pre-register the readout: n ≥ 30 traded 15m windows, entry
   edge ≥ +2¢/sh, net ≥ $0 sanity gate — judged against `btc_15m_v3`'s paper twin
   running beside it.
3. **Keep 5m running** with the enforced rules — our gross entries there are now
   table-competitive, and the round-4 stress test (pros −25/−35¢, us +5.2¢) suggests
   the Aug-20 config's short-window discipline is genuinely good.
4. v6_preopen unchanged (PBot-6's engine: 13.2% ROI on 5m at $869k deployed — still
   the biggest prize on this table, and still not our game today).

## 5. Verification & caveats

Cash identities exact for round 4 and every tf-split row (buys−sells−redeems−merges);
winners 5/5; b27's ROI flagged as upper-bound (edge effect); coverage spans differ
per wallet (2–74 days) — %s are within-wallet, not comparable across wallets without
noting the span; round-4 pro numbers are 5-window snapshots (variance, not verdicts).
