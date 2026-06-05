# GPU LSTM — SOLUSDT_4h (underlying-crypto direction) — auto

Device=cuda. SEQ=64, next-bar direction. Walk-forward train70/val15/**test15** (held out).

- Test directional accuracy: **0.489** (0.50 = coin-flip)
- OOS strategy Sharpe (pos=conf>0.55, 5bps): **0.00**   vs buy&hold Sharpe -2.50
- n_test=1899, trades=0

## Read
- acc≈0.50 and Sharpe≈0 => deep net finds NO tradeable direction (efficient), consistent with the indicator sweep.
- Only a clearly >0.5 acc AND OOS Sharpe>buy&hold that holds on a 2nd asset/window is real. Re-confirm before sizing.