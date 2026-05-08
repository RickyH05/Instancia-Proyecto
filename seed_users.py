"""
seed_users.py  |  Crea/actualiza usuarios de acceso para MediNFC
medi_nfc2  — coherente con seed_completo_postgres.sql
==============================================================================

Ejecutar DESPUÉS de seed_completo_postgres.sql:
    pip install psycopg[binary] bcrypt
    python seed_users.py

El script es idempotente:
  - Si el usuario ya existe (p_ok=-10) actualiza su password con sp_gestion_usuario
  - Si no existe lo crea con sp_crear_usuario_admin
  - Nunca aborta por duplicados

Usuarios creados/actualizados (email / contraseña / rol):
─────────────────────────────────────────────────────────────────────────────
MÉDICO (id 1)
  carlos.mendoza@medinfc.mx     Medinfc2024!   medico   (Dr. Carlos Mendoza Rios)

CUIDADORES (ids 1-2)
  sofia.castro@medinfc.mx       Medinfc2024!   cuidador (Sofia Castro Leal,  formal)
  javier.mora@medinfc.mx        Medinfc2024!   cuidador (Javier Mora Reyes,  formal)
─────────────────────────────────────────────────────────────────────────────
"""

import sys
import bcrypt
import psycopg

# ── Conexión ─────────────────────────────────────────────────────────────────
DB_DSN = "postgresql://proyectofinal_user:444@localhost:5432/medi_nfc2"


def get_conn():
    return psycopg.connect(DB_DSN)


# ── Utilidades ────────────────────────────────────────────────────────────────

def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def log(label: str, p_ok: int, p_msg: str, accion: str = ""):
    if p_ok == 1:
        marca = "✓"
    elif p_ok == -10:
        marca = "↺"  # ya existe, se actualizó
    else:
        marca = "✗"
    sufijo = f" [{accion}]" if accion else ""
    print(f"  {marca}  {label}: {p_msg}{sufijo}")
    if p_ok not in (1, -10):
        print(f"     ERROR FATAL — abortando. Código: {p_ok}")
        sys.exit(1)


# ── Datos de usuarios ─────────────────────────────────────────────────────────
# (email, contraseña_plana, rol, id_en_tabla_medico_o_cuidador)
# IDs deben coincidir con seed_completo_postgres.sql

MEDICOS = [
    ("carlos.mendoza@medinfc.mx", "Medinfc2024!", "medico", 1),
]

CUIDADORES = [
    ("sofia.castro@medinfc.mx",  "Medinfc2024!", "cuidador", 1),
    ("javier.mora@medinfc.mx",   "Medinfc2024!", "cuidador", 2),
]


# ── Crear o actualizar usuario ────────────────────────────────────────────────

def crear_o_actualizar(conn, cur, email: str, password: str,
                       rol: str, id_rol: int, idx: int):
    """
    Intenta crear con sp_crear_usuario_admin.
    Si ya existe (p_ok=-10), actualiza el password con sp_gestion_usuario.
    """
    pw_hash  = hash_pw(password)
    cur_name = f"cur_{rol[:4]}_{idx}"

    # Intentar crear
    cur.execute("BEGIN")
    cur.execute(
        "CALL sp_crear_usuario_admin(%s, %s, %s::rol_usuario_enum, %s, NULL, NULL, %s)",
        [email, pw_hash, rol, id_rol, cur_name],
    )
    p_ok, p_msg, _ = cur.fetchone()
    cur.execute(f"CLOSE {cur_name}")
    conn.commit()

    if p_ok == 1:
        log(f"{email:<42} id={id_rol}", p_ok, p_msg, "CREADO")
        return

    if p_ok == -10:
        # Ya existe — actualizar password
        cur.execute("BEGIN")
        cur.execute("""
            SELECT id_usuario FROM usuario WHERE email = %s
        """, [email])
        row = cur.fetchone()
        conn.commit()

        if row:
            id_usuario = row[0]
            cur_upd = f"cur_upd_{idx}"
            cur.execute("BEGIN")
            cur.execute(
                "CALL sp_gestion_usuario('U', %s, NULL, NULL, %s, NULL, %s)",
                [id_usuario, cur_upd, pw_hash],
            )
            p_ok2, p_msg2 = cur.fetchone()[:2]
            cur.execute(f"CLOSE {cur_upd}")
            conn.commit()
            log(f"{email:<42} id={id_rol}", 1, "Password actualizado", "ACTUALIZADO")
        else:
            log(f"{email:<42} id={id_rol}", p_ok, p_msg, "YA EXISTE")
        return

    log(f"{email:<42} id={id_rol}", p_ok, p_msg)


def crear_usuarios(conn, cur, lista: list, seccion: str):
    print(f"\n── {seccion} {'─' * (54 - len(seccion))}")
    for idx, (email, password, rol, id_rol) in enumerate(lista):
        crear_o_actualizar(conn, cur, email, password, rol, id_rol, idx)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 60)
    print("  seed_users.py  |  MediNFC — usuarios de prueba")
    print("═" * 60)

    conn = get_conn()
    cur  = conn.cursor()

    crear_usuarios(conn, cur, MEDICOS,    "MÉDICO (id 1)")
    crear_usuarios(conn, cur, CUIDADORES, "CUIDADORES (ids 1-2)")

    # ── Verificación final con SP ─────────────────────────────────────────────
    cur.execute("BEGIN")
    cur.execute("CALL sp_rep_lista_usuarios('cur_verify')")
    cur.execute("FETCH ALL FROM cur_verify")
    rows = cur.fetchall()
    conn.commit()

    # cols: id_usuario, email, rol_usuario, activo, ultimo_acceso,
    #       nombre_persona, id_rol
    print("\n── USUARIOS REGISTRADOS " + "─" * 37)
    print(f"  {'Email':<42} {'Rol':<10} {'id':>4}  {'Nombre':<28} OK")
    print(f"  {'─'*42} {'─'*10} {'─'*4}  {'─'*28} ──")
    for r in rows:
        id_usr, email, rol, activo, _, nombre, id_rol = r
        estado = "✓" if activo else "✗"
        nombre_display = nombre or "—"
        print(f"  {email:<42} {rol:<10} {str(id_rol):>4}  {nombre_display:<28} {estado}")

    total_med  = sum(1 for r in rows if r[2] == "medico")
    total_cuid = sum(1 for r in rows if r[2] == "cuidador")

    print(f"\n  Total médicos:    {total_med}")
    print(f"  Total cuidadores: {total_cuid}")
    print(f"  Total usuarios:   {len(rows)}")
    print("\n" + "═" * 60)
    print("  Contraseña de todos los usuarios:  Medinfc2024!")
    print("  Médico:    carlos.mendoza@medinfc.mx")
    print("  Cuidador:  sofia.castro@medinfc.mx")
    print("  Cuidador:  javier.mora@medinfc.mx")
    print("═" * 60 + "\n")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()