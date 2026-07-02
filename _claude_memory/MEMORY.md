# Memory Index

## Feedback
- [Subagent model](feedback_subagent_model.md) — always spawn Agent subagents with model "sonnet"
- [Canonical refresh](feedback_canonical_refresh.md) — canonical data refreshes from VPS3 storedata only (Ireland = shadow/live exec, no collector); merge then delete the downloaded refresh dir

## Project
- [aliplayer frozen](project_aliplayer_frozen.md) — HF aliplayer BBO dataset frozen at Apr 21 2026, NOT auto-updating (handoff is wrong)
- [sleeve PnL metric](project_sleeve_pnl_metric.md) — rank sleeves on TV dashboard dedup metric, NOT raw events.pnl_usd (double-counts/inflates; lagv2 +$1681→−$195)
- [Kalshi early-book CORRECTED](project_kalshi_scalp_deprecated.md) — "+30s no-book" was observability (subscribe-late), NOT missing liquidity; pre-subscribe via status=unopened fixes it → early-offset 15m sleeves become Kalshi-tradeable
- [Scalp exit config](project_scalp_exit_config.md) — FINAL 2026-06-11: PURE +60s time sell, TP OFF + STOP OFF both hosts (old +0.88 stop claim = harness artifact; maker-exit also dead); entry unchanged
- [Scalp mid-window dead](project_scalp_mid_window_dead.md) — mid-window/FVG/cross-asset/regime scalp variants all tested dead (2026-06-09); edge is open-only, don't re-scaffold
- [Scalp OFI gate dead](project_scalp_ofi_gate_dead.md) — Binance 1s taker-OFI gate (2026-06-16) NO edge; scalp edge is INVERSELY related to flow intensity (thin moves lag more); don't gate scalp on flow/CVD/aggressor signals
- [Retro audit findings](project_retro_audit_findings.md) — 2026-06-10 master audit: scalp exit-fallback outcome-leak bug, Mar30-Apr21 OOS burned, Feb-Mar window fixable for free; E1 repair package before any scaling
- [0xf70d is pUSD contract](project_f70d_is_pusd_contract.md) — 0xf70da97812 = Polymarket pUSD deposit contract funding ALL wallets; never use it for wallet clustering ("F1 treasury" claim invalid)
- [5-lens audit 2026-06-12](project_5lens_audit_2026_06_12.md) — scalp fee proxy unverified ($0.15-1.50/tr inflation bound), 1s bar-start asof lookahead all drivers, only honest OOS left = Feb21-Mar24 one-shot; full report STRATEGY_AUDIT_5LENS_2026_06_12.md
- [sum-pair: taker DEAD, signal-gated REAL](project_sumpair_arb_dead.md) — taker-simultaneous DEAD (overround, sub-100ms revert); BUT signal-gated OSCILLATION-HARVEST (buy each side at its own Binance-lag dip, accumulate, pair-hold) is a REAL thin edge: +$0.52/slug OOS (1-clip), 5m-only, survives markout +8¢/30s; beats deployed scalp; depth-realism test pending
- [synthetic-book marginal](project_synthetic_book_marginal.md) — "buy YES=sell NO" fill upgrade tested on scalp OOS: no-arb inert on priceable fires, ~$6/day rescue only, NOT deployed
- [b945 decoded + replication plan](project_b945_thread_parked.md) — +$21,742 audited; engine = EARLY-placed two-sided GTC ladders, paired sum<1 capture (pvs 0.968); btc-15m markets tradeable ~24h pre-window (= the queue-priority moat); NO merge loop; never apply taker fees to maker fills; TVRUST build plan in B945_ARTICLE_INFRA_GAP_ANALYSIS §8
- [L25 collector drops the delta stream](project_offline_feed_blind_to_edge.md) — persisted full-book ~1-2Hz is ~92% faithful for COARSE fills, BUT `price_change` deltas (high-freq, "hundreds/sec") are RECEIVED & DISCARDED (Phase 15-05 no-DB-write) → no queue dynamics for maker/b945 modeling; FIX=persist scoped deltas (`L25_FEED_GAP_DIAGNOSIS §8`). Also: "feed blind 49%" was MY join bug (used data-API poll-time `local_timestamp_us`); join book↔trade on `timestamp_us` (exchange) only. Deltas now LIVE+verified on VPS3 (btc-15m ~145/s); Phase-2 consumption pipeline built.
- [L25 deep-level corruption](project_l25_level_corruption.md) — canonical L25 + source snapshots have price↔size SWAPPED on ODD book levels (level 0 + even OK); deployed L0 logic safe, deep-book reads corrupted-but-recoverable (swap if price>1); fix storedata collector (emit-tuple vs migration-008 order) + add de-corrupt to load_orderbook_l25_streaming; new delta table is CLEAN
