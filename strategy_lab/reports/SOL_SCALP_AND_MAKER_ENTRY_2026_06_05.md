# SOL Scalp + Maker-Entry Rebate Test — both NEGATIVE (2026-06-05)

**Asks:** (1) extend the exit-scalp to SOL, (2) test maker entry (rebate + spread capture) vs taker.
**Scripts:** `strategy_lab/directional/sol_scalp_2026_06_05.py` · `maker_entry_sim_2026_06_05.py`
**One line:** SOL scalp's edge is real but **untradeable** (0.5% fill at $25 — SOL up/down books too thin).
Maker entry **destroys** the scalp via adverse selection (+$1.52 taker → −$2.59 maker on the gated cell):
a resting bid fills on the losers and misses the winners. **Scalp stays all-taker, BTC/ETH only.**

## 1. SOL scalp — edge present, liquidity wall
Replicated the lag-taker scalp on SOL (delta_bps = |SOL binance-1s 5s return|, fire @ slot_start+5s, $25 taker
entry spread≤0.05, +45/+60s book-sell exit).
- 15,352 SOL resolved slugs → **2,331 candidate fires** (δ≥3) over Apr 7→Jun 4.
- **Fill rate = 12 / 2,331 = 0.5%** — 99.5% rejected by the $25 fill / spread≤0.05 / min-25-book-events gate.
  SOL up/down order books are too thin & spready for a $25 taker entry.
- Of the 12 fills, the **7 gated (vwap<0.55) show the same edge**: pnl45 +$6.27/tr (t=2.19, CI [+1.34,+11.7]),
  pnl60 +$6.53/tr (t=2.69, CI [+2.78,+11.3]). Mechanism confirmed — but n=7 / 0.5% fill = **not deployable**.
- This is why live deploy is BTC/ETH-only. A smaller $5 stake won't fix it (the binding gate is *spread*, not depth).
- → **SOL scalp: not viable as a taker.** (Maker can't save it either — see §2 adverse selection.)

## 2. Maker entry — adverse selection kills it
Rest a BUY limit at the best **bid** at fire (capture spread + 0.20×0.07×p(1−p) rebate). Fill simulated from
the **trade tape**: a SELL trade on the lead token at ≤ our price within 60s (optimistic — ignores queue
position, so an upper bound on maker fill). Exit +60s book-sell. Evaluated on the gated edge cell (vwap<0.55):

| Gated vwap<0.55 | n | TAKER (deployed) $/tr | MAKER-only $/tr | maker fill rate (won/lost) |
|---|---|---|---|---|
| **ALL** | 781 | **+1.52** (CI [0.86,2.17]) | **−2.59** (CI [−3.65,−1.49]) | 0.45 (won 0.36 / **lost 0.55**) |
| BTC | 504 | +2.22 (CI [1.43,3.00]) | −1.89 (CI [−3.22,−0.58]) | 0.43 (0.35 / 0.52) |
| ETH | 277 | +0.25 (CI [−0.90,1.41]) | −3.73 (CI [−5.55,−1.85]) | 0.48 (0.37 / 0.58) |

- **Adverse selection is the whole story.** The scalp edge = "the lag token reprices UP". A resting bid only
  fills when someone **sells into it** (token going DOWN = thesis wrong). So maker fills **50% more often on
  losers** (lost 0.55 vs won 0.36) and **never fills the winners** (token runs up → no seller hits the bid →
  no fill → you miss the money-makers). Result: the +$1.52 taker edge becomes **−$2.59** as a maker.
- The rebate + spread capture **do** work in isolation: maker beats taker **+$1.18/fill on the same fills**.
  But those fills are −$3.8 losers — being cheaper just means losing less on trades you shouldn't take. The
  selection effect (≈−$4) dwarfs the rebate (+$1.18).
- Hybrid "maker, taker-fallback on non-fill" looked +$0.41 (BTC) but is an **artifact**: the fallback assumed
  a taker entry at fire-time on non-fills, which is impossible if you waited 60s for the maker fill (the real
  fallback is a +60s taker-chase = far worse). Not a real edge.

## Verdict
- **Scalp stays all-TAKER.** Its edge depends on aggressively crossing the spread to capture the reprice;
  any passivity (maker entry OR maker exit) loses it. Maker entry → adverse selection (this report); maker exit
  → caps the runners (`SCALP_DYNAMIC_EXIT_2026_06_04`). The rebate (~$0.009/share) never compensates.
- **No SOL scalp sleeve** — 0.5% taker fill (liquidity), and maker would be adversely selected too.
- New durable rule: **maker≠taker for momentum-capture edges** (you fill the wrong side). Alongside WR≠edge, print≠fill.

## Files
- `sol_scalp_2026_06_05.py` → `_results/sol_scalp_fires_2026_06_05.parquet`
- `maker_entry_sim_2026_06_05.py` → `_results/maker_entry_sim_2026_06_05.parquet`
