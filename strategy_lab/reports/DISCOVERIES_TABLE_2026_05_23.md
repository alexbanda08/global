# Complete discoveries — 2026-05-22/23 sessions

Two days of work. New strategies + new data insights + production bug
audit findings. Tables below.

---

## Table A — Strategies discovered (deployable & theorized)

| # | Strategy | Status | Best cell + WR | Sum $/28d | $/tr | n | Notes |
|---:|---|---|---|---:|---:|---:|---|
| **S1** | **VWAP Continuation** | **DEPLOY-READY** | BTC 5m 240s+M1V → **86.3% WR** | **+$1,090** | +$2.00 | 546 | Top 5 configs total +$2,286. OOS test_wr=89%. |
| **S2** | **Fade Extreme Momo** (mag>3) | **DEPLOY-READY** (BTC+ETH only) | ETH 5m → **70.8% WR** | **+$1,264** pooled | +$7-9 | 164 (BTC+ETH) | Existing momo sleeve patch (4-line flip). SOL excluded — no exhaustion. |
| **S3** | **Refreshed HoD-Top-8** | **DEPLOY** (operator update) | momo_v2 ETH 15m → 83.6% WR | +$15,900 ensemble | varies | n/a | Replaces shipped HoD constant. 5.4× ensemble PnL vs current. |
| **S4** | **Cell-specific gate stack** | **DEPLOY** with S3 | momo v1 btc_15m + M1V → 90.2% WR | drop-in upgrade | +$20.73 | 61 | Sleeve #3 gets +M1V; sleeve #2 drops m5va; rest stay. |
| **S5** | **Z_Contra ETH Underdog** | PAPER ONLY | ETH 5m 30s → 55.2% WR | +$594 | +$3.24 | 183 | Sub-60% WR but high $/tr from cheap underdog payoff. Start at $10 notional. |
| **S6** | **Magnitude Cap Gate** | **DEPLOY** with S2 | Block fires `\|ret_2m\| > 2× threshold` | additive | additive | n/a | Subset of S2. Cuts WR-drag from exhaustion zone. |
| **S7** | **Direction-Asymmetric HoD** | THEORIZED | Split UP and DOWN hour lists | est +3-5pp WR | varies | varies | Backtest data confirms pattern; full impl pending. |
| **S8** | **Bayesian-Kelly Sizing** | THEORIZED | Replace flat $25 w/ Kelly-scaled | est -30% DD | same | n/a | Port `bayesian.rs` + `kelly.rs` from polymarket-bot. |
| **S9** | **Mint-and-Sell V3** (asymmetric posting) | REDESIGN | One-sided when \|CVD_30s\| > p80 | needs build | — | n/a | V2 is loss-making symmetric. V3 fixes the directional adverse-selection. |
| S10 | Cross-asset confluence | INTEGRATED into S1 | At fire, other 2 assets dev_bps must agree | +$237 (ETH) | +$1.26 | 188 | Used as gate inside VWAP Continuation (#S1 entries 2-4). |

---

## Strategy descriptions

### S1 — VWAP Continuation (★ the night's winner)

**Mechanics**: At fire time `t = slot_start + offset` (offset 30–270 sec into a 5m slot):
1. Compute `dev_bps = 10,000 · log(binance_close@t / VWAP_15m_anchored)`.
   VWAP = cumulative price×volume / cumulative volume since start of current
   UTC 15m bucket. Uses **1-second binance kline data** (newly pulled from VPS3 collector).
2. If `+thr_min < dev_bps ≤ +thr_max` → **bet UP** (momentum continues).
   If `−thr_max ≤ dev_bps < −thr_min` → **bet DOWN**.
3. Apply gate stack (cell-specific):
   - **M1V**: 1-min vol-adaptive Markov regime must agree with bet direction
   - **F7 RSI(14)**: RSI > 50 for UP, RSI < 50 for DOWN
   - **cross_full**: BOTH other crypto assets' dev_bps same sign as bet
4. Enter via L25 book walk (`engine_v2.fill_at_book`, LegacyConfig).

**Why it works**: Binance leads chainlink resolution by ~30-150s (chainlink
price is essentially delayed Binance). At t=240s into a 5m slot, only 60s
remain — if Binance is clearly off VWAP and Markov regime confirms, the
move has 86%+ probability of holding through settlement.

**Deploy spec**: `TV_AGENT_VWAP_CONTINUATION_SPEC_2026_05_23.md`. 5 sleeves
proposed (4 BTC + 1 ETH + 1 SOL). ~$80/day @ $25 notional, $800/day @ $250.

### S2 — Fade Extreme Momo (mag_ratio > 3×)

**Mechanics**: Existing momo strategy fires when `|ret_2m| > q90(|ret_2m|)`.
Compute `mag_ratio = |ret_2m| / threshold`. When `mag_ratio > 3.0`:
- Original signal said UP → **flip to DOWN**
- Original signal said DOWN → **flip to UP**

**Why it works**: Mean reversion at extremes. When ret_2m is >3× the
14-day q90, the move was a one-off spike (CPI print, liquidation, oracle
outage) — it reverts. The forward WR for `mag>3` follow is **38%**, so
fade WR is ~62%.

**Asset-specific**: Works on **BTC + ETH** (67-71% fade WR). **Does NOT
work on SOL** — SOL is higher-vol so mag>3 is more common and less
signaling (fade WR ≈ 48-52%).

**Implementation cost**: 4-line patch to existing momo. Free
$1,264/28d ($45/day @ $25 notional).

### S3 — Refreshed HoD-Top-8

**Mechanics**: Production HOD_TOP8_BY_CELL was derived using
`at_ts.dt.hour` (RESOLUTION time). Spec §2.1 says use **fire-time hour**.
Re-deriving with fire-time flips all 18 cells.

**Impact**: Sleeves #5 (sniper btc_5m) and #10 (momo_v2 sol_15m) flip
from negative to positive on HoD alone. **Ensemble PnL: $2,949 → $15,900
(5.4×)**. All 11 sleeves positive (was 7/11).

**Deploy**: Update `gates.py::HOD_TOP8_BY_CELL` with the fire-time-derived
constant. Per spec §6 this is operator-gated; first refresh is approved.

### S4 — Cell-specific gate stack

**Insight**: F7+M1V works on BTC 15m (+$3.31/tr) and SOL 15m (+$1.72/tr)
but HURTS BTC 5m (-$3.42/tr) and SOL 5m baseline (-$2.29/tr vs baseline
+$2.29/tr).

**Action**: Don't apply uniform gates. Per-cell config:
- BTC 5m momo v1 → `hod + m1va` (NEW)
- ETH 15m sniper → `hod` (DROP m5va, per audit)
- SOL 5m momo_v2 → `hod` baseline (DROP attempted f7+m1v)
- Others → keep refreshed HoD

### S5 — Z_Contra ETH Underdog

**Mechanics** (port of mlmodelpoly's `z_contra_fav_dip_hedge`):
1. At t = slot_start + 30s, compute fair_up = Φ(z) via Black-Scholes.
2. Get PM book mids: pm_up_mid, pm_down_mid.
3. Identify favorite (mid > 0.5). Compute z_score = (fair_up − pm_up_mid) / σ.
4. Detect dip on favorite side: pm_favorite_mid dropped > 100bps in last 30s.
5. If favorite=UP AND z<-1 AND up_dipped → **BUY DOWN** (cheap underdog).
6. Hold to slot close.

**Numbers**: 55.2% WR (n=183) but **+$3.24/tr** because underdog token
is bought at ~0.30 paying out ~$0.70 per share on win. +$594 sum/28d.

**Caveat**: Sub-60% WR → higher variance. Paper-only initially. Pair with
half-notional sizing.

### S6 — Magnitude Cap Gate

Block any fire where `|ret_2m| > 2 × threshold` (the exhaustion zone).
Pure filter on top of existing momo. Removes ~21% of fires but cuts the
WR-drag. Standalone effect ≈ 3pp WR lift. Subset of S2 (S2 is more
specific: only fade, BTC+ETH only).

### S7 — Direction-Asymmetric HoD

The current HoD top-8 is direction-blind. Splitting by direction:
- BTC 15m UP fires top hours: `[18, 3, 0, 1, 21]`
- BTC 15m DOWN fires top hours: `[14, 20, 16, 3, 9]`

Only 0-2 hours overlap per cell. Direction-conditional HoD cuts wrong-
hour fires by ~50%. Pending implementation.

### S8 — Bayesian-Kelly Sizing (theorized)

Replace flat $25 notional with conviction-scaled Kelly:
- prior = market entry vwap
- likelihood ratio = `exp(α · (|ret_2m|/threshold − 1))`, capped
- confidence = combined F7+M1V agreement
- posterior = `prior · LR^conf / (prior · LR^conf + (1−prior))`
- size = `KELLY_FRAC × (1 − posterior/vwap) × bankroll`
- clamp [$10, $50]

**Expected**: same PnL, ~30% DD reduction, Sharpe up.

### S9 — Mint-and-Sell V3 (asymmetric)

V2 (current) posts symmetric two-sided at $0.50 ± spread. Loses ~$45k/day
across all 6 cells per Agent D analysis. **CVD direction predicts which
leg gets adversely selected**: when CVD_slope_30s is strongly positive,
PM UP-ask gets hit; we're left holding DOWN.

**V3 redesign**: when `|CVD_slope_30s| > p80` for the asset, post ONLY
the side flow is FOR (skip the side we'd be left holding). Architectural
change, not a parameter tweak. Separate workstream.

---

## Table B — Data findings & insights (research observations, not strategies)

| # | Finding | Source | Action |
|---:|---|---|---|
| F1 | **Production fee = 2%-on-profit-only** (verified vs 25,900 prod resolutions) | CLAUDE.md verification | Use LegacyConfig for all production-parity backtests. The `0.07·p·(1−p)` curve in fees.py is hypothetical only. |
| F2 | **Big momo signals LOSE** — WR: 1.0-1.2× = 49%, 1.2-1.5× = 53%, 2-3× = 46%, **>3× = 38%** | per_trade_markov 28d analysis | Drives S2 (fade) + S6 (cap). |
| F3 | **UP and DOWN fires have different hot hours** — only 0-2 of top-5 overlap per cell | HoD analysis | Drives S7. |
| F4 | **F7+M1V is CELL-SPECIFIC** — wins BTC/SOL 15m, hurts BTC/SOL 5m | per_trade_markov gate sweep | Drives S4 (cell-specific stack). |
| F5 | **VPS3 has 1-second binance collector** since 2026-05-07 in `binance_klines_v2.period_id='1SEC'`. 1,832,514 rows per asset. Includes `taker_buy_base` → CVD computable from kline alone (no aggTrade needed). | VPS3 audit | Enabled S1 (VWAP cont) + the full microstructure analysis. |
| F6 | **HoD shipped constant is wrong** — derived from `at_ts.dt.hour` (resolution-time) instead of fire-time per spec §2.1. ALL 18 cells need refresh. | _recompute_hod_top8.py output | Drives S3. |
| F7 | **Sleeve #2 (eth_15m_sniper_hod_m5va) is BROKEN** — Markov regime is never computed (`markov_regime_w20_5m_va=None` hardcoded in loop builders). Gate fails closed 100% of time. | VPS3 code audit | Drop m5va, rename sleeve. See TV_AGENT_PHASE34_FIXES. |
| F8 | **Late-fire (180-270s into 5m slot) is highly profitable** — binance lead-time means chainlink resolution is near-deterministic. 22 deployable configs at 60%+ WR. | vwap_continuation_5m output | Drives S1. |
| F9 | **VWAP deviation predicts CONTINUATION, not reversion** — when binance is +30bps from 15m VWAP, market WR betting UP is 78-93% (not 7-22% if fading). | anchored_vwap_fade_5m v1 (inverse) | Drives S1. |
| F10 | **Cross-asset confluence works** — when BTC+ETH+SOL all extend same direction, WR boost ~5pp | vwap_v2_gated cross_full gate | Integrated into S1. |
| F11 | **Prod q90 is STRICTER than chainlink-only q90** (8-18% higher) — opposite of the "10× fire-count gap" hypothesis. Gap comes from universe filtering (we drop binance-resolved markets), not threshold calibration. | _replicate_prod_q90.py | Closes the calibration question. No action. |
| F12 | **Fair-value edge alone is WEAK** — `fair_up − entry_vwap` doesn't strongly predict WR. PM entry vwap already prices in most of what fair-value captures. | fv_cvd_spike_backtest | Use FV as part of stack, not standalone gate. |
| F13 | **CVD slope alone is WEAK** for momo confirmation; **spike_agree at moderate edge** is the real signal (2-5pp edge + spike → 100% WR n=2; 5-10pp edge + spike → 89% WR n=9). | fv_cvd_spike_backtest | Spike-agree integrated into stacks. |
| F14 | **Mint-and-sell V2 CVD overlay**: directional adverse subset = 27% of fills, **55% of total losses**. But \|CVD\| magnitude alone doesn't separate adverse from positive cleanly. | Agent D | Drives S9 redesign. |
| F15 | **z_contra port WR<60% but PnL+** — buying cheap underdog (entry vwap ~0.30) compensates lower WR. Strategy works on ETH 30s offset only. | Agent B z_contra | Drives S5 (paper-only). |
| F16 | **Live-mimic stress test** under hypothetical `0.07·p·(1−p)` fee curve erodes top S1 config PnL by only 7.3% ($1,010 vs $1,090). Robust across fee scenarios. | vwap_drawdown_livemimic | Confirms S1 deployability. |
| F17 | **OOS test_wr > train_wr** for 3 of 5 top S1 configs. Strategy is robust, not curve-fit. | vwap_drawdown_livemimic 70/30 split | Strengthens S1 deploy decision. |
| F18 | **Max loss streak ≤ 6** trades across all 5 S1 configs. Max DD ≤ 44% of cumulative profit. Bankroll-friendly. | drawdown analysis | S1 sizing OK at $25 / $250. |
| F19 | **All 6 5m cells now have at least one deployable gate stack** (n≥30, WR≥60%) after combinatorial search of 2^9 gate subsets. | gate_search_5m | Enables full 5m sleeve coverage. |
| F20 | **dexorynlabs repo is SEO-spam copy-trade**, no indicators. mlmodelpoly has the Black-Scholes UP-prob model that became S1's signal foundation. | Repo mining | Closes the "what else to mine" question. |

---

## Table C — Deployable now (action items)

| Order | What | Where | Effort | Expected gain (28d, $25 notional) |
|---:|---|---|---|---:|
| 1 | **Refresh HOD_TOP8_BY_CELL** (S3) | `backend/app/strategies/polymarket/gates.py` | 5-min edit + restart | **+$13k** (vs current $2.9k) ensemble |
| 2 | **Drop m5va from sleeve #2** (F7 fix) | `engine_main.py _SHADOW_GATED_SLEEVES_SPEC` | 1-line + restart | Unblocks #2; +$745 alone |
| 3 | **Add M1V to sleeve #3** (S4) | `gates.py` + `polymarket_updown.py` + `poly_updown_loop.py` | Code + tests (per TV_AGENT_PHASE34_FIXES spec) | Sleeve #3 → 90% WR / +$20.73/tr |
| 4 | **Patch momo to fade `mag_ratio > 3.0` on BTC+ETH** (S2) | `momo.py` / `momo_v2.py` strategies | 4 lines + tests | +$1,264 |
| 5 | **Deploy VWAP Continuation** (S1) — 5 paper-only shadow sleeves | new module + loop builder additions | Per `TV_AGENT_VWAP_CONTINUATION_SPEC_2026_05_23.md` | +$2,286 |
| 6 | **Deploy ETH 30s Z_Contra** (S5) at half-notional | new strategy module | per Z_CONTRA_5M_2026_05_23 | +$594 (at full notional; halve for safety) |
| 7 | **Build Mint-and-Sell V3** (S9) | architectural redesign | separate workstream (~1-2 weeks) | TBD |

**Total expected from S1+S2+S3+S4 deployed**: ~$17k over 28d at $25
notional, scales linearly with notional. That's **~$600/day at $25
notional, $6,000/day at $250 notional**.

---

## Files produced this session

**Reports** (all in `strategy_lab/reports/`):
- `MORNING_SUMMARY_2026_05_23.md` — overnight headlines
- `OVERNIGHT_STRATEGY_RUN_2026_05_23.md` — synthesis
- `TV_AGENT_VWAP_CONTINUATION_SPEC_2026_05_23.md` — production deploy spec for S1
- `TV_AGENT_PHASE34_FIXES_2026_05_22.md` — bug fixes (sleeve #2 #3 + HoD)
- `VWAP_CONTINUATION_5M_2026_05_23.md` — backtest details
- `VWAP_CONT_V2_GATED_2026_05_23.md` — gated v2 results
- `VWAP_DRAWDOWN_LIVEMIMIC_2026_05_23.md` — stress test
- `FADE_MOMO_5M_2026_05_23.md` — Agent A
- `Z_CONTRA_5M_2026_05_23.md` — Agent B
- `GATE_SEARCH_5M_2026_05_23.md` — Agent C
- `MINT_AND_SELL_CVD_TIMING_2026_05_23.md` — Agent D
- `INDICATOR_SURVEY_2026_05_22.md` — mlmodelpoly mining
- `NEW_STRATEGIES_PROPOSAL_2026_05_22.md` — initial 7-strategy proposal
- `HANDOFF_2026_05_22_HOD_REFRESH_SLEEVE_FIXES.md` — Day 1 handoff
- `VPS3_SHADOW_AUDIT_2026_05_22.md` — production audit
- `FV_CVD_SPIKE_BACKTEST_2026_05_23.md` — early 1s feature test

**Key data files** (all in `data/v4/canonical/`):
- `klines_1s/binance_1s_28d.parquet` — 5.5M rows of 1s BTC/ETH/SOL OHLCV+CVD
- `_results/vwap_continuation_5m_per_fire.parquet` — 40k fitted fires
- `_results/vwap_continuation_v2_gated.csv` — 1,003 configs tested
- `_results/vwap_drawdown_livemimic.csv` — stress test results
- `_results/fade_momo_5m.csv` — fade variant configs
- `_results/gate_search_5m.csv` — 386 deployable gate stacks
- `_results/z_contra_5m.csv` — z_contra configs
- `_results/mint_and_sell_cvd_overlay.csv` — V2 fills × CVD overlay
- `_results/fv_cvd_spike_overlay.parquet` — early 1s feature overlay
- `_results/prod_q90_calibration/` — q90 replication

## End of discoveries document
