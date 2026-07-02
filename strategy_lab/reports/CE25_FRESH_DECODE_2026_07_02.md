# Agile-Spacing (0xce25e214…7fdc) fresh decode — signature EVOLVED; he now trades like our ladder+V2 hybrid
**2026-07-02. 2-stage agent pull: data-api fills + gamma-api resolutions (all 288 slugs resolved, 100%). Window: Jul 1 21:17 → Jul 2 05:48 UTC (8.5h — the data-api hard-caps history at offset≤3000 ≈ 3,500 rows; this wallet burns that in <9h). Raw: `wallet_hunt/cache/0xce25e214/{trades_recent_2026_07_02.csv, per_slug_pnl_2026_07_02.csv}`.**

## 1. He's still printing — the user's "1–2k/day" is right
- Window (8.5h, ALL fills resolved): **gross +$1,192 → fee-adj +$631 ≈ +$1,776/day pace.**
- Lifetime (lb-api): **+$384,592** (was +$300,397 on Jun 12 → **+$84k in 3 weeks ≈ $4k/day** across the stretch). Lifetime volume $29.8M.
- **Working capital: peak outstanding only ~$2,410 in-window** (lower bound; live positions show 600–700-share legs → true footprint maybe $3–5k). He turns capital ~50–100×/day through 5m/15m resolution cycles — the edge is thin per slug (+$2.19 mean, median +$0.19, 51% slug WR) and the money is SCALE: ~810 slugs/day pace, $123k/day volume, 8 markets.
- Per-coin (this window): **BTC +$11.23/slug (n=77)**, ETH +$2.46, **SOL −$4.28, XRP −$2.01** — the profit concentrates in BTC; the tails may be regime noise (n≈70/coin).
- Fee drag (modeled winner-only taker curve): **$561 = 47% of gross** — massive, because his entries cluster near p=0.5 where the 0.07 curve peaks.

## 2. 🔴 THE HEADLINE: his signature CHANGED since Jun 12
| dimension | Jun 12 decode | now (Jul 1–2) |
|---|---|---|
| entry timing | 78% in first 60s (open-racer) | **14.7% in first 60s; p50 = 223s — spread across the whole window** |
| execution | single/few taker fills | **multi-clip ladder: mean 12 fills/slug (up to 100), median clip $8.25** |
| pair rate | 99.5% | 86%, and pair_fraction only 0.55 (big imbalances) |
| pvs | tight ~1.041 | **wide: min 0.34, 41% of paired slugs <1.0, 33.5% <0.97** |
| sells | none | none (still pure hold-to-resolution + redeem) |
| universe | btc/eth/sol/xrp × 5m/15m | unchanged |

**My read:** the fill pattern — many small clips arriving stochastically all window long, both sides, imbalanced, sometimes very cheap combined sums — is the signature of **passive/dip accumulation on both sides across the window**, not open-racing taker arb. Two candidate mechanics (indistinguishable from this pull alone):
- **(a) Maker laddering** (resting bids both sides getting hit piecemeal) — if so he pays $0 fees + rebates and our fee-adj UNDERSTATES his true PnL by ~$561/8.5h; this is the b945/our-poly_ladder model at scale.
- **(b) Taker dip-sniping per side** (buy each side on its own dip, all window) — our V2 sumpair osc-harvest, unconditional and multi-clip.
Either way: **he has converged on exactly the two designs we're currently building** (the two-sided ladder + the dip-pair accumulation), run across 8 markets with high turnover.

Reconciliation with our ladder's residual problem: his pair_fraction is only 0.55 → huge residual, yet he nets positive. His residual inventory is dip-priced (bought cheap), while our v2 ladder's residual was the side flow dumped into at the favorite band (won 14.7%). His per-slug WR of 51% with positive mean says his residual isn't as adversely selected — likely because dip-buying below ~0.4–0.45 has positive hold-EV even at coin-flip outcomes. That's a design hint for our v3: **skew the book cheap; never accumulate the expensive side.**

## 3. Is OUR strategy mimicking him?
- **Scalp: NO — and it shouldn't.** Different edge (directional Binance-lag, +60s exit, one side). Its ~$505/mo at $25 clips is a capacity-bounded side income, not a competitor to his model. Don't judge it against his $1.8k/day.
- **V2 sumpair osc-harvest: half of him.** Same dip-buy-both-sides idea, but ours is signal-gated (3bp lag), 1 clip firm, BTC/ETH-5m only, residual scalp-exited. He: unconditional, ~12 clips/slug, 8 markets, residual held.
- **Ladder (poly_ladder v2/v3): the other half of him.** Two-sided passive capture + pair-lock + residual — his current execution style looks most like this.
- **What we lack vs him:** (1) scale — 8 markets × ~810 slugs/day vs our 1–2 markets; (2) multi-clip — we hard-capped MAX_CLIPS=1 (the multi-clip "upside" was an L25-corruption artifact — but HIS live tape is evidence multi-clip accumulation works; re-test on clean delta data); (3) capture — our ladder catches 1.7% of flow, his footprint implies far more; (4) residual philosophy — he holds cheap residual, we exit ours (our v3 backstop) — his way only works below ~0.45 entry.

## 4. Path from $500/mo to his league (staged, gated)
1. **Ladder v3 (residual-managed) BTC-15m paper** — in flight. Gate: total_net CI>0. Target ≈ +$1.2–1.6/win ≈ **$115–155/day** on ONE market (already 2–3× the scalp's monthly, per day).
2. **Expand ladder to BTC-5m + ETH (skip SOL/XRP first — even HE loses there this window)** → 3–4 markets ≈ **$300–600/day** at same per-win take. Working capital ~$2–4k (his footprint).
3. **Multi-clip re-validation on clean delta data** (his 12 clips/slug vs our 1) + cheap-side skew (his residual lesson) → the flow_capture 1.7%→5–10% lever ≈ path toward **$1k+/day**.
4. **Fee edge over him:** if he's taker, he burns 47% of gross in fees; our maker ladder pays $0 + rebate on the same flow — a structural ~2× advantage per captured dollar. (If he's maker, we're at parity and his numbers are directly our ceiling map.)
5. Capital: his league needs only **$3–5k working capital** — capital is NOT the constraint; capture and validated residual management are.

## 5. Infra/API facts banked
- **data-api hard cap: offset≤3000 (~3,500 rows), no time params** → full-day decoding of high-frequency wallets is impossible via REST; use Alchemy chain decode (no cap) or forward polling. lb-api /profit+/volume accept ONLY window=1d|all.
- **gamma-api `/events?slug=` resolves EVERYTHING incl XRP** (288/288 here; 100% agreement with vps3 on the 156 overlapping) — fixes our XRP-outcome blind spot.
- **vps3 `market_resolutions_v2` has structural gaps:** ~50% of slugs missing (hourly batch job), **0% XRP** (no XRP oracle collector exists on storedata at all — chainlink/lazer tables carry only BTC/ETH/SOL). Flag to storedata agent if XRP work matters.
- lb-api window=1d showed −$340 vs our +$631 window — scope mismatch (our 8.5h ≠ their 24h; not a contradiction, both partial views).

## 6. Actions
1. Proceed with ladder v3 + sumpair shadow exactly as in flight — his fresh tape is independent live evidence the design class prints at scale.
2. Add to v3 spec follow-ups: **cheap-side skew** (never accumulate the expensive side; his residual survives because it's dip-priced) — testable offline on our v2 ladder_tick tape.
3. After storedata deltas fixed: **multi-clip re-study on clean book data** (pre-registered; the old artifact verdict may be wrong — his live behavior is the counter-evidence).
4. Maker-vs-taker classification of his fills (cross-reference his btc-15m fill prices/times vs OUR Ireland racer book tape — we hold the book truth for those exact slugs) — settles whether his fee bill is real and sizes our fee edge.
