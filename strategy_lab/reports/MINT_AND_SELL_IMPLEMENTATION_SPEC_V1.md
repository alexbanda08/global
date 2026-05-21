# Mint-and-Sell Bot — Complete Implementation Spec v1

_2026-05-17. Single source of truth for implementing the mint-and-sell
maker bot. Consolidates everything decoded from wallet chain-data analysis
+ corrected fee model + verified Polymarket API specifics. Target audience:
TV agent building the live engine + paper-trade simulator._

## 0. Executive summary

**What we're building**: a market-making bot that exploits the structural
mispricing `best_ask(Up) + best_ask(Down) > $1` on Polymarket up-down
crypto markets by minting pair tokens on-chain and selling both sides as
a maker on the CLOB.

**Empirical proof**: 4 chain-decoded wallets running this strategy:
- 0xeebde7a0 — $344k/day
- 0x04b6d7e9 — $212k/day
- 0x89b5cdaa — $10k/day
- 0xf7f0b0b1 — $281/day

**Verified strategy parameters from chain data**:
- Median sum_asks at fire: **$1.010**
- Median notional per fire: **$3-6**
- Fires per slug: **30-170**
- Fire-to-fire cadence: **sub-second median** (top wallets at 0-1000ms)
- Pre-slot-start firing: **0%** (big wallets wait for slot_start, post within 4-10s)
- Pre-mint strategy: confirmed (0x89b5cdaa: 1 mint TX → 1500 sells)

**Key infrastructure correction**: Polymarket CLOB runs on **AWS eu-west-2
(London)**. Ireland → London is <2ms RTT. The user's existing Ireland
server is near-optimal. US East would be ~130ms RTT (uncompetitive).

---

## 1. Strategy mechanics (mechanical, no abstraction)

### 1.1 Market structure

Polymarket up-down market (e.g. `btc-updown-15m-1778509800`):
- Fixed 15-minute window (or 5-minute for the faster cell)
- At `slot_start`: Chainlink oracle records the asset's "strike" price
- At `slot_end` (= slot_start + 900s for 15m): Chainlink records "settlement" price
- `settlement > strike` → Up wins (Up tokens redeem for $1, Down for $0)
- `settlement < strike` → Down wins (mirror)

Two ERC-1155 tokens per market with the same `condition_id`:
- `Up` token (specific `token_id_up`)
- `Down` token (specific `token_id_down`)

**Invariant**: 1 Up + 1 Down = $1 USDC via the CTF (Conditional Token
Framework) contract. The CTF guarantees you can `splitPosition($N) → N
Up + N Down`, or `mergePositions(N pairs) → $N USDC`. Always.

### 1.2 Edge thesis (where money comes from)

When informed takers (e.g. binance momentum traders) buy aggressively on
one side, both `best_ask(Up)` and `best_ask(Down)` can drift such that
`sum_asks > $1.00`. This is a structural mispricing — anyone who can
mint pairs from $1 can sell both sides for `sum_asks` and capture the
gap (less fees).

At sum_asks = $1.010 per pair-share, with Polymarket's verified fee
model:

```
edge_per_pair_share = (sum_asks − 1.0)
                    + maker_rebate(ask_up) + maker_rebate(ask_dn)

maker_rebate(p) = REBATE_SHARE × FEE_RATE × p × (1 − p)
                = 0.20 × 0.07 × p × (1 − p)        for crypto markets

At ask_up = ask_dn ≈ $0.505:
  rebate_per_leg = 0.20 × 0.07 × 0.505 × 0.495 = $0.0035 per share
  edge_per_pair_share = $0.010 + 2 × $0.0035 = $0.017
```

**Per BOTH-fill at $2.5 notional: +$0.0425 of locked-in profit.**

### 1.3 Fire sequence (mechanical)

When the gate triggers at time `t`:

```
[1] MINT  (on-chain Polygon tx — already done at slot_start, see §1.4):
        — Drawing from pre-minted inventory; no per-fire mint

[2] POST sell on Up (Polymarket CLOB, off-chain EIP-712 signed order):
        side = SELL
        token_id = <Up token_id>
        price = <current best_ask_up>       ← match best, get queue priority
        size = N_pairs (e.g. 2.5)
        order_type = GTC                    ← Good Till Cancelled, or GTD for 60s
        expiration_us = t + 60_000_000      (if GTD)
        signature = EIP712.sign(...)

[3] POST sell on Down (mirror of [2]):
        side = SELL
        token_id = <Down token_id>
        price = <current best_ask_dn>
        size = N_pairs
        ...

[4] WAIT (passive monitoring, 60s window):
        For each leg:
          If taker BUYs at our price → leg FILLS
            → cash in: N_pairs × ask + N_pairs × maker_rebate(ask)
          If 60s pass with no fill → cancel via DELETE /order/<id>
        After 60s:
          If BOTH filled: arbitrage captured, inventory unchanged
          If ONE filled: kept N_pairs of the unfilled side as inventory
          If NEITHER:  no inventory change (still in pre-minted pool)
```

### 1.4 Slug lifecycle (orchestration across 15min)

```
T - 30s (slot_start - 30s):
    Subscribe to WS for new slug's Up + Down books
    Pre-compute token_ids, condition_id, fee schedule for this slug

T = 0 (slot_start, Chainlink records strike):
    MINT (one big splitPosition for the whole slug's expected volume):
        call CTF.splitPosition(condition_id, USDC=$N_total)
        e.g. $25 → 25 Up tokens + 25 Down tokens in wallet
        Wait for 1 block confirmation (~2s)

T = +5 to T = +895 (entire slug window):
    OrderManager runs main loop:
      on every WS book update:
        compute sum_asks = best_ask_up + best_ask_dn
        if sum_asks ≥ $1.005 AND inventory available:
          desired_orders = {
            (Up, best_ask_up, fire_size),
            (Down, best_ask_dn, fire_size)
          }
        else:
          desired_orders = {}    ← cancel any active

        diff against current_orders → submit changes

T = +900 (slot_end, Chainlink records settlement):
    Determine winner (read settlement value via Polymarket /markets API or chain)

T = +905 to T = +920 (post-settlement cleanup):
    Cancel any still-active orders
    Compute pair_inventory = min(Up_held, Down_held)
    Compute single_inventory = max(Up_held, Down_held) − min(...)
    Call CTF.mergePositions(condition_id, pair_inventory) → recover $pair × $1 USDC
    Call CTF.redeemPositions(condition_id, winning_side, single_inventory_winning)
        → recover $single_winning × $1 USDC
    Losing single tokens: worth $0, leave them (auto-burn or ignore)
    Persist cycle PnL to log
```

---

## 2. Polymarket API specifics (verified from docs)

### 2.1 Endpoints

```
REST base:       https://clob.polymarket.com
WS market:       wss://ws-subscriptions-clob.polymarket.com/ws/market
WS user:         wss://ws-subscriptions-clob.polymarket.com/ws/user
Data API:        https://data-api.polymarket.com
RTDS WS (price): wss://ws-live-data.polymarket.com  (~100ms feed)

Polygon RPC:     https://polygon-mainnet.g.alchemy.com/v2/<KEY>
                 (already provisioned per project — key in repo)

CTF Exchange:    0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
CTF (CF):        0x4D97DCd97eC945f40cF65F87097ACe5EA0476045
USDC (PoS):      0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
Negative-Risk:   0xC5d563A36AE78145C45a50134d48A1215220f80a (different exchange)
```

### 2.2 Authentication (two layers)

**L1 — Wallet signing (EIP-712 with private key)**
- Used ONCE to derive L2 credentials
- Also used per-order to sign the EIP-712 order message

**L2 — HMAC-SHA256 (API credentials)**
- API key + secret + passphrase (derived via L1 once)
- Required on every REST request (orders, cancels, queries)

**Signature types** (set when initializing client):

| Type | Value | Use case |
|---|---|---|
| `EOA` | 0 | Standalone EOA (you sign + pay own gas) |
| `POLY_PROXY` | 1 | Polymarket proxy wallet |
| `GNOSIS_SAFE` | 2 | Existing Safe wallet |
| `POLY_1271` | 3 | **New API users → deposit wallets (RECOMMENDED)** |

For v1, use signature type **`POLY_1271`** (deposit wallet) — Polymarket's
recommended path for new bots. This avoids gas management and gives you
gasless trading.

### 2.3 Order types

```
GTC — Good Till Cancelled (sits on book until cancelled)
GTD — Good Till Date (auto-expires at expiration_us timestamp)
FOK — Fill Or Kill (taker order: fully fill at limit or cancel entirely)
IOC — Immediate Or Cancel (taker order: fill what's available, cancel rest)
FAK — Fill And Kill (similar to IOC)
```

For mint-and-sell: use **GTD with 60s expiration**. This auto-cleans
unfilled orders without us needing to track and cancel.

### 2.4 WebSocket subscriptions

```javascript
// MARKET channel — orderbook events
const ws = new WebSocket("wss://ws-subscriptions-clob.polymarket.com/ws/market");
ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "market",
    assets_ids: [TOKEN_ID_UP, TOKEN_ID_DOWN],   // subscribe to both sides
    custom_feature_enabled: true,                // enables best_bid_ask events
  }));
};
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  // msg.event_type ∈ { "book", "price_change", "tick_size_change",
  //                    "best_bid_ask", "new_market", "market_resolved", ... }
  // msg.asset_id, msg.bids, msg.asks, msg.timestamp_us
};

// USER channel — fill notifications (separate connection)
const wsUser = new WebSocket("wss://ws-subscriptions-clob.polymarket.com/ws/user");
wsUser.send(JSON.stringify({
  type: "user",
  markets: [CONDITION_ID],
  auth: { apiKey, secret, passphrase },
}));
```

### 2.5 Fee structure (verified)

```
fee_paid_per_share = COLLATERAL × feeRate × price × (1 − price)

where:
  feeRate  — per-market, in basis points
              700 bps (7%) for BTC/ETH/SOL up-down crypto markets
              0 for geopolitical/world events (fee-free)
  price    — fill price ∈ [0, 1]
  COLLATERAL — USDC = 1 (so fee is in USDC per share)

Maker rebate (LIMIT fills only):
  rebate_per_share = REBATE_SHARE × fee_per_share
                   = 0.20 × fee_per_share        (crypto markets)
                   = 0.25 × fee_per_share        (other fee-enabled)

Net for maker:  rebate is INCOME (+$0.0035 per share at p=0.5)
Net for taker:  pays full fee (−$0.0175 per share at p=0.5)
```

Per-market query: `getClobMarketInfo(condition_id)` returns `feesEnabled`
and `feeRate`. Always pull this at slug subscribe time and validate.

### 2.6 Rate limits

Polymarket docs don't expose exact rate limits. Empirically based on
public bot reports: ~100 ops/second per API key is a safe operating
ceiling. Stay well under this with intelligent batching (one cancel-and-
repost per market per book event, not per micro-tick).

---

## 3. Infrastructure layout

### 3.1 Server location

| Region | RTT to CLOB | Verdict |
|---|---|---|
| London (eu-west-2) | <1ms | Geo-blocked for trading |
| **Dublin (eu-west-1)** | **<2ms** | **OPTIMAL — your existing setup** |
| Amsterdam | ~10ms | Good fallback |
| Frankfurt | ~15ms | Acceptable |
| US East | ~130ms | Uncompetitive |

Your Ireland server is essentially co-located. Don't migrate.

### 3.2 Network setup

```
[ Ireland VPS ]
   │
   ├── WS conn 1 → wss://ws-subscriptions-clob.polymarket.com/ws/market
   │   (BTC up-down 15m current slug's Up + Down tokens)
   │
   ├── WS conn 2 → wss://ws-subscriptions-clob.polymarket.com/ws/user
   │   (your wallet's fill notifications)
   │
   ├── WS conn 3 → wss://ws-live-data.polymarket.com
   │   (RTDS price feed — optional, for sanity checks)
   │
   ├── HTTPS conn → https://clob.polymarket.com
   │   (order POST/DELETE, market metadata)
   │
   ├── HTTPS conn → https://data-api.polymarket.com
   │   (positions, account state)
   │
   └── HTTPS conn → polygon-mainnet.g.alchemy.com
       (on-chain mint/merge/redeem TXs)
```

### 3.3 Wallet setup

Use a **deposit wallet** (signature type `POLY_1271`):
1. Generate fresh private key for the bot (don't reuse personal wallet)
2. Fund it with USDC.e (PoS USDC) on Polygon
3. Approve CTF + Exchange contracts to spend USDC (one-time)
4. Approve CTF to manage your ERC-1155 conditional tokens (one-time)
5. Derive L2 API credentials once via L1 signature
6. Store credentials encrypted on disk

Initial bot capital for v1: **$100-200 USDC**. Plenty for $25 per-slug
notional × 4 active slugs over 24h.

---

## 4. Software architecture

### 4.1 Language: Python (confirmed)

Why Python is correct for v1:
- Network roundtrip (50-200ms) dominates everything; CPU latency is noise
- Wallets making $344k/day are almost certainly Python/TypeScript
- Polymarket has an official Python SDK (`py-clob-client`)
- 2-3 weeks of dev saved vs Rust
- Easy to add structured logging, async error handling, fast iteration

If Phase 5+ shows GIL contention on 50+ markets, then carve out the
book-ingestion + decision hot path into Rust. Not before.

### 4.2 Project layout

```
poly_mint_sell_bot/
├── pyproject.toml
├── README.md
├── .env.example                  ← template (private key, API creds, RPC URL)
├── config/
│   └── markets.yaml              ← which slugs to trade, sizing, gates
│
├── bot/
│   ├── __init__.py
│   ├── main.py                   ← entry point: orchestrates all components
│   ├── scheduler.py              ← SlotScheduler: detects new slugs cron-style
│   ├── book.py                   ← BookSubscriber: WS market feed
│   ├── user_events.py            ← UserEventSubscriber: WS user feed (fills)
│   ├── orders.py                 ← OrderManager: post/cancel/diff logic
│   ├── inventory.py              ← InventoryManager: tracks USDC + tokens
│   ├── onchain.py                ← OnChainExecutor: web3 TXs for mint/merge/redeem
│   ├── clob.py                   ← CLOBClient: thin wrapper over py-clob-client
│   ├── pricing.py                ← Pricing logic, gate evaluation
│   ├── pnl.py                    ← Per-slug + cumulative PnL accounting
│   ├── logger.py                 ← Structured logging + parquet persistence
│   ├── monitor.py                ← HealthMonitor: stop-loss, error guard
│   └── paper.py                  ← Paper-trade mode: same logic, mocked I/O
│
├── tests/
│   ├── test_pricing.py
│   ├── test_inventory.py
│   ├── test_orders_diff.py
│   ├── test_pnl.py
│   └── test_paper_end_to_end.py
│
├── scripts/
│   ├── derive_api_creds.py       ← one-time L1 → L2 derivation
│   ├── approve_contracts.py      ← one-time contract approvals
│   └── replay_canonical.py       ← paper-trade against canonical L25 data
│
└── data/
    ├── logs/                     ← rotating logs (10-day retention)
    └── slugs/                    ← per-slug parquet: book snapshots + actions
```

### 4.3 Component contracts

#### SlotScheduler (`bot/scheduler.py`)

```python
class SlotScheduler:
    """Detects when new 15m up-down markets open. Emits slot_start events."""

    def __init__(self, asset: str, timeframe_min: int = 15):
        self.asset = asset                  # "BTC" / "ETH" / "SOL"
        self.timeframe_s = timeframe_min * 60

    async def next_slot_start(self) -> datetime:
        """Return next slot_start UTC datetime (rounded up to next aligned interval)."""
        now = datetime.now(tz=UTC)
        seconds_into_period = (now.timestamp() % self.timeframe_s)
        return now + timedelta(seconds=self.timeframe_s - seconds_into_period)

    async def get_slug_for_slot(self, slot_start: datetime) -> tuple[str, str, str]:
        """Look up condition_id, token_id_up, token_id_down for the next slug.

        Two paths:
        - Gamma API: /events?slug=<...>&closed=false (returns nearest slug)
        - Computed slug pattern: f"{asset.lower()}-updown-15m-{int(slot_start.timestamp())}"

        Returns (slug, condition_id, token_id_up, token_id_down)
        """

    async def run(self):
        """Yield (slot_start, slug, condition_id, token_ids) events."""
        while True:
            t_next = await self.next_slot_start()
            await asyncio.sleep((t_next - datetime.now(UTC)).total_seconds() - 30)
            # T-30s: look up the new slug
            slug_info = await self.get_slug_for_slot(t_next)
            yield SlotStartEvent(t_next, *slug_info)
            # Wait for next cycle
            await asyncio.sleep(self.timeframe_s - 30)
```

#### BookSubscriber (`bot/book.py`)

```python
@dataclass
class BookSnapshot:
    asset_id: str               # token_id (Up or Down)
    best_bid: float | None
    best_ask: float | None
    best_bid_size: float
    best_ask_size: float
    timestamp_us: int
    sequence: int               # CLOB sequence number for ordering


class BookSubscriber:
    """Maintains live top-of-book for one slug's Up + Down tokens."""

    def __init__(self, condition_id: str, token_id_up: str, token_id_down: str):
        self.token_id_up = token_id_up
        self.token_id_down = token_id_down
        self.book_up: BookSnapshot | None = None
        self.book_dn: BookSnapshot | None = None
        self.ws = None
        self.on_update_callbacks: list[Callable] = []

    async def connect(self):
        self.ws = await websockets.connect(
            "wss://ws-subscriptions-clob.polymarket.com/ws/market",
            ping_interval=20, ping_timeout=10,
        )
        await self.ws.send(json.dumps({
            "type": "market",
            "assets_ids": [self.token_id_up, self.token_id_down],
            "custom_feature_enabled": True,
        }))

    async def run(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            updated_book = self._parse_book_update(msg)
            if updated_book:
                if updated_book.asset_id == self.token_id_up:
                    self.book_up = updated_book
                else:
                    self.book_dn = updated_book
                if self.book_up and self.book_dn:
                    for cb in self.on_update_callbacks:
                        await cb(self.book_up, self.book_dn)

    def snapshot(self) -> tuple[BookSnapshot, BookSnapshot] | None:
        if not (self.book_up and self.book_dn):
            return None
        # Reject if either side is older than 2s (stale book guard)
        now_us = int(time.time() * 1e6)
        if (now_us - self.book_up.timestamp_us > 2_000_000 or
            now_us - self.book_dn.timestamp_us > 2_000_000):
            return None
        return (self.book_up, self.book_dn)
```

#### InventoryManager (`bot/inventory.py`)

```python
@dataclass
class SlugInventory:
    """Per-slug inventory state."""
    slug: str
    condition_id: str
    token_id_up: str
    token_id_down: str
    pre_mint_amount: float            # how much we minted at slot_start

    # Token balances
    held_up: float = 0.0              # Up tokens currently in wallet
    held_dn: float = 0.0              # Down tokens currently in wallet

    # Cash flow accumulated
    usdc_in: float = 0.0              # from sells + rebates
    usdc_out: float = 0.0             # mint cost
    rebate_collected: float = 0.0     # tracked separately for analytics

    # Settlement
    settled: bool = False
    winner: str | None = None         # "Up" or "Down" once settled
    final_pnl: float | None = None

    # Active orders (CLOB order IDs)
    active_orders: dict[str, "ActiveOrder"] = field(default_factory=dict)

    def pair_inventory(self) -> float:
        """How many complete (Up, Down) pairs we still hold — mergeable."""
        return min(self.held_up, self.held_dn)

    def single_inventory(self) -> tuple[str, float]:
        """Side + count of single-sided inventory (from partial fills)."""
        if self.held_up > self.held_dn:
            return "Up", self.held_up - self.held_dn
        elif self.held_dn > self.held_up:
            return "Down", self.held_dn - self.held_up
        return "None", 0.0

    def on_mint(self, amount: float):
        self.held_up += amount
        self.held_dn += amount
        self.usdc_out += amount

    def on_fill(self, side: str, size: float, price: float, rebate: float):
        if side == "Up":
            self.held_up -= size
        else:
            self.held_dn -= size
        self.usdc_in += size * price + rebate
        self.rebate_collected += rebate

    def on_merge(self, pair_count: float):
        self.held_up -= pair_count
        self.held_dn -= pair_count
        self.usdc_in += pair_count

    def on_redeem(self, side: str, amount: float, won: bool):
        if side == "Up":
            self.held_up -= amount
        else:
            self.held_dn -= amount
        if won:
            self.usdc_in += amount      # redeem at $1/token

    def compute_pnl(self) -> float:
        """Realized PnL = USDC in − USDC out."""
        return self.usdc_in - self.usdc_out
```

#### OrderManager (`bot/orders.py`)

```python
@dataclass
class DesiredOrder:
    token_id: str
    side: str                     # "SELL" always for mint-and-sell
    price: float
    size: float

@dataclass
class ActiveOrder:
    order_id: str                 # CLOB-assigned ID
    token_id: str
    side: str
    price: float
    size: float
    size_remaining: float
    posted_at_us: int
    expires_at_us: int

class OrderManager:
    """Decides what orders SHOULD be active, then diffs vs current state and reconciles."""

    def __init__(self, clob: CLOBClient, inv: SlugInventory, cfg: BotConfig):
        self.clob = clob
        self.inv = inv
        self.cfg = cfg

    def compute_desired(self, book_up: BookSnapshot, book_dn: BookSnapshot) -> list[DesiredOrder]:
        """Apply gate logic. Return list of desired orders (0, 1, or 2)."""
        if book_up.best_ask is None or book_dn.best_ask is None:
            return []
        sum_asks = book_up.best_ask + book_dn.best_ask
        if sum_asks < self.cfg.min_sum_asks:
            return []
        if book_up.best_ask_size < self.cfg.min_visible_depth:
            return []
        if book_dn.best_ask_size < self.cfg.min_visible_depth:
            return []
        # Spread sanity (avoid posting in pathological books)
        if book_up.best_bid is not None:
            if (book_up.best_ask - book_up.best_bid) > self.cfg.max_spread_per_leg:
                return []
        if book_dn.best_bid is not None:
            if (book_dn.best_ask - book_dn.best_bid) > self.cfg.max_spread_per_leg:
                return []
        # Inventory check: do we have enough Up + Down tokens to post both legs?
        if self.inv.held_up < self.cfg.fire_size:
            return []
        if self.inv.held_dn < self.cfg.fire_size:
            return []
        return [
            DesiredOrder(self.inv.token_id_up, "SELL", book_up.best_ask, self.cfg.fire_size),
            DesiredOrder(self.inv.token_id_down, "SELL", book_dn.best_ask, self.cfg.fire_size),
        ]

    async def reconcile(self, desired: list[DesiredOrder]):
        """Compare desired vs active. Cancel mismatches. Post new where needed."""
        # Map desired by token_id
        desired_by_token = {d.token_id: d for d in desired}
        # Cancel stale orders (price moved, or no longer desired)
        for order_id, ao in list(self.inv.active_orders.items()):
            d = desired_by_token.get(ao.token_id)
            if d is None or d.price != ao.price:
                await self.clob.cancel_order(order_id)
                del self.inv.active_orders[order_id]
        # Post new orders that don't exist yet
        active_by_token = {ao.token_id: ao for ao in self.inv.active_orders.values()}
        for d in desired:
            if d.token_id in active_by_token:
                continue
            ao = await self.clob.post_order(d, expiration_s=60)
            if ao:
                self.inv.active_orders[ao.order_id] = ao
```

#### OnChainExecutor (`bot/onchain.py`)

```python
class OnChainExecutor:
    """Handles splitPosition, mergePositions, redeemPositions on Polygon."""

    def __init__(self, web3: Web3, account: LocalAccount, ctf_address: str):
        self.web3 = web3
        self.account = account
        self.ctf = web3.eth.contract(address=ctf_address, abi=CTF_ABI)

    async def split_position(self, condition_id: str, usdc_amount: int) -> str:
        """Mint usdc_amount/1e6 of Up+Down pair tokens. Returns tx_hash."""
        tx = self.ctf.functions.splitPosition(
            COLLATERAL_USDC_ADDRESS,
            ZERO_BYTES32,                  # parentCollectionId
            condition_id,
            [1, 2],                        # partition: Up + Down
            usdc_amount,
        ).build_transaction({
            "from": self.account.address,
            "nonce": self.web3.eth.get_transaction_count(self.account.address),
            "gas": 350_000,
            "maxFeePerGas": self.web3.to_wei(50, "gwei"),
            "maxPriorityFeePerGas": self.web3.to_wei(30, "gwei"),
        })
        signed = self.account.sign_transaction(tx)
        tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
        # Wait for 1 confirmation
        receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=10)
        return receipt.transactionHash.hex()

    async def merge_positions(self, condition_id: str, pair_amount: int) -> str:
        """Burn pair_amount of (Up, Down) pairs. Recover pair_amount USDC."""
        tx = self.ctf.functions.mergePositions(
            COLLATERAL_USDC_ADDRESS,
            ZERO_BYTES32,
            condition_id,
            [1, 2],
            pair_amount,
        ).build_transaction({...})
        # ... same pattern
        return tx_hash

    async def redeem_positions(self, condition_id: str, winning_index: int) -> str:
        """Redeem winning tokens for USDC. winning_index = 1 (Up) or 2 (Down)."""
        tx = self.ctf.functions.redeemPositions(
            COLLATERAL_USDC_ADDRESS,
            ZERO_BYTES32,
            condition_id,
            [winning_index],
        ).build_transaction({...})
        # ... same pattern
        return tx_hash
```

#### CLOBClient (`bot/clob.py`)

Thin wrapper over `py-clob-client`. Don't reinvent the EIP-712 + HMAC
plumbing.

```python
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType

class CLOBClient:
    def __init__(self, private_key: str, api_creds: ApiCreds):
        self.client = ClobClient(
            host="https://clob.polymarket.com",
            key=private_key,
            chain_id=137,
            signature_type=3,                  # POLY_1271 (deposit wallet)
            creds=api_creds,
        )

    async def post_order(self, d: DesiredOrder, expiration_s: int = 60) -> ActiveOrder:
        args = OrderArgs(
            token_id=d.token_id,
            price=d.price,
            size=d.size,
            side=d.side,
            expiration=int(time.time()) + expiration_s,   # for GTD
        )
        signed = self.client.create_order(args)
        resp = await asyncio.to_thread(self.client.post_order, signed, OrderType.GTD)
        if resp.get("success"):
            return ActiveOrder(
                order_id=resp["orderID"],
                token_id=d.token_id,
                side=d.side,
                price=d.price,
                size=d.size,
                size_remaining=d.size,
                posted_at_us=int(time.time() * 1e6),
                expires_at_us=int(time.time() * 1e6) + expiration_s * 1_000_000,
            )
        else:
            log.warning(f"post_order failed: {resp}")
            return None

    async def cancel_order(self, order_id: str) -> bool:
        resp = await asyncio.to_thread(self.client.cancel, order_id)
        return resp.get("success", False)
```

#### Pricing / config (`bot/pricing.py`, `config/markets.yaml`)

```yaml
# config/markets.yaml — single-market v1 config

bot:
  signature_type: 3                       # POLY_1271 (deposit wallet)

markets:
  - asset: BTC
    timeframe_min: 15
    enabled: true
    # Strategy gates
    min_sum_asks: 1.005                   # min arbitrage gap to fire
    fire_size: 2.5                        # shares per fire (= USDC since mint $1/pair)
    min_visible_depth: 2.5                # require at least our size at best
    max_spread_per_leg: 0.10              # skip pathological books
    # Pre-mint
    pre_mint_amount: 25.0                 # USDC to pre-mint at each slot_start
    # Risk
    max_slug_loss: 5.0                    # halt slug if loss exceeds $5
    max_inventory_single_side: 12.5       # halt if held imbalance > 5x fire_size
```

### 4.4 Main loop (`bot/main.py`)

```python
async def run_slug_cycle(scheduler_event: SlotStartEvent, cfg: MarketConfig,
                          clob: CLOBClient, executor: OnChainExecutor):
    """One full lifecycle of one slug: subscribe → mint → trade → settle → cleanup."""

    slug, condition_id, tid_up, tid_dn = scheduler_event.unpack()
    log.info(f"[{slug}] cycle start. Pre-minting ${cfg.pre_mint_amount}...")

    # === Subscribe to book ===
    book = BookSubscriber(condition_id, tid_up, tid_dn)
    await book.connect()
    book_task = asyncio.create_task(book.run())

    # === Pre-mint ===
    inv = SlugInventory(slug, condition_id, tid_up, tid_dn, cfg.pre_mint_amount)
    mint_tx = await executor.split_position(condition_id, int(cfg.pre_mint_amount * 1e6))
    inv.on_mint(cfg.pre_mint_amount)
    log.info(f"[{slug}] mint tx={mint_tx}")

    # === Order management loop ===
    order_mgr = OrderManager(clob, inv, cfg)
    async def on_book_update(b_up, b_dn):
        desired = order_mgr.compute_desired(b_up, b_dn)
        await order_mgr.reconcile(desired)
    book.on_update_callbacks.append(on_book_update)

    # === Wait until slot_end ===
    slot_end = scheduler_event.slot_start + timedelta(seconds=cfg.timeframe_min * 60)
    sleep_s = (slot_end - datetime.now(UTC)).total_seconds()
    await asyncio.sleep(sleep_s)

    # === Cleanup: cancel all, merge pairs, redeem winners ===
    book_task.cancel()
    for oid in list(inv.active_orders.keys()):
        await clob.cancel_order(oid)

    pair_amt = inv.pair_inventory()
    if pair_amt > 0:
        merge_tx = await executor.merge_positions(condition_id, int(pair_amt * 1e6))
        inv.on_merge(pair_amt)
        log.info(f"[{slug}] merge tx={merge_tx}  recovered ${pair_amt}")

    # Determine winner from market metadata
    winner_side = await clob.get_market_winner(condition_id)
    inv.settled = True
    inv.winner = winner_side

    single_side, single_amt = inv.single_inventory()
    if single_amt > 0:
        winning_index = 1 if winner_side == "Up" else 2
        if single_side == winner_side:
            redeem_tx = await executor.redeem_positions(condition_id, winning_index)
            inv.on_redeem(single_side, single_amt, won=True)
            log.info(f"[{slug}] redeem tx={redeem_tx}  recovered ${single_amt}")
        else:
            inv.on_redeem(single_side, single_amt, won=False)  # tokens are zero

    pnl = inv.compute_pnl()
    log.info(f"[{slug}] FINAL PNL = ${pnl:.4f}")
    persist_slug_state(inv)
```

---

## 5. Paper-trade simulator (validate before live)

### 5.1 What it does

Same code path as live, but with **mocked I/O**:
- `OnChainExecutor.split_position` → fake tx_hash, log only
- `OnChainExecutor.merge_positions` / `redeem_positions` → log only
- `CLOBClient.post_order` → return fake order_id, register in `paper.posted`
- `CLOBClient.cancel_order` → mark in `paper.cancelled`
- `BookSubscriber.run()` → replay canonical L25 data from disk instead of live WS
- `clob.get_market_winner` → look up from `load_resolutions().outcome`

### 5.2 Fill simulation logic

```python
class PaperFillSimulator:
    """Decides whether each posted order would have filled, using canonical L25 data."""

    def simulate_fill(self, order: ActiveOrder, book_history: pd.DataFrame) -> tuple[bool, int]:
        """Returns (filled, fill_time_us).

        Logic: order fills iff best_bid_opp reaches our ask within order's lifetime
               AND we estimate enough taker volume to consume the queue ahead of us.

        Simplification for v1: assume 100% fill if best_bid >= our ask at any
        point during the order's life. Track queue depth at post time as a
        "fill probability discount" factor.
        """
        # ...
```

### 5.3 Run modes

```bash
# Mode 1: replay canonical data for ONE historical slug
python bot/paper.py --slug btc-updown-15m-1778509800 --notional 25 --fire-size 2.5

# Mode 2: replay all slugs in a date range
python bot/paper.py --asset BTC --timeframe 15m --start 2026-04-24 --end 2026-05-15

# Mode 3: live data, paper orders (best validation before flipping to live)
python bot/paper.py --asset BTC --timeframe 15m --mode live-data-paper-orders
```

### 5.4 Outputs

Per slug:
```
data/paper/<slug>/
├── inventory.json          ← final SlugInventory state (held_up, held_dn, winner)
├── orders_log.parquet      ← every desired/posted/cancelled/filled order
├── book_snapshots.parquet  ← (in replay mode) book state at each decision point
├── ledger.json             ← PaperLedger event log (see §8.7)
└── pnl_breakdown.json      ← output of PaperLedger.breakdown() — exact, replayable
```

Aggregate dashboard:
```
data/paper/_summary.csv
  slug, notional, n_fires, n_both, n_up_only, n_dn_only, n_neither,
  mint_cost, gross_sells, total_rebate, merge_recovery, redeem_recovery,
  winner, single_side, single_amt, slug_pnl
```

**Mid-slug running PnL** (for live dashboard): use `mid_slug_pnl_estimate()`
from §8.6. Show three lines on the chart: `realized_pnl`, `total_estimate
(conservative)`, `total_estimate (expected)`. The spread between them is
the inventory exposure at that moment.

### 5.5 What "validation passed" means

Before flipping to live, paper trade must show:

| Metric | Threshold |
|---|---|
| Mean slug PnL | ≥ $0 over ≥ 50 slugs |
| % slugs profitable | ≥ 55% |
| BOTH-fill rate | ≥ 40% |
| Inventory cleared at slot_end | 100% (no orphan tokens) |
| Order post latency (sim) | <500ms p95 |
| Zero crashes | over 50 consecutive slugs |

---

## 6. Phased live rollout

| Phase | Duration | Markets | Notional/slug | Capital at risk | Success criteria |
|---|---|---|---|---|---|
| 0 — Paper (replay) | 2-3 days | BTC 15m, 50+ historical slugs | sim $25 | $0 | All §5.5 metrics pass |
| 1 — Paper (live data) | 1-2 days | BTC 15m, current slugs | sim $25 | $0 | Sim PnL trends ≥ 0 over 50+ live slugs |
| 2 — Live, micro | 2-3 days | BTC 15m | $25 | <$200 | ≥ 50% profitable slugs, no infra failures |
| 3 — Live, scale notional | 3-5 days | BTC 15m | $25 → $100 | <$500 | PnL scales ~linearly |
| 4 — Add ETH 15m | 3-5 days | BTC + ETH 15m | $100 each | <$1000 | No resource contention, both profitable |
| 5 — Add SOL 15m + all 5m | 1 week | All 6 cells | $100 each | <$5000 | Aggregate $/day matches projection |
| 6 — Scale notional broadly | gradual | All | $100 → $500+ | scales | Edge per slug stable as size grows |

**Halt conditions** at every phase:
- Running PnL < −20% of capital at risk
- > 5 consecutive losing slugs
- API error rate > 1%
- Any on-chain TX failure (mint/merge/redeem)
- Detected stale book data > 5s gap

---

## 7. Risk management (hard rules)

### 7.1 Per-slug

```python
HALT_SLUG_LOSS_USD = 5.0           # cancel all + merge if running loss exceeds
HALT_SINGLE_INV    = 12.5          # cancel all if |held_up - held_dn| > 5x fire_size
HALT_STALE_BOOK_S  = 5             # no fires if last WS update >5s old
```

### 7.2 Per-day

```python
HALT_DAILY_PNL_PCT = -0.10         # halt all trading if daily PnL < -10% of capital
HALT_API_ERROR_PCT = 0.01          # halt if API errors > 1% over rolling 1min
MAX_CONCURRENT_SLUGS = 4           # cap to control resource use during v1
```

### 7.3 Capital

```python
MIN_USDC_BUFFER = 50.0             # keep $50 unallocated for gas + safety
MAX_PRE_MINT_AT_RISK_PCT = 0.50    # never have >50% of capital in active pre-mints
```

### 7.4 Recovery on crash

On bot restart, recover state from log:
1. Read last `inventory.json` per active slug
2. Query CLOB for currently-active orders → reconcile with inv
3. Query data-api for token balances → reconcile with inv
4. If discrepancy: log alert, halt that slug, manual review

---

## 8. PnL accounting (precise formulas for paper + live)

### 8.1 Per fire (= one mint-and-sell cycle attempt)

```
Pre-condition: pre-minted N pair-tokens at cost $N (handled at slot_start)

Fire at time t:
  Post SELL N Up @ ask_up
  Post SELL N Dn @ ask_dn
  Wait 60s, observe fills

Cash impact at time t+60s (FROM this fire only — pre-mint cost separate):
  Up filled?    Δ_cash_up = +N × ask_up + N × rebate(ask_up)
  Dn filled?    Δ_cash_dn = +N × ask_dn + N × rebate(ask_dn)
  Up not filled? — Up tokens stay in inventory (no cash change)
  Dn not filled? — Dn tokens stay in inventory (no cash change)
```

### 8.2 Per slug (= 15min lifecycle)

```
At slot_start:
  cash_balance -= pre_mint_amount        ← mint cost
  held_up += pre_mint_amount             ← tokens received
  held_dn += pre_mint_amount

During slug (sum of all fires):
  cash_balance += Σ (filled fills × prices + rebates)
  held_up -= Σ (Up legs filled)
  held_dn -= Σ (Dn legs filled)

At slot_end:
  pair_amt = min(held_up, held_dn)       ← pairs we can merge back
  cash_balance += pair_amt
  held_up -= pair_amt
  held_dn -= pair_amt

After settlement:
  Determine winner.
  single_side, single_amt = inventory.single_inventory()
  if single_side == winner:
    cash_balance += single_amt            ← redeem winning tokens
  # losing tokens: cash impact = 0 (already factored as held)
  held_up = 0; held_dn = 0

slug_pnl = cash_balance − cash_balance_at_slug_start
```

### 8.3 Per day / cumulative

```
daily_pnl = Σ slug_pnl for slugs settled during the day
running_pnl = Σ all slug_pnl since bot start
```

### 8.4 Decomposition for analytics

For every fire, log:
```
fire_id, slug, t_us, ask_up, ask_dn, sum_asks,
posted_up: bool, posted_dn: bool,
filled_up: bool, filled_dn: bool,
fill_price_up, fill_price_dn,
rebate_up, rebate_dn,
pre_fire_held_up, pre_fire_held_dn,
post_fire_held_up, post_fire_held_dn,
expected_fill_pnl, realized_fill_pnl
```

For every slug, log:
```
slug, slot_start, slot_end, pre_mint_amount, n_fires,
n_both_fill, n_up_only, n_dn_only, n_neither,
gross_sells_usd, total_rebate_usd, mint_cost, merge_recovery,
winner, redeem_recovery, final_held_up, final_held_dn,
slug_pnl, slug_pnl_breakdown
```

This is what lets you answer "is the strategy actually working?" with
hard numbers, not vibes.

---

### 8.5 Worked numeric example — full slug ledger

Two scenarios, identical mid-slug activity, different settlement.

**Setup**: BTC 15m slug. Pre-mint $10 (10 pair-tokens, i.e. 10 Up + 10 Down).
Fee = $0 (maker), rebate = `0.20 × 0.07 × p × (1−p)` per share.

**Mid-slug fires (same in both scenarios)**:

| t (s into slug) | side | size | fill_price | rebate/share | cash_in |
|---:|---|---:|---:|---:|---:|
| 12 | Up | 4 | $0.520 | $0.003494 | $2.0940 (= 4×0.520 + 4×0.003494) |
| 48 | Dn | 5 | $0.495 | $0.003500 | $2.4925 |
| 121 | Up | 3 | $0.508 | $0.003500 | $1.5345 |
| 247 | Dn | 4 | $0.492 | $0.003495 | $1.9820 |
| 433 | Up | 2 | $0.511 | $0.003498 | $1.0290 |

**Running ledger after each event**:

```
t=0  (mint):       cash=-$10.00  held=(10,10)  pair=10  single=(–, 0)
t=12 (Up filled):  cash=-$7.906  held=(6,10)   pair=6   single=("Dn", 4)
t=48 (Dn filled):  cash=-$5.414  held=(6,5)    pair=5   single=("Up", 1)
t=121(Up filled):  cash=-$3.879  held=(3,5)    pair=3   single=("Dn", 2)
t=247(Dn filled):  cash=-$1.897  held=(3,1)    pair=1   single=("Up", 2)
t=433(Up filled):  cash=-$0.868  held=(1,1)    pair=1   single=("–", 0)
```

**At slot_end (t = 900s)**:

```
merge min(held_up, held_dn) = min(1,1) = 1 pair
cash += 1 × $1 = +$1.00
held = (0, 0)
cash_now = -$0.868 + $1.00 = +$0.132
```

→ No leftover inventory; slug is fully closed before settlement.
**slug_pnl (Scenario A, both sides perfectly merged) = +$0.132**

Now reset and run a different fire pattern where the bot is unable to merge
back to zero (because Up filled 9 but Dn only filled 5 across the slug):

```
t=0:   mint, cash=-$10, held=(10,10)
... (9 Up fills totaling +$4.61, 5 Dn fills totaling +$2.49 with rebates) ...
t=900: cash = -$10 + $4.61 + $2.49 = -$2.90, held = (1, 5)
       merge min(1,5) = 1: cash += $1, held=(0, 4)
       cash_after_merge = -$1.90, held single = ("Dn", 4)
```

**Scenario B-Down-wins**: chainlink settles Down. Redeem 4 Down @ $1.
```
cash = -$1.90 + 4 × $1 = +$2.10
slug_pnl = +$2.10
```

**Scenario B-Up-wins**: chainlink settles Up. Redeem 4 Down @ $0.
```
cash = -$1.90 + 0 = -$1.90
slug_pnl = -$1.90
```

The 4 Down tokens at slot_end are an unhedged directional bet. Expected
value at the resolution oracle's *unbiased* prior (50/50) is:

```
E[slug_pnl | unbiased] = 0.5 × $2.10 + 0.5 × −$1.90 = +$0.10
```

But the **held-side selection bias** (the side we held = the side that
didn't get bought aggressively → the side the market *thought* would
lose) gives `held_WR ≈ 0.20–0.30` empirically (`MINT_AND_SELL_PARTIAL_FILL_POLICY_2026_05_16.md`).
So realistic expected:

```
E[slug_pnl | empirical held_WR=0.25] = 0.25 × $2.10 + 0.75 × −$1.90
                                     = +$0.525 − $1.425 = −$0.90
```

This is why §1.4's HOLD-vs-MARKET_EXIT analysis says holding the unfilled
leg is a losing proposition *per partial*. The strategy only wins when
many fires per slug make **both** sides accumulate single-inventory (the
BOTH_SIDES_PARTIALS regime described in §1.4's final summary).

---

### 8.6 Mid-slug mark-to-market (running PnL for paper-trade UI)

During a slug, the wallet has cash + token inventory whose ultimate cash
value is unknown. For running display (Grafana, paper-trade tail), report:

```python
def mid_slug_pnl_estimate(inv: SlugInventory,
                           current_best_bid_up: float,
                           current_best_bid_dn: float,
                           mode: str = "expected") -> dict:
    """
    realized_pnl: cash actually moved (sells, rebates, mint cost). Always exact.

    inventory_value: a forward estimate of what we'll recover from token holdings.
      modes:
        - "conservative" : pair_value + 0    (assume single-side worthless)
        - "expected"     : pair_value + single × (best_bid for that side)
        - "midpoint"     : pair_value + single × 0.5  (50/50 prior)
        - "winner_known" : pair_value + single × (1 if won else 0)  [post-settlement]

    Total = realized + inventory_value.
    """
    pair_amt = inv.pair_inventory()                                 # mergeable
    side, single_amt = inv.single_inventory()                       # unmergeable

    pair_value = pair_amt * 1.00                                    # merge yields $1/pair

    if mode == "conservative":
        single_value = 0.0
    elif mode == "expected":
        bid = current_best_bid_up if side == "Up" else current_best_bid_dn
        single_value = single_amt * bid                             # market-exit price
    elif mode == "midpoint":
        single_value = single_amt * 0.5
    elif mode == "winner_known":
        won = (side == inv.winner)
        single_value = single_amt * (1.0 if won else 0.0)
    else:
        raise ValueError(mode)

    realized = inv.usdc_in - inv.usdc_out
    return {
        "realized_pnl": realized,
        "inventory_pair_value": pair_value,
        "inventory_single_value": single_value,
        "single_side": side,
        "single_amount": single_amt,
        "total_estimate": realized + pair_value + single_value,
        "mode": mode,
    }
```

**For paper-trade dashboard reporting**:
- `realized_pnl` = source-of-truth, no projection
- `total_estimate (mode="expected")` = best mid-flight guess
- `total_estimate (mode="conservative")` = worst-case floor
- `total_estimate (mode="winner_known")` = final, only available after chainlink settles

---

### 8.7 Paper-trade ledger reference implementation

Drop into `bot/paper_ledger.py`. The simulator must produce identical output
to the live PnL accountant — same events, same arithmetic, no extra magic.

```python
from dataclasses import dataclass, field
from typing import Literal

Side = Literal["Up", "Dn"]


@dataclass
class FireRecord:
    fire_id: int
    t_us: int
    ask_up: float
    ask_dn: float
    sum_asks: float
    sizes: dict[Side, float]              # what we posted per leg
    fills: dict[Side, tuple[bool, float, float]]  # filled, fill_px, rebate_per_share


@dataclass
class PaperLedger:
    """Append-only event ledger; produces slug-level PnL on demand."""
    slug: str
    pre_mint_amount: float

    # Event log
    fires: list[FireRecord] = field(default_factory=list)
    merge_amount: float | None = None     # set at slot_end
    redeem: tuple[Side, float] | None = None  # set after settlement

    # Settlement (oracle)
    winner: Side | None = None

    # ---- accounting ----
    @property
    def mint_cost(self) -> float:
        return self.pre_mint_amount

    @property
    def gross_sells(self) -> float:
        """Σ size × fill_price across all filled legs."""
        s = 0.0
        for f in self.fires:
            for side in ("Up", "Dn"):
                filled, px, _ = f.fills[side]
                if filled:
                    s += f.sizes[side] * px
        return s

    @property
    def total_rebate(self) -> float:
        s = 0.0
        for f in self.fires:
            for side in ("Up", "Dn"):
                filled, _, reb_per_share = f.fills[side]
                if filled:
                    s += f.sizes[side] * reb_per_share
        return s

    @property
    def merge_recovery(self) -> float:
        return self.merge_amount or 0.0

    @property
    def redeem_recovery(self) -> float:
        if self.redeem is None or self.winner is None:
            return 0.0
        side, amt = self.redeem
        return amt if side == self.winner else 0.0

    @property
    def slug_pnl(self) -> float:
        """Final slug PnL — only valid after settlement."""
        return (self.gross_sells + self.total_rebate
                + self.merge_recovery + self.redeem_recovery
                - self.mint_cost)

    def breakdown(self) -> dict:
        return {
            "mint_cost": -self.mint_cost,
            "gross_sells": self.gross_sells,
            "total_rebate": self.total_rebate,
            "merge_recovery": self.merge_recovery,
            "redeem_recovery": self.redeem_recovery,
            "slug_pnl": self.slug_pnl,
            "n_fires": len(self.fires),
            "n_both_fill":  sum(1 for f in self.fires
                                if f.fills["Up"][0] and f.fills["Dn"][0]),
            "n_up_only":    sum(1 for f in self.fires
                                if f.fills["Up"][0] and not f.fills["Dn"][0]),
            "n_dn_only":    sum(1 for f in self.fires
                                if not f.fills["Up"][0] and f.fills["Dn"][0]),
            "n_neither":    sum(1 for f in self.fires
                                if not f.fills["Up"][0] and not f.fills["Dn"][0]),
        }
```

**Identity** (must hold for every slug):

```
slug_pnl == gross_sells + total_rebate + merge_recovery + redeem_recovery − mint_cost
```

Paper-trade output `pnl_breakdown.json` (§5.4) is exactly `breakdown()`.

This is the only ledger. Live PnL is the same arithmetic; the difference is
that `gross_sells`/`total_rebate` come from real CLOB fill events instead
of `PaperFillSimulator`, and `merge_recovery`/`redeem_recovery` come from
on-chain TX receipts instead of simulator hand-back.

---

## 9. Edge cases + error handling

### 9.1 Mint TX fails or is slow

- If `wait_for_transaction_receipt` times out (>10s) → check tx status
  separately. If still pending → cancel and re-broadcast with higher gas.
  If reverted → log + halt this slug cycle (don't post sells without inventory).

### 9.2 Single-leg fill at very end of slug

If a leg fills at t = slot_start + 880s (20s before slot_end):
- We were holding N Dn at the end (e.g.)
- Mint→Sell capture: less critical → still on path
- Tokens settle normally — handled by post-slot-end cleanup

### 9.3 Order rejected by CLOB

Common reasons: insufficient balance, invalid signature, expired nonce,
price outside tick size.

- Log the rejection reason
- If signature/nonce issue: re-derive credentials, re-sign
- If price tick issue: round to nearest tick (Polymarket uses 0.01 ticks
  for most markets — verify per-market via `getClobMarketInfo`)
- If balance issue: re-query token balance, reconcile inventory

### 9.4 Market resolves early / abnormally

Polymarket markets can resolve early in extreme conditions. Subscribe to
the `market_resolved` event on the WS user channel. On receipt:
- Cancel all active orders for that condition_id
- Trigger cleanup phase immediately
- Don't wait for slot_end timer

### 9.5 WS disconnect

- Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s)
- On reconnect, re-subscribe to current slug's tokens
- If reconnect takes >30s during active trading: halt slug, cancel orders
  via REST as a fallback

### 9.6 Self-trade prevention

Don't post a SELL on Up while you also have a BUY on Up (you'd match
yourself). For mint-and-sell this isn't possible (we never BUY on the
CLOB — we mint instead). But sanity-check anyway via the user feed:
flag any fill where `maker_address == taker_address == your_wallet`.

### 9.7 Capital exhaustion mid-slug

If pre-mint succeeded but bot crashes mid-slug → wallet has leftover Up + Dn
tokens. On restart:
- Recovery script scans all known condition_ids for non-zero balances
- For each, call `mergePositions(min(up, dn))` to recover pair value
- For single-side residual: wait for chainlink resolution, then redeem if winner

---

## 10. Monitoring + observability

### 10.1 Real-time dashboards (Grafana / similar)

- **Strategy health**: BOTH-fill rate (rolling 1h), partial held_WR, slug-mean PnL
- **Execution**: book-update → order-posted latency p50/p95/p99, cancel latency
- **Inventory**: USDC balance, current held_up + held_dn across all active slugs
- **Errors**: API error rate, WS reconnect count, on-chain TX failure rate
- **PnL**: cumulative PnL chart, per-slug PnL histogram, daily total

### 10.2 Alerts (Telegram or similar)

- Slug halt triggered (loss > threshold)
- Daily PnL halt triggered (-10% of capital)
- API error rate > 1% sustained for 1min
- WS disconnect not recovered in 30s
- On-chain TX failed
- Capital buffer below $50

### 10.3 Daily summary log

Auto-generated at 00:00 UTC:
```
═════ DAILY SUMMARY 2026-05-17 ═════
Slugs traded:        96
Slugs profitable:    61 (63.5%)
Mean slug PnL:       $0.42
Total PnL:           $40.32
BOTH-fill rate:      48.7%
Median fires/slug:   118
Capital used:        $1450 / $2000 (72%)
API errors:          0.12%
On-chain TXs:        96 mints + 96 merges + 78 redeems = 270 (gas: $1.35)
Top winning slug:    btc-updown-15m-... ($3.40)
Top losing slug:     btc-updown-15m-... (-$2.10)
═══════════════════════════════════
```

---

## 11. What success looks like (define before deploy)

**Phase 2 (live, micro)** = success if over ≥50 slugs:
- ≥ 55% profitable
- Mean slug PnL ≥ $0.10 at $25 notional (per our slug-aggregation finding)
- Zero infrastructure failures
- All inventory cleared at slot_end (no orphan tokens)

**Phase 5 (full universe)** = success if over a week:
- Daily PnL ≥ $20 at $100/slug × 4-6 cells
- Sharpe ratio > 1.0
- Drawdown < 15% from peak

**Production scale-up** = success at $500-1000/slug if Phase 5 metrics
hold linearly with size.

---

## 12. Open questions for next session

1. **Effective fill rate uplift**: our backtest shows 35-55% BOTH-fill;
   wallets likely achieve 50-70%. Why? Tighter posting? Better queue
   timing? Need a paper-trade run with realistic queue simulation.

2. **Self-selection on fire timing**: do wallets skip the first 30s of
   each slug? The last 60s? Inspect `offset_from_slot_start_s` densities
   per wallet at fire-level granularity.

3. **Negative-Risk markets**: Polymarket has a separate Exchange contract
   (0xC5d...) for negative-risk markets (multi-outcome with combined
   resolution). Our up-down markets aren't in this — but worth confirming.

4. **Sell-and-Redeem variant**: per handoff, 0x89b5cdaa is 100% only-SELL.
   That's the "mint pair, sell expensive side, hold cheap side to redeem"
   pattern. Should v2 of the engine support this as a config flag?

5. **Maker rebate program eligibility**: Polymarket has a separate
   Maker Rebates Program with daily USDC payouts based on volume + spread
   tightness. Does this stack with the per-fill rebate? Check
   `docs.polymarket.com/market-makers/maker-rebates`.

---

## 13. References

- Strategy decode: `strategy_lab/reports/STRATEGY_DECODED_2026_05_16.md`
- Wallet PnL methodology: `strategy_lab/reports/WALLET_PNL_BREAKTHROUGH_2026_05_16.md`
- Previous live-deploy draft: `strategy_lab/reports/MINT_AND_SELL_LIVE_SPEC_2026_05_16.md`
- Partial-fill policy analysis: `strategy_lab/reports/MINT_AND_SELL_PARTIAL_FILL_POLICY_2026_05_16.md`
- v2 backtest replication: `strategy_lab/reports/MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md`
- Handoff: `strategy_lab/reports/HANDOFF_WALLET_DECODER_2026_05_16.md`
- Fee model: `strategy_lab/fees.py`
- v2 scanner: `strategy_lab/wallet_hunt/replicate/mint_and_sell_scan_v2.py`
- Policy compare: `strategy_lab/wallet_hunt/replicate/partial_fill_policy_compare_v2.py`

### Polymarket docs (verified 2026-05-17)
- CLOB overview: https://docs.polymarket.com/developers/CLOB/introduction
- Orderbook + WS: https://docs.polymarket.com/trading/orderbook
- Fees: https://docs.polymarket.com/trading/fees
- Python SDK: https://github.com/Polymarket/py-clob-client
- Rust SDK: https://github.com/Polymarket/rs-clob-client
- TypeScript SDK: https://github.com/Polymarket/clob-client-v2

### Server hosting (verified 2026-05-17)
- AWS eu-west-2 (London) — independently triangulated
- Dublin (eu-west-1) → London: <2ms RTT
- US East → London: ~130ms RTT (uncompetitive)
