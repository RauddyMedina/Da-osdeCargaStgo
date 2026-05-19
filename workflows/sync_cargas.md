# Workflow: Sincronización de Cargas desde Outlook

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
