# SCALP CAPACITY PROSPECT — per market (2026-06-13)

Strategy: the one validated live edge — **oracle-lag exit-scalp** (fire slot_start+5s on |binance-1s 5s-ret|≥3bps,
buy lead token at ask if entry_vwap<0.55, **pure +60s time-sell**, no stop/TP). Causal signal (patched 2026-06-13).
Depth model: production L25 (Apr22–Jun11), real multi-level walk on entry asks + +60s exit bids.

**Coverage:** BTC/ETH/SOL × {5m,15m} only — the sole coins with production L25 depth. **DOGE/XRP/BNB have NO L25
depth** (BBO top-of-book only) → not depth-sizeable here; they were OOS-validated on BBO but capacity is unknown.

## Method & honesty caveats (read first)
- **In-sample window.** Apr22–Jun11 is the search window → absolute $/tr is optimistic. Causal OOS (BBO Mar30–Apr21)
  says $25 $/tr ≈ +0.9–1.5 vs in-sample +3.1 → **OOS haircut ≈ ×0.35** (band ×0.30–0.45).
- **Haircut is clean only in the low-slippage zone.** Slippage is a fixed $ cost (book depth), not edge — so at the
  capacity ceiling, OOS net dies *faster* than ×0.35 implies. Recommended deploy stays where fillfrac≈1 and exit vwap
  hasn't eroded (the linear zone), so ×0.35 is valid there.
- **MaxDD shown is IN-SAMPLE = a FLOOR.** Real DD is worse (in-sample overstates edge → understates loss runs), and
  BTC/ETH/SOL are highly correlated → drawdowns stack concurrently. Plan for ~1.5–2× the floor.
- **fires/day already nets the ~64% entry-fill rate** (fires with no L25 book at fire+85ms are dropped).
- **These are MODELED projections.** Live evidence is still ~20 fires. The real number is the live wallet, not this.

## Capacity ceiling (where in-sample CI95 crosses 0 — the depth limit)

| Market | fires/day | ceiling stake $ | binding constraint |
|---|---|---|---|
| BTC 5m | 4.0 | **$800** | deepest book; entry never caps, exit slips slowly |
| BTC 15m | 3.0 | **$300** | |
| ETH 5m | 3.6 | **$200** | exit-bid depth |
| ETH 15m | 4.8 | **$150** | |
| SOL 5m | 6.0 | **$50** | thin book; dies fast |
| SOL 15m | 5.3 | **$50** | thinnest |

## RECOMMENDED DEPLOY (low-slippage zone, OOS-anchored ×0.35)

| Market | rec stake $ | fires/day | $/tr OOS | **1-mo profit OOS** | 1-mo band (×.30–.45) | MaxDD floor (IS) |
|---|---|---|---|---|---|---|
| BTC 5m | 200 | 4.0 | +10.5 | **+1,268** | 1,086–1,630 | $309 |
| BTC 15m | 150 | 3.2 | +4.3 | **+405** | 347–521 | $219 |
| ETH 5m | 100 | 4.6 | +3.4 | **+474** | 406–609 | $234 |
| ETH 15m | 100 | 5.2 | +2.4 | **+376** | 322–483 | $136 |
| SOL 5m | 50 | 6.0 | +1.6 | **+237** | 203–305 | $78 |
| SOL 15m | 50 | 5.3 | +0.9 | **+115** | 98–148 | $42 |
| **TOTAL** | **$650 / fire** | ~26/day | — | **≈ +$2,875 / month** | **2,460–3,700** | **$1,176 floor → plan ~$2,000–2,500** |

## Working capital & verdict
- **Capital at risk per simultaneous fire ≈ $650** (sum of rec stakes). With overlapping 5m/15m windows and ~60s holds,
  peak concurrency is a few fires → **~$1,500–2,000 working capital** is comfortable (incl. buffer).
- **Expected ~$2.9k/month OOS-anchored** (band $2.5–3.7k), **MaxDD plan ~$2.0–2.5k** → ~1.2–1.5× monthly profit as DD
  reserve. Calmar ≈ 1.2–1.4 (modeled).
- **BTC 5m is the workhorse** (~44% of expected profit, deepest book, highest ceiling). SOL is capacity-starved
  ($50 cap) — barely worth the operational slot; consider dropping SOL 15m.
- **Scaling lever is the EXIT, not the entry.** Entry asks absorb $800+ on BTC; the +60s dump is what erodes vwap_x.
  To raise ceilings: stagger the exit (sell in 2–3 child orders +45/+60/+75s) or use the synthetic exit
  (sell lead bid ∪ buy opp ask). Untested — would extend BTC 5m past $800 if it works.

**Bottom line:** at current depth, the scalp is a **~$1.5–2k-capital, ~$3k/month (OOS) operation**, MaxDD ~$2–2.5k,
BTC-5m-dominated. Not scalable to large capital without an exit-execution upgrade. Numbers are modeled off an
in-sample window haircut to the causal OOS — treat as a planning envelope, confirm on ≥200 live fires.
