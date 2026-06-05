# Intra-Window Scalp Research — buy ~0.40 / sell ~0.70 on 5m & 15m crypto tokens — 2026-06-02

**Scope:** Buy a Polymarket BTC/ETH/SOL up-down binary token cheap (~0.40 implied prob), sell it on the
book when it reprices (~0.70), WITHIN the window — no resolution required. PnL = (exit_vwap −
entry_vwap) × shares − two taker legs.

**Synthesized from:** 10 independent research angles (physics_path_predict, shorthorizon_price_forecast,
binary_scalp_mechanics, token_price_momentum_meanrev, gamma_digital_option, lag_reprice_capture,
cross_token_fastmove, exit_policy_optimization, exotic_new_ways, regime_timing_gates), each adversarially
screened. ~60 raw ideas reduced to the final set below.

**Fee convention (used throughout):** production-verified `poly_taker_curve` = `0.07 × p × (1−p)` per
share per leg. Note: CLAUDE.md (2026-05-22) confirms production BTC/ETH/SOL up-down markets currently
charge **2%-on-profit-only** (`LegacyConfig`). Run backtests under both; compare to production shadow PnL
using `LegacyConfig`; stress-test under `LiveMimicConfig` to bound downside.

---

## 1. Structural Constraints — Why Intra-Window Scalps Are Hard

These findings pre-screen any idea before analysis:

| Constraint | Evidence | Source |
|---|---|---|
| **Complete-set lock is dead** | UP+DN ask sum NEVER < 1.00 at any latency (82k events, dwell = 0ms, all cells). Anti-corr UP/DN ask increments −0.88 to −0.92 | `LEG2_REPRICING_STUDY_2026_05_29.md` |
| **Fixed TP exits are strict downgrades** | ALL TP thresholds 5–150% worsen ROI vs hold-to-resolution on any high-WR (81%+) sleeve. Best: tp_150pct_plus_revbp = −0.12pp vs baseline. Zero cross-asset/day agreement | `POLYMARKET_TAKE_PROFIT.md` |
| **Move-already-happened trap** | Any signal read at `slot_start + offset` from Poly CVD/VPIN/book captures the move already priced into vwap (WR 75–89%, $/tr = −$0.62 to +$0.01) | `EDGE_VALIDATION_TIER1_2026_06_01.md` |
| **Binance price-technicals at ws_s are dead** | KAMA-ER, semivariance, RS-vol, CUSUM, Kalman: all ~50% WR vs oracle | `EDGE_VALIDATION_TIER1_2026_06_01.md` |
| **BSM degenerates to step function** | σ√τ < 0.002 for all 5m/15m cells; N(d2) is binary on sign(S−K); ALL cells fail G1 (mean PnL < 0) | `BSM_FAIRVALUE_2026_05_31.md` |
| **Physics signal is priced in** | All-fires realized WR 81.6% = market-implied 81.5% (gap ≈ 0); unfiltered $/fire = −$0.02 to −$0.26 | `PHYSICS_SIGNAL_SYNTHESIS_2026_06_01.md` |
| **TP exits destroy EV on high-WR entries** | Even at 150% TP + revbp, ROI loss is 0.12pp per trade; the binary $1 payoff dominates any cap at finite threshold | `POLYMARKET_TAKE_PROFIT.md` |

**Fee hurdle for a 2-leg round trip at $25 notional:**
- Entry p=0.40: fee_in = 0.07 × 0.40 × 0.60 × 62.5sh = $1.05
- Exit p=0.70: fee_out = 0.07 × 0.70 × 0.30 × 62.5sh = $0.92
- Total round-trip fees ≈ **$1.97 on $25 = 7.9%**
- Minimum gross reprice needed to break even: ~**8pp** (0.40→0.48 is NOT enough)
- Useful net profit requires gross reprice of **15–30pp** (entry 0.40 → exit 0.55–0.70)

Under `LegacyConfig` (production reality): 2% on profit only. At entry 0.40, exit 0.70, gross $18.75,
fee = 0.02 × $18.75 = $0.375. Net = $18.375. Far more favorable — but only on the winning exit leg.

---

## 2. Deduplicated Idea Inventory — All 60 Raw Ideas Mapped

Many of the ~60 raw ideas from the 10 angles are duplicates or near-duplicates. The table below collapses them.

| Raw idea cluster | Angles that raised it | Kill reason (if killed) |
|---|---|---|
| TP exits at fixed thresholds (5–150%) | binary_scalp_mechanics, gamma_digital_option, lag_reprice_capture, exit_policy_optimization | Killed — ALL thresholds fail 0/4 gates in `POLYMARKET_TAKE_PROFIT.md` |
| Complete-set UP+DN lock/hedge | gamma_digital_option, cross_token_fastmove | Killed — dwell = 0ms, sum ≥ 1.01 always (`LEG2_REPRICING_STUDY_2026_05_29.md`) |
| BSM fair-value entry + continuous exit | exotic_new_ways, binary_scalp_mechanics, exit_policy_optimization | Killed — BSM step function at 5m/15m; all cells fail G1 (`BSM_FAIRVALUE_2026_05_31.md`) |
| Polymarket CVD/VPIN as direction gate | shorthorizon_price_forecast, exit_policy_optimization | Killed — confirmed B1/C4 traps (WR high, vwap already 0.76–0.87, $/tr ≤ 0) |
| L25 book depth/OFI at mid-window | binary_scalp_mechanics, exit_policy_optimization, shorthorizon_price_forecast | Killed — same move-already-happened trap as CVD (C1/C4/C8 all inverted or 0) |
| OI-spike + funding gate | cross_token_fastmove, exotic_new_ways, regime_timing_gates | Killed — only 2–3 days of cex_futures_ticker data (since May 30); statistically untestable |
| Physics signal (dist/speed/speed_away) | physics_path_predict | Killed — priced in, gap ≈ 0pp, −$0.02 to −$0.26/fire |
| Rogers-Satchell / realized semivariance gate | shorthorizon_price_forecast, binary_scalp_mechanics | Killed — ≤0.65pp lift, ns; same family as other vol-regime gates |
| Session-hour gate (London-NY 13-17 UTC) | regime_timing_gates | Killed — subsumed by existing C5_session_burst + TOD table in lag_taker_foundation |
| Mean-reversion on overstretch (fade spike) | token_price_momentum_meanrev | Killed — fade_mom_cheap WR 31–36%, $/tr −$2 to −$4, p=1.0 in permutation test |
| Perp-funding polarity gate | gamma_digital_option, cross_token_fastmove | Killed — 2 days data + funding gates explicitly failed V10A/V10B in prior research |
| Multi-level OFI burst (Cont et al.) | shorthorizon_price_forecast, exit_policy_optimization | Killed — structurally identical to B1 VPIN trap; Binance L2 depth not in canonical |
| Hawkes burst direction rule | shorthorizon_price_forecast | Killed — repo already has `vpin_hawkes_2026_05_26/` with H-A rule validated 3-way |
| Oracle-tick momentum snipe | gamma_digital_option | Killed — equivalent to catalog item #18 "oracle-snipe late-slot (taker)" CLOSED; book reprices on confirming RTDS tick |
| Depth-drain clock (late-window depth decay) | physics_path_predict | Killed — late entry at repriced vwap (0.60+) cannot clear 2×taker + spread; structural equivalent to killed TP exits |
| RV-regime gate (high-RV entry) | regime_timing_gates | Killed — same family as B3/B4 (vol-regime gates ≤0.65pp lift); high-RV regimes = Poly MMs reprice FASTER, shortening the lag window |
| Polymarket trade tape signals (TICK-REVERSAL) | binary_scalp_mechanics | Killed — `load_trades` stale at May 6; infeasible on current data |
| Optimal stopping / path-signature exit | exit_policy_optimization | Killed — TP verdict applies universally; signature converges to rev_bp rule with higher engineering cost |
| THETA-aware partial scale-out | exit_policy_optimization | Killed — HEDGE_LATE already tested; partial sell at T−120s degrades EV ($12.46 vs $13.90 full-hold) |
| Micro-price mean-reversion (cross-token) | exotic_new_ways | Killed — anti-corr −0.88 to −0.92 extends to micro-price; repricing sub-100ms, not modelable at 10Hz |
| Negation-pair KL divergence / single-leg lock | exotic_new_ways | Killed — sum_ask NEVER < 1.00 in 82k events; sum < 0.93 needed for profit at p=0.47, never observed |
| Late-window BSM entry (T−30s) | exotic_new_ways | Killed — book fully repriced at T−30s for directional slugs; entry vwap ≥ 0.85+ |

---

## 3. Survivor Evaluation — All Angles

After removing duplicates and applying the four-criterion screen (Novel / Feasible / Fee survival / Plausibility), the following survive from one or more angles.

### Screen criteria applied to each survivor:
1. **Novel**: not already implemented or equivalently killed in the arsenal
2. **Feasible**: both entry (`fill_at_book`) AND mid-window exit (`sell_pnl_partial`) computable from existing loaders without new data collection
3. **Fee survival**: two taker legs at `poly_taker_curve` (or `LegacyConfig` comparison) leave net positive EV at realistic reprice magnitudes
4. **Plausibility**: causal mechanism is coherent and not contradicted by existing empirical findings

---

## 4. Master Candidate Table (All Survivors Before Dedup/Tiering)

| ID | Name | Type | Novel | Feasible | Fee Survival | Plausibility | Angles | Verdict |
|---|---|---|---|---|---|---|---|---|
| **S1** | CUSUM-STALE (onset t* + ask-staleness + mid-window exit) | full_strategy | High | Yes | Likely | High | shorthorizon, lag_reprice | TIER 1 |
| **S2** | STALE-ASK DEPTH-LOCK (ask frozen ≥10 snaps before entry) | entry_rule | High | Yes | Likely | Med-High | regime_timing, lag_reprice | TIER 1 |
| **S3** | OI-LIQ-CASCADE (HL cascade onset intra-window + mid-window exit) | full_strategy | Yes (onset+exit novel) | Partial (drop OI norm) | Likely | Medium | binary_scalp, gamma_digital, cross_token | TIER 2 |
| **S4** | NEGATIVE JUMP ASYMMETRY (bipower LM detection, DOWN token) | signal + entry | Yes (DN-specific) | Yes | Marginal | Low-Med | token_price_momentum | TIER 2 |
| **S5** | OFI-FLIP EXIT (book-qty OFI sign-reversal as exit trigger) | exit_rule | Yes | Yes | Marginal | Low-Med | exit_policy, lag_reprice | TIER 2 |
| **S6** | VWAP-TO-MID DEVIATION GATE (vol-weighted vs chainlink, pre-entry) | gate | Medium | Yes | Likely (gate only) | Medium | regime_timing | TIER 2 |
| **S7** | VAMP EXIT (Volume-Adjusted Mid Price leads raw bid by 1–2 snaps) | exit_rule | Yes | Yes | Likely | Medium | exit_policy | TIER 2 |
| **S8** | FILTERED-OBI-TAKER (Binance taker_buy_base ratio gate) | signal + entry | Medium | Partial | Marginal | Med | cross_token | TIER 2 |
| **S9** | CEILING-FADE via DN token (entry when UP bid ≥ 0.88, ≥90s left) | full_strategy | Yes | Yes | Likely (15m) | Medium | exotic_new_ways | TIER 3 |
| **S10** | RSVD (realized semivariance + BSM combined gate) | gate + strategy | Marginal | Yes | Marginal | Low-Med | shorthorizon | TIER 3 |
| **S11** | FUNDING-SPIKE-CONTRA (OI drop after cascade + contra entry) | gate | Yes | Yes | Likely on paper | Low | cross_token | TIER 3 |
| **S12** | HL LIQ BURST PRIMARY TRIGGER + intra-window exit (A1 variant) | full_strategy | Yes (exit layer new) | Partial (stale HL data) | Likely | Medium | gamma_digital, binary_scalp | TIER 3 |
| **S13** | STALE-ASK MOMENTUM BURST (lag-taker + 2-leg exit variant) | full_strategy | Medium | Yes | Marginal | Med | lag_reprice | TIER 3 |

---

## 5. Deduplication — Near-Duplicate Collapse

| Group | IDs | Master | Dropped |
|---|---|---|---|
| Ask-staleness entry verification | S1 (CUSUM-STALE), S2 (DEPTH-LOCK), S13 (momentum burst exit) | **S1 is most complete**: it contains ask-staleness verification (S2) as a component AND adds the CUSUM onset condition; S13 adds the 2-leg mid-window exit which S1 also targets | S13 collapsed into S1 (its exit is covered by S1's mid-window exit step). S2 retained separately as a standalone entry_rule applicable to any fire, not just CUSUM fires. |
| HL liq cascade scalp | S3 (cascade onset + mid-exit), S12 (A1 variant + exit) | **S3 is broader and more novel**: S12 is a subset (A1 hold-to-resolution, adding only the exit layer). S3's genuine novelty is the intra-window cascade ONSET detection, not just the exit | S12 collapsed into S3. |
| OFI / flow exit | S5 (OFI-flip bid/ask), S8 (Binance taker ratio gate) | Kept separate: S5 is an EXIT rule on the Poly token book; S8 is an ENTRY gate on Binance-side flow. Different roles in the trade lifecycle | — |
| Exit triggers | S5 (OFI-flip), S7 (VAMP) | Both are exit rules applied post-entry. Kept separate: VAMP is a lead indicator of the bid (price-side); OFI-flip is a flow indicator (size-side). Can be combined in one backtest as parallel exit conditions | — |

**Final deduplicated list (9 candidates):** S1, S2, S3, S4, S5, S6, S7, S9, S10/S11

---

## 6. Detailed Candidate Profiles

---

### TIER 1 — Build and Backtest Next

---

#### S1 — CUSUM-STALE: Dynamic Onset + Ask-Staleness + Mid-Window Exit

**Category:** Full strategy (extends lag-taker with dynamic entry trigger and intra-window sell)

**Mechanism:**
For each BTC/ETH slug, run `running_cusum(px_1s)` causally from `slot_start − 300s`. Find the first
timestamp `t*` in `[slot_start + 5s, slot_start + 90s]` where `|CUSUM_S| > threshold h = 4`. At `t*`:
check whether L25 ask for the CUSUM-indicated side is unchanged from `ask_at_slot_start × (1 + 2 ticks)`.
If stale: fire entry. Scan L25 10Hz forward for: (a) CUSUM resets toward 0, (b) `bid ≥ entry_vwap + 0.18`,
or (c) 120s elapsed. Exit via `sell_pnl_partial` at whichever fires first.

**Why novel:**
- Existing lag-taker fires blindly at `slot_start + 5s` regardless of whether CUSUM has confirmed a genuine
  trend onset — CUSUM onset timestamp `t*` is NOT computed anywhere in the arsenal.
- Existing CUSUM code in `edge_val_stage2_klines_2026_06_01.py` reads the CUSUM value AT ws_s only.
- The ask-staleness condition (proven OOS, t=2.28, +$1.31/$25 at 5s) is tightened: instead of firing at a
  fixed 5s offset, it fires only when CUSUM has confirmed a directional breakout AND the ask hasn't moved.
- Mid-window exit (selling on the book) rather than hold-to-resolution is novel for this signal combination.

**Why the reprice happens:**
The CUSUM onset marks the moment when a genuine trend shift exceeds noise (cumulative sum of deviations from
mean exceeds h=4). The lag-taker thesis (proven OOS at t=2.78, +$1.71–$2.39/$25 on BTC+ETH) is that
Binance leads; Polymarket asks lag. CUSUM onset selects the subset of fires where the Binance trend is
structurally confirmed, not just a transient spike — these are the fires most likely to see the Polymarket
book reprice in the indicated direction over the next 60–120s.

**Entry trigger:**
```
asset in {BTC, ETH}
t* = first CUSUM crossing in [slot_start + 5s, slot_start + 90s], |S| > 4
ask_UP_at_t* < ask_UP_at_slot_start * 1.02   (ask is stale)
fire_us = t*
fill_at_book(books_idx, slug, cusum_side, t*, cfg=LiveMimicConfig(), spread_filter=0.05)
```

**Exit rule:**
```
scan L25 10Hz from t* forward:
  if CUSUM_S crosses 0 (trend exhausted): sell_pnl_partial(fill, books_idx, slug, side, t_exit, cfg)
  elif bid_at_t ≥ fill.vwap + 0.18:       sell_pnl_partial(fill, books_idx, slug, side, t_exit, cfg)
  elif t - t* > 120s:                      sell_pnl_partial(fill, books_idx, slug, side, t_exit, cfg)
else:
  hold_pnl(fill, won=..., cfg=...)   # fallback if exit never triggers within window
```

**Fee math ($25 notional, poly_taker_curve):**
- Entry p ≈ 0.50 (CUSUM fires early; book not yet repriced): shares ≈ 50, fee_in = 0.07×0.50×0.50×50 = $0.875
- Exit p ≈ 0.68 (target: entry + 0.18): fee_out = 0.07×0.68×0.32×50 = $0.762
- Total fees ≈ $1.64. Gross reprice 0.18 on 50sh = $9.00. Net ≈ **+$7.36** if exit triggered.
- Under LegacyConfig: fee_out only on winning exit = 2% × ($34 − $25) = $0.18. Net ≈ **+$8.82**.
- Break-even: if exit triggers in 30–40% of winning fires (WR ~65%), EV turns positive even if half of
  exits under-deliver on the 0.18 reprice.

**Exact loaders:**
```python
from load import load_resolutions, load_klines, load_orderbook_l25_streaming
from engine_v2 import LiveMimicConfig, LegacyConfig, fill_at_book, sell_pnl_partial, hold_pnl

res = load_resolutions()
px_1s = load_klines(asset, freq='1s')   # time_period_start_us, price_close columns
books_idx = load_orderbook_l25_streaming(asset.lower(), slugs=slug_set, subsample_1hz=False)
cfg = LiveMimicConfig()   # compare vs LegacyConfig() for production parity
```

**Running CUSUM (already coded in `edge_val_stage2_klines_2026_06_01.py`):**
```python
def running_cusum(px_arr, k=0.5, h=4.0):
    mu = px_arr.mean(); S, hi, lo = 0.0, 0.0, 0.0
    S_arr = np.zeros(len(px_arr))
    for i, x in enumerate(px_arr):
        S = S + (x - mu)   # basic CUSUM; use k*sigma version for calibrated detection
        S_arr[i] = S
    return S_arr
```

**Backtest sketch:**
```
For each BTC/ETH 5m slug in canonical resolutions (Apr 22 → May 27, max HL liq data):
  1. Load px_1s for [slot_start - 360s, slot_start + 90s], compute running_cusum
  2. Find t* = first crossing |S| > 4 in [slot_start+5s, slot_start+90s]
  3. If no t*: skip (fallback to lag_taker baseline or skip fire entirely)
  4. Check L25 ask at t* vs slot_start: if ask_UP_t* < ask_UP_slot_start * 1.02, fire
  5. fill_at_book at t*, 85ms latency, spread_filter=0.05
  6. Scan forward 10Hz L25: first exit condition triggers sell_pnl_partial
  7. Record: t*, entry_vwap, exit_vwap, net_pnl, cusum_S_at_t*, ask_stale_flag
Compare: (a) CUSUM-fires vs full lag-taker universe on WR and $/tr; (b) mid-window exit vs hold_pnl
on the CUSUM-fire subset.
```

**Key gotchas:**
- L25 `subsample_1hz=False` mandatory (per CLAUDE.md convention).
- HL liq data stale at May 27; if restricting to slugs where cascade overlaps, limit window further.
- CUSUM h=4 is a starting point; sweep h ∈ {3, 4, 5} and k ∈ {0.3, 0.5, 0.8} to avoid overfitting.
- The "fallback to hold_pnl" branch must be reported separately (compare to pure hold baseline).

**Source:** Anastasopoulos & Gradojevic, "Order Flow and Cryptocurrency Returns," EFMA 2025.
Latency edge OOS: `strategy_lab/directional/latency_walkforward.py` (t=2.28 standalone).
CUSUM code: `strategy_lab/directional/edge_val_stage2_klines_2026_06_01.py`.

---

#### S2 — STALE-ASK DEPTH-LOCK: Pre-Entry Book Stability Filter

**Category:** Entry rule (pre-entry filter on any lag-taker or CUSUM fire)

**Mechanism:**
Before calling `fill_at_book`, verify that the top-3 ask levels for the target token are IDENTICAL across
the last 10 consecutive native-10Hz L25 snapshots (= 1 full second of stability). Only enter if frozen.

**Why novel:**
The lag-taker fires at whatever ask is present at `slot_start + 5s`. It infers staleness from the Binance
return signal but does NOT verify that the ask is actually frozen. This filter pre-selects fires where the
market-maker lag is PROVABLY active (the resting ask has not refreshed in ≥1s), not merely inferred.
No existing code in the arsenal checks ask-snapshot stability as an entry gate.

**Why the reprice happens:**
If the ask has been frozen for ≥1s in the face of a Binance move, the market-maker has genuinely not
responded yet. The subsequent batch update (when the MM does respond) is a step-function jump in the book,
which the buyer captures in part. Trades where the ask was already refreshed before entry lack this mechanic.

**Entry trigger:**
```python
# Immediately before fill_at_book:
snaps_before = L25_snapshots[target_us - 1_000_000 : target_us]  # last 1s at 10Hz = ~10 snaps
if len(snaps_before) >= 10:
    stable = (np.all(snaps_before[-10:, 0, 0:3] == snaps_before[-11, 0, 0:3]) and   # ask prices
              np.all(snaps_before[-10:, 1, 0:3] == snaps_before[-11, 1, 0:3]))        # ask sizes
    if not stable: continue   # skip fire
fill = fill_at_book(books_idx, slug, side, fire_us, cfg=cfg, spread_filter=0.05)
```

**Fee survival:** Identical to underlying lag-taker (+$1.71–$2.39/$25 after 0.07 winner-only fee). This
is a volume-reducing filter; it cannot worsen per-trade economics.

**Backtest sketch:**
Modify `lag_taker_foundation_2026_05_29.py` inner loop to tag each fire `stale_lock=True/False`. Compare
WR, entry_vwap, and $/tr between the two subsets. Primary metric: does `stale_lock=True` show materially
better entry_vwap (the ask was genuinely unrefreshed) and higher WR?

**Sweep:** N ∈ {5, 8, 10, 15} snapshots (0.5s, 0.8s, 1.0s, 1.5s stability windows).

**Source:** `LAGV2_ROOTCAUSE_ALWAYS_UP_2026_06_01.md` (mechanism discussion); lag-taker edge
`LAG_TAKER_FINAL_CONFIG_2026_05_29.md`.

---

### TIER 2 — Promising but Marginal or Partially Data-Constrained

---

#### S3 — OI-LIQ-CASCADE: Intra-Window Cascade Onset + Mid-Window Exit

**Category:** Full strategy (variant of A1 with genuinely new onset detection and exit layer)

**Mechanism:**
For each BTC 5m slug, scan the HL liquidation tape for `[slot_start, slot_start + 120s]`. At each 1s step,
compute rolling 60s Close-Short notional. Find first `t*` where `CascadeScore_t ≥ $500k notional` (onset
within window). At `t*`: `fill_at_book(books_idx, slug, "Up", t*, cfg=LiveMimicConfig())`. Scan forward
for cascade exhaustion (`CascadeScore → 0`) or `bid ≥ entry_vwap + 0.15` or 120s elapsed.
`sell_pnl_partial` at exit.

**Why novel vs existing A1:**
- A1 (`edge_val_stage5_a1fill_2026_06_01.py`) uses cascade score at `ws_s` (pre-window, 5–15min before
  slug starts) as a hold-to-resolution gate. This fires WITHIN the window using dynamic onset detection.
- The intra-window scalp exit (sell_pnl_partial on cascade exhaustion) has never been tested.
- Novel components: (a) cascade-onset detection intra-window, (b) mid-window exit on exhaustion signal.

**Data constraint:**
HL liquidations data max-ts = May 27 13:35 UTC. Limits backtest window to ~35 days; BTC has 42.79M rows
(densest coverage). Must refresh via `migration_2026_05_26/pull_hl_full.sh` before this becomes current.

**Fee math:**
- Entry vwap ≈ 0.51 (A1 Stage5 fill confirms), 50 shares: fee_in = 0.07×0.51×0.49×50 = $0.87
- Exit at bid 0.66 (entry + 0.15): fee_out = 0.07×0.66×0.34×50 = $0.79
- Total fees ≈ $1.66. Gross 0.15 × 50 = $7.50. Net ≈ **+$5.84** if exit triggered.
- Plausibility caveat: A1 directional WR was 53.8% with t=0.35 — below significance. The intra-window
  exit reduces resolution variance but the entry directional lean is weak.

**Exact loaders:**
```python
from load import load_resolutions, load_orderbook_l25_streaming, load_hyperliquid_liquidations_full
liqs = load_hyperliquid_liquidations_full()   # 5.27M rows, max May 27
books_idx = load_orderbook_l25_streaming('btc', slugs=slug_set, subsample_1hz=False)
```

**Backtest sketch:**
```
For each BTC 5m slug (slot_start ≤ May 27 13:00):
  1. Filter liqs to [slot_start, slot_start + 120s], type="Close Short"
  2. Compute rolling_60s_notional at each 1s step
  3. Find t* = first step where rolling_60s_notional ≥ 500_000
  4. If no t* in window: skip
  5. fill_at_book at t* + 85ms
  6. Scan L25 10Hz: cascade_score → 0 OR bid >= entry_vwap + 0.15 OR 120s
  7. sell_pnl_partial; vs hold_pnl control on same entries
```

---

#### S4 — NEGATIVE JUMP ASYMMETRY: Bipower LM Detection on DOWN Token

**Category:** Signal + entry (extension of existing LM panel to asymmetric DOWN-entry case)

**Mechanism:**
For each 5m slug, compute bipower variation over trailing 270 bars of 5s returns (= 22.5min lookback) from
`load_klines(freq='1s')`. Detect a negative jump at any `t` in `[slot_start - 30s, slot_start + 30s]`
using Lee-Mykland statistic `|L| > 3.5 × MAD_6hr`. If negative jump detected AND `time_remaining > 150s`:
`fill_at_book(books_idx, slug, "Down", t + 30s, cfg=LiveMimicConfig())`. Exit at bid ≥ entry_vwap + 0.10
or 90s.

**Why novel:**
Existing `lee_mykland_2026_05_26/build_lm_panel.py` and `lm_standalone_rules.csv` test LM-A (fire with
jump direction, any sign) → WR=69.9%, $/tr=+$1.17 at 30s offset. That test used fake vwap=0.50 (no real
L25 fills). This is:
(a) DOWN-token specific on negative jumps only (asymmetric: negative jumps are documented to be larger and
    self-exciting per Zhang et al. 2024, Liu/Packham/Sepp arXiv:2510.21297)
(b) Real L25 fills via `fill_at_book` (the LM-A +$1.17 is probably optimistic)
(c) Mid-window exit via `sell_pnl_partial` instead of hold-to-resolution

**Fee math:** Entry p≈0.52 (DOWN token, fair near slot start): fee_in = 0.07×0.52×0.48×50sh = $0.87.
Exit p≈0.62 (entry + 0.10): fee_out = 0.07×0.62×0.38×50sh = $0.83. Net ≈ $5.00 − $1.70 = **+$3.30**.
Marginal: depends on the actual fill vwap not being the move-already-happened trap.

**Critical risk:** If the negative jump causes the DOWN token to reprice upward within 100ms (the lag-taker
mechanism runs both directions), the fill vwap will be > 0.52 and the fee math degrades. Must verify
entry_vwap is actually near-fair (≤ 0.55) in practice using real L25.

**Source:** Zhang et al. (2024) JoForecasting; Liu/Packham/Sepp arXiv:2510.21297; existing
`lee_mykland_2026_05_26/build_lm_panel.py` (bipower formula already coded).

---

#### S5 — OFI-FLIP EXIT: Real-Time Book-Size Imbalance Reversal

**Category:** Exit rule (applied post-entry to any lag-taker or CUSUM fire)

**Mechanism:**
After `fill_at_book`, stream L25 10Hz. At each snapshot, compute rolling 6-snap (60s) smoothed OFI on the
held token: `OFI_t = (bsz[0,t] − asz[0,t]) / (bsz[0,t] + asz[0,t])`. When smoothed OFI crosses from
strongly positive (> 0.30) to negative (< 0) AND `bid[0,t] ≥ entry_vwap + 0.10`: call `sell_pnl_partial`.

**Why novel vs killed C4/C8:**
C4 (Poly CVD) and C8 (cross-token ask asymmetry) were used as DIRECTIONAL ENTRY gates and killed because
entry vwap tracked the move (trap). OFI-flip here is used as a POST-ENTRY exit trigger, applied AFTER a
confirmed directional fill. The structural question is different: not "which way will the token move?" but
"has the existing move exhausted?" The anti-correlation structure of the book means OFI flipping negative
on the held token while the complement flips positive is a real signal of maker rebalancing.

**Key risk:** OFI at 10Hz is noisy; a single MM canceling 5 shares fires the signal. Minimum OFI magnitude
threshold (0.30 → 0.0) + minimum bid condition (≥ entry_vwap + 0.10) is required to avoid premature exits.

**Fee math:** Same entry as lag-taker. Exit at bid ≈ 0.60 (entry ~0.52, + 0.08 min qualifier):
fee_out = 0.07×0.60×0.40×50 = $0.84. Net = (0.60−0.52)×50 − $0.875 − $0.84 = **+$2.29** at minimum
qualifier. Higher if OFI flip coincides with a larger reprice.

---

#### S6 — VWAP-TO-MID DEVIATION GATE: Volume-Weighted vs Oracle Pre-Entry Filter

**Category:** Gate (pre-entry overlay on lag-taker fires)

**Mechanism:**
At each `slot_start`, compute 300-bar trailing VWAP from `load_klines(freq='1s')`:
`vwap_300s = sum(close × vol) / sum(vol)`. Look up `chainlink_rtds_price` via `load_chainlink_asof`.
Compute `vwap_dev = (vwap_300s − chainlink_rtds_price) / chainlink_rtds_price`. Gate: `|vwap_dev| > 3 bps`
AND sign matches lag-taker direction.

**Why novel vs existing `cl_basis`:**
`cl_basis` in the arsenal uses `binance_1m_close − chainlink_rtds_price` (simple close price, 1m bar).
VWAP uses `volume_traded` per 1s bar (available in `klines_1s`), down-weighting thin bars and
up-weighting high-conviction moves. The external finding (Bieganowski & Slepaczuk arXiv:2602.00776 on 1s
perp data) identifies VWAP-to-mid as the SHAP-dominant microstructure feature — not close-to-mid.

**Correlation risk:** High correlation with `ret_bps` (the lag-taker signal) cannot be ruled out without
measurement. If they are >0.90 correlated, this gate adds nothing beyond tightening the existing threshold.
Must be tested as a split of existing lag-taker fires.

**Fee survival:** Identical to lag-taker (gate only, no new fee leg). Net of the gate is WR lift or
fire-count reduction.

---

#### S7 — VAMP EXIT: Volume-Adjusted Mid Price Leading Indicator

**Category:** Exit rule (mid-window exit trigger applied post-entry)

**Mechanism:**
At each L25 10Hz snapshot after entry, compute VAMP (Volume-Adjusted Mid Price):
`VAMP_t = (bp[0] × asz[0] + ap[0] × bsz[0]) / (asz[0] + bsz[0])`. When `VAMP_t ≥ exit_threshold` (e.g.,
0.67) while `bid[0] < exit_threshold`, trigger `sell_pnl_partial` — VAMP leads the raw bid by 1–2 snaps
(100–200ms) because it reflects pending size direction.

**Why novel vs raw-bid TP:**
The TP verdict killed raw bid-threshold exits (all 10 levels 0/4 gates). VAMP is a different signal: it
leads the raw bid by incorporating the size distribution on both sides. A VAMP crossing 0.67 when bid is
still 0.63 selects for moments when the book structure predicts an imminent bid uptick — reducing exit-leg
slippage vs a blind threshold. The POLYMARKET_TAKE_PROFIT verdict tested raw-bid-price thresholds, not
VAMP-based triggers. The microprice module (`microprice_2026_05_26/`) uses Stoikov microprice as a
DIRECTIONAL ENTRY gate — never as a continuous post-entry exit trigger.

**Fee math:** VAMP crosses 0.67 when bid ≈ 0.65 (lead of ~100ms). For entry at 0.47:
Gross = (0.65 − 0.47) × 53sh = $9.54. Fee_in = $0.87, fee_out = 0.07×0.65×0.35×53 = $0.85.
Net ≈ **+$7.82**. Fee-survivable if reprice reaches 0.65+.

**Sweep:** VAMP threshold ∈ {0.63, 0.67, 0.70} vs raw bid ∈ {0.61, 0.65, 0.68} on same fire universe.
Key output: does VAMP-triggered exit achieve higher exit_vwap and lower slippage than raw-bid threshold?

---

### TIER 3 — Speculative / Data-Limited / Mechanism Risk

---

#### S9 — CEILING-FADE via DN Token

**Category:** Full strategy (genuinely untested entry direction)

**Mechanism:**
Scan L25 10Hz for each slug. Find first snapshot where `DN_best_ask ≤ 0.12` (UP bid ≥ 0.88) AND
`time_remaining > 90s` AND `physics_speed_away < 50 bps/min` (prevents runaway momentum entry).
`fill_at_book(books_idx, slug, "Down", fire_us, cfg=LiveMimicConfig())`.
Exit at first `DN_best_bid ≥ 0.27` (UP drops to ~0.73) or `T−60s` time stop.

**Why novel:** All prior ceiling-and-TP research tested EXITS from held-long positions. This is a fresh
SHORT entry on the DN side when UP is at extreme ceiling. The mechanism is genuine gamma: binary options
have highest gamma near ATM (≈ strike), and at p=0.88 with >90s remaining, there is non-trivial gamma —
a 30bps adverse Binance move can drop UP from 0.88 to ~0.73. `fade_mom_cheap` and
`MEANREV_GATE_TEST_2026_05_29.md` tested opposing-token entries after earlier spikes, NOT at extreme
ceiling levels specifically (0.88+).

**Plausibility:** MEDIUM at 15m (σ√τ ≈ 0.04 at 90s remaining → 30bps move has non-trivial probability).
LOW at 5m (σ√τ ≈ 0.013 → very small probability). 15m only.

**Fee math:** Buy DN at 0.12 (83.3sh at $25), target bid 0.27:
fee_in = 0.07×0.12×0.88×83.3 = $0.62. fee_out = 0.07×0.27×0.73×83.3 = $1.15. Total $1.77.
Gross = (0.27 − 0.12) × 83.3 = $12.50. Net ≈ **+$10.73**. Fee-survivable — but WR must be ≥ 15%
for UP-at-0.88-with-90s-remaining to actually resolve Down. The market prices this at 12%; if true WR is
closer to 15%, the strategy is marginal. Breakeven: WR_Down × $10.73 ≥ WR_Up × $12.50 (loss on misses).
Breakeven WR_Down = 12.50 / (10.73 + 12.50) = 53.8% of the expected-loss-at-win → requires
~14% actual Down resolution rate vs 12% market-implied. Very sensitive to the 2pp gap.

---

#### S10 — RSVD: Realized Semivariance + BSM Dual Gate

**Category:** Gate (dual confirmation for mid-window entry)

**Mechanism:**
At `slot_start + 30s`: compute `RS_ratio = RS+ / (RS+ + RS-)` from `load_klines(freq='1s')` over
`[slot_start − 60s, slot_start + 30s]`. Compute BSM `N(d2)` from existing `bsm_fairvalue_2026_05_31.py`.
Gate: `RS_ratio > 0.70` AND `ask_UP < N(d2) − 0.02`. Entry via `fill_at_book`. Exit at bid ≥ entry + 0.18
or 150s.

**Why marginal:** BSM is already killed as a standalone (all 5m cells fail G1). The dual gate might
pre-select the subset where the mispricing is genuine (upside vol dominant + BSM confirms cheap). But
median |BSM edge| is 5–12%; after real fills the pricing efficiency catches up. Tier 3.

---

#### S11 — FUNDING-SPIKE-CONTRA: OI Drop After Cascade + Contra Entry

**Category:** Gate (contra entry signal)

**Mechanism:** When cross-exchange `cex_futures_ticker` funding_rate > 0.08%/8h AND `open_interest_usd`
drops > 2% in 60s AND Binance 60s return > +15bps: buy DOWN token, exit at `bid ≥ entry + 0.13` or
T−180s.

**Why Tier 3:** `cex_futures_ticker` started May 30 — only ~2–3 days of data at run time. Statistically
untestable (n expected ~5–15 qualifying events maximum). Can revisit after 14+ days of accumulation.

---

## 7. Ranked Summary Table

| Rank | ID | Name | Category | Fee Survival | Data | Priority |
|---|---|---|---|---|---|---|
| 1 | S1 | CUSUM-STALE | full_strategy | Likely ($7.36 net at target) | Full (Apr 22–May 27) | **TIER 1 — Build first** |
| 2 | S2 | STALE-ASK DEPTH-LOCK | entry_rule | Likely (same as lag-taker) | Full | **TIER 1 — 5-line addition to existing script** |
| 3 | S3 | OI-LIQ-CASCADE | full_strategy | Likely ($5.84 net at target) | Partial (stale HL liq, May 27) | TIER 2 — refresh HL data first |
| 4 | S7 | VAMP EXIT | exit_rule | Likely ($7.82 net at target) | Full | TIER 2 — parallelizable with S5 |
| 5 | S5 | OFI-FLIP EXIT | exit_rule | Marginal ($2.29 at minimum) | Full | TIER 2 — parallelizable with S7 |
| 6 | S6 | VWAP-TO-MID DEVIATION GATE | gate | Likely (gate only) | Full | TIER 2 — quick split of existing fires |
| 7 | S4 | NEGATIVE JUMP ASYMMETRY | signal + entry | Marginal (real-fill dependent) | Full | TIER 2 — 1-day extension of LM panel |
| 8 | S9 | CEILING-FADE via DN token | full_strategy | Likely on paper | Full (15m only) | TIER 3 — very low prior WR |
| 9 | S10/S11 | RSVD / FUNDING-CONTRA | gate | Marginal | Partial (BSM killed; tiny funding data) | TIER 3 — speculative |

---

## 8. TOP 5 to Backtest First — With Rationale

### #1 — S2: STALE-ASK DEPTH-LOCK (2 hours work)
**Rationale:** Zero new data sources. A 2-line numpy check added to `lag_taker_foundation_2026_05_29.py`.
Tags every lag-taker fire `stale_lock=True/False`, reports split statistics. If `stale_lock=True` shows
+$0.50+ better entry_vwap and +3pp WR lift, it immediately improves the deployed LAGV2 strategy without
any new backtest risk. Fastest possible test with potentially direct production impact.
**Expected output:** stale_lock=True n≈100–200, stale_lock=False n≈300+. Test: does True subset have
lower mean entry_vwap and higher WR vs False subset?

### #2 — S6: VWAP-TO-MID DEVIATION GATE (half-day work)
**Rationale:** Split existing lag_taker fire universe by `|vwap_dev| > 3bps`. No new fills needed —
uses existing fill records from `lag_taker_fires_enriched_2026_05_29.parquet`. Verifies whether the
volume-weighted vs close-price distinction adds lift to the existing cl_basis gate. Quick correlation
check reveals whether this is redundant or complementary.
**Expected output:** Two-way table of WR×$/tr by (vwap_dev gate: True/False) × (existing cl_basis: True/False).

### #3 — S1: CUSUM-STALE (1–2 days work)
**Rationale:** Most mechanistically complete TIER 1 idea. Requires: (a) running CUSUM over `klines_1s`,
(b) ask-staleness check on L25, (c) mid-window exit scan. All primitives exist. The CUSUM code is
already in `edge_val_stage2_klines_2026_06_01.py`. The lag-taker latency edge (t=2.28 OOS) provides the
directional base; CUSUM onset tightens the entry gate. Highest mechanistic coherence of all TIER-1/2 ideas.
**Expected output:** n_cusum_fires (expected 20–40% of lag_taker universe), WR and $/tr for:
(cusum_exit_triggered, cusum_exit_not_triggered, hold_pnl_fallback).

### #4 — S7 + S5 (combined exit sweep, 1 day work)
**Rationale:** Test VAMP-exit and OFI-flip-exit in parallel on the same lag-taker fire universe. Load
L25 once per slug, compute both exit signals, record exit_vwap and timing for each. Compare:
raw-bid threshold (existing) vs VAMP crossing vs OFI-flip vs time-stop. Best exit policy feeds
directly into CUSUM-STALE (#3) and the deployed LAGV2.
**Expected output:** 4-way exit comparison table (raw_bid_65, vamp_67, ofi_flip, time_90s) on WR×$/tr.

### #5 — S3: OI-LIQ-CASCADE (1 day work, conditional on HL refresh)
**Rationale:** The only idea that adds a genuinely new directional signal (HL liquidation cascade)
rather than refining the lag-taker. A1 directional WR 57.9% (p=0.03) is weak as a standalone but the
intra-window exit layer has never been tested. Requires HL liq refresh via
`migration_2026_05_26/pull_hl_full.sh` first. IF the exit layer converts the underpowered A1 signal
into a tight-window scalp with sufficient n and t≥2, this becomes a second independent strategy line.
**Expected output:** CascadeScore onset events n (expected 20–60 per 35-day window), entry_vwap (should
be ~0.51), exit_vwap distribution, $/tr and t-stat.

---

## 9. Dropped / Already-Have Appendix

The following candidates were confirmed equivalents of existing arsenal items or definitively killed by prior empirical work:

| Candidate | Status | Kill evidence |
|---|---|---|
| Complete-set UP+DN lock/hedge | Dead | LEG2_REPRICING_STUDY: sum ≥ 1.01 always, dwell=0ms, all 82k events |
| All fixed TP exits (5–150%) | Dead | POLYMARKET_TAKE_PROFIT: 0/4 gates, all 10 thresholds, all assets |
| BSM fair-value strategy | Dead | BSM_FAIRVALUE_2026_05_31: BSM = step function at 5m/15m, all cells fail G1 |
| Physics signal (dist/speed) | Dead | PHYSICS_SIGNAL_SYNTHESIS: gap ≈ 0pp, priced in, negative $/fire |
| Polymarket CVD/VPIN direction | Dead | EDGE_VALIDATION: B1 TRAP (WR 87%, $/tr −$0.62, t≤0) |
| L25 book depth ratio (C1) | Dead | EDGE_VALIDATION: INVERTED, WR 31–41%, p=0 |
| Cross-token ask asymmetry (C8) | Dead | EDGE_VALIDATION: INVERTED, WR 30–35%, p=0 |
| Rogers-Satchell / semivariance vol gate | Dead | EDGE_VALIDATION: ≤0.65pp lift, ns |
| KAMA Efficiency Ratio gate | Dead | EDGE_VALIDATION: ≤0.6pp lift, ns |
| Mean-reversion fade (fade_mom_cheap) | Dead | MEANREV_GATE_TEST: WR 31–36%, p=1.0 permutation |
| Multi-level OFI (Cont et al.) on Poly | Dead (or not novel) | mlofi_2026_05_26 exists; move-already-happened trap |
| Hawkes burst direction | Not novel | vpin_hawkes_2026_05_26 + H-A rule validated 3-way |
| Oracle-tick momentum snipe | Dead | Catalog item #18 CLOSED; book reprices on confirming RTDS tick |
| Session-hour gate | Not novel | Subsumed by C5_session_burst + existing TOD table |
| Depth-drain late entry | Dead | Same priced-in trap as C1/C8; entry at 0.60+ cannot clear 2×taker |
| Optimal stopping / signature exit | Dead | TP verdict universal; converges to rev_bp |
| Micro-price cross-token mean-reversion | Infeasible | Dwell=0ms; 10Hz cannot resolve sub-100ms dynamics |
| Negation-pair lock (single-leg cheap) | Dead | sum_ask < 0.93 never observed; mechanically impossible |
| Perp funding polarity gate | Infeasible | 2 days data; V10A/V10B explicitly tested and failed |
| High-RV gamma burst entry | Not novel + dead | Same family as B3/B4 (vol-regime gates); high-RV = MM reprices FASTER |
| Late-window BSM entry T−30s | Dead | Book fully repriced at T−30s; entry vwap ≥ 0.85 |
| VPIN toxic-flow follower | Dead | B1 TRAP confirmed; wrong sign on CEX VPIN too |
| Cross-asset leading-leg (BTC→ETH token) | Speculative | Cross-asset corr 0.87–0.89; both reprice from same Binance/chainlink signal simultaneously |
| Theta-aware partial scale-out | Dead | HEDGE_LATE research: partial sell at T−120s degrades EV ($12.46 vs $13.90 hold) |
| RV-regime gate entry | Dead | Same family as B3/B4; WORSE in high-RV (MMs reprice faster = shorter lag window) |
| Polymarket trade tape signals | Infeasible | `load_trades` stale at May 6; no fresh delta puller |
| OI-surge + funding gate | Infeasible now | 2–3 days of cex_futures_ticker data; revisit after 14+ days |

---

## 10. Engineering Checklist (All Backtest Implementations)

- [ ] `load_orderbook_l25_streaming(asset, slugs=slug_set, subsample_1hz=False)` — MANDATORY native 10Hz
- [ ] `fill_at_book(..., cfg=LiveMimicConfig(), spread_filter=0.05)` for entry
- [ ] `sell_pnl_partial(fill, books_idx, slug, side, exit_us, cfg=LiveMimicConfig())` for mid-window exit
- [ ] Compare PnL under BOTH `LiveMimicConfig` (stress) AND `LegacyConfig` (production parity)
- [ ] Outcome truth: use `outcome` col from `load_resolutions()` (chainlink-derived) for hold_pnl branches
- [ ] Never localize timestamps — all `*_us` columns are UTC microseconds
- [ ] Slug suffix = `int(slug.rsplit('-',1)[1])` = slot_start in seconds; anchor ws_s correctly
- [ ] Report: n, WR, entry_vwap, exit_vwap (if sell leg), $/tr, 95% CI, t-stat, IS vs OOS split
- [ ] Flag any result with t < 2.0 as NOT deploy-grade; t ≥ 2.0 with n ≥ 100 required before further steps

---

## END
