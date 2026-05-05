# Base de datos `medi_nfc2` — Documentación completa para Claude Code

> **Motor:** PostgreSQL  
> **Base de datos:** `medi_nfc2`  
> **Usuario:** `proyectofinal_user` / contraseña: `444`  
> **Conexión:** `postgresql://proyectofinal_user:444@localhost:5432/medi_nfc2`

---

## Convenciones globales de los SPs (v7)

Todos los stored procedures siguen estas reglas de firma en PostgreSQL:

1. Los parámetros `OUT` e `INOUT` siempre van **antes** de los `IN` con `DEFAULT`.
2. Los parámetros de salida de estado son siempre: `p_ok INTEGER` (1=éxito, negativo=error) y `p_msg VARCHAR(300)`.
3. **Todos los SPs incluyen `INOUT io_cursor REFCURSOR`** — siempre hay que pasarle un nombre de cursor y hacer `FETCH ALL` dentro de una transacción explícita.
4. Los reportes son **Views** — se consultan con `SELECT` directo, sin transacción explícita.

### Patrón psycopg (v3) — SP con REFCURSOR

```python
# IMPORTANTE: usar psycopg (v3), NO psycopg2
import psycopg

conn.autocommit = False   # necesario para que el cursor sobreviva al FETCH

with conn.cursor() as cur:
    cur.execute("BEGIN")
    cur.execute("CALL sp_nombre(NULL, NULL, NULL, 'mi_cursor', %s, %s)",
                [param1, param2])
    p_id, p_ok, p_msg = cur.fetchone()   # salidas escalares
    cur.execute("FETCH ALL FROM mi_cursor")
    rows = cur.fetchall()                 # filas del cursor
    conn.commit()
```

> **Regla del nombre de cursor:** cada llamada debe usar un nombre de cursor único
> dentro de la misma conexión. Usar `f"cur_{sp_nombre}_{id_unico}"` o similar.
> El cursor se cierra automáticamente en el `COMMIT`.

### Patrón psycopg (v3) — View (sin cursor)

```python
with conn.cursor() as cur:
    cur.execute("SELECT * FROM v_nombre WHERE columna_filtro = %s", [valor])
    rows = cur.fetchall()
# No requiere BEGIN/COMMIT
```

### Posición de `io_cursor` en la firma

`io_cursor` va siempre **después de los OUT escalares** y **antes de los IN opcionales con DEFAULT**:

```
CALL sp_nombre(
    IN  p_obligatorio,
    INOUT p_id,
    OUT p_ok,
    OUT p_msg,
    INOUT io_cursor REFCURSOR,   ← aquí siempre
    IN  p_opcional DEFAULT NULL,
    ...
)
```

En Python, los parámetros `NULL` para OUT se pasan como `None` o `NULL` y
el nombre del cursor como string en la posición de `io_cursor`:

```python
# Firma: sp_gestion_paciente('I', p_id INOUT, p_ok OUT, p_msg OUT, io_cursor INOUT, p_nom DEFAULT...)
cur.execute("CALL sp_gestion_paciente('I', NULL, NULL, NULL, 'cur1', %s, %s, %s, %s, %s, NULL)",
            [nombre, ap, am, fecha_nac, curp])
p_id, p_ok, p_msg = cur.fetchone()
```

### Códigos de `p_ok`

| Valor | Significado |
|-------|-------------|
| `1`   | Operación exitosa |
| `-1`  | Campos obligatorios incompletos / dato no encontrado |
| `-2`  | Validación de negocio fallida (ej. dosis excede máximo, hora_fin <= hora_inicio) |
| `-3`  | Falta `p_id` para UPDATE/DELETE, o FK requerida ausente |
| `-4`  | Registro no encontrado para eliminar |
| `-10` | Violación de unicidad (UNIQUE constraint) |
| `-99` | Acción no válida (solo acepta I/U/D/L según SP) |
| `-100`| Error inesperado (ver `p_msg` para detalle) |

---

## ENUMs disponibles

| Tipo | Valores |
|------|---------|
| `tipo_cuidador_enum` | `'formal'`, `'informal'` |
| `rol_usuario_enum` | `'medico'`, `'cuidador'` |
| `estado_receta_enum` | `'vigente'`, `'cancelada'`, `'vencida'` |
| `estado_etiqueta_enum` | `'activo'`, `'inactivo'` |
| `origen_enum` | `'manual'`, `'nfc'` |
| `dia_semana_enum` | `'lunes'`, `'martes'`, `'miercoles'`, `'jueves'`, `'viernes'`, `'sabado'`, `'domingo'` |
| `estado_agenda_enum` | `'pendiente'`, `'cumplida'`, `'tardia'`, `'omitida'` |
| `prioridad_alerta_enum` | `'Alta'`, `'Media'`, `'Baja'` |

---

## Nombres reales de columnas (errores comunes)

| Tabla | Columnas correctas |
|-------|-------------------|
| paciente, medico, cuidador | `apellido_p`, `apellido_m` (NO `apellido_paterno`/`materno`) |
| medicamento | `dosis_max` (NO `dosis_maxima`) |
| ubicacion_gps | `latitud`, `longitud`, `timestamp_ubicacion` (NO `lat`/`lon`/`timestamp_gps`) |
| alerta | `id_estado` (NO `estado`) — hacer JOIN con `estado_alerta` para la descripción |
| beacon | `latitud_ref`, `longitud_ref`, `radio_metros` |
| evento_nfc | `timestamp_lectura`, `fecha_registro`, `desfase_min` |
| cuidador_horario | `hora_inicio`, `hora_fin`, `dia_semana`, `id_paciente_cuidador` |
| paciente_cuidador | `id_paciente_cuidador` (PK), `es_principal`, `activo` |

---

## Tablas catálogo (IDs fijos en producción)

### `resultado_validacion`
| id | descripcion |
|----|-------------|
| 1  | Exitoso |
| 2  | Tardío |
| 3  | Duplicado |
| 4  | Omitido |

### `tipo_alerta`
| id | descripcion |
|----|-------------|
| 1  | Toma Tardía |
| 2  | Dosis Duplicada |
| 3  | Omisión de Medicamento |
| 4  | Proximidad Inválida |

### `estado_alerta`
| id | descripcion |
|----|-------------|
| 1  | Pendiente |
| 2  | Atendida |

### `canal_notificacion`
| id | descripcion |
|----|-------------|
| 1  | Sistema |
| 2  | Push |
| 3  | SMS |
| 4  | Email |

---

## 1. CRUD — Paciente

### `sp_gestion_paciente`

**Firma completa:**
```sql
CALL sp_gestion_paciente(
    p_acc       CHAR(1),              -- 'I'=Insert, 'U'=Update, 'D'=Desactivar, 'L'=Listar activos
    p_id        INTEGER INOUT,        -- NULL en Insert; id del paciente en U/D
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_nom       VARCHAR(100) DEFAULT NULL,
    p_ap        VARCHAR(100) DEFAULT NULL,
    p_am        VARCHAR(100) DEFAULT NULL,
    p_nac       DATE         DEFAULT NULL,
    p_curp      VARCHAR(18)  DEFAULT NULL,
    p_foto      VARCHAR(255) DEFAULT NULL
)
```

**Cursor devuelve:** `id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento, curp, activo, foto_perfil`

**Ejemplos psycopg:**
```python
# INSERT
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_paciente('I', NULL, NULL, NULL, 'cur1', %s, %s, %s, %s, %s, NULL)",
    ['Juan', 'Pérez', 'López', '1990-05-15', 'PELJ900515HDFRZN01']
)
p_id, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur1")
paciente_row = cur.fetchone()
conn.commit()

# UPDATE (solo campos que cambian, el resto queda igual con COALESCE)
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_paciente('U', %s, NULL, NULL, 'cur1', %s, NULL, NULL, NULL, NULL, NULL)",
    [id_paciente, 'NuevoNombre']
)
_, p_ok, p_msg = cur.fetchone()
conn.commit()

# DESACTIVAR (soft delete)
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_paciente('D', %s, NULL, NULL, 'cur1')",
    [id_paciente]
)
_, p_ok, p_msg = cur.fetchone()
conn.commit()

# LISTAR activos
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_paciente('L', NULL, NULL, NULL, 'cur1')")
_, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

**Notas:**
- CURP debe tener exactamente 18 caracteres (CHECK en BD).
- `'D'` hace `activo = FALSE`, no elimina el registro.
- En UPDATE, los campos con `NULL` no se modifican.

---

## 2. CRUD — Médico

### `sp_gestion_medico`

**Firma completa:**
```sql
CALL sp_gestion_medico(
    p_acc       CHAR(1),              -- 'I', 'U', 'D', 'L'
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_nom       VARCHAR(100) DEFAULT NULL,
    p_ap        VARCHAR(100) DEFAULT NULL,
    p_am        VARCHAR(100) DEFAULT NULL,
    p_ced       VARCHAR(50)  DEFAULT NULL,
    p_email     VARCHAR(150) DEFAULT NULL,
    p_foto      VARCHAR(255) DEFAULT NULL
)
```

**Cursor devuelve:** `id_medico, nombre, apellido_p, apellido_m, cedula_profesional, email, activo`

**Ejemplos psycopg:**
```python
# INSERT
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_medico('I', NULL, NULL, NULL, 'cur1', %s, %s, %s, %s, %s, NULL)",
    ['Ana', 'García', 'Ruiz', 'CED12345', 'ana@hospital.com']
)
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()

# UPDATE email
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_medico('U', %s, NULL, NULL, 'cur1', NULL, NULL, NULL, NULL, %s, NULL)",
    [id_medico, 'nuevo@email.com']
)
_, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 3. CRUD — Cuidador

### `sp_gestion_cuidador`

**Firma completa:**
```sql
CALL sp_gestion_cuidador(
    p_acc       CHAR(1),              -- 'I', 'U', 'D', 'L', 'R'
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_nom       VARCHAR(100)       DEFAULT NULL,
    p_ap        VARCHAR(100)       DEFAULT NULL,
    p_am        VARCHAR(100)       DEFAULT NULL,
    p_tipo      tipo_cuidador_enum DEFAULT NULL,
    p_tel       VARCHAR(20)        DEFAULT NULL,
    p_email     VARCHAR(150)       DEFAULT NULL,
    p_foto      VARCHAR(255)       DEFAULT NULL
)
```

**Acciones:**
- `'I'` — Crear cuidador
- `'U'` — Actualizar datos
- `'D'` — Desactiva vínculos en `paciente_cuidador` (NO elimina al cuidador)
- `'L'` — Listar cuidadores activos
- `'R'` — Leer uno por `p_id`

**Cursor devuelve:** `id_cuidador, nombre, apellido_p, apellido_m, tipo_cuidador, telefono, email, activo`

**Ejemplos psycopg:**
```python
# INSERT
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_cuidador('I', NULL, NULL, NULL, 'cur1', %s, %s, %s, %s, %s, %s, NULL)",
    ['María', 'López', 'Soto', 'formal', '8112345678', 'maria@email.com']
)
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()

# UPDATE teléfono
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_cuidador('U', %s, NULL, NULL, 'cur1', NULL, NULL, NULL, NULL, %s, NULL, NULL)",
    [id_cuidador, '8119876543']
)
_, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 4. CRUD — Medicamento

### `sp_gestion_medicamento`

**Firma completa:**
```sql
CALL sp_gestion_medicamento(
    p_acc       CHAR(1),              -- 'I', 'U', 'D', 'L'
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_nombre    VARCHAR(150) DEFAULT NULL,
    p_atc       VARCHAR(30)  DEFAULT NULL,
    p_dmax      INTEGER      DEFAULT NULL,
    p_unidad    INTEGER      DEFAULT NULL
)
```

**Cursor devuelve (todas las acciones):**
`id_medicamento, nombre_generico, codigo_atc, dosis_max, activo, unidad, id_unidad`

| col | campo |
|-----|-------|
| 0 | id_medicamento |
| 1 | nombre_generico |
| 2 | codigo_atc |
| 3 | dosis_max |
| 4 | activo |
| 5 | unidad (abreviatura) |
| 6 | id_unidad ← necesario para pre-seleccionar el `<select>` en modales de edición |

```python
# INSERT
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_medicamento('I', NULL, NULL, NULL, 'cur1', %s, %s, %s, %s)",
    ['Metformina', 'A10BA02', 850, 1]
)
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()

# LISTAR activos (para tabla + modal de edición)
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_medicamento('L', NULL, NULL, NULL, 'cur_med_l')")
_, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur_med_l")
medicamentos = cur.fetchall()
conn.commit()
# En template: m[0]=id, m[1]=nombre, m[2]=atc, m[3]=dosis_max, m[5]=unidad, m[6]=id_unidad
```

---

## 5. CRUD — Diagnóstico

### `sp_gestion_diagnostico`

Acepta `'I'`, `'U'` y `'L'`. Los diagnósticos no se eliminan.

**Firma completa:**
```sql
CALL sp_gestion_diagnostico(
    p_acc       CHAR(1),              -- 'I', 'U', 'L'
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_desc      VARCHAR(255) DEFAULT NULL
)
```

**Cursor devuelve:** `id_diagnostico, descripcion`

```python
# LISTAR todos (para poblar <select>)
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_diagnostico('L', NULL, NULL, NULL, 'cur_diag_l')")
_, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur_diag_l")
diagnosticos = cur.fetchall()
conn.commit()

# INSERT
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_diagnostico('I', NULL, NULL, NULL, 'cur1', %s)", ['Diabetes Tipo 2'])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 6. CRUD — Especialidad

### `sp_gestion_especialidad`

Acepta `'I'`, `'U'` y `'L'`.

**Firma completa:**
```sql
CALL sp_gestion_especialidad(
    p_acc       CHAR(1),              -- 'I', 'U', 'L'
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_desc      VARCHAR(255) DEFAULT NULL
)
```

**Cursor devuelve:** `id_especialidad, descripcion`

```python
# LISTAR todas (para poblar <select>)
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_especialidad('L', NULL, NULL, NULL, 'cur_esp_l')")
_, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur_esp_l")
especialidades = cur.fetchall()
conn.commit()

# INSERT
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_especialidad('I', NULL, NULL, NULL, 'cur1', %s)", ['Cardiología'])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 7. CRUD IoT — Beacon

### `sp_gestion_beacon`

**Firma completa:**
```sql
CALL sp_gestion_beacon(
    p_acc       CHAR(1),
    p_id        BIGINT INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_uuid      VARCHAR(50)   DEFAULT NULL,
    p_nom       VARCHAR(150)  DEFAULT NULL,
    p_pac       INTEGER       DEFAULT NULL,
    p_lat       NUMERIC(10,7) DEFAULT NULL,
    p_lon       NUMERIC(10,7) DEFAULT NULL,
    p_radio     NUMERIC(6,2)  DEFAULT 5.00
)
```

**Cursor devuelve:** `id_beacon, uuid_beacon, nombre, id_paciente, latitud_ref, longitud_ref, radio_metros, activo`

```python
# INSERT
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_beacon('I', NULL, NULL, NULL, 'cur1', %s, %s, %s, %s, %s, %s)",
    ['uuid-abc-123', 'Beacon Habitación', id_paciente, 25.6866, -100.3161, 5.0]
)
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()

# DESACTIVAR
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_beacon('D', %s, NULL, NULL, 'cur1')", [id_beacon])
_, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 8. CRUD IoT — GPS

### `sp_gestion_gps`

**Un cuidador solo puede tener un GPS activo** (UNIQUE en `id_cuidador`).

**Firma completa:**
```sql
CALL sp_gestion_gps(
    p_acc       CHAR(1),
    p_id        BIGINT INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_imei      VARCHAR(20)  DEFAULT NULL,
    p_mod       VARCHAR(100) DEFAULT NULL,
    p_cuid      INTEGER      DEFAULT NULL
)
```

**Cursor devuelve:** `id_gps, imei, modelo, id_cuidador, activo, fecha_asignacion, cuidador`

```python
# INSERT
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_gps('I', NULL, NULL, NULL, 'cur1', %s, %s, %s)",
    ['123456789012345', 'GPS Tracker V2', id_cuidador]
)
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 9. Recetas

### `sp_crear_receta`

**Firma completa:**
```sql
CALL sp_crear_receta(
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_pac       INTEGER,
    p_med       INTEGER,
    p_emi       DATE,
    p_ini       DATE,
    p_fin       DATE
)
```

**Cursor devuelve:** `id_receta, id_paciente, paciente, id_medico, medico, fecha_emision, fecha_inicio, fecha_fin, estado_receta`

```python
cur.execute("BEGIN")
cur.execute(
    "CALL sp_crear_receta(NULL, NULL, NULL, 'cur1', %s, %s, %s, %s, %s)",
    [id_paciente, id_medico, '2026-04-15', '2026-04-15', '2026-05-15']
)
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

### `sp_agregar_receta_med`

Agrega un medicamento a una receta vigente.
**Dispara automáticamente `trg_generar_agenda`** que crea todas las entradas en `agenda_toma`.

**Firma completa:**
```sql
CALL sp_agregar_receta_med(
    p_id_rm     INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_rec       INTEGER,
    p_medic     INTEGER,
    p_dosis     INTEGER,
    p_freq      INTEGER,
    p_tol       INTEGER,
    p_hora      TIME,
    p_uni       INTEGER
)
```

**Cursor devuelve:** `id_receta_medicamento, id_receta, medicamento, dosis_prescrita, unidad, frecuencia_horas, tolerancia_min, hora_primera_toma, agendas_generadas`

```python
cur.execute("BEGIN")
cur.execute(
    "CALL sp_agregar_receta_med(NULL, NULL, NULL, 'cur1', %s, %s, %s, %s, %s, %s, %s)",
    [id_receta, id_medicamento, 500, 8, 30, '08:00:00', 1]
)
p_id_rm, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur1")
detalle = cur.fetchone()
conn.commit()
```

---

### `sp_cancelar_receta`

Cancela una receta vigente: agendas pendientes → `'omitida'`, etiquetas NFC → `'inactivo'`.

**Firma completa:**
```sql
CALL sp_cancelar_receta(
    p_rec       INTEGER IN,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT
)
```

**Cursor devuelve:** `id_receta, estado_receta, agendas_omitidas, etiquetas_desactivadas`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_cancelar_receta(%s, NULL, NULL, 'cur1')", [id_receta])
p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 10. Registro de Toma NFC

### `sp_registrar_toma_nfc`

SP principal del flujo operativo. Registra una toma escaneada por NFC.

**Internamente:**
1. Valida la etiqueta NFC.
2. Registra ubicación GPS del cuidador (requiere GPS activo para generar alerta de proximidad).
3. Calcula distancia al beacon del paciente (Haversine).
4. Inserta en `evento_nfc` → dispara `trg_antes_evento` y `trg_despues_evento`.
5. Inserta en `evento_proximidad`.
6. Si GPS verificado y distancia > radio → genera alerta `'Proximidad Inválida'`.

**Firma completa:**
```sql
CALL sp_registrar_toma_nfc(
    p_id_ev     BIGINT INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    p_res       VARCHAR(50) OUT,
    p_prox      BOOLEAN OUT,
    io_cursor   REFCURSOR INOUT,
    p_uid       VARCHAR(100),
    p_cuid      INTEGER,
    p_lat       NUMERIC(10,7),
    p_lon       NUMERIC(10,7),
    p_prec      NUMERIC(6,2) DEFAULT NULL,
    p_obs       VARCHAR(255) DEFAULT NULL
)
```

**Cursor devuelve:** `id_evento, timestamp_lectura, resultado, desfase_min, distancia_metros, proximidad_valida, cuidador, paciente, medicamento`

```python
cur.execute("BEGIN")
cur.execute("""
    CALL sp_registrar_toma_nfc(NULL, NULL, NULL, NULL, NULL, 'cur1',
                               %s, %s, %s, %s, %s, %s)
""", [uid_nfc, id_cuidador, lat, lon, 5.0, 'Toma registrada'])
p_id_ev, p_ok, p_msg, p_res, p_prox = cur.fetchone()
cur.execute("FETCH ALL FROM cur1")
evento_detalle = cur.fetchone()
conn.commit()

if p_ok == 1:
    flash(f"Toma {p_res}. Proximidad: {'válida' if p_prox else 'INVÁLIDA'}")
```

**Resultados posibles de `p_res`:**
| Valor | Significado |
|-------|-------------|
| `'Exitoso'` | Toma dentro de ventana de tolerancia |
| `'Tardío'` | Toma fuera de tolerancia pero registrada |
| `'Duplicado'` | Ya existe evento exitoso/tardío para esa agenda en la misma ventana |

---

## 11. Alertas

### `sp_marcar_alerta_atendida`

**Firma completa:**
```sql
CALL sp_marcar_alerta_atendida(
    p_id_al     BIGINT IN,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_obs       VARCHAR(255) DEFAULT NULL
)
```

**Cursor devuelve:** `id_alerta, tipo, estado, prioridad, timestamp_gen, paciente, medicamento`

```python
cur.execute("BEGIN")
cur.execute(
    "CALL sp_marcar_alerta_atendida(%s, NULL, NULL, 'cur1', %s)",
    [id_alerta, 'Cuidador notificado vía teléfono']
)
p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 12. Login

**`sp_login` existe en la BD pero NO se usa desde Flask.**
La verificación bcrypt debe hacerse en Python.

**Flujo correcto:**
```python
import bcrypt

# 1. Obtener hash de la BD
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

# 2. Verificar bcrypt
if row and bcrypt.checkpw(password.encode(), row[1].encode()):
    session['user_id'] = row[0]
    session['rol']     = row[2]
    session['id_rol']  = row[3]
    session['nombre']  = row[4]
    cur.execute(
        "INSERT INTO log_acceso (id_usr, email, rol, ip, exitoso) VALUES (%s,%s,%s,%s,TRUE)",
        [row[0], email, row[2], request.remote_addr]
    )
    conn.commit()
else:
    cur.execute(
        "INSERT INTO log_acceso (id_usr, email, rol, ip, exitoso) "
        "SELECT id_usuario, %s, rol_usuario::TEXT, %s, FALSE "
        "FROM usuario WHERE email = %s LIMIT 1",
        [email, request.remote_addr, email]
    )
    conn.commit()
```

**Admin:** credenciales en `.env` (`ADMIN_EMAIL`, `ADMIN_PASSWORD_HASH`). No vive en la tabla `usuario`.

---

## 13. Omisiones (Proceso Batch)

### `sp_detectar_omisiones`

Busca todas las `agenda_toma` en `'pendiente'` cuya ventana ya venció,
las marca como `'omitida'` y genera alertas. Ejecutar con cron (ej. cada hora).

**Firma completa:**
```sql
CALL sp_detectar_omisiones(
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    p_total     INTEGER OUT,
    io_cursor   REFCURSOR INOUT
)
```

**Cursor devuelve:** `id_alerta, timestamp_gen, paciente, medicamento, toma_programada`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_detectar_omisiones(NULL, NULL, NULL, 'cur1')")
p_ok, p_msg, p_total = cur.fetchone()
cur.execute("FETCH ALL FROM cur1")
omisiones = cur.fetchall()
conn.commit()
print(f"Omisiones detectadas: {p_total}")
```

---

## 14. Asignaciones

### `sp_asignar_diagnostico`

**Ruta Flask:** `POST /medico/paciente/<id_pac>/asignar-diagnostico` → `medico_asignar_diagnostico` (`@rol_requerido('medico')`)

**Firma completa:**
```sql
CALL sp_asignar_diagnostico(
    p_pac       INTEGER IN,
    p_diag      INTEGER IN,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT
)
```

**Cursor devuelve:** `id_paciente, paciente, id_diagnostico, diagnostico, activo`

**Notas:**
- Si el diagnóstico ya existía pero estaba inactivo, lo reactiva (`ON CONFLICT DO UPDATE SET activo = TRUE`).
- Requiere auditoría: ejecutar `set_config` **antes** del `BEGIN`.
- Para poblar el `<select>` del formulario usar `sp_gestion_diagnostico('L', ...)` en el GET del perfil.

```python
# En la ruta GET — cargar catálogo para el <select>
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_diagnostico('L', NULL, NULL, NULL, 'cur_diag_cat')")
_, p_ok_cat, _ = cur.fetchone()
if p_ok_cat != 1:
    conn.rollback()
else:
    cur.execute("FETCH ALL FROM cur_diag_cat")
    diagnosticos_catalogo = cur.fetchall()  # d[0]=id_diagnostico, d[1]=descripcion
    conn.commit()

# En la ruta POST — asignar con auditoría
cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)", [str(session['user_id'])])
cur.execute("BEGIN")
cur.execute(
    "CALL sp_asignar_diagnostico(%s, %s, NULL, NULL, 'cur_asig_diag')",
    [id_pac, id_diagnostico]
)
p_ok, p_msg = cur.fetchone()[:2]
cur.execute("FETCH ALL FROM cur_asig_diag")
if p_ok == 1:
    conn.commit()
    flash(p_msg, 'success')
else:
    conn.rollback()
    flash(p_msg, 'danger')
```

---

### `sp_asignar_cuidador`

**Un solo cuidador principal activo por paciente** (índice único parcial).
Para cambiar el principal: primero `UPDATE paciente_cuidador SET activo=FALSE` del anterior, luego llamar este SP con `p_princ=True`.

**Firma completa:**
```sql
CALL sp_asignar_cuidador(
    p_pac       INTEGER IN,
    p_cuid      INTEGER IN,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_princ     BOOLEAN DEFAULT FALSE
)
```

**Cursor devuelve:** `id_paciente_cuidador, paciente, cuidador, es_principal, activo`

```python
cur.execute("BEGIN")
cur.execute(
    "CALL sp_asignar_cuidador(%s, %s, NULL, NULL, 'cur1', %s)",
    [id_paciente, id_cuidador, True]
)
p_ok, p_msg = cur.fetchone()
conn.commit()
```

> **Cambio de cuidador principal:**
> ```python
> # 1. Desactivar el anterior
> cur.execute("""
>     UPDATE paciente_cuidador SET activo = FALSE
>     WHERE id_paciente = %s AND es_principal = TRUE AND activo = TRUE
> """, [id_paciente])
> # 2. Asignar el nuevo
> cur.execute("BEGIN")
> cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, 'cur1', TRUE)",
>             [id_paciente, id_cuidador_nuevo])
> p_ok, p_msg = cur.fetchone()
> conn.commit()
> ```

---

### `sp_asignar_especialidad`

**Firma completa:**
```sql
CALL sp_asignar_especialidad(
    p_med       INTEGER IN,
    p_esp       INTEGER IN,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT
)
```

```python
cur.execute("BEGIN")
cur.execute(
    "CALL sp_asignar_especialidad(%s, %s, NULL, NULL, 'cur1')",
    [id_medico, id_especialidad]
)
p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

### `sp_desasignar_cuidador`

Desactiva el vínculo de un cuidador de apoyo (NO se puede desasignar al principal).

**Firma completa:**
```sql
CALL sp_desasignar_cuidador(
    p_id_pac_cuid   INTEGER IN,   -- id_paciente_cuidador
    p_ok            INTEGER OUT,
    p_msg           VARCHAR(300) OUT,
    io_cursor       REFCURSOR INOUT
)
```

```python
cur.execute("BEGIN")
cur.execute(
    "CALL sp_desasignar_cuidador(%s, NULL, NULL, 'cur1')",
    [id_paciente_cuidador]
)
p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 15. Crear Usuario

### `sp_crear_usuario_admin`

**Firma completa:**
```sql
CALL sp_crear_usuario_admin(
    p_email         VARCHAR(150) IN,
    p_password_hash TEXT IN,
    p_rol           rol_usuario_enum,
    p_id_rol        INTEGER IN,
    p_ok            INTEGER OUT,
    p_msg           VARCHAR(300) OUT,
    io_cursor       REFCURSOR INOUT
)
```

**Cursor devuelve:** `id_usuario, email, rol_usuario, activo`

```python
import bcrypt

password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

cur.execute("BEGIN")
cur.execute(
    "CALL sp_crear_usuario_admin(%s, %s, %s::rol_usuario_enum, %s, NULL, NULL, 'cur1')",
    [email, password_hash, rol, id_rol]
)
p_ok, p_msg, _ = cur.fetchone()
conn.commit()
```

**Flujo completo — crear médico + usuario:**
```python
# 1. Crear el médico
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_medico('I', NULL, NULL, NULL, 'cur_med', %s, %s, %s, %s, %s, NULL)",
    ['Ana', 'García', 'Ruiz', 'CED12345', 'ana@hospital.com']
)
id_medico, p_ok, p_msg = cur.fetchone()
conn.commit()

# 2. Crear el usuario vinculado
password_hash = bcrypt.hashpw('password123'.encode(), bcrypt.gensalt()).decode()
cur.execute("BEGIN")
cur.execute(
    "CALL sp_crear_usuario_admin(%s, %s, 'medico'::rol_usuario_enum, %s, NULL, NULL, 'cur_usr')",
    ['ana@hospital.com', password_hash, id_medico]
)
p_ok, p_msg, _ = cur.fetchone()
conn.commit()
```

---

### `sp_gestion_usuario`

Gestión de usuarios existentes: actualizar email/password, activar, desactivar.

**Firma completa:**
```sql
CALL sp_gestion_usuario(
    p_acc           CHAR(1),          -- 'U'=Update, 'D'=Desactivar, 'A'=Activar
    p_id_usuario    INTEGER IN,
    p_ok            INTEGER OUT,
    p_msg           VARCHAR(300) OUT,
    io_cursor       REFCURSOR INOUT,
    p_email         VARCHAR(150) DEFAULT NULL,
    p_password_hash TEXT         DEFAULT NULL
)
```

**Cursor devuelve:** `id_usuario, email, rol_usuario, activo, ultimo_acceso`

```python
# Desactivar usuario
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_usuario('D', %s, NULL, NULL, 'cur1')", [id_usuario])
p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 16. Horario de Cuidador

### `sp_gestion_horario`

Gestiona turnos semanales de un cuidador para un paciente.
Usa `id_paciente_cuidador` (PK de `paciente_cuidador`), NO `id_cuidador`.

**Firma completa:**
```sql
CALL sp_gestion_horario(
    p_acc       CHAR(1),              -- 'I'=Insertar, 'D'=Eliminar, 'L'=Listar
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_pac_cuid  INTEGER      DEFAULT NULL,
    p_dia       dia_semana_enum DEFAULT NULL,
    p_inicio    TIME         DEFAULT NULL,
    p_fin       TIME         DEFAULT NULL
)
```

**Acciones:**
| Acción | Parámetros requeridos | Cursor devuelve |
|--------|----------------------|-----------------|
| `'I'` | `p_pac_cuid`, `p_dia`, `p_inicio`, `p_fin` | Turno creado con nombre cuidador/paciente |
| `'D'` | `p_id` (id_cuidador_horario) | `ok, msg` |
| `'L'` | `p_pac_cuid` | Todos los turnos del vínculo, ordenados por día/hora |

**Validaciones:**
- `hora_fin` > `hora_inicio` → `p_ok = -2`
- Vínculo debe existir y estar activo → `p_ok = -3`
- Turno debe existir para eliminarlo → `p_ok = -4`

**Ejemplos psycopg:**
```python
# Obtener id_paciente_cuidador
cur.execute("""
    SELECT id_paciente_cuidador FROM paciente_cuidador
    WHERE id_paciente = %s AND id_cuidador = %s AND activo = TRUE
""", [id_paciente, id_cuidador])
id_pc = cur.fetchone()[0]

# INSERTAR turno
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_horario('I', NULL, NULL, NULL, 'cur1', %s, %s, %s, %s)",
    [id_pc, 'lunes', '08:00:00', '14:00:00']
)
p_id, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur1")
turno = cur.fetchone()
conn.commit()

# LISTAR turnos de un vínculo
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_horario('L', NULL, NULL, NULL, 'cur1', %s)", [id_pc])
p_id, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur1")
turnos = cur.fetchall()
conn.commit()

# ELIMINAR turno
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_horario('D', %s, NULL, NULL, 'cur1')", [id_cuidador_horario])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 17. Badge de alertas — Views (no SP)

```python
if session['rol'] == 'medico':
    cur.execute(
        "SELECT total_pendientes FROM v_alertas_pendientes_medico WHERE id_usuario = %s",
        [session['user_id']]
    )
elif session['rol'] == 'cuidador':
    cur.execute(
        "SELECT total_pendientes FROM v_alertas_pendientes_cuidador WHERE id_usuario = %s",
        [session['user_id']]
    )
row   = cur.fetchone()
total = row[0] if row else 0
```

---

## 18. SP de Reportes (sp_rep_*)

> **Regla absoluta:** Flask **NUNCA hace SELECT directo** a Views ni tablas.
> Siempre `CALL sp_rep_*('cursor', ...)` + `FETCH ALL FROM cursor`.

**`io_cursor` va como primer parámetro** en todos los `sp_rep_*`.

```python
# Patrón Python para TODOS los sp_rep_*
cur.execute("BEGIN")
cur.execute("CALL sp_rep_nombre('cur1', %s, %s)", [param1, param2])
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_dashboard_cuidador`
**Firma:** `(INOUT io_cursor, IN p_cuidador INTEGER, IN p_fecha DATE DEFAULT CURRENT_DATE)`
**Columnas:** `id_cuidador, id_paciente, paciente, medicamento, fecha_hora_programada, tolerancia_min, estado_agenda, dosis_prescrita, unidad, alertas_pend`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_dashboard_cuidador('cur1', %s)", [id_cuidador])
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_agenda_dia_cuidador`
**Firma:** `(INOUT io_cursor, IN p_cuidador INTEGER, IN p_fecha DATE DEFAULT CURRENT_DATE)`
**Columnas:** `id_cuidador, id_agenda, fecha_hora_programada, estado_agenda, tolerancia_min, id_paciente, paciente, nombre_generico, dosis_prescrita, unidad, uid_nfc`

---

### `sp_rep_alertas_cuidador`
**Firma:** `(INOUT io_cursor, IN p_cuidador INTEGER, IN p_sol_pendientes BOOLEAN DEFAULT TRUE)`
**Columnas:** `id_cuidador, id_alerta, prioridad, tipo, estado, timestamp_gen, paciente, medicamento`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_alertas_cuidador('cur1', %s)", [id_cuidador])       # solo pendientes
cur.execute("CALL sp_rep_alertas_cuidador('cur1', %s, FALSE)", [id_cuidador]) # todas
```

---

### `sp_rep_alertas_medico`
**Firma:** `(INOUT io_cursor, IN p_medico INTEGER, IN p_sol_pendientes BOOLEAN DEFAULT TRUE)`
**Columnas:** `id_medico, id_alerta, prioridad, tipo, estado, timestamp_gen, paciente, medicamento, id_evento`

---

### `sp_rep_badge_alertas`
**Firma:** `(INOUT io_cursor, IN p_usuario INTEGER, IN p_rol VARCHAR(10))`
**Columnas:** `total_pendientes`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_badge_alertas('cur1', %s, %s)", [session['user_id'], session['rol']])
cur.execute("FETCH ALL FROM cur1")
total = cur.fetchone()[0] if cur.fetchone() else 0
conn.commit()
```

---

### `sp_rep_pacientes_medico`
**Firma:** `(INOUT io_cursor, IN p_medico INTEGER)`
**Columnas:** `id_medico, id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento, curp, activo, id_receta, estado_receta, fecha_inicio, fecha_fin`

---

### `sp_rep_perfil_paciente`
**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER)`
**Columnas:** `id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento, curp, activo, diagnosticos, cuidador_princ, medicamentos`

---

### `sp_rep_recetas_paciente`
**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER, IN p_estado_receta VARCHAR(20) DEFAULT NULL)`
**Columnas:** `id_paciente, id_receta, estado_receta, fecha_emision, fecha_inicio, fecha_fin, medico, id_receta_medicamento, nombre_generico, dosis_prescrita, unidad, frecuencia_horas, tolerancia_min, hora_primera_toma`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_recetas_paciente('cur1', %s, 'vigente')", [id_paciente])
# o sin filtro: cur.execute("CALL sp_rep_recetas_paciente('cur1', %s)", [id_paciente])
```

---

### `sp_rep_historial_tomas`
**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER, IN p_dias INTEGER DEFAULT 14)`
**Columnas:** `id_paciente, id_evento, timestamp_lectura, uid_nfc, resultado, desfase_min, origen, observaciones, fecha_registro, medicamento, cuidador, distancia_metros, proximidad_valida`

---

### `sp_rep_adherencia_pacientes_medico`
**Firma:** `(INOUT io_cursor, IN p_medico INTEGER, IN p_dias INTEGER DEFAULT 14)`
**Columnas:** `id_paciente, paciente, medicamento, total, ok, tarde, omitida, pend, pct`

---

### `sp_rep_adherencia_medicos`
**Firma:** `(INOUT io_cursor, IN p_dias INTEGER DEFAULT 14)`
**Columnas:** `id_medico, medico, total, ok, tarde, omitida, pct`

---

### `sp_rep_adherencia_cuidadores`
**Firma:** `(INOUT io_cursor, IN p_dias INTEGER DEFAULT 14)`
**Columnas:** `id_cuidador, cuidador, total, ok, tarde, omitida, pct`

---

### `sp_rep_grafica_tomas`
**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER, IN p_dias INTEGER DEFAULT 14)`
**Columnas:** `id_paciente, fecha, total, correctas, fuera_horario, no_tomadas, pendientes`

---

### `sp_rep_mapa_medico`
**Firma:** `(INOUT io_cursor, IN p_medico INTEGER)`
**Columnas:** `id_medico, id_paciente, paciente, id_beacon, bec_lat, bec_lon, radio_metros, gps_lat, gps_lon, gps_ts, cuidador`

---

### `sp_rep_bitacora`
**Firma:** `(INOUT io_cursor, IN p_dias INTEGER DEFAULT 7, IN p_limite INTEGER DEFAULT 100)`
**Columnas:** `id_bitacora, id_evento, regla_aplicada, resultado, detalle, timestamp_eval, uid_nfc, timestamp_lectura, paciente, medicamento`

---

### `sp_rep_auditoria`
**Firma:** `(INOUT io_cursor, IN p_tabla VARCHAR(80) DEFAULT NULL, IN p_limite INTEGER DEFAULT 100)`
**Columnas:** `id_audit, tabla, id_reg, accion, campo, val_antes, val_despues, usuario_db, id_usr_app, ts`

---

### `sp_rep_log_acceso`
**Firma:** `(INOUT io_cursor, IN p_usuario INTEGER DEFAULT NULL, IN p_limite INTEGER DEFAULT 100)`
**Columnas:** `id_log, id_usr, email, rol, ip, exitoso, ts`

---

### `sp_rep_carga_medicos`
**Firma:** `(INOUT io_cursor)`
**Columnas:** `id_medico, medico, cedula_profesional, total_pac, pacientes`

---

### `sp_rep_supervision`
**Firma:** `(INOUT io_cursor)`
**Columnas:** `id_paciente, paciente, id_medico, medico, id_receta, estado_receta, fecha_inicio, fecha_fin`

---

### `sp_rep_dispositivos_iot`
**Firma:** `(INOUT io_cursor)`
**Columnas:** `tipo` (`'GPS'`|`'BEACON'`), `id_disp, ident, nombre, asignado, activo`

---

### `sp_rep_tendencia_adherencia`
**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER DEFAULT NULL, IN p_dias INTEGER DEFAULT 30)`
**Columnas:** `id_paciente, paciente, fecha, total_citas, cumplidas, tardias, omitidas, pct_dia, promedio_movil_7d, tendencia`
**`tendencia`:** `'INICIO'`, `'MEJORA'`, `'DECLIVE'`, `'ESTABLE'`

---

### `sp_rep_riesgo_omision`
**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER DEFAULT NULL, IN p_solo_activas BOOLEAN DEFAULT TRUE, IN p_min_dias INTEGER DEFAULT 2)`
**Columnas:** `id_paciente, paciente, medicamento, inicio_racha, fin_racha, dias_consecutivos, nivel_riesgo, racha_activa, dias_desde_ultima_omision`
**`nivel_riesgo`:** `'CRÍTICO'` (≥5), `'ALTO'` (≥3), `'MODERADO'` (<3)

---

### `sp_rep_ranking_mejora`
**Firma:** `(INOUT io_cursor, IN p_rol VARCHAR(10) DEFAULT NULL)`
**Columnas:** `rol, id_persona, nombre, pct_anterior, pct_reciente, delta_pct, rank_mejora, dense_rank_mejora, cuartil_mejora, clasificacion`
**`clasificacion`:** `'MEJORA SIGNIFICATIVA'`, `'MEJORA LEVE'`, `'SIN CAMBIO'`, `'DECLIVE LEVE'`, `'DECLIVE SIGNIFICATIVO'`

---

### `sp_rep_vinculo_paciente_cuidador`
**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER, IN p_solo_activo BOOLEAN DEFAULT TRUE)`
**Columnas:** `id_paciente_cuidador, id_cuidador, es_principal, activo, cuidador`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_vinculo_paciente_cuidador('cur1', %s)", [id_paciente])
cur.execute("FETCH ALL FROM cur1")
vinculos = cur.fetchall()
conn.commit()
```

---

### `sp_rep_recetas_medico`
**Firma:** `(INOUT io_cursor, IN p_medico INTEGER, IN p_estado VARCHAR(20) DEFAULT NULL)`
**Columnas:** `id_receta, pac_nombre, estado_receta, fecha_emision, fecha_inicio, fecha_fin, id_receta_medicamento, nombre_generico, dosis_prescrita, unidad, frecuencia_horas, tolerancia_min, hora_primera_toma`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_recetas_medico('cur1', %s)", [id_medico])            # todas
cur.execute("CALL sp_rep_recetas_medico('cur1', %s, 'vigente')", [id_medico]) # solo vigentes
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_detalle_paciente_admin`
**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER)`
**Columnas:** `id_paciente, paciente, id_medico, medico, id_cuidador, cuidador, es_principal, id_receta, estado_receta, fecha_inicio, fecha_fin, medicamento, dosis_prescrita, unidad, frecuencia_horas`

---

### `sp_rep_pacientes_cuidador_admin`
**Firma:** `(INOUT io_cursor, IN p_cuidador INTEGER)`
**Columnas:** `id_cuidador, cuidador, id_paciente, paciente, es_principal, medico_responsable, id_receta, estado_receta, medicamento, dosis_prescrita, unidad, frecuencia_horas`

---

### `sp_rep_pacientes_medico_admin`
**Firma:** `(INOUT io_cursor, IN p_medico INTEGER)`
**Columnas:** `id_medico, medico, id_paciente, paciente, cuidador_principal, id_receta, estado_receta, fecha_inicio, fecha_fin, medicamento, dosis_prescrita, unidad, frecuencia_horas`

---

### `sp_rep_lista_cuidadores`
**Firma:** `(INOUT io_cursor)`
**Columnas:** `id_cuidador, cuidador`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_lista_cuidadores('cur1')")
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_lista_usuarios`
**Firma:** `(INOUT io_cursor)`
**Columnas:** `id_usuario, email, rol_usuario, activo, ultimo_acceso, nombre_persona, id_rol`

---

## 19. SPs nuevos (agregados post-v9)

### `sp_gestion_etiqueta_nfc`

Gestión de etiquetas NFC: registrar, actualizar estado, listar por receta.

**Firma completa:**
```sql
CALL sp_gestion_etiqueta_nfc(
    p_acc       CHAR(1),                    -- 'I', 'U', 'L'
    p_uid       VARCHAR(100) INOUT,         -- UID de la etiqueta
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_nombre    VARCHAR(150)         DEFAULT NULL,
    p_tipo      VARCHAR(100)         DEFAULT NULL,
    p_rm        INTEGER              DEFAULT NULL,  -- FK receta_medicamento.id_receta_medicamento
    p_estado    estado_etiqueta_enum DEFAULT 'activo'
)
```

**Cursor devuelve:** `uid_nfc, nombre, tipo_etiqueta, id_receta_medicamento, estado_etiqueta, fecha_registro`

```python
# INSERT (reemplaza INSERT directo en etiqueta_nfc)
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_etiqueta_nfc('I', %s, NULL, NULL, 'cur_nfc', %s, %s, %s, %s)",
    [uid_nfc, nombre_etiqueta, tipo_etiqueta, id_receta_medicamento, 'activo']
)
p_uid, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur_nfc")
conn.commit()

# LISTAR por receta_medicamento
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_etiqueta_nfc('L', NULL, NULL, NULL, 'cur_nfc_l', NULL, NULL, %s)",
    [id_receta_medicamento]
)
p_uid, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur_nfc_l")
etiquetas = cur.fetchall()
conn.commit()
```

---

### `sp_rep_gps_cuidador`

GPS activo del cuidador con su última ubicación registrada.

**Firma:** `(INOUT io_cursor, IN p_cuidador INTEGER)`

**Columnas:**

| col | campo |
|-----|-------|
| 0 | id_gps |
| 1 | imei |
| 2 | modelo |
| 3 | activo |
| 4 | fecha_asignacion |
| 5 | latitud |
| 6 | longitud |
| 7 | timestamp_ubicacion |

```python
# Reemplaza SELECT directo a gps_imei + ubicacion_gps
cur.execute("BEGIN")
cur.execute("CALL sp_rep_gps_cuidador('cur_gps', %s)", [id_cuidador])
cur.execute("FETCH ALL FROM cur_gps")
gps_row = cur.fetchone()   # None si el cuidador no tiene GPS activo
conn.commit()

if gps_row:
    imei      = gps_row[1]
    latitud   = gps_row[5]
    longitud  = gps_row[6]
    ultima_ts = gps_row[7]
```

---

### `sp_rep_perfil_paciente_foto`

Igual que `sp_rep_perfil_paciente` pero incluye `foto_perfil`.

**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER)`

**Columnas:**

| col | campo |
|-----|-------|
| 0 | id_paciente |
| 1 | nombre |
| 2 | apellido_p |
| 3 | apellido_m |
| 4 | fecha_nacimiento |
| 5 | curp |
| 6 | activo |
| 7 | foto_perfil ← col extra vs sp_rep_perfil_paciente |
| 8 | diagnosticos |
| 9 | cuidador_princ |
| 10 | medicamentos |

```python
# Reemplaza SELECT foto_perfil FROM paciente WHERE id_paciente = %s
cur.execute("BEGIN")
cur.execute("CALL sp_rep_perfil_paciente_foto('cur_perf', %s)", [id_paciente])
cur.execute("FETCH ALL FROM cur_perf")
row = cur.fetchone()
conn.commit()

foto     = row[7]
nombre   = row[1]
apellido = row[2]
```

---

### `sp_rep_conteos_admin`

Todos los conteos del dashboard admin en **una sola fila**.

**Firma:** `(INOUT io_cursor)`

**Columnas:**

| col | campo |
|-----|-------|
| 0 | total_medicos |
| 1 | total_cuidadores |
| 2 | total_pacientes |
| 3 | total_medicamentos |
| 4 | total_gps |
| 5 | total_beacon |
| 6 | total_alertas_pendientes |

```python
# Reemplaza los 7 SELECT COUNT(*) directos del admin_dashboard
cur.execute("BEGIN")
cur.execute("CALL sp_rep_conteos_admin('cur_conteos')")
cur.execute("FETCH ALL FROM cur_conteos")
row = cur.fetchone()
conn.commit()

total_medicos            = row[0]
total_cuidadores         = row[1]
total_pacientes          = row[2]
total_medicamentos       = row[3]
total_gps                = row[4]
total_beacon             = row[5]
total_alertas_pendientes = row[6]
```

---

### `sp_rep_unidades_dosis`

Lista todas las unidades de dosis para poblar `<select>` en formularios.

**Firma:** `(INOUT io_cursor)`

**Columnas:** `id_unidad, abreviatura, descripcion`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_unidades_dosis('cur_uni')")
cur.execute("FETCH ALL FROM cur_uni")
unidades = cur.fetchall()
conn.commit()
# En template: u[0]=id_unidad, u[1]=abreviatura, u[2]=descripcion
```

---

## 20. Triggers automáticos (no llamar directamente)

| Trigger | Tabla | Momento | Qué hace |
|---------|-------|---------|----------|
| `trg_antes_evento` | `evento_nfc` | BEFORE INSERT | Calcula desfase, detecta duplicados, clasifica resultado, actualiza agenda |
| `trg_despues_evento` | `evento_nfc` | AFTER INSERT | Inserta en `alerta` y `bitacora_regla_negocio` |
| `trg_generar_agenda` | `receta_medicamento` | AFTER INSERT | Genera todas las entradas de `agenda_toma` |
| `trg_audit_paciente` | `paciente` | AFTER INSERT/UPDATE | Registra cambios en `audit_cambios` |
| `trg_audit_medico` | `medico` | AFTER INSERT/UPDATE | Registra cambios en `audit_cambios` |
| `trg_audit_cuidador` | `cuidador` | AFTER INSERT/UPDATE | Registra cambios en `audit_cambios` |
| `trg_audit_usuario` | `usuario` | AFTER INSERT/UPDATE | Registra cambios en `audit_cambios` |

---

## Referencia rápida — SPs totales

### CRUD y Operativos

| SP | Acciones | Rol |
|----|----------|-----|
| `sp_gestion_paciente` | I/U/D/L | Admin/Médico |
| `sp_gestion_medico` | I/U/D/L | Admin |
| `sp_gestion_cuidador` | I/U/D/L/R | Admin |
| `sp_gestion_medicamento` | I/U/D/L | Admin |
| `sp_gestion_diagnostico` | I/U/L | Admin |
| `sp_gestion_especialidad` | I/U/L | Admin |
| `sp_gestion_beacon` | I/U/D | Admin |
| `sp_gestion_gps` | I/U/D | Admin |
| `sp_gestion_horario` | I/D/L | Admin/Médico |
| `sp_gestion_usuario` | U/D/A | Admin |
| `sp_crear_receta` | — | Médico |
| `sp_agregar_receta_med` | — | Médico |
| `sp_cancelar_receta` | — | Médico |
| `sp_registrar_toma_nfc` | — | Cuidador |
| `sp_marcar_alerta_atendida` | — | Médico/Cuidador |
| `sp_detectar_omisiones` | — | Sistema (cron) |
| `sp_asignar_diagnostico` | — | Médico |
| `sp_asignar_cuidador` | — | Admin |
| `sp_desasignar_cuidador` | — | Admin |
| `sp_asignar_especialidad` | — | Admin |
| `sp_crear_usuario_admin` | — | Admin |
| `sp_gestion_etiqueta_nfc` | I/U/L | Admin/Médico |
| ~~`sp_login`~~ | — | ~~No usar~~ |

### Reportes sp_rep_* (31 SPs)

| SP | Rol |
|----|-----|
| `sp_rep_dashboard_cuidador` | Cuidador |
| `sp_rep_agenda_dia_cuidador` | Cuidador |
| `sp_rep_alertas_cuidador` | Cuidador |
| `sp_rep_alertas_medico` | Médico |
| `sp_rep_badge_alertas` | Médico/Cuidador |
| `sp_rep_pacientes_medico` | Médico |
| `sp_rep_perfil_paciente` | Médico |
| `sp_rep_recetas_paciente` | Médico/Cuidador |
| `sp_rep_historial_tomas` | Médico |
| `sp_rep_adherencia_pacientes_medico` | Médico |
| `sp_rep_adherencia_medicos` | Admin |
| `sp_rep_adherencia_cuidadores` | Admin |
| `sp_rep_grafica_tomas` | Médico |
| `sp_rep_mapa_medico` | Médico |
| `sp_rep_bitacora` | Admin |
| `sp_rep_auditoria` | Admin |
| `sp_rep_log_acceso` | Admin |
| `sp_rep_carga_medicos` | Admin |
| `sp_rep_supervision` | Admin |
| `sp_rep_dispositivos_iot` | Admin |
| `sp_rep_tendencia_adherencia` | Médico/Admin |
| `sp_rep_riesgo_omision` | Médico/Admin |
| `sp_rep_ranking_mejora` | Admin |
| `sp_rep_vinculo_paciente_cuidador` | Admin/Médico |
| `sp_rep_recetas_medico` | Médico |
| `sp_rep_detalle_paciente_admin` | Admin |
| `sp_rep_pacientes_cuidador_admin` | Admin |
| `sp_rep_pacientes_medico_admin` | Admin |
| `sp_rep_lista_cuidadores` | Admin |
| `sp_rep_lista_usuarios` | Admin |
| `sp_rep_gps_cuidador` | Cuidador/Admin |
| `sp_rep_perfil_paciente_foto` | Médico/Cuidador |
| `sp_rep_conteos_admin` | Admin |
| `sp_rep_unidades_dosis` | Admin |