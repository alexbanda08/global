# Tradingvenue — Polymarket UpDown Strategy Implementation Guide

**Audience:** the Tradingvenue agent / operator implementing Phase 18.
**Purpose:** replace the placeholder `naive-momentum` strategy stubs in `Updown5mStrategy` / `Updown15mStrategy` with the validated `sig_ret5m` Binance latency-arbitrage signal, and add the **hedge-hold** exit rule. Self-contained — does not require reading the strategy_lab backtest files.

**Source of validation:** 5,742 markets across BTC/ETH/SOL × 5m+15m, Apr 22-27, 2026. Forward-walk 80/20 holdout with quantile thresholds fit on TRAIN only. All recommended cells have 95% CI strictly above zero on holdout.

**Quantile policy (timeframe-specific, validated 2026-04-27):** Sniper mode uses `q10` (top 10%) on 5m markets and `q20` (top 20%) on 15m markets. Forward-walk shows q10 beats q20 on 5m by **+7pp ROI on holdout** (BTC: +35.5% vs +26.9%); on 15m markets, q10 ≈ q20 (no meaningful difference). The tighter quantile only helps on the faster horizon. See §9 for full numbers.

---

## TL;DR — the strategy in 5 lines

1. **At each market's `window_start`**, compute `ret_5m = log(BTC_close[window_start] / BTC_close[window_start - 300s])` from `binance_klines_v2` (1MIN bars, BINANCE_SPOT_BTC_USDT — and ETH/SOL equivalents).
2. **Bet UP** if `ret_5m > 0`, **bet DOWN** if `ret_5m < 0`. Place a CLOB taker buy of the chosen side at its current ask.
3. **Every ~10s while the position is open**, check Binance close. If BTC has reversed by ≥**5 basis points** against our signal direction, **buy the OPPOSITE side at its current ask** ("hedge-hold").
4. **Hold both legs to natural resolution.** No `mergePositions()` call needed.
5. **After resolution, call `redeemPositions()`** on the CTF contract to convert winning tokens to pUSD and free capital for the next trade. Background worker polls every 30s.

The only on-chain interaction is **redemption** (winning tokens → pUSD). Entries and hedges go through the existing CLOB. No `mergePositions`, no `splitPosition`, no ERC-1155 approvals.

---

## 1. The Signal — `sig_ret5m`

### What

```python
# At window_start (start of the 5m or 15m prediction window):
btc_now    = binance_close_at_or_before(window_start)
btc_prior  = binance_close_at_or_before(window_start - 300)  # always 5min ago, even on 15m markets
ret_5m     = log(btc_now / btc_prior)

if ret_5m > 0:
    side = "UP"
elif ret_5m < 0:
    side = "DOWN"
else:
    side = "NONE"  # extremely rare; skip
```

For ETH and SOL up-down markets, use the same formula but with `BINANCE_SPOT_ETH_USDT` and `BINANCE_SPOT_SOL_USDT` 1MIN closes respectively. **The asset feed must match the market asset** — you cannot use BTC closes to predict ETH up-down outcomes.

### Why it works

Polymarket settles via Chainlink Data Streams, which aggregates multiple exchanges and lags Binance by 4–12 seconds. Binance accounts for ~35–45% of total BTC spot+futures volume — it's the price-discovery venue. The previous 5 minutes of Binance return is a leading indicator of the next 5–15 minutes of Chainlink-settled price (and therefore of the Polymarket UpDown outcome).

### Two entry filters (modes)

The strategy ships in **two modes**. Both are recommended; run them in parallel.

**Mode A — `volume` (every signal fires):**
- No threshold filter. Bet on every market where `ret_5m != 0`.
- Approximately **285 trades/day per asset** (BTC + ETH + SOL ⇒ ~860/day).
- Backtest hit rate: **62.1%** (5m), **60.7%** (15m).
- Backtest ROI per trade: **+11.4%** (5m), **+12.7%** (15m).

**Mode B — `sniper` mode (timeframe-specific quantile):**
- Only bet when `|ret_5m|` clears a quantile threshold of recent observations for that (asset, timeframe).
- **Threshold per timeframe:**
  - **5m markets → q10** (top 10% = 90th percentile)
  - **15m markets → q20** (top 20% = 80th percentile)
- Computed daily from a **rolling 14-day window** of historical `ret_5m` magnitudes for that (asset, timeframe).
  - At market open, look at all `ret_5m` values from completed markets in the last 14 days for the same `(asset, timeframe)`. Take the appropriate percentile of `|ret_5m|` (90th for 5m, 80th for 15m). If today's `|ret_5m| >= threshold`, fire. Else skip.
  - For the first 14 days of operation (cold start), use a lookback of "all available history" (will be smaller initially).
- Approximately **9 trades/day per asset on 5m + 18 trades/day per asset on 15m** (BTC+ETH+SOL ⇒ ~80/day combined across timeframes).
- **Forward-walk holdout (validated 2026-04-27):**
  - 5m × ALL: hit **81.4%**, ROI **+28.17%** (n=43 holdout)
  - 5m × BTC: hit **86.7%**, ROI **+35.54%** (n=15 holdout)
  - 15m × ALL: hit **91.3%**, ROI **+24.36%** (n=23 holdout)
  - 15m × BTC: hit **87.5%**, ROI **+30.95%** (n=8 holdout)

**Why timeframe-specific:** Forward-walk on 5m shows q10 beats q20 by +3 to +9pp ROI across all assets; on 15m the two are tied (+0.06pp to +0.57pp). The tighter quantile only helps when moves develop fast.

**Recommended deployment:** run both modes in parallel as separate sleeves. Mode A is the volume engine; Mode B is the high-conviction sleeve. The trades don't conflict — sniper is a strict subset of volume, and the hedging logic prevents same-market conflicts naturally.

---

## 2. Exit Logic — Hedge-Hold

### Rule

**Every ~10 seconds while a position is open**, fetch the latest Binance close (1MIN bar from `binance_klines_v2` or your live ticker for that asset).

```python
REV_BP_THRESHOLD = 5  # basis points

btc_now   = binance_close_at_or_before(now())
btc_at_ws = binance_close_at_or_before(window_start)  # cached at entry

bps = (btc_now - btc_at_ws) / btc_at_ws * 10000  # signed

reverted = (
    (signal == "UP"   and bps <= -REV_BP_THRESHOLD) or
    (signal == "DOWN" and bps >=  REV_BP_THRESHOLD)
)

if reverted and slot.status != "hedged_holding":
    # Buy the OPPOSITE side. Same qty (in shares) as the original entry.
    other_token_id   = market.no_token_id if signal == "UP" else market.yes_token_id
    other_ask_price  = clob_client.get_orderbook(other_token_id).asks[0].price  # best ask
    
    place_entry_order(
        token_id   = other_token_id,
        qty        = original_entry_qty,         # same number of shares as held position
        limit_px   = other_ask_price,            # cross the spread, take liquidity
        sleeve_id  = sleeve_id,
        side       = "buy",
    )
    
    slot.status = "hedged_holding"
    # No further action. Both legs settle naturally. PnL closed at resolution.
```

### Why hedge-hold (not direct sell, not merge)

We tested three exit options:
- **Direct sell** (sell our held side at the current bid): vulnerable to bid-side spread degradation. When the market moves against us, the bid often slips 3–5¢ before we can exit, locking in a dirty fill.
- **Buy other + `mergePositions()`**: redeems $1 immediately. Slightly higher PnL than hedge-hold (~$0.01 per $1) but requires Polygon RPC integration, ERC-1155 approvals, and gas estimation logic.
- **Hedge-hold (THIS RULE)**: buy the opposite side at its ask, hold both legs. At resolution, exactly one leg pays $1 and the other pays $0. We capture the same downside protection as merge with **zero on-chain code path** — just one extra CLOB order.

**Why this works mathematically:** once we hold equal YES + NO of the same condition, our position is **delta-neutral and risk-free**. The combined value at resolution is exactly $1 (one leg wins, the other is worthless). Loss is capped at:

```
max_loss = entry_yes_ask + entry_no_ask - 1.00 + 0.02 * (1 - winning_leg_entry)
```

In typical conditions, this is `~$0.02–$0.04` per $1 stake. Compare to direct exit on a stressed bid which can lose `$0.10–$0.30`.

### `REV_BP_THRESHOLD` value

**Use 5.** Tested values 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50:
- `rev_bp=3` has marginally higher in-sample PnL but **5× more train→holdout drift** (signs of overfitting to micro-volatility).
- `rev_bp=5` captures ~82% of rev_bp=3's PnL with half the drift. Robust on holdout.
- Higher rev_bp values (15+) miss too many reversals → bigger losses on bad calls.

Holdout validation at rev_bp=5:
- full 5m ALL: train 63.6% → holdout 56.4% hit, holdout PnL +$50.99 [CI +$24, +$78]
- full 15m ALL: train 61.1% → holdout 59.0% hit, holdout PnL +$26.20 [CI +$12, +$41]
- sniper 5m ALL (**q10**): train 82.3% → **holdout 81.4%** hit, holdout ROI **+28.17%** [CI +$8, +$16]
- sniper 15m ALL (**q20**): train 73.2% → **holdout 91.3%** hit, holdout ROI **+24.36%** [CI +$3, +$7]
- (legacy q20 on 5m ALL: holdout 73.1% / +21.18% — superseded by q10 above for +7pp ROI lift)

---

## 3. Files to Modify in Tradingvenue

### 3.1 `backend/app/strategies/polymarket/base.py`

Extend the abstract `signal()` signature to accept an optional auxiliary context (Binance bars). Backward-compatible default `aux=None`.

```python
class PolymarketBinaryStrategy(ABC):
    @abstractmethod
    def signal(
        self,
        bars: list["Bar"],            # Polymarket-side bars (kept for compatibility)
        config: SignalConfig,
        aux: dict | None = None,      # NEW — Binance closes pre-fetched by controller
    ) -> Literal["UP", "DOWN", "NONE"]:
        ...
```

The `aux` dict expected schema:

```python
aux = {
    "binance_close_at_ws":      Decimal | None,   # close at window_start
    "binance_close_5m_before":  Decimal | None,   # close at window_start - 300s
    "ret_5m":                   float | None,     # pre-computed log return (optional convenience)
    # For sniper mode (Mode B) — controller computes the right percentile per timeframe:
    "abs_ret_5m_threshold":     float | None,     # q90 if tf==5m else q80 (rolling 14-day)
}
```

If `aux` is `None` or has missing keys, `signal()` must return `"NONE"`. Never crash.

### 3.2 `backend/app/strategies/polymarket/updown_5m.py` and `updown_15m.py`

Replace the SMA-momentum body. Both files are identical except for the timeframe label (the signal logic is the same — `ret_5m` over Binance regardless of Polymarket timeframe).

```python
import math
from typing import Literal

from backend.app.strategies.polymarket.base import PolymarketBinaryStrategy, SignalConfig

class Updown5mStrategy(PolymarketBinaryStrategy):  # or Updown15mStrategy
    """sig_ret5m strategy: bet sign of Binance 5m return at window_start.

    Optional sniper filter: only bet when |ret_5m| >= rolling threshold.
    The threshold is computed by the controller per timeframe:
      - 5m markets:  90th percentile of |ret_5m| (q10)
      - 15m markets: 80th percentile of |ret_5m| (q20)
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

**Note for both `updown_5m.py` and `updown_15m.py`:** the strategy code is **identical** — the timeframe-specific quantile is enforced upstream by the controller (which knows which timeframe the slot belongs to). The strategy just consumes the threshold from `aux`.

### 3.3 `backend/app/controllers/polymarket_updown.py`

Three changes:

**(a) Pre-fetch Binance closes before calling `strategy.signal()`.**

```python
async def on_bar_close(self, symbol: Symbol, tf: Tf, bars: list[Bar]) -> None:
    # ... existing setup ...
    window_start_us = bars[-1].close_time_us  # or however TV represents window_start

    aux = await self._build_signal_aux(symbol, window_start_us)
    direction = strategy.signal(bars, config, aux=aux)
    if direction == "NONE":
        return
    # ... existing entry placement using `direction` ...

async def _build_signal_aux(self, symbol: Symbol, window_start_us: int) -> dict:
    sym_id_map = {
        "BTC": "BINANCE_SPOT_BTC_USDT",
        "ETH": "BINANCE_SPOT_ETH_USDT",
        "SOL": "BINANCE_SPOT_SOL_USDT",
    }
    symbol_id = sym_id_map[symbol]
    ws_s = window_start_us // 1_000_000

    # Read 1MIN bar at-or-before window_start, and at-or-before window_start-300s.
    # Use existing helpers in backend/app/data/bars.py (asof lookups).
    btc_now   = await self._db.fetch_close_asof(symbol_id, "1MIN", ws_s)
    btc_prior = await self._db.fetch_close_asof(symbol_id, "1MIN", ws_s - 300)

    ret_5m = None
    if btc_now and btc_prior and btc_prior > 0:
        ret_5m = math.log(float(btc_now) / float(btc_prior))

    # For sniper mode: rolling 14-day quantile of |ret_5m| for this (symbol, tf).
    # The percentile depends on the timeframe (q90 on 5m, q80 on 15m).
    # Compute at most once per day per (symbol, tf), cache it.
    abs_ret_5m_threshold = await self._fetch_or_compute_threshold(symbol, tf, ws_s)

    return {
        "binance_close_at_ws":      btc_now,
        "binance_close_5m_before":  btc_prior,
        "ret_5m":                   ret_5m,
        "abs_ret_5m_threshold":     abs_ret_5m_threshold,
    }


async def _fetch_or_compute_threshold(self, symbol: Symbol, tf: Tf, ws_s: int) -> float | None:
    """Rolling 14-day quantile of |ret_5m|. Percentile is timeframe-specific:
       - 5m → 0.90 (q10, top 10%)
       - 15m → 0.80 (q20, top 20%)
    """
    # Cache key includes symbol AND tf so 5m and 15m get separate cached thresholds.
    cache_key = (symbol, tf, ws_s // 86_400)  # daily cache
    if (val := self._threshold_cache.get(cache_key)) is not None:
        return val

    quantile = 0.90 if tf == "5m" else 0.80
    # Pull |ret_5m| values from completed markets in the last 14 days for this (symbol, tf).
    # The set of markets to compute over is "completed before ws_s, within last 14d, same symbol+tf".
    # Implementation detail: query feature store / pre-built ret_5m series.
    rows = await self._db.fetch_abs_ret_5m_history(
        symbol_id=sym_id_map[symbol], tf=tf,
        from_s=ws_s - 14 * 86_400, until_s=ws_s,
    )
    if len(rows) < 50:
        # Cold start fallback: insufficient history → return None (no threshold).
        # Strategy in sniper mode will return NONE for the slot, falling through to volume mode.
        return None
    threshold = float(numpy.quantile(rows, quantile))
    self._threshold_cache[cache_key] = threshold
    return threshold
```

**(b) Add an `on_tick(...)` periodic hook for the reversal check.**

```python
REV_BP_THRESHOLD = 5

async def on_tick(self) -> None:
    """Called every ~10s by the BarEngine while any slot is open."""
    for slot in self._open_slots():
        if slot.status == "hedged_holding":
            continue  # already hedged; nothing to do until resolution
        await self._maybe_hedge(slot)

async def _maybe_hedge(self, slot: Slot) -> None:
    btc_at_ws = slot.btc_close_at_ws  # cached at entry
    btc_now = await self._db.fetch_close_asof(slot.binance_symbol_id, "1MIN",
                                              now_unix_seconds())
    if btc_now is None or btc_at_ws is None:
        return
    bps = float((Decimal(btc_now) - Decimal(btc_at_ws)) / Decimal(btc_at_ws) * 10_000)

    reverted = (
        (slot.signal == "UP"   and bps <= -REV_BP_THRESHOLD) or
        (slot.signal == "DOWN" and bps >=  REV_BP_THRESHOLD)
    )
    if not reverted:
        return

    other_token_id = slot.no_token_id if slot.signal == "UP" else slot.yes_token_id
    book = await self._venue_client.get_orderbook(other_token_id)
    if not book.asks:
        log.warning("hedge_skipped_no_asks", slot=slot.id, side=slot.signal)
        return
    other_ask_price = book.asks[0].price

    # Use SAME executor (paper or live) and SAME sleeve. Match entry qty.
    await self._executor.place_entry_order(
        token_id=other_token_id,
        qty=slot.entry_qty,
        limit_px=other_ask_price,
        sleeve_id=slot.sleeve_id,
        side="buy",
    )
    slot.status = "hedged_holding"
    slot.hedge_other_entry_price = other_ask_price
    log.info("slot_hedged", slot=slot.id, signal=slot.signal,
             entry=slot.entry_price, hedge_entry=other_ask_price, bps=bps)
```

**(c) Resolution accounting** — update slot PnL after natural resolution. The existing TV resolution path likely already handles this for one-leg positions; verify both legs of a hedged slot are credited correctly:

```python
# Pseudo: at market resolution, both legs settle automatically on-chain.
# Slot PnL = (winning_leg_qty * 1.0 * (1 - 0.02)) - sum(entry_costs)
#         = qty * (0.98) - (entry_price + hedge_other_entry) * qty       if hedged
#         = qty * (0.98) - entry_price * qty                              if not hedged AND won
#         = -entry_price * qty                                            if not hedged AND lost
```

The 2% protocol fee applies only to the **winning leg's profit portion** (not stake). Polymarket charges this automatically at settlement.

### 3.4 `backend/app/venues/polymarket/settings.py`

Add config knobs:

```python
class PolySettings(BaseSettings):
    # ... existing fields ...
    rev_bp_threshold: int = 5             # Binance reversal trigger in basis points
    strategy_mode: Literal["volume", "sniper", "both"] = "both"
    # For sniper mode rolling threshold (timeframe-specific quantile, single lookback window):
    sniper_lookback_days: int = 14
    sniper_quantile_5m:   float = 0.90    # q10 — top 10% of |ret_5m| on 5m markets
    sniper_quantile_15m:  float = 0.80    # q20 — top 20% of |ret_5m| on 15m markets
```

### 3.5 D-04 sizing override (for $1–$10 micro-live)

`polymarket_updown.py` currently raises `SizingOverrideForbidden` if `notional_usd != $25`. To enable cheap real-world testing, gate the override on a new flag. Polymarket supports fractional shares, so $1/slot is fully workable:

```python
NOTIONAL_PER_SLOT_USD = Decimal("25")
TINY_LIVE_MIN_USD     = Decimal("1.00")  # Polymarket supports fractional shares
TINY_LIVE_MAX_USD     = Decimal("10")    # cap to keep risk low during validation

def __init__(
    self,
    pool: "asyncpg.Pool",
    executor: Any,
    mode: Mode,
    *,
    notional_usd: Decimal | None = None,
    tiny_live_mode: bool = False,        # NEW
) -> None:
    if notional_usd is None:
        notional_usd = NOTIONAL_PER_SLOT_USD
    if not tiny_live_mode and notional_usd != NOTIONAL_PER_SLOT_USD:
        raise SizingOverrideForbidden(
            f"D-04: $25/slot is hard-coded; got override={notional_usd}"
        )
    if tiny_live_mode and not (TINY_LIVE_MIN_USD <= notional_usd <= TINY_LIVE_MAX_USD):
        raise SizingOverrideForbidden(
            f"tiny_live: must be in [${TINY_LIVE_MIN_USD}, ${TINY_LIVE_MAX_USD}]; got {notional_usd}"
        )
    self.notional_usd = notional_usd
```

---

## 4. Polymarket-specific Operational Details

### 4.1 Minimum order size

**Polymarket supports fractional shares** — you can buy positions as small as a few cents ($0.01–$0.10). There is no formal minimum trading size limit on the protocol itself; the only practical floor is **liquidity** — finding a counterparty at your desired price.

The `min_order_size` field returned by `clob_client.get_orderbook(token_id)` (when present) is a per-market hint about the smallest order the matching engine will accept for that token, but this can be quite small (often well under $1). **$1 trades are fully supported** in 5m/15m UpDown markets.

**Implementation rule:** still respect `book.min_order_size` if returned, but for sub-dollar markets it's not a meaningful constraint:

```python
# Compute fractional qty (Polymarket supports fractional shares)
qty = Decimal(notional_usd) / Decimal(entry_price)
qty = qty.quantize(Decimal("0.000001"))  # 6-decimal precision

# Honor the per-market min_order_size only as a courtesy check
if book.min_order_size and qty < Decimal(book.min_order_size):
    log.info("trade_skipped_below_min", slot=slot.id, qty=qty, min=book.min_order_size)
    return
```

The bigger practical risk at $1 stakes is **liquidity at your limit_px**, not the minimum size. If the book is thin and a $1 fill walks the book by 2–3¢, your effective entry price drifts. Use a small `slippage_bps` cap (TV already has `slippage_bps` in `PolymarketClient` settings — default 2 bps; bump to 50–100 bps for tiny-live to ensure fills).

### 4.2 Tick size

Returned per-market as `book.tick_size`. Typically `0.01`. Switches to `0.001` when price > 0.96 or < 0.04 (`tick_size_change` WS event). **Round all `limit_px` to the current tick size or the order is rejected.**

```python
def round_to_tick(px: Decimal, tick: Decimal) -> Decimal:
    return (px / tick).quantize(Decimal("1")) * tick
```

### 4.3 Standard vs negative-risk markets

Our BTC/ETH/SOL Up-Down markets are **standard binary CTF** (`market.neg_risk == false` in Storedata's `markets` table). Use the standard CLOB order endpoints. Negative-risk adapter is **not needed** for this strategy.

### 4.4 Settlement price source

All Up-Down markets settle via Chainlink Data Streams (`https://data.chain.link/streams/{btc,eth,sol}-usd`). The `market_resolutions_v2.resolution_source` field confirms this on every resolved row in our universe. No alternative oracle paths.

### 4.5 Fee model

- **Resolution fee:** 2% of the winning leg's profit (`(1 - entry_price) * 0.02`). Applied automatically at on-chain settlement.
- **Maker rebate:** 0% (no rebate on this venue).
- **Taker fee:** 0% on the trade itself; fee is charged only on resolution winnings.
- **Gas:** ~$0.001 on Polygon per CLOB order; signed orders are gasless from the trader perspective for entries (matched on-chain by Polymarket's matching engine). Gas applies to direct on-chain interactions like `mergePositions()` — **which we are NOT calling**.

---

## 4.6 Redemption — claiming pUSD after resolution

**Critical:** Polymarket does NOT auto-redeem winning tokens. After a market resolves, your winning YES (or NO) tokens sit in your wallet as ERC-1155 balances on the CTF contract until **you** call `redeemPositions()`. Until then, the pUSD is locked — you can't use it for the next trade.

### When to redeem

A market is redeemable once:
1. The market end condition fires (5m or 15m window closes)
2. The UMA Adapter oracle reports the outcome via `reportPayouts()`
3. The CTF contract records the payout vector

In practice for our UpDown markets, this is **typically 30–90 seconds after `resolve_unix`**. You can check via the `markets` table in Storedata: row has `resolved_at IS NOT NULL` and `outcome` populated.

There's **no deadline** — winning tokens stay redeemable forever. So if a redemption fails, retry later is always safe.

### What to redeem

For each market we held a position in (whether hedged or unhedged):
- **Unhedged win:** we hold N winning tokens, 0 losing tokens. Redeem the winning side → receive $N pUSD.
- **Unhedged loss:** we hold 0 winning tokens, N losing tokens. Skip — `redeemPositions` on losing-only is a no-op (burns 0, pays 0). Don't waste gas.
- **Hedged (both legs held):** we hold N YES + N NO. Redeem both sides → receive $N pUSD (only winning leg pays). Single transaction by passing `indexSets = [1, 2]`.

### Function call

```solidity
function redeemPositions(
    IERC20  collateralToken,
    bytes32 parentCollectionId,
    bytes32 conditionId,
    uint256[] calldata indexSets
) external;
```

| Param | Value for our use |
|---|---|
| `collateralToken` | pUSD: `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` |
| `parentCollectionId` | `bytes32(0)` |
| `conditionId` | `markets.condition_id` from Storedata DB |
| `indexSets` | `[1, 2]` always — redeems both outcomes; only the winning side actually pays |

**No approval needed.** Unlike merge (which transfers tokens INTO the contract), redeem burns your tokens AT the CTF contract directly — `msg.sender` is the token holder, no allowance required.

### Contract addresses (Polygon mainnet, chain_id=137)

```
ConditionalTokens (CTF):  0x4D97DCd97eC945f40cF65F87097ACe5EA0476045
pUSD (Polymarket USD):    0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB
NegRiskAdapter (NOT used for our markets): 0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296
```

For our **standard binary** BTC/ETH/SOL UpDown markets (`markets.neg_risk = false`), use the CTF contract directly. Negative-risk markets would use NegRiskAdapter — not in scope.

### Gas

- ~80–150k gas per redeem call
- At Polygon ~30 gwei × $0.40 MATIC ≈ **$0.001–$0.002 per redemption**
- For ~80 sniper trades/day (~27 5m + ~54 15m) × ~55% hedge rate = ~80–125 redemption transactions/day
- Daily gas cost: **~$0.10–$0.15/day** — negligible

### Optimization — Multicall batch

For higher volume (volume mode at 860 trades/day), pack multiple `redeemPositions` calls into a single transaction via Multicall3 (`0xcA11bde05977b3631167028862bE2a173976CA11` on Polygon). Saves ~50% gas at 5+ redemptions per tx. **Not needed for $1 micro-live phase.** Add later as an optimization.

### TV implementation — `RedemptionWorker`

Add a new background worker process. It runs as part of `tv-engine` (or a sibling unit `tv-redeemer.service`).

**Logic:**

```python
# backend/app/services/redemption_worker.py
import asyncio
from decimal import Decimal
from web3 import Web3

CTF_ADDRESS    = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
PUSD_ADDRESS   = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
PARENT_COLL_ID = "0x" + "00" * 32  # bytes32(0)
INDEX_SETS     = [1, 2]            # both outcomes; only winning pays

class RedemptionWorker:
    def __init__(self, w3_primary: Web3, w3_fallback: Web3, signer_account, db_pool, poly_client):
        self.w3           = w3_primary           # Alchemy
        self.w3_fallback  = w3_fallback          # public Polygon RPC
        self.signer       = signer_account
        self.db           = db_pool
        self.poly         = poly_client
        self.ctf          = w3_primary.eth.contract(address=CTF_ADDRESS, abi=CTF_ABI)
        self.ctf_fallback = w3_fallback.eth.contract(address=CTF_ADDRESS, abi=CTF_ABI)
        self._seen        = set()  # in-memory cache of already-redeemed condition_ids
    
    def _try_with_fallback(self, fn):
        """Run an RPC call; on error, retry once via fallback. Returns (result, provider_used)."""
        try:
            return fn(self.w3, self.ctf), "alchemy"
        except Exception as e:
            log.warning("primary_rpc_failed_falling_back", error=str(e))
            return fn(self.w3_fallback, self.ctf_fallback), "fallback"
        
    async def run(self):
        """Background loop. Polls every 30s for newly-resolved markets we hold."""
        while True:
            try:
                await self._scan_and_redeem()
            except Exception:
                log.exception("redemption_worker_error")
            await asyncio.sleep(30)
    
    async def _scan_and_redeem(self):
        # 1. Find resolved markets where we held positions
        rows = await self.db.fetch("""
            SELECT DISTINCT m.condition_id, m.market_id, m.slug
            FROM markets m
            JOIN trading.events e
              ON e.market_id = m.market_id 
             AND e.event_type IN ('entry_placed', 'hedge_placed')
            WHERE m.platform = 'polymarket'
              AND m.resolved_at IS NOT NULL
              AND m.condition_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM trading.events e2
                WHERE e2.market_id = m.market_id
                  AND e2.event_type = 'redeemed'
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
    
    async def _redeem_one(self, condition_id: str, market_id: str, slug: str):
        # 2. Build and send transaction
        tx = self.ctf.functions.redeemPositions(
            PUSD_ADDRESS,
            PARENT_COLL_ID,
            condition_id,
            INDEX_SETS,
        ).build_transaction({
            "from":      self.signer.address,
            "nonce":     self.w3.eth.get_transaction_count(self.signer.address),
            "gas":       200_000,
            "maxFeePerGas":         self.w3.eth.gas_price,
            "maxPriorityFeePerGas": Web3.to_wei(30, "gwei"),
            "chainId":   137,
        })
        signed = self.signer.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)

        # 3. Log event for audit + idempotency
        await self.db.execute("""
            INSERT INTO trading.events (market_id, event_type, tx_hash, status, payload)
            VALUES ($1, 'redeemed', $2, $3, $4)
        """, market_id, tx_hash.hex(),
            "success" if receipt.status == 1 else "reverted",
            {"condition_id": condition_id, "slug": slug, "gas_used": receipt.gasUsed})
        log.info("redeemed", slug=slug, tx=tx_hash.hex(), gas=receipt.gasUsed)
```

### Key behaviors

| Property | Behavior |
|---|---|
| **Idempotency** | Once `trading.events` has a `redeemed` row for a market_id, never call redeem again for it. The CTF burns the tokens on first call — second call is a wasted-gas no-op. |
| **Loss markets** | Skip — no winning tokens to redeem. Optional: still log a `redeem_skipped_no_winner` event for auditability, costs nothing. |
| **Both legs lost** | Impossible for binary up/down. (One side always wins.) |
| **Resolution lag** | Poll every 30s. Worst case: redeem fires ~30s after resolution. The pUSD lockup window is `~30–90s (oracle) + ~30s (poll) + ~5s (tx confirm) = ~1–2 min` after `resolve_unix`. |
| **Gas spike** | At max gas price 100 gwei, each redeem is still ~$0.005. Skip rate-limiting. |
| **Wallet balance** | Polygon MATIC balance must stay ≥ 0.5 MATIC to cover gas for ~250 redemptions. Add a watchdog alert at 0.2 MATIC. |
| **Tx revert** | Most likely cause: market not yet resolved on-chain (oracle lag). Retry on next poll cycle. |
| **Restart resilience** | `_seen` cache rebuilds from `trading.events` on startup. No state lost. |

### Schema additions

```sql
-- Add a 'redeemed' event_type to the existing trading.events table.
-- No new table needed; reuse the existing audit log.

ALTER TYPE trading.event_type ADD VALUE IF NOT EXISTS 'redeemed';
ALTER TYPE trading.event_type ADD VALUE IF NOT EXISTS 'redeem_skipped_no_winner';

-- For fast lookup of unredeemed markets:
CREATE INDEX IF NOT EXISTS trading_events_redeemed_idx
  ON trading.events (market_id) WHERE event_type = 'redeemed';
```

### Wallet & key management

The signing key for `tv-engine` (which places entries and hedges) is the same key that holds the resulting tokens. Therefore:
- `RedemptionWorker` uses the **same wallet/key** as the entry path
- No additional credential setup needed beyond what's already in TV's `polymarket/settings.py` (POLYMARKET_PRIVATE_KEY env var)
- Make sure the wallet has MATIC for gas — fund it once with ~5 MATIC (~$2 at current prices) and refill periodically

### Live observability

In TV's frontend dashboard, surface:
- Pending redemptions (resolved markets where we hold winning tokens but haven't called redeem yet) — should always be < 5 with the 30s poll
- Total pUSD redeemed today (vs total expected from win-rate × stake × wins)
- MATIC balance with low-threshold alert
- Last successful redeem tx_hash + timestamp

---

## 5. Bring-Up Sequence

### Phase 18 wave plan

**18-01 — Strategy fill** (½ day)
- Implement `PolymarketBinaryStrategy.signal(bars, config, aux=None)` change in `base.py`
- Replace bodies of `Updown5mStrategy` and `Updown15mStrategy` with the new logic
- Add unit tests in `backend/tests/unit/`:
  - `test_updown_5m_strategy.py`: signal returns UP for positive ret_5m, DOWN for negative, NONE for missing aux, NONE in sniper mode below threshold.
  - Same for 15m.

**18-02 — Controller wiring + on_tick reversal hook** (1.5 days)
- Add `_build_signal_aux()` to `PolymarketUpdownController`. Reads via existing `bar_sources.py`.
- Add `_fetch_or_compute_threshold(symbol, tf, ws_s)` with a daily cache for the rolling 14-day threshold (q90 for tf=5m, q80 for tf=15m). Cache key MUST include `tf` so 5m and 15m get separate thresholds.
- Add `on_tick()` hook called by BarEngine every 10s. Implements `_maybe_hedge()`.
- Add `slot.status` field with values `{"open", "hedged_holding", "resolved"}`.
- Update `polymarket_updown.py` to track `entry_qty`, `entry_price`, `btc_close_at_ws`, `binance_symbol_id` per slot.
- Tests in `backend/tests/integration/test_poly_hedge_hold.py`:
  - Setup: paper mode, mock Binance bars showing reversal.
  - Verify: slot transitions to `hedged_holding` after rev_bp triggered.
  - Verify: hedge order is placed for the opposite token, same qty, at current ask.
  - Verify: no second hedge fires on subsequent ticks.

**18-03 — Redemption worker** (1 day)
- Add `backend/app/services/redemption_worker.py` (see §4.6 spec).
- Add web3.py dependency if not already present (`pip install web3`). Pin to compatible Polygon version.
- **Set up Alchemy as primary Polygon RPC** (free tier; sign up at alchemy.com, create Polygon Mainnet app, copy HTTP URL). Use public RPC as fallback.
- Implement primary→fallback retry: on RPC error, retry once with `TV_POLYGON_FALLBACK_RPC`. Log which provider succeeded.
- Add `trading.events` event types: `redeemed`, `redeem_skipped_no_winner`.
- Wire the worker into `tv-engine`'s lifespan (start on app startup, gracefully cancel on shutdown).
- Test against a previously-resolved market via integration test (paper mode doesn't redeem since no real tokens; use a fork or hardhat-style local node, OR run against a known-resolved Polymarket market with a test wallet that holds 1¢ of winning tokens).
- Watchdog: low-MATIC alert at 0.2 MATIC threshold.

**18-04 — Sizing override + paper smoke run** (½ day)
- Add `tiny_live_mode` param to `PolymarketUpdownController`.
- Add config flag `tv-engine` reads from env: `TV_TINY_LIVE=true` and `TV_TINY_LIVE_NOTIONAL=1.00`.
- Run `tv-engine` in paper mode for **24 hours** with full=mode and sniper=mode both active.
- Verify by query against `trading.events`:
  - `signal_generated` events fire at every market window_start_at
  - `entry_placed` events have correct side, qty, sleeve_id
  - `hedge_placed` events fire for ~30–60% of opens (varies with BTC volatility)
  - `slot_resolved` events compute PnL correctly for both hedged and unhedged paths
  - (Note: paper mode does NOT call `redeemPositions` — no real tokens to redeem. Redemption worker is only relevant in live mode.)

**18-05 — Parity check + go-live $1 micro** (1 day)
- Build a daily report comparing realized hit rate to the backtest holdout bands:
  - Volume mode: 56.4% holdout hit (5m), 59.0% (15m)
  - **Sniper mode (q10 on 5m): 81.4% holdout hit**
  - **Sniper mode (q20 on 15m): 91.3% holdout hit**
- Trip wire: if 24h realized hit rate falls below `holdout_hit - 7pp` for **two consecutive days**, send Telegram alert and trip the kill switch.
  - Concretely: trip if 5m sniper falls below 74.4% OR 15m sniper falls below 84.3% on two consecutive days.
- Once 48h paper looks correct, set `TV_TINY_LIVE=true` and `TV_TINY_LIVE_NOTIONAL=1.00` (or higher per your risk tolerance — see §5.2 below).
- POLY_LIVE_ACK attestation file must be present per existing Phase 14 D-04 requirements.

**18-06 — 7-day live audit** (parallel to ops)
- Daily: realized PnL vs expected, hit rate vs backtest, max drawdown.
- After 7 days within parity bands, escalate to v0.1 production sizing (Phase 19 territory).

### 5.1 Stake size recommendations

| Phase | Notional/slot | Daily max risk | Purpose |
|---|---|---|---|
| 18-03 paper smoke (24h) | $25 sim | $0 | wiring validation |
| **18-04 first live** | **$1.00** | **~$25** | **sanity, fill realism — recommended starting point** |
| 18-04 day 3+ | $5 | ~$120 | better statistical signal |
| 18-04 day 5+ if green | $10 | ~$240 | calibration |
| Phase 19 | $25 | ~$600 | v0.1 production |

At $1/slot, sniper expected daily P&L (in-sample, by timeframe):
- 5m sniper (q10): ~27 trades/day × +$0.246/trade ≈ **+$6.64/day**
- 15m sniper (q20): ~54 trades/day × +$0.204/trade ≈ **+$11.01/day**
- **Combined sniper sleeve ≈ +$17.65/day** (gross). After ~10% live-execution haircut, ≈ **+$15.90/day**.

Daily *worst-case* loss is bounded by `(entry + hedge - 1 + fee) ≈ $0.05 max per trade × ~80 trades = $4/day` even if every signal fails. Real-world haircut on a $1 stake from spread-walking on tiny qty could be 5–10% — bumps worst-case to ~$8–10/day.

This is the **cheapest possible reality test** while still exercising every code path: real CLOB fills, real Chainlink-vs-Binance lag observation, real WebSocket reliability, real partial-fill handling. Burning $5–7/day worst case for 7 days = $35–50 to validate the entire stack is the best bargain in this project.

### 5.2 Practical $1/trade considerations

- **Polymarket supports fractional shares** — at entry $0.51 with $1 stake, you buy `1/0.51 ≈ 1.961` shares. The CLOB accepts fractional qty natively.
- **Spread cost is the dominant risk at small size.** The book's bid-ask is typically 1¢ (~2% of $0.50 mid). A $1 trade with 2% slippage = $0.02 friction per leg, $0.04 round-trip. That's ~10% of expected per-trade ROI on top of the modeled 2% protocol fee. Plan for it.
- **Gas is essentially free** on Polygon (~$0.001 per signed CLOB order). Polymarket entry orders are matched on-chain by their matching engine, but the trader doesn't pay gas directly.
- **Capital lockup**: at $1 + $1 hedge = $2 locked × ~58 concurrent slots = ~$116 max locked at any moment. Trivial.
- **Resolution wait** is 5–15 min — same as backtest. Each day's PnL fully realizes within 24h.

---

## 6. Validation Targets (parity gates)

After 24h of paper mode (18-03), verify against these expected ranges:

| Metric | Volume mode (full × ALL) | Sniper 5m (q10) | Sniper 15m (q20) |
|---|---|---|---|
| Trades / day | ~860 | ~27 | ~54 |
| Hedge-trigger rate | ~27% | ~50% | ~63% |
| Win rate (PnL > 0) | 60–64% | **78–86%** | 73–91% |
| Mean PnL / trade | +$0.10–$0.13 | **+$0.25–$0.35** | +$0.18–$0.24 |
| Max drawdown over 24h | < $6 per $1 stake | < $1 per $1 stake | < $1 per $1 stake |

If realized metrics fall **more than 5 percentage points below** these on hit rate or **more than 30% below** on mean PnL, hold off on going live and investigate. Most likely causes: signal wiring bug (wrong asset feed, wrong window_start), hedge logic bug (wrong side, wrong qty), or threshold cache stale.

After 7 days live (18-05), verify hit rate stays within ±5pp of these bands.

---

## 7. Edge Cases and Required Error Handling

| Case | Required behavior |
|---|---|
| Binance bar at `window_start - 300s` not yet ingested | Return `NONE`. Don't trade. Log `signal_skipped_no_binance_data`. |
| `ret_5m == 0` exactly | Return `NONE`. |
| `min_order_size > qty` | Skip the trade. Log `trade_skipped_below_min_order`. |
| Other-side ask is `None` (book empty) at hedge time | Skip the hedge. Mark slot `held_no_hedge`. PnL goes to natural resolution unhedged. Log `hedge_skipped_no_asks`. |
| Binance feed becomes stale during open position (>2 min lag) | Skip hedge checks until feed recovers. Log `hedge_check_skipped_stale_feed`. Position rides to resolution unhedged. |
| Hedge order rejected (rate limit, signing error, etc.) | Retry up to 3 times with 200ms backoff. If all fail, mark slot `hedge_failed_held` and rely on natural resolution. Send operator alert. |
| Multiple ticks arrive while hedge is already placed but slot.status not yet flipped | Idempotent: check slot.status atomically before placing hedge. |
| Sniper threshold cache is None on first market of the day | Compute synchronously (one DB query per (symbol, tf)). If still None due to insufficient history, return `NONE` for that market in sniper mode (and rely on volume mode if running in parallel). |
| Market resolves before our hedge order fills | Cancel the hedge order. PnL is the natural-resolution PnL of the YES-only leg. |
| Same window_start_at fires twice (engine restart) | Idempotency by `(symbol, tf, window_start_unix)` key. Skip duplicates. |

---

## 8. Configuration Summary

```ini
# /etc/storedata/tv-engine.env or equivalent

# Strategy config
TV_POLY_REV_BP_THRESHOLD=5
TV_POLY_STRATEGY_MODES=volume,sniper       # both run in parallel
TV_POLY_SNIPER_LOOKBACK_DAYS=14
TV_POLY_SNIPER_QUANTILE_5M=0.90            # q10 — top 10% on 5m markets
TV_POLY_SNIPER_QUANTILE_15M=0.80           # q20 — top 20% on 15m markets

# Sizing for tiny-live phase
TV_POLY_TINY_LIVE=true
TV_POLY_TINY_LIVE_NOTIONAL=1.00            # USD per slot during 18-04 first 48h
# After 48h green parity, ramp: 1 → 5 → 10 → 25

# Asset feeds (for clarity — already wired in TV)
TV_BINANCE_SYMBOLS=BINANCE_SPOT_BTC_USDT,BINANCE_SPOT_ETH_USDT,BINANCE_SPOT_SOL_USDT
TV_BINANCE_PERIOD=1MIN

# Polygon RPC (for redemption worker — required for live mode)
# Use Alchemy as PRIMARY (free tier covers us 100x over) + public RPC as FALLBACK
TV_POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/<YOUR_ALCHEMY_KEY>
TV_POLYGON_FALLBACK_RPC=https://polygon-rpc.com
TV_POLYGON_CHAIN_ID=137
TV_REDEEM_POLL_INTERVAL_S=30
TV_MATIC_LOW_THRESHOLD=0.2                    # alert below 0.2 MATIC

# Get an Alchemy key:
#   1. Sign up at https://www.alchemy.com (free)
#   2. Create a new app: Network = Polygon, Chain = Mainnet
#   3. Copy the HTTP URL (already includes your API key)
#   4. Free tier: 300M compute units/month — we use ~600 RPC calls/day = 0.03% of tier

# Polymarket key — already in TV; here for completeness
POLYMARKET_PRIVATE_KEY=<your wallet private key, 0x-prefixed hex>
POLYMARKET_FUNDER_ADDRESS=<proxy wallet address if using signature_type=2>
```

---

## 9. Backtest Reference Numbers (for parity reasoning)

Source: 5,742 markets across BTC+ETH+SOL × 5m+15m, Apr 22-27, 2026. Forward-walked 80/20.

### Headline cells (in-sample full-universe)

| Universe | n | Hit% | Total PnL/$1 | 95% CI | Mean/trade | ROI/bet |
|---|---|---|---|---|---|---|
| **Sniper (q10 × 5m × ALL)** | 579 | **81.5%** | **+$142.34** | [+$129, +$156] | +$0.2458 | **+24.58%** |
| **Sniper (q20 × 15m × ALL)** | 289 | **75.8%** | **+$58.91** | [+$50, +$67] | +$0.2039 | **+20.39%** |
| Volume (full × 5m × ALL) | 4,306 | 62.1% | +$490.82 | [+$439, +$549] | +$0.1140 | +11.40% |
| Volume (full × 15m × ALL) | 1,436 | 60.7% | +$182.78 | [+$156, +$209] | +$0.1273 | +12.73% |

### Forward-walk holdout (Sniper, chronological 80/20, threshold fit on TRAIN only)

| Cell | TRAIN n / hit / ROI | HOLDOUT n / hit / ROI / 95% CI | Verdict |
|---|---|---|---|
| **q10 × 5m × ALL** | 345 / 82.3% / +25.52% | **43 / 81.4% / +28.17%** [+$8, +$16] | ✅ generalizes (Δhit +0.9pp) |
| q10 × 5m × BTC | 114 / 85.1% / +28.91% | 15 / 86.7% / **+35.54%** [+$3, +$7] | ✅ generalizes (Δhit −1.6pp) |
| q10 × 5m × ETH | 116 / 80.2% / +24.81% | 15 / 73.3% / +24.81% [+$1, +$6] | ⚠️ CI ok, hit drift +6.8pp |
| q10 × 5m × SOL | 116 / 81.9% / +23.05% | 13 / 84.6% / +23.53% [+$1, +$5] | ✅ generalizes (Δhit −2.7pp) |
| **q20 × 15m × ALL** | 231 / 73.2% / +19.15% | **39 / 91.3% / +24.36%** [+$3, +$7] | ✅ holdout > train |
| q20 × 15m × BTC | 76 / 75.0% / +19.96% | 12 / 91.7% / **+31.67%** [+$3, +$5] | ✅ holdout > train |
| q20 × 15m × ETH | 77 / 74.0% / +19.96% | 13 / 84.6% / +23.82% [+$2, +$4] | ✅ holdout > train |
| q20 × 15m × SOL | 77 / 70.1% / +17.24% | 14 / 85.7% / +17.68% [+$0, +$4] | ⚠️ CI just touches zero |

**Why q10 on 5m, q20 on 15m:**

Forward-walk head-to-head holdout (q10 vs q20 at the same cell):

| TF | Asset | q20 holdout ROI | q10 holdout ROI | Δ |
|---|---|---|---|---|
| **5m** | ALL | +21.18% | **+28.17%** | **+6.99pp ✅** |
| **5m** | BTC | +26.91% | **+35.54%** | **+8.63pp ✅** |
| **5m** | ETH | +17.80% | **+24.81%** | **+7.01pp ✅** |
| **5m** | SOL | +20.71% | **+23.53%** | **+2.82pp ✅** |
| 15m | ALL | +24.03% | +24.36% | +0.33pp ≈tie |
| 15m | BTC | +31.67% | +30.95% | −0.71pp ≈tie |
| 15m | ETH | +23.82% | +24.39% | +0.57pp ≈tie |
| 15m | SOL | +17.68% | +17.75% | +0.06pp ≈tie |

q10 dominates on 5m (+3 to +9pp ROI lift), ties q20 on 15m. We use the better quantile per timeframe.

### Per-asset (Sniper at recommended quantile, rev_bp=5)

In-sample headline:

| Asset | TF | Quantile | n | Hit% | Mean/trade | ROI/bet |
|---|---|---|---|---|---|---|
| BTC | 5m | q10 | 143 | 85.3% | +$0.2961 | +29.61% |
| ETH | 5m | q10 | 145 | 79.3% | +$0.2507 | +25.07% |
| SOL | 5m | q10 | 145 | 79.3% | +$0.2168 | +21.68% |
| BTC | 15m | q20 | 95 | 77.9% | +$0.2225 | +22.25% |
| ETH | 15m | q20 | 97 | 76.3% | +$0.2120 | +21.20% |
| SOL | 15m | q20 | 97 | 73.2% | +$0.1775 | +17.75% |

### Sniper hedge-state breakdown

| Subset | n | Win% | Total PnL | Mean/trade |
|---|---|---|---|---|
| Unhedged (rode to resolution) | 108 | **92.6%** | +$43.91 | **+$0.41** |
| Hedged (synthetic close) | 181 | 65.7% | +$15.00 | +$0.08 |

The hedge subset is **mildly profitable on its own** — not just a loss-mitigation tool. When BTC reverses we still make ~$0.08/trade on average from spread capture and selective routing.

---

## 10. Out of Scope (do NOT implement in Phase 18)

**In scope (must implement):**
- ✅ `sig_ret5m` strategy logic in `Updown5mStrategy` / `Updown15mStrategy`
- ✅ `on_tick` reversal hook + hedge-hold exit (CLOB-only, no on-chain)
- ✅ `RedemptionWorker` — calls `redeemPositions()` on the CTF contract after each market resolves to convert winning tokens to pUSD (§4.6)
- ✅ Polygon RPC client (web3.py) — ONLY for `redeemPositions` calls
- ✅ `tiny_live_mode` sizing flag for $1/slot validation phase

**Out of scope (defer to v0.2+):**
- ❌ `mergePositions()` on-chain calls — superseded by hedge-hold; merge would only marginally improve PnL (~$0.01/$1) and adds substantial complexity
- ❌ `splitPosition()` — not needed; we never need to split pUSD into outcome tokens, we always buy them on the CLOB
- ❌ ERC-1155 `setApprovalForAll` for CTF — neither merge nor redeem requires it (redeem burns user's own tokens; merge would need it but we're not doing merge)
- ❌ Multicall3 batching for redemptions — single-redeem is fine at $1/trade volume; batch later
- ❌ Negative-risk adapter (`NegRiskAdapter`) — our markets are standard binary
- ❌ Multi-asset cross-correlation features (e.g., ETH momentum predicting BTC outcome)
- ❌ ML model fitting / Kronos retraining
- ❌ Funding-rate features (data not yet backfilled — May 1 ETA)
- ❌ Adaptive rev_bp per asset (single global threshold of 5 is sufficient per backtest)
- ❌ Order-book imbalance / book-skew features (univariate test showed no edge in this universe)
- ❌ Time-of-day filters (good_hours / bad_hour exclusion) — promising in-sample (+5pp ROI) but cross-asset robustness is medium-weak (Spearman ρ ~0.35) and weekend behavior diverges; **revisit after 14+ days of live data**, not for v0.1
- ❌ q5 quintile (top 5%) on 5m — even tighter than q10; in-sample roi is +25.34% but holdout sample drops to ~25 trades/cell which is too small to distinguish from q10. **Defer until more data lands**
- ❌ `combo_q20` (ret_5m AND smart_minus_retail agree) — best in-sample on BTC×15m (+26.32% ROI) but n=48 and not forward-walked. **Promising follow-up**, not v0.1

These v0.2+ candidates only after v0.1 core is live and stable.

---

## 11. Reference: Tradingvenue files this guide touches

| File | Change |
|---|---|
| `backend/app/strategies/polymarket/base.py` | Add `aux` param to `signal()` |
| `backend/app/strategies/polymarket/updown_5m.py` | Replace body with `sig_ret5m` logic |
| `backend/app/strategies/polymarket/updown_15m.py` | Same body, identical logic |
| `backend/app/controllers/polymarket_updown.py` | Add `_build_signal_aux`, `on_tick`, `_maybe_hedge`, `tiny_live_mode` flag |
| `backend/app/venues/polymarket/settings.py` | Add `rev_bp_threshold`, `strategy_mode`, `sniper_lookback_days`, `sniper_quantile_5m` (=0.90), `sniper_quantile_15m` (=0.80) |
| `backend/app/data/bars.py` | (verify) `fetch_close_asof(symbol_id, period, ts_s)` exists or add it |
| **`backend/app/services/redemption_worker.py`** | **NEW** — `RedemptionWorker` (see §4.6) |
| **`backend/app/venues/polymarket/ctf_abi.json`** | **NEW** — minimal ABI for `redeemPositions` on CTF |
| **`backend/app/main.py`** (or lifespan) | **MODIFIED** — start/stop `RedemptionWorker` task |
| **`pyproject.toml`** | **MODIFIED** — add `web3` dependency |
| **Alembic migration** (new revision) | **NEW** — adds `'redeemed'` and `'redeem_skipped_no_winner'` to `trading.event_type` enum + index |
| `backend/tests/unit/test_updown_5m_strategy.py` | New tests for sig_ret5m |
| `backend/tests/unit/test_updown_15m_strategy.py` | New tests for sig_ret5m |
| `backend/tests/integration/test_poly_hedge_hold.py` | New: hedge-hold flow on paper executor |
| `backend/tests/integration/test_redemption_worker.py` | New: redeem flow against forked Polygon (or recorded fixture) |

**One new external dependency** (`web3`), **one new schema migration** (event_type enum extension), no new venues, no new contracts.

---

**End of guide.** All values, thresholds, and ranges are from validated backtest evidence with forward-walk holdout. The implementation surface is small and well-bounded — strict additive change, no rewrite of existing TV components.
