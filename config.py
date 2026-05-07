import os
import uuid

import psycopg

_DB_HOST     = "127.0.0.1"
_DB_NAME     = "medi_nfc2"
_DB_USER     = "proyectofinal_user"
_DB_PASS     = "444"
_DB_PORT     = "5432"
_SECRET_KEY  = "Grupo1"
_ADMIN_EMAIL = "admin@medinfc.local"
_ADMIN_HASH  = "$2b$12$yrMiWtApVrY6RTyEabeWT.w/Be4XnE1sZDQJOS7fkgpzZJrbICzMm"

_ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
_MAX_FOTO_BYTES = 2 * 1024 * 1024  # 2 MB

# Se sobreescribe en app.py después de crear la instancia Flask
_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "static", "img", "uploads")


def get_db():
    return psycopg.connect(
        host=_DB_HOST,
        dbname=_DB_NAME,
        user=_DB_USER,
        password=_DB_PASS,
        port=_DB_PORT,
    )


def guardar_foto_perfil(file_storage):
    if not file_storage or file_storage.filename == "":
        return None
    from flask import flash
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        flash("Formato de imagen no permitido. Usa PNG, JPG, JPEG o WEBP.", "danger")
        return None
    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > _MAX_FOTO_BYTES:
        flash("La imagen supera el límite de 2 MB.", "danger")
        return None
    filename = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(_UPLOAD_DIR, filename))
    return f"uploads/{filename}"
