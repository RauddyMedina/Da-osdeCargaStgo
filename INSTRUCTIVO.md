# Instructivo: App Declaración de Daños de Carga en Andén

**Proyecto:** DeclaracionCargaDanosStg  
**Fecha:** 18-05-2026  
**Desarrollado por:** Claude (Anthropic) + Rauddy Medina

---

## ¿Qué hace esta app?

Permite que los operarios del andén declaren daños de embalaje en las cargas liberadas por Easy/Cencosud, directamente desde el celular. Al final del turno, el supervisor envía un correo consolidado con todos los daños declarados y las fotos de respaldo.

**Flujo completo:**
1. Easy Chile envía correos con cargas liberadas a la carpeta `EasyGo` en Outlook
2. La app sincroniza esas cargas automáticamente
3. Los operarios declaran daños por número de ENTREGA y toman foto de la hoja de carga
4. El supervisor envía el correo consolidado del día a todos los destinatarios

---

## Acceso a la app

**Desde cualquier celular (cualquier red):**
```
https://stooge-haiku-startup.ngrok-free.dev
```

**Desde la PC local:**
```
http://localhost:8504
```

---

## Estructura del proyecto

```
DeclaracionCargaDanosStg/
├── app/
│   └── streamlit_app.py          ← App principal (PWA mobile)
├── tools/
│   ├── db.py                     ← Base de datos SQLite (schema + helpers)
│   ├── seed_usuarios.py          ← Carga los operarios iniciales
│   ├── sync_cargas_outlook.py    ← Lee correos EasyGo y carga cargas en BD
│   ├── append_carga_to_sheet.py  ← Guarda historial en Google Sheets
│   └── send_consolidado_email.py ← Genera y envía el correo consolidado
├── workflows/
│   ├── sync_cargas.md            ← SOP de sincronización
│   ├── declarar_danos.md         ← SOP del operario (cómo usar la app)
│   └── enviar_consolidado.md     ← SOP del cierre de día
├── data/
│   ├── declaracion.db            ← Base de datos SQLite (persistente)
│   └── fotos/                    ← Fotos de hojas de carga
├── .tmp/
│   └── correos_descargados/      ← CSVs descargados de Outlook
├── .env                          ← Variables de entorno del proyecto
├── .env.example                  ← Plantilla de variables
├── requirements.txt              ← Dependencias Python
├── README.md                     ← Guía técnica rápida
└── INSTRUCTIVO.md                ← Este archivo
```

---

## Requisitos para funcionar

| Requisito | Estado |
|---|---|
| Python 3.12+ instalado | ✅ |
| Outlook Desktop abierto con cuenta `ext_rauddy.medina@transyanez.cl` | ✅ Necesario para sync |
| Streamlit corriendo (`streamlit run app/streamlit_app.py`) | ✅ Automático al iniciar PC |
| ngrok activo (túnel al link fijo) | ✅ Automático al iniciar PC |

---

## Inicio automático al encender la PC

Se crearon dos scripts en la carpeta de inicio de Windows que se ejecutan solos al iniciar sesión:

| Archivo | Qué hace |
|---|---|
| `shell:startup\streamlit-danos-anden.vbs` | Levanta la app Streamlit en background |
| `shell:startup\ngrok-danos-anden.vbs` | Activa el túnel ngrok con el link fijo |

**No necesitas abrir ninguna terminal.** Enciende la PC, inicia sesión, y la app queda disponible en el link de arriba en ~30 segundos.

---

## Operarios del andén

Lista inicial cargada en el sistema:
- Vicente Caniullan
- Benjamin
- Maryari

Para agregar un operario nuevo, editar el archivo `tools/seed_usuarios.py` y volver a ejecutarlo:
```powershell
cd c:\Users\Usuario\Documents\claude\DeclaracionCargaDanosStg
python tools/seed_usuarios.py
```

---

## Cómo usar la app (operario)

### 1. Login
- Abrir el link en el celular
- Seleccionar tu nombre
- Presionar **"Rutas Disponibles"**

### 2. Pantalla de cargas
- Aparecen las cargas del día con el número de entregas
- Usar las flechas **◄ ►** para ver cargas de días anteriores
- Presionar **↻ Sincronizar** para cargar nuevas cargas que llegaron por correo
- Tabs: **Por declarar** / **Finalizados** / **Admin**

### 3. Declarar daños en una carga
- Presionar **"Abrir"** en la carga deseada
- Usar el buscador para encontrar la **ENTREGA** (número largo, ej: `2917842991`)
- Abrir el desplegable de esa entrega
- Seleccionar el tipo de daño:
  - `01`
  - `02`
  - `03`
  - `04`
  - `Rechazado en anden por daños`
- Presionar **"Guardar"**

### 4. Tomar foto (OBLIGATORIA)
- Bajar hasta la sección **"📷 Fotos de la hoja de carga"**
- Presionar **"Tomar foto"** — abre la cámara del celular
- Sacar foto a la hoja de carga física
- Mínimo 1 foto obligatoria para poder finalizar

### 5. Finalizar la carga
Dos opciones en la parte inferior:

| Botón | Cuándo usarlo |
|---|---|
| **📤 Enviar daños de Carga XXXX** | Cuando hay al menos 1 daño declarado y 1 foto |
| **✓ Carga sin daños** | Cuando la carga se revisó pero no tiene daños (igual requiere 1 foto) |

> ⚠️ Las cargas marcadas **"Sin daños"** NO van al correo consolidado, pero sí quedan registradas en el historial.

### 6. Corregir un error
- Ir al tab **"Finalizados"**
- Abrir la carga
- Presionar **"↺ Reabrir carga para editar"**
- *(Solo disponible si el correo consolidado aún no fue enviado)*

---

## Cómo cerrar el día (supervisor)

1. Verificar que todas las cargas del día estén en el tab **"Finalizados"**
2. Ir al tab **"Admin"**
3. Revisar la lista de cargas listas para enviar
4. Presionar **"🔎 Vista previa (dry-run)"** para confirmar lo que se va a enviar
5. Presionar **"📨 Enviar consolidado del día"**

**El correo se envía a:**
- Skarlett Lucero (Cencosud)
- Jonathan Carvallo, Diego Hernández, Jessica Muñoz, Sasha Raventos (Easy Chile)
- Enrique Arcila, Marion González, Roberto Cofre, Isamar Riquelme, Jean Menéndez, Carolina Sánchez, Torre Control (TransYáñez)

**Asunto del correo:**
```
Respaldo de Productos declarados con daños de embalaje en andenes DD-MM-YYYY
```

**Formato del cuerpo:** tabla por carga con número de ENTREGA y tipo de DAÑO (estilo Captura.JPG histórico).

**Adjuntos:** todas las fotos de las hojas de carga físicas.

---

## Tipos de daño disponibles

| Código | Descripción |
|---|---|
| `01` | Daño tipo 01 |
| `02` | Daño tipo 02 |
| `03` | Daño tipo 03 |
| `04` | Daño tipo 04 |
| `Rechazado en anden por daños` | Rechazado completo en andén |

---

## Mantenimiento manual

### Sincronizar cargas manualmente (sin usar la app)
```powershell
cd c:\Users\Usuario\Documents\claude\DeclaracionCargaDanosStg
python tools/sync_cargas_outlook.py
```
> Requiere que **Outlook Desktop esté abierto**.

### Enviar el correo consolidado desde terminal
```powershell
python tools/send_consolidado_email.py
# Vista previa sin enviar:
python tools/send_consolidado_email.py --dry-run
```

### Reiniciar la app manualmente
```powershell
cd c:\Users\Usuario\Documents\claude\DeclaracionCargaDanosStg
streamlit run app/streamlit_app.py
```

### Reiniciar el túnel ngrok manualmente
```powershell
C:\ngrok\ngrok.exe start danos-anden --config "C:\Users\Usuario\AppData\Local\ngrok\ngrok.yml"
```

---

## Solución de problemas

| Problema | Solución |
|---|---|
| La app no carga en el celular | Verificar que la PC esté encendida e iniciada sesión. Esperar 30 seg después del login. |
| El link `ngrok-free.dev` no responde | Abrir PowerShell y ejecutar el comando de reinicio de ngrok (ver arriba). |
| No aparecen cargas del día | Presionar **↻ Sincronizar** en la app. Verificar que Outlook esté abierto. |
| Error al sincronizar | Verificar que Outlook Desktop esté abierto y con sesión activa en `ext_rauddy.medina@transyanez.cl`. |
| Error al enviar correo | Verificar contraseña SMTP en `.env`. Si Office 365 bloquea SMTP, contactar a TI para habilitar autenticación básica. |
| Botón "Enviar daños" deshabilitado | Revisar que haya ≥1 daño declarado Y ≥1 foto subida. |
| Botón "Sin daños" deshabilitado | Revisar que NO haya daños declarados Y que haya ≥1 foto subida. |

---

## Configuración técnica (para TI)

### Variables de entorno (`.env`)
Las variables principales se heredan del `.env` del directorio padre:
```
c:\Users\Usuario\Documents\claude\.env
```

Variables específicas de este proyecto (`DeclaracionCargaDanosStg\.env`):
```
DESTINATARIOS_DANOS     Lista de correos separados por coma
SMTP_SERVER             smtp.office365.com
SMTP_PORT               587
GOOGLE_SHEET_TAB_HISTORICO  HISTORICO_DANOS_ANDEN
MIN_FOTOS_POR_CARGA     1
```

### Google Sheet histórico
Todas las cargas finalizadas se appendean automáticamente a:
- **Spreadsheet:** el definido en `GOOGLE_SHEET_ID` del `.env` padre
- **Pestaña:** `HISTORICO_DANOS_ANDEN`
- **Columnas:** `fecha_finalizacion, numero_carga, cd, anden, entrega, tipo_dano, declarado_por, finalizada_por, sin_danos`

### Sincronización de correos
- **Método:** Outlook Desktop COM (win32com) — no requiere Azure AD
- **Carpeta:** `EasyGo` en la cuenta `ext_rauddy.medina@transyanez.cl`
- **Ventana:** últimos 7 días (configurable con `DIAS_VENTANA` en `.env`)
- **Idempotencia:** cada correo se procesa una sola vez (EntryID registrado en SQLite)

### ngrok (túnel público)
- **Dominio fijo:** `stooge-haiku-startup.ngrok-free.dev`
- **Config:** `C:\Users\Usuario\AppData\Local\ngrok\ngrok.yml`
- **Inicio automático:** `shell:startup\ngrok-danos-anden.vbs`
- **Plan:** Free (1 dominio estático gratuito)

---

## Contacto y soporte

Para modificaciones o soporte técnico en la app, contactar al desarrollador a través de Claude Code en el proyecto `DeclaracionCargaDanosStg`.
