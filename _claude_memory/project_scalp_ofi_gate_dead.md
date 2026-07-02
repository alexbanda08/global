---
name: project_scalp_ofi_gate_dead
description: "Binance 1s taker-OFI gate on the lag-scalp tested 2026-06-16 — DEAD (no dose-response, gating lowers $/tr); scalp edge is INVERSELY related to flow intensity (thin moves lag more)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 95da9a9e-f870-4e84-8fd8-e3dfce1d3760
---

Tested the 5-lens audit's #2 "free win": gate the deployed lag-scalp on Binance taker-order-flow-imbalance (OFI = 2·Σtaker_buy/Σvol−1 over the [ss,ss+5s] signal window, signed to the lead). `scalp_ofi_gate_2026_06_16.py`, report `SCALP_OFI_GATE_RESULT_2026_06_16.md`.

**DEAD — no edge.** Production window (Apr22+; `klines_1s.taker_buy_base` only on live-WS rows, vision-backfill NULL → OOS BBO window unusable for OFI). 293 gated fires, 125 with OFI. Dose-response by ofi_aligned quintile NON-monotone (Q1 +2.39 / Q2 −1.26 / Q3 +2.62 / Q4 +1.84 / Q5 +0.92); gating ofi>0 LOWERS $/tr (base +2.23 → +1.12). Every per-coin cell ofi>0 ≤ base.

**Mechanistic takeaway (the useful bit):** fires WITH computable OFI (more 1s volume in the signal window) are WORSE (+1.1) than thin/no-OFI fires (+2.2) → **the scalp edge is INVERSELY related to flow intensity** — thin low-volume moves leave the Poly book lagging more (the lag the scalp captures). "Keep high-flow" is backwards. At 5s horizon the aggressor flow is already in the price (cause = consequence), so OFI adds no orthogonal info.

**Why:** prevents re-testing OFI/flow gates on the scalp. The scalp profits from EXECUTION LAG, not move-persistence prediction — don't gate it on flow/CVD/aggressor signals (also see Poly-CVD priced-in-trap). Links [[project_5lens_audit_2026_06_12]], [[project_scalp_exit_config]].
**How to apply:** OFI/flow gating on the lag-scalp = no edge; taker_buy cols only populated Apr22+ live-WS. Caveat: in-sample window, 43% coverage, but the gate-vs-base comparison is relative so the negative holds.
