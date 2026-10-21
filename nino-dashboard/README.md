# Observatorio El Niño Perú — MVP 1.0

## Ejecutar localmente
Requiere Python 3.10+; sin dependencias Python externas.

```bash
python app.py
```

Abrir http://localhost:8080

## Publicar en Render
1. Subir esta carpeta a un repositorio de GitHub.
2. Render → New → Web Service → conectar repositorio.
3. Runtime: Python; Build Command: `echo ready`; Start Command: `python app.py`.
4. Render suministra `PORT`. Utilizar instancia siempre activa para recolección periódica; los planes que duermen no garantizan sondeo permanente.
5. Configurar dominio personalizado y HTTPS desde el proveedor.

## Arquitectura
Navegador (HTML, JS, Leaflet/OpenStreetMap) → backend HTTP Python → conectores ENFEN, SENAMHI WIS2 OGC API, INDECI ArcGIS REST. Caché en memoria TTL 30 minutos; proceso de actualización cada 30 minutos. La caché se pierde al reiniciar y no constituye una base histórica. La API `/api/status` expone datos, marca temporal, errores y URL de origen.

## Límites actuales
- ENFEN: se recuperan títulos, no se interpreta automáticamente el contenido PDF ni se determina su alerta actual.
- SENAMHI: se solicitan hasta 50 observaciones de una colección; la estructura y disponibilidad del endpoint pueden variar. No hay series históricas ni índices agregados.
- INDECI: hasta 100 registros de una capa sin filtrado temporal ni tipológico; no son necesariamente emergencias activas. La capa puede cambiar de estructura.
- No hay todavía pronóstico local, riesgo compuesto, avisos push, persistencia histórica ni alertas sobre infraestructura.
- Fuentes externas pueden bloquear peticiones o cambiar formatos. El dashboard muestra el fallo, no datos fabricados.
- Para producción: base PostgreSQL/Timescale, scheduler independiente, paginación y normalización por fecha, límites de solicitudes, validación de esquemas, observabilidad, pruebas, y permisos/CORS.


## Versión 1.2: mapa oceánico NOAA
- Muestra anomalías SST MUR de NOAA CoastWatch mediante WMS, centrado inicialmente en la costa del Perú y Pacífico oriental.
- `/api/ocean-meta` lee GetCapabilities y descubre capa y fecha; `/api/ocean-map` obtiene imagen WMS de NOAA para la ventana cartográfica.
- El mapa **no** constituye alerta ENFEN; la capa depende de disponibilidad externa. Si NOAA falla, aparece un mensaje, sin inventar datos.
- Para actualizar GitHub/Render, reemplazar `app.py` e `index.html` en la carpeta `nino-dashboard/`.
- Pruebas: `python -m py_compile app.py`, abrir `/api/ocean-meta`, verificar `ok: true`, abrir mapa y confirmar `capa cargada`.
- Esta entrega se probó localmente en sintaxis y estructura; la red de ejecución no permitió comprobar solicitudes en vivo a NOAA.
