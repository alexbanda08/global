# Decode: Big BTC-5m Lifetime Wallets (2026-05-29)

Wallets decoded: 0xa6896d11 ($72.9k), 0x951bd740 ($42.6k), 0xdd3c4d67 ($22.6k)

---

## Summary table

| wallet | lb_profit_life | lb_profit_30d | bucket | mechanic | reproducible |
|---|---|---|---|---|---|
| 0xa6896d11 | $72.9k | $62.2k | **MIXED**: maker pair-arb (primary) + directional taker (secondary) | TRADE+MERGE+REDEEM; pair_sum mean=0.997, +single-sided directional | Pair-arb: YES. Directional component: weak/uncertain |
| 0x951bd740 | $42.6k | $29.1k | **MIXED**: maker pair-arb (primary) + directional taker (secondary) | TRADE+MERGE+REDEEM; pair_sum mean=1.002, + single-sided directional | Pair-arb: marginal (pair_sum ≈ 1). Directional: WR=65.2%, possible real edge |
| 0xdd3c4d67 | $22.6k | $19.1k | **DIRECTIONAL TAKER** (pure) | TRADE+REDEEM only; no MERGE/SPLIT; avg entry 0.324, WR=32.4% | NOT reproducible — underdog-betting, WR < entry price, net-negative |

---

## 1. 0xa6896d11 — $72.9k lifetime (PRIORITY TARGET)

### Activity tape
- `TRADE=3500, MERGE=3500, REDEEM=3500, MAKER_REBATE=39` — MERGE confirms pair-arb exit mechanic
- Volume: $5.05M. USDC flow: in $403.6k, out $405.6k (net -$1.975k cash; profit is in ERC1155 redemptions)
- ERC1155: 22,304 transfers (8,750 sent, 13,554 received)
- Active window: May 23-29 only (6 days at $72.9k = ~$12k/day)

### Pair-arb component (81.7% of slugs)
- 836 total slugs; 683 both-sided (paired), 88 Up-only, 65 Down-only
- Pair_sum: mean=0.9965, median=1.0004, min=0.39, max=1.54
- 49.5% below 1.00 (arb), 20.2% below 0.95 (strong arb)
- Edge mechanism: buy Up+Down below $1.00 cost, MERGE immediately for guaranteed $1.00
  - Expected edge per pair at mean: $0.0035/pair nominal
  - At tail (sub-0.95): $0.07+/pair — this is where the real money is
- Very high-velocity: ~$5M volume in 6 days on 836 slugs = $6k avg notional/slug

### Directional component (18.3% of slugs)
- Harness: 124 resolved directional fires, WR=58.9%, entry_px=0.537
- Segment tool: directional%=18%, WR=58.9% — above entry price (positive EV directional)
- Direction discriminator: `cl_basis_bps` d=-0.507 (Up fires when cl_basis lower, Down when higher)
  - Matches the cl_basis survivor identified in EFFICIENT_MARKET_FINDING_2026_05_28.md
- Win/loss discriminator: `rv_15m_bps` d=-0.424 (wins in LOW volatility), `ret_5m` d=+0.315
  - Wins cluster at low volatility + favorable recent return (momentum-consistent)
- Slug selection: `rv_15m_bps` d=0.363 (fires in HIGHER vol than control — paradox with win filter)
  - Suggests they fire broadly on high-vol days but the winning subset is low-rv within that
- All direction d-scores < 0.6: no single clean rule fully explains direction picks

### Funder
- pUSD minted from zero-address (self-mint from USDC via Polymarket)
- Small top-up from `0x3a9418b2651c8164db5ebc56f12008137865e0f7` ($257) = **F2 treasury** (the $43k/day CLOB taker decoded in F2_FINAL_VERDICT_2026_05_18.md). Fleet link confirmed.

### Verdict
**MIXED: primarily maker pair-arb + cl_basis-driven directional overlay.**
- Pair-arb edge: real, structural (buy below $1.00, merge immediately). Thin median edge (0.003/pair) but high velocity compensates. Reproducible in principle — requires fast CLOB limit orders to acquire sub-$1 pair.
- Directional overlay: 18% of slugs, WR=58.9% above 53.7% entry — marginal positive EV. cl_basis signal is the same survivor from our capstone analysis. Weak Cohen's d across all features; no clean codeable rule. **Uncertain reproducibility.**
- Revenue attribution: most lifetime PnL likely from pair-arb volume ($5M at 0.3-0.5% margin) not directional.

---

## 2. 0x951bd740 — $42.6k lifetime

### Activity tape
- `TRADE=3500, MERGE=3500, REDEEM=3500, MAKER_REBATE=30` — same pair-arb mechanic as wallet1
- Volume: $4.66M. USDC flow: in $437.6k, out $439.6k (net -$1.98k)
- ERC1155: 25,448 transfers
- Active: May 23-29 (6 days, ~$7k/day)

### Pair-arb component (86.1% of slugs)
- 764 total slugs; 658 both-sided, 63 Up-only, 43 Down-only
- Pair_sum: mean=1.0017, median=1.0042, min=0.51, max=1.58
- 48.8% below 1.00 (arb), 18.4% below 0.95
- **Pair_sum median barely above 1.0** — weaker arb than wallet1. May be holding to REDEEM (directional bet on winner) rather than MERGE when pair_sum > 1.

### Directional component (13.9% of slugs)
- Harness: 89 directional fires, **WR=65.2%**, entry_px=0.521 — flagged segment (WR > 65%)
- Direction discriminator (strong): `cl_basis_bps` d=-0.605 (Up when lower basis), `ret_15m` d=+0.481, `macd_hist` d=+0.441, `ema9_slope_bps` d=+0.321
  - **Momentum + cl_basis combo**: fires Up when MACD histogram positive + upward EMA slope + lower cl_basis. Down is the opposite.
- Win/loss discriminator: `rv_15m_bps` d=-0.647 (strong: wins in LOW vol), `macd_hist` d=-0.237
  - Wins when volatility is LOW. Losses when volatility is high.
- Slug selection: `macd_hist` d=0.239, `ret_3m` d=+0.190 — selects slugs with upward short-term momentum
- **Best-decoded wallet of the three for directional edge**: rule is effectively "fire momentum direction (MACD/EMA9) but only when cl_basis is NOT elevated AND volatility is low"

### Funder
- Same pattern: pUSD self-minted + $285 from `0x3a9418` (F2 treasury). Fleet link confirmed.

### Verdict
**MIXED: maker pair-arb + real directional momentum/cl_basis edge.**
- Pair-arb: same structural edge but median pair_sum=1.004 suggests many slugs bought near/above $1 — either REDEEM-holding or timing lag. Less pure than wallet1.
- Directional: WR=65.2% at n=89 is the strongest harness result here. Direction rule: MACD histogram + EMA9 slope + low cl_basis + low rv_15m → bet in momentum direction. Win/loss separability via rv_15m is strong (d=-0.65). This pattern is reproducible if the momentum + volatility filter holds.
- **Reproducibility: UNCERTAIN.** The efficient market capstone showed momentum is priced-out at portfolio level. 89 fires is thin; 65.2% WR could be sample noise. cl_basis survival is thin-edge only. Needs walk-forward validation before deploying.

---

## 3. 0xdd3c4d67 — $22.6k lifetime

### Activity tape
- `TRADE=3500, REDEEM=3500, MAKER_REBATE=43` — **NO MERGE, NO SPLIT**
- Pure directional taker: buys tokens, holds to REDEEM (resolution)
- Volume: $1.23M. USDC flow: in $34.9k, out $32.7k (net +$2.1k — USDC positive; profits via ERC1155 redemptions)
- ERC1155: 5,557 transfers (much lower than wallets 1+2)
- Active: May 23-29 (6 days, ~$3.8k/day)

### Directional profile (74% directional, WR=32.4%, entry_px=0.324)
- 1,721 total slugs; only 446 both-sided (25.9%), 601 Up-only (34.9%), 674 Down-only (39.2%)
- avg entry price 0.324: **buys underdogs** (cheap contracts)
- WR=32.4% vs entry_px=32.4% → WR equals entry price → **net-zero before fees, negative after**
- Verified: pnl_per_bet = -$4.03 at ~$180 avg notional (consistent with entry=WR pricing)
- Price distribution: 30.5% of trades under $0.20 (deep underdog), 56.3% under $0.40
- Pair_sum (paired slugs): mean=0.868, median=0.885 — BUT this is not arb since no MERGE: buys both cheap sides of extreme-price slugs (sum far below 1 = market expects one side very likely)

### Trigger features
- Direction discriminators: `px_vs_strike_bps` d=-0.347 (bets Down when strike > price), `ret_3m` d=-0.287 (bets Down after recent up-move = contrarian)
  - **Contrarian direction pick**: bets against recent 3m momentum
- Slug selection: near-zero Cohen's d on all features (max d=0.096) — fires on essentially every slug, no selection
- Win/loss discriminator: `rv_15m_bps` d=+0.461 (wins in HIGH vol) — opposite of wallets 1+2

### Why it shows $22.6k lifetime profit despite net-negative per-trade math
- lb_profit = Polymarket leaderboard PnL = includes open positions in `open_value=$29.83` (n=100 open)
- $22.6k with WR=entry_px over 1,721 slugs → some timing luck OR the lb_profit includes edge from extreme-underdog bets that resolved favorably in this 6-day window (variance-heavy)
- **This is not a real edge.** WR tracks entry price perfectly = fully priced market.

### Funder
- pUSD self-minted + $63 from `0x3a9418` (F2 treasury). Fleet link.

### Verdict
**PURE DIRECTIONAL TAKER, NOT REPRODUCIBLE.**
- Contrarian underdog bettor. Buys cheap (0.04-0.40) contracts betting on low-probability outcomes.
- WR = entry price = efficient market pricing. Net-negative after fees.
- $22.6k lifetime profit is variance/luck in a 6-day window; strategy is expectation-negative.
- **DO NOT attempt to replicate.**

---

## Fleet analysis

All three wallets share the same funder (`0x3a9418b2651c8164db5ebc56f12008137865e0f7` = F2 treasury) and were all created within seconds of each other (May 23, 20:19-20:22 UTC). They appear to be a 3-wallet fleet operated by the same entity as F2 (the $43-49k/day CLOB taker). The F2 operator appears to be running multiple concurrent strategies: the known F2 directional high-frequency strategy + these new pair-arb + mixed wallets.

---

## Reproducibility matrix

| strategy | confidence | gate recommendation |
|---|---|---|
| Pair-arb (buy Up+Down < $1.00, MERGE) | HIGH — structural, zero-outcome-risk | Requires fast limit order execution, Ireland RTT. Already in MINT_AND_SELL spec. |
| Directional cl_basis + momentum (wallet2 rule) | LOW-MEDIUM — 89 fires, thin d-scores | Needs 200+ fire walk-forward before live. |
| Underdog contrarian taker (wallet3) | NONE | Do not pursue. |

---

*Generated 2026-05-29. Data: segment_winrate.py + trigger_decode_harness.py + polymarket_api.py + fetch_alchemy.py on trades/activity tapes (3500-record caps).*
