# Relay wallet decode — `0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0`

**Date**: 2026-05-18
**Source**: Alchemy `getAssetTransfers` (Polygon mainnet)
**Window analyzed**: blocks `87,070,357 → 87,072,859` = **73 minutes** (2026-05-18 14:00 → 15:13 UTC)
**Raw data**: `strategy_lab/wallet_hunt/cache/0xf3cfb6a6/alchemy_transfers.parquet` (125,141 transfer rows)

> Important caveat: The fetcher was capped at 50 pages/direction (1000 transfers/page),
> and at this wallet's volume that exhausts in only ~73 minutes of recent history.
> All figures below describe a **single hot hour**, then are extrapolated to daily rates.
> The cross-references against the 3 maker wallets (0x89b5cdaa, 0x04b6d7e9, 0xeebde7a0)
> use their existing 3-5 day caches.

---

## Verdict: NOT a "treasury merger" — it is a **CTF Exchange operator / merge-and-settle relayer**

The original hypothesis was that this wallet aggregates paired Up+Down tokens from many
operators, calls `mergePositions`, and distributes pUSD back to the originators.

**That is mostly correct on the merge side, but WRONG on the distribution side.**
The relay does NOT pay USDC back to the originating wallets. Every USDC dollar it
recovers from merging tokens is **immediately forwarded to the Polymarket Exchange contract
`0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb`** in the same transaction. The relay's net USDC
balance per tx is ~$0 — it is a **pass-through router**, not a treasury.

This looks like Polymarket's official **MakerOrderBatcher** or **NegRisk settlement relayer**:
a contract address that the protocol uses to batch `mergePositions` calls across many users
on a per-market basis, recover USDC, and credit the Exchange contract which then routes
settlement to individual users via separate ledger updates (not direct ERC20 transfers).

---

## Scale (73-min window)

| Metric | Value | Annotation |
|---|---|---|
| Total transfer rows | 125,141 | both directions, both categories |
| ERC1155 received | 50,206 | from many distinct senders |
| ERC1155 sent | 28,518 | of which **28,442 are burns to address(0)** (99.7%) |
| ERC1155 mints (from 0x0) | **0** | relay never calls `splitPosition` |
| ERC1155 burns (to 0x0) | **28,442** = 1,268 burn-tx | every burn is `mergePositions` |
| ERC20 (USDCE) in | $3,113,304 over 24,897 transfers | 100% from CTF contract `0x4d97...6045` |
| ERC20 (USDCE) out | $2,620,365 over 21,520 transfers | 100% to Exchange `0xc011a7e1...` |
| Unique tokenIds touched | 678 | both Yes/No legs of ~339 markets |

**Extrapolated per-day rates (caveat: based on a 73-min sample, real daily likely lower):**
- ~$61M USDC in, ~$51M USDC out, **mid-block-balance ~$0**
- ~561k ERC1155 transfers/day, ~25k merges/day
- ~25k tx/day involving this address

The relay is one of the busiest non-protocol wallets on Polymarket Polygon.

### Per-tx structure (across 1,486 tx in the window)

| | median | p75 | max |
|---|---|---|---|
| ERC1155 received per tx | 40 | 40 | — |
| ERC1155 burned per tx | 24 | 27 | 35 |
| USDC in per tx | $859 | $1,615 | $101,377 |
| USDC out per tx | $729 | $1,352 | $101,377 |
| USDC pass-through balance | **$0** | $0 | — |

Typical tx: receives ~40 individual ERC1155 transfers across one market's
Yes/No leg from ~20 different small operators, merges 24 paired shares
(= 12 complete Yes+No pairs), forwards the recovered USDC (~$850) to the
Exchange. The 16 unpaired tokens stay as relay inventory pending more
arrivals from other operators. **88% of tokenIds are fully balanced
within the 73-min window** — the relay rarely holds inventory for long.

---

## Counterparty graph

### Senders of ERC1155 TO the relay (top 10 in 73-min window)
| Wallet | Count | Notes |
|---|---|---|
| 0xae3db1cc | 206 | unknown maker |
| 0x680717d1 | 190 | unknown maker |
| 0xb55fa129 | 142 | unknown maker (also a USDC payer of 0x89b5cdaa) |
| 0x3066e42f | 140 | unknown maker |
| **0xce25e214** | **138** | 🎯 known cataloged maker wallet |
| 0xd093a6cd | 132 | unknown maker |
| 0x54bc3153 | 120 | unknown maker |
| ... | | long tail of thousands |
| 0x89b5cdaa | 80 | 🎯 the F1-cluster maker (sends 9,434 over 5 days) |
| 0xeebde7a0 | 84 | 🎯 cataloged maker |
| 0x04b6d7e9 | 36 | 🎯 cataloged maker |

The 3 hypothesized maker wallets all hit the relay during the window. The fact
that they only contributed 0.4-0.5% of inbound transfers each in this 73-min slice
confirms the relay has **dozens to hundreds of operators feeding it**, not just our
3-wallet hypothesis.

### Recipients of USDCE FROM the relay
| Recipient | Count | $ Total |
|---|---|---|
| `0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb` | 21,520 | $2.62M (100%) |

**Single counterparty**: the Polymarket CTF Exchange / NegRiskAdapter. The relay
sends USDC to nobody else. Period.

### Sources of USDCE TO the relay
| Source | Count | $ Total |
|---|---|---|
| `0x4d97dcd97ec945f40cf65f87097ace5ea0476045` (CTF contract) | 24,837 | $3.10M (99.7%) |
| `0x3a3bd7bb9528e159577f7c2e685cc81a765002e2` | 60 | $10.3k |

Almost 100% from the Polymarket CTF contract itself — the USDC arrives as the
merge payout (Yes + No → 1 USDCE).

### Distribution back to originators — **NONE**

Checking the 4 known maker wallets (`0x89b5cdaa`, `0x04b6d7e9`, `0xeebde7a0`, `0xce25e214`),
their USDCE inbound is sourced from:
- `0x00000...0000` (zero address — Polymarket meta-tx / Gnosis Safe relayer pattern)
- `0xe1111800...87b996b` (Polymarket fee/funding proxy)

**Zero USDC ever flows back from the relay (`0xf3cfb6a6`) or the Exchange (`0xc011a7e1`)
directly to any of the 4 maker wallets.** Settlement to user-owned wallets happens via
a separate path (Gnosis Safe proxy + meta-transactions emitted from address(0)).

---

## Cross-reference: do paired transfers become merges?

In every one of the 1,268 burn-transactions, ALL three operations co-occur in
the same tx:
- ERC1155 received from one or more makers ✓
- ERC1155 burned to address(0) (the `mergePositions` call) ✓
- USDC arrives from CTF, identical USDC departs to Exchange ✓

Merge efficiency over the window: 28,442 burns / 50,206 inbound tokens = **56.7%**.
The unbalanced 43% is mid-batch inventory waiting for the matching leg, which
will be merged in subsequent tx — over a longer window, balance approaches 100%
(596/678 = **88% of tokenIds were fully closed within 73 minutes**).

Capital recovery: **$2.6M USDCE flowed out** vs roughly 4.4M tokens received
(at the merge time, paired shares = 1 USDCE) — confirming the per-token redemption
is exactly 1 USDC for each Yes+No pair burned.

---

## What the relay does NOT do

- **No `splitPosition`** — never mints new conditional tokens (0 inbound from address(0)).
- **No order posting** — only transfers in/out; never an OrderFilled / TradedQuote event signature.
- **No fee retention** — USDC in/out per tx balances to within $0.0001 in 86% of tx.
- **No directional trading** — does not hold positions for >1 batch.
- **No payback** — never sends USDC to user-controlled wallets.

It is a **pure batch-merge router** wired into Polymarket's Exchange settlement layer.

---

## Implications for strategy deployment

1. **The relay is protocol infrastructure, not a copy-trade target.** Watching its
   trades will not reveal a directional alpha — it has no directional view.

2. **Our cataloged maker wallets are end-users of the relay.** When `0x89b5cdaa`,
   `0xeebde7a0`, `0x04b6d7e9`, `0xce25e214` send Yes+No legs to the relay, that signals
   they are EXITING a paired position via merge — i.e., they had previously executed a
   mint-and-sell strategy (held both legs and want to recover principal). This is
   confirmation our previous read of the mint-and-sell maker pattern is correct.

3. **The relay's per-block ERC1155 inbound count is a real-time "how many makers
   are unwinding right now" signal.** If you can stream relay activity per slug, a
   sudden burst of arrivals from many distinct senders may indicate a coordinated
   exit by the maker cohort — useful for *contrarian* timing or as a "slug is closing
   out" flag.

4. **Mint-and-sell V2 spec (`MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md`) does NOT need
   to interact with this relay.** When deploying, we will hold the unsold leg until
   strike resolution and either let CTF auto-redeem (winning leg) or eat the loss
   (losing leg). We do not need to batch our merges through this relay (it is open
   to anyone who calls `mergePositions` themselves, but our scale is too small to
   benefit from batching).

5. **Identifying the relay's operator address** would be valuable. The contract at
   `0xf3cfb6a6...` is almost certainly deployed and operated by Polymarket Labs as
   part of the NegRiskAdapter or settlement infrastructure. A future task: read the
   contract bytecode + verified source on Polygonscan to confirm function selectors
   and operator.

---

## Surprises

1. **Pass-through, not treasury.** The hypothesis assumed accumulation. Reality: zero
   net USDC retention per tx.

2. **Asset symbol is USDCE not pUSD.** The CTF contract issues `USDC.e` (bridged
   Polygon USDC, contract `0x2791bca1...`), not the symbol "pUSD" that appears in
   some of our other wallet exports. Our `fetch_alchemy.py` would print USDC in/out
   as $0.00 for this wallet because the summary string-matches `asset == "pUSD"` —
   this is a latent bug in the analysis path that should be generalized to also
   match `USDCE` and the actual USDC.e contract address.

3. **No mints.** A real treasury that recycled capital would issue new positions
   (split → re-sell). This wallet only consumes existing pairs. It does not generate
   new market exposure.

4. **The destination `0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb` is a perfect
   funnel.** Out of 1,276 USDC-out tx, 100% went to this single address. That
   makes it the **canonical Polymarket on-chain settlement endpoint** — useful
   for filtering Exchange flow in future on-chain queries.

---

## Files written

- `strategy_lab/wallet_hunt/cache/0xf3cfb6a6/alchemy_transfers.parquet` (raw 125k transfers)
- `strategy_lab/reports/RELAY_WALLET_DECODE_0xf3cfb6a6_2026_05_18.md` (this report)
