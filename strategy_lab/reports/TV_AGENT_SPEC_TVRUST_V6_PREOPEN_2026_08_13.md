# TV_AGENT_SPEC — `v6_preopen`: pre-open discount collector — 2026-08-13

**Status: SPEC — paper only, pre-registered, thresholds FROZEN before first run.**
Basis: full decode of PBot-6 `0x21d0a97aac03917e752857a551bbe5103a00e8d7`
([PBOT6_WALLET_DECODE_2026_08_13.md](PBOT6_WALLET_DECODE_2026_08_13.md) + the mechanism
tests in `wallet_hunt/_pbot6_side_mechanism_2026_08_13.py`). Target: `/opt/tvrust`, new
sleeve family beside the ladder (shares mirrors/racer/summary infra; different lifecycle).

---

## 1. The measured mechanism being copied (and the one improvement)

PBot-6, 44 days, cash-truth: +$158,283 net, ROI 13.1%, $205,960 lifetime, ~99% maker.

**It does not pick winners.** Tested and rejected: BTC 1–15m momentum alignment (agree
50.7–55.9%; WR aligned 63.3% ≈ WR anti 62.0%), drift (base P(Up)=49.0%, WR symmetric
Up/Down 53.3/54.7), prev-window momentum (WR following 53.9% ≈ fading 55.0%). What
remains, measured directly:

| its fills | shares | vwap | share-wtd WR | **EV/share** | ROI |
|---|---:|---:|---:|---:|---:|
| **pre-open** (97% in final 5 min) | 2,137,734 | 0.4690 | 52.36% | **+5.46¢** | **+11.6%** |
| post-open leftovers | 380,818 | 0.5497 | 53.89% | **−1.08¢** | −2.0% |

The pre-open market price is approximately CALIBRATED (price ≈ win probability within
±2–5pp at every price bucket). The edge is purely: **rest maker bids on BOTH tokens of
the not-yet-open window and get filled ~5¢ below the prevailing pre-open price by
impatient sellers crossing a thin book.** WR 52% at entry 0.469 is what calibration
delivers; no directional signal exists or is needed. Uniform across btc/eth and 5m/15m
(per-tf ROI 13.2% / 12.6%).

**Our improvement over the original:** its post-open tail is measurably NEGATIVE. Ours
will cancel all unfilled pre-open quotes AT open (`T−2s`), never carrying them into the
strike-live regime. We copy the +11.6% leg and delete the −2.0% leg.

Supporting infra facts (latency audit 2026-08-13): venue builds full books 28–83+ min
pre-open (~145k sh resting); queue is FIFO from placement; our `placement_offset_s=−3600`
already rests orders at market creation. Flow to collect arrives in the final 5 min.

---

## 2. The arm

`poly_v6_preopen_{btc,eth}_{5m,15m}` — start with **`btc_5m` + `btc_15m`** (one coin,
both tfs; eth after first verdict). PAPER submit. Own isolated mirrors per market chain,
same racer/data-quality stack as the ladder.

### Lifecycle per window

```
PHASE A [market_create .. T_open−2s]  (the ONLY quoting phase)
  - place GTC BUY on BOTH tokens at price = min(best_bid, BAND_HI) rounded to tick,
    never above BAND_HI, never below BAND_LO   (defaults 0.49 / 0.30)
  - clip = max(5 sh, $CLIP_USD/price, $1.00/price·(1+1e-9))  (venue floors, house rule)
  - on fill: refill same side until SIDE_CAP_USD; both sides quoted INDEPENDENTLY
    (both-side fills = a free pair at ≈0.94 — welcome, not required; NO pvs gate)
  - requote: follow best_bid down freely; follow UP only while ≤ BAND_HI
    (deadband REQUOTE_TICKS=1 to keep queue position — queue is the moat)
PHASE B [T_open−2s]
  - CANCEL all unfilled quotes (batch DELETE, 1 RTT). No exceptions. No post-open quoting.
PHASE C [T_open .. settle]
  - hold everything to chainlink settlement; redeem. NO sells, NO recycle, NO backstop.
    (PBot-6: zero sells in 121,694 fills; its holding EV is the strategy.)
```

### Env (defaults FROZEN)

```
TV_V6_PREOPEN_ENABLED        false
TV_V6_BAND_HI                0.49     # see REV A note below
TV_V6_BAND_LO                0.30     # below this the token is a lotto ticket; its <0.30 flow is negligible
TV_V6_CLIP_USD               3.0
TV_V6_SIDE_CAP_USD           15.0     # per window per side (paper); PBot-6 median $29/window total
TV_V6_DAY_CAP_USD            600.0
TV_V6_CANCEL_LEAD_S          2
TV_V6_REQUOTE_DEADBAND_TICKS 2        # REV A: 1 tick = the minimum move = no deadband at all
```

**REV A note on `BAND_HI = 0.49`.** The original justification ("PBot-6 realized vwap
0.469") was wrong — 0.469 is a MEAN, not a boundary, and PBot-6's pre-open fills in
the 0.50–0.54 bucket are also profitable (+4.6¢/share on 417k sh). 0.49 is kept
anyway, for a reason the draft failed to state: with no pair gate in this sleeve,
`BAND_HI = 0.49` bounds the worst-case two-sided quote sum at **0.98 by construction**
— the only structural loss-cap the design has. Extending to 0.53 (worth ≈ +$19k/44d at
PBot-6's scale) requires an explicit cross-side quote-sum guard (`bid_up + bid_dn ≤
0.99`) and is a candidate **v6.1 spec with its own pre-registration** — not a tuning
of this one.

### Telemetry (verdict inputs — into `ladder_summary`-style events, kind `v6_summary`)

Per window: `preopen_fill_sh/usd/vwap` per side, `fills_by_minute_to_open` (histogram
−10m..0), `cancelled_at_open_sh`, `winner`, `settle_pnl`, `implied_pair_sh`
(min(up,dn) filled), `queue_pos_estimate` at T−5m (from depth_at_price when placed).
Plus per fill: `v6_fill {side, px, sh, s_to_open, best_bid_at_fill, book_age_ms}`.

---

## 3. Pre-registration (FROZEN)

Verdict at **n ≥ 2,000 windows with ≥1 pre-open fill** OR 21 days, whichever first;
btc_5m and btc_15m judged separately:

- **H1 (the edge): share-weighted `(win_rate − fill_vwap)` ≥ +2.0¢/share on pre-open
  fills, AND the 95% CI clustered BY WINDOW excludes 0.** (REV A: clustering is
  mandatory — all fills in a window share one winner, so the unit of inference is the
  window, not the fill. Power note: window-level sd ≈ 0.5 → SE at n=2,000 ≈ 1.1¢; a
  true +5.46¢ edge like PBot-6's reads at z≈5, a true +2¢ is borderline — that is
  accepted: a borderline read extends the run, it does not loosen the bar.)
- **H2 (fill capacity): ≥ 300 filled sh/week per tf** — measured under the UNCAPPED
  pre-open queue model (impl §2.2b; the 5-level queue truncation would false-pass
  this). Below the bar we are queue-starved and the finding is "no seat at this table
  without earlier placement or better pricing" — a finding, not a tuning invitation.
- **H3 (regime sanity): the signed edge `(WR − vwap)` is positive in BOTH halves of
  the sample** (first vs second half by time) — guards against one vol-regime carrying
  the verdict.

Pass → live-candidate discussion (§5 gates). Fail H1 → kill. Fail H2 only → keep paper,
write a queue-position spec (earlier placement / tick-undercut), new pre-registration.
**No tuning of BAND_HI/LO, caps, or cancel lead mid-flight.**

## 4. Sim-honesty notes (why this paper number is trustable)

- Pre-open fills are ordinary maker fills against the print tape — same honest
  queue-consume model as the post-epoch ladder sim (no `tp<p` generosity), and the
  pre-open book is SLOW (98ms+ book ages irrelevant; flow is sparse prints) — the regime
  where the sim's remaining defects (D3/D4 queue-reset) bite least: we place once and
  rarely requote by design (deadband).
- The verdict metric H1 (WR − vwap) is *internally* consistent even if absolute fill
  volume is sim-optimistic; H2 carries the volume risk explicitly.

## 5. Live-port gates (later, not part of this spec's verdict)

1. Standing blockers resolved: breaker counts redemptions; capital ≥ $300 (hold-to-settle
   across ≥2 concurrent windows × 2 tfs + redemption float ~47s).
2. Live fills vs paper twin capture ratio ≥ 50% over ≥200 fills (queue reality check).
3. The §6-invariants from the v5_tc spec apply (live reads live, balance pre-check,
   kill/breaker stack).
4. Rebate accounting: at PBot-6's scale rebates were 23% of lifetime profit — model the
   real tier schedule before sizing beyond $1k/day notional.

## 6. Explicit non-goals

- No directional signal, no momentum gate, no side selection — the decode proved none
  exists in the original. Any future "add a signal" idea is a NEW spec.
- No selling, no recycle, no backstop in this sleeve — hold-to-settle IS the design.
- Does not touch the ladder arms (v3/v5 line) or their pre-registrations. The ladder's
  own pre-open placement (−3600s, for in-window queue priority) is unchanged; v6 is a
  separate sleeve with separate caps — if both fill pre-open, they are separate books.
- eth + 15m-first variants only after the btc verdicts.

## 7. Risks named

- **Queue competition with PBot-6 itself** (and siblings): we join the same FIFO queues
  later in life than an incumbent. H2 exists precisely to measure whether there is room.
- Pre-open flow could be one large uninformed seller who leaves; edge decays → H3
  half-split catches regime dependence.
- The 22 recent windows excluded from its decode (unredeemed) can't hide a tail: its
  redemption cadence is ~50s and the sample is 14,904 windows.
