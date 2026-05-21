# Within-slug timing decode — 2026-05-20

**Question (continuing from `SLUG_SELECTION_DECODE_2026_05_20.md`):**
Slug-selection signal didn't decode the wallets' alpha. Maybe their edge is **within-slug timing** — when in the slug do they fire, and is that the profitable moment?

**Short answer:**
1. ✅ Each reference wallet has a **distinct within-slug timing signature**. 0xcfb103c3 (PAT/xuanxuan008) concentrates 18.6% of fills in the first 30 seconds — almost 2× any other 30s bucket. Other wallets have flatter or mid-slug-skewed distributions.
2. 🚨 BUT chain-truth `pnl_net` (the column in `pnl.parquet` that combines cash flow + mint cost + leftover redemption − fees) shows **all four reference wallets are NET NEGATIVE on BTC up-down in the canonical window** — across every offset bucket. 0xcfb103c3 averages **−$94.6/slug** in the 0-30s bucket and −$67 to −$95 in every other bucket.
3. This contradicts LB-API which shows these wallets at $2-6k/day profit. Two interpretations:
   - **`pnl.parquet` has a bug** in how it sums mint cost vs redemption (the per-slug formula I sanity-checked on `btc-updown-5m-1778767500` showed pnl_gross=+$18.64 where my hand calc gave −$39.59 — formula likely double-counts redemption or omits mint-from-leftover-pair accounting)
   - **Wallets are profitable on non-BTC markets we don't have decoded** — pnl.parquet only covers BTC slugs in our canonical window; their LB-API stat aggregates all assets and may use different fee assumptions

Either way: **we cannot trust the wallet PnL claims at the per-slug level**, so we cannot validate timing → PnL alpha from chain decode alone.

---

## What we built

| File | Output |
|---|---|
| `strategy_lab/backtests/within_slug_timing.py` | Per-fill offset distribution + binance leading features |
| `strategy_lab/backtests/timing_profitability.py` | Per-slug cash_flow PnL by first-fill bucket (MISLEADING — see §3) |
| `strategy_lab/backtests/timing_truth_pnl.py` | Per-slug chain-truth `pnl_net` by first-fill bucket |

Outputs:
- `_wallet_fill_timing_summary.csv` (9 rows — per wallet × tf)
- `_wallet_fill_timing_offsets.csv` (170 rows — 30s buckets × wallet × tf)
- `_wallet_fill_timing_features.csv` (238,816 fills enriched with binance lead + book state)
- `_timing_truth_pnl_per_slug.csv` + `_timing_truth_pnl_summary.csv`

---

## 1. Within-slug timing signature is real

Fraction of each wallet's BTC 5m fills, by 30s offset bucket:

| Bucket | 0x04b6d7e9 (MAS) | 0xeebde7a0 (Hybrid) | 0x89b5cdaa (dir.MAS) | **0xcfb103c3 (PAT)** | 0xce25e214 (mixed) |
|---|---:|---:|---:|---:|---:|
| 0-30s | 9.3% | 10.3% | 9.3% | **18.6%** | 8.5% |
| 30-60s | 15.9% | 10.5% | 12.9% | 10.4% | 12.8% |
| 60-90s | 16.8% | 11.7% | 13.7% | 12.8% | 12.8% |
| 90-120s | 15.4% | 12.1% | 10.9% | 11.1% | 14.0% |
| 120-150s | 13.5% | 12.0% | 11.4% | 10.7% | 14.2% |
| 150-180s | 9.6% | 10.2% | 11.2% | 7.9% | 10.4% |
| 180-210s | 8.7% | 10.1% | 10.9% | 9.0% | 8.8% |
| 210-240s | 6.3% | 9.0% | 7.9% | 7.2% | 8.1% |
| 240-270s | 3.7% | 9.2% | 8.6% | 8.1% | 7.7% |
| 270-300s | — | 5.0% | 3.1% | 4.3% | 2.6% |

**Pattern**:
- **0xcfb103c3**: sharp **slug-open bias** — 1.8× spike at 0-30s, then flat-to-declining. Consistent with reactive taker firing on opening-book inefficiency.
- **0x04b6d7e9** (MAS): peaks at 30-90s, declines after — consistent with "let book stabilize then mint-and-sell".
- **0xeebde7a0** (Bonereaper): nearly uniform across the slug — engages constantly.
- **0x89b5cdaa** (directional MAS): flat with slight mid-slug peak.
- **0xce25e214**: builds gradually, peaks at 90-150s.

**Per-fill behavior of 0xcfb103c3 by bucket** (book state at fill):
- 90% takers, 10% makers — confirms taker-heavy profile
- Spread at fill time: tight (1¢ median) across all buckets
- abs_ret_60s_at_fire: 0.0002 across buckets — they do NOT fire after binance moves
- ask_size_top_med: ~100 shares (sufficient depth)

So the timing **fact** is solid. The fact's **profitability** is what we can't verify.

---

## 2. The pair_cost problem

For 0xcfb103c3's paired-taker fires (1,791 events where the wallet bought BOTH Up and Down within 1s of each other):

| Bucket | mean pair_cost | median | p90 | frac < 1.00 |
|---|---:|---:|---:|---:|
| 0-30s | **1.0221** | 1.01 | 1.050 | **0.0%** |
| 30-60s | 1.0205 | 1.01 | 1.040 | 0.0% |
| 60-120s | 1.0191 | 1.01 | 1.050 | 0.0% |
| 120-180s | 1.0203 | 1.01 | 1.050 | 0.0% |
| 180-300s | 1.0223 | 1.01 | 1.060 | 0.0% |

**The pair_cost is ALWAYS ≥ 1.00.** This is the opposite of a classic PAT pair-arb (which requires `ask_up + ask_dn + fees < 1.00`).

Two possibilities:
- The "PAT" label on this wallet is **wrong** — they aren't running pair-arb. They might be doing **paired directional bets** that happen to look like PAT because the bot buys both sides separately in quick succession.
- The wallet uses a **maker-side strategy** (mint-and-sell variant) where the taker buys we see are minor offsets to inventory, and the real economics come from the maker fills we can't isolate cleanly.

Either way, the strategy we deployed (PAT+ACC-M HYBRID with `pat_max_pair_cost=1.00`) is **structurally different** from what 0xcfb103c3 does on chain. Our backtest's projected +$7.79/slug came from running OUR strategy on the universe, not from replicating the wallet.

---

## 3. The cash-flow vs chain-truth divergence

| Wallet | Bucket | n_slugs | cash_flow_usd/slug | **pnl_net/slug** (chain truth) | Win rate (pnl_net) |
|---|---|---:|---:|---:|---:|
| 0xcfb103c3 | 0-30s | 322 | +$16.41 | **−$94.62** | 16.15% |
| 0xcfb103c3 | 30-60s | 44 | +$3.43 | **−$84.34** | 13.64% |
| 0xcfb103c3 | 60-120s | 39 | −$1.32 | **−$67.52** | 12.82% |
| 0x04b6d7e9 | 0-30s | 148 | +$2,687 | **−$97.31** | 41.89% |
| 0xeebde7a0 | 0-30s | 323 | +$523.74 | **−$50.90** | 36.84% |
| 0x89b5cdaa | 0-30s | 188 | +$564.53 | **−$20.50** | 39.36% |
| 0xce25e214 | 0-30s | 54 | −$67.09 | **−$79.19** | 37.04% |

`cash_flow_usd = sum(sell_usd) − sum(buy_usd)` is essentially worthless as a PnL metric for these wallets because:
- They mint pairs ($1 cost each, paid in USDC, NOT a "buy" or "sell" trade)
- Winner-side leftover redeems at $1/share at settlement (also outside fills)
- Both are accounted for in `pnl_net` but not in `cash_flow_usd`

**Sanity check on `pnl_net`**: for slug `btc-updown-5m-1778767500`, my hand calc was:
```
cash_total (= sell - buy)     = -23.61
mint_cost (= minted_pairs × 1) = -58.21
leftover_redeem (winner side) = +42.25
expected pnl_gross            = -39.57
actual pnl_gross in column    = +18.64   ← MISMATCH ($58 gap)
fees                          =  7.27
pnl_net                       = +11.37
```

I can't reproduce `pnl_gross` from the visible fields. The formula likely either:
- Treats `minted_pairs` already net of merges (so cost is lower than I assumed)
- Counts redemption of full position (not just leftover)
- Or has a sign-flip bug somewhere in the building script

This means **both `pnl_net` and `cash_flow_usd` are suspect** for this analysis. We don't have a trustworthy per-slug PnL number for these wallets.

---

## 4. What we can still say

1. **Timing signatures are real and reproducible** from the raw fills.parquet. They don't depend on PnL calculation.
2. **0xcfb103c3 has the strongest slug-open bias** (18.6% in 0-30s) — this is structural evidence the wallet specifically targets the early-slug window.
3. **The wallet does NOT pair-arb at pair_cost < 1.00** — our PAT cap of $1.00 will rarely-to-never fire when book is in 0xcfb103c3's typical regime (pair_cost ≈ 1.02).
4. **PAT+ACC-M HYBRID's projected +$7.79/slug** comes from our OWN backtest on the full universe, not from replicating any wallet. That projection is still valid until shadow data refutes it.

---

## 5. What to do next

The honest path forward is:
1. **Stop trying to decode wallet PnL from chain data.** The pnl.parquet formula needs an audit (separate task — file a follow-up under wallet_hunt). Until then, every wallet-derived "alpha estimate" carries an unknown bias.
2. **Trust the universe-level PAT+ACC-M backtest** (+$7.79/slug, 49% fire rate, 75% win rate on fires) since it doesn't depend on wallet data. This is what Ireland VPS is now running.
3. **Let the shadow monitor be the validator.** The 7-day shadow data will tell us if the +$7.79/slug projection holds in production. If it does, we promote per the implementation spec. If not, we have ground-truth (not chain-decode artifact) data to debug from.
4. **Consider lowering `pat_min_time_after_open_s` from 5s to 0s** (or 2s) so PAT can fire in the slug-open window where 0xcfb103c3 demonstrably concentrates activity. The book asymmetry is real even if the wallet isn't pair-arbing. Backtest projects PAT fires throughout the slug; allowing earlier fires might lift the fire-rate and PnL. Test this as a config-flag change after the first 7 days of baseline shadow data.

---

## 6. Audit-worthy follow-ups (out of scope this session)

| Item | Owner | Why |
|---|---|---|
| Audit `pnl.parquet` build script | wallet_hunt agent | pnl_gross doesn't reconcile to cash_total + mint + redeem on sample slug |
| Cross-check cfb103c3 vs LB-API per-day | manual | LB-API says +$2.5k/day but chain says −$40k total → 16× discrepancy that needs resolving |
| Decode whether wallet runs paired-directional bets rather than pair-arb | wallet_hunt | They buy both sides at pair_cost > 1.00 — not arb but consistent fire rate suggests intentional |
| Build trade-tape leading features at fire-time (cvd_60s, large_print_60s) | strategy_lab | A potential timing signal we haven't tested |

---

## Artifacts

```
strategy_lab/backtests/within_slug_timing.py
strategy_lab/backtests/timing_profitability.py
strategy_lab/backtests/timing_truth_pnl.py
strategy_lab/backtests/_wallet_fill_timing_summary.csv
strategy_lab/backtests/_wallet_fill_timing_offsets.csv
strategy_lab/backtests/_wallet_fill_timing_features.csv      (238,816 rows)
strategy_lab/backtests/_timing_profitability_per_slug.csv
strategy_lab/backtests/_timing_truth_pnl_per_slug.csv
strategy_lab/backtests/_timing_truth_pnl_summary.csv
strategy_lab/reports/WITHIN_SLUG_TIMING_DECODE_2026_05_20.md  (this report)
```
