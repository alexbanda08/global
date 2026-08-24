# PBot fleet (2, 3, 5, 6) — window-by-window comparison — 2026-08-13

Wallets: PBot-2 `0x095fd7cc9ddf7110586d1bda3974eccc52155f24`, PBot-3
`0x74a2b82f079e12bcc25cd0d479f17979fb62e32f`, PBot-5
`0x1b58d3de60d7f9e1aefdc9449e8d3733ea096f11`, PBot-6
`0x21d0a97aac03917e752857a551bbe5103a00e8d7`.
Common period: **Jul 25 → Aug 13 (19.2 days)**. Scripts:
`_pbot_fleet_compare_2026_08_13.py` + fetch pipeline. All BUY-only makers on
btc/eth-updown, no sells, no merges (same family signature as b945/b27).

## 1. Four different fingerprints

| | windows | usd | tf mix | **pre-open %** | paired:resid | **first fill (med)** | last fill (med) |
|---|---:|---:|---|---:|---:|---:|---:|
| **PBot-6** | 6,241 | $514k | 5m+15m | **80.9%** | 0.33 | **−53s** | +0s |
| **PBot-2** | 6,341 | $523k | 5m+15m | 0.0% | **1.16** | **+27s** | +240s |
| **PBot-3** | 5,499 | $206k | 5m+15m | 0.0% | 0.22 | **+75s** | +197s |
| **PBot-5** | 1,951 | $56k | **5m only** | 0.0% | **0.05** | **+171s** | +219s |

## 2. They trade the SAME windows — no partitioning

Overlap (% of row's windows also traded by col): PBot-3 is **99.5% inside** PBot-2's set;
PBot-5 86.7% inside PBot-2's; PBot-6 shares ~60% with 2 and 3. The fleet does NOT split
the universe; they stack on the same markets.

## 3. But each owns a TIME SLICE — it's a relay

Median first fills line up in strict sequence: **PBot-6 −53s → PBot-2 +27s → PBot-3
+75s → PBot-5 +171s.** Pre-open collector → at-open pairer → mid-window accumulator →
late-window one-sided finisher. Per-bot Δfirst-fill medians on shared windows are all
consistent with this ordering (2 before 3 by 34s; 2 before 5 by 137s; 6 before everyone).

## 4. Correlation: two correlated, one ANTI-correlated, one independent

| pair | shared w | side-agree | phi | usd-corr |
|---|---:|---:|---:|---:|
| PBot-2 vs PBot-3 | 5,470 | **67.9%** | **+0.416** | +0.58 |
| **PBot-2 vs PBot-5** | 1,692 | **37.5%** | **−0.250** | +0.42 |
| PBot-2 vs PBot-6 | 3,742 | 49.1% | −0.02 | +0.33 |
| PBot-3 vs PBot-6 | 3,235 | 50.3% | −0.01 | +0.19 |
| PBot-3 vs PBot-5 | 1,541 | 45.5% | −0.11 | +0.25 |
| PBot-5 vs PBot-6 | 1,216 | 56.2% | +0.12 | +0.37 |

- **2 and 3 lean the same way** (phi +0.42): same signal or 3 follows 2 (2 enters 34s
  earlier).
- **5 takes the OPPOSITE side of 2** (phi −0.25), entering 137s later, 5m-only, ratio
  0.05 — it is not an independent trader, it is the **late-window counterweight**.
- **6 is orthogonal to everyone** (phi ≈ 0) — the pre-open niche is independent of the
  in-window flow, as its decode implied.
- usd-corr all positive (+0.19..+0.58): sizing responds to the same window-level
  activity/volatility for all four — consistent with one operator scaling the fleet's
  exposure per window.

## 5. The decisive test: CROSS-WALLET PAIRING

Aggregate the 4 books per window and re-compute pairing:

| | paired sh | residual sh | ratio |
|---|---:|---:|---:|
| sum of individuals | 479,799 | 1,100,472 | 0.44 |
| **fleet aggregated** | **604,905** | **850,258** | **0.71** |

**Combining the wallets deletes 22.7% of the residual (+26% more pairs).** A quarter of
what looks like directional risk per-wallet is actually PAIRED ACROSS WALLETS — one
wallet's Up matches another's Down in the same window. The venue (and any per-wallet
copier) sees four directional books; the operator holds a substantially more paired book.
PBot-5 is the clearest instrument of this: near-pure one-sided, late, anti-correlated
with PBot-2 = the fleet's completion leg in a separate wallet.

**CORRECTION (same day, operator challenge upheld):** each bot is INDIVIDUALLY
profitable, verified by cash reconstruction (period: PBot-2 +$7,206 / 6.19% ROI, PBot-3
+$5,658 / 6.45%, PBot-5 +$10,745 / 3.03% at 41.3% WR payoff 1.52, PBot-6 +$158,283 /
13.06%; lifetimes $30k/$62k/$32k/$206k). So PBot-5 is NOT paid insurance for the fleet —
it has standalone edge (late discount buying, loses most windows, wins bigger). The
anti-correlation itself is NOT luck (phi −0.25, n=1,692 → z=−10.3; 2↔3 phi +0.416 →
z=+30.8), but the correct reading is MECHANICAL COMPLEMENTARITY, not cross-subsidy:
complementary rules produce the cross-wallet pairing gain (−22.7% residual) as an
emergent property while each leg remains +EV on its own. The design lesson strengthens:
every time-slice of the window's life carries a separately-positive edge.

## 6. Answers to the question asked

- **Correlated or unrelated?** Neither uniformly. Three relationships coexist:
  2↔3 correlated (+0.42), 2↔5 anti-correlated (−0.25), 6 independent of all (~0).
- **Same windows?** Yes — near-total overlap, no partitioning. What is partitioned is
  **time-within-window** (relay: −53s / +27s / +75s / +171s) and **role**
  (collect / pair / accumulate / counterweight).
- Almost certainly one operator: shared naming, same BUY-only-never-sell-never-merge
  signature, positive usd-corr across all pairs, and the cross-wallet pairing gain.

## 7. Implications for us

1. **The "residual" of a single wallet is not measurable from outside.** Our b945/PBot
   per-wallet residual numbers are UPPER BOUNDS on true directional risk — the operator
   may be pairing across wallets we haven't found (PBot-1, 4, 7…?). This weakens any
   "they tolerate X residual" conclusion, including mine on b945 (its residual may be
   partially completed by a sibling we haven't pulled).
2. **The relay is the design insight**: pre-open collection, at-open pairing, late
   completion are separately-optimal sub-strategies that COMBINE into one paired book.
   Our single-sleeve ladder tries to do all three phases with one quoting policy. The
   v5_latepair + v5_tc direction (phase-specific behavior inside one sleeve) is the
   single-wallet version of exactly this.
3. **PBot-5's role validates late opposite-side completion** at fleet level — the same
   mechanism as b945's taker TC, implemented as maker from a separate wallet.
4. Worth a later sweep for PBot-1/4/7+ (leaderboard/name search) before trusting any
   per-wallet PnL decomposition of this family.

Caveats: common-period comparison only (19.2d); PBot-2/3/6 hit the 120k fetch cap
(coverage truncation differs per bot — overlap %s computed on the common period only);
side = heavy-side sign, which for near-balanced books (PBot-2, ratio 1.16) is a noisy
label — its phi values are attenuated accordingly.
