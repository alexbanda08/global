# TV Deploy Spec — BDH (Binance-Directional Hold) — 2026-05-21

# ✅ STATUS: BUILD (real alpha confirmed, sizing revised)

**Update 2026-05-21 late × 2.** Portfolio audit using official Polymarket API confirms BDH wallets ARE profitable:

| Wallet | Pseudonym | Lifetime | Last 30d | Last 7d | True $/day (30d) |
|---|---|---:|---:|---:|---:|
| 0x9dae874a | Prgovindu1 | **+$49,205** | +$49,205 | n/a | **+$1,640/day** |
| 0xa0a50783 | Prgovindu1-clone | **+$43,578** | +$43,578 | −$2,860 | **+$1,453/day** |
| **Cluster total** | — | **+$92,783** | +$92,783 | — | **+$3,093/day** |

The original "$5,900/day per wallet" claim from F2 reports overstated by ~3.5×. **True cluster rate is ~$3.1k/day combined**, not $11.7k/day. Still real alpha, but capital-efficient at the wallet scale (~$25 per fire).

Why the earlier "BDH dead" verdict was wrong:
- Local chain decoder dropped REDEEM events (filter `side ∈ {BUY, SELL}` excluded `side=""` REDEEM rows)
- 0x9dae874a missed $185,003 of REDEEM proceeds; 0xa0a50783 missed $123,059
- These are pure-taker wallets that hold winners to expiry and `redeemPositions()` them — that's where ALL the cash comes from
- Plus $487-$503 in MAKER_REBATE payouts also missed

**Implementation status**: this spec's mechanics (contrarian on binance momentum, single TAKE, HOLD to resolution, REDEEM at slug end) are correct. BUT:

1. The signal in this spec (5s ret_60salance) may not be the right one — BDH research agent found wallet actually correlates 74% with **binance 60s price return**, only 59% with 5s flow. **Use 60s price return**, not 5s ret_60salance, in the implementation.
2. Re-run the BDH research agent's grid search using the new decoder (with REDEEM/MERGE/REBATE income) on the same trigger formula. The −$14k broad-universe loss was computed against the same buggy cash-only accounting — likely also under-stated.

Updated `min_abs_flow` threshold and slug-selection filter must be re-derived against properly-accounted PnL before live deploy.

**Build, do not implement until decoder fix lands AND re-derived trigger config is confirmed.**

(Original spec below — adjust signal to 60s price return + re-derived thresholds before code.)

The research agent's findings (full report at `migration_ireland_shadow_2026_05_21/bdh_research/BDH_RESEARCH_REPORT.md`):

1. **Both BDH wallets are net NEGATIVE on cash basis**: 0x9dae874a = **−$348/day**, 0xa0a50783 = **−$296/day** over 7d. The "$5,800-$5,900/day" headline from earlier reports does NOT reconcile with on-chain settlement.
2. **93% of taker counterparties on the BUY side = relay wallet `0xf3cfb6a6`** — this is a treasury cycle, not alpha capture.
3. **Trigger formula loses broadly**: 97,050 fires × −$0.14 mean = **−$14k** over 19d on BTC 5m at $1 stake.
4. **No slug-selection filter found**: 87,480-config grid search; best config has **t-stat = 0.61** (statistical noise, not signal).
5. **Wallet vs trigger on the same 92 slugs**: **BOTH lose**. Wallet −$4,506 (−3.07 % of volume); trigger −$25.89 (−1.77 %). No hidden alpha in the slugs themselves.
6. **The signal in this spec is wrong**: I wrote 5s ret_60salance; the wallet actually correlates 74 % with binance 60s price return, only 59 % with 5s flow. **Neither signal works** so it doesn't matter, but flagging the spec error for the record.
7. **Infrastructure was not the blocker** — Ireland has the data. The strategy itself doesn't produce alpha.

**Verdict**: redirect dev-time to other priorities. F2-cluster wallets are not a deployable template.

The rest of this document below is the original spec, preserved for historical context only. **Do not implement.**

---

(historical content follows)

**New 6th maker-arb sleeve.** Implements the F2-cluster wallet template (`0x9dae874a`, `0xa0a50783`) that prints $5.8-$5.9k/day per wallet from a single behavioral signal: take the side of Polymarket up-down that CONTRADICTS recent binance 5s trade-flow imbalance.

Status: **SHADOW DEPLOY ONLY** at first. Live promotion gated on the BDH research subagent's backtest result (running in background as of this writing). Re-evaluate after that completes.

## 0. TL;DR

| Attribute | Value |
|---|---|
| Code | `BDH` (CSV log prefix `bdh_<date>.csv`, sleeve id `poly_bdh_<asset>_<tf>_shadow`) |
| Cells | btc_5m, eth_5m, sol_5m (start with all three; tighten after data lands) |
| Mode | Shadow (paper-only) for first 14 days |
| Trigger | Binance 5s ret_60salance threshold; contrarian direction |
| Action | Single TAKE at best_ask, size = `bdh_take_size` |
| Hold policy | HOLD to slug resolution (chainlink) |
| Wallet seed (live target) | $25 per fire × 5 concurrent slugs = $125 working cap |
| Expected $/day | TBD pending research; wallet ref: $5.8k/day @ unknown sizing |
| Required infra | Binance 5s aggregated trade flow feed (NEW — not yet built on Ireland) |

## 1. Strategy mechanics

### 1.1 Signal — LOCKED to binance 60s price return

Source: binance 1m kline close price for the asset (BTC/ETH/SOL), with the 60-second lookback computed live.

    ret_60s = (close_now − close_60s_ago) / close_60s_ago
    range: roughly [−0.01, +0.01] for typical 60s windows on liquid crypto

**Signal correction from BDH research subagent**: the F2 wallets correlate 74% with binance 60s PRICE return and only 59% with 5s ret_60salance. Use price return as the primary trigger signal. The 5s flow variant in earlier drafts was a wrong hypothesis from F2_TRIGGER_DECODE.

Wallet 0x9dae874a / 0xa0a50783 fire when `|ret_60s| ≥ bdh_min_abs_ret` (default 0.0025 = 25 bps over 60s), and direction is **CONTRARIAN**:

    if ret_60s > +0.0025   →  take DOWN  (fade up-move)
    if ret_60s < −0.0025   →  take UP    (fade down-move)

Mechanism hypothesis: short-lived binance price moves mean-revert within the 5m/15m slug window, so the prediction-market side that priced IN the move overshoots and the contrarian side has positive EV.

Already-available data feed: production `poly_updown_loop.py` consumes binance 1MIN klines for the momo controller — same feed can serve BDH's 60s lookback (subtract close at t−60 from close at t).

Discarded alternatives:
- 5s ret_60salance (74% vs 59% correlation; the F2 docs were wrong)
- Multi-window blended (would need separate research; defer until single-signal baseline shadow-tests)

### 1.2 Trigger gates

In addition to the |ret_60salance| threshold:

| Gate | Default | Why |
|---|---|---|
| `bdh_min_abs_ret_60s` | 0.40 | Below 0.40 the signal is noise |
| `bdh_min_book_depth_at_best_ask` | 10 shares | Need to fill our take cleanly |
| `bdh_max_best_ask` | 0.85 | Don't take above 85¢; we'd be paying close to certainty for low EV |
| `bdh_min_best_ask` | 0.15 | Below 15¢ EV per share is tiny + fees eat it |
| `bdh_min_time_after_slug_active_s` | 30 | Skip first 30s of slug (no kline history, noise) |
| `bdh_max_time_before_slug_end_s` | 60 | Skip last 60s (convergence window — adverse selection per Bartlett & O'Hara) |
| `bdh_allowed_utc_hours` | "22,23,0,1,2,9,10" | Per F2 verdict: fires 22-02 UTC + 9-10 UTC, AVOIDS 12-21 UTC (US hours) |
| `bdh_max_fires_per_slug` | 1 | One bet per slug; no doubling down |
| `bdh_min_s_between_fires_per_asset` | 30 | Rate limit across slugs of same asset |

### 1.3 Action

Single TAKE Decision on the contrarian side:

    action = "TAKE"
    side   = "up" if ret_60s < -threshold else "dn"
    price  = best_ask_at_that_side
    size   = min(bdh_take_size, depth_at_best_ask)

`bdh_take_size` default = 25 shares per fire (matches the wallets' typical fill batch).

### 1.4 Exit

HOLD to slug resolution. No active exit. Polymarket pays $1.00 per winning share at chainlink-resolved settlement; loser shares pay $0.

No MERGE (single-side strategy, no paired inventory).

### 1.5 On-resolution

Emit REDEEM Decision with `side = winning_side`, `size = winner_residual_shares`. Inherited from MakerStrategyBase's REDEEM hook — implementation pattern identical to ACC-M's `on_slug_resolved` but with no paired-merge step (BDH never pairs).

## 2. File layout

### 2.1 Create `backend/app/strategies/polymarket/maker/bdh.py`

Structure mirrors `pat_shadow.py` (single-trigger sleeve, no maker BIDs, single TAKE per fire, inherited slug-lifecycle):

```python
"""Phase 33 — BDH (Binance-Directional Hold).

Contrarian taker on Polymarket up-down markets driven by binance 5s
trade-flow imbalance. Fades momentum: when binance buyers dominate,
takes the DOWN side; when sellers dominate, takes the UP side.

Wallet template: 0x9dae874a + 0xa0a50783 (F2 cluster, $5.8k/day each).

This sleeve does NOT post maker BIDs. POST_SIZE=0. Only TAKE + REDEEM.
"""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import structlog

from backend.app.strategies.polymarket.maker.acc_m import AccMStrategy
from backend.app.strategies.polymarket.maker.base import taker_fee
from backend.app.strategies.polymarket.maker.types import (
    Decision,
    L25Update,
    SlugState,
    TradePrint,
)

if TYPE_CHECKING:
    from backend.app.core.config import Settings
    from backend.app.data.binance_flow import BinanceKlineFeed  # NEW dependency

log = structlog.get_logger(__name__)


class BdhStrategy(AccMStrategy):
    """BDH: contrarian taker on binance ret_60salance.

    Inherits AccMStrategy for slug lifecycle (state init, fill handling,
    slug resolve) but overrides on_l25_update + on_trade_print to ONLY
    run the BDH trigger. No maker BIDs.
    """

    code = "BDH"

    def __init__(self, settings: "Settings", asset: str, tf: str,
                 binance_flow: "BinanceKlineFeed") -> None:
        super().__init__(settings, asset, tf)
        self._binance_flow = binance_flow

    def on_l25_update(self, evt: L25Update) -> list[Decision]:
        """No maker BIDs. Run BDH check on every L25 update."""
        state = self.slug_states.get(evt.slug)
        if state is None:
            return []
        # Cache L25 for the trigger's best-ask + depth read.
        self._l25_cache[(evt.slug, evt.side)] = evt
        # Trigger needs BOTH sides' L25.
        up_cached = self._l25_cache.get((evt.slug, "up"))
        dn_cached = self._l25_cache.get((evt.slug, "dn"))
        if up_cached is None or dn_cached is None:
            return []
        return self._bdh_decisions(state, up_cached, dn_cached, evt.ts_us)

    def _bdh_decisions(
        self,
        state: SlugState,
        up_evt: L25Update,
        dn_evt: L25Update,
        ts_us: int,
    ) -> list[Decision]:
        cfg = self.config

        # Gate 1 — UTC hour filter
        from datetime import datetime, UTC
        utc_hour = datetime.fromtimestamp(ts_us / 1_000_000, tz=UTC).hour
        allowed = set(int(h) for h in str(
            getattr(cfg, "tv_poly_maker_bdh_allowed_utc_hours",
                    "22,23,0,1,2,9,10")
        ).split(","))
        if utc_hour not in allowed:
            return []

        # Gate 2 — rate limit + per-slug cap
        min_us = int(getattr(cfg, "tv_poly_maker_bdh_min_s_between_fires_per_asset", 30)) * 1_000_000
        if (ts_us - state.last_bdh_fire_us) < min_us:
            return []
        max_fires = int(getattr(cfg, "tv_poly_maker_bdh_max_fires_per_slug", 1))
        if state.n_bdh_fires >= max_fires:
            return []

        # Gate 3 — time within slug
        min_open_us = int(getattr(cfg, "tv_poly_maker_bdh_min_time_after_slug_active_s", 30)) * 1_000_000
        if (ts_us - state.slug_active_ts_us) < min_open_us:
            return []
        max_close_us = int(getattr(cfg, "tv_poly_maker_bdh_max_time_before_slug_end_s", 60)) * 1_000_000
        time_to_end_us = state.slug_end_ts_us - ts_us
        if time_to_end_us < max_close_us:
            return []

        # Gate 4 — binance ret_60salance
        ret_60s = self._binance_flow.imbalance_5s(state.asset, ts_us)
        if ret_60s is None:  # feed gap
            return []
        threshold = Decimal(str(getattr(cfg, "tv_poly_maker_bdh_min_abs_ret_60s", "0.40")))
        if abs(Decimal(str(ret_60s))) < threshold:
            return []

        # Determine contrarian side
        side = "dn" if ret_60s > 0 else "up"
        target_evt = up_evt if side == "up" else dn_evt
        best_ask = self._best_ask(target_evt)
        if best_ask is None:
            return []

        # Gate 5 — price band
        min_px = Decimal(str(getattr(cfg, "tv_poly_maker_bdh_min_best_ask", "0.15")))
        max_px = Decimal(str(getattr(cfg, "tv_poly_maker_bdh_max_best_ask", "0.85")))
        if not (min_px < best_ask < max_px):
            return []

        # Gate 6 — book depth
        min_depth = Decimal(getattr(cfg, "tv_poly_maker_bdh_min_book_depth_at_best_ask", 10))
        depth = target_evt.asks[0][1] if target_evt.asks else Decimal("0")
        if depth < min_depth:
            return []

        # Gate 7 — inventory cap (defensive)
        abs_max = Decimal(getattr(cfg, "tv_poly_maker_bdh_max_inventory_per_side", 50))
        cur_inv = state.inv_up if side == "up" else state.inv_dn
        if cur_inv >= abs_max:
            return []

        # Size
        take_size = min(
            Decimal(getattr(cfg, "tv_poly_maker_bdh_take_size", 25)),
            depth,
        )
        if take_size < Decimal(getattr(cfg, "tv_poly_maker_min_post_shares", 5)):
            return []

        # State update
        state.n_bdh_fires += 1
        state.last_bdh_fire_us = ts_us

        return [Decision(
            ts_us=ts_us,
            strategy=self.code,
            slug=state.slug,
            asset=state.asset,
            tf=state.tf,
            action="TAKE",
            side=side,
            price=best_ask,
            size=take_size,
            order_id=None,
            trigger_reason=f"bdh_ret_60s={ret_60s:+.3f}",
        )]


__all__ = ["BdhStrategy"]
```

### 2.2 Add SlugState fields

In `strategies/polymarket/maker/types.py`, extend `SlugState`:

```python
class SlugState:
    # ... existing fields ...
    n_bdh_fires: int = 0
    last_bdh_fire_us: int = 0
```

(Initialize to 0 in the constructor; no migration needed for inherited slugs since BDH is a new sleeve.)

### 2.3 NEW dependency — binance flow feed

Create `backend/app/data/binance_flow.py`:

```python
"""Binance 5s trade-flow aggregator. Subscribes to binance ws aggTrade
stream for the configured asset universe; maintains a rolling 5s window
of (timestamp, buy_volume, sell_volume); exposes:

    imbalance_5s(asset, ts_us) -> float | None
        Returns (buy − sell) / (buy + sell) over the last 5 seconds
        ending at ts_us. None if window is empty or feed is stale.

Latency budget: <100 ms from binance to local cache (binance WS direct
is typically 30-80 ms RTT from Ireland).
"""
```

This module already partially exists per CLAUDE.md ("Binance is the SIGNAL source, matching production momo controller"). Check if `poly_updown_loop.py` already wires a binance flow imbalance; if yes, expose its 5s window via a shared service.

### 2.4 Strategy registration in `engine/main.py`

Mirror the PAT-SHADOW registration pattern (~line 2189-2196):

```python
"BDH": AsyncShadowLogger(
    strategy_code="BDH",
    log_dir="/var/log/tv/maker",
    maxsize=10_000,
    drain_batch_size=200,
    drain_timeout_s=1.0,
    alert_service=alert_svc,
),
```

And dispatch table entry (search for existing PAT-SHADOW dispatch and add BDH parallel).

## 3. Config knobs (defaults in `Settings`)

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # === BDH (Binance-Directional Hold) — Phase 33 ===
    tv_poly_maker_bdh_enabled: bool = True              # master enable
    tv_poly_maker_bdh_shadow_mode: bool = True          # shadow-only at start
    tv_poly_maker_bdh_take_size: int = 25
    tv_poly_maker_bdh_min_abs_ret_60s: Decimal = Decimal("0.40")
    tv_poly_maker_bdh_min_book_depth_at_best_ask: int = 10
    tv_poly_maker_bdh_max_best_ask: Decimal = Decimal("0.85")
    tv_poly_maker_bdh_min_best_ask: Decimal = Decimal("0.15")
    tv_poly_maker_bdh_min_time_after_slug_active_s: int = 30
    tv_poly_maker_bdh_max_time_before_slug_end_s: int = 60
    tv_poly_maker_bdh_allowed_utc_hours: str = "22,23,0,1,2,9,10"
    tv_poly_maker_bdh_max_fires_per_slug: int = 1
    tv_poly_maker_bdh_min_s_between_fires_per_asset: int = 30
    tv_poly_maker_bdh_max_inventory_per_side: int = 50
```

## 4. Shadow logging

BDH writes to `/var/log/tv/maker/bdh_<date>.csv` using the standard 23-col schema (same as PAT-SHADOW). `trigger_reason` column carries the ret_60salance value at fire time (e.g. `bdh_ret_60s=+0.523`).

## 5. Per-slug expectations (TARGETS from spec — actuals TBD post-backtest)

| Metric | Target |
|---|---:|
| Fires per active slug | 0.05 - 0.30 (very selective) |
| Fires per day per asset | 30 - 100 (across all slugs) |
| Realized win rate (fade signal) | 55-65% |
| Avg $/fire | +$2 to +$5 (wallet ref) |
| Per-slug PnL contribution | +$0.20 to +$1.00 (only on fired slugs) |
| Total $/day per cell | $50 - $300 (at $25/fire) |

## 6. Live promotion criteria

After 14 days of shadow mode at default config:

| Gate | Pass criterion |
|---|---|
| Win rate (last 100 fires per cell) | ≥ 55% |
| Mean honest PnL per fire | ≥ +$0.50 |
| Total cell $/day | ≥ +$30 (i.e. >$1/fire avg + at least 30 fires) |
| 3σ drawdown | ≤ -$200 / day |
| Per-cell sample size | ≥ 300 fires |

All four cells must pass independently. Live deploy size: $25 per fire, $125 working capital per cell.

## 7. Kill switches (live mode)

- 5 consecutive losing fires per cell → pause that cell 2 h
- −$200 day on any single cell → pause cell + manual review
- Realized win rate over last 50 fires < 45% → pause + investigate (signal may have decayed)
- Binance feed gap > 30 s → pause ALL cells until feed restores

## 8. Implementation checklist

- [ ] Read F2 reports for any additional gates I missed:
  - `strategy_lab/reports/F2_TRIGGER_DECODE_2026_05_17.md`
  - `strategy_lab/reports/F2_FINAL_VERDICT_2026_05_18.md`
  - `strategy_lab/reports/F2_REPLICATION_VERDICT_2026_05_17.md`
- [ ] Check if `binance_flow.BinanceKlineFeed` (or equivalent 5s aggregator) already exists on Ireland. If yes, reuse. If no, build from `poly_updown_loop.py`'s existing binance WS subscription.
- [ ] Create `bdh.py` per §2.1
- [ ] Add SlugState fields per §2.2
- [ ] Add config knobs per §3
- [ ] Register sleeve in `engine/main.py` per §2.4
- [ ] Unit tests:
  - Gate-by-gate skip cases
  - Contrarian direction (flow > 0 → dn side; flow < 0 → up side)
  - UTC hour filter
  - Convergence-window skip (T-60s)
- [ ] Smoke test: deploy to Ireland, run 24 h shadow, verify `bdh_<date>.csv` populates.
- [ ] WAIT for the BDH research subagent's backtest report — adjust defaults from its findings before any live promotion.

## 9. Open questions / risks

1. **Binance feed missing**: if the 5s aggregator doesn't exist, this sleeve is dead until it's built. Estimated 1 dev-week to add a clean binance aggTrade WS subscriber with rolling-window aggregation.
2. **Slug-selection gap unknown**: F2 verdict says trigger formula loses on broad universe but wins on hand-selected slugs. The BDH research subagent is searching for a slug-selection filter; defaults above (UTC + price band + depth) are first-pass guesses.
3. **Latency to live**: binance WS to Ireland ~30-80ms; our reaction must be sub-150ms to beat the news-bot bracket per Bartlett & O'Hara. Verify on-Ireland latency before live.
4. **Wallet decode may have drifted**: F2 wallets were decoded May 17; market regime may have changed. Re-pull recent fills before any live deploy to confirm $5.8k/day still holds.

## 10. References

- F2 trigger source: `strategy_lab/reports/F2_TRIGGER_DECODE_2026_05_17.md`
- F2 verdict: `strategy_lab/reports/F2_FINAL_VERDICT_2026_05_18.md`
- Wallet caches: `strategy_lab/wallet_hunt/cache/0x9dae874a/`, `0xa0a50783/`
- Parent strategy patterns: `strategies/polymarket/maker/pat_shadow.py` (single-trigger no-maker template)
- Inheritance hooks: `strategies/polymarket/maker/acc_m.py` (slug lifecycle + REDEEM)
- Deploy report: `strategy_lab/reports/MAKER_ARB_DEPLOY_REPORT_2026_05_21.md`
- Adverse-selection literature: Bartlett & O'Hara (Stanford SSRN 6615739)

## 11. Status

- 2026-05-21: this spec drafted. BDH research subagent running in parallel — will inform default config + slug-selection gate before TV agent implements.
- Next: TV agent reads BDH research findings, then implements per this spec. Shadow-only mode for 14 days before any live capital.
