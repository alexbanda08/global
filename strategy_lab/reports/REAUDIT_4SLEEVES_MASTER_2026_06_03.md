# Re-audit — 4 deployed sleeves vs fresh canonical (2026-06-03)

Same rigorous treatment as the S4 re-audit: found creation docs, confirmed the live gate
logic, faithfully reproduced each backtest + gates on canonical **Apr 24 → Jun 1**, and
ground-truthed against the **actual live fires** (VPS3 `poly_updown_resolution` events).
Per-sleeve detail: `REAUDIT_BTC15M_MOMO_EMADOWN_2026_06_03.md`, `REAUDIT_SOL5M_MOMOV2_2026_06_03.md`,
`REAUDIT_ETH5M_HURST_2026_06_03.md`.

## Master table — backtest vs LIVE
| sleeve | engine | LIVE n/WR/PnL | backtest n/WR/$tr | binom_p | OOS / by-week | reproduces live? | verdict |
|---|---|---|---|---|---|---|---|
| **btc_15m_ema50_ema800_off600_down** | sniper_v5 DOWN | 175 / **82.2%** / +$176 (83%/82% stable) | 1105 / 75.0% / +$1.11 (lgc) | **<1e-6** | OOS WR 73.1% holds; 6/7 wks + | **YES** (live +6pp = tighter live spread) | ✅ **ROBUST — validated, fleet's best** |
| **eth_5m_l_ema50_hurst_grandparent_v8** | sniper_v5 | 270 / 69.3% / +$139 (74%/66%) | IS 467/82.0%/+$0.97; OOS-known 78/73.1%/+$72 | IS 6e-47 | decay 82→73→69% gradual | **YES** (conditional) | ✅ **ROBUST — validated, keep** |
| **sol_5m_momo_v2_HOLD_f7** | momo_v2+F7 | 171 / 59.6% / **+$676** (all wks +) | **native-10Hz** 358/49.4%/−$0.75 (−$268); live-win 106/54.7% | 0.60 (full) | IS −$456, OOS +$137 | **PARTIAL — execution + live-selection edge** | ⚠️ **LIVE-POSITIVE, not backtest-validated (native-confirmed)** |
| **btc_15m_momo_HOLD_f7** | momo_v1+F7 | 78 / 57.7% / +$286 (one big wk) | **already native-10Hz** 107/53.3%/+$1.41 | **0.281 (n.s.)** | train breakeven, ALL pnl in last 40% (W22 +$162) | **NO** (structurally) | 🔶 **FRAGILE — noise-driven, don't size up** |

> **10Hz-law re-test (2026-06-03):** `btc_15m_momo_HOLD_f7` was **already** run at native 10Hz (`bt_momo_f7.py` uses `subsample_1hz=False`) — verdict unchanged. `sol_5m_momo_v2` was the only 1Hz one; **re-ran at native 10Hz → result essentially unchanged** (−$267.96 vs −$267.68; same 358 fills, 49.4% WR). Native loaded ~2× the book rows (median 257 vs 135 per 300s window — the flip took effect) but did NOT close the backtest↔live gap. Root cause is therefore **NOT subsampling**: (1) SOL canonical L25 is natively sparse (~0.86 snapshots/s) → **43% of fires have no fillable book at fire_us** (fill_rate 57.3%, unchanged by native); (2) live places only **171** of the 625 candidate signals — a selective subset (HOD/M5V/per-host feed-timing) winning 60%, which the broad 358-fill backtest doesn't isolate. The SOL edge lives in live execution + live-only selection, unreproducible from canonical at any sampling rate. LiveMimic (0.07-curve) still places 0 fills — SOL books genuinely have <25 events/window. Going forward, `subsample_1hz=False` enforced on all tests per CLAUDE.md law.

## The spectrum (this is the point)
Unlike S4 (a coin-flip that reverted), these 4 span the full reproducibility spectrum:

**✅ VALIDATED (backtest reproduces live, statistically real):**
1. **btc_15m_ema50_ema800_off600_down** — the standout. Backtest n=1105, WR 75% (binom_p <1e-6), OOS holds at 73%, 6/7 weeks positive; live is even better (82%, stable both weeks — the live cross-token spread filter is tighter than the backtest's). The entry-vwap **band [0.15,0.93] lifts $/tr +$1.11→+$1.84** (the V10 case). This is a genuine, validated, robust edge — the best in the fleet.
2. **eth_5m_l_ema50_hurst_grandparent_v8** — gate stack faithful (3 AND gates: `tr_above_ema50` + `hurst_trending≥0.50` + `grandparent_trend_with`, offset 60s). IS 82% (circular), known-OOS 73% matches live 69%; gradual decay, not a cliff. The **Hurst gate is load-bearing** (drop it → 47.6% coin-flip). Validated; minor risk = entry-vwap compression (add `evcap≤0.70` if it continues). Caveat: a clean fresh-OOS needs 1s klines for hurst recompute (data gap).

**⚠️ LIVE-POSITIVE but EXECUTION-dependent (backtest can't validate):**
3. **sol_5m_momo_v2_HOLD_f7** — biggest live $ winner (+$676) and live-positive all 3 weeks, BUT the backtest is breakeven-to-negative (full −$0.75/tr, 49.4% WR). The gap is a **data artifact, not a logic break**: SOL L25 has ~55% ask-NaN + we can only load it at 1Hz (memory) → backtest places 57% fill-rate vs live's ~100%; live fires on liquid 10Hz moments the 1Hz backtest never sees (W21: live 93 fires vs backtest 66). Signal logic verified correct. **It's a real execution/microstructure edge we can't reproduce offline** — keep it deployed, but DO NOT size from backtest; use the live $/tr as the floor. (Definitive validation needs a native-10Hz SOL run on a high-RAM box.)

**🔶 FRAGILE / noise-driven:**
4. **btc_15m_momo_HOLD_f7** — net live +$286 but **not statistically significant** (backtest binom_p=0.281, CI spans zero) and **structurally unstable**: backtest train half breakeven, 100% of PnL in the last 40% (W22 alone +$162); W17 went 0-for-8. Both live and backtest are riding the same favorable late window. Monitor; do not size up. (Consistent with the prior FIDELITY_B finding: bare-F7 HOLD is breakeven without the Markov overlay.)

## Bottom line
- **2 of 4 are genuinely validated** (ema_down, eth_hurst) — backtest reproduces live, real edge, keep + scale the ema_down band.
- **1 is a live-only execution edge** (sol momo_v2) — real money but unreproducible offline due to SOL book gaps; keep, don't backtest-size.
- **1 is fragile/insignificant** (btc momo HOLD) — one good window, not an edge; monitor.
- Method holds: grounding each against live + faithful reproduction separates the real edges (sniper_v5 trend/hurst lines) from the noise (momo HOLD) and the execution-only (sol momo_v2). The sniper_v5 trend family (ema_down, eth_hurst) is where the durable alpha is.

Artifacts: the 3 per-sleeve reports + `strategy_lab/_sleeve_reaudit_2026_06_03/*`, `meta_classifier/reaudit_sol5m_momov2_2026_06_03.py`, `_results/reaudit_sol5m_momov2_2026_06_03/*`.
