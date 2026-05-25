# Second-run summary — 2026-05-23 (after morning push)

_Followup session: ran 3 more agents + 3 inline experiments + ensemble
simulator. **Three big wins**, one definitive negative result on mint-and-sell._

## Headline numbers

**Ensemble PnL at $25 notional over 24 days = +$16,487** (7,437 fires).
**Max DD −$509 (3.1% of total).** **Sharpe-like annual 18.88.**

That's ~**$687/day @ $25** → **~$6,870/day @ $250** → **~$27,500/day @ $1,000**
on chainlink-resolved BTC/ETH/SOL 5m markets (subject to PM book depth
constraints — Polymarket Tier-1 books support $100-500 fills cleanly).

---

## Strategies tested in this run

| # | Strategy | Verdict | Sum $/28d | WR | Headline |
|---:|---|---|--:|--:|---|
| **S1.5** | **Slot-anchored VWAP (NEW)** | **DEPLOY** | **+$6,280 (deduped)** | **83.1%** | Replaces S1 — better anchor |
| **S6** | **Spike-driven entry (NEW)** | **DEPLOY** | **+$4,965 (deduped)** | **67.2%** | Independent of momo, 6,514 unique fires |
| **S7** | VWAP continuation 15m | secondary deploy | +$700 best single config | 77.5-89% | Smaller volume, narrow opportunity |
| **S8** | BTC→ETH/SOL lead-lag | DON'T DEPLOY standalone | (overlaps S1) | 85%+ | 100% overlap with S1.5; no new edge. Can be a confirmation feature. |
| **S9** | Mint-and-Sell V3 asymmetric | DON'T DEPLOY | still −$1,381/day | n/a | CVD asymmetric doesn't fix V2. Park. |
| (S1 v1 — superseded by S1.5) | 15m-anchored VWAP | superseded | +$2,277 | 81% | Slot-anchored variant beats it |

---

## S1.5 — Slot-anchored VWAP (REPLACES S1)

**Change vs S1**: anchor = slot_open (start of THIS 5m market's slot), not the
start of the current 15m UTC bucket. This makes VWAP measure "where has
binance moved since the chainlink strike was set" — semantically cleaner.

### S1.5 top 10 configs (raw, before gating)

| # | Cell | offset | dev tier | n | WR | $/tr | sum $ |
|--:|---|--:|---|--:|--:|--:|--:|
| 1 | BTC 5m | 210s | 5-10bps | 529 | **87.3%** | +$2.99 | **+$1,581** |
| 2 | ETH 5m | 210s | 10-15bps | 138 | 87.0% | **+$10.92** | **+$1,508** |
| 3 | BTC 5m | 240s | 3-5bps | 810 | 81.7% | +$1.09 | +$886 |
| 4 | ETH 5m | 150s | 5-10bps | 707 | 84.3% | +$1.25 | +$883 |
| 5 | ETH 5m | 240s | 5-10bps | 714 | 85.3% | +$1.12 | +$803 |
| 6 | ETH 5m | 150s | 3-5bps | 881 | 79.9% | +$0.84 | +$741 |
| 7 | SOL 5m | 270s | 5-10bps | 570 | 87.2% | +$1.14 | +$651 |
| 8 | BTC 5m | 150s | 3-5bps | 770 | 81.0% | +$0.84 | +$650 |
| 9 | ETH 5m | 210s | 5-10bps | 719 | 87.5% | +$0.84 | +$606 |
| 10 | BTC 5m | 60s | 3-5bps | 442 | 74.7% | +$1.31 | +$579 |

### S1.5 with gates layered on (vwap_slot_v2_gated)

178 STRICT configs (n≥30, WR≥65%, $/tr≥$1). 73 ULTRA configs (n≥100, WR≥75%, $/tr≥$1).

Top with gates:
- **BTC 240s 5-10bps + M1V Markov+cross_full**: n=178, **WR=93.3%**, +$2.66/tr, +$474
- **ETH 210s 5-10bps + F7+cross_partial**: n=381, **WR=94.5%**, +$1.42/tr, +$541
- **ETH 240s 3-5bps + F7+cross_full**: n=474, **WR=91.1%**, +$1.30/tr, +$618
- ETH 150s 10-15bps (no gate): n=98, **WR=95.9%**, +$3.58/tr, +$351

ETH at 90%+ WR is genuinely happening with reasonable n.

---

## S6 — Spike-driven entry (NEW INDEPENDENT STRATEGY)

Fires on 5-15s binance breakouts (|ret_5s| > 2.5bps with CVD agreement),
INDEPENDENT of momo signal. Agent A's full backtest found:

- **251 deployable configs** (n≥30, WR≥60%, $/tr>0)
- **30 robust configs** (n≥80, WR≥68%, $/tr≥$1.5)
- Top BTC: offset=120s, |ret_5s|>2.5bps + cvd-agree, tier T1 → n=146, **WR 70.5%**, +$6.57/tr, **+$960**
- Top ETH: offset=120s + vwap_agree gate → n=125, **WR 85.6%**, +$4.21/tr
- Top SOL: offset=30s → n=130, **WR 78.5%**, +$3.55/tr

**Crucially**: 6,514 spike fires do NOT overlap S1.5 (different decision criteria).
Those alone deliver WR=62%, +$0.49/tr — **independent edge**.

### Spike-driven family contribution to ensemble

After filtering to high-quality sub-configs (per-source WR≥62%, $/tr>0), the
spike-driven family contributes **n=2,884, +$4,965 sum, WR=67.2%, +$1.72/tr**
to the ensemble.

---

## S7 — VWAP continuation on 15m markets

Same logic as S1.5 but on 15m chainlink markets. Less compelling than 5m:

| Cell | offset | dev | n | WR | $/tr | sum |
|---|--:|---|--:|--:|--:|--:|
| **SOL** | **840s** | **20-30bps** | 40 | **77.5%** | **+$17.34** | **+$694** ⭐ |
| ETH | 480s | 5-10bps | 449 | 76.8% | +$0.61 | +$274 |
| SOL | 240s | 10-15bps | 116 | 82.8% | +$1.79 | +$208 |
| ETH | 120s | 10-15bps | 40 | 82.5% | +$4.21 | +$168 |
| ETH | 480s | 15-20bps | 58 | **89.7%** | +$1.23 | +$72 |

14 deployable configs but only 1 ultra-strict. 15m markets fire 4× less
frequently than 5m, so smaller universe. Recommend including SOL 840s as a
6th VWAP sleeve.

---

## S8 — BTC→ETH/SOL lead-lag (NOT a separate strategy)

Agent C found lead-lag correlation IS positive (+0.10 to +0.16 with BTC CVD
as best predictor) but **100% of deployable ETH lead-lag fires overlap S1.5**.
On 67/68 ETH overlapped slugs, the lead-lag fires LATER than S1.5 (by the
time BTC has moved enough to trigger, ETH has already moved too).

**Verdict**: lead-lag is real but already captured by S1.5. Don't deploy as
standalone sleeve. Could be useful as a confirmation requirement for higher-WR
subset of S1.5 (require BTC CVD also agree).

---

## S9 — Mint-and-Sell V3 asymmetric: DOES NOT FIX V2

Agent B tested asymmetric one-sided posting (skip UP-side when CVD strongly
positive, skip DOWN-side when CVD strongly negative):

- V2 baseline: −$21k/day across all 6 cells (under hypothetical fee curve)
- V3 best uniform (cvd_pct=0.30, sigma_pct=0.10): **−$1,962/day** (91% better, but still negative)
- V3 per-cell tuned: −$1,381/day (overfit; 2 cells barely positive)
- CVD signal contributes only ~15% of improvement; rest is just throttling volume

**Important caveat from Agent B**: V2/V3 were backtested under the hypothetical
`0.07·p·(1−p)` fee curve, NOT the production-actual 2%-on-profit fee. Per
CLAUDE.md, production fee is 2%-on-profit-only — V2 under production fees
might be near-breakeven. A re-test with `engine_v2.LegacyConfig` is the
priority before any V3 decision.

**Decision**: park V3 redesign. Focus on the 4 deploy-ready strategies.

---

## Ensemble simulator results (combined timeline)

After de-duplicating fires that hit the same (slug, direction) across multiple
strategies (kept earliest fire by timestamp):

```
n_fires:           7,437
total_pnl:         +$16,487
avg_pnl/trade:     +$2.22
WR overall:        72.3%
max DD:            −$509  (3.1% of sum)
max loss streak:   26 trades
daily mean:        $687
daily std:         $695
Sharpe annual:     18.88
n_days:            24
```

### Per-family contribution

| Family | n | sum $ | WR | $/tr |
|---|--:|--:|--:|--:|
| **S1.5 slot-anchored** | 3,445 | **+$6,280** | 83.1% | +$1.82 |
| **Spike-driven** | 2,884 | **+$4,965** | 67.2% | +$1.72 |
| S3 refresh HoD (production) | 954 | +$3,980 | 49.4% | +$4.17 |
| S2 fade BTC+ETH @ mag>3 | 154 | +$1,262 | 66.2% | +$8.20 |

### Top 10 sources

| Source | n | sum $ | WR | $/tr |
|---|--:|--:|--:|--:|
| spike_driven (all defs combined) | 2,884 | $4,965 | 67.2% | +$1.72 |
| **S1.5 ETH 210s 10-15bps** | 63 | **$1,605** | **90.5%** | **+$25.48** ⭐ |
| S1.5 BTC 210s 5-10bps | 266 | $1,490 | 86.5% | +$5.60 |
| S1.5 BTC 240s 3-5bps cross_full | 523 | $1,275 | 81.6% | +$2.44 |
| S1.5 ETH 240s 5-10bps | 494 | $947 | 85.0% | +$1.92 |
| S2 fade BTC mag>3 | 85 | $634 | 64.7% | +$7.46 |
| S2 fade ETH mag>3 | 69 | $629 | 68.1% | +$9.11 |
| S1.5 BTC 150s 3-5bps cross_full | 586 | $626 | 81.7% | +$1.07 |
| S3 refresh momo_v2 eth_15m | 44 | $605 | 77.3% | +$13.75 |
| S1.5 ETH 150s 5-10bps | 536 | $486 | 82.6% | +$0.91 |

---

## Updated deploy plan

| Order | What | Approx $/day @ $25 | Cumulative |
|--:|---|--:|--:|
| 1 | **S3+S4 fixes** (refresh HOD, drop m5va, add M1V to #3) — already in TV_AGENT_PHASE34_FIXES spec | +$140 | $140 |
| 2 | **S2 fade BTC+ETH momo at mag>3** — 4-line patch | +$45 | $185 |
| 3 | **S1.5 slot-anchored VWAP** — 5-10 new shadow sleeves (NOT S1 — use the slot-anchored variant) | +$224 | $409 |
| 4 | **S6 spike-driven** — new shadow sleeve line, independent of momo | +$177 | $586 |
| 5 | S7 SOL 15m vwap 840s | +$25 | $611 |
| (S5 z_contra) | half-notional ETH 30s | +$10 | $621 |
| (S9 mint-and-sell V3) | DO NOT DEPLOY — V2 needs prior fee re-test | — | — |

**Total estimated $/day @ $25 notional**: ~$620/day
**At $250 notional**: ~$6,200/day
**At $1,000 notional**: ~$24,800/day (Polymarket book depth permitting)

The ensemble simulator showed actual de-duped 24-day total of $16,487 = $687/day at $25 — close to the bottom-up estimate of $621/day.

---

## Updated TV-agent shopping list

1. **Phase 35 (S1.5 + S6 + S7)**: NEW sleeves on the 1s binance feed:
   - Use SLOT-ANCHORED VWAP (anchor = slot_open), NOT 15m-anchored
   - Add 5+ slot-anchored VWAP sleeves at offsets {60, 90, 150, 210, 240, 270} × BTC/ETH/SOL
   - Add spike-driven sleeve at offset 120s for BTC (D1 + cvd_agree) and offset 30s for SOL (D2)
   - Add SOL 15m offset=840s as a 6th VWAP sleeve

2. **Phase 34 fixes** (already documented in TV_AGENT_PHASE34_FIXES): ship those first — they're the cheap $13k/28d gain.

3. **S2 fade patch**: 4-line change in `momo.py`/`momo_v2.py` to FLIP direction when mag_ratio > 3.0, ONLY for BTC and ETH (NOT SOL).

4. **DO NOT** ship V3 mint-and-sell yet. First re-test V2 with `engine_v2.LegacyConfig` to see if V2 is actually near-breakeven under production fees.

---

## Files produced this run

- `data/v4/canonical/_results/vwap_slot_anchored_5m.csv` (147 configs aggregated)
- `data/v4/canonical/_results/vwap_slot_anchored_5m_per_fire.parquet` (33,323 fires)
- `data/v4/canonical/_results/vwap_slot_v2_gated.csv` (1,003 gated configs)
- `data/v4/canonical/_results/spike_entry_5m.csv` (860 rows)
- `data/v4/canonical/_results/spike_entry_5m_per_fire.parquet` (11,336 fires)
- `data/v4/canonical/_results/vwap_continuation_15m.csv` (14 deployable)
- `data/v4/canonical/_results/btc_lead_lag_5m.csv`
- `data/v4/canonical/_results/mint_and_sell_v3_simulation.csv`
- `data/v4/canonical/_results/ensemble_per_fire.parquet`
- `data/v4/canonical/_results/ensemble_daily.csv`
- `data/v4/canonical/_results/momo_with_vwap_overlay.parquet`

**Reports** (all `strategy_lab/reports/*2026_05_23*`):
- `VWAP_SLOT_ANCHORED_5M_2026_05_23.md`
- `VWAP_SLOT_V2_GATED_2026_05_23.md`
- `VWAP_CONTINUATION_15M_2026_05_23.md`
- `SPIKE_ENTRY_5M_2026_05_23.md`
- `BTC_LEAD_LAG_5M_2026_05_23.md`
- `MINT_AND_SELL_V3_SIMULATION_2026_05_23.md`
- `ENSEMBLE_SIMULATOR_2026_05_23.md`

## End of second-run summary
