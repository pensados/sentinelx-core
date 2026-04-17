# SentinelX Core

Portable core of SentinelX for controlled command execution, uploads, editing and service actions over FastAPI.

## Local development

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
./run.sh
```

Default local port: `8092`

## Install on a server

```bash
sudo bash install.sh
```

Installed config example: `/etc/sentinelx/sentinelx.env`


## Sudo and protected files

SentinelX Core typically runs as a dedicated service user such as `sentinelx`.

- Files editable without sudo must be writable by that service user.
- To edit protected files, use `sudo: true` in the request and configure a minimal, explicit sudoers policy.
- Do **not** grant unrestricted sudo to the service. Only allow the exact commands you intend to support.
- Review ownership and permissions for log, upload, and target directories during installation.
