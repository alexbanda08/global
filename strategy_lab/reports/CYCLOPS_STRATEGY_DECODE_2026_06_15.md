# Cyclops.exe — strategy DECODE + local validation — 2026-06-15

**Wallet:** `0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c` ("Cyclops.exe"). 5d pull/handoff: `HANDOFF_CYCLOPS_5D_2026_06_15.md`.
**Premise (operator):** the favorite-hold we see is **new** (last ~5d); decode it as a fresh strategy and validate on local canonical data.
**Verdict:** decoded with certainty — it is a **mid-window oracle-lag favorite-hold**: buy the side Binance has ALREADY confirmed mid-window, while Polymarket's favorite token still lags (priced ~0.83 vs conditional truth ~0.88–0.94), hold to resolution. **Signal validated OOS on 25,290 local BTC/ETH 5m slugs.** The whole edge = the poly-vs-binance price lag; it is +EV only while poly underprices the confirmed favorite.

---

## 1. The decode (26/26 entries, fresh Binance 1s join)

Script `wallet_hunt/cyclops_decode_5d_2026_06_15.py` joined each buy to fresh Binance 1s (canonical ends Jun 11; entries are Jun 11–15 → no overlap, had to fetch live).

| Feature | Value |
|---|---|
| **Alignment** (fav side == Binance direction at fire) | **100% (26/26)** |
| Fire offset into 5m window | median **124s (42%)**, range 76–261s |
| \|Binance move open→fire\| at fire | median **7.6 bps** (p10 2.8 → p90 12.6) |
| Poly entry price (favorite) | median **0.835** (0.54–0.97) |
| Binance dir@fire == realized close dir | **92.3%** |
| Realized WR | **96.2%** (1 loss = ETH where Binance reversed post-fire) |
| Markets | BTC 5m (22) + ETH 5m (4) only; no 15m, no SOL/XRP |

**Reading:** it is NOT a blind favorite-buyer. Every fire, Binance had already moved ~7.6bps the favorite's way by mid-window. It buys the **Binance-confirmed** side at a poly price (0.83) **below** the move's true conditional probability. Pure oracle-lag monetization, held to settlement.

This is the **same signal family** as our deployed momentum-alignment scalp (`g_lag_momentum_align`: lag-sign == binance-momentum-sign) — but a different regime: **mid-window + expensive favorite (0.55–0.90) + HOLD**, vs our scalp's **early + cheap (<0.55) + +60s exit**. Complementary, not duplicate.

## 2. Local validation (OOS, n=25,290 BTC/ETH 5m, Apr 22→Jun 11)

Script `directional/cyclops_signal_validate_2026_06_15.py`. For every canonical 5m slug: if Binance moved ≥THR bps (aligned) by offset t, what is P(close finishes same direction)? = the conditional WR the bot monetizes. EV computed at poly price 0.83 with winner-only fee `0.07·p·(1−p)`.

**Conditional WR rises monotonically with offset AND threshold** (base rate 49.8%):

| asset | off | thr(bps) | n | WR % | EV @0.83 /sh |
|---|---|---|---|---|---|
| btc | 120 | 5 | 4182 | 85.0 | +0.018 |
| btc | 120 | 8 | 2315 | 87.8 | **+0.046** |
| btc | 180 | 5 | 5149 | 90.7 | +0.076 |
| btc | 180 | 8 | 3025 | 93.7 | +0.106 |
| btc | 240 | 8 | 3566 | 97.6 | +0.145 |
| eth | 120 | 8 | 3211 | 87.5 | +0.044 |
| eth | 180 | 8 | 4002 | 92.8 | +0.096 |

**Cyclops's regime (off ~124s, move ~7.6bps) lands at ~btc 120/8 → local WR ≈ 88%.** Its live 96% over 5d is a hot streak above the 88% local expectation, but the **signal is confirmed +EV at the price it pays**. Below ~off 90 / thr 3–5, EV at 0.83 is **negative** — the edge requires waiting for enough Binance confirmation.

## 3. Where the edge actually lives (and the trap)

The EV table assumes a **constant 0.83 entry**. That is the load-bearing assumption:
- At off=240/thr=10, conditional truth is 98% → **fair** price is ~0.98. If poly has caught up and charges 0.95+, the +0.15 EV collapses to ~0. The "+0.15" is **overstated** wherever poly is efficient.
- The real, harvestable edge = **the gap between poly's favorite ask and the conditional truth**. Cyclops's own fills (median 0.83 for an ~88–94% true-prob favorite) are direct evidence that **poly DOES still lag at off 120–180s** → +5–11pp underpricing.
- This is exactly why our prior momo decode called naive favorite-hold the **"priced-in trap"**: when poly = truth, favorite-hold is the favorite-longshot knife-edge (Apr22–Jun8 −$0.28/tr). Cyclops escapes the trap **only** via the entry gate: fire when Binance is confirmed AND the favorite is still cheap (≤~0.90).

**So the strategy in one line:** *buy the Binance-confirmed favorite mid-window ONLY while poly's ask still lags the conditional truth; hold to resolution.* Discipline = price-gated entry, not blind favorite-buying.

## 4. Comparison to our stack

| | Our exit-scalp / momalign | **Cyclops (decoded)** |
|---|---|---|
| Signal | lag-sign == binance momentum | **same (align 100%)** |
| Offset | early (5–60s) | **mid (120–180s)** |
| Entry price | cheap (<0.55) | **favorite (0.55–0.90)** |
| Exit | +45/+60s time-sell | **HOLD to resolution** |
| Regime | early cheap mispricing | **confirmed favorite still lagging** |

→ Cyclops occupies an **entry band we do NOT currently trade** (mid-window, favorite, hold). Net-new candidate.

## 5. Caveats (GROUND-TRUTH)

1. **n=26, 5d, hot streak.** Live 96% WR will regress toward the local ~88% conditional WR at its regime. Lifetime wallet = −$210 (the old strategy); the new one has 5 days of evidence only.
2. **Edge = poly lag, unproven in $ locally.** The signal is validated, but $/trade depends on the entry-price gap, which needs **L25 book-walk** at the mid-window fire moment. Canonical L25 ends Jun 11 — testable on Apr22→Jun11 (does the favorite ask really stay ≤0.83–0.90 at off 120–180 after an 8bps Binance move?). **This is the decisive untested step.**
3. **Spread/fill on a 0.83 favorite is thin** — the EV is per-share; at ~3 shares/$2.6 the $/trade is small (~+$0.10–0.36). Capacity-limited.
4. **Favorite-hold reversal tail** — 8% of mid-window-confirmed favorites still reverse to close (the ETH loss). Full stake at risk each time; no stop.

## 6. DECISIVE RESULT — L25 $-backtest (fresh data Jun 1→Jun 15, RAN 2026-06-15)

Script `directional/cyclops_l25_backtest_2026_06_15.py`. Real poly entry via L25 book-walk ($1 notional, 1Hz), 0.07 winner-only fee, chainlink truth. **n = 2,961 BTC + 2,969 ETH 5m slugs** (data confirmed fresh to Jun 15 13:50).

| asset | thr | cap | n | WR % | entry_vwap | **gap_pp** | **$/trade** | sum_ask |
|---|---|---|---|---|---|---|---|---|
| btc | 5 | 0.88 | 794 | 76.3 | 0.748 | **+1.5** | **+0.0143** | 1.013 |
| btc | 8 | 0.88 | 546 | 78.9 | 0.777 | +1.3 | +0.0081 | 1.013 |
| btc | 8 | 0.90 | 581 | 79.5 | 0.784 | +1.1 | +0.0066 | 1.013 |
| eth | 5 | 0.90 | 835 | 71.4 | 0.741 | **−2.7** | **−0.0471** | 1.015 |
| eth | 8 | 0.83 | 509 | 73.1 | 0.739 | −0.8 | −0.0214 | 1.015 |

**The edge mostly evaporates with real prices:**
1. **The 13pp "lag" was 5d variance, not structure.** With true entry prices the conditional WR is **76–80% (BTC)**, not the 88–96% the klines-only proxy suggested. Cyclops paying 0.83 for a favorite that wins ~76–80% → real **gap ≈ +1.5pp on BTC, NEGATIVE on ETH (−1 to −3pp, poly OVER-prices)**. Its 96% WR over 26 trades was a hot streak (expected ~5–6 losses, got 1).
2. **$/trade ≈ breakeven (BTC) to negative (ETH).** BTC best +$0.0143/$1; **ex-top2 collapses to +$0.0062** (edge partly outlier-driven). ETH −$0.02 to −$0.05. 8/16 cells positive, all BTC, all thin.
3. **Optimistic by construction:** 1Hz L25 biases toward tight-book moments (convention warns this over-fills) → real 10Hz fills worse. And **tx cost ~$0.011/trade kills a +$0.006–0.014 edge** outright.
4. **Fill rate only ~34–37%** — ~63% of fired slugs had no fillable favorite book at the fire second. Capacity/execution-constrained.
5. **sum_ask ≈ 1.013–1.015** — overround small but real; favorite is **near-efficiently priced** mid-window.

**VERDICT: NOT a deployable edge.** This is the **favorite-longshot knife-edge / priced-in trap** the project already established (momo decode: favorite-hold Apr22–Jun8 −$0.28/tr). The poly favorite is ~efficient mid-window (gap +1.5pp BTC / negative ETH); net of realistic fills + ~$0.011 tx it is ≤0. **Do NOT clone Cyclops.** Its 5d +$11 is variance on top of a lifetime −$210.

### Residual nuance (not actionable yet)
BTC gap is **consistently +1.0–1.5pp across every thr/cap cell** (robust sign, n~800) — a *real but tiny* lag, just too small to monetize as a taker at $1 after tx. The only way it becomes interesting is **as a MAKER** (post the favorite bid below the lagging ask → fee $0 + rebate flips the thin gap positive) — but the b945 queue-sim already showed maker policies ≤0 here. Parked.

## 6b. SLUG SELECTOR decoded + edge RESCUED on BTC (RAN 2026-06-15)

Operator was right: there is a slug selector beyond the loose trigger. Cyclops actually trades **285 BTC + 4 ETH over 21d (~14/day), 26 in the last 5d** — but the *new* (last-5d) regime fires **mid-window (~120s), not the old late/small-move regime (offset 229s, ~1.6bps) seen over 21d.**

**Selector decode** (`wallet_hunt/cyclops_selector_decode_2026_06_15.py`, last-5d scope, fired vs signaling-not-fired):
- **`move_120` is the discriminator: fired +6.5bps vs universe +1.4bps** (4–5× more directional displacement by mid-window).
- **monotonic 90%** (no opposite >2bps excursion before fire), **moderate vol** (lower zmove 0.85 vs 1.12 — it does NOT chase outsized moves), slight trend-continuation (run_len≥1 55% vs 49%), mild TOD lean to 11–12 UTC.
- → the selector = *"binance has an early (by 120s), sustained, monotonic ~6bps move in one direction"*. That's why ~5/day not ~100/day.

**Selector L25 $-backtest** (`directional/cyclops_l25_selector_bt_2026_06_15.py`, fire@120 iff |move120|≥thr & monotonic, hold, real L25 entry, Jun1→Jun15):

| asset | thr | cap | n | WR % | entry | gap_pp | $/trade | ex-top2 |
|---|---|---|---|---|---|---|---|---|
| btc | 3 | 0.88 | 393 | 78.9 | 0.762 | **+2.7** | **+0.0179** | **+0.0139** |
| btc | 5 | 1.00 | 333 | 83.8 | 0.815 | +2.3 | +0.0148 | +0.0104 |
| btc | 8 | 1.00 | 196 | 86.2 | 0.839 | +2.4 | +0.0181 | +0.0130 |
| eth | 5 | 0.90 | 239 | 76.6 | 0.786 | −2.0 | −0.0350 | −0.0428 |

**The selector roughly DOUBLES the BTC edge vs the loose trigger** (gap +1.5→+2.5pp; ex-top2 +$0.006→+$0.013). On BTC it is **consistently positive across every threshold AND ex-top2 stays positive** — i.e. NOT outlier-driven, NOT the favorite-longshot trap. ETH stays negative (poly prices ETH efficiently/over).

### Revised verdict
- **BTC-5m monotonic-early-move favorite-hold IS a real (thin) edge.** ~WR 79–86%, entry 0.76–0.84, **gap +2.3–2.7pp**, **$/trade +$0.014–0.018**, ex-top2 +$0.010–0.014, n=200–400 over 14d.
- Net of ~$0.011 tx → **≈ +$0.003–0.007 per $1**; at ~5–13 BTC fires/day this is small but positive — matches Cyclops's actual realized (+$11/5d ≈ +$2.2/day on ~$13/day deployed).
- **ETH must be excluded** (negative). Cyclops's own 4 ETH trades / the 1 loss confirm it.
- Cyclops's 96% live WR is still a hot streak over the structural ~80%.

### Caveats before any capital
1. **1Hz L25 is optimistic** (convention: over-fills tight-book moments) → re-run at **native 10Hz** before trusting the +$0.015 magnitude; real edge likely thinner.
2. **No DSR** yet — consistent positive sign across thr∈{3,5,8} + positive ex-top2 is encouraging but not deflation-tested. Run DSR/CPCV on the BTC cell.
3. Fill rate only **29–36%** (favorite book often absent at fire second) — capacity-limited.
4. Edge is **BTC-only, thin, regime-dependent** — deploy as a **$1 shadow A/B** (selector ON vs OFF), judge by ≥200 live fires, not the backtest.

## 6c. NATIVE 10Hz + DSR (RAN 2026-06-15) — edge real in $ but FAILS deflation

`directional/cyclops_l25_selector_10hz_dsr_2026_06_15.py` — BTC only, `subsample_1hz=False`, snapshot nearest fire_us (±1s), batched load, self-contained DSR (Bailey & López de Prado), n_trials=16.

| thr | cap | n | WR % | $/trade | ex-top2 | per-trade Sharpe |
|---|---|---|---|---|---|---|
| 3 | 0.88 | 395 | 78.7 | +0.0143 | +0.0106 | 0.026 |
| 5 | 1.00 | 334 | 83.8 | +0.0130 | +0.0087 | 0.028 |
| 8 | 0.90 | 148 | 83.1 | +0.0153 | +0.0084 | 0.033 |
| 8 | 1.00 | 195 | 86.7 | **+0.0202** | +0.0150 | 0.049 |

**1Hz was ~20% optimistic** (thr3/cap.88 +0.0179→**+0.0143**) — exactly the convention warning. Positive $/trade **survives** at 10Hz for cap≥0.88; net of ~$0.011 tx ≈ **+$0.001–0.009/$1** (thin).

**DSR verdict (the decider):**
| cell | n | Sharpe | SR0(null) | **DSR** | skew | kurt |
|---|---|---|---|---|---|---|
| thr3 cap0.88 | 395 | 0.0265 | 0.0416 | **0.384** | −1.22 | 2.81 |
| thr5 cap1.00 | 334 | 0.0283 | 0.0416 | **0.406** | −1.60 | 4.01 |
| thr8 cap1.00 (best $) | 195 | 0.049 | 0.0416 | **0.538** | — | — |

**FAILS DSR (0.38–0.54 « 0.95).** Per-trade Sharpe (0.026–0.049) is at or below the multiple-testing null (SR0=0.042); the favorite-hold's **negative skew (−1.2 to −1.6)** — wins small, loses full stake — sinks it. The 80–87% WR masks a fat left tail. ex-top2 staying positive (+$0.015) is mildly reassuring but does not rescue DSR.

### FINAL VERDICT
- Cyclops's selector strategy is **real but marginal and statistically fragile**: thin positive $ at realistic 10Hz fills (+$0.012–0.020 gross, ~breakeven-to-thin net of tx), **but does not pass deflation** (DSR ≤0.54). Consistent with the wallet's actual profile (lifetime −$210, recent +$11 = hot streak, not a robust money-printer).
- **Do NOT deploy real capital on the backtest.** The negative skew + no-stop means full-stake loss tail.
- **Only valid path:** $1 live **shadow A/B** (selector ON vs OFF), judge by **≥200 live fires + CI>0**, never the backtest (project standard). BTC-only; ETH excluded (dead).
- The decode itself is solid and banked: selector = *early (by 120s), monotonic, ~6bps binance move → buy that favorite, hold*. It just isn't a deflation-significant edge at our fee/skew.

## 7. Next step

Build the **L25 mid-window favorite-hold backtest** on canonical Apr22→Jun11:
- For each BTC/ETH 5m slug, at first offset t∈[90,180]s where Binance moved ≥{5,8}bps aligned, **walk the L25 book** for the favorite ask (`book_walk_fill`, native 10Hz, cross-token spread filter).
- Gate: only enter if ask ≤ {0.83, 0.88, 0.90} (the lag condition).
- Hold to chainlink resolution; PnL via `engine_v2` 0.07 winner-only.
- Report $/trade, WR, fill-rate, and **ask-vs-conditional-truth gap** (does poly actually lag?). DSR + ex-top2.
- If the favorite ask ≈ conditional truth (no gap) → edge is illusory (priced-in trap). If ask lags by ≥5pp at ≤0.90 → real, deploy as a new mid-window-hold sleeve A/B vs our exit-scalp.

## Files
- `wallet_hunt/cyclops_decode_5d_2026_06_15.py` (per-entry Binance decode)
- `directional/cyclops_signal_validate_2026_06_15.py` (local n=25k conditional-WR validation)
- `wallet_hunt/cache/_cyclops_5d/activity_raw.json` (raw)
- `reports/HANDOFF_CYCLOPS_5D_2026_06_15.md` (5d activity handoff)
