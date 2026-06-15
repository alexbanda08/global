# ETH 5m `l_ema50_hurst_grandparent_V10` — VPS3 shadow vs Ireland live (last 5 days, 2026-06-08)

Sleeve: `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10`. VPS3 = shadow/paper engine;
Ireland = live-mirror engine (`_V10_LIVE`, real $, `TV_POLY_SNIPER_V5_LIVE_ENABLED=true`,
allowlisted). Window ≈ Jun 4 → Jun 9. ETH-5m slugs only.
Sources: VPS3 `/var/log/.../sniper_v5/*.jsonl`; Ireland `trading.events`.

## Comprehensive comparison

| metric | VPS3 shadow | Ireland LIVE |
|---|--:|--:|
| placed (5d) | **299** | **111** |
| resolved | 286 | 111 |
| WR | 66.1% | 64.0% |
| total PnL | **+$62.4** | **+$1.1** |
| mean $/tr | **+$0.218** | **+$0.010** |
| avg entry vwap | 0.628 | 0.629 |

**Live is ~breakeven (+$1.1 / +$0.010/tr) while shadow shows +$62 / +$0.218/tr.** Same WR
(~65%), same entry price — the gap is almost entirely **fire COUNT** (shadow places 2.7× more).

## Slug overlap
| | n |
|---|--:|
| placed by BOTH hosts | 100 |
| **VPS3 placed, Ireland live did NOT** | **199** |
| Ireland live placed, VPS3 did not | 11 |

## ⭐ Why Ireland live did NOT fire the 199 VPS3-shadow fires
Slug-set algebra against Ireland's own paper-signal + live-signal logs:

| reason | n | share |
|---|--:|--:|
| **(B) Live execution-layer reject** (Ireland's gates passed but live didn't place) | **112** | **56%** |
|   ↳ live cross-token **spread gate** rejected the wide book (paper-signaled) | 108 | |
|   ↳ live-path signaled but fill/qty failed | 4 | |
| **(A) Cross-host feed/gate divergence** (Ireland never even signaled) | **87** | **44%** |

### (B) The dominant cause — live spread gate on WIDE books
The 199 VPS3-only fires had **cross_spread median 0.282, p90 0.314** — i.e. UP+DOWN vwaps sum
to ~1.28, books are 28% wide. VPS3 shadow's spread filter is the **same-token bid-ask** check
(looser), so it places; Ireland live uses the **cross-token arb-consistency** spread gate
(~0.02), which correctly rejects these. **These fires are not genuinely executable live** —
you can't fill at the shadow's vwap on a 28%-wide book. This is exactly the documented
behaviour (CLAUDE.md: "live's cross-token check fails 99%+ on real books where UP+DOWN ≈ 1.30").

### (A) Cross-host divergence — Ireland never signaled (87)
Each host computes the gate inputs (`ema50`, `hurst_60`, `grandparent` 1h-slope) from its OWN
Binance feed. At decision boundaries the two feeds flip the gate result, so Ireland's gates
fail where VPS3's pass → no signal on Ireland. (The 06-03 parity proof: feeds are bit-identical
97.9% of the time; the ~2% boundary flips + rolling-threshold state drive this.)

## 🔑 The key insight: shadow PnL is OVERSTATED by un-fillable fires
VPS3 "earned" **+$77.3 (mean +$0.411/tr, 129/188 wins)** on the 199 fires Ireland live skipped
— but those are the **wide-book (cross_spread 0.28) fires that can't actually fill live**. Strip
them and live is the truth: **~breakeven**. The shadow's +$62 is mostly paper profit on books
no one could trade. **Judge this sleeve by the LIVE wallet (+$1.1, breakeven), not shadow (+$62).**

## Takeaways
1. Live ≈ **breakeven** over 111 real fires (5d) — NOT the +$62 shadow implies.
2. 56% of the shadow's extra fires die on the **live cross-token spread gate** (wide books);
   44% on **per-host feed divergence**. The spread gate is the bigger driver and is *correct*
   (those fires aren't executable).
3. To make shadow predictive: replace the shadow same-token bid-ask spread filter with the
   live **cross-token** spread definition (the standing TV-parity fix).

Scripts: `migration_2026_06_08/{v10_vps3_dump.py, v10_parity_analyze.py}`; data CSVs alongside.
