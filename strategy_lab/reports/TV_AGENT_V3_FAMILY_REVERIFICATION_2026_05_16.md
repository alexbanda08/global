# V3 Family Re-Verification — Controller is Correct, Prior Spec was Measurement Error

**Date:** 2026-05-16
**Author:** strategy-lab agent (alexandre.bandarra)
**Supersedes (partially):** `TV_AGENT_V3_FAMILY_DIFFERENTIATION_SPEC_2026_05_11.md`
**Status:** NO BUG. The v3 family dispatcher works as designed. Prior spec recanted.
**VPS3 controller HEAD:** `af58dec` (latest), file modified 2026-05-16 02:05 UTC (uncommitted slot_allowlist patch — unrelated to v3 family).

---

## TL;DR

The 2026-05-11 spec claimed v3 / v3_1 / v3_2 / v3_3 / v4 sleeves "collapse into 2 functional classes" because no `regime_blocked` / `hour_blocked` / `macro_2of3_fail` audit rows appeared in 14d. **That was a query bug, not a controller bug.** The prior query filtered on `event_time_us`, a column that doesn't exist in `trading.events` — every row was excluded. Re-running with the correct schema (`at` timestamp + `kind = 'poly_updown_signal'`) shows all expected gates are firing.

**Conclusion:** No TV agent fix required. v4 already differs from v3_1. Issue 3 (v3_2 ≡ v3_3 on BTC/ETH) is by design (per Phase 18.3 spec — v3_3's MH-AND filter is SOL-only) and not a defect.

---

## Evidence — 14d audit breakdown (2026-05-02 → 2026-05-16)

Source: `trading.events` on VPS3, `kind = 'poly_updown_signal'`. Recomputed 2026-05-16 03:50 UTC.

### BTC 5m

| sleeve | fires | regime_blocked | hour_blocked | macro_2of3_fail | wide_spread_skip | no_signal |
|---|---:|---:|---:|---:|---:|---:|
| v3   | 128 | 0  | 0  | 0  | 226 | 2847 |
| v3_1 | 109 | 19 | 0  | 0  | 226 | 2847 |
| v3_2 | 91  | 0  | 18 | 19 | 226 | 2847 |
| v3_3 | 91  | 0  | 18 | 19 | 226 | 2847 |
| v4   | 85  | 19 | 15 | 9  | 226 | 2847 |

### ETH 5m

| sleeve | fires | regime_blocked | hour_blocked | macro_2of3_fail | wide_spread_skip | no_signal |
|---|---:|---:|---:|---:|---:|---:|
| v3   | 19 | 0 | 0 | 0 | 149 | 3033 |
| v3_1 | 6  | 3 | 0 | 0 | 130 | 3062 |
| v3_2 | 10 | 0 | 5 | 4 | 149 | 3033 |
| v3_3 | 10 | 0 | 5 | 4 | 149 | 3033 |
| v4   | 3  | 3 | 2 | 1 | 130 | 3062 |

### SOL 5m

| sleeve | fires | hour_blocked | wide_spread_skip | no_signal |
|---|---:|---:|---:|---:|
| v3   | 190 | 0  | 196 | 2817 |
| v3_1 | 161 | 0  | 151 | 2891 |
| v3_2 | 206 | 40 | 368 | 2589 |
| v3_3 | 162 | 28 | 196 | 2817 |
| v4   | 136 | 25 | 151 | 2891 |

(SOL bypasses `macro_2of3` internally per controller, and v3_3's MH-AND filter is SOL-only — reducing v3_3 fires below v3_2.)

---

## Recantation by issue

### Prior Issue 1 — "V3.1 + V3.2 audit gates produce zero blocking audits in 14d" → **FALSE**

The empirical table above shows all five expected gate reasons present and firing:

- `regime_blocked`: 19 BTC + 3 ETH for both v3_1 and v4 (identical counts — confirms shared gate)
- `hour_blocked`: 18 BTC v3_2/v3_3, 15 BTC v4, 5 ETH v3_2/v3_3, 2 ETH v4, 40 SOL v3_2, 28 SOL v3_3, 25 SOL v4
- `macro_2of3_fail`: 19 BTC v3_2/v3_3, 9 BTC v4, 4 ETH v3_2/v3_3, 1 ETH v4 (SOL bypasses by design)

The gates also fire in expected stack order: v4 totals (`19 + 15 + 9 = 43` BTC) are slightly lower than the sum of v3_1 regime + v3_2 hour+macro (`19 + 18 + 19 = 56`) because earlier gates short-circuit. ✓

Per code at `polymarket_updown.py:334`:
```python
def _v3p_flag(name: str, default: str = "true") -> bool:
    return os.environ.get(name, default).lower() == "true"
```
Default is `"true"` → gates run unless explicitly disabled. Only `V3_2_LIQ_QUIET_ENABLED` defaults to `"false"` (per 2026-05-01 decision). Server env (`/etc/tv/*.env`) only overrides `TV_POLY_V3_SPREAD_FILTER_{BTC,ETH,SOL}`; no gate disable.

**Why the prior session missed this:** the diagnostic queries used `event_time_us` (a column from `oracle_prices_v2` / klines tables, not `trading.events`). That column does not exist in `trading.events`, so the query returned an empty set, falsely interpreted as "no gates firing".

### Prior Issue 2 — "v3_1 and v4 share their entire empirical signature" → **FALSE**

| asset | v3_1 fires | v4 fires | delta |
|---|---:|---:|---:|
| BTC | 109 | 85  | -24 (v3.2 hour+macro gates) |
| ETH | 6   | 3   | -3  |
| SOL | 161 | 136 | -25 |

v4 = v3_1 + V3.2 gate stack. Since V3.2 gates fire on real bars (table above), v4 strictly under-fires v3_1. **They are distinct.**

If the prior "byte-identical signals" claim came from a verifier comparing pre-gate `_build_signal_aux` output rather than post-gate emissions, the verifier was looking at the wrong layer. Pre-gate, v3_1 and v4 should agree on signal direction/threshold — that's the design intent (v3_1 quantile + V3.2 gates = v4).

### Prior Issue 3 — "v3_2 and v3_3 are identical by design on BTC/ETH" → **TRUE (but expected)**

| asset | v3_2 fires | v3_3 fires | delta |
|---|---:|---:|---:|
| BTC | 91  | 91  | 0   |
| ETH | 10  | 10  | 0   |
| SOL | 206 | 162 | -44 (MH-AND filter) |

This is correct by design per Phase 18.3 spec: v3_3 = v3_2 + SOL-only multi-horizon AND filter. On BTC/ETH there is no MH-AND, so v3_3 reduces to v3_2 byte-for-byte. Whether this is desirable is a **product decision**, not a bug.

Action item (optional, NOT a TV agent fix): if the user wants v3_3 to do something different on BTC/ETH, write a new spec defining what — e.g., "v3_3 BTC/ETH = stricter `regime` threshold" or "v3_3 BTC/ETH = tighter spread filter". Until that decision lands, leave as-is.

---

## What actually changed since 2026-05-11

The controller file mtime is 2026-05-16 02:05 UTC, but `git diff HEAD` shows **only** an uncommitted `slot_allowlist` patch (per-slot allowlist for live-mirror controllers, ~30 LOC, unrelated to v3 family). The v3 dispatcher logic is identical to the 7de7b12 reference cited in the prior spec.

```
Phase 26.3 D-04 / 2026-05-16 change:
+ slot_allowlist: "frozenset[tuple[str, str]] | None" = None
+ # early-return in on_bar_close if (sym, tf) not in allowlist
```

That fix is for the 2026-05-15 "unintended-fire bug" where one live-mirror controller fired all 6 (asset, tf) slots when only one was allowlisted — entirely separate from v3 family work.

---

## What the strategy lab should do instead

1. **Drop the v3 family A/B as currently designed** — the gate-stack differences ARE real but tiny. BTC v3_1 vs v4 = 24-fire difference over 14d; the noise floor in shadow PnL is wider than the signal. Run the comparison for ≥30 days or accept the verdict-in-noise.

2. **For Issue 3 (v3_2 ≡ v3_3 on BTC/ETH)**: ship a product decision. Either (a) accept that v3_3 = v3_2 + SOL-MH-only and stop expecting them to differ on BTC/ETH, or (b) author a Phase 18.4-equivalent spec naming a new BTC/ETH differentiator. No controller code change needed for (a).

3. **Update internal aggregators / dashboards** that may have inherited the same `event_time_us` query bug. The fault is in our SQL, not in production audit emissions.

---

## Side findings still relevant (separate tickets)

1. **`eth_5m_momo_v2_HOLD`: 24 `qty_compute_failed` events** — confirmed still present in 14d (53 in last query for `sol_5m_volume_INV_NIGHT` and visible across momo_v2 stacks). Open as own ticket. Not a v3 family issue.

2. **SOL v3_2 quantile is looser than v3_3's**: v3_2 emits 678 pre-spread signals vs v3_3 emits 444. Both share gates after that. This is consistent with code (v3_3 inherits v3_2 quantile but adds MH-AND filter) and is correct.

---

## Verification queries (for future re-runs)

```sql
-- Skip-reason breakdown per v3 sleeve, last 14d
SELECT sleeve_id,
       COALESCE(data->>'reason','<fire>') AS reason,
       COUNT(*)
FROM trading.events
WHERE at > NOW() - INTERVAL '14 days'
  AND kind = 'poly_updown_signal'
  AND sleeve_id ~ 'poly_updown_(btc|eth|sol)_(5|15)m_(v3|v3_1|v3_2|v3_3|v4)$'
GROUP BY 1, 2
ORDER BY 1, 3 DESC;

-- Pre-gate (non-trivial) signal totals per sleeve
SELECT sleeve_id, COUNT(*)
FROM trading.events
WHERE at > NOW() - INTERVAL '14 days'
  AND kind = 'poly_updown_signal'
  AND data->>'reason' NOT IN ('no_signal','wide_spread_skip','market_already_resolved')
GROUP BY 1
ORDER BY 1;
```

**Wrong (prior session — do NOT use):** filtering on `event_time_us` — that column does not exist in `trading.events`.

---

## Closing

No TV agent action required. Controller is correct. Prior spec (`TV_AGENT_V3_FAMILY_DIFFERENTIATION_SPEC_2026_05_11.md`) should be archived with a pointer to this document. Sleeves are distinguishable in production telemetry — the strategy-lab side of the analysis needs more time-on-test, not more code changes.
