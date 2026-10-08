#!/usr/bin/env bash
# Scan every file tracked at a commit for secrets with gitleaks.
#
# Neither built-in gitleaks mode fits a whole-tree check: `gitleaks dir .` ignores
# .gitignore (it walks .venv, node_modules, and other local state), and `gitleaks git`
# scans all of history, including long-since-removed fixtures. Exporting the committed
# tree to a temp dir and scanning that covers exactly what would be pushed.
# The exported tree carries .gitleaksignore, which gitleaks reads from the scan root.
#
# At pre-push, prek runs hooks once per pushed ref and exports that ref's commit as
# PRE_COMMIT_TO_REF (prek keeps pre-commit's env var names), so `git push origin
# other-branch` scans other-branch rather than whatever is checked out. Without it
# (CI's `prek run --all-files`), scan HEAD.
set -euo pipefail

ref=${PRE_COMMIT_TO_REF:-HEAD}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

git archive "$ref" | tar -x -C "$tmp"
cd "$tmp"
gitleaks dir . --redact --no-banner --verbose
