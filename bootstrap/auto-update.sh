#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
#
# Script de compatibilité — délègue à /usr/local/sbin/protectado-update.
# Si ce script sécurisé n'est pas encore installé, l'installe automatiquement.
# Après la première exécution, /usr/local/sbin/protectado-update prend le relais.

set -euo pipefail

INSTALL_DIR="/opt/protectado"
SECURE="/usr/local/sbin/protectado-update"
SUDOERS="/etc/sudoers.d/protectado-update"

if [ ! -f "$SECURE" ]; then
    # Déterminer le service user (propriétaire du venv)
    SVC_USER=$(stat -c %U "$INSTALL_DIR/.venv" 2>/dev/null || echo "root")

    # Installer le script sécurisé
    sed "s|__USER__|$SVC_USER|g" \
        "$INSTALL_DIR/bootstrap/protectado-update.sh" > "$SECURE"
    chown root:root "$SECURE"
    chmod 755 "$SECURE"

    # Remplacer le sudoers par l'entrée sécurisée (script immuable)
    printf '%s ALL=(root) NOPASSWD: %s\n' "$SVC_USER" "$SECURE" > "$SUDOERS"
    chmod 440 "$SUDOERS"

    echo "[auto-update] Script sécurisé installé : $SECURE"
fi

exec "$SECURE" "$@"
