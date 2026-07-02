# HL Sleeve Cards

**Built:** 2026-07-02T11:05:17.308708+00:00
**Mode:** shadow_paper | **Venue:** hyperliquid_perp
**Fleet:** 9 V52 sleeves + 1 XSM basket

## V52 fleet (9 sleeves)

| Card | Coin | TF | Family | Gate | Weight | Val Sharpe | 2026 Sh | Live state | Fires | Last fire |
|---|---|---|---|---|---:|---:|---:|---|---:|---|
| STF_BTC NEW | BTC | 4h | trend (SuperTrend) | FUND_Z<2 | 12% | 1.0 | 3.61 | FLAT | 3 | 2026-05-27T16:00 |
| CCI_ETH | ETH | 4h | mean-reversion (CCI) | FUND_Z<2 | 12% | 1.411 | 0.42 | FLAT | 6 | 2026-06-30T08:00 |
| STF_SOL | SOL | 4h | trend (SuperTrend) | FUND_Z<2 | 12% | 1.148 | -0.717 | FLAT | 7 | 2026-06-23T04:00 |
| STF_AVAX | AVAX | 4h | trend (SuperTrend) | FUND_Z<2 | 12% | 2.3 | 0.422 | FLAT | 5 | 2026-06-25T00:00 |
| LATBB_AVAX | AVAX | 4h | range-fade (Bollinger) | FUND_Z<2 | 12% | 1.59 | 0.148 | FLAT | 5 | 2026-06-24T08:00 |
| MFI_SOL | SOL | 4h | volume (MFI) | ATR_NOTOPVOL | 10% | 1.12 | -0.083 | OPEN | 11 | 2026-06-24T00:00 |
| VP_LINK | LINK | 4h | volume (Volume-Profile) | ATR_NOTOPVOL | 10% | 1.634 | -1.12 | FLAT | 11 | 2026-06-16T20:00 |
| SVD_AVAX | AVAX | 4h | volume (Signed-Vol-Divergence) | ATR_NOTOPVOL | 10% | 0.538 | 2.072 | FLAT | 5 | 2026-06-19T08:00 |
| MFI_ETH | ETH | 4h | volume (MFI) | ATR_NOTOPVOL | 10% | 0.683 | 0.975 | OPEN | 11 | 2026-06-23T08:00 |

## XSM basket

- **V24-XSM** — Long top-4 of 9 by 14d momentum, weekly rebalance
- Filter: **FLAT** (breadth 2/9, BTC>100dMA=False, 50dMA_rising=False)
- Current basket: `FLAT`
- Live allocation: **0%** (Separate book. 0% live allocation until more coins join HL (only 5/9 HL-tradeable). Defensive by design: filter passed only ~4.5% of 2026 bars. Relaxations all hurt.)

## Per-card files

One JSON per sleeve in `shadow_v52/cards/`:
- `cards/v52_stf_btc.json` — STF_BTC (BTC)
- `cards/v52_cci_eth.json` — CCI_ETH (ETH)
- `cards/v52_stf_sol.json` — STF_SOL (SOL)
- `cards/v52_stf_avax.json` — STF_AVAX (AVAX)
- `cards/v52_latbb_avax.json` — LATBB_AVAX (AVAX)
- `cards/v52_mfi_sol.json` — MFI_SOL (SOL)
- `cards/v52_vp_link.json` — VP_LINK (LINK)
- `cards/v52_svd_avax.json` — SVD_AVAX (AVAX)
- `cards/v52_mfi_eth.json` — MFI_ETH (ETH)
- `cards/xsm_v24_multifilter.json` — V24-XSM (9-coin basket)