# Cyclops Bot Wallet Hunt — 2026-06-01

**Goal:** match the `cyclops_signals` Telegram channel's last-2-day signals to on-chain
Polymarket trades to identify the wallet executing them.

**Method:** parse SIGNAL posts (post_ts ≥ 2026-05-30) → reconstruct `btc-updown-5m-<slot_start>`
(EDT = UTC−4) → resolve each slug's `condition_id` via canonical `load_resolutions` → pull
`data-api.polymarket.com/trades?market=<condition_id>` (slug is silently ignored; conditionId
required) → match BUY trades on the signaled side, near entry_cents, in `[post_ts−10s, post_ts+120s]`
→ rank wallets, then validate the top candidate on direction-consistency, latency, fill price,
and trading profile.

Scripts: `strategy_lab/wallet_hunt/cyclops_wallet_{hunt,refine,validate}_2026_06_01.py`.
Cached API responses + intermediates: `strategy_lab/wallet_hunt/cache/_cyclops_hunt/`.

---

## 1. Last-2-day win rate

- **58 SIGNALs** (post_ts 2026-05-30 06:14 → 2026-05-31 19:03 UTC; slot range 05-30 06:10 → 05-31 19:00 UTC). Direction mix: 32 DOWN / 26 UP. All 58 had entry_cents.

| Source | W | L | WR | n |
|---|---|---|---|---|
| **Channel WIN/LOSS labels** (on signal slots) | 54 | 4 | **93.1%** | 58 |
| **Our chainlink truth** (`load_resolutions`) | 34 | 19 | **64.2%** | 53 |

5 signals too recent for canonical chainlink (resolutions max = Jun 1 08:55 UTC; those slugs still got trades via condition_id). The channel's advertised 93% is heavily inflated vs the 64% chainlink reality — consistent with prior cyclops findings (selective WIN/LOSS posting / cherry-picking).

---

## 2. Signal → trade match

- Condition IDs resolved: **53/53** from canonical `market_id` (0 gamma-fallback needed; 5 signals had no canonical row).
- Total trades pulled across 53 markets: **105,846**.
- Every signal slug had ≥1 candidate wallet (these are liquid 5m markets with hundreds of participants each), so raw "≥1 match" is uninformative — discrimination came from the **tight directional + latency** filter (below).

---

## 3. Ranked candidate wallets

Naive ranking (any BUY on signaled side, in window) surfaced market-makers that trade both sides
every slot. The discriminating ranking requires the wallet to be **one-sided on the signaled
direction** with **consistent post-time latency**:

| wallet | active slugs | one-sided dir | tight match | exec offset (med / std) | profile |
|---|---|---|---|---|---|
| **0xf69af0b9…39e7b5c** | 52/53 | **52/52 = signaled** | 22 (px-tight) | **+1s / 0.8s** | **100% BTC 5m, $11.5k vol** |
| 0x0c7c5204…12bae4cb | 52/53 | 37/52 (71%) | 23 | −80s / 61s | btc/sol/bnb/eth, $5.9M vol |
| 0xe9076a87… / 0x47c58c… / 0xbd0508… | 53/53 | both sides | — | — | market-makers |

The naive #1 (`0x0c7c52…`) trades **before** the post (median −80s) across 4 assets — a momentum
trader, not the channel executor. Disqualified.

---

## 4. VERDICT — single executor found

### **Cyclops wallet = `0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c`**

Validation (script `cyclops_wallet_validate_2026_06_01.py`, full per-slug table at
`cache/_cyclops_hunt/validate_0xf69af0b9.csv`):

- **Direction:** took the **signaled side on 52/52 active slugs = 100.0%**. One-sided every slug
  (never buys both Up and Down on the same market). Side always equals the channel's UP/DOWN.
- **Latency:** exec offset from post_ts — **median +1s, mean +0.9s, std 0.8s, range [−1, +2]s**.
  100% of fills land in [−10, +30]s. Sub-second, robotic consistency = automated execution keyed
  to the channel post. (The −1s edge is post-timestamp jitter, not lookahead.)
- **Coverage:** active on 52 of 53 signals (98%); the 1 miss is a single skipped slot.
- **Fill price:** earliest signaled-side fill is median −1.0c vs advertised entry_cents (it fills
  at-or-slightly-better than the quoted entry; 50% within ±3c — the channel quotes a target and the
  bot takes whatever the book gives ~1s later).
- **Profile (lb-api):** recent 500 TRADE events are **100% BTC 5m up-down** — trades nothing else.
  Lifetime volume **$11,497**, lifetime PnL **−$217.17** (30d −$2.25). A small-stake / paper-style
  mirror bot, not a profit center — consistent with it simply executing every channel call at ~$25
  notional and bleeding the 64%-real-WR edge after fees.

**Why this is the executor and not coincidence:** a wallet that (a) fires within 1±0.8s of the post,
(b) takes the exact signaled direction 52/52, (c) is one-sided every slot, and (d) trades *only*
BTC 5m up-down cannot be explained by independent trading. It is the cyclops channel's on-chain
executor.

---

## 5. Profile of the cyclops wallet

| window | profit | volume |
|---|---|---|
| all | **−$217.17** | **$11,497.10** |
| 30d | −$2.25 | $28.19 |
| 7d | −$2.25 | $114.23 |
| 1d | −$2.25 | $28.19 |

- Markets: **exclusively BTC 5m up-down** (500/500 recent trades).
- Behavior: directional taker, ~1s after channel posts, ~one fill per signal, signaled side only.
- Economics: net-negative lifetime — the channel's true ~64% chainlink WR does not overcome
  Polymarket entry pricing + fees at these stakes, matching the project's standing conclusion that
  cyclops is marginal-to-negative after fees.

---

## Caveats

- Chainlink WR (64.2%) covers 53/58 signals; 5 most-recent slots resolve after the canonical
  Jun 1 08:55 UTC cutoff.
- Fill-price tightness is loose by design (channel posts a *target* entry; the bot takes market ~1s
  later), so the price filter was not used to *establish* identity — direction (100%) + latency
  (std 0.8s) + single-market focus are the load-bearing evidence.
