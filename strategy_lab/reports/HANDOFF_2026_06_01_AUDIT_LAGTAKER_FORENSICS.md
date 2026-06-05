# Session Handoff — 2026-06-01 — Sleeve audits · Lag-taker · Cyclops · Silent-sleeve forensics · LAGV2 bug

Read this first for current state. Big multi-thread session: full live-vs-backtest audit of the 132-sleeve shadow fleet, a new deployable strategy (lag-taker / FAST_TAKER_LAGV2), competitor-bot decode + wallet hunt, and forensics that found **6 distinct production bugs** (5 fixed/partly-fixed, several TV fix-specs pending).

---

## A. DONE this session

### A1. Full fidelity + backtest-vs-live audit of all 132 shadow sleeves
- **141/147 sleeve definitions faithful to spec.** Reports: `FIDELITY_AUDIT_{V5_V9,V6_V7,V8_H,VL,MOMO_SHADOW}_2026_06_01.md` (note: some are dated 05_29).
- Master comparison: `MASTER_LIVE_VS_BACKTEST_2026_05_29.md` + corrected `AUDIT_FINAL_CORRECTED_2026_05_29.md`. Backtest engine TRUSTWORTHY (BTC/ETH sniper replay |Δvwap|≈0.01; momo 100% direction-match on shared slugs). SOL canonical L25 is **genuinely thin** (empty asks = real market, not a data gap).
- **Fee model: 0.07·p·(1−p) winner-only curve is CORRECT** (operator-confirmed) — our older backtests used legacy 2% (over-optimistic). Re-baseline future backtests on the 0.07 curve.
- Spread-loosen sims (`SPREAD_LOOSEN_SIM_*`): 11 sleeves would benefit (ETH 5m mostly); SOL 5m + BTC 5m do NOT (KEEP tight).

### A2. New strategy — Lag Taker (`FAST_TAKER_LAGV2`)
4-phase research (`LAG_TAKER_FINAL_CONFIG_2026_05_29.md` + LEG2_REPRICING / LAG_TAKER_EDGE / LAG_TAKER_GATES / LAG_TAKER_STOPLOSS_SIZING):
- **Leg-2 complete-set lock/hedge = DEAD** (UP/DOWN asks anti-corr −0.90, sum pinned ~1.01, 0% lockable at any latency). Retired.
- **Leg-1 directional binance→chainlink lag taker = REAL** edge: WR ~68%, +$3.0-3.4/$25, OOS t=2.78. BTC+ETH only (SOL drag). 15m cleaner than 5m. delta_bps >12 REVERSES (cap it). Best stop = binance-reversal ≥10bps (cuts maxDD 32%; price-floor stops are a TRAP). Sizing = confidence-proportional (Kelly over-bets the −EV >12bps tail).
- Deploy spec written: `TV_AGENT_SPEC_FAST_TAKER_LAGV2_2026_05_29.md`.

### A3. Cyclops Telegram bot — decoded + wallet found
- `CYCLOPS_SIGNALS_DECODE_2026_05_29.md`: advertised 85% WR, **real chainlink truth 52-64%** (coin flip), −EV after fees, "follow the book off 50¢", PTB indicator is fake. Not worth copying.
- `CYCLOPS_WALLET_HUNT_2026_06_01.md`: **the executor wallet = `0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c`** (52/53 signals, 100% signaled-direction, +1s latency, 100% BTC 5m, lifetime −$217). Reusable harvester: `wallet_hunt/harvest_*` + `data-api.polymarket.com/trades?market=<slug>` → proxyWallet matching.

### A4. Silent-sleeve forensics — 31 never-fired sleeves
`SILENT_SLEEVES_FORENSICS_MASTER_2026_06_01.md`: NONE are dispatch bugs (all evaluate). Split: **4 real bugs (15 sleeves)** + 1 dead stub + 12 low-base-rate. Key lesson: the dashboard "dominant skip reason" = first-failing gate in declaration order, NOT the binding constraint — the real bugs were None/empty features UPSTREAM of the gates.

### A5. Infra wallet type (Ireland `85.137.174.152`)
- Live directional trading = **plain EOA, signature_type=0** (secrets: `poly_signer_private_key` + `poly_proxy_address` holding the EOA's own addr; encrypted, tv_master). NOT a Safe/proxy like the bots.
- Mint-sell maker (SHADOW only) = separate **POLY_1271 wallet, signature_type=3**.
- Ireland LIVE: 3 momo sleeves ($1/$0.20) + Kalshi KXBTC15M (the ema50_ema800 lag sleeve).

### A6. LAGV2 always-UP bug (the big find)
`LAGV2_ROOTCAUSE_ALWAYS_UP_2026_06_01.md`: all **8 poly_fast_taker sleeves fire 100% UP / 0% DOWN** → coin-flip (btc_15m 13% on n=15). Root cause: the live gates read **feed-vs-chainlink-oracle basis** (`oracle_lag.price_delta_bps`, pinned positive) instead of the backtested **intra-window binance return** (`binance(slot_start+offset)/binance(slot_start)−1`, symmetric ±). NOT contrarian — wrong signal. Backtest fires 50/50 UP/DOWN at 68% WR.

---

## B. OPEN — TV fix-specs pending implementation (priority order)

| Spec | Covers | Status |
|---|---|---|
| **`TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md`** | ALL 8 poly_fast_taker (both gates `g_oracle_lag_with` + `g_oracle_lag_bps_ge`): swap to binance-return signal + history reset | 🔴 PENDING. Cleanest = 1 controller change feeding both gates. Acceptance #1 = direction split ~50/50. Consider killing the 2 `a25_merge` (merge mechanic dead). |
| **`HANDOFF_HURST_HLCASCADE_FIX_2026_06_01.md`** | (1) SOL 5m hurst: `g_hurst_reverting` 0% live vs 39% backtest — likely **cold-start warmup** (5h for 5m hurst, panel rebuilt empty each restart) → backfill VolHurst deque on boot. (2) hlcascade: bybit/bitget liq collectors EMPTY → repair. | 🔴 PENDING. FIX 4 hit the gate not the panel — redo at `vol_hurst.py`. |
| **`TV_AGENT_FIX_SILENT_SLEEVES_2026_06_01.md`** | vwap aux (✅done), overlay features+m5v (✅done, m5v confirmed working), liq feed (❌), hurst (❌) | partial — see POSTFIX below |
| `TV_FIX_SOL_ANTIGATE_2026_05_27.md` | SOL anti-gate (g_poly_aggressor_anti) on 20 SOL sleeves | status unverified — check if deployed |
| `SHADOW_DEPLOY_SPEC_V9_AND_VL_2026_05_27.md` | V9 (10) + VL (11) — already deployed; some V9 silent (hlcascade feed) | deployed |

### Post-fix verification (`POSTFIX_VERIFICATION_2026_06_01.md`)
TV deployed 4 silent-sleeve fixes (uncommitted working-tree). Result: **vwap ✅ + m5v ✅ work; hurst ❌ + hlcascade ❌ still broken.** 9 of 15 bug-sleeves now fire; 4-6 still won't until hurst-panel + liq-feed fixes land.

### Other open threads
- **Commit the TV working-tree fixes** — currently uncommitted on VPS3 (lost on a bad restart).
- **Lag taker**: longer-window OOS re-validation before any real-money sizing; then deploy `FAST_TAKER_LAGV2` (after its signal is correct — note the LAGV2 spec describes the INTENDED signal; the live impl had the wrong-signal bug → the fix spec B1 supersedes).
- **HoD monthly refresh job** — never built; `*_hod` sleeves run on stale top-8 lists.
- **Re-audit the 12 low-base-rate 15m sleeves** in 7-14d (deployed on thin n=8-12 lockboxes — consider killing n<20).
- **Deploy-time guard**: assert every shadow sleeve's gate features non-None AND in-range at eval (would have caught all the silent bugs).
- **Roster cleanup**: KILL list from the master audit — INV_NIGHT ×6 (deprecated but still firing at night, −$3.6k), fade ×5, sniper_hod, BTC/SOL v3/v4, btc_5m_q (−$352, over-optimistic backtest).

---

## C. Data state (see top of CLAUDE.md)
Canonical refreshed 2026-06-01 09:11 UTC (Apr 22 → Jun 1 ~09:07, ~40d) incl. NEW cex_futures (klines/ticker/trades/liqs) from bybit/bitget/gate/okx. **Note: `cex_futures_liquidations` is gate+okx only — bybit/bitget collectors EMPTY** (same root cause as the live hlcascade feed bug in B). Lag-taker fire universe: `strategy_lab/lag_taker_fires_2026_05_29.parquet` (+ gated/enriched).

## D. Key reports index (this session)
Audit: `AUDIT_FINAL_CORRECTED_2026_05_29.md` · `MASTER_LIVE_VS_BACKTEST_2026_05_29.md` · `DEBUG_FINDINGS_ALL_SLEEVES_2026_05_29.md`
Lag taker: `LAG_TAKER_FINAL_CONFIG_2026_05_29.md` · `TV_AGENT_SPEC_FAST_TAKER_LAGV2_2026_05_29.md` · `LAGV2_ROOTCAUSE_ALWAYS_UP_2026_06_01.md` · `TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md`
Cyclops: `CYCLOPS_SIGNALS_DECODE_2026_05_29.md` · `CYCLOPS_WALLET_HUNT_2026_06_01.md`
Forensics: `SILENT_SLEEVES_FORENSICS_MASTER_2026_06_01.md` · `HANDOFF_HURST_HLCASCADE_FIX_2026_06_01.md` · `POSTFIX_VERIFICATION_2026_06_01.md` · `TV_AGENT_FIX_SILENT_SLEEVES_2026_06_01.md`

## END
