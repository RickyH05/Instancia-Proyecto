import json
from datetime import date

from flask import flash, redirect, render_template, request, session, url_for

from config import get_db
from mongo_client import (
    agregar_ubicacion_gps,
    get_historial_paciente,
    registrar_log_nfc_fallido,
    registrar_log_sistema,
)
from utils.decorators import login_requerido, rol_requerido


@login_requerido
@rol_requerido("cuidador")
def cuidador_home():
    id_cuidador = session["id_rol"]
    fecha_hoy   = date.today().isoformat()
    pacientes   = {}
    stats       = {"tomas_ok": 0, "alertas_pend": 0}

    try:
        conn = get_db()
        cur  = conn.cursor()

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

            if estado == "pendiente" and fh_prog:
                hora_str = fh_prog.strftime("%H:%M") if hasattr(fh_prog, "strftime") else str(fh_prog)[-8:-3]
                if p["next"] is None:
                    p["next"] = hora_str

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_badge_alertas('cur_badge_cuid', %s, %s)",
                    [session["user_id"], "cuidador"])
        cur.execute("FETCH ALL FROM cur_badge_cuid")
        row_al = cur.fetchone()
        stats["alertas_pend"] = row_al[0] if row_al else 0
        conn.commit()

        if pacientes:
            cur.execute(
                "SELECT id_paciente, foto_perfil FROM paciente WHERE id_paciente = ANY(%s)",
                [list(pacientes.keys())],
            )
            for pid, fp in cur.fetchall():
                if pid in pacientes:
                    pacientes[pid]["foto"] = fp or ""

        gps_resumen = None
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_gps_cuidador('cur_gps', %s)", [id_cuidador])
        cur.execute("FETCH ALL FROM cur_gps")
        gps_row = cur.fetchone()
        conn.commit()
        if gps_row:
            gps_resumen = {
                "imei":   gps_row[1],
                "modelo": gps_row[2],
                "activo": gps_row[3],
                "lat":    gps_row[5],
                "lon":    gps_row[6],
                "ts":     str(gps_row[7])[11:16] if gps_row[7] else None,
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


@login_requerido
@rol_requerido("cuidador")
def cuidador_paciente(id):
    id_cuidador = session["id_rol"]
    fecha_hoy   = date.today().isoformat()
    agenda      = []
    paciente    = {"nombre": "", "diagnosticos": ""}

    try:
        conn = get_db()
        cur  = conn.cursor()

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

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_perfil_paciente('cur_perf_cuid', %s)", [id])
        cur.execute("FETCH ALL FROM cur_perf_cuid")
        perf_rows = cur.fetchall()
        conn.commit()

        if perf_rows:
            r = perf_rows[0]
            paciente["nombre"]       = f"{r[1]} {r[2]} {r[3] or ''}".strip()
            paciente["diagnosticos"] = r[7] or ""

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_perfil_paciente_foto('cur_foto_beacon', %s)", [id])
        cur.execute("FETCH ALL FROM cur_foto_beacon")
        fp_row = cur.fetchone()
        conn.commit()
        paciente["foto"] = fp_row[7] or "" if fp_row else ""

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


@login_requerido
@rol_requerido("cuidador")
def cuidador_escaneo(id):
    id_cuidador = session["id_rol"]
    resultado   = None

    if request.method == "POST":
        uid_nfc   = request.form.get("uid_nfc", "").strip()
        lat       = request.form.get("lat", "").strip()
        lon       = request.form.get("lon", "").strip()
        precision = request.form.get("precision", "").strip() or None
        obs       = request.form.get("observaciones", "").strip() or None

        if not uid_nfc or not lat or not lon:
            flash("UID NFC, latitud y longitud son obligatorios.", "danger")
            return render_template("cuidador/nfc_escaneo.html", id=id, resultado=None)

        try:
            conn = get_db()
            cur  = conn.cursor()

            cur.execute("BEGIN")
            cur.execute(
                """CALL sp_registrar_toma_nfc(
                    NULL, NULL, NULL, NULL, NULL, 'cur_nfc',
                    %s, %s::integer, %s::numeric(10,7), %s::numeric(10,7), %s::numeric(6,2), %s
                )""",
                [uid_nfc, id_cuidador, float(lat), float(lon), float(precision) if precision else None, obs],
            )
            p_id_ev, p_ok, p_msg, p_res, p_prox, _ = cur.fetchone()
            cur.execute("FETCH ALL FROM cur_nfc")
            row_cursor = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

        except Exception as e:
            flash(f"Error al registrar la toma: {e}", "danger")
            return render_template("cuidador/nfc_escaneo.html", id=id, resultado=None)

        if p_ok == 1:
            resultado = {
                "estado":            p_res,
                "proximidad":        p_prox,
                "id_evento":         p_id_ev,
                "msg":               p_msg,
                "desfase_min":       row_cursor[3] if row_cursor else None,
                "distancia_metros":  row_cursor[4] if row_cursor else None,
                "paciente":          row_cursor[7] if row_cursor else None,
                "medicamento":       row_cursor[8] if row_cursor else None,
            }
            # PUNTO B — registrar duplicado en MongoDB
            if p_res == "Duplicado":
                try:
                    registrar_log_nfc_fallido(
                        pg_id_cuidador  = session["id_rol"],
                        nombre_cuidador = session["nombre"],
                        uid_nfc         = uid_nfc,
                        motivo          = "duplicado",
                        ip              = request.remote_addr,
                    )
                except Exception:
                    pass
            # PUNTO GPS — guardar coordenada en MongoDB tras toma exitosa
            try:
                nombre_pac = row_cursor[7] if row_cursor else ""
                id_pac_gps = row_cursor[0] if row_cursor else None
                if id_pac_gps:
                    agregar_ubicacion_gps(
                        pg_id_paciente   = id_pac_gps,
                        pg_id_cuidador   = session["id_rol"],
                        nombre_paciente  = nombre_pac or "",
                        latitud          = float(lat),
                        longitud         = float(lon),
                        precision_metros = float(precision) if precision else None,
                        en_domicilio     = bool(p_prox),
                    )
            except Exception:
                pass
        elif p_ok == -1:
            # PUNTO A — registrar UID desconocido en MongoDB
            try:
                registrar_log_nfc_fallido(
                    pg_id_cuidador  = session["id_rol"],
                    nombre_cuidador = session["nombre"],
                    uid_nfc         = uid_nfc,
                    motivo          = "uid_desconocido",
                    ip              = request.remote_addr,
                )
            except Exception:
                pass
            try:
                conn2 = get_db()
                cur2  = conn2.cursor()
                cur2.execute("BEGIN")
                cur2.execute(
                    "CALL sp_nfc_escaneo_desconocido(%s, %s, NULL, NULL, 'cur_nfc_desc')",
                    [uid_nfc, id_cuidador],
                )
                desc_ok, desc_msg, _ = cur2.fetchone()
                conn2.commit()
                cur2.close(); conn2.close()
            except Exception as e:
                flash(f"Error al procesar UID desconocido: {e}", "danger")
                return render_template("cuidador/nfc_escaneo.html", id=id, resultado=None)

            if desc_ok == 1:
                return redirect(url_for("cuidador_nfc_vincular", uid=uid_nfc))
            elif desc_ok == -1:
                flash("Este NFC ya tiene un medicamento asignado.", "warning")
            else:
                flash(desc_msg or "Error al procesar el UID.", "danger")
        else:
            flash(p_msg, "danger")

    return render_template("cuidador/nfc_escaneo.html", id=id, resultado=resultado)


@login_requerido
@rol_requerido("cuidador")
def cuidador_nfc_nuevo():
    id_cuidador = session["id_rol"]

    if request.method == "POST":
        uid_nfc = request.form.get("uid_nfc", "").strip()
        if not uid_nfc:
            flash("Ingresa o escanea el UID de la etiqueta NFC.", "danger")
            return render_template("cuidador/nfc_nuevo.html")

        try:
            conn = get_db()
            cur  = conn.cursor()
            cur.execute("BEGIN")
            cur.execute(
                "CALL sp_nfc_escaneo_desconocido(%s, %s, NULL, NULL, 'cur_nfc_nuevo')",
                [uid_nfc, id_cuidador],
            )
            p_ok, p_msg, _ = cur.fetchone()
            conn.commit()
            cur.close(); conn.close()
        except Exception as e:
            flash(f"Error al procesar el UID: {e}", "danger")
            return render_template("cuidador/nfc_nuevo.html")

        if p_ok == 1:
            return redirect(url_for("cuidador_nfc_vincular", uid=uid_nfc))
        elif p_ok == -1:
            flash("Este NFC ya tiene un medicamento asignado.", "warning")
        else:
            flash(p_msg or "Error al procesar el UID.", "danger")
        return render_template("cuidador/nfc_nuevo.html")

    return render_template("cuidador/nfc_nuevo.html")


@login_requerido
@rol_requerido("cuidador")
def cuidador_nfc_vincular(uid):
    id_cuidador  = session["id_rol"]
    medicamentos = []
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_nfc_medicamentos_sin_vincular(%s, NULL, NULL, 'cur_sin_nfc')",
            [id_cuidador],
        )
        p_ok, p_msg, _ = cur.fetchone()
        cur.execute("FETCH ALL FROM cur_sin_nfc")
        medicamentos = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar medicamentos: {e}", "danger")
    return render_template("cuidador/nfc_vincular.html", uid=uid, medicamentos=medicamentos)


@login_requerido
@rol_requerido("cuidador")
def cuidador_nfc_vincular_post():
    id_cuidador   = session["id_rol"]
    uid_nfc       = request.form.get("uid_nfc", "").strip()
    id_receta_med = request.form.get("id_receta_medicamento", "").strip()

    if not uid_nfc or not id_receta_med:
        flash("Datos incompletos para la vinculación.", "danger")
        return redirect(url_for("cuidador_nfc_vincular", uid=uid_nfc or ""))

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_nfc_vincular(%s, %s, %s, NULL, NULL, 'cur_vincular')",
            [uid_nfc, int(id_receta_med), id_cuidador],
        )
        p_ok, p_msg, _ = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al vincular: {e}", "danger")
        return redirect(url_for("cuidador_nfc_vincular", uid=uid_nfc))

    if p_ok == 1:
        flash("Pastillero vinculado correctamente.", "success")
        return redirect(url_for("cuidador_home"))
    else:
        flash(p_msg, "danger")
        return redirect(url_for("cuidador_nfc_vincular", uid=uid_nfc))


@login_requerido
@rol_requerido("cuidador")
def cuidador_alertas():
    id_cuidador = session["id_rol"]
    solo_pend   = request.args.get("filtro", "pendientes") == "pendientes"
    alertas     = []

    try:
        conn = get_db()
        cur  = conn.cursor()

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


@login_requerido
@rol_requerido("cuidador")
def cuidador_alerta_atender(id_alerta):
    obs = request.form.get("observaciones", "").strip() or None

    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_marcar_alerta_atendida(%s, NULL, NULL, 'cur_atender_cuid', %s)",
            [id_alerta, obs],
        )
        _row = cur.fetchone()
        p_ok, p_msg = _row[1], _row[2]
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


@login_requerido
@rol_requerido("cuidador")
def cuidador_historial():
    id_cuidador        = session["id_rol"]
    eventos            = []
    stats              = {"ok": 0, "omitidas": 0, "fuera": 0}
    fecha_seleccionada = request.args.get("fecha") or str(date.today())
    id_paciente_filtro = request.args.get("id_paciente", type=int)
    total_omisiones    = 0
    lista_pacientes    = []
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_dashboard_cuidador('cur_dash', %s)", [id_cuidador])
        cur.execute("FETCH ALL FROM cur_dash")
        dashboard_rows = cur.fetchall()
        conn.commit()
        id_pacientes    = list({r[1] for r in dashboard_rows})
        pac_nombre      = {r[1]: r[2] for r in dashboard_rows}
        lista_pacientes = [{"id": k, "nombre": v} for k, v in sorted(pac_nombre.items(), key=lambda x: x[1])]

        ids_a_consultar = [id_paciente_filtro] if id_paciente_filtro and id_paciente_filtro in id_pacientes else id_pacientes

        historial_rows = []
        for id_pac in ids_a_consultar:
            cur_name = f"cur_hist_{id_pac}"
            cur.execute("BEGIN")
            cur.execute(f"CALL sp_rep_historial_tomas('{cur_name}', %s, 14)", [id_pac])
            cur.execute(f"FETCH ALL FROM {cur_name}")
            historial_rows.extend(cur.fetchall())
            conn.commit()

        for r in historial_rows:
            eventos.append({
                "id":             r[1],
                "id_paciente":    r[0],
                "pac":            pac_nombre.get(r[0], "—"),
                "med":            r[9] or "—",
                "resultado":      r[4] or "—",
                "time":           str(r[2])[:16],
                "orig":           "NFC" if (r[6] or "").lower() == "nfc" else "Manual",
                "regla_aplicada": r[13] if len(r) > 13 else None,
            })
        stats["ok"]    = sum(1 for e in eventos if e["regla_aplicada"] in ("TOMA_EXITOSA", "TOMA_TARDIA", "DUPLICADO_DETECTADO"))
        stats["fuera"] = sum(1 for e in eventos if e["regla_aplicada"] == "SIN_AGENDA_ASOCIABLE")

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_agenda_dia_cuidador('cur_agenda', %s, %s)",
                    [id_cuidador, fecha_seleccionada])
        cur.execute("FETCH ALL FROM cur_agenda")
        agendas = cur.fetchall()
        conn.commit()
        total_omisiones = sum(1 for a in agendas if a[3] == "omitida" and a[5] in ids_a_consultar)

        for a in agendas:
            if a[3] == "omitida" and a[5] in ids_a_consultar:
                eventos.append({
                    "id":             None,
                    "id_paciente":    a[5],
                    "pac":            a[6] or "—",
                    "med":            a[7] or "—",
                    "resultado":      "Omitido",
                    "time":           str(a[2])[:16],
                    "orig":           "—",
                    "regla_aplicada": "OMITIDA",
                })

        eventos.sort(key=lambda e: e["time"], reverse=True)

        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar historial: {e}", "danger")
    return render_template("cuidador/historial_nfc.html",
                           eventos=eventos, stats=stats, omisiones=total_omisiones,
                           fecha_seleccionada=fecha_seleccionada,
                           lista_pacientes=lista_pacientes,
                           id_paciente_filtro=id_paciente_filtro)


@login_requerido
@rol_requerido("cuidador")
def cuidador_beacon(id):
    paciente  = {"nombre": "", "iniciales": "??"}
    historial = []
    stats     = {"total": 0, "con_presencia": 0, "sin_presencia": 0}
    try:
        conn = get_db()
        cur  = conn.cursor()

        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_perfil_paciente_foto('cur_perf', %s)", [id])
        cur.execute("FETCH ALL FROM cur_perf")
        row = cur.fetchone()
        conn.commit()
        if row:
            nom, ap, am, fp = row[1], row[2], row[3] or '', row[7]
            paciente = {
                "nombre":    f"{nom} {ap} {am}".strip(),
                "iniciales": (nom[0] + ap[0]).upper(),
                "foto":      fp or "",
            }

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


@login_requerido
@rol_requerido("cuidador")
def cuidador_mi_gps():
    id_cuidador      = session["id_rol"]
    gps              = None
    ultima_ubicacion = None
    posiciones       = []
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_gps_cuidador('cur_gps', %s)", [id_cuidador])
        cur.execute("FETCH ALL FROM cur_gps")
        row = cur.fetchone()
        conn.commit()
        if row:
            gps = {"id": row[0], "imei": row[1], "modelo": row[2], "activo": row[3]}
            if row[5] is not None:
                posiciones.append({"lat": row[5], "lon": row[6], "ts": str(row[7])[11:16]})
                ultima_ubicacion = {
                    "lat": row[5], "lon": row[6],
                    "ts": str(row[7])[:16],
                }
        cur.close(); conn.close()
    except Exception as e:
        flash(f"Error al cargar GPS: {e}", "danger")
    return render_template("cuidador/mi_gps.html",
        gps=gps, ultima_ubicacion=ultima_ubicacion, posiciones=posiciones
    )


@login_requerido
@rol_requerido("cuidador")
def cuidador_grafica_adherencia():
    id_cuidador     = session["id_rol"]
    dias            = request.args.get("dias", 7, type=int)
    if not dias or dias <= 0:
        dias = 7
    pacientes_datos = {}

    # ── Obtener qué pacientes tiene este cuidador — PostgreSQL ───────────────
    ids_paciente = []
    pac_nombre   = {}
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("CALL sp_rep_dashboard_cuidador('cur_dash_ga', %s)", [id_cuidador])
        cur.execute("FETCH ALL FROM cur_dash_ga")
        rows_dash = cur.fetchall()
        conn.commit()
        cur.close(); conn.close()
        # cols: 0=id_cuidador, 1=id_paciente, 2=paciente, ...
        for r in rows_dash:
            pid = r[1]; nom = r[2]
            if pid and pid not in pac_nombre:
                pac_nombre[pid] = nom
        ids_paciente = list(pac_nombre.keys())
    except Exception as e:
        flash(f"Error al cargar datos del cuidador: {e}", "danger")

    # ── Historial desde MongoDB ──────────────────────────────────────────────
    # Construir lista JSON-serializable con string keys para el template
    series_json = []   # [{nombre, datos:[{fecha,correctas,fuera_horario,no_tomadas,pendientes}]}]
    for id_pac in ids_paciente:
        try:
            docs   = get_historial_paciente(id_pac, dias=dias)
            puntos = []
            for doc in docs:
                m = doc.get("metricas", {})
                puntos.append({
                    "fecha":         str(doc["fecha"])[:10],
                    "correctas":     int(m.get("correctas",  0)),
                    "fuera_horario": int(m.get("tardias",    0)),
                    "no_tomadas":    int(m.get("omitidas",   0)),
                    "pendientes":    int(m.get("pendientes", 0)),
                    "total":         int(m.get("total",      0)),
                })
            series_json.append({
                "id_paciente": id_pac,
                "nombre":      pac_nombre.get(id_pac, str(id_pac)),
                "datos":       puntos,
            })
            # mantener pacientes_datos para la lógica del template (un solo / múltiples)
            pacientes_datos[id_pac] = {"nombre": pac_nombre.get(id_pac, str(id_pac)), "datos": puntos}
        except Exception as e:
            registrar_log_sistema(
                "ERROR", "cuidador_grafica_adherencia",
                f"Fallo MongoDB historial paciente {id_pac}", str(e)
            )
            pacientes_datos[id_pac] = {"nombre": pac_nombre.get(id_pac, str(id_pac)), "datos": []}
            series_json.append({"id_paciente": id_pac,
                                 "nombre": pac_nombre.get(id_pac, str(id_pac)),
                                 "datos": []})

    return render_template("cuidador/grafica_adherencia.html",
                           pacientes_datos=pacientes_datos,
                           series_json=json.dumps(series_json, ensure_ascii=False),
                           dias=dias)
