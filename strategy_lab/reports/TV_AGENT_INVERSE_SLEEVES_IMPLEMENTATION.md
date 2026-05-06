# TV Agent: Implementation Guide — Inverse Sleeves (Shadow Mode)

**Recipient:** TV agent (Claude operating `/root/tv-bootstrap` and `/opt/tradingvenue` on VPS3 = `185.190.143.7`)
**Author:** Strategy lab (laptop)
**Date:** 2026-05-05
**Goal:** Add 3 inverse-signal sleeves alongside the existing losing sleeves to validate the anti-edge hypothesis IN PAPER MODE. No live capital.
**Source analysis:** `strategy_lab/reports/ANTI_EDGE_FINDINGS.md`

---

## 0 · Executive context

The existing `*_volume` and `*_sniper` sleeves on VPS3 are systematically losing. Statistical analysis of 6,111 trades over 5 days (Apr 30 → May 5) shows the losses are not random — they cluster on:

1. **Overnight UTC hours** (1-5 = Asian session, 9-10 = London open) for ALL `*_volume` sleeves on BTC/ETH/SOL
2. **All hours** for `sol_5m_sniper` (40% hit rate, symmetric across UP/DOWN)
3. **DOWN signals only** for `eth_5m_sniper` (35% hit rate on DOWN, 54% hit on UP)

Inversing those produces hit rates of 60-77% on backtest. We want to validate this is real (not regime-specific noise) by running the inverse in PAPER MODE alongside the originals for 1-2 weeks before committing to anything live.

---

## 1 · Sleeve specifications

Three new sleeves to create. ALL run in `mode='paper'` only. ALL share the same hedge-hold + $25/slot architecture as existing sleeves.

### Sleeve 1: `poly_updown_*_volume_INV_NIGHT` (6 instances)

**One per (symbol, tf) pair**: BTC/ETH/SOL × 5m/15m = 6 new sleeves.

Naming:
- `poly_updown_btc_5m_volume_INV_NIGHT`
- `poly_updown_eth_5m_volume_INV_NIGHT`
- `poly_updown_sol_5m_volume_INV_NIGHT`
- `poly_updown_btc_15m_volume_INV_NIGHT`
- `poly_updown_eth_15m_volume_INV_NIGHT`
- `poly_updown_sol_15m_volume_INV_NIGHT`

**Logic:**
```
1. Subscribe to the SAME signal stream as the existing poly_updown_{symbol}_{tf}_volume sleeve.
2. Get the current_utc_hour from window_start_at (NOT from server clock — must match the analysis cell).
3. If signal direction in {UP, DOWN}:
     If current_utc_hour in {1, 2, 3, 4, 5, 9, 10}:
         FLIP the direction (UP ↔ DOWN)
         Record event with sleeve_id = poly_updown_{symbol}_{tf}_volume_INV_NIGHT
     Else:
         No-op (don't record anything; we don't want to compete with the original)
4. If signal direction == NONE: no-op.
```

**Important**: the inverse sleeve only fires DURING the bias windows. Outside those hours, it's silent. This isolates the test cell.

### Sleeve 2: `poly_updown_sol_5m_sniper_INV` (1 instance)

**Symbol/tf**: SOL only, 5m only.

**Logic:**
```
1. Subscribe to the SAME signal stream as poly_updown_sol_5m_sniper.
2. If signal direction in {UP, DOWN}:
     FLIP the direction (UP ↔ DOWN)
     Record event with sleeve_id = poly_updown_sol_5m_sniper_INV
3. If signal direction == NONE: no-op.
```

No hour gating — flip every signal at any hour.

### Sleeve 3: `poly_updown_eth_5m_sniper_DOWN_INV` (1 instance)

**Symbol/tf**: ETH only, 5m only.

**Logic:**
```
1. Subscribe to the SAME signal stream as poly_updown_eth_5m_sniper.
2. If signal direction == DOWN:
     FLIP to UP
     Record event with sleeve_id = poly_updown_eth_5m_sniper_DOWN_INV
3. If signal direction in {UP, NONE}: no-op (UP signals already work fine).
```

---

## 2 · Implementation pattern (recommended architecture)

The cleanest pattern: a **strategy decorator** that wraps an existing strategy class and applies an inverse rule.

### Suggested code location

Based on existing structure observed (`/opt/tradingvenue/backend/app/strategies/polymarket/`):

```
/opt/tradingvenue/backend/app/strategies/polymarket/
  __init__.py
  base.py
  updown5m.py            # existing Updown5mStrategy
  updown15m.py           # existing Updown15mStrategy
  inverse.py             # NEW: InverseDecorator class
```

### Decorator class (pseudocode — adapt to actual SignalResult schema)

```python
# /opt/tradingvenue/backend/app/strategies/polymarket/inverse.py
from datetime import UTC
from typing import Callable, Optional
from backend.app.strategies.polymarket.base import (
    PolymarketBinaryStrategy, SignalResult,
)

class InverseDecorator(PolymarketBinaryStrategy):
    """
    Wraps a base strategy and inverts its signal direction conditionally.

    `condition_fn(window_start_at)` returns True if the signal should be flipped.
    If condition_fn is None, every UP/DOWN signal is flipped.
    `direction_filter` (optional) restricts flipping to a specific direction
    (e.g., only flip when base outputs DOWN).
    """
    def __init__(
        self,
        base: PolymarketBinaryStrategy,
        sleeve_id: str,
        condition_fn: Optional[Callable] = None,
        direction_filter: Optional[str] = None,  # 'UP' or 'DOWN' or None
    ):
        super().__init__()
        self._base = base
        self._sleeve_id = sleeve_id
        self._condition_fn = condition_fn
        self._direction_filter = direction_filter

    @property
    def sleeve_id(self) -> str:
        return self._sleeve_id

    def signal(self, *args, **kwargs) -> SignalResult:
        # Delegate ALL computation to the base strategy
        result = self._base.signal(*args, **kwargs)

        if result.signal not in ("UP", "DOWN"):
            return result  # NONE → pass through

        if self._direction_filter and result.signal != self._direction_filter:
            return SignalResult(signal="NONE", reason="inverse_skipped_wrong_direction")

        # Get window_start_at from the result or kwargs
        window_start = kwargs.get("window_start_at") or result.window_start_at
        if self._condition_fn and not self._condition_fn(window_start):
            return SignalResult(signal="NONE", reason="inverse_skipped_outside_window")

        # FLIP direction
        flipped = "DOWN" if result.signal == "UP" else "UP"
        return SignalResult(
            signal=flipped,
            reason=f"inverse_of_{result.signal}",
            # Carry over any other fields from result (strike, etc.)
            **{k: v for k, v in result.__dict__.items()
               if k not in ("signal", "reason")},
        )


def is_night_hour_utc(window_start_at) -> bool:
    """True if window_start_at is in UTC hours 1-5 or 9-10."""
    h = window_start_at.astimezone(UTC).hour
    return h in (1, 2, 3, 4, 5, 9, 10)
```

### Registration in PolymarketUpdownController

In `polymarket_updown_PROD.py` (or wherever the controller registers sleeves), add new entries:

```python
# Existing (don't touch, keep firing):
sleeves["poly_updown_btc_5m_volume"] = Updown5mVolumeStrategy(symbol="BTC")
# ... etc for all 6 existing volume sleeves + sniper sleeves

# NEW inverse sleeves (paper mode only):

# Sleeve set 1: ANTI-VOLUME-NIGHT (6 instances)
for symbol in ("BTC", "ETH", "SOL"):
    for tf in ("5m", "15m"):
        base_id = f"poly_updown_{symbol.lower()}_{tf}_volume"
        inv_id = f"{base_id}_INV_NIGHT"
        sleeves[inv_id] = InverseDecorator(
            base=sleeves[base_id],
            sleeve_id=inv_id,
            condition_fn=is_night_hour_utc,
        )

# Sleeve 2: SOL_5M_SNIPER full inverse
sleeves["poly_updown_sol_5m_sniper_INV"] = InverseDecorator(
    base=sleeves["poly_updown_sol_5m_sniper"],
    sleeve_id="poly_updown_sol_5m_sniper_INV",
    condition_fn=None,  # always flip
)

# Sleeve 3: ETH_5M_SNIPER DOWN-only inverse
sleeves["poly_updown_eth_5m_sniper_DOWN_INV"] = InverseDecorator(
    base=sleeves["poly_updown_eth_5m_sniper"],
    sleeve_id="poly_updown_eth_5m_sniper_DOWN_INV",
    condition_fn=None,
    direction_filter="DOWN",  # only flip DOWN signals
)
```

### Mode enforcement

Every inverse sleeve MUST be hard-coded to `mode="paper"`. Add a guard in the controller:

```python
INVERSE_SLEEVE_PREFIXES = ("_INV", "_INV_NIGHT")
def assert_paper_only(sleeve_id, mode):
    if any(sleeve_id.endswith(suffix) for suffix in INVERSE_SLEEVE_PREFIXES):
        assert mode == "paper", f"INVERSE sleeve {sleeve_id} MUST run paper-only, got mode={mode}"
```

---

## 3 · Database / event recording

**No schema changes required.** The `trading.events` table already supports arbitrary `sleeve_id` text values. The new sleeves will write `poly_updown_signal`, `poly_updown_resolution` events with the new `sleeve_id` strings, and the existing analysis queries on `kind = 'poly_updown_resolution'` will pick them up automatically.

The `data` JSONB payload should include:
```json
{
  "tf": "5m",
  "mode": "paper",
  "signal": "UP",  // the FLIPPED direction
  "symbol": "SOL",
  "strategy_mode": "inverse",  // NEW field — distinguishes from base sleeves
  "base_signal": "DOWN",  // NEW field — what the original sleeve said
  "inverse_reason": "night_hour" or "sol_sniper_full" or "eth_sniper_down_only"
}
```

This makes it trivial later to query `WHERE data->>'strategy_mode' = 'inverse'` and check inverse sleeve performance separately.

---

## 4 · Testing protocol

### 4.1 Unit tests (before deploying to VPS3 service)

In `/opt/tradingvenue/backend/tests/strategies/test_inverse.py`:

```python
def test_inverse_flips_up_to_down():
    base = MockStrategy(returns=SignalResult(signal="UP", reason="base_up"))
    inv = InverseDecorator(base, sleeve_id="test_INV")
    result = inv.signal(window_start_at=datetime(2026, 5, 5, 3, 0, tzinfo=UTC))
    assert result.signal == "DOWN"

def test_inverse_passes_through_none():
    base = MockStrategy(returns=SignalResult(signal="NONE"))
    inv = InverseDecorator(base, sleeve_id="test_INV")
    result = inv.signal(window_start_at=datetime(2026, 5, 5, 3, 0, tzinfo=UTC))
    assert result.signal == "NONE"

def test_night_hour_condition_outside_window():
    base = MockStrategy(returns=SignalResult(signal="UP"))
    inv = InverseDecorator(base, sleeve_id="test_INV", condition_fn=is_night_hour_utc)
    # 12:00 UTC is NOT a night hour
    result = inv.signal(window_start_at=datetime(2026, 5, 5, 12, 0, tzinfo=UTC))
    assert result.signal == "NONE"  # filtered out

def test_night_hour_condition_inside_window():
    base = MockStrategy(returns=SignalResult(signal="UP"))
    inv = InverseDecorator(base, sleeve_id="test_INV", condition_fn=is_night_hour_utc)
    # 03:00 UTC IS a night hour
    result = inv.signal(window_start_at=datetime(2026, 5, 5, 3, 0, tzinfo=UTC))
    assert result.signal == "DOWN"  # flipped

def test_direction_filter_skips_wrong_direction():
    base = MockStrategy(returns=SignalResult(signal="UP"))
    inv = InverseDecorator(base, sleeve_id="test_INV", direction_filter="DOWN")
    result = inv.signal(window_start_at=datetime(2026, 5, 5, 3, 0, tzinfo=UTC))
    assert result.signal == "NONE"  # only flips DOWN, so UP is skipped
```

### 4.2 Integration smoke test

Before enabling in `tv-engine.service`:
1. Run controller in dev mode against last 24h of paper signals.
2. Verify each inverse sleeve fires the expected count (~10-30 per day for sniper inverses, ~50-100 per day for volume night inverses).
3. Verify base sleeves still fire normally (no regression).
4. Verify all inverse trades have `mode='paper'` and `strategy_mode='inverse'` in their event data.

### 4.3 Production deployment

1. Merge code via standard PR process (`/root/tv-bootstrap` workflow).
2. Restart `tv-engine.service`: `systemctl restart tv-engine`.
3. Verify logs: `journalctl -u tv-engine -f | grep -i inverse`.
4. After 1 hour, verify events landing in DB:
   ```sql
   SELECT sleeve_id, COUNT(*) FROM trading.events
   WHERE kind='poly_updown_signal'
     AND sleeve_id LIKE '%_INV%'
     AND at > NOW() - INTERVAL '1 hour'
   GROUP BY sleeve_id;
   ```

---

## 5 · Monitoring & validation criteria

After 1 week of paper-trading, the lab will pull fresh data and re-run `anti_edge_analyzer.py` to verify:

### Pass criteria (all 3 must hold for an inverse sleeve to be "validated")

| Criterion | Threshold |
|---|---|
| **Sample size** | ≥ 50 paper trades for the inverse sleeve |
| **Hit rate** | ≥ 55% (must beat 50/50 by at least 5pp) |
| **PnL** | ≥ +$5 per trade on $25 stakes |
| **Stability** | Hit rate within ±5pp of analysis cell prediction |

### Specific targets per inverse sleeve

| Inverse Sleeve | Predicted Hit | Pass If |
|---|---|---|
| `*_volume_INV_NIGHT` (combined) | 60-65% | ≥ 55% on ≥50 trades |
| `sol_5m_sniper_INV` | 60.2% | ≥ 55% on ≥50 trades |
| `eth_5m_sniper_DOWN_INV` | 65.1% | ≥ 60% on ≥30 trades (smaller universe) |

### Fail criteria (kill the inverse sleeve immediately)

- Hit rate falls below 45% over rolling 50 trades → kill (means the bias has reversed, regime change)
- Total paper PnL goes below -$200 → kill (something structurally wrong)

---

## 6 · Path C — Re-validation schedule (laptop side)

The lab will:

1. **Daily**: Light query to count new inverse sleeve events:
   ```sql
   SELECT sleeve_id, COUNT(*) AS n_today
   FROM trading.events
   WHERE kind = 'poly_updown_resolution'
     AND sleeve_id LIKE '%_INV%'
     AND at::date = CURRENT_DATE
   GROUP BY sleeve_id;
   ```

2. **Every 7 days**: Pull fresh `losing_sleeves.csv` AND a new `inverse_sleeves_resolutions.csv`. Re-run `strategy_lab/meta_classifier/anti_edge_analyzer.py` (already implemented).

3. **At the 1-week and 2-week marks**: Apply pass/fail criteria above. Document outcome in a follow-up report:
   - `strategy_lab/reports/ANTI_EDGE_VALIDATION_WEEK1.md`
   - `strategy_lab/reports/ANTI_EDGE_VALIDATION_WEEK2.md`

4. **At the 2-week mark, IF all criteria pass**:
   - Promote 1 or 2 winning inverse sleeves to live mode (small size, e.g., $25/slot remains).
   - Continue paper-mode monitoring for any losers.
   - The other 4-5 inverse sleeves stay in paper indefinitely as a control group.

---

## 7 · Operational checklist for TV agent

| Step | Action | Owner | Done |
|---|---|---|---|
| 1 | Read `strategy_lab/reports/ANTI_EDGE_FINDINGS.md` for full context | TV agent | [ ] |
| 2 | Create `/opt/tradingvenue/backend/app/strategies/polymarket/inverse.py` with `InverseDecorator` + `is_night_hour_utc` | TV agent | [ ] |
| 3 | Update controller registration to add 8 new inverse sleeves (6 volume_INV_NIGHT + 1 sol_sniper_INV + 1 eth_sniper_DOWN_INV) | TV agent | [ ] |
| 4 | Add paper-mode hard-guard for any sleeve_id ending in `_INV` or `_INV_NIGHT` | TV agent | [ ] |
| 5 | Add `strategy_mode` and `base_signal` fields to event payload for inverse sleeves | TV agent | [ ] |
| 6 | Write unit tests in `tests/strategies/test_inverse.py` | TV agent | [ ] |
| 7 | Run tests + integration smoke test against last 24h signals | TV agent | [ ] |
| 8 | Merge → restart `tv-engine.service` → verify logs | TV agent | [ ] |
| 9 | Verify inverse events landing in `trading.events` after 1 hour | TV agent | [ ] |
| 10 | Report back to lab with confirmation + first-hour fire counts per inverse sleeve | TV agent | [ ] |
| 11 | Lab pulls week-1 data and re-runs analyzer | Lab | [ ] |
| 12 | Apply pass/fail criteria, decide which inverse sleeves graduate | Lab + TV agent | [ ] |

---

## 8 · Rollback / kill switch

If anything goes wrong, kill all inverse sleeves with one SQL toggle (assuming sleeve registration reads from a config table; if hardcoded, use feature flag in env):

```bash
# Quick kill — set env var and restart
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "echo 'TV_INVERSE_SLEEVES_ENABLED=false' >> /etc/tv/tradingvenue.env && systemctl restart tv-engine"
```

The controller code should respect this env var:
```python
INVERSE_ENABLED = os.environ.get("TV_INVERSE_SLEEVES_ENABLED", "true").lower() == "true"
if INVERSE_ENABLED:
    # register the inverse sleeves
    ...
```

---

## 9 · Open questions for the TV agent (please answer in your reply)

1. **Where exactly is the controller's sleeve registration?** I assumed `polymarket_updown_PROD.py` based on the file name, but the actual class name and the registration list path may differ. Adjust the code path in §2 accordingly.
2. **What's the exact `SignalResult` dataclass schema?** I sketched the inverse based on what I saw in the `poly_updown_resolution` event payload (signal, outcome, won, etc.). The base class may have additional fields that need preserving.
3. **Is there an existing pattern for "parameter-only" sleeve variants?** (e.g., the `_v3_1` / `_v3_2` / `_v3_3` family suggests there's already a way to fork a base strategy with different parameters.) If so, the InverseDecorator may be redundant — could just be a config toggle on the existing strategies.
4. **Does the controller dispatch to ALL registered sleeves on every market signal, or only one per (symbol, tf)?** If the latter, the inverse sleeves need a separate dispatch path so they don't compete with the originals for the (symbol, tf) slot.
5. **Hedge-hold logic on inverse sleeves**: should it apply, or skip? My recommendation: SKIP hedge-hold on inverse sleeves (they're paper-only, no real position to hedge). But the dispatcher may still call `on_tick` and try to compute a hedge — make sure that's a no-op for inverse sleeves.

---

## 10 · References

- **Source analysis**: `strategy_lab/reports/ANTI_EDGE_FINDINGS.md`
- **Raw data**: `data/v4/shadow_trades_2026_05_05_live/losing_sleeves.csv` (6,111 trades)
- **Per-cell breakdown**: `strategy_lab/results/meta_classifier/anti_edge_breakdown.csv`
- **Re-runnable analyzer**: `strategy_lab/meta_classifier/anti_edge_analyzer.py`
- **VPS3 connection**: `root@185.190.143.7` via `~/.ssh/vps3_ed25519`
- **DB connection**: `postgresql://tradingvenue:<VPS3_TV_PWD>@127.0.0.1:5432/storedata`
- **Existing controller**: `/root/tv-bootstrap/.planning/phases/15-polymarket-updown-strategies/` (Phase 15)
- **Shadow week phase**: `/root/tv-bootstrap/.planning/phases/18-trader-shadow-week/`

---

*End of TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md. Awaiting TV agent confirmation that inverse sleeves are deployed in paper mode. Lab will check back in 7 days for week-1 validation.*
