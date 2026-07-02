# HANDOFF — Hyperliquid research → V52/XSM shadow deploy + sleeve cards

**Date:** 2026-06-11 (work spanned a multi-day thread; data refreshed to 2026-06-09/10)
**Scope:** Port Polymarket indicator/logic library to **Hyperliquid PERPETUAL futures** (NOT up/down
markets). Audit + optimize the existing V52 + V24-XSM HL strategies. Wire BOTH into shadow mode.
Build HL sleeve cards. Diagnose why the production TV dashboard HL cards show no activity.

**READ FIRST if continuing this thread.** GROUND-TRUTH RULE applies.

---

## TL;DR

1. **New HL research dir:** `strategy_lab/hl_research_2026_05_26/` — full perp-native research run
   (engine, feature panels, 6 strategy families, PDFs). The user twice corrected scope: this is
   **perpetual futures**, not Polymarket binary. Indicators/logic ported; strategy STRUCTURE is
   perp-native (continuous PnL, funding, leverage, ATR/signal-flip/trailing exits — NOT binary
   fixed-window).
2. **Shadow system LIVE (paper) at `shadow_v52/`** — hourly Windows task `V52Shadow` runs a tick:
   refresh HL data → V52 (9 sleeves) → XSM basket → sleeve cards → 6-card TV feed. **$0, no orders.**
3. **V52 + XSM both wired & reporting.** V52 = 9 per-coin sleeves (46 paper fires/60d). XSM =
   correctly FLAT (defensive filter; breadth 1/9 in current weak regime). Neither is "broken";
   both are mostly flat because 2026 is V52's weak regime + XSM's filter gates it off.
4. **Production TV dashboard cards still need VPS3 wiring** — see §5. My local system produces the
   exact card payload; a TV deploy spec was written for the VPS3 agent to port.

---

## 1. Research run (`strategy_lab/hl_research_2026_05_26/`)

Perp-native rebuild after the user corrected the initial (wrongly Polymarket-shaped) attempt.

- **Engine:** `hl_engine.py` — `HyperliquidConfig` (taker 4.5bps×2, maker 1.5bps, hourly funding
  accrual @1.25bps/hr cap, 50ms latency, leverage). `perp_exit_rules.py` — signal-flip / ATR-trail /
  ATR SL+TP / regime-change / fixed-bars exits + `run_strategy` + `summarize`.
- **Feature panels:** `build_hl_panel.py` → 24 panels (143 cols) in `panels/` (TA/QR/SMS/TR/RF/DRZ/
  regime/Markov + HL funding/liq/OI). Binance backbone (8.6y BTC/ETH, 5.6y SOL) + HL-native.
- **6 perp families tested (`wave2_perp/`):** A trend, B mean-rev, C breakout, D carry, E regime
  composite, F ML-sized. Aggregated → `MASTER_TABLE_PERP.{csv,md}` (3,929 cells).
  - **Winners:** D1 basis-carry (HL vs Binance spot-perp) strongest; A1 ETH 4h Donchian OOS Sharpe
    3.32 (beats BH 5.6×); C ETH-4h breakout cluster (6 cells all-gates). D2 verdict: funding
    CONTRARIAN beats momentum on all 4 coins.
  - **Rejected:** mean-reversion (crypto perp is momentum), ML probability-trading (fees > AUC edge),
    2-venue hedged arb (D3), funding-regime composite (D4 fails G7), all <4h non-carry TFs.
  - Honest caveat banked: D1 carry Sharpes (3-12) are on a 107-day HL window = small-sample/overfit
    risk; expect 30-60% OOS degradation. A1 trend on 8.6y is the most trustworthy.
- **Reports:** `PAPER_DEPLOY_CANDIDATES_PERP.md` (final), `HL_DEPLOY_SPEC.pdf` (clean 15-page),
  `MASTER_PLAN.md`, `INDICATOR_REGISTRY.md`, `HL_DATA_AUDIT.md`, `EXISTING_HL_STRATS.md`.

**Data corrections banked (CLAUDE.md was wrong):** Binance per-symbol archive
`data/binance/parquet/{SYM}/{TF}/year=*/` = **8.6y BTC/ETH, 5.6y SOL, 5-8y alts** (NOT 12 months).
HL canonical = **4 coins (BTC/ETH/SOL/HYPE), 106 days, NOT 2.3y**.

---

## 2. V52 + V24-XSM audit + optimization (`hl_research_2026_05_26/v52_v24_audit/`)

**Audit (`AUDIT_REPORT.md`): NO BUGS.** Funding sign correct, HMM no leak, signals causal. The
"flat" the operator saw = **HL parquet data was 32-44 days stale** (the real blocker) + 2026 is a
regime-driven slowdown (alt vol −30%, funding ⅓ of 2024), NOT a code fault. V24-XSM flat is
BY DESIGN (filter passed only ~4.5% of 2026 bars). V52 has no native BTC sleeve.

**Optimization (`OPTIMIZATION_RESULTS.md`), all walk-forward-positive:**
- **New STF_BTC_V45 sleeve** (fills missing BTC slot): Sharpe 1.00, 2026 Sh +3.61 (counter-cyclical).
- **FUND_Z<2 gate** on the 5 V41-family sleeves (|rolling-500 funding z| < 2): +0.07..+0.21 Sharpe;
  STF_AVAX permutation p=0.000.
- **ATR_NOTOPVOL gate** on the 4 volume diversifiers (ATR rolling-500 pct-rank < 0.80): +0.18..+0.53.
- V24-XSM relaxations ALL hurt (keep original 5/9-breadth filter). V52+V24 blend HURTS (keep separate).

---

## 3. Shadow system (`shadow_v52/`) — LIVE (paper)

**Scheduled:** Windows task **`V52Shadow`** runs `shadow_tick.bat` → `shadow_tick.py` hourly
(idempotent; hourly catches each 4h-bar fire within ~1h without timezone fiddling).

**Tick pipeline:** incremental HL data refresh → V52 runner (9 sleeves) → XSM eval → sleeve cards →
6-card TV feed.

| File | Role |
|---|---|
| `shadow_tick.py` / `.bat` | scheduled unit (refresh + run all). `tick.log` = output. |
| `_register_task.py` (`--delete` to remove) | register/remove the hourly task |
| `v52_v24_audit/v52_shadow_runner.py` | 9 V52 sleeves: signal+gate+exit+fire detection (recompute-from-history each run; no state drift) |
| `xsm_shadow.py` | V24 multi_filter basket evaluator (9-coin: HL for BTC/ETH/SOL/AVAX/LINK + Binance for ADA/XRP/BNB/DOGE) |
| `build_sleeve_cards.py` → `cards/*.json` + `SLEEVE_CARDS.md` | 10 per-sleeve cards (spec+metrics+live) |
| `tv_cards_feed.py` → `_tv_cards_feed.json` | **6 per-coin dashboard cards** (the TV target schema) |
| outputs: `positions_latest.csv`, `fires_ledger.csv`, `pending_fires_latest.csv`, `STATUS.md`, `XSM_STATUS.md`, `run_log.csv`, `xsm_status.csv` |

**The 9 sleeves (exact spec in the runner + TV spec):**
- V41-family (gate FUND_Z<2, weight 0.12): STF_BTC(V45), CCI_ETH(V41), STF_SOL(base), STF_AVAX(V45), LATBB_AVAX(base)
- Volume diversifiers (gate ATR_NOTOPVOL, weight 0.10): MFI_SOL(V41), VP_LINK(base), SVD_AVAX(base), MFI_ETH(base)
- Exits: EXIT_4H (tp10/sl2/trail6/hold60 ATR) baseline; V41/V45 use regime-adaptive REGIME_EXITS_4H (HMM train_frac=0.30 seed=42).

**Controls:** `schtasks /Run /TN V52Shadow` (fire now) · `schtasks /Query /TN V52Shadow` · `py shadow_v52\_register_task.py --delete` (stop).

---

## 4. The 6 dashboard cards = per-coin bundles

| Card | Bundle |
|---|---|
| V52-BTC | STF_BTC |
| V52-ETH | CCI_ETH, MFI_ETH |
| V52-SOL | STF_SOL, MFI_SOL |
| V52-AVAX | STF_AVAX, LATBB_AVAX, SVD_AVAX |
| V52-LINK | VP_LINK |
| V52-XSM | V24 multi_filter basket (0% live; only 5/9 coins HL-tradeable) |

Card SIGNAL = sign(Σ weight·dir over OPEN sleeves); CONFIDENCE = round(100·|net|/bundle_weight).
Live example from the reference feed: **V52-AVAX = LONG conf 29** (one AVAX sleeve open).

---

## 5c. 2026-06-16 INCIDENT — Postgres OOM outage + card signal endpoint isolation

**Symptom:** operator reported HL cards still empty (`SIGNAL FLAT / CONFIDENCE —`) after 5b, even
though headers now showed `bundle: HL_V52_SHADOW` (the bundles fix held).

**Root cause chain (deeper than 5b):**
1. The card `SIGNAL/CONFIDENCE` (both collapsed header + expanded) is rendered from the
   `/sleeves/{id}/signal/current` endpoint (NOT `SleeveManifestRow`, which has no direction field).
2. My 5b patch read `_deps.pool` — but the shared tv-api pool was throwing `acquire` TimeoutErrors.
3. **The actual cause: Postgres (`postgresql@17-main`) was OOM-killed at 2026-06-16 08:53 CEST and
   stayed DOWN ~5h** (`Restart=no`, no swap). No DB → tv-api pool dead → every card fell to the stub.

**Fixes applied (VPS3):**
- **Restarted Postgres** (RAM was free again; `systemctl start postgresql@17-main`), then restarted
  tv-engine + tv-api to reconnect. Verified: regime models intact (5), hl_bars fresh, DB accepting.
- **Made the card signal endpoint resilient to shared-pool exhaustion:** rewrote
  `backend/app/api/_hl_signal.py` to use its OWN small asyncpg pool (`TV_DB_URL`, max 2,
  `command_timeout=10`) + a 60s TTL cache (one query burst / 60s for all 6 cards), and re-patched
  `get_signal_current` to call `compute_hl_signal(sleeve_id)` with NO `_deps.pool` guard. So the cards
  keep working even when the busy write pool times out. Patch/helper: `migration_2026_06_08/
  {_hl_signal.py,_patch_sleeves2.py}`; backups `sleeves.py.bak-hlcards2-*`.

**Verified live (DB up):** `V52-SOL=LONG conf 0.333`, `V52-AVAX=SHORT conf 0.333`, ETH/LINK FLAT,
BTC no-stream, XSM FLAT — all `blocked=False` (UI shows real signal). Signals evolve per bar.

**RELIABILITY FIXES APPLIED 2026-06-16 (operator-authorized "wire everything"):**
- **8 GB swap** added (`/swapfile`, persisted in `/etc/fstab`, `vm.swappiness=10` via
  `/etc/sysctl.d/99-tv-swappiness.conf`) — active now; prevents the OOM-kill that took the DB down.
- **Postgres auto-restart** drop-in `/etc/systemd/system/postgresql@17-main.service.d/override.conf`
  (`Restart=on-failure`, `RestartSec=10`, `StartLimitBurst=5`, `OOMScoreAdjust=-600` so the kernel
  kills other processes before the DB). Source: `migration_2026_06_08/postgres_override.conf`.
  `OOMScoreAdjust` applies on the next DB restart; swap is the active protection meanwhile.
- `tv-engine` + `tv-api` already had `Restart=on-failure` → the whole stack now self-heals.
- HL cards bypass the busy shared write pool entirely (own pool + 60s cache), so they keep serving
  even under DB pressure. Other endpoints still use the shared pool (separate scaling concern).

**Remaining (optional):** root-cause the memory spike that triggered the original OOM (lower
`shared_buffers`, or profile the engine's peak); not required now that swap + OOMScoreAdjust protect it.

## 5b. RESOLVED 2026-06-14 — production TV dashboard HL cards wired LIVE on VPS3

The `SHADOW (6)` HL cards (`V52-BTC/ETH/SOL/AVAX/LINK` + `V24-XSM`) were dead (`bundle: none`,
`SIGNAL FLAT`). Root-caused + fixed directly on VPS3 (185.190.143.7, `ssh vps3`):

1. **Regime models were never seeded** (`engine.v52_regime_models` empty, `/var/lib/tradingvenue/v52/`
   missing) → V52 sleeves abstained → all-flat. `engine.hl_bars` only retains 7d so the canonical
   2024 train window wasn't present. **Fix:** backfilled 2024 HL 4h bars via candleSnapshot API
   (`migration_2026_06_08/_hl_2024_backfill.py`, 999 bars/coin Mar–Aug 2024 into `engine.hl_bars`),
   then fit the 3-component GMM per coin (`_v52_fit.py` — the prod `scripts/v52/fit_regime.py` has a
   str-vs-date asyncpg bug + writes to the wrong dir `/var/lib/tv/v52`; my fitter writes to the
   engine's `/var/lib/tradingvenue/v52/regime_{COIN}.json` + `engine.v52_regime_models` pointer).
2. **`/etc/tv/bundles.yaml` missing** → `bundle: none`. **Fix:** installed bundles.yaml (root:tv 0640)
   with `HL_V52_SHADOW` (5 coin cards) + `HL_XSM_SHADOW`, both `paused: true` (= shadow). Source:
   `migration_2026_06_08/bundles.yaml`. The API reads it live.
3. **The card signal endpoint `get_signal_current` was a hardcoded 23-02 STUB** returning
   `direction=FLAT, blocked=True, block_reason='awaiting_first_bar'` for EVERY sleeve (plans
   23-03/23-05 never built). This was THE reason nothing ever showed. **Fix:** added
   `backend/app/api/_hl_signal.py` (`compute_hl_signal` — runs the deployed V52 controllers'
   `signal(bars)` on recent `engine.hl_bars`, aggregates the per-coin bundle → direction+confidence)
   and surgically patched `get_signal_current` (HL branch, try/except fallback to stub, Poly path
   unchanged). Patch + helper: `migration_2026_06_08/{_hl_signal.py,_patch_sleeves.py}`. Backup at
   `sleeves.py.bak-hlcards-*`.
4. Restarted `tv-engine` (loads regime+bundles, boots clean, `v52.registered` n=10, no
   `regime_dir.missing`) + `tv-api` (loads patched endpoint, clean).

**Verified live:** `V52-ETH = SHORT conf 0.667` (CCI_ETH_P3+P5 short), SOL/AVAX/LINK real-FLAT,
BTC FLAT (no BTC stream deployed — VPS3 V52 is the original 10-stream blend, my STF_BTC + FUND_Z/
ATR optimizations are NOT on VPS3 yet), XSM FLAT. Cards now show real signals + bundle, `blocked=False`.

**Durability caveats:** (a) a `git pull`/redeploy on VPS3 would overwrite the `sleeves.py` patch +
`_hl_signal.py` — reapply from `migration_2026_06_08/`. (b) The 2024 `hl_bars` I inserted get swept by
7d retention, but the regime JSON files persist (that's what the engine reads). (c) V52 is daily-
rebalanced + sparse — cards read FLAT most of the time by nature (weak 2026 regime), NOT a bug.
(d) To deploy my optimized fleet (STF_BTC sleeve + FUND_Z/ATR gates) on VPS3, port the controllers
+ re-seed streams — separate task.

## 5. (ORIGINAL OPEN — superseded by 5b above) production TV dashboard wiring (VPS3)

The operator dashboard `SHADOW (6)` HL cards show `bundle: none` / no activity because **the VPS3
TV engine has no HL loop** — it only runs Polymarket loops. My local system can't feed the VPS3
dashboard. **Deliverable handed off:** `strategy_lab/reports/TV_DEPLOY_SPEC_HL_V52_XSM_SHADOW_2026_06_09.md`
— defines a new `hl_perp_loop` (4h), the 9 sleeve signals + 2 gates verbatim, per-coin bundling,
SIGNAL/CONFIDENCE aggregation, fire logging, and points at `shadow_v52/` as the reference impl to
port (same pattern as `shadow_engine/` was ported for Polymarket).

**NEXT for the TV agent:** port that spec into the VPS3 engine; verify card states match
`shadow_v52/_tv_cards_feed.json`. Until then the production cards stay flat.

---

## 6. Reality / promotion gates (before ANY HL capital)

- SHADOW ONLY, $0. Per V52 deploy notes: ≥4 weeks shadow, aggregate Sharpe > 1.2, funding accrual
  reconciles ±5%, no sleeve hits −12% DD. STF_BTC brand-new (never live) — watch closest.
- XSM stays 0% until the HL coin universe widens past 5/9.
- V52 win-rate is ~35% by design (small stops, big trailing TPs; edge is the asymmetric exit).
  2026 is its weak regime — sparse fires, lower returns until vol/funding return.

---

## 7. Data state at handoff

- HL klines+funding (BTC/ETH/SOL/AVAX/LINK 4h) fresh to **2026-06-09/10** via
  `strategy_lab/ingest_hyperliquid.py` (incremental; the tick keeps it current).
- Binance per-symbol 4h refreshed for the XSM 9-coin universe via `fetch_binance_multi.py`.
- NOTE the separate Polymarket canonical pipeline (CLAUDE.md top) is unrelated to this HL stack.
