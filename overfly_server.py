#!/usr/bin/env python3
"""OVERFLY - Live Aircraft Tracker"""

import json, math, os, sys, threading, time, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
import requests as req_lib

PORT = int(os.environ.get("PORT", 7477))

# ── Airline lookup (ICAO 3-letter prefix → name, category) ───────────────────
AIRLINES = {
    "UAL":("United Airlines","airline"),       "AAL":("American Airlines","airline"),
    "DAL":("Delta Air Lines","airline"),        "SWA":("Southwest Airlines","airline"),
    "FFT":("Frontier Airlines","airline"),      "JBU":("JetBlue Airways","airline"),
    "ASA":("Alaska Airlines","airline"),        "HAL":("Hawaiian Airlines","airline"),
    "SKW":("SkyWest Airlines","airline"),       "RPA":("Republic Airways","airline"),
    "ENY":("Envoy Air","airline"),              "PDT":("Piedmont Airlines","airline"),
    "PSA":("PSA Airlines","airline"),           "CPZ":("CommutAir","airline"),
    "GJS":("GoJet Airlines","airline"),         "VTE":("Contour Airlines","airline"),
    "LXJ":("Flexjet","charter"),               "EJA":("NetJets","charter"),
    "SBE":("Signature Flight","charter"),       "CXK":("FlightSafety","charter"),
    "WSJ":("World Jet","charter"),              "CLJ":("Clay Lacy","charter"),
    "USC":("US Customs & Border","government"), "SAM":("Special Air Mission","military"),
    "RCH":("US Air Force","military"),          "QPK":("Government Flight","government"),
    "LFN":("LifeFlight Network","medical"),     "LIF":("LifeFlight","medical"),
    "UPS":("UPS Airlines","cargo"),             "FDX":("FedEx Express","cargo"),
    "ABX":("ABX Air","cargo"),                  "GTI":("Atlas Air","cargo"),
    "CLX":("Cargolux","cargo"),                 "PAC":("Airborne Express","cargo"),
    "BAW":("British Airways","airline"),        "DLH":("Lufthansa","airline"),
    "AFR":("Air France","airline"),             "KLM":("KLM","airline"),
    "UAE":("Emirates","airline"),               "QFA":("Qantas","airline"),
    "ACA":("Air Canada","airline"),             "AMX":("Aeromexico","airline"),
    "WJA":("WestJet","airline"),               "VOI":("Volaris","airline"),
}

# ── Aircraft type lookup ──────────────────────────────────────────────────────
AIRCRAFT_TYPES = {
    "B738":"Boeing 737-800","B739":"Boeing 737-900","B37M":"Boeing 737 MAX 7",
    "B38M":"Boeing 737 MAX 8","B39M":"Boeing 737 MAX 9",
    "B744":"Boeing 747-400","B748":"Boeing 747-8",
    "B752":"Boeing 757-200","B753":"Boeing 757-300",
    "B762":"Boeing 767-200","B763":"Boeing 767-300","B764":"Boeing 767-400",
    "B772":"Boeing 777-200","B773":"Boeing 777-300","B77W":"Boeing 777-300ER",
    "B788":"Boeing 787-8","B789":"Boeing 787-9","B78X":"Boeing 787-10",
    "A19N":"Airbus A319neo","A20N":"Airbus A320neo","A21N":"Airbus A321neo",
    "A319":"Airbus A319","A320":"Airbus A320","A321":"Airbus A321",
    "A332":"Airbus A330-200","A333":"Airbus A330-300",
    "A359":"Airbus A350-900","A35K":"Airbus A350-1000","A388":"Airbus A380",
    "E135":"Embraer ERJ-135","E145":"Embraer ERJ-145",
    "E75L":"Embraer E175","E170":"Embraer E170","E190":"Embraer E190",
    "CRJ2":"Bombardier CRJ-200","CRJ7":"Bombardier CRJ-700","CRJ9":"Bombardier CRJ-900",
    "DH8D":"Bombardier Dash 8","ATR7":"ATR 72",
    "C25A":"Citation CJ2","C25B":"Citation CJ3","C25C":"Citation CJ4",
    "C56X":"Citation Excel","C680":"Citation Sovereign","C68A":"Citation Latitude",
    "C700":"Citation Longitude","C750":"Citation X",
    "CL30":"Challenger 300","CL35":"Challenger 350","CL60":"Challenger 600",
    "GL5T":"Global 5000","GL7T":"Global 7500","GLEX":"Global Express",
    "G280":"Gulfstream G280","G450":"Gulfstream G450","G550":"Gulfstream G550",
    "G600":"Gulfstream G600","G650":"Gulfstream G650",
    "F2TH":"Dassault Falcon 2000","F7X":"Dassault Falcon 7X","F900":"Dassault Falcon 900",
    "LJ35":"Learjet 35","LJ45":"Learjet 45","LJ60":"Learjet 60",
    "E545":"Embraer Legacy 450","E55P":"Embraer Phenom 300","PC12":"Pilatus PC-12",
    "C172":"Cessna Skyhawk","C182":"Cessna Skylane","C208":"Cessna Caravan",
    "C152":"Cessna 152","C177":"Cessna Cardinal","C210":"Cessna 210",
    "P28A":"Piper Cherokee","PA44":"Piper Seminole","P46T":"Piper Matrix",
    "BE35":"Beechcraft Bonanza","BE58":"Beechcraft Baron","BE9L":"Beechcraft King Air",
    "SR20":"Cirrus SR20","SR22":"Cirrus SR22","S22T":"Cirrus SR22T",
    "M20P":"Mooney M20","DA40":"Diamond DA40","DA42":"Diamond DA42",
    "AS50":"Airbus AS350 Helicopter","B06":"Bell 206 Helicopter",
    "B407":"Bell 407 Helicopter","EC35":"Airbus H135 Helicopter",
    "R44":"Robinson R44 Helicopter","S76":"Sikorsky S-76 Helicopter",
    "GLID":"Glider","DISC":"Glider","JS3E":"Sailplane","AS21":"Glider",
    "COL4":"Columbia 400","DHC6":"Twin Otter","UF13":"Ultralight",
}

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

def classify_flight(callsign, reg, ac_type):
    """Return (airline_name, category) for a flight."""
    cs = (callsign or "").strip().upper()
    # Try ICAO 3-letter prefix
    if len(cs) >= 3:
        prefix = re.match(r'^([A-Z]{3})\d', cs)
        if prefix:
            code = prefix.group(1)
            if code in AIRLINES:
                return AIRLINES[code]
    # Numeric-only or N-reg with no airline prefix = private
    if re.match(r'^N\d', cs) or re.match(r'^[A-Z]\d', cs):
        return (None, "private")
    # Registration-based callsign = private
    if cs == (reg or "").upper():
        return (None, "private")
    # Gliders / ultralights
    t = (ac_type or "").upper()
    if t in ("GLID","DISC","JS3E","AS21","UF13","GLID"):
        return (None, "glider")
    return (None, "private")

def get_route(callsign, session):
    """Try to fetch origin/destination from aviationapi.com"""
    cs = (callsign or "").strip()
    if not cs or len(cs) < 4:
        return None, None
    try:
        url = f"https://api.adsbdb.com/v0/callsign/{cs}"
        r = session.get(url, timeout=5)
        if r.status_code == 200:
            d = r.json()
            fp = d.get("response", {}).get("flightroute", {})
            if fp:
                orig = fp.get("origin", {})
                dest = fp.get("destination", {})
                orig_str = f"{orig.get('municipality','?')} ({orig.get('icao_code','?')})" if orig else None
                dest_str = f"{dest.get('municipality','?')} ({dest.get('icao_code','?')})" if dest else None
                return orig_str, dest_str
    except Exception:
        pass
    return None, None


# ── Airline name from callsign prefix ────────────────────────────────────────
AIRLINES = {
    "UAL":"United","DAL":"Delta","AAL":"American","SWA":"Southwest",
    "FFT":"Frontier","JBU":"JetBlue","ASA":"Alaska","SKW":"SkyWest",
    "RPA":"Republic","ENY":"Envoy","QXE":"Horizon","PDT":"Piedmont",
    "LXJ":"Flexjet","EJA":"NetJets","VJT":"VistaJet","VTE":"Contour",
    "CPZ":"Comair","TSC":"Air Transat","WJA":"WestJet","ACA":"Air Canada",
    "BAW":"British Airways","DLH":"Lufthansa","AFR":"Air France",
    "UAE":"Emirates","QFA":"Qantas","KLM":"KLM","IBE":"Iberia",
    "SWR":"Swiss","AUA":"Austrian","TAP":"TAP Air Portugal",
    "FDX":"FedEx","UPS":"UPS","ABX":"ABX Air","GTI":"Atlas Air",
    "CPT":"Capital Cargo","USB":"US Coachways","N":"Private",
    "LIFELN":"Life Flight","USC":"US Customs","CXK":"Private",
    "SBE":"Private","LYM":"Key Lime Air","QPK":"Unknown",
}

# ── Airport name from IATA/ICAO code ─────────────────────────────────────────
AIRPORTS = {
    "LAX":"Los Angeles","JFK":"New York","ORD":"Chicago","ATL":"Atlanta",
    "DFW":"Dallas","DEN":"Denver","SFO":"San Francisco","SEA":"Seattle",
    "LAS":"Las Vegas","PHX":"Phoenix","MIA":"Miami","BOS":"Boston",
    "IAH":"Houston","MCO":"Orlando","EWR":"Newark","MSP":"Minneapolis",
    "DTW":"Detroit","PHL":"Philadelphia","LGA":"New York","CLT":"Charlotte",
    "SLC":"Salt Lake City","BWI":"Baltimore","SAN":"San Diego","TPA":"Tampa",
    "MDW":"Chicago Midway","HNL":"Honolulu","PDX":"Portland","STL":"St Louis",
    "BNA":"Nashville","AUS":"Austin","OAK":"Oakland","MCI":"Kansas City",
    "RDU":"Raleigh","SJC":"San Jose","SMF":"Sacramento","IND":"Indianapolis",
    "CMH":"Columbus","PIT":"Pittsburgh","MEM":"Memphis","CLE":"Cleveland",
    "BDL":"Hartford","MKE":"Milwaukee","OMA":"Omaha","ORF":"Norfolk",
    "ABQ":"Albuquerque","TUL":"Tulsa","OKC":"Oklahoma City","ELP":"El Paso",
    "COS":"Colorado Springs","GJT":"Grand Junction","DRO":"Durango",
    "ASE":"Aspen","HDN":"Hayden","EGE":"Eagle","TEX":"Telluride",
    "APA":"Centennial","BJC":"Broomfield","FNL":"Fort Collins",
    "PUB":"Pueblo","LAA":"Lamar","ALS":"Alamosa","MTJ":"Montrose",
    "GUC":"Gunnison","SBS":"Steamboat Springs","HBU":"Buckley",
    "CDW":"Caldwell","LGB":"Long Beach","BUR":"Burbank","SNA":"Orange County",
    "ONT":"Ontario","PSP":"Palm Springs","FAT":"Fresno","RNO":"Reno",
    "TUS":"Tucson","GEG":"Spokane","BOI":"Boise","BZN":"Bozeman",
    "MSO":"Missoula","FCA":"Glacier","JAC":"Jackson Hole",
    "KDEN":"Denver","KCOS":"Colorado Springs","KAPA":"Centennial",
    "KBJC":"Broomfield","KFNL":"Fort Collins","KPUB":"Pueblo",
}

def airline_name(callsign):
    """Get friendly airline name from callsign."""
    if not callsign: return "Private"
    cs = callsign.strip().upper()
    # Try longest prefix match first
    for length in (6, 5, 4, 3):
        prefix = cs[:length]
        if prefix in AIRLINES:
            return AIRLINES[prefix]
    # Registration-style (starts with N) = private US
    if cs.startswith("N") and (len(cs) < 7 or not cs[1:4].isalpha()):
        return "Private"
    return "Private"

def origin_airport(callsign):
    """
    Look up flight origin from callsign via aviationstack-free or return None.
    We use a lightweight approach: query the FlightAware/AviationAPI if available,
    otherwise return None and skip the origin.
    """
    return None  # will be enriched async if possible

def announce_text(ac):
    """Build short announcement: 'Airline, Origin' or 'Private, Centennial'."""
    callsign = (ac.get("callsign") or "").strip()
    airline  = airline_name(callsign)
    origin   = ac.get("origin")  # may be None
    if origin:
        origin_name = AIRPORTS.get(origin.upper(), origin)
        return f"{airline}, {origin_name}"
    else:
        return airline

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
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
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
                reg      = (ac.get("r", "") or "").strip()
                callsign = (ac.get("flight", "") or reg or ac.get("hex", "")).strip()
                ac_type  = (ac.get("t", "") or "").strip()
                airline, category = classify_flight(callsign, reg, ac_type)
                type_full = AIRCRAFT_TYPES.get(ac_type.upper(), ac_type)

                # Fetch route (only for airline/cargo/charter flights, not private)
                origin, dest = None, None
                if category in ("airline", "cargo", "charter"):
                    origin, dest = get_route(callsign, session)

                aircraft.append({
                    "icao":     ac.get("hex",""),
                    "callsign": callsign,
                    "reg":      reg,
                    "type":     ac_type,
                    "typeFull": type_full,
                    "lat":      ac.get("lat"),
                    "lon":      ac.get("lon"),
                    "altFt":    int(alt) if isinstance(alt,(int,float)) else None,
                    "spdKt":    int(ac.get("gs",0)) if ac.get("gs") else None,
                    "country":  country_from_reg(reg),
                    "distNm":   round(haversine_nm(lat,lon,ac["lat"],ac["lon"]),1),
                    "dir":      bearing_label(lat,lon,ac["lat"],ac["lon"]),
                    "airline":  airline,
                    "category": category,
                    "origin":   origin,
                    "dest":     dest,
                })
            aircraft.sort(key=lambda a: a["altFt"] or 0, reverse=True)
            return aircraft
        except Exception as e:
            last_err = e
            continue
    raise Exception(f"All sources failed: {last_err}")

# ── Geocode zip ───────────────────────────────────────────────────────────────
def geocode_zip(zipcode):
    url = f"https://nominatim.openstreetmap.org/search?postalcode={zipcode}&country=US&format=json&limit=1"
    r = req_lib.get(url, headers={"User-Agent":"OVERFLY/2.0"}, timeout=8)
    r.raise_for_status()
    data = r.json()
    if not data: raise Exception(f"ZIP code {zipcode} not found")
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0]["display_name"].split(",")[0]

# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path in ("/","/index.html"):
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type","text/html")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == "/scan":
            try:
                lat    = float(qs.get("lat",[0])[0])
                lon    = float(qs.get("lon",[0])[0])
                radius = int(qs.get("radius",[10])[0])
                aircraft = fetch_aircraft(lat, lon, radius)
                self.send_json({"ok":True,"aircraft":aircraft,"count":len(aircraft)})
            except Exception as e:
                self.send_json({"ok":False,"error":str(e)},500)

        elif parsed.path == "/geocode":
            try:
                zipcode = qs.get("zip",[""])[0]
                lat, lon, name = geocode_zip(zipcode)
                self.send_json({"ok":True,"lat":lat,"lon":lon,"name":name})
            except Exception as e:
                self.send_json({"ok":False,"error":str(e)},500)

        else:
            self.send_response(404); self.end_headers()

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
  .wrap{max-width:1100px;margin:0 auto;padding:16px;position:relative;}
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
  .btns{display:flex;gap:8px;}
  .main{display:grid;grid-template-columns:200px 1fr;gap:16px;margin-bottom:16px;}
  .radar-wrap{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:14px;display:flex;flex-direction:column;align-items:center;gap:8px;}
  .rl{font-family:'Share Tech Mono',monospace;font-size:10px;color:var(--muted);letter-spacing:2px;}
  canvas{border-radius:50%;}
  .ac-panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;overflow:hidden;display:flex;flex-direction:column;}
  .ph{display:flex;align-items:center;justify-content:space-between;padding:11px 16px;border-bottom:1px solid var(--border);background:rgba(0,212,255,.04);}
  .pt{font-family:'Orbitron',monospace;font-size:11px;letter-spacing:3px;color:var(--accent);}
  .badge{background:rgba(0,212,255,.12);border:1px solid var(--accent);color:var(--accent);font-family:'Orbitron',monospace;font-size:12px;padding:2px 10px;border-radius:10px;}
  .ac-list{overflow-y:auto;flex:1;max-height:340px;}
  .ac-item{padding:10px 16px;border-bottom:1px solid rgba(26,58,92,.4);cursor:pointer;transition:background .15s;}
  .ac-item:hover{background:rgba(0,212,255,.05);}
  .ac-item.fresh{animation:flashin 1.5s ease;}
  @keyframes flashin{0%{background:rgba(57,255,20,.15);}100%{background:transparent;}}
  .ac-row1{display:flex;align-items:center;gap:10px;margin-bottom:4px;}
  .cs{font-family:'Orbitron',monospace;font-size:13px;font-weight:700;color:var(--accent);}
  .cat-badge{font-family:'Share Tech Mono',monospace;font-size:9px;padding:2px 6px;border-radius:3px;text-transform:uppercase;letter-spacing:1px;}
  .cat-airline{background:rgba(0,212,255,.15);color:var(--accent);border:1px solid rgba(0,212,255,.3);}
  .cat-cargo{background:rgba(255,107,53,.15);color:var(--accent2);border:1px solid rgba(255,107,53,.3);}
  .cat-charter{background:rgba(255,215,0,.12);color:#ffd700;border:1px solid rgba(255,215,0,.3);}
  .cat-private{background:rgba(74,127,165,.15);color:var(--muted);border:1px solid rgba(74,127,165,.3);}
  .cat-military{background:rgba(57,255,20,.12);color:var(--green);border:1px solid rgba(57,255,20,.3);}
  .cat-medical{background:rgba(255,51,85,.15);color:var(--danger);border:1px solid rgba(255,51,85,.3);}
  .cat-glider{background:rgba(74,127,165,.1);color:var(--muted);border:1px solid rgba(74,127,165,.2);}
  .ac-row2{display:flex;gap:16px;flex-wrap:wrap;align-items:center;}
  .info-chip{font-family:'Share Tech Mono',monospace;font-size:10px;color:var(--muted);}
  .info-chip b{color:var(--text);}
  .route-str{font-family:'Share Tech Mono',monospace;font-size:10px;color:#ffd700;}
  .alt-hi{color:var(--accent);} .alt-md{color:#ffd700;} .alt-lo{color:var(--accent2);}
  .empty{padding:40px;text-align:center;color:var(--muted);font-family:'Share Tech Mono',monospace;}
  .log-panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;overflow:hidden;}
  .log-body{max-height:130px;overflow-y:auto;padding:4px 0;}
  .le{display:flex;gap:10px;padding:6px 16px;font-family:'Share Tech Mono',monospace;font-size:11px;border-left:2px solid transparent;}
  .le.new{border-left-color:var(--accent);background:rgba(0,212,255,.04);}
  .lt{color:var(--muted);flex-shrink:0;} .lx{color:var(--text);} .lx b{color:var(--accent);}
  .lx.ok{color:var(--green);} .lx.err{color:var(--danger);}
  #toast{position:fixed;bottom:20px;right:20px;background:var(--panel);border:1px solid var(--accent);border-radius:10px;padding:13px 18px;max-width:340px;z-index:999;transform:translateY(140%);transition:transform .4s cubic-bezier(.34,1.56,.64,1);box-shadow:0 0 30px rgba(0,212,255,.2);}
  #toast.show{transform:translateY(0);}
  .th{font-family:'Orbitron',monospace;font-size:10px;color:var(--accent);letter-spacing:2px;margin-bottom:5px;}
  .tb{font-size:12px;line-height:1.7;}
  #countdown{font-family:'Orbitron',monospace;font-size:11px;color:var(--muted);padding:0 6px;}
  @media(max-width:640px){.main{grid-template-columns:1fr;}.ac-row2{gap:8px;}}
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
  if(!window.speechSynthesis||muted)return;
  speechSynthesis.cancel();
  const u=new SpeechSynthesisUtterance(text);
  u.rate=0.92;u.pitch=1.0;u.volume=1.0;
  speechSynthesis.speak(u);
}

function buildAnnouncement(ac){
  const cs  = ac.callsign||ac.reg||ac.icao;
  const alt = ac.altFt ? ac.altFt.toLocaleString()+' feet' : 'unknown altitude';
  const cat = ac.category||'private';

  if(cat==='private'||cat==='glider'){
    const tf = ac.typeFull||ac.type||'aircraft';
    return `Private ${tf}, registration ${ac.reg||cs}, at ${alt}`;
  }
  let msg = cs;
  if(ac.airline) msg += `, ${ac.airline}`;
  if(ac.typeFull||ac.type) msg += `, ${ac.typeFull||ac.type}`;
  if(ac.origin && ac.dest)       msg += `, flying from ${ac.origin} to ${ac.dest}`;
  else if(ac.origin)             msg += `, from ${ac.origin}`;
  else if(ac.dest)               msg += `, to ${ac.dest}`;
  msg += `, at ${alt}`;
  return msg;
}

function doAlert(ac){
  if(muted)return;
  const mode=document.getElementById('alertSel').value;
  if(mode==='ding'||mode==='both') playDing();
  if(mode==='voice'||mode==='both') playVoice(buildAnnouncement(ac));
  showToast(ac);
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
  } else if(mode==='gps'){
    document.getElementById('locVal').textContent='Requesting GPS...';
    document.getElementById('locSub').textContent='';
    if(!navigator.geolocation){
      document.getElementById('locVal').textContent='⚠ GPS not available';return;
    }
    navigator.geolocation.getCurrentPosition(
      p=>{
        uLat=p.coords.latitude;uLon=p.coords.longitude;
        document.getElementById('locVal').textContent=uLat.toFixed(4)+'°N, '+Math.abs(uLon).toFixed(4)+'°W — GPS Locked';
        document.getElementById('locSub').textContent='Accuracy: ±'+Math.round(p.coords.accuracy)+'m';
        addLog('GPS locked: '+uLat.toFixed(4)+', '+uLon.toFixed(4));
      },
      ()=>{document.getElementById('locVal').textContent='⚠ GPS blocked — try ZIP tab';},
      {timeout:10000}
    );
  } else if(mode==='zip'){
    document.getElementById('locVal').textContent='Enter ZIP code below';
    document.getElementById('locSub').textContent='';
  } else if(mode==='coords'){
    document.getElementById('locVal').textContent='Enter coordinates below';
    document.getElementById('locSub').textContent='';
  }
}

async function lookupZip(){
  const zip=document.getElementById('zipIn').value.trim();
  if(!zip||zip.length<5)return;
  const st=document.getElementById('zipStatus');st.textContent='Looking up...';
  try{
    const r=await fetch('/geocode?zip='+zip);
    const d=await r.json();
    if(!d.ok)throw new Error(d.error);
    uLat=d.lat;uLon=d.lon;
    document.getElementById('locVal').textContent=uLat.toFixed(4)+'°N, '+Math.abs(uLon).toFixed(4)+'°W';
    document.getElementById('locSub').textContent=d.name;
    st.textContent='✓ '+d.name;
    addLog('ZIP lookup: <b>'+zip+'</b> → '+d.name);
  }catch(e){st.textContent='⚠ '+e.message;}
}

function setManualCoords(){
  const lat=parseFloat(document.getElementById('latIn').value);
  const lon=parseFloat(document.getElementById('lonIn').value);
  if(isNaN(lat)||isNaN(lon)){addLog('⚠ Invalid coordinates','err');return;}
  uLat=lat;uLon=lon;
  document.getElementById('locVal').textContent=lat.toFixed(4)+'°, '+Math.abs(lon).toFixed(4)+'° — Set';
  document.getElementById('locSub').textContent='';
  addLog('Manual coords set');
}

// ── Scan ──────────────────────────────────────────────────────────────────────
async function doScan(){
  if(!uLat||!uLon){addLog('⚠ No location set','err');return;}
  setStatus('scan');
  try{
    const radius=parseInt(document.getElementById('radR').value);
    const res=await fetch(`/scan?lat=${uLat}&lon=${uLon}&radius=${radius}`);
    const data=await res.json();
    if(!data.ok)throw new Error(data.error||'Unknown error');
    const cur=new Map();
    for(const ac of data.aircraft){ac.isNew=!known.has(ac.icao);cur.set(ac.icao,ac);}
    for(const ac of [...cur.values()].filter(a=>a.isNew)){
      doAlert(ac);
      const cs=ac.callsign||ac.reg||ac.icao;
      const route=ac.origin&&ac.dest?` ${ac.origin}→${ac.dest}`:ac.origin?` from ${ac.origin}`:'';
      addLog(`<b>${cs}</b> ${ac.airline||catLabel(ac.category)} ${ac.typeFull||ac.type||''}${route} — ${ac.altFt?ac.altFt.toLocaleString()+'ft':'?'}`, 'ok');
      await new Promise(r=>setTimeout(r,800));
    }
    known=cur;
    renderList([...cur.values()]);
    addLog('Scan complete: '+data.count+' contacts');
    setStatus('live');
  }catch(e){addLog('⚠ '+e.message,'err');setStatus('err');}
}

function catLabel(cat){
  const m={airline:'',cargo:'Cargo',charter:'Charter',private:'Private',military:'Military',medical:'Medical',glider:'Glider'};
  return m[cat]||'';
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
  ctid=setInterval(()=>{secs--;document.getElementById('countdown').textContent='next: '+secs+'s';if(secs<=0)clearInterval(ctid);},1000);
  tid=setTimeout(()=>{doScan();scheduleNext();},secs*1000);
}

// ── Render ────────────────────────────────────────────────────────────────────
function altColor(ft){if(!ft)return'';if(ft>25000)return'alt-hi';if(ft>5000)return'alt-md';return'alt-lo';}

function catBadge(cat){
  const labels={airline:'✈ Airline',cargo:'📦 Cargo',charter:'💼 Charter',
    private:'🔒 Private',military:'🎖 Military',medical:'🚑 Medical',glider:'🪂 Glider'};
  return `<span class="cat-badge cat-${cat||'private'}">${labels[cat]||'Private'}</span>`;
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
    const routeStr=ac.origin&&ac.dest
      ?`<span class="route-str">✈ ${ac.origin} → ${ac.dest}</span>`
      :ac.origin?`<span class="route-str">from ${ac.origin}</span>`
      :ac.dest?`<span class="route-str">to ${ac.dest}</span>`:'';
    const airlineStr=ac.airline?`<span class="info-chip"><b>${ac.airline}</b></span>`:'';
    const typeStr=ac.typeFull||ac.type?`<span class="info-chip">${ac.typeFull||ac.type}</span>`:'';
    return`<div class="ac-item${ac.isNew?' fresh':''}" onclick="reannounce('${ac.icao}')">
      <div class="ac-row1">
        <div class="cs">${cs}</div>
        ${catBadge(ac.category)}
        ${airlineStr}
        <div class="${ac_} info-chip" style="margin-left:auto"><b>${alt}</b></div>
      </div>
      <div class="ac-row2">
        ${typeStr}
        ${routeStr}
        <span class="info-chip">${spd}</span>
        <span class="info-chip">${ac.dir||''} ${ac.distNm?ac.distNm+'nm':''}</span>
      </div>
    </div>`;
  }).join('');
}

// ── Radar ─────────────────────────────────────────────────────────────────────
function drawRadar(list){
  const cv=document.getElementById('radar'),cx=cv.getContext('2d'),W=cv.width,c=W/2,r=c-4;
  cx.clearRect(0,0,W,W);cx.fillStyle='#050a0f';cx.beginPath();cx.arc(c,c,r,0,Math.PI*2);cx.fill();
  [.25,.5,.75,1].forEach(f=>{cx.beginPath();cx.arc(c,c,r*f,0,Math.PI*2);cx.strokeStyle='rgba(0,212,255,.12)';cx.lineWidth=1;cx.stroke();});
  cx.strokeStyle='rgba(0,212,255,.12)';cx.lineWidth=1;
  cx.beginPath();cx.moveTo(c,c-r);cx.lineTo(c,c+r);cx.stroke();
  cx.beginPath();cx.moveTo(c-r,c);cx.lineTo(c+r,c);cx.stroke();
  cx.save();cx.translate(c,c);cx.rotate(radarAngle);
  cx.beginPath();cx.moveTo(0,0);cx.arc(0,0,r,-Math.PI/2,-Math.PI/2+1.2);cx.closePath();cx.fillStyle='rgba(0,212,255,.06)';cx.fill();
  cx.beginPath();cx.moveTo(0,0);cx.lineTo(0,-r);cx.strokeStyle='rgba(0,212,255,.7)';cx.lineWidth=1.5;cx.stroke();
  cx.restore();cx.beginPath();cx.arc(c,c,3,0,Math.PI*2);cx.fillStyle='#00d4ff';cx.fill();
  const km=parseFloat(document.getElementById('radR').value)*1.852;
  (list||[]).forEach(ac=>{
    if(!ac.lat||!ac.lon)return;
    const ratio=Math.min(ac.distNm*1.852/km,1),ang=Math.atan2(ac.lon-uLon,ac.lat-uLat);
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
  const ann=announced?'<br><span style="color:#39ff14;font-size:11px">🔊 '+announced+'</span>':'';
  document.getElementById('toastBody').innerHTML=
    '<b>'+cs+'</b> — '+(ac.type||'Aircraft')+'<br>Alt: '+(ac.altFt?ac.altFt.toLocaleString()+' ft':'N/A')+' | '+(ac.dir||'')+' '+(ac.distNm?ac.distNm+'nm':'')+ann;
  const t=document.getElementById('toast');t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),7000);
}

function reannounce(icao){
  const ac=known.get(icao);if(!ac)return;doAlert(ac);
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
  el.innerHTML=`<span class="lt">${now}</span><span class="lx ${cls}">${html}</span>`;
  body.prepend(el);setTimeout(()=>el.classList.remove('new'),3000);
  while(body.children.length>60)body.removeChild(body.lastChild);
}
</script>
</body>
</html>"""

def main():
    print(f"\n  ✈  OVERFLY starting on port {PORT}\n", flush=True)
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"  Serving on port {PORT}\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  OVERFLY stopped.\n")

if __name__ == "__main__":
    main()
