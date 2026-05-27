# Sniper Search Brief V7 — 2026-05-27

V7 round: **"ensembles, 2-leg, cross-asset, deeper extensions"**. Supersedes V6 brief where they conflict.

Read this BEFORE doing V7 work. Refer to V5 brief (`_BRIEF.md`) for gate library + data paths, and V6 brief (`_BRIEF_V6.md`) for V6-introduced gates.

---

## 0. What V6 settled (don't re-explore)

- **Kelly is dead.** Quarter-Kelly clamps to $5 floor on binary markets. Constant $25 wins absolute PnL. Linear-3-bucket only helps on broader funnels (ETH 15m core). V7 default = constant $25.
- **$250 testing dropped.** Drop `g_book_depth_supports_250`, `g_depth_250_strict`.
- **Pre-window ws_s anchor**: outperforms ONLY for ETH 15m (V6 sleeve 08, WR 94.4% vs 84.6%). Other markets failed. V7 may still test pre-window in NEW configurations but not the V6 pattern.
- **Per-market timing**:
  - BTC 5m: late offsets (150-240) won — extend
  - BTC 15m: late offsets (600-840) won, DOWN-dominant — extend
  - ETH 5m: offset 60 won — extend
  - ETH 15m: offset_early + ws_s won — extend
  - SOL 5m: offset 60-150s + f7_rsi universal — extend
  - SOL 15m: offset 60-240s + HOD EU morning won — extend
- **Universal winners across markets**: `g_hurst_trending`, `g_mp_skew_with`, `g_f7_rsi_with` (pre-window), `g_tr_stack_full_with`.

## 1. V7 explore — new dimensions

### Path A — Weighted ensembles (drop "all gates must pass")

Instead of requiring ALL gates to pass for entry, compute a weighted gate sum and fire when sum > threshold:

```python
gate_weights = {
  "g_tr_stack_full_with": 1.5,
  "g_hurst_trending":     1.2,
  "g_mp_skew_with":       1.0,
  "g_ribbon_agrees":      0.8,
  ...
}
gate_sum = sum(weight[g] for g in gates if g.evaluate(direction, fire_us))
if gate_sum >= threshold:
    fire(direction)
```

Weights tuned by training-window WR-lift per gate. Threshold tuned to give n=100-500 lockbox fires. Test on every market.

**Hypothesis**: catches more fires while filtering noise — broader funnel + still selective. May beat strict 4-5 gate stacks.

### Path B — 2-leg straddle sleeves

Enter BOTH UP and DOWN tokens on the same slug at different offsets:
- Buy UP at offset=30 (when book is fresh, vwap=0.50-0.55)
- Buy DOWN at offset=180 (when momentum has shown direction, vwap drift up if Down probable)
- Sum the two PnLs at slot_end

**Hypothesis**: captures volatility/non-direction premium. Works in choppy markets. Already used in classic options strategies.

Alternative: cross-slug straddle (UP on BTC slot + DOWN on ETH slot starting same time).

### Path C — Cross-asset signal triggers

V6 universal `g_f7_rsi_with` was at the SAME asset's ws_s. V7: test **OTHER asset's** features as a trigger:
- BTC microstructure → ETH sleeve fire (BTC microprice change leads ETH by 0-500ms per HL research 2026-05-21)
- BTC trend_slope_30m → SOL fire (SOL beta to BTC is high)
- HL liquidation cascade on asset X → fire asset Y opposite direction (mean-reversion play)

### Path D — Slot-end OFI

For LATE-offset sleeves (BTC 15m winners), evaluate order flow imbalance in the LAST 60s of the slot (`slot_end - 60s` to `slot_end`). If imbalance heavily favors a direction in those final seconds, the chainlink resolution likely follows.

```python
g_slot_end_ofi_with(direction, slot_end_us, slug):
  # Order flow imbalance in final 60s before resolution
  ofi = polymarket_trade_flow_60s_pre_close(slug, slot_end_us - 60_000_000, slot_end_us)
  return sign(ofi) matches direction AND abs(ofi) > threshold
```

**Caveat**: this is LOOKAHEAD if applied at fire_us < slot_end - 60s. Only valid for fires AT slot_end-60s or later. For 15m slots, valid offsets are 840s+.

### Path E — Build offset=0 fires

Current v3 fires don't include offset=0. The earliest is offset=30 (5m) or offset=60 (15m). Build a new mini-universe `oos_fires_{ASSET}_{TF}_offset0_v3.parquet` with offsets {0, 15, 30} for 5m and {0, 30, 60} for 15m. Test if even earlier entry adds vwap improvement (the V6 research showed +$14-17 per won at offset 30 vs 270 — offset 0 might add another $2-4).

### Path F — 15m parent → 5m child confluence

For 5m markets, only fire IF the 15m regime panel (`regime_panel_15m_v2_fixed`) for the same asset shows alignment with direction at the time:
```python
g_parent_15m_regime_with(direction, fire_us, asset):
  parent_label = regime_panel_15m_v2_fixed[asset].regime_label at asof_bar_end(fire_us)
  return (parent_label=="trending_up" and direction=="UP") or
         (parent_label=="trending_dn" and direction=="DOWN")
```

Use as a top-of-stack filter. Should reduce n by 40-60% but lift WR.

### Path G — Volume regime specialization

Split fires into HIGH-VOL vs LOW-VOL regimes using `vol_hurst_at_fire.rv_60` median. Some gate stacks may work in only one regime. Find regime-specialized sleeves.

### Path H — Deeper Hurst variants

V6 used `g_hurst_trending` (hurst > 0.50). V7 test:
- `g_hurst_strong_trending`: hurst > 0.65
- `g_hurst_reverting`: hurst < 0.40
- `g_hurst_regime_with(direction)`: hurst > 0.55 AND price-trend aligned with direction

### Path I — Pre-window combos (deeper than V6's single g_pw_trend_slope)

For ETH 15m specifically (where pre-window worked):
- `g_pw_m1v_with`: Markov M1V state at ws_s
- `g_pw_f7_rsi_extreme`: F7 RSI in extreme zone at ws_s
- `g_pw_xa_unanimity`: all 3 asset RFs agree at ws_s-30s
- Combine 2-3 PW gates in one sleeve

## 2. V7 target profile (kept from V6)

| Metric | Target |
|---|---|
| n / 32d | 30-2000 |
| WR on lockbox | ≥65% (or ≥55% if $/tr ≥ $10) |
| $/tr at $25 stake | ≥$4 |
| Max DD at $25 stake | ≤$500 |
| Max loss streak | ≤14 |
| Bootstrap p (lockbox) | ≤0.05 |
| Sharpe (daily approx) | ≥1.5 |

**Primary objective**: maximize `lockbox_$/tr × sqrt(lockbox_n)` (Sharpe-flavored expected dollar lift), with stability across train/val/lockbox (no negative split $/tr).

## 3. Stake convention

- **Default: constant $25**
- For weighted-ensemble sleeves: linear-bucket stake based on `gate_sum / max_gate_sum` ratio (3 buckets: $5/$15/$25)
- NO Kelly. NO $250.

## 4. Data paths (UNCHANGED from V6)

v3 fires: `data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_{ASSET}_{TF}_full_v3.parquet`

All other feature panels: see V5 brief §5 and V6 brief §6.

## 5. Conventions (UNCHANGED)

- ws_s anchor for pre-window
- `engine_v2.LegacyConfig` (2%-on-profit fee)
- L25 walk fill, spread filter per asset
- chainlink outcome
- bug-fixed `*_v2_fixed` panels

## 6. Output spec

Per agent, write to `strategy_lab/sniper_search_2026_05_27/{market_slug}_v7/`:

1. `top_5_candidates_v7.csv` — columns:
   `sleeve_id, anchor, gate_stack, weights (if weighted), conviction_method, n_train, n_val, n_lockbox, wr_train, wr_val, wr_lockbox, dpt_25_train, dpt_25_val, dpt_25_lockbox, sum_25_28d_const, max_dd_25, loss_streak, sharpe, bootstrap_p_lockbox`

2. `SNIPER_{MARKET}_V7_REPORT.md`:
   - Top 3-5 candidates with full metrics
   - Approach used (which V7 paths A-I tested)
   - Per-path findings (which worked, which didn't)
   - Comparison vs V6 best sleeve for the market
   - Confidence per candidate

3. Cumulative PnL PNGs per top sleeve

4. Code in `scripts/`

### Return to orchestrator (<300 words):
- # candidates meeting V7 profile
- Best candidate gate stack + 28d projection
- Which V7 path was the winner
- Comparison vs V6 best (+/- $)
- Top failure
- Confidence

## 7. What NOT to do (carry-forward)

Same as V6 §10. Plus:
- Don't test Kelly (confirmed loser)
- Don't test $250 (dropped)
- Don't sum sleeve PnL without slug-overlap dedup
- Don't anchor on slot_start (use ws_s OR fire_us-1_000_000)

## 8. Per-market V7 priorities

| Market | V7 explore (paths) |
|---|---|
| BTC 5m | A (weighted), D (slot-end OFI for late), H (hurst variants), F (parent 15m), B (2-leg) |
| ETH 5m | A (weighted), C (BTC→ETH cross-asset), H (hurst), F (parent 15m), I (PW deeper) |
| SOL 5m | A (weighted), C (BTC→SOL cross-asset), H (hurst), G (vol regime), F (parent 15m) |
| BTC 15m | A (weighted), D (slot-end OFI ⭐), H (hurst), G (vol regime), B (2-leg straddle) |
| ETH 15m | A (weighted), I (PW deeper — combine 2-3 PW gates) ⭐, C (BTC→ETH), G (vol regime), H (hurst) |
| SOL 15m | A (weighted), C (cross-asset → SOL ⭐), F (parent — but SOL has no parent), G (vol regime), H (hurst) |
