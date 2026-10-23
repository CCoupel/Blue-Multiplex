#!/usr/bin/env bash
# CI_CMD — script unique de la CI (contrat infra C11).
# Appele par .github/workflows/ci-branch.yml, .github/workflows/release.yml, et en local par qa/deploy.
# Les commandes sont lues dans .claude/project-config.json : aucune etape n'existe uniquement en CI ou en local.
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIG=.claude/project-config.json
cmd() { jq -r --arg k "$1" '.commands[$k] // ""' "$CONFIG"; }

step() { echo; echo "=== $1 ==="; }

step "deps"      ; uv sync --locked --all-groups
step "lint"      ; bash -c "$(cmd lint)"
step "typecheck" ; bash -c "$(cmd typecheck)"
# Tests : meme commande que commands.coverage ; les tests marques `hardware` (BlueZ/PipeWire reels)
# sont exclus partout (CI et local) — ils s'executent sur le Pi de qualif via /qa.
step "tests"     ; bash -c "$(cmd coverage) -m 'not hardware' --cov-fail-under=$(jq -r '.testing.coverage_min // 0' "$CONFIG")"
step "audit"     ; bash -c "$(cmd audit)"
step "build"     ; rm -rf dist && bash -c "$(cmd build)"
# Lockfile runtime haché (dépendances de production seulement, sans btmux lui-même : installé depuis la wheel) — utilisé par
# le postinst du .deb et par deploy.sh (`pip install --require-hashes --no-deps -r`).
step "lockfile"  ; uv export --no-dev --frozen --hashes --no-emit-project --format requirements-txt -o dist/requirements.lock.txt

echo; echo "CI OK — artefacts dans dist/ :"; ls -1 dist/
