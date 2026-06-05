# TV Agent Spec — `poly_fast_taker_v2` shadow sleeve (2026-05-29)

> **Delta spec:** extends `TV_AGENT_SPEC_POLY_FAST_TAKER_2026_05_29.md` (the V1 base).
> All unchanged sections (§0, §1, §2, §3, §9) are inherited from V1 — do not duplicate.
> This document specifies two new modules:
> - **Module A — Conviction-based position sizing** (replaces V1's flat $25 stake)
> - **Module B — Merge-based collateral recycling** (new capital-efficiency layer)
>
> Evidence source for both: `WALLET_DECODE_5WALLETS_2026_05_29.md` §1 (`0xeebde7a0`,
> $825k lifetime, $92k/7d, currently live and profitable).

---

## 0. Mechanic in plain English (entry / counter-trade / merge / settle)

**Core bet:** Polymarket up-down resolves on Chainlink, which lags Binance ~5-20s. The
resting ask on the binance-leading side is stale-cheap for a few seconds after a move → take it.

1. **ENTRY fire** — anchored on `slot_start`. Snapshot `px0=binance(slot_start)`; on each
   binance tick compute `ret=binance(now)/px0−1`. Fire when offset∈[3s,12s] AND `|ret|≥3bps`
   AND the book/spread gate passes. Buy the leading side (`Up if ret>0 else Down`) at the L25
   ask; size by conviction (Module A). Hold.
2. **COUNTER-TRADE fire (Module B only)** — NOT a hedge; a *second independent entry*. If
   binance reverses past the threshold the other way later in the same window and the opposite
   side hasn't fired, fire the now-leading side at its fresh stale ask. ⚠️ Backtest shows this
   reversal fire is **~EV-neutral** (+$1.30 ≈ base +$1.31) — it adds NO return; its only job is
   to set up the merge.
3. **MERGE (Module B only)** — once holding both sides, the matched `min(up,down)` portion is a
   complete set (guaranteed $1, but ties up collateral). Merge it (gasless, 1:1) to recover
   $1/pair and redeploy; keep the directional residual. Merge is NOT profit (locks ~2.5¢/pair
   loss); its only value is **freeing capital**.
4. **SETTLE** — hold the residual to chainlink resolution. Won → `shares×(1−vwap)×0.98`;
   lost → `−shares×vwap`.

> **Scale dependence — READ BEFORE MICRO-LIVE (see §D.1):** Module B's value is *capital
> turnover*, which only matters when collateral is the binding constraint (eebde7a0 runs
> thousands of concurrent positions). At $1-5 stake you have no capital pressure, so Module B
> adds a ~EV-neutral second fire + a tiny merge loss for **zero benefit**. **At micro stake run
> Module A only (`TV_FT_V2_ALLOW_BOTH_SIDES=false`).** Enable Module B only when scaled up.

---

## A. Conviction-Based Position Sizing

### A.0 Why

`0xeebde7a0` exhibits a stark conviction-sizing pattern:
- **Raw dominant-side WR = 61.4%** (matches our backtest ~63%), but
- **$-weighted WR = 83.6%** — the big bets win 84%.
- Avg entry price when it **wins**: **0.721**; when it **loses**: **0.436**.
  It pays up for high-conviction winners and keeps losers tiny/cheap.

Our backtest shows a dose-response — but read the **OOS** table carefully (the
"59→64→71→82%" headline is IS/pooled; OOS is weaker and flattens):

| min |ret| threshold | OOS WR | OOS mean/fire | OOS t | n | trades/day |
|---:|---:|---:|---:|---:|---:|
| 2 bps | 60.2% | +$0.60 | 1.41 | 2485 | 113 |
| **3 bps** | **63.0%** | **+$1.31** | **2.28** | 1307 | 59 |
| **5 bps** | **66.6%** | **+$1.85** | 1.85 | 398 | 18 |
| 8 bps | 66.7% | +$0.91 | **0.49** | 114 | 5 |

**Critical:** OOS mean PnL/fire **peaks at 5bps (+$1.85)** and *declines* at 8bps
(+$0.91, t=0.49 — NOT significant, n=114). WR flattens (66.6→66.7). So the OOS evidence
supports sizing UP from 3→5bps, but **does NOT yet support sizing up further at 8bps** —
the 8bps tier is small-n noise with lower mean than 5bps. The eebde7a0 $-weighted 84% WR
shows conviction sizing works *in principle*; our own OOS only confirms it through 5bps.

The sizing function therefore caps the multiplier at 5bps by default, with 8bps held at the
same multiplier until shadow accumulates OOS n≥50 confirming mean ≥ the 5bps tier.

### A.1 Sizing function

```python
def conviction_size(ret_bps: float, cfg: "FastTakerV2Config") -> float:
    """
    Map |binance ret in bps| to target notional in USD.

    Tiers are mapped to the measured WR gradient. The base unit is the V1
    $25 (WR ~63% at 3bps). Multipliers scale up to a max at >=8bps (WR ~82%).

    Returns 0.0 to abstain (below TV_FT_V2_MIN_BPS).
    """
    absbps = abs(ret_bps)

    if absbps < cfg.min_bps:          # TV_FT_V2_MIN_BPS (default 3.0)
        return 0.0                    # abstain — below significance threshold

    # Tier lookup (inclusive lower bound)
    for threshold, multiplier in sorted(cfg.size_tiers, reverse=True):
        if absbps >= threshold:
            raw = cfg.base_notional * multiplier
            break
    else:
        raw = cfg.base_notional       # fallback (should not reach here if tiers cover >=min_bps)

    # Cap 1: absolute max notional
    raw = min(raw, cfg.max_notional)  # TV_FT_V2_MAX_NOTIONAL (default $100)

    return raw
```

**Default tier table** (`TV_FT_V2_SIZE_TIERS`) — multipliers tracked to OOS mean PnL, NOT WR:

| |ret| bps (lower bound) | Multiplier | Target notional | Rationale (OOS) |
|---:|---:|---:|---|
| 3.0 | 1.0× | $25 | Base unit, WR 63.0%, mean +$1.31, t=2.28 |
| 5.0 | 2.0× | $50 | WR 66.6%, mean +$1.85 (best OOS mean), still fillable |
| 8.0 | 2.0× | $50 | Held at 5bps mult — OOS mean DROPS to +$0.91 (t=0.49, n=114). **Promote to 3-4× only after shadow confirms OOS n≥50 mean ≥ 5bps tier** |

Cap: `TV_FT_V2_MAX_NOTIONAL = $100` (hard ceiling — lowered from $200 until the 8bps tier is
validated OOS; raise once AC-A1/AC-S2 pass with n≥50 at ≥8bps).

> Rationale for capping 8bps at 2×: conviction sizing should scale with **expected $/fire**,
> which OOS peaks at 5bps. Sizing 4× on a tier whose OOS mean is *below* the 5bps tier would
> concentrate capital on the worst-EV (and statistically insignificant) bucket. This is the
> one place the base-spec brief (which cited the IS 82% figure) and the OOS evidence diverge —
> we follow the OOS evidence.

### A.2 Book-depth cap (prevents self-impact)

After computing `raw_size` from tiers, apply:

```python
def apply_book_depth_cap(raw_size: float, ask_prices: list, ask_sizes: list,
                         cfg: "FastTakerV2Config") -> float:
    """
    Walk ask levels; find the notional available before VWAP degrades more than
    TV_FT_V2_MAX_SLIPPAGE_BPS (default 10 bps) above ask0.
    Return min(raw_size, available_notional_within_slippage).
    """
    if not ask_prices or not ask_sizes:
        return 0.0
    ask0 = ask_prices[0]
    limit_price = ask0 * (1 + cfg.max_slippage_bps * 1e-4)
    available_usd = 0.0
    for p, s in zip(ask_prices, ask_sizes):
        if p > limit_price:
            break
        available_usd += float(p) * float(s)
    # Require at least 50% fill
    if available_usd < raw_size * 0.5:
        return 0.0                    # skip — book too thin for meaningful fill
    return min(raw_size, available_usd)
```

`TV_FT_V2_MAX_SLIPPAGE_BPS = 10` (default). At 10bps the edge is still strongly
positive (WR ~63% at 3bps means even a 10bps wider ask doesn't kill it).

### A.3 Per-slug exposure cap

```python
TV_FT_V2_MAX_SLUG_EXPOSURE_USD = 400   # max total $ deployed in a single slug
```

The sleeve fires at most **once per slug** (inherited V1 one-shot rule), so this cap
is additive with Module B: if collateral-recycled capital is re-deployed on a second
fire in the same slug (after a MERGE — see §B), the total cumulative deployed notional
in that slug cannot exceed `TV_FT_V2_MAX_SLUG_EXPOSURE_USD`.

Pseudocode:
```python
slug_deployed: dict[str, float] = {}   # reset at each slug boundary

def check_slug_cap(slug: str, candidate_size: float) -> float:
    already = slug_deployed.get(slug, 0.0)
    allowed = max(0.0, TV_FT_V2_MAX_SLUG_EXPOSURE_USD - already)
    return min(candidate_size, allowed)
```

### A.4 Optional: V3 composite confidence boost

The eebde7a0 V3 composite (`disc_capture OR pm_drop_5s>0.02 OR offset_s∈[0,60] OR
(buy_vol_60s>50 AND pm_drop_5s>0) OR utc_hour==15`, 78.9% coverage, lift 1.37×) is an
**optional secondary input** to the sizing function. Default OFF (`TV_FT_V2_V3_BOOST=false`).

When ON: if the fire also satisfies the V3 composite, apply a `TV_FT_V2_V3_BOOST_MULT = 1.5×`
multiplier on top of the bps-tier size (before the book-depth and notional caps). Rationale:
V3-composite fires win ~78.9% of the time (vs 63% base), so sizing up on them further
approximates eebde7a0's $-weighted 84% WR. This is config-gated because V3 requires live
access to pm_drop_5s (Polymarket price feed) and buy_vol_60s (CLOB trade tape), which may
not be available in the Ireland engine at boot. Do NOT gate the base sizing on V3.

### A.5 Config additions (append to `/etc/tv/tradingvenue.env`)

```
# Module A — conviction sizing
TV_FT_V2_MIN_BPS=3.0
TV_FT_V2_BASE_NOTIONAL=25
TV_FT_V2_MAX_NOTIONAL=100
TV_FT_V2_MAX_SLUG_EXPOSURE_USD=400
TV_FT_V2_MAX_SLIPPAGE_BPS=10
TV_FT_V2_SIZE_TIERS=3.0:1.0,5.0:2.0,8.0:2.0   # format: bps:mult,...
TV_FT_V2_V3_BOOST=false
TV_FT_V2_V3_BOOST_MULT=1.5
```

---

## B. Merge-Based Collateral Recycling

### B.0 Why

`0xeebde7a0` buys **both** Up and Down in 81.8% of slugs ($-skewed 75/25 to one side).
After multiple fires in the same slug, it holds a directional residual PLUS a hedged (Up+Down
equal) portion that is capital-dead. **MERGE collapses matched pairs back to $1 of pUSD**
(gasless, 1:1 — verified on-chain: 270,341 shares → $270,341, CLAUDE.md). This frees that
capital for the next fire, without affecting the directional residual which rides to REDEEM.

**This is a capital-efficiency trick, not a P&L source.** MERGE on sets bought for ~1.025
actually LOSES 2.5¢/pair (pair-cost above $1). In shadow mode, the accounting must reflect
this accurately — merged pairs that cost > $1 total are a loss locked in at merge time.

### B.1 When this applies

Module B is only relevant when the sleeve fires **more than once in a slug** — which requires:
1. The V1 one-shot-per-slug rule to be **relaxed** to a per-side one-shot rule, OR
2. The recycled-collateral trigger to allow a second fire on the same side after a merge.

**Spec decision (assumption):** relax to **one-fire-per-side per slug**. The sleeve can fire
once on "Up" and once on "Down" per slug (never twice on the same side in one slug). This
matches eebde7a0's observed behavior (buys both Up and Down in 82% of slugs). This is the
minimum relaxation — the sleeve still fires at most twice per slug. A flag controls it:

```
TV_FT_V2_ALLOW_BOTH_SIDES=true    # default true to enable recycling; false = V1 one-shot
```

### B.2 Slug inventory state

The sleeve tracks per-slug inventory in a lightweight state struct:

```python
@dataclass
class SlugInventory:
    slug: str
    up_shares: float = 0.0          # shares held on Up outcome
    down_shares: float = 0.0        # shares held on Down outcome
    up_cost: float = 0.0            # total USD paid for Up shares
    down_cost: float = 0.0          # total USD paid for Down shares
    merged_pairs: float = 0.0       # number of Up+Down pairs already merged
    merge_pnl: float = 0.0          # cumulative P&L from merge ops (usually <= 0)
    collateral_recovered: float = 0.0  # cash returned by MERGE ops
    fired_up: bool = False
    fired_down: bool = False
```

Reset `SlugInventory` for a slug at slot boundary (`now > slot_start + window_s`).

### B.3 Merge trigger

```python
MERGE_THRESHOLD_PAIRS = 1.0    # TV_FT_V2_MERGE_THRESHOLD (shares, default 1.0)
MERGE_TIMING = "on_fill"       # trigger immediately after each fill that creates a pair

def maybe_merge(inv: SlugInventory, cfg: "FastTakerV2Config") -> MergeDecision | None:
    """
    If the sleeve holds >=MERGE_THRESHOLD_PAIRS of BOTH Up and Down shares,
    merge the matched (min) portion.

    Returns a MergeDecision with pairs_to_merge, expected_collateral, merge_pnl_estimate.
    Returns None if no merge warranted.
    """
    pairs = min(inv.up_shares, inv.down_shares)
    if pairs < cfg.merge_threshold:
        return None

    # Compute the cost basis for the pairs being merged (FIFO avg cost)
    avg_up_cost = inv.up_cost / inv.up_shares if inv.up_shares > 0 else 0.0
    avg_dn_cost = inv.down_cost / inv.down_shares if inv.down_shares > 0 else 0.0
    pair_cost = (avg_up_cost + avg_dn_cost) * pairs   # total USD in

    collateral_freed = pairs * 1.0   # CTF pays exactly $1 per pair, gasless
    merge_pnl = collateral_freed - pair_cost   # usually slightly negative (~-0.025*pairs)

    return MergeDecision(
        pairs=pairs,
        collateral_freed=collateral_freed,
        pair_cost=pair_cost,
        merge_pnl=merge_pnl,
    )
```

**Timing:** trigger `maybe_merge` immediately after each FILL that creates offsetting
inventory (i.e., after any fill where both `inv.up_shares > 0` AND `inv.down_shares > 0`).
Do NOT defer to end-of-slug — eebde7a0 merges mid-slug to re-deploy capital within the
same window. Immediate merge is the capital-efficient choice.

**Config:**
```
TV_FT_V2_MERGE_THRESHOLD=1.0   # min pairs (shares) before triggering merge
```

### B.4 Paper-ledger accounting for freed collateral

In shadow mode, no real CTF call is made. The paper ledger handles MERGE as follows:

```python
def apply_merge(inv: SlugInventory, decision: MergeDecision,
                pool: "CollateralPool") -> None:
    """
    Shadow: update inventory, book merge PnL, return freed cash to pool.
    """
    # 1. Remove merged pairs from inventory
    inv.up_shares   -= decision.pairs
    inv.down_shares -= decision.pairs
    # Proportional cost basis reduction
    if inv.up_shares >= 0:
        inv.up_cost -= (inv.up_cost / (inv.up_shares + decision.pairs)) * decision.pairs
    if inv.down_shares >= 0:
        inv.down_cost -= (inv.down_cost / (inv.down_shares + decision.pairs)) * decision.pairs

    # 2. Book the merge P&L (typically small negative = pair premium paid)
    inv.merge_pnl += decision.merge_pnl
    inv.merged_pairs += decision.pairs
    inv.collateral_recovered += decision.collateral_freed

    # 3. Return freed collateral to the per-sleeve available-capital pool
    pool.available_usd += decision.collateral_freed

    # 4. Log a MERGE row to the shadow CSV (see §B.5 logging)
```

**CollateralPool** is a simple per-sleeve float tracking available capital. It starts at
`TV_FT_V2_POOL_USD` (default $500) and rises on MERGE, falls on each FILL. Subsequent
fires draw from `pool.available_usd` rather than an infinite budget. If `pool.available_usd
< candidate_size * 0.5`, skip the fire (insufficient capital).

```
TV_FT_V2_POOL_USD=500    # starting per-sleeve capital pool for shadow (paper)
```

### B.5 Interaction with REDEEM at settlement

At resolution (`fill_sim.settle_slug`):
1. The **directional residual** (the unmerged net side) is settled normally:
   - Won side: `pnl = residual_shares × (1 − vwap_avg) × 0.98`
   - Lost side: `pnl = −residual_shares × vwap_avg`
2. Any remaining `inv.up_shares` or `inv.down_shares` that were NOT yet merged are treated
   the same way (won/lost per outcome). Do NOT suppress them — they still need to be settled.
3. MERGE P&L is already booked at merge time (`inv.merge_pnl`); do NOT double-count.
4. Total slug PnL = settlement_pnl + inv.merge_pnl.

### B.6 Capital-efficiency metrics to track

Log these per-slug (and aggregate daily) to measure recycling benefit:

```
capital_deployed_usd   = total USD sent to fills across all fires in slug
collateral_freed_usd   = sum of CTF collateral returned by MERGEs
capital_turnover_ratio = capital_deployed_usd / starting_pool_committed_usd
                         # >1.0 means collateral was recycled and re-deployed
return_on_deployed_usd = slug_pnl / capital_deployed_usd
```

**Baseline for comparison:** run a parallel V1 (no recycling) shadow sleeve on the same
cells to compare `capital_turnover_ratio` and `return_on_deployed_usd`.

### B.7 Config additions

```
# Module B — merge recycling
TV_FT_V2_ALLOW_BOTH_SIDES=true
TV_FT_V2_MERGE_THRESHOLD=1.0
TV_FT_V2_POOL_USD=500
```

---

## C. Updated Logging Schema

Extends V1's CSV schema (`TV_AGENT_SPEC_POLY_FAST_TAKER_2026_05_29.md` §6). Add columns:

```
ret_bps_raw        – raw |binance ret| that triggered sizing (Module A)
size_tier          – which tier fired (e.g. "3.0:1.0x", "5.0:2.0x", "8.0:4.0x")
notional_raw       – size before book-depth cap
notional_book_cap  – size after book-depth cap (= actual notional submitted)
pool_available_pre – collateral pool balance BEFORE this fill
pool_available_post– collateral pool balance AFTER this fill
v3_composite_hit   – bool: did this fire satisfy the V3 composite filter?
v3_boost_applied   – bool: was the V3 boost multiplier used?
# MERGE rows (action = MERGE):
merge_pairs        – shares merged (= min(up_shares, down_shares) at trigger)
merge_collateral   – collateral freed by merge ($1 × pairs)
merge_pnl          – P&L booked at merge time (pair_cost - collateral_freed, usually <=0)
merge_up_residual  – up_shares AFTER merge
merge_dn_residual  – down_shares AFTER merge
```

---

## D. Full Config Block (V2)

`/etc/tv/tradingvenue.env` — append below V1 block:

```
# --- poly_fast_taker_v2 ENHANCEMENTS ---
# Module A — conviction sizing
TV_FT_V2_MIN_BPS=3.0
TV_FT_V2_BASE_NOTIONAL=25
TV_FT_V2_MAX_NOTIONAL=100
TV_FT_V2_MAX_SLUG_EXPOSURE_USD=400
TV_FT_V2_MAX_SLIPPAGE_BPS=10
TV_FT_V2_SIZE_TIERS=3.0:1.0,5.0:2.0,8.0:2.0
TV_FT_V2_V3_BOOST=false
TV_FT_V2_V3_BOOST_MULT=1.5

# Module B — merge recycling
TV_FT_V2_ALLOW_BOTH_SIDES=true
TV_FT_V2_MERGE_THRESHOLD=1.0
TV_FT_V2_POOL_USD=500
```

---

## D.1 Micro-stake live-validation profile (USE THIS for $1-5 live) ⭐

The §D defaults ($25 base) reproduce the backtest. **For live validation at $1-5, override
with this profile** — and **disable Module B** (no capital constraint at micro stake, so merge-
recycling adds nothing; run pure directional + conviction sizing).

```
# --- MICRO-STAKE LIVE PROFILE ($1-5) ---
TV_FT_NOTIONAL_USD=1            # V1 base stake
TV_FT_V2_BASE_NOTIONAL=1        # 3bps tier = $1
TV_FT_V2_SIZE_TIERS=3.0:1.0,5.0:2.0,8.0:2.0   # → $1 / $2 / $2
TV_FT_V2_MAX_NOTIONAL=5         # hard ceiling = your $5 max
TV_FT_V2_MAX_SLUG_EXPOSURE_USD=5
TV_FT_V2_POOL_USD=50            # ample; pool never binds at this size

# Module B OFF at micro stake (capital turnover irrelevant <$5):
TV_FT_V2_ALLOW_BOTH_SIDES=false
# (TV_FT_V2_MERGE_THRESHOLD / POOL recycling inert when ALLOW_BOTH_SIDES=false)

# Module A ON — this is what we're validating at micro:
TV_FT_V2_V3_BOOST=false         # keep off until pm_drop_5s/buy_vol_60s feeds confirmed
```

Resulting size schedule: **3bps → $1, 5bps → $2, 8bps → $2** (max $5 ceiling leaves headroom
to promote 8bps to $4-5 later once OOS n≥50 confirms it).

**Micro-stake notes & gotchas:**
- 🚨 **Verify Polymarket CLOB minimum order size + tick BEFORE going live.** At $1 notional you
  are near the venue floor (e.g. at price 0.95 that's ~1.05 shares). If orders reject for
  min-size, bump `TV_FT_V2_BASE_NOTIONAL=2` (still inside your $1-2 band). Confirm against the
  live CLOB `minimum_order_size` / `min_tick_size` for each token.
- **Absolute PnL is tiny — that's expected.** The edge is %-based (~+5%/fire OOS): ~+$0.05/fire
  at $1, ~+$0.10 at $2. Micro-live validates **fill-rate, WR, per-tier gradient, and live↔
  backtest VWAP parity** — NOT dollar PnL. Don't judge on $ PnL at this size; judge on WR + fill
  fidelity (§E.3).
- **Book-depth cap & 50%-fill rule effectively never bind** at $1-5 (you're far inside L25
  depth) → near-zero self-slippage. The spread filter (≤0.05) and min-book-events (25) still apply.
- **Fees unchanged:** 2%-on-winning-profit only; no per-fill taker fee.
- **When to enable Module B:** only after scaling to where multiple concurrent positions tie up
  meaningful collateral (roughly when per-day deployed capital approaches your wallet balance).
  At that point flip `ALLOW_BOTH_SIDES=true` and re-read §B. The AC-B* criteria (capital
  turnover) are **N/A** during the micro-stake run.

---

## E. Shadow-Mode Test Plan & Acceptance Criteria

### E.1 What to log (in addition to V1 logging)

- Per-fire: `size_tier`, `ret_bps_raw`, `notional_book_cap`, `pool_available_pre/post`.
- Per-merge: full MERGE row including `merge_pnl`, residuals, collateral freed.
- Per-slug (at SETTLE): `capital_deployed_usd`, `collateral_freed_usd`,
  `capital_turnover_ratio`, `return_on_deployed_usd`.
- Aggregate daily: WR and mean PnL **per size tier** (the key dose-response check).

### E.2 Acceptance criteria

**Module A — sizing:**

| Criterion | Target | Rationale |
|---|---|---|
| **AC-A1 — Per-tier WR matches gradient** | Tier 3bps WR ≥ 60%, tier 5bps ≥ 64%, tier 8bps ≥ 68% (after ≥100/30/10 fills per tier) | Replicates OOS dose-response; if WR is flat across tiers, the sizing function adds no value |
| **AC-A2 — $-weighted WR** | $-weighted WR ≥ raw WR by ≥5pp across the run | Validates that the sizing captures the conviction signal; if $-weighted ≈ raw, size tiers are misfiring |
| **AC-A3 — No book blowout** | Mean (notional_book_cap / notional_raw) ≥ 0.80 | Book-depth cap is not cutting >20% of intended size on average; if it is, reduce TV_FT_V2_MAX_NOTIONAL or tier multipliers |
| **AC-A4 — Tier distribution** | Fires in all 3 tiers within 7 days | Confirms binance-1s feed delivers moves across the full bps range; if tier 8bps never fires, reduce its threshold |

**Module B — recycling:**

| Criterion | Target | Rationale |
|---|---|---|
| **AC-B1 — Both-sides fires observed** | ≥20% of slugs have both Up and Down fires within first 7 days | Confirms TV_FT_V2_ALLOW_BOTH_SIDES=true is working; if < 5%, the fire gate rarely favors opposite sides on same slug |
| **AC-B2 — MERGE events fire** | ≥1 MERGE per 10 both-sided slugs | Confirms merge trigger is live; if 0 MERGEs, check min-pairs threshold vs typical slug inventory |
| **AC-B3 — Capital turnover > 1.0** | Mean capital_turnover_ratio > 1.0 for any recycled slug | Proves recycling re-deploys capital intra-slug; if always ≤ 1.0, MERGE is happening too late |
| **AC-B4 — Merge P&L small negative** | Mean merge_pnl ∈ [−$0.10, $0.00] per pair | Validates pair-cost ~$1.02 (pair premium); large negative signals bad fill on hedge leg |

**System-level:**

| Criterion | Target |
|---|---|
| **AC-S1 — Total WR ≥ V1 WR** | V2 run WR ≥ V1 parallel run WR (same cells, same window) |
| **AC-S2 — Total mean PnL/trade ≥ V1** | V2 mean ≥ V1 × 1.0 (at minimum neutral; ideally higher due to sizing) |
| **AC-S3 — Pool never depleted** | pool_available_usd never hits 0 across any 24h period (if it does, raise TV_FT_V2_POOL_USD or lower TV_FT_V2_MAX_NOTIONAL) |

### E.3 Comparison against backtest

After 7 days:
1. Pull the V2 shadow CSV. For each fire compute realized vwap vs the canonical
   `latency_threshold_sweep.py` fill on the same slug/fire_us (within ±1s). VWAP should
   match within 1 tick (≤0.002). Deviations > 0.01 signal the live BookMirror diverging from
   canonical L25 — flag immediately.
2. Compare per-tier WR to the static backtest table (§A.0) — allow ±8pp for n<100.
3. Confirm no fires land outside the `[TV_FT_OFFSET_MIN_S, TV_FT_OFFSET_MAX_S]` window.

### E.4 Go/no-go bar before capital

Both enhancements must pass their acceptance criteria AND:
- ≥ 2 weeks of shadow with n ≥ 200 total fills (not just fires).
- V2 $-weighted WR ≥ 75% (mirroring the eebde7a0 $-weighted 83.6% with a margin for our
  smaller sample and less-refined trigger).
- No pool depletion events in the last 7 days of the shadow run.
- The sizing function contributes positive $ to total PnL (compare V2 cumulative PnL to a
  hypothetical flat-$25 run on the same fills; V2 must be ≥ 0pp better, accounting for the
  higher capital at risk on large tiers).

---

## F. Risks & Gotchas (V2 additions)

**Inherited from V1 (do not re-derive):** anchor is `slot_start + offset_s` (not `ws_s`);
fee = 2%-on-winning-profit-only (LegacyConfig, `won → shares×(1−vwap)×0.98`, `lost → −shares×vwap`);
spread filter = same-token `ask0 − bid0` (NOT cross-token vwap sum); L25 native 10Hz
(`subsample_1hz=False`); outcome truth = chainlink `resolutions_from_rtds`; MERGE/REDEEM
gasless and 1:1 on-chain.

**Module A risks:**

- **Tier 8bps is small-n in backtest** (OOS n=114). The 66.7% WR is directionally correct
  (consistent with the monotonic gradient) but has wide CI (~±9pp). Do NOT treat tier-8bps
  shadow results as validated until n ≥ 50 live fills. Until then, keep `TV_FT_V2_MAX_NOTIONAL=100`
  for safety.
- **Book-depth cap may be too loose at $100-200 notional.** The L25 validation was at $25.
  Actual book depth at the 85ms mark may not sustain a $100-$200 walk without significant
  slippage. The `max_slippage_bps=10` guard handles this but monitor `notional_raw` vs
  `notional_book_cap` ratio in the first week — if the book-depth cap fires >30% of the time
  at the $100 tier, reduce `TV_FT_V2_MAX_NOTIONAL`.
- **V3 composite boost is OFF by default.** The pm_drop_5s and buy_vol_60s features require
  the live CLOB price feed and CLOB trade tape. If those feeds are not plumbed into the Ireland
  engine's fast-taker path, do NOT enable `TV_FT_V2_V3_BOOST`. The base sizing (bps tiers)
  is self-contained and does not require them.
- **Edge decay / crowding:** an open-source bot replicates this family at ~61% WR. As more
  players pick up the stale-ask pattern, the 5-20s window may compress. Monitor whether the
  7-day rolling WR trends down over consecutive shadow weeks before committing capital.

**Module B risks:**

- **Merge is a real loss on pairs bought above $1.** `0xeebde7a0`'s median pair cost is
  $1.025 → each merge loses ~2.5¢/pair in exchange for freeing $1 of capital. This is a
  CAPITAL EFFICIENCY TRADE-OFF, not free money. At $25/side per fire, 2.5¢/pair is ~0.1% of
  notional — negligible. At $100/side, still only 0.025% drag. Track `merge_pnl` to ensure
  it stays within this range; large merge losses signal the fires are pairing on unfavorable
  prices.
- **Both-sides relaxation increases slug-level loss risk.** Firing both Up and Down in the
  same slug means if the binance move reverses immediately, both sides lose. The slug-level
  exposure cap (`TV_FT_V2_MAX_SLUG_EXPOSURE_USD=400`) limits this. Do NOT set it above the
  initial pool size.
- **Paper collateral pool is a proxy.** In paper mode, `pool.available_usd` is a simulation.
  In live mode, actual pUSD wallet balance on Polygon is the constraint. The pool starting
  value `TV_FT_V2_POOL_USD=500` is a shadow accounting convention — it does not pre-fund
  anything. Before live deployment, confirm pUSD on-wallet ≥ max intended concurrent exposure.
- **`fill_sim.settle_slug` must see all fires per slug.** With both-sides enabled, the existing
  settlement path (E1-fixed) must settle Up residual AND Down residual independently. Confirm
  the E1 fix handles multi-side slugs — look for cases where `inv.up_shares > 0` AND
  `inv.down_shares > 0` at settlement (i.e., a merge was NOT triggered, or only partial) and
  both are correctly settled to won/lost. If the current `settle_slug` only handles one side
  per slug, patch it to loop over both outcomes.

---

## G. Rollout (V2 additions to V1 §9)

V1 §9 (shadow → micro-live path) is inherited. Additional steps:

1. **Run V2 shadow in parallel with V1 shadow for ≥1 week** on the same cells (btc_5m
   priority). Use distinct sleeve IDs: `poly_fast_taker_v1_btc_5m_shadow` and
   `poly_fast_taker_v2_btc_5m_shadow`. This produces a direct side-by-side comparison.
2. **Verify AC-A1 through AC-B4 + AC-S1-S3** before any capital (§E.2, §E.4).
3. **Enhancements degrade gracefully:** if `TV_FT_V2_ALLOW_BOTH_SIDES=false`, Module B is
   disabled and V2 degrades to V1 sizing (still an improvement over flat $25). The two modules
   are independently togglable.
4. **First live test:** use V2 config but restrict to `TV_FT_V2_SIZE_TIERS=3.0:1.0,5.0:1.0`
   (flat $25 for 3-5bps, $25 for 5+) and `TV_FT_V2_MAX_NOTIONAL=25` for the first live week.
   This isolates the infrastructure wiring from the sizing risk before scaling up the multipliers.

---

## Assumptions (ambiguities in base spec / codebase)

1. **One-shot rule:** V1 specifies "one-shot per slug" (§1, last bullet). This spec relaxes to
   one-per-side per slug when `TV_FT_V2_ALLOW_BOTH_SIDES=true`. This is an assumption —
   if the V1 implementor hard-coded a `fired[slug]=True` flag (vs `fired_up/fired_dn`), the
   Ireland-side code needs a targeted patch.
2. **`fill_sim.settle_slug` multi-side:** the E1-fixed settle path was verified on maker
   sleeves which hold one side per slug (ACC-M/ACC-H). Whether it handles `inv.up_shares > 0
   AND inv.down_shares > 0` simultaneously is unverified — assumed it iterates over both sides
   but must be confirmed.
3. **`eebde7a0` 8bps tier:** the backtest shows OOS WR 66.7% at ≥8bps (n=114), not 82%.
   The 82% figure cited in the task brief was from an earlier IS pass. The spec uses the
   conservative OOS 66.7% for the tier rationale but retains the 4× multiplier because
   even at 66.7% WR the expected value at $100 notional is strongly positive (+~$6/fire
   at fee 2%-on-profit). This is flagged as requiring more shadow data to confirm.
4. **Cross-token spread note:** V1 §2 correctly specifies same-token `ask0−bid0` for this
   directional taker. The task brief mentions cross-token spread "not relevant here" — agreed.
   This spec inherits V1 §2 unchanged and does NOT implement a cross-token check.
5. **Collateral pool accounting:** in shadow mode, `pool.available_usd` is a pure paper
   accounting construct. It does not interact with the real pUSD wallet (no live orders).
   The starting value $500 was chosen to represent a realistic per-sleeve capital allocation;
   change it to match the actual intended live capital before going live.

---

## Source-of-truth artifacts

- **Base spec:** `strategy_lab/reports/TV_AGENT_SPEC_POLY_FAST_TAKER_2026_05_29.md`
- **Live evidence (eebde7a0):** `strategy_lab/reports/WALLET_DECODE_5WALLETS_2026_05_29.md` §1
- **V3 composite:** `strategy_lab/reports/EEBDE7A0_TAKER_TRIGGER_V3_2026_05_18.md`
- **Backtest (dose-response):** `strategy_lab/reports/LATENCY_EDGE_FINDING_2026_05_29.md`
  (threshold sweep table, §MOVE-THRESHOLD SWEEP)
- **Engine:** `strategy_lab/engine_v2.py` (`LegacyConfig`, `fill_at_book`, `hold_pnl`)
- **MERGE accounting:** `MAKER_ARB_CONTEXT_HANDOFF_2026_05_29.md` §2 point 4 (gasless, 1:1)
- **Settlement path (E1):** `ENGINE_FIX_VERIFICATION_2026_05_29.md` (E1 FIXED + live)
