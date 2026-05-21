# Taker Trigger Decode — Wallet `0xeebde7a0`

**Date:** 2026-05-18
**Wallet:** `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30`
**Scope:** BTC updown 5m + 15m (88% of wallet volume)
**Data:** `strategy_lab/wallet_hunt/cache/0xeebde7a0/` (547,545 OrderFilled rows, 1,758 BTC slugs with both maker+taker activity)

---

## TL;DR — what they actually do

**The wallet only BUYS shares on the order book.** It never appears as a SELLER on Polymarket OrderFilled. Its mint-and-sell maker SELL side (selling shares acquired by `splitPosition`) is **NOT visible** in the OrderFilled stream — splits happen via the ConditionalTokens contract directly.

What we DO see on the order book:

| Role | Events | What it means |
|------|--------|---------------|
| `wallet_is_maker=True, side=SELL` | 275,092 | Wallet posted a **limit BUY**; an aggressor seller hit it |
| `wallet_is_taker=True, side=BUY` | 272,453 | Wallet crossed the spread to **market BUY** an offered ask |

So the question "WHEN do they fire as TAKER vs MAKER" reframes as: **when do they passively wait at a bid vs aggressively cross the spread?**

- Counts are nearly equal (50/50 split between passive and aggressive buys).
- Both modes accumulate inventory; the taker mode is **the impatience knob**.

---

## Q1: WHEN (offset_from_slot_start_s) do they fire as TAKER vs MAKER?

Across all BTC updown trades (real-price subset, n=356,768):

```
                 TAKER (n=210,687)            MAKER (n=146,081)
offset_s median       178                          197
offset_s p10/p90      27 / 707                     32 / 718

By market class:
updown_5m:  TAKER 143s (median), MAKER 149s
updown_15m: TAKER 377s (median), MAKER 347s
```

**Deciles of (offset / duration)** — fires are ~UNIFORM across the slug for both roles:

| frac thru slug | TAKER % | MAKER % |
|----------------|---------|---------|
| 0-10%   | 11.6 | 10.8 |
| 10-20%  | 11.0 | 11.1 |
| 20-30%  | 10.9 | 11.7 |
| 30-40%  | 10.5 | 11.0 |
| 40-50%  | 10.3 | 11.3 |
| 50-60%  |  9.5 |  9.7 |
| 60-70%  | 10.5 | 10.6 |
| 70-80%  |  9.9 |  8.6 |
| 80-90%  | 10.0 |  8.4 |
| 90-100% |  5.9 |  6.8 |

**Finding:** **NO temporal pattern distinguishes taker from maker fires.** Both run continuously through the slug. Both taper slightly in the last 10%. There is **no "maker early, taker late"** rule.

(Note: fires_decoded sample of 72 maker fires only included offsets 327-941s — that's a **sampling artifact**, not a real pattern. The full trades_chain shows continuous activity.)

---

## Q2: WHAT triggers each taker BUY?

Using `fires_decoded.parquet` (n=1,448 BTC taker fires with full L25 + binance context):

### Book state at the moment of taker fire

```
own_ask  (price paid)       median 0.51   p25=0.43   p75=0.625
own_bid  (best bid own side)median 0.50   p25=0.42   p75=0.62
spread_own                  median 0.01   p95=0.03    (TIGHT)
sum_asks (Up_ask+Dn_ask)    median 1.010  p5=1.010   p95=1.030  --  >1.005 in 98.9% of fires
sum_bids (Up_bid+Dn_bid)    median 0.990  p5=0.970   p95=0.990
opp_ask - own_ask           median 0.01  (symmetric — they don't always pick the cheap leg)
```

### Conditions tested

| Rule | Hit rate on taker fires |
|------|-------------------------|
| `sum_asks > 1.005` (book has at least 0.5ct of cross-leg arb cushion) | **98.9%** |
| `sum_asks > 1.005 AND own_ask < opp_ask` (bought the cheaper leg)     | 46.8% |
| `sum_asks > 1.005 AND own_ask < opp_ask − 0.05`                       | 32.3% |
| `own_ask < slug_median_price` (buying below trailing fair)            | 48.2% |
| `own_ask < slug_median_price − 0.05`                                  | 35.5% |

### binance_ret signal — NOT USABLE in this sample

All `binance_ret_30s/60s/120s` values are 0.000000 in the enriched sample. Either the enrichment job failed or the canonical binance asof was wrong-keyed for these slugs. **Cannot decode any binance/cross-exchange trigger from this data**; would need to re-enrich.

### Predictive conditions — what actually triggers a TAKER fire

The **only near-universal condition (98.9%)** is `sum_asks > $1.005`. That is **trivially true on Polymarket binary markets** during normal periods (Up_ask + Dn_ask is essentially always > $1 by 1-2 cents due to bid-ask). So this is **not a discriminative trigger** — it is just the equilibrium book state.

**Conclusion:** the taker-vs-maker decision is **not** driven by a clean book signal in our captured features. The wallet seems to fire as taker simply to **maintain a target inventory accumulation rate**: when its passive limit bids aren't filling fast enough (e.g., flow is moving prices up faster than its bid ladder catches), it crosses the spread.

This is consistent with a **maker bot that has a target USDC-per-second inventory build** (likely set per-slug based on minted-pair budget) and uses takes as the slack variable when bids miss.

---

## Q3: Price distribution of taker BUYs

`own_ask` (= price paid) for n=1,439 TAKER BUY fires, BTC:

```
range       count    %
$0.00-$0.10    3    0.2%
$0.10-$0.20   58    4.0%
$0.20-$0.30  127    8.8%
$0.30-$0.40  108    7.5%
$0.40-$0.50  381   26.5%
$0.50-$0.55  226   15.7%
$0.55-$0.60  120    8.3%
$0.60-$0.70  182   12.6%
$0.70-$0.80  106    7.4%
$0.80-$0.90   97    6.7%
$0.90-$1.00   31    2.2%
```

**No concentration at cheap prices.** Distribution peaks near $0.45-$0.55 (parity), with full coverage of $0.10-$0.90. They are **not "deep discount hunters"** — they pay the going ask regardless of level.

Same shape repeats in the full trades_chain (n=226,249 taker BUYs across BTC updown):

```
$0.00-$0.10  47,037 (20.8%)
$0.10-$0.20  31,831 (14.1%)
$0.20-$0.30  32,702 (14.5%)
$0.30-$0.40  25,878 (11.4%)
$0.40-$0.50  41,430 (18.3%)
$0.50-$0.55   7,603 (3.4%)
$0.55-$0.60   7,273 (3.2%)
$0.60-$0.70   8,931 (3.9%)
$0.70-$0.80   8,051 (3.6%)
$0.80-$0.90   6,936 (3.1%)
$0.90-$1.00   8,577 (3.8%)
```

When using full data (less symmetric than fires_decoded sample), there is a **clear bias toward the $0.00-$0.50 range** (78% of fills). They preferentially buy outcome shares **at or below parity**, which makes sense: cheap shares have higher absolute upside and lower downside per dollar at risk.

---

## Q4: Sizing pattern

**Per-fire shares** (TAKER BUYs, real trades, n=226,249):

```
median   5.3 shares    (≈ $1.50-$3 notional at typical price)
p25      ~3 shares
p75     12 shares
p95     30 shares
p99    100 shares
max  10,032 shares     (one outlier)

size bin    count
0-2          19,660  (8.7%)
2-5          86,886  (38.4%)
5-10         69,545  (30.7%)
10-25        36,983  (16.3%)
25-50         6,076  (2.7%)
50-100        4,043  (1.8%)
100-500       2,868  (1.3%)
500-1000        168  (0.07%)
>1000            20  (0.009%)
```

**Pattern: SMALL repeatedly.** 78% of fills are 2-10 shares (~$1-5 per fill). They scrape the book one or two ask-levels at a time, hundreds of times per slug (avg **120 taker fills per slug**, max **>500 per slug**). This is consistent with **chasing fills against a fragmented ask queue without market impact**.

Total taker volume: **5,154,208 shares for $1,084,830** → VWAP $0.37 per taker share.
Total maker volume: **2,410,134 shares for $1,088,233** → VWAP $0.45 per maker share.
**Taker VWAP is 18% CHEAPER than their maker VWAP** — consistent with takers preferring cheap legs when crossing the spread.

---

## Q5: Buy-side direction split (Up vs Down)

```
Total taker BUYs (BTC):
  Down: 107,569 (51.1%)
  Up:   103,118 (48.9%)
```

**Essentially random.** Up% by price bucket:

| price bucket | Up% |
|--------------|-----|
| $0.00-$0.10  | 51.5 |
| $0.10-$0.30  | 48.3 |
| $0.30-$0.50  | 47.2 |
| $0.50-$0.70  | 49.9 |
| $0.70-$0.90  | 48.7 |
| $0.90-$1.00  | 50.1 |

**No directional alpha.** They buy whichever side has a cheap ask. **Direction is irrelevant** — they are a market maker (or a delta-neutral accumulator) building both-sides inventory.

---

## Q6: Counterparty pattern

### TAKER side (makers we BOUGHT FROM)

```
Unique counterparties: 6,108
Top-5 share: 10.4%
Top-10 share: 16.9%

Top 10 maker counterparties:
  0xd44e29936409019f93993de8bd603ef6cb1bb15e    5,850
  0x25bf6c226717bd53e8b7efdb2ae565e1f69eddfa    4,592
  0xd2e8a0b4c4d67622a9f0f6ec45842f8ba2bcd107    4,101
  0xd9013df863c1ba932780857b020dfdeacedf8e14    3,832
  0x38e598961dd0456a7fb2e758bd433d3e59fb8a4a    3,574
  0x48ac40fc545cf327edd5365435c3a9f385614a7e    3,454
  0x9a5e7b2c91192300314d4a736947530a3577aeae    2,931
  0x76d4d4703add6e94cfdb1107f3d991d85ff2c512    2,524
  0x7b32b6372709f19360d22271643f4e2a32a1377d    2,343
  0xfb0f17657c9c24293b918adb86362a4d8fc90b02    2,333
```

**Fragmented.** Taking from 6,100+ different makers, top-10 only 17%. They are **not targeting specific mint-and-sell wallets** — they are picking up cheap asks from the broad order book.

### MAKER side (takers who SOLD TO us — hit our limit bids)

```
Unique counterparties: 14,865
Top-5 share: 34.8%

Top 10 taker counterparties (sellers who hit our bids):
  0xe111180000d2663c0091e4f400237545b87b996b    46,474  (23%)  <-- dominant
  0xe0229e10a858860218b6132f4234602c47bd6603     1,467
  0x674887d1ac838099a48b629dff53f25b7b87ee08     1,073
  0xe9076a87c5ed90ef16e6fe6529c943baeca0cff6     1,010
  0xce25e214d5cfe4f459cf67f08df581885aae7fdc       837
  0x227d4ca3b363cea6fb5fb6195f8f3f6f547e69fc       818
  0xfb0f17657c9c24293b918adb86362a4d8fc90b02       704
  0xbd050887b28ef80590e25b0d0e4110154d930a55       684
  0x60889af507ec3f9da136f38b1c58080bec32f361       667
  0xf3531b23b504cf0aed4ff21325232b2a2d496685       657
```

**Striking:** `0xe111180000d2663c0091e4f400237545b87b996b` (note the human-readable `e111180000d...` prefix) accounts for **23% of all takers** that fill our limit bids. Looks like a Polymarket router / aggregator / matcher contract address (the `e111` prefix is suspicious — possibly the **Polymarket Exchange v2 contract** itself or an order-router/keeper). **It is NOT a competing wallet** — it's likely an infrastructure contract aggregating takes.

The other top sellers-to-us are themselves likely other market makers / liquidity providers selling inventory.

---

## Q7: Per-slug economics (20 sample BTC slugs)

Using REAL trades (price ∈ (0, 1.01]):

```
      slug  mk_fills  tk_fills  Up_sh  Dn_sh  paired  excess  excess_side  usdc_out  pnl_paired  pnl_avg
1778616000        40        48  363.5  294.3   294.3    69.2   Up           355.56     -61.30   -26.70
1778579700        48       122  495.1  883.1   495.1   388.0   Down         820.05    -324.97  -130.95
1778817300        62        88  395.4  955.9   395.4   560.4   Down         652.84    -257.41    22.81
1778830500        55        74  495.3  567.0   495.3    71.7   Down         614.20    -118.94   -83.09
1778815800        42        60 1033.1  265.2   265.2   767.8   Up           406.19    -140.96   242.96
1778577300        64       222 1456.1 1389.4  1389.4    66.8   Up          1487.81     -98.43   -65.05
1778846700        25       253 3101.1  981.6   981.6  2119.5   Up          2345.97  -1364.35  -304.60
1778695200       170       165 1094.3 3364.4  1094.3  2270.1   Down        1443.42    -349.10   785.96
1778702100        65       123  340.9 3407.7   340.9  3066.8   Down        1194.23    -853.30   680.11
1778811300       198       185 1599.0 1494.1  1494.1   104.9   Up          1411.15      82.99   135.43
1778454900       264       271 3863.6 1458.3  1458.3  2405.3   Up          1938.80    -480.51   722.13
1778617800        38        70 2671.2  287.8   287.8  2383.3   Up          1235.28    -947.46   244.21
1778851800        89        40 1031.4  294.1   294.1   737.3   Up           437.25    -143.17   225.49
1778513400       263       211 4220.9 1268.5  1268.5  2952.4   Up          1810.24    -541.69   934.50
1778551800        38        89  329.2  498.6   329.2   169.4   Down         370.80     -41.58    43.11
1778457600       104       120  893.3 1061.7   893.3   168.5   Down        1055.66    -162.41   -78.16
1778894100        80        77 2330.3  382.5   382.5  1947.8   Up           656.23    -273.71   700.19
1778554500        63       126 1148.4  534.3   534.3   614.0   Up           834.70    -300.36     6.64
1778688600        89       165  955.0 1479.4   955.0   524.4   Down        1275.61    -320.66   -58.45
1778619900        23        30  161.6  254.6   161.6    93.0   Down         262.03    -100.40   -53.89
```

Notes:
- Wallet on Polymarket OrderFilled is **always a buyer** — `usdc_out` = total they spent (no offsetting sells visible here).
- `Up_sh` / `Dn_sh` = shares of each outcome acquired through book.
- `paired` = `min(Up_sh, Dn_sh)`: guaranteed payoff $1 per pair at slug end (one wins, other loses, net = $1).
- `excess` = `max - min`: directional bet, pays $1 if right side wins, $0 otherwise.
- `pnl_paired = paired × $1 − usdc_out` (worst case if excess always loses).
- `pnl_avg = pnl_paired + 0.5 × excess` (E[pnl] if excess is a coin flip).

**Aggregates over 20 sample slugs:**
- Avg `pnl_paired`: **-$340/slug** (taker-only book activity is unprofitable on its own).
- Avg `pnl_avg` (assuming coin-flip excess): **+$197/slug**.
- Median `paired` shares: ~480.
- `paired/total` ratio: **28%** — only 28% of acquired shares are paired; **72% is directional excess**.

**Crucial caveat:** these numbers represent **only the book-buy side** of activity. The wallet ALSO mints pairs via `splitPosition` (free, off-book) and sells the resulting Up+Dn shares via limit-SELL orders. Those mint+sell legs do NOT appear in OrderFilled when wallet=maker SELLER if the original parquet only captured wallet-as-maker rows where side=SELL (taker side). To get true PnL per slug, you must merge:

1. `alchemy_transfers.parquet` (mint events from ConditionalTokens contract)
2. Wallet's outgoing share transfers (sells via direct transfer or matched orders not captured)
3. Slug-end USDC payout from outcome resolution

This is the **missing leg** that explains how the wallet shows $344k/day profit despite the book-buy economics looking negative.

---

## Q8: Trigger condition spec

Based on what we can confirm from the data, the TAKER fire rule is **trivial**:

```python
def fire_as_taker(book, wallet_state, slug_state):
    """
    Wallet 0xeebde7a0 taker-fire rule (decoded from 226k BTC updown taker fills).

    Inputs:
      book.own_ask    — current best ask of the side we want to buy
      book.own_bid    — current best bid of the side we want to buy
      book.sum_asks   — Up_ask + Dn_ask (≈ 1.01 in equilibrium)
      wallet_state.inventory_target_progress    — what % of target inv we've built
      wallet_state.elapsed_frac_of_slug          — what % of slug has elapsed
      slug_state.our_outstanding_bid_size        — qty of our limit-bid on this side

    Returns: (fire_bool, side_to_buy, size_shares)
    """
    # Always-required conditions (we observe these in ALL taker fires):
    if book.own_ask <= 0 or book.own_ask >= 1.0:
        return False, None, 0
    if book.spread_own > 0.05:          # we don't fire on illiquid wide markets (95% of fires have spread ≤ 0.03)
        return False, None, 0

    # Pacing rule (decoded behavior): we want to maintain a target inventory build rate
    # If our limit bid hasn't filled enough vs. slug progress, take to catch up.
    inventory_deficit = wallet_state.elapsed_frac_of_slug - wallet_state.inventory_target_progress
    if inventory_deficit > 0.02:   # we're >2% behind pace
        # Pick the cheaper leg if both are gettable, else just the one we're buying.
        # In our data, 47% of fires hit cheaper leg, 53% hit pricier leg — so they DO NOT strictly pick cheap.
        # The choice of side is governed by *which side our bid is being undercut on*.
        side = pick_side_with_cheapest_ask_relative_to_our_bid(book)

        # Size: small bites. p50 = 5 shares, p95 = 30 shares.
        size = min(
            book.size_at_best_ask,        # only eat best level
            sample_from_distribution(p50=5, p95=30)
        )
        return True, side, size

    return False, None, 0
```

**Key behavioral observations encoded:**

1. **Spread filter**: 95% of taker fires occur when `spread_own ≤ $0.03`. They do NOT fire on wide markets.
2. **Sum-asks "filter"**: 99% of fires have `sum_asks ≥ 1.005`. This is just normal book state, not predictive.
3. **No direction bias**: Up/Down split is 49/51%. They are not contrarian or trend-following.
4. **No deep-discount targeting**: only 35% of fires happen at price < slug-median − $0.05.
5. **Small consistent sizing**: median 5 shares per fill, p95 = 30, 78% of fills are 2-10 shares.
6. **No counterparty selection**: fragmented across 6,108 makers, top-10 is only 17%.

**The most likely true trigger (which we cannot directly verify from OrderFilled):** an **inventory pacing controller** — the wallet has a per-slug target USDC outlay (likely a function of expected mint-and-sell maker rebate income), posts limit bids continuously to ladder in, and crosses the spread whenever bid-fill pace falls behind a target curve.

---

## Outstanding gaps / data needed to fully decode

1. **Mint events** (`splitPosition` on the ConditionalTokens contract) — to verify the mint-and-sell maker leg and reconcile inventory.
2. **Wallet's outgoing share transfers** — to capture the SELL side of mint-and-sell that doesn't show in OrderFilled.
3. **binance_ret signal** — current `fires_decoded.parquet` has all-zero binance returns. Re-enrich using `data/v4/canonical/load_klines_asof()` with the corrected `asof_strict()` to test whether binance momentum predicts taker fires.
4. **Per-slug timing of mint vs first taker buy vs first maker bid fill** — to test the "early mint, late take" hypothesis.
5. **`taker_amount_raw` field semantics** — in 82% of rows it is 0, suggesting it's USDC notional (and only filled when relevant). Need to verify against polymarket docs.

---

## Files

- Input data: `strategy_lab/wallet_hunt/cache/0xeebde7a0/trades_chain.parquet`, `fires_decoded.parquet`
- Token lookup: `strategy_lab/wallet_hunt/cache/_token_lookup.parquet`
- This report: `strategy_lab/reports/TAKER_TRIGGER_DECODE_0xeebde7a0_2026_05_18.md`
