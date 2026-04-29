# Synthetic Covered Call: Leveraged Crypto Futures + Polymarket Binaries

**Date:** 2026-04-28  •  Status: Greenfield design (NOT reusing any V## sleeve)

---

## 1. The Analogy — Schwab Covered Call → Crypto

A covered call:
- **Long 100 shares** of underlying (you own the upside).
- **Sell 1 OTM call** at strike K, expiry T → collect premium P.
- Payoff at T:
  - Stock ≤ K → keep stock + keep P. (Best zone: chop / mild rally.)
  - Stock > K → stock called away at K, you keep K − cost_basis + P. **Upside capped at K + P.**
- Risk shape: bounded gain, partial downside cushion = P, full exposure below S₀ − P.

**Crypto translation:**

| Schwab leg | Crypto leg | Notes |
|---|---|---|
| 100 shares of stock | **Long BTC perpetual future, leveraged** (1–3×) | "Cover" = the underlying long |
| Sell 1 OTM call @ strike K, expiry T | **Sell YES on Polymarket "BTC ≥ K by T"** | Binary digital, max payout $1 |
| Premium received | YES sale price (e.g. $0.40) | Max gain on overlay = sale_px |
| Strike K | The Polymarket question level | Pick from listed strikes |
| Expiry T | Polymarket resolution time (5m / 15m / 4h / 24h) | Tenor menu = options-chain analog |
| Assignment (stock called) | YES resolves true → pay out $1, settle | No actual share transfer; cash settle |

Key difference vs. vanilla call: Polymarket is **digital** (1 or 0), not linear. Above the strike, perp keeps gaining linearly while binary loss is bounded at (1 − sale_px). So unlike a true covered call, **upside is *not* capped** — only the binary leg has bounded loss. This is structurally favorable: the synthesis is "long perp + tiny short digital" rather than a hard cap.

---

## 2. Strategy: "Synthetic Covered Yes"

### 2.1 Core idea
Hold a leveraged long BTC perp. Continuously sell short-dated Polymarket "BTC up by T" YES contracts when their implied probability is **above** a fair-value estimate (premium is rich). The perp acts as the cover: if BTC rallies hard enough that the YES resolves true, perp PnL exceeds the binary payout.

### 2.2 Three legs, three time-frames

**Leg A — Cover (the "stock"):**

Two flavors. Leverage is **matched to the binary's resolution window**, not picked in the abstract. Short-tenor binaries get short-duration high-lev scalps; long-tenor binaries get a low-lev hold.

| Tenor of paired binary | Perp leverage | Holding period | Why it's safe |
|---|---|---|---|
| **5m markets** | **60–70×** | minutes (≤ resolution) | A 1.0–1.5% adverse move liquidates, but BTC rarely moves >0.4% in 5m outside vol shocks. Sized so liquidation = ≤0.8% equity. |
| **15m markets** | **40–60×** | ≤ 15m | Same logic, slightly wider buffer. Normal 15m range ≈ 0.3–0.7%. |
| **4h markets** | 3–5× | hours | Conventional swing leverage. |
| **24h+ markets** | 1–2× | core hold | Funding-aware; the original "I own BTC, writing calls" mode. |

**Hard rule:** the perp position **is not a core hold** in the high-lev modes. It opens with the binary, closes with the binary's resolution (or earlier on stop). Lifetime ≤ tenor. No overnight 70× exposure. Ever.

**Sizing math for high-lev tier (5m / 15m):**
- Cap **liquidation loss per scalp at 0.8% of equity**.
- At 60× lev, liquidation distance ≈ 1.5% (after fees/maint margin). So position notional = 0.008 × equity / 0.015 ≈ **0.53× equity** committed margin → about $1 of equity yields $30 of notional after the lever.
- Concurrent high-lev scalps: max 2 simultaneously → ≤ 1.6% equity at risk in fast lane.

**Entry trigger for high-lev cover:**
- Only opened *jointly* with a Polymarket short-YES sale on the same tenor. The cover is hedging the binary, not a standalone trade.
- Direction = same side as the binary you're shorting (sold UP-YES → long perp; sold DOWN-YES → short perp).
- Stop-loss is mandatory: hard stop at 0.6× the liquidation distance (e.g. 0.9% adverse for 60× lev). Bracket the entry — never let the exchange liquidate you.

**Funding-rate guard (24h tier only):** if 8h funding > +0.05% (longs pay heavily), shave to 1× until it normalizes. Irrelevant for 5m/15m scalps — funding accrues per 8h, immaterial in minutes.

**Leg B — Premium harvest (the "call"):**
- Sell YES on Polymarket BTC up/down binaries at three tenors:
  - **5m** markets: pure noise-decay. Sell when implied UP-prob ≥ 0.55 and realized 5m vol implies ≤ 0.50.
  - **15m** markets: slightly larger size, same mispricing logic.
  - **4h** markets: structural — sell when 4h question is at-the-money but realized hourly vol < implied.
- Strike selection: prefer **OTM by 0.5–1.5σ** of realized hourly vol (the "30–40 delta call" of the chain).
- Sizing per question: max loss ≤ 0.5% equity. With YES sold at $0.45 (loss = $0.55), size = 0.005 × equity / 0.55.
- Tenor caps: 5m ≤ 1% equity at risk concurrent, 15m ≤ 1.5%, 4h ≤ 2%. Total prediction sleeve ≤ 4% live risk.

**Leg C — Tail hedge (the "protective put" — optional):**
- Buy NO on a far-OTM crash question ("BTC ≤ −5% in 24h") periodically when premium is cheap (NO < $0.05 implies <5% disaster prob).
- Funded out of premium harvested in Leg B.
- Protects the leveraged perp from liquidation wicks.

### 2.3 Fair-value model for premium harvest
Polymarket YES on "BTC ≥ K at T" has fair price ≈ Φ(d) where d depends on log(S/K), realized vol, and time to T (Black-style). Compute **realized vol from last 24h of 1m bars**, plug in, compare to live YES bid. Sell only when bid − fair_value ≥ **edge buffer**:
- 5m markets: ≥ 8 cents.
- 15m markets: ≥ 6 cents.
- 4h markets: ≥ 4 cents.

The buffer covers Polymarket fees, slippage, and oracle/resolution noise.

### 2.4 Position management
- **Hold to resolution by default.** Theta is the friend on a short binary.
- Close early if YES halves → take 50% profit, redeploy.
- Close early if YES doubles → cut loss (event probably re-rated, model was wrong).
- **Roll** at expiry: cash from resolved markets is recycled into the next tenor's sells.

### 2.5 Risk gates
- **Liquidation guard on perp:** if mark price drops 12% from entry at 2× lev, close half regardless of overlay state.
- **Combined drawdown kill:** −20% account equity in any 30-day window → stop overlay, leave perp at 1×.
- **Polymarket liquidity guard:** never take size that exceeds 5% of question's 24h volume.
- **Correlation tail check:** if ≥ 3 short-YES positions are simultaneously > 0.50 marked-to-market loss, halt new sells until expiries flush.

---

## 3. Why this can work (edge thesis)

1. **Retail bias on prediction markets.** Polymarket BTC up/down books are dominated by directional retail. They overpay for "BTC up" YES during rallies and "BTC down" YES during dumps — same overpay-for-momentum pattern that makes covered-call writing profitable on hot single-names.
2. **Vol-risk premium at short tenors.** 5m and 15m binaries price implied vol higher than realized vol delivers, especially in chop regimes. Selling vol harvests this gap.
3. **The cover is leveraged + carries native return.** Unlike Schwab where the stock is unlevered, the perp gives you 2× exposure to BTC drift — historically positive — *while* the overlay throws off premium. Two return streams stacked.
4. **Asymmetric loss cap on the call leg.** Worst case per-question is bounded ($1 − sale_px). Perp's worst case is bounded by liquidation engineering. No unbounded short-vol blow-up like options gamma.

---

## 4. Worst-case stress tests

### 4.1 Long-tenor / low-lev sleeve (24h binaries, 2× perp)

| Scenario | Perp PnL (2×) | Overlay PnL | Net |
|---|---|---|---|
| BTC +10% in 1h | +20% sleeve | 4 concurrent UP-YES at $0.50 pay out → −2% | **+18%** ✅ |
| BTC −10% in 1h | −20% sleeve | UP-YES expires worthless → +2% | **−18%** ❌ |
| BTC chop ±1% over 24h | ~0% | Short-tenor YES decays → +3–5% | **+3–5%** ✅ ideal |
| Flash-wick −15% then recovery | Liq-guard halves sleeve at −12% | Leg C tail hedge fires | ~−10% contained |

### 4.2 Short-tenor / high-lev sleeve (15m binary, 60× perp)

Per-scalp position. Cover is paired 1:1 with one short-YES sell.

| Scenario | Perp (60×, hard stop @ 0.9%) | Short YES @ $0.55 (sized 0.5% equity max-loss) | Net per scalp |
|---|---|---|---|
| BTC +0.5% in 15m, ends above strike | +30% on margin, $0.27 equity gain on a 0.53× equity notional → **+~16% equity** if held; but binary resolves YES → −0.5% equity | mixed → in practice take perp profit at +0.5% target = **+8% equity** | strongly positive |
| BTC +0.3% in 15m, ends just below strike | +18% on margin, scalp closes at expiry → **+~9.5% equity** | YES expires worthless → +0.5% premium kept | **+~10%** ✅ best case |
| BTC −0.3% in 15m | scalp at adverse, but inside stop → close manually at expiry, ~−9.5% on margin → **−~5% equity** | YES expires worthless → +0.5% premium | **−4.5%** moderate loss |
| BTC −0.9% in 15m (stopped out) | Hard stop fires → **−0.8% equity** loss capped | YES expires worthless → +0.5% premium | **−0.3%** ✅ trivial |
| BTC −1.5% in 15m flash | If stop slipped past, liq triggers → **−0.8% equity** (liq cap by sizing) | YES expires worthless → +0.5% premium | **−0.3%** ✅ engineered cap |
| BTC +1.5% in 15m blowoff | Stop never hits, scalp wins ~+1% on 0.53× notional → **+~50% on margin / +0.5%? ** wait — see math note | YES resolves true → loss = 0.5% equity | net depends on net notional |

**Math note:** at 60× lev with 0.53× equity *notional* (i.e. 0.0088× equity *margin*), a +1.5% spot move = +1.5% × 0.53 = **+0.8% equity** on the perp side, vs. −0.5% equity on the binary side = **+0.3% equity net**. The asymmetry means: capped losses on adverse moves, capped-but-positive on favorable moves. Each scalp is a tightly-bounded bet, not a moonshot.

### 4.3 The real risk in high-lev mode
**Slippage past the stop during low-liquidity wicks.** A 70× position with a 0.9% stop assumes the stop fills — in a 0.3% gap-down on thin venue, you can lose 1.5% before the bracket triggers. Mitigations:
- Run the perp on a deep venue (Binance, Bybit) not a low-liquidity DEX.
- Use **limit-stop** brackets, not market stops, accepting the small chance of unfilled stops in exchange for no slippage blowups.
- Cap concurrent high-lev scalps at 2 — never run a portfolio of leveraged tinder-boxes.
- **The binary itself is the secondary stop:** even if perp loss runs to 0.8% equity, the YES premium recouped at expiry trims a few bps back.

---

## 5. Build & validation plan

1. **Data**: pull Polymarket BTC binary tick history (questions, books, resolution outcomes). Pair with 1m BTC perp OHLCV + funding.
2. **Fair-value calibration**: fit realized-vol → implied-prob curve on 5m/15m/4h binaries. Measure premium-decay alpha.
3. **Walk-forward backtest**: IS 12 months, OOS most-recent 6 months. Three legs combined.
4. **Pass criteria**:
   - Combined Sharpe ≥ 1.5
   - Max DD ≤ −20%
   - Overlay incremental Sharpe ≥ 0.5 over perp-only baseline
   - Tail-hedge cost < 30% of overlay premium income
5. **Paper trade** 60 days. Live ramp at 10% target size.

---

## 6. Open design questions

- Polymarket book depth at 5m tenor — can it absorb meaningful notional? Empirical scrape required.
- Choice of futures venue — Hyperliquid (low fees, on-chain, isolated margin) vs. Deribit (deeper book) vs. Binance perps. Affects funding and liquidation mechanics.
- Better strike selection: ATM (max gamma, max premium) vs. 1σ-OTM (lower hit rate, smaller payout-on-loss). Backtest decides.
- Should Leg C use Polymarket NO contracts or out-of-the-money put options on Deribit? Deribit puts give linear hedge, Polymarket NO is cheaper but binary.
