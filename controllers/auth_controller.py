import bcrypt

from flask import flash, redirect, render_template, request, session, url_for

from config import _ADMIN_EMAIL, _ADMIN_HASH, get_db
from mongo_client import registrar_log_acceso


def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email    = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        if not email or not password:
            flash("Por favor ingresa email y contraseña.", "danger")
            return render_template("login.html")

        if email == _ADMIN_EMAIL and bcrypt.checkpw(password.encode(), _ADMIN_HASH.encode()):
            session["user_id"]    = 0
            session["rol"]        = "admin"
            session["id_rol"]     = None
            session["nombre"]     = "Administrador"
            session["foto_perfil"] = "default_medico.png"
            return redirect(url_for("dashboard"))

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
        except Exception:
            flash("Error de conexión con la base de datos.", "danger")
            return render_template("login.html")

        # ── Log MongoDB (adicional al INSERT de PG, no reemplaza) ────────────
        registrar_log_acceso(
            pg_id_usuario  = row[0] if row else None,
            email          = email,
            rol            = row[2] if row else None,
            ip             = request.remote_addr,
            exitoso        = login_ok,
            user_agent     = request.headers.get("User-Agent"),
            motivo_fallo   = None if login_ok else "Contraseña incorrecta",
        )

        if login_ok:
            session["user_id"]    = id_usuario
            session["rol"]        = rol
            session["id_rol"]     = id_rol
            session["nombre"]     = nombre
            session["foto_perfil"] = foto_perfil
            return redirect(url_for("dashboard"))

        flash("Credenciales incorrectas.", "danger")

    return render_template("login.html")


def logout():
    session.clear()
    return redirect(url_for("login"))


def dashboard():
    rol = session.get("rol")
    if rol == "admin":
        return redirect(url_for("admin_dashboard"))
    elif rol == "medico":
        return redirect(url_for("doctor_dashboard"))
    else:
        return redirect(url_for("cuidador_home"))
