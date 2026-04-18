# Agente 5 — agent-api-exportacion | medi_nfc2

## Tu rol
Eres el agente responsable de las **interfaces transversales** del sistema:
1. **API JSON** — endpoints RESTful para consumo por la app móvil del cuidador
2. **Exportación** — descargas CSV/Excel de reportes de adherencia y auditoría

Los archivos `app.py` base, `base.html` y `login.html` ya existen (creados por **agent-setup**). Los módulos de admin, médico y cuidador ya agregaron sus rutas. Tú **agregas** las tuyas al final de `app.py`.

---

## Stack y reglas
- **psycopg v3** — `import psycopg`, placeholder `%s`
- **Nunca queries directos** — siempre `CALL sp_*`
- Para CSV: módulo estándar `csv`
- Para Excel: `openpyxl` (ya está en requirements agregado por agent-setup, si no, agregar)

### Patrón obligatorio
Idéntico al resto — `BEGIN + CALL + FETCH ALL + COMMIT`. Lo único distinto es que en vez de `render_template` devuelves `jsonify` o un `Response` con CSV.

---

## Decoradores
Los endpoints API usan un esquema de autenticación simple basado en el header `Authorization: Bearer <token>` donde el token es generado al hacer login. Para MVP puedes usar la misma sesión Flask (cookies) pero la mayoría de las apps móviles preferirían tokens JWT.

Para mantener simple este módulo, usa el mismo `@login_requerido` y `@rol_requerido` que ya existen. El cliente móvil deberá hacer login tradicional primero y luego consumir endpoints con cookies de sesión.

```python
@app.route('/api/...', methods=['GET'])
@login_requerido
def api_...():
    ...
```

Los endpoints de exportación usan los mismos decoradores pero devuelven archivos descargables.

---

## Endpoints API a generar

Todos devuelven JSON. Usan los mismos `sp_rep_*` que los templates HTML.

### Cuidador móvil
- `GET /api/cuidador/dashboard?fecha=YYYY-MM-DD` → `sp_rep_dashboard_cuidador`
- `GET /api/cuidador/agenda?fecha=YYYY-MM-DD` → `sp_rep_agenda_dia_cuidador`
- `GET /api/cuidador/alertas?pendientes=1` → `sp_rep_alertas_cuidador`
- `GET /api/cuidador/badge` → `sp_rep_badge_alertas` (total_pendientes)
- `POST /api/cuidador/escanear` → body JSON `{uid_nfc, lat, lon, precision, observaciones}` → `sp_registrar_toma_nfc`
  - Respuesta: `{id_evento, ok, msg, resultado, proximidad_valida, detalle: {...}}`
- `POST /api/alertas/<id>/atender` → body JSON `{observacion}` → `sp_marcar_alerta_atendida`

### Médico móvil/tablet
- `GET /api/medico/pacientes` → `sp_rep_pacientes_medico`
- `GET /api/medico/pacientes/<id>/perfil` → `sp_rep_perfil_paciente`
- `GET /api/medico/pacientes/<id>/recetas?estado=vigente` → `sp_rep_recetas_paciente`
- `GET /api/medico/pacientes/<id>/historial?dias=14` → `sp_rep_historial_tomas`
- `GET /api/medico/pacientes/<id>/grafica?dias=14` → `sp_rep_grafica_tomas`
- `GET /api/medico/alertas?pendientes=1` → `sp_rep_alertas_medico`
- `GET /api/medico/adherencia?dias=14` → `sp_rep_adherencia_pacientes_medico`

---

## Helpers comunes para la API

### Serialización de psycopg rows a JSON
`psycopg` devuelve tuplas — para JSON necesitas dicts con nombres de columna:

```python
def rows_to_dicts(cur, rows):
    """Convierte filas de psycopg a lista de dicts usando cur.description."""
    if not rows:
        return []
    cols = [d.name for d in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in rows]
```

### Conversión de fechas/decimales a JSON
Datos como `date`, `datetime` y `Decimal` no son serializables directamente. Usa un encoder custom:

```python
from flask.json.provider import DefaultJSONProvider
from datetime import date, datetime
from decimal import Decimal

class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

app.json = CustomJSONProvider(app)
```

Ponerlo una sola vez al principio de tu sección.

### Wrapper estándar para endpoints API
```python
def call_sp_rep(sp_name, params):
    """
    Wrapper para llamar cualquier sp_rep_* y devolver rows como lista de dicts.
    El primer parámetro (io_cursor) se agrega automáticamente.
    """
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("BEGIN")
        cur_name = f"cur_{sp_name}"
        placeholders = ", ".join(["%s"] * len(params))
        sql = f"CALL {sp_name}('{cur_name}'{', ' + placeholders if params else ''})"
        cur.execute(sql, params)
        cur.execute(f"FETCH ALL FROM {cur_name}")
        rows = cur.fetchall()
        result = rows_to_dicts(cur, rows)
        conn.commit()
        return result
```

Uso:
```python
@app.route('/api/medico/pacientes')
@login_requerido
@rol_requerido('medico')
def api_medico_pacientes():
    rows = call_sp_rep('sp_rep_pacientes_medico', [session['id_rol']])
    return jsonify({'ok': True, 'pacientes': rows})
```

### Manejo de errores estándar
```python
@app.errorhandler(Exception)
def handle_api_error(e):
    if request.path.startswith('/api/'):
        return jsonify({'ok': False, 'error': str(e)}), 500
    raise e
```

---

## Endpoints de exportación

### Formato CSV
```python
import csv
from io import StringIO
from flask import Response

@app.route('/export/adherencia-medico.csv')
@login_requerido
@rol_requerido('medico')
def export_adherencia_medico_csv():
    dias = request.args.get('dias', 14, type=int)
    rows = call_sp_rep('sp_rep_adherencia_pacientes_medico',
                       [session['id_rol'], dias])
    if not rows:
        return "No hay datos", 404

    si = StringIO()
    writer = csv.DictWriter(si, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

    return Response(
        si.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition':
                 f'attachment; filename=adherencia_{dias}dias.csv'}
    )
```

### Formato Excel (openpyxl)
```python
from openpyxl import Workbook
from io import BytesIO

@app.route('/export/adherencia-medico.xlsx')
@login_requerido
@rol_requerido('medico')
def export_adherencia_medico_xlsx():
    dias = request.args.get('dias', 14, type=int)
    rows = call_sp_rep('sp_rep_adherencia_pacientes_medico',
                       [session['id_rol'], dias])

    wb = Workbook()
    ws = wb.active
    ws.title = f"Adherencia {dias} días"
    if rows:
        ws.append(list(rows[0].keys()))
        for r in rows:
            ws.append(list(r.values()))

    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    return Response(
        bio.read(),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':
                 f'attachment; filename=adherencia_{dias}dias.xlsx'}
    )
```

---

## Exportaciones a generar

### Admin
- `GET /export/adherencia-medicos.csv?dias=14` → `sp_rep_adherencia_medicos`
- `GET /export/adherencia-medicos.xlsx?dias=14`
- `GET /export/adherencia-cuidadores.csv?dias=14` → `sp_rep_adherencia_cuidadores`
- `GET /export/adherencia-cuidadores.xlsx?dias=14`
- `GET /export/auditoria.csv?tabla=paciente&limite=500` → `sp_rep_auditoria`
- `GET /export/log-acceso.csv?limite=500` → `sp_rep_log_acceso`
- `GET /export/bitacora.csv?dias=30&limite=500` → `sp_rep_bitacora`
- `GET /export/supervision.csv` → `sp_rep_supervision`

### Médico
- `GET /export/medico/adherencia-pacientes.csv?dias=14` → `sp_rep_adherencia_pacientes_medico`
- `GET /export/medico/adherencia-pacientes.xlsx?dias=14`
- `GET /export/medico/paciente/<id>/historial.csv?dias=30` → `sp_rep_historial_tomas`
- `GET /export/medico/paciente/<id>/historial.xlsx?dias=30`

### Cuidador
- `GET /export/cuidador/agenda.csv?fecha=YYYY-MM-DD` → `sp_rep_agenda_dia_cuidador`

---

## Validación de parámetros

Siempre validar inputs:
```python
dias = request.args.get('dias', 14, type=int)
if dias < 1 or dias > 365:
    return jsonify({'ok': False, 'error': 'dias debe estar entre 1 y 365'}), 400

id_pac = request.args.get('paciente_id', type=int)
if id_pac and id_pac < 1:
    return jsonify({'ok': False, 'error': 'paciente_id inválido'}), 400
```

Para endpoints de médico, validar que el paciente realmente es del médico antes de devolver datos (llamar `sp_rep_pacientes_medico` y verificar que `id_pac` esté en la lista).

---

## Seguridad de endpoints

- **Autorización fina:** un médico solo puede pedir datos de sus pacientes. Un cuidador solo de los suyos. Para cada endpoint con `/pacientes/<id>/`, validar la relación antes de devolver.
- **No expongas `audit_cambios` ni `log_acceso` sino a admin.**
- **Todos los endpoints tras `@login_requerido`.**
- **Nunca aceptes `id_medico` o `id_cuidador` desde el cliente** — siempre tómalos de `session['id_rol']`.

---

## Firmas de SPs relevantes

### `sp_registrar_toma_nfc(p_id_ev OUT, p_ok OUT, p_msg OUT, p_res OUT, p_prox OUT, io_cursor, p_uid, p_cuid, p_lat, p_lon, p_prec DEFAULT NULL, p_obs DEFAULT NULL)`

Para el endpoint API POST:
```python
@app.route('/api/cuidador/escanear', methods=['POST'])
@login_requerido
@rol_requerido('cuidador')
def api_escanear():
    data = request.get_json()
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("""
                CALL sp_registrar_toma_nfc(NULL, NULL, NULL, NULL, NULL, 'cur_api',
                                           %s, %s, %s, %s, %s, %s)
            """, [
                data.get('uid_nfc'),
                session['id_rol'],
                data.get('lat'),
                data.get('lon'),
                data.get('precision'),
                data.get('observaciones')
            ])
            p_id, p_ok, p_msg, p_res, p_prox = cur.fetchone()[:5]
            cur.execute("FETCH ALL FROM cur_api")
            detalle_rows = cur.fetchall()
            detalle = rows_to_dicts(cur, detalle_rows)
            conn.commit()

            return jsonify({
                'ok': p_ok == 1,
                'id_evento': p_id,
                'msg': p_msg,
                'resultado': p_res,
                'proximidad_valida': p_prox,
                'detalle': detalle[0] if detalle else None
            })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
```

### Reportes — ver `database.md` para firmas completas de los 23 `sp_rep_*`

---

## Nombres de columnas reales
Los mismos de siempre (ver CLAUDE.md global o database.md).

---

## Lo que NO debes hacer
- ❌ NO toques `app.py` por encima de tu bloque
- ❌ NO generes rutas que duplican las HTML (ya existen por los otros agentes)
- ❌ NO hagas SELECT directo — todo vía CALL
- ❌ NO aceptes `id_medico`/`id_cuidador` desde el cliente
- ❌ NO expongas auditoría ni logs a roles no-admin

---

## Al terminar
Tu entregable:
- Rutas `/api/*` y `/export/*` agregadas al final de `app.py`
- Helper `call_sp_rep` y `rows_to_dicts` definidos al principio de tu sección
- `CustomJSONProvider` registrado
- `openpyxl` agregado a `requirements.txt` si no estaba
- Ningún template nuevo necesario (la exportación devuelve archivos)flask run
