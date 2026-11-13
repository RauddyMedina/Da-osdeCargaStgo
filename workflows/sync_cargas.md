# Workflow: Sincronización de Cargas desde Outlook

## Por dónde entran las cargas (hay tres vías)

| Vía | Quién la dispara | Estado |
|---|---|---|
| **PC** — `tools/sync_and_push.py` (Outlook COM → base local → `POST /api/import`) | el PC de Rauddy | la de siempre; si el PC no corre, no entra nada |
| **Cron IMAP** — `sync-cargas-imap` del `render.yaml` | Render, cada hora | **muerto**: el tenant bloquea la auth básica de IMAP |
| **Panel web** — `inventario.fluxaia.cloud/bases`, tarjetas WMS y Metabase → `POST /api/import-archivo` | quien sube el Excel a mano | escrita el 27-10-2026, **viva recién desde el 13-11-2026** |

> **Lo que costó caro (26-10-2026):** la carga del WMS se subió por el panel web, que
> hasta ese día sólo escribía en el Google Sheet. En el andén no se pudo declarar nada
> porque acá no había llegado **ninguna** de las 6 cargas, y el cron IMAP tampoco traía
> nada desde el 24. De ahí sale `/api/import-archivo`.

> **Lo que costó caro de nuevo (12-11-2026):** `/api/import-archivo` existía en el disco
> y **nunca se había pusheado** a `RauddyMedina/Da-osdeCargaStgo`, que es lo que Render
> despliega. O sea que la vía web contestaba **405** desde el día uno y el aviso a Daños
> fallaba siempre. Las 5 cargas del 12-11 hubo que empujarlas armando el payload
> `{cargas, items}` a mano contra `/api/import`.
>
> **Dos cosas que hay que recordar de ese arreglo:**
> 1. Render **solo despliega al pushear**: un endpoint nuevo sin push no existe. La forma
>    de comprobarlo en un minuto es pegarle con un token falso — **401** significa que la
>    ruta está; **405** significa que no está y lo atendió Streamlit.
> 2. En Tornado hay que registrar `/api/import-archivo` **antes** que `/api/import`:
>    `PathMatches(r"/api/import")` no ancla el final y se come la otra ruta.

**El archivo se parsea SIEMPRE acá** (`tools/ingest_archivo.py`), venga del PC o de la
web. Es a propósito: con dos parsers, el día que el WMS cambie un encabezado una vía
carga y la otra se queda muda sin que nadie se entere.

⚠️ **La fecha manda.** El panel web manda la *fecha del correo* que eligió quien sube, y
la pantalla de daños filtra por fecha **exacta**: si se sube el correo de ayer con la
fecha de hoy, las cargas quedan en el día equivocado y en el andén parece que faltan.

## Objetivo
Leer correos nuevos de la carpeta `EasyGo` en Outlook 365, descargar el adjunto Excel/CSV con el detalle de la carga liberada, y poblar las tablas `cargas` e `items` en SQLite.

## Inputs
- Cuenta Outlook configurada en `.env` del padre (`OUTLOOK_EMAIL`, `MS_CLIENT_ID`, `MS_TENANT_ID`)
- Variable `OUTLOOK_FOLDER` (default `EasyGo`)
- Token MSAL cacheado en `.tmp/ms_token_cache.json` (se genera al primer device-code flow)

## Tool a ejecutar
```bash
python tools/sync_cargas_outlook.py
```

También se puede disparar desde la app vía el botón ↻ Sincronizar.

## Filtros aplicados
- Asunto matchea regex: `Envío de guías de despachos|Easy ?Go|Detalle carga` (case-insensitive)
- Tiene adjuntos (`hasAttachments=true`)
- `message-id` no está en la tabla `processed_emails`

## Outputs
- Filas nuevas en `cargas` (1 por número de carga único)
- Filas nuevas en `items` (1 por línea del Excel)
- Adjuntos guardados en `.tmp/correos_descargados/`
- Logs en stdout con resumen: correos procesados, cargas nuevas, items nuevos

## Edge cases
| Caso | Comportamiento |
|---|---|
| Excel sin columna `NUMERO CARGA` o `ENTREGA` | Se omite el archivo con warning, NO se marca como procesado |
| Múltiples correos para la misma carga | El segundo es idempotente (ON CONFLICT IGNORE) |
| Adjunto en formato distinto a CSV/XLSX | Se descarga pero se ignora |
| Fecha del correo (`receivedDateTime`) | Se usa como `fecha_correo` de la carga (≠ FECHA de despacho del Excel) |

## Re-ejecución
El script es idempotente. Se puede correr múltiples veces al día — solo procesará correos no vistos. Para reprocesar un correo, eliminar manualmente su `message_id` de `processed_emails`.

## Cuándo correrlo
- Manual: cada vez que el operario presiona ↻ en la app
- Automático (opcional, futuro): cron cada 10 min con `python tools/sync_cargas_outlook.py`
