# TV agent — VWAP Continuation strategy implementation spec

_2026-05-23. Production-ready 5m strategy validated overnight. Best single
config: BTC 240s offset + 5-10bps deviation + M1V Markov gate → 86.3% WR,
+$2.10/tr legacy, +$1.91/tr live-mimic, n=546 over 28d. Out-of-sample
test WR=89%. Loss streak max=3. Sharpe annual=8.12._

## 1. Strategy summary

**Name**: `poly_updown_vwap_continuation` (paper-only initially)
**Markets**: BTC/ETH/SOL 5m chainlink-resolved up-down markets
**Fire timing**: LATE-fire — 30 to 270 seconds INTO each 5m slot (not at
slot_open like sniper, not at ws_s+120 like momo v1)
**Signal**: binance close has deviated from its 15m-anchored VWAP →
bet WITH the deviation (continuation, not fade)
**Filter**: 1-min Markov vol-adaptive regime must agree with bet direction

## 2. Signal definition

At fire time `t` (= `slot_start_s + fire_offset_s`):

1. **VWAP_15m_anchored** = `Σ(close[i] · vol[i]) / Σ(vol[i])` over all
   1-second binance bars from start of current UTC 15m bucket to `t`.
   - Bucket start = `(t // 900) * 900` seconds.
   - Uses 1-second binance kline data (already collected in
     `binance_klines_v2.period_id='1SEC'`).

2. **dev_bps** = `10_000 · log(close@t / VWAP_15m_anchored)`.
   - Positive = binance is above VWAP. Negative = below.

3. **Bet direction**:
   - if `dev_bps > +thr` → bet UP
   - if `dev_bps < -thr` → bet DOWN
   - `thr` is cell-specific (see §3)

4. **Markov filter** (M1V, same as existing `m1va` gate spec):
   - Compute regime from prior 14d of 1-min binance log returns + last
     20 closes (vol-adaptive tertiles).
   - UP bet requires regime == 2 (Bull). DOWN bet requires regime == 0 (Bear).
   - Sideways/warmup → SKIP fire.

5. **Optional gates** (per cell):
   - **F7 RSI(14)** — UP requires RSI > 50, DOWN requires RSI < 50
   - **Cross-asset confluence** — partial: at least one of the other 2
     crypto assets has dev_bps with same sign at fire time

## 3. Per-cell parameters (deploy these 5 sleeves)

| sleeve_id | fire_offset_s | dev_thr_min_bps | dev_thr_max_bps | gates |
|---|--:|--:|--:|---|
| `poly_updown_btc_5m_vwap_off240_m1v` | 240 | 5 | 10 | M1V |
| `poly_updown_btc_5m_vwap_off60_f7_cross` | 60 | 10 | 15 | F7 + cross_full |
| `poly_updown_btc_5m_vwap_off90_cross` | 90 | 10 | 15 | cross_full |
| `poly_updown_eth_5m_vwap_off210_f7_m1v` | 210 | 10 | 15 | F7 + M1V |
| `poly_updown_sol_5m_vwap_off60` | 60 | 20 | 30 | (none — bare) |

`cross_full` = both OTHER assets' dev_bps match bet direction at fire time.

## 4. Expected performance (28d backtest, $25 notional, LegacyConfig)

| sleeve | n/wk | WR | $/tr | sum/wk |
|---|--:|--:|--:|--:|
| btc_5m_vwap_off240_m1v | 137 | 86.3% | +$2.00 | +$272 |
| btc_5m_vwap_off60_f7_cross | 41 | 73.2% | +$2.77 | +$114 |
| btc_5m_vwap_off90_cross | 55 | 77.8% | +$1.77 | +$98 |
| eth_5m_vwap_off210_f7_m1v | 47 | 92.6% | +$1.26 | +$59 |
| sol_5m_vwap_off60 | 16 | 75.0% | +$1.66 | +$27 |
| **ensemble** | **296** | **avg 81%** | **+$1.90** | **+$570** |

That's roughly **$80/day at $25 notional** or **$800/day at $250 notional**.

## 5. Files to add / modify on VPS3

### New module: `backend/app/strategies/polymarket/vwap_continuation.py`

```python
"""VWAP Continuation strategy (Phase 35).

Fires at multiple offsets into a 5m slot when binance has clearly
deviated from its 15m anchored VWAP. Bets WITH the deviation. Filtered
by M1V Markov regime agreement.

INVARIANTS (CLAUDE.md inv #4): pure signal function, no IO inside.
Reads aux populated by poly_updown_loop.py.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from backend.app.strategies.polymarket.base import (
    PolymarketBinaryStrategy,
    SignalConfig,
    SignalResult,
)
from backend.app.strategies.polymarket.markov import label_regime_vol_adaptive

if TYPE_CHECKING:  # pragma: no cover
    from backend.app.data.models import Bar


class VwapContinuationStrategy(PolymarketBinaryStrategy):
    """Late-fire VWAP continuation. Reads aux from t_plus_30/60/90/120/150/180/210/240 phase."""
    name = "vwap_continuation"

    def __init__(
        self,
        *,
        fire_offset_s: int,
        dev_thr_min_bps: float,
        dev_thr_max_bps: float,
        require_m1v: bool = False,
        require_f7: bool = False,
        require_cross_full: bool = False,
        require_cross_partial: bool = False,
    ) -> None:
        self.fire_offset_s = int(fire_offset_s)
        self.dev_min = float(dev_thr_min_bps)
        self.dev_max = float(dev_thr_max_bps)
        self.require_m1v = bool(require_m1v)
        self.require_f7 = bool(require_f7)
        self.require_cross_full = bool(require_cross_full)
        self.require_cross_partial = bool(require_cross_partial)

    def signal(
        self,
        bars: list[Bar],
        config: SignalConfig | None = None,
        aux: dict | None = None,
    ) -> SignalResult:
        if aux is None:
            return "NONE"
        # Phase guard — only fire on the matching late-fire phase.
        expected_phase = f"t_plus_{self.fire_offset_s}"
        if aux.get("bar_ctx_phase") != expected_phase:
            return "NONE"
        dev_bps = aux.get("vwap_dev_bps")
        if dev_bps is None or not math.isfinite(dev_bps):
            return "NONE"
        abs_dev = abs(dev_bps)
        if not (self.dev_min < abs_dev <= self.dev_max):
            return "NONE"
        direction: SignalResult = "UP" if dev_bps > 0 else "DOWN"
        # M1V gate
        if self.require_m1v:
            regime = aux.get("markov_regime_w20_1m_va")
            if regime is None:
                return "NONE"
            if direction == "UP" and regime != 2:
                return "NONE"
            if direction == "DOWN" and regime != 0:
                return "NONE"
        # F7 RSI gate
        if self.require_f7:
            rsi = aux.get("rsi_14_for_signal")
            if rsi is None or not math.isfinite(rsi):
                return "NONE"
            if direction == "UP" and rsi <= 50:
                return "NONE"
            if direction == "DOWN" and rsi >= 50:
                return "NONE"
        # Cross-asset confluence
        if self.require_cross_full or self.require_cross_partial:
            cross_dev = aux.get("cross_asset_devs")  # list of (asset, dev_bps)
            if not cross_dev:
                return "NONE"
            agree_count = 0
            for _, d in cross_dev:
                if d is None or not math.isfinite(d):
                    continue
                if direction == "UP" and d > 0:
                    agree_count += 1
                elif direction == "DOWN" and d < 0:
                    agree_count += 1
            need = len(cross_dev) if self.require_cross_full else 1
            if agree_count < need:
                return "NONE"
        return direction


__all__ = ["VwapContinuationStrategy"]
```

### Modify `backend/app/engine/poly_updown_loop.py`

Add multiple late-fire dispatches. Each fires at `slot_start + N` for
N ∈ {30, 60, 90, 120, 150, 180, 210, 240, 270}. For each, build a
BarContext with `phase=f"t_plus_{N}"` containing:

```python
aux = {
    "bar_ctx_phase": f"t_plus_{N}",
    "vwap_dev_bps": float,                  # 10_000 · log(close@now / vwap_15m_anchored)
    "vwap_15m_anchored": float,              # cumulative vwap since 15m bucket start
    "rsi_14_for_signal": float,              # same as today
    "markov_regime_w20_1m_va": int,          # NEW — computed from 1m binance closes + 14d returns
    "cross_asset_devs": [(asset, dev_bps), ...],  # the OTHER two crypto assets' dev_bps
}
```

Computation of `vwap_15m_anchored`:
- Maintain a per-asset running (cum_px_vol, cum_vol) since start of
  current 15m UTC bucket.
- Reset at each bucket boundary (every 15min on the 00/15/30/45 mark UTC).
- `vwap = cum_px_vol / cum_vol`.
- Uses 1-second binance klines (already collected — see
  `binance_klines_v2.period_id='1SEC'`).

Computation of `markov_regime_w20_1m_va`:
- See existing M1V spec in `TV_AGENT_PHASE34_FIXES_2026_05_22.md` §4.4.
- Same compute, same caching.

Computation of `cross_asset_devs`:
- For each fire candidate, compute dev_bps for the OTHER two assets at
  the same UTC timestamp.

### Modify `backend/app/engine/main.py` — register 5 sleeves

Add to `_SHADOW_GATED_SLEEVES_SPEC` or a new `_VWAP_SLEEVES_SPEC`:

```python
_VWAP_CONT_SLEEVES_SPEC = (
    # (sleeve_id, asset, tf, offset_s, dev_min, dev_max, gates_tuple, hedge_policy)
    ("poly_updown_btc_5m_vwap_off240_m1v",
     "BTC", "5m", 240, 5, 10, ("m1v",), "HOLD_ONLY"),
    ("poly_updown_btc_5m_vwap_off60_f7_cross",
     "BTC", "5m", 60, 10, 15, ("f7", "cross_full"), "HOLD_ONLY"),
    ("poly_updown_btc_5m_vwap_off90_cross",
     "BTC", "5m", 90, 10, 15, ("cross_full",), "HOLD_ONLY"),
    ("poly_updown_eth_5m_vwap_off210_f7_m1v",
     "ETH", "5m", 210, 10, 15, ("f7", "m1v"), "HOLD_ONLY"),
    ("poly_updown_sol_5m_vwap_off60",
     "SOL", "5m", 60, 20, 30, (), "HOLD_ONLY"),
)
```

Enable via env: `TV_POLY_VWAP_CONT_ENABLED=true` (default false until ready).

## 6. Validation post-deploy

Same pattern as Phase 34:

```sql
-- 1h after deploy: all 5 sleeves emitted signals
SELECT sleeve_id, COUNT(*) FROM trading.events
WHERE at > NOW() - INTERVAL '1 hour'
  AND kind = 'poly_updown_signal'
  AND sleeve_id LIKE '%vwap%'
GROUP BY 1;
-- Expect: 5 rows.

-- 24h after deploy: WR matches expected ranges per §4
SELECT sleeve_id, COUNT(*) AS n,
       AVG(CASE WHEN data->>'won' = 'true' THEN 1.0 ELSE 0.0 END) AS wr,
       SUM((data->>'pnl_usd')::numeric) AS sum_pnl
FROM trading.events
WHERE at > NOW() - INTERVAL '24 hours'
  AND kind = 'poly_updown_resolution'
  AND sleeve_id LIKE '%vwap%'
GROUP BY 1;
-- Expect: btc_5m_vwap_off240_m1v WR >= 80%, ETH 210 >= 90%.
```

## 7. Risk + caveats

- **Sample size of best config = n=546 in 28d**. Not huge but not tiny.
  Test_wr (n=164) of 89% confirms in OOS.
- **Late-fire (240s in) means only 60s remain in the 5m slot**. Order
  placement latency must be < 5s or fills will be at slot_end levels
  (very close to settlement, near-zero spread but also near-zero edge).
- **Fee model**: backtest uses LegacyConfig (2%-on-profit-only) which
  matches production-actual fees per CLAUDE.md (verified vs 25,900 prod
  resolutions). $1,090 sum is the realistic number. A separate live-mimic
  stress test under the hypothetical `0.07·p·(1−p)`-per-share curve
  (Polymarket general docs, NOT production reality) erodes PnL by
  ~7.3% to $1,010 — i.e., the strategy still survives even the
  worst-case scenario if Polymarket ever switches fee models.
- **No sniper/momo overlap** — VWAP continuation fires at slot_start+30
  to +270, sniper at slot_start, momo at slot_start-window_s+120. Can
  deploy alongside without contention.
- **L25 book staleness**: at 240s into a 5m slot, the book has 240s of
  history — plenty of events. min_book_events=25 filter rarely trips.
- **Cross-asset confluence**: requires concurrent dev_bps computation
  for BTC/ETH/SOL. Already trivial if 1s feeds are running.

## 8. Rollback

If any sleeve WR < 50% after 24h:
```bash
sudo sed -i 's/^TV_POLY_VWAP_CONT_ENABLED=true/TV_POLY_VWAP_CONT_ENABLED=false/' /etc/tv/tradingvenue.env
sudo systemctl restart tv-engine
```

## 9. Files added/modified

| File | Change |
|---|---|
| `backend/app/strategies/polymarket/vwap_continuation.py` | NEW — strategy class |
| `backend/app/engine/poly_updown_loop.py` | MODIFY — add late-fire phase builders, new aux fields |
| `backend/app/engine/main.py` | MODIFY — register 5 vwap_continuation sleeves |
| `backend/tests/strategies/polymarket/test_vwap_continuation.py` | NEW — unit tests |
| `/etc/tv/tradingvenue.env` | NEW env var `TV_POLY_VWAP_CONT_ENABLED` |

## 10. References

- Backtest: `strategy_lab/reports/VWAP_CONTINUATION_5M_2026_05_23.md`
- Gated v2: `strategy_lab/reports/VWAP_CONT_V2_GATED_2026_05_23.md`
- Drawdown + live-mimic: `strategy_lab/reports/VWAP_DRAWDOWN_LIVEMIMIC_2026_05_23.md`
- Synthesis: `strategy_lab/reports/OVERNIGHT_STRATEGY_RUN_2026_05_23.md`
- Existing M1V spec (for reuse): `strategy_lab/reports/TV_AGENT_PHASE34_FIXES_2026_05_22.md` §4
