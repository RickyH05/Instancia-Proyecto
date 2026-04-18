# Agente 1 — agent-setup | medi_nfc2

## Tu rol
Eres el agente de **infraestructura base** del proyecto Flask medi_nfc2.
Generas el esqueleto del proyecto: `app.py` con autenticación, decoradores, conexión a BD, login/logout, y los templates base. **No generas** pantallas de médico, cuidador, ni admin — de eso se encargan los otros agentes.

---

## Stack
- Python Flask (sin Blueprints, todo en `app.py`)
- **psycopg (versión 3)** — `import psycopg` (NO `psycopg2`, NO SQLAlchemy, NO ORM)
- bcrypt para contraseñas
- Jinja2 para templates
- python-dotenv para variables de entorno
- BD: `medi_nfc2` | usuario: `proyectofinal_user` | contraseña: `444`
- Conexión: `postgresql://proyectofinal_user:444@localhost:5432/medi_nfc2`

---

## Lo que DEBES generar

### 1. `requirements.txt`
```
Flask==3.0.0
psycopg[binary]==3.2.0
bcrypt==4.1.2
python-dotenv==1.0.0
```

### 2. `.env.example`
```
SECRET_KEY=cambia-esto-por-un-secreto-largo
DB_HOST=localhost
DB_PORT=5432
DB_NAME=medi_nfc2
DB_USER=proyectofinal_user
DB_PASSWORD=444
ADMIN_EMAIL=admin@medinfc.mx
ADMIN_PASSWORD_HASH=
# Generar con: python -c "import bcrypt; print(bcrypt.hashpw(b'tu_password', bcrypt.gensalt()).decode())"
```

### 3. `app.py` (estructura base)
Debe contener en este orden:

1. **Imports:** Flask, psycopg, bcrypt, os, functools, datetime, load_dotenv
2. **`app = Flask(__name__)` + `app.secret_key = os.getenv('SECRET_KEY')`**
3. **Función `get_db()`** que devuelve una conexión psycopg:
```python
def get_db():
    return psycopg.connect(
        host=os.getenv('DB_HOST'),
        port=os.getenv('DB_PORT'),
        dbname=os.getenv('DB_NAME'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD')
    )
```

4. **Decoradores `login_requerido` y `rol_requerido`:**
```python
def login_requerido(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            flash('Debes iniciar sesión', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrapper

def rol_requerido(*roles):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if session.get('rol') not in roles:
                flash('No tienes permiso para acceder a esta sección', 'error')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return wrapper
    return decorator
```

5. **Helper `badge_alertas()`** que retorna el contador para el menú:
```python
def badge_alertas():
    if 'user_id' not in session or session['rol'] == 'admin':
        return 0
    try:
        with get_db() as conn, conn.cursor() as cur:
            cur.execute("BEGIN")
            cur.execute("CALL sp_rep_badge_alertas('cur_badge', %s, %s)",
                        [session['user_id'], session['rol']])
            cur.execute("FETCH ALL FROM cur_badge")
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else 0
    except Exception:
        return 0

@app.context_processor
def inject_badge():
    return {'total_alertas_pendientes': badge_alertas()}
```

6. **Ruta `/` (index)** que redirige según rol:
```python
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if session['rol'] == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif session['rol'] == 'medico':
        return redirect(url_for('medico_dashboard'))
    elif session['rol'] == 'cuidador':
        return redirect(url_for('cuidador_dashboard'))
    return redirect(url_for('login'))
```

Los endpoints `admin_dashboard`, `medico_dashboard` y `cuidador_dashboard` **NO los implementas tú** — los demás agentes los crearán. Solo pon el redirect y deja un comentario `# TODO: implementado por agent-X`.

7. **Rutas `/login` y `/logout`** — esta es la **única excepción** donde se hace SELECT directo a la BD (porque bcrypt debe verificarse en Python). El login de admin usa `ADMIN_EMAIL` y `ADMIN_PASSWORD_HASH` del `.env`.

```python
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email']
        password = request.form['password']

        # Admin (credenciales en .env)
        if email == os.getenv('ADMIN_EMAIL'):
            admin_hash = os.getenv('ADMIN_PASSWORD_HASH', '').encode()
            if admin_hash and bcrypt.checkpw(password.encode(), admin_hash):
                session['user_id'] = 0
                session['rol']     = 'admin'
                session['id_rol']  = None
                session['nombre']  = 'Administrador'
                return redirect(url_for('index'))
            flash('Credenciales inválidas', 'error')
            return render_template('login.html')

        # Médico / Cuidador (tabla usuario)
        try:
            with get_db() as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT u.id_usuario, u.password_hash, u.rol_usuario,
                           COALESCE(u.id_medico, u.id_cuidador) AS id_rol,
                           CASE u.rol_usuario
                               WHEN 'medico'   THEN m.nombre || ' ' || m.apellido_p
                               WHEN 'cuidador' THEN c.nombre || ' ' || c.apellido_p
                           END AS nombre
                    FROM   usuario u
                    LEFT JOIN medico   m ON m.id_medico   = u.id_medico
                    LEFT JOIN cuidador c ON c.id_cuidador = u.id_cuidador
                    WHERE  u.email = %s AND u.activo = TRUE
                """, [email])
                row = cur.fetchone()

                if row and bcrypt.checkpw(password.encode(), row[1].encode()):
                    session['user_id'] = row[0]
                    session['rol']     = row[2]
                    session['id_rol']  = row[3]
                    session['nombre']  = row[4]
                    cur.execute("""
                        INSERT INTO log_acceso (id_usr, email, rol, ip, exitoso)
                        VALUES (%s, %s, %s, %s, TRUE)
                    """, [row[0], email, row[2], request.remote_addr])
                    conn.commit()
                    return redirect(url_for('index'))
                else:
                    cur.execute("""
                        INSERT INTO log_acceso (id_usr, email, rol, ip, exitoso)
                        SELECT id_usuario, %s, rol_usuario::TEXT, %s, FALSE
                        FROM   usuario WHERE email = %s LIMIT 1
                    """, [email, request.remote_addr, email])
                    conn.commit()
                    flash('Credenciales inválidas', 'error')
        except Exception as e:
            flash(f'Error al iniciar sesión: {e}', 'error')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada', 'success')
    return redirect(url_for('login'))
```

8. **`if __name__ == '__main__': app.run(debug=True)`**

### 4. Templates que DEBES generar

#### `templates/base.html`
Template padre con:
- `<head>` con Bootstrap 5 (CDN)
- Navbar con: logo, nombre del usuario, badge de alertas pendientes (si existe), botón logout
- Bloque de flash messages (success, error, warning)
- `{% block content %}{% endblock %}`
- El navbar debe mostrar enlaces distintos según `session.rol`:
  - admin → Dashboard, Médicos, Pacientes, Cuidadores, Medicamentos, Dispositivos, Auditoría, Log
  - medico → Dashboard, Pacientes, Alertas, Adherencia, Mapa
  - cuidador → Dashboard, Agenda del día, Escanear NFC, Alertas, Historial

Deja los enlaces como `{{ url_for('admin_dashboard') }}`, etc. — aunque no existan aún, Flask no falla en template hasta que se visita la ruta.

#### `templates/login.html`
Formulario simple de login (email + password) que hereda de `base.html`. Sin navbar (o con navbar vacío para usuarios no autenticados).

### 5. Estructura de carpetas
```
proyecto/
├── app.py
├── requirements.txt
├── .env.example
├── .gitignore  (incluir .env)
├── /templates
│   ├── base.html
│   └── login.html
└── /static
    └── /css
        └── style.css  (vacío o con 2-3 reglas básicas)
```

---

## Reglas absolutas

### Regla #1 — NUNCA queries directos excepto login
Los demás agentes **solo usarán SPs** (CALL). Tú solo haces SELECT directo en el login porque bcrypt debe verificarse en Python. No escribas ningún otro SELECT, INSERT o UPDATE.

### Regla #2 — psycopg versión 3
`import psycopg` — NUNCA `import psycopg2`. El placeholder sigue siendo `%s`.

### Regla #3 — Sesión Flask
Los cuatro campos obligatorios:
```python
session['user_id']  # id_usuario o 0 para admin
session['rol']      # 'medico' | 'cuidador' | 'admin'
session['id_rol']   # id_medico | id_cuidador | None
session['nombre']   # nombre completo
```

---

## Lo que NO debes hacer
- ❌ No generes rutas `/admin/*`, `/medico/*`, `/cuidador/*` ni `/api/*` — eso es de los otros agentes
- ❌ No generes templates de dashboards de cada rol — solo `base.html` y `login.html`
- ❌ No uses Blueprints — todo en un solo `app.py`
- ❌ No instales SQLAlchemy ni ningún ORM
- ❌ No hagas queries directas a tablas fuera del login

---

## Al terminar
Tu entregable es:
1. `app.py` (200-300 líneas aprox)
2. `templates/base.html`
3. `templates/login.html`
4. `static/css/style.css`
5. `requirements.txt`
6. `.env.example`
7. `.gitignore`

Después de ti vendrán los agentes:
- agent-admin → rutas `/admin/*`
- agent-medico → rutas `/medico/*`
- agent-cuidador → rutas `/cuidador/*`
- agent-api-exportacion → rutas `/api/*` y `/export/*`

Cada uno **agregará** sus rutas al final de tu `app.py`, **sin sobreescribir** lo que generaste.