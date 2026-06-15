"""Ground-truth check: at Ireland's actual scalp eval slots, what fraction of
the TRUE binance 5s return (px@slot+5 / px@slot - 1)*1e4 lands in the gate's
[3,12] bps band? If high but Ireland logged 0% gate-pass -> Ireland's 1s data
path is broken (store stale / feed None), NOT low base rate.

Reads _ireland_scalp_slots.txt (slot_start seconds). Fetches BTC 1s klines from
Binance REST covering the window. Computes at-or-before close_at semantics.
"""
import time, requests, bisect
from pathlib import Path

HERE = Path(__file__).parent
slots = sorted({int(x) for x in HERE.joinpath("_ireland_scalp_slots.txt").read_text().split() if x.strip().isdigit()})
print(f"slots: {len(slots)}  range {slots[0]}..{slots[-1]}  span_h={(slots[-1]-slots[0])/3600:.1f}")

lo = slots[0] - 5
hi = slots[-1] + 10
# fetch 1s klines [lo,hi] in 1000-bar pages
url = "https://api.binance.com/api/v3/klines"
ts = {}  # open_sec -> close_price
cur = lo
pages = 0
while cur <= hi:
    r = requests.get(url, params={"symbol": "BTCUSDT", "interval": "1s",
                                  "startTime": cur*1000, "endTime": hi*1000, "limit": 1000}, timeout=20)
    if r.status_code != 200:
        print("ERR", r.status_code, r.text[:120]); break
    rows = r.json()
    if not rows:
        break
    for k in rows:
        ts[int(k[0])//1000] = float(k[4])  # open_sec -> close
    pages += 1
    last = int(rows[-1][0])//1000
    if last <= cur:
        break
    cur = last + 1
    time.sleep(0.15)

secs = sorted(ts.keys())
print(f"fetched {len(secs)} 1s bars over {pages} pages  cov {secs[0]}..{secs[-1]}")

def close_at(t):
    # at-or-before t
    i = bisect.bisect_right(secs, t) - 1
    return ts[secs[i]] if i >= 0 else None

inband = 0; n = 0; absbps = []; missing = 0
for s in slots:
    po = close_at(s)
    pf = close_at(s + 5)
    if not po or not pf:
        missing += 1; continue
    bps = (pf/po - 1.0) * 1e4
    n += 1
    absbps.append(abs(bps))
    if 3.0 <= abs(bps) <= 12.0:
        inband += 1

absbps.sort()
med = absbps[len(absbps)//2] if absbps else 0
print(f"\nslots_evaluated={n}  missing_price={missing}")
print(f"|bps| median={med:.2f}")
print(f"IN-BAND [3,12]: {inband}/{n} = {inband/n*100:.1f}%   (Ireland logged 0% gate-pass)")
print(f"|bps|<3 (too small): {sum(1 for b in absbps if b<3)/n*100:.0f}%   >12 (too big): {sum(1 for b in absbps if b>12)/n*100:.0f}%")
