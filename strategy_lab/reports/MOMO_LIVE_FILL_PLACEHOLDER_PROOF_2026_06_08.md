# PROOF: btc_15m_momo_HOLD_f7 live "profit" is a fake-fill artifact (2026-06-08)

**Operator hunch:** "the live shadow shows something not true." CONFIRMED — the live `entry_price` is a ~0.50
PLACEHOLDER, not the real fill. The live PnL is fictitious. The sleeve is favorite-longshot breakeven-to-negative.

## Method
71 live `poly_updown_btc_15m_momo_HOLD_f7` fires (May21–Jun2), slug via `markets.condition_id`. For each, triangulate
the entry price three ways at fire = suffix+120: (1) live `entry_price` (what the live PnL used), (2) canonical L25
ask-walk (my backtest engine), (3) ACTUAL executed Polymarket trades in [W+60,W+180] (ground truth).
Scripts: `momo_engine_fidelity_2026_06_08.py`, `momo_engine_triangulate_2026_06_08.py`.

## Result — decisive
| metric | value | meaning |
|---|---|---|
| L25 snapshot gap to fire | median 1s, p90 20s | engine reads a FRESH book (not stale) |
| **corr(L25_ask, real executed trades)** | **0.950** (mean diff 0.039) | the L25 book = the real market; my engine is faithful |
| **corr(live_entry, real executed trades)** | **0.116** (mean diff 0.122) | live entry tracks NOTHING real |
| mean live_entry / l25_ask / real_trade | 0.495 / 0.504 / 0.492 | aggregate matches by averaging only |

Examples (live_entry vs REAL traded vs L25):
```
05-23 DOWN: live 0.46 | real 0.92 | L25 0.96   (462 real trades)
05-27 DOWN: live 0.47 | real 0.11 | L25 0.12
06-02 DOWN: live 0.50 | real 0.83 | L25 0.87
06-01 DOWN: live 0.47 | real 0.17 | L25 0.16
```
live_entry pinned ~0.46–0.51 while the token really traded 0.11–0.96. The L25 (corr 0.95) IS the real book.

## Conclusion
- **Live `entry_price` (May21–Jun2) is a ~0.50 placeholder → the live PnL is fake.** Winners (≈76% of momentum
  favorites) booked at fake-cheap 0.50 generated the fictitious +$3–4/tr. Real fill ≈ 0.77 → tiny/negative.
- **Reconciles everything:** placeholder era (May21–early Jun) = fake +$4.19/tr; after the fill bug was fixed
  (mid-June, real entries 0.65–0.9) live went NEGATIVE (−1.79/tr last 10) = the corrected backtest's verdict.
- **My corrected L25-fill backtest is the TRUTH** (engine now proven: corr 0.95 vs real trades, 1s freshness):
  favorite-longshot, **breakeven-to-negative** (BTC −0.28/tr at the real ~0.77 fill). HIGH WR != edge.
- **The engine was right; the LIVE entry_price was the broken thing.** Do NOT trust momo/momo_v2 shadow PnL.

## All-data backtest (verified engine) — favorite-longshot breakeven knife-edge
`bt_momo_btc15m_febmar_2026_06_08.py` (Feb fill = real executed trades, validated = book corr 0.95) +
`bt_momo_hold_f7_allcoins_2026_06_08.py` (Apr–Jun, L25 $25 walk). ws_s=W, fire W+120, q90+F7, 0.07 fee, HOLD.
| period | n | WR | $/tr | vwap | breakeven-WR @ vwap | note |
|---|---|---|---|---|---|---|
| Feb21–Mar24 (out-of-regime) | 147 | 79.6% | +1.79 | 0.734 | ~74.4% | +5pp → marginally +, t=1.53 (ns); trade-median fill slightly optimistic vs taker ask |
| Apr22–Jun8 | 243 | 76.5% | −0.28 | 0.77 | ~78% | −1.5pp → breakeven-neg |
**Sits ON the breakeven line** — profit flips sign with a couple points of WR vs the entry-vwap breakeven. No robust
edge; regime-dependent; neither period significant. The high WR (76–80%) is favorite-longshot, exactly the breakeven
WR for buying the favorite at 0.73–0.77.

## Implication
Every momo/momo_v2 HOLD shadow sleeve PnL booked during the placeholder era is fictitious. The "profitable momo"
reads across the fleet are this artifact. Re-baseline all momo shadow PnL on the real L25 fill (or post-fill-fix
live only). Flag the paper-fill placeholder bug to the TV agent (entry_price must record the real book ask, not ~0.50).
