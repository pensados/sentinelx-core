# agent.py
from fastapi import FastAPI, Request, Header, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, model_validator
from typing import Optional, Literal
import subprocess
import os
import time
import json
import uuid
import hashlib
import shutil
from pathlib import Path
from logger import log_exec
from context import context
from logger_exec import log_command

app = FastAPI(title="SentinelX", version="0.3.5")

AGENT_TOKEN = os.getenv("SENTINEL_TOKEN", "changeme")

BASE_DIR = Path(__file__).resolve().parent
BIN_DIR = BASE_DIR / "bin"
PENSA_SAFE_EDIT_BIN = os.getenv("SENTINEL_SAFE_EDIT_BIN", str(BIN_DIR / "sentinelx-safe-edit"))

UPLOAD_BASE_DIR = Path(os.getenv("SENTINEL_UPLOAD_DIR", "/var/lib/sentinelx/uploads")).resolve()
UPLOAD_TMP_DIR = UPLOAD_BASE_DIR / ".sentinelx_uploads"
MAX_UPLOAD_BYTES = int(os.getenv("SENTINEL_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024 * 1024)))

PATH_INDEX = {
    "root": {"path": "/", "description": "Filesystem root"},
    "home": {"path": "/home", "description": "User home directories"},
    "etc": {"path": "/etc", "description": "System configuration"},
    "var": {"path": "/var", "description": "Variable system data"},
    "var_log": {"path": "/var/log", "description": "System and service logs"},
    "var_www": {"path": "/var/www", "description": "Common web roots"},
    "usr_local_bin": {"path": "/usr/local/bin", "description": "Locally installed executables"},
    "opt": {"path": "/opt", "description": "Optional software"},
    "systemd_units": {"path": "/etc/systemd/system", "description": "systemd unit files"},
}

PLAYBOOKS = {
    "nginx_debug": {
        "description": "Basic diagnostics for Nginx or reverse proxy issues",
        "steps": [
            "systemctl status nginx",
            "nginx -t",
            "tail /var/log/nginx/error.log",
            "tail /var/log/nginx/access.log",
            "ls /etc/nginx/sites-available",
        ],
    },
    "docker_debug": {
        "description": "Basic diagnostics for Docker engine and containers",
        "steps": [
            "systemctl status docker",
            "docker ps",
            "docker images",
        ],
    },
    "systemd_debug": {
        "description": "Basic diagnostics for systemd-managed services",
        "steps": [
            "ls /etc/systemd/system",
            "systemctl status nginx",
            "systemctl status docker",
        ],
    },
    "network_debug": {
        "description": "Basic network diagnostics",
        "steps": [
            "ip a",
            "ip route",
            "ss -tuln",
            "ping 8.8.8.8",
            "nslookup localhost",
        ],
    },
}

ALLOWED_COMMANDS = [
    'uptime', 'pwd', 'whoami', 'id', 'ls', 'tree', 'cat', 'sudo cat', 'head', 'tail', 'less',
    'grep', 'find', 'sort', 'du -h', 'df -h', 'touch', 'echo', 'printf', 'tee', 'cp', 'mv',
    'mkdir', 'sudo touch', 'getfacl', 'rm', 'ln -s', 'unlink', 'chmod', 'chown',
    'docker', 'sudo docker', 'nginx -t', 'sudo nginx -t', 'ip a', 'ip route', 'ss -tuln',
    'netstat -tuln', 'ping', 'traceroute', 'tcpdump', 'dig', 'nslookup',
    'cloudflared tunnel list', 'cloudflared tunnel run', 'cloudflared tunnel info',
    'sudo tee', 'sudo cp', 'sudo mv', 'sudo mkdir', 'sudo rm', 'sudo ln -s', 'sudo unlink',
    'sudo chmod', 'sudo chown', 'sudo systemctl', 'curl', 'wget', 'nft', 'sudo nft',
    'sed', 'sudo sed', 'python3', 'sudo python3', 'systemctl', 'journalctl', 'wc', 'jq',
    'lsof', 'stat', 'namei', 'realpath', 'diff', 'cmp', 'apt', 'tar', 'gzip', 'unzip', 'zip',
    'git', 'set', 'if', 'cd', 'which', 'ssh', 'sudo ssh', 'bash -lc',
    'pensa-safe-edit', 'sudo pensa-safe-edit',
]

SERVICE_ACTIONS = {
    "sentinelx": {
        "unit": "sentinelx.service",
        "manager": "systemd",
        "actions": ["status", "start", "stop", "restart"],
        "description": "SentinelX agent service",
        "checks": {
            "status": "systemctl status sentinelx.service",
            "logs": "journalctl -u sentinelx.service"
        },
        "risk": "medium",
        "action_commands": {
            "status": "systemctl status sentinelx.service",
            "start": "sudo systemctl start sentinelx.service",
            "stop": "sudo systemctl stop sentinelx.service",
            "restart": "sudo systemctl restart sentinelx.service"
        }
    },
    "nginx": {
        "unit": "nginx",
        "manager": "systemd",
        "actions": ["status", "start", "stop", "restart", "reload", "validate"],
        "description": "Nginx reverse proxy",
        "checks": {
            "status": "systemctl status nginx",
            "validate": "sudo nginx -t",
            "logs": "tail /var/log/nginx/error.log"
        },
        "risk": "low",
        "action_commands": {
            "status": "systemctl status nginx",
            "start": "sudo systemctl start nginx",
            "stop": "sudo systemctl stop nginx",
            "restart": "sudo systemctl restart nginx",
            "reload": "sudo systemctl reload nginx",
            "validate": "sudo nginx -t"
        }
    },
    "docker": {
        "unit": "docker",
        "manager": "systemd",
        "actions": ["status", "start", "stop", "restart"],
        "description": "Docker daemon",
        "checks": {
            "status": "systemctl status docker",
            "runtime": "docker ps"
        },
        "risk": "high",
        "action_commands": {
            "status": "systemctl status docker",
            "start": "sudo systemctl start docker",
            "stop": "sudo systemctl stop docker",
            "restart": "sudo systemctl restart docker"
        }
    }
}


class EditRequest(BaseModel):
    path: str
    sudo: bool = False
    mode: Literal["replace", "regex", "replace-block", "append", "prepend", "write"]

    old: Optional[str] = None
    new_text: Optional[str] = None
    pattern: Optional[str] = None
    start_marker: Optional[str] = None
    end_marker: Optional[str] = None

    count: int = 0
    multiline: bool = False
    dotall: bool = False
    interpret_escapes: bool = False
    backup_dir: Optional[str] = None
    validator: Optional[str] = None
    validator_preset: Optional[Literal["nginx", "json", "python", "sh", "yaml", "systemd"]] = None
    diff: bool = False
    dry_run: bool = False
    allow_no_change: bool = False
    create: bool = False

    @model_validator(mode="after")
    def validate_request(self):
        if not self.path or not self.path.strip():
            raise ValueError("path es obligatorio")

        if self.validator and self.validator_preset:
            raise ValueError("No puedes usar validator y validator_preset juntos")

        if self.count < 0:
            raise ValueError("count no puede ser negativo")

        if self.mode == "replace":
            if self.old is None:
                raise ValueError("En mode=replace debes indicar old")
            if self.new_text is None:
                raise ValueError("En mode=replace debes indicar new_text")

        elif self.mode == "regex":
            if not self.pattern:
                raise ValueError("En mode=regex debes indicar pattern")
            if self.new_text is None:
                raise ValueError("En mode=regex debes indicar new_text")

        elif self.mode == "replace-block":
            if not self.start_marker or not self.end_marker:
                raise ValueError("En mode=replace-block debes indicar start_marker y end_marker")
            if self.new_text is None:
                raise ValueError("En mode=replace-block debes indicar new_text")

        elif self.mode in ("append", "prepend", "write"):
            if self.new_text is None:
                raise ValueError(f"En mode={self.mode} debes indicar new_text")

        return self


class EditCompleteRequest(BaseModel):
    upload_id: str
    path: str
    sudo: bool = False
    mode: Literal["replace", "regex", "replace-block", "append", "prepend", "write"]

    pattern: Optional[str] = None
    start_marker: Optional[str] = None
    end_marker: Optional[str] = None

    count: int = 0
    multiline: bool = False
    dotall: bool = False
    interpret_escapes: bool = False
    backup_dir: Optional[str] = None
    validator: Optional[str] = None
    validator_preset: Optional[Literal["nginx", "json", "python", "sh", "yaml", "systemd"]] = None
    diff: bool = False
    dry_run: bool = False
    allow_no_change: bool = False
    create: bool = False

    @model_validator(mode="after")
    def validate_request(self):
        if not self.upload_id:
            raise ValueError("upload_id es obligatorio")
        if not self.path or not self.path.strip():
            raise ValueError("path es obligatorio")
        if self.validator and self.validator_preset:
            raise ValueError("No puedes usar validator y validator_preset juntos")
        if self.count < 0:
            raise ValueError("count no puede ser negativo")
        if self.mode == "regex" and not self.pattern:
            raise ValueError("En mode=regex debes indicar pattern")
        if self.mode == "replace-block" and (not self.start_marker or not self.end_marker):
            raise ValueError("En mode=replace-block debes indicar start_marker y end_marker")
        return self


class ScriptRunRequest(BaseModel):
    interpreter: Literal["bash", "python3"]
    content: str
    args: Optional[list[str]] = None
    cwd: Optional[str] = None
    timeout: int = 60
    sudo: bool = False
    cleanup: bool = True
    filename: Optional[str] = None
    env: Optional[dict[str, str]] = None

    @model_validator(mode="after")
    def validate_request(self):
        if not self.content or not self.content.strip():
            raise ValueError("content es obligatorio")
        if self.timeout < 1 or self.timeout > 300:
            raise ValueError("timeout debe estar entre 1 y 300 segundos")
        if self.args is not None:
            for arg in self.args:
                if not isinstance(arg, str):
                    raise ValueError("args debe ser una lista de strings")
        if self.env is not None:
            for k, v in self.env.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise ValueError("env debe ser un dict[str, str]")
        return self


def execute_command(cmd: str):
    start = time.time()
    try:
        print(f"[SentinelX] Ejecutando: {cmd}", flush=True)

        result = subprocess.run(
            ["bash", "-lc", cmd],
            text=True,
            capture_output=True,
            timeout=60
        )

        duration = round(time.time() - start, 2)
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        if not stdout and not stderr:
            output = "⚠️ Sin salida"
        else:
            output = f"{stdout}\n{stderr}".strip()

        return {
            "output": output,
            "duration": duration,
            "returncode": result.returncode
        }

    except subprocess.TimeoutExpired:
        return {"output": "⏱️ Timeout", "duration": round(time.time() - start, 2), "returncode": -1}
    except Exception as e:
        return {"output": f"❌ Error: {e}", "duration": round(time.time() - start, 2), "returncode": -1}


def get_command_help(cmd: str):
    try:
        result = subprocess.run(
            ["bash", "-lc", cmd],
            text=True,
            capture_output=True,
            timeout=10
        )

        return (result.stdout or result.stderr or "No help available").strip()

    except Exception as e:
        return f"Error getting help: {e}"

def _ensure_upload_dirs():
    UPLOAD_BASE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True)


def _require_agent_token(authorization: str):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = authorization.split(" ")[1]
    if token != AGENT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


def _safe_upload_path(target_path: str) -> Path:
    if not target_path or not target_path.strip():
        raise HTTPException(status_code=400, detail="Missing target_path")

    raw = target_path.strip().lstrip("/")
    candidate = (UPLOAD_BASE_DIR / raw).resolve()
    base = UPLOAD_BASE_DIR.resolve()

    if candidate != base and base not in candidate.parents:
        raise HTTPException(status_code=400, detail="target_path escapes upload base dir")

    return candidate


def _write_upload_file(src: UploadFile, dest: Path):
    hasher = hashlib.sha256()
    size = 0
    with dest.open("wb") as f:
        while True:
            chunk = src.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="File too large")
            hasher.update(chunk)
            f.write(chunk)
    return size, hasher.hexdigest()

def run_process(args: list[str], timeout: int = 60, env=None, cwd=None):
    start = time.time()
    try:
        print(f"[SentinelX] Ejecutando argv: {args}", flush=True)

        result = subprocess.run(
            args,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
        )

        duration = round(time.time() - start, 2)
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()

        if not stdout and not stderr:
            output = "⚠️ Sin salida"
        else:
            output = f"{stdout}\n{stderr}".strip()

        return {
            "output": output,
            "duration": duration,
            "returncode": result.returncode
        }

    except subprocess.TimeoutExpired:
        return {
            "output": "⏱️ Timeout",
            "duration": round(time.time() - start, 2),
            "returncode": -1
        }
    except Exception as e:
        return {
            "output": f"❌ Error: {e}",
            "duration": round(time.time() - start, 2),
            "returncode": -1
        }


def _build_edit_command(
    workdir: Path,
    path: str,
    sudo: bool,
    mode: str,
    old: str | None = None,
    new_text: str | None = None,
    pattern: str | None = None,
    start_marker: str | None = None,
    end_marker: str | None = None,
    count: int = 0,
    multiline: bool = False,
    dotall: bool = False,
    interpret_escapes: bool = False,
    backup_dir: str | None = None,
    validator: str | None = None,
    validator_preset: str | None = None,
    diff: bool = False,
    dry_run: bool = False,
    allow_no_change: bool = False,
    create: bool = False,
    old_file_path: Path | None = None,
    new_file_path: Path | None = None,
) -> list[str]:
    args = []

    if sudo:
        args.append("sudo")

    args.extend([PENSA_SAFE_EDIT_BIN, path, "--mode", mode])

    if old_file_path is not None:
        args.extend(["--old-file", str(old_file_path)])
    elif old is not None:
        p = workdir / "old.txt"
        p.write_text(old, encoding="utf-8")
        args.extend(["--old-file", str(p)])

    if new_file_path is not None:
        args.extend(["--new-file", str(new_file_path)])
    elif new_text is not None:
        p = workdir / "new.txt"
        p.write_text(new_text, encoding="utf-8")
        args.extend(["--new-file", str(p)])

    if pattern:
        args.extend(["--pattern", pattern])

    if start_marker:
        args.extend(["--start-marker", start_marker])

    if end_marker:
        args.extend(["--end-marker", end_marker])

    if count:
        args.extend(["--count", str(count)])

    if multiline:
        args.append("--multiline")

    if dotall:
        args.append("--dotall")

    if interpret_escapes:
        args.append("--interpret-escapes")

    if backup_dir:
        args.extend(["--backup-dir", backup_dir])

    if validator:
        args.extend(["--validator", validator])

    if validator_preset:
        args.extend(["--validator-preset", validator_preset])

    if diff:
        args.append("--diff")

    if dry_run:
        args.append("--dry-run")

    if allow_no_change:
        args.append("--allow-no-change")

    if create:
        args.append("--create")

    return args


def _edit_upload_dir(upload_id: str) -> Path:
    _ensure_upload_dirs()
    upload_dir = UPLOAD_TMP_DIR / f"edit_{upload_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def _safe_edit_upload_file(upload_id: str, filename: str) -> Path:
    upload_dir = _edit_upload_dir(upload_id)
    safe_name = Path(filename).name
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return upload_dir / safe_name


def _cleanup_edit_upload(upload_id: str):
    try:
        shutil.rmtree(UPLOAD_TMP_DIR / f"edit_{upload_id}", ignore_errors=True)
    except Exception:
        pass

def execute_service_action(service: str, action: str):
    meta = SERVICE_ACTIONS.get(service)
    if not meta:
        return {"error": f"Service not allowed: {service}", "status": "blocked"}

    action = (action or "").strip()
    if not action:
        return {"error": "Missing action", "status": "blocked"}

    if action not in meta.get("actions", []):
        return {
            "error": f"Action not allowed for {service}: {action}",
            "status": "blocked",
            "allowed_actions": meta.get("actions", [])
        }

    cmd = meta.get("action_commands", {}).get(action)
    if not cmd:
        return {
            "error": f"No command mapped for {service}:{action}",
            "status": "blocked"
        }

    result = execute_command(cmd)
    result["ok"] = result.get("returncode", 1) == 0
    result["service"] = service
    result["action"] = action
    result["command"] = cmd
    return result

@app.get("/capabilities")
async def get_capabilities(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = authorization.split(" ")[1]
    if token != AGENT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    pensa_safe_edit_help = get_command_help(PENSA_SAFE_EDIT_BIN)
    pensa_safe_edit_help = f"""{pensa_safe_edit_help}

Guia de uso recomendada para SentinelX:
- Usar replace para cambios literales pequenos y exactos.
- Usar regex cuando el valor pueda variar pero el patron sea estable.
- Usar replace-block para bloques HTML, Nginx, JSON, YAML o config delimitados por marcadores unicos.
- Usar --new-file para contenido multilinea o bloques grandes; evitar pasar textos largos inline.
- Usar --interpret-escapes solo cuando necesites \\n, \\t o escapes Unicode inline en --new o --old.
- Preferir --validator-preset cuando exista uno adecuado; usar --validator para validaciones personalizadas. Ejemplos: --validator-preset nginx, --validator-preset json, o --validator 'python3 -m json.tool {{file}}'.
- Preferir backups y diff en cambios delicados; el comando ya genera backup automatico y acepta --diff para revisar cambios.
- Para cambios sensibles, usar --dry-run primero; si algo sale mal, usar --restore con un backup previo.
- Para archivos grandes, evitar heredocs largos, tee masivo o reescritura completa; preferir sentinelx-safe-edit.
- Para archivos en /etc o protegidos, usar sudo sentinelx-safe-edit.
- Si el cambio afecta servicios, validar primero y reiniciar o recargar solo despues de una validacion exitosa.
"""


    return {
        "agent": "sentinelx",
        "version": "0.3.5",
        "allowed_commands": ALLOWED_COMMANDS,
        "service_actions": {name: {k: v for k, v in meta.items() if k != "action_commands"} for name, meta in SERVICE_ACTIONS.items()},
        "categories": {
            "read": ["cat", "head", "tail", "grep", "find", "journalctl", "jq", "stat", "realpath"],
            "write": ["echo", "printf", "tee", "sed", "touch", "chmod", "chown"],
            "filesystem": ["ls", "cp", "mv", "rm", "mkdir", "ln -s", "unlink", "tree"],
            "edit": ["/edit", "/edit/upload/init", "/edit/upload/file", "/edit/upload/complete"],
            "script": ["/script/run"],
            "services": ["systemctl", "docker", "nginx -t", "cloudflared tunnel list", "cloudflared tunnel info"],
            "network": ["ip a", "ip route", "ss -tuln", "netstat -tuln", "ping", "traceroute", "tcpdump", "dig", "nslookup", "curl", "wget", "lsof"],
            "tooling": ["python3", "git", "bash -lc", "sentinelx-safe-edit"],
            "upload": ["/upload", "/upload/init", "/upload/chunk", "/upload/complete"],
            "privileged": [cmd for cmd in ALLOWED_COMMANDS if cmd.startswith("sudo")]
        },
        "upload_capabilities": {
            "base_dir": str(UPLOAD_BASE_DIR),
            "temp_dir": str(UPLOAD_TMP_DIR),
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "modes": {
                "single": {"endpoint": "/upload", "method": "POST", "fields": ["file", "target_path", "overwrite"]},
                "chunked": {
                    "init": {"endpoint": "/upload/init", "method": "POST"},
                    "chunk": {"endpoint": "/upload/chunk", "method": "POST", "fields": ["upload_id", "index", "chunk"]},
                    "complete": {"endpoint": "/upload/complete", "method": "POST"}
                }
            },
            "path_rules": {
                "target_path_is_relative_to_base_dir": True,
                "path_traversal_blocked": True,
                "overwrite_supported": True
            }
        },
        "edit_capabilities": {
            "json_endpoint": {"endpoint": "/edit", "method": "POST"},
            "file_endpoint": {
                "init": {"endpoint": "/edit/upload/init", "method": "POST"},
                "file": {"endpoint": "/edit/upload/file", "method": "POST", "fields": ["upload_id", "role", "file"]},
                "complete": {"endpoint": "/edit/upload/complete", "method": "POST"}
            }
        },
        "script_capabilities": {
            "run_endpoint": {"endpoint": "/script/run", "method": "POST"},
            "interpreters": ["bash", "python3"],
            "features": {
                "temporary_files": True,
                "cleanup_default": True,
                "sudo_supported": True,
                "cwd_supported": True,
                "env_supported": True,
                "timeout_max_seconds": 300
            }
        },
        "locations": PATH_INDEX,
        "playbooks": PLAYBOOKS,
        "help": {
            "safe_edit": pensa_safe_edit_help,
        "upload": "Upload simple: POST /upload multipart/form-data con file, target_path, overwrite. Upload grande: POST /upload/init, luego /upload/chunk, y cerrar con /upload/complete.",
        "edit": (
            "Edicion estructurada sin quoting: "
            "POST /edit con JSON para cambios pequenos/medianos. "
            "Para bloques grandes: POST /edit/upload/init, luego /edit/upload/file con role=new|old, "
            "y cerrar con /edit/upload/complete."
            ),
        "script": (
            "Ejecucion de scripts temporales sin pasar contenido por shell inline: "
            "POST /script/run con interpreter bash|python3, content, args, cwd, timeout, sudo y cleanup."
            ),
        }
    }


@app.post("/exec")
async def exec_command(request: Request, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = authorization.split(" ")[1]
    if token != AGENT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    data = await request.json()
    cmd = data.get("cmd")

    if not cmd:
        raise HTTPException(status_code=400, detail="Missing command")

    allowed_match = any(cmd.startswith(allowed) for allowed in ALLOWED_COMMANDS)
    if not allowed_match:
        context.update(cmd, "blocked", status="blocked")
        log_exec(cmd, "blocked", allowed=False)
        return {"error": f"Command not allowed: {cmd}"}

    result = execute_command(cmd)
    log_exec(cmd, result["output"])
    context.update(cmd, result["output"], status="ok")
    log_command(cmd, result["output"], source="sentinelx")
    return result


@app.post("/edit")
async def edit_file(request: EditRequest, authorization: str = Header(None)):
    _require_agent_token(authorization)
    _ensure_upload_dirs()
    workdir = UPLOAD_TMP_DIR / f"edit_job_{uuid.uuid4().hex}"
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        args = _build_edit_command(
            workdir=workdir,
            path=request.path,
            sudo=request.sudo,
            mode=request.mode,
            old=request.old,
            new_text=request.new_text,
            pattern=request.pattern,
            start_marker=request.start_marker,
            end_marker=request.end_marker,
            count=request.count,
            multiline=request.multiline,
            dotall=request.dotall,
            interpret_escapes=request.interpret_escapes,
            backup_dir=request.backup_dir,
            validator=request.validator,
            validator_preset=request.validator_preset,
            diff=request.diff,
            dry_run=request.dry_run,
            allow_no_change=request.allow_no_change,
            create=request.create,
        )

        result = run_process(args)
        ok = result.get("returncode", 1) == 0

        key = f"edit:{request.path}"
        log_exec(
            f"{'sudo ' if request.sudo else ''}sentinelx-safe-edit {request.path} --mode {request.mode}",
            result.get("output", ""),
            allowed=True
        )
        context.update(key, result.get("output", ""), status="ok" if ok else "error")
        log_command(key, result.get("output", ""), source="sentinelx")

        return {
            "ok": ok,
            "path": request.path,
            "mode": request.mode,
            "sudo": request.sudo,
            "command": args,
            **result
        }

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@app.post("/script/run")
async def script_run(request: ScriptRunRequest, authorization: str = Header(None)):
    _require_agent_token(authorization)
    _ensure_upload_dirs()

    script_id = uuid.uuid4().hex
    workdir = UPLOAD_TMP_DIR / f"script_job_{script_id}"
    workdir.mkdir(parents=True, exist_ok=True)

    ext = "sh" if request.interpreter == "bash" else "py"
    safe_name = Path(request.filename).name if request.filename else f"script.{ext}"
    script_path = workdir / safe_name

    try:
        script_path.write_text(request.content, encoding="utf-8")
        os.chmod(script_path, 0o700)

        args = []
        if request.sudo:
            args.append("sudo")
        if request.interpreter == "bash":
            args.extend(["bash", str(script_path)])
        else:
            args.extend(["python3", str(script_path)])
        if request.args:
            args.extend(request.args)

        env = os.environ.copy()
        if request.env:
            env.update(request.env)

        result = run_process(args, timeout=request.timeout, env=env, cwd=request.cwd)
        ok = result.get("returncode", 1) == 0

        key = f"script:{safe_name}"
        log_exec(
            f"{'sudo ' if request.sudo else ''}{request.interpreter} {safe_name}",
            result.get("output", ""),
            allowed=True
        )
        context.update(key, result.get("output", ""), status="ok" if ok else "error")
        log_command(key, result.get("output", ""), source="sentinelx")

        response = {
            "ok": ok,
            "interpreter": request.interpreter,
            "sudo": request.sudo,
            "cwd": request.cwd,
            "cleanup": request.cleanup,
            "command": args,
            **result
        }
        if not request.cleanup:
            response["script_path"] = str(script_path)
            response["workdir"] = str(workdir)
        return response

    finally:
        if request.cleanup:
            shutil.rmtree(workdir, ignore_errors=True)


@app.post("/restart")
async def restart_service(request: Request, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = authorization.split(" ")[1]
    if token != AGENT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    data = await request.json()
    service = data.get("service")

    if not service:
        raise HTTPException(status_code=400, detail="Missing service")

    meta = SERVICE_ACTIONS.get(service)
    if not meta:
        context.update(service, "blocked", status="blocked")
        log_exec(service, "blocked", allowed=False)
        return {"error": f"Service not allowed: {service}"}

    cmd = meta.get("action_commands", {}).get("restart")
    if not cmd:
        context.update(service, "blocked", status="blocked")
        log_exec(service, "blocked", allowed=False)
        return {"error": f"Restart not configured for service: {service}"}

    subprocess.Popen(["bash", "-lc", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    message = f"{service} restart triggered"
    log_exec(service, message)
    context.update(service, message, status="ok")
    log_command(service, message, source="sentinelx")

    return {
        "ok": True,
        "service": service,
        "message": message
    }

@app.post("/service")
async def service_action(request: Request, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = authorization.split(" ")[1]
    if token != AGENT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    data = await request.json()
    service = data.get("service")
    action = data.get("action")

    if not service:
        raise HTTPException(status_code=400, detail="Missing service")
    if not action:
        raise HTTPException(status_code=400, detail="Missing action")

    result = execute_service_action(service, action)
    key = service + ":" + action

    if result.get("status") == "blocked":
        context.update(key, "blocked", status="blocked")
        log_exec(key, "blocked", allowed=False)
        return result

    log_exec(key, result.get("output", ""))
    context.update(key, result.get("output", ""), status="ok")
    log_command(key, result.get("output", ""), source="sentinelx")
    return result


@app.post("/upload")
async def upload_file_endpoint(
    authorization: str = Header(None),
    file: UploadFile = File(...),
    target_path: str = Form(...),
    overwrite: bool = Form(False),
):
    _require_agent_token(authorization)
    _ensure_upload_dirs()

    dest = _safe_upload_path(target_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists() and not overwrite:
        raise HTTPException(status_code=409, detail="File already exists")

    tmp = UPLOAD_TMP_DIR / (str(uuid.uuid4()) + ".upload")
    try:
        size, sha256 = _write_upload_file(file, tmp)
        tmp.replace(dest)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass

    return {
        "ok": True,
        "mode": "single",
        "target_path": str(dest),
        "size": size,
        "sha256": sha256,
        "filename": file.filename,
    }


@app.post("/upload/init")
async def upload_init_endpoint(
    request: Request,
    authorization: str = Header(None),
):
    _require_agent_token(authorization)
    _ensure_upload_dirs()

    data = await request.json()
    target_path = data.get("target_path")
    overwrite = bool(data.get("overwrite", False))
    total_size = int(data.get("total_size", 0) or 0)
    filename = data.get("filename")

    dest = _safe_upload_path(target_path)
    if dest.exists() and not overwrite:
        raise HTTPException(status_code=409, detail="File already exists")

    upload_id = uuid.uuid4().hex
    upload_dir = UPLOAD_TMP_DIR / upload_id
    parts_dir = upload_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "upload_id": upload_id,
        "target_path": str(dest),
        "overwrite": overwrite,
        "total_size": total_size,
        "filename": filename,
    }
    (upload_dir / "meta.json").write_text(json.dumps(meta))

    return {
        "ok": True,
        "mode": "chunked",
        "upload_id": upload_id,
        "target_path": str(dest),
        "total_size": total_size,
    }


@app.post("/upload/chunk")
async def upload_chunk_endpoint(
    authorization: str = Header(None),
    upload_id: str = Form(...),
    index: int = Form(...),
    chunk: UploadFile = File(...),
):
    _require_agent_token(authorization)
    _ensure_upload_dirs()

    upload_dir = UPLOAD_TMP_DIR / upload_id
    meta_file = upload_dir / "meta.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="upload_id not found")

    parts_dir = upload_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    part_path = parts_dir / f"{index:08d}.part"

    size = 0
    with part_path.open("wb") as f:
        while True:
            data = chunk.file.read(1024 * 1024)
            if not data:
                break
            size += len(data)
            f.write(data)

    return {
        "ok": True,
        "upload_id": upload_id,
        "index": index,
        "chunk_size": size,
    }


@app.post("/upload/complete")
async def upload_complete_endpoint(
    request: Request,
    authorization: str = Header(None),
):
    _require_agent_token(authorization)
    _ensure_upload_dirs()

    data = await request.json()
    upload_id = data.get("upload_id")
    sha256_expected = data.get("sha256")

    if not upload_id:
        raise HTTPException(status_code=400, detail="Missing upload_id")

    upload_dir = UPLOAD_TMP_DIR / upload_id
    meta_file = upload_dir / "meta.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="upload_id not found")

    meta = json.loads(meta_file.read_text())
    dest = Path(meta["target_path"]).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    tmp = upload_dir / "assembled.bin"
    parts = sorted((upload_dir / "parts").glob("*.part"))
    if not parts:
        raise HTTPException(status_code=400, detail="No chunks uploaded")

    hasher = hashlib.sha256()
    total = 0
    with tmp.open("wb") as out:
        for part in parts:
            with part.open("rb") as pf:
                while True:
                    chunk = pf.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="File too large")
                    hasher.update(chunk)
                    out.write(chunk)

    sha256 = hasher.hexdigest()
    expected_size = int(meta.get("total_size", 0) or 0)
    if expected_size and total != expected_size:
        raise HTTPException(status_code=400, detail=f"Size mismatch: expected {expected_size}, got {total}")
    if sha256_expected and sha256_expected != sha256:
        raise HTTPException(status_code=400, detail="sha256 mismatch")
    if dest.exists() and not meta.get("overwrite", False):
        raise HTTPException(status_code=409, detail="File already exists")

    tmp.replace(dest)

    try:
        shutil.rmtree(upload_dir, ignore_errors=True)
    except Exception:
        pass

    return {
        "ok": True,
        "mode": "chunked",
        "upload_id": upload_id,
        "target_path": str(dest),
        "size": total,
        "sha256": sha256,
    }

@app.post("/edit/upload/init")
async def edit_upload_init(request: Request, authorization: str = Header(None)):
    _require_agent_token(authorization)
    _ensure_upload_dirs()

    upload_id = uuid.uuid4().hex
    upload_dir = _edit_upload_dir(upload_id)

    meta = {
        "upload_id": upload_id,
        "created_at": int(time.time())
    }
    (upload_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    return {
        "ok": True,
        "upload_id": upload_id,
        "temp_dir": str(upload_dir)
    }
    

@app.post("/edit/upload/file")
async def edit_upload_file(
    authorization: str = Header(None),
    upload_id: str = Form(...),
    role: str = Form(...),
    file: UploadFile = File(...),
):
    _require_agent_token(authorization)
    _ensure_upload_dirs()

    if role not in ("new", "old"):
        raise HTTPException(status_code=400, detail="role must be 'new' or 'old'")

    upload_dir = _edit_upload_dir(upload_id)
    meta_file = upload_dir / "meta.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="upload_id not found")

    dest = upload_dir / f"{role}.bin"

    size, sha256 = _write_upload_file(file, dest)

    return {
        "ok": True,
        "upload_id": upload_id,
        "role": role,
        "filename": file.filename,
        "stored_as": str(dest),
        "size": size,
        "sha256": sha256
    }


@app.post("/edit/upload/complete")
async def edit_upload_complete(request: EditCompleteRequest, authorization: str = Header(None)):
    _require_agent_token(authorization)
    _ensure_upload_dirs()

    upload_dir = _edit_upload_dir(request.upload_id)
    meta_file = upload_dir / "meta.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="upload_id not found")

    new_file = upload_dir / "new.bin"
    old_file = upload_dir / "old.bin"

    if not new_file.exists():
        raise HTTPException(status_code=400, detail="Missing uploaded file for role=new")

    if request.mode == "replace" and not old_file.exists():
        raise HTTPException(status_code=400, detail="Missing uploaded file for role=old")

    workdir = UPLOAD_TMP_DIR / f"edit_job_{uuid.uuid4().hex}"
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        args = _build_edit_command(
            workdir=workdir,
            path=request.path,
            sudo=request.sudo,
            mode=request.mode,
            pattern=request.pattern,
            start_marker=request.start_marker,
            end_marker=request.end_marker,
            count=request.count,
            multiline=request.multiline,
            dotall=request.dotall,
            interpret_escapes=request.interpret_escapes,
            backup_dir=request.backup_dir,
            validator=request.validator,
            validator_preset=request.validator_preset,
            diff=request.diff,
            dry_run=request.dry_run,
            allow_no_change=request.allow_no_change,
            create=request.create,
            old_file_path=old_file if old_file.exists() else None,
            new_file_path=new_file,
        )

        result = run_process(args)
        ok = result.get("returncode", 1) == 0

        key = f"edit:{request.path}"
        log_exec(
            f"{'sudo ' if request.sudo else ''}sentinelx-safe-edit {request.path} --mode {request.mode}",
            result.get("output", ""),
            allowed=True
        )
        context.update(key, result.get("output", ""), status="ok" if ok else "error")
        log_command(key, result.get("output", ""), source="sentinelx")

        return {
            "ok": ok,
            "path": request.path,
            "mode": request.mode,
            "sudo": request.sudo,
            "upload_id": request.upload_id,
            "command": args,
            **result
        }

    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        _cleanup_edit_upload(request.upload_id)
        
        

@app.get("/state")
async def get_state(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    token = authorization.split(" ")[1]
    if token != AGENT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    return context.get_state()
