# TV-AGENT SPEC — Time-of-Day Gated Scalp Sleeves (2026-06-05)

**Type:** new shadow sleeves (clone of the live scalp sleeves + a UTC-hour exclude gate).
**Evidence:** `SLUG_SELECTION_RESULTS_2026_06_05.md` — scalp edge is ~2× in 22–02 UTC and dead at h12/17/18–21.
Excluding the dead hours lifts $/tr with ~no volume loss; walk-forward stable (3/3 folds); independently
corroborated by F2 (puts 32% of its slugs in 22–02 vs 17% baseline, avoids 18–21 entirely).
**Goal:** measure the live lift of a light time-gate vs the existing un-houred scalp sleeves (the control).

## Backtest support (gated cell, BTC+ETH, entry_vwap<0.55, pnl60, n=780)
| gate | coverage | $/tr | total PnL | walk-forward |
|---|---|---|---|---|
| none (current live) | 100% | +2.95 | +2302 | — |
| **exclude {12,17}** (TOD2) | 94% | **+3.14** | +2306 | +2.84 / +3.41 / +3.25 ✓ |
| exclude {2,12,16,17,18} (TOD5) | 79% | +3.55 | +2201 | (higher Sharpe, small volume cost) |

## New gate — `g_hour_not_in` (add to `app/strategies/polymarket/sniper_v5_gates.py`)
```python
def g_hour_not_in(direction, fire_us, *, excluded_hours=frozenset(), **_kw) -> bool:
    """Block the fire if the UTC hour of fire_us is in excluded_hours.
    Hour anchor = UTC hour of fire_us (matches backtest: (fire_us//1e6 % 86400)//3600)."""
    hour = (int(fire_us) // 1_000_000 % 86_400) // 3600
    return hour not in excluded_hours
```
Register in `__all__`. GateRef params pass the hour set, e.g. `(("excluded_hours", "12,17"),)` parsed to a set
(mirror how other GateRef tuple-args are parsed in this module).

## New sleeves (add to `app/strategies/polymarket/sniper_v5_sleeves.py`)
Clone the existing GATED scalp v1 sleeves (entry_band=(0,0.55), exit_policy="SCALP_EXIT",
scalp_exit_offset_s=60, offsets=(5,), one_shot_per_slug, BOTH) and append the hour gate. Use the **TOD2 set
{12,17}** as primary (94% coverage). Cover the workhorse cells: btc_5m δ≥5 ($25) + the $5 δ≥3 cells
(btc_5m, btc_15m, eth_5m) which fire fastest.

```python
# --- TOD2 (exclude {12,17} UTC) variants of the gated scalp sleeves ---
*(
    SniperV5Sleeve(
        sleeve_id=f"shadow_scalp_exit_{_sym.lower()}_{_tf}{_d3}_tod2_v1",
        asset=_sym, tf=_tf, direction="BOTH",
        offsets=(5,),
        spread_filter=_SPREAD_LAGV2,
        notional_usd_override=Decimal("5.0" if _d3 else "25.0"),
        one_shot_per_slug=True,
        exit_policy="SCALP_EXIT",            # scalp_exit_offset_s defaults to 60
        entry_band=(0.0, 0.55),
        gates=(
            GateRef(g_oracle_lag_with,
                    (("lo_bps", "3.0" if _d3 else "5.0"), ("hi_bps", "12.0")),
                    f"g_oracle_lag_with({'3.0' if _d3 else '5.0'},12.0)"),
            GateRef(g_hour_not_in, (("excluded_hours", "12,17"),), "g_hour_not_in(12,17)"),
        ),
    )
    for (_sym, _tf, _d3) in [("BTC","5m",False), ("BTC","5m",True), ("BTC","15m",True), ("ETH","5m",True)]
),
```
- **Control = the existing `shadow_scalp_exit_*_v1` sleeves** (no hour gate). Compare $/tr of `_tod2_v1` vs the
  matching `_v1` over forward fires → the hour-gate lift.
- Optional **TOD5 arm:** duplicate with `g_hour_not_in(2,12,16,17,18)` and id suffix `_tod5_v1` (higher Sharpe,
  ~79% volume) if you want both arms.
- `paper_only`/shadow: the `shadow_` id prefix routes to the shadow log (same as the existing scalp sleeves).

## Validation / acceptance
- Confirm the new sleeves fire only outside {12,17} UTC (check `trading.events` `poly_updown_signal` hour histogram).
- Graduation: after ≥150 forward `poly_updown_scalp_exit` fills per arm, compare bootstrap $/tr of `_tod2_v1`
  vs `_v1`; expect `_tod2` ≥ `_v1` at ~94% of the fire count. No real capital (shadow only).

## Host / notes
VPS3 (same host as the live scalp sleeves). Exit stays **+60s** (per `SCALP_DYNAMIC_EXIT_2026_06_04`: do NOT
flip to +45 for BTC). Hour anchor must match backtest (UTC hour of fire_us). Re-verify 0.07 winner-only fee live.
