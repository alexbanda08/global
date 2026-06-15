# Scalp-from-profitable-shadow-sleeves — research log (2026-06-09)

**Goal:** mine profitable shadow sleeves on VPS3, test whether their gates can drive a
**begin/mid-window scalp** (book-exit intra-window) that survives fidelity, and search new
gates/regimes for a robust scalp.

**Fidelity:** engine_v2 `LiveMimicConfig` — native-10Hz L25 walk, 85ms latency, spread filter,
min_book_events=25, $25 notional. PnL: hold = winner-only 0.07 curve; scalp = 0.07 both legs.

---

## Step 0 — Profitable shadow sleeves (dedup PnL, VPS3)

Ranked all sleeves by **dedup** realized PnL (one row per sleeve×condition_id — raw `events.pnl_usd`
double-counts). Top active gate-based sleeves (n≥20, PnL>0): momo line ($5–6.6/tr but old, 05-07→05-21,
schema-painful) + **sniper_v5 gate sleeves** (active 05-27→06-09, clean fire events). Focused on 12
sniper_v5 sleeves spanning BTC/ETH/SOL × 5m/15m × early/mid/late offsets. Fires extracted to
`strategy_lab/directional/_sleeve_fires_raw.csv` (6442 fires; join placed-signal→resolution on condition_id).

## Step 1 — Do the directional sleeves convert to scalps? **NO (priced-in).**

Cache: `strategy_lab/directional/sleeve_scalp_cache_2026_06_09.py` →
`_results/sleeve_scalp_cache_2026_06_09.parquet` (2611 filled fires, entry re-fill + bid path 15–180s + hold).
Analysis: `sleeve_scalp_analyze_2026_06_09.py` → `_results/sleeve_scalp_verdict_2026_06_09.csv`.

**Findings:**
- **`scalp beats hold` = NONE** (0/30 cells). Hold-to-resolution dominates book-exit for every sleeve ×
  every entry-vwap band; paired diff CI<0 everywhere.
- 9 cells have scalp $/tr CI>0 in absolute terms, but **best exit always +150–180s** (near-hold partial),
  never a fast scalp. Short exits (+15/30/45s) strictly worse.
- `eth_15m_trstack_vwap_offearly` (early entry) goes **negative** on book-exit (−2.1/tr).

**Conclusion:** the sleeves' edge is **directional/settlement, fully priced into the intra-window book**
(WR≠edge / print≠fill trap). No fast-rebound scalp lives in their entry signal. Do NOT scalp-exit them —
hold is optimal. → the scalp opportunity is a *different entry* (cheap lag-token rebound), tested next.

## Step 2 — Universal begin/mid-window lag-rebound scalp scan (new gates)

Cache `midwindow_scalp_cache_2026_06_09.py` (~150k entries, BTC/ETH 5m+15m × offsets
{5m:30,60,120,180,240; 15m:60,150,300,450,600}). At each offset: buy the binance-leading
cheap token (`|lag_bps|`=binance 5s return; tok=lead side; vwap<0.55), record bid path +{30,45,60,90}.
Features: lag_bps, mom30 (30s return), rv60, hour. Gate search + within-window + DSR:
`midwindow_scalp_{gates,robust,oos}_2026_06_09.py`.

**Skeptical scrutiny (avoided two traps):**
- offset 120–240 "$14–34/tr" cells = **favorite-longshot lottery** on 15–19¢ deep-cheap tokens (often
  hold-fallback or near-end deep-cheap), CI to ±40, outlier-driven. Discarded.
- **DSR across the full search (~130 cells): EVERY cell fails** (prob 0.000–0.113). Searching produces
  deflation-failing noise — same lesson as the 387k selectors. (Caveat: n_trials=130 over-penalizes —
  cells are correlated; effective trials ≪130.)

**Pre-registered single hypothesis (no search) + disjoint OOS** (`_oos_`):
BTC 5m begin-window (off 30/60) cheap **lag[3,12] + momentum-alignment** (lag-sign==mom30-sign), exit +45s:
- **OOS (last 40%): +$4.24/tr, CI[1.85,6.52], t=3.60.** momalign beats no-regime OOS (+4.24 vs +2.77).
  IS weaker (+1.53 ns) → not overfit. **ETH does NOT hold** (BTC≫ETH, known).

**Verdict:** the only genuinely new, OOS-positive result is the **momentum-alignment regime gate** on the
begin-window BTC-5m lag scalp — a refinement of the deployed +5s scalp (works at off 30–60s; momalign adds
OOS lift). Mid/late-window scalps = noise. Directional sleeves = priced-in (Step 1). Not deflation-confirmed
across search, but as a pre-registered hypothesis with disjoint-OOS CI>0 it meets the project bar for a
**forward-test shadow sleeve** (gate live, accrue ≥200 fires + CI>0 before capital). Spec:
`TV_AGENT_SPEC_SCALP_MOMALIGN_BTC5M_2026_06_09.md`.

**NOT recommended:** a bigger gate-search workflow — the data shows broad search = more DSR-failing in-sample
noise. Bottleneck is live forward fires, not more trials.

## Step 3 — EXIT-POLICY ground truth on the momalign cell (`momalign_exit_policy_2026_06_09.py`)

Fine 2s bid-path re-walk on the 164 candidate fires. Exit policies (PnL 0.07 both legs), IS/OOS:

| policy | ALL $/tr | IS | OOS |
|---|---|---|---|
| pure +45s | +2.86 | +1.68 | +4.61 |
| **+45s + stop@−0.10 (no TP)** | **+3.59** | **+2.50** | **+5.21** |
| +45s + TP@0.65 | +1.01 | −0.02 | +2.54 |
| +45s + TP + stop | +1.72 | +0.80 | +3.09 |

**`stop − pure` = +0.73/tr, CI[+0.35,+1.14] — stop HELPS (SIG in ALL/IS/OOS). TP LEAKS** (3.59→1.01).
stop-hit 23%, tp-hit 40%. → **optimal exit = +45s + protective stop@−0.10, NO take-profit.** (Corrects the
prior handoff claim that the stop leaks — only the TP leaks. Earlier "pure +45" rec was untested; fixed.)
