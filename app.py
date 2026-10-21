import os, json, time, threading, re, urllib.request, urllib.parse, html, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

VERSION = '1.7.2'
BASE = Path(__file__).resolve().parent

URLS = {
    'enfen': 'https://enfen.imarpe.gob.pe/downloads/comunicados/',
    'noaa': 'https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for',
    'indeci': 'https://geosinpad.indeci.gob.pe/indeci/rest/services/Emergencias/EMERGENCIAS_SINPAD/MapServer/0/query',
    'gdacs': 'https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH',
    'forecast': 'https://api.open-meteo.com/v1/forecast',
}
TTL = {'enfen': 3600, 'noaa': 21600, 'indeci': 21600, 'gdacs': 1800, 'news': 3600, 'forecast': 3600, 'rain': 3600}

# name, lat, lon
REGIONS = {
    'tumbes': ('Tumbes', -3.57, -80.46),
    'piura': ('Piura', -5.19, -80.63),
    'chiclayo': ('Chiclayo', -6.77, -79.84),
    'trujillo': ('Trujillo', -8.11, -79.03),
    'chimbote': ('Chimbote', -9.07, -78.59),
    'lima': ('Lima', -12.05, -77.04),
    'ica': ('Ica', -14.07, -75.73),
    'arequipa': ('Arequipa', -16.40, -71.54),
    'huancayo': ('Huancayo', -12.07, -75.21),
    'cusco': ('Cusco', -13.53, -71.97),
    'puno': ('Puno', -15.84, -70.02),
    'iquitos': ('Iquitos', -3.75, -73.25),
}

CACHE = {}
LOCK = threading.RLock()


def fetch(url, limit=3_000_000, timeout=15):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'ObservatorioNinoPeru/' + VERSION + ' (public data monitoring)',
        'Accept': 'application/json,text/plain,text/html,application/xml,*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit)


def cached(key, loader, ttl):
    now = time.time()
    with LOCK:
        old = CACHE.get(key)
        # Failed lookups are retried after 5 minutes instead of waiting the full TTL
        if old and now - old['checked_epoch'] < (ttl if old['status'] == 'ok' else min(ttl, 300)):
            return old
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        result = {'status': 'ok', 'data': loader(), 'checked_epoch': now, 'checked_at': stamp, 'stale': False}
    except Exception as e:
        result = {'status': 'error', 'error': str(e)[:220], 'checked_epoch': now, 'checked_at': stamp,
                  'stale': bool(old and old.get('data'))}
        if old and old.get('data'):
            result['data'] = old['data']
    with LOCK:
        CACHE[key] = result
    return result


def get_enfen():
    page = fetch(URLS['enfen']).decode('utf-8', 'replace')
    out = []
    for attrs, inside in re.findall(r'<a\b([^>]*)>(.*?)</a>', page, re.I | re.S):
        title = re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', inside))).strip()
        if not re.search(r'comunicado\s+oficial|enfen\s+n[°ºo.]', title, re.I):
            continue
        m = re.search(r'href\s*=\s*["\']([^"\']+)', attrs, re.I)
        url = urllib.parse.urljoin(URLS['enfen'], html.unescape(m.group(1))) if m else URLS['enfen']
        if urllib.parse.urlsplit(url).scheme not in ('https', 'http'):
            url = URLS['enfen']
        if title and not any(x['title'] == title for x in out):
            out.append({'title': title, 'url': url})
    if not out:
        raise ValueError('No se encontraron comunicados en la página de ENFEN')
    return {'items': out[:12], 'source_url': URLS['enfen']}


def get_noaa():
    raw = fetch(URLS['noaa'], limit=2_000_000, timeout=20)
    rows = []
    for line in raw.decode('utf-8', 'replace').splitlines():
        # Format: 02SEP1981     20.6-0.1     24.8-0.1     26.5-0.2     28.3-0.3
        # Columns are fixed width, so a negative anomaly sticks to the SST ("20.6-0.1").
        m = re.match(r'^\s*(\d{2}[A-Za-z]{3}\d{4})\s+(.+)$', line)
        if not m:
            continue
        try:
            date = datetime.strptime(m.group(1), '%d%b%Y').date().isoformat()
            nums = [float(x) for x in re.findall(r'-?\d+\.\d+', m.group(2))[:8]]
        except ValueError:
            continue
        if len(nums) != 8:
            continue
        rows.append({'date': date, 'sst12': nums[0], 'nino12': nums[1], 'sst34': nums[4], 'nino34': nums[5]})
    if not rows:
        raise ValueError('NOAA respondió pero no se reconocieron datos semanales')
    rows.sort(key=lambda x: x['date'])
    return {'series': rows[-52:], 'latest': rows[-1], 'all': rows, 'source_url': URLS['noaa']}


def get_indeci_latest():
    # INDECI's public GIS layer is not updated continuously; report the date of its newest record.
    params = {'where': '1=1', 'outFields': 'FECHA', 'orderByFields': 'FECHA DESC',
              'resultRecordCount': '1', 'returnGeometry': 'false', 'f': 'json'}
    obj = json.loads(fetch(URLS['indeci'] + '?' + urllib.parse.urlencode(params), timeout=20))
    if obj.get('error'):
        raise ValueError('ArcGIS: ' + str(obj['error'].get('message', 'error')))
    feats = obj.get('features') or []
    if not feats:
        raise ValueError('INDECI no devolvió registros')
    stamp = float(feats[0]['attributes']['FECHA'])
    stamp = stamp / 1000 if stamp > 1e11 else stamp
    return {'latest_record': datetime.fromtimestamp(stamp, timezone.utc).date().isoformat(),
            'source_url': 'https://portal.indeci.gob.pe/'}


GDACS_TYPES = {'EQ': 'Sismo', 'FL': 'Inundación', 'TC': 'Ciclón tropical', 'VO': 'Volcán',
               'DR': 'Sequía', 'WF': 'Incendio forestal', 'TS': 'Tsunami'}


def get_gdacs():
    today = datetime.now(timezone.utc).date()
    params = {'eventlist': 'EQ;FL;TC;VO;DR;WF', 'fromDate': (today - timedelta(days=60)).isoformat(),
              'toDate': today.isoformat(), 'alertlevel': 'Green;Orange;Red', 'country': 'Peru'}
    url = URLS['gdacs'] + '?' + urllib.parse.urlencode(params, safe=';')
    raw = fetch(url, limit=5_000_000, timeout=20)
    obj = json.loads(raw) if raw.strip() else {'features': []}
    events = []
    for f in obj.get('features') or []:
        p = f.get('properties') or {}
        coords = (f.get('geometry') or {}).get('coordinates') or []
        if len(coords) < 2 or not all(isinstance(v, (int, float)) for v in coords[:2]):
            continue
        sev = p.get('severitydata') or {}
        report = (p.get('url') or {}).get('report') or 'https://www.gdacs.org/'
        events.append({
            'type': GDACS_TYPES.get(p.get('eventtype'), p.get('eventtype') or 'Evento'),
            'code': p.get('eventtype'),
            'name': p.get('name') or '',
            'alert': (p.get('alertlevel') or '').lower(),
            'date': (p.get('fromdate') or '')[:10],
            'detail': sev.get('severitytext') or '',
            'lon': coords[0], 'lat': coords[1],
            'url': report if report.startswith('https://') else 'https://www.gdacs.org/',
        })
    events.sort(key=lambda e: e['date'], reverse=True)
    return {'events': events, 'days': 60, 'source_url': 'https://www.gdacs.org/'}


def get_news():
    q = urllib.parse.quote('fenómeno El Niño Perú lluvias SENAMHI ENFEN when:14d')
    url = 'https://news.google.com/rss/search?q=' + q + '&hl=es-419&gl=PE&ceid=PE:es-419'
    root = ET.fromstring(fetch(url, limit=1_000_000))
    items = []
    for node in root.findall('./channel/item')[:12]:
        title = (node.findtext('title') or '').strip()
        link = (node.findtext('link') or '').strip()
        pub = (node.findtext('pubDate') or '').strip()
        publisher = (node.findtext('source') or '').strip()
        if not title or not link.startswith('https://'):
            continue
        if publisher and title.endswith(' - ' + publisher):
            title = title[:-(len(publisher) + 3)]
        items.append({'title': title, 'url': link, 'publisher': publisher or 'Medio de prensa', 'published': pub})
    if not items:
        raise ValueError('Sin noticias en el RSS')
    return {'items': items[:7]}


def get_forecast(region):
    name, lat, lon = REGIONS[region]
    params = {'latitude': lat, 'longitude': lon,
              'daily': 'precipitation_sum,temperature_2m_max,temperature_2m_min',
              'timezone': 'America/Lima', 'forecast_days': 7}
    d = json.loads(fetch(URLS['forecast'] + '?' + urllib.parse.urlencode(params))).get('daily', {})
    if not d.get('time'):
        raise ValueError('Pronóstico no disponible')
    return {'region': region, 'name': name, 'daily': d}


def get_rain_map():
    # Total rain forecast for the next 3 days per city. One multi-location Open-Meteo call;
    # if that fails, fall back to the per-city 7-day forecasts (cached and shared with the forecast panel).
    keys = list(REGIONS)
    out = []
    try:
        params = {'latitude': ','.join(str(REGIONS[k][1]) for k in keys),
                  'longitude': ','.join(str(REGIONS[k][2]) for k in keys),
                  'daily': 'precipitation_sum', 'timezone': 'America/Lima', 'forecast_days': 3}
        data = json.loads(fetch(URLS['forecast'] + '?' + urllib.parse.urlencode(params)))
        if isinstance(data, dict):
            data = [data]
        if len(data) != len(keys):
            raise ValueError('Respuesta incompleta de Open-Meteo')
        dailies = [(loc.get('daily') or {}).get('precipitation_sum') or [] for loc in data]
    except Exception:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            res = list(ex.map(lambda k: cached('forecast:' + k, lambda: get_forecast(k), TTL['forecast']), keys))
        dailies = [((r.get('data') or {}).get('daily') or {}).get('precipitation_sum', [])[:3] if r.get('data') else None for r in res]
        if all(d is None for d in dailies):
            raise ValueError('Open-Meteo no respondió')
    for k, vals in zip(keys, dailies):
        if vals is None:
            continue
        name, lat, lon = REGIONS[k]
        nums = [v for v in vals if isinstance(v, (int, float))]
        out.append({'id': k, 'name': name, 'lat': lat, 'lon': lon, 'rain_3d': round(sum(nums), 1)})
    return {'cities': out, 'days': 3}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE), **kwargs)

    def send_json(self, data, code=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    MCP_405 = ('<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
               '<title>Servidor MCP · Observatorio El Niño · Perú</title>'
               '<body style="font:16px/1.6 system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 18px;background:#0b1522;color:#eef4fb">'
               '<h1 style="font-size:22px">Servidor MCP del Observatorio El Niño · Perú</h1>'
               '<p>Esta dirección no se abre en el navegador: es un servidor <b>MCP</b> para asistentes de IA. '
               'Para usarlo, agrégala como <b>conector personalizado</b> en tu asistente (por ejemplo, en Claude: Configuración → Conectores → Agregar conector personalizado) '
               'con esta URL:</p><p><code style="background:#18293f;padding:4px 8px;border-radius:4px">https://observatorio-nino-peru.onrender.com/mcp</code></p>'
               '<p>Herramientas disponibles: estado de El Niño esta semana, serie semanal del mar desde 1981, pronóstico por ciudad, lluvia esperada, '
               'emergencias recientes (GDACS) y comunicados de ENFEN.</p>'
               '<p><a style="color:#5fd3e4" href="/">Ir al dashboard del observatorio</a></p></body></html>').encode()

    def send_mcp_405(self):
        # Status stays 405 (correct for MCP clients); the body explains it to people and AI browsers.
        self.send_response(405)
        self.send_header('Allow', 'POST, OPTIONS')
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(self.MCP_405)))
        self.end_headers()
        self.wfile.write(self.MCP_405)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        p = path.path
        if p == '/api/status':
            noaa = dict(cached('noaa', get_noaa, TTL['noaa']))
            if noaa.get('data'):  # the full history is for MCP; the page only needs the last year
                noaa['data'] = {k: v for k, v in noaa['data'].items() if k != 'all'}
            return self.send_json({'sources': {
                'noaa': noaa,
                'enfen': cached('enfen', get_enfen, TTL['enfen']),
                'gdacs': cached('gdacs', get_gdacs, TTL['gdacs']),
                'indeci': cached('indeci', get_indeci_latest, TTL['indeci']),
                'news': cached('news', get_news, TTL['news']),
            }, 'server_time': datetime.now(timezone.utc).isoformat()})
        if p == '/api/rain-map':
            return self.send_json(cached('rain', get_rain_map, TTL['rain']))
        if p == '/api/forecast':
            region = urllib.parse.parse_qs(path.query).get('region', ['lima'])[0]
            if region not in REGIONS:
                return self.send_json({'error': 'Región no admitida'}, 400)
            return self.send_json(cached('forecast:' + region, lambda: get_forecast(region), TTL['forecast']))
        if p == '/api/health':
            return self.send_json({'status': 'ok', 'version': VERSION, 'server_time': datetime.now(timezone.utc).isoformat()})
        if p == '/mcp':
            # 2026-07-28 removed the GET stream; older clients probing it get 405 too.
            return self.send_mcp_405()
        if p in ('/app.py', '/render.yaml', '/mcp_server.py'):
            return self.send_error(404)
        return super().do_GET()


    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path != '/mcp':
            return self.send_error(404)
        import mcp_server
        mcp_server.handle_post(self)

    def do_DELETE(self):
        if urllib.parse.urlsplit(self.path).path == '/mcp':
            return self.send_mcp_405()
        self.send_error(404)

    def do_OPTIONS(self):
        if urllib.parse.urlsplit(self.path).path != '/mcp':
            return self.send_error(404)
        import mcp_server
        mcp_server.handle_options(self)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    print('Observatorio', VERSION, 'en puerto', port, flush=True)
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
