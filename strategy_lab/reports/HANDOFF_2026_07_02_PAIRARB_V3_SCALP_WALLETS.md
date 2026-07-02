# SESSION HANDOFF 2026-06-29 → 07-02 — pair-arb ladder v1→v3, scalp live-readiness, b945/ce25 fresh decodes
**Written 2026-07-02 for continuation on another machine. SELF-CONTAINED — the auto-memory files do NOT transfer between PCs; everything needed is here + in the linked reports (all pushed, commit `307b1e4`).**

---

## 0. WHERE EVERYTHING RUNS (infra map)
| box | what | access |
|---|---|---|
| **vps_ireland** (85.137.174.152) | TVRUST rust engine (`tv-rust-engine.service`) — ladder v3 + sumpair_osc + rust sleeve fleet; Python tv-engine (live $1 scalp probes); postgres: `tradingvenue_rust` (rust events) + `storedata` (**python engine's trading.events live here**) | `ssh vps_ireland`, `sudo -u postgres psql <db>` |
| **vps3** (185.190.143.7) | storedata collector (books/trades/oracle) + production Python tradingvenue (shadow fleet); postgres `storedata` holds BOTH collector tables AND python `trading.events` (`TV_DB_URL` → storedata) | `ssh vps3` |
| local | repo `Desktop/global` (this), rust repo `Desktop/TVRUST`, archives `D:\global_data\` | py = Python 3.14 + pandas |
- SSH keys: `~/.ssh/{config, vps_ireland_ed25519, vps3_ed25519, vps2_ed25519}` (copy to new PC).
- Canonical data local ends ~Jun 15. v1 ladder DB archived: `D:\global_data\ireland_archive\` (pg_dump 93MB + trading_events tsv.gz 50.8MB, sha256 in `TV_AGENT_SPEC_LADDER_V2_RESIDUAL_PVSGATE_FRESH_2026_06_30.md` §4). **Old `tradingvenue_rust` v1/v2 data NOT yet deleted on Ireland (delete authorized post-v3-confirm; 53G free, not urgent).**

## 1. THE PAIR-ARB LADDER THREAD (the main event)
**v1 (at-touch ladder + 4-conn racer, Jun 16–30, 13.4d, 1,161 windows)** — `IRELAND_LADDER_FULL_DECODE_HANDOFF_2026_06_30.md`: pair_frac **0.80** live (offline sim ceiling was 0.29 = the old NO-GO → **overturned**); matched-pair locked arb **+$1,611 outcome-independent**; residual unmeasured (no telemetry).

**v2 (G1 residual telemetry + G3 pvs≤0.99 gate, Jun 30–Jul 2, 142 clean windows)** — `IRELAND_LADDER_V2_FIRST_RESULTS_2026_07_01.md` + fresh re-pull: **NO-GO as configured**. total_net **−$0.91/win CI[−1.50,−0.32]**. Decomposition: paired **+$1.51/win** (gate works: 0% pvs>1 vs 33% in v1; pvs 0.853) + rebate +0.04 − residual **−$2.46/win**. Residual = **adverse selection −5.5σ**: heavy-filled side wins **14.1%** at entry 0.396 (breakeven 40%); big residuals win 6.9%. Counterfactual on same tape: flatten residual at ≤$0.05/sh → **+$1.21–1.62/win**. `outcome` field ground-truthed 3/3 vs Binance. All analysis scripts + tapes: `strategy_lab/directional/_ireland_6day/` (`analyze_v2.py`, `ladder_summary_v2.tsv`).

**Fresh wallet decodes (Jul 2) — the design answer** — `PAIRARB_LADDER_VS_CE25_HEADTOHEAD_2026_07_02.md` (THE key doc, §3b/3c/3d):
- **ce25/Agile-Spacing** (`0xce25e214d5cfe4f459cf67f08df581885aae7fdc`): lifetime **+$384.6k** (+$84k in 3wk ≈ $4k/day; fresh 8.5h window ≈ +$1.8k/day fee-adj) on only **~$2.4–5k working capital**; 8 markets (btc/eth/sol/xrp × 5m/15m), ~810 slugs/day; signature EVOLVED since Jun-12 decode: multi-clip (12 fills/slug, med $8.25), spread across whole window (14.7% first-60s vs 78% before), pair rate 86%, pair_frac 0.55, 0% sells. Fill classification vs pre-fill VPS3 books (820 fills, book age 0.78s): **MAKER 42.5%$ / TAKER 47.2%$, maker bids −1 tick med (p10 −5) BELOW the touch**. BTC +$11.23/slug; SOL/XRP negative even for him.
- **b945** (`0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68`, the design source): lifetime **+$28,286** (~$100–310/day — NOT the 1–2k/day wallet, that's ce25). **Added btc-5m**; fresh 2.95d: **btc-5m +$4.22/slug (n=188) vs btc-15m −$6.70/slug (n=76) — he LOST on 15m the same days our 15m ladder lost** (regime, not just design). pair_frac 0.36, pvs≈1.00, 11.4 fills/slug. Classification (n=115 thin): MAKER 42.8%$/TAKER 51.8%$, maker bids **−3 ticks med (p10 −9)**.
- **THE LESSON (convergent evolution): nobody profitable quotes at the touch.** Our at-touch v2 absorbed informed window-scale sell flow (= exit liquidity → toxic residual); their fills are dip/overshoot-selected (deep bids + dip-taker clips). We harvest the pair and eat the residual; they harvest the residual and tolerate the pair.

**v3 DEPLOYED (Jul 2, TV agent confirmed, tests green)** — spec `TV_AGENT_SPEC_LADDER_V3_DEEPQUOTES_5M_2026_07_02.md`, scope = "Core v3, recycle fast-follow" (operator-chosen):
- Sleeves: **`poly_ladder_btc_15m_v3` + `poly_ladder_btc_5m_v3`** (v2 stopped clean, 0 rows post-restart).
- **Deep quotes**: `TV_LADDER_QUOTE_DEPTH_TICKS=2` — rest 2 ticks below touch, never at/above (verified in ladder_tick: best_bid 0.50 → resting 0.48); composes with pvs cap.
- **T−tail taker-flatten backstop** (60s/15m, 45s/5m) wired into G1 (`residual_pnl` = flatten + held remainder); GLT-cap skew pause kept; **maker-recycle deferred to v4** (justified: both wallets show 0% sells — they fix residual via fill selection, not recycling).
- New telemetry: `quote_depth_ticks`, `fill_below_touch_ticks_{up,dn}`, `residual_{recycled,flattened}_sh`, `residual_backstop_cost_usd`. `pair_gate_bound_sh` fixed.
- **Depth-4 A/B variant BUILT but OFF** (`TV_LADDER_D4_ENABLED` unset). Decision given to agent: flip after 8-conn setup proves stable a few hours; when enabling, prefer it SHARING the 15m d2 book feed (else confirm `feed_quality.book_age` parity — single-conn vs 4-conn would confound the depth A/B).

## 2. SCALP THREAD (btc_5m_d3 exit-scalp)
- **Rust impl audit** (`IRELAND_RUST_IMPL_AUDIT_2026_07_01.md`): rust resolve tape = HOLD PnL for all sleeves (losses exactly −$5); ScalpExit sell loop spawned (`sniper.rs:1418`) but result reached no event; entry band (0,0.55) only on live path → rust twin's −0.074/tr was a hold-counterfactual on unbanded (ev 0.63) entries, **NOT the edge**. → fixes SHIPPED by TV agent (`8dd4881`): band on paper path + `scalp_exit` events + pure +60s knobs. **sumpair_osc ALSO enabled in same commit** — both accruing now.
- **True tape** (`SCALP_RETRO_AND_TRUE_TAPE_2026_07_02.md`): VPS3 Python shadow (`poly_updown_scalp_exit` events, exact deployed config) = **+$0.783/tr CI[+0.36,+1.21], n=77, WR 65%, band 100%** — edge ALIVE, consistent w/ corrected OOS +0.91. Weekly $/tr 0.04→0.42→0.96→0.65 (regime-tracking). **Retro-computation structurally impossible**: storedata subscribes each 5m market ~+117s (canonical: 2% of slugs have books by +5s) — scalp moments exist ONLY in engine ws_mirror books.
- **Live-readiness audit** (`SCALP_LIVE_READINESS_AUDIT_2026_07_02.md`): 🔴 **the Python LIVE path NEVER SELLS** — real $1 entry + SIMULATED +60s exit; real tokens ride to resolution (17 on-chain redeems) → live money ran the strategy WITHOUT its edge and **drained the wallet to $1.77** (76+ CLOB "not enough balance" rejections since Jun 26 — journalctl-only, invisible in trading.events). Fire-rate gap = wallet (Jun 26+) + unexplained Ireland-vs-VPS3 gate divergence Jun 11–25 (0 vs 79 all-pass on `g_oracle_lag_with(3,12)`, same cadence — open follow-up). $1 clips ≈2 shares = below ~5-share venue min; marketable-limit 0.99 needs ~2× collateral.
- **Min capital**: $5 clips (validated size) = fund **~$150**, +$101/mo expected, ≥200-fire gate ≈45–50d; $25 = ~$300, +$505/mo (depth-safe). Max concurrent = 1.
- **⏸ OPERATOR DECISION PENDING: the live-sell patch requires touching frozen Python Tradingvenue** (one branch in `maybe_scalp_exit`) OR waiting for the TVRUST scalp to become live-capable. Recommended: grant the one-patch exception + notional $1→$5 + raise `SNIPER_V5_LIVE_MAX_NOTIONAL` ($2 cap, `polymarket_sniper_v5.py:97`) + allowlist btc_5m_d3 only + persist order rejections as events. **DO NOT fund the wallet before the live-sell exists.**

## 3. FOUR PAPER STREAMS NOW ACCRUING (as of Jul 2 ~13:00 UTC)
1. `poly_ladder_btc_15m_v3` (deep quotes + backstop)
2. `poly_ladder_btc_5m_v3` (new market)
3. `sumpair_osc` (dip-taker engine; logs BOTH fill models — `net_pnl_level0` vs `net_pnl_walk`, `partial_frac` — settles the +0.52-level0 vs −0.70-walk question)
4. Fixed rust scalp twin (banded + `scalp_exit` events)

## 4. #1 NEXT ACTION — the verify pass (~24h after deploy, then ~1wk read)
On Ireland `tradingvenue_rust`:
```sql
SELECT sleeve_id, data->>'fill_below_touch_ticks_up', data->>'total_net_usd', data->>'residual_flattened_sh'
FROM trading.events WHERE sleeve_id LIKE 'poly_ladder_btc%_v3' AND kind='ladder_summary'
AND (data->>'pair_frac')::float>0 ORDER BY at DESC LIMIT 5;
```
Checklist: (a) both v3 sleeves emitting, no v2 rows, nothing live-armed; (b) `fill_below_touch_ticks_mean ≥1` on traded windows (≈0 = depth not applied — #1 failure mode); no fill at/above touch; pvs<0.99; `pair_gate_bound_sh` counting; (c) backstop fires T−60/45s, `residual_backstop_cost_usd` logged; (d) NO maker-recycle path (deferred); (e) `total_net = paired + rebate + residual − backstop` exact; outcome vs Binance 3 slugs; (f) 5m warmup OK; (g) sumpair_osc rows with both fill models; (h) scalp twin: 100% in-band entries, `scalp_exit` present, losses NOT clustered at −$5. Then ~1wk: net CI per market, our fill-depth distribution vs the wallets' (−1..−3 ticks), d4 curve if enabled. **Pre-registered go-live gate: total_net CI>0 ≥1wk + `tv-watchdog` deployed (STILL MISSING — hard prerequisite for any live arm).**

## 5. OPEN ITEMS (other agents / later)
- **storedata agent**: (1) `orderbook_deltas_v2` broke AGAIN Jun 30 18:24 (7.15M rows then stopped) — diagnosis `STOREDATA_DELTA_WRITE_REGRESSION_2026_06_29.md`; (2) snapshot stream intermittent (Jul 2: coverage only 01:00–05:03; ~13 rows/s vs historical 1–2Hz — dedup possibly removed, verify intentional); (3) NO XRP oracle/books anywhere; `market_resolutions_v2` ~50% slug gaps; (4) proposed: pre-subscribe markets at discovery (+~20MB/day, negligible — enables offline scalp research).
- **TVRUST v4 backlog**: maker-recycle (only if v3 residual still bleeds), multi-clip re-test on clean delta data (MAX_CLIPS=1 verdict has live counter-evidence: both wallets ladder ~12 clips/slug), market expansion BTC-5m→ETH (skip SOL/XRP — negative even for ce25).
- Ireland-vs-VPS3 scalp gate divergence (0 vs 79 all-pass, Jun 11–25) — unexplained, matters because live runs on Ireland but the validated tape is VPS3's.
- Delete old `tradingvenue_rust` v1/v2 partitions on Ireland once v3 confirmed (backup exists on D:).

## 6. GOTCHAS BANKED THIS SESSION (don't re-learn)
- **data-api hard cap: offset≤3000 (~3.5k rows), no time params** → full-day decode of high-freq wallets needs Alchemy chain pulls. lb-api profit/volume accept ONLY `window=1d|all`. **gamma-api `/events?slug=` resolves ALL coins incl XRP** (100% agreement w/ vps3 where both exist).
- lb-api/data-api from python urllib need a `User-Agent` header (403 otherwise). context-mode hook blocks `curl` in Bash — use `py` urllib.
- Fill classification method: join fills to last pre-fill snapshot (≤15s stale) → price ≥ask0 = taker, ≤bid0 = maker.
- Fee truths: winner-only `0.07·p·(1−p)` resolution fee; Python scalp charges the sell-leg fee UNCONDITIONALLY (conservative, stale "$0 proxy" docstring); maker/redeem $0. Rust `resolver.rs` books hold-PnL generically.
- Ireland Python engine writes to its LOCAL `storedata` DB (`TV_DB_URL`), same pattern as VPS3. Balance rejections appear ONLY in journalctl, not DB.
- Odd-level price↔size corruption is LIVE in `orderbook_snapshots_v2` too — level-0 reads safe, deep levels swap-if-price>1.
- Windows: `df.at` collides with pandas indexer (rename to ts); heredoc SSH quoting — use plain single quotes; pandas to_csv int64 cols can emit `.0` (cast before slug-building).

## 7. KEY REPORT INDEX (all in `strategy_lab/reports/`, pushed @ `307b1e4`)
`PAIRARB_LADDER_VS_CE25_HEADTOHEAD_2026_07_02.md` ← START HERE (the design verdict) · `TV_AGENT_SPEC_LADDER_V3_DEEPQUOTES_5M_2026_07_02.md` (what's deployed) · `IRELAND_LADDER_V2_FIRST_RESULTS_2026_07_01.md` · `IRELAND_LADDER_FULL_DECODE_HANDOFF_2026_06_30.md` · `CE25_FRESH_DECODE_2026_07_02.md` · `SCALP_LIVE_READINESS_AUDIT_2026_07_02.md` · `SCALP_RETRO_AND_TRUE_TAPE_2026_07_02.md` · `IRELAND_RUST_IMPL_AUDIT_2026_07_01.md` · `TV_AGENT_SPEC_SUMPAIR_START_SCALP_TELEMETRY_2026_07_01.md` · `TV_AGENT_SPEC_LADDER_V2_RESIDUAL_PVSGATE_FRESH_2026_06_30.md` · raw tapes/scripts in `strategy_lab/directional/_ireland_6day/`.

**GROUND-TRUTH RULE applies as always: verify against actual fills/events/on-chain before believing any number — this session alone retracted three of its own intermediate conclusions by doing exactly that.**
