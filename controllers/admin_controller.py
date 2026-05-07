from collections import defaultdict

import bcrypt
import psycopg

from flask import flash, redirect, render_template, request, session, url_for

from config import (
    _DB_HOST, _DB_NAME, _DB_PASS, _DB_PORT, _DB_USER,
    get_db, guardar_foto_perfil,
)


def _admin_db():
    """Abre conexión y cursor. Devuelve (conn, cur)."""
    conn = get_db()
    cur  = conn.cursor()
    return conn, cur


def admin_dashboard():
    """Vista general: carga de médicos + conteos reales para stat cards."""
    carga = []
    total_medicos = total_cuidadores = total_pacientes = total_medicamentos = 0
    total_gps = total_beacons = total_alertas = 0
    actividad_reciente = []
    try:
        conn, cur = _admin_db()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_carga_medicos('cur_carga')")
        cur.execute("FETCH ALL FROM cur_carga")
        carga = cur.fetchall()
        conn.commit()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_conteos_admin('cur_conteos')")
        cur.execute("FETCH ALL FROM cur_conteos")
        row = cur.fetchone()
        conn.commit()
        total_medicos            = row[0]
        total_cuidadores         = row[1]
        total_pacientes          = row[2]
        total_medicamentos       = row[3]
        total_gps                = row[4]
        total_beacons            = row[5]
        total_alertas            = row[6]

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_auditoria('cur_audit', NULL, 5)")
        cur.execute("FETCH ALL FROM cur_audit")
        raw_act = cur.fetchall()
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

            _row = cur.fetchone()
            p_ok, p_msg = _row[1], _row[2]
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_medicos"))

    medicos = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_medico('L', NULL, NULL, NULL, 'cur_med_l')")
        _, p_ok, p_msg, _ = cur.fetchone()
        cur.execute("FETCH ALL FROM cur_med_l")
        medicos = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar médicos: {e}", "danger")
    return render_template("admin/medicos.html", medicos=medicos)


def admin_cuidadores():
    """CRUD de cuidadores — sp_gestion_cuidador ('I'/'U'/'D')."""
    if request.method == "POST":
        acc    = request.form.get("acc", "").strip().upper()
        id_c   = request.form.get("id_cuidador", None, type=int)
        nom    = request.form.get("nombre",    "").strip() or None
        ap     = request.form.get("apellido_p","").strip() or None
        am     = request.form.get("apellido_m","").strip() or None
        tipo   = request.form.get("tipo",      "").strip() or None
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

            _row = cur.fetchone()
            p_ok, p_msg = _row[1], _row[2]
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_cuidadores"))

    cuidadores = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_cuidador('L', NULL, NULL, NULL, 'cur_cuid_l')")
        _, p_ok, p_msg, _ = cur.fetchone()
        cur.execute("FETCH ALL FROM cur_cuid_l")
        cuidadores = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar cuidadores: {e}", "danger")
    return render_template("admin/cuidadores.html", cuidadores=cuidadores)


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

            _, p_ok, p_msg = cur.fetchone()[:3]
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            conn.rollback()
            error_msg = str(e)
            if 'curp_check' in error_msg or 'curp' in error_msg.lower():
                flash('El CURP ingresado no tiene el formato correcto. '
                      'Debe tener exactamente 18 caracteres con el formato oficial mexicano. '
                      'Ejemplo válido: GOMC900101HDFLRR09', 'danger')
            elif 'unique' in error_msg.lower() or 'duplicate' in error_msg.lower():
                flash('Ya existe un paciente registrado con ese CURP.', 'danger')
            else:
                flash(f'Error al guardar: {error_msg}', 'danger')

        return redirect(url_for("admin_pacientes"))

    pacientes = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_paciente('L', NULL, NULL, NULL, 'cur_pac_l')")
        cur.execute("FETCH ALL FROM cur_pac_l")
        pacientes = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar pacientes: {e}", "danger")
    return render_template("admin/pacientes.html", pacientes=pacientes)


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

            _row = cur.fetchone()
            p_ok, p_msg = _row[1], _row[2]
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_medicamentos"))

    medicamentos = []
    unidades = []
    try:
        conn, cur = _admin_db()

        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_medicamento('L', NULL, NULL, NULL, 'cur_med_l')")
        _, p_ok, p_msg, _ = cur.fetchone()
        cur.execute("FETCH ALL FROM cur_med_l")
        medicamentos = cur.fetchall()
        conn.commit()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_unidades_dosis('cur_uni')")
        cur.execute("FETCH ALL FROM cur_uni")
        unidades = cur.fetchall()
        conn.commit()

        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar medicamentos: {e}", "danger")
    return render_template("admin/medicamentos.html", medicamentos=medicamentos, unidades=unidades)


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

            _row = cur.fetchone()
            p_ok, p_msg = _row[1], _row[2]
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_diagnosticos"))

    diagnosticos = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_diagnostico('L', NULL, NULL, NULL, 'cur_diag_l')")
        _, p_ok, p_msg, _ = cur.fetchone()
        cur.execute("FETCH ALL FROM cur_diag_l")
        diagnosticos = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar diagnósticos: {e}", "danger")
    return render_template("admin/diagnosticos.html", diagnosticos=diagnosticos)


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

            _row = cur.fetchone()
            p_ok, p_msg = _row[1], _row[2]
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_especialidades"))

    especialidades = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_especialidad('L', NULL, NULL, NULL, 'cur_esp_l')")
        _, p_ok, p_msg, _ = cur.fetchone()
        cur.execute("FETCH ALL FROM cur_esp_l")
        especialidades = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar especialidades: {e}", "danger")
    return render_template("admin/especialidades.html", especialidades=especialidades)


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

            _row = cur.fetchone()
            p_ok, p_msg = _row[1], _row[2]
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_beacon"))

    beacons = []
    pacientes = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_dispositivos_iot('cur_iot_bec')")
        cur.execute("FETCH ALL FROM cur_iot_bec")
        beacons = [r[1:] for r in cur.fetchall() if r[0] == 'BEACON']
        conn.commit()
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_paciente('L', NULL, NULL, NULL, 'cur_pac_l')")
        _, p_ok, p_msg, _ = cur.fetchone()
        cur.execute("FETCH ALL FROM cur_pac_l")
        pacientes = [(r[0], f"{r[1]} {r[2]} {r[3] or ''}".strip()) for r in cur.fetchall()]
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar beacons: {e}", "danger")
    return render_template("admin/beacons.html", beacons=beacons, pacientes=pacientes)


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

            _row = cur.fetchone()
            p_ok, p_msg = _row[1], _row[2]
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_gps"))

    gps_lista = []
    cuidadores = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_dispositivos_iot('cur_iot_gps')")
        cur.execute("FETCH ALL FROM cur_iot_gps")
        gps_lista = [r[1:] for r in cur.fetchall() if r[0] == 'GPS']
        conn.commit()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_lista_cuidadores('cur_cuid')")
        cur.execute("FETCH ALL FROM cur_cuid")
        cuidadores = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar GPS: {e}", "danger")
    return render_template("admin/gps_dispositivos.html", gps_lista=gps_lista, cuidadores=cuidadores)


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


def admin_usuarios():
    if request.method == "POST":
        email    = request.form.get("email",    "").strip()
        password = request.form.get("password", "").strip()
        rol      = request.form.get("rol",      "").strip()
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
                "CALL sp_crear_usuario_admin(%s, %s, %s::rol_usuario_enum, %s, NULL, NULL, 'cur_cu')",
                [email, password_hash, rol, id_rol],
            )
            p_ok, p_msg, _ = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_usuarios"))

    usuarios   = []
    medicos    = []
    cuidadores = []
    try:
        conn, cur = _admin_db()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_lista_usuarios('cur_lu')")
        cur.execute("FETCH ALL FROM cur_lu")
        usuarios = cur.fetchall()
        conn.commit()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_carga_medicos('cur_med')")
        cur.execute("FETCH ALL FROM cur_med")
        medicos = cur.fetchall()
        conn.commit()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_lista_cuidadores('cur_cuid')")
        cur.execute("FETCH ALL FROM cur_cuid")
        cuidadores = cur.fetchall()
        conn.commit()

        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar usuarios: {e}", "danger")
    return render_template("admin/usuarios.html",
                           usuarios=usuarios, medicos=medicos, cuidadores=cuidadores)


def admin_usuario_desactivar(id_usr):
    try:
        conn, cur = _admin_db()
        cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
                    [str(session["user_id"])])
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_usuario('D', %s, NULL, NULL, 'cur_du')", [id_usr])
        p_ok, p_msg = cur.fetchone()[:2]
        conn.commit()
        cur.close(); conn.close()
        flash(p_msg, "success" if p_ok == 1 else "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for("admin_usuarios"))


def admin_usuario_activar(id_usr):
    try:
        conn, cur = _admin_db()
        cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
                    [str(session["user_id"])])
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_usuario('A', %s, NULL, NULL, 'cur_au')", [id_usr])
        p_ok, p_msg = cur.fetchone()[:2]
        conn.commit()
        cur.close(); conn.close()
        flash(p_msg, "success" if p_ok == 1 else "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for("admin_usuarios"))


def admin_usuario_editar(id_usr):
    if request.method == "POST":
        email    = request.form.get("email", "").strip() or None
        password = request.form.get("password", "").strip()
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode() if password else None

        try:
            conn, cur = _admin_db()
            cur.execute("SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
                        [str(session["user_id"])])
            cur.execute("BEGIN")
            cur.execute(
                "CALL sp_gestion_usuario('U', %s, NULL, NULL, 'cur_eu', %s, %s)",
                [id_usr, email, password_hash],
            )
            p_ok, p_msg = cur.fetchone()[:2]
            conn.commit()
            cur.close(); conn.close()
            flash(p_msg, "success" if p_ok == 1 else "danger")
        except Exception as e:
            flash(f"Error: {e}", "danger")

        return redirect(url_for("admin_usuarios"))

    usuario    = None
    medicos    = []
    cuidadores = []
    try:
        conn, cur = _admin_db()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_lista_usuarios('cur_lu2')")
        cur.execute("FETCH ALL FROM cur_lu2")
        for row in cur.fetchall():
            if row[0] == id_usr:
                usuario = row
                break
        conn.commit()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_carga_medicos('cur_med2')")
        cur.execute("FETCH ALL FROM cur_med2")
        medicos = cur.fetchall()
        conn.commit()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_lista_cuidadores('cur_cuid2')")
        cur.execute("FETCH ALL FROM cur_cuid2")
        cuidadores = cur.fetchall()
        conn.commit()

        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar usuario: {e}", "danger")

    if not usuario:
        flash("Usuario no encontrado.", "danger")
        return redirect(url_for("admin_usuarios"))

    return render_template("admin/usuario_editar.html",
                           usuario=usuario, medicos=medicos, cuidadores=cuidadores)


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
        _row = cur.fetchone()
        p_ok, p_msg = _row[1], _row[2]
        conn.commit()
        cur.close(); conn.close()
        flash(p_msg, "success" if p_ok == 1 else "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")

    return redirect(url_for("admin_medicos"))


def admin_omisiones():
    """Ejecuta sp_detectar_omisiones manualmente."""
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_detectar_omisiones(NULL, NULL, NULL, 'cur_omisiones')")
        p_ok, p_msg, p_total, _ = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        flash(
            f"{p_msg} — {p_total} omisión(es) detectada(s)." if p_ok == 1 else p_msg,
            "success" if p_ok == 1 else "danger",
        )
    except Exception as e:
        flash(f"Error al ejecutar omisiones: {e}", "danger")

    return redirect(url_for("admin_dashboard"))


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


def admin_supervision_detalle():
    pacientes = {}
    medicos = []
    cuidadores = []
    try:
        conn, cur = _admin_db()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_supervision('cur_sv')")
        cur.execute("FETCH ALL FROM cur_sv")
        for f in cur.fetchall():
            id_pac = f[0]
            if id_pac not in pacientes:
                pacientes[id_pac] = {'nombre': f[1], 'medicos': set(), 'recetas_vigentes': 0}
            if f[3]:
                pacientes[id_pac]['medicos'].add(f[3])
            if f[5] == 'vigente':
                pacientes[id_pac]['recetas_vigentes'] += 1
        conn.commit()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_carga_medicos('cur_med')")
        cur.execute("FETCH ALL FROM cur_med")
        medicos = cur.fetchall()
        conn.commit()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_lista_cuidadores('cur_cuid')")
        cur.execute("FETCH ALL FROM cur_cuid")
        cuidadores = cur.fetchall()
        conn.commit()

        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar supervisión ampliada: {e}", "danger")
    return render_template("admin/supervision_detalle.html",
                           pacientes=pacientes, medicos=medicos, cuidadores=cuidadores)


def admin_sup_paciente(id_pac):
    paciente_nombre = ""
    medico = ""
    cuidadores = []
    recetas = {}
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_detalle_paciente_admin('cur_dp', %s)", [id_pac])
        cur.execute("FETCH ALL FROM cur_dp")
        filas = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()

        seen_cuidadores = {}
        for f in filas:
            if not paciente_nombre:
                paciente_nombre = f[1]
            if not medico and f[3]:
                medico = f[3]
            id_cuid = f[4]
            if id_cuid and id_cuid not in seen_cuidadores:
                seen_cuidadores[id_cuid] = {'nombre': f[5], 'es_principal': f[6]}
            id_rec = f[7]
            if id_rec:
                if id_rec not in recetas:
                    recetas[id_rec] = {'estado': f[8], 'fecha_inicio': f[9],
                                       'fecha_fin': f[10], 'meds': []}
                if f[11]:
                    med_str = f"{f[11]} {f[12]} {f[13]} c/{f[14]}h"
                    if med_str not in recetas[id_rec]['meds']:
                        recetas[id_rec]['meds'].append(med_str)
        cuidadores = list(seen_cuidadores.values())
    except Exception as e:
        flash(f"Error al cargar detalle paciente: {e}", "danger")
    return render_template("admin/sup_paciente.html",
                           paciente_nombre=paciente_nombre, medico=medico,
                           cuidadores=cuidadores, recetas=recetas)


def admin_sup_medico(id_med):
    medico_nombre = ""
    pacientes = {}
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_pacientes_medico_admin('cur_dm', %s)", [id_med])
        cur.execute("FETCH ALL FROM cur_dm")
        filas = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()

        for f in filas:
            if not medico_nombre:
                medico_nombre = f[1]
            id_pac = f[2]
            if id_pac not in pacientes:
                pacientes[id_pac] = {'nombre': f[3], 'cuidador': f[4] or 'Sin cuidador', 'recetas': {}}
            id_rec = f[5]
            if id_rec:
                if id_rec not in pacientes[id_pac]['recetas']:
                    pacientes[id_pac]['recetas'][id_rec] = {'estado': f[6], 'meds': []}
                if f[9]:
                    med_str = f"{f[9]} {f[10]} {f[11]} c/{f[12]}h"
                    if med_str not in pacientes[id_pac]['recetas'][id_rec]['meds']:
                        pacientes[id_pac]['recetas'][id_rec]['meds'].append(med_str)
    except Exception as e:
        flash(f"Error al cargar detalle médico: {e}", "danger")
    return render_template("admin/sup_medico.html",
                           medico=medico_nombre, pacientes=pacientes)


def admin_sup_cuidador(id_cuid):
    cuidador_nombre = ""
    pacientes = {}
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_pacientes_cuidador_admin('cur_dc', %s)", [id_cuid])
        cur.execute("FETCH ALL FROM cur_dc")
        filas = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()

        for f in filas:
            if not cuidador_nombre:
                cuidador_nombre = f[1]
            id_pac = f[2]
            if id_pac not in pacientes:
                pacientes[id_pac] = {
                    'nombre': f[3], 'es_principal': f[4],
                    'medico': f[5], 'medicamentos': [], 'estado_receta': f[7]
                }
            if f[8]:
                med_str = f"{f[8]} {f[9]} {f[10]} c/{f[11]}h"
                if med_str not in pacientes[id_pac]['medicamentos']:
                    pacientes[id_pac]['medicamentos'].append(med_str)
    except Exception as e:
        flash(f"Error al cargar detalle cuidador: {e}", "danger")
    return render_template("admin/sup_cuidador.html",
                           cuidador=cuidador_nombre, pacientes=pacientes)


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


def admin_reporte_ranking():
    """Ranking de mejora de adherencia."""
    rol_filtro = request.args.get("rol", "")
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


def admin_reporte_riesgo():
    """Rachas de omisiones consecutivas."""
    solo_activas = request.args.get("activas", "1") == "1"
    rows = []
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_riesgo_omision('cur_riesgo', NULL, %s)", [solo_activas])
        cur.execute("FETCH ALL FROM cur_riesgo")
        rows = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar reporte de riesgo: {e}", "danger")
    return render_template("admin/reporte_riesgo.html", rows=rows, solo_activas=solo_activas)


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


def admin_auditoria():
    """Auditoría de cambios en tablas maestras."""
    tabla  = request.args.get("tabla",  "") or None
    limite = request.args.get("limite", 200, type=int)
    rows   = []
    usuarios_map = {}
    try:
        conn, cur = _admin_db()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_lista_usuarios('cur_usr_audit')")
        cur.execute("FETCH ALL FROM cur_usr_audit")
        for u in cur.fetchall():
            if u[0] and u[5]:
                usuarios_map[u[0]] = u[5]
        conn.commit()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_auditoria('cur_audit2', %s, %s)", [tabla, limite])
        cur.execute("FETCH ALL FROM cur_audit2")
        raw = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
        rows = [
            {
                "id":           r[0],
                "tabla":        r[1],
                "id_reg":       r[2],
                "accion":       r[3],
                "campo":        r[4],
                "val_antes":    r[5],
                "val_despues":  r[6],
                "usuario_db":   r[7],
                "id_usr_app":   r[8],
                "ts":           r[9],
                "nombre_usuario": usuarios_map.get(r[8], r[7] or "Sistema"),
            }
            for r in raw
        ]
    except Exception as e:
        flash(f"Error al cargar auditoría: {e}", "danger")
    return render_template("admin/auditoria.html", rows=rows, tabla=tabla or "", limite=limite)


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


def admin_configuracion():
    return render_template("admin/configuracion.html")


def admin_gps_legacy():
    return redirect(url_for("admin_gps"))


def admin_beacons_legacy():
    return redirect(url_for("admin_beacon"))


def admin_reporte_ranking_mejora():
    rol_filtro = request.args.get("rol", "")
    filas = []
    try:
        conn = get_db()
        cur  = conn.cursor()
        p_rol = rol_filtro if rol_filtro else None
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_ranking_mejora('cur_rank', %s)", [p_rol])
        cur.execute("FETCH ALL FROM cur_rank")
        rows = cur.fetchall()
        conn.commit()
        for r in rows:
            filas.append({
                "rol":               r[0],
                "id_persona":        r[1],
                "nombre":            r[2],
                "pct_anterior":      float(r[3]) if r[3] is not None else 0,
                "pct_reciente":      float(r[4]) if r[4] is not None else 0,
                "delta_pct":         float(r[5]) if r[5] is not None else 0,
                "rank_mejora":       int(r[6] or 0),
                "dense_rank_mejora": int(r[7] or 0),
                "cuartil_mejora":    int(r[8] or 0),
                "clasificacion":     str(r[9] or ""),
            })
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar ranking: {e}", "danger")
    return render_template("admin/reporte_ranking_mejora.html",
                           filas=filas,
                           rol_filtro=rol_filtro)


def admin_reporte_tendencia_global():
    dias = request.args.get("dias", 30, type=int)
    if not dias or dias <= 0:
        dias = 30
    filas = []
    clasificacion = defaultdict(list)
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_tendencia_adherencia('cur_tg', NULL, %s)", [dias])
        cur.execute("FETCH ALL FROM cur_tg")
        rows = cur.fetchall()
        conn.commit()
        for r in rows:
            filas.append({
                "id_paciente": r[0],
                "paciente":    r[1],
                "fecha":       str(r[2]),
                "pct_dia":     float(r[7]) if r[7] is not None else None,
                "mov7d":       float(r[8]) if r[8] is not None else None,
                "tendencia":   str(r[9] or ""),
            })

        ultimas_tendencias = {}
        for r in rows:
            id_pac = r[0]
            fecha  = r[2]
            if id_pac not in ultimas_tendencias or fecha > ultimas_tendencias[id_pac]["fecha"]:
                ultimas_tendencias[id_pac] = {
                    "fecha":     fecha,
                    "nombre":    r[1],
                    "tendencia": str(r[9] or ""),
                }
        for pac in ultimas_tendencias.values():
            clasificacion[pac["tendencia"]].append(pac["nombre"])

        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar tendencia global: {e}", "danger")
    return render_template("admin/reporte_tendencia_global.html",
                           filas=filas,
                           clasificacion=clasificacion,
                           dias=dias)


def detectar_omisiones():
    conn = None
    try:
        conn = psycopg.connect(
            host=_DB_HOST,
            dbname=_DB_NAME,
            user=_DB_USER,
            password=_DB_PASS,
            port=_DB_PORT,
        )
        with conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("CALL sp_detectar_omisiones(NULL, NULL, NULL, 'cur_om')")
            p_ok, p_msg, p_total = cur.fetchone()[:3]
            cur.execute("FETCH ALL FROM cur_om")
            conn.commit()
        print(f"[scheduler] omisiones detectadas={p_total} | {p_msg}")
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[scheduler] ERROR detectar_omisiones: {e}")
    finally:
        if conn:
            conn.close()
