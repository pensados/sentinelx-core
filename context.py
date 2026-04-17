#- context.py
from datetime import datetime, timedelta
import time

class SentinelContext:
    """Memoria contextual de SentinelX (estado actual del agente)."""

    def __init__(self):
        self.start_time = time.time()
        self.last_command = None
        self.last_output = None
        self.last_status = None
        self.last_update = None
        self.blocked_count = 0
        self.error_count = 0
        self.total_executions = 0

    def update(self, cmd: str, output: str, status: str = "ok"):
        self.last_command = cmd
        self.last_output = output[:200]  # truncar para evitar logs gigantes
        self.last_status = status
        self.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.total_executions += 1

        if status == "blocked":
            self.blocked_count += 1
        elif status == "error":
            self.error_count += 1

    def uptime(self):
        delta = timedelta(seconds=int(time.time() - self.start_time))
        return str(delta)

    def get_state(self):
        return {
            "uptime": self.uptime(),
            "last_command": self.last_command,
            "last_output": self.last_output,
            "last_status": self.last_status,
            "last_update": self.last_update,
            "total_executions": self.total_executions,
            "blocked_count": self.blocked_count,
            "error_count": self.error_count,
        }

# Instancia global
context = SentinelContext()
