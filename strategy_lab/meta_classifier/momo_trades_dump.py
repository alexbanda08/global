"""Dump every momo trade with all available fields, joined: resolution + fill signal."""
import csv
import json
import os
import re
from datetime import datetime, timezone
from decimal import Decimal

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
RES_CSV = os.path.join(ROOT, "data/v4/shadow_trades_2026_05_06/momo_resolutions.csv")
SIG_CSV = os.path.join(ROOT, "data/v4/shadow_trades_2026_05_06/momo_signal_fills.csv")
OUT_CSV = os.path.join(ROOT, "data/v4/shadow_trades_2026_05_06/momo_trades_full.csv")

SLEEVE_RE = re.compile(r"poly_updown_(btc|eth|sol)_(5m|15m)_momo_(HOLD|HEDGE|SELL)$")


def parse_at(s):
    s = s.strip()
    if re.search(r"[+-]\d{2}$", s):
        s = s + ":00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def f(x, default=None):
    if x is None or x == "":
        return default
    try:
        return float(Decimal(str(x)))
    except Exception:
        return default


# Index fill signals by event_id (since resolution.fill_event_id points to it)
fills = {}
with open(SIG_CSV, "r", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        fills[r["event_id"]] = json.loads(r["data"])

trades = []
with open(RES_CSV, "r", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        d = json.loads(r["data"])
        m = SLEEVE_RE.match(r["sleeve_id"])
        if not m:
            continue
        asset = m.group(1).upper()
        tf = m.group(2)
        ex = m.group(3)
        at_utc = parse_at(r["at"])
        fill = fills.get(d.get("fill_event_id"), {}) if d.get("fill_event_id") else {}
        trades.append({
            "at_utc": at_utc,
            "sleeve_id": r["sleeve_id"],
            "asset": asset, "tf": tf, "exit": ex,
            "signal": d.get("signal"),
            "outcome": d.get("outcome"),
            "won": bool(d.get("won")),
            "mode": d.get("mode"),
            "entry_price": f(d.get("entry_price")),
            "entry_qty": f(d.get("entry_qty")),
            "pnl_usd": f(d.get("pnl_usd"), 0.0),
            "hedged": bool(d.get("hedged")),
            "hedge_price": f(d.get("hedge_price")),
            "partial_bid_exit": bool(d.get("partial_bid_exit", False)),
            "partial_exit_price": f(d.get("partial_exit_price")),
            "partial_exit_qty": f(d.get("partial_exit_qty")),
            "realized_via_bid_pnl": f(d.get("realized_via_bid_pnl")),
            "chainlink_pnl_on_held": f(d.get("chainlink_pnl_on_held")),
            "held_qty_to_chainlink": f(d.get("held_qty_to_chainlink")),
            "settlement_price": f(d.get("settlement_price")),
            "strike_price": f(d.get("strike_price")),
            "price_source": d.get("price_source"),
            "condition_id": d.get("condition_id"),
            "fill_event_id": d.get("fill_event_id"),
            # joined from fill signal:
            "limit_px": f(fill.get("limit_px")),
            "fill_price": f(fill.get("fill_price")),
            "fill_qty": f(fill.get("fill_qty")),
            "qty_intended": f(fill.get("qty_intended")),
            "fill_status": fill.get("fill_status"),
            "entry_phase": fill.get("entry_phase"),
            "ret_2m_at_signal": fill.get("ret_2m_at_signal"),
            "abs_ret_2m_threshold": fill.get("abs_ret_2m_threshold"),
            "bar_ctx_age_ms": fill.get("bar_ctx_age_ms"),
        })

trades.sort(key=lambda t: t["at_utc"])

# Write detailed CSV
with open(OUT_CSV, "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(trades[0].keys()))
    w.writeheader()
    for t in trades:
        row = {**t}
        row["at_utc"] = t["at_utc"].isoformat()
        w.writerow(row)

# Print compact table to stdout
def fmt_ret(x):
    if x is None:
        return "—"
    return f"{x*1e4:+6.1f}bp"

cum_pnl = 0.0
wins = 0
print(f"{'#':>3} {'time UTC':<19} {'cell':<10} {'ex':<5} {'sig':<4} {'out':<4} {'W':<2} "
      f"{'ent_px':>7} {'ent_qty':>9} {'pnl':>8} {'cum':>9} {'WR':>6} "
      f"{'ret_2m':>8} {'thresh':>8} {'ctx_ms':>6} "
      f"{'fill_px':>7} {'fill_qty':>9} {'fill_st':<8} {'hedged':<6} {'pbe':<3} "
      f"{'rev_pnl':>8} {'ck_pnl':>8} {'sett':>7}")
print("-" * 215)

for i, t in enumerate(trades, 1):
    cum_pnl += t["pnl_usd"]
    if t["won"]:
        wins += 1
    wr = wins / i
    cell = f"{t['asset']}_{t['tf']}"
    print(
        f"{i:>3} "
        f"{t['at_utc'].strftime('%m-%d %H:%M:%S'):<19} "
        f"{cell:<10} {t['exit']:<5} {t['signal']:<4} {t['outcome']:<4} "
        f"{'Y' if t['won'] else 'N':<2} "
        f"{(t['entry_price'] or 0):>7.4f} "
        f"{(t['entry_qty'] or 0):>9.4f} "
        f"{t['pnl_usd']:>+8.2f} "
        f"{cum_pnl:>+9.2f} "
        f"{wr:>6.1%} "
        f"{fmt_ret(t['ret_2m_at_signal']):>8} "
        f"{fmt_ret(t['abs_ret_2m_threshold']):>8} "
        f"{(t['bar_ctx_age_ms'] if t['bar_ctx_age_ms'] is not None else '—'):>6} "
        f"{(t['fill_price'] or 0):>7.4f} "
        f"{(t['fill_qty'] or 0):>9.4f} "
        f"{(t['fill_status'] or '—'):<8} "
        f"{('Y' if t['hedged'] else 'N'):<6} "
        f"{('Y' if t['partial_bid_exit'] else 'N'):<3} "
        f"{(t['realized_via_bid_pnl'] if t['realized_via_bid_pnl'] is not None else 0):>+8.2f} "
        f"{(t['chainlink_pnl_on_held'] if t['chainlink_pnl_on_held'] is not None else 0):>+8.2f} "
        f"{(t['settlement_price'] if t['settlement_price'] is not None else 0):>7.2f}"
    )

print()
print(f"=== Totals: {len(trades)} trades, {wins} wins ({wins/len(trades):.1%} WR), cum PnL ${cum_pnl:+.2f} ===")
print(f"\nFull CSV: {OUT_CSV}")
print("\nCol legend: ent_px = entry book-walk vwap; ret_2m = log return @ t+120s; thresh = q90 daily threshold;")
print("            ctx_ms = bar_ctx_age_ms at fill; pbe = partial_bid_exit; rev_pnl = realized_via_bid_pnl;")
print("            ck_pnl = chainlink_pnl_on_held; sett = settlement_price (asset $)")
