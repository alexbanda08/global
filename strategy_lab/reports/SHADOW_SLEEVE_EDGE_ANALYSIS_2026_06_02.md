# Shadow Sleeve Edge Analysis — which sleeves have REAL, profitable edge — 2026-06-02

Analysis of every shadow sleeve that has been firing for a while, from VPS3 `trading.events`
(`kind='poly_updown_resolution'`, the canonical settled-trade source, last 45d, one row per completed
trade with `won` + `pnl_usd`). 179 sleeves with n≥15; **59 currently active** (last fire ≥05-30, span ≥5d):
momo_v3 family ×39, sniper_v5 ×11, prewindow ×9.

Data: `strategy_lab/_sleeve_edge_2026_06_02/{sleeve_edge_raw.csv, analyze.py}`.
Edge bar applied (this session's hard lessons): **$/tr>0 after fees AND t≥2 AND n≥30** — NOT win-rate
(WR alone is the priced-in trap), measured on LIVE shadow PnL (the real OOS).

---

## Headline: across ALL 215 sleeves (full table → `_sleeve_edge_2026_06_02/full_table.md`), the fleet is net **−$25.4k**. Only **4** sleeves clear t≥2 with positive $/tr (small totals); **13** are promising (1≤t<2); **25** are significant bleeders (−$19.8k); the rest are flat/low-n/inactive.

Full distribution (215 sleeves, 45d resolved):

| bucket | sleeves | Σ PnL | meaning |
|---|--:|--:|---|
| 🟢 EDGE (t≥2, $/tr>0) | 4 | +$342 | real but small |
| 🟡 PROMISING (1≤t<2, $/tr>0) | 13 | +$2,147 | underpowered |
| ⚪ FLAT (insignificant) | 46 | +$674 | noise |
| 🟠 NEG (t≤−1) | 5 | −$676 | leaning bad |
| 🔴 BLEEDER (t≤−2 or ≤−$300) | 25 | **−$19,806** | KILL |
| ⏸ LOW_N (<30 fires) | 43 | −$554 | too few fires |
| ⬛ INACTIVE (no fire ≥5d) | 79 | −$7,496 | stopped |

The single-fire variance is huge (~$25 SD), so even genuine +$1–4/tr edges sit at t≈1–2 over 5–22 day
windows — significance needs 2–4× more fires. **The complete per-sleeve table for all 215 is in
`strategy_lab/_sleeve_edge_2026_06_02/full_table.md`** (this report covers the decision-relevant subset).

### The 4 EDGE sleeves (t≥2, active, $/tr>0)
| sleeve | fires | WR | vwap | $/tr | total | t |
|---|--:|--:|--:|--:|--:|--:|
| `kalshi_sniper_btc_15m_ema50_ema800_off600_down` | 108 | 84.3% | 0.74 | +1.33 | +144 | 2.0 |
| `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8` | 183 | 71.0% | 0.63 | +0.66 | +120 | **2.2** |
| `poly_sniper_v5_btc_15m_ts_trstack_off600_down` | 37 | 89.2% | 0.76 | +1.29 | +48 | 2.1 |
| `poly_sniper_v5_btc_15m_mpskew_trstack_off600_down` | 50 | 94.0% | 0.84 | +0.61 | +31 | 2.4 |

Common thread: **BTC-15m trend-continuation "off600 down" / trstack** + the **ETH-5m ema50-hurst** sleeve
(the one with the "5W streak" question — it has genuine edge, t=2.2, vwap 0.63 with a real WR-vs-breakeven
gap). The poly ema50_ema800 twin (t=1.99) sits just under the bar → effectively 5 sleeves in the ema/trstack
cluster carry the only real edge. **Beware the inverse:** the two HIGHEST-volume sniper sleeves
(`btc_5m_l_1hrf_imb5_rf_v8` 1922 fires 76% WR, `_ribbon_v8` 1527 fires 76% WR) are **significant LOSERS**
(−$611 t=−4.7, −$310 t=−2.8) — the priced-in trap at scale (high WR, vwap 0.74–0.77, −$/tr).

---

## 🟢 STRONGEST real-edge candidate — `btc_15m_ema50_ema800_off600_down`

| venue | n | WR | entry vwap | $/tr | total | **t** | span |
|---|--:|--:|--:|--:|--:|--:|--:|
| `kalshi_sniper_btc_15m_ema50_ema800_off600_down` | 108 | 84.3% | 0.741 | +$1.33 | +$143 | **2.00** | 3.1d |
| `poly_sniper_v5_btc_15m_ema50_ema800_off600_down` | 134 | 81.3% | 0.728 | +$1.24 | +$167 | **1.99** | 5.5d |

**Why it has edge (and is NOT a priced-in trap):** at entry vwap 0.73, breakeven WR ≈ **73–74%** (under
*both* the legacy 2%-on-profit and the 0.07-winner fee models); realized WR is **81–84%** → a genuine
**~8pp surplus**, and the realized +$1.25/tr confirms it survives fees. Mechanism = **established-trend
continuation lag**: when BTC is below both ema50 AND ema800 (the gates), the 15m DOWN market underprices
continuation even 10 min in. **It replicates independently on Kalshi (84% WR, t=2.00) — a different
order book — so it is not a single-venue book artifact.** Cross-venue 2σ replication is the best evidence
in the whole fleet.
Caveat: only 3–5.5 d of resolved data; t=2.0 is borderline. Needs 2–3× more fires to lock significance.
(Note: this is the same sleeve from the off900-logging investigation — the edge is real; the "double-fire"
was a counting artifact.)

## 🟡 Promising but underpowered (positive $/tr, t<2, asset-specific — do NOT deploy as a family)

| sleeve | n | WR | $/tr | total | t | span |
|---|--:|--:|--:|--:|--:|--:|
| `poly_updown_sol_5m_momo_v2_HOLD_f7` | 164 | 59.1% | **+$3.73** | +$611 | 1.97 | 11.9d |
| `poly_updown_btc_15m_momo_HOLD_f7` | 62 | 58.1% | +$3.85 | +$239 | 1.22 | 12.1d |
| `poly_updown_btc_5m_momo_HOLD_f7` | 171 | 54.4% | +$2.31 | +$395 | 1.20 | 11.3d |
| `poly_updown_eth_5m_v4` | 41 | 56.1% | +$4.22 | +$173 | 1.37 | 21.5d (small n) |
| `poly_sniper_v5_sol_5m_cci_f7_mfi_partial_vwap_v6` | 102 | 77.5% | +$0.43 | +$44 | 1.42 | 5.4d |

These are **F7-RSI-filtered directional momentum** (HOLD-to-resolution). Modest WR (54–59%) with real
+$2–4/tr → directional edge, not deep-favorite pricing. **But the F7 family is asset-dependent and
unstable:** the *same* mechanism is NEGATIVE on ETH (`eth_5m_momo_HOLD_f7` −$2.80/tr −$550; `btc_5m_momo_v2`
−$2.54/tr −$556). So the edge is in specific (asset × variant) cells (SOL-5m, BTC-5m/15m HOLD_f7), not the
family — high overfitting risk. Treat as watchlist, accumulate more fires before sizing.

## 🔴 CONFIRMED BLEEDERS — kill these (active, large negative, some significant)

| sleeve | n | WR | $/tr | total | t |
|---|--:|--:|--:|--:|--:|
| `poly_updown_sol_5m_volume_INV_NIGHT` | 2244 | 50.6% | −$1.22 | **−$2,744** | −2.4 |
| `poly_updown_btc_5m_volume_INV_NIGHT` | 2819 | 50.1% | −$0.75 | −$2,104 | −1.6 |
| `poly_updown_eth_5m_volume_INV_NIGHT` | 2487 | 51.1% | −$0.76 | −$1,887 | −1.6 |
| `poly_updown_sol_15m_volume_INV_NIGHT` | 900 | 49.3% | −$1.81 | −$1,632 | −2.3 |
| `shadow_poly_updown_ALL_5m_phase1_kelly` | 1285 | 50.9% | −$1.22 | −$1,562 | −0.6 |
| `poly_updown_eth_15m_volume_INV_NIGHT` | 960 | 49.8% | −$1.24 | −$1,192 | −1.6 |
| `poly_updown_btc_5m_momo_v2_HOLD_f7` | 219 | 45.2% | −$2.54 | −$556 | −1.5 |
| `poly_updown_eth_5m_momo_HOLD_f7` | 196 | 44.9% | −$2.80 | −$550 | −1.6 |
| `shadow_poly_updown_sol_5m_fade_momo_v2` | 203 | 46.8% | −$2.94 | −$597 | −1.7 |
| `poly_updown_sol_5m_v3` / `_v3_3` / `poly_updown_btc_5m_v4` | — | <52% | neg | −$500 to −$710 | — |

**INV_NIGHT ×6 alone bleeds ≈ −$10k** (WR ≈ coin-flip, so the entry cost is pure loss) — matches the
handoff KILL list. The `phase1_kelly` and `fade_momo` sleeves are also dead.

---

## Why "no proven winner" is the honest verdict
1. **Variance dominates.** $25 single-fire SD vs +$1–4/tr means t = (edge/25)·√n; even the SOL-5m
   momo (+$3.73/tr, n=164) only reaches t=1.97. Need ~n≥350 for t≥2 at that edge.
2. **WR is misleading** (this session's repeated lesson): the only sleeves with WR≥77% that are positive
   are the ema/cci ones where vwap (0.73/0.71) leaves a real gap; high-WR-without-edge would show $/tr≤0.
3. **Fees & fills:** `pnl_usd` is the engine's shadow model (≈legacy 2%-on-profit per the 2026-05-22
   verification). The ema candidate is +EV under both fee models — robust. Shadow `ws_mirror` book-walk
   fills may be slightly optimistic vs live cross-token spread; re-confirm on live fills before sizing.

## Recommendation
- **Lead candidate to push toward live: `btc_15m_ema50_ema800_off600_down`** — cross-venue replicated,
  +EV under both fee models, real WR-vs-breakeven gap. Keep accumulating; promote when t≥2 holds on ≥2
  more weeks AND live-fill PnL confirms.
- **Watchlist (accumulate, don't size):** SOL-5m & BTC-5m/15m `momo_HOLD_f7`. Per-cell only — the F7
  family is not robust across assets (ETH leaks).
- **Kill now:** all 6 INV_NIGHT, `phase1_kelly`, `fade_momo_v2`, `momo_v2_HOLD_f7` (btc/eth), `eth_5m_momo_HOLD_f7`,
  sol `v3/v3_3`, `btc_5m_v4`. Combined they bleed ≈ −$13k of shadow PnL and dilute the book.

---

## TV AGENT — actionable items (IMPORTANT: most losers are NOT bugs)

A losing sleeve here is almost always a **−EV strategy or a deprecated sleeve still firing**, not a code
bug. There is **no code fix that turns them profitable** — the action is to **DISABLE/REMOVE**, not patch.
Direction-split (30d) confirms each loser bets a fixed/normal side at coin-flip WR; the loss is the entry
cost, not a malfunction.

### 1. DISABLE (config / lifecycle — not a code fix)
Deprecated or −EV, actively bleeding. Set these sleeves inactive in the sniper/updown config:
```
poly_updown_{sol,btc,eth}_5m_volume_INV_NIGHT
poly_updown_{sol,eth,btc}_15m_volume_INV_NIGHT          # 6× INV_NIGHT, ≈ −$10k, DEPRECATED (handoff)
shadow_poly_updown_ALL_5m_phase1_kelly                   # −$1.56k
shadow_poly_updown_{sol,btc}_5m_fade_momo_v2 + sol_15m   # fade family, −EV
poly_updown_btc_5m_momo_v2_HOLD_f7                        # −$556
poly_updown_eth_5m_momo_HOLD_f7                          # −$550 (ETH cell of F7 leaks)
poly_updown_eth_5m_momo_v2_HOLD_f7                       # −$161
poly_updown_sol_5m_v3, poly_updown_sol_5m_v3_3, poly_updown_btc_5m_v4
```

### 2. FIX A REAL BUG (the only genuine code bug among losers)
`poly_fast_taker_lagv2_*` (8 sleeves) — wrong-signal bug (reads feed-vs-oracle basis instead of the
backtested binance intra-window return; fires ~100% UP live). **Spec already written:**
`TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md`. Current resolved data is small-n + priced-in-trap negative, so
low priority, but it is the one item where a code change (not a disable) is the right fix.

### 3. KEEP + accumulate (the actual edge — no bug)
- `*_btc_15m_ema50_ema800_off600_down` (kalshi + poly) — the lead candidate; do NOT touch the signal.
  Only minor hygiene: the sniper_v5 `sleeve_fire_resolved` event redundantly stamps `all_gates_passed=true`
  (counting footgun, NOT a trading bug) — see `TV_FIX_SNIPER_DOUBLE_FIRE_NONBUG_2026_06_01.md`.
- `poly_updown_{sol_5m,btc_5m,btc_15m}_momo_HOLD_f7` — watchlist, leave running to accumulate fires.

**Bottom line for the TV agent:** there is no "bug in the winning sleeve" to fix. The work is (1) disable
the −EV/deprecated bleeders above, (2) optionally land the lagv2 signal fix, (3) let the ema + F7 cells
keep accruing OOS fires until t≥2.

## END
