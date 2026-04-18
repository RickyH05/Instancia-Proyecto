import os
import uuid
from datetime import date
from functools import wraps

import bcrypt
import psycopg
from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.jinja_env.filters['enumerate'] = enumerate
app.secret_key = os.environ["SECRET_KEY"]

# Asegurar que el directorio de uploads exista al iniciar
_UPLOAD_DIR = os.path.join(app.root_path, "static", "img", "uploads")
os.makedirs(_UPLOAD_DIR, exist_ok=True)

_ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
_MAX_FOTO_BYTES = 2 * 1024 * 1024  # 2 MB


def guardar_foto_perfil(file_storage):
    """Valida y guarda un archivo de foto de perfil.

    Retorna la ruta relativa para guardar en BD (ej. 'uploads/abc123.jpg'),
    o None si no se subió archivo o la validación falla (se llama flash).
    """
    if not file_storage or file_storage.filename == "":
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        flash("Formato de imagen no permitido. Usa PNG, JPG, JPEG o WEBP.", "danger")
        return None
    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > _MAX_FOTO_BYTES:
        flash("La imagen supera el límite de 2 MB.", "danger")
        return None
    filename = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(_UPLOAD_DIR, filename))
    return f"uploads/{filename}"


@app.context_processor
def inject_alert_count():
    if "user_id" not in session:
        return {"alertas_badge": 0}
    rol = session.get("rol")
    if rol not in ("medico", "cuidador"):
        return {"alertas_badge": 0}
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_badge_alertas('cur_badge', %s, %s)",
                    [session["user_id"], rol])
        cur.execute("FETCH ALL FROM cur_badge")
        row = cur.fetchone()
        total = row[0] if row else 0
        conn.commit()
        cur.close(); conn.close()
        return {"alertas_badge": total}
    except Exception:
        return {"alertas_badge": 0}

# ─── Conexión a la base de datos ────────────────────────────────────────────

def get_db():
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASS"],
        port=os.environ.get("DB_PORT", "5432"),
    )

# ─── Decoradores de acceso ───────────────────────────────────────────────────

def login_requerido(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def rol_requerido(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get("rol") not in roles:
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator

# ═══════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════

@app.route("/", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not email or not password:
            flash("Por favor ingresa email y contraseña.", "danger")
            return render_template("login.html")

        # ── Verificar admin especial (credenciales en .env, sin registro en BD) ──
        admin_email = os.environ.get("ADMIN_EMAIL", "")
        admin_hash  = os.environ.get("ADMIN_PASSWORD_HASH", "")
        if email == admin_email and admin_hash and bcrypt.checkpw(password.encode(), admin_hash.encode()):
            session["user_id"]    = 0
            session["rol"]        = "admin"
            session["id_rol"]     = None
            session["nombre"]     = "Administrador"
            session["foto_perfil"] = "default_medico.png"
            return redirect(url_for("dashboard"))

        # ── Login normal contra tabla usuario ────────────────────────────────
        try:
            conn = get_db()
            cur  = conn.cursor()

            cur.execute("""
                SELECT u.id_usuario, u.password_hash, u.rol_usuario,
                       COALESCE(u.id_medico, u.id_cuidador) AS id_rol,
                       CASE u.rol_usuario
                           WHEN 'medico'   THEN m.nombre || ' ' || m.apellido_p
                           WHEN 'cuidador' THEN c.nombre || ' ' || c.apellido_p
                           ELSE u.email
                       END AS nombre,
                       CASE u.rol_usuario
                           WHEN 'medico'   THEN COALESCE(m.foto_perfil, 'default_medico.png')
                           WHEN 'cuidador' THEN COALESCE(c.foto_perfil, 'default_cuidador.png')
                           ELSE 'default_medico.png'
                       END AS foto_perfil
                FROM usuario u
                LEFT JOIN medico   m ON m.id_medico   = u.id_medico
                LEFT JOIN cuidador c ON c.id_cuidador = u.id_cuidador
                WHERE u.email = %s AND u.activo = TRUE
            """, [email])
            row = cur.fetchone()

            login_ok = False
            if row:
                id_usuario, stored_hash, rol, id_rol, nombre, foto_perfil = row
                if bcrypt.checkpw(password.encode(), stored_hash.encode()):
                    login_ok = True

            if row:
                cur.execute("""
                    INSERT INTO log_acceso (id_usr, email, rol, ip, exitoso)
                    VALUES (%s, %s, %s, %s, %s)
                """, [row[0], email, row[2], request.remote_addr, login_ok])
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            flash("Error de conexión con la base de datos.", "danger")
            return render_template("login.html")

        if login_ok:
            session["user_id"]    = id_usuario
            session["rol"]        = rol
            session["id_rol"]     = id_rol
            session["nombre"]     = nombre
            session["foto_perfil"] = foto_perfil
            return redirect(url_for("dashboard"))

        flash("Credenciales incorrectas.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_requerido
def dashboard():
    rol = session.get("rol")
    if rol == "admin":
        return redirect(url_for("admin_dashboard"))
    elif rol == "medico":
        return redirect(url_for("doctor_dashboard"))
    else:
        return redirect(url_for("cuidador_home"))

# ═══════════════════════════════════════════════════════
# ADMIN — helpers
# ═══════════════════════════════════════════════════════

def _admin_db():
    """Abre conexión y cursor. Devuelve (conn, cur)."""
    conn = get_db()
    cur  = conn.cursor()
    return conn, cur

# ═══════════════════════════════════════════════════════
# ADMIN — Dashboard
# ═══════════════════════════════════════════════════════

@app.route("/admin")
@login_requerido
@rol_requerido("admin")
def admin_dashboard():
    """Vista general: carga de médicos + conteos reales para stat cards."""
    carga = []
    total_medicos = total_cuidadores = total_pacientes = total_medicamentos = 0
    total_gps = total_beacons = total_alertas = 0
    actividad_reciente = []
    try:
        conn, cur = _admin_db()

        # carga de médicos
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_carga_medicos('cur_carga')")
        cur.execute("FETCH ALL FROM cur_carga")
        carga = cur.fetchall()
        conn.commit()

        # conteos directos (no tienen SP equivalente)
        cur.execute("SELECT COUNT(*) FROM medico WHERE activo = TRUE")
        total_medicos = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM cuidador")
        total_cuidadores = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM paciente WHERE activo = TRUE")
        total_pacientes = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM medicamento WHERE activo = TRUE")
        total_medicamentos = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM gps_imei WHERE activo = TRUE")
        total_gps = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM beacon WHERE activo = TRUE")
        total_beacons = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM alerta a
            JOIN estado_alerta ea ON ea.id_estado = a.id_estado
            WHERE UPPER(ea.descripcion) = 'PENDIENTE'
        """)
        total_alertas = cur.fetchone()[0]

        # actividad reciente de auditoría
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_auditoria('cur_audit', NULL, 5)")
        cur.execute("FETCH ALL FROM cur_audit")
        raw_act = cur.fetchall()
        # cols: id_audit, tabla, id_reg, accion, campo, val_antes, val_despues, usuario_db, id_usr_app, ts
        actividad_reciente = [
            (str(r[8]) if r[8] else r[7], r[3], r[1], str(r[9])[:16]) for r in raw_act
        ]
        conn.commit()

        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar el dashboard: {e}", "danger")
    return render_template("admin/dashboard.html",
        carga=carga,
        total_medicos=total_medicos, total_cuidadores=total_cuidadores,
        total_pacientes=total_pacientes, total_medicamentos=total_medicamentos,
        total_gps=total_gps, total_beacons=total_beacons, total_alertas=total_alertas,
        actividad_reciente=actividad_reciente,
    )


# ═══════════════════════════════════════════════════════
# ADMIN — Médicos
# ═══════════════════════════════════════════════════════

@app.route("/admin/medicos", methods=["GET", "POST"])
@login_requerido
@rol_requerido("admin")
def admin_medicos():
    """CRUD de médicos — sp_gestion_medico ('I'/'U'/'D')."""
    if request.method == "POST":
        acc     = request.form.get("acc", "").strip().upper()
        id_med  = request.form.get("id_medico", None, type=int)
        nom     = request.form.get("nombre",    "").strip() or None
        ap      = request.form.get("apellido_p","").strip() or None
        am      = request.form.get("apellido_m","").strip() or None
        ced     = request.form.get("cedula",    "").strip() or None
        email   = request.form.get("email",     "").strip() or None
        foto    = guardar_foto_perfil(request.files.get("foto"))

        try:
            conn, cur = _admin_db()
            cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
                        [str(session["user_id"])])
            cur.execute("BEGIN")
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_medico('I', NULL, NULL, NULL, 'cur_med_i', %s, %s, %s, %s, %s, %s)",
                    [nom, ap, am, ced, email, foto],
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_medico('U', %s, NULL, NULL, 'cur_med_u', %s, %s, %s, %s, %s, %s)",
                    [id_med, nom, ap, am, ced, email, foto],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_medico('D', %s, NULL, NULL, 'cur_med_d')", [id_med])
            else:
                conn.rollback()
                flash("Acción no válida.", "danger")
                return redirect(url_for("admin_medicos"))

            _, p_ok, p_msg = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_medicos"))

    # GET — listado directo (no existe sp_rep_* para listar todos los médicos)
    medicos = []
    try:
        conn, cur = _admin_db()
        cur.execute("""
            SELECT id_medico, nombre, apellido_p, COALESCE(apellido_m,'') AS apellido_m,
                   COALESCE(cedula_profesional,'') AS cedula,
                   COALESCE(email,'') AS email, activo,
                   COALESCE(foto_perfil,'') AS foto_perfil
            FROM medico ORDER BY apellido_p, nombre
        """)
        medicos = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar médicos: {e}", "danger")
    return render_template("admin/medicos.html", medicos=medicos)


# ═══════════════════════════════════════════════════════
# ADMIN — Cuidadores
# ═══════════════════════════════════════════════════════

@app.route("/admin/cuidadores", methods=["GET", "POST"])
@login_requerido
@rol_requerido("admin")
def admin_cuidadores():
    """CRUD de cuidadores — sp_gestion_cuidador ('I'/'U'/'D')."""
    if request.method == "POST":
        acc    = request.form.get("acc", "").strip().upper()
        id_c   = request.form.get("id_cuidador", None, type=int)
        nom    = request.form.get("nombre",    "").strip() or None
        ap     = request.form.get("apellido_p","").strip() or None
        am     = request.form.get("apellido_m","").strip() or None
        tipo   = request.form.get("tipo",      "").strip() or None   # 'formal'|'informal'
        tel    = request.form.get("telefono",  "").strip() or None
        email  = request.form.get("email",     "").strip() or None
        foto   = guardar_foto_perfil(request.files.get("foto"))

        try:
            conn, cur = _admin_db()
            cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
                        [str(session["user_id"])])
            cur.execute("BEGIN")
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_cuidador('I', NULL, NULL, NULL, 'cur_cuid_i', %s, %s, %s, %s, %s, %s, %s)",
                    [nom, ap, am, tipo, tel, email, foto],
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_cuidador('U', %s, NULL, NULL, 'cur_cuid_u', %s, %s, %s, %s, %s, %s, %s)",
                    [id_c, nom, ap, am, tipo, tel, email, foto],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_cuidador('D', %s, NULL, NULL, 'cur_cuid_d')", [id_c])
            else:
                conn.rollback()
                flash("Acción no válida.", "danger")
                return redirect(url_for("admin_cuidadores"))

            _, p_ok, p_msg = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_cuidadores"))

    # GET
    cuidadores = []
    try:
        conn, cur = _admin_db()
        cur.execute("""
            SELECT id_cuidador, nombre, apellido_p, COALESCE(apellido_m,'') AS apellido_m,
                   tipo_cuidador, COALESCE(telefono,'') AS telefono,
                   COALESCE(email,'') AS email, activo,
                   COALESCE(foto_perfil,'') AS foto_perfil
            FROM cuidador ORDER BY apellido_p, nombre
        """)
        cuidadores = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar cuidadores: {e}", "danger")
    return render_template("admin/cuidadores.html", cuidadores=cuidadores)


# ═══════════════════════════════════════════════════════
# ADMIN — Pacientes
# ═══════════════════════════════════════════════════════

@app.route("/admin/pacientes", methods=["GET", "POST"])
@login_requerido
@rol_requerido("admin")
def admin_pacientes():
    """CRUD de pacientes — sp_gestion_paciente ('I'/'U'/'D')."""
    if request.method == "POST":
        acc   = request.form.get("acc", "").strip().upper()
        id_p  = request.form.get("id_paciente", None, type=int)
        nom   = request.form.get("nombre",    "").strip() or None
        ap    = request.form.get("apellido_p","").strip() or None
        am    = request.form.get("apellido_m","").strip() or None
        nac   = request.form.get("fecha_nac", "").strip() or None
        curp  = request.form.get("curp",      "").strip() or None
        foto  = guardar_foto_perfil(request.files.get("foto"))

        try:
            conn, cur = _admin_db()
            cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
                        [str(session["user_id"])])
            cur.execute("BEGIN")
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_paciente('I', NULL, NULL, NULL, 'cur_pac_i', %s, %s, %s, %s, %s, %s)",
                    [nom, ap, am, nac, curp, foto],
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_paciente('U', %s, NULL, NULL, 'cur_pac_u', %s, %s, %s, %s, %s, %s)",
                    [id_p, nom, ap, am, nac, curp, foto],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_paciente('D', %s, NULL, NULL, 'cur_pac_d')", [id_p])
            else:
                conn.rollback()
                flash("Acción no válida.", "danger")
                return redirect(url_for("admin_pacientes"))

            _, p_ok, p_msg = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_pacientes"))

    # GET — SELECT directo (no hay view para listar pacientes — excepción aceptada)
    pacientes = []
    diagnosticos = []
    cuidadores   = []
    try:
        conn, cur = _admin_db()
        cur.execute("""
            SELECT id_paciente, nombre, apellido_p,
                   COALESCE(apellido_m,'') AS apellido_m,
                   COALESCE(curp,'') AS curp,
                   fecha_nacimiento, activo,
                   COALESCE(foto_perfil,'') AS foto_perfil
            FROM paciente
            ORDER BY apellido_p, nombre
        """)
        pacientes = cur.fetchall()

        cur.execute("SELECT id_diagnostico, descripcion FROM diagnostico ORDER BY descripcion")
        diagnosticos = cur.fetchall()

        cur.execute("""
            SELECT id_cuidador,
                   nombre || ' ' || apellido_p || ' ' || COALESCE(apellido_m,'') AS nombre_completo
            FROM cuidador ORDER BY apellido_p, nombre
        """)
        cuidadores = cur.fetchall()

        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar pacientes: {e}", "danger")
    return render_template("admin/pacientes.html",
                           pacientes=pacientes,
                           diagnosticos=diagnosticos,
                           cuidadores=cuidadores)


# ─── Asignaciones rápidas desde la vista de pacientes ───────────────────────

@app.route("/admin/pacientes/<int:id_pac>/asignar-diagnostico", methods=["POST"])
@login_requerido
@rol_requerido("admin")
def admin_paciente_asignar_diagnostico(id_pac):
    id_diag = request.form.get("id_diagnostico", type=int)
    if not id_diag:
        flash("Selecciona un diagnóstico.", "danger")
        return redirect(url_for("admin_pacientes"))
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_asignar_diagnostico(%s, %s, NULL, NULL, 'cur_asig_diag')", [id_pac, id_diag])
        p_ok, p_msg = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        flash(p_msg, "success" if p_ok == 1 else "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for("admin_pacientes"))


@app.route("/admin/pacientes/<int:id_pac>/asignar-cuidador", methods=["POST"])
@login_requerido
@rol_requerido("admin")
def admin_paciente_asignar_cuidador(id_pac):
    id_cuid  = request.form.get("id_cuidador", type=int)
    principal = request.form.get("principal") == "1"
    if not id_cuid:
        flash("Selecciona un cuidador.", "danger")
        return redirect(url_for("admin_pacientes"))
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, 'cur_asig_cuid', %s)",
                    [id_pac, id_cuid, principal])
        p_ok, p_msg = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        flash(p_msg, "success" if p_ok == 1 else "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for("admin_pacientes"))


# ═══════════════════════════════════════════════════════
# ADMIN — Medicamentos
# ═══════════════════════════════════════════════════════

@app.route("/admin/medicamentos", methods=["GET", "POST"])
@login_requerido
@rol_requerido("admin")
def admin_medicamentos():
    """CRUD de medicamentos — sp_gestion_medicamento ('I'/'U'/'D')."""
    if request.method == "POST":
        acc    = request.form.get("acc", "").strip().upper()
        id_m   = request.form.get("id_medicamento", None, type=int)
        nombre = request.form.get("nombre", "").strip() or None
        atc    = request.form.get("atc",    "").strip() or None
        dmax   = request.form.get("dosis_max", None, type=int)
        unidad = request.form.get("id_unidad",  None, type=int)

        try:
            conn, cur = _admin_db()
            cur.execute("BEGIN")
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_medicamento('I', NULL, NULL, NULL, 'cur_med_i', %s, %s, %s, %s)",
                    [nombre, atc, dmax, unidad],
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_medicamento('U', %s, NULL, NULL, 'cur_med_u', %s, %s, %s, %s)",
                    [id_m, nombre, atc, dmax, unidad],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_medicamento('D', %s, NULL, NULL, 'cur_med_d')", [id_m])
            else:
                conn.rollback()
                flash("Acción no válida.", "danger")
                return redirect(url_for("admin_medicamentos"))

            _, p_ok, p_msg = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_medicamentos"))

    # GET
    medicamentos = []
    unidades = []
    try:
        conn, cur = _admin_db()
        cur.execute("""
            SELECT m.id_medicamento, m.nombre_generico, m.codigo_atc,
                   m.dosis_max, u.descripcion AS unidad, m.id_unidad
            FROM medicamento m
            LEFT JOIN unidad_dosis u ON u.id_unidad = m.id_unidad
            ORDER BY m.nombre_generico
        """)
        medicamentos = cur.fetchall()
        cur.execute("SELECT id_unidad, descripcion FROM unidad_dosis ORDER BY descripcion")
        unidades = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar medicamentos: {e}", "danger")
    return render_template("admin/medicamentos.html", medicamentos=medicamentos, unidades=unidades)


# ═══════════════════════════════════════════════════════
# ADMIN — Diagnósticos
# ═══════════════════════════════════════════════════════

@app.route("/admin/diagnosticos", methods=["GET", "POST"])
@login_requerido
@rol_requerido("admin")
def admin_diagnosticos():
    """CRUD de diagnósticos — sp_gestion_diagnostico ('I'/'U')."""
    if request.method == "POST":
        acc   = request.form.get("acc",  "").strip().upper()
        id_d  = request.form.get("id_diagnostico", None, type=int)
        desc  = request.form.get("descripcion", "").strip() or None

        try:
            conn, cur = _admin_db()
            cur.execute("BEGIN")
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_diagnostico('I', NULL, NULL, NULL, 'cur_diag_i', %s)", [desc]
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_diagnostico('U', %s, NULL, NULL, 'cur_diag_u', %s)", [id_d, desc]
                )
            else:
                conn.rollback()
                flash("Acción no válida (solo I/U).", "danger")
                return redirect(url_for("admin_diagnosticos"))

            _, p_ok, p_msg = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_diagnosticos"))

    # GET — SELECT directo: no existe view para listar diagnósticos (excepción aceptada)
    diagnosticos = []
    try:
        conn, cur = _admin_db()
        cur.execute("SELECT id_diagnostico, descripcion FROM diagnostico ORDER BY descripcion")
        diagnosticos = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar diagnósticos: {e}", "danger")
    return render_template("admin/diagnosticos.html", diagnosticos=diagnosticos)


# ═══════════════════════════════════════════════════════
# ADMIN — Especialidades
# ═══════════════════════════════════════════════════════

@app.route("/admin/especialidades", methods=["GET", "POST"])
@login_requerido
@rol_requerido("admin")
def admin_especialidades():
    """CRUD de especialidades — sp_gestion_especialidad ('I'/'U')."""
    if request.method == "POST":
        acc   = request.form.get("acc", "").strip().upper()
        id_e  = request.form.get("id_especialidad", None, type=int)
        desc  = request.form.get("descripcion", "").strip() or None

        try:
            conn, cur = _admin_db()
            cur.execute("BEGIN")
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_especialidad('I', NULL, NULL, NULL, 'cur_esp_i', %s)", [desc]
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_especialidad('U', %s, NULL, NULL, 'cur_esp_u', %s)", [id_e, desc]
                )
            else:
                conn.rollback()
                flash("Acción no válida (solo I/U).", "danger")
                return redirect(url_for("admin_especialidades"))

            _, p_ok, p_msg = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_especialidades"))

    # GET — SELECT directo: no existe view para listar especialidades (excepción aceptada)
    especialidades = []
    try:
        conn, cur = _admin_db()
        cur.execute("SELECT id_especialidad, descripcion FROM especialidad ORDER BY descripcion")
        especialidades = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar especialidades: {e}", "danger")
    return render_template("admin/especialidades.html", especialidades=especialidades)


# ═══════════════════════════════════════════════════════
# ADMIN — Dispositivos IoT: Beacons
# ═══════════════════════════════════════════════════════

@app.route("/admin/dispositivos/beacon", methods=["GET", "POST"])
@login_requerido
@rol_requerido("admin")
def admin_beacon():
    """CRUD de beacons — sp_gestion_beacon ('I'/'U'/'D')."""
    if request.method == "POST":
        acc    = request.form.get("acc", "").strip().upper()
        id_b   = request.form.get("id_beacon",  None, type=int)
        uuid_  = request.form.get("uuid",       "").strip() or None
        nom    = request.form.get("nombre",     "").strip() or None
        id_pac = request.form.get("id_paciente",None, type=int)
        lat    = request.form.get("lat",        None, type=float)
        lon    = request.form.get("lon",        None, type=float)
        radio  = request.form.get("radio",      None, type=float)

        try:
            conn, cur = _admin_db()
            cur.execute("BEGIN")
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_beacon('I', NULL, NULL, NULL, 'cur_bec_i', %s, %s, %s, %s, %s, %s)",
                    [uuid_, nom, id_pac, lat, lon, radio],
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_beacon('U', %s, NULL, NULL, 'cur_bec_u', %s, %s, %s, %s, %s, %s)",
                    [id_b, uuid_, nom, id_pac, lat, lon, radio],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_beacon('D', %s, NULL, NULL, 'cur_bec_d')", [id_b])
            else:
                conn.rollback()
                flash("Acción no válida.", "danger")
                return redirect(url_for("admin_beacon"))

            _, p_ok, p_msg = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_beacon"))

    # GET
    beacons = []
    pacientes = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_dispositivos_iot('cur_iot_bec')")
        cur.execute("FETCH ALL FROM cur_iot_bec")
        # cols: tipo, id_disp, ident, nombre, asignado, activo
        beacons = [r[1:] for r in cur.fetchall() if r[0] == 'BEACON']
        conn.commit()
        # listado de pacientes (no tiene SP equivalente)
        cur.execute("""
            SELECT id_paciente,
                   nombre || ' ' || apellido_p || ' ' || COALESCE(apellido_m,'') AS nombre_completo
            FROM paciente WHERE activo = TRUE ORDER BY apellido_p, nombre
        """)
        pacientes = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar beacons: {e}", "danger")
    return render_template("admin/beacons.html", beacons=beacons, pacientes=pacientes)


# ═══════════════════════════════════════════════════════
# ADMIN — Dispositivos IoT: GPS
# ═══════════════════════════════════════════════════════

@app.route("/admin/dispositivos/gps", methods=["GET", "POST"])
@login_requerido
@rol_requerido("admin")
def admin_gps():
    """CRUD de GPS — sp_gestion_gps ('I'/'U'/'D')."""
    if request.method == "POST":
        acc    = request.form.get("acc", "").strip().upper()
        id_g   = request.form.get("id_gps",     None, type=int)
        imei   = request.form.get("imei",        "").strip() or None
        modelo = request.form.get("modelo",      "").strip() or None
        id_c   = request.form.get("id_cuidador", None, type=int)

        try:
            conn, cur = _admin_db()
            cur.execute("BEGIN")
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_gps('I', NULL, NULL, NULL, 'cur_gps_i', %s, %s, %s)",
                    [imei, modelo, id_c],
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_gps('U', %s, NULL, NULL, 'cur_gps_u', %s, %s, %s)",
                    [id_g, imei, modelo, id_c],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_gps('D', %s, NULL, NULL, 'cur_gps_d')", [id_g])
            else:
                conn.rollback()
                flash("Acción no válida.", "danger")
                return redirect(url_for("admin_gps"))

            _, p_ok, p_msg = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_gps"))

    # GET
    gps_lista = []
    cuidadores = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_dispositivos_iot('cur_iot_gps')")
        cur.execute("FETCH ALL FROM cur_iot_gps")
        # cols: tipo, id_disp, ident, nombre, asignado, activo
        gps_lista = [r[1:] for r in cur.fetchall() if r[0] == 'GPS']
        conn.commit()
        # listado de cuidadores (no tiene SP equivalente)
        cur.execute("""
            SELECT id_cuidador,
                   nombre || ' ' || apellido_p || ' ' || COALESCE(apellido_m,'') AS nombre_completo
            FROM cuidador ORDER BY apellido_p, nombre
        """)
        cuidadores = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar GPS: {e}", "danger")
    return render_template("admin/gps_dispositivos.html", gps_lista=gps_lista, cuidadores=cuidadores)


# ═══════════════════════════════════════════════════════
# ADMIN — Vista combinada de dispositivos IoT
# ═══════════════════════════════════════════════════════

@app.route("/admin/dispositivos")
@login_requerido
@rol_requerido("admin")
def admin_dispositivos():
    """Vista general de todos los dispositivos IoT."""
    dispositivos = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_dispositivos_iot('cur_iot_all')")
        cur.execute("FETCH ALL FROM cur_iot_all")
        dispositivos = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar dispositivos: {e}", "danger")
    return render_template("admin/dispositivos.html", dispositivos=dispositivos)


# ═══════════════════════════════════════════════════════
# ADMIN — Usuarios
# ═══════════════════════════════════════════════════════

@app.route("/admin/usuarios", methods=["GET", "POST"])
@login_requerido
@rol_requerido("admin")
def admin_usuarios():
    """Crear usuarios del sistema — sp_crear_usuario_admin."""
    if request.method == "POST":
        email    = request.form.get("email",    "").strip()
        password = request.form.get("password", "").strip()
        rol      = request.form.get("rol",      "").strip()   # 'medico' | 'cuidador'
        id_rol   = request.form.get("id_rol",   None, type=int)

        if not email or not password or not rol or not id_rol:
            flash("Todos los campos son obligatorios.", "danger")
            return redirect(url_for("admin_usuarios"))

        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        try:
            conn, cur = _admin_db()
            cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
                        [str(session["user_id"])])
            cur.execute("BEGIN")
            cur.execute(
                "CALL sp_crear_usuario_admin(%s, %s, %s::rol_usuario_enum, %s, NULL, NULL, 'cur_usr')",
                [email, password_hash, rol, id_rol],
            )
            p_ok, p_msg, _ = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_usuarios"))

    # GET — SELECT directo: no existe view para listar usuarios (excepción aceptada)
    usuarios = []
    try:
        conn, cur = _admin_db()
        cur.execute("""
            SELECT id_usuario, email, rol_usuario,
                   COALESCE(id_medico::TEXT, id_cuidador::TEXT) AS id_rol,
                   activo, ultimo_acceso
            FROM usuario
            ORDER BY rol_usuario, email
        """)
        usuarios = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar usuarios: {e}", "danger")
    return render_template("admin/usuarios.html", usuarios=usuarios)


# ═══════════════════════════════════════════════════════
# ADMIN — Asignaciones
# ═══════════════════════════════════════════════════════

@app.route("/admin/asignaciones/cuidador", methods=["POST"])
@login_requerido
@rol_requerido("admin")
def admin_asignar_cuidador():
    """Asigna un cuidador a un paciente — sp_asignar_cuidador."""
    id_pac  = request.form.get("id_paciente",  None, type=int)
    id_c    = request.form.get("id_cuidador",  None, type=int)
    princ   = request.form.get("principal", "false").lower() == "true"

    if not id_pac or not id_c:
        flash("Paciente y cuidador son obligatorios.", "danger")
        return redirect(url_for("admin_pacientes"))

    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_asignar_cuidador(%s, %s, NULL, NULL, 'cur_asig_c2', %s)",
            [id_pac, id_c, princ],
        )
        p_ok, p_msg = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        flash(p_msg, "success" if p_ok == 1 else "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")

    return redirect(url_for("admin_pacientes"))


@app.route("/admin/asignaciones/diagnostico", methods=["POST"])
@login_requerido
@rol_requerido("admin")
def admin_asignar_diagnostico():
    """Asigna un diagnóstico a un paciente — sp_asignar_diagnostico."""
    id_pac  = request.form.get("id_paciente",   None, type=int)
    id_diag = request.form.get("id_diagnostico",None, type=int)

    if not id_pac or not id_diag:
        flash("Paciente y diagnóstico son obligatorios.", "danger")
        return redirect(url_for("admin_pacientes"))

    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_asignar_diagnostico(%s, %s, NULL, NULL, 'cur_asig_d2')",
            [id_pac, id_diag],
        )
        p_ok, p_msg = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        flash(p_msg, "success" if p_ok == 1 else "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")

    return redirect(url_for("admin_pacientes"))


@app.route("/admin/asignaciones/especialidad", methods=["POST"])
@login_requerido
@rol_requerido("admin")
def admin_asignar_especialidad():
    """Asigna una especialidad a un médico — sp_asignar_especialidad."""
    id_med = request.form.get("id_medico",      None, type=int)
    id_esp = request.form.get("id_especialidad",None, type=int)

    if not id_med or not id_esp:
        flash("Médico y especialidad son obligatorios.", "danger")
        return redirect(url_for("admin_medicos"))

    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_asignar_especialidad(%s, %s, NULL, NULL, 'cur_asig_esp')",
            [id_med, id_esp],
        )
        p_ok, p_msg = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        flash(p_msg, "success" if p_ok == 1 else "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")

    return redirect(url_for("admin_medicos"))


# ═══════════════════════════════════════════════════════
# ADMIN — Proceso batch omisiones
# ═══════════════════════════════════════════════════════

@app.route("/admin/omisiones", methods=["POST"])
@login_requerido
@rol_requerido("admin")
def admin_omisiones():
    """Ejecuta sp_detectar_omisiones manualmente."""
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_detectar_omisiones(NULL, NULL, NULL, 'cur_omisiones')")
        p_ok, p_msg, p_total = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        flash(
            f"{p_msg} — {p_total} omisión(es) detectada(s)." if p_ok == 1 else p_msg,
            "success" if p_ok == 1 else "danger",
        )
    except Exception as e:
        flash(f"Error al ejecutar omisiones: {e}", "danger")

    return redirect(url_for("admin_dashboard"))


# ═══════════════════════════════════════════════════════
# ADMIN — Supervisión
# ═══════════════════════════════════════════════════════

@app.route("/admin/supervision")
@login_requerido
@rol_requerido("admin")
def admin_supervision():
    """Vista médico ↔ paciente."""
    filas = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_supervision('cur_superv')")
        cur.execute("FETCH ALL FROM cur_superv")
        filas = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar supervisión: {e}", "danger")
    return render_template("admin/supervision.html", filas=filas)


# ═══════════════════════════════════════════════════════
# ADMIN — Reportes de adherencia
# ═══════════════════════════════════════════════════════

@app.route("/admin/reportes/adherencia/medico")
@login_requerido
@rol_requerido("admin")
def admin_reporte_adherencia_medico():
    """Adherencia agrupada por médico."""
    dias = request.args.get("dias", 30, type=int)
    rows = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_adherencia_medicos('cur_adh_med', %s)", [dias])
        cur.execute("FETCH ALL FROM cur_adh_med")
        rows = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar reporte: {e}", "danger")
    return render_template("admin/reporte_adherencia_medico.html", rows=rows, dias=dias)


@app.route("/admin/reportes/adherencia/cuidador")
@login_requerido
@rol_requerido("admin")
def admin_reporte_adherencia_cuidador():
    """Adherencia agrupada por cuidador."""
    dias = request.args.get("dias", 30, type=int)
    rows = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_adherencia_cuidadores('cur_adh_cuid', %s)", [dias])
        cur.execute("FETCH ALL FROM cur_adh_cuid")
        rows = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar reporte: {e}", "danger")
    return render_template("admin/reporte_adherencia_cuidador.html", rows=rows, dias=dias)


# ═══════════════════════════════════════════════════════
# ADMIN — Analítica avanzada
# ═══════════════════════════════════════════════════════

@app.route("/admin/reportes/ranking")
@login_requerido
@rol_requerido("admin")
def admin_reporte_ranking():
    """Ranking de mejora de adherencia."""
    rol_filtro = request.args.get("rol", "")   # 'medico' | 'cuidador' | '' = todos
    rows = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        if rol_filtro in ("medico", "cuidador"):
            cur.execute("CALL sp_rep_ranking_mejora('cur_rank', %s)", [rol_filtro])
        else:
            cur.execute("CALL sp_rep_ranking_mejora('cur_rank')")
        cur.execute("FETCH ALL FROM cur_rank")
        rows = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar ranking: {e}", "danger")
    return render_template("admin/reporte_ranking.html", rows=rows, rol_filtro=rol_filtro)


@app.route("/admin/reportes/riesgo")
@login_requerido
@rol_requerido("admin")
def admin_reporte_riesgo():
    """Rachas de omisiones consecutivas."""
    solo_activas = request.args.get("activas", "1") == "1"
    rows = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        # p_solo_activas y p_min_dias son opcionales; filtramos en Python si es necesario
        cur.execute("CALL sp_rep_riesgo_omision('cur_riesgo', NULL, %s)", [solo_activas])
        cur.execute("FETCH ALL FROM cur_riesgo")
        rows = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar reporte de riesgo: {e}", "danger")
    return render_template("admin/reporte_riesgo.html", rows=rows, solo_activas=solo_activas)


# ═══════════════════════════════════════════════════════
# ADMIN — Bitácora, Auditoría y Accesos
# ═══════════════════════════════════════════════════════

@app.route("/admin/bitacora")
@login_requerido
@rol_requerido("admin")
def admin_bitacora():
    """Bitácora de reglas de negocio."""
    desde  = request.args.get("desde",  "")
    hasta  = request.args.get("hasta",  "")
    limite = request.args.get("limite", 200, type=int)
    rows   = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_bitacora('cur_bita', 7, %s)", [limite])
        cur.execute("FETCH ALL FROM cur_bita")
        rows = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar bitácora: {e}", "danger")
    return render_template("admin/bitacora.html", rows=rows, desde=desde, hasta=hasta, limite=limite)


@app.route("/admin/auditoria")
@login_requerido
@rol_requerido("admin")
def admin_auditoria():
    """Auditoría de cambios en tablas maestras."""
    tabla  = request.args.get("tabla",  "") or None
    limite = request.args.get("limite", 200, type=int)
    rows   = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_auditoria('cur_audit2', %s, %s)", [tabla, limite])
        cur.execute("FETCH ALL FROM cur_audit2")
        rows = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar auditoría: {e}", "danger")
    return render_template("admin/auditoria.html", rows=rows, tabla=tabla or "", limite=limite)


@app.route("/admin/accesos")
@login_requerido
@rol_requerido("admin")
def admin_accesos():
    """Log de accesos al sistema."""
    id_usr = request.args.get("id_usr", None, type=int)
    limite = request.args.get("limite", 200, type=int)
    rows   = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_log_acceso('cur_log', %s, %s)", [id_usr, limite])
        cur.execute("FETCH ALL FROM cur_log")
        rows = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar accesos: {e}", "danger")
    return render_template("admin/accesos.html", rows=rows, id_usr=id_usr, limite=limite)


@app.route("/admin/configuracion")
@login_requerido
@rol_requerido("admin")
def admin_configuracion():
    return render_template("admin/configuracion.html")


# Alias para las rutas antiguas de dispositivos individuales
@app.route("/admin/gps-dispositivos")
@login_requerido
@rol_requerido("admin")
def admin_gps_legacy():
    return redirect(url_for("admin_gps"))


@app.route("/admin/beacons")
@login_requerido
@rol_requerido("admin")
def admin_beacons_legacy():
    return redirect(url_for("admin_beacon"))

# ═══════════════════════════════════════════════════════
# MÉDICO
# ═══════════════════════════════════════════════════════

@app.route("/doctor")
@login_requerido
@rol_requerido("medico")
def doctor_dashboard():
    """Dashboard: adherencia de pacientes + alertas pendientes.

    Views: v_adherencia_paciente_por_medico, v_alertas_medico.
    SP: sp_contar_alertas.
    """
    id_medico    = session["id_rol"]
    adherencia   = []
    alertas_rec  = []
    alertas_pend = 0
    stats        = {"total_pac": 0, "bajo_80": 0, "recetas_vig": 0, "alertas_pend": 0}

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_rep_adherencia_pacientes_medico ──────────────────────────────
        # cols: id_paciente, paciente, medicamento, total, ok, tarde, omitida, pend, pct
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_adherencia_pacientes_medico('cur_adh_doc', %s, 30)", [id_medico])
        cur.execute("FETCH ALL FROM cur_adh_doc")
        rows = cur.fetchall()
        conn.commit()
        pac_map = {}
        for r in rows:
            pid, nombre, med, total, ok, tarde, omitida, pend, pct = r
            if pid not in pac_map:
                pac_map[pid] = {"id": pid, "nombre": nombre,
                                "ok": 0, "tarde": 0, "omitida": 0}
            pac_map[pid]["ok"]      += (ok      or 0)
            pac_map[pid]["tarde"]   += (tarde   or 0)
            pac_map[pid]["omitida"] += (omitida or 0)

        for p in pac_map.values():
            pasadas = p["ok"] + p["tarde"] + p["omitida"]
            p["pct"] = round(p["ok"] / pasadas * 100) if pasadas > 0 else None

        adherencia = list(pac_map.values())
        stats["total_pac"] = len(pac_map)
        stats["bajo_80"]   = sum(1 for p in adherencia if p["pct"] is not None and p["pct"] < 80)

        # ── sp_rep_alertas_medico ─────────────────────────────────────────────
        # cols: id_medico, id_alerta, prioridad, tipo, estado, timestamp_gen,
        #       paciente, medicamento, id_evento
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_alertas_medico('cur_alert_doc', %s)", [id_medico])
        cur.execute("FETCH ALL FROM cur_alert_doc")
        rows_al = cur.fetchall()
        conn.commit()
        for r in rows_al:
            _, id_al, prio, tipo, estado, ts_gen, paciente, medicamento, id_ev = r
            alertas_rec.append({
                "id": id_al, "prioridad": prio, "tipo": tipo,
                "estado": estado, "timestamp": ts_gen,
                "paciente": paciente, "medicamento": medicamento,
            })
            if estado == "Pendiente":
                alertas_pend += 1
        alertas_rec = alertas_rec[:5]

        stats["alertas_pend"] = alertas_pend

        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al cargar el dashboard: {e}", "danger")

    return render_template(
        "doctor/dashboard.html",
        adherencia=adherencia,
        alertas_rec=alertas_rec,
        stats=stats,
    )


@app.route("/doctor/pacientes")
@login_requerido
@rol_requerido("medico")
def doctor_pacientes():
    """Lista de pacientes del médico con adherencia.

    View: v_pacientes_medico.
    """
    id_medico = session["id_rol"]
    pacientes = []

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_rep_pacientes_medico ──────────────────────────────────────────
        # cols: id_medico, id_paciente, nombre, apellido_p, apellido_m,
        #       fecha_nacimiento, curp, activo, id_receta, estado_receta,
        #       fecha_inicio, fecha_fin
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_pacientes_medico('cur_pac_doc', %s)", [id_medico])
        cur.execute("FETCH ALL FROM cur_pac_doc")
        rows = cur.fetchall()
        conn.commit()
        pac_map = {}
        for r in rows:
            _, pid, nom, ap, am, fnac, curp, activo, id_rx, est_rx, f_ini, f_fin = r
            if pid not in pac_map:
                pac_map[pid] = {
                    "id":      pid,
                    "nombre":  f"{nom} {ap} {am or ''}".strip(),
                    "curp":    curp or "",
                    "activo":  activo,
                    "recetas": [],
                    "foto":    "",
                }
            if id_rx:
                pac_map[pid]["recetas"].append({
                    "id": id_rx, "estado": est_rx,
                    "ini": f_ini, "fin": f_fin,
                })

        if pac_map:
            cur.execute(
                "SELECT id_paciente, foto_perfil FROM paciente WHERE id_paciente = ANY(%s)",
                [list(pac_map.keys())],
            )
            for pid, fp in cur.fetchall():
                if pid in pac_map:
                    pac_map[pid]["foto"] = fp or ""

        pacientes = list(pac_map.values())
        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al cargar pacientes: {e}", "danger")

    return render_template("doctor/pacientes.html", pacientes=pacientes)


@app.route("/doctor/pacientes/nuevo", methods=["POST"])
@login_requerido
@rol_requerido("medico")
def doctor_paciente_nuevo():
    nom  = request.form.get("nombre",    "").strip() or None
    ap   = request.form.get("apellido_p","").strip() or None
    am   = request.form.get("apellido_m","").strip() or None
    curp = request.form.get("curp",      "").strip() or None
    nac  = request.form.get("fecha_nac", "").strip() or None
    foto = guardar_foto_perfil(request.files.get("foto"))
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
                    [str(session["user_id"])])
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_gestion_paciente('I', NULL, NULL, NULL, 'cur_pac_nuevo', %s, %s, %s, %s, %s, %s)",
            [nom, ap, am, nac, curp, foto],
        )
        _, p_ok, p_msg = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        flash(p_msg, "success" if p_ok == 1 else "danger")
    except Exception as e:
        flash(f"Error al crear paciente: {e}", "danger")
    return redirect(url_for("doctor_pacientes"))


@app.route("/doctor/pacientes/<int:id>")
@login_requerido
@rol_requerido("medico")
def doctor_paciente_perfil(id):
    """Perfil completo: datos, recetas, historial NFC y alertas.

    Views: v_perfil_paciente, v_historial_tomas, v_alertas_medico, v_recetas_paciente.
    """
    id_medico = session["id_rol"]
    paciente  = {}
    historial = []
    alertas   = []
    recetas   = {}   # keyed by id_receta

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_rep_perfil_paciente ───────────────────────────────────────────
        # cols: id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento,
        #       curp, activo, diagnosticos, cuidador_princ, medicamentos
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_perfil_paciente('cur_perfil', %s)", [id])
        cur.execute("FETCH ALL FROM cur_perfil")
        rows = cur.fetchall()
        conn.commit()
        if rows:
            r = rows[0]
            paciente = {
                "id":           r[0],
                "nombre":       f"{r[1]} {r[2]} {r[3] or ''}".strip(),
                "curp":         r[5] or "",
                "diagnosticos": r[7] or "",
                "cuidador":     r[8] or "",
                "medicamentos": r[9] or "",
                "pct":          None,
                "foto":         "",
            }
            cur.execute("SELECT foto_perfil FROM paciente WHERE id_paciente = %s", [r[0]])
            fp = cur.fetchone()
            paciente["foto"] = fp[0] or "" if fp else ""

        # ── sp_rep_adherencia_pacientes_medico → pct del paciente ────────────
        # cols: id_paciente, paciente, medicamento, total, ok, tarde, omitida, pend, pct
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_adherencia_pacientes_medico('cur_adh_perf', %s, 30)", [id_medico])
        cur.execute("FETCH ALL FROM cur_adh_perf")
        rows_adh = cur.fetchall()
        conn.commit()
        pac_adh = {}
        for r in rows_adh:
            pid, nombre, med, total, ok, tarde, omitida, pend, pct = r
            if pid not in pac_adh:
                pac_adh[pid] = {"ok": 0, "tarde": 0, "omitida": 0}
            pac_adh[pid]["ok"]      += (ok      or 0)
            pac_adh[pid]["tarde"]   += (tarde   or 0)
            pac_adh[pid]["omitida"] += (omitida or 0)

        if id in pac_adh and paciente:
            p = pac_adh[id]
            pasadas = p["ok"] + p["tarde"] + p["omitida"]
            paciente["pct"] = round(p["ok"] / pasadas * 100) if pasadas > 0 else None

        # ── sp_rep_historial_tomas ───────────────────────────────────────────
        # cols: id_paciente, id_evento, timestamp_lectura, uid_nfc, resultado,
        #       desfase_min, origen, observaciones, fecha_registro, medicamento,
        #       cuidador, distancia_metros, proximidad_valida
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_historial_tomas('cur_hist_perf', %s, 14)", [id])
        cur.execute("FETCH ALL FROM cur_hist_perf")
        rows = cur.fetchall()
        conn.commit()
        for r in rows:
            _, id_ev, ts, uid, resultado, desfase, origen, obs, fecha_reg, med, cuidador, dist, prox = r
            historial.append({
                "id_evento":   id_ev,
                "timestamp":   ts,
                "resultado":   resultado,
                "desfase_min": desfase,
                "origen":      origen,
                "medicamento": med,
                "cuidador":    cuidador,
                "proximidad":  prox,
            })

        # ── alertas del paciente via sp_rep_alertas_medico ───────────────────
        # cols: id_medico, id_alerta, prioridad, tipo, estado, timestamp_gen,
        #       paciente, medicamento, id_evento
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_alertas_medico('cur_alert_perf', %s)", [id_medico])
        cur.execute("FETCH ALL FROM cur_alert_perf")
        rows_al = cur.fetchall()
        conn.commit()
        for r in rows_al:
            _, id_al, prio, tipo, estado, ts_gen, pac_nombre, med, id_ev = r
            alertas.append({
                "id": id_al, "prioridad": prio, "tipo": tipo,
                "estado": estado, "timestamp": ts_gen, "medicamento": med,
            })

        # ── sp_rep_recetas_paciente ──────────────────────────────────────────
        # cols: id_paciente, id_receta, estado_receta, fecha_emision, fecha_inicio,
        #       fecha_fin, medico, id_receta_medicamento, nombre_generico,
        #       dosis_prescrita, unidad, frecuencia_horas, tolerancia_min, hora_primera_toma
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_recetas_paciente('cur_rx_perf', %s)", [id])
        cur.execute("FETCH ALL FROM cur_rx_perf")
        rows = cur.fetchall()
        conn.commit()
        for r in rows:
            _, id_rx, est_rx, f_emi, f_ini, f_fin, medico, id_rxm, med_nom, dosis, unidad, freq, tol, hora = r
            if id_rx not in recetas:
                recetas[id_rx] = {
                    "id": id_rx, "estado": est_rx, "emision": f_emi,
                    "inicio": f_ini, "fin": f_fin, "medico": medico, "meds": [],
                }
            if id_rxm:
                recetas[id_rx]["meds"].append({
                    "nombre": med_nom, "dosis": dosis, "unidad": unidad,
                    "frecuencia_h": freq, "tolerancia": tol, "hora": hora,
                })

        # ── sp_rep_vinculo_paciente_cuidador → cuidadores asignados ─────────
        # cols: id_paciente_cuidador, id_cuidador, es_principal, activo, cuidador
        vinculos = []
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_vinculo_paciente_cuidador('cur_vpc_perf', %s)", [id])
        cur.execute("FETCH ALL FROM cur_vpc_perf")
        vinculos = [r for r in cur.fetchall() if r[3]]  # solo activos
        conn.commit()

        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al cargar el perfil: {e}", "danger")

    return render_template(
        "doctor/paciente_perfil.html",
        id=id,
        paciente=paciente,
        historial=historial,
        alertas=alertas,
        recetas=list(recetas.values()),
        vinculos=vinculos,
    )


@app.route("/doctor/pacientes/<int:id>/grafica")
@login_requerido
@rol_requerido("medico")
def doctor_paciente_grafica(id):
    """Datos de gráfica de adherencia diaria.

    View: v_grafica_tomas.
    Devuelve JSON para consumo desde el frontend.
    """
    from flask import jsonify

    dias  = request.args.get("dias", 14, type=int)
    datos = []

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_rep_grafica_tomas ─────────────────────────────────────────────
        # cols: id_paciente, fecha, total, correctas, fuera_horario, no_tomadas, pendientes
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_grafica_tomas('cur_grafica', %s, %s)", [id, dias])
        cur.execute("FETCH ALL FROM cur_grafica")
        rows = cur.fetchall()
        conn.commit()
        for r in rows:
            _, fecha, total, correctas, fuera, no_tomadas, pendientes = r
            datos.append({
                "fecha":        str(fecha),
                "total":        total,
                "correctas":    correctas,
                "fuera_horario": fuera,
                "no_tomadas":   no_tomadas,
                "pendientes":   pendientes,
            })

        cur.close()
        conn.close()

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(datos)


@app.route("/doctor/pacientes/<int:id>/receta", methods=["POST"])
@login_requerido
@rol_requerido("medico")
def doctor_receta_crear(id):
    """Crea una receta y agrega sus medicamentos.

    SPs: sp_crear_receta, sp_agregar_receta_med (por cada medicamento).
    Medicamentos llegan como listas paralelas en el form:
      med_id[], dosis[], frecuencia[], tolerancia[], hora[]
    """
    id_medico = session["id_rol"]
    f_ini     = request.form.get("fecha_inicio", "").strip()
    f_fin     = request.form.get("fecha_fin", "").strip()
    f_emi     = request.form.get("fecha_emision", f_ini).strip()

    med_ids    = request.form.getlist("med_id[]")
    dosis_lst  = request.form.getlist("dosis[]")
    freq_lst   = request.form.getlist("frecuencia[]")
    tol_lst    = request.form.getlist("tolerancia[]")
    hora_lst   = request.form.getlist("hora[]")
    unidad_lst = request.form.getlist("unidad[]")

    if not f_ini or not f_fin:
        flash("Las fechas de inicio y fin son obligatorias.", "danger")
        return redirect(url_for("doctor_paciente_perfil", id=id))

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_crear_receta ──────────────────────────────────────────────────
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_crear_receta(NULL, NULL, NULL, 'cur_rx_crear', %s, %s, %s, %s, %s)",
            [id, id_medico, f_emi, f_ini, f_fin],
        )
        p_id_rx, p_ok, p_msg = cur.fetchone()
        conn.commit()

        if p_ok != 1:
            flash(p_msg, "danger")
            cur.close(); conn.close()
            return redirect(url_for("doctor_paciente_perfil", id=id))

        # ── sp_agregar_receta_med — uno por medicamento ──────────────────────
        for i, mid in enumerate(med_ids):
            if not mid:
                continue
            try:
                dosis  = int(dosis_lst[i])
                freq   = int(freq_lst[i])
                tol    = int(tol_lst[i])
                hora   = hora_lst[i]
                unidad = int(unidad_lst[i])
            except (IndexError, ValueError):
                continue

            cur_rxmed = f"cur_rxmed_{i}"
            cur.execute("BEGIN")
            cur.execute(
                f"CALL sp_agregar_receta_med(NULL, NULL, NULL, '{cur_rxmed}', %s, %s, %s, %s, %s, %s, %s)",
                [p_id_rx, int(mid), dosis, freq, tol, hora, unidad],
            )
            _, p_ok_m, p_msg_m = cur.fetchone()
            conn.commit()
            if p_ok_m != 1:
                flash(f"Medicamento {i+1}: {p_msg_m}", "warning")

        cur.close()
        conn.close()
        flash("Receta creada correctamente.", "success")

    except Exception as e:
        flash(f"Error al crear la receta: {e}", "danger")

    return redirect(url_for("doctor_paciente_perfil", id=id))


@app.route("/doctor/receta/<int:id_receta>/cancelar", methods=["POST"])
@login_requerido
@rol_requerido("medico")
def doctor_receta_cancelar(id_receta):
    """Cancela una receta vigente.

    SP: sp_cancelar_receta.
    """
    id_pac = request.form.get("id_paciente", type=int)

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_cancelar_receta ───────────────────────────────────────────────
        cur.execute("BEGIN")
        cur.execute("CALL sp_cancelar_receta(%s, NULL, NULL, 'cur_cancelar')", [id_receta])
        p_ok, p_msg = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al cancelar la receta: {e}", "danger")
        return redirect(url_for("doctor_paciente_perfil", id=id_pac or 0))

    if p_ok == 1:
        flash("Receta cancelada correctamente.", "success")
    else:
        flash(p_msg, "danger")

    return redirect(url_for("doctor_paciente_perfil", id=id_pac or 0))


@app.route("/doctor/alertas")
@login_requerido
@rol_requerido("medico")
def doctor_alertas():
    """Lista de alertas del médico.

    View: v_alertas_medico.
    """
    id_medico = session["id_rol"]
    solo_pend = request.args.get("filtro", "pendientes") == "pendientes"
    alertas   = []

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_rep_alertas_medico ────────────────────────────────────────────
        # cols: id_medico, id_alerta, prioridad, tipo, estado, timestamp_gen,
        #       paciente, medicamento, id_evento
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_alertas_medico('cur_alert_med', %s, %s)",
                    [id_medico, solo_pend])
        cur.execute("FETCH ALL FROM cur_alert_med")
        rows = cur.fetchall()
        conn.commit()
        for r in rows:
            _, id_al, prio, tipo, estado, ts_gen, paciente, medicamento, id_ev = r
            alertas.append({
                "id":          id_al,
                "prioridad":   prio,
                "tipo":        tipo,
                "estado":      estado,
                "timestamp":   ts_gen,
                "paciente":    paciente,
                "medicamento": medicamento,
                "id_evento":   id_ev,
            })

        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al cargar alertas: {e}", "danger")

    return render_template(
        "doctor/alertas.html",
        alertas=alertas,
        filtro="pendientes" if solo_pend else "todas",
    )


@app.route("/doctor/alertas/<int:id_alerta>/atender", methods=["POST"])
@login_requerido
@rol_requerido("medico")
def doctor_alerta_atender(id_alerta):
    """Marca una alerta como atendida.

    SP: sp_marcar_alerta_atendida.
    """
    obs = request.form.get("observaciones", "").strip() or None

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_marcar_alerta_atendida(%s, NULL, NULL, 'cur_atender_med', %s)",
            [id_alerta, obs],
        )
        p_ok, p_msg = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al atender la alerta: {e}", "danger")
        return redirect(url_for("doctor_alertas"))

    flash("Alerta marcada como atendida." if p_ok == 1 else p_msg,
          "success" if p_ok == 1 else "danger")
    return redirect(url_for("doctor_alertas"))


@app.route("/doctor/mapa")
@login_requerido
@rol_requerido("medico")
def doctor_mapa():
    """Datos GPS/Beacon de los pacientes del médico.

    View: v_mapa_medico.
    """
    id_medico = session["id_rol"]
    puntos    = []

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_rep_mapa_medico ───────────────────────────────────────────────
        # cols: id_medico, id_paciente, paciente, id_beacon, bec_lat, bec_lon,
        #       radio_metros, gps_lat, gps_lon, gps_ts, cuidador
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_mapa_medico('cur_mapa', %s)", [id_medico])
        cur.execute("FETCH ALL FROM cur_mapa")
        rows = cur.fetchall()
        conn.commit()
        for r in rows:
            _, id_pac, pac, id_bec, bec_lat, bec_lon, radio, gps_lat, gps_lon, gps_ts, cuidador = r
            puntos.append({
                "id_paciente": id_pac,
                "paciente":    pac,
                "beacon":      {"id": id_bec, "lat": float(bec_lat or 0), "lon": float(bec_lon or 0), "radio": float(radio or 5)},
                "gps":         {"lat": float(gps_lat or 0), "lon": float(gps_lon or 0), "ts": str(gps_ts or "")},
                "cuidador":    cuidador,
            })

        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al cargar el mapa: {e}", "danger")

    return render_template("proximidad/mapa.html", puntos=puntos)


@app.route("/doctor/pacientes/<int:id>/receta/nueva")
@login_requerido
@rol_requerido("medico")
def doctor_receta_nueva(id):
    return redirect(url_for("doctor_paciente_perfil", id=id))


@app.route("/doctor/pacientes/<int:id_pac>/cuidadores/<int:id_cuid>")
@login_requerido
@rol_requerido("medico")
def doctor_cuidador_detalle(id_pac, id_cuid):
    """Detalle de un cuidador asignado al paciente: datos, vínculo y horarios."""
    cuidador = {}
    vinculo  = None
    horarios = []
    try:
        conn = get_db()
        cur  = conn.cursor()

        # 1. Datos del cuidador
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_cuidador('R', %s, NULL, NULL, 'cur_cuid')", [id_cuid])
        cur.fetchone()  # descarta OUT escalares
        cur.execute("FETCH ALL FROM cur_cuid")
        row_c = cur.fetchone()
        conn.commit()
        if row_c:
            cuidador = {
                "id":       row_c[0],
                "nombre":   f"{row_c[1]} {row_c[2]} {row_c[3] or ''}".strip(),
                "tipo":     row_c[4] or "",
                "telefono": row_c[5] or "",
                "email":    row_c[6] or "",
                "activo":   row_c[7],
            }

        # 2. Vínculo con el paciente
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_vinculo_paciente_cuidador('cur_vpc_det', %s)", [id_pac])
        cur.execute("FETCH ALL FROM cur_vpc_det")
        rows_vpc = cur.fetchall()
        conn.commit()
        vinculo = next((r for r in rows_vpc if r[1] == id_cuid and r[3]), None)

        # 3. Horarios del vínculo
        if vinculo:
            id_pc = vinculo[0]
            cur.execute("BEGIN")
            cur.execute(
                "CALL sp_gestion_horario('L', NULL, NULL, NULL, 'cur_hor_det', %s)", [id_pc]
            )
            cur.fetchone()  # descarta OUT escalares
            cur.execute("FETCH ALL FROM cur_hor_det")
            horarios = cur.fetchall()
            conn.commit()

        cur.close()
        conn.close()
    except Exception as e:
        flash(f"Error al cargar el detalle: {e}", "danger")

    return render_template(
        "doctor/cuidador_detalle.html",
        id_pac=id_pac,
        cuidador=cuidador,
        vinculo=vinculo,
        horarios=horarios,
    )


@app.route("/doctor/pacientes/<int:id>/asignar-cuidador", methods=["GET"])
@login_requerido
@rol_requerido("medico")
def doctor_asignar_cuidador(id):
    """Formulario: asignar cuidador + gestionar horarios."""
    cuidadores            = []
    horarios_por_cuidador = []
    id_pc                 = None
    id_cuid_actual        = None
    pac_nombre            = ""
    try:
        conn = get_db()
        cur  = conn.cursor()

        # Nombre del paciente
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_perfil_paciente('cur_pac', %s)", [id])
        cur.fetchone()[:3]  # descarta OUT escalares
        cur.execute("FETCH ALL FROM cur_pac")
        row_pac = cur.fetchone()
        conn.commit()
        pac_nombre = f"{row_pac[1]} {row_pac[2]} {row_pac[3] or ''}".strip() if row_pac else ""

        # Cuidadores activos disponibles
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_cuidador('L', NULL, NULL, NULL, 'cur_cuids')")
        _, p_ok, p_msg = cur.fetchone()[:3]
        cur.execute("FETCH ALL FROM cur_cuids")
        rows_c = cur.fetchall()
        conn.commit()
        # cols: id_cuidador, nombre, apellido_p, apellido_m, tipo, tel, email, activo
        cuidadores = [(r[0], f"{r[1]} {r[2]}") for r in rows_c]

        # Todos los vínculos activos del paciente
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_vinculo_paciente_cuidador('cur_vpc', %s)", [id])
        cur.execute("FETCH ALL FROM cur_vpc")
        rows_vpc = cur.fetchall()
        conn.commit()
        # cols: id_paciente_cuidador[0], id_cuidador[1], es_principal[2], activo[3], cuidador[4]
        vinculos_activos = [r for r in rows_vpc if r[3]]

        # Cuidador principal (para el form de agregar turno)
        id_pc          = None
        id_cuid_actual = None
        row_principal  = next((r for r in vinculos_activos if r[2]), None)
        if row_principal:
            id_pc          = row_principal[0]
            id_cuid_actual = row_principal[1]

        # Horarios agrupados por cuidador
        horarios_por_cuidador = []
        for v in vinculos_activos:
            cur.execute("BEGIN")
            cur_name = f"cur_hor_{v[0]}"
            cur.execute(
                f"CALL sp_gestion_horario('L', NULL, NULL, NULL, '{cur_name}', %s)", [v[0]]
            )
            cur.fetchone()  # descarta OUT escalares
            cur.execute(f"FETCH ALL FROM {cur_name}")
            turnos = cur.fetchall()
            conn.commit()
            horarios_por_cuidador.append({
                "nombre":       v[4],
                "es_principal": v[2],
                "id_pac_cuid":  v[0],
                "id_cuidador":  v[1],
                "turnos":       turnos,
            })

        cur.close()
        conn.close()
    except Exception as e:
        flash(f"Error al cargar la página: {e}", "danger")

    return render_template(
        "doctor/asignar_cuidador.html",
        id=id,
        pac_nombre=pac_nombre,
        cuidadores=cuidadores,
        horarios_por_cuidador=horarios_por_cuidador,
        id_pc=id_pc,
        id_cuid_actual=id_cuid_actual,
    )


@app.route("/doctor/pacientes/<int:id>/asignar-cuidador", methods=["POST"])
@login_requerido
@rol_requerido("medico")
def doctor_asignar_cuidador_post(id):
    """Procesa la asignación de cuidador."""
    id_cuid    = request.form.get("id_cuidador", type=int)
    principal  = request.form.get("es_principal") == "1"

    if not id_cuid:
        flash("Selecciona un cuidador.", "danger")
        return redirect(url_for("doctor_asignar_cuidador", id=id))

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
                    [str(session["user_id"])])

        if principal:
            cur.execute("""
                UPDATE paciente_cuidador SET activo = FALSE
                WHERE id_paciente = %s AND es_principal = TRUE AND activo = TRUE
            """, [id])

        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_asignar_cuidador(%s, %s, NULL, NULL, 'cur_asig_c', %s)",
            [id, id_cuid, principal]
        )
        p_ok, p_msg = cur.fetchone()[:2]
        cur.execute("FETCH ALL FROM cur_asig_c")
        conn.commit()
        cur.close()
        conn.close()
        flash(p_msg, "success" if p_ok == 1 else "danger")
    except Exception as e:
        flash(f"Error al asignar cuidador: {e}", "danger")

    return redirect(url_for("doctor_asignar_cuidador", id=id))


@app.route("/doctor/pacientes/<int:id>/horario/agregar", methods=["POST"])
@login_requerido
@rol_requerido("medico")
def doctor_horario_agregar(id):
    """Agrega un turno al cuidador principal del paciente."""
    id_cuid     = request.form.get("id_cuidador", type=int)
    dia         = request.form.get("dia_semana", "").strip()
    hora_inicio = request.form.get("hora_inicio", "").strip()
    hora_fin    = request.form.get("hora_fin", "").strip()

    if not all([id_cuid, dia, hora_inicio, hora_fin]):
        flash("Completa todos los campos del turno.", "danger")
        return redirect(url_for("doctor_asignar_cuidador", id=id))

    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_vinculo_paciente_cuidador('cur_vpc2', %s)", [id])
        cur.execute("FETCH ALL FROM cur_vpc2")
        rows_vpc = cur.fetchall()
        conn.commit()
        # cols: id_paciente_cuidador, id_cuidador, es_principal, activo, cuidador
        row = next((r for r in rows_vpc if r[1] == id_cuid and r[3] == True), None)
        if not row:
            flash("No existe vínculo activo entre ese cuidador y el paciente.", "danger")
            return redirect(url_for("doctor_asignar_cuidador", id=id))
        id_pc = row[0]

        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_gestion_horario('I', NULL, NULL, NULL, 'cur_hor_i', %s, %s, %s, %s)",
            [id_pc, dia, hora_inicio, hora_fin]
        )
        p_id, p_ok, p_msg = cur.fetchone()[:3]
        cur.execute("FETCH ALL FROM cur_hor_i")
        if p_ok == 1:
            conn.commit()
            flash(p_msg, "success")
        else:
            conn.rollback()
            flash(p_msg, "danger")
        cur.close()
        conn.close()
    except Exception as e:
        flash(f"Error al agregar turno: {e}", "danger")

    return redirect(url_for("doctor_asignar_cuidador", id=id))


@app.route("/doctor/pacientes/<int:id>/horario/eliminar", methods=["POST"])
@login_requerido
@rol_requerido("medico")
def doctor_horario_eliminar(id):
    """Elimina un turno por id_horario."""
    id_horario = request.form.get("id_horario", type=int)
    if not id_horario:
        flash("ID de horario inválido.", "danger")
        return redirect(url_for("doctor_asignar_cuidador", id=id))

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_gestion_horario('D', %s, NULL, NULL, 'cur_hor_d')",
            [id_horario]
        )
        p_id, p_ok, p_msg = cur.fetchone()[:3]
        cur.execute("FETCH ALL FROM cur_hor_d")
        if p_ok == 1:
            conn.commit()
            flash(p_msg, "success")
        else:
            conn.rollback()
            flash(p_msg, "danger")
        cur.close()
        conn.close()
    except Exception as e:
        flash(f"Error al eliminar turno: {e}", "danger")

    return redirect(url_for("doctor_asignar_cuidador", id=id))


@app.route("/doctor/recetas/nueva", methods=["POST"])
@login_requerido
@rol_requerido("medico")
def doctor_receta_desde_lista():
    """Crea una receta desde la pantalla /doctor/recetas (el paciente viene en el form body)."""
    id_medico  = session["id_rol"]
    id_pac     = request.form.get("id_paciente", type=int)
    f_ini      = request.form.get("fecha_inicio", "").strip()
    f_fin      = request.form.get("fecha_fin", "").strip()
    f_emi      = request.form.get("fecha_emision", f_ini).strip()
    med_ids    = request.form.getlist("med_id[]")
    dosis_lst  = request.form.getlist("dosis[]")
    freq_lst   = request.form.getlist("frecuencia[]")
    tol_lst    = request.form.getlist("tolerancia[]")
    hora_lst   = request.form.getlist("hora[]")
    unidad_lst = request.form.getlist("unidad[]")

    if not id_pac:
        flash("Selecciona un paciente.", "danger")
        return redirect(url_for("doctor_recetas"))
    if not f_ini or not f_fin:
        flash("Las fechas de inicio y fin son obligatorias.", "danger")
        return redirect(url_for("doctor_recetas"))
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_crear_receta(NULL, NULL, NULL, 'cur_rx_lista', %s, %s, %s, %s, %s)",
            [id_pac, id_medico, f_emi, f_ini, f_fin],
        )
        p_id_rx, p_ok, p_msg = cur.fetchone()
        conn.commit()
        if p_ok != 1:
            flash(p_msg, "danger")
            cur.close(); conn.close()
            return redirect(url_for("doctor_recetas"))
        for i, mid in enumerate(med_ids):
            if not mid:
                continue
            try:
                dosis  = int(dosis_lst[i])
                freq   = int(freq_lst[i])
                tol    = int(tol_lst[i])
                hora   = hora_lst[i]
                unidad = int(unidad_lst[i])
            except (IndexError, ValueError):
                continue
            cur_rxm = f"cur_rxmed_lista_{i}"
            cur.execute("BEGIN")
            cur.execute(
                f"CALL sp_agregar_receta_med(NULL, NULL, NULL, '{cur_rxm}', %s, %s, %s, %s, %s, %s, %s)",
                [p_id_rx, int(mid), dosis, freq, tol, hora, unidad],
            )
            _, p_ok_m, p_msg_m = cur.fetchone()
            conn.commit()
            if p_ok_m != 1:
                flash(f"Medicamento {i+1}: {p_msg_m}", "warning")
        cur.close(); conn.close()
        flash("Receta creada correctamente.", "success")
    except Exception as e:
        flash(f"Error al crear la receta: {e}", "danger")
    return redirect(url_for("doctor_recetas"))


@app.route("/doctor/recetas")
@login_requerido
@rol_requerido("medico")
def doctor_recetas():
    id_medico  = session["id_rol"]
    recetas    = {}
    pacientes  = []
    medicamentos = []
    try:
        conn = get_db()
        cur  = conn.cursor()

        # cols: id_receta, pac_nombre, estado_receta, fecha_emision, fecha_inicio,
        #       fecha_fin, id_receta_medicamento, nombre_generico, dosis_prescrita,
        #       unidad, frecuencia_horas, tolerancia_min, hora_primera_toma
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_recetas_medico('cur_rx_med', %s)", [id_medico])
        cur.execute("FETCH ALL FROM cur_rx_med")
        rows = cur.fetchall()
        conn.commit()
        for row in rows:
            id_rx, pac, estado, f_emi, f_ini, f_fin, id_rxm, med_nom, dosis, unidad, freq, tol, hora = row
            if id_rx not in recetas:
                recetas[id_rx] = {
                    "id": id_rx, "pac_nombre": (pac or "").strip(),
                    "estado": estado,
                    "ini": str(f_ini), "fin": str(f_fin),
                    "meds": [],
                }
            if med_nom:
                label = f"{med_nom} {dosis}{unidad}" if dosis and unidad else med_nom
                recetas[id_rx]["meds"].append({
                    "nombre": label,
                    "freq":   f"{freq}h" if freq else "—",
                    "hora":   str(hora)[:5] if hora else "—",
                })

        # cols: id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento, curp, activo
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_paciente('L', NULL, NULL, NULL, 'cur_pacs')")
        _, p_ok, p_msg = cur.fetchone()[:3]
        cur.execute("FETCH ALL FROM cur_pacs")
        rows_p = cur.fetchall()
        conn.commit()
        pacientes = [(r[0], f"{r[1]} {r[2]} {r[3] or ''}".strip()) for r in rows_p]

        # cols: id_medicamento, nombre_generico, codigo_atc, dosis_max, activo, unidad
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_medicamento('L', NULL, NULL, NULL, 'cur_meds')")
        _, p_ok, p_msg = cur.fetchone()[:3]
        cur.execute("FETCH ALL FROM cur_meds")
        rows_m = cur.fetchall()
        conn.commit()
        medicamentos = [(r[0], r[1]) for r in rows_m]

        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar recetas: {e}", "danger")
    return render_template("doctor/recetas.html",
        recetas=list(recetas.values()),
        pacientes=pacientes,
        medicamentos=medicamentos,
    )


@app.route("/doctor/reportes")
@login_requerido
@rol_requerido("medico")
def doctor_reportes():
    id_medico = session["id_rol"]
    dias = request.args.get("dias", 30, type=int)
    pacientes_adh = []
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_rep_adherencia_pacientes_medico('cur_adh_rep', %s, %s)",
            [id_medico, dias]
        )
        cur.execute("FETCH ALL FROM cur_adh_rep")
        rows = cur.fetchall()
        conn.commit()
        cur.close()
        conn.close()

        # Agrupar por paciente sumando todos sus medicamentos
        pac_seen = {}
        for r in rows:
            pid, paciente_nom, med, total, ok, tarde, omitida, pend, pct = r
            if pid not in pac_seen:
                pac_seen[pid] = {
                    'id':      pid,
                    'nombre':  paciente_nom,
                    'total':   0,
                    'ok':      0,
                    'tarde':   0,
                    'omitida': 0,
                    'pend':    0
                }
            pac_seen[pid]['total']   += (total   or 0)
            pac_seen[pid]['ok']      += (ok      or 0)
            pac_seen[pid]['tarde']   += (tarde   or 0)
            pac_seen[pid]['omitida'] += (omitida or 0)
            pac_seen[pid]['pend']    += (pend    or 0)

        # Calcular pct correcto: solo tomas pasadas (no pendientes)
        for p in pac_seen.values():
            pasadas = p['ok'] + p['tarde'] + p['omitida']
            p['pct'] = round(p['ok'] / pasadas * 100) if pasadas > 0 else None
            pacientes_adh.append(p)

    except Exception as e:
        flash(f"Error al cargar reportes: {e}", "danger")

    return render_template(
        "doctor/reportes.html",
        pacientes_adh=pacientes_adh,
        dias=dias
    )

@app.route("/doctor/configuracion")
@login_requerido
@rol_requerido("medico")
def doctor_configuracion():
    return render_template("doctor/configuracion.html")


@app.route("/doctor/proximidad/mapa")
@login_requerido
@rol_requerido("medico")
def doctor_proximidad_mapa():
    return redirect(url_for("doctor_mapa"))


@app.route("/doctor/proximidad/historial")
@login_requerido
@rol_requerido("medico")
def doctor_proximidad_historial():
    id_medico = session["id_rol"]
    eventos   = []
    total = validos = sin_prox = 0
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT p.nombre || ' ' || p.apellido_p AS paciente,
                   vht.medicamento, vht.cuidador, vht.timestamp_lectura,
                   vht.distancia_metros, vht.proximidad_valida
            FROM v_historial_tomas vht
            JOIN paciente p ON p.id_paciente = vht.id_paciente
            WHERE vht.id_paciente IN (
                SELECT DISTINCT r.id_paciente FROM receta r WHERE r.id_medico = %s
            )
            ORDER BY vht.timestamp_lectura DESC
            LIMIT 100
        """, [id_medico])
        for r in cur.fetchall():
            pac, med, cuid, ts, dist, valida = r
            eventos.append({
                "pac":   pac,
                "med":   med or "—",
                "cuid":  cuid or "—",
                "ts":    str(ts)[:16],
                "dist":  f"{dist:.1f}m" if dist is not None else "—",
                "valida": bool(valida),
            })
        total    = len(eventos)
        validos  = sum(1 for e in eventos if e["valida"])
        sin_prox = total - validos
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar historial de proximidad: {e}", "danger")
    return render_template("proximidad/historial.html",
        eventos=eventos, total=total, validos=validos, sin_prox=sin_prox
    )

# ═══════════════════════════════════════════════════════
# CUIDADOR
# ═══════════════════════════════════════════════════════

@app.route("/cuidador")
@login_requerido
@rol_requerido("cuidador")
def cuidador_home():
    """Dashboard principal: resumen del día usando v_dashboard_cuidador."""
    id_cuidador = session["id_rol"]
    fecha_hoy   = date.today().isoformat()
    pacientes   = {}
    stats       = {"tomas_ok": 0, "alertas_pend": 0}

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_rep_dashboard_cuidador ────────────────────────────────────────
        # cols: id_cuidador, id_paciente, paciente, medicamento,
        #       fecha_hora_programada, tolerancia_min, estado_agenda,
        #       dosis_prescrita, unidad, alertas_pend
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_dashboard_cuidador('cur_dash_cuid', %s)", [id_cuidador])
        cur.execute("FETCH ALL FROM cur_dash_cuid")
        rows = cur.fetchall()
        conn.commit()

        for row in rows:
            _, pid, nombre, medicamento, fh_prog, tol, estado, dosis, unidad, al_pend = row
            if pid not in pacientes:
                pacientes[pid] = {
                    "id":          pid,
                    "nombre":      nombre,
                    "meds":        0,
                    "next":        None,
                    "alertas":     0,
                    "tomas_ok":    0,
                    "total_tomas": 0,
                }
            p = pacientes[pid]
            p["meds"]        += 1
            p["total_tomas"] += 1
            p["alertas"]      = max(p["alertas"], al_pend or 0)

            if estado in ("cumplida", "tardia"):
                p["tomas_ok"] += 1
                stats["tomas_ok"] += 1

            # Próxima toma pendiente más cercana
            if estado == "pendiente" and fh_prog:
                hora_str = fh_prog.strftime("%H:%M") if hasattr(fh_prog, "strftime") else str(fh_prog)[-8:-3]
                if p["next"] is None:
                    p["next"] = hora_str

        # ── sp_rep_badge_alertas ─────────────────────────────────────────────
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_badge_alertas('cur_badge_cuid', %s, %s)",
                    [session["user_id"], "cuidador"])
        cur.execute("FETCH ALL FROM cur_badge_cuid")
        row_al = cur.fetchone()
        stats["alertas_pend"] = row_al[0] if row_al else 0
        conn.commit()

        # ── foto_perfil de cada paciente ─────────────────────────────────────
        if pacientes:
            cur.execute(
                "SELECT id_paciente, foto_perfil FROM paciente WHERE id_paciente = ANY(%s)",
                [list(pacientes.keys())],
            )
            for pid, fp in cur.fetchall():
                if pid in pacientes:
                    pacientes[pid]["foto"] = fp or ""

        # ── GPS del cuidador (resumen para home) ─────────────────────────────
        gps_resumen = None
        cur.execute("""
            SELECT g.imei, g.modelo, g.activo,
                   u.latitud, u.longitud, u.timestamp_ubicacion
            FROM gps_imei g
            LEFT JOIN ubicacion_gps u ON u.id_gps = g.id_gps
            WHERE g.id_cuidador = %s AND g.activo = TRUE
            ORDER BY u.timestamp_ubicacion DESC NULLS LAST
            LIMIT 1
        """, [id_cuidador])
        gps_row = cur.fetchone()
        if gps_row:
            imei, modelo, activo, lat, lon, ts_ub = gps_row
            gps_resumen = {
                "imei":   imei,
                "modelo": modelo,
                "activo": activo,
                "lat":    lat,
                "lon":    lon,
                "ts":     str(ts_ub)[11:16] if ts_ub else None,
            }

        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al cargar el dashboard: {e}", "danger")
        gps_resumen = None

    lista_pacientes = list(pacientes.values())
    return render_template(
        "cuidador/home.html",
        pacientes=lista_pacientes,
        stats=stats,
        fecha_hoy=fecha_hoy,
        gps_resumen=gps_resumen,
    )


@app.route("/cuidador/paciente/<int:id>")
@login_requerido
@rol_requerido("cuidador")
def cuidador_paciente(id):
    """Agenda del día de un paciente usando v_agenda_dia_cuidador y v_perfil_paciente."""
    id_cuidador = session["id_rol"]
    fecha_hoy   = date.today().isoformat()
    agenda      = []
    paciente    = {"nombre": "", "diagnosticos": ""}

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_rep_agenda_dia_cuidador ───────────────────────────────────────
        # cols: id_cuidador, id_agenda, fecha_hora_programada, estado_agenda,
        #       tolerancia_min, id_paciente, paciente, nombre_generico,
        #       dosis_prescrita, unidad, uid_nfc
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_agenda_dia_cuidador('cur_agenda_cuid', %s)", [id_cuidador])
        cur.execute("FETCH ALL FROM cur_agenda_cuid")
        rows = cur.fetchall()
        conn.commit()

        for row in rows:
            _, id_agenda, fh_prog, estado, tol, id_pac, nombre_pac, med, dosis, unidad, uid_nfc = row
            if id_pac != id:
                continue
            paciente["nombre"] = nombre_pac
            hora_str = fh_prog.strftime("%H:%M") if hasattr(fh_prog, "strftime") else str(fh_prog)[-8:-3]
            agenda.append({
                "id_agenda":  id_agenda,
                "hora":       hora_str,
                "med":        f"{med} {dosis}{unidad}",
                "estado":     estado,
                "uid_nfc":    uid_nfc,
                "tolerancia": tol,
            })

        # ── sp_rep_perfil_paciente ───────────────────────────────────────────
        # cols: id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento,
        #       curp, activo, diagnosticos, cuidador_princ, medicamentos
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_perfil_paciente('cur_perf_cuid', %s)", [id])
        cur.execute("FETCH ALL FROM cur_perf_cuid")
        perf_rows = cur.fetchall()
        conn.commit()

        if perf_rows:
            r = perf_rows[0]
            paciente["nombre"]       = f"{r[1]} {r[2]} {r[3] or ''}".strip()
            paciente["diagnosticos"] = r[7] or ""

        cur.execute("SELECT foto_perfil FROM paciente WHERE id_paciente = %s", [id])
        fp = cur.fetchone()
        paciente["foto"] = fp[0] or "" if fp else ""

        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al cargar la agenda: {e}", "danger")

    return render_template(
        "cuidador/paciente_dashboard.html",
        id=id,
        paciente=paciente,
        agenda=agenda,
        fecha_hoy=fecha_hoy,
    )


@app.route("/cuidador/paciente/<int:id>/escaneo", methods=["GET", "POST"])
@login_requerido
@rol_requerido("cuidador")
def cuidador_escaneo(id):
    """Registra una toma NFC usando sp_registrar_toma_nfc."""
    id_cuidador = session["id_rol"]
    resultado   = None   # se rellena tras POST exitoso

    if request.method == "POST":
        uid_nfc = request.form.get("uid_nfc", "").strip()
        lat     = request.form.get("lat", "").strip()
        lon     = request.form.get("lon", "").strip()
        obs     = request.form.get("observaciones", "").strip() or None

        if not uid_nfc or not lat or not lon:
            flash("UID NFC, latitud y longitud son obligatorios.", "danger")
            return render_template("cuidador/nfc_escaneo.html", id=id, resultado=None)

        try:
            conn = get_db()
            cur  = conn.cursor()

            # ── sp_registrar_toma_nfc ────────────────────────────────────────
            # OUT: p_id_ev, p_ok, p_msg, p_res, p_prox; io_cursor entre p_prox y p_uid
            cur.execute("BEGIN")
            cur.execute(
                """CALL sp_registrar_toma_nfc(
                    NULL, NULL, NULL, NULL, NULL, 'cur_nfc',
                    %s, %s, %s, %s, NULL, %s
                )""",
                [uid_nfc, id_cuidador, float(lat), float(lon), obs],
            )
            p_id_ev, p_ok, p_msg, p_res, p_prox = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

        except Exception as e:
            flash(f"Error al registrar la toma: {e}", "danger")
            return render_template("cuidador/nfc_escaneo.html", id=id, resultado=None)

        if p_ok == 1:
            resultado = {
                "estado":    p_res,          # 'Exitoso' | 'Tardío' | 'Duplicado'
                "proximidad": p_prox,
                "id_evento": p_id_ev,
                "msg":       p_msg,
            }
        else:
            flash(p_msg, "danger")

    return render_template("cuidador/nfc_escaneo.html", id=id, resultado=resultado)


@app.route("/cuidador/alertas")
@login_requerido
@rol_requerido("cuidador")
def cuidador_alertas():
    """Lista de alertas del cuidador usando v_alertas_cuidador."""
    id_cuidador = session["id_rol"]
    solo_pend   = request.args.get("filtro", "pendientes") == "pendientes"
    alertas     = []

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_rep_alertas_cuidador ──────────────────────────────────────────
        # cols: id_cuidador, id_alerta, prioridad, tipo, estado, timestamp_gen,
        #       paciente, medicamento
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_alertas_cuidador('cur_alert_cuid', %s, %s)",
                    [id_cuidador, solo_pend])
        cur.execute("FETCH ALL FROM cur_alert_cuid")
        rows = cur.fetchall()
        conn.commit()

        for row in rows:
            _, id_al, prioridad, tipo, estado, ts_gen, paciente, medicamento = row
            alertas.append({
                "id":          id_al,
                "prioridad":   prioridad,
                "tipo":        tipo,
                "estado":      estado,
                "timestamp":   ts_gen,
                "paciente":    paciente,
                "medicamento": medicamento,
            })

        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al cargar alertas: {e}", "danger")

    return render_template(
        "cuidador/alertas.html",
        alertas=alertas,
        filtro="pendientes" if solo_pend else "todas",
    )


@app.route("/cuidador/alertas/<int:id_alerta>/atender", methods=["POST"])
@login_requerido
@rol_requerido("cuidador")
def cuidador_alerta_atender(id_alerta):
    """Marca una alerta como atendida usando sp_marcar_alerta_atendida."""
    obs = request.form.get("observaciones", "").strip() or None

    try:
        conn = get_db()
        cur  = conn.cursor()

        # ── sp_marcar_alerta_atendida ────────────────────────────────────────
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_marcar_alerta_atendida(%s, NULL, NULL, 'cur_atender_cuid', %s)",
            [id_alerta, obs],
        )
        p_ok, p_msg = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al atender la alerta: {e}", "danger")
        return redirect(url_for("cuidador_alertas"))

    if p_ok == 1:
        flash("Alerta marcada como atendida.", "success")
    else:
        flash(p_msg, "danger")

    return redirect(url_for("cuidador_alertas"))


@app.route("/cuidador/historial")
@login_requerido
@rol_requerido("cuidador")
def cuidador_historial():
    id_cuidador = session["id_rol"]
    eventos = []
    stats   = {"ok": 0, "omitidas": 0, "fuera": 0}
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT p.nombre || ' ' || p.apellido_p AS paciente,
                   vht.id_evento, vht.timestamp_lectura, vht.medicamento,
                   vht.resultado, vht.origen
            FROM v_historial_tomas vht
            JOIN paciente p ON p.id_paciente = vht.id_paciente
            WHERE vht.id_paciente IN (
                SELECT id_paciente FROM paciente_cuidador
                WHERE id_cuidador = %s AND activo = TRUE
            )
            ORDER BY vht.timestamp_lectura DESC
            LIMIT 50
        """, [id_cuidador])
        for r in cur.fetchall():
            pac, id_ev, ts, med, resultado, origen = r
            eventos.append({
                "id":        id_ev,
                "pac":       pac,
                "med":       med or "—",
                "resultado": resultado or "—",
                "time":      str(ts)[:16],
                "orig":      "NFC" if (origen or "").lower() == "nfc" else "Manual",
            })
        stats["ok"]    = sum(1 for e in eventos if e["resultado"] == "Exitoso")
        stats["fuera"] = sum(1 for e in eventos if e["resultado"] == "Tardío")
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar historial: {e}", "danger")
    return render_template("cuidador/historial_nfc.html", eventos=eventos, stats=stats)


@app.route("/cuidador/paciente/<int:id>/beacon")
@login_requerido
@rol_requerido("cuidador")
def cuidador_beacon(id):
    paciente = {"nombre": "", "iniciales": "??"}
    historial = []
    stats     = {"total": 0, "con_presencia": 0, "sin_presencia": 0}
    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("""
            SELECT nombre, apellido_p, COALESCE(apellido_m,''), foto_perfil
            FROM paciente WHERE id_paciente = %s
        """, [id])
        row = cur.fetchone()
        if row:
            nom, ap, am, fp = row
            paciente = {
                "nombre":    f"{nom} {ap} {am}".strip(),
                "iniciales": (nom[0] + ap[0]).upper(),
                "foto":      fp or "",
            }

        # sp_rep_historial_tomas cols: id_paciente, id_evento, timestamp_lectura,
        # uid_nfc, resultado, desfase_min, origen, observaciones, fecha_registro,
        # medicamento, cuidador, distancia_metros, proximidad_valida
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_historial_tomas('cur_hist_beacon', %s, 14)", [id])
        cur.execute("FETCH ALL FROM cur_hist_beacon")
        rows_h = cur.fetchall()[:20]
        conn.commit()
        for r in rows_h:
            ts = r[2]; med = r[9]; valida = r[12]; dist = r[11]
            historial.append({
                "ts":    str(ts)[11:16],
                "med":   med or "—",
                "valid": bool(valida),
                "dist":  f"{dist:.1f}" if dist is not None else None,
            })
        stats["total"]         = len(historial)
        stats["con_presencia"] = sum(1 for h in historial if h["valid"])
        stats["sin_presencia"] = stats["total"] - stats["con_presencia"]
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar detalle de beacon: {e}", "danger")
    return render_template("cuidador/patient_beacon_detail.html",
        id=id, paciente=paciente, historial=historial, stats=stats
    )


@app.route("/cuidador/mi-gps")
@login_requerido
@rol_requerido("cuidador")
def cuidador_mi_gps():
    id_cuidador     = session["id_rol"]
    gps             = None
    ultima_ubicacion = None
    posiciones      = []
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("""
            SELECT id_gps, imei, modelo, activo
            FROM gps_imei
            WHERE id_cuidador = %s
            ORDER BY activo DESC LIMIT 1
        """, [id_cuidador])
        row = cur.fetchone()
        if row:
            id_gps, imei, modelo, activo = row
            gps = {"id": id_gps, "imei": imei, "modelo": modelo, "activo": activo}
            cur.execute("""
                SELECT latitud, longitud, timestamp_ubicacion
                FROM ubicacion_gps
                WHERE id_gps = %s
                ORDER BY timestamp_ubicacion DESC LIMIT 5
            """, [id_gps])
            rows = cur.fetchall()
            for lat, lon, ts in rows:
                posiciones.append({"lat": lat, "lon": lon, "ts": str(ts)[11:16]})
            if posiciones:
                p0 = posiciones[0]
                ultima_ubicacion = {
                    "lat": p0["lat"], "lon": p0["lon"],
                    "ts": str(rows[0][2])[:16],
                }
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar GPS: {e}", "danger")
    return render_template("cuidador/mi_gps.html",
        gps=gps, ultima_ubicacion=ultima_ubicacion, posiciones=posiciones
    )

# ═══════════════════════════════════════════════════════
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
