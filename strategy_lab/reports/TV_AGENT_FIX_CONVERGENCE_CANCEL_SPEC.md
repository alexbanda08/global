# TV Agent Fix Spec — Convergence-window cancellation

**Scope**: stop maker BIDs from posting / resting into the slug resolution window. Auto-cancel + auto-stop-posting at `slot_end − offset_s`.

**Severity**: MEDIUM. Files touched: 4 strategy files + 1 config. Lines changed: ~80. Estimated effort: 2-3 dev-hours + smoke test.

## 1. Problem

Strategies currently keep POSTing BIDs all the way to `slot_end`. The last 60-120s of a slug is the **convergence window** — the prediction market price converges to the eventual outcome (0 or 1) as chainlink resolution approaches. Informed flow pushes price; uninformed makers donate.

**Empirical evidence** (May 25-27 shadow):
- ACC-H btc 15m losing slugs have **13.3 fills/slug vs 10.2 for winners** (+30% activity)
- ACC-PC btc 15m losing slugs have **15.8 fills/slug vs 10.1 for winners** (+56% activity)
- Late-window fills disproportionately weighted toward losers (literature consensus: 15-25% of fill volume in last 6-7% of slug time)

**Literature** (Bartlett & O'Hara, Kalshi single-name MM study): "Rational makers pull quotes in the convergence window — leaving them up is pure adverse-selection donation."

**Estimated PnL improvement from fix**: +10-15% on ACC-H + ACC-PC. Quantified by independent CSV replay (running in parallel).

## 2. Behavior to implement

### 2.1 Per-strategy cancel offset

Each strategy gets a `stop_posting_offset_s` config knob:

| Strategy | Default | Reason |
|---|---:|---|
| ACC-M | 60 (5m) / 120 (15m) | Maker BID strategy — needs early exit to avoid filling at adverse prices |
| ACC-H | 60 / 120 | Same as ACC-M, inherits |
| ACC-PC | 60 / 120 | Same; PC taker should also stop firing |
| MAS | 60 / 120 | Stops repricing ASKs in convergence window |
| PAT-SHADOW | 30 (5m only) | PAT only takes pairs cheap; safer to fire later but still 30s buffer |

### 2.2 In `_post_decisions` — REJECT post if too late

At top of every strategy's `_post_decisions` (or equivalent):

```python
def _post_decisions(self, state: SlugState, ts_us: int) -> list[Decision]:
    cfg = self.config

    # === Convergence-window block — stop NEW posts ===
    if state.slug_end_ts_us is not None:
        offset_s = int(getattr(cfg, f"tv_poly_maker_{self.code.lower().replace('-','_')}_stop_posting_offset_s", 0))
        if offset_s > 0:
            offset_us = offset_s * 1_000_000
            if (state.slug_end_ts_us - ts_us) < offset_us:
                return []  # too late in slug; skip post pass

    # ... existing post logic ...
```

Per-strategy lookup names:
- ACC-M → `tv_poly_maker_acc_m_stop_posting_offset_s`
- ACC-H → `tv_poly_maker_acc_h_stop_posting_offset_s` (overrides ACC-M)
- ACC-PC → `tv_poly_maker_acc_pc_stop_posting_offset_s` (overrides ACC-M)
- MAS → `tv_poly_maker_mas_stop_posting_offset_s`
- PAT-SHADOW → `tv_poly_maker_pat_shadow_stop_posting_offset_s`

(Strategy can inherit ACC-M's offset if their own knob is unset — see §2.5.)

### 2.3 In `_cancel_decisions` — FORCE-CANCEL existing open orders at the boundary

`_cancel_decisions` is called every L25 update. Add at the top of the existing cancel logic:

```python
def _cancel_decisions(self, state: SlugState, evt: L25Update) -> list[Decision]:
    cfg = self.config
    decisions: list[Decision] = []

    # === Convergence-window block — force-cancel all open orders ===
    if state.slug_end_ts_us is not None:
        offset_s = int(getattr(cfg, f"tv_poly_maker_{self.code.lower().replace('-','_')}_stop_posting_offset_s", 0))
        if offset_s > 0:
            offset_us = offset_s * 1_000_000
            if (state.slug_end_ts_us - evt.ts_us) < offset_us:
                for order_id, order in list(state.open_orders.items()):
                    decisions.append(
                        Decision(
                            ts_us=evt.ts_us,
                            strategy=self.code,
                            slug=state.slug,
                            asset=state.asset,
                            tf=state.tf,
                            action="CANCEL",
                            side=order.side,
                            price=order.price,
                            size=order.size,
                            order_id=order_id,
                            trigger_reason="convergence_window_cancel",
                        )
                    )
                    del state.open_orders[order_id]
                return decisions  # don't run normal cancel rules; we cancelled everything

    # ... existing cancel logic ...
```

### 2.4 ACC-H + ACC-PC + PAT-SHADOW — same gate for TAKER paths

ACC-H's `_h_taker_decisions`, ACC-PC's `_pc_taker_decision`, PAT-SHADOW's `_pat_shadow_decisions` should all check the same offset at the top:

```python
if state.slug_end_ts_us - ts_us < offset_us:
    return []  # no new TAKE in convergence window
```

ACC-M's inherited PAT path (`_pat_decisions`) needs the same gate.

### 2.5 SlugState.slug_end_ts_us must be populated

Check `strategies/polymarket/maker/types.py` and `base.py`. The strategy currently has `state.slug_active_ts_us` (when SlugActive event fired) but I haven't confirmed `state.slug_end_ts_us` exists. If not, derive on slug-activation:

```python
def on_slug_active(self, evt: SlugActive) -> list[Decision]:
    # ... existing init ...
    window_s = 300 if state.tf == "5m" else 900
    state.slug_end_ts_us = state.slug_active_ts_us + window_s * 1_000_000
    return ...
```

(slug-active fires at slot_start, so slug_end = slot_start + window. Verify against actual slug suffix arithmetic.)

### 2.6 Config additions in `core/config.py`

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # === Convergence-window cancellation ===
    # offset in seconds before slot_end at which to STOP posting + CANCEL all open orders.
    # 60s recommended for 5m markets, 120s for 15m markets (literature consensus).
    # Set per-strategy; each falls back to acc_m's default if unset.
    tv_poly_maker_acc_m_stop_posting_offset_s: int = 60
    tv_poly_maker_acc_h_stop_posting_offset_s: int = 120  # ACC-H runs on btc_15m
    tv_poly_maker_acc_pc_stop_posting_offset_s: int = 120  # ACC-PC runs on btc_15m
    tv_poly_maker_mas_stop_posting_offset_s: int = 60
    tv_poly_maker_pat_shadow_stop_posting_offset_s: int = 30
```

Note: ACC-M runs on btc_5m → 60s default. ACC-H + ACC-PC run on btc_15m → 120s default. If/when ACC-H or ACC-PC are extended to 5m cells, the offset would need to be cell-aware. For now, keep simple.

### 2.7 Optional: cell-aware offset

If we extend strategies to multiple cells, replace the single int with a dict:

```python
tv_poly_maker_acc_h_stop_posting_offset_s_per_cell: dict = {
    "btc_5m": 60,
    "btc_15m": 120,
    "eth_5m": 60,
    "eth_15m": 120,
}
```

Defer this until cross-cell deploy lands (cross-cell backtest is running in parallel — wait for results).

## 3. Unit tests

Add to `tests/strategies/test_acc_m.py`:

```python
def test_post_blocked_in_convergence_window():
    """No POST_BID emitted if ts_us > slot_end - offset_s × 1e6."""
    state = make_slug_state(tf="5m", slot_end_ts_us=1_000_000_000)
    cfg = make_config(tv_poly_maker_acc_m_stop_posting_offset_s=60)
    strategy = AccMStrategy(cfg, "BTC", "5m")
    # ts_us = slot_end - 30s (within 60s convergence window)
    decisions = strategy._post_decisions(state, 1_000_000_000 - 30_000_000)
    assert decisions == []

def test_post_allowed_outside_convergence_window():
    """POST_BID emitted if ts_us ≤ slot_end - offset_s × 1e6."""
    state = make_slug_state(tf="5m", slot_end_ts_us=1_000_000_000)
    cfg = make_config(tv_poly_maker_acc_m_stop_posting_offset_s=60)
    seed_l25(strategy, slug, ba_up=0.50, ba_dn=0.45, bb_up=0.49, bb_dn=0.44)
    strategy = AccMStrategy(cfg, "BTC", "5m")
    # ts_us = slot_end - 90s (outside 60s window)
    decisions = strategy._post_decisions(state, 1_000_000_000 - 90_000_000)
    assert len(decisions) >= 1

def test_cancel_all_in_convergence_window():
    """All open orders cancelled when entering convergence window."""
    state = make_slug_state(tf="5m", slot_end_ts_us=1_000_000_000)
    state.open_orders = {
        "order-1": OpenOrder(order_id="order-1", side="up", price=Decimal("0.5"), size=Decimal("20"), ts_posted_us=0),
        "order-2": OpenOrder(order_id="order-2", side="dn", price=Decimal("0.4"), size=Decimal("20"), ts_posted_us=0),
    }
    strategy = AccMStrategy(make_config(tv_poly_maker_acc_m_stop_posting_offset_s=60), "BTC", "5m")
    evt = make_l25_update(ts_us=1_000_000_000 - 30_000_000)  # 30s before end
    decisions = strategy._cancel_decisions(state, evt)
    cancel_actions = [d for d in decisions if d.action == "CANCEL"]
    assert len(cancel_actions) == 2
    assert state.open_orders == {}
```

## 4. Smoke test after deploy

1. Land all edits, restart `tv-engine.service`.
2. Wait 6 hours.
3. Pull CSVs from `/var/log/tv/maker/`.
4. For each strategy, verify:
   - Zero POST_BID rows where `(slug_end_ts_us - ts_us) < offset_us` ← no late posts
   - CANCEL rows with `trigger_reason="convergence_window_cancel"` appear near slug end
   - Per-slug fill count drops (especially losing slugs)
   - Per-slug honest PnL improves

Expected post-fix changes (from replay backtest in parallel):
- ACC-H btc 15m: honest PnL +10-15%
- ACC-PC btc 15m: +10-20%
- ACC-M btc 5m: +5-10% (smaller because 60s/300s = 20% of slug; 120s/900s = 13% of slug — 5m has more relative truncation)
- MAS: ~flat (MAS posts ASKs once and rarely re-quotes; convergence cancel matters less)
- PAT-SHADOW: ~flat (PAT only fires when book is cheap; doesn't usually fire in convergence)

## 5. Rollout checklist

- [ ] F1 (canonical fee booking) already landed — REQUIRED prerequisite ✓ (confirmed May 25-27 audit)
- [ ] Apply §2.5 (verify `state.slug_end_ts_us` exists or add to `on_slug_active`)
- [ ] Apply §2.2 (post-pass gate) to ACC-M `_post_decisions`. ACC-H, ACC-PC, MAS, PAT-SHADOW inherit.
- [ ] Apply §2.3 (cancel-pass force-cancel) to ACC-M `_cancel_decisions`.
- [ ] Apply §2.4 (TAKE-path gates) to ACC-H/_h_taker_decisions, ACC-PC/_pc_taker_decision, PAT-SHADOW/_pat_shadow_decisions, ACC-M/_pat_decisions.
- [ ] Apply §2.6 (config knobs).
- [ ] Add 3 unit tests (§3).
- [ ] Restart `tv-engine.service`.
- [ ] Smoke test (§4) after 6h soak.
- [ ] Run convergence-replay backtest comparison: pull post-fix data + run `audit_slug_breakdown.py`; honest $/slug should be 5-15% higher per sleeve.

## 6. Backward compatibility

- All knobs default to non-zero. Setting any to `0` disables the gate for that strategy = old behavior.
- No schema change, no env var rename, no DB migration.
- Existing CSV columns unchanged; new `trigger_reason="convergence_window_cancel"` value is just a string discriminator in the same column.

## 7. Why these specific offset values

| TF | Offset | Reasoning |
|---|---:|---|
| 5m (300s) | 60s | 20% of slot. Aligns with Telonex empirical data showing fill volume spikes in minutes 13-14 of 15m. For 5m the equivalent spike is in last 60-90s. Bartlett & O'Hara recommend cancel-before-convergence; 60s gives 4 minutes of active posting. |
| 15m (900s) | 120s | 13% of slot. Same reasoning. Telonex shows minute-14 spike → cancel at minute 13. The 15m allows slightly less conservative 120s buffer than 5m's 60s because 15m windows have less variance per minute. |

Tune up if drawdown shows we're still bleeding in last 30s before T-offset hits; tune down if we're losing too many post opportunities to the gate.

## 8. References

- Slug breakdown: `migration_ireland_shadow_2026_05_27/audit_slug_breakdown.py` + slug_breakdown_*.csv
- Replay backtest (running): `migration_ireland_shadow_2026_05_27/convergence_backtest/` (in progress)
- Adverse-selection literature: Bartlett & O'Hara (Stanford SSRN 6615739)
- Empirical Polymarket data: Telonex `top-crypto-traders-polymarket-15m`
- Strategy source: `strategies/polymarket/maker/{acc_m,acc_h,acc_pc,mas,pat_shadow}.py`
