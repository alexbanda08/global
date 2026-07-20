# TV RUST AGENT SPEC — v3.2 "CHEAP-FLOW" 15m LADDER (b945-tape derived) — 2 new PAPER sleeves
**2026-07-20 · TVRUST only · vps_ireland · ALL PAPER $0 · rides along the next engine deploy (no dedicated restart).**

## 0. Ground rules (unchanged)
- `poly_ladder_btc_15m_v3`, `btc_5m_v3` + all existing v3.1 variants stay **BYTE-FROZEN** — they are the A/B baseline and the go-live mid-gate.
- New sleeves MUST share the base sleeves' racer/book feed (a variant on its own connection confounds the A/B with feed quality).
- Live-path punch list (real-order fire-drill + $2 dry-arm) remains PRIORITY 1 if not yet delivered.

## 1. Why (evidence — operator fill-by-fill audit of wallet 0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68, Jul 16–17 btc-15m tape, 1,453 scored fills, outcomes from our own DB)
His 15m engine per price band (PnL as % of notional): **0.01–0.40 → +38..+108%** ($1,886 notional, +$1,093 = his ENTIRE profit); 0.40–0.50 → **−25%**; 0.50–0.60 → +10%; 0.60–0.85 → −4%; **>0.85 → −13%** ($8.9k notional, −$686). He nets only +$3.87/slug because the favorite-band bleed eats the cheap-rung harvest. Mechanics: median **19 distinct 1¢ rungs filled per slug**, **flat ~30-share clips at every rung**, ~3s inter-fill cadence (continuous re-quote), residual ≈22% of book landing on the WINNING side 71% (price-following drift). Our current 15m v3: pair_frac 0.058, 6 sh/slug, $0.09/window — our conservative depth-2 quoting misses essentially all of this flow.
**Thesis: copy his rung density + flat clips + both-sided cheap-band quoting; amputate the 0.40–0.50 coin-flip band and everything >0.62. On his own tape that config is ≈ +$1,3xx/2d where his full config made +$147.**

## 2. New paper sleeves (BTC 15m; clone to ETH 15m only if the ladder loop already supports it for free)

### Variant A — `poly_ladder_btc_15m_v32_cheap`
Identical framework to 15m v3 (same feed, same window lifecycle, same settle logic, same telemetry schema) EXCEPT the quoting book:
- **Rung grid: GTC bids at EVERY 1¢ from 0.02 to 0.40, BOTH tokens simultaneously**, flat clip per rung (see caps). No quoting above 0.40. No 0.40–0.50 fills possible by construction.
- **Re-quote/price-follow cadence ≤5s** (his is ~3s): as the book moves, keep the full 0.02–0.40 grid live on whichever side is currently cheap; rungs on the expensive side simply sit deep (that's fine — they harvest the reversal).
- **Flat clip**: `TV_LADDER_V32_CLIP_SH` default sized so worst-case one-side full-grid fill respects the window cap (below). His flat-30sh at our cap ⇒ ~1–2 sh/rung; that's acceptable for paper signal.
- Keep OUR risk layer (this is where we beat him): **T−45s backstop flatten + rcg residual band flatten (0.30–0.45 as tuned) + daily circuit breaker**. His tape shows raw hold-to-resolution residual pain; we keep the amputation.

### Variant B — `poly_ladder_btc_15m_v32_cheapmid`
Variant A **plus** a second band **0.50–0.62** (every 1¢, same flat clip). Nothing in 0.40–0.50, nothing >0.62 — captures his +10% mid band while still excluding both bleed zones. This is the only A-vs-B question: does the mid band add or dilute.

### Caps / env (paper, but keep live-shaped)
- `TV_LADDER_V32_MAX_PER_WINDOW_USD=12` per side (same as base), `TV_LADDER_V32_CLIP_SH` (default from cap), `TV_LADDER_V32_BAND_A=0.02:0.40`, `TV_LADDER_V32_BAND_B=0.50:0.62` (variant B only), `TV_LADDER_V32_REQUOTE_S=5`.

## 3. Telemetry (must-have for the verdict)
Same `ladder_summary` schema PLUS per-window: `fills_per_band` (A/B band share counts + vwap), `rungs_filled_n`, `pair_frac`, and standard `total_net_usd/paired_pnl_locked_usd/residual_pnl_usd`. Money/share floats rounded ≤6 dp at serialization (the Jul-16 crash rule).

## 4. Pre-registered expectations (judge against these, not vibes)
1. **Fill volume**: v32_cheap fills ≥5× base 15m v3 shares/window (base is 6 sh/slug; his tape says the flow exists).
2. **Band sanity**: zero fills outside configured bands (construction check).
3. **Primary**: v32_cheap beats `btc_15m_v3` paired per-window (same slugs) with **t ≥ 2 within ~5 days** (≈480 15m windows). Secondary: per-band PnL sign matches his tape (≤0.40 band positive).
4. **A vs B**: keep whichever wins paired t after the same window; kill the loser.
5. If v32_cheap does NOT beat base → write the negative result, do not tune-and-rerun bands post-hoc (that's how overfits are born); bands are frozen as specced.

## 5. Also in this deploy (small, from the same audit)
- **Kill candidates**: `poly_ladder_btc_5m_v31_d4` (paired t=−2.13 vs base, significantly worse) — stop the sleeve, note in ledger. BTC-15m sniper pair (`poly_sniper_v5_btc_15m_ema50_ema800_off600_down` + kalshi twin H) — ~−$90/75tr since Jul 14, disable per fleet-audit rules.
- **Trigger-counter report** for `eth_5m_v31_rcg` and `btc_15m_v4_coc`: both show EXACT zero paired delta vs base (t=0.00) — report `rcg_flattened_sh` / `coc_triggers` totals; if zero, they're inert (mis-gated or genuinely never trigger) and should be killed to free slots.

## 6. Reporting
Per-sleeve first-24h snapshot (fills/window, band histogram, pair_frac, net), then the day-5 paired verdict vs base. Flag any deviation from this spec BEFORE implementing it. Commit/push as you go.
