import os, json, time, threading, re, urllib.request, urllib.parse, html, xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
BASE=Path(__file__).resolve().parent
PUBLIC={'enfen':'https://enfen.imarpe.gob.pe/downloads/comunicados/','senamhi':'https://www.senamhi.gob.pe/','indeci':'https://portal.indeci.gob.pe/','noaa':'https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for','ocean':'https://coastwatch.pfeg.noaa.gov/erddap/wms/jplMURSST41anom1day/index.html','forecast':'https://open-meteo.com/en/docs'}
URLS={'enfen':PUBLIC['enfen'],'noaa':PUBLIC['noaa'],'indeci':'https://geosinpad.indeci.gob.pe/indeci/rest/services/Emergencias/EMERGENCIAS_SINPAD/MapServer/0/query'}
CACHE={};LOCK=threading.RLock();TTL={'enfen':3600,'noaa':21600,'indeci':1800,'forecast':3600,'ocean':3600,'news':3600}
REGIONS={'lima':(-12.05,-77.04),'piura':(-5.19,-80.63),'tumbes':(-3.57,-80.46),'chiclayo':(-6.77,-79.84),'trujillo':(-8.11,-79.03),'iquitos':(-3.75,-73.25),'cusco':(-13.53,-71.97),'arequipa':(-16.40,-71.54)}

def fetch(url,limit=3000000,timeout=12):
 req=urllib.request.Request(url,headers={'User-Agent':'ObservatorioNinoPeru/1.3 (public data monitoring)','Accept':'application/json,text/plain,text/html,application/xml,*/*'})
 with urllib.request.urlopen(req,timeout=timeout) as r:return r.read(limit),r.headers.get('Content-Type','')

def cached(key,loader,ttl):
 now=time.time()
 with LOCK:
  old=CACHE.get(key)
  if old and now-old['checked_epoch']<ttl:return old
 try:
  data=loader();result={'status':'ok','data':data,'checked_epoch':now,'checked_at':datetime.now(timezone.utc).isoformat(),'stale':False}
 except Exception as e:
  result={'status':'error','error':str(e)[:220],'checked_epoch':now,'checked_at':datetime.now(timezone.utc).isoformat(),'stale':bool(old and old.get('data'))}
  if old and old.get('data'):result['data']=old['data']
 with LOCK:CACHE[key]=result
 return result

def get_enfen():
 raw,_=fetch(URLS['enfen']);page=raw.decode('utf-8','replace')
 # Extract link + heading in both common markup orders; fallback is the archive URL.
 anchors=re.findall(r'<a\b([^>]*)>(.*?)</a>',page,re.I|re.S)
 out=[]
 for attrs,inside in anchors:
  title=re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',inside))).strip()
  if not re.search(r'comunicado\s+oficial|enfen\s+n[°ºo.]',title,re.I):continue
  m=re.search(r'href\s*=\s*["\']([^"\']+)',attrs,re.I)
  url=urllib.parse.urljoin(URLS['enfen'],html.unescape(m.group(1))) if m else URLS['enfen']
  if urllib.parse.urlsplit(url).scheme not in ('https','http'):url=URLS['enfen']
  if title and not any(x['title']==title for x in out):out.append({'title':title,'url':url})
 if not out:
  for x in re.findall(r'<h[1-4][^>]*>(.*?)</h[1-4]>',page,re.I|re.S):
   title=re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',x))).strip()
   if 'comunicado oficial' in title.lower():out.append({'title':title,'url':URLS['enfen']})
 if not out:raise ValueError('No se encontraron comunicados en el HTML')
 return {'items':out[:12],'source_url':URLS['enfen']}

def get_noaa():
 raw,_=fetch(URLS['noaa']);lines=raw.decode('utf-8','replace').splitlines()
 # NOAA CPC weekly: year week then SST and anomaly for 1+2, 3, 3.4 and 4.
 rows=[]
 for line in lines:
  parts=line.split()
  if len(parts)<10:continue
  try:
   year=int(parts[0]);date=parts[1];nums=[float(x) for x in parts[2:10]]
   if not (1980<=year<=2100 and re.fullmatch(r'\d{1,2}[A-Za-z]{3}\d{4}',date)):continue
   dt=datetime.strptime(date,'%d%b%Y').date().isoformat()
   rows.append({'date':dt,'nino12':nums[1],'nino34':nums[5],'sst12':nums[0],'sst34':nums[4]})
  except (ValueError,IndexError):continue
 if not rows:raise ValueError('Formato de la serie NOAA CPC no reconocido')
 rows.sort(key=lambda x:x['date']);return {'series':rows[-30:],'latest':rows[-1],'unit':'°C','period':'semanal','source_url':URLS['noaa']}

def get_indeci():
 # Server-side query: last 30 days based on SINPAD FECHA epoch ms, not first 100 historical rows.
 since=int((datetime.now(timezone.utc)-timedelta(days=30)).timestamp()*1000)
 where='FECHA >= '+str(since)
 params={'where':where,'outFields':'OBJECTID,FECHA,ANHO,MES,DEPARTAMENTO,PROVINCIA,DISTRITO,FENOMENO,IDE_SINPAD','returnGeometry':'true','outSR':'4326','orderByFields':'FECHA DESC','resultRecordCount':'200','f':'geojson'}
 url=URLS['indeci']+'?'+urllib.parse.urlencode(params)
 raw,_=fetch(url,limit=6000000,timeout=16);obj=json.loads(raw)
 if 'error' in obj:raise ValueError('ArcGIS: '+str(obj['error'].get('message','error')))
 if not isinstance(obj.get('features'),list):raise ValueError('GeoJSON no disponible')
 feats=[]
 for f in obj['features']:
  p=f.get('properties') or {};date=p.get('FECHA')
  try:
   stamp=float(date);stamp=stamp/1000 if stamp>1e11 else stamp
   if stamp < since/1000:continue
   p['fecha_iso']=datetime.fromtimestamp(stamp,timezone.utc).date().isoformat()
  except (TypeError,ValueError,OverflowError,OSError):continue
  feats.append(f)
 return {'features':feats,'count_sample':len(feats),'sample_only':True,'period_days':30,'source_url':'https://portal.indeci.gob.pe/'}

def get_news():
 # Headlines and publisher from an external RSS feed, never machine-invented summaries.
 q=urllib.parse.quote('fenómeno El Niño Perú lluvias SENAMHI ENFEN when:14d')
 url='https://news.google.com/rss/search?q='+q+'&hl=es-419&gl=PE&ceid=PE:es-419'
 raw,_=fetch(url,limit=1000000,timeout=12)
 root=ET.fromstring(raw);items=[]
 for node in root.findall('./channel/item')[:12]:
  title=(node.findtext('title') or '').strip();link=(node.findtext('link') or '').strip()
  pub=(node.findtext('pubDate') or '').strip();publisher=(node.findtext('source') or '').strip()
  if not title or not link.startswith('https://'):continue
  if publisher and title.endswith(' - '+publisher):title=title[:-(len(publisher)+3)]
  items.append({'title':title,'url':link,'publisher':publisher or 'Medio de prensa','published':pub})
 if not items:raise ValueError('Sin noticias disponibles en el RSS')
 return {'items':items[:7],'source_url':'https://news.google.com/'}

def get_forecast(region):
 lat,lon=REGIONS[region]
 params={'latitude':lat,'longitude':lon,'daily':'precipitation_sum,temperature_2m_max,temperature_2m_min','timezone':'America/Lima','forecast_days':7}
 url='https://api.open-meteo.com/v1/forecast?'+urllib.parse.urlencode(params)
 raw,_=fetch(url,timeout=13);data=json.loads(raw);d=data.get('daily',{})
 if not d.get('time'):raise ValueError('Pronóstico meteorológico no disponible')
 return {'region':region,'latitude':lat,'longitude':lon,'daily':d,'unit_precip':'mm/día','type':'pronóstico modelado (no observación)','source_url':PUBLIC['forecast'],'retrieved_at':datetime.now(timezone.utc).isoformat()}

OCEAN_BASE='https://coastwatch.pfeg.noaa.gov/erddap/wms/jplMURSST41anom1day/request'
def ocean_metadata():
 def load():
  url=OCEAN_BASE+'?service=WMS&request=GetCapabilities&version=1.3.0'
  raw,_=fetch(url,limit=18000000,timeout=16);root=ET.fromstring(raw);layers=[]
  for node in root.iter():
   if node.tag.rsplit('}',1)[-1]!='Layer':continue
   name=next((c.text for c in node if c.tag.rsplit('}',1)[-1]=='Name'),None)
   if name and 'anom' in name.lower():layers.append((node,name))
  if not layers:raise ValueError('Capa de anomalía no publicada')
  layer,name=layers[0];extent=None
  for node in layer.iter():
   if node.tag.rsplit('}',1)[-1] in ('Dimension','Extent') and node.attrib.get('name','').lower()=='time':extent=(node.text or '').strip();break
  if not extent:raise ValueError('NOAA no publicó fecha de capa')
  last=extent.split(',')[-1].split('/')[-1].strip()
  if not re.match(r'^\d{4}-\d{2}-\d{2}',last):raise ValueError('Fecha NOAA no reconocida')
  return {'layer':name,'time':last,'source_url':PUBLIC['ocean']}
 return cached('ocean',load,TTL['ocean'])

def ocean_image(query):
 meta=ocean_metadata()
 if meta['status']!='ok' and not meta.get('data'):raise ValueError(meta.get('error','NOAA no disponible'))
 args=urllib.parse.parse_qs(query);bbox=[float(x) for x in args.get('bbox',[''])[0].split(',')]
 if len(bbox)!=4 or not(-180<=bbox[0]<bbox[2]<=180 and -90<=bbox[1]<bbox[3]<=90):raise ValueError('bbox inválido')
 w=max(200,min(1100,int(args.get('width',['900'])[0])));h=max(200,min(900,int(args.get('height',['600'])[0])))
 m=meta['data'];params={'service':'WMS','version':'1.1.1','request':'GetMap','layers':m['layer'],'styles':'','format':'image/png','transparent':'TRUE','srs':'EPSG:4326','bbox':','.join(map(str,bbox)),'width':w,'height':h,'time':m['time']}
 raw,_=fetch(OCEAN_BASE+'?'+urllib.parse.urlencode(params),limit=8000000,timeout=20)
 if not raw.startswith(b'\x89PNG'):raise ValueError('El WMS no devolvió PNG')
 return raw

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(BASE),**kwargs)
 def send_json(self,data,code=200):
  raw=json.dumps(data,ensure_ascii=False).encode();self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  path=urllib.parse.urlsplit(self.path);p=path.path
  if p=='/api/ocean-map':
   try:
    raw=ocean_image(path.query);self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Cache-Control','public, max-age=600');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
   except Exception as e:self.send_json({'error':str(e)},503)
   return
  if p=='/api/ocean-meta':return self.send_json(ocean_metadata())
  if p=='/api/status':
   data={'enfen':cached('enfen',get_enfen,TTL['enfen']),'noaa':cached('noaa',get_noaa,TTL['noaa']),'indeci':cached('indeci',get_indeci,TTL['indeci']),'news':cached('news',get_news,TTL['news'])}
   # WIS2 is intentionally not queried: previous endpoint repeatedly timed out; official portal always accessible as a link.
   data['senamhi']={'status':'portal','source_url':PUBLIC['senamhi'],'message':'Consulta de avisos en el portal oficial; API WIS2 no verificada'}
   return self.send_json({'sources':data,'server_time':datetime.now(timezone.utc).isoformat()})
  if p=='/api/forecast':
   region=urllib.parse.parse_qs(path.query).get('region',['lima'])[0]
   if region not in REGIONS:return self.send_json({'error':'Región no admitida'},400)
   return self.send_json(cached('forecast:'+region,lambda:get_forecast(region),TTL['forecast']))
  if p=='/api/health':return self.send_json({'status':'ok','version':'1.4','server_time':datetime.now(timezone.utc).isoformat()})
  return super().do_GET()
if __name__=='__main__':
 port=int(os.environ.get('PORT',8080));print('Observatorio 1.4 en puerto',port,flush=True)
 ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
