# Workflow: Declaración de Daños en la App (Operario)

## Objetivo
Que cada operario del andén declare los daños físicos encontrados en las cargas liberadas, suba foto de la hoja de carga y finalice cada carga.

## Cómo se accede
La app está en `http://<IP-PC>:8501` (red local). Se puede instalar como ícono en el celular agregando "Añadir a pantalla de inicio" desde Chrome.

## Flujo paso a paso

### 1. Login
- Selecciona tu nombre del listado
- Presiona **"Rutas Disponibles"**

### 2. Cargas del día
- Aparecen las cargas de la fecha seleccionada
- **Flechas ◄ ►**: navegar entre días (útil para cargas activadas con desfase de fecha)
- **Botón ↻**: sincroniza nuevos correos desde Outlook
- **Tabs**: `Por declarar`, `Finalizados`, `Admin`
- Presiona **"Abrir"** en una carga para ver detalle

### 3. Detalle de carga
- Buscador para encontrar una ENTREGA específica
- Por cada entrega: expander con tipo de daño:
  - `01`, `02`, `03`, `04`, o `Rechazado en anden por daños`
  - O `(sin daño)` para limpiar una declaración previa
- Botones **Guardar** / **Eliminar**

### 4. Foto de la hoja de carga (OBLIGATORIA — mínimo 1)
- Sección **"📷 Fotos de la hoja de carga"**
- Botón "Tomar foto" abre la cámara del celular
- Permite subir múltiples fotos
- Cada foto se guarda en `data/fotos/CARGA_<numero>_<uuid>.jpg`

### 5. Finalizar carga
Dos opciones en el footer:

#### Opción A: "📤 Enviar daños de Carga XXXX"
- Habilitado si: ≥1 daño declarado AND ≥1 foto subida
- Marca la carga como `finalizada`, `sin_danos=0`
- Hace append al Google Sheet histórico
- La carga entra al pool del correo consolidado del día

#### Opción B: "✓ Carga sin daños"
- Habilitado si: 0 daños declarados AND ≥1 foto subida
- Pide confirmación
- Marca la carga como `finalizada`, `sin_danos=1`
- Hace append al Sheet (con `tipo_dano='SIN DAÑOS'` y `sin_danos=1`)
- **NO entra al correo consolidado** (queda solo en histórico)

### 6. Corregir una carga finalizada
- Ve a tab **"Finalizados"**
- Abre la carga
- Botón **"↺ Reabrir carga para editar"** (solo si no fue enviada todavía)

## Reglas clave
| Regla | Razón |
|---|---|
| Foto obligatoria (mín 1) | Auditoría y respaldo físico |
| 1 declaración por ENTREGA | Simplicidad; si una entrega tiene varios bultos, se declara el peor caso |
| No se puede editar carga ya enviada | Integridad del correo enviado |
| Las cargas "Sin daños" SÍ van al Sheet histórico | Trazabilidad de qué se revisó |
