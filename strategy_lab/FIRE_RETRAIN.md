# FIRE: Retrain Kronos on Extended BTC Data (Path B)

## Status: READY TO FIRE

All prep is done. Single command launches the retrain.

## What will happen

1. Tokenizer phase: **SKIPPED** (pre-copied from previous fine-tune to `D:/kronos-ft/BTCUSDT_5m_ext/tokenizer/`)
2. Predictor phase: trains from Kronos-base on extended dataset (321,554 bars, Apr 2023 → Apr 22 2026)
3. Runtime: **~5-6h** on RTX 3060
4. Output: `D:/kronos-ft/BTCUSDT_5m_ext/basemodel/best_model/` (409 MB model.safetensors + config)

## Fire command

From `C:/Users/alexandre bandarra/Desktop/global/external/Kronos/finetune/`:

```bash
D:/kronos-venv/Scripts/python.exe -u train_sequential.py --config "C:/Users/alexandre bandarra/Desktop/global/strategy_lab/kronos_ft/config_btc_5m_ext.yaml"
```

(Claude will wrap this with proper background execution + logging when you say go.)

## Data summary

| Item | Value |
|---|---|
| Training CSV | `strategy_lab/kronos_ft/data/BTCUSDT_5m_ext.csv` |
| Total bars | 321,554 |
| Date range | 2023-04-01 → 2026-04-22 14:00 CEST |
| Split (85/7.5/7.5) | Train ~273k, Val ~24k, Test ~24k |
| Training tail | ~early Jan 2026 |
| Test slice | ~Feb 1 → Apr 22 2026 |

## After training completes

Claude will auto-run:
1. Kronos inference on the 444 Polymarket window_starts (both sample=1 and sample=30)
2. Full backtest with all 56 strategies
3. Comparison table: new model vs old model on same markets
4. Final verdict: did the Apr-included training recover the edge?

## Safety / resume

- If training stops mid-predictor-run: the best_model saved so far is kept
- Tokenizer is already in place, so `skip_existing: true` will prevent re-training it
- To resume: just re-run the same fire command; it'll see the partial predictor state and (depending on script support) either restart the predictor or skip if a good basemodel exists

## To fire: just say "go" or "fire retrain"
