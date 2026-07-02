# Wallet 0xb27bc932 — DECODE (HFT market-maker) — 2026-06-16

**Wallet:** `0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82` (the "$254k/day HFT scalper" flagged in CLAUDE.md as needs-decode; relay-exit wallet `0xf3cfb6a6…`).
**Verdict:** **professional high-frequency MARKET-MAKER on BTC/ETH up-down** — quotes both sides continuously within each 5m/15m window (~150 fills/window), captures spread + maker rebate, neutralizes inventory via merges + the relay wallet. **lb-api all-time +$690,366**, +$16,083/7d, +$1,874/1d on **$765k/day volume**. By far the biggest/most profitable wallet decoded.
**Scripts:** `wallet_hunt/profile_b27_fresh_2026_06_16.py`, `_b27_pair_check.py`. Prior cache: `cache/0xb27bc932/*` (May, hold-PnL was misleading — see §4).

---

## 1. Scale (FRESH Jun 17)

| | |
|---|---|
| Trades in a **43-minute** sample | **3,479 buys** (~80/min) |
| data-api sides | **BUY only** (0 SELL shown — exits are merges/relay, not visible as SELL) |
| **lb-api /profit** | 1d **+$1,874** · 7d **+$16,083** · **all-time +$690,366** |
| **lb-api /volume** | 1d **$765,319** · 7d **$4,585,967** |
| Return on volume | ~0.35%/day — classic thin-margin HFT MM |

## 2. Market-making signature (decisive)

- **100% of windows have BOTH Up & Down bought** (20/20 conds in sample) — two-sided quoting.
- **~149 buys per window** (median 147, max 251) — it re-quotes continuously through the 5m/15m window, not a single entry.
- **Full price-range fills**: entry px p10 **0.05** → median **0.54** → p90 **0.82**. It quotes across the whole book (bids at many levels), not a favorite/longshot bias.
- **Tiny clips**: median **$3** / ~8 shares, max $24. Many small maker fills.
- **Fires throughout the window**: offset p10 41s → median 197 → p90 359 (no fixed timing — continuous).
- Balanced-ish both sides: Up 1657 / Down 1822; per-window Up/Down notional balance median 0.44 (takes some directional inventory, then hedges/exits).
- Markets: **BTC 5m (1306), ETH 5m (1125), BTC 15m (448)** — pure BTC/ETH crypto up-down. (Contrast 13f0bcec which sweeps all sports/esports.)

## 3. It is NOT rebalancing-arb

Paired **sum_vwap (Up+Down) = mean 1.168, median 1.170**; only 10% of paired conds < $1.00. So it is **not** buying both sides for <$1 (the static rebalancing arb from the AFT paper). It pays ~1.17 on its *buy* legs on average — which alone loses. **The profit is on the EXIT side** (sell at the ask / merge / relay distribution): it earns the **bid-ask spread + maker rebate**, classic MM, not arb.

## 4. Why the data-api view (and the old May decode) is misleading

b27's `/activity` shows **buys only, no sells**. The May cache (`strategy_deepdive.json`) computed a hold-to-resolution PnL of −$2,007 and buy-WR 36.6% — **wrong framing**: the wallet does not hold. Its round-trip is **buy (b27) → exit via OrdersMerged or the relay wallet `0xf3cfb6a6`**, so the sell leg never appears under b27 on data-api. Hold-PnL is meaningless for an MM. **The only correct PnL is lb-api realized: +$690,366 all-time.** (Same lesson as ce25: don't infer PnL from a partial event view.)

## 5. What it is, and deployability

A **co-located, low-latency two-sided market-maker** on BTC/ETH up-down: posts bids/asks across the book all window, scalps the spread, captures maker rebate, manages inventory (directional skew bounded, neutralized via merges + a second wallet). $4.6M/wk volume, +$690k lifetime, smooth (positive 1d/7d/all).

**Deployability for us: NO (as-is).** Requires pro MM infra — sub-100ms quoting, order-book co-location (Polymarket CLOB AWS eu-west-2), live inventory/risk engine, two-wallet exit plumbing. This is the `0xb27bc932` archetype the project already knew about; now confirmed as **spread-capture MM, not a signal**.

**But — relevant to our own work:** this validates that **two-sided maker on BTC/ETH up-down is genuinely profitable at scale** (the thing our b945 queue-sim kept finding ≤0 at small scale). The gap is execution: b27 wins on **rebate + spread + volume + speed**, exactly the maker-fill/queue dynamics our offline feed can't model (memory `project_offline_feed_blind_to_edge`). If we ever pursue maker, b27 is the reference implementation to study — needs the persisted delta-stream + queue-position model, not our 1Hz book.

## 6. Open / next (if pursued)
- **Reconcile the relay** `0xf3cfb6a6`: pull its sells, match to b27 buys per cond → reconstruct true round-trip spread captured per window (cache already has `cache/0xf3cfb6a6/alchemy_transfers.parquet`).
- Confirm maker vs taker split on-chain (OrderFilled maker flag) — rebate share of the +$690k.
- Per-window inventory curve: how much directional risk it carries before neutralizing.
