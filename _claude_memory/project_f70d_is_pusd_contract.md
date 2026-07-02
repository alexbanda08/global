---
name: f70d-is-pusd-contract
description: "0xf70da97812cb96acdf810712aa562db8dfa3dbef is the Polymarket pUSD deposit contract, NOT an \"F1 treasury\" — it funds ALL wallets"
metadata: 
  node_type: memory
  type: project
  originSessionId: b0cf2009-b4b4-4bf6-9bdd-9dd3566b683d
---

`0xf70da97812cb96acdf810712aa562db8dfa3dbef` = Polymarket's pUSD deposit/funding contract. Every
Polymarket wallet's first USDC inflow comes from it (UI deposits route through it).

**Why:** Operator corrected 2026-06-12 when I flagged wallet `0xb945945d` (article author
`@l5zn1bwom8etsk`) as "seeded by the F1 treasury" — the inflow was just a normal $9,985 UI deposit.

**How to apply:** Never use an inflow from `0xf70da97812` as evidence of wallet clustering,
common ownership, or "treasury seeding". The CLAUDE.md / WALLET_CATALOG claim that the "F1
treasury seeded 4+ strategy variants" via this address is invalid for the same reason — any
cluster inference must come from other signals (shared relay wallets, direct wallet-to-wallet
transfers, behavioral fingerprints).
