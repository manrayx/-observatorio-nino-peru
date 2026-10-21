# Observatorio El Niño Perú — versión 1.8

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
Los archivos `app.py`, `mcp_server.py`, `index.html`, `README.md` y `render.yaml` van en la **raíz** del repositorio (Render ejecuta la raíz salvo que se configure *Root Directory*). Luego, en Render: *Manual Deploy → Deploy latest commit*. Comprobar en `/api/health` que la versión sea 1.8.

## Endpoints
`/api/status` (NOAA, ENFEN, GDACS, INDECI, noticias) · `/api/rain-map` · `/api/forecast?region=lima` · `/api/health`

## Servidor MCP (versión 1.7)
El observatorio expone sus datos a asistentes de IA (Claude, ChatGPT u otros compatibles con MCP) en:

`https://observatorio-nino-peru.onrender.com/mcp`

Implementado en `mcp_server.py`, sin dependencias externas. Compatible con el protocolo MCP 2026-07-28 (sin sesiones, metadatos por solicitud, `server/discover`) y con clientes anteriores (2025-03-26 a 2025-11-25, con `initialize`). Solo lectura.

| Herramienta | Qué devuelve |
|---|---|
| `estado_el_nino` | Anomalía de la semana en Niño 1+2 y Niño 3.4, con categoría referencial |
| `serie_temperatura_mar` | Serie semanal desde 1981 (`indice`, `desde`, `hasta`); por defecto, últimas 52 semanas |
| `pronostico_ciudad` | 7 días de lluvia y temperatura para una de las 12 ciudades |
| `lluvia_esperada_ciudades` | Lluvia total esperada en 3 días por ciudad |
| `emergencias_recientes` | Eventos GDACS de los últimos 60 días (filtro opcional por tipo) |
| `comunicados_enfen` | Últimos comunicados oficiales de ENFEN |

**Conectarlo en Claude:** Configuración → Conectores → Agregar conector personalizado → pegar la URL de arriba.

Notas: el plan gratuito de Render duerme el servidor; la primera consulta puede tardar ~1 minuto (si falla, reintentar). Límite de ~60 consultas por minuto por IP. Para permitir otros orígenes de navegador, definir la variable de entorno `MCP_ALLOWED_ORIGINS` (lista separada por comas).
