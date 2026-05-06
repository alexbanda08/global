# V3 Shadow vs Backtest — VPS3 Live Reconciliation

_Generated: 2026-05-05_

## Setup

Pulled all V3-family resolutions from VPS3 `trading.events` (kind=`poly_updown_resolution`, sleeve_id LIKE `poly_updown_%_v3%`).

- Source: VPS3 (root@185.190.143.7) → /tmp/v3_resolutions_latest.csv → SCP local
- Total rows: 190
- Sleeves observed: 11 (poly_updown_btc_5m_v3, poly_updown_btc_5m_v3_1, poly_updown_btc_5m_v3_2, poly_updown_btc_5m_v3_3, poly_updown_eth_5m_v3, poly_updown_eth_5m_v3_1, poly_updown_eth_5m_v3_2, poly_updown_sol_5m_v3, poly_updown_sol_5m_v3_1, poly_updown_sol_5m_v3_2, poly_updown_sol_5m_v3_3)
- Date range: 2026-04-30 07:46:00.692075+02:00 → 2026-05-05 23:45:50.399093+02:00
- Mode: {'paper': 190}

## Production execution semantics observed in shadow

- Entry price (median):  $0.5100  (range $0.480 – $0.530)
- Entry qty (median):    49.02 shares
- Notional (qty×price):  $25.00 per trade
- Hedged trades:         0 / 190 (0.0%)

## Shadow performance — top-line

| Slice | n | wins | hit% | hedged | total PnL | mean PnL | ROI/trade | avg entry px | range |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| ALL V3 sleeves | 190 | 96 | 50.5% | 0 | $-104.91 | $-0.5522 | -2.00% | $0.511 | 2026-04-30→2026-05-05 |
| V3 base (no variant) | 73 | 38 | 52.1% | 0 | $+8.98 | $+0.1230 | +0.72% | $0.512 | 2026-04-30→2026-05-05 |
| V3 variants (v3_1/2/3) | 117 | 58 | 49.6% | 0 | $-113.89 | $-0.9735 | -3.70% | $0.510 | 2026-05-02→2026-05-05 |
| BTC only | 127 | 72 | 56.7% | 0 | $+309.07 | $+2.4336 | +9.76% | $0.511 | 2026-04-30→2026-05-05 |
| BTC 5m | 127 | 72 | 56.7% | 0 | $+309.07 | $+2.4336 | +9.76% | $0.511 | 2026-04-30→2026-05-05 |
| ETH only | 22 | 11 | 50.0% | 0 | $-23.90 | $-1.0865 | -4.92% | $0.519 | 2026-05-02→2026-05-04 |
| ETH 5m | 22 | 11 | 50.0% | 0 | $-23.90 | $-1.0865 | -4.92% | $0.519 | 2026-05-02→2026-05-04 |
| SOL only | 41 | 13 | 31.7% | 0 | $-390.07 | $-9.5140 | -36.87% | $0.505 | 2026-05-02→2026-05-05 |
| SOL 5m | 41 | 13 | 31.7% | 0 | $-390.07 | $-9.5140 | -36.87% | $0.505 | 2026-05-02→2026-05-05 |

### Per-sleeve breakdown

| Sleeve | n | hit% | total PnL | mean PnL | ROI/trade | hedged |
|---|---:|---:|---:|---:|---:|---:|
| poly_updown_btc_5m_v3 | 56 | 57.1% | $+146.50 | $+2.6161 | +10.51% | 0 |
| poly_updown_btc_5m_v3_1 | 36 | 52.8% | $+20.09 | $+0.5580 | +2.27% | 0 |
| poly_updown_btc_5m_v3_2 | 27 | 66.7% | $+196.86 | $+7.2910 | +29.16% | 0 |
| poly_updown_btc_5m_v3_3 | 8 | 37.5% | $-54.38 | $-6.7978 | -27.19% | 0 |
| poly_updown_eth_5m_v3 | 9 | 44.4% | $-33.75 | $-3.7505 | -15.34% | 0 |
| poly_updown_eth_5m_v3_1 | 6 | 50.0% | $-6.75 | $-1.1249 | -5.37% | 0 |
| poly_updown_eth_5m_v3_2 | 7 | 57.1% | $+16.60 | $+2.3714 | +8.85% | 0 |
| poly_updown_sol_5m_v3 | 8 | 25.0% | $-103.77 | $-12.9710 | -49.74% | 0 |
| poly_updown_sol_5m_v3_1 | 8 | 37.5% | $-51.28 | $-6.4094 | -24.66% | 0 |
| poly_updown_sol_5m_v3_2 | 16 | 31.2% | $-158.31 | $-9.8941 | -38.69% | 0 |
| poly_updown_sol_5m_v3_3 | 9 | 33.3% | $-76.73 | $-8.5250 | -33.04% | 0 |

## Backtest comparison

Backtest numbers from `V3_BTC_UNION_REALFILLS.md` ($25 stake, real book, hedge-hold rev_bp=5, 2% fee):

| Source | Period | n | hit% | total PnL | mean PnL | ROI/trade |
|---|---|---:|---:|---:|---:|---:|
| Backtest V3_alone — ALL | Apr 22 → Apr 29 | 322 | 61.5% | $+641.97 | $+1.9937 | +11.51% |
| Backtest V3_alone — 5m | Apr 22 → Apr 29 | 238 | 64.3% | $+449.12 | $+1.8870 | +9.73% |
| Backtest V3_alone — 15m | Apr 22 → Apr 29 | 84 | 53.6% | $+192.86 | $+2.2959 | +16.53% |
| Backtest BTC_only — ALL | Apr 22 → May 4 | 454 | 85.5% | $+4931.64 | $+10.8600 | +42.65% |
| **Shadow ALL V3** | Apr 30 → May 5 | 190 | 50.5% | $-104.91 | $-0.5522 | -2.00% |

## Reconciliation

**Same engine, different periods + slightly different gate**:

- Backtest **V3_alone** uses cached `prob_stack` from `btc_features_v3.csv` (Apr 22 → Apr 29) at threshold ≥ 0.65, BTC only.
- Shadow **V3 family** uses live `prob_stack` from BarEngine across BTC + ETH + SOL on 5m sleeves, with multiple thresholds (v3_1/2/3 = sniper variants at higher quantile q90/q80).
- Backtest BTC ALL: hit 61.5%, mean $+1.9937/trade
- Shadow ALL V3:  hit 50.5%, mean $-0.5522/trade

**Hit rate delta**: -11.0pp (shadow vs backtest BTC-only)
**Mean PnL delta**: $-2.5459/trade

→ **Shadow UNDERPERFORMS backtest** by $2.55/trade — forward-walk degradation; investigate before scaling.

### BTC-5m subset (cleanest apples-to-apples)

- **Backtest V3_alone — 5m**: n=238, hit=64.3%, mean $+1.8870/trade
- **Shadow BTC 5m**:           n=127, hit=56.7%, mean $+2.4336/trade
- **Hit Δ**: -7.6pp   **Mean PnL Δ**: $+0.5466

## Vs the BTC_only candidate (backtest only — not yet deployed)

- Backtest **BTC_only** (top-10% \|btc_ret_2m\|, t+120s entry): n=454, hit=85.5%, mean $+10.8600/trade, ROI +42.65%/trade
- Shadow **V3 family** total: n=190, hit=50.5%, mean $-0.5522/trade, ROI -2.00%/trade
- BTC_only outperforms V3 by **$1086.0×** per-trade in mean PnL.

**Recommendation**: deploy BTC_only sleeve (top-10% \|btc_ret_2m\|, sign = direction, entry @ bucket 12) in shadow mode alongside V3 to forward-walk validate the backtest result before scaling.
