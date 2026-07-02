# Wallet 0x13f0bcec — DECODE — 2026-06-16

**Wallet:** `0x13f0bcec1e2e60ec9acc3bee4d2da2fe9694a50f` (anonymous — pseudonym is just the address; created ~Mar 21 2026).
**Status:** NOT previously mapped. New.
**Strategy:** **near-resolution favorite SWEEP** — buys the ~certain winner at **~$0.99** in the final seconds, across **ALL** Polymarket markets (sports/esports/crypto), collects the last ~1¢ at resolution. High-volume, razor-thin edge, fat left tail. **lb-api all-time +$28,428** (positive, but terrifying variance).
**Scripts:** `wallet_hunt/profile_13f0bcec_2026_06_16.py` · cache `cache/0x13f0bcec/activity_raw.json`.

---

## 1. Scale (last ~3 days pulled: Jun 13 23:30 → Jun 16 23:00; /activity capped at 3,500 events)

| | |
|---|---|
| BUY trades | **3,055** ($1,374,273 cost) — ~1,000/day, ~$450k/day turnover |
| REDEEM | 442 ($1,380,247) |
| SELL | 0 (never sells — holds to resolution + redeems) |
| MAKER_REBATE | 3 (mostly taker) |
| lb-api realized | **1d +$639 · 7d +$1,538 · all-time +$28,428** |

This is **15,000× Cyclops's volume** ($1.37M vs $90). Different league entirely.

## 2. Strategy signature

- **Buys near-certain favorites at ~$0.99.** Size-weighted entry **0.9982**; **91.6% of capital deployed at ≥0.995**, 8.3% at 0.98–0.99. Essentially buying winners for 99¢.
- **Fires at the END of the window.** 5m-updown fire offset **median 295s** (p10 265, p90 331) — the last ~5–35s before close, when the outcome is all but decided.
- **Trades EVERYTHING, not crypto-specific.** Market mix by count: FIFA (fifwc 1065), **btc 598**, CS2 466, ATP tennis 407, WTA 175, MLB 115, Dota2 115, UFC 94, Valorant 72, LoL 67… **81% of cost is non-updown** (sports/esports), ~8% btc-5m.
- **Single-sided, no pairs** (0/432 slugs had both Up&Down — not pair-arb). No directional signal — it buys whatever is the near-locked favorite.
- **Heterogeneous size**: median $44, but $0.08 → **$62,136** single trade. It sweeps whatever depth exists at 0.99 (many split fills per slug at the same second/price).

## 3. Economics — "penny in front of the steamroller"

Matched resolved (431 conds in window):
- **WR 99.3%** (428 won / 3 lost… but 4 loss-events by size).
- **avg WIN +$5.60** · **avg LOSS −$864.31** → ~**154 wins to cover one loss**.
- Buy 0.99 → win pays 1.00 = **+1.01% gross**; lose = **−99%**. Breakeven WR at 0.99 ≈ 99.0%; at size-wtd 0.998 ≈ 99.8%.
- The edge is **knife-edge and tail-dominated**. Daily net-cash swings are violent: **Jun 14 −$58,870 · Jun 15 +$46,088 · Jun 16 +$18,732**.

⚠️ My 3-day **matched** PnL came out −$1,066 (−0.078%), but that's distorted by (a) **1,491 pending buys** whose winning redeems haven't posted yet (undercounts wins) and (b) **4 tail losses** (−$3.5k) landing in this short window. **lb-api is the truth: +$1,538/7d, +$28,428 all-time = net positive.** The strategy works on volume; individual 3-day windows can be sharply negative.

By entry bucket (matched, this window): 0.995–1.00 = +$1,260 on $1.26M (+0.1%); 0.98–0.99 = −$2,448 (the 0.98–0.99 band caught tail losses). Sports/other +$1,260 vs updown −$2,327 (window-specific; tail noise).

## 4. What this actually is

A **near-resolution liquidity-provision / favorite-sweep bot.** Holders of a winning position who want out *before* resolution (avoid the wait/redeem gas) sell at ~0.99; this wallet **buys their near-locked winner at 0.99 and collects the final cent on settlement**, thousands of times a day across every market type. Profit = (last ¢ × huge volume) − (rare favorite that flips × big size). Net positive long-run (+$28k), but:
- Requires **enormous capital** (~$450k+/day turnover) and **speed** (final-seconds fills across thousands of markets).
- Carries a **catastrophic tail** — one large 0.99 bet that flips = −$thousands (the −$864 avg loss, −$58.9k worst day).
- Edge per dollar is **~0.1%** — pure scale/microstructure play.

## 5. Deployability for us: NO
- Capital + infra (sweep 1,000 markets/day in the last seconds) far beyond our stack.
- Razor-thin ~0.1% edge with a fat left tail; one mis-sized flip erases weeks.
- No transferable *signal* — it's not predicting anything, just buying locked favorites. Nothing to clone into our scalp/directional fleet.
- **Banked as an archetype:** distinct from Cyclops (signal-driven favorite-hold) and from ce25/b945 (pair-arb/maker). This is **scale favorite-sweeping**.

## 6. Open / next (if pursued)
- True per-trade size-weighted PnL needs the **full history** (pull capped at 3,500 = ~3 days; wallet active since Mar). Pull via offset-paginated `/activity` in date chunks or Alchemy chain history for all-time reconciliation.
- Decode whether the profitable core is **maker** (posts 0.99 bids, earns rebate + spread) vs **taker** sweeping — only 3 MAKER_REBATE events suggest mostly taker, but verify on chain (OrderFilled maker flag).
- Identify the tail: what were the 4 big losses (which markets flipped at 0.99)? Risk-management decode.
