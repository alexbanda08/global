# Maker-Arb + Strategy Project — Context Handoff (2026-05-29)

> **Read this first to continue in a fresh session.** Supersedes
> `MAKER_ARB_CONTEXT_HANDOFF_2026_05_28.md`. Self-contained: data state, every key
> finding from the 2026-05-29 session, verdicts, the new directional candidate, and
> next steps. Next session continues pursuing arbitrage / market-maker / positioned-arb
> + (optionally) the directional latency taker.

---

## 0. One-paragraph state
The maker-arb suite (ACC-M/H/PC/MAS/PAT) is **verified net-negative** with the now-honest
engine (E1 settlement fix is live on Ireland). Deep diligence this session shows the
**symmetric market-neutral maker-arb / positioned-arb has no reproducible edge at our
infrastructure** — the profitable wallets win on HFT speed (colo+relay), directional
tilt, or sum<$1 capture that's gone before we can reach it. The one NEW, live-candidate
edge found is a **fast DIRECTIONAL TAKER on the binance→chainlink lag** (intra-window,
distinct from the killed momo line): **OOS +$1.31 per $25 fire, t=2.28, WR 63%, ~59
fires/day**, survives realistic fills. Hedge/stop overlays reduce variance but don't add
return. Canonical data fully refreshed to **May 29 13:17 UTC**.

---

## 1. DATA STATE — canonical refreshed 2026-05-29 13:17 UTC (`migration_2026_05_29/`)
All **core** up-down tables current, single file per data type, downloads deleted
(single-source invariant). Window **Apr 22 → May 29 13:17**.

| table | rows | max-ts |
|---|---:|---|
| klines_1m (binance-spot-ws) | 575,483 | May 29 13:15 |
| klines_1s | 13.38M | May 29 13:16 |
| chainlink_rtds | 8.62M | May 29 13:17 |
| resolutions / resolutions_from_rtds | 42,494 / 39,304 | May 29 13:10 |
| trades_polymarket btc/eth/sol | 39.7M/10.5M/4.6M | May 29 12:47/13:11/13:05 |
| orderbook_l25 btc/eth/sol | 70.7M/13.2M/5.9M | May 29 13:13/14/14 |
| trading_events_30d | 1.13M | May 29 13:18 |

- **L25 merge gotcha:** the old per-refresh L25 deltas were deleted in the 05-27 dedup, so
  `consolidate_l25_to_canonical.py` can NOT rebuild from sources. Use
  `migration_2026_05_29/merge_l25_topoff.py` — streams `[existing canonical + new delta]`
  → temp → atomic replace (ParquetWriter row_group_size=200_000; `metadata==df` verified).
- **SSH-drop gotcha:** a big L25 `\copy` keeps running server-side if SSH drops; use
  `nohup` + poll a `.done` marker (see `migration_2026_05_29/resume_l25_2026_05_29.sh`).
- **binance-1s coverage is only ~May 7→29** → any sub-minute-signal backtest (the latency
  edge) is effectively limited to that ~3-week window, NOT the full Apr 22 range.
- **Canonical L25 is event-driven, median 55ms (61% <100ms)**, NOT a fixed 10Hz — fresh in
  active periods, multi-second gaps when quiet. Always load `subsample_1hz=False`.
- **STALE (not refreshed — different collectors):** Hyperliquid (klines/liqs May 27,
  trades/metrics May 16), OKX/Coinbase/Kraken (VPS2 dormant, ~May 16), cryptocap_dominance
  (~Apr 30), tier1_entries_at_t120 (~May 15, README gotcha #6), clob_resolutions_cache (empty).
  None used by maker-arb/latency work. HL is on VPS3 storedata if ever needed.

---

## 2. MAKER-ARB / MM / POSITIONED-ARB — findings + verdict (THE continued focus)
**Verdict: no reproducible market-neutral maker-arb edge at our infra. Retire the
symmetric sleeves; the only reachable maker edge requires a directional tilt or colo+relay.**

Evidence chain (all this session):
1. **Engine now honest (E1 fix live).** The shadow engine never realized directional-loser
   expiry losses + marked open inventory optimistically → `slug_pnl_so_far`/dashboard drifted
   positive. Fixed on Ireland (`fill_sim.settle_slug` force-settles every slug; EXPIRE rows).
   Verified live (`ENGINE_FIX_VERIFICATION_2026_05_29.md`).
2. **Censoring reversal:** the prior "+$4.44/slug ACC-H-V2" was **survivorship bias** —
   directional losers never got a REDEEM so "settled-only inv=0" excluded them. Uncensored
   truth (settle residuals vs chainlink): all sleeves net-negative. (`MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`)
3. **Backfill:** every sleeve **−$6,599 over 5 days** on the corrected measure. (`MAKER_ARB_BACKFILL_REAL_PNL_2026_05_29.md`)
4. **MERGE is 1:1 EXACTLY** (verified on-chain vs wallet 0x89b5cdaa, 270,341 shares → $270,341).
   **No 0.25% protocol fee.** Our engine's 0.9975 / $0.05-"gas" was a phantom modeling artifact.
   Prior maker-arb backtests understated by ~$0.05/pair. CTF merge/redeem are **GASLESS**
   (Polymarket relayer pays).
5. **Maker rebates real + open to all but small:** Program-2 fee-rebate (20% of taker fee)
   IS active on crypto up-down — 0x89b5cdaa earns ~$1k/day (~18% of its net). Program-1 (the
   big $5M liquidity-rewards pool) is **sports/esports only** for now (crypto "coming soon").
   Rebates are ~$0.35/100sh — too small to save a losing sleeve.
6. **Positioned/sequential leg-in (the RIGHT way) STILL loses:** with free merge + rebates +
   stop/flatten, the sequential leg-in nets **−$0.03/share**. Root cause = irreducible maker
   adverse selection: a symmetric resting bid fills leg-1 on the side the market is moving
   AGAINST (the loser); the ~20% stuck losers (~−$0.40 each) swamp the $0.03-0.06 completed-pair
   spread. (`MAKER_ARB_POSITIONED_PLAN_2026_05_29.md`)
7. **Sum<$1 atomic take-both arb exists but is unreachable:** only **0.004-0.13% of book-time**
   (book sum ≥ $0.9975 ~99.9% of the time), ~$125/day GROSS ceiling, capturable only by winning
   a sub-100ms race vs colocated HFT bots. Not for us without colo+relay.
8. **The profitable maker wallets don't run passive symmetric maker-arb:** 0xb27bc932 (HFT
   scalper, HOLD=−$0.36/$, needs colo+relay), 0xeebde7a0 (HFT mint-sell), 0x04b6d7e9/0x89b5cdaa
   (lb-api +$216k/+$530k but profit is MERGE/sum<$1 capture by fast TAKING + **directional tilt**
   — 0x89b5cdaa buys Down 3.4× more than Up). (`MAKER_WALLET_REEVALUATION_2026_05_29.md`)

**Open avenues for next session (if continuing maker/arb):**
- **Directional-tilted maker:** post maker bids ONLY on the binance-favored side (use the
  latency signal §3), capturing maker rebate + avoiding the adverse-selected loser leg. This
  is the bridge between "maker-arb" and the working directional taker — UNTESTED.
- **Colo + relay** (eu-west-2): only path to the sum<$1 HFT capture. Big infra lift; ~$125/day ceiling.
- Everything else (symmetric ACC-M/MAS/PAT, simultaneous paired bids) is **dead** — don't re-test.

---

## 3. 🟢 NEW CANDIDATE — fast directional taker on the binance→chainlink lag
**The only edge found that clears OOS significance + survives realistic fills.** Full spec:
**`TV_AGENT_SPEC_POLY_FAST_TAKER_2026_05_29.md`** (implement as a shadow sleeve to test).

- **Mechanism:** Polymarket up-down resolves on Chainlink Data Streams, which LAGS Binance.
  Right after a binance move, the resting Polymarket ask is STALE for ~5-20s → buy the leading
  side below fair value.
- **Rule:** anchor on `slot_start` (slug suffix). Fire ~5s into the window when
  `|binance(now)/binance(slot_start) − 1| ≥ 3 bps`. TAKE the leading side (Up if ret>0) at the
  L25 ask ($25 book-walk, spread≤0.05, ~85ms latency). HOLD to chainlink resolution.
- **Result (binance-1s window ~May 7-29, $25, 2%-on-profit fee, native 10Hz, engine_v2 fills):**
  **OOS +$1.31/trade, t=2.28, WR 63.0%, ~59 fires/day** (IS +$2.47, t=2.77). Monotonic
  dose-response: WR 59→64→71→82% as threshold 2→3→5→8bps; edge decays to ~0 by 45-60s.
- **DISTINCT from momo/F7/Cyclops/BDH** — those anchor `ws_s` (PRIOR window) and were mostly
  killed ("efficiently priced"). This anchors `slot_start+offset` (intra-window stale-ask
  pick-off) — never tested before. (`STRATEGY_REEVALUATION_2026_05_29.md` for the momo contrast.)
- **Overlays:** hedge (buy other side on binance reversal) and stop-loss are **variance
  reducers, NOT return adders** — realistic hedge +$1.30 ≈ base (the +$2.16 first pass was a
  top-of-book fill artifact; realistically the other-side ask reprices before you hedge cheap,
  pair cost $1.09). A 15-20¢ stop raises t to ~3.6-4.0 at flat mean — useful for reliability.
- **Reachable on current infra:** edge window is 5-20 SECONDS, not sub-100ms. Ireland is <2ms
  to the CLOB; the live BookMirror (`venues/polymarket/book_mirror.py`) is event-driven; the
  100ms is only the maker strategy poll (irrelevant here). Gasless CTF. Taker-rebate program
  (live 2026-05-28, crypto weight 2.3) offsets the fee — upside.
- **Caveats before capital:** (a) ~3-week window (binance-1s limit); (b) 3bps sweep-selected
  (mitigated by IS+OOS co-significance + monotonic gradient); (c) needs forward OOS.
- **Reports:** `LATENCY_EDGE_FINDING_2026_05_29.md`. **Scripts:** `strategy_lab/directional/`
  (`l25_ask_latency_test`, `realistic_latency_validation`, `latency_walkforward`,
  `latency_threshold_sweep`, `path_overlay`, `hedge_realistic`).

---

## 4. ENGINE BUG MAP — `ENGINE_BUG_MAP_2026_05_28.md` (E1-E17)
Status on Ireland (verified `ENGINE_FIX_VERIFICATION_2026_05_29.md`):
- **E1 (loser settlement / mark) — FIXED + live** (`settle_slug`, EXPIRE rows firing).
- **E2 (MAS-V2 inert gate) — FIXED** (`variant!="v2"` skip; MAS-V2 now trades).
- **E3 (slug-keyed fill routing) — FIXED** (`_lookup_strategy` routes by order_id).
- **E5 (dashboard PnL) — FIXED** (adds cash_recovered; real-pnl drops fee cols).
- **E4 (fee model) — machinery present but NOT activated** (`getattr(...,"curve")` default;
  dashboard ignores fee cols so displayed PnL is real; CSV `slug_pnl_so_far` is slightly
  conservative). To get live parity set `TV_POLY_MAKER_FEE_MODEL=curve_winner`/`legacy_2pct`.
- E6/E7 (convergence-flatten, per-side pair cost) + fill-realism E8-E12 unaddressed (moot if maker-arb retired).

---

## 5. KEY CONVENTIONS / GOTCHAS (reinforced this session)
- **`subsample_1hz=False` MANDATORY** for any L25 backtest (native ~10Hz/event-driven). Used in all this session's scripts.
- **`engine_v2.py` for fills:** `fill_at_book` (book-walk + 85ms latency + spread filter + min_book_events) + `hold_pnl`. `LiveMimicConfig` for latency/spread; production fee = **2%-on-winning-profit-only** (per CLAUDE.md, 25,900 events) — model it directly (won → qty×(1−p)×0.98; lost → −qty×p).
- **Anchor:** momo/F7 use `ws_s = slot_start − window_s` (prior window). The latency taker uses `slot_start + offset` (intra-window) — different, both causal.
- **MERGE = $1 (free, gasless). Outcome truth = chainlink `resolutions_from_rtds`.**
- `python` not on PATH locally — use `py -X utf8`. SSH hosts: `vps3` (185.190.143.7, storedata collector) + `vps_ireland` (85.137.174.152, live+shadow exec, NO collector).

---

## 6. WALLETS (catalog: `wallet_hunt/cache/_directional_wallet_registry.csv` + `_master_catalog.csv`)
- Decoder fixed (`cash_pnl.py`, lb-api truth via `polymarket_api.py`). Profitable up-down
  wallets are directional (binance-lead) or HFT-taker, NOT passive makers. Fresh re-pull
  2026-05-29: 4/5 directional wallets still active; their up-down PnL is a thin sideline
  (~$30-226/day) vs huge other-market PnL.

---

## 7. NEXT-SESSION PRIORITIES
1. **Implement + paper the `poly_fast_taker` shadow sleeve** (`TV_AGENT_SPEC_POLY_FAST_TAKER_2026_05_29.md`)
   on the now-honest Ireland engine. Accumulate fresh OOS trades vs the backtest before any capital.
2. **(Maker/arb continuation)** Test the **directional-tilted maker** — post bids only on the
   binance-favored side (latency signal) to capture rebate + dodge adverse selection. The only
   live maker avenue left.
3. If pursuing the sum<$1 HFT capture: scope the **eu-west-2 colo + relay-wallet** build (the
   `migration_2026_05_29` + `sum_discount_arb_scan.py` are ready to re-run on fresh L25).
4. Optional: top off Hyperliquid from VPS3 if any HL-dependent work resumes.
