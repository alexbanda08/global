# TV AGENT SPEC — `sum_pair_osc_harvest` sleeve (signal-gated sum-pair, oscillation-harvest)
**2026-06-14 · $0 shadow first · the first validated sum-pair edge of the campaign**

Implement a new sleeve that harvests the Binance→Polymarket lag on BOTH sides of a crypto Up/Down market,
accumulating each leg at its own lag-dip so the time-averaged pair cost is < $1, then holding the matched
pair to resolution. **This REUSES the deployed lag-scalp's signal + book-walk + +60s-exit machinery** — it
is NOT the b945 ladder build; it's a lighter extension of the existing scalp sleeve. Validated offline in
`SUMPAIR_SIGNAL_GATED_2026_06_13.md` (engine `strategy_lab/directional/_sumpair_signal_oscillation_harvest.py`).

---

## 0. Why this sleeve (the proven part)
The deployed lag-scalp already profits by buying the lagging Poly leg cheap (Binance moved, book hasn't
repriced) and SELLING at +60s. This sleeve instead **accumulates both legs on their respective lag-dips and
HOLDS the matched pair to resolution** — locking a sub-$1 pair. Offline it:
- achieves paired cost **median 0.73, 92.6% sub-1** (vs the ~1.01 overround a same-instant pair always pays);
- **survives the markout test** (the cheap ask we fill RISES +8¢/30s — genuine lag, not the sub-100ms revert
  that killed the simultaneous taker arb);
- **beats the deployed +60s scalp** on the same fires (+1.95/slug paired diff, CI excl 0);
- survives bar-END causality, 85ms latency, chainlink settlement.
**Deployable floor = +$0.40/slug OOS (1-clip, scalp-residual ARM B, CI [+0.26,+0.55]); real-depth multi-clip
up to +$1.77 (unlim) — depth test DONE 2026-06-16, see §3b.** **BTC/ETH 5m ONLY** (SOL straddles 0; 15m straddles 0).

## 1. The strategy (exact validated config)
- **Markets:** BTC/ETH **5m** Up/Down only. (SOL straddles zero on the depth-realism per-coin ARM B — §3b — exclude; 15m straddles zero — exclude.)
- **Signal (REUSE the deployed scalp lag signal, causal):** at each decision tick (rolling every 5s from
  slot_start+5s to slot_end−65s), compute Binance **bar-END** return over a 5s lookback on `klines_1s`
  (`asof_on(ends, close, t)` with `ends = bar_start+1e6`; **NEVER bar-START — that's the look-ahead bug**).
  If `|ret|·1e4 ≥ 3 bp`: the side Binance just moved toward is lag-cheap (ret>0 → buy **Up**; ret<0 → buy
  **Down**) — the same lagging-side the scalp buys.
- **Entry:** book-walk a **$5 clip** on that side's ask at decision+**85ms**; require entry vwap **`ev < 0.55`**
  (the validated gate). Fill ≤ real available depth (do NOT assume infinite depth).
- **Accumulate** both sides across the window as each side's signal fires, up to **`MAX_CLIPS` per side**
  (config; default to the depth-test result — conservative start = 1–3 per side; floor result is 1).
- **Settlement:** the **matched pair** `min(sh_up, sh_dn)` is HELD to chainlink resolution (winner leg
  redeems $1). **Residual (excess on the heavier side): scalp-EXIT at +60s** (sell on book, like the deployed
  scalp) — do NOT hold the residual directionally (it's a −$1.19/slug drag if held).
- **Fee:** winner-only `0.07·p·(1−p)` on the winning leg, $0 on loser, fee-free redeem (matched-pair
  settlement = `q·[(1−p_w)(1−0.07·p_w) − p_l]`).
- **No stops** on the matched pair (self-hedged). >0.85 ev already excluded by the `ev<0.55` gate.

## 2. What's NEW vs the deployed scalp (the only added machinery)
| Deployed lag-scalp | this sleeve |
|---|---|
| fires once per window (one side) | fires repeatedly, BOTH sides, on each side's lag-dip |
| sells the single leg at +60s | HOLDS the matched pair to resolution; scalp-exits only the residual |
| directional repricing edge | market-neutral sum<1 capture + residual scalp |
Reused as-is: the Binance bar-END lag signal, the book-walk entry fill, the +60s sell exit, chainlink
settlement, the dedup/event logging.

## 3. Config (env / sleeve params)
```
TV_SUMPAIR_OSC_ENABLED=true
TV_SUMPAIR_OSC_COINS=BTC,ETH        # SOL dropped 2026-06-16 (depth-realism per-coin ARM B straddles 0)
TV_SUMPAIR_OSC_TF=5m
TV_SUMPAIR_OSC_THR_BPS=3
TV_SUMPAIR_OSC_EV_GATE=0.55
TV_SUMPAIR_OSC_CLIP_USD=5
TV_SUMPAIR_OSC_MAX_CLIPS_PER_SIDE=2   # SET 2026-06-15 from _sumpair_v2_upside.py: real depth supports median 2 clips/side; net rises to ~+$1.7 at 3 clips BUT it's tail-driven (median −$5, ~72% single-leg). Start 1 (floor +$0.52, significant), raise to 2-3 ONLY once residual-exit proven to lift the median.
TV_SUMPAIR_OSC_DECISION_STEP_S=5
TV_SUMPAIR_OSC_LOOKBACK_S=5
TV_SUMPAIR_OSC_RESIDUAL_EXIT_S=60     # scalp-exit excess leg; do NOT hold residual
TV_SUMPAIR_OSC_LIVE_ENABLED=false     # false = $0 shadow (paper)
```

## 3b. UPSIDE / DEPTH RESULT (2026-06-15, `_sumpair_v2_upside.py` → `_results/sumpair_v2_upside_2026_06_15.parquet`)
Max-clip sweep (real-25-level-depth fill, OOS, THR=3, 1/10 sample): net/slug = +0.53 (1 clip) → +1.16 (2) →
+1.70 (3) → +2.97 (∞). **Real depth supports median 2 clips/side (p25=1, p75=4); depth_short=0 (book carries
the $5 clips — the cap is a choice, not a depth limit).** ⚠️ **The mean rises with clips but the MEDIAN is
−$5.00 and ~72% of fired slugs are SINGLE-LEG losers** (only ~28% both-fill) — the positive mean is tail-driven
by the both-filled matched pairs. This run HOLDS the residual (pessimistic); the −$5 median = unpaired clips
held to $0. **The residual-scalp-exit (§1, sell the unpaired leg at +60s) is the fix for the negative median
and is NOT yet backtested — measure it live in Stage 0 (log hold-residual vs scalp-exit-residual side by side).**
Deployable read: start MAX_CLIPS=1 (floor +$0.52, full-run CI [+0.36,+0.68] significant); raise to 2-3 (≈+$1.2-1.7
mean) ONLY after the live shadow shows residual-exit lifts the median and the matched-pair locked PnL holds.

## 3c. DEPTH-REALISM + RESIDUAL-EXIT RESULT (2026-06-16, `_sumpair_v2_depth_realism.py`, full OOS, `SUMPAIR_V2_DEPTH_REALISM_2026_06_14.md`)
**The §3b "residual-exit NOT yet backtested" open question is now ANSWERED offline.** Full 25-level ladder walk
(per-level carry, no DEEP) + both ARM A (hold residual) and ARM B (scalp residual @+60s):
- **Real depth = ~9 clips/snapshot/side** → multi-clip is NOT a refill artifact (engine fires only ~2.4/side).
  ARM A net/slug 1→+0.64, 2→+1.09, 4→+1.75, ∞→+2.45 (matches the 06-15 upside HELD-residual curve).
- **Scalp-residual (ARM B) is the DEPLOYABLE form — it FIXES the −$5 median.** 74% of fires are single-leg;
  HOLD = higher mean but **median −$5, 36-38% win = untradeable**; SCALP the unmatched leg @+60s → **median
  −$0.35, 44% win**, mean +0.40 (1-clip, CI [+0.26,+0.55]) / +1.77 (unlim). **So §1's "scalp the residual"
  choice is now offline-confirmed, not just hypothesized.**
- **Per-coin ARM B:** BTC +0.91(1)/+3.32(unlim), ETH +0.41/+2.23 (both CI>0); **SOL +0.12/+0.60 straddles 0 → DROPPED.**
- Markout +1.9/+3.7/+2.5¢ (lag real; +30s CI straddles 0, tail-driven).
- **ONE open question remains, live-only:** inter-fire liquidity regeneration (does the lagging quote refill
  after you lift it). The 1-clip +0.40 floor needs no such assumption; the multi-clip +1.77 does. → Stage-0
  shadow still measures it; keep MAX_CLIPS=1 until live confirms regeneration.

## 4. Staged rollout
- **Stage 0 — $0 shadow (paper):** real lag signal + real book-walk paper fills, both sides, accumulate, settle
  to chainlink. Log everything (§5). ALSO log the virtual residual-scalp-exit vs hold-residual so we measure
  the refinement live. Run BTC/ETH/SOL 5m.
- **Stage 1 — small capital** ($5 clips, MAX_CLIPS=1 first) only after Stage 0 shows ≥200 fires with live
  paircost median <1, matched-pair locked PnL CI>0, on the live wallet (NOT the backtest — the OOS window is
  the only honest forward test).
- **Stage 2 — raise MAX_CLIPS** toward the depth-test number, verify net scales, then scale capital in steps.
- **Promotion gate (pre-registered):** live paircost median ≤ 0.98 AND matched-pair net/slug CI>0 AND
  residual-exit ≥ hold-residual AND ≥200 fires / ≥4wk. Else file the sleeve dead.

## 5. Telemetry (headline metrics to watch)
Per fired slug, log to `trading.events` (reuse the scalp event schema + new kind `sumpair_osc`):
`{slug, coin, tf, nclip_up, nclip_dn, ev_up, ev_dn, matched_sh, paircost (=ev_up+ev_dn), locked_pnl,
residual_sh, residual_exit_pnl, residual_hold_pnl(virtual), net_pnl, both_filled, clips_per_side,
binance_ret_at_fire}`. **paircost (<1?) and matched-pair locked_pnl are THE numbers.** Per-window markout
of each fill (does the cheap ask rise after fill — the live confirmation of the lag).

## 6. Guardrails / known traps (do NOT repeat)
- **Bar-END signal only** (bar-START = look-ahead; killed prior scalp drivers).
- **85ms latency** on every fill (detect-instant fills made the dead taker-arb look positive).
- **Real depth** — do NOT assume size==0 → infinite (the V2 headline was 4× inflated by that; the deployable
  floor is the depth-honest number).
- **Chainlink settlement** on ALL gated slugs (never engine-redeem = the censoring trap).
- **BTC/ETH 5m only** (SOL + 15m straddle 0). **Hold matched pair only; scalp-exit residual** (don't hold residual — depth-realism §3c: scalp-exit median −$0.35 vs hold −$5).
- Judge by the **live wallet CI**, not the backtest (deployed-scalp OOS window is burned).

## 7. Files / provenance
Engine: `strategy_lab/directional/_sumpair_signal_oscillation_harvest.py`; signal/fill: `scalp_fill_lib_2026_06_10.py`
+ `scalp_causal_asof_oneshot_2026_06_12.py`; verdict + adversarial audit: `SUMPAIR_SIGNAL_GATED_2026_06_13.md`;
upside/depth: `_sumpair_v2_upside.py` → `_results/sumpair_v2_upside_2026_06_15.parquet`;
**depth-realism + residual-exit (the deployable verdict): `_sumpair_v2_depth_realism.py` →
`_results/sumpair_v2_depth_realism_2026_06_14.parquet` + `SUMPAIR_V2_DEPTH_REALISM_2026_06_14.md` (§3c).**
