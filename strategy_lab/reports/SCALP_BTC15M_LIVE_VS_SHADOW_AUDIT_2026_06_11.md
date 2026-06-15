# Live × Shadow audit — `shadow_scalp_exit_btc_15m_d3_v1` — 2026-06-11

**Question:** why do live (Ireland `_LIVE`, $1 real) and shadow diverge so much?
**Answer:** the strategy/engine does NOT diverge — signal parity is near-perfect. The apparent divergence is
**(1) era mix in the shadow's cumulative PnL (TP-on profits), (2) the stop drag concentrated in live's short
window (now removed), (3) a config drift (VPS3 15m runs maker-exit, live runs taker), (4) accounting artifacts.**

## 1. Engine parity — CLEAN ✅
- Ireland live vs Ireland paper twin: **6/7 fires identical** slug+direction+fill_vwap+shares (e.g. 0.53/0.51/0.48/0.50/0.55/0.46 — exact matches). The paper twin logs them as `scalp_hold_counterfactual`.
- Ireland live vs VPS3 shadow: 5/7 common slugs, same direction every time, fill vwaps within 0–2¢ (one 5¢: live 0.55 vs VPS3 0.50 on `...1081100` — book timing). No adverse live slippage visible at this n.

## 2. The four real causes of the "divergence"

**(a) ERA MIX — the big one.** VPS3 twin cumulative: **+$18.29 / ~48 real exits (+$0.37/tr at $5)**. But the
exit-type-by-day table shows its profitable era = **06-04→06-07 when TP@0.65 was still ON** (13 `scalp_tp065`
exits at ≈+$1.1–1.5 each ≈ most of the cumulative profit). Ireland live only began 06-08 — *after* TP-off.
Comparing live's post-TP fires vs shadow's TP-era cumulative = comparing different strategies in different weeks.
**Same-window (since 06-08): VPS3 = 8 exits, −$0.35 net ($5) vs live = 7 exits, −$0.795 ($1) — both slightly
negative, no mystery.**

**(b) STOP drag in live's window.** Live: 3/7 exits were stops totalling **−$0.726 = 91% of all live losses**
(avg −$0.24/stop on $1 = −24%/stake; worst −32.6%). VPS3 same window: 1 stop −$1.196 ($5). This is the live
confirmation of the corrected-harness verdict (stop = significantly negative) — **stop removed on both hosts
2026-06-11**, so this drag ends now.

**(c) CONFIG DRIFT — VPS3 15m runs maker-exit, live runs taker.** Since ~06-08 VPS3's twin logs
`scalp_maker_lift` exits (maker@0.60 + taker fallback — the "15m maker winner" config). Ireland live is
taker-+60 only. The maker-exit's offline support was REVERSED by the corrected harness (+0.42 → −0.07 ns), so
the twins aren't even running the same exit policy. Either revert VPS3 15m to pure taker +60 (clean twin
parity) or accept they're different experiments.

**(d) ACCOUNTING artifacts.** (i) Ireland paper twin's counterfactual exits carry **NULL `pnl_usd`** → any
dashboard summing events.pnl_usd shows paper=0 vs live=−$0.79 → fake divergence. (ii) VPS3 double-logs each
exit (a second row ~15 min later with null pnl) → raw row counts inflate ~2×. (iii) Sizing $5 vs $1 scales
everything 5×. Always compare per-$-of-stake, same window, same config.

## 3. Per-slot live vs VPS3 (5 common slugs, per-$1 normalized)
| slug (slot) | live exit / pnl per $1 | VPS3 exit / pnl per $1 | note |
|---|---|---|---|
| …0961400 | time60 −0.019 | time60 −0.074 | live sold at better bid |
| …1011800 | time60 −0.059 | time60 −0.078 | ≈same |
| …1016300 | time60 +0.083 | time60 +0.042 | ≈same |
| …1081100 | stop −0.185 | time60 −0.100 | live entered 5¢ worse (0.55 vs 0.50) → stop triggered |
| …1113500 | stop −0.326 | stop −0.239 | both stopped |

## 4. Verdict + actions
- **No bug.** Live execution is spec-true; fills match paper/shadow.
- The honest live read: time60-only exits are ~flat (−$0.017/tr on $1, n=4) — statistically nothing at this n;
  the stop caused the losses and is gone. Keep accruing toward the ≥200-fire gate; judge per-$ CI.
- **Decide:** revert VPS3 15m scalp sleeves from maker-exit to pure taker +60? (maker evidence is dead
  post-bugfix; reverting restores twin parity). Until then, expect live≠shadow on 15m by design.
- Dashboard hygiene: exclude `scalp_hold_counterfactual` (null-pnl) rows and dedup the double-logged exits
  before any live-vs-shadow PnL comparison.
