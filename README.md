# SentinelX Core

Portable core of SentinelX for controlled command execution, uploads, structured editing and service actions over FastAPI.

SentinelX Core is the generic, installable base of SentinelX. It is designed to run as a dedicated service user and expose a token-protected local HTTP API that can later be consumed by another integration layer.

## What it includes

- FastAPI-based local agent
- token-based authentication
- controlled command execution with an allowlist
- file upload endpoints
- structured file editing through the internal `sentinelx-safe-edit` tool
- basic service actions for `sentinelx`, `nginx` and `docker`
- lightweight runtime state and logging

## Repository layout

```text
.
├── agent.py
├── bin/
│   └── sentinelx-safe-edit
├── examples/
│   └── sentinelx.env.example
├── install.sh
├── LICENSE
├── README.md
├── requirements.txt
├── run.sh
└── systemd/
    └── sentinelx.service
```

## Quick start

### Basic installation

```bash
git clone git@github.com:pensados/sentinelx-core.git
cd sentinelx-core
sudo bash install.sh
```

That installs SentinelX Core into:

- `/opt/sentinelx`
- `/etc/sentinelx/sentinelx.env`
- `/var/lib/sentinelx/uploads`
- `/var/log/sentinelx`

And creates the `systemd` service:

- `sentinelx`

### Edit the installed configuration

```bash
sudo nano /etc/sentinelx/sentinelx.env
```

Example minimal configuration:

```env
SENTINEL_TOKEN=tu_token_seguro
AGENT_PORT=8091
LOG_DIR=/var/log/sentinelx
LOG_FILE=/var/log/sentinelx/sentinelx.log
LOG_EXEC_FILE=/var/log/sentinelx/exec.log
AGENT_NAME="SentinelX Core"
SENTINEL_UPLOAD_DIR=/var/lib/sentinelx/uploads
SENTINEL_SAFE_EDIT_BIN=/opt/sentinelx/bin/sentinelx-safe-edit
```

Then restart the service:

```bash
sudo systemctl restart sentinelx
sudo systemctl status sentinelx
```

## Install on a server

Run:

```bash
sudo bash install.sh
```

The installer will:

- install Python runtime dependencies from the OS
- create a dedicated system user named `sentinelx`
- copy the project to `/opt/sentinelx`
- create a virtualenv
- install Python requirements
- place the environment file at `/etc/sentinelx/sentinelx.env`
- install a `systemd` service named `sentinelx`

### Important installed paths

- code: `/opt/sentinelx`
- env file: `/etc/sentinelx/sentinelx.env`
- uploads: `/var/lib/sentinelx/uploads`
- logs: `/var/log/sentinelx`
- service: `sentinelx.service`

### Start and check the service

```bash
sudo systemctl status sentinelx
sudo journalctl -u sentinelx -n 100 --no-pager
```

## Local development

Local development defaults are intentionally different from the installed service defaults.

The local `.env` is meant for development and testing from the repository itself. The installed example env under `examples/` is meant for a real server installation.

### Run locally

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
./run.sh
```

Default local development port:

```text
8092
```

## Configuration

Installed example environment file:

```env
SENTINEL_TOKEN=changeme
AGENT_PORT=8091
LOG_DIR=/var/log/sentinelx
LOG_FILE=/var/log/sentinelx/sentinelx.log
LOG_EXEC_FILE=/var/log/sentinelx/exec.log
AGENT_NAME="SentinelX Core"
SENTINEL_UPLOAD_DIR=/var/lib/sentinelx/uploads
SENTINEL_SAFE_EDIT_BIN=/opt/sentinelx/bin/sentinelx-safe-edit
```

After editing the installed env file, reload the service:

```bash
sudo systemctl restart sentinelx
```

## First API checks

The service is expected to run locally and be called with a bearer token.

### State

```bash
curl -H "Authorization: Bearer tu_token_seguro" http://127.0.0.1:8091/state
```

### Capabilities

```bash
curl -s -H "Authorization: Bearer tu_token_seguro" http://127.0.0.1:8091/capabilities | jq
```

### Simple command execution

```bash
curl -s -X POST http://127.0.0.1:8091/exec \
  -H "Authorization: Bearer tu_token_seguro" \
  -H "Content-Type: application/json" \
  -d '{"cmd":"pwd"}'
```

## Structured editing with `sentinelx-safe-edit`

SentinelX Core includes an internal editing helper:

```text
bin/sentinelx-safe-edit
```

The `/edit` endpoint uses this helper internally. This is the preferred way to perform text replacement and structured edits instead of sending large shell one-liners.

### Successful `/edit` example

This example works when the target file is writable by the user running the service.

Create a writable test file first:

```bash
printf 'hola sentinelx core\n' | sudo tee /tmp/sentinelx-demo.txt > /dev/null
sudo chown sentinelx:sentinelx /tmp/sentinelx-demo.txt
```

Then edit it:

```bash
curl -s -X POST http://127.0.0.1:8091/edit \
  -H "Authorization: Bearer tu_token_seguro" \
  -H "Content-Type: application/json" \
  -d '{
    "path":"/tmp/sentinelx-demo.txt",
    "mode":"replace",
    "old":"hola sentinelx core",
    "new_text":"hola sentinelx core editado",
    "diff":true
  }'
```

Check the file:

```bash
cat /tmp/sentinelx-demo.txt
```

Expected result:

```text
hola sentinelx core editado
```

## Functional installation checklist

A practical first validation after installation is:

1. install SentinelX Core with `sudo bash install.sh`
2. set a real token in `/etc/sentinelx/sentinelx.env`
3. restart the service
4. verify `/state`
5. verify `/capabilities`
6. verify `/exec` with `pwd`
7. verify `/edit` on a file owned by `sentinelx`
8. only then decide whether you need privileged operations through sudoers

## Permissions model

This is the most important concept for a functional installation.

SentinelX Core typically runs as a dedicated service user such as:

```text
sentinelx
```

That means:

- commands and edits without `sudo` run with the permissions of that service user
- files editable without `sudo` must already be writable by that service user
- protected files will fail without additional privilege configuration

### What works without sudo

- editing files owned by `sentinelx`
- writing under the configured upload directory
- writing under directories explicitly granted to the service user

### What will fail without sudo

- editing files owned only by `root`
- editing files owned by another user if `sentinelx` has no write permission
- replacing content inside protected system paths such as many files under `/etc`

## Sudoers and protected files

If you want SentinelX Core to support edits or commands over protected files, document and configure that explicitly.

### Recommendation

Use a **minimal and explicit** sudoers policy.

Do **not** grant unrestricted sudo to the `sentinelx` service user.

### Good principle

Allow only the exact commands you intend to support, for example:

- `systemctl` for selected units
- `nginx -t`
- `sentinelx-safe-edit` for specific operational workflows

### Example sudoers style approach

The exact sudoers policy depends on your server, but the principle should be narrow. For example, prefer allowing only specific commands instead of broad root access.

### Example request with sudo enabled

```bash
curl -s -X POST http://127.0.0.1:8091/edit \
  -H "Authorization: Bearer tu_token_seguro" \
  -H "Content-Type: application/json" \
  -d '{
    "path":"/etc/nginx/sites-available/example.conf",
    "sudo":true,
    "mode":"replace",
    "old":"old_value",
    "new_text":"new_value",
    "diff":true
  }'
```

### Important note

Using `"sudo": true` in the request is **not enough by itself**.

The service user must also be allowed to execute the corresponding privileged command through sudoers.

### Installation guidance

When installing SentinelX Core on a real server, review all of these:

- ownership of `/var/lib/sentinelx/uploads`
- ownership of `/var/log/sentinelx`
- ownership and permissions of target files you expect to edit without sudo
- any sudoers rules required for protected operations

## Logging

Installed defaults:

- main log: `/var/log/sentinelx/sentinelx.log`
- exec log: `/var/log/sentinelx/exec.log`

Useful checks:

```bash
sudo tail -n 100 /var/log/sentinelx/sentinelx.log
sudo tail -n 100 /var/log/sentinelx/exec.log
sudo journalctl -u sentinelx -n 100 --no-pager
```

## Troubleshooting

### Service does not start

```bash
sudo systemctl status sentinelx
sudo journalctl -u sentinelx -n 100 --no-pager
```

### Token works but `/edit` fails

Most of the time this is a permissions issue on the target file or directory. First verify that the file is writable by the `sentinelx` user. If not, either adjust ownership/permissions or use a controlled sudoers setup.

### `/exec` works but logs are empty

Verify:

- `/var/log/sentinelx` exists
- ownership is correct for the `sentinelx` user
- the environment file points to the expected log paths

## Current scope

SentinelX Core is the generic base. It does not try to ship your whole personal infrastructure profile.

This repository is intended to remain portable and reusable.

## Security notes

- bind it locally unless you have a reason to expose it
- use a strong token
- put a reverse proxy and stronger controls in front of it if you expose it beyond localhost
- prefer explicit allowlists and least privilege
- review every privileged capability before enabling it in production
