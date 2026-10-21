import os,json,time,threading,re,urllib.request,urllib.parse,html,xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from datetime import datetime,timezone
from pathlib import Path
BASE=Path(__file__).parent
SOURCES={
 'enfen':'https://enfen.imarpe.gob.pe/downloads/comunicados/',
 'senamhi':'https://wis.senamhi.gob.pe/oapi/collections/urn%3Awmo%3Amd%3Ape-senamhi%3Asynop-hourly/items?f=json&limit=50',
 'indeci':'https://geosinpad.indeci.gob.pe/indeci/rest/services/Emergencias/EMERGENCIAS_SINPAD/MapServer/0/query?where=1%3D1&outFields=*&returnGeometry=true&outSR=4326&resultRecordCount=100&f=geojson'
}
CACHE={}; LOCK=threading.Lock(); TTL=1800

def fetch(url,limit=3_000_000):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; PeruNinoMonitor/1.0)','Accept':'application/json,text/html,*/*'})
 with urllib.request.urlopen(req,timeout=18) as r: return r.read(limit),r.headers.get('Content-Type','')

def update(name):
 now=time.time()
 with LOCK:
  old=CACHE.get(name)
  if old and now-old['checked_epoch']<TTL:return old
 try:
  raw,ct=fetch(SOURCES[name]); data=None
  if name=='enfen':
   body=raw.decode('utf-8','replace'); matches=re.findall(r'<h[1-4][^>]*>\s*(.*?)\s*</h[1-4]>',body,re.I|re.S)
   titles=[html.unescape(re.sub('<[^>]+>',' ',m)).strip() for m in matches]
   titles=[re.sub(r'\s+',' ',x) for x in titles if 'Comunicado Oficial' in x.lower() or 'comunicado oficial' in x.lower()]
   if not titles:
    titles=re.findall(r'Comunicado Oficial\s+Enfen\s+N[°ºo.]?\s*\d+[-–]\d+',re.sub('<[^>]+>',' ',body),re.I)[:10]
   data={'headlines':list(dict.fromkeys(titles))[:8]}
   if not data['headlines']:raise ValueError('No se encontraron títulos de comunicados')
  else:
   obj=json.loads(raw)
   if not isinstance(obj,dict) or 'features' not in obj:raise ValueError('La fuente no devolvió GeoJSON con features')
   features=obj.get('features',[])
   if name=='indeci':
    # No interpretamos campos heterogéneos ni asignamos categorías no verificadas.
    data={'features':features[:100],'count_sample':len(features),'sample_only':True}
   else:
    data={'features':features[:50],'count_sample':len(features),'sample_only':True}
  result={'status':'ok','checked_at':datetime.now(timezone.utc).isoformat(),'checked_epoch':now,'data':data,'source':SOURCES[name]}
 except Exception as e:
  result={'status':'error','checked_at':datetime.now(timezone.utc).isoformat(),'checked_epoch':now,'error':str(e)[:240],'source':SOURCES[name]}
  if old and old.get('data') is not None:result['data']=old['data'];result['stale']=True
 with LOCK:CACHE[name]=result
 return result

# NOAA CoastWatch MUR: cartografía oceánica, no clasificación oficial de alerta.
OCEAN_BASE='https://coastwatch.pfeg.noaa.gov/erddap/wms/jplMURSST41anom1day/request'
OCEAN_LOCK=threading.Lock()
OCEAN_META={}
def ocean_metadata():
 now=time.time()
 with OCEAN_LOCK:
  if OCEAN_META.get('checked',0)+3600>now:return dict(OCEAN_META)
 url=OCEAN_BASE+'?service=WMS&request=GetCapabilities&version=1.3.0'
 try:
  raw,_=fetch(url,limit=20_000_000)
  root=ET.fromstring(raw)
  layers=[]
  for node in root.iter():
   if node.tag.rsplit('}',1)[-1]!='Layer':continue
   name=next((c.text for c in node if c.tag.rsplit('}',1)[-1]=='Name'),None)
   if name and ':' in name and ('anom' in name.lower() or 'sst' in name.lower()):
    layers.append((node,name))
  if not layers:raise ValueError('No se encontró la capa de anomalía en GetCapabilities')
  layer,name=next(((n,k) for n,k in layers if 'anom' in k.lower()),layers[0])
  extent=None
  for node in layer.iter():
   if node.tag.rsplit('}',1)[-1] in ('Dimension','Extent') and node.attrib.get('name','').lower()=='time':
    extent=(node.text or '').strip();break
  if not extent:
   for node in root.iter():
    if node.tag.rsplit('}',1)[-1] in ('Dimension','Extent') and node.attrib.get('name','').lower()=='time':
     extent=(node.text or '').strip();break
  if not extent:raise ValueError('WMS no publicó la dimensión temporal')
  # ERDDAP suele entregar una lista separada por comas o un intervalo ISO.
  last=extent.split(',')[-1].strip().split('/')[-1].strip()
  if last.lower()=='current':last=datetime.now(timezone.utc).strftime('%Y-%m-%dT00:00:00Z')
  if not re.match(r'^\d{4}-\d{2}-\d{2}',last):raise ValueError('Fecha WMS no reconocida')
  result={'ok':True,'layer':name,'time':last,'checked':now,'url':url,'source':'NOAA CoastWatch / MUR'}
 except Exception as e:
  result={'ok':False,'error':str(e)[:200],'checked':now,'url':url}
 with OCEAN_LOCK:OCEAN_META.clear();OCEAN_META.update(result)
 return dict(result)

def ocean_image(query):
 meta=ocean_metadata()
 if not meta['ok']:raise ValueError(meta.get('error','WMS no disponible'))
 args=urllib.parse.parse_qs(query)
 bbox=[float(x) for x in args.get('bbox',[''])[0].split(',')]
 if len(bbox)!=4 or not all(-180<=v<=180 for v in bbox):raise ValueError('bbox inválido')
 width=min(1100,max(200,int(args.get('width',['900'])[0])))
 height=min(900,max(200,int(args.get('height',['600'])[0])))
 params={'service':'WMS','version':'1.1.1','request':'GetMap','layers':meta['layer'],'styles':'','format':'image/png','transparent':'TRUE','srs':'EPSG:4326','bbox':','.join(map(str,bbox)),'width':str(width),'height':str(height),'time':meta['time']}
 url=OCEAN_BASE+'?'+urllib.parse.urlencode(params)
 raw,ct=fetch(url,limit=8_000_000)
 if not raw.startswith(b'\x89PNG') and not raw.startswith(b'\xff\xd8'):raise ValueError('NOAA no devolvió una imagen válida')
 return raw

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(BASE),**kwargs)
 def do_GET(self):
  if self.path.startswith('/api/ocean-meta'):
   body=json.dumps(ocean_metadata(),ensure_ascii=False).encode()
   self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','public, max-age=900');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
  if self.path.startswith('/api/ocean-map'):
   try:
    raw=ocean_image(urllib.parse.urlsplit(self.path).query)
    self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Cache-Control','public, max-age=900');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   except Exception as e:
    body=str(e).encode();self.send_response(503);self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
   return
  if self.path.startswith('/api/status'):
   result={k:update(k) for k in SOURCES}
   body=json.dumps({'sources':result,'server_time':datetime.now(timezone.utc).isoformat()},ensure_ascii=False).encode()
   self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Access-Control-Allow-Origin','*');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
  return super().do_GET()

def refresh():
 while True:
  for key in SOURCES:update(key)
  time.sleep(TTL)
if __name__=='__main__':
 threading.Thread(target=refresh,daemon=True).start()
 port=int(os.environ.get('PORT',8080));print('Dashboard en puerto',port,flush=True)
 ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
