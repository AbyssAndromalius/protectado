#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Arnaud Ortais
# Dual-licensed: AGPL-3.0 (open source) or Commercial License — see LICENSE and LICENSE-COMMERCIAL.
# update.sh — Mise à jour manuelle de Protectado
# Version git-based : pull depuis GitHub, migration DB, restart services.
# Usage : sudo bash update.sh

set -euo pipefail

INSTALL_DIR="/opt/protectado"
BRANCH="release"

echo "╔══════════════════════════════════════╗"
echo "║   Protectado — Mise à jour          ║"
echo "╚══════════════════════════════════════╝"

if [ ! -d "$INSTALL_DIR/.git" ]; then
  echo "❌  $INSTALL_DIR n'est pas un dépôt git."
  echo "    Utilisez bootstrap.sh pour une installation initiale."
  exit 1
fi

cd "$INSTALL_DIR"

# ── Sauvegarde ───────────────────────────────────────────────────────────────
echo "→ Sauvegarde de la configuration..."
[ -f config.json ]    && cp config.json    /tmp/fw-config.backup.json && echo "   config.json sauvegardé ✓"
[ -f protectado.db ] && cp protectado.db /tmp/fw-db.backup          && echo "   protectado.db sauvegardé ✓"

# ── Mise à jour du code ───────────────────────────────────────────────────────
echo "→ Vérification des mises à jour..."
git fetch origin "$BRANCH" --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
  echo "   Déjà à jour (${LOCAL:0:8}) — rien à faire."
  exit 0
fi

echo "   Mise à jour : ${LOCAL:0:8} → ${REMOTE:0:8}"
git pull origin "$BRANCH" --quiet
echo "   Code mis à jour ✓"

# Restaurer config.json (jamais écrasé par git)
[ -f /tmp/fw-config.backup.json ] && cp /tmp/fw-config.backup.json config.json

# ── Dépendances Python ───────────────────────────────────────────────────────
echo "→ Mise à jour des dépendances Python..."
.venv/bin/pip install -q --upgrade -r requirements.txt
echo "   Dépendances OK ✓"

# ── Migration base de données ─────────────────────────────────────────────────
echo "→ Migration base de données..."
.venv/bin/python -c "import database; database.init_db(); print('   DB OK ✓')"

# ── Redémarrage ───────────────────────────────────────────────────────────────
echo "→ Redémarrage des services..."
sudo systemctl restart protectado-runner protectado-agent
sleep 3

# ── Vérification ─────────────────────────────────────────────────────────────
STATUS_RUNNER=$(systemctl is-active protectado-runner || echo "inactive")
STATUS_AGENT=$(systemctl is-active protectado-agent   || echo "inactive")

echo ""
echo "  protectado-runner : $STATUS_RUNNER"
echo "  protectado-agent  : $STATUS_AGENT"

if [ "$STATUS_AGENT" != "active" ]; then
  echo ""
  echo "⚠  L'agent n'a pas redémarré — rollback..."
  git reset --hard "$LOCAL" --quiet
  [ -f /tmp/fw-config.backup.json ] && cp /tmp/fw-config.backup.json config.json
  .venv/bin/python -c "import database; database.init_db()"
  sudo systemctl restart protectado-runner protectado-agent
  echo "   Rollback vers ${LOCAL:0:8} effectué."
  exit 1
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║        Mise à jour terminée !        ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "  Dashboard → http://$(hostname -I | awk '{print $1}'):8080"
echo ""
