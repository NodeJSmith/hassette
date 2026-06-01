# Docker — Troubleshooting

**Status:** Exists (350 lines), symptom-lookup format, voice polish needed
**Voice mode:** Getting-started — "you" allowed, problem/solution format

## Outline

Pure symptom-lookup for Docker-specific issues. Each H2 is a symptom category, each H3 is a specific problem with cause and fix.

### H2: Container Won't Start
#### H3: Check the Logs
#### H3: Token Not Set
#### H3: Can't Reach Home Assistant
#### H3: Permission Errors

### H2: Apps Not Loading
#### H3: Check App Discovery
#### H3: Verify App Directory Configuration
#### H3: Check for Python Errors
#### H3: Verify App Configuration

### H2: Dependency Installation Fails
#### H3: Check Installation Output
#### H3: Dependency Conflicts
#### H3: pyproject.toml Not Found
#### H3: Project Has pyproject.toml But Dependencies Don't Install
#### H3: requirements.txt Not Found
#### H3: Version Conflicts
#### H3: Import Errors at Runtime

### H2: Health Check Failing
Symptoms, solutions.

### H2: Hot Reload Not Working
Requirements, configuration, volume mount verification.

### H2: Import Errors
#### H3: Package Not Found
#### H3: Hassette Module Not Found

### H2: Performance Issues
#### H3: Slow Container Startup
#### H3: High Memory Usage

### H2: Getting Help

## Snippet Inventory

All existing `ts-*` snippets (25+) are keeps — they show diagnostic commands and config fixes. These are Docker-specific troubleshooting commands.

| Snippet | Status |
|---|---|
| `ts-app-config.toml` | Keep |
| `ts-app-dir-src-env.yml` | Keep |
| `ts-app-dir-toml.toml` | Keep |
| `ts-cat-pyproject.sh` | Keep |
| `ts-check-constraints.sh` | Keep |
| `ts-check-logs.sh` | Keep |
| `ts-check-logs-tail.sh` | Keep |
| `ts-chmod.sh` | Keep |
| `ts-curl-ha.sh` | Keep |
| `ts-dep-conflict.txt` | Keep |
| `ts-dep-install-logs.sh` | Keep |
| `ts-diagnostics.sh` | Keep |
| `ts-find-requirements.sh` | Keep |
| `ts-grep-errors.sh` | Keep |
| `ts-health-check-long-start.yml` | Keep |
| `ts-health-check.sh` | Keep |
| `ts-hot-reload.toml` | Keep |
| `ts-ls-apps.sh` | Keep |
| `ts-memory-limit.yml` | Keep |
| `ts-pin-hassette-pyproject.toml` | Keep |
| `ts-project-dir-env.yml` | Keep |
| `ts-pyproject-dep.toml` | Keep |
| `ts-uv-cache-vol.yml` | Keep |
| `ts-uv-relock.sh` | Keep |
| `ts-vol-mount.yml` | Keep |

## Cross-Links

- **Links to:** Docker Setup, Dependencies, Image Tags
- **Linked from:** Docker Setup, Dependencies (troubleshooting links)
