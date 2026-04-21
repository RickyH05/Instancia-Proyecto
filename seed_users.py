"""
seed_users.py  |  Crea los usuarios de acceso para médicos y cuidadores
medi_nfc2  — datos de prueba (seed_test_data.sql)
==============================================================================

Ejecutar DESPUÉS de seed_test_data.sql:
    pip install psycopg[binary] bcrypt python-dotenv
    python seed_users.py

El script es idempotente: si un usuario ya existe (p_ok=-10) lo reporta
como ⚠  y continúa sin abortar.

Usuarios creados (email / contraseña / rol):
─────────────────────────────────────────────────────────────────────────────
MÉDICO (id 1)
  dr.garza@medinfc.mx           ~~    medico  (Geriatría + Cardiología)

CUIDADORES (ids 1-3)
  maria.lopez@medinfc.mx        Password1!     cuidador  (María,    formal)
  carlos.ramirez@medinfc.mx     Password1!     cuidador  (Carlos,   informal)
  patricia.morales@medinfc.mx   Password1!     cuidador  (Patricia, informal)
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


def log(label: str, p_ok: int, p_msg: str):
    marca = "✓" if p_ok == 1 else ("⚠" if p_ok == -10 else "✗")
    print(f"  {marca}  {label}: {p_msg}")
    if p_ok not in (1, -10):
        print(f"     ERROR FATAL — abortando. Código: {p_ok}")
        sys.exit(1)


# ── Datos de usuarios ─────────────────────────────────────────────────────────
#  (email, contraseña_plana, rol, id_en_tabla_medico_o_cuidador)
#  Los emails e IDs deben coincidir exactamente con seed_test_data.sql

MEDICOS = [
    ("dr.garza@medinfc.mx", "Password1!", "medico", 1),  # Roberto Garza — Geriatría/Cardiología
]

CUIDADORES = [
    ("maria.lopez@medinfc.mx",      "Password1!", "cuidador", 1),  # María    — formal
    ("carlos.ramirez@medinfc.mx",   "Password1!", "cuidador", 2),  # Carlos   — informal
    ("patricia.morales@medinfc.mx", "Password1!", "cuidador", 3),  # Patricia — informal
]


# ── Creación de usuarios ──────────────────────────────────────────────────────

def crear_usuarios(conn, cur, lista: list, seccion: str):
    """Itera la lista y llama sp_crear_usuario_admin por cada entrada."""
    print(f"\n── {seccion} {'─' * (54 - len(seccion))}")
    for idx, (email, password, rol, id_rol) in enumerate(lista):
        pw_hash  = hash_pw(password)
        cur_name = f"cur_{rol[:4]}_{idx}"

        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_crear_usuario_admin(%s, %s, %s::rol_usuario_enum, %s, NULL, NULL, %s)",
            [email, pw_hash, rol, id_rol, cur_name],
        )
        p_ok, p_msg, _ = cur.fetchone()
        cur.execute(f"CLOSE {cur_name}")
        conn.commit()

        log(f"{email:<42} id={id_rol}", p_ok, p_msg)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 60)
    print("  seed_users.py  |  Usuarios de prueba — medi_nfc2")
    print("═" * 60)

    conn = get_conn()
    cur  = conn.cursor()

    crear_usuarios(conn, cur, MEDICOS,    "MÉDICO (id 1)")
    crear_usuarios(conn, cur, CUIDADORES, "CUIDADORES (ids 1-3)")

    # ── Verificación final ────────────────────────────────────────────────────
    cur.execute("""
        SELECT u.email,
               u.rol_usuario,
               CASE u.rol_usuario
                   WHEN 'medico'   THEN m.nombre || ' ' || m.apellido_p
                   WHEN 'cuidador' THEN c.nombre || ' ' || c.apellido_p
               END AS nombre,
               COALESCE(u.id_medico, u.id_cuidador) AS id_rol,
               u.activo
        FROM   usuario u
        LEFT JOIN medico   m ON m.id_medico   = u.id_medico
        LEFT JOIN cuidador c ON c.id_cuidador = u.id_cuidador
        ORDER BY u.rol_usuario DESC, COALESCE(u.id_medico, u.id_cuidador)
    """)
    rows = cur.fetchall()

    print("\n── USUARIOS REGISTRADOS " + "─" * 37)
    print(f"  {'Email':<42} {'Rol':<10} {'id':>4}  {'Nombre':<25} OK")
    print(f"  {'─'*42} {'─'*10} {'─'*4}  {'─'*25} ──")
    for email, rol, nombre, id_rol, activo in rows:
        estado = "✓" if activo else "✗"
        print(f"  {email:<42} {rol:<10} {id_rol:>4}  {nombre:<25} {estado}")

    total_med  = sum(1 for _, r, *_ in rows if r == "medico")
    total_cuid = sum(1 for _, r, *_ in rows if r == "cuidador")

    print(f"\n  Total médicos:    {total_med}")
    print(f"  Total cuidadores: {total_cuid}")
    print(f"  Total usuarios:   {len(rows)}")
    print("\n" + "═" * 60)
    print("  Contraseña de todos los usuarios:  Password1!")
    print("═" * 60 + "\n")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()