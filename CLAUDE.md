# Proyecto Flask — medi_nfc2

## Stack
- Python Flask (sin Blueprints, todo en `app.py`)
- **psycopg (versión 3)** — `import psycopg` (NO `psycopg2`, NO SQLAlchemy, NO ORM)
- Base de datos: `medi_nfc2` | usuario: `proyectofinal_user` | contraseña: `444`
- Conexión: `postgresql://proyectofinal_user:444@localhost:5432/medi_nfc2`
- Ver `@docs/database.md` para firmas completas de SPs

## Estructura
- `app.py` (una sola app, sin blueprints)
- `/templates` con Jinja2
- `/static` para CSS, JS e imágenes
- `.env` con `SECRET_KEY`, `DB_*`, `ADMIN_EMAIL`, `ADMIN_PASSWORD_HASH`

---

## Regla #1 — NUNCA queries directos. SIEMPRE Stored Procedures.

**Flask no escribe SQL propio. Ni SELECT, ni INSERT, ni UPDATE, ni DELETE.**
Para todo — lecturas, escrituras, reportes, contadores — se usa un SP.

```
✅ CORRECTO:   cur.execute("CALL sp_rep_pacientes_medico('cur1', %s)", [id])
✅ CORRECTO:   cur.execute("CALL sp_gestion_paciente('I', NULL, NULL, NULL, 'cur1', ...)")
❌ INCORRECTO: cur.execute("SELECT * FROM v_pacientes_medico WHERE id_medico = %s", [id])
❌ INCORRECTO: cur.execute("SELECT * FROM paciente WHERE activo = TRUE")
❌ INCORRECTO: cur.execute("INSERT INTO alerta ...")
❌ INCORRECTO: cur.execute("UPDATE paciente SET ...")
```

Las Views y las tablas existen en la BD como capa interna — Flask nunca las toca directamente.

**Excepciones explícitas (y únicas):**
1. **Login** — bcrypt debe verificarse en Python, no en BD; se hace SELECT de contraseña.
2. **Cambio de cuidador principal** — el UPDATE de `activo=FALSE` en `paciente_cuidador` no tiene SP propio.

---

## Regla #2 — Patrón obligatorio para todos los SPs

Todos los SPs tienen `INOUT io_cursor REFCURSOR`. Siempre `BEGIN` + `CALL` + `FETCH ALL` + `COMMIT`.

```python
try:
    cur.execute("BEGIN")
    cur.execute("CALL sp_nombre('cur_unico', %s, %s)", [param1, param2])
    # Si el SP tiene OUT escalares (p_ok, p_msg, etc.) leerlos ANTES del FETCH:
    p_ok, p_msg = cur.fetchone()[:2]
    cur.execute("FETCH ALL FROM cur_unico")
    rows = cur.fetchall()
    if p_ok != 1:
        conn.rollback()
        flash(p_msg, 'error')
    else:
        conn.commit()
        flash(p_msg, 'success')
except Exception as e:
    conn.rollback()
    flash(str(e), 'error')
```

**Nombre del cursor:** único por llamada dentro de la misma conexión.
Usar `f"cur_{nombre_sp}_{id_o_timestamp}"` para evitar colisiones.

---

## Posición de `io_cursor` según tipo de SP

| Tipo | Posición de `io_cursor` | Ejemplo |
|------|------------------------|---------|
| **CRUD / Operativos** | Después de `OUT` escalares, antes de `IN DEFAULT` | `CALL sp_gestion_paciente('I', NULL, NULL, NULL, 'cur1', %s, ...)` |
| **Reportes `sp_rep_*`** | **Primer parámetro** | `CALL sp_rep_pacientes_medico('cur1', %s)` |

Los `sp_rep_*` tienen `io_cursor` primero porque todos sus demás parámetros
son opcionales con `DEFAULT` y PostgreSQL no permite parámetros sin DEFAULT
después de uno con DEFAULT.

---

## Nombres de columnas reales (NO inventar variantes)

| Tabla | Nombres correctos |
|-------|------------------|
| `paciente`, `medico`, `cuidador` | `apellido_p`, `apellido_m` |
| `medicamento` | `dosis_max` |
| `ubicacion_gps` | `latitud`, `longitud`, `timestamp_ubicacion` |
| `alerta` | `id_estado` (NO `estado`) — JOIN con `estado_alerta` para descripción |
| `beacon` | `latitud_ref`, `longitud_ref`, `radio_metros` |
| `cuidador_horario` | `hora_inicio`, `hora_fin`, `dia_semana`, `id_paciente_cuidador` |
| `paciente_cuidador` | `id_paciente_cuidador` (PK), `es_principal`, `activo` |

---

## Autenticación

- **bcrypt** — `bcrypt.checkpw(password.encode(), stored_hash.encode())`
- **NO usar `sp_login`** — única excepción donde Flask hace SELECT directo
- Login admin: `ADMIN_EMAIL` + `ADMIN_PASSWORD_HASH` en `.env`

```python
# Login — ÚNICA excepción válida para SELECT directo
cur.execute("""
    SELECT u.id_usuario, u.password_hash, u.rol_usuario,
           COALESCE(u.id_medico, u.id_cuidador) AS id_rol,
           CASE u.rol_usuario
               WHEN 'medico'   THEN m.nombre || ' ' || m.apellido_p
               WHEN 'cuidador' THEN c.nombre || ' ' || c.apellido_p
           END AS nombre
    FROM   usuario u
    LEFT JOIN medico   m ON m.id_medico   = u.id_medico
    LEFT JOIN cuidador c ON c.id_cuidador = u.id_cuidador
    WHERE  u.email = %s AND u.activo = TRUE
""", [email])
row = cur.fetchone()
if row and bcrypt.checkpw(password.encode(), row[1].encode()):
    session.update({'user_id': row[0], 'rol': row[2],
                    'id_rol': row[3], 'nombre': row[4]})
```

---

## Sesión Flask

```python
session['user_id'] = id_usuario
session['rol']     = 'medico' | 'cuidador' | 'admin'
session['id_rol']  = id_medico | id_cuidador | None   # None para admin
session['nombre']  = 'Nombre Completo'
```

---

## Protección de rutas

```python
@login_requerido          # revisa session['user_id']
@rol_requerido('medico')  # revisa session['rol']
def mi_ruta():
    ...
```

---

## Auditoría

Antes de cualquier SP que modifica tablas maestras (`paciente`, `medico`, `cuidador`, `usuario`):

```python
cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
            [str(session['user_id'])])
```

---

## Casos especiales

### Badge de alertas pendientes
```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_badge_alertas('cur_badge', %s, %s)",
            [session['user_id'], session['rol']])
cur.execute("FETCH ALL FROM cur_badge")
row   = cur.fetchone()
total = row[0] if row else 0
conn.commit()
```

### Cambio de cuidador principal (única excepción #2)
```python
# UPDATE directo — no hay SP para desactivar la relación anterior
cur.execute("""
    UPDATE paciente_cuidador SET activo = FALSE
    WHERE  id_paciente = %s AND es_principal = TRUE AND activo = TRUE
""", [id_paciente])
# Luego asignar el nuevo con SP
cur.execute("BEGIN")
cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, 'cur1', TRUE)",
            [id_paciente, id_cuidador_nuevo])
p_ok, p_msg = cur.fetchone()[:2]
conn.commit()
```

### Gestión de horarios
Requiere `id_paciente_cuidador` (PK de `paciente_cuidador`), no `id_cuidador`:
```python
# Obtener el id del vínculo
cur.execute("""
    SELECT id_paciente_cuidador FROM paciente_cuidador
    WHERE  id_paciente = %s AND id_cuidador = %s AND activo = TRUE
""", [id_paciente, id_cuidador])
id_pc = cur.fetchone()[0]

# Usar el SP
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_horario('I', NULL, NULL, NULL, 'cur1', %s, %s, %s, %s)",
            [id_pc, 'lunes', '08:00:00', '14:00:00'])
p_id, p_ok, p_msg = cur.fetchone()[:3]
conn.commit()
```

### Proceso batch de omisiones (cron)
```python
cur.execute("BEGIN")
cur.execute("CALL sp_detectar_omisiones(NULL, NULL, NULL, 'cur_om')")
p_ok, p_msg, p_total = cur.fetchone()[:3]
cur.execute("FETCH ALL FROM cur_om")
omisiones = cur.fetchall()
conn.commit()
```

---

## Tabla rápida — SP por pantalla

### Acciones (CRUD / Operativos)

| Pantalla / Acción | SP |
|---|---|
| Alta / edición paciente | `sp_gestion_paciente('I'/'U'/'D', ...)` |
| Alta / edición médico | `sp_gestion_medico('I'/'U'/'D', ...)` |
| Alta / edición cuidador | `sp_gestion_cuidador('I'/'U'/'D', ...)` |
| Alta / edición medicamento | `sp_gestion_medicamento('I'/'U'/'D', ...)` |
| Alta diagnóstico / especialidad | `sp_gestion_diagnostico` / `sp_gestion_especialidad` |
| Alta beacon / GPS | `sp_gestion_beacon` / `sp_gestion_gps` |
| Gestionar turno cuidador | `sp_gestion_horario('I'/'D'/'L', ...)` |
| Crear usuario acceso | `sp_crear_usuario_admin(...)` |
| Asignar diagnóstico | `sp_asignar_diagnostico(...)` |
| Asignar cuidador | `sp_asignar_cuidador(...)` |
| Cambiar cuidador principal | UPDATE directo + `sp_asignar_cuidador(...)` |
| Asignar especialidad | `sp_asignar_especialidad(...)` |
| Nueva receta | `sp_crear_receta(...)` |
| Agregar medicamento a receta | `sp_agregar_receta_med(...)` |
| Cancelar receta / actualizar dosis | `sp_cancelar_receta(...)` |
| Escaneo NFC | `sp_registrar_toma_nfc(...)` |
| Atender alerta | `sp_marcar_alerta_atendida(...)` |
| Detectar omisiones (cron) | `sp_detectar_omisiones(...)` |

### Lectura / Reportes (sp_rep_*)

| Pantalla | SP |
|---|---|
| Dashboard cuidador (agenda del día) | `sp_rep_dashboard_cuidador('cur', id_cuid)` |
| Lista de tomas del día + NFC | `sp_rep_agenda_dia_cuidador('cur', id_cuid)` |
| Alertas del cuidador | `sp_rep_alertas_cuidador('cur', id_cuid)` |
| Alertas del médico | `sp_rep_alertas_medico('cur', id_med)` |
| Badge contador alertas menú | `sp_rep_badge_alertas('cur', user_id, rol)` |
| Lista pacientes del médico | `sp_rep_pacientes_medico('cur', id_med)` |
| Perfil completo del paciente | `sp_rep_perfil_paciente('cur', id_pac)` |
| Recetas y medicamentos | `sp_rep_recetas_paciente('cur', id_pac, 'vigente')` |
| Historial de tomas NFC | `sp_rep_historial_tomas('cur', id_pac, dias)` |
| Adherencia pacientes del médico | `sp_rep_adherencia_pacientes_medico('cur', id_med, dias)` |
| Gráfica de barras adherencia | `sp_rep_grafica_tomas('cur', id_pac, dias)` |
| Mapa GPS/Beacon | `sp_rep_mapa_medico('cur', id_med)` |
| Adherencia global médicos | `sp_rep_adherencia_medicos('cur', dias)` |
| Adherencia global cuidadores | `sp_rep_adherencia_cuidadores('cur', dias)` |
| Bitácora reglas de negocio | `sp_rep_bitacora('cur', dias, limite)` |
| Auditoría de cambios | `sp_rep_auditoria('cur', tabla, limite)` |
| Log de accesos | `sp_rep_log_acceso('cur')` |
| Carga de médicos | `sp_rep_carga_medicos('cur')` |
| Supervisión médico-paciente | `sp_rep_supervision('cur')` |
| Dispositivos IoT | `sp_rep_dispositivos_iot('cur')` |
| Tendencia adherencia (7d móvil) | `sp_rep_tendencia_adherencia('cur', id_pac, dias)` |
| Riesgo omisión consecutiva | `sp_rep_riesgo_omision('cur', id_pac)` |
| Ranking mejora adherencia | `sp_rep_ranking_mejora('cur', rol)` |