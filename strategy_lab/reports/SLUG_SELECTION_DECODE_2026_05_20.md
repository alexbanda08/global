# Slug-selection decode — 2026-05-20

**Question (from `NEXT_SESSION_PICKUP_2026_05_20.md`):**
Can we predict which slugs the reference wallets engage, then capture their
alpha by running ACC-M on classifier-selected slugs only?

**Short answer:** The selection signal is **real but small**, and it is **not aligned with PAT+ACC-M PnL**. Wallet engagement is highly predictable from static book + binance + time features (AUC 0.62–0.98), but predicted-engaged slugs do not have meaningfully higher PAT+ACC-M PnL than random subsets. Wallets must derive their edge from **within-slug microstructure timing**, **a different strategy than ACC-M**, or **information we don't observe**.

---

## What we built

| Script | Output | Purpose |
|---|---|---|
| `strategy_lab/backtests/build_slug_features.py` | `_per_slug_features_btc.csv` (8146 slugs × 38 cols) | Per-slug feature table: book at first L25 snapshot + binance leading vol/ret + time |
| `strategy_lab/backtests/train_wallet_classifier.py` | `_wallet_classifier_metrics.csv`, `_wallet_classifier_weights.csv`, `_wallet_selected_slugs.csv` | 5-fold CV logistic regression + gradient boosting per wallet |
| `strategy_lab/backtests/validate_classifier_pnl.py` | `_classifier_pnl_validation.csv` | Compare PAT+ACC-M / ACC-M / MAS PnL on classifier-selected slugs vs random vs wallet-actual |

## Feature set (18 numeric + 1 categorical)

Book (at first L25 snapshot per outcome):
- `sum_bids`, `sum_asks`, `spread_up`, `spread_dn`, `mid_diff`
- `depth_up`, `depth_dn`, `depth_tot`, `depth_imb`

Binance leading (anchored on production `ws_s = slot_start - window`):
- `ret_60s`, `ret_120s`, `abs_ret_60s`, `abs_ret_120s`
- `vol_5m`, `vol_10m` (realized std of 1m log-rets)

Time:
- `hour_utc`, `weekday`, `min_in_hour`

Categorical: `tf` (5m / 15m, one-hot encoded)

---

## Classifier results — engagement is highly predictable

| Wallet | Pattern | n_engaged / n_window | Base rate | LR AUC | GB AUC | Lift @ top-20% |
|---|---|---:|---:|---:|---:|---:|
| 0x04b6d7e9 | MAS | 229 / 396 | 57.8% | 0.805 | **0.984** | 1.66× |
| 0xeebde7a0 | HYBRID (Bonereaper) | 321 / 327 | 98.2% | — (skipped: 6 unengaged) | — | — |
| 0x89b5cdaa | directional MAS (ohanism) | 368 / 482 | 76.3% | 0.552 | 0.620 | 1.04× |
| 0xcfb103c3 | PAT (xuanxuan008) | 324 / 482 | 67.2% | 0.924 | **0.944** | 1.43× |
| 0xce25e214 | mixed taker | 90 / 192 | 46.9% | 0.847 | **0.947** | 2.08× |

**Three of four wallets have very strong selection signals (GB AUC ≥ 0.94).** 0x89b5cdaa engages broadly with weak feature differentiation. 0xeebde7a0 engages 98% of slugs in its window — no selection problem.

### Top features by wallet (standardized logistic-regression coefficients)

```
0x04b6d7e9 (MAS):
  hour_utc   +1.56    time-of-day driven
  vol_10m    +1.22    higher vol → engage
  weekday    +1.12

0xcfb103c3 (PAT):
  tf_5m      +1.51    strongly prefers 5m, avoids 15m
  vol_10m    -0.85    lower vol → engage
  weekday    +0.53

0xce25e214 (mixed):
  weekday    -1.06
  vol_10m    +1.03    higher vol → engage
  hour_utc   -0.68

0x89b5cdaa (directional MAS):
  weak signals across all features (AUC 0.62)
```

The strongest single-feature finding: **0xcfb103c3 (PAT/xuanxuan008) trades 5m and avoids 15m**. This is a strict tf preference, not microstructure-driven.

---

## PnL validation — selection alpha does NOT amplify PAT+ACC-M

Expected PnL per slug on PAT+ACC-M (non-fires count as $0):

| Wallet | window_all | wallet_actual_engaged | classifier_top@n_eng | classifier_top@10% | classifier_top@50% |
|---|---:|---:|---:|---:|---:|
| 0x04b6d7e9 | $0.87 | $1.12 (×1.28) | $1.12 | $0.00 | $1.16 (×1.33) |
| 0x89b5cdaa | $0.94 | $0.99 (×1.05) | $1.04 | $1.26 (×1.34) | $0.52 |
| 0xcfb103c3 | $0.94 | $1.03 (×1.10) | $0.64 | $0.06 | $0.48 |
| 0xce25e214 | $1.58 | $2.20 (×1.39) | $1.53 | $0.00 | $2.06 (×1.30) |

Random-subset baseline is essentially identical to `window_all` (±$0.01) across all wallets — confirming that wallet's actual engagement provides at most a **1.3-1.4×** lift on PAT+ACC-M, not the 5-10× we would need to explain the wallets' real-money PnL.

PAT+ACC-M fire-rate per subset:

| Wallet | window_all | wallet_actual_engaged | Top-20% classifier |
|---|---:|---:|---:|
| 0x04b6d7e9 | 2.8% | 3.5% | 0.0% |
| 0x89b5cdaa | 2.9% | 3.5% | 2.1% |
| 0xcfb103c3 | 2.9% | 3.7% | 2.1% |
| 0xce25e214 | 4.2% | 5.6% | 2.6% |

ACC-M / ACC-PC / sized variants fire on 0.4–1.1% of wallet-window slugs — they barely activate. ACC-M PnL is fee-bleed regardless of selection.

MAS-pre30 fires on 100% (always tries) but expected PnL is +$0.01-0.03 per slug — flat.

---

## Interpretation

**1. The signal exists.** Three reference wallets have GB AUC ≥ 0.94. Engagement is predictable from book opening, binance leading vol/ret, and time-of-day. The top discriminators are intuitive (time-of-day, vol regime, timeframe).

**2. The signal is NOT slug-selection-for-our-strategies alpha.** Classifier-top subsets have *lower* fire-rates and *lower* PnL on PAT+ACC-M than wallet-actual engagement. Predicting "would the wallet engage" is a different question from "would PAT+ACC-M profit here."

**3. Modest selection lift is real but small.** Wallet-actual subsets show 1.05–1.39× PAT+ACC-M PnL vs window/random. Multiplied by full-universe PAT+ACC-M of +$7.79/slug, that's +$10/slug at best on the wallet's selected ~250 slugs ≈ $2.5k for the wallet over 21 days. Reference wallets actually earn $1.7k–$6k *per day* per LB-API. Selection alone can't close the 50–100× gap.

**4. The wallets' edge must be elsewhere.** Most likely candidates:
   - **Within-slug timing**: entry/exit at specific microstructure events (sweep imbalance, sudden REST/WS lag, oracle-tick proximity) — features collapsed away by our static opening-book snapshot
   - **A different strategy**: pre-mint + price-drift exit (true MAS), pair-arb mint at specific price/spread combos, or active inventory management that wins on direction, not on maker/taker spread
   - **Order-flow / venue information** we don't have (e.g., their own taker fills moving price, hosted bot vs ours)

---

## What to try next session

Falsifiable next experiments, in priority order:

1. **Within-slug fire-time analysis.** For each engagement, look at *when* (offset from slot_start) the wallet enters and exits. Compare to PAT+ACC-M fire offset. If wallets enter earlier / on a specific event, that's the missing alpha.

2. **Per-wallet actual-PnL per slug as the target, not engagement.** Train a classifier with target = "wallet made profit on this slug" instead of "wallet engaged this slug". This isolates the profit-relevant selection signal, not just the engage signal.

3. **Decode 0xcfb103c3 (PAT/xuanxuan008) more deeply.** Strongest signal (AUC 0.94) and known PAT pattern. The tf_5m + low-vol preference suggests it runs PAT only on calm 5m books. Simulate PAT only on those subsets and check against $12.6M cumulative volume from chain decode.

4. **Trade-tape leading features.** Add Polymarket trade-flow features (cvd_60s, trade_count_60s, large_print_in_120s) and time-asymmetry of fills (initiator side from trades parquet) to feature table. These need to be measured at fire_us, not slug-open.

5. **Engagement vs profit decomposition for 0x89b5cdaa.** Weakest engagement signal but highest LB-API rank. Either it engages indiscriminately and profits via within-slug execution, or its target dataset is too narrow (only 482 slugs in window vs 1500 fills). Cross-check chain PnL per engaged slug.

---

## Artifacts written this session

```
strategy_lab/backtests/build_slug_features.py
strategy_lab/backtests/train_wallet_classifier.py
strategy_lab/backtests/validate_classifier_pnl.py
strategy_lab/backtests/_per_slug_features_btc.csv          (8146 rows × 38 cols)
strategy_lab/backtests/_wallet_classifier_metrics.csv      (per wallet × model)
strategy_lab/backtests/_wallet_classifier_weights.csv      (per wallet × feature)
strategy_lab/backtests/_wallet_selected_slugs.csv          (slug, wallet, prob_lr, prob_gb, engaged)
strategy_lab/backtests/_classifier_pnl_validation.csv      (wallet × strategy × subset)
strategy_lab/reports/SLUG_SELECTION_DECODE_2026_05_20.md   (this report)
```

## Quick rerun

```bash
py -3 -X utf8 strategy_lab/backtests/build_slug_features.py --asset btc
py -3 -X utf8 strategy_lab/backtests/train_wallet_classifier.py
py -3 -X utf8 strategy_lab/backtests/validate_classifier_pnl.py
```

All three run end-to-end in under 1 minute (after the L25 open-book scan, which is ~25s).
