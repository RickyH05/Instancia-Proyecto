import atexit

from flask import Flask, jsonify, redirect, request, session, url_for
from apscheduler.schedulers.background import BackgroundScheduler

from config import _SECRET_KEY, get_db

import controllers.auth_controller   as auth
import controllers.admin_controller  as admin
import controllers.doctor_controller as doctor
import controllers.cuidador_controller as cuidador

app = Flask(__name__)
app.jinja_env.filters['enumerate'] = enumerate
app.jinja_env.globals['enumerate'] = enumerate
app.secret_key = _SECRET_KEY


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


# ─── Auth ───────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def login():
    return auth.login()

@app.route("/logout")
def logout():
    return auth.logout()

@app.route("/dashboard")
def dashboard():
    return auth.dashboard()


# ─── Admin ──────────────────────────────────────────────────────────────────

@app.route("/admin")
def admin_dashboard():
    return admin.admin_dashboard()

@app.route("/admin/medicos", methods=["GET", "POST"])
def admin_medicos():
    return admin.admin_medicos()

@app.route("/admin/cuidadores", methods=["GET", "POST"])
def admin_cuidadores():
    return admin.admin_cuidadores()

@app.route("/admin/pacientes", methods=["GET", "POST"])
def admin_pacientes():
    return admin.admin_pacientes()

@app.route("/admin/medicamentos", methods=["GET", "POST"])
def admin_medicamentos():
    return admin.admin_medicamentos()

@app.route("/admin/diagnosticos", methods=["GET", "POST"])
def admin_diagnosticos():
    return admin.admin_diagnosticos()

@app.route("/admin/especialidades", methods=["GET", "POST"])
def admin_especialidades():
    return admin.admin_especialidades()

@app.route("/admin/dispositivos/beacon", methods=["GET", "POST"])
def admin_beacon():
    return admin.admin_beacon()

@app.route("/admin/dispositivos/gps", methods=["GET", "POST"])
def admin_gps():
    return admin.admin_gps()

@app.route("/admin/dispositivos")
def admin_dispositivos():
    return admin.admin_dispositivos()

@app.route("/admin/usuarios", methods=["GET", "POST"])
def admin_usuarios():
    return admin.admin_usuarios()

@app.route("/admin/usuarios/<int:id_usr>/desactivar", methods=["POST"])
def admin_usuario_desactivar(id_usr):
    return admin.admin_usuario_desactivar(id_usr)

@app.route("/admin/usuarios/<int:id_usr>/activar", methods=["POST"])
def admin_usuario_activar(id_usr):
    return admin.admin_usuario_activar(id_usr)

@app.route("/admin/usuarios/<int:id_usr>/editar", methods=["GET", "POST"])
def admin_usuario_editar(id_usr):
    return admin.admin_usuario_editar(id_usr)

@app.route("/admin/asignaciones/especialidad", methods=["POST"])
def admin_asignar_especialidad():
    return admin.admin_asignar_especialidad()

@app.route("/admin/omisiones", methods=["POST"])
def admin_omisiones():
    return admin.admin_omisiones()

@app.route("/admin/supervision")
def admin_supervision():
    return admin.admin_supervision()

@app.route("/admin/supervision/detalle")
def admin_supervision_detalle():
    return admin.admin_supervision_detalle()

@app.route("/admin/supervision/detalle/paciente/<int:id_pac>")
def admin_sup_paciente(id_pac):
    return admin.admin_sup_paciente(id_pac)

@app.route("/admin/supervision/detalle/medico/<int:id_med>")
def admin_sup_medico(id_med):
    return admin.admin_sup_medico(id_med)

@app.route("/admin/supervision/detalle/cuidador/<int:id_cuid>")
def admin_sup_cuidador(id_cuid):
    return admin.admin_sup_cuidador(id_cuid)

@app.route("/admin/reportes/adherencia/medico")
def admin_reporte_adherencia_medico():
    return admin.admin_reporte_adherencia_medico()

@app.route("/admin/reportes/adherencia/cuidador")
def admin_reporte_adherencia_cuidador():
    return admin.admin_reporte_adherencia_cuidador()

@app.route("/admin/reportes/ranking")
def admin_reporte_ranking():
    return admin.admin_reporte_ranking()

@app.route("/admin/reportes/riesgo")
def admin_reporte_riesgo():
    return admin.admin_reporte_riesgo()

@app.route("/admin/bitacora")
def admin_bitacora():
    return admin.admin_bitacora()

@app.route("/admin/auditoria")
def admin_auditoria():
    return admin.admin_auditoria()

@app.route("/admin/accesos")
def admin_accesos():
    return admin.admin_accesos()

@app.route("/admin/configuracion")
def admin_configuracion():
    return admin.admin_configuracion()

@app.route("/admin/gps-dispositivos")
def admin_gps_legacy():
    return admin.admin_gps_legacy()

@app.route("/admin/beacons")
def admin_beacons_legacy():
    return admin.admin_beacons_legacy()

@app.route("/admin/reporte-ranking-mejora")
def admin_reporte_ranking_mejora():
    return admin.admin_reporte_ranking_mejora()

@app.route("/admin/reporte-tendencia-global")
def admin_reporte_tendencia_global():
    return admin.admin_reporte_tendencia_global()


# ─── Doctor ─────────────────────────────────────────────────────────────────

@app.route("/doctor")
def doctor_dashboard():
    return doctor.doctor_dashboard()

@app.route("/doctor/pacientes")
def doctor_pacientes():
    return doctor.doctor_pacientes()

@app.route("/doctor/pacientes/nuevo", methods=["POST"])
def doctor_paciente_nuevo():
    return doctor.doctor_paciente_nuevo()

@app.route("/doctor/pacientes/<int:id>")
def doctor_paciente_perfil(id):
    return doctor.doctor_paciente_perfil(id)

@app.route("/medico/paciente/<int:id_pac>/asignar-diagnostico", methods=["POST"])
def medico_asignar_diagnostico(id_pac):
    return doctor.medico_asignar_diagnostico(id_pac)

@app.route("/doctor/pacientes/<int:id>/grafica")
def doctor_paciente_grafica(id):
    return doctor.doctor_paciente_grafica(id)

@app.route("/doctor/pacientes/<int:id>/receta", methods=["POST"])
def doctor_receta_crear(id):
    return doctor.doctor_receta_crear(id)

@app.route("/doctor/receta/<int:id_receta>/cancelar", methods=["POST"])
def doctor_receta_cancelar(id_receta):
    return doctor.doctor_receta_cancelar(id_receta)

@app.route("/doctor/alertas")
def doctor_alertas():
    return doctor.doctor_alertas()

@app.route("/doctor/alertas/<int:id_alerta>/atender", methods=["POST"])
def doctor_alerta_atender(id_alerta):
    return doctor.doctor_alerta_atender(id_alerta)

@app.route("/doctor/mapa")
def doctor_mapa():
    return doctor.doctor_mapa()

@app.route("/doctor/pacientes/<int:id>/receta/nueva")
def doctor_receta_nueva(id):
    return doctor.doctor_receta_nueva(id)

@app.route("/doctor/pacientes/<int:id_pac>/cuidadores/<int:id_cuid>")
def doctor_cuidador_detalle(id_pac, id_cuid):
    return doctor.doctor_cuidador_detalle(id_pac, id_cuid)

@app.route("/doctor/pacientes/<int:id>/asignar-cuidador", methods=["GET"])
def doctor_asignar_cuidador(id):
    return doctor.doctor_asignar_cuidador(id)

@app.route("/doctor/pacientes/<int:id>/asignar-cuidador", methods=["POST"])
def doctor_asignar_cuidador_post(id):
    return doctor.doctor_asignar_cuidador_post(id)

@app.route("/doctor/pacientes/<int:id>/horario/agregar", methods=["POST"])
def doctor_horario_agregar(id):
    return doctor.doctor_horario_agregar(id)

@app.route("/doctor/pacientes/<int:id_pac>/desasignar_cuidador", methods=["POST"])
def doctor_desasignar_cuidador(id_pac):
    return doctor.doctor_desasignar_cuidador(id_pac)

@app.route("/doctor/pacientes/<int:id>/horario/eliminar", methods=["POST"])
def doctor_horario_eliminar(id):
    return doctor.doctor_horario_eliminar(id)

@app.route("/doctor/recetas/nueva", methods=["POST"])
def doctor_receta_desde_lista():
    return doctor.doctor_receta_desde_lista()

@app.route("/doctor/recetas")
def doctor_recetas():
    return doctor.doctor_recetas()

@app.route("/doctor/reportes")
def doctor_reportes():
    return doctor.doctor_reportes()

@app.route("/doctor/configuracion")
def doctor_configuracion():
    return doctor.doctor_configuracion()

@app.route("/doctor/proximidad/mapa")
def doctor_proximidad_mapa():
    return doctor.doctor_proximidad_mapa()

@app.route("/doctor/proximidad/historial")
def doctor_proximidad_historial():
    return doctor.doctor_proximidad_historial()

@app.route("/doctor/pacientes/<int:id_pac>/grafica-tomas")
def doctor_grafica_tomas(id_pac):
    return doctor.doctor_grafica_tomas(id_pac)

@app.route("/doctor/pacientes/<int:id_pac>/tendencia")
def doctor_tendencia(id_pac):
    return doctor.doctor_tendencia(id_pac)

@app.route("/doctor/riesgo-omision")
def doctor_riesgo_omision():
    return doctor.doctor_riesgo_omision()


# ─── Cuidador ───────────────────────────────────────────────────────────────

@app.route("/cuidador")
def cuidador_home():
    return cuidador.cuidador_home()

@app.route("/cuidador/paciente/<int:id>")
def cuidador_paciente(id):
    return cuidador.cuidador_paciente(id)

@app.route("/cuidador/paciente/<int:id>/escaneo", methods=["GET", "POST"])
def cuidador_escaneo(id):
    return cuidador.cuidador_escaneo(id)

@app.route("/cuidador/nfc/nuevo", methods=["GET", "POST"])
def cuidador_nfc_nuevo():
    return cuidador.cuidador_nfc_nuevo()

@app.route("/cuidador/nfc/vincular/<uid>")
def cuidador_nfc_vincular(uid):
    return cuidador.cuidador_nfc_vincular(uid)

@app.route("/cuidador/nfc/vincular", methods=["POST"])
def cuidador_nfc_vincular_post():
    return cuidador.cuidador_nfc_vincular_post()

@app.route("/cuidador/alertas")
def cuidador_alertas():
    return cuidador.cuidador_alertas()

@app.route("/cuidador/alertas/<int:id_alerta>/atender", methods=["POST"])
def cuidador_alerta_atender(id_alerta):
    return cuidador.cuidador_alerta_atender(id_alerta)

@app.route("/cuidador/historial")
def cuidador_historial():
    return cuidador.cuidador_historial()

@app.route("/cuidador/paciente/<int:id>/beacon")
def cuidador_beacon(id):
    return cuidador.cuidador_beacon(id)

@app.route("/cuidador/mi-gps")
def cuidador_mi_gps():
    return cuidador.cuidador_mi_gps()

@app.route("/cuidador/grafica-adherencia")
def cuidador_grafica_adherencia():
    return cuidador.cuidador_grafica_adherencia()


# ─── API GPS ────────────────────────────────────────────────────────────────

@app.route("/api/ubicacion-gps", methods=["POST"])
def api_ubicacion_gps():
    """Recibe coordenadas GPS del teléfono del cuidador y las guarda en MongoDB."""
    from utils.decorators import login_requerido, rol_requerido
    from mongo_client import agregar_ubicacion_gps
    if "user_id" not in session:
        return jsonify({"ok": False, "msg": "No autenticado"}), 401
    if session.get("rol") != "cuidador":
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    try:
        data            = request.get_json(force=True) or {}
        lat             = data.get("lat")
        lon             = data.get("lon")
        precision       = data.get("precision")
        id_paciente     = data.get("id_paciente")
        nombre_paciente = data.get("nombre_paciente", "")

        if not lat or not lon or not id_paciente:
            return jsonify({"ok": False, "msg": "Faltan datos"}), 400

        agregar_ubicacion_gps(
            pg_id_paciente   = int(id_paciente),
            pg_id_cuidador   = session["id_rol"],
            nombre_paciente  = nombre_paciente,
            latitud          = float(lat),
            longitud         = float(lon),
            precision_metros = float(precision) if precision else None,
            en_domicilio     = None,
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


# ─── Scheduler ──────────────────────────────────────────────────────────────

scheduler = BackgroundScheduler()
scheduler.add_job(admin.detectar_omisiones, "interval", minutes=5)

if __name__ == "__main__":
    if not scheduler.running:
        scheduler.start()
        atexit.register(lambda: scheduler.shutdown())
    app.run(debug=True, host="0.0.0.0", port=5001, use_reloader=False)
