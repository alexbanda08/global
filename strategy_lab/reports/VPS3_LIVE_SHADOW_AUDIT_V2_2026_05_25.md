# VPS3 live shadow audit — v2 with fresh local data (2026-05-25 19:21 UTC)

_Update of `VPS3_LIVE_SHADOW_AUDIT_2026_05_25.md` after the user refreshed local `trading_events_30d.parquet` from VPS3. Adds (a) FADE direction sanity from a slug+time JOIN against production momo/sniper signals, and (b) per-sleeve live-vs-backtest scorecard._

## Headline verdict

| | result |
|---|---|
| All 15 specced sleeves wired + emitting events | ✅ |
| **FADE direction is CORRECT (5 of 6 sleeves fire opposite to prod)** | ✅ |
| 9 of 15 sleeves have **0 actual fires** (feature publisher bug) | ❌ |
| 6 FADE sleeves firing but **LOSING vs backtest** | ⚠ −$487 live / 26 h vs +$71/day expected |
| `eth_15m_fade_sniper` mis-fires 50 % of the time | ⚠ partial direction bug |
| `imb5` feature never wired | ❌ |

## Live data window

- Source: `data/v4/canonical/trading_events_30d.parquet` (refreshed)
- Latest event: **2026-05-25 19:21 UTC**
- Shadow events captured: **4 803** total (164 real fires + 4 639 heartbeats)
- Resolutions matched: 82
- Time span: 25.6 hours

## 1. Live-vs-backtest scorecard (all 15 sleeves)

| sleeve | live fires/24h | exp fires/24h | live n_res | **live WR %** | exp WR % | **live $/tr** | exp $/tr | **live $/day** | exp $/day | verdict |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| btc_5m_fade_momo_v2 | 41 | 35 | 22 | **36.4** | 51.9 | **−$7.55** | +$0.86 | **−$156** | +$22 | PNL_NEG |
| sol_5m_fade_sniper | 26 | 17 | 14 | 35.7 | 50.8 | −$8.59 | +$0.45 | −$113 | +$6 | PNL_NEG |
| sol_5m_fade_momo_v2 | 26 | 17 | 14 | 35.7 | 50.1 | −$8.29 | +$0.55 | −$109 | +$7 | PNL_NEG |
| btc_5m_fade_sniper | 26 | 30 | 14 | 42.9 | 53.0 | −$4.51 | +$0.80 | −$59 | +$18 | PNL_NEG |
| eth_15m_fade_sniper | 23 | 15 | 12 | 50.0 | 52.6 | −$1.42 | +$1.02 | −$16 | +$12 | PNL_NEG |
| sol_15m_fade_momo_v2 | 11 | 4 | 6 | 50.0 | 52.4 | −$0.86 | +$1.88 | −$5 | +$6 | HIGH_FIRES |
| **FADE TOTAL** | **154** | **118** | **82** | **40.2** | **52.1** | **−$5.97** | **+$0.95** | **−$458** | **+$71** | |
| **ALL_5m_phase1_kelly** | **0** | 167 | 0 | — | 84.4 | — | $5.50 | 0 | +$927 | **MISSING** |
| ALL_5m_S3_prewindow | 0 | 95 | 0 | — | 52.8 | — | $0.83 | 0 | +$78 | MISSING |
| ALL_15m_S4_prewindow | 0 | 11 | 0 | — | 54.6 | — | $2.26 | 0 | +$25 | MISSING |
| eth_15m_sniper_m5v | 0 | 4 | 0 | — | 63.2 | — | $7.15 | 0 | +$29 | MISSING |
| btc_5m_momo_v2_fairedge500 | 0 | 15 | 0 | — | 52.9 | — | $0.34 | 0 | +$29 | MISSING |
| btc_15m_momo_v2_fairedge500_cvd30 | 0 | 3 | 0 | — | 63.2 | — | $5.54 | 0 | +$17 | MISSING |
| sol_15m_sniper_fairedge500 | 0 | 2 | 0 | — | 65.6 | — | $8.06 | 0 | +$14 | MISSING |
| sol_5m_momo_v1_m5v | 0 | 3 | 0 | — | 62.5 | — | $4.99 | 0 | +$17 | MISSING |
| sol_5m_momo_v2_cvd_macd | 0 | 5 | 0 | — | 57.3 | — | $2.13 | 0 | +$17 | MISSING |

**Backtest-expected aggregate**: +$1 200/day (Phase-1 Kelly $927 + S3/S4 prewindow $103 + 6 overlays $123 + 6 FADE $71)
**Live aggregate**: **−$458/day** (FADE only; rest are dead)
**Net delta**: **−$1 660/day** below expectation

## 2. FADE direction sanity — IT IS WORKING

Joined each shadow `_fade_*` real fire to production momo/sniper `poly_updown_signal` on `slug` + `at` within ±60 s. Counted same vs opposite direction:

| shadow fade sleeve | joined fires | same_dir | **opposite_dir** | **% opposite** |
|---|--:|--:|--:|--:|
| **btc_5m_fade_momo_v2** | 62 | 4 | **58** | **93.5 %** ✅ |
| sol_15m_fade_momo_v2 | 15 | 1 | 14 | 93.3 % ✅ |
| sol_5m_fade_sniper | 50 | 5 | 45 | 90.0 % ✅ |
| btc_5m_fade_sniper | 51 | 6 | 45 | 88.2 % ✅ |
| sol_5m_fade_momo_v2 | 40 | 5 | 35 | 87.5 % ✅ |
| **eth_15m_fade_sniper** | **8** | **4** | **4** | **50.0 %** ⚠ |

**5 of 6 FADE sleeves are correctly firing the OPPOSITE direction** (87–94 %). The few %-of-same fires are explainable by:
- Production sleeve has multiple HOLD/HEDGE/SELL variants emitting different `signal` fields at slightly different ts
- 60 s join tolerance picks up the wrong parent in cross-sleeve same-slug fires

**`eth_15m_fade_sniper` is broken**: 50 % same, 50 % opposite on 8 join cases. Either the production parent sleeve_id mapping is wrong or the HOD-pass check happens in the wrong branch. Needs source inspection.

## 3. So why is FADE losing if direction is correct?

The implementation flips direction correctly. The **strategy hypothesis** itself is the question.

Backtest panel (21 d, Apr–May 2026):
- Production momo/sniper on F7-off, HOD-failing subset = **−$546/day net loss**
- Flipping that subset = **+$71/day gain** (recovering ~13 % of the loss)

Live 26 h (May 24-25 2026):
- Same hook fires, opposite direction confirmed
- But hit rate on the flipped side = **40 % WR** (backtest expected 52 %)
- Per-trade $ = **−$5.97** (backtest expected +$0.95)

Three plausible causes:

1. **Sample size is tiny.** 82 resolutions across 6 sleeves. Backtest had n = 84–747 per cell. Binomial variance on 22 trials at 50 % WR = ±10 pp at 1σ — easily reaches 36 % by noise. 7-day live data needed.
2. **Backtest period was the contrarian regime.** If production momo's un-gated subset was bleeding in April–May (the 21-d panel) but is now winning (post-May-21), the FADE alpha disappeared. Production momo may have been quietly improved in the same Phase-34/35 deploys.
3. **Live HOD-top8 lists differ from backtest constants.** My backtest used my own HOD lists from `_recompute_hod_top8.py`. If production's HOD-top8 was refreshed in Phase 34 ("HoD refresh + drop m5va + add m1va"), then the live ungated subset = a DIFFERENT set of fires than the backtest ungated subset.

I lean **(2) + (3) combined** based on Phase 34 git log: `feat(34): HoD refresh + drop m5va + add m1va`. The HOD list refresh likely changed which fires get rejected, so the "ungated" subset live ≠ ungated subset in my backtest.

## 4. Root bug for the 9 missing sleeves — still feature publisher

Confirmed via `journalctl -u tv-engine`:

```
{"symbol":"BTC","tf":"5m","ws_s":1779735300,"offset_s":60,
 "dev_bps":null,"vwap_present":false,"m1v":null,
 "cvd_30s":null,"macd":null,"rvol":null,
 "fair_edge_up":null,"fair_edge_dn":null,
 "event":"bar_context_t_plus_n.built"}
```

Every shadow event from S3/S4/phase1/overlay-filter sleeves has the same null payload. Without `fair_edge_bp`, `cvd_agree_30s`, `macd_agree`, `rvol_30_300`, the AND rules can never evaluate True.

Builder runs (`phase1_ms ≈ 38`, `phase2_ms ≈ 651`) but every output is null. Likely a wrong-table / wrong-symbol pointer in the binance-1s kline lookup inside the `bar_context.*.built` function at `backend/app/engine/poly_updown_loop.py`.

## 5. Recommended action plan

### P0 (blocker — engine team)

1. **Debug `bar_context_t_plus_n.built` / `bar_context_pre_window.built` null-feature bug** in `backend/app/engine/poly_updown_loop.py`. Check binance-1s ingestion path on VPS3 (`klines_v2` table presence and per-symbol freshness).
2. **Fix `eth_15m_fade_sniper`** — half the fires go the wrong direction. Audit the production-parent → shadow-mirror direction-flip hook for this specific cell.

### P1 (data needed before deciding FADE)

3. **Recompute the BACKTEST baseline using VPS3's CURRENT HOD-top8 + Markov labels**, not my own. Pull the active list from VPS3, re-run `flip_with_gating_breakdown.py`. Compare to the original backtest. If the FADE alpha disappears with the live HOD list, **deprecate the FADE sleeves**.
4. **Let FADE run 7+ live days** before any deprecate decision. 26 h is statistically meaningless on n=22 max per sleeve.

### P2 (cleanup)

5. **Port `imb5` feature** or remove from spec docs.
6. **Tag heartbeat vs fire events** — currently both emit `kind=poly_updown_signal`. Either add `kind=poly_updown_heartbeat` for null-feature checks or filter on `data->>'reason'`.

## 6. Quick wins for the next session

When you start the next session, the first 30 minutes:
1. Inspect `backend/app/engine/poly_updown_loop.py` `_build_bar_context_*` functions — confirm the binance-1s table pointer
2. Run on VPS3: `sudo -u postgres psql -d storedata -c "SELECT symbol_id, MAX(time_period_start_us), COUNT(*) FROM binance_klines_v2 WHERE timeframe='1SEC' AND time_period_start_us > extract(epoch from now() - interval '1h')*1e6 GROUP BY 1"` — confirm 1s feed is up to date
3. If the table is fresh, the bug is in feature build code. If table is stale, the bug is in ingestion.

## 7. Files

- This audit: `strategy_lab/reports/VPS3_LIVE_SHADOW_AUDIT_V2_2026_05_25.md`
- Previous audit: `strategy_lab/reports/VPS3_LIVE_SHADOW_AUDIT_2026_05_25.md`
- Comparison runner: `strategy_lab/overnight_2026_05_23/vps3_verify_shadow_sleeves/04_local_live_vs_backtest.py`
- CSV output: `data/v4/canonical/_results/live_shadow_vs_backtest.csv`
- Original spec: `strategy_lab/reports/SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md`
