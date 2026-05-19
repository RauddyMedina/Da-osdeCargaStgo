# Deploy en Render

Guía paso-a-paso para publicar la app en https://render.com con disco persistente
(la DB SQLite y las fotos sobreviven entre deploys).

## Antes de empezar

- Cuenta de GitHub (repo privado).
- Cuenta de Render (https://render.com — se loguea con GitHub).
- El proyecto en este folder, con los archivos: `Procfile`, `render.yaml`,
  `.streamlit/config.toml`, `.env.example`, `requirements.txt`.
- Tu DB local (`data/declaracion.db`) y carpeta de fotos (`data/fotos/`).
  Las vas a subir manualmente al disco persistente después del primer deploy.

## Paso 1 — Subir el código a GitHub

Desde la carpeta del proyecto:

```powershell
git init
git add .
git commit -m "Initial commit: app lista para Render"
git branch -M main

# Crea un repo privado en https://github.com/new (sin README, sin gitignore — ya los tienes)
git remote add origin https://github.com/TU_USUARIO/declaracion-danos.git
git push -u origin main
```

⚠️ El `.gitignore` excluye `data/` (DB y fotos) y `.env` (secretos). Eso es correcto;
la data va al disco persistente de Render, no al repo.

## Paso 2 — Crear el servicio en Render

Opción A — desde el `render.yaml` (recomendado):

1. Login en Render → **New +** → **Blueprint**.
2. Conecta tu repo de GitHub.
3. Render detecta `render.yaml` y propone crear el servicio + disco. Aceptar.
4. Se queda "esperando variables" porque algunas tienen `sync: false`.

Opción B — manual desde la UI:

1. **New +** → **Web Service** → conecta el repo.
2. Configura:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `streamlit run app/streamlit_app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
   - **Health Check Path**: `/_stcore/health`
   - **Plan**: Starter ($7/mes)
3. En la sección **Disks** → agregar:
   - **Mount Path**: `/var/data`
   - **Size**: 1 GB

## Paso 3 — Configurar variables de entorno

En el dashboard del servicio → **Environment** → agregar:

| Variable | Valor |
|---|---|
| `DATA_DIR` | `/var/data` |
| `APP_PASSWORD` | (escoge un password robusto, mínimo 12 chars) |
| `MIN_FOTOS_POR_CARGA` | `1` |
| `OUTLOOK_EMAIL` | tu correo de Outlook |
| `OUTLOOK_PASSWORD` | tu password o app password de Outlook |
| `SMTP_SERVER` | `smtp.office365.com` |
| `SMTP_PORT` | `587` |
| `DESTINATARIOS_DANOS` | lista separada por comas |
| `REMITENTE_DANOS` | (opcional, si distinto de OUTLOOK_EMAIL) |
| `GOOGLE_SHEET_ID` | tu Sheet ID |
| `GOOGLE_SHEET_TAB_HISTORICO` | `HISTORICO_DANOS_ANDEN` |

Para Google Sheets en Render, lo más limpio es usar **Service Account** en vez
de OAuth interactivo:

1. Crea un Service Account en Google Cloud Console.
2. Comparte tu Sheet con el email del Service Account (permiso Editor).
3. Descarga el JSON, abrelo y pega TODO el contenido en una variable:
   `GOOGLE_SERVICE_ACCOUNT_JSON` (un solo string).
4. Hay que adaptar `append_carga_to_sheet.py` para leer credenciales desde
   esa variable en vez de `credentials.json`. Si todavía no lo necesitas,
   puedes deshabilitar el append: no setees `GOOGLE_SHEET_ID`.

## Paso 4 — Primer deploy

Render arranca el servicio. Ver logs en la pestaña **Logs**.

Cuando veas `You can now view your Streamlit app in your browser`, abre la URL
`https://declaracion-danos.onrender.com` (el nombre exacto te lo da Render).

Te debería pedir el `APP_PASSWORD` → luego el selector de operario → app lista.

⚠️ La DB todavía está VACÍA porque acabamos de crear el disco. Próximo paso.

## Paso 5 — Migrar tu data local al disco persistente

Opciones:

**A — Subir DB y fotos a Render Shell** (gratis, manual):

1. En el dashboard → **Shell** (tab al lado de Logs).
2. Subes los archivos con `curl` desde algún hosting temporal, o usas un
   bucket S3/Cloudinary intermedio.

**B — Cargar todo desde `seed_usuarios.py` + sync de Outlook** (recomendado):

Si los datos en tu DB local vinieron originalmente del sync de Outlook,
puedes empezar de cero:

```
# En la Shell de Render:
python tools/seed_usuarios.py
python tools/sync_cargas_outlook.py   # requiere creds MS_*
```

**C — SCP/rsync vía un instance temporal** (avanzado, si tienes data crítica).

## Paso 6 — Verificación end-to-end

Desde el celular:

1. Abrir `https://tu-app.onrender.com`
2. Ingresar password
3. Seleccionar operario
4. Crear una carga de prueba (o esperar a que llegue por sync de Outlook)
5. Declarar daños con los checkboxes
6. Adjuntar una foto desde galería
7. Finalizar carga
8. En el panel Admin, "Enviar consolidado" para validar SMTP

## Notas operativas

- **Free tier no sirve** — duerme tras 15min de inactividad. Necesitas Starter mínimo.
- **Backup del disco**: Render hace snapshots automáticos en planes pagos.
  Igual recomendable bajar periódicamente `/var/data/declaracion.db` por
  Shell + `curl --upload-file` a un bucket.
- **Logs**: la pestaña **Logs** muestra stdout/stderr. Útil para debuggear
  errores de SMTP, Sheets, etc.
- **Dominio propio**: Settings → Custom Domain. HTTPS automático con Let's Encrypt.
- **Apagar app temporalmente**: Settings → Suspend Service (no se cobra mientras esté suspendido,
  pero el disco SÍ se cobra ~$0.25/mes por GB).

## Costos estimados

| Item | Costo |
|---|---|
| Web service Starter | $7/mes |
| Disco persistente 1 GB | $0.25/mes |
| **Total** | **~$7.25/mes** |

Si necesitas más RAM (uploads grandes, muchos usuarios concurrentes),
considera el plan Standard ($25/mes).
