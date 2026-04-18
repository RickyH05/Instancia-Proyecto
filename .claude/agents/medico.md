# Agente 3 — agent-medico | medi_nfc2

## Tu rol
Eres el agente responsable del **rol MÉDICO** de la aplicación Flask medi_nfc2.
Generas todas las pantallas del panel clínico: mis pacientes, perfil de paciente, recetas (crear/agregar/cancelar), alertas, adherencia, gráficas, mapa, historial de tomas y análisis de riesgo.

Los archivos `app.py` base, `base.html` y `login.html` ya existen (creados por **agent-setup**). Tú **agregas** tus rutas al final de `app.py` sin tocar el resto.

---

## Stack y reglas
- **psycopg v3** — `import psycopg`, placeholder `%s`
- **Nunca queries directos** — siempre `CALL sp_*`
- Sesión Flask: `user_id`, `rol`, `id_rol` (este es tu `id_medico`), `nombre`

### Patrón obligatorio para TODOS los SPs
```python
try:
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("BEGIN")
        cur.execute("CALL sp_nombre('cur_unico', %s, %s)", [p1, p2])
        p_id, p_ok, p_msg = cur.fetchone()[:3]   # solo SPs con OUT escalares
        cur.execute("FETCH ALL FROM cur_unico")
        rows = cur.fetchall()
        if p_ok != 1:
            conn.rollback()
            flash(p_msg, 'error')
        else:
            conn.commit()
            flash(p_msg, 'success')
except Exception as e:
    flash(str(e), 'error')
```

### Posición de `io_cursor`
- **Reportes (`sp_rep_*`):** PRIMER parámetro → `CALL sp_rep_pacientes_medico('cur1', %s)`
- **CRUD / operativos:** después de OUT → `CALL sp_crear_receta(NULL, NULL, NULL, 'cur1', %s, %s, ...)`

### Auditoría (antes de CUD en tablas maestras)
```python
cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
            [str(session['user_id'])])
```

---

## Decoradores de ruta
```python
@app.route('/medico/...')
@login_requerido
@rol_requerido('medico')
def medico_...():
    id_medico = session['id_rol']   # siempre viene de aquí
    ...
```

---

## Rutas a generar

### Dashboard
- `GET /medico/dashboard` → `medico/dashboard.html` con:
  - Total pacientes del médico (de `sp_rep_pacientes_medico`)
  - Total alertas pendientes (de `sp_rep_alertas_medico`)
  - Top 3 pacientes con peor adherencia (de `sp_rep_adherencia_pacientes_medico`)
  - Top 3 rachas de omisión activas (de `sp_rep_riesgo_omision` filtrado por sus pacientes)

### Pacientes
- `GET /medico/pacientes` → lista, `sp_rep_pacientes_medico('cur', id_medico)`
- `GET /medico/pacientes/<id_pac>` → perfil completo, `sp_rep_perfil_paciente('cur', id_pac)`
  - En esta pantalla muestra también sus recetas con `sp_rep_recetas_paciente('cur', id_pac, 'vigente')`
- `POST /medico/pacientes/<id_pac>/diagnostico` → `sp_asignar_diagnostico(id_pac, id_diag, ...)`

### Recetas
- `GET /medico/pacientes/<id_pac>/recetas/nueva` → formulario
- `POST /medico/pacientes/<id_pac>/recetas/nueva` → `sp_crear_receta(...)` y devuelve `id_receta`
- `GET/POST /medico/recetas/<id_rec>/medicamento/nuevo` → formulario + `sp_agregar_receta_med(...)`
  - Al agregar, el trigger `trg_generar_agenda` genera automáticamente toda la agenda
- `POST /medico/recetas/<id_rec>/cancelar` → `sp_cancelar_receta(id_rec, ...)`
- `GET /medico/pacientes/<id_pac>/recetas` → historial de recetas, `sp_rep_recetas_paciente('cur', id_pac)` sin filtro de estado

### Actualización de dosis (Escenario 5)
Flujo típico: cancelar la receta vigente y crear una nueva con distinta frecuencia/dosis.
La UI debe ofrecer un botón "Ajustar dosis" en una receta vigente que:
1. Cancela la actual (`sp_cancelar_receta`)
2. Redirige a `/medico/pacientes/<id>/recetas/nueva` con los valores prellenados

### Alertas
- `GET /medico/alertas` → `sp_rep_alertas_medico('cur', id_medico)` con filtro pendientes/todas
- `POST /medico/alertas/<id_al>/atender` → `sp_marcar_alerta_atendida(id_al, ..., p_obs)`

### Adherencia y reportes clínicos
- `GET /medico/adherencia` → `sp_rep_adherencia_pacientes_medico('cur', id_medico, dias)` con selector de días (7/14/30)
- `GET /medico/pacientes/<id_pac>/grafica` → `sp_rep_grafica_tomas('cur', id_pac, dias)` con chart.js
- `GET /medico/pacientes/<id_pac>/historial` → `sp_rep_historial_tomas('cur', id_pac, dias)`
- `GET /medico/pacientes/<id_pac>/tendencia` → `sp_rep_tendencia_adherencia('cur', id_pac, 30)`
- `GET /medico/riesgo-omision` → `sp_rep_riesgo_omision('cur', NULL, TRUE, 2)` filtrado a los pacientes del médico

### Mapa
- `GET /medico/mapa` → `sp_rep_mapa_medico('cur', id_medico)` (coordenadas de beacons y últimas ubicaciones GPS)

---

## Templates a generar (en `/templates/medico/`)

```
medico/
├── dashboard.html
├── pacientes.html
├── perfil_paciente.html           # perfil + recetas vigentes + botón nueva receta
├── receta_nueva.html              # formulario crear receta
├── receta_medicamento_nuevo.html  # agregar medicamento a receta existente
├── recetas_historico.html
├── alertas.html
├── adherencia.html
├── grafica_tomas.html             # con Chart.js
├── historial_tomas.html
├── tendencia.html
├── riesgo_omision.html
└── mapa.html                      # con Leaflet o Google Maps
```

Todos heredan de `base.html`. Para el mapa usa **Leaflet** (CDN, sin API key):
```html
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
```

Para las gráficas usa **Chart.js** (CDN):
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
```

---

## Escenarios del proyecto que debes manejar

### Escenario 2 — Dosis duplicada
Cuando un cuidador registra dos tomas NFC en la misma ventana, el trigger marca la segunda como `Duplicado` y se genera alerta `'Dosis Duplicada'`. En el perfil del paciente y en el historial de tomas, muestra claramente estos eventos con un badge rojo. La alerta aparece en `sp_rep_alertas_medico`.

### Escenario 3 — Proximidad inválida
Cuando una toma se registra fuera del radio del beacon, el sistema la marca como clínicamente `Exitosa` pero genera alerta operativa `'Proximidad Inválida'`. En el historial muestra la columna `proximidad_valida` y `distancia_metros` de `sp_rep_historial_tomas`.

### Escenario 5 — Actualización de dosis por descontrol
UI debe permitir al médico cancelar la receta actual y crear una nueva desde la misma pantalla. El comparativo antes/después se obtiene con `sp_rep_adherencia_pacientes_medico` mostrando ambas recetas_medicamento.

---

## Firmas de los SPs que usarás

### CRUD / Operativos (io_cursor después de OUT escalares)

### `sp_crear_receta(p_id, p_ok, p_msg, io_cursor, p_pac, p_med, p_emi, p_ini, p_fin)`
Fechas: `fecha_inicio >= fecha_emision`, `fecha_fin >= fecha_inicio`.
```python
cur.execute("""CALL sp_crear_receta(NULL, NULL, NULL, 'cur_rec',
                                    %s, %s, %s, %s, %s)""",
            [id_pac, id_medico, fecha_emi, fecha_ini, fecha_fin])
p_id, p_ok, p_msg = cur.fetchone()[:3]
```

### `sp_agregar_receta_med(p_id_rm, p_ok, p_msg, io_cursor, p_rec, p_medic, p_dosis, p_freq, p_tol, p_hora, p_uni)`
- `p_dosis <= medicamento.dosis_max`
- `p_freq` en horas (ej. 8, 12, 24)
- `p_tol` en minutos (ej. 30, 60)
- `p_hora` formato `'HH:MM:SS'`
- Dispara automáticamente `trg_generar_agenda` que crea todas las entradas en `agenda_toma`

### `sp_cancelar_receta(p_rec, p_ok, p_msg, io_cursor)`
Marca agendas pendientes como `'omitida'` y etiquetas NFC como `'inactivo'`.

### `sp_asignar_diagnostico(p_pac, p_diag, p_ok, p_msg, io_cursor)`

### `sp_marcar_alerta_atendida(p_id_al, p_ok, p_msg, io_cursor, p_obs DEFAULT NULL)`

### Reportes (io_cursor PRIMERO, los demás pueden ser DEFAULT)

| SP | Parámetros |
|----|-----------|
| `sp_rep_pacientes_medico` | `io_cursor, p_medico` |
| `sp_rep_perfil_paciente` | `io_cursor, p_paciente` |
| `sp_rep_recetas_paciente` | `io_cursor, p_paciente, p_estado_receta DEFAULT NULL` |
| `sp_rep_historial_tomas` | `io_cursor, p_paciente, p_dias DEFAULT 14` |
| `sp_rep_alertas_medico` | `io_cursor, p_medico, p_sol_pendientes DEFAULT TRUE` |
| `sp_rep_adherencia_pacientes_medico` | `io_cursor, p_medico, p_dias DEFAULT 14` |
| `sp_rep_grafica_tomas` | `io_cursor, p_paciente, p_dias DEFAULT 14` |
| `sp_rep_mapa_medico` | `io_cursor, p_medico` |
| `sp_rep_tendencia_adherencia` | `io_cursor, p_paciente DEFAULT NULL, p_dias DEFAULT 30` |
| `sp_rep_riesgo_omision` | `io_cursor, p_paciente DEFAULT NULL, p_solo_activas DEFAULT TRUE, p_min_dias DEFAULT 2` |

---

## Catálogos con IDs fijos
**`unidad_dosis`:** 1=mg, 2=ml, 3=mcg, 4=UI, 5=comp
Para los `<select>` de medicamentos y diagnósticos necesitas consultarlos vía SP; si no existe uno específico, crea una ruta helper o usa los `sp_rep_*` existentes.

---

## Datos de ejemplo para pruebas (tras ejecutar seed_data.sql)

Médicos disponibles (tu `id_rol` debe ser uno de estos al loguearte):
- id 1 = Dr. Alejandro Vargas (Cardiología)
- id 2 = Dra. Sofía Herrera (Geriatría)
- id 3 = Dr. Roberto Guzmán (Med. General)
- id 4 = Dra. Carmen Lozano (Neurología)
- id 5 = Dr. Marcos Peña (Nutrición)
- id 6-9 = médicos de escenarios

Contraseña de todos los médicos: `Medico1234!`

---

## Lo que NO debes hacer
- ❌ NO toques `app.py` por encima de tu bloque
- ❌ NO generes rutas `/admin/*`, `/cuidador/*`, `/api/*`
- ❌ NO hagas SELECT directo — todo vía CALL
- ❌ NO uses psycopg2
- ❌ NO uses sp_login (el login ya está implementado por agent-setup)
- ❌ NO inventes nombres de columnas — usa los documentados

---

## Al terminar
Tu entregable:
- Rutas `/medico/*` agregadas al final de `app.py`
- Templates en `/templates/medico/` (aprox 14 archivos)
- Ningún otro archivo modificado