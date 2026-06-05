# TV-AGENT SPEC — Oracle-Determinism Settlement Shadow Sleeve (2026-06-05)

**Type:** new shadow (paper-only) sleeve — structural/settlement edge, NOT prediction.
**Evidence:** `ORACLE_SETTLEMENT_SELECTOR_2026_06_05.md`. ~18% of slugs are decided by Chainlink ≥99.6% at
T-60s; the poly price of the oracle-winner LAGS the oracle (+1.35%/share print EV, CI excludes 0), concentrated
in CHEAP-but-decided slugs. On the fillable subset it stays +EV (win 92–100% at vwap~0.85, +$1.8–4.2/tr) —
unlike favorite-longshot it does NOT flip negative on ask-walk fills. BUT it's UNDERPOWERED offline (3–12%
fill, 9–42 fills/43d, CIs include 0). **Purpose of this sleeve: accrue forward fills to settle the power question.**

## Strategy (one line)
At **T-60s before slot_end**, if the Chainlink oracle has effectively decided the outcome
(`|chainlink_price − strike| / strike ≥ 15bp`) AND the oracle-implied winner token is still cheap
(best ask `< 0.95`), BUY that winner (taker, $5), HOLD to resolution.

## New gate — `g_oracle_decided` (add to `app/strategies/polymarket/sniper_v5_gates.py`)
Direction is **set by the oracle** (dynamic), so this gate must drive the fire side.
```python
def g_oracle_decided(direction, fire_us, *, book_mirror=None, token_id_up="", token_id_dn="",
                     chainlink_price=None, strike_price=None, dist_bp_min=15.0, max_ask=0.95, **_kw) -> bool:
    """Fire iff oracle is decided AND the oracle-winner is still cheap.
      strike      = chainlink price at slot_start (captured per slug at window open)
      chainlink   = current live RTDS 'crypto_prices_chainlink' value at fire
      winner side = 'Up' if chainlink > strike else 'Down'  (MUST equal `direction`)
      decided     = |chainlink - strike|/strike*1e4 >= dist_bp_min
      cheap       = best ask of the winner token < max_ask
    """
    if chainlink_price is None or strike_price is None: return False          # warm-up / no strike → no fire
    dist_bp = abs(chainlink_price - strike_price) / strike_price * 1e4
    if dist_bp < dist_bp_min: return False
    winner = "Up" if chainlink_price > strike_price else "Down"
    if direction != winner: return False                                      # sleeve fires the winner side only
    tok = token_id_up if winner == "Up" else token_id_dn
    book = (book_mirror or {}).get(tok)
    if not book or not book.get("asks"): return False
    return float(book["asks"][0]["price"]) < max_ask
```
- **Requires two live inputs not used by the scalp:** (1) the Chainlink RTDS channel
  `crypto_prices_chainlink` (sponsored key per Polymarket docs — confirm the live engine subscribes; canonical
  already captures it 1s), and (2) the **strike** = the Chainlink value at `slot_start`, captured/stored per slug
  at window open (the same value the market settles against). Add strike capture to the per-slug context if not present.
- Register in `__all__`; wire `chainlink_price`/`strike_price` into `_build_gate_kwargs` for this sleeve.

## New sleeves (add to `app/strategies/polymarket/sniper_v5_sleeves.py`)
Fire at T-60s before slot_end → `offset = window_s − 60` (5m → 240s, 15m → 840s). Direction BOTH (gate picks the
winner side). HOLD to resolution (no SCALP_EXIT). $5, one-shot/slug, paper-only.
```python
*(
    SniperV5Sleeve(
        sleeve_id=f"shadow_oracle_settle_{_sym.lower()}_{_tf}",
        asset=_sym, tf=_tf, direction="BOTH",
        offsets=(_off,),                       # window_s - 60
        spread_filter=Decimal("0.05"),
        notional_usd_override=Decimal("5.0"),
        one_shot_per_slug=True,
        # exit: HOLD to resolution (no exit_policy / no scalp_exit)
        gates=(
            GateRef(g_oracle_decided,
                    (("dist_bp_min", "15.0"), ("max_ask", "0.95")),
                    "g_oracle_decided(15bp,ask<0.95)"),
        ),
    )
    for (_sym, _tf, _off) in [("BTC","5m",240), ("ETH","5m",240), ("SOL","5m",240),
                              ("BTC","15m",840), ("ETH","15m",840), ("SOL","15m",840)]
),
```
- Include SOL: the cheap-decided mispricing was strongest on ETH/SOL (thin books), so SOL is worth shadowing here
  even though the $25 taker scalp can't fill SOL.
- `shadow_` prefix → shadow log / paper-only. Distinct event_type (e.g. `sleeve_oracle_settle`) so it never
  double-counts in the main WR/PnL.

## Validation / acceptance
- Smoke: confirm fires only when `|dist|≥15bp` and winner ask<0.95; confirm direction == oracle winner.
- Sanity: realized win rate of fires should be ~92–100% (oracle was decided). If WR << 0.9, the RTDS feed is
  lagging the settle print — investigate feed fidelity before trusting (we verified canonical fidelity = 1.0,
  but the LIVE WS feed may differ; this sleeve is also a live fidelity probe).
- Graduation: ≥100–200 forward fills + bootstrap $/tr CI > 0 (per $5 stake) before any real capital.

## Host / notes
VPS3. Needs live `crypto_prices_chainlink` subscription + per-slug strike capture at slot_start. Hold-to-settle
fee = 0.07 winner-only (re-verify live). Paper-only until graduation. This is the first STRUCTURAL/settlement
slug-selector — distinct from the lag-taker scalp (which is a Binance-momentum signal).
