# Proyecto Flask — medi_nfc2

## Stack
- Python Flask
- PostgreSQL con psycopg2 (NO usar SQLAlchemy, NO usar ORM de ningún tipo)
- Base de datos: medi_nfc2 | usuario: proyectofinal_user | contraseña: 444
- Conexión: postgresql://proyectofinal_user:444@localhost:5432/medi_nfc2

## Estructura del proyecto
- Una sola app Flask sin Blueprints
- Todas las rutas en app.py
- Carpeta /templates para HTML con Jinja2
- Carpeta /static para CSS, JS e imágenes

## Base de datos
- NUNCA escribir SQL directo, siempre usar los Stored Procedures definidos en @docs/database.md
- Toda llamada a SP usa psycopg2 con cur.execute("CALL sp_nombre(...)", [params])
- Los SPs de reporte (REFCURSOR) siempre van dentro de BEGIN / COMMIT explícito
- Siempre verificar p_ok == 1 antes de usar los resultados
- Siempre usar conn.commit() después de operaciones de escritura
- En caso de error, hacer conn.rollback()

## Autenticación y contraseñas
- Usar bcrypt para hashear contraseñas (librería: bcrypt)
- NUNCA guardar ni comparar contraseñas en texto plano
- Hashear siempre antes de pasar al SP: bcrypt.hashpw(password.encode(), bcrypt.gensalt())
- Verificar con: bcrypt.checkpw(password.encode(), hash_guardado)
- Sesiones con Flask session (secret_key en variable de entorno)

## Seguridad
- El secret_key de Flask viene de variable de entorno, nunca hardcodeado
- Proteger rutas con un decorador @login_required que revise session['user_id']
- Siempre validar que el rol en sesión coincida con la ruta que se está accediendo

## Convenciones de código
- Funciones pequeñas, una responsabilidad por función
- Manejo de errores con try/except en cada llamada a la BD
- Los mensajes de error al usuario vienen del campo p_msg que devuelve el SP
- Usar flash() para mensajes de éxito y error al usuario
## Base de datos
Ver @docs/database.md para firmas y ejemplos de todos los SPs.
## ⚠️ Regla crítica — SPs de reporte eliminados

Los siguientes SPs **ya no existen** en la base de datos. Fueron reemplazados por Views.
Si en algún momento de esta conversación o en código existente aparece una llamada a cualquiera
de estos SPs, **debes reemplazarla automáticamente** por la View equivalente usando SELECT.

| SP eliminado | View que lo reemplaza | Filtros equivalentes |
|---|---|---|
| `sp_rep_adherencia_admin` | `v_adherencia_medico` | `fecha_hora_programada >= NOW() - INTERVAL 'X days'` |
| `sp_rep_adherencia_cuidador` | `v_adherencia_cuidador` | `fecha_hora_programada >= NOW() - INTERVAL 'X days'` |
| `sp_rep_adherencia_medico` | `v_adherencia_paciente_por_medico` | `id_medico = %s AND fecha_hora_programada >= ...` |
| `sp_listar_bitacora` | `v_bitacora_regla_negocio` | `timestamp_eval BETWEEN %s AND %s` |
| `sp_listar_audit_cambios` | `v_audit_cambios` | `tabla = %s` |
| `sp_listar_accesos` | `v_log_acceso` | `id_usr = %s` |
| `sp_dashboard_cuidador` | `v_dashboard_cuidador` | `id_cuidador = %s AND fecha_hora_programada::DATE = %s` |
| `sp_pacientes_medico` | `v_pacientes_medico` | `id_medico = %s` |
| `sp_alertas_medico` | `v_alertas_medico` | `id_medico = %s AND UPPER(estado) = 'PENDIENTE'` |
| `sp_alertas_cuidador` | `v_alertas_cuidador` | `id_cuidador = %s AND UPPER(estado) = 'PENDIENTE'` |
| `sp_recetas_paciente` | `v_recetas_paciente` | `id_paciente = %s AND estado_receta = %s` |
| `sp_historial_tomas` | `v_historial_tomas` | `id_paciente = %s AND fecha_registro >= NOW() - INTERVAL 'X days'` |
| `sp_agenda_dia_cuidador` | `v_agenda_dia_cuidador` | `id_cuidador = %s AND fecha_hora_programada::DATE = %s` |
| `sp_carga_medicos` | `v_carga_medicos` | — |
| `sp_supervision` | `v_supervision` | — |
| `sp_listar_iot` | `v_dispositivos_iot` | — |
| `sp_perfil_paciente` | `v_perfil_paciente` | `id_paciente = %s` |
| `sp_grafica_tomas` | `v_grafica_tomas` | `id_paciente = %s AND fecha >= CURRENT_DATE - X` |
| `sp_mapa_medico` | `v_mapa_medico` | `id_medico = %s` |
| `sp_tendencia_adherencia_movil` | `v_tendencia_adherencia_movil` | `id_paciente = %s AND fecha >= CURRENT_DATE - X` |
| `sp_riesgo_omision_consecutiva` | `v_riesgo_omision_consecutiva` | `id_paciente = %s AND racha_activa = TRUE` |
| `sp_ranking_mejora_adherencia` | `v_ranking_mejora_adherencia` | `rol = %s` |

### Patrón de migración

**Antes (SP eliminado):**
```python
cur.execute("BEGIN;")
cur.execute("CALL sp_dashboard_cuidador('c1', NULL, NULL, %s, %s)", [id_cuidador, fecha])
cur.execute("FETCH ALL FROM c1;")
rows = cur.fetchall()
cur.execute("COMMIT;")
```

**Ahora (View):**
```python
cur.execute("""
    SELECT * FROM v_dashboard_cuidador
    WHERE id_cuidador = %s AND fecha_hora_programada::DATE = %s
    ORDER BY fecha_hora_programada
""", [id_cuidador, fecha])
rows = cur.fetchall()
```