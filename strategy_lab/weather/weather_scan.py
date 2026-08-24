"""Weather temp-market scanner v1 (2026-07-28).

Read-only. Pulls all active Polymarket daily high/low temperature events, parses the
resolution station from each market description, fetches real-time observations
(METAR via aviationweather.gov for airport stations, HKO API for Hong Kong), computes
the running daily max/min, and flags deterministic mispricings (dead brackets still bid,
underpriced live tail). Appends one snapshot row per bracket to snapshots/*.csv.

Usage:  python strategy_lab/weather/weather_scan.py
Run on a 5-10 min schedule to build the research dataset (see spec §Data plan).
"""
import csv
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

GAMMA = "https://gamma-api.polymarket.com"
METAR_API = "https://aviationweather.gov/api/data/metar?ids={ids}&format=json&hours=26"
HKO_API = "https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=rhrread&lang=en"

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")

# Fixed UTC offsets (July / DST where applicable). v1 pragmatism — replace with IANA tz later.
CITY_UTC_OFFSET = {
    "nyc": -4, "chicago": -5, "atlanta": -4, "dallas": -5, "miami": -4,
    "seattle": -7, "los-angeles": -7, "toronto": -4,
    "london": 1, "paris": 2, "madrid": 2, "amsterdam": 2, "milan": 2, "munich": 2,
    "warsaw": 2, "helsinki": 3, "moscow": 3, "istanbul": 3, "ankara": 3, "tel-aviv": 3,
    "jeddah": 3, "karachi": 5, "lucknow": 5.5, "hong-kong": 8, "shanghai": 8,
    "beijing": 8, "shenzhen": 8, "guangzhou": 8, "chengdu": 8, "chongqing": 8,
    "wuhan": 8, "jinan": 8, "qingdao": 8, "zhengzhou": 8, "taipei": 8,
    "kuala-lumpur": 8, "singapore": 8, "manila": 8, "seoul": 9, "busan": 9,
    "tokyo": 9, "wellington": 12, "sao-paulo": -3, "buenos-aires": -3, "cape-town": 2,
}

SLUG_RE = re.compile(r"^(highest|lowest)-temperature-in-(.+)-on-(\w+)-(\d+)-(\d{4})$")
MONTHS = {m.lower(): i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June",
     "July", "August", "September", "October", "November", "December"])}
# ICAO from a wunderground history URL in the description, e.g. .../KLGA
ICAO_RE = re.compile(r"wunderground\.com/history/daily/[^\s)]*/([A-Z0-9]{4})")
BRACKET_RE = re.compile(r"^(\d+)(?:-(\d+))?\s*°([FC])(?:\s+or\s+(below|higher))?", re.I)


def http_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "weather-scan/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_events():
    """All active daily temperature events (paged)."""
    events, offset = [], 0
    while True:
        page = http_json(f"{GAMMA}/events?tag_slug=weather&closed=false&limit=100&offset={offset}")
        if not page:
            break
        events += [e for e in page if SLUG_RE.match(e.get("slug") or "")]
        if len(page) < 100:
            break
        offset += 100
    return events


def parse_bracket(title):
    """'70-71°F' -> (70, 71, 'F'); '69°F or below' -> (None, 69, 'F'); '88°F or higher' -> (88, None, 'F')."""
    m = BRACKET_RE.match((title or "").strip())
    if not m:
        return None
    lo, hi, unit, tail = m.group(1), m.group(2), m.group(3).upper(), (m.group(4) or "").lower()
    lo, hi = int(lo), (int(hi) if hi else None)
    if tail == "below":
        return (None, lo, unit)
    if tail == "higher":
        return (lo, None, unit)
    if hi is None:
        return (lo, lo, unit)  # single-degree bracket e.g. '25°C'
    return (lo, hi, unit)


def local_date_for(city, utc_now):
    off = CITY_UTC_OFFSET.get(city)
    if off is None:
        return None
    return (utc_now + dt.timedelta(hours=off)).date()


def metar_running_extreme(icao, city, target_date, utc_now, kind, unit, cache):
    """Running max (or min) temp for the station's local calendar day. Returns (value, n_obs) or None."""
    if icao not in cache:
        try:
            cache[icao] = http_json(METAR_API.format(ids=icao))
        except Exception as e:
            print(f"  ! METAR fetch failed {icao}: {e}", file=sys.stderr)
            cache[icao] = []
    off = CITY_UTC_OFFSET.get(city)
    temps = []
    for ob in cache[icao] or []:
        t_c = ob.get("temp")
        obs_time = ob.get("obsTime") or ob.get("reportTime")
        if t_c is None or obs_time is None:
            continue
        if isinstance(obs_time, (int, float)):
            ts = dt.datetime.fromtimestamp(obs_time, dt.timezone.utc)
        else:
            try:
                ts = dt.datetime.fromisoformat(str(obs_time).replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=dt.timezone.utc)
            except ValueError:
                continue
        if (ts + dt.timedelta(hours=off)).date() != target_date:
            continue
        # Wunderground displays whole °F (rounded from METAR °C) for US-style markets.
        temps.append(round(float(t_c) * 9 / 5 + 32) if unit == "F" else float(t_c))
    if not temps:
        return None
    return (max(temps) if kind == "highest" else min(temps), len(temps))


def hko_running_extreme(target_date, utc_now, kind, cache):
    """HKO 'Hong Kong Observatory' station current temp; running extreme accumulated across scans
    would need history — v1 returns the CURRENT reading only (floor for max / ceiling for min)."""
    if "hko" not in cache:
        try:
            cache["hko"] = http_json(HKO_API)
        except Exception as e:
            print(f"  ! HKO fetch failed: {e}", file=sys.stderr)
            cache["hko"] = {}
    d = cache["hko"]
    for rec in (d.get("temperature") or {}).get("data", []):
        if rec.get("place") == "Hong Kong Observatory":
            return (float(rec["value"]), 1)
    return None


def scan():
    utc_now = dt.datetime.now(dt.timezone.utc)
    events = fetch_events()
    print(f"{utc_now.isoformat()} — {len(events)} active daily temp events")
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"weather_snapshots_{utc_now:%Y_%m_%d}.csv")
    new_file = not os.path.exists(out_path)
    obs_cache = {}
    n_rows = n_violations = 0

    with open(out_path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["ts_utc", "event_slug", "city", "kind", "target_date", "station",
                        "run_extreme", "n_obs", "bracket", "lo", "hi", "unit",
                        "price", "best_bid", "best_ask", "dead", "flag"])
        for e in events:
            slug = e["slug"]
            sm = SLUG_RE.match(slug)
            kind, city = sm.group(1), sm.group(2)
            try:
                market_date = dt.date(int(sm.group(5)), MONTHS[sm.group(3).lower()], int(sm.group(4)))
            except (KeyError, ValueError):
                continue
            markets = e.get("markets") or []
            if not markets:
                continue
            icao_m = ICAO_RE.search(markets[0].get("description") or "")
            # The monotone-max constraint only binds once the station's local calendar
            # day IS the market's target date. Future-dated events: snapshot prices only.
            today_local = local_date_for(city, utc_now)
            target_date = market_date if market_date == today_local else None
            unit = None
            brackets = []
            for m in markets:
                b = parse_bracket(m.get("groupItemTitle"))
                if b:
                    unit = b[2]
                    brackets.append((b, m))
            if not brackets:
                continue

            ext = None
            station = "HKO" if city == "hong-kong" else (icao_m.group(1) if icao_m else "")
            if target_date is not None:  # obs constraint only binds on the market's own local day
                if city == "hong-kong":
                    ext = hko_running_extreme(target_date, utc_now, kind, obs_cache)
                elif icao_m:
                    ext = metar_running_extreme(station, city, target_date, utc_now, kind, unit, obs_cache)
            run_val, n_obs = ext if ext else (None, 0)

            live_sum = 0.0
            for (lo, hi, u), m in brackets:
                try:
                    price = float(json.loads(m.get("outcomePrices") or "[0]")[0])
                except (ValueError, IndexError):
                    price = None
                bid, ask = m.get("bestBid"), m.get("bestAsk")
                dead = flag = ""
                if run_val is not None:
                    # margin of 1 degree against rounding/precision risk near the boundary
                    if kind == "highest" and hi is not None and hi < run_val - 0.5:
                        dead = "DEAD"
                    if kind == "lowest" and lo is not None and lo > run_val + 0.5:
                        dead = "DEAD"
                    if dead and bid is not None and float(bid) >= 0.02:
                        flag = f"DEAD_BID_{bid}"
                        n_violations += 1
                    if not dead and price is not None:
                        live_sum += price
                w.writerow([utc_now.isoformat(), slug, city, kind, market_date, station,
                            run_val, n_obs, m.get("groupItemTitle"), lo, hi, u,
                            price, bid, ask, dead, flag])
                n_rows += 1
                if flag:
                    print(f"  VIOLATION {slug} [{m.get('groupItemTitle')}] run={run_val} bid={bid}")
            if run_val is not None and 0 < live_sum < 0.95:
                print(f"  TAIL_CHEAP {slug} live-bracket sum={live_sum:.3f} run={run_val}")

    print(f"wrote {n_rows} rows -> {out_path} | dead-bid violations: {n_violations}")


if __name__ == "__main__":
    scan()
