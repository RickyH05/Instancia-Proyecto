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
    try:
        conn = get_db()
        cur  = conn.cursor()
        if session.get("rol") == "medico":
            cur.execute(
                "SELECT total_pendientes FROM v_alertas_pendientes_medico WHERE id_usuario = %s",
                [session["user_id"]]
            )
        elif session.get("rol") == "cuidador":
            cur.execute(
                "SELECT total_pendientes FROM v_alertas_pendientes_cuidador WHERE id_usuario = %s",
                [session["user_id"]]
            )
        else:
            cur.close(); conn.close()
            return {"alertas_badge": 0}
        row = cur.fetchone()
        cur.close(); conn.close()
        return {"alertas_badge": row[0] if row else 0}
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
        cur.execute("SELECT * FROM v_carga_medicos ORDER BY total_pac DESC")
        carga = cur.fetchall()

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

        cur.execute("""
            SELECT COALESCE(id_usr_app::text, usuario_db), accion, tabla, ts
            FROM v_audit_cambios
            ORDER BY ts DESC LIMIT 5
        """)
        raw_act = cur.fetchall()
        actividad_reciente = [(r[0], r[1], r[2], str(r[3])[:16]) for r in raw_act]

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
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_medico('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s)",
                    [nom, ap, am, ced, email, foto],
                )
            elif acc == "U":
                # foto=None → COALESCE en SP mantiene la foto actual
                cur.execute(
                    "CALL sp_gestion_medico('U', %s, NULL, NULL, %s, %s, %s, %s, %s, %s)",
                    [id_med, nom, ap, am, ced, email, foto],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_medico('D', %s, NULL, NULL)", [id_med])
            else:
                flash("Acción no válida.", "danger")
                return redirect(url_for("admin_medicos"))

            _, p_ok, p_msg = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_medicos"))

    # GET
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
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_cuidador('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)",
                    [nom, ap, am, tipo, tel, email, foto],
                )
            elif acc == "U":
                # foto=None → COALESCE en SP mantiene la foto actual
                cur.execute(
                    "CALL sp_gestion_cuidador('U', %s, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)",
                    [id_c, nom, ap, am, tipo, tel, email, foto],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_cuidador('D', %s, NULL, NULL)", [id_c])
            else:
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
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_paciente('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s)",
                    [nom, ap, am, nac, curp, foto],
                )
            elif acc == "U":
                # foto=None → COALESCE en SP mantiene la foto actual
                cur.execute(
                    "CALL sp_gestion_paciente('U', %s, NULL, NULL, %s, %s, %s, %s, %s, %s)",
                    [id_p, nom, ap, am, nac, curp, foto],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_paciente('D', %s, NULL, NULL)", [id_p])
            else:
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
        cur.execute("CALL sp_asignar_diagnostico(%s, %s, NULL, NULL)", [id_pac, id_diag])
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
        cur.execute("CALL sp_asignar_cuidador(%s, %s, NULL, NULL, %s)",
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
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_medicamento('I', NULL, NULL, NULL, %s, %s, %s, %s)",
                    [nombre, atc, dmax, unidad],
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_medicamento('U', %s, NULL, NULL, %s, %s, %s, %s)",
                    [id_m, nombre, atc, dmax, unidad],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_medicamento('D', %s, NULL, NULL)", [id_m])
            else:
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
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_diagnostico('I', NULL, NULL, NULL, %s)", [desc]
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_diagnostico('U', %s, NULL, NULL, %s)", [id_d, desc]
                )
            else:
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
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_especialidad('I', NULL, NULL, NULL, %s)", [desc]
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_especialidad('U', %s, NULL, NULL, %s)", [id_e, desc]
                )
            else:
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
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_beacon('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s)",
                    [uuid_, nom, id_pac, lat, lon, radio],
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_beacon('U', %s, NULL, NULL, %s, %s, %s, %s, %s, %s)",
                    [id_b, uuid_, nom, id_pac, lat, lon, radio],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_beacon('D', %s, NULL, NULL)", [id_b])
            else:
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
        cur.execute("""
            SELECT id_disp, ident, nombre, asignado, activo
            FROM v_dispositivos_iot
            WHERE tipo = 'BEACON'
            ORDER BY activo DESC, nombre
        """)
        beacons = cur.fetchall()
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
            if acc == "I":
                cur.execute(
                    "CALL sp_gestion_gps('I', NULL, NULL, NULL, %s, %s, %s)",
                    [imei, modelo, id_c],
                )
            elif acc == "U":
                cur.execute(
                    "CALL sp_gestion_gps('U', %s, NULL, NULL, %s, %s, %s)",
                    [id_g, imei, modelo, id_c],
                )
            elif acc == "D":
                cur.execute("CALL sp_gestion_gps('D', %s, NULL, NULL)", [id_g])
            else:
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
        cur.execute("""
            SELECT id_disp, ident, nombre, asignado, activo
            FROM v_dispositivos_iot
            WHERE tipo = 'GPS'
            ORDER BY activo DESC, ident
        """)
        gps_lista = cur.fetchall()
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
    """Vista general de todos los dispositivos IoT (v_dispositivos_iot)."""
    dispositivos = []
    try:
        conn, cur = _admin_db()
        cur.execute("SELECT * FROM v_dispositivos_iot ORDER BY tipo, activo DESC")
        dispositivos = cur.fetchall()
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
            cur.execute(
                "CALL sp_crear_usuario_admin(%s, %s, %s, %s, NULL, NULL)",
                [email, password_hash, rol, id_rol],
            )
            p_ok, p_msg = cur.fetchone()
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
        cur.execute(
            "CALL sp_asignar_cuidador(%s, %s, NULL, NULL, %s)",
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
        cur.execute(
            "CALL sp_asignar_diagnostico(%s, %s, NULL, NULL)",
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
        cur.execute(
            "CALL sp_asignar_especialidad(%s, %s, NULL, NULL)",
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
        cur.execute("CALL sp_detectar_omisiones(NULL, NULL, NULL)")
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
    """Vista médico ↔ paciente (v_supervision)."""
    filas = []
    try:
        conn, cur = _admin_db()
        cur.execute("SELECT * FROM v_supervision ORDER BY paciente, medico")
        filas = cur.fetchall()
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
    """Adherencia agrupada por médico (v_adherencia_medico)."""
    dias = request.args.get("dias", 30, type=int)
    rows = []
    try:
        conn, cur = _admin_db()
        cur.execute("""
            SELECT DISTINCT id_medico, medico, total, ok, tarde, omitida, pct
            FROM v_adherencia_medico
            WHERE fecha_hora_programada >= NOW() - INTERVAL '1 day' * %s
            ORDER BY pct DESC NULLS LAST
        """, [dias])
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar reporte: {e}", "danger")
    return render_template("admin/reporte_adherencia_medico.html", rows=rows, dias=dias)


@app.route("/admin/reportes/adherencia/cuidador")
@login_requerido
@rol_requerido("admin")
def admin_reporte_adherencia_cuidador():
    """Adherencia agrupada por cuidador (v_adherencia_cuidador)."""
    dias = request.args.get("dias", 30, type=int)
    rows = []
    try:
        conn, cur = _admin_db()
        cur.execute("""
            SELECT DISTINCT id_cuidador, cuidador, total, ok, tarde, omitida, pct
            FROM v_adherencia_cuidador
            WHERE fecha_hora_programada >= NOW() - INTERVAL '1 day' * %s
            ORDER BY pct DESC NULLS LAST
        """, [dias])
        rows = cur.fetchall()
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
    """Ranking de mejora de adherencia (v_ranking_mejora_adherencia)."""
    rol_filtro = request.args.get("rol", "")   # 'medico' | 'cuidador' | '' = todos
    rows = []
    try:
        conn, cur = _admin_db()
        if rol_filtro in ("medico", "cuidador"):
            cur.execute("""
                SELECT * FROM v_ranking_mejora_adherencia
                WHERE rol = %s
                ORDER BY rank_mejora
            """, [rol_filtro])
        else:
            cur.execute("SELECT * FROM v_ranking_mejora_adherencia ORDER BY rol, rank_mejora")
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar ranking: {e}", "danger")
    return render_template("admin/reporte_ranking.html", rows=rows, rol_filtro=rol_filtro)


@app.route("/admin/reportes/riesgo")
@login_requerido
@rol_requerido("admin")
def admin_reporte_riesgo():
    """Rachas de omisiones consecutivas (v_riesgo_omision_consecutiva)."""
    solo_activas = request.args.get("activas", "1") == "1"
    rows = []
    try:
        conn, cur = _admin_db()
        if solo_activas:
            cur.execute("""
                SELECT * FROM v_riesgo_omision_consecutiva
                WHERE racha_activa = TRUE AND dias_consecutivos >= 2
                ORDER BY dias_consecutivos DESC
            """)
        else:
            cur.execute("""
                SELECT * FROM v_riesgo_omision_consecutiva
                ORDER BY dias_consecutivos DESC
            """)
        rows = cur.fetchall()
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
    """Bitácora de reglas de negocio (v_bitacora_regla_negocio)."""
    desde  = request.args.get("desde",  "")
    hasta  = request.args.get("hasta",  "")
    limite = request.args.get("limite", 200, type=int)
    rows   = []
    try:
        conn, cur = _admin_db()
        if desde and hasta:
            cur.execute("""
                SELECT * FROM v_bitacora_regla_negocio
                WHERE timestamp_eval BETWEEN %s AND %s
                ORDER BY timestamp_eval DESC LIMIT %s
            """, [desde, hasta, limite])
        else:
            cur.execute("""
                SELECT * FROM v_bitacora_regla_negocio
                ORDER BY timestamp_eval DESC LIMIT %s
            """, [limite])
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar bitácora: {e}", "danger")
    return render_template("admin/bitacora.html", rows=rows, desde=desde, hasta=hasta, limite=limite)


@app.route("/admin/auditoria")
@login_requerido
@rol_requerido("admin")
def admin_auditoria():
    """Auditoría de cambios en tablas maestras (v_audit_cambios)."""
    tabla  = request.args.get("tabla",  "")
    limite = request.args.get("limite", 200, type=int)
    rows   = []
    try:
        conn, cur = _admin_db()
        if tabla:
            cur.execute("""
                SELECT * FROM v_audit_cambios
                WHERE tabla = %s
                ORDER BY ts DESC LIMIT %s
            """, [tabla, limite])
        else:
            cur.execute("SELECT * FROM v_audit_cambios ORDER BY ts DESC LIMIT %s", [limite])
        rows = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar auditoría: {e}", "danger")
    return render_template("admin/auditoria.html", rows=rows, tabla=tabla, limite=limite)


@app.route("/admin/accesos")
@login_requerido
@rol_requerido("admin")
def admin_accesos():
    """Log de accesos al sistema (v_log_acceso)."""
    id_usr = request.args.get("id_usr", None, type=int)
    limite = request.args.get("limite", 200, type=int)
    rows   = []
    try:
        conn, cur = _admin_db()
        if id_usr:
            cur.execute("""
                SELECT * FROM v_log_acceso
                WHERE id_usr = %s
                ORDER BY ts DESC LIMIT %s
            """, [id_usr, limite])
        else:
            cur.execute("SELECT * FROM v_log_acceso ORDER BY ts DESC LIMIT %s", [limite])
        rows = cur.fetchall()
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

        # ── v_adherencia_paciente_por_medico ─────────────────────────────────
        # Cols: id_paciente, paciente, medicamento, total, ok, tarde, omitida, pend, pct
        cur.execute("""
            SELECT DISTINCT id_paciente, paciente, medicamento,
                   total, ok, tarde, omitida, pend, pct
            FROM v_adherencia_paciente_por_medico
            WHERE id_medico = %s
              AND fecha_hora_programada >= NOW() - INTERVAL '14 days'
            ORDER BY paciente, medicamento
        """, [id_medico])
        rows = cur.fetchall()
        # Agrupar por paciente (la view devuelve una fila por medicamento)
        pac_map = {}
        for r in rows:
            pid, nombre, med, total, ok, tarde, omitida, pend, pct = r
            if pid not in pac_map:
                pac_map[pid] = {"id": pid, "nombre": nombre, "pct": pct or 0,
                                "recetas_vig": 0}
            else:
                # Promedio de adherencia entre medicamentos
                pac_map[pid]["pct"] = (pac_map[pid]["pct"] + (pct or 0)) / 2

        adherencia = list(pac_map.values())
        stats["total_pac"] = len(pac_map)
        stats["bajo_80"]   = sum(1 for p in adherencia if p["pct"] < 80)

        # ── v_alertas_medico — solo las 5 más recientes del dashboard ────────
        # Cols: id_alerta, prioridad, tipo, estado, timestamp_gen,
        #       paciente, medicamento, id_evento
        cur.execute("""
            SELECT id_alerta, prioridad, tipo, estado, timestamp_gen,
                   paciente, medicamento, id_evento
            FROM v_alertas_medico
            WHERE id_medico = %s
            ORDER BY timestamp_gen DESC
        """, [id_medico])
        rows_al = cur.fetchall()
        for r in rows_al:
            id_al, prio, tipo, estado, ts_gen, paciente, medicamento, id_ev = r
            alertas_rec.append({
                "id": id_al, "prioridad": prio, "tipo": tipo,
                "estado": estado, "timestamp": ts_gen,
                "paciente": paciente, "medicamento": medicamento,
            })
            if estado == "Pendiente":
                alertas_pend += 1
        alertas_rec = alertas_rec[:5]   # solo las más recientes para el widget

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

        # ── v_pacientes_medico ───────────────────────────────────────────────
        # Cols: id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento,
        #       curp, activo, id_receta, estado_receta, fecha_inicio, fecha_fin
        cur.execute("""
            SELECT id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento,
                   curp, activo, id_receta, estado_receta, fecha_inicio, fecha_fin
            FROM v_pacientes_medico
            WHERE id_medico = %s
            ORDER BY apellido_p, nombre
        """, [id_medico])
        rows = cur.fetchall()
        # Deduplicar por paciente (puede haber varias recetas)
        pac_map = {}
        for r in rows:
            pid, nom, ap, am, fnac, curp, activo, id_rx, est_rx, f_ini, f_fin = r
            if pid not in pac_map:
                pac_map[pid] = {
                    "id":        pid,
                    "nombre":    f"{nom} {ap} {am}".strip(),
                    "curp":      curp or "",
                    "activo":    activo,
                    "recetas":   [],
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
        cur.execute(
            "CALL sp_gestion_paciente('I', NULL, NULL, NULL, %s, %s, %s, %s, %s, %s)",
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

        # ── v_perfil_paciente ────────────────────────────────────────────────
        # Cols: id_paciente, nombre, apellido_p, apellido_m, fecha_nacimiento,
        #       curp, activo, diagnosticos, cuidador_princ, medicamentos
        cur.execute("SELECT * FROM v_perfil_paciente WHERE id_paciente = %s", [id])
        rows = cur.fetchall()
        if rows:
            r = rows[0]
            pct_gauge = 0
            paciente = {
                "id":           r[0],
                "nombre":       f"{r[1]} {r[2]} {r[3]}".strip(),
                "curp":         r[5] or "",
                "diagnosticos": r[7] or "",
                "cuidador":     r[8] or "",
                "medicamentos": r[9] or "",
                "pct":          pct_gauge,
                "foto":         "",
            }
            cur.execute(
                "SELECT foto_perfil FROM paciente WHERE id_paciente = %s", [r[0]]
            )
            fp = cur.fetchone()
            paciente["foto"] = fp[0] or "" if fp else ""

        # ── v_historial_tomas ────────────────────────────────────────────────
        # Cols: id_evento, timestamp_lectura, uid_nfc, resultado, desfase_min,
        #       origen, observaciones, medicamento, cuidador,
        #       distancia_metros, proximidad_valida
        cur.execute("""
            SELECT id_evento, timestamp_lectura, uid_nfc, resultado, desfase_min,
                   origen, observaciones, medicamento, cuidador,
                   distancia_metros, proximidad_valida
            FROM v_historial_tomas
            WHERE id_paciente = %s
              AND fecha_registro >= NOW() - INTERVAL '14 days'
            ORDER BY timestamp_lectura DESC
        """, [id])
        rows = cur.fetchall()
        ok_count = 0
        for r in rows:
            id_ev, ts, uid, resultado, desfase, origen, obs, med, cuidador, dist, prox = r
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
            if resultado == "Exitoso":
                ok_count += 1
        total = len(historial)
        if paciente and total:
            paciente["pct"] = round(ok_count / total * 100)

        # ── alertas directas por id_paciente ────────────────────────────────
        cur.execute("""
            SELECT a.id_alerta, a.prioridad, ta.descripcion AS tipo,
                   ea.descripcion AS estado, a.timestamp_gen,
                   med.nombre_generico AS medicamento
            FROM alerta a
            JOIN tipo_alerta   ta  ON ta.id_tipo_alerta = a.id_tipo_alerta
            JOIN estado_alerta ea  ON ea.id_estado      = a.id_estado
            JOIN receta_medicamento rm ON rm.id_receta_medicamento = a.id_receta_medicamento
            JOIN receta r2            ON r2.id_receta    = rm.id_receta
            JOIN medicamento med      ON med.id_medicamento = rm.id_medicamento
            WHERE r2.id_paciente = %s
            ORDER BY a.timestamp_gen DESC
        """, [id])
        for r in cur.fetchall():
            id_al, prio, tipo, estado, ts_gen, med = r
            alertas.append({
                "id": id_al, "prioridad": prio, "tipo": tipo,
                "estado": estado, "timestamp": ts_gen, "medicamento": med,
            })

        # ── v_recetas_paciente ───────────────────────────────────────────────
        # Cols: id_receta, estado_receta, fecha_emision, fecha_inicio, fecha_fin,
        #       medico, id_receta_medicamento, nombre_generico, dosis_prescrita,
        #       unidad, frecuencia_horas, tolerancia_min, hora_primera_toma
        cur.execute("""
            SELECT id_receta, estado_receta, fecha_emision, fecha_inicio, fecha_fin,
                   medico, id_receta_medicamento, nombre_generico, dosis_prescrita,
                   unidad, frecuencia_horas, tolerancia_min, hora_primera_toma
            FROM v_recetas_paciente
            WHERE id_paciente = %s
            ORDER BY fecha_emision DESC, nombre_generico
        """, [id])
        rows = cur.fetchall()
        for r in rows:
            id_rx, est_rx, f_emi, f_ini, f_fin, medico, id_rxm, med_nom, dosis, unidad, freq, tol, hora = r
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

        # ── v_grafica_tomas ──────────────────────────────────────────────────
        # Cols: fecha, total, correctas, fuera_horario, no_tomadas, pendientes
        cur.execute("""
            SELECT fecha, total, correctas, fuera_horario, no_tomadas, pendientes
            FROM v_grafica_tomas
            WHERE id_paciente = %s AND fecha >= CURRENT_DATE - %s
            ORDER BY fecha
        """, [id, dias])
        rows = cur.fetchall()
        for r in rows:
            fecha, total, correctas, fuera, no_tomadas, pendientes = r
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
        cur.execute(
            "CALL sp_crear_receta(NULL, NULL, NULL, %s, %s, %s, %s, %s)",
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

            cur.execute(
                "CALL sp_agregar_receta_med(NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)",
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
        cur.execute("CALL sp_cancelar_receta(%s, NULL, NULL)", [id_receta])
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

        # ── v_alertas_medico ─────────────────────────────────────────────────
        # Cols: id_alerta, prioridad, tipo, estado, timestamp_gen,
        #       paciente, medicamento, id_evento
        if solo_pend:
            cur.execute("""
                SELECT id_alerta, prioridad, tipo, estado, timestamp_gen,
                       paciente, medicamento, id_evento
                FROM v_alertas_medico
                WHERE id_medico = %s AND UPPER(estado) = 'PENDIENTE'
                ORDER BY timestamp_gen DESC
            """, [id_medico])
        else:
            cur.execute("""
                SELECT id_alerta, prioridad, tipo, estado, timestamp_gen,
                       paciente, medicamento, id_evento
                FROM v_alertas_medico
                WHERE id_medico = %s
                ORDER BY timestamp_gen DESC
            """, [id_medico])
        rows = cur.fetchall()
        for r in rows:
            id_al, prio, tipo, estado, ts_gen, paciente, medicamento, id_ev = r
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
        cur.execute(
            "CALL sp_marcar_alerta_atendida(%s, NULL, NULL, %s)",
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

        # ── v_mapa_medico ────────────────────────────────────────────────────
        # Cols: id_paciente, paciente, id_beacon, bec_lat, bec_lon,
        #       radio_metros, gps_lat, gps_lon, gps_ts, cuidador
        cur.execute("""
            SELECT id_paciente, paciente, id_beacon, bec_lat, bec_lon,
                   radio_metros, gps_lat, gps_lon, gps_ts, cuidador
            FROM v_mapa_medico
            WHERE id_medico = %s
        """, [id_medico])
        rows = cur.fetchall()
        for r in rows:
            id_pac, pac, id_bec, bec_lat, bec_lon, radio, gps_lat, gps_lon, gps_ts, cuidador = r
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


@app.route("/doctor/pacientes/<int:id>/asignar-cuidador")
@login_requerido
@rol_requerido("medico")
def doctor_asignar_cuidador(id):
    return redirect(url_for("doctor_paciente_perfil", id=id))


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
        cur.execute(
            "CALL sp_crear_receta(NULL, NULL, NULL, %s, %s, %s, %s, %s)",
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
            cur.execute(
                "CALL sp_agregar_receta_med(NULL, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)",
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
        cur.execute("""
            SELECT vr.id_receta,
                   p.nombre || ' ' || p.apellido_p || ' ' || COALESCE(p.apellido_m,'') AS pac_nombre,
                   vr.estado_receta, vr.fecha_inicio, vr.fecha_fin,
                   vr.nombre_generico, vr.dosis_prescrita, vr.unidad,
                   vr.frecuencia_horas, vr.hora_primera_toma
            FROM v_recetas_paciente vr
            JOIN receta   r ON r.id_receta   = vr.id_receta
            JOIN paciente p ON p.id_paciente = vr.id_paciente
            WHERE r.id_medico = %s
            ORDER BY vr.fecha_emision DESC, vr.id_receta, vr.nombre_generico
        """, [id_medico])
        for row in cur.fetchall():
            id_rx, pac, estado, f_ini, f_fin, med_nom, dosis, unidad, freq, hora = row
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

        cur.execute("""
            SELECT id_paciente,
                   nombre || ' ' || apellido_p || ' ' || COALESCE(apellido_m,'') AS nombre
            FROM paciente WHERE activo = TRUE ORDER BY apellido_p, nombre
        """)
        pacientes = cur.fetchall()

        cur.execute("SELECT id_medicamento, nombre_generico FROM medicamento ORDER BY nombre_generico")
        medicamentos = cur.fetchall()

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
    from datetime import datetime, timedelta
    id_medico = session["id_rol"]
    dias = request.args.get("dias", 30, type=int)
    pacientes_adh = []
    try:
        conn = get_db()
        cur  = conn.cursor()
        fecha_desde = datetime.now() - timedelta(days=dias)
        cur.execute("""
            SELECT DISTINCT id_paciente, paciente, total, ok, tarde, omitida, pend, pct
            FROM v_adherencia_paciente_por_medico
            WHERE id_medico = %s
              AND fecha_hora_programada >= %s
            ORDER BY paciente
        """, [id_medico, fecha_desde])
        pacientes_adh = cur.fetchall()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar reportes: {e}", "danger")
    return render_template("doctor/reportes.html", pacientes_adh=pacientes_adh, dias=dias)


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

        # ── v_dashboard_cuidador ─────────────────────────────────────────────
        # Columnas: id_paciente, paciente, medicamento, fecha_hora_programada,
        #           tolerancia_min, estado_agenda, dosis_prescrita, unidad, alertas_pend
        cur.execute("""
            SELECT id_paciente, paciente, medicamento, fecha_hora_programada,
                   tolerancia_min, estado_agenda, dosis_prescrita, unidad, alertas_pend
            FROM v_dashboard_cuidador
            WHERE id_cuidador = %s
              AND fecha_hora_programada::DATE = %s
            ORDER BY fecha_hora_programada
        """, [id_cuidador, fecha_hoy])
        rows = cur.fetchall()

        for row in rows:
            pid, nombre, medicamento, fh_prog, tol, estado, dosis, unidad, al_pend = row
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

        # ── v_alertas_pendientes_cuidador ────────────────────────────────────
        cur.execute(
            "SELECT total_pendientes FROM v_alertas_pendientes_cuidador WHERE id_usuario = %s",
            [session["user_id"]],
        )
        row_al = cur.fetchone()
        stats["alertas_pend"] = row_al[0] if row_al else 0

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

        # ── v_agenda_dia_cuidador ────────────────────────────────────────────
        # Columnas: id_agenda, fecha_hora_programada, estado_agenda,
        #           tolerancia_min, id_paciente, paciente, nombre_generico,
        #           dosis_prescrita, unidad, uid_nfc
        cur.execute("""
            SELECT id_agenda, fecha_hora_programada, estado_agenda,
                   tolerancia_min, id_paciente, paciente, nombre_generico,
                   dosis_prescrita, unidad, uid_nfc
            FROM v_agenda_dia_cuidador
            WHERE id_cuidador = %s
              AND fecha_hora_programada::DATE = %s
            ORDER BY fecha_hora_programada
        """, [id_cuidador, fecha_hoy])
        rows = cur.fetchall()

        for row in rows:
            id_agenda, fh_prog, estado, tol, id_pac, nombre_pac, med, dosis, unidad, uid_nfc = row
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

        # ── v_perfil_paciente — para nombre y diagnósticos ───────────────────
        # Columnas: id_paciente, nombre, apellido_p, apellido_m,
        #           fecha_nacimiento, curp, activo, diagnosticos, cuidador_princ, medicamentos
        cur.execute("SELECT * FROM v_perfil_paciente WHERE id_paciente = %s", [id])
        perf_rows = cur.fetchall()

        if perf_rows:
            r = perf_rows[0]
            paciente["nombre"]       = f"{r[1]} {r[2]} {r[3]}"
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
            # OUT: p_id_ev, p_ok, p_msg, p_res, p_prox
            cur.execute(
                """CALL sp_registrar_toma_nfc(
                    NULL, NULL, NULL, NULL, NULL,
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

        # ── v_alertas_cuidador ───────────────────────────────────────────────
        # Columnas: id_alerta, prioridad, tipo, estado, timestamp_gen,
        #           paciente, medicamento
        if solo_pend:
            cur.execute("""
                SELECT id_alerta, prioridad, tipo, estado, timestamp_gen,
                       paciente, medicamento
                FROM v_alertas_cuidador
                WHERE id_cuidador = %s AND UPPER(estado) = 'PENDIENTE'
                ORDER BY timestamp_gen DESC
            """, [id_cuidador])
        else:
            cur.execute("""
                SELECT id_alerta, prioridad, tipo, estado, timestamp_gen,
                       paciente, medicamento
                FROM v_alertas_cuidador
                WHERE id_cuidador = %s
                ORDER BY timestamp_gen DESC
            """, [id_cuidador])
        rows = cur.fetchall()

        for row in rows:
            id_al, prioridad, tipo, estado, ts_gen, paciente, medicamento = row
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
        cur.execute(
            "CALL sp_marcar_alerta_atendida(%s, NULL, NULL, %s)",
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

        cur.execute("""
            SELECT timestamp_lectura, medicamento, proximidad_valida, distancia_metros
            FROM v_historial_tomas
            WHERE id_paciente = %s
            ORDER BY timestamp_lectura DESC
            LIMIT 20
        """, [id])
        for r in cur.fetchall():
            ts, med, valida, dist = r
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
