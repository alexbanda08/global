# PBot-6 (`0x21d0a97aac03917e752857a551bbe5103a00e8d7`) decoded — 2026-08-13

Fresh pull: **121,694 trades (hit the 120k cap), Jul 1 → Aug 13 (~44 days)**, 31,781
redeems, 0 merges, 0 splits. Identity: `PBot-6` / "Tangible-Friendship".
**Lifetime profit +$205,680** (lb-api), portfolio value parked: **$583** — full recycle.
Scripts: same pipeline as b945 (`_refresh…py 0x21d0…`, `_analyze_updown_behavior…`,
`_b945_window_pnl… 0x21d0a97a`).

## 1. What it is — a THIRD strategy on the same books

**A pre-open discount-collecting maker.** ~98.7% maker (taker fills: 2/h vs 140/h total).
It does NOT pair (ratio 0.32), never sells, never merges, holds everything to settlement.

The signature nobody else has: **82–84% of its buy USD fills BEFORE the window opens** —
and **97.4% of that lands in the final 5 minutes pre-open** ($978k of $1.0M pre-open
volume; zero fills earlier than 30min). It rests bids a few ticks under fair on the
embryo book (heavy-side vwap 0.476–0.487 vs the 0.50/0.51 pre-open touch) and collects
whoever dumps into the next window early. Post-open it goes nearly quiet (8.5% of USD in
the first minute, <2% in the last).

vs the family:

| | b945 (15m) | b27 (5m) | **PBot-6** |
|---|---|---|---|
| niche | in-window pairing + TC | in-window pairing + merge | **pre-open flow collection** |
| pre-open fills | 0% | 0% | **82–84% of USD** |
| paired:resid | 5.53 | 4.07 | **0.32** |
| profit engine | pair spread + selected residual | pair spread × velocity | **discounted residual, held** |
| WR / payoff | 78% / 1.77 | — | **51.6% / 1.34** |

## 2. The complete window table (14,904 settled windows, cash-truth)

| | 15m | 5m | ALL |
|---|---:|---:|---:|
| windows | 4,446 | 10,458 | 14,904 (~340/day — every btc+eth window) |
| capital/window mean · median · p90 | $77 · $46 · $190 | $83 · $22 · $194 | $81 · $29 |
| profitable | 2,275 (51.2%) | 5,421 (51.8%) | **7,696 (51.6%)** |
| avg win | +$64.56 | +$70.28 | **+$68.59** |
| losing | 2,171 (48.8%) | 5,026 (48.1%) | 7,197 (48.3%) |
| avg loss | −$47.71 | −$52.92 | **−$51.35** |
| **NET** | **+$43,282** | **+$115,001** | **+$158,283 (+$10.62/w)** |
| **ROI on deployed** | **12.61%** | **13.24%** | **13.06%** |

≈ **$3,600/day** trading + **$10,273 rebates in-period** (lifetime rebates $48,068 =
**23% of lifetime profit** — the rebate line is a quarter of the business).

## 3. Profit sources and loss causes

| P&L source (ALL) | net |
|---|---:|
| **residual settlement** | **+$162,219** (gross +$514k / −$352k) |
| paired spread | **−$3,936** (it pays for what little pairing it does) |
| rebates (period) | +$10,273 |

| loss cause | windows | $ |
|---|---:|---:|
| residual lost (side ≠ winner) | 3,442 | −$279,395 |
| one-sided lost | 3,607 | −$87,613 |
| pvs>1 | 148 | −$2,566 |

The edge is arithmetic, not prediction: buy at ~0.476 what settles 51.6% of the time your
way → EV/share ≈ 0.516 − 0.476 ≈ **+4¢**, × ~1.6M shares ≈ the $158k observed. Half the
edge is the pre-open discount (uninformed early flow sells to it below fair), half is a
genuinely >50% hit rate (mild informed selection or flow-side correlation), and rebates
gross it up ~25%.

## 4. What this means for OUR ladder

1. **The pre-open 5 minutes is a real, large flow zone** (~$23k/day collected at discount
   by this one bot). Our `placement_offset_s=−3600` already RESTS there for queue
   priority — but our accounting, caps and sim treat pre-open as dead time, and our live
   sessions to date only ever filled post-open. Measurable question, pre-registerable:
   do OUR resting clips take pre-open fills, at what discount, and with what settle-EV?
   (The `ladder_tick`/summary pipeline can answer this from data already flowing.)
2. **Rebate economics are not a footnote** — 23% of PBot-6's lifetime P&L, ~11% of
   b945's period P&L. Our `rebate_rate_assumed=0.0015` flat is materially wrong at scale;
   get the real tier schedule before any sizing decision.
3. **Three profitable niches now mapped on the same books** — pre-open collection
   (PBot-6), in-window pairing 15m (b945), in-window pairing 5m at velocity + merge
   (b27). All three: pure maker, never sell, hold to settle. Our current live design
   (in-window 5m pairing with recycle-sells) matches none of the three winners exactly;
   the closest winner template for our capital size ($55!) is b27's — but the capital
   math (median $29–$869/window across these wallets) says we are 1–2 orders of
   magnitude under ALL of them.
4. "PBot-**6**" implies a fleet (PBot-1..N). Worth one cheap sweep of the leaderboard for
   siblings — same fetch pipeline, one command per wallet — to see whether the niches
   are partitioned across numbered bots (a future session's task).

## 5. ADDENDUM (same day): the side-selection mystery SOLVED — there is no selection

Mechanism tests (`_pbot6_side_mechanism_2026_08_13.py` + VPS3 1m klines join):
drift REJECTED (base P(Up)=49.0%, WR symmetric 53.3/54.7 Up/Down); BTC momentum
REJECTED (agree 50.7–55.9% across 8 signal definitions; WR aligned 63.3% ≈ anti 62.0%);
prev-window momentum REJECTED (follow 53.9% ≈ fade 55.0%). The decisive split:

| fills | sh | vwap | share-wtd WR | EV/share | ROI |
|---|---:|---:|---:|---:|---:|
| **pre-open** | 2,137,734 | 0.4690 | 52.36% | **+5.46¢** | **+11.6%** |
| post-open | 380,818 | 0.5497 | 53.89% | **−1.08¢** | −2.0% |

The pre-open price is ~calibrated (price ≈ probability, ±2–5pp in every bucket); the
whole edge is buying ~5¢ BELOW it as resting maker against impatient sellers in the
final 5 minutes. The "51.6% winner-picking" is what calibration delivers at 0.469 entry
— no signal exists. Its post-open leftovers LOSE (−2%) — an improvable defect.
Strategy port: [TV_AGENT_SPEC_TVRUST_V6_PREOPEN_2026_08_13.md](TV_AGENT_SPEC_TVRUST_V6_PREOPEN_2026_08_13.md).

Caveats: trade window truncated at the 120k cap (Jul 1 start — lifetime is longer);
winner inference from redemption-matching as before; pre-open discount estimate uses
heavy-side vwap vs 0.50 anchor, not tick-level book data.
