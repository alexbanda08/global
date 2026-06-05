# FINAL CORRECTED AUDIT — All Shadow Sleeves — 2026-05-29

Supersedes the fee/V9/deprecation claims in `MASTER_LIVE_VS_BACKTEST_2026_05_29.md` and `DEBUG_FINDINGS_ALL_SLEEVES_2026_05_29.md`. Three operator corrections applied:
1. **Fee 0.07·p·(1−p) curve is CORRECT** (not a bug).
2. **V9 is wired and working** on multi-venue liquidations (bybit/bitget/okex/+1).
3. **Many sleeves are DEPRECATED** (hidden, not active) — excluded from the active analysis.

---

## CORRECTION 1 — Fee model: 0.07 curve is RIGHT ✅ (was wrongly flagged as Bug 1)

- Live resolution PnL `pnl_won = (1−vwap)·shares·(1 − 0.07·vwap)` is the **correct, intended** Polymarket fee. The 0.07·p·(1−p) winner-only curve is the true formula. My earlier "legacy 2%-on-profit" assumption (from a stale CLAUDE.md note) is WRONG.
- **Consequence for OUR backtests**: every spec backtest that used `LegacyConfig` (2%-on-profit) **undercharged fees → overstated PnL**. At p≈0.69 the curve fee (~0.0150/share) is ~2.4× the legacy fee (~0.0062/share). So live PnL runs **modestly below** the legacy-fee backtest projections — this is expected, not a divergence. Re-baseline all future backtests on the 0.07 curve (`engine_v2` poly_taker_curve), NOT LegacyConfig.
- **Residual minor inconsistency (LOW)**: the HEDGE_LATE cut path uses legacy `·0.98` while the HOLD/resolution path uses the 0.07 curve. A mid-slug taker sell should also pay the curve fee. Fix: switch the hedge-cut leg to the 0.07 curve for consistency. Tiny magnitude, 1 sleeve (`_H`), not urgent.

**Net: Bug 1 is RETRACTED.** No systemic fee bug. Only a 1-line hedge-path consistency tweak.

---

## CORRECTION 2 — V9 is live and working on multi-venue liquidations ✅

- Earlier I said "V9 silent until HL parquet populated." WRONG. V9 is firing and profitable in places.
- The A2 cascade gate function takes a liquidation DataFrame; the param is still named `hl_short_proxy` (stale Hyperliquid-era label) but the **wiring feeds multi-venue liquidations from our own collectors: bybit, bitget, okex (+1)**. Working as of this audit.
- Live V9 evidence (lifetime, $5 stake): `btc_5m_up_b2_contrarian2k_v9` +$81 (67% WR, n=30) · `sol_5m_b3_abs500_no_opp_v9` +$43 (54%, n=46) · `sol_5m_b1_polyflow_aligned_v9` +$23 (83%, n=6) · `sol_5m_down_b1_500_v9` +$23 (100%, n=3) · `sol_5m_b3_abs500_v9` +$20 (50%, n=52) · `btc_5m_up_a2_hlcascade50k_v9` +$7 (67%, n=3) · `btc_5m_a2_hlcascade100k_v9` +$3 (50%, n=6).
- V9 losers: `btc_5m_down_b2_contrarian2k_v9` −$38 (34%, n=29) — the DOWN contrarian leg is failing live (UP leg works); `sol_5m_down_b1_flow250_v9` −$9 (41%); `sol_5m_b1_120s_250_v9` −$2 (breakeven).
- **Recommendation**: V9 UP-side flow/cascade gates validate live; the DOWN-contrarian leg (b2 DOWN) underperforms — consider tightening or dropping the DOWN direction on b2. A2 multi-venue cascade is promising but LOW_N — keep accumulating.
- **Action item**: rename `hl_short_proxy` → `liq_cascade_proxy` (or similar) in code/docs to reflect it's multi-venue, so future readers aren't misled.

---

## CORRECTION 3 — Deprecated sleeves excluded from active roster

`TV_POLY_DEPRECATED_SLEEVES` (+ `TV_POLY_DEPRECATED_HIDE=true`) hides these — they are NOT active bleed; my DB query caught their historical events. Removed from all KILL/keep recommendations:

- **All 48 momo HEDGE + SELL variants** (v1 + v2, BTC/ETH/SOL, 5m/15m) — already deprecated. My "KILL HEDGE/SELL" is moot.
- **poly_updown sniper ×6** (btc/eth/sol 5m+15m) + sniper_INV ×2 — deprecated.
- **btc_5m_v3, btc_5m_v3_2, btc_5m_v3_3, sol_5m_v4** — deprecated (the surviving v3/v4 cells in the dashboard are the non-deprecated ones).
- **`volume` + `volume_INV_NIGHT` (all assets)** — deprecated on VPS3 2026-05-08. **⇒ INV_NIGHT is NOT active. The −$3,647 I reported was historical pre-deprecation loss, not current bleed.** Bug 8 KILL recommendation is moot (already done).

**Net effect**: the true active roster is the ~95 sleeves in the operator's dashboard (the ones with cards), not the 158 distinct sleeve_ids in the events table (which includes deprecated historical rows).

---

## RE-ANALYZED FINDINGS — point by point

### A. Implementation fidelity (unchanged — still valid)
- **sniper_v5: 75/78 faithful.** momo/shadow active families faithful.
- Spec↔code matches on gates, offsets, direction, spread_filter, anchors (ws_s), F7 RSI (simple-mean Wilder), Kelly tiers, prewindow, fade direction.

### B. Backtest engine is trustworthy
- BTC sniper replay: |Δfill_vwap|≈0.01, bt_WR≈live_WR. ETH sniper replay (rerun): |Δvwap|=0.008, bt_WR 54.5% vs live 53.4%. Momo: corr 0.61, **100% fired-direction match on shared slugs**, INV_NIGHT anti-edge reproduced.
- Divergences are real-world (bad sleeves / live-only gate bugs / data gaps), NOT engine error.
- **One caveat now**: backtests used legacy 2% fee; with the correct 0.07 curve they'd show modestly lower PnL. Re-run key validations on the curve.

### C. Confirmed ACTIVE bugs (3, down from 4 — fee retracted)
1. **btc_5m_q_parent15mslope_ts_imb5_v8** [KILL] — live −$352, replay −$0.43/tr; original +$6.20 backtest was over-optimistic (likely imbalance-gate look-ahead in the V8 search harness). Out-of-sample edge doesn't exist. **KILL + audit the search harness's imb5 gate for look-ahead.**
2. **V8_01/V8_02 gate mismatch** [FIX] — `btc_5m_l_1hrf_imb5_rf_v8` + `_ribbon_v8` run `g_grandparent_trend_with` live vs spec `g_1h_rf_with`. Un-validated combo (currently +$4/+$2, LOW_N). Restore `g_1h_rf_with` or re-validate as-built + update spec.
3. **vwap80 gate flip** [FIX] — 4 SOL 15m `*vwap80*` sleeves use `g_vwap_premium` (vwap≥0.55 floor) vs spec `vwap<0.80` ceiling. Different fire set; live net-negative (−$22 tightrib). Restore the ceiling gate.

### D. Already-FIXED (confirmed in live code)
- rv_60 scale (vol_high/vol_contracting) ✅ — pre-fix shadow data contaminated; btc_15m_btceth_diverg now fires.
- Synthetic-fill 0.5 placeholder ✅ — 3-tier book read deployed.
- Spread metric cross-token ✅ — now same-token bid-ask.

### E. Benign / non-bugs
- HEDGE/SELL fee inconsistency → see Correction 1 (1-line tweak).
- Kelly override not reset to None (latent), F7 RSI=50 skip (per-spec), V7_02 OFI stub (intentional 0-fire), 1 chainlink/CLOB outcome disagreement.

### F. Active roster performance (deprecated removed)

**Winners — KEEP/scale:**
| Sleeve | Lifetime PnL | WR | Note |
|---|--:|--:|---|
| shadow_ALL_5m_phase1_kelly | +$1,900 | 53% | ⭐ Kelly sizing edge, faithful |
| sol_5m_momo_v2_HOLD_f7 | +$567 | 60% | bt MATCH |
| btc_5m_momo_HOLD_f7 | +$330 | 54% | bt MATCH |
| eth_5m_v3_2 / v3_3 | +$292 | 60% | ETH v3 edge (active, non-deprecated) |
| shadow_ALL_5m_S3_prewindow | +$271 | 54% | prewindow edge |
| btc_15m_momo_HOLD_f7 | +$265 | 61% | bt +$8.5 |
| eth_5m_v4 | +$246 | 62% | |
| eth_15m_momo_v2_HOLD_f7 | +$234 | 60% | bt +$11.4 |
| eth_5m_v3 / v3_1 | +$221/+$193 | 54/57% | |
| shadow_ALL_15m_S4_prewindow | +$198 | 76% | |
| sol_5m_momo_HOLD_f7 | +$156 | 53% | |
| sol_5m_rf_tr_partial_mid | +$47 | 71% | top SOL sniper |
| sol_5m_btcf7_f7overb_v7 | +$54 | 71% | |
| sol_5m_j_2asset_v8 | +$36 | 77% | |
| btc_5m_up_b2_contrarian_v9 | +$81 | 67% | V9 working |
| btc_15m_ema50_ema800_off600_down (+_H) | +$26/+$12 | 82/89% | bt MATCH, _H HEDGE_LATE faithful |

**Active losers — KILL (deprecated already removed from this list):**
| Sleeve | Lifetime PnL | Reason |
|---|--:|---|
| sol_5m_v3_3 | −$483 | SOL v3 edge absent (active, non-deprecated) |
| btc_5m_fade_momo_v2 | −$482 | fade family loses |
| sol_5m_fade_sniper | −$468 | fade |
| btc_5m_q_parent15mslope_v8 | −$352 | bug #1 (active), over-optimistic backtest |
| sol_5m_fade_momo_v2 | −$376 | fade |
| sol_15m_fade_momo_v2 | −$340 | fade |
| sol_5m_v3_2 | −$327 | SOL v3 |
| btc_5m_v4 | −$323 | BTC v4 (active) |
| btc_15m_sniper_hod | −$287 | sniper_hod (HoD lists stale — bug #G below) |
| sol_5m_v3 | −$281 | |
| btc_5m_sniper_hod | −$267 | sniper_hod |
| eth_5m_momo_v2_HOLD_f7 | −$266 | eth5m v2 cell fragile |
| btc_5m_fade_sniper | −$246 | fade |
| eth_5m_momo_HOLD_f7 | −$238 | eth5m bare-F7 weak cell |

**fade family**: every fade loses except `eth_15m_fade_sniper` (+$81). Kill 5/6.

### F.1 Kelly / Prewindow / Fade backtest (now run on 0.07 curve)
Full results: `BACKTEST_KELLY_PREWINDOW_FADE_2026_05_29.md`.
- **Kelly — ✅ MATCH.** BT +$2,723 / 53.0% WR vs live +$1,729 / 52.8% WR; **98.5% direction agreement** on 399 shared slots. **Edge is ~89% sizing, ~11% base signal** — WR rises monotonically with fair_edge_bp tier (46.7→55.7%), but the mult=1 tier is a net loser; the **4× Kelly leverage on the high-conviction tail** is what pays. Flat-$25 counterfactual collapses live +$1,729 → **+$186 (+$0.30/tr)**. KEEP, but understand it's a **leverage-on-weak-edge** play — fragile if fair_edge_bp predictiveness degrades; watch the high tiers.
- **Prewindow S3/S4 — ⚠ DIVERGE (live-only edge).** Fire-sets barely overlap (S3 30/212, S4 1/14); the edge lives in the exact CLOB entry at the thin pre-window book, which canonical L25 cannot reconstruct at slot_start−60/−120. Canonical recompute over-fires and goes negative. So the prewindow edge is **genuine live pre-window microstructure** (not canonically validatable) AND S4 is small-n (14). KEEP-but-monitor; do not size up on backtest confidence.
- **Fade — ✅ MATCH (anti-edge confirmed).** 46.8% WR / −$1,782 across 639 fires, 5/6 lose. Anti-edge by construction (fades production signal + pays spread on ~50/50 markets). **KILL 5/6** (keep only eth_15m_fade_sniper, small-n +ve).
- **Fee sanity**: kelly on 0.07 curve = +$2,723 vs legacy-2% +$3,093 → **−12% (~$0.37/win) drag**; sign does NOT flip. Confirms the 0.07 curve is the right (harsher) model and the Kelly edge survives it.

### G. INVESTIGATE (not kill yet)
- **HoD top-8 lists stale** — monthly refresh job never built; all `*_hod` (sniper_hod bleeding) judged on stale lists. Build refresh, then re-judge.
- **momo_HOLD_f7 (bare F7)** ≈ breakeven; HANDOFF deploy spec stacked Markov+HoD. Add the Markov overlay to reach the validated +$4-5/tr.
- **V9 b2 DOWN leg** — UP works (+$81), DOWN loses (−$38). Drop/tighten DOWN on b2.
- **~20 too-new sniper_v5 sleeves** (1h26m run, 0 fires) — re-audit after 48h.

### H. Data/infra — CORRECTED (no real gaps)
- **SOL "55% NaN asks" = genuinely thin/empty book, NOT a data defect.** The canonical L25 faithfully records that SOL books are frequently empty on the ask side. So SOL thinness IS real market signal: a fire when the book is empty genuinely has no taker liquidity (live's 3-tier would fall to CLOB or skip). SOL sniper edge therefore depends on firing when liquidity is present. Do NOT "densify" — the data is correct. Re-evaluate SOL fills treating empty-ask as real illiquidity (a fire there should be scored as no-fill / deep-walk, matching reality), not as missing data.
- **1s-trade features ARE available** — `klines_1s.parquet` (450MB binance 1s) + precomputed `_results/{ta_indicators_1s (MACD), range_filter_1s, realized_vol_1s, traders_reality_1s}.parquet` + `trades_polymarket` (CVD) + L25 (fair_edge_bp). So kelly + prewindow + fade ARE backtestable. Backtest launched (`BACKTEST_KELLY_PREWINDOW_FADE_2026_05_29.md`). The earlier "NO_INFRA" conclusion was WRONG.
- Backtests must move to the **0.07 curve fee** (Correction 1) to match live — the only real methodology change.

---

## PRIORITY ACTIONS (corrected)

1. **KILL active bleeders**: btc_5m_q (bug), fade ×5 (keep eth_15m), sniper_hod (pending HoD refresh), SOL v3 cells (v3/v3_2/v3_3), btc_5m_v4. (HEDGE/SELL + INV_NIGHT already deprecated — no action.)
2. **FIX 2 gate mismatches**: V8_01/02 (1h_rf), vwap80 ×4 (ceiling).
3. **Re-baseline backtests on the 0.07 fee curve** (retire LegacyConfig for these markets).
4. **Build HoD monthly refresh**, then re-judge *_hod.
5. **Add Markov overlay** to momo_HOLD_f7 to hit validated numbers.
6. **Rename** `hl_short_proxy` → multi-venue liq label.
7. **Densify SOL L25** + add 1s-trade features to canonical.

## Source artifacts
All 8 agent reports + `live_dashboard_2026_05_29.txt` + `live_all158_stats.csv`. This doc is the corrected master; the fee/V9/deprecation sections here override the earlier two synthesis docs.

## END
