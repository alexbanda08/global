# Ireland ladder + racer + latency tape — 6-day live research (Jun 24 → 30)
**2026-06-29. The full moat stack (4-conn WS racer + early-placed paper ladder + per-hop latency tape) running on the Ireland TVRUST box (`vps_ireland`, `tradingvenue_rust` DB). Data = `trading.events` kinds `ladder_summary`/`feed_quality`/`tick_latency`. PAPER (modeled FIFO fills on the live racer feed) — no capital.**

## Headline — the offline pair-fraction NO-GO is BEATEN live
The offline maker-ladder sim ceilinged at **~29% pair fraction** (joining the FIFO queue at +60s) and was a NO-GO. **Live, with the racer + early placement, pair fraction is 0.79.** That's the live-only edge the b945 article described — and we now have 6 days of evidence the infra changes the picture.

### Ladder (452 windows, all BTC-15m)
| metric | value | read |
|---|---|---|
| **pair_frac** | **0.791** | ↑↑ vs offline 0.29 — the queue blocker is SOLVED live |
| **pvs** (paired vwap sum) | 0.963 | matched pairs cost < $1 — the capture engine works |
| **flow_capture** | **1.73%** | ↓ vs b945 ~11.5% / offline ceiling 4–7% — we UNDER-capture |
| maker_pct | 100% | pure maker; taker_completions 0 |
| **net_paired** (locked) | **+$1.38/window** | **+$622.93 over 6 d (~$104/d) — PAIRED ONLY** |
| rebate | +$49.74 (~$8/d) | income |
| residual_sh | 9.1 sh/window held | the directional **drag — PnL NOT logged** |

### 🔴 The deciding gap: residual PnL is not measured
`net_paired_estimate` is the **matched-pair** PnL only. The **residual** (9.1 sh/window held directionally — the b945 "−$29k drag" component) is logged as *shares*, not PnL. So **+$623 is NOT the net** — true net = paired (+$623) − residual drag (unmeasured). The offline full-net was −$0.05/window; if the live residual drag is ~−$1.4/window it cancels the paired gain → net ~0. **We cannot call this profitable until the ladder logs `residual_pnl` (held-to-resolution outcome of the residual side).** This is the #1 telemetry fix.

## Racer (feed_quality, 6-day avg)
- **4 connections**, dedup first-wins ~2561/tick, multiple conns winning the race (conn0 22 / conn2 10 / conn1 4 in the sample) → redundancy + freshness working. `recorder_dropped 0`.
- ⚠️ **avg book_age ≈ 80 s** — inflated by inactive/pre-window ticks, but high; in active windows the sample showed ~141 ms. Worth confirming the active-window book is actually fresh (could be the unfixed `price_change` parse bug → book updates only on snapshots).
- ⚠️ **warmup_pass ≈ 20%** — 80% of ticks/windows fail the data-quality warmup gate. Either the gate is too strict or feed quality is poor; limits coverage. Investigate.
- ⚠️ **4.29 M deltas rejected** (the >15¢ outlier gate) over 6 d — verify it's not over-rejecting real moves.

## Latency tape (tick_latency, 203k samples)
- `recv_to_apply`: **p50 21 µs, p95 44 µs** (worst 145 ms = one outlier). Excellent — the Rust hot path is ~20 µs. Latency is NOT a constraint.

## What this changes
- **Pair fraction (the offline blocker) is solved live (0.79).** The racer + early placement deliver the queue priority the offline sim couldn't model. This is real, 6-day evidence — it reframes the b945 maker NO-GO.
- **BUT not yet a green light:** (1) flow capture is low (1.73% vs b945 11.5%) — we capture a small slice; (2) the residual drag is unmeasured — true net unknown; (3) feed-quality flags (80 s avg book age, 20% warmup, 4.3 M rejects) need a look.

## Next (in priority)
1. **Add `residual_pnl` to `ladder_summary`** (held-to-resolution outcome of the residual side) → compute the TRUE net = paired + residual + rebate. Until then "+$623" is paired-only, not profit.
2. **Diagnose the feed-quality flags** — is the active-window book actually fresh (vs the `price_change` parse bug), why 80% warmup fails, is the 4.3 M reject gate too aggressive.
3. **Why is capture only 1.73%?** (vs b945 11.5%) — quoting too thin / too few levels? The ladder is single-clip; b945 is dense multi-level EV-layering.
4. Re-decide the b945 deploy question on the TRUE net once #1 lands.
