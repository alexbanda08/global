# VPS3 live shadow audit — 2026-05-25 21:00 UTC

_24 h after Phase-36 + Phase-36b deploy. SSH-confirmed to VPS3, queried `storedata.trading.events` directly._

## Status at a glance

| | result |
|---|---|
| Engine running | ✅ `tv-engine.service` active since 2026-05-24 20:37 UTC, 24h uptime |
| All 15 sleeves wired into source | ✅ `backend/app/api/bots.py` + `backend/app/engine/main.py` |
| All 15 sleeves logging events | ✅ 4 947 signal events + 82 resolutions in last 24 h |
| New features published in `data` JSON | ⚠ **BROKEN** — see § 3 |
| 9 of 15 sleeves ever fired | ❌ **0 actual fires** (only heartbeats) — see § 4 |
| 6 of 15 sleeves firing (FADE) | ✅ but **all 6 are LOSING in live** vs backtest expectation — see § 5 |
| `imb5` feature in source | ❌ 0 occurrences (didn't get wired) |

## 1. Deploy commits visible on VPS3 (`git log`)

```
a6ad4fd1  feat(36b): 6 fade companions + 6 overlay filters (Sleeves #2-7 + Bonus)
8f2e9247  feat(36): 3 shadow sleeves — Phase 1 Kelly + S3/S4 pre-window
37aecbd4  feat(35): VWAP continuation — 5 paper-only late-fire shadow sleeves   (earlier)
dd24e7a7  feat(34): shadow gated sleeves — HoD + MTF + Markov (11 × 3 = 33 paper)
```

Phase 36 + 36b = my spec from yesterday. Both shipped before engine restart.

## 2. Sleeves found in DB, with first/last fire times

All 15 specced sleeves are present (9 new + 6 overlay filters):

| sleeve_id | first_seen | last_seen | signal events / 24 h |
|---|---|---|--:|
| `shadow_poly_updown_ALL_5m_phase1_kelly` | 2026-05-24 19:47 | 2026-05-25 20:52 | 906 |
| `shadow_poly_updown_ALL_5m_S3_prewindow` | 2026-05-24 19:49 | 2026-05-25 20:49 | 903 |
| `shadow_poly_updown_ALL_15m_S4_prewindow` | 2026-05-24 19:58 | 2026-05-25 20:43 | 300 |
| `shadow_poly_updown_btc_5m_fade_sniper` | 2026-05-24 20:40 | 2026-05-25 20:50 | 305 |
| `shadow_poly_updown_sol_5m_fade_sniper` | 2026-05-24 20:40 | 2026-05-25 20:50 | 305 |
| `shadow_poly_updown_btc_5m_momo_v2_fairedge500` | 2026-05-24 20:41 | 2026-05-25 20:51 | 291 |
| `shadow_poly_updown_btc_5m_fade_momo_v2` | 2026-05-24 20:41 | 2026-05-25 20:51 | 313 |
| `shadow_poly_updown_sol_5m_fade_momo_v2` | 2026-05-24 20:41 | 2026-05-25 20:51 | 305 |
| `shadow_poly_updown_sol_5m_momo_v2_cvd_macd` | 2026-05-24 20:41 | 2026-05-25 20:51 | 291 |
| `shadow_poly_updown_sol_5m_momo_v1_m5v` | 2026-05-24 20:42 | 2026-05-25 20:52 | 291 |
| `shadow_poly_updown_eth_15m_fade_sniper` | 2026-05-24 20:45 | 2026-05-25 20:45 | 109 |
| `shadow_poly_updown_eth_15m_sniper_m5v` | 2026-05-24 20:45 | 2026-05-25 20:45 | 97 |
| `shadow_poly_updown_sol_15m_sniper_fairedge500` | 2026-05-24 20:45 | 2026-05-25 20:45 | 97 |
| `shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30` | 2026-05-24 20:46 | 2026-05-25 20:46 | 97 |
| `shadow_poly_updown_sol_15m_fade_momo_v2` | 2026-05-24 20:46 | 2026-05-25 20:46 | 103 |

## 3. 🚨 ROOT BUG — feature publisher returns NULL

Sampled raw `data` JSON from `shadow_poly_updown_ALL_5m_S3_prewindow` (every event):

```json
{
    "tf": "5m",
    "mode": "paper",
    "s_now": null,
    "tau_s": null,
    "reason": "no_signal",
    "signal": "NONE",
    "strike": null,
    "symbol": "ETH",
    "cvd_30s": null,
    "cvd_60s": null,
    "fair_up": null,
    "macd_hist": null,
    "entry_phase": "pre_window_60",
    "rvol_30_300": null,
    "fair_edge_bp": null,
    "vwap_dev_bps": null,
    "strategy_mode": "prewindow_s3",
    "predicted_edge_pp": 3.0,
    "predicted_cost_bps": 400.0
}
```

**Every required feature is null**: `s_now`, `tau_s`, `strike`, `cvd_30s`, `cvd_60s`, `fair_up`, `macd_hist`, `rvol_30_300`, `fair_edge_bp`, `vwap_dev_bps`.

Confirmed in `journalctl -u tv-engine` log line (2026-05-25 20:54:09 UTC):

```
{"symbol": "ETH", "tf": "5m", "slot_start_unix_s": 1779735300, "offset_s": 60,
 "dev_bps": null, "fair_edge_up": null, "fair_edge_dn": null, "cvd_60s": null,
 "cid_resolved": true, "total_ms": 271,
 "event": "bar_context_pre_window.built"}
```

And:

```
{"symbol": "BTC", "tf": "5m", "ws_s": 1779735300, "offset_s": 60,
 "dev_bps": null, "vwap_present": false, "m1v": null, "cid_resolved": true,
 "cvd_30s": null, "macd": null, "rvol": null,
 "fair_edge_up": null, "fair_edge_dn": null, "total_ms": 28,
 "event": "bar_context_t_plus_n.built"}
```

`cid_resolved` = true (chainlink read works), `cvd_30s`/`macd`/`rvol`/`fair_edge`/`dev_bps` = null. **The feature pipeline runs but every output is null.** Without features, the AND-rule predicates can't evaluate to True, so the sleeve never fires.

Phase1 + 2 timings: phase1 (kline lookups) = ~38 ms, but `kline_now_ms: 0, kline_5m_ms: 0, kline_15m_ms: 0, kline_1h_ms: 0` — kline lookups return 0 ms wall clock = likely returning empty / nothing. Phase 2 (feature build) = 600-650 ms; runs but produces nulls.

**Probable causes** (need source inspection):
1. **Binance 1s kline source pointer wrong** — engine may be reading from a kline table that's not populated, or a path that's wrong
2. **VWAP/CVD builder bug** — `vwap_present: false` confirms the 15m anchored VWAP isn't being computed
3. **Feature publisher** depends on a data table that's empty in the live storedata DB (e.g., a 1s-binance ws ingestion gap)

## 4. Fire counts — actual vs heartbeat

Filtered to `data->>'signal' IN ('UP','DOWN')` (real fires) vs `data->>'reason' = 'no_signal'` (heartbeats / skipped):

| sleeve | total events | **real fires** | no_signal | verdict |
|---|--:|--:|--:|---|
| `shadow_poly_updown_btc_5m_fade_momo_v2` | 288 | **22** | 266 | ✅ firing |
| `shadow_poly_updown_sol_5m_fade_momo_v2` | 288 | **14** | 274 | ✅ firing |
| `shadow_poly_updown_sol_5m_fade_sniper` | 288 | **14** | 274 | ✅ firing |
| `shadow_poly_updown_btc_5m_fade_sniper` | 288 | **14** | 274 | ✅ firing |
| `shadow_poly_updown_eth_15m_fade_sniper` | 96 | **12** | 84 | ✅ firing |
| `shadow_poly_updown_sol_15m_fade_momo_v2` | 96 | **6** | 90 | ✅ firing |
| `shadow_poly_updown_sol_15m_sniper_fairedge500` | 96 | **0** | 96 | ❌ no fires |
| `shadow_poly_updown_sol_5m_momo_v1_m5v` | 288 | **0** | 288 | ❌ no fires |
| `shadow_poly_updown_ALL_15m_S4_prewindow` | 288 | **0** | 288 | ❌ no fires |
| `shadow_poly_updown_sol_5m_momo_v2_cvd_macd` | 288 | **0** | 288 | ❌ no fires |
| `shadow_poly_updown_ALL_5m_S3_prewindow` | 864 | **0** | 864 | ❌ no fires |
| `shadow_poly_updown_ALL_5m_phase1_kelly` | 864 | **0** | 864 | ❌ no fires |
| `shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30` | 96 | **0** | 96 | ❌ no fires |
| `shadow_poly_updown_btc_5m_momo_v2_fairedge500` | 288 | **0** | 288 | ❌ no fires |
| `shadow_poly_updown_eth_15m_sniper_m5v` | 96 | **0** | 96 | ❌ no fires |

**Summary**: **6 of 15 sleeves are alive (FADE only)**; **9 sleeves are dead because of the feature-publisher bug** in § 3. The FADE sleeves work because they consume **production momo/sniper signals** (which compute themselves) and just flip direction — they don't need the new feature pipeline.

## 5. 🚨 FADE sleeves LIVE results — all 6 LOSING money

| sleeve | n resolved | live WR % | live per_tr | live sum_$ | backtest WR % | backtest per_tr | backtest $/day |
|---|--:|--:|--:|--:|--:|--:|--:|
| `shadow_poly_updown_btc_5m_fade_momo_v2` | 22 | **36.4** | **−$7.55** | **−$166** | 51.9 | +$0.86 | +$22 |
| `shadow_poly_updown_sol_5m_fade_sniper` | 14 | 35.7 | −$8.59 | −$120 | 50.8 | +$0.45 | +$6 |
| `shadow_poly_updown_sol_5m_fade_momo_v2` | 14 | 35.7 | −$8.29 | −$116 | 50.1 | +$0.55 | +$7 |
| `shadow_poly_updown_btc_5m_fade_sniper` | 14 | 42.9 | −$4.51 | −$63 | 53.0 | +$0.80 | +$18 |
| `shadow_poly_updown_eth_15m_fade_sniper` | 12 | 50.0 | −$1.42 | −$17 | 52.6 | +$1.02 | +$12 |
| `shadow_poly_updown_sol_15m_fade_momo_v2` | 6 | 50.0 | −$0.86 | −$5 | 52.4 | +$1.88 | +$6 |
| **TOTAL FADE** | **82** | **40.2** | **−$5.97** | **−$487** | — | — | **+$71** |

**Live total: −$487 over 24h of resolved trades.** Backtest predicted **+$71/day**. That's a swing of −$558/day vs expectation.

**Sample FADE fire payload** (BTC 5m fade_momo_v2, `order_placed`):

```json
{
    "tf": "5m",
    "mode": "paper",
    "reason": "order_placed",
    "signal": "UP",
    "symbol": "BTC",
    "fee_usd": 0.875,
    "fill_qty": "50.0000",
    "fill_price": "0.5",
    "fill_status": "filled",
    "qty_intended": "25",
    "strategy_mode": "fade_momo_v2"
}
```

Fills are real (price=0.5, qty=50). Direction is `UP` here. **The direction-correctness vs production cannot be verified from this query because the production momo_v2 BTC 5m signal isn't joining against the same slug field with the same JSON path.** Need to debug.

**Hypotheses for live-vs-backtest divergence**:
1. **The FADE may be firing the SAME direction as production momo, not opposite.** A direct join SQL returned 0 rows because either the join column mismatches OR the hook is firing both sides.
2. **Production HOD-top8 hours on VPS3 may differ from my backtest constants** (HOD list could have been refreshed since the panel was built).
3. **Sample size is tiny** (n=6 to 22 resolutions) — statistical noise is huge on 24h.
4. **Production momo_v2 quality may have shifted in this window** — if the parent strategy is currently *winning* in the un-gated cells too, fading them loses by construction.

## 6. Feature-publisher hooks check on VPS3

```
backend/app/engine/poly_updown_loop.py    — has `fair_edge_bp`, `cvd_30s/60s`, `macd_hist`, `rvol_30_300`, `fair_up`, `kelly_mult`
backend/app/venues/polymarket/poly_updown_loop.py    — duplicate? need to verify
```

`imb5` was specced but **0 occurrences in source** — confirmed dropped during deploy.

The grep counts:
```
fair_up         4 files
fair_edge_bp    4 files
cvd_30s         4 files
cvd_60s         3 files
macd_hist       4 files
rvol_30_300     4 files
imb5            0 files   ← MISSING
kelly_mult      2 files
```

## 7. ⚠ Action items for next session

### P0 — blockers

1. **Debug the bar_context builder** — figure out why `dev_bps`, `vwap_dev_bps`, `cvd_30s/60s`, `macd_hist`, `rvol_30_300`, `fair_edge_bp`, `fair_up`, `s_now`, `strike` are all null in `bar_context_pre_window.built` and `bar_context_t_plus_n.built`. Start point: `backend/app/engine/poly_updown_loop.py` — the builder function. Likely a missing data-source pointer.
2. **Confirm FADE direction is OPPOSITE of production** — write a SQL that joins by slug + same fire time, compares directions. The current join returned 0 rows so there's a slug-format mismatch to debug.
3. **Decide on `imb5`** — port the publisher or drop from the spec.

### P1 — should fix

4. **Add `fire_offset_s` to prewindow event payload** — currently missing from `data` JSON for S3/S4 prewindow events (heartbeat events show no offset).
5. **Re-evaluate FADE backtest assumptions** — the −$487 / 24h loss is much worse than backtest predicted. Either the flip is wrong, prod HOD/M5V drifted, or the backtest period was anomalous. Need a 7-day live sample before concluding.

### P2 — nice-to-have

6. **Distinguish heartbeat vs fire** in the event log — currently both emit `kind = 'poly_updown_signal'` and only differ by `data->>'reason'`. Consider `kind = 'poly_updown_heartbeat'` for the null-feature checks.
7. **Run `03_compare_to_backtest.py`** after a fresh `pull_delta_vps3.sh` to write a clean per-sleeve scorecard.

## 8. What's working

- Phase-36 + Phase-36b code is **fully deployed** to VPS3
- All 15 specced `sleeve_id` strings are **registered + emitting events**
- Engine restart picked up the changes (uptime since 2026-05-24 20:37 UTC)
- 6 FADE sleeves are **producing real fills against real L25 books** in paper mode
- 82 resolutions matched cleanly to fires by `slug` + `sleeve_id`

## 9. What's NOT working

- **Feature publisher is broken** → 9 of 15 sleeves can't fire
- **6 FADE sleeves are losing −$487 / 24 h** vs backtest +$71 / day predicted
- **`imb5` feature missing** from source
- **No engine alerts** firing on null-feature condition (silent failure)

## Raw data reference

| query | output captured at |
|---|---|
| sleeve presence (`shadow_*` prefix) | 2026-05-25 20:55 UTC |
| fire counts per sleeve last 24 h | 2026-05-25 20:55 UTC |
| resolved PnL per sleeve last 7 d | 2026-05-25 20:55 UTC |
| heartbeat-vs-fire split last 24 h | 2026-05-25 20:55 UTC |
| journalctl tv-engine last 6 h grep features | 2026-05-25 20:54 → 20:58 UTC |
| sample S3 payload (`jsonb_pretty`) | 2026-05-25 20:55 UTC |
| sample FADE fire payload | 2026-05-25 20:55 UTC |

## Files

- This audit: `strategy_lab/reports/VPS3_LIVE_SHADOW_AUDIT_2026_05_25.md`
- Verification kit: `strategy_lab/overnight_2026_05_23/vps3_verify_shadow_sleeves/`
- Original spec: `strategy_lab/reports/SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md`
- Worked examples: `strategy_lab/reports/WORKED_EXAMPLES_KELLY_FADE_OVERLAY_2026_05_24.md`
- Phase-2 findings: `strategy_lab/reports/PHASE2_FINAL_FINDINGS_2026_05_24.md`
