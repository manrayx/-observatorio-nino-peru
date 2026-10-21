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
