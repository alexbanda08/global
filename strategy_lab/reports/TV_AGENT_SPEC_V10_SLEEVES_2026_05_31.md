# TV Agent Spec — 4 new V10 shadow sleeves (2026-05-31)

_Deploy 4 new shadow (paper) sleeves on VPS3, derived from this session's full-period analysis. Three are ETH 5m winners + the single best risk-adjusted new gate; one is the corrected kelly. Each V10 runs ALONGSIDE its parent so we measure the new-gate lift live (the new gates are in-sample on the GA universe → shadow A/B confirms OOS)._

## Summary

| V10 sleeve | clones | change vs parent | market | why |
|---|---|---|---|---|
| `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10` | `..._v8` | **+ `g_sms_no_liquidity_above`** | ETH 5m | Calmar 17.3→23.7 (MaxDD −$25→−$15), full-period |
| `poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_V10` | `..._v6` | **+ `g_tr_above_pp`** | ETH 5m | cuts MaxDD ($35→$21), Calmar 12.0→12.3 |
| `poly_sniper_v5_eth_5m_bb_mp_hurst_band_V10` | `..._v6` | **`g_entry_vwap_in_band` → `g_entry_vwap_in_band_narrow`** | ETH 5m | +$1.41/tr, Calmar 9.6→13.6 |
| `shadow_poly_updown_ALL_5m_phase1_kelly_fe1000_V10` | `ALL_5m_phase1_kelly` | **`|fair_edge_bp|>1000` floor + ½-Kelly + drop `keep_EU`** | **BTC+ETH+SOL 5m** | only robust gate (both-half+); de-leverage |

All shadow/paper mode, $5 base stake (sniper) / ½-Kelly (kelly). Keep parents running for A/B.

---

## 1. `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10`

- **Clone**: `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8` (keep its exact gate stack, offset set, spread filter, direction=BOTH, ETH/5m).
- **Add one gate** to the AND-stack: **`g_sms_no_liquidity_above`** (SMS: no resting liquidity above on the bet side — i.e., clear path).
- Everything else identical (offset 60s, spread 0.02, $5, hold-to-resolve).
- **Backtest basis (full period Apr 24–May 26, $5, 0.07-curve)**: parent n=467, WR 82.0%, +$0.93/tr, +$432, MaxDD −$25, Calmar 17.3 → **V10 n=353, +$355, MaxDD −$15, Calmar 23.7**.
- **Alt to A/B**: `+ g_mp_skew_with` instead (n=275, +$0.25/tr lift, Calmar 20.1) — higher per-trade EV, slightly higher DD. Optionally register both as `_V10a` (sms) / `_V10b` (mp_skew).

## 2. `poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_V10`

- **Clone**: `poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6` (gates `g_tr_above_cloud + g_ribbon_agrees + g_mp_skew_with + g_hurst_trending`, offset 60, spread 0.02, BOTH, ETH/5m).
- **Add one gate**: **`g_tr_above_pp`** (price above the pivot point on the bet side).
- **Backtest basis**: parent n=481, WR 81.7%, +$0.88/tr, +$422, MaxDD −$35, Calmar 12.0 → **V10 +$254, MaxDD −$21, Calmar 12.3** (lower drawdown).
- **Alt (higher EV, lower freq)**: `+ g_entry_vwap_in_band_narrow` → +$2.28/tr but n drops 481→62. Register as `_V10b` if you want the high-conviction variant.

## 3. `poly_sniper_v5_eth_5m_bb_mp_hurst_band_V10`

- **Clone**: `poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6` (gates `g_bb_pos_with + g_mp_skew_with + g_hurst_trending + g_entry_vwap_in_band`, offset 60, spread 0.02, BOTH, ETH/5m).
- **Change one gate**: replace **`g_entry_vwap_in_band` → `g_entry_vwap_in_band_narrow`** (tighter entry-price band).
- **Backtest basis**: parent n=162, WR 74.1%, +$1.92/tr, +$311, MaxDD −$32, Calmar 9.6 → **V10 n=65, WR 76.9%, +$3.33/tr, +$216, MaxDD −$16, Calmar 13.6**.
- Note: ~60% fewer fires; this is a higher-conviction, lower-frequency variant.

## 4. `shadow_poly_updown_ALL_5m_phase1_kelly_fe1000_V10`

- **Clone**: `shadow_poly_updown_ALL_5m_phase1_kelly` (the momo/fair-value Kelly sleeve; **trades BTC + ETH + SOL 5m up/down**).
- **Changes**:
  1. **Add conviction floor**: fire only when **`|fair_edge_bp| > 1000`** (was: all positive-edge tiers). Direction = sign(fair_edge) → buy the fair-value-rich side.
  2. **Stake = ½-Kelly**: halve the Kelly multiplier (base unit $12.5 × tier_mult instead of $25 × tier_mult; caps max ~$50/trade vs ~$100).
  3. **Remove the `keep_EU` time-of-day gate** (failed OOS — see rationale).
- **Backtest basis (May 1–21, Kelly-sized, 0.07-curve)**: parent base n=3508, WR 84.4%, +$18,879, MaxDD −$844, Calmar 391 → **V10 (`fe>1000`, ½-Kelly) n=818, +$22.50/tr (full-Kelly) → ~+$9,200 at ½-Kelly, MaxDD ~−$260, Calmar ~528**. `fe>1000` is the only gate passing both-half holdout (H1 +$10.83, H2 +$34.17/tr at full-Kelly).
- **Risk note**: edge is concentrated (the high-`fair_edge_bp` 4× tier; 73% of in-sample PnL was week-21). ½-Kelly + the `fe>1000` floor is the de-risked posture. Kill-switch if `fair_edge_bp` predictiveness decays.

---

## Registration (VPS3 — same pattern as existing sniper_v5 / shadow sleeves)

1. **Sniper V10 (×3)**: add entries to the sniper_v5 sleeve registry (the spec list that `engine/main.py` / `api/bots.py` iterate). Each is a clone tuple of the parent with the gate-stack delta above. The new gate names (`g_sms_no_liquidity_above`, `g_tr_above_pp`, `g_entry_vwap_in_band_narrow`) are **already computed** in the sniper_v5 gate library (present in the universe panels) — no new feature code, just reference them in the AND-stack.
2. **Kelly V10 (×1)**: register a `shadow_poly_updown_*` sleeve cloning the phase1 kelly controller with: `fair_edge_bp` floor=1000, kelly_fraction×0.5, `keep_EU=False`.
3. Set all to **paper/shadow mode**, $5 (sniper) / ½-Kelly (kelly).
4. Keep the 4 parent sleeves running unchanged (A/B baseline).
5. Restart `tv-engine.service`; confirm each V10 emits `sleeve_fire_eval` / `poly_updown_signal` events.

## Acceptance criteria (12h + 7d live)

- All 4 V10 sleeves emit events and resolve trades (n>0).
- ETH V10 fire-rate ≈ the backtest gated/parent ratio (l_ema50 ~75%, cloud_ribbon ~55%, bb ~40% of parent fires).
- Kelly V10 fires only on `|fair_edge_bp|>1000` slots; stake ≤ ~$50.
- **7-day OOS check (the real point)**: compare each V10's live `$/tr` and WR to its parent. The new gate is confirmed only if V10 ≥ parent on both WR and Calmar live. If not, the in-sample improvement was overfit → revert to parent.

## Rationale + honest caveats

- **ETH 5m base alpha persists** full-period (in-sample WR 72-82% ≈ live 71-73%) — these are the fleet's best, lowest-drawdown sleeves (Calmar 10-17). The V10 gates further cut drawdown / lift EV **in-sample** on the GA universe.
- ⚠ **The 3 ETH new gates are in-sample** (universe = GA training set; ~200 candidates swept). Shadow-deploying V10 alongside the parent is exactly how we get the OOS confirmation. Do NOT promote to live until the 7-day A/B shows V10 ≥ parent.
- **Kelly `keep_EU` was dropped because it failed OOS** (both-half holdout H1 −$0.08 / H2 +$6.94 — the live +$2,272 was the week-21 spike). `fair_edge_bp>1000` is the durable replacement. ½-Kelly addresses the documented 4×-Kelly ruin risk.
- **Do NOT add `entry_vwap≤0.70` to the ETH winners** — it lifts $/tr but lowers Calmar (cuts net-positive high-priced winners). It's a marginal/loser-sleeve gate.

Source: `FULLPERIOD_5STRATS_FINAL_2026_05_31.md`, `ETH_NEWGATES_MDD_2026_05_31.md`, `KELLY_FULLPERIOD_2026_05_31.md`, `FULLPERIOD_PERSISTENCE_2026_05_30.md`.
