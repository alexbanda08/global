# TV Deploy Spec — Hyperliquid V52 + XSM shadow loop (light up the 6 HL cards)

**Date:** 2026-06-09
**For:** TV agent (VPS3 production engine owner)
**Status:** SHADOW ONLY, $0 capital. Goal: populate the dashboard's `SHADOW (6)` HL cards.
**Reference impl (port this, like you ported `shadow_engine/`):** `shadow_v52/` in repo root.

---

## 0. Problem statement

The operator dashboard shows a `SHADOW (6)` group with cards **V52-BTC, V52-ETH, V52-SOL,
V52-LINK, V52-AVAX, (XSM)** — all `bundle: none`, `SIGNAL FLAT`, `CONFIDENCE —`, no activity.

Root cause: those 6 cards exist in the UI but **no engine loop feeds them**. The TV engine
today runs only Polymarket loops (`poly_updown_loop`, `poly_maker_loop`). V52/XSM are
**Hyperliquid 4h perpetual** strategies — a different surface (HL perps, not Poly slugs).
`bundle: none` = no sleeves attached to the cards.

This spec defines a new **`hl_perp_loop`** that computes the V52 + XSM signals on HL 4h bars,
attaches sleeves to each card, and emits per-card SIGNAL/CONFIDENCE + fires so the dashboard
lights up.

**A fully-working reference producer already exists and runs hourly locally** — port it, don't
reinvent. See §6.

---

## 1. The 6 cards = per-coin bundles of 9 sleeves

| Card | Coin | Bundle (sleeves) | Each sleeve weight |
|---|---|---|---|
| **V52-BTC** | BTC | STF_BTC | 0.12 |
| **V52-ETH** | ETH | CCI_ETH, MFI_ETH | 0.12, 0.10 |
| **V52-SOL** | SOL | STF_SOL, MFI_SOL | 0.12, 0.10 |
| **V52-AVAX** | AVAX | STF_AVAX, LATBB_AVAX, SVD_AVAX | 0.12, 0.12, 0.10 |
| **V52-LINK** | LINK | VP_LINK | 0.10 |
| **V52-XSM** | 9-coin basket | V24 multi_filter | (separate book, 0% live) |

Fix `bundle: none` by attaching these sleeve lists to the cards.

---

## 2. Engine architecture

Add `backend/app/engine/hl_perp_loop.py` — **bar-driven, 4h cadence** (NOT the slug/event
cadence of the poly loops). Runs once per closed 4h bar (UTC 00/04/08/12/16/20) + a small delay.

```
hl_perp_loop (every 4h bar close):
  1. Pull HL candleSnapshot 4h + fundingHistory for BTC/ETH/SOL/AVAX/LINK
     (ingest = reference strategy_lab/ingest_hyperliquid.py; incremental append).
     Also pull Binance Vision 4h for ADA/XRP/BNB/DOGE (XSM 9-coin universe).
  2. For each of the 9 V52 sleeves: compute signal + gate + exit state on the latest bar.
  3. For XSM: evaluate the multi_filter + target basket.
  4. Aggregate sleeves -> 6 per-card SIGNAL/CONFIDENCE (see §4).
  5. Emit card state + any fires to the shadow store the dashboard reads.
```

Coexists with the poly loops in the engine TaskGroup. Pure shadow: never submits an HL order.

---

## 3. The 9 V52 sleeve signals (EXACT — from the validated reference)

Data per sleeve: HL 4h OHLCV + per-4h funding. Exits: `EXIT_4H = tp 10 ATR / sl 2 ATR /
trail 6 ATR / max_hold 60 bars`; V41/V45 variants use regime-adaptive `REGIME_EXITS_4H`
(HMM, `train_frac=0.30`, seed=42). All signals are causal (decide at bar close, fill next open).

| Sleeve | Coin | Signal | Variant | Gate |
|---|---|---|---|---|
| STF_BTC | BTC | SuperTrend(10, 3.0) flip + EMA(200) regime | V45 (vol>1.1×20MA) | FUND_Z<2 |
| CCI_ETH | ETH | CCI(20) extreme cross ±150, ADX(14)<22 | V41 (regime exits) | FUND_Z<2 |
| STF_SOL | SOL | SuperTrend(10, 3.0) flip + EMA(200) | baseline | FUND_Z<2 |
| STF_AVAX | AVAX | SuperTrend(10, 3.0) flip + EMA(200) | V45 (vol>1.1×20MA) | FUND_Z<2 |
| LATBB_AVAX | AVAX | Lateral BB(20, 2.0) fade, ADX(14)<18 | baseline | FUND_Z<2 |
| MFI_SOL | SOL | MFI(14) extreme 25/75 | V41 (regime exits) | ATR_NOTOPVOL |
| VP_LINK | LINK | Volume-profile rotation (win=60, n_bins=15) | baseline | ATR_NOTOPVOL |
| SVD_AVAX | AVAX | Signed-volume divergence (lookback=20, cvd_win=50) | baseline | ATR_NOTOPVOL |
| MFI_ETH | ETH | MFI(14) extreme 25/75 | baseline | ATR_NOTOPVOL |

**Signal source code (port verbatim):**
- `strategy_lab/run_v30_creative.py` → `sig_supertrend_flip`, `sig_cci_extreme`
- `strategy_lab/run_v29_regime.py` → `sig_lateral_bb_fade`
- `strategy_lab/strategies/v50_new_signals.py` → `sig_mfi_extreme`, `sig_volume_profile_rot`, `sig_signed_vol_div`
- Simulator/exits: `strategy_lab/eval/perps_simulator_funding.py` (`simulate_with_funding`) + `perps_simulator_adaptive_exit.py` (`REGIME_EXITS_4H`)
- Regime: `strategy_lab/regime/hmm_adaptive.py` (`fit_regime_model`)

**Gate definitions (EXACT):**

```python
# FUND_Z<2  (V41-family sleeves: STF_BTC, CCI_ETH, STF_SOL, STF_AVAX, LATBB_AVAX)
fund_4h = funding_per_4h_bar(coin, df.index)          # sum of hourly HL funding per 4h bar
mu = fund_4h.rolling(500, min_periods=100).mean()
sd = fund_4h.rolling(500, min_periods=100).std()
z  = (fund_4h - mu) / sd.replace(0, np.nan)
fund_ok = (z.abs() < 2.0).fillna(True)                # entries allowed where True

# ATR_NOTOPVOL  (volume diversifiers: MFI_SOL, VP_LINK, SVD_AVAX, MFI_ETH)
tr  = pd.concat([(h-l), (h-c.shift(1)).abs(), (l-c.shift(1)).abs()], axis=1).max(axis=1)
atr = tr.rolling(14).mean()
pct = atr.rolling(500, min_periods=100).rank(pct=True)
atr_ok = (pct < 0.80).fillna(True)                    # skip entries when ATR pct >= 0.80

# V45 variant adds: active = volume > 1.1 * volume.rolling(20).mean()  (AND-ed into entries)
```

---

## 4. Card-level SIGNAL + CONFIDENCE (the dashboard fields)

Per coin card, aggregate its bundle's sleeves (port `shadow_v52/tv_cards_feed.py`):

```
dir_i  = +1 if sleeve i currently LONG, -1 if SHORT, 0 if flat
net    = sum(weight_i * dir_i)  over OPEN sleeves in the bundle
total  = sum(weight_i)          over the whole bundle
SIGNAL     = LONG if net>0, SHORT if net<0, else FLAT
CONFIDENCE = round(100 * |net| / total)        # 0..100, share of bundle weight aligned+open
```
If a sleeve has a fresh fire on the just-closed bar (pending entry at next open), the card
SIGNAL reflects that pending action and CONFIDENCE uses that sleeve's weight.

---

## 5. XSM card (V24 multi_filter)

9-coin cross-sectional momentum (BTC/ETH/SOL/LINK/ADA/XRP/BNB/DOGE/AVAX), 4h, weekly rebalance.
Long top-4 by 14d momentum ONLY when ALL pass, else CASH:
1. BTC close > BTC 100d-MA
2. BTC 50d-MA rising (`btc_ma_fast[i] >= btc_ma_fast[i-24]`, 4h bars)
3. breadth ≥ 5/9 coins above own 50d-MA

Card: SIGNAL = LONG (basket) if filter ACTIVE else FLAT; show breadth + the 3 filter booleans +
target basket. **0% live allocation** until the HL coin universe widens past the current 5/9.
Reference: `shadow_v52/xsm_shadow.py`. Source logic: `strategy_lab/v23_low_dd_xsm.py` mode="multi_filter".

---

## 6. Reference implementation (ALREADY WORKING — port it)

A complete shadow producer runs hourly on the research box and emits exactly the card payload
the dashboard needs. Port these into the engine (decision logic is truth; integration is yours):

| File | Role |
|---|---|
| `strategy_lab/hl_research_2026_05_26/v52_v24_audit/v52_shadow_runner.py` | 9 V52 sleeves: signal+gate+exit+fire detection, writes positions + fires ledger |
| `shadow_v52/xsm_shadow.py` | XSM multi_filter evaluator + target basket |
| `shadow_v52/tv_cards_feed.py` | **Aggregates → the 6-card dashboard payload (`_tv_cards_feed.json`)** ← the target schema |
| `shadow_v52/build_sleeve_cards.py` | Per-sleeve cards (spec + validated metrics + live status) |
| `shadow_v52/shadow_tick.py` | The 4h cadence wrapper (refresh data → run all → emit feed) |
| `strategy_lab/ingest_hyperliquid.py` | HL candleSnapshot + fundingHistory ingest (incremental) |
| `strategy_lab/util/hl_data.py` | `load_hl`, `funding_per_4h_bar` |

### Target card payload (`_tv_cards_feed.json`) — reproduce this shape

```json
{
  "card": "V52-AVAX", "fleet": "V52", "venue": "hyperliquid_perp", "coin": "AVAX", "tf": "4h",
  "bundle": ["STF_AVAX","LATBB_AVAX","SVD_AVAX"],
  "signal": "LONG", "confidence": 29,
  "open_positions": [{"sleeve":"SVD_AVAX","direction":"LONG","entry_ts":"...","unrealized_pct":...,"weight":0.10}],
  "pending": [],
  "n_fires": 10, "last_fire": "2026-06-01T04:00:00+00:00",
  "recent_fires": [{"sleeve":"SVD_AVAX","dir":"SHORT","entry_ts":"...","exit_ts":"...","reason":"TP","ret_pct":14.9,"paper_pnl":37.2}],
  "data_end": "2026-06-09T12:00:00+00:00"
}
```

Card content requested by operator: **live state + recent fires + spec** — all present above.

---

## 7. Fire / event logging (so the dashboard reads it)

Mirror the maker-sleeve logging pattern (`/var/log/tv/...` daily CSV + lifetime aggregation,
per `TV_AGENT_FIX_DASHBOARD_CUMULATIVE_PNL_SPEC.md`). Per HL sleeve, log each entry/exit with:
`ts_us, sleeve_id, card, coin, direction, entry_price, exit_price, reason, bars_held, ret_pct,
paper_pnl_usd, funding_paid, fees`. Dashboard shows today + lifetime per card (sum over bundle).

---

## 8. Honest status / caveats (operator must know)

- All 9 V52 sleeves are **genuinely FLAT most of the time** right now — 2026 is V52's weak
  regime (alt realized-vol −30%, funding ⅓ of 2024). Fires are sparse; a card reads FLAT until
  a 4h signal triggers. The local reference logged **46 fires over the last 60 days** (proof the
  path works), but the fleet is often between trades. "No activity" ≠ broken.
- XSM is **correctly in CASH** (filter passes only ~4.5% of 2026 bars; breadth 1/9 today).
- **SHADOW ONLY, $0.** Promotion gates before any HL capital (per V52 deployment notes): ≥4 weeks
  shadow, aggregate Sharpe > 1.2, funding accrual reconciles ±5%, no sleeve hits −12% DD.
  STF_BTC is brand-new (never live) — watch closest. XSM stays 0% until >5/9 coins on HL.

---

## 9. Checklist

```
[ ] Add hl_perp_loop.py (4h cadence) to engine TaskGroup
[ ] Port the 6 signal functions + 2 gates + simulate_with_funding + HMM regime
[ ] Wire HL data ingest (candleSnapshot 4h + fundingHistory; Binance 4h for ADA/XRP/BNB/DOGE)
[ ] Attach the 5 per-coin bundles + XSM to the dashboard cards (kills `bundle: none`)
[ ] Implement §4 card SIGNAL/CONFIDENCE aggregation (port tv_cards_feed.py)
[ ] Log fires per §7; dashboard shows today + lifetime per card
[ ] Verify against the reference: card states match `shadow_v52/_tv_cards_feed.json`
[ ] Confirm SHADOW mode ($0), no HL orders submitted
```

---

**Bottom line for the operator:** the cards are flat because nothing feeds them yet. This spec
attaches the 9 V52 sleeves (as 5 coin-bundles) + XSM to the cards and defines the 4h engine loop
that computes their signals. The full producer already runs locally and emits the exact card
payload — port it. Once wired, cards flip LONG/SHORT with a confidence score whenever a 4h
signal fires (e.g. V52-AVAX is LONG conf 29 right now in the reference feed).
```
