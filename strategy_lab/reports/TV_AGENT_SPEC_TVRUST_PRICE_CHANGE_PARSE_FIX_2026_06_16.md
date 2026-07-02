# TV AGENT SPEC — fix TVRUST `price_change` WS parse (execution-critical, Rust only)
**2026-06-16 · TVRUST (Rust) ONLY · do first, before any new strategy work.**

> **Why this is #1:** every TVRUST Polymarket strategy quotes off the live `BookState`. That book is only
> delta-fresh if `price_change` events are parsed and applied. They currently are **not** (wrong key + wrong
> asset_id shape), so the live book likely updates only on ~1 Hz full `book` snapshots and is **stale between
> them** — silently degrading sniper, scalp, the ladder, and the new V2 sleeve. This fix is independent of
> storedata (that's a separate system; it just happens to need the identical fix, already done there).

## 1. The bug
`crates/tv-feeds/src/poly_book.rs` parses the WS `price_change` event with:
- key **`changes`** (`evt.get("changes")` — `:117` and `:251`), and
- a **message-level** `asset_id` (`:109` / `:143`, and the second decoder `:245`/`:285`).

The live Polymarket CLOB WS frame (verified against the feed by the storedata agent; the format changed from
the old `changes[]`) is:
- key **`price_changes`** (array), and
- a **per-change `asset_id`** — a single frame's `price_changes[]` can span multiple tokens (Up + Down, and
  other markets).

Result: `evt.get("changes")` returns `None` on the live frame → **0 `BookEvent::PriceChange` produced** →
`BookState.apply_inner` (`:410`, which is correct) never runs for deltas → the book only mutates on full
`book` snapshots. (`apply_inner`/the `BookEvent`/`PriceChange` types are fine — the bug is purely in the parse.)

## 2. The fix (both decoders)
There are **two** parse sites — the `Vec<BookEvent>` decoder (`~:85-146`) and the keyed/dedup decoder
(`~:220-285`). Fix **both** (grep `"price_change"` to confirm you got them all). In each `Some("price_change")`
arm:
1. Read the array from **`price_changes` first, fall back to `changes`** (so it survives a venue flip-back).
2. Take `asset_id` **per change** (`ch.get("asset_id")`), falling back to the event-level `asset_id` if a
   change omits it.
3. **Group changes by `asset_id`** and emit **one `BookEvent::PriceChange { asset_id, changes }` per asset_id**
   — this keeps `apply_inner` (which routes by event-level `asset_id`) unchanged.

Sketch (decoder 1; apply the same to decoder 2, building one keyed tuple per asset_id):
```rust
Some("price_change") => {
    let evt_asset = evt.get("asset_id").map(value_to_string);            // fallback only
    let arr = evt.get("price_changes")                                   // live key first
        .or_else(|| evt.get("changes"))                                  // legacy fallback
        .and_then(|c| c.as_array());
    let mut by_asset: std::collections::HashMap<String, Vec<PriceChange>> = Default::default();
    if let Some(arr) = arr {
        for ch in arr {
            if !ch.is_object() { continue; }
            let aid = ch.get("asset_id").map(value_to_string)
                        .or_else(|| evt_asset.clone()).unwrap_or_default();
            if aid.is_empty() { continue; }
            let price = match decimal_field(ch, "price") { Some(p) => p, None => continue };
            let size  = match decimal_field(ch, "size")  { Some(s) => s, None => continue };
            let side = match ch.get("side").map(value_to_string).unwrap_or_default().to_uppercase().as_str() {
                "BUY" => ChangeSide::Bid,      // buy-side change = a bid level
                "SELL" => ChangeSide::Ask,     // sell-side change = an ask level
                _ => continue,
            };
            by_asset.entry(aid).or_default().push(PriceChange { price, size, side });
        }
    }
    for (asset_id, changes) in by_asset {
        out.push(BookEvent::PriceChange { asset_id, changes });
    }
}
```
Keep the existing `BUY→Bid / SELL→Ask` mapping (verify the live `side` casing — `.to_uppercase()` covers it).
Do **not** change `BookEvent`, `PriceChange`, or `apply_inner` — only the parse.

## 3. Verify against the live frame (don't trust the spec — probe it, like storedata did)
- Log one raw `price_change` JSON from the live WS; confirm the key is `price_changes` and each element has its
  own `asset_id`. (If the venue ever sends `changes`, the fallback covers it.)
- After the fix: confirm `BookEvent::PriceChange` is produced at a high rate (many/sec on an active btc token),
  and that `BookState` best-bid/best-ask now **change between full `book` snapshots** (not frozen at ~1 Hz).

## 4. Parity / tests
- Any golden-vector fixture for `poly_book` that encodes the old `changes`/message-asset_id shape is now
  unrealistic — update it (or add one) to the live `price_changes` + per-change-`asset_id` shape, including a
  **multi-asset frame** (Up + Down changes in one event) to lock the grouping behavior.
- Add a unit test: a `price_changes` frame with two asset_ids → two `BookEvent::PriceChange`, each applied to
  its own token's book.

## 5. Acceptance
- Live `price_change` events parsed (>0/sec on active tokens) and applied; book is delta-fresh between
  snapshots. Parity green. No change to `apply_inner` / downstream consumers. Default behavior otherwise
  identical (the 5 live sleeves still fire; they just quote on a fresher book).

## 6. Scope
Rust only (`crates/tv-feeds/src/poly_book.rs`). No Python Tradingvenue change. No storedata interaction
(storedata fixed the same bug independently in its own collector). This gates correct live execution for
**all** TVRUST poly strategies — land it before the V2 sleeve / ladder work.
