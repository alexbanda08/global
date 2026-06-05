# Directional Up/Down Decode — Synthesis (2026-05-28)

8 high-WR directional wallets decoded in parallel via
`strategy_lab/wallet_hunt/trigger_decode_harness.py`. Per-wallet reports:
`DECODE_<short>_2026_05_28.md`. This file ties them together.

## The root edge (one mechanism, two expressions)
**Polymarket up-down markets resolve on the Chainlink Data Streams oracle, which
LAGS Binance spot.** Every decoded wallet is, at bottom, trading the same thing:
*Binance leads the Chainlink settlement.* They buy the side Binance is already
moving toward, before the slower oracle (and thus the market price) catches up.

Two ways they express it — both reduce to the same signal:

### Family A — EMA/return momentum
Buy the side of the short-term Binance trend.
- **0xe3867b68** (CLEANEST): single cross-asset rule `ema9_slope_bps>0 → Up`
  on BTC/ETH/SOL. Direction Cohen's d = 0.59 / 1.00 / 1.08. Rule-agree WR
  (entry_px≥0.65): BTC 86%, ETH 90%, SOL 74%; pooled 85% (n=141).
- **0x0079c319** btc-15m: `ema9_slope>0`, 62% agree, WR 81% when rule agrees vs
  62% when not (Δ+18.5pp, p<1e-4). n=610, 15d — robust.
- **0x07480f20** btc-5m: `ret_3m>0`, WR 81.5% aligned vs 66.4% misaligned. n=816,
  but high-freq (102 slugs/day).

### Family B — explicit Chainlink-RTDS divergence (`cl_basis_bps`)
`cl_basis_bps = (binance − chainlink_RTDS)/chainlink × 1e4`. Fire when extreme.
- **0x0de4458d** btc-5m: `cl_basis<9 → Up`, `>12 → Down`. Mid-tier WR 78%.
  **Selective slug picker** — 3.8× overweight extreme-cl_basis slugs, avoids the
  neutral 9–12 zone (0.58×). Control slugs with cl_basis<9 resolve Up only 40% —
  wallet hits 77% there. p<1e-12. Fires fast (median 33s into 300s window).
- **0x8ef6a1cc** btc-5m: `cl_basis<9 → Up` 90% agreement, d=2.04. Core tier WR
  93%. Independently corroborates Family B — but only 1 day of data.

Family A and Family B are the **same edge**: ema-slope is a proxy for "binance has
moved and the oracle hasn't yet" = positive cl_basis. cl_basis is the cleaner,
more direct expression.

## Universal structure (every wallet)
1. **Entry-price tiers dominate raw WR — must filter:**
   - `entry_px > 0.85` (~30–40% of fires): WR 96–100%. **Not edge** — late-window
     buys after the outcome is near-certain; captures pennies. Inflates headline WR.
   - `entry_px 0.55–0.85`: the **real momentum edge**, WR ~78–91%.
   - `entry_px < 0.50`: direction goes **contrarian** to momentum, WR 28–35%.
     Structural losers — a poison-pill tail. Any deploy MUST gate it out.
   - Deployable filter: **`entry_px ∈ [~0.55, 0.92]`**.
2. **Slug selection is mostly indiscriminate** (|d|<0.2): they fire on ~every slug
   in the asset/tf. EXCEPTION: **0x0de4458d selects on cl_basis extremity** — the
   one wallet with a real, reproducible slug filter. This is the slug-selection
   crack we were missing: *the selector is cl_basis magnitude.*
3. **Win vs loss not separable** ex-ante beyond entry_px → edge is in the
   direction pick + timing, not in filtering winnable slugs.

## Deployability ranking
| wallet | signal | WR (filtered) | n / span | verdict |
|---|---|---|---|---|
| **0xe3867b68** | cross-asset ema9_slope, px≥0.65 | 85% (n=141) | 281 / 5d | **HIGH** — one rule, 3 assets, no exotic data. Forward-test first. |
| **0x0079c319** | ema9_slope btc-15m, px∈[0.6,0.92] | 90% (n=393) | 610 / 15d | **HIGH** — most robust span. |
| **0x07480f20** | ret_3m + cl_basis btc-5m | 80% (combo) | 816 / 8d | MEDIUM-HIGH — high-freq, edge compresses on high-px tier. |
| **0x0de4458d** | cl_basis<9/>12 btc-5m + slug filter | 78% mid | 297 / 7d | MEDIUM — mechanistic + selective; needs fast infra (~33s). |
| 0x9f5ffe76 | early-momentum 15m | 88% px≥0.5 | 45 / 12d | DO NOT DEPLOY — n too small. |
| 0x10188828 | ema9_slope sol/eth-15m | 67% | 161 / 2d | DO NOT DEPLOY — 2-day, poison low-px tail. |
| 0x8ef6a1cc | cl_basis btc-5m | 93% core | 40 / 1d | RE-PULL — credible (matches B) but 1 day. |
| 0xf6d2f340 | px_vs_strike sol-5m | 93% core | 68 / 1d | RE-PULL — weak/novel decode, 1 day. |

## Recommended next steps
1. **Build the unified signal**: `cl_basis_bps` (binance spot − chainlink RTDS) is
   the cleanest single feature. Backtest a generic strategy: fire on |cl_basis|
   extreme, buy the leading side, gate `entry_px∈[0.55,0.92]`, across btc/eth/sol
   × 5m/15m, using `engine_v2.LegacyConfig` (2%-on-profit fee) + cross-token spread
   filter per CLAUDE.md. This generalizes ALL the wallets at once.
2. **Re-pull deeper history** for the 1-day wallets (0x8ef6a1cc, 0xf6d2f340) and
   small-n (0x9f5ffe76) via deeper data-api pagination, then re-run the harness to
   confirm the WR holds out of the hot-streak window.
3. **Slug-selector**: replicate 0x0de4458d's cl_basis-magnitude selector explicitly
   — it's the one confirmed slug filter; test whether selectivity beats "fire all".

## Artifacts
- Tool: `strategy_lab/wallet_hunt/trigger_decode_harness.py`
- Per-fire feature tables: `cache/<short>/trigger_<asset>_<tf>.parquet`
- Per-wallet reports: `strategy_lab/reports/DECODE_*_2026_05_28.md`
- Discovery + WR scan: `strategy_lab/reports/DIRECTIONAL_WR_SCAN_2026_05_28.md`
