# Proyecto Flask — medi_nfc2

## Stack
- Python Flask (sin Blueprints, todo en `app.py`)
- **psycopg (versión 3)** — `import psycopg` (NO `psycopg2`, NO SQLAlchemy, NO ORM)
- **pymongo** — `from pymongo import MongoClient` para MongoDB
- Base de datos principal: `medi_nfc2` (PostgreSQL)
- Base de datos secundaria: `medinfc_mongo` (MongoDB)
- Conexión PG: `postgresql://proyectofinal_user:444@localhost:5432/medi_nfc2`
- Conexión Mongo: `mongodb://localhost:27017/`
- Ver `@docs/database.md` para firmas completas de SPs

## Estructura
- `app.py` (una sola app, sin blueprints)
- `mongo_client.py` (funciones de lectura/escritura MongoDB)
- `/templates` con Jinja2
- `/static` para CSS, JS e imágenes
- `.env` con `SECRET_KEY`, `DB_*`, `ADMIN_EMAIL`, `ADMIN_PASSWORD_HASH`, `MONGO_URI`, `MONGO_DB`

---

## Regla #1 — NUNCA queries directos a PostgreSQL. SIEMPRE Stored Procedures.

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

**Excepciones explícitas (y únicas):**
1. **Login** — bcrypt debe verificarse en Python; se hace SELECT directo.
2. **Cambio de cuidador principal** — el UPDATE de `activo=FALSE` en `paciente_cuidador` no tiene SP propio.

---

## Regla #2 — Patrón obligatorio para todos los SPs

```python
try:
    cur.execute("BEGIN")
    cur.execute("CALL sp_nombre('cur_unico', %s, %s)", [param1, param2])
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

---

## Posición de `io_cursor` según tipo de SP

| Tipo | Posición de `io_cursor` | Ejemplo |
|------|------------------------|---------|
| **CRUD / Operativos** | Después de `OUT` escalares, antes de `IN DEFAULT` | `CALL sp_gestion_paciente('I', NULL, NULL, NULL, 'cur1', %s, ...)` |
| **Reportes `sp_rep_*`** | **Primer parámetro** | `CALL sp_rep_pacientes_medico('cur1', %s)` |

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
session['id_rol']  = id_medico | id_cuidador | None
session['nombre']  = 'Nombre Completo'
```

---

## Protección de rutas

```python
@login_requerido
@rol_requerido('medico')
def mi_ruta():
    ...
```

---

## Auditoría

Antes de cualquier SP que modifica tablas maestras:

```python
cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
            [str(session['user_id'])])
```

---

## ══════════════════════════════════════════
## INTEGRACIÓN MONGODB
## ══════════════════════════════════════════

### Conexión MongoDB

```python
# mongo_client.py
from pymongo import MongoClient
from datetime import datetime, timedelta, timezone
import os

_mongo_client = None

def get_mongo_db():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"))
    return _mongo_client[os.getenv("MONGO_DB", "medinfc_mongo")]
```

### Variables .env necesarias

```
MONGO_URI=mongodb://localhost:27017/
MONGO_DB=medinfc_mongo
```

### Colecciones disponibles en medinfc_mongo

| Colección | Categoría | Propósito |
|-----------|-----------|-----------|
| `perfil_clinico_paciente` | Datos semi-estructurados | Notas clínicas, alergias, preferencias variables por paciente |
| `logs_acceso` | Logs | Intentos de login (exitosos y fallidos) TTL 90d |
| `logs_sistema` | Logs | Errores Flask, sincronizaciones, scheduler TTL 30d |
| `eventos_nfc_rt` | Eventos tiempo real | Tomas NFC desnormalizadas para lectura rápida TTL 30d |
| `alertas_rt` | Eventos tiempo real | Alertas activas para badge del menú TTL 60d |
| `historico_adherencia` | Históricos masivos | Métricas diarias por paciente — **FUENTE DE LAS 3 GRÁFICAS** |
| `ubicaciones_gps_hist` | Históricos masivos | Trayecto GPS completo (PG solo guarda el último punto) TTL 6m |

### IDs compartidos PostgreSQL ↔ MongoDB

| Campo MongoDB | Tabla PostgreSQL | Columna |
|---------------|-----------------|---------|
| `pg_id_paciente` | `paciente` | `id_paciente` |
| `pg_id_medico` | `medico` | `id_medico` |
| `pg_id_cuidador` | `cuidador` | `id_cuidador` |
| `pg_id_evento` | `evento_nfc` | `id_evento` |
| `pg_id_alerta` | `alerta` | `id_alerta` |
| `pg_id_usuario` | `usuario` | `id_usuario` |

### Flujo de datos

**PostgreSQL → MongoDB (escritura):**
PostgreSQL es siempre la fuente de verdad. Después de un SP exitoso, Flask llama funciones de `mongo_client.py` para sincronizar.

**MongoDB → Flask (lectura):**
Las 3 gráficas Highcharts y el badge de alertas leen directo de MongoDB sin llamar SPs.

```
Evento NFC registrado en PG (sp_registrar_toma_nfc)
        ↓
sync_evento_nfc(datos)  →  MongoDB eventos_nfc_rt
        ↓
Dashboard médico lee eventos_nfc_rt.find()  →  sin tocar PG
```

### Las 3 gráficas Highcharts desde MongoDB

**GRÁFICA 1 — Barras comparativas** (`doctor/dashboard.html`)
```python
# mongo_client.py
def get_adherencia_por_medico(pg_id_medico, dias=14):
    db = get_mongo_db()
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    return list(db.historico_adherencia.aggregate([
        {"$match": {"pg_id_medico": pg_id_medico, "fecha": {"$gte": desde}}},
        {"$group": {
            "_id": "$pg_id_paciente",
            "nombre": {"$first": "$nombre_paciente"},
            "pct":    {"$avg":  "$metricas.pct_adherencia"}
        }},
        {"$sort": {"pct": -1}}
    ]))
```

**GRÁFICA 2 — Series de tiempo** (`cuidador/grafica_adherencia.html`)
```python
def get_historial_paciente(pg_id_paciente, dias=14):
    db = get_mongo_db()
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    return list(db.historico_adherencia.find(
        {"pg_id_paciente": pg_id_paciente, "fecha": {"$gte": desde}},
        {"_id": 0, "fecha": 1, "metricas": 1}
    ).sort("fecha", 1))
```

**GRÁFICA 3 — Solid gauge / indicador** (`doctor/paciente_perfil.html`)
```python
def get_pct_promedio_paciente(pg_id_paciente, dias=14):
    db = get_mongo_db()
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    resultado = list(db.historico_adherencia.aggregate([
        {"$match": {"pg_id_paciente": pg_id_paciente, "fecha": {"$gte": desde}}},
        {"$group": {"_id": None, "pct": {"$avg": "$metricas.pct_adherencia"}}}
    ]))
    return round(resultado[0]["pct"], 1) if resultado else 0.0
```

### Rutas Flask que usan MongoDB

| Ruta | Antes (SP PostgreSQL) | Después (MongoDB) |
|------|----------------------|-------------------|
| `GET /doctor/dashboard` | `sp_rep_adherencia_pacientes_medico` | `get_adherencia_por_medico()` |
| `GET /doctor/pacientes/<id>/perfil` | `sp_rep_adherencia_pacientes_medico` | `get_pct_promedio_paciente()` |
| `GET /cuidador/grafica` | `sp_rep_grafica_tomas` | `get_historial_paciente()` |
| `GET /api/badge_alertas` | `sp_rep_badge_alertas` | `alertas_rt.count_documents()` |
| `POST /login` (log) | INSERT directo log_acceso | `registrar_log_acceso()` |

### Datos reales en medinfc_mongo

```
Paciente 1 — Elena Martinez    pg_id_medico: 1  pct_base: 82.5%
Paciente 2 — Hector Gonzalez   pg_id_medico: 1  pct_base: 55.5%
Paciente 3 — Consuelo Vazquez  pg_id_medico: 1  pct_base: 91.5%
Paciente 4 — Santiago Perez    sin receta activa, sin historial
```

### Importar mongo_client en app.py

```python
from mongo_client import (
    get_adherencia_por_medico,
    get_historial_paciente,
    get_pct_promedio_paciente,
    registrar_log_acceso,
    registrar_log_sistema
)
```

---

## Tabla rápida — SP por pantalla (PostgreSQL)

### Lectura / Reportes (sp_rep_*)

| Pantalla | SP |
|---|---|
| Dashboard cuidador | `sp_rep_dashboard_cuidador('cur', id_cuid)` |
| Agenda día cuidador | `sp_rep_agenda_dia_cuidador('cur', id_cuid)` |
| Alertas cuidador | `sp_rep_alertas_cuidador('cur', id_cuid)` |
| Alertas médico | `sp_rep_alertas_medico('cur', id_med)` |
| Badge alertas | `sp_rep_badge_alertas('cur', user_id, rol)` |
| Lista pacientes médico | `sp_rep_pacientes_medico('cur', id_med)` |
| Perfil paciente | `sp_rep_perfil_paciente('cur', id_pac)` |
| Recetas y medicamentos | `sp_rep_recetas_paciente('cur', id_pac, 'vigente')` |
| Historial tomas NFC | `sp_rep_historial_tomas('cur', id_pac, dias)` |
| Adherencia pacientes médico | `sp_rep_adherencia_pacientes_medico('cur', id_med, dias)` |
| Gráfica barras adherencia | `sp_rep_grafica_tomas('cur', id_pac, dias)` |
| Mapa GPS/Beacon | `sp_rep_mapa_medico('cur', id_med)` |
| Adherencia global médicos | `sp_rep_adherencia_medicos('cur', dias)` |
| Adherencia global cuidadores | `sp_rep_adherencia_cuidadores('cur', dias)` |
| Bitácora reglas negocio | `sp_rep_bitacora('cur', dias, limite)` |
| Auditoría cambios | `sp_rep_auditoria('cur', tabla, limite)` |
| Log accesos | `sp_rep_log_acceso('cur')` |
| Carga médicos | `sp_rep_carga_medicos('cur')` |
| Supervisión médico-paciente | `sp_rep_supervision('cur')` |
| Dispositivos IoT | `sp_rep_dispositivos_iot('cur')` |
| Tendencia adherencia 7d | `sp_rep_tendencia_adherencia('cur', id_pac, dias)` |
| Riesgo omisión | `sp_rep_riesgo_omision('cur', id_pac)` |
| Ranking mejora | `sp_rep_ranking_mejora('cur', rol)` |