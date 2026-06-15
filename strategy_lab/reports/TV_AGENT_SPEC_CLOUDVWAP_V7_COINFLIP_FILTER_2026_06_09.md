# TV-AGENT SPEC — cloud_vwap_v7: exclude the 0.49-0.51 coinflip dead-zone (2026-06-09)

**Goal:** add a thin entry-vwap dead-zone filter to `eth_5m_cloud_vwap_hurstmp_v7` so it does
NOT fire when the book-walk entry vwap is in **(0.49, 0.51)** — a pure-coinflip pocket with no
edge. Additive gate (does not touch the shared `g_entry_vwap_in_band`). Apply on BOTH hosts
(VPS3 shadow + Ireland live) so the shadow twin stays identical to live.

## Evidence (shadow OOS, May29→Jun09, $5 stake)
The (0.49, 0.51) vwap band on `cloud_vwap_hurstmp_v7`:
- n=7, WR 43%, **$/tr −0.789, total −$5.5** — net loser (50/50 market = no edge).
- Removing ONLY this band (keep |vwap−0.5| ≥ 0.01): n 654→647, $/tr **+0.367 → +0.379**,
  total **+239.8 → +245.3** (+$5.5), MaxDD ($1 net) −13.87 → −12.86, **Calmar 2.94 → 3.26**.
- Pure win: removes only losers, profit + risk both improve. (Wider bands cut profitable
  fires — do NOT widen beyond 0.49-0.51.)
- Analysis: `migration_2026_06_08/` (the cloud_vwap conviction-bucket sweep).

## Change — new additive gate
In `app/strategies/polymarket/sniper_v5_gates.py`, add (mirrors `g_entry_vwap_in_band`'s vwap
source `_entry_vwap_for_dir`, size 25.0):
```python
def g_entry_vwap_not_coinflip(
    direction: str, fire_us: int, *, slug: str, book_mirror: Any,
    token_id_up: str, token_id_dn: str, **_kw: Any,
) -> bool:
    """Skip the (0.49, 0.51) book-walk-vwap coinflip dead-zone — no edge, -0.79/tr in
    shadow OOS. Pass (True) outside the band; fail (False) inside or if vwap is None
    (fail-closed, same as g_entry_vwap_in_band)."""
    v = _entry_vwap_for_dir(
        direction, slug, fire_us, 25.0, book_mirror, token_id_up, token_id_dn,
    )
    if v is None:
        return False
    return not (0.49 < v < 0.51)
```

In `app/strategies/polymarket/sniper_v5_sleeves.py`, append the gate to the
`poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7` sleeve's `gates=(...)` tuple:
```python
        gates=(
            GateRef(g_tr_above_cloud, (("asset", "ETH"),), "g_tr_above_cloud(ETH)"),
            GateRef(g_entry_vwap_in_band, (), "g_entry_vwap_in_band"),
            GateRef(g_hurst_mp_trend_with, (("asset", "ETH"),), "g_hurst_mp_trend_with(ETH)"),
            GateRef(g_entry_vwap_not_coinflip, (), "g_entry_vwap_not_coinflip"),   # NEW
        ),
```
Deploy on **BOTH** hosts (`deploy/vps3` shadow + `deploy/ireland` live) and restart `tv-engine`
on each, so the live `_LIVE` sleeve and its shadow twin evaluate the identical gate set.

## Verify
- New skip reason appears for in-band fires: `g_entry_vwap_not_coinflip=False` in the eval logs
  (VPS3 `sniper_v5/*.jsonl`) / `trading.events` (Ireland).
- Placed fires now have entry vwap ≤ 0.49 or ≥ 0.51 (none in the 0.49-0.51 pocket).
- Fire rate drops only marginally (~1% of fires; ~7 over a 12d window).

## Rollback
Remove the `GateRef(g_entry_vwap_not_coinflip, ...)` line + restart. Reversible. The gate
function can stay (unused) or be removed.

## Caveats
- **Small sample (n=7)** behind the −0.789/tr — the DIRECTION (50/50 vwap = no edge) is sound,
  but the exact magnitude is noisy. Re-check as fires accrue; the filter is low-risk
  (removes ~1% of fires, all near coinflip).
- Threshold tuned on the SAME shadow data (mild in-sample). Keep it THIN (0.49-0.51); do not
  widen without forward validation (wider bands cut profitable fires — Calmar 2.66 at 0.45-0.55).
- Independent of the live↔shadow cloud-boundary direction flips (those slugs had vwap
  0.58-0.71, outside this band) — this filter does not address those.
