# Next Task — AlphaPurify Repo Analysis

**Goal:** clone https://github.com/eliasswu/AlphaPurify, read its engine, compare to our two backtest engines, identify what's worth stealing.

**Why now:** while TV implements the validated strategies, we have a window to mine outside ideas. AlphaPurify is a reference repo — never seen it, no idea what it has, but worth a focused look before starting our own next-strategy hunt.

---

## Our two backtest engines (what AlphaPurify will be compared against)

### Engine A — Polymarket UpDown (`strategy_lab/`, this session's project)

Binary 5min/15min markets on Polymarket BTC/ETH/SOL up-down.

Key components:
- `polymarket_signal_grid_v2.py` — main simulator: per-market sim with hedge-hold rev_bp logic
- `polymarket_forward_walk_v2.py` — chronological 80/20 forward-walk
- `polymarket_signal_grid_realfills.py` + `book_walk.py` — orderbook book-walking for realistic fills
- `polymarket_extract_*.sql` — SQL extractors against Storedata Postgres
- Per-trade simulator in `simulate_market(row, traj_g, k1m, target, stop, rev_bp, merge_aware, hedge_hold)`

Conventions:
- Per-share PnL (1 YES + 1 NO if hedged, 1 YES otherwise)
- Bootstrap CI via `RNG.choice(pnls, size=(2000, n), replace=True)`
- Forward-walk: chronological 80/20 split, threshold fit on TRAIN
- Output format: pandas DataFrame → CSV + markdown table per cell

### Engine B — Hyperliquid futures (separate project, lives on VPS at `/opt/storedata/`)

Leveraged perps with mark price + funding. **NOT in this strategy_lab/ folder** — it's the V52 champion + perps research, files prefixed `run_v52_hl_*` / `hyperliquid/*`. See `archive_hyperliquid/V*_*.md` and `archive_hyperliquid/HYPERLIQUID_PORTFOLIO_REPORT.pdf` for context.

To find the live engine: SSH to VPS and look in `/opt/storedata/` or wherever the V52 champion lives. Should ask user where the Hyperliquid backtest engine code currently lives if not obvious.

---

## What to do — step by step

### Step 1: Clone + skim AlphaPurify

```bash
git clone https://github.com/eliasswu/AlphaPurify.git /tmp/alphapurify
cd /tmp/alphapurify
ls -la
cat README.md  # understand what it claims to do
```

Identify:
- What asset class? (equities? futures? crypto? prediction markets?)
- What timeframes?
- What's the architecture (single script vs modular)?
- Any docstrings or papers it implements?

### Step 2: Map the engine surface area

For each significant module/file, note:
- What signal does it compute?
- What execution model does it assume? (taker vs maker, full fill, slippage model?)
- What exit logic does it have? (stops, TP, trailing, hedge?)
- What validation framework? (walk-forward, k-fold, bootstrap, t-test?)
- What feature engineering? (technicals, microstructure, alternative data?)
- How does it handle data? (CSV, DB, parquet, streaming?)

### Step 3: Cross-reference with our engines

Make a 3-column comparison table:

| Feature | AlphaPurify | Engine A (Polymarket) | Engine B (Hyperliquid) | Worth stealing? |
|---|---|---|---|---|

Examples of what to look for:
- **Fill simulation**: do they have realistic-fills (book-walking)? Better than our `book_walk.py`?
- **Hedge logic**: equivalent of our hedge-hold? Cleaner pattern?
- **Robustness**: how do they validate? Permutation tests? Cross-asset stability?
- **Speed**: vectorized vs per-row iteration? Compare to our `for _, row in df.iterrows()` pattern.
- **Position sizing**: anything beyond fixed notional? Kelly? Vol-targeting?
- **Multi-asset**: how do they handle cross-asset signals?
- **Feature engineering**: any signals we haven't tested? (microstructure, sentiment, on-chain, options-implied, …)
- **Execution mode**: any hooks for paper/live distinction?

### Step 4: Rank the steal list

Produce ranked list of items worth porting, with effort estimate per item:

```
1. [HIGH] Vectorized hedge-hold simulator → speeds Engine A by ~10x — 1 day
2. [HIGH] Permutation-based feature significance test → adds rigor to alt-signal grid — ½ day
3. [MEDIUM] ...
```

Skip items that are inferior to what we already have, or irrelevant to our domain (e.g. equities-only stuff).

### Step 5: Output

Write **`reports/polymarket/02_analysis/ALPHAPURIFY_COMPARISON.md`** with:

1. **Summary** — what AlphaPurify is, 1-paragraph
2. **Comparison table** — feature-by-feature
3. **Ranked steal list** — top 5-10 items with effort + expected impact
4. **What NOT to steal** — items rejected with reasons (so we don't revisit)
5. **Domain-fit score** — how applicable is this repo to our setting (1-10)

---

## Constraints

- **Don't actually port code** in the next session. Just identify and rank. Porting is a follow-up.
- **Don't get lost in the source** — if a module is 5000 LOC of orchestration glue, skim it and move on. We want STEALABLE FRAGMENTS, not a full rewrite.
- **Be ruthless on relevance**. Equities-specific code is 0% applicable to our binary CTF + perps stack. Skip fast.
- **Two engines, separate compatibility lists**. A pattern good for Polymarket UpDown might be useless for Hyperliquid perps and vice versa.

---

## Likely outcomes (predictions to falsify)

Best-case: AlphaPurify has a fast vectorized backtester, a robust statistical validation pipeline, and 1-2 alt signals worth testing. We port 2-3 specific functions, gain ~1-2pp ROI on alt-signal hunt by adding a permutation framework, gain ~5-10x simulator speed.

Worst-case: AlphaPurify is equities/options-focused and irrelevant. Spent ½ day reading, output a "domain mismatch, no theft" note, move on.

Median expectation: 1-2 items worth stealing, mostly in tooling (validation, reporting) rather than alpha.

---

## Time budget

- Skim repo + map architecture: 1-2 hours
- Comparison table: 1 hour
- Ranked list + writeup: 1 hour
- **Total: ½ day**

If the repo is bigger than expected, focus on the engine core and skip orchestration.
