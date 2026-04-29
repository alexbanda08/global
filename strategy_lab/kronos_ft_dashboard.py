"""
kronos_ft_dashboard — tiny local HTTP server that live-parses Kronos fine-tune
logs under D:/kronos-ft/<exp>/logs/*.log and serves a real-time HTML dashboard
at http://localhost:8765/.

No external deps (stdlib http.server + Chart.js from CDN). Refreshes every 3s.

Usage:
  D:/kronos-venv/Scripts/python.exe strategy_lab/kronos_ft_dashboard.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = Path("D:/kronos-ft")
PORT = 8765
MAX_POINTS = 2000    # cap loss series sent to browser

STEP_RE = re.compile(
    r"\[Epoch (\d+)/(\d+), Step (\d+)/(\d+)\]\s*LR:\s*([\d\.eE\-]+),\s*Loss:\s*([\-\d\.eE]+)"
)
TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def list_experiments():
    if not BASE.exists():
        return []
    return sorted([p.name for p in BASE.iterdir() if p.is_dir()])


def parse_log(path: Path, checkpoint_dir: Path = None):
    if not path.exists():
        return {"status": "not_started", "points": [], "current": None}
    checkpoint_saved = bool(checkpoint_dir and checkpoint_dir.exists()
                            and any(checkpoint_dir.iterdir()))
    points = []
    first_ts = None
    last_ts = None
    last_line_ts = None
    current_epoch = None
    total_epochs = None
    current_step = None
    total_steps = None
    last_loss = None
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                t = TIME_RE.match(line)
                if t:
                    last_line_ts = t.group(1)
                m = STEP_RE.search(line)
                if not m:
                    continue
                ep, tep, st, tst, lr, loss = m.groups()
                current_epoch = int(ep)
                total_epochs = int(tep)
                current_step = int(st)
                total_steps = int(tst)
                try:
                    last_loss = float(loss)
                except ValueError:
                    continue
                if t:
                    ts = t.group(1)
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts
                points.append([int(st), last_loss])
        if len(points) > MAX_POINTS:
            stride = max(1, len(points) // MAX_POINTS)
            points = points[::stride]
        status = "running"
        idle = time.time() - path.stat().st_mtime
        if checkpoint_saved:
            status = "done"
        elif current_step == total_steps and current_epoch == total_epochs and total_steps:
            status = "done"
        elif idle > 60 and current_epoch == total_epochs and total_steps and \
             current_step is not None and (total_steps - current_step) <= 50:
            # within log_interval of the end AND idle -> finished (last log may be <total_steps)
            status = "done"
        elif idle > 180:
            status = "stalled"
        # steps/sec estimate from first/last timestamps
        steps_per_sec = None
        eta_sec = None
        if first_ts and last_ts and current_step and current_step > 1:
            try:
                t0 = time.mktime(time.strptime(first_ts, "%Y-%m-%d %H:%M:%S"))
                t1 = time.mktime(time.strptime(last_ts, "%Y-%m-%d %H:%M:%S"))
                dur = max(1, t1 - t0)
                steps_per_sec = current_step / dur
                remaining = max(0, (total_steps * (total_epochs - current_epoch + 1))
                                - (total_steps * (current_epoch - 1) + current_step))
                eta_sec = remaining / steps_per_sec if steps_per_sec else None
            except Exception:
                pass
        return {
            "status": status,
            "points": points,
            "current_epoch": current_epoch,
            "total_epochs": total_epochs,
            "current_step": current_step,
            "total_steps": total_steps,
            "last_loss": last_loss,
            "first_ts": first_ts,
            "last_ts": last_ts,
            "last_line_ts": last_line_ts,
            "steps_per_sec": steps_per_sec,
            "eta_sec": eta_sec,
            "log_size": path.stat().st_size,
            "log_path": str(path),
        }
    except Exception as e:
        return {"status": "error", "error": str(e), "points": []}


def tail_lines(path: Path, n: int = 20):
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return [ln.rstrip("\n") for ln in lines[-n:]]
    except Exception:
        return []


def build_status(exp: str):
    exp_dir = BASE / exp
    tok_log = exp_dir / "logs" / "tokenizer_training_rank_0.log"
    bm_log = exp_dir / "logs" / "basemodel_training_rank_0.log"
    tok_ckpt = exp_dir / "tokenizer" / "best_model"
    bm_ckpt = exp_dir / "basemodel" / "best_model"
    return {
        "experiments": list_experiments(),
        "exp": exp,
        "tokenizer": parse_log(tok_log, tok_ckpt),
        "basemodel": parse_log(bm_log, bm_ckpt),
        "tokenizer_tail": tail_lines(tok_log, 10),
        "basemodel_tail": tail_lines(bm_log, 10),
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<title>Kronos fine-tune dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 20px; background:#0b0f14; color:#e7eaee; }
  h1 { margin-top:0; font-size:20px; }
  select { background:#1a2030; color:#e7eaee; border:1px solid #2a3550; padding:6px; border-radius:4px; }
  .grid { display:grid; grid-template-columns: 1fr 1fr; gap:16px; }
  .panel { background:#151b26; border:1px solid #222a38; border-radius:8px; padding:14px; }
  .phase-title { font-weight:600; font-size:15px; margin-bottom:8px; }
  .status-pill { display:inline-block; padding:2px 8px; border-radius:10px; font-size:12px; margin-left:8px; }
  .s-running { background:#2563eb; color:white; }
  .s-done { background:#16a34a; color:white; }
  .s-not_started { background:#4b5563; color:white; }
  .s-stalled { background:#b45309; color:white; }
  .s-error { background:#991b1b; color:white; }
  .bar-wrap { background:#222a38; border-radius:3px; height:10px; overflow:hidden; margin:6px 0; }
  .bar-fill { background:#2563eb; height:100%; transition:width 0.4s ease; }
  .metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:8px; font-size:13px; }
  .metrics div { background:#0f1420; padding:6px 8px; border-radius:4px; }
  .metrics b { display:block; color:#9ca3af; font-weight:400; font-size:11px; }
  pre { background:#0f1420; padding:8px; border-radius:4px; font-size:11px; overflow-x:auto; max-height:160px; }
  canvas { background:#0f1420; border-radius:4px; }
  .meta { color:#9ca3af; font-size:12px; margin-top:6px; }
</style>
</head>
<body>
  <h1>Kronos fine-tune dashboard
    <select id="expSelect" onchange="location.search='?exp='+this.value"></select>
    <span id="gen" class="meta"></span>
  </h1>
  <div class="grid">
    <div class="panel">
      <div class="phase-title">Tokenizer <span id="tokStatus" class="status-pill"></span></div>
      <div class="bar-wrap"><div id="tokBar" class="bar-fill" style="width:0%"></div></div>
      <div class="metrics">
        <div><b>Epoch</b><span id="tokEpoch">—</span></div>
        <div><b>Step</b><span id="tokStep">—</span></div>
        <div><b>Loss</b><span id="tokLoss">—</span></div>
        <div><b>ETA</b><span id="tokEta">—</span></div>
      </div>
      <canvas id="tokChart" height="140"></canvas>
      <pre id="tokTail">—</pre>
    </div>
    <div class="panel">
      <div class="phase-title">Predictor (Kronos-base) <span id="bmStatus" class="status-pill"></span></div>
      <div class="bar-wrap"><div id="bmBar" class="bar-fill" style="width:0%"></div></div>
      <div class="metrics">
        <div><b>Epoch</b><span id="bmEpoch">—</span></div>
        <div><b>Step</b><span id="bmStep">—</span></div>
        <div><b>Loss</b><span id="bmLoss">—</span></div>
        <div><b>ETA</b><span id="bmEta">—</span></div>
      </div>
      <canvas id="bmChart" height="140"></canvas>
      <pre id="bmTail">—</pre>
    </div>
  </div>

<script>
const params = new URLSearchParams(location.search);
const currentExp = params.get("exp") || "";

function fmtEta(s){ if(!s) return "—"; s=Math.round(s); const h=Math.floor(s/3600), m=Math.floor((s%3600)/60); if(h) return h+"h "+m+"m"; return m+"m "+(s%60)+"s"; }

function mkChart(id){
  const ctx=document.getElementById(id).getContext("2d");
  return new Chart(ctx,{type:"line",data:{labels:[],datasets:[{data:[],borderColor:"#60a5fa",backgroundColor:"rgba(96,165,250,0.15)",borderWidth:1.5,pointRadius:0,tension:0.2,fill:true}]},options:{animation:false,plugins:{legend:{display:false}},scales:{x:{display:true,ticks:{color:"#6b7280",maxTicksLimit:6}},y:{ticks:{color:"#6b7280"},grid:{color:"#1f2937"}}}}});
}
const tokChart=mkChart("tokChart"), bmChart=mkChart("bmChart");

function updatePhase(prefix, phase, chart){
  document.getElementById(prefix+"Status").textContent=phase.status;
  document.getElementById(prefix+"Status").className="status-pill s-"+phase.status;
  const pct = (phase.current_step && phase.total_steps) ? (100*phase.current_step/phase.total_steps) : 0;
  document.getElementById(prefix+"Bar").style.width=pct.toFixed(1)+"%";
  document.getElementById(prefix+"Epoch").textContent = phase.current_epoch? (phase.current_epoch+"/"+phase.total_epochs) : "—";
  document.getElementById(prefix+"Step").textContent = phase.current_step? (phase.current_step+"/"+phase.total_steps+" ("+pct.toFixed(1)+"%)") : "—";
  document.getElementById(prefix+"Loss").textContent = phase.last_loss!=null? phase.last_loss.toFixed(4) : "—";
  document.getElementById(prefix+"Eta").textContent = fmtEta(phase.eta_sec);
  chart.data.labels = phase.points.map(p=>p[0]);
  chart.data.datasets[0].data = phase.points.map(p=>p[1]);
  chart.update("none");
}

async function tick(){
  try{
    const qs = currentExp ? ("?exp="+encodeURIComponent(currentExp)) : "";
    const r = await fetch("/api/status"+qs); const j = await r.json();
    document.getElementById("gen").textContent = "updated "+j.generated_at;
    const sel = document.getElementById("expSelect");
    if(sel.options.length !== j.experiments.length){
      sel.innerHTML = j.experiments.map(e=>`<option value="${e}" ${e===j.exp?"selected":""}>${e}</option>`).join("");
    }
    updatePhase("tok", j.tokenizer, tokChart);
    updatePhase("bm", j.basemodel, bmChart);
    document.getElementById("tokTail").textContent = (j.tokenizer_tail||[]).join("\n");
    document.getElementById("bmTail").textContent = (j.basemodel_tail||[]).join("\n");
  } catch(e){ console.error(e); }
}
tick(); setInterval(tick, 3000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a, **kw): pass  # silence access log

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def _send_html(self, body: str):
        b = body.encode("utf-8")
        self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._send_html(HTML); return
        if u.path == "/api/status":
            qs = parse_qs(u.query)
            exp = (qs.get("exp") or [None])[0]
            exps = list_experiments()
            if not exps:
                self._send_json({"experiments": [], "exp": None, "error": "no experiments under " + str(BASE)}); return
            if not exp or exp not in exps:
                exp = exps[-1]
            self._send_json(build_status(exp)); return
        self._send_json({"error": "not found"}, 404)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Kronos FT dashboard running at http://localhost:{PORT}/")
    print(f"Watching {BASE}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    main()
