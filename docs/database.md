# Base de datos `medi_nfc2` — Documentación completa para Claude Code

> **Motor:** PostgreSQL  
> **Base de datos:** `medi_nfc2`  
> **Usuario:** `proyectofinal_user` / contraseña: `444`  
> **Conexión:** `postgresql://proyectofinal_user:444@localhost:5432/medi_nfc2`

---

## Convenciones globales de los SPs

Todos los stored procedures siguen estas reglas de firma en PostgreSQL:

1. Los parámetros `OUT` e `INOUT` siempre van **antes** de los `IN` con `DEFAULT`.
2. Los parámetros de salida de estado son siempre: `p_ok INTEGER` (1=éxito, negativo=error) y `p_msg VARCHAR(300)`.
3. Los reportes son **Views** — se consultan con `SELECT` directo, sin transacción explícita.

### Patrón psycopg2 — SP normal

```python
cur.execute("CALL sp_nombre(NULL, NULL, NULL, %s, %s)", [param1, param2])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

### Patrón psycopg2 — View

```python
cur.execute("SELECT * FROM v_nombre WHERE columna_filtro = %s", [valor])
rows = cur.fetchall()
# No requiere BEGIN/COMMIT
```

### Códigos de `p_ok`

| Valor | Significado |
|-------|-------------|
| `1`   | Operación exitosa |
| `-1`  | Campos obligatorios incompletos / dato no encontrado |
| `-2`  | Validación de negocio fallida (ej. dosis excede máximo) |
| `-3`  | Falta `p_id` para UPDATE/DELETE |
| `-10` | Violación de unicidad (UNIQUE constraint) |
| `-99` | Acción no válida (solo acepta I/U/D) |
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
| `dia_semana_enum` | `'lunes'`…`'domingo'` |
| `estado_agenda_enum` | `'pendiente'`, `'cumplida'`, `'tardia'`, `'omitida'` |
| `prioridad_alerta_enum` | `'Alta'`, `'Media'`, `'Baja'` |

---
## Nombres reales de columnas (errores comunes)

Estos son nombres que se suelen equivocar — usar EXACTAMENTE así:

| Tabla | Columnas correctas |
|-------|-------------------|
| paciente, medico, cuidador | apellido_p, apellido_m (NO apellido_paterno/materno) |
| medicamento | dosis_max (NO dosis_maxima) |
| ubicacion_gps | latitud, longitud, timestamp_ubicacion (NO lat/lon/timestamp_gps) |
| alerta | id_estado (NO estado) — JOIN con estado_alerta para descripción |
| beacon | latitud_ref, longitud_ref, radio_metros |
| evento_nfc | timestamp_lectura, fecha_registro, desfase_min |
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

Crea, actualiza o desactiva un paciente.

**Firma completa:**
```sql
CALL sp_gestion_paciente(
    p_acc   CHAR(1),         -- 'I'=Insert, 'U'=Update, 'D'=Desactivar
    p_id    INTEGER INOUT,   -- NULL en Insert; id del paciente en U/D
    p_ok    INTEGER OUT,
    p_msg   VARCHAR(300) OUT,
    p_nom   VARCHAR(100) DEFAULT NULL,
    p_ap    VARCHAR(100) DEFAULT NULL,   -- apellido paterno
    p_am    VARCHAR(100) DEFAULT NULL,   -- apellido materno
    p_nac   DATE         DEFAULT NULL,
    p_curp  VARCHAR(18)  DEFAULT NULL,
    p_foto  VARCHAR(255) DEFAULT NULL    -- ruta foto, default='default_paciente.png'
)
```

**Ejemplos psycopg2:**
```python
# INSERT
cur.execute("CALL sp_gestion_paciente('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
            ['Juan', 'Pérez', 'López', '1990-05-15', 'PELJ900515HDFRZN01'])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()

# UPDATE (solo campos que cambian, el resto queda igual)
cur.execute("CALL sp_gestion_paciente('U', %s, NULL, NULL, %s, NULL, NULL, NULL, NULL, NULL)",
            [id_paciente, 'NuevoNombre'])
_, p_ok, p_msg = cur.fetchone()
conn.commit()

# DESACTIVAR (soft delete)
cur.execute("CALL sp_gestion_paciente('D', %s, NULL, NULL)", [id_paciente])
_, p_ok, p_msg = cur.fetchone()
conn.commit()
```

**Notas:**
- CURP debe tener exactamente 18 caracteres (hay CHECK en BD).
- 'D' hace `activo = FALSE`, no elimina el registro.
- En UPDATE, los campos con `NULL` no se modifican (usa `COALESCE`).

---

## 2. CRUD — Médico

### `sp_gestion_medico`

**Firma completa:**
```sql
CALL sp_gestion_medico(
    p_acc   CHAR(1),
    p_id    INTEGER INOUT,
    p_ok    INTEGER OUT,
    p_msg   VARCHAR(300) OUT,
    p_nom   VARCHAR(100) DEFAULT NULL,
    p_ap    VARCHAR(100) DEFAULT NULL,
    p_am    VARCHAR(100) DEFAULT NULL,
    p_ced   VARCHAR(50)  DEFAULT NULL,   -- cédula profesional (UNIQUE)
    p_email VARCHAR(150) DEFAULT NULL,   -- email (UNIQUE)
    p_foto  VARCHAR(255) DEFAULT NULL
)
```

**Ejemplos psycopg2:**
```python
# INSERT
cur.execute("CALL sp_gestion_medico('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
            ['Ana', 'García', 'Ruiz', 'CED12345', 'ana@hospital.com'])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()

# UPDATE email
cur.execute("CALL sp_gestion_medico('U', %s, NULL, NULL, NULL, NULL, NULL, NULL, %s, NULL)",
            [id_medico, 'nuevo@email.com'])
_, p_ok, p_msg = cur.fetchone()
conn.commit()

# DESACTIVAR
cur.execute("CALL sp_gestion_medico('D', %s, NULL, NULL)", [id_medico])
_, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 3. CRUD — Cuidador

### `sp_gestion_cuidador`

**Firma completa:**
```sql
CALL sp_gestion_cuidador(
    p_acc   CHAR(1),
    p_id    INTEGER INOUT,
    p_ok    INTEGER OUT,
    p_msg   VARCHAR(300) OUT,
    p_nom   VARCHAR(100)       DEFAULT NULL,
    p_ap    VARCHAR(100)       DEFAULT NULL,
    p_am    VARCHAR(100)       DEFAULT NULL,
    p_tipo  tipo_cuidador_enum DEFAULT NULL,  -- 'formal' | 'informal'
    p_tel   VARCHAR(20)        DEFAULT NULL,
    p_email VARCHAR(150)       DEFAULT NULL,
    p_foto  VARCHAR(255)       DEFAULT NULL
)
```

**Ejemplos psycopg2:**
```python
# INSERT
cur.execute("CALL sp_gestion_cuidador('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, NULL)",
            ['María', 'López', 'Soto', 'formal', '8112345678', 'maria@email.com'])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()

# UPDATE teléfono
cur.execute("CALL sp_gestion_cuidador('U', %s, NULL, NULL, NULL, NULL, NULL, NULL, %s, NULL, NULL)",
            [id_cuidador, '8119876543'])
_, p_ok, p_msg = cur.fetchone()
conn.commit()
```

**Nota:** La acción 'D' desactiva al cuidador en `paciente_cuidador` (no en la tabla `cuidador` directamente).

---

## 4. CRUD — Medicamento

### `sp_gestion_medicamento`

**Firma completa:**
```sql
CALL sp_gestion_medicamento(
    p_acc    CHAR(1),
    p_id     INTEGER INOUT,
    p_ok     INTEGER OUT,
    p_msg    VARCHAR(300) OUT,
    p_nombre VARCHAR(150) DEFAULT NULL,   -- nombre genérico
    p_atc    VARCHAR(30)  DEFAULT NULL,   -- código ATC
    p_dmax   INTEGER      DEFAULT NULL,   -- dosis máxima (debe ser > 0)
    p_unidad INTEGER      DEFAULT NULL    -- FK a unidad_dosis.id_unidad
)
```

**Ejemplo psycopg2:**
```python
# INSERT
cur.execute("CALL sp_gestion_medicamento('I', NULL, NULL, NULL, %s, %s, %s, %s)",
            ['Metformina', 'A10BA02', 2000, 1])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 5. CRUD — Diagnóstico

### `sp_gestion_diagnostico`

Solo acepta 'I' (Insert) y 'U' (Update). Los diagnósticos no se eliminan.

**Firma completa:**
```sql
CALL sp_gestion_diagnostico(
    p_acc  CHAR(1),
    p_id   INTEGER INOUT,
    p_ok   INTEGER OUT,
    p_msg  VARCHAR(300) OUT,
    p_desc VARCHAR(255) DEFAULT NULL
)
```

**Ejemplo psycopg2:**
```python
cur.execute("CALL sp_gestion_diagnostico('I', NULL, NULL, NULL, %s)", ['Diabetes Tipo 2'])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 6. CRUD — Especialidad

### `sp_gestion_especialidad`

Solo acepta 'I' y 'U'.

**Firma completa:**
```sql
CALL sp_gestion_especialidad(
    p_acc  CHAR(1),
    p_id   INTEGER INOUT,
    p_ok   INTEGER OUT,
    p_msg  VARCHAR(300) OUT,
    p_desc VARCHAR(255) DEFAULT NULL
)
```

**Ejemplo psycopg2:**
```python
cur.execute("CALL sp_gestion_especialidad('I', NULL, NULL, NULL, %s)", ['Cardiología'])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 7. CRUD IoT — Beacon

### `sp_gestion_beacon`

Gestiona los beacons BLE asociados a pacientes.

**Firma completa:**
```sql
CALL sp_gestion_beacon(
    p_acc   CHAR(1),
    p_id    BIGINT INOUT,
    p_ok    INTEGER OUT,
    p_msg   VARCHAR(300) OUT,
    p_uuid  VARCHAR(50)   DEFAULT NULL,   -- UUID del beacon (UNIQUE)
    p_nom   VARCHAR(150)  DEFAULT NULL,
    p_pac   INTEGER       DEFAULT NULL,   -- FK paciente.id_paciente
    p_lat   NUMERIC(10,7) DEFAULT NULL,   -- latitud referencia (-90 a 90)
    p_lon   NUMERIC(10,7) DEFAULT NULL,   -- longitud referencia (-180 a 180)
    p_radio NUMERIC(6,2)  DEFAULT 5.00    -- radio en metros (1 a 50)
)
```

**Ejemplos psycopg2:**
```python
# INSERT
cur.execute("CALL sp_gestion_beacon('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s)",
            ['uuid-abc-123', 'Beacon Habitación', id_paciente, 25.6866, -100.3161, 5.0])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()

# DESACTIVAR
cur.execute("CALL sp_gestion_beacon('D', %s, NULL, NULL)", [id_beacon])
_, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 8. CRUD IoT — GPS

### `sp_gestion_gps`

Gestiona los dispositivos GPS asignados a cuidadores.  
**Un cuidador solo puede tener un GPS activo** (UNIQUE en `id_cuidador`).

**Firma completa:**
```sql
CALL sp_gestion_gps(
    p_acc  CHAR(1),
    p_id   BIGINT INOUT,
    p_ok   INTEGER OUT,
    p_msg  VARCHAR(300) OUT,
    p_imei VARCHAR(20)  DEFAULT NULL,   -- IMEI 15-17 dígitos (UNIQUE)
    p_mod  VARCHAR(100) DEFAULT NULL,   -- modelo del dispositivo
    p_cuid INTEGER      DEFAULT NULL    -- FK cuidador.id_cuidador
)
```

**Ejemplo psycopg2:**
```python
# INSERT — asigna GPS a cuidador
cur.execute("CALL sp_gestion_gps('I', NULL, NULL, NULL, %s, %s, %s)",
            ['123456789012345', 'GPS Tracker V2', id_cuidador])
p_id, p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 9. Recetas

### `sp_crear_receta`

Crea una receta médica. El trigger `trg_generar_agenda` se activa automáticamente al agregar medicamentos (no al crear la receta).

**Firma completa:**
```sql
CALL sp_crear_receta(
    p_id  INTEGER INOUT,
    p_ok  INTEGER OUT,
    p_msg VARCHAR(300) OUT,
    p_pac INTEGER,          -- FK paciente.id_paciente
    p_med INTEGER,          -- FK medico.id_medico
    p_emi DATE,             -- fecha de emisión
    p_ini DATE,             -- fecha de inicio (>= p_emi)
    p_fin DATE              -- fecha de fin (>= p_ini)
)
```

**Ejemplo psycopg2:**
```python
cur.execute("CALL sp_crear_receta(NULL, NULL, NULL, %s, %s, %s, %s, %s)",
            [id_paciente, id_medico, '2026-04-15', '2026-04-15', '2026-05-15'])
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
    p_id_rm INTEGER INOUT,
    p_ok    INTEGER OUT,
    p_msg   VARCHAR(300) OUT,
    p_rec   INTEGER,    -- FK receta.id_receta (debe estar 'vigente')
    p_medic INTEGER,    -- FK medicamento.id_medicamento
    p_dosis INTEGER,    -- dosis prescrita (no puede exceder dosis_max del medicamento)
    p_freq  INTEGER,    -- frecuencia en horas (ej. 8 = cada 8h)
    p_tol   INTEGER,    -- tolerancia en minutos (ej. 30)
    p_hora  TIME,       -- hora de la primera toma (ej. '08:00:00')
    p_uni   INTEGER     -- FK unidad_dosis.id_unidad
)
```

**Ejemplo psycopg2:**
```python
cur.execute("CALL sp_agregar_receta_med(NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)",
            [id_receta, id_medicamento, 500, 8, 30, '08:00:00', 1])
p_id_rm, p_ok, p_msg = cur.fetchone()
conn.commit()
```

**Notas:**
- Valida que `p_dosis <= dosis_max` del medicamento.
- Valida que la receta esté en estado `'vigente'`.
- La agenda generada calcula `floor(24 / frecuencia_horas)` tomas por día entre `fecha_inicio` y `fecha_fin`.

---

### `sp_cancelar_receta`

Cancela una receta vigente, marcando sus agendas pendientes como `'omitida'` y sus etiquetas NFC como `'inactivo'`.

**Firma completa:**
```sql
CALL sp_cancelar_receta(
    p_rec INTEGER IN,
    p_ok  INTEGER OUT,
    p_msg VARCHAR(300) OUT
)
```

**Ejemplo psycopg2:**
```python
cur.execute("CALL sp_cancelar_receta(%s, NULL, NULL)", [id_receta])
p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 10. Registro de Toma NFC

### `sp_registrar_toma_nfc`

SP principal del flujo operativo. Registra una toma de medicamento escaneada por NFC.

**Internamente:**
1. Valida la etiqueta NFC.
2. Registra ubicación GPS del cuidador.
3. Calcula distancia al beacon del paciente (Haversine).
4. Inserta en `evento_nfc` → **dispara triggers** `trg_antes_evento` y `trg_despues_evento` que calculan desfase, clasifican el resultado y generan alertas automáticamente.
5. Inserta en `evento_proximidad`.
6. Si la proximidad es inválida, genera alerta de tipo "Proximidad Inválida".

**Firma completa:**
```sql
CALL sp_registrar_toma_nfc(
    p_id_ev BIGINT INOUT,
    p_ok    INTEGER OUT,
    p_msg   VARCHAR(300) OUT,
    p_res   VARCHAR(50) OUT,    -- resultado final: 'Exitoso'|'Tardío'|'Duplicado'
    p_prox  BOOLEAN OUT,        -- TRUE si la proximidad es válida
    p_uid   VARCHAR(100),       -- UID de la etiqueta NFC
    p_cuid  INTEGER,            -- FK cuidador.id_cuidador
    p_lat   NUMERIC(10,7),      -- latitud actual del cuidador
    p_lon   NUMERIC(10,7),      -- longitud actual del cuidador
    p_prec  NUMERIC(6,2)  DEFAULT NULL,  -- precisión GPS en metros (opcional)
    p_obs   VARCHAR(255)  DEFAULT NULL   -- observaciones (opcional)
)
```

**Ejemplo psycopg2:**
```python
cur.execute("""
    CALL sp_registrar_toma_nfc(NULL, NULL, NULL, NULL, NULL, %s, %s, %s, %s, %s, %s)
""", [uid_nfc, id_cuidador, 25.6866, -100.3161, 5.0, 'Toma registrada correctamente'])
p_id_ev, p_ok, p_msg, p_res, p_prox = cur.fetchone()
conn.commit()

# Evaluar resultado
if p_ok == 1:
    print(f"Evento {p_id_ev}: {p_res}, Proximidad: {'válida' if p_prox else 'inválida'}")
```

**Resultados posibles de `p_res`:**
| Valor | Significado |
|-------|-------------|
| `'Exitoso'` | Toma dentro de ventana de tolerancia |
| `'Tardío'` | Toma fuera de tolerancia pero registrada |
| `'Duplicado'` | Ya existe un evento exitoso/tardío para esa agenda |

---

## 11. Alertas

### `sp_marcar_alerta_atendida`

Marca una alerta como atendida. Opcionalmente registra una observación en la bitácora.

**Firma completa:**
```sql
CALL sp_marcar_alerta_atendida(
    p_id_al BIGINT IN,
    p_ok    INTEGER OUT,
    p_msg   VARCHAR(300) OUT,
    p_obs   VARCHAR(255) DEFAULT NULL   -- observación para bitácora (opcional)
)
```

**Ejemplo psycopg2:**
```python
cur.execute("CALL sp_marcar_alerta_atendida(%s, NULL, NULL, %s)",
            [id_alerta, 'Cuidador notificado vía teléfono'])
p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 12. Login

**NOTA:** `sp_login` existe en la BD pero NO se usa desde Flask. 
La verificación bcrypt tiene que pasar por Python, no por el SP.

Flujo correcto de login:
1. SELECT password_hash FROM usuario WHERE email = %s AND activo = TRUE
2. bcrypt.checkpw(password.encode(), stored_hash.encode())
3. Si OK: INSERT en log_acceso con exitoso=TRUE
4. Si falla: INSERT en log_acceso con exitoso=FALSE
5. Guardar en session: user_id, rol, id_rol, nombre

El nombre se obtiene con JOIN a medico o cuidador según rol_usuario.

Admin especial: credenciales en variables de entorno 
(ADMIN_EMAIL, ADMIN_PASSWORD_HASH). No vive en la tabla usuario.

## 13. Omisiones (Proceso Batch)

### `sp_detectar_omisiones`

Proceso batch para ejecutar periódicamente (ej. cron cada hora).  
Busca todas las `agenda_toma` en estado `'pendiente'` cuya ventana de tolerancia ya venció, las marca como `'omitida'` y genera alertas de tipo "Omisión de Medicamento".

**Firma completa:**
```sql
CALL sp_detectar_omisiones(
    p_ok    INTEGER OUT,
    p_msg   VARCHAR(300) OUT,
    p_total INTEGER OUT    -- número de omisiones detectadas en esta ejecución
)
```

**Ejemplo psycopg2:**
```python
cur.execute("CALL sp_detectar_omisiones(NULL, NULL, NULL)")
p_ok, p_msg, p_total = cur.fetchone()
conn.commit()
print(f"Omisiones detectadas: {p_total}")
```

---

## 14. Asignaciones

### `sp_asignar_diagnostico`

Asigna un diagnóstico a un paciente. Si ya existía inactivo, lo reactiva.

**Firma completa:**
```sql
CALL sp_asignar_diagnostico(
    p_pac  INTEGER IN,
    p_diag INTEGER IN,
    p_ok   INTEGER OUT,
    p_msg  VARCHAR(300) OUT
)
```

```python
cur.execute("CALL sp_asignar_diagnostico(%s, %s, NULL, NULL)", [id_paciente, id_diagnostico])
p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

### `sp_asignar_cuidador`

Asigna un cuidador a un paciente. Solo puede haber **un cuidador principal activo** por paciente (índice único parcial en BD).

**Firma completa:**
```sql
CALL sp_asignar_cuidador(
    p_pac   INTEGER IN,
    p_cuid  INTEGER IN,
    p_ok    INTEGER OUT,
    p_msg   VARCHAR(300) OUT,
    p_princ BOOLEAN DEFAULT FALSE   -- TRUE si es el cuidador principal
)
```

```python
cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, %s)",
            [id_paciente, id_cuidador, True])
p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

### `sp_asignar_especialidad`

Asigna una especialidad a un médico. Ignora si ya está asignada (ON CONFLICT DO NOTHING).

**Firma completa:**
```sql
CALL sp_asignar_especialidad(
    p_med INTEGER IN,
    p_esp INTEGER IN,
    p_ok  INTEGER OUT,
    p_msg VARCHAR(300) OUT
)
```

```python
cur.execute("CALL sp_asignar_especialidad(%s, %s, NULL, NULL)", [id_medico, id_especialidad])
p_ok, p_msg = cur.fetchone()
conn.commit()
```

---

## 15. Crear Usuario

### `sp_crear_usuario_admin`

Crea un usuario vinculado a un médico o cuidador ya existente.
El hash de contraseña se genera en Flask con bcrypt antes de llamar al SP.

**Firma completa:**
```sql
CALL sp_crear_usuario_admin(
    p_email         VARCHAR(150) IN,
    p_password_hash TEXT IN,          -- hash bcrypt generado en Flask
    p_rol           rol_usuario_enum, -- 'medico' | 'cuidador'
    p_id_rol        INTEGER IN,       -- id_medico o id_cuidador según p_rol
    p_ok            INTEGER OUT,
    p_msg           VARCHAR(300) OUT
)
```

**Ejemplo psycopg2:**
```python
import bcrypt

password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

cur.execute("CALL sp_crear_usuario_admin(%s, %s, %s, %s, NULL, NULL)",
            [email, password_hash, rol, id_rol])
p_ok, p_msg = cur.fetchone()
conn.commit()
```

**Flujo completo — crear médico + usuario:**
```python
# 1. Crear el médico primero
cur.execute("CALL sp_gestion_medico('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
            ['Ana', 'García', 'Ruiz', 'CED12345', 'ana@hospital.com'])
id_medico, p_ok, p_msg = cur.fetchone()

# 2. Crear el usuario vinculado
password_hash = bcrypt.hashpw('password123'.encode(), bcrypt.gensalt()).decode()
cur.execute("CALL sp_crear_usuario_admin(%s, %s, %s, %s, NULL, NULL)",
            ['ana@hospital.com', password_hash, 'medico', id_medico])
p_ok, p_msg = cur.fetchone()
conn.commit()
```

**Notas:**
- Devuelve `p_ok = -10` si el email ya existe.
- `p_rol = 'medico'` → vincula `id_medico`, deja `id_cuidador = NULL`.
- `p_rol = 'cuidador'` → vincula `id_cuidador`, deja `id_medico = NULL`.
- Usuario se crea con `activo = TRUE` por defecto.

---

## 15b. Badge de alertas — Views (no SP)

El contador para el badge del menú **no es un SP**, usa dos Views según el rol:

```python
if session['rol'] == 'medico':
    cur.execute("SELECT total_pendientes FROM v_alertas_pendientes_medico WHERE id_usuario = %s",
                [session['user_id']])
else:
    cur.execute("SELECT total_pendientes FROM v_alertas_pendientes_cuidador WHERE id_usuario = %s",
                [session['user_id']])

row = cur.fetchone()
total = row[0] if row else 0
```
## 16. Reportes — Views

> Todos los reportes son **Views** de PostgreSQL. Se consultan con `SELECT` directo sin necesidad de `BEGIN`/`COMMIT`.  
> Los filtros se aplican en el `WHERE` desde Flask.

---

### `v_adherencia_medico`

Adherencia global agrupada por **médico** (Admin).

**Columnas:** `id_medico, medico, fecha_hora_programada, estado_agenda, total, ok, tarde, omitida, pct`

```python
cur.execute("""
    SELECT DISTINCT id_medico, medico, total, ok, tarde, omitida, pct
    FROM v_adherencia_medico
    WHERE fecha_hora_programada >= NOW() - INTERVAL '%s days'
    ORDER BY pct DESC NULLS LAST
""", [dias])
rows = cur.fetchall()
```

---

### `v_adherencia_cuidador`

Adherencia global agrupada por **cuidador** (Admin).

**Columnas:** `id_cuidador, cuidador, fecha_hora_programada, estado_agenda, total, ok, tarde, omitida, pct`

```python
cur.execute("""
    SELECT DISTINCT id_cuidador, cuidador, total, ok, tarde, omitida, pct
    FROM v_adherencia_cuidador
    WHERE fecha_hora_programada >= NOW() - INTERVAL '%s days'
    ORDER BY pct DESC NULLS LAST
""", [dias])
rows = cur.fetchall()
```

---

### `v_adherencia_paciente_por_medico`

Adherencia de los **pacientes de un médico**, desglosada por medicamento (Médico).

**Columnas:** `id_medico, id_paciente, paciente, medicamento, fecha_hora_programada, estado_agenda, total, ok, tarde, omitida, pend, pct`

```python
cur.execute("""
    SELECT DISTINCT id_paciente, paciente, medicamento, total, ok, tarde, omitida, pend, pct
    FROM v_adherencia_paciente_por_medico
    WHERE id_medico = %s
      AND fecha_hora_programada >= NOW() - INTERVAL '%s days'
    ORDER BY paciente, medicamento
""", [id_medico, dias])
rows = cur.fetchall()
```

---

### `v_bitacora_regla_negocio`

Bitácora de reglas de negocio: qué clasificó cada evento NFC (Admin).

**Columnas:** `id_bitacora, id_evento, regla_aplicada, resultado, detalle, timestamp_eval, uid_nfc, timestamp_lectura, paciente, medicamento`

```python
cur.execute("""
    SELECT * FROM v_bitacora_regla_negocio
    WHERE timestamp_eval BETWEEN %s AND %s
    ORDER BY timestamp_eval DESC LIMIT %s
""", [desde, hasta, limite])
rows = cur.fetchall()
```

---

### `v_audit_cambios`

Historial de auditoría de cambios en tablas maestras (Admin).

**Columnas:** `id_audit, tabla, id_reg, accion, campo, val_antes, val_despues, usuario_db, id_usr_app, ts`

```python
# Filtrar por tabla específica
cur.execute("SELECT * FROM v_audit_cambios WHERE tabla = %s ORDER BY ts DESC LIMIT %s",
            [nombre_tabla, limite])
# O todas las tablas
cur.execute("SELECT * FROM v_audit_cambios ORDER BY ts DESC LIMIT %s", [limite])
rows = cur.fetchall()
```

---

### `v_log_acceso`

Log de intentos de login (Admin).

**Columnas:** `id_log, id_usr, email, rol, ip, exitoso, ts`

```python
# Por usuario específico
cur.execute("SELECT * FROM v_log_acceso WHERE id_usr = %s ORDER BY ts DESC LIMIT %s",
            [id_usuario, limite])
# Todos
cur.execute("SELECT * FROM v_log_acceso ORDER BY ts DESC LIMIT %s", [limite])
rows = cur.fetchall()
```

---

### `v_dashboard_cuidador`

Dashboard del día para un cuidador: todas las tomas programadas de sus pacientes.

**Columnas:** `id_cuidador, id_paciente, paciente, medicamento, fecha_hora_programada, tolerancia_min, estado_agenda, dosis_prescrita, unidad, alertas_pend`

```python
cur.execute("""
    SELECT * FROM v_dashboard_cuidador
    WHERE id_cuidador = %s
      AND fecha_hora_programada::DATE = %s
    ORDER BY fecha_hora_programada
""", [id_cuidador, fecha])
rows = cur.fetchall()
```

---

### `v_pacientes_medico`

Pacientes activos con recetas de un médico (Médico).

**Columnas:** `id_medico, id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento, curp, activo, id_receta, estado_receta, fecha_inicio, fecha_fin`

```python
cur.execute("""
    SELECT * FROM v_pacientes_medico
    WHERE id_medico = %s
    ORDER BY apellido_p, nombre
""", [id_medico])
rows = cur.fetchall()
```

---

### `v_alertas_medico`

Alertas de los pacientes de un médico (Médico).

**Columnas:** `id_medico, id_alerta, prioridad, tipo, estado, timestamp_gen, paciente, medicamento, id_evento`

```python
# Solo pendientes
cur.execute("""
    SELECT * FROM v_alertas_medico
    WHERE id_medico = %s AND UPPER(estado) = 'PENDIENTE'
    ORDER BY timestamp_gen DESC
""", [id_medico])
# Todas
cur.execute("SELECT * FROM v_alertas_medico WHERE id_medico = %s ORDER BY timestamp_gen DESC",
            [id_medico])
rows = cur.fetchall()
```

---

### `v_alertas_cuidador`

Alertas de los pacientes de un cuidador (Cuidador).

**Columnas:** `id_cuidador, id_alerta, prioridad, tipo, estado, timestamp_gen, paciente, medicamento`

```python
cur.execute("""
    SELECT * FROM v_alertas_cuidador
    WHERE id_cuidador = %s AND UPPER(estado) = 'PENDIENTE'
    ORDER BY timestamp_gen DESC
""", [id_cuidador])
rows = cur.fetchall()
```

---

### `v_recetas_paciente`

Recetas y medicamentos de un paciente con detalle completo.

**Columnas:** `id_paciente, id_receta, estado_receta, fecha_emision, fecha_inicio, fecha_fin, medico, id_receta_medicamento, nombre_generico, dosis_prescrita, unidad, frecuencia_horas, tolerancia_min, hora_primera_toma`

```python
# Solo vigentes
cur.execute("""
    SELECT * FROM v_recetas_paciente
    WHERE id_paciente = %s AND estado_receta = 'vigente'
    ORDER BY fecha_emision DESC, nombre_generico
""", [id_paciente])
# Todas
cur.execute("SELECT * FROM v_recetas_paciente WHERE id_paciente = %s ORDER BY fecha_emision DESC",
            [id_paciente])
rows = cur.fetchall()
```

---

### `v_historial_tomas`

Historial de eventos NFC de un paciente (Médico).

**Columnas:** `id_paciente, id_evento, timestamp_lectura, uid_nfc, resultado, desfase_min, origen, observaciones, fecha_registro, medicamento, cuidador, distancia_metros, proximidad_valida`

```python
cur.execute("""
    SELECT * FROM v_historial_tomas
    WHERE id_paciente = %s
      AND fecha_registro >= NOW() - INTERVAL '%s days'
    ORDER BY timestamp_lectura DESC
""", [id_paciente, dias])
rows = cur.fetchall()
```

---

### `v_agenda_dia_cuidador`

Agenda detallada del día para un cuidador, con UID de etiqueta NFC (Cuidador).

**Columnas:** `id_cuidador, id_agenda, fecha_hora_programada, estado_agenda, tolerancia_min, id_paciente, paciente, nombre_generico, dosis_prescrita, unidad, uid_nfc`

```python
cur.execute("""
    SELECT * FROM v_agenda_dia_cuidador
    WHERE id_cuidador = %s
      AND fecha_hora_programada::DATE = %s
    ORDER BY fecha_hora_programada
""", [id_cuidador, fecha])
rows = cur.fetchall()
```

---

### `v_carga_medicos`

Carga de pacientes por médico para panel de administración (Admin).

**Columnas:** `id_medico, medico, cedula_profesional, total_pac, pacientes`  
(`pacientes` es un string concatenado con los nombres)

```python
cur.execute("SELECT * FROM v_carga_medicos ORDER BY total_pac DESC")
rows = cur.fetchall()
```

---

### `v_supervision`

Supervisión médico ↔ paciente (Admin).

**Columnas:** `id_paciente, paciente, id_medico, medico, id_receta, estado_receta, fecha_inicio, fecha_fin`

```python
cur.execute("SELECT * FROM v_supervision ORDER BY paciente, medico")
rows = cur.fetchall()
```

---

### `v_dispositivos_iot`

Todos los dispositivos IoT (GPS y Beacons) con su asignación (Admin).

**Columnas:** `tipo` (`'GPS'`|`'BEACON'`), `id_disp, ident, nombre, asignado, activo`

```python
cur.execute("SELECT * FROM v_dispositivos_iot ORDER BY tipo, activo DESC")
rows = cur.fetchall()
```

---

### `v_perfil_paciente`

Perfil completo de un paciente: datos, diagnósticos, cuidador principal y medicamentos activos (Médico).

**Columnas:** `id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento, curp, activo, diagnosticos, cuidador_princ, medicamentos`

```python
cur.execute("SELECT * FROM v_perfil_paciente WHERE id_paciente = %s", [id_paciente])
row = cur.fetchone()
```

---

### `v_grafica_tomas`

Datos agrupados por día para gráfica de barras de adherencia (Médico).

**Columnas:** `id_paciente, fecha, total, correctas, fuera_horario, no_tomadas, pendientes`

```python
cur.execute("""
    SELECT * FROM v_grafica_tomas
    WHERE id_paciente = %s AND fecha >= CURRENT_DATE - %s
    ORDER BY fecha
""", [id_paciente, dias])
rows = cur.fetchall()
```

---

### `v_mapa_medico`

Datos de mapa GPS/Beacons de los pacientes de un médico (Médico).

**Columnas:** `id_medico, id_paciente, paciente, id_beacon, bec_lat, bec_lon, radio_metros, gps_lat, gps_lon, gps_ts, cuidador`

```python
cur.execute("SELECT * FROM v_mapa_medico WHERE id_medico = %s", [id_medico])
rows = cur.fetchall()
```

---

### `v_alertas_pendientes_medico`

Contador de alertas pendientes para badge del menú — rol médico.

**Columnas:** `id_usuario, total_pendientes`

```python
cur.execute("SELECT total_pendientes FROM v_alertas_pendientes_medico WHERE id_usuario = %s",
            [id_usuario])
row = cur.fetchone()
total = row[0] if row else 0
```

---

### `v_alertas_pendientes_cuidador`

Contador de alertas pendientes para badge del menú — rol cuidador.

**Columnas:** `id_usuario, total_pendientes`

```python
cur.execute("SELECT total_pendientes FROM v_alertas_pendientes_cuidador WHERE id_usuario = %s",
            [id_usuario])
row = cur.fetchone()
total = row[0] if row else 0
```

---

## 17. Analítica Avanzada — Views

---

### `v_tendencia_adherencia_movil`

Tendencia de adherencia con **ventana móvil de 7 días** y clasificación por día (Médico/Admin).

**Columnas:** `id_paciente, paciente, fecha, total_citas, cumplidas, tardias, omitidas, pct_dia, promedio_movil_7d, tendencia`

**Valores de `tendencia`:** `'INICIO'`, `'MEJORA'`, `'DECLIVE'`, `'ESTABLE'`

```python
# Todos los pacientes, últimos 30 días
cur.execute("""
    SELECT * FROM v_tendencia_adherencia_movil
    WHERE fecha >= CURRENT_DATE - 30
    ORDER BY id_paciente, fecha
""")
# Paciente específico
cur.execute("""
    SELECT * FROM v_tendencia_adherencia_movil
    WHERE id_paciente = %s AND fecha >= CURRENT_DATE - %s
    ORDER BY fecha
""", [id_paciente, dias])
rows = cur.fetchall()
```

---

### `v_riesgo_omision_consecutiva`

Rachas de omisiones consecutivas con nivel de riesgo (Médico/Admin).

**Columnas:** `id_paciente, paciente, medicamento, inicio_racha, fin_racha, dias_consecutivos, nivel_riesgo, racha_activa, dias_desde_ultima_omision`

**Niveles de riesgo:** `'CRÍTICO'` (≥5 días), `'ALTO'` (≥3 días), `'MODERADO'` (<3 días)

```python
# Solo rachas activas con mínimo 2 días consecutivos
cur.execute("""
    SELECT * FROM v_riesgo_omision_consecutiva
    WHERE dias_consecutivos >= 2 AND racha_activa = TRUE
    ORDER BY dias_consecutivos DESC
""")
# Paciente específico, todas las rachas
cur.execute("""
    SELECT * FROM v_riesgo_omision_consecutiva
    WHERE id_paciente = %s
    ORDER BY dias_consecutivos DESC
""", [id_paciente])
rows = cur.fetchall()
```

---

### `v_ranking_mejora_adherencia`

Ranking de médicos y cuidadores por mejora de adherencia (ventana fija: últimos 14 días vs 14 anteriores) (Admin).

**Columnas:** `rol, id_persona, nombre, pct_anterior, pct_reciente, delta_pct, rank_mejora, dense_rank_mejora, cuartil_mejora, clasificacion`

**Clasificaciones:** `'MEJORA SIGNIFICATIVA'`, `'MEJORA LEVE'`, `'SIN CAMBIO'`, `'DECLIVE LEVE'`, `'DECLIVE SIGNIFICATIVO'`

```python
# Ambos roles
cur.execute("SELECT * FROM v_ranking_mejora_adherencia ORDER BY rol, rank_mejora")
# Solo médicos
cur.execute("""
    SELECT * FROM v_ranking_mejora_adherencia
    WHERE rol = 'medico'
    ORDER BY rank_mejora
""")
rows = cur.fetchall()
```

> **Nota:** La ventana de comparación está fija en 14 días recientes vs 14 anteriores. Si necesitas ventanas dinámicas, consulta directamente las tablas `agenda_toma` con rangos de fecha desde Flask.

---

## 18. Triggers automáticos (no llamar directamente)

Estos triggers se ejecutan automáticamente — Flask **no los llama**, solo invoca los SPs anteriores:

| Trigger | Tabla | Momento | Función | Qué hace |
|---------|-------|---------|---------|---------|
| `trg_antes_evento` | `evento_nfc` | BEFORE INSERT | `fn_calcular_desfase_evento` | Calcula desfase, detecta duplicados, clasifica resultado, actualiza agenda |
| `trg_despues_evento` | `evento_nfc` | AFTER INSERT | `fn_registrar_alertas_y_bitacora` | Inserta en `alerta` y `bitacora_regla_negocio` |
| `trg_generar_agenda` | `receta_medicamento` | AFTER INSERT | `fn_generar_agenda` | Genera todas las entradas de `agenda_toma` |
| `trg_audit_paciente` | `paciente` | AFTER INSERT/UPDATE | `fn_audit_maestro` | Registra cambios en `audit_cambios` |
| `trg_audit_medico` | `medico` | AFTER INSERT/UPDATE | `fn_audit_maestro` | Registra cambios en `audit_cambios` |
| `trg_audit_cuidador` | `cuidador` | AFTER INSERT/UPDATE | `fn_audit_maestro` | Registra cambios en `audit_cambios` |
| `trg_audit_usuario` | `usuario` | AFTER INSERT/UPDATE | `fn_audit_maestro` | Registra cambios en `audit_cambios` |

---

## Referencia rápida

### Stored Procedures

| SP | Tipo | Rol sugerido |
|----|------|--------------|
| `sp_gestion_paciente` | CRUD | Admin/Médico |
| `sp_gestion_medico` | CRUD | Admin |
| `sp_gestion_cuidador` | CRUD | Admin |
| `sp_gestion_medicamento` | CRUD | Admin |
| `sp_gestion_diagnostico` | CRUD | Admin |
| `sp_gestion_especialidad` | CRUD | Admin |
| `sp_gestion_beacon` | CRUD IoT | Admin |
| `sp_gestion_gps` | CRUD IoT | Admin |
| `sp_crear_receta` | Receta | Médico |
| `sp_agregar_receta_med` | Receta | Médico |
| `sp_cancelar_receta` | Receta | Médico |
| `sp_registrar_toma_nfc` | Operativo | Cuidador |
| `sp_marcar_alerta_atendida` | Alerta | Médico/Cuidador |
| `sp_login` | Auth | Todos |
| `sp_detectar_omisiones` | Batch/Cron | Sistema |
| `sp_asignar_diagnostico` | Asignación | Médico |
| `sp_asignar_cuidador` | Asignación | Admin |
| `sp_asignar_especialidad` | Asignación | Admin |
| `sp_crear_usuario_admin` | Crear usuario | Admin |

### Views (Reportes y Analítica)

| View | Tipo | Rol sugerido | Filtros principales |
|------|------|--------------|---------------------|
| `v_adherencia_medico` | Reporte | Admin | `fecha_hora_programada` |
| `v_adherencia_cuidador` | Reporte | Admin | `fecha_hora_programada` |
| `v_adherencia_paciente_por_medico` | Reporte | Médico | `id_medico`, `fecha_hora_programada` |
| `v_bitacora_regla_negocio` | Reporte | Admin | `timestamp_eval` |
| `v_audit_cambios` | Reporte | Admin | `tabla` |
| `v_log_acceso` | Reporte | Admin | `id_usr` |
| `v_dashboard_cuidador` | Reporte | Cuidador | `id_cuidador`, `fecha_hora_programada::DATE` |
| `v_pacientes_medico` | Reporte | Médico | `id_medico` |
| `v_alertas_medico` | Reporte | Médico | `id_medico`, `estado` |
| `v_alertas_cuidador` | Reporte | Cuidador | `id_cuidador`, `estado` |
| `v_recetas_paciente` | Reporte | Médico/Cuidador | `id_paciente`, `estado_receta` |
| `v_historial_tomas` | Reporte | Médico | `id_paciente`, `fecha_registro` |
| `v_agenda_dia_cuidador` | Reporte | Cuidador | `id_cuidador`, `fecha_hora_programada::DATE` |
| `v_alertas_pendientes_medico` | Badge | Médico | `id_usuario` |
| `v_alertas_pendientes_cuidador` | Badge | Cuidador | `id_usuario` |
| `v_carga_medicos` | Reporte | Admin | — |
| `v_supervision` | Reporte | Admin | — |
| `v_dispositivos_iot` | Reporte | Admin | — |
| `v_perfil_paciente` | Reporte | Médico | `id_paciente` |
| `v_grafica_tomas` | Reporte | Médico | `id_paciente`, `fecha` |
| `v_mapa_medico` | Reporte | Médico | `id_medico` |
| `v_tendencia_adherencia_movil` | Analítica | Médico/Admin | `id_paciente`, `fecha` |
| `v_riesgo_omision_consecutiva` | Analítica | Médico/Admin | `id_paciente`, `racha_activa`, `dias_consecutivos` |
| `v_ranking_mejora_adherencia` | Analítica | Admin | `rol` |