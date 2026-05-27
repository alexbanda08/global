# HL Strategy Research — Master Plan (2026-05-26)

**Mission:** Find NEW directional strategies for Hyperliquid perpetual futures. Reuse Polymarket-built engines and indicator stack. Port what's portable, invent what's missing.

---

## 1. ASSETS WE HAVE (no Binance Vision pull needed)

### 1.1 Reusable engines (strategy_lab/)

| Module | Purpose | Port effort |
|---|---|---|
| `engine_v2.py` | LiveMimic + Legacy fee/latency/book-walk | Refactor fee model: HL taker 0.045% / maker 0.015% / funding accrual |
| `walk_forward.py` | Rolling train/test splitter | 1:1 reuse |
| `drz/walk_forward.py` | Drawdown-regime-zoned splitter | 1:1 reuse |
| `markov_filter/markov_regime_micro.py` | 3-state BULL/BEAR/SIDEWAYS labeler (vol-adaptive q33/q66) | 1:1 reuse + recalibrate thresholds per asset |
| `meta_classifier/` | RF/XGB/GBM trainer + walk-forward + hybrid join | 1:1 reuse on new feature panel |
| `ga_optimizer/` | Genetic param search + strict-OOS gate | 1:1 reuse |
| `book_walk.py` + `latency.py` | Fill simulation | Refactor: HL has L2 not L25 |
| `eval/metrics.py` | Sharpe / Sortino / MDD / deflated Sharpe | 1:1 reuse |
| `confluence/` | Multi-market signal aggregator | 1:1 reuse |

### 1.2 Indicator library (12 families, all coded + tested)

- Classic TA: RSI Wilder (F7), EMA ribbon, Stoch, BB, MFI, CCI, ATR, ADX
- QR Lite: 5-layer EMA pairs + alignment + market_health + signal_confidence
- SMS: CHoCH/BOS pivots, RSI divergence, multi-TF trend stack, CVD tier, liquidity sweeps
- Traders Reality: 5-EMA stack, PVSRA candles, daily/weekly pivots + Camarilla, session detection (5 sessions), psych levels
- Range Filter (Donovan Wall): rfilt direction + bands + dist_bps
- Regime Panel: ADX + realized vol + range compression + trend slope → 3-state label
- MA Ribbon Strategy (5m standalone)
- Hybrid Feature Join (100+ cols, causal asof-merge)
- Cross-Asset MTF Confluence
- Markov Regime (1m fixed + vol-adaptive variants)
- F1–F7 series (whale signals + RSI)
- Orderbook microstructure (in-dev; book imbalance, microprice, Kyle's lambda)

### 1.3 Data

| Source | Range | Symbols | Notes |
|---|---|---|---|
| **Binance SPOT klines (per-symbol parquet archive)** | 2017-08 → 2026-03-31 (**8.6y BTC/ETH**, 5.6y SOL, 5-8y alts) | BTC, ETH, SOL (full 6 TFs: 1m/5m/15m/1h/4h/1d) + ADA, AVAX, BNB, DOGE, LINK, SUI, TON, XRP (15m/1h/4h only) — **11 symbols total** | `data/binance/parquet/{SYM}/{TF}/year=YYYY/part.parquet` (1 GB total). The CONSOLIDATED `binance_vision_klines.parquet` (92 MB, 3 symbols, 12 months) is a smaller cached subset — prefer the per-symbol archive. **Delta refresh Apr-May 2026 running in background.** |
| **Binance FUTURES metrics (OI, taker L/S ratios)** | 2020 → 2026 (**6y BTC**, 5y ETH/SOL) | BTC, ETH, SOL | `data/binance/futures/metrics/{SYM}/parquet/year=*/`. NOT klines — contains: sum_open_interest, sum_taker_long_short_vol_ratio, count_long_short_ratio, count_toptrader_long_short_ratio. GOLDEN for funding/positioning signals. |
| **Binance funding rates** | hist | BTC, ETH, SOL | Available |
| **Binance premium index** | 1h | BTC, ETH, SOL | Available |
| **Hyperliquid klines** | 2026-01-30 → 2026-05-16 (**106 days**, NOT 2.3y as CLAUDE.md says) | **BTC, ETH, SOL, HYPE only** (4 coins) at 1m/5m/15m/1h/4h/1d | `data/v4/canonical/hyperliquid_klines.parquet`. **CORRECTION**: prior context said 2.3y / full universe — actual audit shows 106d / 4 coins. |
| **Hyperliquid trades** | 30d rolling | full | 588 MB |
| **Hyperliquid liquidations** | **Apr 2025 → Feb 2026 full**, 30d rolling current | full | 337 MB full + 21 MB delta |
| **Hyperliquid funding** | hourly hist | full | 189 KB |

**Verdict:** No Binance Vision pull required. Data window adequate. The only gap: HL trade tape only 30d rolling (limits microstructure research) and HL kline window only 2.3y (use Binance as proxy for longer-window strategies).

### 1.4 Existing HL strategies (reuse as seed, not anchor)

- **V52 Champion** — 6 sleeves on BTC/ETH/SOL/AVAX/LINK at **4h** (Sharpe 2.65, MDD −5.7%, validated 2.3y). Sleeves: CCI_ETH, STF_SOL, STF_AVAX, LATBB_AVAX, MFI_ETH, VP_LINK, MFI_SOL, SVD_AVAX. **Ready-to-deploy.**
- **Strategy C (liq cascades)** — experimental, 5m/15m on BTC/ETH/SOL, threshold sweep over liq size.
- **V52 gate runner** — 10-gate battery (perm test, walk-forward, MC).

---

## 2. PORTABLE FROM POLYMARKET (verified directional patterns)

| Strategy | Port Score | Adaptation |
|---|---|---|
| **Cyclops S7 X1** (3-axis: trend+levels+momentum coherence) | 4.5/5 | Replace binary $25 → notional sized by regime + vol. Hold to opposite signal vs fixed 5m. |
| **F7 RSI gate** (Wilder simple-mean RSI at ws_s − window_s) | 4/5 | Gate on entry: RSI>50 longs, RSI<50 shorts. Use HL spot klines or Binance proxy. |
| **Markov regime gate** (vol-adaptive 20-bar log-ret BULL/SIDEWAYS/BEAR) | 4/5 | Use as **position-sizing** signal (novel for futures): 0× in transitions, 1× stable, 2× confirmed trend. |
| **Hybrid feature meta-classifier** (RF/XGB on 100+ features) | 5/5 | Train on HL bars → predict next-bar direction. Walk-forward + permutation gates. |
| **MA Ribbon Strategy (5m)** | 4/5 | Direct port — ribbon color/alignment/expansion fires translate as entry signals. |
| **BDH flow-contrarian** | 2/5 | Breaks under mark-to-market. Skip unless we redesign as "spread compression" trade. |
| **Momo 2A/2B/2C timing variants** | 2/5 | Fee-model-sensitive in binary. In futures the entry-timing edge may evaporate. Skip initial. |

---

## 3. NOVEL ANGLES UNIQUE TO HL FUTURES (12 hypotheses)

Ranked by expected edge × feasibility. **Bold = phase-1 priorities.**

| # | Hypothesis | Why novel for HL | Data needed |
|---|---|---|---|
| **N1** | **HL liquidation cascade momentum** — large liq → 1-5 min continuation OR 5-15 min reversion | HL publishes liq feed (rare!) | HL liqs full (have) + HL klines |
| **N2** | **Funding rate divergence reversal** — extreme funding (>+30bp/8h) → contrarian short, mean revert | Funding is perp-only signal | HL funding (have) + Binance funding |
| **N3** | **Spot-perp basis carry** — basis vs realized funding spread → arb | Requires both, we have both | Binance spot + funding |
| **N4** | **Markov regime-sized leverage** (not binary gate) — leverage scales with regime persistence | Polymarket binary cannot size; futures can | Klines only |
| **N5** | **Cross-asset lead-lag pairs** — BTC leads ETH leads SOL by ~30-180s on macro moves; pair long/short | Polymarket trades each asset separately | Binance 1m all assets |
| **N6** | **Session-based regime switching** — Asia low-vol → mean revert, NY high-vol → momentum | Polymarket 5/15m hold misses session structure | Klines + TR sessions |
| **N7** | **Vol regime switching** (Range Filter trending vs ranging) — switch strategy by regime | Polymarket couldn't size shorts | Klines + RF panel |
| **N8** | **Meta-classifier (RF/XGB) on full hybrid feature panel** — let ML find non-linear patterns | We have 100+ engineered features unused on HL | Hybrid panel build |
| **N9** | **Cyclops 3-axis port to HL 5m/15m** — direct directional baseline | Already validated on PM, should transfer | Klines |
| **N10** | **HL orderbook microstructure** — microprice, Kyle's lambda, book imbalance | Polymarket had L25; HL has L2 | HL trades + book (limited 30d) |
| **N11** | **Structure-break pairs** (SMS CHoCH/BOS) — when BTC breaks structure UP but ETH/SOL haven't → pair trade convergence | Polymarket binary can't pair | Multi-asset klines + SMS |
| **N12** | **Macro session × day-of-week × hour-of-day bias matrix** — derive expected drift conditional on calendar | Polymarket holds too short to capture | Klines + TR calendar |

---

## 4. RESEARCH ROADMAP (4 waves)

### Wave 1 — Foundation (parallel, ~2-3h)
- **W1.1** Build HL feature panel (port indicators to HL 5m/15m/1h/4h klines): TA, QR, SMS, TR, RF, Regime, Markov
- **W1.2** Build cross-feature panel: funding rate features, basis features, liquidation features, HL microstructure features
- **W1.3** Baseline Cyclops / F7 / Markov gate on HL (port directly, measure parity)
- **W1.4** Build HL fee/latency engine config (engine_v2 HyperliquidConfig)

### Wave 2 — Hypothesis testing (parallel, ~3-4h)
Run 12 novel-angle backtests in parallel batches:
- N1 (liq cascade), N2 (funding extremes), N3 (basis carry), N5 (lead-lag pairs)
- N6 (session), N7 (vol regime), N9 (Cyclops port), N11 (structure-break pairs)
- Each with: walk-forward (4 windows, train 18m / test 6m), permutation test (n=1000), MC bootstrap (n=10k)

### Wave 3 — Meta-classifier (sequential after W1 features ready)
- N8: train RF + XGB on full feature panel → predict 5m and 15m direction
- Permutation importance → identify top features
- Out-of-sample lift over baseline

### Wave 4 — Composite ensemble + sizing
- N4 (Markov-sized leverage) layered on top of winning Wave-2 strategies
- Build a portfolio of decorrelated sleeves (target Sharpe > 2 ex-fees)
- Stress with MC bootstrap, deflated Sharpe, regime hold-out tests

---

## 5. VALIDATION GATES (every strategy must pass)

1. **G1 — Stat sig**: p < 0.05 binomial vs 50% baseline
2. **G2 — Costs realistic**: HL taker 0.045% × 2 + funding accrual + slippage modeled
3. **G3 — OOS hold-out**: 6m test window after 18m train, ≥ 1 cycle full bull+bear
4. **G4 — Permutation**: Sharpe > 95th pct of random reshuffles (n=1000)
5. **G5 — Walk-forward stability**: Sharpe consistent across ≥ 3 rolling windows
6. **G6 — Monte Carlo**: 10k-bootstrap Sharpe lower-95% CI > 0
7. **G7 — Regime hold-out**: Sharpe doesn't collapse in any single regime (trending up / down / ranging)

Only candidates passing G1-G7 advance to paper-deploy spec.

---

## 6. KEY RISKS / TRAPS

- **Lookahead via slot vs ws_s anchor**: HL bars are continuous (no slot concept), but Polymarket-built features anchored at `ws_s = slot_start − window_s`. For HL, the convention is anchor signal at **bar close**, enter on **next bar open** (or strict-asof with latency).
- **30d HL trade window** limits microstructure backtests to recent month — use Binance proxy or fall back to ratio-based features.
- **Survivorship bias**: V52 was discovered via heavy ML search on 2.3y; novel discovered strategies must pass deflated Sharpe (account for # tested hypotheses).
- **Funding cost compounds**: a strategy with 80% WR but 8h hold has potentially $5-10/contract funding drag.
- **HL liq data only Apr 2025+** — N1 backtest limited to ~13 months full + 30d delta.

---

## 7. OPEN SCOPE QUESTIONS (locked after user input)

- Q1 — Asset universe: BTC/ETH/SOL only OR include V52's broader basket (AVAX, LINK + maybe DOGE/BNB)?
- Q2 — Timeframes priority: 5m+15m (Polymarket parity) OR include 1h/4h (V52 parity, less fee drag)?
- Q3 — Hold horizon: short (≤30min, Polymarket-like) OR adaptive (signal-to-opposite, can be hours/days)?

---

## 8. OUTPUTS

Each wave writes to `strategy_lab/hl_research_2026_05_26/`:

- `WAVE1_FEATURES.md` — feature panel inventory + sanity checks
- `WAVE2_HYPOTHESES/` — 12 sub-reports, one per N# hypothesis
- `WAVE3_META.md` — meta-classifier results + feature importances
- `WAVE4_ENSEMBLE.md` — final portfolio + deploy candidates
- `MASTER_TABLE.csv` — every hypothesis with full G1-G7 scorecard
- `PAPER_DEPLOY_CANDIDATES.md` — final shortlist ready for live paper-test
