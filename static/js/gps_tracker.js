/**
 * MediNFC — GPS Tracker del Cuidador
 * Envía coordenadas GPS a MongoDB cada 30 segundos.
 * Solo activo cuando el rol de sesión es 'cuidador'.
 */

class GPSTracker {
    constructor(idPaciente, nombrePaciente) {
        this.idPaciente      = idPaciente;
        this.nombrePaciente  = nombrePaciente;
        this.watchId         = null;
        this.intervaloEnvio  = null;
        this.ultimaPos       = null;
        this.activo          = false;
    }

    iniciar() {
        if (!navigator.geolocation) {
            console.warn("GPS no disponible en este dispositivo");
            return;
        }

        // Obtener posición inicial
        navigator.geolocation.getCurrentPosition(
            (pos) => {
                this.ultimaPos = pos;
                this.enviarUbicacion(pos);
            },
            (err) => console.warn("Error GPS inicial:", err.message),
            { enableHighAccuracy: true, timeout: 10000 }
        );

        // Escuchar cambios de posición
        this.watchId = navigator.geolocation.watchPosition(
            (pos) => { this.ultimaPos = pos; },
            (err) => console.warn("Error GPS watch:", err.message),
            { enableHighAccuracy: true, maximumAge: 15000, timeout: 10000 }
        );

        // Enviar al servidor cada 30 segundos
        this.intervaloEnvio = setInterval(() => {
            if (this.ultimaPos) {
                this.enviarUbicacion(this.ultimaPos);
            }
        }, 30000);

        this.activo = true;
        console.log("GPS Tracker iniciado para paciente:", this.idPaciente);
    }

    enviarUbicacion(pos) {
        const datos = {
            lat:             pos.coords.latitude,
            lon:             pos.coords.longitude,
            precision:       pos.coords.accuracy,
            id_paciente:     this.idPaciente,
            nombre_paciente: this.nombrePaciente
        };

        fetch("/api/ubicacion-gps", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(datos)
        })
        .then(r => r.json())
        .then(data => {
            if (data.ok) {
                console.log("GPS enviado:", datos.lat, datos.lon);
                const dot = document.getElementById("gps-status");
                if (dot) dot.style.background = "#2ecc71";
            }
        })
        .catch(err => {
            console.warn("Error al enviar GPS:", err);
            const dot = document.getElementById("gps-status");
            if (dot) dot.style.background = "#e74c3c";
        });
    }

    detener() {
        if (this.watchId !== null) {
            navigator.geolocation.clearWatch(this.watchId);
            this.watchId = null;
        }
        if (this.intervaloEnvio !== null) {
            clearInterval(this.intervaloEnvio);
            this.intervaloEnvio = null;
        }
        this.activo = false;
        console.log("GPS Tracker detenido");
    }
}

// Iniciar automáticamente si hay datos de paciente en la página
document.addEventListener("DOMContentLoaded", function() {
    const el = document.getElementById("gps-tracker-data");
    if (el) {
        const idPaciente     = el.dataset.idPaciente;
        const nombrePaciente = el.dataset.nombrePaciente;
        if (idPaciente) {
            window.gpsTracker = new GPSTracker(idPaciente, nombrePaciente);
            window.gpsTracker.iniciar();
        }
    }
});
