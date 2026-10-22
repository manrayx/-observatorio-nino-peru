import os, json, time, threading, re, urllib.request, urllib.parse, html, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

VERSION = '2.0'
BRAND = 'Monitor El Niño · Grupo Evidencia'
BASE = Path(__file__).resolve().parent

URLS = {
    'enfen': 'https://enfen.imarpe.gob.pe/downloads/comunicados/',
    'noaa': 'https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for',
    'indeci': 'https://geosinpad.indeci.gob.pe/indeci/rest/services/Emergencias/EMERGENCIAS_SINPAD/MapServer/0/query',
    'gdacs': 'https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH',
    'forecast': 'https://api.open-meteo.com/v1/forecast',
    'ensemble': 'https://ensemble-api.open-meteo.com/v1/ensemble',
}
TTL = {'enfen': 3600, 'noaa': 21600, 'indeci': 21600, 'gdacs': 1800, 'news': 3600,
       'forecast': 3600, 'rain': 3600, 'ens': 10800}

# id: (name, lat, lon, zone)
REGIONS = {
    'tumbes': ('Tumbes', -3.57, -80.46, 'costa_norte'),
    'piura': ('Piura', -5.19, -80.63, 'costa_norte'),
    'chiclayo': ('Chiclayo', -6.77, -79.84, 'costa_norte'),
    'trujillo': ('Trujillo', -8.11, -79.03, 'costa_norte'),
    'chimbote': ('Chimbote', -9.07, -78.59, 'costa_centro'),
    'lima': ('Lima', -12.05, -77.04, 'costa_centro'),
    'ica': ('Ica', -14.07, -75.73, 'costa_centro'),
    'arequipa': ('Arequipa', -16.40, -71.54, 'sierra_sur'),
    'huancayo': ('Huancayo', -12.07, -75.21, 'sierra_centro'),
    'cusco': ('Cusco', -13.53, -71.97, 'sierra_sur'),
    'puno': ('Puno', -15.84, -70.02, 'sierra_sur'),
    'iquitos': ('Iquitos', -3.75, -73.25, 'amazonia'),
}
ZONES = {'costa_norte': 'Costa norte', 'costa_centro': 'Costa centro', 'sierra_centro': 'Sierra centro',
         'sierra_sur': 'Sierra sur', 'amazonia': 'Amazonía'}

# Large past El Niño events used for comparison (windows around the Niño 1+2 peak)
EPISODES = [('1983', '1982-09-01', '1983-08-31'), ('1998', '1997-04-01', '1998-08-31'),
            ('2017', '2017-01-01', '2017-06-30'), ('2023', '2023-02-01', '2024-03-31')]

CACHE = {}
LOCK = threading.RLock()


def fetch(url, limit=3_000_000, timeout=15):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'MonitorElNino/' + VERSION + ' (public data monitoring; Grupo Evidencia)',
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


def percentile(vals, q):
    s = sorted(vals)
    if not s:
        return None
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 1)


# ---------------------------------------------------------------- official data (hand-transcribed)
def get_oficial():
    """ENFEN statements transcribed by hand into oficial.json (edit that file when a new communiqué comes out)."""
    try:
        with open(BASE / 'oficial.json', encoding='utf-8') as f:
            data = json.load(f)
        return {'status': 'ok', 'data': data}
    except Exception as e:
        return {'status': 'error', 'error': 'oficial.json: ' + str(e)[:160]}


# ---------------------------------------------------------------- ENFEN communiqué list
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


# ---------------------------------------------------------------- NOAA weekly sea temperature
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
    return {'series': rows[-52:], 'latest': rows[-1], 'all': rows, 'insights': noaa_insights(rows),
            'source_url': URLS['noaa']}


def class12(v):
    # ICEN scale used by ENFEN (applied here to the weekly value, as a reference)
    if v > 3.0: return 'extraordinario'
    if v > 1.7: return 'fuerte'
    if v > 1.0: return 'moderado'
    if v > 0.4: return 'débil'
    if v >= -1.0: return 'normal'
    return 'frío'


def episode_peaks(rows):
    out = []
    for name, a, b in EPISODES:
        win = [r for r in rows if a <= r['date'] <= b]
        if win:
            pk = max(win, key=lambda r: r['nino12'])
            out.append({'nombre': name, 'pico_nino12': pk['nino12'], 'semana': pk['date']})
    return out


def noaa_insights(rows):
    """Facts the pages use to write headlines: streaks, changes, records and past events (Niño 1+2)."""
    v = [r['nino12'] for r in rows]
    cur, cat = v[-1], class12(v[-1])
    streak = 0
    for x in reversed(v):
        if class12(x) != cat:
            break
        streak += 1
    # Most recent earlier week that was at least as warm (None = warmest of the whole series).
    higher_since = None
    for r in reversed(rows[:-1]):
        if r['nino12'] >= cur:
            higher_since = r['date']
            break
    return {
        'categoria': cat, 'racha_semanas': streak,
        'categoria_anterior': class12(v[-2]) if len(v) > 1 else cat,
        'cambio_1_semana': round(cur - v[-2], 2) if len(v) > 1 else 0,
        'cambio_4_semanas': round(cur - v[-5], 2) if len(v) > 4 else 0,
        'igual_o_mayor_desde': higher_since,          # None = highest of the whole series
        'serie_desde': rows[0]['date'],
        'nino34': rows[-1]['nino34'],
        'episodios': episode_peaks(rows),
    }


def get_historia():
    """Niño 1+2 weekly anomaly per year, for the 'every year since 1981' chart."""
    noaa = cached('noaa', get_noaa, TTL['noaa'])
    if not noaa.get('data'):
        raise ValueError(noaa.get('error', 'NOAA no disponible'))
    years = {}
    for r in noaa['data']['all']:
        d = datetime.strptime(r['date'], '%Y-%m-%d')
        years.setdefault(d.year, []).append([d.timetuple().tm_yday, r['nino12']])
    return {'anios': years, 'episodios': noaa['data']['insights']['episodios'], 'fuente': 'NOAA CPC'}


# ---------------------------------------------------------------- INDECI (stale public layer: report its date only)
def get_indeci_latest():
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


# ---------------------------------------------------------------- GDACS events
GDACS_TYPES = {'EQ': 'Sismo', 'FL': 'Inundación', 'TC': 'Ciclón tropical', 'VO': 'Volcán',
               'DR': 'Sequía', 'WF': 'Incendio forestal', 'TS': 'Tsunami'}
CLIMATE_CODES = {'FL', 'DR', 'WF', 'TC'}   # weather/climate-related; earthquakes and volcanoes are not El Niño


def nearest_city(lat, lon):
    return min(REGIONS, key=lambda k: (REGIONS[k][1] - lat) ** 2 + (REGIONS[k][2] - lon) ** 2)


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
        code = p.get('eventtype')
        city = nearest_city(coords[1], coords[0])
        events.append({
            'type': GDACS_TYPES.get(code, code or 'Evento'), 'code': code,
            'climatico': code in CLIMATE_CODES,
            'name': p.get('name') or '', 'alert': (p.get('alertlevel') or '').lower(),
            'date': (p.get('fromdate') or '')[:10], 'detail': sev.get('severitytext') or '',
            'lon': coords[0], 'lat': coords[1], 'zona': REGIONS[city][3],
            'url': report if report.startswith('https://') else 'https://www.gdacs.org/',
        })
    events.sort(key=lambda e: e['date'], reverse=True)
    return {'events': events, 'days': 60, 'source_url': 'https://www.gdacs.org/'}


# ---------------------------------------------------------------- news
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


# ---------------------------------------------------------------- forecasts
def get_forecast(region):
    name, lat, lon, zone = REGIONS[region]
    params = {'latitude': lat, 'longitude': lon,
              'daily': 'precipitation_sum,temperature_2m_max,temperature_2m_min',
              'timezone': 'America/Lima', 'forecast_days': 7}
    d = json.loads(fetch(URLS['forecast'] + '?' + urllib.parse.urlencode(params))).get('daily', {})
    if not d.get('time'):
        raise ValueError('Pronóstico no disponible')
    return {'region': region, 'name': name, 'zona': zone, 'daily': d}


def get_ensemble():
    """ECMWF ensemble (51 members) via Open-Meteo: rain ranges per city and day, plus 3-day totals."""
    keys = list(REGIONS)
    params = {'latitude': ','.join(str(REGIONS[k][1]) for k in keys),
              'longitude': ','.join(str(REGIONS[k][2]) for k in keys),
              'daily': 'precipitation_sum', 'timezone': 'America/Lima', 'forecast_days': 7,
              'models': 'ecmwf_ifs025'}
    data = json.loads(fetch(URLS['ensemble'] + '?' + urllib.parse.urlencode(params), limit=8_000_000, timeout=25))
    if isinstance(data, dict):
        if data.get('error'):
            raise ValueError('Open-Meteo: ' + str(data.get('reason', 'error'))[:120])
        data = [data]
    if len(data) != len(keys):
        raise ValueError('Respuesta incompleta del servicio de ensambles')
    out = {}
    for k, loc in zip(keys, data):
        d = loc.get('daily') or {}
        times = d.get('time') or []
        members = [v for name, v in d.items() if name.startswith('precipitation_sum') and isinstance(v, list)]
        if not times or not members:
            continue
        days = []
        for i, t in enumerate(times):
            vals = [m[i] for m in members if i < len(m) and isinstance(m[i], (int, float))]
            days.append({'fecha': t, 'p10': percentile(vals, .1), 'p50': percentile(vals, .5),
                         'p90': percentile(vals, .9)})
        totals = [sum(x for x in m[:3] if isinstance(x, (int, float))) for m in members]
        out[k] = {'dias': days, 'total3': {'p10': percentile(totals, .1), 'p50': percentile(totals, .5),
                                           'p90': percentile(totals, .9)},
                  'max_dia3': {'p50': max((x['p50'] or 0) for x in days[:3]),
                               'p90': max((x['p90'] or 0) for x in days[:3])},
                  'miembros': len(members)}
    if not out:
        raise ValueError('Sin datos de ensambles')
    return {'ciudades': out, 'modelo': 'ECMWF IFS ensamble (Open-Meteo)', 'percentiles': 'p10 / p50 / p90'}


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
        name, lat, lon, zone = REGIONS[k]
        nums = [v for v in vals if isinstance(v, (int, float))]
        out.append({'id': k, 'name': name, 'lat': lat, 'lon': lon, 'zona': zone,
                    'rain_3d': round(sum(nums), 1), 'max_dia': round(max(nums), 1) if nums else 0})
    return {'cities': out, 'days': 3}


def rain_with_ranges():
    rain = cached('rain', get_rain_map, TTL['rain'])
    ens = cached('ens', get_ensemble, TTL['ens'])
    result = dict(rain)
    if rain.get('data'):
        cities = []
        e = (ens.get('data') or {}).get('ciudades', {})
        for c in rain['data']['cities']:
            c = dict(c)
            if c['id'] in e:
                c['total3'] = e[c['id']]['total3']
                c['max_dia3'] = e[c['id']]['max_dia3']
            cities.append(c)
        result['data'] = {**rain['data'], 'cities': cities, 'zonas': ZONES,
                          'rangos': ens['status'] == 'ok' or bool(ens.get('data')),
                          'modelo_rangos': (ens.get('data') or {}).get('modelo')}
    return result


# ---------------------------------------------------------------- CSV
def csv_text(rows, cols):
    def cell(v):
        s = '' if v is None else str(v)
        return '"' + s.replace('"', '""') + '"' if any(c in s for c in ',"\n') else s
    return '\n'.join([','.join(cols)] + [','.join(cell(r.get(c)) for c in cols) for r in rows]) + '\n'


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

    def send_csv(self, text, filename):
        raw = ('﻿' + text).encode('utf-8')   # BOM so Excel opens accents correctly
        self.send_response(200)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    MCP_405 = ('<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
               '<title>Servidor MCP · Monitor El Niño</title>'
               '<body style="font:16px/1.6 system-ui,sans-serif;max-width:640px;margin:40px auto;padding:0 18px;background:#0b1522;color:#eef4fb">'
               '<h1 style="font-size:22px">Servidor MCP del Monitor El Niño · Grupo Evidencia</h1>'
               '<p>Esta dirección no se abre en el navegador: es un servidor <b>MCP</b> para asistentes de IA. '
               'Para usarlo, agrégala como <b>conector personalizado</b> en tu asistente (por ejemplo, en Claude: Configuración → Conectores → Agregar conector personalizado) '
               'con esta URL:</p><p><code style="background:#18293f;padding:4px 8px;border-radius:4px">https://observatorio-nino-peru.onrender.com/mcp</code></p>'
               '<p>Herramientas disponibles: estado de El Niño esta semana, serie semanal del mar desde 1981, perspectiva oficial de ENFEN, '
               'pronóstico por ciudad con rangos, lluvia esperada, emergencias recientes y comunicados de ENFEN.</p>'
               '<p><a style="color:#5fd3e4" href="/">Ir al Monitor El Niño</a></p></body></html>').encode()

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
            if noaa.get('data'):  # the full history is for MCP and /api/historia; pages only need the last year
                noaa['data'] = {k: v for k, v in noaa['data'].items() if k != 'all'}
            return self.send_json({'sources': {
                'noaa': noaa,
                'oficial': get_oficial(),
                'enfen': cached('enfen', get_enfen, TTL['enfen']),
                'gdacs': cached('gdacs', get_gdacs, TTL['gdacs']),
                'indeci': cached('indeci', get_indeci_latest, TTL['indeci']),
                'news': cached('news', get_news, TTL['news']),
            }, 'brand': BRAND, 'server_time': datetime.now(timezone.utc).isoformat()})
        if p == '/api/rain-map':
            return self.send_json(rain_with_ranges())
        if p == '/api/forecast':
            region = urllib.parse.parse_qs(path.query).get('region', ['lima'])[0]
            if region not in REGIONS:
                return self.send_json({'error': 'Región no admitida'}, 400)
            res = dict(cached('forecast:' + region, lambda: get_forecast(region), TTL['forecast']))
            ens = cached('ens', get_ensemble, TTL['ens'])
            if res.get('data'):
                res['data'] = dict(res['data'])
                res['data']['rangos'] = ((ens.get('data') or {}).get('ciudades') or {}).get(region, {}).get('dias')
            return self.send_json(res)
        if p == '/api/historia':
            return self.send_json(cached('historia', get_historia, TTL['noaa']))
        if p == '/api/datos/mar.csv':
            noaa = cached('noaa', get_noaa, TTL['noaa'])
            if not noaa.get('data'):
                return self.send_json({'error': 'NOAA no disponible'}, 503)
            rows = [{'semana': r['date'], 'anomalia_nino12_c': r['nino12'], 'temperatura_nino12_c': r['sst12'],
                     'anomalia_nino34_c': r['nino34'], 'temperatura_nino34_c': r['sst34']} for r in noaa['data']['all']]
            return self.send_csv(csv_text(rows, list(rows[0])), 'monitor-el-nino_mar_semanal_noaa.csv')
        if p == '/api/datos/ciudades.csv':
            rain = rain_with_ranges()
            if not rain.get('data'):
                return self.send_json({'error': 'Pronóstico no disponible'}, 503)
            rows = [{'ciudad': c['name'], 'zona': ZONES[c['zona']], 'lluvia_3d_mm_modelo': c['rain_3d'],
                     'lluvia_3d_mm_p10': (c.get('total3') or {}).get('p10'), 'lluvia_3d_mm_p50': (c.get('total3') or {}).get('p50'),
                     'lluvia_3d_mm_p90': (c.get('total3') or {}).get('p90'),
                     'fuente': 'Open-Meteo (pronóstico de modelo, no observación)'} for c in rain['data']['cities']]
            return self.send_csv(csv_text(rows, list(rows[0])), 'monitor-el-nino_lluvia_3dias.csv')
        if p == '/api/health':
            return self.send_json({'status': 'ok', 'version': VERSION, 'server_time': datetime.now(timezone.utc).isoformat()})
        if p == '/mcp':
            # 2026-07-28 removed the GET stream; older clients probing it get 405 too.
            return self.send_mcp_405()
        if p in ('/detalle', '/detalle/'):
            self.path = '/detalle.html'
        if p.endswith('.py') or p in ('/render.yaml',):
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
    print('Monitor El Niño', VERSION, 'en puerto', port, flush=True)
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()
