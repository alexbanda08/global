# BTC V3 Family Deep Dive + SOL V4 Deployment Audit — 2026-05-04

**Sample window:** 2026-05-03 → 2026-05-04 17:31 UTC (~1.5 days since TV agent deployed Option B patch).
**Source:** `data/v4/shadow_trades_2026_05_02/{vps2,vps3}.csv`.
**Spec audited against:** `strategy_lab/reports/V3_PATCH_OPTION_B_SPEC.md` and `V3_1_PATCH_SPEC_2026_04_30.md`.

---

## TL;DR

1. **BTC V3-family is a clean nested filter cascade.** v4 ⊆ v3_2 ⊆ v3 with 100% subset overlap on (5min-slot, signal) keys. The variants are not independent — V3.2/V4 are V3 with extra rejections.
2. **The hit-rate ladder (65 → 80 → 84.6%) is real but comes from removing trades, not adding alpha.** V3.2 dropped 25 V3 trades that were **+56% hit / +$50 PnL** — i.e. it is throwing out small winners along with the losers.
3. **V4's incremental quantile filter (vs V3.2) is effectively a no-op** — removes only 2 trades, total -$1.46.
4. **Hour blocklist is mixed**: hours 1 and 22 deserve the block (negative on V3 baseline), but hour 16 was actually +66.7% hit / +$22 — **the gate is removing a winner-hour from BTC**.
5. **SOL V3-family is broken**: spec required 4 SOL sleeves (`v3, v3_1, v3_2, v4`); only `v3_2` actually fires. Three SOL sleeves are silent for 1.5 days despite the V3.2 SOL handler firing 5 times — suggests **sleeve registration / mode wiring bug for SOL**.

---

## 1. BTC V3 family — fire breakdown

| Variant | Fires | DistinctMarkets | Hit% | PnL $ | Avg/trade | UP hit% | DOWN hit% |
|---|---:|---:|---:|---:|---:|---:|---:|
| v3   | 40 | 40 | 65.0% | +256.57 | +6.41 | 70.4% (n=27) | 53.8% (n=13) |
| v3_1 | 20 | 20 | 65.0% | +130.09 | +6.50 | 68.8% (n=16) | 50.0% (n=4)  |
| v3_2 | 15 | 15 | 80.0% | +206.55 | +13.77 | 76.9% (n=13) | 100% (n=2)   |
| v4   | 13 | 13 | 84.6% | +208.01 | +16.00 | 81.8% (n=11) | 100% (n=2)   |

### Subset proof (variants are nested, not independent)

| Subset | Overlap | %  | Variant-only fires |
|---|---|---|---|
| v4 ⊆ v3_2  | 13/13 | 100% | 0 v4-only |
| v3_2 ⊆ v3 | 15/15 | 100% | 0 v3_2-only |
| v3_1 ⊆ v3 | 20/20 | 100% | 0 v3_1-only |
| v4 ⊆ v3_1 | 13/13 | 100% | 0 v4-only |
| v4 ⊆ v3   | 13/13 | 100% | 0 v4-only |

**Implication:** V3 baseline is the universe; V3.1, V3.2, V4 are subsets. Per-variant samples are NOT independent — they share exact trades. The hit-rate ladder reflects which subset of V3 trades each gate keeps, not separate signal alpha.

---

## 2. What did V3.2 actually filter out?

V3.2 keeps 15 of V3's 40 fires. The **25 trades V3.2 rejected** had:

| Metric | Value |
|---|---|
| n | 25 |
| Hit% | 56.0% |
| PnL $ | +50.03 |
| Avg/trade | +$2.00 |

**The rejections include net winners.** V3.2's 80% hit rate looks great compared to V3's 65% — but the marginal trades V3.2 dropped were winners (+$50). V3 baseline aggregate ($256.57 / 40 = $6.41/trade) is essentially unchanged whether you measure on V3 or V3.2 + filtered residuals (V3.2 = $206.55, residuals = $50.03; sum = $256.58, identical to V3 by construction).

**Translation:** V3.2's "improvement" is really concentration of capital on fewer trades with higher per-trade winners. **Total PnL is the same ± rounding.** The benefit is variance reduction and capital efficiency, not raw alpha.

V4 vs V3.2: removes 2 more trades (+50.0% hit, -$1.46 total). The V3.1 quantile filter inside V4 is effectively a no-op on the BTC side over this window.

---

## 3. Hour blocklist audit — is {1, 16, 22} the right set?

V3 baseline fires per UTC hour:

| Hour | n | Hit% | PnL $ | Avg | Status | Verdict |
|---:|---:|---:|---:|---:|---|---|
| 1  | 2 | 0%   | -50.00 | -25.00 | BLOCKED | ✓ block correct |
| 2  | 1 | 100% | +23.54 | +23.54 |  | keep |
| 3  | 1 | 0%   | -25.00 | -25.00 |  | candidate to block |
| 4  | 1 | 100% | +23.54 | +23.54 |  | keep |
| 5  | 1 | 100% | +23.54 | +23.54 |  | keep |
| 7  | 1 | 0%   | -25.00 | -25.00 |  | candidate to block |
| 10 | 2 | 0%   | -50.00 | -25.00 |  | candidate to block |
| 11 | 1 | 100% | +23.54 | +23.54 |  | keep |
| 12 | 3 | 100% | +68.80 | +22.94 |  | KEEP (best) |
| 13 | 4 | 75%  | +44.69 | +11.17 |  | keep |
| 14 | 5 | 80%  | +68.23 | +13.65 |  | keep |
| 15 | 8 | 75%  | +89.56 | +11.20 |  | KEEP (high volume) |
| 16 | 3 | 67%  | +22.08 | +7.36  | BLOCKED | **❌ block removing winner** |
| 17 | 3 | 67%  | +21.97 | +7.32  |  | keep |
| 20 | 1 | 100% | +23.54 | +23.54 |  | keep |
| 22 | 2 | 50%  | -1.46  | -0.73  | BLOCKED | marginal — defensible |
| 23 | 1 | 0%   | -25.00 | -25.00 |  | candidate to block |

**Caveat: BTC sample is tiny (40 fires, 1.5 days).** Hours with n=1 are noise. Hours with n≥3:
- 12, 13, 14, 15: top performers, kept ✓
- 16: 66.7% / +$22 over n=3 — **the block is removing this winner-hour for BTC**
- 22: 50% / -$0.73 over n=2 — marginal

**V3.2 hour gate verified working:** zero fires at hours 1, 16, 22 ✓ (block enforced).

**Recommendation:**
- For BTC specifically, hour 16 looks like a winner-hour. The blocklist may be over-applied (blocklist was derived from cross-asset / SOL-driven analysis).
- Hours 3, 7, 10, 23 are candidates to ADD to the blocklist (all 0% on small n) — but need 30-day OOS before changing.
- DO NOT modify the gate yet — sample is too small.

---

## 4. Daily PnL trajectory

| Date (UTC) | v3 | v3_1 | v3_2 | v4 |
|---|---:|---:|---:|---:|
| 2026-04-30 | +92.70 | 0 | 0 | 0 |
| 2026-05-01 | +64.85 | 0 | 0 | 0 |
| 2026-05-03 | -2.92  | +22.08 | +23.54 | +23.54 |
| 2026-05-04 | +101.95 | +108.01 | +183.01 | +184.47 |

**Observations:**
- v3_1, v3_2, v4 first fired on 2026-05-03 — confirms TV agent deployed Option B around that date.
- 2026-05-03 was lean (4 V3 fires, 1 each for v3_1/v3_2/v4).
- 2026-05-04 is the first full day of parallel operation — v3_2 ($183) and v4 ($184) both top v3 ($102). The "V4 wins" headline is a single-day result.
- v3_2 and v4 are nearly identical on 05-04 ($183 vs $184) — V4's incremental filter is a no-op vs V3.2 today.

---

## 5. SOL V4 deployment audit (the user's question)

### Was SOL v4 supposed to deploy?

**Yes.** Per `V3_PATCH_OPTION_B_SPEC.md` lines 247–254:

```python
_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    # ... existing 15 sleeves (V1 + V2 + V3) ...
    "poly_updown_btc_5m_v3_1", "poly_updown_eth_5m_v3_1", "poly_updown_sol_5m_v3_1",  # V3.1
    "poly_updown_btc_5m_v3_2", "poly_updown_eth_5m_v3_2", "poly_updown_sol_5m_v3_2",  # V3.2
    "poly_updown_btc_5m_v4",   "poly_updown_eth_5m_v4",   "poly_updown_sol_5m_v4",    # V4
)
```

The spec also lists `TV_POLY_STRATEGY_MODES=volume,sniper,v3,v3_1,v3_2,v4` for VPS3 (line 284).

### What actually fires (this 1.5-day sample)

| Sleeve (spec'd) | Fires observed | Status |
|---|---:|---|
| `poly_updown_sol_5m_v3`    | **0** | ❌ MISSING |
| `poly_updown_sol_5m_v3_1`  | **0** | ❌ MISSING |
| `poly_updown_sol_5m_v3_2`  | 5 | ✓ deployed |
| `poly_updown_sol_5m_v4`    | **0** | ❌ MISSING |

### Why missing? Three hypotheses

**H1 — Sleeve registration bug.** The TV agent added `sol_5m_v3_2` to `_POLY_UPDOWN_SLEEVE_IDS` but skipped the other three SOL entries. Easy to verify: `grep -E "sol_5m_(v3|v3_1|v4)" backend/app/api/bots.py`.

**H2 — Mode-wiring bug.** All four sleeve_ids are registered, but the controller's mode branches for `v3`, `v3_1`, `v4` skip SOL entirely (e.g. an `if symbol != "SOL"` accidentally added in the v3/v3_1/v4 paths but not in v3_2).

**H3 — Quantiles too tight (legitimate zero-fire).** Per V3.1 spec line 134 ("ETH V3 / SOL V3 zero-fire problem: thresholds are q5 / q15-multi-h. Today's regime didn't trigger.") — V3 baseline SOL has hit-rate-tight quantiles (q15 DOWN, q8+multi-horizon UP) that legitimately may not fire.

**H1/H2 most likely** because:
- `sol_5m_v3_2` (uses BASE V3 quantiles for SOL) DID fire 5 times. By construction `sol_5m_v3` (also base V3 quantiles, no extra gates) **must** fire ≥5 times — V3.2 ⊆ V3 by design.
- Yet `sol_5m_v3` is silent. That contradicts the subset relationship → not a quantile issue, it's a deployment hole.

### Quick verification commands

```bash
# On VPS3 — check controller code for sol+v3 wiring
ssh vps3 'grep -nE "sol|v3_1|v4" /srv/trading-venue/backend/app/controllers/polymarket_updown.py | head -40'
# Check sleeve registration
ssh vps3 'grep -E "sol_5m_(v3|v3_1|v3_2|v4)" /srv/trading-venue/backend/app/api/bots.py'
# Check active strategy modes
ssh vps3 'grep TV_POLY_STRATEGY_MODES /etc/tv/tradingvenue.env'
# Check the live event stream for ANY SOL signal events suppressed at the gate
sudo -u postgres psql -d storedata -c "
  SELECT sleeve_id, COUNT(*) FROM trading.events
  WHERE kind LIKE 'poly_updown_%'
    AND data->>'symbol' = 'SOL'
    AND at > NOW() - INTERVAL '36 hours'
  GROUP BY sleeve_id ORDER BY 1;"
```

---

## 6. Action items (in priority order)

1. **CRITICAL — Run the four verification commands above** to confirm whether sol_5m_v3 / v3_1 / v4 sleeves are unwired (H1/H2) or just legitimately not firing (H3).
2. **If H1/H2 confirmed**, file a TV agent bug: deploy missing SOL handlers. Same controller path as `sol_5m_v3_2`.
3. **If H3 confirmed**, document the expected zero-fire behavior in NEXT_SESSION pointer doc and stop expecting SOL V4 PnL from this window.
4. **Hold off on hour blocklist edits** — BTC sample is too small (1.5 days, n=40). Wait for 7+ days before adjusting.
5. **Stop reporting BTC v4 84.6% hit as a separate result** — it's V3.2 with a no-op filter on this sample. Either report v4 as "= v3_2 within trial" or wait until the V3.1 quantile actually rejects more trades.
6. **The "V3.2 removes winners" finding** should reset expectations: the gates buy variance-reduction, not alpha. PnL contribution at $1/trade live will be modest. Confirm with operator before the live launch is scaled.

---

## 7. Files

- This report: `strategy_lab/reports/BTC_V3_DEEP_DIVE_2026_05_04.md`
- Patch spec (canonical): `strategy_lab/reports/V3_PATCH_OPTION_B_SPEC.md`
- V3.1 origin: `strategy_lab/reports/V3_1_PATCH_SPEC_2026_04_30.md`
- V3.2 deploy spec: `strategy_lab/reports/V3_2_DEPLOY_SPEC_2026_04_30.md`
- Shadow data: `data/v4/shadow_trades_2026_05_02/{vps2,vps3}.csv`
- Prior shadow analysis: `strategy_lab/reports/SHADOW_ANALYSIS_2026_05_04.md`
