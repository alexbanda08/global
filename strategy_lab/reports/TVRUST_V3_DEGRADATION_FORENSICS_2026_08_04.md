# `poly_ladder_btc_5m_v3` — full history + "degradation" forensics — 2026-08-04

Source: Ireland `tradingvenue_rust`, `trading.events` `kind='ladder_summary'`,
deduped `distinct on (slug)` last-summary-per-window. Life: **2026-07-02 → 2026-08-04 (34 days)**.

## VERDICT

**v3 is not degrading.** Three independent tests all fail to reject "flat", and the
**arb core is at a lifetime high**. What moved is the *residual* leg — a
structurally negative-EV coin flip that got lucky in week 1 and has since converged
to its true mean. That is regression, not decay, and it will not come back.

| test | result | significant? |
|---|---|---|
| Daily net OLS, 31 clean days | slope −$2.25 /day/day, **t = −1.71** | **no** (p≈0.10) |
| Paired (arb) leg, wk1 vs rest | 1.0028 → 1.0603, **t = −0.56** | **no** — it went UP |
| Residual leg, wk1 vs rest | +0.0021 → −0.1899, **t = 1.76** | **no** (p≈0.08) |
| Residual hit rate 41.1% → 38.9% | 0.84 sd at n≈1,500 | **no** |
| Paired vwap sum (`pvs`) by week | 0.820, 0.820, 0.818, 0.821, 0.826, 0.812 | **flat — zero spread compression** |

---

## 1. Lifetime scoreboard

| metric | value |
|---|---:|
| windows seen | **9,635** |
| windows traded (`maker_sh>0`) | **7,164** (74.4%) |
| windows no-fill | 2,471 (25.6%) |
| **profitable windows** | **4,226** |
| losing windows | 2,938 |
| **win rate** | **59.0%** |
| **cumulative net** | **+$6,624.20** |
| gross win / gross loss | +$12,777.3 / −$6,153.1 |
| **profit factor** | **2.08** |
| avg win / avg loss | +$3.023 / −$2.094 (payoff 1.44) |
| $/traded window | $0.9247 |
| best / worst window | +$146.13 / −$19.08 |
| **profitable days** | **34 of 34** |
| **max daily-equity drawdown** | **$0.00** |

**Outlier robustness** — the edge is not carried by a few windows:

| | n | total | mean |
|---|---:|---:|---:|
| all | 7,164 | $6,624.2 | 0.9247 |
| ex-top-1 | 7,163 | $6,478.1 | 0.9044 |
| ex-top-5 | 7,159 | $6,256.4 | 0.8739 |
| ex-top-25 | 7,139 | $5,605.0 | 0.7851 |
| ex-top-1% (72) | 7,092 | $4,766.9 | 0.6722 |

---

## 2. Equity curve — monotonic, zero drawdown

```
Jul02   99.4 | cum   99.4      Jul19  169.2 | cum 3776.2
Jul03  375.4 | cum  474.9      Jul20   80.0 | cum 3856.2
Jul04  190.4 | cum  665.3      Jul21  182.3 | cum 4038.5
Jul05  266.1 | cum  931.4      Jul22  205.3 | cum 4243.9
Jul06  138.2 | cum 1069.6      Jul23   87.3 | cum 4331.1
Jul07  153.7 | cum 1223.3      Jul24  278.3 | cum 4609.5
Jul08  187.5 | cum 1410.7      Jul25  195.4 | cum 4804.9
Jul09  235.1 | cum 1645.8      Jul26   90.1 | cum 4895.0
Jul10  300.3 | cum 1946.1      Jul27  251.4 | cum 5146.4
Jul11  273.9 | cum 2220.0      Jul28  176.1 | cum 5322.5
Jul12  250.1 | cum 2470.2      Jul29  207.7 | cum 5530.2
Jul13  283.2 | cum 2753.4      Jul30  119.1 | cum 5649.3
Jul14  229.5 | cum 2982.9      Jul31  190.4 | cum 5839.7
Jul15   49.7 | cum 3032.5  ← engine outage (only 17 traded windows)
Jul16  179.2 | cum 3211.7      Aug01  133.6 | cum 5973.2
Jul17  217.3 | cum 3429.0      Aug02  284.6 | cum 6257.8
Jul18  178.0 | cum 3607.0      Aug03  214.6 | cum 6472.5
                               Aug04  151.7 | cum 6624.2 (partial day)
```

Rolling-7d average: peaked **251.4** (Jul 14) → troughed **150.8** (Jul 21) →
**186.0 today, and rising** since Jul 26 (159.8 → 186.0). The curve you're reading
as "degradation" is the Jul 19–26 soft patch, which has already recovered half-way.

---

## 3. Where the softness actually is — the two-leg decomposition

Every window has two legs. `paired_pnl_locked_usd` = the arb (bought both tokens
at vwap sum < 1, locked). `residual_pnl_usd` = the unpaired inventory held to
chainlink settle.

| week of | traded | net/win | **paired leg** | **residual leg** | rebate | backstop | `pvs` | maker_sh | paired_sh | resid_sh |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Jun 29 | 718 | 1.297 | **1.176** | **+0.092** | 0.030 | −0.172 | 0.8202 | 19.7 | 5.63 | 8.46 |
| Jul 06 | 1,563 | 0.984 | **0.998** | **−0.041** | 0.027 | −0.143 | 0.8197 | 18.1 | 5.10 | 7.89 |
| Jul 13 | 1,349 | 0.968 | **1.105** | **−0.167** | 0.030 | −0.055 | 0.8183 | 20.2 | 5.93 | 8.30 |
| Jul 20 | 1,585 | 0.706 | **0.983** | **−0.305** | 0.028 | +0.044 | 0.8210 | 18.6 | 5.23 | 8.14 |
| Jul 27 | 1,521 | 0.896 | **1.027** | **−0.160** | 0.028 | −0.045 | 0.8258 | 18.9 | 5.64 | 7.64 |
| Aug 03 | 428 | 0.856 | **1.174** | **−0.349** | 0.030 | +0.044 | 0.8124 | 20.1 | 6.06 | 8.02 |

Read the two bold columns:

- **Paired leg: 1.176 → 1.174.** Dead flat, and the last week is the *second-best
  week of its life*. The arb spread it captures (`pvs` ≈ 0.82, i.e. buying the
  complete pair for 82¢) has not compressed by even one basis point in 34 days.
  **There is no competition eating this edge.**
- **Residual leg: +0.092 → −0.349.** The entire −0.44/window decline in the
  headline number is this column, to three decimal places.
- Mechanics unchanged: `maker_sh` 18–20, `paired_sh` 5.1–6.1, `resid_sh` 7.6–8.5,
  rebate 0.028–0.030. Nothing about how the ladder fills has changed.

---

## 4. Why the residual leg was always going to do this

The residual is ~8 shares/window of *unpaired* inventory (vs only ~5.6 paired) held
to settle. It is adversely selected by construction: a resting maker bid gets hit
precisely when the market is moving against that side.

**Breakeven hit rate = entry vwap. It has never been met, in any week:**

| week of | resid_sh | entry vwap | actual hit | **breakeven hit** | theoretical EV/share |
|---|---:|---:|---:|---:|---:|
| Jun 29 | 8.48 | 0.4360 | 40.86% | 43.6% | **−0.0274** |
| Jul 06 | 7.90 | 0.4499 | 41.13% | 45.0% | **−0.0386** |
| Jul 13 | 8.30 | 0.4378 | 40.21% | 43.8% | **−0.0357** |
| Jul 20 | 8.15 | 0.4392 | 38.72% | 43.9% | **−0.0520** |
| Jul 27 | 7.65 | 0.4371 | 41.51% | 43.7% | **−0.0220** |
| Aug 03 | 8.04 | 0.4356 | 38.88% | 43.6% | **−0.0468** |

Week 1 was already theoretically −0.027/share; it *realized* +0.084/share. That
+$0.09/window was luck, not edge. The strategy is now printing −0.047 theoretical /
−0.349 realized per window — i.e. **on top of its true EV.** The residual leg's
per-window sd is **3.3–3.7** — larger than the entire mean return of the strategy.
Six weekly points on a series with that variance can show anything.

Same story in the tails: the four best windows in v3's life (+146, +61, +56, +54)
are **residual lottery wins** (the +$60.74 window: $60.00 of it was residual, $0.60
paired). The four worst (−19, −19, −17, −14) are residual losses with little or no
pairing. **The paired leg is the return; the residual leg is the variance.**

---

## 5. Cross-arm check — it is not the market

If the arb were being competed away, every arm would fade together. They don't:

| sleeve | Jun29 | Jul06 | Jul13 | Jul20 | Jul27 | Aug03 |
|---|---:|---:|---:|---:|---:|---:|
| `btc_5m_v31_rcg` net/win | — | — | 1.113 | 0.877 | 1.024 | **1.343** ← best week of its life |
| `btc_15m_v3` net/win | 0.066 | 0.371 | 0.593 | 0.541 | 0.460 | 0.481 ← improving |
| `eth_5m_v3` net/win | 0.482 | 0.296 | 0.436 | 0.290 | 0.329 | 0.266 |
| `btc_5m_v3` net/win | 1.297 | 0.984 | 0.968 | 0.706 | 0.896 | 0.856 |

The **rcg arm — the one that flattens the residual — is at its lifetime best in the
exact week base v3 looks worst.** That is the whole story in one row.

---

## 6. The real, actionable finding

The residual leg has cost **−$1,098.1** over v3's life. Counterfactual with the
residual leg zeroed:

| | total | $/traded window |
|---|---:|---:|
| actual | $6,624.2 | 0.9247 |
| **residual leg removed** | **$7,722.3 (+16.6%)** | **1.0779** |

**Where the bleed sits** (lifetime, by residual entry vwap; `rcg` currently gates
**0.30–0.60** only):

| entry vwap | n | hit% | shares | residual $ | $/share | t | 1st half | 2nd half | gated by rcg? |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0.0–0.1 | 305 | 3.3 | 4,326 | **+169.2** | +0.0391 | +2.16 | +130.3 | +38.9 | no ✓ correct |
| 0.1–0.2 | 731 | 7.3 | 8,253 | +54.4 | +0.0066 | +0.42 | +179.9 | −125.6 | no ✓ correct |
| **0.2–0.3** | 1,010 | 14.2 | 8,603 | **−429.5** | −0.0499 | **−4.15** | −179.4 | −250.1 | **NO ← the gap** |
| 0.3–0.4 | 1,130 | 26.7 | 8,784 | −453.1 | −0.0516 | −4.15 | −221.3 | −231.9 | yes |
| 0.4–0.5 | 1,113 | 40.0 | 8,085 | −278.2 | −0.0344 | −2.32 | −95.5 | −182.6 | yes |
| 0.5–0.6 | 984 | 53.3 | 6,709 | −288.3 | −0.0430 | −3.04 | −130.8 | −157.4 | yes |
| 0.6–0.7 | 879 | 66.0 | 5,876 | −67.6 | −0.0115 | −0.81 | −2.7 | −64.9 | no (ns — leave it) |
| 0.7–0.8 | 711 | 80.0 | 4,889 | +111.7 | +0.0228 | +1.66 | +112.0 | −0.4 | no ✓ correct |
| 0.8–0.9 | 293 | 89.1 | 2,032 | +83.3 | +0.0410 | +2.68 | +42.0 | +41.3 | no ✓ correct |

Clean inverted-U: the tails (≤0.2, ≥0.7) are **profitable**, the coin-flip middle
bleeds. `rcg`'s 0.30–0.60 band is correctly placed but **one bucket too narrow at
the bottom** — the 0.20–0.30 bucket bleeds **−$429.5 at t=−4.15, and is stable
across both halves** (−179 / −250). The 0.60–0.70 shoulder is *not* significant
(t=−0.81) — do not widen the top.

### Proposed v3.4 — ONE env var, pre-registered, no other change

```
TV_LADDER_RCG_LO   0.30 → 0.20      (TV_LADDER_RCG_HI stays 0.60)
```

Spawned as a new paper arm off the same btc-5m base feed, everything else
byte-v3. **Pre-register before it runs, per house rule (v3.2 was killed for exactly
the sin of post-hoc tuning):** the 0.20–0.30 bucket is an in-sample read, so the
frozen hypothesis must be *"Δ ≥ +0.12/window vs the existing `rcg` arm, paired
t ≥ 2, at n ≥ 2,000 (~7d). Δ < 0 IS the finding — no re-tuning of the band."*

---

## 7. What to tell the dashboard

Rank v3 on the **paired leg**, not `total_net_usd`. `total_net_usd` is
signal + a σ=3.4 lottery ticket, and the lottery ticket is ~60% of the inventory.
Any weekly read of the headline number will keep manufacturing false
"degradation" / "recovery" stories. The paired leg has a σ of 2.1 and has moved
1.176 → 1.174 in 34 days.

## 8. Bearing on the go-live decision

This *strengthens* the c2rcg recommendation from
[TVRUST_LADDER_ARM_AUDIT_2026_08_04.md](TVRUST_LADDER_ARM_AUDIT_2026_08_04.md):
the leg that is soft is precisely the leg `rcg` deletes, and the leg `c2` doubles
is the one that is flat-to-rising. The +0.640/w super-additivity is not a
coincidence — it is c2 scaling a stable core while rcg pays for the scaled-up
residual.
