# Strategy C + D — Perps signals (HL liqs + Funding/OI)

**Session:** 2026-05-16. Discovery batch on perps-derived signals.
**Universe window:** 2026-04-24 → 2026-05-16 (chainlink-resolved BTC/ETH/SOL × 5m/15m). Sampled 2,000/asset/tf → 12,000 markets per strategy.
**Conventions:** UTC us. `outcome` = chainlink. `ws_s = slug_suffix - window_s`. Fee: 2% on profit only.

## DATA COVERAGE CAVEATS (read first)

| dataset | usable window | overlap w/ res window | impact |
|---|---|---|---|
| `hyperliquid_liquidations_full` | May 2025 → Feb 2026 | **0 days** | Cannot use clean liq flag. |
| `hyperliquid_liquidations_30d` | Apr 16 → May 16 2026 | full | Used as proxy. NO `Liquidated/Auto-Deleveraging` `dir` rows in 30d file — it's HL fills for tracked users, not market-wide liqs. Keyed off `side` A/B per spec. |
| `binance_metrics` (OI, L/S ratio) | Apr 27 2025 → Apr 27 2026 | **3 days** (Apr 24-27 of res) | Asof beyond Apr 27 returns stale Apr 27 values → OI delta_1h ≈ 0 for ~95% of fires. |
| `hyperliquid_funding` | Jan 30 → May 15 2026, 1h grain | full | Clean. |

Net: Strategy C runs on a proxy. Strategy D's OI/LS gates are stale-asof for >85% of fires; only HL-funding gate is fully usable.

---

# Strategy C — HL liquidation cascades

**Hypothesis:** Long liqs (forced sells) → DOWN; short liqs (forced buys) → UP. `net = short_liq_notional - long_liq_notional`. Fire UP if `net > +T`, DOWN if `net < -T`.

**Setup:** spec mapping `side='A'` = long liq, `side='B'` = short liq. Lookback 5/10 min. Thresholds {$10k, $50k, $100k, $500k, $1M, $5M}. Variants 5m@ws+120, 15m@ws+120, 15m@slot_end-60 (LATE).

**Results (n≥200, ALL-asset):**

| variant | thr_usd | n | hit |
|---|---:|---:|---:|
| 15m_late_lb10 | 50,000 | 215 | **0.558** |
| 15m_late_lb10 | 10,000 | 323 | 0.551 |
| 15m_ws120_lb10 | 10,000 | 318 | 0.506 |
| 15m_ws120_lb10 | 50,000 | 217 | 0.502 |
| 5m_ws120_lb10 | 50,000 | 206 | 0.451 |
| 5m_ws120_lb10 | 10,000 | 339 | 0.451 |

**Verdict: INCONCLUSIVE.** Best hit 55.8% n=215 → 95% CI ≈ [49%, 62%]. Not separable from chance. Compounded by data proxy. Code ready: set `prefer="full"` in `build_liq_arrays()` after refresh.

---

# Strategy D — Funding / OI regime overlay

**Hypothesis:** regime gates improve binance ret_2m baseline.

**Variants:** `baseline` (sign of ret_2m); `gate_oi` (continuation); `gate_ls_crowd` (extreme L/S); `gate_hl_cross` (HL funding crossed zero last 4h).

**Anchors:** 5m@ws+120, 15m@ws+120, 15m@slot_end-60 (LATE).

**Results (n≥200, ALL-asset):**

Baseline:
| block | thr | n | hit |
|---|---:|---:|---:|
| **15m_late** | 0.0005 | 1594 | **0.629** |
| 15m_late | 0.0002 | 3537 | 0.604 |
| 15m_late | 0.0001 | 4486 | 0.592 |
| 15m_late | 0.0000 | 5287 | 0.585 |
| 15m_ws120 | 0.0001 | 4766 | 0.508 |
| 5m_ws120 | 0.0001 | 4660 | 0.497 |
| 5m_ws120 | 0.0005 | 1873 | 0.476 |

Per-asset 15m_late thr=5bp: BTC n=395 hit=0.630, ETH n=537 hit=0.624, SOL n=662 hit=0.631.

gate_oi: hurts vs baseline (fewer trades, lower hit).
gate_hl_cross: 0.50-0.51 random.
gate_ls_crowd: stale-data artifact, discard.

**Verdict:**
- **NULL on every regime gate.** OI delta / L/S ratio / HL funding cross zero do not improve momentum baseline.
- **ALPHA on late-entry momentum (LATE-15m baseline)** — but this is late-entry momentum, NOT a regime gate. Same finding as strat_A2 (CVD) and strat_B (cross-venue) 15m_late blocks — late-entry momentum is the dominant non-microstructure edge.

---

# Combined summary

| strategy | best block | n | hit | verdict |
|---|---|---:|---:|---|
| C: HL liqs | 15m_late lb=10min T=$50k | 215 | 0.558 | INCONCLUSIVE (proxy data) |
| C: HL liqs | 5m_ws120 | <340 | 0.45 | NULL |
| D: gate_oi | 15m_late thr=1bp | 310 | 0.603 | gate hurts vs baseline |
| D: gate_hl_cross | any | ~1820 | 0.50 | NULL |
| D: gate_ls_crowd | any | 2000 | 0.49 | NULL (data stale) |
| **D: baseline (late momo)** | **15m_late thr=5bp** | **1594** | **0.629** | **ALPHA (late-entry, not a gate)** |

## Key code/data findings

- `hyperliquid_liquidations_full` does NOT cover Apr-May 2026 (gap Nov 2025 → Feb 2026). Storedata refresh needed.
- `binance_metrics` ends Apr 27 2026 → asof beyond returns stale values. Storedata refresh needed.
- HL liq side semantics: `_full` uses `dir` column ('Liquidated * Long' = long-liq), NOT `side`. Strategy script handles both files.
- Bug fixed: `binance_metrics` numeric cols are string-decimals — needs `pd.to_numeric(errors='coerce')`.
