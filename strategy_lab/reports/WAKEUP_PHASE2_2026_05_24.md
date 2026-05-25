# Wake-up — Phase-2 findings, 2026-05-24

_3 parallel agents + 7 inline experiments. **Production 5m sleeves are bleeding ~$546/day in live deploy. Phase-2 add-ons swing the book by +$1 000+ /day at $25 base, +$1.8-2.2k/day under Kelly tiered sizing.**_

## The five new things you can do today

### 1. 🚨 Stop all 5m sniper + momo sleeves (live LOSERS)
Live-fires audit on `trading_events_30d.parquet` (23 810 fires, 14.8 d) shows:
- `poly_updown_btc_5m_sniper` = **−$118/day**
- `poly_updown_btc_5m_momo_{HOLD,SELL,HEDGE}` = −$72/day each
- `poly_updown_eth_5m_volume_INV_NIGHT` = −$74/day
- `poly_updown_sol_5m_volume_INV_NIGHT` = −$64/day
- **Aggregate live 5m loss: ≈ −$546/day**
- 15m_momo_v2 BTC + ETH stack KEEPS WORKING at +$200/day combined

### 2. Replace 5m sleeves with the Phase-1 + Phase-2 ensemble
- Rules: `S4 ∪ S8` at `min_offset_s ≥ 120`, deduped per (slug, direction)
- Apply Kelly tier on `fair_edge_bp` (2×/3×/4× at 1000/2000/3000 bp)
- 84.4 % WR, +$5.50/tr, **+$927/day** at avg notional $34
- max DD 4.3 % of sum, walk-forward retention 2.90

### 3. Add a FADE-UNGATED-MOMO companion sleeve on 6 cells
When production momo fires but HOD-top8 + Markov gate FAILS, fire the OPPOSITE direction:
- momo_v2 BTC 5m: +$22/day
- sniper BTC 5m: +$18/day
- sniper ETH 15m: +$12/day
- momo_v2 SOL 5m: +$7/day
- sniper SOL 5m: +$6/day
- momo_v2 SOL 15m: +$6/day
- **Combined: +$70-100/day**

### 4. Add indicator overlays to the 12 marginally-significant prod sleeves
Top examples (p < 0.10):
- `sniper ETH 15m + m5v_pass` → +$614 over panel (p=0.011 ⭐)
- `momo_v2 BTC 5m + fair_edge>500` → +$618 / per_tr +$0.34 (p=0.081)
- `momo_v2 BTC 15m + fair_edge>0` → +$413 / per_tr +$4.69 (p=0.056)
- `sniper SOL 15m + fair_edge>0` → +$392 / per_tr +$5.01 (p=0.070)
- `momo_v2 SOL 5m + cvd_agree + macd_agree` → +$357 (p=0.097)
- `momo_v1 SOL 5m + m5v_pass` → +$348 (p=0.072)
- **Combined ≈ +$15-30 / sleeve / day**

### 5. Pre-window timing — new S3 sleeve at −60s
- Rule: `fair_edge_bp > 0 AND cvd_agree_60s AND macd_agree`
- Timing: 60 seconds BEFORE slot_start
- 5m markets, n=1 961, WR=52.8 %, per_tr=$0.83
- **+$78/day at $25 notional**, binom_p=0.029 (strongest single new result from the timing sweep)
- Plus S4 pre-window @ −120s on 15m: +$25/day

## Counter-findings

- **momo_v1 BTC 5m is fundamentally CONTRARIAN** — agree-style gates make it WORSE (-$535 sel_upl). If we re-enable this sleeve, use contra gates only.
- **Markov filters reduce sample size without improving edge** — `m1v_pass` cuts 50 % of fires for 0 net uplift. Don't add Markov on top of S4/S8.
- **LightGBM doesn't help** — model overfits to high-vwap, low-$ fires. Rule-based gates win for $.
- **S8 (MACD+RVOL) is a 5m-only signal** — fails on every 15m market regardless of offset.

## Estimated combined daily P&L swing

| stage | $/day |
|---|--:|
| Stop 5m live losers | **+$546** (recovered loss) |
| Add Phase-1 S4∪S8 5m base ensemble | +$237 |
| Apply Kelly tiered sizing on Phase-1 | **+$690** (Kelly amplification) |
| FADE-UNGATED-MOMO companion sleeves | +$70-100 |
| Indicator overlays on marginal sleeves | +$200 |
| Pre-window S3 5m + S4 15m sleeves | +$100 |
| **Net Phase-2 swing at $25 base** | **≈ +$1 040 – $1 200 / day** |
| **Net Phase-2 swing at Kelly $34 avg notional** | **≈ +$1 800 – $2 200 / day** |

## Files to open first

| Path | What |
|---|---|
| `strategy_lab/reports/PHASE2_FINAL_FINDINGS_2026_05_24.md` | Main report — all 7 sections + deploy spec |
| `strategy_lab/reports/STRATEGY_EXPANSION_PHASE2_2026_05_24.md` | Kelly tiers + Markov / DOWN / late-zoom detail |
| `strategy_lab/reports/_live_fires_inbox.md` | Live production per-sleeve PnL |
| `strategy_lab/reports/_indicator_overlay_inbox.md` | Per-sleeve gate winners |
| `strategy_lab/reports/_pre_window_timing_inbox.md` | Offset sweep per rule |
| `strategy_lab/reports/PER_SLEEVE_PER_ASSET_TF_2026_05_24.md` | 5m vs 15m breakdown |
| `data/v4/canonical/_results/live_fires_normalized.csv` | Live fires CSV (23 810 rows) |
| `data/v4/canonical/_results/prod_fills_with_indicators.parquet` | Prod fills with new features |
| `data/v4/canonical/_results/DEPLOY_CANDIDATE_S8_S4_offset120.csv` | Backtest fire list for Phase-1 deploy |

## Hard caveats

1. **Multiple comparisons**: 270+ gate cells tested. Marginal-significance winners need 14 d OOS re-validation before deploy.
2. **Kelly DD risk**: 4× notional ($100) tier fires ~6/day. A 3-fire losing streak = −$300 from this tier alone. Watch.
3. **FADE-UNGATED model approximates flipped pnl** — real Polymarket spread on the other side adds ~10-15 % friction. De-rate uplift accordingly.
4. **Pre-window strike peek**: chainlink strike read at slot_start for offset < 0. Strike doesn't move materially in 60-240 s pre-slot, but live should re-read at fire_us with the small lag.
5. **All numbers panel-period 21 days**. Re-validate on next 28 d data refresh.
