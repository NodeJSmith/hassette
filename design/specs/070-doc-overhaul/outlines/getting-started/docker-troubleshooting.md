# Docker — Troubleshooting

**Status:** Rewrite from blank
**Voice mode:** Getting-started — "you" allowed, problem/solution format
**Page type:** Troubleshooting
**Reader's job:** Fix their broken Docker setup
**One sentence:** "It's not working — what do I check?"

## What was cut

The original outline had 7 H2 categories with 20+ H3 sub-problems and 25
snippets. Most readers hit 2-3 problems total. A getting-started troubleshooting
page should cover the top problems a new user encounters, not every possible
Docker failure mode. Exhaustive troubleshooting belongs in an Operating page.

## Outline

Each H2 is a symptom the reader sees. Each has: what to check, the likely
cause, the fix. No sub-categories — flat list, scannable.

### H2: Container Exits Immediately
Check logs. Most common: token not set, can't reach HA, wrong base_url.

### H2: "Connected" But Apps Don't Load
Check app directory mount, check for Python syntax errors in app files.

### H2: Dependencies Won't Install
HASSETTE__INSTALL_DEPS not set, or requirements.txt not in the mounted path.

### H2: Can't Access the Web UI
Port not published, or bound to wrong interface.

### H2: Changes to Apps Don't Take Effect
File watcher not enabled in production mode. Restart the container, or
enable hot reload (link to Operating page when it exists).

### H2: Getting Help
Link to GitHub issues, link to main troubleshooting page for non-Docker issues.

## Snippet Inventory

| Snippet | Status | Notes |
|---|---|---|
| `ts-check-logs.sh` | Keep | First diagnostic step |
| `ts-curl-ha.sh` | Keep | Test HA connectivity |
| `ts-ls-apps.sh` | Keep | Verify app mount |
| `ts-grep-errors.sh` | Keep | Find Python errors |
| `ts-dep-install-logs.sh` | Keep | Check dep installation |
| All other `ts-*` snippets | Drop | Too detailed for getting-started |

## Cross-Links

- **Links to:** Docker Setup, Dependencies, main Troubleshooting page
- **Linked from:** Docker Setup (next steps)
