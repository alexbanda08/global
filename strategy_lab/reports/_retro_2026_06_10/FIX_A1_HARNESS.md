# FIX A1 — Scalp exit-fill harness correction (2026-06-10)

Two confirmed bugs fixed in the `scalp_oos_bbo_2026_06_05.py` family. Originals untouched; corrected
runners carry the `_fixed_2026_06_10.py` suffix and share one new module.

## The bugs (original code, line ~82 of every sibling)

```python
sell = bid[jx] if (0 <= jx < len(ts) and np.isfinite(bid[jx])) else (1.0 if won else 0.0)
```

1. **OUTCOME-LEAK EXIT FALLBACK.** When no finite bid exists at exit time, the RESOLVED OUTCOME
   (`1.0 if won else 0.0`) is used as a mid-window SELL PRICE — lookahead. Also: no staleness check, so a
   bid from minutes ago is silently carried forward via asof.
2. **NO SELL-SIZE CAP.** Entry is capped at `best_ask_size`, but the exit sold the FULL position at
   `best_bid` regardless of `best_bid_size`. On the BBO tape ~49% of rows have `best_bid_size==0` (bid
   price finite, depth zero) → the old model sold into nonexistent depth.

## Corrected canonical exit model (`scalp_fill_lib_2026_06_10.py`)

- **Entry (unchanged):** ask + ask_size asof `t_fire+85ms`; `shares = min(STAKE/ask, ask_size)`; skip if
  `shares*ask < STAKE*0.5` or `spread > 0.05`.
- **Exit at `ext = min(t_fire+60s, slot_end)`:** `jx = last index with ts<=ext`. Quote is VALID only if
  `jx>=entry_index`, `bid[jx]` finite, AND `(ext - ts[jx]) <= 120_000_000us` (staleness guard).
  - **VALID:** `sold_sh = min(shares, best_bid_size[jx])`; sell `sold_sh` at `bid[jx]` with the 0.015
    round-trip fee on the sold notional. Remainder `rem = shares - sold_sh` is **HELD TO RESOLUTION**:
    `rem*(1-ev)*(1-0.07*ev)` if won else `-rem*ev` (winner-only fee — faithful to live: the engine holds
    what it cannot sell, and valuing a held-to-expiry position at settlement is NOT lookahead).
  - **NOT VALID:** the WHOLE position is held to resolution (same valuation), `held_full=True`.
- **Per fire tracked:** `pnl` (combined), `frac_held` (`rem/shares` or 1.0), `held_full`.
- **Dual bound:** every results cell prints BOTH (a) ALL fires and (b) CLEAN subset (`frac_held==0`).

Library API: `exit_fill(...)`, `entry_fill(...)`, `held_value(...)`, `bpnl(...)`, `boot(v)`, `cell(v)`.
`pnl_sold` fee term: `(sell-ev)*sh - 0.015*sh*(ev*(1-ev)+sell*(1-sell))` (unchanged from originals).

## Files created

- `strategy_lab/directional/scalp_fill_lib_2026_06_10.py` — shared corrected model + stat helpers.
- `scalp_oos_bbo_fixed_2026_06_10.py` — main OOS runner; env coin selection + `OOS_LIMIT`; fires parquet
  `_results/scalp_oos_bbo_fires_fixed_2026_06_10{TAG}.parquet` with `frac_held`; TOD section retained;
  **plus an in-fire STOP simulation** (5s-grid bid poll fire+85ms→ext, trigger `bid<=entry-0.10`,
  size-capped sell, remainder held) → final paired `pnl_stop - pnl60`, ALL and CLEAN.
- `scalp_midwindow_fixed_2026_06_10.py`, `scalp_fvg_fixed_2026_06_10.py`,
  `scalp_xasset_fixed_2026_06_10.py`, `scalp_trailing_fixed_2026_06_10.py`,
  `scalp_entry_opt_fixed_2026_06_10.py` — same grids/gates/cells as originals, corrected exit.
- `maker_exit_fixed_2026_06_10.py` — port of the queue-aware L25 maker-exit; taker-+60 fallback now
  size-capped at L25 best-bid depth with held remainder (no outcome-as-price), maker sell size-capped at
  resting peg size with taker-fallback remainder.

All runners keep the checkpoint-per-coin-tf parquet pattern, flush prints, env coin var, and write to
`_results/*_fixed_2026_06_10*.parquet`.

## AMENDMENT 2026-06-10b — size==0 is a COLLECTOR ARTIFACT (not real zero depth)

Verified on raw BBO (SOL, 3h sample, 5,340 rows): **47.2% of rows have BOTH best_bid_size==0 AND
best_ask_size==0 while prices are ALWAYS present**, and rows with size>0 show 5,210–8,800 shares depth
(p10–p90) — ~100× our ~62-share orders. Conclusion: size==0 = price-only collector update, NOT real
zero depth. The first-pass policy (size==0 → hold remainder to resolution) wrongly converted ~half the
fires into resolution-valuation — too harsh, and it reintroduced heavy dependence on `won`.

**Amended model (`resolve_size` in the lib):** size==0/NaN is UNKNOWN → use the last POSITIVE size for
that token at-or-before the quote row within 300s; else the next positive size within 300s after; else
assume DEEP (no cap — justified by the ~100× depth ratio). Applied to:
- `exit_fill` bid size, the runner's stop-sim sizes, and the trailing runner's grid/fixed sells;
- `entry_fill` ask size — artifact rows were phantom auto-skips under the underfill rule. Fires whose
  entry used a carried size are tagged `entry_size_carried` (exit side: `exit_size_carried`).
Unchanged: 120s PRICE-staleness guard, NaN/missing-bid → whole position held (`held_full`), sold-leg
0.015 fee, held-leg winner-only 0.07 valuation, original underfill rule, ALL vs CLEAN dual reporting.
(`maker_exit_fixed` is on L25 where sizes are real — no artifact handling needed there.)

## Smoke result (amended harness, `OOS_COINS=SOL OOS_LIMIT=80`)

```
candidate fires (delta>=3) = 80; filled = 56 (was 33 first-pass: phantom entry skips recovered)
old-fallback-incidence = 0
frac_held: mean=0.071  held_full=0.071  clean(frac==0)=0.929   (was 0.515 first-pass)
entry_size_carried = 0.411   exit_size_carried = 0.446

ALL filled              ALL   n=56 $/tr=+0.859 t=+0.69 CI=[-1.671,+3.185] won=0.536
                        CLEAN n=52 $/tr=+1.957 t=+2.08 CI=[+0.162,+3.768]
GATED vwap<0.55         ALL   n=37 $/tr=+1.165 t=+0.65 CI=[-2.372,+4.587] won=0.541
                        CLEAN n=33 $/tr=+2.933 t=+2.34 CI=[+0.494,+5.285]
GATED & d>=5            ALL   n= 8 $/tr=-2.830 CI=[-12.937,+5.225] | CLEAN n=6 $/tr=+4.561 CI=[+2.478,+6.550]

STOP SIM (paired pnl_stop - pnl60), gated vwap<0.55:
  ALL    DIFF mean=-1.0549 CI=[-3.2552,+0.2624] ns   (OLD CLAIM +0.88/tr)
  CLEAN  DIFF mean=-1.1828 CI=[-3.5624,+0.3121] ns
TOD: exclude {12,17} CLEAN n=32 $/tr=+3.424 CI=[+1.104,+5.759] >= base CLEAN +2.933
```

First-pass smoke (pre-amendment, same slice, for the record): filled=33, frac_held=0.515,
gated CLEAN n=11 +6.641 CI=[+2.99,+10.58], stop diff exactly 0 (never triggered).
Earlier confirmation runs on `entry_opt_fixed`, `trailing_fixed` (ALL+CLEAN+peak-oracle bound),
and `maker_exit_fixed` (ME_LIMIT=60) all ran end-to-end. Smoke parquets deleted after verification.

## Incidence of the old fallback

- **Literal outcome-as-price fallback (Bug 1) incidence = 0** on the smoke slice: a finite bid always
  existed at the old `jx`. Bug 1 is the tail case (missing/stale bid) — expected low-but-nonzero on the
  full universe; the guard stays.
- **Bug 2 reframed by the amendment:** the old "sell full size at best_bid" was mostly selling into
  ARTIFACT zero-size rows that actually had ~100× depth behind them — approximately right for the wrong
  reason on this tape. The amended model prices the residual real cases honestly: 7.1% of fires still
  end held (no positive size within ±300s), and the carried tags quantify how much rests on the carry
  assumption (~41–45% of fires touch a carried size).
- Smoke deltas vs first pass: fills 33→56, frac_held 0.515→0.071, gated CLEAN +6.64→+2.93 (CI>0 both),
  stop paired diff now measurable at −1.05/tr ns (old claim +0.88/tr NOT reproduced on this slice; full
  run decides).
