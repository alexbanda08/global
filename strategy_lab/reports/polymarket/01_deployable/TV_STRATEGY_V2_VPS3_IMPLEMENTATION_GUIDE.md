# Tradingvenue — Polymarket UpDown Strategy V2 (VPS3 Deployment Guide)

**Audience:** TV agent implementing V2 on a new box (VPS3) in parallel to the existing deployment.
**Purpose:** ship the validated `sig_ret5m` strategy with HYBRID hedge exit and structured audit trail.
**Self-contained:** all strategy logic, code patches, config, and verification gates required to bring up V2 from a clean install. Zero references to legacy v1 internals.

**Source of validation:** 5,742 markets across BTC/ETH/SOL × 5m+15m, Apr 22-27, 2026. Realistic L10 book-walking backtest + 4-policy fallback sweep + Spearman Rank-IC validation. All recommended cells have 95% CI strictly above zero on holdout.

---

## TL;DR — what the strategy does

1. **At each market's `window_start`**, fetch the OKX/Binance close NOW and 5 minutes ago for the matching asset (BTC/ETH/SOL). Compute `ret_5m = log(close_now / close_5m_ago)`.
2. **Bet UP** if `ret_5m > 0`, **bet DOWN** if `ret_5m < 0`. Place a CLOB taker buy of the chosen token at the current ask, $25 USD notional.
3. **Run two firing modes in parallel** — `volume` (every signal fires) and `sniper` (top 10% on 5m, top 20% on 15m by `|ret_5m|`).
4. **Every ~10s while a position is open**, check the latest 1-min close. If price has reversed by ≥5 basis points against signal → execute the **HYBRID hedge**:
   - Try buy-opposite-token at its ask. If filled → hold both legs to resolution.
   - If opposite-side asks empty/rejected → sell own held side at its bid.
   - If both fail → ride to natural resolution (last resort).
5. **After resolution**, call `redeemPositions()` on the CTF contract for any winning tokens still held. Background worker, polls every 30s.

The only on-chain interaction is **redemption**. Entries, hedges, and bid-side exits all go through the CLOB.

---

## 1. The signal — `sig_ret5m`

### Definition

```python
# At window_start (start of the 5m or 15m prediction window):
btc_now    = binance_close_at_or_before(window_start)
btc_prior  = binance_close_at_or_before(window_start - 300)  # always 5min ago
ret_5m     = log(btc_now / btc_prior)

if ret_5m > 0:
    side = "UP"
elif ret_5m < 0:
    side = "DOWN"
else:
    side = "NONE"  # extremely rare; skip
```

For ETH and SOL up-down markets use `BINANCE_SPOT_ETH_USDT` and `BINANCE_SPOT_SOL_USDT` 1MIN closes. **Asset feed must match market asset** — BTC closes cannot predict ETH outcomes.

### Why it works

Polymarket settles via Chainlink Data Streams which lags Binance by 4–12 seconds. Binance is the price-discovery venue (~35–45% of crypto spot+futures volume). The previous 5 minutes of Binance return is a leading indicator of the next 5–15 minutes of Chainlink-settled price.

### Two firing modes

Both run in parallel as separate sleeves.

**Mode A — `volume` (every signal fires):**
- No threshold filter. Bet on every market where `ret_5m != 0`.
- ~285 trades/day per asset (~860/day combined).
- Backtest hit rate: 57.6% (5m), 54.5% (15m).
- Backtest mean PnL/trade @ $25: +$3.40 (5m), +$4.37 (15m).

**Mode B — `sniper` (top-tail filter, timeframe-specific quantile):**
- Only fires when `|ret_5m|` clears the rolling threshold.
- **5m markets → q10** (90th percentile of |ret_5m|).
- **15m markets → q20** (80th percentile).
- Threshold computed daily from a **rolling 14-day window** of completed markets for the same `(asset, tf)`.
- Cold start: <50 historical samples → return NONE in sniper mode.
- ~9 trades/day per asset on 5m, ~18 on 15m (~80/day combined).
- Backtest hit rate: 72.7% (q10 5m ALL), 67.4% (q20 15m ALL).
- Backtest mean PnL/trade @ $25: +$8.63 (q10 5m), +$7.86 (q20 15m).

Sniper trades are a strict subset of volume — same market never double-fires because slot tracking dedupes by `(symbol, tf, window_start_unix)`.

---

## 2. Entry logic

At each market's `window_start`:

```python
async def on_window_start(symbol: str, tf: str, condition_id: str):
    # 1. Compute signal
    aux = await build_signal_aux(symbol, window_start_unix)
    direction = strategy.signal(aux=aux)
    if direction == "NONE":
        return

    # 2. Resolve token_id for the chosen direction
    yes_token, no_token = await load_clob_token_ids(condition_id)
    token_id = yes_token if direction == "UP" else no_token

    # 3. Place taker buy at $25 USD notional
    result = await executor.place_entry_order(
        token_id=token_id,
        notional_usd=Decimal("25"),     # USD intent (NOT shares)
        limit_px=Decimal("0.99"),       # cross the spread aggressively
        sleeve_id=sleeve_id,
        side="buy",
    )

    # 4. Track open Slot if filled or partial
    if result.status in (FillStatus.FILLED, FillStatus.PARTIAL):
        slot = Slot(
            sleeve_id=sleeve_id,
            symbol=symbol,
            tf=tf,
            condition_id=condition_id,
            yes_token_id=yes_token,
            no_token_id=no_token,
            signal=direction,
            entry_price=Decimal(result.raw_response["avg_price"]),
            entry_qty=Decimal(result.raw_response["filled_shares"]),
            entry_cost_usd=Decimal(result.raw_response["filled_usd"]),
            btc_close_at_ws=aux["close_at_ws"],
            window_start_unix=window_start_unix,
            binance_symbol_id=aux["binance_symbol_id"],
            status="open",
        )
        self._slots[(symbol, tf, window_start_unix)] = slot
        await audit_event("order_placed", slot, fill_status="filled",
                          fill_price=str(slot.entry_price), fill_qty=str(slot.entry_qty))
```

**Critical:** `place_entry_order` takes `notional_usd` (USD), not `qty` (shares). The executor walks the book consuming USD until the notional is exhausted; final `filled_shares` = sum of (notional_per_level / price_per_level).

### Sniper threshold computation

```python
async def fetch_or_compute_threshold(symbol: str, tf: str, ws_s: int) -> float | None:
    """Rolling 14-day quantile of |ret_5m|. Per-tf percentile:
       - 5m → 0.90 (q10, top 10%)
       - 15m → 0.80 (q20, top 20%)
    Cache: keyed by (symbol, tf, day), TTL 24h.
    """
    cache_key = (symbol, tf, ws_s // 86_400)
    if (val := self._threshold_cache.get(cache_key)) is not None:
        return val

    quantile = 0.90 if tf == "5m" else 0.80
    rows = await db.fetch_abs_ret_5m_history(
        symbol_id=BINANCE_SYMBOL_MAP[symbol], tf=tf,
        from_s=ws_s - 14 * 86_400, until_s=ws_s,
    )
    if len(rows) < 50:
        return None  # cold start — sniper returns NONE
    threshold = float(numpy.quantile(rows, quantile))
    self._threshold_cache[cache_key] = threshold
    return threshold
```

---

## 3. Exit logic — HYBRID hedge

Every ~10 seconds while a position is open, the controller's `on_tick` calls `_maybe_hedge` for each open slot.

### Algorithm

```python
REV_BP_THRESHOLD = 5             # basis points
HEDGE_RETRY_ATTEMPTS = 3
HEDGE_RETRY_BACKOFF_S = 0.2
STALE_BINANCE_FEED_SECONDS = 120

async def _maybe_hedge(self, slot: Slot) -> None:
    """HYBRID exit: try buy-opposite-ask → fallback sell-own-bid → hold."""

    # --- Reversal-trigger detection ---
    if slot.btc_close_at_ws == 0 or slot.binance_symbol_id == "":
        return

    now_s = int(time.time())
    close_with_ts = await fetch_close_with_ts_asof(
        slot.binance_symbol_id, "1MIN", now_s, pool=self.pool
    )
    if close_with_ts is None:
        return
    btc_now, bar_us = close_with_ts

    bar_age_s = now_s - (bar_us // 1_000_000)
    if bar_age_s > STALE_BINANCE_FEED_SECONDS:
        await audit_event("hedge_check_skipped_stale_feed", slot,
                          extras={"bar_age_s": bar_age_s})
        return

    bps = float(
        (Decimal(btc_now) - Decimal(slot.btc_close_at_ws))
        / Decimal(slot.btc_close_at_ws) * Decimal(10_000)
    )
    reverted = (
        (slot.signal == "UP" and bps <= -REV_BP_THRESHOLD)
        or (slot.signal == "DOWN" and bps >= REV_BP_THRESHOLD)
    )
    if not reverted:
        return

    # --- BRANCH 1: try hedge buy-opposite-ask ---
    opposite_outcome = "NO" if slot.signal == "UP" else "YES"
    opposite_token = slot.no_token_id if slot.signal == "UP" else slot.yes_token_id

    book_opp = await self._fetch_opposite_book(slot, opposite_outcome)
    if book_opp and book_opp.get("asks"):
        first_ask = book_opp["asks"][0]
        other_ask_price = Decimal(str(first_ask.get("price", "0")))
        if other_ask_price > 0:
            hedge_result = await self._try_hedge_with_retries(
                slot, opposite_token, other_ask_price
            )
            if hedge_result is not None and hedge_result.status in (
                FillStatus.FILLED, FillStatus.PARTIAL
            ):
                slot.status = "hedged_holding"
                slot.hedge_other_entry_price = other_ask_price
                slot.hedge_qty = Decimal(hedge_result.raw_response["filled_shares"])
                slot.hedge_cost_usd = Decimal(hedge_result.raw_response["filled_usd"])
                await audit_event("hedge_placed", slot, extras={
                    "branch": "hedge_ok",
                    "token_id": str(opposite_token),
                    "ask_price": str(other_ask_price),
                    "hedge_shares": str(slot.hedge_qty),
                    "hedge_cost_usd": str(slot.hedge_cost_usd),
                    "book_ts": book_opp.get("ts", 0),
                    "book_age_s": now_s - book_opp.get("ts", 0),
                    "asks_count": len(book_opp.get("asks", [])),
                    "bps_at_trigger": bps,
                })
                return

    # --- BRANCH 2: hedge failed → sell own held side at bid ---
    own_outcome = "YES" if slot.signal == "UP" else "NO"
    own_token = slot.yes_token_id if slot.signal == "UP" else slot.no_token_id

    book_own = await self._fetch_own_book(slot, own_outcome)
    if book_own and book_own.get("bids"):
        first_bid = book_own["bids"][0]
        own_bid_price = Decimal(str(first_bid.get("price", "0")))
        if own_bid_price > 0:
            tick = (Decimal("0.001") if own_bid_price > Decimal("0.96")
                    or own_bid_price < Decimal("0.04") else Decimal("0.01"))
            sell_limit = max(own_bid_price - tick, Decimal("0.001"))
            try:
                exit_result = await self.executor.place_exit_order(
                    token_id=own_token,
                    shares=slot.entry_qty,
                    limit_px=sell_limit,
                    sleeve_id=slot.sleeve_id,
                )
            except Exception:
                exit_result = None

            if exit_result is not None and exit_result.status in (
                FillStatus.FILLED, FillStatus.PARTIAL
            ):
                slot.status = "exited_at_bid"
                slot.exit_price = own_bid_price
                slot.exit_proceeds_usd = Decimal(
                    exit_result.raw_response.get("proceeds_usd", "0")
                )
                slot.exit_shares = Decimal(
                    exit_result.raw_response.get("sold_shares", "0")
                )
                await audit_event("exited_at_bid", slot, extras={
                    "branch": "fallback_bid",
                    "token_id": str(own_token),
                    "bid_price": str(own_bid_price),
                    "shares_sold": str(slot.exit_shares),
                    "proceeds_usd": str(slot.exit_proceeds_usd),
                    "book_ts": book_own.get("ts", 0),
                    "book_age_s": now_s - book_own.get("ts", 0),
                    "bps_at_trigger": bps,
                })
                return

    # --- BRANCH 3: both failed → ride to natural resolution ---
    slot.status = "held_no_hedge_no_exit"
    await audit_event("hedge_and_exit_both_failed", slot, extras={
        "branch": "ride_to_resolution",
        "opp_token_id": str(opposite_token),
        "own_token_id": str(own_token),
        "opp_book_ts": book_opp.get("ts", 0) if book_opp else 0,
        "own_book_ts": book_own.get("ts", 0) if book_own else 0,
        "opp_asks_count": len(book_opp.get("asks", [])) if book_opp else 0,
        "own_bids_count": len(book_own.get("bids", [])) if book_own else 0,
        "bps_at_trigger": bps,
    })
```

### Helpers

```python
async def _fetch_opposite_book(self, slot, opposite_outcome) -> dict | None:
    """Fetch book for the opposite-side token (for hedge buy attempt)."""
    get_for_outcome = getattr(self.executor, "get_orderbook_for_outcome", None)
    if get_for_outcome is not None:
        try:
            return await get_for_outcome(slot.condition_id, opposite_outcome)
        except Exception:
            pass
    token_id = slot.no_token_id if slot.signal == "UP" else slot.yes_token_id
    if token_id is None:
        return None
    try:
        return await self.executor.get_orderbook_snapshot(token_id)
    except Exception:
        return None

async def _fetch_own_book(self, slot, own_outcome) -> dict | None:
    """Fetch book for our held-side token (for bid-fallback exit)."""
    get_for_outcome = getattr(self.executor, "get_orderbook_for_outcome", None)
    if get_for_outcome is not None:
        try:
            return await get_for_outcome(slot.condition_id, own_outcome)
        except Exception:
            pass
    token_id = slot.yes_token_id if slot.signal == "UP" else slot.no_token_id
    if token_id is None:
        return None
    try:
        return await self.executor.get_orderbook_snapshot(token_id)
    except Exception:
        return None

async def _try_hedge_with_retries(self, slot, token_id, ask_price) -> OrderResult | None:
    """Place hedge buy with up to HEDGE_RETRY_ATTEMPTS retries (200ms backoff)."""
    last_exc = None
    for attempt in range(HEDGE_RETRY_ATTEMPTS):
        try:
            result = await self.executor.place_entry_order(
                token_id=token_id,
                notional_usd=slot.entry_qty * ask_price,  # match held shares
                limit_px=ask_price + Decimal("0.01"),     # 1 tick above to ensure fill
                sleeve_id=slot.sleeve_id,
                side="buy",
            )
            if result.status in (FillStatus.FILLED, FillStatus.PARTIAL):
                return result
            last_exc = result
        except Exception as exc:
            last_exc = exc
        await asyncio.sleep(HEDGE_RETRY_BACKOFF_S)
    return None
```

---

## 4. Resolution accounting

Three terminal states for a slot:

### State A: `hedged_holding` (HYBRID branch 1 succeeded)

Position is delta-neutral (held YES + bought NO, or vice versa). Both legs settle on-chain at resolution. Exactly one pays $1, the other pays $0.

```python
def pnl_hedged(slot, outcome) -> Decimal:
    sig_won = (slot.signal == "UP" and outcome == "Up") or \
              (slot.signal == "DOWN" and outcome == "Down")
    matched = min(slot.entry_qty, slot.hedge_qty)
    if sig_won:
        # Held side wins. Per-share payout = $1 minus 2% fee on (1 - entry_price) profit.
        payout = matched * (Decimal("1.0") - (Decimal("1.0") - slot.entry_price) * Decimal("0.02"))
    else:
        # Hedge side wins. Per-share payout = $1 minus 2% fee on (1 - hedge_price) profit.
        payout = matched * (Decimal("1.0") - (Decimal("1.0") - slot.hedge_other_entry_price) * Decimal("0.02"))
    # Any unmatched held shares resolve normally (no hedge cover)
    unmatched = slot.entry_qty - matched
    if unmatched > 0 and sig_won:
        payout += unmatched * (Decimal("1.0") - (Decimal("1.0") - slot.entry_price) * Decimal("0.02"))
    total_cost = slot.entry_cost_usd + slot.hedge_cost_usd
    return payout - total_cost
```

Both legs of a hedged position need `redeemPositions()` after on-chain resolution.

### State B: `exited_at_bid` (HYBRID branch 2 succeeded)

Position closed off-chain via CLOB sell. PnL = proceeds − entry cost. **No on-chain redemption needed** — the held tokens were already sold to a counterparty.

```python
def pnl_exited(slot) -> Decimal:
    return slot.exit_proceeds_usd - slot.entry_cost_usd
```

### State C: `held_no_hedge_no_exit` or open-at-resolution unhedged

Single-leg position rides to resolution. Standard win/lose accounting.

```python
def pnl_unhedged(slot, outcome) -> Decimal:
    sig_won = (slot.signal == "UP" and outcome == "Up") or \
              (slot.signal == "DOWN" and outcome == "Down")
    if sig_won:
        gross = slot.entry_qty * Decimal("1.0")
        profit_pre_fee = gross - slot.entry_cost_usd
        fee = profit_pre_fee * Decimal("0.02") if profit_pre_fee > 0 else Decimal("0")
        return profit_pre_fee - fee
    return -slot.entry_cost_usd
```

---

## 5. Files to implement on VPS3

| File | Purpose |
|---|---|
| `backend/app/strategies/polymarket/base.py` | Abstract `PolymarketBinaryStrategy.signal(bars, config, aux=None)` |
| `backend/app/strategies/polymarket/updown_5m.py` | Concrete strategy: `Updown5mStrategy(mode="volume"\|"sniper")` |
| `backend/app/strategies/polymarket/updown_15m.py` | Identical to 5m (sniper threshold differs by tf, set in controller) |
| `backend/app/strategies/polymarket/market_mapping.py` | `resolve_condition_id(symbol, tf, signal_ts)` — DB query against `markets` table |
| `backend/app/controllers/polymarket_updown.py` | `on_bar_close`, `on_tick`, `_maybe_hedge` (HYBRID), `_fetch_opposite_book`, `_fetch_own_book`, `_try_hedge_with_retries`, `_audit` |
| `backend/app/venues/polymarket/paper.py` | `PolyPaperExecutor` — paper executor reading from `orderbook_snapshots_v2` |
| `backend/app/venues/polymarket/client.py` | `PolymarketClient` — live executor wrapping `py_clob_client_v2` |
| `backend/app/venues/polymarket/settings.py` | Config schema |
| `backend/app/services/redemption_worker.py` | `RedemptionWorker` — calls `redeemPositions()` post-resolution |
| `backend/app/venues/polymarket/ctf_abi.json` | Minimal ABI for `redeemPositions` |
| `backend/app/data/bars.py` | `fetch_close_asof(symbol_id, period, ts_s)` — Binance OKX 1MIN lookup |

### Strategy module (`updown_5m.py` / `updown_15m.py`)

Both files identical:

```python
import math
from typing import Literal
from backend.app.strategies.polymarket.base import PolymarketBinaryStrategy, SignalConfig

class Updown5mStrategy(PolymarketBinaryStrategy):  # or Updown15mStrategy
    """sig_ret5m strategy: bet sign of Binance 5m return at window_start.

    Sniper filter (timeframe-specific quantile, set by controller):
      5m markets:  q10 (top 10%)
      15m markets: q20 (top 20%)
    """
    def __init__(self, mode: Literal["volume", "sniper"] = "volume") -> None:
        self.mode = mode

    def signal(self, bars, config, aux=None) -> Literal["UP", "DOWN", "NONE"]:
        if aux is None:
            return "NONE"
        ret_5m = aux.get("ret_5m")
        if ret_5m is None or not math.isfinite(ret_5m):
            return "NONE"
        if self.mode == "sniper":
            threshold = aux.get("abs_ret_5m_threshold")
            if threshold is None or abs(ret_5m) < threshold:
                return "NONE"
        if ret_5m > 0:
            return "UP"
        if ret_5m < 0:
            return "DOWN"
        return "NONE"
```

### Controller — signal-aux build

```python
async def _build_signal_aux(self, symbol: str, window_start_us: int) -> dict:
    sym_id_map = {
        "BTC": "BINANCE_SPOT_BTC_USDT",
        "ETH": "BINANCE_SPOT_ETH_USDT",
        "SOL": "BINANCE_SPOT_SOL_USDT",
    }
    symbol_id = sym_id_map[symbol]
    ws_s = window_start_us // 1_000_000

    btc_now   = await self._db.fetch_close_asof(symbol_id, "1MIN", ws_s)
    btc_prior = await self._db.fetch_close_asof(symbol_id, "1MIN", ws_s - 300)

    ret_5m = None
    if btc_now and btc_prior and btc_prior > 0:
        ret_5m = math.log(float(btc_now) / float(btc_prior))

    abs_ret_5m_threshold = await self._fetch_or_compute_threshold(symbol, self.tf, ws_s)

    return {
        "binance_symbol_id":      symbol_id,
        "binance_close_at_ws":    btc_now,
        "binance_close_5m_before": btc_prior,
        "ret_5m":                 ret_5m,
        "abs_ret_5m_threshold":   abs_ret_5m_threshold,
    }
```

### Paper executor — book-walk semantics

The executor must walk the book consuming **USD notional**, not share count:

```python
async def _simulate(self, *, token_id, notional_usd, limit_px, side, sleeve_id, intent):
    book = await self._fetch_orderbook(token_id)
    book_ts = int(book.get("ts", 0))
    now = int(time.time())
    if book_ts == 0 or (now - book_ts) > STALE_AFTER_SECONDS:
        return OrderResult(status=FillStatus.REJECTED, intent=intent,
                           reason="STALE_ORDERBOOK", raw_response={"book_ts": book_ts})

    levels = book["asks"] if side == "buy" else book["bids"]
    remaining_usd = notional_usd
    filled_shares = Decimal("0")
    notional_paid = Decimal("0")
    for level in levels:
        px = Decimal(str(level.get("price", "0")))
        sz = Decimal(str(level.get("size", "0")))
        if side == "buy" and px > limit_px: break
        if side == "sell" and px < limit_px: break
        if px <= 0 or sz <= 0: continue
        level_notional = px * sz
        if level_notional >= remaining_usd:
            shares_here = remaining_usd / px
            filled_shares += shares_here
            notional_paid += remaining_usd
            remaining_usd = Decimal("0")
            break
        filled_shares += sz
        notional_paid += level_notional
        remaining_usd -= level_notional

    if filled_shares == 0:
        return OrderResult(status=FillStatus.REJECTED, intent=intent,
                           reason="NO_LIQUIDITY_AT_LIMIT")

    avg_price = notional_paid / filled_shares
    is_partial = remaining_usd > Decimal("0.01")
    return OrderResult(
        status=FillStatus.PARTIAL if is_partial else FillStatus.FILLED,
        intent=intent,
        order_id=f"paper-{sleeve_id}-{int(time.time())}",
        raw_response={
            "filled_shares": str(filled_shares),
            "filled_usd":    str(notional_paid),
            "intended_usd":  str(notional_usd),
            "avg_price":     str(avg_price),
        },
    )
```

### Paper executor — `place_exit_order` (sell into bid)

```python
async def place_exit_order(self, *, token_id, shares, limit_px, sleeve_id):
    """Sell `shares` of `token_id` into the bid book."""
    book = await self._fetch_orderbook(token_id)
    book_ts = int(book.get("ts", 0))
    now = int(time.time())
    if book_ts == 0 or (now - book_ts) > STALE_AFTER_SECONDS:
        return OrderResult(status=FillStatus.REJECTED, intent="exit",
                           reason="STALE_ORDERBOOK")

    bids = book.get("bids", [])
    if not bids:
        return OrderResult(status=FillStatus.REJECTED, intent="exit",
                           reason="NO_BIDS")

    remaining_shares = shares
    sold_shares = Decimal("0")
    proceeds_usd = Decimal("0")
    for level in bids:  # bids in descending price order
        px = Decimal(str(level.get("price", "0")))
        sz = Decimal(str(level.get("size", "0")))
        if px < limit_px: break
        if px <= 0 or sz <= 0: continue
        take = min(remaining_shares, sz)
        sold_shares += take
        proceeds_usd += take * px
        remaining_shares -= take
        if remaining_shares <= 0:
            break

    if sold_shares == 0:
        return OrderResult(status=FillStatus.REJECTED, intent="exit",
                           reason="NO_LIQUIDITY_AT_LIMIT")

    avg_price = proceeds_usd / sold_shares
    is_partial = remaining_shares > Decimal("0.01")
    return OrderResult(
        status=FillStatus.PARTIAL if is_partial else FillStatus.FILLED,
        intent="exit",
        order_id=f"paper-{sleeve_id}-exit-{int(time.time())}",
        raw_response={
            "sold_shares":       str(sold_shares),
            "intended_shares":   str(shares),
            "proceeds_usd":      str(proceeds_usd),
            "avg_price":         str(avg_price),
        },
    )
```

### Live executor — `place_exit_order`

Wrap `py_clob_client_v2.create_and_post_order` with `side="SELL"`. Use `limit_px = best_bid - 1*tick_size` to ensure immediate cross. Mirror the same `OrderResult` shape so the controller doesn't branch on executor type.

---

## 6. Sleeve registration

```python
# In tv-engine/main.py (or sleeve-registration module):

SLEEVES = [
    "poly_updown_btc_5m",
    "poly_updown_eth_5m",
    "poly_updown_sol_5m",
    "poly_updown_btc_15m",
    "poly_updown_eth_15m",
    "poly_updown_sol_15m",
]

# Each sleeve gets TWO controllers — volume and sniper running in parallel
controllers = []
for sleeve_id in SLEEVES:
    asset, tf = sleeve_id.split("_")[-2], sleeve_id.split("_")[-1]
    for mode in ["volume", "sniper"]:
        strategy_cls = Updown5mStrategy if tf == "5m" else Updown15mStrategy
        controllers.append(PolymarketUpdownController(
            pool=pool,
            executor=paper_executor,            # or live_client in production
            mode=Mode.PAPER,                    # or Mode.LIVE
            strategy=strategy_cls(mode=mode),
            symbol=asset.upper(),
            tf=tf,
            sleeve_id=f"{sleeve_id}_{mode}",   # unique per (sleeve, mode)
            notional_usd=Decimal("25"),
            tiny_live_mode=False,
        ))
```

12 controllers total: 6 sleeves × 2 modes (volume + sniper).

---

## 7. Configuration — `/etc/tv/tradingvenue.env` on VPS3

```ini
# Database — match VPS3's storedata setup
TV_PG_DSN=postgresql://tradingvenue_ro@localhost:5432/storedata
TV_PG_POOL_MIN=4
TV_PG_POOL_MAX=20

# Strategy
TV_POLY_REV_BP_THRESHOLD=5
TV_POLY_HEDGE_POLICY=HYBRID
TV_POLY_HEDGE_FALLBACK_TO_BID=true
TV_POLY_STRATEGY_MODES=volume,sniper
TV_POLY_SNIPER_LOOKBACK_DAYS=14
TV_POLY_SNIPER_QUANTILE_5M=0.90
TV_POLY_SNIPER_QUANTILE_15M=0.80

# Asset feeds
TV_BINANCE_SYMBOLS=BINANCE_SPOT_BTC_USDT,BINANCE_SPOT_ETH_USDT,BINANCE_SPOT_SOL_USDT
TV_BINANCE_PERIOD=1MIN

# Sizing — start at $1 tiny-live, ramp per §10
TV_POLY_TINY_LIVE=true
TV_POLY_TINY_LIVE_NOTIONAL=1.00
TV_POLY_NOTIONAL_USD=25                # used after tiny-live phase

# Cache TTLs — tight, per-tf
TV_POLY_CONDITION_CACHE_TTL_5M=150
TV_POLY_CONDITION_CACHE_TTL_15M=450
TV_POLY_PAPER_STALE_AFTER_SECONDS=30
TV_POLY_PAPER_BOOK_CACHE_TTL=10

# Polymarket key (live mode only)
POLYMARKET_PRIVATE_KEY=<your wallet private key, 0x-prefixed hex>
POLYMARKET_FUNDER_ADDRESS=<proxy wallet address if using signature_type=2>

# Polygon RPC for redemption worker
TV_POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/<YOUR_ALCHEMY_KEY>
TV_POLYGON_FALLBACK_RPC=https://polygon-rpc.com
TV_POLYGON_CHAIN_ID=137
TV_REDEEM_POLL_INTERVAL_S=30
TV_MATIC_LOW_THRESHOLD=0.2

# Audit / logging
TV_AUDIT_PUBLISH_BAR_PROCESSED=true
```

---

## 8. Polymarket-specific operational details

### 8.1 Minimum order size

Polymarket supports fractional shares. No formal minimum on the protocol; only practical floor is liquidity. `book.min_order_size` is a per-market hint (often <$1).

```python
qty = Decimal(notional_usd) / Decimal(entry_price)
qty = qty.quantize(Decimal("0.000001"))
if book.min_order_size and qty < Decimal(book.min_order_size):
    log.info("trade_skipped_below_min", slot=slot.id, qty=qty, min=book.min_order_size)
    return
```

### 8.2 Tick size

Returned per-market as `book.tick_size`. Typically 0.01; switches to 0.001 when price > 0.96 or < 0.04.

```python
def round_to_tick(px: Decimal, tick: Decimal) -> Decimal:
    return (px / tick).quantize(Decimal("1")) * tick
```

Round all `limit_px` values before submitting orders.

### 8.3 Standard binary CTF

Our BTC/ETH/SOL UpDown markets are standard binary (`market.neg_risk == false`). Use standard CLOB endpoints. **Negative-risk adapter is NOT needed.**

### 8.4 Settlement source

All UpDown markets settle via Chainlink Data Streams (`https://data.chain.link/streams/{btc,eth,sol}-usd`). `market_resolutions_v2.resolution_source` confirms this.

### 8.5 Fee model

- Resolution fee: 2% of winning leg's profit `((1 - entry_price) * 0.02)`. Applied automatically at on-chain settlement.
- Maker rebate: 0%.
- Taker fee: 0% on the trade itself; only on resolution winnings.
- Gas: ~$0.001 on Polygon per CLOB order (gasless from trader's perspective for entries — Polymarket matches on-chain). Gas applies only to direct calls like `redeemPositions`.

---

## 9. Redemption — claiming pUSD post-resolution

**Critical:** Polymarket does NOT auto-redeem. After a market resolves, winning tokens sit as ERC-1155 balances on the CTF contract until **you** call `redeemPositions()`. Until then, pUSD is locked.

### When to redeem

A market is redeemable once:
1. Market end condition fires
2. UMA Adapter oracle reports outcome via `reportPayouts()`
3. CTF contract records the payout vector

In practice for UpDown markets this is typically 30–90 seconds after `resolve_unix`. Storedata's `markets` table will show `resolved_at IS NOT NULL` and `outcome` populated.

There's no deadline — winning tokens stay redeemable forever.

### What to redeem

For each market with a held position:
- **Unhedged win**: hold N winning tokens → `redeemPositions(indexSets=[1,2])` → receive $N pUSD.
- **Unhedged loss**: hold N losing tokens, 0 winning. Skip — `redeem` is a no-op.
- **Hedged (both legs)**: hold N YES + N NO → `redeemPositions(indexSets=[1,2])` → receive $N pUSD (only winning leg pays).
- **Exited at bid**: position already closed off-chain. **Skip — no tokens to redeem.**

### Function call

```solidity
function redeemPositions(
    IERC20  collateralToken,        // pUSD address
    bytes32 parentCollectionId,     // bytes32(0)
    bytes32 conditionId,            // markets.condition_id
    uint256[] calldata indexSets    // [1, 2]
) external;
```

| Param | Value |
|---|---|
| `collateralToken` | pUSD: `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` |
| `parentCollectionId` | `bytes32(0)` |
| `conditionId` | `markets.condition_id` from Storedata DB |
| `indexSets` | `[1, 2]` always — only winning side actually pays |

**No approval needed.** Redeem burns user's own tokens; `msg.sender` is the holder.

### Contract addresses (Polygon mainnet, chain_id=137)

```
ConditionalTokens (CTF):  0x4D97DCd97eC945f40cF65F87097ACe5EA0476045
pUSD:                     0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB
```

### Worker implementation

```python
# backend/app/services/redemption_worker.py
import asyncio
from decimal import Decimal
from web3 import Web3

CTF_ADDRESS    = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
PUSD_ADDRESS   = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
PARENT_COLL_ID = "0x" + "00" * 32
INDEX_SETS     = [1, 2]

class RedemptionWorker:
    def __init__(self, w3_primary, w3_fallback, signer_account, db_pool, poly_client):
        self.w3 = w3_primary
        self.w3_fallback = w3_fallback
        self.signer = signer_account
        self.db = db_pool
        self.poly = poly_client
        self.ctf = w3_primary.eth.contract(address=CTF_ADDRESS, abi=CTF_ABI)
        self._seen = set()

    async def run(self):
        while True:
            try:
                await self._scan_and_redeem()
            except Exception:
                log.exception("redemption_worker_error")
            await asyncio.sleep(30)

    async def _scan_and_redeem(self):
        # Find resolved markets where we held positions AND the slot wasn't exited at bid
        rows = await self.db.fetch("""
            SELECT DISTINCT m.condition_id, m.market_id, m.slug
            FROM markets m
            JOIN trading.events e
              ON e.data->>'condition_id' = m.condition_id
             AND e.kind = 'poly_updown_signal'
             AND e.data->>'reason' = 'order_placed'
             AND e.data->>'fill_status' = 'filled'
            WHERE m.platform = 'polymarket'
              AND m.resolved_at IS NOT NULL
              AND m.condition_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM trading.events e2
                WHERE e2.data->>'condition_id' = m.condition_id
                  AND e2.kind = 'poly_updown_signal'
                  AND e2.data->>'reason' IN ('redeemed', 'exited_at_bid')
              )
            LIMIT 100
        """)
        for r in rows:
            cid = r["condition_id"]
            if cid in self._seen:
                continue
            try:
                await self._redeem_one(cid, r["market_id"], r["slug"])
                self._seen.add(cid)
            except Exception:
                log.exception("redeem_failed", condition_id=cid)

    async def _redeem_one(self, condition_id, market_id, slug):
        tx = self.ctf.functions.redeemPositions(
            PUSD_ADDRESS, PARENT_COLL_ID, condition_id, INDEX_SETS,
        ).build_transaction({
            "from": self.signer.address,
            "nonce": self.w3.eth.get_transaction_count(self.signer.address),
            "gas": 200_000,
            "maxFeePerGas": self.w3.eth.gas_price,
            "maxPriorityFeePerGas": Web3.to_wei(30, "gwei"),
            "chainId": 137,
        })
        signed = self.signer.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        await self.db.execute("""
            INSERT INTO trading.events (kind, data, sleeve_id)
            VALUES ('poly_updown_signal', $1::jsonb, $2)
        """, json.dumps({
            "reason": "redeemed",
            "condition_id": condition_id,
            "slug": slug,
            "tx_hash": tx_hash.hex(),
            "status": "success" if receipt.status == 1 else "reverted",
            "gas_used": receipt.gasUsed,
        }), "redemption_worker")
```

Key behaviors:
- **Idempotency**: `_scan_and_redeem` query excludes already-redeemed AND already-exited-at-bid conditions. Won't double-redeem or burn gas on bid-exited positions.
- **Loss markets**: skip — no winning tokens. Optional: log `redeem_skipped_no_winner` for auditability.
- **Resolution lag**: 30s poll. Worst-case redeem fires ~60–120s after `resolve_unix`.
- **Wallet**: must hold ≥0.5 MATIC for ~250 redemptions. Watchdog at 0.2 MATIC.
- **Restart resilience**: `_seen` cache rebuilds from `trading.events` on startup.

---

## 10. Bring-up sequence

### Wave 1 — Strategy + paper executor (1.5 days)

- Implement `Updown5mStrategy`, `Updown15mStrategy`, `resolve_condition_id`, `PolyPaperExecutor` (with `place_entry_order` taking `notional_usd`, `place_exit_order` for bid sells, 30s `STALE_AFTER_SECONDS`, 10s book cache).
- Unit tests in `backend/tests/unit/`:
  - `test_updown_5m_strategy.py`, `test_updown_15m_strategy.py`: signal returns UP/DOWN/NONE correctly across modes.
  - `test_paper_place_entry_order.py`: walks ask book consuming USD, returns FILLED with correct `filled_shares`.
  - `test_paper_place_exit_order.py`: walks bid book selling shares, returns FILLED with correct `proceeds_usd`.

### Wave 2 — Controller + HYBRID hedge (1.5 days)

- `_build_signal_aux`, `_fetch_or_compute_threshold`, `on_bar_close`, `on_tick`, `_maybe_hedge` (HYBRID), `_fetch_opposite_book`, `_fetch_own_book`, `_try_hedge_with_retries`, `_audit(extras=...)`.
- Slot model with `entry_*`, `hedge_*`, `exit_*`, `status` fields and terminal states `{open, hedged_holding, exited_at_bid, held_no_hedge_no_exit, resolved}`.
- Integration tests:
  - `test_hybrid_hedge_path.py`: mock executor returning `asks=[]` for opposite_book → slot transitions to `exited_at_bid`.
  - `test_hybrid_hedge_success.py`: mock executor with healthy asks → slot transitions to `hedged_holding`.
  - `test_hybrid_both_fail.py`: empty asks AND empty bids → slot transitions to `held_no_hedge_no_exit`.
  - `test_resolution_for_exited_at_bid.py`: PnL = `proceeds - cost`, no redemption call.

### Wave 3 — Sleeve registration + paper smoke (½ day)

- Register 12 controllers (6 sleeves × 2 modes).
- Run `tv-engine` paper mode 24h.
- Verify by SQL (see §11).

### Wave 4 — Redemption worker (1 day)

- Implement `RedemptionWorker` per §9.
- Set up Alchemy as primary RPC + public Polygon RPC fallback.
- Wire into `tv-engine` lifespan.
- Test against a known-resolved market with a test wallet.

### Wave 5 — Tiny-live ($1) + parity check (1 day setup, 7 days observation)

- Set `TV_POLY_TINY_LIVE=true` + `TV_POLY_TINY_LIVE_NOTIONAL=1.00`.
- Switch executor from paper to live (`PolymarketClient`).
- POLY_LIVE_ACK attestation in place.
- Daily parity report: realized hit rate vs §11 backtest bands.
- If parity holds 7 days → ramp to $5 → $10 → $25.

---

## 11. Verification gates — what "good" looks like

### After Wave 3 (paper smoke 24h)

```sql
-- 1. All 12 sleeves firing
SELECT sleeve_id, COUNT(*) AS n
FROM trading.events
WHERE kind LIKE 'poly_updown_%'
  AND at > now() - interval '24 hours'
GROUP BY sleeve_id ORDER BY n DESC;
-- Expected: 12 rows, all with non-zero counts.

-- 2. HYBRID branches active
SELECT data->>'reason' AS reason, COUNT(*) FROM trading.events
WHERE kind='poly_updown_signal'
  AND at > now() - interval '24 hours'
GROUP BY reason ORDER BY count DESC;
-- Expected reasons present: order_placed, hedge_placed, exited_at_bid,
--                           hedge_check_skipped_stale_feed (occasional),
--                           hedge_and_exit_both_failed (rare, <5%)

-- 3. PnL realism
SELECT data->>'symbol' AS sym,
       AVG(abs((data->>'pnl_usd')::numeric)) AS avg_abs_pnl,
       COUNT(*) AS n
FROM trading.events
WHERE kind='poly_updown_resolution'
  AND at > now() - interval '24 hours'
GROUP BY sym;
-- Expected: avg_abs_pnl in $5–15 range per asset. Not $0.025 (ghost fills).

-- 4. Hit rates by sleeve+mode
SELECT
  data->>'symbol' AS sym, data->>'tf' AS tf,
  CASE WHEN sleeve_id LIKE '%sniper%' THEN 'sniper' ELSE 'volume' END AS mode,
  COUNT(*) AS n,
  ROUND(100.0 * SUM(CASE WHEN data->>'won'='true' THEN 1 ELSE 0 END)::numeric / COUNT(*), 1) AS hit_pct,
  ROUND(AVG((data->>'pnl_usd')::numeric), 2) AS avg_pnl
FROM trading.events
WHERE kind='poly_updown_resolution'
  AND at > now() - interval '24 hours'
GROUP BY sym, tf, mode
ORDER BY sym, tf, mode;
```

Compare hit_pct + avg_pnl to backtest reference numbers in §13. If realized is more than 5pp below backtest hit rate OR more than 30% below backtest avg_pnl, halt and investigate.

### After Wave 5 (7 days tiny-live)

Per-day scorecard (paste this on dashboard):

```sql
SELECT
  date_trunc('day', at) AS day,
  COUNT(*) AS resolutions,
  ROUND(AVG((data->>'pnl_usd')::numeric), 2) AS avg_pnl,
  ROUND(SUM((data->>'pnl_usd')::numeric), 2) AS total_pnl,
  ROUND(100.0 * SUM(CASE WHEN data->>'won'='true' THEN 1 ELSE 0 END)::numeric / COUNT(*), 1) AS hit_pct,
  ROUND(100.0 * SUM(CASE WHEN data->>'hedged'='true' THEN 1 ELSE 0 END)::numeric / COUNT(*), 1) AS hedge_rate,
  COUNT(*) FILTER (WHERE data->>'reason' = 'exited_at_bid') AS bid_exits,
  COUNT(*) FILTER (WHERE data->>'reason' = 'hedge_and_exit_both_failed') AS both_failed
FROM trading.events
WHERE kind='poly_updown_resolution' AND at > now() - interval '7 days'
GROUP BY day ORDER BY day DESC;
```

Trip wires (halt and investigate if any holds 3 consecutive days):
- Hit rate >5pp below backtest band on any sleeve
- Mean PnL/trade >30% below backtest band
- `both_failed` rate >5%
- `hedge_rate` near 0% (HYBRID branch 1 broken)
- `bid_exits` always 0 (HYBRID branch 2 not triggering)

---

## 12. Edge cases — required behavior

| Case | Behavior |
|---|---|
| Binance 1MIN bar at `window_start - 300s` not yet ingested | Return NONE. Don't trade. Audit `signal_skipped_no_binance_data`. |
| `ret_5m == 0` exactly | Return NONE. |
| `min_order_size > qty` | Skip trade. Audit `trade_skipped_below_min_order`. |
| Sniper threshold cache None on first market of day (cold start) | Compute synchronously. If still None due to <50 history rows, return NONE for sniper mode (volume mode still fires). |
| Both opposite-asks AND own-bids empty at hedge time | Slot → `held_no_hedge_no_exit`. Ride to natural resolution. Audit `hedge_and_exit_both_failed`. |
| Binance feed stale (>2 min) during open position | Skip hedge checks until feed recovers. Audit `hedge_check_skipped_stale_feed`. |
| Hedge-buy rejected (rate limit, signing error) | Retry up to 3× with 200ms backoff. If all fail, fall back to bid-side exit. |
| Bid-side exit rejected | If hedge also failed → slot → `held_no_hedge_no_exit`. Audit. |
| Multiple ticks while hedge already placed | `slot.status` check is idempotent. `hedged_holding` and `exited_at_bid` skip further hedge attempts. |
| Market resolves before hedge fills | Cancel hedge. PnL = natural-resolution PnL of held leg only. |
| Same `(symbol, tf, window_start_unix)` fires twice (engine restart) | Idempotency — skip duplicate. |
| Resolution event fires for `exited_at_bid` slot | PnL already realized at exit — record resolution event with `pnl=exit_proceeds - entry_cost`. No redemption. |

---

## 13. Backtest reference numbers

Source: 5,742 markets BTC+ETH+SOL × 5m+15m, Apr 22-27, 2026. Realistic L10 book-walking sim, $25 stake, HYBRID exit policy.

### Per-sleeve / per-mode @ $25

| Sleeve | Mode | Trades/day | Hit% | Mean PnL | Sharpe | MaxDD |
|---|---|---:|---:|---:|---:|---:|
| btc_5m | volume | 221 | 57.3% | +$3.61 | +51.0 | -$289 |
| eth_5m | volume | 224 | 58.2% | +$3.62 | +53.7 | -$317 |
| sol_5m | volume | 220 | 57.3% | +$2.96 | +44.9 | -$391 |
| btc_15m | volume | 65 | 57.7% | +$5.67 | +53.1 | -$110 |
| eth_15m | volume | 66 | 52.8% | +$3.68 | +35.5 | -$113 |
| sol_15m | volume | 62 | 52.9% | +$3.74 | +36.2 | -$175 |
| btc_5m | sniper q10 | 22 | 74.8% | +$10.63 | +67.0 | -$43 |
| eth_5m | sniper q10 | 22 | 74.6% | +$9.46 | +57.6 | -$42 |
| sol_5m | sniper q10 | 22 | 68.7% | +$7.23 | +42.0 | -$83 |
| btc_15m | sniper q20 | 13 | 66.7% | +$8.35 | +50.2 | -$28 |
| eth_15m | sniper q20 | 13 | 68.8% | +$8.41 | +51.6 | -$38 |
| sol_15m | sniper q20 | 12 | 66.7% | +$6.37 | +41.3 | -$33 |

**Total expected gross @ $25 stake: ~$3,999/day.** After 30–50% live haircut: **~$2,000–$2,800/day net**.

### Capacity ladder (TF=ALL, signal=full)

| Asset | $1 ROI | $25 ROI | $100 ROI | $250 ROI |
|---|---:|---:|---:|---:|
| BTC | +21.1% | +20.8% | +20.0% | +18.5% |
| ETH | +21.1% | +19.9% | +16.7% | +13.3% |
| SOL | +21.6% | +17.6% | +10.6% | +7.7% |

BTC scales cleanly to $250. ETH cap ~$100. SOL cap ~$25–50 (thin books force >40% skip at $250).

### HYBRID vs HEDGE_HOLD edge (at 0% synthetic-fail)

| Cell | HYBRID @ $25 | HEDGE_HOLD @ $25 | Δ |
|---|---:|---:|---:|
| q10 5m ALL | +35.4% ROI / Sharpe 95.7 | +34.5% ROI / Sharpe 95.7 | +0.9 pp |
| q20 15m ALL | +33.4% ROI / Sharpe 89.3 | +31.4% ROI / Sharpe 82.7 | +2.0 pp |
| q10 15m ALL | +37.97% ROI / Sharpe 83.5 | +35.97% ROI / Sharpe 77.7 | +2.0 pp |

HYBRID matches or beats HEDGE_HOLD on every cell. The bid-exit branch captures slightly more value than holding both legs through resolution (skips the 2% fee on the winning leg of the hedged pair).

---

## 14. Out of scope (defer to v3+)

These are validated as future-promising but require additional data or implementation work not justified for V2:

| Item | Reason to defer |
|---|---|
| Asset-stratified stakes (BTC=$100, ETH=$50, SOL=$25) | After V2 7-day parity gate passes, then ramp |
| Disable SOL 5m sniper sleeve | After 7-day data confirms backtest tail (Rank-IC IR 0.36 on SOL 5m, Sharpe 42 — weakest cell) |
| `book_skew` overlay on BTC 5m sniper | Phase 19 — needs 14-day forward-walk; Rank-IC IR=−2.40 in backtest |
| Cross-asset BTC confirmation on ETH/SOL 5m | Phase 19 — re-run under HYBRID + new metrics |
| Switch 15m sniper q20→q10 | DON'T — q20 has 2× trade count, wins on $/day at fixed stake |
| `mergePositions()` on-chain | Already superseded by HYBRID. No marginal benefit. |
| Multicall3 redemption batching | Volume too low to justify; revisit at production stakes |
| `combo_q20` (`ret_5m` AND `smart_minus_retail` agree) | n=48 in-sample — wait for more data |
| q5 ultra-tight on 5m | Holdout sample drops too small to distinguish from q10 |
| Time-of-day filter | Cross-asset robustness medium-weak; weekend behavior diverges |

---

## 15. Files reference (for the implementer)

```
backend/app/strategies/polymarket/
├── base.py                    # PolymarketBinaryStrategy ABC
├── updown_5m.py               # Updown5mStrategy
├── updown_15m.py              # Updown15mStrategy
└── market_mapping.py          # resolve_condition_id

backend/app/controllers/
└── polymarket_updown.py       # PolymarketUpdownController, _maybe_hedge HYBRID

backend/app/venues/polymarket/
├── paper.py                   # PolyPaperExecutor (place_entry_order, place_exit_order)
├── client.py                  # PolymarketClient (live executor)
├── settings.py                # PolySettings
└── ctf_abi.json               # CTF redeemPositions ABI

backend/app/services/
└── redemption_worker.py       # RedemptionWorker

backend/app/data/
└── bars.py                    # fetch_close_asof, fetch_close_with_ts_asof

backend/tests/unit/
├── test_updown_5m_strategy.py
├── test_updown_15m_strategy.py
├── test_paper_place_entry_order.py
└── test_paper_place_exit_order.py

backend/tests/integration/
├── test_hybrid_hedge_path.py
├── test_hybrid_hedge_success.py
├── test_hybrid_both_fail.py
├── test_resolution_for_exited_at_bid.py
└── test_redemption_worker.py
```

---

**End of guide.** Self-contained Phase 18 V2 implementation for VPS3. All values from validated backtest evidence (5,742 markets × 6 days, realistic L10 book-walking, 4-policy fallback sweep, Rank-IC validation). Estimated bring-up: 5–6 days dev + 1 day Wave 4 RPC setup + 7 days tiny-live observation = **~13–14 days end-to-end** to production sizing.
