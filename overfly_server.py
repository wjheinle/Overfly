#!/usr/bin/env python3
"""OVERFLY - Live Aircraft Tracker"""

import json, math, os, re, sys, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
import requests as req_lib

PORT = int(os.environ.get("PORT", 7477))

# ── Lookups ───────────────────────────────────────────────────────────────────
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

AIRLINES = {
    "UAL":"United","DAL":"Delta","AAL":"American","SWA":"Southwest",
    "FFT":"Frontier","JBU":"JetBlue","ASA":"Alaska","SKW":"SkyWest",
    "RPA":"Republic","ENY":"Envoy","QXE":"Horizon","PDT":"Piedmont",
    "LXJ":"Flexjet","EJA":"NetJets","VJT":"VistaJet","VTE":"Contour",
    "FDX":"FedEx","UPS":"UPS","GTI":"Atlas Air","WJA":"WestJet",
    "ACA":"Air Canada","BAW":"British Airways","DLH":"Lufthansa",
    "AFR":"Air France","UAE":"Emirates","KLM":"KLM","IBE":"Iberia",
    "SWR":"Swiss","QFA":"Qantas","LIFELN":"Life Flight",
    "LYM":"Key Lime Air","SBE":"Shuttle America","USC":"US Customs",
}

AIRPORTS = {
    "LAX":"Los Angeles","JFK":"New York","ORD":"Chicago","ATL":"Atlanta",
    "DFW":"Dallas","DEN":"Denver","SFO":"San Francisco","SEA":"Seattle",
    "LAS":"Las Vegas","PHX":"Phoenix","MIA":"Miami","BOS":"Boston",
    "IAH":"Houston","MCO":"Orlando","EWR":"Newark","MSP":"Minneapolis",
    "DTW":"Detroit","PHL":"Philadelphia","CLT":"Charlotte",
    "SLC":"Salt Lake City","BWI":"Baltimore","SAN":"San Diego",
    "TPA":"Tampa","MDW":"Chicago Midway","HNL":"Honolulu",
    "PDX":"Portland","STL":"Saint Louis","BNA":"Nashville",
    "AUS":"Austin","MCI":"Kansas City","RDU":"Raleigh",
    "SJC":"San Jose","SMF":"Sacramento","IND":"Indianapolis",
    "CMH":"Columbus","PIT":"Pittsburgh","ABQ":"Albuquerque",
    "OKC":"Oklahoma City","ELP":"El Paso","COS":"Colorado Springs",
    "APA":"Centennial","BJC":"Broomfield","FNL":"Fort Collins",
    "ASE":"Aspen","EGE":"Eagle","HDN":"Hayden","TEX":"Telluride",
    "MTJ":"Montrose","GUC":"Gunnison","PUB":"Pueblo",
    "GJT":"Grand Junction","DRO":"Durango","JAC":"Jackson Hole",
    "BZN":"Bozeman","BOI":"Boise","RNO":"Reno","TUS":"Tucson",
    "LGB":"Long Beach","BUR":"Burbank","SNA":"Orange County",
    "PSP":"Palm Springs","FAT":"Fresno","GEG":"Spokane",
}

def country_from_reg(reg):
    if not reg: return ""
    r = reg.upper()
    for p, c in REG_PREFIXES:
        if r.startswith(p): return c
    return ""

def haversine_nm(lat1, lon1, lat2, lon2):
    R = 3440.065
    dlat = math.radians(lat2-lat1); dlon = math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def bearing_label(lat1, lon1, lat2, lon2):
    dlon = math.radians(lon2-lon1)
    x = math.sin(dlon)*math.cos(math.radians(lat2))
    y = math.cos(math.radians(lat1))*math.sin(math.radians(lat2)) - \
        math.sin(math.radians(lat1))*math.cos(math.radians(lat2))*math.cos(dlon)
    b = math.degrees(math.atan2(x, y)) % 360
    return ["N","NE","E","SE","S","SW","W","NW"][int((b+22.5)/45)%8]

# ── Flight route lookup via adsbdb ────────────────────────────────────────────
def get_route(callsign, session):
    cs = (callsign or "").strip()
    if not cs or len(cs) < 4: return None, None
    try:
        r = session.get(f"https://api.adsbdb.com/v0/callsign/{cs}", timeout=5)
        if r.status_code == 200:
            fp = r.json().get("response", {}).get("flightroute", {})
            if fp:
                orig = fp.get("origin", {})
                dest = fp.get("destination", {})
                orig_iata = orig.get("iata_code") or orig.get("icao_code","")
                dest_iata = dest.get("iata_code") or dest.get("icao_code","")
                orig_city = orig.get("municipality") or AIRPORTS.get(orig_iata,"")
                dest_city = dest.get("municipality") or AIRPORTS.get(dest_iata,"")
                return orig_city or orig_iata or None, dest_city or dest_iata or None
    except Exception:
        pass
    return None, None

# ── Fetch aircraft ────────────────────────────────────────────────────────────
def fetch_aircraft(lat, lon, radius_nm):
    urls = [
        f"https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{radius_nm}",
        f"https://api.adsb.one/v2/point/{lat}/{lon}/{radius_nm}",
        f"https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{radius_nm}",
    ]
    session = req_lib.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    })
    last_err = None
    for url in urls:
        try:
            time.sleep(1)
            r = session.get(url, timeout=12)
            r.raise_for_status()
            data = r.json()
            aircraft = []
            for ac in data.get("ac", data.get("aircraft", [])):
                alt = ac.get("alt_baro", "ground")
                if alt == "ground": continue
                if not ac.get("lat") or not ac.get("lon"): continue
                if isinstance(alt, (int, float)) and alt < 0: continue
                reg = (ac.get("r") or "").strip()
                callsign = (ac.get("flight") or reg or ac.get("hex","")).strip()
                # Airline name
                cs_up = callsign.upper()
                airline = "Private"
                for code, name in AIRLINES.items():
                    if cs_up.startswith(code):
                        airline = name
                        break
                # Route lookup
                origin, dest = get_route(callsign, session)
                aircraft.append({
                    "icao":     ac.get("hex",""),
                    "callsign": callsign,
                    "reg":      reg,
                    "type":     (ac.get("t") or "").strip(),
                    "airline":  airline,
                    "origin":   origin,
                    "dest":     dest,
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

# ── Geocode ZIP ───────────────────────────────────────────────────────────────
def geocode_zip(zipcode):
    url = f"https://nominatim.openstreetmap.org/search?postalcode={zipcode}&country=US&format=json&limit=1"
    r = req_lib.get(url, headers={"User-Agent": "OVERFLY/2.0"}, timeout=8)
    r.raise_for_status()
    data = r.json()
    if not data:
        raise Exception(f"ZIP code {zipcode} not found")
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(",")[0]

# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == "/scan":
            try:
                lat    = float(qs.get("lat", [0])[0])
                lon    = float(qs.get("lon", [0])[0])
                radius = int(qs.get("radius", [10])[0])
                aircraft = fetch_aircraft(lat, lon, radius)
                self.send_json({"ok": True, "aircraft": aircraft, "count": len(aircraft)})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)

        elif parsed.path == "/geocode":
            try:
                zipcode = qs.get("zip", [""])[0]
                lat, lon, name = geocode_zip(zipcode)
                self.send_json({"ok": True, "lat": lat, "lon": lon, "name": name})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)

        else:
            self.send_response(404)
            self.end_headers()

# ── HTML ──────────────────────────────────────────────────────────────────────
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
  .loc-card{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px 18px;margin-bottom:16px;}
  .loc-label{font-family:'Share Tech Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;text-transform:uppercase;margin-bottom:10px;}
  .loc-tabs{display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;}
  .loc-tab{font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:1px;padding:5px 12px;border-radius:4px;border:1px solid var(--border);background:transparent;color:var(--muted);cursor:pointer;transition:all .2s;}
  .loc-tab.active{border-color:var(--accent);color:var(--accent);background:rgba(0,212,255,.08);}
  .loc-val{font-family:'Orbitron',monospace;font-size:12px;color:var(--accent);margin-bottom:4px;}
  .loc-sub{font-family:'Share Tech Mono',monospace;font-size:10px;color:var(--muted);}
  .loc-input-row{display:none;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap;}
  .loc-input-row.show{display:flex;}
  .tin{background:var(--bg);border:1px solid var(--border);color:var(--accent);font-family:'Orbitron',monospace;font-size:12px;padding:6px 10px;border-radius:4px;outline:none;width:140px;}
  .tin:focus{border-color:var(--accent);}
  .tin::placeholder{color:var(--muted);font-size:10px;}
  .controls-row{display:flex;gap:12px;margin-bottom:16px;align-items:flex-start;flex-wrap:wrap;}
  .settings{display:flex;gap:10px;flex-wrap:wrap;flex:1;}
  .sg{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--border);border-radius:6px;padding:8px 14px;}
  .sg label{color:var(--muted);font-family:'Share Tech Mono',monospace;font-size:11px;letter-spacing:1px;}
  select,input[type=range]{background:var(--bg);border:1px solid var(--border);color:var(--text);font-family:'Share Tech Mono',monospace;font-size:12px;padding:4px 8px;border-radius:4px;outline:none;}
  input[type=range]{width:80px;accent-color:var(--accent);}
  .rv{font-family:'Orbitron',monospace;font-size:11px;color:var(--accent);min-width:44px;}
  .btn{font-family:'Orbitron',monospace;font-size:11px;letter-spacing:2px;font-weight:700;border:1px solid var(--accent);background:transparent;color:var(--accent);padding:11px 18px;border-radius:6px;cursor:pointer;transition:all .2s;text-transform:uppercase;white-space:nowrap;}
  .btn:hover{background:rgba(0,212,255,.1);}
  .btn.stop{border-color:var(--danger);color:var(--danger);}
  .btn.sm{padding:5px 12px;font-size:10px;}
  .btns{display:flex;flex-direction:column;gap:8px;}
  .main{display:grid;grid-template-columns:210px 1fr;gap:16px;margin-bottom:16px;}
  .radar-wrap{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px;display:flex;flex-direction:column;align-items:center;gap:8px;}
  .rl{font-family:'Share Tech Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;}
  canvas{border-radius:50%;}
  .ac-panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;overflow:hidden;display:flex;flex-direction:column;}
  .ph{display:flex;align-items:center;justify-content:space-between;padding:11px 16px;border-bottom:1px solid var(--border);background:rgba(0,212,255,.04);}
  .pt{font-family:'Orbitron',monospace;font-size:11px;letter-spacing:3px;color:var(--accent);}
  .badge{background:rgba(0,212,255,.12);border:1px solid var(--accent);color:var(--accent);font-family:'Orbitron',monospace;font-size:12px;padding:2px 10px;border-radius:10px;}
  .ac-list{overflow-y:auto;flex:1;max-height:300px;}
  .ac-item{display:grid;grid-template-columns:70px 1fr 80px 70px 50px 40px;align-items:center;padding:10px 16px;border-bottom:1px solid rgba(26,58,92,.4);cursor:pointer;transition:background .15s;gap:8px;font-size:12px;}
  .ac-item:hover{background:rgba(0,212,255,.05);}
  .ac-item.fresh{animation:flashin 1.2s ease;}
  @keyframes flashin{0%{background:rgba(57,255,20,.15);}100%{background:transparent;}}
  .cs{font-family:'Orbitron',monospace;font-size:12px;font-weight:700;color:var(--accent);}
  .ac-info{display:flex;flex-direction:column;gap:2px;}
  .ac-airline{font-size:12px;color:var(--text);}
  .ac-route{font-size:10px;color:var(--muted);font-family:'Share Tech Mono',monospace;}
  .muted{color:var(--muted);font-family:'Share Tech Mono',monospace;font-size:10px;}
  .alt-hi{color:var(--accent);} .alt-md{color:#ffd700;} .alt-lo{color:var(--accent2);}
  .empty{padding:40px;text-align:center;color:var(--muted);font-family:'Share Tech Mono',monospace;}
  .log-panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;overflow:hidden;}
  .log-body{max-height:140px;overflow-y:auto;padding:4px 0;}
  .le{display:flex;gap:10px;padding:6px 16px;font-family:'Share Tech Mono',monospace;font-size:11px;border-left:2px solid transparent;}
  .le.new{border-left-color:var(--accent);background:rgba(0,212,255,.04);}
  .lt{color:var(--muted);flex-shrink:0;} .lx{color:var(--text);} .lx b{color:var(--accent);}
  .lx.ok{color:var(--green);} .lx.err{color:var(--danger);}
  #toast{position:fixed;bottom:20px;right:20px;background:var(--panel);border:1px solid var(--accent);border-radius:10px;padding:13px 18px;max-width:320px;z-index:999;transform:translateY(140%);transition:transform .4s cubic-bezier(.34,1.56,.64,1);box-shadow:0 0 30px rgba(0,212,255,.2);}
  #toast.show{transform:translateY(0);}
  .th{font-family:'Orbitron',monospace;font-size:10px;color:var(--accent);letter-spacing:2px;margin-bottom:5px;}
  .tb{font-size:12px;line-height:1.6;}
  #countdown{font-family:'Orbitron',monospace;font-size:11px;color:var(--muted);padding:0 6px;}
  @media(max-width:640px){.main{grid-template-columns:1fr;}.ac-item{grid-template-columns:60px 1fr auto;}}
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

  <div class="loc-card">
    <div class="loc-label">📍 Location</div>
    <div class="loc-tabs">
      <button class="loc-tab active" id="tabHome" onclick="setLocMode('home')">🏠 Home</button>
      <button class="loc-tab" id="tabGps" onclick="setLocMode('gps')">📡 Find My Location</button>
      <button class="loc-tab" id="tabZip" onclick="setLocMode('zip')">🔢 ZIP Code</button>
      <button class="loc-tab" id="tabCoords" onclick="setLocMode('coords')">🌐 Coordinates</button>
    </div>
    <div class="loc-val" id="locVal">🏠 Home — 39.3896°N, 104.8900°W</div>
    <div class="loc-sub" id="locSub">Parker, Colorado</div>
    <div class="loc-input-row" id="zipRow">
      <input class="tin" id="zipIn" placeholder="e.g. 80134" maxlength="5">
      <button class="btn sm" onclick="lookupZip()">LOOK UP</button>
      <span id="zipStatus" style="font-family:'Share Tech Mono',monospace;font-size:10px;color:var(--muted);"></span>
    </div>
    <div class="loc-input-row" id="coordsRow">
      <span style="font-family:'Share Tech Mono',monospace;font-size:10px;color:var(--muted);">LAT</span>
      <input class="tin" id="latIn" placeholder="39.3896" style="width:110px;">
      <span style="font-family:'Share Tech Mono',monospace;font-size:10px;color:var(--muted);">LON</span>
      <input class="tin" id="lonIn" placeholder="-104.8900" style="width:110px;">
      <button class="btn sm" onclick="setManualCoords()">SET</button>
    </div>
  </div>

  <div class="controls-row">
    <div class="settings">
      <div class="sg"><label>RADIUS</label><input type="range" id="radR" min="5" max="25" value="10" oninput="document.getElementById('radV').textContent=this.value+'nm'"><span class="rv" id="radV">10nm</span></div>
      <div class="sg"><label>REFRESH</label>
        <select id="refSel"><option value="15">15s</option><option value="30" selected>30s</option><option value="60">60s</option></select>
      </div>
      <div class="sg"><label>ALERT</label>
        <select id="alertSel"><option value="voice">🔊 Voice</option><option value="ding">🔔 Ding</option><option value="both" selected>🔊+🔔 Both</option><option value="none">🔇 Silent</option></select>
      </div>
      <button class="btn" id="muteBtn" onclick="toggleMute()" style="padding:8px 14px;">🔊</button>
    </div>
    <div class="btns">
      <button class="btn" id="scanBtn" onclick="startScan()">⬡ SCAN</button>
      <button class="btn stop" id="stopBtn" onclick="stopScan()" style="display:none">■ STOP</button>
    </div>
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
    <div class="log-body" id="logBody"><div class="le"><span class="lt">--:--:--</span><span class="lx">OVERFLY ready.</span></div></div>
  </div>
</div>

<div id="toast"><div class="th">✈ NEW CONTACT</div><div class="tb" id="toastBody"></div></div>

<script>
const HOME_LAT=39.3896, HOME_LON=-104.8900;
let uLat=HOME_LAT, uLon=HOME_LON, locMode='home';
let scanning=false, tid=null, ctid=null, known=new Map(), muted=false, radarAngle=0;

// ── Audio ─────────────────────────────────────────────────────────────────────
function playDing(){
  try{
    const ctx=new(window.AudioContext||window.webkitAudioContext)();
    const o=ctx.createOscillator(),g=ctx.createGain();
    o.connect(g);g.connect(ctx.destination);
    o.frequency.setValueAtTime(880,ctx.currentTime);
    o.frequency.exponentialRampToValueAtTime(1760,ctx.currentTime+0.1);
    g.gain.setValueAtTime(0.4,ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001,ctx.currentTime+0.8);
    o.start();o.stop(ctx.currentTime+0.8);
  }catch(e){}
}

function playVoice(text){
  if(!window.speechSynthesis)return;
  speechSynthesis.cancel();
  const u=new SpeechSynthesisUtterance(text);
  u.rate=0.88;u.pitch=1.0;u.volume=1.0;
  speechSynthesis.speak(u);
}

function doAlert(ac){
  if(muted)return;
  const mode=document.getElementById('alertSel').value;
  if(mode==='none')return;
  // Skip private/small aircraft — only announce known airlines
  const airline=ac.airline||'Private';
  if(airline==='Private')return;
  // Only announce if we have an origin city
  const origin=ac.origin||null;
  if(!origin)return;
  const msg=airline+', '+origin;
  if(mode==='ding'||mode==='both')playDing();
  if(mode==='voice'||mode==='both')playVoice(msg);
  showToast(ac,msg);
}

// ── Location ──────────────────────────────────────────────────────────────────
function setLocMode(mode){
  locMode=mode;
  ['Home','Gps','Zip','Coords'].forEach(n=>{
    const el=document.getElementById('tab'+n);
    if(el)el.classList.toggle('active',n.toLowerCase()===mode);
  });
  document.getElementById('zipRow').classList.toggle('show',mode==='zip');
  document.getElementById('coordsRow').classList.toggle('show',mode==='coords');
  if(mode==='home'){
    uLat=HOME_LAT;uLon=HOME_LON;
    document.getElementById('locVal').textContent='🏠 Home — '+HOME_LAT+'°N, '+Math.abs(HOME_LON)+'°W';
    document.getElementById('locSub').textContent='Parker, Colorado';
  }else if(mode==='gps'){
    document.getElementById('locVal').textContent='Requesting GPS...';
    document.getElementById('locSub').textContent='';
    if(!navigator.geolocation){
      document.getElementById('locVal').textContent='⚠ GPS not available — try ZIP or Coords';return;
    }
    navigator.geolocation.getCurrentPosition(
      p=>{
        uLat=p.coords.latitude;uLon=p.coords.longitude;
        document.getElementById('locVal').textContent=uLat.toFixed(4)+'°, '+uLon.toFixed(4)+'° — GPS Locked';
        document.getElementById('locSub').textContent='Accuracy: ±'+Math.round(p.coords.accuracy)+'m';
        addLog('GPS locked: '+uLat.toFixed(4)+', '+uLon.toFixed(4));
      },
      ()=>{document.getElementById('locVal').textContent='⚠ GPS blocked — try ZIP or Coords tab';},
      {timeout:10000}
    );
  }else if(mode==='zip'){
    document.getElementById('locVal').textContent='Enter ZIP code below';
    document.getElementById('locSub').textContent='';
  }else if(mode==='coords'){
    document.getElementById('locVal').textContent='Enter coordinates below';
    document.getElementById('locSub').textContent='';
  }
}

async function lookupZip(){
  const zip=document.getElementById('zipIn').value.trim();
  if(!zip||zip.length<5)return;
  const st=document.getElementById('zipStatus');
  st.textContent='Looking up...';
  try{
    const r=await fetch('/geocode?zip='+zip);
    const d=await r.json();
    if(!d.ok)throw new Error(d.error);
    uLat=d.lat;uLon=d.lon;
    document.getElementById('locVal').textContent=uLat.toFixed(4)+'°, '+Math.abs(uLon).toFixed(4)+'°';
    document.getElementById('locSub').textContent=d.name;
    st.textContent='✓ '+d.name;
    addLog('ZIP: <b>'+zip+'</b> → '+d.name);
  }catch(e){st.textContent='⚠ '+e.message;}
}

function setManualCoords(){
  const lat=parseFloat(document.getElementById('latIn').value);
  const lon=parseFloat(document.getElementById('lonIn').value);
  if(isNaN(lat)||isNaN(lon)||lat<-90||lat>90||lon<-180||lon>180){
    addLog('⚠ Invalid coordinates','err');return;
  }
  uLat=lat;uLon=lon;
  document.getElementById('locVal').textContent=lat.toFixed(4)+'°, '+Math.abs(lon).toFixed(4)+'° — Set';
  document.getElementById('locSub').textContent='';
  addLog('Coords set: '+lat.toFixed(4)+', '+lon.toFixed(4));
}

// ── Scan ──────────────────────────────────────────────────────────────────────
async function doScan(){
  if(!uLat||!uLon){addLog('⚠ No location set','err');return;}
  setStatus('scan');
  try{
    const radius=parseInt(document.getElementById('radR').value);
    const res=await fetch('/scan?lat='+uLat+'&lon='+uLon+'&radius='+radius);
    const data=await res.json();
    if(!data.ok)throw new Error(data.error||'Unknown error');
    const cur=new Map();
    for(const ac of data.aircraft){
      ac.isNew=!known.has(ac.icao);
      cur.set(ac.icao,ac);
    }
    for(const ac of [...cur.values()].filter(a=>a.isNew)){
      doAlert(ac);
      const cs=ac.callsign||ac.reg||ac.icao;
      const route=ac.origin&&ac.dest?ac.origin+' → '+ac.dest:ac.origin||'';
      addLog('<b>'+cs+'</b> '+ac.airline+(route?' | '+route:''),'ok');
      await new Promise(r=>setTimeout(r,800));
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
  doScan();scheduleNext();
}

function stopScan(){
  scanning=false;clearTimeout(tid);clearInterval(ctid);
  document.getElementById('scanBtn').style.display='';
  document.getElementById('stopBtn').style.display='none';
  document.getElementById('countdown').textContent='';
  known.clear();renderList([]);setStatus('idle');addLog('Tracking stopped.');
}

function scheduleNext(){
  if(!scanning)return;
  let secs=parseInt(document.getElementById('refSel').value);
  document.getElementById('countdown').textContent='next: '+secs+'s';
  ctid=setInterval(()=>{
    secs--;
    document.getElementById('countdown').textContent='next: '+secs+'s';
    if(secs<=0)clearInterval(ctid);
  },1000);
  tid=setTimeout(()=>{doScan();scheduleNext();},secs*1000);
}

// ── Render ────────────────────────────────────────────────────────────────────
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
    const c=altColor(ac.altFt);
    const route=ac.origin&&ac.dest?ac.origin+' → '+ac.dest:ac.origin||ac.dest||'';
    return'<div class="ac-item'+(ac.isNew?' fresh':'')+'" onclick="reannounce(\''+ac.icao+'\')">'+
      '<div class="cs">'+cs+'</div>'+
      '<div class="ac-info"><div class="ac-airline">'+(ac.airline||'Private')+'</div>'+
      '<div class="ac-route">'+route+'</div></div>'+
      '<div class="'+c+' muted">'+alt+'</div>'+
      '<div class="muted">'+spd+'</div>'+
      '<div class="muted">'+(ac.dir||'')+'</div>'+
      '<div class="muted">'+(ac.distNm?ac.distNm+'nm':'')+'</div>'+
      '</div>';
  }).join('');
}

// ── Radar ─────────────────────────────────────────────────────────────────────
function drawRadar(list){
  const cv=document.getElementById('radar'),cx=cv.getContext('2d'),W=cv.width,c=W/2,r=c-4;
  cx.clearRect(0,0,W,W);
  cx.fillStyle='#050a0f';cx.beginPath();cx.arc(c,c,r,0,Math.PI*2);cx.fill();
  [.25,.5,.75,1].forEach(f=>{cx.beginPath();cx.arc(c,c,r*f,0,Math.PI*2);cx.strokeStyle='rgba(0,212,255,.12)';cx.lineWidth=1;cx.stroke();});
  cx.strokeStyle='rgba(0,212,255,.12)';cx.lineWidth=1;
  cx.beginPath();cx.moveTo(c,c-r);cx.lineTo(c,c+r);cx.stroke();
  cx.beginPath();cx.moveTo(c-r,c);cx.lineTo(c+r,c);cx.stroke();
  cx.save();cx.translate(c,c);cx.rotate(radarAngle);
  cx.beginPath();cx.moveTo(0,0);cx.arc(0,0,r,-Math.PI/2,-Math.PI/2+1.2);cx.closePath();cx.fillStyle='rgba(0,212,255,.06)';cx.fill();
  cx.beginPath();cx.moveTo(0,0);cx.lineTo(0,-r);cx.strokeStyle='rgba(0,212,255,.7)';cx.lineWidth=1.5;cx.stroke();
  cx.restore();
  cx.beginPath();cx.arc(c,c,3,0,Math.PI*2);cx.fillStyle='#00d4ff';cx.fill();
  const km=parseFloat(document.getElementById('radR').value)*1.852;
  (list||[]).forEach(ac=>{
    if(!ac.lat||!ac.lon)return;
    const ratio=Math.min(ac.distNm*1.852/km,1);
    const ang=Math.atan2(ac.lon-uLon,ac.lat-uLat);
    const bx=c+ratio*r*Math.sin(ang),by=c-ratio*r*Math.cos(ang);
    cx.beginPath();cx.arc(bx,by,3,0,Math.PI*2);
    const col=ac.altFt>25000?'#00d4ff':ac.altFt>5000?'#ffd700':'#ff6b35';
    cx.fillStyle=col;cx.shadowColor=col;cx.shadowBlur=6;cx.fill();cx.shadowBlur=0;
  });
  document.getElementById('rcount').textContent=(list?list.length:0)+' contact'+((list&&list.length!==1)?'s':'');
}
(function loop(){radarAngle+=scanning?.04:.015;drawRadar(scanning?[...known.values()]:[]);requestAnimationFrame(loop);})();

// ── Toast ─────────────────────────────────────────────────────────────────────
function showToast(ac,announced){
  const cs=(ac.callsign||ac.reg||ac.icao).trim();
  const route=ac.origin&&ac.dest?ac.origin+' → '+ac.dest:ac.origin||'';
  const ann=announced?'<br><span style="color:#39ff14;font-size:11px">🔊 '+announced+'</span>':'';
  document.getElementById('toastBody').innerHTML=
    '<b>'+cs+'</b> — '+(ac.airline||'Private')+'<br>'+
    (ac.type||'Aircraft')+' | '+(ac.altFt?ac.altFt.toLocaleString()+' ft':'N/A')+
    ' | '+(ac.dir||'')+' '+(ac.distNm?ac.distNm+'nm':'')+
    (route?'<br>✈ '+route:'')+ann;
  const t=document.getElementById('toast');t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),7000);
}

function reannounce(icao){
  const ac=known.get(icao);if(!ac)return;
  doAlert(ac);
}

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
  el.innerHTML='<span class="lt">'+now+'</span><span class="lx '+cls+'">'+html+'</span>';
  body.prepend(el);setTimeout(()=>el.classList.remove('new'),3000);
  while(body.children.length>60)body.removeChild(body.lastChild);
}
</script>
</body>
</html>"""

def main():
    print(f"\n  OVERFLY starting on port {PORT}\n", flush=True)
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  OVERFLY stopped.\n")

if __name__ == "__main__":
    main()
