# hftbacktest feasibility for Polymarket maker sim — 2026-06-11

**TL;DR:** Installed OK on Py3.14. **VERDICT: do NOT use hftbacktest for the Polymarket maker sim — our book data is L1-only (top-of-book) + ~50% size==0, which defeats the whole point of the tool (queue-position fill realism). Build a custom conservative price-through fill sim instead. Reserve hftbacktest for Hyperliquid later (when we have its L2 deltas).**

---

## 1. Install — YES (Python 3.14, Windows)

- `C:/Python314/python.exe -m pip install hftbacktest` → **a `cp314-cp314-win_amd64` wheel exists** on PyPI (v2.4.4). Rust core is prebuilt; no compiler needed.
- First attempt failed only on a transitive pin: hftbacktest requires `numpy<2.3,>=2.0`; pip tried to build numpy 2.2.6 from sdist and hit a Windows path-too-long error inside numpy's vendored meson test cases.
- **Workaround used:** `pip install --no-deps hftbacktest`. Installed clean against the already-present `numpy 2.4.3` + `numba 0.65.0`.
- **Import verified:** `import hftbacktest` (2.4.4), `BacktestAsset`, `HashMapMarketDepthBacktest`, constants (`LIMIT,GTC,BUY_EVENT,SELL_EVENT,DEPTH_EVENT,TRADE_EVENT`) all import.
- ⚠️ numpy pin caveat: hftbacktest declares `numpy<2.3` but we run 2.4.3. Imports work; if a numpy-ABI runtime error ever surfaces, pin a 3.12 venv with numpy 2.2.x. Not needed today.

## 2. Data model fit — POOR

hftbacktest digests a numpy structured array of 8-field events: `ev (flags), exch_ts, local_ts, px, qty, order_id, ival, fval`. `ev` carries `DEPTH_EVENT`/`TRADE_EVENT` + `BUY/SELL` + `EXCH/LOCAL`. It reconstructs the **full L2 book from depth deltas** and replays trades. The entire value proposition is **queue-position-aware fills**: `ProbQueueModel` / `LogProbQueueModel` / `PowerProbQueueFunc*` infer where your resting order sits by watching **qty at your price level decrease** across depth updates and trades. `NoPartialFillExchange` / `PartialFillExchange` then fill you only when the queue ahead of you clears (or a trade prints through your price).

**Our data (verified schemas):**

- **BBO** (`D:\global_data\canonical_bbo\{coin}.parquet`): `timestamp_us, slug, outcome(token=Up/Down), best_bid, best_ask, best_bid_size, best_ask_size, timeframe`. **L1 only** — top-of-book, no levels behind best. Two rows per timestamp (one per token). On the sampled sol slug: **best_bid_size zero-rate 0.50, best_ask_size 0.51** (collector artifact, as flagged). Span is the full market lifetime (~24h+ pre-slot). Median inter-event dt ~0ms (event bursts).
- **Trades** (`canonical_bbo_trades`, via `load_trades_hf(asset,bbo=True)`): `timestamp_us, slug, outcome, side(BUY/SELL), price, size_usdc, spot_price, timeframe`. **Trades DO carry side + price + size** — usable as `TRADE_EVENT`. Good.
- **L25** (`canonical/orderbook_l25/{btc,eth,sol}.parquet`, 10Hz, 25 levels both sides): real depth, BUT only btc/eth/sol and only **Apr22→now** — disjoint from the BBO/maker window (Mar30–Apr21) and from the 7-coin scalp universe.

**Why the fit is poor:**

- (a) **BBO + trades** → we can only ever emit a 1-level depth event per side per token. hftbacktest will "reconstruct" a book that is exactly 1 level deep. The queue models then have **no qty-behind-best signal** — and when our resting price is *not* the current best (the normal maker case: you quote inside/behind), we have **zero visibility** into the size at that level. Queue advancement degrades to "fill only when best crosses you or a trade prints through," which is just a naive price-through sim with extra machinery. The 50% size==0 rows make even the at-best qty unreliable (queue estimate garbage half the time).
- (b) **10Hz L25 snapshots + no trades** → L25 gives real depth, so the book reconstruction would be honest, BUT: (i) snapshots are not deltas — feedable as full-replace depth per tick, OK; (ii) **no trade tape for that window** (trades are the Mar30–Apr21 set; L25 is Apr22+) → without `TRADE_EVENT`s the queue models can't advance position via prints and `NoPartialFillExchange`'s "front of queue && price==trade price" branch never triggers. You'd fill only on best-cross, again degenerating to price-through. Also btc/eth/sol only.
- **Queue models do NOT degrade gracefully to L1.** They are explicitly depth-decrement models. Feeding 1-level data doesn't make them conservative — it makes the queue estimate meaningless. There is no "L1 mode" that's principled.

## 3. Conversion sketch (proof of mapping) — effort if pursued

Mapping ONE 15m slug is *mechanically* possible:

- **Instruments:** Polymarket Up/Down are two separate CLOB tokens → **2 hftbacktest assets** (not 1). Each is a [0,1] price market; set `tick_size=0.01`, `lot_size=1` (shares), `px`=token price, `qty`=size (shares = size_usdc/price).
- **DEPTH events:** for each BBO row of a token, emit two rows — `BUY_EVENT|DEPTH_EVENT` at `(best_bid, best_bid_size)` and `SELL_EVENT|DEPTH_EVENT` at `(best_ask, best_ask_size)`. (To clear stale levels you'd also emit qty=0 rows for the previous best when it moves — needed so the reconstructed book doesn't accumulate phantom levels.)
- **TRADE events:** for each trade row, `(BUY or SELL)|TRADE_EVENT` at `(price, size_shares)`.
- **Timestamps:** `exch_ts = local_ts = timestamp_us * 1000` (data is in µs; hftbacktest wants ns; we have no exch/local split → set equal, then add a synthetic +Xms feed latency via the order-latency model to keep latency positive per the validation rule). Sort by ts; merge depth+trade streams chronologically.
- **size==0 handling:** drop or forward-fill — but this is exactly the unreliability that breaks the queue model.
- Write to npz/`.npz` structured array, build `BacktestAsset` per token, run a `HashMapMarketDepthBacktest`.

**Effort to a working single-slug npz: S–M (≈half a day).** The mapping is not the problem. **Effort to a *trustworthy maker fill* on this data: effectively impossible** — no amount of conversion creates the depth-behind-best that the queue models require. So the conversion is cheap but the output is not more credible than a custom sim.

## 4. Verdict + effort

**Use a custom conservative price-through fill sim for Polymarket. Do NOT route Polymarket through hftbacktest.**

Rationale:
- Our Polymarket book is L1 + 50% null sizes. hftbacktest's entire edge (queue-aware partial fills from L2/L3 depth decrements) cannot be exercised on L1 — it silently degrades to price-through, so we'd carry a heavy Rust/Numba dependency and conversion pipeline for a result we can reproduce in ~50 lines of pandas with full transparency.
- A custom sim lets us be honestly conservative (e.g. only fill a resting maker quote when a trade prints *through* the price, or when best crosses AND assume we're last in queue), which matches the project's GROUND-TRUTH posture better than a black-box queue estimate fed garbage depth.
- **Reserve hftbacktest for Hyperliquid later:** HL has real L2 book deltas + trade tape (HL S3 archive `l2Book` + trades). That is the data hftbacktest is designed for, and the install is already proven on Py3.14.

**Effort estimates:**
- hftbacktest Polymarket conversion: **S–M** to wire, but **NOT worth it** (low-value output).
- Custom conservative maker fill sim (price-through on BBO+trades, per-token, fee = 0.07 curve winner-only): **S** (~half day), and it's the right tool.
- hftbacktest for Hyperliquid (future): **M** (real L2 conversion from HL archive), install already done.

---

### Install state
- `hftbacktest 2.4.4` installed (user site, `--no-deps`) against numpy 2.4.3 / numba 0.65.0 on `C:/Python314`. Imports verified.
- Probe script: `C:\Users\alexandre bandarra\Desktop\global\_hft_probe.py` (schema/zero-rate checks; safe to delete).
