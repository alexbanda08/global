"""Harvest cyclops_signals public Telegram channel via the t.me/s/ web preview.

Public channels expose recent messages at https://t.me/s/<channel> (no auth).
Pagination: ?before=<msg_id> returns older messages. We walk back N pages,
parse each tgme_widget_message block, extract the monospace signal box fields.

Run on VPS3 (network + clean python3): ssh vps3 'python3 /tmp/harvest_cyclops.py'
Output: /tmp/cyclops_signals.csv
"""
from __future__ import annotations
import re, time, html, json, urllib.request, csv

CHAN = "cyclops_signals"
UA = {"User-Agent": "Mozilla/5.0 (decode-research)"}

def fetch(before=None):
    url = f"https://t.me/s/{CHAN}"
    if before:
        url += f"?before={before}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")

# Each message: <div class="tgme_widget_message ..." data-post="cyclops_signals/8719">
#   text in <div class="tgme_widget_message_text ...">...</div>
#   time in <time datetime="2026-05-30T19:00:..">
MSG_RE = re.compile(r'data-post="cyclops_signals/(\d+)"')
TEXT_RE = re.compile(r'js-message_text[^>]*>(.*?)</div>', re.S)
TIME_RE = re.compile(r'<time datetime="([^"]+)"')

def strip_tags(s):
    s = re.sub(r'<br\s*/?>', '\n', s)
    s = re.sub(r'<[^>]+>', '', s)
    return html.unescape(s)

def parse_block(block):
    mid = MSG_RE.search(block)
    txt = TEXT_RE.search(block)
    tm = TIME_RE.search(block)
    if not mid or not txt:
        return None
    raw = strip_tags(txt.group(1))
    rec = {"msg_id": int(mid.group(1)), "post_ts": tm.group(1) if tm else "", "raw": raw.replace("\n", " | ")}
    # type
    if "WIN" in raw and "BUY" in raw:
        rec["type"] = "WIN"
    elif "LOSS" in raw or "❌" in raw:
        rec["type"] = "LOSS"
    elif "WATCHING" in raw:
        rec["type"] = "WATCHING"
    elif "BUY" in raw:
        rec["type"] = "SIGNAL"
    else:
        rec["type"] = "OTHER"
    # direction
    if "BUY UP" in raw or "BUY UP" in raw:
        rec["direction"] = "UP"
    elif "BUY DOWN" in raw:
        rec["direction"] = "DOWN"
    else:
        rec["direction"] = ""
    # slot window header "May 30 3:00-3:05 PM ET"
    m = re.search(r'([A-Z][a-z]{2} \d{1,2} \d{1,2}:\d{2}-\d{1,2}:\d{2} [AP]M ET)', raw)
    rec["slot_et"] = m.group(1) if m else ""
    # btc price + beat(strike)
    m = re.search(r'BTC \$([\d,]+)', raw); rec["btc_price"] = m.group(1).replace(",","") if m else ""
    m = re.search(r'Beat \$([\d,]+)', raw); rec["beat_strike"] = m.group(1).replace(",","") if m else ""
    # arrow move "$73,915 → $73,934 (+18)"
    m = re.search(r'\$([\d,]+) .?→.? \$([\d,]+) \(([+\-]?\d+)\)', raw)
    if m:
        rec["mv_from"], rec["mv_to"], rec["mv_delta"] = m.group(1).replace(",",""), m.group(2).replace(",",""), m.group(3)
    # entry cents + multiplier
    m = re.search(r'Entry (\d+)¢', raw); rec["entry_cents"] = m.group(1) if m else ""
    m = re.search(r'\(([\d.]+)x\)', raw); rec["mult"] = m.group(1) if m else ""
    # PTB indicator (arrows/squares)
    m = re.search(r'PTB\s*([^\|]+)', raw); rec["ptb"] = (m.group(1).strip()[:12] if m else "")
    rec["ptb_up"] = raw.count("🟩"); rec["ptb_dn"] = raw.count("🟥")
    rec["btc_dir_arrow"] = ("UP" if "BTC ▲" in raw else ("DOWN" if "BTC ▼" in raw else ""))
    # confidence dots + label
    m = re.search(r'Confidence\s*([●○]+)\s*(\w+)', raw)
    if m:
        rec["conf_dots"] = m.group(1).count("●"); rec["conf_label"] = m.group(2)
    # record
    m = re.search(r'Record (\d+)W (\d+)L \((\d+)%\)', raw)
    if m:
        rec["rec_w"], rec["rec_l"], rec["rec_wr"] = m.group(1), m.group(2), m.group(3)
    m = re.search(r'(\d+)W streak', raw); rec["streak"] = m.group(1) if m else ""
    return rec

def main(pages=80, sleep=0.4):
    seen = {}
    before = None
    for p in range(pages):
        try:
            h = fetch(before)
        except Exception as e:
            print(f"page {p} fetch err {e}"); break
        blocks = re.split(r'(?=data-post="cyclops_signals/\d+")', h)
        ids_this = []
        for b in blocks:
            r = parse_block(b)
            if r:
                seen[r["msg_id"]] = r
                ids_this.append(r["msg_id"])
        if not ids_this:
            print(f"page {p}: no msgs, stop"); break
        oldest = min(ids_this)
        print(f"page {p}: {len(ids_this)} msgs, oldest={oldest}, total={len(seen)}")
        if before is not None and oldest >= before:
            print("no older msgs, stop"); break
        before = oldest
        time.sleep(sleep)
    rows = sorted(seen.values(), key=lambda r: r["msg_id"])
    cols = ["msg_id","post_ts","slot_et","type","direction","btc_price","beat_strike",
            "mv_from","mv_to","mv_delta","entry_cents","mult","ptb","ptb_up","ptb_dn",
            "btc_dir_arrow","conf_dots","conf_label","rec_w","rec_l","rec_wr","streak","raw"]
    out = "/tmp/cyclops_signals.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({c: r.get(c,"") for c in cols})
    print(f"\nWROTE {len(rows)} msgs -> {out}")
    # quick taxonomy
    from collections import Counter
    print("types:", dict(Counter(r["type"] for r in rows)))
    print("directions:", dict(Counter(r["direction"] for r in rows if r["direction"])))
    sigs = [r for r in rows if r["type"]=="SIGNAL"]
    print(f"SIGNAL msgs: {len(sigs)}")
    if rows:
        print("first slot:", rows[0].get("slot_et"), "last slot:", rows[-1].get("slot_et"))

if __name__ == "__main__":
    main()
