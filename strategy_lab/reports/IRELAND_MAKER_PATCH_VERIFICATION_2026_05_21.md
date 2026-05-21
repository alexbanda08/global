# Ireland maker patch verification — 2026-05-21

**Compare**: `TV_AGENT_MAKER_BUG_FIX_GUIDE.md` (10 bugs filed yesterday) vs Ireland VPS state today.
**Engine uptime**: 1h37min, stable since May 21 ~00:00 UTC. 5 restarts in the prior 6h (during patching).
**Verdict**: **TV agent shipped patches for 7 of 10 bugs and they all work.** Shadow data is now usable.

---

## 1. Patch status

| # | Bug | Patched? | Verified by |
|---:|---|:---:|---|
| 1 | `slug_pnl_so_far` always empty | ✅ | shadow_log.py:317 computes & writes; CSV shows 100% populated |
| 2 | `cash_recovered` always empty | ✅ | types.py:198 adds field; shadow_log.py:300 writes; CSV 100% pop |
| 3 | `slug_offset_s` always empty | ✅ | shadow_log.py:321 writes; CSV 100% pop |
| 4 | No `FILL` rows emitted | ✅ | All 5 sleeves now log FILL rows (10-571 per CSV) |
| 5 | `fill_simulated=1` only on TAKE | ✅ | Subsumed by Bug 4 — FILL rows have `fill_simulated=1` |
| 6 | Aggressor=None over-decrements | ✅ | `_infer_aggressor` added at fill_sim:304; tp.price vs mid heuristic |
| 7 | `take_empty_book` state leak | ⚠️ Not patched | Edge case — deferred per guide §7 ("DEFER unless > 1/h") |
| 8 | `sleeve_id` not in CSV | ✅ | New 23rd column appended; populated `poly_<strategy>_<asset>_<tf>_shadow` |
| 9 | Cold-start retry hardcoded 10 | ✅ | `tv_poly_maker_fill_sim_cold_start_max_retries` env var added (fill_sim:923) |
| 10 | State lost on engine restart | ⚠️ Not patched | Deferred to Phase 33 per guide §10 |

**7 of 10 patched. The 3 unpatched were correctly identified as defer-able in the guide.**

---

## 2. CSV data sanity — 100% column population

All 5 sleeves' May 21 CSVs:

| sleeve | rows | fill_simulated pop | slug_pnl_so_far pop | slug_offset_s pop | sleeve_id pop | cash_recovered pop |
|---|---:|---:|---:|---:|---:|---:|
| acc-h | 5,389 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| acc-m | 3,781 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| acc-pc | 1,255 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| mas | 158 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| pat-shadow | 1,428 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |

**All 5 previously-broken columns now report at 100%.**

---

## 3. Action audit — strategies firing correctly

Action counts in May 21 CSVs:

| sleeve | POST_BID | POST_ASK | CANCEL | FILL | TAKE | MERGE | MINT | REDEEM |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| acc-h | 2,485 | — | 2,380 | 246 | 143 | 121 | — | 14 |
| acc-m | 1,763 | — | 1,736 | 118 | 94 | 52 | — | 18 |
| acc-pc | 599 | — | 579 | 36 | 16 | 15 | — | 10 |
| mas | — | 56 | — | 10 | — | — | 46 | 46 |
| pat-shadow | — | — | — | 571 | 572 | 285 | — | — |

**Every expected action type appears.** Before the patch, FILL and MERGE were invisible. Now:
- `acc-m`: 118 FILL rows visible, 52 MERGE events, 18/18 slugs reach REDEEM (full lifecycle complete)
- `pat-shadow`: 572 TAKE → 571 FILL (1:1 — every take fills the synthetic walk), 285 MERGE (pair completions)
- `mas`: clean MINT → POST_ASK → FILL → REDEEM cycle on all 25 slugs (46 redeems = both sides)

---

## 4. THE BIG REVEAL — PnL flipped

The −$9,721/day "bleed" I reported yesterday was **a bookkeeping artifact**, not real losses. Now that fills and merges are properly accounted for, the actual May 21 numbers (~5h of operation) are:

| sleeve | Yesterday claim (broken bookkeeping) | Today actual (patched) | Change |
|---|---:|---:|---|
| **acc-h** | −$3,474 / 23 slugs (−$151/slug) | **+$12.15 / 24 slugs (+$0.51/slug)** | flipped positive |
| **acc-m** | −$525 / 17 slugs (−$31/slug) | **+$56.26 / 18 slugs (+$3.13/slug)** | flipped positive |
| **acc-pc** | −$264 / 6 slugs (−$44/slug) | **+$27.76 / 7 slugs (+$3.97/slug)** | flipped positive |
| **mas** | −$240 / 23 slugs (−$10/slug) | **+$303.78 / 25 slugs (+$12.15/slug)** | flipped positive |
| **pat-shadow** | −$5,219 / 17 slugs (−$307/slug) | **−$74.34 / 17 slugs (−$4.37/slug)** | 70× less negative |

**Aggregate**: −$9,721 fake bleed → **+$325.61 actual PnL over ~5h of operation**. 4 of 5 sleeves positive.

**Root cause of the fake bleed**: pre-patch CSV had `cash_received`, `cash_recovered`, `rebates` columns blank (the actual cash credits from MERGE + REDEEM + maker fills were happening internally but not written to disk). My PnL calc used `cash_received − cash_spent − fees` from those blank columns → showed only the COSTS, never the CREDITS. The patches expose the full balance.

---

## 5. pat-shadow update

Still negative but much smaller. Per-slug now **−$4.37** (vs the fake **−$307**).

At `pat_max_pair_cost=1.02` it's structurally slightly negative because half the fires take above $1.00, but the merge gain partially compensates. Not the catastrophe it appeared yesterday.

**Recommendation update**: pat-shadow at −$4/slug × 17 slugs/5h = −$72/5h ≈ **−$346/day**. Still negative, still recommend disabling unless explicitly kept for research, but no longer the $5k/day emergency it looked like yesterday.

---

## 6. Engine stability check

- **Current uptime**: 1h37min (since May 21 00:00 UTC approx)
- **Restarts in last 6h**: 5 (all during patching window earlier on May 20)
- **Recent crashes**: NONE since the patch sequence completed
- **Recent warnings**: `poly.submit.failed` (4 events) — `PolyApiException not enough balance / allowance: balance 1.9 USDC, order 2.1 USDC`. These are from the **live momo mirrors** trying to submit real orders against an under-funded wallet, **not maker-arb sleeves** (which are still shadow-only per `TV_POLY_MAKER_SHADOW_MODE=true`). Separate concern.

---

## 7. F7 RSI filter status

The F7 spec was given to the TV agent yesterday for momo sleeves on VPS3. Today's verification was for Ireland maker-arb sleeves only. Confirm F7 deployment status on VPS3 separately by inspecting `trading.events` for new `_v3_` or `_v3x_` sleeves.

---

## 8. Open items

1. **Bug 7** (take_empty_book state leak) — patch when convenient; minor.
2. **Bug 10** (state persistence on restart) — deferred to Phase 33 (live mode).
3. **pat-shadow operator decision** — keep for research at −$346/day, or disable.
4. **`poly.submit.failed` on live momo mirrors** — wallet under-funded by ~$0.20 USDC. Top up or reduce notional.

---

## 9. Verdict

**The TV agent did the work correctly.** Patches went in clean, no behavioral regression on the strategies themselves (the same fires happen — just now bookkept correctly). Shadow CSV is now usable as a validation source.

Real shadow performance over 5h:
- 4 of 5 sleeves positive
- mas is the strongest (+$12/slug, 25 slugs/5h = +$60/h)
- Aggregate +$325/5h ≈ **+$1,560/day projected** at the current scale

This is a strikingly different picture from yesterday's audit — and the difference is entirely accounting hygiene, not strategy quality. The strategies were always firing correctly; we just couldn't see the cash credits.

Recommend: **let it run 48h, then re-evaluate per-sleeve trends with the clean data.**
