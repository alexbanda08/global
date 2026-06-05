# STRATEGY MAP — everything we've tried (2026-06-03)

Consolidated from 6 category maps (read those for detail): `01_directional`, `02_maker_lp_arb`,
`03_wallets`, `04_sleeves_families`, `05_engine_fidelity`, `06_exit_sizing_risk`.
~620 reports mapped. Purpose: stop repeating dead ends; aim new research at the gaps.

## The meta-conclusion (why most of it died)
**The Polymarket crypto up-down PRICE is a near-optimal out-of-sample probability estimator.** Re-confirmed
~10× and now sealed by the Synth test (market Brier 0.221, beats every model + coinflip in all 6 cells).
⇒ **There is NO reproducible directional edge in price/flow data.** Profitable wallets win on **execution**
(sub-second maker queue + relay settlement we can't match), **private slug-selection signals** (invisible in
canonical data — F2 cluster), or **domain forecasting** (weather nowcast). Not on prediction we can copy.

## What SURVIVED (the short list)
| edge | status | catch |
|---|---|---|
| **Intra-window EXIT-SCALP** (buy lag-taker <0.55, SELL on book +60s) | EDGE, 16 shadow sleeves LIVE-shadow | fwd OOS still flat (n<76) → needs ≥200 live fires + CI>0 |
| **Oracle-lag LAGV2 / clbasis_rel BTC-5m** | EDGE-LIVE (anchor edge) | ~2/day; user already passed |
| **Cyclops S7 X1** composite | EDGE-VALIDATED, paper-deploy ready | fragile n=36 |
| 4 EMA/trstack 15m-down sleeves (t≥2) | EDGE in shadow | fleet net is −$25.4k; spread-filter/fill caveats |
| **Mint-and-sell V3** (maker) | paper-edge validated | NOT deployed; per-fire breakeven, slug-agg positive |
| **LP-rewards farming** | active research, 232 targets | ~10% APR ceiling; needs quoting bot + live validation |
| Exit/risk techniques: info-stop (≥10bps), confidence-sizing, signal-driven exits (SELL/HEDGE_REVERT_5) | HELP | execution-side only, not an entry edge |

## What's DEAD (do not re-run)
- **Directional price/flow:** momentum, ema-slope, favorite/underdog, fade-momentum, flow-imbalance, RSI,
  BSM/N(d2) fair-value, VPIN/CVD, multi-venue & cross-exchange lead-lag, funding/OI, moneyness_t — all
  priced-out (WR≠edge; entry vwap already prices the move; net-negative after fees).
- **Symmetric maker-arb (ACC-H/M, MAS):** survivorship bias — uncensored −$0.41 to −$3.63/slug. Hard dead.
- **Covered-call, buy-wait-hedge-lock, deep gate-stacking:** no edge / no lock (UP+DOWN sum ~1.30).
- **Wallet mimicry:** 0 of ~30 decoded wallets yielded a reproducible+deployable trigger OOS.
- **Exit:** fixed/trailing price stops always hurt on binaries; HEDGE_LATE hurts winner sleeves.

## ⬜ WHITE-SPACE / UNTESTED (seeds for new research)
1. **Cross-venue arbitrage** — Polymarket vs **Kalshi** (we trade live) vs **Limitless** (Synth exposes both):
   same event, different price → lock the spread. Never systematically tested.
2. **Cross-slug term-structure arb** — same asset 1m/5m/15m/hourly up-down must be internally consistent
   (vol scaling); misprice between tenors = arb. Untested.
3. **Directional-tilted ONE-SIDED LP** — combine a weak lean (favorite base-rate / our signals) with LP
   rewards: post one-sided (÷3 score per MuddyRC) so you only fill the side you'd want + collect rewards.
   No backtest yet.
4. **Domain forecasting on NON-crypto markets** — weather nowcast is *proven profitable* (HighTempTation
   +$7.8k); same playbook untested for sports, economic-data releases, elections. Needs own model/feed.
5. **Partial scale-out exit** (sell half mid-window, hold half); ORACLE_CUT (just misses CI>0); HEDGE_LATE
   on ETH/SOL marginal sleeves (only BTC confirmed).
6. **New-data edges** we lack collectors for: Polymarket CLOB WS event tape + cross-exchange basis (to crack
   the F2 slug-selector), order-queue position.

## Engine rules any new backtest MUST respect (from 05)
ws_s anchor (not slot_start); fee = 0.07·p·(1−p) winner-only; L25 native 10Hz; cross-token spread (not
same-token); chainlink-only outcomes; backtest fill is OPTIMISTIC on thin slugs; judge live by the wallet,
not shadow (parity diverges). Open bug: live↔shadow parity (qty_compute + feed/threshold) not yet fixed.
