#- logger_exec.py
import os
from datetime import datetime

# Tomar configuración desde variables de entorno (mismo esquema que logger.py)
LOG_DIR = os.getenv("LOG_DIR", "./logs")

# Archivo de log específico para comandos (si no se define, cae en ./logs/exec.log)
LOG_FILE = os.getenv("LOG_EXEC_FILE", os.path.join(LOG_DIR, "exec.log"))

def ensure_log_dir():
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    except Exception as e:
        # Nunca romper por logging
        print(f"[LoggerExecError] Cannot create log dir for {LOG_FILE}: {e}")

def log_command(cmd: str, output: str, source: str = "telegram"):
    """Guarda una entrada en el log de ejecuciones (no debe romper la API)."""
    ensure_log_dir()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Limita salida para mantener legibilidad
    out = output or ""
    summary = (out[:300] + "...") if len(out) > 300 else out

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] ({source}) CMD={cmd}\nOUT={summary}\n\n")
    except Exception as e:
        print(f"[LoggerExecError] Cannot write log file {LOG_FILE}: {e}")
