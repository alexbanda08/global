#!/usr/bin/env python3
"""ALT/BTC Relative-Strength panel generator — STANDALONE (stdlib only).

Fetches Binance SPOT klines for a liquid set of HL-tradeable perps, computes
alt/BTC relative strength vs SMA200 & EMA200 on Daily / 4H / 1H, plus an RS
momentum ranking and a daily-persistence strip. Writes a single self-contained
index.html (Plotly.js via CDN). No pandas/plotly-python; safe on bare python3.

NOTE: this is a self-contained market-data tool. It does NOT touch the trading
engine, storedata, or any of our HL strategies (V52/XSM). Public data only.
"""
import json, math, time, urllib.request, urllib.error, os, sys
from datetime import datetime, timezone

OUT_DIR = os.environ.get("RS_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "public"))
LEN = 200          # MA length
BASE = "BTC"

# label -> binance spot symbol. Liquid HL perps that exist on Binance spot.
# (HYPE excluded — not on Binance spot. Symbols auto-skip on 400.)
COINS = [
    ("ETH","ETHUSDT"),("SOL","SOLUSDT"),("BNB","BNBUSDT"),("XRP","XRPUSDT"),
    ("DOGE","DOGEUSDT"),("ADA","ADAUSDT"),("AVAX","AVAXUSDT"),("LINK","LINKUSDT"),
    ("DOT","DOTUSDT"),("LTC","LTCUSDT"),("BCH","BCHUSDT"),("TRX","TRXUSDT"),
    ("NEAR","NEARUSDT"),("APT","APTUSDT"),("SUI","SUIUSDT"),("ARB","ARBUSDT"),
    ("OP","OPUSDT"),("INJ","INJUSDT"),("TIA","TIAUSDT"),("SEI","SEIUSDT"),
    ("ATOM","ATOMUSDT"),("FIL","FILUSDT"),("RUNE","RUNEUSDT"),("AAVE","AAVEUSDT"),
    ("UNI","UNIUSDT"),("ENA","ENAUSDT"),("WLD","WLDUSDT"),("ORDI","ORDIUSDT"),
    ("LDO","LDOUSDT"),("STX","STXUSDT"),("CRV","CRVUSDT"),("JUP","JUPUSDT"),
    ("TAO","TAOUSDT"),("FET","FETUSDT"),("RENDER","RENDERUSDT"),("PYTH","PYTHUSDT"),
]
TFS = [("D","1d"), ("4H","4h"), ("1H","1h")]
LIMIT = 300        # bars per fetch (need >= LEN + persistence window)

API = "https://api.binance.com/api/v3/klines"

def fetch(symbol, interval, limit=LIMIT, retries=3):
    url = f"{API}?symbol={symbol}&interval={interval}&limit={limit}"
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"rs-panel/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                rows = json.load(r)
            # [openTime, o,h,l,c,v, closeTime, ...]
            return [(int(k[0]), float(k[4])) for k in rows]   # (openTime, close)
        except urllib.error.HTTPError as e:
            if e.code == 400:   # symbol not on spot
                return None
            time.sleep(1.0 + a)
        except Exception:
            time.sleep(1.0 + a)
    return None

def sma(xs, n):
    if len(xs) < n: return [None]*len(xs)
    out=[None]*(n-1); s=sum(xs[:n]); out.append(s/n)
    for i in range(n, len(xs)):
        s += xs[i]-xs[i-n]; out.append(s/n)
    return out

def ema(xs, n):
    if len(xs) < n: return [None]*len(xs)
    k=2/(n+1); out=[None]*(n-1); e=sum(xs[:n])/n; out.append(e)
    for i in range(n, len(xs)):
        e = xs[i]*k + e*(1-k); out.append(e)
    return out

def align(alt, btc):
    """Return ratio series aligned on openTime (alt_close/btc_close)."""
    bt = dict(btc)
    rs=[]
    for t,c in alt:
        b = bt.get(t)
        if b and b>0: rs.append((t, c/b))
    return rs

def sig(ratio_last, ma_last):
    if ratio_last is None or ma_last is None: return -1
    return 1 if ratio_last > ma_last else 0

def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    # fetch BTC per TF first (reference)
    btc = {}
    for tflab, tfi in TFS:
        b = fetch(BASE+"USDT" if False else "BTCUSDT", tfi)
        if not b:
            print(f"FATAL: BTC {tflab} fetch failed", file=sys.stderr); sys.exit(1)
        btc[tflab] = b
    rows=[]
    persist_days = 30
    for label, sym in COINS:
        rec = {"coin": label, "sym": sym, "sig": {}, "ratio_last":{}, "ma":{}}
        ok=True
        for tflab, tfi in TFS:
            kl = fetch(sym, tfi)
            time.sleep(0.08)
            if not kl: ok=False; break
            rs = align(kl, btc[tflab])
            ratios = [r for _,r in rs]
            if len(ratios) < LEN+1: ok=False; break
            s = sma(ratios, LEN); e = ema(ratios, LEN)
            rec["sig"][f"sma_{tflab}"] = sig(ratios[-1], s[-1])
            rec["sig"][f"ema_{tflab}"] = sig(ratios[-1], e[-1])
            rec["ratio_last"][tflab] = ratios[-1]
            if tflab=="D":
                # RS momentum (alt/BTC return) + persistence strip
                def chg(n):
                    if len(ratios)>n and ratios[-1-n]>0: return ratios[-1]/ratios[-1-n]-1
                    return None
                rec["mom_7d"]=chg(7); rec["mom_30d"]=chg(30); rec["mom_90d"]=chg(90)
                # last `persist_days` daily: ratio above its SMA200?
                strip=[]
                for i in range(len(ratios)-persist_days, len(ratios)):
                    strip.append(1 if (s[i] is not None and ratios[i]>s[i]) else 0)
                rec["strip"]=strip
                # chart series: daily ratio vs SMA200/EMA200 (last ~160 valid-MA bars)
                times=[t for t,_ in rs]
                def r6(x): return None if x is None else float(f"{x:.6g}")
                cn=min(160, len(ratios)-(LEN-1))
                a=len(ratios)-cn
                rec["chart"]={"t":times[a:],
                              "ratio":[r6(x) for x in ratios[a:]],
                              "sma":[r6(s[i]) for i in range(a,len(ratios))],
                              "ema":[r6(e[i]) for i in range(a,len(ratios))]}
        if not ok:
            print(f"skip {label} ({sym}) — no/short data", file=sys.stderr); continue
        rec["score"] = sum(1 for v in rec["sig"].values() if v==1)
        rows.append(rec)
    rows.sort(key=lambda r:(-r["score"], -(r.get("mom_7d") or -9)))
    payload = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "len": LEN, "base": BASE, "persist_days": persist_days,
        "tfs": [t[0] for t in TFS], "rows": rows,
    }
    html = render(payload)
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"wrote {OUT_DIR}/index.html — {len(rows)} coins, {payload['generated_utc']}")

def render(p):
    data = json.dumps(p)
    return TEMPLATE.replace("/*__DATA__*/", data)

TEMPLATE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ALT / BTC Relative Strength</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
:root{--bg:#0d1117;--panel:#161b22;--bull:#1f8b4c;--bear:#c0392b;--mut:#6b7280;--fg:#e6edf3;--bd:#30363d}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 -apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:18px}
h1{font-size:20px;margin:0 0 2px}.sub{color:var(--mut);font-size:12px;margin-bottom:16px}
.grid{display:grid;gap:18px}.card{background:var(--panel);border:1px solid var(--bd);border-radius:10px;padding:14px}
.card h2{font-size:14px;margin:0 0 10px;color:#9ca3af;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:5px 8px;text-align:center;border-bottom:1px solid #21262d}th{color:#9ca3af;font-weight:600;font-size:12px}
td.coin,th.coin{text-align:left;font-weight:600}
.cell{display:inline-block;width:22px;height:22px;line-height:22px;border-radius:4px;font-size:12px}
.up{background:rgba(31,139,76,.22);color:#3fb950}.dn{background:rgba(192,57,43,.22);color:#f85149}.na{background:rgba(110,118,129,.18);color:#6b7280}
.score{font-weight:700;padding:2px 7px;border-radius:5px}
.s5{background:rgba(31,139,76,.25);color:#3fb950}.s2{background:rgba(192,57,43,.25);color:#f85149}.s3{background:rgba(190,150,30,.22);color:#e3b341}
.strip{display:flex;gap:1px}.sb{width:5px;height:16px;border-radius:1px}
small{color:var(--mut)}
select{background:#0d1117;color:var(--fg);border:1px solid var(--bd);border-radius:6px;padding:5px 8px;font-size:13px;margin-bottom:8px}
.how{font-size:13px;line-height:1.6;color:#c9d1d9}.how b{color:#fff}.how code{background:#0d1117;padding:1px 5px;border-radius:4px;color:#e3b341}
.how .up{padding:0 5px}.how .dn{padding:0 5px}
</style></head><body><div class="wrap">
<h1>ALT / BTC — Relative Strength</h1>
<div class="sub">pair = alt&#247;BTC vs SMA<span id="len"></span> &amp; EMA<span id="len2"></span> on D / 4H / 1H · score = #above out of 6 · <span id="gen"></span> · Binance spot · auto-refreshes</div>
<div class="grid">
 <div class="card"><h2>Chart — alt / BTC ratio vs SMA200 &amp; EMA200 (daily)</h2>
   <select id="coinsel"></select>
   <div id="chart" style="height:430px"></div>
 </div>
 <div class="card"><h2>How to read this</h2><div class="how" id="how"></div></div>
 <div class="card"><h2>Leaderboard</h2><div id="tbl"></div></div>
 <div class="card"><h2>RS momentum (alt/BTC return)</h2><div id="mom" style="height:520px"></div></div>
 <div class="card"><h2>Signal heatmap</h2><div id="heat" style="height:560px"></div></div>
 <div class="card"><h2>Daily RS persistence — last <span id="pd"></span> days (alt/BTC above SMA200)</h2><div id="strip"></div></div>
</div>
<div class="sub" style="margin-top:14px">Standalone market dashboard. Not connected to any trading system. Data: Binance public spot klines.</div>
</div>
<script>
const P = /*__DATA__*/;
document.getElementById('len').textContent=P.len;document.getElementById('len2').textContent=P.len;
document.getElementById('len').textContent=P.len;document.getElementById('pd').textContent=P.persist_days;
document.getElementById('gen').textContent=P.generated_utc;
const cols=[['sma_D','SMA D'],['ema_D','EMA D'],['sma_4H','SMA 4H'],['ema_4H','EMA 4H'],['sma_1H','SMA 1H'],['ema_1H','EMA 1H']];
function cls(v){return v===1?'up':v===0?'dn':'na'}
function gly(v){return v===1?'▲':v===0?'▽':'—'}
// Leaderboard table
let h='<table><tr><th class="coin">ALT/BTC</th>'+cols.map(c=>`<th>${c[1]}</th>`).join('')+'<th>7d%</th><th>30d%</th><th>Score</th></tr>';
for(const r of P.rows){
  const sc=r.score, scc=sc>=5?'s5':sc<=2?'s2':'s3';
  const pc=v=>v==null?'<small>—</small>':`<span style="color:${v>=0?'#3fb950':'#f85149'}">${(v*100).toFixed(1)}</span>`;
  h+=`<tr><td class="coin">${r.coin}<small>/BTC</small></td>`+
     cols.map(c=>`<td><span class="cell ${cls(r.sig[c[0]])}">${gly(r.sig[c[0]])}</span></td>`).join('')+
     `<td>${pc(r.mom_7d)}</td><td>${pc(r.mom_30d)}</td><td><span class="score ${scc}">${sc}/6</span></td></tr>`;
}
document.getElementById('tbl').innerHTML=h+'</table>';
// Momentum bar (7d & 30d), sorted by 30d
const mr=[...P.rows].filter(r=>r.mom_30d!=null).sort((a,b)=>a.mom_30d-b.mom_30d);
Plotly.newPlot('mom',[
 {x:mr.map(r=>r.mom_30d*100),y:mr.map(r=>r.coin),type:'bar',orientation:'h',name:'30d',marker:{color:mr.map(r=>r.mom_30d>=0?'#1f8b4c':'#c0392b')}},
 {x:mr.map(r=>(r.mom_7d||0)*100),y:mr.map(r=>r.coin),type:'bar',orientation:'h',name:'7d',marker:{color:'#888'},opacity:.55},
],{barmode:'overlay',margin:{l:60,r:20,t:10,b:30},paper_bgcolor:'#161b22',plot_bgcolor:'#161b22',font:{color:'#e6edf3'},xaxis:{title:'% vs BTC',zeroline:true,zerolinecolor:'#444',gridcolor:'#21262d'},yaxis:{automargin:true},legend:{orientation:'h',y:1.05}},{displayModeBar:false,responsive:true});
// Heatmap coins x 6 signals
const z=P.rows.map(r=>cols.map(c=>r.sig[c[0]]));
Plotly.newPlot('heat',[{z:z,x:cols.map(c=>c[1]),y:P.rows.map(r=>r.coin),type:'heatmap',colorscale:[[0,'#c0392b'],[0.5,'#6b7280'],[1,'#1f8b4c']],zmin:-1,zmax:1,showscale:false,xgap:2,ygap:2}],
 {margin:{l:60,r:10,t:10,b:40},paper_bgcolor:'#161b22',plot_bgcolor:'#161b22',font:{color:'#e6edf3'},yaxis:{automargin:true,autorange:'reversed'}},{displayModeBar:false,responsive:true});
// Persistence strips
let s='<table>';
for(const r of P.rows){
  const st=(r.strip||[]).map(v=>`<span class="sb" style="background:${v?'#1f8b4c':'#3a2226'}"></span>`).join('');
  s+=`<tr><td class="coin">${r.coin}</td><td style="text-align:left"><span class="strip">${st}</span></td></tr>`;
}
document.getElementById('strip').innerHTML=s+'</table>';
// Coin dropdown + ratio chart
const sel=document.getElementById('coinsel');
P.rows.forEach((r,i)=>{const o=document.createElement('option');o.value=i;o.textContent=`${r.coin}  (${r.score}/6)`;sel.appendChild(o);});
function drawChart(i){
  const r=P.rows[i], c=r.chart; if(!c){document.getElementById('chart').innerHTML='<small>no chart data</small>';return;}
  const x=c.t.map(t=>new Date(t));
  Plotly.newPlot('chart',[
    {x:x,y:c.ratio,name:r.coin+'/BTC',mode:'lines',line:{color:'#58a6ff',width:2}},
    {x:x,y:c.sma,name:'SMA200',mode:'lines',line:{color:'#e3b341',width:1.4}},
    {x:x,y:c.ema,name:'EMA200',mode:'lines',line:{color:'#3fb950',width:1.4,dash:'dot'}},
  ],{margin:{l:60,r:15,t:6,b:30},paper_bgcolor:'#161b22',plot_bgcolor:'#161b22',font:{color:'#e6edf3'},
     xaxis:{gridcolor:'#21262d'},yaxis:{title:'alt/BTC',gridcolor:'#21262d'},
     legend:{orientation:'h',y:1.08}},{displayModeBar:false,responsive:true});
}
sel.addEventListener('change',e=>drawChart(+e.target.value));
drawChart(0);
// How to read
document.getElementById('how').innerHTML=`
<p><b>The idea:</b> for each coin we build the <b>synthetic pair = coin price &#247; BTC price</b>. If that pair is rising, the coin is <b>outperforming BTC</b> (gaining in BTC terms); if falling, it's underperforming. Everything here measures strength <i>relative to BTC</i>, not the USD price.</p>
<p><b>The chart:</b> the blue line is the alt/BTC ratio. The <span style="color:#e3b341">orange</span> line is its <b>SMA200</b> and the <span style="color:#3fb950">green dotted</span> is its <b>EMA200</b> (200-period averages of the ratio). <b>Ratio above the averages = the coin is in a relative up-trend vs BTC</b>; below = down-trend. Pick a coin from the dropdown.</p>
<p><b>Score (x/6):</b> we check the same thing on <b>3 timeframes</b> (Daily, 4H, 1H) &times; <b>2 averages</b> (SMA, EMA) = 6 checks. Score = how many say "above". <span class="up">▲</span> above &nbsp; <span class="dn">▽</span> below &nbsp; — no data.
 <code>6/6</code> = strong vs BTC on every horizon; <code>0/6</code> = weak everywhere; mixed = trend turning.</p>
<p><b>7d% / 30d%:</b> how much the coin moved <i>against BTC</i> over the last 7 / 30 days. Positive = beat BTC.</p>
<p><b>Heatmap:</b> the 6 checks for all coins at a glance (green=above, red=below). <b>Persistence strip:</b> the last ${P.persist_days} daily bars — green where the coin held above its SMA200 vs BTC. Lots of green = consistently strong; recent green after red = a fresh rotation into that coin.</p>
<p><b>How to use it:</b> high score + rising 7d/30d + a strip flipping green = money rotating <i>into</i> that alt vs BTC (relative momentum). Low score + red = capital leaving it. It tells you <b>where strength is</b> across the alts right now — it is <b>not</b> a buy/sell signal by itself.</p>`;
</script></body></html>"""

if __name__ == "__main__":
    main()
