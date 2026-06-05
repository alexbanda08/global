# Overnight GPU model search — kline→poly relative-value — 2026-06-03

Trained **415** model configs (arch×seq×hidden×layers×horizon×features) on 8.8y klines (pre-2026-03-15); each judged by **poly-LOCKBOX relative-value $/tr** (does it beat the poly price?). Device=cuda.

## Top 15 configs by poly-lockbox $/tr
| arch | seq | hid | lay | hor | acc | polyLK $/tr | CI | n |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| lstm | 48 | 64 | 2 | 2 | 0.524 | -0.104 | [-0.51,+0.3] | 3181 |
| gru | 32 | 48 | 1 | 3 | 0.525 | -0.111 | [-0.5,+0.3] | 3206 |
| lstm | 32 | 64 | 2 | 3 | 0.528 | -0.127 | [-0.52,+0.28] | 3190 |
| lstm | 32 | 48 | 2 | 3 | 0.527 | -0.128 | [-0.54,+0.27] | 3196 |
| lstm | 48 | 48 | 1 | 3 | 0.526 | -0.13 | [-0.53,+0.27] | 3207 |
| lstm | 32 | 64 | 2 | 3 | 0.528 | -0.133 | [-0.53,+0.26] | 3215 |
| lstm | 48 | 32 | 1 | 3 | 0.525 | -0.136 | [-0.54,+0.27] | 3201 |
| lstm | 32 | 48 | 2 | 3 | 0.526 | -0.151 | [-0.55,+0.24] | 3206 |
| lstm | 48 | 64 | 1 | 1 | 0.517 | -0.152 | [-0.5,+0.18] | 4422 |
| gru | 32 | 48 | 1 | 3 | 0.526 | -0.152 | [-0.58,+0.28] | 2682 |
| lstm | 32 | 64 | 2 | 3 | 0.528 | -0.152 | [-0.56,+0.24] | 3181 |
| gru | 48 | 48 | 2 | 2 | 0.524 | -0.153 | [-0.55,+0.24] | 3203 |
| gru | 48 | 48 | 2 | 3 | 0.527 | -0.153 | [-0.54,+0.26] | 3207 |
| lstm | 32 | 32 | 1 | 3 | 0.528 | -0.153 | [-0.57,+0.24] | 3220 |
| gru | 64 | 32 | 1 | 2 | 0.523 | -0.157 | [-0.55,+0.26] | 3214 |

## Survivors (poly-lockbox CI>0 AND $/tr>0): 0/415

**None beat the poly price with CI>0.** The kline model does not find exploitable poly mispricing — poly up/down is efficiently priced vs an 8.8y-trained direction model. Edge stays in execution (exit-scalp).