#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
#
# Template installé par bootstrap dans /usr/local/sbin/protectado-update
# Propriété : root:root 755 — jamais écrasé par git pull
#
# Modèle de sécurité :
#   - Seul systemctl restart s'exécute en root
#   - git, pip, python tournent en tant que __USER__ (service user)
#   - /usr/local/sbin/protectado-update est hors de portée du service user
#   - Pour mettre à jour CE script, relancer bootstrap.sh

set -euo pipefail

INSTALL_DIR="/opt/protectado"
BRANCH="main"
SVC_USER="__USER__"
LOG="/var/log/fw-update.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "[$TIMESTAMP] $*" | tee -a "$LOG"; }

# Toutes les opérations sur le code tournent en tant que SVC_USER
as_user() { sudo -u "$SVC_USER" -- "$@"; }

log "INFO  Vérification des mises à jour..."

cd "$INSTALL_DIR"

as_user git fetch origin "$BRANCH" --quiet 2>&1 || {
    log "WARN  Impossible de joindre le dépôt — pas de mise à jour"
    exit 0
}

LOCAL=$(as_user git rev-parse HEAD)
REMOTE=$(as_user git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    log "OK    Déjà à jour (${LOCAL:0:8})"
    exit 0
fi

log "INFO  Mise à jour disponible : ${LOCAL:0:8} → ${REMOTE:0:8}"

# Sauvegarde
BACKUP="/tmp/protectado-bk-$(date +%s)"
mkdir -p "$BACKUP"
[ -f data/config.json ]    && cp data/config.json    "$BACKUP/"
[ -f data/protectado.db ]  && cp data/protectado.db  "$BACKUP/"

# Pull — hooks git tournent en tant que SVC_USER
as_user git pull origin "$BRANCH" --quiet 2>&1
log "INFO  Code mis à jour"

# Restaurer config (jamais écrasée par git)
[ -f "$BACKUP/config.json" ] && cp "$BACKUP/config.json" data/config.json

# Dépendances et migration — tout en tant que SVC_USER, jamais root
as_user .venv/bin/pip install -q --upgrade -r requirements.txt 2>&1
log "INFO  Dépendances Python OK"

as_user .venv/bin/python -c "
import sys; sys.path.insert(0, '$INSTALL_DIR')
import database; database.init_db()
" 2>&1
log "INFO  Migration DB OK"

# Mettre à jour les fichiers systemd depuis le repo (applique les changements de templates)
for unit in protectado-update.service protectado-update.path; do
    if [ -f "$INSTALL_DIR/$unit" ]; then
        sed "s|__WORKDIR__|$INSTALL_DIR|g" "$INSTALL_DIR/$unit" \
            > "/etc/systemd/system/$unit"
    fi
done
systemctl daemon-reload 2>&1

# Seules opérations nécessitant root
systemctl restart protectado-runner protectado-agent 2>&1
sleep 5

# Vérification + rollback
if ! systemctl is-active --quiet protectado-agent; then
    log "ERROR Service inactif après mise à jour — rollback vers ${LOCAL:0:8}"
    as_user git reset --hard "$LOCAL" --quiet 2>&1
    [ -f "$BACKUP/config.json" ]   && cp "$BACKUP/config.json"   data/config.json
    [ -f "$BACKUP/protectado.db" ] && cp "$BACKUP/protectado.db" data/protectado.db
    as_user .venv/bin/python -c "
import sys; sys.path.insert(0, '$INSTALL_DIR')
import database; database.init_db()
" 2>&1
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
