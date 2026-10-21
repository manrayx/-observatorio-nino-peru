import os,json,time,threading,re,urllib.request,urllib.parse,html
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

def fetch(url):
 req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; PeruNinoMonitor/1.0)','Accept':'application/json,text/html,*/*'})
 with urllib.request.urlopen(req,timeout=18) as r: return r.read(3_000_000),r.headers.get('Content-Type','')

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

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(BASE),**kwargs)
 def do_GET(self):
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
