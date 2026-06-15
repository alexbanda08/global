# Handoff — Cyclops.exe wallet, last 5 days — 2026-06-15

**Trigger:** operator screenshot of a BTC "Up or Down" 5m favorite-hold bot. Asked: find the exact wallet, confirm if mapped, pull last 5d, full breakdown (markets, ROI/market, # trades, WR).

## Identification — CONFIRMED, already mapped

- **Wallet:** `0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c`
- **Pseudonym:** **Cyclops.exe** (lb-api `/profit` `name` + `pseudonym`)
- **Already in catalog** (CLAUDE.md: "CYCLOPS wallet … BTC-5m $3 favorite-hold, −$198 lifetime"; scripts `cyclops_wallet_{4d,7d}_*`). Cluster funder `0x2e1e827f` + sibling `0x886a78bfd` (small/losing).
- **Screenshot ↔ on-chain match = 1:1 on every row** (price/shares/cost/time), e.g. Jun-14 01:56PM Down px0.71 sz3.68 $2.66; 05:59AM Up px0.89 sz3.07 $2.75; Jun-13 02:26PM Up sz3.19 → the +$3.19 redeem. No ambiguity — this is the wallet.

## Decoder

- Script: `strategy_lab/wallet_hunt/cyclops_wallet_5d_2026_06_15.py`
- Source: Polymarket **`data-api /activity`** (paginated, public, no Alchemy key) + `lb-api /profit` cross-check.
- Raw cache: `strategy_lab/wallet_hunt/cache/_cyclops_5d/activity_raw.json`
- PnL = Σredeem + Σsell − Σbuy (net cash). WR computed two ways (see survivorship note).

## Strategy signature (unchanged from prior decode)

**Single-sided directional FAVORITE-hold-to-resolution.** Buys ONE side (the favorite), ~3 shares, ~$2.6 stake, holds to settlement, redeems. No pair-arb, no maker, no exit/scalp.
- **100% of buys on the favorite** (price > 0.5); entry px: median **0.835**, mean 0.817, p05–p95 = 0.71–0.94, max 0.97.
- Size: median **3.07 shares** (~$2.59 notional, tight std 0.28). One clip per slug (26 buys / 26 distinct slugs).
- Side mix: **Up 20 / Down 6** (window-dependent; follows momentum, not a fixed bias).

## 5-day window (2026-06-10 13:05 → 2026-06-15 13:05 UTC)

| Metric | Value |
|---|---|
| BUY trades | 26 ($67.46 cost) |
| SELL trades | 0 |
| REDEEM events | 25 ($78.78 payout) |
| **Realized PnL (net cash)** | **+$11.31** |
| **Overall ROI** (PnL/cost) | **+16.77%** |
| Resolved buys | 26 (0 pending) |
| **TRUE WR** | **96.2%** (25 won / 1 lost) |
| avg WIN pnl/slug | +$0.564 |
| the 1 loss | eth-updown-5m Up @0.90, −$2.78 (full stake) |

### ROI per market (asset × tf)

| Market | Buys | Cost $ | Redeem $ | PnL $ | ROI % | WR |
|---|---|---|---|---|---|---|
| **btc 5m** | 22 | 56.33 | 68.99 | **+12.66** | **+22.47%** | 22/22 = 100% |
| **eth 5m** | 4 | 11.13 | 9.79 | **−1.34** | **−12.06%** | 3/4 = 75% |

→ Trades **only BTC & ETH 5m** in this window (no 15m, no SOL/XRP). BTC is the breadwinner; ETH was net-negative (the single loss landed there).

### Daily breakdown

| Day | Buys | Redeems | Cost $ | Net $ | ROI % |
|---|---|---|---|---|---|
| 06-11 | 1 | 1 | 3.06 | +0.80 | +26.3 |
| 06-12 | 1 | 1 | 2.56 | +0.80 | +31.0 |
| 06-13 | 4 | 4 | 9.14 | +3.74 | +40.9 |
| 06-14 | 9 | 9 | 23.43 | +4.80 | +20.5 |
| 06-15 | 11 | 10 | 29.27 | +1.18 | +4.0 |

Activity **ramping up** (1→11 buys/day); 06-15 ROI compressed (one ETH loss + lower-edge fills).

## ⚠️ Critical caveats (GROUND-TRUTH)

1. **WR survivorship trap (re-confirms the ce25/momo lesson).** The raw redeem-count metric showed **100% WR** because **losing favorite-holds leave NO redeem event** (token expires worthless). True WR = 96.2% only after matching buy→redeem conditionIds. Any Cyclops WR must be computed on **resolved BUYS**, never on redeems.
2. **5d is a HOT STREAK, not the edge.** lb-api **all-time profit = −$210.66**. The favorite-hold pays the favorite premium (median entry 0.835 → needs >83.5% WR just to break even on a fair book; long-run it loses). +$11.31/5d is variance, consistent with prior decode (lifetime −$198 to −$213).
3. **lb-api `/profit` windowing is unreliable** here: 1d == 7d == +$1.83 (ignores/caches window), while activity-derived net cash = +$11.31/5d. Trust the **activity-reconciled net cash** (redeem−buy balances exactly), not lb windowed.
4. **No alpha to copy.** Single-sided favorite-hold with no entry signal (ML side-decode was a coin flip in prior work) and negative expectancy after the favorite premium. This is a marginal mirror bot, not a strategy to clone.

## Files

- Decoder: `strategy_lab/wallet_hunt/cyclops_wallet_5d_2026_06_15.py`
- Cache: `strategy_lab/wallet_hunt/cache/_cyclops_5d/activity_raw.json`
- This handoff: `strategy_lab/reports/HANDOFF_CYCLOPS_5D_2026_06_15.md`
