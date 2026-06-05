# Debug — `sol_5m_momo_v2_HOLD_f7` Live (Ireland) vs Shadow (VPS3): why trades diverge

_Question: the live (Ireland) and shadow (VPS3) copies of `poly_updown_sol_5m_momo_v2_HOLD_f7` show divergent
trades. Root-caused. Data: `trading.events` both boxes, 7d. Artifacts: `vps3_engine_snapshot_2026_06_01/`
(`momo_ireland_7d.csv`, `momo_vps3_7d.csv`, `_audit/debug_sol_momo.py`)._

## TL;DR — 3 distinct effects, only one is a problem

| # | Observation | Cause | Problem? |
|---|-------------|-------|----------|
| 1 | PnL/fire: live **+$0.04** vs shadow **+$0.64** (15×) | **Sizing**: live stake **$0.99** (qty≈2) vs shadow **$25.29** (qty≈49). Per-$ edge is live **+4.0%** vs shadow **+2.5%** — both positive | ✅ by design |
| 2 | Where both fire, do they agree? | **80/80 common markets identical** — same_signal 80/80, same_outcome 80/80, same_win 80/80 | ✅ logic identical |
| 3 | Fire count: live **116** vs shadow **83** | 🔴 **VPS3 shadow sleeve went SILENT after the 06-02 01:37 CEST engine restart** — dropped from the registry. 32 of the 36 live-only markets are on 06-02 | 🔴 **silent-sleeve regression** |

## Detail

### Effect 1 — PnL divergence is pure sizing (not a bug)
`entry_qty × entry_price`: live ≈ **2 × $0.50 = $0.99** stake; shadow ≈ **49 × $0.51 = $25.29** stake. 25× notional.
Entry prices are realistic on **both** (live 0.47–0.53 at $0.01 ticks = real fills; shadow 0.49–0.52 continuous
book-walk vwap). WR matches (live 0.526 / shadow 0.530). Normalized **pnl per $ staked: live +0.040 vs shadow
+0.025** — live is actually slightly better (small-sample). The headline "15× pnl/fire" is entirely the stake.

### Effect 2 — identical where both fire
Joined on `condition_id` (momo schema has no `ws_s`/`slug`): **80 common markets**, and on every one the two boxes
agree on signal, outcome, and win (**80/80/80**). The strategy computes the same thing on both boxes. No logic drift.

### Effect 3 — the real divergence: VPS3 shadow dropped the sleeve at the 01:37 restart 🔴
- Time spans: Ireland live runs to **06-02 21:15 UTC**; **VPS3 shadow's last fire = 06-01 22:35 UTC** (06-02 00:35
  CEST). 32 of the 36 live-only markets are **06-02**.
- `tv-engine` `ExecMainStartTimestamp = 2026-06-02 01:37:13 CEST` (NRestarts=0). The sleeve's last signal was
  **01:36 CEST — one minute before the restart**. After the restart: **0 signals AND 0 resolutions** for
  `sol_5m_momo_v2_HOLD_f7` (and for `btc_5m_momo_v2_HOLD_f7`).
- Sibling control: after the same restart `eth_5m_momo_v2_HOLD_f7` logged **267 signals + 32 resolutions**; the
  15m HOLD variants (`btc_15m`, `eth_15m`, `sol_15m`) all kept firing. **Only `{btc,sol}_5m_momo_v2_HOLD_f7` died.**
- **Not deprecation:** none of the three `*_5m_momo_v2_HOLD_f7` sleeves are in `TV_POLY_DEPRECATED_SLEEVES`
  (`/etc/tv/tradingvenue.env`, unchanged since 06-01 11:19). `TV_POLY_MOMO_V2_ENABLED=true`, `momo_v2` ∈ strategy modes.
- **Not market-driven:** Ireland live fired `sol_5m_momo_v2_HOLD` **32× on 06-02** off the same momo_v2 signal, so
  the signal *was* triggering — VPS3 shadow simply wasn't evaluating the sleeve (0 signals = not scheduled/registered).

→ **Root cause:** the 06-02 01:37 CEST restart loaded the engine's **uncommitted working tree** (30+ modified files,
last commit May 29), and in that build `poly_updown_{btc,sol}_5m_momo_v2_HOLD_f7` are no longer registered/scheduled
while `eth_5m` and the 15m variants are. A **registration/scheduler regression** silently removed exactly those two —
a new instance of the "silent sleeve" class (cf. `TV_AGENT_FIX_SILENT_SLEEVES_2026_06_01.md`). Live (Ireland, separate
box/build) was unaffected, so the shadow A/B for these two sleeves has been **dark for ~24h**.

## Where to look / fix
1. **Confirm at boot:** the engine logs registered sleeve_ids via `poly_updown.momo_v2_controller_registered`
   (`engine/main.py:1706`) — it's written to the **app log file** (`/var/log/tradingvenue/…`), not journald. Check the
   01:37 boot: is `{btc,sol}_5m_momo_v2_HOLD_f7` in the registered list? If absent → registration drop; if present →
   the master scheduler's `(sym,tf)` t+60 dispatch is skipping them.
2. **Code path:** `register_poly_updown(momo_v2_ctrl)` (the `(sym,tf)` slot set) + the t+60 master scheduler dispatch.
   Diff the uncommitted working tree against commit `3a2ff3a9` for changes touching the momo_v2 `(sym,tf)` set or a
   per-symbol 5m guard — something now excludes BTC-5m + SOL-5m but not ETH-5m.
3. **Fast remediation:** restart `tv-engine` and re-check (if a transient boot-order race dropped them, a clean
   restart re-registers). If they drop again → it's deterministic in the working-tree code; fix the registration then
   **commit the working tree** (this is also handoff open-item #3 — running uncommitted code is how this regressed).

## Bottom line
The live and shadow copies are **the same strategy** (80/80 identical where both fire); the PnL gap is **sizing**
($1 live vs $25 shadow), not logic. The genuine divergence is a **VPS3-side silent-sleeve regression**: the 06-02
01:37 engine restart dropped `{btc,sol}_5m_momo_v2_HOLD_f7` from the shadow fleet, so shadow has logged no trades for
them in ~24h while live keeps running. Re-register + commit the working tree.
