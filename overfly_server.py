#!/usr/bin/env python3
"""
OVERFLY - Local server + web UI
Run: python3 overfly_server.py
Then open: http://localhost:7477
"""

import json, math, os, sys, threading, subprocess, time, webbrowser, requests as req_lib
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import urlopen, Request
from urllib.error import URLError

# ── Config ────────────────────────────────────────────────────────────────────
HOME_LAT = 39.3896
HOME_LON = -104.8900
PORT     = int(os.environ.get("PORT", 7477))

# ── Speech ────────────────────────────────────────────────────────────────────
_speech_lock = threading.Lock()

def speak(text):
    def _say():
        with _speech_lock:
            try:
                if sys.platform == "darwin":
                    subprocess.run(["say", "-r", "175", text], capture_output=True)
                elif sys.platform.startswith("linux"):
                    subprocess.run(["espeak", "-s", "160", text], capture_output=True)
                elif sys.platform == "win32":
                    try:
                        import pyttsx3
                        e = pyttsx3.init(); e.setProperty("rate",175); e.say(text); e.runAndWait()
                    except ImportError:
                        ps = f'Add-Type -AssemblyName System.Speech;(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak("{text}")'
                        subprocess.run(["powershell","-Command",ps], capture_output=True)
            except Exception: pass
    threading.Thread(target=_say, daemon=True).start()

def ding():
    try:
        if sys.platform == "darwin":
            subprocess.run(["afplay","/System/Library/Sounds/Glass.aiff"], capture_output=True)
        else:
            print("\a", end="", flush=True)
    except Exception:
        print("\a", end="", flush=True)

# ── Helpers ───────────────────────────────────────────────────────────────────
REG_PREFIXES = [
    ("N","United States"),("G-","United Kingdom"),("C-","Canada"),
    ("D-","Germany"),("F-","France"),("I-","Italy"),("B-","China"),
    ("VH-","Australia"),("JA","Japan"),("HL","South Korea"),
    ("VT-","India"),("ZS-","South Africa"),("LN-","Norway"),
    ("SE-","Sweden"),("OY-","Denmark"),("OH-","Finland"),
    ("PH-","Netherlands"),("HB-","Switzerland"),("OE-","Austria"),
    ("EC-","Spain"),("PP-","Brazil"),("PR-","Brazil"),("PT-","Brazil"),
    ("XA-","Mexico"),("XB-","Mexico"),("RP-","Philippines"),
    ("TC-","Turkey"),("A6-","UAE"),("4X-","Israel"),("AP-","Pakistan"),
]
def country_from_reg(reg):
    if not reg: return ""
    r = reg.upper()
    for p, c in REG_PREFIXES:
        if r.startswith(p): return c
    return ""

def haversine_nm(lat1,lon1,lat2,lon2):
    R=3440.065; dlat=math.radians(lat2-lat1); dlon=math.radians(lon2-lon1)
    a=math.sin(dlat/2)**2+math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R*2*math.atan2(math.sqrt(a),math.sqrt(1-a))

def bearing_label(lat1,lon1,lat2,lon2):
    dlon=math.radians(lon2-lon1)
    x=math.sin(dlon)*math.cos(math.radians(lat2))
    y=math.cos(math.radians(lat1))*math.sin(math.radians(lat2))-math.sin(math.radians(lat1))*math.cos(math.radians(lat2))*math.cos(dlon)
    b=math.degrees(math.atan2(x,y))%360
    return ["N","NE","E","SE","S","SW","W","NW"][int((b+22.5)/45)%8]

# ── Fetch aircraft ────────────────────────────────────────────────────────────
def fetch_aircraft(lat, lon, radius_nm):
    urls = [
        f"https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{radius_nm}",
        f"https://api.adsb.one/v2/point/{lat}/{lon}/{radius_nm}",
        f"https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{radius_nm}",
    ]
    session = req_lib.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "cross-site",
    })
    last_err = None
    for url in urls:
        try:
            r = session.get(url, timeout=12)
            r.raise_for_status()
            data = r.json()
            aircraft = []
            for ac in data.get("ac", data.get("aircraft", [])):
                alt = ac.get("alt_baro", "ground")
                if alt == "ground": continue
                if not ac.get("lat") or not ac.get("lon"): continue
                reg = (ac.get("r", "") or "").strip()
                aircraft.append({
                    "icao":     ac.get("hex", ""),
                    "callsign": (ac.get("flight", "") or reg or ac.get("hex", "")).strip(),
                    "reg":      reg,
                    "type":     (ac.get("t", "") or "").strip(),
                    "lat":      ac.get("lat"),
                    "lon":      ac.get("lon"),
                    "altFt":    int(alt) if isinstance(alt, (int, float)) else None,
                    "spdKt":    int(ac.get("gs", 0)) if ac.get("gs") else None,
                    "country":  country_from_reg(reg),
                    "distNm":   round(haversine_nm(lat, lon, ac["lat"], ac["lon"]), 1),
                    "dir":      bearing_label(lat, lon, ac["lat"], ac["lon"]),
                })
            aircraft.sort(key=lambda a: a["altFt"] or 0, reverse=True)
            return aircraft
        except Exception as e:
            last_err = e
            continue
    raise Exception(f"All sources failed: {last_err}")

# ── HTTP handler ──────────────────────────────────────────────────────────────
HTML = None  # loaded once

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass  # silence access log

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type","text/html")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        elif self.path.startswith("/scan"):
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            lat    = float(qs.get("lat",[HOME_LAT])[0])
            lon    = float(qs.get("lon",[HOME_LON])[0])
            radius = int(qs.get("radius",[50])[0])
            try:
                aircraft = fetch_aircraft(lat, lon, radius)
                self.send_json({"ok": True, "aircraft": aircraft, "count": len(aircraft)})
            except Exception as e:
                import traceback
                self.send_json({"ok": False, "error": str(e), "detail": traceback.format_exc()}, 500)

        elif self.path.startswith("/speak"):
            from urllib.parse import urlparse, parse_qs, unquote
            qs = parse_qs(urlparse(self.path).query)
            text = unquote(qs.get("text",[""])[0])
            mode = qs.get("mode",["voice"])[0]
            if mode in ("ding","both"): ding()
            if mode in ("voice","both") and text: speak(text)
            self.send_json({"ok": True})

        else:
            self.send_response(404); self.end_headers()

# ── HTML UI ───────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OVERFLY</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&family=Exo+2:wght@300;400;600&display=swap');
  :root{--bg:#050a0f;--panel:#0d1e2e;--border:#1a3a5c;--accent:#00d4ff;--accent2:#ff6b35;--green:#39ff14;--text:#c8e6f5;--muted:#4a7fa5;--danger:#ff3355;}
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--text);font-family:'Exo 2',sans-serif;min-height:100vh;overflow-x:hidden;}
  body::before{content:'';position:fixed;inset:0;background-image:linear-gradient(rgba(0,212,255,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(0,212,255,.03) 1px,transparent 1px);background-size:40px 40px;pointer-events:none;}
  .wrap{max-width:1000px;margin:0 auto;padding:16px;position:relative;}

  header{display:flex;align-items:center;justify-content:space-between;padding:16px 0 20px;border-bottom:1px solid var(--border);margin-bottom:18px;}
  .logo{font-family:'Orbitron',monospace;font-size:26px;font-weight:900;letter-spacing:6px;color:var(--accent);text-shadow:0 0 20px rgba(0,212,255,.5);}
  .logo span{color:var(--accent2);}
  .pill{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--border);border-radius:20px;padding:6px 14px;font-family:'Share Tech Mono',monospace;font-size:12px;color:var(--muted);}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--muted);}
  .dot.live{background:var(--green);box-shadow:0 0 8px var(--green);animation:pulse 2s infinite;}
  .dot.err{background:var(--danger);box-shadow:0 0 8px var(--danger);}
  @keyframes pulse{0%,100%{opacity:1;}50%{opacity:.4;}}

  .controls{display:grid;grid-template-columns:1fr auto;gap:12px;margin-bottom:16px;align-items:start;}
  .card{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px 18px;}
  .clabel{font-family:'Share Tech Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;text-transform:uppercase;margin-bottom:6px;}
  .cval{font-family:'Orbitron',monospace;font-size:13px;color:var(--accent);}
  .btns{display:flex;flex-direction:column;gap:8px;}
  .btn{font-family:'Orbitron',monospace;font-size:11px;letter-spacing:2px;font-weight:700;border:1px solid var(--accent);background:transparent;color:var(--accent);padding:11px 18px;border-radius:6px;cursor:pointer;transition:all .2s;text-transform:uppercase;white-space:nowrap;}
  .btn:hover{background:rgba(0,212,255,.1);}
  .btn:disabled{opacity:.4;cursor:not-allowed;}
  .btn.stop{border-color:var(--danger);color:var(--danger);}

  .settings{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap;}
  .sg{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:8px 14px;}
  .sg label{color:var(--muted);font-family:'Share Tech Mono',monospace;font-size:11px;letter-spacing:1px;}
  select,input[type=range]{background:var(--bg);border:1px solid var(--border);color:var(--text);font-family:'Share Tech Mono',monospace;font-size:12px;padding:4px 8px;border-radius:4px;outline:none;}
  input[type=range]{width:80px;accent-color:var(--accent);}
  .rv{font-family:'Orbitron',monospace;font-size:11px;color:var(--accent);min-width:44px;}

  .main{display:grid;grid-template-columns:210px 1fr;gap:16px;margin-bottom:16px;}
  .radar-wrap{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px;display:flex;flex-direction:column;align-items:center;gap:8px;}
  .rl{font-family:'Share Tech Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;}
  canvas{border-radius:50%;}

  .ac-panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;overflow:hidden;display:flex;flex-direction:column;}
  .ph{display:flex;align-items:center;justify-content:space-between;padding:11px 16px;border-bottom:1px solid var(--border);background:rgba(0,212,255,.04);}
  .pt{font-family:'Orbitron',monospace;font-size:11px;letter-spacing:3px;color:var(--accent);}
  .badge{background:rgba(0,212,255,.12);border:1px solid var(--accent);color:var(--accent);font-family:'Orbitron',monospace;font-size:12px;padding:2px 10px;border-radius:10px;}
  .ac-list{overflow-y:auto;flex:1;}
  .ac-item{display:grid;grid-template-columns:70px 80px 90px 70px 55px 40px 1fr;align-items:center;padding:10px 16px;border-bottom:1px solid rgba(26,58,92,.4);cursor:pointer;transition:background .15s;gap:6px;font-size:12px;}
  .ac-item:hover{background:rgba(0,212,255,.05);}
  .ac-item.fresh{animation:flashin 1.2s ease;}
  @keyframes flashin{0%{background:rgba(57,255,20,.15);}100%{background:transparent;}}
  .cs{font-family:'Orbitron',monospace;font-size:12px;font-weight:700;color:var(--accent);}
  .muted{color:var(--muted);font-family:'Share Tech Mono',monospace;font-size:10px;}
  .alt-hi{color:var(--accent);}  .alt-md{color:#ffd700;} .alt-lo{color:var(--accent2);}
  .empty{padding:40px;text-align:center;color:var(--muted);font-family:'Share Tech Mono',monospace;}

  .log-panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;overflow:hidden;}
  .log-body{max-height:140px;overflow-y:auto;padding:4px 0;}
  .le{display:flex;gap:10px;padding:6px 16px;font-family:'Share Tech Mono',monospace;font-size:11px;border-left:2px solid transparent;}
  .le.new{border-left-color:var(--accent);background:rgba(0,212,255,.04);}
  .lt{color:var(--muted);flex-shrink:0;}
  .lx{color:var(--text);}
  .lx b{color:var(--accent);}
  .lx.ok{color:var(--green);}
  .lx.err{color:var(--danger);}

  #toast{position:fixed;bottom:20px;right:20px;background:var(--panel);border:1px solid var(--accent);border-radius:10px;padding:13px 18px;max-width:320px;z-index:999;transform:translateY(140%);transition:transform .4s cubic-bezier(.34,1.56,.64,1);box-shadow:0 0 30px rgba(0,212,255,.2);}
  #toast.show{transform:translateY(0);}
  .th{font-family:'Orbitron',monospace;font-size:10px;color:var(--accent);letter-spacing:2px;margin-bottom:5px;}
  .tb{font-size:12px;line-height:1.6;}
  #countdown{font-family:'Orbitron',monospace;font-size:11px;color:var(--muted);padding:0 6px;}

  @media(max-width:640px){.main{grid-template-columns:1fr;}.ac-item{grid-template-columns:65px 1fr auto;}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">OVER<span>FLY</span></div>
    <div style="display:flex;gap:10px;align-items:center;">
      <span id="countdown"></span>
      <div class="pill"><div class="dot" id="dot"></div><span id="stxt">IDLE</span></div>
    </div>
  </header>

  <div class="controls">
    <div class="card">
      <div class="clabel">📍 Position</div>
      <div class="cval" id="posDisplay">39.3896°N, 104.8900°W — HOME</div>
    </div>
    <div class="btns">
      <button class="btn" id="scanBtn" onclick="startScan()">⬡ SCAN</button>
      <button class="btn stop" id="stopBtn" onclick="stopScan()" style="display:none">■ STOP</button>
    </div>
  </div>

  <div class="settings">
    <div class="sg"><label>RADIUS</label><input type="range" id="radR" min="10" max="150" value="50" oninput="document.getElementById('radV').textContent=this.value+'nm'"><span class="rv" id="radV">50nm</span></div>
    <div class="sg"><label>REFRESH</label>
      <select id="refSel"><option value="15">15s</option><option value="30" selected>30s</option><option value="60">60s</option></select>
    </div>
    <div class="sg"><label>ALERT</label>
      <select id="alertSel"><option value="voice">🔊 Voice</option><option value="ding">🔔 Ding</option><option value="both" selected>🔊+🔔 Both</option><option value="none">🔇 Silent</option></select>
    </div>
    <button class="btn" id="muteBtn" onclick="toggleMute()" style="padding:8px 14px;">🔊</button>
  </div>

  <div class="main">
    <div class="radar-wrap">
      <div class="rl">RADAR</div>
      <canvas id="radar" width="180" height="180"></canvas>
      <div class="rl" id="rcount">0 contacts</div>
    </div>
    <div class="ac-panel">
      <div class="ph"><div class="pt">AIRCRAFT OVERHEAD</div><div class="badge" id="acct">0</div></div>
      <div class="ac-list" id="acList"><div class="empty">Press SCAN to detect aircraft</div></div>
    </div>
  </div>

  <div class="log-panel">
    <div class="ph"><div class="pt">INTERCEPT LOG</div></div>
    <div class="log-body" id="logBody"><div class="le"><span class="lt">--:--:--</span><span class="lx">OVERFLY ready. Connected to local server.</span></div></div>
  </div>
</div>

<div id="toast"><div class="th">✈ NEW CONTACT</div><div class="tb" id="toastBody"></div></div>

<script>
const HOME_LAT=39.3896, HOME_LON=-104.8900;
let scanning=false, tid=null, ctid=null, known=new Map(), muted=false, radarAngle=0;

// ── Fetch from local server ─────────────────────────────────────────────────
async function fetchAircraft(){
  const r=parseInt(document.getElementById('radR').value);
  const res=await fetch(`/scan?lat=${HOME_LAT}&lon=${HOME_LON}&radius=${r}`);
  if(!res.ok) throw new Error('Server error '+res.status);
  return res.json();
}

async function serverSpeak(text){
  const mode=muted?'none':document.getElementById('alertSel').value;
  const url=`/speak?text=${encodeURIComponent(text)}&mode=${mode}`;
  await fetch(url).catch(()=>{});
}

// ── Main scan ───────────────────────────────────────────────────────────────
async function doScan(){
  setStatus('scan');
  try{
    const data=await fetchAircraft();
    if(!data.ok) throw new Error(data.error||'Unknown error');
    const cur=new Map();
    for(const ac of data.aircraft){
      ac.isNew=!known.has(ac.icao);
      cur.set(ac.icao,ac);
    }
    // Announce new
    for(const ac of [...cur.values()].filter(a=>a.isNew)){
      const cs=ac.callsign||ac.reg||ac.icao;
      const alt=ac.altFt?ac.altFt.toLocaleString()+' feet':'unknown altitude';
      const msg=`${cs}${ac.type?', '+ac.type:''}, from ${ac.country||'unknown'}, at ${alt}`;
      await serverSpeak(msg);
      showToast(ac);
      addLog(`<b>${cs}</b> ${ac.type?'('+ac.type+')':''} from ${ac.country||'?'} at ${ac.altFt?ac.altFt.toLocaleString()+' ft':'?'}`,'ok');
      await new Promise(r=>setTimeout(r,600));
    }
    known=cur;
    renderList([...cur.values()]);
    addLog('Scan: '+data.count+' contacts');
    setStatus('live');
  }catch(e){
    addLog('⚠ '+e.message,'err');
    setStatus('err');
  }
}

function startScan(){
  scanning=true;
  document.getElementById('scanBtn').style.display='none';
  document.getElementById('stopBtn').style.display='';
  doScan();
  scheduleNext();
}

function stopScan(){
  scanning=false;
  clearTimeout(tid); clearInterval(ctid);
  document.getElementById('scanBtn').style.display='';
  document.getElementById('stopBtn').style.display='none';
  document.getElementById('countdown').textContent='';
  known.clear(); renderList([]);
  setStatus('idle'); addLog('Tracking stopped.');
}

function scheduleNext(){
  if(!scanning)return;
  let secs=parseInt(document.getElementById('refSel').value);
  document.getElementById('countdown').textContent=`next: ${secs}s`;
  ctid=setInterval(()=>{
    secs--;
    document.getElementById('countdown').textContent=`next: ${secs}s`;
    if(secs<=0){clearInterval(ctid);}
  },1000);
  tid=setTimeout(()=>{ doScan(); scheduleNext(); }, secs*1000);
}

// ── Render ──────────────────────────────────────────────────────────────────
function altColor(ft){
  if(!ft)return'';
  if(ft>25000)return'alt-hi';
  if(ft>5000)return'alt-md';
  return'alt-lo';
}

function renderList(list){
  document.getElementById('acct').textContent=list.length;
  const el=document.getElementById('acList');
  if(!list.length){el.innerHTML='<div class="empty">No aircraft in range</div>';return;}
  el.innerHTML=list.map(ac=>{
    const cs=ac.callsign||ac.reg||ac.icao;
    const alt=ac.altFt?ac.altFt.toLocaleString()+' ft':'N/A';
    const spd=ac.spdKt?ac.spdKt+'kt':'';
    const ac_=altColor(ac.altFt);
    return`<div class="ac-item${ac.isNew?' fresh':''}" onclick="reannounce('${ac.icao}')">
      <div class="cs">${cs}</div>
      <div class="${ac_} muted" style="font-size:11px">${alt}</div>
      <div style="color:#c8e6f5;font-size:11px">${ac.type||'—'}</div>
      <div class="muted">${ac.country||ac.reg||'?'}</div>
      <div class="muted">${spd}</div>
      <div class="muted">${ac.dir||''}</div>
      <div class="muted">${ac.distNm?ac.distNm+'nm':''}</div>
    </div>`;
  }).join('');
}

// ── Radar ────────────────────────────────────────────────────────────────────
function drawRadar(list){
  const cv=document.getElementById('radar'),cx2=cv.getContext('2d');
  const W=cv.width,c=W/2,r=c-4;
  cx2.clearRect(0,0,W,W);
  cx2.fillStyle='#050a0f';cx2.beginPath();cx2.arc(c,c,r,0,Math.PI*2);cx2.fill();
  [.25,.5,.75,1].forEach(f=>{cx2.beginPath();cx2.arc(c,c,r*f,0,Math.PI*2);cx2.strokeStyle='rgba(0,212,255,.12)';cx2.lineWidth=1;cx2.stroke();});
  cx2.strokeStyle='rgba(0,212,255,.12)';cx2.lineWidth=1;
  cx2.beginPath();cx2.moveTo(c,c-r);cx2.lineTo(c,c+r);cx2.stroke();
  cx2.beginPath();cx2.moveTo(c-r,c);cx2.lineTo(c+r,c);cx2.stroke();
  cx2.save();cx2.translate(c,c);cx2.rotate(radarAngle);
  cx2.beginPath();cx2.moveTo(0,0);cx2.arc(0,0,r,-Math.PI/2,-Math.PI/2+1.2);cx2.closePath();cx2.fillStyle='rgba(0,212,255,.06)';cx2.fill();
  cx2.beginPath();cx2.moveTo(0,0);cx2.lineTo(0,-r);cx2.strokeStyle='rgba(0,212,255,.7)';cx2.lineWidth=1.5;cx2.stroke();
  cx2.restore();
  cx2.beginPath();cx2.arc(c,c,3,0,Math.PI*2);cx2.fillStyle='#00d4ff';cx2.fill();
  const km=parseFloat(document.getElementById('radR').value)*1.852;
  (list||[]).forEach(ac=>{
    if(!ac.lat||!ac.lon)return;
    const dist=ac.distNm*1.852; const ratio=Math.min(dist/km,1);
    const ang=Math.atan2(ac.lon-HOME_LON,ac.lat-HOME_LAT);
    const bx=c+ratio*r*Math.sin(ang),by=c-ratio*r*Math.cos(ang);
    cx2.beginPath();cx2.arc(bx,by,3,0,Math.PI*2);
    const col=ac.altFt>25000?'#00d4ff':ac.altFt>5000?'#ffd700':'#ff6b35';
    cx2.fillStyle=col;cx2.shadowColor=col;cx2.shadowBlur=6;cx2.fill();cx2.shadowBlur=0;
  });
  document.getElementById('rcount').textContent=(list?list.length:0)+' contact'+((list&&list.length!==1)?'s':'');
}
(function loop(){radarAngle+=scanning?.04:.015;drawRadar(scanning?[...known.values()]:[]);requestAnimationFrame(loop);})();

// ── Toast ────────────────────────────────────────────────────────────────────
function showToast(ac){
  const cs=(ac.callsign||ac.reg||ac.icao).trim();
  document.getElementById('toastBody').innerHTML=`<b>${cs}</b> — ${ac.type||'Aircraft'}<br>From: ${ac.country||ac.reg||'?'} &nbsp;|&nbsp; Alt: ${ac.altFt?ac.altFt.toLocaleString()+' ft':'N/A'} &nbsp;|&nbsp; ${ac.dir||''} ${ac.distNm?ac.distNm+'nm':''}`;
  const t=document.getElementById('toast');t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),6000);
}

async function reannounce(icao){
  const ac=known.get(icao); if(!ac)return;
  const cs=ac.callsign||ac.reg||ac.icao;
  const alt=ac.altFt?ac.altFt.toLocaleString()+' feet':'unknown altitude';
  await serverSpeak(`${cs}${ac.type?', '+ac.type:''}, from ${ac.country||'unknown'}, at ${alt}`);
  showToast(ac);
}

// ── Helpers ──────────────────────────────────────────────────────────────────
function toggleMute(){muted=!muted;document.getElementById('muteBtn').textContent=muted?'🔇':'🔊';}

function setStatus(s){
  const dot=document.getElementById('dot'),txt=document.getElementById('stxt');
  dot.className='dot';
  if(s==='live'){dot.classList.add('live');txt.textContent='LIVE';}
  else if(s==='scan'){txt.textContent='SCANNING...';}
  else if(s==='err'){dot.classList.add('err');txt.textContent='ERROR';}
  else txt.textContent='IDLE';
}

function addLog(html,cls=''){
  const body=document.getElementById('logBody'),now=new Date().toLocaleTimeString();
  const el=document.createElement('div');el.className='le new';
  el.innerHTML=`<span class="lt">${now}</span><span class="lx ${cls}">${html}</span>`;
  body.prepend(el);setTimeout(()=>el.classList.remove('new'),3000);
  while(body.children.length>60)body.removeChild(body.lastChild);
}
</script>
</body>
</html>"""

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n  ✈  OVERFLY starting on port {PORT}\n")
    pass  # no browser on server
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"  Serving on port {PORT}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  OVERFLY stopped.\n")

if __name__ == "__main__":
    main()
