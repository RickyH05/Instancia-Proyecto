# Agente 4 — agent-cuidador | medi_nfc2

## Tu rol
Eres el agente responsable del **rol CUIDADOR** de la aplicación Flask medi_nfc2.
Generas las pantallas operativas del cuidador: agenda del día, escaneo NFC, alertas y historial.

Tu flujo es el **más crítico y delicado** del sistema porque maneja la validación de tomas en tiempo real con `sp_registrar_toma_nfc`, que interactúa con tres triggers de BD.

Los archivos `app.py` base, `base.html` y `login.html` ya existen (creados por **agent-setup**). Tú **agregas** tus rutas al final de `app.py`.

---

## Stack y reglas
- **psycopg v3** — `import psycopg`, placeholder `%s`
- **Nunca queries directos** — siempre `CALL sp_*`
- Sesión Flask: `user_id`, `rol`, `id_rol` (tu `id_cuidador`), `nombre`

### Patrón obligatorio para TODOS los SPs
```python
try:
    with get_db() as conn, conn.cursor() as cur:
        cur.execute("BEGIN")
        cur.execute("CALL sp_nombre('cur_unico', %s, %s)", [p1, p2])
        # leer OUT escalares ANTES del FETCH si existen
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
- **Reportes (`sp_rep_*`):** PRIMER parámetro
- **Operativos (`sp_registrar_toma_nfc`, `sp_marcar_alerta_atendida`):** después de OUT escalares

---

## Decoradores de ruta
```python
@app.route('/cuidador/...')
@login_requerido
@rol_requerido('cuidador')
def cuidador_...():
    id_cuidador = session['id_rol']
    ...
```

---

## Rutas a generar

### Dashboard
- `GET /cuidador/dashboard` → `cuidador/dashboard.html` con:
  - Agenda del día (`sp_rep_dashboard_cuidador`)
  - Total alertas pendientes (`sp_rep_alertas_cuidador` con TRUE)
  - Pacientes a cargo (lista simple)

### Agenda del día con UIDs NFC
- `GET /cuidador/agenda` → `sp_rep_agenda_dia_cuidador('cur', id_cuidador, fecha)` con selector de fecha
  - Muestra cada toma programada con su `uid_nfc` y botón "Escanear"

### Escaneo NFC (la pantalla más importante)
- `GET /cuidador/escanear` → `cuidador/escaneo.html`
  - Input para pegar/ingresar UID del NFC
  - Inputs de latitud, longitud (obtenibles vía `navigator.geolocation` en JS)
  - Campo opcional de observaciones
  - Campo oculto con `id_cuidador = session.id_rol`
- `POST /cuidador/escanear` → llama `sp_registrar_toma_nfc(...)`
  - Este SP devuelve `p_id_ev, p_ok, p_msg, p_res, p_prox` en esos 5 valores
  - **Leerlos ANTES del FETCH**:
    ```python
    cur.execute("BEGIN")
    cur.execute("""
        CALL sp_registrar_toma_nfc(NULL, NULL, NULL, NULL, NULL, 'cur_nfc',
                                   %s, %s, %s, %s, %s, %s)
    """, [uid, id_cuidador, lat, lon, precision, observaciones])
    p_id_ev, p_ok, p_msg, p_res, p_prox = cur.fetchone()[:5]
    cur.execute("FETCH ALL FROM cur_nfc")
    detalle = cur.fetchone()
    conn.commit()
    ```
  - Mostrar feedback según resultado:
    - `p_res = 'Exitoso'` → verde, "Toma registrada correctamente"
    - `p_res = 'Tardío'` → amarillo, "Toma tardía — se registró pero fuera de tolerancia"
    - `p_res = 'Duplicado'` → rojo, "DUPLICADO — ya se escaneó esta toma recientemente"
  - Si `p_prox = False` → mostrar advertencia adicional "GPS fuera del radio del beacon"

### Alertas
- `GET /cuidador/alertas` → `sp_rep_alertas_cuidador('cur', id_cuidador, p_sol_pendientes)` con filtro
- `POST /cuidador/alertas/<id_al>/atender` → `sp_marcar_alerta_atendida(id_al, ..., p_obs)` con formulario opcional de observación

### Historial de tomas de sus pacientes
- `GET /cuidador/historial` → lista de pacientes asignados
- `GET /cuidador/pacientes/<id_pac>/historial` → `sp_rep_historial_tomas('cur', id_pac, dias)`

### Recetas de sus pacientes (solo lectura)
- `GET /cuidador/pacientes/<id_pac>/recetas` → `sp_rep_recetas_paciente('cur', id_pac, 'vigente')`

---

## Templates a generar (en `/templates/cuidador/`)

```
cuidador/
├── dashboard.html          # resumen del día + alertas pendientes
├── agenda.html             # tomas del día con UID NFC
├── escaneo.html            # formulario principal de escaneo NFC
├── escaneo_resultado.html  # resultado de una toma (éxito/tardío/duplicado/prox inválida)
├── alertas.html
├── historial.html          # selector de paciente
├── historial_paciente.html # historial de tomas de un paciente
└── recetas_paciente.html   # recetas del paciente (solo lectura)
```

---

## Escaneo NFC — detalle técnico CRÍTICO

### Obtener ubicación en el navegador (`escaneo.html`)
```javascript
navigator.geolocation.getCurrentPosition(
    (pos) => {
        document.querySelector('input[name="latitud"]').value  = pos.coords.latitude;
        document.querySelector('input[name="longitud"]').value = pos.coords.longitude;
        document.querySelector('input[name="precision"]').value = pos.coords.accuracy;
    },
    (err) => alert('No se pudo obtener ubicación: ' + err.message)
);
```

### Lectura del UID NFC
Para MVP, el cuidador puede ingresar manualmente el UID (copiándolo de la pantalla de agenda).
Si el navegador soporta Web NFC API (solo Chrome Android):
```javascript
if ('NDEFReader' in window) {
    const reader = new NDEFReader();
    await reader.scan();
    reader.onreading = (event) => {
        document.querySelector('input[name="uid_nfc"]').value = event.serialNumber;
    };
}
```

### Validaciones en el formulario
- `uid_nfc` obligatorio
- `latitud` entre -90 y 90
- `longitud` entre -180 y 180
- `precision` opcional, entre 0.5 y 500 si se provee

### Qué hace `sp_registrar_toma_nfc` internamente
1. Valida que `uid_nfc` exista en `etiqueta_nfc` y esté activa → sino `p_ok = -1`
2. Registra una fila en `ubicacion_gps` para el cuidador (si tiene GPS asignado)
3. Calcula distancia Haversine al beacon del paciente
4. Inserta en `evento_nfc` → **dispara 2 triggers automáticos**:
   - `trg_antes_evento`: calcula desfase, detecta duplicados, clasifica `id_resultado`
   - `trg_despues_evento`: inserta en `alerta` si corresponde + `bitacora_regla_negocio`
5. Inserta en `evento_proximidad` con la distancia calculada
6. Si `proximidad_valida = FALSE` y GPS está verificado → genera alerta `Proximidad Inválida`

**Tú no haces ningún INSERT manual — el SP lo hace todo.** Solo lo llamas con los parámetros correctos.

---

## Los 3 resultados posibles del escaneo

| p_res | p_prox | Significado | Color UI |
|-------|--------|-------------|----------|
| `'Exitoso'` | `TRUE` | Toma en ventana + en domicilio | 🟢 Verde |
| `'Exitoso'` | `FALSE` | Toma en ventana + fuera de domicilio → alerta operativa | 🟡 Amarillo |
| `'Tardío'` | `TRUE` o `FALSE` | Toma fuera de tolerancia | 🟠 Naranja |
| `'Duplicado'` | `-` | Ya había toma exitosa/tardía en la misma ventana | 🔴 Rojo |

El SP siempre devuelve `p_ok = 1` para estos casos (no es error de sistema, es resultado clínico). El único caso donde `p_ok != 1` es si el UID no existe o faltan campos.

---

## Firmas de los SPs que usarás

### `sp_registrar_toma_nfc(p_id_ev, p_ok, p_msg, p_res, p_prox, io_cursor, p_uid, p_cuid, p_lat, p_lon, p_prec DEFAULT NULL, p_obs DEFAULT NULL)`
- 5 OUT escalares + io_cursor + 6 IN (2 con DEFAULT)
- Al leer con `fetchone()[:5]` obtienes `(p_id_ev, p_ok, p_msg, p_res, p_prox)`

### `sp_marcar_alerta_atendida(p_id_al, p_ok, p_msg, io_cursor, p_obs DEFAULT NULL)`
- 2 OUT + io_cursor + 1 IN con DEFAULT
- `p_obs` opcional, se guarda en `bitacora_regla_negocio`

### Reportes (io_cursor PRIMERO)
- `sp_rep_dashboard_cuidador('cur', p_cuidador, p_fecha DEFAULT CURRENT_DATE)`
- `sp_rep_agenda_dia_cuidador('cur', p_cuidador, p_fecha DEFAULT CURRENT_DATE)`
- `sp_rep_alertas_cuidador('cur', p_cuidador, p_sol_pendientes DEFAULT TRUE)`
- `sp_rep_historial_tomas('cur', p_paciente, p_dias DEFAULT 14)`
- `sp_rep_recetas_paciente('cur', p_paciente, p_estado_receta DEFAULT NULL)`

### Badge (en `base.html` ya está inyectado vía context_processor por agent-setup, no hace falta llamarlo manualmente en tus rutas)

---

## Datos de ejemplo para pruebas

Cuidadores disponibles (tu `id_rol` tras login):
- id 1 = Adriana Morales (formal, con GPS)
- id 2 = Juan Torres (formal, con GPS)
- id 3 = Patricia Luna (informal, sin GPS)
- id 4 = Luz García (formal, con GPS)
- id 5-8 = resto

Contraseña de todos: `Cuidador1234!`

UIDs NFC de ejemplo disponibles en la BD:
- `NFC-001` → Losartán paciente 1 (Ernesto)
- `NFC-005` → Metformina paciente 2 (Gloria)
- `NFC-017` → Metformina paciente 5 (Jorge)
- `NFC-021` → Losartán paciente 6 (Leticia)
- etc. (20 etiquetas total)

---

## Nombres de columnas reales

| Tabla | Nombres correctos |
|-------|-------------------|
| paciente, cuidador | `apellido_p`, `apellido_m` |
| ubicacion_gps | `latitud`, `longitud`, `timestamp_ubicacion` |
| evento_nfc | `timestamp_lectura`, `fecha_registro`, `desfase_min` |
| alerta | `id_estado` (NO `estado`) |
| beacon | `latitud_ref`, `longitud_ref`, `radio_metros` |

---

## Lo que NO debes hacer
- ❌ NO toques `app.py` por encima de tu bloque
- ❌ NO generes rutas `/admin/*`, `/medico/*`, `/api/*`
- ❌ NO hagas INSERT manual a `evento_nfc`, `ubicacion_gps`, `evento_proximidad` o `alerta` — `sp_registrar_toma_nfc` lo hace todo vía triggers
- ❌ NO uses psycopg2
- ❌ NO uses `sp_login`

---

## Al terminar
Tu entregable:
- Rutas `/cuidador/*` agregadas al final de `app.py`
- Templates en `/templates/cuidador/` (8 archivos)
- Ningún otro archivo modificado