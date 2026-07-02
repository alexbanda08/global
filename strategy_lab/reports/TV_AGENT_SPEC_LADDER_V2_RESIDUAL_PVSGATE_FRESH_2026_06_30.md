# TV RUST AGENT SPEC — Ladder v2: residual-PnL telemetry + pvs gate, on a FRESH engine
**2026-06-30 · TVRUST (Rust) ONLY · PAPER ($0). Python Tradingvenue stays frozen.**
Goal: re-run the BTC-15m maker ladder as a **clean fresh engine** (no mixing with the v1 data), adding the **two changes that decide go-live**: (G1) measure the residual PnL we currently can't see, and (G3) gate out the pvs>1 windows that lock guaranteed losses. The v1 data is **already archived locally (§4)** — this spec authorizes deleting it on Ireland to reclaim space.

Context / why: `IRELAND_LADDER_FULL_DECODE_HANDOFF_2026_06_30.md`. v1 (13.4d, 1,161 windows, paper) proved the core edge — **pair_frac 0.80 (beats offline 0.29 NO-GO), +$1,611 outcome-independent locked arb**. But the **residual (10,634 directional shares held to resolution) has NO logged PnL**, and **33% of windows locked a pvs>1 loss (−$442)**. v2 fixes exactly those two gaps. Nothing else changes (same clip/levels/markets) so v1↔v2 is a clean comparison.

---

## 1. FRESH ENGINE — no data mixing (do this first)
**Requirement:** v2 telemetry must be physically separated from v1, and v1 must be deletable. **Recommended path (cleanest):**
- New database **`tradingvenue_rust_v2`** — run the engine's migrations fresh against it. Point the v2 engine's `DATABASE_URL` (and `tv-rust-api` read URL, if it reads this DB) at `tradingvenue_rust_v2`.
- Version the sleeve id to **`poly_ladder_btc_15m_v2`** (belt-and-suspenders namespacing).
- Keep the **same 4 event kinds** (`ladder_summary`, `ladder_tick`, `feed_quality`, `tick_latency`) so the existing analysis pipeline (`strategy_lab/directional/_ireland_6day/analyze.py`) runs unchanged on v2 — just with the new fields added (§2).

Acceptable alternatives if your API wiring makes a new DB heavy: new schema `trading_v2` in the same DB, OR same table with the `_v2` sleeve id + **TRUNCATE the old June partition** after backup. The two hard invariants: **(a) v2 rows never intermix with v1 rows; (b) the v1 bulk (`trading.events_2026_06`, 1149 MB) is reclaimable.**

> Note: a brand-new DB resets ALL paper sleeves on the box (kalshi/poly_sniper/shadow_scalp histories) — that history is preserved in the §4 archive, and those sleeves re-log fresh on restart. Confirm that's fine before dropping; if any of those must keep continuity, use the new-schema or truncate path instead.

---

## 2. G1 — RESIDUAL PnL TELEMETRY (the deciding fix)
At window settle the engine already holds the outcome (it settles the paired legs to chainlink). It just needs to **also mark the residual to that outcome and log it.** Add these fields to every `ladder_summary`:

| field | definition |
|---|---|
| `filled_up_vwap` | avg fill price of ALL Up shares this window (maker fills) |
| `filled_dn_vwap` | avg fill price of ALL Dn shares this window |
| `outcome` | chainlink winner: `"up"` or `"dn"` (the same settle you already use for the paired legs) |
| `residual_entry_vwap` | vwap of the residual side = `filled_up_vwap` if `residual_side=="up"` else `filled_dn_vwap` |
| `residual_pnl_usd` | held-to-resolution PnL of the residual, winner-only fee (formula below) |
| `total_net_usd` | `paired_pnl_locked_usd + rebate_usd + residual_pnl_usd` — **the TRUE net we've been missing** |

**Formula (winner-only 0.07·p fee; NEVER fee the loser or the redeem):**
```
v   = residual_entry_vwap
won = (residual_side == outcome)
residual_pnl_usd = won ?  residual_sh * (1 - v) * (1 - 0.07 * v)
                       : -residual_sh * v
# residual_side == "none"  ->  residual_pnl_usd = 0
total_net_usd = paired_pnl_locked_usd + rebate_usd + residual_pnl_usd
```
Keep all existing fields (`pvs`, `pair_frac`, `paired_sh`, `residual_sh`, `residual_side`, `paired_pnl_locked_usd`, `rebate_usd`, `flow_capture`, `market_sell_total_sh`, …) unchanged. (`filled_up_vwap`/`filled_dn_vwap` also let the research side independently recompute pvs and residual_pnl as a cross-check — please emit them even though they're partly redundant.)

**Implementation surface:** the `ladder_summary` build/insert in `crates/tv-engine/src/loops/poly_ladder.rs` (the per-window settle block). You already track per-side filled size + cost to compute `pvs`/`paired_pnl_locked` → `filled_*_vwap = side_cost / side_sh`. The outcome is the chainlink settle you already apply to the paired legs.

---

## 3. G3 — pvs GATE (free EV; configurable, ON in v2)
v1 locked a **pvs>1 pair in 33% of windows** (guaranteed loss the moment both legs fill above sum 1). Fix = **cap the second-leg bid so a completed pair can't sum ≥ `PAIR_MAX_SUM`.**

- Config: `TV_LADDER_PAIR_MAX_SUM` (default **0.99**).
- Rule (live quoting invariant): when one side is (partially) filled at vwap `v_side`, **cap the opposite side's resting bid at `PAIR_MAX_SUM − v_side`.** If the market won't fill that cheap, you simply don't complete the pair — the already-filled shares stay as **residual** (directional, now measured by G1) instead of a locked loss. Net effect: realized `pvs < PAIR_MAX_SUM` by construction.
- If no opposite fills yet, reference the opposite side's current best bid for the cap; exact reference is your call — the **invariant to hold is `pvs < PAIR_MAX_SUM`**.
- Log per window: `pair_gate_bound_sh` (shares the cap kept from pairing) so we can size the gate's effect. `taker_completions` stays 0 (pure maker).

**Why this is safe to just turn on:** it can only *prevent* a pair from locking above sum 1; it never forces a trade. With G1 also live, we measure whether converting those would-be losing pairs into residual actually improves `total_net_usd` (vs v1's archived ungated distribution). If `PAIR_MAX_SUM=0.99` proves too tight (suppresses too much pairing), it's one env var to relax.

**Keep everything else identical to v1** (clip size, # levels, band, decision cadence, markets = BTC-15m only) so v1↔v2 differs ONLY by G1+G3.

---

## 4. DELETE v1 DATA — backup is DONE & verified (authorized)
The research/data side has archived the **entire `tradingvenue_rust` DB** locally, two ways, verified:
```
D:\global_data\ireland_archive\
  tradingvenue_rust_2026-06-30.dump        93,366,539 B  pg_dump -Fc (restorable via pg_restore)
      sha256 5e1371c7e36d30e4f34391456001ef79f9f0b779ff13db28faf8a6c48d9ce4c7
  trading_events_2026-06-30.tsv.gz         50,836,840 B  gzipped TSV, 1,636,446 rows (at\tsleeve\tkind\tdata)
      sha256 e84e622325fc3231f0753c4d2c1ccabb6901222adfead3846644bf0a882e9f45
```
Both verified: PGDMP header valid; TSV row count = server count; all sleeves present (ladder 538k×3 + kalshi/poly_sniper/shadow_scalp). **Backup CONFIRMED — deletion authorized**, gated on:
1. v2 engine confirmed writing to the fresh store (rows landing in `tradingvenue_rust_v2` / `_v2` sleeve), AND
2. `tv-rust-api` (if it read the old DB) repointed and healthy.

Then reclaim space (irreversible — archive exists):
- **Full path:** `DROP DATABASE tradingvenue_rust;` (after stopping anything still attached). Frees the full 1159 MB.
- **Conservative path** (kept DB / other sleeves): `TRUNCATE trading.events_2026_06;` frees the 1149 MB bulk.

(Disk is currently 53 G free / 23% used — not urgent, so prioritize getting v2 up cleanly over the delete; do the delete once v2 is confirmed.)

---

## 5. NOT in scope / guardrails
- ❌ No LIVE arm. v2 is PAPER. **`tv-watchdog` (kill-path) must be deployed before any future live flip** — not required for paper, noted as the live prerequisite (G2).
- ❌ Don't change the fill model, clip size, levels, or markets — v2 must stay comparable to v1.
- ❌ Don't fee maker/redeem legs. Winner-only 0.07·p on the won leg only.
- ❌ Don't touch Python Tradingvenue, storedata, or the VPS3 box.

## 6. Acceptance criteria
1. `tradingvenue_rust_v2` (or `_v2`-namespaced) receiving `ladder_summary` rows on BTC-15m windows, with the 6 new G1 fields populated and `total_net_usd` = paired+rebate+residual.
2. On traded windows, realized `pvs < TV_LADDER_PAIR_MAX_SUM` (gate holding); `pair_gate_bound_sh` logged.
3. v1 data archived (§4) and deleted on Ireland once v2 confirmed.
4. ≥1 week accrual → research side computes bootstrap CI on `total_net_usd` (the go-live decision) and compares gated v2 vs ungated v1.

## 7. Provenance
v1 decode + the two gaps: `IRELAND_LADDER_FULL_DECODE_HANDOFF_2026_06_30.md`. Strategy mechanics + fill model: `TV_AGENT_HANDOFF_IRELAND_V2_SHADOW_2026_06_16.md`. Memory: `project_offline_feed_blind_to_edge`.
