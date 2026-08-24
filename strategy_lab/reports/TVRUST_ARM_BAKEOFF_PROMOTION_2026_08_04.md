# Ladder arm bake-off → next promotion — 2026-08-04

All btc-5m arms, **common era 2026-07-27 → 08-04** (9 days, same slugs, same feed,
regime differenced out). Paper sim. `distinct on (sleeve_id, slug)` last summary.

---

## 1. The complete table

### Returns

| arm | traded win | WR | net/win | **paired leg** | **residual leg** | rebate | total 9d | $/day |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **`_v31_c2rcg`** | 1,762 | **77.1%** | **1.677** | **1.688** | −0.057 | 0.046 | **$2,955** | **$372** |
| `_v31_c2` | 1,958 | 59.0% | 1.297 | 1.646 | −0.394 | 0.045 | $2,539 | $285 |
| **`_v31_rcg`** | 1,958 | **77.8%** | 1.094 | 1.066 | **0.000** | 0.029 | $2,142 | $243 |
| `_v3` (base) | 1,949 | 58.8% | 0.887 | 1.060 | −0.201 | 0.029 | $1,729 | $189 |
| `_v31_d1` | 2,255 | 56.2% | 0.880 | **1.380** | **−0.533** | 0.034 | $1,986 | $226 |
| `_v3_live` twin | 1,642 | 59.0% | 0.843 | 1.080 | −0.266 | 0.029 | $1,383 | $177 |

### Capital + risk

| arm | maker_sh | paired_sh | resid_sh | `pvs` | notional/win | **return on notional** | sd/win | **Sharpe/win** | sd/day | Sharpe/day |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `_v31_rcg` | 19.1 | 5.63 | 7.79 | 0.8176 | $7.66 | **14.28%** | **2.780** | **0.394** | 68.5 | 3.55 |
| `_v31_c2rcg` | 30.4 | 9.20 | 12.05 | 0.8225 | $12.30 | 13.64% | 4.721 | 0.355 | 117.6 | 3.17 |
| `_v3` | 19.2 | 5.73 | 7.72 | 0.8228 | $7.82 | 11.35% | 3.652 | 0.243 | 55.2 | 3.43 |
| `_v3_live` | 19.4 | 5.70 | 7.96 | 0.8175 | $7.81 | 10.78% | 3.589 | 0.235 | 58.1 | 3.04 |
| `_v31_c2` | 29.8 | 8.94 | 11.89 | 0.8219 | $12.12 | 10.70% | 5.865 | 0.221 | 121.9 | 2.34 |
| `_v31_d1` | 22.9 | 7.17 | 8.53 | 0.8158 | $8.95 | 9.84% | 4.079 | 0.216 | 51.1 | 4.42 |

### Robustness

| arm | paired Δ vs v3 | paired t | lifetime n | lifetime t | ex-top-5 | ex-top-20 | % of mean from top-20 | H1 → H2 | neg days | max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| `_v31_c2rcg` | **+0.640** | **8.87** | 1,761 | 14.92 | 1.569 | 1.411 | 15.9% | 1.533 → **1.818** ↑ | 0/9 | $0 |
| `_v31_c2` | +0.318 | 4.04 | 4,535 | 13.20 | 1.172 | 1.016 | 21.7% | 1.258 → 1.344 ↑ | 0/9 | $0 |
| `_v31_rcg` | +0.162 | 3.15 | 4,545 | **23.83** | 1.033 | 0.941 | **14.0%** | 1.008 → **1.199** ↑ | 0/9 | $0 |
| `_v3` | — | — | 7,164 | 17.72 | 0.812 | 0.695 | 21.7% | 0.890 → 0.884 → | 0/9 | $0 |
| `_v31_d1` | +0.101 | 1.47 ✗ | 5,170 | 15.56 | 0.811 | 0.687 | 22.0% | 0.913 → **0.839** ↓ | 0/9 | $0 |
| `_v3_live` | −0.001 | −0.01 | 2,110 | 9.51 | 0.763 | 0.642 | 23.8% | 0.906 → 0.787 ↓ | 0/8 | $0 |

Retired, for the record: `_v31_d4` Δ−0.215 t=−2.87 · `15m_v32_cheapmid` −5.062/w t=−30.2 ·
`15m_v32_cheap` Δ−0.321 t=−1.76 · `15m_v2` −0.622/w t=−1.85 · `eth_5m_v31_rcg` Δ≈0.

---

## 2. What the table says

**Every arm's edge is the paired leg. Every arm's variance is the residual leg.**
`pvs` is 0.816–0.823 across all six — they are all capturing the identical 18¢
arb, they differ only in how much of it they grab and how much residual junk
they carry home.

- **`c2` = size.** Paired leg 1.060 → 1.646 (+55%) for 2× clip. But residual bleed
  also doubles, −0.201 → −0.394, and sd goes 3.65 → 5.87. Net effect on *return
  per dollar deployed*: **11.35% → 10.70%. c2 alone is capital-destructive.**
- **`rcg` = risk removal.** Same size, same paired leg (1.060 → 1.066), but the
  residual leg goes **−0.201 → exactly 0.000**. It still carries 7.79 residual
  shares — it flattens the losing 0.30–0.60 band and keeps the profitable tails.
  Return on notional **11.35% → 14.28%**, sd **3.65 → 2.78**, WR **58.8% → 77.8%**.
- **`c2rcg` = both, and it super-adds** (0.318 + 0.162 = 0.480 < 0.640) for the
  reason the decomposition now makes obvious: c2's problem *is* residual bleed, and
  rcg *is* the residual fix. Each arm repairs the other's weakness.
- **`d1` is the sleeper and the miss.** Best paired leg of any 1× arm — **1.380 vs
  base 1.060 (+30%)** at only 1.14× the capital — but the *worst* residual leg
  (−0.533) eats all of it. Its paired Δ vs base is t=1.47 → fails, and H1→H2 is the
  only one declining. Do not promote. See §5.

---

## 3. Promote next: **`_v31_rcg`** — not c2rcg

This reverses the ordering in [TVRUST_LADDER_ARM_AUDIT_2026_08_04.md](TVRUST_LADDER_ARM_AUDIT_2026_08_04.md) §6.
Capital efficiency and paper→live model risk weren't in that read; they decide it.

**1. It is the only arm whose fill model is already validated live.**
`rcg` changes **zero** about size, depth, price, or placement — it is a pure exit
rule on inventory you already hold. Its fill path is byte-identical to `v3`, whose
live twin has parity **t = −0.01 over 2,110 windows**. `c2` doubles clip size,
which is precisely where a maker sim is least trustworthy (queue position at size:
the sim fills your whole clip, the book fills the front of the queue). Promoting
c2rcg now means introducing an unmeasured fill-model risk *in the same experiment
that exists to measure fill-model risk.* Confounded, and unnecessarily.

**2. It wins per dollar, which is your actual constraint.**
14.28% vs 13.64% return on notional. c2rcg's bigger headline is bought with 1.6×
the capital ($12.30/win vs $7.66). Your wallet is $80 pUSD and the day cap is $40
notional — capital is binding, not opportunity. Per-dollar is the right metric.

**3. It wins every risk axis.** Best window Sharpe (0.394), lowest sd by 40%
(2.78 vs 4.72), lowest daily sd (68.5 vs 117.6), highest win rate (77.8%), most
outlier-robust (14.0% of mean from top-20 vs 15.9%). Under a hard `$50` daily-loss
latch, c2rcg's 1.7× daily variance means materially more spurious trips and more
time disarmed.

**4. It has 3× the evidence.** n=4,545 traded windows since Jul 14, **lifetime
t=23.83 — the highest of any arm ever run.** c2rcg has 1,761 windows over 9 days.

**5. It fixes the leg that is actually soft.** Per the degradation forensics: the
paired core is flat-to-rising, the residual leg is a structurally negative-EV
lottery (breakeven hit = entry vwap ≈43.7%, actual ≈40%). `rcg` deletes it. That
is why the rcg arm's most recent week is the best of its life while base v3's
looks weak.

### The clean experiment
Spawn `poly_ladder_btc_5m_v31_rcg_live` at the **same caps as `v3_live`**
(after the cap lift: $5 clip / $20 per side / $200 day / $50 loss). Size is then
held constant across the live A/B, so the live read isolates exactly one thing:
does gating the residual survive contact with real fills? Both live sleeves share
the btc-5m book feed, so feed quality doesn't confound either.

**Pre-register now:** promote to size only if, at n ≥ 1,500 live-eligible windows,
**(a)** capture ratio ≥ 60% vs its own paper twin, and **(b)** paired-leg Δ vs
`v3_live` CI excludes 0. Capture < 60% is a finding about the fill model, not a
reason to re-tune the band.

---

## 4. Then c2rcg — the size question, asked separately

c2rcg is a real result and it stays queued: it passed a genuine pre-registration
(Δ+0.640 vs a frozen ≥+0.35 bar, t=8.87 vs t≥2, n=2,291 vs n≥2,000), it is
super-additive with a mechanistic explanation, its half-split is *improving*
(1.533 → 1.818), and it has the highest absolute $/day of anything you run.

It goes live **third**, once the rcg live A/B has produced a real capture ratio —
because at that point "does 2× clip fill like the sim says" is the only open
question, and you can ask it cleanly instead of tangled with the residual question.
If capture holds at size, c2rcg is the end state.

---

## 5. Bench: two pre-registerable hypotheses, neither promoted

Both are in-sample decomposition reads. Freeze the threshold *before* the arm runs
— `v32_cheap` was killed for exactly the sin of tuning after the fact.

**v3.4 — widen the rcg band.** `TV_LADDER_RCG_LO 0.30 → 0.20`, nothing else.
The 0.20–0.30 residual bucket bleeds **−$429.5 lifetime at t=−4.15**, stable across
halves (−179 / −250), and sits just outside the current gate. The 0.60–0.70
shoulder is *not* significant (t=−0.81) — do not widen the top.
Frozen bar: Δ ≥ +0.12/w vs the existing `rcg` arm, paired t ≥ 2, n ≥ 2,000.

**v3.5 — `d1 × rcg`.** d1 has the best paired leg of any 1× arm (**1.380**, +30% vs
base) at 1.14× capital; its whole problem is the worst residual leg (−0.533). If
rcg neutralizes d1's residual the way it neutralizes v3's, the implied result is
~1.41/win on $8.95 notional = **15.8% return on notional, better than every arm
currently running.** Caveat: d1 fills differently (depth-1), so its residual may
not respond to the same band — this is an inference, not a measurement.
Frozen bar: Δ ≥ +0.35/w vs the `d1` arm, paired t ≥ 2, n ≥ 2,000.

---

## 6. Order of operations

1. **Lift the v3_live caps** ($4→$20/side, $2→$5 clip, $40→$200 day, $15→$50 loss),
   top up the wallet, add restart-grace to the watchdog kill. Measure real capture
   ratio for 3–5 days. *No new arm.*
2. **Promote `_v31_rcg` live** at identical caps → clean size-controlled A/B.
3. **Promote `_v31_c2rcg` live** at $10 clip / $40 side, once capture is known.
4. Spawn the two bench arms as paper, pre-registered, in parallel with step 1 —
   they cost nothing and read out in ~7 days.

**Do not promote:** `d1` (paired t=1.47, only declining half-split), `c2` alone
(capital-destructive standalone), `eth_5m` (⅕ the edge), `15m` (¼ the fire rate).

---

## 7. Standing caveat

Every number here is a maker-fill **simulation** with `rebate_rate_assumed=0.0015`.
The ranking between arms is trustworthy — same sim, same feed, same slugs, one
variable changed at a time. The absolute expectancy is not, and will not be until
step 1 produces a capture ratio. Nothing in this table survives a capture ratio of
20%.
