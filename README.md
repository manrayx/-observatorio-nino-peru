# Monitor El Niño · Grupo Evidencia — versión 2.0

Monitor independiente de datos públicos sobre El Niño en el Perú. **No es un servicio de pronóstico**: muestra lo que miden NOAA y la NASA, lo que calcula un modelo meteorológico (con su rango de incertidumbre) y lo que dice oficialmente ENFEN.

## Dos vistas
- **`/` · Para todos** (celular primero): tu ciudad y su semáforo, titular automático, "¿está empeorando?", "¿va a llover?", "¿qué dicen las autoridades?", comparación con 1983, 1998, 2017 y 2023, lo nuevo de la semana, preguntas frecuentes, qué hacer y números de emergencia, compartir por WhatsApp o como imagen.
- **`/detalle` · Vista detallada** (periodistas y empresas): mapa con capas (mar, lluvia que cayó, lluvia esperada, emergencias por clima, sismos), semáforo por región, pronóstico de 7 días con rangos, serie de todos los años desde 1981, datos descargables y conexión MCP.

## Fuentes
| Dato | Fuente | Tipo |
|---|---|---|
| Temperatura del mar semanal (Niño 1+2 y 3.4), desde 1981 | NOAA CPC `wksst9120.for` | Observación (automática) |
| Mapa del mar | NASA GIBS · MUR SST | Satélite (automática) |
| Lluvia que cayó | NASA GIBS · IMERG | Satélite (automática) |
| Lluvia esperada y temperatura | Open-Meteo; rangos con el ensamble ECMWF (51 escenarios, percentiles 10/50/90) | Modelo (automática) |
| Estado de alerta, magnitud prevista, lluvias por zona, próximo comunicado | ENFEN, comunicado oficial | **Transcrito a mano** en `oficial.json` |
| Lista de comunicados | Página de comunicados de ENFEN | Automática |
| Emergencias | GDACS (ONU / Comisión Europea); solo las de clima en la vista principal | Automática |
| Noticias | Google News RSS | Automática |

## Mantenimiento: cuando ENFEN publica un comunicado nuevo
Edita `oficial.json` (número, fecha, enlace, estado de alerta, magnitud, duración, lluvias por zona y fecha del próximo comunicado), copiando lo que dice ENFEN, y súbelo a GitHub. Render lo publica solo. Si no se actualiza, la vista detallada avisa cuando detecta un comunicado más reciente en la web de ENFEN.

## Semáforo (referencial, no es una alerta oficial)
- **Cuidado:** el escenario central del modelo prevé lluvia fuerte en los próximos 3 días.
- **Atento:** lluvia moderada prevista, o ENFEN prevé lluvias por encima de lo normal en la zona.
- **Tranquilo:** en los demás casos.
Umbrales diarios de referencia — costa (desierto): ligera ≥0,5 mm, moderada ≥2 mm, fuerte ≥10 mm; sierra y selva: ligera ≥1 mm, moderada ≥10 mm, fuerte ≥30 mm.

## Publicación
Los archivos `app.py`, `mcp_server.py`, `index.html`, `detalle.html`, `oficial.json`, `README.md` y `render.yaml` van en la **raíz** del repositorio. Con Auto-Deploy activado, Render publica cada cambio. Comprobar en `/api/health` que la versión sea 2.0.

## Endpoints
`/api/status` · `/api/rain-map` (con rangos) · `/api/forecast?region=lima` (con rangos) · `/api/historia` · `/api/datos/mar.csv` · `/api/datos/ciudades.csv` · `/api/health` · `/mcp`

## Servidor MCP
`https://observatorio-nino-peru.onrender.com/mcp` — protocolo 2026-07-28 y clientes anteriores (2025-03-26 a 2025-11-25). Solo lectura.

| Herramienta | Qué devuelve |
|---|---|
| `estado_el_nino` | Anomalía de la semana en Niño 1+2 y Niño 3.4, con categoría referencial |
| `serie_temperatura_mar` | Serie semanal desde 1981 (`indice`, `desde`, `hasta`) |
| `perspectiva_oficial_enfen` | Lo que dice el último comunicado de ENFEN (transcrito) |
| `pronostico_ciudad` | 7 días de lluvia (con rango 10/50/90) y temperatura para una de las 12 ciudades |
| `lluvia_esperada_ciudades` | Lluvia esperada en 3 días por ciudad |
| `emergencias_recientes` | Eventos GDACS de 60 días; por defecto solo los de clima |
| `comunicados_enfen` | Últimos comunicados oficiales de ENFEN |

**Conectarlo en Claude:** Configuración → Conectores → Agregar conector personalizado → pegar la URL.

## Limitaciones
- La temperatura del mar es un dato semanal; la categoría semanal es referencial (la clasificación oficial es el ICEN de ENFEN, mensual).
- El pronóstico es de un modelo global sin corrección local; para decisiones, seguir los avisos de SENAMHI.
- GDACS no registra cada emergencia local. La base pública de INDECI se actualiza con meses de retraso, por eso no se usa para contar emergencias.
- En el plan gratuito de Render el servidor se duerme tras 15 minutos sin visitas; la primera visita puede tardar ~1 minuto.
