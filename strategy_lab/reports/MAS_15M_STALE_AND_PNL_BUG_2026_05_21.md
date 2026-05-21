# MAS 15m "stale" + PnL formula bug + pUSD wallet shortfall — 2026-05-21

Three findings from the user's question. Two are real bugs, one is operator config.

---

## 1. MAS 15m is NOT stale — it's firing on EVERY slug. But it has ZERO maker fills.

### Evidence (per-slug trace of mas_2026-05-21.csv)

Every MAS 15m slug follows the EXACT same lifecycle:

```
MINT (synthetic + decision)                  → inv_up=30, inv_dn=30, cash_spent=30
POST_ASK up @ $0.51 size=10                  → posted, never filled
POST_ASK dn @ $0.50 size=10                  → posted, never filled
... (sometimes more POST_ASK if price moves)
REDEEM up size=30 @ $1 (sim_redeem_winner)   → cash_recovered=30, inv_up=0, inv_dn STILL =30
```

**12 MINT + 12 POST_ASK + 0 FILL + 12 REDEEM** across 7 slugs.

The strategy is firing correctly. The maker ASKs sit on the Polymarket book at $0.50/$0.51 and **never get hit by takers** during the 15-minute window. So MAS 15m functions as "mint pair + redeem winner side" with no maker rebate income.

### Why no fills?

On 15m markets the queue is deep (more competing makers) and price moves slower → our ASKs at best-ask price sit far back in the queue and the queue never fully drains during the slug. The fill_simulator's queue model (we go to the back of the queue at post time) is correctly modeling this.

5m markets DO get a few fills (10 FILLs across 18 slugs in mas_2026-05-21.csv) because the queue churns faster. 15m markets just don't churn that much.

### Is this a bug?

**No.** This is the actual MAS strategy hitting Polymarket's book reality. MAS's hypothesis (capture `sum_asks > $1` mispricing via passive maker fills) requires that taker BUYers occasionally walk up the book. On 15m BTC books they don't.

**Operator action**: either accept that MAS 15m makes $0/slug (only mint+redeem economics), or run MAS 5m only.

---

## 2. PnL formula bug — `residual × $0.50` mark applied incorrectly after REDEEM

### The bug

`shadow_log.py:307-317` computes per-row PnL with a mark-to-market component:

```python
paired = min(slug_state.inv_up, slug_state.inv_dn)
residual = abs(slug_state.inv_up - slug_state.inv_dn)
mark = paired * Decimal("1.0") + residual * Decimal("0.5")
pnl = (cash_received + cash_recovered + rebates_received
       - cash_spent - taker_fees_paid + mark)
```

The `residual × $0.50` assumes the residual inventory has **unknown outcome** (50/50). That's correct **before resolution** but **wrong after REDEEM**.

### Trace — why MAS 15m shows +$15/slug when the real economics are $0

For every MAS 15m slug at slug_resolved:
- `cash_spent=30` (mint cost)
- `cash_received=0` (no fills)
- `cash_recovered=30` (winner side redeemed: 30 shares × $1)
- `rebates_received=0`, `taker_fees_paid=0`
- `inv_up=0` (redeemed away)
- `inv_dn=30` (loser side residual — **stays in state because `on_slug_resolved` only zeros the winner side**)

Mark-to-market computation:
- `paired = min(0, 30) = 0`
- `residual = abs(0 - 30) = 30`
- `mark = 0 × 1.0 + 30 × 0.5 = $15.00` ← **WRONG — should be $0**
- `pnl = 0 + 30 + 0 - 30 - 0 + 15 = +$15.00`

**Reality**: the loser-side 30 shares are worth $0 (the loser leg is settled, has no value). The mark formula doesn't know the slug has resolved AND it doesn't know which side is the loser.

### Impact across all sleeves (NOT just MAS)

Every sleeve's `slug_pnl_so_far` at REDEEM rows is **inflated by `loser_residual × $0.50`**.

For sleeves with no maker fills (like MAS 15m): the entire reported PnL is the bug. **True PnL ≈ $0.**
For sleeves with fills: real PnL exists but is masked under the inflation.

### Re-estimate of actual May 21 PnL after removing the bug

| sleeve | reported pnl (bugged) | est. residual_mark inflation | actual pnl (approx) |
|---|---:|---:|---:|
| acc-h | +$12.15 | 14 redeems × ~$10 (residual ~20-shares × $0.50) | **−$130 to −$80** |
| acc-m | +$56.26 | 18 redeems × ~$10 | **−$120 to −$60** |
| acc-pc | +$27.76 | 10 redeems × ~$10 | **−$70 to −$30** |
| mas (5m) | +$213.78 | 18 slugs × ~$15 | **−$60 to +$0** |
| mas (15m) | +$90.00 | 7 slugs × $15 | **−$15 to +$0** |
| pat-shadow | −$74.34 | 17 slugs × maybe small (paired merges close inv) | **−$74 likely correct** |

The patches solved the **visibility** bug but introduced an **arithmetic** bug. The shadow numbers are still misleading, just in the opposite direction.

### Fix — patch the residual mark to be resolution-aware

**Option A (cleanest)**: at `on_slug_resolved`, zero out the loser-side inventory in addition to redeeming the winner:

```python
# acc_m.py / mas.py / acc_h.py / acc_pc.py on_slug_resolved
if evt.winner == "up":
    if state.inv_up > 0:
        decisions.append(Decision(action="REDEEM", side="up", size=state.inv_up, ...))
        state.cash_recovered += state.inv_up * Decimal("1.0")
        state.inv_up = Decimal(0)
+   # Loser side is worthless after resolution — clear inventory so the
+   # mark-to-market in shadow_log doesn't credit $0.50/share.
+   state.inv_dn = Decimal(0)
elif evt.winner == "dn":
    if state.inv_dn > 0:
        ...
        state.inv_dn = Decimal(0)
+   state.inv_up = Decimal(0)
```

**Option B**: in `shadow_log.py`, skip the mark when the slug is resolved (add `slug_state.is_resolved` flag, default False, set True in `on_slug_resolved`).

**Option A is recommended** — keeps the formula simple and aligns SlugState with reality.

### Tests to add

```python
def test_loser_residual_zeroed_after_resolution():
    state = SlugState(...)
    state.inv_up = Decimal(30)
    state.inv_dn = Decimal(30)
    state.cash_spent = Decimal(30)
    strategy.on_slug_resolved(SlugResolved(slug=..., winner="up"))
    # Winner side redeemed → inv_up = 0
    # Loser side cleared → inv_dn = 0
    assert state.inv_up == Decimal(0)
    assert state.inv_dn == Decimal(0)
    # Real PnL: 0 + 30 cash_recovered + 0 - 30 cash_spent + 0 mark = 0
    assert state.cash_recovered == Decimal(30)

def test_pnl_zero_for_mas_15m_without_fills():
    """Reproduce the bug: mint+redeem with no fills should be ~$0 PnL."""
    state = SlugState(...)
    state.cash_spent = Decimal(30)         # mint cost
    state.cash_recovered = Decimal(30)     # winner redeem
    state.inv_up = Decimal(0)              # winner cleared
    state.inv_dn = Decimal(0)              # loser cleared (post-fix)
    pnl_row = logger._row_from_decision(redeem_decision, sim_fill=True, slug_state=state)
    assert abs(float(pnl_row["slug_pnl_so_far"])) < 0.01  # should be ~0, not +$15
```

---

## 3. pUSD wallet under-funded on live momo mirror

### The error

Polymarket CLOB API rejecting orders with:
```
status_code=400, error_message={'error': 'not enough balance / allowance:
the balance is not enough -> balance: 1902191, order amount: 2100260'}
```

### Decoding

Both numbers are in **6-decimal pUSD micro-units** (USDC.e on Polygon is 6-decimal):

| field | micro-units | pUSD |
|---|---:|---:|
| wallet balance | 1,902,191 | **$1.902191** |
| order amount | 2,100,260 | **$2.100260** |
| shortfall | −198,069 | **−$0.198 pUSD** |

### Why the order is $2.10 when notional is $1

`/etc/tv/tradingvenue.env`:
```
TV_POLY_LIVE_NOTIONAL_MOMO_USD=1.00
```

But Polymarket's `order_amount` is the **collateral** the order requires, not the notional. For a BUY order:
- price × size = collateral
- $1 notional / $0.51 price ≈ 1.96 shares
- But CLOB minimum is 5 shares → forced bump to 5 shares
- 5 shares × $0.42 (some lower price) ≈ $2.10 collateral

Or alternatively the order is for a fixed share count (e.g. 5 shares) and the wallet balance just happens to be below the share×price for current market prices.

### Confirmed: this is live momo, not maker-arb

The errors come from **`PolyApiException` on `/order` endpoint** — the live momo controller submitting real orders. Maker-arb is `TV_POLY_MAKER_SHADOW_MODE=true` (no real orders).

### Fix

Top up the live momo wallet by ≥ $5 pUSD (USDC.e on Polygon at address `0x2791bca1...`). The shortfall is only $0.20 but a buffer prevents frequent borderline failures.

Alternatively reduce the live momo notional further:
```
TV_POLY_LIVE_NOTIONAL_MOMO_USD=0.50   # was 1.00
```

(Though CLOB minimum of 5 shares means at very low notional you still need ~$2.10 collateral when price is in the $0.40-$0.60 range.)

### Confirm which wallet

Get the wallet address:
```bash
ssh vps_ireland 'grep -E "WALLET_ADDR|POLY_ADDRESS|live_mirror_wallet" /etc/tv/tradingvenue.env'
```

Then verify on-chain balance:
```
https://polygonscan.com/token/0x2791bca1f2de4661ed88a30c99a7a9449aa84174?a=<address>
```

---

## 4. Summary

| Issue | Severity | Owner |
|---|---|---|
| **PnL formula adds $0.50 mark to loser residual after resolution** — inflates every sleeve's PnL by ~$10-15/slug | **HIGH** — invalidates current shadow PnL numbers | TV agent (`shadow_log.py` or `on_slug_resolved` in all 5 strategies) |
| MAS 15m has 0 maker fills | LOW — strategy reality, not a bug | Operator decides whether to disable MAS 15m |
| Live momo wallet under-funded by $0.20 pUSD | MEDIUM — orders failing silently in logs | Operator tops up wallet OR reduces TV_POLY_LIVE_NOTIONAL_MOMO_USD |

The MAS 15m question is partly a strategy reality check (no fills in 15m) and partly a symptom of the PnL bug (the $15/slug shown is fake). The real MAS 15m PnL is **$0** — not stale, not bleeding, just structurally break-even when no taker hits the maker ASKs.

After the residual-mark fix lands, the May 21 sleeve numbers will likely look like:

| sleeve | reported May 21 | post-fix May 21 estimate |
|---|---:|---:|
| acc-h | +$12 | −$80 to −$130 |
| acc-m | +$56 | −$60 to −$120 |
| acc-pc | +$28 | −$30 to −$70 |
| mas 5m | +$214 | $0 to −$60 |
| mas 15m | +$90 | $0 to −$15 |
| pat-shadow | −$74 | −$74 (paired merges close inventory, mark ≈ 0) |

The "patch flipped everything positive" celebration yesterday was premature — the patches fixed observability but the new PnL field has its own bug.

Honest take: **shadow PnL is still not trustworthy**. After the residual-mark fix, the data finally tells the truth. Until then, the per-trade economics from cash columns (cash_received − cash_spent + cash_recovered − fees + rebates) are the only reliable signal.
