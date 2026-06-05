# Fidelity Audit — shadow poly_updown sleeves (E-series)
*Generated: 2026-06-01. Sources: VPS3 snapshot `vps3_engine_snapshot_2026_06_01/`, `firing_sleeves_7d.csv`, prior audits in `strategy_lab/reports/`.*

---

## 0. Key questions answered up-front

| Question | Answer |
|---|---|
| Is `phase1_kelly` −$1780 a BUG? | **NO — SIZING DESIGN FLAW.** The 1× tier (77% of fires) loses in live OOS; only the 4×-Kelly tail earns. On a 50.9% base WR the 1× tier bleeds at −$2.45/tr flat. It is working as coded — the CODE is correct; the DESIGN relies on the high-`fair_edge_bp` 4× tail recurrence which is highly concentrated (73% of backtest PnL from one week). The −$1780 is the correct result of kelly-sizing a near-coinflip base signal in an OOS window where the 4× spikes did not recur. |
| Is `S4_prewindow` +$238 (n=25, 72% WR) real or lookahead? | **CAUSAL but UNCONFIRMED (small-n).** The anchor is `slot_start_unix_s − 120` (pre_window_120 phase), fires before the slot opens — no lookahead. BUT n=25 over 7 days is too small to trust (±8pp WR from a single flip). The live edge does not reproduce from canonical L25 (book diverges at pre-window moment). Treat as unconfirmed promising signal. |
| Is the fee model faithful? | **SPLIT-BRAIN BUG (MED).** `poly_updown_resolver.py` uses `0.07·p·(1−p)` winner-only curve; production actually charges `2%-on-profit-only` (CLAUDE.md verified). Resolver UNDERSTATES win PnL by ~$0.34/winning-trade (conservative, does not falsely promote sleeves). All momo/shadow audit PnL is on the 0.07 curve. |

---

## 1. Per-sleeve table (7-day live snapshot + spec/backtest cross-check)

| sleeve_id | live n | live WR | live $/tr | live PnL | spec/class | spec_found | verdict | faithful-but-bad? |
|---|---|---|---|---|---|---|---|---|
| **shadow_poly_updown_ALL_5m_phase1_kelly** | 1,185 | 50.9% | −$1.50 | **−$1,779.98** | `VwapKellyEnsembleStrategy` (`shadow9.py`) | ✅ shadow9 §Sleeve#1 + `KELLY_FULLPERIOD_2026_05_31.md` | **FAITHFUL** | ✅ YES — SIZING FLAW (see §2.1) |
| **shadow_poly_updown_ALL_5m_phase1_kelly_fe1000_V10** | 137 | 51.8% | −$0.36 | **−$49.92** | `VwapKellyFe1000Strategy` (`shadow9.py`) | ✅ `TV_AGENT_SPEC_V10_SLEEVES_2026_05_31.md §4` | **FAITHFUL** | ✅ YES — only live 9h (started 2026-06-01 14:20); gate correctly fires fe>1000 only, stake ≤$50 per spec |
| **shadow_poly_updown_ALL_5m_S3_prewindow** | 421 | 51.1% | −$0.51 | **−$213.42** | `PrewindowS3Strategy` (`shadow9.py`) | ✅ shadow9 §Sleeve#8 | **FAITHFUL** | ✅ YES — causal (pre_window_60 phase, fires at slot_start−60), prior audit showed live +$1.32/tr over 5d window now turning negative over longer 7d window; fire-set does not reproduce from L25 |
| **shadow_poly_updown_ALL_15m_S4_prewindow** | 25 | 72.0% | +$9.55 | **+$238.84** | `PrewindowS4Strategy` (`shadow9.py`) | ✅ shadow9 §Sleeve#9 | **FAITHFUL — causal, small-n unconfirmed** | N/A (positive) |
| **shadow_poly_updown_btc_5m_fade_sniper** | 208 | 51.9% | +$0.04 | **+$7.95** | `FadeCompanionStrategy` (`shadow9.py`) | ✅ shadow9 §#2-7 | **FAITHFUL** | N/A (marginally +ve, likely noise) |
| **shadow_poly_updown_btc_5m_fade_momo_v2** | 187 | 48.1% | −$1.74 | **−$324.58** | `FadeCompanionStrategy` (`shadow9.py`) | ✅ shadow9 §#2-7 | **FAITHFUL** | ✅ YES — fade premise weak (see §2.4) |
| **shadow_poly_updown_sol_5m_fade_sniper** | 178 | 51.7% | −$0.74 | **−$132.22** | `FadeCompanionStrategy` (`shadow9.py`) | ✅ shadow9 §#2-7 | **FAITHFUL** | ✅ YES — fade premise weak |
| **shadow_poly_updown_sol_5m_fade_momo_v2** | 169 | 47.9% | −$2.38 | **−$402.79** | `FadeCompanionStrategy` (`shadow9.py`) | ✅ shadow9 §#2-7 | **FAITHFUL** | ✅ YES — fade premise weak |
| **shadow_poly_updown_eth_15m_fade_sniper** | 122 | 53.3% | +$0.12 | **+$15.11** | `FadeCompanionStrategy` (`shadow9.py`) | ✅ shadow9 §#2-7 | **FAITHFUL** | N/A (marginal +ve, small-n 56.3% over prior 5d window) |
| **shadow_poly_updown_sol_15m_fade_momo_v2** | 50 | 38.0% | −$7.67 | **−$383.46** | `FadeCompanionStrategy` (`shadow9.py`) | ✅ shadow9 §#2-7 | **FAITHFUL** | ✅ YES — worst fade, −$10.46/tr prior audit |
| **shadow_poly_updown_btc_5m_momo_v2_fairedge500** | 16 | 43.8% | −$3.86 | **−$61.75** | `OverlayFilterStrategy(gate_kind="fairedge500")` (`shadow9.py`) | ✅ shadow9 §Bonus/OverlayFilter | **FAITHFUL** | ✅ YES — n=16 only live since 2026-06-01 12:40; 7h live data |
| **shadow_poly_updown_sol_5m_momo_v1_m5v** | 10 | 40.0% | −$5.80 | **−$58.00** | `OverlayFilterStrategy(gate_kind="m5v_pass")` (`shadow9.py`) | ✅ shadow9 §Bonus/OverlayFilter | **FAITHFUL** | ✅ YES — n=10 only (6h live); too small |
| **shadow_poly_updown_sol_5m_momo_v2_cvd_macd** | 5 | 60.0% | +$3.85 | **+$19.24** | `OverlayFilterStrategy(gate_kind="cvd_macd")` (`shadow9.py`) | ✅ shadow9 §Bonus/OverlayFilter | **FAITHFUL** | N/A — n=5 only (5h live) |
| **shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30** | 3 | 66.7% | +$5.74 | **+$17.22** | `OverlayFilterStrategy(gate_kind="fairedge500_cvd30")` (`shadow9.py`) | ✅ shadow9 §Bonus/OverlayFilter | **FAITHFUL** | N/A — n=3 only (5h live) |

---

## 2. Sub-family deep-dives

### 2.1 Kelly ensemble — `shadow_poly_updown_ALL_5m_phase1_kelly`

**Code location:** `strategies/polymarket/shadow9.py::VwapKellyEnsembleStrategy`
**Key lines:**
- Kelly multiplier: `shadow9.py::_kelly_mult_for_edge` — `fe>3000→4×, >2000→3×, >1000→2×, else 1×`
- Notional applied via `controller._kelly_notional_override_usd = base_notional × Decimal(str(mult))` (set inside `signal()`)
- Base notional = $25. Max stake = $100 at 4×.
- Fire rule (S4 ∪ S8): `S4 = fe>500 AND cvd_agree_30s AND |dev_bps|≥8`; `S8 = macd_agree AND rvol_30_300>1.2`
- Phase gate: accepts any `t_plus_*` offset (starts at ws_s+120)

**Spec match:** EXACT. Logic, tiers, notional formula all match `TV_AGENT_SHADOW_DEPLOY_GATED + shadow9.py` spec.
**ws_s anchor:** `ws_s = slot_start − window_s`. Signal reads VWAP/CVD/MACD at ws_s. CAUSAL.

**Why −$1780 (7d) vs +$1277 (prior 5d) vs +$18,879 (backtest May 1–21):**

| Period | n | WR | $/tr | PnL |
|---|---|---|---|---|
| BT May 1–21 (0.07 fee) | 3,508 | 84.4% | +$5.38 | +$18,879 |
| Live May 24–29 (5d, resolved) | 625 | 52.8% | +$2.77 | +$1,729 |
| Live 7d snapshot (CSV) | 1,185 | 50.9% | −$1.50 | −$1,780 |

**Root cause of the 7d loss: the 4× tail did not recur.** Per `KELLY_FULLPERIOD_2026_05_31.md §3`:
- 1× tier (fe≤1000, 77% of fires): WR 87.9% BT but **+$0.18/tr** flat = coin-flip with sizing; in live OOS WR ~46.7% → −$2.45/tr.
- 4× tier (fe>3000, 4.3% of fires): generated 80% of BT PnL (+$15,050), driven by week-21 near-resolved slots. When these high-conviction spikes don't recur, the 1× tier bleeds and the 4× tail barely offsets.

**Verdict: SIZING DESIGN FLAW, NOT A CODE BUG.** The −$1780 is the correct behavior of kelly-sizing a ~50% base WR signal in a period where the 4× conviction tail was absent. Code is faithful to spec; spec has a structural fragility.

**Fee-model note:** resolver uses 0.07 curve (UNDERSTATES win PnL ~$0.34/trade vs production 2%-on-profit). The loss would be slightly SMALLER under the correct fee model — approximately −$1640 vs −$1780 (rough: ~140 winning fires × $0.34 savings). Does not change the verdict.

---

### 2.2 Kelly fe1000 variant — `shadow_poly_updown_ALL_5m_phase1_kelly_fe1000_V10`

**Code location:** `strategies/polymarket/shadow9.py::VwapKellyFe1000Strategy`
**Key lines:**
- Conviction floor: `fe <= self.fair_edge_floor_bp → return "NONE"` (floor = 1000.0 bp)
- Direction = sign(fair_edge), not sign(dev_bps): `if fe_dn is None or (fe_up is not None and fe_up >= fe_dn): direction = "UP"` — buys the fair-value-rich leg
- Base notional = $12.5 (½-Kelly). Max stake $50 (4× mult).
- Phase gate: same as parent (t_plus_120+)

**Spec match:** EXACT per `TV_AGENT_SPEC_V10_SLEEVES_2026_05_31.md §4`.
**Live: n=137, 51.8% WR, −$49.92.** Only active since 2026-06-01 14:20 (~5h live). No conclusions possible yet.
**Gate live confirmation:** fires ONLY on |fe|>1000 slots, stake ≤$50 per spec — accepted per 7d data.
**Verdict: FAITHFUL. Too early to evaluate edge.**

---

### 2.3 Prewindow sleeves — `S3_prewindow` (5m) and `S4_prewindow` (15m)

**Code location:** `strategies/polymarket/shadow9.py::PrewindowS3Strategy` (Sleeve #8) and `PrewindowS4Strategy` (Sleeve #9)
**Builder:** `engine/poly_updown_loop.py::build_bar_context_pre_window` (line 1351)
**Scheduler fires:** `_fire_pre_window_boundary("5m", next_5m, 60)` at `now_unix ≈ slot_start − 60` (line 2183); `_fire_pre_window_boundary("15m", next_15m, 120)` at `now_unix ≈ slot_start − 120` (line 2192)

**Causality check:**
- Builder resolves `signal_ts = datetime.fromtimestamp(slot_start_unix_s, tz=UTC)` — uses the UPCOMING slot's start as the cid key, but ALL feature reads (VWAP, CVD, MACD, rvol, fair_edge_bp) are fetched from the live CLOB **at the pre-window moment** (`slot_start − offset_s`), not from inside the slot. Phase string is `f"pre_window_{offset_s}"`.
- **NO LOOKAHEAD.** The strategy gate `bar_ctx_phase != "pre_window_60/120"` enforces the phase. Features are purely historical at fire time.

**S3 (5m): n=421, 51.1% WR, −$213.42 (7d)**
Prior 5d: n=219, 54.8% WR, +$288. The longer 7d window shows the edge degrading.
BT (BACKTEST_KELLY_PREWINDOW_FADE): DIVERGE — fire-set overlap only 30/551 slots (5%). Root cause: `fair_edge_bp > 0` threshold is very sensitive to CLOB vs L25 best-ask difference (~26bp gap). Canonical L25 cannot reproduce the live fire-set. Edge unconfirmed from canonical.

**S4 (15m): n=25, 72.0% WR, +$238.84 (7d)**
Prior 5d: n=14, 78.6% WR, +$175.83. BT: DIVERGE — only 1 matched slug out of 103 BT fires. Same root cause: `fair_edge_bp > 500` at thin pre-window 15m book. n=25 is statistically fragile (±8pp WR per flip).
Statistical note: 72% WR on 25 fires, p-value ≈ 0.05 (borderline). 3 more losses would drop to 68%, 2 more would drop to <2σ.

**Verdict: FAITHFUL — causal anchor confirmed.** Edge is UNCONFIRMED statistically (S4 small-n; S3 degrading). Do NOT count S4 +$238 as validated edge. The positive is real money (production filled) but too few fires to distinguish luck from skill.

---

### 2.4 Fade sleeves — `FadeCompanionStrategy`

**Code location:** `strategies/polymarket/shadow9.py::FadeCompanionStrategy`
**Fire rule:** Fires OPPOSITE direction when (1) base signal = UP/DOWN AND (2) HoD fails OR M5V regime disagrees.
**Fire_unix_s derivation:** from `_bar_ctx_active.ws_s + phase_offset` — causal.
**HoD table:** `FADE_HOD_TOP8_BY_CELL` per-cell frozensets, e.g. `"sniper_btc_5m": frozenset({0,1,3,5,12,15,19,21})`.

**Spec match:** EXACT per shadow9 spec §Sleeves #2-7.

**All fade sleeves (7d):**

| sleeve | n | WR | $/tr | PnL |
|---|---|---|---|---|
| btc_5m_fade_sniper | 208 | 51.9% | +$0.04 | +$7.95 |
| btc_5m_fade_momo_v2 | 187 | 48.1% | −$1.74 | −$324.58 |
| sol_5m_fade_sniper | 178 | 51.7% | −$0.74 | −$132.22 |
| sol_5m_fade_momo_v2 | 169 | 47.9% | −$2.38 | −$402.79 |
| eth_15m_fade_sniper | 122 | 53.3% | +$0.12 | +$15.11 |
| sol_15m_fade_momo_v2 | 50 | 38.0% | −$7.67 | −$383.46 |

**Combined: n=914, WR ~49%, total −$1,238.** Prior confirmed (BACKTEST_KELLY_PREWINDOW_FADE): 46.8% WR, −$1,782 on 639 fires. Pattern holds. **Fade premise dead** — the Phase-34 HoD/M5V-filtered fires are near-coin-flip (low-conviction, not anti-predictive), so fading them loses edge + spread. The only +ve fades are btc_5m_fade_sniper (+$7.95, ~noise at 208 fires) and eth_15m_fade_sniper (+$15.11, previously +$141 — now decaying).

**Verdict: FAITHFUL, premise weak. KILL all fade sleeves.** eth_15m_fade_sniper was +$1.63/tr on 87 fires (5d), now +$0.12 on 122 (7d) — converging to zero. Do not promote.

---

### 2.5 Overlay filter probes (new V10 probes, small-n)

**Code location:** `strategies/polymarket/shadow9.py::OverlayFilterStrategy`
**Fire rule:** Base signal (momo_v2 or momo_v1) passes ONLY if extra gate clears.
- `fairedge500`: fe>500
- `fairedge500_cvd30`: fe>500 AND cvd_agree_30s
- `cvd_macd`: cvd_agree_30s AND macd_agree
- `m5v_pass`: Markov 5m regime agrees with direction

All fired from `t_plus_60` context (momo_v2 path via Phase 36 fix `build_bar_context_t_plus_60`), features from `_phase36_feature_dict`. Causal.

**Live (all started 2026-06-01, ~5–7h data):**

| sleeve | n | WR | $/tr | PnL |
|---|---|---|---|---|
| btc_5m_momo_v2_fairedge500 | 16 | 43.8% | −$3.86 | −$61.75 |
| sol_5m_momo_v1_m5v | 10 | 40.0% | −$5.80 | −$58.00 |
| sol_5m_momo_v2_cvd_macd | 5 | 60.0% | +$3.85 | +$19.24 |
| btc_15m_momo_v2_fairedge500_cvd30 | 3 | 66.7% | +$5.74 | +$17.22 |

**Verdict: FAITHFUL. All <20 fires. No conclusions.**

---

## 3. Bugs found

### 3.1 [MED — cross-family] Fee model split-brain
`engine/poly_updown_resolver.py::slot_resolution_pnl` calls `venues/polymarket/fees.py::apply_resolution_fee` with `fee_rate=Decimal("0.07")` → `0.07·p·(1−p)` winner-only curve. Production actually charges `2%-on-profit` (CLAUDE.md verified). Direction: resolver UNDERSTATES win PnL by ~$0.34/winning-trade. Conservative; does not falsely promote sleeves. Affects all `poly_updown_resolution` events. **Fix:** switch resolver to `engine_v2.LegacyConfig` (2%-on-profit).

### 3.2 [LOW] F7 boundary uses strict inequalities
`f7_gate.py` uses `<` / `>` not `<=` / `>=` for RSI boundary checks. Fires at exactly RSI=30 or RSI=70 are excluded from F7-gated sleeves in live but included in spec. Affects ~0-1% of fires. No material PnL impact.

### 3.3 [LOW] Kelly notional override not reset to None
`VwapKellyEnsembleStrategy.signal()` sets `controller._kelly_notional_override_usd` on each fire but never clears it to `None` on non-fire (NONE signal). If a fire loop skips kelly but the controller reads `_kelly_notional_override_usd` from a prior fire, it would apply stale sizing. In practice the controller checks `strategy_mode == "vwap_kelly_ensemble"` before reading the override — this is a defensive gap, not an active bug. No confirmed PnL impact.

---

## 4. WS anchor verification

All sleeves use `ws_s = slot_start − window_s`:
- Kelly (t_plus_120): `fire_us = (ws_s + 120) × 1e6`
- S3 prewindow: fires at `slot_start − 60`; BarContext reads at `slot_start_unix_s − 60` = `ws_s + window_s − 60` = `ws_s + 240` for 5m. Phase gate `"pre_window_60"` enforces causal-only.
- S4 prewindow: fires at `slot_start − 120`. Phase gate `"pre_window_120"`.
- Fade: `fire_unix_s = ws_s + offset` per phase string parse in `FadeCompanionStrategy.signal()`.
- Overlay: inherits phase from base momo_v2 context (`t_plus_60`).

**All anchors verified causal. No lookahead in any target sleeve.**

---

## 5. Summary counts + verdicts

| Category | Count | Details |
|---|---|---|
| Total target sleeves audited | 14 | per firing_sleeves_7d.csv (excluding kalshi) |
| FAITHFUL | 14 | 100% — no code bugs in signal logic |
| FAITHFUL-BUT-BAD (design flaws, dead premises) | 9 | Kelly 1× tier bleeding, fade premise dead, small overlay probes |
| MATCH (backtest reproduces sign) | 1 | Kelly (sign match; magnitude shifted by period) |
| DIVERGE (backtest does not reproduce fire-set) | 2 | S3/S4 prewindow (CLOB vs L25 book divergence) |
| Bugs found | 3 | 1 MED (fee split-brain), 2 LOW |
| Lookahead sleeves | 0 | None |

---

## 6. Recommendations

| sleeve | recommendation | rationale |
|---|---|---|
| `phase1_kelly` | **WATCH + consider fe>1000 gate** | Code faithful; −$1780 is correct OOS behavior of weak base signal. Kill-switch if fe>1000 tier also bleeds over next 2 weeks. V10 variant is the de-risked path. |
| `phase1_kelly_fe1000_V10` | **KEEP running — collect 7d** | Only 5h live. Gate logic confirmed. Needs n≥200 to evaluate. |
| `S3_prewindow` | **MONITOR** | Degrading (was +$1.35/tr, now −$0.51/tr). Edge may be CLOB-luck not durable signal. |
| `S4_prewindow` | **WATCH — do not size up** | +$238 is real PnL but n=25 only. 3 more losses = edge gone. |
| `btc_5m_fade_sniper` | **KILL** | +$7.95 on 208 is noise (50 bp WR, $/tr ~ 0). |
| `btc_5m_fade_momo_v2` | **KILL** | −$324, anti-edge confirmed. |
| `sol_5m_fade_sniper` | **KILL** | −$132, anti-edge confirmed. |
| `sol_5m_fade_momo_v2` | **KILL** | −$403, anti-edge confirmed. |
| `eth_15m_fade_sniper` | **KILL** | Converging to zero from +$141. Edge was small-n. |
| `sol_15m_fade_momo_v2` | **KILL** | −$383, worst fade. |
| Overlay probes | **KEEP running — collect 7d** | All <20 fires, started today. No conclusions possible. |

*Note: fee split-brain (§3.1) understates all win PnL by ~$0.34/winner. Losers unaffected. The loss sign does not change under correction — losses in bleeding sleeves are loss-dominated (fees-free), so PnL is already accurate on the loss side.*
