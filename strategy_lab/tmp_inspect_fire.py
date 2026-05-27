"""Inspect a specific sleeve's fires in V5 JSONL."""
import json

sleeve_target = "poly_sniper_v5_btc_15m_ema800_ribslp_hawkes_off840_v6"
path = "/var/log/tradingvenue/sniper_v5/2026-05-27.jsonl"

matches = []
with open(path) as f:
    for line in f:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("sleeve_id") == sleeve_target:
            matches.append(r)

print(f"Total events for {sleeve_target}: {len(matches)}")
print()

by_event = {}
for r in matches:
    et = r.get("event_type", "?")
    by_event[et] = by_event.get(et, 0) + 1
print(f"Events by type: {by_event}")
print()

placed = [r for r in matches if r.get("event_type") == "sleeve_fire_placed"]
resolved = [r for r in matches if r.get("event_type") == "sleeve_fire_resolved"]

print(f"PLACED count: {len(placed)}")
for r in placed:
    slug = r.get("slug")
    direction = r.get("direction")
    fire_us = r.get("fire_us")
    fill_vwap = r.get("fill_vwap")
    fill_shares = r.get("fill_shares")
    placed_size = r.get("placed_size_usd")
    intended = r.get("intended_size_usd")
    bk = r.get("l25_book_snapshot") or {}
    up = bk.get("up_vwap")
    dn = bk.get("dn_vwap")
    print(f"  slug={slug} dir={direction} fire_us={fire_us}")
    print(f"    fill_vwap={fill_vwap} fill_shares={fill_shares}")
    print(f"    placed_size_usd={placed_size} intended_size_usd={intended}")
    print(f"    book: up_vwap={up} dn_vwap={dn}")

print()
print(f"RESOLVED count: {len(resolved)}")
for r in resolved:
    slug = r.get("slug")
    direction = r.get("direction")
    outcome = r.get("outcome")
    pnl = r.get("pnl_usd")
    fill_vwap = r.get("fill_vwap")
    fill_shares = r.get("fill_shares")
    placed_size = r.get("placed_size_usd")
    intended = r.get("intended_size_usd")
    print(f"  slug={slug} dir={direction}")
    print(f"    outcome={outcome}  pnl_usd={pnl}")
    print(f"    fill_vwap={fill_vwap}  fill_shares={fill_shares}")
    print(f"    placed_size_usd={placed_size}  intended_size_usd={intended}")
    # Manual PnL recompute
    if fill_vwap is not None and fill_shares is not None:
        if outcome and outcome.lower() == direction.lower():
            won = True
            # gross = shares*1 - usd_in (legacy 2pct on profit)
            usd_in = fill_vwap * fill_shares
            gross = fill_shares * 1.0 - usd_in
            pnl_check_legacy = gross - (gross * 0.02 if gross > 0 else 0)
            print(f"    [manual recompute LEGACY 2pct-on-profit] won=True gross={gross:.4f} pnl_calc={pnl_check_legacy:.4f}")
        else:
            won = False
            usd_in = fill_vwap * fill_shares
            pnl_check_legacy = -usd_in
            print(f"    [manual recompute LEGACY] won=False usd_in={usd_in:.4f} pnl_calc={-usd_in:.4f}")
        # ROI sanity
        if placed_size and placed_size > 0:
            roi_pct = (pnl / placed_size) * 100 if pnl is not None else None
            print(f"    ROI vs placed_size: {roi_pct}")
        if intended and intended > 0:
            roi_intended = (pnl / intended) * 100 if pnl is not None else None
            print(f"    ROI vs intended_size: {roi_intended}")
