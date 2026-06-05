# "Lock-the-lag" hypothesis test — 2026-05-29

> **Hypothesis (user):** the wallet buys the leading side cheap (Up@66¢), waits for the
> binance→oracle lag to fill (Up→77¢, Down→23¢), then completes the set by buying the OTHER
> side cheap (Down@23¢) → matched pair = 89¢ → redeems $1 → **locked ~11¢ market-neutral**.
> **Test:** time-ordered FIFO complete-set matching of every BUY fill (not avg-per-side).
> **Script:** `strategy_lab/wallet_hunt/_decode_lock_pattern_2026_05_29.py`

## Verdict: REFUTED as the dominant/profitable mechanic. Pattern exists but nets NEGATIVE.

If the wallets locked guaranteed profit, matched-pair sums would be consistently **< $1** and
net-locked $ strongly **positive**. They are not.

| Wallet | matched pairs | pair-sum median | % sum<$1 (share-wtd) | NET locked $ (sample) | median leg gap |
|---|---:|---:|---:|---:|---:|
| **`0xeebde7a0`** (best, 5m/15m) | 2537 | **1.020** | **38.8%** | **−$961** | 78s |
| `0x0fe40e88` gobblewobble (daily) | 2176 | 1.020 | 41.4% | +$4,162 | 29,477s (8.2h) |
| `0x143732d8` (sports/neg-risk) | 326 | 0.851 | 100% | +$733 | 49,134s (13.6h) |
| `0xa42f127d` 5f5a (sports MM) | 343 | 1.010 | 47.8% | +$132 | 6,026s |
| `0x4ee29e4e` IH2P (price buckets) | 620 | **1.330** | 36.0% | −$6,544 | 2,246s |

### What the numbers mean
- **`eebde7a0` (the one trading your exact 5m BTC example): median matched-pair sum = 1.020, only
  38.8% of completions are < $1, and the matched-pair book NETS −$961** in the sample. The
  sum<1 "good locks" (+$1,460, mean +12.3¢) are **outweighed** by sum≥1 "loss locks" (−$2,421).
  → The wallet does **not** make money locking pairs. Its $825k profit comes from the **directional
  residual** (unmatched shares held to resolution: 61% raw / **84% $-weighted** WR — see
  `WALLET_DECODE_5WALLETS_2026_05_29.md` §1). The pairs are **capital churn**, slightly negative.
- The example sequences show completions going **both ways**: e.g. on `btc-updown-5m-1778905800`
  they buy Up@0.52 then Down@0.423 = **0.943 LOCK +5.7¢** (your pattern ✓) — but on the same/other
  slugs they buy Up@0.487 then Down@0.60–0.65 = **1.09–1.14 LOSS** (completing when the bet went
  WRONG). It is oscillation-driven accumulation, not a disciplined sum<$1 lock.
- **gobblewobble's** "pairs" have **8-hour gaps** — that's a daily market trending all day, not a
  5–20s lag fill. Net +$4,162 on pairs is tiny vs its $408k (again: profit = directional residual).
- **`143732d8`'s** 100%-sum<1 is the **neg-risk / multi-outcome basket** structure (buy NO across
  mutually-exclusive sports outcomes), NOT a binary lag-lock — and that wallet is **losing**
  (−$9.3k/30d). `IH2P`'s 1.33 median is multi-bucket markets where the two legs aren't complementary.

## Why it is NOT free money (the EV argument)
You cannot escape directional risk by "locking when right":
- **When right** (your leg appreciates): you CAN complete the other side cheap → lock a **small**
  gain (+5–12¢), which **caps** the larger gain you'd have made holding to resolution.
- **When wrong** (your leg falls): to "complete" you'd buy the other side **expensive** → sum>$1 →
  lock a **loss**; or you skip completing and hold the losing leg = the same directional loss.
- So a disciplined "lock-only-when-sum<1" rule = **directional bet with capped winners + full
  losers = LOWER EV than just holding** the lag bet. The data confirms it: completing both ways
  nets negative; completing one way just relocates the loss to the held leg.
- **Execution reality:** the realistic-fill test (`LATENCY_EDGE_FINDING_2026_05_29.md`) found the
  opposite-side ask **reprices before you can complete cheap** — realistic pair cost ~**$1.09**,
  not <$1. By the time Up is 0.77, Down's *ask* is already ~0.25+, so sum ≈ 1 + two spreads.

## Recommendation
**Keep the V2 plan as a directional taker held to resolution + conviction sizing. Do NOT add a
"complete-the-set-to-lock" rule** — the evidence shows it is EV-negative (caps winners, keeps
losers, and the book reprices the second leg too fast to get sum<$1 reliably). The genuine,
profitable edge in `eebde7a0` is the **directional residual on the lag**, which V2 already targets.

The only place sum<$1 buying is real and consistent is the **neg-risk basket** on multi-outcome
markets (143732d8) — a different strategy on different markets, and currently unprofitable.
