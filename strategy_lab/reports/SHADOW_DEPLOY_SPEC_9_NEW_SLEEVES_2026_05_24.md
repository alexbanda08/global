# Shadow-deploy spec — 9 new sleeves for VPS3 + 6 production-sleeve filters

_All sleeves run on VPS3 in **shadow mode** (no real orders; PnL recorded against L25 walk-fills + 2 %-on-profit fee). Side-by-side with existing 11 production sleeves. Targets 14-day shadow window to validate vs backtest._

## How `fair_edge_bp` works — clarification

`fair_edge_bp` is a scalar feature computed at fire_us:

```python
sigma   = std(log(close_1s) over last 900 s)          # binance 1s realized vol
tau_s   = (slot_end_us - fire_us) / 1_000_000         # seconds to settlement
strike  = chainlink_rtds_price_at(slot_start_us)
s_now   = binance_close_at(fire_us)
z       = log(s_now / strike) / (sigma * sqrt(tau_s))
fair_up = norm.cdf(z)                                 # P(Up wins | binance random walk)

if direction == "UP":
    fair_edge_bp = (fair_up - entry_vwap)        * 10_000
else:  # DOWN
    fair_edge_bp = ((1 - fair_up) - entry_vwap)  * 10_000
```

Interpretation: "the FV model thinks our bet has +X bp of expected edge over the entry vwap we'd pay on Polymarket." Positive = model thinks +EV, negative = model thinks -EV.

Used two ways:
- **A. As a FIRE rule component** — `fair_edge_bp > 500` (or any threshold) is a sufficient condition for a new sleeve to fire (combined with other conditions).
- **B. As a FILTER on existing production** — production sleeve raises a signal, we add `fair_edge_bp > 500` to gate whether to actually fire.

Same feature, different role.

---

## The 9 new shadow sleeves

Naming convention: `shadow_poly_updown_{asset}_{tf}_{strategy_id}`. All run on the same VPS3 fire-loop infra as production. **None of these exist in current production.**

| # | sleeve_id | asset | tf | trigger | notional | expected $/day @ $25 |
|--:|---|---|---|---|---|--:|
| 1 | `shadow_poly_updown_ALL_5m_phase1_kelly` | BTC+ETH+SOL | 5m | S4 ∪ S8, off ≥ 120 s, Kelly tier | $25-$100 | +$280 base / **+$927 Kelly** |
| 2 | `shadow_poly_updown_btc_5m_fade_momo_v2` | BTC | 5m | momo_v2 fires AND (HOD fails OR M5V fails) | $25 | +$22 |
| 3 | `shadow_poly_updown_btc_5m_fade_sniper` | BTC | 5m | sniper fires AND ungated | $25 | +$18 |
| 4 | `shadow_poly_updown_eth_15m_fade_sniper` | ETH | 15m | sniper fires AND ungated | $25 | +$12 |
| 5 | `shadow_poly_updown_sol_5m_fade_sniper` | SOL | 5m | sniper fires AND ungated | $25 | +$6 |
| 6 | `shadow_poly_updown_sol_5m_fade_momo_v2` | SOL | 5m | momo_v2 fires AND ungated | $25 | +$7 |
| 7 | `shadow_poly_updown_sol_15m_fade_momo_v2` | SOL | 15m | momo_v2 fires AND ungated | $25 | +$6 |
| 8 | `shadow_poly_updown_ALL_5m_S3_prewindow` | BTC+ETH+SOL | 5m | S3 rule at slot_start − 60 s | $25 | +$78 |
| 9 | `shadow_poly_updown_ALL_15m_S4_prewindow` | BTC+ETH+SOL | 15m | S4 rule at slot_start − 120 s | $25 | +$25 |

**Aggregate projected $/day at $25 base** = +$450 (additive on top of existing production).
**Aggregate projected $/day with Kelly on sleeve #1** = **+$1 100**.

### Required features (TV-agent must publish all at fire_us)

| feature | source | window |
|---|---|---|
| `s_now` | binance 1s close | latest @ fire_us |
| `sigma_per_sqrt_sec_15m` | std(log_rets of binance 1s close) | last 900 s |
| `strike` | chainlink RTDS | at slot_start_us |
| `entry_vwap` | L25 ask walk, $25 notional | at fire_us + 85 ms |
| `dev_bps` | `10_000 * log(s_now / vwap_15m_anchored)` | 15m anchored VWAP |
| `vwap_15m_anchored` | 1s-volume-weighted close | 15m bucket |
| `fair_up` | `norm.cdf(z)` formula above | derived |
| `fair_edge_bp` | derived from fair_up + entry_vwap + direction | derived |
| `cvd_30s` | sum(2·taker_buy_quote - quote_volume) on binance 1s | last 30 s |
| `cvd_60s` | same | last 60 s |
| `macd_hist` | MACD(12, 26, 9) on binance 1s close | derived |
| `rvol_30_300` | `vol(last 30 s) / mean_vol(last 300 s)` | derived |
| `m1v_pass`, `m5v_pass` | markov_regime_micro labels match direction | 1m / 5m bars |
| `m1v_regime`, `m5v_regime` | raw regime label (0=BEAR, 1=BULL, -1=unknown) | 1m / 5m bars |
| `imb5` | L25 5-level bid/ask imbalance | at fire_us + 85 ms |

These should already be in the TV-agent feature pipeline as of Phase 18.6+, except for `fair_up`, `fair_edge_bp`, `cvd_30s`, `cvd_60s`, `macd_hist`, `rvol_30_300`, `imb5`, and the `m*_regime` raw labels. Those need to be added.

---

## Per-sleeve detailed spec

### Sleeve #1 — `shadow_poly_updown_ALL_5m_phase1_kelly`

**Headline strategy**: 5m up-down winner ensemble with conviction-weighted Kelly sizing.

```python
def fire_decision_sleeve_1(slot, fire_offset_s, features):
    # Only at offset 120 s into the 5m slot (or higher offsets if you sweep at 120/150/180/210/240/270 s and stop on first match)
    if fire_offset_s < 120:
        return None
    if features.tf != "5m":
        return None

    # Direction = sign of dev_bps
    direction = "UP" if features.dev_bps > 0 else "DOWN"

    # Rule S4: high-conviction fair-value
    S4 = (features.fair_edge_bp > 500
          and features.cvd_agree_30s
          and abs(features.dev_bps) >= 8)
    # Rule S8: short-term momentum + volume
    S8 = (features.macd_agree
          and features.rvol_30_300 > 1.2)

    if not (S4 or S8):
        return None

    # Dedup: fire at FIRST offset ≥ 120 s in the slot. If already fired
    # this slug × direction at an earlier offset, skip.
    if already_fired(slot.slug, direction):
        return None

    # Kelly tier on fair_edge_bp
    if   features.fair_edge_bp > 3000: mult = 4.0
    elif features.fair_edge_bp > 2000: mult = 3.0
    elif features.fair_edge_bp > 1000: mult = 2.0
    else:                              mult = 1.0
    notional_usd = 25.0 * mult

    rule_label = "S4" if S4 else "S8"

    return Fire(
        sleeve_id="shadow_poly_updown_ALL_5m_phase1_kelly",
        slug=slot.slug, asset=slot.asset, tf="5m",
        direction=direction, notional_usd=notional_usd,
        meta={"rule": rule_label, "kelly_mult": mult,
              "fair_edge_bp": features.fair_edge_bp,
              "dev_bps": features.dev_bps,
              "fire_offset_s": fire_offset_s},
    )
```

**Backtest stats (21 d panel)**: n = 3 508, WR = 84.4 %, per-trade = +$5.50, sum = +$19 308 = **+$927/day**, max DD = −$829, walk-forward 2.90×.

**Monitoring KPIs (shadow window 14 d, expected)**:
- Fires per day: ~167 (across BTC/ETH/SOL)
- Avg notional: ~$34
- WR: 82-86 %
- Per-trade: $4-6
- Capacity: 4× tier (~$100 fires) ~6/day — watch L25 fill quality

### Sleeves #2-7 — FADE-UNGATED-MOMO companions

**Pattern**: when production raises a signal but the production HOD-top8 + M5V filter rejects it, FIRE THE OPPOSITE direction at $25.

```python
HOD_TOP8 = {                          # production hour-of-day filter per cell
    "momo_v2_btc_5m": {0, 2, 5, 6, 10, 12, 21, 23},
    "sniper_btc_5m":  {0, 1, 3, 5, 12, 15, 19, 21},
    "sniper_eth_15m": {0, 6, 7, 9, 13, 14, 19, 22},
    "sniper_sol_5m":  {0, 1, 2, 4, 8, 15, 19, 23},
    "momo_v2_sol_5m": {4, 5, 6, 8, 10, 12, 14, 17},
    "momo_v2_sol_15m":{1, 2, 5, 12, 13, 16, 17, 21},
}

FADE_CELLS = {
    "momo_v2_btc_5m":  "shadow_poly_updown_btc_5m_fade_momo_v2",
    "sniper_btc_5m":   "shadow_poly_updown_btc_5m_fade_sniper",
    "sniper_eth_15m":  "shadow_poly_updown_eth_15m_fade_sniper",
    "momo_v2_sol_5m":  "shadow_poly_updown_sol_5m_fade_momo_v2",
    "sniper_sol_5m":   "shadow_poly_updown_sol_5m_fade_sniper",
    "momo_v2_sol_15m": "shadow_poly_updown_sol_15m_fade_momo_v2",
}

def fire_decision_fade(slot, production_signal, features):
    cell_key = f"{production_signal.strategy}_{production_signal.asset.lower()}_{production_signal.tf}"
    sleeve_id = FADE_CELLS.get(cell_key)
    if sleeve_id is None:
        return None  # not a fade-eligible cell

    fire_hour = pd.Timestamp(slot.fire_us, unit='us', tz='UTC').hour
    hod_pass = fire_hour in HOD_TOP8[cell_key]
    m5v_pass = features.m5v_pass

    # FADE only fires when production WOULD HAVE DROPPED the signal.
    if hod_pass and m5v_pass:
        return None  # production fires its standard direction, leave alone

    opposite_dir = "DOWN" if production_signal.direction == "UP" else "UP"
    return Fire(
        sleeve_id=sleeve_id, slug=slot.slug, asset=slot.asset, tf=slot.tf,
        direction=opposite_dir, notional_usd=25.0,
        meta={"original_strategy": production_signal.strategy,
              "original_direction": production_signal.direction,
              "hod_pass": hod_pass, "m5v_pass": m5v_pass,
              "fire_offset_s": (slot.fire_us - slot.slot_start_us) / 1e6},
    )
```

**Per-sleeve specifics:**

| sleeve_id | cell | un-gated n / 21 d | fade WR % | per-tr $ | $/day | max DD |
|---|---|--:|--:|--:|--:|--:|
| `shadow_poly_updown_btc_5m_fade_momo_v2` | momo_v2 BTC 5m | 747 | 51.9 | +$0.86 | +$22 | ~−$200 |
| `shadow_poly_updown_btc_5m_fade_sniper` | sniper BTC 5m | 636 | 53.0 | +$0.80 | +$18 | ~−$180 |
| `shadow_poly_updown_eth_15m_fade_sniper` | sniper ETH 15m | 325 | 52.6 | +$1.02 | +$12 | ~−$140 |
| `shadow_poly_updown_sol_5m_fade_sniper` | sniper SOL 5m | 366 | 50.8 | +$0.45 | +$6 | ~−$120 |
| `shadow_poly_updown_sol_5m_fade_momo_v2` | momo_v2 SOL 5m | 351 | 50.1 | +$0.55 | +$7 | ~−$130 |
| `shadow_poly_updown_sol_15m_fade_momo_v2` | momo_v2 SOL 15m | 84 | 52.4 | +$1.88 | +$6 | ~−$90 |
| **Aggregate** | | 2 509 | ~51 | ~$0.85 | **+$71** | ~−$650 worst |

**Critical implementation note**: the fade companion must HOOK INTO the production fire pipeline so it gets called every time a production momo/sniper signal fires (including when prod ends up dropping it). This is a NEW hook, not an existing one. Confirm with `migration_2026_05_21/vps3_controller_inspect/paper.py` integration point.

### Sleeve #8 — `shadow_poly_updown_ALL_5m_S3_prewindow`

```python
def fire_decision_s3_prewindow(slot, fire_us, features):
    if slot.tf != "5m":
        return None
    # PRE-WINDOW timing: fire 60 s BEFORE slot_start
    if fire_us != (slot.slot_start_us - 60 * 1_000_000):
        return None
    # S3 rule: fair_edge > 0 + cvd_60s_agree + macd_agree
    if not (features.fair_edge_bp > 0
            and features.cvd_agree_60s
            and features.macd_agree):
        return None
    direction = "UP" if features.dev_bps > 0 else "DOWN"
    return Fire(
        sleeve_id="shadow_poly_updown_ALL_5m_S3_prewindow",
        slug=slot.slug, asset=slot.asset, tf="5m",
        direction=direction, notional_usd=25.0,
        meta={"rule": "S3", "fire_offset_s": -60,
              "fair_edge_bp": features.fair_edge_bp},
    )
```

**Backtest**: n = 1 961, WR = 52.8 %, per-trade = +$0.83, sum = +$1 628 / 21 d = **+$78/day**, binom_p = 0.029 (strongest single-offset result in the timing sweep). Lower WR than intra-slot sleeves but lower avg_vwap (~0.50) gives bigger per-share payoff on wins.

### Sleeve #9 — `shadow_poly_updown_ALL_15m_S4_prewindow`

```python
def fire_decision_s4_prewindow_15m(slot, fire_us, features):
    if slot.tf != "15m":
        return None
    # PRE-WINDOW timing: fire 120 s BEFORE slot_start
    if fire_us != (slot.slot_start_us - 120 * 1_000_000):
        return None
    if not (features.fair_edge_bp > 500
            and features.cvd_agree_30s
            and abs(features.dev_bps) >= 8):
        return None
    direction = "UP" if features.dev_bps > 0 else "DOWN"
    return Fire(
        sleeve_id="shadow_poly_updown_ALL_15m_S4_prewindow",
        slug=slot.slug, asset=slot.asset, tf="15m",
        direction=direction, notional_usd=25.0,
        meta={"rule": "S4_15m", "fire_offset_s": -120,
              "fair_edge_bp": features.fair_edge_bp},
    )
```

**Backtest**: n = 229, WR = 54.6 %, per-trade = **+$2.26**, sum = +$517 / 21 d = **+$25/day**, binom_p = 0.090.

---

## Bonus — 6 production-sleeve FILTERS (separate from the 9 new sleeves)

These don't create new sleeves; they DUPLICATE existing production sleeves with the gate filter added. Deploy as `shadow_{existing_sleeve_id}_gated_{gate_name}`. Each is a SHADOW VARIANT of the production sleeve — fires only when the production sleeve fires AND the new gate passes. Compare its PnL to the original production sleeve over 14 d.

```python
PROD_FILTER_OVERLAYS = [
    # (sleeve_to_clone, gate_predicate, shadow_id)
    ("poly_updown_eth_15m_sniper",  lambda f: f.m5v_pass,
     "shadow_poly_updown_eth_15m_sniper_m5v"),                   # p=0.011 ⭐
    ("poly_updown_btc_5m_momo_v2",  lambda f: f.fair_edge_bp > 500,
     "shadow_poly_updown_btc_5m_momo_v2_fairedge500"),           # p=0.081
    ("poly_updown_btc_15m_momo_v2", lambda f: f.fair_edge_bp > 500 and f.cvd_agree_30s,
     "shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30"),    # p=0.055
    ("poly_updown_sol_15m_sniper",  lambda f: f.fair_edge_bp > 500,
     "shadow_poly_updown_sol_15m_sniper_fairedge500"),           # p=0.066
    ("poly_updown_sol_5m_momo_v1",  lambda f: f.m5v_pass,
     "shadow_poly_updown_sol_5m_momo_v1_m5v"),                   # p=0.072
    ("poly_updown_sol_5m_momo_v2",  lambda f: f.cvd_agree_30s and f.macd_agree,
     "shadow_poly_updown_sol_5m_momo_v2_cvd_macd"),              # p=0.097
]

def fire_decision_overlay(production_signal, features):
    """Called AFTER production decides to fire. Shadow only fires if the
    extra gate also passes."""
    for prod_id, gate_fn, shadow_id in PROD_FILTER_OVERLAYS:
        if production_signal.sleeve_id == prod_id and gate_fn(features):
            # Mirror the production fire under the shadow sleeve_id
            return Fire(
                sleeve_id=shadow_id,
                **production_signal.copy_payload(),
                meta={"gate": gate_fn.__name__,
                      "prod_sleeve": prod_id},
            )
    return None
```

**Top expected uplifts (per overlay)**:

| shadow sleeve | n / 21 d | WR % | per-tr | sel_upl $ | $/day | p |
|---|--:|--:|--:|--:|--:|--:|
| `shadow_poly_updown_eth_15m_sniper_m5v` | 76 | 63.2 | **+$7.15** | +$615 | **+$29** | **0.011 ⭐** |
| `shadow_poly_updown_btc_5m_momo_v2_fairedge500` | 314 | 52.9 | +$0.34 | +$618 | +$29 | 0.081 |
| `shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30` | 68 | 63.2 | +$5.54 | +$350 | +$17 | 0.055 |
| `shadow_poly_updown_sol_15m_sniper_fairedge500` | 32 | 65.6 | **+$8.06** | +$288 | +$14 | 0.066 |
| `shadow_poly_updown_sol_5m_momo_v1_m5v` | 72 | 62.5 | +$4.99 | +$348 | +$17 | 0.072 |
| `shadow_poly_updown_sol_5m_momo_v2_cvd_macd` | 110 | 57.3 | +$2.13 | +$357 | +$17 | 0.097 |
| **Aggregate filters** | 672 | ~60 | ~$3 | **+$2 576 / 21d** | **+$123** | — |

These run alongside the 9 NEW sleeves above. If validated in shadow, ROLL INTO the corresponding production sleeve (replace the production fire rule with the gate-AND version).

---

## Wire-up summary for VPS3 / TV-agent

1. **Publisher additions** — add the missing features listed at the top to the per-slot feature feed:
   - `fair_up`, `fair_edge_bp`, `cvd_30s`, `cvd_60s`, `macd_hist`, `rvol_30_300`, `imb5`, `m1v_regime`, `m5v_regime`
2. **Sleeve registration** — add 9 sleeve IDs (and 6 overlay IDs) to the TV-agent sleeve registry, marked `mode = "shadow"` so no real CLOB orders fire.
3. **Fire-loop hooks**:
   - The Phase-1 ensemble (sleeve #1) and pre-window sleeves (#8, #9) need their OWN per-slot fire loop driven by `fire_offset_s` (`+120` for S4/S8 ensemble, `-60` for S3 5m, `-120` for S4 15m).
   - The 6 FADE sleeves (#2-7) HOOK INTO the existing momo/sniper signal pipeline — they fire ONLY when a production signal raises AND fails HOD/M5V filter.
   - The 6 PROD FILTER overlays hook AFTER the production fire decision — they fire ONLY when production decides to fire AND the extra gate passes.
4. **Per-fire log payload** — for each shadow fire, log to `trading_events` with `kind = "poly_updown_signal_shadow"` and include `meta` with rule, kelly_mult, fair_edge_bp, etc. so we can join to resolutions.
5. **Resolution join** — existing `poly_updown_resolution` event flow handles this automatically since shadow fires use the same slug-level resolution.
6. **L25 fill model** — shadow fires walk the same L25 books as production, with 85 ms latency + 2 %-on-profit fees (engine_v2.LegacyConfig).

## Monitoring during the shadow window (14 d minimum)

For each shadow sleeve, log the canonical 5-row scorecard daily:

```
sleeve_id | fires_today | WR_today | per_tr | sum_today | rolling_7d_sum | rolling_7d_dd
```

Trigger an alert if any sleeve:
- Diverges from backtest WR by > 8 pp for 3+ consecutive days
- Loses > 2 × the backtest max DD in any 24h window
- Sees fire-rate < 50 % of backtest expectation (suggests feature pipeline drift)

Compare each shadow sleeve to:
1. Its backtest expectation (this report)
2. The matching production sleeve if applicable (e.g., compare `shadow_poly_updown_btc_5m_momo_v2_fairedge500` to `poly_updown_btc_5m_momo_v2_HOLD`)

## Promotion criteria — after 14 days of shadow

For a sleeve to graduate from shadow → live:
1. Daily WR within ±5 pp of backtest expectation across the 14 d window
2. Sum-PnL positive on the rolling 7 d view
3. Max DD does not exceed 1.5 × backtest expectation
4. No data-feed outages / feature NaN-rate > 5 %

Top 3 likely to promote first (highest backtest p-significance + per-trade $):
1. **sleeve #1 — Phase-1 Kelly ensemble** (the biggest absolute mover)
2. **overlay — `shadow_poly_updown_eth_15m_sniper_m5v`** (only strict p < 0.05 result)
3. **sleeve #8 — S3 5m pre-window** (largest single-offset edge from timing sweep, p = 0.029)

## Files

- This spec: `strategy_lab/reports/SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md`
- Worked examples: `strategy_lab/reports/WORKED_EXAMPLES_KELLY_FADE_OVERLAY_2026_05_24.md`
- Per-sleeve breakdown: `strategy_lab/reports/PER_SLEEVE_PER_ASSET_TF_2026_05_24.md`
- Final phase-2 findings: `strategy_lab/reports/PHASE2_FINAL_FINDINGS_2026_05_24.md`
- Live fires CSV (for join): `data/v4/canonical/_results/live_fires_normalized.csv`
- Prod fills with new features: `data/v4/canonical/_results/prod_fills_with_indicators.parquet`
- Deploy candidate CSV (Phase-1 ensemble): `data/v4/canonical/_results/DEPLOY_CANDIDATE_S8_S4_offset120.csv`
