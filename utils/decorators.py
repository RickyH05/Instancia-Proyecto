from functools import wraps

from flask import redirect, session, url_for


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
