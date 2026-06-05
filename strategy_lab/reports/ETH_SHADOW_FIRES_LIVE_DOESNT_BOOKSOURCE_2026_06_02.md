# Why shadow fires slugs the live doesn't — the spread gate reads DIFFERENT books (2026-06-02)

> 🚨 **CORRECTION (verified).** An earlier draft of this file said "VPS3 shadow reads the storedata-DB book."
> **That was WRONG.** The shadow event explicitly shows `book_source=ws_mirror` and `dn_book_source=ws_mirror`
> — VPS3 shadow uses TV's own WS BookMirror, same source TYPE as live. `TV_POLY_PAPER_DB_FALLBACK=true` is only
> a fallback when the mirror is empty; it was NOT used here.
>
> **The real divergence:** both hosts use `ws_mirror`, but the two INDEPENDENT mirror connections showed
> different book snapshots at the same fire instant — VPS3 shadow: DOWN bid 0.19 / ask 0.21 = spread **0.02**
> (passed); Ireland live: spread **0.05** (rejected). Prime suspect = the shadow/paper path's
> **`TV_POLY_PAPER_BOOK_CACHE_TTL=1`** (book cached up to 1s) serving a slightly STALE, tighter snapshot vs the
> live's fresher read. On a thin, fast deep-underdog token (0.21) at the spread gate's exact 0.02 boundary, the
> 1s staleness flips the decision. So it is a **snapshot-freshness divergence between two ws_mirror reads**,
> NOT a wrong-book-source bug. Read the rest of this file through this correction.
>
> **Fix for TV agent:** evaluate the shadow spread gate against a FRESH (uncached) mirror snapshot — i.e. set
> the paper book cache TTL to 0 for the spread-gate read, or read the live mirror snapshot directly — so the
> shadow's spread matches what the live engine sees. Then shadow over-fires of thin-book slugs stop.


**Sleeve:** `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8` (VPS3 shadow vs Ireland `_LIVE`).
**Operator observation:** "shadow fired, live didn't" on a specific slot. CONFIRMED + root-caused.

## The smoking-gun slug: `eth-updown-5m-1780442400`
| host | book source | spread read (DOWN side) | event |
|---|---|---|---|
| **Ireland (live)** | live WS BookMirror (real) | `spread_bidask_too_wide_0.0500_>_0.0200` | both sides SKIPPED → no fire |
| **VPS3 (shadow)** | storedata-DB / paper-REST | `≤ 0.0200` (UP rejected at 0.0200>0.0200; DOWN passed) | **PLACED DOWN @ 0.21** |

Same gate threshold (0.02). DIFFERENT books → opposite decision. The real Polymarket book had a **5¢**
spread on the DOWN @ 0.21 (deep-underdog, thin) token; the shadow's book read showed **≤2¢**.

## Mechanism (reconciles the whole thread)
- **Favored-side, tight-book slugs** (the 11 matched earlier): both book reads agree → identical fires,
  identical direction, fill within 1–2¢. ✓ (see `ETH_LIVE_VS_SHADOW_SAME_TRADES_2026_06_02.md`)
- **Marginal thin-book slugs** (deep underdog, wide REAL spread): the shadow's book source is tighter/staler
  than the live WS book → spread gate **passes on shadow, rejects on live** → shadow fires, live correctly skips.
- ⇒ **The shadow fire set is a SUPERSET of the live fire set.** Shadow places extra marginal slugs (often
  deep-underdog losers like DOWN @ 0.21) that the live engine rejects.

## Is it a bug? YES — a book-source parity bug (for the TV agent)
The shadow (VPS3) and live (Ireland) evaluate the spread gate against **different order books**:
- **VPS3 shadow:** storedata-DB snapshot / paper-REST (`TV_POLY_PAPER_DB_FALLBACK=true`) — staler and/or
  tighter on thin tokens.
- **Ireland live:** real-time WS BookMirror — the true, wider book.
Consequence: the shadow's WR/PnL is NOT representative of live (it fires slugs that can't be filled at the
modeled price), AND the operator sees "shadow fired, live didn't."

### Fix
Make the shadow's spread-gate book source identical to the live path's WS BookMirror (or compute the
spread metric from the SAME snapshot the live engine uses). After this, shadow fires == live fires, and the
shadow's inflated WR (from the extra thin-book slugs) collapses to the true live WR.

### Why it matters
This is the concrete, evidenced version of the long-suspected "shadow is optimistic vs live" gap. It is NOT
small-sample variance and NOT a fire-timing bug — it is a **book-read divergence at the spread gate**. It
explains both (a) the operator's "shadow fired / live didn't" and (b) why shadow backtest WR overstates live.

## Also still open (separate, cosmetic)
`fire_us` in the RESOLVED event is mislabeled to `slot_end` (placed events correctly show off=60). Fix for
clean analytics. Does not affect fires.

## Net for restart
Before trusting any shadow number for live, the TV agent should unify the book source (above). Until then,
only the LIVE wallet WR (vs de-vigged entry-implied price) is trustworthy; the shadow over-fires thin-book
underdog slugs.
