#!/usr/bin/env bash
# Scan every file tracked at HEAD for secrets with gitleaks.
#
# Neither built-in gitleaks mode fits a whole-tree check: `gitleaks dir .` ignores
# .gitignore (it walks .venv, node_modules, and other local state), and `gitleaks git`
# scans all of history, including long-since-removed fixtures. Exporting the committed
# tree to a temp dir and scanning that covers exactly what would be pushed.
# The exported tree carries .gitleaksignore, which gitleaks reads from the scan root.
set -euo pipefail

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

git archive HEAD | tar -x -C "$tmp"
cd "$tmp"
gitleaks dir . --redact --no-banner --verbose
