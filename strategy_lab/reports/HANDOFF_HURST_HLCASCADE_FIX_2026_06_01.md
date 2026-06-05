# Handoff — 2 unresolved silent-sleeve bugs: SOL 5m hurst + SOL hlcascade — 2026-06-01

Two of the 4 deployed fixes did NOT work. This is the standalone handoff to finish them. (FIX 1 vwap ✅, FIX 2 fairedge/m5v ✅ confirmed working — only these two remain.)

Affected sleeves (still 0 fires post-fix):
- **hurst**: `poly_sniper_v5_sol_5m_btctrend_cci_hurstrev_v7`, `poly_sniper_v5_sol_5m_btcf7against_cci_hurstrev_mfi_v8`
- **hlcascade**: `poly_sniper_v5_sol_5m_a2_hlcascade25k_v9`, `poly_sniper_v5_sol_5m_up_a2_hlcascade15k_v9` (+ the BTC v9 hlcascade sleeves, impaired)

---

## BUG A — SOL 5m hurst: `g_hurst_reverting` True 0% live vs 39% backtest

### Evidence
- `g_hurst_reverting(SOL,5m)` = True **0 / 16,322 evals** over 6 days (all gates else healthy). Backtest = True **39.2%**.
- FIX 4 edited the GATE (`sniper_v5_gates.py`) — but the gate logic is already correct:
  ```python
  # sniper_v5_gates.py:1057
  def g_hurst_reverting(direction, fire_us, *, asset, tf, vol_hurst_panel, **_kw) -> bool:
      if vol_hurst_panel is None: return False
      row = vol_hurst_panel.lookup(asset, tf, fire_us)
      if row is None or row.hurst_60 is None: return False     # <-- None → False
      return row.hurst_60 < HURST_REVERTING_THR                # 0.40
  ```
  Editing the gate can't help — the panel feeds a `hurst_60` that never satisfies `<0.40`.

### Most-likely root cause: COLD-START WARMUP never completes (not a logic bug)
`vol_hurst.py`:
- `hurst_60` is **None for the first `RV_LOOKBACK_BARS = 60` emitted bars** (warmup — needs 60 log returns).
- The panel is built FRESH on every engine boot: `main.py:2223 "vol_hurst": VolHurstPanel()` (empty deque), fed by `on_1m_bar` (main.py:2261) which aggregates 1m → 5m/15m.
- **5m hurst warmup = 60 × 5min = 5 HOURS** of continuous 1m-bar feed after a restart. (15m hurst = 15h.)
- The engine restarted **many times this week** (every deploy). If restarts are < 5h apart, the SOL 5m hurst deque **never reaches 60 bars → `hurst_60` stays None forever → gate always False.**
- The **backtest has the full history** (no warmup gap) → hurst_60 finite → 39% < 0.40. That's the exact 39%-vs-0% discrepancy.
- Today's restart was 09:50 UTC; we measured ~2h later (~24 5m-bars) → still mid-warmup → consistent.

### How to confirm (1 check)
Inspect the RAW `hurst_60` value live (the gate only logs True/False, masking None-vs-value):
- Add a one-shot debug log of `vol_hurst_panel.lookup("SOL","5m",now).hurst_60` (and `rv_60`) at eval, OR
- in a python shell on the running engine, dump the panel: is `hurst_60 is None` (⟹ WARMUP — confirmed) or a finite value ≥0.40 (⟹ genuine panel bug, investigate `_hurst_rs` for SOL)?
- Also dump `len(panel._rows[("SOL","5m")])` — if < 60, warmup not done.

### Fix (warmup case — most likely)
**Backfill the VolHurst deque from history on engine boot** so hurst_60 is available immediately instead of needing 5h:
- On `VolHurstPanel` construction (or first slot), seed each `(asset, tf)` deque with the last ≥60 tf-bars built from recent binance klines (the same klines the engine already pulls). Then `hurst_60`/`rv_60` are non-None from the first eval.
- This ALSO fixes `g_vol_high`/`g_vol_contracting` (rv_60 same warmup) and the 15m hurst sleeves (15h warmup — currently almost never warm).
- Lower-effort alt: persist the panel deques across restarts (pickle on shutdown, reload on boot) so warmup survives redeploys.

### Fix (panel-bug case — if hurst_60 is finite but ≥0.40)
If the check shows hurst_60 finite and pinned ≥0.40 for SOL 5m: investigate `_hurst_rs(log_rets)` — degenerate/low-variance SOL 5m returns can bias R/S toward ~0.5; verify the 5m aggregation feeds real closes (not flat/duplicated), and that the SOL series isn't shorter/different from BTC/ETH.

### Files
- `backend/app/features/vol_hurst.py` — `VolHurstPanel`, `on_1m_bar`, `_hurst_rs`, `RV_LOOKBACK_BARS=60`, `MAXLEN_BY_TF`
- `backend/app/engine/main.py:2223,2261` — panel construction + 1m-bar wiring
- `backend/app/strategies/polymarket/sniper_v5_gates.py:1057` — `g_hurst_reverting` (no change needed)

---

## BUG B — SOL hlcascade: liquidation feed missing 2 venues → cascade gate 0%

### Evidence
- `g_a2_hl_short_cascade` True **0%** for ALL assets post-fix (btc 0/28, sol 0/12 in 2h).
- Liq collector tables (storedata): **bybit_liquidations_v2 = 0 rows, bitget_liquidations_v2 = 0 rows**; only **okx = 660, gate = 224** (okx max ts ~10:34 UTC = live).
- `cex_liq_feed.started` logs `exchanges: okx,bybit,gate,bitget` — but bybit/bitget deliver nothing.

### Root cause
The in-process `CexLiquidationFeed` (read by the gate) subscribes to 4 venue WSs, but **bybit + bitget — the two largest perp-liq venues — are not delivering** (their collector tables are empty too, so it's not just the in-process feed). Aggregate liquidation notional is missing ~50-70% → the $25k-$100k cascade thresholds rarely/never clear, even on BTC.

### How to confirm
- `backend/app/feeds/cex_liquidations_feed.py` — check the bybit + bitget WS connection: are they connecting + subscribed to the liquidation channel? Look for reconnect-loop / auth / wrong-symbol-format errors in `journalctl -u tv-engine` since 09:50 (grep bybit/bitget).
- Confirm the standalone collectors (storedata side) that populate `bybit_liquidations_v2` / `bitget_liquidations_v2` — they're producing 0 rows, so the upstream WS for those venues is down on BOTH paths.

### Fix
1. **Repair bybit + bitget liquidation WS** in `cex_liquidations_feed.py` (and the storedata collectors). Likely a WS endpoint / subscription-payload / symbol-format change on those exchanges. Confirm events flow → tables grow → in-process feed sees them.
2. **Add a feed-health alert**: if a venue delivers 0 liq events for N minutes, WARN — so a silently-dead venue doesn't zero the hlcascade gates again.
3. **SOL hlcascade — KILL regardless.** Even with all 4 venues healthy, SOL short-liqs are too sparse (~9 / 6d, ~4 windows >$25k) — V9 spec §2.4 already said "SOL/ETH: insufficient HL data, do not use." The viable cells are BTC (`btc_5m_a2_hlcascade100k_v9`, `_up_a2_hlcascade50k_v9`) once bybit/bitget are restored.

### Files
- `backend/app/feeds/cex_liquidations_feed.py` — multi-venue WS feed (bybit/bitget broken)
- storedata collectors populating `{bybit,bitget}_liquidations_v2` (empty)
- `backend/app/strategies/polymarket/sniper_v5_gates.py` — `g_a2_hl_short_cascade` (logic OK; starved input)

---

## Priority
1. **BUG A hurst** — high leverage: the warmup-backfill fix unblocks the 2 SOL hurst sleeves AND the 15m hurst sleeves AND fixes rv_60-warmup for vol_high/vol_contracting. One fix, broad benefit. Confirm None-vs-value first (5-min check).
2. **BUG B hlcascade** — repair bybit/bitget collectors (also restores the BTC v9 cells); kill the 2 SOL hlcascade sleeves.

## END
