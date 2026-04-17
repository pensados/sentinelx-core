#- logger.py
import os
from datetime import datetime

# Tomar configuración desde variables de entorno
LOG_DIR = os.getenv("LOG_DIR", "./logs")
LOG_FILE = os.getenv("LOG_FILE", os.path.join(LOG_DIR, "sentinelx.log"))

def ensure_log_dir():
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except Exception as e:
        # Nunca romper ejecución por logging
        print(f"[LoggerError] Cannot create log dir {LOG_DIR}: {e}")

def log_exec(cmd: str, output: str, allowed: bool = True):
    ensure_log_dir()

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "ok" if allowed else "blocked"

    # Truncar output para evitar logs gigantes
    safe_output = (output or "")[:120]

    line = f"[{timestamp}] CMD={cmd} | STATUS={status} | OUTPUT={safe_output}\n"

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        # Logging jamás debe tumbar la API
        print(f"[LoggerError] Cannot write log file {LOG_FILE}: {e}")
