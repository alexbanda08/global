# Tradingvenue — Polymarket UpDown Strategy V3 (Portfolio Deploy Guide)

**Audience:** TV agent shipping V3 alongside V1/V2 on VPS3 in shadow mode.
**Purpose:** ship the **per-asset tuned 3-sleeve sniper portfolio** (BTC q10 + ETH q5 + SOL multi-horizon q15) with maker entry, spread filter, HEDGE_HOLD exit. Pure paper / shadow. No live capital this round.
**Self-contained.** Backtest evidence + 10-gate validation: `strategy_lab/reports/RESEARCH_DEEP_DIVE_2026_04_29.md` and `strategy_lab/v2_signals/portfolio_gauntlet.py`.

---

## TL;DR — what V3 does

For every Polymarket BTC/ETH/SOL UpDown 5m market window:

1. Compute `ret_5m = ln(close_now / close_5m_prior)` from `binance_klines_v2 source='binance-spot-ws' period='1MIN'` (existing V2 plumbing — unchanged).

2. **Per-asset magnitude gate** (new vs V2):
   - BTC: only fire if `|ret_5m|` is in **top 10%** of last 14d (q10 — same as V2 sniper).
   - ETH: only fire if `|ret_5m|` is in **top 5%** of last 14d (q5 — TIGHTER than V2).
   - SOL: only fire if `|ret_5m|` is in **top 15% AND** `ret_5m`, `ret_15m`, `ret_1h` all same sign (q15 + multi-horizon agreement).

3. **Bet direction** = sign of `ret_5m` (UP if positive, DOWN if negative).

4. **Spread filter:** if `(ask_yes − bid_yes) / mid_yes ≥ 2%` at entry, skip the market. Same on NO side if betting DOWN.

5. **Entry execution:** maker order at `bid_0 + $0.01` (1¢ above best bid). Wait 30s. If filled at maker → done. If not filled → fall back to taker at the current ask.

6. **Hold to resolution.** No bid-exit branch. No reversal trigger. Just hold.

7. **Resolution:** standard chainlink-fast oracle (existing V2 path).

15m markets are **NOT** part of V3 — backtest showed 15m sleeves dilute the portfolio (HO ROI dropped from 32% to 26% when 15m added). 5m only.

---

## Why this differs from V2 sniper

V2 ships: `mode=sniper` with `q10` on 5m and `q20` on 15m, single threshold per timeframe, HYBRID exit fallback.

V3 changes:
| Item | V2 | V3 |
|---|---|---|
| Magnitude gate | q10 (5m) / q20 (15m) — same for all assets | **q10 BTC / q5 ETH / q15 SOL** — per-asset tuned |
| Multi-horizon filter | none | **enabled for SOL only** (ret_5m, ret_15m, ret_1h same sign) |
| Timeframe | 5m + 15m | **5m only** |
| Spread filter | none | **enabled — skip if spread ≥ 2%** |
| Entry mode | taker at ask | **maker @ bid + $0.01, fall back taker** |
| Exit policy | HYBRID (try buy-opp, else sell-bid, else hold) | **HEDGE_HOLD only — try buy-opp, else hold to resolution** |

V3 is essentially V2 sniper + recalibrated execution + per-asset gates. No new oracle dependencies. No new data tables. Same controller, new gating logic.

---

## Backtest evidence (the gates that V3 cleared)

Forward-walk holdout (chronological 80/20 on 7-day data):

| Sleeve | TR n | TR hit | HO n | HO hit | HO ROI |
|---|---|---|---|---|---|
| BTC 5m q10 mag-only | 165 | 68.5% | 36 | 72.2% | **+47.1%** |
| ETH 5m q5 mag-only | 82 | 64.6% | 26 | 65.4% | **+37.6%** |
| SOL 5m q15 multi-horizon | 107 | 57.0% | 23 | **78.3%** | **+54.9%** |

Combined portfolio (top-of-ask fills):
- HO ROI: **+32.16%** (3-sleeve)
- HO ROI: **+33.47%** with maker entry overlay
- HO ROI: **+27.09%** with realistic L10 book-walk fills (5pp haircut, still positive)

10-gate validation gauntlet (all passed):
- Outcome-permutation p < 0.005 (200 reps): edge is statistically significant
- Block bootstrap 95% CI: [$602, $1456] on $1029 holdout PnL — lower bound positive
- Stratified ret_5m permutation p < 0.005: **direction IS the alpha**, not magnitude alone
- Multi-split (60/70/80/90): HO ROI 25%-41% — stable across splits
- Magnitude ±2pp: smooth optimum, all variants positive
- Per-day: 04-28 hit 64.1% / +$301; 04-29 hit 66.3% / +$728 — both positive
- Realistic fills: 5pp haircut, still profitable
- Maker overlay: +1.3pp HO ROI lift

**Caveat:** 7-day data, 2-day holdout. Bulletproof on the sample we have, but the sample is small. Re-validate at 30 days.

---

## 1. Code changes (single PR against `epic-tu-a8a796`)

### 1.1 Controller — per-asset gating

`backend/app/controllers/polymarket_updown.py` — new function + per-asset config.

```python
# Add near top (after existing SNIPER_LOOKBACK_DAYS, SNIPER_MIN_SAMPLES):

# V3 per-asset magnitude quantiles. Override SNIPER quantile per (symbol, tf).
# 5m only — V3 does not run on 15m markets.
V3_PER_ASSET_QUANTILE = {
    ("BTC", "5m"): 0.90,   # top 10% by |ret_5m|
    ("ETH", "5m"): 0.95,   # top  5%
    ("SOL", "5m"): 0.85,   # top 15%
}

# V3 multi-horizon AND filter applies only to specific (symbol, tf) cells.
V3_REQUIRE_MULTI_HORIZON = {("SOL", "5m")}   # SOL only

# V3 spread filter: skip entry if (ask - bid) / mid >= threshold
V3_SPREAD_FILTER_PCT = 0.02
```

### 1.2 Threshold computation — per-asset

In `_compute_threshold` (or wherever the sniper quantile is currently computed), replace the single `quantile = 0.90 if tf == "5m" else 0.80` with a lookup:

```python
def _v3_quantile_for(symbol: str, tf: str) -> float | None:
    """Return V3 per-asset magnitude quantile, or None if V3 doesn't apply."""
    return V3_PER_ASSET_QUANTILE.get((symbol.upper(), tf))
```

In the threshold-fetcher path:
```python
# Existing V2 logic computes |ret_5m| samples over 14d.
# V3 just changes the quantile applied to those samples.

q = _v3_quantile_for(symbol, tf) if mode == "v3" else (0.90 if tf == "5m" else 0.80)
threshold = float(np.quantile(samples, q))
```

### 1.3 Multi-horizon filter

The strategy class `Updown5mStrategy` already accepts `aux={"ret_5m": ..., "abs_ret_5m_threshold": ...}`. Extend the controller's aux build to also include `ret_15m` and `ret_1h`:

```python
# In the aux dict that gets passed to strategy.signal():
aux = {
    ...,
    "ret_5m": ret_5m,
    "ret_15m": ret_15m,         # NEW: log return over last 15m
    "ret_1h":  ret_1h,           # NEW: log return over last 1h
    "abs_ret_5m_threshold": threshold,
    "require_multi_horizon": (symbol.upper(), tf) in V3_REQUIRE_MULTI_HORIZON,
}
```

`ret_15m` and `ret_1h` are computed analogously to `ret_5m` from `binance_klines_v2 1MIN` — see `_fetch_binance_close_at_or_before` for the existing pattern. The sub-skill `claude-api:claude-api` and `engineering:code-review` may help drafting these.

In `Updown5mStrategy.signal(...)`:
```python
def signal(self, closed_bars, config, aux):
    # ... existing magnitude / direction logic ...
    if aux.get("require_multi_horizon"):
        ret_5m = aux["ret_5m"]
        ret_15m = aux.get("ret_15m")
        ret_1h = aux.get("ret_1h")
        if ret_15m is None or ret_1h is None:
            return "NONE"
        # All three same sign (or all zero/positive)
        same_sign = (
            (ret_5m > 0 and ret_15m > 0 and ret_1h > 0)
            or (ret_5m < 0 and ret_15m < 0 and ret_1h < 0)
        )
        if not same_sign:
            return "NONE"
    # ... continue existing q10/q20/threshold logic ...
```

### 1.4 Spread filter

Right before the entry order is placed in the controller:

```python
yes_bid = book["bid_price_0"]
yes_ask = book["ask_price_0"]
mid = (yes_bid + yes_ask) / 2
spread_pct = (yes_ask - yes_bid) / mid if mid > 0 else 1.0
if spread_pct >= V3_SPREAD_FILTER_PCT:
    log.info("poly_updown.v3_spread_skip", spread_pct=spread_pct, slug=slug)
    record_event(slug, "poly_updown_signal", reason="wide_spread_skip", ...)
    return
```

(Same gate on the NO side when betting DOWN — substitute `no_bid` / `no_ask`.)

### 1.5 Maker entry

Reuse the existing maker-entry implementation (V2 paper-shadow has a stub at `place_entry_order(... entry_mode="maker" ...)`). Wire the env flag to switch on V3 sleeves:

```python
if entry_mode == "maker" and V3_MAKER_ENABLED:
    # Place limit buy at bid + 0.01
    quote_px = round(book["bid_price_0"] + 0.01, 2)
    submit_limit_order(token=outcome_token, side="buy", price=quote_px, qty=qty,
                       expiry_seconds=30)
    # If not filled within 30s -> fall back to taker
    # (existing executor handles this via place_entry_order's wait+fallback path)
```

If the existing executor doesn't have a wait+fallback path, add one: poll fill status every 5s, cancel and re-submit as taker at second 30.

### 1.6 Sleeve registration

In `engine/main.py` (or wherever sleeves are registered), add 3 V3 sleeves alongside V1/V2:

```python
# V3 sleeves: 5m only, per-asset gating
for symbol in ("BTC", "ETH", "SOL"):
    register_sleeve(
        sleeve_id=f"poly_updown_{symbol.lower()}_5m_v3",
        controller=PolyUpdownController(
            mode="v3",                # NEW mode flag
            symbol=symbol,
            tf="5m",
            hedge_policy="HEDGE_HOLD",
            entry_mode="maker",
            spread_filter_pct=0.02,
        ),
    )
```

Sleeve IDs prefixed `_v3` so they're attributable in `trading.events` separately from V1 (`poly_updown_btc_5m`) and V2 (`poly_updown_btc_5m_volume`, `poly_updown_btc_5m_sniper`).

### 1.7 Tests

`backend/tests/unit/test_v3_per_asset_quantile.py`:
```python
def test_v3_quantile_lookup_btc_5m():
    assert _v3_quantile_for("BTC", "5m") == 0.90
def test_v3_quantile_lookup_eth_5m():
    assert _v3_quantile_for("ETH", "5m") == 0.95
def test_v3_quantile_lookup_sol_5m():
    assert _v3_quantile_for("SOL", "5m") == 0.85
def test_v3_quantile_15m_returns_none():
    assert _v3_quantile_for("BTC", "15m") is None
def test_v3_multi_horizon_skips_when_disagree():
    aux = {"ret_5m": 0.01, "ret_15m": -0.005, "ret_1h": 0.001,
           "require_multi_horizon": True, "abs_ret_5m_threshold": 0.002}
    assert Updown5mStrategy().signal(None, None, aux) == "NONE"
def test_v3_multi_horizon_fires_when_agree():
    aux = {"ret_5m": 0.01, "ret_15m": 0.005, "ret_1h": 0.001,
           "require_multi_horizon": True, "abs_ret_5m_threshold": 0.002}
    assert Updown5mStrategy().signal(None, None, aux) == "UP"
```

`backend/tests/unit/test_v3_spread_filter.py`:
```python
def test_v3_spread_filter_skips_wide_spread():
    book = {"bid_price_0": 0.45, "ask_price_0": 0.50}  # spread 11%
    assert _spread_pct(book) >= 0.02
def test_v3_spread_filter_passes_tight_spread():
    book = {"bid_price_0": 0.495, "ask_price_0": 0.505}  # spread 2%
    assert _spread_pct(book) < 0.02 + 1e-9
```

`backend/tests/integration/test_v3_register_sleeves.py`:
```python
def test_v3_registers_3_sleeves_btc_eth_sol_5m_only():
    engine = make_engine(env={"TV_POLY_STRATEGY_MODES": "v3"})
    sleeves = engine.list_sleeves()
    v3_ids = [s for s in sleeves if "_v3" in s]
    assert sorted(v3_ids) == [
        "poly_updown_btc_5m_v3",
        "poly_updown_eth_5m_v3",
        "poly_updown_sol_5m_v3",
    ]
```

---

## 2. Configuration — `/etc/tv/tradingvenue.env` on VPS3

Add (don't replace V1/V2 lines):
```bash
# V3 portfolio sleeves alongside V2
TV_POLY_STRATEGY_MODES=volume,sniper,v3   # extend existing list
TV_POLY_HEDGE_POLICY=HEDGE_HOLD            # already correct per V2 fix plan
TV_POLY_V3_ENABLED=1                       # master gate
TV_POLY_V3_MAKER_ENABLED=1                 # maker entry overlay
TV_POLY_V3_SPREAD_FILTER_PCT=0.02          # skip entries with spread >= 2%
TV_POLY_V3_TIMEFRAMES=5m                   # 15m disabled
```

---

## 3. Data dependencies (zero new requirements)

V3 reuses everything V2 already needs:
- `binance_klines_v2` `source='binance-spot-ws'` `period='1MIN'` for BTC/ETH/SOL — **same backfill that unblocks V2 sniper unblocks V3.**
- `orderbook_snapshots_v2` (live) — book reads for spread filter and maker entry.
- `market_resolutions_v2` — already wired.

If VPS3's 14-day Binance backfill (per `docs/SNIPER_DATA_SPEC_VPS3.md`) is in place, V3 fires from boot. If not, V3 sleeves cold-start the same way V2 sniper does.

---

## 4. Sleeve count after V3 deploy

VPS3 will register up to 12 + 3 = **15 sleeves** after V3 lands:
- 6 V2 volume (`poly_updown_{btc,eth,sol}_{5m,15m}_volume`)
- 6 V2 sniper (`poly_updown_{btc,eth,sol}_{5m,15m}_sniper`)
- **3 V3** (`poly_updown_{btc,eth,sol}_5m_v3`)

VPS2 still runs V1 (6 sleeves, HEDGE_HOLD only). All three versions coexist for the A/B/C comparison.

---

## 5. Acceptance gates (post-deploy)

### D+1 (24 hours after deploy)

```sql
SELECT
  data->>'symbol' AS sym,
  COUNT(*) FILTER (WHERE kind='poly_updown_signal' AND data->>'reason'='order_placed') AS fires,
  COUNT(*) FILTER (WHERE kind='poly_updown_resolution' AND (data->>'won')::boolean) AS wins,
  COUNT(*) FILTER (WHERE kind='poly_updown_resolution') AS resolutions,
  ROUND(SUM((data->>'pnl_usd')::numeric)::numeric, 2) AS pnl
FROM trading.events
WHERE sleeve_id LIKE 'poly_updown_%_v3' AND at > now() - interval '24 hours'
GROUP BY 1;
```

Expected after backfill lands:
- BTC sleeve: 5-15 fires per day (q10 of 5m markets ≈ 28/day × 0.10 × 1 asset)
- ETH sleeve: 2-7 fires per day (q5 — half BTC's rate)
- SOL sleeve: 4-10 fires per day (q15 + multi-horizon — q15 alone is wider but multi-horizon trims)

Per-sleeve hit rate (paper, n≥10): target **≥55%**. Slack from backtest's 65-72% to allow for live-execution drift.

### D+7 (one week)

Per-sleeve hit rate target **≥60%** (n≥30 each). Combined portfolio paper PnL > 0 (on $25 stakes ≈ ≥$50/day).

### D+14 (two weeks)

If still passing: discuss live ramp ($1 per market initially, scale only after another 14 days).

---

## 6. Kill switches

Live in the controller / supervisor:

```python
# Per-sleeve auto-pause
PER_SLEEVE_DD_KILL = -0.10        # -10% sleeve drawdown
HIT_RATE_FLOOR    = 0.40          # halt sleeve if hit rate < 40% over n>=30
ALL_V3_DD_KILL    = -0.15         # halt entire V3 if combined DD < -15% in 24h
```

Implementation: extend the existing supervisor that reads `trading.events` and writes `trading.bots.status='paused'` when thresholds breach. V1/V2 already have this — V3 should reuse the same machinery, just keyed on `sleeve_id LIKE '%_v3'`.

---

## 7. Failure-mode contingencies

| What | Action |
|---|---|
| V3 fires zero events 6 hours after deploy | Check Binance backfill landed (per VPS3_FIX_PLAN). Sniper threshold path falls back to None until ≥50 samples. V3 is a strict subset of sniper — same gate applies. |
| V3 fires but hit rate <40% on n≥30 over 24h | Auto-paused by kill switch. Page operator. Investigate: is feed latency worse than V2? Are spreads wider than backtest? |
| V3 maker entries never fill (always falls back to taker) | Likely Polymarket book is tighter than expected (bid+0.01 ≥ ask). Drop maker overlay temporarily; expected ~1-2 pp ROI loss. |
| V3 spread filter rejects >50% of would-be entries | Either spread threshold too tight (try 0.025) OR markets are structurally wider than backtest. Re-tune from live data. |
| V3 outperforms V2 sniper materially in shadow | Plan upgrade: deprecate V2 sniper sleeves, route capital to V3. Decision point at D+30. |

---

## 8. Rollback

V3 is purely additive. To roll back:
1. `TV_POLY_V3_ENABLED=0` in `/etc/tv/tradingvenue.env`
2. Restart `tv-engine`. V3 sleeves stop registering. V1/V2 unchanged.
3. Optionally: prune existing V3 sleeves with `UPDATE trading.bots SET status='archived' WHERE sleeve_id LIKE '%_v3'`.

No DB schema changes. No oracle changes. No data migrations.

---

## 9. Estimated effort (TV agent)

| Task | Effort |
|---|---|
| Per-asset quantile lookup + V3 mode flag | 1h |
| Multi-horizon filter (extend strategy + aux build) | 2h |
| Spread filter pre-entry check | 1h |
| Maker entry wait+fallback (if not already from V2 work) | 2-4h |
| Sleeve registration | 30min |
| Unit + integration tests (~6 tests above) | 2h |
| Smoke deploy + verify | 1h |
| **TOTAL** | **~10-12 hours** |

Compatible with single-day PR + same-day deploy if VPS3 backfill is already in place.

---

## 10. References

- Backtest evidence: `strategy_lab/reports/RESEARCH_DEEP_DIVE_2026_04_29.md`
- Validation gauntlet: `strategy_lab/v2_signals/portfolio_gauntlet.py`
- Per-asset cells source-of-truth: `strategy_lab/v2_signals/portfolio_backtest.py` (`BEST_CELLS` dict)
- V2 baseline (for diffing): this folder's `TV_STRATEGY_V2_VPS3_IMPLEMENTATION_GUIDE.md`
- VPS3 prerequisites: `docs/VPS3_FIX_PLAN.md` (Binance backfill, HEDGE_HOLD env flag)
- Sim-vs-live diagnosis: `strategy_lab/reports/SIM_VS_LIVE_RECONCILIATION.md`

**End of guide.** Self-contained Phase V3 implementation for VPS3. All values from validated backtest evidence (8,189 markets × 7 days, 10-gate validation, forward-walk + bootstrap + permutation). Estimated bring-up: 10-12 hours dev + same-day deploy = **1 working day end-to-end** to V3 paper-shadow firing.
