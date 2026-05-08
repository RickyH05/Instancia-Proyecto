from datetime import date as _date

from flask import flash, jsonify, redirect, render_template, request, session, url_for

from config import get_db, guardar_foto_perfil
import json

from mongo_client import (
    get_adherencia_por_medico,
    get_pct_promedio_paciente,
    get_trayectos_todos_pacientes,
    registrar_log_sistema,
)
from utils.decorators import login_requerido, rol_requerido


@login_requerido
@rol_requerido("medico")
def doctor_dashboard():
    id_medico    = session["id_rol"]
    alertas_rec  = []
    alertas_pend = 0
    stats        = {"total_pac": 0, "bajo_80": 0, "recetas_vig": 0, "alertas_pend": 0}

    # ── Gráfica de adherencia — MongoDB ─────────────────────────────────────
    adherencia_mongo = get_adherencia_por_medico(id_medico, dias=14)
    # Normalizar a lista de dicts con keys: _id, nombre, pct
    adherencia = [
        {
            "_id":    r.get("_id"),
            "nombre": r.get("nombre") or f"Paciente {r.get('_id')}",
            "pct":    round(r["pct"], 1) if r.get("pct") is not None else 0.0,
        }
        for r in adherencia_mongo
    ]
    stats["total_pac"] = len(adherencia)
    stats["bajo_80"]   = sum(1 for p in adherencia if p["pct"] < 80)

    # ── Alertas recientes — PostgreSQL ───────────────────────────────────────
    try:
        conn = get_db()
        cur  = conn.cursor()

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


@login_requerido
@rol_requerido("medico")
def doctor_pacientes():
    id_medico = session["id_rol"]
    pacientes = []

    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_pacientes_medico('cur_pac_doc', %s)", [id_medico])
        cur.execute("FETCH ALL FROM cur_pac_doc")
        rows = cur.fetchall()
        conn.commit()
        pac_map = {}
        for r in rows:
            _, pid, nom, ap, am, fnac, curp, activo, id_rx, est_rx, f_ini, f_fin = r
            if pid not in pac_map:
                edad = None
                if fnac:
                    hoy = _date.today()
                    edad = hoy.year - fnac.year - ((hoy.month, hoy.day) < (fnac.month, fnac.day))
                pac_map[pid] = {
                    "id":      pid,
                    "nombre":  f"{nom} {ap} {am or ''}".strip(),
                    "curp":    curp or "",
                    "edad":    edad,
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
        p_id, p_ok, p_msg = cur.fetchone()[:3]
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
            flash(f'Error al crear paciente: {error_msg}', 'danger')
    return redirect(url_for("doctor_pacientes"))


@login_requerido
@rol_requerido("medico")
def doctor_paciente_perfil(id):
    id_medico             = session["id_rol"]
    solo_pend_alertas     = request.args.get("filtro_alertas", "pendientes") == "pendientes"
    paciente              = {}
    historial             = []
    alertas               = []
    recetas               = {}
    vinculos              = []
    diagnosticos_catalogo = []
    pct_mongo             = 0.0

    try:
        conn = get_db()
        cur  = conn.cursor()

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
            cur.execute("BEGIN")
            cur.execute("CALL sp_rep_perfil_paciente_foto('cur_perf', %s)", [r[0]])
            cur.execute("FETCH ALL FROM cur_perf")
            fp_row = cur.fetchone()
            conn.commit()
            paciente["foto"] = fp_row[7] or "" if fp_row else ""

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

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_historial_tomas('cur_hist_perf', %s, 14)", [id])
        cur.execute("FETCH ALL FROM cur_hist_perf")
        rows = cur.fetchall()
        conn.commit()
        for r in rows:
            id_ev     = r[1]
            ts        = r[2]
            uid       = r[3]
            resultado = r[4]
            desfase   = r[5]
            origen    = r[6]
            obs       = r[7]
            fecha_reg = r[8]
            med       = r[9]
            cuidador  = r[10]
            dist      = r[11]
            prox      = r[12]
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

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_alertas_medico('cur_alert_perf', %s, %s)", [id_medico, solo_pend_alertas])
        cur.execute("FETCH ALL FROM cur_alert_perf")
        rows_al = cur.fetchall()
        conn.commit()
        for r in rows_al:
            _, id_al, prio, tipo, estado, ts_gen, pac_nombre, med, id_ev = r
            alertas.append({
                "id": id_al, "prioridad": prio, "tipo": tipo,
                "estado": estado, "timestamp": ts_gen, "medicamento": med,
            })

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_recetas_paciente('cur_rx_perf', %s)", [id])
        cur.execute("FETCH ALL FROM cur_rx_perf")
        rows = cur.fetchall()
        conn.commit()
        for r in rows:
            id_pac  = r[0]
            id_rx   = r[1]
            est_rx  = r[2]
            f_emi   = r[3]
            f_ini   = r[4]
            f_fin   = r[5]
            medico  = r[6]
            id_rxm  = r[7]
            med_nom = r[8]
            dosis   = r[9]
            unidad  = r[10]
            freq    = r[11]
            tol     = r[12]
            hora    = r[13]

            if id_rx not in recetas:
                recetas[id_rx] = {
                    "id": id_rx, "estado": est_rx, "emision": f_emi,
                    "inicio": f_ini, "fin": f_fin, "medico": medico, "meds": [],
                }
            if id_rxm:
                recetas[id_rx]["meds"].append({
                    "id_rm": id_rxm, "nombre": med_nom, "dosis": dosis, "unidad": unidad,
                    "frecuencia_h": freq, "tolerancia": tol, "hora": hora,
                })

        vinculos = []
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_vinculo_paciente_cuidador('cur_vpc_perf', %s)", [id])
        cur.execute("FETCH ALL FROM cur_vpc_perf")
        vinculos = [r for r in cur.fetchall() if r[3]]
        conn.commit()

        diagnosticos_catalogo = []
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_diagnostico('L', NULL, NULL, NULL, 'cur_diag_cat')")
        _, p_ok_cat, _msg, _ = cur.fetchone()
        if p_ok_cat != 1:
            conn.rollback()
        cur.execute("FETCH ALL FROM cur_diag_cat")
        diagnosticos_catalogo = cur.fetchall()
        conn.commit()

        observaciones_atendidas = []
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_observaciones_alertas_paciente('cur_obs_alertas', %s)", [id])
        cur.execute("FETCH ALL FROM cur_obs_alertas")
        obs_rows = cur.fetchall()
        conn.commit()
        observaciones_atendidas = [
            {
                "id":          row[0],
                "observacion": row[1],
                "fecha":       row[2],
                "medicamento": row[3],
                "tipo_alerta": row[4],
            }
            for row in obs_rows
        ]

        cur.close()
        conn.close()

    except Exception as e:
        import traceback as _tb; _tb.print_exc()
        flash(f"Error al cargar el perfil: {e}", "danger")

    print(f"DEBUG recetas count={len(recetas)}")
    print(f"DEBUG recetas keys={list(recetas.keys())}")
    for _rx_id, _rx in recetas.items():
        print(f"  receta id={_rx_id} meds={[m.get('id_rm') for m in _rx.get('meds', [])]}")

    # ── Etiquetas NFC por id_receta_medicamento ──────────────────────────────
    import traceback as _tb
    etiquetas_nfc = {}  # {id_rm: uid_nfc}
    ids_rm_vistos = set()
    for rx in recetas.values():
        for m in rx.get("meds", []):
            id_rm = m.get("id_rm")
            if not id_rm or id_rm in ids_rm_vistos:
                continue
            ids_rm_vistos.add(id_rm)
            try:
                conn_et = get_db()
                cur_et  = conn_et.cursor()
                cur_et.execute("BEGIN")
                cur_et.execute(
                    "CALL sp_gestion_etiqueta_nfc('L', NULL, NULL, NULL, 'cur_et', NULL, NULL, %s)",
                    [id_rm],
                )
                cur_et.fetchone()  # consume INOUT/OUT params (p_uid, p_ok, p_msg)
                cur_et.execute("FETCH ALL FROM cur_et")
                rows_et = cur_et.fetchall()
                conn_et.commit()
                cur_et.close(); conn_et.close()
                print(f"DEBUG NFC id_rm={id_rm} rows_et={rows_et}")
                activas = [r for r in rows_et if r[4] == 'activo']
                if activas:
                    etiquetas_nfc[int(id_rm)] = activas[0][0]
            except Exception:
                _tb.print_exc()
    print(f"DEBUG etiquetas_nfc final={etiquetas_nfc}")

    # ── Gauge de adherencia — MongoDB ────────────────────────────────────────
    try:
        pct_mongo = get_pct_promedio_paciente(id, dias=14)
    except Exception as e:
        registrar_log_sistema("ERROR", "doctor_paciente_perfil",
                              f"Fallo MongoDB pct paciente {id}", str(e))
        pct_mongo = 0.0

    # ── Catálogos para modal nueva receta ────────────────────────────────────
    medicamentos_cat = []
    unidades_cat     = []
    try:
        conn2 = get_db()
        cur2  = conn2.cursor()
        cur2.execute("BEGIN")
        cur2.execute("CALL sp_gestion_medicamento('L', NULL, NULL, NULL, 'cur_med_cat_perf')")
        cur2.fetchone()
        cur2.execute("FETCH ALL FROM cur_med_cat_perf")
        medicamentos_cat = cur2.fetchall()
        conn2.commit()
        cur2.execute("BEGIN")
        cur2.execute("CALL sp_rep_unidades_dosis('cur_uni_cat_perf')")
        cur2.execute("FETCH ALL FROM cur_uni_cat_perf")
        unidades_cat = cur2.fetchall()
        conn2.commit()
        cur2.close(); conn2.close()
    except Exception:
        pass

    return render_template(
        "doctor/paciente_perfil.html",
        id=id,
        paciente=paciente,
        historial=historial,
        alertas=alertas,
        recetas=list(recetas.values()),
        vinculos=vinculos,
        diagnosticos_catalogo=diagnosticos_catalogo,
        pct_mongo=pct_mongo,
        observaciones_atendidas=observaciones_atendidas,
        solo_pend_alertas=solo_pend_alertas,
        medicamentos_cat=medicamentos_cat,
        unidades_cat=unidades_cat,
        etiquetas_nfc=etiquetas_nfc,
    )


@login_requerido
@rol_requerido("medico")
def medico_asignar_diagnostico(id_pac):
    id_diagnostico = request.form.get("id_diagnostico", type=int)
    if not id_diagnostico:
        flash("Selecciona un diagnóstico.", "danger")
        return redirect(url_for("doctor_paciente_perfil", id=id_pac))

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            "SELECT set_config('medi_nfc2.id_usuario_app', %s, TRUE)",
            [str(session["user_id"])]
        )
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_asignar_diagnostico(%s, %s, NULL, NULL, 'cur_asig_diag')",
            [id_pac, id_diagnostico]
        )
        p_ok, p_msg = cur.fetchone()[:2]
        cur.execute("FETCH ALL FROM cur_asig_diag")
        if p_ok == 1:
            conn.commit()
            flash(p_msg, "success")
        else:
            conn.rollback()
            flash(p_msg, "danger")
        cur.close()
        conn.close()
    except Exception as e:
        flash(str(e), "danger")

    return redirect(url_for("doctor_paciente_perfil", id=id_pac))


@login_requerido
@rol_requerido("medico")
def doctor_paciente_grafica(id):
    dias  = request.args.get("dias", 14, type=int)
    datos = []

    try:
        conn = get_db()
        cur  = conn.cursor()

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


@login_requerido
@rol_requerido("medico")
def doctor_receta_crear(id):
    id_medico  = session["id_rol"]
    f_ini      = request.form.get("fecha_inicio", "").strip()
    f_fin      = request.form.get("fecha_fin", "").strip()
    f_emi      = request.form.get("fecha_emision", f_ini).strip()

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

        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_crear_receta(NULL, NULL, NULL, 'cur_rx_crear', %s, %s, %s, %s, %s)",
            [id, id_medico, f_emi, f_ini, f_fin],
        )
        _row = cur.fetchone()
        p_id_rx, p_ok, p_msg = _row[0], _row[1], _row[2]
        conn.commit()

        if p_ok != 1:
            flash(p_msg, "danger")
            cur.close(); conn.close()
            return redirect(url_for("doctor_paciente_perfil", id=id))

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
                flash(f"Medicamento {i+1}: datos incompletos.", "warning")
                continue

            cur_rxmed = f"cur_rxmed_{i}"
            try:
                cur.execute("BEGIN")
                cur.execute(
                    f"CALL sp_agregar_receta_med(NULL, NULL, NULL, '{cur_rxmed}', %s, %s, %s, %s, %s, %s, %s)",
                    [p_id_rx, int(mid), dosis, freq, tol, hora, unidad],
                )
                row_m  = cur.fetchone()
                p_ok_m = row_m[1] if row_m else -99
                p_msg_m = row_m[2] if row_m else "Sin respuesta del SP"
                cur.execute(f"FETCH ALL FROM {cur_rxmed}")
                if p_ok_m != 1:
                    conn.rollback()
                    flash(f"Medicamento {i+1}: {p_msg_m}", "warning")
                else:
                    conn.commit()
            except Exception as em:
                conn.rollback()
                flash(f"Medicamento {i+1}: {em}", "warning")

        cur.close()
        conn.close()
        flash("Receta creada correctamente.", "success")

    except Exception as e:
        flash(f"Error al crear la receta: {e}", "danger")

    return redirect(url_for("doctor_paciente_perfil", id=id))


@login_requerido
@rol_requerido("medico")
def doctor_nfc_desactivar(id_pac, uid):
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("""
            CALL sp_gestion_etiqueta_nfc(
                'U', %s, NULL, NULL, 'cur_nfc_desact',
                NULL, NULL, NULL, 'inactivo'
            )
        """, [uid])
        row    = cur.fetchone()
        p_ok   = row[1] if row else -99
        p_msg  = row[2] if row else "Sin respuesta del SP"
        cur.execute("FETCH ALL FROM cur_nfc_desact")
        if p_ok != 1:
            conn.rollback()
            flash(p_msg, "danger")
        else:
            conn.commit()
            flash("Etiqueta NFC desactivada.", "success")
        cur.close(); conn.close()
    except Exception as e:
        flash(str(e), "danger")
    return redirect(url_for("doctor_paciente_perfil", id=id_pac))


@login_requerido
@rol_requerido("medico")
def doctor_receta_cancelar(id_receta):
    id_pac = request.form.get("id_paciente", type=int)

    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("BEGIN")
        cur.execute("CALL sp_cancelar_receta(%s, NULL, NULL, 'cur_cancelar')", [id_receta])
        _row = cur.fetchone()
        p_ok, p_msg = _row[1], _row[2]
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


@login_requerido
@rol_requerido("medico")
def doctor_alertas():
    id_medico = session["id_rol"]
    solo_pend = request.args.get("filtro", "pendientes") == "pendientes"
    alertas   = []

    try:
        conn = get_db()
        cur  = conn.cursor()

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


@login_requerido
@rol_requerido("medico")
def doctor_alerta_atender(id_alerta):
    obs = request.form.get("observaciones", "").strip() or None

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_marcar_alerta_atendida(%s, NULL, NULL, 'cur_atender_med', %s)",
            [id_alerta, obs],
        )
        p_ok, p_msg = cur.fetchone()[:2]
        cur.execute("FETCH ALL FROM cur_atender_med")
        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al atender la alerta: {e}", "danger")
        return redirect(url_for("doctor_alertas"))

    flash("Alerta marcada como atendida." if p_ok == 1 else p_msg,
          "success" if p_ok == 1 else "danger")
    return redirect(url_for("doctor_alertas"))


@login_requerido
@rol_requerido("medico")
def doctor_mapa():
    id_medico = session["id_rol"]
    puntos    = []

    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_mapa_medico('cur_mapa', %s)", [id_medico])
        cur.execute("FETCH ALL FROM cur_mapa")
        rows = cur.fetchall()
        conn.commit()

        pac_map = {}
        for r in rows:
            _, id_pac, pac, id_bec, bec_lat, bec_lon, radio, gps_lat, gps_lon, gps_ts, cuidador = r
            if id_pac not in pac_map:
                pac_map[id_pac] = {
                    "id_paciente": id_pac,
                    "paciente":    pac,
                    "beacon":      {
                        "id":    id_bec,
                        "lat":   float(bec_lat or 0),
                        "lon":   float(bec_lon or 0),
                        "radio": float(radio or 5),
                    },
                    "cuidadores": [],
                }
            if gps_lat:
                pac_map[id_pac]["cuidadores"].append({
                    "nombre": cuidador or "",
                    "gps": {
                        "lat": float(gps_lat),
                        "lon": float(gps_lon),
                        "ts":  str(gps_ts or ""),
                    },
                })
        puntos = list(pac_map.values())

        cur.close()
        conn.close()

    except Exception as e:
        flash(f"Error al cargar el mapa: {e}", "danger")

    con_gps = len(set(
        c["nombre"]
        for p in puntos
        for c in p["cuidadores"]
        if c["gps"]["lat"] != 0
    ))

    return render_template("proximidad/mapa.html", puntos=puntos, con_gps=con_gps)


@login_requerido
@rol_requerido("medico")
def doctor_receta_nueva(id):
    return redirect(url_for("doctor_paciente_perfil", id=id))


@login_requerido
@rol_requerido("medico")
def doctor_cuidador_detalle(id_pac, id_cuid):
    cuidador = {}
    vinculo  = None
    horarios = []
    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_cuidador('R', %s, NULL, NULL, 'cur_cuid')", [id_cuid])
        cur.fetchone()
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

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_vinculo_paciente_cuidador('cur_vpc_det', %s)", [id_pac])
        cur.execute("FETCH ALL FROM cur_vpc_det")
        rows_vpc = cur.fetchall()
        conn.commit()
        vinculo = next((r for r in rows_vpc if r[1] == id_cuid and r[3]), None)

        if vinculo:
            id_pc = vinculo[0]
            cur.execute("BEGIN")
            cur.execute(
                "CALL sp_gestion_horario('L', NULL, NULL, NULL, 'cur_hor_det', %s)", [id_pc]
            )
            cur.fetchone()
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


@login_requerido
@rol_requerido("medico")
def doctor_asignar_cuidador(id):
    cuidadores            = []
    horarios_por_cuidador = []
    id_pc                 = None
    id_cuid_actual        = None
    pac_nombre            = ""
    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_perfil_paciente('cur_pac', %s)", [id])
        cur.fetchone()[:3]
        cur.execute("FETCH ALL FROM cur_pac")
        row_pac = cur.fetchone()
        conn.commit()
        pac_nombre = f"{row_pac[1]} {row_pac[2]} {row_pac[3] or ''}".strip() if row_pac else ""

        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_cuidador('L', NULL, NULL, NULL, 'cur_cuids')")
        _, p_ok, p_msg = cur.fetchone()[:3]
        cur.execute("FETCH ALL FROM cur_cuids")
        rows_c = cur.fetchall()
        conn.commit()
        cuidadores = [(r[0], f"{r[1]} {r[2]}") for r in rows_c]

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_vinculo_paciente_cuidador('cur_vpc', %s)", [id])
        cur.execute("FETCH ALL FROM cur_vpc")
        rows_vpc = cur.fetchall()
        conn.commit()
        vinculos_activos = [r for r in rows_vpc if r[3]]

        id_pc          = None
        id_cuid_actual = None
        row_principal  = next((r for r in vinculos_activos if r[2]), None)
        if row_principal:
            id_pc          = row_principal[0]
            id_cuid_actual = row_principal[1]

        horarios_por_cuidador = []
        for v in vinculos_activos:
            cur.execute("BEGIN")
            cur_name = f"cur_hor_{v[0]}"
            cur.execute(
                f"CALL sp_gestion_horario('L', NULL, NULL, NULL, '{cur_name}', %s)", [v[0]]
            )
            cur.fetchone()
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


@login_requerido
@rol_requerido("medico")
def doctor_asignar_cuidador_post(id):
    id_cuid   = request.form.get("id_cuidador", type=int)
    principal = request.form.get("es_principal") == "1"

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


@login_requerido
@rol_requerido("medico")
def doctor_horario_agregar(id):
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
        row = next((r for r in rows_vpc if r[1] == id_cuid and r[3] == True), None)
        if not row:
            flash("No existe vínculo activo entre ese cuidador y el paciente.", "danger")
            return redirect(url_for("doctor_asignar_cuidador", id=id))
        id_pc = row[0]

        # Fetch existing shifts for this link and check for overlaps in Python
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_gestion_horario('L', NULL, NULL, NULL, 'cur_hor_chk', %s)",
            [id_pc]
        )
        cur.fetchone()  # consume OUT scalars
        cur.execute("FETCH ALL FROM cur_hor_chk")
        existing = cur.fetchall()
        conn.commit()

        from datetime import time as _time
        def _t(s):
            h, m = str(s).split(":")[:2]
            return _time(int(h), int(m))

        nueva_ini = _t(hora_inicio)
        nueva_fin = _t(hora_fin)
        conflicto = next(
            (r for r in existing
             if r[1] == dia and nueva_ini < _t(str(r[3])) and nueva_fin > _t(str(r[2]))),
            None
        )
        if conflicto:
            flash(
                f"Traslape de horario: ya existe un turno el {dia} "
                f"de {conflicto[2]} a {conflicto[3]}.",
                "danger"
            )
            cur.close(); conn.close()
            return redirect(url_for("doctor_asignar_cuidador", id=id))

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


@login_requerido
@rol_requerido("medico")
def doctor_desasignar_cuidador(id_pac):
    id_pac_cuid = request.form.get("id_paciente_cuidador", type=int)
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("CALL sp_desasignar_cuidador(%s, NULL, NULL, 'cur_desasig')", [id_pac_cuid])
        p_ok, p_msg = cur.fetchone()[:2]
        conn.commit()
        cur.close()
        conn.close()
        if p_ok == 1:
            flash("Cuidador desasignado correctamente.", "success")
        else:
            flash(f"No se pudo desasignar: {p_msg}", "danger")
    except Exception as e:
        flash(f"Error: {e}", "danger")
    return redirect(url_for('doctor_paciente_perfil', id=id_pac))


@login_requerido
@rol_requerido("medico")
def doctor_horario_eliminar(id):
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


@login_requerido
@rol_requerido("medico")
def doctor_receta_desde_lista():
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
    nfc_uids   = request.form.getlist("nfc_uids[]")

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
        _row = cur.fetchone()
        p_id_rx, p_ok, p_msg = _row[0], _row[1], _row[2]
        conn.commit()
        if p_ok != 1:
            flash(p_msg, "danger")
            cur.close(); conn.close()
            return redirect(url_for("doctor_recetas"))

        med_nombres = {}
        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_medicamento('L', NULL, NULL, NULL, 'cur_meds_rx')")
        cur.fetchone()
        cur.execute("FETCH ALL FROM cur_meds_rx")
        for r in cur.fetchall():
            med_nombres[str(r[0])] = r[1]
        conn.commit()

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
                flash(f"Medicamento {i+1}: datos incompletos.", "warning")
                continue
            cur_rxm = f"cur_rxmed_lista_{i}"
            try:
                cur.execute("BEGIN")
                cur.execute(
                    f"CALL sp_agregar_receta_med(NULL, NULL, NULL, '{cur_rxm}', %s, %s, %s, %s, %s, %s, %s)",
                    [p_id_rx, int(mid), dosis, freq, tol, hora, unidad],
                )
                row_m   = cur.fetchone()
                p_id_rm = row_m[0] if row_m else None
                p_ok_m  = row_m[1] if row_m else -99
                p_msg_m = row_m[2] if row_m else "Sin respuesta del SP"
                cur.execute(f"FETCH ALL FROM {cur_rxm}")
                if p_ok_m != 1:
                    conn.rollback()
                    flash(f"Medicamento {i+1}: {p_msg_m}", "warning")
                    continue
                conn.commit()
            except Exception as em:
                conn.rollback()
                flash(f"Medicamento {i+1}: {em}", "warning")
                continue
            uid = nfc_uids[i] if i < len(nfc_uids) else ''
            if uid.strip():
                nombre_med = med_nombres.get(str(mid), str(mid))
                cur.execute("BEGIN")
                cur.execute(
                    "CALL sp_gestion_etiqueta_nfc('I', %s, NULL, NULL, 'cur_nfc', %s, %s, %s, %s)",
                    [uid.strip(), f"{nombre_med} - Paciente", 'medicamento', p_id_rm, 'activo'],
                )
                p_uid, p_ok, p_msg, _ = cur.fetchone()
                cur.execute("FETCH ALL FROM cur_nfc")
                conn.commit()
        cur.close(); conn.close()
        flash("Receta creada correctamente.", "success")
    except Exception as e:
        flash(f"Error al crear la receta: {e}", "danger")
    return redirect(url_for("doctor_recetas"))


@login_requerido
@rol_requerido("medico")
def doctor_recetas():
    id_medico    = session["id_rol"]
    recetas      = {}
    pacientes    = []
    medicamentos = []
    try:
        conn = get_db()
        cur  = conn.cursor()

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

        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_paciente('L', NULL, NULL, NULL, 'cur_pacs')")
        _, p_ok, p_msg = cur.fetchone()[:3]
        cur.execute("FETCH ALL FROM cur_pacs")
        rows_p = cur.fetchall()
        conn.commit()
        pacientes = [(r[0], f"{r[1]} {r[2]} {r[3] or ''}".strip()) for r in rows_p]

        cur.execute("BEGIN")
        cur.execute("CALL sp_gestion_medicamento('L', NULL, NULL, NULL, 'cur_meds')")
        _, p_ok, p_msg = cur.fetchone()[:3]
        cur.execute("FETCH ALL FROM cur_meds")
        rows_m = cur.fetchall()
        conn.commit()
        medicamentos = [(r[0], r[1], r[3]) for r in rows_m]

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_unidades_dosis('cur_unis')")
        cur.execute("FETCH ALL FROM cur_unis")
        rows_u = cur.fetchall()
        conn.commit()
        # cols: id_unidad[0], abreviatura[1], descripcion[2]
        unidades = [(r[0], r[1], r[2]) for r in rows_u]

        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar recetas: {e}", "danger")
        unidades = []
    return render_template("doctor/recetas.html",
        recetas=list(recetas.values()),
        pacientes=pacientes,
        medicamentos=medicamentos,
        unidades=unidades,
    )


@login_requerido
@rol_requerido("medico")
def doctor_reportes():
    id_medico     = session["id_rol"]
    dias          = request.args.get("dias", 30, type=int)
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


@login_requerido
@rol_requerido("medico")
def doctor_configuracion():
    return render_template("doctor/configuracion.html")


@login_requerido
@rol_requerido("medico")
def doctor_proximidad_mapa():
    return redirect(url_for("doctor_mapa"))


@login_requerido
@rol_requerido("medico")
def doctor_proximidad_historial():
    id_medico = session["id_rol"]
    eventos   = []
    total = validos = sin_prox = 0
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_mapa_medico('cur_mapa', %s)", [id_medico])
        cur.execute("FETCH ALL FROM cur_mapa")
        mapa_rows = cur.fetchall()
        conn.commit()
        id_pacientes = list({r[1] for r in mapa_rows})
        historial_prox = []
        for id_pac in id_pacientes:
            cur.execute("BEGIN")
            cur.execute("CALL sp_rep_historial_tomas('cur_hist', %s, 7)", [id_pac])
            cur.execute("FETCH ALL FROM cur_hist")
            historial_prox.extend(cur.fetchall())
            conn.commit()
        pac_nombre = {r[1]: r[2] for r in mapa_rows}
        for r in historial_prox:
            dist   = r[11]
            valida = r[12]
            eventos.append({
                "pac":   pac_nombre.get(r[0], "—"),
                "med":   r[9] or "—",
                "cuid":  r[10] or "—",
                "ts":    str(r[2])[:16],
                "dist":  f"{dist:.1f}m" if dist is not None else "—",
                "valida": bool(valida),
            })
        total    = len(eventos)
        validos  = sum(1 for e in eventos if e["valida"])
        sin_prox = total - validos
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar historial de proximidad: {e}", "danger")

    horas = int(request.args.get("horas", 24))
    try:
        trayectos = get_trayectos_todos_pacientes(
            pg_id_medico=session["id_rol"],
            horas=horas,
        )
    except Exception as e:
        registrar_log_sistema("ERROR", "doctor_proximidad_historial",
                              "Fallo MongoDB trayectos GPS", str(e))
        trayectos = {}
    trayectos_json = json.dumps(trayectos)

    return render_template("proximidad/historial.html",
        eventos=eventos, total=total, validos=validos, sin_prox=sin_prox,
        trayectos_json=trayectos_json, horas=horas,
    )


@login_requerido
@rol_requerido("medico")
def doctor_grafica_tomas(id_pac):
    dias = request.args.get("dias", 14, type=int)
    if not dias or dias <= 0:
        dias = 14
    nombre_paciente = ""
    datos = []
    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_perfil_paciente('cur_perf_gt', %s)", [id_pac])
        cur.execute("FETCH ALL FROM cur_perf_gt")
        filas = cur.fetchall()
        conn.commit()
        if filas:
            r = filas[0]
            nombre_paciente = f"{r[1]} {r[2]}" if r[1] else ""

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_grafica_tomas('cur_gt', %s, %s)", [id_pac, dias])
        cur.execute("FETCH ALL FROM cur_gt")
        rows = cur.fetchall()
        conn.commit()
        for r in rows:
            datos.append({
                "fecha":         str(r[1]),
                "correctas":     int(r[3] or 0),
                "fuera_horario": int(r[4] or 0),
                "no_tomadas":    int(r[5] or 0),
                "pendientes":    int(r[6] or 0),
            })
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar gráfica: {e}", "danger")
    return render_template("doctor/grafica_tomas.html",
                           id_pac=id_pac,
                           nombre_paciente=nombre_paciente,
                           datos=datos,
                           dias=dias)


@login_requerido
@rol_requerido("medico")
def doctor_tendencia(id_pac):
    dias = request.args.get("dias", 30, type=int)
    if not dias or dias <= 0:
        dias = 30
    nombre_paciente  = ""
    datos            = []
    tendencia_global = ""
    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_perfil_paciente('cur_perf_td', %s)", [id_pac])
        cur.execute("FETCH ALL FROM cur_perf_td")
        filas = cur.fetchall()
        conn.commit()
        if filas:
            r = filas[0]
            nombre_paciente = f"{r[1]} {r[2]}" if r[1] else ""

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_tendencia_adherencia('cur_tend', %s, %s)", [id_pac, dias])
        cur.execute("FETCH ALL FROM cur_tend")
        rows = cur.fetchall()
        conn.commit()
        for r in rows:
            datos.append({
                "fecha":     str(r[2]),
                "pct_dia":   float(r[7]) if r[7] is not None else None,
                "mov7d":     float(r[8]) if r[8] is not None else None,
                "tendencia": str(r[9] or ""),
            })
        if datos:
            tendencia_global = datos[-1]["tendencia"]
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar tendencia: {e}", "danger")
    return render_template("doctor/tendencia.html",
                           id_pac=id_pac,
                           nombre_paciente=nombre_paciente,
                           datos=datos,
                           dias=dias,
                           tendencia_global=tendencia_global)


@login_requerido
@rol_requerido("medico")
def doctor_riesgo_omision():
    id_medico    = session["id_rol"]
    solo_activas = request.args.get("activas", "1") == "1"
    min_dias     = request.args.get("min_dias", 2, type=int)
    filas = []
    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_pacientes_medico('cur_pacs_ro', %s)", [id_medico])
        cur.execute("FETCH ALL FROM cur_pacs_ro")
        mis_pacs = {int(r[1]) for r in cur.fetchall()}
        conn.commit()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_riesgo_omision('cur_riesgo', NULL, %s, %s)",
                    [solo_activas, min_dias])
        cur.execute("FETCH ALL FROM cur_riesgo")
        rows = cur.fetchall()
        conn.commit()

        for r in rows:
            if r[0] in mis_pacs:
                filas.append({
                    "id_paciente":              r[0],
                    "paciente":                 r[1],
                    "medicamento":              r[2],
                    "inicio_racha":             str(r[3]) if r[3] else "",
                    "fin_racha":                str(r[4]) if r[4] else "",
                    "dias_consecutivos":        int(r[5] or 0),
                    "nivel_riesgo":             str(r[6] or ""),
                    "racha_activa":             bool(r[7]),
                    "dias_desde_ultima_omision": int(r[8] or 0),
                })
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar riesgo de omisión: {e}", "danger")
    return render_template("doctor/riesgo_omision.html",
                           filas=filas,
                           solo_activas=solo_activas,
                           min_dias=min_dias)
