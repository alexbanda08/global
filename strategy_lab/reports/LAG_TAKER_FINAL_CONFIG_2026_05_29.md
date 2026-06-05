# Lag Taker — Final Config (Buy→Wait→Hedge → distilled to directional lag taker) — 2026-05-29

Consolidation of the 4-phase research on the "Buy→Wait→Hedge lock-the-lag" idea. The lock/hedge mechanic is dead; the surviving edge is a **directional binance→chainlink oracle-lag taker, hold-to-resolution**. This doc is the deployable config.

Source phases: `LEG2_REPRICING_STUDY`, `LAG_TAKER_EDGE_RESEARCH`, `LAG_TAKER_GATES`, `LAG_TAKER_STOPLOSS_SIZING` (all 2026-05-29).

---

## 0. What survived

| Component | Verdict |
|---|---|
| Leg-2 complete-set LOCK/HEDGE | ❌ **DEAD** — UP/DOWN asks anti-correlated −0.90, sum pinned ~1.01-1.02, lockable fraction 0.0000 at any latency. Retired. |
| Leg-1 DIRECTIONAL lag taker | ✅ **REAL edge** — survives 0.07 fee, monotonic dose-response, OOS-significant |

The whole strategy reduces to: **buy the binance-leading side when it's stale-cheap, hold to resolution.**

---

## 1. The edge (foundation)
Binance leads; chainlink/Polymarket lag. When binance moves ≥3bps in the pre-fire window, the market resolves in that direction 63-69% of the time (WR rises with move size — the lag signature). Buying the leading side at the stale L25 ask captures the gap.

Dose-response (base BTC+ETH, hold-to-resolution, 0.07 fee):
| |delta_bps| | WR | $/tr |
|---|--:|--:|
| ≥2 | 59.8% | — |
| ≥3 | 63.3% | +$2.39 |
| ≥5 | 67.7% | +$3.38 |
| ≥8 | 69.1% | (n collapses) |
| **≥12** | **56% — REVERSES, −$4.17/tr** ← huge moves already priced; CAP here |

---

## 2. RECOMMENDED DEPLOY CONFIG

```
# --- Universe ---
assets          = {BTC, ETH}          # SOL EXCLUDED (net drag, t=-0.5)
timeframes      = {5m, 15m}           # 15m cleaner than 5m
direction       = follow binance lead (buy the leading side)

# --- Entry signal (leg-1) ---
signal          = oracle_lag.price_delta_bps  (binance move over pre-fire window)
entry_gate      = 3 <= |delta_bps| <= 12       # >12 is -EV (priced in)
fire_time       = slot_start + 5s
fill            = L25 book walk $25, +85ms latency, 0.07 winner-only fee
                  pnl_won = (1-vwap)*shares*(1 - 0.07*vwap); loss = -vwap*shares

# --- Gates (R5, most robust) ---
gate_tod        = exclude 18-23 UTC          # OOS t=3.29 standalone
gate_confluence = other asset (BTC<->ETH) leading SAME direction >=3bps in overlapping window
gate_depth      = top-ask resting $ >= median   # OOS-robust (+$0.67/tr)
spread_filter   = <= 0.05  (DO NOT tighten — edge lives in dislocated wide books; tighter = inverse)

# --- Exit ---
exit_primary    = hold to resolution
stop_loss       = binance-reversal >= 10bps against entry dir -> sell at L25 bid (0.07 fee on sale)
                  # cuts maxDD -32%, EV cost only -$0.36/tr, Sharpe improves
                  # NO price-floor stop (TRAP — realizes recoverable noise dips)

# --- Sizing ---
sizing          = confidence-proportional: notional ∝ (bucket_WR - mean_vwap)
                  # beats flat + Kelly-tiering (kelly over-bets the -EV >12bps tail)
                  base $25; verify book-walk slippage before scaling >$50
```

### Expected performance
| Config | n/day | WR | $/tr | IS t | OOS t | maxDD |
|---|--:|--:|--:|--:|--:|--:|
| Base (BTC+ETH, ≥3bps, hold) | ~59 | 65.4% | +$2.39 | 4.06 | 2.46 | −$394 |
| **R5 (ex18-23 + confluence)** | **~22** | **68.1%** | **+$3.42** | 2.45 | **2.78** | **−$227** |
| R7 (ex18-23 + δ≥5) sharper | ~11.5 | 71.8% | +$4.73 | 3.15 | 2.39 | — |
| R5 + reversal-stop + conf-sizing | ~22 | ~68% | **~+$3.0-3.4** | — | — | ~−$227 to −$452, Sharpe 0.136 |

**Pick R5** as the deploy base — best volume×robustness (OOS t=2.78, maxDD cut 42% vs base). R7 for a sharper/lower-volume sleeve.

---

## 3. What was KILLED (don't implement)
- **Leg-2 lock/hedge** — dead at any infra (§0).
- **Price-floor stop-loss** — trap; realizes recoverable dips.
- **Spread-tightening** — inverse; edge is in wide/dislocated books.
- **1s RSI/MACD/CCI gates** — no-ops (~98% agree with the move; the move IS the signal).
- **Kelly-tiered sizing** — over-bets the −EV >12bps tail; use confidence-prop instead.
- **delta_bps > 12** — net-negative (priced in).
- **SOL** — net drag.

---

## 4. Caveats / open risks
- Sizing tested linear-scaled; verify $>50 book-walk slippage before scaling.
- Confidence buckets fit in-sample; top-bucket (>12bps) inversion is small-n (32) — monitor.
- Reversal-stop worst-5% still −$25 (can't outrun fastest reversals).
- OOS windows are short (days). Re-validate on a longer window before sizing up.
- Edge depends on binance→chainlink lag persisting; if Polymarket/oracle tightens, edge decays.

---

## 5. Next steps
1. **Deploy spec for TV** — this is a NEW strategy line (distinct from sniper_v5 / momo). Needs: `oracle_lag.price_delta_bps` signal (already on VPS3), the R5 gates, reversal-stop exit, confidence-prop sizing, paper-mode shadow at $5-25.
2. **Live shadow A/B**: R5 vs R7 vs base, 2-4 weeks, compare to these backtest numbers.
3. **Longer-window re-validation** before any real-money sizing.

## Artifacts
- Fire universes: `lag_taker_fires_2026_05_29.parquet` (3,653), `lag_taker_fires_gated_2026_05_29.parquet` (R5, n=477), `lag_taker_fires_enriched_2026_05_29.parquet`
- Reports: LEG2_REPRICING_STUDY, LAG_TAKER_EDGE_RESEARCH, LAG_TAKER_GATES, LAG_TAKER_STOPLOSS_SIZING (all 2026-05-29)
- Scripts: `strategy_lab/directional/*`

## END
