# Polymarket Maker Rebate Facts — 2026-06-11

**Sources fetched:** docs.polymarket.com/market-makers/maker-rebates, /trading/fees, /trading/taker-rebates, /api-reference/rebates/get-current-rebated-fees-for-a-maker  
**Fetch date:** 2026-06-11

---

## 1. Confirmed Facts (with sources + dates)

### 1.1 Taker Fee Formula — Crypto Markets

```
fee_USDC = C × feeRate × p × (1 − p)
```

- `C` = shares traded, `p` = price of shares
- **Crypto category `feeRate = 0.07`** (confirmed live in docs as of fetch 2026-06-11)
- **Maker fee rate = 0** — makers are never charged fees
- Formula is symmetric around p=0.50; a trade at 0.30 incurs the same dollar fee as one at 0.70
- Source: `docs.polymarket.com/trading/fees` (fetched 2026-06-11)

### 1.2 Maker Rebate Share — Crypto Category

- **Crypto markets: 20% of collected taker fees go to the maker rebate pool**
- All other categories (Sports, Finance, Politics, etc.) receive 25%
- Geopolitics = 0% (fee-free markets, no rebate)
- Source: `docs.polymarket.com/trading/fees` and `docs.polymarket.com/market-makers/maker-rebates` (fetched 2026-06-11)

### 1.3 Distribution Method — "Fee-Curve Weighted"

The rebate for each filled maker order is computed using the **same formula as the taker fee**:

```
fee_equivalent = C × feeRate × p × (1 − p)
```

- `C` = shares in the maker fill, `p` = fill price, `feeRate = 0.07` (for Crypto)
- Each maker's share of the daily pool = their `fee_equivalent` / sum of all `fee_equivalents` in that market on that day
- Rebates are **proportional to share of executed maker liquidity per market** — you compete only with other makers in the SAME market (not globally)
- Source: `docs.polymarket.com/market-makers/maker-rebates` (fetched 2026-06-11)

**What this means:** rebate is tied to FILLED maker volume, weighted by the fee-curve value at the fill price. A fill at p=0.50 carries maximum weight (0.07 × 0.50 × 0.50 = 0.01750). A fill at p=0.10 carries much less weight (0.07 × 0.10 × 0.90 = 0.00630).

### 1.4 Filled Volume Only — Not Resting Quote Uptime

- "You earn based on the share of liquidity you provided that actually got **taken**" (direct quote from docs)
- Eligibility: "Place orders that add liquidity to the book and get filled (i.e., your liquidity is taken by another trader)"
- No uptime/depth-weighting for resting quotes that never fill
- Source: `docs.polymarket.com/market-makers/maker-rebates` (fetched 2026-06-11)

### 1.5 Payment Mechanics

- **Daily in pUSD**, paid directly to wallet
- **Minimum payout threshold: $1 pUSD** per day (accruals below $1 not paid out that day)
- Payment time: **midnight UTC** (confirmed in taker rebates doc; maker docs say "daily" without specifying time — assume same midnight UTC cadence)
- No manual claim required — automatic
- Source: `docs.polymarket.com/market-makers/maker-rebates` (fetched 2026-06-11)

### 1.6 Eligibility — No API Tier or Volume Minimums

- No stated API access tier requirement for maker rebates
- No volume threshold stated (only the $1 payout minimum)
- Any wallet placing maker orders that get filled is eligible
- The old "Liquidity Rewards" program (separate, quota-based, pre-2026) is distinct from this fee-funded rebate program
- Source: `docs.polymarket.com/market-makers/maker-rebates` (fetched 2026-06-11)

### 1.7 Crypto Category Covers 5m/15m Up/Down Markets

- BTC/ETH/SOL crypto up/down binary markets fall under **"Crypto"** category
- Confirmed: Crypto has `feesEnabled = true`, taker fee rate 0.07, maker rebate 20%
- No special carve-out for short-duration (5m/15m) markets vs longer-duration crypto markets — all Crypto is treated the same category
- Source: `docs.polymarket.com/trading/fees` (fetched 2026-06-11)

### 1.8 Taker Rebate Program (NEW — live 2026-05-28)

- A separate **Taker Rebate Program** launched 2026-05-28 (tiered by 30-day Weighted Volume)
- Crypto taker weighted volume uses a **2.3× category weight** (highest of any category), encouraging taker activity
- This is a SEPARATE program from maker rebates — funded from a different pool (docs do not specify its source explicitly, but it appears distinct from the 20% maker pool)
- Both programs pay daily in pUSD at midnight UTC
- Source: `docs.polymarket.com/trading/taker-rebates` (fetched 2026-06-11)

### 1.9 API — Rebate Lookup Endpoint

```
GET https://clob.polymarket.com/rebates/current?date=YYYY-MM-DD&maker_address=0x...
```
- Returns per-market rebated fees in USDC for a given day
- No authentication required
- Response fields: `date`, `condition_id`, `asset_address`, `maker_address`, `rebated_fees_usdc`
- Source: `docs.polymarket.com/api-reference/rebates/get-current-rebated-fees-for-a-maker` (fetched 2026-06-11)

---

## 2. Unverified / Needs Dashboard Check

| Item | Status | Action |
|------|--------|--------|
| Exact rebate % for specific crypto 5m/15m condition IDs | UNVERIFIED | Call `getClobMarketInfo(conditionID)` for a live BTC-5m market; check `feeRate` and any market-level rebate override |
| Whether the 20% crypto rebate applies to BOTH sides of a binary market (UP token + DOWN token fills) or just one | UNVERIFIED | Check via `/rebates/current` on a day you had fills on both sides |
| Whether the $1 payout minimum applies per market or across all markets aggregated | UNVERIFIED | Check operator dashboard; docs say "minimum accrued rebate of $1 pUSD" without specifying scope |
| Whether the Taker Rebate Program (launched 2026-05-28) draws from the same 20% Crypto pool or is separately funded | UNVERIFIED | Not stated in docs — check Polymarket blog or Discord |
| Rebate rate stability — Polymarket explicitly states "rebate percentage is at the sole discretion of Polymarket and may change over time" | STRUCTURAL RISK | Monitor docs or changelog for changes |
| Any whitelist / approved maker API key requirement not stated in public docs | UNVERIFIED | Check via `market-makers/getting-started` page and operator dashboard |

---

## 3. Implications for Maker Strategy EV Model

### Rebate per $1 of filled notional at p = 0.50

Taker pays (per 1 share at p=0.50):
```
taker_fee = 0.07 × 0.50 × 0.50 = $0.0175 per share
```

Maker rebate pool (Crypto = 20% of taker fee):
```
rebate_pool_per_share = 0.20 × 0.0175 = $0.00350 per share filled
```

But the maker's actual rebate depends on their **share of that market's total maker fee-equivalents on that day**:
```
maker_rebate = 0.0035 × (your_fee_equivalent / total_market_fee_equivalent)
```

If you are the **only maker** filled in that market on a given day:
```
rebate = $0.00350 per share filled at p=0.50
       = $0.350 per $100 notional (0.35%)
```

In practice (competitive market with multiple makers), your share will be < 1.0.

### Fee-curve-weighted rebate at other prices

| p    | taker_fee/share | maker_rebate/share (sole maker) |
|------|-----------------|---------------------------------|
| 0.50 | $0.01750        | $0.00350                        |
| 0.60 | $0.01680        | $0.00336                        |
| 0.65 | $0.01593        | $0.00319                        |
| 0.70 | $0.01470        | $0.00294                        |
| 0.40 | $0.01680        | $0.00336                        |

**At our typical entry_vwap ≈ 0.55–0.65:**
- Sole-maker upper bound: **~$0.003–$0.0035 per share** (~0.30–0.35% of notional per fill)
- Realistic (competitive market, modest share): likely **$0.001–$0.002 per share**

### Net EV impact for scalp maker-exit strategy

If maker-exit fills $1 notional per trade at p=0.65:
- No taker fee paid (maker fee = $0)
- Rebate upside (competitive): +$0.001–$0.003 per $1 notional
- Compare to taker cost if using taker exit at same price: −$0.01593 per share
- Maker vs taker exit differential: **+$0.017 per share** = meaningful edge at scale

**Key caveat:** rebate is fill-dependent (no fill = no rebate). In thin 5m/15m markets where the resolution window is short, maker fills are not guaranteed, and unfilled maker exit = carry-to-resolution risk.

---

## 4. Changelog Note

- **Old Liquidity Rewards program** (pre-2026, quota-based quoting uptime scoring) is DISTINCT from this fee-funded rebate. The current program described here is the fee-curve-weighted maker rebates program documented as of 2026-06-11.
- **Taker Rebate Program** launched 2026-05-28 is NEW and separate — does not reduce the maker rebate pool (not confirmed, but implied by separate documentation sections).

---

*Sources fetched 2026-06-11 from docs.polymarket.com. Rebate % at sole discretion of Polymarket and may change without notice.*
