"""MCP server for Monitor El Niño · Grupo Evidencia.

Streamable HTTP endpoint at POST /mcp, no external dependencies.
Dual-era (see https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning):
  * Modern 2026-07-28: stateless, version + client info in params._meta, required
    MCP-Protocol-Version / Mcp-Method / Mcp-Name headers, server/discover, resultType.
  * Legacy 2025-03-26 … 2025-11-25: initialize handshake (served statelessly, no session ids).
All tools are read-only views of public data the dashboard already uses.
"""
import base64, json, sys, threading, time, importlib, os
from datetime import date

MODERN = ['2026-07-28']
LEGACY = ['2025-11-25', '2025-06-18', '2025-03-26']
META_VER = 'io.modelcontextprotocol/protocolVersion'
META_SERVER = 'io.modelcontextprotocol/serverInfo'
SERVER_INFO = {'name': 'monitor-el-nino', 'title': 'Monitor El Niño · Grupo Evidencia', 'version': '2.1'}
INSTRUCTIONS = (
    'Datos públicos sobre El Niño y el clima en el Perú, reunidos por el Monitor El Niño (Grupo Evidencia, con MNRY). '
    'Es un monitor de datos, no un servicio de pronóstico. Fuentes: NOAA CPC (anomalías semanales de temperatura del mar, base 1991–2020), '
    'ENFEN (comunicados oficiales; su perspectiva es la única voz oficial sobre lo que viene), '
    'Open-Meteo (pronóstico de modelo y ensambles ECMWF, no observación ni aviso de SENAMHI) y GDACS (desastres con impacto relevante, no exhaustivo). '
    'La etiqueta de categoría semanal aplica la escala ICEN de ENFEN al dato semanal: es una señal temprana, no la clasificación oficial. '
    'Para hablar del futuro, usa perspectiva_oficial_enfen. Cita siempre la fuente y la fecha de cada dato. '
    'El servidor gratuito puede tardar ~1 minuto en responder la primera vez si estaba en reposo.'
)

# ---------- access to the running app (same cache as the dashboard) ----------
def _app():
    m = sys.modules.get('__main__')
    return m if hasattr(m, 'get_noaa') else importlib.import_module('app')

# ---------- plain-language classification ----------
def class12(v):
    if v > 3.0: return 'Cálido extraordinario'
    if v > 1.7: return 'Cálido fuerte'
    if v > 1.0: return 'Cálido moderado'
    if v > 0.4: return 'Cálido débil'
    if v >= -1.0: return 'Normal'
    return 'Frío'

def class34(v):
    if v >= 2.0: return 'Cálido muy fuerte'
    if v >= 1.5: return 'Cálido fuerte'
    if v >= 1.0: return 'Cálido moderado'
    if v >= 0.5: return 'Cálido débil'
    if v > -0.5: return 'Normal'
    return 'Frío (tipo La Niña)'

# ---------- tools ----------
class ToolError(Exception):
    pass

def _source(key, loader, ttl_key):
    a = _app()
    res = a.cached(key, loader, a.TTL[ttl_key])
    if not res.get('data'):
        raise ToolError(f'La fuente no respondió en este momento ({res.get("error", "sin detalle")}). Intenta de nuevo en unos minutos.')
    note = ' (datos anteriores: la fuente no respondió en la última consulta)' if res.get('stale') else ''
    return res['data'], res.get('checked_at'), note

def t_estado():
    a = _app()
    d, checked, note = _source('noaa', a.get_noaa, 'noaa')
    l = d['latest']
    out = {
        'semana': l['date'],
        'nino12': {'region': 'Costa norte del Perú y Ecuador (0–10°S, 90–80°O)', 'anomalia_c': l['nino12'],
                   'temperatura_c': l['sst12'], 'categoria_referencial': class12(l['nino12'])},
        'nino34': {'region': 'Pacífico central (5°N–5°S, 170–120°O)', 'anomalia_c': l['nino34'],
                   'temperatura_c': l['sst34'], 'categoria_referencial': class34(l['nino34'])},
        'base_climatologica': '1991–2020',
        'fuente': 'NOAA CPC, wksst9120.for', 'fuente_url': d['source_url'], 'consultado': checked,
    }
    txt = (f"Semana del {l['date']}{note}. Niño 1+2 (costa norte): {l['nino12']:+.1f} °C sobre lo normal, "
           f"{class12(l['nino12'])}. Niño 3.4 (Pacífico central): {l['nino34']:+.1f} °C, {class34(l['nino34'])}. "
           'Fuente: NOAA CPC. Categorías referenciales (escala ICEN aplicada al dato semanal).')
    return txt, out

def t_serie(args):
    a = _app()
    indice = args.get('indice', 'nino12')
    if indice not in ('nino12', 'nino34'):
        raise ToolError('indice debe ser "nino12" o "nino34".')
    def pdate(k):
        v = args.get(k)
        if v in (None, ''): return None
        try: return date.fromisoformat(str(v)).isoformat()
        except ValueError: raise ToolError(f'{k} debe tener formato AAAA-MM-DD.')
    desde, hasta = pdate('desde'), pdate('hasta')
    d, checked, note = _source('noaa', a.get_noaa, 'noaa')
    rows = d.get('all') or d['series']
    if desde: rows = [r for r in rows if r['date'] >= desde]
    if hasta: rows = [r for r in rows if r['date'] <= hasta]
    if not desde and not hasta: rows = rows[-52:]
    truncated = len(rows) > 600
    rows = rows[-600:]
    if not rows:
        raise ToolError('No hay semanas en ese rango. La serie empieza en septiembre de 1981.')
    sst = 'sst12' if indice == 'nino12' else 'sst34'
    serie = [{'semana': r['date'], 'anomalia_c': r[indice], 'temperatura_c': r[sst]} for r in rows]
    vals = [r[indice] for r in rows]
    mx = max(rows, key=lambda r: r[indice])
    out = {'indice': indice, 'semanas': len(serie), 'desde': serie[0]['semana'], 'hasta': serie[-1]['semana'],
           'maximo': {'semana': mx['date'], 'anomalia_c': mx[indice]}, 'promedio_anomalia_c': round(sum(vals) / len(vals), 2),
           'recortado_a_600_semanas': truncated, 'serie': serie, 'fuente': 'NOAA CPC', 'consultado': checked}
    txt = (f"{indice}: {len(serie)} semanas ({serie[0]['semana']} a {serie[-1]['semana']}){note}. "
           f"Máximo {mx[indice]:+.1f} °C (semana del {mx['date']}); promedio {out['promedio_anomalia_c']:+.2f} °C.")
    return txt, out

def t_pronostico(args):
    a = _app()
    ciudad = str(args.get('ciudad', '')).lower()
    if ciudad not in a.REGIONS:
        raise ToolError('Ciudad no disponible. Opciones: ' + ', '.join(a.REGIONS))
    d, checked, note = _source('forecast:' + ciudad, lambda: a.get_forecast(ciudad), 'forecast')
    dd = d['daily']
    ens = a.cached('ens', a.get_ensemble, a.TTL['ens'])
    rng = {x['fecha']: x for x in ((ens.get('data') or {}).get('ciudades') or {}).get(ciudad, {}).get('dias', [])}
    dias = [{'fecha': t, 'lluvia_mm': dd['precipitation_sum'][i], 'temp_min_c': dd['temperature_2m_min'][i],
             'temp_max_c': dd['temperature_2m_max'][i],
             'lluvia_rango_mm': ({'p10': rng[t]['p10'], 'p50': rng[t]['p50'], 'p90': rng[t]['p90']} if t in rng else None)}
            for i, t in enumerate(dd['time'])]
    out = {'ciudad': d['name'], 'dias': dias, 'tipo': 'pronóstico de modelo, no observación',
           'rangos': 'percentiles 10/50/90 del ensamble ECMWF (51 escenarios)' if rng else 'no disponibles',
           'fuente': 'Open-Meteo', 'consultado': checked,
           'aviso': 'Para decisiones, consultar los avisos oficiales de SENAMHI.'}
    total = round(sum(x['lluvia_mm'] or 0 for x in dias), 1)
    txt = f"Pronóstico 7 días para {d['name']}{note}: {total} mm de lluvia en total. Fuente: Open-Meteo (modelo)."
    return txt, out

def t_lluvia():
    a = _app()
    d, checked, note = _source('rain', a.get_rain_map, 'rain')
    cities = sorted(d['cities'], key=lambda c: -c['rain_3d'])
    out = {'dias': 3, 'ciudades': [{'ciudad': c['name'], 'lluvia_mm': c['rain_3d'], 'lat': c['lat'], 'lon': c['lon']} for c in cities],
           'tipo': 'pronóstico de modelo', 'fuente': 'Open-Meteo', 'consultado': checked}
    top = ', '.join(f"{c['name']} {c['rain_3d']} mm" for c in cities[:3])
    return f'Lluvia esperada en los próximos 3 días{note}. Mayores valores: {top}. Fuente: Open-Meteo.', out

def t_emergencias(args):
    a = _app()
    d, checked, note = _source('gdacs', a.get_gdacs, 'gdacs')
    evs = d['events']
    tipo = args.get('tipo')
    if tipo:
        evs = [e for e in evs if e['type'].lower() == str(tipo).lower()]
    elif args.get('solo_climaticos', True):
        evs = [e for e in evs if e.get('climatico')]
    out = {'dias': d.get('days', 60), 'total': len(evs),
           'eventos': [{'tipo': e['type'], 'fecha': e['date'], 'alerta': e['alert'], 'detalle': e['detail'] or e['name'],
                        'climatico': e.get('climatico'), 'lat': e['lat'], 'lon': e['lon'], 'informe': e['url']} for e in evs],
           'nota': 'GDACS registra eventos de impacto relevante; no incluye cada emergencia local.',
           'fuente': 'GDACS (ONU / Comisión Europea)', 'consultado': checked}
    n = len(evs)
    return f"{n} {'evento' if n == 1 else 'eventos'} en Perú en los últimos {out['dias']} días según GDACS{note}.", out

def t_enfen():
    a = _app()
    d, checked, note = _source('enfen', a.get_enfen, 'enfen')
    items = d['items'][:5]
    out = {'comunicados': [{'titulo': i['title'], 'url': i['url']} for i in items], 'fuente': 'ENFEN', 'consultado': checked}
    return f"Comunicado más reciente detectado: {items[0]['title']}{note}. Para el diagnóstico oficial, lee el documento enlazado.", out

def t_oficial():
    a = _app()
    res = a.get_oficial()
    if res['status'] != 'ok':
        raise ToolError('No se pudo leer la perspectiva oficial: ' + res.get('error', ''))
    o = {k: v for k, v in res['data'].items() if not k.startswith('_')}
    txt = (f"{o.get('comunicado')} ({o.get('fecha')}): {o.get('estado_alerta')}. Magnitud prevista en la costa: "
           f"{o.get('magnitud_costa')} hasta {o.get('magnitud_costa_hasta')}; El Niño costero {o.get('duracion')}. "
           f"Próximo comunicado: {o.get('proximo_comunicado')}. Texto transcrito a mano del comunicado oficial.")
    o['nota'] = 'Transcrito a mano del comunicado oficial de ENFEN; verificar en la fuente.'
    return txt, o

RO = {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': True}
NO_ARGS = {'type': 'object', 'additionalProperties': False}

def tool_defs():
    cities = list(_app().REGIONS)
    return [
        {'name': 'estado_el_nino', 'title': 'Estado de El Niño esta semana',
         'description': 'Anomalía más reciente de temperatura del mar en Niño 1+2 (costa norte del Perú) y Niño 3.4 (Pacífico central), con categoría referencial en lenguaje simple. Fuente: NOAA CPC, dato semanal.',
         'inputSchema': NO_ARGS, 'annotations': RO, 'run': lambda args: t_estado()},
        {'name': 'serie_temperatura_mar', 'title': 'Serie semanal de temperatura del mar',
         'description': 'Serie semanal de anomalías (°C frente a 1991–2020) desde 1981. Sin fechas devuelve las últimas 52 semanas; con desde/hasta (AAAA-MM-DD) devuelve ese rango, máximo 600 semanas. Útil para comparar años, p. ej. 1997–98, 2017, 2023 y el presente.',
         'inputSchema': {'type': 'object', 'properties': {
             'indice': {'type': 'string', 'enum': ['nino12', 'nino34'], 'default': 'nino12', 'description': 'nino12 = costa norte del Perú; nino34 = Pacífico central'},
             'desde': {'type': 'string', 'format': 'date', 'description': 'Fecha inicial AAAA-MM-DD (opcional)'},
             'hasta': {'type': 'string', 'format': 'date', 'description': 'Fecha final AAAA-MM-DD (opcional)'}},
             'additionalProperties': False},
         'annotations': RO, 'run': t_serie},
        {'name': 'perspectiva_oficial_enfen', 'title': 'Perspectiva oficial de ENFEN',
         'description': 'Lo que dice el último comunicado oficial de ENFEN: estado de alerta, magnitud prevista, duración, lluvias esperadas por zona y fecha del próximo comunicado. Es la referencia oficial sobre lo que viene.',
         'inputSchema': NO_ARGS, 'annotations': {**RO, 'openWorldHint': False}, 'run': lambda args: t_oficial()},
        {'name': 'pronostico_ciudad', 'title': 'Pronóstico de 7 días por ciudad',
         'description': 'Lluvia diaria (mm) con rango de escenarios (percentiles 10/50/90 del ensamble ECMWF) y temperatura mínima/máxima de los próximos 7 días para una ciudad del Perú. Pronóstico de modelo, no observación ni aviso oficial de SENAMHI.',
         'inputSchema': {'type': 'object', 'properties': {'ciudad': {'type': 'string', 'enum': cities}}, 'required': ['ciudad'], 'additionalProperties': False},
         'annotations': RO, 'run': t_pronostico},
        {'name': 'lluvia_esperada_ciudades', 'title': 'Lluvia esperada en 3 días (todas las ciudades)',
         'description': 'Lluvia total pronosticada para los próximos 3 días en las 12 ciudades del monitor, ordenadas de mayor a menor. Fuente: Open-Meteo.',
         'inputSchema': NO_ARGS, 'annotations': RO, 'run': lambda args: t_lluvia()},
        {'name': 'emergencias_recientes', 'title': 'Emergencias y desastres recientes en el Perú',
         'description': 'Eventos registrados por GDACS en el Perú y su costa en los últimos 60 días. Por defecto solo los relacionados con el clima (inundaciones, sequías, incendios, ciclones); sismos y volcanes con solo_climaticos=false o filtrando por tipo. No es exhaustivo: GDACS solo registra eventos de impacto relevante.',
         'inputSchema': {'type': 'object', 'properties': {'tipo': {'type': 'string', 'enum': ['Sismo', 'Inundación', 'Ciclón tropical', 'Volcán', 'Sequía', 'Incendio forestal'], 'description': 'Filtrar por tipo (opcional)'},
                                                          'solo_climaticos': {'type': 'boolean', 'default': True, 'description': 'Solo eventos relacionados con el clima (por defecto true)'}}, 'additionalProperties': False},
         'annotations': RO, 'run': t_emergencias},
        {'name': 'comunicados_enfen', 'title': 'Comunicados oficiales de ENFEN',
         'description': 'Títulos y enlaces de los comunicados oficiales más recientes de ENFEN, la comisión peruana que declara oficialmente El Niño costero.',
         'inputSchema': NO_ARGS, 'annotations': RO, 'run': lambda args: t_enfen()},
    ]

def public_tools():
    return [{k: v for k, v in t.items() if k != 'run'} for t in tool_defs()]

# ---------- rate limiting & origin ----------
_RL = {}; _RL_LOCK = threading.Lock(); RATE, BURST = 1.0, 60  # ~60 requests/min per IP

def _allowed(ip):
    now = time.time()
    with _RL_LOCK:
        tokens, last = _RL.get(ip, (BURST, now))
        tokens = min(BURST, tokens + (now - last) * RATE)
        if tokens < 1:
            _RL[ip] = (tokens, now); return False
        _RL[ip] = (tokens - 1, now)
        if len(_RL) > 5000: _RL.clear()
        return True

ALLOWED_ORIGINS = {'https://claude.ai', 'https://claude.com', 'https://chatgpt.com', 'https://chat.openai.com'}
ALLOWED_ORIGINS |= {o.strip() for o in os.environ.get('MCP_ALLOWED_ORIGINS', '').split(',') if o.strip()}

def _origin_ok(h):
    origin = h.headers.get('Origin')
    if not origin:
        return True  # server-to-server clients (Claude connectors, SDKs) send no Origin
    host = h.headers.get('Host', '')
    if origin in ALLOWED_ORIGINS or origin in (f'https://{host}', f'http://{host}'):
        return True
    o = origin.split('://', 1)[-1].split(':')[0]
    return o in ('localhost', '127.0.0.1', '[::1]') or o.endswith('.claude.ai')

def _cors(h):
    origin = h.headers.get('Origin')
    if origin and _origin_ok(h):
        h.send_header('Access-Control-Allow-Origin', origin)
        h.send_header('Vary', 'Origin')
        h.send_header('Access-Control-Expose-Headers', 'Content-Type')

def handle_options(h):
    if not _origin_ok(h):
        return _send(h, 403, None)
    h.send_response(204)
    _cors(h)
    h.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
    h.send_header('Access-Control-Allow-Headers', 'Content-Type, Accept, Authorization, MCP-Protocol-Version, Mcp-Method, Mcp-Name, Mcp-Session-Id')
    h.send_header('Access-Control-Max-Age', '86400')
    h.send_header('Content-Length', '0')
    h.end_headers()

# ---------- JSON-RPC plumbing ----------
def _send(h, status, payload):
    raw = b'' if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    h.send_response(status)
    _cors(h)
    if raw:
        h.send_header('Content-Type', 'application/json; charset=utf-8')
    h.send_header('Cache-Control', 'no-store')
    h.send_header('Content-Length', str(len(raw)))
    h.end_headers()
    if raw:
        h.wfile.write(raw)

def _err(id_, code, msg, data=None):
    e = {'code': code, 'message': msg}
    if data is not None: e['data'] = data
    out = {'jsonrpc': '2.0', 'error': e}
    if id_ is not None: out['id'] = id_
    return out

def _decode_header(v):
    if v and v.startswith('=?base64?') and v.endswith('?='):
        try: return base64.b64decode(v[9:-2]).decode('utf-8')
        except Exception: return None
    return v

def _call_tool(params, modern):
    name = params.get('name')
    args = params.get('arguments') or {}
    tool = next((t for t in tool_defs() if t['name'] == name), None)
    if tool is None:
        return None, _err(None, -32602, f'Herramienta desconocida: {name}')
    if not isinstance(args, dict):
        return None, _err(None, -32602, 'arguments debe ser un objeto')
    try:
        text, data = tool['run'](args)
        res = {'content': [{'type': 'text', 'text': text}, {'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}],
               'structuredContent': data, 'isError': False}
    except ToolError as e:
        res = {'content': [{'type': 'text', 'text': str(e)}], 'isError': True}
    except Exception as e:  # unexpected failure in a data source
        res = {'content': [{'type': 'text', 'text': f'Error al consultar los datos: {str(e)[:200]}'}], 'isError': True}
    return res, None

def handle_post(h):
    if not _origin_ok(h):
        return _send(h, 403, _err(None, -32600, 'Origin no permitido'))
    ip = (h.headers.get('X-Forwarded-For') or h.client_address[0]).split(',')[0].strip()
    if not _allowed(ip):
        return _send(h, 429, _err(None, -32000, 'Demasiadas solicitudes; intenta en un minuto'))
    try:
        n = int(h.headers.get('Content-Length') or 0)
        if n > 1_000_000:
            return _send(h, 413, _err(None, -32600, 'Solicitud demasiado grande'))
        msg = json.loads(h.rfile.read(n) or b'null')
    except (ValueError, UnicodeDecodeError):
        return _send(h, 400, _err(None, -32700, 'Parse error'))
    if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0' or not isinstance(msg.get('method'), str):
        return _send(h, 400, _err(msg.get('id') if isinstance(msg, dict) else None, -32600, 'Invalid Request'))

    method, id_ = msg['method'], msg.get('id')
    params = msg.get('params') or {}
    if not isinstance(params, dict):
        return _send(h, 400, _err(id_, -32602, 'params debe ser un objeto'))
    if 'id' not in msg:  # notification (e.g. legacy notifications/initialized)
        return _send(h, 202, None)

    meta = params.get('_meta') or {}
    modern_ver = meta.get(META_VER) if isinstance(meta, dict) else None
    header_ver = h.headers.get('MCP-Protocol-Version')

    # ---------- modern (2026-07-28): stateless, per-request metadata ----------
    if modern_ver is not None:
        if modern_ver not in MODERN:
            return _send(h, 400, _err(id_, -32022, 'Unsupported protocol version',
                                      {'supported': MODERN + LEGACY, 'requested': modern_ver}))
        if header_ver is None or h.headers.get('Mcp-Method') is None:
            return _send(h, 400, _err(id_, -32020, 'Header mismatch: faltan MCP-Protocol-Version o Mcp-Method'))
        if header_ver != modern_ver:
            return _send(h, 400, _err(id_, -32020, f"Header mismatch: MCP-Protocol-Version '{header_ver}' no coincide con '{modern_ver}'"))
        if h.headers.get('Mcp-Method') != method:
            return _send(h, 400, _err(id_, -32020, 'Header mismatch: Mcp-Method no coincide con method'))
        if method == 'tools/call':
            hn = _decode_header(h.headers.get('Mcp-Name'))
            if hn is None or hn != params.get('name'):
                return _send(h, 400, _err(id_, -32020, 'Header mismatch: Mcp-Name falta o no coincide con params.name'))
        meta_out = {META_SERVER: SERVER_INFO}
        if method == 'server/discover':
            return _send(h, 200, {'jsonrpc': '2.0', 'id': id_, 'result': {
                'resultType': 'complete', 'supportedVersions': MODERN + LEGACY, 'capabilities': {'tools': {}},
                'instructions': INSTRUCTIONS, '_meta': meta_out, 'ttlMs': 3600000, 'cacheScope': 'public'}})
        if method == 'tools/list':
            return _send(h, 200, {'jsonrpc': '2.0', 'id': id_, 'result': {
                'resultType': 'complete', 'tools': public_tools(), 'ttlMs': 3600000, 'cacheScope': 'public', '_meta': meta_out}})
        if method == 'tools/call':
            res, err = _call_tool(params, True)
            if err:
                err['id'] = id_; return _send(h, 200, err)
            res['resultType'] = 'complete'; res['_meta'] = meta_out
            return _send(h, 200, {'jsonrpc': '2.0', 'id': id_, 'result': res})
        return _send(h, 404, _err(id_, -32601, f'Method not found: {method}'))

    # ---------- legacy (2025-03-26 … 2025-11-25): initialize handshake, served statelessly ----------
    if header_ver is not None and header_ver not in LEGACY and method != 'initialize':
        return _send(h, 400, _err(id_, -32600, f'Unsupported protocol version: {header_ver}', {'supported': MODERN + LEGACY}))
    if method == 'initialize':
        req = params.get('protocolVersion')
        ver = req if req in LEGACY else LEGACY[0]
        return _send(h, 200, {'jsonrpc': '2.0', 'id': id_, 'result': {
            'protocolVersion': ver, 'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': SERVER_INFO, 'instructions': INSTRUCTIONS}})
    if method == 'ping':
        return _send(h, 200, {'jsonrpc': '2.0', 'id': id_, 'result': {}})
    if method == 'tools/list':
        return _send(h, 200, {'jsonrpc': '2.0', 'id': id_, 'result': {'tools': public_tools()}})
    if method == 'tools/call':
        res, err = _call_tool(params, False)
        if err:
            err['id'] = id_; return _send(h, 200, err)
        return _send(h, 200, {'jsonrpc': '2.0', 'id': id_, 'result': res})
    if method in ('resources/list', 'prompts/list'):
        key = method.split('/')[0]
        return _send(h, 200, {'jsonrpc': '2.0', 'id': id_, 'result': {key: []}})
    return _send(h, 200, _err(id_, -32601, f'Method not found: {method}'))
