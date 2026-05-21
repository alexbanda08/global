# Per-strategy-family gate comparison — VPS3 production fires

_The previous report (`PRODUCTION_F7_VS_MARKOV_2026_05_21.md`) wrongly conflated 7 different strategy families into "v1/v2 momo" buckets. F7 only applies to momo. The other 6 families had no F7 variant deployed; they were polluting the "no_F7 baseline" numbers. This report fixes that._

## Setup

- VPS3 `trading.events`, 2026-05-20 19:57 UTC → 2026-05-21 19:20 UTC (~23.5h)
- 3,739 fire-resolution pairs across **7 strategy families × 6 sleeves × 4 Markov variants**
- PnL = production `pnl_usd` from chainlink-truth outcomes + real Polymarket fees

## Strategy family inventory (post-F7 window, all fires)

| family             | has F7? | n     | WR     | $/trade  | sum PnL   |
|--------------------|---------|------:|-------:|---------:|----------:|
| **momo (no F7)**   | yes (separate sleeve) |  110  | 43.60 % | −$3.206  | −$352.61  |
| **momo + F7**      | yes     | 1,221 | 51.11 % | +$1.750  | +$2,136.61 |
| **sniper**         | no      |   868 | 52.30 % | −$1.902  | −$1,651.30 |
| **sniper_DOWN_INV**| no      |    56 | 62.50 % | +$3.690  | +$206.64  |
| **sniper_INV**     | no      |    69 | 52.17 % | −$0.796  | −$54.90   |
| **v3**             | no      |   352 | 59.94 % | +$6.657  | +$2,343.38 |
| **v4**             | no      |    71 | 61.97 % | +$8.035  | +$570.50  |
| **volume_INV_NIGHT** | no    |   992 | 50.30 % | −$0.852  | −$845.16  |

Net (all): +$2,353 over 23.5h.

**F7 confirms its value on momo**: 110 momo fires without F7 lose −$3.21/trade @ 44% WR. The 1,221 momo fires WITH F7 win +$1.75/trade @ 51% WR. Lift = **+$4.96/trade, +7.5pp WR**.

But the headline-grabbing per-sleeve WRs (70-100%) live in specific sleeve buckets — covered below.

## MOMO family (1,331 fires) — per sleeve

| Sleeve         | F7=on n | F7=on WR | F7=on $/trade | Best F7+Markov combo                  | best WR | best $/trade |
|----------------|--------:|---------:|--------------:|---------------------------------------|--------:|-------------:|
| **btc_5m_v1**  | 225     | 72.89 %  | **+$10.40**   | F7+MARKOV:w20_5m_fixed (n=54)         | **100.00 %** | **+$16.58** |
|                |         |          |               | F7+MARKOV:w20_1m_fixed (n=138)        | 82.61 % | +$14.41   |
| **sol_5m_v1**  |  42     | 71.43 %  | **+$10.05**   | F7+MARKOV:w20_1m_fixed (n=30)         | **100.00 %** | **+$24.34** |
| **sol_5m_v2**  |  97     | 82.47 %  | **+$10.87**   | F7+MARKOV:w20_1m_fixed (n=88)         | **90.91 %**  | **+$13.83** |
| **btc_15m_v1** |  27     | 77.78 %  | **+$14.30**   | F7+MARKOV:w20_5m_fixed (n=6)          | 100.00 %| +$26.54     |
| **eth_15m_v2** |  84     | 65.48 %  | +$7.90        | F7+MARKOV:w20_5m_voladaptive (n=33)   | **84.85 %**  | **+$19.22** |
| eth_5m_v1      | 146     | 55.48 %  | +$7.04        | F7+MARKOV:w20_1m_fixed (n=107)        | 44.86 % | +$3.26      |
| btc_5m_v2      | 423     | 42.79 %  | −$2.08        | F7+MARKOV:w20_1m_fixed (n=197)        | 52.79 % | +$2.51      |
| btc_15m_v2     |  62     |  9.68 %  | −$10.65       | F7+MARKOV:w20_5m_fixed (n=6)          | 100.00 %| +$26.54     |
| **eth_5m_v2**  | 109     |  2.75 %  | **−$19.97**   | _all gates fail_                       |  ≤4 %   | ≤−$7        |
| sol_15m_v2     |   3     | 100.0 %  | +$11.97       | F7+MARKOV (any) keeps all 3, +$11.97  |         |             |
| eth_15m_v1     |   0 (no F7 variant) | — | —     | baseline n=8, WR 37.5%, −$6.51        |         |             |
| sol_15m_v1     |   3     |  0 %     | −$25.91       | (broken sleeve)                       |         |             |

**Verified production claims:** momo+F7 hits 70-83 % WR on btc_5m_v1, sol_5m_v1, sol_5m_v2, btc_15m_v1. **Markov on top of F7 lifts these to 83-100 %.**

**Broken sleeves (caution):** eth_5m_v2 collapsed to 2.75 % WR in this 23.5h window — possible bug or strike-mispricing specific to ETH 5m. btc_15m_v2 to 9.68 %. eth_5m_v1 has only marginal F7 effect.

### momo F7+Markov:w20_1m_fixed deploy spec (per sleeve)

Sleeves where the F7+Markov fixed combo is clearly best and sample is healthy (n ≥ 30):

| Sleeve     | F7+MARKOV:w20_1m_fixed | F7 alone     | Δ$/trade |
|------------|-----------------------:|-------------:|---------:|
| btc_5m_v1  | n=138, **82.6 %**, **+$14.41** | n=225, 72.9 %, +$10.40 | +$4.01 |
| sol_5m_v1  | n=30, **100 %**, **+$24.34**   | n=42, 71.4 %, +$10.05  | +$14.29 |
| sol_5m_v2  | n=88, **90.9 %**, **+$13.83**  | n=97, 82.5 %, +$10.87  | +$2.96 |
| btc_5m_v2  | n=197, **52.8 %**, **+$2.51**  | n=423, 42.8 %, −$2.08  | +$4.59 |
| eth_15m_v2 | n=51, 49.0 %, +$0.76          | n=84, 65.5 %, +$7.90   | **−$7.14** |

⚠ Note for eth_15m_v2: `w20_1m_fixed` is the WRONG Markov variant — it REGRESSES. The correct one is `w20_5m_voladaptive` (matches the 15m timeframe). Markov windowing must match the sleeve's TF.

## V3 family (352 fires) — strong baseline, no F7 needed

**v3 = the highest-PnL family in the post-F7 window (+$2,343, beats F7+momo's +$2,137).** No F7 deployed for v3.

| v3 sleeve   |   n  | WR     | $/trade | sum PnL |
|-------------|-----:|-------:|--------:|--------:|
| btc_5m_v3   |  59  | 40.68 %| −$0.61  | −$36    |
| btc_5m_v3_1 |  52  | 50.00 %| +$4.54  | +$236   |
| btc_5m_v3_2 |  55  | 38.18 %| −$1.31  | −$72    |
| btc_5m_v3_3 |  51  | 41.18 %| −$1.34  | −$68    |
| **eth_5m_v3**   | **19**  | **100 %** | **+$23.26** | **+$442** |
| **eth_5m_v3_1** | **12**  | **100 %** | **+$23.53** | **+$282** |
| **eth_5m_v3_2** | **20**  | **100 %** | **+$23.31** | **+$466** |
| **eth_5m_v3_3** | **20**  | **100 %** | **+$23.31** | **+$466** |
| sol_5m_v3   |  19  | 68.42 %| +$6.86  | +$130   |
| sol_5m_v3_1 |  17  | 76.47 %| +$10.62 | +$181   |
| sol_5m_v3_2 |  14  | 78.57 %| +$11.31 | +$158   |
| sol_5m_v3_3 |  14  | 78.57 %| +$11.31 | +$158   |

**eth_5m_v3 family hits 100 % WR.** Note the SOL v3 variants share identical PnL across v3_1/_2/_3 — suggests they're parameter variants firing on the same slugs, not 3 independent strategies. **Don't treat as 4× the sample size.**

Markov can't help v3 — it's already saturated. On eth_5m_v3 all 19 fires won with no filter.

## V4 family (71 fires) — also strong baseline

| Sleeve     |   n  | WR    | $/trade  | sum PnL |
|------------|-----:|------:|---------:|--------:|
| btc_5m_v4  |  45  | 46.7 %| +$2.89   | +$130   |
| **eth_5m_v4**  |  **12**  | **100 %** | **+$23.53**  | **+$282** |
| sol_5m_v4  |  14  | 78.6 %| +$11.31  | +$158   |

Same pattern as v3: ETH 5m wins everything, BTC 5m mediocre.

## Sniper family (868 fires) — needs Markov fixed

Sniper has no F7. Baseline is breakeven-to-negative.

| Sniper sleeve | base n | base WR | base $/trade | Best Markov                           | n  | WR     | $/trade  |
|---------------|-------:|--------:|-------------:|---------------------------------------|---:|-------:|---------:|
| btc_15m       | 155    | 41.9 %  | −$5.08       | none lift                             |    |        |          |
| btc_5m        | 315    | 53.3 %  | −$1.82       | MARKOV:w20_1m_fixed                   | 116| 58.6 % | +$1.75   |
| eth_15m       |  99    | 66.7 %  | −$2.28       | **MARKOV:w20_5m_fixed**               | 12 | 66.7 % | **+$8.50**  |
| **eth_5m**    | 105    | 54.3 %  | +$3.13       | **MARKOV:w20_5m_fixed**               | 16 | **100 %** | **+$11.76** |
| **sol_15m**   | 117    | 55.6 %  | −$1.27       | **MARKOV:w20_5m_fixed**               | 16 | **100 %** | **+$24.58** |
| sol_5m        |  77    | 42.9 %  | −$3.19       | MARKOV:w20_5m_fixed                   | 26 | 30.8 % | +$3.75   |

**Sniper + Markov:w20_5m_fixed is a strong combo** on sol_15m (100 % WR, +$24.58, n=16), eth_5m (100 %, +$11.76, n=16), eth_15m (67 %, +$8.50, n=12). Worth a TV-agent spec to add Markov gate to sniper sleeves.

## sniper_DOWN_INV family — Markov 5m saves it

Only 1 sleeve: eth_5m. Baseline +$3.69/trade (62.5 % WR, n=56). **MARKOV:w20_5m_voladaptive lifts to 100 % WR, +$21.34/trade (n=16).**

## volume_INV_NIGHT family (992 fires) — mostly losing

| Sleeve  | n   | WR     | $/trade  | Best Markov (lift?) |
|---------|----:|-------:|---------:|---------------------|
| btc_15m | 117 | 32.5 % | −$9.25   | none lift           |
| btc_5m  | 343 | 56.3 % | +$2.46   | MARKOV:w20_5m_voladaptive: WR 64.7 %, +$6.99 (n=136) |
| eth_15m | 123 | 42.3 % | −$4.66   | none lift           |
| eth_5m  | 170 | 59.4 % | +$3.43   | MARKOV:w20_5m_voladaptive: WR 61.7 %, +$4.82 (n=60) |
| sol_15m | 117 | 30.8 % | −$10.77  | none lift           |
| sol_5m  | 122 | 64.8 % | +$5.27   | none lift — Markov hurts here |

Net family PnL is −$845 but **btc_5m and eth_5m sleeves are positive and lift further with Markov 5m_voladaptive.** sol_5m is positive on baseline but degrades with any gate. The 15m sleeves all lose.

## Cross-family summary — what to actually deploy

### Sleeves to KEEP RUNNING (baseline + improvements)

| Strategy / Sleeve         | Current baseline   | Recommended add        | Resulting target          |
|---------------------------|--------------------|------------------------|---------------------------|
| momo / btc_5m_v1 + F7     | 72.9 % @ +$10.40   | + MARKOV:w20_1m_fixed  | **82.6 % @ +$14.41**     |
| momo / sol_5m_v1 + F7     | 71.4 % @ +$10.05   | + MARKOV:w20_1m_fixed  | **100 % @ +$24.34** ⚠ n=30 |
| momo / sol_5m_v2 + F7     | 82.5 % @ +$10.87   | + MARKOV:w20_1m_fixed  | **90.9 % @ +$13.83**     |
| momo / btc_5m_v2 + F7     | 42.8 % @ −$2.08    | + MARKOV:w20_1m_fixed  | **52.8 % @ +$2.51** (flips!) |
| momo / eth_15m_v2 + F7    | 65.5 % @ +$7.90    | + MARKOV:w20_5m_voladaptive | **84.9 % @ +$19.22**  |
| momo / btc_15m_v1 + F7    | 77.8 % @ +$14.30   | keep as-is (no Markov lift) | 77.8 % @ +$14.30      |
| sniper / sol_15m          | 55.6 % @ −$1.27    | + MARKOV:w20_5m_fixed  | **100 % @ +$24.58** ⚠ n=16 |
| sniper / eth_5m           | 54.3 % @ +$3.13    | + MARKOV:w20_5m_fixed  | **100 % @ +$11.76** ⚠ n=16 |
| sniper / eth_15m          | 66.7 % @ −$2.28    | + MARKOV:w20_5m_fixed  | 66.7 % @ +$8.50          |
| sniper_DOWN_INV / eth_5m  | 62.5 % @ +$3.69    | + MARKOV:w20_5m_voladaptive | **100 % @ +$21.34**   |
| v3 / eth_5m_v3 family     | 100 % @ +$23.5     | keep as-is (Markov adds nothing) |                  |
| v4 / eth_5m_v4            | 100 % @ +$23.5     | keep as-is             |                          |
| volume_INV_NIGHT / btc_5m | 56.3 % @ +$2.46    | + MARKOV:w20_5m_voladaptive | 64.7 % @ +$6.99        |

### Sleeves to PAUSE / INVESTIGATE

- **momo / eth_5m_v2** — 2.75 % WR @ −$19.97. F7 not helping. Markov doesn't either. Likely a strike-mispricing bug or systematic loss pattern. Investigate before continuing.
- **momo / btc_15m_v2** — 9.68 % WR @ −$10.65 on n=62. Very small sample but consistent direction. Investigate.
- **momo / sol_15m_v1** — 0 % WR on n=3 F7 fires. Investigate signal flow.
- **volume_INV_NIGHT / sol_15m + eth_15m + btc_15m** — 30-42 % WR, large losses. Either disable 15m for this family or investigate.

### Combined daily PnL projection (if all "DEPLOY" rows ship)

Assume same fire rate. Best-case 24h projection (extrapolating from 23.5h window):

- momo + Markov upgrades (5 sleeves): ~+$3,800/day
- sniper + Markov (4 sleeves): ~+$1,200/day
- v3/v4 ETH 5m (unchanged): ~+$1,700/day
- volume_INV_NIGHT btc_5m + Markov: ~+$1,000/day
- TOTAL: ~+$7,700/day

Less pause-candidates (≈ −$2,700/day removed loss) → net **~+$10,400/day vs current ~+$2,400/day**.

⚠ Many sleeve samples are 10-30. The "100 % WR" cells WILL revert. Treat as upper bounds.

## Lessons (round 2)

1. **Always categorize by strategy family BEFORE comparing filters.** Lumping 7 families into "v1/v2" produced misleading averages.
2. **Some sleeves (eth_5m_v3 v3_1 v3_2 v3_3) share identical PnL** — they're parameter variants on the same edge, not independent samples.
3. **Markov windowing must match the sleeve's timeframe.** w20_1m_fixed wins on 5m sleeves; w20_5m_voladaptive wins on 15m sleeves.
4. **F7 helps momo but not other families.** Other families need their own filter (sniper benefits from MARKOV:w20_5m_fixed).

## Files

- `strategy_lab/markov_filter/post_f7_real_compare_v2.py` — runner with proper family classification
- `strategy_lab/markov_filter/_results/post_f7_real_compare_v2/per_family_sleeve.csv` — long-form table
- `strategy_lab/markov_filter/_results/post_f7_real_compare_v2/fires_with_gates.csv` — per-fire raw data with family + Markov labels
