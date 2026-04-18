"""
seed_users.py  |  Crea los usuarios de acceso para médicos y cuidadores
medi_nfc2  v7
==============================================================================

Ejecutar DESPUÉS de seed_data.sql:
    pip install psycopg2-binary bcrypt python-dotenv
    python seed_users.py

El script es idempotente: si un usuario ya existe (p_ok=-10) lo reporta
como ⚠ y continúa sin abortar.

Usuarios creados (email / contraseña / rol):
─────────────────────────────────────────────────────────────────────────────
MÉDICOS — Sección A (ids 1-5)
  a.vargas@clinicamedi.mx       Medico1234!    medico  (Cardiología)
  s.herrera@clinicamedi.mx      Medico1234!    medico  (Geriatría)
  r.guzman@clinicamedi.mx       Medico1234!    medico  (Medicina General)
  c.lozano@clinicamedi.mx       Medico1234!    medico  (Neurología)
  m.pena@clinicamedi.mx         Medico1234!    medico  (Nutrición)

MÉDICOS — Escenarios (ids 6-9)
  a.ramirez@clinicamedi.mx      Medico1234!    medico  (Medicina General — E1)
  g.castillo@clinicamedi.mx     Medico1234!    medico  (Geriatría — E2/E3)
  f.moreno@clinicamedi.mx       Medico1234!    medico  (Medicina General — E4)
  v.vega@clinicamedi.mx         Medico1234!    medico  (Nutrición — E5)

CUIDADORES — Sección A (ids 1-8)
  a.morales@enfermerianl.mx     Cuidador1234!  cuidador (Adriana, formal)
  j.torres@enfermerianl.mx      Cuidador1234!  cuidador (Juan, formal)
  patricia.luna@gmail.com       Cuidador1234!  cuidador (Patricia, informal)
  l.garcia@enfermerianl.mx      Cuidador1234!  cuidador (Luz, formal)
  r.espinoza@hotmail.com        Cuidador1234!  cuidador (Ricardo, informal)
  n.reyes@enfermerianl.mx       Cuidador1234!  cuidador (Norma, formal)
  claudia.vasquez@gmail.com     Cuidador1234!  cuidador (Claudia, informal)
  d.mendez@enfermerianl.mx      Cuidador1234!  cuidador (Diego, formal)

CUIDADORES — Escenarios (ids 9-14)
  rosa.ibarra@seed.com          Cuidador1234!  cuidador (Rosa, formal — E1)
  jorge.paredes@seed.com        Cuidador1234!  cuidador (Jorge, formal — E2)
  ana.leal@seed.com             Cuidador1234!  cuidador (Ana, informal — E3)
  diana.mora@seed.com           Cuidador1234!  cuidador (Diana, formal — E4 orig)
  felix.rios@seed.com           Cuidador1234!  cuidador (Félix, formal — E4 nuevo)
  carmen.pena@seed.com          Cuidador1234!  cuidador (Carmen, formal — E5)
─────────────────────────────────────────────────────────────────────────────
"""

import sys
import bcrypt
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# ── Conexión ─────────────────────────────────────────────────────────────────
DB_DSN = "postgresql://proyectofinal_user:444@localhost:5432/medi_nfc2"


def get_conn():
    return psycopg2.connect(DB_DSN)


# ── Utilidades ────────────────────────────────────────────────────────────────

def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def ok(label: str, p_ok: int, p_msg: str):
    marca = "✓" if p_ok == 1 else ("⚠" if p_ok == -10 else "✗")
    print(f"  {marca}  {label}: {p_msg}")
    if p_ok not in (1, -10):  # -10 = email ya registrado (idempotente)
        print(f"     ERROR FATAL — abortando. Código: {p_ok}")
        sys.exit(1)


# ── Datos de usuarios ─────────────────────────────────────────────────────────
#
# Estructura: (email, password_plano, rol, id_en_tabla_medico_o_cuidador)
# Los emails y IDs deben coincidir exactamente con seed_data.sql

MEDICOS = [
    # ── Sección A (ids 1-5) ───────────────────────────────────────────────────
    ("a.vargas@clinicamedi.mx",  "Medico1234!", "medico", 1),  # Cardiología
    ("s.herrera@clinicamedi.mx", "Medico1234!", "medico", 2),  # Geriatría
    ("r.guzman@clinicamedi.mx",  "Medico1234!", "medico", 3),  # Medicina General
    ("c.lozano@clinicamedi.mx",  "Medico1234!", "medico", 4),  # Neurología
    ("m.pena@clinicamedi.mx",    "Medico1234!", "medico", 5),  # Nutrición
    # ── Escenarios (ids 6-9) ──────────────────────────────────────────────────
    ("a.ramirez@clinicamedi.mx",  "Medico1234!", "medico", 6),  # Med. General E1
    ("g.castillo@clinicamedi.mx", "Medico1234!", "medico", 7),  # Geriatría   E2/E3
    ("f.moreno@clinicamedi.mx",   "Medico1234!", "medico", 8),  # Med. General E4
    ("v.vega@clinicamedi.mx",     "Medico1234!", "medico", 9),  # Nutrición   E5
]

CUIDADORES = [
    # ── Sección A (ids 1-8) ───────────────────────────────────────────────────
    ("a.morales@enfermerianl.mx",  "Cuidador1234!", "cuidador", 1),  # Adriana, formal
    ("j.torres@enfermerianl.mx",   "Cuidador1234!", "cuidador", 2),  # Juan, formal
    ("patricia.luna@gmail.com",    "Cuidador1234!", "cuidador", 3),  # Patricia, informal
    ("l.garcia@enfermerianl.mx",   "Cuidador1234!", "cuidador", 4),  # Luz, formal
    ("r.espinoza@hotmail.com",     "Cuidador1234!", "cuidador", 5),  # Ricardo, informal
    ("n.reyes@enfermerianl.mx",    "Cuidador1234!", "cuidador", 6),  # Norma, formal
    ("claudia.vasquez@gmail.com",  "Cuidador1234!", "cuidador", 7),  # Claudia, informal
    ("d.mendez@enfermerianl.mx",   "Cuidador1234!", "cuidador", 8),  # Diego, formal
    # ── Escenarios (ids 9-14) ─────────────────────────────────────────────────
    ("rosa.ibarra@seed.com",       "Cuidador1234!", "cuidador",  9),  # Rosa,   formal  E1
    ("jorge.paredes@seed.com",     "Cuidador1234!", "cuidador", 10),  # Jorge,  formal  E2
    ("ana.leal@seed.com",          "Cuidador1234!", "cuidador", 11),  # Ana,    informal E3
    ("diana.mora@seed.com",        "Cuidador1234!", "cuidador", 12),  # Diana,  formal  E4-orig
    ("felix.rios@seed.com",        "Cuidador1234!", "cuidador", 13),  # Félix,  formal  E4-nuevo
    ("carmen.pena@seed.com",       "Cuidador1234!", "cuidador", 14),  # Carmen, formal  E5
]


# ── Main ──────────────────────────────────────────────────────────────────────

def crear_usuarios(conn, cur, lista: list, seccion: str):
    """Itera la lista y llama sp_crear_usuario_admin por cada entrada."""
    print(f"\n── {seccion} {'─'*(54 - len(seccion))}")
    for idx, (email, password, rol, id_rol) in enumerate(lista):
        pw_hash  = hash_pw(password)
        cur_name = f"cur_{rol[:4]}_{idx}"
        cur.execute("BEGIN")
        cur.execute(
            "CALL sp_crear_usuario_admin(%s, %s, %s::rol_usuario_enum, %s, NULL, NULL, %s)",
            [email, pw_hash, rol, id_rol, cur_name]
        )
        p_ok, p_msg, _ = cur.fetchone()
        cur.execute(f"CLOSE {cur_name}")
        conn.commit()
        ok(f"{email:<40} id={id_rol}", p_ok, p_msg)


def main():
    print("\n" + "═" * 60)
    print("  seed_users.py  |  Creación de usuarios medi_nfc2")
    print("═" * 60)

    conn = get_conn()
    cur  = conn.cursor()

    # ── Sección A ─────────────────────────────────────────────────────────────
    medicos_a    = [u for u in MEDICOS    if u[3] <= 5]
    cuidadores_a = [u for u in CUIDADORES if u[3] <= 8]

    crear_usuarios(conn, cur, medicos_a,    "MÉDICOS — Sección A (ids 1-5)")
    crear_usuarios(conn, cur, cuidadores_a, "CUIDADORES — Sección A (ids 1-8)")

    # ── Escenarios ────────────────────────────────────────────────────────────
    medicos_sc    = [u for u in MEDICOS    if u[3] >= 6]
    cuidadores_sc = [u for u in CUIDADORES if u[3] >= 9]

    crear_usuarios(conn, cur, medicos_sc,    "MÉDICOS — Escenarios (ids 6-9)")
    crear_usuarios(conn, cur, cuidadores_sc, "CUIDADORES — Escenarios (ids 9-14)")

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

    print("\n── USUARIOS CREADOS " + "─" * 41)
    print(f"  {'Email':<40} {'Rol':<10} {'id':>4}  {'Nombre':<25} OK")
    print(f"  {'─'*40} {'─'*10} {'─'*4}  {'─'*25} ──")
    for email, rol, nombre, id_rol, activo in rows:
        estado = "✓" if activo else "✗"
        print(f"  {email:<40} {rol:<10} {id_rol:>4}  {nombre:<25} {estado}")

    total_med  = sum(1 for _, r, *_ in rows if r == "medico")
    total_cuid = sum(1 for _, r, *_ in rows if r == "cuidador")

    print(f"\n  Total médicos:    {total_med}")
    print(f"  Total cuidadores: {total_cuid}")
    print(f"  Total usuarios:   {len(rows)}")
    print("\n" + "═" * 60)
    print("  Contraseñas:")
    print("    Médicos:    Medico1234!")
    print("    Cuidadores: Cuidador1234!")
    print("═" * 60 + "\n")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()