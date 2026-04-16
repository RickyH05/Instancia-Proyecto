# Proyecto Flask — medi_nfc2

## Stack
- Python Flask (sin Blueprints, todo en app.py)
- PostgreSQL con psycopg2 (NO usar SQLAlchemy ni ORM)
- Base de datos: medi_nfc2 | usuario: proyectofinal_user | contraseña: 444
- Conexión: postgresql://proyectofinal_user:444@localhost:5432/medi_nfc2
- Ver @docs/database.md para firmas completas de SPs y Views

## Estructura
- app.py (una sola app, sin blueprints)
- /templates con Jinja2
- /static para CSS, JS e imágenes
- .env con variables SECRET_KEY, DB_*, ADMIN_EMAIL, ADMIN_PASSWORD_HASH

## Reglas de BD — NO negociables

### Reportes y consultas de lectura
Usar SIEMPRE SELECT directo a las Views documentadas en database.md.
NO usar BEGIN / CALL / FETCH / COMMIT para lecturas.
NO escribir SQL ad-hoc cuando existe una View para ese caso.

### Acciones (CRUD, login, NFC, alertas)
Usar SIEMPRE los Stored Procedures documentados en database.md.
Patrón: cur.execute("CALL sp_nombre(...)", [params]) + cur.fetchone() + conn.commit()
Siempre validar p_ok == 1 antes de confiar en el resultado.
En caso de error: conn.rollback().

### Nombres de columnas reales (errores comunes)
La BD usa estos nombres exactos — NO inventar variantes:
- paciente/medico/cuidador: apellido_p, apellido_m  (NO apellido_paterno/materno)
- medicamento: dosis_max  (NO dosis_maxima)
- ubicacion_gps: latitud, longitud, timestamp_ubicacion  (NO lat, lon, timestamp_gps)
- alerta: NO tiene columna 'estado' — tiene id_estado que hace JOIN con estado_alerta

## Autenticación
- bcrypt para contraseñas (nunca texto plano, nunca hash nuevo para comparar)
- Verificar con bcrypt.checkpw(password.encode(), stored_hash.encode())
- NO usar sp_login — hacer SELECT directo y verificar con checkpw
- Login de admin: email + hash en variables de entorno (ADMIN_EMAIL, ADMIN_PASSWORD_HASH)
- Login normal: contra tabla usuario con JOIN a medico/cuidador para obtener nombre

## Sesión Flask
Siempre guardar: user_id, rol, id_rol, nombre.
- rol es 'medico' | 'cuidador' | 'admin' (admin solo vive en .env)
- id_rol es id_medico o id_cuidador según rol (None para admin)
- nombre es el nombre completo (se muestra en base.html)

## Protección de rutas
- @login_requerido revisa session['user_id']
- @rol_requerido('medico', 'cuidador', ...) revisa session['rol']
- Siempre usar ambos decoradores juntos para rutas protegidas

## Convenciones de código
- Funciones pequeñas, try/except en cada llamada a BD
- Mensajes al usuario con flash() usando el p_msg del SP
- Templates Jinja2 reciben datos reales, nunca usar listas hardcodeadas con datos ficticios
- Si una View no cubre un caso, es aceptable hacer SELECT directo (ver database.md sección "excepción aceptada")

## Auditoría
Antes de llamar un SP que modifica tablas maestras, setear el usuario:
```python
cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)", [str(session['user_id'])])
```