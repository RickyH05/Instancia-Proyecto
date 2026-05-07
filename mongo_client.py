import os
import traceback
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient

_mongo_client = None


def get_mongo_db():
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017/"))
    return _mongo_client[os.getenv("MONGO_DB", "medinfc_mongo")]


# ─── Lectura: gráficas ───────────────────────────────────────────────────────

def get_adherencia_por_medico(pg_id_medico, dias=14):
    """Gráfica 1 — barras comparativas del dashboard médico."""
    try:
        db    = get_mongo_db()
        desde = datetime.now(timezone.utc) - timedelta(days=dias)
        return list(db.historico_adherencia.aggregate([
            {"$match": {"pg_id_medico": pg_id_medico, "fecha": {"$gte": desde}}},
            {"$group": {
                "_id":    "$pg_id_paciente",
                "nombre": {"$first": "$nombre_paciente"},
                "pct":    {"$avg":  "$metricas.pct_adherencia"},
            }},
            {"$sort": {"pct": -1}},
        ]))
    except Exception as e:
        registrar_log_sistema(
            "ERROR", "mongo_client.get_adherencia_por_medico",
            f"Fallo al leer historico_adherencia para médico {pg_id_medico}",
            str(e), traceback.format_exc()
        )
        return []


def get_historial_paciente(pg_id_paciente, dias=14):
    """Gráfica 2 — series de tiempo para la gráfica de adherencia del cuidador."""
    try:
        db    = get_mongo_db()
        desde = datetime.now(timezone.utc) - timedelta(days=dias)
        return list(db.historico_adherencia.find(
            {"pg_id_paciente": pg_id_paciente, "fecha": {"$gte": desde}},
            {"_id": 0, "fecha": 1, "metricas": 1, "detalle_medicamentos": 1, "nombre_paciente": 1},
        ).sort("fecha", 1))
    except Exception as e:
        registrar_log_sistema(
            "ERROR", "mongo_client.get_historial_paciente",
            f"Fallo al leer historico_adherencia para paciente {pg_id_paciente}",
            str(e), traceback.format_exc()
        )
        return []


def get_pct_promedio_paciente(pg_id_paciente, dias=14):
    """Gráfica 3 — solid gauge en el perfil del paciente (médico)."""
    try:
        db    = get_mongo_db()
        desde = datetime.now(timezone.utc) - timedelta(days=dias)
        resultado = list(db.historico_adherencia.aggregate([
            {"$match": {"pg_id_paciente": pg_id_paciente, "fecha": {"$gte": desde}}},
            {"$group": {"_id": None, "pct": {"$avg": "$metricas.pct_adherencia"}}},
        ]))
        return round(resultado[0]["pct"], 1) if resultado else 0.0
    except Exception as e:
        registrar_log_sistema(
            "ERROR", "mongo_client.get_pct_promedio_paciente",
            f"Fallo al calcular pct promedio para paciente {pg_id_paciente}",
            str(e), traceback.format_exc()
        )
        return 0.0


def get_badge_alertas(pg_id_medico):
    """Badge de alertas pendientes para el médico."""
    try:
        db = get_mongo_db()
        return db.alertas_rt.count_documents({
            "medico.pg_id_medico": pg_id_medico,
            "estado": "pendiente",
        })
    except Exception as e:
        registrar_log_sistema(
            "ERROR", "mongo_client.get_badge_alertas",
            f"Fallo al contar alertas para médico {pg_id_medico}",
            str(e), traceback.format_exc()
        )
        return 0


# ─── Escritura: logs ─────────────────────────────────────────────────────────

def registrar_log_acceso(pg_id_usuario, email, rol, ip, exitoso,
                         user_agent=None, motivo_fallo=None):
    """Inserta en logs_acceso (TTL 90 d)."""
    try:
        db = get_mongo_db()
        db.logs_acceso.insert_one({
            "pg_id_usuario": pg_id_usuario,
            "email":         email,
            "rol":           rol,
            "ip":            ip,
            "exitoso":       exitoso,
            "user_agent":    user_agent,
            "motivo_fallo":  motivo_fallo,
            "timestamp":     datetime.now(timezone.utc),
        })
    except Exception:
        pass  # log de acceso nunca debe romper el flujo de login


def registrar_log_sistema(nivel, modulo, mensaje, detalle=None, traceback_str=None):
    """Inserta en logs_sistema (TTL 30 d). nivel: ERROR | WARNING | INFO."""
    try:
        db = get_mongo_db()
        db.logs_sistema.insert_one({
            "nivel":     nivel,
            "modulo":    modulo,
            "mensaje":   mensaje,
            "detalle":   detalle,
            "traceback": traceback_str,
            "timestamp": datetime.now(timezone.utc),
        })
    except Exception:
        pass  # no lanzar excepciones desde el logger


# ─── Escritura: eventos NFC ──────────────────────────────────────────────────

def sync_evento_nfc(datos):
    """Upsert en eventos_nfc_rt por pg_id_evento."""
    try:
        db = get_mongo_db()
        db.eventos_nfc_rt.update_one(
            {"pg_id_evento": datos["pg_id_evento"]},
            {"$set": {**datos, "timestamp_sync": datetime.now(timezone.utc)}},
            upsert=True,
        )
    except Exception as e:
        registrar_log_sistema(
            "ERROR", "mongo_client.sync_evento_nfc",
            f"Fallo al sincronizar evento NFC {datos.get('pg_id_evento')}",
            str(e), traceback.format_exc()
        )


# ─── Escritura: NFC fallidos y GPS ──────────────────────────────────────────

def registrar_log_nfc_fallido(pg_id_cuidador, nombre_cuidador,
                               uid_nfc, motivo, ip=None):
    """
    Registra en MongoDB cuando un escaneo NFC falla.
    Motivos posibles: 'uid_desconocido', 'etiqueta_inactiva',
                      'receta_vencida', 'duplicado'
    """
    try:
        db = get_mongo_db()
        db.logs_nfc_fallidos.insert_one({
            "pg_id_cuidador":  pg_id_cuidador,
            "nombre_cuidador": nombre_cuidador,
            "uid_nfc":         uid_nfc,
            "motivo":          motivo,
            "ip":              ip,
            "timestamp":       datetime.now(timezone.utc),
        })
    except Exception:
        pass  # MongoDB nunca interrumpe el flujo principal


def agregar_ubicacion_gps(pg_id_paciente, pg_id_cuidador,
                           nombre_cuidador, latitud, longitud,
                           precision_metros=None, en_domicilio=None):
    """
    Guarda una coordenada GPS del teléfono del cuidador en MongoDB.
    PostgreSQL solo guarda la última coordenada en ubicacion_gps.
    MongoDB acumula el trayecto completo en ubicaciones_gps_hist.
    pg_id_gps se usa 0 cuando viene del teléfono (no dispositivo físico).
    """
    try:
        db = get_mongo_db()
        db.ubicaciones_gps_hist.insert_one({
            "pg_id_gps":       0,
            "pg_id_paciente":  pg_id_paciente,
            "pg_id_cuidador":  pg_id_cuidador,
            "nombre_cuidador": nombre_cuidador if nombre_cuidador else "",
            "coordenadas": {
                "latitud":          latitud,
                "longitud":         longitud,
                "precision_metros": precision_metros,
            },
            "timestamp":    datetime.now(timezone.utc),
            "en_domicilio": en_domicilio,
            "fuente":       "telefono",
        })
    except Exception:
        pass  # MongoDB nunca interrumpe el flujo principal


def get_trayecto_cuidador(pg_id_cuidador, horas=24):
    """
    Retorna el trayecto GPS del cuidador en las últimas N horas.
    Solo disponible en MongoDB — PostgreSQL no guarda el historial.
    """
    try:
        db    = get_mongo_db()
        desde = datetime.now(timezone.utc) - timedelta(hours=horas)
        return list(db.ubicaciones_gps_hist.find(
            {"pg_id_cuidador": pg_id_cuidador,
             "timestamp": {"$gte": desde}},
            {"_id": 0, "coordenadas": 1, "timestamp": 1,
             "en_domicilio": 1},
        ).sort("timestamp", 1))
    except Exception:
        return []


def get_trayectos_todos_pacientes(pg_id_medico, horas=24):
    """
    Retorna trayectos GPS de los cuidadores agrupados por pg_id_cuidador.
    pg_id_medico se acepta por firma pero la colección no filtra por médico.
    """
    try:
        db    = get_mongo_db()
        desde = datetime.now(timezone.utc) - timedelta(hours=horas)
        cursor = db.ubicaciones_gps_hist.find(
            {"timestamp": {"$gte": desde}},
            {"_id": 0, "pg_id_cuidador": 1, "nombre_cuidador": 1,
             "pg_id_paciente": 1, "coordenadas": 1,
             "timestamp": 1, "en_domicilio": 1},
        ).sort("timestamp", 1)

        trayectos = {}
        for punto in cursor:
            id_cuid = punto["pg_id_cuidador"]
            if id_cuid not in trayectos:
                trayectos[id_cuid] = {
                    "nombre": punto.get("nombre_cuidador", "Cuidador"),
                    "puntos": [],
                }
            trayectos[id_cuid]["puntos"].append({
                "lat":          punto["coordenadas"]["latitud"],
                "lon":          punto["coordenadas"]["longitud"],
                "timestamp":    punto["timestamp"].strftime("%Y-%m-%d %H:%M")
                                if hasattr(punto["timestamp"], "strftime")
                                else str(punto["timestamp"]),
                "en_domicilio": punto.get("en_domicilio", None),
            })
        return trayectos
    except Exception:
        return {}


def get_logs_acceso(limite=100):
    """Últimos N intentos de login desde MongoDB."""
    try:
        db = get_mongo_db()
        return list(db.logs_acceso.find(
            {},
            {"_id": 0, "pg_id_usuario": 1, "email": 1, "rol": 1,
             "ip": 1, "exitoso": 1, "timestamp": 1,
             "user_agent": 1, "motivo_fallo": 1}
        ).sort("timestamp", -1).limit(limite))
    except Exception:
        return []


def get_logs_sistema(limite=100):
    """Últimos N logs del sistema desde MongoDB."""
    try:
        db = get_mongo_db()
        return list(db.logs_sistema.find(
            {},
            {"_id": 0, "nivel": 1, "modulo": 1, "mensaje": 1,
             "timestamp": 1, "detalle": 1, "traceback": 1}
        ).sort("timestamp", -1).limit(limite))
    except Exception:
        return []


def get_logs_nfc_fallidos(limite=100):
    """Últimos N escaneos NFC fallidos desde MongoDB."""
    try:
        db = get_mongo_db()
        return list(db.logs_nfc_fallidos.find(
            {},
            {"_id": 0, "pg_id_cuidador": 1, "nombre_cuidador": 1,
             "uid_nfc": 1, "motivo": 1, "ip": 1, "timestamp": 1}
        ).sort("timestamp", -1).limit(limite))
    except Exception:
        return []
