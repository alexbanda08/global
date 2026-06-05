# TV Agent Spec — btc_15m_ema50_ema800_off600_down **V10** (entry-band gate) — 2026-06-01

_One small, high-value change to a proven, faithful strategy: add an entry-price band gate._

## OPERATOR DEPLOYMENT DECISION (2026-06-01) — band `[0.15, 0.93]`, $1/fire
- **Band = `0.15 ≤ entry_vwap < 0.93`** (operator chose 0.93 cap; ≈+$231 full-period, between the 0.92/+$230 and 0.95/+$233 runs). Stake **$1/fire** (EV & MaxDD scale ÷5 from the $5 backtest — still net-positive).
- **LIVE on Kalshi** = V10 (with band). **LIVE on Polymarket** = parent (no band) keeps running. **+ a Polymarket SHADOW sleeve** = V10 (with band).
- ⚠ **A/B validity:** the *clean* test of the band is **same-venue**: Polymarket-parent (live) vs Polymarket-V10 (shadow) — both see identical books, so any difference IS the band. The **Kalshi-live-V10 vs Poly-live-parent** comparison is **cross-venue** (different liquidity / fees / crowd / prices) → use it for "does V10 make money live on Kalshi," NOT to measure the band's isolated lift. Ideally also run a Kalshi parent (shadow) for a same-venue Kalshi A/B.
- ⚠ **Kalshi ≠ Polymarket economics:** the +$231 backtest used Polymarket L25 fills + the 0.07-curve fee. Kalshi has its own fee schedule + liquidity → expect different absolute numbers; the *edge structure* (skip both price extremes) should still hold, but re-baseline expectations.
- Log skipped (out-of-band) fires as audit events so the A/B can compare taken-vs-skipped.

## Change
Clone `poly_sniper_v5_btc_15m_ema50_ema800_off600_down` (gates `g_dir_down + g_tr_above_ema50(BTC) + g_tr_above_ema800(BTC)`, offset 600, DOWN, hold-to-resolve, $5) → **`..._V10`**, adding ONE gate:

- **`g_entry_vwap_band(0.15, 0.95)`** — only fire when the DOWN-token fill vwap is in **[0.15, 0.95]**.
  - Skip `entry < 0.15` (deepest-lottery contrarian bets: −EV over the full period, WR≈implied, just high-variance noise — incl. the 0.06/0.03 fires).
  - Skip `entry ≥ 0.95` (no-upside favorites: win pays ~+$0.10, loss costs −$5 → net −EV + tail risk; "nothing of profit").

Everything else identical. The gate is evaluated at fire time on the same `fill_vwap` already used for the L25 walk (the band check happens after the book walk produces the entry vwap, before placing — if vwap ∉ band, skip the fire). If a `g_entry_vwap_in_band`-style gate already exists in the gate library, parameterize it to [0.15, 0.95]; otherwise add a thin band check.

## Sleeves to create (4)
| new | clones |
|---|---|
| `poly_sniper_v5_btc_15m_ema50_ema800_off600_down_V10` | `..._down` |
| `poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H_V10` | `..._down_H` (hedge variant, same band) |
| `kalshi_sniper_btc_15m_ema50_ema800_off600_down_V10` | kalshi twin |
| `kalshi_sniper_btc_15m_ema50_ema800_off600_down_H_V10` | kalshi `_H` twin |

Paper/shadow mode, $5. Keep the 4 parents running for A/B.

## Backtest basis (all local data, Apr 24 → May 26, 0.07-curve, flat $5)

| config | n | WR% | total $ | $/tr |
|---|--:|--:|--:|--:|
| parent (no band) | 917 | 76.3 | +176 | +0.19 |
| floor only `≥0.15` | 881 | 79.2 | +229 | +0.26 |
| **V10 band [0.15, 0.95]** | 692 | 74.3 | **+233** | **+0.34** |

+32% total / +78% per-trade vs parent. Positive every full week (one partial-week dip). The band removes the two −EV tails (deep-lottery + no-upside favorites) and the worst tail-risk fires.

## Why (the edge map)
DOWN bet → `entry_vwap` = market-implied P(DOWN); edge = realized WR − implied. Full-period per-bucket edge:
- `<0.15`: **−2.3pp** (−$53) — not an edge; the live window's +$110 was 5-trade luck.
- `0.15-0.30`: +6.8pp (+$65) ✅
- `0.50-0.70`: **+10pp (+$110)** ⭐ the workhorse
- `0.70-0.95`: +2-4pp (+$56) ✅ modest
- `≥0.95`: **−0.2pp (−$4)** — dead weight + tail risk.

The genuine alpha is the **0.15-0.95 contrarian-to-modest-favorite zone**, where the EMA50/EMA800 down-trend beats the Polymarket crowd's price. The extremes are fairly priced (no edge) and only add variance.

## Acceptance (7-day A/B)
- V10 fires only when 0.15 ≤ entry_vwap < 0.95 (verify in events).
- V10 fire-rate ≈ 75% of parent (≈692/917).
- V10 ≥ parent on **$/tr** AND Sharpe/Calmar live. If yes → promote V10, deprecate parent. (The band is the rare both-ends-confirmed optimization — high confidence.)

## Notes
- Do NOT add stop-loss/hedge — hold-to-resolve is optimal here (prior work; HEDGE_LATE hurts this winner).
- High variance remains (cheap wins pay ~16×, std ~8 on $5) — size for it.
- This `_V10` band tweak supersedes the earlier floor-only suggestion in `EMA_DOWN_DEEPDIVE_2026_06_01.md` §5 (the cap adds the high-end trim).

Source: `EMA_DOWN_DEEPDIVE_2026_06_01.md`, scripts `23/24/25_ema_down_*.py`, substrate `sniper_btc15m_v8_gated.parquet`.
