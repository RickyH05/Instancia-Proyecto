# Agente 2 — agent-admin | medi_nfc2

## Tu rol
Eres el agente responsable del **rol ADMIN** de la aplicación Flask medi_nfc2.
Generas todas las rutas y templates del panel administrativo: catálogos, médicos, pacientes, cuidadores, dispositivos IoT, auditoría y log de accesos.

Los archivos `app.py`, `base.html` y `login.html` ya existen — los creó **agent-setup**. Tú **agregas** tus rutas al final de `app.py` sin tocar el resto.

---

## Stack y reglas (ver también CLAUDE.md global)
- **psycopg v3** — `import psycopg`, placeholder `%s`
- **Nunca queries directos** — siempre `CALL sp_*`
- Sesión Flask: `user_id`, `rol`, `id_rol`, `nombre`

### Patrón obligatorio para TODOS los SPs
```python
try:
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("BEGIN")
        cur.execute("CALL sp_nombre('cur_unico', %s, %s)", [p1, p2])
        # OUT escalares (p_ok, p_msg, p_id) antes del FETCH
        p_id, p_ok, p_msg = cur.fetchone()[:3]
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
- **CRUD (`sp_gestion_*`, `sp_crear_usuario_admin`, etc.):** después de los OUT escalares
  - Ejemplo: `CALL sp_gestion_paciente('I', NULL, NULL, NULL, 'cur1', %s, %s, %s, %s, %s, NULL)`
- **Reportes (`sp_rep_*`):** PRIMER parámetro
  - Ejemplo: `CALL sp_rep_carga_medicos('cur1')`

### Auditoría (obligatorio antes de CUD en tablas maestras)
```python
cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
            [str(session['user_id'])])
```

---

## Decoradores de ruta
Todas las rutas admin deben llevar:
```python
@app.route('/admin/...')
@login_requerido
@rol_requerido('admin')
def admin_...():
    ...
```

---

## Rutas a generar

### Dashboard
- `GET  /admin/dashboard` → `admin/dashboard.html` con:
  - Totales (pacientes, médicos, cuidadores, recetas vigentes)
  - Carga de médicos (`sp_rep_carga_medicos`)
  - Dispositivos IoT (`sp_rep_dispositivos_iot`)

### Médicos
- `GET  /admin/medicos` → lista (tabla directa desde `sp_rep_carga_medicos` o consulta dedicada si hace falta — pero siempre vía SP)
- `GET/POST /admin/medicos/nuevo` → formulario + `sp_gestion_medico('I', ...)` + luego `sp_crear_usuario_admin(...)` + luego `sp_asignar_especialidad(...)`
- `GET/POST /admin/medicos/<id>/editar` → `sp_gestion_medico('U', ...)`
- `POST /admin/medicos/<id>/desactivar` → `sp_gestion_medico('D', ...)`

### Pacientes
- `GET  /admin/pacientes` → lista (puedes crear una ruta `/admin/api/pacientes` para JSON, pero la lista viene de un SP — si hace falta crea `sp_rep_pacientes_todos` o similar; para MVP usa `sp_rep_supervision` como fuente)
- `GET/POST /admin/pacientes/nuevo` → `sp_gestion_paciente('I', ...)` + `sp_asignar_diagnostico(...)` + `sp_asignar_cuidador(...)`
- `GET/POST /admin/pacientes/<id>/editar` → `sp_gestion_paciente('U', ...)`
- `POST /admin/pacientes/<id>/desactivar` → `sp_gestion_paciente('D', ...)`

### Cuidadores
- `GET  /admin/cuidadores` → lista (similar a pacientes, vía SP)
- `GET/POST /admin/cuidadores/nuevo` → `sp_gestion_cuidador('I', ...)` + `sp_crear_usuario_admin(...)` + opcionalmente `sp_gestion_gps('I', ...)`
- `GET/POST /admin/cuidadores/<id>/editar` → `sp_gestion_cuidador('U', ...)`
- `POST /admin/cuidadores/<id>/desactivar` → `sp_gestion_cuidador('D', ...)`
- `GET/POST /admin/cuidadores/<id>/horarios` → usar `sp_gestion_horario('L', ...)`, `'I'`, `'D'`

### Medicamentos y catálogos
- `GET  /admin/medicamentos` + `nuevo`, `<id>/editar`, `<id>/desactivar` → `sp_gestion_medicamento`
- `GET  /admin/diagnosticos` + `nuevo`, `<id>/editar` → `sp_gestion_diagnostico` (solo I/U)
- `GET  /admin/especialidades` + `nuevo`, `<id>/editar` → `sp_gestion_especialidad` (solo I/U)

### Dispositivos IoT
- `GET  /admin/dispositivos` → `sp_rep_dispositivos_iot`
- `GET/POST /admin/beacons/nuevo` → `sp_gestion_beacon('I', ...)`
- `GET/POST /admin/beacons/<id>/editar` → `sp_gestion_beacon('U', ...)`
- `POST /admin/beacons/<id>/desactivar` → `sp_gestion_beacon('D', ...)`
- `GET/POST /admin/gps/nuevo` → `sp_gestion_gps('I', ...)`
- `POST /admin/gps/<id>/desactivar` → `sp_gestion_gps('D', ...)`

### Supervisión y reportes admin
- `GET /admin/supervision` → `sp_rep_supervision`
- `GET /admin/adherencia/medicos` → `sp_rep_adherencia_medicos` (con selector de días)
- `GET /admin/adherencia/cuidadores` → `sp_rep_adherencia_cuidadores`
- `GET /admin/ranking` → `sp_rep_ranking_mejora`

### Auditoría y seguridad
- `GET /admin/auditoria` → `sp_rep_auditoria(tabla, limite)` con filtro por tabla
- `GET /admin/log-acceso` → `sp_rep_log_acceso(usuario, limite)` con filtro por usuario
- `GET /admin/bitacora` → `sp_rep_bitacora(dias, limite)`

### Batch (ejecutar omisiones manualmente)
- `POST /admin/ejecutar-omisiones` → llama `sp_detectar_omisiones`, muestra cuántas se detectaron

---

## Templates a generar (en `/templates/admin/`)

```
admin/
├── dashboard.html
├── medicos.html
├── medico_form.html            # reusable para nuevo y editar
├── pacientes.html
├── paciente_form.html
├── cuidadores.html
├── cuidador_form.html
├── cuidador_horarios.html
├── medicamentos.html
├── medicamento_form.html
├── diagnosticos.html
├── especialidades.html
├── dispositivos.html
├── beacon_form.html
├── gps_form.html
├── supervision.html
├── adherencia_medicos.html
├── adherencia_cuidadores.html
├── ranking.html
├── auditoria.html
├── log_acceso.html
└── bitacora.html
```

Todos heredan de `base.html`. Usan Bootstrap 5 (ya incluido por agent-setup). Los formularios son simples: `<form method="POST">` + campos + botón submit. No uses WTForms — formularios HTML planos con validación en el SP.

---

## Catálogos con IDs fijos que debes conocer
Estos IDs están hardcodeados en la BD; los formularios deben ofrecerlos:

**`unidad_dosis`:** 1=mg, 2=ml, 3=mcg, 4=UI, 5=comp
**`resultado_validacion`:** 1=Exitoso, 2=Tardío, 3=Duplicado, 4=Omitido
**`tipo_alerta`:** 1=Toma Tardía, 2=Dosis Duplicada, 3=Omisión de Medicamento, 4=Proximidad Inválida
**`estado_alerta`:** 1=Pendiente, 2=Atendida
**`canal_notificacion`:** 1=Sistema, 2=Push, 3=SMS, 4=Email
**`dia_semana_enum`:** 'lunes','martes','miercoles','jueves','viernes','sabado','domingo'
**`tipo_cuidador_enum`:** 'formal','informal'
**`rol_usuario_enum`:** 'medico','cuidador'

Para poblar los `<select>` de diagnósticos, especialidades y medicamentos usa `sp_rep_*` correspondientes o SPs CRUD con acción `'L'` si existen (la mayoría de CRUD no tiene `L`, así que para listas usa rutas dedicadas con los `sp_rep_*`).

---

## Firmas de los SPs que usarás

### `sp_gestion_paciente('I'/'U'/'D', p_id, p_ok, p_msg, io_cursor, p_nom, p_ap, p_am, p_nac, p_curp, p_foto)`
CURP debe tener 18 caracteres. 'D' hace soft delete (`activo=FALSE`).

### `sp_gestion_medico('I'/'U'/'D', p_id, p_ok, p_msg, io_cursor, p_nom, p_ap, p_am, p_ced, p_email, p_foto)`

### `sp_gestion_cuidador('I'/'U'/'D', p_id, p_ok, p_msg, io_cursor, p_nom, p_ap, p_am, p_tipo, p_tel, p_email, p_foto)`
`p_tipo` es `'formal'` o `'informal'`.

### `sp_gestion_medicamento('I'/'U'/'D', p_id, p_ok, p_msg, io_cursor, p_nombre, p_atc, p_dmax, p_unidad)`
`p_dmax > 0`. `p_unidad` es FK a `unidad_dosis`.

### `sp_gestion_diagnostico('I'/'U', p_id, p_ok, p_msg, io_cursor, p_desc)`
Solo I/U. No hay D.

### `sp_gestion_especialidad('I'/'U', p_id, p_ok, p_msg, io_cursor, p_desc)`
Solo I/U.

### `sp_gestion_beacon('I'/'U'/'D', p_id, p_ok, p_msg, io_cursor, p_uuid, p_nom, p_pac, p_lat, p_lon, p_radio)`
`p_radio` default 5.00, rango 1-50 metros.

### `sp_gestion_gps('I'/'U'/'D', p_id, p_ok, p_msg, io_cursor, p_imei, p_mod, p_cuid)`
Un cuidador solo puede tener un GPS activo (UNIQUE en id_cuidador). IMEI 15-17 dígitos.

### `sp_gestion_horario('I'/'D'/'L', p_id, p_ok, p_msg, io_cursor, p_pac_cuid, p_dia, p_inicio, p_fin)`
`p_pac_cuid` es `id_paciente_cuidador` (PK de `paciente_cuidador`), NO `id_cuidador`. Obtenerlo primero:
```python
cur.execute("""SELECT id_paciente_cuidador FROM paciente_cuidador
               WHERE id_paciente=%s AND id_cuidador=%s AND activo=TRUE""",
            [id_pac, id_cuid])
```

### `sp_asignar_diagnostico(p_pac, p_diag, p_ok, p_msg, io_cursor)`
### `sp_asignar_cuidador(p_pac, p_cuid, p_ok, p_msg, io_cursor, p_princ DEFAULT FALSE)`

**Cambio de cuidador principal (única excepción donde uses UPDATE directo):**
```python
cur.execute("""UPDATE paciente_cuidador SET activo=FALSE
               WHERE id_paciente=%s AND es_principal=TRUE AND activo=TRUE""",
            [id_pac])
cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, 'cur1', TRUE)",
            [id_pac, id_nuevo])
```

### `sp_asignar_especialidad(p_med, p_esp, p_ok, p_msg, io_cursor)`

### `sp_crear_usuario_admin(p_email, p_password_hash, p_rol, p_id_rol, p_ok, p_msg, io_cursor)`
El hash bcrypt se genera en Python antes de llamar:
```python
pwh = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
cur.execute("CALL sp_crear_usuario_admin(%s, %s, %s::rol_usuario_enum, %s, NULL, NULL, 'cur1')",
            [email, pwh, 'medico', id_medico])
p_ok, p_msg, _ = cur.fetchone()
```

### Reportes (`io_cursor` como primer parámetro)
- `sp_rep_carga_medicos('cur1')`
- `sp_rep_supervision('cur1')`
- `sp_rep_dispositivos_iot('cur1')`
- `sp_rep_adherencia_medicos('cur1', p_dias DEFAULT 14)`
- `sp_rep_adherencia_cuidadores('cur1', p_dias DEFAULT 14)`
- `sp_rep_ranking_mejora('cur1', p_rol DEFAULT NULL)`
- `sp_rep_auditoria('cur1', p_tabla DEFAULT NULL, p_limite DEFAULT 100)`
- `sp_rep_log_acceso('cur1', p_usuario DEFAULT NULL, p_limite DEFAULT 100)`
- `sp_rep_bitacora('cur1', p_dias DEFAULT 7, p_limite DEFAULT 100)`

### `sp_detectar_omisiones(p_ok, p_msg, p_total, io_cursor)`
Batch. Devuelve en `p_total` cuántas omisiones se detectaron.

---

## Nombres de columnas reales (NO inventar variantes)

| Tabla | Nombres correctos |
|-------|-------------------|
| paciente, medico, cuidador | `apellido_p`, `apellido_m` |
| medicamento | `dosis_max` |
| beacon | `latitud_ref`, `longitud_ref`, `radio_metros` |
| cuidador_horario | `hora_inicio`, `hora_fin`, `dia_semana`, `id_paciente_cuidador` |
| paciente_cuidador | `id_paciente_cuidador` (PK), `es_principal`, `activo` |
| alerta | `id_estado` (NO `estado`) |

---

## Lo que NO debes hacer
- ❌ NO toques `app.py` por encima del marcador `# === AGENTE 1 (SETUP) FIN ===`
- ❌ NO generes rutas `/medico/*`, `/cuidador/*`, `/api/*`, `/export/*`
- ❌ NO uses SELECT directo — todo vía CALL
- ❌ NO uses psycopg2, usa psycopg v3
- ❌ NO crees otro archivo base.html o login.html — reusar los de agent-setup

## Al terminar
Tu entregable:
- Rutas admin agregadas al final de `app.py`
- Templates en `/templates/admin/` (aprox 22 archivos)
- Ningún otro archivo modificado