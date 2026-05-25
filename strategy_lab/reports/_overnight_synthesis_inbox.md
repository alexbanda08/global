# Overnight synthesis — 5m strategy state of play (2026-05-23)

_Digest of 14 reports. Caveman-terse. WR/n/sum on $25 notional, LegacyConfig (2%-on-profit, prod-matched), 28d Apr 24 → May 21._

## Per-report 1-liners

| # | Report | Strategy | n | WR | $/tr | sum | Status | Key gate / why |
|--:|---|---|--:|--:|--:|--:|---|---|
| 1 | `OVERNIGHT_STRATEGY_RUN_2026_05_23` | VWAP-cont + Fade-momo + Z-contra synthesis | 1,162+ | 81% avg | — | +$2,370 | **DEPLOY** | binance lead-time at LATE-fire (180-270s in) is near-deterministic vs chainlink settle |
| 2 | `MORNING_SUMMARY_2026_05_23` | Same — exec summary | 546 (top) | 86.3% | +$2.00 | +$1,090 | **DEPLOY** | BTC 240s + 5-10bps + M1V; OOS test_wr=89% > train 85% |
| 3 | `GATE_SEARCH_5M_2026_05_23` | 2^9 gate combos × 6 cells on fv_cvd_spike fires | 30-135/cell | 60-68% | +$4-8 | $150-600/cell | DEPLOY (per cell) | HoD+m5v+cvd_strong universal for BTC/ETH; SOL_v2 needs m5v+edge_2pp+cvd_strong (NO hod) |
| 4 | `VWAP_CONTINUATION_5M_2026_05_23` | v1 unfiltered — WR rises with offset & thr | 50-1k | up to 98.6% | varies | mixed | partial | outcome-WR very high at late offsets, but $/tr negative at smaller dev_tiers — need gates |
| 5 | `FADE_MOMO_5M_2026_05_23` | Fade momo when mag_ratio>3 (BTC+ETH only) | 164 | 67-71% | +$7-9 | +$1,264 | **DEPLOY** | Extreme momo signals = exhaustion. SOL stays random (~52%) |
| 6 | `Z_CONTRA_5M_2026_05_23` | mlmodelpoly z-contra port (favorite-dip + binance disagree) | 183 | 55.2% | +$3.24 | +$594 | PAPER-ONLY | ETH 30s only; buys cheap underdog so big payoff per win compensates sub-60% WR |
| 7 | `ANCHORED_VWAP_FADE_5M_2026_05_23` | Fade (bet AGAINST VWAP extension) | 31-39 | 8-23% | — | — | **DEAD** | The fade direction is wrong — confirms VWAP extensions CONTINUE, don't revert |
| 8 | `FV_CVD_SPIKE_BACKTEST_2026_05_23` | mlmodelpoly fair-value Φ(z) + CVD agree + 5s spike | 1,162 | 51.3% | +$0.15 | +$171 | **partial** | edge>=2pp+cvd_agree+no-anti-spike only helps BTC 15m (WR 64% +$659); fails on 5m cells |
| 9 | `INDICATOR_SURVEY_2026_05_22` | Survey mlmodelpoly + dexorynlabs | — | — | — | — | research | 7 features ported: fair_up, microprice, RVOL, vwap_15m, sigma_15m, PM dip, z_contra |
| 10 | `NEW_STRATEGIES_PROPOSAL_2026_05_22` | S1-S7 specs (mag-cap, dir-HoD, cell-stack, Kelly, cooldown, wallet-mimic) | — | — | — | — | spec | S1+S2 evidence already in data; S4 Kelly + S5 cooldown UNTESTED |
| 11 | `MINT_AND_SELL_CVD_TIMING_2026_05_23` | V2 maker + 1s CVD overlay | 7,490 | varies | — | -$782 sample | **DEAD as gate** / V3 redesign needed | CVD DIRECTION predicts held-side (27% fills → 55% losses), but \|CVD\| MAGNITUDE doesn't separate adverse rate — need asymmetric one-sided posting |
| 12 | `VWAP_CONT_V2_GATED_2026_05_23` | v1 + F7/M1V/cross-asset gates | 539 (top) | 86.6% | +$2.10 | +$1,133 | **DEPLOY** | M1V+cross_partial at BTC 240s 5-10bps is the headline winner |
| 13 | `VWAP_DRAWDOWN_LIVEMIMIC_2026_05_23` | Top-5 VWAP-cont robustness check | 64-546 | 73-93% | — | — | **validates DEPLOY** | OOS WR ≥ train WR for 3 of 5 configs; max DD ≤ 35% sum; live-mimic loses only 7.3% |
| 14 | `TV_AGENT_VWAP_CONTINUATION_SPEC_2026_05_23` | Production spec for 5 VWAP-cont sleeves | — | — | — | — | **ship-ready** | New aux fields: vwap_15m_anchored, dev_bps, m1v_regime, cross_asset_devs |

## Synthesis

### CONFIRMED deployable 5m edges
- **VWAP Continuation late-fire** — binance dev from 15m-anchored VWAP, bet WITH, gated by M1V Markov + optional F7/cross-asset. 5 sleeves, ensemble 81% WR, +$2,370/28d. Production spec written (#14).
- **Fade extreme momo (BTC+ETH only)** — when mag_ratio>3.0 on momo fires, FLIP direction. +$1,264/28d. 4-line patch.
- **HoD+m5v+cvd_strong stack (all 6 cells)** — gate_search confirmed every 5m momo/momo_v2 cell has a deployable stack (n≥30, WR≥60%). Cell-specific (SOL_v2 drops hod, picks m5v+edge_2pp+cvd_strong).
- **Z_contra ETH 30s** — paper-only, smaller stake. 55% WR but cheap-underdog payoff yields +$3.24/tr.

### Tested USELESS — do NOT retry
- **Anchored VWAP FADE (mean-reversion)** — Backwards-confirmed: WR 8-23%. Extensions continue, don't revert.
- **Z_thresh 1.0-2.0 binance disagreement alone on BTC/SOL** — all sub-50% WR.
- **Symmetric |CVD| magnitude gate on Mint-and-Sell V2** — selectivity ≤ 0.23pp, cuts winners ~= losers. Requires V3 redesign (asymmetric posting), not a gate tweak.
- **Fair-value edge alone (Φ(z) − vwap)** on 5m — only BTC 15m benefits (WR 64% with stack); 5m cells stay negative.
- **Fade momo on SOL** — random ~52% WR even at mag>3 (SOL signals aren't exhausted at high mag).
- **Anti-spike (5s spike sanity) as standalone gate** — n too small (3-76); flag is rare.

### UNTESTED / PARTIALLY-TESTED — build next

**A. Feature-stack gaps (no script exists yet)**
1. **CVD + MACD combination** — neither CVD slope nor MACD-on-binance-1s tested as a momentum-confirm pair on the 5m universe. We have `cvd_strong` in gate_search but no MACD overlay anywhere.
2. **MACD on 1s binance vs the 5m fire** — 1s feed is now in `binance_1s_28d.parquet` (5.5M rows). Compute MACD(12,26,9) on 1s or 5s rebars; bucket fires by MACD histogram sign vs bet direction.
3. **Microprice (B from indicator survey)** — never written into engine_v2. Could improve fill estimates for VWAP-cont entries (which fire at offset≥60s into a slot, where L25 books are deep).
4. **RVOL × Markov stack** — RVOL never wired as a gate. Hypothesis: regime + rising RVOL = real momentum (not just floor-of-quiet).
5. **PM dip detector (F)** — never implemented. Detect <3s drops on PM mid while binance flat → buy the dip. Different fire timing than VWAP-cont (within first 60s of slot).
6. **Sigma_15m as regime FLOOR gate** — proposed in #9 but never benched. Skip fires when sigma_15m below p20.

**B. Untried combinations (each row is a NEW backtest to write)**
- VWAP-cont × CVD-slope agreement (does CVD direction confirm the extension?)
- VWAP-cont × MACD histogram > 0 for UP / < 0 for DOWN
- VWAP-cont × cross-asset MACD agreement (vs the current cross_partial which uses dev_bps only)
- Z_contra × Markov regime (z_contra never gated by M1V/M5V)
- Fade-momo × CVD contra (does CVD divergence from price confirm exhaustion?)
- Fade-momo × MACD bearish crossover
- Mint-and-Sell V3 asymmetric posting × 1s CVD direction (the redesign called out in #11)
- Microprice-based entry vs current entry_vwap on VWAP-cont top-5 sleeves (live-mimic refill diff)
- 1s spike-then-pause (binance moves >X bps in 5s then flatlines 15s) as standalone entry signal
- Kelly sizing (S4) on top of VWAP-cont — flat $25 → conviction-scaled bet size, measure Sharpe uplift
- Confidence-decay cooldown (S5) on losing streaks across all deployable sleeves
- Direction-asymmetric HoD (S2) — split HOD_TOP8 by UP/DOWN per cell; data exists, never benched

**C. Cells / windows never explored**
- All VWAP-cont and gate_search work focused on 5m. 15m has only FV+CVD+spike (BTC 15m WR 64% with stack). No VWAP-cont 15m, no fade-momo 15m, no z_contra 15m benched on this 28d window.
- Mid-fire offsets (270s into a 15m slot, 600s into a 15m slot) untested.
- 1s feature × 15m slot — only 5m has been overlaid with 1s CVD/spike features.

**D. Specific top-priority CVD + MACD + Markov + microstructure + 1s combos NOT YET TRIED**
1. VWAP-cont (BTC 240s 5-10bps M1V) + CVD-slope_30s agreement gate (does +$1,090 grow or shrink?)
2. VWAP-cont + MACD(1s) histogram agreement
3. Fade-momo (BTC+ETH mag>3) + CVD-slope contra-to-price (exhaustion confirmation)
4. VWAP-cont + microprice-better-than-mid-by-X (book imbalance entry)
5. Cell-specific stack from gate_search × VWAP dev_bps (e.g., HoD+m5v+cvd_strong + dev_bps>5)
6. Markov M5V on VWAP-cont (only M1V tested; M5V is the slower regime, may filter different fires)
7. CVD + MACD double-confirm on Fade-momo for SOL (the cell where mag>3 fade failed — maybe order-flow confirmation rescues it)
8. RVOL × M1V × dev_bps triple stack on VWAP-cont (volume-backed regime-confirmed extensions)

### Risk flags
- Live-mimic in #13 uses the HYPOTHETICAL 0.07·p·(1-p) fee curve, NOT prod-actual. Per CLAUDE.md, production runs 2%-on-profit-only (verified vs 25,900 resolutions). LegacyConfig $/tr is the deploy reality.
- All "WS-only" readings since Phase 18.6 Wave 1 mean book-source no longer matters for live-vs-backtest gap.
- All n≥30 cells exist, but n=64 (SOL 60s) and n=50 (ETH 270 15-20bps) are thin — treat as paper-only.
- 1s binance feed is fresh (`binance_1s_28d.parquet`, 5.5M rows). Re-use for any CVD/MACD/spike work. Don't re-pull.
