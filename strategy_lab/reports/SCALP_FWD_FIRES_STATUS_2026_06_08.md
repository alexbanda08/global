# Exit-Scalp — Forward-Fire Validation Status (2026-06-08)

Lane: accumulate ≥200 live forward fires + live-wallet bootstrap CI before scaling real
capital (06-06 handoff §E#4). This is a checkpoint on that gate, queried live from VPS3
(shadow fleet) + Ireland (live wallet) on 2026-06-08 ~18:30 UTC.

Scripts: `migration_2026_06_08/scalp_fwd_agg.py`, `scalp_fwd_realfee.py`.

## TL;DR
1. **Shadow forward sample is healthy and edge-shaped** but underpowered after honest fees.
2. **The LIVE wallet is BOTH tiny (~21 trades) AND CONTAMINATED** — both live sleeves still
   run TP@0.65 + stop, never the validated pure +60 exit. ⇒ live fires are NOT testing the
   real strategy. **Blocker: apply `TV_AGENT_SPEC_SCALP_DISABLE_TP_2026_06_06.md` BEFORE
   accumulating the 200, or the gate validates the wrong (leaky) variant.**

## A. Shadow forward sample (VPS3, 2026-06-03 → 06-08, paper)
Realized `sleeve_scalp_exit` events, bootstrap 95% CI on per-trade PnL. `raw` = as logged
(`sell_leg_fee=0.0`, optimistic); `realfee` = minus taker sell fee `0.07·q·(1−q)·shares`.

| sleeve | n | raw mean / CI | real-fee mean / CI |
|---|---|---|---|
| btc_5m_d3_v1        | 81  | +0.42 [+0.10,+0.73] | **+0.27 [−0.05,+0.58]** |
| btc_15m_d3_v1       | 44  | +0.45 [+0.16,+0.75] | **+0.29 [−0.004,+0.59]** |
| eth_5m_d3_v1        | 22  | +0.21 [−0.34,+0.75] | +0.05 [−0.50,+0.60] |
| btc_5m_d3_**control** | 353 | +0.085 [−0.02,+0.20] | **−0.05** (flat-neg) |
| btc_5m_d3_tod2_v1   | 26  | +0.07 | −0.09 |
| btc_5m_d3_notp_v1   | 7   | +0.20 | +0.05 (started 06-07, the clean no-TP A/B) |

Reading: gated δ≥3 BTC sleeves are positive in point estimate and **separate cleanly from
the flat-negative control** — the edge is real-shaped. But the real sell fee (~$0.15/tr)
drags the lower CI bound to ≈0 at current n. **Underpowered, not disproven** — exactly why
the ≥200-fire gate exists. At +0.27 mean and this variance, ~200 fires should exclude 0.
SOL/DOGE/XRP/BNB fire-eval ~580/day but PLACE ≈0 (thin books / gates) — not accumulating.

## B. Live wallet (Ireland, real $1) — the actual graduation metric
- `shadow_scalp_exit_btc_5m_d3_v1_LIVE`: **10 scalp-exits + 8 redeems ≈ 18 trades.**
  Exit PnL: `+0.56 +0.27 −0.34 −0.18 +0.26 −0.38 −0.27 +0.29 −0.19 −0.20` →
  **sum ≈ −$0.18, mean ≈ −0.02/tr, WR 40%.**
- `kalshi_scalp_exit_btc_15m_d3_v1`: **11 trades.** `scalp_stop`×5 = −0.76, `scalp_time`×5
  = +0.10, `scalp_tp`×1 = +0.12 → **sum ≈ −$0.55.**
- Combined live realized ≈ **−$0.73 over ~21 trades** (tiny capital, tiny n).

### ✅ DEPLOYED CONFIG IS CORRECT — CODE-CONFIRMED 2026-06-08 (this corrects two earlier wrong drafts)
Code audit of the DEPLOYED Ireland engine (`controllers/polymarket_sniper_v5.py:1382`,
`strategies/polymarket/sniper_v5_sleeves.py`; engine restarted 06-08 14:23 *after* file
mtime 13:54 → this source is live). Exit decision:
```python
tp_on   = getattr(sleeve, "scalp_tp_enabled",   False)   # default False
stop_on = getattr(sleeve, "scalp_stop_enabled", True)    # default True
if   tp_on   and best_bid >= scalp_tp_bid:                  trigger = "tp065"
elif stop_on and best_bid <= fill_vwap - scalp_stop_delta: trigger = "stop"
else: return False     # poll until +60 deadline → trigger = "time60"
```
| config | deployed | validated? |
|---|---|---|
| TP@0.65 | OFF (`scalp_tp_enabled=False`) | ✅ correct — TP leaks edge (`SCALP_DYNAMIC_EXIT`, lookahead-confirmed) |
| Stop@−0.10 | **ON** (`scalp_stop_enabled=True`) | ✅ **correct — stop is +0.88/tr SIG on 5m** (`SCALP_EXIT_CONFIG_BY_TF_2026_06_06`) |
| 15m exit | `maker_fixed@0.60` + stop | ✅ correct — 15m maker is the validated winner |
| Exit time | +60s | ✅ correct — +45/+60 tied, +60 = argmax-mean |

**The deployed exit (TP off, STOP ON, 15m maker, +60) exactly implements the LATEST validated
research.** The authoritative test is **`SCALP_EXIT_CONFIG_BY_TF_2026_06_06`** (script
`maker_exit_by_tf_2026_06_06.py`, n=780, paired bootstrap), which decomposed TP vs stop
*separately* — superseding `TV_AGENT_SPEC_SCALP_DISABLE_TP` (which lumped them):
- 5m (n=531): pure taker+60 = +2.91/tr; **+STOP@−0.10 = +3.79, paired +0.88 SIG+.** Stop
  survives ≤3c slip (+0.48 SIG), dies at 6c (ns). Maker on 5m = ns → stay taker.
- 15m (n=249): maker@0.60 + stop combo = best.
- Verdict (verbatim): *"disable the TP, NOT the stop. The stop is protective and significantly
  positive, especially 5m."*

⚠️ **My two earlier framings in this file were WRONG:** (a) calling stop-removal a "missing
fix" and (b) calling the stop "the dominant live edge-leak." The opposite is true — **the
stop is the single biggest edge-ADD (+0.88/tr SIG).** The live `scalp_stop` exits aren't a
leak; they're the stop correctly cutting losers that would otherwise decay to bid_60 and
lose MORE. The −$0.73 over 21 live trades is small-n variance + honest fees, not a leak.

## C. Verdict on the gate
- **Live exits ARE the validated config** (TP off / stop on / +60 / 15m-maker). Nothing to
  "fix" — earlier "not pure +60" verdict was based on the superseded spec. Current live +
  shadow fires DO test the validated strategy → they COUNT toward the 200.
- Shadow d3 sleeves are the trustworthy forward signal (both raw-CI>0; real-fee CI grazes 0);
  rate ≈16/day btc_5m_d3 → ~200 by ~late June. The `notp_v1` twins (tp-off+stop-on) are the
  same config as `d3_v1` → redundant, harmless.
- **The ONE genuine open item on the stop = MAGNITUDE, not direction.** The +0.88 was on an
  OPTIMISTIC stop fill (sells at exact ev−0.10); live = taker-cross a FALLING thin book
  (spread_filter 0.05). At 6c slippage the 5m stop edge vanishes and the 15m stop turns
  NEGATIVE. The live losses going to stop (−0.34/−0.38, larger than −0.10·shares) suggest
  the live stop IS slipping. Keep the stop (direction robust), but quantify live stop
  slippage vs the +0.88 budget.

## D. Recommended next actions (priority)
1. **KEEP the stop — no change to the live config.** It is validated (+0.88/tr SIG 5m) and
   correctly deployed. The disable-TP spec's "remove stop" is superseded; mark that doc stale.
2. **Quantify live stop slippage** — pull the live `scalp_stop` fills' realized sell price vs
   `fill_vwap−0.10` on the _LIVE sleeve; compare the slip to the 3c/6c break-even from
   `SCALP_EXIT_CONFIG_BY_TF`. This is the real risk to the stop's +0.88, not whether to keep it.
3. Re-test the stop with an **L25 queue/slippage-aware fill** + OOS on Mar30–Apr21 BBO
   (`maker_exit_by_tf` caveat) to firm up the magnitude. Direction (keep) is not in question.
4. Set shadow `sell_leg_fee` to the real taker curve so shadow $/tr stops overstating.
5. Re-check this gate at n≈200 shadow (≈late June) and n≈100 live.

## E. Kalshi scalp — DEPRECATED (operator, 2026-06-08)
Kalshi has **no order book until ~+30s after market start**; the scalp fires at +5s → not
tradeable on Kalshi with this strategy. `kalshi_scalp_exit_*` sleeves are dead-ends for the
exit-scalp. **Focus Poly only.** (Independent of the separate Poly×Kalshi 15m settlement arb,
which is a different mechanism.)
