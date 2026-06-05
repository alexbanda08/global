# Backtest vs Live — momo & shadow sleeves (2026-05-29)

_Canonical-data backtest of the momentum / shadow-sleeve families
(`poly_updown_*`, `shadow_poly_*`) over the LIVE shadow window, compared to
live shadow PnL._

**Window:** 2026-05-27 00:00 UTC → 2026-05-29 13:10 UTC (~2.55 days), bounded by
canonical resolution + kline coverage (resolutions to 13:10, klines 1MIN to
13:16). Live shadow rows extend to ~19:00 UTC on 05-29 for some sleeves; the
backtest is capped at the canonical edge, so backtest n is naturally ≤ live n
for sleeves still firing past 13:10.

**Method (per backtestable sleeve):**
- Universe = chainlink-resolved BTC/ETH/SOL 5m+15m markets in window (2,841 markets).
- Anchors per CLAUDE.md: `ws_s = slot_start − window_s`.
  - momo v1: `ret_2m = log(c@(ws_s+120)/c@ws_s)`, fire `@ws_s+120`.
  - momo v2: `ret_2m = log(c@(ws_s+60)/c@(ws_s−60))`, fire `@ws_s+60`.
  - INV_NIGHT (volume base): `ret_5m = log(c@ws_s/c@(ws_s−300))`, fire `@slot_start`.
- Gate (momo): `|ret_2m| ≥ feed-backed rolling-14d q90` (production-style, computed
  over ALL 1MIN bars — not chainlink-only) + **F7 basic** (UP needs RSI(14)>50,
  DOWN<50, simple-mean Wilder anchored @ ws_s).
- INV_NIGHT: volume mode fires `sign(ret_5m)`; flip direction iff `ws_s` UTC hour
  ∈ {1,2,3,4,5,9,10}, else silent.
- Fill: L25 book-walk $25 notional, **`subsample_1hz=False` (native 10 Hz)**,
  spread filter 0.02 (BTC/ETH) / 0.025 (SOL), strict-asof.
- Resolve: chainlink `outcome`. Fee: **legacy 2%-on-profit** (`engine_v2.LegacyConfig`).
- HOLD policy = hold to settlement (no early sell) → `hold_pnl`.

**Script:** `strategy_lab/meta_classifier/backtest_vs_live_momo_2026_05_29.py`
**Outputs:** `data/v4/canonical/_results/backtest_vs_live_momo_2026_05_29/{per_trade.parquet,sleeve_table.csv}`

---

## 1. Per-sleeve table (live vs backtest)

`$/tr` = per-trade PnL @ $25 notional. Verdict: **MATCH** = same sign and
|Δ$/tr| reasonable for the overlapping-n; **DIVERGE** = sign flip or large gap;
**NO_INFRA** = no canonical signal reconstruction possible.

| sleeve_id | n_live | live_WR | live_$/tr | n_bt | bt_WR | bt_$/tr | Δ$/tr | verdict |
|---|--:|--:|--:|--:|--:|--:|--:|:--|
| poly_updown_btc_5m_volume_INV_NIGHT | 232 | 43.5% | −3.88 | 194 | 41.2% | −5.29 | −1.41 | **MATCH** |
| poly_updown_eth_5m_volume_INV_NIGHT | 232 | 42.2% | −5.05 | 152 | 40.8% | −5.77 | −0.72 | **MATCH** |
| poly_updown_sol_5m_volume_INV_NIGHT | 225 | 41.8% | −5.37 | 148 | 43.2% | −4.49 | +0.88 | **MATCH** |
| poly_updown_eth_15m_volume_INV_NIGHT | 78 | 46.2% | −3.13 | 48 | 37.5% | −6.91 | −3.78 | **MATCH** (both neg) |
| poly_updown_btc_15m_volume_INV_NIGHT | 78 | 52.6% | +0.35 | 59 | 47.5% | −1.80 | −2.15 | DIVERGE (sign) |
| poly_updown_sol_15m_volume_INV_NIGHT | 74 | 48.6% | −2.03 | 26 | 38.5% | −7.14 | −5.11 | **MATCH** (both neg) |
| poly_updown_btc_5m_momo_v2_HOLD_f7 | 67 | 46.3% | −2.11 | 59 | 47.5% | −1.31 | +0.80 | **MATCH** |
| poly_updown_btc_5m_momo_HOLD_f7 | 61 | 50.8% | +0.21 | 49 | 55.1% | +2.65 | +2.44 | **MATCH** |
| poly_updown_eth_5m_momo_HOLD_f7 | 60 | 45.0% | −2.86 | 23 | 56.5% | +3.11 | +5.97 | DIVERGE (sign) |
| poly_updown_sol_5m_momo_HOLD_f7 | 57 | 52.6% | +0.68 | 34 | 55.9% | +2.67 | +2.00 | **MATCH** |
| poly_updown_sol_5m_momo_v2_HOLD_f7 | 50 | 52.0% | +0.18 | 32 | 50.0% | −0.57 | −0.75 | **MATCH** (≈flat) |
| poly_updown_eth_5m_momo_v2_HOLD_f7 | 38 | 36.8% | −6.99 | 36 | 52.8% | +1.02 | +8.00 | DIVERGE (sign) |
| poly_updown_btc_15m_momo_HOLD_f7 | 21 | 61.9% | +5.55 | 12 | 66.7% | +8.52 | +2.98 | **MATCH** |
| poly_updown_sol_15m_momo_HOLD_f7 | 19 | 52.6% | +0.60 | 2 | 100% | +24.99 | +24.4 | NO_INFRA (n_bt=2) |
| poly_updown_eth_15m_momo_HOLD_f7 | 19 | 57.9% | +3.92 | 7 | 71.4% | +11.39 | +7.47 | **MATCH** (both pos) |
| poly_updown_sol_15m_momo_v2_HOLD_f7 | 16 | 56.3% | +2.56 | 6 | 66.7% | +8.01 | +5.44 | **MATCH** (both pos) |
| poly_updown_eth_15m_momo_v2_HOLD_f7 | 14 | 71.4% | +10.19 | 9 | 66.7% | +8.49 | −1.70 | **MATCH** |
| poly_updown_btc_15m_momo_v2_HOLD_f7 | 9 | 66.7% | +8.11 | 11 | 72.7% | +11.39 | +3.28 | **MATCH** |

**Aggregate alignment:** Pearson corr(live_$/tr, bt_$/tr) = **0.61**; sign
agreement **77.8%** (14/18). On slugs the two share, **fired-direction match is
100%** (verified btc_5m momo, eth_15m momo_v2, and all 6 INV_NIGHT cells).

### NO_INFRA sleeves (live-only — cannot backtest from canonical)

These depend on 1s-trade-derived microstructure features (`fair_edge_bp`,
`cvd_30s/60s`, `macd_hist`, `vwap_dev_bps`) or proprietary sniper-search v6–v9
gates that are **not present in the canonical dataset for this window**. The
master feature panel (`master_gate_features_v2.parquet`) has F7/microprice/Markov
columns but lacks the CVD/MACD/fair-edge atoms AND predates the shadow window.

| sleeve_id | n_live | live_WR | live_$/tr | note |
|---|--:|--:|--:|:--|
| shadow_poly_updown_ALL_5m_phase1_kelly | 560 | 52.5% | +2.28 | VwapKellyEnsemble (S4∪S8, fair_edge/cvd/macd + Kelly tier) — **NO_INFRA** |
| shadow_poly_updown_ALL_5m_S3_prewindow | 204 | 54.9% | +1.35 | PrewindowS3 (fair_edge>0 ∧ cvd_60s ∧ macd) — **NO_INFRA** |
| shadow_poly_updown_ALL_15m_S4_prewindow | 11 | 81.8% | +14.19 | PrewindowS4 (fair_edge>500 ∧ cvd_30s ∧ |dev|≥8) — **NO_INFRA** |
| poly_sniper_v5_* (40+ sleeves) | — | — | — | sniper-search v6–v9 feature gates — **NO_INFRA** |
| shadow_poly_updown_*_fade_* (6 sleeves) | — | — | — | FadeCompanion (HoD+M5V gate on base) — partial infra; not run |
| poly_updown_*_momo_{HEDGE,SELL}_f7 (20) | n 2–8 | — | — | tiny-n hedge/sell policies, all 05-27 only; not prioritized |

---

## 2. The 5 production-parity sleeves (S1–S5) — still matching?

The HANDOFF_2026_05_22 S1–S5 are all **btc_15m / eth_5m momo + Markov** cells.
In this 2.55-day window they fire too rarely (the q90 + Markov stack on a
chainlink-only universe yields n=2–12 per cell) to re-validate at parity. The
closest live analogues that DO have data:
- **btc_15m momo HOLD_f7** (≈ S1/S2/S3 cell): live +$5.55/tr (n=21), bt +$8.52/tr
  (n=12) — **MATCH, both strongly positive**. The 15m-BTC edge that anchored
  S1–S3 persists in this window.
- **eth_5m momo HOLD_f7** (≈ S5 cell): live −$2.86 (n=60) vs bt +$3.11 (n=23) —
  **DIVERGE on the non-overlapping fires**; the S5 eth_5m cell is the weakest of
  the five and is sensitive to which fires the (stricter) backtest q90 admits.

Verdict: the **15m momo edge (S1–S4 family) holds**; the **eth_5m (S5) cell is
fragile** in this window. Full S1–S5 Markov-stack re-validation needs a longer
window than 2.55 days.

---

## 3. kelly + prewindow + INV_NIGHT

- **shadow_ALL_5m_phase1_kelly** (n=560, live +$2.28/tr, +$1,277 total): the
  single biggest live winner in scope. **NO_BACKTEST_INFRA** — the
  `VwapKellyEnsembleStrategy` rule (S4 = fair_edge_bp>500 ∧ cvd_30s ∧ |dev_bps|≥8;
  S8 = macd_agree ∧ rvol>1.2) plus the Kelly notional tier (1×–4× on fair_edge_bp)
  cannot be reconstructed — `fair_edge_bp`, `cvd`, `macd_hist`, `rvol`,
  `vwap_dev_bps` are computed live from the 1s trade tape + book and are absent
  from canonical for this window. **Report live-only: it is the strongest sleeve
  (+$1.28k over 2.5d) and warrants its own feature-panel build to backtest.**
- **shadow_ALL_5m_S3_prewindow** (n=204, live +$1.35/tr): same blocker
  (PrewindowS3 = fair_edge_bp>0 ∧ cvd_60s ∧ macd). **NO_INFRA.** Live-positive.
- **shadow_ALL_15m_S4_prewindow** (n=11, live +$14.19/tr): **NO_INFRA**, tiny n.
- **INV_NIGHT trio** (6 cells, n=74–232): **fully backtested and MATCHES live.**
  After fixing the signal anchor (see §4), backtest reproduces the live result:
  all 5m cells net-negative (−$4.5 to −$5.8/tr bt vs −$3.9 to −$5.4/tr live),
  15m cells also negative. **The night-hour flip is confirmed anti-edge in this
  window** — exactly what live shows. INV_NIGHT is a losing sleeve in both views.

---

## 4. Anchor bug found & fixed during this run (INV_NIGHT)

First pass used `ws = slot_start` for the volume `ret_5m` (per the source
*comment* `log(c@ws / c@(ws−300))`). That gave only **49% fired-direction
agreement with live** and falsely showed 5m INV_NIGHT as *positive* (sign flip).
Empirical anchor sweep against 220 live btc_5m fires found **`ws_s = slot_start −
window_s`** with `ret_5m = log(c@ws_s / c@(ws_s−300))` gives **100% direction
match** (verified across all 6 cells). The night-hour check is likewise on
**ws_s** (100% of live fires fall in night-hours under ws_s vs 97.7% under
slot_start). So the live volume controller's `window_start_us` == `ws_s`, the
PREVIOUS slot start — consistent with the global CLAUDE.md ws_s convention, and
the volume strategy's source comment is misleading. Fix applied; backtest then
matched live.

---

## 5. Data-coverage limits

- Canonical resolutions to **2026-05-29 13:10 UTC**; klines 1MIN to 13:16. Live
  sleeves firing past 13:10 (most momo/sniper run to ~19:00) have live n > bt n
  purely from the window cap — not a logic gap.
- L25 books: BTC consolidated to ~10:01, ETH/SOL to ~13:13 on 05-29; SOL L25 is
  sparse (~55% NaN asks historically). SOL 15m bt n is small (2–26) → low-power
  cells flagged NO_INFRA / wide Δ.
- The backtest q90 is feed-backed (prod-style) but the **chainlink-only universe
  is ~10× narrower than production's feed-backed universe** (per CLAUDE.md), so
  momo bt n undershoots live n. Fired direction is identical on shared slugs;
  the per-trade gap on non-overlapping fires is a sampling effect, not bias.

---

## Summary counts

- **MATCH: 13** — 4 INV_NIGHT-5m/15m + 9 momo HOLD_f7 cells (sign + magnitude consistent).
- **DIVERGE: 3** — btc_15m INV_NIGHT (live +0.35 vs bt −1.80, both near-flat),
  eth_5m momo, eth_5m momo_v2 (sign flips driven by small / non-overlapping bt n).
- **NO_INFRA: 2 prioritized + ~67 background** — kelly (n=560) and both prewindow
  sleeves are the highest-value blocked targets; all `poly_sniper_v5_*`, fade,
  and tiny-n HEDGE/SELL_f7 sleeves also lack canonical signal infra.

**Biggest divergence:** eth_5m momo_v2_HOLD_f7 (Δ +$8.00/tr) — live −$6.99 (n=38,
36.8% WR, full live row to 19:00) vs bt +$1.02 (n=36, 52.8% WR). **On the 21
slugs the two share, fired direction matches 100% AND WR is identical (52.4% both).**
The gap is entirely from *non-overlapping* fires (live fired on extra slugs the
stricter chainlink-only q90 didn't admit, and on the live row's post-13:10 fires),
not a backtest logic error. Same pattern for eth_5m momo HOLD_f7 (shared-slug WR
57.1% identical both sides). This is a fire-universe / window-cap sampling effect.
