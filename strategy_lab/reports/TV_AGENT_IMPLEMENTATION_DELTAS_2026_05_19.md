# TV Agent — Implementation Deltas (2026-05-19)

**Purpose**: Specific changes TV agent must apply to in-progress or planned strategy implementations.
**Scope**: Updates the 2026-05-18 handoff with backtest-validated revisions.
**Hand this to TV agent**: yes, this is the authoritative change-list.

---

## TL;DR

3 changes to existing strategies + 2 new strategies (shadow-only first):

| Change | Status | Effort |
|---|---|---|
| **ACC-M**: POST_SIZE 5 → 20 | Modify | 1 hour |
| **ACC-M**: add PAT overlay (PAT+ACC-M HYBRID) | Add | +4 hours |
| **MAS**: reduce 6 cells → 2 cells | Modify | 1 hour |
| **ACC-H**: switch from live target to shadow-only | Modify | 2 hours |
| **NEW: ACC-PC** (pair-completion taker) | New strategy | 6 hours |
| **NEW: PAT shadow** (pure pair-arb taker, research-only) | New strategy | 4 hours |

Total dev work: **~18 hours = 2-3 days** on top of existing infrastructure work.

**Sizing recommendation**: drop the $100/strategy cap. Optimal sizing varies per strategy.

---

## 1. Capital allocation (revised, no fixed $100 cap)

Different strategies have different optimal sizing. Forcing $100 each is suboptimal.

| Strategy | Backtest PnL/slug | Recommended wallet | Why this size |
|---|---|---|---|
| **PAT+ACC-M HYBRID** | **+$1.98** | $150-200 | sz=20 needs $20/slug × 3 concurrent = $60 working + buffer |
| **ACC-PC** (with PC taker) | +$0.30-0.50 | $100 | sz=20 + occasional PC takes = $40-60 working |
| **MAS REV** | +$0.09 | $80 | $30 pre-mint × 2 cells = $60 active + buffer |
| **ACC-H SHADOW** | n/a (sim only) | $0 | no live capital |
| **TOTAL LIVE** | | **$330-380** | |

Recommended starting deployment: **$200 on PAT+ACC-M HYBRID only**. Validate for 7 days. Add others if profitable.

This is **lower risk** than the original $200 split across 3 strategies because we're concentrating on the validated winner.

---

## 2. ACC-M REV → PAT+ACC-M HYBRID (the BIG change)

Two changes to the existing ACC-M spec:

### 2.1 Size up (already documented in ACC-M REV)

```python
# OLD (v1 spec from 2026-05-18)
POST_SIZE = 5
ABSOLUTE_MAX_INVENTORY = 50
wallet_seed_usdc = 50

# NEW (REV)
POST_SIZE = 20            # +4x size — validated +$1.25/slug
ABSOLUTE_MAX_INVENTORY = 100
MAX_IMBALANCE_SHARES = 10  # was 5 — looser for sz=20
wallet_seed_usdc = 150     # was $50 — supports POST_SIZE=20 budget
MAX_CONCURRENT_SLUGS = 3   # was 4 — narrower for capital efficiency
```

### 2.2 Add PAT overlay (NEW — replaces ACC-PC as primary upgrade)

```python
# ADD to ACC-M REV
enable_pat = True              # PAT (Pair-Arb Taker) overlay
pat_take_size = 20             # match POST_SIZE
pat_max_pair_cost = 1.00       # only fire if ask_up + ask_dn + fees < $1.00
pat_min_s_between_fires = 5    # rate limit
pat_max_fires_per_slug = 10    # bounded
pat_min_book_depth_each_side = 5  # need fills available
pat_min_time_after_open_s = 5  # let book stabilize
```

### 2.3 PAT logic (50 lines, added to ACC-M on-tick handler)

```python
def check_pat(ss_up, ss_dn, cfg, ts_us, slot_start_us):
    """Fire when sum_asks + total_fees < pat_max_pair_cost."""
    if not (0 < ss_up.best_ask < 1 and 0 < ss_dn.best_ask < 1):
        return False
    if (ts_us - max(ss_up.last_pat_fire_us, ss_dn.last_pat_fire_us)) < 5_000_000:
        return False
    if ss_up.n_pat_fires >= cfg.pat_max_fires_per_slug:
        return False
    elapsed_s = (ts_us - slot_start_us) / 1_000_000
    if elapsed_s < cfg.pat_min_time_after_open_s:
        return False
    if ss_up.ask_size_at_best < 5 or ss_dn.ask_size_at_best < 5:
        return False
    fee_up = poly_taker_fee_per_share(ss_up.best_ask)
    fee_dn = poly_taker_fee_per_share(ss_dn.best_ask)
    pair_cost = ss_up.best_ask + ss_dn.best_ask + fee_up + fee_dn
    if pair_cost >= cfg.pat_max_pair_cost or pair_cost <= 0:
        return False
    if ss_up.inv >= cfg.absolute_max_inv or ss_dn.inv >= cfg.absolute_max_inv:
        return False
    return True


# On every L25Update (after ACC-M maker logic):
if cfg.enable_pat and check_pat(ss_up, ss_dn, cfg, ts_us, slot_start_us):
    take_size = min(cfg.pat_take_size, ss_up.ask_size_at_best, ss_dn.ask_size_at_best)
    if take_size >= 5:
        ask_up = ss_up.best_ask
        ask_dn = ss_dn.best_ask
        fee_up = take_size * poly_taker_fee_per_share(ask_up)
        fee_dn = take_size * poly_taker_fee_per_share(ask_dn)
        # Submit BOTH MarketBuy orders simultaneously
        emit MarketBuy(slug, "Up", price=ask_up, size=take_size, reason="PAT")
        emit MarketBuy(slug, "Down", price=ask_dn, size=take_size, reason="PAT")
        # Track state
        ss_up.inv += take_size; ss_up.cost_paid += take_size * ask_up; ss_up.taker_fees += fee_up
        ss_dn.inv += take_size; ss_dn.cost_paid += take_size * ask_dn; ss_dn.taker_fees += fee_dn
        ss_up.n_pat_fires += 1; ss_dn.n_pat_fires += 1
        ss_up.last_pat_fire_us = ts_us; ss_dn.last_pat_fire_us = ts_us
        # Immediate merge — paired by construction
        pairs = take_size
        emit MergePositions(slug, pairs)
        ss_up.inv -= pairs; ss_dn.inv -= pairs
        # cash_recovered += pairs * 1.0 (handled by merger callback)
```

### 2.4 New action: simultaneous dual-side MarketBuy

Critical: PAT requires TWO market buys to be submitted near-simultaneously (one Up, one Down) to lock in the arbitrage. If one fires and the other doesn't (e.g., book moves), we have a single-side exposure that's bad.

Suggested implementation:
- TV's `PolymarketClient.market_buy(slug, side, price, size)` — submit two in parallel via asyncio.gather
- On either failure, immediately cancel the other (or accept partial single-side exposure with risk logging)

Engine flow:
```python
async def execute_pat_fire(slug, ask_up, ask_dn, size):
    up_task = asyncio.create_task(client.market_buy(slug, "Up", ask_up, size))
    dn_task = asyncio.create_task(client.market_buy(slug, "Down", ask_dn, size))
    up_result, dn_result = await asyncio.gather(up_task, dn_task, return_exceptions=True)
    if isinstance(up_result, Exception) and isinstance(dn_result, Exception):
        log.error("Both PAT legs failed")
    elif isinstance(up_result, Exception):
        log.warning("Up leg failed, holding Down inventory single-side")
        # state already tracks Down inv; ACC-M maker logic will try to balance via BID
    elif isinstance(dn_result, Exception):
        log.warning("Down leg failed, holding Up inventory single-side")
    else:
        # Both filled — immediate merge
        pairs = min(up_result.filled_size, dn_result.filled_size)
        if pairs >= 1:
            await merger.merge_pairs(slug, pairs)
```

### 2.5 Expected per-slug behavior

- ACC-M maker BIDs: 8-25 fills/slug (same as ACC-M REV)
- PAT taker fires: 0-2 per slug (rare; depends on market dislocation)
- Merge events: 2-5 per slug (from ACC-M) + 0-2 (from PAT)
- Avg PnL: **+$1.98/slug** (validated 87 slugs)

---

## 3. MAS REV — keep as documented

`TV_DEPLOY_SPEC_MAS_REV_2026_05_19.md` stands. Key changes from v1:
- Cells reduced 6 → 2 (btc_5m, btc_15m)
- Wallet $100 → $80 active capital
- Promotion bar relaxed (break-even acceptable for data collection)
- Don't scale pre-mint above $30 (validated harmful at $500)

Expected: +$0.09/slug = $0-5/day. Treat as data collection, not profit engine.

---

## 4. ACC-H SHADOW-ONLY — keep as documented

`TV_DEPLOY_SPEC_ACC_H_SHADOW_2026_05_19.md` stands.

Critical: **ACC-H V3f composite taker LOSES $6.84/slug in 213-slug backtest**. DO NOT deploy live.

Run shadow with per-rule logging for 14 days. If shadow corroborates backtest losses, drop permanently.

---

## 5. ACC-PC — DEMOTE to optional 3rd strategy

The original revision elevated ACC-PC (pair-completion taker, reactive on imbalance) as the primary new strategy. **But PAT+ACC-M HYBRID is strictly better** in our 87-slug test (+$1.98 vs +$0.30-0.50).

**New plan**: ACC-PC is optional 3rd strategy after PAT+ACC-M and MAS validate. Capital: $100 wallet if deployed.

`TV_DEPLOY_SPEC_ACC_PC_2026_05_19.md` spec stands but priority is now **3rd, not 1st**.

---

## 6. PAT shadow — research-only deployment

In addition to PAT+ACC-M HYBRID (live deployment), also run pure-PAT in shadow with relaxed parameters to keep gathering signal data.

```python
PAT_SHADOW_CONFIG = {
    "strategy_code": "PAT-SHADOW",
    "enable_pat": True,
    "pat_take_size": 20,
    "pat_max_pair_cost": 1.02,     # MORE permissive than live PAT+ACC-M ($1.00)
    "pat_min_s_between_fires": 3,  # faster rate for shadow data
    "pat_max_fires_per_slug": 30,  # many fires for stats
    "shadow_mode": True,           # NO LIVE TRADES
    "live_deploy_forbidden": True,
    "log_path": "shadow_pat_{date}.csv",
}
```

The shadow logs every check + would-be fire. After 14 days, analyze:
- Fire rate at different thresholds
- Whether thresholds in [1.00, 1.05] could be profitable if combined with another signal
- Whether thin-book + PAT works in live data (didn't work in backtest)

---

## 7. Revised deployment timeline

### Week 1: PAT+ACC-M HYBRID alone

```
Day 1-2: Port ACC-M REV
Day 3:   Add PAT overlay (cfg.enable_pat=True, code from §2.3)
Day 4:   Implement dual-side MarketBuy (§2.4)
Day 5:   Shadow deploy
Day 6:   48h shadow validation
Day 7:   PROMOTE TO LIVE at $200 wallet (was $100 — bigger because better Sharpe)
```

### Week 2: Add MAS REV

```
Day 8-10: Port MAS REV (2 cells, $80 wallet)
Day 11:   Shadow deploy
Day 12:   48h validation
Day 13:   PROMOTE TO LIVE (parallel to PAT+ACC-M)
```

Total live capital: $280.

### Week 3: Add ACC-PC + ACC-H shadow + PAT shadow

```
Day 14-15: Port ACC-PC
Day 16:    Shadow deploy ACC-PC on BTC 15m
Day 17:    Port ACC-H V3f as SHADOW-ONLY (with per-rule logging)
Day 18:    Port PAT-SHADOW (more permissive thresholds)
Day 19:    Shadow validation across all 3 new
Day 20-21: Promote ACC-PC to LIVE if shadow PnL > $0 ($100 wallet)
```

Total live capital: $380. Plus ACC-H and PAT shadow logging.

### Week 4: Validation + selective scale-up

```
Day 22-28: Daily PnL monitoring
  - PAT+ACC-M HYBRID: target $20-50/day live
  - MAS REV: target $0-5/day
  - ACC-PC: target $5-15/day (if deployed)
  - ACC-H shadow: decide drop/refine
  - PAT shadow: identify if any threshold beats live PAT+ACC-M

Day 28: Decision point — scale winners 2x?
```

---

## 8. Total system overview

| Strategy | Code | Mode | Wallet | Cells | Avg PnL/slug | Daily target |
|---|---|---|---|---|---|---|
| **PAT+ACC-M HYBRID** | new | LIVE | $200 | BTC 5m | +$1.98 | $20-50 |
| **MAS REV** | mod | LIVE | $80 | BTC 5m + 15m | +$0.09 | $0-5 |
| **ACC-PC** | new | LIVE wk3 | $100 | BTC 15m | +$0.30-0.50 | $5-15 |
| **ACC-H SHADOW** | mod | shadow | $0 | logs | -$6.84 sim | research |
| **PAT SHADOW** | new | shadow | $0 | logs | varies | research |
| **TOTAL** | | | **$380** | | | **$25-70/day** |

---

## 9. The 4 changes the TV agent must make (in order)

1. **Resize ACC-M**: POST_SIZE 5 → 20, supporting infra (queue tracking, inventory cap). Already documented in `TV_DEPLOY_SPEC_ACC_M_REV_2026_05_19.md`.

2. **Add PAT overlay to ACC-M**: ~50 lines of code + dual-side MarketBuy capability + immediate merge after dual fill. See §2 here.

3. **Reduce MAS to 2 cells**: simple config change. Documented in `TV_DEPLOY_SPEC_MAS_REV_2026_05_19.md`.

4. **Lock ACC-H to shadow**: add `live_deploy_forbidden = True` flag, add per-rule decision logging. See `TV_DEPLOY_SPEC_ACC_H_SHADOW_2026_05_19.md`.

---

## 10. Why drop the $100/strategy cap?

Original plan: $100 max per strategy = $300 across 3 strategies, equal allocation.

Why this was wrong:
- Strategies have wildly different expected returns ($0.09 vs $1.98/slug)
- Equal capital across them is suboptimal
- Better to concentrate capital on validated winners

Revised allocation respects per-strategy capital efficiency:
- PAT+ACC-M HYBRID: $200 (concentrate on winner)
- MAS REV: $80 (small, just for data + diversification)
- ACC-PC: $100 (added later, if PAT+ACC-M validates)

Total: $380 if all 3 deployed, $200-280 if starting with first 2.

If you want STRICTLY $100 cap per strategy, deploy PAT+ACC-M HYBRID at $100 and skip the others initially. Expected PnL: $10-25/day on $100. Still positive expected value.

---

## 11. What stays the same as 2026-05-18 handoff

Everything infrastructure-related:
- Ireland VPS, BookMirror, PolymarketClient
- Performance requirements P1-P10
- Allowance preflight, live_gate
- NegRiskAdapter merger
- CTF splitter (for MAS only)
- Cancel rules (3¢ / 20s)
- CLOB minimum (5 shares)
- Operating hours: 24/7

---

## 12. What's NOT in this delta document

- Directional MAS (0x89b5cdaa pattern, $248/slug) — needs signal we don't have. **Defer.**
- Slug-selection signal (engagement filtering) — research stage. **Defer.**
- Multi-asset (ETH, SOL) — start with BTC, validate, then expand. **Phase 2.**
- 4PM-ET daily markets — only 5m/15m for now.

---

## Bottom line

**The original handoff is 70% correct, 20% needs tuning, 10% should be dropped:**

- ✅ Infrastructure plan: unchanged
- ✅ Performance requirements: unchanged
- ✅ Cancel/merge/spread rules: unchanged
- 🟡 ACC-M: resize 5→20 AND add PAT overlay (PAT+ACC-M HYBRID)
- 🟡 MAS: scope to 2 cells
- 🔴 ACC-H: shadow-only, not live
- 🆕 ACC-PC: optional 3rd, defer
- 🆕 PAT shadow: research-only

**Hand TV agent this document + the 4 REV spec files.** They'll have everything needed.

---

*Companion documents:*
- `STRATEGY_REVISION_2026_05_19.md` — master revision rationale
- `OVERNIGHT_WALLET_VS_BACKTEST_2026_05_19.md` — 213-slug validation data
- `PAT_FINDINGS_2026_05_19.md` — PAT-specific findings (87 slugs)
- `TV_DEPLOY_SPEC_ACC_M_REV_2026_05_19.md` — ACC-M REV details (add PAT per §2)
- `TV_DEPLOY_SPEC_MAS_REV_2026_05_19.md` — MAS REV details
- `TV_DEPLOY_SPEC_ACC_H_SHADOW_2026_05_19.md` — ACC-H shadow-only spec
- `TV_DEPLOY_SPEC_ACC_PC_2026_05_19.md` — ACC-PC spec (now 3rd priority)
