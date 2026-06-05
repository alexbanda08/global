# GPU LSTM — BTCUSDT_1h (underlying-crypto direction) — auto

Device=cuda. SEQ=64, next-bar direction. Walk-forward train70/val15/**test15** (held out).

- Test directional accuracy: **0.510** (0.50 = coin-flip)
- OOS strategy Sharpe (pos=conf>0.55, 5bps): **-1.53**   vs buy&hold Sharpe -0.50
- n_test=11527, trades=114

## Read
- acc≈0.50 and Sharpe≈0 => deep net finds NO tradeable direction (efficient), consistent with the indicator sweep.
- Only a clearly >0.5 acc AND OOS Sharpe>buy&hold that holds on a 2nd asset/window is real. Re-confirm before sizing.