# Strategy Lab Engine Uplift Spec (v0.5)

**Target file:** `strategy_lab/engine.py`
**Status:** Design only — no implementation
**Author date:** 2026-04-22

## § 1. API Design

### 1.1 ExecutionConfig dataclass

```
@dataclass(frozen=True)
class ExecutionConfig:
    mode: Literal["v1", "market", "limit", "hybrid"] = "v1"
    fee_schedule: str | FeeSchedule = "binance_spot"   # key in FEE_REGISTRY or object
    slippage_bps: float = 5.0                          # taker slippage only
    limit_mode: Literal["at_close", "offset_pct", "ladder", "stop_limit"] | None = None
    limit_offset_pct: float = 0.0                      # for offset_pct
    limit_ladder_pcts: tuple[float, ...] = ()          # e.g. (0.001, 0.002, 0.003)
    limit_ladder_weights: tuple[float, ...] = ()       # must sum to 1.0; same len as pcts
    limit_valid_bars: int = 3                          # N — cancel after N bars unfilled
    stop_trigger_pct: float = 0.0                      # for stop_limit_breakout
    stop_limit_inside_pct: float = 0.0                 # offset inside the trigger
    max_fill_pct_of_bar_volume: float = 0.10           # P — partial-fill cap
    hybrid_fallback_after_bars: int = 3                # limit→market fallback in hybrid
    queue_position_penalty_bps: float = 1.0            # mid-bar conservative fill adj
    report_unfilled: bool = True
```

### 1.2 New engine entry point

```
def run_backtest(
    df: pd.DataFrame,
    signals: dict,                       # {"entries", "exits", "short_entries", "short_exits",
                                         #  optional: "entry_limit_price", "exit_limit_price",
                                         #  "entry_limit_offset", "exit_limit_offset"}
    *,
    sl_stop: float | None = None,
    tsl_stop: float | None = None,
    tp_stop: float | None = None,
    execution: ExecutionConfig | None = None,
    **legacy_kwargs,                     # fees, slippage, direction, init_cash — v1 passthrough
) -> BacktestResult:
```

`execution=None` → constructs `ExecutionConfig(mode="v1")` which reproduces pre-uplift behavior **exactly** (flat 10 bps fees, 5 bps slippage, next-bar open fill via vectorbt). Legacy kwargs (`fees=`, `slippage=`, etc.) are accepted in v1 mode and override the config.

### 1.3 Strategy return contract (backwards compatible)

Existing strategies return a dict with 4 boolean `pd.Series` (`entries`, `exits`, `short_entries`, `short_exits`) — unchanged. Limit-aware strategies may additionally return:

- `entry_limit_price`: `pd.Series[float]` — absolute limit price per bar (NaN → fall back to config)
- `entry_limit_offset`: `pd.Series[float]` — offset in pct (e.g. 0.002 = 20 bps inside)
- `exit_limit_price`, `exit_limit_offset`: same for exits

Per-signal overrides win over `ExecutionConfig` defaults. If neither is supplied in `limit` mode, fall back to `limit_mode="at_close"`.

### 1.4 BacktestResult

Unchanged public fields (`equity`, `trades`, `stats`) plus new:

- `fills: pd.DataFrame` — one row per fill: `ts, side, size, price, fee, is_maker, slippage_bps, order_id, parent_signal_ts`
- `unfilled_orders: pd.DataFrame` — `ts_posted, side, limit_price, expired_at, reason`
- `execution_metrics: dict` (see § 4)

---

## § 2. Fill Simulation Algorithm

### 2.1 Limit-buy fill (pseudocode)

```
post_ts = signal_bar_ts
L = resolve_limit_price(signal, config, signal_close)   # absolute price
qty_remaining = target_qty

for i in range(1, N+1):                       # next-bar onward ONLY
    bar = df[post_ts + i]
    if bar.low <= L:
        # conservative fill assumption: mid-bar at L, with queue penalty
        fill_price = L * (1 + queue_position_penalty_bps / 1e4)
        fill_qty = min(qty_remaining, bar.volume * P)
        record_fill(ts=bar.ts, price=fill_price, qty=fill_qty,
                    is_maker=True, slippage_bps=0)
        qty_remaining -= fill_qty
        if qty_remaining <= 0: break
    # else: order still resting
if qty_remaining > 0:
    record_unfilled(post_ts, L, expired_at=post_ts + N,
                    reason="expired" if never_touched else "partial_expired")
```

**Look-ahead rule:** even if `bar[post_ts+1].open <= L`, we do **not** assume fill at open — only fill at `L * (1 + penalty)` because we can't prove our order was ahead in the queue.

### 2.2 Limit-sell fill

Mirror of above: fill when `bar.high >= L`, penalty is `L * (1 - penalty_bps/1e4)`.

### 2.3 Partial fill logic

`fill_qty_this_bar = min(qty_remaining, bar.volume * max_fill_pct_of_bar_volume)`. Remainder carries to next bar while within the N-bar validity window. Each partial fill is its own row in `fills`.

### 2.4 Stop-limit breakout

Long: trigger when `bar.high >= stop_trigger`. Once triggered, post a limit at `stop_trigger * (1 - stop_limit_inside_pct)`. Fill that bar if `bar.low <= limit_price` after trigger; else carry N bars as in 2.1. Short: mirror with `bar.low`/trigger, limit above.

### 2.5 Ladder

Each rung is an independent limit order with weight `w_k` of target qty. Fill/expire evaluated per rung, aggregated into parent order.

### 2.6 Hybrid mode

`mode="hybrid"` runs `limit` path first. If order unfilled after `hybrid_fallback_after_bars`, cancel limit and post market order at the next bar's open (taker fee + `slippage_bps`).

---

## § 3. Fee Schedule Abstraction

### 3.1 FeeSchedule

```
@dataclass(frozen=True)
class FeeSchedule:
    exchange_name: str
    maker_bps: float
    taker_bps: float
    effective_date: date
    notes: str = ""
```

### 3.2 Registry

```
FEE_REGISTRY: dict[str, FeeSchedule] = {
    "binance_spot":  FeeSchedule("binance_spot",  10.0, 10.0, date(2024,1,1)),
    "binance_vip0":  FeeSchedule("binance_vip0",  10.0, 10.0, date(2024,1,1)),
    "bybit_spot":    FeeSchedule("bybit_spot",    10.0, 10.0, date(2024,1,1)),
    "bybit_perp":    FeeSchedule("bybit_perp",     2.0,  5.5, date(2024,1,1)),
    "hyperliquid":   FeeSchedule("hyperliquid",    1.5,  3.5, date(2024,1,1)),
}
def register_fee_schedule(fs: FeeSchedule) -> None: ...
```

### 3.3 Per-fill fee path

```
fee = fill.notional * (fs.maker_bps if fill.is_maker else fs.taker_bps) / 1e4
```

Market fills → `is_maker=False`. Limit fills that rest ≥1 bar → `is_maker=True`. Stop-limit fills → `is_maker=True` only if they rested; same-bar triggered+filled → `is_maker=False`.

---

## § 4. Metrics Additions

Added to `execution_metrics` dict:

| Name | Type | Computation |
|---|---|---|
| `maker_fill_pct` | float | `sum(fills.is_maker)/len(fills)` |
| `taker_fill_pct` | float | `1 - maker_fill_pct` |
| `unfilled_order_count` | int | `len(unfilled_orders)` |
| `unfilled_order_pct` | float | `unfilled_count / (unfilled + filled_parents)` |
| `total_fee_paid` | float | `fills.fee.sum()` |
| `fee_drag_pct_of_pnl` | float | `total_fee_paid / abs(gross_pnl)` |
| `avg_entry_slippage_bps` | float | volume-weighted mean over entry fills |
| `avg_exit_slippage_bps` | float | same, exits |
| `avg_slippage_per_trade` | float | per-trade avg (entry + exit halves) |
| `partial_fill_ratio` | float | `len(fills_with_partial_flag)/len(fills)` |
| `avg_fills_per_order` | float | `len(fills)/n_parent_orders` |

---

## § 5. No-Lookahead Safeguards

1. A limit order posted at bar `i` **can never fill on bar `i`**. First eligible bar is `i+1`.
2. The limit reference price (e.g., `signal_close`) is read from bar `i` only; bar `i+1` never feeds back into bar `i`.
3. Tie-breaking at bar `i+1`: if `bar.low <= L <= bar.open`, we do NOT fill at `open` (that requires queue priority we cannot prove). We fill at `L * (1 + queue_position_penalty_bps/1e4)` conservatively. Same rule inverted for sells.
4. For stop-limits: trigger and fill may occur in the same bar only when mode is `stop_limit`; this represents realistic market-maker behavior once a stop elects. Flagged `is_maker=False`.
5. Volume-cap partial fills use `bar[i+k].volume`, never aggregated forward volume.
6. All stop/trailing checks still use `df.shift(1)` pattern — no modification.
7. `df` index must be monotonic `DatetimeIndex`; engine asserts at entry.

---

## § 6. Test Plan (minimum 10)

1. `test_v1_mode_matches_pre_uplift_baseline` — run a known strategy under `mode="v1"` and pickled pre-uplift equity curve; assert `np.allclose(eq_new, eq_old, atol=1e-9)`.
2. `test_market_fill_regression` — `mode="market"` with flat fees reproduces v1 output within 1e-9.
3. `test_limit_buy_fills_on_touch` — synthetic OHLCV where `bar[i+1].low == L`; expect single fill at `L * (1 + penalty)`, `is_maker=True`.
4. `test_limit_buy_expires_without_touch` — `bar[i+1..i+N].low > L`; expect 0 fills and one row in `unfilled_orders` with `reason="expired"`.
5. `test_limit_sell_fills_on_touch_high` — symmetric to test 3 using `bar.high`.
6. `test_partial_fill_over_two_bars` — signal qty > P × bar.volume; expect 2 fill rows summing to qty, both `is_maker=True`.
7. `test_stop_limit_trigger_and_fill_same_bar` — `bar.high` crosses trigger and `bar.low` reaches limit; expect 1 fill, `is_maker=False`.
8. `test_stop_limit_trigger_no_fill_expires` — trigger hit but limit never touched within N bars; expect `unfilled_orders` row.
9. `test_maker_vs_taker_fee_correctness` — manual 2-trade scenario, assert `fills.fee` matches `notional × bps/1e4` per side.
10. `test_ladder_weighted_partial_fills` — 3-rung ladder (0.3/0.4/0.3), middle rung touches; assert only middle rung fills at correct weighted qty.
11. `test_hybrid_fallback_to_market` — limit doesn't fill within `hybrid_fallback_after_bars`; assert fallback market fill at `open * (1 + slippage_bps/1e4)` and `is_maker=False`.
12. `test_no_lookahead_open_below_limit` — craft bar with `open < L < high`: assert fill price is `L * (1 + penalty)`, NOT `open`.
13. `test_fee_registry_pluggable` — register custom `FeeSchedule`, run, assert fees use custom bps.
14. `test_execution_metrics_shape` — asserts all § 4 keys present with correct types.
15. `test_unfilled_count_metric` — 10 limits posted, 3 expire; assert `unfilled_order_count == 3`, pct correct.

---

## § 7. Migration Plan (as shipped)

- **Phase 0.5a — DONE.** `ExecutionConfig`, `FeeSchedule`, `FEE_REGISTRY`, and `BacktestResult.fills/unfilled_orders/execution_metrics` scaffolding. `mode="v1"` preserves bit-identical stats; 14 tests green.
- **Phase 0.5b — DONE.** `mode="market"` (vbt + FeeSchedule taker fees) and `mode="limit"` (pure-Python fill loop) ship. Covers no-lookahead, partial fills, maker/taker tagging, unfilled-order tracking. Tests 2, 3, 4, 5, 6, 9, 12, 15 green. Numba optimization deferred until performance is measured against real Phase-5 workloads.
- **Phase 0.5c.1 — DONE.** `sl_stop` / `tsl_stop` / `tp_stop` work inside `mode="limit"`. Stop-hit fills market-close at stop level × (1 − slip_bps/1e4), taker fee, `is_maker=False`. Stops override resting sell limits (logged as unfilled/`stop_override`). 5 stops-specific tests green.
- **Phase 0.5c.2+ — DEFERRED to 0.5d (optional).** Not blocking downstream phases:
  - Shorts in limit mode (mirror state machine) — needed for pairs / long-short systems
  - `mode="hybrid"` (limit-then-market fallback)
  - `limit_mode="stop_limit"` (breakout trigger + inside limit)
  - `limit_mode="ladder"` (multi-rung weighted limits)
  Each has a clear extension path in the current fill-loop code; flag a specific strategy candidate during Phase 3 research and come back.
- **Rollout gate (hard)** — CI runs all existing runners under `mode="v1"` and diffs equity curves vs the frozen golden-master pickle (`tests/golden/v1_equity_curves.pkl`) to `≤ 1e-9`. Green.

---

## § 8. Open Questions / Risks

1. **vectorbt 0.28 cannot natively simulate resting limit orders with intrabar touch logic.** Highest-risk item. Likely resolution: bypass `vbt.Portfolio.from_signals` for `mode in {"limit","hybrid","stop_limit"}` and drive a custom Numba fill loop (`@njit`) that feeds synthesized `size_arr` / `price_arr` into `Portfolio.from_orders`. Needs prototype before 0.5b.
2. **Bar-volume accuracy** — Binance spot kline `volume` is base-asset, `quote_volume` is quote; P% cap must be applied consistently. Decision: cap by quote volume to stay currency-neutral across assets. Flag in config.
3. **Queue-position penalty is a free parameter** — 1 bp default is a guess. Risk of overfitting if tuned per-strategy. Proposal: pin at 1 bp globally in config, document as assumption, never fit.
4. **Maker classification for same-bar fills** — a limit posted at bar `i-1` close that fills bar `i` with `bar.open` already past `L` is technically a marketable limit (taker). Current § 2.1 treats all resting-limit fills as maker for simplicity. Flag for later refinement; may need `is_marketable_limit` sub-classification.
5. **Golden-master brittleness** — 1e-9 tolerance assumes float determinism across numpy/pandas versions. Pin `numpy==X.Y`, `pandas==X.Y`, `vectorbt==0.28.*` in `requirements-engine-lock.txt` and bake versions into the golden pickle filename.
6. **Short-entry limit semantics** — asymmetric with longs (uptick rules on some venues, borrow fees on perps). Out of scope for 0.5; document explicitly. `short_entries` under `mode="limit"` uses the symmetric algorithm from § 2.2 with a TODO to revisit per-venue.
