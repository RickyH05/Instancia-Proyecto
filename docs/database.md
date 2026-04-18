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
    p_acc       CHAR(1),              -- 'I'=Insert, 'U'=Update, 'D'=Desactivar
    p_id        INTEGER INOUT,        -- NULL en Insert; id del paciente en U/D
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,      -- nombre del cursor para filas de resultado
    p_nom       VARCHAR(100) DEFAULT NULL,
    p_ap        VARCHAR(100) DEFAULT NULL,  -- apellido paterno
    p_am        VARCHAR(100) DEFAULT NULL,  -- apellido materno
    p_nac       DATE         DEFAULT NULL,
    p_curp      VARCHAR(18)  DEFAULT NULL,
    p_foto      VARCHAR(255) DEFAULT NULL   -- default='default_paciente.png'
)
```

**Cursor devuelve:** fila completa del paciente afectado (`id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento, curp, activo, foto_perfil`)

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
    p_acc       CHAR(1),
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_nom       VARCHAR(100) DEFAULT NULL,
    p_ap        VARCHAR(100) DEFAULT NULL,
    p_am        VARCHAR(100) DEFAULT NULL,
    p_ced       VARCHAR(50)  DEFAULT NULL,  -- cédula profesional (UNIQUE)
    p_email     VARCHAR(150) DEFAULT NULL,  -- email (UNIQUE)
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
    p_acc       CHAR(1),
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_nom       VARCHAR(100)       DEFAULT NULL,
    p_ap        VARCHAR(100)       DEFAULT NULL,
    p_am        VARCHAR(100)       DEFAULT NULL,
    p_tipo      tipo_cuidador_enum DEFAULT NULL,  -- 'formal' | 'informal'
    p_tel       VARCHAR(20)        DEFAULT NULL,
    p_email     VARCHAR(150)       DEFAULT NULL,
    p_foto      VARCHAR(255)       DEFAULT NULL
)
```

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

**Nota:** `'D'` desactiva al cuidador en `paciente_cuidador`, no en la tabla `cuidador`.

---

## 4. CRUD — Medicamento

### `sp_gestion_medicamento`

**Firma completa:**
```sql
CALL sp_gestion_medicamento(
    p_acc       CHAR(1),
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_nombre    VARCHAR(150) DEFAULT NULL,
    p_atc       VARCHAR(30)  DEFAULT NULL,
    p_dmax      INTEGER      DEFAULT NULL,  -- dosis_max (> 0)
    p_unidad    INTEGER      DEFAULT NULL   -- FK unidad_dosis.id_unidad
)
```

**Cursor devuelve:** `id_medicamento, nombre_generico, codigo_atc, dosis_max, activo, unidad`

```python
# INSERT
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_medicamento('I', NULL, NULL, NULL, 'cur1', %s, %s, %s, %s)",
    ['Metformina', 'A10BA02', 850, 1]
)
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 5. CRUD — Diagnóstico

### `sp_gestion_diagnostico`

Solo acepta `'I'` y `'U'`. Los diagnósticos no se eliminan.

**Firma completa:**
```sql
CALL sp_gestion_diagnostico(
    p_acc       CHAR(1),
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_desc      VARCHAR(255) DEFAULT NULL
)
```

**Cursor devuelve:** `id_diagnostico, descripcion`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_gestion_diagnostico('I', NULL, NULL, NULL, 'cur1', %s)", ['Diabetes Tipo 2'])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 6. CRUD — Especialidad

### `sp_gestion_especialidad`

Solo acepta `'I'` y `'U'`.

**Firma completa:**
```sql
CALL sp_gestion_especialidad(
    p_acc       CHAR(1),
    p_id        INTEGER INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_desc      VARCHAR(255) DEFAULT NULL
)
```

**Cursor devuelve:** `id_especialidad, descripcion`

```python
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
    p_uuid      VARCHAR(50)   DEFAULT NULL,  -- UUID del beacon (UNIQUE)
    p_nom       VARCHAR(150)  DEFAULT NULL,
    p_pac       INTEGER       DEFAULT NULL,  -- FK paciente.id_paciente
    p_lat       NUMERIC(10,7) DEFAULT NULL,  -- latitud_ref (-90 a 90)
    p_lon       NUMERIC(10,7) DEFAULT NULL,  -- longitud_ref (-180 a 180)
    p_radio     NUMERIC(6,2)  DEFAULT 5.00   -- radio en metros (1 a 50)
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
    p_imei      VARCHAR(20)  DEFAULT NULL,  -- IMEI 15-17 dígitos (UNIQUE)
    p_mod       VARCHAR(100) DEFAULT NULL,
    p_cuid      INTEGER      DEFAULT NULL   -- FK cuidador.id_cuidador
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
    p_pac       INTEGER,     -- FK paciente.id_paciente
    p_med       INTEGER,     -- FK medico.id_medico
    p_emi       DATE,        -- fecha de emisión
    p_ini       DATE,        -- fecha de inicio (>= p_emi)
    p_fin       DATE         -- fecha de fin (>= p_ini)
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
    p_rec       INTEGER,  -- FK receta.id_receta (debe estar 'vigente')
    p_medic     INTEGER,  -- FK medicamento.id_medicamento
    p_dosis     INTEGER,  -- no puede exceder dosis_max del medicamento
    p_freq      INTEGER,  -- frecuencia en horas (ej. 8 = cada 8h, 24 = 1/día)
    p_tol       INTEGER,  -- tolerancia en minutos
    p_hora      TIME,     -- hora de la primera toma (ej. '08:00:00')
    p_uni       INTEGER   -- FK unidad_dosis.id_unidad
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
detalle = cur.fetchone()  # incluye agendas_generadas
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
4. Inserta en `evento_nfc` → dispara `trg_antes_evento` (clasifica resultado, detecta duplicado) y `trg_despues_evento` (genera alerta y bitácora).
5. Inserta en `evento_proximidad`.
6. Si GPS verificado y distancia > radio → genera alerta `'Proximidad Inválida'`.

**Firma completa:**
```sql
CALL sp_registrar_toma_nfc(
    p_id_ev     BIGINT INOUT,
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    p_res       VARCHAR(50) OUT,   -- 'Exitoso'|'Tardío'|'Duplicado'
    p_prox      BOOLEAN OUT,       -- TRUE si proximidad válida
    io_cursor   REFCURSOR INOUT,
    p_uid       VARCHAR(100),      -- UID de la etiqueta NFC
    p_cuid      INTEGER,           -- FK cuidador.id_cuidador
    p_lat       NUMERIC(10,7),     -- latitud actual del cuidador
    p_lon       NUMERIC(10,7),     -- longitud actual del cuidador
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
    # 3. Registrar acceso exitoso
    cur.execute(
        "INSERT INTO log_acceso (id_usr, email, rol, ip, exitoso) VALUES (%s,%s,%s,%s,TRUE)",
        [row[0], email, row[2], request.remote_addr]
    )
    conn.commit()
else:
    # 4. Registrar fallo
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

Busca todas las `agenda_toma` en `'pendiente'` cuya ventana de tolerancia ya venció,
las marca como `'omitida'` y genera alertas de tipo "Omisión de Medicamento".
Ejecutar periódicamente con cron (ej. cada hora).

**Firma completa:**
```sql
CALL sp_detectar_omisiones(
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    p_total     INTEGER OUT,      -- omisiones detectadas en esta ejecución
    io_cursor   REFCURSOR INOUT
)
```

**Cursor devuelve:** alertas de omisión generadas en la última hora (`id_alerta, timestamp_gen, paciente, medicamento, toma_programada`)

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

```python
cur.execute("BEGIN")
cur.execute(
    "CALL sp_asignar_diagnostico(%s, %s, NULL, NULL, 'cur1')",
    [id_paciente, id_diagnostico]
)
p_ok, p_msg = cur.fetchone()
conn.commit()
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

> **Cambio de cuidador principal (Escenario 4):**
> ```python
> # 1. Desactivar el cuidador anterior
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

## 15. Crear Usuario

### `sp_crear_usuario_admin`

**Firma completa:**
```sql
CALL sp_crear_usuario_admin(
    p_email         VARCHAR(150) IN,
    p_password_hash TEXT IN,          -- hash bcrypt generado en Flask
    p_rol           rol_usuario_enum, -- 'medico' | 'cuidador'
    p_id_rol        INTEGER IN,       -- id_medico o id_cuidador
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

## 16. Horario de Cuidador ← NUEVO en v7

### `sp_gestion_horario`

Gestiona los turnos semanales de un cuidador para un paciente concreto.
Usa `id_paciente_cuidador` (PK de la tabla `paciente_cuidador`), NO `id_cuidador`.

**Firma completa:**
```sql
CALL sp_gestion_horario(
    p_acc       CHAR(1),              -- 'I'=Insertar, 'D'=Eliminar, 'L'=Listar
    p_id        INTEGER INOUT,        -- NULL en I; id_cuidador_horario en D
    p_ok        INTEGER OUT,
    p_msg       VARCHAR(300) OUT,
    io_cursor   REFCURSOR INOUT,
    p_pac_cuid  INTEGER      DEFAULT NULL,  -- FK paciente_cuidador.id_paciente_cuidador
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
- `hora_fin` debe ser mayor que `hora_inicio` → `p_ok = -2` si falla.
- El vínculo `paciente_cuidador` debe existir y estar activo → `p_ok = -3` si no.
- El horario debe existir para eliminarlo → `p_ok = -4` si no.

**Ejemplos psycopg:**
```python
# Obtener id_paciente_cuidador
cur.execute("""
    SELECT id_paciente_cuidador FROM paciente_cuidador
    WHERE id_paciente = %s AND id_cuidador = %s AND activo = TRUE
""", [id_paciente, id_cuidador])
row = cur.fetchone()
id_pc = row[0]

# INSERTAR turno
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_horario('I', NULL, NULL, NULL, 'cur1', %s, %s, %s, %s)",
    [id_pc, 'lunes', '08:00:00', '14:00:00']
)
p_id, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur1")
turno = cur.fetchone()   # id_cuidador_horario, dia_semana, hora_inicio, hora_fin, cuidador, paciente
conn.commit()

# LISTAR todos los turnos de un vínculo
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_horario('L', NULL, NULL, NULL, 'cur1', %s)",
    [id_pc]
)
p_id, p_ok, p_msg = cur.fetchone()
cur.execute("FETCH ALL FROM cur1")
turnos = cur.fetchall()
conn.commit()

# ELIMINAR turno
cur.execute("BEGIN")
cur.execute(
    "CALL sp_gestion_horario('D', %s, NULL, NULL, 'cur1')",
    [id_cuidador_horario]
)
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
> Para leer datos usa `CALL sp_rep_*('cursor', ...)` + `FETCH ALL FROM cursor`.
> Las Views existen como capa interna — Flask no las llama directamente.

**Posición de `io_cursor`:** en los `sp_rep_*` va como **primer parámetro**
porque los demás son opcionales con `DEFAULT` y PostgreSQL exige que
después de un parámetro con `DEFAULT` todos los siguientes también lo tengan.

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
Agenda diaria + contador de alertas pendientes por paciente.

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
Agenda del día con UID NFC para escanear.

**Firma:** `(INOUT io_cursor, IN p_cuidador INTEGER, IN p_fecha DATE DEFAULT CURRENT_DATE)`
**Columnas:** `id_cuidador, id_agenda, fecha_hora_programada, estado_agenda, tolerancia_min, id_paciente, paciente, nombre_generico, dosis_prescrita, unidad, uid_nfc`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_agenda_dia_cuidador('cur1', %s)", [id_cuidador])
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_alertas_cuidador`
Alertas de los pacientes de un cuidador.

**Firma:** `(INOUT io_cursor, IN p_cuidador INTEGER, IN p_sol_pendientes BOOLEAN DEFAULT TRUE)`
**Columnas:** `id_cuidador, id_alerta, prioridad, tipo, estado, timestamp_gen, paciente, medicamento`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_alertas_cuidador('cur1', %s)", [id_cuidador])       # solo pendientes
cur.execute("CALL sp_rep_alertas_cuidador('cur1', %s, FALSE)", [id_cuidador]) # todas
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_alertas_medico`
Alertas de los pacientes de un médico.

**Firma:** `(INOUT io_cursor, IN p_medico INTEGER, IN p_sol_pendientes BOOLEAN DEFAULT TRUE)`
**Columnas:** `id_medico, id_alerta, prioridad, tipo, estado, timestamp_gen, paciente, medicamento, id_evento`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_alertas_medico('cur1', %s)", [id_medico])
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_badge_alertas`
Contador de alertas pendientes para el badge del menú.

**Firma:** `(INOUT io_cursor, IN p_usuario INTEGER, IN p_rol VARCHAR(10))`
**Columnas:** `total_pendientes`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_badge_alertas('cur1', %s, %s)",
            [session['user_id'], session['rol']])
cur.execute("FETCH ALL FROM cur1")
row   = cur.fetchone()
total = row[0] if row else 0
conn.commit()
```

---

### `sp_rep_pacientes_medico`
Pacientes activos con recetas de un médico.

**Firma:** `(INOUT io_cursor, IN p_medico INTEGER)`
**Columnas:** `id_medico, id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento, curp, activo, id_receta, estado_receta, fecha_inicio, fecha_fin`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_pacientes_medico('cur1', %s)", [id_medico])
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_perfil_paciente`
Perfil completo: datos, diagnósticos, cuidador principal, medicamentos activos.

**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER)`
**Columnas:** `id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento, curp, activo, diagnosticos, cuidador_princ, medicamentos`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_perfil_paciente('cur1', %s)", [id_paciente])
cur.execute("FETCH ALL FROM cur1")
row = cur.fetchone()
conn.commit()
```

---

### `sp_rep_recetas_paciente`
Recetas y medicamentos de un paciente.

**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER, IN p_estado_receta VARCHAR(20) DEFAULT NULL)`
**Columnas:** `id_paciente, id_receta, estado_receta, fecha_emision, fecha_inicio, fecha_fin, medico, id_receta_medicamento, nombre_generico, dosis_prescrita, unidad, frecuencia_horas, tolerancia_min, hora_primera_toma`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_recetas_paciente('cur1', %s, 'vigente')", [id_paciente]) # vigentes
cur.execute("CALL sp_rep_recetas_paciente('cur1', %s)", [id_paciente])            # todas
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_historial_tomas`
Historial de eventos NFC de un paciente.

**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER, IN p_dias INTEGER DEFAULT 14)`
**Columnas:** `id_paciente, id_evento, timestamp_lectura, uid_nfc, resultado, desfase_min, origen, observaciones, fecha_registro, medicamento, cuidador, distancia_metros, proximidad_valida`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_historial_tomas('cur1', %s, %s)", [id_paciente, 14])
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_adherencia_pacientes_medico`
Adherencia de los pacientes de un médico por medicamento.

**Firma:** `(INOUT io_cursor, IN p_medico INTEGER, IN p_dias INTEGER DEFAULT 14)`
**Columnas:** `id_paciente, paciente, medicamento, total, ok, tarde, omitida, pend, pct`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_adherencia_pacientes_medico('cur1', %s, 14)", [id_medico])
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_adherencia_medicos`
Adherencia global por médico (Admin).

**Firma:** `(INOUT io_cursor, IN p_dias INTEGER DEFAULT 14)`
**Columnas:** `id_medico, medico, total, ok, tarde, omitida, pct`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_adherencia_medicos('cur1', 14)")
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_adherencia_cuidadores`
Adherencia global por cuidador (Admin).

**Firma:** `(INOUT io_cursor, IN p_dias INTEGER DEFAULT 14)`
**Columnas:** `id_cuidador, cuidador, total, ok, tarde, omitida, pct`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_adherencia_cuidadores('cur1', 14)")
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_grafica_tomas`
Datos diarios para gráfica de barras de adherencia.

**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER, IN p_dias INTEGER DEFAULT 14)`
**Columnas:** `id_paciente, fecha, total, correctas, fuera_horario, no_tomadas, pendientes`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_grafica_tomas('cur1', %s, 14)", [id_paciente])
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_mapa_medico`
Datos GPS/Beacon de los pacientes de un médico.

**Firma:** `(INOUT io_cursor, IN p_medico INTEGER)`
**Columnas:** `id_medico, id_paciente, paciente, id_beacon, bec_lat, bec_lon, radio_metros, gps_lat, gps_lon, gps_ts, cuidador`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_mapa_medico('cur1', %s)", [id_medico])
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_bitacora`
Bitácora de reglas de negocio (Admin).

**Firma:** `(INOUT io_cursor, IN p_dias INTEGER DEFAULT 7, IN p_limite INTEGER DEFAULT 100)`
**Columnas:** `id_bitacora, id_evento, regla_aplicada, resultado, detalle, timestamp_eval, uid_nfc, timestamp_lectura, paciente, medicamento`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_bitacora('cur1', 7, 100)")
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_auditoria`
Historial de auditoría de cambios en tablas maestras (Admin).

**Firma:** `(INOUT io_cursor, IN p_tabla VARCHAR(80) DEFAULT NULL, IN p_limite INTEGER DEFAULT 100)`
**Columnas:** `id_audit, tabla, id_reg, accion, campo, val_antes, val_despues, usuario_db, id_usr_app, ts`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_auditoria('cur1', 'paciente', 50)")  # tabla específica
cur.execute("CALL sp_rep_auditoria('cur1')")                   # todas
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_log_acceso`
Log de intentos de login (Admin).

**Firma:** `(INOUT io_cursor, IN p_usuario INTEGER DEFAULT NULL, IN p_limite INTEGER DEFAULT 100)`
**Columnas:** `id_log, id_usr, email, rol, ip, exitoso, ts`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_log_acceso('cur1')")
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_carga_medicos`
Carga de pacientes por médico (Admin).

**Firma:** `(INOUT io_cursor)`
**Columnas:** `id_medico, medico, cedula_profesional, total_pac, pacientes`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_carga_medicos('cur1')")
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_supervision`
Supervisión médico-paciente (Admin).

**Firma:** `(INOUT io_cursor)`
**Columnas:** `id_paciente, paciente, id_medico, medico, id_receta, estado_receta, fecha_inicio, fecha_fin`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_supervision('cur1')")
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_dispositivos_iot`
GPS y Beacons con su asignación (Admin).

**Firma:** `(INOUT io_cursor)`
**Columnas:** `tipo` (`'GPS'`|`'BEACON'`), `id_disp, ident, nombre, asignado, activo`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_dispositivos_iot('cur1')")
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_tendencia_adherencia`
Tendencia con ventana móvil de 7 días (Médico/Admin).

**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER DEFAULT NULL, IN p_dias INTEGER DEFAULT 30)`
**Columnas:** `id_paciente, paciente, fecha, total_citas, cumplidas, tardias, omitidas, pct_dia, promedio_movil_7d, tendencia`
**`tendencia`:** `'INICIO'`, `'MEJORA'`, `'DECLIVE'`, `'ESTABLE'`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_tendencia_adherencia('cur1', %s, 30)", [id_paciente])
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_riesgo_omision`
Rachas de omisiones consecutivas con nivel de riesgo (Médico/Admin).

**Firma:** `(INOUT io_cursor, IN p_paciente INTEGER DEFAULT NULL, IN p_solo_activas BOOLEAN DEFAULT TRUE, IN p_min_dias INTEGER DEFAULT 2)`
**Columnas:** `id_paciente, paciente, medicamento, inicio_racha, fin_racha, dias_consecutivos, nivel_riesgo, racha_activa, dias_desde_ultima_omision`
**`nivel_riesgo`:** `'CRÍTICO'` (≥5 días), `'ALTO'` (≥3 días), `'MODERADO'` (<3 días)

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_riesgo_omision('cur1', %s)", [id_paciente])
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

### `sp_rep_ranking_mejora`
Ranking de mejora de adherencia. Ventana fija: últimos 14 días vs 14 anteriores (Admin).

**Firma:** `(INOUT io_cursor, IN p_rol VARCHAR(10) DEFAULT NULL)`
**Columnas:** `rol, id_persona, nombre, pct_anterior, pct_reciente, delta_pct, rank_mejora, dense_rank_mejora, cuartil_mejora, clasificacion`
**`clasificacion`:** `'MEJORA SIGNIFICATIVA'`, `'MEJORA LEVE'`, `'SIN CAMBIO'`, `'DECLIVE LEVE'`, `'DECLIVE SIGNIFICATIVO'`

```python
cur.execute("BEGIN")
cur.execute("CALL sp_rep_ranking_mejora('cur1')")           # ambos roles
cur.execute("CALL sp_rep_ranking_mejora('cur1', 'medico')") # solo médicos
cur.execute("FETCH ALL FROM cur1")
rows = cur.fetchall()
conn.commit()
```

---

## 19. Triggers automáticos (no llamar directamente)

| Trigger | Tabla | Momento | Qué hace |
|---------|-------|---------|----------|
| `trg_antes_evento` | `evento_nfc` | BEFORE INSERT | Calcula desfase, detecta duplicados, clasifica resultado, actualiza agenda |
| `trg_despues_evento` | `evento_nfc` | AFTER INSERT | Inserta en `alerta` y `bitacora_regla_negocio` |
| `trg_generar_agenda` | `receta_medicamento` | AFTER INSERT | Genera todas las entradas de `agenda_toma` |
| `trg_audit_*` | varias | AFTER INSERT/UPDATE | Registra cambios en `audit_cambios` |

---

## Referencia rápida — 43 SPs totales

### CRUD y Operativos (20 SPs)

| SP | Tipo | Acciones | Rol |
|----|------|----------|-----|
| `sp_gestion_paciente` | CRUD | I/U/D | Admin/Médico |
| `sp_gestion_medico` | CRUD | I/U/D | Admin |
| `sp_gestion_cuidador` | CRUD | I/U/D | Admin |
| `sp_gestion_medicamento` | CRUD | I/U/D | Admin |
| `sp_gestion_diagnostico` | CRUD | I/U | Admin |
| `sp_gestion_especialidad` | CRUD | I/U | Admin |
| `sp_gestion_beacon` | CRUD IoT | I/U/D | Admin |
| `sp_gestion_gps` | CRUD IoT | I/U/D | Admin |
| `sp_gestion_horario` | CRUD Horario | I/D/L | Admin/Médico |
| `sp_crear_receta` | Receta | — | Médico |
| `sp_agregar_receta_med` | Receta | — | Médico |
| `sp_cancelar_receta` | Receta | — | Médico |
| `sp_registrar_toma_nfc` | Operativo | — | Cuidador |
| `sp_marcar_alerta_atendida` | Alerta | — | Médico/Cuidador |
| `sp_detectar_omisiones` | Batch cron | — | Sistema |
| `sp_asignar_diagnostico` | Asignación | — | Médico |
| `sp_asignar_cuidador` | Asignación | — | Admin |
| `sp_asignar_especialidad` | Asignación | — | Admin |
| `sp_crear_usuario_admin` | Usuario | — | Admin |
| ~~`sp_login`~~ | ~~Auth~~ | — | ~~No usar~~ |

### Reportes sp_rep_* (23 SPs)

| SP | Descripción | Rol |
|----|-------------|-----|
| `sp_rep_dashboard_cuidador` | Agenda diaria + alertas_pend | Cuidador |
| `sp_rep_agenda_dia_cuidador` | Agenda con UID NFC | Cuidador |
| `sp_rep_alertas_cuidador` | Alertas del cuidador | Cuidador |
| `sp_rep_alertas_medico` | Alertas del médico | Médico |
| `sp_rep_badge_alertas` | Contador badge menú | Médico/Cuidador |
| `sp_rep_pacientes_medico` | Lista pacientes del médico | Médico |
| `sp_rep_perfil_paciente` | Perfil completo | Médico |
| `sp_rep_recetas_paciente` | Recetas y medicamentos | Médico/Cuidador |
| `sp_rep_historial_tomas` | Historial NFC | Médico |
| `sp_rep_adherencia_pacientes_medico` | Adherencia por paciente | Médico |
| `sp_rep_adherencia_medicos` | Adherencia global médicos | Admin |
| `sp_rep_adherencia_cuidadores` | Adherencia global cuidadores | Admin |
| `sp_rep_grafica_tomas` | Datos gráfica de barras | Médico |
| `sp_rep_mapa_medico` | GPS/Beacon mapa | Médico |
| `sp_rep_bitacora` | Bitácora reglas negocio | Admin |
| `sp_rep_auditoria` | Auditoría de cambios | Admin |
| `sp_rep_log_acceso` | Log de logins | Admin |
| `sp_rep_carga_medicos` | Carga por médico | Admin |
| `sp_rep_supervision` | Supervisión médico-paciente | Admin |
| `sp_rep_dispositivos_iot` | GPS y Beacons | Admin |
| `sp_rep_tendencia_adherencia` | Tendencia 7d móvil | Médico/Admin |
| `sp_rep_riesgo_omision` | Rachas de omisión | Médico/Admin |
| `sp_rep_ranking_mejora` | Ranking mejora adherencia | Admin |