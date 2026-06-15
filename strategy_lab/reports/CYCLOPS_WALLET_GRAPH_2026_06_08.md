# Cyclops Wallet — On-Chain Counterparty Graph (2026-06-08)

**Wallet:** `0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c` ("Cyclops.exe" / Limp-Pitcher, BTC-5m favorite-hold bot)
**Source:** Alchemy `getAssetTransfers`, Polygon mainnet, full history, both directions, all categories.
**Scripts:** `strategy_lab/wallet_hunt/cyclops_graph_2026_06_08.py` (+ raw dumps in `cache/_cyclops_graph/transfers_{from,to}.json`).
**Volume:** 2,990 outgoing transfers (40 counterparties) · 4,445 incoming (113 counterparties).

## ⭐ HEADLINE: Cyclops's real operator cluster is SMALL — one funder EOA + one sibling bot
**Method (corrects a first draft):** classified each counterparty empirically — `eth_getCode`
(contract vs EOA) + counterparty BREADTH + Polymarket `/activity` — instead of trusting a
catalog label. A shared Polymarket contract/onramp touches hundreds–thousands of distinct
users → NOT a unique tie. Only narrow, Cyclops-specific wallets count.

| address | type | breadth | PM trades | verdict |
|---|---|---|---|---|
| **`0x2e1e827fbec36e1dad4a2ee4ed3650d191a7278e`** | EOA | **14–26 cps** | 0 (pure funder) | ✅ **THE OPERATOR'S FUNDING/CONTROLLER WALLET** — seeds Cyclops **657×** with gas (MATIC) + USDC. Narrow → genuinely Cyclops-specific. |
| **`0x886a78bfd638ea1e73db9da0b6fb7f4dfa7af1f4`** | contract | — | **12 (btc-5m ×11, bnb-5m ×1)** | ✅ **CONFIRMED SIBLING BOT** — same btc-5m up/down strategy, funded by the same EOA `0x2e1e827f`. Small/newer (last trade 06-03). |
| `0xc0de9f5c6d80fa4a4f848a087b9f994c7cd319f5` | contract | — | 2 (last 05-26) | ⚠️ weak maybe-sibling (2 PM trades, same funder) |

⇒ **The Cyclops cluster = funder `0x2e1e827f` → {Cyclops, 0x886a78bfd, (maybe 0xc0de9f5c6)}.** That's it.

## ❌ RETRACTED — these are SHARED Polymarket infra, NOT a unique tie (first-draft error)
| address | what it actually is | proof |
|---|---|---|
| `0xf70da97812cb96acdf810712aa562db8dfa3dbef` | shared funder/onramp EOA | **827 distinct counterparties** — funds hundreds of wallets, not just Cyclops's operator. (also funds `0x2e1e827f` itself) |
| `0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0` | shared relay contract | breadth **378** — many wallets use it |
| `0xe3f18acc55091e2c48d883fc8c8413319d4ab7b0` | Polymarket settlement contract | breadth **654** |
| `0xe111180000…` | NegRisk CTF Exchange (settlement rail) | known false-positive (CAPSTONE) |

The earlier "F1 treasury / `0xb27bc932` $254k HFT cluster" claim is **WRONG** — those links go
through shared infra (`f70da978`/`f3cfb6a6`) that hundreds of unrelated wallets also touch.
Operator-uniqueness requires the NARROW funder `0x2e1e827f`, which only seeds Cyclops + ~2 bots.

## System / noise (ignore)
CTF Exchange `0x4bfb…982e`, ConditionalTokens `0x4d97…6045`, USDC `0x2791…`/`0x3c49…`,
1inch `0x1111…2a65`, Seaport `0x0000…1ff3`, ~50 MATIC gas-relayers, 2 telegram-spam airdrops.

## The wallets (answer)
```
CYCLOPS  = 0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c   (btc-5m/15m bot, active to 06-08)
FUNDER   = 0x2e1e827fbec36e1dad4a2ee4ed3650d191a7278e   (operator gas+USDC funder EOA, 0 trades)
SIBLING  = 0x886a78bfd638ea1e73db9da0b6fb7f4dfa7af1f4   (btc-5m up/down bot, SAME funder — confirmed)
maybe    = 0xc0de9f5c6d80fa4a4f848a087b9f994c7cd319f5   (2 PM trades, same funder — weak)
```

## Sibling decode + root trace (2026-06-08, `cyclops_root_trace_2026_06_08.py`)
**(A) `0x886a78bfd` = a Cyclops TWIN.** 12 trades, btc-5m(11)+bnb-5m(1), ran **Jun 2–3 only**
then stopped. **$3.02 median, entry 0.560, 58% favorite** — identical near-coinflip
favorite-hold signature to Cyclops. Lifetime **−$20.27** (bleeding, same as Cyclops). A
short-lived test/variant of the same strategy under the same operator, abandoned after 2 days.

**(B) Trace UP from funder `0x2e1e827f` dead-ends in shared infra.** Every source is
high-breadth shared: onramp `0xf70da978` (716), gas svc `0x91604f59` (273), 1inch
`0x1111…2a65` (479), DEX `0x0f7ae28d` (613) / `0x697b456…` (1098). The operator tops up via
onramp + DEX swaps → **no attributable personal root EOA** (KYC-gated beyond this). Lone
non-shared source = `0x0115dcdd16b8aeac365b0c9e88f5241b3fa47f79` (contract, breadth 11, USDC) —
worth a glance, not a personal wallet.

## FINAL cluster
```
untraceable source : onramp 0xf70da978 + 1inch + gas svcs   (shared, NOT attributable)
FUNDER (op hub)    : 0x2e1e827fbec36e1dad4a2ee4ed3650d191a7278e   gas+USDC, 0 trades
BOTS               : 0xf69af0b9…  Cyclops (btc-5m/15m, active, lifetime -$198)
                     0x886a78bfd… twin    (btc-5m, ran Jun2-3, -$20, abandoned)
                     0xc0de9f5c6… weak    (2 PM trades)
```
Cluster is SMALL and LOSING (Cyclops −$198, twin −$20). Not a profitable operator to copy —
confirms the WATCH (not COPY) tag. Scripts: `cyclops_{classify_counterparties,fleet,
siblings_verify,root_trace}_2026_06_08.py`.
