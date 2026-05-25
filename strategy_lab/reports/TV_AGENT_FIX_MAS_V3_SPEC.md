# TV Agent Fix Spec — MAS V3 (UTC hour filter + min_sum_asks gate)

**Scope**: turn the currently-bleeding MAS sleeve (-$0.41/slug honest) into either a small +$ or a controlled flat. Cheap fixes only — no architecture rework.

**Severity**: MEDIUM. Files touched: 2 (`mas.py` + config). Lines changed: ~30. Estimated effort: 2 dev-hours + smoke test.

## 1. Why this matters

MAS is currently the only mint-and-sell sleeve in the suite. Per yesterday's per-slug audit:

| metric | value |
|---|---:|
| Slugs (post-patch sleeve) | 235 |
| Honest PnL | −$95.43 |
| Honest $/slug | **−$0.41** |
| 0-fill slugs (riskless mint+redeem) | 88 (37%) |
| Partial-fill, unfilled-side-loser | 142 (60%) → mean +$2.50/slug |
| Partial-fill, sold-winner-side | 90 (38%) → mean **−$4.52/slug** |

The strategy IS earning on the favorable partial fills (+$2.50/slug). It loses **only** because the sold-winner-side cases cost more than the wins cover. Two cheap fixes deal with most of the bleed.

## 2. Cause #1 — Time-of-day pattern

The agent's per-hour decomposition shows a sharp split:

| UTC hour | $/slug |
|---|---:|
| 04-12 | +$1 to +$3 |
| 14-21 | **−$2 to −$4** (the bleed) |
| 22-03 | ≈ flat |

US market hours (12-21 UTC) carry directional flow that selects against MAS's symmetric ASK placement. Skipping those hours alone halves the bleed.

## 3. Cause #2 — Missing `min_sum_asks` selectivity gate

Current MAS posts ASKs on every L25 update where inventory exists, regardless of book edge. The V3 design (from `MINT_AND_SELL_V3_PROFITABLE_2026_05_18.md`) requires `sum_asks ≥ 1.005` before posting — i.e., only post when the market is willing to pay >$1 for both sides combined.

Without this gate, MAS posts into markets where the ASK premium has already been absorbed. The book then crosses into us at a price too close to fair, killing the half-cent of edge.

## 4. Edits

### 4.1 Edit MAS-V3.A — `mas.py` (NEW config knobs)

Add to the strategy's config import block (top of file, near other `getattr(cfg, ...)` calls):

```python
# === MAS-V3 selectivity gates (NEW — TV_AGENT_FIX_MAS_V3_SPEC.md) ===
# UTC hour filter: only post when current UTC hour ∈ allowed set.
# Default: 04-12 UTC (the empirically-profitable window).
MAS_V3_ALLOWED_UTC_HOURS = frozenset(
    int(h) for h in getattr(
        cfg,
        "tv_poly_maker_mas_v3_allowed_utc_hours",
        "4,5,6,7,8,9,10,11,12",
    ).split(",")
)

# Minimum sum_asks (best_ask_up + best_ask_dn) required before posting.
# Below this threshold the market has already absorbed the mint premium.
# Default 1.015 (= 1.5¢ premium-to-fair).
MAS_V3_MIN_SUM_ASKS = Decimal(
    str(getattr(cfg, "tv_poly_maker_mas_v3_min_sum_asks", "1.015"))
)

# Enable / disable V3 gates entirely (kill switch).
MAS_V3_ENABLED = bool(getattr(cfg, "tv_poly_maker_mas_v3_enabled", True))
```

### 4.2 Edit MAS-V3.B — `mas.py` `_post_decisions` (the ASK posting loop)

Find `_post_decisions` (the method that emits POST_ASK Decisions). At the TOP of the method body, BEFORE iterating over sides:

```python
def _post_decisions(self, state: SlugState, ts_us: int) -> list[Decision]:
    # ... existing setup ...

    # V3 selectivity gates — skip posting if either fails.
    if MAS_V3_ENABLED:
        # Gate 1: UTC hour filter.
        from datetime import datetime, UTC
        utc_hour = datetime.fromtimestamp(ts_us / 1_000_000, tz=UTC).hour
        if utc_hour not in MAS_V3_ALLOWED_UTC_HOURS:
            return []

        # Gate 2: min sum_asks.
        up_evt = self._l25_cache.get((state.slug, "up"))
        dn_evt = self._l25_cache.get((state.slug, "dn"))
        if up_evt is None or dn_evt is None:
            return []
        ba_up = self._best_ask(up_evt)
        ba_dn = self._best_ask(dn_evt)
        if ba_up is None or ba_dn is None:
            return []
        sum_asks = ba_up + ba_dn
        if sum_asks < MAS_V3_MIN_SUM_ASKS:
            return []

    # ... existing posting logic continues unchanged ...
```

### 4.3 Edit MAS-V3.C — `core/config.py` Settings

Add to the `Settings` model:

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # === MAS V3 selectivity gates ===
    tv_poly_maker_mas_v3_enabled: bool = True
    tv_poly_maker_mas_v3_allowed_utc_hours: str = "4,5,6,7,8,9,10,11,12"
    tv_poly_maker_mas_v3_min_sum_asks: Decimal = Decimal("1.015")
```

### 4.4 Edit MAS-V3.D — `/etc/tv/tradingvenue.env` (no changes required for default)

Defaults are sane. If operator wants to tune later:

```bash
# Wider UTC window for testing — uncomment to enable.
# TV_POLY_MAKER_MAS_V3_ALLOWED_UTC_HOURS=0,1,2,3,4,5,6,7,8,9,10,11,12,22,23

# Tighter selectivity for live deploy.
# TV_POLY_MAKER_MAS_V3_MIN_SUM_ASKS=1.020

# Kill V3 gates entirely (revert to V1 behavior) — for A/B testing.
# TV_POLY_MAKER_MAS_V3_ENABLED=false
```

## 5. Unit tests

Add to `tests/strategies/test_mas.py`:

```python
def test_v3_skip_post_outside_allowed_hours(mas_strategy_at_hour):
    """When UTC hour ∉ allowed set, _post_decisions returns []."""
    # Set ts_us to 15:00 UTC (= hour 15, not in default 4-12 set).
    ts_us = int(datetime(2026, 5, 21, 15, 0, tzinfo=UTC).timestamp() * 1_000_000)
    decisions = mas_strategy_at_hour._post_decisions(state, ts_us)
    assert decisions == []

def test_v3_post_at_allowed_hour(mas_strategy):
    """When UTC hour ∈ allowed set AND sum_asks ≥ min, posts emit."""
    ts_us = int(datetime(2026, 5, 21, 9, 0, tzinfo=UTC).timestamp() * 1_000_000)
    # Seed L25 with sum_asks = 1.05 (well above 1.015 default).
    seed_l25(mas_strategy, slug, ba_up=0.55, ba_dn=0.50)
    decisions = mas_strategy._post_decisions(state, ts_us)
    assert len(decisions) >= 1  # at least one POST_ASK emitted

def test_v3_skip_post_below_min_sum_asks(mas_strategy):
    """When sum_asks < min, no posts even in allowed hour."""
    ts_us = int(datetime(2026, 5, 21, 9, 0, tzinfo=UTC).timestamp() * 1_000_000)
    seed_l25(mas_strategy, slug, ba_up=0.50, ba_dn=0.50)  # sum = 1.00 < 1.015
    decisions = mas_strategy._post_decisions(state, ts_us)
    assert decisions == []

def test_v3_disabled_falls_back_to_v1(mas_strategy_v3_disabled):
    """When MAS_V3_ENABLED=False, gates are bypassed (V1 behavior)."""
    ts_us = int(datetime(2026, 5, 21, 15, 0, tzinfo=UTC).timestamp() * 1_000_000)
    seed_l25(mas_strategy_v3_disabled, slug, ba_up=0.50, ba_dn=0.50)
    decisions = mas_strategy_v3_disabled._post_decisions(state, ts_us)
    # V1 would post here regardless of hour or sum_asks.
    assert len(decisions) >= 1
```

## 6. Smoke test (after deploy)

After landing F1 (canonical fees) AND MAS-V3 gates AND restarting `tv-engine.service`:

1. Run 24 h shadow at default config (04-12 UTC, min_sum_asks=1.015).
2. Pull `/var/log/tv/maker/mas_<date>.csv`.
3. Verify:
   - **n_MINT events drops** (we mint less often because we skip 12-hour daily window).
   - Surviving slugs have `min(sum_asks) ≥ 1.015` at MINT time.
   - Per-slug honest PnL = `cash_received + cash_recovered − cash_spent − taker_fees + rebates`.
4. Expected outcomes:
   - Total slugs/day: drops from ~235 to ~120 (12/24 hours active).
   - Honest $/slug: **+$0.30 to +$0.80** (from −$0.41 baseline).
   - Total honest $/day: roughly flat to +$60 (smaller window, better selection).
5. If 24h numbers don't show ≥+$0.20/slug honest, the strategy stays broken — proceed to §7.

## 7. Fallback plan if V3 gates don't fix MAS

If 7-day post-fix MAS continues to bleed (mean $/slug < +$0.10 honest), MAS goes on the kill list. Options ranked by effort:

1. **Cheapest** — set `tv_poly_maker_mas_v3_enabled=false` and accept MAS as a research-only sleeve (data collection on rebate income, not profit engine).
2. **Medium** — port MAS to ACC-PC-style architecture: mint, then post ASKs ONLY when one side fills first (i.e. asymmetric mint-and-sell). Treats minted shares like accumulated inventory waiting for the other side to dip. This matches the `0x9dae874a`-class wallet behavior more accurately.
3. **Hardest** — rebuild MAS to V3 spec proper: per-cell tuned `pre_mint` ($50-$100), `post_size=1-2` shares, CVD-asymmetric posting, time-of-day filter (this spec's filter), per-asset+tf threshold. Estimated 1 dev-week.

Don't pursue option 3 unless option 1 + option 2 both fail to break even.

## 8. Rollout checklist

- [ ] F1 (canonical fees) has landed and verified — REQUIRED prerequisite.
- [ ] Apply MAS-V3.A, .B, .C edits.
- [ ] Add the 4 unit tests; pytest passes.
- [ ] Restart `tv-engine.service`.
- [ ] Wait 24 hours.
- [ ] Run §6 smoke test on at least 50 MAS slugs.
- [ ] If $/slug honest ≥ +$0.30 over 7 days: keep V3 gates enabled.
- [ ] If $/slug honest < +$0.10 over 7 days: trigger §7 fallback.

## 9. References

- Root-cause analysis: `migration_ireland_shadow_2026_05_21/mas_loss_decomp.md`
- V3 design source: `strategy_lab/reports/MINT_AND_SELL_V3_PROFITABLE_2026_05_18.md` (note: the "+$1k/day" claim was overturned by `MINT_AND_SELL_V3_SIMULATION_2026_05_23.md`; this fix uses ONLY the selectivity gates from V3, not the full V3 architecture).
- Per-slug audit: `migration_ireland_shadow_2026_05_21/mas_loss_decomp_per_slug.csv`
- Deploy report: `strategy_lab/reports/MAKER_ARB_DEPLOY_REPORT_2026_05_21.md`
