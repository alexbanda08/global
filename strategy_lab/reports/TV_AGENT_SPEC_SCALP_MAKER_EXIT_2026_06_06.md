# TV-AGENT SPEC — Scalp MAKER-EXIT (maker-TP + taker-+60 fallback), SHADOW-first (2026-06-06)

**Type:** new EXIT mode for the **Polymarket** scalp + shadow validation sleeves. **Do NOT flip the live-capital sleeve yet.**
**POLYMARKET ONLY** — the Kalshi scalp (`kalshi_scalp_exit_btc_15m_d3_v1`) does NOT benefit from maker exit
(no Kalshi maker rebate + tight spread + 15m runway → maker WORSE; `kalshi_scalp_maker_exit_2026_06_06.py`). Keep Kalshi taker.
**Evidence:** `MAKER_EXIT_SIM_2026_06_06.md` — maker SELL@offer + taker-+60 fallback beat the pure-taker-+60 exit
by **+$0.42/tr (CI [+0.02,+0.82])** on the gated scalp. BUT the sim's fill model is OPTIMISTIC (counts a fill on
any buy-trade ≥ target; **ignores queue position**) and is in-sample. The ONLY way to get the true fill rate is
to run it live in shadow vs the pure-+60 control. This spec implements the exit mode + the shadow A/B.

## Prereq: prerequisite fix first
Apply `TV_AGENT_SPEC_SCALP_DISABLE_TP_2026_06_06.md` first — the pure-taker-+60 (no TP/stop) is the CONTROL
this maker-exit must beat. Both must run side-by-side.

## The exit logic to implement
Today `exit_policy="SCALP_EXIT"` does: poll → at `deadline_us = fire_us + scalp_exit_offset_s(=60)*1e6` →
TAKER market-sell (walk the bid) for the full position. Add a MAKER mode:

New sleeve fields on `SniperV5Sleeve`:
- `scalp_exit_mode: str = "taker"`  → `"taker"` (current, control) | `"maker_fixed"` | `"maker_peg"`
- `scalp_maker_tp: Decimal = Decimal("0.65")`  (offer price for `maker_fixed`)
- `scalp_maker_repost_s: int = 5`  (re-quote cadence for `maker_peg`)
- (keep `scalp_exit_offset_s = 60` = the hard deadline; keep TP/stop OFF per the disable spec)

Exit state machine in `maybe_scalp_exit` / `_scalp_exit_then_resolve` (engine/poly_sniper_v5_loop + controller):
1. **On entry-fill** (position opened at fire): if `scalp_exit_mode` starts with `maker`, **POST a resting
   limit SELL (post-only / GTC)** for the full `fill_shares`:
   - `maker_fixed`: price = `scalp_maker_tp` (0.65).
   - `maker_peg`: price = **current best ASK** of the lead token (join the offer). Re-quote: every
     `scalp_maker_repost_s`, if best_ask moved, **cancel + repost at the new best_ask** (trail up — this avoids
     the fixed-target "cap" and captures bigger moves).
2. **On each poll**: check the resting order's fill status.
   - Filled (full): record maker exit — sell price = the limit price, **fee = $0 (maker)**, **+ rebate** =
     `rebate_share × feeRate × p × (1−p) × shares` (use the live maker rebate share — re-verify on the Poly
     account dashboard; spec used 0.20). Emit `kind='poly_updown_scalp_exit'` with `exit_mode='maker'`,
     `trigger='maker_lift'`, the fill price, fee=0, rebate.
   - Partial fill: keep the remainder resting; track filled qty.
3. **At `deadline_us` (+60s)**: **cancel any unfilled remainder** and **TAKER market-sell** it (walk the bid,
   the current behavior) — `exit_mode='taker_fallback'`, `trigger='time60'`, taker fee charged. (So a partially
   filled order = part maker, part taker.)
4. **Book empty / no quotes**: existing hold-to-resolution fallback unchanged.

CRITICAL: the maker order lifecycle (post-only limit, track fill, cancel/replace, deadline cancel→market) must
use the Polymarket CLOB limit-order path (the mint-and-sell maker code already posts limit orders — reuse that
order-management plumbing). The current scalp exit only does market sells; this adds resting-order management.

## Deploy as SHADOW A/B (paper-only) — do this, NOT a live flip
Clone the deployed scalp sleeves with the new exit mode, paper-only, to measure live fill rate vs the control:
```python
# control already exists = the pure +60 taker sleeves (post-disable-TP). Add maker variants:
*(
    SniperV5Sleeve(
        sleeve_id=f"shadow_scalp_exit_{_sym.lower()}_{_tf}_d3_makerpeg_v1",
        asset=_sym, tf=_tf, direction="BOTH", offsets=(5,),
        spread_filter=_SPREAD_LAGV2, notional_usd_override=Decimal("5.0"),
        one_shot_per_slug=True, exit_policy="SCALP_EXIT",
        scalp_exit_offset_s=60, scalp_exit_mode="maker_peg",   # peg-to-ask + taker-+60 fallback
        entry_band=(0.0, 0.55),
        gates=(GateRef(g_oracle_lag_with, (("lo_bps","3.0"),("hi_bps","12.0")), "g_oracle_lag_with(3.0,12.0)"),),
    )
    for _sym in ("BTC","ETH") for _tf in ("5m","15m")
)
# optionally a _makerfixed_v1 arm (scalp_maker_tp=0.65) to A/B fixed vs peg.
```
Run **three arms side-by-side on the same fires**: `taker` (control, +60 pure), `maker_peg`, `maker_fixed`.
The `shadow_` prefix → paper. They evaluate the SAME signals so it's a clean within-fire A/B.

## What the shadow A/B must log (to settle the open question)
Per scalp exit: `exit_mode`, `trigger` (maker_lift / time60 / partial), **maker fill rate** (% of position filled
as maker vs taker-fallback), fill price, realized $/tr. The KEY metric = **maker fill rate** (the sim assumed
~100% on any lift; real queue position will be lower) and **maker $/tr vs taker-control $/tr on matched fires**.

## Graduation before ANY live-capital switch
Flip the live `shadow_scalp_exit_btc_5m_d3_v1` exit to maker ONLY after the shadow A/B shows, on ≥150 matched
forward fires: **maker $/tr > taker-control $/tr with bootstrap CI > 0**, AND maker fill rate is materially >0
(if fill rate ≈ 0 because of queue position, maker exit is moot — stay taker). Until then: live stays **pure +60
taker** (the disable-TP spec).

## Caveats / notes
- Maker-exit edge in backtest is fill-rate-dependent; queue position is the make-or-break and is ONLY observable
  live → that's why shadow-first.
- `maker_peg` (trail the ask) is preferred over `maker_fixed` (caps at 0.65). A/B both.
- Re-verify the maker rebate share on the Poly account dashboard before crediting rebate in shadow PnL.
- Exit time stays **+60** (paired-bootstrap-verified tied-optimal; do NOT change to 45).

## Files
- `MAKER_EXIT_SIM_2026_06_06.md`, `SCALP_DYNAMIC_EXIT_2026_06_04.md`, `TV_AGENT_SPEC_SCALP_DISABLE_TP_2026_06_06.md`,
  `SCALP_LIVE_AUDIT_2026_06_06.md`. Maker order plumbing: the mint-and-sell limit-order path.
