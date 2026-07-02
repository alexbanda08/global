---
name: project_synthetic_book_marginal
description: "synthetic-book \"buy YES = sell NO\" fill upgrade tested on scalp OOS — no-arb inert on priceable fires, only ~$6/day rescue uplift, NOT deployed"
metadata: 
  node_type: memory
  type: project
  originSessionId: 95da9a9e-f870-4e84-8fd8-e3dfce1d3760
---

Tested the "6 edges" author (b945) technique-2 ("buying YES == selling NO; check the other side's depth") as a fill-engine upgrade on the scalp, clean OOS Mar30-Apr21, 6 coins. Result: **real but marginal, NOT deployed.**

- **No price improvement on normal fires:** `mean(ev_A − ev_B) = +0.0000` across all 1305 gated fills. No-arb guarantees `ask_lead ≤ 1 − bid_opp` whenever the lead ask exists → the synthetic route can NEVER undercut a fillable book. The "better price on the other side" half is inert.
- **Only value = rescued fires:** synthetic fires on +23 slugs (+1.8%) that lead-only skipped (lead ask missing / spread >5¢ but opp bid made effective spread tradeable). Rescued fires +$5.95/tr CI[+2.59,+9.47] (non-junk). Pooled $/tr +1.68→+1.81, t 5.16→5.66, never worse on any coin.
- **Operationally marginal:** 23×$5.95 ≈ $137 over 22d/6coins ≈ **$6/day**, before gas. Capturing a rescue live = mint set + dump opp leg = 2 on-chain ops/fire → gas eats it. Verdict: keep `fill_at_book` lead-only; did NOT modify engine_v2.
- Technique-1 (pre-mint inventory) = [[project_b945_thread_parked]]'s already-decoded ≤0 maker strategy; relocates taker-fill problem to maker-fill problem, can't rescue the lag-scalp (needs taker immediacy).

**Why:** avoids re-testing this article; the synthetic walk only becomes free-to-capture IF pre-mint inventory (oracle-gated maker test) is ever deployed.
**How to apply:** reference harness `strategy_lab/directional/scalp_synth_book_2026_06_12.py` (BBO A/B, uses [[project_scalp_exit_config]] +60s pure time-sell + scalp_fill_lib_2026_06_10). Don't wire synthetic into production for the taker scalp.
