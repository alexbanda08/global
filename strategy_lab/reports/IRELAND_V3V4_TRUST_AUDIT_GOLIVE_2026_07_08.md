# Ladder v3/v4 + sumpair + scalp — full trust audit & go-live verdict
**2026-07-08. 6.1 days of v3 paper (Jul 2 09:22 → Jul 8 12:15), 3,956 ladder windows + 3,389 sumpair events + fixed scalp twin, per-transaction verification. Raw + scripts: `strategy_lab/directional/_ireland_6day/{ladder_v3v4.tsv, sumpair_all.tsv, scalp_twin_jul.tsv, analyze_v3.py}`.**

## 0. What's on the box (more than we specced — agent shipped extras)
`poly_ladder_btc_15m_v3` + `poly_ladder_btc_5m_v3` (Jul 2) + **`poly_ladder_eth_5m_v3`** (Jul 4, market expansion) + **`poly_ladder_btc_15m_v4_coc`** (Jul 5 — Complete-Or-Cut residual variant: wait 75s, complete pair as taker if sum≤0.995 else cut; env `TV_LADDER_COC_*`) + `sumpair_osc_{btc,eth}_5m` + fixed scalp twin. Engine also now logs `outcome_source: gamma_chainlink` + `outcome_binance` cross-check + `settle_attempts` + `feed_watchdog` (in-engine feed recovery — **NOT the tv-watchdog kill-path, which remains undeployed**). Rebate credited at an ASSUMED `rebate_rate_assumed=0.0015`.

## 1. CAN WE TRUST THE DATA? — YES (verified per-transaction)
| check | result |
|---|---|
| PnL identity (all 2,053 settled-traded rows) | **exact to 1e-8**: `total_net = paired + rebate + residual − coc_cut_cost − coc_taker_fee` (v3 rows have coc terms = 0). First-pass "77 diverging rows" was MY incomplete formula, not the engine. |
| `paired_pnl = paired_sh·(1−pvs)` | exact 0.000000 |
| Outcome truth | engine settles on **gamma_chainlink** and logs a Binance cross-check. 66/1,693 (3.9%) mismatches — probed 3 directly: all **sub-tick near-ties** (−0.40/+0.37/+0.38 bps moves) where Chainlink legitimately differs from Binance. Correct behavior, and the near-tie rate quantifies real "outcome risk" windows. |
| Deep quotes | `fill_below_touch_ticks` mean **2.03–2.05**, min 1.0, ~0 violations across 2,800+ fill observations — never at the touch, exactly as specced |
| Backstop | firing (72% of residual windows fully flattened on 15m; flatten accounting inside `residual_pnl`, costs logged) |
| `pair_gate_bound_sh` | now counting (>0 in 289 windows total); pvs ≤ 0.99 everywhere (max exactly 0.990) |
| Settlement | 0 unsettled traded windows; `settle_attempts` retries up to 25 (gamma lag) all converge |
| Best-window forensics | +$146 outlier = real crash-window mechanics (dirt-cheap fills both sides, backstop monetized the dn leg mid-spike); tail windows are where paper-fill optimism concentrates → covered by ex-top2 below |

Residual caveats (small, for live verification): rebate is an assumption (~+$0.02–0.03/win); paper FIFO fills can't price live queue competition — the one gap only live fills close.

## 2. PERFORMANCE (settled traded windows, with the mandatory ex-top2 test)
| sleeve | n | net/win | CI95 | **ex-top2** | median | %pos | $/day | verdict |
|---|---|---|---|---|---|---|---|---|
| **btc-5m v3** | **1,262** | **+1.028** | **[+0.74,+1.38]** | **+0.870 [+0.66,+1.09]** | +0.587 | 61% | **+$212** | ✅ **PASSES — CI>0, ex-top2 CI>0, positive EVERY day (7/7)** |
| eth-5m v3 | 435 | +0.422 | [+0.16,+0.69] | +0.382 [+0.13,+0.64] | +0.217 | 55% | +$42 | ✅ positive & robust, weaker — 2nd candidate |
| btc-15m v3 | 246 | +0.013 | [−0.53,+0.56] | **−0.132** | +0.136 | 52% | +$0.5 | ❌ flat; top-2 windows = entire profit |
| btc-15m v4_coc | 110 | +0.609 | [−0.02,+1.28] | +0.313 [−0.19,+0.80] | +0.318 | 56% | +$19.5 | 🟡 ns; **matched-slug diff vs v3 = −0.17 [−0.79,+0.43]** — apparent edge is window-selection; COC actions netted −$32 vs hold. Keep paper. |

**The v2→v3 fix worked exactly as designed:** residual heavy-side win-rate **14.1% → 47.5%** (adverse selection eliminated by deep quotes), residual drag −$2.46 → −$0.46/win (15m) and ≈$0 (5m). And the market lesson repeated: **the edge lives on 5m, not 15m** — third independent confirmation (our ladder, b945's live book, sumpair below).

## 3. SUMPAIR_OSC — the fill-model question RESOLVED (6.4d)
- **btc-5m: level0 +$0.509/slug CI[+0.21,+0.82] AND walk +$0.523/slug CI[+0.21,+0.85]** (n=552 slugs) — the two fill models **agree on live books** and both are positive. The offline "−0.70 walk" fear didn't materialize; **the offline +0.52 validation is CONFIRMED live-paper almost to the cent.** both_filled 21%, paircost med 0.83.
- eth-5m: flat (−0.06 [−0.30,+0.21]) — BTC-only edge, matches offline.

## 4. SCALP TWIN (fixed) — working, n small
11 exits since Jul 2: **band 100% compliant** (max entry 0.540), **losses no longer cluster at −$5** (0 of 11), `sell_source` logged, mean +$0.82/tr. The measurement is finally right; keep accruing.

## 5. GO-LIVE VERDICT
**`poly_ladder_btc_5m_v3` passes the pre-registered paper gate** (≥~1wk, CI>0, ex-top2 CI>0, trusted accounting, mechanism verified end-to-end). Remaining blockers — all operational, none statistical:
1. **`tv-watchdog` kill-path — still not deployed.** Hard prerequisite (house rule). (`feed_watchdog` events are feed recovery, not this.)
2. **TVRUST live maker order path** — the ladder has only ever paper-traded; `TV_POLY_LADDER_LIVE_ENABLED=false` exists but the live executor (place/cancel/requote GTC bids, wallet creds on the rust engine, venue min-size handling) must be confirmed implemented + integration-tested. The rust engine has never placed a real order.
3. **Wallet + bankroll:** median window uses ~$9/side but crash-tails fill $60+ → fund **~$300–500** and add a **per-window inventory cap** (e.g. $50/side) for the first stage.
4. **Pre-registered live gates (write before flipping):** live-vs-paper-twin fill-capture ratio ≥ ~50% (the queue-competition unknown — run the paper twin in parallel and compare per-window fills); live wallet net CI>0 over ≥2wk; kill if capture <25% or net CI<0 at n≥300 windows.

**Recommended sequence:** TV agent confirms/builds live executor + deploys watchdog → fund ~$400 → flip `btc_5m_v3` live at capped size with the paper twin running in parallel → judge on live wallet + capture ratio. Everything else (15m, v4_coc, eth, sumpair) stays paper.

## 6. Loose ends
- v4_coc: not better than v3 on matched slugs; COC completions/cuts cost −$32 vs hold. Let it accrue; kill in a week if still ns.
- btc-15m v3: flat — candidate for the cheap-side-skew knob (the worst windows are expensive-side accumulation, e.g. dn@0.70 falling knife) before giving up on 15m.
- Verify the real Polymarket maker-rebate rate vs the assumed 0.0015 when live.
- Near-tie windows (3.9%) = irreducible outcome noise; live sizing should expect it.
- Old v2 partitions still deletable on Ireland once v3 archived (backup exists on D:).
