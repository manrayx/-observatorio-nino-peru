# Observatorio El Niño Perú — versión 1.6

Dashboard de seguimiento de El Niño para el Perú: temperatura del mar, lluvias esperadas, emergencias y comunicados oficiales.

## Qué muestra y de dónde sale
| Panel | Fuente | Notas |
|---|---|---|
| Mar costa norte (Niño 1+2) y Pacífico central (Niño 3.4) | NOAA CPC, archivo semanal `wksst9120.for` | Anomalía frente al promedio 1991–2020. La etiqueta (normal, cálido débil…) usa la escala ICEN de ENFEN aplicada al dato semanal: es referencial. |
| Comunicado ENFEN | Página de comunicados de ENFEN | Se enlaza el más reciente. |
| Mapa · temperatura del mar | NASA GIBS (MUR SST, anomalía diaria) | Se carga directo en el navegador; imagen más reciente disponible (1–2 días de retraso). |
| Mapa · lluvia 3 días y pronóstico 7 días | Open-Meteo | Pronóstico de modelo para 12 ciudades, no observación. |
| Emergencias y desastres | GDACS (ONU / Comisión Europea) | Eventos de impacto relevante en Perú, últimos 60 días. No incluye cada emergencia local. |
| Nota INDECI | Servicio ArcGIS público de INDECI | Su base pública se actualiza con meses de retraso (último registro: 12/05/2026 al 21/10/2026), por eso no se usa para contar emergencias actuales. Se muestra la fecha de su registro más reciente. |
| Noticias | Google News RSS | Titulares enlazados a la fuente original. |

## Publicación
Los archivos `app.py`, `index.html`, `README.md` y `render.yaml` van en la **raíz** del repositorio (Render ejecuta la raíz salvo que se configure *Root Directory*). Luego, en Render: *Manual Deploy → Deploy latest commit*. Comprobar en `/api/health` que la versión sea 1.6.

## Endpoints
`/api/status` (NOAA, ENFEN, GDACS, INDECI, noticias) · `/api/rain-map` · `/api/forecast?region=lima` · `/api/health`
