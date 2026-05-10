#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
# auto-update.sh — Mise à jour automatique de Protectado depuis git
# Appelé par cron (/etc/cron.d/protectado) chaque nuit à 3h00.
# Exécuté en tant que root.

set -euo pipefail

INSTALL_DIR="/opt/protectado"
BRANCH="release"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "[$TIMESTAMP] $*"; }

# ── Vérifier qu'il y a des mises à jour ──────────────────────────────────────
cd "$INSTALL_DIR"

git fetch origin "$BRANCH" --quiet 2>&1 || {
  log "WARN  Impossible de joindre GitHub — pas de mise à jour"
  exit 0
}

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
  log "OK    Aucune mise à jour ($LOCAL)"
  exit 0
fi

log "INFO  Mise à jour disponible : ${LOCAL:0:8} → ${REMOTE:0:8}"

# ── Sauvegardes ──────────────────────────────────────────────────────────────
[ -f config.json ]      && cp config.json      /tmp/fw-config.backup.json
[ -f protectado.db ]   && cp protectado.db   /tmp/fw-db.backup

# ── Pull ─────────────────────────────────────────────────────────────────────
git pull origin "$BRANCH" --quiet 2>&1
log "INFO  Code mis à jour"

# Restaurer config.json immédiatement (jamais écrasé par git)
[ -f /tmp/fw-config.backup.json ] && cp /tmp/fw-config.backup.json config.json

# ── Dépendances Python ───────────────────────────────────────────────────────
.venv/bin/pip install -q --upgrade -r requirements.txt 2>&1
log "INFO  Dépendances Python OK"

# ── Migration base de données ─────────────────────────────────────────────────
.venv/bin/python -c "import database; database.init_db()" 2>&1
log "INFO  Migration DB OK"

# ── Redémarrage des services ──────────────────────────────────────────────────
systemctl restart protectado-runner protectado-agent 2>&1
sleep 5

# ── Vérification + rollback si échec ─────────────────────────────────────────
if ! systemctl is-active --quiet protectado-agent; then
  log "ERROR Service protectado-agent inactif après mise à jour — rollback"

  git reset --hard "$LOCAL" --quiet 2>&1
  [ -f /tmp/fw-config.backup.json ] && cp /tmp/fw-config.backup.json config.json
  [ -f /tmp/fw-db.backup ]          && cp /tmp/fw-db.backup protectado.db

  .venv/bin/python -c "import database; database.init_db()" 2>&1
  systemctl restart protectado-runner protectado-agent 2>&1
  sleep 3

  if systemctl is-active --quiet protectado-agent; then
    log "INFO  Rollback réussi — retour à ${LOCAL:0:8}"
  else
    log "CRIT  Rollback échoué — intervention manuelle requise"
    log "CRIT  journalctl -u protectado-agent -n 50"
  fi
  exit 1
fi

log "OK    Mise à jour terminée — version ${REMOTE:0:8}"
