# TV Agent Deploy Spec — ACC-H SHADOW-ONLY (research deployment)

**Version**: 2.0 (replaces TV_DEPLOY_SPEC_ACC_H_2026_05_18.md)
**Date**: 2026-05-19
**Mode**: **SHADOW ONLY** — no live capital allocation
**Capital**: $0 USDC.e (shadow simulation only)
**Reason for shadow-only**: 213-slug backtest showed **-$6.84/slug avg**. Don't burn live capital until live shadow corroborates or refutes.

---

## 0. Why this revision exists

The original ACC-H spec (v1) committed $50 to a live deployment claiming "$50-150/day expected". Our 213-slug backtest with fee-accurate simulation shows ACC-H **LOSES $6.84/slug on average across 4 reference wallets**:

| Wallet | ACC-H PnL/slug | ACC-M PnL/slug | Diff |
|---|---|---|---|
| `0x04b6d7e9` | -$6.58 | +$1.04 | -$7.62 |
| `0xce25e214` | -$7.85 | +$0.35 | -$8.20 |
| `0xeebde7a0` | -$5.93 | +$0.42 | -$6.35 |
| `0xcfb103c3` | -$6.58 | +$0.51 | -$7.09 |
| `0x89b5cdaa` | -$7.24 | -$0.45 | -$6.79 |
| **Average** | **-$6.84** | +$0.37 | **-$7.21** |

The V3f composite taker is consistently HARMFUL across all 5 wallets in our test set.

**Hypothesis options for why**:
1. **Taker fees overwhelm signal**: 7% taker fee × frequent fires drains profit faster than 1.37× lift gains it
2. **Decoded thresholds stale**: V3f rules were tuned to historical book state that no longer holds
3. **Wrong fee model in original decode**: pickup may have used legacy 2% fee, real 7%-on-share blows up the math
4. **Inventory cap creates bad fills**: rules can fire when our maker side is already loaded, creating bad-side exposure

Don't commit live capital until we can attribute which hypothesis is correct.

---

## 1. What this spec covers

A **shadow-only deployment** of ACC-H V3f with **per-rule decision logging**. No orders submitted. Just logs of "what would have happened if we fired".

After 14 days of shadow data, we'll have enough samples to:
- Compute per-rule PnL contribution (which of A/B/C/D actually pay off?)
- Compare to backtest predictions
- Decide: revive ACC-H, refine V3f, or drop permanently

---

## 2. State machine (unchanged from v1)

Inherits ACC-M REV state machine. Adds V3f composite taker check on every L25Update.

NO orders are actually submitted in shadow mode — all logged as "would_have_fired".

---

## 3. V3f composite taker (4 rules, unchanged)

```python
def check_v3f_taker(slug, books, state, ts_us, ask_history_60s,
                    trade_prices_5s, buy_vol_60s):
    """Composite trigger — fires on any of 4 rules."""
    actions = []
    for side in ["Up", "Down"]:
        current_ask = books[side].best_ask

        # Pre-checks (same for all rules)
        if state.inv[side] >= cfg.absolute_max_inv:
            log_decision(rule="any", outcome="skip_inv_cap", side=side)
            continue
        if (ts_us - state.last_taker_us[side]) < cfg.h_min_s_between_taker * 1_000_000:
            log_decision(rule="any", outcome="skip_rate_limit", side=side)
            continue
        if state.h_taker_count[side] >= cfg.h_max_taker_per_slug:
            log_decision(rule="any", outcome="skip_per_slug_cap", side=side)
            continue

        # --- Rule A: discount-capture (33% coverage in original decode) ---
        if current_ask < cfg.h_max_taker_price:  # 0.50
            recent = ask_history_60s[side]
            if len(recent) >= 10:
                median_ask = median([a for _, a in recent if a > 0])
                if (median_ask - current_ask) >= cfg.h_min_ask_drop_60s:  # 0.03
                    actions.append(MarketBuy(slug, side, current_ask,
                                              cfg.h_taker_size, reason="A"))
                    log_decision(rule="A", outcome="WOULD_FIRE",
                                  ask=current_ask, median_60s=median_ask)
                    continue

        # --- Rule B: sharp-drop (33% coverage) ---
        recent_trades = trade_prices_5s[side]
        if len(recent_trades) >= 3:
            max_recent = max(p for _, p in recent_trades)
            if (max_recent - current_ask) >= cfg.h_min_trade_drop_5s:  # 0.02
                actions.append(MarketBuy(slug, side, current_ask,
                                          cfg.h_taker_size, reason="B"))
                log_decision(rule="B", outcome="WOULD_FIRE",
                              max_5s=max_recent, current_ask=current_ask)
                continue

        # --- Rule C: early-slot, no prior fill (20% coverage) ---
        offset_s = (ts_us - state.slot_start_us) / 1_000_000
        if 0 <= offset_s <= cfg.h_early_slot_end_s:  # 60s
            has_prior_fill = state.fill_count[side] > 0 or state.h_taker_count[side] > 0
            if not has_prior_fill:
                actions.append(MarketBuy(slug, side, current_ask,
                                          cfg.h_taker_size, reason="C"))
                log_decision(rule="C", outcome="WOULD_FIRE", offset_s=offset_s)
                continue

        # --- Rule D: buy-pressure then dip (+10pp coverage) ---
        buy_vol_total = sum(v for _, v in buy_vol_60s[side])
        if buy_vol_total > cfg.h_buy_vol_threshold_60s:  # 50
            if recent_trades:
                max_5s = max(p for _, p in recent_trades)
                if (max_5s - current_ask) >= 0.001:
                    actions.append(MarketBuy(slug, side, current_ask,
                                              cfg.h_taker_size, reason="D"))
                    log_decision(rule="D", outcome="WOULD_FIRE",
                                  buy_vol_60s=buy_vol_total, dip=max_5s - current_ask)
                    continue

        log_decision(rule="none", outcome="no_trigger", side=side, ask=current_ask)

    return actions
```

---

## 4. Configuration (unchanged from v1, just shadow-locked)

```python
ACC_H_SHADOW_CONFIG = {
    # === INHERIT FROM ACC-M REV ===
    "strategy_code": "ACC-H-SHADOW",
    "POST_SIZE": 20,
    # ... (all ACC-M REV params)

    # === V3f COMPOSITE TAKER (unchanged from v1) ===
    "enable_h_taker": True,
    "h_taker_size": 20,
    "h_max_taker_price": 0.50,           # Rule A
    "h_min_ask_drop_60s": 0.03,
    "h_min_trade_drop_5s": 0.02,         # Rule B
    "h_early_slot_end_s": 60,            # Rule C
    "h_buy_vol_threshold_60s": 50,       # Rule D
    "h_min_s_between_taker": 5,
    "h_max_taker_per_slug": 20,

    # === SHADOW-ONLY LOCK ===
    "shadow_mode": True,                 # NEVER set to False until validation
    "live_deploy_forbidden": True,       # explicit safety flag
    "log_per_rule_decisions": True,      # KEY — log every check
    "log_path": "shadow_acc_h_{date}.csv",
}
```

---

## 5. Required shadow logging (per-rule attribution)

CSV columns per decision:
```
ts_us, slug, side, rule_evaluated (A/B/C/D/none),
outcome (WOULD_FIRE/skip_inv_cap/skip_rate_limit/skip_per_slug_cap/no_trigger),
current_ask, median_60s_ask, max_5s_trade, buy_vol_60s, offset_s,
inv_up, inv_dn, our_open_bid,
post_fire_simulated_pnl (computed at slug close)
```

After each slug resolves (chainlink outcome known), retroactively compute:
- For each WOULD_FIRE event: what would the PnL have been if we'd taken at that ask + paid the fee + held to close?
- Sum the simulated PnLs per slug → "ACC-H shadow PnL"

After 14 days:
- Per-rule profitability: which of A/B/C/D had positive cumulative simulated PnL?
- Whole-strategy: did shadow PnL match backtest's -$6.84/slug, or was it different?

---

## 6. Decision matrix after 14 days of shadow data

| Shadow result | Action |
|---|---|
| Confirms backtest (avg -$5 to -$10/slug) | **DROP permanently**. The composite was wrong. |
| Less bad than backtest (avg -$2 to -$5/slug) | **Refine**: keep best 1-2 rules, drop others |
| Surprisingly positive (avg +$0 to +$2/slug) | **Investigate**: identify which rules drove it, deploy as v3.1 |
| Per-rule split mixed (e.g. Rule A +EV, Rule B -EV) | **Single-rule deploy**: ACC-H-A only |

Don't deploy live just because per-slug is "close to zero". Need a clear signal that the taker layer adds positive value.

---

## 7. Why this isn't a waste of effort

Even if ACC-H ends up dropped, the shadow data tells us:
- How often each rule fires (rate limit calibration)
- When the rules cluster (early-slot/sharp-drop correlations)
- What ask/CVD conditions exist on real BTC slugs

This dataset is valuable for designing the next taker variant (which we're calling ACC-PC, see separate spec).

---

## 8. Capital allocation

**$0 live capital.** ACC-H SHADOW logs decisions but submits no orders.

Wallet preflight: not required.
Allowance check: not required.
NegRiskAdapter / minter: not used.

This is pure observation.

---

## 9. Implementation checklist

- [ ] Port V3f composite logic from shadow_engine/strategies/acc_h.py
- [ ] Add per-rule decision logging
- [ ] Add post-resolution PnL simulation
- [ ] Wire to BookMirror + TradeMirror (need trade-tape for rules B+D)
- [ ] Implement rolling ask_history_60s, trade_prices_5s, buy_vol_60s
- [ ] Hard-code `live_deploy_forbidden = True` (engine-level safety)
- [ ] Daily summary report: rules fired, simulated PnL, comparison to backtest

---

## 10. Timeline

- Days 1-3: TV agent implements
- Days 4-17: 14 days shadow data collection
- Day 18: review per-rule PnL
- Day 19: decision (drop / refine / revive)

---

## 11. What if we just dropped ACC-H entirely?

Acceptable. We have ACC-M REV (validated +$1.25/slug) and ACC-PC (theoretical +$0.30-0.50/slug). Together they cover the maker-bid edge plus pair-completion variance reduction.

The reason to run shadow is **research value**: ACC-H was decoded from a $6k/day reference wallet (Bonereaper). Our V3f doesn't replicate them, but understanding WHY (via per-rule attribution) might lead us to a better taker variant.

If you want to skip ACC-H shadow entirely and focus capital on ACC-M REV + ACC-PC + MAS REV, that's a defensible choice. The user-facing instruction would be: **drop ACC-H from the deployment plan entirely**.

---

## 12. The big picture

The user's question was: "are our 3 strategies wrong?"

**ACC-M**: right strategy, wrong size — fixed in REV spec
**MAS**: right strategy, undersized — kept small in REV spec
**ACC-H**: maybe wrong strategy — needs 14d shadow to confirm

Decision: keep ACC-H SHADOW for research; don't allocate live capital. If 14d shadow confirms backtest, drop it permanently.

---

*See `STRATEGY_REVISION_2026_05_19.md` for the full strategy revision context and `TV_DEPLOY_SPEC_ACC_PC_2026_05_19.md` for the better-designed taker variant.*
