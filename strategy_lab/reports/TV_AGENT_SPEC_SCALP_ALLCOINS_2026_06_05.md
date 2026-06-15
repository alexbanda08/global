# TV-AGENT SPEC — Exit-Scalp shadow sleeves for ALL validated coins (2026-06-05)

**Type:** new shadow (paper-only) sleeves — extend the deployed BTC/ETH exit-scalp to **SOL, DOGE, BNB**.
**Strategy:** the most-validated edge in the project. Chain: in-sample (+$2.7–5.6/tr) → Deflated Sharpe (pass)
→ live shadow (btc_5m_v1 +$4.49/tr) → **disjoint-window OOS PASS** (`SCALP_OOS_PASS_2026_06_05.md`):
BTC +$2.38, ETH +$1.92, SOL +$2.16, **DOGE +$1.40** (all gated CI>0 on Mar30/Apr6→Apr21, disjoint from search).
BNB +$1.39 directionally but thin/underpowered.

## What the scalp is (unchanged)
delta_bps = |binance-1s 5s return| at slot_start; fire @ slot_start+5s; lead = sign(ret); buy the lead token
$X taker (spread≤0.05); **SELL on the book at +60s** (`exit_policy="SCALP_EXIT"`, `scalp_exit_offset_s=60`);
gated cell `entry_band=(0.0,0.55)`; gate `g_oracle_lag_with(lo,hi)` (δ≥3 `(3,12)` / δ≥5 `(5,12)`).

## Per-coin validation + deploy decision
| coin | OOS gated $/tr (CI) | live L25 fill at $25 | deploy |
|---|---|---|---|
| BTC | +2.38 [0.62,4.09] | OK (live) | already live |
| ETH | +1.92 [0.53,3.33] | OK (live) | already live |
| SOL | +2.16 [1.03,3.25] | **thin (0.5% at $25 in main window!)** | **$5 only** (BBO OOS fill was optimistic) |
| DOGE | +1.40 [0.19,2.61] ✓ | unknown live | **$5** (validated, thinner market) |
| XRP | +2.20 [0.63,3.76] ✓ | unknown live | **$5** (validated, on par with BTC/ETH) |
| BNB | +1.39 [−2.29,5.10] thin | unknown live | **$5, accrue power** |

## New sleeves (add to `app/strategies/polymarket/sniper_v5_sleeves.py`)
Mirror the existing scalp generator; add SOL/DOGE/BNB at **$5** (thin-book friendly), δ≥3 and δ≥5, gated v1
(entry_band 0–0.55) + control (no band). Exit +60s, one-shot/slug, BOTH, paper-only (`shadow_` prefix).
```python
*(
    SniperV5Sleeve(
        sleeve_id=f"shadow_scalp_exit_{_sym.lower()}_{_tf}{_dl}{_ctl}",
        asset=_sym, tf=_tf, direction="BOTH",
        offsets=(5,),
        spread_filter=_SPREAD_LAGV2,
        notional_usd_override=Decimal("5.0"),          # $5 for new/thin coins
        one_shot_per_slug=True,
        exit_policy="SCALP_EXIT",                       # scalp_exit_offset_s=60 default
        entry_band=None if _ctl == "_control_v1" else (0.0, 0.55),
        gates=(GateRef(g_oracle_lag_with,
                       (("lo_bps", "3.0" if _dl == "_d3" else "5.0"), ("hi_bps", "12.0")),
                       f"g_oracle_lag_with({'3.0' if _dl=='_d3' else '5.0'},12.0)"),),
    )
    for _sym in ("SOL", "DOGE", "XRP", "BNB")
    for _tf in ("5m", "15m")
    for _dl in ("_d3", "")           # "" = δ≥5
    for _ctl in ("_v1", "_control_v1")
),
```
(IDs e.g. `shadow_scalp_exit_doge_5m_d3_v1`, `shadow_scalp_exit_sol_5m_v1`, etc.)

## PREREQUISITES
1. ✅ **Live Polymarket markets exist** for SOL/DOGE/BNB up/down — CONFIRMED tradeable by operator 2026-06-05.
   (Confirm `poly_market_discovery` resolves the live `clob_token_up/dn` per slug for each coin's 5m/15m series.)
2. 🔴 **Live binance spot signal** for DOGE/BNB (the lag source). Engine already has BTC/ETH/SOL spot-ws; **add
   DOGE/BNB binance spot-ws 1s** to the live feed if missing. Without the live 1s price, `g_oracle_lag_with`
   can't compute delta for these coins. (SOL signal already present.)
3. 🔴 **L25 BookMirror** subscribed for the new coins' tokens (entry fill + the +60s book-sell read).

## Caveats / guardrails
- **SOL/BNB fill risk:** SOL up/down L25 filled only ~0.5% at $25 in the main window (thin books); the OOS BBO
  fill (top-of-book) was optimistic. Deploy at **$5**, and watch the live `qty_compute_failed` / underfill rate —
  if fill rate is near-zero, the coin isn't tradeable regardless of edge.
- **Time-of-day gate is BTC/ETH/SOL-specific** — the 22–02 UTC boost did NOT replicate on DOGE/BNB. Do NOT apply
  a TOD gate to DOGE/BNB. (TOD gate spec for BTC/ETH/SOL = `TV_AGENT_SPEC_SCALP_TOD_GATE_2026_06_05.md`.)
- Exit stays **+60s** (BTC/ETH/SOL) per `SCALP_DYNAMIC_EXIT`. New coins: keep +60 (no per-coin exit tuning yet).
- Paper-only until graduation: **≥200 forward `poly_updown_scalp_exit` fills + live-wallet bootstrap CI>0 per coin**.

## Validation / acceptance
- Each new `_v1` (gated) sleeve should, over forward fills, show $/tr > its `_control_v1` (the vwap<0.55 gate lift),
  matching the OOS/in-sample pattern. DOGE is the priority confirm (already OOS-validated); SOL/BNB are fill-risk
  + power probes.
- Compare live fill rate per coin to flag thin-book coins early.

## Files / evidence
- OOS: `SCALP_OOS_PASS_2026_06_05.md` · runner `scalp_oos_bbo_2026_06_05.py`.
- Existing live scalp sleeves (BTC/ETH) verified: `VPS3_SLEEVE_VERIFICATION_2026_06_05.md`.
- TOD gate (BTC/ETH/SOL only): `TV_AGENT_SPEC_SCALP_TOD_GATE_2026_06_05.md`.
