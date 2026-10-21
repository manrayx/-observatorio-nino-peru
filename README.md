# Observatorio El Niño Perú — versión correctiva 1.5

## Correcciones
- NOAA CPC: parser corregido para el formato REAL de `wksst9120.for` (fecha al inicio de cada fila; sin columna de año). Serie de 52 semanas, Niño 1+2 y Niño 3.4.
- INDECI: consulta ArcGIS JSON con orden por fecha y filtrado local de los últimos 30 días. Los resultados son una muestra limitada a los 500 registros más recientes; nunca se interpretan como total nacional.
- Mapa: se retira la falsa promesa de un raster satelital operativo. Se muestra la región Niño 1+2 auténtica (0–10°S, 90–80°O) con el valor semanal NOAA, más los puntos recientes INDECI si la fuente funciona. La región puede quedar fuera del encuadre de Lima; usa la vista Niño 1+2.
- Si INDECI falla, se muestra “—”, nunca “0”.

## Publicación
Reemplazar `app.py`, `index.html` y opcionalmente `README.md` dentro de `nino-dashboard` en GitHub. Mantener `render.yaml`. Render redespliega automáticamente si está configurado para ello.

## Limitaciones verificables
No se ha confirmado desde Render la disponibilidad de los servicios externos. El mapa oceánico es un indicador regional NOAA, NO una imagen satelital. SENAMHI continúa como enlace al portal oficial, sin API automática. Los titulares RSS pueden fallar por bloqueos del proveedor. No usar el muestreo INDECI como estadística oficial.

## Pruebas
`python -m py_compile app.py`; `python app.py`; revisar `/api/status`, `/api/forecast?region=lima`, `/api/health`.
