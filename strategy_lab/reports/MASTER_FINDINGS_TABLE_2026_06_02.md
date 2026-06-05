# Master Findings Table — all strategies tested this session, per market — 2026-06-02

Every strategy/edge tested in this session, with market, n, win-rate, $/trade, t-stat, period, fee model,
and verdict. **WR meaning differs by strategy type** (noted): `dir` = directional WR vs chainlink outcome;
`res` = resolution WR after real fill; `rt+` = % of round-trips positive (scalp, mark-to-market).
Fee: `0.07w` = 0.07 winner-only curve; `legacy` = 2%-on-profit-winner-only; `fee0/feeX` = round-trip taker per leg.

---

## A. ⭐ INTRA-WINDOW EXIT-SCALP — the session's best finding (buy lag-taker token, SELL on book mid-window)
Lag-taker fires (FAST_TAKER_LAGV2 corrected signal) → buy → exit at fire+45–60s. Mark-to-market, NO resolution.

| config | market | n | WR(rt+) | $/tr | t | period | fee | verdict |
|---|---|--:|--:|--:|--:|---|---|---|
| TIME+60s exit (all) | BTC+ETH 5m+15m | 1,342 | ~64% | +1.32 | **6.24** | Apr24–Jun1 | fee0 | strong; mostly variance-cut |
| **`vwap<0.55` gate** | BTC+ETH 5m+15m | **398** | ~67% | **+2.56** | **5.50** | Apr24–Jun1 | **0.07 both (worst)** | **✅ CI[+1.65,+3.48] excl 0** |
| Walk-forward (rolling) | BTC+ETH 5m+15m | 312 | — | **+2.98** | **6.33** | Apr24–Jun1 | fee0.015 | ✅ selection-bias-corrected |
| Direction permutation | BTC+ETH | 1,329 | — | +0.96 vs −4.52 opp | p=0.0000 | Apr24–Jun1 | fee0.015 | ✅ lag-direction real |
| forward segment (fwd_oos) | BTC+ETH | 76 | — | **−0.17** | −0.0 | May29–Jun1 | fee0 | ⚠️ **NOT confirmed (open)** |
**Verdict: SHADOW-DEPLOY ready** (gate=`vwap<0.55`, exit+60s). Open: forward-OOS ≥200 fires + live taker-sell fee. Spec: `TV_AGENT_SPEC_SCALP_EXIT_SHADOW_2026_06_02.md`.

## B. Lag-taker (hold-to-resolution) — OOS re-validation
| cut | market | n | WR(dir) | $/tr | t | period | fee | verdict |
|---|---|--:|--:|--:|--:|---|---|---|
| Foundation ≥3bps | BTC 5m+15m | 513 | 66.7% | +2.99 | 3.31 | May8–29 | 0.07w | real |
| Foundation ≥3bps | ETH 5m+15m | 717 | 64.4% | +1.95 | 2.53 | May8–29 | 0.07w | real |
| Foundation ≥3bps | SOL 5m+15m | 635 | 59.4% | −0.43 | −0.52 | May8–29 | 0.07w | ❌ drag (drop) |
| OOS unseen ≥3bps | BTC | 327 | 62.4% | +0.83 | 0.73 | bwd+fwd | 0.07w | thin |
| OOS unseen ≥3bps | ETH | 229 | 58.5% | −0.31 | −0.22 | bwd+fwd | 0.07w | degraded |
| FIT vs UNSEEN ≥3 | BTC+ETH | 786/556 | 65/61% | +1.71/+0.36 | 2.38/0.41 | Apr24–Jun1 | 0.07w | OOS-weak |
| A1-style fill @+5s | BTC+ETH | 99 | 54.5%(res) | +1.16 | 0.47 | Apr24–May27 | 0.07w | vwap0.51, thin |
**Verdict: real but thin/forward-weak; SOL dead. Superseded by the exit-scalp (A).**

## C. Shadow fleet — sleeves with genuine EDGE (t≥2, $/tr>0)  [poly_updown_resolution, ~45d]
| sleeve | market | n | WR(res) | vwap | $/tr | t | verdict |
|---|---|--:|--:|--:|--:|--:|---|
| ema50_ema800_off600_down (Kalshi) | BTC 15m | 108 | 84.3% | 0.74 | +1.33 | 2.00 | ✅ best, cross-venue |
| ema50_ema800_off600_down (Poly) | BTC 15m | 134 | 81.3% | 0.73 | +1.24 | 1.99 | ✅ replicates Kalshi |
| eth_5m_l_ema50_hurst_grandparent_v8 | ETH 5m | 183 | 71.0% | 0.63 | +0.66 | **2.2** | ✅ (the "5W streak" one) |
| btc_15m_ts_trstack_off600_down | BTC 15m | 37 | 89.2% | 0.76 | +1.29 | 2.1 | ✅ low-n |
| btc_15m_mpskew_trstack_off600_down | BTC 15m | 50 | 94.0% | 0.84 | +0.61 | 2.4 | ✅ low-n |
| ALL_15m_S4_prewindow (shadow poly) | BTC/ETH/SOL 15m | 28 | 71.4% | — | +9.30 | 2.23 | 🟡 n<30, Kalshi twin LOSES |
| sol_5m_momo_v2_HOLD_f7 | SOL 5m | 164 | 59.1% | — | +3.73 | 1.97 | 🟡 promising, asset-specific |
| btc_5m / btc_15m momo_HOLD_f7 | BTC 5m/15m | 171/62 | 54/58% | — | +2.31/+3.85 | 1.2 | 🟡 underpowered |

## D. Shadow fleet — confirmed BLEEDERS (kill list) [~45d]
| sleeve | market | n | WR | $/tr | total$ | t |
|---|---|--:|--:|--:|--:|--:|
| volume_INV_NIGHT ×6 | BTC/ETH/SOL 5m+15m | 900–2819 | ~50% | −0.45 to −1.81 | **−$10,000** | up to −2.4 |
| btc_5m_l_1hrf_imb5_rf_v8 | BTC 5m | 1,922 | 76.4% | −0.32 | −611 | **−4.7** (priced-in trap at scale) |
| btc_5m_l_1hrf_imb5_ribbon_v8 | BTC 5m | 1,527 | 76.4% | −0.20 | −310 | −2.8 |
| phase1_kelly (+V10) | ALL 5m | 428–1,287 | ~50% | −1.22 to −2.56 | −$2,810 | — |
| fade_momo / fade_sniper ×N | BTC/SOL/ETH | 60–247 | 43–55% | neg | −$1,300 | — |
| sol v3/v3_2/v3_3, btc_5m_v4, sniper_hod | SOL/BTC | 129–507 | <53% | neg | −$1,700 | — |
**Fleet total: 215 sleeves, net −$25.4k. 4 EDGE, 13 promising, 25 bleeders.** Full table: `_sleeve_edge_2026_06_02/full_table.md`.

## E. New-edge research candidates (16 Tier-1) — validation Stages 1–5
| candidate | market | n | WR | $/tr | period | verdict |
|---|---|--:|--:|--:|---|---|
| A1 HL short-cascade 60s | BTC+ETH 5m+15m | 133 | 57.9%(dir) | — | Apr24–May27 | ⚠️ real-thin (p=0.03); fill +$1.16 t=0.47 |
| A2 cross-CEX liq cascade | BTC+ETH | 84 | 60.7%(dir) | — | May29–Jun1 | 🟡 promising, 2.8d only |
| B1 Polymarket VPIN | BTC+ETH | 11,641 | **75.6%** | **−0.62** | Apr26–Jun1 | ❌ TRAP (high WR, −$/tr) |
| C4 Polymarket CVD-follow | BTC+ETH | 22,499 | **67.0%** | **−1.03** | Apr26–Jun1 | ❌ TRAP |
| C1 / C8 L25 depth ratio/asym | BTC+ETH | 9,000+ | 31–41% | — | Apr22–Jun1 | ❌ INVERTED (p=0) |
| B2–B6 klines (KAMA/semivar/CUSUM/Kalman/RS) | BTC+ETH+SOL | 28k+ | ~50% | ~0 | Apr24–Jun1 | ❌ dead (price-tech = coin-flip) |
| C5 session-open burst | BTC+ETH+SOL | 1,582 | 45% | — | Apr24–Jun1 | ❌ anti (−11pp; fade-only) |
| C6/C7 HL prior-slot/ETH-long | BTC+ETH | 0–492 | ~51% | — | Apr24–May27 | ❌ weak / not reproducible |
**Verdict: 0 of 16 deploy-grade. Report: `EDGE_VALIDATION_TIER1_2026_06_01.md`.**

## F. Physics signal (continuation, hold-to-resolution)
| pocket | market | n | WR | $/fire | t | period | verdict |
|---|---|--:|--:|--:|--:|---|---|
| dist_abs≥40 & vwap<0.95 & spread≤0.02 | BTC 5m+15m | 343 | 90.1% | +0.85 | 1.68 | OOS May16–Jun1 | 🟡 not significant; priced-in baseline |
| all-fires baseline | BTC | 11,210 | 81.6% | ≈0 | — | Apr24–Jun1 | ❌ priced-in (gap≈0) |
| physics × HL-liq cascade combo | BTC | 847 | 89.7% | +0.57 | 1.75 | ≤May27 | ❌ no combination (sparsity) |

---

## Headline summary by market

| market | best edge found | $/tr | t | status |
|---|---|--:|--:|---|
| **BTC 15m** | ema50_ema800_off600_down (Kalshi+Poly) | +1.24–1.33 | ~2.0 | shadow, cross-venue ✅ |
| **BTC 5m+15m** | **exit-scalp `vwap<0.55`** | **+2.56** | **5.50** | shadow-deploy ready ⭐ |
| **ETH 5m** | ema50_hurst_grandparent_v8 | +0.66 | 2.2 | shadow ✅ |
| **ETH 5m+15m** | exit-scalp `vwap<0.55` | +2.56(pooled) | 5.50 | shadow-deploy ⭐ |
| **SOL 5m** | sol_5m_momo_v2_HOLD_f7 | +3.73 | 1.97 | promising, underpowered |
| **SOL (lag/scalp)** | — | — | — | ❌ thin books, dropped |

**One-line takeaway:** the only edge that survived full rigor (walk-forward + permutation + worst-case fee) is the
**intra-window exit-scalp on BTC+ETH with `entry_vwap<0.55`** (+$2.56/tr, t=5.50) — shadow-ready, pending forward
confirmation. The deployed shadow EDGE sleeves (ema50_ema800 BTC-15m, eth hurst) are real but borderline (t≈2).
Everything else is priced-in, a trap, or a confirmed bleeder.
