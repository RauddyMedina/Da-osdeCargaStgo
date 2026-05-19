# Workflow: Envío del Correo Consolidado (Supervisor)

## Objetivo
Enviar UN solo correo consolidado del día con todas las cargas finalizadas con daños, adjuntando las fotos de las hojas de carga.

## Cuándo se envía
**Manualmente** desde la tab **Admin** de la app. El supervisor presiona el botón cuando considera cerrado el turno.

## Tool subyacente
```bash
python tools/send_consolidado_email.py [--dry-run]
```

## Qué incluye el correo

### Asunto
```
Respaldo de Productos declarados con daños de embalaje en andenes DD-MM-YYYY
```
(fecha = día actual de envío)

### Cuerpo HTML
Por cada carga finalizada con `sin_danos=0` y `enviada_at IS NULL`:
- Bloque verde con `DD-MM-YYYY` y `CARGA:<numero>`
- Tabla `OP/CL | DAÑO` con cada entrega declarada

Formato visual idéntico al ejemplo `Captura.JPG` recibido históricamente de Easy.

### Adjuntos
Todas las fotos (`fotos_carga.ruta_archivo`) de las cargas incluidas.
- Si el total supera 20 MB, se comprimen con Pillow (JPEG quality=70)

### Destinatarios
Definidos en `.env` como `DESTINATARIOS_DANOS` (lista separada por comas).

## Después del envío
Las cargas incluidas se marcan con `enviada_at=CURRENT_TIMESTAMP`. Ya no se pueden reabrir ni modificar desde la app.

## Cargas EXCLUIDAS del correo
- Cargas con `sin_danos=1` → solo van al Sheet histórico
- Cargas aún en `por_declarar` → no entran al consolidado
- Cargas ya enviadas anteriormente → tienen `enviada_at IS NOT NULL`

## Re-envío
Si se finalizan más cargas después del envío inicial, presionar de nuevo "Enviar consolidado del día" envía un **segundo correo** solo con las nuevas cargas (no repite las ya enviadas).

## Vista previa (dry-run)
Botón **"🔎 Vista previa (dry-run)"** en la tab Admin permite ver cuántas cargas y fotos se incluirían **sin enviar** el correo.

## Configuración SMTP
```
SMTP_SERVER=smtp.office365.com
SMTP_PORT=587
OUTLOOK_EMAIL=ext_rauddy.medina@transyanez.cl
OUTLOOK_PASSWORD=<password>
```

⚠️ Si SMTP de Office 365 está bloqueado por políticas corporativas (Modern Authentication / MFA estricto), reemplazar el bloque SMTP en `send_consolidado_email.py` por una llamada a `POST /me/sendMail` de Microsoft Graph reutilizando `auth_microsoft.py`.
