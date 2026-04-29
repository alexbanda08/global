# Building a CYCLOPS-Style Prediction Market Trading Bot
### A Professional Quant's Complete Architecture & Implementation Guide

> **Target reader:** A developer who is comfortable with Python, async systems, and APIs, and who wants to build an institutional-grade bot that trades short-duration binary prediction markets (Polymarket 15-min BTC markets, Kalshi equivalents, etc.) using multi-signal confluence, regime awareness, probability calibration, and disciplined risk management.
>
> **What you will end up with:** A layered system — **Data → Brain → Filters → Execution → Learning** — that trades only when independent signals agree, edge exceeds a session-adjusted threshold, and the bot's own calibrated confidence supports the bet. This mirrors the architecture the CYCLOPS article describes, stripped down to the principles, with production details filled in.

---

## Part 1 — Mental Model: Why This Architecture Works

Before writing a single line, understand what this class of bot *is*.

A 15-minute BTC prediction market on Polymarket is a **fully-collateralized binary option**. Two tokens exist — YES and NO — and their prices must satisfy `P(YES) + P(NO) = $1.00`. A price of $0.60 on YES is the market's consensus probability that the event resolves true. Your job as the bot's designer is to produce a **better probability estimate than the market's**, then size the bet accordingly. Every architectural choice flows from that single sentence.

There are only three ways to beat a prediction market:

1. **Faster data** — you see the signal before the market reprices. (Polymarket's 15-min BTC market lags Binance price moves by roughly 30–90 seconds; this is the well-known latency edge.)
2. **Better synthesis** — you combine multiple independent signals (price, order flow, liquidations, cross-market, news) that no single human trader is processing in real time.
3. **Better calibration** — you size bets with Kelly using *your actual historical hit rate at each confidence level*, not your model's raw output.

CYCLOPS stacks all three. The architecture is three layers because each layer exists to **eliminate false positives from the previous layer**:

- **Layer 1 — Data:** gather everything, fast, from independent sources.
- **Layer 2 — Brain:** fuse signals into a directional forecast, regime-aware.
- **Layer 3 — Filters:** kill trades that pass the brain but fail risk, schedule, memory, or veto checks.

A disciplined principle the CYCLOPS author states explicitly: *better to miss an opportunity than to trade noise*. This is the dominant idea in every design decision below.

---

## Part 2 — System Architecture (Reference Topology)

```
                    ┌────────────────────────────────────────────┐
                    │              LAYER 1: DATA                  │
                    │                                             │
   Chainlink WS ────▶ price_feed  (candle engine, sub-sec BTC)    │
   Binance REST ────▶ liq_poller  (rolling 60s liquidation window)│
   Polymarket WS ───▶ book_stream (YES/NO price & depth)          │
   News APIs    ────▶ news_feed   (weighted bullish/bearish score)│
   Cross-mkt    ────▶ eth/sol/xrp 15m market prices (Polymarket)  │
                    └─────────────────┬──────────────────────────┘
                                      │
                    ┌─────────────────▼──────────────────────────┐
                    │         LAYER 2: UnifiedBrainEngine         │
                    │                                             │
                    │  ┌──────────────┐  ┌──────────────────┐     │
                    │  │ Indicators   │  │ RegimeDetector   │     │
                    │  │ (12+ votes)  │──▶ TREND / SIDEWAYS │     │
                    │  └──────┬───────┘  │ / VOLATILE / ... │     │
                    │         │          └─────────┬────────┘     │
                    │         ▼                    ▼              │
                    │  ┌────────────────────────────────────┐     │
                    │  │ Weighted Vote (regime-multiplied)  │     │
                    │  └─────────────────┬──────────────────┘     │
                    │                    │                         │
                    │  ┌─────────────────▼──────────────────┐     │
                    │  │ ContextualFusion                    │     │
                    │  │  • MarketContext (pressure/trend)  │     │
                    │  │  • Synergy bonuses (CVD+AGG, etc.) │     │
                    │  │  • MEGA bonus for 6+ agreement     │     │
                    │  └─────────────────┬──────────────────┘     │
                    │                    ▼                         │
                    │            raw_prob, direction               │
                    └────────────────────┬───────────────────────┘
                                         │
                    ┌────────────────────▼───────────────────────┐
                    │           LAYER 3: FILTERS                  │
                    │                                             │
                    │  Schedule      ─▶ session edge threshold    │
                    │  Calibrator    ─▶ Platt-style correction    │
                    │  SignalMemory  ─▶ Jaccard-similar past WR   │
                    │  VolumeVeto    ─▶ hard block: 4/4 against   │
                    │  StochRSIVeto  ─▶ extremes (conditional)    │
                    │  PeriodTracker ─▶ intra-period direction    │
                    │  DrawdownStop  ─▶ account-level safety      │
                    └────────────────────┬───────────────────────┘
                                         │
                    ┌────────────────────▼───────────────────────┐
                    │         EXECUTION + SETTLEMENT              │
                    │   SmartKelly sizing → CLOB order → wait     │
                    │   15m close → Chainlink price → WIN/LOSS    │
                    │   → update Calibrator + SignalMemory        │
                    └─────────────────────────────────────────────┘
```

The main loop ticks every 5 seconds. Settlement runs on a separate thread so the bot never blocks while the previous trade is waiting to close.

---

## Part 3 — Tech Stack & Project Structure

### Language and core libraries
- **Python 3.11+** — `asyncio` everywhere, `uvloop` on Linux for faster event loop.
- **`py-clob-client`** — Polymarket's official CLOB SDK. Handles EIP-712 signing.
- **`websockets`** / **`aiohttp`** — async data ingestion.
- **`pandas`, `numpy`, `numba`** — indicator math. `numba @jit` the hot inner loops.
- **`ta-lib`** or **`pandas-ta`** — battle-tested indicator implementations.
- **`scikit-learn`** — `CalibratedClassifierCV` for Platt/isotonic.
- **`SQLite` → `PostgreSQL/TimescaleDB`** — trade log, signal memory, calibration set. Start with SQLite; graduate to Timescale when you need tick storage. You already run Timescale on Quan — reuse it.
- **`ClickHouse`** for tick-level OHLCV if you want deep analytics later.
- **`python-telegram-bot`** for the control channel.

### Directory layout (opinionated)

```
cyclops/
├── config/
│   ├── settings.yaml          # thresholds, weights, schedule
│   └── secrets.env            # POLYMARKET_PRIVATE_KEY, API keys
├── data/
│   ├── price_feed.py          # Chainlink WS client
│   ├── liq_poller.py          # Binance liquidations
│   ├── book_stream.py         # Polymarket order book
│   ├── news_feed.py           # news classifier
│   └── candle_engine.py       # unified tick → OHLCV store
├── brain/
│   ├── indicators.py          # SuperTrend, EMA, MACD, StochRSI, CVD...
│   ├── regime.py              # RegimeDetector + hysteresis
│   ├── fusion.py              # ContextualFusion, synergies, MEGA bonus
│   └── unified_brain.py       # orchestrates the above
├── filters/
│   ├── schedule.py            # session table, edge thresholds
│   ├── calibrator.py          # Platt scaling on historical WR
│   ├── signal_memory.py       # Jaccard + time decay
│   ├── vetoes.py              # VolumeVeto, StochRSIVeto, PeriodTracker
│   └── risk.py                # drawdown, daily loss limit
├── exec/
│   ├── kelly.py               # fractional Kelly with modifiers
│   ├── polymarket.py          # py-clob-client wrapper
│   └── settlement.py          # 15m close + result logging
├── app/
│   ├── main_loop.py           # 5-second cycle
│   ├── watchdog.py            # liveness alerts
│   └── telegram_bot.py        # /status /pause /stop
├── db/
│   └── schema.sql
└── tests/
    ├── test_indicators.py
    ├── test_regime.py
    └── test_kelly.py
```

This structure enforces the **Layer 1 / 2 / 3 separation** in code, which makes each piece independently testable. Matches the "Dumb Frontend, Genius Backend" philosophy you already use — the execution layer never touches indicator math; the brain never constructs HTTP requests.

---

## Part 4 — Layer 1: The Data Subsystem

Your bot's eyes. If this layer is wrong, nothing downstream matters.

### 4.1 Price feed — Chainlink Data Streams

Chainlink Data Streams provides sub-second BTC/USD via WebSocket with HMAC authentication and cryptographic report signing. It's the same oracle used by DeFi derivatives protocols, which is why CYCLOPS uses it as the settlement reference — it's what Polymarket resolution uses too, implicitly, because the UMA Optimistic Oracle often references it.

**Why not just use Binance or Coinbase WebSocket?** Three reasons:
1. **Manipulation resistance** — single-exchange feeds are spoofable; Chainlink aggregates multiple.
2. **Sub-second cadence** — comparable to direct CEX feeds but without an exchange-level rate-limit single point of failure.
3. **Settlement parity** — your WIN/LOSS ground truth should come from the same price source the market resolves against, or as close as possible.

**Implementation sketch:**

```python
# data/price_feed.py
import asyncio, hmac, hashlib, time, json
from collections import deque

class ChainlinkPriceFeed:
    def __init__(self, client_id, client_secret, ws_url, feed_id):
        self.client_id = client_id
        self.client_secret = client_secret
        self.ws_url = ws_url
        self.feed_id = feed_id
        self.ticks = deque(maxlen=10_000)     # (ts, price)
        self.last_price = None

    def _auth_headers(self, path, method="GET", body=""):
        ts = str(int(time.time() * 1000))
        body_hash = hashlib.sha256(body.encode()).hexdigest()
        string_to_sign = f"{method} {path} {body_hash} {self.client_id} {ts}"
        sig = hmac.new(self.client_secret.encode(), string_to_sign.encode(),
                       hashlib.sha256).hexdigest()
        return {
            "Authorization": self.client_id,
            "X-Authorization-Timestamp": ts,
            "X-Authorization-Signature-SHA256": sig,
        }

    async def run(self, on_tick):
        import websockets
        path = f"/api/v1/ws?feedIDs={self.feed_id}"
        headers = self._auth_headers(path)
        async with websockets.connect(self.ws_url + path,
                                      extra_headers=headers) as ws:
            async for msg in ws:
                report = json.loads(msg)["report"]
                # decode benchmark price from fullReport (see Chainlink docs)
                price = self._decode_price(report)
                ts = time.time()
                self.ticks.append((ts, price))
                self.last_price = price
                await on_tick(ts, price)
```

Feed the tick stream into your **candle engine** — a rolling structure that aggregates ticks into 1-second, 5-second, 15-second, 1-minute candles. All indicators consume candles, not raw ticks. Use `numba @jit` on the candle update hot path.

**Critical rule (from your own preferences):** never introduce batching delays. Chainlink ticks arrive sub-second; your candle engine must process them synchronously in the WS callback. No `await asyncio.sleep(0.1)` tricks.

### 4.2 Liquidation feed — Binance Futures

One of the fastest real-pressure indicators in crypto. Mass long liquidations = forced selling = bearish in the next 1–5 minutes.

Binance's `fapi/v1/allForceOrders` endpoint is rate-limited; the public **`!forceOrder@arr`** WebSocket stream on `fstream.binance.com` is much better — no polling.

```python
# data/liq_poller.py (actually better as a streamer)
import asyncio, json, time
from collections import deque

class LiquidationStream:
    def __init__(self, symbols=("btcusdt",)):
        self.symbols = symbols
        self.window = deque()   # (ts, side, notional_usd, order_id)
        self._seen_ids = set()

    async def run(self):
        import websockets
        url = "wss://fstream.binance.com/ws/!forceOrder@arr"
        async with websockets.connect(url) as ws:
            async for msg in ws:
                data = json.loads(msg)
                o = data["o"]
                if o["s"].lower() not in self.symbols:
                    continue
                oid = (o["T"], o["s"], o["q"], o["p"])  # synthetic id
                if oid in self._seen_ids:
                    continue
                self._seen_ids.add(oid)
                notional = float(o["q"]) * float(o["p"])
                self.window.append((time.time(), o["S"], notional, oid))
                self._trim()

    def _trim(self, window_sec=60):
        cutoff = time.time() - window_sec
        while self.window and self.window[0][0] < cutoff:
            self.window.popleft()

    def signal(self, window_sec=60, min_total=10_000):
        self._trim(window_sec)
        long_liq  = sum(n for _,s,n,_ in self.window if s == "SELL")
        short_liq = sum(n for _,s,n,_ in self.window if s == "BUY")
        total = long_liq + short_liq
        if total < min_total:
            return None  # silence, not signal
        imbalance = (long_liq - short_liq) / total
        return {
            "dominant": "long_liq" if long_liq > short_liq else "short_liq",
            "imbalance": imbalance,          # -1..+1
            "bearish": long_liq > short_liq * 2,
            "bullish": short_liq > long_liq * 2,
            "total_usd": total,
        }
```

**Why a rolling 60-second window:** shorter than that, the signal is noise; longer and it becomes stale. The CYCLOPS author tuned this by hand reviewing logs — the right answer for *your* strategy may be 45s or 90s. Measure it.

### 4.3 Polymarket order book

The betting-market's own consensus. Update every 1–2 seconds via the CLOB WebSocket. This is as important as the BTC price — it tells you *where the edge is*.

Polymarket has two APIs you need:
- **Gamma API** (public, no auth): market discovery. `GET https://gamma-api.polymarket.com/markets?closed=false&category=Crypto`. Use this to find the active BTC 15-min markets.
- **CLOB API** (authenticated, EIP-712): order book, order placement. Use `py-clob-client`.

The **CLOB WebSocket** has a `market` channel that pushes order book diffs. Subscribe for each active `token_id` you're evaluating.

```python
# data/book_stream.py
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

client = ClobClient(
    host="https://clob.polymarket.com",
    key=os.environ["POLYMARKET_PRIVATE_KEY"],
    chain_id=137,
    funder=os.environ["POLYMARKET_FUNDER_ADDRESS"],
    signature_type=2,   # for proxy wallets; use 0 for EOA
)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

# subscribe via WS for token_id in the active 15m BTC market
```

### 4.4 News feed

The weakest signal of the four, but useful as a **tie-breaker** and as a **veto** around major macro releases (FOMC, CPI).

- Pull from CryptoPanic / CoinDesk / TheBlock RSS every 30–60s.
- Simple keyword classifier: `["ETF approved", "rally", "adoption"] → bullish`, `["hack", "liquidated", "ban"] → bearish`. Weight by recency: headline ≤15m old gets 3× weight vs a 60-min-old headline (as in CYCLOPS).
- Optional upgrade: FinBERT or a small LLM classifier. But don't start there — keyword works.

### 4.5 Cross-market sentiment

The CYCLOPS trick of pulling ETH/SOL/XRP 15-min markets and checking if they're all screaming DOWN simultaneously is high-signal. Correlated sells across majors = a risk-off move in crypto broadly. Add +0.05 to bearish confidence when 3/3 cross-markets agree.

---

## Part 5 — Layer 2: The Brain

### 5.1 Indicator zoo

Twelve indicators is about right. Each must be **independently informative** — pairing EMA with SMA is just noise. The CYCLOPS-style set:

| Indicator | Type | What it captures |
|---|---|---|
| SuperTrend (ATR-based) | Trend | Macro direction, trailing SR |
| EMA 9 / EMA 21 cross | Trend | Short-term momentum flip |
| MACD(12,26,9) histogram | Momentum | Acceleration/deceleration |
| StochRSI(14,14,3,3) | Oscillator | Overbought/oversold extremes |
| ATR(14) | Volatility | Position sizing + regime input |
| Bollinger Band %B | Volatility/MR | Ranging signal |
| CVD (1m) | Order flow | Net aggressor direction |
| VDELTA current bar | Order flow | Intra-bar pressure |
| Liquidation imbalance | Order flow | Forced participants |
| Aggressor flow (trade-tape) | Order flow | Market-order side bias |
| Book imbalance (top 5 levels) | Microstructure | Intent to buy/sell |
| Price acceleration (d²P/dt²) | Momentum | Fast move detection |

Each produces a vote ∈ {+1 (UP), 0 (neutral), -1 (DOWN)} plus a **strength** ∈ [0,1]. Use `pandas-ta` or `ta-lib` for the standard ones. The order-flow ones you'll build yourself from the tick stream.

### 5.2 Regime detection

Not all signals work in all markets. **EMA cross is great in trends and terrible in chop.** You have to know which regime you're in to weight signals properly.

A robust, fast approach without heavy ML:

1. Compute ADX(14). `ADX > 25 → trending`, `< 20 → ranging`.
2. Compute realized volatility over last 60 minutes (std of 1-min log returns). Above 75th percentile of the last 7 days → `volatile`.
3. Combine:

| ADX | Vol | Direction | Regime |
|---|---|---|---|
| >25 | low | up | TREND_UP |
| >25 | low | down | TREND_DOWN |
| >25 | high | either | VOLATILE_TREND |
| <20 | low | flat | SIDEWAYS |
| <20 | high | flat | VOLATILE_CHOPPY |
| else | - | - | UNKNOWN |

**Hysteresis is critical.** Don't switch regimes on a single tick crossing the threshold. Require the new classification to hold for **N consecutive evaluations** (say N=3, at 5s each = 15s of agreement) before updating. Otherwise the weights flip-flop and performance collapses.

```python
# brain/regime.py
class RegimeDetector:
    def __init__(self, stability_N=3):
        self.current = "UNKNOWN"
        self.candidate = None
        self.candidate_count = 0
        self.stability_N = stability_N

    def update(self, adx, vol_percentile, trend_sign):
        raw = self._classify(adx, vol_percentile, trend_sign)
        if raw == self.current:
            self.candidate = None
            return self.current
        if raw == self.candidate:
            self.candidate_count += 1
            if self.candidate_count >= self.stability_N:
                self.current = raw
                self.candidate = None
                self.candidate_count = 0
        else:
            self.candidate = raw
            self.candidate_count = 1
        return self.current
```

### 5.3 Weighted voting (regime-aware)

Each indicator has a base weight. The regime applies a **multiplier matrix**. The idea is simple: in trends, order-book and liquidation signals (leading) get amplified; in sideways, structural indicators (SuperTrend, EMA) dominate because oscillators whipsaw.

```python
REGIME_MULTIPLIERS = {
    "TREND_UP":        {"trend": 1.0, "mom": 1.0, "osc": 0.5,
                        "flow": 1.3, "vol": 1.0, "micro": 1.4},
    "TREND_DOWN":      {"trend": 1.0, "mom": 1.0, "osc": 0.5,
                        "flow": 1.3, "vol": 1.0, "micro": 1.4},
    "SIDEWAYS":        {"trend": 1.1, "mom": 0.8, "osc": 1.4,
                        "flow": 0.7, "vol": 1.0, "micro": 0.5},
    "VOLATILE_TREND":  {"trend": 1.0, "mom": 1.0, "osc": 0.4,
                        "flow": 1.5, "vol": 1.2, "micro": 1.3},
    "VOLATILE_CHOPPY": {"trend": 0.7, "mom": 0.7, "osc": 0.8,
                        "flow": 0.8, "vol": 0.6, "micro": 0.6},
    "UNKNOWN":         {k: 1.0 for k in
                        ("trend","mom","osc","flow","vol","micro")},
}

def vote(indicators_output, regime):
    mult = REGIME_MULTIPLIERS[regime]
    score = 0.0
    for name, (direction, strength, category) in indicators_output.items():
        score += direction * strength * mult[category]
    # normalize to [-1, +1]
    max_possible = sum(mult.values()) * N_INDICATORS_PER_CAT
    return score / max_possible
```

The normalized score is your **raw_prob_delta** — how far away from 0.5 the model's probability estimate should be, before calibration.

### 5.4 Contextual fusion — synergies & the MEGA bonus

This is where the architecture goes beyond a linear voter.

**MarketContext** pre-computes three dimensions:
- `pressure ∈ {buyer, seller, neutral}` from CVD sign + aggressor flow sign
- `trend_structure ∈ {higher_highs, lower_lows, range}` from last 5 swing points
- `momentum_character ∈ {building, fading, steady}` from slope of MACD histogram

**Synergies** are named combinations that historically pay better than any single signal. Example: `CVD+AGG` = CVD and aggressor flow both bullish → +0.05 confidence bonus. `TREND+PRESSURE` = structure is HH/HL AND buyer pressure → +0.05.

**MEGA bonus:** when 6+ of the 12 indicators agree on direction AND at least one synergy fires, add a flat +0.08. This is how you encode "when everything lines up, bet bigger."

```python
def fuse(raw_score, ctx, votes):
    prob = 0.5 + 0.5 * raw_score   # map [-1,1] → [0,1]
    agree = sum(1 for v in votes.values() if np.sign(v[0]) == np.sign(raw_score))

    synergies = detect_synergies(votes, ctx)   # returns a list
    bonus = 0.0
    for s in synergies:
        bonus += SYNERGY_BONUSES[s]

    if agree >= 6 and synergies:
        bonus += 0.08  # MEGA

    prob = min(0.95, max(0.05, prob + bonus * np.sign(raw_score)))
    return prob, agree, synergies
```

Cap at 0.95/0.05 — never claim near-certainty on a 15-minute noise horizon.

---

## Part 6 — Layer 3: Filters (Where Most Edge Lives)

Signals are cheap. **Not taking bad trades is where real PnL hides.**

### 6.1 Session schedule

Not all hours trade the same. The London/NYSE overlap (≈13:00–16:00 UTC) statistically shows the highest WR for crypto short-horizon bots because liquidity and directional flow peak. Early Asia morning is the worst — thin books, fake moves.

Build a table:

| Session (UTC) | Min edge | Min BTC move |
|---|---|---|
| 00:00–06:00 (Asia open) | 0.08 | $80 |
| 06:00–12:00 (Asia/EU) | 0.06 | $60 |
| 12:00–16:00 (LDN/NY overlap) | 0.04 | $40 |
| 16:00–20:00 (NY main) | 0.05 | $50 |
| 20:00–24:00 (NY close/Asia) | 0.07 | $70 |

**Edge** = `|your_prob - market_prob|`. A trade fires only if edge exceeds the session threshold. This makes you trade less in weak hours — which is the point.

### 6.2 Confidence calibration

Your brain outputs a probability. Is it actually calibrated? In other words: of all the times your bot said "70% UP", did ~70% actually win?

Almost certainly not — raw model outputs from an ensemble voter are systematically over- or under-confident. Calibration and discrimination are independent; a model that ranks observations correctly can still be overconfident. This is the single most under-implemented piece in amateur bots, and the fix is cheap.

**Platt scaling** fits a 1-D logistic regression that maps your raw probability to a true-probability estimate. After every N trades (say 50), retrain:

```python
# filters/calibrator.py
from sklearn.linear_model import LogisticRegression
import numpy as np

class ConfidenceCalibrator:
    def __init__(self):
        self.model = None
        self.history = []   # [(raw_prob, outcome_0_or_1), ...]

    def record(self, raw_prob, outcome):
        self.history.append((raw_prob, int(outcome)))
        if len(self.history) % 50 == 0 and len(self.history) >= 100:
            self.fit()

    def fit(self):
        X = np.array([[r] for r, _ in self.history])
        y = np.array([o for _, o in self.history])
        # transform to logit space for Platt
        X_logit = np.log(X / (1 - X + 1e-9))
        self.model = LogisticRegression().fit(X_logit, y)

    def calibrate(self, raw_prob):
        if self.model is None:
            return raw_prob
        lg = np.log(raw_prob / (1 - raw_prob + 1e-9))
        return float(self.model.predict_proba([[lg]])[0, 1])
```

Platt scaling is a calibration technique used to convert raw classifier outputs into true probabilities by fitting a logistic regression on the classifier's scores. For a simple voter with limited data, Platt is the right first choice. Upgrade to isotonic regression once you have 500+ trades.

**Edge is computed on the calibrated probability**, not the raw one. This is non-negotiable.

### 6.3 Signal memory — "have I seen this movie before?"

Encode every trade's signal bundle as a **token set**: `{"SUPERTREND_UP", "EMA_CROSS_UP", "MACD_POS", "CVD_BULL", "REGIME_TREND_UP", ...}`. Store token set + regime + outcome.

For each new signal bundle, compute **Jaccard similarity** to past bundles. If any past bundle is ≥0.70 similar, its outcome adjusts current confidence — weighted by **exponential time decay** (7-day half-life; patterns age out of relevance fast in crypto):

```python
# filters/signal_memory.py
import time, math

class SignalMemory:
    def __init__(self, halflife_hours=168):
        self.halflife = halflife_hours
        self.records = []   # [(tokens:set, regime, outcome, ts)]

    def add(self, tokens, regime, outcome):
        self.records.append((set(tokens), regime, int(outcome), time.time()))

    def confidence_adj(self, tokens, regime):
        tokens = set(tokens)
        now = time.time()
        wins, total, wsum = 0.0, 0.0, 0.0
        for past_tokens, past_regime, outcome, ts in self.records:
            if not past_tokens:
                continue
            sim = len(tokens & past_tokens) / len(tokens | past_tokens)
            if past_regime == regime:
                sim *= 1.2
            if sim < 0.70:
                continue
            age_h = (now - ts) / 3600
            w = sim * math.exp(-age_h * math.log(2) / self.halflife)
            wsum += w
            wins += w * outcome
            total += w
        if total < 2.0:   # not enough evidence
            return 0.0
        empirical_wr = wins / total
        return (empirical_wr - 0.5) * 0.15   # scale factor
```

### 6.4 Vetoes

**VolumeVeto (hard block).** If all four volume indicators (CVD, VDELTA, liquidations, aggressors) point *against* your entry, block. This single rule eliminates a huge class of fake breakouts. In the CYCLOPS author's logs this was adopted after a specific loss: "all volume against, bot entered anyway, BTC dropped."

**StochRSIVeto (conditional).** If StochRSI is at extreme (>95 or <5) AND consensus isn't overwhelming (<6 indicators), block — you're at exhaustion. If consensus IS overwhelming, let it through (the trend is strong enough).

**PeriodTracker (intra-period).** Within the 15-minute market period, monitor BTC's direction. If you want to bet UP but BTC has moved down $200 in the last 8 minutes of a 15-minute window, the mean-reversion probability is small. Block.

### 6.5 Risk gates

- **Max Drawdown** — if account down X% from peak, stop trading for the day. (Typical: 15%.)
- **Daily Loss Limit** — X% daily P&L drawdown → freeze until next UTC day. (Typical: 5%.)
- **Position Concurrency** — never more than 1 open Polymarket position per underlying market.

---

## Part 7 — Position Sizing: SmartKelly

### 7.1 The core formula

For a binary market priced at `market_price` where you believe true probability is `p`:

```
b = (1 - market_price) / market_price          # net odds if you win
f* = (b*p - (1-p)) / b                         # full Kelly fraction
```

Fractional Kelly (typically 0.25x to 0.5x full Kelly) reduces volatility and protects against probability estimation errors. Fractional Kelly strategies reduce volatility more than they proportionally reduce expected growth, offering a pragmatic trade-off between growth and risk control. This is the essential upgrade — full Kelly on estimated probabilities blows up accounts because your probability estimates are noisy.

**Start at 0.25× Kelly.** Move to 0.33× only after 500+ trades of validated performance.

### 7.2 Context modifiers

CYCLOPS calls it "SmartKelly." The idea: the base Kelly answer is a *maximum*; you shade it down when signal quality is weaker.

```python
# exec/kelly.py
def smart_kelly(p, market_price, bankroll, *,
                agree_count, synergies, ctx_pressure,
                fast_slow_conflict, base_fraction=0.25):
    q = 1 - p
    b = (1 - market_price) / market_price
    if b <= 0:
        return 0.0
    f_full = (b * p - q) / b
    if f_full <= 0:
        return 0.0

    # start with fractional Kelly
    f = f_full * base_fraction

    # modifiers
    if agree_count >= 6: f *= 1.25
    elif agree_count <= 3: f *= 0.6

    if synergies: f *= 1 + 0.05 * len(synergies)
    if ctx_pressure == "confirmed": f *= 1.1
    if fast_slow_conflict: f *= 0.7

    # hard caps
    f = min(f, 0.02)          # never > 2% of bankroll on one trade
    return f * bankroll
```

**Never risk more than 2% of bankroll on a single 15-minute bet**, regardless of what Kelly says. This is a survival rule. A 10-trade losing streak at 2% = -18% drawdown; at 5% = -40% and psychological/strategic ruin.

---

## Part 8 — Execution

### 8.1 Placing an order on Polymarket

Use `py-clob-client`. Submit a `GTC` limit order at the best ask (to act like a taker but avoid price slippage on fast moves):

```python
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

def place_entry(client, token_id, price, size_usd):
    # size in shares = size_usd / price (since each share pays $1 max)
    shares = round(size_usd / price, 2)
    order = client.create_order(OrderArgs(
        token_id=token_id,
        price=price,
        size=shares,
        side=BUY,
    ))
    resp = client.post_order(order, OrderType.GTC)
    return resp
```

Read the response carefully. **Silent failures are the single biggest cause of bot losses in early versions** — an API call that returned 200 OK but didn't actually place the order. Always poll `client.get_order(order_id)` and verify `status == 'MATCHED'` or `'LIVE'`.

### 8.2 Settlement

The bot doesn't exit — 15-min markets self-settle. After `close_ts`, fetch the reference BTC price from Chainlink at that exact timestamp, resolve WIN/LOSS, record:

```python
# exec/settlement.py — runs in a thread per trade
def settle(trade, price_feed, calibrator, memory, db):
    wait_until(trade.close_ts + 5)      # small buffer for oracle finality
    close_price = price_feed.at(trade.close_ts)
    won = (close_price > trade.strike) == (trade.direction == "UP")
    db.update_trade(trade.id, outcome=won, close_price=close_price)
    calibrator.record(trade.raw_prob, won)
    memory.add(trade.tokens, trade.regime, won)
    notify_telegram(f"Trade {trade.id}: {'WIN' if won else 'LOSS'} @ {close_price}")
```

---

## Part 9 — The Main Loop

Exactly what CYCLOPS does, ~5 second cadence:

```python
# app/main_loop.py
async def run(bot):
    while True:
        try:
            bot.daily_check()                      # roll UTC day if needed
            if not bot.risk_ok():                  # drawdown / daily limit
                await asyncio.sleep(5); continue

            sess = bot.schedule.current_session()
            if not sess.allowed:
                await asyncio.sleep(5); continue

            btc = bot.price_feed.last_price
            markets = bot.gamma.list_active_btc_15m()

            for m in markets:
                sig = bot.brain.evaluate(m, btc)
                if not sig:
                    continue

                calibrated = bot.calibrator.calibrate(sig.raw_prob)
                edge = abs(calibrated - m.market_price_yes)
                if edge < sess.min_edge:
                    continue

                if bot.vetoes.any_hard_block(sig, m):
                    continue

                size = smart_kelly(calibrated, m.market_price_yes,
                                   bot.bankroll, **sig.ctx_kwargs)
                if size < bot.min_trade_usd:
                    continue

                order = bot.exec.place(m.token_id_yes if sig.direction=="UP"
                                       else m.token_id_no,
                                       m.market_price_yes, size)
                bot.schedule_settlement(order, m.close_ts, sig)
                break   # one trade per cycle
        except Exception as e:
            bot.logger.exception("loop error")

        await asyncio.sleep(5)
```

---

## Part 10 — Supporting Systems

### 10.1 Telegram control

Standard commands:
- `/status` — bankroll, open positions, today's P&L, regime, last signal
- `/pause` / `/start` — soft kill switch
- `/stop` — hard kill (requires confirmation)
- `/claim` — harvest settled winnings from Polymarket contract

A **separate public signal channel** broadcasts direction + strength + result, without exposing edge or internals. Useful for accountability and eventual monetization, but noise-free: no commentary, just signals.

### 10.2 Watchdog

A thread that pings `bot.last_cycle_ts` every minute. If it's been silent > 30 minutes, send an alert. Crypto bots die silently in production — WebSocket half-close, event loop deadlock, OOM — and without a watchdog you find out from your PnL.

### 10.3 Logging

Every cycle writes a structured JSON line: timestamp, regime, every indicator vote, raw prob, calibrated prob, edge, size, decision (traded / vetoed_by / skipped). This log **is the product**. Every future fix you make will start with "open the logs at timestamp X and see what happened." Ship this on day one.

---

## Part 11 — Backtesting & Validation

Before touching real money, you need a backtest that's **not a lie**.

The hard part: Polymarket's 15-min markets only exist going forward. You can't replay historical order books cleanly. Two practical options:

1. **Forward paper trade.** Run the bot for 2–4 weeks logging decisions *without* placing real orders. Compare logged decisions to actual market resolutions. This is slow but honest.
2. **Pseudo-backtest on BTC price only.** Replay Binance 1-second klines, run your brain, pretend Polymarket prices were efficient (equal to rolling historical WR for each regime). Estimate win-rate and PnL. This overstates edge (no market impact, no slippage) but tells you if the brain has any signal at all. If it doesn't work here, it won't work live.

**Purged K-fold cross-validation** is the gold standard for avoiding lookahead bias in financial ML. A random calibration split leaks information across the purge boundary; OOF predictions through PurgedKFold with the correct embargo are the only valid calibration data source for financial data with overlapping labels. When you graduate the calibrator to something heavier, use López de Prado's purged-CV.

Key metrics to track:
- **Hit rate** (raw and by session/regime)
- **Brier score** — `mean((p - outcome)^2)`, lower is better. This measures calibration directly.
- **Max drawdown**
- **Sharpe** on daily P&L
- **Kelly growth rate** — `mean(log(1 + f * R))` where R is per-trade return

---

## Part 12 — Development Philosophy (This Is The Most Important Section)

The CYCLOPS article makes a point that every version was a response to a specific logged incident, not abstract optimization. Internalize this. **Your bot will be wrong in ways you cannot predict a priori.** The entire job is:

1. Log everything, timestamped, structured.
2. When a trade loses, open the log and find *why*.
3. Encode the lesson as a new rule, veto, or weight adjustment.
4. Never remove a rule without a documented reason.

Every fix becomes a docstring comment in code:

```python
# STOCH_RSI_VETO (v47, 2025-11-03)
# Case: 15:51 UTC, 8 indicators bullish, StochRSI at 2.1 blocked entry.
# BTC rose $130. Block was wrong because consensus was overwhelming.
# Fix: allow StochRSI extreme override when agree_count >= 6.
def stoch_rsi_veto(stoch, agree_count):
    if agree_count >= 6:
        return False
    return stoch > 95 or stoch < 5
```

This is the "Senior Software Engineer approach to AI debugging" you already follow — pass strict, comprehensive markdown documentation between debugging sessions. Apply the same discipline to version-to-version of your own bot.

---

## Part 13 — A Realistic 12-Week Build Plan

**Weeks 1–2 — Data layer.** Chainlink WS → candles. Binance liquidation stream. Polymarket Gamma polling + CLOB WebSocket. Just log everything and watch the logs scroll. Nothing else.

**Weeks 3–4 — Indicators + Regime.** Implement all 12 indicators, unit test each against `ta-lib`. Build the regime detector with hysteresis. Watch the regime classification align with what you'd subjectively call the market state.

**Week 5 — Brain.** Voting + ContextualFusion. No trading yet — just output probability forecasts to the log. Eyeball them vs. actual 15-min outcomes.

**Week 6 — Filters.** Schedule, vetoes, signal memory. Still not trading.

**Week 7 — Paper trade.** Route decisions to a simulated executor. Track WR, Brier score, hypothetical P&L. If Brier > 0.25 (worse than random on binary), stop and debug; don't advance.

**Week 8 — Calibrator.** Once you have 200+ simulated trades, fit Platt. See if calibrated edge outperforms raw edge. This should be a measurable, reproducible improvement.

**Week 9 — SmartKelly + Execution.** Wire up `py-clob-client`. Live-test with **$1–5 size** for at least 50 trades. Polymarket has no demo or testnet environment; all API calls hit production, so start with minimal position sizes when testing. Your goal is zero silent failures, not profit.

**Week 10 — Risk + Watchdog + Telegram.** Drawdown stops, daily limits, alerting. Test each safety mechanism by simulating a drawdown in a sandbox DB.

**Week 11 — Scale up.** Raise from $5 to $25 per trade. Only after another 100 trades and confirmed WR matching paper trade.

**Week 12 — Ongoing.** Keep scaling 2× every 2 weeks if metrics hold. Retrain calibrator every 50 trades. Write post-mortem for every losing streak > 3.

---

## Part 14 — What To Be Paranoid About

1. **Private key leaks.** Use a dedicated trading wallet, funded from cold storage, never your main wallet. Rotate the Polymarket API key anytime you change machines.
2. **EIP-712 signing bugs.** One wrong `chain_id` or `signature_type` and your orders silently reject. Log every order response in full.
3. **Timezone confusion.** Always UTC in storage. Display in your local TZ (Florianópolis, America/Sao_Paulo) only in the Telegram UI.
4. **Settlement oracle drift.** The price Polymarket resolves at may differ from your Chainlink price by a few dollars due to aggregation method differences. Treat your self-computed WIN/LOSS as a *tentative* label; reconcile against Polymarket's on-chain resolution daily.
5. **Probability clipping.** Never let calibrated probability hit exactly 0 or 1 — Kelly divides by (1-p). Clip to [0.02, 0.98].
6. **Reentrancy on the main loop.** If evaluation takes longer than the 5s cycle (it will sometimes, on a slow API response), skip this iteration — don't queue up backlog.
7. **Polymarket fee schedule changes.** Fees aren't zero. Bake them into your edge threshold: `edge_required = session_min_edge + fee_buffer`.

---

## Part 15 — Reading List (Curated, No Filler)

**Prediction markets math (required)**
- Wolfers & Zitzewitz, *Prediction Markets*, J. Economic Perspectives — why market prices approximate probabilities and where they deviate.
- The Math of Prediction Markets: Binary Options, Kelly Criterion, and CLOB Pricing Mechanics (Navnoor Bawa, Substack) — concise, modern.

**Kelly & position sizing**
- Kelly 1956 (the original paper, surprisingly readable).
- Thorp, *The Kelly Capital Growth Investment Criterion* — fractional Kelly in practice.
- Maclean, Thorp, Ziemba, *Good and Bad Properties of the Kelly Criterion*.

**Order flow / microstructure**
- Harris, *Trading and Exchanges* — the bible for CLOB mechanics, market vs. limit orders, hidden liquidity.
- CVD literature: Bookmap and Coinalyze have solid primers; CoinMarketCap's CVD article is a good start.

**Probability calibration**
- Platt 1999 (the original SVM calibration paper).
- Guo et al., *On Calibration of Modern Neural Networks* — ECE, reliability diagrams.
- scikit-learn's `CalibratedClassifierCV` docs — all you need operationally.

**Market regimes**
- López de Prado, *Advances in Financial Machine Learning*, Ch. 5 (Fractional Differentiation) and Ch. 7 (Cross-Validation) — for when you upgrade beyond the ADX/vol heuristic.
- QuantStart's HMM regime detection series.

**Polymarket-specific**
- Official Polymarket docs: `docs.polymarket.com`.
- `py-clob-client` source code — read it, the examples are embedded.
- NautilusTrader's Polymarket integration docs — production-grade reference for order signing patterns.

---

## Closing: The Meta-Rule

CYCLOPS is not a strategy. It is a **discipline**: trade only when many independent eyes agree, in a regime where they're allowed to vote, during hours where noise is lowest, with size proportional to your calibrated edge, and stop the moment your account tells you you're wrong.

The edge isn't any single indicator. The edge is that you don't trade when you shouldn't. Build accordingly.
