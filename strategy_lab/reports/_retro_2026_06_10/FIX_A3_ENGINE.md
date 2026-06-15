# FIX A3 — engine_v2 `hold_pnl` loser-fee overcharge + lag-taker re-check — 2026-06-10

## 1. The bug

`strategy_lab/engine_v2.py :: hold_pnl`, the `poly_taker_curve` **LOST** branch subtracted the
entry fee (`fee_in`) on losing hold-to-resolution trades. Live Polymarket charges **$0** fee on a
losing leg (operator-confirmed 2026-06-03, CLAUDE.md): a lost hold pays exactly `-entry_qty *
entry_price`. The winner branch (`qty*(1-p)*(1-0.07*p)`) was already correct; only the loser branch
overcharged — ≈ **$0.87 / losing trade at p≈0.51, 50 shares** (`fee_in = sh*0.07*p*(1-p)`).

`sell_pnl` was **left untouched**: a SELL on the book is a genuine taker fill that does incur the
curve fee in live — that is a different fee question and is NOT contradicted by the "hold-to-resolution
loser pays $0" rule. `LegacyConfig` (2%-on-profit) behavior is unchanged.

### Diff (`hold_pnl`, lost / poly_taker_curve branch)

```diff
     # lost
     if cfg.fee_model == "poly_taker_curve":
-        # paid entry fee + lost the principal
-        return -usd_in - float(fill.get("fee_in", 0.0)) - tx
+        # OPERATOR-CONFIRMED 2026-06-03 (CLAUDE.md): live Polymarket charges $0 fee
+        # on a losing hold-to-resolution trade — the loser pays exactly its principal,
+        # `pnl = -entry_qty * entry_price`, with NO taker fee on the losing leg.
+        # The winner branch above already matches live (qty*(1-p)*(1-0.07*p)); only
+        # this loser branch was overcharging the entry `fee_in` (~$0.87/loss at p≈0.51).
+        return -usd_in - tx
     else:
         return -usd_in - tx     # legacy: no fee on loss, but tx still applies
```

## 2. Verification

### Worked example (CLAUDE.md)
```
WON  entry=0.509 qty=50 -> +23.6753   expect +23.675   OK
LOST entry=0.508 qty=50 -> -25.4000   expect -25.40    OK
loser fee overcharge at p=0.51, 50sh: 0.8747   (matches ~0.87 audit claim)
```

### In-file smoke (`python strategy_lab/engine_v2.py`), post-fix
```
--- HOLD pnl, won ---     legacy +10.9760   live_mimic +10.6580   realistic +10.6480
--- HOLD pnl, lost ---    legacy -25.0000   live_mimic -25.0000   realistic -25.0100
```
`live_mimic` lost was `-25.5420` pre-fix (the $0.542 `fee_in` at p=0.69); now `-25.0000`. Winner
unchanged. Realistic lost `-25.01` = just the $0.01 tx, no fee. Correct.

## 3. Affected scripts (`hold_pnl(` callers — 50 files)

These call `hold_pnl(` directly; those passing `LiveMimicConfig`/`RealisticConfig` (poly_taker_curve)
with losing hold-to-resolution trades had their losses overcharged ~$0.87/loss → verdicts slightly
PESSIMISTIC (real edge is a touch better than reported). Full list of importers in
`grep hold_pnl|LiveMimicConfig|RealisticConfig strategy_lab/**.py` (96 symbol refs; 50 call hold_pnl).
Notable:

- `directional/scalp_rigor_2026_06_02.py`, `scalp_rigor_full_2026_06_02.py`, `scalp_exit_*`,
  `cusum_vwap_gates_2026_06_02.py`
- `autoresearch/scalp_dynamic_exit_2026_06_04.py`, `favorite_fill_revalidate_2026_06_04.py`,
  `oracle_*_2026_06_05.py`
- `meta_classifier/momo_full_universe*_.py`, `momo_*_5m.py`, `vwap_*`, `backtest_vs_live_momo_2026_05_29.py`
- `_sleeve_reaudit_2026_06_03/*`, `s4_backtest_2026_06_03/s4_faithful.py`, `physics/*`,
  `full_window_validation*`, `spread_loosen_*`, `f2_replica/*`

NOTE: many scalp/lag scripts compute PnL with a **local** winner-only `pnl_007`/`pnl_07` helper
(NOT `hold_pnl`) and were therefore NEVER affected — including the lag-taker reval below.

## 4. Lag-taker OOS re-check (re-priced from saved fires, NO L25 re-run)

Source: `strategy_lab/lag_taker_fires_oos_2026_06_01.parquet` (2,538 fires; cols entry_vwap, shares,
won, segment, hour, delta_bps, asset — all present). The script
(`directional/lag_taker_oos_reval_2026_06_01.py`) used its own winner-only `pnl_007`, NOT `hold_pnl`,
so the saved `pnl` column was **already on the correct fee**.

**Cross-check: `max| saved_pnl − winner_only_repricing | = 0.0005`** (rounding only) → the published
report `LAG_TAKER_OOS_REVAL_2026_06_01.md` numbers ARE the corrected-fee numbers.

"OLD(bug-fee)" below = hypothetical, had the engine loser-fee bug been applied. "NEW(winner-only)" =
saved/correct, matches the published report. Bootstrap CI = 5000 resamples (seed 42), BTC+ETH,
hold-to-resolution, 0.07 winner-only.

| gate | segment | n | WR | OLD (bug-fee) $/tr, t, CI | NEW (winner-only) $/tr, t, CI |
|---|---|--:|--:|---|---|
| ge3 | FIT(IS+OOS) | 786 | 65.1% | +1.45, t=1.99, [+0.03,+2.85] | **+1.71, t=2.38, [+0.36,+3.16]** |
| ge3 | **UNSEEN(bwd+fwd)** | 556 | 60.8% | +0.06, t=0.07, [−1.75,+1.85] | **+0.36, t=0.41, [−1.37,+2.14]** |
| ge5 | FIT(IS+OOS) | 250 | 68.0% | +1.69, t=1.36, [−0.75,+4.06] | +1.92, t=1.58, [−0.46,+4.27] |
| ge5 | **UNSEEN(bwd+fwd)** | 180 | 58.9% | −0.94, t=−0.59, [−4.03,+2.15] | **−0.63, t=−0.40, [−3.61,+2.49]** |
| ge3_ex18-23 | FIT(IS+OOS) | 575 | 67.1% | +2.43, t=2.86, [+0.79,+4.11] | **+2.67, t=3.20, [+1.03,+4.30]** |
| ge3_ex18-23 | **UNSEEN(bwd+fwd)** | 422 | 61.8% | +0.83, t=0.79, [−1.27,+2.89] | **+1.13, t=1.10, [−0.90,+3.17]** |

The published report matches the NEW column exactly.

### Does the verdict flip? NO.

- **UNSEEN ge3** (the headline OOS): **+$0.36/tr, t=0.41, CI [−1.37,+2.14]** — still spans 0, still
  underpowered. The fix would have nudged a bug-affected run from +0.06/t0.07 up to +0.36/t0.41, but
  it does NOT reach significance. (Moot anyway: this report was already correct-fee.)
- **UNSEEN ge5** still inverts negative (−0.63, t=−0.40) → overfit signature stands; do not deploy ≥5bps.
- **UNSEEN ge3_ex18-23** is the strongest unseen cell at +1.13/t1.10 — encouraging, not conclusive.
- FIT cells significant (ge3 t=2.38, ge3_ex18-23 t=3.20) but FIT was never the question.

Verdict from `LAG_TAKER_OOS_REVAL_2026_06_01.md` — **HOLD real-money sizing, collect 2–4 weeks live-feed
forward shadow before scaling** — is **UNCHANGED**.
