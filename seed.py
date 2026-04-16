"""
seed.py — Datos de prueba para 5 escenarios de demostración
============================================================
Ejecutar: python seed.py

Requisitos:
    pip install psycopg2-binary bcrypt python-dotenv

Todos los inserts usan los SPs definidos en el script SQL del proyecto.
Las contraseñas se hashean con bcrypt antes de pasar a sp_crear_usuario_admin.

CORRECCIONES APLICADAS RESPECTO AL SEED ORIGINAL:
  1. Se redefine sp_crear_usuario_admin al inicio del seed para anular la
     versión rota duplicada que existe en el SQL (la cual referencia
     columnas inexistentes: nombre, correo, password, rol, fecha_registro).
  2. Escenario 2: se asigna un dispositivo GPS al cuidador antes de
     registrar la toma NFC (requisito del SP sp_registrar_toma_nfc para
     que el flujo de validación de ubicación se ejecute).
  3. Escenario 2: se corrige la hora_primera_toma para que la ventana de
     tolerancia contenga el instante de ambas tomas (antes quedaba fuera
     y el trigger clasificaba como SIN_AGENDA_ASOCIABLE en lugar de
     Duplicado).
  4. Escenario 3: se asigna GPS al cuidador para que sp_registrar_toma_nfc
     genere la alerta de 'Proximidad Inválida' (que solo se emite cuando
     v_gps_ok=TRUE).
  5. Escenario 3: se corrige la consulta final de alertas que usaba la
     columna inexistente a.estado; ahora hace JOIN con estado_alerta.
  6. Escenario 3: se ajusta la hora_primera_toma para caer dentro de la
     ventana de tolerancia de 60 minutos.
"""

import sys
from datetime import date, datetime, timedelta

import bcrypt
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# ─── Conexión ────────────────────────────────────────────────────────────────

DB_DSN = "postgresql://proyectofinal_user:444@localhost:5432/medi_nfc2"


def get_conn():
    return psycopg2.connect(DB_DSN)


# ─── Utilidades ──────────────────────────────────────────────────────────────

def ok(label, p_ok, p_msg, extra=""):
    marca = "✓" if p_ok == 1 else "✗"
    linea = f"  {marca} {label}: {p_msg}"
    if extra:
        linea += f" | {extra}"
    print(linea)
    if p_ok != 1:
        print(f"    ERROR — abortando seed. Codigo: {p_ok}")
        sys.exit(1)


def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def separador(titulo: str):
    print(f"\n{'═'*60}")
    print(f"  {titulo}")
    print(f"{'═'*60}")


# ─── Fix del SP de creación de usuario ──────────────────────────────────────
#
# El script SQL del proyecto define DOS veces sp_crear_usuario_admin. La
# segunda definición (al final del archivo) sobreescribe a la primera y
# está rota: intenta insertar en columnas que no existen en la tabla
# usuario (nombre, correo, password, rol, fecha_registro). Antes de usar
# cualquier SP de usuario, redefinimos la versión correcta.

def fix_sp_crear_usuario_admin(conn):
    """Redefine sp_crear_usuario_admin con la firma y lógica correctas."""
    cur = conn.cursor()

    # Primero eliminamos cualquier versión existente (sin importar firma)
    cur.execute("""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            FOR r IN
                SELECT p.oid::regprocedure AS sig
                FROM pg_proc p
                JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE p.proname = 'sp_crear_usuario_admin'
                  AND n.nspname = 'public'
            LOOP
                EXECUTE 'DROP PROCEDURE ' || r.sig;
            END LOOP;
        END
        $$;
    """)

    # Ahora creamos la versión correcta
    cur.execute("""
        CREATE OR REPLACE PROCEDURE sp_crear_usuario_admin(
            IN  p_email         VARCHAR(150),
            IN  p_password_hash TEXT,
            IN  p_rol           rol_usuario_enum,
            IN  p_id_rol        INTEGER,
            OUT p_ok            INTEGER,
            OUT p_msg           VARCHAR(300)
        )
        LANGUAGE plpgsql AS $BODY$
        BEGIN
            p_ok  := 0;
            p_msg := '';

            IF EXISTS (SELECT 1 FROM usuario WHERE email = p_email) THEN
                p_ok  := -10;
                p_msg := 'El correo ya está registrado.';
                RETURN;
            END IF;

            INSERT INTO usuario (email, password_hash, rol_usuario, id_medico, id_cuidador, activo)
            VALUES (
                p_email,
                p_password_hash,
                p_rol,
                CASE WHEN p_rol = 'medico'   THEN p_id_rol ELSE NULL END,
                CASE WHEN p_rol = 'cuidador' THEN p_id_rol ELSE NULL END,
                TRUE
            );

            p_ok  := 1;
            p_msg := 'Usuario creado: ' || p_email;

        EXCEPTION
            WHEN OTHERS THEN
                p_ok  := -100;
                p_msg := 'Error: ' || SQLERRM;
        END;
        $BODY$;
    """)
    conn.commit()
    cur.close()
    print("  ✓ sp_crear_usuario_admin redefinido (firma correcta)")


# ─── Catalogo compartido ─────────────────────────────────────────────────────

def crear_catalogo(conn):
    """Crea medicamento, especialidad, diagnóstico y unidades reutilizadas."""
    cur = conn.cursor()

    # Unidades de dosis — INSERT directo: no hay SP para esta tabla
    cur.execute("""
        INSERT INTO unidad_dosis (abreviatura, descripcion) VALUES
            ('mg',   'Miligramos'),
            ('ml',   'Mililitros'),
            ('mcg',  'Microgramos'),
            ('UI',   'Unidades Internacionales'),
            ('comp', 'Comprimido')
        ON CONFLICT (descripcion) DO NOTHING
    """)
    conn.commit()

    cur.execute("SELECT id_unidad FROM unidad_dosis WHERE abreviatura = 'mg'")
    id_unidad_mg = cur.fetchone()[0]
    print(f"  ✓ Unidades de dosis insertadas | id_unidad mg={id_unidad_mg}")

    # Especialidad
    cur.execute("CALL sp_gestion_especialidad('I', NULL, NULL, NULL, %s)", ["Geriatria"])
    id_esp, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Especialidad 'Geriatria'", p_ok, p_msg, f"id={id_esp}")

    # Diagnóstico
    cur.execute("CALL sp_gestion_diagnostico('I', NULL, NULL, NULL, %s)", ["Hipertension Arterial"])
    id_diag, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Diagnostico 'Hipertension'", p_ok, p_msg, f"id={id_diag}")

    # Medicamento — usa el id_unidad real de 'mg'
    cur.execute(
        "CALL sp_gestion_medicamento('I', NULL, NULL, NULL, %s, %s, %s, %s)",
        ["Losartan", "C09CA01", 100, id_unidad_mg],
    )
    id_med, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Medicamento 'Losartan 100mg'", p_ok, p_msg, f"id={id_med}")

    cur.close()
    return {"id_esp": id_esp, "id_diag": id_diag, "id_med": id_med, "id_unidad_mg": id_unidad_mg}


# ═══════════════════════════════════════════════════════════════════════════════
# ESCENARIO 1 — Omisión
# ═══════════════════════════════════════════════════════════════════════════════

def escenario_1(conn, catalogo):
    separador("ESCENARIO 1 — Omisión de toma")
    cur = conn.cursor()
    ids = {}

    # Médico
    cur.execute(
        "CALL sp_gestion_medico('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
        ["Carlos", "Mendoza", "Rios", "CED-SC1-001", "carlos.mendoza@seed.com"],
    )
    id_medico, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Medico Carlos Mendoza", p_ok, p_msg, f"id={id_medico}")
    ids["id_medico"] = id_medico

    # Usuario médico
    cur.execute(
        "CALL sp_crear_usuario_admin(%s, %s, %s, %s, NULL, NULL)",
        ["carlos.mendoza@seed.com", hash_pw("Seed1234!"), "medico", id_medico],
    )
    p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Usuario medico", p_ok, p_msg)

    # Paciente
    cur.execute(
        "CALL sp_gestion_paciente('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
        ["Elena", "Torres", "Vega", "1948-03-12", "TOVE480312MDFRRN01"],
    )
    id_pac, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Paciente Elena Torres", p_ok, p_msg, f"id={id_pac}")
    ids["id_paciente"] = id_pac

    # Diagnóstico al paciente
    cur.execute("CALL sp_asignar_diagnostico(%s, %s, NULL, NULL)", [id_pac, catalogo["id_diag"]])
    p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Diagnostico asignado a paciente", p_ok, p_msg)

    # Cuidador
    cur.execute(
        "CALL sp_gestion_cuidador('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, NULL)",
        ["Rosa", "Ibarra", "Soto", "formal", "8110000001", "rosa.ibarra@seed.com"],
    )
    id_cuid, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Cuidador Rosa Ibarra", p_ok, p_msg, f"id={id_cuid}")
    ids["id_cuidador"] = id_cuid

    cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, %s)", [id_pac, id_cuid, True])
    p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Cuidador asignado como principal", p_ok, p_msg)

    # Beacon (coordenadas de referencia)
    cur.execute(
        "CALL sp_gestion_beacon('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s)",
        ["BEACON-SC1-001", "Beacon Elena", id_pac, 25.6866, -100.3161, 10.0],
    )
    id_beacon, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Beacon instalado", p_ok, p_msg, f"id={id_beacon}")

    # Receta con fechas pasadas para que la toma ya haya vencido
    hoy = date.today()
    hace_5_dias = (hoy - timedelta(days=5)).isoformat()
    manana = (hoy + timedelta(days=25)).isoformat()

    cur.execute(
        "CALL sp_crear_receta(NULL, NULL, NULL, %s, %s, %s, %s, %s)",
        [id_pac, id_medico, hace_5_dias, hace_5_dias, manana],
    )
    id_receta, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Receta creada", p_ok, p_msg, f"id={id_receta}")
    ids["id_receta"] = id_receta

    # Agregar medicamento — primera toma hace 5 días a las 00:01
    # Con frecuencia de 24 h y tolerancia 30 min, la toma de hoy ya venció
    cur.execute(
        "CALL sp_agregar_receta_med(NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)",
        [id_receta, catalogo["id_med"], 50, 24, 30, "00:01:00", catalogo["id_unidad_mg"]],
    )
    id_rxm, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Medicamento agregado a receta (trigger genera agenda)", p_ok, p_msg, f"id_rxm={id_rxm}")
    ids["id_rxm"] = id_rxm

    # Verificar que hay agendas pendientes (sin evento NFC — ninguna toma registrada)
    cur.execute("""
        SELECT COUNT(*) FROM agenda_toma
        WHERE id_receta_medicamento = %s AND estado_agenda = 'pendiente'
    """, [id_rxm])
    pendientes_antes = cur.fetchone()[0]
    print(f"  → Agendas pendientes antes de detectar omisiones: {pendientes_antes}")

    # Ejecutar sp_detectar_omisiones
    cur.execute("CALL sp_detectar_omisiones(NULL, NULL, NULL)")
    p_ok, p_msg, p_total = cur.fetchone()
    conn.commit()
    ok(f"sp_detectar_omisiones ejecutado ({p_total} omisiones)", p_ok, p_msg)
    ids["omisiones_detectadas"] = p_total

    # Verificar estado final de la agenda
    cur.execute("""
        SELECT estado_agenda, COUNT(*) FROM agenda_toma
        WHERE id_receta_medicamento = %s
        GROUP BY estado_agenda
    """, [id_rxm])
    estados = cur.fetchall()
    print("  → Estado de agenda_toma tras deteccion:")
    for estado, cnt in estados:
        print(f"       {estado}: {cnt} registros")

    # Verificar alerta generada (omisiones no tienen evento_nfc — se ligan por id_receta_medicamento)
    cur.execute("""
        SELECT COUNT(*) FROM alerta a
        JOIN tipo_alerta ta ON ta.id_tipo_alerta = a.id_tipo_alerta
        JOIN estado_alerta ea ON ea.id_estado = a.id_estado
        WHERE a.id_receta_medicamento = %s
          AND UPPER(ta.descripcion) LIKE '%%OMISI%%'
          AND UPPER(ea.descripcion) = 'PENDIENTE'
    """, [id_rxm])
    row = cur.fetchone()
    total_alertas = row[0] if row else 0
    print(f"  → Alertas de omisión pendientes: {total_alertas}")

    cur.close()
    ids["resultado_esperado"] = "agenda_toma con estado='omitida', alerta tipo 'Omision' en Pendiente"
    return ids


# ═══════════════════════════════════════════════════════════════════════════════
# ESCENARIO 2 — Duplicación
# ═══════════════════════════════════════════════════════════════════════════════

def escenario_2(conn, catalogo):
    separador("ESCENARIO 2 — Toma duplicada")
    cur = conn.cursor()
    ids = {}

    # Médico
    cur.execute(
        "CALL sp_gestion_medico('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
        ["Laura", "Gutierrez", "Mora", "CED-SC2-002", "laura.gutierrez@seed.com"],
    )
    id_medico, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Medico Laura Gutierrez", p_ok, p_msg, f"id={id_medico}")

    # Paciente
    cur.execute(
        "CALL sp_gestion_paciente('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
        ["Pedro", "Salinas", "Cruz", "1955-07-20", "SACP550720HDFRZN02"],
    )
    id_pac, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Paciente Pedro Salinas", p_ok, p_msg, f"id={id_pac}")
    ids["id_paciente"] = id_pac

    # Cuidador
    cur.execute(
        "CALL sp_gestion_cuidador('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, NULL)",
        ["Jorge", "Paredes", "Lima", "formal", "8110000002", "jorge.paredes@seed.com"],
    )
    id_cuid, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Cuidador Jorge Paredes", p_ok, p_msg, f"id={id_cuid}")
    ids["id_cuidador"] = id_cuid

    cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, %s)", [id_pac, id_cuid, True])
    p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Cuidador asignado", p_ok, p_msg)

    # Usuario cuidador (necesario para sp_registrar_toma_nfc)
    cur.execute(
        "CALL sp_crear_usuario_admin(%s, %s, %s, %s, NULL, NULL)",
        ["jorge.paredes@seed.com", hash_pw("Seed1234!"), "cuidador", id_cuid],
    )
    p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Usuario cuidador", p_ok, p_msg)

    # GPS asignado al cuidador (requerido por sp_registrar_toma_nfc para
    # que la validación de ubicación se ejecute). Sin esto, v_gps_ok=FALSE
    # y no se puede clasificar proximidad.
    cur.execute(
        "CALL sp_gestion_gps('I', NULL, NULL, NULL, %s, %s, %s)",
        ["350000000000002", "SeedGPS-SC2", id_cuid],
    )
    id_gps, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("GPS asignado al cuidador", p_ok, p_msg, f"id_gps={id_gps}")

    # Beacon — coordenadas exactas que usaremos para la toma
    lat_beacon, lon_beacon = 25.6500, -100.2900
    cur.execute(
        "CALL sp_gestion_beacon('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s)",
        ["BEACON-SC2-001", "Beacon Pedro", id_pac, lat_beacon, lon_beacon, 50.0],
    )
    id_beacon, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Beacon instalado (radio 50m)", p_ok, p_msg, f"id={id_beacon}")

    # Receta y medicamento
    # Para que el trigger before_evento asocie la toma a una agenda, la
    # hora_primera_toma debe estar cerca del "ahora" (±tolerancia). Usamos
    # la hora actual redondeada — la agenda del día se generará justo
    # alrededor del momento en que registremos las tomas.
    hoy = date.today()
    ayer = (hoy - timedelta(days=1)).isoformat()
    en_30_dias = (hoy + timedelta(days=30)).isoformat()

    cur.execute(
        "CALL sp_crear_receta(NULL, NULL, NULL, %s, %s, %s, %s, %s)",
        [id_pac, id_medico, ayer, ayer, en_30_dias],
    )
    id_receta, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Receta creada", p_ok, p_msg, f"id={id_receta}")
    ids["id_receta"] = id_receta

    # hora_primera_toma = hora actual (no hace 2 horas). Con frecuencia de
    # 12 h y tolerancia 60 min, tanto la primera como la segunda toma caen
    # dentro de la ventana de la misma agenda.
    hora_toma = datetime.now().strftime("%H:%M:%S")
    cur.execute(
        "CALL sp_agregar_receta_med(NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)",
        [id_receta, catalogo["id_med"], 50, 12, 60, hora_toma, catalogo["id_unidad_mg"]],
    )
    id_rxm, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Medicamento agregado (tolerancia 60 min)", p_ok, p_msg, f"id_rxm={id_rxm}")
    ids["id_rxm"] = id_rxm

    # Insertar etiqueta NFC directamente (no hay SP específico)
    uid_nfc = "NFC-SC2-DUPLICADO-001"
    cur.execute("""
        INSERT INTO etiqueta_nfc (uid_nfc, nombre, fecha_registro, tipo_etiqueta, id_receta_medicamento, estado_etiqueta)
        VALUES (%s, %s, NOW(), %s, %s, 'activo')
        ON CONFLICT (uid_nfc) DO NOTHING
    """, [uid_nfc, 'Etiqueta SC2', 'medicamento', id_rxm])
    conn.commit()
    print(f"  ✓ Etiqueta NFC registrada: uid={uid_nfc}")
    ids["uid_nfc"] = uid_nfc

    # Primera toma — debe quedar 'Exitoso'
    cur.execute("""
        CALL sp_registrar_toma_nfc(NULL, NULL, NULL, NULL, NULL,
            %s, %s, %s, %s, NULL, %s)
    """, [uid_nfc, id_cuid, lat_beacon, lon_beacon, "Primera toma SC2"])
    p_id_ev1, p_ok, p_msg, p_res1, p_prox1 = cur.fetchone()
    conn.commit()
    ok(f"Primera toma registrada — resultado: {p_res1}", p_ok, p_msg, f"ev={p_id_ev1}")
    ids["id_evento_1"] = p_id_ev1
    ids["resultado_toma_1"] = p_res1

    # Segunda toma — mismo UID dentro de la misma ventana → trigger clasifica 'Duplicado'
    cur.execute("""
        CALL sp_registrar_toma_nfc(NULL, NULL, NULL, NULL, NULL,
            %s, %s, %s, %s, NULL, %s)
    """, [uid_nfc, id_cuid, lat_beacon, lon_beacon, "Segunda toma SC2 (duplicado)"])
    p_id_ev2, p_ok, p_msg, p_res2, p_prox2 = cur.fetchone()
    conn.commit()
    # p_ok puede ser 1 con resultado 'Duplicado' — el SP lo permite
    print(f"  {'✓' if p_ok == 1 else '✗'} Segunda toma registrada — resultado: {p_res2} | ev={p_id_ev2}")
    ids["id_evento_2"] = p_id_ev2
    ids["resultado_toma_2"] = p_res2

    # Verificar en bitacora_regla_negocio
    cur.execute("""
        SELECT regla_aplicada, resultado, detalle
        FROM bitacora_regla_negocio
        WHERE id_evento = %s
    """, [p_id_ev2])
    bita = cur.fetchone()
    if bita:
        print(f"  → Bitacora (evento duplicado): regla={bita[0]} | resultado={bita[1]}")
        print(f"       detalle: {bita[2]}")
    else:
        print("  → Sin registro en bitacora_regla_negocio para el segundo evento")

    cur.close()
    ids["resultado_esperado"] = (
        "Evento 1 = 'Exitoso', Evento 2 = 'Duplicado', "
        "bitacora con regla DUPLICADO_DETECTADO"
    )
    return ids


# ═══════════════════════════════════════════════════════════════════════════════
# ESCENARIO 3 — Toma fuera de domicilio
# ═══════════════════════════════════════════════════════════════════════════════

def escenario_3(conn, catalogo):
    separador("ESCENARIO 3 — Toma fuera de domicilio (proximidad invalida)")
    cur = conn.cursor()
    ids = {}

    # Médico
    cur.execute(
        "CALL sp_gestion_medico('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
        ["Mario", "Fuentes", "Aguilar", "CED-SC3-003", "mario.fuentes@seed.com"],
    )
    id_medico, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Medico Mario Fuentes", p_ok, p_msg, f"id={id_medico}")

    # Paciente
    cur.execute(
        "CALL sp_gestion_paciente('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
        ["Sofia", "Ramos", "Herrera", "1961-11-05", "RAHS611105MDFRZN03"],
    )
    id_pac, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Paciente Sofia Ramos", p_ok, p_msg, f"id={id_pac}")
    ids["id_paciente"] = id_pac

    # Cuidador
    cur.execute(
        "CALL sp_gestion_cuidador('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, NULL)",
        ["Ana", "Leal", "Dominguez", "informal", "8110000003", "ana.leal@seed.com"],
    )
    id_cuid, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Cuidador Ana Leal", p_ok, p_msg, f"id={id_cuid}")
    ids["id_cuidador"] = id_cuid

    cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, %s)", [id_pac, id_cuid, True])
    p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Cuidador asignado", p_ok, p_msg)

    cur.execute(
        "CALL sp_crear_usuario_admin(%s, %s, %s, %s, NULL, NULL)",
        ["ana.leal@seed.com", hash_pw("Seed1234!"), "cuidador", id_cuid],
    )
    p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Usuario cuidador", p_ok, p_msg)

    # GPS — imprescindible para que sp_registrar_toma_nfc genere la alerta
    # de 'Proximidad Inválida'. El SP solo inserta esa alerta cuando
    # v_gps_ok=TRUE, lo que requiere que el cuidador tenga GPS activo.
    cur.execute(
        "CALL sp_gestion_gps('I', NULL, NULL, NULL, %s, %s, %s)",
        ["350000000000003", "SeedGPS-SC3", id_cuid],
    )
    id_gps, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("GPS asignado al cuidador", p_ok, p_msg, f"id_gps={id_gps}")

    # Beacon con radio pequeño — 5 metros
    lat_beacon, lon_beacon = 25.6700, -100.3100
    cur.execute(
        "CALL sp_gestion_beacon('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s)",
        ["BEACON-SC3-001", "Beacon Sofia", id_pac, lat_beacon, lon_beacon, 5.0],
    )
    id_beacon, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Beacon instalado (radio 5m)", p_ok, p_msg, f"id={id_beacon}")
    ids["beacon_lat"] = lat_beacon
    ids["beacon_lon"] = lon_beacon

    # Receta y medicamento
    hoy = date.today().isoformat()
    en_30_dias = (date.today() + timedelta(days=30)).isoformat()
    cur.execute(
        "CALL sp_crear_receta(NULL, NULL, NULL, %s, %s, %s, %s, %s)",
        [id_pac, id_medico, hoy, hoy, en_30_dias],
    )
    id_receta, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Receta creada", p_ok, p_msg, f"id={id_receta}")
    ids["id_receta"] = id_receta

    # hora_primera_toma = ahora, tolerancia 60 min → la toma cae dentro de
    # la ventana y el trigger la clasifica normalmente. La alerta de
    # proximidad se genera por distancia, no por desfase temporal.
    hora_toma = datetime.now().strftime("%H:%M:%S")
    cur.execute(
        "CALL sp_agregar_receta_med(NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)",
        [id_receta, catalogo["id_med"], 50, 12, 60, hora_toma, catalogo["id_unidad_mg"]],
    )
    id_rxm, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Medicamento agregado a receta", p_ok, p_msg, f"id_rxm={id_rxm}")
    ids["id_rxm"] = id_rxm

    uid_nfc = "NFC-SC3-PROX-001"
    cur.execute("""
        INSERT INTO etiqueta_nfc (uid_nfc, nombre, fecha_registro, tipo_etiqueta, id_receta_medicamento, estado_etiqueta)
        VALUES (%s, %s, NOW(), %s, %s, 'activo')
        ON CONFLICT (uid_nfc) DO NOTHING
    """, [uid_nfc, 'Etiqueta SC3', 'medicamento', id_rxm])
    conn.commit()
    print(f"  ✓ Etiqueta NFC registrada: uid={uid_nfc}")
    ids["uid_nfc"] = uid_nfc

    # Coordenadas muy alejadas del beacon (~555 m al norte)
    lat_lejos = float(lat_beacon) + 0.005   # ~555 m de diferencia
    lon_lejos = float(lon_beacon)

    print(f"  → Coordenadas beacon:  lat={lat_beacon}, lon={lon_beacon}")
    print(f"  → Coordenadas cuidador: lat={lat_lejos}, lon={lon_lejos} (lejos ~555m)")

    cur.execute("""
        CALL sp_registrar_toma_nfc(NULL, NULL, NULL, NULL, NULL,
            %s, %s, %s, %s, %s, %s)
    """, [uid_nfc, id_cuid, lat_lejos, lon_lejos, 10.0, "Toma fuera de domicilio SC3"])
    p_id_ev, p_ok, p_msg, p_res, p_prox = cur.fetchone()
    conn.commit()

    print(f"  {'✓' if p_ok == 1 else '✗'} Toma registrada | resultado={p_res} | p_prox={p_prox}")
    print(f"       msg: {p_msg}")
    ids["id_evento"] = p_id_ev
    ids["p_prox"] = p_prox
    ids["p_res"] = p_res

    # Verificar alerta de proximidad invalida
    # IMPORTANTE: la tabla alerta NO tiene columna 'estado' — tiene
    # id_estado (FK a estado_alerta). Debemos hacer JOIN con estado_alerta
    # para obtener la descripción.
    cur.execute("""
        SELECT a.id_alerta, ta.descripcion AS tipo, ea.descripcion AS estado
        FROM alerta a
        JOIN tipo_alerta   ta ON ta.id_tipo_alerta = a.id_tipo_alerta
        JOIN estado_alerta ea ON ea.id_estado      = a.id_estado
        WHERE a.id_evento = %s
    """, [p_id_ev])
    alertas = cur.fetchall()
    print("  → Alertas generadas para el evento:")
    for al in alertas:
        print(f"       id={al[0]} | tipo={al[1]} | estado={al[2]}")

    cur.close()
    ids["resultado_esperado"] = "p_prox=False, alerta 'Proximidad Invalida' en estado Pendiente"
    return ids


# ═══════════════════════════════════════════════════════════════════════════════
# ESCENARIO 4 — Cambio de cuidador principal
# ═══════════════════════════════════════════════════════════════════════════════

def escenario_4(conn, catalogo):
    separador("ESCENARIO 4 — Cambio de cuidador principal")
    cur = conn.cursor()
    ids = {}

    # Médico
    cur.execute(
        "CALL sp_gestion_medico('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
        ["Patricia", "Vega", "Castillo", "CED-SC4-004", "patricia.vega@seed.com"],
    )
    id_medico, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Medico Patricia Vega", p_ok, p_msg, f"id={id_medico}")

    # Paciente
    cur.execute(
        "CALL sp_gestion_paciente('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
        ["Manuel", "Rojas", "Pena", "1945-02-28", "ROPM450228HDFRZN04"],
    )
    id_pac, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Paciente Manuel Rojas", p_ok, p_msg, f"id={id_pac}")
    ids["id_paciente"] = id_pac

    # Cuidador principal original
    cur.execute(
        "CALL sp_gestion_cuidador('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, NULL)",
        ["Diana", "Mora", "Luna", "formal", "8110000004", "diana.mora@seed.com"],
    )
    id_cuid_orig, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Cuidador original Diana Mora", p_ok, p_msg, f"id={id_cuid_orig}")
    ids["id_cuidador_original"] = id_cuid_orig

    cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, %s)", [id_pac, id_cuid_orig, True])
    p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Diana asignada como principal", p_ok, p_msg)

    # Segundo cuidador (reemplazo)
    cur.execute(
        "CALL sp_gestion_cuidador('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, NULL)",
        ["Felix", "Rios", "Garza", "formal", "8110000005", "felix.rios@seed.com"],
    )
    id_cuid_nuevo, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Cuidador nuevo Felix Rios", p_ok, p_msg, f"id={id_cuid_nuevo}")
    ids["id_cuidador_nuevo"] = id_cuid_nuevo

    # Intentar asignar el nuevo como principal SIN desactivar el anterior
    # → debe fallar por índice único parcial
    cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, %s)", [id_pac, id_cuid_nuevo, True])
    p_ok_esperado_fallo, p_msg_fallo = cur.fetchone()
    conn.commit()
    if p_ok_esperado_fallo != 1:
        print(f"  ✓ Intento fallido esperado: {p_msg_fallo}")
    else:
        print("  ⚠ Se esperaba fallo por indice unico pero el SP lo permitio")

    # Desactivar cuidador principal anterior en paciente_cuidador
    cur.execute("""
        UPDATE paciente_cuidador
        SET activo = FALSE
        WHERE id_paciente = %s AND id_cuidador = %s AND es_principal = TRUE
    """, [id_pac, id_cuid_orig])
    conn.commit()
    print(f"  ✓ Cuidador original desactivado en paciente_cuidador")

    # Ahora asignar Felix como principal
    cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, %s)", [id_pac, id_cuid_nuevo, True])
    p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Felix asignado como nuevo principal", p_ok, p_msg)

    # Verificar histórico — ambos registros deben existir
    cur.execute("""
        SELECT id_cuidador, es_principal, activo
        FROM paciente_cuidador
        WHERE id_paciente = %s
        ORDER BY id_cuidador
    """, [id_pac])
    historial = cur.fetchall()
    print("  → Historico paciente_cuidador:")
    for h in historial:
        estado = "activo" if h[2] else "inactivo"
        print(f"       cuidador={h[0]} | principal={h[1]} | {estado}")

    cur.close()
    ids["resultado_esperado"] = (
        "Diana inactiva (principal=True, activo=False), "
        "Felix activo como principal. Historial conservado."
    )
    return ids


# ═══════════════════════════════════════════════════════════════════════════════
# ESCENARIO 5 — Actualización de dosis (cancelar y recrear receta)
# ═══════════════════════════════════════════════════════════════════════════════

def escenario_5(conn, catalogo):
    separador("ESCENARIO 5 — Actualizacion de dosis (cancelar + nueva receta)")
    cur = conn.cursor()
    ids = {}

    # Médico
    cur.execute(
        "CALL sp_gestion_medico('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
        ["Fernando", "Reyes", "Luna", "CED-SC5-005", "fernando.reyes@seed.com"],
    )
    id_medico, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Medico Fernando Reyes", p_ok, p_msg, f"id={id_medico}")

    # Paciente
    cur.execute(
        "CALL sp_gestion_paciente('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, NULL)",
        ["Gloria", "Navarro", "Diaz", "1958-09-14", "NADG580914MDFRZN05"],
    )
    id_pac, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Paciente Gloria Navarro", p_ok, p_msg, f"id={id_pac}")
    ids["id_paciente"] = id_pac

    # Receta original con dosis 50 mg cada 24 h
    hoy = date.today().isoformat()
    en_30_dias = (date.today() + timedelta(days=30)).isoformat()

    cur.execute(
        "CALL sp_crear_receta(NULL, NULL, NULL, %s, %s, %s, %s, %s)",
        [id_pac, id_medico, hoy, hoy, en_30_dias],
    )
    id_receta_orig, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Receta original creada (50mg c/24h)", p_ok, p_msg, f"id={id_receta_orig}")
    ids["id_receta_original"] = id_receta_orig

    cur.execute(
        "CALL sp_agregar_receta_med(NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)",
        [id_receta_orig, catalogo["id_med"], 50, 24, 30, "08:00:00", catalogo["id_unidad_mg"]],
    )
    id_rxm_orig, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Medicamento 50mg/24h agregado (trigger genera agenda)", p_ok, p_msg, f"id_rxm={id_rxm_orig}")
    ids["id_rxm_original"] = id_rxm_orig

    # Contar agendas generadas
    cur.execute("""
        SELECT COUNT(*) FROM agenda_toma WHERE id_receta_medicamento = %s
    """, [id_rxm_orig])
    agendas_orig = cur.fetchone()[0]
    print(f"  → Agendas generadas por receta original: {agendas_orig}")
    ids["agendas_original"] = agendas_orig

    # Cancelar la receta original
    cur.execute("CALL sp_cancelar_receta(%s, NULL, NULL)", [id_receta_orig])
    p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Receta original cancelada", p_ok, p_msg)

    # Verificar que las agendas pendientes quedaron como 'omitida'
    cur.execute("""
        SELECT estado_agenda, COUNT(*) FROM agenda_toma
        WHERE id_receta_medicamento = %s
        GROUP BY estado_agenda
    """, [id_rxm_orig])
    estados_orig = cur.fetchall()
    print("  → Estado de agendas tras cancelacion:")
    for est, cnt in estados_orig:
        print(f"       {est}: {cnt}")

    # Nueva receta con dosis actualizada: 100 mg cada 12 h
    cur.execute(
        "CALL sp_crear_receta(NULL, NULL, NULL, %s, %s, %s, %s, %s)",
        [id_pac, id_medico, hoy, hoy, en_30_dias],
    )
    id_receta_nueva, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Nueva receta creada (100mg c/12h)", p_ok, p_msg, f"id={id_receta_nueva}")
    ids["id_receta_nueva"] = id_receta_nueva

    cur.execute(
        "CALL sp_agregar_receta_med(NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)",
        [id_receta_nueva, catalogo["id_med"], 100, 12, 30, "08:00:00", catalogo["id_unidad_mg"]],
    )
    id_rxm_nuevo, p_ok, p_msg = cur.fetchone()
    conn.commit()
    ok("Medicamento 100mg/12h agregado (trigger genera nueva agenda)", p_ok, p_msg, f"id_rxm={id_rxm_nuevo}")
    ids["id_rxm_nuevo"] = id_rxm_nuevo

    # Contar agendas de la nueva receta
    cur.execute("""
        SELECT COUNT(*) FROM agenda_toma WHERE id_receta_medicamento = %s
    """, [id_rxm_nuevo])
    agendas_nuevas = cur.fetchone()[0]
    print(f"  → Agendas generadas por nueva receta (doble frecuencia): {agendas_nuevas}")
    ids["agendas_nueva"] = agendas_nuevas

    # Verificar: nueva debe tener el doble de agendas (2 tomas/dia vs 1)
    if agendas_nuevas > 0 and agendas_orig > 0:
        ratio = round(agendas_nuevas / agendas_orig, 1)
        print(f"  → Ratio agendas nueva/original: {ratio}x (esperado ~2x por frecuencia doble)")

    cur.close()
    ids["resultado_esperado"] = (
        "Receta original cancelada, agendas originales='omitida'. "
        "Nueva receta vigente con el doble de agendas (cada 12h vs 24h)."
    )
    return ids


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n" + "█" * 60)
    print("  SEED — medi_nfc2  |  5 Escenarios de demostración")
    print("█" * 60)

    conn = get_conn()

    try:
        # Paso previo: arreglar el SP de usuarios (existen dos definiciones
        # en el SQL; la segunda está rota y sobreescribe a la correcta).
        separador("PREPARACIÓN — Fix de sp_crear_usuario_admin")
        fix_sp_crear_usuario_admin(conn)

        separador("CATÁLOGO COMPARTIDO")
        catalogo = crear_catalogo(conn)

        r1 = escenario_1(conn, catalogo)
        r2 = escenario_2(conn, catalogo)
        r3 = escenario_3(conn, catalogo)
        r4 = escenario_4(conn, catalogo)
        r5 = escenario_5(conn, catalogo)
    finally:
        conn.close()

    # ── Resumen final ──────────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print("  RESUMEN DE IDs GENERADOS")
    print("═" * 60)

    escenarios = [
        ("ESCENARIO 1 — Omision",              r1),
        ("ESCENARIO 2 — Duplicacion",           r2),
        ("ESCENARIO 3 — Proximidad invalida",   r3),
        ("ESCENARIO 4 — Cambio de cuidador",    r4),
        ("ESCENARIO 5 — Actualizacion de dosis",r5),
    ]

    for titulo, ids in escenarios:
        print(f"\n  {titulo}")
        for k, v in ids.items():
            if k == "resultado_esperado":
                continue
            print(f"    {k:<28} = {v}")
        print(f"    {'resultado_esperado':<28} → {ids.get('resultado_esperado','')}")

    print("\n" + "═" * 60)
    print("  Seed completado sin errores.")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    main()