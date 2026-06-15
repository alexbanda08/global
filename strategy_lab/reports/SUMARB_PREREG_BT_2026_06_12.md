# SUM-ARB PRE-REGISTERED BACKTEST — 2026-06-12

**VERDICT: PARK. No cell passes the pre-registered criteria.**

---

## A. Pre-Registration (written before PnL computed)

**Strategy under test:** At/near window open of crypto up/down markets, walk BOTH books (Up ask + Down ask); if `sum_ask = vwap_up + vwap_dn < threshold`, buy both legs as taker (equal notional per leg); hold to resolution. PnL on winner leg = `shares × (1−p_win) × (1−0.07×p_win)`; loser leg = `−shares × p_lose`. Total slug PnL = both legs combined.

**Universe:**
- ALL btc/eth/sol 5m+15m slugs, canonical Apr 22 → Jun 11 2026, with L25 coverage + resolution
- XRP excluded — no canonical L25 in production window
- Entry offsets: {+5s, +30s, +60s} after `slot_start`
- L25 NATIVE 10Hz (`subsample_1hz=False`), strict-asof book at fire time
- Walk BOTH asks for $70/leg notional via `book_walk_fill`
- Skip slug if either book empty/sparse at fire (count + report)

**Gate grid:** `sum_ask < {1.00, 0.99, 0.98, 0.97, 0.95}` → 15 cells + ungated baseline

**IS split:** Apr 22 – May 20 | **OOS split:** May 21 – Jun 11

**Metrics per cell:** n slugs, % universe, $/slug, total, WR, bootstrap CI95 (2000 iters), ex-top2 $/slug, IS vs OOS

**Decision rule (pre-registered):**
> PURSUE if any cell: OOS CI95_lo > 0 AND ex_top2 positive AND n_OOS ≥ 100. Otherwise PARK.

**How this differs from the dead prior test** (SCALP_NEW_EDGE_HUNT_2026_06_09.md Trial Z):
- Prior test used BBO top-of-book (`load_orderbook_bbo`), Mar 30–Apr 21 window; found <0.04% of snapshots with sum_ask<1 AND all at dust/zero executable size → concluded structurally impossible.
- This test: full L25 25-level book, Apr 22–Jun 11 production window, $70/leg notional (realistic fill matching ce25 equivalent), 3 entry offsets, direct PyArrow streaming.
- Also distinct from MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md: that test found censoring bias in maker-arb (right-censored losers). Here ALL entered slugs resolve (both legs), no censoring issue.

---

## B. Coverage

| Coin | Unique slugs (resolution) | L25 coverage | Evaluable rows (all offsets) | Notable skips |
|------|--------------------------|--------------|------------------------------|---------------|
| BTC | 17,008 | 100% | 44,976 | no_snap_up=5,965 (15% of offset/slug combos — book not yet open at +5s) |
| ETH | 17,014 | 100% | 44,958 | no_snap_up=5,945 |
| SOL | 17,009 | 100% | 44,944 | no_snap_up=5,971 |
| **Total** | **51,031** | | **134,878** | |

`no_snap_up` skips (35% of +5s slugs) = L25 book has no snapshot prior to fire_us. Consistent with production: at slot_start+5s many markets haven't had a book event yet. Resolved at +30s/+60s offsets.

Underfill rate (book too thin to fill $70/leg):
- +5s: 0.04% Up / 0.05% Down
- +30s: 0.06% Up / 0.07% Down
- +60s: 0.08% Up / 0.06% Down

Book is adequately liquid for $70/leg notional — fills are essentially complete.

---

## C. sum_ask Distribution

**Key finding: sum_ask < 1.0 NEVER occurs at +5s or +30s. One anomalous row at +60s (data artifact).**

| Offset | n | mean | median | p10 | p90 | <1.00 | <0.99 | <0.98 | <0.97 | <0.95 |
|--------|---|------|--------|-----|-----|-------|-------|-------|-------|-------|
| +5s | 44,071 | 1.0911 | 1.0560 | 1.0137 | 1.2061 | **0** | 0 | 0 | 0 | 0 |
| +30s | 44,940 | 1.0578 | 1.0410 | 1.0119 | 1.1238 | **0** | 0 | 0 | 0 | 0 |
| +60s | 45,867 | 1.0546 | 1.0408 | 1.0117 | 1.1150 | **1** | 1 | 1 | 1 | 1 |

All thresholds get 0 qualifying slugs in OOS. The 1 row at +60s (btc-updown-5m-1778360700, IS period) is a **degenerate artifact**: Down vwap=0.252 (book underfilled, only 142 shares walked) → sum_ask=0.742 is a thin-book artifact, not a real arb opportunity.

The minimum observed sum_ask across 134,878 evaluations (excluding the artifact) is **≥ 1.01**.

**p1 = 1.010** — even the most favorable 1st-percentile slug has sum_ask 1.0% above par.

---

## D. OOS Results Table (May 21 – Jun 11)

```
offset  threshold   n_OOS  %univ   $/slug   CI_lo   CI_hi  ex-top2    wr
------------------------------------------------------------------------
     5    ungated   14268  100.0% -11.6157 -11.9221 -11.3342 -11.6406 0.179
     5       1.00       0    0.0%      NaN     NaN     NaN      NaN   NaN
     5       0.99       0    0.0%      NaN     NaN     NaN      NaN   NaN
     5       0.98       0    0.0%      NaN     NaN     NaN      NaN   NaN
     5       0.97       0    0.0%      NaN     NaN     NaN      NaN   NaN
     5       0.95       0    0.0%      NaN     NaN     NaN      NaN   NaN
    30    ungated   15137  100.0%  -7.7798  -8.3409  -7.2037  -7.8575 0.283
    30       1.00       0    0.0%      NaN     NaN     NaN      NaN   NaN
    30       0.99       0    0.0%      NaN     NaN     NaN      NaN   NaN
    30       0.98       0    0.0%      NaN     NaN     NaN      NaN   NaN
    30       0.97       0    0.0%      NaN     NaN     NaN      NaN   NaN
    30       0.95       0    0.0%      NaN     NaN     NaN      NaN   NaN
    60    ungated   16064  100.0%  -8.2542  -9.0200  -7.4779  -8.3495 0.289
    60       1.00       0    0.0%      NaN     NaN     NaN      NaN   NaN
    60       0.99       0    0.0%      NaN     NaN     NaN      NaN   NaN
    60       0.98       0    0.0%      NaN     NaN     NaN      NaN   NaN
    60       0.97       0    0.0%      NaN     NaN     NaN      NaN   NaN
    60       0.95       0    0.0%      NaN     NaN     NaN      NaN   NaN
```

Note: ungated $/slug is strongly negative because the test ALWAYS enters at $70/leg regardless of sum_ask. With median sum_ask 1.04–1.09, the baseline PnL is approximately `−(sum_ask − 1) × $70 + fee_drag` = approximately −$3 to −$6 per leg × 2 legs = −$6 to −$12/slug, consistent with observed −$8 to −$12 range. This is the correct baseline for the strategy's economics.

---

## E. IS Results Table (Apr 22 – May 20)

```
offset  threshold   n_IS   %univ   $/slug   CI_lo   CI_hi  ex-top2    wr
------------------------------------------------------------------------
     5    ungated   29803  100.0% -14.0713 -14.2520 -13.8845 -14.0797 0.170
     5       1.00       0    0.0%      NaN
     [all gated rows: n=0]
    30    ungated   29803  100.0% -11.2902 -11.6582 -10.9275 -11.3176 0.272
    60    ungated   29803  100.0% -12.3113 -12.8116 -11.8370 -12.3524 0.272
    60       1.00       1    0.0%  +0.3581 +0.3581 +0.3581  NaN      1.000
    [artifact slug only — see §C]
```

---

## F. Sanity Checks (10 BTC slugs, offset +5s)

Manual verification of PnL arithmetic against spec:

| slug | up_vwap | dn_vwap | sum_ask | outcome | win_vwap | pnl |
|------|---------|---------|---------|---------|---------|-----|
| btc-updown-15m-1780446600 | 0.5100 | 0.5093 | 1.0193 | Up | 0.5100 | −$5.15 |
| btc-updown-5m-1780224300 | 0.3850 | 0.6365 | 1.0215 | Down | 0.6365 | −$31.81 |
| btc-updown-5m-1777812600 | 0.4704 | 0.5500 | 1.0204 | Down | 0.5500 | −$14.93 |
| btc-updown-5m-1779834900 | 0.5233 | 0.5076 | 1.0308 | Down | 0.5076 | −$4.50 |
| btc-updown-5m-1780054800 | 0.4899 | 0.5300 | 1.0199 | Down | 0.5300 | −$10.23 |
| btc-updown-5m-1777400400 | 0.6044 | 0.4544 | 1.0588 | Up | 0.6044 | −$26.13 |
| btc-updown-5m-1779370800 | 0.5655 | 0.4544 | 1.0199 | Down | 0.4544 | +$11.38 |
| btc-updown-5m-1777239600 | 0.5200 | 0.4991 | 1.0191 | Down | 0.4991 | −$2.21 |
| btc-updown-5m-1780250700 | 0.4866 | 0.5382 | 1.0249 | Down | 0.5382 | −$12.21 |
| btc-updown-5m-1778570400 | 0.4200 | 0.5900 | 1.0100 | Up | 0.4200 | +$23.82 |

**Arithmetic check** (row 10: up=0.42, dn=0.59, $70/leg, Up wins):
- Up shares ≈ 70/0.42 = 166.67
- Redemption gross = 166.67 × 1.0 = $166.67
- Fee = 0.07 × 0.42 × 0.58 = 0.01706; net payout = 166.67 × (1−0.01706) = $163.82
- Minus up_cost=$70, minus dn_cost=$70 → **PnL = $23.82** ✓ matches

Row 2 (down=0.6365, $70/leg, Down wins):
- Down shares = 70/0.6365 = 110.0
- Fee = 0.07 × 0.6365 × 0.3635 = 0.01618; net = 110.0 × (1−0.01618) = $108.22
- Minus $70+$70 = **PnL = −$31.78** ≈ −$31.81 (rounding in actual walk) ✓

---

## G. Decision

**PARK. Pre-registered rule not met on ANY cell.**

Reason: **sum_ask < 1.00 occurs in 0/44,071 (+5s), 0/44,940 (+30s), and 1/45,867 (+60s) evaluations** across 51,031 slugs over Apr 22–Jun 11. No cell has n_OOS ≥ 100 under any threshold.

The structural reason: Polymarket market makers maintain a persistent overround. Median sum_ask = 1.04–1.06 (4–6% above par) in the production window. The p1 (1st percentile best observed) is 1.010 — even in the most favorable market conditions across 50k slugs, the walk-in sum_ask was still 1% overround. The prior BBO test (Trial Z, SCALP_NEW_EDGE_HUNT_2026_06_09.md) reached the same conclusion on thinner data; this test with the full L25 25-level book confirms it definitively.

---

## H. Why Wallet 0xce25e214 Profits Despite No sum_ask < 1.0 Gate

The wallet decode (§4 of WALLET_CE25E214_DECODE_2026_06_12.md) found median sum_ask = **1.041** at entry — they also never fire on sum_ask < 1.0 in 65% of cases. Their edge is NOT pure pair-arb spread capture. Their per-slug profit ($5–7/slug steady-state, $31/slug on volatile days) comes from **resolution hold + CTF redemption arithmetic** at their scale (486 slugs/day × $138/slug = ~$67k/day deployed). The economics work because:

1. They enter BOTH sides → WR is ~50% on any individual leg
2. Winner leg redeems at $1.00, recovering more than both leg costs when sum_ask is in a favorable region
3. The profit is driven by variance/skew in outcomes at their scale, not a mean spread capture
4. **Crucially: they need $138 deployed per slug to extract the edge.** At $70/leg ($140/slug) our backtest correctly models their size. The problem is the overround IS the fee — you need to be operating at scale where variance averaging makes the 4% overround manageable, which requires the resolution-hold model to generate expected positive value.

**The per-slug positive EV at $140 deployed requires:** `E[winner_payout] > sum_ask × $70`. Since winner_payout = $70/p_win × (1−0.07×p_win) and sum_ask = p_up + p_dn, the expected value calculation shows this is only positive when the resolution probability diverges from the market prices — i.e., the wallet's edge is informational or timing, NOT structural pair-arb.

**Implication for replication:** The wallet's positive PnL may reflect timing/size/order-flow advantages not capturable from canonical L25 data. The strategy is not deployable from a simple sum_ask < 1.0 gate.

---

## I. Replication Gap vs Wallet Performance

| Metric | Wallet (ce25e214) | This backtest |
|--------|-------------------|---------------|
| Median sum_ask at entry | 1.041 | 1.041–1.046 (same data) |
| sum_ask < 1.0 rate | 35% | 0% |
| $/slug | +$5.88–31.29 | −$8 to −$14 (ungated) |
| Method | Real fills + CTF redeem | L25 walked vwap |

The large gap (wallet +$5.88 vs backtest −$8 ungated) is explained by: (1) the wallet's fills are the ACTUAL taker fills vs our simulated L25 walk which may overestimate cost on thin moments; (2) the wallet likely fires at moments when their sum_ask IS below 1.0 using a real-time screen we cannot replicate from historical 10Hz snapshots; (3) 35% of their slugs DO have sum_ask<1.0 — they have selectivity we lack.

The wallet's **35% of slugs at sum_ask<1.0** is their actual selection. Our canonical L25 shows 0% at any threshold. This discrepancy likely means:
- The wallet is using the live CLOB REST (not L25 snapshots) to see momentary arb windows sub-10Hz
- Or there's a timing difference — they may fire at T+0 (before most market makers have posted) whereas our +5s offset still shows overround

---

## J. Files

| File | Path |
|------|------|
| Script | `strategy_lab/directional/_sumarb_prereg_bt.py` |
| Per-slug artifact | `strategy_lab/directional/_results/sumarb_prereg.parquet` (134,878 rows) |
| Cell table | `strategy_lab/directional/_results/sumarb_prereg_cells.csv` |
| This report | `strategy_lab/reports/SUMARB_PREREG_BT_2026_06_12.md` |

---

## K. TVRUST Angle

The operator has a Rust TV port at `C:\Users\alexandre bandarra\Desktop\TVRUST`. A real-time dual-book sum_ask monitor is technically feasible but not useful given the above findings:

- **If the gate is sum_ask < 1.0 (or even < 1.01):** never fires in 50k historical slugs; a live monitor would almost never trigger
- **If sum_ask<1.0 windows exist sub-10Hz at T+0:** they would last milliseconds (pure arb closes instantly); a Python-latency engine cannot capture them; Rust infra would be needed but competing against the wallet's existing speed advantage
- **The structural edge does not exist at L25 observed prices** — do not build infra for this strategy variant

**Recommended next action:** Instead of pursuing sum_ask<1.0 pair-arb, the wallet's actual edge (35% of slugs at sum_ask<1.0 in their fills) suggests they have live-feed access to momentary tight books at slot open (T+0, before other MMs post). This would require: (1) capturing actual CLOB WebSocket order book at the precise slot_start second, (2) measuring sum_ask before any delay, (3) testing if sum_ask<1.0 exists there. This is infra-first research, not a backtest.
