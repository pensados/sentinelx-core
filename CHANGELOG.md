# Changelog

All notable changes to this project will be documented in this file.

The format is inspired by Keep a Changelog and the project uses Git tags for released versions.

## [v0.1.0] - 2026-04-17

Initial public release of SentinelX Core.

### Added

- portable `sentinelx-core` repository separated from the personal SentinelX instance
- FastAPI-based core agent with token authentication
- controlled command execution with allowlisted commands
- structured editing support through the internal `bin/sentinelx-safe-edit` helper
- upload endpoints and temporary upload handling
- service metadata and capabilities output
- `install.sh` for server installation
- `run.sh` for local development
- `requirements.txt` for Python dependencies
- `systemd/sentinelx.service` example unit
- `examples/sentinelx.env.example` for installed configuration
- MIT license
- initial public README with installation, quick start, permissions model, sudoers guidance and working curl examples

### Changed

- removed personal infrastructure paths and project-specific references from the core version
- changed the local development default port for the core to avoid collision with the personal SentinelX instance
- internalized the edit helper into the repository as `bin/sentinelx-safe-edit`
- improved documentation around service ownership, permissions and protected file editing

### Notes

- this release is intended as the generic base of SentinelX, not as a full personal infrastructure profile
- protected operations still require explicit sudoers configuration on the target server
