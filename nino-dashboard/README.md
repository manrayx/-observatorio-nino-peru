# Observatorio El Niño — GRUPO EVIDENCIA · v1.4

## Instalación
Python 3.10+, sin dependencias externas. `python app.py` inicia en el puerto definido por `PORT` (8080 por defecto). Render: directorio raíz `nino-dashboard`, start command `python app.py`. Reemplazar `app.py` e `index.html` en el mismo directorio de GitHub. No subir la carpeta contenedora.

## Funcionalidades
- NOAA CPC: anomalías semanales Niño 1+2 y Niño 3.4, gráfico de las últimas 30 semanas.
- NOAA CoastWatch: superposición WMS de anomalías SST mediante proxy `/api/ocean-map`; su disponibilidad y configuración de capa deben validarse en Render.
- ENFEN: título y enlace a comunicado si el archivo publica una URL detectable. No se inventa sumilla del PDF.
- INDECI: consulta de los últimos 30 días, limitada a 200 registros; no equivale al total nacional. Los registros sin coordenadas válidas no aparecen en mapa.
- Open-Meteo: pronóstico modelado de 7 días para ocho ciudades peruanas; no es observación de SENAMHI.
- SENAMHI: acceso directo a portal oficial. El servicio WIS2 previo agotaba el tiempo de espera y no se anuncia como conectado.
- Noticias: RSS de Google News filtrado por Perú y El Niño; titulares originales, editor y enlace. Puede fallar o incluir artículos tangenciales; no constituye verificación editorial.

## Limitaciones y validación
Los servicios externos no son controlados por GRUPO EVIDENCIA. El entorno de desarrollo no pudo conectarse a ellos; validar `/api/status`, `/api/forecast?region=lima`, `/api/ocean-meta` y la imagen WMS en Render. Los mensajes de error son visibles; nunca se generan mediciones ficticias. Los resúmenes ENFEN solo pueden mostrarse cuando se implemente extracción y verificación de PDFs. No se ha integrado NASA IMERG en un mapa operativo porque algunos productos requieren registro y acceso específico; se enlaza la documentación oficial.

## Prueba local
`python -m py_compile app.py` y abrir http://localhost:8080. Verificar enlaces y capas después del despliegue.
