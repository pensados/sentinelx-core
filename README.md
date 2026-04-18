# SentinelX Core

**Controlled server agent over HTTP. Command allowlist. Structured editing. Upload. Script execution. Service management.**

SentinelX Core runs as a dedicated service user on your server and exposes a token-authenticated local HTTP API. Any integration layer — an MCP bridge, a script, a CI job — can call it to perform controlled operations without giving that layer unrestricted shell access.

---

## How it works

```
Your integration layer (MCP, script, CI...)
        │
        │  HTTP  +  Bearer token
        ▼
  SentinelX Core  (local, port 8091)
        │
        ├─ /exec        → runs allowed commands only
        ├─ /edit        → structured file edits via sentinelx-safe-edit
        ├─ /script/run  → executes temporary bash or python3 scripts
        ├─ /service     → start / stop / restart / status for registered services
        ├─ /upload      → file upload (simple and chunked)
        ├─ /capabilities → allowed commands, services, locations, playbooks
        └─ /state       → runtime state snapshot
```

The key constraint: **`/exec` only runs commands that are explicitly in `ALLOWED_COMMANDS`**. Everything else is rejected.

---

## What it includes

- FastAPI-based local agent
- Token authentication on every endpoint
- Command execution with an explicit allowlist
- Structured file editing via `bin/sentinelx-safe-edit` (no shell quoting, supports replace / regex / replace-block / append / prepend / write, with dry-run, diff and automatic backup)
- File upload endpoints (single and chunked, with SHA256 verification)
- Service action registry (`nginx`, `docker`, `sentinelx`) with per-action commands and risk levels
- Temporary script execution (bash and python3, with cleanup, cwd, env and sudo support)
- `/capabilities` endpoint exposing allowed commands, categories, PATH\_INDEX, playbooks and embedded help — useful for AI agents and MCP integrations
- Lightweight runtime state and structured exec logging

---

## Repository layout

```
.
├── agent.py
├── bin/
│   └── sentinelx-safe-edit
├── config.py
├── context.py
├── logger.py
├── logger_exec.py
├── examples/
│   └── sentinelx.env.example
├── install.sh
├── run.sh
├── requirements.txt
└── systemd/
    └── sentinelx.service
```

---

## Quick start

### Install on a server

```bash
git clone https://github.com/pensados/sentinelx-core.git
cd sentinelx-core
sudo bash install.sh
```

The installer:

- creates a dedicated `sentinelx` system user
- installs the project to `/opt/sentinelx`
- creates a Python virtualenv and installs dependencies
- places the env file at `/etc/sentinelx/sentinelx.env`
- installs and enables a `systemd` service named `sentinelx`

### Configure

```bash
sudo nano /etc/sentinelx/sentinelx.env
```

Minimum required:

```env
SENTINEL_TOKEN=your_strong_token_here
AGENT_PORT=8091
LOG_DIR=/var/log/sentinelx
LOG_FILE=/var/log/sentinelx/sentinelx.log
LOG_EXEC_FILE=/var/log/sentinelx/exec.log
SENTINEL_UPLOAD_DIR=/var/lib/sentinelx/uploads
SENTINEL_SAFE_EDIT_BIN=/opt/sentinelx/bin/sentinelx-safe-edit
```

Then restart:

```bash
sudo systemctl restart sentinelx
sudo systemctl status sentinelx
```

### Local development

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
./run.sh
```

Default local port: **8092** (intentionally different from the installed default to avoid conflicts).

---

## API examples

Replace `YOUR_TOKEN` and `YOUR_PORT` with your actual values.

### Check state

```bash
curl -s -H "Authorization: Bearer YOUR_TOKEN" \
  http://127.0.0.1:YOUR_PORT/state | jq
```

### List capabilities

```bash
curl -s -H "Authorization: Bearer YOUR_TOKEN" \
  http://127.0.0.1:YOUR_PORT/capabilities | jq
```

### Execute a command

```bash
curl -s -X POST http://127.0.0.1:YOUR_PORT/exec \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cmd": "df -h"}'
```

### Edit a file (structured, no shell quoting)

```bash
curl -s -X POST http://127.0.0.1:YOUR_PORT/edit \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/etc/nginx/sites-available/example.conf",
    "sudo": true,
    "mode": "replace",
    "old": "server_name old.example.com;",
    "new_text": "server_name new.example.com;",
    "diff": true,
    "validator_preset": "nginx"
  }'
```

### Run a temporary script

```bash
curl -s -X POST http://127.0.0.1:YOUR_PORT/script/run \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "interpreter": "bash",
    "content": "#!/bin/bash\necho hello from sentinelx\nuptime",
    "timeout": 30
  }'
```

### Service action

```bash
curl -s -X POST http://127.0.0.1:YOUR_PORT/service \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"service": "nginx", "action": "reload"}'
```

---

## Permissions model

SentinelX Core runs as the `sentinelx` system user. This means:

- commands without `sudo` run with the permissions of that user
- files editable without `sudo` must be writable by `sentinelx`
- protected files (e.g. under `/etc`) require explicit `sudoers` rules

### What works without sudo

- editing files owned by `sentinelx`
- writing under `/var/lib/sentinelx/uploads`
- reading most of the filesystem (subject to normal Unix permissions)

### What requires sudo

- editing files owned by `root` or another user
- reloading/restarting system services
- commands like `nginx -t` that touch system paths

---

## Sudoers setup

**Never grant unrestricted sudo to the `sentinelx` user.**

Use a narrow, explicit policy:

```bash
sudo visudo -f /etc/sudoers.d/sentinelx-core
```

Example minimal content:

```sudoers
Cmnd_Alias SENTINELX_SYSTEMD = \
    /bin/systemctl status nginx, \
    /bin/systemctl restart nginx, \
    /bin/systemctl reload nginx

Cmnd_Alias SENTINELX_NGINX   = /usr/sbin/nginx -t
Cmnd_Alias SENTINELX_EDIT    = /opt/sentinelx/bin/sentinelx-safe-edit

sentinelx ALL=(root) NOPASSWD: SENTINELX_SYSTEMD, SENTINELX_NGINX, SENTINELX_EDIT
```

Verify binary paths first:

```bash
which systemctl
which nginx
```

Validate and fix permissions:

```bash
sudo visudo -cf /etc/sudoers.d/sentinelx-core
sudo chmod 440 /etc/sudoers.d/sentinelx-core
```

---

## Extending the allowlist

The command allowlist is defined in `ALLOWED_COMMANDS` in `agent.py`. Add only commands you intend to expose. Prefer broad base commands (`docker`, `git`) over redundant specific variants.

After any change to `agent.py`, restart the service:

```bash
sudo systemctl restart sentinelx
```

---

## Extending the service registry

`SERVICE_ACTIONS` in `agent.py` defines which services can be controlled and which actions are allowed per service. Add an entry with:

- `unit`: the systemd unit name
- `actions`: list of allowed actions (`status`, `start`, `stop`, `restart`, `reload`, `validate`)
- `action_commands`: the exact command for each action
- `risk`: `low`, `medium`, or `high` (informational, passed through `/capabilities`)

---

## Logging

Installed log locations:

| File | Content |
|------|---------|
| `/var/log/sentinelx/sentinelx.log` | Main service log |
| `/var/log/sentinelx/exec.log` | Structured exec audit log |

Useful checks:

```bash
sudo tail -f /var/log/sentinelx/exec.log
sudo journalctl -u sentinelx -n 100 --no-pager
```

---

## Functional validation checklist

After installation, verify in order:

1. `sudo systemctl status sentinelx` → service is running
2. `/state` responds with a valid JSON object
3. `/capabilities` lists the expected allowed commands
4. `/exec` with `{"cmd": "pwd"}` returns a result
5. `/edit` on a file owned by `sentinelx` succeeds without sudo
6. `/edit` on a protected file succeeds with `"sudo": true` (if sudoers is configured)
7. `/service` for `nginx` status works

---

## Troubleshooting

**Service does not start**
```bash
sudo journalctl -u sentinelx -n 50 --no-pager
```

**`/edit` fails with permission error**
The target file is not writable by `sentinelx`. Either change ownership, or use `"sudo": true` with the appropriate sudoers rule.

**`/exec` is blocked**
The command is not in `ALLOWED_COMMANDS`. Add it to `agent.py` and restart.

**Logs are empty**
Verify that `/var/log/sentinelx` exists and is owned by the `sentinelx` user, and that the env file points to the correct log paths.

---

## Security notes

- Bind to `127.0.0.1` unless you have a specific reason to expose it
- Use a strong, randomly generated `SENTINEL_TOKEN`
- If you expose the agent beyond localhost, put an authenticated reverse proxy in front
- Review `ALLOWED_COMMANDS` and `SERVICE_ACTIONS` before deploying
- Use the narrowest possible sudoers policy

---

## Related

- **[sentinelx-core-mcp](https://github.com/pensados/sentinelx-core-mcp)** — MCP/OAuth bridge for SentinelX Core. Exposes the agent as MCP tools with OIDC token validation, ready for Claude, ChatGPT and other MCP clients.

---

## License

MIT
