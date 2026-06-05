> ⚠️ SCOPE NOTE: this report analyzes the **directional taker** wallets — a
> SEPARATE strategy line from our maker-arb sleeves. For the maker-arb / market-maker
> wallets that ACC-M/MAS/PAT were actually built from, see
> **`MAKER_WALLET_REEVALUATION_2026_05_29.md`**. Both conclude "no reproducible edge
> at our scale," via different mechanisms.

# Strategy Re-Evaluation — How (and whether) to Profit Like the Wallets (2026-05-29)

> Re-analyzed: (1) our running sleeves' logic, (2) the decoded profitable wallets
> + their edge, (3) a BROAD backtest of that edge on canonical data. **TL;DR: the
> directional "edge" the May 28 synthesis recommended deploying is priced-in
> (WR ≈ entry_px) and does NOT profit broadly. The wallets' real edge is slug
> selection + sub-60s latency pick-off, which our 1MIN/last-trade data can't
> capture. No parameter tweak makes the maker-arb sleeves profit.**

## 1. Our running sleeves (maker-arb) — why they lose
ACC-M/H/PC + MAS post paired maker bids, merge pairs for $1, hold leftover to
resolution. Backfill (`MAKER_ARB_BACKFILL_REAL_PNL_2026_05_29.md`): **every sleeve
net-negative, −$6,599 over 5 days.** Loss driver = **adverse-selected directional
residual**: the maker gets filled on the side the market is moving away from, and
that leftover is a coin-flip that loses to fees. The residual direction is RANDOM
(no signal) — that's the whole problem.

## 2. The wallets' decoded edge — + FRESH re-pull (2026-05-29)
`_directional_wallet_registry.csv` + `DECODE_*_2026_05_28.md`: the profitable
up-down wallets are **directional takers** riding the **binance→chainlink lag**
(Polymarket resolves on Chainlink Data Streams, which lags Binance spot). They buy
the side Binance is moving toward. Decoded signals: `ema9_slope_bps`, `ret_3m`,
`cl_basis_bps` (binance−chainlink), gated `entry_px∈[0.55,0.92]`.

Fresh chain re-pull (this session, fills through 2026-05-29 11:00 UTC):

| wallet | strategy | 7d WR (decoded) | 7d PnL (decoded slugs) | ~$/day | total CASH PnL | status |
|---|---|---:|---:|---:|---:|---|
| 0x07480f20 | ret_3m btc-5m | 76.1% (n=636) | +$1,138 | ~$224 | $769,225 | ACTIVE |
| 0x0de4458d | cl_basis extreme | 66.3% (n=104) | +$189 | ~$226 | $111,550 | ACTIVE |
| 0x0079c319 | ema9_slope btc-15m | 79.1% (n=215) | +$450 | ~$89 | $625,382 | ACTIVE |
| 0xe3867b68 | ema9_slope cross-asset | 69.4% | +$151 | ~$30 | $69,081 | ACTIVE |
| 0x8ef6a1cc | cl_basis btc-5m | — | $0 | $0 | $338,965 | DORMANT (9d silent) |

**Two findings that REINFORCE the priced-in conclusion below:**
1. **The edge persists** — 7d WR matches/exceeds all-time for the active wallets; no
   degradation. So the wallets genuinely profit on the up-down lag trade.
2. **🔑 Their up-down edge is THIN and a tiny sideline.** Decoded-slug PnL is only
   **+$30 to +$226/day**; their lifetime CASH PnL ($69k–$769k) is **100–500× larger
   and comes from thousands of OTHER markets, not up-down.** We were chasing a
   small piece of large multi-market traders. The up-down piece nets ~$100-200/day
   per wallet — exactly the magnitude of a thin selection/timing edge, NOT a fat
   replicable signal. This is fully consistent with §3: broad = breakeven; their
   small surplus comes from selection + sub-60s timing on chosen slugs.

## 3. 🚨 Broad backtest of the signal — it is PRICED-IN
`strategy_lab/directional/clbasis_signal_wr.py` + `clbasis_pnl.py`, on canonical
(binance 1MIN + chainlink RTDS + resolutions + trades, fresh to May 28), firing on
EVERY resolved slug (btc/eth/sol × 5m/15m):

**Direction WR (does the signal predict the outcome?)** — fire @ slot_start+offset:
| signal | @60s | @120s |
|---|---|---|
| cl_basis | 44-51% (coin flip) | ~50% |
| ema9_slope | 48-52% | 55-58% |
| ret_3m | 54-58% | 60-68% |
| px_vs_strike | 55-59% | 63-66% |

**PnL (buy leading side at market entry_px, gate [0.55,0.92], 2%-on-profit fee):**
| entry_px bucket | n | WR | PnL/share |
|---|---:|---:|---:|
| [.55,.65) | 29,195 | 58.5% | −0.0149 |
| [.65,.75) | 25,217 | 68.5% | −0.0121 |
| [.75,.85) | 17,971 | 79.7% | +0.0024 |
| [.85,.92] | 9,102 | 88.7% | +0.0021 |

**WR ≈ entry_px in every cell → `edge = WR − entry_px ≈ 0`.** The market prices the
persistence efficiently. Net across all cells **−$679/share**. The only positive
zone ([0.75,0.85], +$0.002/share) is within fee/slippage noise.

**This means the May 28 synthesis OVERSTATED deployability.** Its 78-91% WR figures
were measured on (a) the wallets' SELECTED slugs and (b) favorable entry_px tiers —
not a true forward EV that pays the market entry price. Pay the price and the edge
vanishes.

## 4. So where is the wallets' real edge?
Two things my broad/1MIN/last-trade replication cannot capture:
1. **Sub-60s latency pick-off.** WR rises with offset (50%@30s → 59%@60s →
   66%@120s) — but so does the price, so EV stays ~0. The wallets fire FAST
   (0x0de4458d median 33s into a 300s window). The alpha lives in the first ~10-30s
   AFTER a binance move, when **resting polymarket asks are still stale** (priced off
   the lagging oracle). A fast taker picks those off BELOW fair value. My entry_px =
   last-trade reflects the *realized* price, not the stale resting ask — so it misses
   exactly this. This is a latency/pick-off edge, not a signal-broadcast edge.
2. **Slug selection.** 0x0de4458d reportedly hits 77% on cl_basis-extreme slugs vs
   40% control — but my broad cl_basis-magnitude stratification shows ~50% in every
   magnitude bucket. So either its selector is finer than cl_basis magnitude, or the
   n=297/7d sample is partly a hot streak. Unresolved with current data.

This is the **same wall as F2** (`F2_FINAL_VERDICT_2026_05_18.md`): the edge needs
the **Polymarket CLOB WS event tape + cross-exchange basis at sub-second
resolution** to decode — data we don't collect.

## 5. Answer: how to profit like the wallets
**Not by tweaking maker-arb.** The maker residual is random; aligning it to a
priced-in signal adds no alpha. Retire the maker-arb sleeves, or run **merge-only**
(zero directional residual) — that's the most it can be without bleeding.

The wallets' edge is **latency + selection**, requiring infrastructure we don't have
yet. Concrete path, in order of cost/value:

1. **Decisive next experiment (cheap, do first): L25-ask backtest, not last-trade.**
   Re-run Pass 2 using `load_orderbook_l25_streaming` best-ask of the leading side at
   fire_us (the price a fast taker would actually PAY), at offsets 5/10/20/30s. If
   best-ask < fair value in the first seconds after a binance move, the latency edge
   shows up as positive EV; if best-ask already ≈ WR, the edge truly needs sub-second
   speed we can't model. **This single test decides whether the edge is reachable.**
2. **Forward-paper a directional taker sleeve** on the now-honest shadow engine
   (E1-fixed): fire @ +120s, `ret_3m>0`, gate `entry_px∈[0.75,0.85]`, btc/eth/sol 5m.
   Tiny/zero expected edge — but free to run and validates the pipeline + real fills.
3. **Build the CLOB WS event-tape + cross-exchange basis collector** (F2 roadmap §5)
   — the only way to decode the selection/latency signal. Biggest effort; the real
   unlock if pursued.
4. **A true latency play** (pick off stale asks right after binance ticks) needs a
   sub-second taker co-located near the Polymarket CLOB (AWS eu-west-2 / London;
   Ireland RTT <2ms is good). Only worth building if (1) shows the stale-ask gap exists.

## 6. Bottom line
- Maker-arb: structurally unprofitable (random residual). Retire / merge-only.
- Directional signal applied broadly: priced-in, ~breakeven-to-negative. Do NOT
  deploy the cl_basis/ema9 strategy as the May 28 synthesis suggested.
- The wallets' up-down edge is **real but thin (~$100-200/day)** and comes from
  **selection + sub-60s latency**, not the signal — their headline $69k-$769k PnL is
  mostly OTHER markets. Same data gap as F2. The thin up-down surplus is reachable
  only by (a) testing the L25-ask pick-off (step 1), and if it exists (b) building
  sub-second execution + the WS event-tape collector. Even fully replicated, expect
  ~$100-200/day/cell — size accordingly before investing in the infra.

## Artifacts
- `strategy_lab/directional/clbasis_signal_wr.py` + `_results/signal_wr.csv`, `clbasis_magnitude_wr.csv`
- `strategy_lab/directional/clbasis_pnl.py` + `_results/clbasis_pnl.csv`
- Inputs: canonical (binance 1MIN, chainlink RTDS, resolutions, trades_polymarket — all fresh to May 28)
- Wallet evidence: `cache/_directional_wallet_registry.csv`, `DECODE_SYNTHESIS_2026_05_28.md`
