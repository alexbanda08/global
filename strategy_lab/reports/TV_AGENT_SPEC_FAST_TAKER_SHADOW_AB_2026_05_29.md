# TV Agent Spec — `poly_fast_taker` oracle-lag sleeve, A/B shadow (4 sleeves: BTC 5m + ETH 5m) — 2026-05-29

> **For the TV agent (tradingvenue repo on VPS3).** Implement the binance→chainlink
> oracle-lag **directional taker** as **FOUR new paper-only / shadow** sleeves — **two configs
> × two cells (BTC 5m, ETH 5m only)** — on the existing Phase-35 sniper-v5 framework. No live
> capital. No new loop — reuse the sniper-v5 controller, the `oracle_lag` signal, and the maker
> fill-sim. (Cells restricted to BTC 5m + ETH 5m per the per-market evidence in §3.0; 15m/SOL
> deferred.)
>
> The 4 sleeves:
> - **Config A — `poly_fast_taker_a25_merge_{btc,eth}_5m`** (2 sleeves): **$25/fire**, BOTH-sides,
>   **merge mimic ON** (full eebde7a0-style mechanic: accumulate both sides as price oscillates,
>   FIFO-merge matched pairs to recycle collateral, hold residual to resolution).
> - **Config B — `poly_fast_taker_b2_nomerge_{btc,eth}_5m`** (2 sleeves): **$2/fire**, one-shot
>   directional, **no merge** (the micro version we intend to take live), hold to resolution.
>
> Evidence + strategy rationale: `WALLET_DECODE_5WALLETS_2026_05_29.md` §1 (eebde7a0,
> $826k), `LATENCY_EDGE_FINDING_2026_05_29.md` (OOS +$1.31/$25, WR 63%),
> `LOCK_THE_LAG_HYPOTHESIS_TEST_2026_05_29.md` (why we A/B merge vs no-merge), and the
> V2 design `TV_AGENT_SPEC_POLY_FAST_TAKER_V2_2026_05_29.md`.

---

## 0. The edge (so implementation matches the backtest)
Polymarket BTC/ETH/SOL up-down resolves on Chainlink Data Streams, which **lags Binance
~5–20s**. Right after a binance move the resting Polymarket ask on the **leading side** is
**stale-cheap**. TAKE it early, hold to chainlink resolution. Edge decays to ~0 by 45–60s →
fire **early** and only on **strong moves**. Backtest: **OOS +$1.31 per $25 fire, WR ~63%,
~59 fires/day** across btc/eth/sol × 5m/15m.

---

## 1. Reuse what already exists on VPS3 (do NOT build a new loop)

| Need | Existing module to reuse |
|---|---|
| **Fire signal** (binance vs chainlink basis) | `backend/app/engine/oracle_lag.py` → `compute_oracle_lag()` → `OracleLagSnapshot.price_delta_bps = (feed − oracle)/oracle × 10_000` |
| **Sleeve descriptor + registry** | `backend/app/strategies/polymarket/sniper_v5_sleeves.py` (`SniperV5Sleeve`, `SNIPER_V5_SLEEVES`) mirrored by `backend/app/configs/poly_sniper_v5_sleeves.yaml` |
| **Controller / dispatch** | `backend/app/engine/poly_sniper_v5_loop.py` — iterates sleeves, dispatches at `slot_start_us + offset_s`, runs pure gates BEFORE placement |
| **Fill + MERGE + REDEEM accounting (shadow)** | `backend/app/engine/poly_maker_fill_sim.py` — `MakerFillSimulator.observe()` handles `TAKE` (→ inventory), `MERGE` (`_observe_merge`, FIFO pairs, credits $1×pairs, `tv_poly_merge_gas_usd`), `REDEEM` (`_observe_redeem`) |
| **Gates** | `backend/app/strategies/polymarket/sniper_v5_gates.py` — add the new oracle-lag gate(s) here (pure functions) |
| **Shadow logging** | `backend/app/strategies/polymarket/sniper_v5_shadow_log.py` |
| **Resolution truth** | `backend/app/engine/poly_updown_resolver.py` (chainlink) |
| **Structural test (MUST update)** | `backend/tests/strategies/polymarket/sniper_v5/test_sleeves.py` asserts YAML ↔ Python tuple parity (sleeve_id order, asset, tf, direction, offsets, spread_filter, gate names) |

---

## 2. New gate — the oracle-lag fire signal
Add to `sniper_v5_gates.py` (pure, per the invariant "gates fire BEFORE placement"):

```python
def g_oracle_lag_bps_ge(threshold_bps: float):
    """Pass iff |price_delta_bps| >= threshold; expose the SIGN so the controller
    fires the leading side. Up if feed>oracle (delta>0), Down if delta<0."""
    def _gate(ctx) -> GateResult:
        snap = ctx.oracle_lag      # OracleLagSnapshot from compute_oracle_lag(asset, now)
        if snap is None:
            return GateResult(ok=False, reason="no_oracle_lag")
        bps = snap.price_delta_bps
        if abs(bps) < threshold_bps:
            return GateResult(ok=False, reason="lag_below_thresh")
        side = "Up" if bps > 0 else "Down"
        return GateResult(ok=True, direction=side, meta={"price_delta_bps": bps})
    return _gate
```

- **Signal choice (refinement over the backtest):** the backtest used
  `ret = binance(now)/binance(slot_start) − 1`. The engine's `price_delta_bps`
  (feed-vs-oracle) is the *direct* staleness measure and is the better signal (it is the
  handoff §3 "use Chainlink Data Streams directly" idea, already implemented). The shadow run
  will confirm it reproduces the backtest WR. **Also log the slot_start-anchored binance ret**
  (`ret_bps`) alongside `price_delta_bps` so we can compare the two signals offline.
- Default threshold `TV_FT_RET_BPS = 3.0` (the OOS sweet spot; 2bps too loose, 5bps better WR
  but ~3× fewer fires — see `LATENCY_EDGE_FINDING`).
- The controller must fire the side returned by the gate (`direction` from `GateResult`).

---

## 3. The four sleeves (add to `SNIPER_V5_SLEEVES` tuple + YAML + test)

### 3.0 Cell prioritization (per-market backtest evidence — `realistic_latency.csv`)
The edge is **not uniform across cells.** Realistic fills ($25 book-walk, 85ms, spread 0.05,
~3-week OOS window):

| Cell | pnl/trade | pnl/$ | fill | priority |
|---|---:|---:|---:|---|
| **BTC 5m** | +$2.19 | +8.8% | 93% | **PRIMARY** |
| **ETH 5m** | +$2.02 | +8.1% | 90% | **PRIMARY** |
| BTC 15m | +$1.03 | +4.1% | 95% | secondary |
| ETH 15m | +$0.59 | +2.4% | 85% | secondary |
| SOL 15m | +$0.75 | +3.0% | 52% | monitor-only (thin book) |
| **SOL 5m** | **−$1.59** | **−6.4%** | 54% | **EXCLUDE (loses; thin book)** |

**Deploy guidance — THIS BATCH = BTC 5m + ETH 5m ONLY (4 sleeves):**
- Build exactly **4 sleeves**: Config A (merge, $25) × {BTC 5m, ETH 5m} + Config B (no-merge,
  $2) × {BTC 5m, ETH 5m}. These are the highest edge + fill cells.
- **DEFERRED to a later batch:** BTC/ETH 15m (secondary, weaker edge), SOL 15m (monitor-only,
  thin book), SOL 5m (**negative edge — never deploy**). Do NOT add these now.
- Matches the live wallet eebde7a0 (BTC/ETH 5m heaviest). The structural edge exists on all
  crypto up-down, but SOL's thin book makes the fill economics negative at our infra.



### Config A (2 sleeves) — `poly_fast_taker_a25_merge_{btc,eth}_5m`  ($25/fire, BOTH-sides, MERGE mimic ON)
Full eebde7a0 mechanic: fire the leading side on each qualifying oracle-lag signal across the
window (so as price oscillates it accumulates BOTH sides), FIFO-merge matched pairs to recycle
collateral, hold the net directional residual to resolution.

```yaml
- sleeve_id: poly_fast_taker_a25_merge_btc_5m
  asset: BTC
  tf: 5m
  direction: BOTH                 # side set per-fire by g_oracle_lag_bps_ge
  offsets: [5, 10, 20, 40, 80, 160, 240]   # dense early-weighted; fire on each qualifying signal across window
  spread_filter: 0.02             # same-token ask0-bid0 (matches sniper-v5 BTC default)
  paper_only: true
  mode: shadow
  notional_usd_override: 25.0
  exit_policy: HOLD
  merge_mimic: true               # NEW field — route TAKE+MERGE through MakerFillSimulator
  one_shot_per_slug: false        # fire repeatedly to accumulate both sides
  gates:
    - g_oracle_lag_bps_ge(3.0)
```
**Second Config-A sleeve = ETH 5m** — identical to the BTC block above except:
`sleeve_id: poly_fast_taker_a25_merge_eth_5m`, `asset: ETH` (`spread_filter: 0.02`, same offsets,
same `notional_usd_override: 25.0`, `merge_mimic: true`, `one_shot_per_slug: false`).

### Config B (2 sleeves) — `poly_fast_taker_b2_nomerge_{btc,eth}_5m`  ($2/fire, one-shot directional, NO merge)
The micro version we intend to take live. Fire ONCE per slug on the first qualifying early
signal, hold to resolution. No counter-trade, no merge.

```yaml
- sleeve_id: poly_fast_taker_b2_nomerge_btc_5m
  asset: BTC
  tf: 5m
  direction: BOTH
  offsets: [3, 6, 9, 12]          # early-only window; first qualifying offset fires then stops
  spread_filter: 0.02
  paper_only: true
  mode: shadow
  notional_usd_override: 2.0
  exit_policy: HOLD
  merge_mimic: false
  one_shot_per_slug: true         # inherited sniper-v5 one-shot behavior
  gates:
    - g_oracle_lag_bps_ge(3.0)
```
**Second Config-B sleeve = ETH 5m** — identical except `sleeve_id: poly_fast_taker_b2_nomerge_eth_5m`,
`asset: ETH`.

> **Total = 4 sleeves:** `a25_merge_btc_5m`, `a25_merge_eth_5m`, `b2_nomerge_btc_5m`,
> `b2_nomerge_eth_5m`.

> **Two new `SniperV5Sleeve` fields** must be added (default-valued so existing 56 sleeves are
> unaffected): `merge_mimic: bool = False` and `one_shot_per_slug: bool = True`. Update the
> dataclass, the YAML loader, and `test_sleeves.py` parity assertions accordingly.

---

## 4. Fill + settlement wiring (shadow)

Both sleeves route fills through `MakerFillSimulator.observe()` so the existing E1-fixed
settlement + dashboard work unchanged:

- **On fire (both sleeves):** emit a `TAKE` decision (buy `notional_usd_override` of the chosen
  side at the book ask). The sim walks ask levels (`_walk_take_vwap`), records `vwap, shares,
  usd`, adds to slug inventory. Honor `spread_filter` (reject if `ask0−bid0 > spread_filter`)
  and the sim's existing min-liquidity/staleness guards. Log a SKIP row on rejection.
- **Sleeve A only — MERGE:** when slug inventory has `min(inv_up, inv_down) >= 1` share,
  emit a `MERGE` decision so `_observe_merge` pops FIFO pairs, credits `$1 × pairs`, and
  charges `tv_poly_merge_gas_usd` (set **0.0** for crypto up-down — merge is gasless on
  Polymarket, verified on-chain; do NOT use the legacy 0.05). Keep the residual.
- **Sleeve B:** never accumulates both sides (one-shot, single direction) → no MERGE path.
- **At slot resolution (both):** `_observe_redeem` credits `$1 × winning_residual_shares`;
  losing residual → $0. Apply the **2%-on-winning-profit** fee model (E4): set
  `TV_POLY_FAST_TAKER_FEE_MODEL=legacy_2pct` (won → `shares×(1−vwap)×0.98`; lost →
  `−shares×vwap`; no per-fill taker fee — crypto up-down feeRate≈0).
- Outcome truth = `poly_updown_resolver` (chainlink). NOT binance close.

---

## 5. Config (env) — both sleeves
```
# shared
TV_FT_ENABLED=true
TV_FT_RET_BPS=3.0                 # oracle-lag fire threshold (price_delta_bps)
TV_FT_SPREAD_BTC=0.02
TV_FT_SPREAD_ETH=0.02
TV_FT_LATENCY_MS=85               # book lookup at fire_ts + latency (match backtest)
TV_FT_MIN_BOOK_EVENTS=25
TV_POLY_FAST_TAKER_FEE_MODEL=legacy_2pct
TV_POLY_FAST_TAKER_MERGE_GAS_USD=0.0   # gasless on crypto up-down

# Config A ($25 + merge) and Config B ($2, no merge) use per-sleeve
# notional_usd_override (25.0 / 2.0) + merge_mimic (true / false) from the registry.
# Active cells: BTC 5m + ETH 5m only (4 sleeves total).
TV_POLY_FAST_TAKER_KILL=          # e.g. "poly_fast_taker_a25_merge_eth_5m" to kill a cell
```

All sleeves `paper_only=true / mode=shadow`. Live promotion deferred (mirror Phase-35 policy).

---

## 6. Logging (reuse `sniper_v5_shadow_log` schema + add columns)
Per fire/fill/skip/merge/settle row, in addition to the sniper-v5 columns:
`price_delta_bps, ret_bps_binance, side, offset_s, vwap, shares, notional, ask0, bid0, spread,
merge_pairs, merge_collateral, residual_up, residual_down, outcome, won, pnl, skip_reason`.
Sleeve A must log MERGE rows (pairs, collateral freed, residual). Tag each row with `sleeve_id`
so A vs B is directly comparable.

---

## 7. Shadow test plan & acceptance criteria

Run A and B **in parallel** on the same 2 cells (BTC 5m + ETH 5m). Compare A vs B vs backtest.

**Edge validation (both sleeves):**
- **AC-1 Fire rate:** in line with backtest per-cell fire density at 3bps (BTC 5m ~192 signals
  / ETH 5m ~289 over the ~3-week backtest; scale by active hours).
- **AC-2 Fill rate:** 65–91% of fires fill (spread filter rejects the rest).
- **AC-3 WR:** filled-fire WR ≈ **63%** (allow OOS CI; confirm it stays >50% and t builds >2 as n grows).
- **AC-4 Signal parity:** `price_delta_bps`-driven fires reproduce the backtest WR; log `ret_bps_binance` to confirm the engine signal correlates with the slot_start binance ret.
- **AC-5 Live↔backtest fill parity:** sampled fire vwap matches the canonical `latency_threshold_sweep` fill within ≤0.01.

**A vs B comparison (the experiment this A/B answers):**
- **AC-6 Merge value:** does Sleeve A's merge/both-sides add or subtract vs B's pure directional?
  Prior evidence (`LOCK_THE_LAG_HYPOTHESIS_TEST`) says the matched-pair book nets **negative**
  (eebde7a0 −$961 in-sample) and the profit is the directional residual. **Expectation: B's
  per-$ return ≥ A's**; A's value (if any) is capital turnover, which is irrelevant in paper.
  Log A's `capital_turnover_ratio` and net merge PnL to quantify.
- **AC-7:** B (the micro live candidate) is net-positive per-fire after the 2% fee over n≥200 fills.

**Go/no-go before any live capital (Sleeve B only):**
- ≥2 weeks shadow, n≥200 filled fires, WR ≥ 60%, mean pnl/fire > 0 after fee, fill parity holds,
  7-day rolling WR not trending down (crowding check).

---

## 8. Risks & gotchas (honor these — from CLAUDE.md + this session)
- **Anchor = `slot_start + offset_s`** (intra-window). Do NOT use the momo `ws_s` anchor.
- **Spread = same-token `ask0 − bid0`** (directional taker); NOT the cross-token vwap-sum check
  used by the maker sleeves.
- **L25 / BookMirror native event-rate** — fire on the live WS BookMirror snapshot at fire time;
  do not throttle to the 100ms maker poll.
- **Fee = 2%-on-winning-profit only** (`legacy_2pct`); no per-fill taker fee.
- **MERGE is gasless on crypto up-down** → `merge_gas_usd=0.0` (the legacy 0.05 is wrong here).
- **Merge mimic is EV-neutral-to-negative** (this session's finding): A is a *test* of whether
  the full eebde7a0 mechanic reproduces; expect the edge to live in the directional residual,
  not the merge. At the $2 live size (B), capital is never constrained → merge would add nothing,
  which is why B omits it.
- **Crowding:** an open-source bot runs this family at ~61% WR; watch rolling WR for decay.
- **`one_shot_per_slug` semantics:** confirm the sniper-v5 controller's existing one-shot flag is
  per-slug (B) vs the new per-fire repeat behavior (A) — A needs the controller to permit multiple
  fires per slug; verify this doesn't violate an existing controller assumption.
- **`fill_sim.settle_slug` multi-side:** A holds both sides simultaneously before merge; confirm
  the E1-fixed settle path settles Up AND Down residuals independently (the maker sleeves it was
  built for already hold both sides, so this should be covered — but verify).

---

## 9. Deliverable checklist for the TV agent
1. Add `g_oracle_lag_bps_ge` (+ direction-align) to `sniper_v5_gates.py`; wire `ctx.oracle_lag`
   from `compute_oracle_lag`.
2. Add `merge_mimic` + `one_shot_per_slug` fields to `SniperV5Sleeve`; update YAML loader.
3. Add the **4 sleeves** (A×2 + B×2 = `{a25_merge,b2_nomerge}_{btc,eth}_5m`) to
   `SNIPER_V5_SLEEVES` + `poly_sniper_v5_sleeves.yaml`. BTC 5m + ETH 5m only.
4. Route TAKE (both) and MERGE (A only) through `MakerFillSimulator`; set fee model + gas env.
5. Extend `sniper_v5_shadow_log` columns (§6).
6. Update `test_sleeves.py` parity + add a unit test for the oracle-lag gate.
7. Deploy paper-only/shadow; verify AC-1…AC-5 over the first days, then AC-6/AC-7.
