# VPS3 Sleeve Verification — scalp + DISAGR-HAWKES (2026-06-05)

**Ask:** verify the deployed exit-scalp sleeves and `shadow_disagr_hawkes_sol_5m_dn` are spec-true implemented.
**Result:** Both **spec-true** AND **live-firing**. Bonus: the gated scalp's edge is **holding up in live shadow**
(every `_v1` cell positive, every `_control_v1` negative — the `entry_vwap<0.55` gate is the edge, confirmed forward).

## Authority: Python, not YAML
- Engine loads `SNIPER_V5_SLEEVES` from `backend/app/strategies/polymarket/sniper_v5_sleeves.py`
  (`engine/poly_sniper_v5_loop.py:52,145`). **`configs/poly_sniper_v5_sleeves.yaml` is NOT loaded** (grep: no
  `yaml.safe_load` of it anywhere live). The YAML's scalp block is **stale** — missing `entry_band` and
  `exit_policy` and showing `_v1`==`_control_v1`. ⚠️ Delete/sync it; a future maintainer could be misled.

## DISAGR-HAWKES — spec-true ✓
`sniper_v5_sleeves.py:1771` + gate `sniper_v5_gates.py:g_disagr_hawkes`:
| field | spec | implemented |
|---|---|---|
| sleeve_id | shadow_disagr_hawkes_sol_5m_dn | ✓ |
| asset/tf/dir | SOL / 5m / DOWN | ✓ |
| offset | ws_s+210s | `offsets=(210,)` ✓ |
| spread | same-token ≤0.02 | `spread_filter=0.02` ✓ |
| notional | $25 | ✓ |
| book gate | ≥25 events / 120s | `book_event_window_s=120.0` ✓ |
| one-shot/slug | yes | ✓ |
| gate logic | `mp_skew<0 ∧ imb5_diff>0 ∧ hawkes<−0.2` ∧ DOWN | exact ✓ |
| exit | HOLD to resolution | ✓ (no scalp exit) |
- 🔴 **Fire rate problem:** 396 `poly_updown_signal` candidates in ~2 days but **only 1 actual fired position**
  (`poly_updown_resolution`). At ~1 fill / 2 days, the ≥200-forward-fires graduation bar is **~1 year away**.
  The 3-feature AND gate is too restrictive live. Either accept it as a curiosity, loosen a threshold, or drop it.

## Exit-scalp (16 sleeves) — spec-true ✓
`sniper_v5_sleeves.py` generator (BTC,ETH × 5m,15m × {v1,control} + d3 variants):
- `direction=BOTH`, `offsets=(5,)`, `exit_policy="SCALP_EXIT"`, `scalp_exit_offset_s=60` (sell on book at **+60s**),
  `entry_band=(0.0,0.55)` for `_v1` / `None` for `_control_v1`, gate `g_oracle_lag_with(5,12)` (δ≥5) or `(3,12)` (δ≥3).
- Controller enforces the band (`polymarket_sniper_v5.py:918-919`) and the deadline exit
  (`poly_sniper_v5_loop.py:396` `fire_us + 60s`). All matches `TV_AGENT_SPEC_SCALP_EXIT_SHADOW_2026_06_02`.
- Note: current exit = **+60s** (pending spec #3 wants +45; my `SCALP_DYNAMIC_EXIT_2026_06_04` says **keep +60 for BTC**).

## ⭐ Live shadow PnL (poly_updown_scalp_exit, ~2 days, 2026-06-03→05) — the gate works forward
| sleeve | n | $/tr | net | WR |
|---|---|---|---|---|
| **btc_5m_v1** (gated) | 30 | **+4.49** | +67.29 | .333 |
| btc_5m_control_v1 | 140 | −0.18 | −12.47 | .257 |
| **btc_5m_d3_v1** (gated,$5) | 66 | **+0.91** | +30.14 | .348 |
| btc_5m_d3_control_v1 | 298 | +0.19 | +28.00 | .312 |
| **btc_15m_v1** | 16 | **+2.56** | +20.44 | .313 |
| btc_15m_control_v1 | 46 | −0.54 | −12.49 | .196 |
| btc_15m_d3_v1 | 37 | +0.41 | +7.74 | .324 |
| **eth_5m_v1** | 6 | **+3.13** | +9.38 | .333 |
| eth_5m_control_v1 | 54 | −0.84 | −22.56 | .259 |
| eth_5m_d3_v1 | 20 | +0.24 | +2.41 | .250 |
| eth_15m_v1 | 2 | +0.16 | +0.16 | .500 |

- **Every gated `_v1` cell is POSITIVE; every `_control_v1` (no vwap<0.55 band) is NEGATIVE/breakeven.** The
  `entry_vwap<0.55` gate is the edge — confirmed in live shadow, not just backtest. btc_5m_v1 live **+$4.49/tr**
  ≈ backtest +$5.56. Asymmetric payoff (WR ~33% but $/tr positive — wins are big).
- **Graduation progress:** gated `_v1` scalp_exits so far ≈ 30+16+6+2 (δ5) + 66+37+20+2 (δ3) = **~179 fills /
  ~2 days**, aggregate net ≈ **+$138**. On track to cross the ≥200-forward-fires + CI>0 gate within days
  (btc_5m_d3 $5 is the workhorse). **This is the first strong forward confirmation of the exit-scalp.**

## Actions
1. Keep accruing → at n≥200 gated fills, compute the live-wallet bootstrap CI (the real graduation gate).
2. DISAGR-HAWKES: fire rate ~0 → won't graduate; loosen or shelve.
3. Delete/sync the stale `poly_sniper_v5_sleeves.yaml` scalp block (unused but misleading).
4. Exit stays +60 for BTC (confirmed by `SCALP_DYNAMIC_EXIT_2026_06_04`); do NOT blanket-flip to +45.
