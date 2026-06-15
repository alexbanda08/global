# B945 On-Chain Transaction Taxonomy — 2026-06-12

**Wallet:** `0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68`  
**Data:** `cache/0xb945945d/alchemy_transfers.parquet` — 357,113 transfers, 157,647 unique txs, Mar 16 → Jun 11 2026  
**Script:** `strategy_lab/wallet_hunt/_b945_tx_decode.py`  
**Artifacts:** `cache/0xb945945d/{tx_taxonomy,merge_timing,orderfilled_sample,orderfilled_sample_early}.parquet`

> **⚠️ REVISED SAME DAY (v2).** Two v1 conclusions corrected after challenge (see §10):
> 1. **"Pure CLOB taker" was WRONG** — OrderFilled receipt logs show **~63% of fills are MAKER**
>    (resting bids), 37% taker. Classes renamed `TAKER_BUY → CLOB_BUY` (composition ≠ side).
> 2. **MERGE timing decided:** 100% POST-resolution (median +43s after slot end), 0% mid-window —
>    merge is the pUSD-era redemption mechanism, NOT an intra-window recycling loop.
> 3. **USDC_IN was misclassified:** 200 of 214 txs are NegRisk-era paired redemptions
>    (new class `NEGRISK_REDEEM`, $140,876) — closes the income-reconciliation gap to 0.17%.

---

## §1 Wallet Architecture Finding

**b945 IS A GNOSIS SAFE 1.3.0 PROXY — NOT AN EOA.**

| Field | Value |
|-------|-------|
| Contract type | Gnosis Safe 1.3.0 proxy (~62-byte minimal forwarder) |
| Implementation (slot 0) | `0xe51abdf814f8854941b9fe8e3a4f65cab4e7a4a8` (Safe singleton) |
| VERSION() return | "1.3.0" (confirmed) |
| Threshold | 1-of-N |
| getOwners() | Returns None (Safe uses a module or non-standard owner registry) |
| EIP-1967 impl slot | Empty (uses slot 0 / masterCopy pattern) |

**Tx submission is via:**
- **ERC-4337 UserOperations** (MERGE, some TAKER_BUY): bundler EOAs call `handleOps` on custom EntryPoint `0x84ba8962`; the UserOp itself originates from b945 Safe
- **Polymarket relayer EOAs** (REDEEM): call `execTransaction` directly on b945 Safe
- **Bundler/relayer EOAs** (TAKER_BUY): call `matchOrders` on NegRisk CTF Exchange with b945's signed order; b945 doesn't send the tx itself

The operator's private key(s) sign orders/Safe-txs off-chain; Polymarket's relayer infrastructure submits on-chain. b945 is never the raw `tx.from`.

---

## §2 Complete Transaction Taxonomy (v2 — corrected classes)

| Class | Txs | Spent | Received | Shares | Date Range |
|-------|-----|-------|----------|--------|------------|
| CLOB_BUY (~63% maker / 37% taker, see §10.2) | 131,117 | $1,108,194 (pUSD) | — | 2,332,270 in | Apr 28 – Jun 11 |
| CLOB_BUY_EARLY (~64% maker, see §10.2) | 24,889 | $218,433 (USDC.e) | — | 461,987 in | Mar 19 – Apr 28 |
| MERGE (post-resolution, see §10.1) | 1,307 | — | $1,131,135 (pUSD) | 2,331,779 merged | Apr 28 – Jun 11 |
| REDEEM (CTF burn path) | 78 | — | $78,351 (USDC.e) | 163,468 burned | Mar 19 – Apr 25 |
| NEGRISK_REDEEM (adapter path, ex-"USDC_IN") | 200 | — | $140,876 (USDC.e) | 298,323 out | Mar 19 – Apr 28 |
| USDC_IN (true deposits) | 13 | — | $16,814 | — | Mar 16 – Jun 10 |
| PUSD_IN_ONLY | 38 | — | $2,894 (pUSD) | — | Apr 29 – Jun 11 |
| OTHER | 5 | — | $101 | — | Apr 6 – Jun 11 |
| **TOTAL** | **157,647** | **$1,326,627** | **$1,370,171** | | |

---

## §3 Calldata Evidence Per Class

### CLOB_BUY (131,117 txs, Apr 28+, pUSD era) — v1 name "TAKER_BUY" retracted

- **tx.to:** `0xe111180000d2663c0091e4f400237545b87b996b` (NegRisk CTF Exchange)
- **Selector:** `0x3c2b4399` = `matchOrders(bytes32,(uint256,...),(uint256,...)[],uint256,uint256[],uint256,uint256[])` (4byte confirmed)
- **tx.from:** random bundler/relayer EOAs (NOT b945)
- **Pattern:** b945 signs an order off-chain; Polymarket operator submits `matchOrders` (which always bundles one taker order + N maker orders — the selector does NOT determine b945's side); b945 receives ERC1155, pays pUSD
- **Side (from OrderFilled logs, §10.2):** **62.8% ± 3.8% MAKER** (his resting bid hit by a crossing seller/buyer), 37.2% TAKER (his order crossed)
- **Evidence:** pUSD flows `b945 → 0xe111` (payment), ERC1155 flows `0xe111 → b945` (shares received)

### CLOB_BUY_EARLY (24,889 txs, Mar 19 – Apr 28, USDC.e era) — v1 name "TAKER_BUY_EARLY"

- **tx.to:** `0xe3f18acc55091e2c48d883fc8c8413319d4ab7b0` (NegRiskAdapter, code length 6,306 bytes)
- **Selector:** `0x2287e350` = `matchOrders((uint256,...),(uint256,...)[],uint256,uint256,uint256[],uint256,uint256[])` (4byte confirmed)
- **Pattern:** Same CLOB BUY mechanic but using USDC.e directly (pre-pUSD-era; ~64% maker per §10.2). Shares come from both `0x4bfb` (CTF Exchange) and `0xe3f1` (NegRiskAdapter)
- **Evidence:** USDC.e flows `b945 → 0x4bfb` ($218,332), ERC1155 flows from `0x4bfb` and `0xe3f1` → b945

### MERGE (1,307 txs, Apr 28+, pUSD era)

- **tx.to:** `0x84ba896235059fe27727eaa2695a9f99220d9a7e` (custom EntryPoint / AA account factory, 7,106 bytes)
- **Selector:** `0x765e827f` = `handleOps((address,uint256,bytes,bytes,bytes32,uint256,bytes32,bytes,bytes)[],address)` — **ERC-4337 UserOperation bundler**
- **tx.from:** random bundler EOAs (e.g. `0x9314005f`, `0xfa33439b`)
- **Inner call:** The UserOp from b945 calls `CTF.mergePositions()` (selector `0x9e7212ad`); this is wrapped inside the ERC-4337 call stack (not findable via simple calldata string search due to ABI encoding)
- **ERC1155 sent to:**
  - `0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0` (2,586 events) — Polymarket merge relay contract
  - `0xada100874d00e3331d00f2007a9c336a65009718` (142 events) — Polymarket merge helper v2
- **Result:** CTF burns ERC1155 pair → mints pUSD from `0x0` → delivers to b945
- **Receipt evidence:** Log from `0x0000000071727de22e5e9d8baf0edac6f37da032` (canonical ERC-4337 EntryPoint v0.6) with topic `0x49628fd1...` (UserOperationEvent) confirmed inside MERGE tx receipts
- **Log `0xb434294b...`** on `0xf3cfb` = Polymarket PositionsMerged event

### REDEEM (78 txs, Mar 19 – Apr 25)

- **tx.to:** `0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68` (b945 Safe itself)
- **Selector:** `0x6a761202` = `execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)` — **Gnosis Safe executeTransaction**
- **tx.from:** Various Polymarket relayer EOAs (`0xbefc8a81`, `0x714d785a`, `0x33662dae`, others — 14 unique submitters)
- **Inner call:** Contains `0x01b7037c` = `redeemPositions(address,bytes32,bytes32,uint256[])` in calldata (confirmed via string search)
- **Pattern:** Relayer submits pre-signed Safe transaction; Safe executes `CTF.redeemPositions()` which burns winner ERC1155 → delivers USDC.e to b945
- **Only in early era (Mar 19 – Apr 25):** Pre-pUSD era winners were redeemed as USDC.e. In pUSD era, resolution capture done via MERGE instead of REDEEM.

### NEGRISK_REDEEM (200 txs, Mar 19 – Apr 28) — v2 CORRECTION, was misfiled as "USDC_IN"

- **Composition:** b945 sends ERC1155 OUT (398 legs, 298,323 shares = paired Up+Down inventory)
  and receives USDC.e IN ($140,876) from `0x05cd9922a5d37fae921fc5dee280a9dbc4c3b393` (CONTRACT,
  25,626-byte code — a NegRisk redemption/payout vault, **NOT a funder**)
- **No 0x0 burn:** NegRisk wrapped positions redeem through the adapter path, so the ERC1155
  legs go to the vault instead of being burned to 0x0 — which is why v1's burn-based REDEEM
  detector missed them
- **$0.47/share average** = paired redemption (winner pays $1, loser $0, both legs surrendered)
- v1 called 0x05cd "main funder $140k" — WRONG; this is early-era redemption income

### USDC_IN (13 txs — true deposits only, v2)

- `0xf70da97812cb96acdf810712aa562db8dfa3dbef`: $9,985 (Polymarket pUSD deposit contract)
- `0xc417fd8e9661c0d2120b64a04bb3278c17e99db1`: $6,100 (his own cross-wallet transfer)
- Others: ~$729. **True external deposit base ≈ $10k–16k**, matching the PnL audit.

---

## §4 The $1.13M "Mint" Question — DEFINITIVELY RESOLVED

### Prior claim (incorrect)
`B945_PNL_AUDIT_2026_06_12.md` called the 1,360 `from=0x0` pUSD events "negRisk pUSD cycling (0x0 mints $1.13M)". `B945_MERGE_LOOP_VERIFY_2026_06_12.md` called them "1,360 SPLIT ops, USDC→pUSD via 0x4d97".

### What actually happened
**Both were wrong. These are `mergePositions` outputs, not `splitPosition` inputs.**

In ConditionalTokens, `mergePositions` is the reverse of `splitPosition`:
- `splitPosition(pUSD → CTF)`: CTF burns pUSD, mints 2× ERC1155 (from 0x0)
- `mergePositions(ERC1155 → CTF)`: CTF burns 2× ERC1155, **mints pUSD FROM 0x0** → delivers to caller

The 1,307 MERGE txs show:
1. b945 sends Up+Down ERC1155 OUT to `0xf3cfb` (Polymarket relay)
2. CTF burns them
3. CTF mints pUSD and delivers to b945 (`from=0x0, to=b945, asset=pUSD`)

This is **NOT minting new capital**. It is **recovering the USDC collateral** from paired positions — and §10.1 proves it happens exclusively POST-resolution (median +43s after slot end), i.e. it is the pUSD-era redemption mechanism, never a mid-window unwind.

### Confirmed: NO splitPosition calls
- Zero txs found where b945 sends pUSD TO 0x0 (the burn step of splitPosition)
- Zero txs found where pUSD goes to CTF contract directly
- `b945 pUSD → 0x0`: **0 rows** (confirmed exhaustive search)
- **b945 never calls splitPosition (never mints new position tokens from scratch)**

### The actual lifecycle (v2)
```
DEPOSIT: ~$10-16k USDC.e → b945 Safe (0xf70d pUSD contract + own cross-wallet)
  ↓
CLOB_BUY: buy Up+Down tokens on CLOB — ~63% as resting MAKER bids, ~37% as
          crossing TAKER (see §10.2); pUSD/USDC.e out, ERC1155 in
  ↓
HOLD TO RESOLUTION (no mid-window exit of any kind)
  ↓
REDEMPTION (three paths, all post-resolution):
  Path A (early era):  CTF redeemPositions winner-only → USDC.e ($78k)
  Path B (early era):  NegRisk adapter paired redemption via 0x05cd vault → USDC.e ($141k)
  Path C (pUSD era):   mergePositions both legs, median +43s after slot end → pUSD ($1.13M)
  ↓
CAPITAL RECYCLED into next window's CLOB_BUY
```

The MERGE pUSD return ($1.13M) closely tracks CLOB_BUY spend ($1.11M) week-by-week because the merges ARE the capital recovery from prior buys — recycled per-window cadence, not intra-window.

---

## §5 Volume/Timing Analysis

### Weekly flow (pUSD era, Apr 28+)

| Week | Taker pUSD Spent | Merge pUSD Returned | Net |
|------|-----------------|---------------------|-----|
| Apr 27 – May 3 | $209,465 | $223,073 | +$13,608 |
| May 4-10 | $206,702 | $204,285 | -$2,417 |
| May 11-17 | $113,109 | $114,205 | +$1,096 |
| May 18-24 | $156,402 | $157,523 | +$1,121 |
| May 25-31 | $129,086 | $136,782 | +$7,696 |
| Jun 1-7 | $196,554 | $198,537 | +$1,983 |
| Jun 8-14 | $96,878 | $96,730 | -$148 |

**Pattern:** merge_rcvd consistently exceeds taker_spent by $1k-$14k/week = net winning income from winning tokens resolving > 1.0 (i.e., the winner leg pays 1.0 not 0.5, so recovering both legs via merge + resolution yields profit on winner).

### Timeline of strategy phases
- **Mar 16 – Mar 19:** USDC.e deposits arrive ($140k from 0x05cd)
- **Mar 19 – Apr 25:** TAKER_BUY_EARLY + REDEEM era (USDC.e-denominated fills, winner redemptions)
- **Apr 28:** Hard cutover to pUSD system (no overlap)
- **Apr 28 – Jun 11:** TAKER_BUY (pUSD) + MERGE era (no REDEEM after Apr 25)

---

## §6 Does the Wallet Sell Minted Tokens Mid-Window?

**NO.** There is no evidence of mid-window sells of self-minted tokens because:

1. **b945 never calls splitPosition** — it cannot have freshly minted tokens to sell
2. The MERGE txs are 100% post-resolution (§10.1) — collateral recovery after settle, not pre-resolution liquidity manufacturing
3. **All 734 sampled OrderFilled events are BUY-side** (b945's order pays cash, receives tokens) — zero SELL fills in either era (§10.2). He never exits inventory on the book; everything is held to resolution.

The article's "split + sell the unwanted side" mechanic (mint-and-sell / liquidity manufacture) does **NOT apply to b945**. ~~b945 is a pure TAKER~~ **v2 correction: b945 is a maker-majority two-sided BIDDER** (~63% of fills are his resting bids getting hit, ~37% crossing taker fills — see §10.2). He buys both sides, holds to resolution, merges/redeems the pair back.

---

## §7 Revision to §8 Strategy Spec (B945_ARTICLE_INFRA_GAP_ANALYSIS)

The gap analysis §8 discussed building infrastructure to replicate b945's mechanic. Key revisions:

| Prior §8 Claim | Corrected |
|----------------|-----------|
| "b945 calls splitPosition (mints tokens)" | WRONG — b945 NEVER calls splitPosition |
| "The $1.13M 0x0-mint = pUSD cycling via 0x4d97" | WRONG — these are mergePositions RETURNS not INPUTS |
| "Needs CTF.splitPosition integration" | Not needed — just CLOB taker orders |
| "EOA with direct CTF calls" | WRONG — Gnosis Safe 1.3.0 + ERC-4337 infrastructure |
| "b945 submits txs itself" | WRONG — relayers/bundlers submit; b945 signs off-chain |

**What b945 actually does that IS replicable (v2):**
1. Fund a Gnosis Safe with USDC/pUSD
2. Place BUY orders on Polymarket CLOB (both Up+Down) — predominantly **resting GTC bids**
   (~63% of fills are maker), with ~37% crossing taker fills (price-following requotes that cross)
3. Hold everything to resolution (zero on-book sells, zero mid-window unwinds)
4. Post-resolution (+43s median): mergePositions via the Polymarket relay (ERC-4337 UserOp)
5. Recycle the returned pUSD into the next window's bids

No novel on-chain minting needed. The edge (if any) is in **queue position / quoting** and **market selection**, not in contract mechanics.

---

## §8 Key Addresses Reference

| Address | Role | Type |
|---------|------|------|
| `0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68` | b945 wallet (SUBJECT) | Gnosis Safe 1.3.0 proxy |
| `0xe51abdf814f8854941b9fe8e3a4f65cab4e7a4a8` | Safe implementation (singleton) | Contract |
| `0xe111180000d2663c0091e4f400237545b87b996b` | NegRisk CTF Exchange (pUSD era CLOB) | Contract |
| `0xe3f18acc55091e2c48d883fc8c8413319d4ab7b0` | NegRiskAdapter (USDC.e era CLOB) | Contract |
| `0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e` | CTF Exchange | Contract |
| `0x4d97dcd97ec945f40cf65f87097ace5ea0476045` | CTF ConditionalTokens | Contract |
| `0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb` | pUSD token | Contract |
| `0x2791bca1f2de4661ed88a30c99a7a9449aa84174` | USDC.e | Contract |
| `0x84ba896235059fe27727eaa2695a9f99220d9a7e` | Custom ERC-4337 EntryPoint/AccountFactory | Contract |
| `0x0000000071727De22E5E9d8BAf0edAc6f37da032` | ERC-4337 EntryPoint v0.6 (canonical) | Contract |
| `0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0` | Polymarket merge relay v1 | Contract |
| `0xada100874d00e3331d00f2007a9c336a65009718` | Polymarket merge helper v2 | Contract |
| `0x05cd9922a5d37fae921fc5dee280a9dbc4c3b393` | NegRisk redemption payout vault (v2: NOT a funder) | Contract (25.6KB code) |
| `0xf70da97812cb96acdf810712aa562db8dfa3dbef` | Polymarket pUSD deposit contract | Contract |

---

## §9 Summary (v2)

| Headline Finding | Evidence |
|-----------------|----------|
| b945 = Gnosis Safe 1.3.0 (not EOA) | `VERSION()` = "1.3.0"; slot-0 impl = 0xe51a; proxy bytecode = 62 bytes |
| NEVER calls splitPosition | 0 txs with pUSD→0x0 burn; 0 txs with ERC1155 minted from 0x0 alongside pUSD burn |
| $1.13M "0x0-mint" = mergePositions returns | from=0x0, asset=pUSD, inner selector=0x9e7212ad; ERC1155 sent OUT before pUSD received |
| **Maker-majority two-sided BIDDER (v2)** | OrderFilled receipt logs: 62.8%±3.8% maker / 37.2% taker (pUSD era n=634), 64.0%±9.4% maker (early era n=100); 100% BUY-side, fees only on taker fills |
| **Merge timing = 100% POST-resolution (v2)** | 2,689/2,689 mapped merge legs after slot end; median +43s, p95 +56min; 0 pre/mid-window |
| ERC-4337 AA infrastructure | MERGE txs via `handleOps` on `0x84ba8962`; ERC-4337 EntryPoint v0.6 logs in receipt |
| Capital recycling per-window, not intra-window | merge_pUSD_rcvd ≈ buy_pUSD_spent each week (within ~$14k; excess = winners) |
| No mid-window sells | 0 SELL fills in 734 sampled OrderFilled events; no mid-window merges |
| **Income reconciled to 0.17% (v2)** | merge $1,131,135 + CTF redeem $78,351 + NegRisk redeem $140,876 = $1,350,362 ≈ API REDEEM $1,352,604 |

**GROUND-TRUTH STATUS:** Calldata decoded, receipts fetched, transfer composition verified. The "SPLIT" and "pUSD cycling" claims in prior reports were inference errors from transfer shapes without calldata verification. This decode supersedes both `B945_PNL_AUDIT_2026_06_12.md §2` and `B945_MERGE_LOOP_VERIFY_2026_06_12.md` on the mint/split question. **v1's "pure CLOB taker" headline is retracted in v2 (§10.2).**

---

## §10 v2 ADDENDUM — merge timing, income reconciliation, true maker/taker split

### §10.1 MERGE timing vs slug windows — 100% POST-RESOLUTION (decisive)

Method: for each of the 2,730 ERC1155 legs burned in the 1,307 MERGE txs, mapped the token id
(hex→dec) to its slug via `token_lookup_ext.parquet` + `fill_tape_full.parquet` (combined map:
**2,689/2,730 legs = 98.5% mapped**, all `btc-updown-15m`); slug suffix = slot_start (s),
window = 900s; compared the merge tx block timestamp to the window.

| Bucket (merge_time − slot_END) | Legs | % |
|---|---|---|
| PRE-window (before slot_start) | 0 | 0.0% |
| MID-window (slot_start ≤ t < slot_end) | 0 | 0.0% |
| **POST-resolution (t ≥ slot_end)** | **2,689** | **100.0%** |

Distribution of merge lag after slot END: min +27s, p5 +31s, **median +43s**, p75 +68s,
p95 +56min, max 23.4d (a few stale-inventory cleanups). USD-weighted: identical (100% post).

**Verdict:** the activity-API "0 MERGE events" was an observability artifact (ERC-4337 UserOps
invisible to it), but the **article's intra-window capital-recycling loop is NOT real**. Merge
is simply the pUSD-era redemption mechanism for paired inventory, fired by an automated loop
~30–70s after window close. **Capital does NOT turn over intra-window — it is locked per
window. The TVRUST §8 plan stands** (no mid-window merge logic needed; a post-resolution
merge/redeem step IS needed — trivial, the Polymarket relay does it via ERC-4337).
Artifact: `cache/0xb945945d/merge_timing.parquet`.

### §10.2 True maker/taker split from OrderFilled receipt logs — "pure taker" RETRACTED

Method: `eth_getLogs` full enumeration blocked (Alchemy free tier caps getLogs at 10 blocks),
so stratified receipt sampling: **600 pUSD-era + 100 early-era fill txs, uniform over time**;
parsed `OrderFilled` logs where b945 is the indexed order-maker (topic2). Side rule (standard
CTFExchange semantics): event `taker` == exchange contract ⇒ b945's order was the crossing
TAKER order; `taker` == another wallet ⇒ b945's resting order was filled (MAKER).

| Era | Exchange / topic0 | n events | MAKER | TAKER | MAKER share (95% CI) |
|---|---|---|---|---|---|
| pUSD (Apr 28–Jun 11) | `0xe111` / `0xd543adfd…` | 634 | 398 | 236 | **62.8% ± 3.8%** |
| USDC.e (Mar 19–Apr 28) | `0x4bfb` / `0xd0a08e8c…` | 100 | 64 | 36 | **64.0% ± 9.4%** |

- By USD (pUSD era): MAKER 57.9% ($3,022 of $5,221 sampled) — maker fills slightly smaller.
- **Direction: 100% BUY in both eras** (every order has makerAsset = cash) — zero on-book sells,
  consistent with hold-to-resolution.
- **Fees: charged ONLY on taker fills** in the pUSD era ($55.01 on $2,199 taker USD ≈ 2.5%;
  $0.00 on all 398 maker fills) — explains the MAKER_REBATE events and confirms never applying
  taker fees to his maker fills (memory rule).
- Reconciles the prior estimates: ML/book inferred 35–47% maker — true maker share is HIGHER
  (~63%); the gap-analysis §8 "~40% of fills end up taker" is **confirmed: 37.2% ± 3.8%**.

**Corrected identity: b945 is a maker-majority two-sided BIDDER** (early-placed GTC bid ladders
that get hit ~63% of the time, crossing the spread for the other ~37%), not a "pure taker".
The `CLOB_BUY` class name replaces v1's `TAKER_BUY` (composition cannot determine side).
Artifacts: `cache/0xb945945d/orderfilled_sample{,_early}.parquet`.

### §10.3 Income reconciliation — gap closed from $143k to $2.2k (0.17%)

| Component | On-chain |
|---|---|
| MERGE pUSD (pUSD era) | $1,131,135 |
| REDEEM via CTF burn (early era) | $78,351 |
| **NEGRISK_REDEEM via 0x05cd vault (early era — v1 misfiled as "funder deposits")** | **$140,876** |
| **Total on-chain redemption income (thru Jun 11 14:46)** | **$1,350,362** |
| Data-API REDEEM (2,041 events, thru Jun 12) | $1,352,604 |
| **Residual gap** | **$2,242 (0.17%)** |

The v1 $143k gap was the 200 misclassified NegRisk paired redemptions. Residual $2.2k is
boundary-window + event-valuation noise (API window extends ~1 day later, which adds ~$19.8k,
offset by ~$17.5k of small per-event valuation differences between API REDEEM accounting and
raw chain transfer values) — flagged approximate, not exact; immaterial to all conclusions.
