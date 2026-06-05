# Silent-Sleeve Forensics — fairedge/m5v/cvd overlays + SOL hlcascade V9 — 2026-06-01

Auditor: Claude agent (read-only VPS3 + local source mirror `vps3_shadow_audit_2026_05_28/src` + live `/opt/tradingvenue`).
Scope: Group 1 = 6 `shadow_poly_updown_*` overlay sleeves (7d12h, 0 fires, log `poly_updown_signal` to `trading.events`). Group 2 = 2 SOL `*hlcascade*_v9` sniper sleeves (1d8h, 0 fires, log `sleeve_fire_eval` to `/var/log/tradingvenue/sniper_v5/*.jsonl`).

---

## Group 1 — fairedge500 / m5v / cvd_macd / cvd30 overlays → **BUG (feature not computed on this dispatch path)**

### What each overlay requires
`OverlayFilterStrategy` (`strategies/polymarket/shadow9.py`) is a pass-through gate on a base prod strategy. Returns NONE unless **base raises UP/DOWN AND `_gate_passes()`**:
- `fairedge500`: `fair_edge_bp > 500`
- `fairedge500_cvd30`: `fair_edge_bp > 500 AND cvd_agree_30s`
- `cvd_macd`: `cvd_agree_30s AND macd_agree`
- `m5v_pass`: `markov_regime_w20_5m_va == 2 (UP) / 0 (DOWN)`

`_gate_passes` reads features from `controller._bar_ctx_active` (the per-slot BarContext).

### Is the feature computed? Is the base firing?
- **Base strategies fire heavily.** `trading.events` (8d): `poly_updown_btc_5m_momo_v2_HOLD_f7` UP=120/DOWN=136, `*sniper_hod` 100s of fires, `fade_*` 150-230 each. So the overlay NONEs are NOT because the base never raises.
- **`fair_edge_bp` IS computed — but only on a different builder.** `trading.events` shows fair_edge_bp logged by `shadow_poly_updown_ALL_5m_phase1_kelly` (n=1716, **714 with fe>500 = 42%**), `*_5m_S3_prewindow` (157/1722), `*_15m_S4_prewindow` (24/576). So the feature exists and clears 500 routinely.
- **The overlay sleeves never see it.** In `engine/poly_updown_loop.py` the only builder that calls `_compute_phase36_features` (→ sets `fair_edge_bp`, `cvd_30s`, `macd_hist_value`) is `build_bar_context_t_plus_n` (line 1221) + `build_bar_context_pre_window` (1376). Those run **only for `vwap_continuation` / `vwap_kelly_ensemble` / `prewindow_*` controllers** (`_fire_t_plus_n_boundary`). The overlays are bucketed: `overlay_momo`→`momo_controllers` (t+120 via `build_bar_context_t_plus_120`), `overlay_momo_v2`→`momo_v2_controllers` (t+60 via `build_bar_context_t_plus_60`), `overlay_sniper`→`bar_close_controllers` (via `build_bar_context`). **None of those three builders compute phase36 features** — `fair_edge_bp`/`cvd_30s`/`macd_hist_value` default to None.
- **`markov_regime_w20_5m_va` is NEVER computed anywhere.** Hardcoded `=None` at poly_updown_loop.py:650 & 864, omitted at the t_plus_n build (defaults None). Only `markov_regime_w20_1m_va` (`_m1v_regime`) is ever populated. So the two m5v sleeves are double-dead.

### Per-sleeve verdict (all 100% `no_signal`/NONE, 708-2128 evals each over 8d)
| sleeve | gate | feature on its bar_ctx | verdict |
|---|---|---|---|
| btc_5m_momo_v2_fairedge500 | fair_edge_bp>500 | **None** (t+60 builder) | BUG feature-not-computed |
| btc_15m_momo_v2_fairedge500_cvd30 | fe>500 & cvd30 | **None** (t+60) | BUG |
| sol_5m_momo_v2_cvd_macd | cvd30 & macd | **None** (t+60) | BUG |
| sol_15m_sniper_fairedge500 | fe>500 | **None** (bar_close) | BUG |
| eth_15m_sniper_m5v | regime5m==2/0 | **None — never computed** | BUG |
| sol_5m_momo_v1_m5v | regime5m==2/0 | **None — never computed** | BUG |

**Group 1 root cause:** overlay gate features (`fair_edge_bp`, `cvd_30s`, `macd_hist_value`, `markov_regime_w20_5m_va`) are produced on a builder/dispatch path (`build_bar_context_t_plus_n`, vwap/prewindow controllers) the overlays never run on; m5v additionally is hardcoded None project-wide. Gate always evaluates `feature is None → False`. Threshold rarity is irrelevant — feature is null at eval time. **Not LOW_BASE_RATE.** Smoking gun: fair_edge_bp clears 500 on 42% of phase1_kelly fires yet is None on every overlay eval; `grep markov_regime_w20_5m_va = → only =None`.

---

## Group 2 — SOL hlcascade25k/15k V9 → **BUG (engine liq feed near-empty) + low SOL base rate**

### Gate
`g_a2_hl_short_cascade` (`sniper_v5_gates.py:2012`): `sum(notional) for coin==asset within window_s > thresh_usd`, fed by `V9DataStore.get_hl_short_proxy()`. Live source (`strategies/polymarket/sniper_v5_v9_data.py`) is the in-process `CexLiquidationFeed` (OKX/Bybit/Gate/Bitget WS; Binance geo-blocked), short-liq = `side=='buy'`, `coin` parsed from `OKX_PERP_BTC_USDT`→`BTC` (parse correct). The old parquet `hyperliquid_liquidations_full.parquet` is gone (`/opt/tradingvenue/data/v4/canonical/` does not exist) but is no longer the source.

### Is the SOL feed empty, or cascades rare? — BOTH, but BUG dominates
JSONL gate outcomes (all sniper_v5 logs, May28–Jun01): hlcascade gate evaluated thousands of times, was **TRUE 0 times for EVERY asset** — BTC 0/3177, ETH 0/961, **SOL 0/864** (placed=0). The gate is reached (e.g. `g_dir_up` passes 288/288 on the SOL up sleeve) and returns False every time.

**Ground-truth base rate from storedata CEX liq DB** (okx+gate+bybit+bitget union, buy-side, 6 days):
- **BTC: 116 short-liqs/6d. 300s rolling windows >$50k = 64, >$100k = 56.** Gate SHOULD have fired dozens of times — fired 0. The engine's in-process feed is not capturing what the DB collector records. **→ feed BUG.**
- **SOL: 9 short-liqs/6d. 300s windows >$25k = 4, >$15k = 5.** Real but rare (~0.7/day); over the 1d8h window expect ~1 fire — genuinely low base rate.
- DB freshness: **bybit_liquidations_v2 & bitget_liquidations_v2 are EMPTY** (NULL max-ts); only okx + gate flow. Engine journal shows `cex_liq_feed.stale_reconnect` for bybit every ~2.5 min + okx/gate periodic — the live ring buffer is mostly starved.

### Per-sleeve verdict
| sleeve | window/thr | DB base rate | gate TRUE | verdict |
|---|---|---|---|---|
| sol_5m_a2_hlcascade25k_v9 | 300s/$25k | ~4 windows/6d | 0/576 | **BUG (feed near-empty) + LOW_BASE_RATE** |
| sol_5m_up_a2_hlcascade15k_v9 | 300s/$15k | ~5 windows/6d | 0/288 | **BUG (feed near-empty) + LOW_BASE_RATE** |

**Group 2 root cause:** in-process `CexLiquidationFeed` buffer is starved (bybit/bitget tables empty, okx/gate frequently stale) so `get_hl_short_proxy()` returns a near-empty frame → gate False even for BTC where the DB proves 56+ qualifying $100k windows in 6d. Layered on a genuinely tiny SOL short-liq rate. Spec `SHADOW_DEPLOY_SPEC_V9_AND_VL_2026_05_27.md` §2.4 already warns "SOL/ETH: insufficient HL data, do not use" — the SOL sleeves were deployed against that warning. Smoking gun: BTC gate 0/3177 TRUE while DB has 64 windows >$50k over 6d.

---

## Family root causes
1. **Group 1:** structural builder/dispatch mismatch — overlay sleeves run on momo(t+120)/momo_v2(t+60)/bar_close builders that never compute the phase36 features their gates require; `markov_regime_w20_5m_va` is hardcoded None engine-wide. Fix: compute phase36 (and m5v regime) in the t+60/t+120/bar_close builders, or move overlays onto the t_plus_n dispatch.
2. **Group 2:** the live CEX liquidation feed is starved (2 of 4 exchange tables empty, frequent stale-reconnects); cascade gate can't fire for any asset. SOL additionally has a near-zero short-liq base rate. Fix: repair feed ingestion (bybit/bitget), and retire SOL hlcascade per spec §2.4.

Local mirror paths: `vps3_shadow_audit_2026_05_28/src/strategies/polymarket/{shadow9.py,sniper_v5_gates.py,sniper_v5_v9_data.py}`; live `/opt/tradingvenue/backend/app/engine/poly_updown_loop.py` + `/opt/tradingvenue/backend/app/feeds/cex_liquidations_feed.py`.
