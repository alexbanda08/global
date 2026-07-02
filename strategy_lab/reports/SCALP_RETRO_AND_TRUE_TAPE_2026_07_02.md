# Scalp retro-computation + the true performance tape — how the strategy ACTUALLY performed
**2026-07-02. Follow-up to `IRELAND_RUST_IMPL_AUDIT_2026_07_01.md` ("can we retrieve the measurement from data we have?"). Answer: not from stored books (structural gap, §1) — but the Python engines were logging the real thing all along (§2). Raw + scripts: `strategy_lab/directional/_ireland_6day/{fire_list.csv, exit_books.tsv, retro29.csv, vps3_scalp_exits_clean.tsv, ireland_py_scalp.tsv, analyze_py_tapes.py}`.**

## 1. The retro-computation attempt — and the structural lesson it bought
Goal: recompute the +60s exit PnL for the 467 Rust-twin fires (all at exactly +5s offset ✓) by joining fire+60s → best bid from VPS3 `orderbook_snapshots_v2`.

**Result: impossible at scale — the stored books don't contain the scalp's moments.**
- VPS3 snapshot retention Jun 19+ → 321/467 fires in range. Of those: **entry book (+5s) found 0/321, exit book (+65s) found 29/321.**
- Cause (measured): the storedata collector subscribes each new 5m market **~2 minutes into the window** — median first snapshot at **+117s** (canonical L25 confirms: only 2% of 5m slugs have any book by +5s, 31% by +65s).
- 🧠 **Bank this: the +5s/+65s microstructure the scalp trades exists ONLY in the trading engines' own early-subscribed WS books (ws_mirror). It is not in storedata, not in canonical. Any scalp measurement must come from the engine tape (or a collector fixed to subscribe pre-open).**
- The 29 covered fires (biased subset, unbanded ev≈0.63 entries): retro exit +$0.27–0.35/tr vs their logged hold +$0.75/tr — indicative only, n too small, wrong population. No conclusions.
- (Also re-confirmed live in `orderbook_snapshots_v2`: the odd-level price↔size corruption — bid_1 showing 1257.66. Level-0 reads safe, as per `project_l25_level_corruption`.)

## 2. THE TRUE TAPE — VPS3 Python shadow (the deployed strategy, $5 paper on live ws_mirror books)
`shadow_scalp_exit_btc_5m_d3_v1`, kind `poly_updown_scalp_exit`, VPS3 production `storedata.trading.events`. This is the exact deployed config: entry band < 0.55 ✓ (100% of entries, med 0.510), pure +60s time sell (`exit_trigger: time60`), sell-leg fee $0, `fill_method: l25_walk`, `book_source: ws_mirror`.

```
n = 77 exits · Jun 11 → Jun 29 (18d, ~4.3/day)
PnL  +$60.26 total   +$0.783/tr   CI95 [+0.361, +1.205]   WR 65%
week of Jun 8:  n=4   +0.04/tr      (weak regime tail)
week of Jun 15: n=14  +0.42/tr
week of Jun 22: n=51  +0.96/tr      (regime turned — volume AND edge up)
week of Jun 29: n=8   +0.65/tr
```
**→ The scalp edge is ALIVE, CI>0, and consistent with the corrected-causal OOS (+0.91/tr ALL).** The weekly trend tracks the regime (June-early flat → late-June strong), matching everything we know about the edge's volatility dependence.

## 3. Ireland LIVE $1 (real fills, real sells, on-chain redeems)
Tiny n — none decisive yet (the ≥200-fires gate stands):
| live sleeve | n | $/tr | CI95 | WR |
|---|---|---|---|---|
| shadow_scalp_exit_btc_5m_d3_v1_LIVE | 9 | **+0.048** | [−0.19,+0.27] | 56% |
| shadow_scalp_exit_btc_15m_d3_v1_LIVE | 7 | −0.086 | [−0.32,+0.13] | 57% |
| shadow_scalp_momalign_btc_5m_v1_LIVE | 8 | −0.088 | [−0.32,+0.12] | 50% |

(Live $1 stakes; entries med 0.50–0.54 = band respected live. 17 on-chain redemptions logged — wallet plumbing works.)

Bonus — live directional fleet (resolutions, deduped, $1–1.5 stakes, since Jun 11): btc-15m off600 sniper LIVE **−$8.30**/98tr, eth v7 LIVE −$1.12/10, eth v8 LIVE −$4.72/8, kalshi sniper −$6.22/31, momo HEDGE +$0.74/4. **The scalp remains the only CI>0 strategy in the live stack.**

## 4. The three-tape reconciliation (why the Rust number misled)
| tape | measures | n | $/tr | verdict |
|---|---|---|---|---|
| Rust twin `resolve` | HOLD on **unbanded** (ev≈0.63) entries — band+exit both missing | 455 | −0.074 | ✗ not the strategy |
| Retro 29 (VPS3 books) | exit on unbanded entries, biased slug subset | 29 | +0.27 | inconclusive |
| **VPS3 Python shadow** | **the deployed config** (band ✓, +60s sell ✓, live books ✓) | **77** | **+0.783 CI[+0.36,+1.21]** | ✅ **edge alive** |
| Ireland live $1 | real money, same config | 9 | +0.048 | n too small yet |

The Rust −0.074 vs Python +0.783 gap is fully explained by the two Rust defects (no band, no exit) — **the fix spec (`TV_AGENT_SPEC_SUMPAIR_START_SCALP_TELEMETRY_2026_07_01.md` Part 2) is confirmed as the right and necessary move**, and retro-repair is impossible: the data to backfill it never existed outside engine memory.

## 5. Actions
1. TV agent spec already sent (sumpair enable + scalp twin band/exit/knobs) — **unchanged, now with proof it's necessary and sufficient.**
2. **New (data architecture):** if we ever want offline scalp research on production-window books, the storedata collector must **subscribe pre-open** (markets are listable ~24h early — the b945 finding). Candidate storedata spec: pre-subscribe crypto 5m/15m at discovery, not at first-trade. Until then, engine tapes are the only truth for early-window microstructure.
3. Keep accruing Ireland live fires toward the ≥200 gate; judge only on the live wallet CI.
