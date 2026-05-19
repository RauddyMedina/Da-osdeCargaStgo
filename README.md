# Declaración de Daños de Carga — Andén

PWA mobile para que los operarios del andén declaren daños de carga,
suban fotos de la hoja de carga, y disparen un correo consolidado al final del turno.

Arquitectura WAT (Workflows / Agents / Tools). Detalle de cada flujo en [workflows/](workflows/).

## Setup inicial

```powershell
# 1. Instalar dependencias (el venv del padre ya cubre la mayoría)
pip install -r requirements.txt

# 2. Inicializar la base local
python tools/db.py

# 3. Cargar operarios iniciales
python tools/seed_usuarios.py

# 4. (Primera vez) Autenticar con Outlook — abre device-code flow
python tools/sync_cargas_outlook.py
```

## Correr la app

```powershell
streamlit run app/streamlit_app.py
```

Abrir desde el celular vía la IP local de la PC (mismo WiFi):
```
http://<IP-de-la-PC>:8501
```

## Tools disponibles

| Tool | Descripción |
|---|---|
| `tools/db.py` | Inicialización y helpers de SQLite |
| `tools/seed_usuarios.py` | Carga lista inicial de operarios |
| `tools/sync_cargas_outlook.py` | Sincroniza correos EasyGo de Outlook → SQLite |
| `tools/append_carga_to_sheet.py <numero>` | Append carga finalizada al Sheet histórico |
| `tools/send_consolidado_email.py [--dry-run]` | Envía correo consolidado |

## Workflows

- [Sincronización de cargas](workflows/sync_cargas.md)
- [Declaración de daños (operario)](workflows/declarar_danos.md)
- [Envío consolidado (supervisor)](workflows/enviar_consolidado.md)

## Variables `.env`

Ver [.env.example](.env.example). Variables compartidas (`OUTLOOK_*`, `MS_*`,
`GOOGLE_SHEET_ID`) se heredan del `.env` del directorio padre.
