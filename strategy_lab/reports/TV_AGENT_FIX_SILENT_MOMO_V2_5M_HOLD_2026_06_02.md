# TV-Agent Fix — Silent sleeves: `{btc,sol}_5m_momo_v2_HOLD_f7` stopped firing on VPS3 shadow

_For the tv-agent on VPS3 (`/opt/tradingvenue`). Self-contained: problem, proof it's a bug, exact scope, where to
look, fix, verify. Diagnosis from `trading.events` (both boxes) + engine state, 2026-06-02._

## The problem in one paragraph
Two VPS3 **shadow** sleeves — `poly_updown_sol_5m_momo_v2_HOLD_f7` and `poly_updown_btc_5m_momo_v2_HOLD_f7` —
**stopped producing any events** (no signals, no resolutions) after the engine restarted at **2026-06-02 01:37:13
CEST**. Their last fire was 01:36, one minute before the restart. They have been dark for ~24h. The live (Ireland)
copy of the SOL one keeps trading normally, so the shadow↔live A/B for these two has no shadow side right now.

## Is it a bug? YES — and here is the proof it's not config/market

| Check | Result | Conclusion |
|-------|--------|------------|
| Events after the 01:37 restart | `sol_5m_momo_v2_HOLD_f7` = **0**, `btc_5m_momo_v2_HOLD_f7` = **0** | sleeves not evaluating |
| Sibling `eth_5m_momo_v2_HOLD_f7` after restart | **267 signals + 32 resolutions** | the HOLD_f7 path works for ETH-5m |
| Other HOLD_f7 slots after restart | `btc_15m`,`eth_15m`,`sol_15m` HOLD_f7 all firing | 4 of 6 HOLD slots alive |
| Is it the (sym,tf) slot? | `sol_5m_momo_v2_hod` (274 sig) + `btc_5m_momo_v2_hod_mtf` (274 sig) **fire fine** | **(BTC,5m)+(SOL,5m) slots are alive** — not a slot drop |
| Deprecated-config? | none of the 3 `*_5m_momo_v2_HOLD_f7` are in `TV_POLY_DEPRECATED_SLEEVES` (`/etc/tv/tradingvenue.env`, unchanged since 06-01 11:19) | not a deprecation |
| `TV_POLY_MOMO_V2_ENABLED` / strategy modes | `=true`, `momo_v2` ∈ `TV_POLY_STRATEGY_MODES` | momo_v2 is enabled |
| Market-driven (no signal)? | Ireland **live** fired `sol_5m_momo_v2_HOLD` **32×** on 06-02 off the same momo_v2 signal | the signal *was* triggering; shadow just isn't running the sleeve |

**Conclusion:** the **HOLD_ONLY momo_v2 policy controller is no longer firing its `(BTC,5m)` and `(SOL,5m)` slots**,
even though (a) those slots fire for other momo_v2 variants (`_hod`/`_hod_mtf`) and (b) the HOLD_ONLY path fires for
ETH-5m and all three 15m symbols. This is a **deterministic registration/slot-allowlist regression**, introduced by
the engine's **uncommitted working tree** which the 01:37 restart loaded.

## Why now: uncommitted code
`git -C /opt/tradingvenue status` shows ~30 modified files; HEAD is `3a2ff3a9` (May 29). The restart at 01:37 picked
up the working tree. The registration-relevant files are dirty:
```
git diff --stat 3a2ff3a9 -- backend/app/engine/main.py backend/app/engine/poly_updown_loop.py \
                              backend/app/strategies/sleeve_registry.py
  main.py            +220 / -…    poly_updown_loop.py  +126 / -…    sleeve_registry.py  +79 / -…
```
The regression is in one of these diffs — specifically the path that builds the **HOLD_ONLY** momo_v2 controller's
per-(sym,tf) slot allowlist.

## Where to look (ranked)
1. **`backend/app/engine/main.py` ~1683–1713** — the momo_v2 spawn loop:
   ```python
   for _hp in ("HOLD_ONLY", "HEDGE_HOLD", "SELL_BID"):
       momo_v2_ctrl = PolymarketUpdownController(..., strategy_mode="momo_v2", hedge_policy=_hp, ...)
       sleeve_ids = register_poly_updown(momo_v2_ctrl)
   ```
   Check whether `register_poly_updown` (or the controller's `slot_allowlist`) now yields only 4 of the 6 (sym,tf)
   slots for `HOLD_ONLY`. The comment claims "Each manages 6 (sym, tf) slots" — verify that's still true at runtime.
2. **`register_poly_updown` + the momo_v2 controller `slot_allowlist`** (in `poly_updown_loop.py` /
   `sleeve_registry.py`). Look for any list/filter that enumerates `(sym, tf)` for the HOLD_ONLY policy and is
   missing `("BTC","5m")` and `("SOL","5m")` — or an F7-gate availability guard that excludes them. Note the
   asymmetry to exploit: ETH-5m HOLD survives, BTC/SOL-5m HOLD don't → look for an ETH-only or BTC/SOL-excluding
   branch added in the diff.
3. **Boot log** (authoritative): the engine logs the registered ids via
   `logger.info("poly_updown.momo_v2_controller_registered", sleeve_ids=…)` (`main.py:1706`). journald retention
   dropped the 01:37 boot, so **add a one-shot: restart and capture** —
   `journalctl -u tv-engine -S "$(date '+%H:%M' -d '-1 min')" | grep momo_v2_controller_registered` right after a
   restart — and confirm whether `…btc_5m_momo_v2_HOLD_f7` / `…sol_5m_momo_v2_HOLD_f7` are in the emitted list.
   - If **absent from the log list** → registration drop (fix the slot allowlist / register_poly_updown).
   - If **present but still no events** → the master scheduler's t+60 dispatch is skipping those two (fix dispatch).

## Fix
- Restore `(BTC,5m)` and `(SOL,5m)` to the **HOLD_ONLY** momo_v2 controller's slot allowlist so all 6 (sym,tf) HOLD
  sleeves register (matching the other policies / the pre-regression behavior on commit `3a2ff3a9`).
- If the diff intentionally narrowed momo_v2 HOLD to a subset, that intent is wrong for these two: they are active
  shadow sleeves (and `sol_5m_momo_v2_HOLD` is even a promoted **live** sleeve on Ireland), so they must keep
  generating shadow data.
- **Then commit the working tree.** Running uncommitted code is the root enabler — a restart silently shipped this
  regression with no diff review. (This is also standing handoff open-item #3.)

## Verify
1. `git -C /opt/tradingvenue diff 3a2ff3a9 -- backend/app/engine/main.py backend/app/engine/poly_updown_loop.py
   backend/app/strategies/sleeve_registry.py` → find the hunk that changed the momo_v2 HOLD slot set.
2. After fix + restart, confirm the boot log lists both ids, then within ~10 min:
   ```sql
   SELECT sleeve_id, count(*) FROM trading.events
   WHERE kind='poly_updown_signal' AND at> now()-'10min'::interval
     AND sleeve_id IN ('poly_updown_sol_5m_momo_v2_HOLD_f7','poly_updown_btc_5m_momo_v2_HOLD_f7')
   GROUP BY 1;   -- expect both > 0
   ```
3. Resolutions should resume on the next 5m boundaries; WR/PnL should track the live (Ireland) copy again (same
   strategy — they agree 80/80 on every market both fired before the outage).

## Note (not part of this bug)
The live↔shadow PnL-per-fire gap on this sleeve is **sizing only** (live $1 stake vs shadow $25), not logic — see
`DEBUG_SOL_MOMO_V2_HOLD_LIVE_VS_SHADOW_2026_06_02.md`. The only defect is the silent-sleeve drop above.

---

## ✅ VERIFICATION — 2026-06-03 ~06:10 CEST (re-checked on VPS3)

**The registration fix WAS implemented and works.** Engine re-deployed (`ExecMainStartTimestamp` now
`2026-06-03 04:04:06 CEST`; sleeves resumed signalling ~`01:06`). Both previously-silent sleeves are back in the
registry and evaluating:

| sleeve | signals 8h | order_placed | resolutions 8h | status |
|--------|-----------|--------------|----------------|--------|
| `sol_5m_momo_v2_HOLD_f7` | 51 | 9 | **7** | ✅ fully closed-loop (places + resolves) |
| `btc_5m_momo_v2_HOLD_f7` | 51 | 5 | **0** | ⚠️ places orders but **none resolve** (see below) |
| `eth_5m_momo_v2_HOLD_f7` (control) | 83 | — | 13 | ✅ |

Signals show `f7_decision: pass`, `reason: order_placed`/`filled` → the sleeves are registered, f7-gated, and
placing. **The silent-sleeve registration regression is resolved.**

### 🔴 But a SEPARATE incident surfaced — btc_5m-wide resolution gap
`btc_5m_momo_v2_HOLD_f7` places orders (5, oldest 01:16 = >5h ago) but has **0 resolutions in 24h**. Root-caused as
**not momo-specific**: **every `btc_5m` sleeve stopped resolving at `2026-06-02 23:40 CEST`** while `eth_5m` and
`sol_5m` keep resolving normally:

| asset @5m | resolutions 24h | last resolution |
|-----------|-----------------|-----------------|
| btc | 338 | **2026-06-02 23:40** ⛔ (stopped) |
| eth | 164 | 2026-06-03 05:38 ✅ |
| sol | 449 | 2026-06-03 05:41 ✅ |

The 5 btc momo orders' `condition_id`s resolve under **no** sleeve (0/5). So btc_5m markets are being entered but
not settled — a **btc-5m resolution/settlement path issue** (resolver/market-discovery), unrelated to the
registration fix, started 06-02 23:40. **New TODO for the tv-agent:** investigate why `poly_updown_resolver` stopped
producing `poly_updown_resolution` for btc_5m markets after 23:40 (check condition_id discovery / oracle mapping for
btc 5m; eth/sol unaffected).

### ⚠️ Working tree still UNCOMMITTED
`git log` HEAD is still `3a2ff3a9`; `main.py`, `poly_updown_loop.py`, `sleeve_registry.py` remain `M` (dirty). The
fix is live but **not committed** — handoff open-item #3 is still open. Commit the working tree so the fix is
versioned and the next restart can't silently regress again.
